# financial-ratio-analyzer

Input income statement, balance sheet, and market data — get a full ratio dashboard across five categories. Optional AI commentary powered by Claude. Export results as CSV.

Built with Streamlit and Python.

## Ratios computed (22 total)

| Category | Ratios |
|---|---|
| **Valuation** | P/E, EV/EBITDA, EV/Revenue, P/B, P/S |
| **Profitability** | Gross Margin, EBITDA Margin, Operating Margin, Net Margin, ROE, ROA, ROIC |
| **Liquidity** | Current Ratio, Quick Ratio, Cash Ratio |
| **Leverage** | Debt/Equity, Net Debt/EBITDA, Debt/Assets, Interest Coverage |
| **Efficiency** | Asset Turnover, Inventory Turnover, DIO, DSO |

- Ratios are skipped (shown as N/A) when the required inputs are missing — no crashes
- Enterprise Value is auto-calculated from Market Cap + Net Debt, or can be entered manually
- All inputs in $M except share price, EPS, and shares outstanding

## AI Commentary

With an Anthropic API key, click **Analyze with AI** to get a 150-200 word analyst-style take on the most notable findings — written to surface what matters, not restate every number.

## Setup

```bash
git clone https://github.com/owen-alderson/financial-ratio-analyzer.git
cd financial-ratio-analyzer
pip install -r requirements.txt
cp .env.example .env   # add API key for AI commentary (optional)
streamlit run app.py
```

Opens at `http://localhost:8501`. The ratio calculator works without an API key.

## Requirements

- Python 3.8+
- Anthropic API key (optional — only needed for AI commentary)
