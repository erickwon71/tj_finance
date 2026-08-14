"""Layer 3 combination engine — PROTOTYPE (L3-1).

Assembles std metrics for one (corp, fiscal_year, fiscal_period, basis) directly
from Layer 2 `report_lines`, reusing the label catalog (AccountMapper) validated
by the Option-A probe (docs/qa/layer3_option_a_probe_2026-07-22.md, DIFF≈0).

Design (hybrid, per docs/plans/layer3_rebuild_plan_2026-07-22.md §1):
  - Port the old chain's conflict resolution (build._resolve / _reduce_conflict)
    — single→confirm, else keep strictest mapping stage, else auto-reduce, else
    HOLD (missing > wrong). No max-abs, no guessing.
  - Adapt signals: old chain discriminated non-current / broad accounts by acode;
    report_lines has no acode, so we use `label_raw` for those regex checks.
  - Carry structural signals (node_role, section_path, table_seq) on every
    candidate so residual conflicts can be analysed and a node_role-based rule
    added *from evidence* in a measured second iteration (not blind).

Scope of the prototype: DIRECT_MAP metrics only (the 6 probe metrics are all
direct-mapped). Additive/derived rules (D&A, debt sums, EBITDA…) come later.

Read-only: this module never writes to the DB.
"""
from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache

from sqlalchemy import text

from parser.common.account_mapper import get_mapper
from fin2.standardize.rules import (DIRECT_MAP, CONSUMED_CANON, StdContext,
                                    rule_additive_capex, rule_derive_fcf,
                                    rule_derive_net_debt, rule_additive_da,
                                    rule_derive_ebitda, ADDITIVE_CANON)
from fin2.layer3.note_da import note_da_canonicals
from parser.common.note_labels import classify_da_label
from fin2.layer3.industry_profiles import (
    apply_revenue_profile, norm as _norm_label, NO_REVENUE_CORPS,
)

# grand-total revenue labels (normalized) that outrank component labels in is.revenue
# conflicts (증권/지주: 영업수익 total vs 수수료수익 component).
_REVENUE_TOTAL_LABELS = frozenset({"매출액", "영업수익", "매출", "순매출액"})

# ★revenue grand-total override(2026-08-13): a blanket "_REVENUE_TOTAL_LABELS wins"
# rule cannot be generalized — measured against the full report_lines population
# (report_lines is static, unaffected by backfills) it regresses 303 currently-PASS
# rows for only 8 genuine fixes (38:1). SBI인베스트먼트(00156910) etc. are the
# opposite case: their component label ('수수료수익') already matches report_won,
# the grand total includes valuation items report_won excludes. Only corps where
# source-XML comparison confirmed the grand total IS the answer go here.
# docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md §2-1/§3-1
_REVENUE_TOTAL_OVERRIDE_CORPS = frozenset({
    "00159254",   # 한국전자홀딩스
    "00340096",   # 미래에셋벤처투자
})

# ★trade_payables parent(P) override(2026-08-13): a blanket "node_role='P' wins" rule
# cannot be generalized either — measured regression 11,761 currently-PASS rows for
# only 32 genuine fixes (368:1). Most corps' narrow child value ('단기매입채무' etc.)
# already matches report_won (consistent with _NARROW_PREFER's existing design intent).
# Only corps where report_won/source comparison confirmed the parent total IS the
# answer go here.
# docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md §2-2/§3-2
_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS = frozenset({
    "00164502",   # 현대공업
    "00203847",   # 국일신동
    "00210856",   # 코아스
    "00304076",   # 케이엔솔
    "01310269",   # IPARK현대산업개발
    # ★확장(2026-08-14, docs/qa/gate_b_faila_residual_triage_2026-08-14.md §2): 원문
    # XBRL 직접대조로 확인(3개사 전부, 여러 기간에 걸쳐) — 부모 라인
    # ACODE="ifrs-full_TradeAndOtherCurrentPayables"(=report_won), 자식 라인
    # ACODE="ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers"(=db_won, std_v3가
    # 잘못 채택). 세 회사 모두 동일한 ACODE 쌍 — 위 5개사보다 더 명확한 구조적 근거.
    "00105466",   # KCC건설 (6개 기간, 2024FY~2026Q1, 원문확인: 20250320001281.xml:7693-7716)
    "00149239",   # 조일알미늄 (2개 기간, 원문확인: 20260312000761.xml:4577-4584)
    "00353878",   # 다스코 (연결+별도, 원문확인: 20260515001729.xml:4672-4678)
})

# ★trade_payables additive override(2026-08-14, period-scoped): 원문 XBRL 직접대조로
# 확인(둘 다 report_lines 텍스트추출로는 안 잡히는 위치에 있는 진짜 fact와 정확히
# 일치 — ifrs-full_TradeAndOtherPayablesUndiscountedCashFlows[MaturityAxis=1년이내]
# 또는 ifrs-full_TradeAndOtherCurrentPayables). BS 본문엔 매입채무+형제 유동채무
# 라인이 둘 다 이미 존재하지만 결합 총계(P) 라인 자체가 없는 레이아웃 — 그 두
# 라인의 합이 report_won. 라벨이 회사마다 전부 달라 일반화 규칙 금지(위 parent
# override와 같은 위험).
#
# ★키를 corp 단독이 아니라 (corp, fy, period)로 좁힌 이유(실측으로 발견한 함정):
# 최초 구현을 corp 단독 키로 5개사 전체 이력에 적용해 scoped 백필+Gate B recheck
# 했더니, 목표했던 기간(대부분 FY2025~2026Q1)은 고쳐졌지만 같은 회사의 과거 모든
# 분기(2010~2024, LG화학만 100건+)가 새로 fail_b로 대규모 회귀했다 — "두 라인 합
# = report_won"은 원문대조로 확인한 그 특정 필링(들)에서만 성립하고, 같은 회사의
# 다른 기간엔 성립하지 않는다(예: LG화학 2010 연결 report_won=1.30조인데 두 라인
# 합=2.12조). 그래서 아래는 원문/report_won 재대조로 개별 확인된 정확한
# (corp, fiscal_year, fiscal_period) 조합만 등재한다 — corp 하나가 늘 이 관계를
# 만족한다고 가정하지 않는다. basis(연결/별도)는 _resolve() 호출 자체가 이미
# basis별로 분리돼 있어 별도 키가 필요 없다.
# docs/plans/gate_b_faila_trade_payables_additive_design_2026-08-14.md (원설계, corp
# 단독 키 — 폐기) + 이 세션 재검증(period-scoped로 교체).
_TRADE_PAYABLES_ADDITIVE_OVERRIDE = {
    ("00356361", 2025, "FY"): ("매입채무", "기타지급채무"),        # LG화학
    ("00356361", 2026, "Q1"): ("매입채무", "기타지급채무"),        # LG화학
    ("00113544", 2025, "FY"): ("매입채무", "기타채무"),             # 대한화섬
    ("00109310", 2025, "FY"): ("유동매입채무", "단기미지급금"),     # 대동기어
    ("00138446", 2025, "FY"): ("유동매입채무", "기타유동금융부채"), # 아가방컴퍼니
    ("01093007", 2025, "FY"): ("매입채무", "기타채무"),             # LS에코에너지
}


