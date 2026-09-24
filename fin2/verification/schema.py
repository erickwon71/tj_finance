"""Apply fin2/verification/schema.sql (idempotent)."""
from __future__ import annotations

from pathlib import Path

SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def apply_schema(engine) -> None:
    """Run the whole file through the raw DB-API cursor.

    Deliberately not `text()`: SQLAlchemy would parse `:name` as bind parameters and the
    driver would treat PL/pgSQL `RAISE ... %` placeholders as format markers.
    """
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(sql)
        cur.close()
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
