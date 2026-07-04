"""B4 프로토타입 · 사업의 내용 — 생산능력/생산실적/가동률 본문 테이블 파서.

DART 정기보고서 "II. 사업의 내용" 절 안에서 생산능력/생산실적/가동률을 다루는 소제목을
찾아, 그 다음에 나오는 표를 (원본 그대로의) 2D 그리드로 변환한다.

설계 근거(2026-07-04 실측, 2개사 비교 — 삼성전자 vs S-Oil):
- 이 절은 XBRL 태깅 대상이 아니라 순수 HTML형 마크업(TABLE/TR/TD, DART 자체 DTD 속성
  ACLASS/AFIXTABLE 등)이라 fin2/extract/xbrl.py 의 ACODE 기반 추출과는 무관하다.
- 헤더가 ROWSPAN/COLSPAN 으로 병합돼 있다(부문·품목은 세로 병합, 기간은 가로 병합 후
  하위행에 세부 열이 다시 나뉨) → 표준 HTML 그리드 확장 알고리즘 필요
  (parser/xml/table_extractor.py 의 계정과목 전용 추출기는 3-열 금액 표 전제라 이 표
  형태엔 안 맞음 — 여기선 범용 그리드 추출기를 새로 둠).
- **회사마다 소제목 형태가 전혀 다름**(예상보다 훨씬 이질적 — 산업별 표본 확대 전 이미
  확인): 삼성전자는 SPAN "(생산능력)"/"(생산실적)"/"(가동률)" 개별 소제목 3개로 분리.
  S-Oil 은 P 순번소제목 "다. 생산능력" / "라. 생산실적 및 가동률"(두 지표를 한 절에
  결합, 표 하나에 생산실적+가동률 열이 같이 있음) → 매처는 길이+키워드 느슨 매칭으로
  양쪽 다 잡고, 결합된 경우 metric="output+utilization" 처럼 표기해 무손실 보존한다.
  다음 절 경계도 우리 키워드가 없는 일반 순번소제목("마. 생산설비의 현황")으로도 인식
  (안 하면 무관한 표까지 딸려 들어옴 — S-Oil 실측으로 확인 후 추가).
- 이 모듈은 "표를 그대로 grid 로 복원"까지만 하고, 캐노니컬 지표명·컬럼 매핑은 하지
  않는다(무손실 우선, fin2 Track B 텍스트 추출기와 동일 철학). B4b 단계에서 더 많은
  산업 표본을 모아 컬럼 해석 규칙을 반복 보강한다.

usage(프로토타입 검증):
    from fin2.extract.biz_section import parse_biz_tables
    rows = parse_biz_tables(Path("raw_report/.../20250311001085.xml"), "00126380", 2024)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lxml import etree

_MARKERS = {
    "capacity": "생산능력",
    "output": "생산실적",
    "utilization": "가동률",
}
_CELL_TAGS = ("TD", "TH", "TE", "TU")

# DART 사업보고서의 "가./나./다..." 순번 소제목 패턴 — 우리 키워드가 없어도 "다음 절로
# 넘어갔다"는 경계 신호로 쓴다(S-Oil 실측: "마. 생산설비의 현황"이 뒤에 바로 이어져
# 무관한 표(토지·공장 장부가액)까지 딸려 들어오는 걸 방지).
_NUMBERED_HEADING_RE = re.compile(r"^[가-힣]\s*\.\s*\S")


@dataclass
class BizTable:
    metric: str                 # capacity/output/utilization
    narrative: str               # 서브섹션 헤더 다음 문단(있으면) — 단위/산출기준 설명
    grid: list[list[str]]        # rowspan/colspan 확장된 2D 텍스트 그리드(헤더 포함)


def _load_root(file_path: Path) -> etree._Element:
    parser = etree.XMLParser(recover=True, huge_tree=True)
    tree = etree.parse(str(file_path), parser)
    return tree.getroot()


def _tag(el) -> str:
    return el.tag.upper() if isinstance(el.tag, str) else ""


def _text(el) -> str:
    return "".join(el.itertext()).strip()


def expand_table_grid(table_elem: etree._Element) -> list[list[str]]:
    """
    TABLE 요소를 ROWSPAN/COLSPAN 반영한 완전한 2D 텍스트 그리드로 변환(표준 HTML 확장
    알고리즘). 병합 셀은 값이 각 점유 칸에 복제된다(관용적 표현 — 합계 이중집계 방지는
    소비자 책임, 원본 형태를 그대로 보존하는 게 이 레이어의 목적).
    """
    trs = table_elem.findall(".//TR")
    grid: list[list[Optional[str]]] = []
    # row_idx -> col_idx -> value, 미리 계산한 rowspan 점유를 기록해두는 용도
    pending: dict[int, dict[int, str]] = {}

    for r, tr in enumerate(trs):
        if r not in pending:
            pending[r] = {}
        row: list[Optional[str]] = []
        col = 0

        def _next_free_col(c: int) -> int:
            while c in pending[r]:
                row_extend(c)
                c += 1
            return c

        def row_extend(upto: int) -> None:
            while len(row) <= upto:
                row.append(None)

        # 이 행에 이전 rowspan 으로 예약된 값부터 채움
        for c, v in sorted(pending.get(r, {}).items()):
            row_extend(c)
            row[c] = v

        for child in tr:
            if _tag(child) not in _CELL_TAGS:
                continue
            col = _next_free_col(col)
            row_extend(col)
            text = _text(child)
            colspan = int(child.get("COLSPAN") or child.get("colspan") or 1)
            rowspan = int(child.get("ROWSPAN") or child.get("rowspan") or 1)
            for dc in range(colspan):
                row_extend(col + dc)
                row[col + dc] = text
                if rowspan > 1:
                    for dr in range(1, rowspan):
                        pending.setdefault(r + dr, {})[col + dc] = text
            col += colspan

        grid.append(["" if v is None else v for v in row])

    return grid


_HEADING_MAX_LEN = 40   # 소제목 후보 최대 길이(내러티브 본문과 구별 — 실측: 삼성 15자, S-Oil 12자)


def _heading_metrics(text: str) -> list[str]:
    """짧은 소제목 텍스트에서 매칭되는 지표 키(들)를 반환. 헤딩 아니면 빈 리스트.
    실측(2026-07-04) 발견: 회사마다 표기가 전혀 다름 —
      삼성전자: SPAN "(생산능력)"/"(생산실적)"/"(가동률)" 개별 소제목.
      S-Oil:    P "다. 생산능력" / "라. 생산실적 및 가동률"(두 지표 한 절에 결합).
    → 길이 제한 + 키워드 포함으로 느슨하게 판정(내러티브 문단은 훨씬 길어 자연히 배제)."""
    t = text.strip()
    if not t or len(t) > _HEADING_MAX_LEN:
        return []
    hits = [key for key, kw in _MARKERS.items() if kw in t]
    return hits


def find_biz_subsections(root: etree._Element, max_tables_per_marker: int = 3) -> list[BizTable]:
    """
    생산능력/생산실적/가동률 소제목(P 또는 SPAN, 회사마다 형태가 다름 — _heading_metrics 참조)을
    문서 순서로 찾아, 각 소제목 다음(다음 소제목 전까지, 최대 max_tables_per_marker 개) TABLE 을
    grid 로 변환해 반환. 한 소제목이 여러 지표를 겸하면(S-Oil "생산실적 및 가동률") metric 을
    "output+utilization" 처럼 결합 표기해 무손실 보존한다.
    """
    elements = list(root.iter())
    marker_positions: list[tuple[int, str]] = []
    for i, el in enumerate(elements):
        if _tag(el) not in ("SPAN", "P"):
            continue
        hits = _heading_metrics(_text(el))
        if hits:
            marker_positions.append((i, "+".join(hits)))

    results: list[BizTable] = []
    for idx, (pos, metric) in enumerate(marker_positions):
        next_pos = marker_positions[idx + 1][0] if idx + 1 < len(marker_positions) else len(elements)

        # 우리 키워드가 없는 순번 소제목("마. 생산설비의 현황" 등)을 만나면 거기서 창을
        # 잘라낸다 — 다음 절로 넘어갔다는 뜻이라, 그 이후 표는 무관할 가능성이 높음(S-Oil 실측).
        for j in range(pos + 1, next_pos):
            t = _text(elements[j])
            if (_tag(elements[j]) in ("SPAN", "P") and len(t) <= _HEADING_MAX_LEN
                    and _NUMBERED_HEADING_RE.match(t) and not _heading_metrics(t)):
                next_pos = j
                break

        window = elements[pos:next_pos]

        narrative_parts = []
        tables: list[etree._Element] = []
        seen_table_ids = set()
        for el in window:
            if _tag(el) in ("SPAN", "P") and el is not window[0]:
                t = _text(el)
                if t and not _heading_metrics(t):
                    narrative_parts.append(t)
            if _tag(el) == "TABLE" and id(el) not in seen_table_ids:
                seen_table_ids.add(id(el))
                tables.append(el)
                if len(tables) >= max_tables_per_marker:
                    break

        # 첫 표가 "(단위: ...)" 만 있는 1x1 표인 경우가 흔함(삼성전자 실측) — narrative 에 흡수.
        data_tables = []
        for t in tables:
            grid = expand_table_grid(t)
            if len(grid) <= 1 and len(grid[0]) <= 1 if grid else True:
                if grid and grid[0]:
                    narrative_parts.append(grid[0][0])
                continue
            data_tables.append(grid)

        for grid in data_tables:
            results.append(BizTable(metric=metric, narrative=" ".join(narrative_parts), grid=grid))

    return results


def parse_biz_tables(file_path: Path, corp_code: str, fiscal_year: int) -> list[dict]:
    """
    최상위 진입점(프로토타입) — 파일 하나에서 생산능력/생산실적/가동률 표를 찾아
    (corp_code, fiscal_year, metric, narrative, grid) 딕셔너리 리스트로 반환.
    grid 는 원본 그대로(정규화 없음) — 캐노니컬 스키마 매핑은 B4b 이후.
    """
    root = _load_root(file_path)
    tables = find_biz_subsections(root)
    return [
        {
            "corp_code": corp_code,
            "fiscal_year": fiscal_year,
            "metric": t.metric,
            "narrative": t.narrative,
            "grid": t.grid,
        }
        for t in tables
    ]


# ─────────────────────────────────────────────────────────────────────────────
# B4a · 캐노니컬 매핑 — 무손실 grid 를 long-format 지표행으로 해석
# ─────────────────────────────────────────────────────────────────────────────
# 실측 3사(삼성전자·S-Oil·HD현대중공업)로 확인한 표 형태:
#   - 좌측 차원열(부문/품목/구분/단위) + 우측 값열(기간 또는 지표 세부)
#   - 헤더가 1~2행: 상단=기간(제N기/YYYY년), 하단=세부지표(생산능력/생산실적/가동률)
#   - 값열이 기간별(삼성 capacity/output)일 수도, 지표세부별(삼성 utilization: 능력/실적/가동률
#     한 표에 병렬)일 수도, 둘의 교차(S-Oil output+utilization)일 수도 있음.
#   - 기간 미검출 보조표(S-Oil 표준생산능력/가동가능일수)는 period_year=NULL + 컬럼헤더를
#     period_label 로 보존해 무손실.

_METRIC_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("utilization", ("가동률",)),
    ("output",      ("생산실적", "실제 생산", "실제생산", "생산량")),
    ("capacity",    ("생산능력", "표준생산능력", "생산 능력")),
]
_UNIT_HEADER_KW = ("단위",)
_PERIOD_GI_RE = re.compile(r"제\s*(\d+)\s*기")
_PERIOD_YEAR_RE = re.compile(r"(19|20)\d{2}")
_NUM_LEAD_RE = re.compile(r"^\(?\s*-?[\d,]+(?:\.\d+)?")


@dataclass
class BizMetricRow:
    metric: str
    segment: Optional[str]
    item: Optional[str]
    period_label: Optional[str]
    period_year: Optional[int]
    value: float
    unit: Optional[str]
    is_ratio: bool


def _looks_numeric(s: str) -> bool:
    """셀이 수치값(콤마·소수·%·괄호음수·후행단위 허용)인지."""
    t = s.strip()
    if not t:
        return False
    return bool(_NUM_LEAD_RE.match(t)) and any(c.isdigit() for c in t)


def _parse_value(s: str) -> tuple[Optional[float], bool, Optional[str]]:
    """셀 → (숫자값, 비율여부, 인라인단위). 파싱 실패 시 (None, ..)."""
    t = s.strip()
    if not t or t in ("-", "－", "—", "N/A", "해당없음"):
        return None, False, None
    is_ratio = "%" in t
    m = _NUM_LEAD_RE.match(t)
    if not m:
        return None, is_ratio, None
    raw = m.group(0)
    neg = raw.lstrip().startswith("(") and t.rstrip().endswith(")")
    num = float(raw.replace("(", "").replace(",", "").strip())
    if neg:
        num = -num
    # 후행 인라인 단위(예: "362.2일", "8,692시간") — 남은 텍스트에 숫자 없고 %가 아니면 단위로.
    tail = t[m.end():].strip().lstrip("%").strip()
    inline_unit = tail if (tail and not any(c.isdigit() for c in tail) and len(tail) <= 8) else None
    return num, is_ratio, inline_unit


def _narrative_unit(narrative: str) -> Optional[str]:
    """'(단위 : 천배럴)' 처럼 단일 단위만 있으면 추출(혼합이면 None — 행별 단위열/인라인 우선)."""
    m = re.search(r"단위\s*[:：]\s*([^)\]]+)", narrative or "")
    if not m:
        return None
    u = m.group(1).strip()
    # 혼합 단위(콤마/및 로 나열)면 신뢰 불가 → None.
    if "," in u or "및" in u or len(u) > 10:
        return None
    return u or None


def map_biz_table(bt: BizTable, fiscal_year: int) -> list[BizMetricRow]:
    """무손실 grid → 구조화된 지표행. 해석 불가 컬럼은 period_label 로 헤더를 보존(무손실)."""
    grid = [list(r) for r in bt.grid if r]
    if len(grid) < 2:
        return []
    ncols = max(len(r) for r in grid)
    grid = [r + [""] * (ncols - len(r)) for r in grid]

    # 1) 헤더행/데이터행 분리 — 값열이 수치로 시작하는 첫 행부터 데이터.
    first_data = next((i for i, r in enumerate(grid) if any(_looks_numeric(c) for c in r)), None)
    if first_data is None or first_data == 0:
        return []
    header_rows, data_rows = grid[:first_data], grid[first_data:]

    # 2) 열 분류 — 데이터행이 하나도 수치가 아니면 차원열, 아니면 값열.
    dim_cols, val_cols = [], []
    for c in range(ncols):
        col = [data_rows[r][c] for r in range(len(data_rows))]
        (val_cols if any(_looks_numeric(v) for v in col) else dim_cols).append(c)
    if not val_cols:
        return []

    # 단위열(헤더에 '단위') 식별 → 라벨열과 분리.
    unit_col = None
    for c in dim_cols:
        head = " ".join(header_rows[r][c] for r in range(len(header_rows)))
        if any(k in head for k in _UNIT_HEADER_KW):
            unit_col = c
            break
    label_cols = [c for c in dim_cols if c != unit_col]

    # 3) 값열별 기간/세부지표 해석. 현재 '제N기' 최대값 = fiscal_year 로 상대매핑.
    max_gi = None
    for r in header_rows:
        for c in val_cols:
            gm = _PERIOD_GI_RE.search(r[c])
            if gm:
                max_gi = max(max_gi or 0, int(gm.group(1)))

    table_metrics = bt.metric.split("+")

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
        if label is None:
            # 기간 미검출(보조표) → 차원헤더가 아닌 컬럼헤더 텍스트를 라벨로 보존.
            parts = [header_rows[r][c].strip() for r in range(len(header_rows))
                     if header_rows[r][c].strip()]
            label = " ".join(dict.fromkeys(parts)) or None
        return label, year

    def col_metric(c: int, is_ratio: bool) -> str:
        head = " ".join(header_rows[r][c] for r in range(len(header_rows)))
        # 1) 명시 키워드(생산능력/생산실적/가동률 등).
        matched = None
        for mk, kws in _METRIC_KEYWORDS:
            if any(k in head for k in kws):
                matched = mk
                break
        # 가동률 라벨인데 값이 비율이 아니면 신뢰하지 않음(설비능력수량 등 오검 방지) → 재분류.
        if matched == "utilization" and not is_ratio:
            matched = None
        # 2) 헤더 힌트 보강(능력→capacity / 실적·생산량·생산→output).
        if matched is None:
            if "능력" in head:
                matched = "capacity"
            elif any(k in head for k in ("실적", "생산량", "생산")):
                matched = "output"
        # 3) 비율 값은 항상 가동률(캐파/실적 컬럼 아래 %가 오면 그게 가동률).
        if is_ratio:
            return "utilization"
        if matched is not None:
            return matched
        # 4) 폴백: 표 metric(결합표는 비-가동률 우선).
        non_util = [m for m in table_metrics if m != "utilization"]
        return non_util[0] if non_util else "output"

    nar_unit = _narrative_unit(bt.narrative)
    rows: list[BizMetricRow] = []
    for drow in data_rows:
        labels: list[str] = []
        for c in label_cols:
            v = drow[c].strip()
            if v and (not labels or labels[-1] != v):
                labels.append(v)
        segment = labels[0] if labels else None
        item = labels[1] if len(labels) > 1 else None
        row_unit = drow[unit_col].strip() if unit_col is not None else None
        for c in val_cols:
            val, is_ratio, inline_unit = _parse_value(drow[c])
            if val is None:
                continue
            plabel, pyear = col_period(c)
            metric = col_metric(c, is_ratio)
            # 비율 값의 단위는 항상 %(부문 단위열이 천배럴이어도 가동률 셀은 %).
            unit = "%" if is_ratio else (row_unit or inline_unit or nar_unit)
            rows.append(BizMetricRow(
                metric=metric, segment=segment, item=item,
                period_label=plabel, period_year=pyear,
                value=val, unit=unit, is_ratio=is_ratio,
            ))
    return rows


def _clip(v: Optional[str], n: int) -> Optional[str]:
    """DB 컬럼 길이 초과 방어(이질적 표에서 라벨이 주소·설명문이 되는 경우 대비 무손실은
    biz_section_tables.grid 가 보장 — 구조화 행은 안전히 잘라 적재 실패를 막는다)."""
    if v is None:
        return None
    v = v.strip()
    return v[:n] if v else None


def parse_biz_metrics(file_path: Path, corp_code: str, fiscal_year: int) -> tuple[list[dict], list[dict]]:
    """
    파일 하나 → (biz_section_tables 행, biz_metrics 행) 튜플. 수집기(collect_biz_metrics.py)와
    파이프라인이 소비. 원본 grid(무손실) + 구조화 지표행을 함께 반환.
    """
    root = _load_root(file_path)
    tables = find_biz_subsections(root)
    section_rows: list[dict] = []
    metric_rows: list[dict] = []
    for ord_, bt in enumerate(tables):
        mrows = map_biz_table(bt, fiscal_year)
        section_rows.append({
            "corp_code": corp_code, "fiscal_year": fiscal_year, "table_ord": ord_,
            "metric": _clip(bt.metric, 40), "narrative": bt.narrative, "grid": bt.grid,
            "n_metric_rows": len(mrows),
        })
        for m in mrows:
            metric_rows.append({
                "corp_code": corp_code, "fiscal_year": fiscal_year, "table_ord": ord_,
                "metric": _clip(m.metric, 20), "segment": _clip(m.segment, 120),
                "item": _clip(m.item, 150), "period_label": _clip(m.period_label, 60),
                "period_year": m.period_year,
                "value": m.value, "unit": _clip(m.unit, 30), "is_ratio": m.is_ratio,
            })
    return section_rows, metric_rows
