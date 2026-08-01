"""Chronological item-level merge for '사업의 내용' metric rows.

docs/PARSING_RULES.md R0 / R2.

What it does
------------
Parse every filing of a period with the SAME parser, then walk them oldest-first and let a
later filing override an item it re-files. Items a later filing does NOT carry keep their
earlier value — they are never deleted.

  original: 50 items  ->  amendment carries 30 of them
  result:   50 items, 30 of which now hold the amendment's values

This is the same contract as `fin2/layer3/combine.py::build_merged_lines` (base = original,
overlay = only the cells the amendment actually has, ONLY_ORIG kept), expressed for the
long-format rows of `biz_metrics`.

Item identity
-------------
`(metric, table caption, segment, item, period_label, occurrence)`.

`occurrence` is the 0-based count of how many times that tuple already appeared **within the
same filing**. It exists because the first five fields are not unique inside one filing —
measured over 25 companies / 415 periods, 21.9% of parsed rows repeat an identity (some
periods 60%+). Treating a repeat as a duplicate and dropping it loses rows the previous
per-filing loader kept, so repeats are numbered instead. An amendment re-files the same table
with the same repeat structure, so the n-th occurrence lines up with the n-th occurrence.

The caption is part of the key because a single filing routinely emits the same
(metric, segment, item, period_label) from several different tables — measured 2026-07-31,
matching on those four alone collides 9,411 times against only 6,702 aligned rows, i.e. more
than half the rows are not uniquely identifiable. Whitespace is stripped from the caption
because amendments re-typeset it ('(20명× 1,920H )' vs '(20명×1,920H)').

`table_ord` is deliberately NOT part of the key: it is the extraction order inside one filing
and shifts whenever a table is added or removed, so it cannot identify an item across filings.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Optional

# Rows whose caption could not be read still need an identity that is stable within their own
# filing, rather than colliding with every other caption-less row.
_NO_CAPTION = "\x00nocap"


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", "", s or "")


def caption_of(section_row: dict) -> str:
    """Table label used for identity — the narrative head stored by the parsers."""
    return _norm(section_row.get("narrative"))[:80] or _NO_CAPTION


def item_key(metric_row: dict, caption: str) -> tuple:
    return (metric_row.get("metric"), caption,
            _norm(metric_row.get("segment")), _norm(metric_row.get("item")),
            _norm(metric_row.get("period_label")))


def merge_filings(parsed: Iterable[tuple[str, list[dict], list[dict]]]
                  ) -> tuple[list[dict], list[dict], dict]:
    """Merge one period's filings, oldest-first.

    `parsed` = [(rcept_no, section_rows, metric_rows), ...] in chronological order, exactly as
    `parse_biz_metrics` returned them. Rows pass through untouched except that `rcept_no` is
    stamped on, so every stored row records which filing supplied it (provenance).

    Returns (section_rows, merged_metric_rows, stats).
    Section rows are kept for **every** filing — that table is the lossless evidence layer.
    """
    merged: dict[tuple, dict] = {}
    section_out: list[dict] = []
    stats: Counter = Counter()

    for rcept_no, sec_rows, met_rows in parsed:
        stats["filings"] += 1
        caption_by_ord = {s["table_ord"]: caption_of(s) for s in sec_rows}
        for s in sec_rows:
            section_out.append({**s, "rcept_no": rcept_no})

        # ★ 같은 식별자가 한 보고서 안에서 되풀이되는 일이 흔하다(실측 25사 415기간: 원행의
        #   21.9%). 되풀이를 '중복'으로 보고 버리면 **구 적재 방식보다 행이 줄어든다** — 어떤
        #   기간은 60%↑ 유실됐다. 버리지 말고 **반복 순번**을 키에 붙여 구분한다. 정정본도 같은
        #   표를 같은 구조로 다시 내므로 n번째끼리 짝이 맞는다.
        occurrence: Counter = Counter()
        for m in met_rows:
            base = item_key(m, caption_by_ord.get(m.get("table_ord"), _NO_CAPTION))
            n = occurrence[base]
            occurrence[base] += 1
            if n:
                stats["repeated_identity"] += 1
            key = base + (n,)
            stats["overridden" if key in merged else "new"] += 1
            merged[key] = {**m, "rcept_no": rcept_no}

    stats["merged_items"] = len(merged)
    return section_out, list(merged.values()), dict(stats)
