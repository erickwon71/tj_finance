"""P1-I4 · 회계 항등식/연속성 검증 배치 — analyzer/verifier 부활, verification_results 적재.

std_v2(standard_financials view) 대상으로 BS/IS 항등식(자산=부채+자본 · 매출총이익=매출−원가 ·
영업이익=매출총이익−판관비 · 순이익=EBT−법인세)과 연속성(총자본 자릿수/부호 밴드)을 검사하고
`verification_results` 에 upsert 한다(그동안 0행). build 단계 validate_equations(BS·GP 만) 를 넘어
IS 체인(영업이익·순이익 항등식)까지 기록 — B 에서 고친 op==ni 회귀 감시에도 유용.

usage:
  python scripts/verify_identities.py --sample 50          # 표본 50사(con+sep)
  python scripts/verify_identities.py --corps 00126380,00883980
  python scripts/verify_identities.py                      # 전 활성기업(con+sep) — 장시간
  python scripts/verify_identities.py --shard 0/8          # 병렬 분할
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from analyzer.verifier import verify_corp
from collector.db import get_session


def _pick(session, args) -> list[str]:
    if args.corps:
        raw = args.corps
        if Path(raw).exists():
            raw = Path(raw).read_text()
        return [c.strip() for c in raw.replace("\n", ",").split(",") if c.strip()]
    corps = [r[0] for r in session.execute(text(
        "SELECT corp_code FROM corporations WHERE is_active AND stock_code IS NOT NULL "
        "ORDER BY corp_code")).fetchall()]
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        corps = corps[i::n]
    if args.sample:
        rng = random.Random(args.seed)
        rng.shuffle(corps)
        corps = corps[: args.sample]
    return corps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corps", help="corp_code 목록(쉼표) 또는 파일")
    ap.add_argument("--sample", type=int, help="무작위 표본 기업수")
    ap.add_argument("--shard", help="병렬 분할 i/n")
    ap.add_argument("--since", type=int, default=2015, help="검증 시작 회계연도(기본 2015)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with get_session() as s:
        corps = _pick(s, args)
    logger.info(f"[verify-id] 대상 {len(corps)}사 (con+sep, fy≥{args.since})")

    agg = {"corps": 0, "checks": 0, "fail": 0, "err": 0}
    for i, corp in enumerate(corps, 1):
        try:
            for basis in ("consolidated", "separate"):
                res = verify_corp(corp, since_year=args.since, stmt_type=basis, save=True)
                agg["checks"] += len(res)
                agg["fail"] += sum(1 for r in res if r["passed"] is False)
            agg["corps"] += 1
        except Exception as e:  # noqa: BLE001
            agg["err"] += 1
            logger.warning(f"[verify-id] {corp} 실패: {type(e).__name__}: {e}")
        if i % 100 == 0 or i == len(corps):
            logger.info(f"  ..{i}/{len(corps)} (checks {agg['checks']:,} fail {agg['fail']} err {agg['err']})")

    # verification_results 요약
    with get_session() as s:
        by_check = s.execute(text("""
            SELECT check_name, count(*) AS n,
                   count(*) FILTER (WHERE passed IS FALSE) AS fail
            FROM verification_results GROUP BY check_name ORDER BY fail DESC, n DESC
        """)).fetchall()
    print("\n===== verification_results (check별) =====")
    for name, n, fail in by_check:
        print(f"  {name:<22} 총 {n:>7,}  fail {fail:,}")
    logger.success(f"[verify-id] 완료 — 검증 {agg['corps']}사 · checks {agg['checks']:,} · "
                   f"fail {agg['fail']} · 오류 {agg['err']}")


if __name__ == "__main__":
    main()
