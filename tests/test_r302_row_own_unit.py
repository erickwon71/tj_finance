"""R302 - a note row label ending in its own unit marker is read in that unit, not the table's."""
import pytest

from fin2.extract import units as u


@pytest.mark.parametrize("label", ["유통주식수의 기초수량 (단위: 주)", "발행주식수 (단위:주)", "수권주식수 (단위 : 주)",
                                   "총 유통일수 (단위: 일)", "기초수량 적용일수 (일)", "비율(%)", "주당이익>기본주당이익 (단위: 건)"])
def test_non_money_marker(label):
    assert u.row_label_own_unit(label) == "non_money"


@pytest.mark.parametrize("label", ["기본주당이익(손실) (단위: 원)", "배당금 (단위:원)"])
def test_won_marker(label):
    assert u.row_label_own_unit(label) == "won"


@pytest.mark.parametrize("label", ["(주)에스엠지아시아", "자본금(원)", "매출액", "", None])
def test_other_labels_untouched(label):
    assert u.row_label_own_unit(label) is None
