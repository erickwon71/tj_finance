"""R169 — confirm self-contradictory unit declarations per (rcept, section).

A statement that declares "(단위: 백만원)" (or 천원) while printing amounts already in 원
is caught by the 1경원 cap (totals vanish) or stored x10^6 (survivors). The document alone
cannot tell 원 from 천원 (R6), so the proof comes from the company's *other* filings: the
prior-period comparative column of this filing is the current-period column of an earlier
filing whose unit was declared correctly.

Trigger (suspect sections): a declared-unit row with |value_won| >= 1e15 (1,000조원 — no
listed-company line item reaches this; the largest real totals are ~5e14), or the section
vanished entirely under the declared unit.

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
EVIDENCE_MIN = 10**7
MIN_HITS = 3
CANDIDATE_KS = (1, 1_000, 1_000_000)
_BASIS_CODE = {"consolidated": "C", "separate": "S"}
_TRUSTED_SOURCES = ("declared", "inherited", "col_money", "section_def", "doc_default",
                    "proved_unit", "manual_unit")


def _section_code(line) -> str | None:
    b = _BASIS_CODE.get(line.basis or "")
    return f"{line.statement}_{b}" if b else None


def suspect_rcepts(s, era_min: int, corps: list[str] | None = None) -> list[str]:
    corp_clause = " AND corp_code = ANY(:c)" if corps else ""
    return [r for (r,) in s.execute(text(f"""
        SELECT DISTINCT rcept_no FROM report_lines
        WHERE statement IN ('BS','IS','CF','SCE') AND unit_source = 'declared'
          AND abs(value_won) >= :m AND report_fiscal_year >= :y{corp_clause}
        ORDER BY 1"""), {"m": SUSPECT_MIN, "y": era_min, "c": corps or []})]


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
    out = []
    for code in sorted(c for c in by_sec_raw if c):
        decl = [ln for ln in by_sec_decl.get(code, []) if ln.unit_source == "declared"]
        n_raw = sum(1 for ln in by_sec_raw[code] if ln.unit_source == "manual_unit")
        big = any(ln.value_won is not None and abs(ln.value_won) >= SUSPECT_MIN for ln in decl)
        vanished = n_raw > 0 and len(decl) < n_raw
        if not big and not (vanished and not decl):
            continue
        hits = {k: _hits(by_sec_raw[code], k, ev) for k in CANDIDATE_KS}
        k = _decide(hits)
        out.append({
            "rcept": rcept_no, "corp_code": meta.corp_code, "corp_name": meta.corp_name,
            "fy": meta.fiscal_year, "fp": meta.fiscal_period, "section": code,
            "rows_declared": len(decl), "rows_forced": n_raw,
            "hits": {str(c): hits[c] for c in CANDIDATE_KS},
            "decision": f"confirmed:{k}" if k else "unconfirmed",
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
            r["decision"] = f"confirmed:{k}"
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
