"""Which sections does each amendment KIND actually carry? (READ-ONLY)

User's domain rule (2026-08-01): "[첨부정정] does not amend the periodic report body — it
covers corrections to the audit report / opinions / articles of incorporation. What we care
about is [기재정정] of the quarterly / half-year / annual report."

That is a checkable claim, so it is measured here rather than assumed. For a sample of
amendment filings we count, per amendment kind, how many actually contain the report-body
sections ('사업의 내용', '회사의 개요') versus only attachment-side sections
(재무제표 / 주석).

  python scripts/probe_amendment_kind_scope.py --limit 220
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import _load_root, _tag, _text
from parser.xml.section_detector import normalize_dart_section_title

SQL = """
    SELECT f.rcept_no, f.report_nm, f.report_type, c.corp_name, d.file_path
    FROM filings f
    JOIN download_tasks d ON d.rcept_no = f.rcept_no
    JOIN corporations c ON c.corp_code = f.corp_code
    WHERE c.is_active AND c.stock_code IS NOT NULL
      AND f.report_nm LIKE '[%'
      AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
"""

BODY = {"사업의내용", "회사의개요"}
ATTACH = {"연결재무제표", "재무제표", "연결재무제표주석", "재무제표주석"}


def kind(report_nm: str) -> str:
    m = re.match(r"\[([^\]]+)\]", report_nm or "")
    return m.group(1) if m else "(정정아님)"


def sections_of(root) -> set[str]:
    out = set()
    for el in root.iter():
        if _tag(el) == "TITLE":
            t = normalize_dart_section_title(re.sub(r"\s+", " ", _text(el)).strip())
            if t:
                out.add(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=220)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    with get_session() as s:
        rows = [dict(r._mapping) for r in s.execute(text(SQL)).fetchall()]
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]

    tot: Counter = Counter()
    has_body: Counter = Counter()
    has_attach: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    for r in rows:
        p = Path(r["file_path"])
        if not p.exists():
            continue
        try:
            root = _load_root(p)
        except Exception:                                          # noqa: BLE001
            continue
        if root is None:
            continue
        k = kind(r["report_nm"])
        secs = sections_of(root)
        tot[k] += 1
        if secs & BODY:
            has_body[k] += 1
            if len(examples[k]) < 3:
                examples[k].append(f"{r['corp_name']} {r['rcept_no']}")
        if secs & ATTACH:
            has_attach[k] += 1

    print(f"정정 공시 {sum(tot.values())}건 (XML 본문 기준)\n")
    h = f"{'정정 종류':<14} {'건수':>6} {'본문 포함':>18} {'재무제표/주석 포함':>20}"
    print(h)
    print("-" * len(h))
    for k, n in tot.most_common():
        print(f"{k:<14} {n:>6} {has_body[k]:>8} ({has_body[k]/n*100:>5.1f}%) "
              f"{has_attach[k]:>12} ({has_attach[k]/n*100:>5.1f}%)")
    for k, ex in examples.items():
        if ex:
            print(f"\n  {k} 인데 본문을 담은 예: {', '.join(ex)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
