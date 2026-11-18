-- R342/R343 (2026-11-18): snapshot std_v3 + extended_facts_v3 of the affected corps BEFORE the rebuild.
-- Corp list: scripts/qa/r342_r343_corps_2026-11-18.txt (1,732 corps: a BS label whose mapping R342/R342-b/R344
-- changes, or a std row with net_debt NULL and cash present). Run from the repo root.
DROP TABLE IF EXISTS snap_r342_corps, snap_r342_std, snap_r342_ext;
CREATE TABLE snap_r342_corps (corp_code varchar(8) PRIMARY KEY);
\copy snap_r342_corps FROM 'scripts/qa/r342_r343_corps_2026-11-18.txt'
CREATE TABLE snap_r342_std AS SELECT f.* FROM std_financials_v3 f JOIN snap_r342_corps USING (corp_code);
CREATE TABLE snap_r342_ext AS SELECT e.* FROM extended_facts_v3 e JOIN snap_r342_corps USING (corp_code);
SELECT (SELECT count(*) FROM snap_r342_corps) corps, (SELECT count(*) FROM snap_r342_std) std_rows,
       (SELECT count(*) FROM snap_r342_ext) ext_rows;
