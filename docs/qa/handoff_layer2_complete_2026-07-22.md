# 핸드오프 — 계층2 전량적재 완료, 계층3 방향 확정 (새 세션 시작점, 2026-07-22)

> **이 문서부터 읽을 것.** 이전 핸드오프 = `docs/qa/handoff_rearchitecture_2026-07-21.md`(보존) ·
> 계층2 적재 결과 = `docs/qa/layer2_full_load_report_2026-07-22.md` ·
> 계층3 설계 = `docs/plans/layer3_design_2026-07-22.md` ·
> 4계층 계획 = `docs/plans/rearchitecture_4layer_2026-07-19.md` · 관련 메모리 = [[rebuild-phase-a3-done]]

---

## 0. 한 줄 요약

**계층2(report_lines) 2015+ 전량적재 완료 — 102,633건 / 6,168만 행 / 28GB / 오류 0.**
적재 중 공시 원문오류 3유형 발견·표시 체계 구축. 계층3 방향 확정(잔액=BS·현금흐름=CF·
SCE보조). **다음 = 계층3 라벨 정규화 카탈로그**(본체) 또는 미해결 ⚠4종 선점 해소.
작업트리 clean, 이번 세션 커밋 12개.

## 1. 이번 세션에 한 일 (커밋 최신순)

- `58bc5f8` 계층3 설계(출처 우선순위 + 불확실성 지도)
- `3e5437d` report_line_corrections 보정 규칙 저장소(스키마만, 미가동)
- `ff033fc` 계층2 전량적재 결과 보고
- `2aa3edd` launchd NAS 제약 실측 기록
- `41d2e6b` 전량적재 인프라(load_report_lines.py) + launchd 잡
- `f6a026d` SCE↔BS 열 granularity 오탐 수정
- `cc9c568` 계층2 이상치 '표시' 체계(값 불변)
- `9fd4169` SCE [B] 항목별 교차검증 + 오기 유형분류
- `872d7c9` SCE col_label 열 오프셋 수정(28.5%→0%)
- `fee7eee` **자본변동표(SCE) 계층2 편입** — 행렬 규약 + 열 라벨 복원
- `7286329` `bba195b` SCE 편입 설계·유래추적

## 2. 계층2 최종 상태 (검증됨)

| 항목 | 값 |
|---|---|
| report_lines | **61,681,304 행 / 28 GB** |
| 적재 결과 | done 102,633 / skip 0 / **error 0** |
| 원문↔DB 완전일치 | 399/400 (기준선 유지) |
| SCE [B] BS 자본총계 교차검증 | 679 PASS / **0 FAIL** |
| section_path well-formed(비-SCE) | 실패 0 (SCE 20건은 검증기 한계, §5) |

**신규 편입 = 자본변동표(SCE).** BS/IS/CF/SCE × 연결/별도 + (본문만, 주석 미적재).
SCE 는 행렬 구조(행=변동사유 × 열=자본구성요소) — col_index=위치·context_fy=NULL·col_label
(헤더 COLSPAN/ROWSPAN 그리드 복원)로 처리. 상세 = `docs/plans/sce_..._2026-07-21.md`.

## 3. 원문오류 표시 체계 (핵심 산출물)

**원칙(사용자·전문가 확정): report_lines.value_won 은 절대 안 고친다. 표시만 남기고 계층3 이
판단.** 원문대조 회귀(399/400) 유지 목적.

- `report_line_anomalies` (5,600건) — 탐지기 파생물, rcept 단위 delete-then-insert
  · SIGN(부호) 1,008 · DIGIT_TRUNC 15 · DIGIT_EXTRA 3 · OTHER/low 4,574
  · ★ **5,600건 100% 기말잔액 행. 변동사유 행엔 0건** → 잔액을 BS 에서 뽑으면 전량 무해화
- `report_line_corrections` (0건, **스키마만**) — 사람/탐지기 **판정** 저장소(재생성 안 됨)
  · scope(filing/table/row) + operation(set_adecimal/negate/replace) = 규칙으로 저장
  · 지문 2종(expect_label+expect_value / expect_row_count)으로 재추출 내구성
  · cross_verdict(제안우세/혼재/원문우세) — SIGN 실측 결과 컬럼
  · **아직 아무것도 안 채웠다. 탐지→corrections 배선·계층3 적용은 미구현.**

