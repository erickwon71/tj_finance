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
- [ ] A1a Confirm 19:00 backup ran (logs + new dump in /Volumes/tj_finance_data/db_backups on NAS, rotation working)
- [x] A1b Restore drill into scratch DB + `docs/runbook_backup_restore.md`
- [x] A2 Bootout + remove `com.dart.financial.worker` plist
- [~] A3a NAS purchased (Synology DS723+), RAID1 volume + SMB share `tj_finance_data`
      mounted at `/Volumes/tj_finance_data`. raw_report NAS 복사 진행 중; postgres 컨테이너 실행 상태.
      ⚠ HW 개선(RAM 16GB+ / NVMe SSD 볼륨) 후 DB 이전 예정 — 상세는 memory nas-migration-plan.
- [x] A3b DB dump → NAS 직접 저장 (2026-07-05): 별도 mirror 잡 대신 `backup_db.py` 의 `--out-dir`
      기본값을 NAS(`/Volumes/tj_finance_data/db_backups`)로 변경 + plist 반영. **dart_data 사본 제거**
      (NAS RAID1 + 라이브 Mac DB = 독립 2 장애도메인이므로 3번째 사본 불필요; 기존 3개 덤프는 NAS와
      SHA-256 일치 확인 후 삭제, 1.2G 회수). `restore_drill.py`/README/runbook 경로도 NAS로 갱신.
      NAS 미마운트 시 백업 실패+알림(마운트 가드). 실검증: pg_dump 493MB 직접 NAS 저장 exit 0.
      launchd plist 재복사+리로드 완료, 실트리거로 자동 19:00 경로 NAS 반영 확인(exit 0, 복원드릴 PASS).
      ⚠ 아직 남음: **주간 raw_report 미러 rsync 잡**(raw_report NAS 전체 복사 완료 후 세팅 예정 —
      사용자 계획: 복사 완료되면 sdcard 은퇴, NAS를 raw_report main으로 전환. 코드/DB 는 이미
      `<project>/raw_report` 심링크(`collector/config.py`)만 거치고 `download_tasks.file_path` 도
      이 안정 경로로 저장되어 있어 **전환은 심링크 재지정 한 줄로 완료**(코드/DB 변경 불필요) —
      전환 전 완결성 검증(find|wc, du -sh 양쪽 대조) 필수. 상세 계획은 memory nas-migration-plan).
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
      **Full backfill DONE (2026-07-05)**: `collect_order_backlog.py --skip-existing --latest` over
      all 2,555 active corps — 기업 1,988(신규 대상만) · 행 0 · 빈 1,988 (건너뛴 567사가 기존
      2,070행/보유 — sum 2,555 checks out). Verified the 0-row result wasn't a regression by
      re-running known-good filers (삼성중공업·현대건설) directly — still extract 9 rows correctly;
      the 1,988 "empty" corps are genuinely non-backlog industries (`--skip-existing` filters live on
      `SELECT DISTINCT corp_code FROM order_backlog`, confirmed in `scripts/collect_order_backlog.py`).
      Order backlog coverage effectively complete for v1 scope. Progress-only format (대우건설/
      한화오션-style) remains a known B4b-style follow-up if reliable derivation logic is justified.
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
      re-fetching). Incremental daily sync wired into `collect_new.py` (⓪-2, non-fatal).
      **2015+ full backfill (2026-07-05): `scripts/backfill_capital_events.py`** — per-DART-quirk,
      the detail API's lookback is anchored to `end_de` (365 days back), so a single call spanning
      years would silently miss old events; script runs one call per calendar year instead. Ran
      2015~2021 successfully (+8,493 rows, ~3-4min/year), but 2022~2026 silently returned "0 new"
      in <1s each — turned out to be DART's daily quota exhausted mid-run (confirmed via direct
      `status='020'` reproduction), which the old `dart_capital._get()` swallowed as indistinguishable
      from "genuinely no events" (user caught this from the suspiciously fast log, not a proactive
      catch). **Fixed**: `_get()` now raises the project's existing `DartApiError` for any non-'000'/
      non-'013' status instead of silently returning `None`; the backfill script catches it
      specifically and stops immediately with a clear resume command, rather than "completing"
      having silently skipped years. ⚠ **2022–2026 still need re-running once the DART quota
      resets** (`python scripts/backfill_capital_events.py --start-year 2022`).
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
- [x] B4a biz_metrics table + biz_section extractor v1 (생산능력/실적/가동률/수주상황) —
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
      **Full backfill DONE (2026-07-05)** — see B4b closing note below (all years, not just latest).
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

      **Full-history regeneration DONE (2026-07-05)**: ran `python scripts/collect_biz_metrics.py`
      (no flags = all 2,555 active corps × all fiscal years, not just `--latest`) before the planned
      raw_report→NAS migration (local disk is faster for a 41,749-report full sweep than SMB).
      Result: 기업 2,555 · 보고서 41,749 · 표 109,547 · 지표행 1,091,876 · 빈 831 · 오류 0 (~2h,
      `fetched_at` 03:23–05:26 confirms every year 1999–2026 was genuinely re-extracted, not skipped).
      **Investigated before trusting the "stale" premise**: total row count came out nearly identical
      to the pre-rerun total (1,091,876 both times) — checked whether this meant the rerun was a
      silent no-op. It wasn't: `fetched_at` timestamps confirm real re-extraction, and the coincidence
      is explained by the B4b guards being narrow (they only trip on genuinely pathological tables,
      which are a small minority) rather than the historical data being bulk-corrupted. Confirmed the
      two known bug cases from the B4b note are actually fixed in the regenerated data: 강남제비스코
      util>500% row — gone; LX인터내셔널 소재지/번지/주소-labeled rows — 0 (was leaking before B4b).
      So the historical (pre-2025) rows previously in the table were mostly already equivalent to
      what the fixed parser produces — the "stale" concern was real but narrow in practice, and this
      full rerun now guarantees every row reflects the current parser, closing the concern definitively.
