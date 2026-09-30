# Market Data Dashboard

A full-stack Python web app for crypto market data:

- The **web dashboard** shows current prices and starts analyses.
- A **background job** fetches historical candles from Binance, streams them through a custom **processing engine**, saves the result to a file, and shows it on the dashboard as statistics and a chart.
- **AI insights** come from a model running in your local **Ollama**: it classifies an analysis, or any text you type, as bullish, bearish or neutral with low, medium or high risk.

Built with FastAPI and `requests`. All tests run without an internet connection.

## Requirements

- Python 3.10 or newer
- [Ollama](https://ollama.com), only for the AI insight feature. Everything else works without it.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

For AI insights, install Ollama and download a model:

```bash
ollama pull llama3
```

The app uses `llama3` at `http://localhost:11434` by default. To use a different model or address, set environment variables before starting the server:

```bash
export OLLAMA_MODEL=llama3.2              # Windows PowerShell: $env:OLLAMA_MODEL = "llama3.2"
export OLLAMA_HOST=http://localhost:11434 # Windows PowerShell: $env:OLLAMA_HOST = "http://localhost:11434"
```

## Run

```bash
uvicorn app.main:app --reload
```

- Dashboard: http://127.0.0.1:8000/
- Swagger UI (all API routes): http://127.0.0.1:8000/docs

Ollama normally runs in the background after installation. If the dashboard reports that it can't reach Ollama, start it with `ollama serve`.

## Using the dashboard

1. **Current prices:** pick CoinGecko or Binance and click "Refresh prices".
2. **Historical analysis:** choose a symbol (e.g. `BTC`, `ETH`, `SOL`), a candle size and a number of days, and click "Start analysis". The job runs in the background; the page checks its progress every second. When it's done you see:
   - statistic tiles: last close, change, high, low, volatility, max drawdown, trend;
   - a price chart (move the pointer over it to read values);
   - a table view of the chart data.
3. **AI insight:** click "Get AI insight for this analysis", or type any text and click "Classify text".
4. **Recent analyses:** earlier jobs, with a "Show" button for finished ones and the error message for failed ones.
5. **Server telemetry:** call counts and timings collected by the `@log_execution_time` decorator.

## API

| Method | Path                 | Description |
|--------|----------------------|-------------|
| GET    | `/`                  | The dashboard page |
| GET    | `/health`            | Returns `{"status": "ok"}` |
| GET    | `/api/prices`        | Current prices as JSON. Query params: `source` (`coingecko` or `binance`, default `coingecko`), `coins` (CoinGecko ids like `bitcoin,ethereum`, or Binance symbols like `BTC,ETH`; default depends on the source), `currency` (default `usd`) |
| GET    | `/api/history`       | Historical candles, streamed as NDJSON (one JSON object per line). Query params: `symbol` (default `BTC`), `interval` (default `1h`), `days` (1–365, default `30`), `currency` (default `usd`), `source` (default `binance`) |
| POST   | `/api/jobs`          | Start a background analysis. JSON body (all fields optional): `symbol` (default `BTC`), `currency` (default `usd`), `interval` (default `1h`), `days` (1–365, default `30`), `source` (default `binance`). Returns `202` and the new job |
| GET    | `/api/jobs`          | All jobs, newest first |
| GET    | `/api/jobs/{job_id}` | One job: `status` (`pending`, `running`, `done`, `failed`), `rows_processed`, and `result` and `result_file`, or `error` |
| POST   | `/api/insights`      | AI classification. JSON body: `text`, `job_id` (a finished job), or both. Returns `sentiment` (`bullish`, `bearish`, `neutral`), `risk` (`low`, `medium`, `high`), `summary` and `model`. `503` if Ollama isn't running, `502` if the model's answer isn't usable |
| GET    | `/api/telemetry`     | Call counts, error counts and timings for each timed function |

Example of a heavy history fetch (365 days of hourly candles, about 8,760 rows):

```bash
curl "http://127.0.0.1:8000/api/history?symbol=BTC&interval=1h&days=365"
```

In Windows PowerShell, `curl` is a different command; use `curl.exe -N "..."` to see the rows arrive as they are streamed.

Jobs are kept in memory and are lost when the server restarts. Each finished job is also saved to `data/jobs/<job_id>.json`.

### Telemetry

Every `/api/...` route and the background job are wrapped in the `@log_execution_time` decorator (`app/telemetry.py`). Each call prints a line like this in the server terminal:

```
[telemetry] get_prices: 312.4 ms (ok) | calls=3 errors=0 avg=298.1 ms max=402.0 ms
```

### Safe file writing

`AtomicFileWriter` (`app/files.py`) is a context manager used to save job results. It writes to a temporary file and only replaces the real file when the `with` block finishes without an error. To see what happens when the block fails:

```bash
python -m app.demo_context_manager
```

The script ends with a traceback on purpose. The `[file]` lines before it show that the temporary file was closed and deleted and that `data/demo.txt` still has its first version.

## Tests

```bash
pytest
```

The tests never use the network. External calls (CoinGecko, Binance, Ollama) are replaced with mocks, and `tests/conftest.py` makes any HTTP request a test forgot to mock fail immediately. The tests write files only to pytest's temporary folders. To check, turn off Wi-Fi and run `pytest`: every test should pass.

## Project structure

```
app/
  main.py                  FastAPI app: routes, dashboard page, static files
  clients/
    base.py                BaseClient: shared HTTP logic (requests), abstract get_prices(), iter_history()
    coingecko.py           CoinGeckoClient(BaseClient): current prices
    binance.py             BinanceClient(BaseClient): current prices and paged history via generators
  engine.py                Processing engine: Indicator base class, indicators, Engine
  jobs.py                  JobStore (in-memory jobs), run_job (the background job), save_result
  telemetry.py             @log_execution_time decorator and the stats it collects
  files.py                 AtomicFileWriter context manager
  demo_context_manager.py  Shows AtomicFileWriter handling an error inside the with block
  insights.py              Ollama client: structured prompt, JSON schema, answer validation
  static/
    index.html             Dashboard page
    style.css              Dashboard styles (light and dark)
    app.js                 Dashboard logic: API calls, polling, chart
tests/
  conftest.py              Shared setup: temporary folders, empty telemetry, no real HTTP
  test_clients.py          CoinGecko client
  test_binance.py          Binance client and the history generator
  test_engine.py           Engine and indicators
  test_jobs.py             Job store and background job
  test_telemetry.py        Decorator
  test_files.py            Context manager
  test_insights.py         Ollama client, prompt and answer checking
  test_api.py              Routes and dashboard
```

## AI assistance

This reference solution was drafted with an AI assistant. The complex patterns are marked with comments that start with `AI-assisted:`, for example above `AtomicFileWriter.__enter__`.

## Data sources

- CoinGecko keyless public API: https://docs.coingecko.com/docs/keyless-public-api
- Binance market-data-only API (no key): https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only
- Ollama API: https://docs.ollama.com/api/generate

Market data and AI output are for learning purposes only and are not financial advice.
