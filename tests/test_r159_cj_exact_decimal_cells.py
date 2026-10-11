"""R159-보강⑤ — CJ제일제당 20260316001116: 천원 표의 소수 3자리 셀은 정확한 원으로 읽는다."""
from parser.common.amount_normalizer import parse_amount
from parser.xml.table_extractor import apply_source_typo_fixes

R = "20260316001116"


def test_registered_cells_parse_to_exact_won():
    cells = ["(571,455,619.874)", "(322,517,146.659)", "(248,938,473.216)"]
    fixed = apply_source_typo_fixes(cells, R)
    assert [parse_amount(c, 1000) for c in fixed] == [-571_455_619_874, -322_517_146_659,
                                                      -248_938_473_216]


def test_attribution_identity_closes():
    controlling = parse_amount(apply_source_typo_fixes(["(571,455,619.874)"], R)[0], 1000)
    assert abs(controlling + 154_500_212_000 - (-416_955_408_000)) < 1_000


def test_other_filings_untouched():
    assert apply_source_typo_fixes(["(571,455,619.874)"], "20990101000001") == ["(571,455,619.874)"]
