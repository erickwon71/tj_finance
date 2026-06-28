"""사업보고서 [연구개발비용] 표에서 R&D 총액 추출 (rd_expense 갭 복원).

배경: R&D 는 face IS XBRL 표준개념으로 태깅한 기업(~327사)만 std_v2 에 채워지고, 대다수는
**사업보고서 본문 "연구개발활동" 섹션의 [연구개발비용] 표**(DART 표준양식)에만 있다.
이 표는 비교적 정형이라("연구개발비용 총계 | 제N기 | …", 단위 보통 백만원) 파싱 가능하다.

산출: note.rd_expense 합성 fact → build.py 가 수집 → rules.rule_rd_fallback 이 is.rd_expense
없을 때만 rd_expense 로 채움(중복 방지). 단위가드(rd/매출 현실범위)로 가비지 차단.
"""
from __future__ import annotations

from math import log10
from pathlib import Path

from loguru import logger

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.note_extractor import _get_text, _detect_unit_in_text, _parse_amount
from fin2.extract.xbrl import ExtractedFact

# R&D 총액 행 라벨 우선순위(공백 제거 후 부분일치). 총계(정부보조금 차감 전)를 R&D intensity 로 사용.
_LABELS = ("연구개발비용총계", "연구개발비용계", "연구개발비(비용)",
           "연구개발비용합계", "연구개발비합계", "연구개발비용", "연구개발비")
# rd/매출 현실범위(이 밖이면 단위오류로 간주). 일반 0.01~40%, 바이오 등 고강도 여유.
_RATIO_LO, _RATIO_HI, _RATIO_TARGET = 1e-4, 0.6, 0.03
_FACTORS = (1.0, 1e3, 1e-3, 1e6, 1e-6)


def _unit_factor(rd_won: int | None, revenue_ref: int | None) -> float | None:
    if not rd_won or not revenue_ref or revenue_ref <= 0:
        return 1.0
    base = abs(rd_won) / revenue_ref
    best = None
    for f in _FACTORS:
        ratio = base * f
        if _RATIO_LO <= ratio <= _RATIO_HI:
            dist = abs(log10(ratio) - log10(_RATIO_TARGET))
            if best is None or dist < best[0]:
                best = (dist, f)
    return best[1] if best else None


def _norm(s: str) -> str:
    return s.replace(" ", "").replace("　", "")


def _find_rd_table(root):
    """[연구개발비용] 표 = '연구개발비용' 라벨 행을 가진 TABLE. 첫 매칭 반환."""
    for table in root.findall(".//TABLE"):
        rows = table.findall(".//TR")
        for tr in rows:
            cells = [c for c in tr if c.tag in ("TD", "TH")]
            if not cells:
                continue
            label = _norm(_get_text(cells[0]))
            if label.startswith("연구개발비용") or label.startswith("연구개발비"):
                return table
    return None


def _rd_total_from_table(table) -> int | None:
    """우선순위 라벨 행에서 당기(첫 숫자 셀) 값(단위 미적용 원시정수×단위배수)."""
    # 단위: 표 또는 상위 노드 텍스트에서 탐지(없으면 백만원 기본)
    scope = table.getparent() if table.getparent() is not None else table
    unit = _detect_unit_in_text(_get_text(scope)[:4000])

    rows = []
    for tr in table.findall(".//TR"):
        cells = [c for c in tr if c.tag in ("TD", "TH")]
        if not cells:
            continue
        label = _norm(_get_text(cells[0]))
        amounts = [_parse_amount(_get_text(c), unit) for c in cells[1:]]
        curr = next((a for a in amounts if a is not None), None)
        rows.append((label, curr))

    for want in _LABELS:
        for label, curr in rows:
            if label.startswith(want) and curr is not None:
                return curr
    return None


def extract_rd_facts(
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
    revenue_ref: int | None = None,
    basis: str = "consolidated",
) -> list[ExtractedFact]:
    """사업보고서 [연구개발비용] 표 → note.rd_expense ExtractedFact(당기). 실패 시 []."""
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []
    table = _find_rd_table(root)
    if table is None:
        return []
    rd = _rd_total_from_table(table)
    if rd is None or rd <= 0:
        return []

    factor = _unit_factor(rd, revenue_ref)
    if factor is None:
        logger.debug(f"[rd_note] {rcept_no}: 단위 보정 불가(매출대비 비현실 {rd}) → 버림")
        return []

    return [ExtractedFact(
        corp_code=corp_code,
        rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year,
        report_fiscal_period=report_fiscal_period,
        acode="note.rd_expense",
        basis=basis,
        context_fiscal_year=report_fiscal_year,
        col_index=0,
        period_kind=None,
        period_type=None,
        is_cumulative=True,
        extra_dims=None,
        is_dimensional=False,
        adecimal=None,
        amount_won=int(round(rd * factor)),
        source_format="note_rd",
        source_ref=f"{basis}/note_rd"[:180],
        acontext_raw=f"note:{basis}:rd:col0",
        context_parsed=True,
        canonical_account="note.rd_expense",
    )]
