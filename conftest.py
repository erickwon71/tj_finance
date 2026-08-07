"""저장소 루트 conftest — pytest 수집 범위 제한.

`raw_report` 는 NAS 마운트(`/Volumes/tj_finance_data/raw_report`)로 가는 심링크이고
원문 파일이 189,099개(2026-08 기준) 들어있다. pytest 는 기본적으로 심링크를 따라
재귀 수집하므로, 이 디렉터리를 빼두지 않으면 범위 없는 `pytest`/`pytest -q` 를 저장소
루트에서 돌릴 때 이 트리 전체를 "test_*.py 있나" 훑게 된다 — SMB 파일당 접근지연이
로컬보다 46배 느린 것과 맞물려 사실상 끝나지 않는다(2026-08-07 실측: 80분+ 도 미완료,
[[feedback-pytest-scope-raw-report-symlink]]).

이 파일이 있어도 **권장 실행법은 그대로 범위를 명시**하는 것이다(`pytest tests/
fin2/tests/` 또는 `python tests/run_all.py`) — 이건 실수로 범위 없이 돌렸을 때의
안전망일 뿐이다.
"""
collect_ignore = ["raw_report"]
