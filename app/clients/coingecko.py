"""Client for the CoinGecko keyless public API."""

from app.clients.base import BaseClient


class CoinGeckoClient(BaseClient):
    name = "coingecko"
    base_url = "https://api.coingecko.com/api/v3"
    default_symbols = ["bitcoin", "ethereum"]

    def get_prices(self, symbols: list[str], currency: str = "usd") -> list[dict]:
        """Fetch current prices for CoinGecko coin ids (e.g. "bitcoin", "ethereum")."""
        data = self._get(
            "/simple/price",
            params={"ids": ",".join(symbols), "vs_currencies": currency},
        )
        # CoinGecko returns {"bitcoin": {"usd": 67000}, ...}.
        # Coins it does not recognise are left out of the response.
        return [
            {
                "symbol": coin_id,
                "currency": currency,
                "price": float(values[currency]),
                "source": self.name,
            }
            for coin_id, values in data.items()
            if currency in values
        ]
