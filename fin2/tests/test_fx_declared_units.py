"""외화 표시 재무제표(FX) 처리 회귀 테스트 (합성 XML, DB 비의존).

국내 기업이 **표시통화를 외화로** 쓰는 경우가 있다 — 실측 아남전자(008700)는 2019 사업연도부터
본문 8표 전부 `(단위 : USD)` 다. 종전에는 'USD' 에 원화 배수가 없어 표 전체가 보류됐고,
2019~2026 정기보고서 30건이 report_lines 0 행이었다. 숫자를 못 읽어서가 아니라 **통화를
표현할 방법이 없어서** 버린 것이다.

사용자 결정 2026-08-05 — 환산하지 않고 표시통화 금액 그대로 `value_won` 에 담고,
`unit_source='fx_declared'` 로 사실을 남긴다(통화 코드는 `report_tables.currency`).

⚠ 이 테스트가 지키는 두 경계:
  1. **원화 표는 절대 fx 로 넘어가면 안 된다**(오발동 = 조용한 오분류)
  2. **혼합 선언('1USD, 천원')은 FX_ONLY 가 아니다** — 그런 주석표는 원화 열만 적재되고
     외화 셀은 원문이 'USD 12,000,000' 처럼 통화 접두를 달아 금액으로 파싱되지 않는다.
     이미 올바르게 동작하므로 손대면 오히려 위험하다(실측 137,680표).

실행: python -m pytest fin2/tests/test_fx_declared_units.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.units import (  # noqa: E402
    ColumnUnits, FX_ONLY, MIXED, MONEY_ONLY, NON_MONEY_ONLY, SRC_FX,
    classify_tokens, fx_token,
)


# ── 1) 토큰 인식 ────────────────────────────────────────────────────────────

def test_fx_token_forms():
    assert fx_token("USD") == ("USD", 1)
    assert fx_token("(단위 : USD)".split(":")[-1].strip(" )")) == ("USD", 1)
    assert fx_token("천USD") == ("USD", 1_000)
    assert fx_token("천/USD") == ("USD", 1_000)
    assert fx_token("백만USD") == ("USD", 1_000_000)
    assert fx_token("EUR") == ("EUR", 1)
    assert fx_token("JPY") == ("JPY", 1)


def test_fx_token_rejects_krw_and_words():
    for tok in ("천원", "백만원", "원", "주", "%", "USDA", "달러"):
        assert fx_token(tok) is None, tok


# ── 2) 선언 분류 ────────────────────────────────────────────────────────────

def test_fx_only_classification():
    assert classify_tokens(["USD"]) == FX_ONLY
    assert classify_tokens(["천USD"]) == FX_ONLY


def test_krw_declarations_unchanged():
    """★오발동 방지 — 원화 선언은 종전 분류 그대로다."""
    assert classify_tokens(["천원"]) == MONEY_ONLY
    assert classify_tokens(["원"]) == MONEY_ONLY
    assert classify_tokens(["주", "%"]) == NON_MONEY_ONLY
    assert classify_tokens([]) != FX_ONLY


def test_mixed_declaration_is_not_fx():
    """★혼합 선언은 FX_ONLY 가 아니다 — 원화 열만 적재하는 기존 동작을 지킨다.

    실측 서식: '(단위: 1USD, 천원)' · '원화금액(단위 : 천원) 외화금액(단위 : 천/USD)'.
    이걸 FX 로 보면 원화 열까지 USD 로 표시돼 전부 틀린다.
    """
    assert classify_tokens(["1USD", "천원"]) == MIXED
    assert classify_tokens(["천원", "천USD"]) == MIXED
    assert classify_tokens(["천원", "USD", "JPY"]) == MIXED


# ── 3) ColumnUnits 통합 ─────────────────────────────────────────────────────

def test_column_units_fx_declaration():
    cu = ColumnUnits.from_declaration(
        "연결 재무상태표 제 47 기 2019.12.31 현재 (단위 : USD)",
        {0: "제 47 기", 1: "제 46 기"})
    assert cu.kind == FX_ONLY
    assert cu.currency == "USD"
    assert cu.multiplier(0) == 1          # 환산 아님 — 표시통화 스케일
    assert cu.source(0) == SRC_FX
    assert cu.has_money_column is True


def test_column_units_fx_with_scale():
    cu = ColumnUnits.from_declaration("(단위 : 천USD)", {0: "당기"})
    assert cu.kind == FX_ONLY and cu.currency == "USD"
    assert cu.multiplier(0) == 1_000      # 천USD → USD 1,000 단위


def test_column_units_krw_unaffected():
    cu = ColumnUnits.from_declaration("(단위 : 천원)", {0: "당기"})
    assert cu.kind == MONEY_ONLY
    assert cu.currency is None
    assert cu.multiplier(0) == 1_000
    assert cu.source(0) != SRC_FX


def test_mixed_declaration_column_behavior_unchanged():
    """혼합 선언에서 원화 열은 살고 외화/비금액 표지 열은 막힌다(종전 동작)."""
    cu = ColumnUnits.from_declaration(
        "(단위 : 천원, 천USD)", {0: "원화금액", 1: "외화금액"})
    assert cu.kind == MIXED
    assert cu.currency is None
    assert cu.multiplier(0) == 1_000      # '원화금액' = 금액 열
    assert cu.multiplier(1) is None       # '외화금액' → 비금액 표지로 차단
    assert cu.source(0) != SRC_FX
