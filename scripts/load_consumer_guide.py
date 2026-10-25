"""Load docs/consumer_guide/*.md into the consumer_guide table and apply comments.sql.

Idempotent: creates the table if missing, upserts every section, deletes sections whose
source file was removed, then applies the table/column comments and grants.sql (the reader's allowlist). Source of truth = the
markdown files; rerun after editing them. See docs/consumer_guide/README.md.

    .venv/bin/python scripts/load_consumer_guide.py [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collector.config import DATABASE_URL  # noqa: E402

GUIDE_DIR = ROOT / "docs" / "consumer_guide"
MIGRATION_ID = "2026_10_consumer_guide_table"
READER_ROLE = "tja_reader"

DDL = """
CREATE TABLE IF NOT EXISTS consumer_guide (
    section       text PRIMARY KEY,
    ord           integer NOT NULL,
    title         text NOT NULL,
    body          text NOT NULL,
    guide_version text NOT NULL,
    updated_at    timestamp NOT NULL DEFAULT now()
)
"""


def parse_section(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, head, body = text.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in head.strip().splitlines())
    return {
        "section": meta["section"].strip(),
        "ord": int(meta["ord"]),
        "title": meta["title"].strip(),
        "body": body.strip() + "\n",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sections = [parse_section(p) for p in sorted(GUIDE_DIR.glob("s*.md"))]
    digest = hashlib.sha256("".join(s["body"] for s in sections).encode()).hexdigest()[:12]
    version = f"{digest}"
    print(f"{len(sections)} sections, guide_version={version}")
    if args.dry_run:
        for s in sections:
            print(f"  {s['ord']:>3} {s['section']:<22} {len(s['body'])} chars")
        return

    comments_sql = (GUIDE_DIR / "comments.sql").read_text(encoding="utf-8")
    grants_sql = (GUIDE_DIR / "grants.sql").read_text(encoding="utf-8")
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
            for s in sections:
                cur.execute(
                    """
                    INSERT INTO consumer_guide (section, ord, title, body, guide_version, updated_at)
                    VALUES (%s, %s, %s, %s, %s, now())
                    ON CONFLICT (section) DO UPDATE SET
                        ord = EXCLUDED.ord, title = EXCLUDED.title, body = EXCLUDED.body,
                        guide_version = EXCLUDED.guide_version, updated_at = now()
                    """,
                    (s["section"], s["ord"], s["title"], s["body"], version),
                )
            cur.execute(
                "DELETE FROM consumer_guide WHERE section <> ALL(%s)",
                ([s["section"] for s in sections],),
            )
            cur.execute("UPDATE consumer_guide SET guide_version = %s", (version,))
            cur.execute(f"GRANT SELECT ON consumer_guide TO {READER_ROLE}")
            cur.execute(comments_sql)
            cur.execute(grants_sql)
            cur.execute(
                "INSERT INTO schema_migrations (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (MIGRATION_ID,),
            )
    finally:
        conn.close()
    print("applied")


if __name__ == "__main__":
    main()
