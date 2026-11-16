"""R321 - the owners' dividend wording is an alias, so a zero owners row beats the minority dividend row."""
import pytest

from fin2.layer3 import combine
from fin2.layer3.combine import _FS, _map_label


@pytest.mark.parametrize("label", ["보통주배당금의 지급", "보통주 배당금의 지급", "보통주배당금지급", "현금배당금의지급", "연차배당금의 지급"])
def test_owners_dividend_wording_is_an_alias_above_fuzzy(label):
    r = _map_label(label, _FS["CF"])
    assert r.account_code == "cf.dividends_paid" and r.stage in ("exact", "normalized")


def test_minority_dividend_row_stays_fuzzy():
    assert _map_label("비지배지분 배당금의 지급", _FS["CF"]).stage == "fuzzy"


def test_zero_owners_row_beats_the_minority_row():
    # 00858364 2025Q1 consolidated: '보통주배당금의 지급' 0, '비지배지분 배당금의 지급' -5.26B
    cands = {"cf.dividends_paid": [
        {"value": 0, "stage": "exact", "label_raw": "보통주배당금의 지급", "section_path": "재무활동현금흐름", "table_seq": 0,
         "amended": False, "amended_by": None},
        {"value": -5255, "stage": "fuzzy", "label_raw": "비지배지분 배당금의 지급", "section_path": "재무활동현금흐름", "table_seq": 0,
         "amended": False, "amended_by": None}]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["cf.dividends_paid"] == 0
