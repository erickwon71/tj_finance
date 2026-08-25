"""
R43(account_mapper.py 포괄손익 가드 확장) 소급 백필 사전조사 — 254개사 DRY-RUN diff.

프로덕션 std_financials_v3 를 실제로 건드리지 않고(세션을 끝까지 rollback), 실
production 코드 경로(`fin2.layer3.build.build_corp`)를 그대로 호출해 새 코드(이미
적용된 account_mapper.py 수정)로 재계산했을 때 controlling_ni/noncontrolling_ni/
net_income 값이 실제로 달라지는 회사만 골라낸다.

방법: SessionLocal()을 직접 열어(get_session()의 자동 commit 우회) build_corp()를
254개사에 대해 같은 트랜잭션 안에서 호출 → delete+insert 는 flush 는 되지만 commit
전이라 DB 상 실제 상태는 그대로. 트랜잭션 안에서 전/후 값을 비교한 뒤 반드시
rollback.

실행: python dryrun_r43_backfill_diff.py <affected_corps.txt>
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
        "fd734577-8972-436b-a663-f8ebd690a8a2/scratchpad/affected_corps.txt"
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

        with open("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
                   "fd734577-8972-436b-a663-f8ebd690a8a2/scratchpad/r43_dryrun_diff.csv", "w",
                   encoding="utf-8") as f:
            f.write("corp_code,fiscal_year,fiscal_period,statement_type,"
                    "before_controlling_ni,before_net_income,"
                    "after_controlling_ni,after_net_income\n")
            for key, b, a in sorted(changed):
                b = b or (None,) * len(FIELDS)
                a = a or (None,) * len(FIELDS)
                f.write(",".join(str(x) for x in (*key, *b, *a)) + "\n")
        print("\nwrote r43_dryrun_diff.csv")
    finally:
        session.rollback()
        session.close()
        print("\n[dry-run] session rolled back — production std_financials_v3 unchanged.")


if __name__ == "__main__":
    main()
