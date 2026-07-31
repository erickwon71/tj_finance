# 전문서비스 갭 채우기 Phase 2·3·4 전수 백필 (launchd, 매일 00:01, 완료 시 자기 등록해제)

`scripts/nightly_gap_fill_backfill.py` 가 Phase 2(주주환원 API 6종, PRD 13)·Phase 3(부문·수출입
매출, PRD 14)·Phase 4(비용성격 D&A, PRD 15) 전수 백필을 매일 밤 이어서 진행한다. **일회성 백필
잡** — 셋 다 완료되면 스스로 `launchctl unload` + 이 plist 를 삭제해 더 이상 등록/실행되지 않는다.

- Phase 2: DART 서버 쿼터(하루 4만콜, 계정 공유) 제한이라 하루에 다 못 끝나면 자연스럽게
  다음날 이어감(API 별 `--skip-existing`). 시작연도 2015(각 API 의 실제 데이터 보유 최초년도,
  2010~2012 는 DART 자체에 없음 — 실측 확인됨) ~ 실행 시점의 최신연도.
- Phase 3·4: 로컬 파일 파싱(DART 쿼터 무관), 대상 소진까지 한 번에 진행(수시간 걸릴 수 있음).
  Phase 3 의 "매출표 없는 기업" 완료판정은 `~/.tj_finance/gap_fill_phase3_state.json` 로컬
  상태파일로 자체 추적(DB 만으로는 시도이력 구분 불가).

## 설치 (완료 — 2026-07-13 등록됨)

```bash
cp deploy/launchd/com.tjfinance.gapfill.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.gapfill.plist
launchctl start com.tjfinance.gapfill        # 즉시 1회 실행(테스트/최초구동)
```

## 진행 확인

```bash
launchctl list | grep tjfinance.gapfill      # 등록 여부(제거되면 결과 없음=완료 의미)
tail -f logs/gap_fill.out.log logs/gap_fill.err.log   # 진행 로그(loguru 는 기본 stderr)
```

각 Phase 잔여량은 로그의 `[gapfill] ==== 요약 ====` 줄에서 확인(모두 0 이면 다음 줄에서 자동
등록해제 로그가 남고 이후 `launchctl list` 에 더 이상 나타나지 않는다).

## 수동 실행 / 재등록

```bash
python scripts/nightly_gap_fill_backfill.py    # 즉시 1회 수동 실행(포그라운드, 장시간 주의)
```

이미 완료·자기해제된 뒤 다시 필요해지면(예: 신규 상장기업 백필) 설치 단계를 반복하면 된다.

## 참고
- **NAS(`raw_report`) 마운트 필요**: Phase 3·4 는 로컬 보고서 XML 을 읽으므로 `raw_report`
  심링크가 가리키는 볼륨이 마운트돼 있어야 한다(2026-07-13 등록 당시 NAS(tj_finance_data)가
  마운트 안 돼 있어 `dart_data` 폴백으로 임시 전환 — `nas-migration-plan` 메모리 참고).
  NAS 정상화 후 원복하려면 `ln -sfn /Volumes/tj_finance_data/raw_report raw_report`.
- Phase 2 서버 쿼터 소진(status='020' 연속 5회)은 각 API 호출이 수초 내 자연 종료되므로,
  6개 API 를 매일 순차 시도해도 낭비가 적다(quota 소진 후엔 각 API 확인에 몇 초씩만 소모).
- 등록해제 후 재발 방지: 이 잡은 **일회성**이라 완료되면 다시 등록되지 않는다. 이후 신규
  상장기업 분은 `scripts/collect_new.py`(매일 18:00 정기수집)의 ⑤-1/⑤-3 단계가 자동 커버.

---

# 신규 공시 자동 수집 (launchd, 매일 18:00 + 잠자기 깨우기)

`scripts/collect_new.py`(⓪유니버스 갱신→탐지→동기화→다운로드→파싱·표준화)를 매일 18:00
자동 실행한다. 맥북이 잠자기여도 `pmset` 예약 wake(17:58)로 깨운 뒤 launchd 가 18:00 에 실행한다.

