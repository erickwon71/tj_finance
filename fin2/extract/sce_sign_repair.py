"""R162 — SCE 표 원문에서 빠진 **음수 괄호**를 복원한다 (2026-09-22).

## 무엇을 고치는가

DART 원문이 같은 개념을 표에 따라 다르게 렌더링한다 — BS·IS 는 괄호로 음수를 찍는데
같은 필링의 자본변동표(SCE)에서는 괄호가 빠진다(효성중공업 `20190515002585` 실측,
`docs/PARSING_RULES.md` R162). 파서는 원문에 충실했지만 결과적으로 부호가 반대로
적재된다.

## 두 근거를 **둘 다** 요구한다

| 근거 | 역할 |
|---|---|
| (가) BS/IS 교차대조 | **부호 방향(앵커)** — 같은 필링·같은 basis 에 같은 개념이 음수/양수 어느 쪽으로 있는지가 orientation 을 확정한다 |
| (나) 열 롤포워드 항등식 | **적용 자격** — `기초 + Σ변동 = 기말` 이 닫히는 배정만 채택한다 |

(가) 만으로는 부족하다. 잔액행의 `label_raw` 는 **날짜**("2019.01.01 (당기초)")라서
개념 라벨로 매칭되지 않고, 개념은 `col_label` 에 있다. 게다가 **기초** 잔액은 BS 의
전기말과 대조해야 하는데 BS 는 `col_index=0`(당기)만 적재하므로 DB 안에 짝이 없다 —
라벨 교차대조로는 원리적으로 못 닿고 항등식으로만 증명된다.

(나) 만으로도 부족하다. 어떤 배정이 항등식을 만족하면 그 **전체 부호반전(mirror)**도
반드시 만족하므로(양변에 −1), 항등식 혼자서는 orientation 을 정할 수 없다. (가)가
그 둘 중 하나를 골라 준다.

## 손대지 않는 경우 (R6 — 오염보다 결측)

- 항등식이 **이미** 닫힌다 → 정상 표다.
- 만족하는 배정이 **여러 개** 남는다 → 판정불가.
- 앵커가 **하나도 없다** → orientation 미증명.
- 앵커가 배정과 **모순**한다 → 판정불가.
- 후보 셀이 `_MAX_AMBIGUOUS_CELLS` 를 넘는다 → 탐색 폭발 방지.

★**열 전체를 일괄 반전하지 않는다.** 효성중공업 기타자본구성요소 열은 기초·기말
잔액만 괄호를 잃었고 변동행(448,570 / 700,359,720)은 양수가 맞다. 일괄 반전은 멀쩡한
변동행을 망친다 — 그래서 셀 단위 배정을 항등식으로 검증한다.

★**음수로 파싱된 셀은 후보가 아니다.** 원문에 괄호가 있었다는 뜻이므로 부호가
명시된 것이고, 우리가 추측할 대상이 아니다.
"""
from __future__ import annotations

import itertools
import re
from collections import defaultdict
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

from loguru import logger

# Search-space guard. A real SCE block has a handful of movement rows per column;
# anything wider is a layout we have not proven and must not guess at.
_MAX_AMBIGUOUS_CELLS = 14

# Opening / closing balance rows. Their label is a date plus a period marker,
# e.g. "2019.01.01 (당기초)" / "2019.03.31 (당기말)". Spacing is tolerated because
# some filers letter-space these labels (R151 lesson).
_OPEN_BALANCE_RE = re.compile(r"기\s*초")
_CLOSE_BALANCE_RE = re.compile(r"기\s*말")


class Correction(NamedTuple):
    """한 셀의 부호 복원 결과 — 백필/보고가 그대로 쓸 수 있게 근거까지 담는다."""
    basis: str
    table_seq: Optional[int]
    row_order: Optional[int]
    col_index: int
    col_label: Optional[str]
    label_raw: str
    old_value: int
    new_value: int
    anchor_label: str          # 이 블록의 orientation 을 확정해 준 앵커 라벨(들).
                               # ★셀 자신이 아니라 **블록** 기준이다 — 잔액행이 앵커를
                               # 물고 변동행이 항등식으로 따라오는 경우가 흔하다.


