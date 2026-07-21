"""계층2 검증 (3) — 자본변동표(SCE) 전용.

SCE 는 BS/IS/CF 와 컬럼 규약이 달라(열=자본 구성요소) 기존 검증기가 커버하지 못한다.
값·구조가 맞는지 **독립 근거 두 축**으로 확인한다:

  [A] 행 내부 정합 — 총계 열 == 구성요소 열들의 합  (**참고 지표**)
      열 라벨이 통째로 밀리면 즉시 깨지므로 정렬 회귀 감지에 유용하다. 다만 소계/구성요소를
      열 라벨 정규식으로 가르는 데 한계가 있어(회사마다 표기 상이) 잔여 불일치에는 검증기
      결함과 원문 편차가 섞인다 — 판정 근거로 쓰지 말 것.

  [B] BS 항목별 교차검증 — SCE 기말자본 행의 **각 자본 항목**이 같은 보고서 BS 와 일치하는가
      (**판정 지표**). 서로 다른 재무제표를 대조하므로 추출 정확성의 가장 강한 독립 증거다.

★ [B] 를 자본총계 하나가 아니라 **항목별**로 넓힌 이유 (2026-07-21 실측):
    쏠리드 2019 연결(r20200330002492)은 자본총계만 보면 PASS 였으나, 항목별로 보면
        이익잉여금    BS 26,038,777,444 ↔ SCE  2,603,877,744
        지배지분합계  BS 122,609,246,330 ↔ SCE 12,260,924,633
    두 셀 모두 **원문에서 마지막 자릿수가 잘려** 있었다(공시 작성 오류. 같은 XML 의 BS 는
    정상값이라 우리 파서 결함이 아님 — 파싱 경로가 동일하므로 결정적 반증).
    → 항목별 대조는 원문 품질 문제를 자동 검출한다. 계층3 DQ 플래그의 근거로 쓸 수 있다.

사용:
    python scripts/verify_sce.py --corp 00101220
    python scripts/verify_sce.py --sample 300
    python scripts/verify_sce.py --sample 300 --show 20
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
from fin2.extract.report_lines import extract_report_lines

_OPEN = re.compile(r"기초")
_CLOSE = re.compile(r"기말")
_TOTAL_COL = re.compile(r"자본\s*합계|자본총계|총\s*계")
# ⚠ 이 규칙을 `지배기업|지배지분|소유주` 로 넓히지 말 것 — 실측에서 [A] 가 95.7%→93.1% 로
#   **악화**했고 분모도 9,331→4,626 으로 반토막 났다(구성요소 열이 과도하게 소계로 분류돼
#   비교 가능한 행이 사라짐). 표기가 회사마다 달라 정규식 접근 자체에 한계가 있다.
_OWNERS_SUBTOTAL_COL = re.compile(r"지배기업.*합계|지배지분\s*합계|소유주.*합계")
_NCI_COL = re.compile(r"비지배")
_TOL = 0.001            # 상대오차 0.1% — 단위 반올림 흡수

# ── [B] 항목별 대조용 개념 사전 ────────────────────────────────────────────────
# 라벨 정규화 후 **정확일치**만 인정한다(부분일치는 '보통주자본금' 같은 하위항목을 잘못 집는다).
_CONCEPTS: dict[str, set[str]] = {
    "자본금":       {"자본금"},
    "이익잉여금":   {"이익잉여금", "이익잉여금결손금", "결손금", "미처분이익잉여금"},
    "비지배지분":   {"비지배지분"},
    # BS 는 '지배기업의 소유주에게 귀속되는 자본', SCE 열은 같은 말에 '합계'가 붙는 경우가
    # 많다 → 아래 _concept_key 가 접미사 '합계'를 떼고 한 번 더 시도한다.
    "지배지분":     {"지배기업의소유주에게귀속되는자본", "지배기업의소유주에게귀속되는지분",
                     "지배기업소유주지분", "지배기업소유주귀속자본", "지배지분",
                     "지배기업의소유주지분", "지배주주지분"},
    "자본총계":     {"자본총계", "자본합계", "총자본"},
}
_PAREN = re.compile(r"[（(][^)）]*[)）]")


def _norm(s: str | None) -> str:
    return (s or "").replace(" ", "").replace("　", "")


def _concept_key(label: str | None) -> str | None:
    """라벨 → 개념 키. 주석참조 `(주1,17)` 등 괄호구간을 제거한 뒤 **정확일치**.

    부분일치를 쓰지 않는 이유: '보통주자본금'·'우선주자본금' 같은 하위항목이 '자본금' 으로
    잘못 잡혀 BS 쪽 값이 모호해진다(_bs_concepts 가 서로 다른 값 다수 → 보류 처리).

    1차 실패 시 **접미사 '합계' 를 떼고 한 번 더** 시도한다 — BS 는 '지배기업의 소유주에게
    귀속되는 자본', SCE 열 라벨은 같은 개념에 '합계'가 붙는 표기 차이가 흔하다.
    ('자본합계' 처럼 접미사를 떼면 뜻이 달라지는 것은 1차 정확일치에서 이미 잡힌다.)
    """
    n = _norm(_PAREN.sub("", label or ""))
    for cand in (n, n[:-2] if n.endswith("합계") else None):
        if not cand:
            continue
        for concept, names in _CONCEPTS.items():
            if cand in names:
                return concept
    return None


def _leaf(col_label: str | None) -> str:
    """다단 열 라벨('자본>지배기업…>이익잉여금')의 마지막 단."""
    return (col_label or "").split(">")[-1]


def _anomaly_kind(bs: int, sce: int) -> str:
    """원문 오기 유형 추정 — 계층3 DQ 플래그 후보."""
    if bs == -sce:
        return "SIGN"                      # 부호 반전
    a, b = str(abs(bs)), str(abs(sce))
    if len(a) == len(b) + 1 and a.startswith(b):
        return "DIGIT_TRUNC"               # 끝자리 유실(쏠리드 유형)
    if len(b) == len(a) + 1 and b.startswith(a):
        return "DIGIT_EXTRA"
    return "OTHER"


def _classify_cols(col_labels: dict[int, str]) -> tuple[int | None, list[int], list[int]]:
    """반환 (총계열, 소계열들, 구성요소열들).

    ★ 판정 순서가 중요하다: '비지배지분' 은 '지배지분' 을 부분문자열로 포함하므로 **NCI 를 먼저**
      확인해야 한다. 뒤집으면 비지배지분이 소계로 분류돼 총계 합에서 빠지고, 연결 SCE 가 전부
      거짓 불일치를 낸다.
    """
    total: int | None = None
    subtotals: list[int] = []
    for c, lbl in col_labels.items():
        n = _norm(lbl)
        if _NCI_COL.search(n):
            continue                                        # 비지배지분 = 구성요소(총계의 일부)
        if _TOTAL_COL.search(n) and not _OWNERS_SUBTOTAL_COL.search(n):
            total = c if total is None else max(total, c)
        elif _OWNERS_SUBTOTAL_COL.search(n):
            subtotals.append(c)
    comps = [c for c in col_labels if c != total and c not in subtotals]
    return total, subtotals, comps


def _bs_concepts(lines, basis: str) -> dict[str, int | None]:
    """BS 당기(col_index=0) 에서 개념별 값. 같은 개념이 **서로 다른 값**으로 여러 번 나오면
    None(모호 → 대조 보류). 추측해서 하나를 고르지 않는다."""
    buckets: dict[str, set[int]] = defaultdict(set)
    for l in lines:
        if l.statement != "BS" or l.basis != basis or l.col_index != 0:
            continue
        if l.value_won is None:
            continue
        k = _concept_key(l.label_raw)
        if k:
            buckets[k].add(l.value_won)
    return {k: (next(iter(v)) if len(v) == 1 else None) for k, v in buckets.items()}


def _check_one(lines, basis: str):
    sce = [l for l in lines if l.statement == "SCE" and l.basis == basis]
    if not sce:
        return None

    col_labels: dict[int, str] = {}
    for l in sce:
        if l.col_label and l.col_index not in col_labels:
            col_labels[l.col_index] = l.col_label
    n_cols_seen = len({l.col_index for l in sce})

    by_row: dict[tuple, dict[int, int]] = defaultdict(dict)
    for l in sce:
        by_row[(l.table_seq, l.row_order, l.label_raw)][l.col_index] = l.value_won

    total_c, sub_cs, comps = _classify_cols(col_labels)

    # ── [A] 행 내부 정합 ────────────────────────────────────────────────
    a_ok = a_bad = 0
    a_examples = []
    if total_c is not None and comps:
        for (_, _, lbl), vals in by_row.items():
            if total_c not in vals:
                continue
            parts = [vals[c] for c in comps if c in vals]
            if len(parts) < 2:
                continue
            expect, got = sum(parts), vals[total_c]
            if expect == got or (got and abs(expect - got) <= abs(got) * _TOL):
                a_ok += 1
            else:
                a_bad += 1
                if len(a_examples) < 3:
                    a_examples.append((lbl, expect, got))

    labels = [lbl for (_, _, lbl) in by_row]
    has_open = any(_OPEN.search(_norm(l)) for l in labels)
    has_close = any(_CLOSE.search(_norm(l)) for l in labels)

    # ── [B] BS 항목별 교차검증 ──────────────────────────────────────────
    b_res: dict[str, tuple[str, int | None, int | None]] = {}
    close_rows = [(k, v) for k, v in by_row.items() if _CLOSE.search(_norm(k[2]))]
    if close_rows:
        _, close_vals = max(close_rows, key=lambda kv: (kv[0][0], kv[0][1]))
        bs = _bs_concepts(lines, basis)
        # SCE 열 → 개념
        col_concept: dict[str, int] = {}
        for c, lbl in col_labels.items():
            k = _concept_key(_leaf(lbl))
            if k and k not in col_concept:       # 같은 개념 열이 둘이면 첫 번째만(드묾)
                col_concept[k] = c
        for concept in _CONCEPTS:
            c = col_concept.get(concept)
            sce_v = close_vals.get(c) if c is not None else None
            bs_v = bs.get(concept)
            if sce_v is None or bs_v is None:
                b_res[concept] = ("SKIP", bs_v, sce_v)
            elif sce_v == bs_v or abs(sce_v - bs_v) <= abs(bs_v or 1) * _TOL:
                b_res[concept] = ("PASS", bs_v, sce_v)
            else:
                b_res[concept] = ("FAIL", bs_v, sce_v)

    return {
        "n_rows": len(sce), "n_cols": n_cols_seen, "n_labeled": len(col_labels),
        "has_open": has_open, "has_close": has_close,
        "a_ok": a_ok, "a_bad": a_bad, "a_examples": a_examples,
        "b": b_res,
    }


def _fetch(session, args):
    where = ["dt.status='completed'", "dt.file_type='xml'", "dt.file_path IS NOT NULL",
             "f.fiscal_period='FY'", "f.report_nm NOT LIKE '%정정%'", "f.fiscal_year >= 2015"]
    params = {}
    if args.corp:
        where.append("f.corp_code=:c"); params["c"] = args.corp
    sql = f"""SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period,
                     c.corp_name, c.stock_code
              FROM download_tasks dt JOIN filings f USING(rcept_no)
              JOIN corporations c ON c.corp_code = f.corp_code
              WHERE {' AND '.join(where)}"""
    rows = session.execute(text(sql), params).fetchall()
    if args.sample and len(rows) > args.sample:
        rows = random.Random(42).sample(rows, args.sample)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corp")
    ap.add_argument("--sample", type=int)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    with get_session() as session:
        targets = _fetch(session, args)
    if not targets:
        print("대상 없음"); return

    n_rep = n_sec = 0
    cov = Counter()
    a_ok = a_bad = 0
    b_stat: dict[str, Counter] = defaultdict(Counter)
    kinds = Counter()
    fails = []

    for t in targets:
        if not Path(t.file_path).exists():
            continue
        try:
            lines = extract_report_lines(
                t.file_path, rcept_no=t.rcept_no, corp_code=t.corp_code,
                report_fiscal_year=t.fiscal_year, report_fiscal_period=t.fiscal_period)
        except Exception as e:
            fails.append((t, "", f"ERR {type(e).__name__}: {e}"))
            continue
        n_rep += 1
        for basis in ("consolidated", "separate"):
            res = _check_one(lines, basis)
            if res is None:
                continue
            n_sec += 1
            cov["기초행 보유"] += res["has_open"]
            cov["기말행 보유"] += res["has_close"]
            cov["col_label 전열 채움"] += (res["n_labeled"] >= res["n_cols"])
            a_ok += res["a_ok"]; a_bad += res["a_bad"]
            for concept, (st, bs_v, sce_v) in res["b"].items():
                b_stat[concept][st] += 1
                if st == "FAIL":
                    kind = _anomaly_kind(bs_v, sce_v)
                    kinds[kind] += 1
                    fails.append((t, basis,
                                  f"{concept} [{kind}] BS {bs_v:,} ↔ SCE {sce_v:,}"))

    print(f"\n=== SCE 검증: 보고서 {n_rep}건 · SCE 섹션 {n_sec}개 ===\n")
    print("[커버리지]")
    for k in ("기초행 보유", "기말행 보유", "col_label 전열 채움"):
        print(f"    {k:22s} {cov[k]:5,} / {n_sec:5,}  ({100*cov[k]/max(n_sec,1):5.1f}%)")

    tot_a = a_ok + a_bad
    print(f"\n[A] 행 내부 정합(참고)  {a_ok:,} / {tot_a:,} ({100*a_ok/max(tot_a,1):.1f}%)")

    print(f"\n[B] BS 항목별 교차검증 (판정 지표)")
    print(f"    {'항목':<12}{'PASS':>8}{'FAIL':>8}{'SKIP':>8}   PASS율(판정가능분)")
    for concept in _CONCEPTS:
        c = b_stat[concept]
        dec = c["PASS"] + c["FAIL"]
        rate = f"{100*c['PASS']/dec:5.1f}%" if dec else "    -"
        print(f"    {concept:<12}{c['PASS']:>8,}{c['FAIL']:>8,}{c['SKIP']:>8,}   {rate}")

    if kinds:
        print(f"\n[B-FAIL 유형 분류]  (원문 오기 후보 — 계층3 DQ 플래그 근거)")
        for k, c in kinds.most_common():
            desc = {"DIGIT_TRUNC": "끝자리 유실(쏠리드 유형)", "DIGIT_EXTRA": "자릿수 과다",
                    "SIGN": "부호 반전", "OTHER": "기타"}.get(k, k)
            print(f"    {k:12s} {c:5,}   {desc}")

    if fails:
        print(f"\n[불일치 상위 {min(len(fails), args.show)} / 총 {len(fails)}]")
        for t, basis, msg in fails[: args.show]:
            print(f"  ✗ {t.corp_name}({t.stock_code}) {t.fiscal_year} {basis}")
            print(f"      {msg}")
            print(f"      https://dart.fss.or.kr/dsaf001/main.do?rcpNo={t.rcept_no}")


if __name__ == "__main__":
    main()
