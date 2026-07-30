"""계층3 D&A 소스 — note_lines 에서 D&A canonical 을 뽑는다.

계층3 의 본체(combine)는 본문(report_lines)만 읽는다. 그런데 D&A 는 본문 CF 에 없는
기업이 많아 **주석이 실질 소스**다. 이 모듈이 주석 쪽 공급을 담당해, combine 이 기존
표준화 규칙(rule_additive_da → rule_derive_ebitda)에 그대로 태울 수 있는
canonical dict 를 돌려준다.

체인은 계층3 공통 해석 계층을 그대로 쓴다(항목별 전용 추출기를 만들지 않는다):
    ②note_topics.map_topic  → 어느 주석인가
    ③note_periods           → 어느 셀이 당기인가
    ④note_labels            → 어떤 계정인가

★기간 — FY + interim(2026-07-29 확장)
    처음에는 FY 만 대상으로 했다. interim 주석 표는 한 기간 안에서 열이 '3개월'(당해 분기)과
    '누적'(기초~현재)로 갈려 어느 쪽인지 알 수 없었기 때문이다.
    계층2 가 col_label 을 전사하면서 이 구분이 가능해졌다:
        col0 '…>3개월' 감가상각비   837,708,000,000
        col1 '…>누적'  감가상각비 1,656,460,000,000   ← std_financials interim = 누적
    → interim 은 prefer_cumulative=True 로 누적 열을 고른다. 누적 열을 못 찾으면
      값을 만들지 않는다(추측 금지).

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
from parser.common.note_topics import (DA_SOURCE_BROAD, DA_SOURCE_COMPONENT,
                                       DA_SOURCE_PRIORITY, map_topic)

_ROWS_SQL = text(
    """
    SELECT section_path, table_seq, row_order, col_index, col_label, label_raw, value_won
    FROM note_lines
    WHERE rcept_no = :rcept
      AND basis = :basis
      AND statement = 'note'
      AND value_won IS NOT NULL
      -- ★F2 가드(2026-07-31): 계층2 가 헤더 규칙에 걸린 행을 **버리지 않고 전사**하게 됐다.
      --   그 행은 대개 진짜 열 헤더('당기말'·'제 72 기')라 D&A 합산에 섞이면 오염이다.
      --   행이 기간축인 표에서만 실데이터인데, 그 판단은 이 쿼리가 아니라 note_periods 가
      --   '기간라벨' hint 를 신호로 쓰는 쪽에서 한다. 기본은 제외.
      AND header_hint IS NULL
    """
)


class _Row:
    # col_label 은 기간 판정(note_periods 의 COL_LABEL 규칙)에 쓰인다 — 빠뜨리면
    # 헤더가 DB 에 있어도 계층3 가 못 보고 위치 추측으로 돌아간다.
    __slots__ = ("table_seq", "col_index", "col_label", "label_raw",
                 "value_won", "row_order")

    def __init__(self, r):
        self.table_seq = r.table_seq
        self.col_index = r.col_index
        self.col_label = getattr(r, "col_label", None)
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
    if not rcept_no or period not in ("FY", "H1", "Q1", "Q3"):
        return {}
    # interim 은 누적 열을 골라야 한다(위 주석 참조).
    prefer_cum = period != "FY"

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

    def _from_topic(topic: str) -> dict[str, int]:
        """한 주제에서 당기 D&A 버킷을 뽑는다(표 하나만 채택)."""
        for _section, srows in by_topic.get(topic, {}).items():
            # ★한 주석 안에 형제표가 아닌 표가 여러 개일 수 있다(판관비를 부문별로 쪼갠 표,
            #   법인세 주석의 일시적차이 표 등). 그 표들의 col_index=0 이 전부 rank 0 이므로
            #   그냥 합치면 **같은 비용을 여러 번 더한다**(실측: v2 대비 2.87배).
            #   → table_seq 단위로 모은 뒤 **표 하나만** 채택한다.
            per_table: dict[int, dict[str, int]] = {}
            for cell in resolve_periods(srows, prefer_cumulative=prefer_cum):
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
                # 결합 표기('감가상각비와 무형자산상각비')는 그 자체가 D&A 합계다.
                # ★단, 결합 행과 **나란히** 별도 행이 오는 서식이 흔하다(실측 7건) →
                #   세부 버킷을 따로 내보내면 rule_additive_da 가 da_direct 를 우선하며
                #   별도 행을 버린다. 여기서 합쳐 넘긴다.
                out[DA_COMBINED] = (acc[DA_COMBINED]
                                    + acc.get(DEPRECIATION, 0)
                                    + acc.get(DEPRECIATION_ROU, 0)
                                    + acc.get(AMORTIZATION, 0))
            else:
                for k in (DEPRECIATION, DEPRECIATION_ROU, AMORTIZATION):
                    if acc.get(k):
                        out[k] = acc[k]
            if out:
                return out
        return {}

    # ① 완결형은 **먼저 성립하는 하나**만 쓴다(여러 개를 합치면 같은 비용을 이중 계상).
    #    ★단, '값이 하나라도 나왔다'로 채택하면 안 된다. 상위 소스가 **불완전한 결과**를
    #      내놓으면 더 나은 하위 소스가 막힌다.
    #      실측 01274329(성일하이텍) FY2024:
    #        비용의성격별 → '당기손익으로 인식된 감가상각비, 무형자산상각비, 손상차손(환입)'
    #          = 20,893,933,000 은 손상차손이 섞여 있어 배제 → 무형자산상각비 423,373,000 만 남음
    #        현금흐름표   → '감가상각비에 대한 조정' 20,965,887,000
    #                      '무형자산상각비에 대한 조정' 423,373,000  ← 깨끗하게 분리됨
    #      감가상각 없이 상각비만 있는 결과는 D&A 로서 불완전하다 → 완전한 소스를 우선한다.
    partial = None
    for topic in DA_SOURCE_BROAD:
        got = _from_topic(topic)
        if not got:
            continue
        complete = bool(got.get(DA_COMBINED) or got.get(DEPRECIATION)
                        or got.get(DEPRECIATION_ROU))
        if complete:
            return got
        if partial is None:
            partial = got          # 감가상각분이 없는 반쪽 결과 — 마지막 수단으로만

    # ② 완결형이 없으면 구성요소형을 **전부 합산**한다. 자산군별 주석이라 하나만 고르면
    #    나머지가 통째로 빠진다(실측 01274329: 투자부동산 879만만 잡고 리스 14.9억 누락).
    merged: dict[str, int] = {}
    for topic in DA_SOURCE_COMPONENT:
        for k, v in _from_topic(topic).items():
            merged[k] = merged.get(k, 0) + v
    if merged:
        return merged

    # ③ 마지막 수단 — 완결형의 반쪽 결과(감가상각분 없이 상각비만). 구성요소형까지 없을 때만.
    return partial or {}