def concept_of_col_label(col_label: Optional[str]) -> str:
    """`'자본>기타자본구성요소'` → `'기타자본구성요소'`.

    `_build_col_labels` 는 헤더 그리드를 계층으로 이어 붙이므로 상위 헤더('자본')가
    접두어로 붙는다. BS 라벨과 맞추려면 **마지막 조각**만 쓴다.
    """
    if not col_label:
        return ""
    return col_label.split(">")[-1].strip()


def build_sign_anchors(lines: Iterable) -> Dict[Tuple[str, str], Set[int]]:
    """BS/IS 의 `col_index=0` 값을 `(basis, label)` → {values} 로 모은다.

    같은 라벨이 여러 값을 가지면(표 중복·재게재) 그대로 집합에 남겨 둔다 — 아래
    `_required_sign()` 이 방향이 엇갈리는 집합을 '판정불가'로 처리한다.
    """
    anchors: Dict[Tuple[str, str], Set[int]] = defaultdict(set)
    for ln in lines:
        if getattr(ln, "statement", None) not in ("BS", "IS"):
            continue
        if getattr(ln, "col_index", None) != 0:
            continue
        value = getattr(ln, "value_won", None)
        label = (getattr(ln, "label_raw", "") or "").strip()
        if value is None or not label:
            continue
        anchors[(ln.basis, label)].add(int(value))
    return anchors


def _required_sign(cell, anchors: Dict[Tuple[str, str], Set[int]]
                   ) -> Tuple[Optional[int], str]:
    """이 셀의 부호가 BS/IS 로 확정되는가 → `(+1|-1|None, 앵커라벨)`.

    개념 라벨을 두 곳에서 찾는다:
      1. 셀 자신의 `label_raw` — 변동행(예: '순확정급여부채의 재측정요소')
      2. `col_label` 의 마지막 조각 — 잔액행(라벨이 날짜라서 1번이 안 먹는다)
    """
    magnitude = abs(cell.value)
    for key in (cell.label_raw.strip(),
                concept_of_col_label(cell.col_label)):
        if not key:
            continue
        values = anchors.get((cell.basis, key))
        if not values:
            continue
        has_neg = -magnitude in values
        has_pos = magnitude in values
        if has_neg and not has_pos:
            return -1, key
        if has_pos and not has_neg:
            return +1, key
        # 양쪽 다 있으면 방향이 엇갈린다 — 이 앵커로는 판정하지 않는다.
    return None, ""


class _Cell(NamedTuple):
    """항등식 검증용 셀 한 개(추출 산출물 객체와 분리해 순수 계산만 한다)."""
    line: object
    basis: str
    label_raw: str
    col_label: Optional[str]
    value: int


def _blocks(cells: Sequence[_Cell]) -> List[Tuple[int, List[int], int]]:
    """행 순서대로 훑어 `(기초 idx, [변동 idx], 기말 idx)` 블록 목록을 만든다.

    SCE 는 당기 블록과 전기 블록이 **세로로 두 번** 쌓이므로 블록이 여러 개 나온다.
    기초를 만나면 새 블록을 열고, 기말을 만나면 닫는다. 기초 없이 기말만 나오거나
    중첩되면 그 구간은 버린다(추측하지 않는다).
    """
    out: List[Tuple[int, List[int], int]] = []
    open_idx: Optional[int] = None
    movements: List[int] = []
    for i, cell in enumerate(cells):
        label = cell.label_raw
        if _OPEN_BALANCE_RE.search(label):
            open_idx, movements = i, []
            continue
        if _CLOSE_BALANCE_RE.search(label):
            if open_idx is not None:
                out.append((open_idx, movements, i))
            open_idx, movements = None, []
            continue
        if open_idx is not None:
            movements.append(i)
    return out


