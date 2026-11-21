-- R369 (2026-11-21): snapshot std_v3 + extended_facts_v3 BEFORE the company-wide rebuild.
DROP TABLE IF EXISTS snap_r369_std, snap_r369_ext;
CREATE TABLE snap_r369_std AS SELECT * FROM std_financials_v3;
CREATE TABLE snap_r369_ext AS SELECT * FROM extended_facts_v3;
SELECT (SELECT count(*) FROM snap_r369_std) std_rows, (SELECT count(*) FROM snap_r369_ext) ext_rows;
