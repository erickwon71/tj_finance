"""R341 - EBT - tax = net income decides the EBT / tax sign; continuing / discontinued NI canonicals."""
from fin2.layer3 import combine


def _c(value, label, stage="exact"):
    return {"value": value, "stage": stage, "label_raw": label, "section_path": None, "table_seq": 0,
            "amended": False, "amended_by": None}


def _run(ebt, ebt_label, tax, ni, cont=None):
    cands = {"is.ebt": [_c(combine._loss_signed("is.ebt", ebt_label, ebt), ebt_label)],
             "is.tax_expense": [_c(tax, "법인세비용")],
             "is.net_income": [_c(ni, "당기순이익(손실)")]}
    if cont is not None:
        cands["is.continuing_ni"] = [_c(cont, "계속영업이익")]
    confirmed, _ = combine._resolve(cands)
    combine._resolve_sign_identity(cands, confirmed)
    return confirmed


def test_stale_loss_label_over_a_profit_is_not_negated(monkeypatch):
    # 삼성중공업 2025FY consolidated (억원): '법인세비용차감전순손실' printed +6,504, tax 1,147, NI 5,357
    assert _run(6504, "법인세비용차감전순손실", 1147, 5357)["is.ebt"] == 6504
    monkeypatch.setattr(combine, "_R341_SIGN_IDENTITY", False)
    assert _run(6504, "법인세비용차감전순손실", 1147, 5357)["is.ebt"] == -6504


def test_loss_label_over_a_real_loss_stays_negated():
    # 루닛 2021 style: the loss printed as a positive under a loss-only label
    assert _run(736, "법인세비용차감전순손실", 0, -736)["is.ebt"] == -736


def test_tax_printed_as_a_deduction_becomes_expense_positive():
    # 케이티앤지 2025FY consolidated: '법인세비용' printed (3,522), EBT 14,553, NI 11,023 (rounded 억 -> use exact sum)
    assert _run(14553, "법인세비용차감전순이익", -3522, 11031)["is.tax_expense"] == 3522


def test_tax_benefit_label_printed_positive_becomes_negative():
    # 대원 2025FY consolidated: '법인세수익(비용)' +10 is a benefit, EBT -95, NI -85
    assert _run(-95, "법인세비용차감전순이익(손실)", 10, -85)["is.tax_expense"] == -10


def test_discontinued_operations_gap_is_left_alone():
    # NI includes discontinued operations; EBT - tax closes against continuing NI
    c = _run(1000, "법인세비용차감전순이익", 200, 1500, cont=800)
    assert (c["is.ebt"], c["is.tax_expense"]) == (1000, 200)


def test_nothing_closes_nothing_changes():
    c = _run(1000, "법인세비용차감전순이익", 200, 1500)
    assert (c["is.ebt"], c["is.tax_expense"]) == (1000, 200)


def test_ops_ni_labels():
    f = combine._ops_ni_canonical
    assert f("계속영업이익(손실)") == "is.continuing_ni"
    assert f("Ⅵ. 계속영업당기순이익") == "is.continuing_ni"
    assert f("중단영업손익") == "is.discontinued_ni"
    assert f("중단영업이익(손실)") == "is.discontinued_ni"
    assert f("법인세비용차감전계속영업이익") is None
    assert f("계속영업기본주당이익") is None
    assert f("당기순이익") is None
