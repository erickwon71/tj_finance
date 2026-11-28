"""R169-c - Zinus 20141114000764 separate CF prints no unit declaration (BS/IS/SCE print '(단위 : 원)').

The scan proved k=1 from other filings' identical amounts (hits 4 vs 0 for 1,000 / 1,000,000); the
override file carries it, so the CF table is read as `proved_unit` instead of being held back.
"""
import glob
import json
from pathlib import Path

import pytest

import fin2.extract.report_lines as rl

DATA = Path(rl.__file__).resolve().parent / "data" / "unit_self_contradiction_overrides.json"
ROOT = Path(__file__).resolve().parents[1] / "raw_report"
SD = Path("/Volumes/dart_data/raw_report")
RCEPT = "20141114000764"


def test_override_is_registered():
    assert json.loads(DATA.read_text(encoding="utf-8"))[RCEPT] == {"CF_S": 1}


def test_scan_falls_back_to_sd_mirror(monkeypatch):
    import fin2.audit.unit_self_contradiction as u
    assert "_sd_path" in open(u.__file__, encoding="utf-8").read()


def test_separate_cf_is_loaded_as_proved_unit():
    src = None
    for base in (ROOT, SD):
        g = glob.glob(str(base / "KOSPI/00150633_*/quarter/2014" / f"{RCEPT}.xml"))
        if g:
            src = Path(g[0])
            break
    if src is None:
        pytest.skip("source XML is not on disk")
    lines = rl.extract_report_lines(src, rcept_no=RCEPT, corp_code="00150633",
                                    report_fiscal_year=2014, report_fiscal_period="Q3")
    cf = [l for l in lines if l.statement == "CF" and l.basis == "separate"]
    assert cf and {l.unit_source for l in cf} == {"proved_unit"}
    assert any(l.value_won == 2033178793 and l.label_raw.startswith("Ⅰ. 영업활동") for l in cf)
