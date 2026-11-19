-- tj_asset request 3: corps with 2024 sales rows but no 2025 sales rows, with the reason class.
WITH f AS (SELECT DISTINCT corp_code FROM std_financials_v3 WHERE fiscal_year = 2025 AND fiscal_period = 'FY' AND data_quality < 3),
     b25 AS (SELECT DISTINCT corp_code FROM biz_metrics WHERE metric = 'sales' AND fiscal_year = 2025),
     b24 AS (SELECT DISTINCT corp_code FROM biz_metrics WHERE metric = 'sales' AND fiscal_year = 2024),
     m AS (SELECT corp_code FROM f JOIN b24 USING (corp_code) LEFT JOIN b25 USING (corp_code) WHERE b25.corp_code IS NULL),
     fl AS (SELECT m.corp_code, array_agg(fl.rcept_no ORDER BY fl.rcept_no) AS rcepts
            FROM m LEFT JOIN filings fl ON fl.corp_code = m.corp_code AND fl.report_type = 'annual' AND fl.fiscal_year = 2025
            GROUP BY 1),
     t AS (SELECT fl.corp_code,
                  count(*) FILTER (WHERE bt.domain = 'sales') AS sales_tables,
                  count(*) FILTER (WHERE bt.domain = 'catalog' AND bt.metric = 'sales') AS catalog_sales_tables,
                  count(bt.*) AS all_biz_tables
           FROM fl LEFT JOIN biz_section_tables bt ON bt.rcept_no = ANY (fl.rcepts) GROUP BY 1)
SELECT c.stock_code, c.corp_name, t.corp_code, t.all_biz_tables, t.sales_tables, t.catalog_sales_tables,
       CASE WHEN t.sales_tables + t.catalog_sales_tables = 0 THEN 'no sales table in layer 2'
            ELSE 'sales table present, mapper yields 0 rows' END AS reason
FROM t JOIN corporations c USING (corp_code) ORDER BY reason, c.corp_name;
