-- R347 before/after comparison. Snapshots: zz_snap_r347_order_backlog(_periodic), taken 2026-11-19 before the rebuild.
\echo '== tj_asset check (fiscal_year >= 2023): numeric text in category, new_orders NULL, completed < 0'
SELECT 'before' AS side, count(*) AS rows,
       count(*) FILTER (WHERE category ~ '[0-9],[0-9]{3}') AS numcat,
       count(*) FILTER (WHERE new_orders IS NULL) AS new_null,
       count(*) FILTER (WHERE completed < 0) AS neg_completed,
       count(DISTINCT corp_code) AS corps
FROM zz_snap_r347_order_backlog WHERE fiscal_year >= 2023
UNION ALL
SELECT 'after', count(*), count(*) FILTER (WHERE category ~ '[0-9],[0-9]{3}'),
       count(*) FILTER (WHERE new_orders IS NULL), count(*) FILTER (WHERE completed < 0),
       count(DISTINCT corp_code)
FROM order_backlog WHERE fiscal_year >= 2023;

\echo '== after, by layout (fiscal_year >= 2023)'
SELECT layout, count(*) AS rows, count(DISTINCT corp_code) AS corps,
       count(*) FILTER (WHERE layout = 'rollforward' AND opening_backlog IS NOT NULL AND new_orders IS NOT NULL
                          AND completed IS NOT NULL) AS rf_full,
       count(*) FILTER (WHERE layout = 'rollforward' AND abs(opening_backlog + new_orders - completed - backlog_amt)
                          <= greatest(2, 0.005 * abs(backlog_amt))) AS rf_identity_ok,
       count(*) FILTER (WHERE layout = 'cumulative' AND contract_total IS NOT NULL AND completed IS NOT NULL) AS cum_full,
       count(*) FILTER (WHERE layout = 'cumulative' AND abs(contract_total - completed - backlog_amt)
                          <= greatest(2, 0.005 * abs(backlog_amt))) AS cum_identity_ok
FROM order_backlog WHERE fiscal_year >= 2023 GROUP BY 1 ORDER BY 1;

\echo '== all years: rows and (corp, year) coverage'
SELECT 'before' AS side, count(*) AS rows, count(DISTINCT (corp_code, fiscal_year)) AS corp_years,
       count(*) FILTER (WHERE category ~ '[0-9],[0-9]{3}') AS numcat FROM zz_snap_r347_order_backlog
UNION ALL
SELECT 'after', count(*), count(DISTINCT (corp_code, fiscal_year)), count(*) FILTER (WHERE category ~ '[0-9],[0-9]{3}') FROM order_backlog
UNION ALL
SELECT 'p_before', count(*), count(DISTINCT (corp_code, fiscal_year, fiscal_period)),
       count(*) FILTER (WHERE category ~ '[0-9],[0-9]{3}') FROM zz_snap_r347_order_backlog_periodic
UNION ALL
SELECT 'p_after', count(*), count(DISTINCT (corp_code, fiscal_year, fiscal_period)),
       count(*) FILTER (WHERE category ~ '[0-9],[0-9]{3}') FROM order_backlog_periodic;

\echo '== (corp, year) present before but gone after'
SELECT count(*) AS lost_corp_years FROM (
  SELECT DISTINCT corp_code, fiscal_year FROM zz_snap_r347_order_backlog
  EXCEPT SELECT DISTINCT corp_code, fiscal_year FROM order_backlog) x;

\echo '== per (corp, year) total backlog (sum over categories) before vs after, all years'
WITH b AS (SELECT corp_code, fiscal_year, sum(backlog_amt) s FROM zz_snap_r347_order_backlog GROUP BY 1, 2),
     a AS (SELECT corp_code, fiscal_year, sum(backlog_amt) s FROM order_backlog GROUP BY 1, 2)
SELECT count(*) FILTER (WHERE a.s IS NOT DISTINCT FROM b.s) AS same,
       count(*) FILTER (WHERE a.s IS DISTINCT FROM b.s) AS changed
FROM b JOIN a USING (corp_code, fiscal_year);

\echo '== tj_asset example 00406046'
SELECT fiscal_year, category, layout, opening_backlog, new_orders, completed, backlog_amt, contract_total, unit
FROM order_backlog WHERE corp_code = '00406046' AND fiscal_year >= 2024 ORDER BY 1, 2;
