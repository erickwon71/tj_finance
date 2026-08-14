"""
Layer-2 post-process overlay — corrects sign bugs in TEXT-extracted CF report_lines
using inline XBRL facts already present in document.xml (Track A tags,
`<TE ACODE=... ACONTEXT=...>`), reusing the exact same reader Gate B's auditor
(`fin2/audit/face_audit.py::read_report_face_xbrl`) already relies on and has
years of regression fixes behind it (2026-08-12 ambiguous-home/axis-identity
guards — see that function's docstring).

Background:
  docs/qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md (root-cause investigation)
  docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md (design)

Root cause: production text extraction (fin2/extract/text.py, via
extract_report_lines()) reads the CF statement's "배당금의 지급" cell as bare
digits — the filing's CF body table renders this line with NO sign markup
(no minus sign/parens). That cell IS tagged with an ACODE, but a
company-specific extension concept (`entity{corp}_...`), which cannot be
trusted for sign (design §2). Elsewhere in the SAME document (a
capital-changes/dividend-detail table), the SAME kind of fact is ALSO tagged
— this time with the standard IFRS concept
(`ifrs-full_DividendsPaidClassifiedAsFinancingActivities`) AND rendered WITH
parentheses (signed). Gate B's face_audit already reads that second,
authoritative tag site-wide; production never did.

Design principle (R0 — layer2 stays canonical-mapping-free, see
[[architecture-report-read-layer2-only]]): this module does NOT run
AccountMapper or any fuzzy label inference to decide "which row is
dividends_paid" — it only:
  1. builds a canonical-keyed fact table via `map_acode()` (a deterministic
     ACODE->canonical dict lookup — the same tool face_audit already uses,
     not fuzzy/guessed) through `read_report_face_xbrl()` (reused verbatim —
     see design §4-2's "reuse over refactor" fallback: face_audit.py is not
     touched at all, zero regression risk to its 2026-08-12 fixes);
  2. narrows candidate TEXT rows with a fixed keyword substring check
     (label_raw contains BOTH "배당" and "지급") — the same category of
     structural keyword filtering fin2/extract/text.py already does
     elsewhere for section/title detection, not label->canonical inference;
  3. only overrides a row's value_won when EXACTLY one candidate row and
     EXACTLY one fact match on (basis, is_cumulative) AND their magnitudes
     agree within 1% — anything ambiguous or magnitude-mismatched is left
     untouched (design §5 "★블랭킷 수정 금지 원칙").

No ACODE plumbing through RowData/table_extractor.py is needed or added —
this overlay re-parses `file_path` independently (`read_report_face_xbrl`
does its own `_parse_xml_file`) and only mutates the already-built
ReportLineRow list in memory, so it cannot regress the text-extraction path
itself.

Scope (v1, design §4-4): CF / cf.dividends_paid only. Natural to extend to
other CF canonicals later, but each addition needs its own regression-diff
check (design §5) — not done blindly here.
"""
from __future__ import annotations

from pathlib import Path

from fin2.audit.face_audit import read_report_face_xbrl

# structural keyword filter (not canonical inference — see module docstring §point 2).
_DIVIDENDS_PAID_LABEL_KEYWORDS = ("배당", "지급")
_TARGET_CANONICAL = "cf.dividends_paid"

# ACODE/ACONTEXT tags only became common from fiscal_year 2024 (measured:
# docs/qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md §5 — 0.0% for
# 1999-2023, 31.7% in 2024, 98.3%+ after). Older filings are a guaranteed
# no-op through read_report_face_xbrl() anyway (empty result); skip early
# purely to avoid a second full-document TE[@ACODE] scan during backfill.
_MIN_FISCAL_YEAR = 2024

# magnitude sanity tolerance (design §4-3/§5 — "같은 자릿수" check, not a
# magnitude-fixing mechanism; this module only ever corrects SIGN, so text
# and fact magnitudes should already agree almost exactly when they're truly
# the same fact).
_MAGNITUDE_TOLERANCE = 0.01


def overlay_dividends_paid_sign(
    rows: list, file_path: str | Path, report_fiscal_year: int,
) -> int:
    """Mutates `rows` (list[ReportLineRow]) in place: for CF/col0 rows whose
    label_raw looks like the dividends-paid line, replaces value_won (sign +
    magnitude) with the matching Track-A inline-XBRL fact when — and only
    when — exactly one candidate exists on each side and their magnitudes
    already agree. Returns the number of rows overridden (0 = no-op, the
    overwhelming majority of calls: pre-2024 filings or filings without this
    Track-A tag pattern).
    """
    if report_fiscal_year < _MIN_FISCAL_YEAR:
        return 0

    facts = read_report_face_xbrl(file_path)
    target_facts = [f for f in facts
                    if f.canonical == _TARGET_CANONICAL and f.statement == "CF"]
    if not target_facts:
        return 0
    facts_by_key: dict[tuple, list] = {}
    for f in target_facts:
        facts_by_key.setdefault((f.basis, f.is_cumulative), []).append(f)

    candidates = [
        r for r in rows
        if r.statement == "CF" and (r.col_index or 0) == 0 and r.value_won not in (None, 0)
        and all(kw in (r.label_raw or "") for kw in _DIVIDENDS_PAID_LABEL_KEYWORDS)
    ]
    rows_by_key: dict[tuple, list] = {}
    for r in candidates:
        rows_by_key.setdefault((r.basis, r.is_cumulative), []).append(r)

    n_applied = 0
    for key, fact_list in facts_by_key.items():
        if len(fact_list) != 1:
            continue  # ambiguous fact-side (shouldn't normally happen, guard anyway)
        row_list = rows_by_key.get(key, [])
        if len(row_list) != 1:
            continue  # no unique text-side candidate — leave untouched (§5)
        row = row_list[0]
        fact_won = fact_list[0].amount_won
        if fact_won in (None, 0):
            continue
        ratio = abs(fact_won) / abs(row.value_won)
        if not (1 - _MAGNITUDE_TOLERANCE <= ratio <= 1 + _MAGNITUDE_TOLERANCE):
            continue  # magnitude disagreement — probably a different fact, don't touch
        if row.value_won == fact_won:
            continue  # already correct — no-op
        row.value_won = fact_won
        row.source_ref = (f"{row.source_ref};xbrl_inline_override"
                           if row.source_ref else "xbrl_inline_override")
        n_applied += 1
    return n_applied
