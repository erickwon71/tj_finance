"""계층2 이상치 탐지 실행기 — 값은 고치지 않고 `report_line_anomalies` 에 표시만 남긴다.

원칙(사용자 확정): report_lines 는 원문 그대로. 보정은 계층3 이 이 표시를 보고 판단한다.
근거·사례는 `fin2/audit/line_anomaly.py` 와 `collector.models.ReportLineAnomaly` 참고.

한 보고서에서 이상치가 **여러 건** 나올 수 있다(기말 행이 당기·전기·전전기로 여러 개이고,
행마다 항목이 여러 개다). rcept 단위 delete-then-insert 라 재실행이 안전하다.

사용:
    python scripts/detect_line_anomalies.py --corp 00364403            # 한 기업
    python scripts/detect_line_anomalies.py --sample 300 --dry-run     # 표본, 저장 안 함
    python scripts/detect_line_anomalies.py --all                      # 전량(적재 후)
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines
from fin2.audit.line_anomaly import detect_anomalies, store_anomalies

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


def _fetch(session, args):
    where = ["dt.status='completed'", "dt.file_type='xml'", "dt.file_path IS NOT NULL",
             "f.fiscal_period='FY'", "f.report_nm NOT LIKE '%정정%'", "f.fiscal_year >= 2015"]
    params = {}
    if args.corp:
        where.append("f.corp_code=:c"); params["c"] = args.corp
    sql = f"""SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
                     c.corp_name, c.stock_code
              FROM download_tasks dt JOIN filings f USING(rcept_no)
              JOIN corporations c ON c.corp_code = f.corp_code
              WHERE {' AND '.join(where)}"""
    rows = session.execute(text(sql), params).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--all", action="store_true", help="전량(적재 후 전수 스캔)")
    ap.add_argument("--dry-run", action="store_true", help="탐지만 하고 저장 안 함")
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()
    if not (args.corp or args.sample or args.all):
        ap.error("--corp / --sample / --all 중 하나는 필요")

    with get_session() as session:
        targets = _fetch(session, args)
    if not targets:
        print("대상 없음"); return

    kinds, conf = Counter(), Counter()
    per_report = Counter()
    n_rep = n_stored = 0
    shown = 0

    for t in targets:
        if not Path(t.file_path).exists():
            continue
        try:
            lines = extract_report_lines(
                t.file_path, rcept_no=t.rcept_no, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period)
        except Exception as e:
            print(f"  ! ERR {t.rcept_no}: {type(e).__name__}: {e}")
            continue
        n_rep += 1
        found = detect_anomalies(lines, rcept_no=t.rcept_no, corp_code=t.corp_code)
        if found:
            per_report[len(found)] += 1
            for a in found:
                kinds[a.anomaly_kind] += 1
                conf[a.confidence] += 1
            if shown < args.show:
                shown += 1
                print(f"\n  {t.corp_name}({t.stock_code}) {t.fiscal_year} — 이상치 {len(found)}건")
                print(f"    {DART.format(t.rcept_no)}")
                for a in found:
                    print(f"      [{a.anomaly_kind}/{a.confidence}] {a.basis} "
                          f"r{a.row_order} c{a.col_index} '{(a.label_raw or '')[:24]}'")
                    print(f"          {a.evidence_detail}")
        if not args.dry_run:
            with get_session() as s:
                n_stored += store_anomalies(s, t.rcept_no, found)
                s.commit()

    print(f"\n=== 이상치 탐지: 보고서 {n_rep}건 ===")
    print(f"  이상치 보유 보고서 {sum(per_report.values()):,} / {n_rep:,}")
    print(f"  탐지 총건수        {sum(kinds.values()):,}"
          f"{'' if args.dry_run else f' (저장 {n_stored:,})'}")
    if per_report:
        print(f"\n  [보고서당 건수 분포]")
        for k in sorted(per_report):
            print(f"      {k}건: {per_report[k]:,} 보고서")
    if kinds:
        print(f"\n  [유형]")
        for k, c in kinds.most_common():
            print(f"      {k:12s} {c:,}")
        print(f"  [신뢰도]")
        for k, c in conf.most_common():
            print(f"      {k:8s} {c:,}")


if __name__ == "__main__":
    main()
