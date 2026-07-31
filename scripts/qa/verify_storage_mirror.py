"""NAS(primary) ↔ SD(backup) 원문 미러 정합 검증.

두 용도가 있다:

  ① S2b 역방향 정산 (심링크 원복 **전** 1회, `--full`)
     드리프트 기간에 받은 파일은 SD 에만 있고 NAS 에는 없을 수 있다. 데일리 미러는
     NAS→SD 단방향(덧붙이기)이라 이를 NAS 로 끌어오지 않는다. 정산 없이 심링크만
     원복하면 **primary(RAID1)에 구멍이 뚫린 채** 운영이 시작되고 아무도 알려주지 않는다.
     → `--full` 로 "SD에만 있는 실파일" 목록을 뽑아 NAS 로 복사한 뒤 재확인한다.

  ② 데일리 미러 후 정합 확인 (`--sample`, `--since`)
     SMB 전수 순회는 느리다(NAS 10분+). 상시 검증은 표본·당일 변경분으로 한다.

macOS AppleDouble(`._*`)·`.DS_Store`·sentinel·쓰기 프로브는 원문이 아니므로 전부 제외한다.
(SD 가 HFS+ 라 `._*` 가 대량 생성돼 2026-07-31 감사에서 26건 오탐을 냈다.)

사용:
    python scripts/qa/verify_storage_mirror.py --full
    python scripts/qa/verify_storage_mirror.py --sample 90
    python scripts/qa/verify_storage_mirror.py --since 2026-07-01
    python scripts/qa/verify_storage_mirror.py --full --out /tmp/mirror_report.txt
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from collector.storage_guard import BACKUP_ROOT, PRIMARY_ROOT  # noqa: E402

# 원문이 아닌 사이드카/제어 파일
_SKIP_PREFIX = ("._",)
# `.sync.ffs_db` = FreeFileSync 동기화 DB(사용자가 수동 동기화에 써 왔다). 양쪽 크기가
# 1바이트 다른 게 정상이라 제외하지 않으면 매번 "불일치 1건"으로 오탐이 난다.
_SKIP_NAMES = {".DS_Store", ".tj_volume_id", ".sync.ffs_db", ".sync.ffs_lock"}
_SKIP_CONTAINS = (".tj_write_probe.",)


def _is_report_file(name: str) -> bool:
    if name.startswith(_SKIP_PREFIX) or name in _SKIP_NAMES:
        return False
    return not any(s in name for s in _SKIP_CONTAINS)


def walk_files(root: Path, subdirs: list[str] | None = None,
               since_ts: float | None = None) -> dict[str, int]:
    """root 아래 실파일의 {상대경로: 크기}. os.scandir 로 SMB 왕복을 줄인다."""
    out: dict[str, int] = {}
    roots = [root / s for s in subdirs] if subdirs else [root]
    for start in roots:
        if not start.exists():
            continue
        stack = [start]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                stack.append(Path(e.path))
                            elif e.is_file(follow_symlinks=False) and _is_report_file(e.name):
                                st = e.stat()
                                if since_ts is not None and st.st_mtime < since_ts:
                                    continue
                                out[str(Path(e.path).relative_to(root))] = st.st_size
                        except OSError:
                            continue
            except OSError as exc:
                print(f"  ! 순회 실패 {cur}: {exc}", file=sys.stderr)
    return out


def _corp_dirs(root: Path) -> list[str]:
    dirs = []
    for market in ("KOSPI", "KOSDAQ"):
        mroot = root / market
        if not mroot.exists():
            continue
        for name in sorted(os.listdir(mroot)):
            if not name.startswith("."):
                dirs.append(f"{market}/{name}")
    return dirs


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--full", action="store_true", help="전수 대조(느림, NAS 10분+)")
    g.add_argument("--sample", type=int, help="무작위 기업 N개만 대조")
    g.add_argument("--since", type=str, help="이 날짜(YYYY-MM-DD) 이후 변경분만 대조")
    ap.add_argument("--out", type=str, default=None, help="SD 전용 파일 목록 저장 경로")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    subdirs = None
    since_ts = None
    if args.sample:
        random.seed(args.seed)
        all_dirs = _corp_dirs(BACKUP_ROOT)
        subdirs = random.sample(all_dirs, min(args.sample, len(all_dirs)))
        print(f"표본 {len(subdirs)}개 기업 대조")
    elif args.since:
        since_ts = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        print(f"{args.since} 이후 변경분만 대조")
    else:
        print("전수 대조 — SMB 순회라 수 분 걸린다")

    t0 = time.time()
    print(f"  NAS 순회... {PRIMARY_ROOT}")
    nas = walk_files(PRIMARY_ROOT, subdirs, since_ts)
    print(f"    {len(nas):,}개 ({time.time() - t0:.0f}s)")

    t1 = time.time()
    print(f"  SD  순회... {BACKUP_ROOT}")
    sd = walk_files(BACKUP_ROOT, subdirs, since_ts)
    print(f"    {len(sd):,}개 ({time.time() - t1:.0f}s)")

    nas_keys, sd_keys = set(nas), set(sd)
    sd_only = sorted(sd_keys - nas_keys)      # ★ S2b 대상: NAS 에 없는 것
    nas_only = sorted(nas_keys - sd_keys)     # 미러가 아직 안 옮긴 것
    size_diff = sorted(k for k in (nas_keys & sd_keys) if nas[k] != sd[k])

    print("\n" + "=" * 60)
    print(f"NAS(primary) {len(nas):,}  ·  SD(backup) {len(sd):,}")
    print(f"★ SD 에만 있음 (NAS 결손 = S2b 정산 대상): {len(sd_only):,}")
    print(f"  NAS 에만 있음 (미러 미반영):             {len(nas_only):,}")
    print(f"  양쪽 존재하나 크기 불일치:               {len(size_diff):,}")
    print("=" * 60)

    for label, items in (("SD 전용", sd_only), ("NAS 전용", nas_only),
                         ("크기 불일치", size_diff)):
        if items:
            print(f"\n[{label}] 상위 20건")
            for k in items[:20]:
                print(f"  {k}")
            if len(items) > 20:
                print(f"  ... 외 {len(items) - 20:,}건")

    if args.out and sd_only:
        Path(args.out).write_text("\n".join(sd_only) + "\n", encoding="utf-8")
        print(f"\nSD 전용 목록 저장: {args.out}")

    ok = not sd_only and not nas_only and not size_diff
    print(f"\n판정: {'PASS' if ok else 'FAIL'}  (총 {time.time() - t0:.0f}s)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
