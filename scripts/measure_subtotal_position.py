"""계층2 소계 판정 설계용 측정 — 구조적 위치(P/S/F) × 텍스트신호 × 산술검산 3중 교차.

배경(2026-07-21 논의): report_lines 의 is_subtotal 을 구 체인 `_is_subtotal()`(부분문자열,
키워드에 맨 '계' 포함 → 관계기업투자·설계용역 등 오탐)에서 분리해 계층2 전용으로 새로 만든다.
그 전에 "소계는 섹션의 세로 마지막 줄인가"라는 가설을 **실측**한다.

## 위치 분류 (내 raw_indent vs 다음 행 raw_indent — 배타적·전수)
    P (parent/선행형) : 다음 행이 더 깊음  → 자식을 거느림.  예 `자산 288,712` 밑에 유동/비유동
    S (suffix/후행형) : 다음 행이 더 얕음 or 표 끝 → 형제 run 의 마지막.  예 `자산총계`
    F (flat/평면형)   : 다음 행이 같은 깊이 → 형제 중간.  예 IS 의 `매출총이익`

## 산술 검산 = 정답(ground truth)
    P: 값 == 직계 자식들의 합
    S: 값 == 같은 부모 밑 같은 깊이의 **선행 형제들** 합 (자기 제외)
    F: 값 == run 시작 이후 선행 형제들의 누적합 (IS 누적소계 형태)
검산 통과 = TRUE_SUBTOTAL. 이게 위치·텍스트와 무관한 독립 기준이므로 정답으로 쓴다.

## ★ 검산기의 알려진 한계 (실측으로 확인, 2026-07-21)
평면 손익계산서는 **부호 규약이 보고서마다 다르다**. 같은 기업 같은 보고서 안에서도:
    연결 IS  매출원가 = +8,052,891,781,467  → 매출총이익 = 매출액 − 매출원가 (뺄셈 필요)
    별도 IS  매출원가 = -167,580,220,293    → 매출총이익 = 매출액 + 매출원가 (단순 합)
게다가 `법인세비용차감전순이익 = 영업이익 +금융수익 −금융비용 +기타이익 −기타손실 +지분법손익`
처럼 **꼬리 안에서 부호가 섞인다**. 각 항목의 부호를 알아야 검산이 되는데 그 부호 판정이 곧
계정 의미 판단(=계층3 몫)이다. 부분집합 부호탐색으로 억지로 맞추면 우연일치가 정답을 오염시킨다.
→ **평면 IS(F 위치)의 NO 판정에는 '진짜 비소계'와 '검산불가'가 섞여 있다.** IS 의 F 관련
   수치는 하한선으로만 읽을 것. BS/CF 및 P 위치 수치는 이 한계의 영향을 받지 않는다.

## 출력
    1) TRUE_SUBTOTAL 의 위치 분포  → "마지막 줄 100%" 가설의 직접 답
    2) 위치별 정밀도(그 위치면 진짜 소계일 확률) → S 단독 규칙의 오탐률
    3) 텍스트 규칙 2종(loose=구 체인 / strict=접미사) × 위치 교차표 → 규칙 조합 설계 근거
    4) statement(BS/IS/CF) 별 분해 → 서식군마다 답이 다른지

사용:
    python scripts/measure_subtotal_position.py --sample 300
    python scripts/measure_subtotal_position.py --corp 00101220
    python scripts/measure_subtotal_position.py --sample 300 --dump-misses 40
"""
from __future__ import annotations

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.table_extractor import extract_rows, _is_subtotal as loose_is_subtotal
from fin2.extract.report_lines import (
    _parse_xml_file,
    _detect_fin_type,
    _detect_body_statement_tables,
    _detect_period_layout,
    _interim_cumulative_cols,
    _assign_section_paths,
    _SECTION_META,
)

