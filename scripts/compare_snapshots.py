"""
두 standard_financials 스냅샷을 비교해 변동된 항목을 리포트.

사용:
    python scripts/compare_snapshots.py before.json after.json
    python scripts/compare_snapshots.py before.json after.json --threshold 1  # 1% 이상 경고
    python scripts/compare_snapshots.py before.json after.json --corp 00126380
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_COMPARE_FIELDS = [
    ("revenue",           "매출액"),
    ("operating_income",  "영업이익"),
    ("net_income",        "당기순이익"),
    ("controlling_ni",    "지배주주순이익"),
    ("total_assets",      "총자산"),
    ("total_liabilities", "총부채"),
    ("total_equity",      "총자본"),
    ("cfo",               "영업CF"),
    ("cfi",               "투자CF"),
    ("cff",               "재무CF"),
    ("capex",             "CAPEX"),
    ("da_total",          "D&A"),
    ("ebitda",            "EBITDA"),
    ("fcf",               "FCF"),
    ("net_debt",          "순부채"),
    ("dividends_paid",    "배당금"),
    ("shares_out",        "발행주식수"),
    ("data_quality",      "데이터품질"),
]


def _diff_pct(before_v, after_v):
    """변화율 계산. 0 나누기 방지."""
    if before_v is None and after_v is None:
        return 0.0, "SAME"
    if before_v is None and after_v is not None:
        return None, "ADDED"
    if before_v is not None and after_v is None:
        return None, "REMOVED"
    if before_v == 0:
        return None, "ZERO_BASE"
    return (after_v - before_v) / abs(before_v) * 100, "CHANGED"


def compare_snapshots(before_path, after_path, threshold_pct=5.0, corp_filter=None):
    with open(before_path, "r", encoding="utf-8") as f:
        before = json.load(f)
    with open(after_path, "r", encoding="utf-8") as f:
        after = json.load(f)

    all_keys = set(before["data"]) | set(after["data"])
    if corp_filter:
        all_keys = {k for k in all_keys if k.startswith(corp_filter)}

    changes = []
    added_keys   = []
    removed_keys = []

    for key in sorted(all_keys):
        b_rec = before["data"].get(key)
        a_rec = after["data"].get(key)

        if b_rec is None:
            added_keys.append(key)
            continue
        if a_rec is None:
            removed_keys.append(key)
            continue

        key_changes = []
        for field, label in _COMPARE_FIELDS:
            bv = b_rec.get(field)
            av = a_rec.get(field)
            if bv == av:
                continue
            pct, status = _diff_pct(bv, av)
            if status == "SAME":
                continue
            is_significant = (
                status in ("ADDED", "REMOVED", "ZERO_BASE") or
                (pct is not None and abs(pct) >= threshold_pct)
            )
            key_changes.append({
                "field":      field,
                "label":      label,
                "before":     bv,
                "after":      av,
                "pct":        pct,
                "status":     status,
                "flagged":    is_significant,
            })

        if key_changes:
            changes.append({
                "key":        key,
                "corp_code":  b_rec["corp_code"],
                "corp_name":  b_rec["corp_name"],
                "fiscal_year": b_rec["fiscal_year"],
                "changes":    key_changes,
                "has_flagged": any(c["flagged"] for c in key_changes),
            })

    # ── 출력 ──────────────────────────────────────────────────────────
    flagged = [c for c in changes if c["has_flagged"]]
    minor   = [c for c in changes if not c["has_flagged"]]

    print(f"\n{'='*70}")
    print(f"스냅샷 비교: {Path(before_path).name} → {Path(after_path).name}")
    print(f"  변동 대상: {len(changes)}건 (추가:{len(added_keys)}  삭제:{len(removed_keys)})")
    print(f"  임계값 {threshold_pct}% 이상 주요 변동: {len(flagged)}건")
    print(f"{'='*70}")

    if flagged:
        print(f"\n[주요 변동 — {threshold_pct}% 이상 차이]")
        for rec in flagged:
            print(f"\n  {rec['corp_name']} ({rec['corp_code']})  {rec['fiscal_year']}  {rec['key'].split('|')[2]}|{rec['key'].split('|')[3]}")
            for c in rec["changes"]:
                flag = " ⚠" if c["flagged"] else ""
                pct_str = f"{c['pct']:+.1f}%" if c["pct"] is not None else c["status"]
                bv_str = f"{c['before']:,}" if isinstance(c["before"], (int, float)) and c["before"] is not None else str(c["before"])
                av_str = f"{c['after']:,}"  if isinstance(c["after"],  (int, float)) and c["after"]  is not None else str(c["after"])
                print(f"    {c['label']:<14} {bv_str:>18} → {av_str:>18}  ({pct_str}){flag}")

    if minor:
        print(f"\n[소규모 변동 — {threshold_pct}% 미만]")
        for rec in minor[:20]:  # 최대 20건만 표시
            changed_fields = [c["label"] for c in rec["changes"]]
            print(f"  {rec['corp_name']} ({rec['corp_code']}) {rec['fiscal_year']}:  {', '.join(changed_fields)}")
        if len(minor) > 20:
            print(f"  ... 외 {len(minor)-20}건 생략")

    if added_keys:
        print(f"\n[신규 추가 레코드 — {len(added_keys)}건]")
        for k in added_keys[:10]:
            print(f"  {k}")
        if len(added_keys) > 10:
            print(f"  ... 외 {len(added_keys)-10}건")

    if removed_keys:
        print(f"\n[삭제된 레코드 — {len(removed_keys)}건]")
        for k in removed_keys[:10]:
            print(f"  {k}")
        if len(removed_keys) > 10:
            print(f"  ... 외 {len(removed_keys)-10}건")

    if not changes and not added_keys and not removed_keys:
        print("\n✅ 변동 없음 — 두 스냅샷이 동일합니다.")

    return len(flagged)


def main():
    parser = argparse.ArgumentParser(description="standard_financials 스냅샷 비교")
    parser.add_argument("before", help="이전 스냅샷 JSON 파일")
    parser.add_argument("after",  help="이후 스냅샷 JSON 파일")
    parser.add_argument("--threshold", "-t", type=float, default=5.0,
                        help="경고 임계값 %% (기본 5%%)")
    parser.add_argument("--corp",   default=None,
                        help="특정 기업 DART 코드 필터")
    args = parser.parse_args()

    flagged_count = compare_snapshots(
        before_path=args.before,
        after_path=args.after,
        threshold_pct=args.threshold,
        corp_filter=args.corp,
    )
    sys.exit(1 if flagged_count > 0 else 0)


if __name__ == "__main__":
    main()
