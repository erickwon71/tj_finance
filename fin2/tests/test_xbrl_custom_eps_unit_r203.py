"""R203 — EPS tagged with a custom perShareItemType concept and unitRef="SHARES" is stored."""
from __future__ import annotations

from parser.xbrl_instance.instance_parser import QName, XbrlFact, XbrlInstance, XbrlUnit

import fin2.extract.report_lines_xbrl as X

TNS = "http://dart.fss.or.kr/entity01032404"
IFRS = "http://xbrl.ifrs.org/taxonomy/2014-03-05/ifrs-full"
CUSTOM = "udf_IS_2018321135922334_StatementOfComprehensiveIncomeAbstract"

XSD = f"""<?xml version="1.0" encoding="UTF-8"?>
<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:num="http://www.xbrl.org/dtr/type/numeric"
    targetNamespace="{TNS}">
  <xsd:element name="{CUSTOM}" type="num:perShareItemType" abstract="false"/>
  <xsd:element name="udf_Other" type="xbrli:monetaryItemType" abstract="false"/>
  <xsd:element name="udf_PerShareNamed" type="num:perShareItemType"/>
</xsd:schema>
"""


def _instance() -> XbrlInstance:
    shares = QName(ns="http://www.xbrl.org/2003/iso4217", local="shares")
    units = {
        "SHARES": XbrlUnit(id="SHARES", measure=shares),
        "KRW": XbrlUnit(id="KRW", measure=QName(ns="iso4217", local="KRW")),
    }
    facts = [
        XbrlFact(qname=QName(TNS, CUSTOM), context_ref="c", value_raw="347", unit_ref="SHARES"),
        XbrlFact(qname=QName(TNS, "udf_Other"), context_ref="c", value_raw="9", unit_ref="SHARES"),
        XbrlFact(qname=QName(TNS, CUSTOM), context_ref="c", value_raw="5", unit_ref="KRW"),
    ]
    return XbrlInstance(contexts={}, units=units, facts=facts)


def test_custom_per_share_elements_are_found(tmp_path):
    p = tmp_path / "entry_point.xsd"
    p.write_text(XSD, encoding="utf-8")
    found = X._custom_per_share_qnames(p)
    assert found == {QName(TNS, CUSTOM), QName(TNS, "udf_PerShareNamed")}


def test_malformed_xsd_yields_empty(tmp_path):
    p = tmp_path / "bad.xsd"
    p.write_text("<not xml", encoding="utf-8")
    assert X._custom_per_share_qnames(p) == set()


def test_shares_unit_fact_of_custom_eps_becomes_accepted():
    inst = _instance()
    assert X._numeric_value(inst.facts[0], inst.units) is None  # before: dropped
    n = X._normalize_custom_eps_units(inst, {QName(TNS, CUSTOM)})
    assert n == 1
    assert X._numeric_value(inst.facts[0], inst.units) == 347


def test_other_concepts_and_krw_facts_untouched():
    inst = _instance()
    X._normalize_custom_eps_units(inst, {QName(TNS, CUSTOM)})
    assert X._numeric_value(inst.facts[1], inst.units) is None  # non per-share stays rejected
    assert inst.facts[2].unit_ref == "KRW"
    assert X._numeric_value(inst.facts[2], inst.units) == 5


def test_no_custom_per_share_is_a_noop():
    inst = _instance()
    assert X._normalize_custom_eps_units(inst, set()) == 0
    assert inst.facts[0].unit_ref == "SHARES"