# 제안 규칙: 접미사 기반 strict 매칭(맨 '계' 부분문자열 금지 — 관계/설계/통계 오탐 차단).
_STRICT_SUFFIX = re.compile(r"(총계|합계|계|총액|소계)$")
# IS 누적소계처럼 접미사가 없는 확립된 소계 라벨(정확일치).
_STRICT_EXACT = frozenset([
    "매출총이익", "매출총손실", "영업이익", "영업손실",
    "당기순이익", "당기순손실", "법인세비용차감전순이익", "법인세비용차감전순손실",
    "총포괄손익", "당기총포괄이익", "반기순이익", "분기순이익",
])


def strict_is_subtotal(label: str) -> bool:
    """계층2 후보 텍스트 규칙 — 접미사 + 확립된 정확일치."""
    s = (label or "").replace(" ", "").replace("　", "")
    return bool(_STRICT_SUFFIX.search(s)) or s in _STRICT_EXACT


def _first_amount(row):
    """당기 금액 — 표마다 선행 공란 수가 달라 '첫 비어있지 않은 금액'을 당기로 본다.

    _emit_section_lines 의 lead-skip 과 같은 취지. 측정 목적상 이 근사로 충분하되,
    다열(보험/증권) 표는 명세/소계가 섞이므로 호출측에서 제외한다(아래 multicol 스킵).
    """
    for a in row.amounts:
        if a is not None:
            return a
    return None


def _child_path(row, my_path: str | None) -> str:
    return f"{my_path}>{row.account_name}" if my_path else row.account_name


def _classify_positions(rows) -> dict[int, str]:
    """다음 행과의 raw_indent 비교로 P/S/F 배타 분류."""
    out: dict[int, str] = {}
    for i, row in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt is None or nxt.raw_indent < row.raw_indent:
            out[id(row)] = "S"
        elif nxt.raw_indent > row.raw_indent:
            out[id(row)] = "P"
        else:
            out[id(row)] = "F"
    return out


def _arith_check(rows, paths, positions) -> dict[int, str]:
    """산술 검산 → {id(row): 'EXACT'|'NEAR'|'NO'|'NA'}.

    NA = 자기 값 없음 or 비교 대상 없음(검산 불가 — 정답 집합에서 제외).
    NEAR = 상대오차 0.1% 이내(단위 반올림·표시 절사 흡수). EXACT 와 NEAR 를 TRUE 로 본다.
    """
    verdict: dict[int, str] = {}
    # 자식 인덱싱: path 별 (raw_indent, row) 목록
    by_path: dict[str | None, list] = defaultdict(list)
    for row in rows:
        by_path[paths.get(id(row))].append(row)

    for i, row in enumerate(rows):
        mine = _first_amount(row)
        if mine is None:
            verdict[id(row)] = "NA"
            continue
        pos = positions[id(row)]
        my_path = paths.get(id(row))

        if pos == "P":
            kids = by_path.get(_child_path(row, my_path), [])
            # 직계 자식 중 가장 얕은 깊이만(손자가 같은 path 를 갖지는 않지만 방어).
            vals = [_first_amount(k) for k in kids]
            vals = [v for v in vals if v is not None]
            candidates = [sum(vals)] if vals else []
        else:
            # 같은 부모·같은 깊이의 **선행** 형제들(가까운 순 → 먼 순으로 뒤집어 문서 순서 복원).
            sibs = []
            for prev in rows[:i][::-1]:
                if paths.get(id(prev)) != my_path:
                    if prev.raw_indent < row.raw_indent:
                        break          # 부모 경계 도달
                    continue           # 다른 가지(자식 등) 는 건너뜀
                if prev.raw_indent != row.raw_indent:
                    continue
                sibs.append(prev)
            sibs.reverse()
            vals = [v for v in (_first_amount(s) for s in sibs) if v is not None]

            # ★ 손익계산서 소계는 '합'이 아니라 **누진 가감**이다:
            #     매출총이익 = 매출액 − 매출원가        (뺄셈)
            #     영업이익   = 매출총이익 − 판관비      (직전 소계 기준, 앞선 항목 재합산 금지)
            #     총포괄손익 = 당기순이익 + 기타포괄손익
            #   그래서 (a)전체합 만 보면 IS 소계가 전부 NO 로 찍혀 정답집합이 오염된다.
            #   직전에 TRUE 로 확정된 형제(anchor) 이후 구간만 ±로 맞춰본다.
            #   앵커는 **직전 하나가 아니라 앞선 모든 확정소계**를 후보로 둔다:
            #     총포괄손익 = 당기순이익 + 기타포괄손익  ← 앵커가 두 칸 앞(사이에 기타포괄손익)
            candidates = []
            if vals:
                candidates.append(sum(vals))                       # (a) 단순 전체합
                candidates.append(vals[0] - sum(vals[1:]))         # (c) 선두 − 나머지(뺄셈형)
            for j, s in enumerate(sibs):
                if verdict.get(id(s)) not in ("EXACT", "NEAR"):
                    continue
                anchor_val = _first_amount(s)
                if anchor_val is None:
                    continue
                tail = [v for v in (_first_amount(x) for x in sibs[j + 1:]) if v is not None]
                candidates.append(anchor_val + sum(tail))          # (b+) 확정소계 + 이후
                candidates.append(anchor_val - sum(tail))          # (b−) 확정소계 − 이후

        if not candidates:
            verdict[id(row)] = "NA"
            continue
        if any(c == mine for c in candidates):
            verdict[id(row)] = "EXACT"
        elif mine and any(abs(c - mine) <= abs(mine) * 0.001 for c in candidates):
            verdict[id(row)] = "NEAR"
        else:
            verdict[id(row)] = "NO"
    return verdict


