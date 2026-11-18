-- R342~R345 (2026-11-18): snapshot std_v3 + extended_facts_v3 of the affected corps BEFORE the rebuild.
-- Scope: every corp in std_financials_v3 (R345 touches ~10k filings, so the rebuild is company-wide).
-- Run from the repo root.
DROP TABLE IF EXISTS snap_r342_corps, snap_r342_std, snap_r342_ext;
CREATE TABLE snap_r342_corps (corp_code varchar(8) PRIMARY KEY);
INSERT INTO snap_r342_corps SELECT DISTINCT corp_code FROM std_financials_v3;
CREATE TABLE snap_r342_std AS SELECT f.* FROM std_financials_v3 f JOIN snap_r342_corps USING (corp_code);
CREATE TABLE snap_r342_ext AS SELECT e.* FROM extended_facts_v3 e JOIN snap_r342_corps USING (corp_code);
SELECT (SELECT count(*) FROM snap_r342_corps) corps, (SELECT count(*) FROM snap_r342_std) std_rows,
       (SELECT count(*) FROM snap_r342_ext) ext_rows;