## 설치 (최초 1회)

```bash
# 1) plist 배치
cp deploy/launchd/com.tjfinance.collect.plist ~/Library/LaunchAgents/
mkdir -p logs

# 2) ★ disabled 해제 — 이거 없으면 3)이 'Input/output error' 로 실패한다
launchctl enable gui/$(id -u)/com.tjfinance.collect

# 3) launchd 등록 (사용자 세션)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tjfinance.collect.plist

# 4) 확인 — 레이블이 보여야 한다
launchctl list | grep tjfinance

# 5) 잠자기에서 17:58 깨우기 (sudo 필요, 매일)
sudo pmset repeat wakeorpoweron MTWRFSU 17:58:00
```

### ⚠ `Bootstrap failed: 5: Input/output error` 가 나면

2026-07-31 설치 때 실제로 겪은 것이고, 원인이 메시지에 전혀 안 드러난다. 순서대로 확인:

1. **disabled 상태로 남아 있는가** ← 이번 원인
   ```bash
   launchctl print-disabled gui/$(id -u) | grep tjfinance
   ```
   한 번 `bootout`/삭제한 레이블은 **disabled 로 남는다**. 2026-07-22 에 야간 잡을
   전량 삭제한 뒤 `com.tjfinance.collect` 와 `gapfill` 이 그 상태였다.
   `launchctl enable gui/$(id -u)/<레이블>` 로 해제해야 등록된다.

2. **DOCTYPE 이 있는가**
   `plutil -lint` 는 DOCTYPE 없이도 OK 를 내지만 launchd 는 거부한다.
   ```xml
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   ```

3. 같은 레이블이 이미 부트스트랩돼 있는가 — `launchctl bootout gui/$(id -u)/<레이블>` 후 재시도

> 진단 팁: 최소 plist(Label + ProgramArguments 만)로 같은 레이블을 등록해 보면
> **plist 내용 문제인지 레이블 상태 문제인지** 바로 갈린다.

## 확인 / 운영

```bash
launchctl list | grep tjfinance              # 등록 확인
pmset -g sched                               # 예약 wake 확인
launchctl start com.tjfinance.collect        # 지금 즉시 1회 실행(테스트)
tail -f logs/collect.out.log                 # 진행 로그
```

## 변경 반영 (plist 수정 후 재적용)

plist 를 수정하면 이미 등록된 것을 내렸다가 새 파일로 다시 올려야 반영된다.

```bash
launchctl unload -w ~/Library/LaunchAgents/com.tjfinance.collect.plist
cp deploy/launchd/com.tjfinance.collect.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.collect.plist
```

## 해제

```bash
launchctl unload -w ~/Library/LaunchAgents/com.tjfinance.collect.plist
sudo pmset repeat cancel                      # 예약 wake 해제
```

## 참고
- 잠자기(sleep)에서는 wake 후 실행됨. **완전 종료(shutdown)** 상태는 기종(Apple Silicon)에 따라
  power-on 이 안 될 수 있음 — 그 경우 다음 부팅/wake 시 누락분이 실행됨(StartCalendarInterval).
- `--days 3`: 하루 걸러도 겹치는 창이라 누락 방지(멱등).
- `--refresh-universe`: 수집 전 KRX 상장 목록으로 **신규 상장 반영·상장폐지 비활성화**(⓪ 단계).
  네트워크(KRX/DART) 조회라 실패해도 수집은 계속(비치명적). 로그에 신규/제외 기업명 기록.
- `--timeout 600`: 기업당 파싱·표준화 상한(초). 대형 보고서(≈120초 경계)도 완주하도록 600.
  초과 기업은 워커 kill 후 스킵·다음 기업 진행(전체는 안 막힘). 스킵분은 나중에
  `collect_new.py --standardize-only --timeout 600 --corps <corp_code,...>` 로 채울 수 있음.
