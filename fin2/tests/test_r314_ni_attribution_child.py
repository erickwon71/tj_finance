"""R314 - the owners' share printed under the bare net income wording must not outrank the net income row."""
from fin2.layer3 import combine


def _c(value, stage, label, section):
    return {"value": value, "stage": stage, "label_raw": label, "section_path": section, "table_seq": 0,
            "amended": False, "amended_by": None}


def test_child_of_the_attribution_section_loses_to_the_total_row(monkeypatch):
    # 00126487 2025Q1: '연결분기순이익' 75.6B (fuzzy) vs '분기순이익' 26.9B under '당기순이익(손실)의 귀속' (exact)
    cands = {"is.net_income": [_c(75, "fuzzy", "연결분기순이익", None),
                               _c(27, "exact", "분기순이익", "당기순이익(손실)의 귀속")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.net_income"] == 75
    monkeypatch.setattr(combine, "_R314_NI_ATTRIBUTION_CHILD", False)
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.net_income"] == 27


def test_child_under_a_heading_that_is_the_total_row_loses():
    # 00631518 2025Q1: the section is the parent row's own label
    cands = {"is.net_income": [_c(-125, "fuzzy", "분기연결순이익", None),
                               _c(-229, "exact", "분기순이익", "분기연결순이익")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.net_income"] == -125


def test_child_under_a_zero_valued_heading_row_is_the_net_income():
    # 00138297 2016FY: '당기순이익' is a heading row printed as 0, the value is on the child row
    cands = {"is.net_income": [_c(0, "exact", "당기순이익", None),
                               _c(-457, "exact", "당기순이익(손실)", "당기순이익")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.net_income"] == -457


def test_only_candidate_in_the_attribution_section_is_kept():
    cands = {"is.net_income": [_c(27, "exact", "분기순이익", "당기순이익(손실)의 귀속")]}
    confirmed, _ = combine._resolve(cands)
    assert confirmed["is.net_income"] == 27
