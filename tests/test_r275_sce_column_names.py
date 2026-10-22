"""R275: SCE column vocabulary also recognises 보통주납입자본 / 기타자본항목."""
import fin2.extract.text as tx
from lxml import etree


def _tbl(*names):
    cells = "".join(f"<TD>{n}</TD>" for n in names)
    return etree.fromstring(f"<TABLE><TR>{cells}</TR></TABLE>")


def test_r275_new_column_names_make_an_equity_changes_header():
    header = "구분 보통주납입자본 기타자본항목 이익잉여금 총계"
    assert tx._looks_like_equity_changes_header(_tbl(*header.split()))


def test_r275_switch_off():
    tx._R275_MORE_SCE_COLUMN_NAMES = False
    try:
        assert not tx._looks_like_equity_changes_header(_tbl(*"구분 보통주납입자본 기타자본항목 이익잉여금 총계".split()))
    finally:
        tx._R275_MORE_SCE_COLUMN_NAMES = True


def test_r275_old_vocabulary_unchanged():
    assert tx._looks_like_equity_changes_header(_tbl(*"구분 자본금 자본잉여금 이익잉여금 총계".split()))
    assert not tx._looks_like_equity_changes_header(_tbl(*"구분 자본금 총계".split()))
