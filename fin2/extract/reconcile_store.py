"""
`fin2/extract/reconcile.py`의 `ReconcileResult` 를 `report_recon_candidates`
리뷰 큐(DB)에 적재하는 write-path. 설계: `docs/plans/html_viewer_extractor_
design_2026-09-07.md` §8-10.

`reconcile()` 자체는 DB 미의존 순수 함수로 유지한다는 원칙(§8-8/§8-9)을 그대로
지킨다 — 이 모듈이 그 경계를 넘는 유일한 지점이다. `decision == "unresolved"`
인 것만 적재한다(`fin2/audit/curated_key_scan.py` 가 "①일치는 로그만" 하는
것과 동일 원칙 — html/pdf 로 자동 채택된 건 이미 값이 확정돼 하류로 흐르니
리뷰 큐에 넣을 이유가 없다).

재스캔(같은 필링을 다시 reconcile 해도)은 upsert 로 html_confidence/
pdf_confidence/html_values/pdf_values/reason/last_seen_at 만 갱신하고, 사람이
원문대조 후 갱신하는 status/resolution/resolution_note/resolved_at 은 절대
덮어쓰지 않는다(unit_overrides.py "원문대조 없이 짐작 금지" 원칙과 같은 결).

usage:
    from fin2.extract.reconcile import reconcile
    from fin2.extract.reconcile_store import persist_unresolved
    results = reconcile(scraper, rcept_no, corp_code=..., report_fiscal_year=..., report_fiscal_period=...)
    with get_session() as session:
        persist_unresolved(results, session, source_pipeline="track_c_backfill")
"""
from __future__ import annotations

from datetime import datetime

from fin2.extract.reconcile import Confidence, ReconcileResult, _TOTAL_CANONS

_CHECK_KIND_BS_GRAND_TOTAL = "bs_grand_total_identity"


def _facts_to_totals(facts: list | None) -> dict[str, int | None] | None:
    """BS 그랜드토탈 3종만 뽑아 JSONB 에 넣을 수 있는 단순 dict 로 변환.

    `facts` 가 None(PDF 를 아예 시도 안 한 T1 케이스)이면 None 을 그대로 반환
    — "값 3개가 다 없음(T2)"과 "애초에 안 봤음(T1이라 생략)"을 구분해서 남긴다.
    """
    if facts is None:
        return None
    out: dict[str, int | None] = {c: None for c in _TOTAL_CANONS}
    for f in facts:
        if f.canonical_account in _TOTAL_CANONS and f.amount_won is not None:
            out[f.canonical_account] = f.amount_won
    return out


def build_recon_candidate_rows(
    results: list[ReconcileResult],
    *, corp_code: str, rcept_no: str,
    report_fiscal_year: int, report_fiscal_period: str,
    source_pipeline: str = "track_c_backfill",
    check_kind: str = _CHECK_KIND_BS_GRAND_TOTAL,
) -> list[dict]:
    """`decision == "unresolved"` 인 `ReconcileResult` 만 upsert-ready dict 로 변환.

    DB 미의존 순수 함수 — `fin2/tests/test_reconcile_store.py` 가 여기까지만
    단위 테스트한다(실제 session.execute 는 `persist_unresolved()` 에서, DB
    의존이라 이 프로젝트 관례대로 pytest 스위트가 아니라 수동 스모크로 검증).
    """
    now = datetime.utcnow()
    rows = []
    for r in results:
        if r.decision != "unresolved":
            continue
        rows.append({
            "corp_code": corp_code,
            "rcept_no": rcept_no,
            "basis": r.basis,
            "check_kind": check_kind,
            "report_fiscal_year": report_fiscal_year,
            "report_fiscal_period": report_fiscal_period,
            "html_confidence": r.html_confidence.value,
            "pdf_confidence": r.pdf_confidence.value if r.pdf_confidence else None,
            "html_values": _facts_to_totals(r.html_facts),
            "pdf_values": _facts_to_totals(r.pdf_facts),
            "decision": r.decision,
            "reason": r.reason,
            "source_pipeline": source_pipeline,
            "last_seen_at": now,
        })
    return rows


def persist_unresolved(
    results: list[ReconcileResult],
    session,
    *, corp_code: str, rcept_no: str,
    report_fiscal_year: int, report_fiscal_period: str,
    source_pipeline: str = "track_c_backfill",
    check_kind: str = _CHECK_KIND_BS_GRAND_TOTAL,
) -> int:
    """`report_recon_candidates` upsert. 반환값 = 적재/갱신한 행 수(0 = 전부 자동채택됨).

    사람이 갱신하는 status/resolution/resolution_note/resolved_at 은 upsert
    SET 절에서 명시적으로 빠져있다 — 재스캔이 사람 판정을 덮어쓰지 않는다
    (`fin2/audit/curated_key_scan.py::run_all_scans()` 와 동일 패턴).
    """
    rows = build_recon_candidate_rows(
        results, corp_code=corp_code, rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        source_pipeline=source_pipeline, check_kind=check_kind,
    )
    if not rows:
        return 0

    from sqlalchemy.dialects.postgresql import insert

    from collector.models import ReconCandidate

    stmt = insert(ReconCandidate).values(rows)
    upd = {col: stmt.excluded[col] for col in
           ("report_fiscal_year", "report_fiscal_period", "html_confidence",
            "pdf_confidence", "html_values", "pdf_values", "decision", "reason",
            "source_pipeline", "last_seen_at")}
    stmt = stmt.on_conflict_do_update(
        index_elements=["corp_code", "rcept_no", "basis", "check_kind"],
        set_=upd)
    session.execute(stmt)
    session.commit()
    return len(rows)
