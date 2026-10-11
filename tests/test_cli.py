import csv
import io
import json
from datetime import date

import pytest
from rich.console import Console

from edgar_ratios import config
from edgar_ratios.__main__ import UsageError, main, parse_prices
from edgar_ratios.commentary import Commentary, CommentaryError

TODAY = date(2026, 10, 11)


def run(argv, sec=None, commentator=None):
    console = Console(file=io.StringIO(), width=160, color_system=None)
    code = main(argv, sec=sec, console=console, commentator=commentator, today=TODAY)
    return code, console.file.getvalue()


def test_single_ticker_table(sec):
    code, out = run(["AAPL"], sec)
    assert code == 0 and "Apple Inc." in out and "FY2021" in out


def test_years_option(sec):
    code, out = run(["AAPL", "--years", "2"], sec)
    assert code == 0 and "FY2024" in out and "FY2023" not in out


def test_several_tickers_compare_latest_years(sec):
    code, out = run(["aapl", "msft"], sec)
    assert code == 0 and "their years end on different dates" in out


def test_duplicate_tickers_are_collapsed(sec, fetch):
    run(["AAPL", "aapl"], sec)
    assert sum("CIK0000320193" in u for u, _ in fetch.calls) == 1


def test_price_adds_valuation(sec):
    code, out = run(["AAPL", "--price", "200"], sec)
    assert code == 0 and "P/E" in out


def test_json_output(sec, capsys):
    code, _ = run(["AAPL", "--years", "1", "--format", "json"], sec)
    data = json.loads(capsys.readouterr().out)
    assert code == 0 and data[0]["ticker"] == "AAPL"


def test_csv_output(sec, capsys):
    code, _ = run(["AAPL", "MSFT", "--format", "csv"], sec)
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert code == 0 and {r["ticker"] for r in rows} == {"AAPL", "MSFT"}


def test_html_report_is_written(sec, tmp_path):
    path = tmp_path / "r.html"
    code, _ = run(["AAPL", "--html", str(path)], sec)
    assert code == 0 and "Apple Inc." in path.read_text()


def test_sources_flag(sec):
    _, out = run(["AAPL", "--years", "1", "--sources"], sec)
    assert "Sources: Apple Inc." in out


def test_commentary_is_printed_with_unverified_numbers(sec):
    class Fake:
        def write(self, analyses):
            return Commentary("Margins look strong.", ["12.3%"])

    code, out = run(["AAPL", "--commentary"], sec, Fake())
    assert code == 0 and "Margins look strong." in out and "12.3%" in out


def test_commentary_error_exits_cleanly(sec):
    class Failing:
        def write(self, analyses):
            raise CommentaryError("Anthropic API key missing or invalid")

    code, _ = run(["AAPL", "--commentary"], sec, Failing())
    assert code == 1


def test_unknown_ticker_exits_with_message(sec, capsys):
    code, _ = run(["ZZZZ"], sec)
    assert code == 1 and "Unknown ticker" in capsys.readouterr().err


def test_no_tickers_is_a_usage_error(sec, capsys):
    code, _ = run([], sec)
    assert code == 2 and "at least one ticker" in capsys.readouterr().err


def test_years_must_be_positive(sec):
    assert run(["AAPL", "--years", "0"], sec)[0] == 2


def test_set_user_agent_saves_and_exits():
    code, out = run(["--set-user-agent", "Jane Doe jane@example.com"])
    assert code == 0 and "Saved" in out
    assert config.user_agent(interactive=False) == "Jane Doe jane@example.com"


def test_set_user_agent_rejects_values_without_email(capsys):
    code, _ = run(["--set-user-agent", "just-a-name"])
    assert code == 1 and "email" in capsys.readouterr().err


def test_missing_user_agent_outside_a_terminal_explains(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    code, _ = run(["AAPL"])
    assert code == 1 and "--set-user-agent" in capsys.readouterr().err


# ── Prices ────────────────────────────────────────────────────────────────────────────────────


def test_bare_price_for_one_ticker():
    p = parse_prices(["227.50"], ["AAPL"], TODAY)
    assert p["AAPL"].value == 227.5 and p["AAPL"].as_of == TODAY


def test_ticker_prices_for_several():
    p = parse_prices(["aapl=227.5", "MSFT=$1,010"], ["AAPL", "MSFT"], TODAY)
    assert p["AAPL"].value == 227.5 and p["MSFT"].value == 1010


@pytest.mark.parametrize("raw,tickers,message", [
    (["227"], ["AAPL", "MSFT"], "TICKER=PRICE"),
    (["NVDA=1"], ["AAPL"], "isn't one of the tickers"),
    (["AAPL=abc"], ["AAPL"], "Not a price"),
    (["AAPL=-5"], ["AAPL"], "positive"),
])
def test_bad_prices(raw, tickers, message):
    with pytest.raises(UsageError, match=message):
        parse_prices(raw, tickers, TODAY)


def test_bad_price_exits_2(sec):
    assert run(["AAPL", "MSFT", "--price", "100"], sec)[0] == 2
