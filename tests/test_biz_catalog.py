"""Regression tests for the B5 caption catalog.

Every case pins a **defect observed in real filings** (the table shapes below are condensed
from actual documents, not invented). All were found while building
docs/qa/biz_section_items_shortlist_2026-07-31.md.
"""
from __future__ import annotations

from lxml import etree

from fin2.extract.biz_catalog import (CaptionedTable, classify_caption,
                                      extract_catalog_from_root, grid_key,
                                      map_catalog_table, normalize_caption,
                                      walk_captioned_tables)
from fin2.extract.biz_section import _parse_value


def _ct(grid, caption="가. 주요 제품 등의 현황", narrative="", subsection="주요제품및서비스"):
    return CaptionedTable(subsection=subsection, caption=normalize_caption(caption),
                          caption_raw=caption, narrative=narrative, grid=grid)


# ─────────────────────────────────────────────────────────────────────────────
# Caption classification
# ─────────────────────────────────────────────────────────────────────────────
class TestClassifyCaption:
    def test_derivative_not_product(self):
        """'파생상품…' must not match product_status through the substring '상품'.

        Measured misclassification on Samsung Electronics.
        """
        assert classify_caption(normalize_caption("다. 파생상품 및 풋백옵션 등 거래 현황")) == "derivative"

    def test_price_trend_beats_status(self):
        assert classify_caption(normalize_caption("나. 주요 제품 등의 가격변동추이")) == "product_price"
        assert classify_caption(normalize_caption("나. 주요 원재료 등의 가격변동 추이")) == "material_price"
        assert classify_caption(normalize_caption("가. 주요 원재료 등의 현황")) == "material_status"

    def test_owned_by_existing_parsers_skipped(self):
        """Production / sales / R&D expense belong to the existing parsers.

        Catching them here would mean double loading.
        """
        for cap in ("(1) 생산능력", "가. 매출실적", "다. 연구개발비용", "(2) 당해 사업연도의 가동률"):
            assert classify_caption(normalize_caption(cap)) is None, cap

    def test_risk_note_reposts_excluded(self):
        """Risk-management tables are re-postings of the notes — already in note_lines (census F2)."""
        for cap in ("다. 유동성위험", "(1) 외환위험", "② 이자율 위험", "3) 신용위험"):
            assert classify_caption(normalize_caption(cap)) is None, cap

    def test_industry_specific(self):
        cases = {
            "나. 지급여력비율": "ins_solvency",
            "(2) 보험종목별 수입보험료 내역": "ins_premium",
            "라. 보험종목별 보험금 내역": "ins_claim",
            "(3) 자금조달ㆍ운용현황": "fund_flow",
            "(4) 자금운용 실적": "fund_use",
            "4) 환매조건부채권 매매업무": "brokerage",
            "(2) 도급토목공사": "construction",
            "(2) 주요 재고자산의 현황": "inventory",
            "라. 핵심 연구인력": "rd_staff",
            "1) 생산설비의 현황": "facility",
            "(1) 사업부문별 요약 재무현황": "segment_fin",
            "(5) 시장 점유율": "market_share",
            "다. 주요 매출처": "customer",
            "(나) 향후 투자계획": "capex_plan",
            "가. 지적재산권 보유 현황": "ip_right",
        }
        for cap, expected in cases.items():
            assert classify_caption(normalize_caption(cap)) == expected, cap


# ─────────────────────────────────────────────────────────────────────────────
# Value parsing — fixes made to the shared _parse_value
# ─────────────────────────────────────────────────────────────────────────────
class TestParseValue:
    def test_triangle_negative(self):
        """DART writes negatives as '△'. Without support the cell is dropped entirely.

        Measured: Samsung Electronics '기타 △285,155'.
        """
        assert _parse_value("△285,155")[0] == -285155.0
        assert _parse_value("△9.5%")[:2] == (-9.5, True)

    def test_paren_negative_has_no_unit(self):
        """The closing paren of a parenthesized negative must not leak in as the unit ')'.

        Measured: 한솔홈데코 operating profit -703.
        """
        val, is_ratio, unit = _parse_value("(703)")
        assert (val, is_ratio, unit) == (-703.0, False, None)

    def test_paren_ratio_negative(self):
        val, is_ratio, unit = _parse_value("(24.7%)")
        assert val == -24.7 and is_ratio and unit is None

    def test_increase_marker_untouched(self):
        """'▲' also denotes an increase, so its meaning is not settled — leave it alone."""
        assert _parse_value("▲1,000")[0] is None


