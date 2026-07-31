"""
분석/앱 계층 회귀 테스트 공용 유틸 — pytest 무의존 자체 러너(fin2/tests 관행).

각 test_*.py 는 `def test_x(): assert ...` 를 정의하고, 파일 하단에서
`sys.exit(1 if run_tests(globals()) else 0)` 로 직접 실행 가능. `tests/run_all.py` 는
모든 모듈을 모아 한 번에 실행한다. (pytest 가 설치돼 있으면 pytest 로도 수집됨.)
"""
from __future__ import annotations

import os

# 이 모듈은 모든 test_*.py 가 import 한다 — 그래서 여기에 세워두면
# `python tests/test_x.py` 단독 실행에서도 실제 메일·알림이 나가지 않는다
# (일괄 실행은 tests/run_all.py, pytest 는 PYTEST_CURRENT_TEST 로 각각 커버).
os.environ.setdefault("TJ_NOTIFY_DISABLE", "1")


def approx(a, b, tol: float = 1e-9) -> bool:
    """None 안전 근사 비교(절대+상대 허용오차)."""
    if a is None or b is None:
        return a is b or a == b
    return abs(a - b) <= tol * max(1.0, abs(b))


def run_tests(ns: dict) -> int:
    """네임스페이스의 test_* 함수를 실행하고 실패 수를 반환."""
    tests = [v for k, v in sorted(ns.items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: [ERROR] {type(e).__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed
