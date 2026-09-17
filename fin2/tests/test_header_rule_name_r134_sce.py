"""`parser/xml/table_extractor.py::_header_rule_name` R134 회귀 테스트 (2026-09-16).

SCE(자본변동표) 기초/기말 잔액 행 라벨이 "2014.04.01 (제26기 분기초)"처럼 날짜에
"제N기"까지 붙는 경우, 기존 "기수" 규칙(R28 — "원"/"%" 없으면 헤더로 판정)이
allow_date_label=True(SCE 전용) 상태에서도 계속 걸려 앵커 행 전체(모든 열)가
드롭됐다. 메이슨캐피탈 20150817001754 원문대조로 확정 — 자본금/자본잉여금/
자기주식 열 및 "2014.04.01 (제26기 분기초)"·"2014.06.30 (제26기 분기말)" 행이
report_lines 에서 통째로 유실돼 있었다.

실행: pytest fin2/tests/test_header_rule_name_r134_sce.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xml.table_extractor import _header_rule_name  # noqa: E402

# 실측(메이슨캐피탈 20150817001754 원문) — SCE 기초/기말 앵커 행. allow_date_label=True
# (SCE 전용 호출)에서는 데이터 행으로 살아남아야 한다(header_hint=None).
_SCE_ANCHOR_ROWS = [
    "2014.04.01 (제26기 분기초)",
    "2014.06.30 (제26기 분기말)",
    "2015.04.01 (제27기 분기초)",
    "2018.09.30 (기말자본)",          # "제N기" 없는 기존 정상 케이스도 계속 통과해야 함
    "2019.01.01 (기초자본)",
]


def test_sce_anchor_rows_not_dropped_when_allow_date_label():
    """allow_date_label=True(SCE 전용 호출)면 '제N기' 포함 앵커 행도 헤더로 안 잡힌다."""
    for text in _SCE_ANCHOR_ROWS:
        assert _header_rule_name(text, allow_date_label=True) is None, (
            f"SCE 앵커 행이 여전히 헤더로 드롭됨: {text!r}")


def test_giki_rule_unaffected_outside_sce():
    """allow_date_label=False(BS/IS/CF·주석 기본 경로)에서는 R28 '기수' 규칙이 그대로
    남아있어야 한다 — R134 는 SCE 전용 가드만 추가한다."""
    assert _header_rule_name("제59기 기초(2016.1.1)") == "기수"
    assert _header_rule_name("2014.04.01 (제26기 분기초)") == "기수"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
