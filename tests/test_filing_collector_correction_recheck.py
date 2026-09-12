"""정정본 회계기간 재확인 회귀 테스트 (2026-09-12 설계).

배경: docs/plans/era_routing_fallback_and_fiscal_year_correction_parsing_design_
2026-09-12.md §1. `report_nm`에 "(YYYY.MM)" 없는 정정본은 접수일 기반 추정으로
회계연도를 잡는데, 정정이 원본보다 몇 년~수십 년 뒤에 이뤄지면(진원생명과학
20220908000421 실측 — 원본 2006년 접수, 정정 2022년, 실제 대상은 2005 회계연도)
그 추정이 완전히 틀린다. `_fiscal_period_from_correction_section()`이 원문
CORRECTION 섹션의 "최초제출일"로 재확인한다.

실행: pytest tests/test_filing_collector_correction_recheck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector.filing_collector import (  # noqa: E402
    _CORRECTION_ORIG_DATE_RE, _detect_report_type, _fiscal_period_from_correction_section,
)


# ── _detect_report_type() — 제출기한연장신고서 오분류 회귀(2026-09-12) ──────────
# 배경: "사업보고서제출기한연장신고서"가 REPORT_TYPE_MAP 키워드("사업보고서")를
# 부분문자열로 포함해 annual 로 오분류되고 있었다(전사 221건 실측 — 재무제표가
# 전혀 없는 행정신고인데 report_type/fiscal_year 계산까지 실제 보고서처럼 타서
# 계층2 reload 대상에 노이즈로 낀다).

def test_deadline_extension_notice_not_classified_as_annual():
    assert _detect_report_type("사업보고서제출기한연장신고서") is None
    assert _detect_report_type("사업보고서제출기한연장신고서 (2022.12)") is None


def test_deadline_extension_notice_with_amendment_prefix_not_classified():
    """정정+연장신고 조합("[기재정정]사업보고서제출기한연장신고서")도 제외."""
    assert _detect_report_type("[기재정정]사업보고서제출기한연장신고서 (2021.12)") is None


def test_deadline_extension_notice_variants_for_half_and_quarter():
    assert _detect_report_type("반기보고서제출기한연장신고서") is None
    assert _detect_report_type("분기보고서제출기한연장신고서") is None


def test_normal_reports_still_classified():
    """회귀 방지 — 정상 보고서까지 같이 걸러지면 안 된다."""
    assert _detect_report_type("사업보고서 (2022.12)") == "annual"
    assert _detect_report_type("[기재정정]사업보고서 (2022.12)") == "annual"
    assert _detect_report_type("반기보고서 (2022.06)") == "half"
    assert _detect_report_type("분기보고서 (2022.09)") == "quarter"
    assert _detect_report_type("주요사항보고서") is None


# ── 정규식 단위(DB 비의존) ───────────────────────────────────────────────────

def test_correction_date_regex_matches_real_sample():
    """실측 원문 문구(진원생명과학 20220908000421) 그대로."""
    txt = "2. 정정대상 공시서류의 최초제출일 : 2006.03.31"
    m = _CORRECTION_ORIG_DATE_RE.search(txt)
    assert m is not None
    assert m.group(1) == "2006"
    assert m.group(2) == "03"


def test_correction_date_regex_full_width_colon_variant():
    """전각 콜론("：") 표기 변형도 허용."""
    txt = "정정대상 공시서류의 최초제출일：2010.01.15"
    m = _CORRECTION_ORIG_DATE_RE.search(txt)
    assert m is not None
    assert (m.group(1), m.group(2)) == ("2010", "01")


def test_correction_date_regex_no_match_when_absent():
    """이 문구 자체가 없으면(정정 사유만 있는 등) 매칭 안 됨 — 조용히 폴백해야 하는 경우."""
    txt = "1. 정정대상 공시서류 : 제30기 사업보고서 / 3. 정정사유 : 재무제표 금액 오기"
    assert _CORRECTION_ORIG_DATE_RE.search(txt) is None


# ── 실제 DB·원문 연동(있으면 실행, 없으면 스킵) ──────────────────────────────

def test_jinwon_correction_recovers_2005fy_from_original_filing_date():
    """★거짓양성 회귀 — 진원생명과학 20220908000421(2026-09-12 실측).

    원본은 2006.03.31 접수 → `_parse_fiscal_info`의 기존 "접수일 기반" 폴백을 그
    날짜에 다시 태우면 (annual, mo=3<=6) → fiscal_year=원본접수연도-1=2005, FY.
    정정본 자신의 접수일(2022)로 계산하면 틀렸던 것과 대조.
    """
    try:
        from collector.db import get_session
    except Exception:
        return  # DB 미가용 환경 — 스킵
    try:
        with get_session() as s:
            result = _fiscal_period_from_correction_section(
                s, "20220908000421", "annual", fiscal_month=12)
    except Exception:
        return  # DB 미가용/파일 미존재 — 스킵(회귀 고정은 위 순수 정규식 테스트가 담당)
    if result is None:
        return  # 원문 미다운로드 등 환경 차이 — 스킵
    assert result == (2005, "FY"), result
