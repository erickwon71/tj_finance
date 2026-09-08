"""is_ifrs 판정 근거(2026-09-08) 회귀 테스트 (순수 텍스트 판정만, DB 비의존).

docs/plans/is_ifrs_v3_design_2026-09-08.md §5-2 대규모 표본 조사에서 확정한 규칙:
Track A(ACODE+ACONTEXT) > 기준서 번호 자릿수(<1000 K-GAAP / >=1000 K-IFRS, 혼재는
NULL). "한국채택국제회계기준"/"K-IFRS" 단어 자체는 실측으로 변별력 0임이 반증돼
쓰지 않는다 — 아래 테스트가 이걸 회귀로 고정한다(전환기 각주 함정 재발 방지).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.ifrs_evidence import (  # noqa: E402
    EVIDENCE_STD_NO_KGAAP, EVIDENCE_STD_NO_KIFRS, EVIDENCE_STD_NO_MIXED, EVIDENCE_TRACK_A,
    compute_text_evidence, detect_std_no_evidence, detect_track_a_evidence, resolve_is_ifrs,
)


def test_track_a_requires_both_acode_and_acontext():
    assert detect_track_a_evidence('<TE ACODE="ifrs-full_Assets" ACONTEXT="CFY2024">1</TE>')
    # ACODE 만 있고 ACONTEXT 가 없으면(예: 회사고유 확장코드만 태깅된 다른 셀) Track A 아님.
    assert not detect_track_a_evidence('<TE ACODE="ifrs-full_Assets">1</TE>')
    assert not detect_track_a_evidence('<TE>그냥 텍스트, ACODE 없음</TE>')


def test_track_a_ignores_dart_extension_only_without_acontext():
    # 회사고유 확장 개념(entity{corp}_...)만 있고 표준 ifrs-full_/dart_ 접두가 아니면 무시.
    assert not detect_track_a_evidence('<TE ACODE="entity12345_CustomConcept" ACONTEXT="x">1</TE>')


def test_std_no_low_digits_only_is_kgaap():
    text = "회사의 재무제표는 대한민국의 기업회계기준서 제1호 내지 제17호에 따라 작성되었습니다."
    code, nums = detect_std_no_evidence(text)
    assert code == EVIDENCE_STD_NO_KGAAP
    assert nums == [1, 17]


def test_std_no_high_digits_only_is_kifrs():
    text = "연결재무제표는 기업회계기준서 제1001호 및 제1027호에 따라 작성되었습니다."
    code, nums = detect_std_no_evidence(text)
    assert code == EVIDENCE_STD_NO_KIFRS
    assert nums == [1001, 1027]


def test_std_no_mixed_digits_does_not_guess():
    text = "종전 기업회계기준서 제17호를 적용하다가, 당기부터 기업회계기준서 제1027호를 적용함."
    code, nums = detect_std_no_evidence(text)
    assert code == EVIDENCE_STD_NO_MIXED
    assert nums == [17, 1027]


def test_std_no_range_listing_without_repeated_anchor():
    """실측 원문 패턴(§5-2, 00313649 현대바이오 2007FY 표본) — "기업회계기준서"가 나열의
    각 항목마다 반복되지 않고 범위/열거로만 이어진다. 앵커 하나로 뒤따르는 여러 "제N호"를
    다 잡아야 한다(각 항목마다 앵커가 있다고 가정하면 이 케이스를 놓친다)."""
    text = "회사의 재무제표는 대한민국의 기업회계기준서 제1호 내지 제17호(제11호 및 제18호는 제외)에 따라 작성되었습니다."
    code, nums = detect_std_no_evidence(text)
    assert code == EVIDENCE_STD_NO_KGAAP
    assert nums == [1, 11, 17, 18]


def test_std_no_absent_returns_none():
    code, nums = detect_std_no_evidence("이 문서엔 기준서 번호 언급이 없습니다.")
    assert code is None
    assert nums == []


def test_kifrs_word_alone_is_not_evidence_regression_guard():
    """실측 반증(§5-2): "한국채택국제회계기준"/"K-IFRS" 단어는 K-GAAP 시대 필링에도
    전환 예고 각주로 100% 등장한다 — 단어만으로 판정하면 안 된다는 걸 회귀로 고정."""
    text = ("당사는 2011 회계연도부터 한국채택국제회계기준(K-IFRS)을 적용할 예정이며, "
            "당기 재무제표는 종전과 같이 기업회계기준서 제1호 내지 제17호에 따라 작성되었습니다.")
    evidence, _detail = compute_text_evidence(text)
    # 기준서 번호(저자릿수)만으로 K-GAAP 판정 — "한국채택국제회계기준" 단어는 무시된다.
    assert evidence == EVIDENCE_STD_NO_KGAAP


def test_track_a_takes_priority_over_std_no():
    text = ('<TE ACODE="ifrs-full_Assets" ACONTEXT="CFY2024">1</TE> '
            '이 문서는 기업회계기준서 제17호도 언급한다(각주).')
    evidence, _detail = compute_text_evidence(text)
    assert evidence == EVIDENCE_TRACK_A


def test_resolve_is_ifrs_mapping():
    assert resolve_is_ifrs(EVIDENCE_TRACK_A) is True
    assert resolve_is_ifrs(EVIDENCE_STD_NO_KIFRS) is True
    assert resolve_is_ifrs(EVIDENCE_STD_NO_KGAAP) is False
    assert resolve_is_ifrs(EVIDENCE_STD_NO_MIXED) is None
    assert resolve_is_ifrs(None) is None
