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


def test_kgsteel_2006_cf_separate_q1_reprint_detected():
    # R63 CF 확장(2026-09-02 후속 세션, design doc §8) — 원문대조로 확정된 재현
    # 표본: "현금흐름표" table_seq=1이 "영업활동으로 인한 현금흐름"=54,870,597,628원
    # 으로 Q1/H1/Q3 필링에 완전 동일값 재게재(제24기/제23기, 분기 접미어 없음 —
    # 직전 확정 연차). table_seq=0은 "제25기 분기"(분기 접미어 있음, 진짜 당해분기 —
    # Q1=-58,251,047,462원, 필링마다 값이 다름)라 flag되면 안 된다. (이 corp/연도는
    # basis='consolidated' CF가 report_lines에 없어 separate로 확인 — statement=
    # 'CF'는 §1의 IS와 달리 basis 무관하게 같은 신호가 적용됨을 보여주는 표본.)
    with get_session() as s:
        seqs = _stale_annual_reprint_table_seqs(
            s, "00115676", 2006, "Q1", "separate", statement="CF")
    assert 1 in seqs, f"expected CF table_seq=1 flagged stale, got {seqs}"
    assert 0 not in seqs, f"genuine CF table_seq=0 must not be flagged, got {seqs}"


def test_hyundai_2004q1_separate_cf_amendment_duplication_not_flagged():
    # ★버그수정 회귀(2026-09-02, R63 후속 — CF 확장 백필 중 원문대조로 발견):
    # 현대차(00164742) 2004 Q1 별도 CF table_seq=0은 원본(20040515000203)+정정
    # (20040618000205) 2개 필링이 있고, 그 안의 5개 세부계정이 H1과 우연히
    # 일치(5×2필링=10, 임계값과 정확히 같음) — 진짜 재게재가 아니라 필링 중복
    # 집계 아티팩트. table_seq=0은 진짜 당해분기 표(합계선 "영업활동으로 인한
    # 현금흐름"이 Q1=-248,693백만/H1=1,485,674백만/Q3=1,812,881백만으로 분기마다
    # 전부 다름, 원문대조 확인) — 절대 flag되면 안 된다.
    with get_session() as s:
        seqs = _stale_annual_reprint_table_seqs(
            s, "00164742", 2004, "Q1", "separate", statement="CF")
    assert 0 not in seqs, f"genuine table_seq=0 wrongly flagged (dup-count artifact), got {seqs}"


def test_kgsteel_2006_is_and_cf_stale_seqs_are_independent():
    # table_seq는 statement별 독립 카운터 — IS의 stale set과 CF의 stale set을
    # 같은 (corp,fy,period,basis)에서 각각 구해도 서로 다른 statement 쿼리이므로
    # 섞이지 않음을 확인(§8 안전장치의 실측 재확인).
    with get_session() as s:
        is_seqs = _stale_annual_reprint_table_seqs(
            s, "00115676", 2006, "Q1", "consolidated", statement="IS")
        cf_seqs = _stale_annual_reprint_table_seqs(
            s, "00115676", 2006, "Q1", "separate", statement="CF")
    assert 1 in is_seqs
    assert 1 in cf_seqs
    # 두 호출은 서로 다른 basis/statement 스코프라 독립적으로 계산됨 — 우연히 같은
    # table_seq 번호(1)를 flag했다고 해서 같은 표를 가리키는 게 아님(둘 다 맞는 결과).


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