@lru_cache(maxsize=200_000)
def _map_label(label_raw: str, fs: str | None):
    """Cached AccountMapper.map — the same face labels (자산총계·매출액…) recur across
    every filing, and map() runs fuzzy Jaro-Winkler over all aliases, so caching by
    (label_raw, fs) is the dominant speedup for the full std_v3 build. Deterministic."""
    return get_mapper().map(label_raw, fs_section=fs)

# mapping-stage provenance rank (exact/normalized beat fuzzy). Mirrors build._STAGE_RANK.
_STAGE_RANK = {"exact": 3, "normalized": 2, "guard": 2, "fuzzy": 1, None: 0}

_CONFLICT_EPS = 0.001
_CURRENT_STRICT = {"bs.trade_receivables", "bs.trade_payables",
                   "bs.short_term_debt", "bs.current_bonds"}
_NONCURRENT_RE = re.compile(r"장기|비유동")
_NARROW_PREFER = {"bs.trade_receivables", "bs.trade_payables"}


def _is_noncurrent(row: dict) -> bool:
    """True if a _CURRENT_STRICT candidate row is a non-current variant.

    Checks BOTH label_raw and section_path against _NONCURRENT_RE. label_raw alone is
    not enough: some filings place a non-current '매입채무및기타채무' row under
    section_path='부채>비유동부채' with the exact same label text as its current
    counterpart (no '장기'/'비유동' wording in the label itself) — e.g. 경남제약/00307028
    2024FY, docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md ③. section_path carries the
    유동/비유동 classification the label text sometimes omits.
    """
    return bool(_NONCURRENT_RE.search(row.get("label_raw") or "")
                or _NONCURRENT_RE.search(row.get("section_path") or ""))
_BROAD_RE = re.compile(r"및기타|및 기타|AndOther")
# a BS grand-total canonical must not be sourced from a fiduciary/trust-account
# sub-statement embedded in the same filing (banks commonly attach a 신탁계정 balance
# sheet alongside their own — legitimately '자산총계'==부채총계' there, no equity, since
# a trust account holds no residual interest). Such a table's clean-label '자산총계' can
# reach stage='exact' while the real statement's letter-spaced '자    산    총    계'
# (older filing format) only reaches 'normalized', so without an explicit guard the
# trust table's exact match wins over the real one.
# ★ Deliberately narrow and self-verifying (not a blanket table_seq=0 preference —
# that was tried and reverted after a verified regression: 네오셈/01170865 has table_seq=1
# as its correct current-period 별도 BS with table_seq=0 being a stale/mismatched table,
# i.e. table order alone is not a reliable primary-statement signal). A table_seq is only
# excluded when, from *its own* candidates, total_assets == total_liabilities exactly AND
# it has no total_equity candidate at all — the trust-account signature specifically,
# not "a second BS-shaped table exists" in general.
# Real 실측 (2026-08-09): 제주은행(00148832)·기업은행(00149646) — see docs/plans/
# std_v3_dq_shares_period_backfill_todo_2026-08-09.md.
_BS_GRAND_TOTAL = {"bs.total_assets", "bs.total_liabilities", "bs.total_equity"}

# controlling_ni/noncontrolling_ni: the alias catalog has bare labels ('지배기업
# 소유주지분'·'비지배지분') that legitimately appear in BOTH the '당기순이익의 귀속'
# section (wanted) and the '총포괄손익의 귀속' section (OCI-inclusive, wrong concept) —
# both exact-match the same canonical. _resolve()'s normal stage-rank shortcut (below)
# can pick the wrong one outright when the two candidates' stages differ (e.g. a
# footnote suffix drops the right one to 'normalized'/'fuzzy' while the wrong one stays
# 'exact') — its top_vals then collapses to a single (wrong) value and never reaches
# `conflicts`, so `_resolve_ni_attribution`'s identity check (already proven correct,
# including on the two known label-swap filings — see that function's docstring) never
# gets a chance to run. For these two canonicals only, skip the stage-rank shortcut and
# always route a multi-value split to `conflicts` so the identity check always fires.
# docs/plans/std_v3_controlling_ni_oci_section_fix_design_2026-08-12.md §2.
_NI_ATTRIBUTION_CANON = {"is.controlling_ni", "is.noncontrolling_ni"}


def _trust_account_table_seqs(cands: dict[str, list[dict]]) -> set:
    """table_seq values whose own total_assets == total_liabilities with no total_equity
    candidate at all — see _BS_GRAND_TOTAL comment. Computed once per _resolve() call."""
    ta = cands.get("bs.total_assets", [])
    tl = cands.get("bs.total_liabilities", [])
    if not ta or not tl:
        return set()
    ta_by_seq = {r["table_seq"]: r["value"] for r in ta}
    tl_by_seq = {r["table_seq"]: r["value"] for r in tl}
    eq_seqs = {r["table_seq"] for r in cands.get("bs.total_equity", [])}
    return {seq for seq, v in ta_by_seq.items()
            if tl_by_seq.get(seq) == v and seq not in eq_seqs}

# statement -> AccountMapper fs_section hint
_FS = {"IS": "is", "BS": "bs", "CF": "cf"}
# canonical prefix -> statement it is read from
_STMT_OF_PREFIX = {"bs": "BS", "is": "IS", "cf": "CF"}


def _period_filings(session, corp: str, fy: int, period: str) -> list[str]:
    """All rcept_no for a (corp, fy, period), most-final/most-recent first."""
    rows = session.execute(text("""
        SELECT rcept_no FROM filings
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
        ORDER BY is_final DESC, filed_at DESC NULLS LAST, rcept_no DESC
    """), {"c": corp, "y": fy, "p": period}).fetchall()
    return [r[0] for r in rows]


def _period_filings_chrono(session, corp: str, fy: int, period: str) -> list[tuple[str, bool]]:
    """(rcept_no, is_amendment) for a period, ORIGINAL first (filed_at ASC).
    Only filings that have report_lines (a base/overlay must have extractable rows)."""
    rows = session.execute(text("""
        SELECT f.rcept_no, COALESCE(f.is_amendment, false)
        FROM filings f
        WHERE f.corp_code=:c AND f.fiscal_year=:y AND f.fiscal_period=:p
          AND EXISTS (SELECT 1 FROM report_lines rl WHERE rl.rcept_no=f.rcept_no)
        ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC
    """), {"c": corp, "y": fy, "p": period}).fetchall()
    return [(r[0], bool(r[1])) for r in rows]


