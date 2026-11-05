"""R303 - a '가중치' (weight) column is no amount column: R158 must not rewrite its '1.00' into row digits."""
from fin2.extract import units as u


def test_weight_column_is_non_money():
    assert u.column_is_non_money("당반기(누적)>가중치")
    assert u.column_is_non_money("가중치")


def test_amount_columns_are_unchanged():
    assert not u.column_is_non_money("당기")
    assert not u.column_is_non_money("장부금액")
