import csv
import io
import json
import re
from datetime import date

import pytest
from rich.console import Console

from edgar_ratios.export import to_csv, to_json
from edgar_ratios.ratios import RATIOS, Price, Value, analyze
from edgar_ratios.render import fmt_value, print_all
from edgar_ratios.report import to_html

PRICE = Price(200.0, date(2026, 10, 11))


def render(analyses, sources=False):
    console = Console(file=io.StringIO(), width=160, color_system=None)
    print_all(analyses, sources, console)
    return console.file.getvalue()


def ratio(name):
    return next(r for r in RATIOS if r.name == name)


@pytest.mark.parametrize("name,value,text", [
    ("Net margin", 25.306, "25.3%"), ("Interest coverage", 29.06, "29.1x"), ("Debt/Equity", 0.0912, "0.09x"),
    ("Net debt/EBITDA", -0.016, "-0.02x"), ("Current ratio", 0.988, "0.99"), ("Days inventory", 124.9, "125 days"),
])
def test_fmt_value(name, value, text):
    assert fmt_value(Value(ratio(name), value)) == text


def test_fmt_value_unavailable():
    assert fmt_value(Value(ratio("P/E"), None, "why")) == "n/a"


# ── Terminal ──────────────────────────────────────────────────────────────────────────────────


def test_company_view_shows_years_values_and_source(sec):
    out = render([analyze(sec, "AAPL")])
    assert "Apple Inc." in out and "CIK 0000320193" in out
    assert "FY2021" in out and "FY2025" in out
    assert "25.3%" in out and "29.1x" in out
    assert "10-K filings only" in out


def test_company_view_explains_what_is_unavailable(sec):
    out = render([analyze(sec, "AAPL")])
    assert "Not available" in out
    assert re.search(r"Interest coverage \(FY2024, FY2025\): Interest expense not reported", out)


def test_company_view_without_price_asks_for_one_instead_of_a_wall_of_na(sec):
    out = render([analyze(sec, "AAPL")])
    assert "pass --price" in out
    assert "P/E" not in out


def test_company_view_with_price_shows_valuation_and_its_basis(sec):
    out = render([analyze(sec, "AAPL", price=PRICE)])
    assert "P/E" in out and "26.8x" in out
    assert "your price ($200.00" in out


def test_company_view_lists_restatements_and_derivations(sec):
    out = render([analyze(sec, "GOOGL")])
    assert "Gross profit derived as revenue minus cost of revenue" in out


def test_split_notes_show_in_the_view(sec):
    out = " ".join(render([analyze(sec, "NVDA")]).split())
    assert "10-for-1 stock split" in out


def test_peers_view_compares_latest_years(sec):
    out = render([analyze(sec, t, years=1) for t in ("AAPL", "MSFT", "JPM")])
    assert "AAPL" in out and "MSFT" in out and "JPM" in out
    assert "their years end on different dates" in out
    assert "Current ratio (JPM)" in out


def test_peers_view_without_prices_skips_valuation(sec):
    out = render([analyze(sec, t, years=1) for t in ("AAPL", "MSFT")])
    assert "TICKER=PRICE" in out and "EV/EBITDA" not in out


def test_sources_view_names_concepts_and_filings(sec):
    out = render([analyze(sec, "AAPL", years=1)], sources=True)
    assert "Sources: Apple Inc." in out
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in out
    assert "10-K filed 2025-10-31" in out


# ── JSON / CSV ────────────────────────────────────────────────────────────────────────────────


def test_json_has_every_ratio_with_provenance(sec):
    [d] = json.loads(to_json([analyze(sec, "AAPL", years=2)]))
    assert d["ticker"] == "AAPL" and d["cik"] == "0000320193"
    year = d["years"][-1]
    assert len(year["ratios"]) == 23
    revenue = year["inputs"]["revenue"]
    assert revenue["sources"][0]["concept"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue["sources"][0]["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    interest = year["inputs"]["interest_expense"]
    assert interest["value"] is None and "not reported" in interest["unavailable"]


def test_json_records_the_price_source(sec):
    [d] = json.loads(to_json([analyze(sec, "AAPL", years=1, price=PRICE)]))
    assert d["price"] == {"value": 200.0, "as_of": "2026-10-11", "source": "supplied by the user"}


def test_csv_has_one_row_per_ratio_per_year(sec):
    rows = list(csv.DictReader(io.StringIO(to_csv([analyze(sec, "AAPL", years=2)]))))
    assert len(rows) == 2 * 23
    net = next(r for r in rows if r["fiscal_year"] == "2025" and r["ratio"] == "Net margin")
    assert float(net["value"]) == pytest.approx(112_010 / 416_161 * 100, rel=1e-6)
    pe = next(r for r in rows if r["ratio"] == "P/E")
    assert pe["value"] == "" and "price" in pe["unavailable"]


# ── HTML ──────────────────────────────────────────────────────────────────────────────────────


def test_html_report_is_self_contained_and_linked(sec):
    html = to_html([analyze(sec, "AAPL", years=2)])
    assert html.startswith("<!doctype html>")
    assert "<script" not in html and 'src="http' not in html and "stylesheet" not in html
    assert "https://www.sec.gov/Archives/edgar/data/320193/" in html
    assert "FY2025" in html and "26.9%" in html


def test_html_escapes_company_names(sec):
    a = analyze(sec, "AAPL", years=1)
    a.company = type(a.company)(a.company.cik, "AAPL", "Apple <script>alert(1)</script>")
    html = to_html([a])
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_html_shows_reasons_and_notes(sec):
    html = to_html([analyze(sec, "AAPL")])
    assert "Not available" in html and "Interest expense not reported" in html
    assert "need a share price" in html


def test_html_includes_commentary_when_given(sec):
    html = to_html([analyze(sec, "AAPL", years=1)], "First point.\n\nSecond & last.")
    assert "Commentary" in html and "<p>Second &amp; last.</p>" in html


def test_html_peer_title(sec):
    html = to_html([analyze(sec, t, years=1) for t in ("AAPL", "MSFT")])
    assert "<title>AAPL vs MSFT financial ratios</title>" in html
