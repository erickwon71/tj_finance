"""R335 / R336 — share table unit and cell reading (fin2/extract/shares.py).

R335: caption "(단위 : 천주)" with no prose in the section -> "N주" statements anywhere in the
      document decide between x1 and x1000 (세종텔레콤 20261116001658, 티에스아이 20261109000059).
R336: "(단위 : 백만주)" (해성디에스 2021~2023), counts printed with spaces inside
      ('106,461, 552' 두산에너빌리티 20171114001621), and an unreadable common cell does not
      fall through to the preferred / total column.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.shares import extract_share_counts  # noqa: E402


def _row(label, common, pref="-", total="-", note="-"):
    return f"<TR><TD>{label}</TD><TD>{common}</TD><TD>{pref}</TD><TD>{total}</TD><TD>{note}</TD></TR>"


def _doc(tmp_path, rows: str, unit: str = "주", before: str = "", after: str = "") -> str:
    p = tmp_path / "x.xml"
    p.write_text(
        f"<XML>{before}<P>4. 주식의 총수 등</P><P>가. 주식의 총수 현황</P>"
        f"<TABLE><TR><TD>(기준일 : 2026.09.30 )</TD><TD>(단위 : {unit}, %)</TD></TR></TABLE>"
        f"<TABLE>{_row('구 분', '보통주', '우선주', '합계', '비고')}{rows}</TABLE>{after}</XML>",
        encoding="utf-8")
    return str(p)


_SEJONG = (_row("Ⅰ. 발행할 주식의 총수", "200,000,000", "-", "200,000,000")
           + _row("Ⅱ. 현재까지 발행한 주식의 총수", "745,282,103", "-", "745,282,103")
           + _row("Ⅲ. 현재까지 감소한 주식의 총수", "731,282,103", "-", "731,282,103")
           + _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "14,000,000", "-", "14,000,000")
           + _row("Ⅴ. 자기주식수", "-", "-", "-")
           + _row("Ⅵ. 유통주식수 (Ⅳ-Ⅴ)", "14,000,000", "-", "14,000,000"))


# ---------------------------------------------------------------- R335

def test_r335_document_statement_overrides_wrong_thousand_caption(tmp_path):
    # 세종텔레콤 20261116001658: caption 천주, the 자본금 note states the printed count in 주.
    p = _doc(tmp_path, _SEJONG, unit="천주",
             before="<P>분기보고서 제출일 현재 유통주식수는 14,000,000주 입니다.</P>")
    r = extract_share_counts(p)
    assert r["issued"] == 14_000_000 and r["float"] == 14_000_000


def test_r335_document_statement_confirms_thousand_caption(tmp_path):
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "109,142"), unit="천주",
             after="<P>발행주식수 109,142,000주</P>")
    assert extract_share_counts(p)["issued"] == 109_142_000


def test_r335_impossible_caption_is_ignored(tmp_path):
    # 버킷스튜디오 20230814002659: caption 천주, Ⅰ 1,000,000,000 -> 10^12 authorized is impossible.
    p = _doc(tmp_path, _row("Ⅰ. 발행할 주식의 총수", "1,000,000,000", "-", "1,000,000,000")
             + _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "84,109,926", "16,538,231", "100,648,157")
             + _row("Ⅴ. 자기주식수", "1,258") + _row("Ⅵ. 유통주식수 (Ⅳ-Ⅴ)", "84,108,668"), unit="천주")
    r = extract_share_counts(p)
    assert (r["issued"], r["treasury"], r["float"]) == (84_109_926, 1_258, 84_108_668)


def test_r335_impossible_issued_count_rejects_caption(tmp_path):
    # 티로보틱스 20210318000672: caption 천주, Ⅳ 11,853,448 -> 11.9 billion issued is impossible.
    p = _doc(tmp_path, _row("Ⅰ. 발행할 주식의 총수", "37,500,000", "12,500,000", "50,000,000")
             + _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "11,853,448") + _row("Ⅵ. 유통주식수 (Ⅳ-Ⅴ)", "11,853,448"),
             unit="천주")
    r = extract_share_counts(p)
    assert r["issued"] == 11_853_448 and r["float"] == 11_853_448


def test_r335_no_document_evidence_keeps_caption(tmp_path):
    # 현대로템-type table, nothing stated elsewhere: the caption (천주) still decides.
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "109,142"), unit="천주")
    assert extract_share_counts(p)["issued"] == 109_142_000


def test_r335_conflicting_evidence_keeps_caption(tmp_path):
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "209,142"), unit="천주",
             after="<P>209,142주 ... 209,142,000주</P>")
    assert extract_share_counts(p)["issued"] == 209_142_000


def test_r335_small_counts_are_no_evidence(tmp_path):
    # Treasury 383 (thousand) must not be "proved" x1 by an unrelated "383주".
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "6,500") + _row("Ⅴ. 자기주식수", "383"),
             unit="천주", after="<P>단주 383주 처리</P>")
    r = extract_share_counts(p)
    assert r["issued"] == 6_500_000 and r["treasury"] == 383_000


def test_r335_stock_word_is_not_a_share_statement(tmp_path):
    # "4,000,000주식" / "4,000,000주주" are not "N주" statements.
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "4,000,000"), unit="천주",
             before="<P>4,000,000주식 4,000,000주주</P>")
    assert extract_share_counts(p)["issued"] == 4_000_000_000


# ---------------------------------------------------------------- R336

def test_r336_million_share_unit(tmp_path):
    # 해성디에스 20210817000180: "(단위 : 백만주)" Ⅳ 17.
    p = _doc(tmp_path, _row("Ⅰ. 발행할 주식의 총수", "50") + _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "17")
             + _row("Ⅴ. 자기주식수", "-") + _row("Ⅵ. 유통주식수 (Ⅳ-Ⅴ)", "17"), unit="백만주")
    r = extract_share_counts(p)
    assert r == {"issued": 17_000_000, "issued_label": "발행주식의 총수",
                 "treasury": 0, "float": 17_000_000}


def test_r336_spaced_count_is_read(tmp_path):
    # 두산에너빌리티 20171114001621: common '106,461, 552', preferred 12,904,210.
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "106,461, 552", "12,904,210", "119,365, 762")
             + _row("Ⅴ. 자기주식수", "-") + _row("Ⅵ. 유통주식수 (Ⅳ-Ⅴ)", "106,461, 552", "12,904,210"))
    r = extract_share_counts(p)
    assert r["issued"] == 106_461_552 and r["float"] == 106_461_552


def test_r336_spaces_anywhere_in_groups(tmp_path):
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "3 8,515, 764", "-", "38,515,764"))
    assert extract_share_counts(p)["issued"] == 38_515_764
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "21,939,5 62", "-", "21,939,562"))
    assert extract_share_counts(p)["issued"] == 21_939_562


def test_r336_unreadable_common_cell_does_not_take_preferred(tmp_path):
    # Broken groups after removing spaces: unreadable -> Ⅱ fallback, never the preferred count.
    p = _doc(tmp_path, _row("Ⅱ. 현재까지 발행한 주식의 총수", "1,000,000", "50,000")
             + _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "9 99,99", "50,000", "1,049,999"))
    r = extract_share_counts(p)
    assert r["issued"] == 1_000_000 and r["issued_label"] == "현재까지 발행한 주식의 총수"


def test_r336_dash_common_cell_still_falls_through(tmp_path):
    # 경창산업 layout: header '- | 보통주 | 합계' — the '-' column is skipped as before.
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "-", "35,819,005", "35,819,005"))
    assert extract_share_counts(p)["issued"] == 35_819_005
