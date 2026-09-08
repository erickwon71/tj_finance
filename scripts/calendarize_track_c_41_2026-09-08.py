"""calendar_v3 재동기화 배치 — Track C 93건 백필(R83)로 std_financials_v3가 바뀐 41개사
(docs/plans/manual_review_queue_2026-09-08.md, build_std_v3.py --corp 실행 직후 세트).

런북(docs/runbook_new_parser_pipeline_integration.md B5): std_v3를 바꾼 뒤 같은 corp 목록으로
calendarize_corp_v3()를 다시 안 돌리면 예전 std_v3 행을 가리키던 달력분기가 유령행으로 남는다
(dq_assertions.py::calendar_orphan_cq, ERROR)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import get_session
from fin2.standardize.calendar_v3 import calendarize_corp_v3

CORPS = ["00111218","00115694","00120562","00121288","00121534","00122056","00123772",
         "00124197","00127158","00127857","00128546","00129387","00129642","00138279",
         "00139685","00139719","00140946","00146232","00146861","00148276","00148832",
         "00150244","00154462","00158501","00159740","00160047","00163691","00164636",
         "00165103","00166175","00170026","00170877","00173698","00190321","00198697",
         "00199252","00203582","00205687","00267881","00295547","00307222"]

if __name__ == "__main__":
    with get_session() as session:
        total = 0
        for corp in CORPS:
            n = calendarize_corp_v3(session, corp)
            total += n
            print(f"calendarize_corp_v3({corp}) -> {n} rows")
        print(f"total: {total} rows across {len(CORPS)} corps")
