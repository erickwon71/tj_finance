"""2015+ BS/IS/CF 항목수 분포 분석 — 대표필링(그룹별 BS+IS+CF 합산 최다) 선정 후
statement×basis 항목수 분포 통계 + outlier(저조 필링) CSV 추출.

배경: 사용자 요청("2015+ 전체 BS/IS/CF 연결/별도 항목수 분포 보고, 최초보고서에
누락되어 정정보고서에서 추가된 것들은 제외")으로 2026-09-13 작성한 분포 리포트
(artifact)의 재계산용 스크립트 — 원래 스크래치패드에서 1회성으로 돌렸던 걸
다음 세션에서도 재사용할 수 있게 정식 스크립트로 옮김.

대표필링 선정 규칙: 같은 (corp_code, fiscal_year, fiscal_period) 그룹에서
report_lines(BS+IS+CF) 합산 행수가 가장 많은 rcept_no를 그 그룹의 대표로 삼는다
— "최초보고서 결측 + 정정보고서가 채움" 패턴에서 자동으로 정정본이 이긴다.

★2026-09-13 후속(같은 날, R107~R110 연결비대상 확정 작업 완료 후 사용자 요청) —
`filings.consolidation_evidence='no_consolidated_fs_track1'`로 확정된(원문이 "연결
재무제표 없음"을 직접 선언한) 필링은 `*_consolidated` 분포에서 제외한다. 이런
필링은 애초에 연결데이터가 존재하면 안 되는 기간이라, 어쩌다 남아있는 값(과거
결함의 잔재 등)이 연결 항목수 분포를 왜곡하지 않도록 한다. `*_separate` 분포는
영향 없음(별도는 연결 존재여부와 무관하게 항상 있어야 함).

사용:
    python scripts/analyze_2015plus_statement_item_counts_2026-09-13.py
    python scripts/analyze_2015plus_statement_item_counts_2026-09-13.py --outlier-max 3 --outlier-key IS_separate
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

_SQL = """
    WITH universe AS (
        SELECT c.corp_code, c.corp_name, c.market FROM corporations c
        WHERE c.is_active AND c.stock_code IS NOT NULL
          AND c.stock_code NOT LIKE '9%%'
          AND c.coverage_class = 'periodic'
    ),
    targets AS (
        SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, f.report_type
        FROM filings f
        JOIN universe u ON u.corp_code = f.corp_code
        WHERE f.report_type IN ('annual', 'half', 'quarter')
          AND f.fiscal_year >= :fy_min
          AND f.report_nm NOT LIKE '%%제출기한연장%%'
    ),
    line_counts AS (
        SELECT rcept_no, statement, basis, count(*) as n
        FROM report_lines
        WHERE statement IN ('BS', 'IS', 'CF')
        GROUP BY rcept_no, statement, basis
    ),
    total_per_filing AS (
        SELECT t.rcept_no, t.corp_code, t.fiscal_year, t.fiscal_period, t.report_type,
               COALESCE(SUM(lc.n), 0)::int as total_lines
        FROM targets t
        LEFT JOIN line_counts lc ON lc.rcept_no = t.rcept_no
        GROUP BY t.rcept_no, t.corp_code, t.fiscal_year, t.fiscal_period, t.report_type
    ),
    ranked AS (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY corp_code, fiscal_year, fiscal_period
            ORDER BY total_lines DESC, rcept_no DESC
        ) as rn
        FROM total_per_filing
    ),
    representative AS (
        SELECT * FROM ranked WHERE rn = 1
    )
    SELECT r.rcept_no, r.corp_code, r.fiscal_year, r.fiscal_period, r.report_type,
           r.total_lines, u.corp_name, u.market,
           lc.statement, lc.basis, lc.n,
           f.consolidation_evidence
    FROM representative r
    JOIN universe u ON u.corp_code = r.corp_code
    LEFT JOIN line_counts lc ON lc.rcept_no = r.rcept_no
    LEFT JOIN filings f ON f.rcept_no = r.rcept_no
