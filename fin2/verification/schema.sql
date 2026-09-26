-- verification schema — DB-resident state for the DART-vs-DB verification campaign.
-- Design: docs/plans/verification_schema_two_worktree_design_2026-09-24.md
--
-- Applied by collector/db.py migration "2026_09_24_verification_schema" (driver-level
-- execute, so this file may use PL/pgSQL freely). Every statement is idempotent so the
-- file can be re-applied after edits during development.
--
-- NOTE: executed through the raw DB-API cursor with no parameters (see apply_schema), so
-- PL/pgSQL RAISE placeholders are safe here.

CREATE SCHEMA IF NOT EXISTS verification;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tjf_verify') THEN
        CREATE ROLE tjf_verify LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tjf_fix') THEN
        CREATE ROLE tjf_fix LOGIN;
    END IF;
END $$;

-- ───────────────────────────── actor helpers ─────────────────────────────
-- Role = which worktree kind is acting. Decided by the *login* role (session_user), so a
-- SECURITY DEFINER function further down the call stack cannot launder it.
CREATE OR REPLACE FUNCTION verification.actor_role() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT CASE session_user::text
             WHEN 'tjf_verify' THEN 'verify'
             WHEN 'tjf_fix'    THEN 'fix'
             ELSE 'admin' END
$$;

-- Free-form actor label (worktree name) set by collector/db.py on connect.
CREATE OR REPLACE FUNCTION verification.actor() RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT coalesce(nullif(current_setting('verification.actor', true), ''),
                    session_user::text)
$$;

CREATE OR REPLACE FUNCTION verification.guc(p_name text) RETURNS text
LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('verification.' || p_name, true), '')
$$;

-- ───────────────────────────── lookup tables ─────────────────────────────
CREATE TABLE IF NOT EXISTS verification.error_types (
    code        varchar(32) PRIMARY KEY,
    label_ko    text NOT NULL,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO verification.error_types (code, label_ko, description) VALUES
    ('missing_row',      '행 누락',       'row present in the source table is absent in DB'),
    ('extra_row',        '잉여 행',       'DB has a row the source table does not have'),
    ('value_mismatch',   '값 불일치',     'same row, different amount'),
    ('sign_flip',        '부호 반전',     'amount matches in magnitude but sign is reversed'),
    ('unit_scale',       '단위 배수',     'amount off by a power of ten (unit misread)'),
    ('column_misassign', '열 오귀속',     'value taken from the wrong column (SCE component, period)'),
    ('period_misassign', '기간 오귀속',   '3-month vs cumulative / current vs prior period mixed up'),
    ('label_mismatch',   '계정명 불일치', 'value right, label wrong or truncated'),
    ('source_defect',    '원문 자체 오류', 'the DART source itself is inconsistent or has a typo'),
    ('unclassified',     '미분류(신규 패턴)', 'new pattern; fix worktree proposes a proper code via vq.py ask')
ON CONFLICT (code) DO NOTHING;

-- ───────────────────────────── progress ─────────────────────────────
CREATE TABLE IF NOT EXISTS verification.progress (
    corp_code       varchar(8)  NOT NULL REFERENCES public.corporations(corp_code),
    fiscal_year     smallint    NOT NULL,
    fiscal_period   varchar(2)  NOT NULL CHECK (fiscal_period IN ('Q1', 'H1', 'Q3', 'FY')),
    era             varchar(8)  NOT NULL,
    era_rank        smallint    NOT NULL,
    corp_rank       integer,
    status          varchar(12) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'passed', 'has_issues', 'blocked')),
    claimed_by      text,
    claimed_at      timestamptz,
    lease_until     timestamptz,
    retry_count     smallint    NOT NULL DEFAULT 0,
    n_open_issues   integer     NOT NULL DEFAULT 0,
    passed_at       timestamptz,
    note            text CHECK (length(note) <= 2000),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (corp_code, fiscal_year, fiscal_period)
);
CREATE INDEX IF NOT EXISTS ix_vprogress_pick
    ON verification.progress (era_rank, corp_rank, fiscal_year DESC, fiscal_period)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS ix_vprogress_status ON verification.progress (status);

CREATE TABLE IF NOT EXISTS verification.progress_filings (
    rcept_no            varchar(14) PRIMARY KEY REFERENCES public.filings(rcept_no),
    corp_code           varchar(8)  NOT NULL,
    fiscal_year         smallint    NOT NULL,
    fiscal_period       varchar(2)  NOT NULL,
    seq_in_slot         smallint    NOT NULL DEFAULT 1,
    is_amendment        boolean     NOT NULL DEFAULT false,
    status              varchar(12) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'passed', 'has_issues', 'skipped')),
    claim_load_seq      integer,
    verified_load_seq   integer,
    verified_scopes     text[],
    verified_scope_hashes jsonb,
    verified_at         timestamptz,
    verified_by         text,
    note                text CHECK (length(note) <= 2000),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (corp_code, fiscal_year, fiscal_period)
        REFERENCES verification.progress (corp_code, fiscal_year, fiscal_period)
);
CREATE INDEX IF NOT EXISTS ix_vpf_slot
    ON verification.progress_filings (corp_code, fiscal_year, fiscal_period);

