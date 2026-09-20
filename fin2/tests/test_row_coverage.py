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


def test_current_period_index_picks_the_modal_column():
    """당기 열은 '행들이 실제로 값을 넣은 위치의 최빈값'으로 정한다 — 값 사이에 빈 칸이
    끼는 서식(신한지주 EPS 표)에서도 맞아야 한다."""
    rows = [["자산총계", "1,000", "900"], ["부채총계", "400", "350"],
            ["장기파생상품금융부채", "", "1,928"]]
    assert row_coverage._current_period_index(rows) == 1
    spaced = [["Ⅶ. 총포괄이익", "", "1,406,564", "", "1,328,049"],
              ["Ⅳ. 법인세비용", "", "12,345", "", "11,000"]]
    assert row_coverage._current_period_index(spaced) == 2


def test_row_with_no_current_period_value_is_not_reported():
    """★당기가 공란이고 전기에만 값이 있는 행은 적재될 것이 없다 — 결함이 아니다.
    초판이 이걸 결함으로 신고했던 회귀 가드(고려아연 '장기파생상품금융부채',
    NAVER IFRS 9 로 소멸한 '매도가능금융자산')."""
    for path, rcept, corp, fy, fp in (
            (_KOREAZINC_2022H1, "20220816001335", "00102858", 2022, "H1"),
            (_NAVER_2018Q1, "20180515002682", "00266961", 2018, "Q1")):
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
