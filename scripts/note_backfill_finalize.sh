#!/usr/bin/env bash
#
# 주석 백필 마무리 — 전 샤드 종료를 기다렸다가 인덱스를 만들고 검증까지 돌린다.
#
# 적재 중에는 인덱스를 떼어놓기 때문에(scripts/note_lines_indexes.sh drop),
# 이 단계를 빼먹으면 note_lines 에 corp 바운드 인덱스가 없는 상태로 남는다.
# 샤드가 정상 완료한 경우에만 인덱스를 만든다 — 중간에 죽었는데 인덱스를 만들면
# 불완전한 데이터가 완성된 것처럼 보이기 때문.
#
# 사용법: bash scripts/note_backfill_finalize.sh <logdir> [expected_shards]
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

LOGDIR="${1:?logdir 필요}"
EXPECTED="${2:-6}"

# pgrep 패턴에 bracket 을 써서 이 스크립트 자신의 명령줄이 매칭되는 것을 피한다.
while pgrep -f "load_report_lines.py --not[e]s" >/dev/null 2>&1; do sleep 60; done

echo "=== 전 샤드 종료 $(date '+%Y-%m-%d %H:%M:%S') ==="
# `grep -hc` 는 **파일마다 한 줄씩** 카운트를 뱉어서 합산이 필요했고, 그 합산(paste|bc)이
# 깨지면 변수에 여러 줄이 들어가 `[ ... -gt 0 ]` 이 'integer expression expected' 로 죽는다.
# → 가드가 조용히 무력화된다. 매칭된 '줄' 자체를 세는 방식으로 단순화한다.
DONE=$(grep -h "완료" "$LOGDIR"/shard*.log 2>/dev/null | wc -l | tr -d ' ')
echo "완료 샤드: ${DONE}/${EXPECTED}"
grep -h "완료" "$LOGDIR"/shard*.log 2>/dev/null

FAIL=$(grep -hE "DiskFull|PendingRollbackError" "$LOGDIR"/shard*.log 2>/dev/null | wc -l | tr -d ' ')
echo "치명 오류 라인: ${FAIL}"

if [ "$DONE" -lt "$EXPECTED" ] || [ "$FAIL" -gt 0 ]; then
  echo "!! 정상 완료가 아니다 — 인덱스를 만들지 않는다. 로그를 확인할 것." >&2
  df -g /opt/homebrew/var/postgresql@15 | awk 'NR==2{print "DB vol free: "$4" GB"}'
  exit 1
fi

echo
bash scripts/note_lines_indexes.sh create

echo
echo "=== 검증 ==="
psql -d tj_finance -c "
  SELECT count(*) AS rows,
         count(source_ref) AS src_nonnull,
         count(context_raw) AS ctx_nonnull,
         count(DISTINCT section_path) AS sections
  FROM note_lines WHERE rcept_no='20250319000134' AND basis='consolidated';"
echo "  기대: rows=1613 · src/ctx nonnull=0 · sections=32"

df -g /opt/homebrew/var/postgresql@15 | awk 'NR==2{print "DB vol free: "$4" GB"}'
echo
echo "다음: .venv/bin/python scripts/layer3_note_section_resolution_probe.py --corps 200"
