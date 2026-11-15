"""R313 - the owners' dividend printed under another wording maps to cf.dividends_paid (exact stage)."""
import pytest

from fin2.layer3.combine import _FS, _map_label


@pytest.mark.parametrize("label", [
    "연차배당의 지급",            # 00403632
    "보통주 배당 지급",           # 00688996
    "보통주에 지급된 배당금",
    "지배기업의 소유주에게 지급한 배당금",
    "(3)지배기업의소유주에게지급한배당금",
    "(1)배당금으로 인한 유출액",
])
def test_owner_dividend_wordings_are_dividends_paid(label):
    m = _map_label(label, _FS["CF"])
    assert m.account_code == "cf.dividends_paid"
    assert m.stage in ("exact", "normalized")


def test_minority_dividend_row_is_still_the_weaker_candidate():
    # the minority row keeps its fuzzy stage, so it loses against the owners' row
    weak = _map_label("종속기업의 소수주주에 대한 배당금 지급", _FS["CF"])
    assert weak.stage == "fuzzy"
