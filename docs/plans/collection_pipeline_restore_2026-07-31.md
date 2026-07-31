# 수집 파이프라인 복구·강화 계획 (2026-07-31)

> 상태: **계획 — 미실행**. 검토 후 별도 실행 요청을 받아 착수한다.
> 선행 감사: 본 문서 §1 (2026-07-31 읽기 전용 실측)

---

## 0. 확정된 결정 (사용자, 2026-07-31)

| # | 항목 | 결정 |
|---|---|---|
| D1 | 상장폐지 확정 기업 원문 | **NAS 아카이브 영구 보존**. 삭제하지 않음. SD카드는 용량 문제로 미러링 대상에서 **제외** |
| D2 | 상장폐지 DB 반영 | **소프트** — 종속 데이터 전량 보존, 상태 컬럼으로 조회 제외. 되돌리기는 UPDATE 1줄 |
| D3 | NAS→SD 동기화 | **다운로드 후 rsync 단계**. downloader 이중 기록 아님 |
| D3' | 미러의 `--delete` | **데일리에서 제거 — 덧붙이기(`rsync -a`) 전용.** 지우기는 수동·별건(§5.3.1·§6.4b). 근거: 상장폐지 10사 = 857MB(SD 여유의 0.6%)로 얻는 것이 없는데 유일한 치명적 연산 |
| D5 | SD 부분 미러링(최근 N년만) | **보류 — 별도 결정 필요.** SD 용량의 진짜 지렛대이나 이번 범위 밖(§10) |
| D6 | 주 저장소 재검토 (실행 중 제기) | **NAS 주 유지.** 지연은 46배지만 대역폭은 2배뿐이고, SD 는 제거가능 소비자 SD카드(여유 128Gi·약 4년치). 데일리 영향 1.6초 · Phase 5 재파싱만 +46분 |
| D7 | 상장 유니버스 소스 | **KRX OpenAPI 1차 + FDR 2차 상호보완**(§12). 시장별 독립 판정 |
| D8 | 미러 방식 | **증분 기본**(`--files-from`, 4초) + 주기적 `--full`(40분). 전 트리 stat 이 SMB 에서 40분이라 데일리로 부적합(§5.3.3) |
| D4 | 데일리 범위 | 이번엔 **다운로드까지만**. 파싱·표준화·계층2/3 적재는 계층3 재설계 완료 후 재편입(§6) |

---

## 1. 현황 실측 요약

2026-07-31 읽기 전용 감사 결과.

| 확인 항목 | 상태 | 근거 |
|---|---|---|
| 정기보고서 수집 | ❌ **2026-07-10 이후 중단(21일)** | `max(download_tasks.completed_at)` |
| 마지막 파이프라인 실행 | 2026-07-17 18:00, **0/13 성공** | `logs/collect.err.log` |
| 미수집 잔량 (07-11~07-31) | **37건** | `scripts/qa/audit_download_gap.py` |
| 정정보고서 로직 | ✅ 정상 (미탐지는 스케줄러 부재 탓) | 정정 22,889 · 대체 24,249행 |
| `raw_report` 심링크 | ❌ **SD카드를 가리킴** (NAS는 마운트돼 있음) | 드리프트 4회차 |
| NAS↔SD 실파일 일치 | ✅ 현재 90/90 일치 (수동 동기화 결과) | 90사 트리 대조 |
| 동기화 자동화 | ❌ 코드 전무 | `rsync` 참조 0건 |
| 상장폐지 DB 반영 | ✅ `is_active=False` 작동 | 비활성 10개 |
| 상장폐지 파일 정리 | ❌ 미구현 | 10개사 트리 전량 잔존 |

### 1.1 근본 원인 2개

1. **스케줄러 부재** — 야간 launchd 잡이 2026-07-22 전량 삭제된 상태(계층3 작업용). `launchctl list | grep tj` 결과 0건. 07-18 이후로는 실행 자체가 없었다.
2. **저장소 계약 미검증** — 07-17 실행은 살아 있었으나 `raw_report` 심링크가 가리키는 볼륨에 접근이 안 돼 `[Errno 1] Operation not permitted` 로 다운로드 13/13 실패, 기존 파일 **읽기**까지 실패했다. 파이프라인은 이를 "비치명적"으로 넘기고 성공 로그를 남겼다.

### 1.2 증폭 요인

`com.tjfinance.collect.plist` 의 `--days 3`. 조회 창이 실행일 기준 고정 3일이라, **3일 넘는 장애는 그 사이 공시를 영구 누락**시킨다. 자가 복구가 없다.

### 1.3 심링크 추상화는 정상이다 — 문제는 읽기가 아니라 쓰기다

`download_tasks.file_path` **188,177건 전부**가 심링크 경로(`/Users/taejin/Project/tj_finance/raw_report/...`)로 저장돼 있다.

**이건 좋은 설계다.** 코드는 `RAW_REPORT_DIR` 하나만 보고, 두 볼륨 내용이 같은 한 어느 쪽을 가리키든 읽는 값이 동일하다. 심링크만 NAS로 되돌리면 기존 경로 18만 건이 전부 NAS로 해석되므로 **DB 마이그레이션도 0건**이다.

따라서 "드리프트 때문에 읽는 데이터가 달라진다"는 우려는 **사실이 아니다.**

#### 실제 위험: 쓰기 대상과 미러 목적지가 같은 볼륨이 되는 것

> **읽는 순서 주의**: 아래 시나리오는 미러에 `--delete` 가 있을 때의 이야기다.
> 결정 **D3'**(§5.3.1)로 데일리 미러가 덧붙이기 전용이 되어 **이 손실 경로는 해소됐다.**
> 그럼에도 여기 남겨두는 이유는, 이것이 G2(I1) 어서션과 S2b 역방향 정산이 왜 필요한지의 근거이고,
> §6.4b 수동 삭제에서 같은 함정이 되살아나기 때문이다.

원안(`--delete` 포함)에서 심링크가 SD를 가리키는 상태(= 2026-07-31 현재)로 데일리를 돌리면:

```
③ 다운로드     현대약품 반기보고서 → raw_report/ → 실제로는 SD 에 기록
               download_tasks: status='completed', file_path 기록
⑥ rsync -a --delete  NAS/raw_report/ → SD/raw_report/
               NAS 에는 그 파일이 없음
               → --delete 가 방금 받은 파일을 삭제
```

파일은 사라졌는데 DB 는 `completed` 다. 그리고 `run_downloads` 의 큐 조건은
`status IN ('pending','failed')` (`collector/downloader.py:255`) 이므로 **재다운로드가 영원히 일어나지 않는다.**
Gate A(`validate_downloads.py`)가 `MISSING_FILE` 로 잡을 수 있지만 데일리 흐름에 배선돼 있지 않다.

→ **파이프라인은 성공을 보고하고 데이터만 없어진다.** 계층2 DART XML 이스케이프 결함과 같은 유형의 조용한 손실이다.

