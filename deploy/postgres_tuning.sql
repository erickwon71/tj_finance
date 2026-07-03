-- P1-D4 · PostgreSQL 튜닝 (tj_finance, 16GB RAM, SSD, 단일 사용자 분석 워크로드)
--
-- 스톡 기본값은 89GB 분석 DB 엔 과소. ALTER SYSTEM(=postgresql.auto.conf, 되돌리기 쉬움)으로 조정.
-- 적용:  psql -f deploy/postgres_tuning.sql tj_finance
--        brew services restart postgresql@15    # shared_buffers 는 재시작 필요
-- 되돌리기:  ALTER SYSTEM RESET ALL;  (또는 개별 RESET) → reload/restart
--
-- 재시작 필요: shared_buffers.  나머지는 reload(SIGHUP)로 반영.

ALTER SYSTEM SET shared_buffers = '4GB';                 -- ~25% RAM (기존 128MB)
ALTER SYSTEM SET effective_cache_size = '10GB';          -- OS 캐시 가정치 (기존 4GB)
ALTER SYSTEM SET work_mem = '64MB';                      -- 정렬/해시 per-op (기존 4MB; 연결 소수라 안전)
ALTER SYSTEM SET maintenance_work_mem = '1GB';           -- VACUUM/인덱스빌드 (기존 64MB)
ALTER SYSTEM SET random_page_cost = 1.1;                 -- SSD (기존 4)
-- effective_io_concurrency: macOS 는 posix_fadvise 미지원이라 0만 허용 → 설정하지 않음(Linux 서버면 200).
ALTER SYSTEM SET max_wal_size = '4GB';                   -- 체크포인트 빈도 완화 (기존 1GB)
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;    -- 대형 스캔 병렬 (기존 2)

-- fact_v2(87M행)는 dead 누적이 커도 autovacuum 이 늦게 도는 문제 → 테이블별 임계 하향.
ALTER TABLE fact_v2 SET (autovacuum_vacuum_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02);

SELECT pg_reload_conf();  -- reload 가능한 항목 즉시 반영(shared_buffers 는 재시작 후)