- [x] B5 D&A note augmentation — **rescoped + DONE (2026-07-05)**. Investigation changed the
      premise: the original "parity re-check (ebitda/fcf → 0)" is obsolete/unachievable — the legacy
      parity table was dropped in Phase 5, **fcf is already fine** (90–97% coverage, not a gap), and
      the residual **ebitda/da_total gap is data-limited/irreducible** (consolidated ceiling ~42%,
      separate ~34% — per the 2026-07-04 dry-run, D&A is simply absent from many CF statements). The
      note-D&A *assembly* rules (`rule_additive_da`/`rule_ebitda` + `build.py` `_DA_SUPP` collection)
      already existed and work; the D&A *extraction* (`cf_da.recover_cf_da`) only ran as **one-time
      backfill scripts** and was **not wired into the standard pipeline**, so new/incremental reports
      regressed (2026 new = ~11% EBITDA vs 2025's 42%). **Real fix = permanence**: new
      `collector/cf_da_sync.py::sync_cf_da(corps, year_min)` runs the proven recover_cf_da
      (note-first/face-fallback, unit guard) corp-restricted → fact_v2 upsert → **S→Q→C re-propagation**
      (annual std_v2 + discrete-quarter + calendar view, fixing the calendar-staleness the memory
      flagged). Wired into `scripts/collect_new.py` as non-fatal step ④-2 (both normal + resume
      paths) so newly-standardized corps auto-recover D&A. Verified: plumbing smoke (5 corps → 51
      targets found, clean end-to-end); non-destructive proof (`recover_cf_da` on 00264945 2024 FY →
      3 real facts: dep 21.8B/amort 7.1B/da_total 28.9B). The one-time full backfill stays as the
      historical tool; the absolute coverage ceiling is unchanged (data absent, not a pipeline bug).

### Phase C — Verification
- [~] C1 Track B line audit: harness extension → full 107,847 batch run → diff triage → gate pass —
      **HARNESS BUILT + SAMPLE-VALIDATED (2026-07-05); full batch = user-run (long)**. Track A line
      audit (`reconcile_report_lines`) keys on the XBRL acode (exact), so text-track reports
      (`source_format='xml_text'` — the **largest** fact source at 69.3M rows) were left `pending`.
      Added `reconcile_report_lines_text` in `fin2/audit/line_audit.py` using the proven Phase A
      **direction + key**: since the independent reader (`read_report_face_text`) reads *all* columns
      (당기+비교연도) and labels are unstable keys, we verify **each fact_v2 current value (col0,
      authoritative) is present in the report's (canonical,basis) value-set** — not each report line
      against the DB (that first cut gave 62.6% false VALUE_DIFF from comparative-year columns; the
      flipped direction is the fix). VALUE_DIFF = a DB current value backed by *no* report column
      (extraction picked wrong table/unit — blocking candidate); MISSING = reader didn't locate the
      canonical (coverage indicator, non-blocking); EXTRA is structurally N/A for text. New
      measurement tool `scripts/line_audit_trackb.py` (sample/corp/full, measurement-first per Track A
      convention — no persist yet). **Sample result: 240 reports (40+200), ~46K lines, VALUE_DIFF 0,
      MISSING ~0** — report↔DB fidelity holds for Track B. Tests: `test_line_audit.py` +5 (13 total).
      **Larger validation (user-run 2026-07-05)**: 2,000-report confidence batch = 290,006 lines,
      **VALUE_DIFF 0**, MISSING 68 (0.02%, reader-coverage). **INTEGRATED into production Gate B
      (2026-07-05)**: `gateb_audit.audit_lines` now dispatches on track — Track B reports run
      `reconcile_report_lines_text` and get a real pass/fail_a gate persisted to `face_line_audit`
      with `track='B'` (was `pending`); fact load augmented with `canonical_account`. Integration
      smoke (8 corps, `--recheck`): 67,752 lines, value_diff 0, **report gate pending 0** (all 477
      source reports graded, incl. Track B) — DB now holds 430 `track='B'` `pass` rows.
      **Remaining (user-run)**: a full `python scripts/gateb_audit.py --recheck` sweep to upgrade the
      ~107,349 already-`pending` Track B reports to graded (a normal non-recheck run skips
      already-audited rcepts); triage any VALUE_DIFF per the 94-FP playbook (expected ~0 given the
      sample). `scripts/line_audit_trackb.py` remains as the standalone measurement/triage tool.
- [x] C2 con<sep 22 rows triaged — **DONE (2026-07-05)**, `docs/dq_con_lt_sep_triage_2026-07-05.md`.
      The "22" = `con>0 ∧ sep>0 ∧ sep≤1000조 ∧ con<sep×0.5 ∧ FY ∧ fy≥2015` = **21 rows** (full
      con<sep is 14,525, dominated by old sign/unit/zero artifacts). Per-case via fact_v2 candidate
      values: **~10 LEGIT** (한국토지신탁 trust-accounting, 별도 includes 신탁계정 11–13조 > 연결
      1.7–2조, consistent 10yr, no unit bug) → con<sep is correct, not blockable; **~8 BUG** (dominant
      = 별도 ×1000 unit-misdetection where the correct value also sits in fact_v2 but standardization's
      max-abs picked the inflated adec=-3 row — 상상인증권/카카오게임즈/KB금융; + 인카 con tiny-value
      pick) = the known "별도 버그클래스" (root fix design-heavy); **~3 ambiguous** (2015 financials/
      IPO, no unit bug, lean legit). Feeds C3: a `con_lt_sep` DQ assertion flags new occurrences with a
      trust/securities allowlist (root ×1000 fix deferred).
- [x] C3 DQ assertions for backlog/capital_events/biz_metrics — **DONE (2026-07-05)**. Added to
      `scripts/dq_assertions.py` (nightly, WARN-level indicators — ERROR gate stays green): (1)
      `order_backlog_negative` (backlog_amt<0, baseline 10 — body-table parse errors); (2)
      `capital_events_unknown_type` (event_type outside the 9 known values, baseline 0 — clean guard
      catching future collector drift); (3) `biz_metrics_util_impossible` (utilization>500%, baseline
      16 — 계산근거/설비수량 misclassification beyond legit overtime). Also **sharpened the C2 signal**:
      replaced the noisy `consolidated_lt_separate_assets` (con<sep×0.999 = 14,525 rows) with
      `consolidated_lt_separate_assets_material` (con<sep×0.5, positive, sep≤1000조, FY, fy≥2015 =
      baseline 21) so it's an actionable indicator, not noise. (The complex "shares_out change ↔
      matching capital_event" correlation is deferred — high noise, low incremental value vs these
      direct integrity guards.)
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
- [x] C8 Pytest regression suite for derived metrics + app compute functions — **DONE (2026-07-05)**.
      New `tests/` package with **54 golden-value regression tests** over the previously-untested
      derived/analytics layer (fixes W4/W8). Pure, DB-independent (synthetic hand-computed inputs);
      valuation multiples test monkeypatches `price_fetcher.get_market_data`. Follows the fin2/tests
      convention (self-contained `_util.run_tests`, no pytest dependency) + `tests/run_all.py`
      aggregator — run with `python tests/run_all.py` (also pytest-collectable if installed).
      Coverage: `test_ratio_engine` (compute_ratios: margins, avg-balance ROE/ROA, ROIC/NOPAT,
      working-capital days, growth, guards), `test_valuation_engine` (PER/PBR/PSR/PCR/EV·EBITDA/
      EBIT/FCF + controlling_ni preference), `test_units` (억원/%/x/원-주 conversions + signs),
      `test_derived_resolver` (D1 ratio/diff/pershare + build_metric_frame column-vs-ratios +
      validate rules), `test_checks` (anomaly guard: margin>100%/>60%, annual/quarter spike
      triggers), `test_screen_eval` (aggregate avg/YoY/CAGR/QoQ, effective_unit, make_threshold,
      apply_pass filter/sort/limit + missing policy, magic_rank), `test_master_metrics` (Graham
      Number/EY/ROC/PEG/Fisher). **Latent finding surfaced**: `ratio_engine._growth_rate` docstring
      says "음수 전기 → None" but the code only guards `prev == 0` (negative prev returns
      (c-p)/|p|); the test pins actual behavior and flags the doc/code mismatch for a separate fix.
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
- [x] D1 Free-form chart builder page (+preset save/load) — **DONE (2026-07-05)**, v1 scope.
      New page "🧪 자유조합 차트" (`app/views/chart_builder_page.py`, wired into `app/main.py`
      nav). Built on the existing registry + resolver + chart_panel infra (per the 2026-07-04
      decision to keep the field source as the ~50-metric curated registry rather than exposing
      every raw std_v2 column — units/names/signs are all defined there). Adds the four D1
      capabilities: (1) **파생 필드(조합)** via new `app/compute/derived.py` — 비율(A÷B, 무차원
      x), 차분(A−B, 금액필드끼리만), 주당(A÷발행주식수, 원/주); computed on the same tidy frame
      the base metrics use, so chart/table/CSV reuse the same path. (2) **주가 오버레이** — the
      금액(억원) series currently in the frame (base + diff-derived) can be laid over the price
      line via the existing `render_price_financial_combined` (≤3, log toggle). (3) **프리셋
      저장/로드** via new `app/data/presets.py` (local JSON at `~/.tj_finance/chart_presets.json`,
      atomic tmp→replace write, corrupt/missing-file tolerant). (4) **연간/분기** follows the
      global sidebar grain. One small unit added: `UnitType.WON_PER_SHARE("원/주")` in
      `app/registry/units.py` (+ chart_panel hover suffix). Verified: derived math against real
      삼성전자 data (매출−매출원가 2024=114.3조 = gross profit ✓, 순이익 주당 EPS, FCF/영업이익
      ratios incl. negative-FCF year); headless `AppTest` render of the page with a real corp +
      seeded derived specs + overlay = 0 exceptions, all widgets built, price-overlay path
      executed; preset save/list/get/delete + corrupt-file roundtrip. Follow-ups for a future
      iteration: exposing raw (non-registry) columns; letting per-share/ratio derived fields
      participate in the price overlay (currently amount-only); optional PCT rendering for a
      ratio-of-two-amounts (today ratios render as x).
