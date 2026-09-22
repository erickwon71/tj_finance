"""R163 — CF 현금 조정 구간에서 원문이 빠뜨린 음수 부호를 복원한다 (2026-09-22).

## 무엇을 고치는가

R162(SCE)와 **같은 계열**이다 — DART 원문 자체가 부호(괄호/마이너스)를 빠뜨리고,
파서는 원문에 충실하게 양수로 전사한다. 캠페인 이슈#29(한화오션 `20180330001629`
[별도] CF, 제18기 열):

    현금및현금성자산의 증가(감소)      16,367,553,617
    기초의 현금및현금성자산          144,292,901,261
    외화표시 현금및현금성자산의 환율변동효과    521,074,352   ← 참값은 −521,074,352
    기말의 현금및현금성자산          160,139,380,526

    144,292,901,261 + 16,367,553,617 − 521,074,352 = 160,139,380,526 ✓

같은 필링의 비교연도 2개 열과 [연결] CF 는 부호가 정상이다 — 이 한 셀만 깨졌다.

## ★부호만으로는 절대 판정할 수 없다

`환율변동효과` 행이 **양수인 것이 정상**인 경우가 압도적으로 많다(2015+ 실측:
양수 114,412셀 / 음수 83,639셀 — 환율이 오르면 외화현금 평가이익이 나서 양수다).
그래서 이 규칙은 **항등식이 깨진 경우에만** 작동하고, 항등식을 닫는 **단일 셀 뒤집기가
유일할 때만** 적용한다.

## 왜 R162 의 블록 로직을 재사용하지 않는가

SCE 는 `기초 → 변동들 → 기말` 순서지만 CF 는 **순증감 행이 기초보다 앞**에 온다
(위 실측 참고). 그래서 "기초가 열고 기말이 닫는" 블록 탐색이 맞지 않는다. 대신 이
모듈은 현금 조정 4행(기초·순증감·환율효과·기말)을 **라벨로 직접 지목**한다 — 관측된
결함 계열에만 좁게 대응하고, 라벨을 못 찾으면 손대지 않는다.

## 손대지 않는 경우 (R6 — 오염보다 결측)

- 기초·순증감·환율효과·기말 중 하나라도 라벨로 못 찾음.
- 항등식이 이미 닫힘(정상 표).
- 단일 셀 뒤집기로 닫히는 경우가 **없거나 둘 이상**.
- 기초·기말 현금이 음수(현금 잔액은 음수일 수 없다 — 우리가 이해 못 한 표다).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

from loguru import logger

# 로마숫자/번호 접두(`Ⅶ.`, `(1)`)와 자간 공백을 견디게 짠다(R151 교훈).
_CASH = r"현\s*금"
_CLOSING_RE = re.compile(r"(?:분\s*기\s*말|반\s*기\s*말|기\s*말).*" + _CASH)
_OPENING_RE = re.compile(r"기\s*초.*" + _CASH)
# 순증감 — '환율변동효과 반영전 … 순증가(감소)' 도 이 자리에 해당한다(환율효과를
# 그 뒤에 더하는 서식). 반대로 '환율변동효과 후의 … 순증가(감소)' 는 이미 환율이
# 반영된 총계라 이 항등식의 항이 아니다 → 배제한다.
_NET_CHANGE_RE = re.compile(r"(?:순\s*증\s*가|순\s*증\s*감|증\s*가\s*\(\s*감\s*소\s*\)|"
                            r"순\s*증\s*감\s*액)")
_NET_CHANGE_EXCLUDE_RE = re.compile(r"환율변동효과\s*후")
_FX_EFFECT_RE = re.compile(r"환\s*율\s*변\s*동")
# '환율변동효과 반영전 …' 은 순증감 행이고 환율효과 행이 아니다.
_FX_EXCLUDE_RE = re.compile(r"반\s*영\s*전")


class CfCorrection(NamedTuple):
    basis: str
    table_seq: Optional[int]
    row_order: Optional[int]
    col_index: int
    label_raw: str
    old_value: int
    new_value: int
    identity: str          # 복원 후 성립하는 항등식(사람이 검산할 수 있게)


def _norm(label: Optional[str]) -> str:
    return (label or "").strip()


def _pick(rows: List, pattern: re.Pattern,
          exclude: Optional[re.Pattern] = None) -> Optional[object]:
    """패턴에 맞는 행이 **정확히 하나**일 때만 돌려준다(여럿이면 판정불가)."""
    hits = [r for r in rows
            if pattern.search(_norm(r.label_raw))
            and not (exclude and exclude.search(_norm(r.label_raw)))]
    return hits[0] if len(hits) == 1 else None


def repair_cf_cash_sign_loss(lines: List) -> List[CfCorrection]:
    """CF 현금 조정 항등식이 깨진 열에서 단일 셀 부호를 복원한다(제자리 수정)."""
    columns: Dict[Tuple[str, Optional[int], int], List] = defaultdict(list)
    for ln in lines:
        if getattr(ln, "statement", None) != "CF":
            continue
        if getattr(ln, "value_won", None) is None:
            continue
        columns[(ln.basis, getattr(ln, "table_seq", None),
                 ln.col_index)].append(ln)

    corrections: List[CfCorrection] = []
    for group in columns.values():
        group.sort(key=lambda l: (l.row_order if l.row_order is not None else 0))
        opening = _pick(group, _OPENING_RE)
        closing = _pick(group, _CLOSING_RE)
        net = _pick(group, _NET_CHANGE_RE, _NET_CHANGE_EXCLUDE_RE)
        fx = _pick(group, _FX_EFFECT_RE, _FX_EXCLUDE_RE)
        if not (opening and closing and net and fx):
            continue
        if opening.value_won < 0 or closing.value_won < 0:
            # 현금 잔액이 음수인 표 — 우리가 이해한 구조가 아니다.
            continue
        if (opening.value_won + net.value_won + fx.value_won
                == closing.value_won):
            continue                    # 정상 표

        # 단일 셀 뒤집기로 닫히는 경우가 유일할 때만 적용한다.
        winners = []
        for cand in (fx, net):
            if cand.value_won <= 0:
                continue                # 이미 음수 = 원문에 부호가 명시됐다
            flipped = {id(cand): -cand.value_won}
            total = (flipped.get(id(opening), opening.value_won)
                     + flipped.get(id(net), net.value_won)
                     + flipped.get(id(fx), fx.value_won))
            if total == closing.value_won:
                winners.append(cand)
        if len(winners) != 1:
            continue

        target = winners[0]
        old = target.value_won
        target.value_won = -old
        corrections.append(CfCorrection(
            basis=target.basis,
            table_seq=getattr(target, "table_seq", None),
            row_order=getattr(target, "row_order", None),
            col_index=target.col_index,
            label_raw=_norm(target.label_raw),
            old_value=old,
            new_value=target.value_won,
            identity=(f"{opening.value_won:,} + {net.value_won:,} + "
                      f"{fx.value_won:,} = {closing.value_won:,}"),
        ))

    if corrections:
        logger.debug(f"[report_lines/R163] CF 현금 부호 복원 {len(corrections)}셀")
    return corrections
