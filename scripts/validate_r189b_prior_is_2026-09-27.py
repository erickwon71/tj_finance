import json, os, collections, psycopg2
S = os.sys.argv[1]
eff = json.load(open(f"{S}/r189b_effect.json"))
cur = psycopg2.connect(os.environ["DATABASE_URL"]).cursor()
c = collections.Counter(); ex = []
for k, (offv, onv, meta) in eff:
    rc, basis = k[0], k[1]
    # same-company reports other than this one: same magnitude in SCE (same basis), same row label family
    cur.execute("""select l.rcept_no, l.label_raw, l.value_won from report_lines l join filings f using (rcept_no)
                   where f.corp_code=(select corp_code from filings where rcept_no=%s) and l.rcept_no<>%s
                     and l.statement='SCE' and l.basis=%s and abs(l.value_won)=%s""", (rc, rc, basis, abs(onv)))
    hits = cur.fetchall()
    if not hits:
        c["no other-report SCE evidence"] += 1; continue
    # earliest report = the one that first printed this period
    first = min(h[0] for h in hits)
    signs = {h[2] > 0 for h in hits if h[0] == first}
    k2 = "earliest other report agrees" if signs == {onv > 0} else ("earliest other report DISAGREES" if signs == {onv <= 0} else "earliest mixed")
    c[k2] += 1
    if "DISAGREES" in k2 and len(ex) < 12: ex.append((rc, meta[0][:16], meta[1].split(">")[-1][:10], onv, first))
print(dict(c))
for e in ex: print(e)
