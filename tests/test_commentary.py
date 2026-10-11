import json

import httpx2
import pytest
from conftest import anthropic_client, message

from edgar_ratios.commentary import MODEL, Commentator, CommentaryError, build_prompt, unverified_numbers
from edgar_ratios.ratios import analyze


@pytest.fixture
def apple(sec):
    return analyze(sec, "AAPL", years=3)


def replying(text, seen=None, stop_reason="end_turn"):
    def handler(request):
        if seen is not None:
            seen["body"] = json.loads(request.content)
            seen["headers"] = request.headers
        return httpx2.Response(200, json=message([{"type": "text", "text": text}], stop_reason))
    return handler


def test_request_uses_current_model_with_fallbacks(apple):
    seen = {}
    Commentator(anthropic_client(replying("Net margin was 26.9% in FY2025.", seen))).write([apple])
    body = seen["body"]
    assert body["model"] == MODEL == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    assert body["output_config"] == {"effort": "medium"}
    assert "Use only the numbers given" in body["system"]


def test_prompt_contains_only_computed_ratios(apple):
    prompt = build_prompt([apple])
    assert "Apple Inc. (AAPL)" in prompt
    assert "FY2025 (ended 2025-09-27)" in prompt and "Net margin 26.9%" in prompt
    assert "Interest coverage" not in prompt.split("FY2025")[1]  # n/a ratios are left out
    assert "P/E" not in prompt


def test_commentary_text_is_returned(apple):
    c = Commentator(anthropic_client(replying("Gross margin reached 46.9% in FY2025."))).write([apple])
    assert c.text == "Gross margin reached 46.9% in FY2025." and c.unverified == []


def test_numbers_not_in_the_table_are_flagged(apple):
    c = Commentator(anthropic_client(replying("Margins rose 2.1 points to 46.9%, and ROE hit 999.0%."))).write([apple])
    assert c.unverified == ["2.1", "999.0%"]


@pytest.mark.parametrize("text,flagged", [
    ("In FY2025 net margin was 26.9%.", []),
    ("Net margin of 27% in 2025.", []),               # rounder than the table, still consistent
    ("Interest coverage of 29.1x.", []),             # FY2023 value
    ("Current ratio 0.89 in FY2025.", []),
    ("Over three years, two of them improved.", []),
    ("Net margin of 30.0%.", ["30.0%"]),
    ("DSO rose to 99 days.", ["99 days"]),
])
def test_unverified_numbers(apple, text, flagged):
    assert unverified_numbers(text, [apple]) == flagged


def test_refusal_is_an_error(apple):
    with pytest.raises(CommentaryError, match="declined"):
        Commentator(anthropic_client(replying("", stop_reason="refusal"))).write([apple])


def test_empty_reply_is_an_error(apple):
    with pytest.raises(CommentaryError, match="empty"):
        Commentator(anthropic_client(replying("   "))).write([apple])


def test_bad_key_is_explained(apple):
    def handler(request):
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "bad"}})
    with pytest.raises(CommentaryError, match="ANTHROPIC_API_KEY"):
        Commentator(anthropic_client(handler)).write([apple])


def test_rate_limit_is_explained(apple):
    def handler(request):
        return httpx2.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "slow"}})
    with pytest.raises(CommentaryError, match="Rate limited"):
        Commentator(anthropic_client(handler)).write([apple])


def test_server_error_is_explained(apple):
    def handler(request):
        return httpx2.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}})
    with pytest.raises(CommentaryError, match="500"):
        Commentator(anthropic_client(handler)).write([apple])
