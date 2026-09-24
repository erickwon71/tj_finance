#!/usr/bin/env python
"""일회성: camp_run 마크다운 이슈로그(#1~#41) → verification.issues 이관.

    python scripts/vq_import_legacy_issues.py            # dry-run 표만 출력
    python scripts/vq_import_legacy_issues.py --apply    # 실제 이관(관리자 계정, main 에서)

상태 규칙(추측 없이 **현재 DB 상태**로만 정한다):
  - 그 필링이 지금 passed/skipped  → closed  (수정 후 재검토 통과, 또는 결함 아님으로 판정됨)
  - 그 필링이 아직 pending(옛 fail) → fixed   (fixed_parser_commit='legacy-unverified')
      수정됐는지는 이관 시점에 확인하지 않는다. fixed 로 두면 검증 러너가 **가장 먼저**
      원문과 재대조해 closed/reopened 를 정한다 — 재확인이 곧 진실의 원천.
  - 필링을 특정할 수 없는 항목(#27 등 여러 필링 비교) → closed, source_defect
원문 항목 전체는 evidence 에 앞부분만 싣고, legacy_ref 로 문서 위치를 남긴다.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import engine  # noqa: E402
from fin2.verification.ops import _require  # noqa: E402

DOC = Path("docs/qa/layer2_review_campaign_issues_2026-09-20.md")
_STMT = (("자본변동표", "SCE"), ("SCE", "SCE"), ("현금흐름표", "CF"), ("손익계산서", "IS"),
         ("재무상태표", "BS"))


def _error_type(head: str, body: str) -> str:
    h = head
    if "결함 아님" in h or "원문 자체" in h or "DART 원문 자체 결함" in h:
        return "source_defect"
    if "부호" in h or "양수" in h:
        return "sign_flip"
    if "소수점" in h:
        return "value_mismatch"
    if "오분류" in h:
        return "column_misassign"
    if "결측" in h or "누락" in h:
        return "missing_row"
    return "unclassified"


# Entries whose heading only says "same pattern as #k" inherit #k's scope and type.
_SAME_AS = {3: 2, 9: 8}


def parse() -> list[dict]:
    s = DOC.read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## (\d+)\. ", s)[1:]
    out = []
    for i in range(0, len(parts), 2):
        n, body = int(parts[i]), parts[i + 1]
        head = " ".join(body.split("\n\n", 1)[0].split())
        m = re.search(r"r?(20\d{12})", head) or re.search(r"r(20\d{12})", body)
        basis = "separate" if head.find("[별도]") != -1 and (
            head.find("[연결]") == -1 or head.find("[별도]") < head.find("[연결]")) else "consolidated"
        stmt = next((code for word, code in _STMT if word in head), "SCE")
        title = head.split("—", 1)[1].strip() if "—" in head else head
        out.append({"n": n, "rcept": m.group(1) if m else None, "basis": basis, "statement": stmt,
                    "label": f"[camp_run#{n}] {title}"[:300], "error_type": _error_type(head, body),
                    "rule_id": None,   # mentions in the text are not reliable fix attribution
                    "evidence": (body.strip()[:1800] + f"\n… (전문: {DOC}#{n})")[:2000]})
    by_n = {it["n"]: it for it in out}
    for n, k in _SAME_AS.items():
        for f in ("basis", "statement", "error_type"):
            by_n[n][f] = by_n[k][f]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    items = parse()
    with engine.connect() as c:
        info = {r[0]: r[1:] for r in c.execute(text("""
            SELECT pf.rcept_no, pf.status, pf.corp_code, pf.fiscal_year, pf.fiscal_period
            FROM verification.progress_filings pf WHERE pf.rcept_no = ANY(:r)"""),
            {"r": [i["rcept"] for i in items if i["rcept"]]}).fetchall()}
        names = dict(c.execute(text("SELECT corp_code, corp_name FROM corporations")).fetchall())
    for it in items:
        st = info.get(it["rcept"])
        it["filing_status"] = st[0] if st else None
        it["slot"] = st[1:] if st else None
        if st is None:
            it["status"], it["error_type"] = "closed", "source_defect"
        elif st[0] in ("passed", "skipped"):
            it["status"] = "closed"
        else:
            it["status"] = "fixed"
    print(f"{'#':>3} {'rcept':15} {'필링상태':8} {'→이슈상태':8} {'유형':15} {'R':7} scope  회사/제목")
    for it in items:
        corp = names.get(it["slot"][0], "?") if it["slot"] else "-"
        print(f"{it['n']:>3} {it['rcept'] or '-':15} {it['filing_status'] or '-':8} "
              f"{it['status']:8} {it['error_type']:15} {it['rule_id'] or '-':7} "
              f"{it['basis'][:3]}-{it['statement'].lower():3} {corp} {it['label'][14:60]}")
    tally: dict[str, int] = {}
    for it in items:
        tally[it["status"]] = tally.get(it["status"], 0) + 1
    print(f"\n합계 {len(items)}건: {tally}  (필링 특정 불가 {sum(1 for i in items if not i['slot'])}건)")
    if not a.apply:
        print("dry-run — 실제 이관은 --apply")
        return 0

    _require("admin")
    n = 0
    with engine.begin() as c:
        for it in items:
            if not it["slot"]:
                print(f"  #{it['n']} 필링 특정 불가 — 문서에만 남김(이관 생략)")
                continue
            corp, fy, fp = it["slot"]
            c.execute(text("SELECT set_config('verification.evidence', :e, true)"),
                      {"e": f"legacy import camp_run#{it['n']}"})
            c.execute(text("""
                INSERT INTO verification.issues
                    (corp_code, fiscal_year, fiscal_period, rcept_no, basis, statement,
                     account_label, error_type, status, rule_id, evidence, legacy_ref, dart_url,
                     fixed_parser_commit, created_by)
                VALUES (:c, :y, :p, :r, :b, :s, :l, :t, :st, :rule, :ev, :ref, :url,
                        CASE WHEN :st = 'fixed' THEN 'legacy-unverified' END, 'camp_run(legacy)')
                """), {"c": corp, "y": fy, "p": fp, "r": it["rcept"], "b": it["basis"],
                       "s": it["statement"], "l": it["label"], "t": it["error_type"],
                       "st": it["status"], "rule": it["rule_id"], "ev": it["evidence"],
                       "ref": f"{DOC}#{it['n']}",
                       "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={it['rcept']}"})
            n += 1
    print(f"이관 완료 {n}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
