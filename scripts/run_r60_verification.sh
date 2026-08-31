#!/bin/bash
# R60(bs.current_portion_lt_debt 개념분리 — '유동성사채'를 bs.current_bond_plain으로
# 분리, fin2/layer3/combine.py + account_maps/bs_accounts.py) 검증 파이프라인을 한
# 번에 순차 실행한다: face_audit 스냅샷 -> std_financials_v3 전체 재빌드(5-shard) ->
# Gate B 전수재감사(5-shard) -> pass->fail_a 전이 확인 -> net_debt 복구율 확인.
#
# docs/plans/bs_current_portion_lt_debt_concept_split_design_2026-08-31.md §4
#
# ★face_audit은 bs.current_portion_lt_debt/bs.current_bond_plain을 직접 감사하지
# 않는다(R59와 동일 실측 — fail_fields 23종에 두 컬럼 모두 없음, 애초에 net_debt
# 전용 파생 집계 leaf라 std_financials_v3에 자체 컬럼조차 없다). 그래서 Gate B
# 회귀 확인은 R57/R58/R59와 동일하게 "전체 pass->fail_a 전이"만 본다. 이 수정이
# 겨냥한 값 복구 자체는 std_financials_v3.net_debt를 전/후 스냅샷으로 직접 비교한다
# (0단계/5단계) — _additive_debt_for_net_debt의 결과가 net_debt에만 copy-back되고
# short_term_debt/long_term_debt 영속 컬럼은 건드리지 않기 때문(combine.py
# _apply_enrichment 참고).
#
# 각 단계는 이전 단계가 전부 끝난 뒤에만 시작한다.
#
# 사용법(터미널을 열어두고 지켜볼 때):
#   caffeinate -i bash scripts/run_r60_verification.sh
#
# 사용법(백그라운드로 돌리고 터미널을 닫아도 될 때):
#   caffeinate -i nohup bash scripts/run_r60_verification.sh > logs/run_r60_verification.log 2>&1 &
#
# 진행상황 확인:
#   tail -f logs/run_r60_verification.log
#   tail -f logs/build_std_v3_r60_shard_*.log
#   tail -f logs/gateb_r60_shard_*.log
# 중단:
#   pkill -f build_std_v3.py; pkill -f gateb_audit.py
# 재실행: 이 스크립트를 다시 실행하면 된다(build_std_v3.py는 corp 단위 upsert,
#   gateb_audit.py는 --recheck라 안전). 스냅샷 테이블이 이미 있으면 기존 베이스라인을
#   재사용한다.

set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

DB_URL="postgresql://localhost/tj_finance"
SNAP_TABLE="face_audit_snap_20260831_r60"
N_SHARDS=5
YEAR_MIN=1999

if pgrep -f "build_std_v3.py" > /dev/null || pgrep -f "gateb_audit.py" > /dev/null; then
    echo "이미 build_std_v3.py 또는 gateb_audit.py 프로세스가 돌고 있습니다. 중복 실행 방지를 위해 종료합니다."
    ps aux | grep -E "build_std_v3.py|gateb_audit.py" | grep -v grep
    echo "다시 시작하려면 먼저: pkill -f build_std_v3.py; pkill -f gateb_audit.py"
    exit 1
fi

mkdir -p scratchpad logs

START_TS=$(date +%s)
echo "시작: $(date)"

NETDEBT_SNAP_TABLE="std_v3_netdebt_snap_20260831_r60"
echo ""
echo "===== 0단계: 영향 필링('유동성사채' + '유동성장기부채류' 동시존재) std_v3.net_debt 스냅샷 (${NETDEBT_SNAP_TABLE}) ====="
NETDEBT_SNAP_EXISTS=$(psql "$DB_URL" -tAc "SELECT to_regclass('public.${NETDEBT_SNAP_TABLE}') IS NOT NULL;")
if [ "$NETDEBT_SNAP_EXISTS" = "t" ]; then
    echo "스냅샷 테이블이 이미 있습니다 — 기존 베이스라인을 그대로 재사용합니다: ${NETDEBT_SNAP_TABLE}"
