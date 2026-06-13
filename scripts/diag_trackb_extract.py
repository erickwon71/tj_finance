"""
item 4 검증 — Track B extract_facts 실제 산출(무 DB) 카운트·매핑·표본값.

    PYTHONPATH=. .venv_tj_finance/bin/python scripts/diag_trackb_extract.py <xml> <corp> <year> <period>
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fin2.extract.text import extract_facts


def main() -> None:
    xml, corp, year, period = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    facts = extract_facts(xml, rcept_no="TEST", corp_code=corp,
                          report_fiscal_year=year, report_fiscal_period=period)
    print(f"추출 fact: {len(facts)}")
    by_basis = Counter(f.basis for f in facts)
    mapped = sum(1 for f in facts if f.canonical_account)
    print(f"basis: {dict(by_basis)}")
    print(f"canonical 매핑: {mapped}/{len(facts)} ({100*mapped/max(1,len(facts)):.0f}%)")

    print("\n연결 BS 주요 계정(col0=당기):")
    for f in facts:
        if f.basis == "consolidated" and f.period_kind == "instant" and f.col_index == 0 and f.canonical_account:
            if f.canonical_account in ("bs.total_assets", "bs.cash", "bs.total_equity",
                                       "bs.total_liabilities"):
                print(f"  {f.canonical_account:22} {f.amount_won:>20,}  ({f.acode[:20]})")

    print("\n매핑 안 된(canonical NULL) acode 표본 12:")
    seen = set()
    for f in facts:
        if not f.canonical_account and f.acode not in seen:
            seen.add(f.acode)
            print(f"  {f.acode[:50]}")
            if len(seen) >= 12:
                break


if __name__ == "__main__":
    main()
