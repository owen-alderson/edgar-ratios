"""Terminal output: ratio tables per fiscal year, peer comparison, and the sources behind each number."""

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from .facts import LABELS, Figure, Missing, fmt_money
from .ratios import CATEGORIES, NO_PRICE, OLD_YEAR, RATIOS, Analysis, Value

UNITS = {"eps_diluted": "USD/shares", "eps_for_price": "USD/shares", "price": "USD/shares", "shares": "shares"}


def fmt_value(value: Value) -> str:
    if value.value is None:
        return "n/a"
    v, fmt = value.value, value.ratio.fmt
    if fmt == "%":
        return f"{v:.1f}%"
    if fmt == "x":
        return f"{v:.2f}x" if abs(v) < 1 else f"{v:.1f}x"
    if fmt == "days":
        return f"{v:.0f} days"
    return f"{v:.2f}"


def _cell(value: Value) -> Text:
    return Text(fmt_value(value), style="dim" if value.value is None else "")


def header(a: Analysis) -> Text:
    fy = a.latest.year
    text = Text()
    text.append(f"{a.company.name}", style="bold")
    text.append(f"  {a.company.ticker} · CIK {a.company.cik:010d}\n", style="dim")
    text.append(f"SEC EDGAR XBRL data, 10-K filings only · fetched {a.fetched:%Y-%m-%d %H:%M} UTC · "
                f"latest fiscal year {fy.label} ended {fy.end}", style="dim")
    return text


def _footnotes(rows: list[tuple[str, str, str]]) -> list[Text]:
    """Group (ratio, column, reason) into one line per ratio and reason."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for ratio, column, reason in rows:
        grouped.setdefault((ratio, reason), []).append(column)
    lines = []
    for (ratio, reason), columns in grouped.items():
        line = Text("  ")
        line.append(ratio, style="bold")
        line.append(f" ({', '.join(columns)}): ", style="dim")
        line.append(reason)
        lines.append(line)
    return lines


def _notes(a: Analysis) -> list[str]:
    """Restatements and approximations behind the inputs, each listed once."""
    seen: dict[str, list[str]] = {}
    for yr in a.years:
        for fig in yr.inputs.values():
            if isinstance(fig, Figure):
                for note in fig.notes:
                    if "supplied by you" in note:
                        continue
                    seen.setdefault(note, []).append(yr.year.label)
    return a.notes + [f"{note} ({', '.join(dict.fromkeys(years))})" for note, years in seen.items()]


def company_view(a: Analysis) -> Group:
    parts: list = [header(a), Text()]
    missing: list[tuple[str, str, str]] = []
    labels = [yr.year.label for yr in a.years]
    for category in CATEGORIES:
        table = Table(title=category, title_justify="left", title_style="bold cyan", box=None,
                      header_style="dim", pad_edge=False, padding=(0, 2))
        table.add_column("", min_width=24)
        for lab in labels:
            table.add_column(lab, justify="right", min_width=9)  # same width in every table, so years line up
        for i, ratio in enumerate(RATIOS):
            if ratio.category != category:
                continue
            row = [yr.values[i] for yr in a.years]
            if category == "Valuation" and all(v.value is None for v in row) and a.price is None:
                continue
            table.add_row(ratio.name, *[_cell(v) for v in row])
            missing += [(ratio.name, lab, v.reason) for lab, v in zip(labels, row) if v.value is None]
        if category == "Valuation" and a.price is None:
            parts += [Text("Valuation", style="bold cyan"),
                      Text("  Needs a share price: pass --price (SEC filings don't contain market prices).", style="dim"),
                      Text()]
            continue
        parts += [table, Text()]
    footnotes = _footnotes([m for m in missing if m[2] not in (NO_PRICE, OLD_YEAR)])
    if footnotes:
        parts += [Text("Not available", style="bold yellow"), *footnotes, Text()]
    notes = _notes(a)
    if notes:
        parts += [Text("Notes", style="bold"), *[Text(f"  {n}") for n in notes], Text()]
    return Group(*parts)


def peers_view(analyses: list[Analysis]) -> Group:
    table = Table(box=None, header_style="dim", pad_edge=False, padding=(0, 2))
    table.add_column("", min_width=24)
    for a in analyses:
        table.add_column(f"{a.company.ticker}\n{a.latest.year.label}", justify="right")
    missing: list[tuple[str, str, str]] = []
    any_price = any(a.price for a in analyses)
    for category in CATEGORIES:
        if category == "Valuation" and not any_price:
            continue
        table.add_row(Text(category, style="bold cyan"))
        for i, ratio in enumerate(RATIOS):
            if ratio.category != category:
                continue
            row = [a.latest.values[i] for a in analyses]
            table.add_row(f"  {ratio.name}", *[_cell(v) for v in row])
            missing += [(ratio.name, a.company.ticker, v.reason) for a, v in zip(analyses, row) if v.value is None]
    parts: list = [
        Text("Latest fiscal year per company: their years end on different dates.", style="dim"),
        *[Text(f"  {a.company.ticker}: {a.company.name}, {a.latest.year.label} ended {a.latest.year.end}", style="dim")
          for a in analyses],
        Text(), table, Text(),
    ]
    if not any_price:
        parts += [Text("Valuation ratios need a share price: pass --price TICKER=PRICE for each company.", style="dim"), Text()]
    footnotes = _footnotes(missing)
    if footnotes:
        parts += [Text("Not available", style="bold yellow"), *footnotes, Text()]
    return Group(*parts)


def sources_view(a: Analysis) -> Group:
    """Every input figure with the XBRL concept and filing it came from."""
    parts: list = [Text(f"Sources: {a.company.name} ({a.company.ticker})", style="bold"), Text()]
    for yr in a.years:
        table = Table(title=f"{yr.year.label} (ended {yr.year.end})", title_justify="left", title_style="bold cyan",
                      box=None, header_style="dim", pad_edge=False, padding=(0, 2))
        table.add_column("Input")
        table.add_column("Value", justify="right", no_wrap=True)
        table.add_column("From", overflow="fold")  # wrap, never truncate: these are what you trace
        table.add_column("Filing", overflow="fold")
        for name, fig in yr.inputs.items():
            if isinstance(fig, Missing):
                table.add_row(LABELS.get(name, name), Text("n/a", style="dim"), Text(fig.reason, style="dim"), "")
            else:
                filings = "; ".join(dict.fromkeys(f"{s.form} filed {s.filed} ({s.accn})" for s in fig.sources))
                table.add_row(LABELS.get(name, name), fmt_money(fig.value, UNITS.get(name, "USD")), fig.how, filings)
        parts += [table, Text()]
    return Group(*parts)


def print_all(analyses: list[Analysis], sources: bool, console: Console | None = None) -> None:
    console = console or Console()
    if len(analyses) == 1:
        console.print(company_view(analyses[0]))
    else:
        console.print(peers_view(analyses))
    if sources:
        for a in analyses:
            console.print(sources_view(a))
