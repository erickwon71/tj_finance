-- Gate B A'(② Phase 4) 전수 재감사 무변화 검증 + R33 재개 트리거 점검.
-- 선행: CREATE TABLE face_audit_snap_before_aprime AS SELECT * FROM face_audit WHERE source_version='v3';
-- 사용: psql postgresql://localhost/tj_finance -f scripts/verify_gateb_aprime_no_change.sql

\pset pager off

\echo '=== [1] 행 수 대조 (스냅샷 vs 현재) ==='
SELECT (SELECT count(*) FROM face_audit_snap_before_aprime)                     AS snap_rows,
       (SELECT count(*) FROM face_audit WHERE source_version = 'v3')            AS now_rows;

\echo ''
\echo '=== [2] gate_status 전이 행렬 (대각선만 남아야 함) ==='
SELECT COALESCE(s.gate_status, '(신규)') AS before_status,
       COALESCE(a.gate_status, '(소실)') AS after_status,
       count(*)                          AS rows
FROM face_audit_snap_before_aprime s
FULL OUTER JOIN (SELECT * FROM face_audit WHERE source_version = 'v3') a
  ON  a.corp_code      = s.corp_code
  AND a.fiscal_year    = s.fiscal_year
  AND a.fiscal_period  = s.fiscal_period
  AND a.statement_type = s.statement_type
  AND a.is_stub        = s.is_stub
GROUP BY 1, 2
ORDER BY 3 DESC;

\echo ''
\echo '=== [3] 판정 6개 항목 행 단위 완전 대조 (0 이어야 통과) ==='
SELECT count(*) AS changed_rows
FROM face_audit_snap_before_aprime s
JOIN (SELECT * FROM face_audit WHERE source_version = 'v3') a
  ON  a.corp_code      = s.corp_code
  AND a.fiscal_year    = s.fiscal_year
  AND a.fiscal_period  = s.fiscal_period
  AND a.statement_type = s.statement_type
  AND a.is_stub        = s.is_stub
WHERE (s.status, s.gate_status, s.n_pass, s.n_fail, s.n_pending, s.fail_fields)
   IS DISTINCT FROM
      (a.status, a.gate_status, a.n_pass, a.n_fail, a.n_pending, a.fail_fields);

\echo ''
\echo '=== [4] R33 재개 트리거 — M2_WEAK / E5_HEURISTIC (둘 다 0 이면 A- 예외 미발동) ==='
SELECT (SELECT count(*) FROM face_audit fa, LATERAL jsonb_array_elements(fa.fail_detail) f
        WHERE fa.source_version = 'v3' AND f->>'evidence' = 'M2_WEAK')          AS m2_weak_fields,
       (SELECT count(*) FROM face_audit
        WHERE source_version = 'v3' AND evidence_detail ? 'E5_HEURISTIC')       AS e5_rows;
