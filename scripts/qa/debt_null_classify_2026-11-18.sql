CREATE TEMP TABLE x AS
SELECT f.corp_code, f.source_rcepts->>'BS' rc, f.short_term_debt, f.long_term_debt, f.net_debt, f.cash, f.total_liabilities, f.basis_fallback
FROM std_financials_v3 f WHERE fiscal_period='FY' AND fiscal_year=2025 AND statement_type='consolidated' AND data_quality<3;
CREATE TEMP TABLE bsl AS
SELECT x.corp_code, bool_or(true) has_bs,
  bool_or(rl.label_raw ~ '(차입|사채|borrow|Borrow)' AND rl.label_raw !~ '(대여|이자|리스)' ) has_debt_label,
  bool_or(rl.label_raw ~ '(차입|사채)' AND rl.label_raw !~ '(대여|이자|리스)' AND coalesce(rl.value_won,0)<>0) has_debt_value
FROM x JOIN report_lines rl ON rl.rcept_no=x.rc AND rl.statement='BS' AND rl.context_fiscal_year=2025
 AND rl.basis = CASE WHEN x.basis_fallback THEN 'separate' ELSE 'consolidated' END
GROUP BY 1;
\echo == net_debt NULL rows by evidence
SELECT CASE WHEN x.cash IS NULL THEN '0_cash_null'
            WHEN b.corp_code IS NULL THEN '1_no_bs_lines'
            WHEN NOT b.has_debt_value THEN '2_no_debt_line_with_value (debt-free?)'
            ELSE '3_debt_line_exists_but_unmapped' END cls, count(*)
FROM x LEFT JOIN bsl b USING (corp_code) WHERE x.net_debt IS NULL GROUP BY 1 ORDER BY 1;
\echo == short_term_debt NULL rows by evidence (net_debt present?)
SELECT (x.net_debt IS NOT NULL) nd_present, coalesce(b.has_debt_value,false) bs_has_debt, count(*)
FROM x LEFT JOIN bsl b USING (corp_code) WHERE x.short_term_debt IS NULL GROUP BY 1,2 ORDER BY 1,2;
\echo == sample class 3
SELECT c.corp_name, x.corp_code, x.rc FROM x JOIN bsl b USING (corp_code) JOIN corporations c USING (corp_code)
WHERE x.net_debt IS NULL AND x.cash IS NOT NULL AND b.has_debt_value ORDER BY random() LIMIT 6;
