#!/usr/bin/env bash
#
# 전량 재적재 — 본문 + 주석 + 표 메타.
#
# 2026-07-31 판(Phase 4): F1(단위 열귀속)·F2(header_hint)·D1(단위 상속)·D4(데이터행 게이트
# 완화)·F3(report_tables 정규화)을 **한 번의 재적재**로 반영한다. 이 재적재 전까지 DB 는
# 구 포맷이고 오염 6,130,738 행이 그대로 남아 있다.
# 원판: XML 이스케이프 복구(53d440b) 반영 재적재.
#
# ★DB 크기 원칙: delete-then-insert 는 헌 튜플을 남겨 테이블을 부풀린다(2026-07-27 에
#   이것 때문에 디스크가 100% 차서 백필이 전멸했다). 두 테이블 모두 **TRUNCATE 후 순수
#   INSERT** 로 적재해 bloat 를 0 으로 만든다. 증가분은 실데이터 증가(+0.32%)뿐이어야 한다.
#
# 순서(동시 실행 금지):
#   ① report_lines(본문) TRUNCATE → 적재      ※ progress/anomalies 도 함께 비운다
#   ② note_lines(주석)  TRUNCATE → 적재      ※ 인덱스 떼고 적재 후 재생성
#   ③ std_v3 재빌드
#   combine 이 두 테이블을 모두 읽으므로 겹쳐 돌리면 일부 기업만 반영된 상태가 된다.
#
# ★2026-08-08 (R11 note/SCE 열 오귀속 수정, T4.2): 이 수정은 주석/SCE 경로만 건드렸고
#   본문(report_lines)은 T3.4 전수 실측으로 무영향 확인됨(0.0036%, 별건 결함) — 그래서
#   ①은 건너뛸 수 있어야 한다(계획서 `note_span_fix_plan_2026-08-07.md` §4 T4.2가 요구한
#   "스크립트 분리"). SKIP_BODY=1 / SKIP_STD_V3=1 로 개별 단계를 끌 수 있다(기본은 전부 실행
#   — 기존 호출부 동작 무변화).
#
# ★2026-08-08 재개 지원(T4.2 첫 시도가 외부 요인으로 중단된 뒤 추가): note_lines 는
#   rcept 단위 delete-then-insert 이고 BATCH(200건)마다 커밋되므로, 죽어도 마지막 커밋까지는
#   안전하게 남는다(_targets 의 notes 재개 판정 = "note_lines 에 그 rcept 가 이미 있는가").
#   RESUME_NOTES=1 이면 TRUNCATE·인덱스 drop·`--recheck`(전량 재처리 강제)를 전부 생략하고
#   지금 note_lines 에 없는 rcept 만 이어서 채운다 — 이미 실은 행을 다시 태우지 않는다.
#
# 사용법: bash scripts/full_reload_after_sanitize.sh [샤드수]
#         SKIP_BODY=1 bash scripts/full_reload_after_sanitize.sh 6     # ②+③만
#         SKIP_BODY=1 SKIP_STD_V3=1 bash scripts/full_reload_after_sanitize.sh 6   # ②만
#         SKIP_BODY=1 SKIP_STD_V3=1 RESUME_NOTES=1 bash scripts/full_reload_after_sanitize.sh 6  # ② 이어서
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SHARDS="${1:-6}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="logs/full_reload_${STAMP}"
mkdir -p "$LOG"
PGDATA_DIR="$(psql -d tj_finance -tAc 'SHOW data_directory;')"

free_gb() { df -g "$PGDATA_DIR" | awk 'NR==2 {print $4}'; }
say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG/main.log"; }

say "시작 · 여유 $(free_gb) GB · 샤드 ${SHARDS}"

# raw_report 저장소 계약 확인 — NAS 재마운트를 먼저 시도한다(collector.storage_guard).
# 그래도 안 되면 기본은 그냥 실패(드리프트 재발 방지). SD카드 폴백을 원하면 수동으로
# ALLOW_SD_FALLBACK=1 bash scripts/full_reload_after_sanitize.sh 로 명시적으로 켤 것 —
# 이 스크립트가 스스로 켜지 않는다(무인 실행과 동급으로 취급).
STORAGE_MSG="$(.venv/bin/python -c "
import sys
sys.path.insert(0, '.')
from collector.storage_guard import StorageContractError, ensure_root
import os
try:
    root = ensure_root(allow_sd_fallback=bool(os.environ.get('ALLOW_SD_FALLBACK')))
except StorageContractError as exc:
    print(f'{exc}')
    sys.exit(1)
print(f'raw_report 루트 확인 — {root}')
" 2>&1)"
STORAGE_RC=$?
say "$STORAGE_MSG"
if [ "$STORAGE_RC" -ne 0 ]; then
  say "ERROR: raw_report 접근 불가(저장소 계약 위반)"; exit 1
