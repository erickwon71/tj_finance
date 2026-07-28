"""계층3 D&A 소스 — note_lines 에서 D&A canonical 을 뽑는다.

계층3 의 본체(combine)는 본문(report_lines)만 읽는다. 그런데 D&A 는 본문 CF 에 없는
기업이 많아 **주석이 실질 소스**다. 이 모듈이 주석 쪽 공급을 담당해, combine 이 기존
표준화 규칙(rule_additive_da → rule_derive_ebitda)에 그대로 태울 수 있는
canonical dict 를 돌려준다.

체인은 계층3 공통 해석 계층을 그대로 쓴다(항목별 전용 추출기를 만들지 않는다):
    ②note_topics.map_topic  → 어느 주석인가
    ③note_periods           → 어느 셀이 당기인가
    ④note_labels            → 어떤 계정인가

★기간 제약 — FY 만 대상
    1차 소스인 '비용의 성격별 분류' 주석은 **연간 총액**이다. interim(H1/Q1/Q3)에 그대로
    쓰면 누적/분기 구분이 깨진다. 기존 collector/expense_nature_sync.py 도 같은 이유로
    FY 만 타겟한다. 여기서도 동일 제약을 건다.

★정정공시 — 반드시 단일 rcept 로 고정
    원본+정정이 함께 잡히면 값이 **정확히 2배**가 된다(실측). 호출측이 canonical rcept 를
    넘기게 강제한다.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy import text

from parser.common.note_labels import (
    AMORTIZATION, DA_COMBINED, DEPRECIATION, DEPRECIATION_ROU, classify_da_label,
)
from parser.common.note_periods import resolve_periods
from parser.common.note_topics import DA_SOURCE_PRIORITY, map_topic

_ROWS_SQL = text(
    """
    SELECT section_path, table_seq, row_order, col_index, label_raw, value_won
    FROM note_lines
    WHERE rcept_no = :rcept
      AND basis = :basis
      AND statement = 'note'
      AND value_won IS NOT NULL
    """
)


class _Row:
    __slots__ = ("table_seq", "col_index", "label_raw", "value_won", "row_order")

    def __init__(self, r):
        self.table_seq = r.table_seq
        self.col_index = r.col_index
        self.label_raw = r.label_raw
        self.value_won = r.value_won
        self.row_order = r.row_order


def note_da_canonicals(
    session, rcept_no: str, basis: str, period: str = "FY"
) -> dict[str, int]:
    """주석에서 당기 D&A canonical 을 뽑는다.

    Returns:
        {"note.depreciation": …, "note.rou_depreciation": …, "note.amortization": …,
         "note.da_total": …} 중 확보된 것만. 소스가 없으면 빈 dict.
    """
    if period != "FY" or not rcept_no:
        return {}

    rows = session.execute(
        _ROWS_SQL, {"rcept": rcept_no, "basis": basis}
    ).fetchall()
    if not rows:
        return {}

    by_topic: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        topic = map_topic(r.section_path)
        if topic in DA_SOURCE_PRIORITY:
            by_topic[topic][r.section_path].append(_Row(r))

    # 우선순위대로 훑어 **처음 성립하는 주석 하나**만 쓴다.
    # 여러 주석을 합치면 같은 비용을 이중 계상한다(성격별 분류와 유형자산 증감표가 겹침).
    for topic in DA_SOURCE_PRIORITY:
        for _section, srows in by_topic.get(topic, {}).items():
            # ★한 주석 안에 형제표가 아닌 표가 여러 개일 수 있다(판관비를 부문별로 쪼갠 표,
            #   법인세 주석의 일시적차이 표 등). 그 표들의 col_index=0 이 전부 rank 0 이므로
            #   그냥 합치면 **같은 비용을 여러 번 더한다**(실측: v2 대비 2.87배).
            #   → table_seq 단위로 모은 뒤 **표 하나만** 채택한다.
            #   (SIBLING_TABLE 형태에서는 rank 0 셀이 모두 첫 표에 속하므로 동일하게 동작한다.)
            per_table: dict[int, dict[str, int]] = {}
            for cell in resolve_periods(srows):
                if cell.period_rank != 0:          # 당기만
                    continue
                bucket = classify_da_label(cell.label_raw)
                if bucket is None:
                    continue
                acc = per_table.setdefault(cell.table_seq, {})
                acc[bucket] = acc.get(bucket, 0) + abs(cell.value_won)

            if not per_table:
                continue
            # 신호가 가장 풍부한 표(버킷 종류 수) → 동률이면 앞선 표(작은 table_seq).
            best_seq = max(per_table, key=lambda s: (len(per_table[s]), -s))
            acc = per_table[best_seq]

            out: dict[str, int] = {}
            if acc.get(DA_COMBINED):
                # 결합 표기('감가상각,무형자산상각')는 그 자체가 D&A 합계다.
                out[DA_COMBINED] = acc[DA_COMBINED]
            for k in (DEPRECIATION, DEPRECIATION_ROU, AMORTIZATION):
                if acc.get(k):
                    out[k] = acc[k]
            if out:
                return out
    return {}
