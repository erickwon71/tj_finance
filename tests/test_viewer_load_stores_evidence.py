"""The web-view print load and the verification reload store both filing evidences
(2026-11-17: they stored neither; 179 '연결재무제표 해당사항 없음' filings had no evidence)."""
import contextlib

from collector import xbrl_instance_lines_sync as xs
from fin2.extract import consolidation_evidence as ce


class _Session:
    def begin_nested(self):
        return contextlib.nullcontext()


def test_both_evidences_are_stored_and_a_failure_is_not_fatal(monkeypatch):
    calls = []
    monkeypatch.setattr(xs, "store_filing_ifrs_evidence",
                        lambda s, r, file_path=None: calls.append(("ifrs", r, file_path)))

    def boom(s, r, file_path=None):
        calls.append(("cons", r, file_path))
        raise OSError("unreadable")
    monkeypatch.setattr(ce, "store_filing_consolidation_evidence", boom)
    xs.store_filing_evidences(_Session(), "20261116001891", "/x/20261116001891.viewer.xml")
    assert calls == [("ifrs", "20261116001891", "/x/20261116001891.viewer.xml"),
                     ("cons", "20261116001891", "/x/20261116001891.viewer.xml")]


def test_xbrl_zip_source_reads_ifrs_from_the_db_track_only(monkeypatch):
    calls = []
    monkeypatch.setattr(xs, "store_filing_ifrs_evidence",
                        lambda s, r, file_path=None: calls.append(("ifrs", file_path)))
    monkeypatch.setattr(ce, "store_filing_consolidation_evidence",
                        lambda s, r, file_path=None: calls.append(("cons", file_path)))
    xs.store_filing_evidences(_Session(), "r", "/x/r.zip", xml_source=False)
    assert calls == [("ifrs", None), ("cons", "/x/r.zip")]
