"""
'계속영업' 귀속 가드 확장 — OLD-code rebuild vs NEW-code rebuild 격리 diff.

배경: 첫 드라이런(continuing_ops_guard_backfill_diff_2026-08-25.py)이 "DB 커밋값 vs
NEW코드 리빌드값"을 비교했더니, 00204262(한컴) H1-2014 콘솔row 처럼 **내 수정과
무관하게 이미 존재하던 stale drift**(구코드로 리빌드해도 DB 커밋값과 달라짐 — 원문
대조 결과 두 귀속 블록의 값 자체가 서로 뒤바뀐 원문 결함, 내 '계속영업' 가드와는
무관)까지 섞여 들어왔다. 이 스크립트는 **OLD코드 리빌드 스냅샷 vs NEW코드 리빌드
스냅샷**을 직접 비교해 내 수정이 실제로 유발하는 변화만 격리한다(DB 커밋값은 아예
비교 기준에서 뺀다).

사용법:
  1) git checkout -- parser/common/account_mapper.py (구코드 상태로)
     python continuing_ops_isolated_diff_2026-08-25.py snapshot_old <corps.txt>
  2) 내 패치 재적용(git apply my_continuing_ops_fix.patch)
     python continuing_ops_isolated_diff_2026-08-25.py snapshot_new <corps.txt>
  3) python continuing_ops_isolated_diff_2026-08-25.py diff

각 snapshot 단계도 rollback 하므로 프로덕션은 전혀 안 건드림.
"""
import sys, json
from pathlib import Path

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

from sqlalchemy import text
from collector.db import SessionLocal
from fin2.layer3.build import build_corp

FIELDS = ["controlling_ni", "net_income"]
OUT_DIR = Path("/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
                "5a349739-d1e2-49e1-be64-a2dda2124e63/scratchpad")


def snapshot(session, corps):
    rows = session.execute(text(f"""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type,
               {', '.join(FIELDS)}
        FROM std_financials_v3
        WHERE corp_code = ANY(:corps)
    """), {"corps": corps}).fetchall()
    out = {}
    for r in rows:
        key = "|".join(str(x) for x in (r.corp_code, r.fiscal_year, r.fiscal_period, r.statement_type))
        out[key] = [getattr(r, f) for f in FIELDS]
    return out


def do_snapshot(tag, corp_file):
    corps = [l.strip() for l in open(corp_file, encoding="utf-8") if l.strip()]
    print(f"[{tag}] rebuilding {len(corps)} corps (rollback at end)...")
    session = SessionLocal()
    try:
        errors = []
        for i, corp in enumerate(corps, 1):
            try:
                build_corp(session, corp, year_min=2010)
            except Exception as e:  # noqa: BLE001
                errors.append((corp, f"{type(e).__name__}: {e}"))
            if i % 100 == 0:
                print(f"  ...{i}/{len(corps)}")
        session.flush()
        snap = snapshot(session, corps)
        print(f"[{tag}] snapshot rows: {len(snap)}, errors: {len(errors)}")
        if errors:
            for c, m in errors[:20]:
                print(f"    ERROR {c}: {m}")
        with open(OUT_DIR / f"continuing_ops_snapshot_{tag}.json", "w", encoding="utf-8") as f:
            json.dump(snap, f)
        print(f"wrote continuing_ops_snapshot_{tag}.json")
    finally:
        session.rollback()
        session.close()


def do_diff():
    old = json.load(open(OUT_DIR / "continuing_ops_snapshot_old.json", encoding="utf-8"))
    new = json.load(open(OUT_DIR / "continuing_ops_snapshot_new.json", encoding="utf-8"))
    all_keys = set(old) | set(new)
    changed = []
    for key in sorted(all_keys):
        b = old.get(key)
        a = new.get(key)
        if b != a:
            changed.append((key, b, a))
    print(f"=== ISOLATED DIFF (old-code rebuild vs new-code rebuild): {len(changed)} rows ===")
    by_corp = {}
    for key, b, a in changed:
        corp = key.split("|")[0]
        by_corp.setdefault(corp, 0)
        by_corp[corp] += 1
    for key, b, a in changed[:100]:
        print(f"  {key}: old={b} new={a}")
    print(f"\ndistinct corps affected: {len(by_corp)}")
    for corp, cnt in sorted(by_corp.items(), key=lambda x: -x[1]):
        print(f"  {corp}: {cnt}")
    with open(OUT_DIR / "continuing_ops_isolated_diff.csv", "w", encoding="utf-8") as f:
        f.write("corp_code,fiscal_year,fiscal_period,statement_type,old_controlling_ni,old_net_income,new_controlling_ni,new_net_income\n")
        for key, b, a in changed:
            b = b or [None, None]
            a = a or [None, None]
            f.write(",".join(str(x) for x in (*key.split("|"), *b, *a)) + "\n")
    print("wrote continuing_ops_isolated_diff.csv")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode in ("snapshot_old", "snapshot_new"):
        tag = mode.split("_")[1]
        corp_file = sys.argv[2]
        do_snapshot(tag, corp_file)
    elif mode == "diff":
        do_diff()
    else:
        print("usage: snapshot_old <corps.txt> | snapshot_new <corps.txt> | diff")
