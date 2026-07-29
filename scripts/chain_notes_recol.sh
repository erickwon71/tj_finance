#!/usr/bin/env bash
#
# std_v3 재빌드 완료를 기다렸다가 주석 재적재(col_label 반영)를 이어서 실행한다.
#
# 왜 순차인가: combine 이 note_lines 를 D&A 소스로 읽는다. 재빌드 중에 note_lines 를
# 재적재하면 일부 기업만 주석을 보는 불일치가 생긴다.
#
# 사용법: bash scripts/chain_notes_recol.sh
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

echo "[chain] std_v3 재빌드 종료 대기 $(date '+%H:%M:%S')"
while pgrep -f "build_std_v3.py --al[l]" >/dev/null 2>&1; do sleep 60; done
echo "[chain] 재빌드 종료 확인 $(date '+%H:%M:%S')"
tail -1 logs/build_std_v3_da9.log 2>/dev/null

echo "[chain] 주석 재적재 시작 (col_label 반영) $(date '+%H:%M:%S')"
echo yes | bash scripts/backfill_note_sections.sh --fresh
