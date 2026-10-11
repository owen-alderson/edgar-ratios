import json
from pathlib import Path

import httpx2
import pytest

from edgar_ratios.sec import FACTS_URL, TICKERS_URL, Sec

FIXTURES = Path(__file__).parent / "fixtures"
CIKS = {320193: "aapl", 1045810: "nvda", 19617: "jpm", 1652044: "googl", 789019: "msft"}


class FakeFetch:
    """Serves the trimmed real EDGAR fixtures by URL and records every request."""

    def __init__(self, missing=(), error=None):
        self.calls, self.missing, self.error = [], set(missing), error
        self.routes = {TICKERS_URL: FIXTURES / "company_tickers.json"}
        for cik, name in CIKS.items():
            self.routes[FACTS_URL.format(cik=cik)] = FIXTURES / f"{name}.json"

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        if url in self.missing or url not in self.routes:
            from edgar_ratios.sec import SecError, _http_message

            raise SecError(_http_message(404, url))
        return self.routes[url].read_bytes()


@pytest.fixture
def fetch():
    return FakeFetch()


@pytest.fixture
def sec(tmp_path, fetch):
    return Sec("Test Person test@example.com", tmp_path / "cache", fetch=fetch, sleep=lambda s: None)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR_RATIOS_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("EDGAR_RATIOS_USER_AGENT", raising=False)


def facts_json(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ── Synthetic company facts, for testing one rule at a time ────────────────────────────────────


def fact(val, end, start=None, form="10-K", fy=None, filed=None, accn=None, fp="FY"):
    year = int(end[:4])
    return {
        "val": val, "end": end, **({"start": start} if start else {}), "form": form, "fp": fp,
        "fy": fy or year, "filed": filed or f"{year}-11-01", "accn": accn or f"0000000000-{year % 100:02d}-000001",
    }


def annual(val, year, **kw):
    """A full-year flow fact for a calendar fiscal year."""
    return fact(val, f"{year}-12-31", start=f"{year}-01-01", **kw)


def instant(val, year, **kw):
    return fact(val, f"{year}-12-31", **kw)


def company(**concepts):
    """company(Revenues=[annual(...), ...], dei={"EntityCommonStockSharesOutstanding": [...]})"""
    dei = concepts.pop("dei", {})
    units = {"EarningsPerShareDiluted": "USD/shares", "CommonStockSharesOutstanding": "shares"}
    gaap = {c: {"units": {units.get(c, "USD"): facts}} for c, facts in concepts.items()}
    out = {"cik": 1, "entityName": "Test Co", "facts": {"us-gaap": gaap}}
    if dei:
        out["facts"]["dei"] = {c: {"units": {"shares": facts}} for c, facts in dei.items()}
    return out


# ── Claude ─────────────────────────────────────────────────────────────────────────────────────


def anthropic_client(handler):
    """A real Anthropic SDK client whose HTTP goes to `handler(request) -> httpx2.Response`."""
    import anthropic

    return anthropic.Anthropic(api_key="sk-test", max_retries=0,
                               http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def message(content, stop_reason="end_turn"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}
