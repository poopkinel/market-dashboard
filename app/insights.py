"""AI insights: ask a local Ollama model to classify market data or text.

The model must answer with JSON that matches SCHEMA. The answer is checked
before it is returned, so the rest of the app only ever sees one of the
allowed categories.
"""

import json
import os

import requests

# Change these with environment variables, e.g.  set OLLAMA_MODEL=llama3.2  (Windows)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")

SENTIMENTS = ("bullish", "bearish", "neutral")
RISKS = ("low", "medium", "high")

# JSON schema sent to Ollama in the `format` field, so the model's output has to follow it.
SCHEMA = {
    "type": "object",
    "properties": {
        "sentiment": {"type": "string", "enum": list(SENTIMENTS)},
        "risk": {"type": "string", "enum": list(RISKS)},
        "summary": {"type": "string"},
    },
    "required": ["sentiment", "risk", "summary"],
}

SYSTEM_PROMPT = (
    "You are a cautious market analyst. Classify the market data and/or text you are given.\n"
    "- sentiment: bullish, bearish or neutral (the direction the data or text points to).\n"
    "- risk: low, medium or high (how large and unpredictable the price moves are).\n"
    "- summary: one or two plain sentences explaining the classification, "
    "using only the information given.\n"
    "Answer with JSON only."
)


class OllamaError(Exception):
    """Ollama answered, but not with something we can use."""


class OllamaUnavailable(OllamaError):
    """Ollama could not be reached at all."""


def _fmt(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value}{suffix}"


def describe_result(params: dict, result: dict) -> str:
    """Turn a job's parameters and engine result into short text lines for the prompt."""
    lines = [
        f"Asset: {params.get('symbol')} in {str(params.get('currency', '')).upper()}, "
        f"{_fmt(result.get('rows'))} candles of {params.get('interval')} over the last {params.get('days')} days",
        f"First close: {_fmt(result.get('first_close'))}, last close: {_fmt(result.get('last_close'))}",
        f"Change over the period: {_fmt(result.get('change_pct'), '%')}",
        f"Highest high: {_fmt(result.get('high'))}, lowest low: {_fmt(result.get('low'))}",
        f"Volatility (std. dev. of per-candle returns): {_fmt(result.get('volatility_pct'), '%')}",
        f"Largest drop from a peak: {_fmt(result.get('max_drawdown_pct'), '%')}",
        f"20-candle average: {_fmt(result.get('sma_20'))}, 50-candle average: {_fmt(result.get('sma_50'))}, "
        f"trend: {result.get('trend') or 'n/a'}",
    ]
    return "\n".join(lines)


def build_prompt(text: str | None = None, params: dict | None = None, result: dict | None = None) -> str:
    """Build the prompt from market data, free text, or both, and end it with the schema."""
    parts = []
    if result is not None:
        parts.append("Market data summary:\n" + describe_result(params or {}, result))
    if text:
        parts.append("Text to analyse:\n" + text.strip())
    # Ollama recommends also putting the schema in the prompt, to ground the answer.
    parts.append("Answer with JSON that matches this schema:\n" + json.dumps(SCHEMA))
    return "\n\n".join(parts)


# AI-assisted: drafted with an AI assistant for this reference solution.
# In your own project, say here what Copilot suggested and what you changed or checked.
# Pattern: validating a model's JSON answer against a fixed set of categories.
def parse_classification(raw: str) -> dict:
    """Check the model's JSON answer and return it with clean, lower-case categories."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaError("the model did not return valid JSON") from exc
    if not isinstance(data, dict):
        raise OllamaError("the model's JSON is not an object")

    sentiment = str(data.get("sentiment", "")).strip().lower()
    risk = str(data.get("risk", "")).strip().lower()
    if sentiment not in SENTIMENTS:
        raise OllamaError(f"unexpected sentiment {sentiment!r}")
    if risk not in RISKS:
        raise OllamaError(f"unexpected risk {risk!r}")
    return {"sentiment": sentiment, "risk": risk, "summary": str(data.get("summary", "")).strip()}


class OllamaClient:
    """Sends prompts to Ollama's /api/generate endpoint with `requests`."""

    def __init__(self, host: str | None = None, model: str | None = None, timeout: float = 120.0):
        self.host = (host or OLLAMA_HOST).rstrip("/")
        self.model = model or OLLAMA_MODEL
        self.timeout = timeout  # models can take a while, especially on the first call

    def classify(self, prompt: str) -> dict:
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": prompt,
            "format": SCHEMA,
            "stream": False,
            "options": {"temperature": 0},  # same input -> same answer, as far as possible
        }
        try:
            response = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        except requests.ConnectionError as exc:
            raise OllamaUnavailable(
                f"Ollama is not reachable at {self.host}. Is it running? (start it with: ollama serve)") from exc
        except requests.Timeout as exc:
            raise OllamaError(f"Ollama did not answer within {self.timeout:.0f} seconds") from exc
        except requests.RequestException as exc:
            raise OllamaError(f"request to Ollama failed: {exc}") from exc

        if response.status_code == 404:
            raise OllamaError(f"model {self.model!r} was not found. Download it with: ollama pull {self.model}")
        if not response.ok:
            raise OllamaError(f"Ollama returned HTTP {response.status_code}: {response.text[:200]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama's response is not valid JSON") from exc
        classification = parse_classification(body.get("response", ""))
        classification["model"] = self.model
        return classification
