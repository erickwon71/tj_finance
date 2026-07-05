"""
Gate B Phase B — Track B(텍스트) 라인감사 측정/배치 (C1).

Track A 라인감사(gateb_audit.audit_lines)는 XBRL acode 정확대조라 텍스트 보고서
(source_format='xml_text', 전체 fact_v2 의 최대 소스)를 pending 으로 남겼다. 이 스크립트는
`read_report_face_text`(표제기반 독립 리더)로 본문 face 를 재추출해 `fact_v2` 와
(canonical,basis) 값-집합 대조(reconcile_report_lines_text)한다.

정책(Track A 관례): **측정 우선** — VALUE_DIFF(추출 손상 후보)만 차단 신호로 보고,
MISSING 은 완전성 지표. 현재는 측정 전용(집계+예시 출력, 무영속). face_line_audit
적재(track='B')는 대량 배치에서 value_diff 청정 확인 후 후속 단계.

usage:
  python scripts/line_audit_trackb.py --sample 40            # 무작위 40 보고서 측정
  python scripts/line_audit_trackb.py --sample 500 --show 30 # value_diff 예시 30건
  python scripts/line_audit_trackb.py --corp 00126380        # 단일 기업 전 rcept
  전수 배치(사용자 장시간): python scripts/line_audit_trackb.py --sample 0 --show 60
    → 집계 value_diff율·예시로 트리아지(94-FP 플레이북). 청정 확인 후 영속화 추가.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from collector.db import get_session
from fin2.audit.face_audit import read_report_face_text
from fin2.audit.line_audit import reconcile_report_lines_text

EOK = 100_000_000


def _sample_reports(session, args) -> list[tuple[str, str, str]]:
    """(rcept_no, corp_code, file_path) 목록. Track B(xml_text) 본문 보유 xml 보고서."""
    if args.corp:
        sql = """
            SELECT DISTINCT dt.rcept_no, f.corp_code, dt.file_path
            FROM download_tasks dt
            JOIN filings f ON f.rcept_no = dt.rcept_no
            WHERE dt.file_type='xml' AND dt.status='completed' AND f.corp_code=:c
              AND EXISTS (SELECT 1 FROM fact_v2 v WHERE v.rcept_no=dt.rcept_no
                          AND v.source_format='xml_text' AND v.col_index=0)
        """
        rows = session.execute(text(sql), {"c": args.corp}).fetchall()
    else:
        lim = "" if args.sample == 0 else f"LIMIT {int(args.sample)}"
        sql = f"""
            SELECT dt.rcept_no, f.corp_code, dt.file_path
            FROM download_tasks dt
            JOIN filings f ON f.rcept_no = dt.rcept_no
            WHERE dt.file_type='xml' AND dt.status='completed'
              AND EXISTS (SELECT 1 FROM fact_v2 v WHERE v.rcept_no=dt.rcept_no
                          AND v.source_format='xml_text' AND v.col_index=0)
            ORDER BY random() {lim}
        """
        rows = session.execute(text(sql)).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def _facts(session, rcept: str) -> list[dict]:
    rows = session.execute(text("""
        SELECT canonical_account, basis, adecimal, amount_won
        FROM fact_v2
        WHERE rcept_no=:r AND col_index=0 AND NOT COALESCE(is_dimensional, false)
    """), {"r": rcept}).fetchall()
    return [{"canonical_account": a, "basis": b, "adecimal": d, "amount_won": w}
            for a, b, d, w in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=40, help="무작위 표본 수(0=전체)")
    ap.add_argument("--corp", help="단일 corp_code")
    ap.add_argument("--show", type=int, default=15, help="VALUE_DIFF 예시 출력 수")
    args = ap.parse_args()

    with get_session() as session:
        reports = _sample_reports(session, args)
        print(f"대상 Track B 보고서: {len(reports)}건\n")

        agg = Counter()
        empty = 0
        vdiff_examples: list[tuple] = []
        per_report_vdiff: list[tuple[str, int, int]] = []

        for i, (rc, corp, fp) in enumerate(reports, 1):
            if not fp or not Path(fp).exists():
                agg["no_file"] += 1
                continue
            try:
                face = read_report_face_text(fp)
            except (FileNotFoundError, OSError):
                agg["no_file"] += 1
                continue
            if not face:
                empty += 1
                continue
            rla = reconcile_report_lines_text(rc, face, _facts(session, rc))
            agg["reports"] += 1
            agg["lines"] += rla.n_lines
            agg["match"] += rla.n_match
            agg["value_diff"] += rla.n_value_diff
            agg["missing"] += rla.n_missing
            if rla.n_value_diff:
                per_report_vdiff.append((corp, rc, rla.n_value_diff))
                for ld in rla.value_diffs[:5]:
                    vdiff_examples.append((corp, rc, ld))
            if i % 100 == 0:
                print(f"  … {i}/{len(reports)}")

        print(f"\n{'='*60}")
        print(f"측정 완료: 보고서 {agg['reports']}건 (빈 face {empty} · 파일없음 {agg['no_file']})")
        print(f"라인 {agg['lines']:,} · match {agg['match']:,} · "
              f"VALUE_DIFF {agg['value_diff']:,} · MISSING {agg['missing']:,}")
        if agg["lines"]:
            mr = agg["match"] / agg["lines"] * 100
            vr = agg["value_diff"] / agg["lines"] * 100
            print(f"match율 {mr:.1f}% · value_diff율 {vr:.2f}% · "
                  f"value_diff 보고서 {len(per_report_vdiff)}/{agg['reports']}")

        if vdiff_examples:
            print(f"\n[VALUE_DIFF 예시 — 트리아지용 {min(args.show, len(vdiff_examples))}건]")
            print(f"{'corp':<10}{'canonical':<26}{'basis':<11}{'report_won':>18}{'db_won':>18}")
            for corp, rc, ld in vdiff_examples[:args.show]:
                print(f"{corp:<10}{(ld.statement or '')+'|'+ld.acode[:18]:<26}"
                      f"{ld.basis or '':<11}{ld.report_won or 0:>18,}{ld.db_won or 0:>18,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
