"""
Gate B controlling_ni — 하위메커니즘 분류 x 구조규칙(section-based) 커버리지 교차표
(읽기전용, 2026-08-15). 78건 전체에 대해 (a) mismap/notfound/safetynet 분류와
(b) '~순이익...귀속'(포괄 제외) 2행 구조규칙 적용결과를 동시에 계산해 정밀 교차검증한다.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.db import get_session
from sqlalchemy import text
from fin2.layer3.combine import build_merged_lines, _map_rows

TOL = 2
CSV_PATH = Path(__file__).parent / "probe_gateb_reader_concept_gap_2026-08-15_results.csv"


def load_group_a():
    rows = list(csv.DictReader(open(CSV_PATH)))
    ni = [r for r in rows if r["field"] == "controlling_ni" and r["category"] == "CONCEPT_GAP"]
    return [r for r in ni
            if (int(r["db_won"]) >= 0) == (int(r["report_won"]) >= 0)
            and r["evidence_acode"] == "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent"]


def mechanism_bucket(cands: dict, db_won: int, report_won: int) -> str:
    ni_cands = cands.get("is.controlling_ni", [])
    single_wrong = (len(ni_cands) == 1 and abs(ni_cands[0]["value"] - db_won) <= TOL)
    found_elsewhere = any(
        abs(r["value"] - report_won) <= TOL
        for canon, rows in cands.items() if canon != "is.controlling_ni"
        for r in rows if r["value"] is not None
    )
    if len(ni_cands) > 1:
        return "SAFETYNET_FAIL"
    if single_wrong and found_elsewhere:
        return "MISMAP"
    if single_wrong and not found_elsewhere:
        return "UNMAPPED"
    return "OTHER"


def structural_rule(session, corp, fy, fp, basis, report_won):
    rows = session.execute(text("""
        SELECT label_raw, value_won, section_path, table_seq, row_order
        FROM report_lines
        WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
          AND basis=:b AND statement='IS' AND col_index=0 AND value_won IS NOT NULL
          AND header_hint IS NULL
        ORDER BY table_seq, row_order
    """), {"c": corp, "y": fy, "p": fp, "b": basis}).fetchall()
    sections: dict[tuple, list] = {}
    for r in rows:
        sp = r.section_path or ""
        if "귀속" in sp and "순이익" in sp and "포괄" not in sp:
            sections.setdefault((r.table_seq, sp), []).append(r)
    for key, members in sections.items():
        nci_rows = [m for m in members if "비지배" in (m.label_raw or "")]
        other_rows = [m for m in members if "비지배" not in (m.label_raw or "")]
        if len(nci_rows) == 1 and len(other_rows) == 1:
            cand = other_rows[0]
            return abs(cand.value_won - report_won) <= TOL
    return None  # no matching section shape


def main():
    group_a = load_group_a()
    crosstab: dict[tuple, int] = {}
    detail = {"MISMAP": {"HIT": [], "MISS": [], "NONE": []},
              "UNMAPPED": {"HIT": [], "MISS": [], "NONE": []},
              "SAFETYNET_FAIL": {"HIT": [], "MISS": [], "NONE": []},
              "OTHER": {"HIT": [], "MISS": [], "NONE": []}}

    with get_session() as s:
        for r in group_a:
            corp, fy, fp, basis = r["corp_code"], int(r["fiscal_year"]), r["fiscal_period"], r["basis"]
            db_won, report_won = int(r["db_won"]), int(r["report_won"])

            merged = build_merged_lines(s, corp, fy, fp)
            cands = _map_rows(merged, fp, basis, ("BS", "IS", "CF"))
            mech = mechanism_bucket(cands, db_won, report_won)

            sr = structural_rule(s, corp, fy, fp, basis, report_won)
            srkey = "HIT" if sr is True else ("MISS" if sr is False else "NONE")

            crosstab[(mech, srkey)] = crosstab.get((mech, srkey), 0) + 1
            detail[mech][srkey].append((corp, r["corp_name"], fy, fp, basis))

    print("=== 교차표 (메커니즘 x 구조규칙 결과) ===")
    print(f"{'mechanism':16s} {'HIT':>5s} {'MISS':>5s} {'NONE':>5s}")
    for mech in ("MISMAP", "UNMAPPED", "SAFETYNET_FAIL", "OTHER"):
        h = crosstab.get((mech, "HIT"), 0)
        m = crosstab.get((mech, "MISS"), 0)
        n = crosstab.get((mech, "NONE"), 0)
        print(f"{mech:16s} {h:5d} {m:5d} {n:5d}   (합계 {h+m+n})")

    print("\n=== MISMAP 중 구조규칙 NONE(미해결) 상세 ===")
    for row in detail["MISMAP"]["NONE"]:
        print(" ", row)
    print("\n=== MISMAP 중 구조규칙 MISS(오답) 상세 ===")
    for row in detail["MISMAP"]["MISS"]:
        print(" ", row)


if __name__ == "__main__":
    main()
