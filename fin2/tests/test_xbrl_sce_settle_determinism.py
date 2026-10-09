"""
R200 — R176's XBRL SCE sign settle picked, among rows that fix the same number of broken roll-forward cells, the first
one it met while iterating a `set` — so the stored sign depended on PYTHONHASHSEED (케이피티유 `20180816000025`
연결 '배당' 253,000,000: −253,000,000 under seeds 0~4, +253,000,000 under 5~7).
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import fin2.extract.report_lines_xbrl as X  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _correction_rules_on():
    """R0-2: these rules no longer write layer 2 — they produce layer-3 corrections
    (fin2/extract/layer3_corrections.py). Test the rules themselves with them on."""
    from fin2.extract.as_printed import forced
    with forced("repaired"):
        yield

_RAW = ROOT / "raw_report"
_KPTU = "KOSDAQ/00357607_케이피티유/half/2018/20180816000025.zip"
_QSI = "KOSDAQ/00411446_큐에스아이/half/2019/20190910000104.zip"

_CHILD = """
import sys
from datetime import date
sys.path.insert(0, {root!r})
from loguru import logger; logger.remove()
import fin2.extract.report_lines_xbrl as X
ls = X.extract_report_lines_xbrl({zip!r}, rcept_no="20180816000025", corp_code="00357607", report_fiscal_year=2018,
                                 report_fiscal_period="H1", period_end_date=date(2018, 6, 30))
print(sorted((l.statement, l.basis, l.table_seq, l.row_order, l.col_index, l.value_won) for l in ls))
"""


def _lines(rel, rcept, corp, fy, fp, ped, policy):
    path = _RAW / rel
    if not path.exists():
        return None
    X._R176_TIE_POLICY = policy
    try:
        return X.extract_report_lines_xbrl(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                           report_fiscal_period=fp, period_end_date=ped)
    finally:
        X._R176_TIE_POLICY = "strict"


def test_output_does_not_depend_on_hash_seed():
    path = _RAW / _KPTU
    if not path.exists():
        return
    outs = set()
    for seed in ("0", "5"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "TJF_LAYER2_AS_PRINTED": "0"}   # R0-2: rules on
        res = subprocess.run([sys.executable, "-c", _CHILD.format(root=str(ROOT), zip=str(path))],
                             capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=300)
        assert res.returncode == 0, res.stderr[-500:]
        outs.add(res.stdout.strip().splitlines()[-1])
    assert len(outs) == 1


def test_dividend_tie_resolved_by_negative_by_nature_label():
    lines = _lines(_KPTU, "20180816000025", "00357607", 2018, "H1", date(2018, 6, 30), "strict")
    if lines is None:
        return
    div = [l for l in lines if l.statement == "SCE" and l.basis == "consolidated" and l.row_order == 2
           and l.col_index == 0 and l.label_raw.startswith("배당")]
    assert [l.value_won for l in div] == [-253000000]


def test_treasury_stock_extension_row_is_negative_by_label():
    """큐에스아이 '자기주식 처분(취득)' is a filer-extension row: only its Korean label says it is a purchase."""
    lines = _lines(_QSI, "20190910000104", "00411446", 2019, "H1", date(2019, 6, 30), "strict")
    if lines is None:
        return
    row = [l for l in lines if l.statement == "SCE" and l.basis == "consolidated" and l.row_order == 5
           and l.col_index == 0]
    assert row and row[0].value_won < 0


def test_strict_never_flips_more_than_first():
    """A tie that only 'first' resolves stays as printed under 'strict' (R6): strict flips a subset."""
    a = _lines(_QSI, "20190910000104", "00411446", 2019, "H1", date(2019, 6, 30), "strict")
    if a is None:
        return
    b = _lines(_QSI, "20190910000104", "00411446", 2019, "H1", date(2019, 6, 30), "first")
    neg = lambda ls: sum(1 for l in ls if l.statement == "SCE" and (l.value_won or 0) < 0)  # noqa: E731
    assert neg(a) <= neg(b)
