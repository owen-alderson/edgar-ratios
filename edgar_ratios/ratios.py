"""The 23 ratios, computed per fiscal year from traced inputs. A ratio is a number or a reason."""

from dataclasses import dataclass, field
from datetime import date, datetime

from .facts import LABELS, Figure, Filings, FiscalYear, Missing, fmt_money, resolve, shares_outstanding
from .sec import Company, Sec, SecError

CATEGORIES = ["Valuation", "Profitability", "Liquidity", "Leverage", "Efficiency"]


@dataclass(frozen=True)
class Ratio:
    name: str
    category: str
    fmt: str            # "%", "x", "days" or "ratio"
    numerator: str
    denominator: str
    scale: float
    explain: str


def _r(name, category, fmt, num, den, explain, scale=None):
    scale = scale if scale is not None else (100.0 if fmt == "%" else 1.0)
    return Ratio(name, category, fmt, num, den, scale, explain)


RATIOS = [
    _r("P/E", "Valuation", "x", "price", "eps_for_price", "Share price ÷ diluted earnings per share: what you pay for $1 of yearly profit."),
    _r("EV/EBITDA", "Valuation", "x", "enterprise_value", "ebitda", "Enterprise value ÷ EBITDA: the price of the whole business against its operating cash profit."),
    _r("EV/Revenue", "Valuation", "x", "enterprise_value", "revenue", "Enterprise value ÷ revenue."),
    _r("P/B", "Valuation", "x", "market_cap", "equity", "Market cap ÷ shareholders' equity (book value)."),
    _r("P/S", "Valuation", "x", "market_cap", "revenue", "Market cap ÷ revenue."),
    _r("Gross margin", "Profitability", "%", "gross_profit", "revenue", "Gross profit ÷ revenue: what's left after the direct cost of what was sold."),
    _r("EBITDA margin", "Profitability", "%", "ebitda", "revenue", "EBITDA ÷ revenue."),
    _r("Operating margin", "Profitability", "%", "operating_income", "revenue", "Operating income ÷ revenue: profit from the core business."),
    _r("Net margin", "Profitability", "%", "net_income", "revenue", "Net income ÷ revenue: the bottom line."),
    _r("ROE", "Profitability", "%", "net_income", "equity", "Return on equity: net income ÷ year-end shareholders' equity."),
    _r("ROA", "Profitability", "%", "net_income", "total_assets", "Return on assets: net income ÷ year-end total assets."),
    _r("ROIC", "Profitability", "%", "net_income", "invested_capital", "Simple return on invested capital: net income ÷ (equity + total debt)."),
    _r("Current ratio", "Liquidity", "ratio", "current_assets", "current_liabilities", "Current assets ÷ current liabilities: can it pay what's due within a year?"),
    _r("Quick ratio", "Liquidity", "ratio", "quick_assets", "current_liabilities", "(Current assets − inventory) ÷ current liabilities: the same test without inventory."),
    _r("Cash ratio", "Liquidity", "ratio", "cash", "current_liabilities", "Cash ÷ current liabilities: the strictest version."),
    _r("Debt/Equity", "Leverage", "x", "total_debt", "equity", "Total debt ÷ shareholders' equity."),
    _r("Net debt/EBITDA", "Leverage", "x", "net_debt", "ebitda", "(Debt − cash) ÷ EBITDA: years of operating profit to pay off net debt. Negative means more cash than debt."),
    _r("Debt/Assets", "Leverage", "%", "total_debt", "total_assets", "Total debt ÷ total assets."),
    _r("Interest coverage", "Leverage", "x", "operating_income", "interest_expense", "Operating income ÷ interest expense: how many times profit covers interest. Under 1.5x is a warning sign."),
    _r("Asset turnover", "Efficiency", "x", "revenue", "total_assets", "Revenue ÷ total assets."),
    _r("Inventory turnover", "Efficiency", "x", "cost_of_revenue", "inventory", "Cost of revenue ÷ inventory: how many times inventory is sold through a year."),
    _r("Days inventory", "Efficiency", "days", "inventory", "cost_of_revenue", "Inventory ÷ cost of revenue × 365: days of stock on hand.", scale=365.0),
    _r("Days sales outstanding", "Efficiency", "days", "receivables", "revenue", "Receivables ÷ revenue × 365: days customers take to pay.", scale=365.0),
]

DERIVED_LABELS = {
    "invested_capital": "Invested capital (equity + debt)",
    "quick_assets": "Quick assets (current assets − inventory)",
    "net_debt": "Net debt (debt − cash)",
}


@dataclass
class Value:
    ratio: Ratio
    value: float | None
    reason: str | None = None


@dataclass
class Price:
    value: float
    as_of: date


@dataclass
class YearResult:
    year: FiscalYear
    inputs: dict[str, Figure | Missing]
    values: list[Value]


@dataclass
class Analysis:
    company: Company
    fetched: datetime
    years: list[YearResult]
    price: Price | None
    shares: Figure | Missing
    notes: list[str] = field(default_factory=list)

    @property
    def latest(self) -> YearResult:
        return self.years[-1]


def label(name: str) -> str:
    return LABELS.get(name) or DERIVED_LABELS.get(name, name)


def _sum(name: str, parts: list[tuple[str, float]], inputs: dict) -> Figure | Missing:
    """Add (input, sign) pairs, or explain which part is missing."""
    for part, _ in parts:
        if isinstance(inputs.get(part), Missing):
            return Missing(f"{label(name)} needs {label(part).lower()}: {inputs[part].reason}")
    figures = [inputs[p] for p, _ in parts]
    total = sum(sign * f.value for (_, sign), f in zip(parts, figures))
    how = " ".join(("+ " if sign > 0 else "− ") + label(p).lower() for p, sign in parts)[2:]
    return Figure(total, how, [s for f in figures for s in f.sources])


