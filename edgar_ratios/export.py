"""JSON (everything, with provenance) and CSV (one row per ratio per year) output."""

import csv
import io
import json

from .facts import Fact, Figure, Missing
from .ratios import Analysis


def _fact(f: Fact, cik: int) -> dict:
    return {
        "concept": f.concept, "value": f.value, "unit": f.unit, "period_start": str(f.start) if f.start else None,
        "period_end": str(f.end), "form": f.form, "fiscal_year": f.fy, "accession": f.accn,
        "filed": str(f.filed), "url": f.filing_url(cik),
    }


def _input(fig: Figure | Missing, cik: int) -> dict:
    if isinstance(fig, Missing):
        return {"value": None, "unavailable": fig.reason}
    return {"value": fig.value, "how": fig.how, "notes": fig.notes, "sources": [_fact(s, cik) for s in fig.sources]}


def to_dict(a: Analysis) -> dict:
    cik = a.company.cik
    return {
        "ticker": a.company.ticker,
        "name": a.company.name,
        "cik": f"{cik:010d}",
        "source": "SEC EDGAR XBRL company facts (10-K and 10-K/A only)",
        "fetched": a.fetched.isoformat(),
        "price": {"value": a.price.value, "as_of": str(a.price.as_of), "source": "supplied by the user"} if a.price else None,
        "notes": a.notes,
        "years": [
            {
                "fiscal_year": yr.year.fy,
                "label": yr.year.label,
                "period_end": str(yr.year.end),
                "accession": yr.year.accn,
                "ratios": [
                    {"name": v.ratio.name, "category": v.ratio.category, "unit": v.ratio.fmt,
                     "value": v.value, "unavailable": v.reason, "formula": v.ratio.explain}
                    for v in yr.values
                ],
                "inputs": {name: _input(fig, cik) for name, fig in yr.inputs.items()},
            }
            for yr in a.years
        ],
    }


def to_json(analyses: list[Analysis]) -> str:
    return json.dumps([to_dict(a) for a in analyses], indent=2)


def to_csv(analyses: list[Analysis]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ticker", "fiscal_year", "period_end", "category", "ratio", "value", "unit", "unavailable"])
    for a in analyses:
        for yr in a.years:
            for v in yr.values:
                writer.writerow([a.company.ticker, yr.year.fy, yr.year.end, v.ratio.category, v.ratio.name,
                                 "" if v.value is None else round(v.value, 6), v.ratio.fmt, v.reason or ""])
    return out.getvalue()