# cell identity for delta-patch (measured 2026-07-22: SAME 90.9% under this key).
_CELL_KEY = ("statement", "basis", "col_index", "section_path", "label_raw")


def build_merged_lines(session, corp: str, fy: int, period: str) -> list[dict]:
    """★정본 정책(사용자 2026-07-22): 최초등록본 + 순차 델타 패치.

    Base = the ORIGINAL filing (최초등록본). For each 기재정정 (amendment) in
    chronological order, overlay ONLY the cells whose value differs (edit) or that
    are new (add); cells the amendment does not touch keep the original. Every
    patched/added cell is marked (`amended=True`, `amended_by=<rcept>`,
    `amend_chain=[...]`) so "기재정정 반영" provenance flows downstream.

    Value semantics = P1 (final = as-restated), but constructed as original+deltas
    so partial amendments (첨부정정 / 부분 본문정정) never drop the untouched base.

    Cell identity = (statement, basis, col_index, section_path, label_raw). Measured
    alignment: SAME 90.9% / CHANGED 6.4% / ONLY_ORIG 1.2% / ONLY_AMEND 1.5% over 60
    original↔amendment pairs. ONLY_ORIG (amendment not re-listing a base row) is
    KEPT (no deletion) — safe for the 6 top-level metrics (stable labels); label
    drift on detailed line items is a documented refinement (may double-count a
    renamed detail row, does not affect the top-level metrics).

    Returns a list of merged cell dicts (col_index=0 only), each with:
      statement, basis, col_index, section_path, label_raw, value_won, node_role,
      table_seq, is_cumulative, source_rcept, amended(bool), amended_by, amend_chain.
    """
    chrono = _period_filings_chrono(session, corp, fy, period)
    merged: dict[tuple, dict] = {}
    for i, (rcept, is_amend) in enumerate(chrono):
        # ★ base = the FIRST filing (chrono). Its cells are never "amended" even if that
        # filing is itself a [기재정정] (no earlier original to patch → it IS the base).
        # Only LATER filings (i>0) patch a value or add a new row → amended=True.
        is_base = (i == 0)
        rows = session.execute(text("""
            SELECT statement, basis, col_index, section_path, label_raw, value_won,
                   node_role, table_seq, COALESCE(is_cumulative, false) AS is_cum
            FROM report_lines
            WHERE rcept_no=:r AND col_index=0 AND value_won IS NOT NULL
              -- F2 가드(2026-07-31): 헤더 규칙에 걸린 행은 기본 제외(계층2 가 이제 버리지
              -- 않고 header_hint 로 전사한다). 본문 경로는 아직 전사하지 않지만 같은 계약을
              -- 미리 건다 — 나중에 켤 때 계층3 을 다시 손대지 않기 위해서다.
              AND header_hint IS NULL
              -- ★외화 가드(2026-08-05): unit_source='fx_declared' 인 행의 value_won 은
              -- 원화가 아니라 **표시통화 금액 그대로**다(아남전자 = USD). 여기서 막지 않으면
              -- USD 금액이 원화 집계에 그대로 섞인다 — 유실이 아니라 오염이다.
              -- 외화 재무제표를 소비하려면 report_tables.currency 를 읽어 통화를 인지하는
              -- 별도 경로를 만들어야 한다(환산은 계층3 의 판단이지 계층2 가 할 일이 아니다).
              AND COALESCE(unit_source, '') <> 'fx_declared'
        """), {"r": rcept}).fetchall()
        for (statement, basis, col_index, section_path, label_raw, value_won,
             node_role, table_seq, is_cum) in rows:
            key = (statement, basis, col_index, section_path, label_raw)
            cell = {
                "statement": statement, "basis": basis, "col_index": col_index,
                "section_path": section_path, "label_raw": label_raw,
                "value_won": int(value_won), "node_role": node_role,
                "table_seq": table_seq, "is_cumulative": bool(is_cum),
            }
            if key not in merged:
                # first occurrence. From the base filing → not amended. From a later
                # filing → a row added by that amendment → amended.
                cell["source_rcept"] = rcept
                cell["amended"] = not is_base
                cell["amended_by"] = None if is_base else rcept
                cell["amend_chain"] = [] if is_base else [rcept]
                merged[key] = cell
            else:
                base = merged[key]
                if not is_base and int(value_won) != base["value_won"]:
                    # value edit by a later filing → patch + mark
                    cell["source_rcept"] = rcept
                    cell["amended"] = True
                    cell["amended_by"] = rcept
                    cell["amend_chain"] = base["amend_chain"] + [rcept]
                    merged[key] = cell
                # equal value, or same base filing duplicate → keep base (no-op)
    return list(merged.values())


def select_canonical_rcept(session, corp: str, fy: int, period: str) -> str | None:
    """L3-1b: pick ONE canonical filing (rcept_no) for a period — the most-final one.

    Kept for diagnostics/back-compat. Prefer select_canonical_rcepts() for
    combine: the single-filing choice is unsafe when the final filing is a
    첨부정정 (attachment-only amendment, body identical to original → no financial
    statements in report_lines) or a 본문정정 whose statements were not extracted.
    """
    fl = _period_filings(session, corp, fy, period)
    return fl[0] if fl else None


def select_canonical_rcepts(session, corp: str, fy: int, period: str,
                            statements=("BS", "IS", "CF")) -> dict[str, str]:
    """L3-1b (per-statement): resolve each statement to the newest filing that
    ACTUALLY contains report_lines for it.

    Rationale (measured 2026-07-22): filing selection must be per-statement, not
    per-filing. The final filing (is_final) can be a 첨부정정 (body identical → no
    statements in report_lines; 321 cases) or a partially/never-extracted 본문정정
    (125). Blindly reading only is_final would yield empty/MISSING. Walking the
    filing chain (is_final → … → original) per statement recovers 307/321
    attachment amendments (use the original body — identical by definition) and
    17/125 body amendments. The rest have no report_lines in any filing = genuine
    data gap (PDF-only / un-extracted), surfaced as MISSING for L3-2 / PDF pass.

    This mirrors the old chain, which stored bs_rcept / is_rcept / cf_rcept
    separately — per-statement source resolution is the proven design.

    Returns {statement: rcept_no} for statements that have report_lines somewhere
    (statements with no data anywhere are simply absent from the dict).
    """
    filings = _period_filings(session, corp, fy, period)
    out: dict[str, str] = {}
    for statement in statements:
        for rcept in filings:  # most-final first
            has = session.execute(text("""
                SELECT 1 FROM report_lines
                WHERE rcept_no=:r AND statement=:s LIMIT 1
            """), {"r": rcept, "s": statement}).fetchone()
            if has:
                out[statement] = rcept
                break
    return out


_INDUTY_CACHE: dict[str, str | None] = {}


