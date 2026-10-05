"""R225 — '주식의 총수' 표의 Ⅴ 자기주식수·Ⅵ 유통주식수(보통주) 전사 (fin2/extract/shares.py)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fin2.extract.shares import extract_share_counts

_HEAD = "<P>4. 주식의 총수 등</P><TABLE><TR><TD>(단위 : 주)</TD></TR></TABLE><TABLE>"
_TAIL = "</TABLE>"


def _doc(tmp_path, rows: str) -> str:
    p = tmp_path / "x.xml"
    p.write_text(_HEAD + rows + _TAIL, encoding="utf-8")
    return str(p)


def _row(label, common, pref="-", total="-", note="-"):
    return f"<TR><TD COLSPAN='2'>{label}</TD><TD>{common}</TD><TD>{pref}</TD><TD>{total}</TD><TD>{note}</TD></TR>"


def test_samsung_2024_shape(tmp_path):
    # 삼성전자 20250311001085: Ⅳ 5,969,782,550 · Ⅴ 29,700,000 · Ⅵ 5,940,082,550
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수 (Ⅱ-Ⅲ)", "5,969,782,550", "822,886,700")
             + _row("Ⅴ. 자기주식수", "29,700,000", "4,050,000")
             + _row("Ⅵ. 유통주식수 (Ⅳ-Ⅴ)", "5,940,082,550", "818,836,700")
             + _row("Ⅶ. 자기주식 보유비율", "0.5", "0.5"))
    assert extract_share_counts(p) == {"issued": 5969782550, "issued_label": "발행주식의 총수",
                                       "treasury": 29700000, "float": 5940082550}


def test_common_treasury_dash_does_not_pick_preferred(tmp_path):
    # '-' in the 보통주 cell means 0 — must not fall through to the 우선주/합계 numbers.
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수", "1,000,000", "50,000", "1,050,000")
             + _row("Ⅴ. 자기주식수", "-", "5,000", "5,000"))
    r = extract_share_counts(p)
    assert r["treasury"] == 0 and r["float"] == 1000000


def test_float_row_missing_derived_from_issued_minus_treasury(tmp_path):
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수", "1,000,000")
             + _row("Ⅴ. 자기주식수", "100,000"))
    assert extract_share_counts(p)["float"] == 900000


def test_no_treasury_row_no_float_guess(tmp_path):
    p = _doc(tmp_path, _row("Ⅳ. 발행주식의 총수", "1,000,000"))
    r = extract_share_counts(p)
    assert r["issued"] == 1000000 and r["treasury"] is None and r["float"] is None
