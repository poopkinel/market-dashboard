"""FastAPI application entry point."""

import json
import time
from collections.abc import Iterator
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.clients import INTERVALS, APIClientError, BaseClient, BinanceClient, CoinGeckoClient
from app.insights import OllamaClient, OllamaError, OllamaUnavailable, build_prompt
from app.jobs import JobStore, run_job
from app.telemetry import get_stats, log_execution_time

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Market Data Dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

clients: dict[str, BaseClient] = {
    "coingecko": CoinGeckoClient(),
    "binance": BinanceClient(),
}

jobs = JobStore()
insights = OllamaClient()


def get_client(source: str) -> BaseClient:
    client = clients.get(source.lower())
    if client is None:
        raise HTTPException(status_code=400, detail=f"Unknown source {source!r}. Use one of: {', '.join(clients)}")
    return client


def check_interval(interval: str) -> None:
    if interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"Unknown interval {interval!r}")


def start_ms_for(days: int) -> int:
    """Unix time in milliseconds, `days` days ago."""
    return int((time.time() - days * 86400) * 1000)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    """The web UI: one HTML page that calls the API routes below."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Defined with `def`, not `async def`: `requests` is blocking, so FastAPI
# runs this function in a worker thread and the server keeps answering
# other requests while this one waits for the external API.
@app.get("/api/prices")
@log_execution_time
def get_prices(
    coins: str | None = Query(None, description="Comma-separated symbols. CoinGecko: bitcoin,ethereum. Binance: BTC,ETH"),
    currency: str = Query("usd"),
    source: str = Query("coingecko", description="coingecko or binance"),
) -> dict:
    client = get_client(source)
    if coins is None:
        coin_ids = client.default_symbols
    else:
        coin_ids = [c.strip().lower() for c in coins.split(",") if c.strip()]
        if not coin_ids:
            raise HTTPException(status_code=400, detail="No coin ids given")

    try:
        prices = client.get_prices(coin_ids, currency=currency.lower())
    except APIClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"count": len(prices), "prices": prices}


@app.get("/api/history")
@log_execution_time
def get_history(
    symbol: str = Query("BTC", description="Asset symbol, e.g. BTC"),
    currency: str = Query("usd"),
    interval: str = Query("1h", description="Candle size: " + ", ".join(sorted(INTERVALS))),
    days: int = Query(30, ge=1, le=365, description="How many days back to fetch"),
    source: str = Query("binance"),
) -> StreamingResponse:
    """Stream historical candles as NDJSON: one JSON object per line."""
    check_interval(interval)
    client = get_client(source)

    try:
        rows = client.iter_history(symbol, currency=currency.lower(), interval=interval, start_ms=start_ms_for(days))
        # Pull the first row now. If the first request fails, we can still answer
        # with a normal error status, because nothing has been sent yet.
        first = next(rows, None)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except APIClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return StreamingResponse(_to_ndjson(first, rows), media_type="application/x-ndjson")


def _to_ndjson(first: dict | None, rows: Iterator[dict]) -> Iterator[str]:
    """Turn rows into NDJSON lines as they arrive, without collecting them in a list."""
    if first is None:
        return
    yield json.dumps(first) + "\n"
    try:
        for row in rows:
            yield json.dumps(row) + "\n"
    except APIClientError as exc:
        # The status code (200) has already been sent, so the error goes in the body.
        yield json.dumps({"error": str(exc)}) + "\n"


class JobRequest(BaseModel):
    symbol: str = "BTC"
    currency: str = "usd"
    interval: str = "1h"
    days: int = Field(30, ge=1, le=365)
    source: str = "binance"


@app.post("/api/jobs", status_code=202)
@log_execution_time
def create_job(request: JobRequest, background_tasks: BackgroundTasks) -> dict:
    """Start a background job that fetches history and runs it through the engine."""
    check_interval(request.interval)
    client = get_client(request.source)
    if not client.has_history:
        raise HTTPException(status_code=400, detail=f"{client.name} does not provide historical data")

    job = jobs.create({
        "symbol": request.symbol.upper(),
        "currency": request.currency.lower(),
        "interval": request.interval,
        "days": request.days,
        "source": client.name,
        "start_ms": start_ms_for(request.days),
    })
    # Runs after this response has been sent.
    background_tasks.add_task(run_job, jobs, job["id"], client)
    return job


@app.get("/api/jobs")
@log_execution_time
def list_jobs() -> dict:
    return {"jobs": jobs.list()}


@app.get("/api/jobs/{job_id}")
@log_execution_time
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No job with id {job_id!r}")
    return job


@app.get("/api/telemetry")
def telemetry() -> dict:
    """Call counts and timings collected by @log_execution_time."""
    return get_stats()


class InsightRequest(BaseModel):
    text: str | None = Field(None, max_length=4000, description="Free text to classify, e.g. a news headline")
    job_id: str | None = Field(None, description="A finished job whose results should be classified")


@app.post("/api/insights")
@log_execution_time
def get_insight(request: InsightRequest) -> dict:
    """Ask the local Ollama model for a sentiment and risk classification."""
    if not (request.text and request.text.strip()) and not request.job_id:
        raise HTTPException(status_code=400, detail="Send `text`, `job_id`, or both")

    params = result = None
    if request.job_id:
        job = jobs.get(request.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"No job with id {request.job_id!r}")
        if job["status"] != "done":
            raise HTTPException(status_code=409, detail=f"Job {request.job_id!r} is {job['status']}, not done")
        params, result = job["params"], job["result"]

    prompt = build_prompt(text=request.text, params=params, result=result)
    try:
        classification = insights.classify(prompt)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama: {exc}") from exc

    return {**classification, "job_id": request.job_id}
