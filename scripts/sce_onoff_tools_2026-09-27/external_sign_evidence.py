"""Attach external sign evidence (BS/IS same |value| in the filing or same corp's recent filings, economic priors)."""
import json, os, re, sys, collections, ast
import psycopg2
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
judge = {}
for line in open(sys.argv[2]):
    if line.startswith("('ALL'"):
        t = ast.literal_eval(line.rsplit(" ", 1)[0]); judge[(t[1], tuple(t[2]))] = (t[6], t[7], t[8])
DIV = re.compile(r"배당")
NEG_COL = re.compile(r"자기주식")
POS_BAL_COL = re.compile(r"^(자\s*본\s*금|자본잉여금|주식발행초과금)$")
BAL = re.compile(r"(기초|기말|\d{4}\.\d{1,2}\.\d{1,2}|\d{4}년)")
def prior(label, col, row_is_bal):
    c = col.split(">")[-1].strip()
    if DIV.search(label) and "주식배당" not in label and "배당금수익" not in label: return -1, "prior:배당=감소"
    if row_is_bal and POS_BAL_COL.match(c): return 1, "prior:자본금/잉여금 잔액>0"
    if row_is_bal and NEG_COL.search(c): return -1, "prior:자기주식 잔액<0"
    if "자기주식" in label and "취득" in label: return -1, "prior:자기주식취득<0"
    return None, ""
out = []
for l in open(sys.argv[1]):
    r = json.loads(l)
    if not r["diffs"]: continue
    rc = r["rcept"]
    cur.execute("select corp_code, corp_name, fiscal_year, fiscal_period from filings where rcept_no=%s", (rc,))
    corp, nm, fy, fp = cur.fetchone()
    for k, o, n, info in r["diffs"]:
        label, col = (info[0] or ""), (info[1] or "")
        v = abs(n)
        cur.execute("""select rl.rcept_no, rl.statement, rl.label_raw, rl.value_won from report_lines rl join filings f on f.rcept_no = rl.rcept_no
                       where f.corp_code=%s and f.fiscal_year between %s and %s and rl.statement in ('BS','IS','CF')
                       and rl.basis=%s and rl.value_won in (%s, %s) limit 40""", (corp, fy - 2, fy, k[0], v, -v))
        hits = cur.fetchall()
        signs = collections.Counter(1 if h[3] > 0 else -1 for h in hits if h[1] in ("BS", "IS"))
        ext, why = None, ""
        if signs and len(signs) == 1:
            ext = next(iter(signs)); why = "BS/IS:" + ";".join(f"{h[1]}:{h[2][:14]}" for h in hits if h[1] in ("BS","IS"))[:80]
        pr, pwhy = prior(label, col, bool(BAL.search(label)))
        if ext is None and pr is not None: ext, why = pr, pwhy
        elif ext is not None and pr is not None and pr != ext: why += " !conflict " + pwhy
        sn = 1 if n > 0 else -1
        verdict = "NOEVID" if ext is None else ("NEW_OK" if sn == ext else "OLD_OK")
        out.append((rc, nm, fy, fp, tuple(k), label[:22], col.split(">")[-1][:14], o, n, verdict, why, judge.get((rc, tuple(k)))))
per = collections.defaultdict(collections.Counter)
for x in out: per[(x[0], x[1], x[2], x[3])][x[9]] += 1
json.dump([list(map(str, x)) for x in out], open(sys.argv[3], "w"), ensure_ascii=False)
for f, c in sorted(per.items()): print(*f, dict(c))
print("cells", collections.Counter(x[9] for x in out))
