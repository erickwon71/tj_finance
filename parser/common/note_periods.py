"""계층3 ③기간 해석 — 주석 표의 어느 셀이 '당기'인가.

문제
----
주석 행에는 기간 정보가 없다. 계층2 는 주석 컬럼을 연도로 **주장하지 않는다**(설계 의도):
`context_fiscal_year` 는 NULL, `period_kind` 도 NULL, `col_index` 는 위치일 뿐이다.

★2026-07-29 이후: 계층2 가 주석 표의 **열 헤더(col_label)** 를 전사한다(58a8e3f).
  '(단위: 천원)>당기' / '유형자산>건물>…' 처럼 들어오므로 기간을 **위치 추측이 아니라
  헤더 텍스트로** 판정한다(rule=COL_LABEL). 헤더가 없거나 기간 표기가 아니면 아래 구조
  규칙으로 폴백한다. 그 이전에 적재된 행은 col_label 이 NULL 이라 구조 규칙만 쓴다.

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

증감표(rollforward) — col_label 로 해결됨
    유형자산/무형자산 증감표는 컬럼이 **자산 분류**(토지·건물·기계…)라 기간축이 아니다.
    col_label 이전에는 MULTICOL 로 오인해 col_index 를 기간으로 읽었다
    (실측 00103592 FY2024: '12. 유형자산' 감가상각비 행의 col_index 0 이 0 이고 실제 값은
    col 4·5). 이제 헤더가 '유형자산>건물>감가상각누계액…' 으로 들어와 기간 표기가 아님이
    드러나므로 COL_LABEL 판정에서 제외되고 구조 규칙으로 폴백한다.
    보조 완충: DA_SOURCE_PRIORITY 에서 증감표 계열(PPE/무형/투자부동산)은 성격별·현금흐름표
    보다 뒤에 둔다.

반환에 `rule` 을 담아 호출측이 신뢰도를 구분할 수 있게 한다 — 근거 없는 셀을 조용히
'당기'로 단정하지 않는 것이 이 모듈의 요점이다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

# 형제표로 볼 라벨 집합 겹침 최소치(Jaccard). 표마다 합계행 유무 등 사소한 차이가 있어 1.0 은 과하다.
_SIBLING_MIN_JACCARD = 0.6
# 형제표 후보로 볼 최소 라벨 수 — 1~2행짜리 표는 우연히 겹친다.
_SIBLING_MIN_LABELS = 3


# ── col_label 기반 기간 판정 (2026-07-29) ────────────────────────────────────
# 계층2 가 주석 표의 열 헤더를 전사하기 시작하면서(58a8e3f) 기간을 **위치 추측이 아니라
# 헤더 텍스트**로 판정할 수 있게 됐다. 헤더는 '(단위: 천원)>당기' 처럼 경로로 들어오므로
# 마지막 구간을 본다.
#   · 당기/전기 표기      → 직접 판정
#   · 제56기/제55기 표기  → 기수가 큰 쪽이 당기
#   · 자산분류('유형자산>건물>…') → 기간축이 아님 → None (구조 규칙으로 폴백)
# ★단어 경계 필수. '^전기' 로만 매칭하면 '전기요금'(전력비)이 '전기(prior period)'로
#   오판된다(실측). 뒤에 한글 음절이 더 붙으면 다른 단어다 — 말/초 접미만 허용한다.
_CUR_RE = re.compile(r"^(당기|당분기|당반기|금기)(말|초)?(?![가-힣])")
_PRIOR_RE = re.compile(r"^(전기|전분기|전반기|직전기)(말|초)?(?![가-힣])")
_PERIOD_NO_RE = re.compile(r"제\s*(\d+)\s*기")


def _last_segment(col_label: Optional[str]) -> str:
    if not col_label:
        return ""
    return col_label.split(">")[-1].strip()


_UNIT_SEG_RE = re.compile(r"^[(（]?\s*단위")


def _segments(col_label: Optional[str]) -> list[str]:
    """열 헤더 경로의 조각들(단위 선언 조각 제외), **자간 공백을 뺀 형태** — '누 적'·'당 분 기'·
    '전 분 기' 처럼 띄어 쓴 헤더가 흔하다(실측 00217743 20151116000973, 00178790 20251114000638)."""
    if not col_label:
        return []
    segs = (re.sub(r"\s+", "", s) for s in col_label.split(">"))
    return [s for s in segs if s and not _UNIT_SEG_RE.match(s)]


def period_rank_from_label(col_label: Optional[str]) -> Optional[int]:
    """열 헤더에서 기간 순위를 읽는다(0=당기). 기간 표기가 아니면 None.

    ★R230(2026-10-10): 경로의 **모든 조각**을 본다 — 헤더가 '당기>매출원가'·'당기>판매비와관리비'
    처럼 [기간 > 기능] 2단이면 마지막 조각은 기간이 아니다(종전엔 None → 위치 추측 MULTICOL 로
    떨어져 판관비 열이 '전기'가 됐다)."""
    for seg in _segments(col_label):
        if _CUR_RE.match(seg):
            return 0
        if _PRIOR_RE.match(seg):
            return 1
    return None


# ── R230(2026-10-10): 같은 기간 안의 기능별 열 — 합계 열 하나만 ─────────────────
# 비용의 성격별 분류 표는 열이 [기간 > 기능] 2단인 서식이 있다:
#   '(단위:천원)>누적>매출원가' | '…>누적>판매비와 관리비' | '…>누적>성격별 비용'
# 기간 열을 '첫 누적 열' 하나로 고르면 매출원가 몫만 읽고, 그 열이 빈 행(무형자산상각비)은
# 통째로 빠진다(실측 00110431 2015Q3 [기재정정] 20151209000350: 감가상각비 343,401,000 만 →
# 정답 721,815,000 + 1,076,024,000). 같은 기간의 열이 여럿이면 **합계 열**을 쓴다. 합계 열이
# 정확히 하나가 아니면 종전처럼 앞 열(합산 추측은 하지 않는다).
_PERIOD_SEG_RE = re.compile(
    r"^(당기|당분기|당반기|금기|전기|전분기|전반기|직전기)(말|초)?(?![가-힣])"
    r"|누적|3\s*개월|제\s*\d+\s*(?:\(\s*[당전]\s*\)\s*)?기|\d{4}\s*년|\d{4}[.\-/]\d{1,2}")
_TOTAL_SEG_RE = re.compile(r"^(?:합\s*계|계|총\s*계|총\s*액|합\s*계\s*액|성격별\s*비용(?:\s*합계)?|비용\s*합계|총\s*비용)$")


def _dim_key(col_label: Optional[str]) -> tuple:
    """기간 조각을 뺀 나머지 조각(기능·자산분류 등)."""
    return tuple(s for s in _segments(col_label) if not _PERIOD_SEG_RE.search(s))


def _period_key(col_label: Optional[str]) -> tuple:
    return tuple(s for s in _segments(col_label) if _PERIOD_SEG_RE.search(s))


def _one_column(cols: list[int], labels: dict[int, str]) -> list[int]:
    """같은 기간으로 판정된 열들 → 쓸 열 하나: 합계 열이 정확히 하나면 그 열, 아니면 앞 열."""
    if len(cols) <= 1:
        return cols
    dims = {c: _dim_key(labels.get(c)) for c in cols}
    if len(set(dims.values())) == 1:
        return [min(cols)]          # 기능 구분이 없는 중복 헤더 — 종전처럼 앞 열
    totals = [c for c in cols if dims[c] and _TOTAL_SEG_RE.match(dims[c][-1].replace(" ", ""))]
    # no single total column: the earlier behaviour (first column) — the rule only changes
    # tables that print their own total
    return totals if len(totals) == 1 else [min(cols)]


def _col_labels(trows: list) -> dict[int, str]:
    labels: dict[int, str] = {}
    for r in trows:
        ci = r.col_index or 0
        lbl = getattr(r, "col_label", None)
        if lbl and ci not in labels:
            labels[ci] = lbl
    return labels


# ── interim(H1/Q1/Q3) 누적/분기 열 구분 (2026-07-29) ─────────────────────────
# 반기·분기 보고서의 주석 표는 한 기간 안에서 열이 '3개월'(당해 분기)과 '누적'(기초~현재)로
# 갈린다. std_financials 의 interim 행은 **누적** 기준이므로 누적 열을 골라야 한다.
#   실측 현대차 H1 2024 비용의 성격별 분류:
#     col0 '…>3개월' 감가상각비   837,708,000,000
#     col1 '…>누적'  감가상각비 1,656,460,000,000   ← 이쪽을 써야 한다
_CUM_RE = re.compile(r"누적")
_DISCRETE_RE = re.compile(r"3개월|3\s*개월|당분기|당3분기")
_THREE_MONTH_RE = re.compile(r"3\s*개월")
_PRIOR_LOOSE_RE = re.compile(r"^(?:전\s*누적|전\s*년|전\s*기|전\s*분\s*기|전\s*반\s*기|직전)")


def cumulative_cols(trows: list) -> Optional[list[int]]:
    """표에서 당기 '누적' 열(R230: 같은 기간의 기능별 열이면 합계 열 하나). 헤더에 누적 표기가
    없으면 None.

    당기 누적 = 첫 누적 열과 기간 조각이 같은 열들(헤더가 [당기 3개월, 당기 누적, 전기 3개월,
    전기 누적] 순이라 첫 누적 열이 당기다 — 종전 규칙 그대로). 전기 표기가 붙은 열은 뺀다."""
    labels = _col_labels(trows)
    # a '3개월' column is never the cumulative one even under a '당누적3분기' header, and
    # '전누적…'/'전년…' segments are the prior period (실측 00126487 2021Q3 20211115001068:
    # '당누적3분기>3개월' 46,095,000 | '당누적3분기>누적' 7,812,531,000 | '전누적3분기>…')
    cum = sorted(ci for ci, l in labels.items() if any(_CUM_RE.search(sg) for sg in _segments(l))
                 and period_rank_from_label(l) != 1
                 and not any(_THREE_MONTH_RE.search(s) or _PRIOR_LOOSE_RE.match(s) for s in _segments(l)))
    if not cum:
        return None
    first = _period_key(labels[cum[0]])
    return _one_column([ci for ci in cum if _period_key(labels[ci]) == first], labels)


def cumulative_col(trows: list) -> Optional[int]:
    """표에서 당기 '누적' 열의 col_index. 헤더로 판별 불가하면 None."""
    cols = cumulative_cols(trows)
    return cols[0] if cols else None


def _ranks_from_col_labels(trows: list) -> Optional[dict[int, int]]:
    """한 표의 {col_index: period_rank}. 헤더로 판정 불가하면 None.

    제N기 표기는 표 안에서 **상대 비교**해야 하므로(기수가 큰 쪽이 당기) 따로 처리한다.
    """
    labels = _col_labels(trows)
    if not labels:
        return None

    ranks = {ci: period_rank_from_label(l) for ci, l in labels.items()}
    if any(v is not None for v in ranks.values()):
        # 당기/전기 표기가 하나라도 있으면 그걸 신뢰한다. 판정 안 된 열은 제외.
        # R230: 같은 순위의 열이 기능별로 여럿이면 합계 열 하나만(고를 수 없으면 그 순위 없음).
        out: dict[int, int] = {}
        for rank in set(v for v in ranks.values() if v is not None):
            for ci in _one_column(sorted(c for c, v in ranks.items() if v == rank), labels):
                out[ci] = rank
        return out

    # 제N기 비교 — 기수가 큰 쪽이 당기.
    nos: dict[int, int] = {}
    for ci, l in labels.items():
        m = _PERIOD_NO_RE.search(_last_segment(l))
        if m:
            nos[ci] = int(m.group(1))
    if len(set(nos.values())) >= 2:
        order = sorted(nos.items(), key=lambda kv: -kv[1])
        return {ci: rank for rank, (ci, _n) in enumerate(order)}
    return None


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


def resolve_periods(rows: list, prefer_cumulative: bool = False) -> list[PeriodCell]:
    """주석 하나(section_path 단위)의 행들에 period_rank 를 매긴다.

    우선순위:
      1. 형제표가 있으면 → table_seq 순서가 기간(첫 표 = 당기). 각 표 안에서는 col_index=0 만 취한다
         (형제표 형태에서 추가 컬럼은 기간이 아니다).
      2. 형제표가 아닌 단일 표에서 col_index 가 여러 개면 → col_index 가 기간축(0=당기).
      3. 단일 표·단일 컬럼 → rank 0.

    prefer_cumulative: interim(H1/Q1/Q3) 용. 한 기간 표 안에서 '3개월' 대신 '누적' 열을
      고른다(std_financials interim 행은 누적 기준). FY 에는 누적/분기 구분이 없어 무시된다.
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
                trows = by_table[seq]
                # interim 은 형제표 안에서도 '3개월/누적' 로 열이 갈린다 → 누적 열 채택.
                want = cumulative_col(trows) if prefer_cumulative else None
                if want is None:
                    # R230: the extra columns of a sibling table are functions (매출원가/판관비/
                    # 합계) — the single total column when the table prints one, else column 0
                    labels = _col_labels(trows)
                    want = _one_column(sorted(labels), labels)[0] if labels else 0
                for r in trows:
                    if (r.col_index or 0) != want:
                        continue          # 형제표에서 여분 컬럼은 기간이 아니다
                    out.append(PeriodCell(
                        table_seq=seq, col_index=want, label_raw=r.label_raw,
                        value_won=r.value_won, period_rank=rank,
                        rule="SIBLING_TABLE", row_order=r.row_order,
                    ))
            continue

        for seq in seqs:
            trows = by_table[seq]
            # ★열 헤더가 있으면 그것으로 판정한다(위치 추측보다 정확).
            #   증감표('유형자산>건물>…')처럼 기간 표기가 없으면 None → 구조 규칙으로 폴백.
            if prefer_cumulative:
                cum = cumulative_col(trows)
                if cum is not None:
                    for r in trows:
                        if (r.col_index or 0) != cum:
                            continue
                        out.append(PeriodCell(
                            table_seq=seq, col_index=cum, label_raw=r.label_raw,
                            value_won=r.value_won, period_rank=0,
                            rule="COL_LABEL_CUM", row_order=r.row_order,
                        ))
                    continue

            col_ranks = _ranks_from_col_labels(trows)
            if col_ranks:
                for r in trows:
                    ci = r.col_index or 0
                    if ci not in col_ranks:
                        continue          # 기간으로 판정되지 않은 열은 버린다
                    out.append(PeriodCell(
                        table_seq=seq, col_index=ci, label_raw=r.label_raw,
                        value_won=r.value_won, period_rank=col_ranks[ci],
                        rule="COL_LABEL", row_order=r.row_order,
                    ))
                continue

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
