"""`order_backlog`·`biz_metrics` 공백의 **원인**을 원문에서 가른다 (READ-ONLY).

문제
----
문서 census(2026-07-30)에서 `사업의내용 → order_backlog` 가 표본 62/62(100%) 공백,
`biz_metrics` 는 87.1% 공백이었다. 전체로도 order_backlog 566사/2,534 · 가동률 1,513사/2,534.
그런데 "공백"은 두 가지 완전히 다른 사실을 한 단어로 덮는다:

    ① 원문에 그 절이 **없다**            → 정상(수주상황은 건설·조선·방산 등 일부 업종만 쓴다)
    ② 원문에 있는데 **추출이 못 뽑았다**  → 결함(헤딩 키워드 미스매치 · 열 키워드 미스매치 …)

이 도구는 filing 마다 그 둘을 갈라 센다. 추출기 내부 단계(`find_order_subsections`
→ `map_order_table`)를 그대로 호출해 **어디서 0 이 되는지**를 짚는다. 헤딩·표는 있는데 행이
0 인 사례는 표의 헤더 행을 함께 찍어 원인을 눈으로 볼 수 있게 한다.

Usage
-----
    python scripts/audit_biz_order_gap.py --limit 120
    python scripts/audit_biz_order_gap.py --limit 120 --show 15
    python scripts/audit_biz_order_gap.py --rcept 20240313000123 --show 20
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.biz_section import (_heading_metrics, _load_root, _tag, _text,
                                      find_biz_subsections, map_biz_table)
from fin2.extract.order_backlog import (_BACKLOG_KW, _ORDER_HEADING_KW,
                                        find_order_subsections, map_order_table)

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015 {rcept_clause}
    ORDER BY f.rcept_no
"""

# 문서 어디든 '수주' 가 나오는가 — 절 자체의 존재 여부(원문 부재와 추출 실패를 가르는 1차 신호).
_ORDER_ANY_RE = re.compile(r"수주")
_BIZ_ANY_RE = re.compile(r"생산능력|생산실적|가동률|가동율")


