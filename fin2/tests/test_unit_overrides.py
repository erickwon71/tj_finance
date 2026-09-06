"""unit_overrides(2026-09-06) 회귀 테스트 (순수, DB 비의존).

docs/plans/unit_override_self_contradictory_filings_design_2026-09-06.md.

apply_unit_overrides()는 combine.py 밖에서 독립적으로 검증 가능 — DIRECT_MAP 매핑과
UNIT_OVERRIDES 조회, 배수 적용, 반환 레코드만 하는 순수 함수.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.unit_overrides import apply_unit_overrides, UNIT_OVERRIDES, UnitOverride  # noqa: E402

_DIRECT_MAP = {"bs.retained_earnings": "retained_earnings", "bs.total_assets": "total_assets"}


def test_matching_key_applies_multiplier_and_records_evidence():
    overrides = {
        ("00999999", 2020, "FY", "consolidated", "bs.retained_earnings"):
            UnitOverride(multiplier=1e-6, note="test fixture"),
    }
    col = {"retained_earnings": 5_000_000_000_000}
    applied = apply_unit_overrides("00999999", 2020, "FY", "consolidated",
                                   _DIRECT_MAP, col, overrides=overrides)
    assert col["retained_earnings"] == 5_000_000
    assert applied["retained_earnings"]["declared_value"] == 5_000_000_000_000
    assert applied["retained_earnings"]["corrected_value"] == 5_000_000
    assert applied["retained_earnings"]["multiplier"] == 1e-6


def test_non_matching_key_is_a_no_op():
    overrides = {
        ("00999999", 2020, "FY", "consolidated", "bs.retained_earnings"):
            UnitOverride(multiplier=1e-6, note="test fixture"),
    }
    col = {"retained_earnings": 5_000_000_000_000}
    # different corp -> untouched
    applied = apply_unit_overrides("00000001", 2020, "FY", "consolidated",
                                   _DIRECT_MAP, col, overrides=overrides)
    assert applied == {}
    assert col["retained_earnings"] == 5_000_000_000_000


def test_missing_std_col_or_none_value_is_a_no_op():
    overrides = {
        ("00999999", 2020, "FY", "consolidated", "bs.retained_earnings"):
            UnitOverride(multiplier=1e-6, note="test fixture"),
    }
    col = {"total_assets": 100}  # retained_earnings not present at all
    applied = apply_unit_overrides("00999999", 2020, "FY", "consolidated",
                                   _DIRECT_MAP, col, overrides=overrides)
    assert applied == {}
    assert col == {"total_assets": 100}


def test_missing_corp_or_fy_is_a_no_op():
    overrides = {
        ("00999999", 2020, "FY", "consolidated", "bs.retained_earnings"):
            UnitOverride(multiplier=1e-6, note="test fixture"),
    }
    col = {"retained_earnings": 123}
    assert apply_unit_overrides(None, 2020, "FY", "consolidated", _DIRECT_MAP, col,
                                overrides=overrides) == {}
    assert apply_unit_overrides("00999999", None, "FY", "consolidated", _DIRECT_MAP, col,
                                overrides=overrides) == {}
    assert col == {"retained_earnings": 123}


# --- production entry (00138516 아남전자 FY2006) ------------------------------------

def test_production_anam_electronics_2006_entry_present_and_correct_scale():
    key = ("00138516", 2006, "FY", "consolidated", "bs.retained_earnings")
    assert key in UNIT_OVERRIDES
    col = {"retained_earnings": 2_146_172_472_000_000}
    applied = apply_unit_overrides("00138516", 2006, "FY", "consolidated", _DIRECT_MAP, col)
    assert col["retained_earnings"] == 2_146_172_472
    assert applied["retained_earnings"]["concept"] == "bs.retained_earnings"


# --- 2026-09-06 세션 추가분 (가+라) 그룹 원문대조 등록 회귀 확인 -----------------------

_BS_DIRECT_MAP = {"bs.total_assets": "total_assets", "bs.total_equity": "total_equity",
                  "bs.total_liabilities": "total_liabilities",
                  "bs.retained_earnings": "retained_earnings"}
_IS_DIRECT_MAP = {"is.revenue": "revenue"}


def test_goryeo_zinc_2000h1_assets_and_equity():
    col = {"total_assets": 1_607_305_757_650_000, "total_equity": 543_274_522_470_000}
    applied = apply_unit_overrides("00102858", 2000, "H1", "consolidated", _BS_DIRECT_MAP, col)
    assert col["total_assets"] == 1_607_305_757_650
    assert col["total_equity"] == 543_274_522_470
    assert set(applied) == {"total_assets", "total_equity"}


def test_daehan_electric_wire_2001q3_assets_only():
    col = {"total_assets": 1_301_154_371_000_000}
    applied = apply_unit_overrides("00113207", 2001, "Q3", "consolidated", _BS_DIRECT_MAP, col)
    assert col["total_assets"] == 1_301_154_371_000
    assert set(applied) == {"total_assets"}


def test_00117601_2000fy_identity_holds_after_correction():
    col = {"total_assets": 2_147_088_462_884_000, "total_equity": 507_124_189_018_000}
    applied = apply_unit_overrides("00117601", 2000, "FY", "consolidated", _BS_DIRECT_MAP, col)
    # BS identity check (liabilities not in this fixture, but assets/equity scale must match):
    assert col["total_assets"] == 2_147_088_462_884
    assert col["total_equity"] == 507_124_189_018
    assert applied["total_assets"]["multiplier"] == 1e-3


def test_asia_cement_2007_identity_holds_after_correction():
    col = {"total_assets": 1_038_181_374_181_000, "total_equity": 686_974_651_880_000,
           "total_liabilities": 351_206_722_301_000}
    applied = apply_unit_overrides("00138701", 2007, "H1", "consolidated", _BS_DIRECT_MAP, col)
    assert col["total_liabilities"] + col["total_equity"] == col["total_assets"]
    assert len(applied) == 3


def test_m2n_2004q3_revenue():
    col = {"revenue": 5_553_466_556_000_000}
    applied = apply_unit_overrides("00143226", 2004, "Q3", "separate", _IS_DIRECT_MAP, col)
    assert col["revenue"] == 5_553_466_556
    assert applied["revenue"]["multiplier"] == 1e-6


def test_uid_2020q1_retained_earnings_and_revenue():
    col = {"retained_earnings": -2_697_894_422_000_000, "revenue": 7_356_347_189_000_000}
    applied = apply_unit_overrides("00400121", 2020, "Q1", "separate",
                                   {**_BS_DIRECT_MAP, **_IS_DIRECT_MAP}, col)
    assert col["retained_earnings"] == -2_697_894_422
    assert col["revenue"] == 7_356_347_189
    assert set(applied) == {"retained_earnings", "revenue"}


def test_wellcron_hantech_2010h1_revenue():
    for basis in ("separate", "consolidated"):
        col = {"revenue": 7_206_472_963_000_000}
        applied = apply_unit_overrides("00487546", 2010, "H1", basis, _IS_DIRECT_MAP, col)
        assert col["revenue"] == 7_206_472_963
        assert applied["revenue"]["multiplier"] == 1e-6


def test_softcen_2022fy_is_not_registered():
    # 00204226 소프트센 FY2022 — 원문대조 결과 "declared unit 오류"가 아니라 3개년
    # 비교표에서 잘못된 컬럼(전기 comparative)을 뽑은 별개의 코드버그로 확인됨
    # (raw XML 대조: 진짜 당기 값은 17,293,933,213인데 report_lines엔 comparative
    # 값 6,570,137,526이 들어있음). unit_override로 "고치면" 오답을 확정시키는
    # 꼴이라 등록하지 않음 — 다음 세션 별도 코드버그 트랙으로 처리.
    for key in UNIT_OVERRIDES:
        assert key[0] != "00204226"
