"""R148(2026-09-20) 회귀 테스트 — 자본변동표가 페이지 폭 제약으로 표지 문구조차 없이
물리적 <TABLE> 2개로 분할되는 서식에서, 뒤쪽(당기 롤포워드) 표가 통째로 유실되던
결함.

R142(is_substatement_marker)와 달리 뒤쪽 표에 "(N) ...재무제표(기간)" 같은 최소한의
텍스트 표지조차 없다 — 앞 표 마지막 행 바로 다음에 새 <TABLE>이 시작하고, 자기
THEAD 에 SCE 열이름(자본금/자본잉여금/이익잉여금 등)을 그대로 반복할 뿐이다. 텍스트
표지가 없으므로 표 내용(`_looks_like_equity_changes_header`, R127 이 이미 쓰던 판정
근거)만으로 직전 statement(SCE)를 물려받는다.

실측: 신한지주 20220316000748(2021FY) — [연결]/[별도] 자본변동표 당기(2021) 롤포워드
구간 전체가 이 서식 때문에 유실됐었다(layer2 review campaign 원문전체대조 이슈#7).

실행: pytest fin2/tests/test_r148_headerless_sce_continuation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines  # noqa: E402

_SHINHAN_2021FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/00382199_신한지주/annual/2021/20220316000748.xml"
)


def test_shinhan_2021fy_sce_current_period_rollforward_recovered():
    """당기(2021년 12월 31일) 롤포워드 행이 더 이상 유실되지 않고, DART 원문 그대로의
    자본총계(재무상태표 자본총계와 정합)를 갖는다."""
    if not _SHINHAN_2021FY.exists():
        return
    lines = extract_report_lines(
        _SHINHAN_2021FY, rcept_no="20220316000748", corp_code="00382199",
        report_fiscal_year=2021, report_fiscal_period="FY",
    )
    sce = [l for l in lines if l.statement == "SCE"]

    for basis, expected_total in (("consolidated", 49_538_422_000_000),
                                  ("separate", 26_405_376_000_000)):
        rollforward = [l for l in sce if l.basis == basis and l.table_seq == 1]
        assert rollforward, f"{basis} SCE 당기 롤포워드 표(table_seq=1)가 여전히 유실됨(R148 회귀)"
        last_label = max(rollforward, key=lambda l: l.row_order).label_raw
        total = [l for l in rollforward
                 if l.label_raw == last_label and (l.col_label or "").replace(" ", "") == "총계"]
        assert total, f"{basis} 마지막 행({last_label!r})에서 총계 열을 못 찾음"
        assert total[0].value_won == expected_total

    # 이전 구간(table_seq=0, 2019→2020)은 그대로 남아 있어야 한다(가산적 수정 확인).
    for basis in ("consolidated", "separate"):
        prior = [l for l in sce if l.basis == basis and l.table_seq == 0]
        assert prior, f"{basis} SCE 이전 구간(table_seq=0)이 이 수정으로 사라짐"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
