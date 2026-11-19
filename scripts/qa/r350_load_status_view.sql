-- R350 (2026-11-19, user decision: a view, no new table). Read-only freshness view for consumers.
-- One row per item. A reader checks `stale` (or compares data_through with today) before trusting
-- the data. Every part is an index lookup, so the view is cheap to read.
BEGIN;
CREATE OR REPLACE VIEW load_status AS
WITH runs AS (
    SELECT DISTINCT ON (mode) mode, started_at, finished_at, status
    FROM pipeline_runs ORDER BY mode, started_at DESC
), ok AS (
    SELECT DISTINCT ON (mode) mode, finished_at, window_end
    FROM pipeline_runs WHERE status = 'success' ORDER BY mode, window_end DESC, finished_at DESC
)
SELECT 'pipeline:' || r.mode AS item,
       r.started_at          AS last_run_at,
       r.status              AS last_status,
       ok.finished_at        AS last_success_at,
       ok.window_end         AS data_through,
       NULL::text            AS version,
       (ok.window_end IS NULL OR ok.window_end < current_date - 4) AS stale,
       'daily DART collection; data_through = end of the last fully successful window'::text AS note
FROM runs r LEFT JOIN ok USING (mode)
WHERE r.started_at > now() - interval '30 days'  -- retired modes (download_only, 2026-08) drop out
UNION ALL
SELECT 'filings', NULL, NULL, NULL, (SELECT max(filed_at)::date FROM filings), NULL,
       (SELECT max(filed_at)::date FROM filings) < current_date - 4,
       'latest filed_at among collected periodic reports'
UNION ALL
SELECT 'capital_events', NULL, NULL, max(fetched_at), max(filed_at), NULL,
       max(fetched_at) < now() - interval '4 days',
       'latest filed_at / fetched_at of share-count events (bonus issue, split, ...)'
FROM capital_events
UNION ALL
SELECT 'stock_prices', NULL, NULL, NULL,
       (SELECT max(trade_date) FROM stock_prices WHERE stock_code = '005930'), NULL,
       (SELECT max(trade_date) FROM stock_prices WHERE stock_code = '005930') < current_date - 4,
       'latest trade_date (probe: 005930)'
UNION ALL
SELECT 'consumer_guide', NULL, NULL, max(updated_at), NULL, max(guide_version), false,
       'guide_version changes whenever any section changes; re-read consumer_guide when it differs'
FROM consumer_guide;

COMMENT ON VIEW load_status IS
    'R350 freshness per item (pipeline runs, filings, capital_events, stock_prices, consumer_guide). stale = no successful data in the last 4 days.';
GRANT SELECT ON load_status TO tja_reader;
GRANT SELECT ON pipeline_runs TO tja_reader;
COMMIT;
