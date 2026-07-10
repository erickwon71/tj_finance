"""
Coverage class tagging
======================
정기보고(분기/반기/사업) 미대상 상장 entity(펀드·집합투자기구·인프라/리츠 펀드 등)를
corporations.coverage_class='non_periodic' 로 분리한다. 완전성 모집단에서 제외되며,
추후 보강 대상으로 별도 추적 가능(WHERE coverage_class='non_periodic').

운영기업의 정기보고와 재무제표 구조가 다른 entity 이므로 표준 파이프라인에서 분리한다.
큐레이션 목록(아래 NON_PERIODIC) 기준 — 멱등(여러 번 실행해도 안전). 추후 발견 시 목록에 추가.

근거: 이 entity 들은 filings 0건(표준 정기보고서 미제출). 단, 신규상장 직후 미제출 기업은
펀드가 아니므로 목록에 넣지 않는다(자연 제출 대기).

사용:
    python3 scripts/tag_coverage_class.py            # 적용
    python3 scripts/tag_coverage_class.py --dry-run  # 미적용, 대상만 출력
"""
import argparse

import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"

# 큐레이션: 정기보고 미대상 entity (corp_code, 이름, 사유)
NON_PERIODIC = [
    ("00435297", "맥쿼리인프라",   "infra_fund"),
    ("00600013", "맵스리얼티",     "re_fund"),
    ("01880801", "KB발해인프라",   "infra_fund"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    codes = [c for c, _, _ in NON_PERIODIC]
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # 현재 상태 확인
    cur.execute(
        "SELECT corp_code, corp_name, coverage_class FROM corporations WHERE corp_code = ANY(%s) ORDER BY corp_name",
        (codes,),
    )
    print("── 대상 현황 ──")
    for code, name, cls in cur.fetchall():
        print(f"  {code}  {name:20s}  현재 coverage_class={cls}")

    if args.dry_run:
        print("\n[dry-run] 변경 안 함.")
        conn.close()
        return

    cur.execute(
        "UPDATE corporations SET coverage_class='non_periodic', updated_at=NOW() "
        "WHERE corp_code = ANY(%s) AND coverage_class IS DISTINCT FROM 'non_periodic'",
        (codes,),
    )
    changed = cur.rowcount
    conn.commit()
    print(f"\n적용: {changed}건 non_periodic 으로 변경 (총 큐레이션 {len(codes)}건).")
    conn.close()


if __name__ == "__main__":
    main()
