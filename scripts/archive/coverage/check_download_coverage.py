"""
Download coverage verification tool
=====================================
For every DART filing registered per company, shows whether the file was
actually saved on disk (xml / pdf / html-full / html-partial).

Includes special handling for:
  - Amendment pairs: both original and amendment rows shown together
  - HTML files: full vs DART-viewer partial detection (file content heuristic)

Output is raw status — no interpretation or auto-fixing.

Usage:
    python3 scripts/check_download_coverage.py [--output PATH] [--since YEAR]
                                                [--market MARKET] [--corp CORP_CODE]

Status codes in output:
    OK(xml,1240KB)      - completed, file present on disk
    OK(pdf,890KB)       - completed, file present on disk
    OK(html-full,...)   - completed, HTML with full report content
    OK(html-partial,...) - completed, HTML is DART viewer iframe only
    PEND                - task exists, status=pending or failed
    NOTASK              - filing in DB but no download_tasks row
    LOST                - task=completed but file missing from disk
"""
import argparse
import os
from collections import defaultdict
from datetime import datetime

import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"

REPORT_TYPE_LABEL = {"annual": "FY-report", "half": "H-report", "quarter": "Q-report"}
PERIOD_ORDER      = {"Q1": 0, "H1": 1, "Q3": 2, "FY": 3}


# ── DB query ─────────────────────────────────────────────────────────────────

def fetch_filings(since_year: int, market, corp_code) -> list[dict]:
    conn = psycopg2.connect(DB_DSN)
    cur  = conn.cursor()

    clauses = ["c.is_active = TRUE", "f.report_type IS NOT NULL", "f.fiscal_year >= %s"]
    params  = [since_year]

    if market:
        clauses.append("c.market = %s")
        params.append(market.upper())
    if corp_code:
        clauses.append("c.corp_code = %s")
        params.append(corp_code)

    where = " AND ".join(clauses)
    cur.execute(f"""
        SELECT
            c.corp_code,
            c.corp_name,
            COALESCE(c.market, '?')  AS market,
            f.rcept_no,
            f.report_type,
            f.fiscal_year,
            f.fiscal_period,
            f.filed_at,
            f.is_amendment,
            f.is_final,
            dt.status       AS task_status,
            dt.file_type,
            dt.file_size,
            dt.file_path
        FROM corporations c
        JOIN filings f ON f.corp_code = c.corp_code
        LEFT JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
        WHERE {where}
        ORDER BY
            c.corp_name,
            c.corp_code,
            f.fiscal_year   DESC,
            f.fiscal_period,
            f.is_amendment  ASC,
            f.filed_at      ASC,
            f.rcept_no      ASC
    """, params)

    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


# ── HTML classification ───────────────────────────────────────────────────────

