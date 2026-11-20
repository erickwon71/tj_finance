"""R353 - continuing / discontinued NI under labels R341 does not know, confirmed only by an identity."""
import pytest

from fin2.layer3 import combine


def _row(label, value, section_path=None, ro=0):
    return {"statement": "IS", "basis": "consolidated", "label_raw": label, "value_won": value,
            "value_exact": None, "eps_row": False, "node_role": None, "section_path": section_path,
            "table_seq": 0, "is_cumulative": True, "row_order": ro}


def _run(rows, monkeypatch=None, on=True):
    if monkeypatch is not None:
        monkeypatch.setattr(combine, "_R353_LOOSE_OPS_NI", on)
    cands = combine._map_rows(rows, "FY", "consolidated", ("IS",))
    loose = combine._pop_loose_ops_ni(cands)
    assert not any(k.startswith("is.r353") for k in cands)
    confirmed, _ = combine._resolve(cands)
    combine._resolve_loose_ops_ni(loose, cands, confirmed)
    combine._resolve_sign_identity(cands, confirmed)
    return confirmed


@pytest.mark.parametrize("label,key", [
    ("계속사업영업당기순이익", combine._R353_CONT),
    ("계속사업영업손익", combine._R353_CONT),
    ("계속기업당기순이익", combine._R353_CONT),
    ("계속영업연결당기순이익", combine._R353_CONT),
    ("중단사업당기순이익", None),          # R341 strict pattern already takes it
    ("계속영업이익", None),
    ("계속영업총포괄이익", None),
    ("계속영업법인세비용", None),
    ("지배기업의 소유주에게 귀속될 계속영업손익", combine._R353_CONT_CTRL),
    ("비지배지분에 귀속될 계속영업이익(손실)", combine._R353_CONT_NCI),
    ("지배기업의 소유주에게 귀속될 중단영업손익", None),
])
def test_loose_key(label, key):
    assert combine._loose_ops_ni_key(label, None) == key


def test_attribution_by_section_path():
    sp = "당기순이익(손실)의 귀속>비지배지분에 귀속되는 당기순이익"
    assert combine._loose_ops_ni_key("계속사업영업당기순이익", sp) == combine._R353_CONT_NCI


def test_escornek_tax_benefit_printed_positive(monkeypatch):
    # 에스코넥 00573269 2025FY consolidated: EBT 35,505.8M, '법인세비용' printed +2,373.0M,
    # '계속사업영업당기순이익' 37,878.8M (= EBT + 2,373.0 -> benefit), discontinued -2,176.9M, NI 35,701.8M
    rows = [_row("법인세비용차감전순이익(손실)", 35505798645, ro=10), _row("법인세비용", 2372974934, ro=11),
            _row("계속사업영업당기순이익", 37878773579, ro=12), _row("중단영업당기순이익", -2176923987, ro=13),
            _row("당기순이익(손실)", 35701849592, ro=14)]
    c = _run(rows, monkeypatch, on=True)
    assert c["is.continuing_ni"] == 37878773579
    assert c["is.tax_expense"] == -2372974934
    c = _run(rows, monkeypatch, on=False)
    assert "is.continuing_ni" not in c and c["is.tax_expense"] == 2372974934


def test_bitwoen_attribution_split_only(monkeypatch):
    # 비투엔 01326792 2025FY consolidated: no continuing total line, only the attribution split
    rows = [_row("법인세비용차감전순이익(손실)", -10640771788), _row("법인세비용(수익)", 217271793),
            _row("당기순이익(손실)", -12215821766),
            _row("지배기업의 소유주에게 귀속될 계속영업손익", -10679702313),
            _row("비지배지분에 귀속될 계속영업이익(손실)", -178341268)]
    assert _run(rows, monkeypatch)["is.continuing_ni"] == -10858043581


def test_unproven_loose_line_is_not_confirmed(monkeypatch):
    # '계속사업영업이익' that is really operating income: closes neither identity -> nothing
    rows = [_row("계속사업영업이익", 6200), _row("법인세비용차감전순이익", 4000), _row("법인세비용", 1000),
            _row("당기순이익", 3000)]
    assert "is.continuing_ni" not in _run(rows, monkeypatch)


def test_loose_discontinued_needs_continuing_proof(monkeypatch):
    # 세중 00264671 2024Q3 style: '계속기업당기순이익' + loose discontinued line
    rows = [_row("법인세비용차감전순이익(손실)", 1331267617), _row("법인세비용(수익)", 33179268),
            _row("계속기업당기순이익", 1364446885), _row("중단기업당기순이익", 16635162),
            _row("당기순이익(손실)", 1381082047)]
    c = _run(rows, monkeypatch)
    assert c["is.continuing_ni"] == 1364446885 and c["is.discontinued_ni"] == 16635162
    assert c["is.tax_expense"] == -33179268


def test_strict_candidate_is_never_overridden(monkeypatch):
    rows = [_row("법인세비용차감전순이익", 4000), _row("법인세비용", 1000), _row("계속영업이익", 2900),
            _row("계속사업영업당기순이익", 3000), _row("당기순이익", 3000)]
    assert _run(rows, monkeypatch)["is.continuing_ni"] == 2900