# ─────────────────────────────────────────────────────────────────────────────
# grid -> long-format mapping
# ─────────────────────────────────────────────────────────────────────────────
class TestMapCatalogTable:
    def test_table_wide_unit_row_does_not_eat_label_column(self):
        """A '(단위 : 백만원)' row replicated across all columns by COLSPAN made the label
        column look like the unit column.

        Measured: 한솔홈데코 20260311003988 — every segment came out NULL and the segment
        names ended up in unit.
        """
        grid = [
            ["(단위 : 백만원)", "(단위 : 백만원)", "(단위 : 백만원)"],
            ["구분", "제 34기", "제 34기"],
            ["구분", "부문매출", "영업이익"],
            ["목재", "274,860", "(703)"],
            ["열병합발전", "4,957", "4,011"],
        ]
        rows = map_catalog_table(_ct(grid, "2) 사업부문별 요약재무현황"), "segment_fin", 2025)
        segs = {r.segment for r in rows}
        assert segs == {"목재", "열병합발전"}
        assert all(r.unit == "백만원" for r in rows), [r.unit for r in rows]

    def test_measure_columns_stay_distinguishable(self):
        """When revenue and profit split under one period, period_label must keep them apart."""
        grid = [
            ["구분", "제 34기", "제 34기"],
            ["구분", "부문매출", "영업이익"],
            ["목재", "274,860", "(703)"],
        ]
        rows = map_catalog_table(_ct(grid, "2) 사업부문별 요약재무현황"), "segment_fin", 2025)
        by_label = {r.period_label: r.value for r in rows}
        assert by_label == {"제34기 부문매출": 274860.0, "제34기 영업이익": -703.0}
        assert all(r.period_year == 2025 for r in rows)

    def test_bare_year_header_is_not_data(self):
        """A header row of bare years was judged a data row, discarding the whole table.

        Measured: 한화생명 보험종목별 수입보험료 — 21 insurer tables produced zero rows.
        """
        grid = [
            ["구분", "구분", "2025", "2025", "2024"],
            ["구분", "구분", "금액", "비율", "금액"],
            ["생명보험", "보장성보험", "10,086,939", "51.0", "8,345,778"],
        ]
        rows = map_catalog_table(_ct(grid, "(2) 보험종목별 수입보험료 내역"), "ins_premium", 2025)
        assert rows, "a bare-year header row must not discard the table"
        got = {(r.segment, r.item, r.period_label): r.value for r in rows}
        assert got[("생명보험", "보장성보험", "2025년 금액")] == 10086939.0
        assert got[("생명보험", "보장성보험", "2025년 비율")] == 51.0
        assert got[("생명보험", "보장성보험", "2024년 금액")] == 8345778.0

    def test_dash_placeholders_do_not_flip_value_column(self):
        """A value column full of '-' flipped to a dimension column, turning numbers into labels.

        Measured: 한국컴퓨터 20260316000809 material price trend produced item='5.32'.
        """
        grid = [
            ["품목", "OLED제품 소요", "OLED제품 소요", "산업용 제품 소요"],
            ["품목", "제32기", "제30기", "제32기"],
            ["C-CHIP 류", "5.15", "5.32", "-"],
            ["R-CHIP 류", "6.69", "0.58", "-"],
            ["SHIELD CAN 류", "246.93", "-", "-"],
        ]
        rows = map_catalog_table(_ct(grid, "나. 주요 원재료 등의 가격변동추이"), "material_price", 2025)
        assert all(r.item is None for r in rows), [r.item for r in rows]
        vals = {(r.segment, r.period_label): r.value for r in rows}
        assert vals[("C-CHIP 류", "제32기 OLED제품 소요")] == 5.15
        assert vals[("C-CHIP 류", "제30기 OLED제품 소요")] == 5.32

    def test_product_group_headers_do_not_collide(self):
        """Repeated product-group headers must not collapse the same period into one key."""
        grid = [
            ["품목", "OLED(OLED-MOBILE PBA제품 소요)", "산업용-INVERTER등제품 소요"],
            ["품목", "제32기", "제32기"],
            ["CONNECTOR 류", "172.84", "182.44"],
        ]
        rows = map_catalog_table(_ct(grid, "나. 주요 원재료 등의 가격변동추이"), "material_price", 2025)
        assert len({r.period_label for r in rows}) == 2, [r.period_label for r in rows]

    def test_headerless_table_is_not_guessed(self):
        """Without a header the column meanings are unknown — drop it rather than guess."""
        assert map_catalog_table(_ct([["1,000", "2,000"], ["3,000", "4,000"]]),
                                 "product_status", 2025) == []


