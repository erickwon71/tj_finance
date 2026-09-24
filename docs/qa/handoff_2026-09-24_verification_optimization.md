# 핸드오프 — verification 캠페인 남은 최적화 (2026-09-24 20:40)

이어받는 세션: tmux `tj_finance` (main checkout, 관리자 DB 계정).
먼저 읽을 것:
- `docs/verification/WORKFLOW.md` — 운영
- `docs/plans/verification_schema_two_worktree_design_2026-09-24.md` — 설계. §10 구현메모, §11 튜닝, §11.1 파일럿 결과
- `docs/PARSING_RULES.md` R167 — 검증 ↔ 재적재 규칙

## 0. 현재 상태 (이 문서 작성 시점)

| 항목 | 값 |
|---|---|
| 러너 | tmux 세션 `verify`(camp_run 워크트리)에서 가동 중. 최신 코드로 15:58 에 재가동했고, 스크립트가 갱신되면 회차 사이에 스스로 재실행한다 |
| 회차 | run 17~93 (77회). 24시간 합계 passed 58 · has_issues 28 · error 2(둘 다 파일럿 초기 결함, 수정 완료) |
| 슬롯 | passed 1,688 · has_issues 27 · pending 92,861 · 완료 회사 30사 · 시총 상위200 슬롯 1,688/8,143 |
| 이슈 | open 110 · reopened 7 · closed 38 — **수정 워크트리가 아직 한 건도 처리하지 않음** |
| 예산(kv) | `pace_mode=on`, `max_5h_pct=70`, `reserve_7d_pct=40`, `safety_7d_pct=5`, `slots_per_window=60`(안전장치) |
| 계정 | 주간 약 64%(리셋 9/29 13:00). 주간 상한 = 100−40×남은비율−5 → 지금 약 67%. 곧 러너가 쉬기 시작하고, 상한이 오르는 대로 조금씩 진행한다 |
| 디스크 | DB 142 GB · verification 39 MB · 여유 129.8 GB |

확인 명령:

```bash
cd /Users/taejin/Project/tj_finance && .venv/bin/python scripts/vq.py status
```

```bash
cd /Users/taejin/Project/tj_finance && .venv/bin/python scripts/vq.py runner budget
```

```bash
tmux attach -t verify
```

## 1. 실측 부하 구조 (run 17~, 75회)

| 구분 | 회차 | 평균 턴 | 분 | 필링 | 대조 행 | API 환산 |
|---|---|---|---|---|---|---|
| light(<40턴) | 32 | 30 | 2.8 | 1.4 | 591 | $1.09 |
| mid | 35 | 50 | 5.1 | 1.8 | 1,109 | $1.93 |
| heavy(≥70턴) | 8 | 83 | 8.3 | 2.8 | 1,552 | $3.43 |

- 턴 수는 대조 행 수와 상관이 있다(r=0.47). heavy 는 원본과 내용이 다른 정정본이 여러 건이거나, 금융업처럼 SCE 가 큰 슬롯이다.
- 계정 사용률: 주간 회당 약 0.13%p, 5h 회당 약 1.6%p(같은 계정 대화 세션분 포함 — 상한값).
- 비용의 대부분은 모델이 **수백 행을 한 줄씩 비교하는 시간**이다. 준비(`show`·CSV 생성)는 30초~1분이다.

## 2. 남은 최적화 후보 (효과 큰 순)

### ① 기계 대조 + 모델은 불일치만 웹뷰로 확인 — ★사용자 판단 필요(검증 방식 변경)
- 현재 방식: 모델이 Chrome JS 로 원문 표를 TSV 로 뽑고, CSV 와 행 단위로 직접 비교한다.
- 제안:
  - `vq.py compare <rcept>` 가 DART 뷰어 HTML 에서 표를 추출해 DB(`report_lines`)와 자동 비교한다. 웹뷰가 보여주는 것과 같은 원문이다.
    기존 `fin2/extract/html_viewer.py` 가 DART `report/viewer.do` HTML 을 받아 오므로 재사용 후보다.
  - 모델은 불일치 셀만 웹뷰에서 눈으로 확인한다.
- 예상 효과: 턴과 사용량이 절반 이하로 줄고, 하루 60~65 → 100+ 슬롯. 사람 눈의 누락도 기계가 잡는다.
- 주의
  - 표 → scope 매핑과 열 선택(당기/누적/3개월)을 새로 구현하면 파서를 하나 더 만드는 셈이다.
    **파서와 독립적인 단순 규칙**(라벨+값 multiset 비교, 단위 선언 반영)으로 시작하고, 애매하면 불일치로 넘겨 모델이 본다.
  - 사용자가 처음 요구한 것은 "웹뷰로 대조"다. 최종 판정의 근거가 웹뷰 확인이라는 점을 유지하는지 사용자에게 확인할 것.
    판단 요청은 `vq.py ask --category policy ...`(텔레그램 버튼)로 한다.

