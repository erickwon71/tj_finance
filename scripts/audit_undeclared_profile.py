"""미선언 버킷 성격 규명 — '단위 선언이 없어 폐기된 표' 11.2M 셀이 무엇인지 본다 (READ-ONLY).

왜 필요한가
-----------
`audit_unit_declarations.py` 전수 census(2026-07-30)에서 최대 버킷이 **미선언**이었다:
표 5,642,996 · 숫자셀 11,231,925 전량 폐기. 그런데 census 는 '선언이 없다'만 말하고
**그 표가 무엇인지**는 말하지 않는다. 셀/표 비율이 2.0 (금액단독은 13.1)이라 표제표·
서술표 추정이 있었으나 **확인되지 않았다** — 이 스크립트가 그 확인이다.

무엇을 재는가 — 미선언 표를 셀 내용으로 3분류
---------------------------------------------
    A 빈표      : 숫자셀 0                      → 잃을 것이 없다(표제·서술)
    B 소형      : 숫자셀 > 0 · 금액행 < 2       → 키-값·목차·서술 안의 수치
    C 데이터표  : 숫자셀 > 0 · 금액행 >= 2      → **실데이터 후보(진짜 유실)**

C 에 대해서만 추가로 재는 것:
  · 셀 내용 구성 — 콤마그룹 금액 / 무콤마 정수 / 소수·% (금액표인가 수량표인가)
  · **넓힌 창에서 단위 선언이 있는가** — `declared_unit` 은 직전형제·첫행·메타3칸만 본다.
    그 밖(형제 12칸·조상의 앞선 <P>)에 선언이 있으면 창을 넓혀 회수할 수 있는 것이고,
    아예 없으면 원문에 단위가 없는 것이다. 둘은 처방이 완전히 다르므로 구분해 센다.
  · 원문 그리드 표본 출력(`--show N`) — 집계로 끝내지 않는다(계층2 반복 교훈).

Usage
-----
    python scripts/audit_undeclared_profile.py --limit 60
    python scripts/audit_undeclared_profile.py --limit 60 --show 12
    python scripts/audit_undeclared_profile.py --rcept 20150817000851 --show 30
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
from fin2.extract.text import (_detect_body_statement_tables, _detect_fin_type,
                               _table_has_data_rows, inherited_declaration_text)
from parser.common.amount_normalizer import detect_unit_declaration
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles,
                                         table_direct_rows)
from parser.xml.table_extractor import _get_cells

# census 와 **같은** 선언 탐색·분류를 쓴다(다른 판정으로 다른 숫자를 만들지 않기 위해).
from scripts.audit_unit_declarations import (classify, count_numeric_cells,
                                            declaration_text)

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015 {rcept_clause}
    ORDER BY f.rcept_no
"""

# 콤마 3자리 그룹 금액('1,234' · '(1,234)'). DART 금액 표기의 표준형.
_COMMA_AMOUNT = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+\)?$")
_BARE_INT = re.compile(r"^\(?-?\d{1,4}\)?$")
_DECIMAL = re.compile(r"^\(?-?[\d,]*\.\d+\)?%?$")
_PERCENTISH = re.compile(r"%$")


def cell_profile(tbl) -> Counter:
    """표의 숫자 셀을 표기 형태로 쪼갠다 — 금액표인지 수량·비율표인지 가르는 근거."""
    c: Counter[str] = Counter()
    for tr in table_direct_rows(tbl):
        for raw in _get_cells(tr):
            s = raw.strip().replace(" ", "").replace("　", "")
            if not s or not any(ch.isdigit() for ch in s):
                continue
            if _PERCENTISH.search(s):
                c["퍼센트표기"] += 1
            elif _COMMA_AMOUNT.match(s):
                c["콤마금액"] += 1
            elif _DECIMAL.match(s):
                c["소수"] += 1
            elif _BARE_INT.match(s):
                c["무콤마4자리이하"] += 1
            elif re.fullmatch(r"\(?-?\d{5,}\)?", s):
                c["무콤마5자리이상"] += 1
            else:
                c["기타"] += 1
    return c


