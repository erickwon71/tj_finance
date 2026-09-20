"""행 단위 결측 탐지(`fin2/audit/row_coverage.py`) 회귀 테스트.

이 감사의 목적은 "적재 결과에서는 원리적으로 안 보이는 것을 원문 쪽에서 본다"이므로,
테스트도 ① 라벨 정규화(거짓양성의 주원인)와 ② 실제 결함 검출을 같이 본다.

실행: pytest fin2/tests/test_row_coverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit import row_coverage                            # noqa: E402
from fin2.audit.layer2_selfcheck import FAIL                   # noqa: E402
from fin2.extract.report_lines import extract_report_lines     # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
# 당기 공란 + 전기에만 값이 있는 행을 가진 필링 — **결함이 아니므로 적출되면 안 된다**.
#  · 고려아연 `['장기파생상품금융부채', '', '1,928,974,207']` (당기엔 그 부채 없음)
#  · NAVER `['유동매도가능금융자산 (주5,16)', '', '79,435,727,110']`
#    (IFRS 9 이 2018-01-01 시행돼 그 계정이 당기부터 소멸)
# 초판이 이 둘을 결함으로 신고했던 회귀를 막는 가드다.
_KOREAZINC_2022H1 = _ROOT / "raw_report/KOSPI/00102858_고려아연/half/2022/20220816001335.xml"
_NAVER_2018Q1 = _ROOT / "raw_report/KOSPI/00266961_NAVER/quarter/2018/20180515002682.xml"
# 분기 CF 의 '조정사항' 세부행이 연간 열에만 값을 싣는 필링 — 거짓 발화 113건이 나던 것.
_NAVER_2015Q1 = _ROOT / "raw_report/KOSPI/00266961_NAVER/quarter/2015/20150515001873.xml"
# R149(EPS '2,564원' 미파싱)를 되살리면 EPS 행이 결측되는 필링 — 검출력 가드.
_SHINHAN_2022Q1 = _ROOT / "raw_report/KOSPI/00382199_신한지주/quarter/2022/20220516002487.xml"


def test_note_reference_is_normalized_away():
    """원문 '유동매도가능금융자산 (주5,16)' ↔ 적재 '유동매도가능금융자산' 은 같은 행."""
    assert (row_coverage.normalize_label("유동매도가능금융자산 (주5,16)")
            == row_coverage.normalize_label("유동매도가능금융자산"))
    assert (row_coverage.normalize_label("현금및예치금(주석23,41)")
            == row_coverage.normalize_label("현금및예치금"))


def test_trailing_colon_is_normalized_away():
    assert row_coverage.normalize_label("총포괄손익:") == row_coverage.normalize_label("총포괄손익")


def test_composite_sce_label_matches_its_parts():
    """SCE 는 '부모>자식' 복합라벨로 저장된다(R134/R135) — 조각도 후보로 잡아야
    거짓양성이 안 난다."""
    keys = row_coverage.loaded_label_keys("총포괄손익>당기순이익(손실)")
    assert row_coverage.normalize_label("총포괄손익") in keys
    assert row_coverage.normalize_label("총포괄손익>당기순이익(손실)") in keys


def test_loose_number_test_does_not_reuse_parser_logic():
    """★핵심 — 파서가 못 읽는 '2,564원' 도 '숫자 칸'으로 인정해야 한다. 여기서
    `parse_amount()` 를 쓰면 파서의 맹점을 그대로 물려받아 R149 류를 영영 못 잡는다.
    반대로 기간 표기는 숫자 칸이 아니다."""
    assert row_coverage._LOOSE_NUM.match("2,564원")
    assert row_coverage._LOOSE_NUM.match("1,234천원")
    assert row_coverage._LOOSE_NUM.match("(1,234)")
    assert row_coverage._LOOSE_NUM.match("△282")
    assert not row_coverage._LOOSE_NUM.match("제22기")
    assert not row_coverage._LOOSE_NUM.match("2015년")
    assert not row_coverage._LOOSE_NUM.match("3개월")
    assert not row_coverage._LOOSE_NUM.match("-")


def test_reference_positions_come_from_rows_that_were_loaded():
    """★판정 기준을 **파서 자신의 결과**에서 가져온다 — 적재된 행들이 값을 놓은 물리
    위치만 '적재되는 열'로 인정한다.

    "표의 당기 열은 index N" 이라는 모델은 쓸 수 없다. DART 표는 값 사이에 빈 칸을
    끼워서 **같은 표 안에서도 행마다 당기 값의 위치가 다르다**.
    """
    rows = [["자산총계", "1,000", "900"],            # 적재됨 → 위치 1
            ["부채총계", "400", "350"],               # 적재됨 → 위치 1
            ["장기파생상품금융부채", "", "1,928"]]     # 미적재, 위치 2
    known = {row_coverage.normalize_label("자산총계"),
             row_coverage.normalize_label("부채총계")}
    assert row_coverage._loaded_value_positions(rows, known) == {1}

    spaced = [["Ⅶ. 총포괄이익", "", "1,406,564", "", "1,328,049"],   # 적재됨 → 위치 2
              ["기본 및 희석주당이익", "", "2,564원", "", "2,428원"]]  # 미적재, 위치 2
    known2 = {row_coverage.normalize_label("Ⅶ. 총포괄이익")}
    assert row_coverage._loaded_value_positions(spaced, known2) == {2}


def test_first_number_index_ignores_period_markers():
    assert row_coverage._first_number_index(["과 목", "제22기", "2,564"]) == 2
    assert row_coverage._first_number_index(["자산총계", "1,000", "900"]) == 1
    assert row_coverage._first_number_index(["구분", "", ""]) is None


def test_rows_whose_values_sit_in_non_loaded_columns_are_not_reported():
    """★적재 대상이 아닌 열에만 값이 있는 행은 결함이 아니다 — 초판들이 이걸 결함으로
    신고했던 회귀 가드.

    · 고려아연 `['장기파생상품금융부채', '', '1,928,974,207']` — 당기 공란, 전기에만 값
    · NAVER 2018Q1 — IFRS 9 시행으로 당기부터 소멸한 '매도가능금융자산'
    · NAVER 2015Q1 — 분기 CF 의 '조정사항' 세부행이 **연간 열에만** 값을 싣는다
      (분기보고서라 파서는 분기 열만 적재한다). 거짓 발화 113건이 나던 케이스.
    """
    for path, rcept, corp, fy, fp in (
            (_KOREAZINC_2022H1, "20220816001335", "00102858", 2022, "H1"),
            (_NAVER_2018Q1, "20180515002682", "00266961", 2018, "Q1"),
            (_NAVER_2015Q1, "20150515001873", "00266961", 2015, "Q1")):
        if not path.exists():
            continue
        lines = extract_report_lines(path, rcept_no=rcept, corp_code=corp,
                                     report_fiscal_year=fy, report_fiscal_period=fp)
        missing = row_coverage.find_missing_rows(path, lines)
        assert missing == [], [(m.label, m.amounts) for m in missing]


def test_detects_eps_row_loss_when_r149_is_disabled(monkeypatch):
    """검출력 가드 — R149 수정을 끄면(='2,564원' 미파싱 재현) EPS 행 결측을 적출한다.
    이 케이스가 없으면 "한 번도 안 울리는 경보"와 구분되지 않는다."""
    if not _SHINHAN_2022Q1.exists():
        return
    import re as _re

    import parser.common.amount_normalizer as amount_normalizer
    monkeypatch.setattr(amount_normalizer, "_CELL_OWN_WON_RE", _re.compile(r"(?!x)x"))

    lines = extract_report_lines(
        _SHINHAN_2022Q1, rcept_no="20220516002487", corp_code="00382199",
        report_fiscal_year=2022, report_fiscal_period="Q1")
    missing = row_coverage.find_missing_rows(_SHINHAN_2022Q1, lines)
    labels = {m.label for m in missing}
    assert any("주당" in x for x in labels), sorted(labels)
    assert row_coverage.check(_SHINHAN_2022Q1, lines).verdict == FAIL


def test_source_only_rows_are_written_into_the_review_csv():
    """★대조 방향 보강 — 결측행이 검토 CSV 의 데이터 블록에 '★원문만' 으로 실려야
    한다. 예비란 검산 한 줄로만 알리면 단방향 대조에서 그대로 지나친다."""
    from fin2.audit.row_coverage import MissingRow
    from fin2.extract.review_csv import HEADER, build_source_only_rows

    rows = build_source_only_rows([
        MissingRow(basis="separate", statement="IS",
                   label="기본 및 희석주당이익", amounts=("2,564원", "2,428원")),
    ])
    assert len(rows) == 1
    row = rows[0]
    assert len(row) == len(HEADER)
    assert "★원문만" in row[0] and "별도" in row[0]
    assert row[HEADER.index("항목명")] == "기본 및 희석주당이익"
    assert row[HEADER.index("금액")] == ""            # 적재된 금액이 없다는 게 요점
    assert "2,564원" in row[HEADER.index("원문값")]
    assert "fail" in row[HEADER.index("비고")]
    assert build_source_only_rows([]) == []
    assert build_source_only_rows(None) == []
