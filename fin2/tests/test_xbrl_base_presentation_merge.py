"""
R170 — DART delta presentation linkbase + shared base presentation merge
(parser/xbrl_instance/taxonomy_linkbase.py::_build_merged_presentation_tree).

Synthetic linkbases pin the XBRL relationship semantics (prohibition by
priority, filer-over-base placement, parent resolution by concept, IS-only
base de-negation); real-filing tests pin the batch #4 recoveries.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from parser.xbrl_instance.taxonomy_linkbase import (  # noqa: E402
    _denegate_role, parse_presentation,
)
from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl  # noqa: E402

_ROLE = "http://dart.fss.or.kr/role/ifrs/dart_2013-03-31_role-D310005"
_NS = {"ifrs": "http://xbrl.iasb.org/taxonomy/2009-04-01/ifrs",
       "dart": "http://dart.fss.or.kr/2013-03-31/dart"}
_NEG = "http://www.xbrl.org/2009/role/negatedTerseLabel"


def _linkbase(locs: list[str], arcs: list[tuple]) -> str:
    """locs: loc labels shaped '{prefix}_{Local}[suffix]'; arcs: (from, to, order, extra-attrs)."""
    body = []
    for label in locs:
        concept = label.split("#")[0]
        body.append(f'<link:loc xlink:type="locator" xlink:href="x.xsd#{concept}" xlink:label="{label}"/>')
    for frm, to, order, extra in arcs:
        body.append(f'<link:presentationArc xlink:type="arc" '
                    f'xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" '
                    f'xlink:from="{frm}" xlink:to="{to}" order="{order}" {extra}/>')
    return ('<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" '
            'xmlns:xlink="http://www.w3.org/1999/xlink">'
            f'<link:presentationLink xlink:type="extended" xlink:role="{_ROLE}">'
            + "".join(body) + "</link:presentationLink></link:linkbase>")


def _tree(tmp_path: Path, filer: str, base: str, denegate: bool = False):
    fp, bp = tmp_path / "pre_filer.xml", tmp_path / "pre_base.xml"
    fp.write_text(filer, encoding="utf-8")
    bp.write_text(base, encoding="utf-8")
    trees = parse_presentation(fp, _NS, {_ROLE: [bp]},
                               denegate_base_roles=frozenset({_ROLE}) if denegate else frozenset())
    return trees[_ROLE]


def _children(tree, local: str) -> list[str]:
    node = next(n for n in tree.nodes.values() if n.element.local == local)
    return [tree.nodes[c].element.local for c in node.children]


_BASE = _linkbase(
    ["ifrs_IncomeStatementAbstract", "ifrs_Revenue", "ifrs_GrossProfit",
     "ifrs_IncomeTaxExpenseContinuingOperations", "dart_OperatingIncomeLoss", "ifrs_ProfitLoss"],
    [("ifrs_IncomeStatementAbstract", "ifrs_Revenue", "1.0", ""),
     ("ifrs_IncomeStatementAbstract", "ifrs_GrossProfit", "3.0", ""),
     ("ifrs_IncomeStatementAbstract", "dart_OperatingIncomeLoss", "4.0", ""),
     ("ifrs_IncomeStatementAbstract", "ifrs_IncomeTaxExpenseContinuingOperations", "21.0",
      f'preferredLabel="{_NEG}"'),
     ("ifrs_IncomeStatementAbstract", "ifrs_ProfitLoss", "22.0", "")],
)


def test_base_only_concepts_join_the_filer_tree(tmp_path):
    """한화엔진 20150515002710 형태: 회사 파일엔 GrossProfit 이 아예 없고 base 에만
    있다 — 병합 트리엔 들어와야 한다."""
    filer = _linkbase(["ifrs_IncomeStatementAbstract", "ifrs_Revenue"],
                      [("ifrs_IncomeStatementAbstract", "ifrs_Revenue", "1.0", 'priority="1"')])
    tree = _tree(tmp_path, filer, _BASE)
    assert _children(tree, "IncomeStatementAbstract") == [
        "Revenue", "GrossProfit", "OperatingIncomeLoss", "IncomeTaxExpenseContinuingOperations", "ProfitLoss"]
    assert sum(n.element.local == "Revenue" for n in tree.nodes.values()) == 1  # equivalent arcs collapse


def test_prohibited_base_arc_removes_the_concept(tmp_path):
    filer = _linkbase(["ifrs_IncomeStatementAbstract", "ifrs_GrossProfit"],
                      [("ifrs_IncomeStatementAbstract", "ifrs_GrossProfit", "3.0",
                        'use="prohibited" priority="1"')])
    tree = _tree(tmp_path, filer, _BASE)
    assert "GrossProfit" not in {n.element.local for n in tree.nodes.values()}


def test_filer_replacement_arc_beats_base_placement(tmp_path):
    """회사가 base arc 를 prohibit 하고 다른 order 로 다시 걸면 한 번만, 회사 위치로."""
    filer = _linkbase(
        ["ifrs_IncomeStatementAbstract", "ifrs_GrossProfit", "ifrs_GrossProfit#new"],
        [("ifrs_IncomeStatementAbstract", "ifrs_GrossProfit", "3.0", 'use="prohibited" priority="1"'),
         ("ifrs_IncomeStatementAbstract", "ifrs_GrossProfit#new", "0.5", 'priority="2"')])
    tree = _tree(tmp_path, filer, _BASE)
    assert _children(tree, "IncomeStatementAbstract")[0] == "GrossProfit"
    assert sum(n.element.local == "GrossProfit" for n in tree.nodes.values()) == 1


def test_filer_addition_without_prohibition_does_not_duplicate(tmp_path):
    filer = _linkbase(["ifrs_IncomeStatementAbstract", "ifrs_GrossProfit#x"],
                      [("ifrs_IncomeStatementAbstract", "ifrs_GrossProfit#x", "2.5", "")])
    tree = _tree(tmp_path, filer, _BASE)
    assert sum(n.element.local == "GrossProfit" for n in tree.nodes.values()) == 1


def test_orphaned_parent_locator_resolves_by_concept(tmp_path):
    """엘앤에프 20151104000116 형태: 부모 loc 자신은 prohibited 로만 도달돼 탈락하고,
    같은 개념의 새 loc 이 다시 걸렸는데 자식 arc 는 옛 loc 에서 나간다 — 자식은
    같은 개념의 노드 밑으로 붙어야 한다(수정 전엔 arc 가 통째로 버려졌다)."""
    base = _linkbase(["ifrs_LiabilitiesAbstract", "ifrs_CurrentLiabilities"],
                     [("ifrs_LiabilitiesAbstract", "ifrs_CurrentLiabilities", "1.0", "")])
    filer = _linkbase(
        ["ifrs_LiabilitiesAbstract", "ifrs_CurrentLiabilities", "ifrs_CurrentLiabilities#new",
         "dart_ShortTermBorrowings#new"],
        [("ifrs_LiabilitiesAbstract", "ifrs_CurrentLiabilities", "1.0", 'use="prohibited" priority="1"'),
         ("ifrs_LiabilitiesAbstract", "ifrs_CurrentLiabilities#new", "0.5", 'priority="2"'),
         ("ifrs_CurrentLiabilities", "dart_ShortTermBorrowings#new", "0.75", 'priority="2"')])
    tree = _tree(tmp_path, filer, base)
    assert _children(tree, "CurrentLiabilities") == ["ShortTermBorrowings"]
    assert _children(tree, "LiabilitiesAbstract") == ["CurrentLiabilities"]


def test_is_base_negation_dropped_only_when_asked(tmp_path):
    filer = _linkbase(["ifrs_IncomeStatementAbstract"], [])
    kept = _tree(tmp_path, filer, _BASE, denegate=False)
    dropped = _tree(tmp_path, filer, _BASE, denegate=True)
    tax = "IncomeTaxExpenseContinuingOperations"
    assert next(n for n in kept.nodes.values() if n.element.local == tax).preferred_label == _NEG
    assert next(n for n in dropped.nodes.values()
                if n.element.local == tax).preferred_label == "http://www.xbrl.org/2003/role/terseLabel"


def test_denegate_role_mapping():
    assert _denegate_role("http://www.xbrl.org/2009/role/negatedLabel") == "http://www.xbrl.org/2003/role/label"
    assert _denegate_role("http://www.xbrl.org/2009/role/negatedTotalLabel") == \
        "http://www.xbrl.org/2003/role/totalLabel"
    assert _denegate_role("http://www.xbrl.org/2009/role/negatedNetLabel") == "http://www.xbrl.org/2009/role/netLabel"
    assert _denegate_role("http://www.xbrl.org/2003/role/terseLabel") == "http://www.xbrl.org/2003/role/terseLabel"
    assert _denegate_role(None) is None


# ── real filings (skipped when raw_report isn't mounted) ─────────────────────
_RAW = Path(__file__).resolve().parents[2] / "raw_report"


def _lines(rel: str, rcept: str, corp: str, fy: int, fp: str, ped: date):
    path = _RAW / rel
    if not path.exists():
        return None
    return extract_report_lines_xbrl(path, rcept_no=rcept, corp_code=corp, report_fiscal_year=fy,
                                     report_fiscal_period=fp, period_end_date=ped)


def test_hanwha_engine_2015q1_separate_is_complete():
    """batch #4 이슈 #24093·#24097·#24149·#24151 — 원문 별도 손익계산서 값."""
    lines = _lines("KOSPI/00361008_한화엔진/quarter/2015/20150515002710.zip",
                   "20150515002710", "00361008", 2015, "Q1", date(2015, 3, 31))
    if lines is None:
        return
    is_s = {l.source_ref.split("/")[1]: l.value_won
            for l in lines if l.statement == "IS" and l.basis == "separate" and l.col_index == 0}
    assert is_s["GrossProfit"] == -782_632_621
    assert is_s["OperatingIncomeLoss"] == -11_411_155_327
    assert is_s["IncomeTaxExpenseContinuingOperations"] == -2_585_746_745  # 원문 (2,585,746,745)
    assert is_s["BasicEarningsLossPerShare"] == -115  # unitRef="SHARES" (R170-c)
    assert is_s["ProfitLoss"] == -8_010_347_261


