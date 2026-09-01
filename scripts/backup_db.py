"""D1 · DB 백업 — 야간 pg_dump(논리 백업).

89GB DB 단일 사본에 백업이 전무해 디스크 사고 시 전손 위험이 있었다. 이 스크립트는 매일
`pg_dump`(custom format, 압축)로 논리 백업을 **PGDATA(Mac 내장) 와 다른 물리 디스크 — NAS
(RAID1)** 에 저장한다. 라이브 DB(Mac)와 덤프(NAS)가 서로 독립 장애 도메인이 되어 SPOF 해소.

★2026-09-01(fact_v2 GC 트랙, §4-4 DROP, `docs/plans/
factv2_sync_scripts_migration_design_2026-09-01.md`) — 예전엔 재생성 가능한 fact_v2
데이터(≈86GB)를 `--exclude-table-data`로 뺐지만(스키마만 보존), `fact_v2` 테이블 자체가
DROP돼 그 로직이 무의미해졌다 — `--full`/`EXCLUDE_DATA` 제거, 이제 매번 전체 덤프.
남은 대형 테이블(`note_lines`/`report_lines`, 계층2 원문)은 raw_report 재추출로도 복원
가능하지만 fact_v2처럼 "쓰고 버리는 파생물"이 아니라 그 자체가 파싱 산출물의 정본이라
제외 대상이 아니다.

복원:
  pg_restore -d tj_finance --clean --if-exists <파일.dump>

usage:
  python scripts/backup_db.py
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
DEFAULT_OUT = "/Volumes/tj_finance_data/db_backups"  # NAS(RAID1) — PGDATA(Mac 내장)와 다른 물리 디스크


def _pg_dump_bin() -> str:
    return shutil.which("pg_dump") or "/opt/homebrew/bin/pg_dump"


def _notify(title: str, message: str) -> None:
    from scripts.notify import notify_failure
    notify_failure(title, message)


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
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    # 외장 볼륨 미마운트 시 내장 디스크로 백업하면 사고 대비 의미가 없으므로 상위 마운트 확인.
    mount = out_dir if out_dir.exists() else out_dir.parent
    if not mount.exists():
        msg = f"백업 대상 볼륨이 없습니다: {out_dir} — 외장 볼륨 마운트 확인 필요."
        logger.error(f"[backup] {msg}")
        _notify("백업 실패 — 볼륨 미마운트", msg)
        sys.exit(2)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"{args.db}_full_{ts}.dump"

    cmd = [_pg_dump_bin(), "-Fc", "--no-owner", "--no-privileges", "-d", args.db, "-f", str(path)]

    logger.info(f"[backup] pg_dump 시작 → {path.name} (전체)")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        err = f"pg_dump 실패(rc={r.returncode}): {r.stderr.strip()[:500]}"
        logger.error(f"[backup] {err}")
        _notify("백업 실패 — pg_dump 오류", err)
        # 실패한 부분 파일 정리
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
        sys.exit(1)

    size = path.stat().st_size if path.exists() else 0
    if size == 0:
        logger.error("[backup] 결과 파일 크기 0 — 실패로 간주.")
        _notify("백업 실패 — 빈 파일", f"{path.name} 크기 0")
        sys.exit(1)
    removed = _rotate(out_dir, args.db, args.keep)

    logger.success(f"[backup] 완료 — {path.name} ({size/1e6:,.1f} MB) · 보관 {args.keep}개"
                   + (f" · 회전삭제 {len(removed)}개" if removed else ""))


if __name__ == "__main__":
    main()
