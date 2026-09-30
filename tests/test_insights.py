"""Ollama insight tests. requests.post is mocked, so no model and no network are needed."""

import json

import pytest
import requests

from app.insights import (
    SCHEMA, OllamaClient, OllamaError, OllamaUnavailable, build_prompt, describe_result, parse_classification,
)

PARAMS = {"symbol": "BTC", "currency": "usd", "interval": "1h", "days": 30}
RESULT = {"rows": 720, "first_close": 60000.0, "last_close": 66000.0, "change_pct": 10.0, "high": 67000.0,
          "low": 58000.0, "volatility_pct": 0.8, "max_drawdown_pct": 6.5, "sma_20": 65500.0, "sma_50": 64000.0,
          "trend": "up", "series": [{"t": 0, "close": 1.0}]}


def fake_response(mocker, status=200, body=None):
    response = mocker.Mock()
    response.status_code = status
    response.ok = status < 400
    response.json.return_value = body or {}
    response.text = json.dumps(body or {})
    return response


def test_describe_result_includes_the_numbers():
    text = describe_result(PARAMS, RESULT)
    assert "BTC in USD" in text
    assert "10.00%" in text
    assert "trend: up" in text
    assert "series" not in text  # the chart points are not sent to the model


def test_describe_result_handles_missing_values():
    text = describe_result(PARAMS, {"rows": 0, "change_pct": None, "trend": None})
    assert "Change over the period: n/a" in text


def test_build_prompt_with_data_text_and_schema():
    prompt = build_prompt(text="  ETF inflows at a record  ", params=PARAMS, result=RESULT)
    assert "Market data summary:" in prompt
    assert "Text to analyse:\nETF inflows at a record" in prompt
    assert json.dumps(SCHEMA) in prompt


def test_build_prompt_text_only():
    prompt = build_prompt(text="hello")
    assert "Market data summary" not in prompt
    assert "hello" in prompt


def test_parse_classification_normalises_case():
    raw = '{"sentiment": " Bullish ", "risk": "LOW", "summary": "Prices rose steadily."}'
    assert parse_classification(raw) == {"sentiment": "bullish", "risk": "low", "summary": "Prices rose steadily."}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '{"sentiment": "happy", "risk": "low"}',
                                 '{"sentiment": "neutral", "risk": "extreme"}'])
def test_parse_classification_rejects_bad_answers(raw):
    with pytest.raises(OllamaError):
        parse_classification(raw)


def test_classify_sends_a_structured_request(mocker):
    answer = {"response": '{"sentiment": "bearish", "risk": "high", "summary": "Sharp fall."}'}
    post = mocker.patch("app.insights.requests.post", return_value=fake_response(mocker, body=answer))

    result = OllamaClient(host="http://ollama:11434/", model="test-model").classify("the prompt")

    assert result == {"sentiment": "bearish", "risk": "high", "summary": "Sharp fall.", "model": "test-model"}
    url = post.call_args.args[0]
    payload = post.call_args.kwargs["json"]
    assert url == "http://ollama:11434/api/generate"
    assert payload["model"] == "test-model"
    assert payload["prompt"] == "the prompt"
    assert payload["format"] == SCHEMA
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0


def test_classify_ollama_not_running(mocker):
    mocker.patch("app.insights.requests.post", side_effect=requests.ConnectionError("refused"))

    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        OllamaClient().classify("x")


def test_classify_model_not_downloaded(mocker):
    mocker.patch("app.insights.requests.post",
                 return_value=fake_response(mocker, 404, {"error": "model 'llama3' not found"}))

    with pytest.raises(OllamaError, match="ollama pull"):
        OllamaClient(model="llama3").classify("x")


def test_classify_timeout(mocker):
    mocker.patch("app.insights.requests.post", side_effect=requests.Timeout())

    with pytest.raises(OllamaError, match="did not answer"):
        OllamaClient(timeout=5).classify("x")