-- ───────────────────────────── load stamping ─────────────────────────────
-- One row per rcept: the *content version* of its report_lines. load_seq only moves when the
-- content hash changes, so an identical re-parse does not invalidate a verdict.
CREATE TABLE IF NOT EXISTS verification.filing_loads (
    rcept_no        varchar(14) PRIMARY KEY REFERENCES public.filings(rcept_no),
    load_seq        integer     NOT NULL,
    content_hash    text        NOT NULL,
    scope_hashes    jsonb       NOT NULL,
    n_lines         integer     NOT NULL,
    parser_commit   text,
    loaded_by       text,
    reason          text,
    baseline        boolean     NOT NULL DEFAULT false,
    loaded_at       timestamptz NOT NULL DEFAULT now(),
    last_checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verification.filing_load_events (
    event_id        bigserial PRIMARY KEY,
    rcept_no        varchar(14) NOT NULL,
    load_seq        integer     NOT NULL,
    content_hash    text        NOT NULL,
    changed_scopes  text[],
    n_lines         integer     NOT NULL,
    parser_commit   text,
    loaded_by       text,
    db_role         text,
    reason          text,
    at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_vfle_rcept ON verification.filing_load_events (rcept_no, load_seq);

-- Transient: rcepts touched by the current transaction. Rows live only until commit.
CREATE TABLE IF NOT EXISTS verification.load_dirty (
    rcept_no varchar(14) NOT NULL,
    txid     bigint      NOT NULL,
    PRIMARY KEY (rcept_no, txid)
);

-- ───────────────────────────── fix batches ─────────────────────────────
CREATE TABLE IF NOT EXISTS verification.fix_batches (
    batch_id        bigserial PRIMARY KEY,
    error_type      varchar(32) NOT NULL REFERENCES verification.error_types(code),
    rule_id         varchar(16),
    title           text NOT NULL CHECK (length(title) <= 200),
    status          varchar(16) NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'waiting_decision', 'reloading', 'done', 'abandoned')),
    commit_sha      text,
    note            text CHECK (length(note) <= 4000),
    created_by      text NOT NULL DEFAULT verification.actor(),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    done_at         timestamptz
);

CREATE TABLE IF NOT EXISTS verification.batch_targets (
    batch_id    bigint      NOT NULL REFERENCES verification.fix_batches(batch_id),
    rcept_no    varchar(14) NOT NULL REFERENCES public.filings(rcept_no),
    status      varchar(10) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'done', 'deferred', 'failed')),
    attempts    smallint    NOT NULL DEFAULT 0,
    last_error  text CHECK (length(last_error) <= 1000),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (batch_id, rcept_no)
);

-- ───────────────────────────── issues ─────────────────────────────
CREATE TABLE IF NOT EXISTS verification.issues (
    issue_id            bigserial PRIMARY KEY,
    corp_code           varchar(8)  NOT NULL,
    fiscal_year         smallint    NOT NULL,
    fiscal_period       varchar(2)  NOT NULL,
    rcept_no            varchar(14) NOT NULL REFERENCES public.filings(rcept_no),
    basis               varchar(12) NOT NULL CHECK (basis IN ('consolidated', 'separate')),
    statement           varchar(4)  NOT NULL CHECK (statement IN ('BS', 'IS', 'CIS', 'CF', 'SCE')),
    account_label       text NOT NULL CHECK (length(account_label) <= 300),
    column_label        text CHECK (length(column_label) <= 200),
    db_label            text CHECK (length(db_label) <= 300),
    db_row_order        integer,
    db_value            numeric,
    source_value        numeric,
    source_value_raw    text CHECK (length(source_value_raw) <= 200),
    source_unit         varchar(8) CHECK (source_unit IN ('원', '천원', '백만원', '억원')),
    error_type          varchar(32) NOT NULL REFERENCES verification.error_types(code),
    status              varchar(10) NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'fixing', 'fixed', 'closed', 'reopened')),
    found_load_seq      integer,
    found_parser_commit text,
    fixed_parser_commit text,
    fixed_load_seq      integer,
    fix_batch_id        bigint REFERENCES verification.fix_batches(batch_id),
    rule_id             varchar(16),
    dart_url            text CHECK (length(dart_url) <= 300),
    evidence            text CHECK (length(evidence) <= 2000),
    legacy_ref          text CHECK (length(legacy_ref) <= 200),
    created_by          text NOT NULL DEFAULT verification.actor(),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vissues_active_cell
    ON verification.issues (rcept_no, basis, statement, account_label, coalesce(column_label, ''))
    WHERE status <> 'closed';
CREATE INDEX IF NOT EXISTS ix_vissues_fixq ON verification.issues (status, error_type);
CREATE INDEX IF NOT EXISTS ix_vissues_slot
    ON verification.issues (corp_code, fiscal_year, fiscal_period);
CREATE INDEX IF NOT EXISTS ix_vissues_batch ON verification.issues (fix_batch_id);

