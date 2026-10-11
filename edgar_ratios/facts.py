"""Turn the SEC's XBRL company facts into the annual figures the ratios need, each with its source.

Rules (all in one place so they can be read and tested):

- Fiscal years come from the company's original 10-K filings: each 10-K's latest period end is that
  fiscal year's end, labelled with the fiscal year the filing itself states.
- A flow figure (revenue, net income) must cover one annual period, 350-380 days, ending on that
  date. A balance-sheet figure must be dated exactly on it. Only 10-K and 10-K/A facts count.
- The same figure is usually reported again in later 10-Ks as a comparative. The most recently
  filed value is used; if it differs from the value first reported, that is noted as a restatement.
- Each input has an ordered list of XBRL concepts (companies switch, e.g. from SalesRevenueNet to
  RevenueFromContractWithCustomerExcludingAssessedTax). The first one reported for that year wins
  and is recorded. Derived inputs (gross profit, EBITDA, total debt) record how they were built.
- Nothing is guessed: if an input can't be found, it is Missing with the reason.
"""

from dataclasses import dataclass, field
from datetime import date

ANNUAL_FORMS = ("10-K", "10-K/A")
MIN_DAYS, MAX_DAYS = 350, 380


@dataclass(frozen=True)
class Fact:
    concept: str
    value: float
    unit: str
    end: date
    start: date | None
    form: str
    fy: int | None
    accn: str
    filed: date

    def filing_url(self, cik: int) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{self.accn.replace('-', '')}/{self.accn}-index.htm"


@dataclass
class Figure:
    """A number we can stand behind: its value, how it was obtained, and the facts it came from."""

    value: float
    how: str
    sources: list[Fact]
    notes: list[str] = field(default_factory=list)


@dataclass
class Missing:
    reason: str


@dataclass(frozen=True)
class FiscalYear:
    fy: int
    end: date
    accn: str
    filed: date

    @property
    def label(self) -> str:
        return f"FY{self.fy}"


def _parse(concept: str, unit: str, raw: dict) -> Fact:
    return Fact(
        concept=concept,
        value=float(raw["val"]),
        unit=unit,
        end=date.fromisoformat(raw["end"]),
        start=date.fromisoformat(raw["start"]) if raw.get("start") else None,
        form=raw.get("form", ""),
        fy=raw.get("fy"),
        accn=raw.get("accn", ""),
        filed=date.fromisoformat(raw["filed"]),
    )


class Filings:
    def __init__(self, companyfacts: dict):
        self.cik = int(companyfacts.get("cik", 0))
        self.name = companyfacts.get("entityName", "")
        self._facts = companyfacts.get("facts", {})

    def _all(self, concept: str, unit: str, taxonomy: str = "us-gaap") -> list[Fact]:
        units = self._facts.get(taxonomy, {}).get(concept, {}).get("units", {})
        return [_parse(concept, unit, raw) for raw in units.get(unit, [])]

    def fiscal_years(self) -> list[FiscalYear]:
        """Every fiscal year with an original 10-K, oldest first.

        Only annual us-gaap periods count: cover-page facts (share counts, public float) are dated
        after the year ends and would move the period end.
        """
        by_filing: dict[str, list[Fact]] = {}
        for concept, body in self._facts.get("us-gaap", {}).items():
            for unit, raws in body.get("units", {}).items():
                for raw in raws:
                    if raw.get("form") == "10-K" and raw.get("fp") == "FY" and raw.get("fy") and raw.get("start"):
                        fact = _parse(concept, unit, raw)
                        if _fits(fact, instant=False):
                            by_filing.setdefault(fact.accn, []).append(fact)
        years: dict[date, FiscalYear] = {}
        for accn, facts in by_filing.items():
            end = max(f.end for f in facts)
            fy = next(f.fy for f in facts if f.end == end)
            filed = min(f.filed for f in facts)
            if end not in years or filed < years[end].filed:
                years[end] = FiscalYear(fy=fy, end=end, accn=accn, filed=filed)
        ordered = sorted(years.values(), key=lambda y: y.end)
        # A 52/53-week year can make two filings claim the same label; keep the later period for it.
        by_label = {y.fy: y for y in ordered}
        return sorted(by_label.values(), key=lambda y: y.end)

    def annual(self, concept: str, year: FiscalYear, instant: bool, unit: str = "USD") -> Figure | None:
        """The concept's value for that fiscal year, from the most recently filed 10-K that reports it."""
        candidates = [
            f for f in self._all(concept, unit)
            if f.form in ANNUAL_FORMS and f.end == year.end and _fits(f, instant)
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda f: (f.filed, f.accn))
        first = min(candidates, key=lambda f: (f.filed, f.accn))
        figure = Figure(latest.value, concept, [latest])
        if first.value != latest.value:
            was = (f"{fmt_money(first.value, unit)} as first filed ({first.form} filed {first.filed}), "
                   f"{fmt_money(latest.value, unit)} in the latest filing ({latest.form} filed {latest.filed})")
            split = split_ratio(first.value, latest.value) if unit == "USD/shares" else None
            if split:
                figure.notes.append(f"{concept}: {was}, consistent with a {split}-for-1 stock split; "
                                    "using the split-adjusted figure.")
            else:
                figure.notes.append(f"{concept} restated: {was}; using the latest.")
        return figure

    def latest_instant(self, concept: str, unit: str, taxonomy: str) -> list[Fact]:
        """All facts on the most recent date reported for an instant concept, from any form."""
        facts = self._all(concept, unit, taxonomy)
        if not facts:
            return []
        newest = max(f.end for f in facts)
        return [f for f in facts if f.end == newest]


