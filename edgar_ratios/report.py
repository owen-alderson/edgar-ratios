"""A single self-contained HTML report: ratio tables, what's unavailable and why, and linked sources."""

from datetime import datetime, timezone
from html import escape

from .facts import LABELS, Figure, Missing, fmt_money
from .ratios import CATEGORIES, NO_PRICE, OLD_YEAR, RATIOS, Analysis
from .render import UNITS, fmt_value

CSS = """
:root { --bg:#fff; --fg:#1d1f23; --muted:#6b7280; --line:#e5e7eb; --accent:#2563eb; --na:#9ca3af; }
@media (prefers-color-scheme: dark) { :root { --bg:#111317; --fg:#e5e7eb; --muted:#9ca3af; --line:#2a2d35; --accent:#60a5fa; --na:#6b7280; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; max-width:1100px; margin:0 auto; padding:24px 16px; }
h1 { font-size:1.5rem; margin:0 0 4px; } h2 { font-size:1.15rem; margin:32px 0 8px; } h3 { font-size:.8rem; text-transform:uppercase; letter-spacing:.06em; color:var(--accent); margin:20px 0 4px; }
.muted, .meta { color:var(--muted); font-size:.85rem; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { padding:6px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; }
td.na { color:var(--na); }
td.wrap { white-space:normal; text-align:left; }
a { color:var(--accent); }
ul { padding-left:20px; } li { margin:2px 0; }
"""


def _ratio_tables(a: Analysis) -> str:
    html = []
    for category in CATEGORIES:
        rows = []
        for i, ratio in enumerate(RATIOS):
            if ratio.category != category:
                continue
            cells = "".join(
                f'<td class="na" title="{escape(yr.values[i].reason or "")}">n/a</td>' if yr.values[i].value is None
                else f"<td>{escape(fmt_value(yr.values[i]))}</td>"
                for yr in a.years
            )
            rows.append(f'<tr><td title="{escape(ratio.explain)}">{escape(ratio.name)}</td>{cells}</tr>')
        head = "".join(f"<th>{escape(yr.year.label)}</th>" for yr in a.years)
        html.append(f'<h3>{category}</h3><div class="scroll"><table><tr><th></th>{head}</tr>{"".join(rows)}</table></div>')
    return "".join(html)


def _unavailable(a: Analysis) -> str:
    grouped: dict[tuple[str, str], list[str]] = {}
    for yr in a.years:
        for v in yr.values:
            if v.value is None and v.reason not in (NO_PRICE, OLD_YEAR):
                grouped.setdefault((v.ratio.name, v.reason), []).append(yr.year.label)
    if not grouped:
        return ""
    items = "".join(f"<li><b>{escape(r)}</b> ({escape(', '.join(ys))}): {escape(reason)}</li>"
                    for (r, reason), ys in grouped.items())
    return f"<h3>Not available</h3><ul>{items}</ul>"


def _notes(a: Analysis) -> str:
    seen: dict[str, list[str]] = {}
    for yr in a.years:
        for fig in yr.inputs.values():
            if isinstance(fig, Figure):
                for note in fig.notes:
                    seen.setdefault(note, []).append(yr.year.label)
    items = [escape(n) for n in a.notes] + [f"{escape(n)} ({escape(', '.join(dict.fromkeys(ys)))})" for n, ys in seen.items()]
    if a.price is None:
        items.insert(0, "Valuation ratios need a share price (SEC filings contain no market prices); run with --price.")
    return f"<h3>Notes</h3><ul>{''.join(f'<li>{i}</li>' for i in items)}</ul>" if items else ""


def _sources(a: Analysis) -> str:
    html = []
    for yr in a.years:
        rows = []
        for name, fig in yr.inputs.items():
            if isinstance(fig, Missing):
                rows.append(f'<tr><td>{escape(LABELS.get(name, name))}</td><td class="na">n/a</td>'
                            f'<td class="wrap muted" colspan="2">{escape(fig.reason)}</td></tr>')
                continue
            links = ", ".join(dict.fromkeys(
                f'<a href="{escape(s.filing_url(a.company.cik))}">{escape(s.form)} filed {s.filed}</a>' for s in fig.sources))
            rows.append(f"<tr><td>{escape(LABELS.get(name, name))}</td><td>{escape(fmt_money(fig.value, UNITS.get(name, 'USD')))}</td>"
                        f'<td class="wrap">{escape(fig.how)}</td><td class="wrap">{links}</td></tr>')
        html.append(f'<h3>{escape(yr.year.label)} (ended {yr.year.end})</h3><div class="scroll"><table>'
                    f"<tr><th>Input</th><th>Value</th><th>XBRL concept</th><th>Filing</th></tr>{''.join(rows)}</table></div>")
    return "".join(html)


def to_html(analyses: list[Analysis], commentary: str | None = None) -> str:
    title = " vs ".join(a.company.ticker for a in analyses) + " financial ratios"
    body = []
    if commentary:
        paragraphs = "".join(f"<p>{escape(p)}</p>" for p in commentary.split("\n\n") if p.strip())
        body.append(f"<h2>Commentary</h2><p class=\"muted\">Written by Claude from the numbers below.</p>{paragraphs}")
    for a in analyses:
        fy = a.latest.year
        body.append(
            f"<h2>{escape(a.company.name)} ({escape(a.company.ticker)})</h2>"
            f'<p class="meta">CIK {a.company.cik:010d} · SEC EDGAR XBRL data, 10-K filings only · fetched '
            f"{a.fetched:%Y-%m-%d %H:%M} UTC · latest fiscal year {escape(fy.label)} ended {fy.end}</p>"
            f"{_ratio_tables(a)}{_unavailable(a)}{_notes(a)}<h3>Sources</h3>{_sources(a)}"
        )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(title)}</title>'
        f"<style>{CSS}</style></head><body><h1>{escape(title)}</h1>"
        f'<p class="muted">Generated by edgar-ratios on {generated}. Every figure links to the SEC filing it came from. '
        "Hover a ratio for its formula, or an n/a for the reason.</p>"
        f"{''.join(body)}</body></html>\n"
    )
