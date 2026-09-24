"""Parser-independent audit: compare DB report_lines of one filing with the raw XML tables.

For each DB (statement, basis, table_seq) group, find the source table window whose row labels
best align (difflib) with the DB label sequence, then:
  - missing:    source rows with a non-zero current-period amount not matched by any DB row
  - prior_only: source rows whose current-period cell is blank/dash (DB keeps current only)
  - extra:      DB rows whose label is not matched in the window
  - value:      DB value_won != source cell[col_index] * scale  (scale chosen per group;
                per-share rows always in won)
  - uncovered:  SCE only, non-zero source cells in matched rows with no DB cell
Independent of the production parser on purpose (audit of verifier verdicts, design §9-2).
Known false positives: amounts glued to '&cr;' inside a cell, labels split across cells.
Usage: .venv/bin/python scripts/verification_audit_compare.py <rcept_no> <xml_path>
"""
import difflib
import re
import sys
from collections import Counter

import psycopg2
from lxml import etree

CELL_TAGS = {"td", "th", "te", "tu"}
NOTE_RE = re.compile(r"^\d{1,2}(\s*[,.]\s*\d{1,2})*$")
NUM_RE = re.compile(r"^[\(△\-−]?\s*[\d,]+(\.\d+)?\s*\)?$")


def norm_label(s: str) -> str:
    s = (s or "").replace("&cr;", "")
    s = re.sub(r"[\s　\xa0]", "", s or "")
    s = re.sub(r"^(\(?[0-9IVXⅠ-Ⅹ가-하]{1,3}[\.\)])+", "", s)
    s = re.sub(r"\(주석[^)]*\)|\(주[\d,\s]*\)", "", s)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s)


def parse_amount(t: str):
    t = re.sub(r"[\s　\xa0]", "", t or "")
    if t in ("", "　"):
        return "EMPTY"
    if t in ("-", "−", "–", "0"):
        return 0
    if not NUM_RE.match(t):
        return None
    neg = t.startswith(("(", "△", "-", "−"))
    digits = re.sub(r"[^\d.]", "", t)
    try:
        v = float(digits)
    except ValueError:
        return None
    return -v if neg else v


def load_source(path):
    raw = open(path, "rb").read()
    try:
        txt = raw.decode("utf-8")
    except UnicodeDecodeError:
        txt = raw.decode("cp949", "replace")
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt, count=1)
    root = etree.fromstring(txt.encode("utf-8"), etree.HTMLParser(recover=True, encoding="utf-8"))
    rows = []  # (table_id, label, cells)
    for ti, table in enumerate(root.iter("table")):
        trs = []
        for tr in table.iter("tr"):
            texts = ["".join(c.itertext()).strip() for c in tr if isinstance(c.tag, str) and c.tag.lower() in CELL_TAGS]
            if texts:
                trs.append(texts)
        note_idx = None
        for texts in trs[:4]:
            for k, t in enumerate(texts):
                if re.sub(r"[\s\u3000]", "", t) in ("주석", "주석번호", "주"):
                    note_idx = k
        for texts in trs:
            kept = [c for k, c in enumerate(texts) if k != note_idx]
            label, cells = kept[0], kept[1:]
            # two-level label: parent | child | amounts... -> "parent>child"
            if len(cells) > 1 and parse_amount(cells[0]) is None and re.search(r"[가-힣A-Za-z]", cells[0]):
                label, cells = label + ">" + cells[0], cells[1:]
            rows.append((ti, norm_label(label), label, [parse_amount(c) for c in cells]))
    return rows


