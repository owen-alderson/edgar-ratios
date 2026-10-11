from datetime import date

import pytest
from conftest import annual, company, fact, facts_json, instant

from edgar_ratios.facts import (
    Figure,
    Filings,
    FiscalYear,
    Missing,
    fmt_money,
    resolve,
    shares_outstanding,
    split_ratio,
)

FY = FiscalYear(2024, date(2024, 12, 31), "0000000000-24-000001", date(2025, 2, 1))


def years_of(data):
    return Filings(data).fiscal_years()


# ── Fiscal years ─────────────────────────────────────────────────────────────────────────────


def test_fiscal_years_come_from_original_10ks():
    data = company(NetIncomeLoss=[annual(1, 2022), annual(2, 2023), annual(3, 2024)])
    assert [y.fy for y in years_of(data)] == [2022, 2023, 2024]


def test_quarterly_filings_do_not_create_fiscal_years():
    data = company(NetIncomeLoss=[annual(1, 2023), fact(5, "2024-03-31", start="2024-01-01", form="10-Q", fp="Q1")])
    assert [y.fy for y in years_of(data)] == [2023]


def test_amendments_do_not_create_extra_fiscal_years():
    data = company(NetIncomeLoss=[annual(1, 2023), annual(1, 2023, form="10-K/A", accn="x-a")])
    assert len(years_of(data)) == 1


def test_fiscal_year_end_ignores_cover_page_dates_after_year_end():
    data = company(NetIncomeLoss=[annual(1, 2024)],
                   dei={"EntityCommonStockSharesOutstanding": [fact(100, "2025-02-10", fy=2024)]})
    assert years_of(data)[0].end == date(2024, 12, 31)


def test_fiscal_year_end_is_the_latest_annual_period_in_the_filing():
    # A 10-K also carries the two prior years as comparatives; its own year is the latest.
    accn = "0000000000-24-000001"
    data = company(NetIncomeLoss=[annual(1, 2022, accn=accn, fy=2024), annual(2, 2023, accn=accn, fy=2024),
                                  annual(3, 2024, accn=accn, fy=2024)])
    [y] = years_of(data)
    assert (y.fy, y.end) == (2024, date(2024, 12, 31))


def test_apple_fiscal_years_end_in_late_september():
    years = years_of(facts_json("aapl"))
    assert [(y.label, str(y.end)) for y in years[-3:]] == [
        ("FY2023", "2023-09-30"), ("FY2024", "2024-09-28"), ("FY2025", "2025-09-27")]


def test_nvidia_labels_fiscal_year_by_the_filing_not_the_calendar():
    # NVIDIA's FY2026 ended on 25 January 2026, a 52/53-week year.
    y = years_of(facts_json("nvda"))[-1]
    assert (y.label, y.end) == ("FY2026", date(2026, 1, 25))


def test_fiscal_year_label():
    assert FY.label == "FY2024"


# ── Picking one fact per year ─────────────────────────────────────────────────────────────────


def test_flow_figure_must_cover_a_full_year():
    data = company(Revenues=[fact(25, "2024-12-31", start="2024-10-01"), annual(100, 2024)])
    assert Filings(data).annual("Revenues", FY, instant=False).value == 100


def test_a_quarter_alone_is_not_an_annual_figure():
    data = company(Revenues=[fact(25, "2024-12-31", start="2024-10-01")])
    assert Filings(data).annual("Revenues", FY, instant=False) is None


def test_53_week_year_still_counts_as_annual():
    data = company(Revenues=[fact(100, "2024-12-31", start="2023-12-25")])  # 372 days
    assert Filings(data).annual("Revenues", FY, instant=False).value == 100


def test_balance_sheet_figure_must_be_dated_on_the_year_end():
    data = company(Assets=[fact(9, "2024-06-30"), instant(10, 2024)])
    assert Filings(data).annual("Assets", FY, instant=True).value == 10


def test_quarterly_report_values_are_ignored():
    data = company(Assets=[instant(10, 2024, form="10-Q")])
    assert Filings(data).annual("Assets", FY, instant=True) is None


