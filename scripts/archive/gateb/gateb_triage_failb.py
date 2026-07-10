"""Gate B fail_b 트리아지: 현재 fail_b 행을 ×1000 진짜버그 vs reader false-fail 로 분류.

fail_detail = [{field, canonical, db_won, report_won, reason}].
분류:
  X1000  = db == report×1000 (또는 ÷1000) — 단위 std 버그(노트표 오염 등).
  RATIO_K= |db/report| 가 1000 근처(±2%) — ×1000 류이나 라운딩 차.
  CLOSE  = |db/report-1| < 5% — reader 컬럼/다단표 오독 가능(false-fail 의심).
  OTHER  = 그 외.
usage: python scripts/gateb_triage_failb.py [--fy-min 2015]
"""
import sys
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import text
from collector.db import get_session

fy_min = 2015
if "--fy-min" in sys.argv:
    fy_min = int(sys.argv[sys.argv.index("--fy-min") + 1])


def classify(db, rep):
    if db is None or rep is None or rep == 0:
        return "NO_REPORT"
    r = abs(db / rep)
    if abs(db) == abs(rep) * 1000 or abs(rep) == abs(db) * 1000:
        return "X1000"
    if 980 <= r <= 1020 or 0.00098 <= r <= 0.00102:
        return "RATIO_K"
    if abs(r - 1) < 0.05:
        return "CLOSE"
    return "OTHER"


with get_session() as s:
    rows = s.execute(text("""
        SELECT corp_code, fiscal_year, fiscal_period, statement_type, fail_detail
        FROM face_audit
        WHERE gate_status='fail_b' AND fiscal_year >= :y
        ORDER BY corp_code, fiscal_year
    """), {"y": fy_min}).fetchall()

    names = dict(s.execute(text("SELECT corp_code, corp_name FROM corporations")).fetchall())

cat_count = Counter()
field_cat = defaultdict(Counter)         # field -> category counts
corp_cat = defaultdict(Counter)          # corp -> category counts
corp_rows = Counter()
n_field = 0

for corp, fy, fp, basis, detail in rows:
    corp_rows[corp] += 1
    for fd in (detail or []):
        if fd.get("reason") != "VALUE_DIFF":
            continue
        n_field += 1
        cat = classify(fd.get("db_won"), fd.get("report_won"))
        cat_count[cat] += 1
        field_cat[fd.get("field")][cat] += 1
        corp_cat[corp][cat] += 1

print(f"=== fail_b 트리아지 (fy>={fy_min}) ===")
print(f"fail_b 행: {len(rows)} / 기업 {len(corp_rows)}  | VALUE_DIFF 필드: {n_field}\n")
print("필드 카테고리 분포:")
for cat, n in cat_count.most_common():
    print(f"  {cat:10s} {n}")

print("\n상위 필드별 분포:")
for field, c in sorted(field_cat.items(), key=lambda x: -sum(x[1].values()))[:15]:
    print(f"  {field:22s} {dict(c)}")

print("\n상위 기업(행수):")
for corp, n in corp_rows.most_common(25):
    cc = dict(corp_cat[corp])
    print(f"  {corp} {names.get(corp,'?'):16s} rows={n:3d} {cc}")

# 순수 X1000/RATIO_K 만 있는 기업(진짜버그 후보) vs CLOSE/OTHER 만(false-fail 후보)
pure_k = [c for c, cc in corp_cat.items()
          if cc and all(k in ("X1000", "RATIO_K") for k in cc)]
pure_close = [c for c, cc in corp_cat.items()
              if cc and all(k in ("CLOSE", "OTHER") for k in cc)]
print(f"\n순수 ×1000류 기업(진짜버그 후보): {len(pure_k)}")
print("  " + ", ".join(f"{c}:{names.get(c,'?')}" for c in pure_k[:30]))
print(f"순수 CLOSE/OTHER 기업(false-fail 후보): {len(pure_close)}")
print("  " + ", ".join(f"{c}:{names.get(c,'?')}" for c in pure_close[:30]))
