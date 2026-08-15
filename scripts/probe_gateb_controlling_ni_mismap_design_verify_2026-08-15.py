"""
Gate B controlling_ni mismap(53건) — 구조기반 수정설계 사전검증 (읽기전용, 2026-08-15).

가설: '~귀속' 섹션은 report_lines 상 정확히 2행(지배+비지배)으로 구성된다. 그중 라벨에
'비지배'가 들어간 행을 앵커로 잡으면, 같은 섹션의 나머지 행은 (라벨 텍스트와 무관하게)
controlling_ni로 구조적 확정 가능하다 — [[gateb-controlling-ni-groupa-rootcause-2026-08-15]]
mismap 53건에 이 규칙을 적용했을 때 report_won과 실제로 일치하는지 전수 검증.

DB/코드 무변경, 읽기전용.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session

TOL = 2
CSV_PATH = Path(__file__).parent / "probe_gateb_reader_concept_gap_2026-08-15_results.csv"


def load_group_a():
    rows = list(csv.DictReader(open(CSV_PATH)))
    ni = [r for r in rows if r["field"] == "controlling_ni" and r["category"] == "CONCEPT_GAP"]
    return [r for r in ni
            if (int(r["db_won"]) >= 0) == (int(r["report_won"]) >= 0)
            and r["evidence_acode"] == "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent"]


def try_structural_rule(session, corp, fy, fp, basis, report_won):
    """'귀속' 섹션에서 '비지배' 행을 앵커로, 나머지 행을 controlling 후보로 반환."""
    rows = session.execute(text("""
        SELECT label_raw, value_won, section_path, table_seq, row_order, depth
        FROM report_lines
        WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
          AND basis=:b AND statement='IS' AND col_index=0 AND value_won IS NOT NULL
          AND header_hint IS NULL
        ORDER BY table_seq, row_order
    """), {"c": corp, "y": fy, "p": fp, "b": basis}).fetchall()

    # group by (table_seq, section_path) where section_path is a NET-INCOME attribution
    # section specifically ('순이익...귀속', excluding '포괄'/comprehensive-income sections)
    sections: dict[tuple, list] = {}
    for r in rows:
        sp = r.section_path or ""
        if "귀속" in sp and "순이익" in sp and "포괄" not in sp:
            key = (r.table_seq, sp)
            sections.setdefault(key, []).append(r)

    for key, members in sections.items():
        nci_rows = [m for m in members if "비지배" in (m.label_raw or "")]
        other_rows = [m for m in members if "비지배" not in (m.label_raw or "")]
        if len(nci_rows) == 1 and len(other_rows) == 1:
            cand = other_rows[0]
            match = abs(cand.value_won - report_won) <= TOL
            return match, cand.label_raw, cand.value_won, key
        # ambiguous section shape (0, 2+ nci rows, or 3+ total) -> skip this section
    return None, None, None, None


def main():
    group_a = load_group_a()
    # mismap-relevant subset per prior scan categories (recomputed here via same CSV filter
    # is not directly taggable without re-running the scale scan; instead we just try the
    # structural rule against ALL 78 and report which succeed/fail — this also re-derives
    # the mismap/not-found split independently as a cross-check).
    print(f"그룹A 총 {len(group_a)}건에 구조규칙 시도")

    ok, wrong, no_section = 0, 0, 0
    wrong_rows = []
    no_section_rows = []

    with get_session() as s:
        for r in group_a:
            corp = r["corp_code"]
            fy = int(r["fiscal_year"])
            fp = r["fiscal_period"]
            basis = r["basis"]
            report_won = int(r["report_won"])

            match, label, val, key = try_structural_rule(s, corp, fy, fp, basis, report_won)
            if match is None:
                no_section += 1
                no_section_rows.append((corp, r["corp_name"], fy, fp, basis))
            elif match:
                ok += 1
            else:
                wrong += 1
                wrong_rows.append((corp, r["corp_name"], fy, fp, basis, label, val, report_won))

    print(f"\n구조규칙 성공(report_won과 일치): {ok}")
    print(f"구조규칙 적용됐지만 값 불일치: {wrong}")
    print(f"적용 불가(섹션 모양 자체가 안 나옴, 2행 구조 아님): {no_section}")

    print(f"\n=== 값 불일치 상세 ({len(wrong_rows)}건) ===")
    for corp, name, fy, fp, basis, label, val, report_won in wrong_rows:
        print(f"  {corp} {name:16s} {fy} {fp} {basis:12s} 규칙결과={val:>18,}({label!r}) vs report={report_won:>18,}")

    print(f"\n=== 섹션구조 없음 상세 ({len(no_section_rows)}건) ===")
    for corp, name, fy, fp, basis in no_section_rows:
        print(f"  {corp} {name:16s} {fy} {fp} {basis}")


if __name__ == "__main__":
    main()
