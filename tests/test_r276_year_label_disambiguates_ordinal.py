"""R276 - columns printing different calendar years but the same (mistyped) ordinal are keyed by year."""
import parser.xml.table_extractor as te
from parser.xml.table_extractor import _columns_from_grid


def _ranks(headers):
    return [c.period_rank for c in _columns_from_grid([["과 목"] + headers])]


def test_colliding_ordinals_use_the_printed_year():
    h = ["2015연도\n(제16기)", "2016연도\n(제16기)", "2017연도\n(제18기)"]
    assert _ranks(h) == [2, 1, 0]


def test_consistent_ordinals_untouched():
    assert _ranks(["2015연도 (제15기)", "2016연도 (제16기)", "2017연도 (제17기)"]) == [0, 1, 2]


def test_switch_off():
    te._R276_YEAR_LABEL_DISAMBIGUATES = False
    try:
        assert _ranks(["2015연도 (제16기)", "2016연도 (제16기)", "2017연도 (제18기)"]) == [0, 0, 1]
    finally:
        te._R276_YEAR_LABEL_DISAMBIGUATES = True
