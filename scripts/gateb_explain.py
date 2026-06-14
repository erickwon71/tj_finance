"""Gate B 단일 필드 불일치 설명 — std 값 vs 해당 canonical 의 모든 보고서 face 라인.
usage: python scripts/gateb_explain.py CORP FY FP BASIS FIELD
  ex:   python scripts/gateb_explain.py 01294110 2025 H1 separate tax_expense"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from fin2.extract.acontext import parse_acontext
from fin2.audit.face_audit import (
    parse_displayed, _cell_text, STD_FIELD_CANONICAL, map_acode, read_report_face_text,
)

corp, fy, fp, basis, field = sys.argv[1:6]
fy = int(fy)
canon = STD_FIELD_CANONICAL[field]

with get_session() as s:
    row = s.execute(text("""
        SELECT * FROM std_financials_v2
        WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period=:p
          AND statement_type=:b AND version=1 AND NOT COALESCE(is_stub,false)
    """), {"c": corp, "y": fy, "p": fp, "b": basis}).fetchone()
    if not row:
        print("std_v2 행 없음"); sys.exit()
    d = dict(row._mapping)
    print(f"{corp} FY{fy} {fp} {basis}  {field}={d[field]}  canonical={canon}")
    print(f"  applied_rules={d.get('applied_rules')}")
    stmt_pref = canon.split('.')[0]
    rcept = d.get(f"{stmt_pref}_rcept")
    print(f"  {stmt_pref}_rcept={rcept}")
    fp_file = s.execute(text("SELECT file_path FROM download_tasks WHERE rcept_no=:r AND file_type='xml' LIMIT 1"),
                        {"r": rcept}).scalar()
    print(f"  file={Path(fp_file).name if fp_file else None}\n")
    root = _parse_xml_file(Path(fp_file)) if fp_file else None
    if root is None:
        print("root 없음"); sys.exit()
    print(f"  -- 보고서 내 canonical={canon} 매핑 셀 (col0·비차원) --")
    for te in root.findall(".//TE[@ACODE]"):
        ac = te.get("ACODE", "")
        if map_acode(ac) != canon:
            continue
        ctx = parse_acontext(te.get("ACONTEXT", ""))
        if ctx.col_index != 0 or ctx.is_dimensional:
            continue
        disp = parse_displayed(_cell_text(te))
        won = disp * (10 ** (-ctx.adecimal_n)) if False else disp  # disp 그대로(ade=0 가정 표시)
        ade = te.get("ADECIMAL", "")
        wonv = disp * (10 ** (-int(ade))) if (ade and int(ade) < 0) else disp
        print(f"    {ac:50s} basis={ctx.basis} cum={ctx.is_cumulative} ade={ade} "
              f"disp={disp} won={wonv}")

    print(f"\n  -- Track B 텍스트 reader 가 본 canonical={canon} 라인 (basis={basis}) --")
    tb = [ln for ln in read_report_face_text(fp_file) if ln.canonical == canon]
    for ln in tb:
        flag = "  <= basis일치" if ln.basis == basis else ""
        print(f"    [{ln.basis:12s}] label='{ln.label}' disp={ln.displayed_value} "
              f"ade={ln.adecimal} won={ln.amount_won}{flag}")
    print(f"  (총 {len(tb)} 라인, std값={d[field]})")
