#!/usr/bin/env bash
# R144 소급 백필 러너 — 단계별 실행/재개용.
#
# 배경: docs/PARSING_RULES.md R144 (계층2 원문대조 캠페인 fail 20건 근본원인 4종).
#   파서를 고쳤으므로 이미 적재된 report_lines 를 다시 뽑아야 한다(R8 ③).
#   대상은 두 갈래 —
#     ① EPS 유령행이 DB 에 남아 있는 313개사 (SQL 로 정확히 셀 수 있음)
#     ② 금액이 인라인 태그로 쪼개진 원문을 가진 필링 (DB 엔 흔적이 없어 원문 스캔 필요)
#   ①을 재적재하면 그 기업들의 ② 결함도 같이 해소되므로, ②스캔은 ①기업을 제외하고 돈다.
#
# 모든 단계가 **멱등**이다(rcept 단위 delete-then-insert). 중간에 죽으면 그냥 다시 돌리면
# 된다 — 단 phase1 은 이미 끝난 기업도 다시 도므로, 오래 걸리면 phase1r 로 남은 것만 돌 것.
#
# 사용:
#   bash scripts/r144_backfill.sh prep      # 대상 목록 + 샤드 파일 생성
#   bash scripts/r144_backfill.sh phase1    # ① 313개사 재적재(4샤드 병렬)
#   bash scripts/r144_backfill.sh fixup     # phase1 중 오류난 필링만 재처리
#   bash scripts/r144_backfill.sh verify    # EPS 유령행 잔존 0건 확인
#   bash scripts/r144_backfill.sh scan      # ② 원문 스캔(①기업 제외, --resume 내장)
#   bash scripts/r144_backfill.sh phase2    # ② 스캔 적중 필링 재적재
#   bash scripts/r144_backfill.sh status    # 진행 상황만 출력
#   bash scripts/r144_backfill.sh protected # ★R139 보호가드 우회(아래 주의 참고)
#
# ★'protected' 는 `all` 에 없다 — 사람이 원문대조 pass 판정한 필링을 덮어쓰는 단계라
#   일부러 따로 뺐다. R144 를 알기 전 판정이라 EPS 유령행이 남아 있는 27건이 대상이고,
#   덮어쓰는 게 객관적으로 맞지만 판단은 사람이 하라는 뜻이다.
#
# 주의: phase1 은 약 1.5~2시간(34,818건, 4샤드). 다른 무거운 작업과 같이 돌리지 말 것.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PY=${PY:-python}
SHARDS=${SHARDS:-4}
LOG=logs
CORPS=$LOG/r144_eps_corps.txt
HITS=$LOG/r144_hits.txt

mkdir -p "$LOG"

# EPS 유령행 = '주당' 행인데 표 단위(adecimal≠0)가 적용된 것. R144 (1) 참고.
read -r -d '' SQL_GHOST <<'EOF'
SELECT count(*) AS rows, count(DISTINCT rcept_no) AS filings,
       count(DISTINCT corp_code) AS corps
FROM report_lines
WHERE statement='IS' AND label_raw LIKE '%주당%'
  AND source_ref LIKE 'IS%' AND adecimal IS DISTINCT FROM 0;
EOF

die() { echo "ERROR: $*" >&2; exit 1; }

