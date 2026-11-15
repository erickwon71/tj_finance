"""R315 - the first subtotal under a cash flow section heading must not outrank the section total row."""
from fin2.layer3 import combine


def _c(value, stage, label, section):
    return {"value": value, "stage": stage, "label_raw": label, "section_path": section, "table_seq": 0,
            "amended": False, "amended_by": None}


def test_subtotal_under_the_section_heading_loses_to_the_section_total(monkeypatch):
    # 00964595 2025H1 separate: heading 'I. 영업활동으로 인한 현금흐름' -2,258M (normalized) vs the subtotal printed
    # under it, before interest / tax -2,264M (exact)
    cands = {"cf.operating": [_c(-2258, "normalized", "I. 영업활동으로 인한 현금흐름", None),
                              _c(-2264, "exact", "영업활동으로 인한 현금흐름", "I. 영업활동으로 인한 현금흐름")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["cf.operating"] == -2258
    monkeypatch.setattr(combine, "_R315_CF_SECTION_CHILD", False)
    confirmed, _ = combine._resolve(cands)
    assert confirmed["cf.operating"] == -2264


def test_child_under_a_zero_valued_heading_is_kept():
    cands = {"cf.investing": [_c(0, "exact", "투자활동으로 인한 현금흐름", None),
                              _c(-55, "exact", "투자활동으로 인한 현금흐름 합계", "투자활동으로 인한 현금흐름")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["cf.investing"] == -55


def test_only_candidate_is_kept():
    cands = {"cf.financing": [_c(7, "exact", "재무활동으로 인한 현금흐름", "III. 재무활동으로 인한 현금흐름")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["cf.financing"] == 7
