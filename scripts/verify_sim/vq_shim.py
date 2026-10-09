#!/usr/bin/env python
"""Simulation stand-in for scripts/vq.py (A/B test of verifier models).

Same command surface the verifier prompt uses, but:
- show / recheck print the frozen snapshot of the slot (SIM_SNAP/<slot>/), so every run sees the same input;
- issue add / pass / skip / close / reopen / withdraw / done write nothing to the DB, they append
  to SIM_OUT/actions.jsonl (validation mirrors fin2.verification.ops so refusals stay realistic);
- machine issues-json uses the real converter on the frozen findings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path("/Users/taejin/Project/tj_finance")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import vq as real  # noqa: E402
from fin2.verification import ops  # noqa: E402

SNAP = Path(os.environ["SIM_SNAP"])
OUT = Path(os.environ["SIM_OUT"])
SLOT = os.environ["SIM_SLOT"]


def _load():
    return json.loads((SNAP / SLOT.replace(":", "_") / "detail.json").read_text())


def _log(rec: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "actions.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _actions() -> list[dict]:
    p = OUT / "actions.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def deny(msg):
    print(f"거부: {msg}", file=sys.stderr)
    sys.exit(2)


def _slot_ok(s):
    if s and s != SLOT:
        deny(f"{s} 는 이 세션이 점유한 슬롯이 아니다 — `vq.py next` 로 점유 후 진행.")


def _filing(rcept):
    for f in _load()["detail"]["filings"]:
        if f["rcept_no"] == rcept:
            return f
    deny(f"{rcept} 는 이 슬롯의 검증 대상 필링이 아니다")


def cmd_show(a):
    _slot_ok(a.slot)
    s = _load()
    if a.json:
        print(real._j({**s["detail"], "csvs": s["csvs"]}))
    else:
        real._print_detail(s["detail"], None if a.no_csv else s["csvs"])


def cmd_recheck(a):
    _slot_ok(a.slot)
    rows = json.loads((SNAP / SLOT.replace(":", "_") / "recheck.json").read_text())
    if not rows:
        print("재확인 대기(fixed) 이슈 없음")
        return
    real.ops.recheck_list = lambda slot=None: rows
    real.cmd_recheck(argparse.Namespace(slot=None))


def _key(rcept, row):
    return (rcept, row["basis"], row["statement"], row["account_label"], row.get("column_label") or "")


def cmd_issue_add(a):
    f = _filing(a.rcept)
    if a.json_file:
        p = Path(a.json_file)
        if not p.exists():
            deny(f"파일 없음: {a.json_file}")
        items = json.loads(p.read_text(encoding="utf-8"))
        items = items if isinstance(items, list) else [items]
    else:
        items = [{k: getattr(a, k) for k in ops._ISSUE_FIELDS if getattr(a, k, None) is not None}]
    ids, suppressed, already = [], [], []
    active = {_key(i["rcept_no"], i): i["issue_id"] for i in _load()["detail"]["open_issues"]}
    active.update({_key(x["rcept"], x["item"]): x["id"] for x in _actions() if x["act"] == "issue"})
    seen = set()
    from collector.db import engine
    with engine.connect() as conn:
        for it in items:
            bad = set(it) - set(ops._ISSUE_FIELDS)
            if bad:
                deny(f"알 수 없는 이슈 필드 {sorted(bad)}")
            for req in ("basis", "statement", "account_label", "error_type"):
                if not it.get(req):
                    deny(f"이슈 필드 {req} 필수")
            row = {k: it.get(k) for k in ops._ISSUE_FIELDS}
            if row.get("statement") == "CIS":
                row["statement"] = "IS"
            row["column_label"] = ops._strip_column_label_prefix(row.get("column_label"))
            if row.get("error_type") == "source_defect":
                row["column_label"] = ops._identity_column_label(row.get("column_label"))
            elif row.get("error_type") == "label_mismatch":
                row["column_label"] = None
            if row.get("source_unit") and row["source_unit"] not in ops._SOURCE_UNITS:
                row["evidence"] = f"표시통화 {row['source_unit']} · {row.get('evidence') or ''}"
                row["source_unit"] = None
            if not (row.get("evidence") or "").startswith("["):
                import re as _re
                row["account_label"] = _re.sub(r"\s*\(#\d+\)$", "", row["account_label"]) or row["account_label"]
            k, n, base = _key(a.rcept, row), 2, row["account_label"]
            while k in seen:
                row["account_label"] = f"{base[:280]} (#{n})"; k = _key(a.rcept, row); n += 1
            seen.add(k)
            if k in active:
                already.append({"account_label": row["account_label"], "column_label": row["column_label"], "issue_id": active[k]})
                _log({"act": "already", "rcept": a.rcept, "item": row})
                continue
            try:
                prior = ops._prior_no_fix(conn, a.rcept, row)
            except Exception:  # noqa: BLE001
                conn.rollback(); prior = None
            if prior is not None:
                suppressed.append({"account_label": row["account_label"], "column_label": row["column_label"],
                                   "db_value": row.get("db_value"), "prior_issue_id": prior["issue_id"],
                                   "prior_verdict": (prior["evidence"] or "")[:300]})
                _log({"act": "suppressed", "rcept": a.rcept, "item": row, "prior": prior["issue_id"]})
                continue
            nid = 900000 + sum(1 for x in _actions() if x["act"] == "issue") + 1
            ids.append(nid)
            _log({"act": "issue", "rcept": a.rcept, "item": row, "id": nid})
    print(f"이슈 등록 {len(ids)}건: {ids}")
    if already:
        print(f"★등록 안 함 {len(already)}건 — 이미 미해결 이슈가 걸린 셀(다시 등록하지 않는다):")
        for x in already:
            print(f"    {x['account_label']}{'/' + x['column_label'] if x['column_label'] else ''} → #{x['issue_id']}")
    if suppressed:
        print(f"★등록 안 함 {len(suppressed)}건 — 수정쪽이 이미 '코드수정 불필요'로 결론낸 셀(DB 값 동일). "
              f"등록하지 않은 것으로 센다(검증 러너는 다투지 않는다):")
        for x in suppressed:
            print(f"    {x['account_label']}{'/' + x['column_label'] if x['column_label'] else ''} "
                  f"DB={x['db_value']} → 이전 #{x['prior_issue_id']}: {x['prior_verdict'][:160]}")
        if not ids:
            print("    이 필링에 다른 불일치가 없으면 이슈 없이 pass 한다.")


def cmd_pass(a):
    f = _filing(a.rcept)
    given = sorted({s.strip() for s in a.verified_scopes.split(",") if s.strip()})
    loaded = sorted((f.get("scope_hashes") or {}).keys())
    if not loaded:
        deny(f"{a.rcept} 는 적재된 scope 가 없다 — 원문에 표가 없으면 `vq.py skip --rcept {a.rcept} --note ...` 로 처리.")
    if given != loaded:
        deny(f"--verified-scopes 가 실제 적재 scope 와 다르다.\n  적재됨: {','.join(loaded)}\n  입력:   {','.join(given)}\n"
             f"적재된 scope 는 전부 원문과 대조해야 pass 할 수 있다(8scope 전체대조 규약).")
    n_open = sum(1 for i in _load()["detail"]["open_issues"] if i["rcept_no"] == a.rcept)
    n_open += sum(1 for x in _actions() if x["act"] == "issue" and x["rcept"] == a.rcept)
    if n_open:
        deny(f"{a.rcept} 에 미해결 이슈 {n_open}건 — pass 불가(`vq.py done` 으로 슬롯 종료).")
    _log({"act": "pass", "rcept": a.rcept, "scopes": given, "note": a.note})
    print(real._j({"rcept_no": a.rcept, "status": "passed", "scopes": given}))


def cmd_skip(a):
    _filing(a.rcept)
    if not a.note:
        deny("skip 에는 --note(사유)가 필수")
    _log({"act": "skip", "rcept": a.rcept, "note": a.note})
    print(real._j({"rcept_no": a.rcept, "status": "skipped"}))


def cmd_transition(name):
    def fn(a):
        _log({"act": name, "issue_id": a.issue_id, "evidence": a.evidence})
        print(real._j({"issue_id": a.issue_id, "status": "closed" if name != "reopen" else "reopened"}))
    return fn


def cmd_done(a):
    _slot_ok(a.slot)
    _log({"act": "done"})
    print(real._j({"slot": SLOT, "status": "simulated"}))


def cmd_machine(a):
    if a.action != "issues-json":
        deny("이 명령은 검증 세션에서 허용되지 않는다")
    if not a.rcept or len(a.rcept) != 1 or not a.out:
        deny("issues-json 은 --rcept <접수번호 1개> --out <파일> 이 필요하다")
    f = _filing(a.rcept[0])
    from fin2.verification import machine_pass
    fs = f.get("machine_findings") or []
    if bool(a.kinds) == bool(getattr(a, "findings", None)):
        deny("issues-json 은 --findings <발견 번호,...> 또는 --kinds <종류,...> 중 하나만 준다")
    if a.findings:
        try:
            sel = sorted({int(x) for x in a.findings.split(",") if x.strip()})
        except ValueError:
            deny("--findings 는 show 의 발견 번호(쉼표 구분 정수)다")
        bad = [n for n in sel if not 1 <= n <= len(fs)]
        if bad:
            deny(f"발견 번호 {bad} 가 없다(이 필링 발견 1~{len(fs)})")
        items = machine_pass.findings_to_issues(fs, select=sel, prefix=machine_pass.CONFIRMED_PREFIX)
        skipped = [n for n in sel if fs[n - 1]["kind"] in ("sce_identity", "sce_arith", "sign_omitted")
                   and not fs[n - 1].get("src_broken")]
        if skipped:
            print(f"★발견 {skipped} 은 원문 숫자로는 닫히는 항등식(I2)이라 source_defect 를 만들지 않았다")
        kinds = None
    else:
        kinds = tuple(k.strip() for k in a.kinds.split(","))
        items = machine_pass.findings_to_issues(fs, kinds, prefix=machine_pass.CONFIRMED_PREFIX)
    Path(a.out).write_text(json.dumps(items, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    by = {}
    for i in items:
        by[i["error_type"]] = by.get(i["error_type"], 0) + 1
    _log({"act": "issues_json", "rcept": a.rcept[0], "kinds": kinds, "findings": a.findings, "n": len(items)})
    print(f"이슈 {len(items)}건 → {a.out} {by}  (등록: vq.py issue add --rcept {a.rcept[0]} --json-file {a.out})")


def main():
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("show"); x.add_argument("slot", nargs="?")
    x.add_argument("--no-csv", action="store_true"); x.add_argument("--json", action="store_true")
    x.set_defaults(fn=cmd_show)
    x = sp.add_parser("recheck"); x.add_argument("slot", nargs="?"); x.set_defaults(fn=cmd_recheck)
    x = sp.add_parser("pass"); x.add_argument("--rcept", required=True)
    x.add_argument("--verified-scopes", required=True); x.add_argument("--note"); x.set_defaults(fn=cmd_pass)
    x = sp.add_parser("skip"); x.add_argument("--rcept", required=True)
    x.add_argument("--note", required=True); x.set_defaults(fn=cmd_skip)
    x = sp.add_parser("issue"); isp = x.add_subparsers(dest="sub", required=True)
    y = isp.add_parser("add"); y.add_argument("--rcept", required=True); y.add_argument("--json-file")
    for f in ops._ISSUE_FIELDS:
        y.add_argument("--" + f.replace("_", "-"), dest=f)
    y.set_defaults(fn=cmd_issue_add)
    x = sp.add_parser("done"); x.add_argument("--slot"); x.add_argument("--json", action="store_true")
    x.set_defaults(fn=cmd_done)
    for name in ("close", "reopen", "withdraw"):
        x = sp.add_parser(name); x.add_argument("issue_id", type=int)
        x.add_argument("--evidence", required=True); x.set_defaults(fn=cmd_transition(name))
    x = sp.add_parser("machine"); x.add_argument("action")
    x.add_argument("--kinds"); x.add_argument("--findings"); x.add_argument("--out"); x.add_argument("--rcept", nargs="*")
    x.add_argument("--limit", type=int); x.add_argument("--value")
    x.set_defaults(fn=cmd_machine)
    x = sp.add_parser("identity"); x.add_argument("--terms", required=True); x.add_argument("--total", required=True)
    x.add_argument("--unit", required=True); x.add_argument("--eps-unit", default="1")
    x.set_defaults(fn=real.cmd_identity)
    for name in ("whoami", "status", "next", "claim", "fix-queue", "issues", "batch", "ask", "decision",
                 "runner", "admin", "withdraw-released", "stale-tabs", "rcepts"):
        x = sp.add_parser(name); x.add_argument("rest", nargs="*")
        x.set_defaults(fn=lambda a: deny("이 명령은 검증 세션에서 허용되지 않는다"))
    a, extra = p.parse_known_args()
    if extra:
        deny(f"알 수 없는 인자 {extra}")
    a.fn(a)


if __name__ == "__main__":
    main()
