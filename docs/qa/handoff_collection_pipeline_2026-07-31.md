# 핸드오프 — 수집 파이프라인 복구 완료 (2026-07-31)

> 계획: `docs/plans/collection_pipeline_restore_2026-07-31.md` (§12 = 실행하며 달라진 것)
> 다음 단계 런북: `docs/runbook_phase5_reenable_parsing.md`

---

## 0. 한 줄 요약

**21일간 멈춰 있던 보고서 수집이 복구됐고, 매일 18:00 자동 실행이 launchd 에서 실증됐다.**
Phase 1~4 완료. Phase 5(파싱·적재 재편입)는 계층3 재설계 후로 미룸.

---

## 1. 처음 질문과 최종 상태

| 확인 항목 | 처음(07-31 오전) | 지금 |
|---|---|---|
| 분기·반기·사업보고서 최신화 | ❌ 07-10 이후 21일 중단 | ✅ 41건 백필 · 미다운로드 0 |
| 정정보고서 포함 | ⚠️ 24건 미탐지 | ✅ 전부 수집 · 로직 정상 |
| NAS 주 / SD 백업 | ❌ 뒤바뀜(심링크가 SD) | ✅ 원복 + 불변식 가드 |
| 두 저장소 싱크 | ⚠️ 수동(FreeFileSync) | ✅ 189,099개 일치 + 자동 증분 미러 |
| NAS 저장 시 SD 자동 동기화 | ❌ 코드 없음 | ✅ 데일리 ⑥단계(4초) |
| 매일 확인 + 상장폐지 정리 | ❌ 스케줄러 없음 | ✅ 18:00 launchd · 12사 확정 |

---

## 2. ★가장 중요한 발견 — 21일 공백의 진짜 원인

**macOS TCC 가 launchd 프로세스의 네트워크 볼륨(SMB) 접근을 차단하고 있었다.**

| 대상 | 터미널(수동) | launchd |
|---|---|---|
| NAS `/Volumes/tj_finance_data` | listdir OK | **EPERM (errno 1)** |
| SD `/Volumes/dart_data` | OK | OK |
| 내장 디스크 | OK | OK |

`stat` 은 되고 `listdir`/`read` 만 EPERM 인 것이 TCC 시그니처다.

**이것이 설명하는 것**
- 2026-07-17 다운로드 13/13 실패 (당시 "스테일 마운트"로 오진했음)
- **심링크가 4회(7/7·7/11·7/26·7/31) SD 로 "드리프트"한 것** — 사고가 아니라 우회책이었다.
  스케줄 잡이 NAS 에서 안 되니 SD 로 되돌린 것이고, SD 를 가리키는 상태가
  **유일하게 작동하던 구성**이었다.

**해결(적용됨)**: `python3.9` 실체 경로를 전체 디스크 접근 권한에 추가
```
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9
```

**⚠ 교훈 — 이 부류는 수동 검증으로 절대 안 잡힌다.** 터미널은 TCC 를 상속받아 항상 성공한다.
스케줄 잡은 **반드시 launchd 로 한 번 돌려서** 확인할 것. 메모리 [[launchd-tcc-nas-blocked]].

---

## 3. 지금 데일리가 하는 일 (실증됨, 19:07 launchd 실행 `exit 0`)

```
⓪   저장소 계약 검증      실패 시 즉시 중단 + 메일 (경고 후 진행 금지)
⓪-1 시장조치 이벤트
⓪-2 자본 이벤트
⓪   유니버스 갱신         KRX OpenAPI 1차 + FDR 2차 (기본 ON)
⓪-3 상장폐지 판정         DB 상태만 — 원문 파일은 안 건드림
①   공시 탐지             --days auto (pipeline_runs 워터마크, 3일 겹침·90일 상한)
②   공시목록 동기화       정정보고서 버전관리
③   다운로드              → NAS
────────── Phase 5 경계 (파싱·적재 ⛔ 조건 분기로 대기) ──────────
⑥   NAS→SD 증분 미러      4초 (--files-from)
⑦   완전성 감사           DART 대조 + 파일 실재 확인 → 누락 시 error + 메일
⑧   워터마크 기록
```

`launchctl list | grep tjfinance` · 매일 18:00 · `pmset` 17:58 기상 설정됨.

---

## 4. 신설된 것

| 파일 | 역할 |
|---|---|
| `collector/storage_guard.py` | 불변식 I1/I2/I3 · 게이트 G1~G5. 계약 위반 시 예외(경고 후 진행 금지) |
| `collector/krx_client.py` | KRX OpenAPI. **HTTP 200+0건 함정** 방어 · 폐지명부 `fetch_delisted()` |
| `collector/delisting.py` | 판정 엔진. G0(소스신뢰)/G1~G4 + **양성증거 경로**(명부는 G1 우회) |
| `scripts/sync_storage_mirror.py` | 덧붙이기 전용 미러(`--delete` 없음) · 증분 기본 · 신선도 감시 |
| `scripts/delisting_manage.py` | `--evaluate/--list/--archive/--restore/--sync-backup` (드라이런 기본) |
| `scripts/backfill_corps.py` | 기업 지정 전 기간 백필 (`--zero-filings`) |
| `scripts/qa/audit_download_gap.py` | DART 대조 수집 완전성 감사 |
| `scripts/qa/verify_storage_mirror.py` | NAS↔SD 정합 검증 (`--full/--sample/--since`) |
| `tests/test_storage_guard.py` (10) | 드리프트·sentinel·읽기쓰기 결함 주입 |
| `tests/test_corp_universe_guard.py` (8) | 폴백·부분실패·빈결과·DART단독 |

