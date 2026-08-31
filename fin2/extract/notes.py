"""
CF 주석 D&A 추출기 (fin2 E-레이어 보조).

직접법(direct-method) 현금흐름표 등 **재무제표 본문에 감가상각이 없는** 보고서는
D&A 가 현금흐름표 주석("N. 현금흐름표")에만 있다. 레거시 `parser/xml/note_extractor.py`
(검증된 추출기)를 재사용해 note.* fact_v2 행을 생성한다. build.py 의 D&A 보조수집과
rules.rule_additive_da 가 이미 note.* 를 받도록 배선돼 있어, 추출만 채우면 depreciation/
amortization/da_total/ebitda 가 복원된다.

★ 단위감지 강화: 레거시 추출기는 단위 표기를 못 찾으면 백만원(1e6)으로 가정 → 일부
보고서에서 ×1000/×1e6 단위 오류(매출 대비 비현실적 D&A). 본 모듈은 같은 보고서의
매출(revenue_ref, 원 단위)을 앵커로 da_total/revenue 비율이 현실 범위에 들도록 basis 별
배율을 보정하고, 어떤 배율로도 현실적이지 않으면 그 basis 를 **버린다**(가비지보다 NULL).

⚠ 중복합산 방지: face(cf./is.) D&A 가 있는 보고서에 note.* 를 더하면 rule_additive_da 가
2배 합산한다. 따라서 호출측(재추출 스크립트)이 **본문 D&A 없는 보고서로만** 한정해 부른다.
"""
from __future__ import annotations

from math import log10
from pathlib import Path

from loguru import logger

from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.note_extractor import extract_da_from_cf_notes
from fin2.extract.xbrl import ExtractedFact

# da_total/revenue 현실 범위(이 밖이면 단위오류로 간주). 일반 제조/서비스 D&A 는 매출의
# 0.1~60%. 보수적으로 넓게 잡고, 배율 후보 중 target 에 가장 가까운 것을 택한다.
_RATIO_LO, _RATIO_HI = 3e-4, 2.0
_RATIO_TARGET = 0.04
# 시도 배율(원 환산 재조정): 그대로 / ×1e3 / ÷1e3 / ×1e6 / ÷1e6
_FACTORS = (1.0, 1e3, 1e-3, 1e6, 1e-6)

_DEP_LIKE = ("note.depreciation", "note.amortization", "note.rou_depreciation")

# parser/xml/note_extractor.py::_add_da_total() 이 depreciation+amortization(+rou)
# 이 있으면 무조건 덧붙이는 합성 rollup 마커. 원문에 이 정확한 문자열이 나올 수 없어
# (note_extractor.py 의 텍스트/ENG 매핑 테이블엔 note.da_total 로 직접 가는 패턴이
# 없음 — 오직 이 합성 경로만 이 code 를 만든다) 안전하게 판별 가능하다.
# docs/plans/factv2_synthetic_da_total_cleanup_2026-08-31.md §1~§2-1.
_SYNTHETIC_DA_TOTAL_NAME = "D&A 합계 (감가상각비+무형자산상각비)"


def _basis_of(is_consolidated: bool) -> str:
    return "consolidated" if is_consolidated else "separate"


def _unit_factor(da_total_won: int | None, revenue_ref: int | None) -> float | None:
    """
    da_total(원) 과 매출(원)로 단위 보정 배율을 고른다.

    반환: 적용할 배율(현실 범위에 드는 것 중 target 비율에 가장 가까움).
          어떤 배율로도 현실 범위에 못 들면 None(=그 basis 버림).
          revenue_ref 가 없거나 da_total 이 0/None 이면 1.0(보정 안 함).
    """
    if not da_total_won or not revenue_ref or revenue_ref <= 0:
        return 1.0
    base = abs(da_total_won) / revenue_ref
    best: tuple[float, float] | None = None  # (target 거리, factor)
    for f in _FACTORS:
        ratio = base * f
        if _RATIO_LO <= ratio <= _RATIO_HI:
            dist = abs(log10(ratio) - log10(_RATIO_TARGET))
            if best is None or dist < best[0]:
                best = (dist, f)
    return best[1] if best else None


def extract_note_da_facts(
    file_path: str | Path,
    *,
    rcept_no: str,
    corp_code: str,
    report_fiscal_year: int,
    report_fiscal_period: str,
    revenue_by_basis: dict[str, int] | None = None,
) -> list[ExtractedFact]:
    """
    한 DART XML 의 CF 주석에서 당기(col0) D&A 를 추출해 note.* ExtractedFact 로 변환.

    revenue_by_basis: {basis: revenue_won} — 단위감지 강화 앵커(없으면 보정 생략).
    같은 (rcept, acode, acontext) 유일성: acode=note 계정코드, acontext=합성("note:{basis}:col0").
    """
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return []

    raw = [f for f in extract_da_from_cf_notes(root)
           if f.col_index == 0 and f.amount is not None]
    if not raw:
        return []

    revenue_by_basis = revenue_by_basis or {}

    # basis 별 배율 보정: da_total(없으면 dep-like 합)을 앵커로 단일 배율 결정.
    facts_by_basis: dict[str, list] = {}
    for f in raw:
        facts_by_basis.setdefault(_basis_of(f.is_consolidated), []).append(f)

    out: list[ExtractedFact] = []
    for basis, fs in facts_by_basis.items():
        # 같은 계정(note.depreciation 등)이 여러 라인(유형/투자부동산 등)으로 올 수 있다.
        # 계정코드별로 **합산**해 1행씩 방출한다(uq_fact_v2_cell 충돌 방지 + 총액 정확).
        by_code: dict[str, int] = {}
        for f in fs:
            if f.account_code == "note.da_total" and f.account_name_raw == _SYNTHETIC_DA_TOTAL_NAME:
                continue        # 합성 rollup — fact_v2 에 실제 계정처럼 남으면 안 됨
            if f.amount is not None:
                by_code[f.account_code] = by_code.get(f.account_code, 0) + f.amount

        da_total = by_code.get("note.da_total")
        if da_total is None:
            da_total = sum(v for c, v in by_code.items() if c in _DEP_LIKE)
        factor = _unit_factor(da_total, revenue_by_basis.get(basis))
        if factor is None:
            logger.debug(f"[notes] {rcept_no} {basis}: 단위 보정 불가(매출대비 비현실) → 버림")
            continue

        acontext = f"note:{basis}:col0"
        for code, amt in by_code.items():
            out.append(ExtractedFact(
                corp_code=corp_code,
                rcept_no=rcept_no,
                report_fiscal_year=report_fiscal_year,
                report_fiscal_period=report_fiscal_period,
                acode=code,                            # 합성 acode = note 계정코드
                basis=basis,
                context_fiscal_year=report_fiscal_year,
                col_index=0,
                period_kind=None,
                period_type=None,
                is_cumulative=True,                   # 주석 D&A 는 기간 누적
                extra_dims=None,
                is_dimensional=False,
                adecimal=None,
                amount_won=int(round(amt * factor)),
                source_format="note_cf",
                source_ref=f"{basis}/note_cf"[:180],
                acontext_raw=acontext,
                context_parsed=True,
                canonical_account=code,                # note.* 는 이미 canonical
            ))
    return out
