"""In-memory job store and the background job that runs the engine."""

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.clients import APIClientError, BaseClient
from app.engine import Engine
from app.files import AtomicFileWriter
from app.telemetry import log_execution_time

# How often (in rows) a running job saves its progress.
PROGRESS_EVERY = 500
# Where finished jobs are saved, relative to the folder the server runs in.
RESULTS_DIR = Path("data") / "jobs"


@dataclass
class Job:
    id: str
    params: dict
    status: str = "pending"  # pending -> running -> done | failed
    rows_processed: int = 0
    result: dict | None = None
    error: str | None = None
    result_file: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


# AI-assisted: drafted with an AI assistant for this reference solution.
# In your own project, say here what Copilot suggested and what you changed or checked.
# Pattern: a lock around shared state that worker threads update.
class JobStore:
    """Keeps jobs in a dict.

    Background jobs run in worker threads while requests read the same dict,
    so every read and write happens while holding a lock. Reads return copies,
    so callers never see a job half-way through an update.
    Jobs live in memory only and are lost when the server restarts.
    """

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, params: dict) -> dict:
        job = Job(id=uuid.uuid4().hex[:12], params=params)
        with self._lock:
            self._jobs[job.id] = job
            return asdict(job)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return asdict(job) if job else None

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
            return [asdict(j) for j in jobs]

    def update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)


def save_result(job_id: str, params: dict, result: dict) -> Path:
    """Write a finished job to RESULTS_DIR/<job_id>.json and return the path."""
    path = RESULTS_DIR / f"{job_id}.json"
    with AtomicFileWriter(path) as f:
        json.dump({"id": job_id, "params": params, "result": result}, f, indent=2)
    return path


@log_execution_time
def run_job(store: JobStore, job_id: str, client: BaseClient) -> None:
    """Fetch history, feed it through the engine, and save the result on the job.

    FastAPI calls this after the response has been sent. It is a plain
    function, so FastAPI runs it in a worker thread.
    """
    params = store.get(job_id)["params"]
    store.update(job_id, status="running")
    engine = Engine()
    try:
        rows = client.iter_history(params["symbol"], currency=params["currency"],
                                   interval=params["interval"], start_ms=params["start_ms"])
        for row in rows:
            engine.update(row)
            if engine.rows % PROGRESS_EVERY == 0:
                store.update(job_id, rows_processed=engine.rows)
        result = engine.result()
        path = save_result(job_id, params, result)
        store.update(job_id, status="done", rows_processed=engine.rows,
                     result=result, result_file=str(path), finished_at=time.time())
    except APIClientError as exc:
        store.update(job_id, status="failed", rows_processed=engine.rows,
                     error=str(exc), finished_at=time.time())
    except Exception as exc:
        # Any other error must still end the job, or it would stay "running" forever.
        store.update(job_id, status="failed", rows_processed=engine.rows,
                     error=f"Unexpected error: {exc!r}", finished_at=time.time())