phase_prep() {
  echo "== prep — 대상 기업 목록 + 샤드 파일 생성"
  $PY - "$CORPS" "$SHARDS" <<'PYEOF'
import sys
sys.path.insert(0, ".")
from collector.db import get_session
from sqlalchemy import text

out_path, n_shards = sys.argv[1], int(sys.argv[2])
with get_session() as s:
    corps = [r[0] for r in s.execute(text("""
        SELECT DISTINCT corp_code FROM report_lines
         WHERE statement='IS' AND label_raw LIKE '%주당%'
           AND source_ref LIKE 'IS%' AND adecimal IS DISTINCT FROM 0
         ORDER BY corp_code""")).fetchall()]
    if not corps:
        print("EPS 유령행 보유 기업 0개사 — phase1 불필요")
        open(out_path, "w").write("")
        raise SystemExit(0)
    sizes = {r.corp_code: r.n for r in s.execute(text("""
        SELECT f.corp_code, count(*) n
          FROM download_tasks dt JOIN filings f USING(rcept_no)
         WHERE f.corp_code = ANY(:corps) AND dt.status='completed'
           AND dt.file_type='xml' AND dt.file_path IS NOT NULL
         GROUP BY f.corp_code"""), {"corps": corps}).fetchall()}

open(out_path, "w").write("\n".join(corps) + "\n")
# 큰 기업부터 가장 적게 찬 샤드에 넣는다(greedy) — 샤드가 비슷한 시각에 끝나게.
shards, load = [[] for _ in range(n_shards)], [0] * n_shards
for c in sorted(corps, key=lambda c: -sizes.get(c, 0)):
    i = load.index(min(load))
    shards[i].append(c)
    load[i] += sizes.get(c, 0)
for i, (sh, lo) in enumerate(zip(shards, load), 1):
    open(f"logs/r144_shard{i}.txt", "w").write(",".join(sh))
    print(f"  shard{i}: 기업 {len(sh):3}개사 · filing {lo:,}건")
print(f"대상 {len(corps)}개사 · filing 합계 {sum(load):,} → {out_path}")
PYEOF
}

phase1() {
  [[ -s $CORPS ]] || die "$CORPS 가 없다 — 먼저 'prep' 을 돌릴 것"
  echo "== phase1 — 313개사 재적재 (${SHARDS}샤드 병렬)"
  local pids=()
  for i in $(seq 1 "$SHARDS"); do
    local f=$LOG/r144_shard$i.txt
    [[ -s $f ]] || continue
    nohup $PY scripts/reload_report_lines_corp.py --corp "$(cat "$f")" \
      > "$LOG/r144_reload_shard$i.log" 2>&1 &
    pids+=($!)
    echo "  shard$i 시작 pid=${pids[-1]}"
  done
  echo "  진행 확인: bash scripts/r144_backfill.sh status"
  wait "${pids[@]}"
  echo "== phase1 완료"
  phase_status
}

phase_fixup() {
  echo "== fixup — phase1 중 오류난 필링만 재처리"
  # 로그의 ERROR 줄에서 rcept_no(14자리)만 뽑는다. 오류난 필링은 store 가 안 불려
  # **기존 행이 그대로 남아 있다**(오염 아님) — 고친 코드로 다시 돌리면 된다.
  #
  # ★'marked reviewed' 는 제외한다 — R139 보호가드(layer2_review_queue.status='pass')가
  #   일부러 막은 것이라 오류가 아니다. 사람이 원문대조로 확인한 필링을 백필이 조용히
  #   덮어쓰지 않게 하는 장치고, 다시 돌려도 같은 이유로 막힌다.
  grep -h "ERROR" "$LOG"/r144_reload_shard*.log 2>/dev/null \
    | grep -v "marked reviewed" \
    | grep -o '[0-9]\{14\}' | sort -u > "$LOG/r144_errors.txt" || true
  local skipped; skipped=$(grep -h "marked reviewed" "$LOG"/r144_reload_shard*.log \
    2>/dev/null | grep -c . || true)
  echo "  R139 보호로 건너뛴 필링 $skipped 건(정상 — 원문대조 완료분)"
  local n; n=$(wc -l < "$LOG/r144_errors.txt" | tr -d ' ')
  echo "  오류 필링 $n 건"
  [[ $n -gt 0 ]] || { echo "  재처리할 것 없음"; return 0; }
  $PY scripts/reload_report_lines_corp.py --rcept-file "$LOG/r144_errors.txt" \
    2>&1 | tail -5
}

