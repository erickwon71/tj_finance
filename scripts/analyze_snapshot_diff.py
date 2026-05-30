"""
두 스냅샷(before/after) JSON을 비교해 revenue/total_assets 변동을 비율로 분류.
단위탐지 수정의 영향(≈÷1000 교정) vs 회귀(예상치 못한 증가/감소) 판별용.

사용: python3 scripts/analyze_snapshot_diff.py before.json after.json
"""
import json
import sys
from collections import Counter


def load(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # snapshot_metrics 구조: {"data": {"corp|fy|period|stmt": {record}}}
    return data["data"] if isinstance(data, dict) and "data" in data else data


def categorize(ratio):
    if ratio is None:
        return "n/a"
    if 0.0009 <= ratio <= 0.0011:
        return "÷1000 (단위교정)"
    if 0.0000009 <= ratio <= 0.0000011:
        return "÷1e6 (단위교정)"
    if ratio < 0.5:
        return "기타 감소"
    if ratio <= 2.0:
        return "소폭(±2x)"
    if 900 <= ratio <= 1100:
        return "×1000 (회귀의심!)"
    return "기타 증가(>2x)"


def main():
    before = load(sys.argv[1])
    after = load(sys.argv[2])

    fields = ["revenue", "total_assets"]
    cat = Counter()
    suspicious = []  # 회귀 의심: 값이 ×1000 증가 또는 큰 증가

    for key in before.keys() & after.keys():
        b, a = before[key], after[key]
        for fld in fields:
            bv, av = b.get(fld), a.get(fld)
            if bv is None or av is None or bv == 0:
                continue
            if bv == av:
                continue
            ratio = av / bv
            c = categorize(ratio)
            cat[c] += 1
            if c == "×1000 (회귀의심!)":
                suspicious.append((key, fld, bv / 1e8, av / 1e8, ratio))

    print("=== revenue/total_assets 변동 분류 ===")
    for c, n in cat.most_common():
        print(f"  {c:<22}: {n:,}")

    print(f"\n=== ×1000 증가 케이스 (회귀 vs 과소교정 판별) {len(suspicious)}건 ===")
    for key, fld, bawk, aawk, ratio in sorted(suspicious, key=lambda x: -x[4])[:20]:
        print(f"  {key}  {fld}: {bawk:,.1f}억 → {aawk:,.1f}억  ({ratio:,.0f}x)")


if __name__ == "__main__":
    main()