# ─────────────────────────────────────────────────────────────────────────────
# Document traversal — the two source-document traps
# ─────────────────────────────────────────────────────────────────────────────
def _doc(body: str) -> etree._Element:
    return etree.fromstring(
        f"<DOCUMENT><SECTION-2><TITLE>II. 사업의 내용</TITLE>"
        f"<SECTION-2><TITLE>2. 주요 제품 및 서비스</TITLE>{body}</SECTION-2></SECTION-2>"
        f"<SECTION-2><TITLE>III. 재무에 관한 사항</TITLE></SECTION-2></DOCUMENT>".encode(),
        etree.XMLParser(recover=True, huge_tree=True))


_REAL_TABLE = ("<TABLE><TR><TD>부문</TD><TD>매출액</TD></TR>"
               "<TR><TD>DX부문</TD><TD>1,748,877</TD></TR></TABLE>")


class TestWalkCaptionedTables:
    def test_text_wrapper_table_does_not_steal_caption(self):
        """DART wraps narrative paragraphs in 1x1 TABLEs; if one eats the caption the real
        table ends up captionless.

        Measured, Samsung Electronics 2024: looks like 85 tables, actually 37 data tables.
        """
        doc = _doc("<TABLE><TR><TD><P>가. 주요 제품 등의 현황</P></TD></TR></TABLE>" + _REAL_TABLE)
        tables = walk_captioned_tables(doc)
        assert len(tables) == 1, "a 1x1 text wrapper must not be counted as a data table"
        assert tables[0].caption == "주요제품등의현황"

    def test_broken_nesting_still_finds_tables(self):
        """A missing `</TABLE>` nests the whole document inside one table.

        Measured: KT&G 20260318001422. Judging top-level tables by nesting depth finds zero.
        """
        doc = etree.fromstring(
            ("<DOCUMENT><TABLE><TR><TD>"
             "<SECTION-2><TITLE>II. 사업의 내용</TITLE>"
             "<SECTION-2><TITLE>2. 주요 제품 및 서비스</TITLE>"
             "<P>가. 주요 제품 등의 현황</P>" + _REAL_TABLE +
             "</SECTION-2></SECTION-2></TD></TR></TABLE></DOCUMENT>").encode(),
            etree.XMLParser(recover=True, huge_tree=True))
        tables = walk_captioned_tables(doc)
        assert len(tables) == 1 and tables[0].caption == "주요제품등의현황"

    def test_continuation_table_inherits_caption(self):
        """The second table in a caption -> table -> table run (10.6% by census) is not dropped."""
        doc = _doc("<P>가. 주요 제품 등의 현황</P>" + _REAL_TABLE + _REAL_TABLE.replace("DX부문", "DS부문"))
        tables = walk_captioned_tables(doc)
        assert len(tables) == 2
        assert tables[1].caption == "주요제품등의현황" and tables[1].inherited

    def test_section_boundary_stops_at_next_top_level(self):
        """Tables after the next top-level TOC entry (III.) are outside the section."""
        doc = etree.fromstring(
            ("<DOCUMENT><SECTION-2><TITLE>II. 사업의 내용</TITLE>"
             "<P>가. 주요 제품 등의 현황</P>" + _REAL_TABLE + "</SECTION-2>"
             "<SECTION-2><TITLE>III. 재무에 관한 사항</TITLE>"
             "<P>가. 주요 제품 등의 현황</P>" + _REAL_TABLE + "</SECTION-2></DOCUMENT>").encode(),
            etree.XMLParser(recover=True, huge_tree=True))
        assert len(walk_captioned_tables(doc)) == 1


