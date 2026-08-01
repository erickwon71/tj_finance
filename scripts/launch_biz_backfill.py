"""Launch the sharded biz_metrics backfill as detached processes.

Why this exists
---------------
Starting the shards from a wrapper shell (`for i in ...; do ... & done; wait`) makes them
children of that shell and members of its process group. When the wrapper is stopped, the
whole group dies with it — measured 2026-07-31: all 8 shards were killed mid-run at roughly
100-200/315 corps each.

`start_new_session=True` calls setsid(), so each shard becomes its own session leader and
survives the death of whatever launched it. (macOS has no `setsid` binary, so this is done
from Python rather than the shell.)

Progress is safe across restarts: sync_biz_metrics commits per company, and
`--skip-catalog-existing` skips companies that already have catalog metrics, so a restart
resumes rather than redoing work.

  python scripts/launch_biz_backfill.py --shards 8
  python scripts/launch_biz_backfill.py --shards 8 --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=8)
    ap.add_argument("--target", choices=("biz", "order"), default="biz",
                    help="biz=collect_biz_metrics / order=collect_order_backlog")
    ap.add_argument("--log-prefix", default=None,
                    help="기본값은 대상별 자동(logs/{biz_catalog_backfill,order_backfill}_s)")
    ap.add_argument("--full", action="store_true",
                    help="전 기업 재적재(기본은 --skip-catalog-existing 재개 모드). "
                         "적재 계약이 바뀐 뒤에는 이걸 써야 한다 — 재개 모드는 이미 카탈로그 "
                         "지표가 있는 기업을 전부 건너뛰므로 아무것도 갱신되지 않는다.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        print(f"venv python 없음: {python}")
        return 1
    (ROOT / "logs").mkdir(exist_ok=True)

    script = ("scripts/collect_biz_metrics.py" if args.target == "biz"
              else "scripts/collect_order_backlog.py")
    prefix = args.log_prefix or ("logs/biz_catalog_backfill_s" if args.target == "biz"
                                 else "logs/order_backfill_s")

    pids: list[int] = []
    for i in range(args.shards):
        cmd = [str(python), script, "--shard", f"{i}/{args.shards}"]
        if not args.full and args.target == "biz":
            cmd.insert(2, "--skip-catalog-existing")
        log = ROOT / f"{prefix}{i}.log"
        if args.dry_run:
            print(" ".join(cmd), "→", log)
            continue
        with open(log, "a") as fh:                       # append: keep the earlier run's history
            fh.write(f"\n=== relaunch shard {i}/{args.shards} ===\n")
            fh.flush()
            p = subprocess.Popen(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
                                 start_new_session=True)   # ← detach from our process group
        pids.append(p.pid)

    if pids:
        print(f"샤드 {len(pids)}개 기동 · PID {pids}")
        print(f"로그: {prefix}*.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