### ⚠ 단위오류 71건 — 미해결
표제 '백만원'인데 실제 '원'(HLB제약 등). BS·SCE 동반 부풀어 **교차대조로 안 잡힘**.
현재 어느 테이블에도 없음(탐지경로 부재). 절대임계로 격리후보 가능하나 중간대역 누수.

## 4. 계층3 방향 (확정, `layer3_design_2026-07-22.md`)

**출처 우선순위 — 잔액=BS · 현금흐름=CF · SCE 는 보조:**

| 지표군 | 1차 출처 | 근거 |
|---|---|---|
| 자본 잔액(이익잉여금·자본금·자본총계·지배/비지배) | **BS** | SCE 오류 100% 잔액행 → BS 대체로 무해화 |
| 현금 주주환원(배당·자사주취득·증자) | **CF** | CF·SCE·주석 3중 존재·값 일치(삼성 실측) |
| 자본 내부이동(자기주식 소각·재분류·이익잉여금 처분) | **SCE 보조** | 현금 무이동 → CF 에 없음. SCE 고유 |
| 손익 | **IS** | — |

**SIGN 자동판정 3회 실패 기록**(v1 흑자전환기·v2 다중기초·v3 변동행필터) → 자동판정 포기,
잔액은 BS 쓰고 SIGN 은 격리(held). 대체재 있어 실질손실 0. **다시 매달리지 말 것.**

## 5. 다음 세션 — 무엇을 할지 (사용자 결정 대기)

사용자 우려 명시(2026-07-22): "2015+ 가 그나마 표준화된 구간. 여기서 애매하게 넘어가면
pre-2015·PDF 에서 더 복잡해진다. 조금 진행해보고 확실치 않으면 되돌아온다."

### 옵션 A — 계층3 라벨 정규화 카탈로그 착수 (본체)
label_raw 원문('X.영업이익'·'영업이익(손실)'·전각변이)을 canonical 로 정규화. 이게 계층3
1순위이자 지표를 뽑는 전제. 기존 `account_maps/`·`fin2/extract/statement_titles.py` 재활용
조사부터. BS/IS/CF 핵심 잔액·손익·현금흐름 지표로 프로토타입 → 구 std_v2 대조로 회귀 확인.

### 옵션 B — 미해결 ⚠4종 선점 해소 (되돌아올 지점 먼저 정리)
1. 라벨 정규화 규칙(=A와 겹침)
2. 단위오류 71건 탐지경로 신설
3. 주석 적재(볼륨 5배, 주주환원 완결성)
4. 출처 간 정상 불일치(소급재작성 vs 오류) 유형 재분류 — OTHER/low 4,574 대상

### 옵션 C — 2차 패스(pre-2015 70,374건) 착수
⚠ **A/B 미해결 상태로 넘어가면 악화 확실**(2009~13 `<P>` 구분자·2000~08 미확인 서식).
사용자 우려의 정확한 대상 — **A 또는 B 를 먼저 하는 게 안전.**

**권고: A(라벨 정규화)를 소규모로 시작해 "2015+ 가 정말 표준화됐는지"를 지표 레벨에서
검증. 가정이 깨지면 layer3_design §4 로 복귀.** 확실하면 계속.

## 6. 상태 주의

- ⚠ 야간 잡(gapfill·collect) **중지 유지** — [[nightly-jobs-paused-phase-a3]]. 계층2 적재
  끝났으나 계층3 swap 전까지 구 체인 오염 방지 위해 유지.
- ⚠ 앱은 여전히 구 체인(`fact_v2 → statement_source → std_v2`) 사용 — swap 안 함(계층3 후).
- ⚠ **launchd 로 계층2 적재 잡 못 돌림** — raw_report 가 NAS SMB 마운트라 TCC 차단(EPERM).
  전체 디스크 접근 권한을 GUI 에서 python 에 줘야 함. 재적재 필요시 nohup+caffeinate 로
  (로그인 세션 권한 상속). 상세 = `deploy/launchd/com.tjfinance.layer2load.plist` 헤더.
- ⚠ SCE 원문우세 SIGN 소수(~10건, 온코크로스류)는 사람 원문대조 대기 — 급하지 않음(격리로 무해).
- report_lines 는 대용량이라 `node_role`·`label_raw` 정규식 전량 스캔은 인덱스 없어 느림(주의).
