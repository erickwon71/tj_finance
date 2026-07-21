"""
계층2 검증 — report_lines(원문 tree) ↔ 보고서 원문 face 표 1:1 대조.

## 무엇을 "원문"으로 보는가
원문 = **제출된 원본 DART 보고서 XML(raw_report/…)의 재무제표 face 표에 실제 표시된 값**.
사람이 보고서를 열어 눈으로 읽는 그 숫자다. (PDF-only 보고서의 원문은 PDF지만 여기선 XML 대상.)

## 왜 독립 리더인가
report_lines 는 `extract_rows`(라벨/금액 분리·컬럼캡·주석참조 스킵)로 만든다. 검증이 같은 경로를
쓰면 같은 버그를 공유해 무의미하다. 그래서 이 모듈은 **표 안의 모든 셀을 평면 스캔**해 콤마 3자리
그룹 금액을 그대로 읽는다(라벨/컬럼 로직 없음 = 독립 경로). "표에 인쇄된 모든 금액"의 다중집합을
report_lines 값(원→표시 역환산)의 다중집합과 대조한다:
  - MISSING : 원문 표엔 있는데 report_lines 에 없음 → **누락**(행/컬럼 드롭·추출 실패).
  - EXTRA   : report_lines 엔 있는데 원문 표에 없음 → **날조/오파싱**(주석참조·오단위 등).
  - 일치율   : match / 원문금액수.

## 범위·경계 (의도된 것)
- **표 선택은 report_lines 와 동일**(`_detect_body_statement_tables`) — 값 전사 충실도를 검증하지,
  섹션 검출을 검증하지 않는다(그건 카나리아·앵커로 별도 확인). 단위 미선언 표는 양쪽 다 스킵(보류)
  하고 held 로 카운트한다.
- **본문 BS/IS/CF 만**(주석 제외 — 슬라이스). 자본변동표(SCE)는 report_lines 미대상.
- **연간(FY) 정합이 가장 깨끗**: 반기/분기는 report_lines 가 누적(YTD) 컬럼만 채택하므로 원문의
  3개월 컬럼이 MISSING 으로 잡힌다(정상 동작). 그래서 기본은 FY 대조, interim 은 참고.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    table_direct_rows, assign_tables_to_dart_sections, SEC_CONSOL_NOTE, SEC_SEP_NOTE,
)
from parser.xml.table_extractor import _get_cells
from fin2.extract.text import _detect_fin_type, _detect_body_statement_tables, declared_unit, _table_has_data_rows
from fin2.audit.face_audit import parse_displayed

# 셀 안의 콤마 3자리 그룹 금액(예 '55,102,004,323', '(1,234)', '△1,234'). 날짜·기수·소액
# 주석번호(콤마 3자리그룹 아님)를 자연 배제 — 원문 face 금액만 골라내는 독립 필터.
_AMOUNT_IN_CELL = re.compile(r"\d{1,3}(?:,\d{3})+")


def _rl_displayed(value_won: int, adecimal: int | None) -> int:
    """report_lines 값(원) → 원문 표시 리터럴. displayed = value_won × 10^adecimal.
    (adecimal = -3(천원)이면 value_won/1000 = 표시값.)"""
    ad = adecimal or 0
    return int(round(value_won * (10 ** ad)))


@dataclass
class FaceAmounts:
    """원문 face 표에서 독립 스캔한 표시금액 다중집합 (본문 BS/IS/CF)."""
    by_stmt: dict[tuple[str, str], Counter] = field(default_factory=dict)  # (stmt,basis)->Counter[displayed]
    all_amounts: Counter = field(default_factory=Counter)                   # 전 (stmt,basis) 합산
    held_tables: int = 0                                                    # 단위 미선언 스킵 표 수
    n_tables: int = 0


def read_face_amounts(file_path: str | Path) -> FaceAmounts:
    """원본 XML 본문 BS/IS/CF 표를 **평면 스캔**해 표시금액 다중집합을 만든다(독립 리더)."""
    out = FaceAmounts()
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return out
    fin_type = _detect_fin_type(root)
    groups = _detect_body_statement_tables(root, fin_type)  # {section_code: [(tbl, unit, kind)]}
    for section_code, tw in groups.items():
        stmt = section_code.split("_")[0]
        basis = "consolidated" if section_code.endswith("_C") else "separate"
        for tbl, unit, _kind in tw:
            out.n_tables += 1
            if unit is None:
                out.held_tables += 1   # report_lines 도 스킵(보류) — 대조 대상 아님
                continue
            c = out.by_stmt.setdefault((stmt, basis), Counter())
            for tr in table_direct_rows(tbl):
                cells = _get_cells(tr)
                for cell in cells:
                    if _AMOUNT_IN_CELL.search(cell):
                        v = parse_displayed(cell)
                        if v is not None:
                            c[v] += 1
                            out.all_amounts[v] += 1
    return out


# 대조 최소 절대값. 이 미만은 **집합 대조에서 제외**한다. 근거(실측 카테고리화):
#  - 0·소액: 독립 리더는 콤마그룹만 읽어 '0'·소액을 안 잡으나 report_lines 는 잡음 → 무해한 비대칭.
#  - 주당손익(EPS)·주당배당 등 주(株)당 값: 재무제표 face 지만 소액·이중(기본/희석)이라 노이즈.
# 재무제표의 **실질 금액**(자산·부채·자본·매출·손익·현금흐름과 그 성분)은 전부 이 임계 이상이다.
_MIN_ABS = 1000


def read_note_amounts(file_path: str | Path) -> Counter:
    """주석 섹션(연결/별도)의 **단위선언+금액행 있는 표**를 평면 스캔한 표시금액 다중집합.
    `_emit_note_lines` 와 동일한 표 선택(선언단위·데이터행)을 미러링 → apples-to-apples."""
    out: Counter = Counter()
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return out
    sec_tables = assign_tables_to_dart_sections(root)
    for sec_kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
        for tbl in sec_tables.get(sec_kind, []):
            if declared_unit(tbl) is None or not _table_has_data_rows(tbl):
                continue
            for tr in table_direct_rows(tbl):
                for cell in _get_cells(tr):
                    if _AMOUNT_IN_CELL.search(cell):
                        v = parse_displayed(cell)
                        if v is not None:
                            out[v] += 1
    return out


def audit_note_lines(rl_rows: list, note_face: Counter, min_abs: int = _MIN_ABS) -> tuple[int, int, set]:
    """report_lines 주석값이 원문 주석표 값의 **부분집합**인지(날조 없음). 주석은 컬럼 위치·8열
    캡 등으로 원문 일부만 담으므로 EXTRA(=DB에만) 만 본다. 반환=(db수, 원문수, extra집합)."""
    face = {v for v in note_face if abs(v) >= min_abs}
    db = {r.value_won for r in rl_rows
          if r.statement == "note" and r.value_won is not None and abs(r.value_won) >= min_abs}
    # 주석 value_won 은 이미 원 정규화 — 원문 표시값과 비교하려면 표시로 역환산해야 하나, 주석
    # 표시단위(천원 등)가 표마다 달라 역환산이 애매하다. adecimal 로 표시 복원해 비교한다.
    db_disp = {_rl_displayed(r.value_won, r.adecimal) for r in rl_rows
               if r.statement == "note" and r.value_won is not None
               and abs(_rl_displayed(r.value_won, r.adecimal)) >= min_abs}
    extra = db_disp - face
    return (len(db_disp), len(face), extra)


@dataclass
class ReportLineAuditResult:
    rcept_no: str
    n_report: int = 0            # 원문 실질 표시금액 수(집합)
    n_db: int = 0               # report_lines 실질 표시금액 수(집합)
    n_match: int = 0            # 교집합
    held_tables: int = 0
    missing: set = field(default_factory=set)   # 원문엔 있는데 DB에 없음(누락 후보)
    extra: set = field(default_factory=set)     # DB엔 있는데 원문에 없음(날조/오파싱 후보)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.extra

    @property
    def match_rate(self) -> float:
        return (self.n_match / self.n_report) if self.n_report else 1.0


def audit_report_lines(rcept_no: str, face: FaceAmounts, rl_rows: list,
                       min_abs: int = _MIN_ABS) -> ReportLineAuditResult:
    """원문 face ↔ report_lines(본문 BS/IS/CF) **실질 표시금액 집합** 대조.

    집합(중복 무시) 비교인 이유: 재무상태표 항등식(자산총계 == 부채및자본총계)으로 같은 값이
    원문에 2회 인쇄되는 등 **다중집합 개수는 무해하게 어긋난다**. 검증 목표는 "원문에 인쇄된
    모든 실질 금액이 report_lines 에 존재하고, 없는 값을 지어내지 않았는가"이므로 집합이 맞다.
      - MISSING(원문에만): report_lines 가 그 금액을 **아예 못 담음** → 행/컬럼 드롭·오파싱.
      - EXTRA(DB에만): report_lines 에만 있는 금액 → 날조·주석참조·오단위(×10ⁿ) 후보.
    부호 포함 비교(부호 오류도 실질값이면 잡힘). |값| < min_abs 는 양쪽 제외(소액·EPS·0 노이즈).
    """
    res = ReportLineAuditResult(rcept_no=rcept_no, held_tables=face.held_tables)

    db = {_rl_displayed(r.value_won, r.adecimal)
          for r in rl_rows
          if r.statement in ("BS", "IS", "CF") and r.value_won is not None}
    rep = set(face.all_amounts)
    db = {v for v in db if abs(v) >= min_abs}
    rep = {v for v in rep if abs(v) >= min_abs}

    res.n_report = len(rep)
    res.n_db = len(db)
    res.missing = rep - db
    res.extra = db - rep
    res.n_match = len(rep & db)
    return res
