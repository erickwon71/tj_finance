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

`scripts/backup_db.py` 가 매일 19:00 `pg_dump`(custom format)로 **소비계층 논리 백업**을 외장 볼륨
`/Volumes/dart_data/db_backups` 에 저장한다. 재생성 가능한 `fact_v2` 데이터(≈86GB)는 제외(스키마 보존)
하므로 백업이 작고(≈수백 MB) 빠르다. 18:00 수집이 깨운 창(17:58 wake)을 재사용한다.

## 설치
```bash
cp deploy/launchd/com.tjfinance.backup.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.tjfinance.backup.plist
launchctl start com.tjfinance.backup        # 즉시 1회 테스트
tail -f logs/backup.out.log
```

## 복원
```bash
pg_restore -d tj_finance --clean --if-exists /Volumes/dart_data/db_backups/<파일>.dump
# fact_v2 재적재가 필요하면 raw_report 로 재추출: python run.py fin2-all
```

## 참고
- 외장 볼륨(`/Volumes/dart_data`)이 마운트돼 있어야 함(미마운트 시 백업은 에러로 중단 — 내장 디스크로
  백업하면 디스크 사고 대비 의미가 없으므로 의도적).
- `--keep 7`: 최근 7개 유지(회전). `--full`: fact_v2 데이터까지 포함(대용량·느림, 평시 불필요).
- 더 강한 PITR 이 필요하면 `postgresql.conf` 에 `archive_mode=on` + `archive_command` 로 WAL 아카이빙을
  추가(선택). 개인용 단일 노드에는 야간 논리 백업으로 충분.

---

# 무결성 SQL 어서션 (I3, 선택 스케줄)

`scripts/dq_assertions.py` 는 참조무결성/정합성 어서션(미래 period_end·달력 orphan·자산총계<=0 등)을
점검하고 ERROR 위반 시 종료코드 1 을 낸다. 수동 또는 별도 launchd 로 야간 실행할 수 있다.
```bash
python scripts/dq_assertions.py --sample     # 위반 표본까지
```
