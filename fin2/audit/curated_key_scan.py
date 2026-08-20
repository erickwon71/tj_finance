"""
Gate B curated 키 재생성기 — 전수 패턴 스캔 → 3분류(§5-A).

설계: docs/plans/gateb_curated_key_regenerator_design_2026-08-18.md
결정: 같은 문서 §6(2026-08-19 확정) — 1차 구현 범위는 T1 쉬운 2종(trade_payables additive,
cogs concept mismatch) + T2 전수 탐지 스캔(sga_subline, cogs_additive) 4개 family.
(`_FX_PRESENTATION_CURRENCY_KEYS`/T0 축B/T3 는 범위 밖 — §6 결정사항 2·3, 문서 §3 T3 참고.)

R15~R33 다수가 (corp, fy, period[, basis]) 를 리터럴로 열거한 override 로 구현돼 있다
(`fin2/layer3/combine.py`/`fin2/audit/face_audit.py`). 새 필링이 들어와도 이 키 집합은
자동으로 안 늘어나 같은 부류의 버그가 재발하거나(값이 틀림) Gate B 가 pending 을 fail 로
잘못 잡을 수 있다 — 이 모듈은 원 생성/probe 스크립트의 검증 로직을 **corp 제한 없는 전수
모집단**으로 재실행해 신규 후보를 찾는 **탐지 전용**(자동 코드 반영 없음, §5-A) 도구다.

## 두 그룹의 스캔 방식이 다른 이유

- **T2(sga_subline/cogs_additive)** — 원 생성 스크립트(`scripts/generate_*_2026-08-15.py`)
  가 이미 corp 제한 없이 `report_lines` 를 직접 훑는 구조라, 그 쿼리를 그대로 재사용한다.
  `report_lines` 는 override 등록 여부와 무관하게 항상 원문 그대로라 **①일치(스캔==등재)가
  곧 동치성 증명**이 되고 ④소멸(정정공시로 구조가 바뀜)도 정상 계산된다.
- **T1(trade_payables_additive/cogs_concept_mismatch)** — XML/PDF 를 다시 열지 않고 이미
  계산된 `face_audit`(v3, 최신 전수 재감사) 의 `fail_detail` 을 재사용해 report_won 을 얻는다
  (전사 재감사가 데일리/반기 표준화마다 갱신되므로 최신 상태 — 2026-08-21
  xbrl_zip 전사 반영 참고). **주의**: 등재된 키는 정확히 그 override 때문에 face_audit 에서
  더 이상 VALUE_DIFF 로 안 뜬다(cogs_concept_mismatch 는 face_audit.py 가 pending 으로
  재분류, trade_payables_additive 는 combine.py 가 build 시점에 db_won 자체를 고쳐 PASS 로
  뜸) — 즉 이 스캔의 모집단은 **구조적으로 이미 등재분을 제외**하고 있어 ①일치/④소멸 계산이
  성립하지 않는다(design §5-C 가 이미 예견한 caveat). forward/lateral 분류만 제공한다.

**자동 코드 반영 없음.** ②③ 후보는 `curated_key_candidates` 테이블에 적재만 하고, 사람이
원문대조 후 `combine.py`/`face_audit.py` 에 수동 등재 + `docs/PARSING_RULES.md` 갱신 —
지금까지의 R15~R33 워크플로우와 동일, 탐지 단계만 자동화한다(§4 의 실측 경고: 항등식
성립이 우연/기간별로 갈릴 수 있어 무검증 자동반영은 금지).

usage:
    python -m fin2.audit.curated_key_scan          # 전체 4-family 스캔 + 적재 + 알림
    scripts/collect_new.py 두 call site(§5-B, 표준화 직후)에서 run_all_scans() 로 호출.
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from collector.db import get_session
from collector.models import CuratedKeyCandidate
from parser.common.amount_normalizer import normalize_account_name
from parser.common.account_mapper import get_mapper
from fin2.layer3.industry_profiles import norm as norm_label

SCAN_VERSION = "1.0-2026-08-21"

# ── T2 공용 라벨 마커(원 스크립트와 정확히 동일해야 ①일치가 재현된다 — 절대 통합/수정 금지) ──
_SGA_SUBLINE_COGS_MARKERS = ("매출원가", "원가")            # generate_sga_subline_override 원본
_SGA_MARKERS = ("판매비와관리비", "판매비및관리비", "판매비와 관리비", "판매비 및 관리비")
_COGS_ADDITIVE_MARKER = "매출원가"                            # generate_cogs_additive_override 원본

_LIABILITY_LABEL_MARKERS = ("채무", "미지급")   # T1-1 후보 pool(BS 부채성 라인) 필터


# ── 공용: '영업비용' P-line 모집단(T2 두 family 가 공유, 원 스크립트와 동일 쿼리) ──────────
def _operating_expense_parents(session):
    rows = session.execute(text("""
        SELECT id, corp_code, rcept_no, basis, table_seq, row_order, depth, label_raw, value_won,
               report_fiscal_year, report_fiscal_period
        FROM report_lines
        WHERE statement = 'IS' AND col_index = 0 AND node_role = 'P'
          AND label_raw LIKE '%영업비용%'
    """)).fetchall()
    return [r for r in rows if normalize_account_name(r[7]) == "영업비용"]


def _direct_children(session, corp, rcept, basis, tseq, prow, pdepth):
    siblings = session.execute(text("""
        SELECT row_order, depth, label_raw, value_won
        FROM report_lines
        WHERE corp_code = :c AND rcept_no = :r AND basis = :b AND statement = 'IS'
          AND table_seq = :t AND col_index = 0 AND row_order > :ro
        ORDER BY row_order
    """), {"c": corp, "r": rcept, "b": basis, "t": tseq, "ro": prow}).fetchall()
    children = []
    for ro, depth, label, val in siblings:
        if depth is None or pdepth is None or depth <= pdepth:
            break
        if depth == pdepth + 1:
            children.append((label, val))
    return children


def _jsonable(obj):
    if isinstance(obj, tuple) or isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def _classify_full(scan_keys: set, registered_keys: set, corp_index: int = 0):
    """T2 전용 — 모집단이 override 등록과 무관하므로 4-way 전부 계산 가능.
    → (matched=①, vanished=④, forward=②, lateral=③)."""
    matched = scan_keys & registered_keys
    vanished = registered_keys - scan_keys
    new = scan_keys - registered_keys
    registered_corps = {k[corp_index] for k in registered_keys}
    forward = {k for k in new if k[corp_index] in registered_corps}
    lateral = new - forward
    return matched, vanished, forward, lateral


def _classify_residual(scan_keys: set, registered_keys: set, corp_index: int = 0):
    """T1 전용 — 모집단이 구조적으로 이미 등재분을 제외한다(모듈 docstring 참고).
    matched/vanished 는 계산하지 않는다(성립하지 않음) — forward/lateral 만."""
    registered_corps = {k[corp_index] for k in registered_keys}
    forward = {k for k in scan_keys if k[corp_index] in registered_corps}
    lateral = scan_keys - forward
    return forward, lateral


def _result(family, *, matched=None, vanished=None, forward, lateral, detail, has_basis: bool):
    n_m = len(matched) if matched is not None else None
    n_v = len(vanished) if vanished is not None else None
    logger.info(f"[curated_key_scan] {family}: 일치 {n_m if n_m is not None else 'N/A(T1)'} / "
                f"forward {len(forward)} / lateral {len(lateral)} / "
                f"소멸 {n_v if n_v is not None else 'N/A(T1)'}")
    candidates = []
    for cls, keys in (("forward_candidate", forward), ("lateral_candidate", lateral)):
        for k in keys:
            corp, fy, fp = k[0], k[1], k[2]
            basis = k[3] if has_basis else ""
            candidates.append({
                "family": family, "corp_code": corp, "fiscal_year": fy, "fiscal_period": fp,
                "basis": basis, "classification": cls, "identity_holds": True,
                "detail": _jsonable(detail.get(k, {})),
            })
    for k in (vanished or ()):
        corp, fy, fp = k[0], k[1], k[2]
        basis = k[3] if has_basis else ""
        candidates.append({
            "family": family, "corp_code": corp, "fiscal_year": fy, "fiscal_period": fp,
            "basis": basis, "classification": "vanished_candidate", "identity_holds": None,
            "detail": None,
        })
    return {"family": family, "n_matched": n_m, "n_forward": len(forward),
            "n_lateral": len(lateral), "n_vanished": n_v, "candidates": candidates}


# ══════════════════════════════════════════════════════════════════════════════
#  T2-1. sga_subline — combine.py::_SGA_SUBLINE_OVERRIDE_KEYS
#  (원본: scripts/generate_sga_subline_override_2026-08-15.py)
# ══════════════════════════════════════════════════════════════════════════════
def scan_sga_subline(session) -> dict:
    from fin2.layer3.combine import _SGA_SUBLINE_OVERRIDE_KEYS as registered

    target = []
    for (pid, corp, rcept, basis, tseq, prow, pdepth, plabel, pval, fy, fp) in \
            _operating_expense_parents(session):
        if pval is None:
            continue
        children = _direct_children(session, corp, rcept, basis, tseq, prow, pdepth)
        if not children:
            continue
        labels = [c[0] for c in children]
        has_cogs = any(any(m in lbl for m in _SGA_SUBLINE_COGS_MARKERS) for lbl in labels)
        has_sga = any(any(m in lbl for m in _SGA_MARKERS) for lbl in labels)
        if not (has_cogs and has_sga):
            continue
        child_sum = sum(v for _, v in children if v is not None)
        n_missing = sum(1 for _, v in children if v is None)
        if not (n_missing == 0 and child_sum == pval):
            continue
        sga_children = [(lbl, v) for lbl, v in children if any(m in lbl for m in _SGA_MARKERS)]
        target.append({"key": (corp, fy, fp), "sga_children": sga_children, "basis": basis})

    scan_keys = {t["key"] for t in target}
    detail = {t["key"]: {"sga_children": t["sga_children"], "basis": t["basis"]} for t in target}
    matched, vanished, forward, lateral = _classify_full(scan_keys, set(registered))
    return _result("sga_subline", matched=matched, vanished=vanished, forward=forward,
                    lateral=lateral, detail=detail, has_basis=False)


# ══════════════════════════════════════════════════════════════════════════════
#  T2-2. cogs_additive — combine.py::_COGS_ADDITIVE_OVERRIDE
#  (원본: scripts/generate_cogs_additive_override_2026-08-15.py)
# ══════════════════════════════════════════════════════════════════════════════
def scan_cogs_additive(session) -> dict:
    from fin2.layer3.combine import _COGS_ADDITIVE_OVERRIDE as registered

    mapper = get_mapper()
    by_key: dict = {}
    detail: dict = {}
    for (pid, corp, rcept, basis, tseq, prow, pdepth, plabel, pval, fy, fp) in \
            _operating_expense_parents(session):
        if pval is None:
            continue
        children = _direct_children(session, corp, rcept, basis, tseq, prow, pdepth)
        if not children:
            continue
        labels = [c[0] for c in children]
        has_cogs = any(_COGS_ADDITIVE_MARKER in lbl for lbl in labels)
        has_sga = any(any(m in lbl for m in _SGA_MARKERS) for lbl in labels)
        if not (has_cogs and has_sga):
            continue
        child_sum = sum(v for _, v in children if v is not None)
        n_missing = sum(1 for _, v in children if v is None)
        if not (n_missing == 0 and child_sum == pval):
            continue
        cogs_children = [lbl for lbl, v in children if _COGS_ADDITIVE_MARKER in lbl]
        key = (corp, fy, fp, basis)
        norm_labels = tuple(sorted({norm_label(lbl) for lbl in cogs_children}))
        by_key[key] = norm_labels
        detail[key] = {"cogs_children": cogs_children, "norm_labels": norm_labels}

    override = {}
    for key, labels in by_key.items():
        if len(labels) == 1:
            r = mapper.map(labels[0], fs_section="is")
            if r.confidence >= 0.88 and r.account_code == "is.cogs":
                continue   # single_mapped — 기존 alias 로 이미 정확, override 불필요
        override[key] = labels

    scan_keys = set(override)
    matched, vanished, forward, lateral = _classify_full(scan_keys, set(registered))
    return _result("cogs_additive", matched=matched, vanished=vanished, forward=forward,
                    lateral=lateral, detail=detail, has_basis=True)


# ══════════════════════════════════════════════════════════════════════════════
#  T1-1. trade_payables_additive — combine.py::_TRADE_PAYABLES_ADDITIVE_OVERRIDE
#  face_audit(v3) 의 bs.trade_payables VALUE_DIFF 전수에서, 같은 rcept 의 BS 부채성 라인
#  2개 조합 합이 report_won 과 일치(±tol)하는 후보를 찾는다(원문대조 전 후보 생성용,
#  §4 경고대로 자동반영 금지 — 라벨이 회사마다 달라 일반화 불가).
# ══════════════════════════════════════════════════════════════════════════════
def scan_trade_payables_additive(session, tol: int = 1, max_pool: int = 40) -> dict:
    from fin2.layer3.combine import _TRADE_PAYABLES_ADDITIVE_OVERRIDE as registered

    rows = session.execute(text("""
        SELECT fa.corp_code, fa.fiscal_year, fa.fiscal_period, fa.statement_type AS basis,
               (fd->>'db_won')::bigint AS db_won, (fd->>'report_won')::bigint AS report_won
        FROM face_audit fa
        JOIN LATERAL jsonb_array_elements(fa.fail_detail) fd ON true
        WHERE fa.source_version='v3' AND jsonb_typeof(fa.fail_detail)='array'
          AND fd->>'canonical'='bs.trade_payables' AND fd->>'reason'='VALUE_DIFF'
          AND fd->>'report_won' IS NOT NULL
    """)).fetchall()

    scan_keys = set()
    detail: dict = {}
    for r in rows:
        key = (r.corp_code, r.fiscal_year, r.fiscal_period)   # override 키 shape(basis 없음)
        if key in detail:
            continue   # 같은 (corp,fy,fp) 에 basis 두 개가 각각 fail 이어도 1건만 대표로
        src = session.execute(text("""
            SELECT source_rcepts FROM std_financials_v3
            WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:fp AND statement_type=:b
            LIMIT 1
        """), {"c": r.corp_code, "fy": r.fiscal_year, "fp": r.fiscal_period, "b": r.basis}).fetchone()
        bs_rcept = ((src and src.source_rcepts) or {}).get("BS") if src else None
        if not bs_rcept:
            continue
        pool = session.execute(text("""
            SELECT label_raw, value_won FROM report_lines
            WHERE corp_code=:c AND rcept_no=:rc AND basis=:b AND statement='BS' AND col_index=0
              AND value_won IS NOT NULL
        """), {"c": r.corp_code, "rc": bs_rcept, "b": r.basis}).fetchall()
        cands = [(p.label_raw, p.value_won) for p in pool
                 if any(m in p.label_raw for m in _LIABILITY_LABEL_MARKERS)]
        if not cands or len(cands) > max_pool:   # 병리적으로 큰 표 방어
            continue
        hit = None
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                if abs((cands[i][1] + cands[j][1]) - r.report_won) <= tol:
                    hit = (cands[i], cands[j])
                    break
            if hit:
                break
        if not hit:
            continue
        scan_keys.add(key)
        detail[key] = {"labels": [hit[0][0], hit[1][0]], "values": [hit[0][1], hit[1][1]],
                       "report_won": r.report_won, "db_won": r.db_won, "basis": r.basis}

    forward, lateral = _classify_residual(scan_keys, set(registered))
    return _result("trade_payables_additive", forward=forward, lateral=lateral,
                    detail=detail, has_basis=False)


# ══════════════════════════════════════════════════════════════════════════════
#  T1-2. cogs_concept_mismatch — face_audit.py::_COGS_CONCEPT_MISMATCH_KEYS
#  face_audit(v3) 의 is.cogs VALUE_DIFF 전수 + std_financials_v3.sga 조인으로
#  report_won == db_cogs+db_sga(±tol) 항등식 재확인(원 probe 스크립트와 동일 항등식,
#  corp 제한만 제거).
# ══════════════════════════════════════════════════════════════════════════════
def scan_cogs_concept_mismatch(session, tol: int = 1) -> dict:
    from fin2.audit.face_audit import _COGS_CONCEPT_MISMATCH_KEYS as registered

    rows = session.execute(text("""
        SELECT fa.corp_code, fa.fiscal_year, fa.fiscal_period, fa.statement_type AS basis,
               (fd->>'db_won')::bigint AS db_cogs, (fd->>'report_won')::bigint AS report_won,
               sv.sga AS db_sga
        FROM face_audit fa
        JOIN LATERAL jsonb_array_elements(fa.fail_detail) fd ON true
        LEFT JOIN std_financials_v3 sv
          ON sv.corp_code=fa.corp_code AND sv.fiscal_year=fa.fiscal_year
         AND sv.fiscal_period=fa.fiscal_period AND sv.statement_type=fa.statement_type
        WHERE fa.source_version='v3' AND jsonb_typeof(fa.fail_detail)='array'
          AND fd->>'canonical'='is.cogs' AND fd->>'reason'='VALUE_DIFF'
          AND fd->>'report_won' IS NOT NULL
    """)).fetchall()

    scan_keys = set()
    detail: dict = {}
    for r in rows:
        if r.db_sga is None or r.report_won is None or r.db_cogs is None:
            continue
        if abs(r.report_won - (r.db_cogs + r.db_sga)) > tol:
            continue
        key = (r.corp_code, r.fiscal_year, r.fiscal_period, r.basis)
        scan_keys.add(key)
        detail[key] = {"db_cogs": r.db_cogs, "db_sga": r.db_sga, "report_won": r.report_won}

    forward, lateral = _classify_residual(scan_keys, set(registered))
    return _result("cogs_concept_mismatch", forward=forward, lateral=lateral,
                    detail=detail, has_basis=True)


# ══════════════════════════════════════════════════════════════════════════════
#  드라이버
# ══════════════════════════════════════════════════════════════════════════════
def run_all_scans(notify: bool = True) -> dict:
    """4-family 전수 스캔 → curated_key_candidates 적재(①일치는 로그만) → 후보>0 이면 알림."""
    with get_session() as session:
        results = [
            scan_sga_subline(session),
            scan_cogs_additive(session),
            scan_trade_payables_additive(session),
            scan_cogs_concept_mismatch(session),
        ]
        all_candidates = [c for res in results for c in res["candidates"]]
        if all_candidates:
            now = datetime.utcnow()
            values = [{**c, "scan_version": SCAN_VERSION, "last_seen_at": now}
                      for c in all_candidates]
            stmt = insert(CuratedKeyCandidate).values(values)
            upd = {col: stmt.excluded[col] for col in
                   ("classification", "identity_holds", "detail", "last_seen_at", "scan_version")}
            stmt = stmt.on_conflict_do_update(
                index_elements=["family", "corp_code", "fiscal_year", "fiscal_period", "basis"],
                set_=upd)
            session.execute(stmt)
            session.commit()

    total_new = sum(r["n_forward"] + r["n_lateral"] for r in results)
    total_vanished = sum(r["n_vanished"] or 0 for r in results)
    summary = " / ".join(
        f"{r['family']}: fwd{r['n_forward']}+lat{r['n_lateral']}"
        + (f"+van{r['n_vanished']}" if r["n_vanished"] is not None else "")
        for r in results)
    logger.info(f"[curated_key_scan] 전체 요약 — 신규후보 {total_new}건, 소멸후보 {total_vanished}건 | {summary}")

    if notify and (total_new + total_vanished) > 0:
        from scripts.notify import notify_macos
        notify_macos("Gate B curated 키 재생성기",
                     f"신규후보 {total_new}건 · 소멸후보 {total_vanished}건 — "
                     f"curated_key_candidates 리뷰 필요. {summary}")
    return {"total_new": total_new, "total_vanished": total_vanished, "by_family": results}


if __name__ == "__main__":
    from collector.db import init_db
    init_db()
    run_all_scans()
