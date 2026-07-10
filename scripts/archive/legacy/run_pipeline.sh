#!/bin/zsh
# LEGACY path — superseded by the fin2 engine (`run.py fin2-all` / `scripts/collect_new.py`).
# Drives the old parse → recalc-superseded → aggregate flow (tables financial_facts /
# standard_financials). Kept for reference only; NOT run in v1.0. Invoke from repo root.
#
# Full parse → superseded → aggregate pipeline
# Usage: zsh scripts/archive/legacy/run_pipeline.sh

echo "=== [1/4] parse --workers 4 ==="
python3 run.py parse --workers 4

echo "=== [2/4] parse-pdf ==="
python3 run.py parse-pdf --workers 2

echo "=== [3/4] recalc-superseded ==="
python3 run.py recalc-superseded

echo "=== [4/4] aggregate --since 1999 ==="
python3 run.py aggregate --since 1999 --workers 4

echo "=== pipeline complete ==="
