"""R232 backfill — layer-3 sign corrections for CF outflow sections, from the stored printed rows.

The rule (`fin2/extract/cf_outflow_sign.py`) runs at load time inside the extractor's rules-on
pass. For filings already loaded this script runs the same function on the printed CF rows of
`report_lines` and writes the same `layer3_cell_corrections` rows, without re-extracting:

- scope = filings of fiscal year 2015+ (R0-2 retro scope; pre-2015 goes with the R0-2 reload);
- input = printed values (layer 2), the rule runs before R18 in the extractor too;
- cells another rule already corrected (R18 …) keep that row; the section is skipped when that
  value is not the one R232 gives (the extractor's later step would win there);
- cells whose natural key is not unique in the filing count as frozen at their printed value
  (`store_layer3_corrections` cannot link them either).

`fix-r18` removes the R18 rows that turned a printed negative dividend payment positive — the
R18 guard added with R232 no longer produces them.

Usage (cwd = repo root, DATABASE_URL set):
  python scripts/r232_cf_outflow_backfill.py rcepts <out.txt>            # filings in scope
  python scripts/r232_cf_outflow_backfill.py fix-r18 [--apply]
  python scripts/r232_cf_outflow_backfill.py run <rcepts.txt> <out.jsonl> [--apply]
Without --apply nothing is written (counts only). Resumable: rcepts in <out.jsonl> are skipped.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.getcwd())

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract.cf_outflow_sign import RULE, repair_cf_outflow_section_signs  # noqa: E402

_KEY = ("statement", "basis", "table_seq", "row_order", "col_index", "is_cumulative", "period_kind")
_BATCH = 500


class _Row:
    __slots__ = ("id", "statement", "basis", "table_seq", "row_order", "col_index", "is_cumulative",
                 "period_kind", "section_path", "label_raw", "col_label", "value_won", "header_hint",
                 "unit_source")

    def __init__(self, m):
        for k in self.__slots__:
            setattr(self, k, m[k])


def _rcepts(out_path: str) -> None:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT rcept_no FROM report_lines
            WHERE statement = 'CF' AND section_path ~ '현\\s*금\\s*유\\s*출'
              AND report_fiscal_year >= 2015 ORDER BY 1""")).fetchall()
    with open(out_path, "w") as f:
        f.writelines(r[0] + "\n" for r in rows)
    print(f"{len(rows):,} filings -> {out_path}")


def _corrections_for(rows: list[_Row], corrected: dict[int, int]) -> list[dict]:
    keys = Counter(tuple(getattr(r, k) for k in _KEY) + ((r.label_raw or ""),) for r in rows)
    frozen = {}
    for r in rows:
        if r.id in corrected:
            frozen[id(r)] = corrected[r.id]
        elif keys[tuple(getattr(r, k) for k in _KEY) + ((r.label_raw or ""),)] != 1:
            frozen[id(r)] = r.value_won
    printed = {id(r): r.value_won for r in rows}
    if not repair_cf_outflow_section_signs(rows, frozen=frozen):
        return []
    return [{"report_line_id": r.id, "rule": RULE, "printed_value": printed[id(r)],
             "corrected_value": r.value_won, **{k: getattr(r, k) for k in _KEY},
             "label_raw": r.label_raw, "col_label": r.col_label}
            for r in rows if r.value_won != printed[id(r)]]


def _fix_r18(apply: bool) -> None:
    with get_session() as s:
        rows = s.execute(text("""
            SELECT id, rcept_no, label_raw, printed_value, corrected_value FROM layer3_cell_corrections
            WHERE rule = 'R18_dividends_overlay' AND printed_value < 0 AND corrected_value > 0
            ORDER BY rcept_no""")).fetchall()
        for r in rows:
            print(*r, sep="\t")
        if apply and rows:
            s.execute(text("DELETE FROM layer3_cell_corrections WHERE id = ANY(:i)"),
                      {"i": [r[0] for r in rows]})
    print(f"{len(rows)} R18 rows {'deleted' if apply else '(dry run)'}")


def _run(rcepts_path: str, out_path: str, apply: bool) -> None:
    done = set()
    if os.path.exists(out_path):
        done = {json.loads(l)["rcept"] for l in open(out_path)}
    todo = [l.strip() for l in open(rcepts_path) if l.strip() and l.strip() not in done]
    print(f"todo {len(todo):,} (done {len(done):,}) apply={apply}")
    tot = Counter()
    with open(out_path, "a") as out:
        for i in range(0, len(todo), _BATCH):
            batch = todo[i:i + _BATCH]
            with get_session() as s:
                res = s.execute(text("""
                    SELECT id, rcept_no, statement, basis, table_seq, row_order, col_index,
                           is_cumulative, period_kind, section_path, label_raw, col_label,
                           value_won, header_hint, unit_source
                    FROM report_lines WHERE rcept_no = ANY(:r) AND statement = 'CF'"""),
                    {"r": batch}).mappings().all()
                corrected = {r[0]: r[1] for r in s.execute(text("""
                    SELECT report_line_id, corrected_value FROM layer3_cell_corrections
                    WHERE rcept_no = ANY(:r) AND report_line_id IS NOT NULL
                      AND rule NOT LIKE 'R232%'"""), {"r": batch})}
                by_rcept: dict[str, list[_Row]] = {}
                for m in res:
                    by_rcept.setdefault(m["rcept_no"], []).append(_Row(m))
                lines_out = []
                for rc in batch:
                    rows = by_rcept.get(rc, [])
                    rows.sort(key=lambda r: (r.basis or "", r.table_seq or 0, r.row_order or 0))
                    corr = _corrections_for(rows, corrected)
                    c = Counter(x["rule"] for x in corr)
                    tot.update(c)
                    if apply:
                        s.execute(text("""DELETE FROM layer3_cell_corrections
                                          WHERE rcept_no = :r AND rule LIKE 'R232%'"""), {"r": rc})
                        if corr:
                            s.execute(text(f"""
                                INSERT INTO layer3_cell_corrections
                                    (report_line_id, rcept_no, {', '.join(_KEY)}, label_raw, col_label,
                                     printed_value, corrected_value, kind, rule, created_at)
                                VALUES (:report_line_id, :rcept_no, {', '.join(':' + k for k in _KEY)},
                                        :label_raw, :col_label, :printed_value, :corrected_value,
                                        'value', :rule, now())"""),
                                [{**x, "rcept_no": rc} for x in corr])
                    lines_out.append(json.dumps({"rcept": rc, "n": dict(c),
                                                 "dividend_cells": sum(1 for x in corr
                                                                       if "배당" in (x["label_raw"] or ""))},
                                                ensure_ascii=False))
                if apply:
                    s.commit()
            out.write("\n".join(lines_out) + "\n")
            out.flush()
            print(f"{min(i + _BATCH, len(todo)):,}/{len(todo):,} {dict(tot)}", flush=True)


def main():
    from loguru import logger
    logger.remove()
    if sys.argv[1] == "rcepts":
        _rcepts(sys.argv[2])
    elif sys.argv[1] == "fix-r18":
        _fix_r18("--apply" in sys.argv)
    elif sys.argv[1] == "run":
        _run(sys.argv[2], sys.argv[3], "--apply" in sys.argv)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
