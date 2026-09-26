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
#
# 2026-09-26(fix batch #13, sign_flip 잔여 61건): 키에 `row_order` 를 추가했다 —
# 같은 (rcept, basis, label_raw, concept) 조합이 서로 다른 스냅샷/기간 블록에서
# **반복 등장**하는 SCE 표가 있어(예: 고려아연 '기타포괄손익>매도가능증권평가손익'이
# 2016 연간 블록과 2016 Q1 비교블록에 각각 다른 값으로 존재, 두산 '소계.'가 이익잉여금
# 열과 자본금 열에 서로 다른 row_order 로 존재), 라벨+개념만으로는 어느 스냅샷인지
# 가리지 못해 두 번째 항목이 첫 번째를 덮어쓰는 딕셔너리 충돌이 났다. 기존 SK텔레콤
# 항목도 실측 row_order(17)를 채워 이 스키마로 이전했다(동작은 그대로).
#
# 아래 항목들은 R162-d(행 항등식)·R162(열 롤포워드)가 이중증거 요건 때문에 채택하지
# 못한 **개별 확정** 사례다(verification fix batch #13, camp_run 원문/항등식 교차대조
# 기반, 2026-09-26). 일부는 이전 배치가 **반대 방향으로** 뒤집어놓은 것을 되돌린다
# (고려아연 `(부의)지분법자본변동`·POSCO `자기주식의 처분`·두산 `-자기주식의 이익소각`
# 기타자본구성요소·`-인적분할`/`소계.` 자본금·기타포괄손익누계액·SKC `기타거래`
# 비지배지분·`IFRS16 도입` — 각 행 내부 항등식과 소계/연간 롤포워드로 재검증 완료).
_MANUAL_SIGN_FIXES: Dict[Tuple[str, str, str, str, int], Tuple[int, int]] = {
    ("20210517001554", "separate", "2021.03.31 (기말자본)", "자기주식", 17):
        (2_169_660_000_000, -2_169_660_000_000),

    # 고려아연 2017Q1 20170515004148 (consolidated 7 + separate 2)
    ("20170515004148", "consolidated", "기타포괄손익>매도가능증권평가손익", "자본 합계", 18):
        (9_929_116_812, -9_929_116_812),
    ("20170515004148", "consolidated", "기타포괄손익>매도가능증권평가손익", "기타포괄손익누계액", 34):
        (5_450_871_274, -5_450_871_274),
    ("20170515004148", "consolidated", "기타포괄손익>매도가능증권평가손익", "자본 합계", 34):
        (6_012_699_313, -6_012_699_313),
    ("20170515004148", "consolidated", "(부의)지분법자본변동", "기타포괄손익누계액", 36):
        (-329_265_129, 329_265_129),  # revert — 배치#9가 반대방향으로 뒤집음
    ("20170515004148", "consolidated", "해외사업환산손익", "기타포괄손익누계액", 37):
        (9_720_680_163, -9_720_680_163),
    ("20170515004148", "consolidated", "해외사업환산손익", "자본 합계", 37):
        (9_720_680_163, -9_720_680_163),
    ("20170515004148", "consolidated", "종속기업 유상증자", "자본 합계", 28):
        (53_594_000, -53_594_000),
    ("20170515004148", "separate", "매도가능증권평가이익", "자본 합계", 9):
        (4_462_932_945, -4_462_932_945),
    ("20170515004148", "separate", "확정급여제도 재측정요소", "자본 합계", 11):
        (6_195_888_902, -6_195_888_902),

    # POSCO홀딩스 2018H1 — 20180814002744 + byte-identical 20180911000187 (6 x 2)
    ("20180814002744", "separate", "(5)자기주식의 처분", "자기주식", 8):
        (-214_155_208, 214_155_208),  # revert
    ("20180814002744", "separate", "Ⅳ.회계정책변경에 따른 증가(감소)", "적립금", 9):
        (321_653_854_633, -321_653_854_633),
    ("20180814002744", "separate", "2018.01.01 (Ⅰ.기초자본)", "적립금", 11):
        (88_263_539_758, -88_263_539_758),
    ("20180814002744", "separate", "2018.01.01 (Ⅰ.기초자본)", "자기주식", 11):
        (1_533_054_410_954, -1_533_054_410_954),
    ("20180814002744", "separate", "(3)지분증권평가손익", "이익잉여금", 14):
        (3_469_560_708, -3_469_560_708),
    ("20180814002744", "separate", "(5)자기주식의 처분", "자기주식", 19):
        (-270_466_936, 270_466_936),  # revert
    ("20180911000187", "separate", "(5)자기주식의 처분", "자기주식", 8):
        (-214_155_208, 214_155_208),
    ("20180911000187", "separate", "Ⅳ.회계정책변경에 따른 증가(감소)", "적립금", 9):
        (321_653_854_633, -321_653_854_633),
    ("20180911000187", "separate", "2018.01.01 (Ⅰ.기초자본)", "적립금", 11):
        (88_263_539_758, -88_263_539_758),
    ("20180911000187", "separate", "2018.01.01 (Ⅰ.기초자본)", "자기주식", 11):
        (1_533_054_410_954, -1_533_054_410_954),
    ("20180911000187", "separate", "(3)지분증권평가손익", "이익잉여금", 14):
        (3_469_560_708, -3_469_560_708),
    ("20180911000187", "separate", "(5)자기주식의 처분", "자기주식", 19):
        (-270_466_936, 270_466_936),

    # SK하이닉스 2019Q3 20191114002661 separate
    ("20191114002661", "separate", "자기주식 취득", "기타자본", 3):
        (1_736_514_000_000, -1_736_514_000_000),
    ("20191114002661", "separate", "자기주식 취득", "자본 합계", 3):
        (1_736_514_000_000, -1_736_514_000_000),

    # 제주반도체 2019FY 20200330002326 consolidated
    ("20200330002326", "consolidated", "2017.01.01 (기초자본)", "기타자본구성요소", 0):
        (4_986_168_200, -4_986_168_200),
    ("20200330002326", "consolidated", "2017.01.01 (기초자본)", "비지배지분", 0):
        (47_822_249, -47_822_249),
    ("20200330002326", "consolidated", "연결대상범위의 변동", "기타자본구성요소", 22):
        (259_656_740, -259_656_740),

    # SKC 2020FY 20210322000882 consolidated
    ("20210322000882", "consolidated", "기타거래", "지배기업의 소유주에게 귀속되는 자본 합계", 16):
        (40_181_325, -40_181_325),
    ("20210322000882", "consolidated", "기타거래", "비지배지분", 16):
        (-377_744_923, 377_744_923),  # revert
    ("20210322000882", "consolidated", "기업회계기준서 제1116호의 도입", "이익잉여금", 20):
        (-5_277_235, 5_277_235),  # revert
    ("20210322000882", "consolidated", "기업회계기준서 제1116호의 도입",
     "지배기업의 소유주에게 귀속되는 자본 합계", 20):
        (-5_277_235, 5_277_235),  # revert
}

