"""Phase B — 재구축(Track 1) 대상 인벤토리 산출.

계획(docs/plans/vast-nibbling-blum.md §4 Phase B)에 따라 **재파싱 대상 보고서**를 확정한다.
Phase C 가 이 테이블을 읽어 샤딩·진행추적하며 재추출한다.

## 대상 기준 (사용자 확정)
- **2015+** 만(Track 1). 구형 서식(2000~2014)은 Track 3 별도.
- **Track B(xml_text)** 만. Track A(xbrl_acode)는 ACODE 태깅이라 섹션 의존이 없어 범위 밖(§5-1).
  실측: 2015+ 에서 report 별 Track 은 **깨끗이 분리**(pure_A 16,384 / pure_B 86,699 / mixed 0).
- **최초 보고서만**. 정정본 제외: `report_nm NOT LIKE '%정정%'`.
  ⚠ `is_amendment` 단독 사용 금지였으나(구: [첨부정정] 1,145 누락), 현 DB 는
  `is_attachment_amendment` 컬럼이 생겨 `report_nm '%정정%'` == `is_amendment OR
  is_attachment_amendment`(둘 다 24,145 로 일치, 실측). report_nm 기준을 쓴다(가장 견고).
- **본문없음**은 **여기서 거르지 않는다**: 검출은 파싱시점 판정이라 Phase C 가 빈 결과 →
  보류로 처리하며 자연히 별도 리스트가 나온다(사용자 결정: 추측으로 채우지 않음).

## 왜 report 그레인인가
재파싱은 **보고서(rcept) 단위**(파일 1개 → fact 다수). 표준화는 (corp,fy,period,basis) 단위지만
그건 fact_v2 재구축 후 build 가 담당. 대상 테이블은 rcept 그레인 + corp/fy/period 메타.

## Track A/B 판정
report 가 xbrl_acode fact 를 하나라도 가지면 Track A. 그 외(xml_text 만·fact 전무)는 Track B
후보. **fact 전무 report 도 대상**에 포함한다(추출 실패·미시도분 — 재구축이 재시도).

사용:
    python scripts/phase_b_build_targets.py            # 테이블 생성 + 요약
    python scripts/phase_b_build_targets.py --summary  # 재생성 없이 요약만
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger
from sqlalchemy import text

from collector.db import get_session

_TABLE = "rebuild_target_track1"

_CREATE = f"""
DROP TABLE IF EXISTS {_TABLE};
CREATE TABLE {_TABLE} AS
SELECT DISTINCT
    f.rcept_no,
    f.corp_code,
    f.corp_cls,
    f.fiscal_year,
    f.fiscal_period,
    dt.file_path,
    -- Phase C 진행추적용(초기 pending). 재추출 후 done/held/no_body 등으로 갱신.
    'pending'::varchar(12) AS status,
    NULL::timestamp        AS processed_at
FROM filings f
JOIN download_tasks dt ON dt.rcept_no = f.rcept_no
WHERE f.fiscal_year >= 2015
  AND f.report_nm NOT LIKE '%정정%'
  AND f.fiscal_period IS NOT NULL
  AND dt.file_path LIKE '%.xml'
  -- Track A(xbrl_acode) 제외: 그 report 가 xbrl fact 를 가지면 범위 밖
  AND NOT EXISTS (
      SELECT 1 FROM fact_v2 fv
      WHERE fv.rcept_no = f.rcept_no AND fv.source_format = 'xbrl_acode'
      LIMIT 1
  );

ALTER TABLE {_TABLE} ADD PRIMARY KEY (rcept_no);
CREATE INDEX ix_{_TABLE}_corp   ON {_TABLE} (corp_code);
CREATE INDEX ix_{_TABLE}_status ON {_TABLE} (status);
"""


def build(session) -> None:
    logger.info(f"[phase-b] {_TABLE} 생성 중…")
    for stmt in _CREATE.strip().split(";"):
        if stmt.strip():
            session.execute(text(stmt))
    session.commit()
    logger.success(f"[phase-b] {_TABLE} 생성 완료")


def summarize(session) -> None:
    exists = session.execute(text(
        "SELECT to_regclass(:t)"), {"t": _TABLE}).scalar()
    if not exists:
        logger.warning(f"[phase-b] {_TABLE} 없음 — 먼저 생성하라(--summary 없이 실행)")
        return

    total = session.execute(text(f"SELECT count(*) FROM {_TABLE}")).scalar()
    corps = session.execute(text(f"SELECT count(DISTINCT corp_code) FROM {_TABLE}")).scalar()
    logger.info(f"[phase-b] ── 재구축 대상(Track 1) 요약 ──")
    logger.info(f"  총 대상 보고서 : {total:,}")
    logger.info(f"  대상 기업      : {corps:,}")

    logger.info("  기간(fiscal_period)별:")
    for r in session.execute(text(
            f"SELECT fiscal_period, count(*) FROM {_TABLE} GROUP BY 1 ORDER BY 2 DESC")):
        logger.info(f"    {r[0]:4} {r[1]:>8,}")

    logger.info("  시장(corp_cls)별:")
    for r in session.execute(text(
            f"SELECT corp_cls, count(*) FROM {_TABLE} GROUP BY 1 ORDER BY 2 DESC")):
        logger.info(f"    {str(r[0]):4} {r[1]:>8,}")

    logger.info("  연도별(상위):")
    for r in session.execute(text(
            f"SELECT fiscal_year, count(*) FROM {_TABLE} GROUP BY 1 ORDER BY 1 DESC LIMIT 12")):
        logger.info(f"    {r[0]} {r[1]:>8,}")

    # 파일 실재 여부 표본 점검(경로가 DB 에 있어도 파일이 없을 수 있음)
    sample = session.execute(text(
        f"SELECT file_path FROM {_TABLE} ORDER BY random() LIMIT 200")).fetchall()
    missing = sum(1 for (p,) in sample if not Path(p).exists())
    logger.info(f"  파일 실재(표본 200) : 결측 {missing}/200")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="재생성 없이 요약만")
    a = ap.parse_args()
    with get_session() as s:
        if not a.summary:
            build(s)
        summarize(s)


if __name__ == "__main__":
    main()
