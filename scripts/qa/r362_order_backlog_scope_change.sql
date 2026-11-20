-- R362 (2026-11-21): order_backlog scope_change column (business combination / disposal).
-- Additive only; values are filled by re-syncing the affected corps (layer 3).
BEGIN;
ALTER TABLE order_backlog          ADD COLUMN IF NOT EXISTS scope_change bigint;
ALTER TABLE order_backlog_periodic ADD COLUMN IF NOT EXISTS scope_change bigint;
COMMENT ON COLUMN order_backlog.scope_change IS
    'R362 backlog added or removed by a business combination / merger / disposal of a subsidiary, printed sign (rollforward only); not part of new_orders';
COMMENT ON COLUMN order_backlog_periodic.scope_change IS 'same as order_backlog.scope_change';
COMMIT;
