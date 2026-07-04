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


def _load_root(file_path: Path) -> Optional[etree._Element]:
    """XML 루트 로드. 구형 DART 보고서(~2010년대)는 UTF-8 로 선언됐지만 실제 EUC-KR 인 경우가
    많아 인코딩 자동감지 폴백(_detect_xml_encoding 재사용) + 대용량 사업보고서용 huge_tree."""
    from parser.xml.dart_xml_parser import _detect_xml_encoding

    with open(file_path, "rb") as f:
        raw = f.read()
    parser = etree.XMLParser(recover=True, huge_tree=True)
    if _detect_xml_encoding(raw) != "utf-8":
        # EUC-KR → UTF-8 재인코딩 후 선언 교체(text.py/shares.py 폴백과 동일 전략)
        raw = re.sub(rb'encoding\s*=\s*"[^"]*"', b'encoding="utf-8"',
                     raw.decode("euc-kr", "replace").encode("utf-8"), count=1)
    try:
        return etree.fromstring(raw, parser)
    except Exception:
        try:
            return etree.fromstring(
                raw, etree.XMLParser(recover=True, huge_tree=True, encoding="utf-8"))
        except Exception:
            return None


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
_HEAD_WINDOW = 50       # 본문 융합형 소제목에서 앞머리 관찰 폭
# 넘버링 접두((2)·2)·나.·2.·①·ⅰ 등) 뒤 생산 키워드로 '시작'하는 문단 = 본문에 소제목이 붙은 경우.
# 실측(2026-07-04): 흥국 "(2) 생산능력, 생산실적, 가동률연결기업의…", 에이텍 "2) 생산실적 및 가동률당기말…"
# 처럼 소제목과 본문이 한 <P>에 융합돼 길이 40자 필터에 걸리던 케이스를 회수한다.
_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?:[\(（]?\s*\d+\s*[\)）.]|\d+\s*[.)]|[가-힣]\s*[.)]|[①-⑳㉠-㉿]|[ⅰ-ⅹ]+\s*[.)]?)?\s*"
    r"(?:생산\s*능력|생산\s*실적|가동\s*[률율])")


def _heading_metrics(text: str) -> list[str]:
    """소제목 텍스트에서 매칭되는 지표 키(들)를 반환. 헤딩 아니면 빈 리스트.
    실측(2026-07-04) 발견: 회사마다 표기가 전혀 다름 —
      삼성전자: SPAN "(생산능력)"/"(생산실적)"/"(가동률)" 개별 소제목.
      S-Oil:    P "다. 생산능력" / "라. 생산실적 및 가동률"(두 지표 한 절에 결합).
      흥국/에이텍: 소제목이 본문과 한 <P>에 융합("(2) 생산능력, 생산실적, 가동률…") → 앞머리 판정.
    (a) 짧은 순수 소제목: 길이≤40 + 키워드 포함. (b) 융합형: 넘버링+생산키워드로 시작하면 앞머리
    _HEAD_WINDOW 안의 키워드를 지표로 채택(뒤 표는 B4b 생산열/깨끗수치 필터가 보호)."""
    t = text.strip().replace("가동율", "가동률")   # 율/률 표기 변이 정규화(실측: 아세아텍 '가동율')
    if not t:
        return []
    if len(t) <= _HEADING_MAX_LEN:
        return [key for key, kw in _MARKERS.items() if kw in t]
    if _HEADING_PREFIX_RE.match(t):
        head = t[:_HEAD_WINDOW]
        return [key for key, kw in _MARKERS.items() if kw in head]
    return []


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
    if root is None:
        return []
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
    ("utilization", ("가동률", "가동율")),
    ("output",      ("생산실적", "실제 생산", "실제생산", "생산량")),
    ("capacity",    ("생산능력", "표준생산능력", "생산 능력")),
]
_UNIT_HEADER_KW = ("단위",)
# 값열이 '생산 데이터 열'인지 판정하는 도메인 키워드 — 기간(제N기/연도)도 없고 이 키워드도
# 없는 값열은 생산표가 아니라 유형자산 장부금액·공장 소재지/면적 등(PP&E/facility) 표라
# 판단해 버린다. 실측(2026-07-04): 01435489 감가상각표·00120076 면적/가액표 오포착 방지.
_PRODUCTION_COL_KW = ("생산", "가동", "능력", "설비")
# 매출(판매)표 판별 키워드 — 융합형 소제목 탐지가 생산문단 뒤의 매출실적표(제N기 기간열·
# 백만원)를 잘못 잡는 것을 차단. 부문/품목 라벨의 과반이 이 단어를 담으면 매출표로 보고 버린다.
# ('수출액/내수액'은 '수출ATM/내수ATM' 같은 정상 생산품목과 구별하려 '액'까지 요구).
_SALES_KW = ("매출", "판매", "수출액", "내수액")
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


