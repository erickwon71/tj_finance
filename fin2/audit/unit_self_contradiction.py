"""R169 — confirm self-contradictory unit declarations per (rcept, section).

A statement that declares "(단위: 백만원)" (or 천원) while printing amounts already in 원
is caught by the 1경원 cap (totals vanish) or stored x10^6 (survivors). The document alone
cannot tell 원 from 천원 (R6), so the proof comes from the company's *other* filings: the
prior-period comparative column of this filing is the current-period column of an earlier
filing whose unit was declared correctly.

Trigger (suspect sections): a declared-unit row with |value_won| >= 1e15 (1,000조원 — no
listed-company line item reaches this; the largest real totals are ~5e14), or the section
vanished entirely under the declared unit.

R207 second trigger (ratio): a 천원 declaration over cells already in 원 inflates x1,000 and
stays far below 1e15 (콜마비앤에이치 별도 매출 119조원), so the cap never fires. A filing/basis
whose declared-unit 자산총계 is >= RATIO_SUSPECT_MIN x the median 자산총계 of the same
corp+basis's other filings within +-1 fiscal year (and >= 0.1 x the declared multiplier) is a
suspect too. The ratio only *nominates*; confirmation is unchanged (exact cross-filing amount
matches), so a real jump in assets is never rewritten.

Confirmation rule, per section:
  hits(k) = distinct |amount| >= 1e7 that appear in the same corp's other filings with the
            same basis/statement/context year (SCE: same basis, SCE or BS, any year)
  confirmed k  iff  hits(k) >= MIN_HITS  and every other k (incl. declared) has
               hits <= 1 and hits(k) >= 10 x that (one round-number coincidence such as
               5,000,000 x 1,000 = 자본금 5,000,000,000 must not veto 80 exact matches)
Second pass, same rule: a section with no cross-filing evidence may use the amounts of the
sections of the *same document* already confirmed (same basis) — net income, cash and
equity totals recur across IS/CF/SCE/BS, and those amounts are already proven in 원.

Confirmed sections go to fin2/extract/data/unit_self_contradiction_overrides.json (read by
`report_lines._unit_override()`), written only by `scripts/unit_self_contradiction_scan.py
--apply`. The daily pipeline only *reports* new suspects (it must not dirty a tracked file).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text

import fin2.extract.report_lines as rl

SUSPECT_MIN = 10**15
RATIO_SUSPECT_MIN = 100
_TOTAL_ASSETS_LABELS = ("자산총계", "자 산 총 계", "자산 총계")
EVIDENCE_MIN = 10**7
MIN_HITS = 3
CANDIDATE_KS = (1, 1_000, 1_000_000)
_BASIS_CODE = {"consolidated": "C", "separate": "S"}
_TRUSTED_SOURCES = ("declared", "inherited", "col_money", "section_def", "doc_default",
                    "proved_unit", "manual_unit")


def _section_code(line) -> str | None:
    b = _BASIS_CODE.get(line.basis or "")
    return f"{line.statement}_{b}" if b else None


def _ratio_suspect_sql(corp_clause: str, rcept_clause: str) -> str:
    return f"""
        WITH ta AS (
          SELECT rcept_no, corp_code, report_fiscal_year fy, basis, value_won a, adecimal
          FROM report_lines
          WHERE statement = 'BS' AND col_index = 0 AND label_raw = ANY(:labels)
            AND value_won > 0 AND basis IN ('consolidated','separate'){corp_clause}),
        tgt AS (
          SELECT * FROM ta
          WHERE adecimal < 0 AND fy >= :y{rcept_clause}
            AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = ta.rcept_no
                        AND r.statement = 'BS' AND r.unit_source = 'declared'
                        AND r.basis = ta.basis AND r.col_index = 0
                        AND r.label_raw = ANY(:labels))),
        med AS (
          SELECT t.rcept_no, t.basis, t.a, t.adecimal,
                 percentile_cont(0.5) WITHIN GROUP (ORDER BY o.a) AS m
          FROM tgt t JOIN ta o ON o.corp_code = t.corp_code AND o.basis = t.basis
                                AND o.rcept_no <> t.rcept_no AND abs(o.fy - t.fy) <= 1
          GROUP BY t.rcept_no, t.basis, t.a, t.adecimal)
        SELECT rcept_no, basis FROM med
        WHERE a >= m * :ratio AND a >= 0.1 * power(10, -adecimal) * m
        ORDER BY 1, 2"""


def ratio_suspects(s, era_min: int, corps: list[str] | None = None,
                   rcept_no: str | None = None) -> list[tuple[str, str]]:
    """(rcept_no, basis) whose declared-unit 자산총계 is >= RATIO_SUSPECT_MIN x the same
    corp+basis's neighbouring filings (R207 nomination trigger — not a proof)."""
    corp_clause = " AND corp_code = ANY(:c)" if corps else ""
    if rcept_no:   # neighbours must come from the same corp, so scope by corp not by rcept
        corp_clause = (" AND corp_code = (SELECT corp_code FROM filings WHERE rcept_no = :rc)")
    rcept_clause = " AND rcept_no = :rc" if rcept_no else ""
    rows = s.execute(text(_ratio_suspect_sql(corp_clause, rcept_clause)),
                     {"labels": list(_TOTAL_ASSETS_LABELS), "y": era_min, "c": corps or [],
                      "ratio": RATIO_SUSPECT_MIN, "rc": rcept_no})
    return [(r, b) for r, b in rows]