class TestExtractCatalogFromRoot:
    def test_seen_grids_blocks_double_capture(self):
        """A physical table already taken by the production/sales parsers is never re-added
        (guaranteed by the grid hash)."""
        doc = _doc("<P>가. 주요 제품 등의 현황</P>" + _REAL_TABLE)
        sec, met = extract_catalog_from_root(doc, "00126380", 2024)
        assert len(sec) == 1 and met

        already = {grid_key(sec[0]["grid"])}
        sec2, met2 = extract_catalog_from_root(doc, "00126380", 2024, seen_grids=already)
        assert sec2 == [] and met2 == []

    def test_rows_carry_required_columns(self):
        """Respect the biz_metrics schema constraints (metric <= 20 chars, value NOT NULL)."""
        doc = _doc("<P>가. 주요 제품 등의 현황</P>" + _REAL_TABLE)
        _, met = extract_catalog_from_root(doc, "00126380", 2024)
        for m in met:
            assert len(m["metric"]) <= 20
            assert m["value"] is not None
            assert m["corp_code"] == "00126380" and m["fiscal_year"] == 2024


# ─────────────────────────────────────────────────────────────────────────────
# biz_section (production parser) regressions — three pre-existing defects found
# while building the catalog
# ─────────────────────────────────────────────────────────────────────────────
from fin2.extract.biz_section import BizTable, map_biz_table  # noqa: E402


class TestBizSectionRegressions:
    def test_bare_year_header_row_does_not_drop_table(self):
        """A '사업부문|2025년|2024년' header was judged a data row and the table discarded.

        Measured (250-company sample): 33 of 420 production tables (7.9%) lost silently.
        """
        bt = BizTable(metric="output", narrative="(단위 : 대)", grid=[
            ["품목명", "2025년", "2024년"],
            ["품목명", "생산실적", "생산실적"],
            ["조립장비", "87,855,742", "123,198,780"],
        ])
        rows = map_biz_table(bt, 2025)
        assert rows, "a bare-year header row must not discard a production table"
        assert {r.value for r in rows} == {87855742.0, 123198780.0}

    def test_spaced_metric_label_promotes_transposed_layout(self):
        """Letter-spaced '가 동 율' failed to match, so the transposed promotion never happened
        and every row fell back to the table-level metric.

        Measured, 엠플러스: '생산실적' rows were loaded as metric='capacity'.
        """
        bt = BizTable(metric="capacity+output", narrative="", grid=[
            ["품목명", "구 분", "2025년"],
            ["품목명", "구 분", "수량"],
            ["조립장비", "생산능력", "100"],
            ["조립장비", "생 산 실 적", "87"],
            ["조립장비", "가 동 율", "87.0"],
        ])
        got = {(r.item or r.segment, r.metric) for r in map_biz_table(bt, 2025)}
        assert ("조립장비", "capacity") in got
        assert ("조립장비", "output") in got
        assert ("조립장비", "utilization") in got

    def test_transposed_non_metric_rows_are_skipped(self):
        """In a transposed table, non-metric rows ('기말재고') must not fall back into capacity.

        Shaped exactly like the 엠플러스 table — 3 of the 4 divider-column rows are metric
        names, so the transposed promotion fires (60% threshold). Only '기말재고' should then
        be filtered out.
        """
        bt = BizTable(metric="capacity+output", narrative="", grid=[
            ["품목명", "구 분", "2025년"],
            ["품목명", "구 분", "금액"],
            ["조립장비", "생산능력", "100,000,000"],
            ["조립장비", "생산실적", "87,855,742"],
            ["조립장비", "가 동 율", "87.8"],
            ["조립장비", "기말재고", "42,805,946"],
        ])
        rows = map_biz_table(bt, 2025)
        assert 42805946.0 not in [r.value for r in rows], "기말재고 is not a production metric"
        assert {r.metric for r in rows} == {"capacity", "output", "utilization"}


