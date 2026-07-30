"""단위 선언 전수 census — 표가 선언한 단위를 원문 그대로 보고 4분류한다 (READ-ONLY, 샤딩).

왜 별 도구인가 — 기존 두 도구의 **공통 사각**
---------------------------------------------
`layer2_fidelity_full.py`(역방향)는 "DB 값이 원문 숫자에서 파생됐나"만 본다. 이자율 `5` 가
`5,000,000원` 으로 적재돼도 `5` 는 원문에 있으므로 **통과**한다.
`layer2_forward_cells.py`(정방향)는 **적재 대상 표 안**의 셀만 센다. 단위 미선언으로 표째
폐기된 것은 스코프 밖이라 애초에 세지 않는다.
⇒ 단위 판정이 틀렸을 때의 두 결과(**표째 유실**·**열 오염**)를 둘 다 못 본다. 이 도구가 그것만 본다.

무엇을 재는가
-------------
`declared_unit()` 이 **실제로 들여다보는 위치**에서 선언 텍스트를 찾아 토큰으로 쪼갠 뒤:

  금액단독  : 토큰이 전부 금액(억원/백만원/만원/천원/원)      → 현재 정상 적재
  비금액단독: 금액 토큰이 없다(주·%·명·톤·시간·매·USD…)       → **표째 폐기**
  혼합      : 금액 + 비금액이 섞였다('백만원, %')              → **열 오염 위험**
  미선언    : 위치들에서 '단위' 를 못 찾았다                   → 표째 폐기(의도)

그리고 `_UNIT_DECL_RE` 가 **금액 토큰이 선두가 아닐 때 매칭에 실패**하는 것을 따로 센다
('단위 : 매, 백만원' → 백만원을 선언했는데도 폐기).

★ 방법론 — 이 도구를 만들며 고친 것
-----------------------------------
초안은 원문 전체를 `grep '단위[:：]'` 해서 세었다. 그건 **어떤 표도 참조하지 않는 선언까지**
집계한다(다른 섹션·목차·서술문). 계층2 의 반복된 교훈("휴리스틱 대신 실제 코드 경로를 계측")
그대로여서, `declared_unit` 과 **같은 위치 탐색**을 재현하도록 다시 만들었다. 두 방식의 차이는
`--compare-grep` 으로 직접 확인할 수 있다.

Usage
-----
    python scripts/audit_unit_declarations.py --limit 40           # 표본
    python scripts/audit_unit_declarations.py --shard 0/6          # 전수(샤드)
    python scripts/audit_unit_declarations.py --year 2024 --limit 0
    python scripts/audit_unit_declarations.py --contamination-only  # DB 쪽 오염만(빠름)
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.text import (_STMT_TITLE, _detect_body_statement_tables,
                               _detect_fin_type, _is_metadata_only,
                               _table_has_data_rows, declared_unit)
from parser.common.amount_normalizer import (UNIT_MULTIPLIERS,
                                             detect_unit_declaration)
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles,
                                         table_direct_rows)
from parser.xml.table_extractor import _get_cells

MONEY = set(UNIT_MULTIPLIERS)                      # 억원 백만원 만원 천원 원

# ★금액 토큰 판정은 **부분문자열 금지**. `any('원' in tok)` 로 하면 '원화'·'각1단위'·'직원'
#   까지 금액으로 세어 분류가 오염된다(초판에서 실제로 그랬다). 토큰이 금액 단위로 **끝나야**
#   하고 그 앞은 배수 표기(억/백만/만/천) 또는 없음이어야 한다.
_MONEY_TOKEN = re.compile(r"^\(?\s*(?:약\s*)?(?:억|백만|만|천|십억|조)?원\s*\)?[.,]?$")

# '단위' 뒤의 선언 본문. 괄호·따옴표로 닫히거나 줄이 끝날 때까지.
_DECL_BODY = re.compile(r"단위\s*[:：]?\s*(.{0,60}?)(?=[)）\]]|$)")

# 토큰 분리자 — '백만원, 천USD' · '원/주' · '주 · %' 등.
_TOK_SPLIT = re.compile(r"[,，/·|;、\s]+")

# 숫자 셀 판정(금액 여부는 보지 않는다 — 이 도구는 '숫자가 몇 개 있었나'만 센다).
_NUMERIC_CELL = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?%?$")

# 비금액 열임을 원문이 말해주는 표지. 오염 판정에 쓴다(추측이 아니라 열 헤더 원문 근거).
_NON_MONEY_COL = re.compile(r"%|비율|이자율|할인율|지분율|주당|수량|주수|배수|USD|EUR|JPY|외화")

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
      {year_clause}{rcept_clause}
    ORDER BY f.rcept_no
"""


