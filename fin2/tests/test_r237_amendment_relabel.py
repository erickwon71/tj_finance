"""R237 — an amendment that relabels a cell (same place, same amount) replaces the original cell."""
from fin2.layer3.combine import _relabelled_cell

OLD = ("CF", "consolidated", 0, "재무활동현금흐름", "배당금지급")
NEW = ("CF", "consolidated", 0, "재무활동현금흐름", "주식의 발행")
R_ORIG, R_AMEND = "20240522000014", "20240523000228"     # 00667373 2024Q1


def _state(value=36_762_530_400, kind="xml"):
    return {OLD: {"value_won": value, "source_rcept": R_ORIG}}, {OLD: kind}


def test_relabel_replaces():
    merged, kinds = _state()
    assert _relabelled_cell(merged, kinds, OLD, NEW, 36_762_530_400, R_AMEND, "xml") == OLD


def test_other_amount_or_path_or_same_filing_is_not_a_relabel():
    merged, kinds = _state()
    assert _relabelled_cell(merged, kinds, OLD, NEW, 1, R_AMEND, "xml") is None
    assert _relabelled_cell(merged, kinds, OLD, NEW, 36_762_530_400, R_AMEND, "xbrl") is None
    assert _relabelled_cell(merged, kinds, OLD, NEW, 36_762_530_400, R_ORIG, "xml") is None
    assert _relabelled_cell(merged, kinds, None, NEW, 36_762_530_400, R_AMEND, "xml") is None
    assert _relabelled_cell(merged, kinds, OLD, OLD, 36_762_530_400, R_AMEND, "xml") is None


def test_unmapped_new_label_is_not_a_relabel():
    """00126937 2023FY: '당기순이익' → '계속영업당기순이익' (maps to no account) keeps the original."""
    key_old = ("IS", "consolidated", 0, None, "당기순이익")
    key_new = ("IS", "consolidated", 0, None, "계속영업당기순이익")
    merged = {key_old: {"value_won": 227_014_034_818, "source_rcept": "20240314001491"}}
    kinds = {key_old: "xml"}
    assert _relabelled_cell(merged, kinds, key_old, key_new, 227_014_034_818,
                            "20240328001539", "xml") is None


def test_new_account_elsewhere_with_other_amount_is_a_misprint():
    """00528791 2025FY: '자산총계' → '자본총계 (E=C+D)' while '자본총계 (D)' = -11,462,673,871."""
    key_old = ("BS", "consolidated", 0, None, "자산총계")
    key_new = ("BS", "consolidated", 0, None, "자본총계 (E=C+D)")
    merged = {key_old: {"value_won": 528_073_345_609, "source_rcept": "20260327000210"}}
    kinds = {key_old: "xml"}
    canon_values = {("BS", "consolidated", 0, "bs.total_equity"): {528_073_345_609, -11_462_673_871}}
    assert _relabelled_cell(merged, kinds, key_old, key_new, 528_073_345_609, "20260331004970",
                            "xml", canon_values) is None


def test_cosmetic_label_change_is_not_a_relabel():
    """00260611 2024H1: '…반기순이익\\n(손실)' → '…반기순이익（손실）' is the same label."""
    key_old = ("IS", "consolidated", 0, None, "지배기업의 소유주 귀속 반기순이익\n(손실)")
    key_new = ("IS", "consolidated", 0, None, "지배기업의 소유주 귀속 반기순이익（손실）")
    merged = {key_old: {"value_won": -4_495_843_169, "source_rcept": "20240814004628"}}
    kinds = {key_old: "xml"}
    assert _relabelled_cell(merged, kinds, key_old, key_new, -4_495_843_169,
                            "20240816000096", "xml") is None
