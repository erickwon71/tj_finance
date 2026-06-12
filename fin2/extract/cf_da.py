"""2024+ CF D&A 보충추출 (Track A 갭 복원).

배경: DART 가 2024 보고서부터 Track A(xbrl_acode) 포맷으로 전환하면서 현금흐름표의
감가상각 조정라인을 **개별 XBRL ACODE 로 태깅하지 않게** 되었다(집계라인
`ifrs-full_AdjustmentsForReconcileProfitLoss` 만 태깅). Track A 추출기(xbrl.py)는
TE[@ACODE] 만 읽으므로 D&A 를 통째로 놓치고, Track A 가 행을 내므로 Track B 폴백도
영영 돌지 않는다 → 연결 ebitda 가 2023:25%→2024:0.8% 절벽.

복원 전략(검증: 연결 250건 샘플, 레거시 standard_financials 정답지):
  ① CF **주석**(note_extractor) — 삼성류(본문 집계라인만). 레거시 일치 100%.
  ② CF **본문 face**(Track B 텍스트표) — 경농류(본문이 감가상각 itemize). 레거시 일치 83%.
  둘은 상호보완(겹침 0). 주석 우선·본문 폴백 하이브리드 = 복원율 ~38%, 레거시 일치 ~86%.

고신뢰 가드:
  - 단위검증: 보정 후 |da_total|/동일basis 매출 ∈ [accept_lo, accept_hi].
  - 중복합산 방지: 호출측이 depreciation IS NULL 행만 대상으로 호출(본문 D&A 없는 보고서).
  - 산출은 note.* 합성 fact 로 통일(build.py _DA_SUPP 가 수집 → rule_additive_da 가 조립).
    source_format 으로 출처 구분(note_cf / cf_face), acontext 토큰으로 uq_fact_v2_cell 유지.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from fin2.extract.xbrl import ExtractedFact
from fin2.extract.notes import extract_note_da_facts
from fin2.extract import text as text_extract

# 동일 basis 의 da_total/매출 수용 범위(보정 후). 모듈 외부에서 조정 가능.
_DEFAULT_LO, _DEFAULT_HI = 0.003, 0.6

# Track B CF 본문에서 D&A 로 합산할 canonical(감가상각·무형상각·사용권).
_FACE_DEP = ("cf.depreciation", "cf.rou_depreciation", "cf.roa_depreciation")
_FACE_AMO = ("cf.amortization",)


def _da_from_note(facts: list[ExtractedFact], basis: str) -> tuple[int | None, list[ExtractedFact]]:
    """note_extractor 산출물에서 해당 basis 의 (da_total, facts) 추출."""
    fs = [f for f in facts if f.basis == basis]
    if not fs:
        return None, []
    da = next((f.amount_won for f in fs if f.canonical_account == "note.da_total"), None)
    if da is None:
        da = sum(f.amount_won for f in fs if f.canonical_account in
                 ("note.depreciation", "note.amortization", "note.rou_depreciation"))
    return (da or None), fs


def _face_da_facts(
    file_path, *, rcept_no, corp_code, report_fiscal_year, report_fiscal_period, basis
) -> tuple[int | None, list[ExtractedFact]]:
    """Track B CF 본문에서 해당 basis 의 감가상각·무형상각을 합산해 note.* 합성 fact 생성."""
    tb = text_extract.extract_facts(
        file_path, rcept_no=rcept_no, corp_code=corp_code,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
    )
    dep = sum(abs(f.amount_won) for f in tb if f.basis == basis and f.col_index == 0
              and f.canonical_account in _FACE_DEP and f.amount_won)
    amo = sum(abs(f.amount_won) for f in tb if f.basis == basis and f.col_index == 0
              and f.canonical_account in _FACE_AMO and f.amount_won)
    if dep <= 0 and amo <= 0:
        return None, []

    by_code: dict[str, int] = {}
    if dep > 0:
        by_code["note.depreciation"] = dep
    if amo > 0:
        by_code["note.amortization"] = amo
    by_code["note.da_total"] = dep + amo
    facts = _synth_facts(by_code, basis=basis, rcept_no=rcept_no, corp_code=corp_code,
                         report_fiscal_year=report_fiscal_year,
                         report_fiscal_period=report_fiscal_period,
                         source_format="cf_face", acontext=f"cfface:{basis}:col0")
    return dep + amo, facts


def _synth_facts(by_code, *, basis, rcept_no, corp_code, report_fiscal_year,
                 report_fiscal_period, source_format, acontext) -> list[ExtractedFact]:
    return [ExtractedFact(
        corp_code=corp_code, rcept_no=rcept_no,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        acode=code, basis=basis, context_fiscal_year=report_fiscal_year,
        col_index=0, period_kind=None, period_type=None, is_cumulative=True,
        extra_dims=None, is_dimensional=False, adecimal=None, amount_won=int(amt),
        source_format=source_format, source_ref=f"{basis}/{source_format}"[:180],
        acontext_raw=acontext, context_parsed=True, canonical_account=code,
    ) for code, amt in by_code.items()]


def recover_cf_da(
    file_path: str | Path, *, rcept_no: str, corp_code: str,
    report_fiscal_year: int, report_fiscal_period: str,
    basis: str, revenue_by_basis: dict[str, int],
    accept_lo: float = _DEFAULT_LO, accept_hi: float = _DEFAULT_HI,
) -> tuple[list[ExtractedFact], str | None]:
    """
    한 보고서에서 해당 basis 의 CF D&A 를 복원한다(주석 우선·본문 폴백).

    반환: (facts, source). source ∈ {'note','face',None}. 둘 다 단위가드 탈락 시 ([], None).
    facts 는 note.* 합성 ExtractedFact (store_facts 로 upsert → build.py 가 수집).
    """
    rev = revenue_by_basis.get(basis)
    if not rev or rev <= 0:
        return [], None

    def _ok(da):
        return da is not None and da != 0 and accept_lo <= abs(da) / rev <= accept_hi

    # ① CF 주석(단위보정 내장: notes._unit_factor 가 매출 앵커로 배율 보정)
    note_all = extract_note_da_facts(
        file_path, rcept_no=rcept_no, corp_code=corp_code,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        revenue_by_basis=revenue_by_basis,
    )
    da, note_facts = _da_from_note(note_all, basis)
    if note_facts and _ok(da):
        return note_facts, "note"

    # ② CF 본문 face(Track B). 단위는 섹션 선언값 → 비현실 비율이면 가드가 버림.
    da, face_facts = _face_da_facts(
        file_path, rcept_no=rcept_no, corp_code=corp_code,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        basis=basis,
    )
    if face_facts and _ok(da):
        return face_facts, "face"

    return [], None
