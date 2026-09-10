"""Apply pending schema migrations (collector/db.py MIGRATIONS) — one-shot runner.

Used here to apply "2026_09_std_financials_v3_unit_overrides" without going through
a full app entrypoint. Idempotent (schema_migrations tracks applied ids).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collector.db import init_db

if __name__ == "__main__":
    init_db()
