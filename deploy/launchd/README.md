# 신규 공시 자동 수집 (launchd, 매일 18:00 + 잠자기 깨우기)

`scripts/collect_new.py`(⓪유니버스 갱신→탐지→동기화→다운로드→파싱·표준화)를 매일 18:00
자동 실행한다. 맥북이 잠자기여도 `pmset` 예약 wake(17:58)로 깨운 뒤 launchd 가 18:00 에 실행한다.

## 설치 (최초 1회)

```bash
# 1) plist 배치 (이미 복사돼 있으면 생략)
cp deploy/launchd/com.tjfinance.collect.plist ~/Library/LaunchAgents/
mkdir -p logs

# 2) launchd 등록 (사용자 세션)
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.collect.plist

# 3) 잠자기에서 17:58 깨우기 (sudo 필요, 매일)
sudo pmset repeat wakeorpoweron MTWRFSU 17:58:00
```

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

## 이후 자동 갱신
`scripts/collect_new.py` 가 매 실행 끝(⑥)에 `REFRESH MATERIALIZED VIEW CONCURRENTLY` 로 갱신하므로
18:00 수집 잡에 자동으로 포함된다(비치명적 — 실패해도 수집 자체는 성공 처리). 수동으로 다시 갱신하려면:
```bash
python scripts/refresh_valuation_daily.py --concurrent
```