#### 결론: 지켜야 할 것은 불변식 하나

```
raw_report 가 가리키는 볼륨  ==  rsync 의 소스 볼륨
```

"NAS 가 특별하다"가 아니라 이것이다. 심링크를 NAS 로 **고정**하고(§1.4 의 비대칭 때문), 가드는 매 실행 이 불변식을 검사한다.

### 1.4 두 볼륨이 대칭이 아닌 이유 (심링크를 NAS 로 고정하는 근거)

읽는 내용이 같더라도 매체 자체가 다르다.

| | NAS (`tj_finance_data`) | SD카드 (`dart_data`) |
|---|---|---|
| 여유 용량 | 1.2Ti (271Gi/1.5Ti, **19%**) | **148Gi (330Gi/477Gi, 70%)** — 원문이 218G |
| 이중화 | RAID1 | 단일 소비자 플래시 |
| 아카이브 위치 | `archive/delisted/` 가 같은 볼륨 → 이관이 `mv`(즉시) | 크로스 볼륨 복사(SMB 경유, 느림) |

SD 가 쓰기 대상이 되면 용량이 먼저 차고, 원본이 이중화 없는 매체에 쌓인다.

> **검토된 대안**: 미러 방향을 심링크에서 자동 유도(가리키는 쪽이 소스, 반대쪽이 미러)하면 드리프트가 나도 불변식이 자동으로 지켜진다. 기술적으로 가능하나 위 비대칭 3가지가 그대로 남아 **채택하지 않는다**(사용자 결정, 2026-07-31). 심링크는 NAS 고정, 가드는 불변식 검사.

---

## 2. 범위

**이번 범위**: 유니버스 갱신 · 공시 탐지 · 다운로드 · 저장소 계약 · NAS→SD 미러 · 상장폐지 판정/아카이브/DB 반영 · 수집 완전성 감사

**이번 범위 아님** (Phase 5 로 이월): 파싱 · 표준화 · 계층2 전사 · 계층3 조합 · DQ 게이트 · valuation 갱신

---

## 3. Phase 1 — 저장소 계약 확정 (P0, 선행 필수)

### 3.0 이 단계가 지키는 불변식

```
I1  raw_report 심링크가 가리키는 볼륨  ==  rsync 미러의 소스 볼륨  ==  PRIMARY(NAS)
I2  PRIMARY / BACKUP 이 각각 "진짜 그 볼륨"이다        (빈 마운트포인트가 아니다)
I3  PRIMARY 는 지금 읽고 쓸 수 있다                    (스테일 마운트가 아니다)
```

