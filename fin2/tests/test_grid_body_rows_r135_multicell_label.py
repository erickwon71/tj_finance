"""`fin2/extract/report_lines.py::_grid_body_rows` R135 회귀 테스트 (합성 XML, DB/NAS 비의존).

원익피앤이 20161128000288 SCE(자본변동표, 연결) 실측 축소판 — 라벨 영역(grid_col < offset)
안에 물리 셀이 둘(ROWSPAN 카테고리 헤더 "자본의 변동" + 그 아래 구체 항목명 "배당금지급")인
행에서, 기존 코드는 `physical[0]`만 라벨로 써 두 번째 라벨 셀이 통째로 유실됐다(값 자체는
원래도 정확 — offset 정의상 라벨 영역엔 금액이 나온 적이 없어 값 유실은 아니었음). R135는
라벨 영역의 물리 셀을 전부 ">"로 이어붙인다(헤더 다단 조인 `_label_dict_from_header`와 같은
관례).

실행: pytest fin2/tests/test_grid_body_rows_r135_multicell_label.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from fin2.extract.report_lines import _grid_body_rows, _grid_header_split  # noqa: E402

# 원익피앤이 SCE 연결 축소판 — 열: [라벨(COLSPAN=3)] 자본금 | 자본잉여금 | 기타자본 |
# 기타포괄손익누계액 | 이익잉여금 | 지배지분합계 | 비지배지분 | 자본합계
_WONIK_SCE_XML = """<TABLE>
<TR>
  <TD COLSPAN="3">구분</TD>
  <TD>자본금</TD><TD>자본잉여금</TD><TD>기타자본</TD><TD>기타포괄손익누계액</TD>
  <TD>이익잉여금</TD><TD>지배지분합계</TD><TD>비지배지분</TD><TD>자본합계</TD>
</TR>
<TR>
  <TD COLSPAN="3">2016.01.01 (기초자본)</TD>
  <TD>2,450,000,000</TD><TD>8,899,355,197</TD><TD>0</TD><TD>0</TD>
  <TD>10,567,316,182</TD><TD>21,916,671,379</TD><TD>0</TD><TD>21,916,671,379</TD>
</TR>
<TR>
  <TD ROWSPAN="3">자본의 변동</TD>
  <TD COLSPAN="2">배당금지급</TD>
  <TD></TD><TD></TD><TD></TD><TD></TD>
  <TD>490,000,000</TD><TD>490,000,000</TD><TD></TD><TD>490,000,000</TD>
</TR>
<TR>
  <TD>포괄손익</TD><TD>당기순이익</TD>
  <TD></TD><TD></TD><TD></TD><TD></TD>
  <TD>1,191,695,518</TD><TD>1,191,695,518</TD><TD></TD><TD>1,191,695,518</TD>
</TR>
<TR>
  <TD COLSPAN="2">해외사업환산손익</TD>
  <TD></TD><TD></TD><TD>130,434,101</TD><TD></TD>
  <TD></TD><TD>130,434,101</TD><TD></TD><TD>130,434,101</TD>
</TR>
<TR>
  <TD COLSPAN="3">2016.09.30 (기말자본)</TD>
  <TD>2,450,000,000</TD><TD>8,899,355,197</TD><TD>0</TD><TD>130,434,101</TD>
  <TD>11,269,011,700</TD><TD>22,487,932,796</TD><TD>0</TD><TD>22,487,932,796</TD>
</TR>
</TABLE>"""


def _extract(xml: str):
    table = etree.fromstring(xml)
    grid_rows, n_header, offset, width = _grid_header_split(table)
    return _grid_body_rows(table, grid_rows, n_header, offset,
                            allow_date_label=True, keep_header_rows=False)


def test_multicell_label_region_joined_with_gt():
    """라벨 영역에 물리 셀이 둘인 행은 ">"로 이어붙여 구체 항목명을 보존한다(R135)."""
    rows = _extract(_WONIK_SCE_XML)
    labels = [r.account_name for r in rows]
    assert labels == [
        "2016.01.01 (기초자본)",
        "자본의 변동>배당금지급",
        "포괄손익>당기순이익",
        "해외사업환산손익",
        "2016.09.30 (기말자본)",
    ]


def test_multicell_label_region_values_unaffected():
    """라벨 조인은 값(amounts)에 영향을 주지 않는다 — offset 정의상 라벨 영역엔 애초에
    금액이 없었다(값 유실이 아니라 라벨 텍스트만 불완전했던 문제)."""
    rows = _extract(_WONIK_SCE_XML)
    dividend_row = next(r for r in rows if r.account_name == "자본의 변동>배당금지급")
    # 열: 자본금0 자본잉여금1 기타자본2 기타포괄손익누계액3 이익잉여금4 지배지분합계5 비지배지분6 자본합계7
    assert dividend_row.amounts[4] == 490_000_000
    assert dividend_row.amounts[5] == 490_000_000
    assert dividend_row.amounts[7] == 490_000_000


def test_single_label_cell_rows_unchanged():
    """라벨 영역 물리 셀이 하나뿐인 행(대다수)은 기존과 동일하게 동작한다(회귀 없음)."""
    rows = _extract(_WONIK_SCE_XML)
    assert rows[0].account_name == "2016.01.01 (기초자본)"
    assert rows[-1].account_name == "2016.09.30 (기말자본)"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
