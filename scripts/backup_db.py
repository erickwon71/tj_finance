"""D1 · DB 백업 — 야간 pg_dump(논리 백업).

89GB DB 단일 사본에 백업이 전무해 디스크 사고 시 전손 위험이 있었다. 이 스크립트는 매일
`pg_dump`(custom format, 압축)로 논리 백업을 **PGDATA 와 다른 디스크(외장 볼륨)** 에 저장한다.
기본적으로 **재생성 가능한 fact_v2 데이터(≈86GB)는 제외**(스키마는 보존) → 백업이 ~수백 MB 로 작아
빠르다. fact_v2 는 필요 시 raw_report 재추출로 복원한다.

복원:
  pg_restore -d tj_finance --clean --if-exists <파일.dump>
  # fact_v2 재적재가 필요하면 raw_report 로 재추출(run.py fin2-all).

usage:
  python scripts/backup_db.py                     # 소비계층 백업(fact_v2 데이터 제외)
  python scripts/backup_db.py --full              # fact_v2 포함 전체(대용량·느림)
  python scripts/backup_db.py --out-dir /path --keep 14
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

DEFAULT_DB = "tj_finance"
DEFAULT_OUT = "/Volumes/dart_data/db_backups"   # PGDATA(내장 디스크)와 다른 외장 볼륨
EXCLUDE_DATA = ("fact_v2",)                      # 재생성 가능 → 데이터 제외(스키마는 보존)


def _pg_dump_bin() -> str:
    return shutil.which("pg_dump") or "/opt/homebrew/bin/pg_dump"


def _rotate(out_dir: Path, db: str, keep: int) -> list[str]:
    dumps = sorted(out_dir.glob(f"{db}_*.dump"))
    removed = []
    for old in dumps[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError as e:  # noqa: PERF203
            logger.warning(f"[backup] 회전 삭제 실패 {old.name}: {e}")
    return removed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out-dir", default=DEFAULT_OUT, help="백업 저장 폴더(외장 볼륨 권장)")
    ap.add_argument("--keep", type=int, default=7, help="보관할 최근 백업 수(회전)")
    ap.add_argument("--full", action="store_true", help="fact_v2 데이터까지 포함(대용량)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    # 외장 볼륨 미마운트 시 내장 디스크로 백업하면 사고 대비 의미가 없으므로 상위 마운트 확인.
    mount = out_dir if out_dir.exists() else out_dir.parent
    if not mount.exists():
        logger.error(f"[backup] 백업 대상 볼륨이 없습니다: {out_dir} — 외장 볼륨 마운트 확인 필요.")
        sys.exit(2)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    kind = "full" if args.full else "core"
    path = out_dir / f"{args.db}_{kind}_{ts}.dump"

    cmd = [_pg_dump_bin(), "-Fc", "--no-owner", "--no-privileges", "-d", args.db, "-f", str(path)]
    if not args.full:
        for t in EXCLUDE_DATA:
            cmd += [f"--exclude-table-data={t}"]

    logger.info(f"[backup] pg_dump 시작 → {path.name} ({'전체' if args.full else 'fact_v2 데이터 제외'})")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        logger.error(f"[backup] pg_dump 실패(rc={r.returncode}): {r.stderr.strip()[:500]}")
        # 실패한 부분 파일 정리
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
        sys.exit(1)

    size = path.stat().st_size if path.exists() else 0
    if size == 0:
        logger.error("[backup] 결과 파일 크기 0 — 실패로 간주.")
        sys.exit(1)
    removed = _rotate(out_dir, args.db, args.keep)

    logger.success(f"[backup] 완료 — {path.name} ({size/1e6:,.1f} MB) · 보관 {args.keep}개"
                   + (f" · 회전삭제 {len(removed)}개" if removed else ""))


if __name__ == "__main__":
    main()
