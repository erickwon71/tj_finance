"""
Census — "제목+데이터 병합 표" 구조 결함(특수건설 20151116001903 패턴)이
활성기업 n_lines=0(적재공백) 필링들 중 몇 건에 더 있는지 실측한다.

패턴: BS/IS 데이터 TABLE 이 별도 제목표(TABLE-GROUP 의 첫 TABLE, 또는 직전 형제)를
갖지 않고, 자기 자신의 첫 TR 에 재무제표명("재무상태표"/"손익계산서" 등)을 담고 있다
(그 다음 TR 들이 기간·회사명·단위·계정데이터). `title_text_owned()`(직전 형제 기반)는
이런 표에서 표제를 못 찾아 stmt=None → BS/IS 분류 자체가 실패한다(핸드오프 §6 참고).

대상 모집단: report_line_load_progress WHERE status='done' AND n_lines=0,
활성기업(corporations.is_active) 만. 읽기 전용 — DB 미변경.

실행:
    PYTHONPATH=. .venv/bin/python scripts/census_merged_title_data_table.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.xml.dart_xml_parser import _parse_xml_file  # noqa: E402
from parser.xml.section_detector import table_has_amount_rows  # noqa: E402
from fin2.extract.statement_titles import (  # noqa: E402
    title_text_owned,
    _STMT_NAME_ANY,
)


def first_row_text(tbl) -> str:
    """TABLE 의 첫 TR 텍스트(공백 제거 전, 원문 그대로)."""
    for tr in tbl.iter("TR"):
        txt = " ".join("".join(tr.itertext()).split())
        return txt
    return ""


def has_merged_title_row(tbl) -> bool:
    """이 표의 첫 TR 이 재무제표명 하나만 담고 있는가(제목+데이터 병합 표의 신호)."""
    txt = first_row_text(tbl)
    if not txt:
        return False
    compact = re.sub(r"\s+", "", txt)
    # 첫 행이 재무제표명 '단독'이어야 한다(길이가 짧아야 — 계정데이터가 섞이면 배제).
    return bool(_STMT_NAME_ANY.fullmatch(compact)) or (
        bool(_STMT_NAME_ANY.search(compact)) and len(compact) <= 12
    )


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

        hit = False
        for tbl in root.iter("TABLE"):
            if not table_has_amount_rows(tbl):
                continue
            if title_text_owned(tbl):
                continue  # 정상적으로 제목을 찾음 — 이 결함 아님
            if has_merged_title_row(tbl):
                hit = True
                break
        if hit:
            matched.append((rcept_no, corp_code, file_path))

    print(f"\n파싱 성공: {checked}건 (파일없음 {len(no_file)}, 파싱실패 {len(parse_fail)})")
    print(f"제목+데이터 병합 표 패턴 매치: {len(matched)}건")
    for rcept_no, corp_code, file_path in matched:
        print(f"  {rcept_no}  corp={corp_code}  {file_path}")

    if no_file:
        print(f"\n파일 없음(경로 문제, 별도 확인 필요): {no_file}")
    if parse_fail:
        print(f"\nXML 파싱 실패(★기존 '파싱 자체 실패 9건' 트랙과 겹칠 가능성): {parse_fail}")


if __name__ == "__main__":
    main()
