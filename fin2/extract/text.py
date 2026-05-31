"""
Track B 텍스트 추출기 (fin2 E-레이어 폴백).

ACONTEXT/ACODE 가 없는 DART 정기보고서(분기/반기 다수, 구형 연간)에서
한국어 계정명+테이블 텍스트로 fact_v2 행을 추출한다.

설계:
  - 기존 leaf 모듈(section_detector/table_extractor/account_mapper/amount_normalizer)
    재사용. **레거시 오케스트레이터(dart_xml_parser)에 의존하지 않음** → P6 폐기 대비.
  - XBRL 과 달리 권위있는 구조(ADECIMAL/ACONTEXT)가 없으므로 일부 추론 불가피:
    단위=가장 가까운 명시적 선언, 연결/별도=섹션, instant/duration=BS vs IS/CF.
  - **무손실**: 매핑 실패(canonical NULL)해도 행을 버리지 않고 raw 계정명(acode)과 함께
    저장 → 추후 account_maps 보강 후 재파싱 없이 복구 가능(레거시는 미매핑 행 폐기).
  - fact_v2 정합:
      acode              = 정규화된 한국어 계정명(텍스트 레벨 source 개념)
      canonical_account  = account_mapper 결과(텍스트의 concept_map 역할), 미매핑 NULL
      adecimal           = 단위 배수 역산(amount_won = 표기값 × 10^(-adecimal) 불변식 유지)
      acontext_raw       = 합성 토큰 "text:..."(원 ACONTEXT 없음 → uq_fact_v2_cell 유지)
      context_parsed     = False(합성)

run.py extract2 에서 Track A(xbrl)가 0행이면 자동 폴백으로 호출.
"""
from __future__ import annotations

import math
from pathlib import Path

from loguru import logger

from parser.common.account_mapper import get_mapper, MappingResult
from parser.common.amount_normalizer import normalize_account_name
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (
    detect_sections, find_section_tables, find_summary_tables,
    detect_unit_from_section, detect_periods_from_header,
)
from parser.xml.table_extractor import extract_rows
from fin2.extract.xbrl import ExtractedFact

# 섹션 코드 → (basis, period_kind)
_SECTION_META = {
    "BS_C": ("consolidated", "instant"),
    "IS_C": ("consolidated", "duration"),
    "CF_C": ("consolidated", "duration"),
    "BS_S": ("separate", "instant"),
    "IS_S": ("separate", "duration"),
    "CF_S": ("separate", "duration"),
}

# 보고서 기간(fiscal_period) → fact_v2 period_type
_PERIOD_TYPE = {"FY": "FY", "H1": "FH", "Q1": "FQ", "Q3": "FQ", "Q2": "FQ"}


def _adecimal_from_unit(unit: int) -> int:
    """단위 배수 → ADECIMAL 역산. 1→0, 1000→-3, 1000000→-6. (amount_won 불변식 유지)"""
    if unit <= 1:
        return 0
    return -int(round(math.log10(unit)))


def _detect_fin_type(root) -> str:
    """SUMMARY EXTRACTION 의 FIN_TYPE (A=연결있음/B=별도만). 없으면 'A' 가정."""
    for ex in root.findall(".//EXTRACTION"):
        if ex.get("ACODE", "") == "FIN_TYPE":
            return (ex.text or "A").strip() or "A"
    return "A"


def _synth_acontext(basis: str, period_kind: str, col_idx: int, ctx_fy: int | None) -> str:
    """텍스트 셀의 합성 컨텍스트 토큰(고유성 키). 원 ACONTEXT 부재를 명시."""
    return f"text:{basis[:3]}:{'e' if period_kind == 'instant' else 'd'}:c{col_idx}:{ctx_fy}"


def _row_to_fact(
    *, row, col_idx, amount, basis, period_kind, mapping: MappingResult,
    corp_code, rcept_no, report_fiscal_year, report_fiscal_period,
    fiscal_period, unit, fs_type,
) -> ExtractedFact:
    ctx_fy = report_fiscal_year - col_idx
    canonical = None if mapping.account_code.startswith("unknown.") else mapping.account_code
    is_cumulative = period_kind == "duration" and fiscal_period != "FY"
    acode = (normalize_account_name(row.account_name) or row.account_name)[:120]
    return ExtractedFact(
        corp_code=corp_code,
        rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year,
        report_fiscal_period=report_fiscal_period,
        acode=acode,
        basis=basis,
        context_fiscal_year=ctx_fy,
        col_index=col_idx,
        period_kind=period_kind,
        period_type=_PERIOD_TYPE.get(fiscal_period, "FY"),
        is_cumulative=is_cumulative,
        extra_dims=None,
        is_dimensional=False,
        adecimal=_adecimal_from_unit(unit),
        amount_won=amount,
        source_format="xml_text",
        source_ref=f"{fs_type}/{row.account_name[:80]}",
        acontext_raw=_synth_acontext(basis, period_kind, col_idx, ctx_fy),
        context_parsed=False,
        canonical_account=canonical,
    )