def _get_induty(session, corp: str) -> str | None:
    """Cached corp → induty_code (KSIC) lookup (once per corp across the full build)."""
    if corp not in _INDUTY_CACHE:
        r = session.execute(text(
            "SELECT induty_code FROM corporations WHERE corp_code=:c"), {"c": corp}).fetchone()
        _INDUTY_CACHE[corp] = r[0] if r else None
    return _INDUTY_CACHE[corp]


def _reduce_conflict(canon: str, top: list[dict]) -> int | None:
    """Confirm a split top-candidate set WITHOUT guessing, else None (hold).

    Ported from build._reduce_conflict; the acode-based checks are re-expressed
    against label_raw because report_lines carries no acode.
    """
    rows = top
    # narrow-prefer: drop broad '및기타/AndOther' accounts when a pure one exists
    if canon in _NARROW_PREFER:
        narrow = [r for r in rows if not _BROAD_RE.search(r.get("label_raw") or "")]
        if narrow:
            rows = narrow
    # current-strict: a current canonical must not absorb non-current (장기/비유동) rows
    if canon in _CURRENT_STRICT:
        cur = [r for r in rows if not _is_noncurrent(r)]
        if cur:
            rows = cur
    # revenue grand-total preference: a grand-total label (매출액/영업수익) outranks a
    # component label (수수료수익/이자수익/보험영업수익…) that also maps to is.revenue.
    # Fixes securities/holdings where 영업수익 total conflicts with 수수료수익 component
    # (both top-level exact). Insurers under IFRS17 have no such total (or =0) → unaffected.
    if canon == "is.revenue":
        grand = [r for r in rows
                 if _norm_label(r.get("label_raw")) in _REVENUE_TOTAL_LABELS and r["value"]]
        if grand:
            gvals = {r["value"] for r in grand}
            if len(gvals) == 1:
                return next(iter(gvals))
            rows = grand  # multiple grand totals disagree → decide among them below
    def _eps_dup(candidate_vals):
        """Near-equal same-sign values (e.g. original vs restated) -> max-abs, else None."""
        nums = [v for v in candidate_vals if v is not None]
        if len(nums) < 2:
            return None
        hi = max(nums, key=abs)
        lo = min(nums, key=abs)
        if hi == 0 or (hi > 0) != (lo > 0):
            return None
        return hi if abs(hi - lo) / abs(hi) <= _CONFLICT_EPS else None

    vals = {r["value"] for r in rows}
    if len(vals) == 1:
        return next(iter(vals))
    # EPS approx-dup FIRST: an immaterial restatement diff (original vs amended) resolves
    # to max-abs, so the shallowest-depth rule below doesn't override it on a rounding gap.
    dup = _eps_dup(vals)
    if dup is not None:
        return dup
    # shallowest-depth preference: DIRECT_MAP canonicals are statement totals, so the
    # least-nested line outranks deeper sub-items that map to the same canonical
    # (e.g. 'Ⅰ.영업수익' total vs its '보험료수익' children; or IFRS17 '보험서비스수익'
    # at 보험손익 depth-1 vs '수수료수익' at 투자손익>… depth-2). Only fires on an existing
    # conflict, so it can fill a held NULL but never regress a match.
    def _depth(r):
        p = (r.get("section_path") or "").strip()
        return 0 if not p else p.count(">") + 1
    # exclude 0-valued candidates: an IFRS17 empty top-level header (e.g. '영업수익'=0
    # above 보험손익/투자손익 sections) must not win as a shallowest "total".
    pool = [r for r in rows if r["value"] not in (0, None)]
    if not pool:
        return None
    pvals = {r["value"] for r in pool}
    if len(pvals) == 1:
        return next(iter(pvals))          # a single distinct non-zero value
    min_depth = min(_depth(r) for r in pool)
    shallow = [r for r in pool if _depth(r) == min_depth]
    svals = {r["value"] for r in shallow}
    if len(svals) == 1:
        return next(iter(svals))
    return _eps_dup(svals)  # shallowest still split → EPS among them, else hold


