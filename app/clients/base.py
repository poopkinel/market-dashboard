"""Shared base class for all external API clients."""

from abc import ABC, abstractmethod
from collections.abc import Iterator

import requests


class APIClientError(Exception):
    """Raised when a request to an external API fails."""


class BaseClient(ABC):
    """Holds the HTTP logic that every API client needs.

    Subclasses set `name`, `base_url` and `default_symbols` and implement `get_prices`.
    They call `self._get(...)` instead of calling `requests` directly.
    """

    name: str = "base"
    base_url: str = ""
    timeout: float = 10.0
    default_symbols: list[str] = []
    has_history: bool = False  # True for clients that implement iter_history

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        """Send a GET request and return the parsed JSON body."""
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise APIClientError(f"{self.name}: request to {url} failed: {exc}") from exc
        except ValueError as exc:
            raise APIClientError(f"{self.name}: response from {url} is not valid JSON") from exc

    @abstractmethod
    def get_prices(self, symbols: list[str], currency: str = "usd") -> list[dict]:
        """Return current prices as a list of dicts:
        {"symbol": str, "currency": str, "price": float, "source": str}
        """

    def iter_history(self, symbol: str, currency: str = "usd", interval: str = "1h",
                     start_ms: int | None = None, end_ms: int | None = None) -> Iterator[dict]:
        """Yield historical price rows one at a time, oldest first:
        {"symbol": str, "currency": str, "open_time": int, "open": float, "high": float,
         "low": float, "close": float, "volume": float, "source": str}

        Clients that have no historical data keep this default.
        """
        raise NotImplementedError(f"{self.name} does not provide historical data")
