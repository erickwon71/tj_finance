"""Feasibility: compare SCE opening-balance cells with the prior annual report (by date)."""
import json, os, re, sys, datetime, collections
import psycopg2
out = open(sys.argv[1], "w")
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()
DATE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
# 1) prior annual filing per (corp, period_end_date): latest rcept (amendments included)
cur.execute("""select corp_code, period_end_date, max(rcept_no) from filings
               where report_type='annual' and period_end_date is not null group by 1,2""")
annual = {(c, d): r for c, d, r in cur.fetchall()}
print("annual filings", len(annual), flush=True)
# 2) SCE opening cells
cur.execute(r"""select l.rcept_no, f.corp_code, l.basis, l.table_seq, l.row_order, l.col_index,
                       l.col_label, l.label_raw, l.value_won
                from report_lines l join filings f using (rcept_no)
                where l.statement='SCE' and l.value_won is not null and l.value_won <> 0
                  and l.label_raw ~ '기\s*초' and l.label_raw ~ '\d{4}'""")
rows = cur.fetchall()
print("opening cells", len(rows), flush=True)
need = collections.defaultdict(list)
for rc, corp, b, s, ro, ci, cl, lab, v in rows:
    m = DATE.search(lab)
    if not m:
        continue
    try:
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        continue
    prev = d - datetime.timedelta(days=1)
    pr = annual.get((corp, prev))
    need[pr].append((rc, b, s, ro, ci, cl, lab, v, str(prev)))
print("distinct prior filings", len(need), flush=True)
stat = collections.Counter()
for pr, cells in need.items():
    if pr is None:
        stat["no prior annual"] += len(cells)
        for c in cells:
            out.write(json.dumps({"k": "noprior", "cell": c}, ensure_ascii=False, default=str) + "\n")
        continue
    cur.execute("""select statement, basis, label_raw, value_won from report_lines
                   where rcept_no=%s and value_won is not null and value_won<>0
                     and ((statement='BS' and col_index=0) or (statement='SCE'))""", (pr,))
    pv = collections.defaultdict(set)
    for st, b, lab, v in cur.fetchall():
        if st == "SCE" and not re.search(r"기\s*말", lab or ""):
            continue
        pv[(b, abs(v))].add(v > 0)
    for c in cells:
        rc, b, s, ro, ci, cl, lab, v, prev = c
        signs = pv.get((b, abs(v)))
        if not signs:
            k = "no magnitude match in prior"
        elif len(signs) == 2:
            k = "prior has both signs"
        elif (v > 0) in signs:
            k = "sign agrees"
        else:
            k = "SIGN DISAGREES"
        stat[k] += 1
        if k in ("SIGN DISAGREES", "no magnitude match in prior", "prior has both signs"):
            out.write(json.dumps({"k": k, "prior": pr, "cell": c}, ensure_ascii=False, default=str) + "\n")
print(dict(stat), flush=True)