def _resolve(cands: dict[str, list[dict]], corp: str | None = None,
             fy: int | None = None, period: str | None = None):
    """{canonical: [candidate]} -> (confirmed {canonical: value}, conflicts {canonical: [candidate]}).

    Ported from build._resolve. Conflicts are HELD (not filled) and returned for
    analysis (only for consumed canonicals, to avoid lineage noise).

    corp: current corp_code, needed only to gate the curated overrides
    (_REVENUE_TOTAL_OVERRIDE_CORPS / _TRADE_PAYABLES_PARENT_OVERRIDE_CORPS) below.
    fy/period: current fiscal_year/fiscal_period, needed only to gate
    _TRADE_PAYABLES_ADDITIVE_OVERRIDE (period-scoped, not corp-blanket — see its
    comment for why).
    """
    confirmed: dict[str, int] = {}
    conflicts: dict[str, list[dict]] = {}
    trust_seqs = _trust_account_table_seqs(cands)
    for c, rows in cands.items():
        # BS grand-total: drop candidates from a confirmed trust-account sub-statement
        # (see _BS_GRAND_TOTAL / _trust_account_table_seqs above) before stage ranking, so
        # its clean-label 'exact' match can never outrank the real statement's
        # letter-spaced 'normalized' one. Only fires on the specific trust-account
        # signature — never a blanket table_seq preference.
        if c in _BS_GRAND_TOTAL and trust_seqs:
            filtered = [r for r in rows if r.get("table_seq") not in trust_seqs]
            if filtered:
                rows = filtered
        # current-strict canonicals (trade_payables 등): drop non-current (장기/비유동)
        # candidates *before* stage ranking, not only inside _reduce_conflict(). A
        # non-current row can legitimately land on a higher mapping stage than the
        # correct current row (e.g. '장기매입채무및기타채무' is a registered exact alias
        # while '매입채무 및 기타유동채무' only reaches 'normalized' after whitespace
        # normalization) — when that happens top_vals below collapses to the single
        # (wrong) non-current value and _reduce_conflict() never runs at all, since it's
        # only invoked on a genuine top-stage tie. Fixes trade_payables near-zero fail_a
        # (52 rows/21 corps, 경남제약 00307028 등) — docs/qa/
        # gate_b_v3_fail_a_784_triage_2026-08-13.md ③. Only fires when a current-labeled
        # candidate actually exists; if every candidate is non-current (or unlabeled),
        # rows is left untouched — no current period can end up MISSING because of this.
        if c in _CURRENT_STRICT:
            cur_rows = [r for r in rows if not _is_noncurrent(r)]
            if cur_rows:
                rows = cur_rows
        # curated overrides (2026-08-13, see the two frozenset comments above): apply
        # BEFORE stage ranking, same reason as the _CURRENT_STRICT filter just above —
        # a component/child label commonly reaches stage='exact' (clean registered
        # alias) while the parent/total label only reaches 'normalized' (needs
        # whitespace/numbering normalization), so top_vals below would otherwise
        # collapse to the (curated-wrong) child value before _reduce_conflict() ever runs.
        if c == "is.revenue" and corp in _REVENUE_TOTAL_OVERRIDE_CORPS:
            grand = [r for r in rows
                     if _norm_label(r.get("label_raw")) in _REVENUE_TOTAL_LABELS and r["value"]]
            if grand:
                rows = grand
        if c == "bs.trade_payables" and corp in _TRADE_PAYABLES_PARENT_OVERRIDE_CORPS:
            parents = [r for r in rows if r.get("node_role") == "P" and r["value"]]
            if parents:
                rows = parents
        if c == "bs.trade_payables" and (corp, fy, period) in _TRADE_PAYABLES_ADDITIVE_OVERRIDE:
            want = _TRADE_PAYABLES_ADDITIVE_OVERRIDE[(corp, fy, period)]
            # ★the second (sibling) label maps to its OWN canonical (e.g. '기타지급채무'
            # -> bs.other_current_payables), never bs.trade_payables — the AccountMapper
            # alias table routes it there before _resolve() ever sees it (verified: LG화학
            # 실측, _map_label('기타지급채무','bs') -> account_code='bs.other_current_payables').
            # So `rows` (this canonical's own candidates) never contains it; must search
            # across every canonical's candidate list in `cands`, not just `rows`.
            all_rows = [r for rs in cands.values() for r in rs]
            picked = {}
            for r in all_rows:
                if _is_noncurrent(r):
                    continue
                label = _norm_label(r.get("label_raw"))
                for w in want:
                    if w not in picked and label.startswith(w):
                        picked[w] = r["value"]
            if len(picked) == len(want) and all(v is not None for v in picked.values()):
                confirmed[c] = sum(picked.values())
                continue
        # 가산 계열(ADDITIVE_CANON)은 한 canonical 에 여러 행이 정상적으로 대응한다
        # (cf.depreciation ← '감가상각비' + '투자부동산감가상각비'). 단일값 전제로 충돌
        # 판정하면 canonical 이 통째로 폐기되므로, 선언된 계열만 합산한다.
        # 성격 선언은 fin2/standardize/rules.py ADDITIVE_CANON 참조.
        if c in ADDITIVE_CANON:
            # ★합산이라고 품질 게이트를 건너뛰면 안 된다. 다만 어떤 게이트를 쓸지가 관건이다:
            #   · stage 로 거르면 너무 뭉툭하다 — 실측 OVER 32→8 이지만 정상 행이 잘려 MISSING 3→57
            #     (cf.depreciation 의 [exact]감가상각비 옆 [normalized]투자부동산감가상각비가 탈락).
            #   · 섹션(투자/재무활동)만 거르면 영업활동 안의 오매칭을 못 잡는다
            #     (실측 00102618: [fuzzy]'사용권자산손상차손'이 cf.rou_depreciation 에 붙음).
            #   → **의미 기반 라벨 가드**를 쓴다. classify_da_label 은 '손상차손'·'대손상각'·
            #     '누계액'·'상각후원가'를 배제하고 '유형자산의 증가'(=CAPEX)도 D&A 로 보지 않는다.
            #     본문과 주석이 **같은 라벨 어휘**를 공유하게 되는 이점도 있다.
            #   ※ 이 가드는 D&A 계열 전용이다. ADDITIVE_CANON 에 다른 계열(capex 등)을 넣으려면
            #     계열별 가드를 함께 선언해야 한다.
            total, seen = 0, set()
            for r in rows:
                if classify_da_label(r.get("label_raw") or "") is None:
                    continue
                v = r.get("value")
                if v is None:
                    continue
                key = ((r.get("label_raw") or "").strip(), v)
                if key in seen:      # 정정 병합으로 같은 셀이 중복될 수 있다
                    continue
                seen.add(key)
                total += abs(v)
            if total:
                confirmed[c] = total
            continue
        # is.controlling_ni/is.noncontrolling_ni: never let the stage-rank shortcut
        # confirm a split outright — always hold it as a conflict so
        # _resolve_ni_attribution (called right after _resolve()) gets a chance to
        # disambiguate via the net_income identity. See _NI_ATTRIBUTION_CANON above.
        if c in _NI_ATTRIBUTION_CANON:
            vals = {r["value"] for r in rows}
            if len(vals) == 1:
                confirmed[c] = next(iter(vals))
            else:
                conflicts[c] = sorted(rows, key=lambda r: (r["value"] is None, r["value"]))
            continue
        vals = {r["value"] for r in rows}
        if len(vals) == 1:
            confirmed[c] = next(iter(vals))
            continue
        best = max(_STAGE_RANK.get(r.get("stage"), 0) for r in rows)
        top = [r for r in rows if _STAGE_RANK.get(r.get("stage"), 0) == best]
        top_vals = {r["value"] for r in top}
        if len(top_vals) == 1:
            confirmed[c] = next(iter(top_vals))
            continue
        reduced = _reduce_conflict(c, top)
        if reduced is not None:
            confirmed[c] = reduced
            continue
        if c in CONSUMED_CANON:
            conflicts[c] = sorted(top, key=lambda r: (r["value"] is None, r["value"]))
    return confirmed, conflicts


def _top_stage_corroborated(rows: list[dict]):
    """>=2 raw candidates independently reach the single highest mapping stage AND agree
    on one value -> trust it. Phase 2 verification (2026-08-12, design doc §4-2-2) swept
    the full known-bug population (404 fail_a rows) and found this pattern in **zero** of
    them — the bug there is always the opposite shape (exactly one row at top stage,
    outranking a differing lower-stage one; see _resolve_ni_attribution docstring). This
    fires only as the fallback below, after the identity check has already failed or
    can't run, so it never overrides an identity-confirmed answer.

    Concretely this recovers the case where OCI happens to be ~0 for the period: the
    '당기순이익의 귀속' and '포괄손익의 귀속' sections then legitimately report the same
    number at the same (best) stage — two independent extractions agreeing is itself the
    corroboration, no need to know which section is which."""
    if len(rows) < 2:
        return None
    best = max(_STAGE_RANK.get(r.get("stage"), 0) for r in rows)
    top = [r for r in rows if _STAGE_RANK.get(r.get("stage"), 0) == best]
    if len(top) < 2:
        return None
    top_vals = {r["value"] for r in top}
    return next(iter(top_vals)) if len(top_vals) == 1 else None


_NI_IDENTITY_EPS = 2   # won tolerance for the identity match below (§C) — real filings
                       # occasionally carry a 1-won rounding gap between separately
                       # printed cells (measured, e.g. 01025644 2024Q1); negligible next
                       # to any realistic net-income magnitude, so it can't manufacture a
                       # false unique match on its own.


