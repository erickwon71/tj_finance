"""사업보고서 [연구개발비용] 표에서 R&D 총액 추출 (rd_expense 갭 복원).

배경: R&D 는 face IS XBRL 표준개념으로 태깅한 기업(~327사)만 std_v2 에 채워지고, 대다수는
**사업보고서 'II. 사업의 내용' 의 [연구개발비용] 표**(DART 표준양식)에만 있다.

산출: note.rd_expense 합성 fact → build.py 가 수집 → rules.rule_rd_fallback 이 is.rd_expense
없을 때만 rd_expense 로 채움(중복 방지).

── 2026-07-17 재설계(Phase A-3) — 추측 2종 제거 ───────────────────────────────
1) **전역 TABLE 스캔 폐지**(`root.findall(".//TABLE")`). text.py 가 8.5경 사고로 배운 것과
   **똑같은 결함**이었다: '연구개발비용' 라벨은 본문 밖에도 산다. 실측(2018+ 무작위 40건) —
   그 라벨을 가진 표의 소속 섹션은 `사업의내용` **60** vs `연결재무제표주석`/`재무제표주석`
   **61**(+face 6). 즉 **절반이 주석표**이고, **32%의 보고서에서 후보가 2개 이상**이라
   '첫 매칭'은 사실상 문서 순서 운에 맡기는 추측이었다.
   ⟹ `사업의 내용` 섹션 내부 표만 후보(assign_tables_to_dart_sections, 문서순서 귀속).
2) **단위 추측 폐지**. 구버전은 ① 상위노드 텍스트 4,000자를 훑어 단위를 줍고
   (`_detect_unit_in_text`, 못 찾으면 **백만원 가정**) ② 그렇게 얻은 값에 배율 5종
   (1·10³·10⁻³·10⁶·10⁻⁶)을 대입해 **매출 대비 비율이 3% 에 가장 가까운 것**을 채택했다.
   이는 "그럴듯한 답 고르기"이고, 배율을 기록하지 않아 **역산조차 불가**했다.
   ⟹ 그 표가 **명시 선언한 단위만** 사용(declared_unit). 미선언이면 **보류**(적재 안 함).
   원문 단위 오기(3S·네오크레마형)는 garbage-in 으로 그대로 드러나야 어서션이 잡는다.
"""
from __future__ import annotations

import math
from pathlib import Path

from loguru import logger

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.note_extractor import _get_text, _parse_amount
from parser.xml.section_detector import (
    assign_tables_to_dart_sections, table_direct_rows, SEC_BIZ_CONTENT,
)
from fin2.extract.text import declared_unit
from fin2.extract.xbrl import ExtractedFact

# R&D 총액 행 라벨 우선순위(공백 제거 후 전방일치). 총계(정부보조금 차감 전)를 R&D intensity 로 사용.
_LABELS = ("연구개발비용총계", "연구개발비용계", "연구개발비(비용)",
           "연구개발비용합계", "연구개발비합계", "연구개발비용", "연구개발비")


def _norm(s: str) -> str:
    return s.replace(" ", "").replace("　", "")


def _adecimal_from_unit(unit: int) -> int:
    """단위 배수 → ADECIMAL 역산(amount_won = 표기값 × 10^(-adecimal) 불변식 유지)."""
    if unit <= 1:
        return 0
    return -int(round(math.log10(unit)))


def _rd_tables(root) -> list:
    """'사업의 내용' 섹션 안에서 '연구개발비용' 라벨 행을 가진 표들(문서 순서)."""
    sec_tables = assign_tables_to_dart_sections(root)
    out = []
    for table in sec_tables.get(SEC_BIZ_CONTENT, []):
        for tr in table_direct_rows(table):
            cells = [c for c in tr if c.tag in ("TD", "TH")]
            if not cells:
                continue
            label = _norm(_get_text(cells[0]))
            if label.startswith("연구개발비용") or label.startswith("연구개발비"):
                out.append(table)
                break
    return out


def _rd_total_from_table(table) -> int | None:
    """우선순위 라벨 행의 당기(첫 금액 셀) 값(원). 단위 미선언이면 None(보류)."""
    unit = declared_unit(table)
    if unit is None:
        return None

    rows = []
    for tr in table_direct_rows(table):
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
    basis: str = "consolidated",
) -> list[ExtractedFact]:
    """사업보고서 [연구개발비용] 표 → note.rd_expense ExtractedFact(당기). 실패/보류 시 []."""
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []

    tables = _rd_tables(root)
    if not tables:
        logger.debug(f"[rd_note] {rcept_no}: '사업의 내용' 에 연구개발비용 표 없음 → 보류")
        return []

    # 후보가 여럿이면 **고르지 않는다**(추측 금지). 값이 갈리면 판정 불가 → 보류.
    # 같은 값이면 무해하므로 통과. (구버전은 '첫 표'를 집었다 = 문서순서 운.)
    #
    # ★ 실측(2018+ 60건): 추출 37 / 보류 12 / 표없음 11. 보류 12 의 사유는 두 가지이고
    #   **둘 다 보류가 정답**이다:
    #     ① 후보 다중 = 대개 **연결 vs 별도**(국도화학 114억 vs 4.2억 · 계룡건설 22억 vs 12.6억 ·
    #        LS 는 5개 중 하나가 '연결기준으로 …' 라고 서술). 구버전의 '첫 표'는 basis 를
    #        **운에 맡긴 것**이었다 — 인자로 basis 를 받으면서 정작 표 선택엔 안 썼다.
    #        → 제대로 고치려면 서술 헤딩의 '연결' 유무로 basis 를 확정해야 한다
    #          (expense_nature._find_heading 패턴). **Phase C 패턴루프 대상**.
    #     ② 총액행 부재 = 그 표에 '연구개발비/매출액 비율'(3.94%) 같은 **비율행만** 있는 경우
    #        (경보제약·광명전기). 금액이 아니므로 당연히 적재 대상이 아니다.
    seen: dict[int, int] = {}   # amount → unit(참고)
    for t in tables:
        rd = _rd_total_from_table(t)
        if rd is not None and rd > 0:
            seen[rd] = seen.get(rd, 0) + 1
    if not seen:
        logger.debug(f"[rd_note] {rcept_no}: 단위 미선언 또는 총액행 없음 → 보류")
        return []
    if len(seen) > 1:
        logger.debug(f"[rd_note] {rcept_no}: 연구개발비용 총액 후보 {sorted(seen)} 충돌 → 보류")
        return []
    rd = next(iter(seen))

    unit = next((u for u in (declared_unit(t) for t in tables) if u is not None), 1)
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
        adecimal=_adecimal_from_unit(unit),
        amount_won=rd,
        source_format="note_rd",
        source_ref=f"{basis}/note_rd"[:180],
        acontext_raw=f"note:{basis}:rd:col0",
        context_parsed=True,
        canonical_account="note.rd_expense",
        # 재무제표 4섹션이 아니라 **사업 서술** 구획 출처임을 명시(감사 시 구분 가능).
        section_kind=SEC_BIZ_CONTENT,
        mapping_stage="exact",          # 표 라벨을 고정 목록으로 직접 판정(퍼지 아님)
        mapping_confidence=1.0,
        unit_source="declared",
    )]