# 두산 2019FY separate — 20200330004497 + byte-identical 20240418000398 · 20241002000388.
# 3개 rcept 모두 동일 10패턴이라 별도로 생성한다(반복 리터럴을 피하려 코드로 구성해도
# _MANUAL_SIGN_FIXES 는 순수 데이터 딕셔너리로 유지 — 값 자체는 위 항목들과 같은
# 방식으로 하드코드해야 `git grep` 로 이력을 추적하기 쉽다).
_DOOSAN_2019_SEP_PATTERNS: Tuple[Tuple[str, str, int, int, int], ...] = (
    ("-자기주식의 이익소각", "기타자본구성요소", 13, -61_480_484_781, 61_480_484_781),  # revert
    ("-자기주식의 이익소각", "이익잉여금", 13, 61_480_484_781, -61_480_484_781),
    ("-배당금지급", "이익잉여금", 14, 100_425_616_900, -100_425_616_900),
    ("-자기주식", "기타자본구성요소", 17, 26_624_854_000, -26_624_854_000),
    ("소계.", "이익잉여금", 18, 161_906_101_681, -161_906_101_681),
    ("-인적분할", "자본금", 55, -11_107_630_000, 11_107_630_000),  # revert
    ("-인적분할", "기타포괄손익누계액", 55, -804_793_372, 804_793_372),  # revert
    ("-인적분할", "이익잉여금", 55, 804_793_372, -804_793_372),
    ("소계.", "자본금", 58, -11_107_630_000, 11_107_630_000),  # revert
    ("소계.", "기타포괄손익누계액", 58, -804_793_372, 804_793_372),  # revert
)
for _rcept in ("20200330004497", "20240418000398", "20241002000388"):
    for _label, _concept, _row, _old, _new in _DOOSAN_2019_SEP_PATTERNS:
        _MANUAL_SIGN_FIXES[(_rcept, "separate", _label, _concept, _row)] = (_old, _new)