- [x] D2a Watchlist + saved screens — **DONE (2026-07-05)**. Introduced a shared local-JSON
      store `app/data/_localstore.py` (atomic tmp→replace, corrupt/missing-tolerant) and refactored
      D1's `presets.py` onto it. **Watchlist** (`app/data/watchlist.py`, `~/.tj_finance/watchlist.json`):
      ⭐ toggle button on the company-page header (`_watch_toggle`) + a "⭐ 관심종목" sidebar expander
      (`_watchlist_sidebar` in `app/main.py`) listing starred corps as one-click focus-jump buttons
      with ❌ remove. **Saved screens** (`app/data/saved_screens.py`, `~/.tj_finance/saved_screens.json`):
      a "💾 저장된 스크린" bar on the screener that snapshots the screener's session widget config
      (keys matching `^(scr_|p\d+_)`, excluding the bar's own meta widgets) and restores it via
      session-state + rerun — so the whole filter/sort/aggregation/pass setup saves & reloads by name.
- [x] D2b Drill-down to source filing (rcept_no link) — **DONE (2026-07-05)**. New
      `app/data/sources.py::load_statement_sources` reads `statement_source.source_rcept_no` per
      (year, BS/IS/CF) for the displayed basis and groups distinct filings (so a partial 기재정정
      that sources BS from a different filing than IS/CF shows as separate links). Surfaced as a
      "🔗 이 값의 원천 공시" expander in the 재무제표 tab (`company_page._source_drilldown`), each
      filing a DART-viewer `link_button` (reuses `reports.DART_VIEWER`). Cached via
      `cache.statement_sources`. Verified against real 삼성전자 data (2024 BS·IS·CF ← rcept
      20250311001085, the actual 사업보고서).
- [x] D2c V3 EV/EBITDA time series confirmed/added — **CONFIRMED present (2026-07-05)**. Already
      implemented: `ev_ebitda` is in `valuation_bands.BAND_METRICS` and renders as a time-series +
      historical-percentile band in the 밸류에이션 tab. Verified real coverage (삼성전자 2,594
      non-null trading days in `valuation_daily`). No new work needed; noted the known
      ~25%-coverage caveat (EBITDA data gap) means the band is empty for low-coverage corps.
- [x] D3 Panels: backlog / dilution / ownership / utilization — **DONE (2026-07-05)**. Ownership
      (B3, "임원·지분" tab) and utilization-by-segment (B4, "생산·가동률" tab) panels already
      existed from Phase B and were confirmed present/working. Filled the two genuine gaps where
      Phase B only had a snapshot: (1) **backlog trend** — `order_backlog` already holds multi-year
      data (567 corps, 2020–2026, up to 6 yrs/corp), but the panel only showed the latest year's
      table; added `load_order_backlog_trend` (yearly total = Σ backlog_amt) + `render_backlog_trend`
      (bar) + a growth caption, shown above the existing latest-year breakdown when ≥2 years exist.
      (2) **dilution timeline** — B2c only overlaid yearly buckets on the share-count chart; added a
      standalone chronological panel (`capital.dilution_timeline` + `render_dilution_timeline`) in
      the 밸류에이션 tab: date-axis markers by category (▲증자 ▼감자 ◆잠재CB/BW/EB ●자기주식) plus a
      dotted cumulative-confirmed-issuance line (potential/treasury excluded from the cumulative).
      Handles board_date→filed_at fallback and shares_delta-missing events (markers skipped, noted).
      Verified against real data: 00155531 6-yr backlog trend; dilution timeline across corps
      exercising all four categories (00536329 has 증자/감자/잠재/자기주식; 삼성 = 20 treasury-only,
      cum=0). Both tabs headless-`AppTest` = 0 exceptions.
- [x] D4 (opt) Tearsheet export — **DONE (2026-07-05)**. One-page A4 PDF company summary via
      matplotlib (already installed — no new dependency, no external service; the existing CSV
      export covers raw data, so this is the complementary *visual* one-pager). `app/components/
      tearsheet.py::build_tearsheet_pdf` renders header + valuation snapshot (시총/PER/PBR/PSR/
      EV·EBITDA/EPS/BPS/배당수익률) + 재무 요약 table (매출/영업이익/순이익/자산/자본, 8yr) +
      수익성·안정성 table (ROE/영업이익률/순이익률/부채비율) + two trend charts (매출·영업이익,
      ROE·영업이익률), returned as PDF bytes. Korean rendering via Mac font autodetect
      (AppleGothic → Apple SD Gothic Neo → Nanum Gothic). Wired as a **deferred** generate→download
      in the 재무제표 tab (`company_page._tearsheet_download` + `cache.tearsheet_pdf`, matplotlib
      cost paid only on button click, then cached). Verified: real 삼성전자 PDF (86KB, valid %PDF)
      rendered to PNG and visually inspected — Korean correct (no tofu), tables/charts/values right
      (2025 매출 333.6조); table row-labels moved into a first column to fix left-edge clipping;
      headless AppTest with generation forced = 0 exceptions.

## Verification (per phase)
- Phase A: restore-drill row counts match spot checks; `launchctl list` shows new jobs exit 0; NAS mirror file counts match `find | wc -l`.
- Phase B: for 2–3 known corps (삼성전자 + a mid-cap with CB history), cross-check collected events/backlog against the DART viewer by eye; `dq_nightly` stays green.
- Phase C: Track B gate pass counts reported; `face_line_audit` fail=0 after triage.
- Phase D: `streamlit run app/main.py` — build a 2-field ratio chart from raw columns, save/reload preset, drill from a metric to the DART filing page.
