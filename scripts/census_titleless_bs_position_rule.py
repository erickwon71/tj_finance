"""
census_titleless_header_table.py 의 9건 오검출을 좁힌 최종 규칙 — 포시에스 BS
(20171114002836) 패턴에 실제로 해당하는 표만 남긴다. 사용자 확정 조건(2026-08-05):

  1. 표가 "N. 재무제표"/"N. 연결재무제표" SECTION-2 의 **첫 번째** 금액표다(위치).
  2. `title_text_owned()`로 제목을 못 찾는다(현재 스킵되는 표).
  3. 표 자신의 첫 TR 이 헤더행("과목"/"계정명" 등)으로 곧바로 시작한다(제목 없음).
  4. 헤더 다음 데이터 행의 첫 계정명이 "자산"이다(BS 시작 신호 — 계정명 근거).

넷 다 만족해야 BS 로 판단한다(주석/CF/IS 표가 "과목" 관례만 같이 써서 걸리는 오검출을
① 위치 ④ 계정명 조건으로 배제).

대상 모집단: 활성기업 status=done, n_lines=0(census_merged_title_data_table.py 와 동일).
읽기 전용.

실행:
    PYTHONPATH=. .venv/bin/python scripts/census_titleless_bs_position_rule.py
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

_HEADER_FIRST_CELL = re.compile(r"^(과\s*목|계\s*정\s*과\s*목|계\s*정\s*명)$")
_FS_SECTION_TITLE = re.compile(r"재무제표$")


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


_PERIOD_ROW = re.compile(r"^\d{4}[-.]\d{1,2}([-.]\d{1,2})?$|^제\s*\d+\s*\(?[당전]?\)?기|^\d+\s*기")


def first_account_label_after_header(tbl) -> str:
    """헤더행(들) 다음 첫 계정명 후보.

    ★ "과목" 헤더 셀은 종종 `ROWSPAN=2`(과목/금액 2단 헤더)를 써서, 그 다음 TR 은
    1열이 아예 없다(구조상 TR 의 첫 TD 가 이미 2열 값이 된다) — 그 행의 "첫 TD" 를
    그대로 계정명으로 읽으면 날짜/기간값을 계정명으로 오인한다(실측: 포시에스
    "2017-09-30"). 기간·날짜 패턴이면 계정명이 아니라 건너뛴다.
    """
    seen_header = False
    for tr in tbl.iter("TR"):
        cells = [td for td in tr if (td.tag.upper() if isinstance(td.tag, str) else "") in ("TD", "TE", "TH")]
        if not cells:
            continue
        txt = " ".join("".join(cells[0].itertext()).split())
        compact = re.sub(r"\s+", "", txt)
        if not seen_header:
            if compact in ("과목", "계정과목", "계정명"):
                seen_header = True
            continue
        if not compact or _PERIOD_ROW.match(compact):
            continue  # 빈 라벨행 또는 기간/날짜행(ROWSPAN 으로 밀린 값) — 계정명 아님
        return compact
    return ""


def enclosing_section_title(tbl) -> str:
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
        SELECT p.rcept_no, p.corp_code, d.file_path
        FROM report_line_load_progress p
        JOIN corporations c ON c.corp_code = p.corp_code
        JOIN download_tasks d ON d.rcept_no = p.rcept_no
        WHERE p.status = 'done' AND p.n_lines = 0 AND c.is_active = true
        ORDER BY p.rcept_no
    """)
    rows = cur.fetchall()
    print(f"대상 모집단: {len(rows)}건")

    matched = []
    checked = 0

    for rcept_no, corp_code, file_path in rows:
        if not file_path or not Path(file_path).exists():
            continue
        root = _parse_xml_file(Path(file_path))
        if root is None:
            continue
        checked += 1

        section_table_count: dict[str, int] = {}
        for tbl in root.iter("TABLE"):
            if not table_has_amount_rows(tbl):
                continue
            sec = enclosing_section_title(tbl)
            section_table_count[sec] = section_table_count.get(sec, 0) + 1
            position = section_table_count[sec]

            if not _FS_SECTION_TITLE.search(sec):
                continue
            if position != 1:
                continue
            if title_text_owned(tbl):
                continue
            if not is_titleless_header_start(tbl):
                continue
            label = first_account_label_after_header(tbl)
            if label != "자산":
                continue

            matched.append((rcept_no, corp_code, sec, file_path))

    print(f"파싱 성공: {checked}건")
    print(f"최종 규칙(위치=1번째+제목없음+헤더시작+계정명='자산') 매치: {len(matched)}건")
    for rcept_no, corp_code, sec, file_path in matched:
        print(f"  {rcept_no}  corp={corp_code}  섹션='{sec}'  {file_path}")


if __name__ == "__main__":
    main()
