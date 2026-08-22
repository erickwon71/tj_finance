#!/usr/bin/env python
"""
T1 진단 스캐너 — canonical collapse 조사 (P0.6, 읽기전용).

배경: `bs.lease_liability`(유동+비유동 리스부채)·`cf.borrowings_proceeds`/`_repaid`
(단기+장기 차입 유입/상환)가 각각 하나의 canonical로 collapse 되어 있어, 같은 filing 안에
서로 다른 두 금액이 매핑되면 `_resolve()`가 충돌로 보고 값 전체를 버린다(HOLD). 이 스크립트는
그 collapse를 **유동/비유동, 단기/장기로 분해**하는 안(SPLIT_DRAFT)이 실제로 안전한지 —
분해 대상 밖의 다른 라벨 매핑까지 흔드는지 — 카탈로그를 고치기 *전에* 재본다.

참고: docs/plans/std_v2_catalog_split_p0_6_todo_2026-08-22.md (T1~T5)
      docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md (§3.7, 대원칙)

★ 원칙:
  - 이 스크립트는 어떤 파일도 쓰지 않는다. `account_maps/*.py`는 무변경.
  - DB는 SELECT만 쓴다(트랜잭션 커밋 없음, INSERT/UPDATE/DELETE/CREATE/ALTER/DROP 금지).
  - 분해안은 아래 SPLIT_DRAFT dict로만 표현한다 — 카탈로그에는 반영하지 않는다.

Subcommands:
  labels    ① 분해 대상 라벨 전수 지도 (DB 필요) — 새 변형·총계/분리 공존비율
  diff      ② 분해 전/후 매핑 diff, --offline 가능(DB 불필요) — 파급 범위(가장 싸고 중요)
  paren     ③ 괄호 표기 정규화 결함 범위 (DB 필요)
  conflict  ④ 충돌 재측정(P0.5 재현·확대, DB 필요) — canonical별 값-충돌 그룹 수

사용 예:
    python scripts/diag_canonical_collapse_scan.py diff --offline
    python scripts/diag_canonical_collapse_scan.py labels --family lease --statement BS
    python scripts/diag_canonical_collapse_scan.py conflict --family all
"""
from __future__ import annotations

import argparse
import copy
import csv
import re
import sys
from collections import defaultdict

from parser.common.account_mapper import AccountMapper, get_mapper
from parser.common.amount_normalizer import normalize_account_name
import account_maps.bs_accounts as _bs_mod
import account_maps.is_accounts as _is_mod
import account_maps.cf_accounts as _cf_mod
import account_maps.note_accounts as _note_mod
from fin2.standardize.rules import (
    _LEASE_PARTS, _BORROW_PROCEEDS_PARTS, _BORROW_REPAID_PARTS,
    _ST_DEBT_PARTS, _LT_DEBT_PARTS,
)

# ── Proposed split (draft, T2 결과로 다듬을 것). account_maps/*.py 는 손대지 않는다. ──
SPLIT_DRAFT: dict[str, list[str]] = {
    "bs.lease_current":    ["유동리스부채", "유동성리스부채", "유동 리스부채"],
    "bs.lease_noncurrent": ["비유동리스부채", "비유동 리스부채", "비유동성리스부채",
                            "비유동금융리스부채"],
    "bs.lease_liability":  ["리스부채", "금융리스부채"],          # 총계는 그대로 둠
    "cf.borrow_proceeds_st": ["단기차입금의증가", "단기차입금의차입"],
    "cf.borrow_proceeds_lt": ["장기차입금의증가", "장기차입금의차입"],
    "cf.borrow_repaid_st":   ["단기차입금의상환", "단기차입금의감소"],
    "cf.borrow_repaid_lt":   ["장기차입금의상환"],
    "cf.borrowings_proceeds": ["차입금의증가", "차입금의차입", "차입금차입"],  # 총계는 그대로 둠
    "cf.borrowings_repaid":   ["차입금의상환", "차입금상환"],                 # 총계는 그대로 둠
}

# family → SPLIT_DRAFT의 어느 부분집합을 적용할지
_FAMILY_CODES = {
    "lease": {"bs.lease_current", "bs.lease_noncurrent", "bs.lease_liability"},
    "borrow": {"cf.borrow_proceeds_st", "cf.borrow_proceeds_lt",
               "cf.borrow_repaid_st", "cf.borrow_repaid_lt",
               "cf.borrowings_proceeds", "cf.borrowings_repaid"},
}
_FAMILY_CODES["all"] = set().union(*_FAMILY_CODES.values())

