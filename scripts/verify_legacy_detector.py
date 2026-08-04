"""구형 레이아웃 감지기 검증 — **실제 코드 경로**(`_detect_body_statement_tables`)를 돌린다.

세 가지를 확인한다:
  ① 복구  — 2015+ 계층2 공백 189건에서 본문표가 몇 건·무엇으로 잡히는가
  ② 무영향 — **이미 적재된** filing 표본에서 결과가 종전과 동일한가(폴백 미발동 확인)
  ③ 근접성 — 헤딩과 데이터표 사이 거리 분포(대기 상태 상한의 실측 근거)

사용:
    python scripts/verify_legacy_detector.py                 # ①+③
    python scripts/verify_legacy_detector.py --loaded 400    # ② 적재분 표본 무영향
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    SEC_CONSOL_FS, SEC_SEP_FS, SEC_LEGACY_FS,
    assign_tables_to_dart_sections, iter_section_elements, table_direct_rows,
)
from fin2.extract.statement_titles import (
    classify_legacy_statement_heading, is_legacy_note_marker,
)
from fin2.extract.text import (
    _detect_body_statement_tables, _detect_fin_type, _table_has_data_rows,
)

from scripts.probe_legacy_layout_gap import SQL_GAP

SQL_LOADED = """
SELECT f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no
  FROM filings f
 WHERE f.fiscal_year >= 2015
   AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
 ORDER BY md5(f.rcept_no)
 LIMIT :n
"""


def heading_distances(root) -> list[int]:
    """헤딩 → 그 헤딩이 연결한 데이터표까지의 요소 거리."""
    out = []
    pending_at = None
    for i, (tag, el) in enumerate(iter_section_elements(root, SEC_LEGACY_FS)):
        txt = " ".join("".join(el.itertext()).split())
        if tag == "TABLE" and _table_has_data_rows(el):
            if pending_at is not None:
                out.append(i - pending_at)
                pending_at = None
            continue
        if is_legacy_note_marker(txt):
            pending_at = None
            continue
        if classify_legacy_statement_heading(txt, include_sce=True):
            pending_at = i
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loaded", type=int, default=0,
                    help="적재분 표본 N건에서 폴백 미발동 확인")
    args = ap.parse_args()

    with get_session() as s:
        tasks = {r[0]: r[1] for r in s.execute(text(
            "SELECT rcept_no, file_path FROM download_tasks")).fetchall()}
        if args.loaded:
            rows = [(None, r[0], r[1], r[2], None, r[3], None) for r in
                    s.execute(text(SQL_LOADED), {"n": args.loaded}).fetchall()]
        else:
            rows = s.execute(text(SQL_GAP)).fetchall()

    recovered = 0
    still_empty = 0
    code_counter: Counter = Counter()
    dist: Counter = Counter()
    fallback_fired = 0
    per_doc: Counter = Counter()

    for _cc, corp_name, fy, fp, _rt, rcept, _filed in rows:
        fpth = tasks.get(rcept)
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue

        sec = assign_tables_to_dart_sections(root)
        is_legacy = not sec.get(SEC_CONSOL_FS) and not sec.get(SEC_SEP_FS)
        groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)

        if args.loaded:
            if is_legacy:
                fallback_fired += 1
                print(f"  ⚠ 적재분인데 폴백 발동: {corp_name} {fy}{fp} {rcept} → {list(groups)}")
            continue

        if not is_legacy:
            continue
        n = sum(len(v) for v in groups.values())
        per_doc[n] += 1
        if n:
            recovered += 1
            for k, v in groups.items():
                code_counter[k] += len(v)
            for d in heading_distances(root):
                dist[d] += 1
        else:
            still_empty += 1

    if args.loaded:
        print(f"\n=== 적재분 표본 {args.loaded}건 ===")
        print(f"구형 폴백 발동: {fallback_fired}건 (0 이어야 무영향)")
        return 0

    print(f"=== 구형 레이아웃 문서 {recovered + still_empty}건 ===")
    print(f"  본문표 복구됨 : {recovered}")
    print(f"  여전히 0     : {still_empty}")
    print("\n문서당 복구 표 수:")
    for k, v in sorted(per_doc.items()):
        print(f"  {k:3d}표 → {v:4d}건")
    print("\n섹션코드별 복구 표 수:")
    for k, v in sorted(code_counter.items()):
        print(f"  {k:6s} {v}")
    print("\n헤딩→데이터표 거리 분포:")
    for k, v in sorted(dist.items()):
        print(f"  {k:3d}칸 → {v:5d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
