"""Ad-hoc (scratchpad only): for each of the 30 M3 groups, print the exact text of the
element(s) that blocked production's declaration_text()/inherited_declaration_text() --
evidence-gathering for the T4-4 whitelist design, not part of the fix itself."""
from __future__ import annotations

import csv
import glob
import os
import sys

_REPO_ROOT = "/Users/taejin/Project/tj_finance"
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text as sqltext                              # noqa: E402
from collector.db import get_session                                # noqa: E402
from parser.xml.dart_xml_parser import _parse_xml_file               # noqa: E402
from parser.common.amount_normalizer import detect_unit_tokens       # noqa: E402
from fin2.extract.statement_titles import _STMT_TITLE, SECTION_CODE_OF  # noqa: E402
from fin2.extract.text import _detect_fin_type, _detect_body_statement_tables  # noqa: E402
from fin2.extract.report_lines import (                              # noqa: E402
    _detect_pre2015_body_statement_tables_merged, _PRE2015_ROUTING_MAX_FY)

_RAW_ROOT = "/Volumes/dart_data/raw_report"
_MARKET_OF_CLS = {"Y": "KOSPI", "K": "KOSDAQ"}
_THRESHOLD = 1_000_000_000_000_000


def _find_file(corp_code, corp_cls, report_type, fiscal_year, rcept_no):
    market = _MARKET_OF_CLS.get(corp_cls)
    if market is None:
        return None
    corp_dirs = glob.glob(os.path.join(_RAW_ROOT, market, f"{corp_code}_*"))
    for cd in corp_dirs:
        for y in (fiscal_year, fiscal_year - 1, fiscal_year + 1):
            cand = os.path.join(cd, report_type, str(y), f"{rcept_no}.xml")
            if os.path.exists(cand):
                return cand
        hits = glob.glob(os.path.join(cd, report_type, "*", f"{rcept_no}.xml"))
        if hits:
            return hits[0]
    return None


def _route_groups(root, fiscal_year, fin_type):
    if fiscal_year <= _PRE2015_ROUTING_MAX_FY:
        return _detect_pre2015_body_statement_tables_merged(root, fin_type)
    return _detect_body_statement_tables(root, fin_type, include_sce=True)


def _find_table_for_value(root, fiscal_year, fin_type, statement, basis, raw_str):
    section_code = SECTION_CODE_OF.get((basis, statement))
    if section_code is None:
        return None
    groups = _route_groups(root, fiscal_year, fin_type)
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


def _probe_with_trace(tbl, span=15):
    """Same walk as the real _extended_probe, but records every skipped sibling's text."""
    skipped = []
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
                prev = prev.getprevious()
                continue
            if detect_unit_tokens(txt):
                return txt, skipped
            return None, skipped
        if txt:
            if any(p.search(txt) for p, _ in _STMT_TITLE):
                return None, skipped
            if detect_unit_tokens(txt):
                return txt, skipped
            skipped.append(txt)
        prev = prev.getprevious()
    return None, skipped


def main():
    rows = list(csv.DictReader(open(os.path.join(
        _REPO_ROOT, "scripts", "scan_t4_2b_m2_m3_split_2026-08-16_results.csv"))))
    m3 = [r for r in rows if r["classification"] == "M3"]

    with get_session() as s:
        for r in m3:
            g = s.execute(sqltext("""
                SELECT f.report_type, f.fiscal_year, f.corp_cls, rl.adecimal,
                       max(abs(rl.value_won)) AS maxv
                FROM report_lines rl JOIN filings f USING (rcept_no)
                WHERE rl.rcept_no=:rc AND rl.statement=:st AND rl.basis=:b
                  AND rl.unit_source='doc_default' AND abs(rl.value_won) > :t
                GROUP BY 1,2,3,4
            """), {"rc": r["rcept_no"], "st": r["statement"], "b": r["basis"],
                   "t": _THRESHOLD}).fetchone()
            path = _find_file(r["corp_code"], g.corp_cls, g.report_type, g.fiscal_year, r["rcept_no"])
            if path is None:
                print(f"{r['rcept_no']} {r['corp_code']} -- file not found")
                continue
            root = _parse_xml_file(path)
            fin_type = _detect_fin_type(root)
            multiplier = 10 ** abs(g.adecimal) if g.adecimal else 1
            raw = g.maxv // multiplier if multiplier else g.maxv
            raw_str = f"{raw:,}"
            tbl = _find_table_for_value(root, g.fiscal_year, fin_type, r["statement"], r["basis"], raw_str)
            if tbl is None:
                print(f"{r['rcept_no']} {r['corp_code']} -- table not found")
                continue
            found, skipped = _probe_with_trace(tbl)
            print(f"{r['rcept_no']} {r['corp_code']} {r['statement']}/{r['basis']}  "
                  f"skipped={skipped!r}")


if __name__ == "__main__":
    main()
