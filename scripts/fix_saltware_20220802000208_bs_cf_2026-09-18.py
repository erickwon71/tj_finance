"""★★이중대체됨(2026-09-18) — 이 스크립트는 근본원인(R136, has_note_col
미배선) 수정 전 임시 수동패치였다. R136 수정 후 `recover_one()`재적재로 아래
5개 중 4개(이연법인세부채·보통주자본금·주식발행초과금 + 자동추출로 원래 있던
것들)가 복구됐고, 남은 1개(미처분이익잉여금)는 "계정지도가 의도적으로 제외"
때문이라 판단해 manual 삽입했었다. 그런데 그 판단 자체가 틀렸다 — R137(같은 날
후속)에서 "계정지도 매핑 실패가 report_lines 저장을 막을 이유가 없다"는 걸
확인해 canon/storage를 분리했고, 그 김에 CF 가짜행의 진짜 원인(마지막 앵커가
주석 섹션까지 안 닫히는 리전 경계 결함)까지 근본수정했다. 최종적으로
`recover_one()` 재적재만으로 BS/CF/IS 전부(미처분이익잉여금 포함) 자동
추출되어 manual 삽입도 더 이상 필요 없다(BS/CF/IS = 23/10/8행, 전부
`unit_source='pdf'`). 이 파일은 R136/R137 발견 경위 기록용으로만 남겨두되,
**재실행하지 말 것**. 상세: `docs/PARSING_RULES.md` R136·R137.

솔트웨어(01390399) 2022 H1 반기보고서(20220802000208) 별도 BS/CF 정정 (2026-09-18).

배경: 이 필링은 원문 XML archive 손상(2026-09-12 최초 발견)으로 PDF 복구 경로
(`fin2.extract.pdf.extract_pdf_facts`)를 통해 별도 BS/IS/CF가 적재됐다. 사용자가
DART 원문(PDF)과 report_lines를 한 계정씩 직접 대조해 두 가지 결함을 확정했다
(docs/plans/parser_source_fallback_cascade_design_2026-09-12.md §6 이후 경과):

1. **BS 5개 계정 결측** — PDF 복구 함수가 "라벨 바로 다음의 콤마없는 단독
   주석번호(9/10/11 등)를 진짜 금액으로 오인식 → 숫자 개수가 헤더 기간수를
   초과 → 안전장치가 행 전체를 드롭"하는 버그(2026-09-17 세션에서 근본원인
   확정, `fin2/extract/pdf.py::_looks_like_real_amount()`가 콤마 없는 단독
   숫자를 못 거름)로 인해 소실됨. 사용자가 DART 원문에서 직접 읽은 값:
   - 이연법인세부채 42,726,070 (비유동부채 하위)
   - 보통주자본금 648,200,000 (자본금 하위)
   - 주식발행초과금 11,764,905,920 (자본잉여금 하위)
   - 전환권대가 166,216,647 (자본잉여금 하위)
   - 미처분이익잉여금 11,495,730 (이익잉여금 하위)
   전부 당기(col_index=0, 제4(당)반기말)만 — 이 필링의 기존 별도 BS 행 전부가
   당기만 담고 있는 것과 동일 범위(전기 비교값은 이번 스코프 밖).

2. **CF 가짜행 1개** — "단기금융상품 12,493,953,976"이 CF에 들어있는데 사용자가
   DART 원문 CF 섹션에는 이 행이 없음을 확인(원인 미조사 — 앵커 영역 경계
   오판 추정, 별도 후속 필요). 삭제 대상.

--dry-run(기본): 변경될 내용만 출력. --execute: 실제 반영.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session

_RCEPT_NO = "20220802000208"
_CORP_CODE = "01390399"
_REPORT_FISCAL_YEAR = 2022
_REPORT_FISCAL_PERIOD = "H1"

# (label_raw, value_won) — 전부 당기(col_index=0), 원(adecimal=0), 별도(separate) BS.
_MISSING_BS_ROWS = [
    ("이연법인세부채", 42_726_070),
    ("보통주자본금", 648_200_000),
    ("주식발행초과금", 11_764_905_920),
    ("전환권대가", 166_216_647),
    ("미처분이익잉여금", 11_495_730),
]

_SPURIOUS_CF_LABEL = "단기금융상품"
_SPURIOUS_CF_VALUE = 12_493_953_976


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="실제로 반영(기본은 dry-run)")
    args = ap.parse_args()

    with get_session() as session:
        existing_bs = session.execute(text("""
            SELECT label_raw FROM report_lines
            WHERE rcept_no=:r AND statement='BS' AND basis='separate'
        """), {"r": _RCEPT_NO}).scalars().all()
        print(f"[fix-saltware] 현재 BS separate 기존 라벨 {len(existing_bs)}개")
        dup = [lbl for lbl, _ in _MISSING_BS_ROWS if lbl in existing_bs]
        if dup:
            raise SystemExit(f"이미 존재하는 라벨 발견(중복 삽입 위험, 중단): {dup}")

        cf_target = session.execute(text("""
            SELECT id, label_raw, value_won FROM report_lines
            WHERE rcept_no=:r AND statement='CF' AND basis='separate'
              AND label_raw=:lab AND value_won=:val
        """), {"r": _RCEPT_NO, "lab": _SPURIOUS_CF_LABEL, "val": _SPURIOUS_CF_VALUE}).fetchall()
        print(f"[fix-saltware] 삭제 대상 CF 가짜행: {len(cf_target)}건")
        for row in cf_target:
            print(f"  id={row.id} {row.label_raw}={row.value_won}")

        print(f"\n[fix-saltware] 삽입 예정 BS 행 {len(_MISSING_BS_ROWS)}건:")
        for lbl, val in _MISSING_BS_ROWS:
            print(f"  {lbl} = {val:,}")

        if not args.execute:
            print("\n--dry-run 모드입니다. 실제 반영하려면 --execute 를 붙여 다시 실행하세요.")
            return

        for lbl, val in _MISSING_BS_ROWS:
            session.execute(text("""
                INSERT INTO report_lines
                    (corp_code, rcept_no, report_fiscal_year, report_fiscal_period,
                     statement, basis, label_raw, col_index, period_kind, is_cumulative,
                     value_won, adecimal, unit_source, source_ref, context_raw)
                VALUES
                    (:corp_code, :rcept_no, :fy, :fp,
                     'BS', 'separate', :label, 0, 'instant', false,
                     :value, 0, 'manual', :source_ref, NULL)
            """), {
                "corp_code": _CORP_CODE, "rcept_no": _RCEPT_NO,
                "fy": _REPORT_FISCAL_YEAR, "fp": _REPORT_FISCAL_PERIOD,
                "label": lbl, "value": val,
                "source_ref": f"BS_sep/manual/{lbl}"[:180],
            })
        result = session.execute(text("""
            DELETE FROM report_lines
            WHERE rcept_no=:r AND statement='CF' AND basis='separate'
              AND label_raw=:lab AND value_won=:val
        """), {"r": _RCEPT_NO, "lab": _SPURIOUS_CF_LABEL, "val": _SPURIOUS_CF_VALUE})
        session.commit()
        print(f"\n[fix-saltware] 완료: BS {len(_MISSING_BS_ROWS)}건 삽입, "
              f"CF {result.rowcount}건 삭제")


if __name__ == "__main__":
    main()
