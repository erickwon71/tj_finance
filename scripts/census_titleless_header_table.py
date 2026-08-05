"""
Census — "제목 자체가 아예 없는" 표(포시에스 BS `20171114002836` 패턴)가 활성기업
n_lines=0 필링들 중 몇 건에 더 있는지 실측한다.

패턴: 데이터 TABLE 이 `title_text_owned()`로 제목을 못 찾고, 표 자신의 첫 TR 도
재무제표명을 담고 있지 않다(= `census_merged_title_data_table.py` 의 병합표 패턴과도
다름) — 첫 TR 이 곧바로 헤더 행("과목"/"계정명" 등)이라 텍스트로 BS/IS 를 특정할
근거가 전혀 없다.

대상 모집단: `census_merged_title_data_table.py` 와 동일(활성기업, status=done,
n_lines=0). 읽기 전용 — DB 미변경.

실행:
    PYTHONPATH=. .venv/bin/python scripts/census_titleless_header_table.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.xml.dart_xml_parser import _parse_xml_file  # noqa: E402
from parser.xml.section_detector import table_has_amount_rows  # noqa: E402
from fin2.extract.statement_titles import title_text_owned, _STMT_NAME_ANY  # noqa: E402

_HEADER_FIRST_CELL = re.compile(r"^(과\s*목|계\s*정\s*과\s*목|계\s*정\s*명)$")


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
    """이 표의 첫 TR 이 (제목 없이) 곧바로 헤더행인가."""
    cells = first_row_cells(tbl)
    if not cells:
        return False
    first_cell = re.sub(r"\s+", "", cells[0])
    return bool(_HEADER_FIRST_CELL.match(cells[0].strip())) or first_cell in ("과목", "계정과목", "계정명")


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
    print(f"대상 모집단: {len(rows)}건 (active corps, status=done, n_lines=0)")

    matched = []
    no_file = []
    parse_fail = []
    checked = 0

    for rcept_no, corp_code, file_path in rows:
        if not file_path or not Path(file_path).exists():
            no_file.append(rcept_no)
            continue
        root = _parse_xml_file(Path(file_path))
        if root is None:
            parse_fail.append(rcept_no)
            continue
        checked += 1

        hit_tables = 0
        for tbl in root.iter("TABLE"):
            if not table_has_amount_rows(tbl):
                continue
            if title_text_owned(tbl):
                continue  # 정상적으로 제목을 찾음 — 이 결함 아님
            if is_titleless_header_start(tbl):
                hit_tables += 1
        if hit_tables:
            matched.append((rcept_no, corp_code, hit_tables, file_path))

    print(f"\n파싱 성공: {checked}건 (파일없음 {len(no_file)}, 파싱실패 {len(parse_fail)})")
    print(f"제목 자체가 없는 표 패턴 매치: {len(matched)}건")
    for rcept_no, corp_code, n, file_path in matched:
        print(f"  {rcept_no}  corp={corp_code}  hit_tables={n}  {file_path}")


if __name__ == "__main__":
    main()
