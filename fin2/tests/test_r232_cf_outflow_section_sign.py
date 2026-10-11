"""R232 — CF "현금유출액" sections printed as magnitudes get their sign in layer 3.

`docs/PARSING_RULES.md` R232, `docs/plans/r232_cf_outflow_section_sign_2026-10-11.md`.
"""
from __future__ import annotations

from fin2.extract.cf_outflow_sign import repair_cf_outflow_section_signs

_FIN = "재무활동현금흐름"
_IN = _FIN + ">재무활동으로 인한 현금유입액"
_OUT = _FIN + ">재무활동으로 인한 현금유출액"


class _Line:
    def __init__(self, row_order, section_path, label_raw, value_won, *, basis="separate",
                 statement="CF", unit_source="declared"):
        self.statement = statement
        self.basis = basis
        self.table_seq = 0
        self.col_index = 0
        self.row_order = row_order
        self.section_path = section_path
        self.label_raw = label_raw
        self.value_won = value_won
        self.header_hint = None
        self.unit_source = unit_source


def _financing(header, total, dividends=413_409_970, repay=2_100_000_000):
    """재무활동 = 유입 1,500,000,000 / 유출 배당 + 상환 (항목은 크기로 인쇄)."""
    return [
        _Line(44, None, _FIN, total),
        _Line(45, _FIN, "재무활동으로 인한 현금유입액", 1_500_000_000),
        _Line(46, _IN, "단기차입금의 차입", 1_500_000_000),
        _Line(48, _FIN, "재무활동으로 인한 현금유출액", header),
        _Line(49, _OUT, "배당금의 지급", dividends),
        _Line(50, _OUT, "단기차입금의 상환", repay),
    ]


def _values(lines):
    return {l.label_raw: l.value_won for l in lines}


def test_header_in_parentheses_proves_magnitude_children():
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970)
    fixes = repair_cf_outflow_section_signs(lines)
    v = _values(lines)
    assert v["배당금의 지급"] == -413_409_970
    assert v["단기차입금의 상환"] == -2_100_000_000
    assert v["재무활동으로 인한 현금유출액"] == -2_513_409_970     # already signed
    assert v["단기차입금의 차입"] == 1_500_000_000                  # inflow untouched
    assert len(fixes) == 2 and "header" in fixes[0].proof


def test_positive_header_is_signed_too():
    lines = _financing(header=2_513_409_970, total=-1_013_409_970)
    repair_cf_outflow_section_signs(lines)
    v = _values(lines)
    assert v["재무활동으로 인한 현금유출액"] == -2_513_409_970
    assert v["배당금의 지급"] == -413_409_970


def test_activity_identity_alone_is_a_proof():
    lines = [l for l in _financing(header=0, total=-1_013_409_970)
             if l.label_raw != "재무활동으로 인한 현금유출액"]
    fixes = repair_cf_outflow_section_signs(lines)
    assert _values(lines)["배당금의 지급"] == -413_409_970
    assert "activity" in fixes[0].proof


def test_signed_table_is_untouched():
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970,
                       dividends=-413_409_970, repay=-2_100_000_000)
    assert repair_cf_outflow_section_signs(lines) == []


def test_negative_child_in_magnitude_section_stays_negative():
    """R232-c (user decision): 일진홀딩스 20150515002674 `배당금의 지급 (2,298,867,380)` — the
    section name says outflow, the parenthesised child is money paid out (the source subtotal
    subtracted it by mistake). Children become -|value|; the printed negative is kept."""
    lines = _financing(header=-(2_100_000_000 - 2_083_384), total=-(600_000_000 - 2_083_384),
                       dividends=-2_083_384)
    fixes = repair_cf_outflow_section_signs(lines)
    v = _values(lines)
    assert v["배당금의 지급"] == -2_083_384
    assert v["단기차입금의 상환"] == -2_100_000_000
    assert [f.label_raw for f in fixes] == ["단기차입금의 상환"]


def test_all_negative_children_with_magnitude_proof_untouched():
    """Inflows printed negative too — a table we do not understand."""
    lines = [
        _Line(1, None, _FIN, 7_382_717_250),
        _Line(2, _FIN, "재무활동으로 인한 현금유입액", -100_000_000),
        _Line(3, _IN, "유상증자", -100_000_000),
        _Line(4, _FIN, "재무활동으로 인한 현금유출액", 7_482_717_250),
        _Line(5, _OUT, "단기차입금의 상환", -7_482_717_250),
    ]
    assert repair_cf_outflow_section_signs(lines) == []


def test_no_proof_untouched():
    """Header negative but the sum does not close (R232-b rejected)."""
    lines = _financing(header=-2_784_714_260, total=-2_784_714_260)
    assert repair_cf_outflow_section_signs(lines) == []


def test_non_cash_adjustment_section_untouched():
    op = "영업활동현금흐름"
    sec = op + ">현금유출이 없는 비용등의 가산"
    for label in ("현금유출이 없는 비용등의 가산", "현금유출이업는비용등의가산"):
        sec = op + ">" + label
        lines = [
            _Line(1, op, label, 5_000),
            _Line(2, sec, "감가상각비", 3_000),
            _Line(3, sec, "퇴직급여", 2_000),
        ]
        assert repair_cf_outflow_section_signs(lines) == [], label


def test_header_without_activity_word_untouched():
    lines = [
        _Line(1, None, "2. 현금유출", 5_000),
        _Line(2, "2. 현금유출", "원재료 구입", 5_000),
    ]
    assert repair_cf_outflow_section_signs(lines) == []


def test_xbrl_rows_untouched():
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970)
    for l in lines:
        l.unit_source = "xbrl"
    assert repair_cf_outflow_section_signs(lines) == []


def test_frozen_cell_with_same_value_is_kept_and_rest_flipped():
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970)
    div = lines[4]
    fixes = repair_cf_outflow_section_signs(lines, frozen={id(div): -413_409_970})
    assert div.value_won == 413_409_970                 # left to the other rule's row
    assert [f.label_raw for f in fixes] == ["단기차입금의 상환"]


def test_frozen_cell_with_other_sign_skips_section():
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970)
    assert repair_cf_outflow_section_signs(lines, frozen={id(lines[4]): 413_409_970}) == []
    assert lines[5].value_won == 2_100_000_000


def test_frozen_cell_same_sign_other_magnitude_flips_rest():
    """R18 takes the tag amount within 1% (20260318001025 632,379M -> -632,384M) and runs after
    R232 in the extractor — the rest of the section is still signed."""
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970)
    fixes = repair_cf_outflow_section_signs(lines, frozen={id(lines[4]): -413_500_000})
    assert [f.label_raw for f in fixes] == ["단기차입금의 상환"]


def test_columns_are_separate_sections():
    lines = _financing(header=-2_513_409_970, total=-1_013_409_970)
    other = _financing(header=-2_784_714_260, total=-2_784_714_260)
    for l in other:
        l.col_index = 1
    repair_cf_outflow_section_signs(lines + other)
    assert lines[4].value_won == -413_409_970
    assert other[4].value_won == 413_409_970
