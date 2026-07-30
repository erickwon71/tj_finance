#!/usr/bin/env bash
#
# note_lines 인덱스 관리 — 대량 적재 전/후로 나눠 쓴다.
#
# 배경(2026-07-28 실측):
#   note_lines 는 `CREATE TABLE ... (LIKE report_lines INCLUDING ALL)` 로 만들어져
#   본문용 인덱스 6개가 그대로 복사됐다. 주석에는 안 맞는 것이 섞여 있다:
#     · context_fiscal_year_idx : 주석은 연도를 주장하지 않아 이 컬럼이 **전량 NULL**
#                                 (실측 198만 행 중 non-null 0). btree 는 NULL 도 저장하므로
#                                 2.16억 개의 NULL 엔트리를 만들고 유지한다 = 순수 낭비.
#     · corp_code_idx           : 복합 인덱스 (corp_code, report_fiscal_year, …) 의 접두라 중복.
#     · statement 컬럼          : note_lines 에선 값이 'note' 하나뿐(실측 distinct=1)이라
#                                 복합 인덱스에 넣을 이유가 없다.
#     · report_fiscal_year_idx  : 카디널리티 ~12 라 단독으로는 플래너가 거의 안 쓴다.
#   그리고 인덱스를 단 채 대량 INSERT 하면 매 행마다 B-tree 를 갱신해 느리고,
#   그렇게 자란 인덱스는 적재 후 한 번에 만든 것보다 헐겁다(이전 26GB).
#
# ★ rcept_no 인덱스는 적재 중에도 반드시 유지한다 —
#   store_note_lines 가 filing 마다 `DELETE FROM note_lines WHERE rcept_no=:r` 를 실행하므로
#   이 인덱스가 없으면 filing 마다 전체 스캔이 돈다(10만 건 × 순차스캔 = 사실상 불가).
#
# 사용법:
#   bash scripts/note_lines_indexes.sh drop     # 적재 전(불필요 인덱스 제거)
#   bash scripts/note_lines_indexes.sh create   # 적재 후(필요한 것만 한 번에 생성)
#   bash scripts/note_lines_indexes.sh status
#
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

DB=tj_finance
CMD="${1:-status}"

status() {
  psql -d "$DB" -c "
    SELECT indexname,
           pg_size_pretty(pg_relation_size(indexname::regclass)) AS size
    FROM pg_indexes WHERE tablename='note_lines' ORDER BY indexname;"
}

case "$CMD" in
  drop)
    echo "=== 적재 전: 불필요/재생성 대상 인덱스 제거 ==="
    # 유지: note_lines_pkey(id 순차삽입이라 비용 낮음) · rcept_no_idx(위 ★ 참조)
    psql -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
DROP INDEX IF EXISTS note_lines_context_fiscal_year_idx;
DROP INDEX IF EXISTS note_lines_corp_code_idx;
DROP INDEX IF EXISTS note_lines_report_fiscal_year_idx;
DROP INDEX IF EXISTS note_lines_corp_code_report_fiscal_year_statement_basis_idx;
-- 신규 이름(create 단계가 만드는 것). 이걸 빠뜨려 2026-07-29 재적재가 인덱스를 단 채 돌았다.
DROP INDEX IF EXISTS note_lines_corp_fy_basis_idx;
-- F2(2026-07-31) header_hint 부분 인덱스도 같은 이유로 적재 중에는 뗀다(create 가 다시 만든다).
DROP INDEX IF EXISTS ix_note_lines_header_hint;
SQL
    echo "남은 인덱스:"; status
    ;;

  create)
    echo "=== 적재 후: 필요한 인덱스 생성 ==="
    # 인덱스 빌드용으로만 크게 잡는다(세션 한정).
    psql -d "$DB" -v ON_ERROR_STOP=1 <<'SQL'
SET maintenance_work_mem = '2GB';
-- statement 는 note_lines 에서 상수라 키에서 뺐다(원본 4컬럼 → 3컬럼).
-- corp 바운드 조회(corp_code / corp+연도 / corp+연도+basis)를 모두 접두로 커버한다.
CREATE INDEX IF NOT EXISTS note_lines_corp_fy_basis_idx
    ON note_lines (corp_code, report_fiscal_year, basis);
-- F2: 헤더 규칙에 걸린 행만(전체의 ~0.9%) — 부분 인덱스라 NULL 엔트리를 만들지 않는다.
CREATE INDEX IF NOT EXISTS ix_note_lines_header_hint
    ON note_lines (header_hint) WHERE header_hint IS NOT NULL;
SQL
    echo "최종 인덱스:"; status
    psql -d "$DB" -c "
      SELECT pg_size_pretty(pg_relation_size('note_lines')) AS heap,
             pg_size_pretty(pg_indexes_size('note_lines')) AS idx,
             pg_size_pretty(pg_total_relation_size('note_lines')) AS total;"
    ;;

  status) status ;;
  *) echo "usage: $0 {drop|create|status}" >&2; exit 1 ;;
esac
