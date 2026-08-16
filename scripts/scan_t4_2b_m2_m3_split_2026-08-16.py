"""
R28 follow-up track T4-2b (deferred part) -- M2 vs M3 split within the `doc_default`
unit-overscale bucket. (docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §5-7.)

§5-6 established from 3 hand-verified samples that the `doc_default` bucket splits into:
  M2 -- this table genuinely has no nearby unit declaration (the doc-wide default is the
        only signal that exists, and it's wrong for this table).
  M3 -- a correct local declaration DOES exist a few siblings back, but the production
        lookback (`declaration_text()` clause 3 / `inherited_declaration_text()`) stops
        early at a non-metadata paragraph (e.g. a disclaimer) sitting in between.

This script classifies the full `doc_default` population (not a sample) by:
  1. locating, for each affected (rcept_no, statement, basis) group, the actual TABLE
     element that produced the largest offending row (matched by raw value substring --
     same method used for the 5 hand-verified T4-1 samples,
     `scripts/verify_t4_1_source_2026-08-16.py`);
  2. confirming the *production* lookback really returns nothing for that table
     (`declaration_text(tbl) or inherited_declaration_text(tbl)` is None) -- sanity check,
     this should be true for 100% since that's the precondition for doc_default having
     been applied in the first place;
  3. running an *extended* probe lookback that additionally walks past non-metadata text
     siblings (up to a bounded span, still stopping at a real statement-title boundary)
     to see whether a unit declaration becomes reachable.

★ This is a MEASUREMENT only. Finding a candidate declaration under the extended walk
  does NOT mean it is safe to wire into production as-is -- text.py's own comments record
  a real regression (LVMC, `text.py:449-450`) from a lookback that reached too far and
  grabbed an unrelated table's declaration. The M3 count here is an upper bound on "code
  fixable in principle"; the actual fix (if approved) needs a narrower, evidence-driven
  stop condition (§5-8), not this probe's walk verbatim.

Usage:
  .venv/bin/python scripts/scan_t4_2b_m2_m3_split_2026-08-16.py
  .venv/bin/python scripts/scan_t4_2b_m2_m3_split_2026-08-16.py --limit 50   # smoke test
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text as sqltext                          # noqa: E402

from collector.db import get_session                            # noqa: E402
from parser.xml.dart_xml_parser import _parse_xml_file           # noqa: E402
from parser.common.amount_normalizer import detect_unit_tokens   # noqa: E402
from fin2.extract.statement_titles import (                      # noqa: E402
    _is_metadata_only, _STMT_TITLE, SECTION_CODE_OF)
from fin2.extract.text import (                                  # noqa: E402
    declaration_text, inherited_declaration_text, _detect_fin_type,
    _detect_body_statement_tables)
from fin2.extract.report_lines import (                          # noqa: E402
    _detect_pre2015_body_statement_tables_merged, _PRE2015_ROUTING_MAX_FY)

# ★per [[feedback-bulk-read-use-sdcard]] -- bulk read from SD card, not the NAS symlink.
_RAW_ROOT = "/Volumes/dart_data/raw_report"
_MARKET_OF_CLS = {"Y": "KOSPI", "K": "KOSDAQ"}
_REPORT_TYPE_DIR = {"annual": "annual", "half": "half", "quarter": "quarter"}
_EXTENDED_SPAN = 15          # generous -- this is a measurement probe, not the real fix
_THRESHOLD = 1_000_000_000_000_000


def _find_file(corp_code: str, corp_cls: str, report_type: str, fiscal_year: int,
                rcept_no: str) -> str | None:
    market = _MARKET_OF_CLS.get(corp_cls)
    if market is None:
        return None
    rtype = _REPORT_TYPE_DIR.get(report_type, report_type)
    corp_dirs = glob.glob(os.path.join(_RAW_ROOT, market, f"{corp_code}_*"))
    for cd in corp_dirs:
        # `filings.fiscal_year` is not always the folder's year (e.g. a Q1 report filed
        # in Feb often reports the *previous* fiscal year and is filed under that year's
        # folder) -- try the exact year first, then its immediate neighbors, before
        # falling back to a full glob across all years for this corp+report_type.
        for y in (fiscal_year, fiscal_year - 1, fiscal_year + 1):
            cand = os.path.join(cd, rtype, str(y), f"{rcept_no}.xml")
            if os.path.exists(cand):
                return cand
        hits = glob.glob(os.path.join(cd, rtype, "*", f"{rcept_no}.xml"))
        if hits:
            return hits[0]
    return None


def _route_groups(root, fiscal_year: int, fin_type: str):
    """Same routing `extract_report_lines()` itself uses -- reused so the search below
    only looks inside the tables that production actually considers for this
    (statement, basis), instead of the whole document (which risks picking up the
    *same* raw figure recurring in an unrelated sibling statement, e.g. APPR/IS/BS
    legacy forms routinely repeat the period's net income verbatim)."""
    if fiscal_year <= _PRE2015_ROUTING_MAX_FY:
        return _detect_pre2015_body_statement_tables_merged(root, fin_type)
    return _detect_body_statement_tables(root, fin_type, include_sce=True)


def _find_table_for_value(root, fiscal_year: int, fin_type: str, statement: str,
                           basis: str, raw_str: str):
    """Innermost TABLE, scoped to this (statement, basis)'s own detected candidate
    tables, whose text contains `raw_str`. Prefers a table the router itself left with
    `unit is None` (that's precisely the doc_default trigger condition) -- falls back to
    any containing table only if no unit-less one matches (keeps the value-match honest
    without silently accepting a table this row's actual code path wouldn't have used)."""
    section_code = SECTION_CODE_OF.get((basis, statement))
    if section_code is None:
        return None
    try:
        groups = _route_groups(root, fiscal_year, fin_type)
    except Exception:
        return None
    candidates = groups.get(section_code, [])
    fallback = None
    for tbl, unit, _kind in candidates:
        txt = "".join(tbl.itertext())
        if raw_str not in txt:
            continue
        if unit is None:
            return tbl
        if fallback is None:
            fallback = tbl
    return fallback


def _extended_probe(tbl, span: int = _EXTENDED_SPAN) -> str | None:
    """Like `inherited_declaration_text`, but does NOT stop at the first non-empty,
    non-title TEXT sibling (a <P> etc.) -- keeps walking past it (bounded by `span`).
    This is the one and only behavioral delta from production, and it's exactly M3's
    signature (§5-6): a disclaimer paragraph sitting between the declaration and the
    data table. TABLE siblings are still handled exactly like `inherited_declaration_text`
    (skip past sibling data tables; a blank/undeclared TABLE is still a hard stop -- that's
    M2's signature, not M3's, so extending past it would blur the two mechanisms)."""
    prev = tbl.getprevious()
    hops = 0
    while prev is not None and hops < span:
        hops += 1
        tag = prev.tag.upper() if isinstance(prev.tag, str) else ""
        txt = " ".join("".join(prev.itertext()).split())
        if tag == "TABLE":
            trs = prev.findall(".//TR")
            has_data = any("".join(tr.itertext()).strip() for tr in trs) if trs else False
            if has_data:
                prev = prev.getprevious()       # sibling data table under the same decl
                continue
            if detect_unit_tokens(txt):
                return txt                      # declaration-only table -- found it
            return None                         # blank/undeclared table -- M2 signature, stop
        if txt:
            if any(p.search(txt) for p, _ in _STMT_TITLE):
                return None                     # statement boundary -- stop (safety rail kept)
            if detect_unit_tokens(txt):
                return txt
            # ★ extended: unlike production inherited_declaration_text, do not stop here --
            #   this is the one difference that lets M3 (§5-6) get detected.
        prev = prev.getprevious()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--csv", default=os.path.join(
        _REPO_ROOT, "scripts", "scan_t4_2b_m2_m3_split_2026-08-16_results.csv"))
    args = ap.parse_args()

    with get_session() as s:
        groups = s.execute(sqltext("""
            SELECT rl.rcept_no, rl.corp_code, f.report_type, f.fiscal_year, f.corp_cls,
                   rl.statement, rl.basis, rl.adecimal,
                   max(abs(rl.value_won)) AS maxv
            FROM report_lines rl JOIN filings f USING (rcept_no)
            WHERE rl.unit_source = 'doc_default' AND abs(rl.value_won) > :t
            GROUP BY 1,2,3,4,5,6,7,8
            ORDER BY 1
        """), {"t": _THRESHOLD}).fetchall()

    if args.limit:
        groups = groups[:args.limit]
    print(f"scanning {len(groups)} (rcept,statement,basis) groups from {len(set(g.rcept_no for g in groups))} filings")

    counts = {"M2": 0, "M3": 0, "file_missing": 0, "table_not_found": 0,
              "sanity_fail_prod_found_decl": 0, "parse_failed": 0}
    out_rows = []
    root_cache: dict[str, object] = {}

    for i, g in enumerate(groups):
        if i and i % 100 == 0:
            print(f"  ... {i}/{len(groups)}  running: {counts}")
        path = _find_file(g.corp_code, g.corp_cls, g.report_type, g.fiscal_year, g.rcept_no)
        if path is None:
            counts["file_missing"] += 1
            out_rows.append([g.rcept_no, g.corp_code, g.statement, g.basis, "file_missing", ""])
            continue
        if path not in root_cache:
            if len(root_cache) > 4:
                root_cache.clear()   # keep cache tiny -- a filing repeats across statement/basis rows
            try:
                root_cache[path] = _parse_xml_file(path)
            except Exception as e:
                root_cache[path] = None
                print(f"  !! parse failed {path}: {e}")
        root = root_cache[path]
        if root is None:
            counts["parse_failed"] += 1
            out_rows.append([g.rcept_no, g.corp_code, g.statement, g.basis, "parse_failed", ""])
            continue

        multiplier = 10 ** abs(g.adecimal) if g.adecimal else 1
        raw = g.maxv // multiplier if multiplier else g.maxv
        raw_str = f"{raw:,}"
        try:
            fin_type = _detect_fin_type(root)
        except Exception:
            fin_type = "A"
        tbl = _find_table_for_value(root, g.fiscal_year, fin_type, g.statement, g.basis, raw_str)
        if tbl is None:
            counts["table_not_found"] += 1
            out_rows.append([g.rcept_no, g.corp_code, g.statement, g.basis, "table_not_found", raw_str])
            continue

        prod = declaration_text(tbl) or inherited_declaration_text(tbl)
        if prod is not None:
            # Shouldn't happen -- if it did, unit_source should not have been doc_default.
            counts["sanity_fail_prod_found_decl"] += 1
            out_rows.append([g.rcept_no, g.corp_code, g.statement, g.basis,
                              "sanity_fail_prod_found_decl", prod[:80]])
            continue

        found = _extended_probe(tbl)
        if found is not None:
            counts["M3"] += 1
            out_rows.append([g.rcept_no, g.corp_code, g.statement, g.basis, "M3", found[:80]])
        else:
            counts["M2"] += 1
            out_rows.append([g.rcept_no, g.corp_code, g.statement, g.basis, "M2", ""])

    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rcept_no", "corp_code", "statement", "basis", "classification", "note"])
        w.writerows(out_rows)

    print(f"\n=== final ({len(groups)} groups) ===")
    for k, v in counts.items():
        print(f"  {k:32s} {v:5,}")
    print(f"\n  -> {args.csv}")


if __name__ == "__main__":
    main()