# 기존(collapse) canonical — labels/conflict 조회 대상
_FAMILY_OLD_CANON = {
    "lease": ["bs.lease_liability", "bs.lease_current", "bs.lease_noncurrent"],
    "borrow": ["cf.borrowings_proceeds", "cf.borrowings_repaid"],
    "debt": ["bs.current_lt_debt", "bs.current_portion_lt_debt",
             "bs.bond", "bs.bonds", "bs.current_bonds_plain", "bs.current_bond",
             "bs.current_bonds_conv"],
}
_FAMILY_OLD_CANON["all"] = [c for v in _FAMILY_OLD_CANON.values() for c in v]

# T3 "인접 계열" — 분해와 무관하지만 퍼지 파급 감시용으로 같이 diff 해야 하는 라벨
_ADJACENT_LABELS = [
    "유동성장기부채", "유동성장기차입금", "유동성사채", "기타유동부채",
    "기타금융부채", "장기차입금및사채", "사채", "단기차입금", "장기차입금",
]


def _check_split_draft_matches_rules() -> None:
    expected = set(_LEASE_PARTS) | set(_BORROW_PROCEEDS_PARTS) | set(_BORROW_REPAID_PARTS)
    missing = expected - set(SPLIT_DRAFT)
    if missing:
        print(f"⚠ SPLIT_DRAFT 가 rules.py 기대 이름과 어긋남 — 누락: {sorted(missing)}",
              file=sys.stderr)


def _all_alias_universe() -> list[tuple[str, str, str]]:
    """(alias, code, section_prefix) 전량 — diff --offline 후보 라벨 소스."""
    out = []
    for prefix, mod in (("bs", _bs_mod.BS_ACCOUNTS), ("is", _is_mod.IS_ACCOUNTS),
                         ("cf", _cf_mod.CF_ACCOUNTS), ("note", _note_mod.NOTE_ACCOUNTS)):
        for code, aliases in mod.items():
            for alias in aliases:
                out.append((alias, code, prefix))
    return out


def _mapper_with_overlay(split_draft: dict[str, list[str]]) -> AccountMapper:
    """SPLIT_DRAFT 를 반영한 '이후' 매퍼를 파일 수정 없이 만든다.

    account_maps 의 4개 dict 를 deep-copy 하고, split_draft 의 각 alias 를 원래
    있던 code 에서 제거한 뒤 새 code 밑으로 옮긴다. account_mapper 모듈의 전역
    이름을 일시적으로 그 copy 로 바꿔치기해 AccountMapper() 를 재구성한다
    (account_maps/*.py 파일 자체는 전혀 건드리지 않는다).
    """
    bs = copy.deepcopy(_bs_mod.BS_ACCOUNTS)
    is_ = copy.deepcopy(_is_mod.IS_ACCOUNTS)
    cf = copy.deepcopy(_cf_mod.CF_ACCOUNTS)
    note = copy.deepcopy(_note_mod.NOTE_ACCOUNTS)
    section_maps = {"bs": bs, "is": is_, "cf": cf, "note": note}

    for new_code, aliases in split_draft.items():
        prefix = new_code.split(".", 1)[0]
        target = section_maps[prefix]
        for alias in aliases:
            for m in section_maps.values():
                for code, alias_list in m.items():
                    if alias in alias_list:
                        alias_list.remove(alias)
            target.setdefault(new_code, [])
            if alias not in target[new_code]:
                target[new_code].append(alias)

    import parser.common.account_mapper as am
    orig = (am.BS_ACCOUNTS, am.IS_ACCOUNTS, am.CF_ACCOUNTS, am.NOTE_ACCOUNTS)
    am.BS_ACCOUNTS, am.IS_ACCOUNTS, am.CF_ACCOUNTS, am.NOTE_ACCOUNTS = bs, is_, cf, note
    try:
        return AccountMapper()
    finally:
        am.BS_ACCOUNTS, am.IS_ACCOUNTS, am.CF_ACCOUNTS, am.NOTE_ACCOUNTS = orig


def _write_csv(rows: list[dict], path: str) -> None:
    if not rows:
        print("(결과 0행 — CSV 미작성)")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"→ {len(rows)}행 저장: {path}")


# ── subcommand: diff ────────────────────────────────────────────────────

