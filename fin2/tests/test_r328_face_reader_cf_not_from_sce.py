"""R328 - the Gate B face reader never reads a cash flow canonical from an SCE table
(00138729 2025FY: SCE total column '배당금 지급' -10,685,985,250 was taken instead of the
cash flow '배당금의 지급' -10,685,473,600, which is tagged ifrs-full_DividendsPaidOrdinaryShares)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.audit import face_audit  # noqa: E402
from fin2.audit.face_audit import read_report_face_xbrl  # noqa: E402

_HOME = ("CFY2025eFY_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis"
         "_ifrs-full_ConsolidatedMember")
_RE = _HOME + "_ifrs-full_ComponentsOfEquityAxis_ifrs-full_RetainedEarningsMember"


def _te(acode, ctx, text):
    return f'<TE ACODE="{acode}" ACONTEXT="{ctx}" ADECIMAL="0">{text}</TE>'


def _doc():
    sce = ("<TABLE><TR><TE>배당금 지급</TE>"
           + _te("ifrs-full_DividendsPaidClassifiedAsFinancingActivities", _RE, "(10,685,985,250)")
           + _te("ifrs-full_DividendsPaidClassifiedAsFinancingActivities", _HOME, "(10,685,985,250)")
           + "</TR></TABLE>")
    cf = ("<TABLE><TR><TE>(4)배당금의 지급</TE>"
          + _te("ifrs-full_DividendsPaidOrdinaryShares", _HOME, "(10,685,473,600)")
          + "</TR></TABLE>")
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8")
    f.write(f"<DOCUMENT><BODY>{sce}{cf}</BODY></DOCUMENT>")
    f.close()
    return f.name


def _dividends(path):
    return sorted(l.amount_won for l in read_report_face_xbrl(path) if l.canonical == "cf.dividends_paid")


def test_cf_dividend_comes_from_the_cash_flow_table_only(monkeypatch):
    path = _doc()
    assert _dividends(path) == [-10685473600]
    monkeypatch.setattr(face_audit, "_R328_CF_NOT_FROM_SCE", False)
    assert -10685985250 in _dividends(path)


def test_dividends_tag_on_a_row_without_dividend_label_is_ignored():
    """00447007 2024FY tags '리스부채의 원금상환' -302,112,263 with the dividends concept."""
    cf = ("<TABLE><TR><TE>배당금의 지급</TE>"
          + _te("ifrs-full_DividendsPaidOrdinaryShares", _HOME, "(1,951,740,830)")
          + "</TR><TR><TE>리스부채의 원금상환</TE>"
          + _te("ifrs-full_DividendsPaidClassifiedAsFinancingActivities", _HOME, "(302,112,263)")
          + "</TR></TABLE>")
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8")
    f.write(f"<DOCUMENT><BODY>{cf}</BODY></DOCUMENT>")
    f.close()
    assert _dividends(f.name) == [-1951740830]