def test_latest_filed_value_wins_and_the_restatement_is_noted():
    data = company(Revenues=[
        annual(100e6, 2024, filed="2025-02-01", accn="a-1"),
        annual(110e6, 2024, filed="2026-02-01", accn="a-2", fy=2025),
    ])
    figure = Filings(data).annual("Revenues", FY, instant=False)
    assert figure.value == 110e6
    assert figure.sources[0].accn == "a-2"
    assert "restated" in figure.notes[0]
    assert "$100.0M as first filed" in figure.notes[0] and "$110.0M in the latest" in figure.notes[0]


def test_same_value_in_later_filings_is_not_a_restatement():
    data = company(Revenues=[annual(100, 2024, filed="2025-02-01"), annual(100, 2024, filed="2026-02-01", accn="b")])
    assert Filings(data).annual("Revenues", FY, instant=False).notes == []


def test_amendment_counts_as_a_later_filing():
    data = company(NetIncomeLoss=[annual(5, 2024, filed="2025-02-01"),
                                  annual(6, 2024, form="10-K/A", filed="2025-05-01", accn="amend")])
    figure = Filings(data).annual("NetIncomeLoss", FY, instant=False)
    assert figure.value == 6 and figure.sources[0].form == "10-K/A"


def test_per_share_change_matching_a_split_is_labelled_as_a_split():
    data = company(EarningsPerShareDiluted=[annual(12.0, 2024, filed="2025-02-01"),
                                            annual(3.0, 2024, filed="2026-02-01", accn="b")])
    figure = Filings(data).annual("EarningsPerShareDiluted", FY, instant=False, unit="USD/shares")
    assert figure.value == 3.0
    assert "4-for-1 stock split" in figure.notes[0]


def test_nvidia_eps_history_is_split_adjusted():
    filings = Filings(facts_json("nvda"))
    fy2024 = next(y for y in filings.fiscal_years() if y.fy == 2024)
    eps = filings.annual("EarningsPerShareDiluted", fy2024, instant=False, unit="USD/shares")
    assert eps.value == 1.19
    assert "10-for-1 stock split" in eps.notes[0]


@pytest.mark.parametrize("before,after,expected", [
    (11.93, 1.19, 10), (4.52, 1.13, 4), (112.20, 5.61, 20), (1.74, 0.17, 10), (4.87, 1.62, 3),
    (5.0, 4.9, None), (5.0, 3.3, None), (-1.0, 0.5, None), (1.0, 0, None),
])
def test_split_ratio(before, after, expected):
    assert split_ratio(before, after) == expected


def test_units_are_kept_apart():
    data = company(EarningsPerShareDiluted=[annual(2.5, 2024)])
    assert Filings(data).annual("EarningsPerShareDiluted", FY, instant=False, unit="USD") is None


# ── Inputs ────────────────────────────────────────────────────────────────────────────────────


def full_company(**overrides):
    base = dict(
        Revenues=[annual(1000, 2024)], GrossProfit=[annual(400, 2024)], CostOfRevenue=[annual(600, 2024)],
        OperatingIncomeLoss=[annual(200, 2024)], NetIncomeLoss=[annual(150, 2024)],
        InterestExpense=[annual(10, 2024)], DepreciationDepletionAndAmortization=[annual(50, 2024)],
        EarningsPerShareDiluted=[annual(1.5, 2024)], Assets=[instant(2000, 2024)],
        AssetsCurrent=[instant(800, 2024)], CashAndCashEquivalentsAtCarryingValue=[instant(300, 2024)],
        InventoryNet=[instant(100, 2024)], AccountsReceivableNetCurrent=[instant(120, 2024)],
        LiabilitiesCurrent=[instant(400, 2024)], StockholdersEquity=[instant(900, 2024)],
        LongTermDebtNoncurrent=[instant(450, 2024)], LongTermDebtCurrent=[instant(50, 2024)],
    )
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def resolved(**overrides):
    return resolve(Filings(company(**full_company(**overrides))), FY)


def test_all_inputs_resolve_with_their_concepts():
    r = resolved()
    assert r["revenue"].value == 1000 and r["revenue"].how == "Revenues"
    assert r["ebitda"].value == 250
    assert r["total_debt"].value == 500


