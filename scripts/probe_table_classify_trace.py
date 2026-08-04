"""본문 섹션 표 하나하나에 대해 **분류기가 무엇을 보고 무엇으로 판정했는지** 추적한다.

`_detect_body_statement_tables` 는 표제를 두 경로로 읽는다:
  ① `title_text(tbl)`               = 직전 형제 텍스트
  ② `title_text_for_classify(tbl)`  = 메타(단위/기간)줄을 건너뛴 표제
어느 쪽도 못 읽으면 그 표는 후보에서 사라진다(거짓 부재). 이 스크립트는 표별로
①②의 실제 입력값과 판정, 부모 태그, 단위 획득 여부를 나란히 찍어 원인을 특정한다.

사용:
    python scripts/probe_table_classify_trace.py --rcept 20171114002715
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    assign_tables_to_dart_sections, SEC_CONSOL_FS, SEC_SEP_FS, table_direct_rows,
)
from fin2.extract.statement_titles import (
    title_text, title_text_for_classify, classify_statement_in_body_section,
)
from fin2.extract.text import (
    _detect_body_statement_tables, _detect_fin_type, _table_has_data_rows,
    declared_unit, declaration_text,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept", required=True)
    args = ap.parse_args()

    with get_session() as s:
        fpth = s.execute(text("SELECT file_path FROM download_tasks WHERE rcept_no=:r"),
                         {"r": args.rcept}).scalar()
    root = _parse_xml_file(Path(fpth))
    sec_tables = assign_tables_to_dart_sections(root)

    for sec_kind in (SEC_CONSOL_FS, SEC_SEP_FS):
        tbls = sec_tables.get(sec_kind, [])
        if not tbls:
            continue
        print(f"\n=== 섹션 '{sec_kind}' — 표 {len(tbls)}개 ===")
        for i, tbl in enumerate(tbls):
            parent = tbl.getparent()
            ptag = parent.tag if parent is not None and isinstance(parent.tag, str) else "?"
            prev = tbl.getprevious()
            prevtag = (prev.tag if prev is not None and isinstance(prev.tag, str) else "None")
            t1 = title_text(tbl)
            t2 = title_text_for_classify(tbl)
            c1 = classify_statement_in_body_section(t1, include_sce=True)
            c2 = classify_statement_in_body_section(t2, include_sce=True)
            print(f"\n [{i}] parent=<{ptag}> prev=<{prevtag}> "
                  f"rows={len(table_direct_rows(tbl))} data={bool(_table_has_data_rows(tbl))}")
            print(f"     ① title_text          = {t1[:80]!r} → {c1}")
            print(f"     ② title_text_forclass = {t2[:80]!r} → {c2}")
            print(f"     declared_unit={declared_unit(tbl)}  decl_text={str(declaration_text(tbl))[:60]!r}")
            own = " ".join("".join(tbl.itertext()).split())[:70]
            print(f"     표 자신 첫머리        = {own!r}")

    groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
    print("\n=== 최종 감지 결과 ===")
    for code, v in sorted(groups.items()):
        for tbl, unit, kind in v:
            head = " ".join("".join(tbl.itertext()).split())[:50]
            print(f"  {code:6s} unit={unit} rows={len(table_direct_rows(tbl))} {head!r}")
    if not groups:
        print("  (없음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