# 새 항목·새 재무제표의 시작을 알리는 텍스트 — 여기까지 거슬러 올라가면 그 앞의 단위 선언은
# **남의 표 것**이다. 번호주석제목('8. 범주별 금융상품')·소항목('(1) …')·재무제표명이 경계.
_ITEM_BOUNDARY = re.compile(
    r"^(?:\d+[.)]\s|\(\d+\)|[가-하][.)]\s)"
    r"|재\s*무\s*상\s*태\s*표|손\s*익\s*계\s*산\s*서|현\s*금\s*흐\s*름\s*표"
    r"|자\s*본\s*변\s*동\s*표|재무제표\s*주석|연결재무제표")


def inherited_declaration(tbl, span: int = 12) -> str | None:
    """**같은 항목 안**에서 이 표를 관장하는 단위 선언을 찾는다(없으면 None).

    `declared_unit` 은 직전형제·첫행·메타3칸만 본다. 그래서 아래 실측 서식에서 두 번째
    데이터표가 선언을 잃는다 — 사이에 낀 데이터표가 '라벨있는 비메타'라 탐색이 멈춘다:

        <P> (1) … 범주별 금융상품의 내역은 다음과 같습니다.<당분기말>
        <TABLE> (단위: 천원)          ← 선언만 담은 표
        <TABLE> [자산 데이터표]        ← 직전형제가 선언표 → 단위 획득 O
        <P> (빈 요소)
        <TABLE> [부채 데이터표]        ← ★미선언으로 폐기(27~29 콤마금액 유실)

    항목 경계(`_ITEM_BOUNDARY`)를 만나면 즉시 멈춘다 — 그 앞의 선언은 남의 것이다
    (주주현황 표가 4형제 앞 '연결 재무상태표 … 단위:원' 을 주워오는 것을 이렇게 막는다).
    """
    prev = tbl.getprevious()
    for _ in range(span):
        if prev is None:
            return None
        t = " ".join("".join(prev.itertext()).split())
        d = detect_unit_declaration(t)
        if d is not None:
            return t[:120]
        if t and _ITEM_BOUNDARY.search(t[:40]):
            return None                     # 새 항목·재무제표 도달 → 남의 선언
        prev = prev.getprevious()
    return None


def wide_window_declaration(tbl, span: int = 12) -> str | None:
    """`declared_unit` 이 **보지 않는** 넓은 창에서 단위 선언을 찾는다.

    직전 형제 span 칸 + 조상(1단계)의 앞선 형제까지. 여기서 발견되면 '창을 넓히면 회수
    가능', 발견되지 않으면 '원문에 단위가 없다' 로 갈린다. 회수 가능 여부만 재고
    **적재에 쓰지는 않는다**(남의 표 단위를 주워오는 것은 금지된 추측이다).
    """
    prev = tbl.getprevious()
    for _ in range(span):
        if prev is None:
            break
        t = " ".join("".join(prev.itertext()).split())
        if detect_unit_declaration(t) is not None:
            return t[:120]
        prev = prev.getprevious()
    parent = tbl.getparent()
    if parent is not None:
        p = parent.getprevious()
        for _ in range(span):
            if p is None:
                break
            t = " ".join("".join(p.itertext()).split())
            if detect_unit_declaration(t) is not None:
                return t[:120]
            p = p.getprevious()
    return None


def sibling_chain(tbl, span: int = 4) -> list[str]:
    """표 직전 형제들의 텍스트(가까운 순). '넓힌 창의 선언'이 **이 표 것인지 남의 것인지**를
    눈으로 가르기 위한 것 — 집계만으로는 그 둘을 구분할 수 없다(초판이 그 함정에 빠졌다)."""
    out, prev = [], tbl.getprevious()
    for _ in range(span):
        if prev is None:
            break
        tag = prev.tag if isinstance(prev.tag, str) else "?"
        t = " ".join("".join(prev.itertext()).split())
        out.append(f"<{tag}> {t[:100]}" if t else f"<{tag}> (빈 요소)")
        prev = prev.getprevious()
    return out


def grid_preview(tbl, max_rows: int = 4, max_cols: int = 6) -> list[str]:
    out = []
    for tr in list(table_direct_rows(tbl))[:max_rows]:
        cells = [c.strip().replace("\n", " ")[:16] for c in _get_cells(tr)][:max_cols]
        out.append(" | ".join(cells))
    return out


