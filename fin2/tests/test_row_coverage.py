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
# 원문 [연결]·[별도] BS 에 '장기파생상품금융부채'(금액칸 1개)가 있는데 적재되지 않는다.
# ★이건 **현재 살아 있는 결함**을 고정한 픽스처다 — 그 결함을 고치면 이 테스트가
#   깨지는 게 정상이고, 그때 "이제 안 잡힌다"로 바꿔 달아야 한다.
_KOREAZINC_2022H1 = _ROOT / "raw_report/KOSPI/00102858_고려아연/half/2022/20220816001335.xml"


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


def test_detects_a_real_row_loss():
    """고려아연 2022H1 — 원문 BS 의 '장기파생상품금융부채'(금액칸 1개)가 적재되지
    않는 실제 결함을 잡아낸다."""
    if not _KOREAZINC_2022H1.exists():
        return
    lines = extract_report_lines(
        _KOREAZINC_2022H1, rcept_no="20220816001335", corp_code="00102858",
        report_fiscal_year=2022, report_fiscal_period="H1")
    missing = row_coverage.find_missing_rows(_KOREAZINC_2022H1, lines)
    labels = {m.label for m in missing}
    assert any("장기파생상품금융부채" in x for x in labels), sorted(labels)
    assert row_coverage.check(_KOREAZINC_2022H1, lines).verdict == FAIL