-- ───────────────────────────── history (append-only) ─────────────────────────────
CREATE TABLE IF NOT EXISTS verification.issue_events (
    event_id    bigserial PRIMARY KEY,
    issue_id    bigint NOT NULL,
    action      varchar(12) NOT NULL,
    from_status varchar(10),
    to_status   varchar(10),
    actor       text NOT NULL,
    db_role     text NOT NULL,
    evidence    text,
    commit_sha  text,
    load_seq    integer,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_vie_issue ON verification.issue_events (issue_id, event_id);

CREATE TABLE IF NOT EXISTS verification.progress_events (
    event_id      bigserial PRIMARY KEY,
    corp_code     varchar(8) NOT NULL,
    fiscal_year   smallint   NOT NULL,
    fiscal_period varchar(2) NOT NULL,
    rcept_no      varchar(14),
    action        varchar(24) NOT NULL,
    from_status   varchar(12),
    to_status     varchar(12),
    actor         text NOT NULL,
    db_role       text NOT NULL,
    evidence      text,
    load_seq      integer,
    at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_vpe_slot
    ON verification.progress_events (corp_code, fiscal_year, fiscal_period, event_id);

-- ───────────────────────────── machine comparison ─────────────────────────────
-- One row per rcept: the latest machine comparison (fin2/verification/machine_compare.py)
-- of its report_lines against the source XML. Valid only while load_seq matches
-- filing_loads.load_seq - a reload makes it stale and the machine pass re-checks it.
-- clean   -> the machine passed the filing (progress_filings.verified_by = '<wt>:machine')
-- others  -> the model reviewer looks at `findings` in the web view (vq.py show lists them)
-- audit   -> clean, but the slot was drawn for the 1% web-view re-check (full comparison)
CREATE TABLE IF NOT EXISTS verification.machine_checks (
    rcept_no     varchar(14) PRIMARY KEY REFERENCES public.filings(rcept_no),
    load_seq     integer     NOT NULL,
    tool_version text        NOT NULL,
    verdict      varchar(12) NOT NULL
                 CHECK (verdict IN ('clean', 'mismatch', 'no_source', 'no_structure', 'error')),
    audit        boolean     NOT NULL DEFAULT false,
    counts       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    findings     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    checked_at   timestamptz NOT NULL DEFAULT now(),
    checked_by   text        NOT NULL DEFAULT verification.actor()
);
CREATE INDEX IF NOT EXISTS ix_vmc_verdict ON verification.machine_checks (verdict);

-- ───────────────────────────── runner + decisions ─────────────────────────────
CREATE TABLE IF NOT EXISTS verification.runner_runs (
    run_id        bigserial PRIMARY KEY,
    worktree      text NOT NULL,
    corp_code     varchar(8),
    fiscal_year   smallint,
    fiscal_period varchar(2),
    started_at    timestamptz NOT NULL DEFAULT now(),
    ended_at      timestamptz,
    exit_code     integer,
    num_turns     integer,
    input_tokens  bigint,
    output_tokens bigint,
    cost_usd      numeric(10, 4),
    model         text,
    outcome       varchar(12) CHECK (outcome IN
                  ('passed', 'has_issues', 'incomplete', 'timeout', 'usage_limit', 'error',
                   'blocked', 'tool_denied')),
    log_path      text,
    git_head      text
);
CREATE INDEX IF NOT EXISTS ix_vrr_started ON verification.runner_runs (started_at);
-- 2026-09-26: add 'tool_denied' outcome (handoff §2). CREATE TABLE above is a no-op once the
-- table exists, so the CHECK on an already-live table needs its own idempotent migration.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'verification.runner_runs'::regclass
                      AND conname = 'runner_runs_outcome_check'
                      AND pg_get_constraintdef(oid) LIKE '%tool_denied%') THEN
        ALTER TABLE verification.runner_runs DROP CONSTRAINT IF EXISTS runner_runs_outcome_check;
        ALTER TABLE verification.runner_runs ADD CONSTRAINT runner_runs_outcome_check
            CHECK (outcome IN ('passed', 'has_issues', 'incomplete', 'timeout', 'usage_limit',
                                'error', 'blocked', 'tool_denied'));
    END IF;
END $$;
-- Account usage (percent of the 5-hour / 7-day limits) at run start and end, from the
-- claude-dashboard usage probe. Other sessions share the account, so a delta is an upper
-- bound for the run, not an exact cost - good enough to size the runner budget.
ALTER TABLE verification.runner_runs ADD COLUMN IF NOT EXISTS usage_5h_start numeric(5, 1);
ALTER TABLE verification.runner_runs ADD COLUMN IF NOT EXISTS usage_5h_end   numeric(5, 1);
ALTER TABLE verification.runner_runs ADD COLUMN IF NOT EXISTS usage_7d_start numeric(5, 1);
ALTER TABLE verification.runner_runs ADD COLUMN IF NOT EXISTS usage_7d_end   numeric(5, 1);

CREATE TABLE IF NOT EXISTS verification.decisions (
    decision_id   bigserial PRIMARY KEY,
    category      varchar(20) NOT NULL
                  CHECK (category IN ('irreversible', 'policy', 'scope', 'source_ambiguity')),
    asked_by      text NOT NULL DEFAULT verification.actor(),
    batch_id      bigint REFERENCES verification.fix_batches(batch_id),
    issue_id      bigint REFERENCES verification.issues(issue_id),
    question      text NOT NULL CHECK (length(question) <= 200),
    options       jsonb NOT NULL,
    recommended   varchar(8) NOT NULL,
    dedupe_key    text NOT NULL CHECK (length(dedupe_key) <= 200),
    status        varchar(10) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'answered', 'expired', 'cancelled')),
    answer_key    varchar(8),
    answer_text   text CHECK (length(answer_text) <= 2000),
    answered_via  varchar(10) CHECK (answered_via IN ('telegram', 'terminal', 'expiry')),
    nonce         text NOT NULL,
    tg_message_id bigint,
    created_at    timestamptz NOT NULL DEFAULT now(),
    sent_at       timestamptz,
    answered_at   timestamptz,
    expires_at    timestamptz NOT NULL,
    apply_default_on_expiry boolean NOT NULL DEFAULT true,
    CHECK (jsonb_typeof(options) = 'array'
           AND jsonb_array_length(options) BETWEEN 2 AND 4)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vdecisions_pending_key
    ON verification.decisions (dedupe_key) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS ix_vdecisions_status ON verification.decisions (status, created_at);

