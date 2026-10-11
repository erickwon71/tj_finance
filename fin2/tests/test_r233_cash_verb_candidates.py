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


def test_misnamed_cash_line_of_another_account_does_not_win():
    """00223434 2025FY: '재무활동으로 분류된 이자지급' mis-mapped into a dividends pool."""
    rows = [_row("배당금수익", 32_011_200, "영업활동현금흐름>조정"),
            _row("재무활동으로 분류된 이자지급", -5_120_278_275, "재무활동현금흐름")]
    cands = {"cf.dividends_received": list(rows), "cf.dividends_paid": list(rows)}
    _drop_accrual_cash_aliases(cands)
    assert len(cands["cf.dividends_received"]) == 2      # no 배당 cash line -> untouched
    assert len(cands["cf.dividends_paid"]) == 2          # out of scope
