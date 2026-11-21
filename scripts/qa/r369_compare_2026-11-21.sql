-- R369 (2026-11-21): compare after the rebuild with r369_snapshot. Expected: std_financials_v3 unchanged
-- (apart from built_at); extended_facts_v3 only gains rows of the five R369 accounts.
\echo == std rows before / after
SELECT (SELECT count(*) FROM snap_r369_std) before, (SELECT count(*) FROM std_financials_v3) after;
\echo == std cells changed (expected 0 rows except rules newer than the last build)
WITH o AS (SELECT corp_code, fiscal_year, fiscal_period, statement_type,
                  to_jsonb(s) - '{built_at}'::text[] j FROM snap_r369_std s),
     n AS (SELECT corp_code, fiscal_year, fiscal_period, statement_type,
                  to_jsonb(f) - '{built_at}'::text[] j FROM std_financials_v3 f)
SELECT count(*) FILTER (WHERE o.j IS NULL) added, count(*) FILTER (WHERE n.j IS NULL) removed,
       count(*) FILTER (WHERE o.j IS NOT NULL AND n.j IS NOT NULL AND o.j <> n.j) changed
FROM o FULL JOIN n USING (corp_code, fiscal_year, fiscal_period, statement_type);
\echo == extended_facts_v3 rows before / after
SELECT (SELECT count(*) FROM snap_r369_ext) before, (SELECT count(*) FROM extended_facts_v3) after;
\echo == extended changes by canonical and kind
WITH o AS (SELECT * FROM snap_r369_ext), n AS (SELECT * FROM extended_facts_v3)
SELECT coalesce(o.canonical_account, n.canonical_account) canon,
       CASE WHEN o.amount_won IS NULL THEN 'added' WHEN n.amount_won IS NULL THEN 'removed' ELSE 'changed' END kind,
       count(*) cells, count(DISTINCT coalesce(o.corp_code, n.corp_code)) corps
FROM o FULL JOIN n USING (corp_code, fiscal_year, fiscal_period, statement_type, canonical_account)
WHERE o.amount_won IS DISTINCT FROM n.amount_won OR o.amount_exact IS DISTINCT FROM n.amount_exact
GROUP BY 1, 2 ORDER BY 2, 1;
\echo == R369 account coverage by fiscal period type
SELECT canonical_account, fiscal_period, count(*) cells, count(DISTINCT corp_code) corps
FROM extended_facts_v3 WHERE canonical_account IN ('is.impairment_loss','is.impairment_reversal','is.disposal_gain','is.disposal_loss','is.debt_forgiveness_gain')
  AND statement_type = 'consolidated' GROUP BY 1, 2 ORDER BY 1, 2;
