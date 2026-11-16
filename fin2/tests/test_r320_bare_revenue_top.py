"""R320 - the bare '수익' printed on top of the income statement is the revenue total, not a component printed below it."""
from fin2.layer3 import combine


def _c(value, stage, label, section=None, seq=0):
    return {"value": value, "stage": stage, "label_raw": label, "section_path": section, "table_seq": seq,
            "amended": False, "amended_by": None}


def test_bare_top_row_beats_a_component_row(monkeypatch):
    # 00148610 2026Q3 separate: '수익 (주38)' 6,436B (taxonomy) vs '수수료수익 (주29)' 346.7B (normalized)
    cands = {"is.revenue": [_c(6436, "taxonomy", "수익 (주38)"), _c(346, "normalized", "수수료수익 (주29)")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.revenue"] == 6436
    monkeypatch.setattr(combine, "_R320_BARE_REVENUE_TOP", False)
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.revenue"] == 346


def test_component_larger_than_the_bare_row_is_left_to_the_stage_rank():
    cands = {"is.revenue": [_c(100, "taxonomy", "수익"), _c(900, "exact", "영업수익")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.revenue"] == 900


def test_bare_row_inside_a_section_is_not_the_total():
    cands = {"is.revenue": [_c(5000, "taxonomy", "수익", section="영업수익"), _c(300, "exact", "매출액")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.revenue"] == 300
