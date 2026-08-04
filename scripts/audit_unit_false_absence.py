"""단위 '없음' 판정이 **진짜 없음인지, 못 찾은 것인지** 감사한다 (2026-08-04).

사용자 조건 — "단위가 별도 표시되지 않은 표가 **진짜 단위표시가 없어야**
이전 표의 단위를 쓰는 데 문제가 없다."

정확한 지적이다. `declared_unit()` 이 None 을 돌려주는 데는 두 가지 경우가 있고,
상속의 안전성은 전적으로 여기에 달려 있다:

  ⓐ **진짜 없음** — 제출사가 그 표에 단위를 안 적었다 → 앞 표에서 물려받는 게 합리적
  ⓑ **못 찾음(거짓 부재)** — 원문에 있는데 우리 탐색 위치 규약이 못 봤다
      → 이때 상속하면 **틀린 단위를 조용히 넣는다**(유실보다 나쁜 오염)

그래서 unit=None 인 face 표마다 원문 주변을 훑어 '단위' 토큰이 실재하는지 본다.
탐색 범위를 `declared_unit` 보다 **일부러 넓게** 잡아(표 자신 전문 · 직전 형제 6개 ·
관장 제목표) 우리가 놓쳤을 자리를 드러낸다.

사용:
    python scripts/audit_unit_false_absence.py --scope residual   # 보류 중인 공백 filing
    python scripts/audit_unit_false_absence.py --scope loaded --sample 400
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import table_direct_rows
from fin2.extract.text import (
    _detect_body_statement_tables, _detect_fin_type, declared_unit, declaration_text,
)
from parser.common.amount_normalizer import detect_unit_declaration, detect_unit_tokens

SQL_RESIDUAL = """
WITH grp AS (
  SELECT f.corp_code, f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no,
         count(*) FILTER (
           WHERE EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no=f.rcept_no))
           OVER (PARTITION BY f.corp_code,f.fiscal_year,f.fiscal_period,f.report_type) AS n_loaded,
         max(f.filed_at)
           OVER (PARTITION BY f.corp_code,f.fiscal_year,f.fiscal_period,f.report_type) AS last_filed
    FROM filings f WHERE f.fiscal_year >= 2015
)
SELECT g.corp_name, g.fiscal_year, g.fiscal_period, g.rcept_no, d.file_path
  FROM grp g JOIN download_tasks d ON d.rcept_no = g.rcept_no
 WHERE g.n_loaded = 0 AND g.last_filed <= DATE '2026-07-10'
"""

SQL_LOADED = """
SELECT f.corp_name, f.fiscal_year, f.fiscal_period, f.rcept_no, d.file_path
  FROM filings f JOIN download_tasks d ON d.rcept_no = f.rcept_no
 WHERE f.fiscal_year >= 2015
   AND EXISTS (SELECT 1 FROM report_lines r WHERE r.rcept_no = f.rcept_no)
 ORDER BY md5(f.rcept_no) LIMIT :n
"""

_UNIT_TOKEN = re.compile(r"단\s*위")
# 외화 표시 — 원화 배수가 아니므로 앞 표(원화) 단위를 물려주면 값이 통째로 뜻을 잃는다.
_FOREIGN = re.compile(r"USD|달러|미불|EUR|JPY|CNY|유로|엔|위안", re.I)
# 비금액 단위 — 애초에 금액 상속 대상이 아니다.
_NONMONEY = re.compile(r"단\s*위\s*[:：]?\s*[(（]?\s*(주|좌|%|퍼센트|건|명|개|톤|TON|m2|㎡)")


def _text(el) -> str:
    return " ".join("".join(el.itertext()).split())


def wide_scan(tbl) -> tuple[str, str]:
    """`declared_unit` 보다 넓게 훑어 '단위' 표기를 찾는다 → (어디서, 원문조각)."""
    own = _text(tbl)
    if _UNIT_TOKEN.search(own):
        m = _UNIT_TOKEN.search(own)
        return "표 자신 본문", own[max(0, m.start() - 30):m.start() + 40]
    prev = tbl.getprevious()
    for i in range(6):
        if prev is None:
            break
        t = _text(prev)
        if _UNIT_TOKEN.search(t):
            m = _UNIT_TOKEN.search(t)
            return f"직전 형제 -{i+1}", t[max(0, m.start() - 30):m.start() + 40]
        prev = prev.getprevious()
    return "", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["residual", "loaded"], default="residual")
    ap.add_argument("--sample", type=int, default=400)
    args = ap.parse_args()

    with get_session() as s:
        rows = (s.execute(text(SQL_RESIDUAL)).fetchall() if args.scope == "residual"
                else s.execute(text(SQL_LOADED), {"n": args.sample}).fetchall())

    kinds: Counter = Counter()
    examples: list = []
    n_face = n_held = 0
    docs = 0

    for corp_name, fy, fp, rcept, fpth in rows:
        if not fpth or not Path(fpth).exists():
            continue
        root = _parse_xml_file(Path(fpth))
        if root is None:
            continue
        docs += 1
        groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
        for code, v in groups.items():
            for tbl, unit, _k in v:
                n_face += 1
                if unit is not None:
                    continue
                n_held += 1
                where, frag = wide_scan(tbl)
                if not where:
                    kinds["ⓐ 진짜 단위 표기 없음 → 상속 후보"] += 1
                    if len(examples) < 15:
                        examples.append((corp_name, fy, fp, rcept, code, where, None, "(없음)"))
                    continue
                # 토큰은 있다 — 그것이 유효한 원화 배수로 해석되는가?
                parsed = detect_unit_declaration(frag)
                if parsed:
                    tag = "ⓑ 원화 배수인데 못 찾음(거짓 부재) → ★상속하면 위험"
                elif _FOREIGN.search(frag):
                    tag = "ⓒ-1 외화 선언(USD 등) → ★★상속하면 치명적"
                elif _NONMONEY.search(frag):
                    tag = "ⓒ-2 비금액 단위(주·%·좌 등) → 상속 대상 아님"
                else:
                    tag = "ⓒ-3 '단위' 토큰 있으나 해석 불가"
                kinds[tag] += 1
                if len(examples) < 15 and not tag.startswith("ⓒ-1"):
                    examples.append((corp_name, fy, fp, rcept, code, where, parsed, frag))

    print(f"=== scope={args.scope} · 문서 {docs}건 · face 표 {n_face}개 ===")
    print(f"    그중 단위 미확정(보류) face 표 : {n_held}\n")
    for k, v in kinds.most_common():
        pct = v / max(n_held, 1) * 100
        print(f"  {v:5d} ({pct:5.1f}%)  {k}")

    if examples:
        print("\n  사례:")
        for corp_name, fy, fp, rcept, code, where, parsed, frag in examples:
            print(f"    {corp_name} {fy}{fp} {rcept} [{code}]")
            print(f"       위치={where} 해석={parsed} 원문={frag!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
