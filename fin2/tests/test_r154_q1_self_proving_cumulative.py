"""R154(2026-09-21) 회귀 테스트 — Q1 표가 **스스로 증명한** 3개월 = 누적 등식을 읽어,
누적 칸이 공란인 EPS 행이 통째로 사라지던 결함.

R116 은 같은 상황(Q1 인데 누적 칸 공란)을 rcept 예외목록으로만 좁혀 처리했다. 그 이유는
"실측이 두 필링에서만 확인됐다"였지 등식이 의심스러워서가 아니다 — 1분기는 정의상
연초부터 분기말까지의 누적이 곧 그 3개월 자체다.

예외목록은 같은 서식을 쓰는 다른 회사·연도를 계속 흘린다. 실측: 기아 20240516001819
(2024Q1) 연결·별도 IS 에서 기본주당이익이 통째로 결측이었다(camp_run 캠페인 이슈#20).
그 표는 EPS 행만 누적 칸이 공란이고 **나머지 전 행이 3개월과 누적에 똑같은 값을 적어
등식을 스스로 증명**한다:

    매출액       26,212,851 | 26,212,851 | 23,690,660 | 23,690,660
    기본주당이익       7,125 |     (공란) |      5,323 |     (공란)   ← 유실

★이 판정은 R6("서로 다른 값 중 하나를 짐작하지 않는다")를 거스르지 않는다 — 짐작이
아니라 필링 자신이 적어 둔 등식을 읽는 것이다. 반례가 하나라도 있으면 즉시 거짓.

실행: pytest fin2/tests/test_r154_q1_self_proving_cumulative.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest                                                     # noqa: E402

import fin2.extract.report_lines as report_lines                  # noqa: E402
from fin2.extract.report_lines import (                           # noqa: E402
    _q1_cumulative_proved_equal_to_three_month as _proved,
    extract_report_lines,
)
from parser.xml.table_extractor import HeaderColumn               # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
_KIA_2024Q1 = _ROOT / "raw_report/KOSPI/00106641_기아/quarter/2024/20240516001819.xml"


def _cols():
    """[3개월, 누적, 3개월, 누적] — 기아 표와 같은 모양."""
    return [
        HeaderColumn(position=0, period_key="당기", period_rank=0,
                     subtype="three_month", is_note=False),
        HeaderColumn(position=1, period_key="당기", period_rank=0,
                     subtype="cumulative", is_note=False),
        HeaderColumn(position=2, period_key="전기", period_rank=1,
                     subtype="three_month", is_note=False),
        HeaderColumn(position=3, period_key="전기", period_rank=1,
                     subtype="cumulative", is_note=False),
    ]


class _Row:
    def __init__(self, amounts):
        self.amounts = amounts


# ───────────────────────────── 증거 판정 자체 ──────────────────────────────

def test_table_that_repeats_the_same_value_proves_the_equality():
    rows = [_Row([100, 100, 90, 90]), _Row([50, 50, 40, 40])]
    assert _proved(_cols(), rows) is True


def test_a_single_counterexample_disables_the_rule():
    """3개월 ≠ 누적인 행이 하나라도 있으면 그 표는 이 축이 아니다."""
    rows = [_Row([100, 100, 90, 90]), _Row([50, 77, 40, 40])]
    assert _proved(_cols(), rows) is False


def test_rows_with_a_blank_side_are_not_witnesses():
    """한쪽이 공란인 행(= 구제 대상)은 스스로를 증명할 수 없다."""
    assert _proved(_cols(), [_Row([100, None, 90, None])]) is False


def test_no_subtype_header_is_out_of_scope():
    """구분 텍스트 없는 병합군은 R131/R120 의 축이지 이 규칙의 축이 아니다."""
    cols = [HeaderColumn(position=i, period_key="당기", period_rank=0,
                         subtype=None, is_note=False) for i in range(2)]
    assert _proved(cols, [_Row([100, 100])]) is False


def test_empty_inputs_are_false():
    assert _proved([], [_Row([1, 1])]) is False
    assert _proved(_cols(), []) is False


# ─────────────────────────── 실제 필링 원문 대조 ───────────────────────────

@pytest.mark.skipif(not _KIA_2024Q1.exists(), reason="원문 XML 없음")
def test_kia_2024q1_eps_rows_are_recovered():
    """camp_run 이슈#20 — 원문 네 값이 그대로 복원되는지."""
    lines = extract_report_lines(
        str(_KIA_2024Q1), rcept_no="20240516001819", corp_code="00106641",
        report_fiscal_year=2024, report_fiscal_period="Q1")
    eps = {(l.basis, l.col_index): l.value_won for l in lines
           if l.statement == "IS" and "주당" in (l.label_raw or "")}
    assert eps.get(("consolidated", 0)) == 7125
    assert eps.get(("consolidated", 1)) == 5323
    assert eps.get(("separate", 0)) == 5495
    assert eps.get(("separate", 1)) == 2251


@pytest.mark.skipif(not _KIA_2024Q1.exists(), reason="원문 XML 없음")
def test_kia_2024q1_ordinary_rows_are_unchanged():
    """구제 규칙이 일반 행 값을 건드리지 않는지(누적 칸이 원래 차 있던 행)."""
    lines = extract_report_lines(
        str(_KIA_2024Q1), rcept_no="20240516001819", corp_code="00106641",
        report_fiscal_year=2024, report_fiscal_period="Q1")
    sales = {(l.basis, l.col_index): l.value_won for l in lines
             if l.statement == "IS" and (l.label_raw or "").strip() == "매출액"}
    assert sales.get(("consolidated", 0)) == 26_212_851_000_000
    assert sales.get(("separate", 0)) == 15_711_802_000_000


def test_both_paths_receive_the_same_flag():
    """본류와 EPS 경로에 **같은** 표 단위 판정이 넘어가는지(R144/R153 교훈).

    상수/인자 이름이 바뀌면 조용히 깨지므로 배선 자체를 소스에서 확인한다.
    """
    src = Path(report_lines.__file__).read_text(encoding="utf-8")
    assert "q1_cum_blank_use_3m=q1_cum_blank_use_3m" in src
    eps_fn = src.split("def _emit_eps_lines", 1)[1].split("\ndef ", 1)[0]
    assert "q1_cum_blank_use_3m" in eps_fn