def test_lnf_2015q3_consolidated_borrowings_under_current_liabilities():
    """batch #4 이슈 #19166·#19167 — 고아 loc 밑 arc 가 버려져 빠졌던 행."""
    lines = _lines("KOSPI/00398701_엘앤에프/quarter/2015/20151104000116.zip",
                   "20151104000116", "00398701", 2015, "Q3", date(2015, 9, 30))
    if lines is None:
        return
    bs_c = {l.source_ref.split("/")[1]: l for l in lines
            if l.statement == "BS" and l.basis == "consolidated" and l.col_index == 0}
    assert bs_c["ShortTermBorrowings"].value_won == 42_554_298_115
    assert bs_c["CurrentPortionOfLongtermBorrowings"].value_won == 3_981_720_000
    assert bs_c["ShortTermBorrowings"].section_path and "유동부채" in bs_c["ShortTermBorrowings"].section_path


def test_daehan_2017h1_cf_outflows_keep_base_negation():
    """batch #4 이슈 #83810·#83811 — CF base 의 유출 negation 은 원문 괄호와 일치(유지)."""
    lines = _lines("KOSDAQ/00113261_대한광통신/half/2017/20170818000262.zip",
                   "20170818000262", "00113261", 2017, "H1", date(2017, 6, 30))
    if lines is None:
        return
    cf_s = {l.source_ref.split("/")[1]: l.value_won
            for l in lines if l.statement == "CF" and l.basis == "separate" and l.col_index == 0}
    assert cf_s["InterestPaidClassifiedAsOperatingActivities"] == -454_000_662
    assert cf_s["IncomeTaxesPaidRefundClassifiedAsOperatingActivities"] == -6_326_321


