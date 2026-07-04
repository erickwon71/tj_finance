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
