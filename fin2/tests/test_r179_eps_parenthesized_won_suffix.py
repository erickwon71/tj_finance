"""R179(2026-09-26) 회귀 테스트 — 음수(손실) EPS 셀이 '원' 단위까지 괄호 안에 감싼
`'(89원)'` 표기를 `parse_amount()` 가 못 읽어 행이 통째로 결측되던 결함.

R149(2026-09-20)가 `'2,564원'`·`'(2,564)원'`(원이 괄호 밖)은 잡았지만, 음수 표기
자체가 '원'까지 감싼 `'(89원)'`(원이 괄호 **안**)은 정규식이 문자열 끝을 '원'으로
요구해 매치되지 않았다. 실측: SK스퀘어 2021FY 사업보고서(20220317000691) [별도]
손익계산서 'Ⅶ.주당손실 / 기본 및 희석주당순손실 (89원)' 행이 통째로 결측(캠페인
이슈#17, #16(신한지주)과 같은 결함 클래스로 보고됐으나 이 하위 케이스는 미수정 상태였음).

실행: pytest fin2/tests/test_r179_eps_parenthesized_won_suffix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.report_lines import extract_report_lines      # noqa: E402
from parser.common.amount_normalizer import parse_amount        # noqa: E402

_SK_SQUARE_2021FY = (
    Path(__file__).resolve().parents[2]
    / "raw_report/KOSPI/01596425_SK스퀘어/annual/2021/20220317000691.xml"
)


def test_parenthesized_negative_with_won_inside_parens():
    """'원'이 닫는 괄호 **안**에서 끝나도 매치한다 — R149 는 괄호 밖('(2,564)원')만 잡았다."""
    assert parse_amount("(89원)", 1) == -89
    assert parse_amount("(89원)", 1_000_000) == -89          # ★배수 무시(R149 와 동일 원칙)
    assert parse_amount("(1,234,567원)", 1_000_000) == -1234567


def test_r149_existing_forms_unaffected():
    """R149 가 이미 잡던 형태(원이 괄호 밖, 또는 괄호 없음)는 그대로 동작한다(회귀 가드)."""
    assert parse_amount("2,564원", 1_000_000) == 2564
    assert parse_amount("(2,564)원", 1) == -2564
    assert parse_amount("1,234천원", 1) is None              # 배수 포함 접미사는 여전히 미처리


def test_sk_square_2021fy_separate_eps_loss_row_recovered():
    """SK스퀘어 [별도] IS 의 '기본 및 희석주당순손실' 행이 결측에서 복원된다."""
    if not _SK_SQUARE_2021FY.exists():
        return
    lines = extract_report_lines(
        _SK_SQUARE_2021FY, rcept_no="20220317000691", corp_code="01596425",
        report_fiscal_year=2021, report_fiscal_period="FY",
    )
    eps = [l for l in lines if l.basis == "separate" and l.statement == "IS"
           and "주당" in (l.label_raw or "")]
    assert eps, "[별도] IS 주당손실 행이 여전히 결측"
    assert any(l.value_won == -89 for l in eps), \
        f"기본 및 희석주당순손실 -89원이 없음: {[(l.label_raw, l.value_won) for l in eps]}"
