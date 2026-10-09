# 검증 모델 A/B 시뮬레이션 (읽기 전용)

규칙(`docs/verification/verify_prompt.md`)이나 검증 도구를 바꾼 뒤, 모델(Haiku/Sonnet)과 반복 실행에 따라 결과가 같은지
**실제 슬롯**으로 확인하는 하니스다. DB 에는 아무것도 쓰지 않는다(`vq_shim.py` 가 쓰기를 `actions.jsonl` 로 돌린다).
결과 기록: `docs/verification/model_parity_2026-10-09.md`.

작업 폴더: `$SIM_HOME`(기본 `logs/verify_sim`, gitignore).

1. 후보 조사: `.venv/bin/python scripts/verify_sim/survey.py logs/verify_sim/cands.json`
2. 슬롯 고정(층화 표본, detail·CSV 스냅샷): `.venv/bin/python scripts/verify_sim/snapshot.py logs/verify_sim/cands.json logs/verify_sim/snap 1`
   (기계 코드를 바꿨으면 `refresh.py <snap>` 으로 스냅샷의 기계 발견을 다시 계산)
3. 문서 고정: `scripts/verify_sim/mkwork.sh r1`
4. 실행(동시 2개까지 — 그 이상은 Chrome 시간초과가 난다): `SNAPDIR=logs/verify_sim/snap scripts/verify_sim/run.sh r1 haiku 1`
5. 비교: `.venv/bin/python scripts/verify_sim/compare.py r1` · 한 실행 추적: `trace.py r1 haiku_1 3`

비용(2026-10-09 실측): Haiku ≈ $0.03/슬롯, Sonnet ≈ $0.5/슬롯.
