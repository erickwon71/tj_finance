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
