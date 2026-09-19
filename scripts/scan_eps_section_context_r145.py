"""R145 §8-4 measurement: do EPS-like rows occur WITHOUT an EPS section header?

For a random sample of 2015+ filings, re-parse the IS tables and classify every
row whose label contains '주당' by the evidence available to the structural rule:

  A/B  : label matches the structural EPS label pattern (design §3)
  C    : the nearest preceding amount-less header row in the same table
         contains '주당' (= inside an EPS section)
  UNIT : the table declares 원 on some '주당' row (R144 eps_unit_declared)

The question: how many A/B rows have neither C nor UNIT, i.e. real EPS lines
that no section header vouches for.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract import report_lines as RL  # noqa: E402
from parser.common.amount_normalizer import strip_cell_whitespace  # noqa: E402
from parser.xml.table_extractor import extract_rows  # noqa: E402

# --- structural EPS label rule (design doc §3) -------------------------------
_RE_A = re.compile(r"(기본|희석).{0,8}주당")
_RE_B = re.compile(r"주당(계속영업|중단영업|분기|반기|당기|연결|별도)?"
                   r"(순이익|순손익|순손실|이익|손익|손실)")


def _is_structural_eps(label: str) -> bool:
    s = strip_cell_whitespace(label)
    return bool(_RE_A.search(s) or _RE_B.search(s))


def scan_one(job):
    rcept_no, file_path, fy, fp, corp_code = job
    out = []
    try:
        root = RL._parse_xml_file(Path(file_path))
        if root is None:
            return out
        fin_type = RL._detect_fin_type(root, file_path=file_path)
        groups = RL._detect_body_statement_tables(root, fin_type, include_sce=True)
    except Exception as e:  # noqa: BLE001
        return [{"err": f"{type(e).__name__}: {e}", "rcept_no": rcept_no}]

    for code, tables_with_unit in groups.items():
        if not code.startswith("IS"):
            continue
        for table, unit, _hint in tables_with_unit:
            # ★design §5-2(가): keep_header_rows=True so rows carrying an inline
            #   unit declaration ('XV. 주당이익(단위:원)') survive into the section
            #   tree instead of being dropped by the '단위표기' header rule.
            rows = list(extract_rows(table, multiplier=unit or 1, num_cols=3,
                                     direct_only=True, skip_junk=False,
                                     keep_header_rows=True))
            paths = RL._assign_section_paths(rows, "IS")
            # does this table have ANY EPS section header at all? (user's question)
            has_eps_header = any(
                r.account_name and "주당" in r.account_name
                and all(a is None for a in r.amounts[:3])
                for r in rows)
            # table-level 원 declaration evidence (mirrors _emit_eps_lines)
            unit_declared = any(
                r.account_name and "주당" in r.account_name
                and RL.detect_unit_declaration(r.account_name) == 1
                for r in rows)
            prev_hdr_eps = False
            for r in rows:
                label = (r.account_name or "").strip()
                if not label:
                    continue
                has_amt = any(a is not None for a in r.amounts[:3])
                if not has_amt:
                    prev_hdr_eps = "주당" in label
                    continue
                if "주당" not in label:
                    continue
                p = paths.get(id(r)) or ""
                out.append({
                    "rcept_no": rcept_no, "corp": corp_code, "fy": fy, "fp": fp,
                    "code": code, "label": label, "path": p,
                    "ab": _is_structural_eps(label),
                    "c_prev": prev_hdr_eps,                      # old §3-3 heuristic
                    "c_tail": "주당" in p.split(">")[-1],        # design §5-2(나)
                    "c_any": "주당" in p,                        # chain-wide variant
                    "tbl_hdr": has_eps_header,                   # ← user's question
                    "unit": unit_declared,
                })
    return out


def main():
    ap = argparse.ArgumentParser()
    # rcept_no suffix = cheap pseudo-random sample. ORDER BY md5() over the full
    # 102k population forces a sort of every row and hangs for minutes -- don't.
    ap.add_argument("--suffix", default="37", help="rcept_no LIKE '%%<suffix>' sample")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with get_session() as s:
        jobs = s.execute(text("""
            SELECT dt.rcept_no, dt.file_path, f.fiscal_year, f.fiscal_period, f.corp_code
            FROM download_tasks dt JOIN filings f USING(rcept_no)
            WHERE dt.status='completed' AND dt.file_type='xml' AND dt.file_path IS NOT NULL
              AND f.fiscal_year >= 2015 AND dt.rcept_no LIKE :suf
              AND EXISTS (SELECT 1 FROM report_lines rl
                          WHERE rl.rcept_no = dt.rcept_no AND rl.statement='IS'
                            AND rl.label_raw LIKE '%주당%')
        """), {"suf": "%" + args.suffix}).fetchall()
    jobs = [(r.rcept_no, r.file_path, r.fiscal_year, r.fiscal_period, r.corp_code)
            for r in jobs]
    print(f"sample filings = {len(jobs)}", flush=True)

    recs = []
    for done, job in enumerate(jobs, 1):
        recs.extend(scan_one(job))
        if done % 100 == 0:
            print(f"  {done}/{len(jobs)} filings, {len(recs)} rows", flush=True)

    Path(args.out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")

    errs = [r for r in recs if "err" in r]
    rows = [r for r in recs if "err" not in r]
    print(f"\nparse errors = {len(errs)}   classified rows = {len(rows)}")

    ab = [r for r in rows if r["ab"]]
    print(f"\nA∪B(진짜 EPS 라벨) = {len(ab)}행 / 전체 '주당' 행 {len(rows)}")

    print("\n★ 사용자 질문 — 주당이익 섹션 헤더 없이 EPS 항목만 있는가")
    for name, key in (("표 안에 EPS 헤더가 하나도 없음", "tbl_hdr"),
                      ("section_path 말단이 주당 (C-tail)", "c_tail"),
                      ("section_path 어디든 주당 (C-any)", "c_any"),
                      ("직전 헤더가 주당 (구 §3-3 휴리스틱)", "c_prev")):
        if key == "tbl_hdr":
            n = sum(1 for r in ab if not r[key])
            print(f"  {name:<40} {n:>6}행 ({n/max(1,len(ab))*100:5.2f}%)")
        else:
            n = sum(1 for r in ab if r[key])
            print(f"  {name:<40} {n:>6}행 성립 "
                  f"({n/max(1,len(ab))*100:5.2f}%) — 불성립 {len(ab)-n}")

    noh = [r for r in ab if not r["tbl_hdr"]]
    print(f"\n★ EPS 헤더 없는 표의 EPS 행 = {len(noh)}  "
          f"(그중 단위선언도 없음 {sum(1 for r in noh if not r['unit'])})")
    print("  라벨 상위 20종:")
    for lab, n in Counter(r["label"] for r in noh).most_common(20):
        print(f"    {n:>5}  {lab}")
    print("  필링 예시 5건:")
    for r in noh[:5]:
        print(f"    {r['rcept_no']} {r['corp']} {r['code']} | {r['label']} | path={r['path']!r}")

    print("\n★ C-tail 성립인데 A∪B 아님(= C 단독 인정 시 새로 EPS 가 될 행) 상위 20종:")
    conly = [r for r in rows if r["c_tail"] and not r["ab"]]
    print(f"  합계 {len(conly)}행")
    for lab, n in Counter(r["label"] for r in conly).most_common(20):
        print(f"    {n:>5}  {lab}")

    print("\n★ A∪B 인데 C-tail 불성립 — 실제 section_path 상위 20종:")
    for p, n in Counter(r["path"] for r in ab if not r["c_tail"]).most_common(20):
        print(f"    {n:>5}  {p!r}")


if __name__ == "__main__":
    main()
