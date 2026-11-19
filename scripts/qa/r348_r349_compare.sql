-- R348/R349 before/after (snapshots zz_snap_r348_biz_metrics(_periodic) = affected corp-years before rebuild)
\echo '== tj_asset check 3: 2025 FY sales rows, unit NULL, period_year NULL'
SELECT count(*) AS rows, count(*) FILTER (WHERE unit IS NULL) AS unit_null,
       count(*) FILTER (WHERE period_year IS NULL) AS period_year_null, count(DISTINCT corp_code) AS corps
FROM biz_metrics WHERE metric = 'sales' AND fiscal_year = 2025;

\echo '== tj_asset check 3: corps with 2024 sales but no 2025 sales (2025 FY financials loaded)'
WITH f AS (SELECT DISTINCT corp_code FROM std_financials_v3 WHERE fiscal_year = 2025 AND fiscal_period = 'FY' AND data_quality < 3),
     b25 AS (SELECT DISTINCT corp_code FROM biz_metrics WHERE metric = 'sales' AND fiscal_year = 2025),
     b24 AS (SELECT DISTINCT corp_code FROM biz_metrics WHERE metric = 'sales' AND fiscal_year = 2024)
SELECT count(*) AS missing_2025 FROM f JOIN b24 USING (corp_code) LEFT JOIN b25 USING (corp_code) WHERE b25.corp_code IS NULL;

\echo '== affected corp-years, sales rows before/after (annual / periodic)'
WITH a AS (SELECT DISTINCT corp_code, fiscal_year FROM zz_r348_affected WHERE report_type = 'annual')
SELECT 'annual' AS t,
       (SELECT count(*) FROM zz_snap_r348_biz_metrics WHERE metric = 'sales') AS before_sales,
       (SELECT count(*) FROM biz_metrics b JOIN a USING (corp_code, fiscal_year) WHERE metric = 'sales') AS after_sales,
       (SELECT count(*) FROM zz_snap_r348_biz_metrics WHERE metric <> 'sales') AS before_other,
       (SELECT count(*) FROM biz_metrics b JOIN a USING (corp_code, fiscal_year) WHERE metric <> 'sales') AS after_other
UNION ALL
SELECT 'periodic',
       (SELECT count(*) FROM zz_snap_r348_biz_metrics_periodic WHERE metric = 'sales'),
       (SELECT count(*) FROM biz_metrics_periodic b JOIN (SELECT DISTINCT corp_code, fiscal_year FROM zz_r348_affected WHERE report_type <> 'annual') p USING (corp_code, fiscal_year) WHERE metric = 'sales'),
       (SELECT count(*) FROM zz_snap_r348_biz_metrics_periodic WHERE metric <> 'sales'),
       (SELECT count(*) FROM biz_metrics_periodic b JOIN (SELECT DISTINCT corp_code, fiscal_year FROM zz_r348_affected WHERE report_type <> 'annual') p USING (corp_code, fiscal_year) WHERE metric <> 'sales');

\echo '== example 티앤엘 00608440'
SELECT fiscal_year, count(*) AS sales_rows, count(*) FILTER (WHERE unit IS NULL) AS unit_null
FROM biz_metrics WHERE corp_code = '00608440' AND metric = 'sales' AND fiscal_year >= 2023 GROUP BY 1 ORDER BY 1;
