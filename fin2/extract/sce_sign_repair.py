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

# 소계 행의 **라벨** 조건(R162-c). 산술만으로 소계를 찾으면 오탐이 난다 — 실측에서
# '당기순이익(손실)'·'해외사업환산손익'·'감자차손보전' 처럼 소계가 아닌 행이 앞 구간의
# 합과 절대값이 같아 걸렸다. 그래서 **라벨 + 산술 둘 다** 요구한다(R159 와 같은 2근거
# 원칙). 자간 공백('소 계')과 접두 기호('- 총포괄이익 소계')를 견딘다.
_SUBTOTAL_LABEL_RE = re.compile(
    r"소\s*계|합\s*계|총\s*계|총\s*포괄|총\s*기타\s*포괄")


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


def _is_balance_label(label: str) -> bool:
    return bool(_OPEN_BALANCE_RE.search(label)
                or _CLOSE_BALANCE_RE.search(label))


def _required_sign(cell, anchors: Dict[Tuple[str, str], Set[int]],
                   carried: Optional[Dict[int, int]] = None
                   ) -> Tuple[Optional[int], str]:
    """이 셀의 부호가 확정되는가 → `(+1|-1|None, 앵커라벨)`.

    개념 라벨을 두 곳에서 찾는다:
      1. 셀 자신의 `label_raw` — 변동행(예: '순확정급여부채의 재측정요소')
      2. `col_label` 의 마지막 조각 — 잔액행(라벨이 날짜라서 1번이 안 먹는다)

    `carried` 는 **같은 열에서 이미 확정된 잔액**의 `{절대값: 부호}` 다(R162-b).
    SCE 는 당기·전기 블록이 세로로 쌓이고 BS 는 당기만 적재하므로 전기 블록에는 1·2
    앵커가 없다. 그런데 한 블록의 기말은 다른 블록의 기초와 **같은 잔액 그 자체**라
    (엠케이전자 `20150515000634`: 2014.12.31 기말 = 2015.01.01 기초) 확정된 쪽의
    부호를 그대로 물려받을 수 있다.
    ★**잔액행에만** 적용한다 — 변동행까지 절대값으로 맞추면 우연 일치로 날조된다.
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
    if carried and _is_balance_label(cell.label_raw):
        sign = carried.get(magnitude)
        if sign is not None:
            return sign, "이월잔액"
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


def _proven_subtotals(cells: Sequence[_Cell],
                      move_i: Sequence[int]) -> List[int]:
    """변동행 중 **앞선 연속 구간의 합과 절대값이 같은** 행 = 소계(R162-c).

    SCE 는 구성요소 행 뒤에 그 합('총포괄손익' 등)을 **형제로** 한 줄 더 찍는 서식이
    흔하다. 그걸 Σ변동에 같이 넣으면 **이중계상**돼 항등식이 절대 닫히지 않는다.
    실측 디에이치엑스컴퍼니 `20150515000944` 연결 기타포괄손익누계액 열:

        지분법기타포괄손익      21,360,989
        매도가능증권평가손익     -6,006,966
        총포괄손익           15,354,023   ← 앞 두 행의 합
        (기초+Σ변동) − 기말 = 15,354,023  ← 차이가 정확히 이 소계

    ★**들여쓰기로는 못 찾는다** — 이 표는 모든 행이 `depth=0`·`node_role='F'` 다
    (원문에 들여쓰기가 없다). 그래서 `node_role='P'`(부모) 로 소계를 찾으려던 1차
    가설은 실측에서 **0건**으로 기각됐다. 판정은 **산술**로 해야 한다.

    ★절대값으로 비교한다 — 소계 자신이 부호를 잃은 경우도 잡아야 한다. 부호는
    나중에 구성요소의 합으로 확정한다(추측하지 않는다).
    ★소계로 판정된 행은 다음 구간의 합산 대상에서 뺀다(소계의 소계를 만들지 않는다).
    """
    out: List[int] = []
    run: List[int] = []
    for idx in move_i:
        if run and _SUBTOTAL_LABEL_RE.search(cells[idx].label_raw):
            total = sum(cells[j].value for j in run)
            if total and abs(cells[idx].value) == abs(total):
                out.append(idx)
                run = []            # 구간을 닫는다 — 소계는 다음 합에 안 들어간다
                continue
        run.append(idx)
    return out


def _solve_block(cells: Sequence[_Cell], block, anchors,
                 carried: Optional[Dict[int, int]] = None
                 ) -> Tuple[List[Tuple[int, int]], str]:
    """한 블록의 부호 배정을 푼다 → `([(cell idx, new sign)], 앵커설명)`.

    첫 반환이 빈 목록이면 '손대지 않는다'는 뜻이다.
    """
    open_i, move_i, close_i = block
    # R162-c — 소계 행은 Σ변동에서 뺀다(이중계상). 소계 자신의 부호는 추측하지 않고
    # 구성요소의 합으로 확정한다(아래 `_subtotal_fixes`).
    subtotals = _proven_subtotals(cells, move_i)
    summed = [m for m in move_i if m not in set(subtotals)]
    members = [open_i, *summed, close_i]

    def identity_holds(signs: Dict[int, int]) -> bool:
        total = signs[open_i] * abs(cells[open_i].value)
        for m in summed:
            total += signs[m] * abs(cells[m].value)
        return total == signs[close_i] * abs(cells[close_i].value)

    current = {i: (1 if cells[i].value > 0 else -1) for i in members}
    if identity_holds(current):
        # 항등식은 닫혔다 — 그래도 소계 행 자신이 부호를 잃었을 수 있다.
        fixes = _subtotal_fixes(cells, move_i, subtotals, current)
        return (fixes, "소계=구성요소 합") if fixes else ([], "")

    # 음수로 파싱된 셀은 원문에 괄호가 있었다는 뜻 → 부호가 명시된 것이므로 후보 아님.
    ambiguous = [i for i in members if cells[i].value > 0]
    if not ambiguous or len(ambiguous) > _MAX_AMBIGUOUS_CELLS:
        return [], ""

    required: Dict[int, Tuple[int, str]] = {}
    for i in members:
        sign, anchor_label = _required_sign(cells[i], anchors, carried)
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
    fixes = [(i, winner[i]) for i in members
             if winner[i] * abs(cells[i].value) != cells[i].value]
    fixes += _subtotal_fixes(cells, move_i, subtotals, winner)
    return fixes, anchor_desc


def _subtotal_fixes(cells: Sequence[_Cell], move_i: Sequence[int],
                    subtotals: Sequence[int],
                    signs: Dict[int, int]) -> List[Tuple[int, int]]:
    """소계 행의 부호를 **구성요소의 합**으로 확정한다(R162-c).

    소계는 Σ변동에서 빠져 있으므로 항등식이 그 부호를 정해 주지 않는다. 대신 그
    구성요소(앞선 연속 구간)의 합이 부호까지 알려 준다 — 추측이 아니다.
    """
    out: List[Tuple[int, int]] = []
    sub = set(subtotals)
    run: List[int] = []
    for idx in move_i:
        if idx in sub:
            total = sum(signs.get(j, 1 if cells[j].value > 0 else -1)
                        * abs(cells[j].value) for j in run)
            if total and abs(total) == abs(cells[idx].value):
                want = 1 if total > 0 else -1
                if want * abs(cells[idx].value) != cells[idx].value:
                    out.append((idx, want))
            run = []
            continue
        run.append(idx)
    return out


# ── R162-d 원리의 개별 확정 사례(2026-09-22 결정: 일반 백필은 보류, 개별
#    필링은 확정된 대로 등재) ───────────────────────────────────────────────
#
# camp_run 이슈#38(2026-09-23): SK텔레콤 00159023 `20210517001554`(2021Q1)
# [별도] 자본변동표 `2021.03.31 (기말자본)` 행 **자기주식** 열.
#
# R162 의 (가)BS/IS 교차대조 앵커가 원리적으로 없다 — 이 필링 BS 에 '자기주식'
# 단독 행이 없다(재무상태표에 자본조정/기타불입자본으로만 뭉쳐 있음). 그래서
# 일반 `repair_sce_sign_loss()` 는 이 셀을 손대지 않았다(R6, 정상 동작).
#
# 그런데 **행 내부 항등식**이 orientation 을 거울 모호성 없이 확정한다(R162-d 와
# 같은 원리 — 2026-09-22 '스캔·증명 완료·백필 보류' 결정의 그 패턴). 독립된
# 두 증거가 일치한다:
#   ① 열 롤포워드: 2021.01.01(기초) −2,123,661,000,000 + 자기주식의 취득
#      −72,982,000,000 + 자기주식의 처분 +26,983,000,000 = −2,169,660,000,000
#   ② 행 내부 분해: 기타불입자본 합계(245,841,000,000) = 주식발행초과금
#      (2,915,887,000,000) + 자기주식 + 신종자본증권(398,759,000,000) +
#      주식선택권(1,528,000,000) + 기타(−900,673,000,000)
#      → 자기주식 = −2,169,660,000,000 (역산, 동일)
# DB 는 현재 +2,169,660,000,000(원문 그대로, 괄호 누락)으로 적재돼 있다.
#
# ★R162-d 전체 백필은 여전히 보류다(사용자 결정 2026-09-22) — 이건 그 범위를
#   넓히는 게 아니라, camp_run 이 실측 발견하고 사용자가 개별 승인한 **이 필링
#   1건만**의 확정이다(2026-09-23). old_value 가 일치할 때만 적용해, 원문/코드가
#   달라지면 조용히 틀린 값을 덮지 않는다.
_MANUAL_SIGN_FIXES: Dict[Tuple[str, str, str, str], Tuple[int, int]] = {
    ("20210517001554", "separate", "2021.03.31 (기말자본)", "자기주식"):
        (2_169_660_000_000, -2_169_660_000_000),
}


def apply_manual_sign_fixes(lines: List, rcept_no: Optional[str]) -> List[Correction]:
    """`_MANUAL_SIGN_FIXES` 에 등재된 셀만 부호를 뒤집는다(없으면 아무 것도 안 함).

    `apply_source_typo_fixes()`(R159)와 같은 패턴 — rcept 단위 예외목록, old_value
    일치 확인 후에만 적용.
    """
    if not rcept_no or not _MANUAL_SIGN_FIXES:
        return []
    corrections: List[Correction] = []
    for ln in lines:
        if getattr(ln, "statement", None) != "SCE":
            continue
        key = (rcept_no, ln.basis, (ln.label_raw or "").strip(),
               concept_of_col_label(getattr(ln, "col_label", None)))
        fix = _MANUAL_SIGN_FIXES.get(key)
        if fix is None or ln.value_won != fix[0]:
            continue
        old_value = ln.value_won
        ln.value_won = fix[1]
        corrections.append(Correction(
            basis=ln.basis, table_seq=getattr(ln, "table_seq", None),
            row_order=ln.row_order, col_index=ln.col_index,
            col_label=getattr(ln, "col_label", None), label_raw=ln.label_raw or "",
            old_value=old_value, new_value=fix[1], anchor_label="manual(R162-d 개별확정)"))
    if corrections:
        logger.debug(f"[report_lines/R162-manual] SCE 부호 수동확정 "
                     f"{len(corrections)}셀 ({rcept_no})")
    return corrections


def repair_sce_sign_loss(lines: List) -> List[Correction]:
    """`lines` 의 SCE 행 부호를 제자리에서 복원하고 교정 내역을 돌려준다.

    BS/IS 앵커가 필요하므로 **추출이 끝난 뒤 전체 라인 목록에** 적용한다
    (`extract_report_lines` 말미). SCE 만 건드리고 BS/IS/CF 는 읽기만 한다.
    """
    # R162-e runs without BS/IS anchors too, so no early return on an empty anchor map.
    anchors = build_sign_anchors(lines)

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
        # R162-b — 블록을 한 번에 다 풀지 못한다. 당기 블록은 BS 앵커로 풀리고, 그렇게
        # 확정된 잔액이 전기 블록의 앵커가 된다(이월잔액). 진전이 없을 때까지 반복한다.
        blocks = _blocks(cells)
        pending = list(range(len(blocks)))
        while True:
            carried = _carried_balance_signs(cells, blocks, pending)
            progressed = False
            for bi in list(pending):
                fixes, anchor_label = _solve_block(
                    cells, blocks[bi], anchors, carried)
                if not fixes:
                    if _block_identity_holds(cells, blocks[bi]):
                        pending.remove(bi)      # 이미 닫힘 = 확정 → 앵커로 쓸 수 있다
                        progressed = True
                    continue
                pending.remove(bi)
                progressed = True
                _apply(cells, fixes, anchor_label, corrections)
            if not progressed:
                break
        # R162-e — blocks the anchored passes could not close: one positive cell whose
        # flip alone closes the roll-forward, and no other such cell.
        for bi in pending:
            fixes = _solve_single_flip(cells, blocks[bi], anchors, carried)
            if fixes:
                _apply(cells, fixes, "R162-e 롤포워드 단일셀", corrections)

    if corrections:
        logger.debug(f"[report_lines/R162] SCE 부호 복원 {len(corrections)}셀")
    return corrections


def _solve_single_flip(cells: Sequence[_Cell], block, anchors,
                       carried: Optional[Dict[int, int]] = None) -> List[Tuple[int, int]]:
    """R162-e (2026-09-25, 사용자 지시 "R162 확장 배치로 자동 이슈 처리").

    (가) BS/IS 앵커가 **원리적으로 없는** 셀 — 대표적으로 '배당금지급'·'연차배당'
    (BS/IS 에 같은 개념 행이 없다) — 은 R162 가 손대지 못한다. 이런 블록에서 롤포워드가
    닫히지 않고, **양수 셀 하나의 부호만** 뒤집으면 정확히 닫히며, 그런 셀이 **정확히
    하나**일 때만 그 셀을 뒤집는다.

    거울 모호성(R162 의 (나) 단독 금지 사유)은 '최소 변경'으로 끊는다 — 전체 반전은
    나머지 모든 셀의 원문 부호를 부정하는 다(多)셀 변경이고, 여기서는 원문 부호가 맞다는
    전제 아래 틀린 셀이 하나뿐인 배정만 받는다. 후보가 둘 이상이면 판정불가(R6).
    ★음수로 파싱된 셀은 여전히 후보가 아니다(괄호가 명시된 것).
    ★앵커(또는 이월잔액)가 그 셀의 부호를 정해 두었는데 반대로 뒤집게 되면 받지 않는다.
    """
    open_i, move_i, close_i = block
    subtotals = _proven_subtotals(cells, move_i)
    summed = [m for m in move_i if m not in set(subtotals)]
    members = [open_i, *summed, close_i]
    current = {i: (1 if cells[i].value > 0 else -1) for i in members}

    def holds(signs: Dict[int, int]) -> bool:
        total = signs[open_i] * abs(cells[open_i].value)
        for m in summed:
            total += signs[m] * abs(cells[m].value)
        return total == signs[close_i] * abs(cells[close_i].value)

    if holds(current):
        return []
    winners = []
    for i in members:
        if cells[i].value <= 0:
            continue
        trial = dict(current)
        trial[i] = -1
        if holds(trial):
            winners.append(i)
            if len(winners) > 1:
                return []
    if len(winners) != 1:
        return []
    i = winners[0]
    sign, _label = _required_sign(cells[i], anchors, carried)
    if sign == 1:
        return []                       # an anchor says this cell is positive
    signs = dict(current)
    signs[i] = -1
    return [(i, -1)] + _subtotal_fixes(cells, move_i, subtotals, signs)


def _block_identity_holds(cells: Sequence[_Cell], block) -> bool:
    open_i, move_i, close_i = block
    total = cells[open_i].value + sum(cells[m].value for m in move_i)
    return total == cells[close_i].value


def _carried_balance_signs(cells: Sequence[_Cell], blocks,
                           pending: Sequence[int]) -> Dict[int, int]:
    """확정된(=pending 이 아닌) 블록의 잔액 셀에서 `{절대값: 부호}` 를 모은다.

    같은 절대값에 부호가 엇갈리면 그 절대값은 버린다(판정 근거로 쓸 수 없다).
    """
    out: Dict[int, int] = {}
    conflicting: Set[int] = set()
    for bi, (open_i, _moves, close_i) in enumerate(blocks):
        if bi in pending:
            continue
        for i in (open_i, close_i):
            magnitude = abs(cells[i].value)
            sign = 1 if cells[i].value > 0 else -1
            if magnitude in out and out[magnitude] != sign:
                conflicting.add(magnitude)
            out[magnitude] = sign
    for magnitude in conflicting:
        out.pop(magnitude, None)
    return out


def _apply(cells: Sequence[_Cell], fixes, anchor_label: str,
           corrections: List[Correction]) -> None:
    """푼 배정을 라인 객체에 반영하고 교정 내역을 쌓는다."""
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
        # `cells` 는 불변 NamedTuple 이라 값을 제자리에서 못 바꾼다 — 같은 열을 다시
        # 훑는 다음 라운드가 갱신된 부호를 보도록 교체해 둔다.
        cells[idx] = cell._replace(value=new_value)