def suspect_rcepts(s, era_min: int, corps: list[str] | None = None) -> list[str]:
    corp_clause = " AND corp_code = ANY(:c)" if corps else ""
    cap = {r for (r,) in s.execute(text(f"""
        SELECT DISTINCT rcept_no FROM report_lines
        WHERE statement IN ('BS','IS','CF','SCE') AND unit_source = 'declared'
          AND abs(value_won) >= :m AND report_fiscal_year >= :y{corp_clause}
        ORDER BY 1"""), {"m": SUSPECT_MIN, "y": era_min, "c": corps or []})}
    return sorted(cap | {r for r, _ in ratio_suspects(s, era_min, corps)})


def _extract(fp, meta, rcept_no, forced: int | None):
    """Extract with an optional forced rcept-wide multiplier (probe only, never stored)."""
    saved_manual = dict(rl._MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS)
    saved_proved = rl._PROVED_UNIT_OVERRIDES.pop(rcept_no, None)
    try:
        if forced is not None:
            rl._MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS[rcept_no] = forced
        else:
            rl._MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS.pop(rcept_no, None)
        return rl.extract_report_lines(
            fp, rcept_no=rcept_no, corp_code=meta.corp_code,
            report_fiscal_year=meta.fiscal_year, report_fiscal_period=meta.fiscal_period)
    finally:
        rl._MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS.clear()
        rl._MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS.update(saved_manual)
        if saved_proved is not None:
            rl._PROVED_UNIT_OVERRIDES[rcept_no] = saved_proved


def _evidence(s, corp_code: str, exclude: set[str]) -> dict:
    """(basis, statement, ctx_fy) -> set(|value|) from the corp's other trusted filings."""
    ev: dict = defaultdict(set)
    rows = s.execute(text("""
        SELECT rcept_no, basis, statement, context_fiscal_year, abs(value_won)
        FROM report_lines
        WHERE corp_code = :c AND statement IN ('BS','IS','CF','SCE')
          AND unit_source = ANY(:src) AND abs(value_won) >= :lo AND abs(value_won) < :hi"""),
        {"c": corp_code, "src": list(_TRUSTED_SOURCES), "lo": EVIDENCE_MIN, "hi": SUSPECT_MIN})
    for rc, basis, st, fy, v in rows:
        if rc in exclude:
            continue
        ev[(basis, st, fy)].add(int(v))
        if st in ("BS", "SCE"):
            ev[(basis, "EQ*", None)].add(int(v))
    return ev


def _hits(section_lines, k: int, ev: dict, doc_ev: set | None = None) -> int:
    found = set()
    for ln in section_lines:
        if ln.value_won is None or ln.unit_source != "manual_unit":
            continue
        v = abs(ln.value_won) * k
        if v < EVIDENCE_MIN:
            continue
        if doc_ev is not None:
            if v in doc_ev:
                found.add(v)
        elif ln.statement == "SCE":
            if v in ev.get((ln.basis, "EQ*", None), ()):
                found.add(v)
        elif v in ev.get((ln.basis, ln.statement, ln.context_fiscal_year), ()):
            found.add(v)
    return len(found)


def _decide(hits: dict) -> int | None:
    best = max(CANDIDATE_KS, key=lambda k: hits[k])
    others = [hits[k] for k in CANDIDATE_KS if k != best]
    if best == 1_000_000 or hits[best] < MIN_HITS:
        return None
    if max(others) > 1 or hits[best] < 10 * max(others):
        return None
    return best


