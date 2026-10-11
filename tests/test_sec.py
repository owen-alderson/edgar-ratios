import gzip
import json
import os
import time

import pytest
from conftest import FakeFetch

from edgar_ratios.sec import FACTS_URL, MIN_INTERVAL, TICKERS_URL, Sec, SecError, _http_message, _urllib_fetch


def test_lookup_maps_ticker_to_cik_and_name(sec):
    c = sec.lookup("aapl")
    assert (c.cik, c.ticker, c.name) == (320193, "AAPL", "Apple Inc.")


def test_lookup_accepts_dotted_class_tickers(sec):
    assert sec.lookup("BRK.B").ticker == "BRK-B"


def test_unknown_ticker_is_a_clear_error(sec):
    with pytest.raises(SecError, match="Unknown ticker 'ZZZZ'"):
        sec.lookup("ZZZZ")


def test_every_request_sends_the_user_agent(sec, fetch):
    sec.lookup("AAPL")
    sec.company_facts(320193)
    assert all(h["User-Agent"] == "Test Person test@example.com" for _, h in fetch.calls)
    assert all(h["Accept-Encoding"] == "gzip" for _, h in fetch.calls)


def test_ticker_list_is_fetched_once_per_run(sec, fetch):
    sec.lookup("AAPL")
    sec.lookup("MSFT")
    assert [u for u, _ in fetch.calls] == [TICKERS_URL]


def test_company_facts_are_cached_on_disk(tmp_path, fetch):
    first = Sec("T t@example.com", tmp_path, fetch=fetch, sleep=lambda s: None)
    data, fetched = first.company_facts(320193)
    second = Sec("T t@example.com", tmp_path, fetch=fetch, sleep=lambda s: None)
    again, _ = second.company_facts(320193)
    assert data == again
    assert len(fetch.calls) == 1
    assert (tmp_path / "companyfacts-0000320193.json").exists()
    assert fetched.tzinfo is not None


def test_stale_cache_is_refetched(tmp_path, fetch):
    Sec("T t@example.com", tmp_path, fetch=fetch).company_facts(320193)
    path = tmp_path / "companyfacts-0000320193.json"
    old = time.time() - 2 * 24 * 3600
    os.utime(path, (old, old))
    Sec("T t@example.com", tmp_path, fetch=fetch, sleep=lambda s: None).company_facts(320193)
    assert len(fetch.calls) == 2


def test_refresh_ignores_the_cache(tmp_path, fetch):
    Sec("T t@example.com", tmp_path, fetch=fetch).company_facts(320193)
    Sec("T t@example.com", tmp_path, fetch=fetch, refresh=True, sleep=lambda s: None).company_facts(320193)
    assert len(fetch.calls) == 2


def test_broken_cache_file_is_refetched(tmp_path, fetch):
    (tmp_path / "companyfacts-0000320193.json").write_text("{not json")
    data, _ = Sec("T t@example.com", tmp_path, fetch=fetch).company_facts(320193)
    assert data["entityName"] == "Apple Inc."
    assert len(fetch.calls) == 1


def test_requests_are_spaced_to_stay_under_ten_per_second(tmp_path, fetch):
    clock = iter([0.0, 0.02, 0.2]).__next__
    sleeps = []
    sec = Sec("T t@example.com", tmp_path, fetch=fetch, clock=clock, sleep=sleeps.append, refresh=True)
    sec.company_facts(320193)
    sec.company_facts(1045810)
    assert sleeps == [pytest.approx(MIN_INTERVAL - 0.02)]


def test_non_json_response_is_an_error(tmp_path):
    sec = Sec("T t@example.com", tmp_path, fetch=lambda url, h: b"<html>blocked</html>")
    with pytest.raises(SecError, match="isn't JSON"):
        sec.company_facts(1)


def test_http_errors_explain_what_to_do():
    assert "User-Agent" in _http_message(403, "u")
    assert "rate-limited" in _http_message(429, "u")
    assert "Not found" in _http_message(404, "u")
    assert "HTTP 500" in _http_message(500, "u")


def test_urllib_fetch_decompresses_gzip(monkeypatch):
    class Response:
        headers = {"Content-Encoding": "gzip"}

        def read(self):
            return gzip.compress(json.dumps({"ok": 1}).encode())

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def urlopen(request, timeout, context):
        seen["ua"] = request.get_header("User-agent")
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert json.loads(_urllib_fetch("https://x", {"User-Agent": "A a@b.co"})) == {"ok": 1}
    assert seen["ua"] == "A a@b.co"


def test_urllib_fetch_maps_http_errors(monkeypatch):
    import urllib.error

    def urlopen(request, timeout, context):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(SecError, match="403"):
        _urllib_fetch("https://x", {})


def test_urllib_fetch_maps_network_errors(monkeypatch):
    import urllib.error

    def urlopen(request, timeout, context):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(SecError, match="Could not reach the SEC"):
        _urllib_fetch("https://x", {})


def test_facts_url_pads_cik_to_ten_digits():
    assert FACTS_URL.format(cik=320193).endswith("CIK0000320193.json")


def test_missing_company_facts_raise(tmp_path):
    fetch = FakeFetch(missing={FACTS_URL.format(cik=320193)})
    with pytest.raises(SecError, match="Not found"):
        Sec("T t@example.com", tmp_path, fetch=fetch).company_facts(320193)