def cmd_diff(args: argparse.Namespace) -> None:
    _check_split_draft_matches_rules()
    family_codes = _FAMILY_CODES[args.family]
    split_subset = {k: v for k, v in SPLIT_DRAFT.items() if k in family_codes}

    before = get_mapper()
    after = _mapper_with_overlay(split_subset)

    split_aliases = {a for aliases in split_subset.values() for a in aliases}

    # 후보 라벨: 전체 alias 우주(오프라인) + T3 인접계열 + (옵션) DB 관측 라벨
    candidates: list[tuple[str, str]] = [(alias, prefix) for alias, _, prefix in _all_alias_universe()]
    for lbl in _ADJACENT_LABELS:
        candidates.append((lbl, "bs"))
        candidates.append((lbl, "cf"))

    if not args.offline:
        from collector.db import get_session
        from sqlalchemy import text as sqltext
        old_canon = _FAMILY_OLD_CANON[args.family]
        with get_session() as session:
            rows = session.execute(sqltext("""
                SELECT DISTINCT acode, section_kind
                FROM fact_v2
                WHERE canonical_account = ANY(:codes)
                  AND source_format IN ('xml_text', 'pdf')
            """), {"codes": old_canon}).fetchall()
        for acode, section_kind in rows:
            prefix = (section_kind or "bs").lower()
            if prefix not in ("bs", "is", "cf", "note"):
                prefix = "bs"
            candidates.append((acode, prefix))

    seen = set()
    unexpected_changes = []
    expected_changes = []
    n_checked = 0
    for label, prefix in candidates:
        key = (label, prefix)
        if key in seen:
            continue
        seen.add(key)
        n_checked += 1
        r_before = before.map(label, fs_section=prefix)
        r_after = after.map(label, fs_section=prefix)
        if r_before.account_code == r_after.account_code:
            continue
        row = {
            "label": label, "section": prefix,
            "before_code": r_before.account_code, "before_stage": r_before.stage,
            "after_code": r_after.account_code, "after_stage": r_after.stage,
        }
        if label in split_aliases:
            expected_changes.append(row)
        else:
            unexpected_changes.append(row)

    print(f"검사한 라벨 수: {n_checked}")
    print(f"예상된 변경(분해 대상 자체): {len(expected_changes)}건")
    print(f"★예상 밖 변경(합격조건=0): {len(unexpected_changes)}건")
    for row in unexpected_changes[:50]:
        print(f"  {row['label']!r} [{row['section']}]  {row['before_code']}({row['before_stage']})"
              f" → {row['after_code']}({row['after_stage']})")
    if len(unexpected_changes) > 50:
        print(f"  ... 외 {len(unexpected_changes) - 50}건")

    if args.csv:
        _write_csv(expected_changes + unexpected_changes, args.csv)


# ── subcommand: labels ──────────────────────────────────────────────────

def cmd_labels(args: argparse.Namespace) -> None:
    from collector.db import get_session
    from sqlalchemy import text as sqltext

    old_canon = _FAMILY_OLD_CANON[args.family]
    statement_filter = ""
    params = {"codes": old_canon}
    if args.statement:
        statement_filter = "AND section_kind = :stmt"
        params["stmt"] = args.statement.upper()

    with get_session() as session:
        rows = session.execute(sqltext(f"""
            SELECT canonical_account, acode AS label_raw, mapping_stage,
                   mapping_confidence, source_format, count(*) AS n
            FROM fact_v2
            WHERE canonical_account = ANY(:codes)
              {statement_filter}
            GROUP BY 1, 2, 3, 4, 5
            ORDER BY canonical_account, n DESC
        """), params).fetchall()

    out = []
    for canon, label_raw, stage, conf, src, n in rows:
        split_target = None
        for new_code, aliases in SPLIT_DRAFT.items():
            if label_raw in aliases:
                split_target = new_code
                break
        out.append({
            "canonical_account": canon, "label_raw": label_raw, "n": n,
            "mapping_stage": stage, "mapping_confidence": conf,
            "source_format": src, "split_target": split_target or "(미분류)",
        })

    print(f"{'canonical':<24}{'label_raw':<28}{'n':>10}  stage      conf   src        split_target")
    for row in out[:args.sample]:
        print(f"{row['canonical_account']:<24}{row['label_raw']:<28}{row['n']:>10}  "
              f"{str(row['mapping_stage']):<10}{str(row['mapping_confidence']):<7}"
              f"{str(row['source_format']):<11}{row['split_target']}")
    if len(out) > args.sample:
        print(f"... 외 {len(out) - args.sample}행 (--sample 로 더 보기 / --csv 로 전량 저장)")

    unclassified = [r for r in out if r["split_target"] == "(미분류)"]
    print(f"\n분해안에 없는 label_raw 변형(새 변형 후보): {len(unclassified)}건")
    for r in unclassified[:20]:
        print(f"  {r['label_raw']!r} (n={r['n']}, canonical={r['canonical_account']})")

    if args.csv:
        _write_csv(out, args.csv)


# ── subcommand: paren ───────────────────────────────────────────────────

_PAREN_RE = re.compile(r"[\(\)（）]")


