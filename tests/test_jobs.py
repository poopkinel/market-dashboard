"""Job store and background job tests. The client is a mock, so no network is used.
Result files go to a temporary folder (see conftest.py)."""

import json
from pathlib import Path

from app.clients import APIClientError
from app.jobs import JobStore, run_job

PARAMS = {"symbol": "BTC", "currency": "usd", "interval": "1h", "days": 1, "source": "binance", "start_ms": 0}


def rows(n):
    return [{"open_time": i, "open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0 + i, "volume": 1.0}
            for i in range(n)]


def test_store_create_get_update_list():
    store = JobStore()
    job = store.create(PARAMS)

    assert job["status"] == "pending"
    assert store.get(job["id"])["params"] == PARAMS
    store.update(job["id"], status="running")
    assert store.get(job["id"])["status"] == "running"
    assert [j["id"] for j in store.list()] == [job["id"]]
    assert store.get("missing") is None


def test_store_returns_copies():
    store = JobStore()
    job = store.create(PARAMS)
    job["status"] = "changed outside the store"
    assert store.get(job["id"])["status"] == "pending"


def test_run_job_success(mocker):
    store = JobStore()
    job = store.create(PARAMS)
    client = mocker.Mock()
    client.iter_history.return_value = iter(rows(30))

    run_job(store, job["id"], client)

    done = store.get(job["id"])
    assert done["status"] == "done"
    assert done["rows_processed"] == 30
    assert done["result"]["rows"] == 30
    assert done["result"]["last_close"] == 129.0
    assert done["finished_at"] is not None
    client.iter_history.assert_called_once_with("BTC", currency="usd", interval="1h", start_ms=0)

    saved = json.loads(Path(done["result_file"]).read_text())
    assert saved == {"id": job["id"], "params": PARAMS, "result": done["result"]}


def test_run_job_reports_progress(mocker):
    mocker.patch("app.jobs.PROGRESS_EVERY", 10)
    store = JobStore()
    job = store.create(PARAMS)
    client = mocker.Mock()
    client.iter_history.return_value = iter(rows(25))
    spy = mocker.spy(store, "update")

    run_job(store, job["id"], client)

    progress = [c.kwargs["rows_processed"] for c in spy.call_args_list if set(c.kwargs) == {"rows_processed"}]
    assert progress == [10, 20]


def test_run_job_failure(mocker):
    def rows_then_error():
        yield rows(1)[0]
        raise APIClientError("binance: request failed")

    store = JobStore()
    job = store.create(PARAMS)
    client = mocker.Mock()
    client.iter_history.return_value = rows_then_error()

    run_job(store, job["id"], client)

    failed = store.get(job["id"])
    assert failed["status"] == "failed"
    assert failed["error"] == "binance: request failed"
    assert failed["rows_processed"] == 1
    assert failed["result"] is None
    assert failed["result_file"] is None


def test_run_job_prints_telemetry(mocker, capsys):
    store = JobStore()
    job = store.create(PARAMS)
    client = mocker.Mock()
    client.iter_history.return_value = iter(rows(3))

    run_job(store, job["id"], client)

    out = capsys.readouterr().out
    assert "[file] saved" in out
    assert "[telemetry] run_job:" in out
