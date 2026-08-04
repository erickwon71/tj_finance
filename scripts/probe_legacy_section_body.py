"""구형 레이아웃 `XI. 재무제표 등` **내부** 요소 시퀀스를 덤프한다.

`probe_legacy_layout_gap.py` 가 "본문섹션(2.연결재무제표/4.재무제표)이 아예 없다"까지
확정했다. 이 스크립트는 그 다음 질문에 답한다 — **재무제표 표제는 어떤 요소로 있고,
데이터표는 그 사이 어디에 있는가?**

문서 순서 pass 로 `재무제표등` 섹션 진입 후 다음 섹션 표제 전까지의 요소를
(태그, 텍스트앞부분, 데이터행수) 로 찍는다. 추측 없이 원문 그대로 본다(R9).

사용:
    python scripts/probe_legacy_section_body.py --rcept 20141128001023
    python scripts/probe_legacy_section_body.py --rcept 20141128001023 --section 재무에관한사항
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
    classify_dart_section, normalize_dart_section_title, table_direct_rows,
)
from fin2.extract.text import _table_has_data_rows, declared_unit, title_text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcept", required=True)
    ap.add_argument("--section", default="재무제표등",
                    help="정규화된 섹션명(기본 재무제표등)")
    ap.add_argument("--limit", type=int, default=120)
    args = ap.parse_args()

    with get_session() as s:
        fp = s.execute(text("SELECT file_path FROM download_tasks WHERE rcept_no=:r"),
                       {"r": args.rcept}).scalar()
    if not fp or not Path(fp).exists():
        print(f"원문 없음: {fp}")
        return 2

    root = _parse_xml_file(Path(fp))
    inside = False
    shown = 0

    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            t = el.find("TITLE")
            if t is not None:
                raw = " ".join("".join(t.itertext()).split())
                norm = normalize_dart_section_title(raw)
                if inside and norm != args.section:
                    print(f"\n=== 섹션 종료 → {raw}")
                    break
                if norm == args.section:
                    inside = True
                    print(f"=== 섹션 진입: {raw} (classify={classify_dart_section(raw)})\n")
            continue
        if not inside or shown >= args.limit:
            continue

        # 표 안쪽 <P>(셀 텍스트)는 구조가 아니다 — 표 자신만 본다.
        anc, in_table = el.getparent(), False
        while anc is not None:
            if isinstance(anc.tag, str) and anc.tag.upper() == "TABLE":
                in_table = True
                break
            anc = anc.getparent()
        if in_table:
            continue

        txt = " ".join("".join(el.itertext()).split())
        if tag == "TABLE":
            n_direct = len(table_direct_rows(el))
            print(f"[{shown:3d}] <TABLE> direct_rows={n_direct} "
                  f"has_data={bool(_table_has_data_rows(el))} unit={declared_unit(el)}")
            print(f"       title_text={title_text(el)[:100]!r}")
            print(f"       first={txt[:120]!r}")
            shown += 1
        elif tag in ("P", "TITLE") and txt:
            print(f"[{shown:3d}] <{tag}> {txt[:140]!r}")
            shown += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
