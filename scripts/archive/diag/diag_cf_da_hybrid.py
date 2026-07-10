"""Validate hybrid CF D&A recovery (NOTE + FACE) for the 2024+ gap.

For std_v2 rows (chosen basis) with depreciation IS NULL and a CF source, recover
da_total two ways and combine:
  NOTE: note_extractor (CF-note D&A breakdown), target basis
  FACE: Track B CF-statement-face cf.depreciation+cf.amortization, target basis
Unit guard: |da_total| / same-basis revenue in [LO, HI]. Compare to legacy
standard_financials.da_total (validation oracle). Reports recall + match-rate for
note-only, face-only, and hybrid.

Read-only. Usage: python scripts/diag_cf_da_hybrid.py --basis consolidated [--year-min 2024] [--limit N]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.notes import extract_note_da_facts
from fin2.extract import text as text_extract

_ACCEPT_LO, _ACCEPT_HI = 0.003, 0.6
_DEP = ("cf.depreciation", "cf.rou_depreciation")
_AMO = ("cf.amortization",)

_SQL = """
    SELECT s.corp_code, s.fiscal_year, s.fiscal_period,
           ss.source_rcept_no AS cf_rcept, dt.file_path
    FROM std_financials_v2 s
    JOIN statement_source ss
      ON ss.corp_code=s.corp_code AND ss.fiscal_year=s.fiscal_year
     AND ss.fiscal_period=s.fiscal_period AND ss.basis=:basis AND ss.statement='CF'
    JOIN download_tasks dt ON dt.rcept_no = ss.source_rcept_no
    WHERE s.statement_type=:basis AND s.version=1 AND s.depreciation IS NULL
      AND s.fiscal_year >= :ymin AND dt.file_path IS NOT NULL
    ORDER BY s.corp_code, s.fiscal_year, s.fiscal_period
"""


def _revenue_by_basis(session, rcept):
    rows = session.execute(text("""
        SELECT basis, MAX(amount_won) FROM fact_v2
        WHERE rcept_no=:r AND canonical_account='is.revenue'
          AND col_index=0 AND NOT is_dimensional AND basis IN ('consolidated','separate')
        GROUP BY basis
    """), {"r": rcept}).fetchall()
    return {b: v for b, v in rows if v}


def _legacy_da(session, corp, fy, fp, basis):
    return session.execute(text("""
        SELECT da_total FROM standard_financials
        WHERE corp_code=:c AND fiscal_year=:fy AND fiscal_period=:fp AND statement_type=:b
        ORDER BY version DESC NULLS LAST LIMIT 1
    """), {"c": corp, "fy": fy, "fp": fp, "b": basis}).scalar()


def _note_da(file_path, rcept, corp, fy, fp, basis, rev):
    facts = extract_note_da_facts(file_path, rcept_no=rcept, corp_code=corp,
                                  report_fiscal_year=fy, report_fiscal_period=fp,
                                  revenue_by_basis=rev)
    fs = [f for f in facts if f.basis == basis]
    if not fs:
        return None
    da = next((f.amount_won for f in fs if f.canonical_account == "note.da_total"), None)
    if da is None:
        da = sum(f.amount_won for f in fs if f.canonical_account in
                 ("note.depreciation", "note.amortization", "note.rou_depreciation"))
    return da or None


def _face_da(file_path, rcept, corp, fy, fp, basis):
    facts = text_extract.extract_facts(file_path, rcept_no=rcept, corp_code=corp,
                                       report_fiscal_year=fy, report_fiscal_period=fp)
    dep = sum(abs(f.amount_won) for f in facts if f.basis == basis and f.col_index == 0
              and f.canonical_account in _DEP and f.amount_won)
    amo = sum(abs(f.amount_won) for f in facts if f.basis == basis and f.col_index == 0
              and f.canonical_account in _AMO and f.amount_won)
    tot = dep + amo
    return tot or None


def _ok(da, rev):
    if not da or not rev or rev <= 0:
        return False
    return _ACCEPT_LO <= abs(da) / rev <= _ACCEPT_HI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default="consolidated", choices=["consolidated", "separate"])
    ap.add_argument("--year-min", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    with get_session() as session:
        targets = session.execute(text(_SQL),
                                  {"basis": args.basis, "ymin": args.year_min}).fetchall()
    if args.limit:
        targets = targets[: args.limit]
    print(f"[{args.basis}] D&A-NULL targets (fy>={args.year_min}): {len(targets):,}")

    n = dict(note=0, face=0, hybrid=0)
    m = dict(note=[0, 0], face=[0, 0], hybrid=[0, 0])  # [match, mismatch] vs legacy
    disagree = []

    with get_session() as session:
        for t in targets:
            if not t.file_path or not Path(t.file_path).exists():
                continue
            rev = _revenue_by_basis(session, t.cf_rcept)
            r = rev.get(args.basis)
            if not r or r <= 0:
                continue
            note = _note_da(t.file_path, t.cf_rcept, t.corp_code, t.fiscal_year, t.fiscal_period, args.basis, rev)
            face = _face_da(t.file_path, t.cf_rcept, t.corp_code, t.fiscal_year, t.fiscal_period, args.basis)
            note_ok = _ok(note, r)
            face_ok = _ok(face, r)
            # hybrid: prefer note (dedicated breakdown), else face
            hyb = note if note_ok else (face if face_ok else None)

            leg = _legacy_da(session, t.corp_code, t.fiscal_year, t.fiscal_period, args.basis)
            for key, val, ok in (("note", note, note_ok), ("face", face, face_ok),
                                 ("hybrid", hyb, hyb is not None)):
                if ok:
                    n[key] += 1
                    if leg:
                        rel = abs(val - leg) / max(abs(leg), 1)
                        m[key][0 if rel <= 0.02 else 1] += 1

            # face mismatch vs legacy detail (face ok, legacy present, rel>2%)
            if face_ok and leg:
                rel = abs(face - leg) / max(abs(leg), 1)
                if rel > 0.02 and len(disagree) < 20:
                    disagree.append((t.corp_code, t.fiscal_year, t.fiscal_period,
                                     f"face={face:,}", f"legacy={leg:,}",
                                     f"note={format(note, ',') if note else '-'}",
                                     f"{rel*100:.0f}%"))

    tot = len(targets)
    for key in ("note", "face", "hybrid"):
        mm = m[key]
        mr = f"{100*mm[0]/(mm[0]+mm[1]):.1f}%" if (mm[0]+mm[1]) else "n/a"
        print(f"  {key:7s}: recovered {n[key]:4d}/{tot} ({100*n[key]/max(tot,1):4.1f}%)  "
              f"legacy match {mm[0]}/{mm[0]+mm[1]} ({mr})")
    print("\nFACE mismatches vs legacy (corp,fy,fp,face,legacy,note,rel):")
    for d in disagree:
        print("  ", d)


if __name__ == "__main__":
    main()
