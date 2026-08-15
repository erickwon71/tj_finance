"""
Gate B 리더측 결함 영향범위 전수스캔 (읽기전용, 2026-08-15).

가설(삼천리·대우건설 원문대조로 확정): fail_a 의 상당수가 std_v3 데이터 버그가 아니라
Gate B 감사기(`fin2/audit/face_audit.py`)의 원문 재추출 자체가 틀려서 생긴다. 확인된
두 메커니즘:
  (1) CONCEPT_GAP — `fin2/taxonomy/concept_map.py` 에 그 회사가 실제로 쓰는 ACODE가
      아예 안 실려있어, 후보 자체가 다른(엉뚱한) ACODE 로 좁혀짐.
  (2) AXIS_EXCLUDED — 진짜 정답 fact 가 DART 의 보일러플레이트 축(예:
      CarryingAmount...Axis_dart_ReportedAmountMember)에 감싸여 있어 `is_dimensional`
      판정이 "차원분해"로 오인, 후보에서 제외됨.
  (3) ADECIMAL_MISTAG — 매핑된 ACODE의 홈(비차원) fact 가 ADECIMAL 자체를 잘못 태깅.

각 fail_a 행에 대해, concept_map/is_dimensional 필터를 걷어내고 **원문 전체 TE facts**
에서 db_won 과 정확히 일치하는 fact 를 찾아 위 카테고리로 재분류한다(집계 후 개별사례
원문대조 없이 결론내지 않기 — feedback-verify-against-source).

읽기전용: DB/코드 무변경. 결과만 stdout(요약) + CSV.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from fin2.audit.face_audit import (
    STD_FIELD_CANONICAL, _parse_xml_file, _cell_text, _parse_adecimal, _amount_won,
)
from fin2.extract.acontext import parse_acontext
from fin2.taxonomy.concept_map import map_acode, ACODE_TO_CANONICAL

_XBRL_PREFIXES = ("ifrs-full_", "dart_")


def parse_displayed(text_: str) -> int | None:
    from fin2.audit.face_audit import parse_displayed as _pd
    return _pd(text_)


def _row_rcepts(source_rcepts) -> dict:
    return dict(source_rcepts or {})


def inventory_of(root):
    """원문 전체 TE[@ACODE] facts 를 (acode, basis, col_index, is_cumulative) 로 인벤토리."""
    out = []
    for te in root.findall(".//TE[@ACODE]"):
        acode = te.get("ACODE", "")
        if not acode.startswith(_XBRL_PREFIXES) or len(acode) > 255:
            continue
        acontext = te.get("ACONTEXT", "")
        if not acontext:
            continue
        ctx = parse_acontext(acontext)
        if not ctx.parsed or ctx.col_index != 0:
            continue
        displayed = parse_displayed(_cell_text(te))
        if displayed is None:
            continue
        adecimal = _parse_adecimal(te)
        won = _amount_won(displayed, adecimal) if adecimal is not None else displayed
        out.append({
            "acode": acode, "basis": ctx.basis, "is_dimensional": ctx.is_dimensional,
            "extra_dims": ctx.extra_dims, "displayed": displayed, "adecimal": adecimal,
            "won": won, "is_cumulative": ctx.is_cumulative,
        })
    return out


def classify(field: str, basis: str, db_won: int, facts: list) -> tuple[str, dict | None]:
    canon = STD_FIELD_CANONICAL.get(field)
    tol = 1
    cands_all = [f for f in facts if f["basis"] in (basis, None)]

    # (1) concept gap: acode not in map, home context, exact/near match
    for f in cands_all:
        if f["is_dimensional"]:
            continue
        if map_acode(f["acode"]) is not None:
            continue
        if abs(f["won"] - db_won) <= tol:
            return "CONCEPT_GAP", f

    # (2) axis excluded: acode maps to this canon (or would), dimensional, exact match
    for f in cands_all:
        if not f["is_dimensional"]:
            continue
        if abs(f["won"] - db_won) <= tol:
            mapped = map_acode(f["acode"])
            return ("AXIS_EXCLUDED_MAPPED" if mapped == canon else "AXIS_EXCLUDED_UNMAPPED"), f

    # (3) adecimal mistag: acode maps to this canon, home, wrong adecimal but alt scale matches
    for f in cands_all:
        if f["is_dimensional"]:
            continue
        if map_acode(f["acode"]) != canon:
            continue
        for alt in (-6, -3, 0, 3):
            alt_won = _amount_won(f["displayed"], alt)
            if abs(alt_won - db_won) <= tol:
                return "ADECIMAL_MISTAG", {**f, "alt_adecimal": alt}

    # (4) additive-pair: sum of 2 home facts (mapped-canon candidates + siblings) matches
    home_same_acode_family = [f for f in cands_all if not f["is_dimensional"]]
    for i, f1 in enumerate(home_same_acode_family):
        for f2 in home_same_acode_family[i + 1:]:
            if abs((f1["won"] + f2["won"]) - db_won) <= tol:
                return "ADDITIVE_PAIR_CANDIDATE", {"a": f1, "b": f2}

    return "UNRESOLVED", None


def main():
    with get_session() as s:
        rows = s.execute(text("""
            SELECT fa.corp_code, co.corp_name, fa.fiscal_year, fa.fiscal_period,
                   fa.statement_type AS basis, fa.fail_detail, sfv.source_rcepts
            FROM face_audit fa
            JOIN corporations co ON co.corp_code = fa.corp_code
            JOIN std_financials_v3 sfv
              ON sfv.corp_code = fa.corp_code AND sfv.fiscal_year = fa.fiscal_year
             AND sfv.fiscal_period = fa.fiscal_period AND sfv.statement_type = fa.statement_type
            WHERE fa.source_version = 'v3' AND fa.gate_status = 'fail_a'
        """)).fetchall()
        print(f"대상 fail_a 행수: {len(rows)}")

        rcepts_needed = set()
        for r in rows:
            rcepts_needed |= set((r.source_rcepts or {}).values())
        fmap = {}
        if rcepts_needed:
            frows = s.execute(text("""
                SELECT rcept_no, file_path FROM download_tasks
                WHERE rcept_no = ANY(:rs) AND file_type = 'xml' AND status='completed'
                  AND file_path IS NOT NULL
            """), {"rs": list(rcepts_needed)}).fetchall()
            fmap = {fr.rcept_no: fr.file_path for fr in frows}

    _STMT_OF = {"bs.": "BS", "is.": "IS", "cf.": "CF"}
    xml_cache: dict[str, list] = {}
    results = []
    counter = Counter()
    field_counter = defaultdict(Counter)

    for r in rows:
        detail = r.fail_detail
        if isinstance(detail, str):
            import json
            detail = json.loads(detail)
        rc = _row_rcepts(r.source_rcepts)
        for fd in detail:
            field = fd.get("field")
            reason = fd.get("reason")
            if reason != "VALUE_DIFF":
                continue
            canon = STD_FIELD_CANONICAL.get(field) or fd.get("canonical", "")
            stmt = _STMT_OF.get(canon[:3], "")
            rcept = rc.get(stmt)
            fpath = fmap.get(rcept)
            if not fpath:
                counter["NO_FILE"] += 1
                continue
            if fpath not in xml_cache:
                root = _parse_xml_file(Path(fpath))
                xml_cache[fpath] = inventory_of(root) if root is not None else []
            facts = xml_cache[fpath]
            db_won = fd.get("db_won")
            if db_won is None:
                counter["NO_DB_WON"] += 1
                continue
            cat, evidence = classify(field, r.basis, db_won, facts)
            counter[cat] += 1
            field_counter[field][cat] += 1
            results.append({
                "corp_code": r.corp_code, "corp_name": r.corp_name,
                "fiscal_year": r.fiscal_year, "fiscal_period": r.fiscal_period,
                "basis": r.basis, "field": field, "db_won": db_won,
                "report_won": fd.get("report_won"), "category": cat,
                "evidence_acode": (evidence or {}).get("acode") if evidence and "acode" in evidence else "",
            })

    print("\n=== 전체 분류 ===")
    for cat, n in counter.most_common():
        print(f"  {cat:28s} {n}")

    print("\n=== 필드별 분류(상위) ===")
    for field, c in sorted(field_counter.items(), key=lambda kv: -sum(kv[1].values()))[:15]:
        print(f"  [{field}] total={sum(c.values())}")
        for cat, n in c.most_common():
            print(f"      {cat:28s} {n}")

    out_path = Path("scripts/probe_gateb_reader_concept_gap_2026-08-15_results.csv")
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["corp_code", "corp_name", "fiscal_year", "fiscal_period",
                                           "basis", "field", "db_won", "report_won", "category",
                                           "evidence_acode"])
        w.writeheader()
        w.writerows(results)
    print(f"\nCSV 저장: {out_path} ({len(results)}행)")


if __name__ == "__main__":
    main()
