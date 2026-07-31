# 런북 — 데일리에 파싱·DB 적재 되살리기 (Phase 5)

> 상태: **미실행.** 계층3 재설계가 끝난 뒤 착수한다.
> 배경 계획: `docs/plans/collection_pipeline_restore_2026-07-31.md` §5.1 · §7
> 필수 동반 절차: `docs/runbook_new_parser_pipeline_integration.md`

---

## 0. 지금 어떤 상태인가

2026-07-31 부터 데일리(`com.tjfinance.collect`, 매일 18:00)는 **다운로드까지만** 한다.

```
⓪   저장소 계약 검증          storage_guard.assert_storage()
⓪-1 시장조치 이벤트
⓪-2 자본 이벤트
⓪   유니버스 갱신             KRX OpenAPI + FDR (기본 ON)
⓪-3 상장폐지 판정             DB 상태만 — 원문 파일은 안 건드림
①   공시 탐지                 --days auto (pipeline_runs 워터마크)
②   공시목록 동기화           정정보고서 버전관리 포함
③   다운로드                  → NAS
────────────── 여기서 멈춘다 (Phase 5 경계) ──────────────
④   파싱·표준화               ⛔ 조건 분기로 대기
④-2 D&A note 복원             ⛔
④-3 계층2 전사                ⛔
⑤   DQ 게이트                 ⛔
⑤-1 사업지표 / ⑤-2 수주 / ⑤-3 정기API  ⛔
──────────────────────────────────────────────────────
⑥   NAS→SD 증분 미러
⑦   완전성 감사
⑧   워터마크 기록
```

**⛔ 는 삭제된 게 아니라 조건 분기다.** `scripts/collect_new.py` 의 `if args.download_only:`
블록 위 주석(`확장 지점 (Phase 5)`)이 코드상의 경계다.

---

## 1. 되살리는 방법 (핵심은 한 줄)

`deploy/launchd/com.tjfinance.collect.plist` 의 ProgramArguments 에서 아래 한 줄을 지운다.

```xml
<string>--download-only</string>
```

그리고 재등록:

```bash
cp deploy/launchd/com.tjfinance.collect.plist ~/Library/LaunchAgents/
launchctl bootout gui/$(id -u)/com.tjfinance.collect
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tjfinance.collect.plist
launchctl list | grep tjfinance          # 레이블이 보여야 한다
```

**단, 이것만 하면 안 된다.** 아래 2~5 를 반드시 함께 처리한다.

---

## 2. ★두 call site 모두 배선했는가 (가장 자주 잊는 것)

`scripts/collect_new.py` 에는 파싱 경로가 **두 군데** 있다.

| # | 위치 | 언제 타는가 |
|---|---|---|
| 1 | `main()` 메인 흐름 (③ 다운로드 이후) | 평상시 데일리 |
| 2 | `if args.standardize_only:` 블록 | 중단 후 재개 (`--standardize-only`) |

새 파서·로더를 추가하면 **양쪽 다** 호출해야 한다. 한쪽만 배선하면 평상시엔 되는데
재개 실행에서만 조용히 빠진다(또는 그 반대).

```bash
# 확인: 두 블록에 같은 sync 함수가 다 들어 있는가
grep -n "_sync_cf_da\|_sync_layer2_lines\|_sync_biz_metrics\|_sync_order_backlog\|_sync_periodic_apis" \
     scripts/collect_new.py
```

---

## 3. ★소급 백필은 자동이 아니다

`--download-only` 로 운영한 기간에 받은 원문은 **DB 에 반영돼 있지 않다.**
플래그를 뺀다고 과거분이 저절로 채워지지 않는다.

대상 구간은 `pipeline_runs` 에서 정확히 뽑을 수 있다:

```sql
SELECT min(window_bgn) AS 시작, max(window_end) AS 끝, count(*) AS 실행수
FROM pipeline_runs
WHERE mode = 'download_only' AND status = 'success';
```

그 구간에 다운로드된 기업 목록:

```sql
SELECT DISTINCT f.corp_code, c.corp_name
FROM download_tasks d
JOIN filings f USING (rcept_no)
JOIN corporations c ON c.corp_code = f.corp_code
WHERE d.status = 'completed'
  AND d.completed_at >= (SELECT min(window_bgn) FROM pipeline_runs
                         WHERE mode = 'download_only' AND status = 'success')
ORDER BY 2;
```

재표준화 실행:

```bash
.venv/bin/python scripts/collect_new.py --standardize-only --corps <쉼표구분 corp_code>
# 또는 전체 미표준화분
.venv/bin/python scripts/collect_new.py --standardize-only
```

> 2026-07-31 기준 download-only 구간은 07-06 부터다(`pipeline_runs` id=1).
> 여기에는 **B3 신규상장 백필분**(스트라드비젼 2024년치 포함)도 들어 있다.

---

## 4. ⚠상장폐지 확정 기업의 원문은 `raw_report` 밖에 있다

`delisting_status='confirmed'` 이고 `--archive` 를 실행한 기업의 원문은
`/Volumes/tj_finance_data/archive/delisted/<연도>/<코드_이름>/` 로 **이동**돼 있다(삭제 아님).

전량 재적재를 돌리면 그 기업들은 원문을 못 찾는다. 이때:

- **기존 DB 데이터를 보존하고 명시적으로 스킵 + 로그**할 것
- 조용히 빈 값으로 덮어쓰면 **과거 시계열이 사라진다**

대상 확인:

```sql
SELECT corp_code, corp_name, delisted_at, archive_path
FROM corporations WHERE delisting_status = 'confirmed' AND archive_path IS NOT NULL;
```

아카이브분까지 재적재해야 한다면 먼저 되돌린다:

```bash
.venv/bin/python scripts/delisting_manage.py --restore <corp_code> --apply
```

---

## 5. 실행 시간·자원 영향 (실측 기반)

| 항목 | 실측값 | Phase 5 영향 |
|---|---|---|
| NAS 파일 open 지연 | **26.8 ms/건** (SD 0.6ms, 46배) | 102,633 filing 재파싱 시 **약 46분**의 순수 open 지연 |
| NAS 대량 읽기 | 43.4 MB/s (SD 86.8, 2배) | 대역폭은 문제 아님 |
| 직전 전량 재적재 | 5h19m | NAS 기준 ≈ 6h05m 예상 |

데일리 증분(하루 수십 건)은 영향이 무시할 수준(60건 × 27ms ≈ 1.6초)이다.
**전량 재파싱이 잦아지면** 배치 전 로컬 스테이징을 검토한다(주 저장소를 바꾸는 것보다 낫다 — 결정 D6).

---

## 6. 되살린 뒤 검증

| ID | 대상 | 합격 기준 |
|---|---|---|
| P5-1 | 회귀 | `.venv/bin/python tests/run_all.py` 전건 통과 |
| P5-2 | 두 call site | 메인·재개 양쪽에서 같은 테이블이 채워지는가 (기업 1개로 각각 실행 후 대조) |
| P5-3 | 원문 대조 | 표본 기업의 DB 값을 DART 원문과 직접 비교 (집계로 끝내지 말 것) |
| P5-4 | Gate B 무영향 | `scripts/gateb_audit.py` — fail_a 0 · value_diff 0 |
| P5-5 | 아카이브 기업 | 재적재 로그에 명시적 스킵이 찍히고 기존 행이 보존되는가 |
| P5-6 | **launchd 실행** | `launchctl kickstart -p gui/$(id -u)/com.tjfinance.collect` → `last exit code = 0` |

> **P5-6 을 건너뛰지 말 것.** 터미널 실행은 TCC 권한을 상속받아 항상 성공한다.
> 2026-07-31 에 정확히 이것 때문에 NAS 접근 차단을 못 잡고 21일을 날렸다
> (계획서 §3.3). 스케줄 잡의 동작은 **반드시 launchd 로** 확인한다.

---

## 7. 되돌리기

문제가 생기면 plist 에 `--download-only` 를 다시 넣고 재등록하면 된다.
다운로드는 계속되므로 원문은 계속 쌓이고, 파싱만 다시 멈춘다.
