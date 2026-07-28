#!/usr/bin/env bash
#
# 주석 section_path 전량 재적재 (계층2 note_lines).
#
# 왜: assign_note_tables_with_titles 에 <P> 헤딩 branch 를 추가해 주석 섹션 붕괴
#     (전체의 57.5%)를 고쳤다. 코드만 고쳐서는 기존 적재분에 반영되지 않으므로
#     전량 재적재가 필요하다.
#
# ★ --fresh 를 권장한다(2026-07-28 실측 근거):
#     --recheck 재적재는 rcept 단위 delete-then-insert 라 헌 튜플이 쌓인다. 실제로
#     note_lines 는 143GB 중 live 가 73GB 뿐이고 67GB(47%)가 죽은/빈 공간이었으며,
#     이 팽창으로 디스크가 100% 차서 1차 백필이 2h47m 만에 DiskFull 로 전멸했다.
#     --fresh 는 TRUNCATE 후 순수 INSERT 라 블로트가 생기지 않고 더 빠르다.
#     note_lines 는 원문 XML 에서 100% 재생성 가능하므로 TRUNCATE 로 잃는 정보가 없다.
#
# 범위: FY >= 2015 · XML 다운로드 완료분 전체(약 102,633건)
# 영향: note_lines 만 재기록. 본문 report_lines / report_line_load_progress 는 무변경.
# 소요: 6샤드 병렬 약 3시간
#
# 사용법:
#   bash scripts/backfill_note_sections.sh --fresh        # TRUNCATE 후 전량 적재(권장)
#   bash scripts/backfill_note_sections.sh                # 기존 방식(--recheck, 블로트 주의)
#   bash scripts/backfill_note_sections.sh --fresh 4      # 샤드 수 지정
#
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

FRESH=0
if [ "${1:-}" = "--fresh" ]; then FRESH=1; shift; fi
SHARDS="${1:-6}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOGDIR="logs/note_backfill_${STAMP}"

# 순수 INSERT 로 note_lines 를 다 쓰려면 live 기준 약 80GB 가 필요하다.
MIN_FREE_GB="${MIN_FREE_GB:-90}"

# ── 사전 점검 ────────────────────────────────────────────────────────────────
if [ ! -x .venv/bin/python ]; then
  echo "ERROR: .venv/bin/python 이 없다." >&2
  exit 1
fi

# raw_report 는 심링크(SD카드/NAS). 미마운트면 전 샤드가 'file missing' 으로 조용히
# 스킵되므로 반드시 먼저 막는다.
if [ ! -d raw_report ] || [ -z "$(ls -A raw_report 2>/dev/null)" ]; then
  echo "ERROR: raw_report 가 비었거나 접근 불가 — 저장소 미마운트 의심." >&2
  echo "       ls -la raw_report / ls /Volumes 로 확인할 것." >&2
  exit 1
fi

# ★ 1차 백필을 전멸시킨 원인. DB 볼륨 여유를 반드시 먼저 본다.
PGDATA_DIR="$(psql -d tj_finance -tAc 'SHOW data_directory;' 2>/dev/null)"
if [ -z "$PGDATA_DIR" ]; then
  echo "ERROR: postgres 에 접속할 수 없다." >&2
  exit 1
fi
FREE_GB="$(df -g "$PGDATA_DIR" | awk 'NR==2 {print $4}')"
echo "DB 볼륨 여유: ${FREE_GB} GB  (필요 최소 ${MIN_FREE_GB} GB)"

if [ "$FRESH" -eq 0 ] && [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
  cat >&2 <<EOF
ERROR: 여유 공간이 부족하다(${FREE_GB}GB < ${MIN_FREE_GB}GB).
       --recheck 방식은 delete-then-insert 로 공간을 더 먹는다. 두 가지 중 하나를 택할 것:
         · bash scripts/backfill_note_sections.sh --fresh   (TRUNCATE 후 적재 — 권장)
         · 다른 곳에서 공간을 먼저 확보
EOF
  exit 1
fi

mkdir -p "$LOGDIR"

echo "=== 주석 section_path 전량 재적재 ==="
echo "  모드   : $([ "$FRESH" -eq 1 ] && echo 'FRESH (TRUNCATE 후 INSERT)' || echo 'RECHECK (delete-then-insert)')"
echo "  샤드   : ${SHARDS}"
echo "  로그   : ${LOGDIR}/"
echo "  저장소 : $(readlink raw_report 2>/dev/null || echo raw_report)"
echo

# ── TRUNCATE (--fresh) ───────────────────────────────────────────────────────
if [ "$FRESH" -eq 1 ]; then
  echo "note_lines 를 TRUNCATE 한다 — 원문 XML 에서 전량 재생성되므로 정보 손실은 없다."
  printf "  계속하려면 'yes' 입력: "
  read -r ans
  if [ "$ans" != "yes" ]; then echo "중단."; exit 1; fi
  psql -d tj_finance -c "TRUNCATE TABLE note_lines;" || { echo "TRUNCATE 실패" >&2; exit 1; }
  echo "  TRUNCATE 완료 · 여유: $(df -g "$PGDATA_DIR" | awk 'NR==2 {print $4}') GB"
  echo
  # 대량 적재 동안 불필요한 B-tree 갱신을 없앤다(적재 후 create 로 한 번에 생성).
  # rcept_no 인덱스는 유지 — store_note_lines 의 filing 단위 DELETE 가 이걸 쓴다.
  bash scripts/note_lines_indexes.sh drop || { echo "인덱스 정리 실패" >&2; exit 1; }
  echo
fi

# ── 샤드 기동 ────────────────────────────────────────────────────────────────
# --recheck 는 '이미 적재된 rcept 건너뛰기'를 끈다. TRUNCATE 직후엔 어차피 비어 있지만,
# 중간에 끊겨 재실행할 때 이어서 하려면 --fresh 재실행 대신 이 스크립트를 인자 없이 돌릴 것.
for ((a = 0; a < SHARDS; a++)); do
  nohup .venv/bin/python scripts/load_report_lines.py \
    --notes --recheck --shard "${a}/${SHARDS}" \
    > "${LOGDIR}/shard${a}.log" 2>&1 &
  echo "  shard ${a}/${SHARDS} 기동 (pid $!)"
done

cat <<EOF

모두 백그라운드로 돌고 있다. 터미널을 닫아도 계속된다.

  진행 보기 : tail -f ${LOGDIR}/shard*.log
  완료 확인 : grep -h '완료' ${LOGDIR}/shard*.log
  디스크    : df -g "${PGDATA_DIR}" | awk 'NR==2 {print \$4" GB free"}'
  중단      : pkill -f 'load_report_lines.py --notes'

★ 전 샤드가 끝나면 **반드시** 인덱스를 다시 만들 것(적재 중에는 떼어놨다):
  bash scripts/note_lines_indexes.sh create

끝나면 검증:
  psql -d tj_finance -c "SELECT count(DISTINCT section_path) FROM note_lines WHERE rcept_no='20250319000134' AND basis='consolidated';"
    -> 32 가 나와야 한다 (수정 전 1)
  .venv/bin/python scripts/layer3_note_section_resolution_probe.py --corps 200
    -> COLLAPSED 가 57.5% 에서 대폭 감소해야 한다
EOF