def test_revenue_falls_back_through_concepts_and_records_which():
    r = resolved(Revenues=None, RevenueFromContractWithCustomerExcludingAssessedTax=[annual(990, 2024)])
    assert r["revenue"].value == 990
    assert r["revenue"].how == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_first_concept_wins_when_several_are_reported():
    r = resolved(SalesRevenueNet=[annual(1, 2024)])
    assert r["revenue"].how == "Revenues"


def test_concept_can_change_from_year_to_year():
    data = company(**full_company(Revenues=[annual(1000, 2024)], SalesRevenueNet=[annual(900, 2023)]))
    fy2023 = FiscalYear(2023, date(2023, 12, 31), "x", date(2024, 2, 1))
    assert resolve(Filings(data), fy2023)["revenue"].how == "SalesRevenueNet"


def test_missing_input_says_what_was_looked_for():
    r = resolved(InventoryNet=None)
    assert isinstance(r["inventory"], Missing)
    assert "InventoryNet" in r["inventory"].reason


def test_gross_profit_derived_when_not_reported():
    r = resolved(GrossProfit=None)
    assert r["gross_profit"].value == 400
    assert r["gross_profit"].how == "Revenues − CostOfRevenue"
    assert "derived" in r["gross_profit"].notes[0]
    assert len(r["gross_profit"].sources) == 2


def test_cost_of_revenue_derived_when_not_reported():
    r = resolved(CostOfRevenue=None)
    assert r["cost_of_revenue"].value == 600
    assert "derived" in r["cost_of_revenue"].notes[0]


def test_gross_profit_missing_when_neither_can_be_built():
    r = resolved(GrossProfit=None, CostOfRevenue=None)
    assert isinstance(r["gross_profit"], Missing)


def test_ebitda_is_operating_income_plus_da():
    r = resolved()
    assert r["ebitda"].how == "OperatingIncomeLoss + D&A"
    assert {s.concept for s in r["ebitda"].sources} == {"OperatingIncomeLoss", "DepreciationDepletionAndAmortization"}


def test_ebitda_missing_explains_which_part():
    r = resolved(DepreciationDepletionAndAmortization=None)
    assert isinstance(r["ebitda"], Missing)
    assert "Depreciation & amortization" in r["ebitda"].reason


def test_da_built_from_depreciation_plus_amortization():
    r = resolved(DepreciationDepletionAndAmortization=None, Depreciation=[annual(40, 2024)],
                 AmortizationOfIntangibleAssets=[annual(5, 2024)])
    assert r["depreciation_amortization"].value == 45
    assert "separately reported" in r["depreciation_amortization"].notes[0]


def test_depreciation_alone_is_used_with_a_warning():
    r = resolved(DepreciationDepletionAndAmortization=None, Depreciation=[annual(40, 2024)])
    assert r["depreciation_amortization"].value == 40
    assert "understated" in r["depreciation_amortization"].notes[0]


def test_cash_falls_back_to_restricted_cash_with_a_note():
    r = resolved(CashAndCashEquivalentsAtCarryingValue=None,
                 CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents=[instant(310, 2024)])
    assert r["cash"].value == 310
    assert "restricted" in r["cash"].notes[0]


def test_interest_expense_falls_back_to_nonoperating():
    r = resolved(InterestExpense=None, InterestExpenseNonoperating=[annual(12, 2024)])
    assert r["interest_expense"].value == 12


# ── Total debt ────────────────────────────────────────────────────────────────────────────────


def test_debt_adds_short_term_borrowings():
    r = resolved(ShortTermBorrowings=[instant(30, 2024)])
    assert r["total_debt"].value == 530
    assert r["total_debt"].how.endswith("+ ShortTermBorrowings")


def test_debt_uses_commercial_paper_when_no_short_term_borrowings():
    r = resolved(CommercialPaper=[instant(20, 2024)])
    assert r["total_debt"].value == 520


def test_short_term_borrowings_preferred_over_commercial_paper_to_avoid_double_counting():
    r = resolved(ShortTermBorrowings=[instant(30, 2024)], CommercialPaper=[instant(20, 2024)])
    assert r["total_debt"].value == 530


