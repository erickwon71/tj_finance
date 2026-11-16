"""R318 - the income tax candidate that closes EBT - tax = net income wins over the stage rank."""
from fin2.layer3 import combine


def _c(value, stage, label, amended=False):
    return {"value": value, "stage": stage, "label_raw": label, "section_path": None, "table_seq": 0,
            "amended": amended, "amended_by": "a" if amended else None}


def _cands(tax_rows, ebt=-15792, ni=-14092):
    return {"is.ebt": [_c(ebt, "guard", "법인세비용차감전순이익(손실)")],
            "is.net_income": [_c(ni, "exact", "당기순이익(손실)", True)],
            "is.tax_expense": tax_rows}


def test_candidate_that_closes_the_identity_wins_over_the_stage_rank(monkeypatch):
    # 00536888 2023FY consolidated: original '법인세비용(수익)' 2,203 (exact), amendment '법인세 수익(비용)' -1,700 (normalized)
    cands = _cands([_c(2203, "exact", "법인세비용(수익)"), _c(-1700, "normalized", "법인세 수익(비용)", True)])
    confirmed, conflicts = combine._resolve(cands)
    combine._resolve_tax_identity(cands, confirmed, conflicts)
    assert confirmed["is.tax_expense"] == -1700
    monkeypatch.setattr(combine, "_R318_TAX_IDENTITY", False)
    confirmed, conflicts = combine._resolve(cands)
    combine._resolve_tax_identity(cands, confirmed, conflicts)
    assert confirmed.get("is.tax_expense") == 2203


def test_stage_winner_that_closes_the_identity_is_kept():
    cands = _cands([_c(1700, "exact", "법인세비용"), _c(-1700, "normalized", "법인세 수익(비용)")], ebt=-15792, ni=-17492)
    confirmed, conflicts = combine._resolve(cands)
    combine._resolve_tax_identity(cands, confirmed, conflicts)
    assert confirmed["is.tax_expense"] == 1700


def test_no_candidate_closing_the_identity_leaves_the_stage_rank():
    # net income includes discontinued operations: nothing closes, nothing changes
    cands = _cands([_c(2203, "exact", "법인세비용(수익)"), _c(-1700, "normalized", "법인세 수익(비용)", True)], ni=-9999)
    confirmed, conflicts = combine._resolve(cands)
    combine._resolve_tax_identity(cands, confirmed, conflicts)
    assert confirmed["is.tax_expense"] == 2203