def declaration_text(tbl) -> str | None:
    """`declared_unit()` 이 들여다보는 **바로 그 위치들**에서 '단위' 선언 텍스트를 찾는다.

    위치 순서를 `fin2/extract/text.py:declared_unit` 과 일치시킨다:
      ① 직전 형제(표제)  ② 표 자신의 첫 행  ③ 메타 형제 최대 3칸(재무제표명에서 정지)
    금액 토큰 매칭 여부와 **무관하게** 텍스트를 돌려주는 것이 요점 — 그래야 '선언은 있었는데
    우리가 못 읽은' 경우를 셀 수 있다.
    """
    prev0 = tbl.getprevious()
    if prev0 is not None:
        t = " ".join("".join(prev0.itertext()).split())
        if "단위" in t:
            return t
    first_tr = next(iter(table_direct_rows(tbl)), None)
    if first_tr is not None:
        t = " ".join("".join(first_tr.itertext()).split())
        if "단위" in t:
            return t
    prev = tbl.getprevious()
    for _ in range(3):
        if prev is None:
            break
        t = " ".join("".join(prev.itertext()).split())
        if any(p.search(t) for p, _ in _STMT_TITLE):
            break
        if "단위" in t:
            return t
        if not _is_metadata_only(t):
            break
        prev = prev.getprevious()
    return None


def classify(decl: str | None) -> tuple[str, list[str]]:
    """선언 텍스트 → (분류, 토큰 목록). 토큰은 원문 표기를 그대로 둔다(판단 금지)."""
    if not decl:
        return "미선언", []
    m = _DECL_BODY.search(decl)
    if not m:
        return "미선언", []
    body = m.group(1).strip(" .)]}")
    toks = [t for t in _TOK_SPLIT.split(body) if t]
    if not toks:
        return "미선언", []
    money = [t for t in toks if _MONEY_TOKEN.match(t)]
    non_money = [t for t in toks if t not in money]
    has_money = money
    if has_money and non_money:
        return "혼합", toks
    if has_money:
        return "금액단독", toks
    return "비금액단독", toks


def count_numeric_cells(tbl) -> int:
    """표의 숫자 셀 수. 유실·오염 규모를 '표 수' 가 아니라 **셀 수** 로 말하기 위한 것."""
    n = 0
    for tr in table_direct_rows(tbl):
        for c in _get_cells(tr):
            s = c.strip().replace(" ", "").replace("　", "")
            if s and _NUMERIC_CELL.match(s) and any(ch.isdigit() for ch in s):
                n += 1
    return n


