"""R236 — '(영업|투자|재무)활동으로 분류된' qualifier is stripped; the rest maps exact/normalized only."""
from fin2.layer3.combine import _map_label


def _code(label):
    r = _map_label(label, "cf")
    return r.account_code if r.confidence >= 0.88 and not r.account_code.startswith("unknown.") else None


def test_shared_prefix_no_longer_pulls_into_dividends_paid():
    assert _code("재무활동으로 분류된 차입금") is None
    assert _code("재무활동으로 분류된 이자지급") == "cf.interest_paid"


def test_qualified_cash_lines_map_to_their_account():
    assert _code("영업활동으로 분류된 이자수취") == "cf.interest_received"
    assert _code("재무활동으로 분류된 배당금지급") == "cf.dividends_paid"
    assert _code("투자활동으로 분류된 유형자산의 처분") == "cf.ppe_proceeds"


def test_fuzzy_remainder_is_not_mapped_but_plain_fuzzy_kept():
    assert _code("투자활동으로 분류된 선수금의 증가(감소)") is None
    assert _code("재무활동으로 분류된 리스부채의 증가") is None
    assert _code("영업활동으로 분류된 법인세납부(환급)") == "cf.tax_paid"     # alias '법인세납부'


def test_cash_tail_stripped():
    assert _code("투자활동으로 분류된 유형자산의 처분으로 인한 현금유입") == "cf.ppe_proceeds"


def test_unqualified_labels_unchanged():
    assert _code("배당금의 지급") == "cf.dividends_paid"
