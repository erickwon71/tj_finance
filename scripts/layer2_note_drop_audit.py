"""계층2 주석 표 폐기 사유 감사 (READ-ONLY, DB 미변경).

왜 이 방식인가
--------------
'주석을 놓치고 있나'를 원문 텍스트 휴리스틱으로 재려다 **다섯 번 연속 내 측정이 틀렸다**:
  ① FY vs 분기 최대 주석번호  → 보고서 간 번호가 대응 안 됨
  ② 원문 키워드 포함          → '현금흐름표'가 본문 재무제표에도 존재
  ③ basis='consolidated' 고정 → 연결 미작성 기업은 별도만 있음
  ④ '번호. 제목' 으로 좁힘     → '4. 현금흐름표'가 본문 섹션 제목
  ⑤ db_max 초과 번호          → '2024.12.31. 현재' 같은 **날짜 조각**을 제목으로 오인
추정치가 38.8% → 27.2% → 9.4% → 21.9% 로 요동쳤다. 전부 신호 설계 실패다.

그래서 추측하지 않고 **추출기에게 직접 묻는다**. assign_note_tables_with_titles 가 찾은
주석 표 전체를 열거하고, 각 표가 왜 버려졌는지 정확한 사유를 센다:
    · 단위 미선언  (declared_unit is None)      ← 설계상 보류(결측 > 오염)
    · 데이터행 없음(_table_has_data_rows False) ← 서술형 표
    · 정상 적재
이건 휴리스틱이 아니라 실제 코드 경로라 거짓양성이 없다.

Usage
-----
    python scripts/layer2_note_drop_audit.py --year 2024 --limit 120

⚠ **2026-07-31 이후 구 계약이다** — `declared_unit is None → 폐기` 로 세지만, F1/D4 이후
   로더는 데이터행이 있으면 전사한다(단위 미선언이면 value_won 만 빈다). 수치를 그대로
   합격 근거로 쓰지 말 것. 대체 = `scripts/verify_phase4_reload.py` · `audit_unit_declarations.py`.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lxml import etree
from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import _table_has_data_rows, declared_unit
from parser.common.note_topics import DA_SOURCE_BROAD, map_topic
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles)

FILINGS_SQL = text(
    """
    SELECT f.corp_code, f.rcept_no, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE f.fiscal_year = :year AND f.fiscal_period = 'FY'
      AND f.report_type = 'annual' AND f.is_final
      AND d.file_type = 'xml' AND d.status = 'completed' AND d.file_path IS NOT NULL
    """
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260729)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    tally: Counter[str] = Counter()
    # 계층3 가 실제로 쓰는 완결형 주제가 '표는 있는데 버려진' 경우 — 이게 진짜 손실이다.
    lost_broad: Counter[str] = Counter()
    examples: list[str] = []

    with get_session() as session:
        rows = list(session.execute(FILINGS_SQL, {"year": args.year}).fetchall())
        random.Random(args.seed).shuffle(rows)
        rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing (FY{args.year})", flush=True)

        for i, f in enumerate(rows, 1):
            if i % 40 == 0:
                print(f"  … {i}/{len(rows)}", flush=True)
            try:
                root = etree.parse(f.file_path, etree.XMLParser(recover=True)).getroot()
            except Exception:  # noqa: BLE001
                tally["파싱실패"] += 1
                continue
            sec_tables = assign_note_tables_with_titles(root)
            tally["filing"] += 1
            # ★집계 단위가 중요하다. 한 주석은 표가 여러 개이고 서술형 표는 설계상 버린다.
            #   표 하나가 버려진 것은 손실이 아니다 — **그 주제의 표가 전부 버려졌을 때**만
            #   주제가 통째로 사라진 것이고, 그게 계층3 가 값을 못 만드는 진짜 손실이다.
            seen: Counter[str] = Counter()
            loaded: Counter[str] = Counter()
            filing_lost = []

            for sec_kind in (SEC_CONSOL_NOTE, SEC_SEP_NOTE):
                for table, note_title in sec_tables.get(sec_kind, []):
                    tally["표 총계"] += 1
                    topic = map_topic(note_title)
                    if topic in DA_SOURCE_BROAD:
                        seen[topic] += 1
                    if declared_unit(table) is None:
                        tally["폐기:단위 미선언"] += 1
                    elif not _table_has_data_rows(table):
                        tally["폐기:데이터행 없음"] += 1
                    else:
                        tally["적재"] += 1
                        if topic in DA_SOURCE_BROAD:
                            loaded[topic] += 1

            for t, c in seen.items():
                if loaded.get(t, 0) == 0:
                    lost_broad[t] += 1
                    filing_lost.append(f"{t}(표{c}개 전부 폐기)")
            if filing_lost:
                tally["완결형 손실 filing"] += 1
                if len(examples) < args.show:
                    examples.append(f"{f.corp_code} {f.rcept_no} {filing_lost[:3]}")

    n = max(tally["filing"], 1)
    print(f"\n=== 주석 표 폐기 사유 · FY{args.year} (filing {n}) ===")
    for k, v in tally.most_common():
        print(f"  {k:<22} {v:>7}")
    tot = max(tally["표 총계"], 1)
    print(f"\n  적재율 {tally['적재']}/{tot} = {tally['적재']/tot*100:.1f}%")
    print(f"  완결형(D&A 소스) 주제가 버려진 filing: {tally['완결형 손실 filing']}/{n} "
          f"= {tally['완결형 손실 filing']/n*100:.1f}%")
    if lost_broad:
        print("\n  버려진 완결형 주제:")
        for k, v in lost_broad.most_common():
            print(f"    {k:<28} {v}")
    if examples:
        print("\n--- 예시 ---")
        for e in examples:
            print(f"  {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