def _walk_report(file_path: str, fy: int, period: str):
    """한 보고서의 본문 표들을 순회하며 (section_code, rows, paths, positions, verdict) 방출.

    ★ section_code(IS_C/IS_S) 를 그대로 준다 — statement(IS) 로 뭉개면 연결/별도가 한 덩어리가
    되어 '표 2개'가 2표식(손익+포괄 분리)인지 연결+별도인지 구분 못 한다(실측 중 오경보 원인).
    statement 가 필요하면 호출측에서 `.split("_")[0]`."""
    root = _parse_xml_file(Path(file_path))
    if root is None:
        return
    groups = _detect_body_statement_tables(root, _detect_fin_type(root))
    for section_code, tables_with_unit in groups.items():
        statement = section_code.split("_")[0]
        interim_flow = statement in ("IS", "CF") and period in ("H1", "Q1", "Q3")
        for table, unit, _ in tables_with_unit:
            if unit is None:
                continue
            cum_map = _interim_cumulative_cols(table) if interim_flow else None
            n_periods, multicol = (3, False) if cum_map else _detect_period_layout(table)
            if multicol:
                continue   # 보험/증권 다열: 명세/소계 혼재 → 산술검산 신뢰 불가, 측정 제외
            n_cols = max(cum_map) + 1 if cum_map else 3
            rows = [r for r in extract_rows(table, multiplier=unit, num_cols=n_cols,
                                            direct_only=True, skip_junk=False)
                    if r.account_name and "주당" not in r.account_name]
            if len(rows) < 3:
                continue
            paths = _assign_section_paths(rows, statement)
            positions = _classify_positions(rows)
            verdict = _arith_check(rows, paths, positions)
            yield section_code, rows, paths, positions, verdict


