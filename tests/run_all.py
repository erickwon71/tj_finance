"""
분석/앱 회귀 테스트 일괄 실행 — `python tests/run_all.py`.

각 test_*.py 의 test_ 함수를 모아 실행하고, 하나라도 실패하면 종료코드 1.
pytest 미설치 환경에서도 동작(자체 러너). CI/사전커밋 훅에서 이 한 줄로 회귀 검출.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# 테스트에서 실제 메일·알림이 나가지 않게 막는다(scripts/notify.py:_suppressed).
# 테스트 모듈을 import 하기 **전에** 세워야 한다.
os.environ.setdefault("TJ_NOTIFY_DISABLE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._util import run_tests  # noqa: E402

_MODULES = [
    "test_ratio_engine",
    "test_valuation_engine",
    "test_units",
    "test_derived_resolver",
    "test_checks",
    "test_screen_eval",
    "test_master_metrics",
    "test_storage_guard",
    "test_corp_universe_guard",
    "test_delisting_archive",
    "test_market_calendar",
]


def main() -> int:
    total_failed = 0
    total_tests = 0
    for name in _MODULES:
        print(f"\n== {name} ==")
        mod = importlib.import_module(f"tests.{name}")
        ns = vars(mod)
        total_tests += sum(1 for k, v in ns.items()
                           if k.startswith("test_") and callable(v))
        total_failed += run_tests(ns)
    print(f"\n{'=' * 40}\nTOTAL: {total_tests} tests, {total_failed} failed")
    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())