phase_protected() {
  # ★R139 보호가드를 **일부러 우회**한다. 여기 걸리는 필링은 이 결함(R144)을 알기 전에
  #   원문대조 pass 판정을 받은 것들이라, 사람이 확인했음에도 EPS 유령행(주당이익이
  #   단위=백만원으로 ×10⁶ 저장)이 남아 있다 — 객관적으로 틀린 값이고 현재 파서가
  #   확실히 더 정확하다. 그래서 `all` 에는 넣지 않고 **별도 단계로만** 돌게 둔다.
  echo "== protected — R139 보호 필링 중 EPS 유령행이 남은 것만 강제 재적재"
  $PY - "$LOG/r144_protected.txt" <<'PYEOF'
import sys
sys.path.insert(0, ".")
from collector.db import get_session
from sqlalchemy import text
with get_session() as s:
    rc = [r[0] for r in s.execute(text("""
        SELECT DISTINCT rl.rcept_no
          FROM report_lines rl
          JOIN layer2_review_queue q ON q.rcept_no = rl.rcept_no AND q.status='pass'
         WHERE rl.statement='IS' AND rl.label_raw LIKE '%주당%'
           AND rl.source_ref LIKE 'IS%' AND rl.adecimal IS DISTINCT FROM 0
         ORDER BY rl.rcept_no""")).fetchall()]
open(sys.argv[1], "w").write("\n".join(rc) + ("\n" if rc else ""))
print(f"  대상 {len(rc)} 필링")
PYEOF
  local n; n=$(wc -l < "$LOG/r144_protected.txt" | tr -d ' ')
  [[ $n -gt 0 ]] || { echo "  대상 없음"; return 0; }
  $PY scripts/reload_report_lines_corp.py --rcept-file "$LOG/r144_protected.txt" \
      --overwrite-reviewed 2>&1 | tail -5
}

phase_verify() {
  echo "== verify — EPS 유령행 잔존 확인"
  $PY - <<PYEOF
import sys
sys.path.insert(0, ".")
from collector.db import get_session
from sqlalchemy import text
with get_session() as s:
    r = s.execute(text("""$SQL_GHOST""")).mappings().first()
print(f"  EPS 유령행: {r['rows']:,}행 / {r['filings']:,}필링 / {r['corps']:,}개사")
print("  ✅ 0건 — 백필 성공" if r['rows'] == 0 else
      "  ⚠ 잔존 — 남은 기업은 prep 재실행 후 phase1 재시도")
PYEOF
}

phase_scan() {
  echo "== scan — 원문 바이트 스캔(①기업 제외). 40~45분, --resume 내장"
  [[ -s $CORPS ]] || die "$CORPS 가 없다 — 먼저 'prep' 을 돌릴 것"
  local resume=""
  [[ -f $HITS.progress ]] && resume="--resume" && echo "  이전 진행 발견 → 이어서"
  $PY scripts/scan_intra_number_linebreak_r144.py \
      --out "$HITS" --workers 8 --exclude-corp-file "$CORPS" $resume
}

phase2() {
  [[ -s $HITS ]] || { echo "적중 0건 — phase2 불필요"; return 0; }
  local n; n=$(wc -l < "$HITS" | tr -d ' ')
  echo "== phase2 — 스캔 적중 $n 필링 재적재"
  $PY scripts/reload_report_lines_corp.py --rcept-file "$HITS" 2>&1 | tail -5
}

phase_status() {
  local tot=0
  for i in $(seq 1 "$SHARDS"); do
    local f=$LOG/r144_reload_shard$i.log n=0
    [[ -f $f ]] && n=$(grep -c '행 (IS' "$f" 2>/dev/null)
    tot=$((tot + n))
    echo "  shard$i: $n"
  done
  local err; err=$(cat "$LOG"/r144_reload_shard*.log 2>/dev/null | grep -ci ERROR || true)
  local alive; alive=$(pgrep -f reload_report_lines_corp.py | wc -l | tr -d ' ')
  echo "  합계 재적재 $tot 건 · 오류 $err 건 · 실행중 프로세스 $alive"
}

case "${1:-}" in
  prep)   phase_prep ;;
  phase1) phase1 ;;
  fixup)  phase_fixup ;;
  verify) phase_verify ;;
  scan)   phase_scan ;;
  phase2) phase2 ;;
  protected) phase_protected ;;
  status) phase_status ;;
  all)    phase_prep && phase1 && phase_fixup && phase_verify \
            && phase_scan && phase2 && phase_verify ;;
  *) sed -n '1,30p' "$0"; exit 1 ;;
esac