def scan_filing(root, f, t: Counter, samples: dict) -> None:
    """filing 하나의 표를 전부 분류한다. 본문 + SCE + 주석 — 적재 경로와 같은 스코프."""
    groups = _detect_body_statement_tables(root, _detect_fin_type(root), include_sce=True)
    scoped: list[tuple[str, object]] = []
    for code, tables_with_unit in groups.items():
        for tb, _u, _x in tables_with_unit:
            scoped.append(("본문" if not code.startswith("SCE") else "SCE", tb))
    sec_tables = assign_note_tables_with_titles(root)
    for kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
        for tb, _title in sec_tables.get(kind, []):
            scoped.append(("주석", tb))

    for scope, tb in scoped:
        decl = declaration_text(tb)
        cls, toks = classify(decl)
        cells = count_numeric_cells(tb)
        loaded = declared_unit(tb) is not None
        has_rows = _table_has_data_rows(tb)

        t[f"표:{cls}"] += 1
        t[f"셀:{cls}"] += cells
        t[f"표:{scope}:{cls}"] += 1

        if loaded:
            t[f"적재:{cls}"] += 1
            t[f"적재셀:{cls}"] += cells
        else:
            t[f"폐기:{cls}"] += 1
            t[f"폐기셀:{cls}"] += cells
            if not has_rows:
                t[f"폐기(데이터행없음):{cls}"] += 1

        # ★핵심 지표 — 선언은 금액을 포함하는데 우리가 못 읽어서 폐기된 표.
        #   숫자 셀이 0 인 표는 폐기돼도 잃는 것이 없으므로 헤드라인에서 제외한다
        #   (표제표·빈 표가 섞여 규모가 부풀던 문제).
        if cls in ("금액단독", "혼합") and not loaded and cells > 0:
            t["★금액선언인데_폐기:표"] += 1
            t["★금액선언인데_폐기:셀"] += cells
            if len(samples["missed"]) < 25:
                samples["missed"].append((f.rcept_no, scope, decl[:90] if decl else "", cells))
        if cls == "비금액단독" and cells > 0:
            if len(samples["nonmoney"]) < 25:
                samples["nonmoney"].append((f.rcept_no, scope, decl[:90] if decl else "", cells))
        if cls == "혼합" and loaded:
            t["★혼합_적재:표"] += 1
            t["★혼합_적재:셀"] += cells
            if len(samples["mixed"]) < 25:
                samples["mixed"].append((f.rcept_no, scope, decl[:90] if decl else "", cells))
        if decl:
            samples["decl_freq"][" ".join(toks)[:40]] += 1

        # --rcept 드릴: 한 filing 의 모든 표를 원문 선언과 함께 나열한다. 구형 EUC-KR
        # 보고서는 grep 으로 열 수 없으므로(바이트가 UTF-8 이 아니다) 확인은 반드시
        # 추출기와 같은 파싱 경로로 해야 한다 — 이 드릴이 그 창구다.
        if samples.get("drill"):
            samples["drill_rows"].append(
                (scope, cls, cells, loaded, (decl or "")[:160], toks[:8]))


