"""
'계속영업' 귀속 성분 가드 확장(DRB동일 00118266 부수발견 수정) — 436개사 DRY-RUN diff.

동일 방법론: scripts/r43_comprehensive_income_guard_backfill_diff_2026-08-25.py 참고.
프로덕션 std_financials_v3 를 실제로 건드리지 않고(세션을 끝까지 rollback), 실
production 코드 경로(`fin2.layer3.build.build_corp`)를 그대로 호출해 새 코드(이미
적용된 account_mapper.py '계속영업' 가드 확장)로 재계산했을 때
controlling_ni/net_income 값이 실제로 달라지는 회사만 골라낸다.

실행: python continuing_ops_guard_backfill_diff_2026-08-25.py <affected_corps.txt>
"""
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text
from collector.db import SessionLocal
from fin2.layer3.build import build_corp

FIELDS = ["controlling_ni", "net_income"]  # std_financials_v3 has no noncontrolling_ni column


def snapshot(session, corps):
    rows = session.execute(text(f"""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type,
               {', '.join(FIELDS)}
        FROM std_financials_v3
        WHERE corp_code = ANY(:corps)
    """), {"corps": corps}).fetchall()
    out = {}
    for r in rows:
        key = (r.corp_code, r.fiscal_year, r.fiscal_period, r.statement_type)
        out[key] = tuple(getattr(r, f) for f in FIELDS)
    return out


def main():
    corp_file = sys.argv[1] if len(sys.argv) > 1 else (
        "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
        "5a349739-d1e2-49e1-be64-a2dda2124e63/scratchpad/continuing_ops_affected_corps.txt"
    )
    corps = [l.strip() for l in open(corp_file, encoding="utf-8") if l.strip()]
    print(f"dry-run rebuild for {len(corps)} corps (production NOT touched — rollback at end)")

    session = SessionLocal()
    try:
        before = snapshot(session, corps)
        print(f"before snapshot: {len(before)} std_v3 rows")

        n_rows = 0
        errors = []
        for i, corp in enumerate(corps, 1):
            try:
                n_rows += build_corp(session, corp, year_min=2010)
            except Exception as e:  # noqa: BLE001
                errors.append((corp, f"{type(e).__name__}: {e}"))
            if i % 50 == 0:
                print(f"  ...{i}/{len(corps)} corps rebuilt (in-transaction, uncommitted)")
        session.flush()

        after = snapshot(session, corps)
        print(f"after snapshot (uncommitted): {len(after)} std_v3 rows, "
              f"build_corp errors: {len(errors)}")

        # diff
        changed = []
        all_keys = set(before) | set(after)
        for key in all_keys:
            b = before.get(key)
            a = after.get(key)
            if b != a:
                changed.append((key, b, a))

        print(f"\n=== DIFF: {len(changed)} (corp,fy,period,stmt) rows changed ===")
        by_corp = defaultdict(int)
        for key, b, a in changed:
            by_corp[key[0]] += 1

        for key, b, a in sorted(changed)[:80]:
            print(f"  {key}: before={b} after={a}")

        print(f"\ndistinct corps with >=1 changed row: {len(by_corp)}")
        for corp, cnt in sorted(by_corp.items(), key=lambda x: -x[1])[:30]:
            print(f"  {corp}: {cnt} rows changed")

        if errors:
            print(f"\n=== build_corp ERRORS ({len(errors)}) ===")
            for corp, msg in errors[:20]:
                print(f"  {corp}: {msg}")

        out_dir = ("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
                    "5a349739-d1e2-49e1-be64-a2dda2124e63/scratchpad")
        with open(f"{out_dir}/continuing_ops_dryrun_diff.csv", "w", encoding="utf-8") as f:
            f.write("corp_code,fiscal_year,fiscal_period,statement_type,"
                    "before_controlling_ni,before_net_income,"
                    "after_controlling_ni,after_net_income\n")
            for key, b, a in sorted(changed):
                b = b or (None,) * len(FIELDS)
                a = a or (None,) * len(FIELDS)
                f.write(",".join(str(x) for x in (*key, *b, *a)) + "\n")
        print(f"\nwrote {out_dir}/continuing_ops_dryrun_diff.csv")

        with open(f"{out_dir}/continuing_ops_changed_corps.txt", "w", encoding="utf-8") as f:
            for corp in sorted(by_corp):
                f.write(corp + "\n")
        print(f"wrote {out_dir}/continuing_ops_changed_corps.txt ({len(by_corp)} corps)")
    finally:
        session.rollback()
        session.close()
        print("\n[dry-run] session rolled back — production std_financials_v3 unchanged.")


if __name__ == "__main__":
    main()
