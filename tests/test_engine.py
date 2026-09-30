"""Engine tests. Plain calculations on made-up rows; no network is involved."""

import pytest

from app.engine import (
    Engine, HighLow, Indicator, MaxDrawdown, MovingAverage, PriceChange, SeriesSampler, Trend, Volatility,
)


def row(close, t=0, high=None, low=None):
    return {"open_time": t, "close": close,
            "high": close if high is None else high,
            "low": close if low is None else low}


def feed(indicator, closes):
    for i, close in enumerate(closes):
        indicator.update(row(close, t=i))
    return indicator.result()


def test_all_indicators_inherit_indicator():
    for cls in (PriceChange, HighLow, MovingAverage, Trend, Volatility, MaxDrawdown, SeriesSampler):
        assert issubclass(cls, Indicator)


def test_price_change():
    assert feed(PriceChange(), [100, 110, 99]) == {
        "first_close": 100, "last_close": 99, "change_pct": pytest.approx(-1.0),
    }


def test_high_low():
    indicator = HighLow()
    indicator.update(row(100, high=105, low=95))
    indicator.update(row(101, high=110, low=97))
    assert indicator.result() == {"high": 110, "low": 95}


def test_moving_average_needs_a_full_window():
    assert feed(MovingAverage(3), [1, 2]) == {"sma_3": None}
    assert feed(MovingAverage(3), [1, 2, 3, 4]) == {"sma_3": 3.0}


def test_trend_up_and_down():
    assert feed(Trend(short=2, long=3), [1, 2, 3, 4])["trend"] == "up"
    assert feed(Trend(short=2, long=3), [4, 3, 2, 1])["trend"] == "down"


def test_volatility():
    # Returns are +10% and -10%, so the sample standard deviation is sqrt(0.02) = 14.14%.
    assert feed(Volatility(), [100, 110, 99])["volatility_pct"] == pytest.approx(14.1421356, rel=1e-6)


def test_max_drawdown():
    # Peak 120, lowest point after it 90: a 25% drop.
    assert feed(MaxDrawdown(), [100, 120, 90, 130]) == {"max_drawdown_pct": pytest.approx(25.0)}


def test_series_sampler_keeps_even_spacing_and_the_last_row():
    result = feed(SeriesSampler(max_points=4), list(range(10)))
    assert [p["t"] for p in result["series"]] == [0, 4, 8, 9]


def test_series_sampler_memory_stays_bounded():
    sampler = SeriesSampler(max_points=200)
    for i in range(100_000):
        sampler.update(row(1.0, t=i))
    assert len(sampler.points) <= 200
    assert len(sampler.result()["series"]) <= 201


def test_engine_runs_a_generator_and_merges_results():
    rows = (row(100 + i, t=i) for i in range(60))  # a generator, not a list
    result = Engine().run(rows)
    assert result["rows"] == 60
    assert result["first_close"] == 100
    assert result["last_close"] == 159
    assert result["trend"] == "up"
    assert result["max_drawdown_pct"] == 0.0
    for key in ("high", "low", "volatility_pct", "sma_20", "sma_50", "series"):
        assert key in result


def test_engine_with_no_rows():
    result = Engine().run(iter([]))
    assert result["rows"] == 0
    assert result["change_pct"] is None
    assert result["trend"] is None
    assert result["series"] == []


def test_engine_with_custom_indicators():
    result = Engine([PriceChange()]).run([row(1), row(2)])
    assert result == {"rows": 2, "first_close": 1, "last_close": 2, "change_pct": 100.0}