def cmd_paren(args: argparse.Namespace) -> None:
    from collector.db import get_session
    from sqlalchemy import text as sqltext

    limit_clause = "" if args.all else "LIMIT :n"
    params = {}
    if not args.all:
        params["n"] = args.sample

    with get_session() as session:
        rows = session.execute(sqltext(f"""
            SELECT acode AS label_raw, canonical_account, mapping_stage, count(*) AS n
            FROM fact_v2
            WHERE source_format IN ('xml_text', 'pdf')
              AND acode ~ '[()（）]'
            GROUP BY 1, 2, 3
            ORDER BY n DESC
            {limit_clause}
        """), params).fetchall()

    total = 0
    unknown = 0
    out = []
    for label_raw, canon, stage, n in rows:
        total += n
        # ★ fact_v2.canonical_account는 fuzzy/unknown 매치에 문자열 "unknown.*"가 아니라
        # NULL이 저장된다(fin2/extract/text.py::_canonical_of — "퍼지 매치는 canonical을
        # 주지 않는다"). 따라서 "못 잡힌 라벨" = canonical IS NULL로 판정해야 한다.
        is_unknown = canon is None
        if is_unknown:
            unknown += n
        norm = normalize_account_name(label_raw)
        out.append({
            "label_raw": label_raw, "normalized": norm, "canonical_account": canon,
            "mapping_stage": stage, "n": n, "is_unknown": is_unknown,
        })

    ratio = (unknown / total * 100) if total else 0.0
    print(f"괄호 포함 라벨 표본: {len(out)}종 / {total}행")
    print(f"canonical 미부여(NULL) 비율: {unknown}/{total} = {ratio:.2f}%")
    for r in sorted(out, key=lambda r: -r["n"])[:30]:
        flag = "★unknown" if r["is_unknown"] else ""
        print(f"  {r['label_raw']!r} → norm={r['normalized']!r} → {r['canonical_account']}"
              f" ({r['mapping_stage']}, n={r['n']}) {flag}")

    if args.csv:
        _write_csv(out, args.csv)


# ── subcommand: conflict ────────────────────────────────────────────────

def cmd_conflict(args: argparse.Namespace) -> None:
    from collector.db import get_session
    from sqlalchemy import text as sqltext

    old_canon = _FAMILY_OLD_CANON[args.family]
    with get_session() as session:
        rows = session.execute(sqltext("""
            SELECT canonical_account,
                   count(*) FILTER (WHERE distinct_vals > 1) AS conflict_groups,
                   count(*) AS total_groups
            FROM (
                SELECT rcept_no, basis, col_index, context_fiscal_year, canonical_account,
                       count(DISTINCT amount_won) AS distinct_vals
                FROM fact_v2
                WHERE canonical_account = ANY(:codes) AND NOT is_dimensional
                GROUP BY 1, 2, 3, 4, 5
            ) t
            GROUP BY 1
            ORDER BY 1
        """), {"codes": old_canon}).fetchall()

    print(f"{'canonical':<26}{'conflict_groups':>16}{'total_groups':>14}{'ratio':>10}")
    out = []
    for canon, conflict_groups, total_groups in rows:
        ratio = (conflict_groups / total_groups * 100) if total_groups else 0.0
        print(f"{canon:<26}{conflict_groups:>16}{total_groups:>14}{ratio:>9.1f}%")
        out.append({"canonical_account": canon, "conflict_groups": conflict_groups,
                     "total_groups": total_groups, "conflict_ratio_pct": round(ratio, 2)})

    if args.csv:
        _write_csv(out, args.csv)


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="subcommand", required=True)

    def add_common(p):
        p.add_argument("--family", choices=["lease", "borrow", "debt", "all"], default="all")
        p.add_argument("--sample", type=int, default=400)
        p.add_argument("--all", action="store_true", help="전수 스캔(★장시간, 사용자 실행)")
        p.add_argument("--statement", choices=["BS", "CF", "IS", "NOTE"], default=None)
        p.add_argument("--csv", default=None, help="결과 CSV 저장 경로")

    p_labels = sub.add_parser("labels", help="① 분해 대상 라벨 전수 지도 (DB 필요)")
    add_common(p_labels)
    p_labels.set_defaults(func=cmd_labels)

    p_diff = sub.add_parser("diff", help="② 분해 전/후 매핑 diff (--offline 가능)")
    add_common(p_diff)
    p_diff.add_argument("--offline", action="store_true", help="DB 없이 alias 우주만으로 diff")
    p_diff.set_defaults(func=cmd_diff)

    p_paren = sub.add_parser("paren", help="③ 괄호 표기 정규화 결함 범위 (DB 필요)")
    add_common(p_paren)
    p_paren.set_defaults(func=cmd_paren)

    p_conflict = sub.add_parser("conflict", help="④ 충돌 재측정(P0.5 재현·확대, DB 필요)")
    add_common(p_conflict)
    p_conflict.set_defaults(func=cmd_conflict)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
