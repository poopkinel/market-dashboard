"""Custom decorator that times function calls and prints telemetry to the terminal."""

import functools
import inspect
import threading
from time import perf_counter

# Per-function stats: {"get_prices": {"calls": 3, "errors": 0, "total_ms": 812.4, "max_ms": 402.0}, ...}
_stats: dict[str, dict] = {}
# Endpoints run in several worker threads at once, so updates to _stats are locked.
_lock = threading.Lock()


def _record(name: str, elapsed_ms: float, error: Exception | None) -> None:
    """Update the stats for `name` and print one telemetry line."""
    with _lock:
        s = _stats.setdefault(name, {"calls": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0})
        s["calls"] += 1
        s["total_ms"] += elapsed_ms
        s["max_ms"] = max(s["max_ms"], elapsed_ms)
        if error is not None:
            s["errors"] += 1
        calls, errors, avg, max_ms = s["calls"], s["errors"], s["total_ms"] / s["calls"], s["max_ms"]

    if error is None:
        outcome = "ok"
    else:
        status = getattr(error, "status_code", "")  # HTTPException carries a status code
        outcome = f"error: {type(error).__name__} {status}".strip()
    print(f"[telemetry] {name}: {elapsed_ms:.1f} ms ({outcome}) | "
          f"calls={calls} errors={errors} avg={avg:.1f} ms max={max_ms:.1f} ms", flush=True)


# AI-assisted: drafted with an AI assistant for this reference solution.
# In your own project, say here what Copilot suggested and what you changed or checked.
# Pattern: a decorator with functools.wraps and separate sync/async wrappers.
def log_execution_time(func):
    """Time every call to `func`, update its stats, and print a telemetry line.

    Works on plain and async functions. functools.wraps copies the name,
    docstring and signature of `func` onto the wrapper. FastAPI reads the
    signature to find the route's parameters, so without wraps the route
    would lose its query parameters.
    """
    name = func.__name__

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = perf_counter()
            error = None
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                error = exc
                raise
            finally:
                _record(name, (perf_counter() - start) * 1000, error)
        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = perf_counter()
        error = None
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            error = exc
            raise
        finally:
            _record(name, (perf_counter() - start) * 1000, error)
    return wrapper


def get_stats() -> dict:
    """A copy of the stats, with the average added."""
    with _lock:
        return {name: {**s, "avg_ms": s["total_ms"] / s["calls"]} for name, s in _stats.items()}


def reset_stats() -> None:
    with _lock:
        _stats.clear()
