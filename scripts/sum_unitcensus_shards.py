"""단위 census 샤드 로그 합산 — 6 개 로그의 표를 더해 전수 수치를 만든다 (READ-ONLY).

`audit_unit_declarations.py --shard a/6` 을 6 개 띄우면 로그가 6 벌 나온다. 손으로 더하면
자릿수를 틀리기 쉬워 스크립트로 남긴다(이번 census 는 3억 셀 규모다).

    python scripts/sum_unitcensus_shards.py logs/unitcensus_f1_shard*.log
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

CLASSES = ("금액단독", "혼합", "비금액단독", "미선언")
_ROW_RE = re.compile(
    r"^(금액단독|혼합|비금액단독|미선언)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s*$")
_FILL_RE = re.compile(r"^\s+(금액단독|혼합|비금액단독|미선언)\s+채움\s+([\d,]+)\s+·\s+원문만\s+([\d,]+)")
_HEAD_RE = re.compile(r"^★ (금액을 선언했는데 폐기된 표|혼합 단위로 적재된 표)\s*:\s*([\d,]+)\s+\(숫자셀 ([\d,]+)\)")
_TOTAL_RE = re.compile(r"^표 ([\d,]+) · 숫자셀 ([\d,]+)")
_FILING_RE = re.compile(r"=== 단위 선언 census \(filing (\d+)")


def n(s: str) -> int:
    return int(s.replace(",", ""))


def main(paths: list[str]) -> int:
    t: Counter[str] = Counter()
    done = 0
    for p in paths:
        text = Path(p).read_text(errors="replace")
        if "단위 선언 census (filing" not in text:
            print(f"  ⏳ 미완료: {p}")
            continue
        done += 1
        for line in text.splitlines():
            if (m := _FILING_RE.search(line)):
                t["filing"] += int(m.group(1))
            elif (m := _TOTAL_RE.match(line)):
                t["표:합계"] += n(m.group(1)); t["셀:합계"] += n(m.group(2))
            elif (m := _ROW_RE.match(line)):
                c = m.group(1)
                t[f"표:{c}"] += n(m.group(2)); t[f"셀:{c}"] += n(m.group(3))
                t[f"적재표:{c}"] += n(m.group(4)); t[f"폐기표:{c}"] += n(m.group(5))
                t[f"폐기셀:{c}"] += n(m.group(6))
            elif (m := _FILL_RE.match(line)):
                t[f"채움:{m.group(1)}"] += n(m.group(2))
                t[f"원문만:{m.group(1)}"] += n(m.group(3))
            elif (m := _HEAD_RE.match(line.strip())):
                key = "금액선언인데폐기" if "폐기" in m.group(1) else "혼합적재"
                t[f"{key}:표"] += n(m.group(2)); t[f"{key}:셀"] += n(m.group(3))

    print(f"=== 단위 선언 census 합산 (샤드 {done}/{len(paths)} · filing {t['filing']:,}) ===")
    print(f"표 {t['표:합계']:,} · 숫자셀 {t['셀:합계']:,}\n")
    print(f"{'분류':<12}{'표':>12}{'셀':>15}{'적재표':>12}{'폐기표':>12}{'폐기셀':>14}")
    for c in CLASSES:
        print(f"{c:<12}{t[f'표:{c}']:>12,}{t[f'셀:{c}']:>15,}"
              f"{t[f'적재표:{c}']:>12,}{t[f'폐기표:{c}']:>12,}{t[f'폐기셀:{c}']:>14,}")
    print(f"\n★ 금액을 선언했는데 폐기된 표 : {t['금액선언인데폐기:표']:,} "
          f"(숫자셀 {t['금액선언인데폐기:셀']:,})")
    print(f"★ 혼합 단위로 적재된 표       : {t['혼합적재:표']:,} (숫자셀 {t['혼합적재:셀']:,})")

    fill = sum(t[f"채움:{c}"] for c in CLASSES)
    raw = sum(t[f"원문만:{c}"] for c in CLASSES)
    print(f"\n=== 적재 셀의 단위 확정 ===")
    print(f"  value_won 채움 : {fill:,}")
    print(f"  value_raw 만   : {raw:,}  ({100*raw/max(fill+raw,1):.1f}%)")
    for c in CLASSES:
        if t[f"채움:{c}"] or t[f"원문만:{c}"]:
            print(f"    {c:<8} 채움 {t[f'채움:{c}']:>14,} · 원문만 {t[f'원문만:{c}']:>14,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["logs/unitcensus_f1_shard%d.log" % i for i in range(6)]))
