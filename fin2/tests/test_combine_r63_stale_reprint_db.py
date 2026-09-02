"""R63 (2026-09-02, docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_
reprint_design_2026-09-02.md) — DB-backed regression guards for the two real
reproductions this design was built on.

Requires a live DB (DATABASE_URL) with the migrations applied, matching the pattern
used by other DB-backed tests in this repo (e.g. fin2/tests/test_standard_financials_
view.py, tests/test_download_5corps.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.db import get_session
from fin2.layer3.combine import _stale_annual_reprint_table_seqs, build_merged_lines


def _db_available() -> bool:
    try:
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live DATABASE_URL")


def test_kgsteel_2006_consolidated_q1_reprint_detected():
    # KG스틸/동부제강(00115676) 2006 Q1 — 원문대조로 확정된 재현 표본(design doc §1):
    # "연결손익계산서" table_seq=1이 Q1/H1/Q3 필링에 완전 동일값으로 재게재됨.
    with get_session() as s:
        seqs = _stale_annual_reprint_table_seqs(s, "00115676", 2006, "Q1", "consolidated")
    assert 1 in seqs, f"expected table_seq=1 flagged stale, got {seqs}"


def test_kgsteel_2006_separate_not_flagged():
    # 같은 필링의 별도(table_seq=0, 진짜 당해분기 데이터 — 컬럼헤더 기간이 필링마다
    # 정확히 다름, 원문대조 확인)는 재게재 신호가 뜨면 안 된다.
    with get_session() as s:
        seqs = _stale_annual_reprint_table_seqs(s, "00115676", 2006, "Q1", "separate")
    assert 0 not in seqs


def test_kgsteel_2006_fy_not_gated():
    # FY(사업보고서)는 이 패턴과 무관 — 항상 빈 set.
    with get_session() as s:
        seqs = _stale_annual_reprint_table_seqs(s, "00115676", 2006, "FY", "consolidated")
    assert seqs == set()


def test_bracket_label_table_seq_excluded_from_merged_lines():
    # 00171867 rcept 20081114001440(2009H1) — "[유동자산]" 대괄호 라벨이 있는
    # table_seq에 매출액/자산총계/자본총계 등 DIRECT_MAP 라벨이 섞여있던 실측
    # 오염 사례(design doc §6). build_merged_lines()는 corp/fy/period 단위로
    # 동작하므로 그 필링의 (corp, fy, period)를 먼저 조회한다.
    with get_session() as s:
        row = s.execute(text("""
            SELECT corp_code, report_fiscal_year, report_fiscal_period
            FROM report_lines
            WHERE rcept_no = '20081114001440' AND corp_code = '00171867'
            LIMIT 1
        """)).fetchone()
        if row is None:
            pytest.skip("fixture filing 20081114001440 not present in this DB")
        corp, fy, period = row
        merged = build_merged_lines(s, corp, fy, period)
    bracket_labels = [r for r in merged if (r["label_raw"] or "").startswith("[")]
    assert bracket_labels == [], f"bracket-label rows leaked through: {bracket_labels}"
    # 같은 table_seq에 있던 정상형 라벨(매출액 등)도 함께 배제돼야 한다 — 개별 행이
    # 아니라 table_seq 전체가 요약표 잔재라는 신호이므로.
    leaked_summary_labels = [
        r for r in merged
        if r["statement"] in ("BS", "IS") and r.get("basis") == "consolidated"
        and (r["label_raw"] or "") in ("매출액", "자산총계", "자본총계")
        and r["value_won"] == 68_473_333_636  # 요약재무정보 표의 자산총계 실측값(원 단위 태깅)
    ]
    assert leaked_summary_labels == []
