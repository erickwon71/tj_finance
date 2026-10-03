"""L3-4 inspect drill (READ-ONLY): characterize the ~124 inspect cells where v3's value
does NOT equal any filed col0 report_lines value (the residual v3-drill targets).

For each such cell, decide — against the ORIGINAL report_lines (NOT v2, which is not
ground truth) — why v3 differs from a raw filed cell:

  sign_norm  : v3 == -(a filed col0 value) → loss sign-normalization (루닛형). v3 correct.
  derived    : metric is computed (gross_profit=rev-cogs 등) → not a single filed line.
  neg_match  : v3 == -(a filed value) but metric isn't a loss-line → inspect sign issue.
  amended    : v3 came from a 기재정정 delta patch (value not in the canonical filing's col0).
  unexplained: v3 matches no filed value nor its negation → ★genuine drill (wrong line/assembly).

Emits counts per metric + samples of `unexplained` (corp, labels/values) for 원문대조.
"""
from __future__ import annotations
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import get_session
from scripts.layer3_diff_classify import classify_sql, METRICS

DERIVED = {"gross_profit"}  # rev-cogs 등 (현재 8지표엔 없음, 방어적)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="FY")
    ap.add_argument("--show", type=int, default=6, help="unexplained samples per metric")
    args = ap.parse_args()

    with get_session() as s:
        summary = {}
        unexplained_samples = defaultdict(list)
        for metric, stmt in METRICS:
            cls = classify_sql(metric, stmt)
            cases = s.execute(text(f"""
                SELECT v3.corp_code, v3.fiscal_year, v3.statement_type, v3.{metric},
                       (v3.amended_cols ? '{metric}') OR (v3.amend_chain ? '{metric}') AS amended
                FROM std_financials_v3 v3
                JOIN std_financials_v2 v2
                  ON v2.corp_code=v3.corp_code AND v2.fiscal_year=v3.fiscal_year
                 AND v2.fiscal_period=v3.fiscal_period AND v2.statement_type=v3.statement_type
                 AND v2.version=1 AND NOT v2.is_stub AND NOT v2.is_discrete
                LEFT JOIN corporations c ON c.corp_code=v3.corp_code
                WHERE v3.fiscal_year >= 2015 AND v3.fiscal_period=:p AND ({cls})='inspect'
            """), {"p": args.period}).fetchall()

            kind = Counter()
            for corp, fy, basis, v3v, amended in cases:
                # filed col0 values for this metric's statement — BOTH bases (single-entity
                # corps file only one basis and v3 basis-fallbacks the other; querying just
                # v3.statement_type would false-flag those faithful copies as unexplained).
                vals = [r[0] for r in s.execute(text("""
                    SELECT DISTINCT value_won FROM report_lines
                    WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
                      AND statement=:st AND col_index=0 AND value_won IS NOT NULL
                """), {"c": corp, "y": fy, "p": args.period, "st": stmt}).fetchall()]
                vset = set(vals)
                if v3v in vset:
                    continue  # faithful (not a drill target)
                if metric in DERIVED:
                    kind["derived"] += 1
                elif v3v is not None and -v3v in vset:
                    # v3 is the negation of a filed value
                    kind["sign_norm" if metric in ("net_income", "operating_income",
                                                    "ebt", "controlling_ni") else "neg_match"] += 1
                elif amended:
                    kind["amended"] += 1
                else:
                    kind["unexplained"] += 1
                    if len(unexplained_samples[metric]) < args.show:
                        unexplained_samples[metric].append((corp, fy, basis, v3v, sorted(vset, key=lambda x: -abs(x))[:6]))
            summary[metric] = kind

        print(f"# L3-4 inspect drill — v3≠filed 미일치 유형 ({args.period})\n")
        cols = ["sign_norm", "neg_match", "amended", "derived", "unexplained"]
        print("| metric | 미일치 | " + " | ".join(cols) + " |")
        print("|" + "---|" * (len(cols) + 2))
        tot = Counter()
        for metric, _ in METRICS:
            k = summary[metric]
            n = sum(k.values())
            print(f"| {metric} | {n} | " + " | ".join(str(k.get(c, 0)) for c in cols) + " |")
            for c in cols:
                tot[c] += k.get(c, 0)
        print(f"| **TOTAL** | **{sum(tot.values())}** | " + " | ".join(f"**{tot.get(c,0)}**" for c in cols) + " |")

        print(f"\n## unexplained 표본 (★원문대조 대상) — v3v / filed col0 top값들")
        for metric, _ in METRICS:
            smp = unexplained_samples.get(metric, [])
            if not smp:
                continue
            print(f"\n### {metric}")
            for corp, fy, basis, v3v, tops in smp:
                nm = s.execute(text("SELECT corp_name FROM corporations WHERE corp_code=:c"), {"c": corp}).scalar()
                tops_s = ", ".join(f"{v:,}" for v in tops)
                print(f"  {nm} {fy} {basis[:4]}: v3={v3v:,}  filed≈[{tops_s}]")


if __name__ == "__main__":
    main()
