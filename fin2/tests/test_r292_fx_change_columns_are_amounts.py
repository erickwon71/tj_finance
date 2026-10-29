"""R292 - "환율변동" columns are amounts (the effect of exchange-rate changes), not rates: the "율" in
them must not mark the column non-monetary (value_won NULL). The rates themselves stay non-monetary."""
from __future__ import annotations

import pytest

from fin2.extract.units import column_is_non_money


@pytest.mark.parametrize("label", [
    "(원화단위: 천원)>비현금변동>환율변동", "환율변동", "환율 변동 효과", "당기>환율변동효과",
    "환산차이", "(단위: 백만원)>환산손익", "환율효과"])
def test_fx_change_columns_are_amounts(label):
    assert column_is_non_money(label) is False


@pytest.mark.parametrize("label", [
    "전기말>지분율(%)", "계약환율", "(단위:원)>약정환율", "전기말>환율", "이자율", "진행률", "연이자율(%)",
    "부채비율", "환율변동(%)", "(단위 : 천원, USD)>계약환율"])
def test_rates_stay_non_monetary(label):
    assert column_is_non_money(label) is True
