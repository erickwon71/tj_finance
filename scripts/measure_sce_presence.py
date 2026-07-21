"""자본변동표(SCE) 미추출 실태 측정 — 계층2 전량적재 전 스키마 확정용.

배경: `fin2/extract/text.py:49` `_SECTION_META` 는 BS/IS/CF × 연결/별도 **6 섹션만** 정의한다.
`parser/xml/section_detector.py:68` `_BOUNDARY_EXTRA=[["자본변동표"]]` 는 자본변동표를 **경계
표시용으로만** 쓰고(IS_C 가 SCE 의 순이익 행을 흡수하는 오염 방지) 추출하지는 않는다.
즉 K-IFRS 기본재무제표 5종 중 자본변동표가 통째로 버려지고 있다.
(`collector/models.py:354` 주석은 'BS/IS/CF/SCE/note' 라고 적혀 있으나 SCE 는 생성된 적 없음.)

이 스크립트는 원문 XML 에서 자본변동표 제목과 그 뒤 표를 직접 세어, 놓치고 있는 분량을
정량화한다. **추출기를 고치지 않고 원문만 스캔**한다(측정 목적).

사용:
    python scripts/measure_sce_presence.py --sample 300
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import _parse_xml_file, _table_has_data_rows

_SCE_TITLE = "자본변동표"


def _titles_and_tables(root):
    """문서 순서대로 (kind, node) 방출 — kind='title'|'table'. 제목 뒤 표를 귀속시키기 위함."""
    for el in root.iter():
        tag = (el.tag or "").upper()
        if tag in ("TITLE", "P"):
            txt = " ".join("".join(el.itertext()).split())
            if txt and len(txt) <= 40:
                yield "title", txt
        elif tag == "TABLE":
            yield "table", el


def _scan(file_path: str) -> tuple[int, int, int]:
    """반환 (자본변동표 제목 수, 그 뒤 데이터표 수, 그 표들의 TR 합)."""
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return 0, 0, 0
    n_title = n_table = n_tr = 0
    armed = False
    for kind, node in _titles_and_tables(root):
        if kind == "title":
            if _SCE_TITLE in node.replace(" ", ""):
                armed = True
                n_title += 1
            elif any(k in node.replace(" ", "") for k in
                     ("재무상태표", "손익계산서", "현금흐름표", "주석", "대차대조표")):
                armed = False        # 다른 재무제표 제목 → SCE 구간 종료
        elif kind == "table" and armed:
            try:
                if _table_has_data_rows(node):
                    n_table += 1
                    n_tr += len(node.findall(".//TR"))
            except Exception:
                pass
    return n_title, n_table, n_tr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300)
    args = ap.parse_args()

    sql = """SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year
             FROM download_tasks dt JOIN filings f USING(rcept_no)
             WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
               AND f.fiscal_period='FY' AND f.report_nm NOT LIKE '%정정%'"""
    with get_session() as session:
        rows = session.execute(text(sql)).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)

    n_reports = n_with_sce = 0
    title_dist = Counter()
    tot_tables = tot_tr = 0
    for r in rows:
        if not Path(r.file_path).exists():
            continue
        try:
            n_title, n_table, n_tr = _scan(r.file_path)
        except Exception:
            continue
        n_reports += 1
        title_dist[n_title] += 1
        if n_title:
            n_with_sce += 1
            tot_tables += n_table
            tot_tr += n_tr

    print(f"\n=== 자본변동표(SCE) 미추출 실태 ===")
    print(f"보고서 {n_reports}건 (원문 XML 직접 스캔)\n")
    print(f"[1] 자본변동표 제목이 있는 보고서   {n_with_sce:,} / {n_reports:,} "
          f"({100*n_with_sce/max(n_reports,1):.1f}%)")
    print(f"[2] 제목 개수 분포(연결+별도면 2)")
    for k in sorted(title_dist):
        print(f"      제목 {k}개: {title_dist[k]:5,} 보고서")
    print(f"\n[3] 버려지고 있는 데이터표      {tot_tables:,} 표")
    print(f"[4] 버려지고 있는 표 행(TR)      {tot_tr:,} 행")
    if n_with_sce:
        print(f"\n    보고서당 평균 {tot_tables/n_with_sce:.1f} 표 / {tot_tr/n_with_sce:.0f} 행")


if __name__ == "__main__":
    main()
