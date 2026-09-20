"""R147 백필 — EPS 계속영업/중단영업 세부행 결측 재적재 (2026-09-20).

배경: `fin2/extract/report_lines.py::_is_eps_label` 이 라벨 자체에 '주당' 이 없는
EPS 자식행(예: '기본주당이익(손실) (단위 : 원)' 아래 중첩된 '계속영업이익(손실)
(단위 : 원)')을 인식하지 못해 통째로 결측시켰다(설계·근거는
docs/qa/eps_continuing_ops_subline_gap_r147_2026-09-20.md, 파싱 규칙은
docs/PARSING_RULES.md R147 참고). 원인은 근본수정(`_is_eps_label` 의 `E` 규칙)됐고,
이 스크립트는 **이미 report_lines 가 적재된** 과거 필링을 새 코드로 재추출·재적재한다.

사용법:
    python scripts/backfill_eps_continuing_ops_subline_r147_2026-09-20.py --dry-run
    python scripts/backfill_eps_continuing_ops_subline_r147_2026-09-20.py --apply

기본 dry-run. --apply 를 줘야 실제로 DB 를 쓴다.

대상 선정: 이 스크립트 자체는 **후보 목록을 인자로 받는다**(하드코딩 없음) — 전사
스캔은 별도 스캔 스크립트가 만든 rcept_no 목록 파일을 `--rcept-list` 로 넘긴다.
인자가 없으면 이 첫 배치(두산에너빌리티 2015+ 25건, 스캔으로 확정)를 기본값으로 쓴다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from collector.db import get_session  # noqa: E402
from fin2.extract.report_lines import (  # noqa: E402
    extract_report_lines, store_report_lines, store_report_tables)

# 두산에너빌리티(00159616) 2015+ 전수 스캔으로 확정된 25건(2026-09-20,
# scripts/scan_r147_full_corpus_2026-09-20.py 이전 단계의 회사 단위 스캔).
DEFAULT_RCEPT_NOS = [
    "20240327001228",  # 2017FY [기재정정, 2024 재작성]
    "20190329003636",  # 2018FY
    "20240327001230",  # 2018FY [기재정정, 2024 재작성]
    "20190515001464",  # 2019Q1
    "20190515002099",  # 2019Q1 [기재정정]
    "20190814001701",  # 2019H1
    "20191114002511",  # 2019Q3
    "20200330004372",  # 2019FY
    "20240327001231",  # 2019FY [기재정정, 2024 재작성]
    "20200515002634",  # 2020Q1
    "20200814002599",  # 2020H1
    "20201113000791",  # 2020Q3
    "20210319001033",  # 2020FY
    "20240327001232",  # 2020FY [기재정정, 2024 재작성]
    "20240516002209",  # 2020FY [기재정정, 2024 재작성 재정정]
    "20210813000846",  # 2021H1
    "20211112001083",  # 2021Q3
    "20220322000017",  # 2021FY
    "20220513001669",  # 2022Q1
    "20220816001395",  # 2022H1
    "20221114002161",  # 2022Q3
    "20230321001573",  # 2022FY
    "20230515002122",  # 2023Q1
    "20230811002617",  # 2023H1
    "20231114002953",  # 2023Q3
]


def _load_meta(session, rcept_nos: list[str]) -> dict[str, dict]:
    rows = session.execute(text("""
        SELECT dt.rcept_no, dt.file_path, f.corp_code, f.fiscal_year, f.fiscal_period
        FROM download_tasks dt
        JOIN filings f ON f.rcept_no = dt.rcept_no
        WHERE dt.rcept_no = ANY(:rs) AND dt.status = 'completed' AND dt.file_type = 'xml'
    """), {"rs": rcept_nos}).mappings().all()
    return {r["rcept_no"]: dict(r) for r in rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 DB 에 쓴다(기본 dry-run)")
    ap.add_argument("--rcept-list", type=Path, default=None,
                     help="한 줄에 rcept_no 하나씩인 파일. 없으면 DEFAULT_RCEPT_NOS 사용")
    ap.add_argument("--overwrite-reviewed", action="store_true",
                     help="layer2_review_queue.status='pass' 로 이미 검토완료된 rcept 도 "
                          "덮어쓴다 — R147 은 이 버그가 알려지기 전에 pass 처리된 필링에도 "
                          "적용되므로, 근본원인을 원문대조로 이미 확인한 뒤 재적재할 때만 켠다.")
    args = ap.parse_args()

    if args.rcept_list:
        rcept_nos = [l.strip() for l in args.rcept_list.read_text().splitlines() if l.strip()]
    else:
        rcept_nos = DEFAULT_RCEPT_NOS

    ok, blocked, failed = 0, [], []
    with get_session() as session:
        meta = _load_meta(session, rcept_nos)
        missing = [r for r in rcept_nos if r not in meta]
        if missing:
            print(f"⚠ 메타 없음(다운로드 미완/파일유형 상이) — 건너뜀: {missing}")

        for rcept_no in rcept_nos:
            m = meta.get(rcept_no)
            if not m:
                continue
            path = m["file_path"]
            if not Path(path).exists():
                failed.append((rcept_no, "파일 없음"))
                continue
            try:
                lines = extract_report_lines(
                    path, rcept_no=rcept_no, corp_code=m["corp_code"],
                    report_fiscal_year=m["fiscal_year"], report_fiscal_period=m["fiscal_period"],
                    include_notes=False)
            except Exception as exc:  # noqa: BLE001
                failed.append((rcept_no, f"추출 실패: {type(exc).__name__}: {exc}"))
                continue
            if not lines:
                failed.append((rcept_no, "추출 0행"))
                continue
            n_new_eps = len([
                l for l in lines
                if l.source_ref and l.source_ref.startswith("eps/")
                and ("계속영업" in l.label_raw or "중단영업" in l.label_raw)
                and "주당" not in l.label_raw])
            if not args.apply:
                print(f"[dry-run] {rcept_no}: {len(lines)}행 추출, 신규 R147 EPS 자식행 {n_new_eps}개")
                continue
            try:
                store_report_lines(session, rcept_no, lines,
                                    overwrite_reviewed=args.overwrite_reviewed)
                store_report_tables(session, rcept_no, lines)
                session.commit()
            except ValueError as exc:      # manual/reviewed 보호가드
                session.rollback()
                blocked.append((rcept_no, str(exc)))
                continue
            ok += 1
            print(f"✅ {rcept_no}: 재적재 완료 ({len(lines)}행, R147 신규 {n_new_eps}개)")

    if args.apply:
        print(f"\n완료: {ok}건 재적재, {len(blocked)}건 보호가드로 보류, {len(failed)}건 실패")
        for r in blocked:
            print("  BLOCKED", r)
    for r in failed:
        print("  FAILED", r)


if __name__ == "__main__":
    main()
