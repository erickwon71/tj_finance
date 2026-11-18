-- R342~R345 (2026-11-18): compare std_v3 / extended_facts_v3 after the rebuild with the snapshot
-- from r342_r343_snapshot_2026-11-18.sql. Every changed cell is listed by column; expected changes:
-- short_term_debt / long_term_debt / net_debt only: R342/R342-b aliases, net_debt = -cash (R343), R344 drops
-- non-borrowing lines (payables, leases, provisions, contra accounts, assets) from the debt parts. Any other
-- column changing, or extended_facts_v3 rows other than bs.* debt canonicals, needs a look.
CREATE TEMP TABLE d AS
WITH o AS (SELECT corp_code, fiscal_year, fiscal_period, statement_type,
                  to_jsonb(s) - '{built_at,corp_code,fiscal_year,fiscal_period,statement_type}'::text[] j
           FROM snap_r342_std s),
     n AS (SELECT corp_code, fiscal_year, fiscal_period, statement_type,
                  to_jsonb(f) - '{built_at,corp_code,fiscal_year,fiscal_period,statement_type}'::text[] j
           FROM std_financials_v3 f JOIN snap_r342_corps USING (corp_code))
SELECT coalesce(o.corp_code, n.corp_code) corp_code, coalesce(o.fiscal_year, n.fiscal_year) fy,
       coalesce(o.fiscal_period, n.fiscal_period) fp, coalesce(o.statement_type, n.statement_type) st,
       k.key col, o.j -> k.key old_v, n.j -> k.key new_v
FROM o FULL JOIN n USING (corp_code, fiscal_year, fiscal_period, statement_type)
CROSS JOIN LATERAL (SELECT jsonb_object_keys(coalesce(o.j, n.j)) key) k
WHERE (o.j -> k.key) IS DISTINCT FROM (n.j -> k.key);

\echo == std rows before / after
SELECT (SELECT count(*) FROM snap_r342_std) before,
       (SELECT count(*) FROM std_financials_v3 JOIN snap_r342_corps USING (corp_code)) after;
\echo == changed std cells by column and kind
SELECT col,
       CASE WHEN old_v = 'null' OR old_v IS NULL THEN 'null->value'
            WHEN new_v = 'null' OR new_v IS NULL THEN 'value->null' ELSE 'value->value' END kind,
       count(*) cells, count(DISTINCT corp_code) corps
FROM d GROUP BY 1, 2 ORDER BY 1, 2;
\echo == net_debt null->value: R343 (= -cash, st/lt NULL) vs R342 (debt parts found)
SELECT CASE WHEN (n.net_debt = -n.cash) AND n.short_term_debt IS NULL AND n.long_term_debt IS NULL
            THEN 'R343 debt-free' ELSE 'R342 debt found' END kind, n.fiscal_period = 'FY' fy_row, count(*)
FROM d JOIN std_financials_v3 n ON n.corp_code = d.corp_code AND n.fiscal_year = d.fy
  AND n.fiscal_period = d.fp AND n.statement_type = d.st
WHERE d.col = 'net_debt' AND (d.old_v IS NULL OR d.old_v = 'null') GROUP BY 1, 2 ORDER BY 1, 2;
\echo == columns other than the three debt columns that changed (expected: none, or rows not rebuilt since an older rule)
SELECT col, count(*) FROM d WHERE col NOT IN ('short_term_debt', 'long_term_debt', 'net_debt') GROUP BY 1 ORDER BY 2 DESC;
\echo == net_debt value->value: direction
SELECT CASE WHEN new_v::text::numeric > old_v::text::numeric THEN 'up' ELSE 'down' END dir, count(*)
FROM d WHERE col = 'net_debt' AND NOT (old_v IS NULL OR old_v = 'null' OR new_v IS NULL OR new_v = 'null') GROUP BY 1;
\echo == extended_facts_v3 changes by canonical
WITH o AS (SELECT * FROM snap_r342_ext),
     n AS (SELECT e.* FROM extended_facts_v3 e JOIN snap_r342_corps USING (corp_code))
SELECT coalesce(o.canonical_account, n.canonical_account) canon,
       count(*) FILTER (WHERE o.amount_won IS NULL) added,
       count(*) FILTER (WHERE n.amount_won IS NULL) removed,
       count(*) FILTER (WHERE o.amount_won <> n.amount_won) changed
FROM o FULL JOIN n USING (corp_code, fiscal_year, fiscal_period, statement_type, canonical_account)
WHERE o.amount_won IS DISTINCT FROM n.amount_won GROUP BY 1 ORDER BY 1;
\echo == 2025 FY consolidated DQ<3 net_debt NULL rows (was 392)
SELECT count(*) FROM std_financials_v3 WHERE fiscal_year = 2025 AND fiscal_period = 'FY'
  AND statement_type = 'consolidated' AND data_quality < 3 AND net_debt IS NULL;
\copy (SELECT * FROM d ORDER BY corp_code, fy, fp, st, col) TO 'logs/r342_r343_compare_cells.tsv'