def scan_filing(root, f, t: Counter, samples: list, titles: Counter,
                samples_missed: list) -> None:
    groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
    scoped: list[tuple[str, object, str]] = []
    for code, tables_with_unit in groups.items():
        for tb, _u, _x in tables_with_unit:
            scoped.append(("본문" if not code.startswith("SCE") else "SCE", tb, ""))
    sec_tables = assign_note_tables_with_titles(root)
    for kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
        for tb, title in sec_tables.get(kind, []):
            scoped.append(("주석", tb, title or ""))

    for scope, tb, title in scoped:
        cls, _toks = classify(declaration_text(tb))
        if cls != "미선언":
            continue
        cells = count_numeric_cells(tb)
        has_rows = bool(_table_has_data_rows(tb))
        bucket = "A_빈표" if cells == 0 else ("C_데이터표" if has_rows else "B_소형")
        t[f"표:{bucket}"] += 1
        t[f"셀:{bucket}"] += cells
        t[f"표:{scope}:{bucket}"] += 1
        if bucket != "C_데이터표":
            continue

        prof = cell_profile(tb)
        for k, v in prof.items():
            t[f"C셀형태:{k}"] += v
        wide = wide_window_declaration(tb)
        t["C:넓힌창에_선언있음" if wide else "C:넓힌창에도_없음"] += 1
        t[("C셀:넓힌창에_선언있음" if wide else "C셀:넓힌창에도_없음")] += cells
        # ★핵심 구분 — 항목 경계를 넘지 않는 선언(=이 표를 관장한다)이 있는가.
        inh = inherited_declaration(tb)
        t["C:항목내_선언있음" if inh else "C:항목내_선언없음"] += 1
        t[("C셀:항목내_선언있음" if inh else "C셀:항목내_선언없음")] += cells
        # 그 '항목 내 선언' 을 **어디서** 찾았는지로 다시 가른다 — 채택한 규칙(D1 안 ③)은
        # '선언 전용 표'에서만 상속하므로, 나머지는 규칙을 넓혀야만 회수된다.
        if inh:
            impl = inherited_declaration_text(tb)      # 실제 적재에 쓰이는 규칙(안 ③)
            key = "선언전용표" if impl else "텍스트요소_안의_선언"
            t[f"C:상속경로:{key}"] += 1
            t[f"C셀:상속경로:{key}"] += cells
            if not impl and len(samples_missed) < 60:
                # 측정은 '상속 가능'이라는데 구현은 못 받는 표 — **왜 못 받는지**는 형제
                # 사슬을 봐야 안다(집계로는 규칙을 더 넓혀야 하는지 판단할 수 없다).
                samples_missed.append((f.rcept_no, (inh or "")[:60], sibling_chain(tb, 5)))
        if title:
            titles[title.strip()[:50]] += 1
        if len(samples) < 400:
            samples.append({
                "rcept": f.rcept_no, "scope": scope, "title": title.strip()[:60],
                "cells": cells, "prof": prof, "wide": wide, "inh": inh,
                "grid": grid_preview(tb), "sibs": sibling_chain(tb),
            })


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--rcept")
    ap.add_argument("--show", type=int, default=8, help="C 버킷 원문 그리드 표본 수")
    args = ap.parse_args()

    with get_session() as session:
        rows = list(session.execute(
            text(TARGETS_SQL.format(rcept_clause="AND f.rcept_no = :r" if args.rcept else "")),
            {"r": args.rcept} if args.rcept else {},
        ).fetchall())
    if not args.rcept and args.limit:
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    t: Counter[str] = Counter()
    samples: list = []
    samples_missed: list = []
    titles: Counter[str] = Counter()
    t0 = time.time()
    for i, f in enumerate(rows, 1):
        if i % 20 == 0:
            print(f"  … {i}/{len(rows)}", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            t["파일없음"] += 1
            continue
        try:
            root = _parse_xml_file(p)
            if root is None:
                t["파싱실패"] += 1
                continue
            scan_filing(root, f, t, samples, titles, samples_missed)
        except Exception as e:  # noqa: BLE001
            t["스캔실패"] += 1
            if t["스캔실패"] <= 3:
                print(f"  ! {f.rcept_no}: {type(e).__name__}: {e}")
            continue
        t["filing"] += 1

    n = max(t["filing"], 1)
    print(f"\n=== 미선언 표 성격 (filing {n}, {time.time()-t0:.0f}s) ===")
    tot_t = sum(t[f"표:{b}"] for b in ("A_빈표", "B_소형", "C_데이터표"))
    tot_c = sum(t[f"셀:{b}"] for b in ("A_빈표", "B_소형", "C_데이터표"))
    print(f"미선언 표 {tot_t:,} · 숫자셀 {tot_c:,}   (filing 당 표 {tot_t/n:.0f})\n")
    print(f"{'버킷':<12}{'표':>9}{'셀':>10}{'표%':>7}{'셀%':>7}")
    for b in ("A_빈표", "B_소형", "C_데이터표"):
        tt, cc = t[f"표:{b}"], t[f"셀:{b}"]
        print(f"{b:<12}{tt:>9,}{cc:>10,}"
              f"{100*tt/max(tot_t,1):>7.1f}{100*cc/max(tot_c,1):>7.1f}")
    for b in ("A_빈표", "B_소형", "C_데이터표"):
        per = {s: t[f"표:{s}:{b}"] for s in ("본문", "SCE", "주석")}
        print(f"  {b} 스코프: " + " ".join(f"{k}={v:,}" for k, v in per.items()))

    print("\n--- C(데이터표) 셀 표기 구성 ---")
    ctot = sum(v for k, v in t.items() if k.startswith("C셀형태:"))
    for k, v in sorted(((k, v) for k, v in t.items() if k.startswith("C셀형태:")),
                       key=lambda x: -x[1]):
        print(f"  {k.split(':')[1]:<14}{v:>9,}  {100*v/max(ctot,1):>5.1f}%")

    print("\n--- C(데이터표) 단위 회수 가능성 ---")
    print(f"  ★항목 경계 안에 선언 있음 : 표 {t['C:항목내_선언있음']:,} "
          f"· 셀 {t['C셀:항목내_선언있음']:,}   ← 그 표를 관장하는 선언(상속 가능)")
    print(f"  항목 안에 선언 없음       : 표 {t['C:항목내_선언없음']:,} "
          f"· 셀 {t['C셀:항목내_선언없음']:,}   ← 추측 금지(value_won NULL 적재만)")
    print(f"  (참고) 경계 무시 넓은 창  : 표 {t['C:넓힌창에_선언있음']:,} "
          f"· 셀 {t['C셀:넓힌창에_선언있음']:,}   ← 남의 표 선언까지 포함, 채택 금지")
    print("\n--- 그 '항목 내 선언' 을 어디서 찾았나 (D1 규칙 선택의 근거) ---")
    for key, why in (("선언전용표", "채택된 규칙(안 ③) — 지금 실제로 상속한다"),
                     ("텍스트요소_안의_선언", "안 ②로 넓혀야만 회수된다(문단 안에 선언이 있다)")):
        print(f"  {key:<18} 표 {t[f'C:상속경로:{key}']:>6,} · 셀 {t[f'C셀:상속경로:{key}']:>8,}   ← {why}")

    if titles:
        print("\n--- C 표의 주석 표제 상위 15 ---")
        for ttl, c in titles.most_common(15):
            print(f"  {c:>5}  {ttl}")

    if args.show and samples_missed:
        print(f"\n--- 측정=상속가능 · 구현=미상속 인 표의 형제 사슬 {min(args.show, len(samples_missed))} ---")
        for rc, inh, sibs in samples_missed[: args.show]:
            print(f"\n  [{rc}] 측정이 찾은 선언: {inh!r}")
            for i, sb in enumerate(sibs, 1):
                print(f"    -{i}: {sb}")

    if args.show and samples:
        print(f"\n--- C 원문 그리드 표본 {min(args.show, len(samples))} ---")
        for s in samples[: args.show]:
            print(f"\n  [{s['rcept']}] {s['scope']} 셀{s['cells']} "
                  f"{'항목내선언=' + s['inh'][:60] if s['inh'] else '항목내 선언없음'}")
            if s["title"]:
                print(f"    표제: {s['title']}")
            print(f"    형태: {dict(s['prof'])}")
            for i, sib in enumerate(s["sibs"], 1):
                print(f"    직전형제-{i}: {sib}")
            for line in s["grid"]:
                print(f"    | {line}")

    for k in ("파일없음", "파싱실패", "스캔실패"):
        if t[k]:
            print(f"  {k}: {t[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
