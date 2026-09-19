"""
R85 회귀 테스트 — `_emit_eps_lines`가 H1/Q3 IS 표의 2단[3개월|누적] 헤더를
인지해 '누적' 컬럼을 선택하는지 확인한다.

배경: 삼성전자 2025H1(rcpNo=20250814003156) 원문대조로 발견 — 수정 전에는
[당기3개월,당기누적,전기3개월,전기누적] 4열 표에서 EPS 행이 파싱 순서 앞
3개를 그냥 [당기,전기,전전기]로 라벨링해, "당기" 자리에 당기3개월(비누적)
값이 들어갔다(진짜 당기누적 값은 버려짐). 자세한 내용은
docs/PARSING_RULES.md R85.

실행: pytest fin2/tests/test_eps_interim_cum_map_r85.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.report_lines import _emit_section_lines  # noqa: E402

_RCEPT = "TESTR85-0000000001"


def _make_h1_eps_table(label: str, amounts4: list[str]) -> etree._Element:
    """[당기3개월,당기누적,전기3개월,전기누적] 2단 헤더 + EPS 데이터 행 1개.

    실제 원문(삼성전자 20250814003156) 헤더 패턴 "3개월 누적 3개월 누적"을
    그대로 재현 — `_interim_cumulative_cols()`가 실서비스에서 보는 것과
    같은 토큰 배치."""
    header_cells = "".join(f"<TD>{h}</TD>" for h in ["", "3개월", "누적", "3개월", "누적"])
    data_cells = "".join(f"<TD>{a}</TD>" for a in amounts4)
    xml = f"<TABLE><TR>{header_cells}</TR><TR><TD>{label}</TD>{data_cells}</TR></TABLE>"
    return etree.fromstring(xml)


def _run_h1(table, *, unit: int = 1000000):
    lines: list = []
    _emit_section_lines(
        "IS_S", [(table, unit, "(단위 : 백만원)")],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2025, report_fiscal_period="H1",
    )
    return lines


def test_h1_eps_picks_cumulative_column_not_3month():
    """실측 재현 — 원문 [411.0, 1,360.0, 1,045.0, 2,479.0]
    (당기3개월,당기누적,전기3개월,전기누적)에서 당기=1,360(누적), 전기=2,479(누적)이어야
    한다(수정 전엔 당기=411, 전기=1,045 로 3개월 값이 잘못 저장됐음)."""
    table = _make_h1_eps_table(
        "기본주당이익(손실) (단위 : 원)", ["411", "1,360", "1,045", "2,479"])

    lines = _run_h1(table)

    eps_rows = {l.col_index: l.value_won for l in lines
                if l.source_ref.startswith("eps/") and l.label_raw.startswith("기본주당이익")}
    assert eps_rows == {0: 1_360, 1: 2_479}, eps_rows
    # is_cumulative 메타데이터가 실제 선택된 값(누적)과 이제 일치해야 한다.
    assert all(l.is_cumulative for l in lines if l.source_ref.startswith("eps/"))


def test_fy_eps_unaffected_no_2tier_header():
    """cum_map 없는(2단 헤더 미검출) FY EPS 행 — 기존 동작(파싱 순서 앞 3개) 그대로."""
    xml = "<TABLE><TR><TD>기본주당이익(손실) (단위 : 원)</TD><TD>500</TD><TD>450</TD></TR></TABLE>"
    table = etree.fromstring(xml)

    lines: list = []
    _emit_section_lines(
        "IS_S", [(table, 1000, None)],
        emit=lines.append, corp_code="TESTCORP", rcept_no=_RCEPT,
        report_fiscal_year=2024, report_fiscal_period="FY",
    )

    eps_rows = {l.col_index: l.value_won for l in lines if l.source_ref.startswith("eps/")}
    assert eps_rows == {0: 500, 1: 450}, eps_rows
    assert all(not l.is_cumulative for l in lines if l.source_ref.startswith("eps/"))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
