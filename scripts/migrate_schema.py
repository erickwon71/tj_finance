"""
Schema migration — additive, idempotent (no alembic).

Adds the nullable columns / tables introduced by the 재무 DB화 고도화 계획.
Safe to run repeatedly: every statement uses IF NOT EXISTS.

Run after pulling new code, before using the new commands:
    python3 scripts/migrate_schema.py
    python3 scripts/migrate_schema.py --dry-run   # show statements only
"""
import argparse

import psycopg2

DB_DSN = "dbname=tj_finance user=taejin"

# ── Additive DDL — each must be idempotent ────────────────────────────────────
STATEMENTS: list[str] = [
    # A1: 결산월
    "ALTER TABLE corporations ADD COLUMN IF NOT EXISTS fiscal_month SMALLINT DEFAULT 12",

    # B1: 사업보고서 원본 전체 PDF 아카이브 (DownloadTask와 1:1)
    "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS orig_pdf_path VARCHAR(1000)",
    "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS orig_pdf_status VARCHAR(15)",
    "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS orig_pdf_size BIGINT",

    # C3: 출처추적 (provenance)
    "ALTER TABLE financial_facts ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120)",

    # C3: 검증 결과 테이블
    """
    CREATE TABLE IF NOT EXISTS verification_results (
        id              BIGSERIAL    PRIMARY KEY,
        corp_code       VARCHAR(8)   NOT NULL,
        fiscal_year     SMALLINT     NOT NULL,
        fiscal_period   VARCHAR(5)   NOT NULL,
        statement_type  VARCHAR(12)  NOT NULL,
        rcept_no        VARCHAR(14),
        check_name      VARCHAR(40)  NOT NULL,
        layer           SMALLINT,
        passed          BOOLEAN,
        lhs_label       VARCHAR(60),
        rhs_label       VARCHAR(60),
        lhs_value       BIGINT,
        rhs_value       BIGINT,
        diff_pct        DOUBLE PRECISION,
        tolerance_pct   DOUBLE PRECISION,
        source_ref      VARCHAR(120),
        checked_at      TIMESTAMP    DEFAULT NOW(),
        CONSTRAINT uq_verification UNIQUE
            (corp_code, fiscal_year, fiscal_period, statement_type, check_name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_verif_corp_year "
    "ON verification_results (corp_code, fiscal_year, fiscal_period)",
    "CREATE INDEX IF NOT EXISTS ix_verif_failed "
    "ON verification_results (passed) WHERE passed = FALSE",
]


def main():
    ap = argparse.ArgumentParser(description="Additive schema migration")
    ap.add_argument("--dry-run", action="store_true", help="Print statements, no execution")
    args = ap.parse_args()

    if args.dry_run:
        for i, stmt in enumerate(STATEMENTS, 1):
            print(f"-- [{i}] " + stmt.strip().splitlines()[0])
            print(stmt.strip() + ";\n")
        print("Dry-run: no changes made.")
        return

    conn = psycopg2.connect(DB_DSN)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        for i, stmt in enumerate(STATEMENTS, 1):
            first_line = stmt.strip().splitlines()[0].strip()
            cur.execute(stmt)
            print(f"[{i}/{len(STATEMENTS)}] OK: {first_line[:70]}")
        conn.commit()
        print("\nMigration complete.")
    except Exception as exc:
        conn.rollback()
        print(f"\nFAILED, rolled back: {exc}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
