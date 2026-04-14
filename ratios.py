"""
Core ratio calculations. All functions return float or None.
None means the ratio cannot be computed (missing or zero denominator).
"""

from dataclasses import dataclass
from typing import Optional


def _safe(numerator, denominator) -> Optional[float]:
    """Divide safely — returns None if denominator is zero or either value is None."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def pct(value: Optional[float]) -> Optional[float]:
    """Convert a ratio to percentage."""
    return value * 100 if value is not None else None


@dataclass
class Inputs:
    # Company
    company_name: str = ""

    # Income Statement
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    ebitda: Optional[float] = None
    ebit: Optional[float] = None          # operating income
    net_income: Optional[float] = None
    interest_expense: Optional[float] = None
    eps: Optional[float] = None

    # Balance Sheet
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    cash: Optional[float] = None
    inventory: Optional[float] = None
    accounts_receivable: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_liabilities: Optional[float] = None
    total_debt: Optional[float] = None
    shareholders_equity: Optional[float] = None

    # Market / Valuation
    share_price: Optional[float] = None
    shares_outstanding: Optional[float] = None   # in millions
    enterprise_value: Optional[float] = None     # optional override


@dataclass
class RatioResult:
    name: str
    value: Optional[float]
    fmt: str          # "x", "%", or "ratio"
    description: str
    category: str


def compute_all(inp: Inputs) -> list[RatioResult]:
    r = []

    # Derived values — all in $M
    # share_price ($) × shares_outstanding (M shares) = market_cap ($M)
    market_cap = (inp.share_price * inp.shares_outstanding
                  if inp.share_price and inp.shares_outstanding else None)
    net_debt = ((inp.total_debt - inp.cash)
                if inp.total_debt is not None and inp.cash is not None else None)
    ev = inp.enterprise_value or (market_cap + net_debt
                                   if market_cap is not None and net_debt is not None else None)
    cogs = ((inp.revenue - inp.gross_profit)
            if inp.revenue and inp.gross_profit is not None else None)
    quick_assets = ((inp.current_assets - inp.inventory)
                    if inp.current_assets is not None and inp.inventory is not None else None)

    # ── Valuation ─────────────────────────────────────────────────────────────
    r.append(RatioResult("P/E", _safe(inp.share_price, inp.eps), "x",
        "Share price / EPS. How much investors pay per dollar of earnings.", "Valuation"))

    r.append(RatioResult("EV/EBITDA", _safe(ev, inp.ebitda), "x",
        "Enterprise value / EBITDA. Core M&A valuation multiple.", "Valuation"))

    r.append(RatioResult("EV/Revenue", _safe(ev, inp.revenue), "x",
        "Enterprise value / Revenue. Useful for pre-profit or high-growth companies.", "Valuation"))

    r.append(RatioResult("P/B", _safe(market_cap, inp.shareholders_equity), "x",
        "Market cap / Book value. Measures premium paid over net assets.", "Valuation"))

    r.append(RatioResult("P/S", _safe(market_cap, inp.revenue), "x",
        "Market cap / Revenue. Useful when earnings are volatile or negative.", "Valuation"))

    # ── Profitability ─────────────────────────────────────────────────────────
    r.append(RatioResult("Gross Margin", pct(_safe(inp.gross_profit, inp.revenue)), "%",
        "Gross profit / Revenue. Measures pricing power and COGS efficiency.", "Profitability"))

    r.append(RatioResult("EBITDA Margin", pct(_safe(inp.ebitda, inp.revenue)), "%",
        "EBITDA / Revenue. Operating profitability before D&A.", "Profitability"))

    r.append(RatioResult("Operating Margin", pct(_safe(inp.ebit, inp.revenue)), "%",
        "EBIT / Revenue. Core operating efficiency.", "Profitability"))

    r.append(RatioResult("Net Margin", pct(_safe(inp.net_income, inp.revenue)), "%",
        "Net income / Revenue. Bottom-line profitability.", "Profitability"))

    r.append(RatioResult("ROE", pct(_safe(inp.net_income, inp.shareholders_equity)), "%",
        "Net income / Equity. Returns generated on shareholders' capital.", "Profitability"))

    r.append(RatioResult("ROA", pct(_safe(inp.net_income, inp.total_assets)), "%",
        "Net income / Total assets. How efficiently assets generate profit.", "Profitability"))

    roic_denominator = ((inp.shareholders_equity + inp.total_debt)
                        if inp.shareholders_equity is not None and inp.total_debt is not None else None)
    r.append(RatioResult("ROIC", pct(_safe(inp.net_income, roic_denominator)), "%",
        "Net income / Invested capital. Key value creation metric in PE.", "Profitability"))

    # ── Liquidity ─────────────────────────────────────────────────────────────
    r.append(RatioResult("Current Ratio", _safe(inp.current_assets, inp.current_liabilities), "ratio",
        "Current assets / Current liabilities. Ability to cover short-term obligations.", "Liquidity"))

    r.append(RatioResult("Quick Ratio", _safe(quick_assets, inp.current_liabilities), "ratio",
        "(Current assets – Inventory) / Current liabilities. Stricter liquidity test.", "Liquidity"))

    r.append(RatioResult("Cash Ratio", _safe(inp.cash, inp.current_liabilities), "ratio",
        "Cash / Current liabilities. Most conservative liquidity measure.", "Liquidity"))

    # ── Leverage ──────────────────────────────────────────────────────────────
    r.append(RatioResult("Debt/Equity", _safe(inp.total_debt, inp.shareholders_equity), "x",
        "Total debt / Equity. Financial leverage; higher = more risk.", "Leverage"))

    r.append(RatioResult("Net Debt/EBITDA", _safe(net_debt, inp.ebitda), "x",
        "Net debt / EBITDA. Leverage relative to cash generation. Key in LBO analysis.", "Leverage"))

    r.append(RatioResult("Debt/Assets", pct(_safe(inp.total_debt, inp.total_assets)), "%",
        "Total debt / Total assets. Proportion of assets financed by debt.", "Leverage"))

    r.append(RatioResult("Interest Coverage", _safe(inp.ebit, inp.interest_expense), "x",
        "EBIT / Interest expense. Ability to service debt. Below 1.5x is a warning sign.", "Leverage"))

    # ── Efficiency ────────────────────────────────────────────────────────────
    r.append(RatioResult("Asset Turnover", _safe(inp.revenue, inp.total_assets), "x",
        "Revenue / Total assets. How efficiently assets generate revenue.", "Efficiency"))

    inv_turnover = _safe(cogs, inp.inventory)
    r.append(RatioResult("Inventory Turnover", inv_turnover, "x",
        "COGS / Inventory. How fast inventory is sold.", "Efficiency"))

    r.append(RatioResult("Days Inventory (DIO)",
        _safe(365, inv_turnover) if inv_turnover else None, "ratio",
        "365 / Inventory turnover. Average days to sell inventory.", "Efficiency"))

    r.append(RatioResult("Days Sales Outstanding (DSO)",
        _safe(inp.accounts_receivable * 365, inp.revenue)
        if inp.accounts_receivable is not None and inp.revenue else None, "ratio",
        "AR / Revenue × 365. Average days to collect payment.", "Efficiency"))

    return r


def format_value(result: RatioResult) -> str:
    if result.value is None:
        return "N/A"
    v = result.value
    if result.fmt == "%":
        return f"{v:.1f}%"
    elif result.fmt == "x":
        return f"{v:.1f}x"
    else:
        return f"{v:.2f}"


CATEGORIES = ["Valuation", "Profitability", "Liquidity", "Leverage", "Efficiency"]
