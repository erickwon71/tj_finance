"""Phase 3(PRD 14) · 사업의 내용 — 부문·수출/내수 매출실적 본문 테이블 파서.

B4(생산능력/가동률, biz_section.py)에서 검증된 인프라(범용 ROWSPAN/COLSPAN 그리드 확장기
expand_table_grid, 헤딩 탐지 전략, 기간 해석, 값/차원 열 분류, 수치 파싱)를 재사용해
'매출실적/판매실적/매출현황' 표를 부문×채널(수출/내수/합계)×연도 단위로 구조화한다.

설계 근거(2026-07-12 실측 4사 — 삼성전자·S-Oil·한온시스템·유한양행):
- 채널(수출/내수/합계)이 나타나는 3가지 레이아웃:
  (a) 채널-차원열: 부문/품목 옆 별도 열에 수출/내수/합계 값이 반복(S-Oil, 삼성 지역별
      '구분' 열=내수/수출/계). 생산 파서의 전치형 metric_col 승격과 동일 기법으로 검출.
  (b) 채널-헤더: 값열 헤더에 수출/내수/합계 토큰(드물지만 대응).
  (c) 채널 없음: 부문별 총매출만(삼성 부문별) → channel='합계'.
- 값열은 **금액(비-비율)만** 채택 — 비율(%) 열(한온시스템 '비율(%)' 지역별 점유율)은 매출액이
  아니므로 제외(생산 파서와 정반대 방향: 생산은 가동률=비율을 살리지만 매출은 비율을 버린다).
- 라우팅: 생산 파서(biz_section.map_biz_table)는 _SALES_KW 가드로 매출표를 계속 배제하고, 이
  파서가 매출 헤딩 창에서만 캡처한다 → 이중 캡처 없음(같은 물리 표를 두 파서가 겹쳐 잡지 않도록
  parse_biz_metrics 에서 grid 중복 제거로 최종 보증).
- 수주상황표(수주처/납기/수주잔고)·부문별 재무요약표(순이익/총자산)는 매출 헤딩 뒤에 이어져도
  가드로 배제(B1 수주는 order_backlog 소관, 비범위).

usage:
    from fin2.extract.sales_section import parse_sales_metrics
    sec_rows, met_rows = parse_sales_metrics(Path("...annual/2024/....xml"), "00126380", 2024)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from lxml import etree

# B4 인프라 재사용(신규 그리드 확장기·수치 파서 작성 금지 — PRD 14 §4.2).
from fin2.extract.biz_section import (
    _FINANCIAL_STMT_KW,
    _HEADING_MAX_LEN,
    _NUMBERED_HEADING_RE,
    _PERIOD_GI_RE,
    _PERIOD_YEAR_RE,
    _is_clean_number,
    _load_root,
    _narrative_unit,
    _parse_value,
    _tag,
    _text,
    expand_table_grid,
    is_merged_column_table,
)

# 매출 소제목 키워드(공백 무시 매칭). '판매경로'는 S-Oil 실측상 수주잔고표로 이어지는 경우가
# 있어 제외 — 매출실적/판매실적/매출현황 집계표에 집중(PRD 14 §2, 수주는 비범위).
_SALES_HEADING_KW = ("매출실적", "판매실적", "매출현황")
# 융합형 소제목(넘버링+매출키워드로 시작해 본문과 한 <P>에 붙은 경우) 앞머리 판정.
_SALES_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?:[\(（]?\s*\d+\s*[\)）.]|\d+\s*[.)]|[가-힣]\s*[.)]|[①-⑳㉠-㉿]|[ⅰ-ⅹ]+\s*[.)]?)?\s*"
    r"(?:매출\s*실적|판매\s*실적|매출\s*현황)")
_SALES_HEAD_WINDOW = 50

# 수주상황표 판별 — 매출 헤딩 창에 딸려 들어오는 order backlog 표(B1, 비범위)를 배제.
_ORDER_KW = ("수주처", "수주일자", "수주총액", "수주잔고", "납기")

# 매출표 단위 추출 — _narrative_unit(혼합단위 거부)이 놓치는 "(단위: 백만원, %)" 처럼 콤마 뒤에
# %가 붙은 흔한 표기를 회수(첫 금액 단위 토큰 채택). B4 공유 함수를 건드리지 않고 매출 전용 보강.
_UNIT_TOKEN_RE = re.compile(r"단위\s*[:：]?\s*[\(（]?\s*(백만원|십억원|억원|천만원|천원|만원|조원|원)")


def _sales_unit(narrative: str, extra_text: str = "") -> Optional[str]:
    """단위 추출 — narrative(엄격) → narrative(관대, 백만원,% 등) → 표 셀 텍스트(단위가 표 헤더
    셀에 '(단위: 백만원)' 로 박힌 흔한 케이스, 실측 NCsoft/여러 게임·제약사) 순으로 시도."""
    u = _narrative_unit(narrative)
    if u:
        return u
    m = _UNIT_TOKEN_RE.search(narrative or "")
    if m:
        return m.group(1)
    m = _UNIT_TOKEN_RE.search(extra_text or "")
    return m.group(1) if m else None


# 채널 정규화 — 원본 라벨을 수출/내수/합계/기타 4종으로 축약(channel VARCHAR(12)).
def _normalize_channel(text: str) -> Optional[str]:
    t = (text or "").strip().replace(" ", "")
    if not t:
        return None
    if "수출" in t or "해외" in t:
        return "수출"
    if "내수" in t or "국내" in t:
        return "내수"
    if t in ("합계", "계", "소계", "총계", "총액") or "합계" in t:
        return "합계"
    return None


_CELL_TAGS = ("TD", "TH", "TE", "TU")


@dataclass
class SalesTable:
    narrative: str
    grid: list[list[str]]


@dataclass
class SalesMetricRow:
    segment: Optional[str]
    item: Optional[str]
    channel: Optional[str]
    period_label: Optional[str]
    period_year: Optional[int]
    value: float
    unit: Optional[str]


def _is_sales_heading(text: str) -> bool:
    """소제목(P/SPAN)이 매출실적/판매실적/매출현황 헤딩인지. biz_section._heading_metrics 와 동일
    전략(짧은 순수 소제목 + 넘버링 융합형 앞머리 판정)."""
    t = text.strip()
    if not t:
        return False
    if len(t) <= _HEADING_MAX_LEN:
        n = t.replace(" ", "")
        return any(k in n for k in _SALES_HEADING_KW)
    if _SALES_HEADING_PREFIX_RE.match(t):
        return True
    return False


def find_sales_subsections(root: etree._Element, max_tables_per_marker: int = 3) -> list[SalesTable]:
    """매출 소제목을 문서 순서로 찾아, 각 소제목 다음(다음 소제목/무관 순번소제목 전까지) TABLE 을
    grid 로 변환. biz_section.find_biz_subsections 의 창 절단·중첩표·1x1 흡수 로직을 그대로 모방."""
    elements = list(root.iter())
    marker_positions: list[int] = [
        i for i, el in enumerate(elements)
        if _tag(el) in ("SPAN", "P") and _is_sales_heading(_text(el))
    ]

    results: list[SalesTable] = []
    for idx, pos in enumerate(marker_positions):
        next_pos = marker_positions[idx + 1] if idx + 1 < len(marker_positions) else len(elements)

        # 우리 키워드가 없는 순번 소제목("나. 판매경로 등" 등)을 만나면 창을 잘라낸다 — 다음 절로
        # 넘어갔다는 뜻(S-Oil 실측: '나. 판매경로' 뒤 수주잔고표 오염 방지).
        for j in range(pos + 1, next_pos):
            t = _text(elements[j])
            if (_tag(elements[j]) in ("SPAN", "P") and len(t) <= _HEADING_MAX_LEN
                    and _NUMBERED_HEADING_RE.match(t) and not _is_sales_heading(t)):
                next_pos = j
                break

        window = elements[pos:next_pos]
        narrative_parts: list[str] = []
        tables: list[etree._Element] = []
        seen_ids = set()
        for el in window:
            if _tag(el) in ("SPAN", "P") and el is not window[0]:
                t = _text(el)
                if t and not _is_sales_heading(t):
                    narrative_parts.append(t)
            if _tag(el) == "TABLE" and id(el) not in seen_ids:
                seen_ids.add(id(el))
                tables.append(el)
                if len(tables) >= max_tables_per_marker:
                    break

        for tbl in tables:
            grid = expand_table_grid(tbl)
            # 단위/캡션 배너 표(데이터 숫자 없는 ≤1행, 예: 별도 셀에 '(단위: 백만원, %)')는
            # narrative 로 흡수 — 다음 데이터 표의 단위 컨텍스트를 보존(실측 NCsoft/게임·제약사).
            flat = [c.strip() for row in grid for c in row if c and c.strip()]
            has_number = any(_is_clean_number(c) for row in grid for c in row)
            if not flat or (len(grid) <= 1 and not has_number):
                narrative_parts.extend(flat)
                continue
            results.append(SalesTable(narrative=" ".join(narrative_parts), grid=grid))

    return results


def map_sales_table(st: SalesTable, fiscal_year: int) -> list[SalesMetricRow]:
    """무손실 grid → 부문×채널×연도 매출행. 값열은 금액(비-비율)만 채택."""
    grid = [list(r) for r in st.grid if r]
    if len(grid) < 2:
        return []
    # T14 가드(docs/PARSING_RULES.md 부록A) — biz_section.map_biz_table/biz_catalog 와 동일하게
    # 재사용. 이 파서만 누락돼 있었음(order_backlog 크래시 조사 중 발견, 지금까지는 크래시 없이
    # 조용히 날조된 큰 값이 들어갈 수 있는 미검증 구멍이었다).
    if is_merged_column_table(grid):
        return []
    ncols = max(len(r) for r in grid)
    grid = [r + [""] * (ncols - len(r)) for r in grid]

    # 1) 헤더/데이터행 분리 — 첫 '깨끗한 수치' 행부터 데이터.
    first_data = next((i for i, r in enumerate(grid) if any(_is_clean_number(c) for c in r)), None)
    if first_data is None or first_data == 0:
        return []
    header_rows, data_rows = grid[:first_data], grid[first_data:]

    # 수주상황표 가드 — 헤더에 수주 관련 열이 있으면 매출표가 아님(B1 order backlog).
    header_text = " ".join(header_rows[r][c] for r in range(len(header_rows)) for c in range(ncols))
    if any(k in header_text.replace(" ", "") for k in _ORDER_KW):
        return []

    # 2) 열 분류 — 데이터셀 과반이 '깨끗한 수치'면 값열, 아니면 차원열.
    dim_cols, val_cols = [], []
    for c in range(ncols):
        col = [data_rows[r][c].strip() for r in range(len(data_rows))]
        nonempty = [v for v in col if v]
        clean = sum(1 for v in nonempty if _is_clean_number(v))
        (val_cols if nonempty and clean >= len(nonempty) / 2 else dim_cols).append(c)
    if not val_cols:
        return []

    # 3) 채널-차원열 검출 — 차원열 값의 과반이 채널 키워드(수출/내수/합계)면 그 열을 채널열로
    #    승격하고 부문/품목에서 제외(생산 파서의 전치형 metric_col 승격과 동일 기법).
    channel_col = None
    for c in dim_cols:
        vals = [data_rows[r][c].strip() for r in range(len(data_rows))]
        nonempty = [v for v in vals if v]
        hits = sum(1 for v in nonempty if _normalize_channel(v))
        if nonempty and hits >= len(nonempty) * 0.6:
            channel_col = c
            break
    label_cols = [c for c in dim_cols if c != channel_col]

    # 4) 기간 해석 — '제N기' 최대값=fiscal_year 상대매핑(map_biz_table 과 동일).
    max_gi = None
    for r in header_rows:
        for c in val_cols:
            gm = _PERIOD_GI_RE.search(r[c])
            if gm:
                max_gi = max(max_gi or 0, int(gm.group(1)))

    def col_period(c: int) -> tuple[Optional[str], Optional[int]]:
        label = year = None
        for r in header_rows:
            cell = r[c]
            gm = _PERIOD_GI_RE.search(cell)
            ym = _PERIOD_YEAR_RE.search(cell)
            if gm and label is None:
                label = f"제{gm.group(1)}기"
                if ym:
                    year = int(ym.group(0))
                elif max_gi is not None:
                    year = fiscal_year - (max_gi - int(gm.group(1)))
            elif ym and year is None:
                year = int(ym.group(0))
                if label is None:
                    label = f"{ym.group(0)}년"
        return label, year

    def col_channel_from_header(c: int) -> Optional[str]:
        head = " ".join(header_rows[r][c] for r in range(len(header_rows)))
        return _normalize_channel(head)

    # 재무요약표 가드 — 데이터행 라벨에 순이익/총자산/부채 등이 하나라도 있으면 부문별 재무표.
    for r in range(len(data_rows)):
        row_label_text = " ".join(data_rows[r][c] for c in label_cols)
        if any(k in row_label_text for k in _FINANCIAL_STMT_KW):
            return []

    # 단위는 narrative → 표 헤더 셀('(단위: 백만원)' 이 첫 행에 박히는 경우) 순으로(header_text 재사용).
    nar_unit = _sales_unit(st.narrative, header_text)
    rows: list[SalesMetricRow] = []
    for drow in data_rows:
        labels: list[str] = []
        for c in label_cols:
            v = drow[c].strip()
            if v and (not labels or labels[-1] != v):
                labels.append(v)
        segment = labels[0] if labels else None
        # 가장 구체적인 품목축(마지막 라벨)을 item 으로 — 부문/매출유형/품목 3차원일 때 품목 보존.
        item = labels[-1] if len(labels) > 1 else None
        if item == segment:
            item = None

        row_channel = None
        if channel_col is not None:
            row_channel = _normalize_channel(drow[channel_col].strip())

        for c in val_cols:
            val, is_ratio, inline_unit = _parse_value(drow[c])
            if val is None:
                continue
            # 매출값은 금액만 — 비율(%) 열(지역 점유율 등)은 제외.
            if is_ratio:
                continue
            plabel, pyear = col_period(c)
            channel = row_channel or col_channel_from_header(c) or "합계"
            # 인라인 단위는 실제 단위 토큰(원/월/개 등 문자 포함)만 채택 — 음수 괄호 ')' 같은
            # 구두점 잔재는 버린다(실측 한온시스템 '(3,831,482)' → inline_unit=')').
            if inline_unit and not any(ch.isalpha() or "가" <= ch <= "힣" for ch in inline_unit):
                inline_unit = None
            unit = inline_unit or nar_unit
            rows.append(SalesMetricRow(
                segment=segment, item=item, channel=channel,
                period_label=plabel, period_year=pyear, value=val, unit=unit,
            ))
    return rows


def _clip(v: Optional[str], n: int) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v[:n] if v else None


def extract_sales_from_root(root: etree._Element, corp_code: str, fiscal_year: int,
                            start_ord: int = 0) -> tuple[list[dict], list[dict]]:
    """이미 로드된 root 에서 매출표를 추출(biz_section.parse_biz_metrics 가 생산표와 이어서 호출).
    table_ord 는 start_ord 부터 이어붙여 biz_section_tables 유니크(rcept,table_ord) 충돌을 피한다.
    반환=(section_rows, metric_rows). metric='sales', channel 세팅."""
    tables = find_sales_subsections(root)
    section_rows: list[dict] = []
    metric_rows: list[dict] = []
    for i, st in enumerate(tables):
        ord_ = start_ord + i
        mrows = map_sales_table(st, fiscal_year)
        section_rows.append({
            "corp_code": corp_code, "fiscal_year": fiscal_year, "table_ord": ord_,
            "metric": "sales", "narrative": st.narrative, "grid": st.grid,
            "n_metric_rows": len(mrows),
        })
        for m in mrows:
            metric_rows.append({
                "corp_code": corp_code, "fiscal_year": fiscal_year, "table_ord": ord_,
                "metric": "sales", "channel": _clip(m.channel, 12),
                "segment": _clip(m.segment, 120), "item": _clip(m.item, 150),
                "period_label": _clip(m.period_label, 60), "period_year": m.period_year,
                "value": m.value, "unit": _clip(m.unit, 30), "is_ratio": False,
            })
    return section_rows, metric_rows


def parse_sales_metrics(file_path: Path, corp_code: str, fiscal_year: int) -> tuple[list[dict], list[dict]]:
    """파일 하나 → (section_rows, metric_rows). 단독 사용/테스트용(파이프라인은 parse_biz_metrics 경유)."""
    root = _load_root(file_path)
    if root is None:
        return [], []
    return extract_sales_from_root(root, corp_code, fiscal_year, start_ord=0)
