"""Processing engine: turns a stream of candles into summary numbers for the dashboard.

Each indicator looks at one row at a time and keeps only what it needs, so the
engine can process any number of rows (for example, straight from a generator)
with memory that does not grow with the number of rows.
"""

import math
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterable


class Indicator(ABC):
    """Base class for all indicators."""

    @abstractmethod
    def update(self, row: dict) -> None:
        """Take in one candle row."""

    @abstractmethod
    def result(self) -> dict:
        """Return this indicator's numbers as a dict (values are None if there was no data)."""


class PriceChange(Indicator):
    """First close, last close, and the change between them in percent."""

    def __init__(self):
        self.first = None
        self.last = None

    def update(self, row):
        if self.first is None:
            self.first = row["close"]
        self.last = row["close"]

    def result(self):
        change = None
        if self.first:  # None or 0 -> no percentage
            change = (self.last - self.first) / self.first * 100
        return {"first_close": self.first, "last_close": self.last, "change_pct": change}


class HighLow(Indicator):
    """Highest high and lowest low over the whole period."""

    def __init__(self):
        self.high = None
        self.low = None

    def update(self, row):
        self.high = row["high"] if self.high is None else max(self.high, row["high"])
        self.low = row["low"] if self.low is None else min(self.low, row["low"])

    def result(self):
        return {"high": self.high, "low": self.low}


class MovingAverage(Indicator):
    """Average close over the last `window` rows (a simple moving average)."""

    def __init__(self, window: int):
        self.window = window
        self.closes = deque(maxlen=window)  # old values fall off the left end

    def update(self, row):
        self.closes.append(row["close"])

    def value(self) -> float | None:
        if len(self.closes) < self.window:
            return None
        return sum(self.closes) / self.window

    def result(self):
        return {f"sma_{self.window}": self.value()}


class Trend(Indicator):
    """Compares a short and a long moving average: short above long means "up"."""

    def __init__(self, short: int = 20, long: int = 50):
        self.short = MovingAverage(short)
        self.long = MovingAverage(long)

    def update(self, row):
        self.short.update(row)
        self.long.update(row)

    def result(self):
        short, long = self.short.value(), self.long.value()
        if short is None or long is None:
            trend = None
        elif short > long:
            trend = "up"
        elif short < long:
            trend = "down"
        else:
            trend = "flat"
        return {**self.short.result(), **self.long.result(), "trend": trend}


# AI-assisted: drafted with an AI assistant for this reference solution.
# In your own project, say here what Copilot suggested and what you changed or checked.
# Pattern: Welford's running mean and variance.
class Volatility(Indicator):
    """Standard deviation of the per-candle returns, in percent.

    Uses Welford's method, which updates the mean and variance one value at a
    time instead of keeping every return in a list.
    """

    def __init__(self):
        self.prev_close = None
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0  # running sum of squared distances from the mean

    def update(self, row):
        close = row["close"]
        if self.prev_close:
            ret = close / self.prev_close - 1
            self.n += 1
            delta = ret - self.mean
            self.mean += delta / self.n
            self.m2 += delta * (ret - self.mean)
        self.prev_close = close

    def result(self):
        if self.n < 2:
            return {"volatility_pct": None}
        return {"volatility_pct": math.sqrt(self.m2 / (self.n - 1)) * 100}


class MaxDrawdown(Indicator):
    """Largest drop from an earlier peak close, in percent (25.0 means it fell 25% from a high)."""

    def __init__(self):
        self.peak = None
        self.max_dd = None

    def update(self, row):
        close = row["close"]
        if self.peak is None or close > self.peak:
            self.peak = close
        dd = (self.peak - close) / self.peak * 100 if self.peak else 0.0
        self.max_dd = dd if self.max_dd is None else max(self.max_dd, dd)

    def result(self):
        return {"max_drawdown_pct": self.max_dd}


# AI-assisted: drafted with an AI assistant for this reference solution.
# In your own project, say here what Copilot suggested and what you changed or checked.
# Pattern: keeping a bounded, evenly spaced sample of a stream.
class SeriesSampler(Indicator):
    """Keeps a thinned-out list of (time, close) points for the dashboard chart.

    It keeps every `step`-th row. When the list grows past `max_points`, it drops
    every other point and doubles `step`, so the list stays evenly spaced and never
    holds more than `max_points` points, however many rows come in. The latest row
    is added at the end so the chart always reaches the present.
    """

    def __init__(self, max_points: int = 200):
        self.max_points = max_points
        self.step = 1
        self.count = 0
        self.points = []
        self.last = None

    def update(self, row):
        point = {"t": row["open_time"], "close": row["close"]}
        if self.count % self.step == 0:
            self.points.append(point)
            if len(self.points) > self.max_points:
                self.points = self.points[::2]
                self.step *= 2
        self.count += 1
        self.last = point

    def result(self):
        series = list(self.points)
        if self.last is not None and (not series or series[-1] is not self.last):
            series.append(self.last)
        return {"series": series}


def default_indicators() -> list[Indicator]:
    return [PriceChange(), HighLow(), Volatility(), MaxDrawdown(), Trend(20, 50), SeriesSampler(200)]


class Engine:
    """Runs every row through a list of indicators and collects their results."""

    def __init__(self, indicators: list[Indicator] | None = None):
        self.indicators = indicators if indicators is not None else default_indicators()
        self.rows = 0

    def update(self, row: dict) -> None:
        self.rows += 1
        for indicator in self.indicators:
            indicator.update(row)

    def result(self) -> dict:
        out = {"rows": self.rows}
        for indicator in self.indicators:
            out.update(indicator.result())
        return out

    def run(self, rows: Iterable[dict]) -> dict:
        """Process all rows (a list or a generator) and return the result."""
        for row in rows:
            self.update(row)
        return self.result()
