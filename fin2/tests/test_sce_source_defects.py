"""R183 — SCE source defects (per-rcept exception lists re-proved by identities).

Real cases: 동진쎄미켐 `20170515004289` (value typos), 에코프로 `20180402002079` /
`20181206000084` (row in the wrong year block, duplicated row), 현대위아 `20240320001675`
(movement printed only in the total column). `docs/PARSING_RULES.md` R183.
"""
from __future__ import annotations

import inspect

from fin2.extract import report_lines, report_lines_xbrl
from fin2.extract.sce_source_defects import (
    apply_source_defect_fixes, fill_total_only_rows, verify_row_drops,
)


class _Line:
    """Minimal ReportLineRow stand-in."""

    def __init__(self, basis, row_order, label_raw, col_index, value_won, col_label=None):
        self.statement = "SCE"
        self.basis = basis
        self.row_order = row_order
        self.label_raw = label_raw
        self.col_index = col_index
        self.value_won = value_won
        self.col_label = col_label
        self.table_seq = 0


def _rows(basis, spec, col_labels=None):
    out = []
    for ro, label, cells in spec:
        for ci, v in cells.items():
            out.append(_Line(basis, ro, label, ci, v, (col_labels or {}).get(ci)))
    return out


def _get(lines, basis, ro, ci):
    hit = [ln for ln in lines if ln.basis == basis and ln.row_order == ro and ln.col_index == ci]
    return hit[0].value_won if hit else None


# ── 동진쎄미켐 2017Q1 separate SCE (XBRL col_label hierarchy) ─────────────────
_DJ_SEP_COLS = {0: "자본 [member]", 1: "자본 [member]>자본금 [member]",
                2: "자본 [member]>기타불입자본", 3: "자본 [member]>기타자본잉여금 [member]",
                4: "자본 [member]>이익잉여금"}


def _dongjin_separate(new_issue_amount=11_220_094_337):
    return _rows("separate", [
        (1, "기초자본 (2017-01-01)", {0: 185_699_971_060, 1: 23_716_131_500, 2: 61_191_597_597,
                                    3: 20_743_089_545, 4: 80_049_152_418}),
        (3, "연차배당", {0: -2_845_935_780, 4: -2_845_935_780}),
        (5, "당기순이익(손실)", {0: 8_347_125_317, 4: 8_347_125_317}),
        (6, "순확정급여부채 재측정요소", {0: -1_285_950_900, 3: -1_285_950_900}),
        (9, "유상증자", {0: new_issue_amount, 1: 1_348_435_500,
                      2: new_issue_amount - 1_348_435_500}),
        (10, "신주인수권대가", {0: -1_233_655_389, 2: -1_233_655_389}),
        (11, "기말자본 (기말) (2017-03-31)", {0: 199_901_648_645, 1: 25_064_567_000,
                                           2: 131_021_198_642, 3: 40_200_228_190,
                                           4: 85_550_341_955}),
    ], _DJ_SEP_COLS)


def test_value_fix_two_wrong_cells_in_one_row_fixed_together():
    lines = _dongjin_separate()
    apply_source_defect_fixes(lines, "20170515004289")
    assert _get(lines, "separate", 11, 2) == 69_829_601_045
    assert _get(lines, "separate", 11, 3) == 19_457_138_645


def test_value_fix_skipped_when_roll_forward_does_not_prove_it():
    # A different movement amount → the listed new value no longer closes the column.
    lines = _dongjin_separate(new_issue_amount=11_220_094_000)
    apply_source_defect_fixes(lines, "20170515004289")
    assert _get(lines, "separate", 11, 2) == 131_021_198_642


def test_value_fix_other_rcept_untouched():
    lines = _dongjin_separate()
    apply_source_defect_fixes(lines, "20170515000000")
    assert _get(lines, "separate", 11, 2) == 131_021_198_642


def test_value_fix_consolidated_nci():
    cols = {0: "자본 [member]", 1: "자본 [member]>지배기업 소유주지분",
            2: "자본 [member]>지배기업 소유주지분>자본금 [member]",
            6: "자본 [member]>비지배지분 [member]"}
    lines = _rows("consolidated", [
        (1, "기초자본 (2017-01-01)", {0: 196_926_637_460, 1: 190_218_468_317, 6: 6_708_169_143}),
        (4, "당(반)기순이익(손실)", {0: 10_260_399_937, 1: 10_169_814_341, 6: 90_585_596}),
        (7, "해외사업장환산 외환차이", {0: -6_239_329_796, 1: -6_209_464_350, 6: -29_865_446}),
        (10, "기말자본 (기말) (2017-03-31)", {0: 206_802_259_869, 1: 200_033_370_576,
                                           6: 6_768_899_293}),
    ], cols)
    apply_source_defect_fixes(lines, "20170515004289")
    assert _get(lines, "consolidated", 10, 6) == 6_768_889_293


