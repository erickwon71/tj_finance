# Phase C 실행 계획 — 파싱 루프(24/7 무인) × 결정 루프(사용자 시간대 배치)

> 상위 계획 = `docs/plans/vast-nibbling-blum.md` · 착수 핸드오프 =
> `docs/qa/handoff_phaseC_kickoff_2026-07-18.md`
> **확정된 결정**: D1=신버전 swap(version=2) · D2=연속 백그라운드 launchd 잡 ·
> D4=패턴루프 3라운드 상한 · 후보기록=std_v2.value_lineage 일원화 · 파일럿=10사.

---

## Context — 왜 이렇게 나누는가

사용자 가용시간:
- **파싱/재구축(compute)**: **24시간 내내 수행 가능, 무인**.
- **결정(사용자 확인)**: 평일 **20:00–22:00**, 토/일 **08:00–22:00** 에만 가능.

Phase C 는 성격이 다른 두 작업이 섞여 있다 — (a) 79,010 보고서를 다시 파싱해 fact_v2/std_v2
를 재구축하는 **순수 계산**, (b) 애매분(단위 미선언·퍼지매핑·다중후보 등)을 사람이 판정하는
**결정**. 이 둘을 **하나의 루프로 묶으면 계산이 사람 대기 때문에 멈춘다.** 사용자 가용시간이
제한적이므로 **분리**한다:

- **파싱 루프는 사람을 절대 기다리지 않는다.** 확정분은 즉시 version=2 로 적재하고, 애매분은
  `std_v2.value_lineage`(보류큐)에 쌓고 넘어간다. 24/7 무인 진행.
- **결정 루프는 배치**로 돈다. 보류큐를 **원인 패턴별로 묶은 다이제스트**를 언제든 준비해 두고,
  사용자는 자기 시간대에 열어 검토·판정한다. 파서 개선 → 해당 패턴 기업만 상태 리셋 → 파싱
  루프가 다시 주워 재처리. **사용자가 자리에 없어도 계산은 계속 전진한다.**

---

## D2 (확정) — 오케스트레이션

**연속 백그라운드 launchd 잡** (야간 한정 아님). 근거: "24시간 내내 문제없음" + collect/gapfill
가 이미 중지 상태라 경합 없음. gapfill 잡의 **자기해제 패턴**을 그대로 따른다.

- 신규 스크립트 `scripts/phase_c_rebuild.py` — `verify_corp_sequential.py` 구조 재사용
  (corp 오름차순, **기업단위 원자 커밋 = DB 체크포인트**, 재개 skip, `--shard a/n` 분할).
  대상은 `corporations` 가 아니라 **`rebuild_target_track1`**(이미 `status`/`processed_at` 보유
  → 그 컬럼으로 재개·재실행 제어).
- 신규 plist `com.tjfinance.phasec.plist` — `ProcessType=Background`, `RunAtLoad=true`,
  `KeepAlive`(크래시/재부팅 시 재개), 로그 `logs/phase_c.*.log`. 대상 전량
  `status='done'` 이면 스크립트가 **스스로 launchctl unload + plist 삭제**(gapfill 선례).
- 규모 실측 ~150파일/분 → 순수 파싱 ~9h + 표준화 → **며칠에 걸쳐 무인 완주**. 사용자 개입 0.

> 대안(수동 foreground)은 사용자가 며칠간 반복 재실행해야 하므로 가용시간 제약과 상충 →
> 권장하지 않음. 단 **첫 파일럿(1~10사)은 foreground 로 눈으로 확인 후** 잡 등록.

### 기업 단위 파이프라인 (파싱 루프 1스텝, 원자 커밋)
```
rebuild_target_track1 에서 이 기업의 대상 rcept 들
  → 재파싱(신 fin2/extract/text.py, 추측 0, provenance 채움)
  → fact_v2 재구축: 대상 rcept 기존 행 DELETE 후 재삽입(rcept 단위 = swap 의 fact 층)
  → reconcile.select_source
  → std_v2 **version=2** 로 build (확정분 적재 / 애매분 value_lineage 에 기록 + 값 NULL)
  → ★ shares.py 재백필(D3, version=2)  ← 놓치면 valuation_daily 전멸
  → quarterly(version=2) → calendar(version=2)
  → rebuild_target_track1.status='done', processed_at=now  (COMMIT)
```

---

## D4 (확정) — 패턴루프 운영 (사용자 시간대 배치)

**3라운드 상한. 배치 반복 후 잔여는 영구결측/개별처리로 명시.**
근거: 커버리지와 소요시간의 균형 + 시간대 제약. 라운드 사이의 재파싱은 전부 24/7 무인이므로
사용자 시간은 **판정에만** 쓰인다.

### 다이제스트 (사용자 검토용, 언제든 준비)
신규 스크립트 `scripts/phase_c_review_digest.py` — `value_lineage` + 보류사유를 **원인 패턴별로
그룹핑**해 대표사례 N개 + **DART 원문 링크**를 마크다운으로 출력(`docs/qa/phase_c_review_*.md`).
예상 패턴(§ vast-nibbling-blum 실측 기반):

| 패턴 | 사유 | 사용자 판정 |
|---|---|---|
| 단위 미선언 + 금액행 존재 | `(단위:…)` 없음 | 원문 확인 → 실제 단위 or 거부 |
| **외화 표시 재무제표** | `(단위:CNY/USD)` | FX 설계 or 영구결측 (실측 1.6%) |
| 퍼지 매핑 후보 | canonical=NULL 보류 | alias 승급 or 결측 |
| 다중후보 충돌 | max-abs 폐지로 보류 | 어느 후보가 맞는지 |
| 본문 없음 | 섹션 미검출 | 제외 확정(대개 Track 2/3) |

