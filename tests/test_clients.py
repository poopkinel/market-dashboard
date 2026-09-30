"""Client tests. `requests.get` is mocked, so no network is used."""

import pytest
import requests

from app.clients import APIClientError, BaseClient, CoinGeckoClient


def test_coingecko_inherits_base_client():
    assert issubclass(CoinGeckoClient, BaseClient)


def test_get_prices_parses_response(mocker):
    fake_response = mocker.Mock()
    fake_response.json.return_value = {"bitcoin": {"usd": 67000}, "ethereum": {"usd": 3500.5}}
    fake_response.raise_for_status.return_value = None
    mock_get = mocker.patch("app.clients.base.requests.get", return_value=fake_response)

    prices = CoinGeckoClient().get_prices(["bitcoin", "ethereum"])

    assert prices == [
        {"symbol": "bitcoin", "currency": "usd", "price": 67000.0, "source": "coingecko"},
        {"symbol": "ethereum", "currency": "usd", "price": 3500.5, "source": "coingecko"},
    ]
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["params"] == {"ids": "bitcoin,ethereum", "vs_currencies": "usd"}


def test_get_prices_skips_unknown_coins(mocker):
    fake_response = mocker.Mock()
    fake_response.json.return_value = {"bitcoin": {"usd": 67000}}
    mocker.patch("app.clients.base.requests.get", return_value=fake_response)

    prices = CoinGeckoClient().get_prices(["bitcoin", "not-a-coin"])

    assert [p["symbol"] for p in prices] == ["bitcoin"]


def test_network_error_raises_api_client_error(mocker):
    mocker.patch(
        "app.clients.base.requests.get",
        side_effect=requests.ConnectionError("no network"),
    )

    with pytest.raises(APIClientError):
        CoinGeckoClient().get_prices(["bitcoin"])


def test_unmocked_request_is_blocked_in_tests():
    # conftest.py blocks real HTTP, so a missing mock fails fast instead of reaching the internet.
    with pytest.raises(RuntimeError, match="real network"):
        CoinGeckoClient().get_prices(["bitcoin"])
