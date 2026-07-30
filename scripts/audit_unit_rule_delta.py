"""단위 선언 규칙 **구 vs 신** 차분 — F1 이 표를 새로 얻었는지, 잃었는지 센다 (READ-ONLY).

왜 필요한가
-----------
F1 은 `detect_unit_declaration` 의 판정 규칙을 두 곳에서 바꿨다:
  ① 금액 토큰이 '단위' 직후가 아니어도 인정('(단위 : 주, 천원)') · 자간 공백 인정('천 원')
  ② `declaration_text` 가 **가장 가까운 유효 선언에서 멈춘다**(종전에는 금액 선언이 아니면
     다음 위치로 넘어갔다 — 표제가 '(단위: 주)' 인 표가 뒤 메타 형제의 '천원' 을 주워 올 수 있었다)

①은 얻는 방향, ②는 **잃을 수도 있는** 방향이다. 그래서 구 규칙을 이 파일 안에 그대로 재현해
같은 문서에서 표마다 두 판정을 비교한다. 합격 기준:

    유실(구=배수 있음 → 신=None)          : 0 에 가깝고, 남으면 **사례를 원문으로 설명**할 수 있어야
    배수 변경(구≠신, 둘 다 값)             : 0 이어야(같은 표의 단위가 달라지면 값이 ×1000 틀어진다)
    신규 획득(구=None → 신=배수)           : 클수록 좋다(2.63M 셀 유실의 회수분)

Usage
-----
    python scripts/audit_unit_rule_delta.py --limit 120 --show 10
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.text import (_STMT_TITLE, _detect_body_statement_tables,
                               _detect_fin_type, _is_metadata_only,
                               _table_has_data_rows, declared_unit)
from parser.common.amount_normalizer import UNIT_MULTIPLIERS
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles,
                                         table_direct_rows)

# ── 구 규칙 재현(2026-07-30 이전 코드 그대로) ─────────────────────────────
_OLD_UNIT_DECL_RE = re.compile(r'단위\s*[:：]?\s*\(?\s*(억원|백만원|만원|천원|원)')


def old_detect(text_: str) -> Optional[int]:
    if not text_ or "단위" not in text_:
        return None
    normalized = text_.replace('：', ':').replace('　', ' ')
    m = _OLD_UNIT_DECL_RE.search(normalized)
    return UNIT_MULTIPLIERS[m.group(1)] if m else None


def old_declared_unit(tbl) -> Optional[int]:
    prev0 = tbl.getprevious()
    if prev0 is not None:
        d = old_detect(" ".join("".join(prev0.itertext()).split()))
        if d is not None:
            return d
    first_tr = next(iter(table_direct_rows(tbl)), None)
    if first_tr is not None:
        d = old_detect("".join(first_tr.itertext()))
        if d is not None:
            return d
    prev = tbl.getprevious()
    for _ in range(3):
        if prev is None:
            break
        txt = " ".join("".join(prev.itertext()).split())
        if any(p.search(txt) for p, _ in _STMT_TITLE):
            break
        d = old_detect(txt)
        if d is not None:
            return d
        if not _is_metadata_only(txt):
            break
        prev = prev.getprevious()
    return None


TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
    ORDER BY f.rcept_no
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260731)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    with get_session() as s:
        rows = list(s.execute(text(TARGETS_SQL)).fetchall())
    random.Random(args.seed).shuffle(rows)
    rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    t: Counter[str] = Counter()
    lost, changed, gained = [], [], []
    t0 = time.time()
    for i, f in enumerate(rows, 1):
        if i % 20 == 0:
            print(f"  … {i}/{len(rows)} ({(time.time()-t0)/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            t["파일없음"] += 1
            continue
        try:
            root = _parse_xml_file(p)
            if root is None:
                t["파싱실패"] += 1
                continue
        except Exception:  # noqa: BLE001
            t["파싱실패"] += 1
            continue
        t["filing"] += 1

        scoped: list[tuple[str, object]] = []
        for code, tw in _detect_body_statement_tables(
                root, _detect_fin_type(root), include_sce=True).items():
            for tb, _u, _x in tw:
                scoped.append(("SCE" if code.startswith("SCE") else "본문", tb))
        sec = assign_note_tables_with_titles(root)
        for kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
            for tb, _title in sec.get(kind, []):
                scoped.append(("주석", tb))

        for scope, tb in scoped:
            o, nu = old_declared_unit(tb), declared_unit(tb)
            has_rows = bool(_table_has_data_rows(tb))
            t[f"표:{scope}"] += 1
            if o == nu:
                t["동일"] += 1
                continue
            if o is not None and nu is None:
                t[f"유실:{scope}"] += 1
                if has_rows:
                    t["★유실(데이터행있음)"] += 1
                    if len(lost) < 40:
                        lost.append((f.rcept_no, scope, o, _ctx(tb)))
            elif o is None and nu is not None:
                t[f"획득:{scope}"] += 1
                if has_rows:
                    t["★획득(데이터행있음)"] += 1
                    if len(gained) < 40:
                        gained.append((f.rcept_no, scope, nu, _ctx(tb)))
            else:
                t[f"배수변경:{scope}"] += 1
                if len(changed) < 40:
                    changed.append((f.rcept_no, scope, f"{o}→{nu}", _ctx(tb)))

    n = max(t["filing"], 1)
    print(f"\n=== 구·신 단위 규칙 차분 (filing {n}, {time.time()-t0:.0f}s) ===")
    total = sum(t[f"표:{s}"] for s in ("본문", "SCE", "주석"))
    print(f"표 {total:,} · 판정 동일 {t['동일']:,} ({100*t['동일']/max(total,1):.2f}%)")
    for kind in ("유실", "획득", "배수변경"):
        parts = " ".join(f"{s}={t[f'{kind}:{s}']:,}" for s in ("본문", "SCE", "주석"))
        tot = sum(t[f"{kind}:{s}"] for s in ("본문", "SCE", "주석"))
        print(f"  {kind:<6}{tot:>8,}   ({parts})")
    print(f"\n  ★유실(데이터행 있는 표) {t['★유실(데이터행있음)']:,}   ← 0 에 가까워야 한다")
    print(f"  ★획득(데이터행 있는 표) {t['★획득(데이터행있음)']:,}   ← 회수분")
    print(f"  ★배수변경 {sum(t[f'배수변경:{s}'] for s in ('본문','SCE','주석')):,}   ← 0 이어야 한다")

    for title, arr in (("유실 사례(구=배수 → 신=None)", lost),
                       ("배수변경 사례", changed),
                       ("획득 사례(구=None → 신=배수)", gained)):
        if arr:
            print(f"\n--- {title} ---")
            for rc, scope, val, ctx in arr[: args.show]:
                print(f"  {rc} {scope:<4} {val}  {ctx}")

    for k in ("파일없음", "파싱실패"):
        if t[k]:
            print(f"  {k}: {t[k]}")
    return 0


def _ctx(tb) -> str:
    """그 표의 앞 형제·첫 행 텍스트 요약 — 판정이 갈린 이유를 눈으로 보기 위한 근거."""
    prev = tb.getprevious()
    a = " ".join("".join(prev.itertext()).split())[:70] if prev is not None else ""
    first_tr = next(iter(table_direct_rows(tb)), None)
    b = " ".join("".join(first_tr.itertext()).split())[:50] if first_tr is not None else ""
    return f"prev={a!r} first_tr={b!r}"


if __name__ == "__main__":
    raise SystemExit(main())
