"""Gate B fail_b 타깃 재구축 — 현재 fail_b(fy>=2015) 보유 기업만 purge+E→R→S+comparative.

배경(2026-06-18 트리아지): fail_b 624행/165사 잔여의 ~2/3 = 두 추출기 버그(둘 다 fact_v2 에
canonical/표선택이 박혀 재추출 필요):
  ① 세전이익(EBT)→tax_expense 오매핑(account_mapper 가드, 110사 2,665셀): '법인세비용차감전이익
     (손실)'류가 '법인세비용' 부분문자열로 퍼지→tax 오매핑, _collect max-abs 가 거대 EBT 채택.
  ② CF 보충표 ×1000 오염(statement_titles 음수 lookahead): "(1) 현금흐름표의 현금은…" 노트문장이
     face 로 오분류 → 천원 노트값이 CF face 를 ×1000 오염(삼천리자전거 등).

전수 재추출은 heavy(수시간) → fail_b 측정 모집단만 타깃(빠르게 측정 backlog 해소). 잠재(현재
pass/pending/미감사) 케이스까지 잡으려면 별도로 fin2_reextract_all.py 전수 실행.

⚠ fact_v2 (acode) upsert → 옛 orphan cell 잔존 → 재추출 전 corp 단위 purge 필수.
⚠ 3패스 순서(standardize → comparative)로 comparative 채움행 clobber 방지. fy>=2015 라 kgaap 무관.

실행(사용자, ~30분 추정 / 기업 단위 커밋·resume):
    caffeinate -i PYTHONPATH=. .venv_tj_finance/bin/python scripts/gateb_remediate_failb.py \
        --resume-file /tmp/failb_remed.txt 2>&1 | tee -a /tmp/failb_remed.log
이후 재감사:
    PYTHONPATH=. .venv_tj_finance/bin/python -u scripts/gateb_audit.py --fy-min 2015 --recheck \
        --corps <범위> 2>&1 | tee -a /tmp/failb_reaudit.log
옵션: --fy-min(default 2015) --dry-run --limit N --resume-file F
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.reconcile import reconcile_corp
from fin2.standardize.build import standardize_corp, standardize_comparative_corp
from run import _extract2_corp


def load_done(resume_file: str | None) -> set[str]:
    if not resume_file:
        return set()
    p = Path(resume_file)
    return {ln.strip() for ln in p.read_text().splitlines() if ln.strip()} if p.exists() else set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fy-min", type=int, default=2015)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--corps", default=None, help="START:END 위치 슬라이스(병렬 분할)")
    ap.add_argument("--corp-file", dest="corp_file", default=None,
                    help="corp_code 목록 파일(주면 fail_b∪EBT 쿼리 대신 이 목록 사용)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resume-file", default=None)
    args = ap.parse_args()

    # 모집단: --corp-file 주면 그 목록, 아니면 측정된 fail_b ∪ EBT 오매핑 기업.
    if args.corp_file:
        corps = sorted({ln.strip() for ln in Path(args.corp_file).read_text().splitlines() if ln.strip()})
    else:
        with get_session() as s:
            corps = sorted({r[0] for r in s.execute(text("""
                SELECT DISTINCT corp_code FROM face_audit
                WHERE gate_status='fail_b' AND fiscal_year >= :y
                UNION
                SELECT DISTINCT corp_code FROM fact_v2
                WHERE canonical_account='is.tax_expense' AND acode LIKE '%차감전%'
            """), {"y": args.fy_min}).fetchall()})

    if args.corps and ":" in args.corps:
        a, _, b = args.corps.partition(":")
        corps = corps[(int(a) if a else None):(int(b) if b else None)]
    done = load_done(args.resume_file)
    pending = [c for c in corps if c not in done]
    if args.limit:
        pending = pending[:args.limit]
    logger.info(f"[failb-remed] fail_b 기업 {len(corps)} / 완료제외 {len(done)} → 대상 {len(pending)}")
    if args.dry_run:
        print("\n".join(pending))
        return

    agg = {"facts": 0, "track_b": 0, "r": 0, "s": 0, "comp": 0, "err": 0}
    total = len(pending)
    for i, corp in enumerate(pending, 1):
        try:
            with get_session() as s:
                s.execute(text("DELETE FROM fact_v2 WHERE corp_code=:c"), {"c": corp})
                files, a, b, facts = _extract2_corp(s, corp, verbose=False)
                agg["facts"] += facts
                agg["track_b"] += b
                agg["r"] += reconcile_corp(s, corp)
                agg["s"] += standardize_corp(s, corp)
                agg["comp"] += standardize_comparative_corp(s, corp)
                s.commit()
            if args.resume_file:
                with open(args.resume_file, "a") as fh:
                    fh.write(corp + "\n")
        except Exception as e:
            agg["err"] += 1
            logger.error(f"[failb-remed] corp={corp} 실패: {e}")
        if i % 20 == 0 or i == total:
            logger.info(f"[failb-remed] {i}/{total} — facts {agg['facts']:,} "
                        f"stmt_src {agg['r']:,} std {agg['s']:,} comp {agg['comp']:,} 오류 {agg['err']}")

    logger.success(f"[failb-remed] 완료 — 기업 {total}, fact {agg['facts']:,}, "
                   f"stmt_src {agg['r']:,}, std {agg['s']:,}, comp {agg['comp']:,}, 오류 {agg['err']}")
    logger.info("다음: gateb_audit.py --fy-min 2015 --recheck (재감사로 gate_status 갱신)")


if __name__ == "__main__":
    main()
