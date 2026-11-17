"""R325 - consolidation evidence is read from the web-view print of an XBRL-zip / PDF filing.
R326 - when the last filing of a period declares no consolidated statements, the consolidated cells
of the earlier filings are not merged (00323868 2019Q1 / H1, [기재정정] "연결재무제표 작성 제외")."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract import consolidation_evidence as ce  # noqa: E402
from fin2.layer3 import combine  # noqa: E402
from fin2.layer3.combine import build_merged_lines  # noqa: E402

_SECTION = ("<SECTION-2><TITLE>2. 연결재무제표</TITLE><P>해당사항 없음</P></SECTION-2>"
            "<SECTION-2><TITLE>4. 재무제표</TITLE></SECTION-2>")


def test_r325_viewer_print_next_to_zip_gives_the_evidence(tmp_path):
    (tmp_path / "20190821000075.zip").write_bytes(b"PK")
    (tmp_path / "20190821000075.viewer.xml").write_text(_SECTION, encoding="utf-8")
    ev, _ = ce.resolve_filing_evidence(None, "20190821000075", file_path=tmp_path / "20190821000075.zip")
    assert ev == ce.EVIDENCE_NO_CONSOLIDATED_FS


def test_r325_zip_without_viewer_print_has_no_evidence(tmp_path):
    (tmp_path / "20190821000075.zip").write_bytes(b"PK")
    ev, _ = ce.resolve_filing_evidence(None, "20190821000075", file_path=tmp_path / "20190821000075.zip")
    assert ev is None


def _rows(basis, labels, values):
    return [("BS", basis, 0, None, lab, val, "S", 0, False, None, False, None, i)
            for i, (lab, val) in enumerate(zip(labels, values))]


_LABELS = ["유동자산", "비유동자산", "자산총계", "유동부채", "비유동부채", "부채총계", "자본금", "이익잉여금", "자본총계"]
_ROWS = {
    "orig": _rows("consolidated", _LABELS, [10, 20, 30, 12, 8, 20, 5, 5, 10])
            + _rows("separate", _LABELS, [9, 19, 28, 11, 7, 18, 5, 5, 10]),
    "amend": _rows("separate", _LABELS, [9, 19, 28, 11, 7, 18, 5, 5, 10]),
}


class _Result:
    def __init__(self, rows): self._rows = rows
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, evidence): self._ev = evidence

    def execute(self, stmt, params):
        sql = str(stmt)
        if "consolidation_evidence" in sql:
            return _Result([(self._ev.get(params["r"]),)])
        if "period_end_date" in sql:
            return _Result([(r, None) for r in params["r"]])
        if "FROM filings f" in sql:
            return _Result([("orig", False), ("amend", True)])
        if "bool_or(unit_source = 'xbrl')" in sql:
            return _Result([(False, False)])
        return _Result(_ROWS[params["r"]])


def _bases(evidence):
    return {c["basis"] for c in build_merged_lines(_Session(evidence), "00323868", 2019, "Q1")}


def test_r326_final_declares_no_consolidated_drops_earlier_consolidated(monkeypatch):
    assert _bases({"amend": "no_consolidated_fs_track1"}) == {"separate"}
    monkeypatch.setattr(combine, "_R326_FINAL_NO_CONSOLIDATED", False)
    assert _bases({"amend": "no_consolidated_fs_track1"}) == {"consolidated", "separate"}


def test_r326_without_the_declaration_keeps_consolidated():
    assert _bases({}) == {"consolidated", "separate"}
    # only an EARLIER filing declaring it does not withdraw the consolidated cells
    assert _bases({"orig": "no_consolidated_fs_track1"}) == {"consolidated", "separate"}
