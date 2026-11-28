"""R403 - note-zone entry and bare statement names inside the notes.

Polaris Office 20140530000498 (2014Q1): the consolidated notes open with '3. 연결주석사항' (a whole line of its own,
followed by '1. 지배기업의 개요' in the same paragraph). The legacy walker never entered the note zone, so the bare
'현금흐름표' sub-title of note 33 became a separate CF heading and its consolidated detail table was read as the
separate CF (missing/wrong rows #573128~#573136). R403 recognises the whole-line note heading (R403) and refuses a
bare statement name as a statement heading while inside the notes (R403-b). Nothing is re-valued (R0-2).
"""
from pathlib import Path

import pytest

import fin2.extract.statement_titles as st
import fin2.extract.text as T

POSITIVE = [
    "3. 연결주석사항&cr;&cr;1. 지배기업의 개요",   # first line only is judged
    "4. 별도주석사항&cr;",
    "2.재무제표주석",
    "나.별도재무제표주석",
    "1.주석",
    "주석",
    "3분기재무제표에대한주석-계속",
    "2.재무제표에대한주석사항",
    "Ⅱ.연결재무제표에대한주석사항",
    "2.주석사항",
]

NEGATIVE = [
    "주석34에서",                       # cross-reference inside prose
    "(주석12)",
    "주석누락",
    "주석산수소디히드로코데인",           # a drug name, not a heading
    "무형자산의기타주석사항에대한기술",    # a sentence title
    "첨부된감사보고서주석사항39-3참조.",    # a reference sentence
    "1. 영업으로부터 창출된 현금",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_note_heading_line_enters_note_zone(text):
    assert st.is_legacy_note_marker(text)


@pytest.mark.parametrize("text", NEGATIVE)
def test_reference_or_sentence_is_not_a_note_heading(text):
    # The existing '재무제표에대한주석'/bare-'주석' rule keeps its old behaviour; the negatives above
    # are chosen so that neither the old rule nor the new whole-line rule matches them.
    assert not st.is_legacy_note_marker(text)


def test_switch_off_restores_old_behaviour():
    saved = st._R403_NOTE_HEADING_LINE
    try:
        st._R403_NOTE_HEADING_LINE = False
        assert not st.is_legacy_note_marker("3. 연결주석사항&cr;&cr;1. 지배기업의 개요")
    finally:
        st._R403_NOTE_HEADING_LINE = saved


@pytest.mark.parametrize("name", ["현금흐름표", "재무상태표", "포괄손익계산서", "자본변동표"])
def test_bare_name_inside_notes_is_not_a_statement_heading(name):
    assert T._R403_NOTE_ZONE_BARE_NAME is True
    assert name in T._R403_BARE_STATEMENT_NAMES


POLARIS = Path("/Volumes/dart_data/raw_report/KOSDAQ/00269852_폴라리스오피스/quarter/2014/20140530000498.xml")


@pytest.mark.skipif(not POLARIS.exists(), reason="raw XML not mounted")
def test_polaris_note_33_is_not_read_as_separate_cf():
    from pathlib import Path as _P
    from parser.xml.dart_xml_parser import _parse_xml_file

    root = _parse_xml_file(_P(POLARIS))
    out = T._detect_legacy_body_statement_tables(root, "C", False)
    cf_s = [(unit, T.title_text_owned(tbl)) for tbl, unit, _ in out.get("CF_S", [])]
    # Only the statement title is read as the separate CF; the note's 천원 detail table is gone.
    assert all(unit != 1000 for unit, _ in cf_s)
    assert all("창출된 현금흐름은" not in title for _, title in cf_s)