def _inspect(file_path: str, fy: int, period: str, want_stmt: str | None) -> None:
    """한 보고서의 표를 위치·검산 판정과 함께 그대로 덤프(검산기 자체를 눈으로 검증하는 용도)."""
    for section_code, rows, paths, positions, verdict in _walk_report(file_path, fy, period):
        statement = section_code.split("_")[0]
        if want_stmt and statement != want_stmt:
            continue
        print(f"\n--- {section_code} (rows={len(rows)}) ---")
        for row in rows:
            amt = _first_amount(row)
            print(f"  ind{row.raw_indent:<2} {positions[id(row)]} {verdict[id(row)]:<5} "
                  f"{'　' * row.raw_indent}{row.account_name[:34]:<36} "
                  f"{amt if amt is not None else '':>20} | path={paths.get(id(row))}")


def _fetch(session, args):
    where = ["dt.status='completed'", "dt.file_type='xml'", "dt.file_path IS NOT NULL",
             "f.fiscal_period='FY'", "f.report_nm NOT LIKE '%정정%'"]
    params = {}
    if args.corp:
        where.append("f.corp_code=:c"); params["c"] = args.corp
    sql = f"""SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
              FROM download_tasks dt JOIN filings f USING(rcept_no)
              WHERE {' AND '.join(where)}"""
    rows = session.execute(text(sql), params).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)
    return rows


