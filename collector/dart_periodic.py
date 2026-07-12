"""Phase 2 · 정기보고서 API 6종 공통 수집 루프 — 배당(alotMatter)/자기주식(tesstkAcqsDspsSttus)/
직원현황(empSttus)/타법인출자(otrCprInvstmntSttus)/임원보수 요약(hmvAuditAllSttus)/개인별(indvdlByPay).

dart_extra.py::fetch_executives / dart_capital.py::sync_capital_events 패턴을 따름:
  - sync_* 함수가 get_session() 을 내부에서 열고 닫는다(호출측이 세션을 관리하지 않음).
  - DART 013(조회결과없음)은 DartClient._api_get_json 이 이미 빈 리스트로 흡수.
  - 013 외 비-000(특히 020 쿼터초과)은 DartApiError 로 그대로 raise — ad-hoc _get() 재구현
    금지(memory key-bugs-fixed.md #6). 호출측(scripts/collect_periodic_apis.py)이 020 을
    circuit breaker 로 잡아 즉시 중단+재개 안내한다.
  - 각 API 응답의 raw 원본을 JSONB 로 보존(필드명 변이 대비, B2 자본이벤트에서 확립된 관례).
  - corp_code+fiscal_year+api 그레인 delete-then-insert 멱등.
  - periodic_api_progress 체크포인트에 ok/no_data/error 를 반드시 기록 — no_data 도 "확인 완료"로
    남겨야 재실행 시 이미 확인한 케이스를 다시 조회해 쿼터를 낭비하지 않는다.

usage:
    from collector.dart_client import DartClient
    from collector.dart_periodic import sync_periodic
    client = DartClient()
    sync_periodic(client, "alotMatter", "00126380", 2023)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy.dialects.postgresql import insert as pg_insert

from collector.dart_client import DartClient, DartApiError
from collector.db import get_session
from collector.models import (
    DividendFacts, TreasuryActivity, EmployeeStats, OtherInvestment,
    ExecPaySummary, ExecPayIndividual, PeriodicApiProgress,
)

# 정기보고서(사업보고서)만 대상 — bsns_year 단위 연 1회(분기 동일항목은 비범위, PRD §3).
REPRT_CODE = "11011"

API_NAMES: list[str] = [
    "alotMatter", "tesstkAcqsDspsSttus", "empSttus",
    "otrCprInvstmntSttus", "hmvAuditAllSttus", "indvdlByPay",
]


def _num(v) -> Optional[int]:
    if not v or v == "-":
        return None
    try:
        return int(str(v).replace(",", "").strip())
    except ValueError:
        return None


def _pct(v) -> Optional[float]:
    if not v or v == "-":
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _t(v, n: int) -> Optional[str]:
    if not v:
        return None
    s = str(v).strip()
    return s[:n] if s and s != "-" else None


def fetch_periodic(client: DartClient, api_name: str, corp_code: str, fiscal_year: int) -> list[dict]:
    """API 이름으로 해당 DartClient 메서드를 호출. 013 은 빈 리스트, 020 등은 DartApiError raise."""
    fn = {
        "alotMatter":          client.get_dividend_matters,
        "tesstkAcqsDspsSttus": client.get_treasury_stock_status,
        "empSttus":            client.get_employee_status,
        "otrCprInvstmntSttus": client.get_other_corp_investment,
        "hmvAuditAllSttus":    client.get_exec_pay_summary,
        "indvdlByPay":         client.get_exec_pay_individual,
    }[api_name]
    return fn(corp_code, fiscal_year, REPRT_CODE)


# ── API별 row → 테이블 컬럼 매핑(실호출 확인 필드명, 2026-07-12) ────────────────

def _map_dividend(corp_code: str, fy: int, rows: list[dict]) -> Optional[dict]:
    """alotMatter 는 se(항목명)+stock_knd 조합의 long-format ~15행 — corp+fy 당 1행으로 피벗."""
    if not rows:
        return None
    out: dict = {"corp_code": corp_code, "fiscal_year": fy}
    for r in rows:
        se = (r.get("se") or "").strip()
        knd = (r.get("stock_knd") or "").strip()
        val = r.get("thstrm")
        if se == "현금배당금총액(백만원)":
            out["total_dividend_amount"] = _num(val)
        elif se == "(연결)현금배당성향(%)":
            out["payout_ratio"] = _pct(val)
        elif se == "현금배당수익률(%)" and knd == "보통주":
            out["dividend_yield_common"] = _pct(val)
        elif se == "주당 현금배당금(원)" and knd == "보통주":
            out["dps_common"] = _num(val)
        elif se == "주당 현금배당금(원)" and knd == "우선주":
            out["dps_pref"] = _num(val)
        elif se == "주당 주식배당(주)" and knd == "보통주":
            out["stock_dividend_ratio"] = _pct(val)
    out["rcept_no"] = rows[0].get("rcept_no")
    out["raw"] = rows
    out["fetched_at"] = datetime.utcnow()
    return out


def _map_treasury(corp_code: str, fy: int, rows: list[dict]) -> list[dict]:
    return [{
        "corp_code": corp_code, "fiscal_year": fy,
        "stock_kind":      _t(r.get("stock_knd"), 20),
        "acqs_method1":    _t(r.get("acqs_mth1"), 60),
        "acqs_method2":    _t(r.get("acqs_mth2"), 60),
        "acqs_method3":    _t(r.get("acqs_mth3"), 60),
        "qty_begin":       _num(r.get("bsis_qy")),
        "qty_acquired":    _num(r.get("change_qy_acqs")),
        "qty_disposed":    _num(r.get("change_qy_dsps")),
        "qty_incinerated": _num(r.get("change_qy_incnr")),
        "qty_end":         _num(r.get("trmend_qy")),
        "remark":          _t(r.get("rm"), 200),
        "rcept_no":        r.get("rcept_no"),
        "raw": r,
        "fetched_at": datetime.utcnow(),
    } for r in rows]


def _map_employee(corp_code: str, fy: int, rows: list[dict]) -> list[dict]:
    return [{
        "corp_code": corp_code, "fiscal_year": fy,
        "division":            _t(r.get("fo_bbm"), 60),
        "sex":                 _t(r.get("sexdstn"), 4),
        "regular_count":       _num(r.get("rgllbr_co")),
        "contract_count":      _num(r.get("cnttk_co")),
        "total_count":         _num(r.get("sm")),
        "avg_tenure_years":    _pct(r.get("avrg_cnwk_sdytrn")),
        "annual_salary_total": _num(r.get("fyer_salary_totamt")),
        "avg_salary":          _num(r.get("jan_salary_am")),
        "remark":              _t(r.get("rm"), 200),
        "rcept_no":            r.get("rcept_no"),
        "raw": r,
        "fetched_at": datetime.utcnow(),
    } for r in rows]


def _map_other_investment(corp_code: str, fy: int, rows: list[dict]) -> list[dict]:
    return [{
        "corp_code": corp_code, "fiscal_year": fy,
        "investee_name":         _t(r.get("inv_prm"), 150),
        "first_acquired_date":   _t(r.get("frst_acqs_de"), 20),
        "purpose":               _t(r.get("invstmnt_purps"), 60),
        "first_acquired_amount": _num(r.get("frst_acqs_amount")),
        "begin_qty":             _num(r.get("bsis_blce_qy")),
        "begin_pct":             _pct(r.get("bsis_blce_qota_rt")),
        "begin_book_value":      _num(r.get("bsis_blce_acntbk_amount")),
        "end_qty":               _num(r.get("trmend_blce_qy")),
        "end_pct":               _pct(r.get("trmend_blce_qota_rt")),
        "end_book_value":        _num(r.get("trmend_blce_acntbk_amount")),
        "investee_total_assets": _num(r.get("recent_bsns_year_fnnr_sttus_tot_assets")),
        "investee_net_income":   _num(r.get("recent_bsns_year_fnnr_sttus_thstrm_ntpf")),
        "rcept_no": r.get("rcept_no"),
        "raw": r,
        "fetched_at": datetime.utcnow(),
    } for r in rows]


def _map_exec_pay_summary(corp_code: str, fy: int, rows: list[dict]) -> Optional[dict]:
    if not rows:
        return None
    r = rows[0]
    return {
        "corp_code": corp_code, "fiscal_year": fy,
        "total_exec_count":   _num(r.get("nmpr")),
        "total_pay_amount":   _num(r.get("mendng_totamt")),
        "avg_pay_per_person": _num(r.get("jan_avrg_mendng_am")),
        "remark":   _t(r.get("rm"), 200),
        "rcept_no": r.get("rcept_no"),
        "raw": r,
        "fetched_at": datetime.utcnow(),
    }


def _map_exec_pay_individual(corp_code: str, fy: int, rows: list[dict]) -> list[dict]:
    return [{
        "corp_code": corp_code, "fiscal_year": fy,
        "person_name":      _t(r.get("nm"), 50),
        "position":         _t(r.get("ofcps"), 100),
        "total_pay_amount": _num(r.get("mendng_totamt")),
        "pay_detail": r,
        "rcept_no": r.get("rcept_no"),
        "fetched_at": datetime.utcnow(),
    } for r in rows]


# (모델, 테이블명, 매퍼, 단일행 여부) — 단일행 API 는 매퍼가 dict|None 반환, 그 외는 list[dict].
_TABLE_MAP: dict[str, tuple] = {
    "alotMatter":          (DividendFacts,     "dividend_facts",     _map_dividend,           True),
    "tesstkAcqsDspsSttus": (TreasuryActivity,  "treasury_activity",  _map_treasury,           False),
    "empSttus":            (EmployeeStats,     "employee_stats",     _map_employee,           False),
    "otrCprInvstmntSttus": (OtherInvestment,   "other_investments",  _map_other_investment,   False),
    "hmvAuditAllSttus":    (ExecPaySummary,    "exec_pay_summary",   _map_exec_pay_summary,   True),
    "indvdlByPay":         (ExecPayIndividual, "exec_pay_individual", _map_exec_pay_individual, False),
}


def _record_checkpoint(session, corp_code: str, fiscal_year: int, api_name: str, status: str) -> None:
    stmt = pg_insert(PeriodicApiProgress).values(
        corp_code=corp_code, fiscal_year=fiscal_year, api_name=api_name,
        status=status, checked_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["corp_code", "fiscal_year", "api_name"],
        set_={"status": status, "checked_at": datetime.utcnow()},
    )
    session.execute(stmt)


def sync_periodic(client: DartClient, api_name: str, corp_code: str, fiscal_year: int) -> int:
    """단일 (corp, fiscal_year, api) 그레인 수집 + delete-then-insert 적재 + 체크포인트 기록.

    Returns:
        저장된 행 수(0 이면 no_data 또는 error — periodic_api_progress.status 로 구분).

    Raises:
        DartApiError: status='020'(쿼터초과) — 호출측이 circuit breaker 로 즉시 중단하도록 그대로 전파.
    """
    model, table_name, mapper, is_single = _TABLE_MAP[api_name]

    try:
        rows = fetch_periodic(client, api_name, corp_code, fiscal_year)
    except DartApiError as e:
        if e.status == "020":
            raise
        with get_session() as session:
            _record_checkpoint(session, corp_code, fiscal_year, api_name, "error")
        logger.warning(f"[periodic] {api_name} {corp_code} {fiscal_year}: DART [{e.status}] {e.message}")
        return 0

    mapped = mapper(corp_code, fiscal_year, rows)
    saved = (1 if mapped else 0) if is_single else len(mapped)

    with get_session() as session:
        session.execute(model.__table__.delete().where(
            (model.corp_code == corp_code) & (model.fiscal_year == fiscal_year)
        ))
        if is_single:
            if mapped:
                session.execute(model.__table__.insert(), [mapped])
        elif mapped:
            session.execute(model.__table__.insert(), mapped)
        _record_checkpoint(session, corp_code, fiscal_year, api_name, "ok" if saved else "no_data")

    return saved
