"""Enforcement tests for docs/PARSING_RULES.md R0 / R2-0.

R0: read the document as it is — parse what a filing contains, skip what it does not.
    A missing part is never an error, and must never make a whole period unparseable.

These are guard rails, not behaviour tests: they exist so a future parser cannot quietly
reintroduce the defect that cost 547 filings / 447 companies (measured 2026-07-31).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from collector.biz_merge import caption_of, item_key, merge_filings

ROOT = Path(__file__).resolve().parents[1]

# Modules that pick which report files get parsed and loaded. Audit/probe scripts are excluded:
# narrowing a *sample* by is_final is fine, narrowing a *load* by it is not.
_LOADER_PATHS = [
    "collector/biz_metrics.py",
    "collector/order_backlog.py",
    "collector/note_lines_sync.py",
    "collector/filing_select.py",
    "scripts/nightly_gap_fill_backfill.py",
    "scripts/phase_c_rebuild.py",
]

_IS_FINAL_FILTER = re.compile(r"is_final\s*=\s*TRUE|is_final\s*=\s*true|AND\s+f\.is_final\b",
                              re.IGNORECASE)


@pytest.mark.parametrize("rel", _LOADER_PATHS)
def test_loader_does_not_filter_sources_by_is_final(rel):
    """R2-0: is_final marks 'newest in the group', not 'complete'.

    An [첨부정정] carries no report body at all (measured: 0% of 4 sampled) yet takes the flag,
    so filtering sources by it silently drops the filings that DO have a body.
    """
    src = (ROOT / rel).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    hits = [ln.strip() for ln in code.splitlines() if _IS_FINAL_FILTER.search(ln)]
    assert not hits, (
        f"{rel}: 적재 소스를 is_final 로 거르면 안 된다 (PARSING_RULES.md R2-0)\n  " +
        "\n  ".join(hits))


class TestChronologicalMerge:
    """R0: later filings override the items they re-file; untouched items survive."""

    @staticmethod
    def _filing(rcept, caption, items):
        sec = [{"corp_code": "c", "fiscal_year": 2024, "table_ord": 0,
                "metric": "product_status", "narrative": caption, "grid": [[""]],
                "n_metric_rows": len(items)}]
        met = [{"corp_code": "c", "fiscal_year": 2024, "table_ord": 0,
                "metric": "product_status", "segment": seg, "item": None,
                "period_label": "제1기", "period_year": 2024, "value": val,
                "unit": None, "is_ratio": False, "channel": None}
               for seg, val in items]
        return (rcept, sec, met)

    def test_amendment_overrides_only_what_it_carries(self):
        """원본 3항목 → 정정본이 그중 1개만 다시 냄. 결과는 3항목, 1개만 갱신."""
        original = self._filing("R1", "가. 주요 제품", [("A", 10), ("B", 20), ("C", 30)])
        amendment = self._filing("R2", "가. 주요 제품", [("B", 99)])

        _, merged, stats = merge_filings([original, amendment])
        got = {m["segment"]: (m["value"], m["rcept_no"]) for m in merged}

        assert got["A"] == (10, "R1"), "정정본이 안 건드린 항목은 원본 값이 남아야 한다"
        assert got["C"] == (30, "R1")
        assert got["B"] == (99, "R2"), "정정본이 다시 낸 항목은 덮어써야 한다"
        assert stats["overridden"] == 1 and stats["new"] == 3

    def test_partial_amendment_never_truncates(self):
        """정정본이 일부만 담고 있어도 나머지가 사라지면 안 된다 (사용자 예: 50행 → 30행)."""
        original = self._filing("R1", "손익", [(f"L{i}", i) for i in range(50)])
        amendment = self._filing("R2", "손익", [(f"L{i}", 1000 + i) for i in range(30)])

        _, merged, _ = merge_filings([original, amendment])
        assert len(merged) == 50, "정정본 행 수가 최종이 되면 안 된다"
        by_seg = {m["segment"]: m["value"] for m in merged}
        assert by_seg["L0"] == 1000 and by_seg["L29"] == 1029    # 갱신된 30개
        assert by_seg["L30"] == 30 and by_seg["L49"] == 49       # 원본에 남은 20개

    def test_filing_without_the_section_is_skipped_not_fatal(self):
        """그 부분이 없는 보고서는 그냥 건너뛴다 — 오류가 아니고, 앞 내용을 지우지도 않는다."""
        original = self._filing("R1", "가. 주요 제품", [("A", 10)])
        attachment_only = ("R2", [], [])          # [첨부정정]: 본문 없음

        _, merged, stats = merge_filings([original, attachment_only])
        assert len(merged) == 1 and merged[0]["value"] == 10
        assert stats["filings"] == 2

    def test_repeated_identity_is_kept_not_dropped(self):
        """★ 한 보고서 안에서 식별자가 겹치는 행을 버리면 구 적재 방식보다 데이터가 준다.

        실측(25사 415기간): 파싱 원행의 **21.9%** 가 식별자 반복이고, 어떤 기간은 60%↑였다.
        반복은 중복이 아니라 순번으로 구분해야 한다.
        """
        # 같은 (metric, 캡션, segment, item, period_label) 을 갖는 행 3개
        dup = self._filing("R1", "가. 설비", [("서울", 1), ("서울", 2), ("서울", 3)])
        _, merged, stats = merge_filings([dup])
        assert len(merged) == 3, "반복 식별자를 버리면 안 된다"
        assert sorted(m["value"] for m in merged) == [1, 2, 3]
        assert stats["repeated_identity"] == 2

    def test_merge_never_loses_rows_versus_single_filing(self):
        """단일 보고서만 있는 기간은 병합 결과가 파싱 원행과 정확히 같아야 한다."""
        only = self._filing("R1", "가. 제품", [("A", 1), ("A", 1), ("B", 2), ("B", 3)])
        _, merged, _ = merge_filings([only])
        assert len(merged) == len(only[2])

    def test_repeats_align_positionally_across_filings(self):
        """정정본도 같은 구조로 다시 내므로 n번째 반복끼리 짝이 맞아야 한다."""
        original = self._filing("R1", "가. 설비", [("서울", 1), ("서울", 2)])
        amendment = self._filing("R2", "가. 설비", [("서울", 10), ("서울", 20)])
        _, merged, stats = merge_filings([original, amendment])
        assert len(merged) == 2, "정정본이 행을 늘리면 안 된다"
        assert sorted(m["value"] for m in merged) == [10, 20]
        assert stats["overridden"] == 2

    def test_same_caption_different_tables_do_not_collide(self):
        """캡션이 식별에 포함돼야 서로 다른 표의 같은 라벨이 뭉개지지 않는다."""
        a = {"metric": "facility", "segment": "토지", "item": None, "period_label": "장부가"}
        assert item_key(a, "가.국내생산설비") != item_key(a, "나.해외생산설비")

    def test_caption_whitespace_is_normalised(self):
        """정정본이 재조판하며 공백만 바꾸는 일이 흔하다 — 같은 표로 봐야 한다."""
        assert caption_of({"narrative": "(20명× 1,920H )"}) == caption_of({"narrative": "(20명×1,920H)"})