del _rcept, _label, _concept, _row, _old, _new


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
               concept_of_col_label(getattr(ln, "col_label", None)), ln.row_order)
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
    if not winners:
        # R162-f (2026-09-25) — the filer's own subtotal row can be internally off, so the
        # arithmetic subtotal proof (R162-c) fails and the row stays in Σ, double-counting:
        # LG전자 20250317001029 연결 '자본 증가(감소) 합계' 2,389,964 vs the real change
        # 2,393,964 (it omits 사업결합 4,000). Retry with **label-identified** subtotal rows
        # left out; the explicit 기초/기말 balances still have to close exactly and the flip
        # must still be unique.
        label_subs = {m for m in summed if _SUBTOTAL_LABEL_RE.search(cells[m].label_raw)}
        if label_subs:
            summed_f = [m for m in summed if m not in label_subs]
            members_f = [open_i, *summed_f, close_i]

            def holds_f(signs: Dict[int, int]) -> bool:
                total = signs[open_i] * abs(cells[open_i].value)
                for m in summed_f:
                    total += signs[m] * abs(cells[m].value)
                return total == signs[close_i] * abs(cells[close_i].value)

            if holds_f(current):
                return []
            for i in members_f:
                if cells[i].value <= 0:
                    continue
                trial = dict(current)
                trial[i] = -1
                if holds_f(trial):
                    winners.append(i)
                    if len(winners) > 1:
                        return []
            if len(winners) == 1:
                i = winners[0]
                sign, _label = _required_sign(cells[i], anchors, carried)
                if sign == 1:
                    return []
                return [(i, -1)]
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


# ── R162-d (2026-09-25, 사용자 결정: **이중증거 셀만** 적용) ─────────────────────────
#
# 열(`col_label`) 계층에서 한 그룹 아래 '합계' 열이 정확히 하나면
# Σ(형제 열) = 그 합계 열 — 최상위도 같다(지배기업 소유주 귀속 자본 합계 + 비지배지분
# = 자본 합계). 한 행 안에서 이 항등식이 깨져 있는데, 닫는 **양수 셀의 최소 부분집합이
# 유일**하면(≤`_MAX_ROW_FLIP`, 원래 성립하던 항등식은 깨지 않고) 그 배정을 후보로 삼는다.
#
# ★이중증거(사용자 결정): 뒤집는 셀 **모두**가 이 필링 안 다른 곳(BS·IS·CF 본문, 다른
# SCE 행, 주석)에 같은 금액이 **음수로** 있어야 한다. 단, 그 "다른 곳"이 **같은 행의
# 다른 열**일 때는 그 열이 지금 풀려는 항등식의 구성원이면 안 된다 — 그건 새 증거가
# 아니라 지금 풀려는 항등식 자체를 순환 재사용하는 것이다(2026-09-25 표본 원문대조
# #7: '당기순이익(손실)' 행에서 이익잉여금·합계 두 칸뿐인 항등식에 서로를 증거로 썼다).
# 반대로 **다른** 항등식(예: 중첩계층의 안쪽 합계)의 구성원이면 유효한 증거다 — 2026-09-25
# 표본원문대조 #17(제이씨현시스템 `20210517000597`)에서 이익잉여금 칸이 이미
# 확정 음수인 것이 그 바깥 합계 칸의 증거로 유효했다.
#
# ★교차-basis(연결↔별도) SCE 증거는 **자본거래/이월잔액**(자기주식·배당·자본조정·
# 결손금·증자·감자·전환·상환·기초자본/기말자본 등)에만 인정한다. 순이익·기타포괄손익
# 재측정·지분법·처분손익 같은 **손익 결과** 항목은 연결·별도가 서로 다른 부호를 가지는
# 것이 정상이라 배제한다 — 2026-09-25 표본원문대조 #1(이니텍 `20171114002176`
# 별도 '확정급여채무의재측정요소'): 원문은 별도 두 칸 모두 양수(무괄호)로 일관되게
# 인쇄됐는데, 연결의 같은 금액이 음수(원문에 괄호 있음)라는 이유만으로 뒤집으면
# 오히려 이전 규칙이 잘못 뒤집어 놓은 형제 칸을 "확증"하며 별도 금액까지 틀리게 만든다.
_TOTAL_COL_RE = re.compile(r"합\s*계|총\s*계")
_MAX_ROW_FLIP = 3
_CAPITAL_TRANSACTION_RE = re.compile(
    r"자기주식|배당|자본조정|결손금|무상증자|유상증자|무상감자|유상감자|감자차손|"
    r"전환|상환|신종자본증권|연결범위변동|자본금|주식기준보상|주식선택권"
)


