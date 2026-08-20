"""P3-1 '원인 A' 그룹A(감사기 커버리지 공백) 가설 검증 — Track B(텍스트) 리더가
`_supplement_with_text()`의 조기 스킵(statement-level 커버 판정)만 없다면 실제로
is.controlling_ni 를 잡아내는지 원문 파일로 직접 확인한다.

용법: .venv/bin/python scripts/investigate_p3_cause_a_trackb_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fin2.audit.face_audit import (
    read_report_face_xbrl, read_report_face_text, _parse_xml_file,
)

SAMPLES = [
    ("00105271", "케이씨씨",
     "/Users/taejin/Project/tj_finance/raw_report/KOSPI/00105271_케이씨씨/annual/2015/20160330003845.xml",
     183556917097),
    ("00105855", "엘에스일렉트릭",
     "/Users/taejin/Project/tj_finance/raw_report/KOSPI/00105855_엘에스일렉트릭/annual/2015/20160330004015.xml",
     70294636093),
]

for corp, name, fp, expected in SAMPLES:
    print(f"\n=== {corp} {name} (기대값 {expected:,}) ===")
    root = _parse_xml_file(Path(fp))
    a_lines = read_report_face_xbrl(fp, root=root)
    a_covered = {ln.canonical for ln in a_lines if ln.canonical and ln.canonical.startswith("is.")}
    print(f"Track A: {len(a_lines)}줄, IS canonical 커버: {sorted(a_covered)}")
    print(f"  is.controlling_ni in Track A? {'is.controlling_ni' in a_covered}")

    b_lines = read_report_face_text(fp, root=root)
    ctrl_b = [ln for ln in b_lines if ln.canonical == "is.controlling_ni"]
    print(f"Track B: {len(b_lines)}줄, is.controlling_ni 후보 {len(ctrl_b)}건")
    for ln in ctrl_b[:5]:
        print(f"   label={ln.label!r} displayed={ln.displayed_value} adecimal={ln.adecimal} "
              f"amount_won={ln.amount_won} basis={ln.basis}")
        if ln.amount_won == expected:
            print("   ✅ 기대값과 일치")