def _pct(a, b):
    return f"{100*a/b:5.1f}%" if b else "    -"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--dump-misses", type=int, default=0,
                    help="TRUE 인데 strict 텍스트규칙이 놓친 라벨 상위 N 출력")
    ap.add_argument("--roles", type=int, default=0, help="(statement,위치)별 정답 라벨 상위 N")
    ap.add_argument("--inspect", help="이 rcept_no 의 행을 판정과 함께 덤프(검산기 눈검증)")
    ap.add_argument("--stmt", choices=["BS", "IS", "CF"], help="--inspect 시 statement 한정")
    args = ap.parse_args()

    with get_session() as session:
        if args.inspect:
            sql = """SELECT dt.file_path, f.fiscal_year, f.fiscal_period
                     FROM download_tasks dt JOIN filings f USING(rcept_no)
                     WHERE dt.rcept_no=:r AND dt.file_type='xml' AND dt.status='completed'"""
            r = session.execute(text(sql), {"r": args.inspect}).fetchone()
            if not r:
                print("해당 rcept 없음"); return
            _inspect(r.file_path, r.fiscal_year, r.fiscal_period, args.stmt)
            return
        targets = _fetch(session, args)
    if not targets:
        print("대상 없음"); return

    pos_of_true = Counter()                    # 정답 소계의 위치 분포
    pos_total = Counter()                      # 위치별 검산가능(NA 제외) 모수
    pos_true = Counter()                       # 위치별 정답 수
    cross = Counter()                          # (pos, loose, strict, is_true)
    by_stmt = defaultdict(Counter)             # statement 별 정답 위치 분포
    role_labels = defaultdict(Counter)         # (statement, 위치) 별 정답 라벨 — 구조 성격 규명용
    missed_labels = Counter()                  # strict 가 놓친 정답 라벨
    false_labels = Counter()                   # strict 오탐 라벨
    n_reports = n_rows = 0

    for t in targets:
        if not Path(t.file_path).exists():
            continue
        try:
            walk = list(_walk_report(t.file_path, t.fiscal_year, t.fiscal_period))
        except Exception as e:
            print(f"  ! ERR {t.rcept_no}: {type(e).__name__}: {e}")
            continue
        if not walk:
            continue
        n_reports += 1
        for section_code, rows, paths, positions, verdict in walk:
            statement = section_code.split("_")[0]
            for row in rows:
                v = verdict[id(row)]
                if v == "NA":
                    continue
                n_rows += 1
                pos = positions[id(row)]
                is_true = v in ("EXACT", "NEAR")
                lo = loose_is_subtotal(row.account_name)
                st = strict_is_subtotal(row.account_name)
                pos_total[pos] += 1
                cross[(pos, lo, st, is_true)] += 1
                if is_true:
                    pos_true[pos] += 1
                    pos_of_true[pos] += 1
                    by_stmt[statement][pos] += 1
                    role_labels[(statement, pos)][row.account_name] += 1
                    if not st:
                        missed_labels[row.account_name] += 1
                elif st:
                    false_labels[row.account_name] += 1

    tot_true = sum(pos_of_true.values())
    print(f"\n=== 소계 위치 분포 측정 ===")
    print(f"보고서 {n_reports}건 · 검산가능 행 {n_rows:,} · 정답(TRUE_SUBTOTAL) {tot_true:,}\n")

    print("[1] 정답 소계의 구조적 위치 분포  ← '마지막 줄 100%' 가설의 답")
    for pos, name in (("S", "S 후행형(섹션 마지막)"), ("P", "P 선행형(자식 거느림)"),
                      ("F", "F 평면형(형제 중간)")):
        print(f"    {name:24s} {pos_of_true[pos]:7,}  {_pct(pos_of_true[pos], tot_true)}")

    print("\n[2] 위치별 정밀도(그 위치인 행이 실제 소계일 확률) ← 위치 단독 규칙의 오탐률")
    for pos in ("S", "P", "F"):
        print(f"    {pos}: {pos_true[pos]:7,} / {pos_total[pos]:7,} = {_pct(pos_true[pos], pos_total[pos])}")

    print("\n[3] 텍스트 규칙 성능 (검산 정답 기준)")
    for rule_idx, rule_name in ((1, "loose(구 체인 _is_subtotal)"), (2, "strict(접미사+정확일치)")):
        tp = sum(c for (p, lo, st, tr), c in cross.items() if (lo if rule_idx == 1 else st) and tr)
        fp = sum(c for (p, lo, st, tr), c in cross.items() if (lo if rule_idx == 1 else st) and not tr)
        fn = sum(c for (p, lo, st, tr), c in cross.items() if not (lo if rule_idx == 1 else st) and tr)
        prec = _pct(tp, tp + fp); rec = _pct(tp, tp + fn)
        print(f"    {rule_name:30s} 정밀도 {prec}  재현율 {rec}  (TP {tp:,} FP {fp:,} FN {fn:,})")

    print("\n[4] 조합 규칙: 위치 P 무조건 + (S·F 는 strict 텍스트)")
    tp = sum(c for (p, lo, st, tr), c in cross.items() if (p == "P" or st) and tr)
    fp = sum(c for (p, lo, st, tr), c in cross.items() if (p == "P" or st) and not tr)
    fn = sum(c for (p, lo, st, tr), c in cross.items() if not (p == "P" or st) and tr)
    print(f"    정밀도 {_pct(tp, tp+fp)}  재현율 {_pct(tp, tp+fn)}  (TP {tp:,} FP {fp:,} FN {fn:,})")

    print("\n[5] statement 별 정답 위치 분포")
    for stmt in sorted(by_stmt):
        c = by_stmt[stmt]; s = sum(c.values())
        print(f"    {stmt:4s} (n={s:6,})  S {_pct(c['S'], s)}  P {_pct(c['P'], s)}  F {_pct(c['F'], s)}")

    if args.roles:
        print(f"\n[R] (statement, 위치) 별 정답 라벨 상위 {args.roles} — 그 위치가 무엇인지 규명")
        for key in sorted(role_labels):
            stmt, pos = key
            print(f"  {stmt} / {pos}:")
            for lbl, c in role_labels[key].most_common(args.roles):
                print(f"      {c:6,}  {lbl[:50]}")

    if args.dump_misses:
        print(f"\n[6] strict 가 놓친 정답 라벨 상위 {args.dump_misses}")
        for lbl, c in missed_labels.most_common(args.dump_misses):
            print(f"    {c:6,}  {lbl}")
        print(f"\n[7] strict 오탐(텍스트는 소계인데 검산 실패) 상위 {args.dump_misses}")
        for lbl, c in false_labels.most_common(args.dump_misses):
            print(f"    {c:6,}  {lbl}")


if __name__ == "__main__":
    main()
