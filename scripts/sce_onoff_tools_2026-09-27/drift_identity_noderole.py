"""drift_identity_full with the roll-forward residual seeing `node_role` (R193 leading headings).

The production `_residual_at` builds cells with `line=None`, so parent rows ('P') are not
recognised as leading subtotals there; for judging R193 the residual must use them.
Same arguments as drift_identity_full.py.
"""
import os, runpy, sys
from types import SimpleNamespace
sys.path.insert(0, os.getcwd())
import fin2.extract.sce_source_defects as sd
from fin2.extract.sce_sign_repair import _Cell, _blocks, _proven_subtotals


def _column_entries(lines, basis, table_seq, col_index, override=None):
    out = []
    for ln in sd._sce(lines):
        if (ln.basis, getattr(ln, "table_seq", None), ln.col_index) != (basis, table_seq, col_index):
            continue
        ro, val = (override or {}).get(id(ln), (ln.row_order, ln.value_won))
        if ro is None:
            continue
        out.append((ro, (ln.label_raw or ""), int(val), getattr(ln, "node_role", None)))
    out.sort(key=lambda e: e[0])
    return out


def _residual_at(entries, row_order):
    cells = [_Cell(line=SimpleNamespace(node_role=e[3]), basis="", label_raw=e[1], col_label=None, value=e[2])
             for e in entries]
    for open_i, move_i, close_i in _blocks(cells):
        if not entries[open_i][0] <= row_order <= entries[close_i][0]:
            continue
        subtotals = set(_proven_subtotals(cells, move_i))
        return cells[open_i].value + sum(cells[m].value for m in move_i if m not in subtotals) - cells[close_i].value
    return None


sd._column_entries, sd._residual_at = _column_entries, _residual_at
_G = {}


def _check(item):
    if not _G:
        sys.argv = [sys.argv[0], os.path.dirname(os.path.abspath(__file__))]
        _G.update(runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "drift_identity_full.py"), run_name="judge"))
    return _G["check"](item)


if __name__ == "__main__":
    import collections, json
    from multiprocessing import Pool
    items = [(r["rcept"], r["diffs"]) for r in map(json.loads, open(sys.argv[2])) if r["diffs"]]
    tot = collections.Counter()
    with Pool(6) as p:
        for c in p.imap_unordered(_check, items):
            tot.update(c)
    for k, v in tot.items():
        print(k, v) if isinstance(k, tuple) else None
    print({k: v for k, v in tot.items() if not isinstance(k, tuple)})
