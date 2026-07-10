"""LEGACY parsing engine (Phase 1–3).

Superseded by the current `fin2` engine (extract → reconcile → standardize,
tables ``fact_v2`` / ``std_financials_v2``). This package backs the legacy
``run.py parse | parse-pdf | aggregate`` path and tables ``financial_facts`` /
``standard_financials``, which are retained but not part of the v1.0 main
pipeline. New work should target ``fin2/``.
"""
