"""R216 — a KRW per-share fact declared to millions (decimals="-6") is divided back to 원."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from parser.xbrl_instance.instance_parser import QName, XbrlFact, XbrlInstance, XbrlUnit

import fin2.extract.report_lines_xbrl as X

TNS = "http://dart.fss.or.kr/entity00138297"
IFRS = "http://xbrl.ifrs.org/taxonomy/2014-03-05/ifrs-full"
UDF_EPS = "udf_IS_2013515142558406_EarningsPerShareAbstract"
_RAW = Path(__file__).resolve().parents[2] / "raw_report"


def _instance(*facts: XbrlFact) -> XbrlInstance:
    units = {
        "KRW": XbrlUnit(id="KRW", measure=QName(ns="iso4217", local="KRW")),
        "SHARES": XbrlUnit(id="SHARES", measure=QName(ns="http://www.xbrl.org/2003/instance",
                                                      local="shares")),
    }
    return XbrlInstance(contexts={}, units=units, facts=list(facts))


def _fact(local, value, unit="KRW", decimals="-6", ns=TNS) -> XbrlFact:
    return XbrlFact(qname=QName(ns, local), context_ref="c", value_raw=value, unit_ref=unit,
                    decimals=decimals)


def test_stx_udf_eps_in_millions_is_divided_back():
    inst = _instance(_fact(UDF_EPS, "2753000000"), _fact(UDF_EPS, "-11509000000"))
    assert X._rescale_scaled_krw_per_share(inst, set()) == 2
    assert [X._numeric_value(f, inst.units) for f in inst.facts] == [2753, -11509]
    assert inst.facts[0].decimals == "0"


def test_custom_per_share_concept_without_pershare_in_name():
    inst = _instance(_fact("udf_Abstract", "1317000000"))
    assert X._rescale_scaled_krw_per_share(inst, {QName(TNS, "udf_Abstract")}) == 1
    assert X._numeric_value(inst.facts[0], inst.units) == 1317


def test_untouched_cases():
    inst = _instance(
        _fact("udf_Revenue", "2753000000"),                          # not per-share
        _fact("BasicEarningsLossPerShare", "2753", "SHARES", "INF", IFRS),  # R170-c unit
        _fact("BasicEarningsLossPerShare", "12000", decimals="-3", ns=IFRS),  # -3 is not enough
        _fact("BasicEarningsLossPerShare", "2753", decimals="0", ns=IFRS),
        _fact(UDF_EPS, "2753500000"),                                # not a whole multiple
        _fact(UDF_EPS, "2753000000", decimals=None),
    )
    before = [f.value_raw for f in inst.facts]
    assert X._rescale_scaled_krw_per_share(inst, set()) == 0
    assert [f.value_raw for f in inst.facts] == before


def _extract(rel, rcept, corp, fy, fp, ped):
    path = _RAW / rel
    if not path.exists():
        return None
    return X.extract_report_lines_xbrl(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                       report_fiscal_period=fp, period_end_date=ped)


def test_stx_2017h1_continuing_eps():
    """이슈 #88123 — 연결 IS 기본주당계속영업이익 원문 2,753원, DB 2,753,000,000."""
    lines = _extract("KOSPI/00138297_STX/half/2017/20171117000482.zip", "20171117000482",
                     "00138297", 2017, "H1", date(2017, 6, 30))
    if lines is None:
        return
    eps = {(l.label_raw, l.col_index, l.is_cumulative): l.value_won for l in lines
           if l.statement == "IS" and l.basis == "consolidated" and "주당" in l.label_raw}
    cont = {k: v for k, v in eps.items() if "계속영업" in k[0]}
    assert cont and all(abs(v) < 1_000_000 for v in cont.values())
    assert 2753 in cont.values()


def test_songwon_2016h1_separate_eps():
    """송원산업 별도 IS 기본주당이익 원문 1,317원 (이슈 미등록, 같은 패턴)."""
    lines = _extract("KOSPI/00134963_송원산업/half/2016/20160901000022.zip", "20160901000022",
                     "00134963", 2016, "H1", date(2016, 6, 30))
    if lines is None:
        return
    eps = [l.value_won for l in lines
           if l.statement == "IS" and l.basis == "separate" and "주당" in l.label_raw]
    assert eps and all(abs(v) < 1_000_000 for v in eps)
    assert 1317 in eps
