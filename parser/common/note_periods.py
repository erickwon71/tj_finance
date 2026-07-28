"""계층3 ③기간 해석 — 주석 표의 어느 셀이 '당기'인가.

문제
----
주석 행에는 기간 정보가 없다. 계층2 는 주석 컬럼을 연도로 **주장하지 않는다**(설계 의도):
`context_fiscal_year` 는 NULL, `period_kind` 도 NULL, `col_index` 는 위치일 뿐이다.
그리고 `col_label`(컬럼 헤더)은 주석 경로에서 **아예 채워지지 않아 전량 NULL** 이라,
'당기/전기' 헤더 텍스트를 DB 에서 읽을 수 없다(2026-07-28 실측).

게다가 주석의 col_index 는 기간 축이 아닌 경우가 많다 — 유형자산 증감표의 컬럼은
자산 분류이고, 금융상품 주석은 만기구간·공정가치수준이다. 그래서 "col_index=0 이 당기"를
무조건 적용하면 틀린다.

해법 — 구조에서 추론하고, 어떤 근거로 판단했는지 함께 돌려준다
--------------------------------------------------------------
관측된 두 형태(2026-07-28 실측, 비용의성격별 n=46: 형제표 39 · 다열 7):

  ① 형제표(SIBLING) : 당기·전기가 **별도 table_seq** 로 쪼개지고 둘 다 col_index=0.
                      라벨 집합이 사실상 같다. → table_seq 오름차순이 기간 순서.
                      ★교차보고서 자기일관성으로 검증됨(42 지지 / 0 역전).
  ② 다열(MULTICOL)  : 한 표 안에서 col_index 0=당기, 1=전기.

판별은 **라벨 서명**으로 한다: 같은 주석 안에서 인접 표들의 라벨 집합이 겹치면 형제표다.
이 판단은 section_path 에 의존하지 않아도 되지만(라벨만 봄), 있으면 후보를 좁혀 준다.

반환에 `rule` 을 담아 호출측이 신뢰도를 구분할 수 있게 한다 — 근거 없는 셀을 조용히
'당기'로 단정하지 않는 것이 이 모듈의 요점이다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

# 형제표로 볼 라벨 집합 겹침 최소치(Jaccard). 표마다 합계행 유무 등 사소한 차이가 있어 1.0 은 과하다.
_SIBLING_MIN_JACCARD = 0.6
# 형제표 후보로 볼 최소 라벨 수 — 1~2행짜리 표는 우연히 겹친다.
_SIBLING_MIN_LABELS = 3


@dataclass
class PeriodCell:
    """기간이 해석된 셀 하나."""
    table_seq: int
    col_index: int
    label_raw: str
    value_won: int
    period_rank: int          # 0 = 당기, 1 = 직전기, …
    rule: str                 # SIBLING_TABLE | MULTICOL | SINGLE | UNRESOLVED
    row_order: Optional[int] = None


@dataclass
class TableGroup:
    """한 주석 안에서 같은 기간축을 공유하는 표 묶음."""
    table_seqs: list[int] = field(default_factory=list)
    rule: str = "SINGLE"


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group_sibling_tables(rows: Iterable) -> list[TableGroup]:
    """라벨 서명이 겹치는 인접 표들을 기간 형제로 묶는다.

    rows: table_seq / label_raw / col_index 속성을 가진 행들(한 주석 = 한 section_path 범위).
    """
    labels_by_table: dict[int, set[str]] = defaultdict(set)
    for r in rows:
        if r.table_seq is None:
            continue
        labels_by_table[r.table_seq].add((r.label_raw or "").strip())

    seqs = sorted(labels_by_table)
    groups: list[TableGroup] = []
    cur: Optional[TableGroup] = None

    for i, seq in enumerate(seqs):
        if cur is None:
            cur = TableGroup(table_seqs=[seq])
            groups.append(cur)
            continue
        prev = cur.table_seqs[-1]
        a, b = labels_by_table[prev], labels_by_table[seq]
        if (
            len(a) >= _SIBLING_MIN_LABELS
            and len(b) >= _SIBLING_MIN_LABELS
            and _jaccard(a, b) >= _SIBLING_MIN_JACCARD
        ):
            cur.table_seqs.append(seq)
            cur.rule = "SIBLING_TABLE"
        else:
            cur = TableGroup(table_seqs=[seq])
            groups.append(cur)
    return groups


def resolve_periods(rows: list) -> list[PeriodCell]:
    """주석 하나(section_path 단위)의 행들에 period_rank 를 매긴다.

    우선순위:
      1. 형제표가 있으면 → table_seq 순서가 기간(첫 표 = 당기). 각 표 안에서는 col_index=0 만 취한다
         (형제표 형태에서 추가 컬럼은 기간이 아니다).
      2. 형제표가 아닌 단일 표에서 col_index 가 여러 개면 → col_index 가 기간축(0=당기).
      3. 단일 표·단일 컬럼 → rank 0.
    """
    out: list[PeriodCell] = []
    by_table: dict[int, list] = defaultdict(list)
    for r in rows:
        if r.table_seq is not None and r.value_won is not None:
            by_table[r.table_seq].append(r)
    if not by_table:
        return out

    for group in group_sibling_tables(rows):
        seqs = [s for s in group.table_seqs if s in by_table]
        if not seqs:
            continue

        if group.rule == "SIBLING_TABLE" and len(seqs) > 1:
            for rank, seq in enumerate(seqs):
                for r in by_table[seq]:
                    if (r.col_index or 0) != 0:
                        continue          # 형제표에서 여분 컬럼은 기간이 아니다
                    out.append(PeriodCell(
                        table_seq=seq, col_index=0, label_raw=r.label_raw,
                        value_won=r.value_won, period_rank=rank,
                        rule="SIBLING_TABLE", row_order=r.row_order,
                    ))
            continue

        for seq in seqs:
            trows = by_table[seq]
            ncols = len({(r.col_index or 0) for r in trows})
            rule = "MULTICOL" if ncols > 1 else "SINGLE"
            for r in trows:
                out.append(PeriodCell(
                    table_seq=seq, col_index=(r.col_index or 0),
                    label_raw=r.label_raw, value_won=r.value_won,
                    period_rank=(r.col_index or 0), rule=rule,
                    row_order=r.row_order,
                ))
    return out


def current_period_cells(rows: list) -> list[PeriodCell]:
    """당기(period_rank == 0)로 해석된 셀만."""
    return [c for c in resolve_periods(rows) if c.period_rank == 0]
