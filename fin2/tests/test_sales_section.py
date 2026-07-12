"""
Phase 3(PRD 14) 부문·수출/내수 매출실적 본문표 추출 회귀 테스트(실측 파일, DB 비의존).

실측 4사(2026-07-12 캘리브레이션):
  삼성전자(00126380) 2024 — 부문별(채널 없음→합계) + 지역별(내수/수출 채널열).
  S-Oil(00138279)   2024 — 부문·품목·채널(수출/내수/합계) 3차원 + 뒤따르는 수주잔고표 배제.
  한온시스템(00161125) 2025 — 지역 sub-dim + 비율(%) 열 제외 + 음수괄호 단위 오염 없음.
  유한양행(00145109) 2025 — 제약 제품별 내수/수출.

실행: python -m fin2.tests.test_sales_section
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.sales_section import parse_sales_metrics  # noqa: E402

_BASE = Path(__file__).resolve().parents[2]
_SAMSUNG = _BASE / "raw_report/KOSPI/00126380_삼성전자/annual/2024/20250311001085.xml"
_SOIL = _BASE / "raw_report/KOSPI/00138279_S-Oil/annual/2024/20250319000503.xml"
_HANON = _BASE / "raw_report/KOSPI/00161125_한온시스템/annual/2025/20260318000645.xml"
_YUHAN = _BASE / "raw_report/KOSPI/00145109_유한양행/annual/2025/20260312001236.xml"


def _rows(fp, corp, fy):
    _, met = parse_sales_metrics(fp, corp, fy)
    return met


def _find(rows, **kw):
    return [r for r in rows if all(r.get(k) == v for k, v in kw.items())]


def test_samsung_segment_total_channel():
    """부문별 매출표(채널 열 없음) → channel='합계', 부문별 값 정확(제56기=2024)."""
    rows = _rows(_SAMSUNG, "00126380", 2024)
    dx = _find(rows, metric="sales", segment="DX 부문", channel="합계", period_year=2024)
    assert dx and dx[0]["value"] == 1_748_877, dx
    assert dx[0]["unit"] == "억원", dx


def test_samsung_region_export_domestic_channel():
    """지역별 매출현황표('구분' 채널열=내수/수출) → 채널 분리. 내수(국내) 값 정확."""
    rows = _rows(_SAMSUNG, "00126380", 2024)
    dom = _find(rows, metric="sales", channel="내수", period_year=2024)
    assert dom and any(r["value"] == 202_978 for r in dom), dom
    exp = _find(rows, metric="sales", channel="수출", period_year=2024)
    assert exp, "수출 채널 행이 있어야 함"
    # 수출 합 > 내수 합(삼성은 수출 주도).
    assert sum(r["value"] for r in exp) > sum(r["value"] for r in dom)


def test_soil_segment_item_channel_three_dim():
    """부문·품목·채널 3차원 → 정유부문·휘발유의 수출/내수/합계 값 정확(제50기=2024)."""
    rows = _rows(_SOIL, "00138279", 2024)
    def val(ch):
        r = _find(rows, metric="sales", segment="정유부문", item="휘발유",
                  channel=ch, period_year=2024)
        return r[0]["value"] if r else None
    assert val("수출") == 3_876_733, rows[:3]
    assert val("내수") == 2_816_179
    assert val("합계") == 6_692_912
    assert abs(val("수출") + val("내수") - val("합계")) < 1e-6


def test_soil_order_backlog_table_not_captured():
    """'나. 판매경로' 뒤 수주잔고표(수주처/납기/수주총액)가 매출로 새면 안 됨(창 절단 + 가드)."""
    rows = _rows(_SOIL, "00138279", 2024)
    assert not any(r.get("segment") and any(k in r["segment"] for k in ("수주처", "Idemitsu", "Aramco"))
                   for r in rows), [r for r in rows if r.get("segment") and "수주" in str(r["segment"])]


def test_hanon_ratio_columns_excluded_and_unit_clean():
    """비율(%) 열은 매출값이 아니라 제외 + 음수 괄호값의 단위가 ')' 로 오염되지 않음."""
    rows = _rows(_HANON, "00161125", 2025)
    assert rows, "한온 매출행이 있어야 함"
    # 비율(%)이 값으로 새면 0~100 사이 작은 값이 다수 섞임 — 매출값은 모두 큰 금액.
    assert all(r["unit"] != ")" for r in rows), [r for r in rows if r["unit"] == ")"]
    # 지역 sub-dim(아시아/미주/유럽) 존재.
    assert any(r.get("item") in ("아시아", "미주", "유럽") for r in rows), rows[:3]


def test_yuhan_pharma_product_channel():
    """제약 제품별 내수/수출 채널 분리 — 약품사업부문 내수 제품행 존재."""
    rows = _rows(_YUHAN, "00145109", 2025)
    dom = _find(rows, metric="sales", segment="약품사업부문", channel="내수", period_year=2025)
    assert dom, "약품사업부문 내수 제품행이 있어야 함"
    # 대부분 양수 제품 매출(내부매출조정 같은 음수 소거행은 정상적으로 존재).
    assert any(r["value"] > 0 for r in dom)
    assert any(r["item"] == "안티푸라민" and r["value"] == 35_562 for r in dom), \
        [r for r in dom if r["item"] == "안티푸라민"]


def test_all_sales_rows_have_channel_and_no_ratio():
    """모든 매출행은 channel 세팅 + is_ratio=False(매출은 금액만)."""
    for fp, cc, fy in ((_SAMSUNG, "00126380", 2024), (_SOIL, "00138279", 2024),
                       (_HANON, "00161125", 2025), (_YUHAN, "00145109", 2025)):
        if not fp.exists():
            continue
        rows = _rows(fp, cc, fy)
        assert all(r["channel"] in ("수출", "내수", "합계", "기타") for r in rows), \
            [r for r in rows if r["channel"] not in ("수출", "내수", "합계", "기타")]
        assert all(r["is_ratio"] is False for r in rows)


def _run():
    if not _SAMSUNG.exists() or not _SOIL.exists():
        print(f"  - SKIP: 실측 파일 없음 {_SAMSUNG}")
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
