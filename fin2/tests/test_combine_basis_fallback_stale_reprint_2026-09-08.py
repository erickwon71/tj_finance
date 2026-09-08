"""2026-09-08 — `combine_full()`'s `basis_fallback` path queried
`_stale_annual_reprint_table_seqs()` with the original requested `basis` instead of
the basis it actually borrowed candidate rows from, so R63's "직전연차 재게재 배제"
never fired for fallback-derived values (the requested basis has 0 report_lines rows
by definition when the fallback triggers, so the exclusion query always returned an
empty set()). Design: docs/plans/basis_fallback_stale_reprint_exclusion_design_2026-09-08.md

Requires a live DB (DATABASE_URL) with the migrations applied — same pattern as
fin2/tests/test_combine_r63_stale_reprint_db.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.db import get_session
from fin2.layer3.combine import combine_full


def _db_available() -> bool:
    try:
        with get_session() as s:
            s.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="requires a live DATABASE_URL")


def test_vivien_2002h1_basis_fallback_stale_revenue_excluded():
    # 비비안(00107677) 2002 H1, rcept 20020209000160 — 원문대조 확인(v2-drop-remaining-
    # backlog-2026-09-03.md 항목2): 이 rcept 는 report_lines 에 'consolidated' 행이
    # 0개(원문에 연결 섹션 자체가 없음)라 basis_fallback 이 'separate' 데이터를 빌려온다.
    # 그 separate 쪽 revenue 는 R63 재게재 배제로 이미 정상적으로 NULL(직전 FY2001 값
    # 148,330,113,813 원의 재게재로 확인됨) — 수정 전에는 fallback 경로만 이 배제를
    # 놓쳐 consolidated.revenue 에 그 재게재 값이 그대로 샜다.
    with get_session() as s:
        col, conflicts, prov = combine_full(s, "00107677", 2002, "H1", "consolidated")
    assert prov["basis_fallback"] is True
    assert col.get("revenue") != 148_330_113_813, (
        "stale FY2001 reprint leaked into basis_fallback consolidated revenue")
    assert "is.revenue" not in conflicts, (
        "expected clean exclusion (matches separate's own outcome), not a held conflict")


def test_corp_00106395_2000h1_basis_fallback_stale_revenue_excluded():
    # 00106395 2000 H1, rcept 20000814000008 — 같은 버그의 두 번째 검증 표본(별도만
    # 존재, 연결 섹션 없음). 수정 전 78,402,277,000원(재게재 값)이 그대로 샜음(재확인
    # 완료), 수정 후 None.
    with get_session() as s:
        col, conflicts, prov = combine_full(s, "00106395", 2000, "H1", "consolidated")
    assert prov["basis_fallback"] is True
    assert col.get("revenue") != 78_402_277_000, (
        "stale reprint leaked into basis_fallback consolidated revenue")


def test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix():
    # 뉴인텍(00105040) 2007 Q1 — 이건 basis_fallback 이 아니라 DKME 류(원문에 연결
    # 당기 데이터 자체가 없어 report_lines 에 실제 값이 들어있는) 별개 원인이라 이번
    # 수정 스코프 밖(개별 report_lines 삭제로 처리할 항목). basis_fallback=False 여야
    # 함을 확인해 두 원인이 실제로 코드 경로부터 다름을 회귀 고정.
    with get_session() as s:
        col, conflicts, prov = combine_full(s, "00105040", 2007, "Q1", "consolidated")
    assert prov["basis_fallback"] is False