def _solve_block(cells: Sequence[_Cell], block, anchors
                 ) -> Tuple[List[Tuple[int, int]], str]:
    """한 블록의 부호 배정을 푼다 → `([(cell idx, new sign)], 앵커설명)`.

    첫 반환이 빈 목록이면 '손대지 않는다'는 뜻이다.
    """
    open_i, move_i, close_i = block
    members = [open_i, *move_i, close_i]

    def identity_holds(signs: Dict[int, int]) -> bool:
        total = signs[open_i] * abs(cells[open_i].value)
        for m in move_i:
            total += signs[m] * abs(cells[m].value)
        return total == signs[close_i] * abs(cells[close_i].value)

    current = {i: (1 if cells[i].value > 0 else -1) for i in members}
    if identity_holds(current):
        return [], ""                   # 정상 표 — 고칠 것이 없다

    # 음수로 파싱된 셀은 원문에 괄호가 있었다는 뜻 → 부호가 명시된 것이므로 후보 아님.
    ambiguous = [i for i in members if cells[i].value > 0]
    if not ambiguous or len(ambiguous) > _MAX_AMBIGUOUS_CELLS:
        return [], ""

    required: Dict[int, Tuple[int, str]] = {}
    for i in members:
        sign, anchor_label = _required_sign(cells[i], anchors)
        if sign is not None:
            required[i] = (sign, anchor_label)
    if not required:
        return [], ""                   # orientation 미증명(mirror 를 못 가른다)

    solutions: List[Dict[int, int]] = []
    for combo in itertools.product((1, -1), repeat=len(ambiguous)):
        signs = dict(current)
        signs.update(zip(ambiguous, combo))
        if any(signs[i] != req[0] for i, req in required.items()):
            continue                    # 앵커와 모순
        if identity_holds(signs):
            solutions.append(signs)
            if len(solutions) > 1:
                return [], ""           # 판정불가 — 여러 배정이 항등식을 만족

    if not solutions:
        return [], ""
    winner = solutions[0]
    anchor_desc = ", ".join(sorted({label for _s, label in required.values()
                                    if label}))
    return ([(i, winner[i]) for i in members
             if winner[i] * abs(cells[i].value) != cells[i].value], anchor_desc)


def repair_sce_sign_loss(lines: List) -> List[Correction]:
    """`lines` 의 SCE 행 부호를 제자리에서 복원하고 교정 내역을 돌려준다.

    BS/IS 앵커가 필요하므로 **추출이 끝난 뒤 전체 라인 목록에** 적용한다
    (`extract_report_lines` 말미). SCE 만 건드리고 BS/IS/CF 는 읽기만 한다.
    """
    anchors = build_sign_anchors(lines)
    if not anchors:
        return []

    # (basis, table_seq, col_index) 단위로 한 열을 모은다 — SCE 의 col_index 는 기간이
    # 아니라 자본 구성요소 위치이므로, 항등식은 이 열 안에서 닫힌다.
    columns: Dict[Tuple[str, Optional[int], int], List] = defaultdict(list)
    for ln in lines:
        if getattr(ln, "statement", None) != "SCE":
            continue
        if getattr(ln, "value_won", None) is None:
            continue
        columns[(ln.basis, getattr(ln, "table_seq", None),
                 ln.col_index)].append(ln)

    corrections: List[Correction] = []
    for key, group in columns.items():
        group.sort(key=lambda l: (l.row_order if l.row_order is not None else 0))
        cells = [_Cell(line=l, basis=l.basis,
                       label_raw=(l.label_raw or ""),
                       col_label=getattr(l, "col_label", None),
                       value=int(l.value_won)) for l in group]
        for block in _blocks(cells):
            fixes, anchor_label = _solve_block(cells, block, anchors)
            for idx, sign in fixes:
                cell = cells[idx]
                new_value = sign * abs(cell.value)
                corrections.append(Correction(
                    basis=cell.basis,
                    table_seq=getattr(cell.line, "table_seq", None),
                    row_order=getattr(cell.line, "row_order", None),
                    col_index=cell.line.col_index,
                    col_label=cell.col_label,
                    label_raw=cell.label_raw,
                    old_value=cell.value,
                    new_value=new_value,
                    anchor_label=anchor_label,
                ))
                cell.line.value_won = new_value

    if corrections:
        logger.debug(f"[report_lines/R162] SCE 부호 복원 {len(corrections)}셀")
    return corrections
