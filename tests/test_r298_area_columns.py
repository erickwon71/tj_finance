"""R298 - an area column ('면적(㎡)', '㎥') is no amount: value_won stays empty, the printed text is kept."""
import pytest

from fin2.extract import units as u


@pytest.mark.parametrize("label", ["면적(㎡)", "토지 면적", "연면적>당기말", "부피(㎥)", "건물면적(㎡)"])
def test_area_columns_are_non_money(label):
    assert u.column_is_non_money(label)


@pytest.mark.parametrize("label", ["장 부 가 액>당기말", "취득원가", "공시지가>전기말", "당기말", None])
def test_money_columns_are_untouched(label):
    assert not u.column_is_non_money(label)


def test_area_column_has_no_multiplier_in_a_money_table():
    cu = u.ColumnUnits.from_declaration("(단위: 천원)", {0: "면적(㎡)", 1: "장부금액"})
    assert cu.multiplier(0) is None and cu.source(0) == u.SRC_NON_MONEY
    assert cu.multiplier(1) == 1000
