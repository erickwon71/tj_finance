#!/usr/bin/env bash
#
# report_tables(주석) 소급 백필 — docs/plans/report_tables_note_backfill_plan_2026-08-30.md
# Phase 1 실행 스크립트.
#
# 배경: fin2/layer3/note_da.py(std_v3 D&A 추출)가 의존하는 report_tables.section_path가
# note_lines corpus 대비 극히 일부(2026-08-08 하루, 14,739건 = FY2024+ rcept의 0.07%)만
# 채워져 있다 — 08-08 RESUME_NOTES 복구 실행이 "note_lines에 이미 있으면 스킵"만 판정하고
# report_tables 존재는 안 봐서 생긴 백필 공백(코드 버그 아님, 위 계획서 §1-4 참고).
#
# 이 스크립트가 하는 일:
#   0) 사전 점검 — 디스크 여유·전/후 스냅샷 기록
#   1) SKIP_BODY=1 (본문 BS/CF/IS/SCE/APPR는 2026-08-29 전수 재적재로 이미 정상 —
#      계획서 §1-3) — 기존 scripts/full_reload_after_sanitize.sh 를 RESUME_NOTES 없이
#      (전량 TRUNCATE+재적재) 호출 → note_lines 재적재 + report_tables(note) 재구축
#   2) std_v3 전수 재빌드(위 스크립트 ③ 단계, SKIP_STD_V3 안 줌 — 기본 실행)
#   3) 완료 후 report_tables(note) 커버리지 전/후 비교 출력
#
# ★장시간 작업(설계 문서 D4 실측: 07-31 기준 주석 재적재 ~3.1h + std_v3 재빌드 ~1h
#   ≈ 합계 4~4.3시간, 6샤드 병렬 기준). 반드시 백그라운드로 돌릴 것 — 아래 "실행" 참고.
#
# 실행(터미널 닫아도 계속 돌게 nohup):
#   nohup bash scripts/backfill_report_tables_notes_2026-08-30.sh > logs/report_tables_notes_backfill_2026-08-30.out 2>&1 &
#
# 진행 확인:
#   tail -f logs/report_tables_notes_backfill_2026-08-30.out
#
# 중단 시 재개: 이 스크립트는 전량 재적재라 재개 개념이 없다 — 중단되면 처음부터 다시
# 돌린다(note_lines/report_tables는 원문 XML에서 재생성 가능한 파생 테이블이라 데이터
# 손실은 아니다, 계획서 §5 롤백 참고).
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

SHARDS="${1:-6}"
say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

say "=== report_tables(주석) 소급 백필 시작 — 샤드 ${SHARDS} ==="

# ── 0) 사전 점검 ────────────────────────────────────────────────────────────
PGDATA_DIR="$(psql -d tj_finance -tAc 'SHOW data_directory;')"
free_gb() { df -g "$PGDATA_DIR" | awk 'NR==2 {print $4}'; }
say "디스크 여유 $(free_gb)GB (계획서 D4 실측 기준 07-31 165~278GB 구간에서 문제없었음 — 지금은 더 빠듯하니 참고)"

BEFORE_NOTE_LINES="$(psql -d tj_finance -tAc 'SELECT count(*) FROM note_lines;' | tr -d ' ')"
BEFORE_RT_NOTE="$(psql -d tj_finance -tAc "SELECT count(*) FROM report_tables WHERE statement='note';" | tr -d ' ')"
BEFORE_RCEPT_TOTAL="$(psql -d tj_finance -tAc "SELECT count(DISTINCT rcept_no) FROM note_lines WHERE report_fiscal_year >= 2024;" | tr -d ' ')"
say "백필 전 스냅샷 — note_lines ${BEFORE_NOTE_LINES}행 · report_tables(note) ${BEFORE_RT_NOTE}행 · FY2024+ 고유rcept ${BEFORE_RCEPT_TOTAL}건"

# ── 1)+2) 주석 전량 재적재 + std_v3 전수 재빌드 ─────────────────────────────
# SKIP_BODY=1  : 본문(BS/CF/IS/SCE/APPR)은 2026-08-29 전수 재적재로 이미 정상 — 건너뜀.
# RESUME_NOTES 안 줌(기본값 0) : 이번엔 "이어서"가 아니라 전량 재적재가 목적
#                                (재개 판정이 report_tables 존재를 못 봐서 생긴 사고라
#                                 §1-4, 같은 방식 재사용은 피한다).
# SKIP_STD_V3 안 줌(기본값 0)  : ③ std_v3 재빌드까지 이 스크립트가 이어서 실행.
say "SKIP_BODY=1 bash scripts/full_reload_after_sanitize.sh ${SHARDS} 호출"
SKIP_BODY=1 bash scripts/full_reload_after_sanitize.sh "${SHARDS}"
RC=$?
if [ "$RC" -ne 0 ]; then
    say "!!! full_reload_after_sanitize.sh 실패(종료코드 ${RC}) — 위 로그(logs/full_reload_*/main.log) 확인 필요"
    exit "$RC"
fi

# ── 3) 완료 후 커버리지 비교 ─────────────────────────────────────────────────
AFTER_NOTE_LINES="$(psql -d tj_finance -tAc 'SELECT count(*) FROM note_lines;' | tr -d ' ')"
AFTER_RT_NOTE="$(psql -d tj_finance -tAc "SELECT count(*) FROM report_tables WHERE statement='note';" | tr -d ' ')"
AFTER_MATCHED="$(psql -d tj_finance -tAc "
    SELECT count(DISTINCT n.rcept_no)
    FROM note_lines n
    JOIN report_tables rt ON rt.rcept_no=n.rcept_no AND rt.statement='note'
     AND rt.basis=n.basis AND rt.table_seq=n.table_seq
    WHERE n.report_fiscal_year >= 2024;" | tr -d ' ')"

say "=== 완료 ==="
say "note_lines           : ${BEFORE_NOTE_LINES} → ${AFTER_NOTE_LINES}"
say "report_tables(note)  : ${BEFORE_RT_NOTE} → ${AFTER_RT_NOTE}"
say "FY2024+ rcept(${BEFORE_RCEPT_TOTAL}건) 중 report_tables 매칭 : ${AFTER_MATCHED}건"
say ""
say "다음 확인(수동): scripts/census_valdaily_v2v3_sample_compare_2026-08-30.py 재실행"
say "  → 백필 전 불일치율 35%(20건 중 7건)가 얼마나 줄었는지 확인"
say "  (.venv/bin/python scripts/census_valdaily_v2v3_sample_compare_2026-08-30.py)"