# ── R170-d: 법인세 부호는 세전 − 법인세 = 계속영업이익 등식으로 확정 ─────────────
def _is_row(local: str, value: int, basis: str = "separate", col: int = 0):
    from fin2.extract.report_lines import ReportLineRow
    return ReportLineRow(corp_code="x", rcept_no="r", report_fiscal_year=2015, report_fiscal_period="Q3",
                         statement="IS", basis=basis, section_path=None, label_raw=local, col_index=col,
                         context_fiscal_year=2015, period_kind="duration", is_cumulative=True,
                         value_won=value, adecimal=0, unit_source="xbrl",
                         source_ref=f"IS_{basis}/{local}", context_raw="c", row_order=0, depth=0,
                         node_role="F", table_seq=0, table_title=None)


def test_tax_sign_flipped_only_when_identity_proves_it():
    from fin2.extract.report_lines_xbrl import _settle_is_tax_sign
    rows = [_is_row("ProfitLossBeforeTax", -207_824_678),
            _is_row("IncomeTaxExpenseContinuingOperations", -38_948_803),
            _is_row("ProfitLoss", -246_773_481)]
    tax = next(r for r in _settle_is_tax_sign(rows) if "IncomeTax" in r.source_ref)
    assert tax.value_won == 38_948_803


def test_tax_sign_kept_when_identity_already_holds_or_is_unprovable():
    from fin2.extract.report_lines_xbrl import _settle_is_tax_sign
    ok = [_is_row("ProfitLossBeforeTax", -10_596_094_006),
          _is_row("IncomeTaxExpenseContinuingOperations", -2_585_746_745),
          _is_row("ProfitLossFromContinuingOperations", -8_010_347_261)]
    assert _settle_is_tax_sign(ok)[1].value_won == -2_585_746_745
    unprovable = [_is_row("ProfitLossBeforeTax", 1_000),
                  _is_row("IncomeTaxExpenseContinuingOperations", 100),
                  _is_row("ProfitLoss", 555)]  # 중단영업 등 — 어느 쪽도 성립 안 함
    assert _settle_is_tax_sign(unprovable)[1].value_won == 100


