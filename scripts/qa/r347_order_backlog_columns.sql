-- R347 (2026-11-19): order_backlog layout columns. Additive only; existing values are
-- rewritten by the layer-3 rebuild (scripts/qa/r347_order_backlog_rebuild.sh).
BEGIN;
ALTER TABLE order_backlog
    ADD COLUMN IF NOT EXISTS opening_backlog bigint,
    ADD COLUMN IF NOT EXISTS contract_total  bigint,
    ADD COLUMN IF NOT EXISTS layout          varchar(12);
ALTER TABLE order_backlog_periodic
    ADD COLUMN IF NOT EXISTS opening_backlog bigint,
    ADD COLUMN IF NOT EXISTS contract_total  bigint,
    ADD COLUMN IF NOT EXISTS layout          varchar(12);

COMMENT ON COLUMN order_backlog.layout IS
    'R347 table shape: cumulative = 수주총액|기납품(누적)|수주잔고, rollforward = 기초잔고|당기 수주|당기 매출인식|기말잔고';
COMMENT ON COLUMN order_backlog.backlog_amt IS 'ending order backlog, in the printed unit (unit column)';
COMMENT ON COLUMN order_backlog.opening_backlog IS 'R347 opening backlog (rollforward only)';
COMMENT ON COLUMN order_backlog.new_orders IS
    'R347 period order inflow (rollforward only: new orders plus printed changes such as amendments/FX); NULL for cumulative tables';
COMMENT ON COLUMN order_backlog.completed IS
    'R347 cumulative: delivered/recognised to date; rollforward: recognised in the period (positive)';
COMMENT ON COLUMN order_backlog.contract_total IS 'R347 total contract amount to date (cumulative only)';
COMMENT ON COLUMN order_backlog_periodic.layout IS 'same as order_backlog.layout';
COMMIT;
