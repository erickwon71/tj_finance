#!/usr/bin/env python
"""기간 연속성 대조 — R85/86/88류(값은 있는데 다른 기간 컬럼과 뒤바뀜) 트리아지 도구.

설계: `docs/plans/layer2_review_staged_screening_design_2026-09-11.md` §5-1(기법 9).
검증(2026-09-11): git worktree로 R85 재현 → 이 방식으로 411≠1360 즉시 검출 확인.

## 원리
같은 회계기간(예: 2025H1)은 최소 두 번 공시된다 — 처음엔 그 필링 자신의 "당기"로,
1년(또는 1개 분기) 뒤엔 다음 필링의 "전기"로. 두 필링은 서로 다른 문서·다른 표
구조라 컬럼 선택 로직도 독립적으로 돈다 — 그래서 이 둘을 대조하면 "값이 맞는
기간에 붙어 있는지"를 그 필링 하나만 봐서는 원리적으로 못 잡는 컬럼-오선택 버그를
잡을 수 있다(항등식·행수 검산은 이 유형을 못 잡는다 — 뒤바뀐 값도 자기 기간
안에서는 이미 앞뒤가 맞는 진짜 스냅샷이라 등식 자체는 깨지지 않기 때문).

★한계(설계문서 §5-1 R86/R88 검증으로 확인): 다음 필링에 그 라벨이 재등장해야만
대조가 성립한다. 폐지된 계정(예: 2018 IFRS9 전환)이나 1회성 요약표처럼 비주기
라벨은 "무대조"로만 나온다 — 이건 틀렸다는 뜻이 아니라 "이 방법으로는 확인 불가"
라는 뜻이다. 무대조 건도 참고용으로 표시하되, 값불일치보다 낮은 확신도로 다룬다.

## 사용법
    python scripts/layer2_period_continuity_check.py --rcept 20250814003156
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import extract_report_lines

_PERIOD_STEP = {"FY": 1, "H1": 1, "Q1": 1, "Q3": 1}  # 전부 "1년 뒤 같은 기간"

_FILE_SQL = text(
    """
    SELECT dt.file_path
    FROM download_tasks dt
    WHERE dt.rcept_no = :r AND dt.file_type = 'xml' AND dt.status = 'completed'
    """
)

_NEXT_FILING_SQL = text(
    """
    SELECT f.rcept_no, dt.file_path
    FROM filings f JOIN download_tasks dt USING (rcept_no)
    WHERE f.corp_code = :c AND f.fiscal_year = :fy AND f.fiscal_period = :fp
      AND f.is_amendment = false AND dt.file_type = 'xml' AND dt.status = 'completed'
    ORDER BY f.filed_at DESC
    LIMIT 1
    """
)


def _load(session, rcept_no: str) -> dict | None:
    row = session.execute(text(
        "SELECT corp_code, fiscal_year, fiscal_period FROM filings WHERE rcept_no = :r"),
        {"r": rcept_no}).fetchone()
    if row is None:
        return None
    file_row = session.execute(_FILE_SQL, {"r": rcept_no}).fetchone()
    if file_row is None:
        return None
    return {"rcept_no": rcept_no, "corp_code": row.corp_code, "fiscal_year": row.fiscal_year,
            "fiscal_period": row.fiscal_period, "file_path": file_row.file_path}


def cmd_check(args) -> None:
    with get_session() as session:
        target = _load(session, args.rcept)
        if target is None:
            logger.error(f"r{args.rcept}: filings/download_tasks 에서 못 찾음(원문 미보유?)")
            return

        step = _PERIOD_STEP.get(target["fiscal_period"], 1)
        next_fy = target["fiscal_year"] + step
        nxt = session.execute(_NEXT_FILING_SQL, {
            "c": target["corp_code"], "fy": next_fy, "fp": target["fiscal_period"]}).fetchone()
        if nxt is None:
            logger.warning(
                f"r{args.rcept}: 다음 필링({next_fy}{target['fiscal_period']}) 없음 — "
                "대조 불가(아직 안 나왔거나 상장폐지 등). 값 불일치 검사를 못 합니다.")
            return

        logger.info(f"대상: r{target['rcept_no']} ({target['fiscal_year']}{target['fiscal_period']})")
        logger.info(f"대조: r{nxt.rcept_no} ({next_fy}{target['fiscal_period']}, 전기 컬럼)")

        target_lines = extract_report_lines(
            target["file_path"], rcept_no=target["rcept_no"], corp_code=target["corp_code"],
            report_fiscal_year=target["fiscal_year"], report_fiscal_period=target["fiscal_period"])
        next_lines = extract_report_lines(
            nxt.file_path, rcept_no=nxt.rcept_no, corp_code=target["corp_code"],
            report_fiscal_year=next_fy, report_fiscal_period=target["fiscal_period"])

        # ★BS는 분기/반기(interim) 필링에서 전기·전전기 컬럼이 "1년 전 같은 날"이 아니라
        # "직전/전전 회계연도 말"이다(국내 IFRS 관행) — 그래서 "당기말"(예: 2025-06-30)과
        # 같은 날짜를 재보고하는 필링이 원리적으로 없다. 실측(2026-09-11): 이 규칙을
        # 안 넣으면 BS 전 항목이 "불일치"로 잘못 뜬다(자산총계까지도) — 컬럼오선택이
        # 아니라 그냥 다른 시점을 비교한 것이었다. FY 필링끼리는 당기말=전기의 전기말이라
        # 정상 성립(R86이 이 경로로 확인됨).
        statements = ("IS", "CF") if target["fiscal_period"] != "FY" else ("BS", "IS", "CF")

        # 대상의 "당기"(context_fy == 대상 fiscal_year)만 검사 대상 — store_report_lines()가
        # 실제로 DB에 싣는 값과 같은 스코프(사용자 결정 2026-07-30).
        target_dangi = {
            (l.statement, l.basis, l.label_raw): l.value_won
            for l in target_lines
            if l.statement in statements
            and l.context_fiscal_year == target["fiscal_year"] and l.value_won is not None
        }
        # 대조필링에서 같은 기간을 가리키는 값(전기/전전기 등, context_fy로 매칭 — 위치 아님).
        next_by_key: dict[tuple, int] = {}
        for l in next_lines:
            if l.statement in ("BS", "IS", "CF") and l.context_fiscal_year == target["fiscal_year"]:
                next_by_key[(l.statement, l.basis, l.label_raw)] = l.value_won

        mismatches, matches, uncorroborated = [], 0, []
        for key, v in target_dangi.items():
            if key not in next_by_key:
                uncorroborated.append(key)
            elif next_by_key[key] != v:
                mismatches.append((key, v, next_by_key[key]))
            else:
                matches += 1

        print(f"\n=== 결과: 당기 항목 {len(target_dangi)}개 중 "
              f"일치 {matches} / 불일치 {len(mismatches)} / 무대조 {len(uncorroborated)} ===")

        if mismatches:
            print("\n★값 불일치(확신도 높음 — 컬럼 오선택 의심) — 원문대조 필요:")
            for (stmt, basis, label), v, nv in mismatches:
                print(f"  [{stmt}/{basis}] {label!r}: 당기(대상)={v:,} vs "
                      f"전기(다음필링)={nv:,}")
        if uncorroborated and args.show_uncorroborated:
            print(f"\n△무대조({len(uncorroborated)}건, 확신도 낮음 — 다음 필링에 그 라벨 자체가 "
                  "없음. 폐지계정/1회성 요약표일 수 있어 이 방법만으론 판단 보류):")
            for stmt, basis, label in uncorroborated:
                print(f"  [{stmt}/{basis}] {label!r}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rcept", required=True)
    ap.add_argument("--show-uncorroborated", action="store_true",
                    help="무대조 항목도 출력(기본은 값불일치만)")
    ap.set_defaults(func=cmd_check)
    return ap


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
