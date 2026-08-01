"""Do amendments ever carry a PARTIAL '사업의 내용' (present, but only some of it)? (READ-ONLY)

This is the measurement that decides how complex the merge has to be:
  - if amendments always carry the section whole -> per-target replacement is enough
  - if they carry it partially -> a table-level merge onto the original is required

Comparison is done on **subsections** (사업의개요 / 주요제품및서비스 / 원재료및생산설비 / ...)
rather than raw table counts, because table counts wobble with parser detail while a missing
subsection is an unambiguous "this part was not re-filed" signal. Table counts per shared
subsection are reported too.

Only pairs where BOTH sides have a 사업의 내용 section are considered — filings with no body
at all ([첨부정정]) are a different, already-settled case (R2-0).

Prints DART links so findings can be opened and checked by hand.

  python scripts/probe_partial_body_amendment.py --groups 400 --workers 8
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_catalog import walk_captioned_tables
from fin2.extract.biz_section import _load_root

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

# ★ The amendment group key is (report_type, fiscal_year, fiscal_period) — the same key
#   filing_collector uses for is_final. Grouping by (corp, fiscal_year) ALONE is wrong: it puts
#   Q1/H1/Q3/FY of one year in the same bucket, so the probe ends up comparing a 반기보고서
#   against a 분기보고서 and calls the difference a "partial amendment" (measured, first run).
GROUPS_SQL = """
    SELECT f.corp_code, c.corp_name, f.fiscal_year, f.report_type, f.fiscal_period,
           array_agg(f.rcept_no  ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS rcepts,
           array_agg(f.report_nm ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS names,
           array_agg(d.file_path ORDER BY f.filed_at ASC NULLS FIRST, f.rcept_no ASC) AS paths
    FROM filings f
    JOIN download_tasks d ON d.rcept_no = f.rcept_no
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE f.report_type IN ('annual', 'half', 'quarter')
      AND c.is_active AND c.stock_code IS NOT NULL
      AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    GROUP BY 1, 2, 3, 4, 5
    HAVING count(*) >= 2
"""


def profile(path: str) -> dict[str, int] | None:
    """{subsection: table count} for the 사업의 내용 section, or None if unreadable."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        root = _load_root(p)
    except Exception:                                              # noqa: BLE001
        return None
    if root is None:
        return None
    out: Counter = Counter()
    for ct in walk_captioned_tables(root):
        out[ct.subsection] += 1
    return dict(out)


def work(g: dict) -> list[dict]:
    """Compare consecutive filings of one (corp, year) group."""
    profs = []
    for rcept, nm, path in zip(g["rcepts"], g["names"], g["paths"]):
        pr = profile(path)
        if pr is not None:
            profs.append((rcept, nm, pr))
    res = []
    for i in range(len(profs) - 1):
        (ra, na, pa), (rb, nb, pb) = profs[i], profs[i + 1]
        if not pa or not pb:            # one side has no 사업의 내용 at all -> R2-0 case
            continue
        missing = sorted(set(pa) - set(pb))
        added = sorted(set(pb) - set(pa))
        shrunk = sorted(s for s in set(pa) & set(pb) if pb[s] < pa[s] * 0.6)
        res.append({
            "corp": g["corp_name"], "fy": g["fiscal_year"],
            "ra": ra, "na": na, "rb": rb, "nb": nb,
            "ta": sum(pa.values()), "tb": sum(pb.values()),
            "missing": missing, "added": added, "shrunk": shrunk,
            "pa": pa, "pb": pb,
        })
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--groups", type=int, default=400)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    with get_session() as s:
        groups = [dict(r._mapping) for r in s.execute(text(GROUPS_SQL)).fetchall()]
    random.Random(args.seed).shuffle(groups)
    groups = groups[: args.groups]
    print(f"(기업,연도) 그룹 {len(groups)}개 · 워커 {args.workers}개 — 파싱 중…", flush=True)

    with Pool(args.workers) as pool:
        chunks = pool.map(work, groups)
    pairs = [x for c in chunks for x in c]

    partial = [x for x in pairs if x["missing"] or x["shrunk"]]
    print(f"\n양쪽 모두 사업의 내용을 가진 원본↔정정본 쌍 {len(pairs)}개")
    print(f"  · 정정본이 소제목을 통째로 빠뜨림      {sum(1 for x in pairs if x['missing']):>4}쌍")
    print(f"  · 공유 소제목인데 표가 40%+ 줄어듦     {sum(1 for x in pairs if x['shrunk']):>4}쌍")
    print(f"  · 둘 중 하나라도 해당(=부분 수록 의심)  {len(partial):>4}쌍 "
          f"({len(partial)/max(len(pairs),1)*100:.1f}%)")

    if partial:
        print(f"\n{'='*100}\n부분 수록 의심 사례 (직접 확인용 링크)\n")
        for x in sorted(partial, key=lambda y: -(len(y["missing"]) + len(y["shrunk"])))[: args.show]:
            print(f"■ {x['corp']} FY{x['fy']}   표 {x['ta']} → {x['tb']}")
            print(f"    원본   {x['na'][:30]:<32} {DART}{x['ra']}")
            print(f"    정정본 {x['nb'][:30]:<32} {DART}{x['rb']}")
            if x["missing"]:
                print(f"    ▼ 정정본에 없는 소제목: {', '.join(x['missing'])}")
                for s in x["missing"]:
                    print(f"         └ 원본 '{s}' 표 {x['pa'][s]}개")
            if x["shrunk"]:
                for s in x["shrunk"]:
                    print(f"    ▽ '{s}' 표 {x['pa'][s]} → {x['pb'][s]}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