### 배치 운영 리듬 (사용자 가용시간 정합)
1. 파싱 루프가 하루치를 무인 소화 → 밤사이 보류큐 갱신.
2. 사용자가 창(평일 20–22 / 토·일 08–22)에서 다이제스트를 연다 → **패턴 단위**로 판정
   (값 하나씩 아님). 대표사례만 원문 대조.
3. Claude 가 판정을 파서 개선으로 반영 → 해당 패턴 기업의 `rebuild_target_track1.status`
   를 리셋(`'pending'`) → 파싱 루프가 다음 사이클에 자동 재처리.
4. 1~3 반복(≤3라운드). 잔여 = 영구결측 인정 or 기업별 개별처리.

> **CLAUDE.md 필수 절차**: 파서 개선 시 `docs/runbook_new_parser_pipeline_integration.md`
> 체크리스트 — `collect_new.py` **두 call site** 배선 + 소급 백필(=여기선 status 리셋 재실행)
> + 검증(Gate B 무영향).

---

## 확정 상태 (탐색으로 검증)

- `std_v2.value_lineage`(JSONB) 존재 — 모델 주석에 "Phase C 패턴루프 작업목록" 명시. **보류큐로 사용**.
- `std_v2.version` 존재, 현재 **version=1 만**(523,768행). swap = version=2 구축.
- 소비계층 version 하드코딩 = `app/data/extended.py:30`, `app/data/shareholder_return.py` **2곳**
  → swap 시 이 둘을 2 로(권장: `app/` 공용 상수 `STD_VERSION` 도입해 한 곳에서 전환).
- `rebuild_target_track1`(79,010행) = `rcept_no,corp_code,corp_cls,fiscal_year,fiscal_period,
  file_path,status,processed_at` → **재개·재실행 제어 컬럼 이미 보유**.
- `fact_v2` provenance = `section_kind/mapping_stage/mapping_confidence/unit_source` 있음,
  **`candidates` 컬럼은 없음** → 후보 기록은 `std_v2.value_lineage` 로 **일원화(확정)**.
  fact_v2.candidates 마이그레이션 불필요.

---

## 신규/수정 파일

| 파일 | 내용 | 재사용 |
|---|---|---|
| `scripts/phase_c_rebuild.py` (신규) | rebuild_target_track1 corp 순차 루프, 기업 원자 커밋, `--shard`/재개 | `verify_corp_sequential.py` 구조·`run.process_corp` |
| `com.tjfinance.phasec.plist` (신규) | 연속 백그라운드 잡, 완료 자기해제 | `com.tjfinance.gapfill.plist` |
| `scripts/phase_c_review_digest.py` (신규) | value_lineage → 패턴별 다이제스트 + DART링크 | `reconcile.lineage` 포맷 |
| `app/data/extended.py`·`shareholder_return.py` | swap 시 version=2 (또는 공용상수) | — |
| `scripts/collect_new.py` (수정, swap 후) | 신 파서 배선 **두 call site** | CLAUDE.md 런북 |

std_v2 를 version=2 로 재구축하는 체인(reconcile→build→shares→quarterly→calendar)은 기존
fin2 모듈을 그대로 호출하되 **version 인자만 2** 로 흘린다(신규 로직 최소화).

---

## Phase C 후 마무리 (순서, 핸드오프 §3)
1. shares 재백필(D3) 완결 → valuation_daily(version=2 기준) 재전파.
2. provenance 인덱스 추가(재구축 후 전 행 NULL 아님) — fact_v2 4컬럼 + value_lineage.
3. **Phase D 게이트 통과 후 소비자 swap**(version 1→2): 불변식 SQL 5종 = 0, Gate B
   fail_a=0·value_diff=0·골든셋 5/5, DB손해보험 카나리아(8,564,682,463,043), magnitude 307→0.
4. 야간 잡 복구 — **collect 를 신 파서로 정상동작 확인 후** gapfill/collect enable+load.

---

## 검증 (end-to-end)
1. **파일럿 = 10사**: `python scripts/phase_c_rebuild.py --corps 0:10` foreground → std_v2 version=2
   생성·value_lineage 채워짐·shares_out 비어있지 않음 확인. 통과 시 launchd 잡 등록.
2. **카나리아**: DB손해보험 2023 H1 별도 이익잉여금 재구축값 = `8,564,682,463,043`(≠8.5경).
3. **회귀**: `for f in fin2/tests/test_*.py; do python "$f"; done` (19/21 기존 무관 2건 제외).
4. **Phase D SQL 5종** = 0, `python scripts/gateb_audit.py --no-commit` fail_a=0.
5. 잡 등록 후 `logs/phase_c.*.log` 로 진행률·에러 모니터. 완료 시 plist 자기삭제 확인.

---

## 실행 순서 (승인 후)
1. `scripts/phase_c_rebuild.py` 작성(verify_corp_sequential 구조·rebuild_target_track1 대상·version=2·shares 재백필).
2. `scripts/phase_c_review_digest.py` 작성(value_lineage → 패턴별 다이제스트).
3. **파일럿 10사 foreground** 실행·검증(위 §검증 1~2).
4. `com.tjfinance.phasec.plist` 작성·등록 → 연속 무인 재구축 시작.
5. 배치 패턴루프(≤3라운드): 다이제스트 검토(사용자 시간대) → 파서개선 → status 리셋 재실행.
6. Phase D 게이트 통과 → 소비자 swap(version 1→2) → 야간 잡 복구.
