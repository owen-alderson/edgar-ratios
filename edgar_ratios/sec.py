"""SEC EDGAR client: ticker lookup and XBRL company facts, cached on disk and rate limited."""

import gzip
import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import certifi

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

TICKERS_TTL = 7 * 24 * 3600
FACTS_TTL = 24 * 3600
MIN_INTERVAL = 0.11  # the SEC allows at most 10 requests a second


class SecError(Exception):
    pass


@dataclass(frozen=True)
class Company:
    cik: int
    ticker: str
    name: str


def _urllib_fetch(url: str, headers: dict) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    # certifi's CA bundle: python.org builds on macOS ship without system certificates.
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body
    except urllib.error.HTTPError as e:
        raise SecError(_http_message(e.code, url)) from e
    except urllib.error.URLError as e:
        raise SecError(f"Could not reach the SEC ({e.reason}).") from e


def _http_message(code: int, url: str) -> str:
    if code == 403:
        return ("The SEC refused the request (403). Check your User-Agent has a real name and email: "
                "edgar-ratios --set-user-agent \"Your Name you@example.com\".")
    if code == 404:
        return f"Not found on EDGAR: {url}"
    if code == 429:
        return "The SEC rate-limited this machine (429). Wait a minute and try again."
    return f"SEC returned HTTP {code} for {url}"


class Sec:
    """`fetch(url, headers) -> bytes` and `clock`/`sleep` are injectable so tests never touch the network."""

    def __init__(self, user_agent: str, cache_dir: Path, refresh: bool = False,
                 fetch=_urllib_fetch, clock=time.monotonic, sleep=time.sleep, now=time.time):
        self.user_agent, self.cache_dir, self.refresh = user_agent, Path(cache_dir), refresh
        self._fetch, self._clock, self._sleep, self._now = fetch, clock, sleep, now
        self._last_request: float | None = None
        self._tickers: dict | None = None

    def _get(self, url: str) -> bytes:
        if self._last_request is not None:
            wait = MIN_INTERVAL - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()
        return self._fetch(url, {"User-Agent": self.user_agent, "Accept-Encoding": "gzip"})

    def _cached_json(self, name: str, url: str, ttl: int) -> tuple[dict, datetime]:
        path = self.cache_dir / name
        if not self.refresh and path.exists() and self._now() - path.stat().st_mtime < ttl:
            try:
                return json.loads(path.read_text()), _mtime(path)
            except json.JSONDecodeError:
                pass  # a broken cache file is refetched
        body = self._get(url)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise SecError(f"The SEC sent something that isn't JSON for {url}.") from e
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return data, _mtime(path)

    def lookup(self, ticker: str) -> Company:
        if self._tickers is None:
            data, _ = self._cached_json("company_tickers.json", TICKERS_URL, TICKERS_TTL)
            self._tickers = {row["ticker"].upper(): row for row in data.values()}
        key = ticker.strip().upper()
        row = self._tickers.get(key) or self._tickers.get(key.replace(".", "-"))
        if row is None:
            raise SecError(f"Unknown ticker {ticker!r}: it isn't in the SEC's ticker list.")
        return Company(cik=int(row["cik_str"]), ticker=row["ticker"].upper(), name=row["title"])

    def company_facts(self, cik: int) -> tuple[dict, datetime]:
        """Every XBRL fact the company has filed, and when this copy was fetched from the SEC."""
        return self._cached_json(f"companyfacts-{cik:010d}.json", FACTS_URL.format(cik=cik), FACTS_TTL)


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
