"""R398 - three more legacy statement-heading spellings.

(a) section head `1. 재무제표(K-IFRS)` glued before the statement name (Seoul Viosys 20140515000140 separate BS);
(b) a leading `별첨 재무제표에 대한 주석 참조` phrase glued before the title (same filing, separate IS);
(c) `(포괄)손익계산서` (Tovis-gen 20140814000319 separate IS).
"""
import pytest

from fin2.extract.statement_titles import classify_legacy_statement_heading as classify


@pytest.mark.parametrize("text,expected", [
    ("1. 재무제표(K-IFRS) 재 무 상 태 표 제13기 1분기 2014년 3월 31일 현재", ("separate", "BS")),
    ("1. 연결재무제표(K-IFRS) 연결재무상태표 제13기", ("consolidated", "BS")),
    ("별첨 재무제표에 대한 주석 참조 포 괄 손 익 계 산 서 제13기 1분기", ("separate", "IS")),
    ("나. (포괄)손익계산서", ("separate", "IS")),
    ("연결 (포괄)손익계산서 제 16 기 반기", ("consolidated", "IS")),
])
def test_accepted(text, expected):
    assert classify(text, True) == expected


@pytest.mark.parametrize("text", [
    "별첨 재무제표에 대한 주석 참조 입니다 현금흐름표는",
    "나. (포괄)손익계산서에 대한 설명은",
    "29. 현금흐름표",
])
def test_rejected(text):
    assert classify(text, True) is None
