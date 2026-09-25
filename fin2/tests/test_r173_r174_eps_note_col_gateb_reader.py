"""R173 (EPS 경로 주석열) · R174 (Gate B 판독기: 증명된 단위 교정 + 당기 '-' = 0 후보).

Gate B pass→fail_b 148건 트리아지(docs/qa/gateb_pass_to_fail_148_triage_2026-09-25.md) 중 발견.
실측 원문 파일 기반 — raw_report 가 없으면 건너뛴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines  # noqa: E402
from fin2.audit.face_audit import read_report_face_tracked  # noqa: E402

_RAW = Path(__file__).resolve().parents[2] / "raw_report"


def test_r173_eps_path_skips_note_column():
    """아이큐어 2016Q3: [주석 21 | 3개월 277 | 누적 (118)] — 주석열을 금액으로 세면 누적 대신
    3개월 277 이 당기로 들어갔다."""
    path = _RAW / "KOSDAQ/00554352_아이큐어/quarter/2016/20161129000515.xml"
    if not path.exists():
        return
    eps = {(r.basis, r.label_raw): r.value_won
           for r in extract_report_lines(path, rcept_no="20161129000515", corp_code="00554352",
                                         report_fiscal_year=2016, report_fiscal_period="Q3")
           if r.statement == "IS" and (r.source_ref or "").startswith("eps/") and r.col_index == 0}
    assert eps[("separate", "기본주당이익(손실)")] == -118
    assert eps[("consolidated", "기본주당이익(손실)")] == -440


def test_r174_gateb_reader_follows_proved_unit_override():
    """동성케미컬 2017H1 — R169 가 '백만원 선언·실제 원'으로 확정한 필링. 판독기가 선언을
    믿으면 자산총계가 ×10⁶ 이었다."""
    path = _RAW / "KOSPI/00679314_동성케미컬/half/2017/20170814002311.xml"
    if not path.exists():
        return
    lines, _track = read_report_face_tracked(path)
    ta = {l.amount_won for l in lines if l.canonical == "bs.total_assets" and l.basis == "consolidated"}
    assert 842_787_340_982 in ta
    assert all(v < 10 ** 15 for v in ta)


def test_r174_gateb_reader_dash_current_cell_is_zero_candidate():
    """패션플랫폼 2017Q3 별도 재무활동현금흐름: `-, -, -, 11,827,416,000` — 당기 0."""
    path = _RAW / "KOSDAQ/01101041_패션플랫폼/quarter/2017/20171114000014.xml"
    if not path.exists():
        return
    lines, _track = read_report_face_tracked(path)
    cff = {l.amount_won for l in lines if l.canonical == "cf.financing" and l.basis == "separate"}
    assert 0 in cff