def test_lnf_2015q3_separate_tax_sign_follows_identity():
    lines = _lines("KOSPI/00398701_엘앤에프/quarter/2015/20151104000116.zip",
                   "20151104000116", "00398701", 2015, "Q3", date(2015, 9, 30))
    if lines is None:
        return
    is_s = {l.source_ref.split("/")[1]: l.value_won
            for l in lines if l.statement == "IS" and l.basis == "separate" and l.col_index == 0}
    assert is_s["IncomeTaxExpenseContinuingOperations"] == 38_948_803


# ── R175: CF 표시부호 = 계산 weight 누적곱(표 자신의 부모=Σ자식 등식이 더 성립할 때만) ──
def test_r175_lnf_cf_deduction_group_items_are_negative():
    lines = _lines("KOSPI/00398701_엘앤에프/quarter/2015/20151104000116.zip",
                   "20151104000116", "00398701", 2015, "Q3", date(2015, 9, 30))
    if lines is None:
        return
    cf_c = {l.label_raw: l.value_won for l in lines
            if l.statement == "CF" and l.basis == "consolidated" and l.col_index == 0}
    assert cf_c["이자수익"] == -12_568_236          # 원문 (12,568,236)
    assert cf_c["외화환산이익"] == -292_686_451
    assert cf_c["단기금융상품의 취득"] == -2_501_324_561


def test_r175_filer_with_negative_facts_keeps_r10_signs():
    """박셀바이오: 유출 fact 를 이미 음수로 태깅 + weight −1 — weight 를 쓰면 등식이 깨지므로 R10 유지."""
    lines = _lines("KOSDAQ/01335851_박셀바이오/half/2024/20250828000534.zip",
                   "20250828000534", "01335851", 2024, "H1", date(2024, 6, 30))
    if lines is None:
        return
    cf_s = {l.source_ref.split("/")[1]: l.value_won for l in lines
            if l.statement == "CF" and l.basis == "separate" and l.col_index == 0}
    assert cf_s["PurchaseOfFinancialAssetsAtFairValueThroughProfitOrLossClassifiedAsInvestingActivities"] == -1_910_000_000


# ── R176: XBRL SCE 소유주거래 행 부호 = 롤포워드 등식(기초+Σ변동=기말)이 증명할 때만 반전 ──
def test_r176_sk_gas_sce_dividends_negative():
    """원문 (22,340,715,800)[자본 합계]·(22,770,340,800)[이익잉여금]. 기타자본 열의 +429,625,000
    (자기주식분 배당)은 원문도 양수 — 합계 = 이익잉여금 + 기타 로 서로 맞는다."""
    lines = _lines("KOSPI/00144164_SK가스/quarter/2017/20171117000389.zip",
                   "20171117000389", "00144164", 2017, "Q3", date(2017, 9, 30))
    if lines is None:
        return
    div = {l.value_won for l in lines if l.statement == "SCE" and l.basis == "separate"
           and l.source_ref.endswith("/DividendsPaid")}
    assert -22_340_715_800 in div and -22_770_340_800 in div
    assert 22_340_715_800 not in div


