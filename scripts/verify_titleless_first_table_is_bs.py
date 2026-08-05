"""
검증 — "제목 없는 표" 9건에서, 그 표가 "4. 재무제표"(또는 "2. 연결재무제표") 섹션의
**첫 번째** 금액표인지, 그리고 계정명이 BS 다운지(자산/부채/자본 vs 매출/비용) 확인한다.

사용자 가설: "4. 재무제표" 아래 첫 번째 표는 곧 재무상태표(BS)라고 이 서식을 쓰는 기업들이
암묵적으로 취급하고 있다 — 위치가 곧 제목 역할을 한다. census_titleless_header_table.py
의 매치 9건에 대해 이 가설이 실제로 성립하는지 원문 구조로 확인한다. 읽기 전용.

실행:
    PYTHONPATH=. .venv/bin/python scripts/verify_titleless_first_table_is_bs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.xml.dart_xml_parser import _parse_xml_file  # noqa: E402
from parser.xml.section_detector import table_has_amount_rows  # noqa: E402
from fin2.extract.statement_titles import title_text_owned  # noqa: E402

TARGETS = [
    "20171114002836", "20180515001992", "20190401004098", "20190403000131",
    "20190408000557", "20220323000895", "20240401001960", "20240401001990",
    "20240401002009",
]

_HEADER_FIRST_CELL = re.compile(r"^(과\s*목|계\s*정\s*과\s*목|계\s*정\s*명)$")
_FS_SECTION_TITLE = re.compile(r"재무제표$")  # "4. 재무제표" / "2. 연결재무제표" 등


def first_row_cells(tbl) -> list[str]:
    for tr in tbl.iter("TR"):
        cells = []
        for td in tr:
            tag = td.tag.upper() if isinstance(td.tag, str) else ""
            if tag in ("TD", "TE", "TH"):
                cells.append(" ".join("".join(td.itertext()).split()))
        return cells
    return []


def is_titleless_header_start(tbl) -> bool:
    cells = first_row_cells(tbl)
    if not cells:
        return False
    first_cell = re.sub(r"\s+", "", cells[0])
    return bool(_HEADER_FIRST_CELL.match(cells[0].strip())) or first_cell in ("과목", "계정과목", "계정명")


def account_name_cells(tbl, n=6) -> list[str]:
    """첫 열(계정명으로 추정) 텍스트를 앞에서 n개 모은다(헤더 행 제외 시도)."""
    out = []
    for tr in tbl.iter("TR"):
        cells = [td for td in tr if (td.tag.upper() if isinstance(td.tag, str) else "") in ("TD", "TE", "TH")]
        if not cells:
            continue
        txt = " ".join("".join(cells[0].itertext()).split())
        if txt:
            out.append(txt)
        if len(out) >= n:
            break
    return out


def enclosing_section_title(tbl) -> str:
    """이 표를 담은 가장 가까운 SECTION-2/SECTION-1 의 TITLE 텍스트."""
    el = tbl.getparent()
    while el is not None:
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            for child in el:
                ctag = child.tag.upper() if isinstance(child.tag, str) else ""
                if ctag == "TITLE":
                    return " ".join("".join(child.itertext()).split())
            break
        el = el.getparent()
    return ""


def main() -> None:
    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor()
    cur.execute("""
        SELECT rcept_no, file_path FROM download_tasks WHERE rcept_no = ANY(%s)
    """, (TARGETS,))
    path_of = dict(cur.fetchall())

    for rcept_no in TARGETS:
        file_path = path_of.get(rcept_no)
        print(f"\n{'='*90}\n{rcept_no}  {file_path}")
        if not file_path or not Path(file_path).exists():
            print("  파일 없음")
            continue
        root = _parse_xml_file(Path(file_path))
        if root is None:
            print("  파싱 실패")
            continue

        # 섹션별로 금액표를 순서대로 모아, 몇 번째 표인지 계산.
        section_table_count: dict[str, int] = {}
        for tbl in root.iter("TABLE"):
            if not table_has_amount_rows(tbl):
                continue
            sec = enclosing_section_title(tbl)
            section_table_count[sec] = section_table_count.get(sec, 0) + 1
            position = section_table_count[sec]

            if title_text_owned(tbl):
                continue  # 정상 분류됨 — 이 결함 아님
            if not is_titleless_header_start(tbl):
                continue

            names = account_name_cells(tbl)
            print(f"  섹션='{sec}'  섹션내_표순번={position}  계정명샘플={names}")


if __name__ == "__main__":
    main()
