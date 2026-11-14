"""R300 - a row labelled as a share count is no amount: value_won stays empty, the printed text is kept."""
import pytest

from fin2.extract import units as u


@pytest.mark.parametrize("label", ["발행주식수", "발행주식수(주)", "가중평균유통보통주식수(*)", "수권주식수(주)",
                                   "발행한 주식의 수(주)", "발행한 보통주식의 수", "자본금>발행주식총수", "기초주식수"])
def test_share_count_rows(label):
    assert u.row_label_is_share_count(label)


@pytest.mark.parametrize("label", ["자본금", "주식발행초과금", "주식보상비용", "주식수익률", "주당액면금액", "", None])
def test_money_rows_are_untouched(label):
    assert not u.row_label_is_share_count(label)
