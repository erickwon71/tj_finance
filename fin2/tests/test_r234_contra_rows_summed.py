"""R234 — BS contra lines printed under every asset are summed per table (user decision 2026-10-11)."""
from fin2.layer3.combine import _sum_contra_rows

_PPE = "자산>비유동자산>유형자산"


def _r(label, value, *, path=_PPE, seq=0, statement="BS"):
    # (statement, basis, col_index, section_path, label_raw, value_won,
    #  node_role, table_seq, is_cum, value_exact, eps_row, xbrl_local)
    return (statement, "consolidated", 0, path, label, value, "F", seq, False, None, False, None)


def _loren():
    """로젠 20190401002764 연결 BS 유형자산 (일부)."""
    return [_r("건물", 12_747_682_145), _r("감가상각누계액", -5_235_758_293),
            _r("구축물", 1_353_598_653), _r("감가상각누계액", -1_070_985_828),
            _r("기계장치", 43_146_491_701), _r("감가상각누계액", -39_175_057_959)]


def test_contra_rows_summed_into_first():
    out = _sum_contra_rows(_loren())
    dep = [r for r in out if r[4] == "감가상각누계액"]
    assert len(dep) == 1 and dep[0][5] == -45_481_802_080
    assert [r[4] for r in out] == ["건물", "감가상각누계액", "구축물", "기계장치"]


def test_mixed_sign_left_alone():
    rows = [_r("감가상각누계액", -100), _r("감가상각누계액", 50)]
    assert _sum_contra_rows(rows) == rows


def test_other_tables_and_paths_and_labels_not_merged():
    rows = [_r("감가상각누계액", -1, seq=0), _r("감가상각누계액", -2, seq=1),        # other table
            _r("대손충당금", -3, path="자산>유동자산"), _r("대손충당금", -4, path=_PPE),  # other path
            _r("기타유동자산", 5), _r("기타유동자산", 6)]                            # not a contra label
    assert _sum_contra_rows(rows) == rows


def test_spaced_and_parenthesised_labels_match():
    rows = [_r("(대손충당금)", -10, path="자산>유동자산"), _r("(대손충당금)", -20, path="자산>유동자산")]
    assert [r[5] for r in _sum_contra_rows(rows)] == [-30]


def test_non_bs_untouched():
    rows = [_r("정부보조금", 1, statement="CF"), _r("정부보조금", 2, statement="CF")]
    assert _sum_contra_rows(rows) == rows