else
    psql "$DB_URL" -v ON_ERROR_STOP=1 -c "
    CREATE TABLE ${NETDEBT_SNAP_TABLE} AS
    WITH norm AS (
      SELECT corp_code, report_fiscal_year AS fiscal_year, basis,
             regexp_replace(regexp_replace(label_raw, '\(주[0-9,]+\)', '', 'g'), '\s+', '', 'g') AS lbl
      FROM report_lines
      WHERE statement = 'BS'
    ),
    affected AS (
      SELECT corp_code, fiscal_year, basis
      FROM norm
      GROUP BY corp_code, fiscal_year, basis
      HAVING bool_or(lbl = '유동성사채')
         AND bool_or(lbl IN ('유동성장기부채','유동성장기차입금',
                              '비유동차입금(사채포함)의유동성대체부분','비유동차입금의유동성대체부분'))
    )
    SELECT v.corp_code, v.fiscal_year, v.statement_type,
           v.short_term_debt AS short_term_debt_before,
           v.long_term_debt AS long_term_debt_before,
           v.net_debt AS net_debt_before
    FROM std_financials_v3 v
    JOIN affected a ON a.corp_code = v.corp_code AND a.fiscal_year = v.fiscal_year
                   AND a.basis = v.statement_type
    WHERE v.fiscal_period = 'FY';
    "
    echo "스냅샷 생성 완료: ${NETDEBT_SNAP_TABLE}"
fi
psql "$DB_URL" -c "SELECT count(*) AS affected_filings, count(*) FILTER (WHERE net_debt_before IS NULL) AS held_before FROM ${NETDEBT_SNAP_TABLE};"

echo ""
echo "===== 1단계: face_audit 스냅샷 (${SNAP_TABLE}) ====="
SNAP_EXISTS=$(psql "$DB_URL" -tAc "SELECT to_regclass('public.${SNAP_TABLE}') IS NOT NULL;")
if [ "$SNAP_EXISTS" = "t" ]; then
    echo "스냅샷 테이블이 이미 있습니다 — 기존 베이스라인을 그대로 재사용합니다: ${SNAP_TABLE}"
else
    psql "$DB_URL" -v ON_ERROR_STOP=1 -c "CREATE TABLE ${SNAP_TABLE} AS SELECT * FROM face_audit;"
    echo "스냅샷 생성 완료: ${SNAP_TABLE}"
fi

echo ""
echo "===== 2단계: std_financials_v3 전체 재빌드 (${N_SHARDS}-shard) ====="
pids=()
for i in $(seq 0 $((N_SHARDS - 1))); do
    python scripts/build_std_v3.py --all --year-min "$YEAR_MIN" \
        --shard "${i}/${N_SHARDS}" \
        > "logs/build_std_v3_r60_shard_${i}.log" 2>&1 &
    pids+=("$!")
    echo "std_v3 shard $i 시작: PID $!"
done
fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done
if [ "$fail" -eq 1 ]; then
    echo "std_v3 재빌드 중 하나 이상의 샤드가 실패했습니다. 로그를 확인하세요: logs/build_std_v3_r60_shard_*.log"
    exit 1
fi
echo "std_v3 재빌드 ${N_SHARDS}개 샤드 전부 정상 종료됨. 로그 마지막 줄:"
tail -n 3 logs/build_std_v3_r60_shard_*.log

echo ""
echo "===== 3단계: Gate B 전수재감사 (${N_SHARDS}-shard) ====="
python3 - "$N_SHARDS" << 'PYEOF'
import sys
from sqlalchemy import create_engine, text

n_shards = int(sys.argv[1])
eng = create_engine('postgresql://localhost/tj_finance')
with eng.connect() as c:
    r = c.execute(text("SELECT DISTINCT corp_code FROM std_financials_v3 ORDER BY corp_code"))
    corps = [row[0] for row in r]