# ─────────────────────────────────────────────────────────────────────────────
# Merged-column tables — a whole column stacked into ONE cell by the filer
# ─────────────────────────────────────────────────────────────────────────────
from fin2.extract.biz_section import is_merged_column_table, merged_cell_reason  # noqa: E402


class TestMergedColumnTable:
    def test_year_run_is_detected(self):
        """일양약품 20260318000595: <TD> 하나에 44개 연도가 구분자 없이 이어붙었다."""
        assert merged_cell_reason("20252024202320222021202020192018")

    def test_comma_merged_values_are_detected(self):
        """콤마가 있어도 여러 값이 붙으면 단일 값일 수 없는 자릿수가 된다."""
        assert merged_cell_reason("175,6141,796,311520,000")
        assert merged_cell_reason("116,457,18719,833,5955,228,434")

    def test_real_large_values_are_not_flagged(self):
        """파생상품 명목금액처럼 진짜 조 단위 값을 버리면 안 된다(다올투자증권 9.88조)."""
        assert merged_cell_reason("9,882,902,676,000") is None
        assert merged_cell_reason("2,002,287,812,800") is None
        assert merged_cell_reason("300,870,900") is None
        assert merged_cell_reason("58.1%") is None

    def test_merged_table_yields_no_values(self):
        """그런 표는 값을 만들지 않는다 — 날조된 수치보다 없는 게 낫다."""
        grid = [
            ["년   도", "구      분", "취득내용"],
            ["20252024202320222021", "상표권특허권상표권", "용비산 등 22건..."],
        ]
        assert is_merged_column_table(grid)
        assert map_catalog_table(_ct(grid, "1. 지적재산권 보유현황"), "ip_right", 2025) == []

    def test_normal_table_still_parses(self):
        """정상 표는 영향 없어야 한다."""
        grid = [["부문", "매출액"], ["DX부문", "1,748,877"]]
        assert is_merged_column_table(grid) is None
        assert map_catalog_table(_ct(grid), "product_status", 2024)


class TestSalesCaptionGap:
    """2026-08-01 실측: sales_section 이 못 잡는 매출 캡션 보강."""

    def test_sales_variants_are_captured(self):
        for cap in ("가. 매출개요", "가. 매출유형별 실적", "가. 매출형태별 실적",
                    "가. 매출유형별 매출액", "(1) 매출 비중", "마. 매출에 관한 사항"):
            assert classify_caption(normalize_caption(cap)) == "sales", cap

    def test_sales_section_owned_captions_still_skipped(self):
        """'매출실적/판매실적/매출현황' 은 sales_section 소관 — 카탈로그가 잡으면 이중 적재."""
        for cap in ("가. 매출실적", "(2) 매출유형별 매출실적", "가. 매출현황"):
            assert classify_caption(normalize_caption(cap)) is None, cap

    def test_receivable_note_reposts_excluded(self):
        """'매출채권' 잔액표는 주석 재게시라 '매출' 규칙에 걸려선 안 된다."""
        for cap in ("(4) 매출채권", "가. 매출채권 및 기타채권",
                    "당기와 전기 중 매출채권의 손실충당금 변동내역은 다음과 같습니다."):
            assert classify_caption(normalize_caption(cap)) is None, cap

    def test_year_suffix_variants(self):
        """'2024연도' 처럼 두음법칙 표기가 흔들려도 기간 헤더로 인식해야 한다.

        실측 나무에이엑스 20250320000319: '연도' 를 못 읽어 헤더행이 데이터로 오판되고
        매출표가 통째로 버려져 그 기업이 0행이었다.
        """
        grid = [
            ["매출유형", "제 품 명", "2024연도", "2024연도"],
            ["매출유형", "제 품 명", "매출액", "비율"],
            ["상품", "서버, 스토리지 장비류", "22,179,568", "49.9%"],
        ]
        rows = map_catalog_table(_ct(grid, "가. 매출유형별 매출액"), "sales", 2024)
        assert rows, "'연도' 표기를 못 읽어 표를 버리면 안 된다"
        got = {(r.segment, r.period_label): r.value for r in rows}
        assert got[("상품", "2024년 매출액")] == 22179568.0
        assert got[("상품", "2024년 비율")] == 49.9
