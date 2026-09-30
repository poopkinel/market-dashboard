"""Binance client tests. HTTP calls are mocked, so no network is used."""

import inspect
import json

import pytest

from app.clients import APIClientError, BaseClient, BinanceClient


def kline(open_time, close):
    """One raw Binance kline row with made-up values."""
    return [open_time, "1.0", "2.0", "0.5", str(close), "10.0", open_time + 59_999, "0", 5, "0", "0", "0"]


def test_binance_inherits_base_client():
    assert issubclass(BinanceClient, BaseClient)


def test_get_prices_parses_response(mocker):
    client = BinanceClient()
    mock_get = mocker.patch.object(
        client, "_get",
        return_value=[{"symbol": "BTCUSDT", "price": "67000.5"}, {"symbol": "ETHUSDT", "price": "3500"}],
    )

    prices = client.get_prices(["btc", "eth"])

    assert prices == [
        {"symbol": "BTC", "currency": "usd", "price": 67000.5, "source": "binance"},
        {"symbol": "ETH", "currency": "usd", "price": 3500.0, "source": "binance"},
    ]
    params = mock_get.call_args.kwargs["params"]
    assert json.loads(params["symbols"]) == ["BTCUSDT", "ETHUSDT"]


def test_iter_history_is_a_generator_and_waits_until_used(mocker):
    client = BinanceClient()
    mock_get = mocker.patch.object(client, "_get", return_value=[])

    rows = client.iter_history("btc", start_ms=0)

    assert inspect.isgenerator(rows)
    mock_get.assert_not_called()  # nothing is fetched until the first row is asked for
    assert list(rows) == []
    mock_get.assert_called_once()


def test_iter_history_fetches_page_by_page(mocker):
    client = BinanceClient()
    client.page_size = 2
    mock_get = mocker.patch.object(
        client, "_get",
        side_effect=[[kline(0, 100), kline(60_000, 101)], [kline(120_000, 102)]],
    )

    rows = client.iter_history("btc", interval="1m", start_ms=0)

    first = next(rows)
    assert first == {
        "symbol": "BTC", "currency": "usd", "open_time": 0, "open": 1.0, "high": 2.0,
        "low": 0.5, "close": 100.0, "volume": 10.0, "source": "binance",
    }
    assert mock_get.call_count == 1  # only the first page so far

    rest = list(rows)
    assert [r["close"] for r in rest] == [101.0, 102.0]
    assert mock_get.call_count == 2
    # The second page starts right after the last candle of the first page.
    assert mock_get.call_args_list[1].kwargs["params"]["startTime"] == 60_001


def test_iter_history_error_raises_api_client_error(mocker):
    client = BinanceClient()
    mocker.patch.object(client, "_get", side_effect=APIClientError("down"))

    with pytest.raises(APIClientError):
        next(client.iter_history("btc", start_ms=0))
