"""
PRD 02 Gate A — 다운로드 유효성 검증
=====================================
완료(completed) 다운로드가 유효·완전한지 판정해 download_tasks.gate_a_status(PASS/FAIL)+reason 기록.
게이트 A: FAIL 인 (corp,year,period)는 PRD 03(파싱·표준화) 진입 차단 대상.

검사(단계):
  1) 파일 무결성(기본, 빠름): 파일 존재 · 크기>0 · 매직바이트(xml=`<`, pdf=`%PDF`).
     사유: MISSING_FILE / ZERO_BYTE / BAD_MAGIC.
  2) 재무제표 추출가능(--statements): fin2 추출이 facts 를 냈는지(fact_v2 보유)로 판정.
     파일은 정상이나 추출 0건 → status=REVIEW, reason=EXTRACT_EMPTY (하드 차단 아님).
     = 금융업/미지원 포맷 등 추출 갭 후보(item 4). section_detector 는 포맷편향(iXBRL 미탐지)이라 미사용.

resume: gate_a_status IS NULL 인 것만 검사(--recheck 로 전체 재검). 배치 커밋.

사용:
    python3 scripts/validate_downloads.py [--limit N] [--statements] [--recheck] [--batch 2000]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from collector.db import SessionLocal


def _check_magic(path: str, file_type: str) -> bool:
    """파일 앞부분으로 형식 일치 확인. xml=`<`(BOM/공백 허용), pdf=`%PDF`."""
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except OSError:
        return False
    if not head:
        return False
    if file_type == "pdf":
        return head[:5].startswith(b"%PDF") or b"%PDF" in head[:1024]
    if file_type == "xml":
        h = head.lstrip(b"\xef\xbb\xbf").lstrip()  # BOM + 공백 제거
        return h[:1] == b"<"
    return True  # html/hwp/zip 등은 크기만 본다


def integrity_reason(file_path: str, file_type: str) -> str | None:
    """파일 무결성 실패 사유. 통과면 None."""
    if not file_path:
        return "MISSING_FILE"
    if not os.path.exists(file_path):
        return "MISSING_FILE"
    try:
        if os.path.getsize(file_path) == 0:
            return "ZERO_BYTE"
    except OSError:
        return "MISSING_FILE"
    if not _check_magic(file_path, file_type or ""):
        return "BAD_MAGIC"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--statements", action="store_true", help="재무제표 존재 확인(XML 파싱, 느림)")
    ap.add_argument("--recheck", action="store_true", help="이미 검사한 것도 재검")
    ap.add_argument("--batch", type=int, default=2000)
    args = ap.parse_args()

    session = SessionLocal()
    where = "status='completed'" + ("" if args.recheck else " AND gate_a_status IS NULL")
    limit = f" LIMIT {args.limit}" if args.limit else ""
    rows = session.execute(text(
        f"SELECT rcept_no, file_path, file_type FROM download_tasks "
        f"WHERE {where} ORDER BY rcept_no{limit}"
    )).fetchall()
    print(f"검사 대상: {len(rows):,}")

    # --statements: fin2 추출 facts 보유 rcept 집합(신뢰가능 신호). ⚠ download_tasks.parsed_facts 는
    # 레거시 파서 산물로 fact_v2 와 불일치(0인데 fact_v2 有 다수) → 사용 금지. fact_v2 가 권위.
    fact_rcepts: set = set()
    if args.statements:
        print("fact_v2 보유 rcept 로딩(DISTINCT, 수십초~수분)...")
        fact_rcepts = {r[0] for r in session.execute(
            text("SELECT DISTINCT rcept_no FROM fact_v2")).fetchall()}
        print(f"  → {len(fact_rcepts):,} rcept")

    from collections import Counter
    stat = Counter()
    n = 0
    for r in rows:
        reason = integrity_reason(r.file_path, r.file_type)
        if reason is not None:
            status = "FAIL"
        elif args.statements and r.rcept_no not in fact_rcepts:
            # 파일 정상이나 fin2 추출 0 → 검토(하드 차단 아님). 금융업/미지원 포맷 갭(item 4).
            status, reason = "REVIEW", "EXTRACT_EMPTY"
        else:
            status = "PASS"
        stat[status] += 1
        if reason:
            stat[reason] += 1
        session.execute(text("""
            UPDATE download_tasks SET gate_a_status=:s, gate_a_reason=:r, gate_a_checked_at=:t
            WHERE rcept_no=:rc
        """), {"s": status, "r": reason, "t": datetime.utcnow(), "rc": r.rcept_no})
        n += 1
        if n % args.batch == 0:
            session.commit()
            print(f"  ...{n:,} 검사 (PASS {stat['PASS']:,} / FAIL {stat['FAIL']:,})")
    session.commit()
    session.close()

    print(f"\n완료: {n:,} 검사")
    for k, v in stat.most_common():
        print(f"  {k:14s} {v:,}")


if __name__ == "__main__":
    main()
