#!/bin/bash
# DART 백필 체인 — 00:01(일일쿼터 리셋 직후) 시작, 순차 실행.
#   1) B2b   자본이벤트 2022~2026 (backfill_capital_events, 가벼움)
#   2) 대주주 잔여연도 2015~2025  (collect_shareholders --skip-existing, 재개안전)
#   3) C5    크로스소스 전수      (verify_cross_source 전 기업 × 최근5FY)
# 셋 다 같은 DART 일일쿼터를 공유하므로 병렬 이득 없음 → 순차. 각 스크립트는 쿼터 소진 시
# 스스로 깔끔히 중단(자본이벤트=upsert 멱등, 대주주=--skip-existing 로 다음날 이어짐).
#
# 실행(사용자, 한 줄):
#   nohup caffeinate -i bash scripts/dart_backfill_chain.sh > logs/dart_chain.log 2>&1 &
# 진행 보기:  tail -f logs/dart_chain.log
set -u
cd /Users/taejin/Project/tj_finance || exit 1
PY=.venv_tj_finance/bin/python

# ── 다가오는 00:01 까지 대기(쿼터 리셋 직후 시작) ──
target=$(date -v0H -v1M -v0S +%s); now=$(date +%s)
[ "$target" -le "$now" ] && target=$(date -v+1d -v0H -v1M -v0S +%s)
echo "[chain] $(date '+%F %T') — 00:01 까지 $((target - now))초 대기"
sleep $((target - now))
echo "[chain] $(date '+%F %T') — 시작"

#echo "===== [1/3] B2b 자본이벤트 2022+ · $(date '+%T') ====="
#$PY -u scripts/backfill_capital_events.py --start-year 2022
#echo "[1/3] 종료 · $(date '+%T')"
#
#echo "===== [2/3] 대주주 잔여연도 2015~2025 · $(date '+%T') ====="
#for y in 2025 2024 2023 2022 2021 2020 2019 2018 2017 2016 2015; do
#  echo "--- 대주주 $y · $(date '+%T') ---"
#  $PY -u scripts/collect_shareholders.py --year "$y" --skip-existing
#done
#echo "[2/3] 종료 · $(date '+%T')"

echo "===== [3/3] C5 크로스소스 전수 2021~2025 · $(date '+%T') ====="
$PY -u scripts/verify_cross_source.py --sample 3000 --years 2021-2025
echo "[3/3] 종료 · $(date '+%T')"

echo "===== [chain] 전체 완료 · $(date '+%F %T') ====="
