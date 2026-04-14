import streamlit as st
import pandas as pd
import os
from commentary import load_env, get_commentary
from ratios import Inputs, compute_all, format_value, CATEGORIES

load_env()

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(page_title="Financial Ratio Analyzer", page_icon="📊", layout="wide")

st.markdown("""
<style>
    .ratio-table { width: 100%; border-collapse: collapse; font-size: .88rem; }
    .ratio-table th {
        text-align: left; padding: 8px 12px;
        border-bottom: 2px solid #2a2d3d;
        font-size: .75rem; color: #6b7280;
        text-transform: uppercase; letter-spacing: .05em;
    }
    .ratio-table td { padding: 9px 12px; border-bottom: 1px solid #1e2130; }
    .ratio-table tr:last-child td { border-bottom: none; }
    .ratio-table tr:hover td { background: #1a1d27; }
    .val-available { font-weight: 700; color: #e5e7eb; font-size: .95rem; }
    .val-na { color: #4b5563; }
    .desc { color: #6b7280; font-size: .8rem; }
    .cat-header {
        font-size: .75rem; font-weight: 700;
        color: #4f8ef7; text-transform: uppercase;
        letter-spacing: .08em; padding: 14px 12px 4px;
    }
    .commentary-box {
        background: #1a1d27;
        border: 1px solid #2a2d3d;
        border-left: 3px solid #4f8ef7;
        border-radius: 10px;
        padding: 20px 24px;
        font-size: .9rem;
        line-height: 1.7;
        color: #e5e7eb;
        margin-top: 8px;
    }
    .section-label {
        font-size: .75rem; font-weight: 600;
        color: #6b7280; text-transform: uppercase;
        letter-spacing: .06em; margin: 20px 0 10px;
    }
</style>
""", unsafe_allow_html=True)

st.title("📊 Financial Ratio Analyzer")
st.caption("Enter financial figures to compute valuation, profitability, liquidity, leverage, and efficiency ratios.")

# ── Inputs ────────────────────────────────────────────────────────────────────

def num(label, key, help=None, placeholder="—"):
    val = st.text_input(label, key=key, help=help, placeholder=placeholder)
    if val.strip() == "" or val.strip() == "—":
        return None
    try:
        return float(val.replace(",", ""))
    except ValueError:
        st.warning(f"'{val}' is not a valid number for {label}.")
        return None

with st.expander("ℹ️ How to enter numbers", expanded=False):
    st.markdown("""
    - Enter values **in millions** (e.g. revenue of $5 billion = `5000`)
    - For share price and EPS, use **actual values** (e.g. `142.50` and `8.30`)
    - Shares outstanding in **millions** (e.g. 500 million shares = `500`)
    - Leave any field blank if you don't have the data — those ratios will show N/A
    """)

company_name = st.text_input("Company name (optional)", placeholder="Apple Inc.")

