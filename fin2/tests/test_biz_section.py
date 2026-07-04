"""
B4 생산능력/생산실적/가동률 본문 표 추출 + 캐노니컬 매핑 회귀 테스트(실측 파일, DB 비의존).

실측 2사:
  삼성전자(00126380) 2024 사업보고서 — 부문·품목 2차원, capacity/output 기간표 + utilization
    한 표에 능력/실적/가동률 병렬(3지표).
  S-Oil(00138279) 2024 — 단위열 존재, 구분 병합(부문만), output+utilization 결합표 +
    기간 미검출 보조표(표준생산능력/가동가능일수, period_year=NULL 무손실 보존).

실행: python -m fin2.tests.test_biz_section
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.biz_section import parse_biz_metrics  # noqa: E402

_BASE = Path(__file__).resolve().parents[2]
_SAMSUNG = _BASE / "raw_report/KOSPI/00126380_삼성전자/annual/2024/20250311001085.xml"
_SOIL = _BASE / "raw_report/KOSPI/00138279_S-Oil/annual/2024/20250319000503.xml"
# B4b 회귀: 강남제비스코 = 계산근거 컬럼('2,350시간÷2,760시간×100=85.1%')이 가동률 2350%로
# 오염되던 케이스. LX인터내셔널 = 유형자산/공장 소재지·면적 표만 있어 생산행 0이어야 함.
_KANGNAM = _BASE / "raw_report/KOSPI/00100939_강남제비스코/annual/2024/20250318001036.xml"
_LXINTL = _BASE / "raw_report/KOSPI/00120076_LX인터내셔널/annual/2024/20250320000626.xml"
# B4b-2 회귀: 아세아텍 = 전치형 레이아웃(지표명이 '구분' 열 값) + 기간별 수량/금액 하위열 +
# 날짜헤더 "2024.06.30(제46기)"(first_data 오탐 유발) + '가동율'(율 표기 변이).
_ASEATECH = _BASE / "raw_report/KOSDAQ/00138747_아세아텍/annual/2024/20240913000575.xml"
# B4b-3 회귀: 삼화전자공업(2005, 구형 K-GAAP) — 빈 셀이 콤마 하나(',')뿐인 표 → _parse_value 가
# _NUM_LEAD_RE 매치를 숫자로 오인해 float('') ValueError 크래시(전수 다개년 백필 중 실측 발견).
_SAMHWA = _BASE / "raw_report/KOSPI/00129280_삼화전자공업/annual/2005/20060515002622.xml"


def _rows(fp, corp, fy):
    _, met = parse_biz_metrics(fp, corp, fy)
    return met


def _find(rows, **kw):
    out = []
    for r in rows:
        if all(r.get(k) == v for k, v in kw.items()):
            out.append(r)
    return out


def test_samsung_capacity_period_resolution():
    """제56/55/54기 → 2024/2023/2022 상대 연도 해석 + 값 정확."""
    rows = _rows(_SAMSUNG, "00126380", 2024)
    memory = _find(rows, metric="capacity", segment="DS 부문", item="메모리")
    by_year = {r["period_year"]: r["value"] for r in memory}
    assert by_year.get(2024) == 2_238_240_405, by_year
    assert by_year.get(2023) == 1_926_651_546, by_year
    assert by_year.get(2022) == 1_905_731_836, by_year


def test_samsung_utilization_three_metrics_one_table():
    """가동률 표 하나에서 capacity/output/utilization 3지표 분리 + 가동률 %."""
    rows = _rows(_SAMSUNG, "00126380", 2024)
    tv_util = _find(rows, metric="utilization", segment="DX 부문", item="TV, 모니터 등",
                    period_year=2024)
    assert len(tv_util) == 1 and abs(tv_util[0]["value"] - 79.8) < 1e-6, tv_util
    assert tv_util[0]["is_ratio"] is True and tv_util[0]["unit"] == "%"


def test_soil_unit_column_and_merged_segment():
    """단위열(천배럴/천톤) 행별 적용 + 구분 병합 → segment만(item None)."""
    rows = _rows(_SOIL, "00138279", 2024)
    jeongyu = _find(rows, metric="capacity", segment="정유부문", period_year=2024)
    assert len(jeongyu) == 1, jeongyu
    assert jeongyu[0]["item"] is None
    assert jeongyu[0]["value"] == 242_300 and jeongyu[0]["unit"] == "천배럴"


def test_soil_combined_output_utilization():
    """결합표(생산실적+가동률)에서 컬럼 세부라벨로 지표 분리. 가동률 unit=%."""
    rows = _rows(_SOIL, "00138279", 2024)
    util = _find(rows, metric="utilization", segment="윤활부문", period_year=2024)
    assert len(util) == 1 and abs(util[0]["value"] - 101.0) < 1e-6, util
    assert util[0]["unit"] == "%"
    out = _find(rows, metric="output", segment="윤활부문", period_year=2024)
    assert len(out) == 1 and out[0]["value"] == 15_965, out


def test_soil_nonperiod_supplementary_lossless():
    """기간 미검출 보조표(표준생산능력/가동가능일수) → period_year NULL + 라벨 보존(무손실)."""
    rows = _rows(_SOIL, "00138279", 2024)
    std_cap = _find(rows, segment="정유부문", period_label="표준생산능력")
    assert len(std_cap) == 1 and std_cap[0]["period_year"] is None, std_cap
    assert std_cap[0]["value"] == 669_000


def test_kangnam_formula_column_excluded():
    """계산근거(÷×= 서술) 컬럼은 값열이 아니라 배제 → 가동률 오염(실제가동시간 2350%) 없음."""
    if not _KANGNAM.exists():
        return
    rows = _rows(_KANGNAM, "00100939", 2024)
    util = [r for r in rows if r["metric"] == "utilization"]
    assert util, "가동률 행이 있어야 함"
    assert all(0 <= r["value"] <= 200 for r in util), \
        [r for r in util if not 0 <= r["value"] <= 200]
    # 실제가동시간(2350)은 utilization 아닌 output 으로 분류.
    assert not any(r["metric"] == "utilization" and r["value"] == 2350 for r in rows)


def test_lxintl_facility_table_dropped():
    """유형자산/공장 소재지·면적 표만 존재 → 생산 지표행 0(오포착 차단)."""
    if not _LXINTL.exists():
        return
    rows = _rows(_LXINTL, "00120076", 2024)
    assert len(rows) == 0, f"소재지/면적 표에서 생산행이 새면 안 됨: {rows[:2]}"


def test_aseatech_transposed_layout():
    """전치형(지표명이 구분열) + 수량/금액 하위열 + 날짜헤더 + '가동율' 변이 종합."""
    if not _ASEATECH.exists():
        return
    rows = _rows(_ASEATECH, "00138747", 2024)
    assert rows, "전치형 표에서 행을 뽑아야 함(날짜헤더 first_data 오탐 회귀 방지)"
    metrics = {r["metric"] for r in rows}
    assert metrics >= {"capacity", "output", "utilization"}, metrics
    # 관리기 2024: 구분열이 지표로 승격 + 수량/금액 단위 구분.
    g = [r for r in rows if r["segment"] == "관리기" and r["period_year"] == 2024]
    out_qty = [r for r in g if r["metric"] == "output" and r["unit"] == "수량"]
    assert out_qty and out_qty[0]["value"] == 16458, out_qty
    assert any(r["metric"] == "output" and r["unit"] == "금액" for r in g), g
    # 가동율(율 표기) → utilization + 비율(%없이도).
    util = [r for r in g if r["metric"] == "utilization"]
    assert util and util[0]["is_ratio"] and util[0]["unit"] == "%", util
    assert 0 < util[0]["value"] <= 200, util


def test_samhwa_comma_only_cell_no_crash():
    """콤마 하나(',')뿐인 빈 셀이 _parse_value 를 크래시시키지 않아야 함(ValueError 회귀)."""
    if not _SAMHWA.exists():
        return
    rows = _rows(_SAMHWA, "00129280", 2005)  # 예외 없이 완주하면 통과
    assert isinstance(rows, list)


def _run():
    for fp, name in ((_SAMSUNG, "삼성전자"), (_SOIL, "S-Oil")):
        if not fp.exists():
            print(f"  - SKIP: 실측 파일 없음 {name} {fp}")
            return 0
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests)} tests, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
