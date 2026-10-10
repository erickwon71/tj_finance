#!/bin/zsh
# Web-viewer source follow-up chain (user decision 2026-10-10 afternoon: run in order through the
# layer-3 rebuild). Each step logs to logs/r0_2/viewer_chain.log; a step that fails stops the chain.
#   1. collect the remaining targets ([첨부정정] + retries)   2. register + one document.xml recheck
#   3. NAS -> SD mirror   4. target lists   5. layer-3 snapshot   6. layer-2 reload (viewer XML)
#   7. layer-3 rebuild (4 shards)   8. compare
# Usage (cwd = repo root): zsh scripts/r0_2_migration/run_viewer_chain.sh
set -e
set -o pipefail
cd "${0:A:h}/../.."
set -a; source .env; set +a
PY=.venv/bin/python
D=logs/r0_2
M=$D/viewer_xml_manifest.jsonl
LOG=$D/viewer_chain.log
step() { print -- "=== $(date '+%F %T') $*" | tee -a $LOG; }

while pgrep -f collect_viewer_xml.py >/dev/null; do sleep 60; done

step "1 collect remaining"
$PY scripts/r0_2_migration/collect_viewer_xml.py $M >> $D/viewer_xml_collect.log 2>&1
command grep -o '"status": "[a-z_]*' $M | sort | uniq -c | tee -a $LOG

step "2 register + package recheck"
$PY scripts/r0_2_migration/register_viewer_xml.py $M --recheck-package --apply 2>&1 | tee -a $LOG

step "3 NAS -> SD mirror"
$PY scripts/sync_storage_mirror.py --since-hours 24 2>&1 | tail -15 | tee -a $LOG

step "4 target lists"
TARGETS="FROM download_tasks dt JOIN filings f USING (rcept_no)
  WHERE dt.viewer_xml_path IS NOT NULL AND NOT (dt.status = 'completed' AND dt.file_type = 'xml')
    AND dt.layer2_reload_pending"
psql "$DATABASE_URL" -Atc "SELECT DISTINCT dt.rcept_no $TARGETS ORDER BY 1" > $D/viewer_rcepts.txt
psql "$DATABASE_URL" -AtF $'\t' -c "SELECT DISTINCT f.corp_code, f.fiscal_year, f.fiscal_period $TARGETS" \
  > $D/viewer_periods.tsv
cut -f1 $D/viewer_periods.tsv | sort -u > $D/viewer_corps.txt
print -- "rcepts $(wc -l < $D/viewer_rcepts.txt) periods $(wc -l < $D/viewer_periods.tsv) corps $(wc -l < $D/viewer_corps.txt)" | tee -a $LOG

step "5 layer-3 snapshot"
$PY scripts/r0_2_migration/compare_layer3.py snapshot viewer $D/viewer_corps.txt $D/viewer_periods.tsv 2>&1 | tee -a $LOG

step "6 layer-2 reload"
$PY scripts/r0_2_migration/reload_drift.py $D/viewer_rcepts.txt $D/viewer_reload.jsonl 4 r0_2_viewer_reload 2>&1 | tee -a $LOG
command grep -o '"status": "[a-z]*' $D/viewer_reload.jsonl | sort | uniq -c | tee -a $LOG

step "7 layer-3 rebuild"
rm -f $D/viewer_corps_part_*(N)
awk -v d=$D '{ print > (d "/viewer_corps_part_" (NR % 4)) }' $D/viewer_corps.txt
for p in $D/viewer_corps_part_?; do
  $PY scripts/build_std_v3.py --corp "$(paste -sd, $p)" --year-min 2015 > $p.log 2>&1 &
done
wait
tail -qn1 $D/viewer_corps_part_?.log | tee -a $LOG

step "8 compare"
$PY scripts/r0_2_migration/compare_layer3.py compare viewer $D/viewer_corps.txt $D/viewer_periods.tsv 2>&1 | tee -a $LOG
step "done"
