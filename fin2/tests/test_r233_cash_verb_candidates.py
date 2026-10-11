"""R233 — CF interest/dividend canonicals prefer the cash line over the P&L alias (order-free)."""
from fin2.layer3.combine import _drop_accrual_cash_aliases


def _row(label, value, path):
    return {"label_raw": label, "value": value, "section_path": path}


def _pool():
    """00112679 2015Q1 separate: 조정 구간 `이자비용` + 재무활동 `이자지급` (same size, opposite sign)."""
    return [_row("이자비용", 19_794_068, "영업활동현금흐름>당기순이익조정을 위한 가감"),
            _row("이자지급", -19_794_068, "재무활동현금흐름")]


def test_cash_line_wins_in_either_order():
    for rows in (_pool(), list(reversed(_pool()))):
        cands = {"cf.interest_paid": rows}
        _drop_accrual_cash_aliases(cands)
        assert [r["value"] for r in cands["cf.interest_paid"]] == [-19_794_068]


def test_direct_method_alias_kept_without_cash_line():
    cands = {"cf.interest_received": [_row("이자수익", 5_000, "영업활동으로 인한 현금흐름")]}
    _drop_accrual_cash_aliases(cands)
    assert len(cands["cf.interest_received"]) == 1


def test_other_canonicals_untouched():
    cands = {"cf.capex": [_row("유형자산의 취득", -1, "투자"), _row("건설중인자산", -2, "투자")]}
    _drop_accrual_cash_aliases(cands)
    assert len(cands["cf.capex"]) == 2
