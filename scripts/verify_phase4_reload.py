"""Phase 4 재적재 수용 검증 — 승인된 계획 §6 을 SQL 로 한 번에 확인한다 (READ-ONLY).

재적재는 F1(단위 열귀속)·F2(header_hint)·D1(단위 상속)·D3·D4(게이트 완화)·F3(report_tables)
를 한꺼번에 DB 에 반영한다. 그래서 "돌았다"가 아니라 **무엇이 어떻게 달라졌는지**를 항목별로
확인해야 한다. 각 검사는 기준(=합격 조건)을 함께 찍는다.

    python scripts/verify_phase4_reload.py
    python scripts/verify_phase4_reload.py --sample     # 위반 표본행도 출력

★ 여기서 통과해도 원문 대조는 별도다(`scripts/verify_f1_columns.py --dump`).
  집계 통과로 끝내지 않는다 — 이번 작업에서 그 방식으로 거짓양성을 3 건 잡았다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

# (이름, 설명, SQL, 합격조건 함수, 표본 SQL)
CHECKS = [
    # ★판정은 **로더와 같은 규칙**이어야 한다(fin2/extract/units.py). 초판은 2026-07-30
    #   측정용 정의(`CONTAMINATION_MARKERS` 를 라벨 전체에 그대로)를 써서 재적재 후에도
    #   1,598,596 행을 위반으로 셌는데, 열어 보니 전부 **선언 접두**가 걸린 것이었다:
    #     '(원화단위 : 천원, 외화단위 : 1단위)>차입금액' — 'USD/외화' 는 표의 선언이지
    #     그 열의 성격이 아니다. 로더는 `label_segments()` 가 단위 단을 버린 뒤 판정한다.
    #   그래서 SQL 도 ① '단 위'(자간 공백 포함) 가 든 단을 걷어내고 ② '%' 는 단위로 쓰인
    #   때만 본다. 이 규칙으로 전수 246.6M 행에서 **0**.
    ("오염 — 비금액 열에 value_won",
     "F1 의 핵심 목표. 재적재 전 6,130,738 행 → **0 이어야 한다**",
     r"""WITH x AS (
           SELECT value_won,
                  regexp_replace(col_label, '(^|>)[^>]*단\s*위[^>]*', '', 'g') AS lbl
           FROM note_lines WHERE value_won IS NOT NULL AND col_label IS NOT NULL)
         SELECT count(*) FROM x
         WHERE lbl ~ '(\(\s*%\s*\)|%\s*(>|$)|율|률|비율|주당|수량|주수|배수|USD|EUR|JPY'
                     '|외화|주식수|소유주식|보유주식|발행주식|의결권|일수|적수|천주|백만주'
                     '|인원|건수|톤)'""",
     lambda v: v == 0,
     r"""WITH x AS (
           SELECT rcept_no, col_label, label_raw, value_won,
                  regexp_replace(col_label, '(^|>)[^>]*단\s*위[^>]*', '', 'g') AS lbl
           FROM note_lines WHERE value_won IS NOT NULL AND col_label IS NOT NULL)
         SELECT rcept_no, col_label, label_raw, value_won FROM x
         WHERE lbl ~ '(\(\s*%\s*\)|%\s*(>|$)|율|률|비율|주당|USD|주식수)'
         ORDER BY abs(value_won) DESC LIMIT 10"""),

    # 재적재로 드러난 **별개 결함**(F1 소관 아님) — 한 셀에 두 숫자가 구분자 없이 붙는 서식.
    #   원문 실측 20200814000694 담보제공자산: '500,0001,302,500' = '500,000' + '1,302,500'.
    #   `parse_amount` R1 은 **공백으로 나뉜** 다중 숫자만 거부하고, R3 상한은 1경이라 통과한다.
    #   한국 상장사 최대 총자산 ≈ 500조(5×10^14) 이므로 단일 셀 1,000조 이상은 실값일 수 없다.
    ("타당성 — 1,000조 이상(셀 병합 의심)",
     "R3 상한(1경)이 느슨해 붙은 숫자가 통과한다. 사용자 판단 대기 — 현재는 관찰만",
     "SELECT count(*) FROM note_lines WHERE abs(value_won) >= 1e15",
     lambda v: True,
     "SELECT rcept_no, label_raw, col_label, value_won FROM note_lines "
     "WHERE abs(value_won) >= 1e15 ORDER BY abs(value_won) DESC LIMIT 5"),

    ("정보 손실 — 값도 원문도 없는 행",
     "value_won 이 비었으면 value_raw 가 있어야 한다(F1 의 불변식)",
     "SELECT count(*) FROM note_lines WHERE value_won IS NULL AND value_raw IS NULL",
     lambda v: v == 0,
     "SELECT rcept_no, label_raw, unit_source FROM note_lines "
     "WHERE value_won IS NULL AND value_raw IS NULL LIMIT 10"),

    ("중복 저장 — 값과 원문을 둘 다",
     "값이 있으면 원문은 복원 가능하므로 저장하지 않는다",
     "SELECT count(*) FROM note_lines WHERE value_won IS NOT NULL AND value_raw IS NOT NULL",
     lambda v: v == 0, None),

    ("F3 — note_lines 에 남은 table_title",
     "표 단위 값은 report_tables 로 갔다",
     "SELECT count(*) FROM note_lines WHERE table_title IS NOT NULL",
     lambda v: v == 0, None),

    ("F3 — note_lines 에 남은 section_path",
     "주석 제목은 표 단위라 report_tables 로 갔다(본문은 행마다 유지)",
     "SELECT count(*) FROM note_lines WHERE section_path IS NOT NULL",
     lambda v: v == 0, None),

    ("F3 — report_lines 에 남은 table_title",
     "본문도 표 제목은 report_tables 로",
     "SELECT count(*) FROM report_lines WHERE table_title IS NOT NULL",
     lambda v: v == 0, None),

    ("F3 — 본문 section_path 는 **남아야** 한다",
     "본문의 section_path 는 들여쓰기 경로라 행마다 다르다(옮기면 tree 가 뭉개진다)",
     "SELECT count(*) FROM report_lines WHERE section_path IS NOT NULL",
     lambda v: v > 0, None),

    ("F3 — 표 메타 고아",
     "note_lines 의 표 키가 report_tables 에 없으면 조인이 끊긴다",
     """SELECT count(*) FROM (
            SELECT DISTINCT n.rcept_no, n.basis, n.table_seq FROM note_lines n
            WHERE NOT EXISTS (SELECT 1 FROM report_tables rt
                              WHERE rt.rcept_no=n.rcept_no AND rt.statement='note'
                                AND rt.basis=n.basis AND rt.table_seq=n.table_seq)
        ) x""",
     lambda v: v == 0,
     """SELECT DISTINCT n.rcept_no, n.basis, n.table_seq FROM note_lines n
        WHERE NOT EXISTS (SELECT 1 FROM report_tables rt
                          WHERE rt.rcept_no=n.rcept_no AND rt.statement='note'
                            AND rt.basis=n.basis AND rt.table_seq=n.table_seq) LIMIT 10"""),

    ("F1 — unit_source 분포(값이 채워진 행)",
     "declared/col_money/inherited 만 값을 가진다",
     """SELECT count(*) FROM note_lines WHERE value_won IS NOT NULL
        AND unit_source NOT IN ('declared','col_money','inherited')""",
     lambda v: v == 0,
     "SELECT unit_source, count(*) FROM note_lines WHERE value_won IS NOT NULL "
     "GROUP BY 1 ORDER BY 2 DESC"),

    ("타당성 — 1경원 초과",
     "R3 상한(parse_amount). 자릿수 폭발이 남아 있으면 안 된다",
     "SELECT count(*) FROM note_lines WHERE abs(value_won) > 10000000000000000",
     lambda v: v == 0, None),
]

INFO = [
    ("행 수", "SELECT to_char(count(*),'FM999,999,999') FROM note_lines"),
    ("본문 행 수", "SELECT to_char(count(*),'FM999,999,999') FROM report_lines"),
    ("표 메타 행 수", "SELECT to_char(count(*),'FM999,999,999') FROM report_tables"),
    ("unit_source=inherited(D1)", "SELECT to_char(count(*),'FM999,999,999') FROM note_lines "
                                  "WHERE unit_source='inherited'"),
    ("header_hint 있는 행(F2)", "SELECT to_char(count(*),'FM999,999,999') FROM note_lines "
                                "WHERE header_hint IS NOT NULL"),
    ("value_raw 만 있는 행", "SELECT to_char(count(*),'FM999,999,999') FROM note_lines "
                             "WHERE value_raw IS NOT NULL"),
    ("DB 총 크기", "SELECT pg_size_pretty(pg_database_size('tj_finance'))"),
    ("note_lines", "SELECT pg_size_pretty(pg_total_relation_size('note_lines'))"),
    ("report_lines", "SELECT pg_size_pretty(pg_total_relation_size('report_lines'))"),
    ("report_tables", "SELECT pg_size_pretty(pg_total_relation_size('report_tables'))"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    fails = 0
    with get_session() as s:
        print("=== 현황 ===")
        for name, sql in INFO:
            print(f"  {name:<26}{s.execute(text(sql)).scalar()}")

        print("\n=== 합격 판정 ===")
        for name, why, sql, ok, sample in CHECKS:
            v = s.execute(text(sql)).scalar() or 0
            good = ok(v)
            fails += 0 if good else 1
            print(f"  {'✅' if good else '❌'} {name:<34}{v:>14,}   — {why}")
            if (not good or args.sample) and sample:
                for r in s.execute(text(sample)).fetchall():
                    print(f"        {tuple(r)}")

    print(f"\n{'✅ 전 항목 통과' if fails == 0 else f'❌ {fails} 항목 실패'}")
    print("※ 다음: 원문 대조(verify_f1_columns.py --dump) · Gate B · std_v3 커버리지")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
