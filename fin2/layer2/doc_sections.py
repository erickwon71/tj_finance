"""Layer2 writer for periodic-report non-financial section tables (→ `doc_section_tables`).

API→문서 전환 Phase 0 (docs/plans/api_to_document_migration_plan_2026-10-05.md §2.1).
배당·주주·임원·직원·임원보수·타법인출자·자기주식 등 정기보고서의 비재무 섹션 표를
**판단 없이** 원문 그대로(ROWSPAN/COLSPAN 전개 격자) 보존한다. 해석(어느 행이 DPS 인가 등)은
계층3 도메인 매퍼(`fin2/layer3/doc_<domain>.py`)가 이 테이블만 읽고 한다(R1).

표 식별 — 두 경로:
  1. **서식 코드**: DART 는 표준 서식 표를 `<TABLE-GROUP ACLASS="DIVIDEND">` 로 감싼다. 표제
     문자열은 시대마다 흔들리지만(배당에관한사항 / 배당에관한사항등 / 가.최근5사업연도의…)
     서식 코드는 안정적이다. 카탈로그(docs/qa/doc_section_catalog_2026-10-05.md): 2015+ 대상 코드
     출현 99~100%, 2010-14 대부분, 2009 이전 일부. `TARGET_ACLASS` 의 그룹 안 표를 전부 담는다
     (첫 표가 기준일·단위 캡션인 경우가 많아 group_ord 로 순서를 남긴다).
  2. **표제 폴백**: 서식 코드 없는 표가 대상 섹션(`TARGET_KEYWORDS`) 안에 있으면 aclass=NULL 로
     담는다(2009 이전 '다.자기주식의취득및처분'·'다.주주분포' 등). 섹션 귀속은
     `section_detector.assign_tables_to_dart_sections` 와 같은 **문서 순서** 규칙.

`heading_raw` 는 표 직전의 마지막 문단 텍스트(소제목 후보)다 — 같은 섹션에 여러 종류 표가
섞인 구형 서식에서 매퍼가 표 종류를 가르는 근거로 쓴다(판정은 계층3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from fin2.extract.biz_section import expand_table_grid
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import normalize_dart_section_title

# Standard-form codes whose tables feed the API→document migration (catalog 2026-10-05).
TARGET_ACLASS = frozenset({
    # 주식의 총수 / 자기주식
    "TOT_STK", "STOCK", "OWN_SHR",
    # 배당
    "DIVIDEND",
    # 주주
    "BSH_SPCL", "BSH_CHA", "SH5_PRE_STT", "SH4_PRE_STT",
    # 임원·직원
    "SH5_DRCT_STT", "PSN_MBER", "EMPLOYEE", "UNRESISTER",
    # 임원 보수
    "SUB_CMP", "SUB_CMPT", "SUB_CMPP", "SUB_CMPK", "SUB_CMPK_HIGH", "SUB_CMPI",
    # 타법인출자
    "INV_PRT",
})

# Title fallback: tables outside any TABLE-GROUP inside these sections are kept too.
TARGET_KEYWORDS = ("배당", "주주", "임원", "직원", "타법인출자", "자기주식", "주식의총수",
                   "발행한주식")
# '주주' also matches these sections, which no migration target reads (and 주주총회 tables
# are the largest payload: ~11 KB/filing measured on 삼양식품 2024).
EXCLUDED_KEYWORDS = ("주주총회", "대주주등과의거래", "이해관계자와의거래", "의결권행사")

_HEADING_MAX = 200
_WS = re.compile(r"\s+")


@dataclass
class DocSectionTable:
    table_ord: int
    aclass: Optional[str]
    group_ord: int
    section_key: Optional[str]
    section_title_raw: Optional[str]
    heading_raw: Optional[str]
    grid: list[list[Optional[str]]] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.grid)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.grid), default=0)


def _tag(el) -> str:
    return el.tag.upper() if isinstance(el.tag, str) else ""


def _text(el) -> str:
    return _WS.sub(" ", "".join(el.itertext())).strip()


def _is_target_section(section_key: Optional[str]) -> bool:
    return (bool(section_key) and any(k in section_key for k in TARGET_KEYWORDS)
            and not any(k in section_key for k in EXCLUDED_KEYWORDS))


def extract_doc_section_tables(root) -> list[DocSectionTable]:
    """Walk the document in reading order and return the target tables (no judgment)."""
    out: list[DocSectionTable] = []
    section_key = section_raw = heading = None
    claimed: set[int] = set()      # TABLE elements already emitted via their TABLE-GROUP
    for el in root.iter():
        tag = _tag(el)
        if tag.startswith("SECTION"):
            te = el.find("TITLE")
            if te is not None:
                section_raw = _text(te)
                section_key = normalize_dart_section_title(section_raw) or None
                heading = None
        elif tag == "P":
            t = _text(el)
            if t:
                heading = t[:_HEADING_MAX]
        elif tag == "TABLE-GROUP":
            ac = el.get("ACLASS")
            if ac not in TARGET_ACLASS:
                continue
            tables = [t for t in el.iter() if _tag(t) == "TABLE"]
            for gi, t in enumerate(tables):
                claimed.add(id(t))
                out.append(DocSectionTable(len(out), ac, gi, section_key, section_raw,
                                           heading, expand_table_grid(t)))
        elif tag == "TABLE" and id(el) not in claimed and _is_target_section(section_key):
            if _inside_table_group(el):
                continue  # a non-target TABLE-GROUP's table (e.g. VOT_STK) — not ours
            if _nested_in_table(el):
                continue  # layout tables nested in a cell are part of the outer grid
            out.append(DocSectionTable(len(out), None, 0, section_key, section_raw,
                                       heading, expand_table_grid(el)))
    return out


def _inside_table_group(el) -> bool:
    anc = el.getparent()
    while anc is not None:
        if _tag(anc) == "TABLE-GROUP":
            return True
        anc = anc.getparent()
    return False


def _nested_in_table(el) -> bool:
    anc = el.getparent()
    while anc is not None:
        if _tag(anc) == "TABLE":
            return True
        anc = anc.getparent()
    return False


def extract_from_file(path: str) -> list[DocSectionTable]:
    return extract_doc_section_tables(_parse_xml_file(path))


def store_doc_section_tables(session, rcept_no: str, corp_code: str, fiscal_year: int,
                             fiscal_period: str, tables: list[DocSectionTable]) -> int:
    """rcept 단위 delete-then-insert. 이 테이블은 이 writer 만 쓰므로 범위 = rcept 전체."""
    from sqlalchemy import delete, insert
    from collector.models import DocSectionTableRow

    session.execute(delete(DocSectionTableRow).where(DocSectionTableRow.rcept_no == rcept_no))
    if not tables:
        return 0
    now = datetime.utcnow()
    session.execute(insert(DocSectionTableRow).values([{
        "rcept_no": rcept_no, "corp_code": corp_code,
        "report_fiscal_year": fiscal_year, "report_fiscal_period": fiscal_period,
        "table_ord": t.table_ord, "aclass": t.aclass, "group_ord": t.group_ord,
        "section_key": t.section_key, "section_title_raw": t.section_title_raw,
        "heading_raw": t.heading_raw, "grid": t.grid,
        "n_rows": t.n_rows, "n_cols": t.n_cols, "parsed_at": now,
    } for t in tables]))
    return len(tables)
