"""Client for Binance's public market-data API (no API key needed)."""

import json
from collections.abc import Iterator

from app.clients.base import BaseClient

# Candle sizes Binance accepts for /api/v3/klines.
INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}


class BinanceClient(BaseClient):
    name = "binance"
    base_url = "https://data-api.binance.vision"
    default_symbols = ["BTC", "ETH"]
    has_history = True
    # Binance trades against USDT, not USD.
    quotes = {"usd": "USDT"}
    # Most rows Binance returns per klines request.
    page_size = 1000

    def _pair(self, symbol: str, currency: str) -> str:
        """"btc" + "usd" -> "BTCUSDT"."""
        quote = self.quotes.get(currency.lower(), currency.upper())
        return f"{symbol.upper()}{quote}"

    def get_prices(self, symbols: list[str], currency: str = "usd") -> list[dict]:
        """Fetch current prices for asset symbols (e.g. "BTC", "ETH")."""
        pair_to_symbol = {self._pair(s, currency): s.upper() for s in symbols}
        data = self._get(
            "/api/v3/ticker/price",
            params={"symbols": json.dumps(list(pair_to_symbol), separators=(",", ":"))},
        )
        # Binance returns [{"symbol": "BTCUSDT", "price": "67000.01"}, ...].
        return [
            {
                "symbol": pair_to_symbol[item["symbol"]],
                "currency": currency,
                "price": float(item["price"]),
                "source": self.name,
            }
            for item in data
            if item["symbol"] in pair_to_symbol
        ]

    # AI-assisted: drafted with an AI assistant for this reference solution.
    # In your own project, say here what Copilot suggested and what you changed or checked.
    # Pattern: a generator that pages through an API with `yield from`.
    def iter_history(self, symbol: str, currency: str = "usd", interval: str = "1h",
                     start_ms: int | None = None, end_ms: int | None = None) -> Iterator[dict]:
        """Yield candles one at a time, fetching one page of up to `page_size` rows at a time.

        Only the current page is held in memory. The next page is requested only
        after every row of the current one has been used.
        """
        params = {"symbol": self._pair(symbol, currency), "interval": interval, "limit": self.page_size}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms

        while True:
            page = self._get("/api/v3/klines", params=params)
            if not page:
                return
            yield from self._parse_klines(page, symbol, currency)
            if len(page) < self.page_size:
                return
            # Next page starts right after the last candle's open time.
            params["startTime"] = page[-1][0] + 1

    def _parse_klines(self, page: list[list], symbol: str, currency: str) -> Iterator[dict]:
        """Turn raw kline arrays into dicts, one row at a time.

        Each raw row is [open_time, open, high, low, close, volume, close_time, ...].
        """
        for row in page:
            yield {
                "symbol": symbol.upper(),
                "currency": currency,
                "open_time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "source": self.name,
            }