shards = [[] for _ in range(n_shards)]
for i, corp in enumerate(corps):
    shards[i % n_shards].append(corp)

for i, s in enumerate(shards):
    with open(f"scratchpad/gateb_r60_shard_{i}.txt", "w") as f:
        f.write("\n".join(s) + "\n")
    print(f"scratchpad/gateb_r60_shard_{i}.txt: {len(s)}개사")
PYEOF

pids=()
for i in $(seq 0 $((N_SHARDS - 1))); do
    python scripts/gateb_audit.py --source v3 --fy-min "$YEAR_MIN" --recheck \
        --corp-file "scratchpad/gateb_r60_shard_${i}.txt" \
        > "logs/gateb_r60_shard_${i}.log" 2>&1 &
    pids+=("$!")
    echo "gateb shard $i 시작: PID $!"
done
fail=0
for pid in "${pids[@]}"; do
    wait "$pid" || fail=1
done
if [ "$fail" -eq 1 ]; then
    echo "Gate B 전수재감사 중 하나 이상의 샤드가 실패했습니다. 로그를 확인하세요: logs/gateb_r60_shard_*.log"
    exit 1
fi
echo "Gate B 전수재감사 ${N_SHARDS}개 샤드 전부 정상 종료됨. 로그 마지막 줄:"
tail -n 3 logs/gateb_r60_shard_*.log

echo ""
echo "===== 4단계: pass -> fail_a 전이 확인 (Gate B 전체 — R60 컬럼들은"
echo "             face_audit이 애초에 감사하지 않는 필드라 canonical 스코프 필터는 불가) ====="
psql "$DB_URL" -v ON_ERROR_STOP=1 -c "
SELECT count(*) AS pass_to_fail_a
FROM ${SNAP_TABLE} s
JOIN face_audit c
  ON s.corp_code = c.corp_code AND s.fiscal_year = c.fiscal_year
 AND s.fiscal_period = c.fiscal_period AND s.statement_type = c.statement_type
 AND s.is_stub = c.is_stub AND s.source_version = c.source_version
WHERE s.gate_status = 'pass' AND c.gate_status = 'fail_a';
"

echo ""
echo "===== 5단계: net_debt 복구율 (전/후 비교, ${NETDEBT_SNAP_TABLE}) ====="
psql "$DB_URL" -v ON_ERROR_STOP=1 -c "
SELECT
  count(*) AS affected_filings,
  count(*) FILTER (WHERE d.net_debt_before IS NULL) AS held_before,
  count(*) FILTER (WHERE d.net_debt_before IS NULL AND v.net_debt IS NOT NULL) AS recovered_after,
  count(*) FILTER (WHERE d.net_debt_before IS NULL AND v.net_debt IS NULL) AS still_held_after,
  count(*) FILTER (WHERE d.short_term_debt_before IS DISTINCT FROM v.short_term_debt) AS st_persisted_col_changed,
  count(*) FILTER (WHERE d.long_term_debt_before IS DISTINCT FROM v.long_term_debt) AS lt_persisted_col_changed
FROM ${NETDEBT_SNAP_TABLE} d
JOIN std_financials_v3 v
  ON v.corp_code = d.corp_code AND v.fiscal_year = d.fiscal_year
 AND v.statement_type = d.statement_type AND v.fiscal_period = 'FY';
"

END_TS=$(date +%s)
echo ""
echo "===== 완료: $(date) (총 $(( (END_TS - START_TS) / 60 ))분 소요) ====="
echo "종료 조건: 4단계 pass_to_fail_a = 0 AND 5단계 recovered_after > 0"
echo "(st/lt_persisted_col_changed는 설계상 항상 0이어야 함 — 영속 컬럼은 안 건드림, §3-2 참고)."
echo "still_held_after 표본을 원문대조로 확인할 것(sibling 이미 후보 존재 guard 등으로 부분복구만 되는 케이스가 있을 수 있음)."
