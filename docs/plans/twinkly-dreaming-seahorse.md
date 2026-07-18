# 기업별 순차 다운로드 + 보고서↔DB 전기간 검증 파이프라인

## Context (왜 이 작업을 하는가)

현재 파이프라인은 **배치(가로) 방식**이다: 전 기업 download → 전 기업 fin2-all(E→R→S) → 전 기업 Gate B. 단계가 분리돼 있어 한 기업의 "보고서 원본 = DB 적재값 100% 일치"(PRD 00 불변 원칙) 상태를 한 번에 확인하기 어렵고, 문제 발견이 늦다.

사용자 요구: **기업을 corp_code 순으로 하나씩** 받아서, 그 기업의 **전체 기간(상장 이후 분기/반기/사업보고서 전부)** 에 대해 보고서와 DB를 비교 검증하고 다음 기업으로 넘어가는 **세로(per-company vertical slice) 루프**. 한 기업이 끝나면 그 기업은 "검증 완료/실패 사유 기록" 상태가 남는다.

빌딩블록은 모두 존재한다. 새로 만들 것은 이들을 **기업 단위로 순차 오케스트레이션**하는 드라이버와 **기업별 검증 상태 기록**이다.

### 사용자 확정 결정
- **검증 깊이**: 1단계는 현행 `face_audit`(표준 40필드 std_v2 매핑) 비교로 전수 → 후속 단계에서 본문 전 계정 라인 전수 비교로 확장.
- **basis 범위**: 연결+별도 둘 다 (gateb_audit는 std_v2 전 행을 순회하므로 자동 포함).
- **실패 처리**: 보고서≠DB여도 중단하지 않고 `face_audit`/리포트에 기록 후 다음 기업 계속.
- **대상/순서**: 활성 보통주 전수, `corp_code` 오름차순.

## 기존 빌딩블록 (재사용)

| 단계 | 명령/함수 | 위치 |
|---|---|---|
| 공시목록 동기화 | `run.py sync-filings --corp CODE` → `sync_filings()` | `collector/filing_collector.py` |
| 보고서 다운로드 | `run.py download --corp CODE` → `run_downloads(only_corp_codes=[...])` | `collector/downloader.py` |
| Gate A(다운로드 유효성) | `scripts/validate_downloads.py --statements` → `download_tasks.gate_a_status` | `scripts/validate_downloads.py` |
| E→R→S→분기→달력 | `cmd_fin2_all` 내부 호출: `_extract2_corp`/`reconcile_corp`/`standardize_corp`/`derive_quarters_corp`/`calendarize_corp` | `run.py:2902-2917`, `fin2/` |
| Gate B(보고서↔DB 100%) | `scripts/gateb_audit.py --corp CODE` → `face_audit` upsert | `scripts/gateb_audit.py`, `fin2/audit/face_audit.py` |

## 설계: 기업 단위 순차 오케스트레이터

신규 스크립트 **`scripts/verify_corp_sequential.py`** (기존 `scripts/fin2_*.py` 오케스트레이터 패턴 — `--corps`, `--shard`, `--resume-file`, 기업 단위 커밋 — 을 그대로 따름).

활성 보통주 corp_code 오름차순 목록을 돌며, **각 기업마다 아래 6단계를 순서대로** 실행하고 기업 단위로 커밋한다. 기업별 예외는 로깅 후 계속(전체 중단 방지).

```
for corp in active_corps (corp_code ASC):
    if corp in corp_verify_status(done) and not --recheck: skip
    1) sync-filings(corp)        # DART list API로 전기간 공시목록 최신화
    2) download(corp)            # 전기간 보고서 다운로드(멱등·재개)
    3) Gate A(corp)              # 파일 무결성 + 재무제표 존재 → gate_a_status
    4) fin2 chain(corp)          # extract2 → reconcile → standardize → quarterly → calendar
    5) Gate B(corp)              # face_audit: 보고서 본문 vs DB(std_v2 40필드), 연결+별도 전 fy
    6) rollup(corp)              # face_audit 집계 → corp_verify_status 기록(전기간 pass/fail/pending)
    commit
```

4단계는 `run.py fin2-all`의 기업별 로직을 그대로 재사용한다. `cmd_fin2_all`의 기업 루프 본문(`run.py:2902-2917`)을 **`process_corp(session, corp)` 헬퍼 함수로 추출**해 `run.py`와 신규 오케스트레이터가 공유한다(중복 방지).

### 기업별 검증 상태 기록 (신규)

