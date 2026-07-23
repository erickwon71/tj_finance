"""(b) Insurer revenue-composition realizability survey (READ-ONLY).

Confirms whether "revenue = 보험(서비스)수익 + 투자(서비스)수익" is buildable across the
whole insurer universe under IFRS17 (2023+), before writing the composition rule.

Label families (verified 2026-07-24):
  생보(life)   : 보험서비스수익  / 투자서비스수익  / 보험서비스결과 / 투자손익
  손보(non-life): 보험영업수익    / 투자영업수익    / 보험손익       / 투자손익
Both file 영업이익 directly (= 보험손익/서비스결과 + 투자손익); v3 already reads it.

For each insurer-year (FY, consolidated, 2023+) it detects the two revenue subtotals by
EXACT normalized label (numbering/space-stripped, so children like 일반보험서비스수익 are
excluded) and reports coverage: both / 보험-only / 투자-only / neither. Writes nothing.
"""
from __future__ import annotations
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from collector.db import get_session

INS_REV = {"보험영업수익", "보험서비스수익"}
INV_REV = {"투자영업수익", "투자서비스수익"}
_NUM_PREFIX = re.compile(r"^[\sⅠ-Ⅹⅰ-ⅹIVXivx0-9\.\(\)]+")


def norm(label: str) -> str:
    if not label:
        return ""
    s = _NUM_PREFIX.sub("", label)
    return re.sub(r"\s+", "", s).split("(")[0]  # drop trailing 주석 refs


def detect(session, corp, fy, basis="consolidated"):
    """Return (ins_rev, inv_rev, op_income) from the canonical IS filing."""
    rows = session.execute(text("""
        SELECT label_raw, value_won, node_role, section_path
        FROM report_lines
        WHERE corp_code=:c AND report_fiscal_year=:y AND report_fiscal_period='FY'
          AND basis=:b AND statement='IS' AND col_index=0 AND value_won IS NOT NULL
    """), {"c": corp, "y": fy, "b": basis}).fetchall()
    ins = inv = opinc = None
    for label, val, role, path in rows:
        n = norm(label)
        if n in INS_REV and ins is None:
            ins = val
        elif n in INV_REV and inv is None:
            inv = val
        elif n == "영업이익" and opinc is None:
            opinc = val
    return ins, inv, opinc


def main():
    with get_session() as s:
        # insurer universe = corps that ever file a 보험(서비스/영업)수익 line
        corps = s.execute(text("""
            SELECT DISTINCT rl.corp_code, c.corp_name, c.induty_code
            FROM report_lines rl JOIN corporations c ON c.corp_code=rl.corp_code
            WHERE rl.statement='IS' AND rl.report_fiscal_period='FY'
              AND (rl.label_raw LIKE '%보험영업수익%' OR rl.label_raw LIKE '%보험서비스수익%')
            ORDER BY c.corp_name
        """)).fetchall()
        print(f"insurer universe (files 보험영업/서비스수익) = {len(corps)} corps\n")

        cover = Counter()
        opinc_ok = opinc_miss = 0
        rows_out = []
        for corp, name, induty in corps:
            years = [r[0] for r in s.execute(text("""
                SELECT DISTINCT report_fiscal_year FROM report_lines
                WHERE corp_code=:c AND report_fiscal_period='FY' AND statement='IS'
                  AND report_fiscal_year >= 2023 ORDER BY 1
            """), {"c": corp}).fetchall()]
            for fy in years:
                ins, inv, opinc = detect(s, corp, fy)
                v3 = s.execute(text("""SELECT revenue, operating_income FROM std_financials_v3
                    WHERE corp_code=:c AND fiscal_year=:y AND fiscal_period='FY'
                      AND statement_type='consolidated'"""), {"c": corp, "y": fy}).fetchone()
                if ins and inv:
                    cover["both (합산 가능)"] += 1
                elif ins:
                    cover["보험만"] += 1
                elif inv:
                    cover["투자만"] += 1
                else:
                    cover["neither"] += 1
                # op_income realizability: v3 has it AND == filed 영업이익
                if v3 and v3[1] is not None and (opinc is None or v3[1] == opinc):
                    opinc_ok += 1
                elif opinc is not None:
                    opinc_miss += 1
                if ins and inv and len(rows_out) < 18:
                    summ = ins + inv
                    v3r = v3[0] if v3 else None
                    rows_out.append((name, fy, ins, inv, summ, v3r))

        print("=== IFRS17(2023+) insurer-year revenue 합산 실현성 ===")
        tot = sum(cover.values())
        for k, v in cover.most_common():
            print(f"  {k:<16}{v:>5}  ({100*v/tot:.0f}%)")
        print(f"  합계 {tot} insurer-years")
        print(f"\n  operating_income: v3 이미 정답 {opinc_ok} · 원문 영업이익 있으나 v3 불일치/결측 {opinc_miss}")

        print("\n=== 합산 예시 (보험rev + 투자rev = revenue) — 백만/조 ===")
        for name, fy, ins, inv, summ, v3r in rows_out:
            v3s = f"{v3r/1e12:.1f}조" if v3r else "—"
            print(f"  {name:12}{fy}  보험={ins/1e12:>5.1f}조 투자={inv/1e12:>5.1f}조 "
                  f"합산={summ/1e12:>5.1f}조  (현 v3={v3s})")


if __name__ == "__main__":
    main()