def extract_facts(
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
) -> list[ExtractedFact]:
    """
    Track B(텍스트) 추출. 표준 섹션(BS/IS/CF) 우선, 없으면 요약재무정보 폴백.
    같은 (acode, 합성 context) 셀 중복 시 1개로 합치되 금액 보유 행 우선.
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        logger.warning(f"[extract2/text] XML 루트 없음: {file_path}")
        return []

    fin_type = _detect_fin_type(root)
    mapper = get_mapper()
    dedup: dict[tuple[str, str], ExtractedFact] = {}

    def _add(fact: ExtractedFact):
        key = (fact.acode, fact.acontext_raw)
        prev = dedup.get(key)
        if prev is None or prev.amount_won is None:
            dedup[key] = fact

    sections = detect_sections(root)
    for section_code, title_elem in sections.items():
        if title_elem is None or section_code not in _SECTION_META:
            continue
        basis, period_kind = _SECTION_META[section_code]
        if basis == "consolidated" and fin_type == "B":
            continue  # 연결 없는 기업의 연결 섹션 무시

        unit = detect_unit_from_section(title_elem)
        tables = find_section_tables(title_elem)
        if not tables:
            continue
        # TR 많은 테이블 우선(첫 표는 보통 헤더)
        data_tables = sorted(tables, key=lambda t: len(t.findall(".//TR")), reverse=True)
        fs_section = section_code.split("_")[0].lower()

        for table in data_tables:
            for row in extract_rows(table, multiplier=unit):
                if not row.account_name:
                    continue
                mapping = mapper.map(row.account_name, fs_section=fs_section)
                for col_idx, amount in enumerate(row.amounts):
                    if amount is None:
                        continue
                    _add(_row_to_fact(
                        row=row, col_idx=col_idx, amount=amount,
                        basis=basis, period_kind=period_kind, mapping=mapping,
                        corp_code=corp_code, rcept_no=rcept_no,
                        report_fiscal_year=report_fiscal_year,
                        report_fiscal_period=report_fiscal_period,
                        fiscal_period=report_fiscal_period, unit=unit,
                        fs_type=section_code,
                    ))

    # 표준 섹션이 하나도 없으면 요약재무정보 폴백(분기/반기)
    core_found = any(
        sections.get(c) is not None
        for c in ("BS_C", "IS_C", "CF_C", "BS_S", "IS_S", "CF_S")
    )
    if not core_found:
        _extract_summary(root, mapper, fin_type, dedup, _add,
                         corp_code, rcept_no, report_fiscal_year, report_fiscal_period)

    return list(dedup.values())


def _extract_summary(root, mapper, fin_type, dedup, add,
                     corp_code, rcept_no, report_fiscal_year, report_fiscal_period):
    """요약재무정보 테이블 폴백. account_code 접두어로 BS/IS/CF·instant/duration 결정."""
    summary = find_summary_tables(root)
    if not any(v is not None for v in summary.values()):
        return
    for stmt_key, table_elem in summary.items():
        if table_elem is None:
            continue
        basis = "consolidated" if stmt_key == "consolidated" else "separate"
        if basis == "consolidated" and fin_type == "B":
            continue
        unit = _detect_unit_near_table(table_elem)
        for row in extract_rows(table_elem, multiplier=unit):
            if not row.account_name:
                continue
            mapping = mapper.map(row.account_name)
            code = mapping.account_code
            if code.startswith("bs."):
                period_kind, fs_type = "instant", "BS_" + basis[:1].upper()
            elif code.startswith("is."):
                period_kind, fs_type = "duration", "IS_" + basis[:1].upper()
            elif code.startswith("cf."):
                period_kind, fs_type = "duration", "CF_" + basis[:1].upper()
            else:
                period_kind, fs_type = "instant", "BS_" + basis[:1].upper()
            for col_idx, amount in enumerate(row.amounts):
                if amount is None:
                    continue
                add(_row_to_fact(
                    row=row, col_idx=col_idx, amount=amount,
                    basis=basis, period_kind=period_kind, mapping=mapping,
                    corp_code=corp_code, rcept_no=rcept_no,
                    report_fiscal_year=report_fiscal_year,
                    report_fiscal_period=report_fiscal_period,
                    fiscal_period=report_fiscal_period, unit=unit,
                    fs_type=fs_type,
                ))


def _detect_unit_near_table(table_elem) -> int:
    """요약표 인접 단위 선언 탐지(표 첫 행 → 앞 5개 형제, 가장 가까운 선언)."""
    from parser.common.amount_normalizer import detect_unit_declaration
    first_tr = table_elem.find(".//TR")
    if first_tr is not None:
        decl = detect_unit_declaration("".join(first_tr.itertext()))
        if decl is not None:
            return decl
    parent = table_elem.getparent()
    if parent is None:
        return 1
    siblings = list(parent)
    try:
        idx = siblings.index(table_elem)
    except ValueError:
        return 1
    for s in reversed(siblings[max(0, idx - 5):idx]):
        tag = s.tag.upper() if isinstance(s.tag, str) else ""
        if tag in ("P", "TABLE"):
            decl = detect_unit_declaration("".join(s.itertext()))
            if decl is not None:
                return decl
    return 1
