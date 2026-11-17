"""R334-b - layer 3 issued count when the reader fell back to Ⅱ (issued to date) (fin2/layer3/build.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.layer3.build import _shares_value

II = "현재까지 발행한 주식의 총수"
IV = "발행주식의 총수"


def test_fallback_to_issued_to_date_uses_treasury_plus_float():
    # 엘컴텍 20150515000586: Ⅱ 271,384,859, Ⅲ 188,717,340, Ⅳ '-', Ⅴ '-', Ⅵ 82,667,519
    row = (271384859, 0, 82667519, II)
    assert _shares_value(row, "shares_out") == 82667519
    assert _shares_value(row, "float_shares") == 82667519


def test_printed_issued_count_is_kept():
    # Ⅳ printed: never overridden here, even when the identity fails (other causes, not R334).
    assert _shares_value((35700000, 1173352, 526648, IV), "shares_out") == 35700000


def test_fallback_without_both_parts_is_kept():
    assert _shares_value((1000, None, 900, II), "shares_out") == 1000
    assert _shares_value((1000, 100, None, II), "shares_out") == 1000


def test_parts_larger_than_issued_to_date_are_rejected():
    # SDN 20160812001264: Ⅴ read as 35,113,983 = Ⅵ -> Ⅴ + Ⅵ 70,227,966 > Ⅱ: keep Ⅱ.
    assert _shares_value((35113983, 35113983, 35113983, II), "shares_out") == 35113983
