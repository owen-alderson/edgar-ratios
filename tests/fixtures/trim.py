"""Rebuild the test fixtures from real EDGAR data, trimmed to the concepts edgar-ratios reads.

    python tests/fixtures/trim.py ~/.edgar-ratios/cache/companyfacts-0000320193.json aapl.json
"""

import json
import sys
from pathlib import Path

from edgar_ratios.facts import CONCEPTS, DA_CONCEPTS

KEEP = {c for _, _, concepts in CONCEPTS.values() for c in concepts} | set(DA_CONCEPTS) | {
    "Depreciation", "AmortizationOfIntangibleAssets", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "LongTermDebtNoncurrent", "LongTermDebtCurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations",
    "ShortTermBorrowings", "CommercialPaper", "CommonStockSharesOutstanding",
}
SINCE = "2018-01-01"


def trim(data: dict) -> dict:
    facts = {}
    for taxonomy, concepts in data["facts"].items():
        for concept, body in concepts.items():
            shares = concept in ("EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding")
            if concept not in KEEP and not shares:
                continue
            units = {}
            for unit, raws in body["units"].items():
                kept = [r for r in raws if r["end"] >= SINCE and (shares or r.get("form") in ("10-K", "10-K/A"))]
                if kept:
                    units[unit] = kept
            if units:
                facts.setdefault(taxonomy, {})[concept] = {"units": units}
    return {"cik": data["cik"], "entityName": data["entityName"], "facts": facts}


if __name__ == "__main__":
    src, dest = sys.argv[1], sys.argv[2]
    out = Path(__file__).parent / dest
    out.write_text(json.dumps(trim(json.loads(Path(src).read_text())), separators=(",", ":")))
    print(f"{out}: {out.stat().st_size // 1024} KB")
