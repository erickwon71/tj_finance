"""
B1(→B4) 수주상황 추출 회귀 테스트(실측 파일, DB 비의존).

실측 6사(2026-07-05) — 3개 구조유형:
  집계형: 삼성중공업(품목별 소수행)·한화시스템(사업부문별).
  프로젝트 상세형(계약잔액 명시 → 합산): 현대건설·GS건설.
  진행률형(계약잔액 없이 진행률%만 → 1차 범위 밖, 자연 스킵): 대우건설(수주계약현황)·한화오션.
  (대우건설은 "수주상황(요약)" 표도 있어 완전 0행은 아니고, 그 요약표에서 집계형 값이 나옴.)

실행: python -m fin2.tests.test_order_backlog
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.order_backlog import parse_order_backlog  # noqa: E402

_BASE = Path(__file__).resolve().parents[2]
_SAMSUNG_HI = _BASE / "raw_report/KOSPI/00126478_삼성중공업/annual/2025/20260312001037.xml"
_HANWHA_SYS = _BASE / "raw_report/KOSPI/00339391_한화시스템/annual/2025/20260513000644.xml"
_HYUNDAI_ENG = _BASE / "raw_report/KOSPI/00164478_현대건설/annual/2025/20260318001395.xml"
_GS_ENG = _BASE / "raw_report/KOSPI/00120030_GS건설/annual/2025/20260701000624.xml"
_HANWHA_OCEAN = _BASE / "raw_report/KOSPI/00111704_한화오션/annual/2025/20260317000644.xml"
_DAEWOO_ENG = _BASE / "raw_report/KOSPI/00124540_대우건설/annual/2025/20260318001029.xml"
# 100사 표본 스윕(2026-07-05)으로 발견한 3종 추가 회귀.
_LS_HOLDING = _BASE / "raw_report/KOSPI/00105952_LS/annual/2025/20260318001427.xml"          # 합계행 이중집계
_WISEAI = _BASE / "raw_report/KOSDAQ/00374738_위세아이텍/annual/2025/20260320000390.xml"      # 계약금액/수익인식액/진행률%
_KC_COTTRELL = _BASE / "raw_report/KOSPI/00797364_KC코트렐/annual/2025/20260407003641.xml"     # 환종별 롤포워드
# 전수백필(2,555사) 실행 중 실측 발견(2026-07-05): 회사명 컬럼 헤더에 "단위" 글자가 우연히
# 포함("회사명(단위)")돼 그 컬럼 전체가 단위열로 오인 → 회사명 셀값(22자)이 unit(varchar(20))
# 에 들어가려다 DB insert 크래시 + 진짜 카테고리(회사명) 통째 소실.
_PUNGSAN = _BASE / "raw_report/KOSPI/00155531_풍산홀딩스/annual/2025/20260312001433.xml"
# 전수백필 이상치 트리아지(2026-07-05)로 발견한 2종 추가 회귀.
_JEIO = _BASE / "raw_report/KOSDAQ/00411808_제이오/annual/2025/20260323000393.xml"              # 완성공사액 당기(누적)
_NKMAX_GEN = _BASE / "raw_report/KOSDAQ/00977650_엔케이젠바이오텍코리아/annual/2025/20260324000530.xml"  # rowspan 밀림


def _rows(fp, corp, fy):
    return parse_order_backlog(fp, corp, fy)


def test_samsung_hi_aggregate_identity():
    """집계형 — 품목별 행 + 합계행. 수주총액-기납품액=수주잔고 항등식, 날짜열 라벨오염 없음."""
    if not _SAMSUNG_HI.exists():
        return
    rows = _rows(_SAMSUNG_HI, "00126478", 2025)
    assert len(rows) == 3
    total = next(r for r in rows if r["category"] and r["category"].replace(" ", "") == "합계")
    assert total["new_orders"] - total["completed"] == total["backlog_amt"]
    assert total["backlog_amt"] == 280305
    # 날짜열("수주일자"/"납기")이 category 라벨에 섞이면 안 됨.
    assert not any(r["category"] and ("~" in r["category"] or "2025.12" in r["category"]) for r in rows)
    assert all(r["unit"] == "억원" for r in rows), "표 앞 '(단위 : 억원)' 안내문 캡처 필요"


def test_hanwha_system_unit_differs_from_samsung():
    """단위는 회사마다 다르다(삼성중공업=억원, 한화시스템=백만원) — 캡처 안 하면 스케일 오독."""
    if not _HANWHA_SYS.exists():
        return
    rows = _rows(_HANWHA_SYS, "00339391", 2025)
    assert all(r["unit"] == "백만원" for r in rows)


def test_hanwha_system_segment_breakdown():
    """집계형 — 사업부문별(방산/ICT/기타) + 합계. 합계=부문합과 근사 일치."""
    if not _HANWHA_SYS.exists():
        return
    rows = _rows(_HANWHA_SYS, "00339391", 2025)
    assert len(rows) == 4
    total = next(r for r in rows if r["category"] and r["category"].startswith("합"))
    segs = [r for r in rows if r is not total]
    assert sum(r["backlog_amt"] for r in segs) == total["backlog_amt"]


def test_hyundai_eng_detail_table_aggregated():
    """프로젝트 상세형 — 계약잔액 명시 컬럼 있음. 많은 행(>10)은 회사 합산 1행으로 축약됨을
    간접 확인(개별 프로젝트명이 아닌 None-category 합산행이 존재)."""
    if not _HYUNDAI_ENG.exists():
        return
    rows = _rows(_HYUNDAI_ENG, "00164478", 2025)
    assert any(r["category"] is None for r in rows), "상세형 합산행(카테고리 없음)이 있어야 함"
    for r in rows:
        assert r["backlog_amt"] is not None and r["backlog_amt"] >= 0


def test_gs_eng_detail_table_total_identity():
    """프로젝트 상세형(GS건설) — 합산 후 항등식(수주총액-완성공사액=계약잔액 근사)."""
    if not _GS_ENG.exists():
        return
    rows = _rows(_GS_ENG, "00120030", 2025)
    assert rows
    for r in rows:
        if r["new_orders"] is not None:
            assert abs((r["new_orders"] - r["completed"]) - r["backlog_amt"]) < 10


def test_hanwha_ocean_progress_only_table_skipped():
    """진행률형(계약잔액 없이 진행률%만) — 낮은신뢰도라 1차 범위 밖, 빈 결과여야 함."""
    if not _HANWHA_OCEAN.exists():
        return
    rows = _rows(_HANWHA_OCEAN, "00111704", 2025)
    assert rows == []


def test_daewoo_eng_summary_table_used_detail_skipped():
    """대우건설 — "수주상황(요약)" 집계표는 채택하고, "수주계약 현황"(진행률형) 상세표는
    스킵(낮은 신뢰도) → 결과는 집계형 값만 남아야 함(수십~수백 개별 프로젝트 행 없음)."""
    if not _DAEWOO_ENG.exists():
        return
    rows = _rows(_DAEWOO_ENG, "00124540", 2025)
    assert rows, "수주상황(요약) 집계표는 있어야 함"
    assert len(rows) <= 5, "진행률형 상세표(수십~수백행)까지 채택되면 안 됨"


def test_ls_holding_existing_total_row_not_double_counted():
    """LS(지주) — 부문별 11행 + 이미 계산된 "합계" 1행(총12행, 상세형 임계 초과). 전부 다시
    합산하면 합계행까지 더해져 2배로 부풀려짐(149,834→299,668) — 기존 합계행을 그대로 채택해야 함."""
    if not _LS_HOLDING.exists():
        return
    rows = _rows(_LS_HOLDING, "00105952", 2025)
    assert len(rows) == 1
    assert rows[0]["backlog_amt"] == 149834, rows[0]


def test_wiseai_contract_amount_and_revenue_recognized_synonyms():
    """위세아이텍 — "계약금액"(수주총액 아님)·"수익인식액"(기납품 아님)·"계약종료일"(날짜)·
    "진행률"(%) 표기 변이. 계약명에 날짜/퍼센트/숫자 오염 없이 총액·완료액 모두 채워져야 함."""
    if not _WISEAI.exists():
        return
    rows = _rows(_WISEAI, "00374738", 2025)
    assert rows
    r0 = rows[0]
    assert r0["category"] == "국회사무처 차세대 e의안시스템 구축"
    assert r0["new_orders"] == 2358101 and r0["completed"] == 1179051 and r0["backlog_amt"] == 1179050


def test_kc_cottrell_rollforward_currency_table():
    """환종별 롤포워드표(기초계약잔액/당기신규·변동/당기공사수익/기말계약잔액) — "당기 XX"
    미분류열이 category 에 안 새고(순수 통화코드만), backlog 는 기말(마지막 매치) 값 채택."""
    if not _KC_COTTRELL.exists():
        return
    rows = _rows(_KC_COTTRELL, "00797364", 2025)
    assert {r["category"] for r in rows} == {"KRW", "USD", "EUR", "INR", "TWD"}
    krw = next(r for r in rows if r["category"] == "KRW")
    assert krw["backlog_amt"] == 16603919


def test_pungsan_company_name_column_not_misdetected_as_unit():
    """"회사명(단위)" 헤더가 "단위" substring 매칭으로 단위열 오인되면 안 됨 — unit 은 20자
    이하(DB varchar(20) 크래시 회귀)여야 하고, 회사명 라벨은 살아있되 "(단위:...)" 주석은
    제거된 상태여야 함."""
    if not _PUNGSAN.exists():
        return
    rows = _rows(_PUNGSAN, "00155531", 2025)
    assert rows
    assert all((r["unit"] or "") and len(r["unit"]) <= 20 or r["unit"] is None for r in rows)
    assert not any(r["category"] and "단위" in r["category"] for r in rows)
    assert not any(r["category"] is None and r["backlog_amt"] == 0 for r in rows)


def test_jeio_completed_prefers_cumulative_in_parens():
    """완성공사액 셀이 "29,961,564(72,900,381)"(당기(누적)) 형태 — 계약잔액 계산엔 괄호 안
    누적값이 쓰이므로(기본도급액-누적완성공사액=계약잔액 정확 성립) 그 값을 채택해야 함."""
    if not _JEIO.exists():
        return
    rows = _rows(_JEIO, "00411808", 2025)
    domestic = next(r for r in rows if r["category"] and "국내" in r["category"])
    assert domestic["completed"] == 72900381, domestic
    assert domestic["new_orders"] - domestic["completed"] == domestic["backlog_amt"]


def test_nkmax_gencorea_malformed_row_dropped():
    """원본 문서의 rowspan 이상(품목 셀이 3칸에 걸쳐 중복)으로 데이터가 밀려 납기일자가
    수주총액으로 오파싱(→2032)되는 행 — backlog>total 불변식 위반으로 폐기돼야 함(다른
    정상 행·소스 자체 합계행은 살아있어야 함)."""
    if not _NKMAX_GEN.exists():
        return
    rows = _rows(_NKMAX_GEN, "00977650", 2025)
    assert not any(r["new_orders"] is not None and r["new_orders"] < 10000 for r in rows), \
        "납기연도(2032 등)가 수주총액으로 오파싱된 행이 남아있으면 안 됨"
    assert any(r["category"] and r["category"].strip().startswith("합") for r in rows)


def _run():
    files = [_SAMSUNG_HI, _HANWHA_SYS, _HYUNDAI_ENG, _GS_ENG, _HANWHA_OCEAN, _DAEWOO_ENG]
    if not any(f.exists() for f in files):
        print("  - SKIP: 실측 파일 없음")
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
