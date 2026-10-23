"""R116 list - the 2015 Q1 amendments of 형지I&C get the same blank-cumulative fill as the original."""
import pytest

from fin2.extract.report_lines import _Q1_CUM_BLANK_USE_3M_RCEPTS


@pytest.mark.parametrize("rcept", ["20150514004898", "20150515000009", "20150519000237"])
def test_hyeongji_2015_q1_filings_are_listed(rcept):
    assert rcept in _Q1_CUM_BLANK_USE_3M_RCEPTS