def split_ratio(before: float, after: float) -> int | None:
    """N if before/after is close to a whole N >= 2 (per-share figures after an N-for-1 split), else None.

    5% tolerance because EPS is rounded to the cent, which is coarse for small values ($0.17).
    """
    if before <= 0 or after <= 0:
        return None
    ratio = before / after
    n = round(ratio)
    return n if n >= 2 and abs(ratio - n) / n <= 0.05 else None


def _fits(fact: Fact, instant: bool) -> bool:
    if instant:
        return fact.start is None
    return fact.start is not None and MIN_DAYS <= (fact.end - fact.start).days <= MAX_DAYS


def fmt_money(value: float, unit: str = "USD") -> str:
    if unit == "USD/shares":
        return f"${value:,.2f}"
    if unit == "shares":
        return f"{value / 1e6:,.1f}M shares"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e9:
        return f"{sign}${v / 1e9:,.1f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:,.1f}M"
    return f"{sign}${v:,.0f}"


# ── Inputs ───────────────────────────────────────────────────────────────────────────────────────

FLOW, STOCK = False, True

CONCEPTS: dict[str, tuple[bool, str, list[str]]] = {
    # name: (instant?, unit, concepts in order of preference)
    "revenue": (FLOW, "USD", [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ]),
    "gross_profit": (FLOW, "USD", ["GrossProfit"]),
    "cost_of_revenue": (FLOW, "USD", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]),
    "operating_income": (FLOW, "USD", ["OperatingIncomeLoss"]),
    "net_income": (FLOW, "USD", ["NetIncomeLoss"]),
    "interest_expense": (FLOW, "USD", ["InterestExpense", "InterestExpenseNonoperating"]),
    "eps_diluted": (FLOW, "USD/shares", ["EarningsPerShareDiluted"]),
    "total_assets": (STOCK, "USD", ["Assets"]),
    "current_assets": (STOCK, "USD", ["AssetsCurrent"]),
    "cash": (STOCK, "USD", ["CashAndCashEquivalentsAtCarryingValue"]),
    "inventory": (STOCK, "USD", ["InventoryNet"]),
    "receivables": (STOCK, "USD", ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"]),
    "current_liabilities": (STOCK, "USD", ["LiabilitiesCurrent"]),
    "equity": (STOCK, "USD", ["StockholdersEquity"]),
}

LABELS = {
    "revenue": "Revenue",
    "gross_profit": "Gross profit",
    "cost_of_revenue": "Cost of revenue",
    "operating_income": "Operating income",
    "depreciation_amortization": "Depreciation & amortization",
    "ebitda": "EBITDA",
    "net_income": "Net income",
    "interest_expense": "Interest expense",
    "eps_diluted": "Diluted EPS",
    "total_assets": "Total assets",
    "current_assets": "Current assets",
    "cash": "Cash & equivalents",
    "inventory": "Inventory",
    "receivables": "Accounts receivable",
    "current_liabilities": "Current liabilities",
    "total_debt": "Total debt",
    "equity": "Shareholders' equity",
    "price": "Share price",
    "shares": "Shares outstanding",
    "market_cap": "Market cap",
    "enterprise_value": "Enterprise value",
    "eps_for_price": "EPS used for P/E",
}

DA_CONCEPTS = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
]


def first_reported(filings: Filings, year: FiscalYear, concepts: list[str], instant: bool, unit: str) -> Figure | None:
    for concept in concepts:
        figure = filings.annual(concept, year, instant, unit)
        if figure is not None:
            return figure
    return None


def _not_reported(name: str, concepts: list[str], year: FiscalYear) -> Missing:
    tags = ", ".join(concepts)
    return Missing(f"{LABELS[name]} not reported in the 10-K data (looked for {tags})")


def _combine(how: str, value: float, parts: list[Figure], notes: list[str] | None = None) -> Figure:
    return Figure(value, how, [s for p in parts for s in p.sources],
                  [n for p in parts for n in p.notes] + (notes or []))