def scan(root, t: Counter, samples: dict, rcept: str, fiscal_year: int) -> None:
    full = " ".join(x for x in (_text(el) for el in root.iter()) if x)

    # ── 수주상황 ────────────────────────────────────────────────────────
    has_word = bool(_ORDER_ANY_RE.search(full))
    # 헤딩 존재 여부를 **따로** 센다. `find_order_subsections` 는 헤딩 뒤에 TABLE 이 있을 때만
    # 결과를 만들므로, 그것만 보면 '헤딩은 있는데 표가 없다'(예 '마. 수주현황 — 해당사항 없음')가
    # '헤딩 미검출'로 잘못 분류된다(초판이 그랬다).
    headings = [_text(el) for el in root.iter()
                if _tag(el) in ("SPAN", "P") and _text(el)
                and len(_text(el)) <= 30 and any(k in _text(el) for k in _ORDER_HEADING_KW)]
    subs = find_order_subsections(root)
    rows = []
    for _h, unit, grid in subs:
        rows.extend(map_order_table(grid, default_unit=unit))
    if rows:
        t["수주:행있음"] += 1
    elif subs:
        t["수주:헤딩·표있는데 행0"] += 1
        # 0행의 이유를 **표 안을 보고** 가른다. 원문 드릴로 확인된 3 가지다:
        #   ① 표가 비어 있다(전부 '-') = 해당사항 없음을 표로 쓴 것 → 정상
        #   ② 진행률형(계약잔액 열 없이 진행률%) → 설계상 보류(모듈 docstring 유형 3)
        #   ③ 창이 무관한 표를 잡았다(러닝헤더로 헤딩이 재출현) → 0행이라 무해
        flat = [" ".join(r) for _h, _u, g in subs for r in g[:3]]
        head = " ".join(flat)
        cells = [c for _h, _u, g in subs for r in g[1:] for c in r]
        digits = sum(1 for c in cells if any(ch.isdigit() for ch in c))
        if any(k in head for k in _BACKLOG_KW) and digits == 0:
            t["수주:0행 이유=표가 비어있음(해당없음)"] += 1
        elif "진행률" in head:
            t["수주:0행 이유=진행률형(설계상 보류)"] += 1
        elif any(k in head for k in _BACKLOG_KW):
            t["★수주:0행 이유=잔고열 있는데 실패"] += 1
            if len(samples["order_realfail"]) < 30:
                samples["order_realfail"].append(
                    (rcept, subs[0][0], [c[:14] for r in subs[0][2][:2] for c in r][:14]))
        else:
            t["수주:0행 이유=무관한 표(창 오검출)"] += 1
        if len(samples["order_norow"]) < 30:
            samples["order_norow"].append(
                (rcept, subs[0][0], [c[:16] for c in (subs[0][2][0] if subs[0][2] else [])]))
    elif headings:
        t["수주:헤딩은 있는데 표없음(해당사항없음 등)"] += 1
        if len(samples["order_notable"]) < 30:
            samples["order_notable"].append((rcept, headings[:2]))
    elif has_word:
        t["수주:'수주' 글자만 있음(서술문·주석)"] += 1
        if len(samples["order_nohead"]) < 30:
            # 어떤 텍스트에 '수주' 가 있었나 — 헤딩 판정 실패인지 무관한 문장인지 가른다.
            hits = [_text(el)[:60] for el in root.iter()
                    if _tag(el) in ("SPAN", "P") and "수주" in (_text(el) or "")]
            samples["order_nohead"].append((rcept, hits[:3]))
    else:
        t["수주:원문에 '수주' 없음(정상)"] += 1

    # ── 생산능력/가동률 ─────────────────────────────────────────────────
    has_biz_word = bool(_BIZ_ANY_RE.search(full))
    bsubs = find_biz_subsections(root)
    brows = []
    for bt in bsubs:
        try:
            brows.extend(map_biz_table(bt, fiscal_year))
        except Exception:  # noqa: BLE001
            t["가동률:map 예외"] += 1
    if brows:
        t["가동률:행있음"] += 1
    elif bsubs:
        t["가동률:헤딩·표있는데 행0"] += 1
        if len(samples["biz_norow"]) < 30:
            g = bsubs[0].grid
            samples["biz_norow"].append((rcept, bsubs[0].metric,
                                         [c[:16] for c in (g[0] if g else [])]))
    elif any(_heading_metrics(_text(el) or "") for el in root.iter()
             if _tag(el) in ("SPAN", "P")):
        # 수주와 같은 함정: `find_biz_subsections` 는 헤딩 **뒤에 표가 있을 때만** 결과를
        # 만든다. '보안 특성상 기재를 생략합니다' 처럼 표가 없는 절을 '헤딩 미검출'로
        # 부르면 원인 진단이 틀린다.
        t["가동률:헤딩은 있는데 표없음(기재생략 등)"] += 1
    elif has_biz_word:
        t["가동률:글자만 있음(서술문)"] += 1
        # 헤딩 판정은 SPAN/P 만 본다(`find_biz_subsections`). 키워드를 가진 요소의 **태그**를
        # 세어 두면 "다른 태그에 있어서 못 봤다"인지 "서술문일 뿐"인지 가릴 수 있다.
        for el in root.iter():
            if _BIZ_ANY_RE.search(_text(el) or ""):
                t[f"가동률태그:{_tag(el)}"] += 1
        if len(samples["biz_nohead"]) < 30:
            hits = [_text(el)[:60] for el in root.iter()
                    if _tag(el) in ("SPAN", "P") and _BIZ_ANY_RE.search(_text(el) or "")]
            samples["biz_nohead"].append((rcept, hits[:3]))
    else:
        t["가동률:원문에 관련 표기 없음(정상)"] += 1


