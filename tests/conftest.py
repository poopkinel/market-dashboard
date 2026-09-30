"""Shared test setup. pytest loads this file automatically."""

import pytest

from app import telemetry


def _no_network(*args, **kwargs):
    raise RuntimeError("A test tried to use the real network. Mock the HTTP call instead.")


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Runs before every test:
    - job files go to the test's own temporary folder;
    - telemetry starts empty;
    - any HTTP request made with `requests` that a test forgot to mock fails at once,
      instead of reaching the internet or Ollama (or hanging when offline)."""
    monkeypatch.setattr("app.jobs.RESULTS_DIR", tmp_path / "jobs")
    telemetry.reset_stats()
    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", _no_network)
