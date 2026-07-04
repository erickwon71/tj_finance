"""야간 데이터 품질 점검 — I3 SQL 어서션 + I1 교차검증(순환 표본)을 한 번에.

launchd(com.tjfinance.dqcheck)로 매일 실행. 두 점검 결과를 한 로그에 남기고, ERROR(어서션 위반)면
종료코드 1. 교차검증은 매일 소수 표본을 무작위(시드=날짜)로 돌려 시간이 지나며 커버리지가 순환된다.

usage:
  python scripts/dq_nightly.py [--xsrc-sample 25]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv_tj_finance" / "bin" / "python")
sys.path.insert(0, str(ROOT))


def _run(args: list[str]) -> int:
    print(f"\n$ {' '.join(a for a in args if not a.startswith('/Users'))}", flush=True)
    r = subprocess.run([PY, *args], cwd=str(ROOT))
    return r.returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xsrc-sample", type=int, default=25, help="교차검증 표본 기업수(0=생략)")
    args = ap.parse_args()

    print(f"===== DQ 야간 점검 {date.today()} =====", flush=True)

    # (1) 참조무결성 SQL 어서션 — ERROR 위반 시 exit 1
    rc_assert = _run([str(ROOT / "scripts" / "dq_assertions.py")])

    # (2) DART 교차검증 — 날짜 시드로 순환 표본(가벼운 API 호출). 불일치는 참고(게이트 제외).
    if args.xsrc_sample > 0:
        seed = int(date.today().strftime("%Y%m%d"))
        _run([str(ROOT / "scripts" / "verify_cross_source.py"),
              "--sample", str(args.xsrc_sample), "--years", "2020-2024", "--seed", str(seed)])

    # 게이트 = 어서션 ERROR 만(교차검증 불일치는 정정노이즈/합성 포함이라 비게이트).
    print(f"\n[dq-nightly] 어서션 종료코드 {rc_assert}", flush=True)
    if rc_assert != 0:
        from scripts.notify import notify_failure
        notify_failure("DQ 야간 점검 실패", f"어서션 위반 발견(exit {rc_assert}) — logs/dqcheck.out.log 확인")
    sys.exit(rc_assert)


if __name__ == "__main__":
    main()
