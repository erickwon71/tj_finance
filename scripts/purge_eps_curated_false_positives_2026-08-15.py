"""
Phase 1 of the R28 rollout
(docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md
§8 Phase 1, rules in §4-E-B).

Purge the 13 false-positive rows from the 2,218-key curated candidate set
(scripts/eps_curated_candidates_2026-08-15.json) and emit the three
artifacts Phase 2+ consume:

  (a) fin2/extract/data/eps_kgaap_headline_not_eps_keys_2026-08-15.json
      -- the 2,205 (rcept_no, statement, basis, table_seq, label_raw)
      5-tuple keys _emit_eps_lines will read at import time.
  (b) scripts/eps_curated_purged_rows_2026-08-15.json
      -- audit trail of the 13 purged rows, with which rule(s) fired.
  (c) scripts/eps_r28_target_corps_2026-08-15.txt
      -- the 286 corp_codes left after purge, one per line (Phase 4 input).

Purge rules (§4-E-B, union G ∪ L):
  G -- abs(scaled) <= _EPS_MAX_PLAUSIBLE_WON (gate-survivor group; if the skip
       mechanism fired on these the row would vanish entirely -- the §4-A
       lossless invariant would be violated). Rows with value_won/scaled
       missing are also purged (can't prove the invariant holds).
  L -- label's leading token (after stripping ordinal/paren/roman-numeral/
       digit noise) starts with 주당/기본주당/희석주당/보통주주당 AND
       xref_match is False (LIKELY tier only -- CONFIRMED rows are never
       purged by L, they were cross-validated against an independent total).
"""
import json
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

from fin2.extract.report_lines import _EPS_MAX_PLAUSIBLE_WON  # noqa: E402  (keep in sync with R27)

CANDIDATES_PATH = os.path.join(_REPO_ROOT, "scripts", "eps_curated_candidates_2026-08-15.json")
KEYS_OUT_PATH = os.path.join(_REPO_ROOT, "fin2", "extract", "data",
                              "eps_kgaap_headline_not_eps_keys_2026-08-15.json")
PURGED_OUT_PATH = os.path.join(_REPO_ROOT, "scripts", "eps_curated_purged_rows_2026-08-15.json")
CORPS_OUT_PATH = os.path.join(_REPO_ROOT, "scripts", "eps_r28_target_corps_2026-08-15.txt")

# Strip ordinal/paren/roman-numeral/digit/punctuation noise from the label's
# leading edge, then test whether what's left starts with an EPS-subject token.
_LEADING_NOISE_RE = re.compile(r"^[\s()\[\]0-9ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫIVX.,\-·]+")
_EPS_SUBJECT_RE = re.compile(r"^(주당|기본주당|희석주당|보통주주당)")


def rule_g(row: dict) -> bool:
    """Gate-survivor group -- would not vanish under the skip mechanism,
    so keeping it here would break the §4-A lossless invariant."""
    scaled = row.get("scaled")
    if scaled is None:
        return True  # can't prove the invariant holds -> purge
    return abs(scaled) <= _EPS_MAX_PLAUSIBLE_WON


def rule_l(row: dict) -> bool:
    """Structural: leading token is an EPS-subject word, and this row was
    never cross-validated against an independent std_v3 total."""
    if row.get("xref_match"):
        return False  # CONFIRMED rows are exempt (§4-E-B)
    stripped = _LEADING_NOISE_RE.sub("", row["label"])
    return bool(_EPS_SUBJECT_RE.match(stripped))


def main():
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)
    all_rows = candidates["confirmed"] + candidates["likely_no_xref"]
    print(f"Loaded {len(candidates['confirmed'])} CONFIRMED + "
          f"{len(candidates['likely_no_xref'])} LIKELY = {len(all_rows)} total candidates")

    kept, purged = [], []
    for row in all_rows:
        g = rule_g(row)
        l = rule_l(row)
        if g or l:
            row = dict(row)
            row["purge_rule_g"] = g
            row["purge_rule_l"] = l
            purged.append(row)
        else:
            kept.append(row)

    print(f"\nPurged: {len(purged)} rows (rule G: {sum(r['purge_rule_g'] for r in purged)}, "
          f"rule L: {sum(r['purge_rule_l'] for r in purged)}, "
          f"both: {sum(r['purge_rule_g'] and r['purge_rule_l'] for r in purged)})")
    purged_corps = sorted(set(r["corp_code"] for r in purged))
    print(f"Purged corps ({len(purged_corps)}): {' '.join(purged_corps)}")
    purged_filings = set((r["corp_code"], r["fy"], r["period"]) for r in purged)
    print(f"Purged distinct filings(corp+fy+period): {len(purged_filings)}")
    confirmed_purged = sum(1 for r in purged if r.get("xref_match"))
    print(f"CONFIRMED rows purged (should be 0): {confirmed_purged}")

    print(f"\nKept: {len(kept)} rows")
    kept_filings = set((r["corp_code"], r["fy"], r["period"]) for r in kept)
    kept_rcepts = set(r["rcept_no"] for r in kept)
    kept_corps = set(r["corp_code"] for r in kept)
    print(f"Kept distinct filings(corp+fy+period): {len(kept_filings)}")
    print(f"Kept distinct rcept_no: {len(kept_rcepts)}")
    print(f"Kept distinct corp: {len(kept_corps)}")

    # Lossless invariant check on the keep set (§4-A / §8 Phase 1 hard invariant).
    violators = [r for r in kept if r.get("scaled") is None or abs(r["scaled"]) <= _EPS_MAX_PLAUSIBLE_WON]
    if violators:
        print(f"\n!!! INVARIANT VIOLATION: {len(violators)} kept rows fail "
              f"|scaled| > {_EPS_MAX_PLAUSIBLE_WON} !!!")
        for r in violators[:5]:
            print(f"  {r['rcept_no']} {r['corp_code']} scaled={r.get('scaled')}")
        sys.exit(1)
    print(f"\nInvariant OK: all {len(kept)} kept rows satisfy |scaled| > {_EPS_MAX_PLAUSIBLE_WON}")

    # (a) 5-tuple keys for the code to load.
    keys = sorted(
        [r["rcept_no"], r["statement"], r["basis"], int(r["table_seq"]), r["label"]]
        for r in kept
    )
    os.makedirs(os.path.dirname(KEYS_OUT_PATH), exist_ok=True)
    with open(KEYS_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=1)
    print(f"\nWrote {len(keys)} keys -> {KEYS_OUT_PATH}")

    # (b) purged rows audit trail.
    with open(PURGED_OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(purged, f, ensure_ascii=False, indent=1, default=str)
    print(f"Wrote {len(purged)} purged rows -> {PURGED_OUT_PATH}")

    # (c) target corp list for Phase 4.
    with open(CORPS_OUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(kept_corps and sorted(kept_corps)) + "\n")
    print(f"Wrote {len(kept_corps)} corp codes -> {CORPS_OUT_PATH}")


if __name__ == "__main__":
    main()
