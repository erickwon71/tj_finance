WITH x AS (SELECT f.corp_code, f.source_rcepts->>'BS' rc, f.basis_fallback FROM std_financials_v3 f
  WHERE fiscal_period='FY' AND fiscal_year=2025 AND statement_type='consolidated' AND data_quality<3 AND net_debt IS NULL AND cash IS NOT NULL)
SELECT regexp_replace(rl.label_raw,'\s+','','g') label, count(DISTINCT x.corp_code) corps, min(rl.section_path) sp
FROM x JOIN report_lines rl ON rl.rcept_no=x.rc AND rl.statement='BS' AND rl.context_fiscal_year=2025
 AND rl.basis = CASE WHEN x.basis_fallback THEN 'separate' ELSE 'consolidated' END
WHERE rl.label_raw ~ '(차입|사채)' AND rl.label_raw !~ '(대여|이자|리스)' AND coalesce(rl.value_won,0)<>0
GROUP BY 1 ORDER BY 2 DESC LIMIT 30;