def _derive_net_income_from_ebt(cands: dict):
    """§A fallback anchor: when is.net_income has NO raw candidate at all (the total line
    is simply absent from this filing's body — measured ~12% of the still-held PASS
    sample, e.g. 00107987 2022FY), derive it as EBT − tax_expense for the sole purpose of
    anchoring the identity check below. Only fires when both are single, unambiguous
    candidates (never guesses among a split). Does NOT write into `confirmed` — net_income
    confirmation itself is out of this fix's scope, this value is only used locally here."""
    ebt = cands.get("is.ebt", [])
    tax = cands.get("is.tax_expense", [])
    if len(ebt) == 1 and len(tax) == 1:
        return ebt[0]["value"] - tax[0]["value"]
    return None


def _match_ni_identity(cni_vals: set, nci_vals: set, net_income: int):
    """cni × nci pair whose sum matches net_income, exact first, else (§C) within
    _NI_IDENTITY_EPS — but only if the epsilon relaxation still yields a UNIQUE pair.
    Multiple exact matches (a real ambiguity, e.g. two candidate pairs both landing on
    net_income by coincidence) short-circuits straight to "no answer" without trying
    epsilon, since relaxing further can only make that ambiguity worse."""
    exact = {(c, n) for c in cni_vals for n in nci_vals if c + n == net_income}
    if len(exact) == 1:
        return next(iter(exact))
    if exact:
        return None
    near = {(c, n) for c in cni_vals for n in nci_vals if abs(c + n - net_income) <= _NI_IDENTITY_EPS}
    return next(iter(near)) if len(near) == 1 else None


def _resolve_ni_attribution(cands: dict, confirmed: dict, conflicts: dict) -> None:
    """2nd pass (Phase B, docs/plans/std_v3_controlling_ni_gap_fix_plan_2026-08-08.md §3-2):
    re-select a held is.controlling_ni conflict via the accounting identity
    controlling_ni + noncontrolling_ni = net_income, falling back to same-stage
    cross-candidate corroboration (_top_stage_corroborated) when that identity can't run
    or can't disambiguate.

    Root cause (§1-B/§1-B-부록): the alias catalog has bare labels ('지배기업
    소유주지분'·'비지배지분') that legitimately appear in BOTH the '당기순이익의 귀속'
    section (what we want) and the '포괄손익의 귀속' section (총포괄이익 몫, wrong
    concept) — both exact-match the same canonical, so _resolve() above holds instead
    of guessing. Cross-matching the candidate pairs against the already-confirmed
    net_income disambiguates without guessing (mutates confirmed/conflicts in place).

    Deliberately NOT a section_path text filter ('포괄' 있으면 버림): measured
    (2026-08-08) that ~0.5% of filings have the two section labels literally swapped
    in the source (DH오토웨어 00110583 2022H1, 에프알텍 00442561 2017H1) — a text
    filter would pick the wrong candidate there, while the identity check still finds
    the right one because it's anchored to the actual net_income value, not a label.

    Fallback #1 (added 2026-08-12, Phase 2 verification §4-2-2/§4-2-3): the identity check
    needs both net_income confirmed AND a clean controlling/noncontrolling value pairing
    — measured ~28% of a 5,000-row PASS-population re-check had a stage-rank-confirmed
    value (from _resolve()'s pre-fix behavior) get dropped to NULL here purely because
    net_income was missing or the real noncontrolling_ni candidate had been misclassified
    into the controlling_ni pool for that filing (unrelated data-quality gaps, not this
    fix). _top_stage_corroborated recovers those without reintroducing the original bug
    (verified absent from the 404-row known-bug population — see its docstring).

    Fallback #2 (added 2026-08-12, same-day follow-up): re-examining what was STILL held
    after fallback #1 found three more low-risk, independently-gated recovery paths —
    §A always also tries EBT−tax_expense as a net_income anchor when the direct line is
    missing (_derive_net_income_from_ebt); §B always also tries nci=0 in addition to
    whatever noncontrolling_ni candidate(s) exist (small/negligible NCI can still pick up
    an unrelated noisy candidate for that canonical); §C allows a small rounding-level
    epsilon (_NI_IDENTITY_EPS) when no exact pair matches. Measured recovery on the same
    5,000-row sample: A 12% / B 24% / C 3% of the still-NULL bucket, each still requiring
    a UNIQUE resulting pair to fire — an ambiguous result (e.g. two pairs both landing on
    net_income) still correctly stays held.

    If nothing disambiguates (identity ambiguous/impossible AND no multi-row stage
    corroboration — the '단독 후보' pattern from §1-A), stays held (결측 > 오염, no
    guessing)."""
    if "is.controlling_ni" not in conflicts:
        return
    matched = False
    net_income = confirmed.get("is.net_income")
    if net_income is None:
        net_income = _derive_net_income_from_ebt(cands)               # §A
    if net_income is not None:
        cni_vals = {r["value"] for r in conflicts["is.controlling_ni"]}

        nci_vals = set()
        if "is.noncontrolling_ni" in confirmed:
            nci_vals.add(confirmed["is.noncontrolling_ni"])
        elif "is.noncontrolling_ni" in conflicts:
            nci_vals |= {r["value"] for r in conflicts["is.noncontrolling_ni"]}
        elif "is.noncontrolling_ni" in cands:
            nci_vals |= {r["value"] for r in cands["is.noncontrolling_ni"]}
        nci_vals.add(0)   # §B: wholly-owned/negligible-NCI is always a candidate pairing,
                          # even when some other (possibly unrelated/noisy) candidate
                          # exists for this canonical too — mirrors the old sole-fallback
                          # (v2's `nci or 0`), just no longer gated on "nothing else found".

        match = _match_ni_identity(cni_vals, nci_vals, net_income)     # §C (eps inside)
        if match is not None:
            c_val, n_val = match
            confirmed["is.controlling_ni"] = c_val
            del conflicts["is.controlling_ni"]
            if "is.noncontrolling_ni" in conflicts:
                confirmed["is.noncontrolling_ni"] = n_val
                del conflicts["is.noncontrolling_ni"]
            matched = True
    if matched:
        return
    # identity couldn't run or couldn't disambiguate -> try stage corroboration per
    # canonical independently (controlling_ni and noncontrolling_ni are unrelated events
    # here — one may corroborate while the other stays genuinely ambiguous).
    if "is.controlling_ni" in conflicts:
        cv = _top_stage_corroborated(conflicts["is.controlling_ni"])
        if cv is not None:
            confirmed["is.controlling_ni"] = cv
            del conflicts["is.controlling_ni"]
    if "is.noncontrolling_ni" in conflicts:
        nv = _top_stage_corroborated(conflicts["is.noncontrolling_ni"])
        if nv is not None:
            confirmed["is.noncontrolling_ni"] = nv
            del conflicts["is.noncontrolling_ni"]