# ── 에코프로 2017FY consolidated SCE, capital/surplus/parent-total/total ───────
_ECO_CON_COLS = {0: "자본>지배기업의 소유주에게 귀속되는 자본>자본금",
                 1: "자본>지배기업의 소유주에게 귀속되는 자본>자본잉여금",
                 3: "자본>지배기업의 소유주에게 귀속되는 자본>지배기업의 소유주에게 귀속되는 자본 합계",
                 5: "자본>자본 합계"}


def _ecopro_consolidated(target_taken=False):
    spec = [
        (0, "2015.01.01 (기초자본)", {0: 7_011_255_500, 1: 63_769_139_061}),
        (4, "신주인수권행사", {0: 696_804_000, 1: 10_581_704_580}),
        (8, "전환권대가", {1: 1_953_434_497}),
        (10, "전환사채발행및행사", {0: 239_779_000, 1: 3_603_841_388}),
        (18, "2015.12.31 (기말자본)", {0: 8_482_026_000, 1: 87_805_368_770}),
        (19, "2016.01.01 (기초자본)", {0: 8_482_026_000, 1: 87_805_368_770}),
        (23, "신주인수권행사", {0: 598_778_000, 1: 7_889_214_531}),
        (24, "전환상환우선주행사", {0: 534_187_500, 1: 7_897_249_244,
                             3: 8_431_436_744, 5: 8_431_436_744}),
        (25, "신주인수권대가", {1: 1_970_522_619}),
        (26, "교환권대가", {1: 1_612_107_037}),
        (28, "전환권행사및상환", {0: 551_019_500, 1: 7_908_863_288}),
        (32, "유상증자", {0: 1_050_000_000, 1: 13_976_329_400}),
        (33, "종속기업유상증자", {1: 9_947_093_582}),
        (34, "주주간자본거래", {1: 6_321_311_457}),
        (37, "2016.12.31 (기말자본)", {0: 10_681_823_500, 1: 137_430_810_684}),
    ]
    if target_taken:
        spec.append((5, "다른행", {1: 0}))
    return _rows("consolidated", spec, _ECO_CON_COLS)


def test_row_move_to_the_block_where_both_close():
    lines = _ecopro_consolidated()
    apply_source_defect_fixes(lines, "20180402002079")
    moved = [ln for ln in lines if ln.label_raw == "전환상환우선주행사"]
    assert {ln.row_order for ln in moved} == {5}
    assert len(moved) == 4               # total columns move with the row


def test_row_move_skipped_when_target_slot_taken():
    lines = _ecopro_consolidated(target_taken=True)
    apply_source_defect_fixes(lines, "20181206000084")
    assert {ln.row_order for ln in lines if ln.label_raw == "전환상환우선주행사"} == {24}


def test_row_move_skipped_when_blocks_do_not_close():
    lines = _ecopro_consolidated()
    for ln in lines:
        if ln.row_order == 18 and ln.col_index == 0:
            ln.value_won = 8_482_026_001  # 2015 capital no longer closes after the move
    apply_source_defect_fixes(lines, "20180402002079")
    assert {ln.row_order for ln in lines if ln.label_raw == "전환상환우선주행사"} == {24}


# ── 에코프로 2017FY separate SCE retained-earnings column ─────────────────────
def _ecopro_separate(remeasurement):
    return _rows("separate", [
        (0, "2015.01.01 (기초자본)", {2: 5_831_180_301, 3: 76_611_574_862}),
        (1, "당기순이익(손실)", {2: 189_521_071, 3: 189_521_071}),
        (2, "확정급여제도의재측정요소", {2: remeasurement, 3: remeasurement}),
        (3, "지분법이익잉여금변동", {2: 104_092_712, 3: 104_092_712}),
        (10, "2015.12.31 (기말자본)", {2: 5_544_982_303, 3: 101_832_377_073}),
    ], {2: "자본>이익잉여금", 3: "자본>자본 합계"})


def test_row_drop_kept_when_block_closes_after_the_chain():
    lines = _ecopro_separate(remeasurement=-475_719_069)
    dropped = apply_source_defect_fixes(lines, "20180402002079")
    assert not any(ln.label_raw == "지분법이익잉여금변동" for ln in lines)
    assert verify_row_drops(lines, dropped) == 1
    assert not any(ln.label_raw == "지분법이익잉여금변동" for ln in lines)


def test_row_drop_restored_when_block_still_open():
    # The sign-repair chain did not fix the remeasurement sign → block stays open.
    lines = _ecopro_separate(remeasurement=475_719_069)
    dropped = apply_source_defect_fixes(lines, "20180402002079")
    assert verify_row_drops(lines, dropped) == 0
    assert sum(ln.label_raw == "지분법이익잉여금변동" for ln in lines) == 2


def test_row_drop_needs_exact_expected_values():
    lines = _ecopro_separate(remeasurement=-475_719_069)
    for ln in lines:
        if ln.row_order == 3 and ln.col_index == 3:
            ln.value_won = 104_092_713
    assert apply_source_defect_fixes(lines, "20180402002079") == []


