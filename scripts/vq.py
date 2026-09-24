#!/usr/bin/env python
"""verification 캠페인 CLI — 모든 상태는 DB(verification 스키마)에 있다.

설계: docs/plans/verification_schema_two_worktree_design_2026-09-24.md
운영: docs/verification/WORKFLOW.md

역할은 DB 계정이 정한다(워크트리 .env 의 DATABASE_URL):
  검증 camp_run        (tjf_verify)  next · show · pass · skip · issue add · done · recheck · close · reopen
  수정 camp_err_review (tjf_fix)     fix-queue · batch … · ask · decision …
  main                 (관리자)       admin …

자주 쓰는 명령:
  python scripts/vq.py whoami
  python scripts/vq.py status
  python scripts/vq.py next                                   # 검증: 이어하기/다음 슬롯 점유
  python scripts/vq.py pass --rcept R --verified-scopes sep-bs,sep-is,... --note "..."
  python scripts/vq.py issue add --rcept R --json-file issues.json
  python scripts/vq.py done
  python scripts/vq.py fix-queue                              # 수정: 오류유형별 대기열
  python scripts/vq.py batch new --type sign_flip --title "..." [--rule R167]
  python scripts/vq.py batch reload 3
  python scripts/vq.py batch mark-fixed 3
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from fin2.verification import ops  # noqa: E402
from fin2.verification.ops import Slot, VqError  # noqa: E402


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, indent=1)


def _scopes_fmt(d: dict | None) -> str:
    return ", ".join(f"{k}={v}" for k, v in (d or {}).items()) or "(적재 행 없음)"


# ─────────────────────────────── common ───────────────────────────────
def cmd_whoami(a):
    print(_j(ops.whoami()))


def cmd_status(a):
    st = ops.status()
    if a.json:
        print(_j(st))
        return
    print(f"[verification 현황 {st['at']}]")
    print(f"  슬롯   : {st['slots']}")
    print(f"  필링   : {st['filings']}")
    print(f"  이슈   : {st['issues']}")
    print(f"  완료 회사: {st['corps_done']}사 · 시총 상위200 슬롯 passed "
          f"{st['top200_passed']}/{st['top200_total']}")
    print(f"  점유 중 : {[(r['corp_code'], r['fiscal_year'], r['fiscal_period'], r['claimed_by']) for r in st['in_progress']]}")
    print(f"  러너 24h: {st['runs_24h']} · 대기 판단 {st['pending_decisions']}건")
    warn = " ★경고: 50GB 미만" if (st["disk_free_gb"] or 999) < 50 else ""
    print(f"  디스크 : DB {st['db_size']} · verification {st['verification_schema_size']} · "
          f"여유 {st['disk_free_gb']} GB{warn}")


# ─────────────────────────────── verify ───────────────────────────────
def _print_detail(d: dict, csvs: dict[str, str] | None) -> None:
    s = d["slot"]
    print(f"\n■ 슬롯 {s['corp_code']}:{s['fiscal_year']}:{s['fiscal_period']}  "
          f"{s['corp_name']} ({s['market']}, 시총순위 {s['corp_rank']})  상태={s['status']}"
          f"  점유={s['claimed_by']} ~{s['lease_until']}")
    for f in d["filings"]:
        print(f"\n  [{f['seq_in_slot']}] {f['rcept_no']} {f['report_nm']} (접수 {f['filed_at']})"
              f"{' ·정정' if f['is_amendment'] else ''}  상태={f['status']}")
        print(f"      DART: {f['dart_url']}")
        if csvs and f["rcept_no"] in csvs:
            print(f"      CSV : {csvs[f['rcept_no']]}")
        print(f"      적재: load_seq={f['load_seq']} parser={f['parser_commit']} "
              f"({'baseline' if f['baseline'] else f['loaded_at']})")
        print(f"      scope 행수: {_scopes_fmt(f['scope_rows'])}")
        print(f"      → pass 시 --verified-scopes {','.join(f['scope_rows'])}")
        if f["changed_since_verified"] is not None:
            print(f"      ★이전 판정({f['verified_at']}) 이후 바뀐 scope: "
                  f"{f['changed_since_verified'] or '없음'} — 바뀐 scope 만 원문 재대조")
        for other, same in f["identical_to_earlier"].items():
            print(f"      = {other} 와 byte-identical: {','.join(same)}")
    if d["open_issues"]:
        print("\n  미해결 이슈:")
        for i in d["open_issues"]:
            print(f"    #{i['issue_id']} [{i['status']}] {i['rcept_no']} {i['basis']}/{i['statement']} "
                  f"{i['account_label']}{'/' + i['column_label'] if i['column_label'] else ''} "
                  f"DB={i['db_value']} 원문={i['source_value_raw']} ({i['error_type']})")


def _show(slot: Slot, a) -> None:
    d = ops.slot_detail(slot)
    csvs = None if getattr(a, "no_csv", False) else ops.write_review_csvs(slot, d)
    if getattr(a, "json", False):
        print(_j({**d, "csvs": csvs}))
    else:
        _print_detail(d, csvs)


def cmd_next(a):
    slot = ops.own_slot()
    if slot:
        print(f"이어하기: 이 세션이 점유 중인 슬롯 {slot}")
    else:
        slot = ops.claim()
        if slot is None:
            print("대기 슬롯 없음")
            return
        print(f"점유: {slot}")
    _show(slot, a)


def cmd_claim(a):
    slot = ops.claim(Slot.parse(a.slot) if a.slot else None)
    if a.json:
        print(json.dumps({"slot": str(slot) if slot else None}))
    else:
        print(slot or "대기 슬롯 없음")


def cmd_show(a):
    slot = Slot.parse(a.slot) if a.slot else ops.own_slot()
    if slot is None:
        raise VqError("점유 중인 슬롯이 없다 — 슬롯을 지정하거나 `next`")
    _show(slot, a)


def cmd_pass(a):
    scopes = [s.strip() for s in a.verified_scopes.split(",") if s.strip()]
    print(_j(ops.pass_filing(a.rcept, scopes, a.note)))


def cmd_skip(a):
    print(_j(ops.skip_filing(a.rcept, a.note)))


def cmd_issue_add(a):
    if a.json_file:
        items = json.loads(Path(a.json_file).read_text(encoding="utf-8"))
        items = items if isinstance(items, list) else [items]
    else:
        items = [{k: getattr(a, k) for k in ops._ISSUE_FIELDS if getattr(a, k, None) is not None}]
    ids = ops.add_issues(a.rcept, items)
    print(f"이슈 등록 {len(ids)}건: {ids}")


def cmd_done(a):
    res = ops.done(Slot.parse(a.slot) if a.slot else None)
    print(json.dumps(res, ensure_ascii=False) if a.json else _j(res))


def cmd_recheck(a):
    rows = ops.recheck_list(Slot.parse(a.slot) if a.slot else None)
    if not rows:
        print("재확인 대기(fixed) 이슈 없음")
    for r in rows:
        print(f"#{r['issue_id']} {r['corp_code']}:{r['fiscal_year']}:{r['fiscal_period']} {r['rcept_no']} "
              f"{r['basis']}/{r['statement']} {r['account_label']}"
              f"{'/' + r['column_label'] if r['column_label'] else ''}  원문={r['source_value_raw']}"
              f"({r['source_unit']}) 등록시DB={r['db_value']} 현재DB={r['db_value_now']}  "
              f"fix={r['fixed_parser_commit']} batch={r['fix_batch_id']} {r['rule_id'] or ''}")
        print(f"    {r['dart_url']}")


def cmd_close(a):
    print(_j(ops.transition(a.issue_id, "closed", a.evidence)))


def cmd_reopen(a):
    print(_j(ops.transition(a.issue_id, "reopened", a.evidence)))


def cmd_withdraw(a):
    print(_j(ops.transition(a.issue_id, "closed", "[withdrawn] " + a.evidence)))


# ─────────────────────────────── fix ───────────────────────────────
def cmd_fix_queue(a):
    q = ops.fix_queue()
    if a.json:
        print(_j(q))
        return
    if q["decisions"]:
        print("■ 판단")
        for d in q["decisions"]:
            ans = f"→ {d['answer_key'] or ''} {d['answer_text'] or ''}".strip() if d["status"] == "answered" else ""
            print(f"  #{d['decision_id']} [{d['status']}] batch={d['batch_id']} {d['question']} {ans}")
    print("■ 진행 중 배치 (답이 온 판단이 걸린 배치 → reloading → 나머지 순)")
    for b in q["batches"] or []:
        print(f"  batch {b['batch_id']} [{b['status']}] {b['error_type']} {b['rule_id'] or ''} "
              f"{b['title']} — fixing {b['n_fixing']}건, 재적재 대기 {b['n_to_reload']}건"
              f"{', ★답 도착' if b['n_answered'] else ''}")
    if not q["batches"]:
        print("  없음")
    print("■ 미배정 이슈 (error_type 별)")
    for g in q["groups"] or []:
        print(f"  {g['error_type']:17s} {g['label_ko']:10s} 이슈 {g['n_issues']:4d} · 필링 {g['n_filings']} · "
              f"회사 {g['n_corps']} · 재오픈 {g['n_reopened']} (첫 이슈 #{g['first_issue']})")
    if not q["groups"]:
        print("  없음")


def cmd_issues(a):
    for r in ops.issues_of_type(a.type):
        print(f"#{r['issue_id']} [{r['status']}] {r['corp_name']} {r['fiscal_year']}{r['fiscal_period']} "
              f"{r['rcept_no']} {r['basis']}/{r['statement']} {r['account_label']}"
              f"{'/' + r['column_label'] if r['column_label'] else ''} DB={r['db_value']} "
              f"원문={r['source_value_raw']}({r['source_unit']})")
        if r["evidence"]:
            print(f"    근거: {r['evidence'][:300]}")


def cmd_batch_new(a):
    ids = [int(x) for x in a.issues.split(",")] if a.issues else None
    print(_j(ops.batch_new(a.type, a.title, ids, a.rule)))


def cmd_batch_add(a):
    rcepts = [t.strip() for t in Path(a.rcept_file).read_text(encoding="utf-8").split() if t.strip()]
    print(f"대상 추가 {ops.batch_add_targets(a.batch_id, rcepts)}건 (입력 {len(rcepts)})")


def cmd_batch_reload(a):
    print(_j(ops.batch_reload(a.batch_id, a.limit)))


def cmd_batch_mark_fixed(a):
    print(_j(ops.batch_mark_fixed(a.batch_id)))


def cmd_batch_set(a):
    ops.batch_set(a.batch_id, status=a.status, rule_id=a.rule, note=a.note)
    print("ok")


def cmd_ask(a):
    from fin2.verification import decisions as dz
    opts = [dz.parse_option(o) for o in a.option]
    res = dz.ask(category=a.category, question=a.question, options=opts,
                 recommended=a.recommend, dedupe_key=a.key or a.question,
                 batch_id=a.batch, issue_id=a.issue, expires_hours=a.expires_hours,
                 apply_default=not a.no_default)
    print(_j(res))


def cmd_decision(a):
    from fin2.verification import decisions as dz
    if a.action == "list":
        print(_j(dz.pending()))
    elif a.action == "wait":
        print(_j(dz.wait(a.id, a.timeout)))
    elif a.action == "answer":
        print(dz.answer_terminal(a.id, a.key, a.text))
    elif a.action == "cancel":
        dz.cancel(a.id, a.text or "cancelled")
        print("cancelled")


# ─────────────────────────────── runner ───────────────────────────────
def cmd_runner(a):
    from fin2.verification import runner
    if a.action == "start":
        print(runner.start(Slot.parse(a.slot), a.model))
    elif a.action == "finish":
        print(json.dumps(runner.finish(a.run_id, Path(a.log), a.exit_code), ensure_ascii=False))
    elif a.action == "budget":
        print(json.dumps(runner.budget_state(), ensure_ascii=False))


# ─────────────────────────────── admin ───────────────────────────────
def cmd_admin(a):
    ops._require("admin")
    if a.action == "apply-schema":
        from collector.db import engine
        from fin2.verification.schema import apply_schema
        apply_schema(engine)
        print("schema applied")
    elif a.action == "init":
        print(_j(ops.init_era(a.era)))
    elif a.action == "import-queue":
        print(_j(ops.import_legacy_queue(dry_run=not a.apply)))
    elif a.action == "expire":
        from fin2.verification import decisions as dz
        print(dz.expire_due())
    elif a.action == "send-unsent":
        from fin2.verification import decisions as dz
        print(dz.send_unsent())
    elif a.action == "audit-sample":
        from collector.db import engine
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT corp_code, fiscal_year, fiscal_period FROM verification.progress
                WHERE status = 'passed'""")).fetchall()
        k = max(1, round(len(rows) * a.pct / 100)) if rows else 0
        for r in random.sample(rows, k):
            print(f"{r[0]}:{r[1]}:{r[2]}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("whoami").set_defaults(fn=cmd_whoami)
    x = sp.add_parser("status"); x.add_argument("--json", action="store_true"); x.set_defaults(fn=cmd_status)

    x = sp.add_parser("next", help="검증: 점유 중 슬롯 재개 또는 다음 슬롯 점유 + 상세/CSV")
    x.add_argument("--no-csv", action="store_true"); x.add_argument("--json", action="store_true")
    x.set_defaults(fn=cmd_next)
    x = sp.add_parser("claim", help="러너용: 슬롯 점유만")
    x.add_argument("--slot"); x.add_argument("--json", action="store_true"); x.set_defaults(fn=cmd_claim)
    x = sp.add_parser("show"); x.add_argument("slot", nargs="?")
    x.add_argument("--no-csv", action="store_true"); x.add_argument("--json", action="store_true")
    x.set_defaults(fn=cmd_show)
    x = sp.add_parser("pass"); x.add_argument("--rcept", required=True)
    x.add_argument("--verified-scopes", required=True); x.add_argument("--note")
    x.set_defaults(fn=cmd_pass)
    x = sp.add_parser("skip"); x.add_argument("--rcept", required=True)
    x.add_argument("--note", required=True); x.set_defaults(fn=cmd_skip)
    x = sp.add_parser("issue"); isp = x.add_subparsers(dest="sub", required=True)
    y = isp.add_parser("add"); y.add_argument("--rcept", required=True); y.add_argument("--json-file")
    for f in ops._ISSUE_FIELDS:
        y.add_argument("--" + f.replace("_", "-"), dest=f)
    y.set_defaults(fn=cmd_issue_add)
    x = sp.add_parser("done"); x.add_argument("--slot"); x.add_argument("--json", action="store_true")
    x.set_defaults(fn=cmd_done)
    x = sp.add_parser("recheck"); x.add_argument("slot", nargs="?"); x.set_defaults(fn=cmd_recheck)
    for name, fn in (("close", cmd_close), ("reopen", cmd_reopen), ("withdraw", cmd_withdraw)):
        x = sp.add_parser(name); x.add_argument("issue_id", type=int)
        x.add_argument("--evidence", required=True); x.set_defaults(fn=fn)

    x = sp.add_parser("fix-queue"); x.add_argument("--json", action="store_true"); x.set_defaults(fn=cmd_fix_queue)
    x = sp.add_parser("issues"); x.add_argument("--type", required=True); x.set_defaults(fn=cmd_issues)
    x = sp.add_parser("batch"); bsp = x.add_subparsers(dest="sub", required=True)
    y = bsp.add_parser("new"); y.add_argument("--type", required=True); y.add_argument("--title", required=True)
    y.add_argument("--rule"); y.add_argument("--issues", help="쉼표구분 issue_id(생략=그 유형의 미배정 전부)")
    y.set_defaults(fn=cmd_batch_new)
    y = bsp.add_parser("add-targets"); y.add_argument("batch_id", type=int)
    y.add_argument("--rcept-file", required=True); y.set_defaults(fn=cmd_batch_add)
    y = bsp.add_parser("reload"); y.add_argument("batch_id", type=int); y.add_argument("--limit", type=int)
    y.set_defaults(fn=cmd_batch_reload)
    y = bsp.add_parser("mark-fixed"); y.add_argument("batch_id", type=int); y.set_defaults(fn=cmd_batch_mark_fixed)
    y = bsp.add_parser("set"); y.add_argument("batch_id", type=int)
    y.add_argument("--status", choices=["open", "waiting_decision", "reloading", "done", "abandoned"])
    y.add_argument("--rule"); y.add_argument("--note"); y.set_defaults(fn=cmd_batch_set)

    x = sp.add_parser("ask", help="수정: 사용자 판단 요청(텔레그램 버튼)")
    x.add_argument("--category", required=True); x.add_argument("--question", required=True)
    x.add_argument("--option", action="append", required=True, help="KEY:라벨:결과 (2~4회)")
    x.add_argument("--recommend", required=True); x.add_argument("--key", help="중복 억제 키")
    x.add_argument("--batch", type=int); x.add_argument("--issue", type=int)
    x.add_argument("--expires-hours", type=int, default=24)
    x.add_argument("--no-default", action="store_true", help="만료 시 권장안 자동 적용 안 함")
    x.set_defaults(fn=cmd_ask)
    x = sp.add_parser("decision"); x.add_argument("action", choices=["list", "wait", "answer", "cancel"])
    x.add_argument("id", type=int, nargs="?"); x.add_argument("key", nargs="?")
    x.add_argument("--text"); x.add_argument("--timeout", type=int, default=540)
    x.set_defaults(fn=cmd_decision)

    x = sp.add_parser("runner"); x.add_argument("action", choices=["start", "finish", "budget"])
    x.add_argument("--slot"); x.add_argument("--model"); x.add_argument("--run-id", type=int)
    x.add_argument("--log"); x.add_argument("--exit-code", type=int)
    x.set_defaults(fn=cmd_runner)

    x = sp.add_parser("admin")
    x.add_argument("action", choices=["apply-schema", "init", "import-queue", "expire",
                                      "send-unsent", "audit-sample"])
    x.add_argument("--era", default="2015+"); x.add_argument("--apply", action="store_true")
    x.add_argument("--pct", type=float, default=2.0)
    x.set_defaults(fn=cmd_admin)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except VqError as exc:
        print(f"거부: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