def report_contamination(session) -> None:
    """DB 쪽 오염 실측 — 비금액 열인데 `value_won` 이 채워진 행.

    XML 재파싱 없이 SQL 로만 잰다(`col_label` 이 원문 열 헤더를 전사해 두었기 때문).
    `%`·`이자율`·`지분율`·`USD` 같은 열에 원 단위 금액이 들어 있으면 그건 단위 오적용이다.
    """
    print("\n=== DB 오염 실측 (note_lines.col_label 근거) ===", flush=True)
    q = text("""
        SELECT count(*) AS rows,
               count(DISTINCT rcept_no) AS filings,
               count(*) FILTER (WHERE abs(value_won) >= 1000000) AS big
        FROM note_lines
        WHERE value_won IS NOT NULL AND col_label ~ :pat
    """)
    r = session.execute(q, {"pat": _NON_MONEY_COL.pattern}).fetchone()
    print(f"  비금액 열 표지가 있는데 value_won 채워짐: {r.rows:,} 행 "
          f"({r.filings:,} filing) · 그중 100만원 이상 {r.big:,}")
    q2 = text("""
        SELECT col_label, count(*) n, max(abs(value_won)) mx
        FROM note_lines
        WHERE value_won IS NOT NULL AND col_label ~ :pat
        GROUP BY 1 ORDER BY 2 DESC LIMIT 15
    """)
    print("  상위 열 헤더:")
    for row in session.execute(q2, {"pat": _NON_MONEY_COL.pattern}):
        print(f"    {row.n:>9,}  max={row.mx:>22,}  {row.col_label[:60]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--limit", type=int, default=40, help="0 = 전수")
    ap.add_argument("--shard", help="a/n")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--contamination-only", action="store_true",
                    help="XML 스캔 없이 DB 오염 실측만(수 초)")
    ap.add_argument("--rcept", help="단건 드릴 — 그 filing 의 표별 선언을 전부 나열")
    args = ap.parse_args()

    if args.contamination_only:
        with get_session() as s:
            report_contamination(s)
        return 0

    t: Counter[str] = Counter()
    samples: dict = {"missed": [], "nonmoney": [], "mixed": [],
                     "decl_freq": Counter(),
                     "drill": bool(args.rcept), "drill_rows": []}
    t0 = time.time()

    with get_session() as session:
        rows = list(session.execute(
            text(TARGETS_SQL.format(
                year_clause="AND f.fiscal_year = :y" if args.year else "",
                rcept_clause=" AND f.rcept_no = :r" if args.rcept else "")),
            {k: v for k, v in (("y", args.year), ("r", args.rcept)) if v},
        ).fetchall())
    if args.shard:
        a, n = (int(x) for x in args.shard.split("/"))
        rows = [r for i, r in enumerate(rows) if i % n == a]
    elif args.rcept:
        pass                                       # 단건 드릴은 그대로
    elif args.limit:
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    for i, f in enumerate(rows, 1):
        if i % 200 == 0:
            el = time.time() - t0
            print(f"  … {i}/{len(rows)} ({el/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            t["파일없음"] += 1
            continue
        try:
            # ★추출기와 같은 파싱 경로(sanitize + 인코딩 판정). 직접 fromstring 금지.
            root = _parse_xml_file(p)
            if root is None:
                t["파싱실패"] += 1
                continue
            scan_filing(root, f, t, samples)
        except Exception as e:  # noqa: BLE001
            t["스캔실패"] += 1
            if t["스캔실패"] <= 3:
                print(f"  ! {f.rcept_no}: {type(e).__name__}: {e}")
            continue
        t["filing"] += 1

    if args.rcept:
        print(f"\n=== 드릴 {args.rcept} — 표 {len(samples['drill_rows'])} ===")
        print(f"{'스코프':<6}{'분류':<11}{'셀':>5} {'적재':<5} 선언 / 토큰")
        for scope, cls, cells, loaded, decl, toks in samples["drill_rows"]:
            if cells == 0 and cls == "금액단독":
                continue                            # 빈 표는 지면만 차지한다
            print(f"{scope:<6}{cls:<11}{cells:>5} {'O' if loaded else 'X':<5} "
                  f"{decl}\n{'':>29}→ {toks}")
        return 0

    el = time.time() - t0
    n = max(t["filing"], 1)
    print(f"\n=== 단위 선언 census (filing {n}, {el:.0f}s, {el/n:.2f}s/filing) ===")
    total_t = sum(t[f"표:{c}"] for c in ("금액단독", "비금액단독", "혼합", "미선언"))
    total_c = sum(t[f"셀:{c}"] for c in ("금액단독", "비금액단독", "혼합", "미선언"))
    print(f"\n표 {total_t:,} · 숫자셀 {total_c:,}\n")
    print(f"{'분류':<12}{'표':>10}{'셀':>14}{'적재표':>10}{'폐기표':>10}{'폐기셀':>14}")
    for c in ("금액단독", "혼합", "비금액단독", "미선언"):
        print(f"{c:<12}{t[f'표:{c}']:>10,}{t[f'셀:{c}']:>14,}"
              f"{t[f'적재:{c}']:>10,}{t[f'폐기:{c}']:>10,}{t[f'폐기셀:{c}']:>14,}")

    print(f"\n★ 금액을 선언했는데 폐기된 표 : {t['★금액선언인데_폐기:표']:,} "
          f"(숫자셀 {t['★금액선언인데_폐기:셀']:,})   ← 0 이어야 한다")
    print(f"★ 혼합 단위로 적재된 표       : {t['★혼합_적재:표']:,} "
          f"(숫자셀 {t['★혼합_적재:셀']:,})   ← 열 오염 위험")
    print(f"  비금액단독 폐기 셀           : {t['폐기셀:비금액단독']:,} "
          f"← 현재 DB 에 전혀 없는 정보")

    for key, title in (("missed", "금액 선언인데 폐기"),
                       ("mixed", "혼합 단위로 적재"),
                       ("nonmoney", "비금액 단독(전량 폐기)")):
        if samples[key]:
            print(f"\n--- {title} 사례 ---")
            for rc, scope, decl, cells in samples[key][:8]:
                print(f"  {rc} {scope:<4} 셀{cells:>5}  '{decl}'")

    if samples["decl_freq"]:
        print("\n--- 선언 토큰 빈도 상위 25 ---")
        for tok, cnt in samples["decl_freq"].most_common(25):
            print(f"  {cnt:>8,}  {tok}")

    for k in ("파일없음", "파싱실패", "스캔실패"):
        if t[k]:
            print(f"  {k}: {t[k]}")

    with get_session() as s:
        report_contamination(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