st.markdown('<div class="section-label">Income Statement ($M)</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1: revenue       = num("Revenue",          "revenue")
with c2: gross_profit  = num("Gross Profit",     "gross_profit")
with c3: ebitda        = num("EBITDA",            "ebitda")
with c4: ebit          = num("EBIT (Op. Income)", "ebit")

c5, c6, c7, c8 = st.columns(4)
with c5: net_income      = num("Net Income",        "net_income")
with c6: interest_exp    = num("Interest Expense",  "interest_exp")
with c7: eps             = num("EPS ($)",           "eps",    placeholder="e.g. 6.42")
with c8: pass

st.markdown('<div class="section-label">Balance Sheet ($M)</div>', unsafe_allow_html=True)
b1, b2, b3, b4 = st.columns(4)
with b1: total_assets   = num("Total Assets",       "total_assets")
with b2: current_assets = num("Current Assets",     "current_assets")
with b3: cash           = num("Cash & Equivalents", "cash")
with b4: inventory      = num("Inventory",          "inventory")

b5, b6, b7, b8 = st.columns(4)
with b5: accounts_rec   = num("Accounts Receivable","accounts_rec")
with b6: current_liab   = num("Current Liabilities","current_liab")
with b7: total_debt     = num("Total Debt",         "total_debt")
with b8: equity         = num("Shareholders Equity","equity")

st.markdown('<div class="section-label">Market Data</div>', unsafe_allow_html=True)
m1, m2, m3 = st.columns(3)
with m1: share_price    = num("Share Price ($)",    "share_price",  placeholder="e.g. 185.50")
with m2: shares_out     = num("Shares Outstanding (M)", "shares_out", placeholder="e.g. 500")
with m3: ev_override    = num("Enterprise Value ($M, optional)", "ev_override",
                               help="Leave blank to auto-calculate from Market Cap + Net Debt")

st.divider()

# ── Compute ───────────────────────────────────────────────────────────────────

inp = Inputs(
    company_name=company_name,
    revenue=revenue, gross_profit=gross_profit, ebitda=ebitda, ebit=ebit,
    net_income=net_income, interest_expense=interest_exp, eps=eps,
    total_assets=total_assets, current_assets=current_assets, cash=cash,
    inventory=inventory, accounts_receivable=accounts_rec,
    current_liabilities=current_liab, total_debt=total_debt,
    shareholders_equity=equity,
    share_price=share_price, shares_outstanding=shares_out,
    enterprise_value=ev_override,
)

results = compute_all(inp)
available = [r for r in results if r.value is not None]

if not available:
    st.info("Fill in some figures above to compute ratios.")
    st.stop()

# ── Results table ─────────────────────────────────────────────────────────────

left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader(f"Ratios — {company_name or 'Company'}")
    rows_html = ""
    for cat in CATEGORIES:
        cat_results = [r for r in results if r.category == cat]
        if not any(True for r in cat_results):
            continue
        rows_html += f'<tr><td colspan="3" class="cat-header">{cat}</td></tr>'
        for r in cat_results:
            val_class = "val-available" if r.value is not None else "val-na"
            val_str = format_value(r)
            rows_html += f"""
            <tr>
              <td>{r.name}</td>
              <td class="{val_class}">{val_str}</td>
              <td class="desc">{r.description}</td>
            </tr>"""

    st.markdown(
        f'<table class="ratio-table"><thead><tr><th>Ratio</th><th>Value</th><th>What it measures</th></tr></thead>'
        f'<tbody>{rows_html}</tbody></table>',
        unsafe_allow_html=True,
    )

with right_col:
    # Quick summary metrics
    def get_val(name):
        for r in results:
            if r.name == name:
                return format_value(r)
        return "N/A"

    st.subheader("Snapshot")
    snap_data = {
        "EV/EBITDA": get_val("EV/EBITDA"),
        "Net Margin": get_val("Net Margin"),
        "ROE": get_val("ROE"),
        "Net Debt/EBITDA": get_val("Net Debt/EBITDA"),
        "Current Ratio": get_val("Current Ratio"),
        "Interest Coverage": get_val("Interest Coverage"),
    }
    for k, v in snap_data.items():
        col_a, col_b = st.columns([2, 1])
        col_a.markdown(f"**{k}**")
        col_b.markdown(f"`{v}`")

    st.divider()

    # AI commentary
    st.subheader("AI Commentary")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.caption("Add `ANTHROPIC_API_KEY` to `.env` to enable AI analysis.")
    else:
        if st.button("Analyze with AI", use_container_width=True, type="primary"):
            with st.spinner("Analyzing..."):
                commentary = get_commentary(company_name, results)
                st.session_state["commentary"] = commentary

        if "commentary" in st.session_state:
            st.markdown(
                f'<div class="commentary-box">{st.session_state["commentary"]}</div>',
                unsafe_allow_html=True,
            )

# ── Export ────────────────────────────────────────────────────────────────────

st.divider()

export_rows = [
    {"Category": r.category, "Ratio": r.name, "Value": format_value(r), "Description": r.description}
    for r in results
]
df = pd.DataFrame(export_rows)
csv = df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇️ Export ratios as CSV",
    data=csv,
    file_name=f"{(company_name or 'company').lower().replace(' ','-')}-ratios.csv",
    mime="text/csv",
    use_container_width=True,
)
