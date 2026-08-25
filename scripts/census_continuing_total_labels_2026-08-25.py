"""Census: what label texts does the corpus use for the COMPANY-WIDE (non-attributed,
section_path IS NULL) continuing-ops / discontinued-ops TOTAL net-income line on the
IS statement? Needed to build §B's new net_income anchor (sum of continuing-total +
discontinued-total) with adequate synonym coverage before implementing.
"""
import sys
sys.path.insert(0, "/Users/taejin/Project/tj_finance")
from sqlalchemy import text
from collector.db import SessionLocal

s = SessionLocal()

print("=== '계속' labels (section_path IS NULL, IS statement) ===")
rows = s.execute(text("""
    SELECT label_raw, COUNT(*) AS n
    FROM report_lines
    WHERE statement = 'IS' AND section_path IS NULL
      AND label_raw LIKE '%계속%'
      AND label_raw NOT LIKE '%주당%'
      AND label_raw NOT LIKE '%법인세%'
    GROUP BY label_raw
    ORDER BY n DESC
    LIMIT 60
""")).fetchall()
for r in rows:
    print(f"  n={r.n:>6}  {r.label_raw!r}")

print("\n=== '중단' labels (section_path IS NULL, IS statement) ===")
rows = s.execute(text("""
    SELECT label_raw, COUNT(*) AS n
    FROM report_lines
    WHERE statement = 'IS' AND section_path IS NULL
      AND label_raw LIKE '%중단%'
      AND label_raw NOT LIKE '%주당%'
      AND label_raw NOT LIKE '%법인세%'
    GROUP BY label_raw
    ORDER BY n DESC
    LIMIT 60
""")).fetchall()
for r in rows:
    print(f"  n={r.n:>6}  {r.label_raw!r}")

s.close()
