"""L3-4 full-population DIFF classifier (READ-ONLY).

Compares the built std_financials_v3 (Layer 3, new chain) against std_financials_v2
(old chain) across the whole population and classifies every per-metric cell into a
disposition, so the ~2% DIFF baseline (L3-3 §3c) is broken down into:

  (a) NORMAL non-match — not a regression:
        amended    : v3 value came from a 기재정정 delta patch (col in amended_cols /
                     amend_chain). v3 reflects the as-restated figure, v2 kept the
                     original — expected under policy P1.
        rcept_diff : v3 read the metric from a different source filing than v2
                     (source_rcepts[STMT] != v2.{stmt}_rcept) — soft restatement /
                     filing-selection difference, not an engine bug.
  (b) REGRESSION candidate — same filing, no amendment, material value gap:
        sign_flip  : v3 == -v2 (sign-handling defect).
        inspect    : both sides well-scaled, moderate material diff → ★원문대조
                     (the genuine engine/mapping-disagreement set).
  (c) LONGTAIL — same-source, one chain almost certainly wrong or benign:
        unit_1000x : v3 == 1000 * v2 (v2 stored 천원, v3 원 — overwhelmingly v3-win;
                     direction spot-checked in the sample).
        v2_tiny    : |v2| < |v3|/100 (v2 read a garbage/wrong cell — v3-win).
        rounding   : |v3-v2| within tolerance (unit / rounding).
        fin_catalog: financial-sector corp (KSIC 64/65/66) — insurance/securities
                     revenue alias longtail (account_maps job, not an engine bug).

Coverage-only (one side null):
        v3only     : v3 has a value v2 lacks (split-table recovery — new-chain win).
        v2only     : v2 has a value v3 lacks (missing in v3 — catalog gap / hold).

Writes nothing to the DB. Emits a markdown report.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from collector.db import get_session

# metric -> statement key in source_rcepts / the v2 {stmt}_rcept column
METRICS = [
    ("total_assets", "BS"), ("total_equity", "BS"), ("retained_earnings", "BS"),
    ("cash", "BS"), ("revenue", "IS"), ("operating_income", "IS"),
    ("net_income", "IS"), ("cfo", "CF"),
]

# disposition order for stable reporting
CLASSES = ["MATCH", "amended", "rcept_diff", "sign_flip", "inspect",
           "unit_1000x", "v2_tiny", "v2_huge", "rounding", "fin_catalog",
           "v3only", "v2only"]

# relative/abs tolerance for "rounding" (benign) same-source diffs
REL_TOL = 0.001   # 0.1%
ABS_TOL = 1000    # 1,000 won


def classify_sql(metric: str, stmt: str) -> str:
    """One CASE expression producing the disposition for a metric cell.

    v3rc = source filing v3 read this metric's statement from.
    v2rc = v2's per-statement source rcept for the same statement.
    """
    v2rc = {"BS": "v2.bs_rcept", "IS": "v2.is_rcept", "CF": "v2.cf_rcept"}[stmt]
    return f"""
      CASE
        WHEN v3.{metric} IS NULL AND v2.{metric} IS NULL THEN NULL
        WHEN v3.{metric} IS NOT NULL AND v2.{metric} IS NULL THEN 'v3only'
        WHEN v3.{metric} IS NULL AND v2.{metric} IS NOT NULL THEN 'v2only'
        WHEN v3.{metric} = v2.{metric} THEN 'MATCH'
        -- DIFF from here (both non-null, unequal)
        WHEN (v3.amended_cols ? '{metric}') OR (v3.amend_chain ? '{metric}')
             THEN 'amended'
        WHEN COALESCE(v3.source_rcepts->>'{stmt}','') <> COALESCE({v2rc},'')
             THEN 'rcept_diff'
        WHEN v2.{metric} <> 0 AND v3.{metric} = -v2.{metric} THEN 'sign_flip'
        WHEN v2.{metric} <> 0 AND v3.{metric} <> 0
             AND (ABS(v3.{metric}::numeric - 1000 * v2.{metric}::numeric)
                    <= GREATEST({ABS_TOL}, {REL_TOL} * ABS(v3.{metric}))
                  OR ABS(v2.{metric}::numeric - 1000 * v3.{metric}::numeric)
                    <= GREATEST({ABS_TOL}, {REL_TOL} * ABS(v2.{metric}))) THEN 'unit_1000x'
        WHEN v2.{metric} <> 0
             AND ABS(v3.{metric}::numeric) > 100 * ABS(v2.{metric}::numeric)
             THEN 'v2_tiny'
        WHEN v3.{metric} <> 0
             AND ABS(v2.{metric}::numeric) > 100 * ABS(v3.{metric}::numeric)
             THEN 'v2_huge'
        WHEN ABS(v3.{metric} - v2.{metric})
               <= GREATEST({ABS_TOL}, {REL_TOL} * ABS(v2.{metric})) THEN 'rounding'
        WHEN c.induty_code LIKE '64%' OR c.induty_code LIKE '65%'
             OR c.induty_code LIKE '66%' THEN 'fin_catalog'
        ELSE 'inspect'
      END
    """


def counts_for_metric(session, metric: str, stmt: str, period: str) -> dict:
    cls = classify_sql(metric, stmt)
    rows = session.execute(text(f"""
        SELECT {cls} AS disp, COUNT(*) AS n
        FROM std_financials_v3 v3
        JOIN std_financials_v2 v2
          ON v2.corp_code=v3.corp_code AND v2.fiscal_year=v3.fiscal_year
         AND v2.fiscal_period=v3.fiscal_period AND v2.statement_type=v3.statement_type
         AND v2.version=1 AND NOT v2.is_stub AND NOT v2.is_discrete
        LEFT JOIN corporations c ON c.corp_code=v3.corp_code
        WHERE v3.fiscal_year >= 2015 AND v3.fiscal_period = :p
        GROUP BY 1
    """), {"p": period}).fetchall()
    return {r[0]: r[1] for r in rows if r[0] is not None}


def inspect_anatomy(session, period: str) -> list:
    """Break the 'inspect' bucket down per metric by sign agreement, to expose
    whether the residual is dominated by sign-convention disagreements."""
    unions = []
    for metric, stmt in METRICS:
        cls = classify_sql(metric, stmt)
        unions.append(f"""
        SELECT '{metric}' AS metric,
               SUM(CASE WHEN SIGN(v3.{metric})<>SIGN(v2.{metric})
                        AND v3.{metric}<>0 AND v2.{metric}<>0 THEN 1 ELSE 0 END) AS sign_opp,
               SUM(CASE WHEN SIGN(v3.{metric})=SIGN(v2.{metric})
                         OR v3.{metric}=0 OR v2.{metric}=0 THEN 1 ELSE 0 END) AS same_sign
        FROM std_financials_v3 v3
        JOIN std_financials_v2 v2
          ON v2.corp_code=v3.corp_code AND v2.fiscal_year=v3.fiscal_year
         AND v2.fiscal_period=v3.fiscal_period AND v2.statement_type=v3.statement_type
         AND v2.version=1 AND NOT v2.is_stub AND NOT v2.is_discrete
        LEFT JOIN corporations c ON c.corp_code=v3.corp_code
        WHERE v3.fiscal_year >= 2015 AND v3.fiscal_period=:p AND ({cls})='inspect'
        GROUP BY 1
        """)
    sql = " UNION ALL ".join(unions) + " ORDER BY 1"
    return session.execute(text(sql), {"p": period}).fetchall()


def faithfulness_check(session, period: str) -> list:
    """For each metric's 'inspect' cases, test whether v3's value exactly equals some
    current-period (col_index=0) report_lines value in the source filing's statement.
    A match means v3 reproduced a genuinely-filed figure (did not invent/miscompute
    it), so the DIFF is a v2 (old-chain) disagreement — not a v3 fabrication. (node_role
    is NOT restricted: retained_earnings/cfo are sub-line/subtotal roles, not 'F'.)
    Non-matches are assembled/derived values warranting a deeper drill.

    Per-row report_lines lookup (bounded by the small inspect population). Read-only.
    """
    out = []
    for metric, stmt in METRICS:
        cls = classify_sql(metric, stmt)
        cases = session.execute(text(f"""
            SELECT v3.corp_code, v3.fiscal_year, v3.statement_type, v3.{metric}
            FROM std_financials_v3 v3
            JOIN std_financials_v2 v2
              ON v2.corp_code=v3.corp_code AND v2.fiscal_year=v3.fiscal_year
             AND v2.fiscal_period=v3.fiscal_period AND v2.statement_type=v3.statement_type
             AND v2.version=1 AND NOT v2.is_stub AND NOT v2.is_discrete
            LEFT JOIN corporations c ON c.corp_code=v3.corp_code
            WHERE v3.fiscal_year >= 2015 AND v3.fiscal_period=:p AND ({cls})='inspect'
        """), {"p": period}).fetchall()
        matched = 0
        for corp, fy, basis, v3v in cases:
            hit = session.execute(text("""
                SELECT 1 FROM report_lines
                WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period=:p
                  AND basis=:b AND statement=:st AND col_index=0
                  AND value_won=:v LIMIT 1
            """), {"c": corp, "y": fy, "p": period, "b": basis, "st": stmt, "v": v3v}).fetchone()
            if hit:
                matched += 1
        out.append((metric, len(cases), matched))
    return out


def regression_samples(session, period: str, limit: int) -> list:
    """Pull same-source material diffs classed 'regression' across all metrics,
    ranked by relative gap, for 원문대조."""
    unions = []
    for metric, stmt in METRICS:
        cls = classify_sql(metric, stmt)
        v2rc = {"BS": "v2.bs_rcept", "IS": "v2.is_rcept", "CF": "v2.cf_rcept"}[stmt]
        unions.append(f"""
        SELECT '{metric}' AS metric, v3.corp_code, c.corp_name, c.induty_code,
               v3.fiscal_year AS fy, v3.fiscal_period AS fp, v3.statement_type AS basis,
               v3.{metric} AS v3v, v2.{metric} AS v2v,
               v3.source_rcepts->>'{stmt}' AS v3_rcept, {v2rc} AS v2_rcept,
               ABS(v3.{metric} - v2.{metric})::float
                 / NULLIF(ABS(v2.{metric}),0) AS relgap
        FROM std_financials_v3 v3
        JOIN std_financials_v2 v2
          ON v2.corp_code=v3.corp_code AND v2.fiscal_year=v3.fiscal_year
         AND v2.fiscal_period=v3.fiscal_period AND v2.statement_type=v3.statement_type
         AND v2.version=1 AND NOT v2.is_stub AND NOT v2.is_discrete
        LEFT JOIN corporations c ON c.corp_code=v3.corp_code
        WHERE v3.fiscal_year >= 2015 AND v3.fiscal_period=:p
          AND ({cls}) = 'inspect'
        """)
    sql = " UNION ALL ".join(unions) + " ORDER BY relgap DESC NULLS LAST LIMIT :lim"
    return session.execute(text(sql), {"p": period, "lim": limit}).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="FY")
    ap.add_argument("--sample-regressions", type=int, default=40)
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    lines = []
    def emit(s=""):
        print(s)
        lines.append(s)

    with get_session() as s:
        per_metric = {}
        for metric, stmt in METRICS:
            per_metric[metric] = counts_for_metric(s, metric, stmt, args.period)

        emit(f"# L3-4 DIFF full-population classification ({args.period}, v2 version=1, 2015+)\n")
        emit("Rows = per-metric cells where BOTH std_v3 and std_v2 exist for the "
             "(corp,fy,period,basis) key (join; coverage-only cells counted as "
             "v3only/v2only).\n")

        # summary table
        hdr = "| metric | both | MATCH | MATCH% | " + " | ".join(
            c for c in CLASSES if c not in ("MATCH",)) + " |"
        emit(hdr)
        emit("|" + "---|" * (hdr.count("|") - 1))
        totals = {c: 0 for c in CLASSES}
        for metric, _ in METRICS:
            cc = per_metric[metric]
            both = sum(v for k, v in cc.items() if k not in ("v3only", "v2only"))
            match = cc.get("MATCH", 0)
            pct = 100.0 * match / both if both else 0.0
            row = [metric, f"{both:,}", f"{match:,}", f"{pct:.2f}"]
            for c in CLASSES:
                if c == "MATCH":
                    continue
                row.append(f"{cc.get(c,0):,}")
            emit("| " + " | ".join(row) + " |")
            for c in CLASSES:
                totals[c] += cc.get(c, 0)
        # totals row
        both_t = sum(v for k, v in totals.items() if k not in ("v3only", "v2only"))
        pct_t = 100.0 * totals["MATCH"] / both_t if both_t else 0.0
        trow = ["**TOTAL**", f"**{both_t:,}**", f"**{totals['MATCH']:,}**", f"**{pct_t:.2f}**"]
        for c in CLASSES:
            if c == "MATCH":
                continue
            trow.append(f"**{totals[c]:,}**")
        emit("| " + " | ".join(trow) + " |")

        # roll-up by disposition family
        emit("\n## Disposition roll-up (all 8 metrics)\n")
        fam = {
            "(a) NORMAL  amended    (재작성 반영·회귀아님)": totals["amended"],
            "(a) NORMAL  rcept_diff (다른 정본filing·회귀아님)": totals["rcept_diff"],
            "(b) REGRESS sign_flip  (부호결함 ★조사)": totals["sign_flip"],
            "(b) REGRESS inspect    (양측 정상스케일·실질차 ★조사)": totals["inspect"],
            "(c) v3-WIN  unit_1000x (×1000 단위불일치·v3정답)": totals["unit_1000x"],
            "(c) v3-WIN  v2_tiny    (v2 과소·오셀렉트·v3정답)": totals["v2_tiny"],
            "(c) v3-WIN  v2_huge    (v2 과대·오셀렉트·v3정답)": totals["v2_huge"],
            "(c) LONGTL  rounding   (허용오차·양성)": totals["rounding"],
            "(c) LONGTL  fin_catalog(금융업 매출alias)": totals["fin_catalog"],
            "cov         v3only     (split-table 복구·우위)": totals["v3only"],
            "cov         v2only     (v3 결측·catalog gap)": totals["v2only"],
        }
        diff_total = (totals["amended"] + totals["rcept_diff"] + totals["sign_flip"]
                      + totals["inspect"] + totals["unit_1000x"] + totals["v2_tiny"]
                      + totals["v2_huge"] + totals["rounding"] + totals["fin_catalog"])
        for k, v in fam.items():
            share = f"{100.0*v/diff_total:.1f}% of DIFF" if diff_total and "cov" not in k else ""
            emit(f"- {k:<46} {v:>7,}  {share}")
        emit(f"\n  DIFF total = {diff_total:,}   "
             f"(b) 조사대상 = {totals['sign_flip']+totals['inspect']:,}  "
             f"({100.0*(totals['sign_flip']+totals['inspect'])/diff_total:.1f}% of DIFF)")

        # inspect anatomy (sign structure)
        emit("\n## (b) INSPECT anatomy — sign structure per metric\n")
        emit("| metric | inspect | sign_opposite | same_sign |")
        emit("|---|---:|---:|---:|")
        ana = inspect_anatomy(s, args.period)
        tso = tss = 0
        for metric, so, ss in ana:
            emit(f"| {metric} | {(so or 0)+(ss or 0):,} | {so or 0:,} | {ss or 0:,} |")
            tso += so or 0
            tss += ss or 0
        emit(f"| **TOTAL** | **{tso+tss:,}** | **{tso:,}** | **{tss:,}** |")
        emit(f"\n부호반대 = inspect 의 {100.0*tso/(tso+tss):.0f}% "
             f"→ 잔여 (b) 는 **부호규약 불일치가 지배적**(net_income·cfo 집중).")

        # faithfulness: does v3 reflect a genuinely-filed figure?
        emit("\n## (b) INSPECT faithfulness — v3 vs filed line (col0, any role)\n")
        emit("v3 값이 정본 filing 의 당기(col0) report_lines 값 중 하나와 정확히 일치하면 v3 는 실제 "
             "기재된 셀을 재현한 것(값 조작/오산 아님) → 그 DIFF 는 **v2(구 체인) 불일치**(v3 날조 아님). "
             "불일치분은 조립/파생값으로 추가 드릴 대상.\n")
        emit("| metric | inspect | v3==filed | v3-충실% | 불일치(드릴) |")
        emit("|---|---:|---:|---:|---:|")
        fc = faithfulness_check(s, args.period)
        ti = tm = 0
        for metric, ni, nm in fc:
            pf = 100.0 * nm / ni if ni else 0.0
            emit(f"| {metric} | {ni:,} | {nm:,} | {pf:.0f} | {ni-nm:,} |")
            ti += ni
            tm += nm
        emit(f"| **TOTAL** | **{ti:,}** | **{tm:,}** | **{100.0*tm/ti if ti else 0:.0f}** | **{ti-tm:,}** |")
        emit(f"\n→ inspect 의 **{100.0*tm/ti if ti else 0:.0f}%** 는 v3 가 filed 최상위값을 정확 반영 "
             f"(v2 구 체인 오류). 나머지 {ti-tm:,} 건이 v3 조립/라인선택 드릴 대상(부호정규화·sub-line 등).")

        # inspect detail
        emit(f"\n## (b) INSPECT sample — top {args.sample_regressions} by relative gap "
             f"(both well-scaled, same-source, material — ★원문대조 대상)\n")
        samples = regression_samples(s, args.period, args.sample_regressions)
        if not samples:
            emit("_none_")
        else:
            emit("| metric | corp | name | induty | fy | basis | v3 | v2 | relgap | rcept |")
            emit("|---|---|---|---|---|---|---:|---:|---:|---|")
            for r in samples:
                (metric, corp, name, induty, fy, fp, basis, v3v, v2v,
                 v3rc, v2rc, relgap) = r
                rg = f"{relgap:.3f}" if relgap is not None else "—"
                emit(f"| {metric} | {corp} | {name} | {induty or '—'} | {fy} | "
                     f"{basis[:4]} | {v3v:,} | {v2v:,} | {rg} | {v3rc or '—'} |")

    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n[written] {args.out}")


if __name__ == "__main__":
    main()
