# TJ Finance — Mid-Project Evaluation & Improvement Roadmap (2026-07-04)

## Context

The project's goal is a personal "Bloomberg-terminal-grade" tool: collect every DART periodic report, DB-ize all evaluation-relevant data (financials, share counts, dilution contracts, utilization, order backlog, inventory, executives), and visualize it freely. The user asked for: (1) analysis of the expert-review results (docs/prd/08 + follow-up docs), (2) evaluation of progress to date including launchd automation, (3) gaps, and (4) an improvement plan with schedule and checklist.

User decisions (2026-07-04): **buy a NAS** for backup/raw_report redundancy; **expand verification to Track B line audit** (PDF-only and pre-2010 K-GAAP stay deferred); **remove** the failing `com.dart.financial.worker` launchd item (old project).

---

## Part 1 — Evaluation of current state

### What is solid (verified from docs + git log + live system)

| Area | Status | Evidence |
|---|---|---|
| Report→DB pipeline (fin2) | **Excellent** | 2,557/2,557 corps PASS; Gate B face audit 271,193 pass / 0 fail; Track A line audit 3,334,396 lines, value_diff 0 |
| Expert review execution | **P0 100%, P1 ~80% done** | I1 `verify_cross_source.py`, I2 collect-time DQ gate, I3 `dq_assertions.py`, D1 `backup_db.py`, D2 index cleanup (89→84GB), D4 pg tuning, I4 verifier revived — all in git log |
| DQ findings triage | **Done, documented** | op==ni bug fixed (660 corps/3,204 rows); future period_end + 자산총계≤0 quarantined; docs/dq_findings_2026-07-03.md |
| Visualization | **Strong** | 7 pages; B-1 valuation bands, B-2 per-share, B-3 executives, B-4 trust badge, peer benchmarking; screener Phase 5 (Buffett/Graham/Greenblatt/Lynch/Fisher/Piotroski) |
| Automation (launchd) | **Good, 1 unverified** | collect 18:00 / backup 19:00 / dqcheck 20:30 all loaded, exit 0; pmset wake 17:58 |

The expert-review process itself was well-designed (4 personas, prioritized P0/P1/P2, decisions recorded) and — importantly — was actually executed, not just written. The review's own quality is adequate; its one blind spot: it audited the DB/app but not the **physical storage layout** (backups and raw originals sharing one external disk) or **restore testing**.

### Gaps found (ordered by risk)

**G1. Ops/safety (urgent, small effort)**
- Backup automation unverified: only 1 dump exists (`tj_finance_core_20260702_2237.dump`, manual-looking), **no `logs/backup.*.log` at all** despite a daily 19:00 schedule installed 7/3. Restore has never been tested.
- **Single point of failure**: raw_report originals (218GB, 356,105 files) AND db_backups both live on `/Volumes/dart_data`. One disk failure loses originals + backups together.
- `com.dart.financial.worker` (old project) fails daily with exit 127.
- P1 leftovers from the review: D3 `valuation_daily` materialized view, D5 VACUUM/ANALYZE routine, migration governance (`schema_migrations` vs rerunning 30 DDLs each boot).

**G2. Data coverage — vs the user's #1 goal ("all evaluation-relevant data DB-ized")**
| Category | Status |
|---|---|
| CB/BW/warrants, 증자·감자, 자사주 events (share-count-affecting contracts) | **Missing entirely** — no dilution-event data; DART APIs exist (`cvbdIsDecsn`, `bdwtIsDecsn`, `exbdIsDecsn`, `piicDecsn`, `tsstkAqDecsn`, `irdsSttus`) |
| 수주잔고 (order backlog) | **Table + fetcher exist (`order_backlog`, `collector/dart_extra.py`) but never wired** — 0 rows, no panel |
| 가동률/생산실적 (utilization/production) | **Missing** — no DART API; requires parsing 사업보고서 "사업의 내용 > 생산 및 설비" tables from the 218GB raw_report already on disk |
| 대주주/지분 (major shareholders) | **Missing** — APIs exist (`hyslrSttus`, `hyslrChgSttus`, `mrhlSttus`) |
| D&A/EBITDA cluster (ebitda, da_total, fcf, capex parity) | **Known open gap** — note-D&A augmentation rule not yet added to `fin2/standardize/rules.py`/`build.py` |
| Inventory detail (원재료/재공품/제품 breakdown), treasury transactions | Shallow (totals only) |

