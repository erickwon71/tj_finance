"""Of the tables we skip as 'merged column', how many are actually RECOVERABLE? (READ-ONLY)

We currently skip every table where a cell holds several values (PARSING_RULES.md 부록 C).
That is right for 일양약품 20260318000595, whose <TD> holds 44 years with **no separator of any
kind** — BeautifulSoup, lxml and lxml-xml all return one row there, because the row boundary
simply is not in the document.

But 'merged' is not one thing. A cell may instead separate its values with <BR/>, with child
<P> elements, or with newline characters — and those ARE recoverable. The stored grid cannot
tell us which, because expand_table_grid already flattened the cell to text. So this reopens
the SOURCE XML and classifies each offending cell:

    child_tags   : <P>/<BR>/... inside the TD          -> recoverable
    newline      : '\\n' inside the text                -> recoverable
    multi_text    : several sibling text nodes          -> probably recoverable
    none         : one flat string, no boundary at all  -> NOT recoverable (일양약품 형)

  python scripts/probe_merged_recoverable.py --limit 400 --workers 6
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import _load_root, _tag, _text, merged_cell_reason

DART = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def classify_cell(td) -> str:
    kids = [k for k in td if isinstance(_tag(k), str) and _tag(k)]
    if kids:
        return f"child_tags({','.join(sorted({_tag(k) for k in kids}))})"
    raw = "".join(td.itertext())
    if "\n" in raw.strip():
        return "newline"
    texts = [t for t in td.itertext() if t and t.strip()]
    if len(texts) > 1:
        return "multi_text"
    return "none"


def work(job: tuple[str, str]) -> list[tuple[str, str, str]]:
    """→ [(kind, rcept, sample)] for each merged cell found in the source XML."""
    rcept, path = job
    p = Path(path)
    if not p.exists():
        return []
    try:
        root = _load_root(p)
    except Exception:                                              # noqa: BLE001
        return []
    if root is None:
        return []
    out = []
    for el in root.iter():
        if _tag(el) not in ("TD", "TH", "TE", "TU"):
            continue
        txt = _text(el)
        if len(txt) < 40 or not merged_cell_reason(txt):
            continue
        out.append((classify_cell(el), rcept, txt[:50]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    with get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT t.rcept_no, d.file_path
            FROM biz_section_tables t
            JOIN download_tasks d ON d.rcept_no = t.rcept_no
                                 AND d.file_type='xml' AND d.file_path IS NOT NULL
            JOIN biz_metrics b ON b.rcept_no = t.rcept_no AND b.table_ord = t.table_ord
            WHERE abs(b.value) > 1e15
            LIMIT :l
        """), {"l": args.limit}).fetchall()
    jobs = [(r.rcept_no, r.file_path) for r in rows]
    print(f"보고서 {len(jobs)}건 · 워커 {args.workers} — 원문 재확인 중…", flush=True)

    with Pool(args.workers) as pool:
        chunks = pool.map(work, jobs)

    kinds: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    for c in chunks:
        for kind, rcept, sample in c:
            kinds[kind] += 1
            if len(samples[kind]) < 3:
                samples[kind].append((rcept, sample))

    total = sum(kinds.values())
    print(f"\n병합 셀 {total:,}개의 구분자 유무\n")
    for kind, n in kinds.most_common():
        verdict = "복원 불가" if kind == "none" else "복원 가능"
        print(f"  {kind:<28} {n:>6,} ({n/max(total,1)*100:>5.1f}%)  {verdict}")
        for rcept, s in samples[kind][:2]:
            print(f"       {DART}{rcept}  {s[:44]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
