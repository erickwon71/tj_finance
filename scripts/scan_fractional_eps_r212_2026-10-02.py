"""R212 target scan — 2015+ filings whose source prints a fractional EPS (13.42).

Two passes (read-only, no DB writes):
  1. regex prefilter on the source XML: a <TR> that contains '주당' and a cell holding a number
     with a non-zero fraction (notes' EPS tables match too — pass 2 drops those);
  2. re-extract the prefiltered filing with the production HTML extractor and keep it only when
     an IS line gets `value_exact` (the fraction survives into a statement EPS row).
Bulk reads go to the SD-card mirror (/Volumes/dart_data/raw_report), NAS only as fallback.

Output: docs/qa/eps_fractional_targets_2026-10-02.txt (one rcept_no per line) and a .tsv with
corp/year/period and the exact values found.

Run: python scripts/scan_fractional_eps_r212_2026-10-02.py --shard 0/4 (… 3/4, in parallel), then --merge
"""
from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

NAS_PREFIX = "/Users/taejin/Project/tj_finance/raw_report/"
SD_PREFIX = "/Volumes/dart_data/raw_report/"
OUT_TXT = ROOT / "docs/qa/eps_fractional_targets_2026-10-02.txt"
OUT_TSV = ROOT / "docs/qa/eps_fractional_targets_2026-10-02.tsv"

_TR_RE = re.compile(r"<TR[^>]*>(.*?)</TR>", re.S | re.I)
_FRAC_CELL_RE = re.compile(r">\s*\(?\s*-?\s*[0-9][0-9,]*\.[0-9]*[1-9][0-9]*\s*\)?\s*(?:원)?\s*<")

_SQL = """
    SELECT DISTINCT ON (rl.rcept_no) rl.rcept_no, rl.corp_code, rl.report_fiscal_year,
           rl.report_fiscal_period, dt.file_path
    FROM report_lines rl
    JOIN download_tasks dt ON dt.rcept_no = rl.rcept_no AND dt.status = 'completed'
                          AND dt.file_type = 'xml' AND dt.file_path IS NOT NULL
    WHERE rl.statement = 'IS' AND rl.report_fiscal_year >= 2015
      AND (rl.label_raw LIKE '%주당%' OR rl.section_path LIKE '%주당%')
    ORDER BY rl.rcept_no, dt.id DESC
"""


def _resolve(fp: str) -> Path | None:
    if fp.startswith(NAS_PREFIX):
        sd = Path(SD_PREFIX + fp[len(NAS_PREFIX):])
        if sd.exists():
            return sd
    p = Path(fp)
    return p if p.exists() else None


def _check(job: tuple) -> tuple | None:
    rcept, corp, fy, fp_, path = job
    src = _resolve(path)
    if src is None:
        return ("missing", rcept, corp, fy, fp_, "")
    raw = src.read_bytes()
    try:  # some filings declare utf-8 but are EUC-KR (비투엔 20210317000884)
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp949", errors="ignore")
    if not any("주당" in tr and _FRAC_CELL_RE.search(tr) for tr in _TR_RE.findall(text)):
        return None
    from fin2.extract.report_lines import extract_report_lines
    try:
        lines = extract_report_lines(src, rcept_no=rcept, corp_code=corp,
                                     report_fiscal_year=fy, report_fiscal_period=fp_)
    except Exception as exc:  # report, do not guess
        return ("error", rcept, corp, fy, fp_, f"{type(exc).__name__}: {exc}"[:120])
    hits = [f"{l.basis}:{l.label_raw[:20]}:{l.col_index}={l.value_exact}"
            for l in lines if l.statement == "IS" and l.value_exact is not None]
    return ("target", rcept, corp, fy, fp_, "; ".join(hits)) if hits else ("prefilter_only", rcept, corp, fy, fp_, "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shard", default="", help="i/n — scan every n-th filing from i (parallel runs)")
    ap.add_argument("--merge", action="store_true", help="merge shard outputs into the final files")
    a = ap.parse_args()
    if a.merge:
        # report_lines keeps col_index 0 only (IS): a prior-period-only fraction never changes
        # the stored data, so only filings with a current-period (":0=") hit are targets
        rows = sorted({line for f in OUT_TSV.parent.glob(OUT_TSV.stem + ".shard*.tsv")
                       for line in f.read_text().splitlines() if line and ":0=" in line},
                      key=lambda l: l.split("\t")[0])
        OUT_TXT.write_text("".join(l.split("\t")[0] + "\n" for l in rows))
        OUT_TSV.write_text("rcept_no\tcorp_code\tfiscal_year\tfiscal_period\texact_values\n"
                           + "".join(l + "\n" for l in rows))
        print(f"merged {len(rows)} targets -> {OUT_TXT}")
        return
    from sqlalchemy import text
    from collector.db import engine
    with engine.connect() as c:
        jobs = [tuple(r) for r in c.execute(text(_SQL)).fetchall()]
    tag = ""
    if a.shard:
        i, n = map(int, a.shard.split("/"))
        jobs, tag = jobs[i::n], f".shard{i}of{n}"
    if a.limit:
        jobs = jobs[:a.limit]
    # targets are appended as they are found, so a run cut short keeps what it scanned
    out = OUT_TSV.with_name(OUT_TSV.stem + (tag or ".shard0of1") + ".tsv")
    out.write_text("")
    print(f"filings with IS EPS rows (2015+){tag}: {len(jobs)}", flush=True)
    counts: dict[str, int] = {}
    with ProcessPoolExecutor(a.workers) as ex, out.open("a") as fh:
        for i, res in enumerate(ex.map(_check, jobs, chunksize=32), 1):
            if res is not None:
                counts[res[0]] = counts.get(res[0], 0) + 1
                if res[0] == "target":
                    fh.write("\t".join(map(str, res[1:])) + "\n")
                    fh.flush()
                elif res[0] in ("missing", "error"):
                    print("\t".join(map(str, res)), flush=True)
            if i % 5000 == 0:
                print(f"{i}/{len(jobs)} {counts}", flush=True)
    print(f"done: scanned {len(jobs)} {counts} -> {out}", flush=True)


if __name__ == "__main__":
    main()