def _label(k: int | None, decl_mults: set[int]) -> str:
    if k is None:
        return "unconfirmed"
    if decl_mults == {k}:
        return "declared_correct"  # evidence agrees with the declaration — nothing to override
    return f"confirmed:{k}"


def scan_rcept(s, rcept_no: str, suspects: set[str]) -> list[dict]:
    meta = s.execute(text("""
        SELECT dt.file_path, f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period
        FROM download_tasks dt JOIN filings f USING (rcept_no)
        WHERE dt.rcept_no = :r AND dt.file_type = 'xml' AND dt.status = 'completed'"""),
        {"r": rcept_no}).first()
    if meta is None or not Path(meta.file_path).exists():
        return [{"rcept": rcept_no, "decision": "no_xml"}]
    declared = _extract(meta.file_path, meta, rcept_no, None)
    raw = _extract(meta.file_path, meta, rcept_no, 1)   # k=1 → value_won == raw amount
    by_sec_decl: dict = defaultdict(list)
    for ln in declared:
        by_sec_decl[_section_code(ln)].append(ln)
    by_sec_raw: dict = defaultdict(list)
    for ln in raw:
        by_sec_raw[_section_code(ln)].append(ln)
    ev = _evidence(s, meta.corp_code, suspects)
    ratio_bases = {_BASIS_CODE[b] for r, b in ratio_suspects(s, 0, rcept_no=rcept_no)}
    out = []
    for code in sorted(c for c in by_sec_raw if c):
        decl = [ln for ln in by_sec_decl.get(code, []) if ln.unit_source == "declared"]
        n_raw = sum(1 for ln in by_sec_raw[code] if ln.unit_source == "manual_unit")
        big = any(ln.value_won is not None and abs(ln.value_won) >= SUSPECT_MIN for ln in decl)
        vanished = n_raw > 0 and len(decl) < n_raw
        by_ratio = code.split("_")[1] in ratio_bases
        if not big and not by_ratio and not (vanished and not decl):
            continue
        decl_mults = {10 ** -ln.adecimal for ln in decl if ln.adecimal is not None}
        if decl_mults == {1}:
            continue  # the big value is not a scale effect (e.g. R152 concatenated cell)
        hits = {k: _hits(by_sec_raw[code], k, ev) for k in CANDIDATE_KS}
        k = _decide(hits)
        out.append({
            "rcept": rcept_no, "corp_code": meta.corp_code, "corp_name": meta.corp_name,
            "fy": meta.fiscal_year, "fp": meta.fiscal_period, "section": code,
            "declared_mults": sorted(decl_mults),
            "rows_declared": len(decl), "rows_forced": n_raw,
            "hits": {str(c): hits[c] for c in CANDIDATE_KS},
            "decision": _label(k, decl_mults),
        })
    # Second pass — in-document evidence from sections confirmed at k=1 (same basis).
    for r in out:
        if r["decision"] != "unconfirmed":
            continue
        basis_code = r["section"].split("_")[1]
        doc_ev = {abs(ln.value_won) for c in (x["section"] for x in out
                  if x["decision"] == "confirmed:1" and x["section"].endswith("_" + basis_code))
                  for ln in by_sec_raw[c]
                  if ln.value_won is not None and ln.unit_source == "manual_unit"
                  and abs(ln.value_won) >= EVIDENCE_MIN}
        if not doc_ev:
            continue
        hits = {k: _hits(by_sec_raw[r["section"]], k, ev, doc_ev) for k in CANDIDATE_KS}
        k = _decide(hits)
        r["doc_hits"] = {str(c): hits[c] for c in CANDIDATE_KS}
        if k:
            r["decision"] = _label(k, set(r["declared_mults"]))
            r["evidence"] = "same_document"
    return out



def merge_confirmed(results: list[dict]) -> int:
    """Merge confirmed sections into the tracked data file. Returns rcepts in the file."""
    path = rl._PROVED_UNIT_OVERRIDES_PATH
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for r in results:
        if r.get("decision", "").startswith("confirmed:"):
            data.setdefault(r["rcept"], {})[r["section"]] = int(r["decision"].split(":")[1])
    path.write_text(json.dumps(dict(sorted(data.items())), ensure_ascii=False, indent=1)
                    + "\n", encoding="utf-8")
    return len(data)
