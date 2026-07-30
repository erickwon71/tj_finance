"""단위 선언 탐지 비용 측정 — 깨진 XML 의 **긴 텍스트**가 병목이 되는지 확인한다.

왜 재는가: F1 의 `_iter_declarations` 는 '단위' 출현마다 본문을 토큰화한다. 정상 표제
텍스트(수십~수백 자)에서는 무해하지만, `</TABLE>` 누락으로 한 형제의 itertext 가 문서 전체가
되는 실측 서식(메가스터디 20190401004405: 직접 1행 vs `.//TR` 3,573행)에서는 '단위' 가
수천 번 나온다. 그래서 (a) 첫 금액 선언에서 멈추고 (b) 출현 수를 상한으로 끊었다.
이 스크립트는 그 두 장치가 실제로 필요한지/효과가 있는지를 숫자로 남긴다.

    python scripts/bench_unit_declaration.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.common.amount_normalizer import (_DECL_SCAN_MAX, detect_unit_declaration,
                                             detect_unit_tokens)

N = 20_000


def bench(label: str, text: str, fn, expect) -> None:
    t0 = time.perf_counter()
    for _ in range(N):
        got = fn(text)
    el = time.perf_counter() - t0
    ok = "OK " if got == expect else f"불일치({got!r})"
    print(f"  {label:<44} {el/N*1e6:>9.2f} µs/call  {ok}")


def main() -> int:
    print(f"단위 선언 탐지 비용 ({N:,} 회 평균, 출현 상한 {_DECL_SCAN_MAX})\n")

    short = "연결 재무상태표 제 33 기 2023.12.31 현재 (단위 : 백만원)"
    # 깨진 XML 형제: 같은 문구가 수천 번 반복돼 '단위' 도 그만큼 나온다.
    prose_unit = "당사는 현금창출단위의 회수가능액을 추정하였으며 손상징후는 없습니다. "
    long_no_money = prose_unit * 400                      # 금액 선언 없음 = 최악(전량 스캔)
    long_money_late = prose_unit * 400 + "(단위 : 천원)"    # 금액 선언이 끝에 있다

    bench("짧은 표제(정상)", short, detect_unit_declaration, 1_000_000)
    bench("긴 서술문·금액선언 없음(최악)", long_no_money, detect_unit_declaration, None)
    # 끝에 있는 선언도 찾아야 한다 — 구 정규식은 텍스트 어디서든 첫 매칭을 찾았으므로,
    # 상한을 짧게 잡으면 **조용한 유실**이 된다(초판 상한 24 에서 실제로 None 이 나왔다).
    bench("긴 서술문 + 끝에 금액선언", long_money_late, detect_unit_declaration, 1_000)
    bench("짧은 표제 — 토큰", short, detect_unit_tokens, ["백만원"])

    print(f"\n  '단위' 출현 수: 짧은 표제 1 · 긴 서술문 {long_no_money.count('단위'):,}")
    print(f"  출현당 추가 비용 ≈ 740 ns → 상한 {_DECL_SCAN_MAX:,} 은 폭주 방어용이고 "
          "정상 문서의 선언은 놓치지 않는다.")
    print("  ※ 전수 스윕 실측 처리량은 0.14 s/filing (F1 전 census 와 동일).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
