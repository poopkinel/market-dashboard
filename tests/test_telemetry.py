"""Decorator tests. No network is involved."""

import asyncio
import inspect

import pytest

from app.telemetry import get_stats, log_execution_time


def test_keeps_name_docstring_and_signature():
    def original(a: int, b: str = "x") -> str:
        """Docstring."""
        return b * a

    wrapped = log_execution_time(original)

    assert wrapped.__name__ == "original"
    assert wrapped.__doc__ == "Docstring."
    assert inspect.signature(wrapped) == inspect.signature(original)


def test_prints_telemetry_and_returns_the_result(capsys):
    @log_execution_time
    def add(a, b):
        return a + b

    assert add(2, 3) == 5

    out = capsys.readouterr().out
    assert "[telemetry] add:" in out
    assert "(ok)" in out
    assert get_stats()["add"]["calls"] == 1


def test_measures_time(mocker):
    mocker.patch("app.telemetry.perf_counter", side_effect=[0.0, 0.5, 1.0, 1.1])

    @log_execution_time
    def work():
        return None

    work()  # 500 ms
    work()  # 100 ms

    stats = get_stats()["work"]
    assert stats["calls"] == 2
    assert stats["max_ms"] == pytest.approx(500.0)
    assert stats["avg_ms"] == pytest.approx(300.0)


def test_counts_errors_and_reraises(capsys):
    @log_execution_time
    def broken():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        broken()

    assert "(error: ValueError)" in capsys.readouterr().out
    assert get_stats()["broken"]["errors"] == 1


def test_works_on_async_functions(capsys):
    @log_execution_time
    async def fetch():
        return "done"

    assert inspect.iscoroutinefunction(fetch)
    assert asyncio.run(fetch()) == "done"
    assert "[telemetry] fetch:" in capsys.readouterr().out