def _classify_html(file_path: str, file_size) -> str:
    """Return 'html-full' or 'html-partial' based on file content."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(10240).decode("utf-8", errors="replace")
        if "viewer.do" in header or "<iframe" in header.lower():
            label = "html-partial"
        else:
            label = "html-full"
    except Exception:
        label = "html-?"
    kb = f"{(file_size or 0) / 1024:.0f}KB"
    return f"{label},{kb}"


# ── Status string ─────────────────────────────────────────────────────────────

def _status_str(row: dict) -> str:
    task_status = row["task_status"]
    file_type   = row["file_type"]
    file_size   = row["file_size"]
    file_path   = row["file_path"]

    if task_status is None:
        return "NOTASK"

    if task_status in ("pending", "failed"):
        return f"PEND({task_status})"

    if task_status == "skipped":
        return "SKIP"

    if task_status == "completed":
        if not file_path or not os.path.exists(file_path):
            return "LOST"
        if file_type in ("html", "htm"):
            detail = _classify_html(file_path, file_size)
        else:
            kb     = f"{(file_size or 0) / 1024:.0f}KB"
            detail = f"{file_type or '?'},{kb}"
        return f"OK({detail})"

    return f"?({task_status})"


# ── Output builder ─────────────────────────────────────────────────────────────

def build_output(rows: list[dict], since_year: int) -> list[str]:
    lines        = []
    current_year = datetime.now().year

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append("=" * 110)
    lines.append("  TJ Finance — Download Coverage Verification")
    lines.append(f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Since     : {since_year}")
    lines.append("  Status codes: OK(type,size) | PEND | NOTASK | LOST | SKIP")
    lines.append("  GroupOK   : Y = original+all amendments OK  |  N = any gap  |  - = amendment row")
    lines.append("=" * 110)
    lines.append("")

    # ── Group rows by company, then by (fiscal_year, fiscal_period, report_type) ──
    # Build corp → list[row] preserving DB order
    corp_rows: dict[str, list[dict]] = defaultdict(list)
    corp_meta: dict[str, dict] = {}
    for r in rows:
        cc = r["corp_code"]
        corp_rows[cc].append(r)
        corp_meta[cc] = {"corp_name": r["corp_name"], "market": r["market"]}

    # Global stats
    stat: dict[str, int] = defaultdict(int)
    amend_groups_total   = 0
    amend_groups_ok      = 0
    gap_corps: list[str] = []   # corps with any GroupOK=N

    col_w = {
        "year": 4, "period": 6, "filed": 10, "rcept": 14, "am": 5,
        "status": 30, "groupok": 7,
    }
    hdr = (
        f"  {'Year':>{col_w['year']}}  {'Period':<{col_w['period']}}  "
        f"{'filed_at':<{col_w['filed']}}  {'rcept_no':<{col_w['rcept']}}  "
        f"{'A/M':<{col_w['am']}}  {'Status':<{col_w['status']}}  GroupOK"
    )
    sep = "  " + "-" * (len(hdr) - 2)

    for cc, c_rows in corp_rows.items():
        meta  = corp_meta[cc]
        lines.append("─" * 110)
        lines.append(f"  {cc}  {meta['corp_name']}  [{meta['market']}]")
        lines.append(hdr)
        lines.append(sep)

        # Group into (fiscal_year, fiscal_period, report_type) clusters
        group_key = lambda r: (r["fiscal_year"], r["fiscal_period"], r["report_type"])
        current_group = None
        group_rows: list[dict] = []
        corp_has_gap = False

        def flush_group(g_rows: list[dict]) -> bool:
            """Write group rows, return True if group is OK."""
            nonlocal amend_groups_total, amend_groups_ok
            has_amendment = any(r["is_amendment"] for r in g_rows)
            if has_amendment:
                amend_groups_total += 1

            group_ok = all(
                _status_str(r).startswith("OK") for r in g_rows
            )
            if has_amendment and group_ok:
                amend_groups_ok += 1

            for i, r in enumerate(g_rows):
                am_label  = "AMEND" if r["is_amendment"] else "Orig"
                status    = _status_str(r)
                groupok   = ""
                if not r["is_amendment"]:  # only on original row
                    groupok = "Y" if group_ok else "N"

                # accumulate global stats
                if status.startswith("OK"):
                    ft = r["file_type"] or "?"
                    if ft in ("html", "htm"):
                        if "html-full" in status:
                            stat["OK(html-full)"] += 1
                        else:
                            stat["OK(html-partial)"] += 1
                    else:
                        stat[f"OK({ft})"] += 1
                elif status.startswith("PEND"):
                    stat["PEND"] += 1
                elif status == "NOTASK":
                    stat["NOTASK"] += 1
                elif status == "LOST":
                    stat["LOST"] += 1
                elif status == "SKIP":
                    stat["SKIP"] += 1

                filed = r["filed_at"].strftime("%Y-%m-%d") if r["filed_at"] else "????-??-??"
                lines.append(
                    f"  {r['fiscal_year']:>{col_w['year']}}  "
                    f"{r['fiscal_period']:<{col_w['period']}}  "
                    f"{filed:<{col_w['filed']}}  "
                    f"{r['rcept_no']:<{col_w['rcept']}}  "
                    f"{am_label:<{col_w['am']}}  "
                    f"{status:<{col_w['status']}}  "
                    f"{groupok}"
                )
            return group_ok

        for r in c_rows:
            gk = group_key(r)
            if gk != current_group:
                if group_rows:
                    ok = flush_group(group_rows)
                    if not ok:
                        corp_has_gap = True
                group_rows   = []
                current_group = gk
            group_rows.append(r)
            stat["total"] += 1

        if group_rows:
            ok = flush_group(group_rows)
            if not ok:
                corp_has_gap = True

        lines.append("")

        if corp_has_gap:
            gap_corps.append(f"  {cc}  {meta['corp_name']:30s}  [{meta['market']}]")

    # ── Summary ─────────────────────────────────────────────────────────────
    lines.append("=" * 110)
    lines.append("  Coverage Summary")
    lines.append("=" * 110)
    lines.append(f"  Companies with data   : {len(corp_rows):,}")
    lines.append(f"  Filings inspected     : {stat['total']:,}")
    lines.append("")
    lines.append("  By status:")
    for key in ["OK(xml)", "OK(xbrl)", "OK(pdf)", "OK(html-full)", "OK(html-partial)",
                "PEND", "NOTASK", "LOST", "SKIP"]:
        if stat[key]:
            lines.append(f"    {key:<22s}: {stat[key]:,}")
    lines.append("")
    lines.append(f"  Amendment groups      : {amend_groups_total:,}")
    lines.append(f"    Both orig+all OK    : {amend_groups_ok:,}")
    lines.append(f"    Some missing        : {amend_groups_total - amend_groups_ok:,}")
    lines.append("")

    if gap_corps:
        lines.append(f"  ── Companies with GroupOK=N gaps ({len(gap_corps)}) ──")
        lines.extend(gap_corps[:300])
        if len(gap_corps) > 300:
            lines.append(f"  ... and {len(gap_corps)-300} more")
        lines.append("")

    lines.append("=" * 110)
    lines.append(f"  Total records: {stat['total']:,}")
    lines.append("=" * 110)

    return lines


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download coverage verification tool")
    parser.add_argument("--output", "-o", default="download_coverage.txt")
    parser.add_argument("--since",  type=int, default=2000,
                        help="Earliest fiscal_year to include (default: 2000)")
    parser.add_argument("--market", choices=["KOSPI", "KOSDAQ"], default=None)
    parser.add_argument("--corp",   default=None, metavar="CORP_CODE",
                        help="Single company spot-check")
    args = parser.parse_args()

    print(f"[1/3] Querying DB... (since={args.since}, market={args.market or 'all'}"
          + (f", corp={args.corp}" if args.corp else "") + ")")
    rows = fetch_filings(args.since, args.market, args.corp)
    print(f"      → {len(rows):,} filing rows")

    print("[2/3] Building output...")
    lines = build_output(rows, args.since)

    print(f"[3/3] Writing: {args.output}")
    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    size_kb = os.path.getsize(args.output) / 1024
    print(f"Done: {args.output} ({size_kb:,.0f} KB, {len(lines):,} lines)")


if __name__ == "__main__":
    main()