def resolve(filings: Filings, year: FiscalYear) -> dict[str, Figure | Missing]:
    """Every input for one fiscal year, each a Figure (with sources) or Missing (with the reason)."""
    out: dict[str, Figure | Missing] = {}
    for name, (instant, unit, concepts) in CONCEPTS.items():
        out[name] = first_reported(filings, year, concepts, instant, unit) or _not_reported(name, concepts, year)

    if isinstance(out["cash"], Missing):
        alt = filings.annual("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", year, STOCK)
        if alt:
            alt.notes.append("Cash includes restricted cash: the company doesn't report unrestricted cash on its own.")
            out["cash"] = alt

    revenue, gp, cor = out["revenue"], out["gross_profit"], out["cost_of_revenue"]
    if isinstance(gp, Missing) and isinstance(revenue, Figure) and isinstance(cor, Figure):
        out["gross_profit"] = _combine(f"{revenue.how} − {cor.how}", revenue.value - cor.value, [revenue, cor],
                                       ["Gross profit derived as revenue minus cost of revenue (not reported directly)."])
    if isinstance(cor, Missing) and isinstance(revenue, Figure) and isinstance(gp, Figure):
        out["cost_of_revenue"] = _combine(f"{revenue.how} − {gp.how}", revenue.value - gp.value, [revenue, gp],
                                          ["Cost of revenue derived as revenue minus gross profit (not reported directly)."])

    out["depreciation_amortization"] = _depreciation(filings, year)
    oi, da = out["operating_income"], out["depreciation_amortization"]
    if isinstance(oi, Figure) and isinstance(da, Figure):
        out["ebitda"] = _combine(f"{oi.how} + D&A", oi.value + da.value, [oi, da])
    else:
        missing = oi if isinstance(oi, Missing) else da
        out["ebitda"] = Missing(f"EBITDA needs operating income and D&A: {missing.reason}")

    out["total_debt"] = _total_debt(filings, year)
    return out


def _depreciation(filings: Filings, year: FiscalYear) -> Figure | Missing:
    figure = first_reported(filings, year, DA_CONCEPTS, FLOW, "USD")
    if figure:
        return figure
    dep = filings.annual("Depreciation", year, FLOW)
    amort = filings.annual("AmortizationOfIntangibleAssets", year, FLOW)
    if dep and amort:
        return _combine("Depreciation + AmortizationOfIntangibleAssets", dep.value + amort.value, [dep, amort],
                        ["D&A built from separately reported depreciation and intangible amortization."])
    if dep:
        dep.notes.append("Only depreciation is reported; amortization isn't included, so EBITDA may be slightly understated.")
        return dep
    return _not_reported("depreciation_amortization", DA_CONCEPTS + ["Depreciation"], year)


def _total_debt(filings: Filings, year: FiscalYear) -> Figure | Missing:
    """Long-term debt including its current portion, plus short-term borrowings. Leases excluded."""
    get = lambda concept: filings.annual(concept, year, STOCK)  # noqa: E731
    noncurrent, current = get("LongTermDebtNoncurrent"), get("LongTermDebtCurrent")
    notes: list[str] = []
    if noncurrent and current:
        long_parts, long_how = [noncurrent, current], "LongTermDebtNoncurrent + LongTermDebtCurrent"
    elif total := get("LongTermDebt"):
        long_parts, long_how = [total], "LongTermDebt"
    elif with_leases := get("LongTermDebtAndCapitalLeaseObligations"):
        long_parts = [with_leases] + ([current] if current else [])
        long_how = "LongTermDebtAndCapitalLeaseObligations" + (" + LongTermDebtCurrent" if current else "")
        notes.append("Long-term debt includes finance lease obligations (the company reports them together).")
    elif noncurrent:
        long_parts, long_how = [noncurrent], "LongTermDebtNoncurrent"
        notes.append("Current portion of long-term debt not reported; total debt may be understated.")
    else:
        return Missing("Total debt: no long-term debt reported in the 10-K data "
                       "(looked for LongTermDebtNoncurrent + LongTermDebtCurrent, LongTermDebt, "
                       "LongTermDebtAndCapitalLeaseObligations)")

    short = get("ShortTermBorrowings")
    short_how = "ShortTermBorrowings"
    if short is None:
        short, short_how = get("CommercialPaper"), "CommercialPaper"
    if short is None:
        notes.append("No short-term borrowings or commercial paper reported; none added.")
    parts = long_parts + ([short] if short else [])
    how = long_how + (f" + {short_how}" if short else "")
    return _combine(how, sum(p.value for p in parts), parts, notes)


def shares_outstanding(filings: Filings) -> Figure | Missing:
    """The most recent share count: the cover-page figure if there is one, else the balance-sheet one."""
    for taxonomy, concept in (("dei", "EntityCommonStockSharesOutstanding"), ("us-gaap", "CommonStockSharesOutstanding")):
        facts = filings.latest_instant(concept, "shares", taxonomy)
        if not facts:
            continue
        values = {f.value for f in facts}
        if len(values) > 1:
            return Missing(f"{concept} has {len(values)} different values on {facts[0].end} "
                           "(probably several share classes), so there is no single share count")
        fact = max(facts, key=lambda f: f.filed)
        return Figure(fact.value, concept, [fact], [f"Shares outstanding as of {fact.end} ({fact.form} filed {fact.filed})."])
    return Missing("Shares outstanding not reported (looked for dei:EntityCommonStockSharesOutstanding "
                   "and us-gaap:CommonStockSharesOutstanding)")