# P&L 결과 계정(손실이 될 수 있음). 순'손실' 단독 라벨(이익 없음)에 양수값이면 손실을 양(+)으로
# 기재한 서식(루닛 2021 'V.당기순손실'=+73.6B 등) → 표준화 시 부호반전. 이미 음수(괄호기재)이거나
# 결합라벨('이익(손실)')·이익 라벨은 그대로. 실측: 손실단독 net_income 음수 1098 vs 양수 90(7.6%).
_LOSS_CANON = frozenset({
    "is.net_income", "is.operating_income", "is.ebt",
    "is.controlling_ni", "is.gross_profit",
})


def _loss_signed(canon: str, label: str, value):
    """순'손실' 단독 라벨 + 양수 → −value(손실). 그 외는 원값."""
    if (value is not None and value > 0 and canon in _LOSS_CANON
            and label and "손실" in label and "이익" not in label):
        return -value
    return value


def _map_rows(rows, period: str, basis: str, statements) -> dict[str, list[dict]]:
    """Map merged cell dicts → {canonical: [candidate]}. Shared by both paths.
    Interim (H1/Q3) flow (is./cf.) keeps cumulative cells only (std_v2 convention).
    Carries the amendment marker (amended/amended_by) onto each candidate."""
    interim = period in ("H1", "Q3")
    cands: dict[str, list[dict]] = defaultdict(list)
    cum_seen: set[str] = set()
    stmt_set = set(statements)
    for r in rows:
        if r["statement"] not in stmt_set or r["basis"] != basis:
            continue
        fs = _FS.get(r["statement"])
        res = _map_label(r["label_raw"], fs)
        if res.confidence < 0.88 or res.account_code.startswith("unknown."):
            continue
        c = res.account_code
        is_cum = r["is_cumulative"]
        flow = interim and (c.startswith("is.") or c.startswith("cf."))
        if flow:
            if is_cum:
                if c not in cum_seen:
                    cands.pop(c, None)
                    cum_seen.add(c)
            elif c in cum_seen:
                continue
        cands[c].append({
            "value": _loss_signed(c, r["label_raw"], r["value_won"]),
            "stage": res.stage, "label_raw": r["label_raw"],
            "node_role": r["node_role"], "section_path": r["section_path"],
            "table_seq": r["table_seq"], "is_cumulative": is_cum,
            "amended": r.get("amended", False), "amended_by": r.get("amended_by"),
        })
    return dict(cands)


def collect_candidates(session, corp: str, fy: int, period: str, basis: str,
                       statements=("BS", "IS"),
                       rcept_by_stmt: dict[str, str] | None = None) -> dict[str, list[dict]]:
    """Map current-year (col_index=0) report_lines to {canonical: [candidate]} by
    querying report_lines directly (diagnostic / ablation path).

    rcept_by_stmt: optional {statement: rcept_no} to restrict each statement to a
    single filing. Without it, ALL filings for the period are pooled — which pools
    original + amendment/restatement versions and produces spurious conflicts.
    combine() uses build_merged_lines() instead (delta-patch); this stays for the
    ablation/pooled diagnostics.
    """
    rows = []
    for statement in statements:
        params = {"c": corp, "y": fy, "p": period, "b": basis, "s": statement}
        rcept_clause = ""
        if rcept_by_stmt and rcept_by_stmt.get(statement):
            rcept_clause = " AND rcept_no = :r"
            params["r"] = rcept_by_stmt[statement]
        db_rows = session.execute(text(f"""
            SELECT label_raw, value_won, node_role, section_path, table_seq,
                   COALESCE(is_cumulative, false) AS is_cum
            FROM report_lines
            WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
              AND basis=:b AND statement=:s AND col_index=0 AND value_won IS NOT NULL
              AND header_hint IS NULL          -- F2 가드(위와 같은 이유)
              {rcept_clause}
        """), params).fetchall()
        for label_raw, value_won, node_role, section_path, table_seq, is_cum in db_rows:
            rows.append({
                "statement": statement, "basis": basis, "label_raw": label_raw,
                "value_won": int(value_won), "node_role": node_role,
                "section_path": section_path, "table_seq": table_seq,
                "is_cumulative": bool(is_cum),
            })
    return _map_rows(rows, period, basis, statements)


def combine(session, corp: str, fy: int, period: str, basis: str,
            rcept_by_stmt: dict[str, str] | None = None,
            select_filing: bool = True, statements=("BS", "IS")):
    """Assemble std columns for one period. Returns (col, conflicts).

    col: {std_column: value} for DIRECT_MAP canonicals that resolved to a single
    value. conflicts: {canonical: [held candidates]} for analysis.

    Default path (L3-1b, 정본 정책): build_merged_lines() — 최초등록본 + 순차 델타
    패치(기재정정 반영 표시 포함). This removes spurious conflicts from pooling
    versions AND preserves untouched base cells under partial amendments.

    rcept_by_stmt: explicit {statement: rcept_no} bypasses the merge (ablation).
    select_filing=False + no rcept_by_stmt: pool all filings (diagnostic).
    """
    col, conflicts, _prov = combine_full(
        session, corp, fy, period, basis,
        rcept_by_stmt=rcept_by_stmt, select_filing=select_filing, statements=statements)
    return col, conflicts


