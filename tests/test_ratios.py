from datetime import date

import pytest

from edgar_ratios.facts import Figure, Missing
from edgar_ratios.ratios import (
    CATEGORIES,
    NO_PRICE,
    OLD_YEAR,
    RATIOS,
    Price,
    analyze,
    compute,
    market_inputs,
)
from edgar_ratios.sec import SecError

PRICE = Price(200.0, date(2026, 10, 11))


def by_name(values):
    return {v.ratio.name: v for v in values}


def fig(value):
    return Figure(value, "Test", [])


def inputs(**overrides):
    base = dict(
        revenue=1000, gross_profit=400, cost_of_revenue=600, operating_income=200, net_income=150,
        interest_expense=10, eps_diluted=1.5, total_assets=2000, current_assets=800, cash=300,
        inventory=100, receivables=120, current_liabilities=400, equity=900, total_debt=500, ebitda=250,
    )
    base.update(overrides)
    return {k: (v if isinstance(v, Missing) else fig(v)) for k, v in base.items()}


# ── Golden values from Apple's real filings ──────────────────────────────────────────────────


@pytest.fixture
def apple(sec):
    return analyze(sec, "AAPL", years=5)


def year(analysis, fy):
    return next(yr for yr in analysis.years if yr.year.fy == fy)


def test_apple_fy2023_matches_the_10k(apple):
    v = by_name(year(apple, 2023).values)
    assert v["Net margin"].value == pytest.approx(96_995 / 383_285 * 100)        # 25.3%
    assert v["Interest coverage"].value == pytest.approx(114_301 / 3_933)        # 29.1x
    assert v["Gross margin"].value == pytest.approx(169_148 / 383_285 * 100)      # 44.1%
    assert v["Current ratio"].value == pytest.approx(143_566 / 145_308)           # 0.99
    assert v["Debt/Equity"].value == pytest.approx((95_281 + 9_822 + 5_985) / 62_146)


def test_apple_interest_coverage_unavailable_once_interest_stops_being_tagged(apple):
    v = by_name(year(apple, 2025).values)["Interest coverage"]
    assert v.value is None and "Interest expense not reported" in v.reason


def test_apple_has_five_years_and_all_ratios(apple):
    assert [yr.year.fy for yr in apple.years] == [2021, 2022, 2023, 2024, 2025]
    assert all(len(yr.values) == len(RATIOS) for yr in apple.years)


def test_without_a_price_valuation_says_why(apple):
    v = by_name(apple.latest.values)["P/E"]
    assert v.value is None and v.reason == NO_PRICE


def test_with_a_price_only_the_latest_year_is_valued(sec):
    a = analyze(sec, "AAPL", years=3, price=PRICE)
    assert by_name(a.latest.values)["P/E"].value == pytest.approx(200 / 7.46)
    assert by_name(a.years[0].values)["P/E"].reason == OLD_YEAR
    assert "your price" in a.notes[0]


def test_market_cap_uses_latest_shares_outstanding(sec):
    a = analyze(sec, "AAPL", years=1, price=PRICE)
    shares = a.shares.value
    assert by_name(a.latest.values)["P/S"].value == pytest.approx(200 * shares / 416_161e6)


def test_bank_profitability_works_but_industrial_ratios_explain_themselves(sec):
    a = analyze(sec, "JPM", years=1)
    v = by_name(a.latest.values)
    assert v["ROE"].value is not None
    assert v["Current ratio"].value is None and "Current assets" in v["Current ratio"].reason
    assert v["Debt/Equity"].value is None and "long-term debt" in v["Debt/Equity"].reason


def test_years_option_limits_history(sec):
    assert len(analyze(sec, "NVDA", years=2).years) == 2