**G3. Verification scope**
- Track B/C: 107,847 reports have no report↔DB line audit (user chose to close Track B).
- Consolidated<separate assets: 22 true-magnitude-error rows awaiting per-case triage.

**G4. Visualization freedom**
- No free-form field combiner — the user explicitly wants "db에 있는 상세 항목을 조합할 수 있는 자유도"; today charts are limited to the ~50-metric registry and fixed panels.
- Open P2 items: V3 EV/EBITDA multiple time series (verify), V7 watchlist/saved screens, V8 line→source-filing drill-down.
- Panels for 수주/dilution/대주주/가동률 blocked on G2 data.

---

## Part 1.5 — Weaknesses in the existing verification methodology itself

The Gate A/B + line-audit design proves **extraction fidelity** (DB == the file we parsed) extremely well, but it has structural blind spots:

- **W1. Correlated-error blindness**: Gate B's "report side" and the pipeline both parse the same file, partly with shared assumptions — a systematic misreading passes both. I1 (DART API cross-source) is the right antidote but currently runs as a **25-corp/day rotating sample → ~100 days per full rotation**, and only on accounts `fnlttSinglAcnt` exposes. A one-time **full-universe cross-source sweep** (all 2,557 corps × recent 3–5 years, major accounts) has never been run.
- **W2. Standardization layer is the weakest-verified layer**: the op==ni bug (660 corps) lived in canonical-column *selection*, not extraction — Gate B could not see it; it was caught later by I1/I3. Defenses today are DQ equations + a **golden set of only 5 corps**. Equations can't catch a wrong-but-arithmetically-consistent mapping. → expand golden set to ~30–50 corps (diverse industries/sizes/periods, hand-verified against DART viewer).
- **W3. No cross-domain consistency check**: computed PER/EPS (financials × shares_out × price) is never compared to **KRX-provided per/eps/bps already sitting in `stock_prices`**. This single assertion ties financials + share count + prices together with an independent source — cheap and powerful; not in any plan.
- **W4. Derived/analytics layer has no regression tests**: quarterly conversion, ratio/valuation engines, screener math were verified by one-time scripts and eyeball oracles (삼성전자 333.6조). A future code change silently breaking a formula would go unnoticed. → pytest suite with frozen golden expected values.
- **W5. Completeness is verified once, not continuously**: the user's requirement "중간에 비는 분기가 없을 것" was proven in the 6/25 full run, but nothing recurring asserts every active corp has every expected period going forward (new listings, late filings, amendments drift). → recurring completeness matrix in dq_nightly + coverage % in the trust badge.
- **W6. Amendment/restatement blindness**: DB stores as-filed; when a 기재정정 supersedes numbers, the user can be shown stale values with no indication. → flag (corp, period) where a later amendment filing exists; surface in trust badge; prioritize I1 cross-check there.
- **W7. Silent failure of the monitoring itself**: dqcheck/backup failures only write to log files nobody reads daily — exactly how the unverified backup situation arose. → push a macOS notification (or mail) on nonzero exit / assertion failure.
- **W8. App layer unverified**: "시각화에 오류가 없는지" is covered only by manual spot checks and the anomaly guard; unit conversions (억원), sign conventions, per-share transforms in `app/compute/` have no fixture-based tests.

These become Phase C items C5–C10 below.

---

## Part 2 — Improvement plan