- **수집 후 DQ 게이트(I2)**: `collect_new.py` 는 표준화 성공 기업에 Gate B(보고서==DB)+항등식을 재검하고
  `corp_verify_status` 를 갱신한다(기본 on). 확정 불일치(fail_a/value_diff)는 `logs/collect.err.log` 에
  ERROR 로 남는다. 끄려면 `--no-verify`.
- DART 키는 `.env`(OPENDART_API_KEY)에서 자동 로드(절대경로).

---

# DB 백업 (launchd, 매일 19:00) — D1

`scripts/backup_db.py` 가 매일 19:00 `pg_dump`(custom format)로 **소비계층 논리 백업**을 NAS(RAID1)
`/Volumes/tj_finance_data/db_backups` 에 저장한다. 재생성 가능한 `fact_v2` 데이터(≈86GB)는 제외(스키마 보존)
하므로 백업이 작고(≈수백 MB) 빠르다. 라이브 DB(Mac 내장)와 덤프(NAS)가 독립 장애 도메인 → SPOF 해소.
NAS 미마운트 시 백업은 실패+알림(마운트 가드). 18:00 수집이 깨운 창(17:58 wake)을 재사용한다.

## 설치
```bash
cp deploy/launchd/com.tjfinance.backup.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.backup.plist
launchctl start com.tjfinance.backup        # 즉시 1회 테스트
tail -f logs/backup.out.log
```

## 복원
```bash
pg_restore -d tj_finance --clean --if-exists /Volumes/tj_finance_data/db_backups/<파일>.dump
# fact_v2 재적재가 필요하면 raw_report 로 재추출: python run.py fin2-all
```

## 참고
- 외장 볼륨(`/Volumes/dart_data`)이 마운트돼 있어야 함(미마운트 시 백업은 에러로 중단 — 내장 디스크로
  백업하면 디스크 사고 대비 의미가 없으므로 의도적).
- `--keep 7`: 최근 7개 유지(회전). `--full`: fact_v2 데이터까지 포함(대용량·느림, 평시 불필요).
- 더 강한 PITR 이 필요하면 `postgresql.conf` 에 `archive_mode=on` + `archive_command` 로 WAL 아카이빙을
  추가(선택). 개인용 단일 노드에는 야간 논리 백업으로 충분.

---

# 분기별 백업 복원 드릴 (launchd, 1/4/7/10월 1일 19:30) — C4

`scripts/restore_drill.py --drop-after` 가 그날 19:00 백업 덤프를 scratch DB(`tj_finance_restore_test`)에
복원하고 실 DB와 행수를 대조한다. 19:00 백업 직후·20:30 dqcheck 이전에 배치해, 그 사이 쓰기로 인한
시점차 오탐(가짜 MISMATCH)을 최소화했다. 상세: `docs/runbook_backup_restore.md`.

## 설치
```bash
cp deploy/launchd/com.tjfinance.restoredrill.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.restoredrill.plist
launchctl start com.tjfinance.restoredrill        # 즉시 1회 테스트
tail -f logs/restoredrill.out.log
```

---

# 야간 데이터 품질 점검 (launchd, 매일 20:30) — I3 + I1

`scripts/dq_nightly.py` = **I3 SQL 어서션**(참조무결성: 미래 period_end·달력 orphan·자산총계<=0·op==ni 등)
+ **I1 DART 교차검증**(날짜 시드 순환 표본 25사). 18:00 수집·19:00 백업 뒤 실행. 어서션 ERROR 위반 시
종료코드 1(로그로 확인). 교차검증 불일치는 정정노이즈·합성 포함이라 게이트 제외(참고).

## 설치
```bash
cp deploy/launchd/com.tjfinance.dqcheck.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.dqcheck.plist
launchctl start com.tjfinance.dqcheck        # 즉시 1회 테스트
tail -f logs/dqcheck.out.log
```

## 수동 실행
```bash
python scripts/dq_assertions.py --sample      # 어서션만(위반 표본까지)
python scripts/dq_nightly.py --xsrc-sample 0  # 어서션만(교차검증 생략)
python scripts/verify_cross_source.py --sample 50 --years 2018-2024   # 교차검증 깊게
```

