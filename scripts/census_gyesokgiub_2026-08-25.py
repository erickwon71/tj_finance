import sys
sys.path.insert(0, "/Users/taejin/Project/tj_finance")
from sqlalchemy import text
from collector.db import SessionLocal
s = SessionLocal()
rows = s.execute(text("""
    SELECT label_raw, COUNT(*) AS n FROM report_lines
    WHERE statement='IS' AND section_path IS NULL AND label_raw LIKE '%계속기업%'
    GROUP BY label_raw ORDER BY n DESC LIMIT 20
""")).fetchall()
for r in rows:
    print(f"  n={r.n:>6}  {r.label_raw!r}")
s.close()