def test_debt_notes_when_no_short_term_debt_is_reported():
    r = resolved()
    assert any("No short-term borrowings" in n for n in r["total_debt"].notes)


def test_debt_falls_back_to_long_term_debt_total():
    r = resolved(LongTermDebtNoncurrent=None, LongTermDebtCurrent=None, LongTermDebt=[instant(480, 2024)])
    assert r["total_debt"].value == 480 and r["total_debt"].how.startswith("LongTermDebt")


def test_debt_with_lease_obligations_is_flagged():
    r = resolved(LongTermDebtNoncurrent=None, LongTermDebtCurrent=[instant(50, 2024)],
                 LongTermDebtAndCapitalLeaseObligations=[instant(470, 2024)])
    assert r["total_debt"].value == 520
    assert any("finance lease" in n for n in r["total_debt"].notes)


def test_noncurrent_only_debt_warns_it_may_be_understated():
    r = resolved(LongTermDebtCurrent=None)
    assert r["total_debt"].value == 450
    assert any("understated" in n for n in r["total_debt"].notes)


def test_no_long_term_debt_means_debt_is_unavailable_not_zero():
    r = resolved(LongTermDebtNoncurrent=None, LongTermDebtCurrent=None, ShortTermBorrowings=[instant(30, 2024)])
    assert isinstance(r["total_debt"], Missing)


def test_bank_has_no_classified_balance_sheet():
    filings = Filings(facts_json("jpm"))
    r = resolve(filings, filings.fiscal_years()[-1])
    assert isinstance(r["current_assets"], Missing)
    assert isinstance(r["total_debt"], Missing)
    assert isinstance(r["net_income"], Figure)


# ── Shares and formatting ─────────────────────────────────────────────────────────────────────


def test_shares_prefer_the_cover_page_figure():
    data = company(CommonStockSharesOutstanding=[instant(90, 2024)],
                   dei={"EntityCommonStockSharesOutstanding": [fact(100, "2025-02-10", form="10-K")]})
    s = shares_outstanding(Filings(data))
    assert s.value == 100 and s.how == "EntityCommonStockSharesOutstanding"
    assert "2025-02-10" in s.notes[0]


def test_shares_use_the_most_recent_date_from_any_form():
    data = company(dei={"EntityCommonStockSharesOutstanding": [
        fact(100, "2025-02-10", form="10-K"), fact(98, "2025-07-20", form="10-Q", filed="2025-07-30")]})
    assert shares_outstanding(Filings(data)).value == 98


def test_shares_fall_back_to_balance_sheet_count():
    s = shares_outstanding(Filings(facts_json("googl")))
    assert s.how == "CommonStockSharesOutstanding" and s.value > 1e10


def test_conflicting_share_counts_on_one_date_are_not_guessed():
    data = company(dei={"EntityCommonStockSharesOutstanding": [fact(100, "2025-02-10"), fact(40, "2025-02-10", accn="b")]})
    assert isinstance(shares_outstanding(Filings(data)), Missing)


def test_no_share_count_is_missing():
    assert isinstance(shares_outstanding(Filings(company(Revenues=[annual(1, 2024)]))), Missing)


def test_filing_url_points_at_the_filing_index():
    f = Filings(facts_json("aapl")).annual("Assets", Filings(facts_json("aapl")).fiscal_years()[-1], instant=True)
    url = f.sources[0].filing_url(320193)
    assert url.startswith("https://www.sec.gov/Archives/edgar/data/320193/") and url.endswith("-index.htm")


@pytest.mark.parametrize("value,unit,text", [
    (383_285_000_000, "USD", "$383.3B"), (3_933_000_000, "USD", "$3.9B"), (250_000_000, "USD", "$250.0M"),
    (-2_137_000_000, "USD", "-$2.1B"), (5_000, "USD", "$5,000"), (6.13, "USD/shares", "$6.13"),
    (14_594_180_000, "shares", "14,594.2M shares"),
])
def test_fmt_money(value, unit, text):
    assert fmt_money(value, unit) == text