---

# 주간 VACUUM(ANALYZE) (launchd, 매주 일요일 22:00) — D5 / A4b

`scripts/vacuum_db.py` 가 DB 전체(기본) 또는 지정 테이블에 `vacuumdb --analyze` 를 실행한다.
전문가 리뷰 §5: `fact_v2`(87M행)가 dead tuple ~15%인데 수동 VACUUM 이력이 전무했던 문제의 정례 대응.
`collector/db.py` 마이그레이션(`2026_07_fact_v2_autovacuum_tuning`)이 `fact_v2` 의 autovacuum 임계값도
낮춰 자동 청소 빈도를 높였다 — 이 주간 잡은 그 보완(+ 대량 수집 뒤 플래너 통계 갱신).
18:00 수집·19:00 백업·20:30 DQ점검 뒤(리소스 경합 회피) 일요일 22:00 로 배치.

## 설치
```bash
cp deploy/launchd/com.tjfinance.vacuum.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.vacuum.plist
launchctl start com.tjfinance.vacuum        # 즉시 1회 테스트
tail -f logs/vacuum.out.log
```

## 수동 실행
```bash
python scripts/vacuum_db.py                  # 전체 DB
python scripts/vacuum_db.py --table fact_v2  # 특정 테이블만
```

---

# valuation_daily matview 갱신 — A4a (D3)

재무↔주가 결합 밸류에이션 뷰(`app/data/valuation_bands.py` 가 소비)는 11.2M 주가행마다 LATERAL로
최신 FY 재무를 조인하는 일반 뷰였던 것을 **materialized view** 로 전환했다(전문가 리뷰 §4).
`collector/db.py` 마이그레이션이 `WITH NO DATA` 로 뷰만 만들어두므로, **최초 1회 수동 적재가 필요**하다.

## 최초 적재 (1회, 사용자 실행 — 수 분 소요 가능)
```bash
python scripts/refresh_valuation_daily.py
```

## 이후 자동 갱신 — 전용 잡 `com.tjfinance.valuation` (매일 19:30)

★ **2026-07-16 변경(외부평가 P0-1)**: refresh 를 collect 잡에서 **분리**했다. 예전엔 refresh 가
`collect_new.py` 마지막 단계(⑥)에만 매달려 있어서, collect 이 단계 ①에서 DART 쿼터초과([020])로
크래시하면(gapfill 잡이 쿼터 선소진) matview 가 며칠~몇주씩 정체됐다. 이제 DART 와 무관한
독립 잡이 갱신을 보장한다:

```
scripts/nightly_valuation_refresh.py
  ① 주가 증분 top-up (pykrx, 최근 15일)  → stock_prices
  ② 시가총액·shares_out 재계산 (순수 SQL) → market_cap
  ③ REFRESH MATERIALIZED VIEW CONCURRENTLY valuation_daily
```
각 단계는 격리되어 하나가 실패해도 나머지는 이미 신선한 데이터 위에서 계속 진행한다.

### 설치
```bash
cp deploy/launchd/com.tjfinance.valuation.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.valuation.plist
launchctl start com.tjfinance.valuation      # 즉시 1회 실행(테스트)
```

### 수동 실행
```bash
python scripts/nightly_valuation_refresh.py                # 전수(주가 15일 + 시총 + refresh)
python scripts/nightly_valuation_refresh.py --skip-prices  # 시총+refresh 만(초고속)
```

### 최신성 모니터링
`scripts/dq_assertions.py` 의 `valuation_daily_stale` 어서션(ERROR)이 최신 거래일 6일 이상 지연을
잡고, `com.tjfinance.dqcheck` 야간 잡이 위반 시 `notify.py` 로 알림한다.

> 참고: `collect_new.py`(18:00)도 여전히 끝에서 refresh 를 시도하지만(비치명적 redundant), 신뢰
> 경로는 이 전용 잡이다. collect 이 DART 로 죽어도 밸류에이션은 정상 갱신된다.