def main(rcept, path):
    conn = psycopg2.connect(dbname="tj_finance")
    cur = conn.cursor()
    cur.execute("""SELECT statement, basis, table_seq, row_order, label_raw, col_index, value_won
                   FROM report_lines WHERE rcept_no=%s ORDER BY statement, basis, table_seq, row_order, col_index""", (rcept,))
    db = cur.fetchall()
    src = load_source(path)
    src_labels = [r[1] for r in src]
    groups = {}
    for st, ba, ts, ro, lab, ci, v in db:
        groups.setdefault((st, ba, ts), []).append((ro, lab, ci, v))
    total = Counter()
    for key, items in groups.items():
        # distinct rows in order
        seen, seq = set(), []
        for ro, lab, ci, v in items:
            if (ro, lab) not in seen:
                seen.add((ro, lab)); seq.append((ro, lab))
        dlabels = [norm_label(l) for _, l in seq]
        # best table by label overlap
        dset = Counter(dlabels)
        tscore = Counter()
        for ti, nl, _, _ in src:
            if nl in dset:
                tscore[ti] += 1
        if not tscore:
            print(f"  {key}: NO SOURCE TABLE MATCH ({len(seq)} rows)"); total["nomatch"] += len(seq); continue
        top = tscore.most_common(1)[0][1]
        dvals = Counter(abs(v) for _, _, _, v in items if v)
        def vhits(t):
            n = 0
            for ti, _, _, cells in src:
                if ti == t:
                    for x in cells:
                        if isinstance(x, float) and x:
                            for sc in (1, 1000, 1_000_000):
                                if dvals.get(int(round(abs(x) * sc))):
                                    n += 1; break
            return n
        best = max((t for t, sc_ in tscore.items() if sc_ >= 0.8 * top), key=lambda t: (vhits(t), tscore[t]))
        # window: best table plus adjacent tables that also score
        tids = sorted(t for t, s in tscore.items() if abs(t - best) <= 3 and s >= 2)
        tids = [t for t in tids if t >= best - 1] or [best]
        win = [(i, r) for i, r in enumerate(src) if r[0] in tids]
        wl = [r[1] for _, r in win]
        sm = difflib.SequenceMatcher(None, dlabels, wl, autojunk=False)
        d2s = {}
        for a, b, n in sm.get_matching_blocks():
            for k in range(n):
                d2s[a + k] = b + k
        # re-pair rows that only differ in order (e.g. row_order NULL)
        free = {}
        for j in range(len(win)):
            if j not in set(d2s.values()):
                free.setdefault(wl[j], []).append(j)
        for i in range(len(seq)):
            if i not in d2s and free.get(dlabels[i]):
                d2s[i] = free[dlabels[i]].pop(0)
        matched_s = set(d2s.values())
        lo, hi = (min(matched_s), max(matched_s)) if matched_s else (0, -1)
        missing = [win[j][1] for j in range(lo, hi + 1) if j not in matched_s
                   and win[j][1][1] and any(isinstance(x, float) and x != 0 for x in win[j][1][3])]
        prior_only = [m for m in missing if not (isinstance(m[3][0], float) and m[3][0] != 0)] if key[0] != "SCE" else []
        missing = [m for m in missing if m not in prior_only]
        total["prior_only"] += len(prior_only)
        extra = [seq[i] for i in range(len(seq)) if i not in d2s]
        # scale
        rowmap = {seq[i]: win[j][1] for i, j in d2s.items()}
        cand = Counter()
        for ro, lab, ci, v in items:
            r = rowmap.get((ro, lab))
            if r and v not in (None, 0) and ci is not None and ci < len(r[3]) and isinstance(r[3][ci], float) and r[3][ci]:
                for sc in (1, 1000, 1_000_000):
                    if abs(r[3][ci] * sc - v) < 1:
                        cand[sc] += 1
        scale = cand.most_common(1)[0][0] if cand else 1
        bad = []
        nchk = 0
        for ro, lab, ci, v in items:
            r = rowmap.get((ro, lab))
            if not r or v is None:
                continue
            cells = r[3]
            nchk += 1
            exp = cells[ci] if ci is not None and ci < len(cells) else "OOR"
            sc_ = 1 if '주당' in lab else scale
            ok = isinstance(exp, float) and abs(exp * sc_ - v) < 1
            if not ok and exp in (0, "EMPTY") and v == 0:
                ok = True
            if not ok:
                # tolerate shifted empty note column: try ci+1
                alt = cells[ci + 1] if ci is not None and ci + 1 < len(cells) else None
                if isinstance(alt, float) and abs(alt * sc_ - v) < 1:
                    ok = True
            if not ok:
                where = [k for k, x in enumerate(cells) if isinstance(x, float) and abs(x * scale - v) < 1]
                flipped = [k for k, x in enumerate(cells) if isinstance(x, float) and x and abs(-x * scale - v) < 1]
                bad.append((ro, lab, ci, v, exp, where, flipped, r[2]))
        uncovered = []
        if key[0] == "SCE":
            have = {}
            for ro, lab, ci, v in items:
                have.setdefault((ro, lab), set()).add(ci)
            for rk, r in rowmap.items():
                for k, x in enumerate(r[3]):
                    if isinstance(x, float) and x != 0 and k not in have.get(rk, set()):
                        uncovered.append((r[2], k, x))
        total["uncovered"] += len(uncovered)
        for u in uncovered[:10]:
            print(f"      UNCOVERED src '{u[0]}' col={u[1]} val={u[2]}")
        total["rows"] += len(seq); total["cells"] += nchk; total["bad"] += len(bad)
        total["missing"] += len(missing); total["extra"] += len(extra)
        flag = "OK" if not (bad or missing or extra) else "CHECK"
        print(f"  {flag} {key}: rows={len(seq)} cells={nchk} scale={scale} tables={tids} bad={len(bad)} missing={len(missing)} extra={len(extra)}")
        for b in bad[:15]:
            print(f"      BAD ro={b[0]} '{b[1]}' ci={b[2]} db={b[3]} src={b[4]} found_at={b[5]} flipped_at={b[6]}")
        for m in missing[:15]:
            print(f"      MISSING src '{m[2]}' cells={m[3][:6]}")
        for e in extra[:15]:
            print(f"      EXTRA db ro={e[0]} '{e[1]}'")
    print(f"TOTAL {rcept}: {dict(total)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