fi

# ── ① 본문 ────────────────────────────────────────────────────────────────
if [ "${SKIP_BODY:-0}" = "1" ]; then
  say "① 본문 — SKIP_BODY=1, 건너뜀(T3.4: R11이 본문에 무영향인 것 실측 확인됨)"
else
  say "① report_lines TRUNCATE"
  psql -d tj_finance -v ON_ERROR_STOP=1 <<'SQL' >>"$LOG/main.log" 2>&1 || exit 1
TRUNCATE TABLE report_lines;
TRUNCATE TABLE report_line_load_progress;
-- ★F3(2026-07-31): 표 단위 메타(table_title·주석 section_path·단위 선언 원문)를 담는 새 테이블.
--   두 적재 패스가 rcept 단위로 delete-then-insert 하지만, 전량 재적재에서는 먼저 비운다
--   (구 포맷 잔재가 남지 않도록 — 라인 테이블과 같은 원칙).
TRUNCATE TABLE report_tables;
-- ★report_line_corrections 가 report_line_anomalies 를 FK 로 참조한다. 따로 비우면
--   "cannot truncate a table referenced in a foreign key constraint" 로 막힌다.
--   두 테이블을 **한 문장에서** 함께 비워야 한다(2026-07-29 여기서 중단됨).
--   둘 다 적재 과정에서 재생성되는 감사 테이블이라 보존 대상이 아니다.
TRUNCATE TABLE report_line_anomalies, report_line_corrections;
SQL
  say "  TRUNCATE 완료 · 여유 $(free_gb) GB"

  say "① 본문 적재 시작 (${SHARDS} 샤드)"
  for ((a = 0; a < SHARDS; a++)); do
    .venv/bin/python -u scripts/load_report_lines.py --shard "${a}/${SHARDS}" \
      > "$LOG/body_shard${a}.log" 2>&1 &
  done
  wait
  say "① 본문 적재 종료 · 여유 $(free_gb) GB"
  grep -h "완료" "$LOG"/body_shard*.log | tee -a "$LOG/main.log"
fi

# ── ② 주석 ────────────────────────────────────────────────────────────────
NOTE_FLAGS="--notes --recheck"
if [ "${RESUME_NOTES:-0}" = "1" ]; then
  say "② note_lines — RESUME_NOTES=1, TRUNCATE/인덱스drop 생략(이미 있는 rcept 는 건너뛰고 이어서)"
  NOTE_FLAGS="--notes"
  CURRENT_ROWS="$(psql -d tj_finance -tAc 'SELECT count(*) FROM note_lines;')"
  say "  현재 note_lines $(printf '%s' "$CURRENT_ROWS" | tr -d ' ') 행부터 이어감"
else
  say "② note_lines TRUNCATE + 인덱스 제거"
  psql -d tj_finance -v ON_ERROR_STOP=1 -c "TRUNCATE TABLE note_lines;" >>"$LOG/main.log" 2>&1 || exit 1
  bash scripts/note_lines_indexes.sh drop >>"$LOG/main.log" 2>&1
  say "  완료 · 여유 $(free_gb) GB"
fi

say "② 주석 적재 시작 (${SHARDS} 샤드, ${NOTE_FLAGS})"
for ((a = 0; a < SHARDS; a++)); do
  .venv/bin/python -u scripts/load_report_lines.py ${NOTE_FLAGS} --shard "${a}/${SHARDS}" \
    > "$LOG/note_shard${a}.log" 2>&1 &
done
wait
say "② 주석 적재 종료 · 여유 $(free_gb) GB"
grep -h "완료" "$LOG"/note_shard*.log | tee -a "$LOG/main.log"

say "② 인덱스 재생성"
bash scripts/note_lines_indexes.sh create >>"$LOG/main.log" 2>&1

# ── ③ std_v3 ──────────────────────────────────────────────────────────────
if [ "${SKIP_STD_V3:-0}" = "1" ]; then
  say "③ std_v3 재빌드 — SKIP_STD_V3=1, 건너뜀(계획서 T4.3, 별도 실행)"
else
  say "③ std_v3 재빌드"
  .venv/bin/python -u scripts/build_std_v3.py --all > "$LOG/std_v3.log" 2>&1
  tail -1 "$LOG/std_v3.log" | tee -a "$LOG/main.log"
fi

say "전체 완료 · 여유 $(free_gb) GB"
psql -d tj_finance -c "
SELECT s.relname, pg_size_pretty(pg_total_relation_size(s.relid)) AS total
FROM pg_stat_user_tables s ORDER BY pg_total_relation_size(s.relid) DESC LIMIT 4;" \
  | tee -a "$LOG/main.log"
