"""
Gate B controlling_ni 그룹A(78건) 전수 스캔 (읽기전용, 2026-08-15).

수동 원문(XML) 대조를 4개사(삼성전자·KPX홀딩스·동성케미컬·KG에코솔루션)로 확정한 메커니즘
[[gateb-controlling-ni-groupa-rootcause-2026-08-15]]을 나머지 74건까지 확장 검증한다:

  가설: is.controlling_ni 후보풀엔 OCI 섹션의 오답 1개만 단독으로 남고(그래서 _resolve()가
  자동확정, _resolve_ni_attribution 안전망 미발동), 진짜 정답(report_won)은 다른
  canonical(주로 is.net_income/is.noncontrolling_ni)의 후보풀 어딘가에 잘못 매핑돼 있다.

방법: build_merged_lines()+_map_rows()로 combine.py 가 실제로 보는 candidate pool 을
그대로 재현(원문 XML을 직접 다시 열지 않음 — report_lines 자체가 XML에서 추출된 결과이고,
4개사 표본에서 이미 XML과 report_lines 값 일치를 확인했으므로 이 스케일에서는 report_lines
기반 재현이 곧 원문 검증에 준함. 다만 완전한 원문 XML 재대조는 아니라는 점은 명시).

DB/코드 무변경, 읽기전용.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.db import get_session
from fin2.layer3.combine import build_merged_lines, _map_rows

TOL = 2  # won, 5dbecac 의 라운딩 허용오차와 동일 기준

CSV_PATH = Path(__file__).parent / "probe_gateb_reader_concept_gap_2026-08-15_results.csv"


def load_group_a():
    rows = list(csv.DictReader(open(CSV_PATH)))
    ni = [r for r in rows if r["field"] == "controlling_ni" and r["category"] == "CONCEPT_GAP"]
    return [r for r in ni
            if (int(r["db_won"]) >= 0) == (int(r["report_won"]) >= 0)
            and r["evidence_acode"] == "ifrs-full_ComprehensiveIncomeAttributableToOwnersOfParent"]


def classify(cands: dict, db_won: int, report_won: int):
    ni_cands = cands.get("is.controlling_ni", [])
    single_wrong = (len(ni_cands) == 1 and abs(ni_cands[0]["value"] - db_won) <= TOL)

    # search every OTHER canonical's candidate pool for a value matching report_won
    found_in = []
    for canon, rows in cands.items():
        if canon == "is.controlling_ni":
            continue
        for r in rows:
            if r["value"] is not None and abs(r["value"] - report_won) <= TOL:
                found_in.append((canon, r.get("stage"), r.get("label_raw")))

    if not ni_cands:
        shape = "NI_CANDS_EMPTY"
    elif len(ni_cands) == 1 and single_wrong:
        shape = "SINGLE_WRONG_CONFIRMED"
    elif len(ni_cands) > 1:
        shape = "MULTI_CANDS_UNEXPECTED"  # would mean this row shouldn't have auto-confirmed this way
    else:
        shape = "SINGLE_BUT_NOT_MATCHING_DB"  # single candidate, but doesn't match db_won (surprising)

    if found_in:
        mismap_canons = sorted({c for c, _, _ in found_in})
        cat = f"MISMAP_CONFIRMED:{'+'.join(mismap_canons)}"
    else:
        cat = "NOT_FOUND_IN_POOL"

    return shape, cat, found_in


def main():
    group_a = load_group_a()
    print(f"그룹A 총 {len(group_a)}건")

    shape_counter: dict[str, int] = {}
    cat_counter: dict[str, int] = {}
    not_found_rows = []
    unexpected_rows = []

    with get_session() as s:
        for r in group_a:
            corp = r["corp_code"]
            fy = int(r["fiscal_year"])
            fp = r["fiscal_period"]
            basis = r["basis"]
            db_won = int(r["db_won"])
            report_won = int(r["report_won"])

            merged = build_merged_lines(s, corp, fy, fp)
            cands = _map_rows(merged, fp, basis, ("BS", "IS", "CF"))

            shape, cat, found_in = classify(cands, db_won, report_won)
            shape_counter[shape] = shape_counter.get(shape, 0) + 1
            cat_counter[cat] = cat_counter.get(cat, 0) + 1

            if cat == "NOT_FOUND_IN_POOL":
                not_found_rows.append((corp, r["corp_name"], fy, fp, basis, db_won, report_won))
            if shape == "MULTI_CANDS_UNEXPECTED" or shape == "SINGLE_BUT_NOT_MATCHING_DB":
                unexpected_rows.append((corp, r["corp_name"], fy, fp, basis, shape, db_won, report_won,
                                         [(c["value"], c.get("stage")) for c in cands.get("is.controlling_ni", [])]))

    print("\n=== 후보풀 모양(shape) 분류 ===")
    for k, v in sorted(shape_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {k:28s} {v}")

    print("\n=== 정답값 소재(mismap 대상) 분류 ===")
    for k, v in sorted(cat_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {k:40s} {v}")

    print(f"\n=== NOT_FOUND_IN_POOL 상세 ({len(not_found_rows)}건) ===")
    for corp, name, fy, fp, basis, db_won, report_won in not_found_rows:
        print(f"  {corp} {name:16s} {fy} {fp} {basis:12s} db={db_won:>18,} report={report_won:>18,}")

    print(f"\n=== 예상외 shape 상세 ({len(unexpected_rows)}건) ===")
    for corp, name, fy, fp, basis, shape, db_won, report_won, ni_cands in unexpected_rows:
        print(f"  {corp} {name:16s} {fy} {fp} {basis:12s} shape={shape} db={db_won:>18,} report={report_won:>18,}")
        print(f"      is.controlling_ni cands: {ni_cands}")


if __name__ == "__main__":
    main()
