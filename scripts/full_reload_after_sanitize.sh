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
# 사용법: bash scripts/full_reload_after_sanitize.sh [샤드수]
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

if [ ! -d raw_report ] || [ -z "$(ls -A raw_report 2>/dev/null)" ]; then
  say "ERROR: raw_report 접근 불가(저장소 미마운트)"; exit 1
fi

# ── ① 본문 ────────────────────────────────────────────────────────────────
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

# ── ② 주석 ────────────────────────────────────────────────────────────────
say "② note_lines TRUNCATE + 인덱스 제거"
psql -d tj_finance -v ON_ERROR_STOP=1 -c "TRUNCATE TABLE note_lines;" >>"$LOG/main.log" 2>&1 || exit 1
bash scripts/note_lines_indexes.sh drop >>"$LOG/main.log" 2>&1
say "  완료 · 여유 $(free_gb) GB"

say "② 주석 적재 시작 (${SHARDS} 샤드)"
for ((a = 0; a < SHARDS; a++)); do
  .venv/bin/python -u scripts/load_report_lines.py --notes --recheck --shard "${a}/${SHARDS}" \
    > "$LOG/note_shard${a}.log" 2>&1 &
done
wait
say "② 주석 적재 종료 · 여유 $(free_gb) GB"
grep -h "완료" "$LOG"/note_shard*.log | tee -a "$LOG/main.log"

say "② 인덱스 재생성"
bash scripts/note_lines_indexes.sh create >>"$LOG/main.log" 2>&1

# ── ③ std_v3 ──────────────────────────────────────────────────────────────
say "③ std_v3 재빌드"
.venv/bin/python -u scripts/build_std_v3.py --all > "$LOG/std_v3.log" 2>&1
tail -1 "$LOG/std_v3.log" | tee -a "$LOG/main.log"

say "전체 완료 · 여유 $(free_gb) GB"
psql -d tj_finance -c "
SELECT s.relname, pg_size_pretty(pg_total_relation_size(s.relid)) AS total
FROM pg_stat_user_tables s ORDER BY pg_total_relation_size(s.relid) DESC LIMIT 4;" \
  | tee -a "$LOG/main.log"