### ② 이슈 등록 단위 — 연속 결측은 1건 + 행 목록
- 실측: missing_row 68건이 필링 16개·회사 4곳에서 나왔다. 키움증권 2018FY 는 자본조정 등 24건이다.
- 섹션 전체 결측도 셀마다 1건이라 수정 큐가 부풀고, 등록에도 턴을 쓴다.
- 방안
  - `issues` 에 `row_labels text[]`(또는 `evidence` 규약)를 둬서 "같은 원인·같은 표의 연속 결측 = 1건"을 허용한다.
  - 프롬프트와 `vq.py issue add` 를 함께 수정한다.
  - 스키마 변경이므로 러너를 STOP 한 뒤 `admin apply-schema` 를 돌린다.
- 오류 유형 분포(파일럿 이후 신규): missing_row 68 · unclassified 16 · period_misassign 11 · column_misassign 7 · sign_flip 4 · source_defect 4(오등록 정리됨).

### ③ 검증 품질 표본 확대 (Sonnet 유지 판단 근거) — ✅완료(2026-09-24 21시)
- 결과: 6슬롯·필링 11건·4,087행·6,906셀을 `scripts/verification_audit_compare.py` 로 기계 대조했다. 오판 0 → **Sonnet 유지**.
  상세는 설계 §11.2. 아래는 착수 전 메모다.
- 지금까지는 run 28(에이피알 2019H1 별도 BS 48항목) 1건을 직접 원문대조했고, 전부 일치했다.
- 5~10건이 필요하다. 표본 추출은 `vq.py admin audit-sample --pct 2`. 무거운 슬롯, 금융업, 2024+ 서식을 섞는다.
- 오판이 나오면 모델을 Opus 로 올릴지 사용자에게 판단을 요청하고(`vq.py ask`), 설계 §11 의 예산을 다시 계산한다.

### ④ 수정 쪽 병목 — ★사용자 판단 필요(수정 세션 운영)
- open 110 · reopened 7. 수정 워크트리(camp_err_review)는 아직 가동하지 않았다.
- 실결함 패턴 후보(배치 1개 = 패턴 1개):
  - EPS 당기 공란에 전기 값 유입 — period_misassign #52~#55 (00105961 2023FY)
  - SCE 기초자본 행에 기말 값 유입 — period_misassign #56~#58 (01160363 2021FY)
  - 증권업 EPS 열·자본조정 결측 — 키움증권 00296290 2015~2018FY
  - 이관 이슈 reopen — #24 (R160 미적용, 엘에스일렉트릭), #39 (SK텔레콤 SCE 부호), #22·#30·#31 계열
  - #46 금액 없는 소제목 행 누락: 값 결함이 아니다. 반복되면 "이슈로 볼지" 정책 질문 대상이다
  - #51 에이피알 2018H1 CF 라벨 없는 최종행: 원문 결함일 가능성
- 시작 절차: `docs/verification/WORKFLOW.md` §5.
  대화형 세션을 쓰고, 배치 1개 = 세션 1개로 한다.
  검증 러너와 같은 계정 한도를 쓰므로, 수정 세션을 돌리는 동안 러너 예산(주간 예비 40%)이 그 몫이다.

## 3. 알아둘 함정 (오늘 겪은 것)

- **러너 프로세스 찾기**: `pgrep -f verify_runner.sh` 는 감시 스크립트 자신의 명령줄에 걸린다.
  `ps -axo command | grep "^/bin/bash .*verify_runner.sh"` 를 쓴다.
- **스크립트 변경 반영**: 러너는 회차 사이에 스스로 재실행한다(`ps` 에 스크립트가 절대경로로 보이면 재실행된 것).
  프롬프트(`docs/verification/verify_prompt.md`)와 `fin2/verification/*.py` 는 매 회차 새로 읽는다.
- **테스트가 실제 텔레그램을 보내지 않게**: `runner._notify`·`decisions.tg` 는 테스트 픽스처에서 막혀 있다.
  새 테스트도 `as_role` 픽스처를 쓸 것.
- **Chrome 표 추출**: iframe URL·location 을 반환하면 확장이 출력을 차단한다(`[BLOCKED: Cookie/query string data]`).
  `#ifrm.contentDocument` 로 표 텍스트만 반환한다(프롬프트에 스니펫 있음).
- **원문 오타**: PARSING_RULES 에 문서화된 패턴이고 DB 가 복원했으면 이슈가 아니다(pass 노트에만 기록).
- 판단 요청은 `vq.py ask`(4개 카테고리, 선택지 2~4개, 권장안 필수)로만 한다. 진행 보고는 텔레그램으로 보내지 않는다.

## 4. 주요 파일

| 역할 | 파일 |
|---|---|
| 스키마·트리거 | `fin2/verification/schema.sql` |
| 로직 | `fin2/verification/ops.py` · `runner.py`(예산·페이스·사용량 프로브) · `decisions.py`(텔레그램 판단) |
| CLI | `scripts/vq.py` |
| 러너 | `scripts/verify_runner.sh` |
| 러너 프롬프트 | `docs/verification/verify_prompt.md` |
| 역할 규칙 | 각 워크트리 `CLAUDE.local.md`(gitignore) |
| 테스트 | `fin2/tests/test_verification_schema.py` · `test_verification_ops.py` · `test_review_csv.py` |
