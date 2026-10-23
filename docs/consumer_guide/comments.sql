-- Table/view level comments for objects consumed by other projects (English).
-- Column comments already present in the DB (Korean) are kept; only gaps are filled here.
-- Applied by scripts/load_consumer_guide.py (idempotent). Full guide: SELECT * FROM consumer_guide ORDER BY ord;

COMMENT ON TABLE consumer_guide IS 'Usage guide for consumers of this DB (layer 3 only). Read first: SELECT section,title,body FROM consumer_guide ORDER BY ord. Source: tj_finance docs/consumer_guide/.';

COMMENT ON TABLE corporations IS 'Company master. stock_code <-> corp_code map; is_active=false for delisted. account_bucket=financial marks banks/insurers/securities (different account structure).';
COMMENT ON TABLE filings IS 'DART periodic reports. filed_at = public disclosure date (use for point-in-time). is_final=true is the version to use; amendments replace originals (superseded_by).';
COMMENT ON TABLE std_financials_v3 IS 'Layer 3 standardized financials. Key (corp_code, fiscal_year, fiscal_period FY/H1/Q1/Q3, statement_type). Flow columns are CUMULATIVE year-to-date; stock columns are period-end. Use data_quality < 3. KRW bigint.';
COMMENT ON TABLE std_financials_calendar IS 'Calendar-aligned financials derived from std_financials_v3. CQ1..CQ4 = discrete single quarters, CY = calendar year. Use version=1 (view calendar_financials). Filter data_quality < 3. No filing date: join filings for point-in-time.';
COMMENT ON VIEW calendar_financials IS 'std_financials_calendar restricted to version=1 (current).';
COMMENT ON VIEW standard_financials IS 'std_financials_v3 plus gate_b_status (independent audit result); rows with fail_a are removed, unaudited kept. Flow columns cumulative YTD.';
COMMENT ON VIEW standard_financials_verified IS 'standard_financials restricted to gate_b_status = pass: highest trust, lower coverage.';
COMMENT ON VIEW extended_financials IS 'Long format of accounts that are not standard columns (canonical_account, amount_won, amount_exact) per (corp_code, fiscal_year, fiscal_period, basis). Cumulative like std_financials_v3.';
COMMENT ON VIEW report_lines_l3 IS 'Layer 3 line items = layer 2 report_lines + tj_finance corrections. value_won = corrected, printed_value_won = as printed, correction_rule = reason. Pass rcept_no as = ANY(ARRAY(SELECT ... FROM filings WHERE is_final)); never join this view to filings (26 GB scan). Do not query report_lines.';
COMMENT ON TABLE stock_prices IS 'Daily KRX prices per stock_code (1990-): OHLCV, market_cap (KRW), shares_out, and KRX-published per/pbr/eps/bps/dps/div_yield.';
COMMENT ON MATERIALIZED VIEW valuation_daily IS 'Daily valuation ratios from market_cap and the latest annual FY row with period_end <= trade_date. Annual (not TTM) and NOT point-in-time (look-ahead before disclosure). Active companies only. Do not use for backtests.';

COMMENT ON COLUMN std_financials_v3.data_quality IS '1 ok, 2 warning (BS identity off 1-5% or gross profit mismatch >5%), 3 error (identity off >5% or total_assets<=0). Use < 3.';
COMMENT ON COLUMN std_financials_v3.consolidation_status IS 'On consolidated rows: consolidated | no_subsidiary_confirmed (equals separate, confirmed) | fallback_unconfirmed (separate shown, unconfirmed). Empty on separate rows.';
COMMENT ON COLUMN std_financials_v3.fiscal_period IS 'FY, H1, Q1, Q3 as reported (no Q2/Q4 rows). Flow columns are cumulative year-to-date.';
COMMENT ON COLUMN std_financials_calendar.data_quality IS '1 ok, 2 a needed flow component was missing in the underlying quarters (common, not an error), 3 error (max over the quarters). Use < 3.';
COMMENT ON COLUMN report_lines_l3.value_won IS 'Corrected value in KRW (equals printed_value_won when correction_rule is NULL).';
COMMENT ON COLUMN report_lines_l3.printed_value_won IS 'Value as printed in the report, KRW.';
COMMENT ON COLUMN report_lines_l3.correction_rule IS 'tj_finance rule id that changed the printed value; NULL = no correction.';
COMMENT ON COLUMN stock_prices.stock_code IS 'KRX ticker; map to corp_code via corporations.';
COMMENT ON TABLE note_lines IS 'NOT for consumers. Layer 2 quality (printed values only): not refined, not verified (deferred by the verification campaign), no layer 3 view. Notes-derived metrics (depreciation, D&A, EBITDA) are already in std_financials_v3 / extended_financials.';