DB 추가: `corporations` 4컬럼(`delisting_status`·`delisting_first_seen`·`delisted_at`·`archive_path`) +
`delisting_audit`·`pipeline_runs`·`storage_sync_log` 3테이블. **전부 추가만.**

회귀 **83/83**. 커밋 `8b62965`·`0eefd66`·`607fc92`·`c14c1f0`·`3b404c2`.

---

## 5. 상장폐지 12사 확정 (원문 미이관)

`delisting_status='confirmed'` + `is_active=false` + 폐지일 기록. **원문은 그대로 `raw_report` 에 있다.**

노블엠앤비·더존비즈온·바이온·비유테크놀러지·스타코링크·아이엠·아크솔루션스·에코마케팅·
일정실업·프로브잇·현대홈쇼핑·NPX
(완전자회사화 4 · 상장적격성 5 · 감사의견거절 1 · 시총미달 1 · 기타 1)

- 펀드 3사(맥쿼리인프라·맵스리얼티·KB발해인프라)는 **폐지 아님**으로 정확히 제외됨
- 아카이브 이관은 수동: `scripts/delisting_manage.py --archive --apply`
- 되돌리기: `--restore <corp_code> --apply`

---

## 6. 다음 세션이 할 일

### 6.1 우선순위 없음 — 데일리는 자율 운영 중

매일 18:00 자동 실행되고, 실패하면 메일이 온다. 당장 개입할 것은 없다.

### 6.2 Phase 5 (계층3 재설계 완료 후)

**`docs/runbook_phase5_reenable_parsing.md` 를 그대로 따를 것.** 핵심만:
1. plist 에서 `--download-only` 한 줄 제거
2. **두 call site 모두** 배선 확인 (메인 + `--standardize-only`)
3. **소급 백필은 자동 아님** — 대상 구간은 `pipeline_runs WHERE mode='download_only'`
4. 아카이브된 상장폐지 기업은 원문이 `raw_report` 밖 → 명시적 스킵(조용히 덮어쓰면 시계열 소실)
5. **P5-6 launchd 실행 검증을 건너뛰지 말 것**

### 6.3 관찰만 하면 되는 것

| 항목 | 언제 | 조치 |
|---|---|---|
| **KRX 유가증권 활용기간 1개월** | 2026-08 말 | 만료 시 401 → FDR 자동 폴백 + 메일. 재신청 시 **1년으로** |
| SD 여유 128Gi (74%) | 연 30GB 증가 → 약 4년 | M3 가드가 20GB 에서 경고. 부분 미러(D5) 검토 |
| SD 정체불명 124GB | 사용자 처리 예정 | `du` 225G vs `df` 349Gi. `.Trashes` 유력 |
| 미러 신선도 | 자동 | 7일 초과 경고 / 30일 error+메일 |

### 6.4 남은 정리

- `note_lines` VACUUM FULL — **불필요할 가능성 높음**. `report_lines` 실측 회수량 **0 bytes**
  (드롭 컬럼이 전부 NULL 이었다). 메모리의 "VACUUM 으로 회수 필요"는 사실이 아님이 확인됨.
- 계획서 §1.1 의 07-17 진단(스테일 마운트)은 §3.3 에서 정정했으나 본문은 초안 그대로 둠.

---

## 7. 이번 세션에서 고친 '조용한 결함' 5가지

기록해 둘 가치가 있는 것들 — 전부 **증상이 안 보이는** 유형이었다.

1. **신선도 검사가 처음부터 무력**했다. Python `utcnow()` vs DB `now()` 로 차이가 음수 →
   `.days == -1` → 임계를 절대 못 넘음. 백업이 낡는 걸 잡으려던 장치가 그 이유로 안 울렸다.
2. **`_get_krx_universe()` 부분 실패를 삼켰다.** KOSPI 조회만 실패해도 그 시장 809개가
   통째로 비활성 대상이 됐다. 파일 삭제가 연결됐다면 원문이 한 번에 사라진다.
3. **판정 대상을 `is_active=TRUE` 로 좁혀** 이미 내려간 기업 5사가 영원히 미평가로 남았다.
4. **투자 유니버스로 폐지를 판정**해 KRX 에 상장된 펀드 3사가 폐지로 오판됐다.
5. **드라이런이 감사 원장에 `confirmed` 로 기록**됐다(29건 중 실제 12건). 원장의 존재 이유가
   사후 추적인데 거짓을 남기고 있었다 → `dry:` 접두 + 과거분 정정.