신규 테이블 **`corp_verify_status`** (오케스트레이터가 기업 단위로 upsert). 재개 마커이자 전기간 검증 결과 요약.

| 컬럼 | 용도 |
|---|---|
| `corp_code` (PK) | 기업 |
| `stage` | last_done: downloaded / loaded / audited |
| `gate_a_pass` / `gate_a_fail` | 다운로드 유효성 카운트 |
| `n_std_rows` | std_v2 적재 행수(연결+별도, 전기간) |
| `gb_pass` / `gb_fail` / `gb_pending` | face_audit 집계(전 fy·fp·basis) |
| `fail_periods` (JSONB) | 실패한 (fy,fp,basis) 목록 — triage 진입점 |
| `verified_at` | 검증 시각 |

전기간 통과 기준: 해당 기업의 `face_audit` 행 중 `gate_status='fail_a'`(Track A 자기보고서 불일치)가 **0건**이면 기업 PASS, 그 외는 FAIL(사유는 `fail_periods`에 기록, 루프는 계속).

## Phase 구성

### Phase A — 표준 40필드 전수 검증 (지금)
1. `process_corp` 헬퍼 추출 (`run.py` 리팩터, `cmd_fin2_all`와 신규 드라이버 공유).
2. `validate_downloads.py`에 **`--corp` 필터 추가**(현재 전역만 지원) — 기업 단위 Gate A 스코핑.
3. `corp_verify_status` 테이블 + 마이그레이션 (`collector/models.py`, `collector/db.py`).
4. `scripts/verify_corp_sequential.py` 작성: 6단계 루프, `--corps START:END`/`--shard a/n`/`--recheck`/`--limit`, 기업 단위 커밋·재개, 실패 비중단.
5. 기업별 실패 리포트 출력: `corp_verify_status` + 콘솔 요약(진행 N/total, pass/fail/pending 누적).

### Phase B — 본문 전 계정 라인 전수 비교 (후속)
- `fin2/audit/face_audit.py`의 `read_report_face_*`를 확장해 std 40필드 매핑이 아니라 **보고서 본문 BS/IS/CF 전 라인**을 DB의 fact_v2/std와 대조(PRD 04 원안). 별도 단계로 분리해 Phase A 전수 통과 후 착수.

## 수정/생성 파일

- **신규** `scripts/verify_corp_sequential.py` — 기업 단위 순차 오케스트레이터.
- **수정** `run.py` — `cmd_fin2_all` 기업 루프 본문을 `process_corp(session, corp)` 헬퍼로 추출(`run.py:2902-2924`).
- **수정** `scripts/validate_downloads.py` — `--corp` 인자 추가(WHERE에 corp 스코프).
- **수정** `collector/models.py` — `CorpVerifyStatus` 모델 추가.
- **수정** `collector/db.py` — `corp_verify_status` 경량 마이그레이션.
- 재사용(변경 없음): `scripts/gateb_audit.py`, `fin2/audit/face_audit.py`, `collector/filing_collector.py`, `collector/downloader.py`.

## 검증 (end-to-end 테스트)

1. **파일럿 1사**: `python scripts/verify_corp_sequential.py --corps 0:1`
   → 한 기업이 sync-filings→download→GateA→fin2→GateB→rollup 완주, `corp_verify_status` 1행 생성 확인.
2. **상태 점검 쿼리**: `SELECT * FROM corp_verify_status WHERE corp_code=:c;` — gb_pass/fail/pending 합이 해당 기업 `face_audit` 행수와 일치하는지.
3. **재개 검증**: 같은 명령 재실행 시 done 기업 skip 로그 확인(`--recheck`로 강제 재검 동작 확인).
4. **실패 비중단 검증**: 일부러 fail이 있는 기업(기존 face_audit fail_a 보유 기업)을 포함시켜 루프가 멈추지 않고 `fail_periods` 기록 후 다음 기업으로 진행하는지.
5. **소표본 전수**: `--corps 0:10`로 10사 완주 후 콘솔 누적 요약(pass/fail/pending) 및 소요시간 확인 → 전수 샤딩(`--shard a/n`) 분할 실행 계획 산정.

## 운영 메모
- 다운로드·Gate B는 XML 다수 open으로 **장시간** 작업 → 사용자가 직접 실행(메모리 `feedback-long-running-commands` 준수), Claude는 코드/쿼리 제공.
- 전수는 `--shard`로 분할 권장. 각 샤드 독립 재개 가능.
- Pro 요금제·DB 쿼리 일정 속도 유지: rollup 집계는 corp 단위 인덱스(`face_audit(corp_code)`) 사용.
