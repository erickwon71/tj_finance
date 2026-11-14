"""R297 - a note-table column whose last header segment is 주석 / 관련주석 holds note numbers, not amounts."""
import pytest

from fin2.extract.report_lines import _is_note_table_ref_column_label


@pytest.mark.parametrize("label", [
    "주석", "주 석", "관련주석", "관련 주석", "(단위: 천원)>관련주석", "(단위: 원)>주석", "구분>주석번호", "주기",
])
def test_note_reference_column_labels(label):
    assert _is_note_table_ref_column_label(label)


@pytest.mark.parametrize("label", [
    None, "", "당기", "(단위: 천원)>당기말", "주석>당기", "주 석>Ⅰ. 반기순이익", "비고", "주석사항금액",
])
def test_other_column_labels_are_kept(label):
    assert not _is_note_table_ref_column_label(label)