CREATE TABLE IF NOT EXISTS verification.kv (
    key        text PRIMARY KEY,
    value      text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- ═════════════════════════════ functions ═════════════════════════════

-- Scope code of a report_lines (basis, statement) pair, same spelling as
-- scripts/layer2_review.py (_scope_codes): 'sep-bs' ... 'con-sce'.
CREATE OR REPLACE FUNCTION verification.scope_code(p_basis text, p_statement text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p_basis WHEN 'separate' THEN 'sep' WHEN 'consolidated' THEN 'con' ELSE p_basis END
           || '-' || lower(p_statement)
$$;

-- Content hashes of one rcept's verifiable report_lines (BS/IS/CF/SCE).
-- Provenance columns (id, source_ref, context_raw) are excluded on purpose: a change there
-- does not change what the reviewer compared against the source.
CREATE OR REPLACE FUNCTION verification.compute_hashes(
    p_rcept text, OUT content_hash text, OUT scope_hashes jsonb, OUT n_lines integer)
LANGUAGE plpgsql STABLE AS $$
BEGIN
    WITH r AS (
        SELECT verification.scope_code(basis, statement) AS scope,
               concat_ws('|', statement, basis, table_seq, row_order, depth, node_role,
                         section_path, label_raw, col_index, col_label, context_fiscal_year,
                         period_kind, is_cumulative, value_won, value_raw, adecimal,
                         unit_source, header_hint) AS line
        FROM public.report_lines
        WHERE rcept_no = p_rcept AND statement IN ('BS', 'IS', 'CF', 'SCE')
    ), s AS (
        SELECT scope, md5(string_agg(line, E'\n' ORDER BY line)) AS h, count(*) AS n
        FROM r GROUP BY scope
    )
    SELECT coalesce(jsonb_object_agg(scope, h), '{}'::jsonb),
           coalesce(sum(n), 0)::integer
      INTO scope_hashes, n_lines
      FROM s;
    content_hash := md5(scope_hashes::text);
END $$;

-- Record a baseline content version for an rcept that has none yet (claim / migration).
CREATE OR REPLACE FUNCTION verification.ensure_baseline(p_rcept text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
DECLARE
    v_seq integer;
    h record;
BEGIN
    SELECT load_seq INTO v_seq FROM verification.filing_loads WHERE rcept_no = p_rcept;
    IF FOUND THEN
        RETURN v_seq;
    END IF;
    SELECT * INTO h FROM verification.compute_hashes(p_rcept);
    INSERT INTO verification.filing_loads
        (rcept_no, load_seq, content_hash, scope_hashes, n_lines, parser_commit, loaded_by,
         reason, baseline)
    VALUES (p_rcept, 1, h.content_hash, h.scope_hashes, h.n_lines, 'pre-verification',
            verification.actor(), 'baseline', true)
    ON CONFLICT (rcept_no) DO NOTHING;
    SELECT load_seq INTO v_seq FROM verification.filing_loads WHERE rcept_no = p_rcept;
    RETURN v_seq;
END $$;

-- Recompute a slot's derived state: open-issue count, per-filing has_issues, slot status.
-- Leaves in_progress / blocked slots' status alone (their owner decides).
CREATE OR REPLACE FUNCTION verification.refresh_slot(p_corp text, p_fy integer, p_fp text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
DECLARE
    v_open integer;
    v_total integer;
    v_done integer;
BEGIN
    SELECT count(*) INTO v_open FROM verification.issues
     WHERE corp_code = p_corp AND fiscal_year = p_fy AND fiscal_period = p_fp
       AND status <> 'closed';

    UPDATE verification.progress_filings pf SET status = 'has_issues', updated_at = now()
     WHERE pf.corp_code = p_corp AND pf.fiscal_year = p_fy AND pf.fiscal_period = p_fp
       AND pf.status IN ('pending', 'passed')
       AND EXISTS (SELECT 1 FROM verification.issues i
                    WHERE i.rcept_no = pf.rcept_no AND i.status <> 'closed');
    -- All issues of a filing closed -> back to pending: the reviewer re-checks the scopes
    -- whose content changed since the verdict (vq.py show lists them) and passes it.
    UPDATE verification.progress_filings pf SET status = 'pending', updated_at = now()
     WHERE pf.corp_code = p_corp AND pf.fiscal_year = p_fy AND pf.fiscal_period = p_fp
       AND pf.status = 'has_issues'
       AND NOT EXISTS (SELECT 1 FROM verification.issues i
                        WHERE i.rcept_no = pf.rcept_no AND i.status <> 'closed');

    SELECT count(*), count(*) FILTER (WHERE status IN ('passed', 'skipped'))
      INTO v_total, v_done
      FROM verification.progress_filings
     WHERE corp_code = p_corp AND fiscal_year = p_fy AND fiscal_period = p_fp;

    UPDATE verification.progress p
       SET n_open_issues = v_open,
           status = CASE
               WHEN p.status IN ('in_progress', 'blocked') THEN p.status
               WHEN v_open > 0 THEN 'has_issues'
               WHEN v_total > 0 AND v_done = v_total THEN 'passed'
               ELSE 'pending' END,
           passed_at = CASE
               WHEN p.status IN ('in_progress', 'blocked') THEN p.passed_at
               WHEN v_open = 0 AND v_total > 0 AND v_done = v_total
                    THEN coalesce(p.passed_at, now())
               ELSE NULL END,
           updated_at = now()
     WHERE p.corp_code = p_corp AND p.fiscal_year = p_fy AND p.fiscal_period = p_fp;
END $$;

-- ═════════════════════════════ report_lines load hook ═════════════════════════════
-- Statement-level triggers only collect the touched rcepts; the real work happens once per
-- rcept at COMMIT (deferred constraint trigger), after the delete+insert pair is complete.

CREATE OR REPLACE FUNCTION verification.trg_rl_mark_new() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
BEGIN
    INSERT INTO verification.load_dirty (rcept_no, txid)
    SELECT DISTINCT rcept_no, txid_current() FROM new_rows
    ON CONFLICT DO NOTHING;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION verification.trg_rl_mark_old() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
BEGIN
    INSERT INTO verification.load_dirty (rcept_no, txid)
    SELECT DISTINCT rcept_no, txid_current() FROM old_rows
    ON CONFLICT DO NOTHING;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION verification.trg_finalize_load() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
DECLARE
    h         record;
    fl        record;
    v_seq     integer;
    v_changed text[];
    v_role    text := verification.actor_role();
    v_actor   text := verification.actor();
    v_commit  text := verification.guc('parser_commit');
    v_reason  text := coalesce(verification.guc('load_reason'), 'unspecified');
    slot      record;
    v_demoted integer;
BEGIN
    SELECT * INTO h FROM verification.compute_hashes(NEW.rcept_no);
    SELECT * INTO fl FROM verification.filing_loads WHERE rcept_no = NEW.rcept_no FOR UPDATE;

    IF FOUND AND fl.content_hash = h.content_hash THEN
        UPDATE verification.filing_loads SET last_checked_at = now()
         WHERE rcept_no = NEW.rcept_no;
        DELETE FROM verification.load_dirty WHERE rcept_no = NEW.rcept_no AND txid = NEW.txid;
        RETURN NULL;
    END IF;

    IF FOUND THEN
        SELECT array_agg(k ORDER BY k) INTO v_changed
          FROM (SELECT key AS k FROM jsonb_each_text(h.scope_hashes)
                UNION SELECT key FROM jsonb_each_text(fl.scope_hashes)) keys
         WHERE (h.scope_hashes ->> k) IS DISTINCT FROM (fl.scope_hashes ->> k);
        v_seq := fl.load_seq + 1;
        UPDATE verification.filing_loads
           SET load_seq = v_seq, content_hash = h.content_hash, scope_hashes = h.scope_hashes,
               n_lines = h.n_lines, parser_commit = v_commit, loaded_by = v_actor,
               reason = v_reason, baseline = false, loaded_at = now(), last_checked_at = now()
         WHERE rcept_no = NEW.rcept_no;
    ELSE
        SELECT array_agg(k ORDER BY k) INTO v_changed FROM jsonb_object_keys(h.scope_hashes) k;
        v_seq := 1;
        INSERT INTO verification.filing_loads
            (rcept_no, load_seq, content_hash, scope_hashes, n_lines, parser_commit, loaded_by,
             reason, baseline)
        VALUES (NEW.rcept_no, 1, h.content_hash, h.scope_hashes, h.n_lines, v_commit, v_actor,
                v_reason, false);
    END IF;

    INSERT INTO verification.filing_load_events
        (rcept_no, load_seq, content_hash, changed_scopes, n_lines, parser_commit, loaded_by,
         db_role, reason)
    VALUES (NEW.rcept_no, v_seq, h.content_hash, v_changed, h.n_lines, v_commit, v_actor,
            v_role, v_reason);

    -- Is this rcept part of a verification slot?
    SELECT p.corp_code, p.fiscal_year, p.fiscal_period, p.status, p.lease_until, p.claimed_by,
           pf.status AS filing_status
      INTO slot
      FROM verification.progress_filings pf
      JOIN verification.progress p USING (corp_code, fiscal_year, fiscal_period)
     WHERE pf.rcept_no = NEW.rcept_no;

    IF FOUND THEN
        -- Lease guard: the fix worktree must not change data a reviewer is looking at.
        -- (admin = daily pipeline: allowed, the optimistic load_seq check catches it.)
        IF slot.status = 'in_progress' AND slot.lease_until > now() AND v_role = 'fix' THEN
            RAISE EXCEPTION 'verification lease active on % (slot % % %, claimed by %, until %)',
                NEW.rcept_no, slot.corp_code, slot.fiscal_year, slot.fiscal_period,
                slot.claimed_by, slot.lease_until
                USING ERRCODE = '55P03';
        END IF;

        IF slot.filing_status = 'passed' THEN
            UPDATE verification.progress_filings SET status = 'pending', updated_at = now()
             WHERE rcept_no = NEW.rcept_no;
            INSERT INTO verification.progress_events
                (corp_code, fiscal_year, fiscal_period, rcept_no, action, from_status,
                 to_status, actor, db_role, evidence, load_seq)
            VALUES (slot.corp_code, slot.fiscal_year, slot.fiscal_period, NEW.rcept_no,
                    'reloaded_after_pass', 'passed', 'pending', v_actor, v_role,
                    'changed scopes: ' || coalesce(array_to_string(v_changed, ','), '-')
                    || ' / reason: ' || v_reason, v_seq);
        END IF;
        PERFORM verification.refresh_slot(slot.corp_code, slot.fiscal_year, slot.fiscal_period);
    ELSE
        -- A new filing (e.g. a fresh amendment) for a slot that already exists joins it.
        INSERT INTO verification.progress_filings
            (rcept_no, corp_code, fiscal_year, fiscal_period, seq_in_slot, is_amendment)
        SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period,
               (SELECT coalesce(max(seq_in_slot), 0) + 1 FROM verification.progress_filings x
                 WHERE x.corp_code = f.corp_code AND x.fiscal_year = f.fiscal_year
                   AND x.fiscal_period = f.fiscal_period),
               coalesce(f.is_amendment, false)
          FROM public.filings f
          JOIN verification.progress p
            ON p.corp_code = f.corp_code AND p.fiscal_year = f.fiscal_year
           AND p.fiscal_period = f.fiscal_period
         WHERE f.rcept_no = NEW.rcept_no
        ON CONFLICT (rcept_no) DO NOTHING;
        GET DIAGNOSTICS v_demoted = ROW_COUNT;
        IF v_demoted > 0 THEN
            SELECT corp_code, fiscal_year, fiscal_period INTO slot
              FROM verification.progress_filings WHERE rcept_no = NEW.rcept_no;
            INSERT INTO verification.progress_events
                (corp_code, fiscal_year, fiscal_period, rcept_no, action, to_status, actor,
                 db_role, evidence, load_seq)
            VALUES (slot.corp_code, slot.fiscal_year, slot.fiscal_period, NEW.rcept_no,
                    'filing_joined', 'pending', v_actor, v_role, v_reason, v_seq);
            PERFORM verification.refresh_slot(slot.corp_code, slot.fiscal_year,
                                              slot.fiscal_period);
        END IF;
    END IF;

    DELETE FROM verification.load_dirty WHERE rcept_no = NEW.rcept_no AND txid = NEW.txid;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS vrl_mark_ins ON public.report_lines;
CREATE TRIGGER vrl_mark_ins AFTER INSERT ON public.report_lines
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION verification.trg_rl_mark_new();

DROP TRIGGER IF EXISTS vrl_mark_upd ON public.report_lines;
CREATE TRIGGER vrl_mark_upd AFTER UPDATE ON public.report_lines
    REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION verification.trg_rl_mark_new();

DROP TRIGGER IF EXISTS vrl_mark_del ON public.report_lines;
CREATE TRIGGER vrl_mark_del AFTER DELETE ON public.report_lines
    REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION verification.trg_rl_mark_old();

DROP TRIGGER IF EXISTS vld_finalize ON verification.load_dirty;
CREATE CONSTRAINT TRIGGER vld_finalize AFTER INSERT ON verification.load_dirty
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION verification.trg_finalize_load();

-- ═════════════════════════════ issue state machine ═════════════════════════════
CREATE OR REPLACE FUNCTION verification.trg_issue_before() RETURNS trigger
LANGUAGE plpgsql SET search_path = verification, public AS $$
DECLARE
    v_role text := verification.actor_role();
    v_seq  integer;
    v_loaded_at timestamptz;
    ok     boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF v_role = 'fix' THEN
            RAISE EXCEPTION 'issues are registered by the verify worktree, not fix';
        END IF;
        IF NEW.status <> 'open' AND v_role <> 'admin' THEN
            RAISE EXCEPTION 'a new issue must start as open (got %)', NEW.status;
        END IF;
        IF NEW.found_load_seq IS NULL THEN
            SELECT load_seq INTO NEW.found_load_seq
              FROM verification.filing_loads WHERE rcept_no = NEW.rcept_no;
        END IF;
        IF NEW.found_parser_commit IS NULL THEN
            SELECT parser_commit INTO NEW.found_parser_commit
              FROM verification.filing_loads WHERE rcept_no = NEW.rcept_no;
        END IF;
        RETURN NEW;
    END IF;

    -- Column ownership.
    IF v_role = 'fix' AND (NEW.rcept_no, NEW.basis, NEW.statement, NEW.account_label,
                           NEW.column_label, NEW.db_value, NEW.source_value,
                           NEW.source_value_raw, NEW.source_unit, NEW.evidence)
            IS DISTINCT FROM
                          (OLD.rcept_no, OLD.basis, OLD.statement, OLD.account_label,
                           OLD.column_label, OLD.db_value, OLD.source_value,
                           OLD.source_value_raw, OLD.source_unit, OLD.evidence) THEN
        RAISE EXCEPTION 'fix worktree may not edit the observed facts of an issue';
    END IF;
    IF v_role = 'verify' AND (NEW.fixed_parser_commit, NEW.fixed_load_seq)
            IS DISTINCT FROM (OLD.fixed_parser_commit, OLD.fixed_load_seq) THEN
        RAISE EXCEPTION 'verify worktree may not edit the fix fields of an issue';
    END IF;

    -- An issue going back into the fix queue (open/reopened) while still pointing at an
    -- already-finished batch is invisible to both the "unassigned" (fix_batch_id IS NULL)
    -- and "active batch" fix-queue views. Auto-clear it here instead of leaving it for
    -- someone to notice and UPDATE by hand (docs/qa/handoff_2026-09-26_full_automation.md §5).
    IF NEW.status IN ('open', 'reopened') AND NEW.fix_batch_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM verification.fix_batches b
                        WHERE b.batch_id = NEW.fix_batch_id
                          AND b.status IN ('open', 'waiting_decision', 'reloading')) THEN
        NEW.fix_batch_id := NULL;
    END IF;

    -- Still block a *client-supplied* reassignment to some other non-null batch — only the
    -- auto-clear above (which only ever nulls it) may change this field under role verify.
    IF v_role = 'verify' AND NEW.fix_batch_id IS NOT NULL
       AND NEW.fix_batch_id IS DISTINCT FROM OLD.fix_batch_id THEN
        RAISE EXCEPTION 'verify worktree may not edit the fix fields of an issue';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status THEN
        ok := v_role = 'admin'
           OR (v_role = 'fix' AND (OLD.status, NEW.status) IN
                 (('open', 'fixing'), ('reopened', 'fixing'), ('fixing', 'fixed'),
                  ('fixing', 'open')))
           OR (v_role = 'verify' AND (OLD.status, NEW.status) IN
                 (('fixed', 'closed'), ('fixed', 'reopened'), ('closed', 'reopened'),
                  ('open', 'closed')));
        -- open -> closed (verify) = withdrawn as a false report; evidence is mandatory below.
        IF NOT ok THEN
            RAISE EXCEPTION 'illegal issue transition % -> % for role %',
                OLD.status, NEW.status, v_role;
        END IF;

        IF NEW.status = 'fixed' THEN
            IF NEW.fixed_parser_commit IS NULL THEN
                RAISE EXCEPTION 'fixed requires fixed_parser_commit';
            END IF;
            SELECT load_seq, loaded_at INTO v_seq, v_loaded_at
              FROM verification.filing_loads WHERE rcept_no = NEW.rcept_no;
            IF v_role <> 'admin' AND (v_seq IS NULL
                   OR (OLD.found_load_seq IS NOT NULL AND v_seq <= OLD.found_load_seq)
                   OR (OLD.found_load_seq IS NULL AND v_loaded_at <= OLD.created_at)) THEN
                RAISE EXCEPTION 'fixed requires a reload that changed the data of % (load_seq %, found at %)',
                    NEW.rcept_no, v_seq, OLD.found_load_seq;
            END IF;
            NEW.fixed_load_seq := v_seq;
        END IF;

        IF v_role <> 'admin' AND NEW.status IN ('reopened', 'closed') AND OLD.status = 'open'
           OR (v_role <> 'admin' AND NEW.status = 'reopened') THEN
            IF verification.guc('evidence') IS NULL THEN
                RAISE EXCEPTION '% -> % requires evidence (SET LOCAL verification.evidence)',
                    OLD.status, NEW.status;
            END IF;
        END IF;
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION verification.trg_issue_after() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO verification.issue_events
            (issue_id, action, to_status, actor, db_role, evidence, load_seq)
        VALUES (NEW.issue_id, 'create', NEW.status, verification.actor(),
                verification.actor_role(), verification.guc('evidence'), NEW.found_load_seq);
    ELSIF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO verification.issue_events
            (issue_id, action, from_status, to_status, actor, db_role, evidence, commit_sha,
             load_seq)
        VALUES (NEW.issue_id, 'transition', OLD.status, NEW.status, verification.actor(),
                verification.actor_role(), verification.guc('evidence'),
                NEW.fixed_parser_commit,
                (SELECT load_seq FROM verification.filing_loads WHERE rcept_no = NEW.rcept_no));
    ELSIF NEW.fix_batch_id IS DISTINCT FROM OLD.fix_batch_id
       OR NEW.error_type IS DISTINCT FROM OLD.error_type
       OR NEW.rule_id IS DISTINCT FROM OLD.rule_id THEN
        INSERT INTO verification.issue_events
            (issue_id, action, actor, db_role, evidence)
        VALUES (NEW.issue_id, 'relink', verification.actor(), verification.actor_role(),
                concat_ws(' ', 'batch=' || NEW.fix_batch_id, 'type=' || NEW.error_type,
                          'rule=' || NEW.rule_id, verification.guc('evidence')));
    END IF;
    PERFORM verification.refresh_slot(NEW.corp_code, NEW.fiscal_year, NEW.fiscal_period);
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS vissue_before ON verification.issues;
CREATE TRIGGER vissue_before BEFORE INSERT OR UPDATE ON verification.issues
    FOR EACH ROW EXECUTE FUNCTION verification.trg_issue_before();
DROP TRIGGER IF EXISTS vissue_after ON verification.issues;
CREATE TRIGGER vissue_after AFTER INSERT OR UPDATE ON verification.issues
    FOR EACH ROW EXECUTE FUNCTION verification.trg_issue_after();

-- ═════════════════════════════ progress history ═════════════════════════════
-- Two functions because NEW.rcept_no only exists on progress_filings (PL/pgSQL resolves
-- record fields when the statement is planned, even inside an unreached CASE branch).
CREATE OR REPLACE FUNCTION verification.trg_progress_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO verification.progress_events
            (corp_code, fiscal_year, fiscal_period, action, from_status, to_status,
             actor, db_role, evidence)
        VALUES (NEW.corp_code, NEW.fiscal_year, NEW.fiscal_period, 'slot_status',
                OLD.status, NEW.status, verification.actor(), verification.actor_role(),
                verification.guc('evidence'));
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION verification.trg_progress_filing_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = verification, public AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        INSERT INTO verification.progress_events
            (corp_code, fiscal_year, fiscal_period, rcept_no, action, from_status, to_status,
             actor, db_role, evidence, load_seq)
        VALUES (NEW.corp_code, NEW.fiscal_year, NEW.fiscal_period, NEW.rcept_no,
                'filing_status', OLD.status, NEW.status, verification.actor(),
                verification.actor_role(), verification.guc('evidence'),
                (SELECT load_seq FROM verification.filing_loads WHERE rcept_no = NEW.rcept_no));
    END IF;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS vprogress_event ON verification.progress;
CREATE TRIGGER vprogress_event AFTER UPDATE ON verification.progress
    FOR EACH ROW EXECUTE FUNCTION verification.trg_progress_event();
DROP TRIGGER IF EXISTS vpf_event ON verification.progress_filings;
CREATE TRIGGER vpf_event AFTER UPDATE ON verification.progress_filings
    FOR EACH ROW EXECUTE FUNCTION verification.trg_progress_filing_event();

-- ═════════════════════════════ grants ═════════════════════════════
GRANT USAGE ON SCHEMA public, verification TO tjf_verify, tjf_fix;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO tjf_verify;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tjf_fix;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO tjf_fix;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO tjf_verify;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tjf_fix;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO tjf_fix;
DO $$ BEGIN
    EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO tjf_verify, tjf_fix', current_database());
END $$;

GRANT SELECT ON ALL TABLES IN SCHEMA verification TO tjf_verify, tjf_fix;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA verification TO tjf_verify, tjf_fix;

-- verify: slot/filing verdicts, issue registration + verifier transitions, runner bookkeeping.
GRANT UPDATE ON verification.progress, verification.progress_filings TO tjf_verify;
GRANT INSERT, UPDATE ON verification.issues TO tjf_verify;
GRANT INSERT, UPDATE ON verification.runner_runs TO tjf_verify;
GRANT INSERT, UPDATE ON verification.kv TO tjf_verify;
GRANT INSERT, UPDATE ON verification.machine_checks TO tjf_verify;

-- fix: fixer transitions, batches, decisions.
GRANT UPDATE ON verification.issues TO tjf_fix;
GRANT INSERT, UPDATE ON verification.fix_batches, verification.batch_targets TO tjf_fix;
GRANT INSERT, UPDATE ON verification.decisions TO tjf_fix;
GRANT INSERT, UPDATE ON verification.kv TO tjf_fix;
GRANT INSERT, UPDATE ON verification.runner_runs TO tjf_fix;

-- Load stamping is written only through the SECURITY DEFINER triggers/functions above.
REVOKE INSERT, UPDATE, DELETE ON verification.filing_loads, verification.filing_load_events,
    verification.issue_events, verification.progress_events FROM tjf_verify, tjf_fix;
-- load_dirty is written by the SECURITY DEFINER statement triggers; nobody writes it directly.
REVOKE ALL ON verification.load_dirty FROM tjf_verify, tjf_fix;