def test_unknown_company_facts_are_a_clear_error(sec, fetch):
    fetch.missing.add("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
    with pytest.raises(SecError, match="no XBRL financial data"):
        analyze(sec, "AAPL")


def test_company_without_10ks_is_explained(sec, fetch, tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"cik": 320193, "entityName": "Apple Inc.", "facts": {}}')
    fetch.routes["https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"] = empty
    with pytest.raises(SecError, match="no 10-K annual reports"):
        analyze(sec, "AAPL")


# ── Formula rules ─────────────────────────────────────────────────────────────────────────────


def test_there_are_23_ratios_in_five_categories():
    assert len(RATIOS) == 23
    assert {r.category for r in RATIOS} == set(CATEGORIES)


@pytest.mark.parametrize("name,expected", [
    ("Gross margin", 40.0), ("EBITDA margin", 25.0), ("Operating margin", 20.0), ("Net margin", 15.0),
    ("ROE", 150 / 900 * 100), ("ROA", 7.5), ("ROIC", 150 / 1400 * 100),
    ("Current ratio", 2.0), ("Quick ratio", 1.75), ("Cash ratio", 0.75),
    ("Debt/Equity", 500 / 900), ("Net debt/EBITDA", 0.8), ("Debt/Assets", 25.0), ("Interest coverage", 20.0),
    ("Asset turnover", 0.5), ("Inventory turnover", 6.0), ("Days inventory", 100 / 600 * 365),
    ("Days sales outstanding", 120 / 1000 * 365),
])
def test_formula(name, expected):
    assert by_name(compute(inputs(), NO_PRICE))[name].value == pytest.approx(expected)


def test_missing_input_carries_its_reason_to_the_ratio():
    v = by_name(compute(inputs(inventory=Missing("Inventory not reported")), NO_PRICE))
    assert v["Inventory turnover"].reason == "Inventory not reported"
    assert "needs inventory" in v["Quick ratio"].reason


def test_zero_denominator_is_explained():
    v = by_name(compute(inputs(interest_expense=0), NO_PRICE))["Interest coverage"]
    assert v.value is None and v.reason == "Interest expense is zero"


def test_negative_equity_makes_return_ratios_not_meaningful():
    v = by_name(compute(inputs(equity=-50), NO_PRICE))
    assert v["ROE"].value is None and "negative" in v["ROE"].reason
    assert v["Debt/Equity"].value is None


def test_negative_numerator_is_fine():
    assert by_name(compute(inputs(net_income=-100), NO_PRICE))["Net margin"].value == pytest.approx(-10.0)


def test_net_cash_gives_negative_net_debt_ratio():
    assert by_name(compute(inputs(cash=600), NO_PRICE))["Net debt/EBITDA"].value == pytest.approx(-0.4)


def test_valuation_reason_applies_only_to_valuation():
    values = compute(inputs(), "no price")
    assert all(v.reason == "no price" for v in values if v.ratio.category == "Valuation")
    assert all(v.value is not None for v in values if v.ratio.category != "Valuation")


# ── Valuation inputs ──────────────────────────────────────────────────────────────────────────


def test_market_inputs_build_cap_and_enterprise_value():
    base = inputs()
    m = market_inputs(base, PRICE, Figure(100, "EntityCommonStockSharesOutstanding", []))
    assert m["market_cap"].value == 20_000
    assert m["enterprise_value"].value == 20_000 + 500 - 300
    v = by_name(compute({**base, **m}))
    assert v["P/E"].value == pytest.approx(200 / 1.5)
    assert v["EV/EBITDA"].value == pytest.approx(20_200 / 250)
    assert v["P/B"].value == pytest.approx(20_000 / 900)


def test_enterprise_value_cites_shares_debt_and_cash(sec):
    a = analyze(sec, "AAPL", years=1, price=PRICE)
    concepts = {s.concept for s in a.latest.inputs["enterprise_value"].sources}
    assert {"EntityCommonStockSharesOutstanding", "LongTermDebtNoncurrent",
            "CashAndCashEquivalentsAtCarryingValue"} <= concepts


def test_price_is_labelled_as_yours():
    m = market_inputs(inputs(), PRICE, Figure(100, "x", []))
    assert "supplied by you" in m["price"].notes[0]


def test_no_shares_means_no_market_cap_but_pe_still_works():
    m = market_inputs(inputs(), PRICE, Missing("no share count"))
    v = by_name(compute({**inputs(), **m}))
    assert v["P/B"].value is None and "no share count" in v["P/B"].reason
    assert v["P/E"].value is not None


def test_missing_debt_blocks_enterprise_value():
    base = inputs(total_debt=Missing("no debt reported"))
    m = market_inputs(base, PRICE, Figure(100, "x", []))
    assert isinstance(m["enterprise_value"], Missing) and "no debt reported" in m["enterprise_value"].reason


def test_split_after_the_10k_blocks_pe():
    # 10-K EPS implies 100 shares; 400 are outstanding now: a 4-for-1 split since.
    m = market_inputs(inputs(), PRICE, Figure(400, "x", []))
    v = by_name(compute({**inputs(), **m}))["P/E"]
    assert v.value is None and "stock split" in v.reason


def test_negative_eps_makes_pe_not_meaningful():
    m = market_inputs(inputs(eps_diluted=-1.0, net_income=-100), PRICE, Figure(100, "x", []))
    v = by_name(compute({**inputs(eps_diluted=-1.0, net_income=-100), **m}))["P/E"]
    assert v.value is None and "negative" in v.reason
