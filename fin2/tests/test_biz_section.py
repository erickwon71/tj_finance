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
# B4b-4 회귀(다개년 전수 백필 중 실측, 2026-07-05): 중첩 TABLE·경계매치·오검출 4종 복합.
_LG = _BASE / "raw_report/KOSPI/00120021_LG/annual/2011/20120330003253.xml"          # 중첩TABLE 오염
_DAECHANG = _BASE / "raw_report/KOSPI/00112679_대창단조/annual/2009/20100331000054.xml"  # 2096년 버그
_SUNL = _BASE / "raw_report/KOSPI/00132211_SUN&L/annual/2023/20240321001713.xml"     # 1907년 버그
_HYUNDAIWIA = _BASE / "raw_report/KOSPI/00106623_현대위아/annual/2006/20070330001121.xml"  # 가동률 오분류
_GS = _BASE / "raw_report/KOSPI/00500254_GS/annual/2023/20240320001516.xml"           # 매입처표 오염
_HYUNDAIBIO = _BASE / "raw_report/KOSDAQ/00313649_현대바이오/annual/2015/20160329000763.xml"  # 전치형 시간값 오염
_SGWORLD = _BASE / "raw_report/KOSPI/00133511_SG세계물산/annual/2017/20180402002320.xml"  # 순이익률표 오염
_HYUNDAIHIMS = _BASE / "raw_report/KOSDAQ/00667373_현대힘스/annual/2025/20260318000236.xml"  # PP&E롤포워드 오염
_LOTTE_EM = _BASE / "raw_report/KOSPI/00113997_롯데에너지머티리얼즈/annual/2024/20250314001597.xml"  # 약정공시 오염


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


def test_lg_nested_table_no_pollution():
    """페이지 레이아웃 바깥 TABLE 이 중첩 TABLE 을 통째로 감싸는 문서(중첩 859개, 최대 TABLE
    3073 TR 중 3069개=중첩분)에서 재무제표 라인('법인세비용' 등)이 생산데이터로 새면 안 됨."""
    if not _LG.exists():
        return
    rows = _rows(_LG, "00120021", 2011)
    assert not any(r["segment"] and any(k in r["segment"] for k in ("법인세비용", "환율변동효과", "영업외손익"))
                   for r in rows)
    assert all(r["value"] < 10_000_000 for r in rows if r["metric"] == "utilization")


def test_daechang_no_bogus_future_year():
    """소제목 번호("6","7"...)가 부문명으로, 무관한 큰 수의 부분매치가 period_year=2096 으로
    새던 회귀. 모든 period_year 는 합리적 범위(1990~2027)여야 함."""
    if not _DAECHANG.exists():
        return
    rows = _rows(_DAECHANG, "00112679", 2009)
    assert not any(r["segment"] and r["segment"].strip().isdigit() for r in rows)
    assert all(1990 <= r["period_year"] <= 2027 for r in rows if r["period_year"] is not None)


def test_sunl_year_not_matched_inside_decimal():
    """'0.0119072CBM' 같은 소수/큰수 내부에 우연히 낀 4자리("1907")를 연도로 오인하면 안 됨
    (_PERIOD_YEAR_RE 자릿수 경계 가드 회귀)."""
    if not _SUNL.exists():
        return
    rows = _rows(_SUNL, "00132211", 2023)
    assert all(1990 <= r["period_year"] <= 2027 for r in rows if r["period_year"] is not None)


def test_hyundaiwia_ratio_without_percent_sign():
    """%기호 없이 순수숫자로만 쓰인 진짜 가동률("90.14")은 utilization+%단위로 살아있어야 하고
    (과잉 재분류 방지), 정작 큰 시간값("연간가동가능시간" 1,189,180)은 가동률로 새면 안 됨."""
    if not _HYUNDAIWIA.exists():
        return
    rows = _rows(_HYUNDAIWIA, "00106623", 2006)
    util = [r for r in rows if r["metric"] == "utilization"]
    assert util, "진짜 가동률(90.14 등)이 output 등으로 오분류되면 안 됨"
    assert all(r["unit"] == "%" and 0 <= r["value"] <= 200 for r in util), util


def test_gs_purchase_table_dropped():
    """원재료 매입처 현황표("N (X%)" 수량+비중 괄호표기)가 생산데이터로 새면 안 됨
    (괄호 비중 길이가 우연히 clean-number 판정을 흔들어 헤더경계까지 왜곡시키던 케이스)."""
    if not _GS.exists():
        return
    rows = _rows(_GS, "00500254", 2023)
    assert not any(r["metric"] == "utilization" and r["value"] > 200 for r in rows)


def test_hyundaibio_transposed_hours_not_forced_ratio():
    """전치형(구분열='가동률' 단일값)에서 row_metric 강제가 매그니튜드 가드를 우회해
    '가동가능시간'(4,800)·'실제가동시간'(4,300) 이 4800%/4300% 로 새면 안 됨. 진짜 비율
    (가동율 89.6%)은 그대로 utilization 유지."""
    if not _HYUNDAIBIO.exists():
        return
    rows = _rows(_HYUNDAIBIO, "00313649", 2015)
    assert not any(r["metric"] == "utilization" and r["value"] > 500 for r in rows)
    real_util = [r for r in rows if r["segment"] == "김천공장" and r["metric"] == "utilization"]
    assert real_util and real_util[0]["value"] == 89.6


def test_sgworld_financial_summary_table_dropped():
    """부문별 재무요약표(매출액/순이익(손실)/총자산/부채)가 utilization 으로 새면 안 되지만,
    같은 파일의 진짜 생산표(의류수출/SSV 등 capacity)는 살아있어야 함."""
    if not _SGWORLD.exists():
        return
    rows = _rows(_SGWORLD, "00133511", 2017)
    assert not any(r["item"] and "순이익" in str(r["item"]) for r in rows)
    assert any(r["metric"] == "capacity" and r["segment"] == "의류수출" for r in rows)


def test_hyundaihims_ppe_rollforward_dropped():
    """유형자산 취득원가/감가상각 롤포워드표(기초/취득/처분/기말)가 '제N기' 기간헤더를 갖고
    있어 생산열 필터를 통과해버리는 것 차단. period_year 이상치(2028) 잔존 금지."""
    if not _HYUNDAIHIMS.exists():
        return
    rows = _rows(_HYUNDAIHIMS, "00667373", 2025)
    assert not any(r["period_year"] and (r["period_year"] > 2027 or r["period_year"] < 1990) for r in rows)
    assert not any(r["segment"] in ("기초", "취득원가") for r in rows)


def test_lotte_em_commitment_disclosure_dropped():
    """특수관계자 투자약정 공시("약정 금액")가 생산데이터로 새면 안 됨."""
    if not _LOTTE_EM.exists():
        return
    rows = _rows(_LOTTE_EM, "00113997", 2024)
    assert not any(r["segment"] == "약정 금액" for r in rows)


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
