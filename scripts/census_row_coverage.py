#!/usr/bin/env python
"""원문 행 단위 결측 전수 센서스 — `fin2.audit.row_coverage` 를 큐 전체에 돌린다.

## 왜 별도 스크립트인가

`layer2_review.py` 의 검산은 **그 1건**만 본다. 결함은 보통 회사/서식 단위로 무리지어
나타나므로(R149 = 금융지주 19개사 324건), 고치기 전에 "같은 모양이 어디에 몇 건인가"를
먼저 알아야 한다. 캠페인이 106,448건을 한 건씩 훑는 동안 기다릴 수는 없다.

## 전수는 한 번에 돌리지 않는다

건당 XML 파싱 2회(추출 + 감사)라 1~3초가 걸린다 → 106k건이면 수십 시간이다. 그래서
**재개 가능**하게 만들었다: 결과를 JSONL 로 append 하고, 다시 실행하면 이미 처리한
rcept_no 는 건너뛴다. 사용자 지침("장시간 명령 실행 금지")대로 `--limit` 으로 끊어서
여러 번 돌리는 것을 전제로 한다.

## 사용법

    python scripts/census_row_coverage.py --limit 300 --breadth   # ★계열 탐색은 이쪽
    python scripts/census_row_coverage.py --limit 300             # 시총순 깊게
    python scripts/census_row_coverage.py --limit 300 --corp 00382199
    python scripts/census_row_coverage.py --report                # 누적 결과 집계만

★처음에는 `--breadth`(회사별 1건씩) 로 돌려라. 기본 순서는 시총순이라 삼성전자 110건을
다 훑고 나서야 다음 회사로 가는데, 결함은 회사/서식 단위로 무리지으므로 회사를 많이
보는 쪽이 계열 발견에 압도적으로 유리하다(실측: 시총 상위 296건 발화 0건).

출력: `docs/qa/row_coverage_census.jsonl`(건당 1줄) + `--report` 집계.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.audit import row_coverage
from fin2.extract.report_lines import extract_report_lines

_OUT = Path(__file__).resolve().parents[1] / "docs/qa/row_coverage_census.jsonl"

# `layer2_review.py` 의 원문 경로 해석을 그대로 쓴다(같은 규칙을 두 번 쓰지 않는다).
_L2R = Path(__file__).resolve().parent / "layer2_review.py"


def _resolve_source_fn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_l2r", _L2R)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._resolve_source


_TARGETS_SQL = """
    SELECT rcept_no, corp_code, corp_name, corp_rank, fiscal_year, fiscal_period
    FROM layer2_review_queue
    -- ★`source_kind` 로 거르지 않는다(2026-09-20) — 그 값은 `_reload_one` 이 한 번
    -- 돌고 나서야 채워지므로, pending 건은 대부분 NULL 이다. 그걸로 필터를 걸면
    -- 센서스가 **이미 검토된 건만** 보게 돼(실측: 대상이 76건으로 줄었다) 전수라는
    -- 목적이 무너진다. 원문 유무는 실행 시점에 `_resolve_source` 가 판정한다.
    WHERE fiscal_year >= 2015
      {corp_filter}
    ORDER BY corp_rank NULLS LAST, corp_code, fiscal_year DESC, rcept_no
"""

# ★넓게 도는 모드 — 회사별 **가장 오래된** 필링 1건씩.
#   기본 순서(시총순 → 회사 안에서 최신순)는 삼성전자 110건을 다 훑고 나서야 다음
#   회사로 간다. 결함은 **회사/서식 단위**로 무리지으므로, 계열을 빨리 찾으려면 회사를
#   많이 보는 쪽이 압도적으로 낫다. 오래된 쪽을 고르는 이유는 실측에서 발화가 2015~2017
#   서식에 몰렸기 때문이다(최신 40개사 0건 vs 최고령 40개사 2건).
_BREADTH_SQL = """
    SELECT DISTINCT ON (corp_code)
           rcept_no, corp_code, corp_name, corp_rank, fiscal_year, fiscal_period
    FROM layer2_review_queue
    -- ★`source_kind` 로 거르지 않는다(2026-09-20) — 그 값은 `_reload_one` 이 한 번
    -- 돌고 나서야 채워지므로, pending 건은 대부분 NULL 이다. 그걸로 필터를 걸면
    -- 센서스가 **이미 검토된 건만** 보게 돼(실측: 대상이 76건으로 줄었다) 전수라는
    -- 목적이 무너진다. 원문 유무는 실행 시점에 `_resolve_source` 가 판정한다.
    WHERE fiscal_year >= 2015
      {corp_filter}
    ORDER BY corp_code, fiscal_year ASC, rcept_no