def _row_identities(by_path: Dict[Tuple[str, ...], object]) -> List[Tuple[Tuple, List[Tuple]]]:
    """`{col-path -> line}` 한 행에서 (합계 경로, [구성원 경로...]) 항등식 목록을 뽑는다."""
    children: Dict[Tuple, List[Tuple]] = defaultdict(list)
    for path in by_path:
        children[path[:-1]].append(path)
    out = []
    for parent, kids in children.items():
        totals = [k for k in kids if _TOTAL_COL_RE.search(k[-1])]
        if len(totals) != 1:
            continue
        members = [k for k in kids if k != totals[0]]
        resolved = [m for m in members if m in by_path]
        groups = {k[:len(parent) + 1] for k in by_path if len(k) > len(parent) + 1
                  and k[:len(parent)] == parent}
        ok = True
        for g in groups:
            gkids = children.get(g, [])
            gt = [k for k in gkids if _TOTAL_COL_RE.search(k[-1])]
            if len(gt) != 1:
                ok = False
                break
            resolved.append(gt[0])
        if ok and resolved:
            out.append((totals[0], resolved))
    return out


def _row_flip_solution(by_path: Dict[Tuple, object],
                        identities: List[Tuple[Tuple, List[Tuple]]]
                        ) -> Optional[Tuple[Tuple, ...]]:
    """항등식을 전부 닫는, 유일한 최소 양수-부분집합 반전을 찾는다(없으면 None)."""
    def holds(signs: Dict[Tuple, int], ident) -> bool:
        total, members = ident
        val = lambda p: signs.get(p, 1) * getattr(by_path[p], "value_won")  # noqa: E731
        return sum(val(m) for m in members) == val(total)

    broken = [i for i in identities if not holds({}, i)]
    if not broken:
        return None
    involved = sorted({p for t, ms in broken for p in [t, *ms]}
                      | {p for t, ms in identities for p in [t, *ms]})
    positives = [p for p in involved if getattr(by_path[p], "value_won") > 0]
    for size in range(1, _MAX_ROW_FLIP + 1):
        sols = []
        for combo in itertools.combinations(positives, size):
            signs = {p: -1 for p in combo}
            if all(holds(signs, i) for i in identities):
                sols.append(combo)
                if len(sols) > 1:
                    break
        if sols:
            return sols[0] if len(sols) == 1 else None
    return None