def combine_full(session, corp: str, fy: int, period: str, basis: str,
                 rcept_by_stmt: dict[str, str] | None = None,
                 select_filing: bool = True, statements=("BS", "IS", "CF"),
                 merged: list[dict] | None = None):
    """Like combine() but also returns provenance (for std_v3 build, L3-3).

    Returns (col, conflicts, prov) where prov = {
      basis_fallback: bool,
      amended_cols:   [std_col, ...]         # value came from a 기재정정-patched cell
      amend_chain:    {std_col: [rcept,...]} # which amendments touched it
    }. source_rcepts is resolved by the caller (build) from the merged filings.

    merged: pre-built build_merged_lines() result. Pass it to reuse the (basis-
    independent) delta-patch merge across both bases — halves the query cost in
    the full build.
    """
    prov = {"basis_fallback": False, "amended_cols": [], "amend_chain": {}}
    if rcept_by_stmt is not None:
        cands = collect_candidates(session, corp, fy, period, basis,
                                   statements=statements, rcept_by_stmt=rcept_by_stmt)
    elif select_filing:
        if merged is None:
            merged = build_merged_lines(session, corp, fy, period)
        cands = _map_rows(merged, period, basis, statements)
        # L3-2 basis fallback: a company with no subsidiaries files only 별도(separate);
        # its 연결(consolidated) figures = separate. When the requested basis is entirely
        # absent but the period has only the other basis, fall back (verified: 45/45 such
        # cases are single-basis companies whose other-basis value == std_v2). Mirrors the
        # old chain (consolidated→separate for non-consolidating corps).
        if not cands:
            other = "separate" if basis == "consolidated" else "consolidated"
            bases_present = {r["basis"] for r in merged}
            if bases_present == {other}:
                cands = _map_rows(merged, period, other, statements)
                prov["basis_fallback"] = True
    else:
        cands = collect_candidates(session, corp, fy, period, basis,
                                   statements=statements)
    confirmed, conflicts = _resolve(cands, corp, fy, period)
    _resolve_ni_attribution(cands, confirmed, conflicts)
    # net_income fallback (ported from fin2/standardize/rules.py::rule_net_income_fill,
    # missing from the v3 port — 실측 2026-08-09: 삼성증권 FY2025 등 470행/119개사).
    # A nonstandard total-NI label (e.g. '보통주 당기순이익' instead of '당기순이익') can
    # fail to match is.net_income while the attribution lines (controlling/noncontrolling —
    # distinct labels, reliably matched) still resolve. Recompose the total from those
    # rather than leaving it NULL. Non-controlling defaults to 0 (e.g. 별도, no subsidiaries).
    if "is.net_income" not in confirmed and "is.controlling_ni" in confirmed:
        nci = confirmed.get("is.noncontrolling_ni", 0)
        confirmed["is.net_income"] = confirmed["is.controlling_ni"] + nci
    col: dict[str, int] = {}
    for canon, value in confirmed.items():
        std_col = DIRECT_MAP.get(canon)
        if std_col is None:
            continue
        col[std_col] = value
        # amendment provenance: did the winning value come from a 기재정정-patched cell?
        amend_rcepts = [r["amended_by"] for r in cands.get(canon, [])
                        if r["value"] == value and r.get("amended") and r.get("amended_by")]
        if amend_rcepts:
            prov["amended_cols"].append(std_col)
            # dedupe preserving order
            prov["amend_chain"][std_col] = list(dict.fromkeys(amend_rcepts))

    # industry revenue profile (P1): for insurers etc. whose K-IFRS IS diverges from the
    # general 매출액 standard, standardized revenue = Σ named subtotals, and the components
    # are preserved for the industry-aware tearsheet. Only the build/select path (which has
    # the raw merged lines) applies this; diagnostic (pooled/rcept) paths skip it.
    if merged is not None and rcept_by_stmt is None:
        is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == basis]
        if not is_lines and prov["basis_fallback"]:
            other = "separate" if basis == "consolidated" else "consolidated"
            is_lines = [r for r in merged if r["statement"] == "IS" and r["basis"] == other]
        applied = apply_revenue_profile(is_lines, _get_induty(session, corp), corp)
        if applied:
            pname, revenue, components = applied
            col["revenue"] = revenue
            prov["industry_lines"] = {"profile": pname, **components}
    # 증권성 금융지주: 매출액 개념이 없으므로 revenue 는 NULL(사실). DIRECT_MAP 이 수수료수익 등
    # 성분을 revenue 로 오선택했거나 bank 프로파일이 gross 를 억지로 채운 것을 제거. op_income
    # 이하는 그대로 유지(정확 적재됨).
    if corp in NO_REVENUE_CORPS:
        col.pop("revenue", None)
        if prov.get("industry_lines"):
            prov["industry_lines"] = None
    # enrichment (v3-native, 2026-07-25): capex/fcf/net_debt = report_lines-native, reusing
    # the v2 standardize rules against the confirmed canonicals. Additive-only — writes new
    # columns without mutating the existing DIRECT_MAP cols (debt/lease additive rules are NOT
    # run here to avoid perturbing validated columns; net_debt uses v3's own debt/cash).
    # D&A·EBITDA are supplied v3-natively from note_lines (2026-07-28) — see _apply_enrichment.
    # shares_out·data_quality still come from separate backfills.
    # ★ note_lines must be read with the *effective* basis: a non-consolidating corp files only
    #   별도, and its notes are stored as basis='separate' even though this row is 'consolidated'.
    #   Ignoring the fallback silently loses D&A for every such corp (실측 미채움의 주원인).
    eff_basis = (("separate" if basis == "consolidated" else "consolidated")
                 if prov["basis_fallback"] else basis)
    _apply_enrichment(session, corp, fy, period, basis, confirmed, col, eff_basis, cands)
    return col, conflicts, prov


def _apply_enrichment(session, corp, fy, period, basis, confirmed, col, note_basis=None,
                      cands=None):
    """Compute capex/fcf/net_debt/D&A/EBITDA in-place on `col` by reusing the v2 standardize
    rules on the confirmed canonicals. Additive: only sets the new keys, never mutates the
    existing DIRECT_MAP cols. net_debt derives from v3's own short/long debt + cash (v3 debt
    diverges from v2 for some firms — a pre-existing base-mapping matter tracked for G2, not
    fixed here). shares_out·data_quality still come from separate backfills.

    D&A (2026-07-28): the body CF has no D&A for many firms, so notes are the real source.
    note_da_canonicals() runs the layer-3 note interpretation chain (topic→period→label) and
    returns note.* canonicals, which feed the *existing* rule_additive_da — no bespoke D&A
    extractor. Notes only supplement: body canonicals win, since rule_additive_da sums the
    canonical families and cf.* is listed ahead of note.*.
    """
    canon = dict(confirmed)
    # 주석 D&A 는 FY + interim 모두 대상(2026-07-29). interim 은 note_da 가 col_label 로
    # '누적' 열을 골라 std_financials 의 누적 기준과 맞춘다 — 누적 열을 못 찾으면 값을 만들지 않는다.
    # 본문에서 이미 D&A 를 확보했으면 주석을 덧대지 않는다(같은 비용 이중 계상 방지).
    if not _has_body_da(canon):
        try:
            rcept = select_canonical_rcept(session, corp, fy, period)
            if rcept:
                canon.update(note_da_canonicals(
                    session, rcept, note_basis or basis, period))
        except Exception:  # noqa: BLE001 — 주석 소스 실패가 표준화 전체를 막으면 안 됨
            pass

    ctx = StdContext(corp_code=corp, fiscal_year=fy, fiscal_period=period,
                     basis=basis, canon=canon, col=dict(col))
    rule_additive_capex(ctx)     # capex = -(|유형자산취득| + |무형자산취득|)  [cf.capex canonicals]
    rule_derive_fcf(ctx)         # fcf = cfo - |capex|
    rule_derive_net_debt(ctx)    # net_debt = (short+long debt) - cash  [v3's own values]
    rule_additive_da(ctx)        # depreciation/amortization/da_total  [cf.* 우선, 없으면 note.*]
    rule_derive_ebitda(ctx)      # ebitda = operating_income + da_total
    for k in ("capex", "fcf", "net_debt",
              "depreciation", "amortization", "da_total", "ebitda"):
        v = ctx.col.get(k)
        if v is not None:
            col[k] = v


# 본문(CF/IS)에서 이미 D&A 가 잡혔는지 — 잡혔으면 주석을 덧대지 않는다.
_BODY_DA_CANON = ("cf.depreciation", "cf.amortization", "cf.da_total",
                  "cf.rou_depreciation", "is.depreciation", "is.amortization")


def _has_body_da(canon: dict) -> bool:
    return any(canon.get(c) for c in _BODY_DA_CANON)

