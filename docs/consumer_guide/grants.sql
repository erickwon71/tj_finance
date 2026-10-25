-- Read access of the consumer role tja_reader: an allowlist of the objects the guide documents
-- (financial objects s02-s07 and the structured disclosure tables s10).
-- Applied by scripts/load_consumer_guide.py (idempotent). Layer 2 (report_lines), note_lines and all
-- internal snapshot / audit / queue tables are NOT readable; report_lines_l3 and the standard views
-- run with their owner's rights, so they keep working without access to the tables under them.
-- Plan: docs/plans/consumer_guide_in_db_2026-10-23.md. Previous grants: grants_before_2026-10-25.txt.
DO $$
DECLARE
    r record;
    allow text[] := ARRAY[
        'consumer_guide', 'corporations', 'filings',
        'std_financials_v3', 'standard_financials', 'standard_financials_verified',
        'std_financials_calendar', 'calendar_financials', 'extended_financials',
        'report_lines_l3', 'stock_prices', 'valuation_daily',
        -- structured disclosure tables (s10_structured)
        'biz_metrics', 'capital_events', 'dividend_facts', 'employee_stats', 'exec_pay_individual',
        'exec_pay_summary', 'executives', 'major_shareholders', 'order_backlog', 'other_investments',
        'regulatory_events', 'report_shares_outstanding', 'retail_ownership', 'shareholder_changes',
        'treasury_activity'];
BEGIN
    FOR r IN SELECT c.oid::regclass AS rel, c.relname FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm', 'p')
               AND c.relname <> ALL(allow)
               AND has_table_privilege('tja_reader', c.oid, 'SELECT')
    LOOP
        EXECUTE format('REVOKE ALL ON %s FROM tja_reader', r.rel);
    END LOOP;
    FOR r IN SELECT c.oid::regclass AS rel FROM pg_class c
             JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm', 'p') AND c.relname = ANY(allow)
    LOOP
        EXECUTE format('GRANT SELECT ON %s TO tja_reader', r.rel);
    END LOOP;
END $$;
-- new tables must not become readable by default (they were: SELECT was granted on creation)
ALTER DEFAULT PRIVILEGES FOR ROLE taejin IN SCHEMA public REVOKE SELECT ON TABLES FROM tja_reader;