Execution notes (per established workflow): long-running backfills/audits are run by the user in a terminal (Claude writes the script and the exact command); multi-line code always as `scripts/*.py`. First implementation step: save this roadmap as `docs/prd/09_improvement_roadmap.md` so it lives in-repo.

### Model strategy (quota optimization, decided 2026-07-04)
Claude cannot switch its own session model mid-session — only the user can via `/model`. Two levers:
1. **Per-session model choice (main lever)**: at the start of each work session, pick the model to match that session's tasks. Recommended mapping (recorded in the roadmap doc so each session's handoff names the right model):
   - **Sonnet 5** — routine coding/ops: A1 backup verify, A2 plist removal, A4 matview/VACUUM/migrations, C10 notifications, C6 KRX assertion, B1 backlog wiring, D2 watchlist/drill-down, checklist doc updates.
   - **Fable 5 (or Opus)** — design-heavy/ambiguous: B2 capital_events schema+collectors design, B4 biz-section extractor (heterogeneous table parsing), B5 D&A standardization rule, C1 Track B audit harness extension, diff triage judgment calls, D1 chart-builder architecture.
   - **Haiku 4.5** — only for trivial mechanical batches via subagent delegation (see 2).
2. **Subagent model override (secondary)**: within a session, well-scoped mechanical chunks can be delegated to a cheaper-model subagent (`Agent` tool with `model: "sonnet"`/`"haiku"`). Use sparingly — each subagent starts cold and re-reads context, so it only pays off for self-contained batch work (e.g., writing many similar collector functions from a fixed spec), not small edits.

### Phase A — Ops hardening (Week 1: 7/5–7/11)
- **A1 Backup verification**: confirm tonight's 19:00 run writes `logs/backup.out.log` + a new dump; fix if not (plist path/label check). Then a **restore drill**: `pg_restore` the core dump into a scratch DB `tj_finance_restore_test`, row-count spot-check vs live, document in `docs/runbook_backup_restore.md`.
- **A2 Remove old worker**: `launchctl bootout gui/$UID/com.dart.financial.worker` + delete plist (user confirmation before delete).
- **A3 NAS integration** (hardware: 2-bay NAS, RAID1, 2×8TB+ — e.g., Synology DS224+ class):
  - raw_report mirror: weekly `rsync -a --delete` launchd job → NAS share.
  - db_backups second copy: daily rsync after the 19:00 backup (e.g., 19:40).
  - New plists in `deploy/launchd/` (pattern of existing ones); guard on mount availability like `backup_db.py` does.
- **A4 DB P1 leftovers**: D3 `valuation_daily` matview + refresh hook at end of `collect_new.py`; D5 weekly VACUUM/ANALYZE launchd job; add `schema_migrations` table to `collector/db.py::_run_migrations`.

### Phase B — Data expansion (Weeks 2–5) ★ top priority per user
Common pattern per dataset: collection script (backfill 2015+ first, then extend) → incremental hook in `scripts/collect_new.py` → DQ assertion in `scripts/dq_assertions.py` → panel in `app/views/company_page.py`.

- **B1 수주잔고 — merged into B4 (corrected 2026-07-04)**: originally scoped as "easiest — plumbing
  exists," but investigation found no DART structured API for order backlog at all (unlike
  executives' `exctvSttus`) and no fetcher function in `collector/dart_extra.py` despite the
  `OrderBacklog` model being imported there. The model's own docstring always specified body-table
  parsing as the source. B1 is not independently doable — pick it up as part of B4's body-table
  extractor (수주상황 is one of the same heterogeneous tables B4 already targets).