"""


def load_done() -> set[str]:
    if not _OUT.exists():
        return set()
    done = set()
    with _OUT.open() as fh:
        for line in fh:
            try:
                done.add(json.loads(line)["rcept_no"])
            except (ValueError, KeyError):
                continue
    return done


def report() -> None:
    if not _OUT.exists():
        print("아직 센서스 결과가 없습니다.")
        return
    n = 0
    hit_files = 0
    by_corp = Counter()
    by_label = Counter()
    by_scope = Counter()
    errors = Counter()
    with _OUT.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            n += 1
            if rec.get("error"):
                errors[rec["error"][:60]] += 1
                continue
            miss = rec.get("missing") or []
            if not miss:
                continue
            hit_files += 1
            by_corp[rec["corp_name"]] += 1
            for m in miss:
                by_label[m["label"]] += 1
                by_scope[f'{m["basis"][:3]}/{m["statement"]}'] += 1
    print(f"센서스 처리 {n:,}건 · 발화 {hit_files:,}건"
          f"{f' ({hit_files / n:.1%})' if n else ''} · 오류 {sum(errors.values()):,}건")
    print(f"\n회사별 발화(상위 20): {by_corp.most_common(20)}")
    print(f"\n재무제표별 결측행: {by_scope.most_common()}")
    print(f"\n라벨별 결측행(상위 25): {by_label.most_common(25)}")
    if errors:
        print(f"\n오류 유형: {errors.most_common(5)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=200, help="이번 실행에서 처리할 건수")
    ap.add_argument("--corp", help="corp_code 지정 시 그 회사만")
    ap.add_argument("--breadth", action="store_true",
                    help="회사별 가장 오래된 1건씩 넓게 훑는다(결함 계열 탐색용). "
                         "기본은 시총순으로 회사별 전 필링을 깊게 훑는다.")
    ap.add_argument("--report", action="store_true", help="집계만 출력하고 종료")
    args = ap.parse_args()

    if args.report:
        report()
        return

    resolve_source = _resolve_source_fn()
    done = load_done()
    print(f"이미 처리: {len(done):,}건 — 건너뜁니다.")

    sql = (_BREADTH_SQL if args.breadth else _TARGETS_SQL).format(
        corp_filter="AND corp_code = :corp" if args.corp else "")
    params = {"corp": args.corp} if args.corp else {}

    processed = hits = 0
    with get_session() as session, _OUT.open("a") as out:
        targets = session.execute(text(sql), params).mappings().all()
        for it in targets:
            if processed >= args.limit:
                break
            if it["rcept_no"] in done:
                continue
            rec = {"rcept_no": it["rcept_no"], "corp_code": it["corp_code"],
                   "corp_name": it["corp_name"],
                   "period": f'{it["fiscal_year"]}{it["fiscal_period"]}'}
            kind, path = resolve_source(session, it["rcept_no"])
            if kind != "xml" or not path:
                rec["error"] = f"원문 없음({kind})"
            else:
                try:
                    lines = extract_report_lines(
                        path, rcept_no=it["rcept_no"], corp_code=it["corp_code"],
                        report_fiscal_year=it["fiscal_year"],
                        report_fiscal_period=it["fiscal_period"])
                    missing = row_coverage.find_missing_rows(path, lines)
                    rec["missing"] = [
                        {"basis": m.basis, "statement": m.statement,
                         "label": m.label, "amounts": list(m.amounts)}
                        for m in missing]
                    if missing:
                        hits += 1
                except Exception as exc:               # noqa: BLE001 — 한 건 실패로 멈추지 않는다
                    rec["error"] = f"{type(exc).__name__}: {exc}"
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            processed += 1
            if processed % 25 == 0:
                print(f"  ... {processed}/{args.limit} (발화 {hits})", flush=True)

    print(f"\n이번 실행: {processed:,}건 처리, 발화 {hits:,}건 → {_OUT}")
    print("이어서 돌리려면 같은 명령을 다시 실행하세요(처리한 건은 건너뜁니다).")


if __name__ == "__main__":
    main()