def dump_grid(root, fiscal_year: int) -> None:
    """수주/가동률 창의 표 그리드를 그대로 찍는다 — 0행의 원인을 원문에서 짚기 위한 창구."""
    for heading, unit, grid in find_order_subsections(root):
        rows = map_order_table(grid, default_unit=unit)
        print(f"\n=== [수주] {heading!r} unit={unit!r} → 산출 {len(rows)} 행")
        for r in grid[:14]:
            print("   " + " | ".join(c[:18] for c in r))
        if len(grid) > 14:
            print(f"   … 그 외 {len(grid)-14} 행")
        for r in rows[:5]:
            print(f"   → {r}")
    for bt in find_biz_subsections(root):
        try:
            rows = map_biz_table(bt, fiscal_year)
        except Exception as e:  # noqa: BLE001
            rows = f"예외 {type(e).__name__}: {e}"
        print(f"\n=== [가동률] metric={bt.metric} → 산출 "
              f"{len(rows) if isinstance(rows, list) else rows}")
        for r in bt.grid[:12]:
            print("   " + " | ".join(c[:18] for c in r))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--rcept")
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--dump-grid", action="store_true",
                    help="--rcept 와 함께: 수주/가동률 창의 **표 그리드 전체**를 찍는다. "
                         "0행의 원인은 헤더 두 단·열 키워드처럼 표 안을 봐야 보인다")
    args = ap.parse_args()

    with get_session() as s:
        rows = list(s.execute(
            text(TARGETS_SQL.format(rcept_clause="AND f.rcept_no = :r" if args.rcept else "")),
            {"r": args.rcept} if args.rcept else {}).fetchall())
    if not args.rcept:
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing  (사업보고서만이 아니라 분·반기 포함)", flush=True)

    t: Counter[str] = Counter()
    samples = {"order_norow": [], "order_nohead": [], "order_notable": [],
               "order_realfail": [], "biz_norow": [], "biz_nohead": []}
    t0 = time.time()
    for i, f in enumerate(rows, 1):
        if i % 20 == 0:
            print(f"  … {i}/{len(rows)} ({(time.time()-t0)/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            t["파일없음"] += 1
            continue
        try:
            root = _load_root(p)
            if root is None:
                t["파싱실패"] += 1
                continue
            if args.dump_grid:
                dump_grid(root, f.fiscal_year)
                return 0
            scan(root, t, samples, f.rcept_no, f.fiscal_year)
            t["filing"] += 1
        except Exception as e:  # noqa: BLE001
            t["스캔실패"] += 1
            if t["스캔실패"] <= 3:
                print(f"  ! {f.rcept_no}: {type(e).__name__}: {e}")

    n = max(t["filing"], 1)
    print(f"\n=== 공백 원인 분해 (filing {n}, {time.time()-t0:.0f}s) ===")
    for key in sorted(t):
        if key.startswith(("수주:", "가동률:", "★수주:")):
            print(f"  {key:<38}{t[key]:>7,}{100*t[key]/n:>7.1f}%")
    tags = {k.split(":", 1)[1]: v for k, v in t.items() if k.startswith("가동률태그:")}
    if tags:
        print(f"  (헤딩 미검출 filing 에서 키워드를 가진 요소 태그: {tags})")

    print(f"\n  ※ 수주 열 키워드 = {_BACKLOG_KW} (이 열이 없으면 map_order_table 이 0행)")
    print(f"  ※ 수주 헤딩 키워드 = {_ORDER_HEADING_KW} (30자 이하 SPAN/P 만)")

    for key, title in (("order_realfail", "★잔고 열이 있는데 0행 — 진짜 추출 실패 후보"),
                       ("order_norow", "수주 헤딩·표는 있는데 0행 — 표의 첫 행(헤더)"),
                       ("order_notable", "수주 헤딩은 있는데 표 없음 — 그 헤딩"),
                       ("order_nohead", "'수주' 글자만 — 그 텍스트"),
                       ("biz_norow", "가동률 헤딩·표는 있는데 0행 — 표의 첫 행"),
                       ("biz_nohead", "가동률 글자는 있는데 헤딩 미검출 — 그 텍스트")):
        if samples[key]:
            print(f"\n--- {title} ---")
            for row in samples[key][: args.show]:
                print(f"  {row[0]}  {row[1:]}")

    for k in ("파일없음", "파싱실패", "스캔실패", "가동률:map 예외"):
        if t[k]:
            print(f"  {k}: {t[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
