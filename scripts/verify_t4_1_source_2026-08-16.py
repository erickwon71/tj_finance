"""
R28 follow-up track T4-1 -- source verification for the 5 sampled unit-overscale rows.
(docs/plans/eps_r28_followup_tracks_design_2026-08-16.md §5, T4-1.)

For each sample this re-derives, straight from the raw XML (SD/NAS `raw_report`, EUC-KR
despite the `encoding="utf-8"` header -- a known DART legacy quirk), three facts:
  1. the raw (unscaled) value actually written in the source table
  2. the unit declaration text governing that table, and where it sits structurally
     relative to the data table (title-table sibling / table's own first row / an
     intervening element / genuinely absent)
  3. whether DB's `value_won` = raw x declared/doc-default multiplier (confirms the
     parser applied the multiplier it says it applied -- i.e. this is not a second,
     independent bug)

Does NOT decide a fix. Only establishes ground truth for the T4-3 design decision.

Usage:
  .venv/bin/python scripts/verify_t4_1_source_2026-08-16.py
"""
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text as sqltext          # noqa: E402

from collector.db import get_session            # noqa: E402

SAMPLES = [
    dict(rcept="20040623000255", corp="00117212", label="두산 2003FY CF consolidated "
         "(doc_default) -- title table's own unit cell is present but BLANK",
         file=os.path.join(_REPO_ROOT, "raw_report/KOSPI/00117212_두산/annual/2003/"
                            "20040623000255.xml"),
         needle="4,957,820,592"),
    dict(rcept="20050516001328", corp="00153393", label="태광산업 2005Q1 SCE consolidated "
         "(doc_default) -- title table has NO unit line at all",
         file=os.path.join(_REPO_ROOT, "raw_report/KOSPI/00153393_태광산업/quarter/2005/"
                            "20050516001328.xml"),
         needle="5,567,000,000"),
    dict(rcept="20130828000220", corp="00359623", label="우리산업홀딩스 2013H1 SCE "
         "consolidated (declared) -- title table DOES declare '(단위 : 백만원)', but the "
         "raw cell is a plain 원 figure",
         file=os.path.join(_REPO_ROOT, "raw_report/KOSDAQ/00359623_우리산업홀딩스/half/"
                            "2013/20130828000220.xml"),
         needle="6,077,715,000"),
    dict(rcept="20220322000790", corp="00176835", label="NH농우바이오 2021FY SCE "
         "consolidated (declared, 2020+) -- same pattern as above",
         file=os.path.join(_REPO_ROOT, "raw_report/KOSDAQ/00176835_NH농우바이오/annual/"
                            "2021/20220322000790.xml"),
         needle="8,015,280,500"),
    dict(rcept="20220317001218", corp="01113499", label="아이티센피엔에스 2021FY BS "
         "separate (doc_default, 2020+) -- title table DOES declare '(단위: 원)' 2 "
         "siblings back, but an intervening disclaimer <P> blocks both "
         "declaration_text()'s clause-3 walk and inherited_declaration_text()'s "
         "single-hop check",
         file=os.path.join(_REPO_ROOT, "raw_report/KOSDAQ/01113499_아이티센피엔에스/"
                            "annual/2021/20220317001218.xml"),
         needle="7,324,129,549"),
]


def _decode(path: str) -> str:
    data = open(path, "rb").read()
    return data.decode("euc-kr", errors="replace")


def main():
    with get_session() as s:
        for spec in SAMPLES:
            print(f"\n{'='*100}\n{spec['rcept']} {spec['corp']} -- {spec['label']}")
            if not os.path.exists(spec["file"]):
                print(f"  !! FILE NOT FOUND: {spec['file']}")
                continue
            t = _decode(spec["file"])
            idx = t.find(spec["needle"])
            print(f"  raw needle {spec['needle']!r} found at byte {idx}")
            if idx == -1:
                continue
            unit_matches = [m.start() for m in re.finditer("단위", t[:idx])]
            if unit_matches:
                near = unit_matches[-1]
                snippet = re.sub(r"\s+", " ", t[max(0, near - 60):near + 40])
                print(f"  nearest preceding '단위' occurrence: {snippet!r}")
            else:
                print("  no '단위' occurrence anywhere before this point in the document")

            rows = s.execute(sqltext("""
                SELECT statement, basis, adecimal, unit_source, value_won,
                       left(regexp_replace(label_raw, '\\s+', ' ', 'g'), 60) AS label
                FROM report_lines
                WHERE rcept_no = :r AND value_won::text LIKE :needle
                LIMIT 3
            """), {"r": spec["rcept"], "needle": f"%{spec['needle'].replace(',', '')}%"}).fetchall()
            for row in rows:
                print(f"  DB: {row.statement}/{row.basis} adecimal={row.adecimal} "
                      f"src={row.unit_source} value_won={row.value_won:,} label={row.label!r}")


if __name__ == "__main__":
    main()