def repair_sce_row_identity(lines: List) -> List[Correction]:
    """R162-d — SCE 한 행 안의 **열 항등식**과 **이중증거**로 원문에서 빠진 음수 괄호를
    복원한다. 모듈 docstring의 R162-d 절 참조. 열 롤포워드(R162/R162-e/f)가 먼저 돈
    뒤에 적용한다."""
    anchors = build_sign_anchors(lines)
    # magnitude -> {(statement, basis, table_seq, row_order, col_path)} — report_lines
    # statements only (BS/IS/CF/SCE). note_lines (statement='note') tracked separately:
    # per the user's decision any note magnitude match counts regardless of site,
    # so it needs no site-exclusion bookkeeping.
    neg_sites: Dict[int, Set[Tuple]] = defaultdict(set)
    has_neg_note: Set[int] = set()
    for ln in lines:
        v = getattr(ln, "value_won", None)
        if v is None or v >= 0:
            continue
        mag = -int(v)
        stmt = getattr(ln, "statement", None)
        if stmt == "note":
            has_neg_note.add(mag)
            continue
        col_label = getattr(ln, "col_label", None)
        col_path = tuple(s.strip() for s in col_label.split(">")) if col_label else ()
        neg_sites[mag].add((stmt, ln.basis, getattr(ln, "table_seq", None),
                            getattr(ln, "row_order", None), col_path))

    rows: Dict[Tuple, Dict[Tuple, object]] = defaultdict(dict)
    for ln in lines:
        if getattr(ln, "statement", None) != "SCE" or getattr(ln, "value_won", None) is None:
            continue
        col_label = getattr(ln, "col_label", None)
        if not col_label:
            continue
        path = tuple(s.strip() for s in col_label.split(">"))
        rows[(ln.basis, getattr(ln, "table_seq", None), ln.row_order)][path] = ln

    corrections: List[Correction] = []
    for (basis, table_seq, row_order), by_path in rows.items():
        if len(by_path) < 2:
            continue
        identities = _row_identities(by_path)
        if not identities:
            continue
        solution = _row_flip_solution(by_path, identities)
        if not solution:
            continue

        participants: Dict[Tuple, Set[Tuple]] = defaultdict(set)
        for t, ms in identities:
            group = {t, *ms}
            for p in group:
                participants[p] |= group - {p}

        row_label = next(iter(by_path.values())).label_raw or ""
        row_is_capital_txn = bool(_is_balance_label(row_label)
                                  or _CAPITAL_TRANSACTION_RE.search(row_label))

        ok = True
        for p in solution:
            ln = by_path[p]
            mag = abs(int(ln.value_won))
            excluded = {("SCE", basis, table_seq, row_order, q) for q in participants[p]}
            report_sites = {s for s in neg_sites.get(mag, ()) if s not in excluded}
            if not report_sites and mag not in has_neg_note:
                ok = False
                break
            same_basis_evidence = any(b == basis for _st, b, _ts, _ro, _cp in report_sites)
            # 같은 basis 의 report_lines 증거가 아니면(교차-basis SCE·BS/IS/CF, 또는
            # 주석뿐) — 그 신뢰도를 원문으로 직접 검증하지 않았으므로, 자본거래/이월
            # 잔액 행에만 인정한다(모듈 상단 R162-d 절 참조).
            if not same_basis_evidence and not row_is_capital_txn:
                ok = False
                break
            anchor_sign, _ = _required_sign(
                _Cell(line=ln, basis=basis, label_raw=ln.label_raw or "",
                      col_label=ln.col_label, value=int(ln.value_won)), anchors)
            if anchor_sign == 1:
                ok = False
                break
        if not ok:
            continue

        for p in solution:
            ln = by_path[p]
            old = int(ln.value_won)
            ln.value_won = -old
            corrections.append(Correction(
                basis=basis, table_seq=table_seq, row_order=row_order,
                col_index=ln.col_index, col_label=ln.col_label, label_raw=ln.label_raw or "",
                old_value=old, new_value=-old, anchor_label="R162-d 행항등식+이중증거"))
    if corrections:
        logger.debug(f"[report_lines/R162-d] SCE 행 항등식 부호 복원 {len(corrections)}셀")
    return corrections