# ── 현대위아 2023FY separate SCE 2021 block (백만원 → 원) ──────────────────────
_HW_COLS = {0: "자본>자본금", 1: "자본>기타불입자본", 2: "자본>기타자본구성요소",
            3: "자본>이익잉여금", 4: "자본>자본 합계"}
_M = 1_000_000


def _hyundai_wia(closing_re=2_544_918):
    lines = _rows("separate", [
        (0, "2021.01.01 (기초자본)", {0: 135_975 * _M, 1: 425_996 * _M, 2: 25_336 * _M,
                                  3: 2_440_374 * _M, 4: 3_027_681 * _M}),
        (1, "기타포괄손익-공정가치측정금융자산평가손익", {0: 0, 1: 0, 2: 35 * _M, 3: 0, 4: 35 * _M}),
        (3, "확정급여제도의 재측정요소", {0: 0, 1: 0, 2: 0, 3: 14_193 * _M, 4: 14_193 * _M}),
        (4, "당기순이익(손실)", {0: 0, 1: 0, 2: 0, 3: 108_944 * _M, 4: 108_944 * _M}),
        (7, "배당금의 지급", {4: -18_593 * _M}),
        (8, "2021.12.31 (기말자본)", {0: 135_975 * _M, 1: 425_996 * _M, 2: 25_371 * _M,
                                  3: closing_re * _M, 4: 3_132_260 * _M}),
    ], _HW_COLS)
    for ln in lines:
        ln.context_raw = f"sce:separate:c{ln.col_index}"
    return lines


def test_cell_fill_adds_the_blank_component_cell():
    lines = _hyundai_wia()
    apply_source_defect_fixes(lines, "20240320001675")
    assert _get(lines, "separate", 7, 3) == -18_593 * _M
    added = [ln for ln in lines if ln.row_order == 7 and ln.col_index == 3][0]
    assert added.col_label == "자본>이익잉여금" and added.context_raw == "sce:separate:c3"
    assert _get(lines, "separate", 7, 4) == -18_593 * _M


def test_cell_fill_skipped_when_roll_forward_does_not_prove_it():
    lines = _hyundai_wia(closing_re=2_563_511)   # column already closes without the cell
    apply_source_defect_fixes(lines, "20240320001675")
    assert _get(lines, "separate", 7, 3) is None


def test_cell_fill_skipped_when_cell_already_present():
    lines = _hyundai_wia()
    lines.append(_Line("separate", 7, "배당금의 지급", 3, -18_593 * _M, "자본>이익잉여금"))
    n = len(lines)
    apply_source_defect_fixes(lines, "20240320001675")
    assert len(lines) == n


def test_cell_fill_other_rcept_filled_by_general_rule_r184():
    lines = _hyundai_wia()
    apply_source_defect_fixes(lines, "20240320001676")
    assert _get(lines, "separate", 7, 3) == -18_593 * _M


# ── R184: general total-only row fill ────────────────────────────────────────
def test_r184_fills_the_single_short_component_column():
    lines = _hyundai_wia()
    assert fill_total_only_rows(lines) == 1
    assert _get(lines, "separate", 7, 3) == -18_593 * _M


def test_r184_never_overwrites_a_printed_zero():
    lines = _hyundai_wia()
    lines.append(_Line("separate", 7, "배당금의 지급", 3, 0, "자본>이익잉여금"))
    assert fill_total_only_rows(lines) == 0


def test_r184_skips_when_two_columns_are_short_by_the_same_amount():
    lines = _hyundai_wia()
    for ln in lines:
        if ln.row_order == 8 and ln.col_index == 2:
            ln.value_won -= 18_593 * _M      # 기타자본구성요소 now also short by it
    assert fill_total_only_rows(lines) == 0


def test_r184_skips_when_total_column_does_not_close():
    lines = _hyundai_wia()
    for ln in lines:
        if ln.row_order == 8 and ln.col_index == 4:
            ln.value_won += 1
    assert fill_total_only_rows(lines) == 0


def test_r184_skips_tables_with_two_total_columns():
    lines = _hyundai_wia()
    for ln in lines:
        if ln.col_index == 2:
            ln.col_label = "자본>지배기업 소유지분 합계"
    assert fill_total_only_rows(lines) == 0


# ── wiring ────────────────────────────────────────────────────────────────────
def test_wired_before_sign_repair_and_verified_after_chain_in_xml_path():
    src = inspect.getsource(report_lines.extract_report_lines)
    assert src.index("apply_source_defect_fixes(") < src.index("repair_sce_sign_loss(")
    assert src.index("repair_cf_cash_sign_loss(") < src.index("verify_row_drops(")


def test_wired_in_xbrl_path():
    src = inspect.getsource(report_lines_xbrl.extract_report_lines_xbrl)
    assert "apply_source_defect_fixes(" in src and "verify_row_drops(" in src
