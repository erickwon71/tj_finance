"""R235 — CF dividends paid are -|value| in layer 3 (user decision 2026-10-11)."""
from fin2.layer3.combine import _sign_dividends_paid


def _row(label, value):
    return {"label_raw": label, "value": value}


def test_dividend_paid_labels_become_negative():
    cands = {"cf.dividends_paid": [_row("배당금의 지급", 413_409_970), _row("배   당   금의 지급", -5),
                                   _row("배당금의지금", 299_741_720)]}
    _sign_dividends_paid(cands)
    assert [r["value"] for r in cands["cf.dividends_paid"]] == [-413_409_970, -5, -299_741_720]


def test_mis_mapped_labels_untouched_and_rows_not_mutated():
    src = _row("재무활동으로 분류된 차입금", 17_088_619_684)
    paid = _row("배당금 지급", 10)
    cands = {"cf.dividends_paid": [src, paid], "cf.other": [paid]}
    _sign_dividends_paid(cands)
    assert cands["cf.dividends_paid"][0]["value"] == 17_088_619_684
    assert paid["value"] == 10                         # shared dict not mutated
