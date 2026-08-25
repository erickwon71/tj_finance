"""
Full-corpus census (parallel) — same logic as census_analyze.py but using
multiprocessing.Pool to parallelize XML parsing across cores (single-process
run projected ~2h for 30,449 files; this should cut it to ~15-20min on 10 cores).

For every raw XML file containing '포괄이익'/'포괄손실' label text, extract the TR
rows whose Hangul-cell label contains '지배' AND ('포괄이익' or '포괄손실') but NOT
'포괄손익' (already guarded by existing rule), then test current account_mapper.map()
output on that label. Purpose: census how widespread the false-positive mapping is,
and check for any legitimate case where blocking would remove the ONLY candidate
(over-blocking risk check) before deciding on a fix.
"""
import sys, re, csv
from pathlib import Path
from multiprocessing import Pool

sys.path.insert(0, "/Users/taejin/Project/tj_finance")

HANGUL_RE = re.compile(r"[가-힣]")

_mapper = None


def _worker_init():
    global _mapper
    from parser.common.account_mapper import get_mapper
    _mapper = get_mapper()


def _process_file(rel: str):
    from fin2.audit.face_audit import _parse_xml_file, parse_displayed
    from parser.xml.table_extractor import _get_cells
    from parser.common.amount_normalizer import normalize_account_name

    p = Path(rel)
    if not p.is_absolute():
        p = Path("/Volumes/dart_data/raw_report") / rel.lstrip("./")
    try:
        root = _parse_xml_file(p)
    except Exception:
        return ("ERROR", str(p), None, None, None, None)
    if root is None:
        return ("ERROR", str(p), None, None, None, None)

    out = []
    for tr in root.findall(".//TR"):
        cells = _get_cells(tr)
        label = None
        nums = []
        for cell in cells:
            if label is None and HANGUL_RE.search(cell):
                label = cell.strip()
                continue
            if label is None:
                continue
            v = parse_displayed(cell)
            if v is not None:
                nums.append(v)
        if not label or not nums:
            continue  # mirrors read_report_face_text._read_table's real gate
        norm = normalize_account_name(label)
        if "지배" not in norm:
            continue
        if not (("포괄이익" in norm) or ("포괄손실" in norm)):
            continue
        if "포괄손익" in norm:
            continue
        current = _mapper.map(label, fs_section="is")
        out.append((str(p), label, norm, current.account_code, round(current.confidence, 3),
                    nums[0]))
    return ("OK", str(p), out, None, None, None)


def main():
    hit_list_path = sys.argv[1] if len(sys.argv) > 1 else (
        "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
        "fd734577-8972-436b-a663-f8ebd690a8a2/scratchpad/hit_files_pogwal.txt"
    )
    with open(hit_list_path, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    print(f"scanning {len(paths)} candidate files with 9 workers...", flush=True)

    rows_out = []
    errors = 0
    n_done = 0

    with Pool(processes=9, initializer=_worker_init) as pool:
        for status, p, out, *_ in pool.imap_unordered(_process_file, paths, chunksize=50):
            n_done += 1
            if status == "ERROR":
                errors += 1
            else:
                rows_out.extend(out)
            if n_done % 2000 == 0:
                print(f"  ...{n_done}/{len(paths)} files, {len(rows_out)} hits so far, "
                      f"{errors} parse errors", flush=True)

    print(f"done. files={len(paths)} errors={errors} hits={len(rows_out)}", flush=True)

    out_csv = (
        "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
        "fd734577-8972-436b-a663-f8ebd690a8a2/scratchpad/census_pogwal_hits_v2.csv"
    )
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "label", "normalized", "current_canon", "confidence", "displayed_value"])
        w.writerows(rows_out)
    print(f"wrote {out_csv}", flush=True)


if __name__ == "__main__":
    main()