def with_derived(inputs: dict[str, Figure | Missing]) -> dict[str, Figure | Missing]:
    out = dict(inputs)
    out["invested_capital"] = _sum("invested_capital", [("equity", 1), ("total_debt", 1)], inputs)
    out["quick_assets"] = _sum("quick_assets", [("current_assets", 1), ("inventory", -1)], inputs)
    out["net_debt"] = _sum("net_debt", [("total_debt", 1), ("cash", -1)], inputs)
    return out


def market_inputs(inputs: dict, price: Price, shares: Figure | Missing) -> dict[str, Figure | Missing]:
    """Price-based inputs for the latest fiscal year: price from you, shares from the latest filing."""
    out: dict[str, Figure | Missing] = {
        "price": Figure(price.value, f"your price, entered {price.as_of}", [],
                        [f"Share price ${price.value:,.2f} was supplied by you (SEC filings contain no market prices)."]),
        "shares": shares,
    }
    if isinstance(shares, Missing):
        out["market_cap"] = Missing(f"Market cap needs shares outstanding: {shares.reason}")
    else:
        out["market_cap"] = Figure(price.value * shares.value, "price × shares outstanding", shares.sources)
    out["eps_for_price"] = _eps_for_price(inputs.get("eps_diluted"), inputs.get("net_income"), shares)
    cap, debt, cash = out["market_cap"], inputs.get("total_debt"), inputs.get("cash")
    missing = next((m for m in (cap, debt, cash) if isinstance(m, Missing)), None)
    if missing is not None:
        out["enterprise_value"] = Missing(f"Enterprise value needs market cap, debt and cash: {missing.reason}")
    else:
        out["enterprise_value"] = Figure(cap.value + debt.value - cash.value, "market cap + total debt − cash",
                                         cap.sources + debt.sources + cash.sources)
    return out


def _eps_for_price(eps, net_income, shares) -> Figure | Missing:
    """Diluted EPS, unless the share count has changed so much since the 10-K (a split after it was filed)
    that today's price and that EPS aren't on the same basis."""
    if not isinstance(eps, Figure):
        return eps if isinstance(eps, Missing) else Missing("Diluted EPS unavailable")
    if isinstance(net_income, Figure) and isinstance(shares, Figure) and eps.value > 0 and net_income.value > 0:
        implied = net_income.value / eps.value
        change = shares.value / implied
        if not 0.67 <= change <= 1.5:
            return Missing(f"Shares outstanding now ({shares.value / 1e6:,.0f}M) differ from the ~{implied / 1e6:,.0f}M "
                           "implied by the 10-K's EPS (probably a stock split since), so today's price and that EPS "
                           "aren't comparable")
    return eps


def compute(inputs: dict[str, Figure | Missing], valuation_reason: str | None = None) -> list[Value]:
    """Every ratio for one year. Valuation ratios are skipped with `valuation_reason` when there's no price."""
    inputs = with_derived(inputs)
    values = []
    for ratio in RATIOS:
        if ratio.category == "Valuation" and valuation_reason:
            values.append(Value(ratio, None, valuation_reason))
            continue
        num, den = inputs.get(ratio.numerator), inputs.get(ratio.denominator)
        if isinstance(num, Missing) or num is None:
            values.append(Value(ratio, None, num.reason if num else f"{label(ratio.numerator)} unavailable"))
        elif isinstance(den, Missing) or den is None:
            values.append(Value(ratio, None, den.reason if den else f"{label(ratio.denominator)} unavailable"))
        elif den.value == 0:
            values.append(Value(ratio, None, f"{label(ratio.denominator)} is zero"))
        elif den.value < 0:
            values.append(Value(ratio, None, f"{label(ratio.denominator)} is negative "
                                             f"({fmt_money(den.value, 'USD/shares' if ratio.denominator == 'eps_diluted' else 'USD')}), "
                                             "so the ratio isn't meaningful"))
        else:
            values.append(Value(ratio, ratio.scale * num.value / den.value))
    return values


NO_PRICE = "Needs a share price: pass --price (SEC filings don't contain market prices)"
OLD_YEAR = "Valued only for the latest fiscal year, at the price you passed"


def analyze(sec: Sec, ticker: str, years: int = 5, price: Price | None = None) -> Analysis:
    company = sec.lookup(ticker)
    try:
        data, fetched = sec.company_facts(company.cik)
    except SecError as e:
        if "Not found" in str(e):
            raise SecError(f"{company.ticker}: no XBRL financial data on EDGAR for {company.name}.") from e
        raise
    filings = Filings(data)
    fiscal_years = filings.fiscal_years()[-years:]
    if not fiscal_years:
        raise SecError(f"{company.ticker}: no 10-K annual reports in EDGAR's XBRL data "
                       "(foreign companies filing 20-F or 40-F aren't supported).")
    shares = shares_outstanding(filings)
    results = []
    for i, fy in enumerate(fiscal_years):
        inputs = resolve(filings, fy)
        latest = i == len(fiscal_years) - 1
        if price and latest:
            inputs.update(market_inputs(inputs, price, shares))
            values = compute(inputs)
        else:
            values = compute(inputs, OLD_YEAR if price else NO_PRICE)
        results.append(YearResult(fy, inputs, values))
    notes = []
    if price:
        notes.append(f"Valuation ratios use your price (${price.value:,.2f}, entered {price.as_of}) against "
                     f"{fiscal_years[-1].label} figures; enterprise value uses the {fiscal_years[-1].label} "
                     "year-end balance sheet.")
    return Analysis(company, fetched, results, price, shares, notes)
