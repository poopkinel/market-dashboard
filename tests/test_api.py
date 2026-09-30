"""API route tests. The clients are mocked, so no network is used."""

import json

from fastapi.testclient import TestClient

from app.clients import APIClientError
from app.insights import OllamaError, OllamaUnavailable
from app.main import app, clients, insights, jobs

test_client = TestClient(app)


def test_health():
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_prices_returns_json(mocker):
    fake_prices = [{"symbol": "bitcoin", "currency": "usd", "price": 67000.0, "source": "coingecko"}]
    mock = mocker.patch.object(clients["coingecko"], "get_prices", return_value=fake_prices)

    response = test_client.get("/api/prices", params={"coins": "Bitcoin"})

    assert response.status_code == 200
    assert response.json() == {"count": 1, "prices": fake_prices}
    mock.assert_called_once_with(["bitcoin"], currency="usd")


def test_prices_uses_default_symbols_of_the_source(mocker):
    mock = mocker.patch.object(clients["binance"], "get_prices", return_value=[])

    response = test_client.get("/api/prices", params={"source": "binance"})

    assert response.status_code == 200
    mock.assert_called_once_with(["BTC", "ETH"], currency="usd")


def test_prices_empty_input_returns_400():
    response = test_client.get("/api/prices", params={"coins": " , "})
    assert response.status_code == 400


def test_prices_unknown_source_returns_400():
    response = test_client.get("/api/prices", params={"source": "nope"})
    assert response.status_code == 400


def test_prices_upstream_error_returns_502(mocker):
    mocker.patch.object(clients["coingecko"], "get_prices", side_effect=APIClientError("down"))

    response = test_client.get("/api/prices")

    assert response.status_code == 502


def test_history_streams_ndjson(mocker):
    fake_rows = [{"open_time": 0, "close": 100.0}, {"open_time": 60_000, "close": 101.0}]
    mock = mocker.patch.object(clients["binance"], "iter_history", return_value=iter(fake_rows))

    response = test_client.get("/api/history", params={"symbol": "BTC", "interval": "1m", "days": 1})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert lines == fake_rows
    assert mock.call_args.kwargs["interval"] == "1m"


def test_history_first_page_error_returns_502(mocker):
    def failing_rows():
        raise APIClientError("down")
        yield  # makes this a generator

    mocker.patch.object(clients["binance"], "iter_history", return_value=failing_rows())

    response = test_client.get("/api/history")

    assert response.status_code == 502


def test_history_later_page_error_is_written_in_the_body(mocker):
    def rows_then_error():
        yield {"open_time": 0, "close": 100.0}
        raise APIClientError("down")

    mocker.patch.object(clients["binance"], "iter_history", return_value=rows_then_error())

    response = test_client.get("/api/history")

    lines = [json.loads(line) for line in response.text.splitlines()]
    assert lines[0] == {"open_time": 0, "close": 100.0}
    assert "error" in lines[1]


def test_history_bad_interval_returns_400():
    response = test_client.get("/api/history", params={"interval": "7x"})
    assert response.status_code == 400


def test_history_source_without_history_returns_400():
    response = test_client.get("/api/history", params={"source": "coingecko"})
    assert response.status_code == 400