def _is_clean_number(s: str) -> bool:
    """'깨끗한 수치 셀'(값열 판정용) — 선두 숫자 + 짧은 후행단위만. 계산식·서술형(÷×=,
    '2,350시간 ÷2,760시간×100=85.1%' 같은 계산근거 컬럼)은 값열이 아니라 배제한다."""
    t = s.strip()
    if not t or not _looks_numeric(t):
        return False
    if any(ch in t for ch in ("÷", "×", "=", "/")):
        return False
    tail = t[_NUM_LEAD_RE.match(t).end():].strip().lstrip("%").strip()
    return len(tail) <= 6


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
    if not any(ch.isdigit() for ch in raw):
        # "," 단독처럼 [\d,]+ 가 콤마만 매치한 빈 셀(실측: 00129280 2005 구형 표) — 숫자 아님.
        return None, is_ratio, None
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

    # 1) 헤더행/데이터행 분리 — '깨끗한 수치' 셀이 처음 나오는 행부터 데이터.
    #    _looks_numeric(선두숫자만) 은 헤더의 날짜셀 "2025.06.30(제47기)" 도 수치로 오인해
    #    header_rows 를 비워버림 → _is_clean_number(짧은 후행단위만 허용) 로 판정.
    first_data = next((i for i, r in enumerate(grid) if any(_is_clean_number(c) for c in r)), None)
    if first_data is None or first_data == 0:
        return []
    header_rows, data_rows = grid[:first_data], grid[first_data:]

    # 2) 열 분류 — 데이터셀의 과반이 '깨끗한 수치'면 값열, 아니면 차원열(계산근거·서술 컬럼 배제).
    dim_cols, val_cols = [], []
    for c in range(ncols):
        col = [data_rows[r][c].strip() for r in range(len(data_rows))]
        nonempty = [v for v in col if v]
        clean = sum(1 for v in nonempty if _is_clean_number(v))
        (val_cols if nonempty and clean >= len(nonempty) / 2 else dim_cols).append(c)
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

    # 전치형 레이아웃 — 지표명(생산능력/생산실적/가동률)이 열 헤더가 아니라 '구분' 차원열의
    # 값으로 들어간 경우(아세아텍류). 값의 과반이 지표명인 차원열을 지표열로 승격하고, 각 행의
    # 지표를 그 값에서 얻는다(그 열은 부문/품목에서 제외).
    metric_col = None
    for c in label_cols:
        vals = [data_rows[r][c].strip() for r in range(len(data_rows))]
        nonempty = [v for v in vals if v]
        hits = sum(1 for v in nonempty if _heading_metrics(v))
        if nonempty and hits >= len(nonempty) * 0.6:
            metric_col = c
            break
    if metric_col is not None:
        label_cols = [c for c in label_cols if c != metric_col]

    # 3) 값열 유효성 필터 — 기간(제N기/연도)이 있거나 생산 도메인 키워드(생산/가동/능력/설비)를
    #    가진 열만 '생산 데이터 열'로 채택. 둘 다 없는 열(장부금액·소재지·면적 등)은 버려
    #    유형자산·설비현황 표 오포착을 차단. 채택 열이 하나도 없으면 생산표가 아님(빈 반환).
    def _has_period(c: int) -> bool:
        return any(_PERIOD_GI_RE.search(header_rows[r][c]) or _PERIOD_YEAR_RE.search(header_rows[r][c])
                   for r in range(len(header_rows)))

    def _is_production_col(c: int) -> bool:
        if _has_period(c):
            return True
        head = " ".join(header_rows[r][c] for r in range(len(header_rows)))
        return any(k in head for k in _PRODUCTION_COL_KW)

    val_cols = [c for c in val_cols if _is_production_col(c)]
    if not val_cols:
        return []

    # 현재 '제N기' 최대값 = fiscal_year 로 상대매핑.
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
            # 기간 미검출(보조표) → 컬럼헤더 텍스트를 라벨로 보존하되 서술형(단위·산출기준·주소)은
            # 배제. 짧고 의미있는 세부지표명(설비능력수량/가동가능일수/표준생산능력)만 남긴다.
            parts = []
            for r in range(len(header_rows)):
                p = header_rows[r][c].strip().replace("\n", " ")
                if p and len(p) <= 20 and not any(k in p for k in ("단위", "기준", "소재지", "：", ":")):
                    parts.append(p)
            label = " ".join(dict.fromkeys(parts))[:60] or None
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

    def col_sublabel(c: int) -> Optional[str]:
        """값열 헤더의 세부축(수량/금액/대 등) — 기간·지표키워드 토큰은 제외. 전치형에서 한 기간에
        수량·금액 두 열이 오는 경우 단위로 구분(그냥 두면 같은 키로 충돌)."""
        for r in range(len(header_rows)):
            t = header_rows[r][c].strip()
            if (t and len(t) <= 6 and not _PERIOD_GI_RE.search(t) and not _PERIOD_YEAR_RE.search(t)
                    and not any(k in t for k in _PRODUCTION_COL_KW)):
                return t
        return None

    # 매출표 가드 — 부문·품목 라벨의 과반이 매출/판매 키워드면 매출실적표로 보고 버린다
    # (융합 소제목 탐지가 생산문단 뒤 매출표를 잘못 잡는 경우 차단).
    sales_rows = sum(
        1 for r in range(len(data_rows))
        if any(k in " ".join(data_rows[r][c] for c in label_cols) for k in _SALES_KW))
    if data_rows and sales_rows >= len(data_rows) / 2:
        return []

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
        # 전치형: 이 행의 지표는 구분열 값에서(생산능력/생산실적/가동률).
        row_metric = None
        if metric_col is not None:
            mh = _heading_metrics(drow[metric_col].strip())
            row_metric = mh[0] if mh else None
        for c in val_cols:
            val, is_ratio, inline_unit = _parse_value(drow[c])
            if val is None:
                continue
            plabel, pyear = col_period(c)
            if metric_col is not None:
                metric = row_metric or col_metric(c, is_ratio)
                if metric == "utilization":   # 전치형 가동률 행은 %없이도 비율(예: 71.56)
                    is_ratio = True
            else:
                metric = col_metric(c, is_ratio)
            # 비율 값의 단위는 항상 %(부문 단위열이 천배럴이어도 가동률 셀은 %).
            unit = "%" if is_ratio else (row_unit or inline_unit or col_sublabel(c) or nar_unit)
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
    if root is None:
        return [], []
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
