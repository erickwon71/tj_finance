# TJ Finance — convenience wrappers over existing entry points (no new logic).
# Uses the project venv directly so `make` works without activating it first.

PY := .venv_tj_finance/bin/python
STREAMLIT := .venv_tj_finance/bin/streamlit

.PHONY: help app collect backup dq

help:
	@echo "make app      - run the Streamlit visualization app"
	@echo "make collect  - run the daily collection pipeline (last 3 days)"
	@echo "make backup   - run the DB backup (pg_dump)"
	@echo "make dq       - run the nightly data-quality assertions"

app:
	$(STREAMLIT) run app/main.py

collect:
	$(PY) scripts/collect_new.py --days 3 --timeout 600 --refresh-universe

backup:
	$(PY) scripts/backup_db.py

dq:
	$(PY) scripts/dq_nightly.py
