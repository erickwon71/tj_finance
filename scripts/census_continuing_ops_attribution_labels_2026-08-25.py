"""
Full-corpus census (parallel) — same methodology as
census_r43_comprehensive_income_labels_2026-08-25.py, applied to the sibling gap
found in the '지배/비지배 귀속 중단영업 성분 가드'(account_mapper.py, 2026-08-23 원설,
2026-08-25 '계속영업' 확장).

For every raw XML file containing '계속영업', extract the TR rows whose Hangul-cell
label contains '지배' AND ('중단' or '계속영업') AND ('지분' or '소유주' or '귀속'),
then test current account_mapper.map() output on that label. Purpose:
1. Census how widespread the '계속영업' component mislabeling is (was previously
   unguarded until the 2026-08-25 fix).
2. Over-blocking check: confirm no legitimate headline-total label gets caught by
   the widened guard (i.e. no label combining '계속영업' + attribution wording that
   is NOT a partial component but the actual combined-total NI attribution line).

Background: memory
`gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25`
(부수발견 항목, DRB동일 00118266).
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
        return ("ERROR", str(p), None)
    if root is None:
        return ("ERROR", str(p), None)

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
        if not (("중단" in norm) or ("계속영업" in norm)):
            continue
        if not (("지분" in norm) or ("소유주" in norm) or ("귀속" in norm)):
            continue
        current = _mapper.map(label, fs_section="is")
        out.append((str(p), label, norm, current.account_code, round(current.confidence, 3),
                    nums[0]))
    return ("OK", str(p), out)


def main():
    hit_list_path = sys.argv[1] if len(sys.argv) > 1 else (
        "/private/tmp/claude-501/-Users-taejin-Project-tj-finance/"
        "5a349739-d1e2-49e1-be64-a2dda2124e63/scratchpad/hit_files_continuing_ops.txt"
    )
    with open(hit_list_path, encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip()]

    print(f"scanning {len(paths)} candidate files with 9 workers...", flush=True)

    rows_out = []
    errors = 0
    n_done = 0

    with Pool(processes=9, initializer=_worker_init) as pool:
        for status, p, out in pool.imap_unordered(_process_file, paths, chunksize=50):
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
        "5a349739-d1e2-49e1-be64-a2dda2124e63/scratchpad/census_continuing_ops_hits.csv"
    )
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "label", "normalized", "current_canon", "confidence", "displayed_value"])
        w.writerows(rows_out)
    print(f"wrote {out_csv}", flush=True)


if __name__ == "__main__":
    main()