# ── R177: XBRL SCE canonical_dates(row_order 기간 순서)는 행마다 따로 잡지 않고 표 전체에서 한 번만 잡는다 ──
def test_r177_sk_gas_sce_treasury_share_no_chain_shift():
    """SK가스 2017Q1 연결 SCE '자기주식 취득' — 당기(2017Q1)엔 원문에 이 행이 전열 공백인데,
    행마다 따로 날짜를 랭킹하던 예전 코드는 이 개념의 total 열 날짜 목록이 다른 행보다 하나
    짧다는 이유로 FY2016 값을 당기 칸에, FY2015 값을 FY2016 칸에 밀어넣고 FY2015 칸은
    비워버렸다(3구간 연쇄 오귀속, batch #11 이슈 #84674~84680/84825~84835). 원문 실제값:
    당기=공백, FY2016=(154,645,788), FY2015=(131,459,328)(별도 CF·SCE 재무활동 자기주식의
    취득 열 제32기/제31기와 대조 확정)."""
    lines = _lines("KOSPI/00144164_SK가스/quarter/2017/20170529000325.zip",
                   "20170529000325", "00144164", 2017, "Q1", date(2017, 3, 31))
    if lines is None:
        return
    treasury = {l.row_order: l.value_won for l in lines
                if l.statement == "SCE" and l.basis == "consolidated" and l.col_index == 0
                and l.label_raw == "자기주식 취득"}
    assert not any(o <= 17 for o in treasury), "당기(2017Q1) 블록엔 원문 공백 — 값이 있으면 안 된다"
    assert treasury.get(32) == -154_645_788   # FY2016 블록
    assert treasury.get(68) == -131_459_328   # FY2015 블록


# ── R162-f: 원문 소계행이 틀려(R162-c 산술증명 실패) 이중계상되던 블록도 라벨소계 제외로 단일셀 반전 ──
def test_r162f_lg_dividends_negative_despite_inconsistent_subtotal():
    """LG전자 2024FY 연결 '자본 증가(감소) 합계' 2,389,964 ≠ 실제 변동 2,393,964(사업결합 4,000 누락)."""
    path = _RAW / "KOSPI/00401731_LG전자/annual/2024/20250317001029.xml"
    if not path.exists():
        return
    from fin2.extract.report_lines import extract_report_lines
    rows = extract_report_lines(path, rcept_no="20250317001029", corp_code="00401731",
                                report_fiscal_year=2024, report_fiscal_period="FY")
    div = {r.value_won for r in rows if r.statement == "SCE" and r.basis == "consolidated"
           and r.label_raw.strip() == "배당" and r.col_index == 8}
    assert div == {-231_468_000_000, -240_987_000_000, -316_709_000_000}


# ── 개별 확정(fix batch #13, 2026-09-26): IS '재분류 OCI 관련 법인세' 부호 예외목록 ──
def test_manual_is_sign_fix_e1_reclass_oci_tax():
    """E1 2017Q1 20180130000271 — '당기손익으로 재분류되는 기타포괄손익의 구성요소와
    관련된 법인세'는 R170-d(IncomeTaxExpenseContinuingOperations, 본선 법인세)가 보지
    않는 별개 개념이다. 연결·별도 모두 세전재분류OCI − OCI = 이 값 등식으로 원문 부호가
    자기증명되는데(연결 -3,541,999,661-(-4,712,736,047)=+1,170,736,386, 별도
    55,600,396-73,351,436=-17,751,040) 파서가 반대로 저장했다."""
    from fin2.extract.report_lines_xbrl import _apply_manual_is_sign_fixes
    local = ("IncomeTaxRelatingToComponentsOfOtherComprehensiveIncomeThatWillBeReclassified"
             "ToProfitOrLoss")
    con = _is_row(local, -1_170_736_386, basis="consolidated")
    sep = _is_row(local, 17_751_040, basis="separate")
    fixed = _apply_manual_is_sign_fixes([con, sep], "20180130000271")
    by_basis = {r.basis: r.value_won for r in fixed}
    assert by_basis["consolidated"] == 1_170_736_386
    assert by_basis["separate"] == -17_751_040


def test_manual_is_sign_fix_scoped_to_rcept():
    from fin2.extract.report_lines_xbrl import _apply_manual_is_sign_fixes
    local = ("IncomeTaxRelatingToComponentsOfOtherComprehensiveIncomeThatWillBeReclassified"
             "ToProfitOrLoss")
    con = _is_row(local, -1_170_736_386, basis="consolidated")
    fixed = _apply_manual_is_sign_fixes([con], "99999999999999")
    assert fixed[0].value_won == -1_170_736_386
