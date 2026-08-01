"""Follow-up analysis of the JSON produced by survey_biz_section_inventory.py (READ-ONLY).

Shows per-industry captions by raw frequency, without the '2x the overall rate' filter, and
breaks down what the '(캡션없음)' bucket actually is.

Usage:
    python scripts/survey_biz_section_drill.py --json scratchpad/biz_inv.json --ind 64,65,66
    python scripts/survey_biz_section_drill.py --json ... --nocaption
    python scripts/survey_biz_section_drill.py --json ... --corp 삼성전자
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load(p: str) -> list[dict]:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def ind_report(recs: list[dict], ind2: str, top: int) -> None:
    grp = [r for r in recs if (r["induty_code"] or "??")[:2] == ind2]
    if not grp:
        print(f"\n### KSIC {ind2}: 표본 없음")
        return
    cap_corp: dict[str, set] = defaultdict(set)
    cap_num: Counter = Counter()
    ex: dict[str, str] = {}
    for r in grp:
        for t in r["tables"]:
            c = t["caption"] or "(캡션없음)"
            cap_corp[c].add(r["corp_code"])
            cap_num[c] += t["num_cells"]
            ex.setdefault(c, f"{r['corp_name']}: {t['caption_raw'][:34]}")
    print(f"\n### KSIC {ind2}  n={len(grp)}사 — {', '.join(r['corp_name'] for r in grp[:12])}")
    print(f"{'캡션':<38} {'기업':>4} {'커버':>5} {'숫자셀':>7}  예시")
    for c, corps in sorted(cap_corp.items(), key=lambda x: -len(x[1]))[:top]:
        if c == "(캡션없음)":
            continue
        print(f"{c[:37]:<38} {len(corps):>4} {len(corps)/len(grp)*100:>4.0f}% "
              f"{cap_num[c]:>7,}  {ex[c][:52]}")


def nocaption_report(recs: list[dict]) -> None:
    sub: Counter = Counter()
    sub_num: Counter = Counter()
    corp: Counter = Counter()
    for r in recs:
        for t in r["tables"]:
            if t["caption"]:
                continue
            sub[t["subsection"]] += 1
            sub_num[t["subsection"]] += t["num_cells"]
            corp[r["corp_name"]] += 1
    print("\n### '(캡션없음)' 표의 소제목 분포")
    print(f"{'소제목':<34} {'표':>6} {'숫자셀':>9}")
    for s, n in sub.most_common(15):
        print(f"{s[:33]:<34} {n:>6,} {sub_num[s]:>9,}")
    print("\n상위 기업(표 수):", ", ".join(f"{k}({v})" for k, v in corp.most_common(12)))


def corp_report(recs: list[dict], name: str) -> None:
    for r in recs:
        if name not in r["corp_name"]:
            continue
        print(f"\n### {r['corp_name']} ({r['market']}, KSIC {r['induty_code']}) "
              f"FY{r['fiscal_year']} · 표 {len(r['tables'])}개")
        cur = None
        for t in r["tables"]:
            if t["subsection"] != cur:
                cur = t["subsection"]
                print(f"  [{cur}]")
            print(f"    {t['caption_raw'][:50]:<52} {t['rows']:>3}x{t['cols']:<3} "
                  f"숫자{t['num_cells']:>5}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--ind", help="쉼표구분 KSIC 2자리")
    ap.add_argument("--top", type=int, default=22)
    ap.add_argument("--nocaption", action="store_true")
    ap.add_argument("--corp", help="기업명 부분일치 드릴")
    args = ap.parse_args()

    recs = load(args.json)
    if args.nocaption:
        nocaption_report(recs)
    if args.corp:
        corp_report(recs, args.corp)
    for ind in (args.ind or "").split(","):
        if ind.strip():
            ind_report(recs, ind.strip(), args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