- **I1** 이 깨지면 다운로드가 SD 로 가고 NAS(RAID1·primary)에 원본이 안 쌓인다. 덧붙이기 미러(D3')로 파일이 삭제되지는 않지만, **이중화 없는 매체에만 존재하는 원본**이 생긴다.
- **I2** 가 깨지면 빈 마운트포인트를 볼륨으로 오인한다. 덧붙이기 미러에서는 무해하지만 §6.4b 수동 삭제에서는 치명적이다.
- **I3** 이 07-17 장애다.

**이걸 먼저 하지 않으면 이후 모든 단계가 SD카드에 쓴다.**

### 3.1 신규 모듈 `collector/storage_guard.py`

```
PRIMARY_ROOT = /Volumes/tj_finance_data/raw_report     # NAS(RAID1) — 기본·쓰기 대상·미러 소스
BACKUP_ROOT  = /Volumes/dart_data/raw_report           # SD카드 — 미러 목적지
ARCHIVE_ROOT = /Volumes/tj_finance_data/archive/delisted
SYMLINK      = <repo>/raw_report
```

`assert_storage(require_backup: bool = False)` 가 순서대로 검사하고, 하나라도 실패하면 `StorageContractError` 를 올려 **파이프라인을 즉시 중단**한다.

경고 후 진행은 금지한다 — 07-17 실행이 정확히 그렇게 해서 다운로드 13/13 실패를 "비치명적"으로 넘기고 성공 로그를 남겼다.

| # | 불변식 | 검사 | 막아내는 사고 |
|---|---|---|---|
| G1 | I2 | PRIMARY 루트에 sentinel `.tj_volume_id` 존재 · 내용 `nas-primary` | NAS 미마운트 시 `/Volumes/tj_finance_data` 가 **빈 디렉터리로 존재**하는 것을 정상으로 오인. §6.4b 수동 삭제에서 SD 백업 전멸로 이어진다 |
| G2 | **I1** | `SYMLINK.resolve() == PRIMARY_ROOT` | **심링크 드리프트(4회차).** 원본이 RAID1 없는 SD 에만 쌓이는 것. 원안(`--delete`)에서는 당일 수신분 삭제까지 갔다(§1.3) |
| G3 | I3 | PRIMARY 쓰기 프로브 (임시파일 생성→삭제) | 07-17 의 EPERM 을 다운로드 시작 **전에** 잡아냄 |
| G4 | I3 | PRIMARY 읽기 프로브 (기존 파일 1건 stat+read) | 스테일 SMB 마운트 |
| G5 | I2 | `require_backup` 일 때: BACKUP sentinel `sd-backup` + 쓰기 가능 | 미마운트 백업에 rsync |

**G2 와 G1 이 서로 다른 사고를 막는다는 점이 중요하다.**
G2 는 *쓰기가 엉뚱한 볼륨으로 가는 것*을, G1 은 *소스가 비어 있는 채로 미러가 도는 것*을 막는다. 하나만으로는 부족하다.

### 3.2 작업 목록

| ID | 작업 | 산출물 |
|---|---|---|
| S1 | 각 볼륨 루트에 sentinel 생성 | `.tj_volume_id` × 2 |
| S2 | `storage_guard.py` 작성 + 단위 테스트 | 신규 모듈, `tests/test_storage_guard.py` |
| **S2b** | **SD → NAS 역방향 정산 (아래 ⚠️ 필수)** | `scripts/qa/verify_storage_mirror.py --full` 리포트 |
| S3 | 심링크 NAS 로 원복 | `ln -sfn /Volumes/tj_finance_data/raw_report raw_report` |
| S4 | 원복 후 무결성 확인 — 기존 파일 표본 200건 읽기 | 검증 로그 |
| S5 | `config.py` 에 PRIMARY/BACKUP/ARCHIVE 상수 노출 | `collector/config.py` |

> ⚠️ S3 는 **S1·S2 완료 후**에 한다. 어서션 없이 원복만 하면 5회차 드리프트가 또 조용히 일어난다.

#### ⚠️ S2b 를 건너뛰면 NAS 가 불완전한 채로 primary 가 된다

드리프트 기간 동안 다운로드된 파일은 **SD 에만 있고 NAS 에는 없을 수 있다.** 이 상태로 심링크만 NAS 로 돌리면:

- 덧붙이기 미러(D3')는 NAS→SD 단방향이라 **그 파일들을 NAS 로 끌어오지 않는다.** 영구히 SD 에만 남는다
- 즉 **primary(RAID1)에 구멍이 있는 채로** 운영이 시작되고, 이후 아무 단계도 이를 알려주지 않는다
- SD 카드가 죽으면 그 구멍만큼이 그대로 소실된다

> 참고: 원안(`--delete` 포함)에서는 첫 미러가 그 파일들을 **삭제**했다. D3' 로 삭제는 없어졌지만
> **NAS 결손은 그대로 남으므로 S2b 는 여전히 필수다.**

따라서 **첫 미러 전에 반드시 역방향으로 한 번 정산한다:**

1. 전수 대조 — SD 에만 있는 실파일 목록 산출 (`._*`·`.DS_Store` 제외)
   - SMB 전수 순회는 느리다(오늘 측정: SD 30초 / NAS 는 10분+ 미완). **사용자 실행 구간**으로 잡는다
2. 있으면 **SD → NAS 단방향 복사**(`rsync -a --ignore-existing SD/ → NAS/`, `--delete` 없음)
3. 재대조하여 **SD 에만 있는 실파일 0건** 확인
4. 그 다음에 S3(심링크 원복) → 첫 정방향 미러

> 오늘 표본(90사)에서는 실파일 불일치 0 이었지만, **표본은 전수의 증거가 아니다.** 전수 대조를 하고 넘어간다.

### 3.3 ★드리프트 근본 원인 규명됨 — macOS TCC (2026-07-31)

> 초안에서는 "원인 미규명, 어서션은 탐지일 뿐"으로 남겨뒀다. **실행 중 규명됐다.**

**드리프트는 사고가 아니라 우회책이었다.**

`macOS TCC(개인정보 보호)가 launchd 프로세스의 네트워크 볼륨 접근을 차단`한다. 동일 스크립트를
컨텍스트만 바꿔 돌린 실측:

| 대상 | 터미널(수동) | **launchd** |
|---|---|---|
| NAS `/Volumes/tj_finance_data` (SMB) | listdir OK | **EPERM (errno 1)** |
| SD `/Volumes/dart_data` (외장 HFS+) | OK | OK |
| 내장 디스크 | OK | OK |

`stat` 은 성공하고 `listdir`/`read` 만 EPERM 인 것이 TCC 시그니처다. LaunchAgent 는 권한 팝업을
띄울 수 없어 그냥 거부당한다.

**이것이 설명하는 것**

| 현상 | 설명 |
|---|---|
| 2026-07-17 다운로드 13/13 실패 | launchd 잡이 NAS 를 못 읽음 |
| 수동 실행은 언제나 성공 | 터미널이 TCC 권한을 상속 |
| 심링크가 4회(7/7·7/11·7/26·7/31) SD 로 "드리프트" | 스케줄 잡이 NAS 에서 안 되니 SD 로 되돌린 것. **SD 를 가리키는 상태가 유일하게 작동하던 구성** |

§1.1 에서 07-17 장애를 "스테일 SMB 마운트"로 추정한 것은 **오진이다.**

**해결(적용 완료)**: `python3.9` 실체 경로를 시스템 설정 → 개인정보 보호 및 보안 →
**전체 디스크 접근 권한**에 추가.
```
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9
```
`.venv/bin/python` 은 심링크라 실체 경로를 넣어야 한다. Finder 가 `/Library/Developer` 를 숨기므로
`+` 버튼만으로는 못 찾고 **⇧⌘G(폴더로 이동)** 를 써야 한다.

**교훈 — 이 부류 결함은 수동 검증으로 절대 안 잡힌다.**
터미널 실행은 항상 성공하므로, 스케줄 잡의 동작은 **반드시 launchd 로 한 번 돌려서** 확인해야 한다.
최소 plist(Label + ProgramArguments)로 kickstart 하고 stdout 을 파일로 받으면 된다.

> 초안에서 근본 해결책으로 검토했던 ①심링크 어서션 ②dart_data 은퇴 는 **둘 다 이 원인을 못 고친다.**
> 어서션은 탐지만 하고, dart_data 를 은퇴하면 스케줄 잡이 아예 못 돈다.
> 그럼에도 어서션(G2)은 유지한다 — TCC 권한이 다시 풀리거나 다른 이유로 드리프트하면
> **데이터가 깨지기 전에** 멈춰야 하기 때문이다(실제로 07-31 실행에서 그렇게 막았다).

---

## 4. Phase 2 — 밀린 분 백필

Phase 1 완료가 전제.

| ID | 작업 | 대상 | 비고 |
|---|---|---|---|
| B1 | 실패 13건 재시도 | `download_tasks.status='failed'` → `pending` 리셋 후 `run_downloads` | 07-17 EPERM 잔재 |
| B2 | 미탐지 24건 수집 | `--days 25` 로 재탐지 → `sync_filings(force)` → 다운로드 | 전부 정정보고서 |
| B3 | 신규상장 6사 전기간 수집 | 스트라드비젼·세미티에스·피스피스스튜디오·매드업·레몬헬스케어·레메디 | 상장 이후 전 정기보고서 |
| B4 | 인프라펀드 3사 처리 | 맥쿼리인프라·KB발해인프라·맵스리얼티 | `CORP_EXCLUDE_KEYWORDS` 보강 → 유니버스 제외 |
| B5 | 백필 후 완전성 재감사 | `audit_download_gap.py --days 30` 결과 **미탐지 0 · 미다운로드 0** | 합격 기준 |

> B3 는 `--download-only` 라 파싱이 안 붙는다. 이 6사의 재무 데이터는 Phase 5 에서 채워진다. 그 전까지 앱에서 빈 기업으로 보이는 것은 **의도된 상태**이며, `coverage_class` 로 구분 표기한다.

---

## 5. Phase 3 — 데일리 파이프라인 재구성 (다운로드 전용)

### 5.1 `collect_new.py --download-only` 신설

기존 흐름에서 파싱·적재 계열을 전부 스킵하는 모드를 추가한다.

| 단계 | 내용 | `--download-only` |
|---|---|---|
| ⓪ | **`storage_guard.assert_storage(require_backup=True)`** | ✅ 신규·최우선 |
| ①-1 | 시장조치 이벤트 (`_sync_regulatory`) | ✅ 유지 |
| ①-2 | 자본 이벤트 (`_sync_capital`) | ✅ 유지 |
| ②-1 | 유니버스 갱신 (`refresh_universe`) | ✅ 유지 |
| ②-2 | **상장폐지 판정** (§6) | ✅ 신규 |
| ③ | 공시 탐지 (`discover_recent_corps`) | ✅ 유지, 창 계산 변경(5.2) |
| ④ | 공시목록 동기화 (`sync_filings`) | ✅ 유지 |
| ⑤ | 다운로드 (`run_downloads`) | ✅ 유지 |
| ⑥ | **NAS→SD rsync 미러** (§5.3) | ✅ 신규 |
| ⑦ | **수집 완전성 감사** (`audit_download_gap`) | ✅ 신규 |
| ⑧ | 리포트·알림 | ✅ 신규 |
| — | 파싱·표준화 (`_standardize_with_timeout`) | ⛔ 스킵 |
| — | D&A 복원 / 계층2 전사 / DQ 게이트 | ⛔ 스킵 |
| — | biz_metrics / order_backlog / periodic_apis | ⛔ 스킵 |
| — | valuation_daily 갱신 | ⛔ 스킵 (별도 잡 유지) |

> ⛔ 항목들은 **삭제가 아니라 조건 분기**로 둔다. Phase 5 에서 플래그만 내리면 되살아나야 한다.

### 5.2 조회 창 자가복구 — `--days auto`

`--days 3` 고정을 버리고 워터마크 기반으로 바꾼다. **21일 공백을 만든 직접 원인이다.**

```
새 테이블  pipeline_runs(run_id, mode, started_at, finished_at, status, window_bgn, window_end, summary jsonb)

조회 시작일 = max( 마지막 status='success' 실행의 window_end - 3일,  today - 90일 )
```

- 며칠 멈춰 있었어도 다음 실행이 그 구간을 자동으로 다시 훑는다.
- 3일 겹침은 DART 반영 지연 대비. 수집은 `rcept_no` 단위 멱등이라 중복 무해.
- 90일 상한은 이번 같은 장기 중단 시 DART API 쿼터 폭주 방지. 그보다 긴 공백은 수동 백필(Phase 2 방식).

### 5.3 `scripts/sync_storage_mirror.py` (NAS → SD) — **덧붙이기 전용**

#### 5.3.1 왜 `--delete` 를 데일리에서 뺐나 (결정 D3', 2026-07-31)

측정 결과: **상장폐지 10개사 원문 전체가 857MB.** SD 여유는 148GB.

`--delete` 로 회수되는 용량은 여유 대비 **0.6%**, 연간 상장폐지 10~20개사 기준 **1~2GB/년**이다.
SD 용량 압박의 실체는 상장폐지분이 아니라 **활성 기업의 정상 증가분**이다.

`--delete` 는 이 계획에서 유일하게 치명적인 연산인데 사는 것이 거의 없다 → **데일리에서 제거한다.**

| | 덧붙이기 미러 (데일리 자동) | 지우기 동기화 (수동·별건) |
|---|---|---|
| 명령 | `rsync -a` (**`--delete` 없음**) | `rsync -a --delete` |
| 하는 일 | NAS 신규분을 SD 로 복사 | 아카이브 이관분을 SD 에서 제거 |
| 최악의 사고 | 파일이 미러 안 됨 — **복구 가능** | SD 218GB 전멸 / 당일 수신분 삭제 |
| 빈도 | 매일 (안 하면 백업이 낡음) | 연 1~2회로 충분 |
| 위치 | §5.3.2 | §6.4 `delisting_manage.py --sync-backup --apply` |

**부수 효과 — §1.3 손실 시나리오의 소멸.** `--delete` 가 없으면 심링크가 SD 를 가리켜도
"그날 받은 파일이 NAS 에 안 올라감"에 그친다. 파일은 SD 에 그대로 있고 역방향 정산(§3.2 S2b)으로
회수된다. G2(I1) 는 계속 검사하되 **실패가 더 이상 치명적이지 않다.**

#### 5.3.2 데일리 미러

```
rsync -a --exclude '._*' --exclude '.DS_Store' \
      /Volumes/tj_finance_data/raw_report/  /Volumes/dart_data/raw_report/
```

**실행 전 가드:**

| 가드 | 내용 | 이유 |
|---|---|---|
| M1 | `assert_storage(require_backup=True)` 통과 | 미마운트 볼륨(빈 디렉터리)에 쓰지 않기. **rsync 소스는 심링크가 아닌 `PRIMARY_ROOT` 절대경로** |
| M3 | SD 여유 < 20GB 경고, < 5GB 중단 | 현재 SD 70% 사용 |

> M2(파일 수 급감 가드)는 **불필요해져 삭제한다.** 원본이 손상돼도 덧붙이기는 백업을 지우지 못한다.

- `._*` 제외: SD 가 HFS+ 라 macOS 가 AppleDouble 사이드카를 만든다. 감사에서 실제 26건 오탐을 냈으므로 처음부터 제외한다.
- 이력은 `storage_sync_log` 에 기록(전송 건수, 소요, 결과, 성공 시각).

### 5.4 완전성 감사 상시화

`scripts/qa/audit_download_gap.py`(오늘 신설)를 파이프라인 ⑦단계에 붙인다.

- DART `pblntf_ty=A` 목록 대 `filings`/`download_tasks` 대조
- **미탐지 > 0 또는 미다운로드 > 0 이면 `logger.error` + 알림.** 조용히 지나가지 않는다.
- 이게 있었다면 07-17 의 13건 실패가 당일 드러났다.

**추가 검사 — 파일 실재 확인** (§1.3 손실 유형 탐지용):
`status='completed'` 인데 `file_path` 가 실제로 없는 건을 찾는다. 큐 조건이
`pending|failed` 뿐이라 한 번 `completed` 가 되면 파일이 사라져도 재다운로드되지 않기 때문이다.

- 당일 다운로드분은 **전수**, 그 외는 표본 500건
- 유실 발견 시 해당 `download_tasks` 를 `pending` 으로 되돌리고 알림 → 다음 실행에서 자동 복구
- 이것이 §1.3 시나리오가 가드를 뚫었을 때의 **최후 안전망**이다

**추가 검사 — 미러 신선도** (덧붙이기 전용 전환의 대가):
`--delete` 를 뺀 대신 "백업이 조용히 낡는" 리스크가 생긴다. 백업은 잊어도 티가 안 나는 것이 문제다.

- `storage_sync_log` 의 마지막 성공 시각이 **7일 초과면 경고**, **30일 초과면 error + 알림**
- SD 미마운트가 며칠 이어져도 데일리 수집은 계속되므로(미러만 실패), 이 검사가 없으면 모른 채 지나간다

### 5.5 launchd 재설치

`deploy/launchd/com.tjfinance.collect.plist` 수정 후 설치.

- 인자: `--download-only --days auto --timeout 600`
- 나머지 6종(백업·DQ·valuation 등)은 **이번엔 재설치하지 않는다.** 계층3 재설계 진행 중이라 파싱 계열 잡은 Phase 5 에서 함께 되살린다.
- 예외: `com.tjfinance.backup.plist`(DB 백업)는 독립적이므로 함께 복구 검토.

---

## 6. Phase 4 — 상장폐지 확정 판정 · 안전장치 · DB 반영

### 6.1 현행 판정 로직과 그 구멍 (실측)

#### 6.1.1 대상기업 리스트는 매 실행 처음부터 다시 만든다

`collector/corp_collector.py:sync_corporations()` — 증분이 아니라 **전량 재구성**이다.

```
① KRX 상장목록      FinanceDataReader.StockListing("KOSPI"/"KOSDAQ")
                    → ETF/ETN/우선주 미포함 (KIND 기준, 법인당 보통주 1개)
② DART corpCode.xml → {stock_code: (corp_code, corp_name, modify_date)}
③ stock_code JOIN   → DART 에 없으면 제외 (우선주·DART미등록)
④ 이름 필터         → 스팩/SPAC/기업인수목적·선박투자·리츠·부동산투자회사·인프라투자·투자회사
⑤ 외국기업 필터     → stock_code 가 '9' 로 시작 (900xxx·950xxx)
⑥ corporations upsert (is_active=True)
```

실측 이력(`collection_runs`, run_type='corp_sync'): KRX 2,765 → 제외 211 → **최종 2,554**. 최근 한 달 `krx_total` 2,765~2,766 으로 안정적.

#### 6.1.2 비활성 판정은 이 한 줄이 전부다

`corp_collector.py:265`

```python
to_deactivate = [c for c in existing_active if c not in final_codes]
```

**"이번 실행의 최종 후보에 없으면 비활성."** 조건이 하나뿐인데, 후보에서 빠지는 경로는 4가지이고 **전부 구분 없이 똑같이 처리된다.**

| | 경로 | 실제 의미 |
|---|---|---|
| (a) | KRX 목록에서 사라짐 | 진짜 상장폐지 |
| (b) | FDR 조회 실패 | **일시적 네트워크 오류** |
| (c) | DART corpCode.xml 매핑 실패 | DART 쪽 일시 누락 |
| (d) | 이름·외국기업 필터에 새로 걸림 | 사명 변경 등 |

#### 6.1.3 ★가장 위험한 구멍 — 시장별 부분 실패

`_get_krx_universe()` (`corp_collector.py:71`):

```python
for market in ("KOSPI", "KOSDAQ"):
    try:
        df = fdr.StockListing(market)
        ...
    except Exception as e:
        logger.warning(...)      # ← 경고만 하고 넘어감(호출자는 모른다)
if not universe:                 # ← 둘 다 실패해야 None
    return None
```

**KOSPI 조회만 실패하면** `universe` 에 KOSDAQ 만 담긴 채 `krx_mode=True` 로 진행한다.
→ `final_codes` 에 KOSPI 가 통째로 없으므로 **KOSPI 809개 전부가 `to_deactivate`** 가 된다.

지금은 `is_active=False` 만 되고 다음 실행에 자동 복구되어 티가 안 난다. 그러나 **여기에 파일 삭제를 붙였다면 KOSPI 전 종목 원문이 한 번에 사라진다.** 목록 크기 sanity 검사는 어디에도 없다.

**DART 단독 모드 폴백은 반대 방향으로 위험하다.** 둘 다 실패하면 DART corpCode.xml 전체를 후보로 쓰는데, 코드 주석이 이미 `※ DART 단독 모드는 상장폐지 기업이 포함될 수 있습니다` 라고 경고한다. 이 모드에서는 `market=None` 으로 덮어쓰기까지 한다.

#### 6.1.4 더존비즈온 건 — 판단 근거 정정 (2026-07-31)

초안에서 "KRX 조회 실패에 의한 오탐 유력"이라고 썼으나 `collection_runs` 이력이 이를 지지하지 않는다.

- 07-13 `krx_total=2766` → 07-17 `krx_total=2765` (**정확히 -1**)
- 대량 실패 흔적 없음. 같은 날 레메디가 신규 편입되어 `final_count` 는 2,554 유지

→ **KRX 목록에서 실제로 빠진 것**으로 보인다. 다만 `regulatory_events` 가 없으므로 상태는 "오탐 유력"이 아니라 **"교차 신호 부재로 미확정"**이다. §6.7 재판정 대상으로 남긴다.

이 정정은 결론을 바꾸지 않는다 — **단일 신호로 확정하지 않는다**는 원칙은 6.1.3 만으로도 충분히 정당하다.

### 6.2 상태 기계

```
       KRX 목록 부재 첫 관측
NULL ─────────────────────────► candidate
                                   │  10영업일 연속 부재 + 교차신호 ≥1
                                   ▼
                                confirmed ──► 원문 NAS 아카이브 이동
                                   │            + DB 소프트 마킹
        KRX 목록 재등장            │
  candidate/confirmed ────────► reinstated ──► 아카이브에서 원위치 복원
```

`is_active` 는 **KRX 관측 사실 그대로** 둔다(현행 `sync_corporations` 동작 보존). 조치 판단은 오직 `delisting_status` 가 한다. 두 개념을 분리해야 오탐이 파일에 손대지 못한다.

### 6.3 확정(confirmed) 조건 — 전부 충족해야 함

**G0 계열은 "소스가 믿을 만한가"를 보고, G1~G4 는 "이 기업이 정말 빠졌나"를 본다.**
G0 중 하나라도 걸리면 **그날 판정 전체를 스킵**한다(개별 기업 판정으로 내려가지 않는다).

| 게이트 | 조건 | 막아내는 것 |
|---|---|---|
| **G0a (소스)** | **시장별 조회 성공 여부를 개별 확인** — KOSPI·KOSDAQ 중 **하나라도 실패하면 전체 스킵** | §6.1.3 부분 실패. 현재는 부분 성공으로 그냥 진행해 **한 시장 전체가 비활성**이 될 수 있다 |
| **G0b (소스)** | 목록 크기 -5% 가드를 **KOSPI/KOSDAQ 각각** 적용 (전체 합계 아님) | 전체 합계로는 부분 실패가 묻힌다. 기준값은 `collection_runs` 의 직전 성공 실행 |
| **G0c (소스)** | **DART 단독 모드(`krx_mode=False`)에서는 상장폐지 판정 전면 금지** — candidate 감지조차 안 함 | 이 모드는 상장폐지 기업을 걸러내지 못한다고 코드 주석이 명시 |
| **G1** | `delisting_first_seen` 이후 **10영업일 이상 연속** 부재 | 일시적 조회 실패 (회복 시간 충분히 확보) |
| **G2** | 교차 신호 **≥ 1개**: <br>ⓐ `regulatory_events` 에 상장폐지·정리매매·상장적격성 이벤트 <br>ⓑ `stock_prices` 에 10영업일 이상 신규 시세 없음 <br>ⓒ DART 최근 정기공시 부재 | 단일 소스(KRX) 의존 |
| **G3** | 하루 `confirmed` 전환 **상한 5개** | 대량 오탐의 폭발 반경 제한 |
| **G4** | 전환 시 **알림 발송** (`scripts/notify.py`) | 사람이 사후 검토 가능 |

판정 근거는 매 검사마다 신규 테이블 `delisting_audit` 에 남긴다:

```
delisting_audit(corp_code, checked_at,
                krx_mode,              -- krx | dart_only  (G0c)
                krx_market_ok,         -- 'KOSPI:ok,KOSDAQ:ok'  (G0a)
                krx_present,
                krx_market_size,       -- 해당 시장 목록 크기  (G0b)
                days_absent, regulatory_event, last_price_date,
                dart_recent_filing, verdict, reason)
```

G0 스킵도 **기록한다** — "그날 판정을 왜 안 했는지"가 남아야 조회 실패가 반복되는 것을 알아챈다.

**왜 확정했는지 나중에 추적할 수 있어야 한다.** 오탐이 나면 이 테이블이 유일한 단서다.

### 6.4 확정 시 조치

| 대상 | 조치 | 되돌리기 |
|---|---|---|
| 원문 (NAS) | `raw_report/{MARKET}/{CODE_NAME}/` → `archive/delisted/{YYYY}/{CODE_NAME}/` **이동**(같은 볼륨, 즉시). 삭제 없음 | 폴더 되옮기기 |
| 원문 (SD) | **자동 제거 안 함.** 데일리 미러가 덧붙이기 전용이라 SD 에 남는다. 정리는 §6.4b 수동 명령 | 덧붙이기 미러가 다음 실행에서 자동 복구 |
| DB | 소프트 — 종속 데이터 **전량 보존**. `delisting_status='confirmed'`, `delisted_at`, `archive_path` 기록 | `UPDATE` 1줄 |
| 앱·스크리너 | 기본 조회에서 제외 + "상장폐지 포함" 토글 제공 | 토글 |

### 6.4b SD 백업 정리 — 수동, 연 1~2회

데일리 미러가 덧붙이기 전용이므로 아카이브 이관분은 SD 에 그대로 남는다. 정리는 **사용자가 명시적으로** 돌린다.

```
scripts/delisting_manage.py --sync-backup             # 드라이런: 지울 대상·용량만 출력
scripts/delisting_manage.py --sync-backup --apply     # 실제 삭제
```

- 대상은 `delisting_status='confirmed'` 이고 NAS 아카이브에 **실재가 확인된** 기업의 SD 폴더로 한정한다.
  전역 `rsync --delete` 를 쓰지 않는다 — 폴더 목록을 명시적으로 만들어 그것만 지운다.
- 실행 전 `assert_storage(require_backup=True)` + NAS 아카이브 실재 확인(원본 없이 백업만 지우는 사고 방지)
- 급하지 않다. **10개사 = 857MB, SD 여유 148GB.** 잊고 1~2년 지나도 문제없다.

### 6.5 DB 스키마 변경

`collector/db.py` 의 `schema_migrations` 패턴을 따른다(Alembic 없음, 멱등 DDL + id 기록).

```
2026_07_corp_delisting_status      ALTER TABLE corporations ADD COLUMN IF NOT EXISTS delisting_status VARCHAR(12)
2026_07_corp_delisting_first_seen  ALTER TABLE corporations ADD COLUMN IF NOT EXISTS delisting_first_seen DATE
2026_07_corp_delisted_at           ALTER TABLE corporations ADD COLUMN IF NOT EXISTS delisted_at DATE
2026_07_corp_archive_path          ALTER TABLE corporations ADD COLUMN IF NOT EXISTS archive_path VARCHAR(500)
2026_07_delisting_audit            CREATE TABLE IF NOT EXISTS delisting_audit (...)
2026_07_pipeline_runs              CREATE TABLE IF NOT EXISTS pipeline_runs (...)
2026_07_storage_sync_log           CREATE TABLE IF NOT EXISTS storage_sync_log (...)
```

전부 **추가만** — 기존 컬럼·데이터 무변경.

### 6.6 코드 변경

#### 6.6.1 기존 파일 수정 — `collector/corp_collector.py` (G0a 전제조건)

**G0a 는 이 수정 없이는 구현할 수 없다.** 현재 `_get_krx_universe()` 는 시장별 실패를
`logger.warning` 으로 삼켜서 **호출자가 어느 시장이 실패했는지 알 방법이 없다.**

| 항목 | 현재 | 변경 |
|---|---|---|
| 반환값 | `dict \| None` | `(dict, per_market_status: dict[str, bool \| int])` — 시장별 성공 여부·건수 동반 |
| 부분 실패 | 경고만 하고 성공한 시장으로 진행 | 호출자에게 전달. `sync_corporations` 은 **비활성 처리를 건너뛴다**(upsert 는 정상 수행) |
| 빈 결과(`df.empty`) | `continue` — 실패와 구분 안 됨 | 실패로 간주 |

> ⚠️ **비활성 처리만 건너뛰고 upsert 는 계속한다.** 부분 실패 시 신규 상장 반영은 되되,
> 기존 기업을 내리는 파괴적 방향만 막는 것이 목적이다.

이 수정은 `delisting_status` 도입과 **독립적으로 그 자체가 버그 수정**이므로 우선 적용한다.

#### 6.6.2 신규 파일

```
collector/delisting.py                 판정 엔진 (G0a~G0c·G1~G4 + 상태 전이)
scripts/delisting_manage.py            --list / --confirm <code> / --restore <code>
                                       --sync-backup (§6.4b)
```

`--dry-run` 이 기본. 아카이브 이동·SD 삭제는 명시적 `--apply` 에서만 일어난다.

### 6.7 즉시 조치 — 현재 비활성 10사 재판정

Phase 4 구현 직후 10개사를 새 규칙으로 전건 재판정한다.

- **더존비즈온(012510)** — `krx_total` 이 정확히 -1 만 움직여 조회 글리치 근거는 약하나(§6.1.4), 교차 신호(`regulatory_events`)가 없어 **미확정**. KRX·DART 원문 확인 필요
- 일정실업(008500), 바이온(032980) 등도 `regulatory_events` 부재 → 개별 확인
- 에코마케팅(230360) 은 `주식교환·이전` 매매거래정지 기록 있음 → 실제 상장폐지로 확정 가능

> 이 재판정 결과는 사용자에게 **표로 보고하고 승인받은 뒤** 조치한다. 자동 실행하지 않는다.

---

## 7. Phase 5 — 최종형: 파싱·DB 적재 재편입

계층3 재설계(`docs/plans/rearchitecture_4layer.md`)가 끝난 뒤 착수. 이번 실행 범위 아님.

- `--download-only` 플래그 해제 → §5.1 의 ⛔ 항목 복원
- **`docs/runbook_new_parser_pipeline_integration.md` 체크리스트 필수 적용**:
  ① `collect_new.py` **두 call site 모두** 배선(메인 + `--standardize-only` 재개)
  ② 21일 + Phase 2 백필분 소급 재표준화 (자동 아님)
  ③ 회귀 테스트 + 원문 대조 + Gate B 무영향
- **아카이브된 상장폐지 기업 처리**: 원문이 `raw_report` 밖이라 재파싱 대상에서 자연 제외된다. 계층2 전수 재적재 시 `delisting_status='confirmed'` 기업은 **기존 DB 데이터를 보존하고 명시적으로 스킵 + 로그**한다. 조용히 빈 값으로 덮어쓰지 않는다.
- 파싱 계열 launchd 잡 재설치

---

## 8. 검증 계획

| ID | 대상 | 방법 | 합격 기준 |
|---|---|---|---|
| V1 | 저장소 계약 | `tests/test_storage_guard.py` — 심링크 오설정(I1)·sentinel 부재(I2)·읽기쓰기 불가(I3)를 각각 주입 | 전 케이스에서 `StorageContractError`, **경고 후 진행 0건** |
| V1b | 불변식 I1 회귀 | 심링크를 SD로 돌린 상태에서 `sync_storage_mirror.py` 실행 | M1 에서 중단. **파일 삭제 0건** |
| V1c | 덧붙이기 미러 무해성 | NAS 소스를 일부러 비운 채 미러 실행 | **SD 파일 삭제 0건** (`--delete` 부재 확인) |
| V1d | 수동 삭제 안전성 | `delisting_manage.py --sync-backup` 드라이런 → NAS 아카이브 없는 기업 주입 | 해당 기업은 삭제 대상에서 **제외**, 경고 |
| V2 | 심링크 원복 무결성 | 원복 후 기존 파일 표본 200건 읽기 | 읽기 실패 0 |
| V3 | 미러 정합 | `scripts/qa/verify_storage_mirror.py` (오늘 쓴 `sync_diff2.sh` 를 정식화). 당일 변경분 전수 + 표본 90사 | 실파일 불일치 0 |
| V4 | 수집 완전성 | `audit_download_gap.py --days 30` | 미탐지 0 · 미다운로드 0 |
| V5 | 정정보고서 | 백필 후 최근 30일 정정 전건이 `filings` 에 존재하고 `is_final` 그룹당 정확히 1건 | 위반 0 |
| V6 | 상장폐지 판정 | 과거 6개월 데이터로 백테스트 — 실제 상장폐지사 재현율, 오탐 0 | 오탐 0 |
| **V6a** | **G0a 부분 실패** | `fdr.StockListing("KOSPI")` 가 예외를 던지도록 주입하고 `sync_corporations` 실행 | **`to_deactivate` 0건** (현행 코드는 809건 비활성 — 회귀 방지 기준선) |
| **V6b** | G0b 시장별 급감 | KOSDAQ 목록을 90%로 축소해 주입 | 판정 스킵 + `delisting_audit` 에 사유 기록 |
| **V6c** | G0c DART 단독 모드 | FDR 전체 실패 주입 | candidate 감지 **0건**, upsert 는 정상 |
| V7 | 회귀 | `pytest` | 253/253 유지 |

---

## 9. 실행 순서

각 단계는 **앞 단계 합격 후** 진행. 병렬 실행 금지.

```
1. Phase 1  저장소 계약        S1 → S2 → V1 → S2b(역방향 정산) → S3 → V2 → V1b·V1c → S5
2. Phase 2  밀린 분 백필        B1 → B2 → B3 → B4 → B5(V4)
3. Phase 3  데일리 재구성       5.1 → 5.2 → 5.3(V3) → 5.4 → V7 → 5.5 launchd
4. Phase 4  상장폐지            6.6.1 corp_collector 수정(G0a 전제·단독 버그수정) → V6a
                               → 6.5 DDL → 6.6.2 엔진 → V6·V6b·V6c
                               → 6.7 재판정 보고 → [사용자 승인] → 조치
5. Phase 5  파싱·적재 재편입    (계층3 재설계 완료 후, 별도 계획)
```

**사용자 실행 구간**(장시간·네트워크): **S2b 전수 대조·역방향 정산**(SMB 전수 순회 10분+), Phase 2 백필 전체, Phase 3 초회 rsync, Phase 4 재판정.
나머지는 코드 작성·커밋.

---

## 10. 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| ~~`rsync --delete` 가 SD 백업 218GB 를 지움~~ | ~~치명~~ | **해소 — 데일리에서 `--delete` 제거(D3'/§5.3.1).** 잔여분은 §6.4b 수동 명령에 한정되고, 거기서도 전역 `--delete` 대신 명시적 폴더 목록만 삭제 |
| 심링크 드리프트 5회차 | **중간**(치명→강등) | G2(I1) 로 차단. 뚫려도 덧붙이기 미러라 파일이 지워지지 않고 "NAS 에 안 올라감"에 그침 → S2b 역방향 정산으로 회수. 단 드리프트 근본 원인은 미규명(§3.3) |
| **SD 미러가 조용히 낡음** (덧붙이기 전환의 대가) | 중간 | §5.4 미러 신선도 검사 — 마지막 성공 7일 초과 경고 / 30일 초과 error+알림 |
| Gate A 가 데일리에 없어 파일 유실이 조용히 지나감 | 높음 | §5.4 완전성 감사에서 `download_tasks.completed` 대비 **파일 실재 여부** 검사 추가(당일분 전수) |
| 상장폐지 오탐으로 원문 유실 | 높음 | 결정 D1 로 **삭제 자체를 안 함**(아카이브 영구 보존) + G0a~G4 |
| **KRX 시장별 부분 실패로 한 시장 전체 비활성** (§6.1.3, 현행 코드에 가드 0) | 높음 | 6.6.1 `corp_collector` 수정 + G0a. **`delisting_status` 도입과 무관한 단독 버그이므로 Phase 4 최우선** |
| SD 용량 70% → 포화 | 중간 | 상장폐지 이관은 **회수량이 미미**(857MB/10사)하므로 대책이 못 된다. 진짜 지렛대는 **SD 를 최근 N년만 미러링**하는 부분 백업(결정 D5, 보류). M3 가드가 임계 도달을 먼저 알린다 |
| DART API 쿼터 초과 (장기 공백 백필) | 중간 | 조회 창 90일 상한 + 기존 `rate_limiter` |
| Phase 5 까지 재무 DB가 21일+ 낡음 | 중간 | **의도된 상태**. 원문은 확보되므로 소급 재표준화로 복구 가능. 앱에 기준일 캡션 노출 |
| `--download-only` 분기가 Phase 5 에서 되살아나지 않음 | 중간 | 삭제 아닌 조건 분기 + 런북 체크리스트 ①(두 call site) |

---

## 11. 이 계획이 답하는 최초 질문

| 질문 | 계획상 해결 |
|---|---|
| 분기·반기·사업보고서가 오늘까지 다 받아졌나 | Phase 2 백필 + Phase 3 `--days auto` 자가복구 |
| 정정보고서도 같이 받나 | 로직은 이미 정상. Phase 3 스케줄러 복구로 자동 해결 + V5 검증 |
| NAS 기본 / SD 백업인가 | Phase 1 S3 심링크 원복 + G2 상시 검증 |
| 두 저장소가 같은 구조·파일인가 | Phase 3 §5.3 rsync + V3 정합 검증 |
| NAS 저장 시 SD도 자동 동기화되나 | Phase 3 §5.3.2 덧붙이기 미러 자동(결정 D3·D3'). 지우기만 수동(§6.4b) |
| 매일 확인해서 신규 다운로드하나 | Phase 3 §5.5 launchd + §5.4 완전성 감사 |
| 상장폐지 기업 폴더를 정리하나 | Phase 4 — 안전장치 통과 후 NAS 아카이브 이관(자동), SD 정리는 수동 연 1~2회(결정 D1·D2·D3') |

---

## 12. 실행하며 계획과 달라진 것 (2026-07-31 완료 시점)

계획을 세울 때 몰랐던 사실 때문에 바뀐 부분만 적는다. 계획서 본문은 초안 그대로 두고 여기서 정정한다.

### 12.1 ★드리프트 근본 원인 = macOS TCC → §3.3 참조

가장 큰 변화. "원인 미규명"이 규명됐고, 07-17 장애 진단(스테일 마운트)이 오진이었다.

### 12.2 상장 유니버스 소스가 바뀌었다 — KRX OpenAPI 도입 (결정 D7)

계획은 FDR 스크래핑을 전제로 G0a/G0b/G0c 를 설계했다. 실행 중 사용자가 KRX OpenAPI 키를
발급받아 **공식 API 를 1차 소스로** 쓴다.

| | FDR (기존) | **KRX OpenAPI (신규 1차)** |
|---|---|---|
| 인증 | 없음(스크래핑) | `AUTH_KEY` 헤더 |
| 실패 표현 | 예외/빈 결과 | 401 (명시적) |
| 우선주 | 섞여 들어옴 → DART 매핑 실패로 간접 제외 | `KIND_STKCERT_TP_NM` 으로 **직접 제외** |
| 인프라펀드·리츠 | 이름 키워드로 거름(누락 발생 — 3사) | `SECUGRP_NM` 으로 **자동 제외** |
| 부가 필드 | — | 상장일 `LIST_DD` · 상장주식수 `LIST_SHRS` |

- **상호보완 구조**: 시장별로 독립 판정. KRX 실패 → 그 시장만 FDR 로 폴백. **둘 다 실패한
  시장이 있을 때만** 비활성 처리를 건너뛴다.
- 교차검증: 겹침 95% 미만이면 경고+메일. 실측 **100.0%**.
- ⚠ **함정**: `basDd` 를 안 주거나 당일을 조회하면 **HTTP 200 + 0건**이 온다. 그대로 믿으면
  전 종목이 상장폐지 처리된다 → `krx_client` 는 빈 목록을 **실패로 취급**하고 직전 영업일로
  최대 10일 소급 재시도한다.
- ⚠ **활용기간**: 서비스별 신청·승인제. 2026-07-31 기준 유가증권 **1개월**·코스닥 1년.
  만료되면 401 `Unauthorized API Call` → 그 시장만 FDR 폴백 + **메일 경고**.

### 12.3 상장폐지 판정에 '양성 증거' 경로 추가 (계획에 없던 것)

계획의 G1(10영업일 대기)+G2(교차신호)는 **"목록에 없으니 폐지겠지"라는 추론**을 전제로 한다.
실행 중 **KRX-DELISTING 명부**(FDR, 4,170행)를 찾았다 — 폐지일·사유가 명시된 **사실**이다.

- 명부 등재는 G1 을 건너뛰고 즉시 확정한다. G1 은 *추론이 틀릴 위험*을 막는 장치이므로
  명시된 사실에는 적용할 이유가 없다.
- **계획의 G2 만으로는 부족했다는 실측**: 더존비즈온·일정실업은 `regulatory_events` 가 **0건**이다.
  "지주회사 완전자회사화"·"시가총액 미달"은 DART 시장조치 공시로 발생하지 않는다.
- 대신 명부 오염 가드: 미확정 기업의 **2% 초과**가 명부에 걸리면 명부를 통째로 불신하고
  추론 경로로 폴백(실측 12/2,545 = 0.47%).
- 일일 상한도 분리 — 추론 5건, 명부 20건(실패 양상이 다르다).

> 웹 검색 연동도 검토했으나 채택하지 않았다. 결과가 매번 다르고("상장폐지 위기" 기사도 매칭)
> 안전이 중요한 판정 경로에 부적합하다. 명부가 더 권위 있고 결정적이며 이미 설치된 의존성이다.

### 12.4 판정 대상 집합 두 가지를 분리 (설계 결함 수정)

- **`listed_codes()`(전 증권 2,764)** — "거래소에 상장돼 있나"
- **`to_universe()`(보통주 2,604)** — "우리 투자대상인가"

판정을 후자로 하면 KRX 에 멀쩡히 상장된 **인프라펀드·리츠가 폐지로 오판**된다.
또한 판정 대상을 `is_active=TRUE` 로 좁히면 `corp_collector` 가 이미 내린 기업이
**영원히 미평가**로 남는다(실제 5개사).

### 12.5 미러는 증분이 기본 (결정 D8)

계획 §5.3 은 매 실행 전 트리 rsync 를 전제했다. 실측 **40분**(189,099 파일 × SMB stat 15ms).
데일리로 부적합 → `--files-from` 으로 최근 다운로드분만 전송 → **4초**. 전 트리는 `--full`.

### 12.6 신선도 검사가 처음부터 고장나 있었다

`started_at` 을 Python `utcnow()`(UTC)로, `finished_at` 을 DB `now()`(KST)로 써서 차이가 음수였다.
`.days == -1` 이라 warn/error 임계를 **절대 넘지 못했다** — 경보가 영원히 안 울리는 상태.
시각을 DB `now()` 로 통일하고 경과일수를 DB 안에서 계산하도록 고쳤다. 음수는 통과가 아니라 실패.

### 12.7 계획에 있었으나 구현 때 빠뜨린 것

**⓪-3 상장폐지 판정이 데일리에 배선되지 않았다.** §5.1 에 단계로 적어두고 누락했고,
`delisting_manage.py` 수동 실행으로만 가능했다. 유니버스 갱신 직후로 배선했다.

또 `--refresh-universe` 가 opt-in 이라 플래그를 빼먹으면 신규 상장이 영원히 안 들어오고
상장폐지 판정도 통째로 건너뛰었다 → **기본 ON**.

### 12.8 launchd 설치가 막혔던 두 가지 (README 에 진단 절차 기록)

`Bootstrap failed: 5: Input/output error` 는 원인을 전혀 안 알려준다.
① 2026-07-22 잡 삭제 때 레이블이 **disabled 로 남아** 있었다 → `launchctl enable` 필요
② plist 에 **DOCTYPE 이 없었다** (`plutil -lint` 는 OK 를 냄)

### 12.9 S2b 역방향 정산은 불필요했다 (하지만 확인은 필요했다)

전수 대조 결과 NAS·SD **실파일 189,099개 완전 일치**, SD 전용 0건. 유일한 차이는
`.sync.ffs_db`(FreeFileSync 동기화 DB) 1건 — 사용자가 그 도구로 수동 동기화해 왔다.
제외 목록에 추가했다.