def test_create_job_runs_in_background(mocker):
    fake_rows = [{"open_time": i, "open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0 + i, "volume": 1.0}
                 for i in range(5)]
    mock = mocker.patch.object(clients["binance"], "iter_history", return_value=iter(fake_rows))

    response = test_client.post("/api/jobs", json={"symbol": "btc", "interval": "1h", "days": 7})

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "pending"  # the response is sent before the job starts
    assert job["params"]["symbol"] == "BTC"

    # TestClient runs background tasks before it returns, so the job has finished by now.
    done = test_client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "done"
    assert done["result"]["rows"] == 5
    assert mock.call_args.kwargs["interval"] == "1h"


def test_list_jobs_includes_new_job(mocker):
    mocker.patch.object(clients["binance"], "iter_history", return_value=iter([]))

    job = test_client.post("/api/jobs", json={}).json()

    ids = [j["id"] for j in test_client.get("/api/jobs").json()["jobs"]]
    assert job["id"] in ids


def test_create_job_bad_interval_returns_400():
    assert test_client.post("/api/jobs", json={"interval": "7x"}).status_code == 400


def test_create_job_source_without_history_returns_400():
    assert test_client.post("/api/jobs", json={"source": "coingecko"}).status_code == 400


def test_create_job_days_out_of_range_returns_422():
    assert test_client.post("/api/jobs", json={"days": 0}).status_code == 422


def test_get_unknown_job_returns_404():
    assert test_client.get("/api/jobs/nope").status_code == 404


def test_route_prints_telemetry(mocker, capsys):
    mocker.patch.object(clients["coingecko"], "get_prices", return_value=[])

    test_client.get("/api/prices")

    assert "[telemetry] get_prices:" in capsys.readouterr().out


def test_decorated_route_keeps_its_query_parameters(mocker):
    mock = mocker.patch.object(clients["binance"], "get_prices", return_value=[])

    test_client.get("/api/prices", params={"source": "binance", "coins": "sol", "currency": "eur"})

    mock.assert_called_once_with(["sol"], currency="eur")


def test_telemetry_endpoint_counts_calls_and_errors(mocker):
    mocker.patch.object(clients["coingecko"], "get_prices", return_value=[])
    test_client.get("/api/prices")
    test_client.get("/api/prices", params={"coins": " , "})  # raises HTTPException 400

    stats = test_client.get("/api/telemetry").json()

    assert stats["get_prices"]["calls"] == 2
    assert stats["get_prices"]["errors"] == 1


def test_finished_job_has_a_result_file(mocker):
    mocker.patch.object(clients["binance"], "iter_history", return_value=iter([]))

    job = test_client.post("/api/jobs", json={}).json()
    done = test_client.get(f"/api/jobs/{job['id']}").json()

    assert done["result_file"].endswith(f"{job['id']}.json")


def test_dashboard_page_is_served():
    response = test_client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Market Data Dashboard" in response.text


def test_dashboard_script_and_styles_are_served():
    assert test_client.get("/static/app.js").status_code == 200
    assert test_client.get("/static/style.css").status_code == 200


INSIGHT = {"sentiment": "bullish", "risk": "low", "summary": "Steady rise.", "model": "llama3"}


def test_insight_for_text(mocker):
    classify = mocker.patch.object(insights, "classify", return_value=INSIGHT)

    response = test_client.post("/api/insights", json={"text": "ETF inflows at a record"})

    assert response.status_code == 200
    assert response.json() == {**INSIGHT, "job_id": None}
    assert "ETF inflows at a record" in classify.call_args.args[0]


def test_insight_for_a_finished_job(mocker):
    fake_rows = [{"open_time": i, "open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0 + i, "volume": 1.0}
                 for i in range(60)]
    mocker.patch.object(clients["binance"], "iter_history", return_value=iter(fake_rows))
    classify = mocker.patch.object(insights, "classify", return_value=INSIGHT)
    job = test_client.post("/api/jobs", json={"symbol": "eth"}).json()

    response = test_client.post("/api/insights", json={"job_id": job["id"]})

    assert response.status_code == 200
    assert response.json()["job_id"] == job["id"]
    prompt = classify.call_args.args[0]
    assert "Market data summary" in prompt
    assert "ETH" in prompt


def test_insight_needs_text_or_job():
    assert test_client.post("/api/insights", json={"text": "   "}).status_code == 400


def test_insight_unknown_job_returns_404():
    assert test_client.post("/api/insights", json={"job_id": "nope"}).status_code == 404


def test_insight_unfinished_job_returns_409():
    job = jobs.create({"symbol": "BTC"})  # still "pending"

    assert test_client.post("/api/insights", json={"job_id": job["id"]}).status_code == 409


def test_insight_ollama_not_running_returns_503(mocker):
    mocker.patch.object(insights, "classify", side_effect=OllamaUnavailable("Ollama is not reachable"))

    response = test_client.post("/api/insights", json={"text": "hello"})

    assert response.status_code == 503
    assert "not reachable" in response.json()["detail"]


def test_insight_bad_model_answer_returns_502(mocker):
    mocker.patch.object(insights, "classify", side_effect=OllamaError("unexpected risk 'extreme'"))

    assert test_client.post("/api/insights", json={"text": "hello"}).status_code == 502