"""

_NO_CONSOLIDATED_FS = "no_consolidated_fs_track1"


def load_by_filing(fy_min: int) -> dict[str, dict]:
    with get_session() as s:
        rows = list(s.execute(text(_SQL), {"fy_min": fy_min}).mappings())

    by_filing: dict[str, dict] = {}
    for r in rows:
        key = r["rcept_no"]
        if key not in by_filing:
            by_filing[key] = {
                "rcept_no": r["rcept_no"],
                "corp_code": r["corp_code"], "corp_name": r["corp_name"], "market": r["market"],
                "fiscal_year": r["fiscal_year"], "fiscal_period": r["fiscal_period"],
                "report_type": r["report_type"], "total_lines": r["total_lines"],
                "no_consolidated_fs": r["consolidation_evidence"] == _NO_CONSOLIDATED_FS,
                "counts": {},
            }
        if r["statement"] is not None:
            by_filing[key]["counts"][f"{r['statement']}_{r['basis']}"] = r["n"]
    return by_filing


def print_distribution(by_filing: dict[str, dict]) -> None:
    dist = defaultdict(list)
    excluded_consolidated = 0
    for v in by_filing.values():
        for k, n in v["counts"].items():
            # ★연결비대상 확정 필링은 *_consolidated 분포에서 제외(위 모듈 docstring 참고).
            if k.endswith("_consolidated") and v["no_consolidated_fs"]:
                excluded_consolidated += 1
                continue
            dist[k].append(n)
    logger.info(f"연결비대상 확정으로 *_consolidated 분포에서 제외된 (필링×statement) "
                f"{excluded_consolidated:,}건")

    logger.info(f"대표필링 {len(by_filing):,}건")
    empty = [v for v in by_filing.values() if v["total_lines"] == 0]
    logger.info(f"완전 결측(BS+IS+CF 전무) {len(empty)}건")
    for v in empty:
        logger.info(f"  {v['rcept_no']} {v['corp_name']} {v['fiscal_year']}{v['fiscal_period']}")

    for key in ["BS_consolidated", "BS_separate", "IS_consolidated", "IS_separate",
                "CF_consolidated", "CF_separate"]:
        vals = sorted(dist.get(key, []))
        if not vals:
            continue
        n = len(vals)
        def pct(p, vals=vals, n=n):
            return vals[min(n - 1, int(n * p))]
        logger.info(f"{key}: n={n:,} min={vals[0]} p25={pct(0.25)} median={pct(0.5)} "
                    f"p75={pct(0.75)} max={vals[-1]} mean={round(statistics.mean(vals), 1)}")
    return dist


# 아티팩트 히스토그램 구간(2026-09-13 원래 리포트와 동일 경계 유지 — 재현성).
_BIN_EDGES = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 100, None]
_BIN_LABELS = ["0-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39",
               "40-44", "45-49", "50-59", "60-69", "70-79", "80-99", "100+"]


def histogram(vals: list[int]) -> dict:
    hist = [0] * len(_BIN_LABELS)
    for v in vals:
        for i, hi in enumerate(_BIN_EDGES[1:]):
            if hi is None or v < hi:
                hist[i] += 1
                break
    return {
        "hist": hist, "n": len(vals), "min": min(vals), "max": max(vals),
        "median": statistics.median(vals),
        "mean": round(statistics.mean(vals), 1),
    }


def build_hist_json(dist: dict) -> dict:
    series = {}
    for key in ["BS_consolidated", "BS_separate", "IS_consolidated", "IS_separate",
                "CF_consolidated", "CF_separate"]:
        vals = dist.get(key, [])
        if vals:
            series[key] = histogram(vals)
    return {"labels": _BIN_LABELS, "series": series}


def print_report_type_medians(by_filing: dict[str, dict]) -> None:
    by_rt = defaultdict(lambda: defaultdict(list))
    counts = Counter()
    for v in by_filing.values():
        rt = v["report_type"]
        counts[rt] += 1
        for k, n in v["counts"].items():
            if k.endswith("_consolidated") and v["no_consolidated_fs"]:
                continue
            by_rt[rt][k].append(n)
    logger.info("보고서유형별 중앙값(연결비대상 제외):")
    for rt in ("annual", "half", "quarter"):
        meds = {k: (statistics.median(v) if v else None) for k, v in by_rt[rt].items()}
        logger.info(f"  {rt}: {meds} 건수={counts[rt]:,}")


def write_outlier_csv(by_filing: dict[str, dict], key: str, out_path: Path,
                       max_n: int | None = None, min_n: int | None = None) -> None:
    """max_n(저조 필링, <=)와 min_n(과다 필링, >=) 중 지정된 쪽만 적용(둘 다 줄 수도 있음)."""
    def keep(v):
        n = v["counts"].get(key, -1)
        if n == -1:
            return False
        if key.endswith("_consolidated") and v["no_consolidated_fs"]:
            return False
        if max_n is not None and n > max_n:
            return False
        if min_n is not None and n < min_n:
            return False
        return True

    rows = [v for v in by_filing.values() if keep(v)]
    rows.sort(key=lambda v: (-v["counts"][key], v["corp_name"]) if min_n is not None
              else (v["fiscal_year"], v["fiscal_period"], v["corp_name"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rcept_no", "corp_name", "market", "fiscal_year", "fiscal_period",
                    "report_type", f"{key}_n", "dart_link"])
        for v in rows:
            w.writerow([v["rcept_no"], v["corp_name"], v["market"], v["fiscal_year"],
                        v["fiscal_period"], v["report_type"], v["counts"][key],
                        f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={v['rcept_no']}"])
    bound = f"<= {max_n}" if max_n is not None else f">= {min_n}"
    logger.info(f"{key} {bound}: {len(rows):,}건 → {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fiscal-year-min", type=int, default=2015)
    ap.add_argument("--outlier-key", default=None,
                     help="예: IS_separate — 지정 시 outlier CSV도 추출")
    ap.add_argument("--outlier-max", type=int, default=None, help="이 값 이하(저조 필링)")
    ap.add_argument("--outlier-min", type=int, default=None, help="이 값 이상(과다 필링)")
    ap.add_argument("--json-out", type=Path, default=None,
                     help="아티팩트 재구성용 히스토그램+요약 JSON 저장 경로")
    args = ap.parse_args()

    by_filing = load_by_filing(args.fiscal_year_min)
    dist = print_distribution(by_filing)
    print_report_type_medians(by_filing)

    total_lines = sum(n for v in by_filing.values() for n in v["counts"].values())
    n_corps = len({v["corp_code"] for v in by_filing.values()})
    n_excluded_filings = sum(1 for v in by_filing.values() if v["no_consolidated_fs"])
    logger.info(f"필링 {len(by_filing):,}건 / 기업 {n_corps:,}개 / report_lines 행 "
                f"{total_lines:,} / 연결비대상 확정 필링 {n_excluded_filings:,}건")

    if args.outlier_key:
        bound_tag = f"le{args.outlier_max}" if args.outlier_max is not None else f"ge{args.outlier_min}"
        out = Path(f"manual_review/_2015plus_distribution_review_2026-09-13/"
                   f"outlier_{args.outlier_key.lower()}_{bound_tag}.csv")
        write_outlier_csv(by_filing, args.outlier_key, out,
                           max_n=args.outlier_max, min_n=args.outlier_min)

    if args.json_out:
        import json
        payload = {
            "n_filings": len(by_filing), "n_corps": n_corps, "total_lines": total_lines,
            "n_excluded_consolidated_filings": n_excluded_filings,
            "hist": build_hist_json(dist),
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"JSON 저장: {args.json_out}")


if __name__ == "__main__":
    main()
