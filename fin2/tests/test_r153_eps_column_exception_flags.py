"""R153(2026-09-20) 회귀 테스트 — R116/R120 열선택 예외 플래그가 EPS 경로에 전달되지
않아 EPS 행이 **두 경로 사이 틈으로 증발**하던 결함.

일부 필링은 손익계산서 열이 [3개월|누적] 2단인데 **누적 칸을 통째로 비워둔다**. 그래서
R116 은 그런 Q1 필링을 예외목록(`_Q1_CUM_BLANK_USE_3M_RCEPTS`)에 두고 3개월 값을 누적으로
채택한다 — 본류(`_emit_section_lines`)는 그 플래그를 넘겨 정상 행을 싣는다.

그런데 `_emit_eps_lines` 는 같은 `select_by_header_columns()` 를 **플래그 없이** 불렀다.
EPS 행은 누적 칸이 공란이라 `pairs` 가 비어 `continue` 로 빠지고, 그 직후 본류의 EPS 위임
가드가 "EPS 처럼 보이면 무조건 건너뜀" 이라 본류도 싣지 않는다 → 행이 증발한다.

실측: 형지I&C 20150514004898(2015Q1) 연결·별도 IS 에서 기본/희석/계속영업 주당이익
4행이 전부 결측이었다(행 단위 결측 탐지기 전수 센서스 2,528개사에서 적출). 같은 목록의
나머지 필링도 같은 증상이었다.

R144 의 교훈("같은 판정을 두 경로가 각자 구현하면 갈린다")이 열 선택 **인자**에도
그대로 적용된다.

★2026-10-11(사용자 결정, R0-2): 누적 공란에 3개월 값을 싣는 것은 **빈칸 채움**이라 계층3 이다.
계층2(기본 추출 = 인쇄값)에는 그 행이 없고, 규칙을 켠 추출(`as_printed.forced("repaired")`)과
`layer3_cell_corrections` fill(`R154_q1_cum_fill`)에만 있다. 두 경로가 같은 플래그를 받는다는
R153 의 요지는 그대로 — 이제 둘 다 `_q1_cum_fill_on()` 하나를 묻는다.

실행: pytest fin2/tests/test_r153_eps_column_exception_flags.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fin2.extract.report_lines as report_lines                  # noqa: E402
from fin2.extract import as_printed as AP                         # noqa: E402
from fin2.extract.layer3_corrections import extract_xml_with_corrections  # noqa: E402
from fin2.extract.report_lines import extract_report_lines        # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_HYUNGJI_2015Q1 = (
    _ROOT / "raw_report/KOSDAQ/00142713_형지I&C/quarter/2015/20150514004898.xml")


_KW = dict(rcept_no="20150514004898", corp_code="00142713",
           report_fiscal_year=2015, report_fiscal_period="Q1")


def _repaired(path):
    """Rules-on extraction = what layer 3 reads through report_lines_l3."""
    with AP.forced("repaired"):
        return extract_report_lines(path, **_KW)


def _eps_rows(lines, basis):
    return {(l.label_raw, l.col_index): l.value_won for l in lines
            if l.statement == "IS" and l.basis == basis and "주당" in (l.label_raw or "")}


def test_exception_lists_are_still_wired_to_the_eps_path():
    """플래그를 넘기는 코드가 살아 있는지(상수 이름이 바뀌면 조용히 깨진다)."""
    src = (Path(report_lines.__file__)).read_text(encoding="utf-8")
    eps_fn = src.split("def _emit_eps_lines", 1)[1].split("\ndef ", 1)[0]
    assert "allow_three_month_as_cumulative=_q1_cum_fill_on(" in eps_fn
    assert "prefer_last_of_two_as_cumulative" in eps_fn
    flag_fn = src.split("def _q1_cum_fill_on", 1)[1].split("\ndef ", 1)[0]
    assert "_Q1_CUM_BLANK_USE_3M_RCEPTS" in flag_fn
    assert 'repair_on("R154_q1_cum_fill")' in flag_fn


def test_hyungji_2015q1_eps_rows_recovered():
    """누적 칸이 통째로 빈 Q1 필링에서 EPS 행이 3개월 값으로 복원된다(계층3 = 규칙 켬)."""
    if not _HYUNGJI_2015Q1.exists():
        return
    lines = _repaired(_HYUNGJI_2015Q1)

    con = _eps_rows(lines, "consolidated")
    assert con, "연결 EPS 행이 여전히 결측"
    # 원문: ['기본주당이익(손실) (주31)', '(7)', '', '4', ...] → 당기 -7 / 전기 4
    assert con[("기본주당이익(손실) (주31)", 0)] == -7
    assert con[("기본주당이익(손실) (주31)", 1)] == 4
    assert con[("계속영업기본주당이익(손실) (주31)", 0)] == -7
    assert con[("희석주당이익(손실) (주31)", 0)] == -7
    assert _eps_rows(lines, "separate"), "별도 EPS 행이 여전히 결측"


def test_normal_rows_unaffected():
    """가산적 수정 — 같은 표의 일반 손익 행은 그대로다(계층3 = 규칙 켬)."""
    if not _HYUNGJI_2015Q1.exists():
        return
    lines = _repaired(_HYUNGJI_2015Q1)
    rows = {l.label_raw: l.value_won for l in lines
            if l.statement == "IS" and l.basis == "consolidated" and l.col_index == 0}
    revenue = next(v for k, v in rows.items() if k.startswith("수익(매출액)"))
    assert revenue == 29_893_315_770


def test_layer2_keeps_the_blank_and_layer3_gets_r154_fills(monkeypatch):
    """R0-2 — 계층2 는 누적 공란 그대로(행 없음), 3개월 값은 R154 fill 보정으로만 간다."""
    if not _HYUNGJI_2015Q1.exists():
        return
    monkeypatch.delenv(AP.ENV, raising=False)
    lines, corrections = extract_xml_with_corrections(_HYUNGJI_2015Q1, include_notes=False, **_KW)
    assert not [l for l in lines if l.statement == "IS" and l.col_index == 0
                and "주당" in (l.label_raw or "")]
    fills = {(c["basis"], c["label_raw"]): c for c in corrections if c["statement"] == "IS"}
    eps = fills[("consolidated", "기본주당이익(손실) (주31)")]
    assert (eps["kind"], eps["rule"], eps["printed_value"], eps["corrected_value"]) == (
        "fill", "R154_q1_cum_fill", None, -7)
    assert eps["row_data"]                       # report_lines_l3 adds the whole row back
    assert all(c["rule"] == "R154_q1_cum_fill" and c["kind"] == "fill"
               for c in corrections if c["statement"] == "IS")