- **B2 Dilution/capital events** (highest investment value): new table `capital_events` (corp, event_type, rcept_no, date, amounts, conversion price, share delta). Sources: `piicDecsn`(유상증자), `cvbdIsDecsn`(CB), `bdwtIsDecsn`(BW), `exbdIsDecsn`(EB), `tsstkAqDecsn`/처분(자사주), `irdsSttus`(증자감자 현황), 미상환 CB/BW balance APIs. Viz: event markers overlaid on the B-2 share-count chart + "potential dilution %" metric.
- **B3 대주주/지분**: new table `major_shareholders`; `hyslrSttus` + `hyslrChgSttus` + `mrhlSttus`; ownership-structure panel (largest shareholder %, float %). Confirmed real DART structured APIs (unlike B1) — genuinely quick relative to B4.
- **B4 가동률/생산/수주 body-table extractor** (hardest — now includes B1's 수주상황): new `fin2/extract/biz_section.py` parsing 생산능력/생산실적/가동률/수주상황 tables from stored raw reports. Heterogeneous per industry — start with manufacturing corps + user's watchlist, iterate; store in long-format table `biz_metrics` (corp, period, metric, segment, value, unit) rather than wide columns.
- **B5 D&A note augmentation**: add note-D&A binding rule in `fin2/standardize/rules.py`/`build.py` (closes the ebitda/da_total/fcf/capex parity divergence flagged since the fin2 rebuild).

### Phase C — Verification expansion (Weeks 5–7, overlaps B; C5/C6/C10 pulled into Weeks 1–2 — cheap, high value)
- **C1 Track B line audit**: extend the `face_line_audit` harness (from `verify_corp_sequential.py` Phase B) to text-track reports; run in batches (user-run, resumable) over the 107,847 pending; triage diffs like the 94-false-positive playbook.
- **C2** con<sep 22-row per-case cross-validation with DART API.
- **C3** DQ assertions for new datasets (e.g., shares_out change should have a matching capital_event; backlog continuity).
- **C4** Recurring quarterly restore drill (calendar reminder in runbook).
- **C5 Full cross-source sweep (fixes W1)**: one-time `verify_cross_source.py` run over all 2,557 corps × recent 3–5 FY (user-run, resumable, rate-limited); triage per the dq_findings playbook (extraction bug / restatement / synthetic). Afterwards keep the daily 25-corp rotation, weighted toward latest periods.
- **C6 KRX consistency assertion (fixes W3)**: nightly assertion comparing computed EPS/BPS/PER vs KRX-provided values in `stock_prices` within tolerance; violations → `verification_results`.
- **C7 Golden set expansion (fixes W2)**: 5 → 30–50 corps across industries/sizes/periods, hand-verified once against the DART viewer; wire into dq_nightly.
- **C8 Metric regression tests (fixes W4, W8)**: pytest suite freezing expected values for ratio/valuation/quarterly/per-share/screener math and key `app/compute/` functions (unit conversion, signs) against a small DB fixture.
- **C9 Amendment awareness (fixes W6)**: detect (corp, period) superseded by later 기재정정 filings; flag in trust badge; feed into I1 priority queue.
- **C10 Failure notification (fixes W7)**: macOS `osascript` notification (or mail) from dq_nightly/backup wrappers on nonzero exit or assertion failure — no more silent red.
- **C11 Recurring completeness matrix (fixes W5)**: dq_nightly assertion that every active corp has every expected period since listing (reuse `verify_corp_sequential` expected-report enumeration); coverage % surfaced in the B-4 trust badge.

### Phase D — Visualization freedom & product (Weeks 6–8)
- **D1 Free-form chart builder** (the "자유도" requirement): new page — pick any `std_financials_v2`/`calendar` column (plus price/market-cap overlay and per-share transform), N series, A/B ratio of two fields, annual/quarterly toggle; save/load presets as local JSON. Reuse `app/registry/metrics.py` loaders + `chart_panel.py`.
- **D2** V7 watchlist + saved screener queries (local JSON/SQLite); V8 drill-down: any metric cell → source filing (DART viewer URL from `rcept_no` via `statement_source`); confirm V3 (EV/EBITDA time series) done or add.
- **D3** New-data panels: backlog trend, dilution timeline, ownership structure, utilization by segment.
- **D4** (optional) tearsheet PDF/Excel export.

### Schedule summary
| Week | Focus |
|---|---|
| 1 (7/5–7/11) | Phase A: backup verify+restore drill, old worker removal, NAS order+setup, D3/D5/migrations + C10 notifications, C6 KRX assertion |
| 2 (7/12–) | B1 수주 + B5 D&A rule; kick off C5 full cross-source sweep (background, user-run) |
| 3–4 | B2 capital events (+panel), B3 대주주; C7 golden set expansion |
| 4–5 | B4 biz-section extractor v1 (manufacturing subset); C8 regression suite |
| 5–7 | C1 Track B line audit batches (background, user-run) + C2/C3/C9/C11 |
| 6–8 | D1 chart builder → D2 → D3 panels |

---

## Master checklist

### Phase A — Ops
- [x] A0 Save this roadmap as `docs/prd/09_improvement_roadmap.md`
- [ ] A1a Confirm 19:00 backup ran (logs + new dump in /Volumes/dart_data/db_backups, rotation working)
- [x] A1b Restore drill into scratch DB + `docs/runbook_backup_restore.md`
- [x] A2 Bootout + remove `com.dart.financial.worker` plist
- [ ] A3a NAS purchased, RAID1 volume + shares (`raw_report_mirror`, `db_backups2`)
- [ ] A3b rsync launchd jobs (weekly raw_report, daily dump copy) + mount guards
- [x] A4a D3 valuation_daily matview + refresh in collect_new.py
- [x] A4b D5 weekly VACUUM/ANALYZE job
- [x] A4c schema_migrations governance

### Phase B — Data
- [x] B1 order_backlog extractor + collector + pipeline + panel — **DONE (2026-07-05)**, v1 scope.
      Confirmed the 2026-07-04 rescoping (no DART API, body-table parsing only) and built it as an
      extension of B4's biz_section.py infrastructure (same document structure, same pollution risks,
      same reusable primitives: grid extraction, nested-TABLE exclusion, numeric parsing, financial-
      statement guard). Empirically found 3 structural formats across 6 real filers (삼성중공업/
      한화시스템/현대건설/GS건설/대우건설/한화오션): **aggregate** (few rows by segment, explicit
      수주총액/기납품액/수주잔고 columns), **detail-with-explicit-backlog** (dozens–hundreds of
      per-project rows with an explicit 계약잔액 column — summed to one company-level row), and
      **progress-only** (수주총액 + 진행률% with no explicit backlog column — deriving backlog would
      need value×(1-progress%), which is unreliable given rounding/change-order edge cases — v1
      explicitly skips this format rather than guess). New files: `fin2/extract/order_backlog.py`,
      `collector/order_backlog.py`, `scripts/collect_order_backlog.py`, wired into `collect_new.py`
      as non-fatal step ⑤-2, panel added to company_page's existing "🏭 생산·가동률" tab (reuses the
      pre-existing `OrderBacklog` schema unchanged). Fixed 3 bugs found via an 80-corp sample sweep
      (construction/shipbuilding/defense/machinery): date columns (수주일자/납기/수주년도) leaking
      into the category label, unit never captured (억원 vs 백만원 differs per filer — reused
      biz_section's `_narrative_unit`), and a heading that recurs as a running header deep in the
      financial-statement section pulling in unrelated tables (부채총계/현금성자산) — fixed with a
      `max_tables_per_marker` cap (mirroring biz_section's existing defense) plus a reused financial-
      statement keyword guard. Tests: `fin2/tests/test_order_backlog.py` 7/7 (real 6 filers),
      biz_section's 18 tests unaffected. 80-corp sweep: 24 corps with data, 72 rows, 0 anomalies.
      ⚠ Full backfill not yet run — user to run `collect_order_backlog.py --sample N --latest`,
      expand after spot-checking. Progress-only format (대우건설/한화오션-style) is a known B4b-style
      follow-up if reliable derivation logic is ever justified.
- [x] B2a capital_events table + collectors (CB/BW/EB/유증/자사주/증자감자) — 9 DART endpoints verified
      live (2026-07-04) before building: piicDecsn/fricDecsn/pifricDecsn/crDecsn/cvbdIsDecsn/
      bdwtIsDecsn/exbdIsDecsn/tsstkAqDecsn/tsstkDpDecsn. Key discovery: these decision-detail APIs
      filter by **board resolution date (bddd), not receipt date**, and always return only the
      **current/latest amended state** per decision (no historical versions) — required widening
      the detail-fetch lookback to 365 days and deriving `filed_at` from `rcept_no` prefix (no
      `rcept_dt` field in the detail response). `collector/dart_capital.py`.
- [~] B2b Backfill + incremental in collect_new.py — **10-month backfill done (2025-09~2026-07,
      not full 2015+): 2,843 rows across 1,071 corps** (paid_increase 702·cb_issue 587·
      treasury_dispose 899·treasury_acquire 301·eb_issue 137·reduction 134·free_increase 42·
      bw_issue 29·mixed_increase 12). shares_delta field-extraction coverage is high (88–100%)
      except treasury_dispose (36% — some disposal sub-methods likely use a different field name
      than `eaq_ostk`; raw data preserved in `detail` JSONB regardless, fixable later without
      re-fetching). Incremental daily sync wired into `collect_new.py` (⓪-2, non-fatal). Deeper
      historical backfill can be run later the same way (just call `sync_capital_events` with an
      earlier `bgn_de`).
- [x] B2c Dilution overlay on share-count chart + potential-dilution metric — `app/data/capital.py`
      + `chart_panel.render_pershare_panel` markers (▲dilutive/▼reduction/◆potential CB-BW-EB) on
      the B-2 share-count chart, "잠재 희석 %" caption (upper-bound estimate, doesn't track
      conversion/redemption status — noted as a known limitation), event history expander.
      Verified live via Playwright on 제이에스링크(00642541, real CB history).
- [x] B3 major_shareholders table + collectors + ownership panel — 3 DART endpoints verified live
      before building (roadmap's naming was correct this time, unlike B1): `hyslrSttus`(최대주주
      현황), `hyslrChgSttus`(최대주주 변동현황), `mrhlSttus`(소액주주 현황/float 근사치). New tables
      `major_shareholders`/`shareholder_changes`/`retail_ownership`, `scripts/collect_shareholders.py`
      (mirrors `collect_executives.py` pattern). Ownership panel added to the existing "임원" tab
      (renamed "임원·지분"): 최대주주+특수관계인 %, 소액주주 %, holder table, change history.
      **Bug caught before commit**: DART's `hyslrSttus` includes "계"(subtotal) rows per stock kind
      — naively summing all rows double-counted the major-shareholder % (40.4% instead of the
      correct 20.2% for Samsung); fixed to prefer the "계" rows when present. Verified live via
      Playwright against Samsung Electronics (20.2% major + 68.2% retail, matches public knowledge).
      100-corp sample backfilled (not full 2,557 — same background-run pattern as executives).
- [~] B4a biz_metrics table + biz_section extractor v1 (생산능력/실적/가동률/수주상황) —
      **prototype done (2026-07-04), DB schema/wiring not started**: `fin2/extract/biz_section.py`
      finds the 생산능력/생산실적/가동률 subsection headings (heading format varies wildly by
      company — Samsung uses individual `(생산능력)`/`(생산실적)`/`(가동률)` SPAN markers, S-Oil
      combines "생산실적 및 가동률" into one numbered-paragraph heading covering both) and returns
      the following table(s) as a loss-less 2D grid with proper ROWSPAN/COLSPAN expansion (reused
      nowhere else in the codebase — `parser/xml/table_extractor.py`'s `extract_rows` assumes a
      3-column financial-statement shape and doesn't fit this). Validated against 3 real, unrelated
      industries: Samsung Electronics (perfect), S-Oil (perfect, correctly merged output+utilization
      table), HD Hyundai Heavy Industries (core utilization/output data correct — 97.1%/28.9%/148.4%
      per segment — but 1 of 5 "capacity" matches pulled in an unrelated raw-materials table because
      its heading "다. 주요 원재료 및 생산능력" combines two topics under numbered sub-items (1)/(2)
      — a genuine heterogeneity case for B4b to iterate on, not a bug).
      **DONE (2026-07-04, part 2)**: two tables added — `biz_section_tables` (loss-less raw grid +
      narrative, one row per source table) and `biz_metrics` (structured long-format: corp, fiscal_year,
      rcept_no, table_ord, metric[capacity/output/utilization], segment, item, period_label, period_year,
      value, unit, is_ratio). Canonical mapping `fin2/extract/biz_section.map_biz_table` classifies
      columns (dimension vs value, unit column detection), resolves periods (제N기→calendar year via
      max-기 relative mapping, or `(YYYY년)` direct; non-period supplementary tables keep the column
      header as `period_label` with `period_year`=NULL — loss-less), and resolves per-column metric via
      explicit keywords + header hints (능력→capacity / 실적·생산량→output) + a **ratio-consistency
      guard** (a % value is always utilization; a 가동률-labeled column with a non-% value is
      reclassified — fixes the 삼화전기 "설비능력수량" 426,624 being mislabeled as 426,624%
      utilization). Collector `collector/biz_metrics.py::sync_biz_metrics` (finds annual reports via
      download_tasks.file_path JOIN filings, corp+rcept delete-then-insert, idempotent) +
      `scripts/collect_biz_metrics.py` (sample/resume/corps, mirrors collect_shareholders.py) +
      wired into `collect_new.py` as non-fatal step ⑤-1 (latest annual of newly-standardized corps).
      Tests `fin2/tests/test_biz_section.py` (5, real Samsung+S-Oil). Validated: 150-corp sample =
      3,154 rows, 0 errors, utilization max 102.7% (0 outliers >200%); string fields clipped to column
      limits so a facilities/소재지 table's long address label can't crash a corp's insert.
      ⚠ Full 2,557-corp backfill not yet run (long background job — hand to user:
      `python scripts/collect_biz_metrics.py --latest --skip-existing`).
- [x] B4b Coverage report by industry; iterate parser — **DONE (2026-07-04)**: coverage tool
      `scripts/biz_metrics_coverage.py` (KSIC 2-digit division map, per-industry 생산표 보유율 +
      avg rows + ★flag for manufacturing divisions <50% covered; `--manufacturing`/`--missing`).
      Parser iteration (empirically driven by a 300-corp read-only file sweep) fixed the dominant
      leaks: (1) **production-column filter** — a value column must resolve to a period (제N기/YYYY)
      OR contain a production keyword (생산/가동/능력/설비); a table with no such column is not a
      production table → dropped, killing PP&E 장부금액 tables (01435489) and 공장 소재지/면적 tables
      (00120076). (2) **clean-number value-column test** — a value column must be majority "clean
      numbers" (leading digit + short unit, no ÷×=), dropping 계산근거 formula columns whose embedded
      `%` was contaminating utilization (강남제비스코 실제가동시간 2,350 → bogus 2350% util). (3)
      tightened non-period `period_label` fallback (reject 단위/기준/소재지/narrative, ≤20 chars).
      Sweep before→after: facility leaks→0, utilization out-of-[0,200]→0 (remaining >100% like
      00162911's 278% are the report's own values — 실제가동 6,683h/가능 2,400h, not bugs, like the
      Samsung-2026 source case), null-year% 43–63%→26.5%. Regression tests +2 (강남제비스코 formula
      column, LX인터내셔널 facility drop) → `test_biz_section.py` 7 total. ⚠ Existing biz_metrics rows
      (from B4a sample runs + any in-flight backfill) are stale vs the new parser — re-run the full
      backfill to regenerate clean rows: `python scripts/collect_biz_metrics.py --latest` (idempotent
      per rcept). Remaining for future: 수주상황(order backlog) section type; per-column units in
      S-Oil 표준생산능력 detail table; units embedded in segment labels (반도체기판 "패키지솔루션(천㎡)").
- [ ] B5 D&A note augmentation rule + parity re-check (ebitda/fcf divergence → 0)

### Phase C — Verification
- [ ] C1 Track B line audit: harness extension → full 107,847 batch run → diff triage → gate pass
- [ ] C2 con<sep 22 rows triaged
- [ ] C3 DQ assertions for backlog/capital_events/biz_metrics
- [x] C4 Quarterly restore drill scheduled in runbook
- [ ] C5 Full-universe cross-source sweep (2,557 corps × recent FY) + triage; rotation re-weighted to latest periods
- [ ] C6 Computed-vs-KRX EPS/BPS/PER nightly consistency assertion — **BLOCKED (2026-07-04)**: this
      item assumed `stock_prices.per/pbr/eps/bps/div_yield/dps` already held independent KRX-sourced
      values to compare against. Checked live DB: all five columns are 100% NULL (0/11.2M rows) —
      never populated. `analyzer/price_fetcher.py:371` documents why: pykrx's fundamental endpoint
      returns empty responses (structural breakage), so the design deliberately derives market_cap
      from close_price × DART shares_out instead, and never attempted per/eps/bps at all. There is
      currently no independent second source to cross-check against — C6 needs a new KRX data
      source design (direct KRX open API, alternate library, or scraped fallback) before it's
      implementable. Revisit as its own scoped item, not a quick win.
- [ ] C7 Golden set 5 → 30–50 corps, wired into dq_nightly
- [ ] C8 Pytest regression suite for derived metrics + app compute functions
- [ ] C9 Amendment-supersede flag + trust-badge surfacing
- [x] C10 Failure notifications (osascript/mail) on dq_nightly/backup errors
- [x] C11 Recurring completeness matrix (every corp × every expected period) in dq_nightly — implemented
      as a forward-looking staleness check (no `listing_date` column exists, so full since-listing
      re-enumeration wasn't attempted — the 2026-06-25 full run already proved that once). Calibrated
      against two real false-positive classes: fiscal-year-change stub periods (아시아종묘, fixed by
      not excluding `is_stub`) and brand-new listings (5 corps, fixed via `dart_modify_date` proxy for
      listing recency, since no listing_date exists). After calibration, found 1 genuine flag: 피씨엘
      (01051092) — no filing since Q3 2025, worth a manual look.

### Phase D — Visualization
- [ ] D1 Free-form chart builder page (+preset save/load)
- [ ] D2a Watchlist + saved screens
- [ ] D2b Drill-down to source filing (rcept_no link)
- [ ] D2c V3 EV/EBITDA time series confirmed/added
- [ ] D3 Panels: backlog / dilution / ownership / utilization
- [ ] D4 (opt) Tearsheet export

## Verification (per phase)
- Phase A: restore-drill row counts match spot checks; `launchctl list` shows new jobs exit 0; NAS mirror file counts match `find | wc -l`.
- Phase B: for 2–3 known corps (삼성전자 + a mid-cap with CB history), cross-check collected events/backlog against the DART viewer by eye; `dq_nightly` stays green.
- Phase C: Track B gate pass counts reported; `face_line_audit` fail=0 after triage.
- Phase D: `streamlit run app/main.py` — build a 2-field ratio chart from raw columns, save/reload preset, drill from a metric to the DART filing page.
