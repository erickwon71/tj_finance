# Gate B fail_a 버그 #2·#3 수정 계획 (착수용, 2026-08-13)

**상태: 계획만, 미착수.** 전제 조사는 `docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md`(원문대조까지 완료) 참고.
이 문서는 다음 세션이 바로 코드 수정에 들어갈 수 있도록 재현조건·원인가설·수정지점 후보·검증계획을 정리한 것.
**CLAUDE.md 정책상 계획 문서 작성만 하고 실행은 별도 요청 대기.**

---

## 버그 #2 — dividends_paid 부호 오류 (CF 부모-자식 부호상속 누락)

### 재현 케이스
- corp `00120021`(LG), rcept `20260318001025`, 2025FY separate
- 원문(raw XML) 위치: "재무활동으로 인한 현금유출액:"(부모, ACODE=`entity00120021_udf_CF_201885105910658_CashFlowsFromUsedInFinancingActivities`, 텍스트 `(633,061)`=음수 표기) 바로 아래 자식행 "배당금의 지급"(ACODE=`entity00120021_PaymentOfDividendOfudf_CF_201885105910658_CashFlowsFromUsedInFinancingActivities`, 텍스트 `632,379`=**부호기호 없음**, 단위 백만원)
- std_v3: `dividends_paid = +632,379,000,000` (양수로 적재)
- Gate B 원문대조(report_won) = `-632,384,000,000`(음수) — 절대값은 거의 일치(오차 0.001% 이내, 별개 원인일 수 있음, 아래 참고), **부호만 반대**
- fail_a 4건 전부 동일 ratio≈-1.0 패턴(2026-08-12 gateb_audit 결과 기준)

### ★★ 중요 — 블랭킷(전역) 부호수정 절대 금지
- `std_financials_v3.dividends_paid IS NOT NULL` 전체 161,148행 중 **43,590행(27%)이 이미 양수로 저장돼 있고, 그중 다수가 Gate B `status='pass'`**(원문 face 값과 정확히 일치 확인됨 — 표본: `00121507`·`00121534`·`00665676` 등).
  → 이건 **DART 원문 자체가 배당금 지급을 양수로 표기하는 회사가 많다**는 뜻(프로젝트 전역에 "CF outflow=항상 음수" 강제 규약이 없음, 충실성=원문 그대로 캡처가 현재 설계).
  → 따라서 "canon=='cf.dividends_paid' 이고 value>0 이면 무조건 -value로 뒤집는다" 같은 **전역 규칙은 절대 하면 안 됨** — 정상인 43,590행 중 상당수를 오염시킴.
- **진짜 원인은 부호규약이 아니라 "부모-자식 문맥 상속 누락"**: 이 LG 케이스처럼 **부모 라인이 괄호로 음수 표기된 소계/합계이고, 그 직속 자식 라인이 부호기호 없이 양수로만 적힌 경우에 한해서만** 부모의 음수를 상속해야 한다. 부모가 양수거나 이 라인이 독립된(부모 없는) 최상위 항목이면 원문 그대로(현재 동작) 유지.

### 원인 위치 (코드 조사 결과)
- 값 파싱 자체(`parser/common/amount_normalizer.py:parse_amount()`)는 셀 텍스트 문자(괄호/`-`/`△`/`▲`)만 보고 부호를 정하며, **부모-자식 문맥을 전혀 모른다** — 이 함수 단독 수정으로는 해결 불가(문맥 정보가 여기 없음).
- `report_lines` 테이블엔 `depth`, `section_path`, `node_role`, `row_order` 컬럼이 있어 **부모-자식 관계를 복원할 재료는 이미 있음**(그러나 현재 combine 단계가 이걸 부호보정에 안 씀).
- 기존 유사 패턴(참고할 선례): `fin2/layer3/combine.py:576-588` `_LOSS_CANON`/`_loss_signed()` — "'손실' 단독 라벨 + 양수 → 음수" 라벨기반 부호보정 함수. **단, 이건 라벨 텍스트만 보고 부모문맥은 안 봄** — dividends_paid 케이스는 라벨 자체("배당금의 지급")엔 손실 신호가 없어서 이 함수를 그대로 재사용할 수 없고, **부모 depth/값의 부호를 참조하는 새 함수**가 필요.
- 후보 수정 지점: `fin2/layer3/combine.py`의 row-mapping 단계(`_map_rows` 부근, `_loss_signed` 바로 아래) — 같은 rcept·basis·statement 내에서 depth가 1 작은 직전 행(또는 section_path 접두 일치하는 부모)을 찾아, 그 부모 값이 음수이고 현재 행이 양수·부호기호 없음이면 상속.
- 대안(더 좁은 범위): `fin2/extract/report_lines.py`의 라인 생성 단계(`_emit_statement_lines`류)에서 CF 섹션 한정으로 부모-자식 관계를 이미 순회하고 있을 가능성이 있음 — 여기서 처리하는 게 combine.py보다 원본에 더 가까울 수 있음(조사 필요).

### 다음 세션 할 일
1. `00120021` 외 나머지 확정 4건(2026-08-12 gateb_audit 기준, ratio≈-1.0인 나머지 3건) 전부 원문대조해서 "부모 음수+자식 무부호" 패턴이 100% 인지 확인(표본 1건만 봤음).
2. tolerance 오탐 의심 9건(`docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md` ①-2 참고)도 이 조사 김에 원문대조 — 부호버그와 무관한 별개 이슈일 수 있음(`face_audit.py:796-822` tol 로직 쪽).
3. 부모-자식 상속 로직 설계·구현 (범위를 **CF financing 섹션 + 부모가 괄호음수인 경우로 최대한 좁게** — 과설계 방지).
4. 회귀 스윕: 수정 전/후 `dividends_paid` 전체 diff — 43,590건의 기존 양수행 중 몇 건이 바뀌는지 반드시 확인(0건이어야 정상, 바뀌는 게 있으면 그 케이스도 원문대조).
5. `docs/PARSING_RULES.md`에 신규 규칙(R번호) 등재.
6. `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 준수 — 이건 "새 파서 추가"는 아니고 기존 파서 버그수정이지만, **소급 백필이 필요한 변경**이므로 배선점 확인 + 전수 재표준화 스코프 결정.

---

## 버그 #3 — trade_payables 노트 fallback 열(column) 오선택

### 재현 케이스
- corp `00307028`(경남제약), rcept `20250312000888`, 2024FY (consolidated·separate 둘 다)
- BS 본문엔 "매입채무" 단독 라인 없음(정상, "매입채무및기타채무" 통합라인만 존재) → 노트 fallback 발동
- 원문 노트: "16. 매입채무및기타채무" 아래 **두 개의 서로 다른 표**가 있음:
  - (A) 항목별 유동/비유동 분해표(라인 17089 부근): 매입채무 당기합계=**5,557,481천원**
  - (B) **금융부채 만기분석표**(라인 3316 부근): 컬럼=[장부금액, 계약상현금흐름, 1년미만, **1년초과5년미만**], "매입채무및기타채무" 행의 장부금액=8,215,379천원, 1년초과5년미만=**6,000천원**
- std_v3 적재값 = **6,000,000원** = (B)표의 "1년초과5년미만" 컬럼(6,000천원)과 정확히 일치 — **장부금액도, (A)표의 매입채무 합계도 아닌, 완전히 다른 의미의 열을 집어옴**.
- 같은 corp의 다른 분기(2024 H1/Q1/Q3, 2025 전체, 2026 Q1 separate)도 전부 작음(1,000,000 또는 6,000,000원) — 매 분기 (B)표의 "1년초과5년미만" 값이 우연히 다른 것뿐, 동일 매커니즘으로 추정.
- fail_a 21개사·52건이 "near-zero"(db가 report의 2% 미만) — 같은 매커니즘일 가능성 높으나 **경남제약 1건만 확정검증**, 나머지 20개사는 미검증.

### 원인 위치 (코드 조사 결과)
- `fin2/layer3/combine.py`가 note fallback 후보를 모을 때 `WHERE col_index=0`만 취함(즉 "col_index=0가 곧 대표값"이라는 전역 가정) — 이 가정은 "당기/전기 2블록" 표준 노트표엔 맞지만, **(B) 같은 카테고리별 다열(多列) 표(장부금액/현금흐름/만기구간)에는 안 맞음** — 이런 표는애초에 col_index=0가 "장부금액"이어야 정답인데, 실제 적재된 값이 3번째 데이터컬럼(1년초과5년미만)과 일치하는 걸 보면 **`fin2/extract/report_lines.py`의 그리드/헤더 파싱 단계(`_grid_header_split`/`_build_col_labels`/`_grid_body_rows`/`_emit_note_lines`)에서 이 표의 컬럼 오프셋 계산이 잘못돼 col_index 번호 자체가 밀렸을 가능성**이 유력(즉 col_index=0으로 "기록된" 셀이 실제로는 원문의 4번째 데이터 컬럼 값).
- 확인 방법: `report_lines` 테이블에서 `rcept_no='20250312000888' AND label_raw='매입채무및기타채무'`로 모든 `(table_seq, col_index, col_label, value_won)` 행을 뽑아, 어떤 table_seq/col_index가 6,000(천원)을 담고 있고 그게 combine.py 쪽에서 어떤 col_index로 잡히는지 직접 대조해야 함(이번 조사에선 raw XML까지만 갔고 `report_lines` 저장값 자체는 아직 확인 안 함 — **다음 세션 최우선 확인 사항**).

### 다음 세션 할 일
1. **먼저** `report_lines` 테이블에서 이 rcept의 해당 note 표(두 개 다) 실제 저장값을 `(table_seq, row_order, col_index, col_label, value_won)`으로 전부 덤프 — col_index가 원문 순서와 어긋나는지, 아니면 combine.py가 여러 table_seq 중 엉뚱한 것을 고르는지부터 구분.
2. 위 확인에 따라 수정 지점이 갈림:
   - (a) `report_lines` 저장 단계에서 col_index가 이미 틀렸다면 → `fin2/extract/report_lines.py`의 그리드 파싱 수정.
   - (b) `report_lines`엔 맞게 들어갔는데 combine.py가 (B)표(만기분석)를 (A)표(유동/비유동분해) 대신 잘못 고른 거라면 → `fin2/layer3/combine.py`의 note-table 선택 로직(어떤 table_seq/제목을 우선할지) 수정.
3. 나머지 20개사(근접-zero 52건 중 경남제약 제외) 표본 3~5개 추가 원문대조 — 같은 (B)류 "만기분석표" 패턴인지, 아니면 다른 원인이 섞여있는지 확인 후 일반화.
4. 수정 후 회귀: trade_payables 전체 diff(오염 위험 낮음 — 애초에 이 필드는 BS face에 없어 note fallback 타는 소수 케이스만 영향받을 것으로 예상되나, **반드시 실측**).
5. `docs/PARSING_RULES.md` 신규 규칙 등재, `docs/runbook_new_parser_pipeline_integration.md` 체크리스트(배선 2곳 + 소급백필 + 검증) 준수.

---

## 공통 검증 순서 (둘 다 적용)
1. 코드 수정
2. pytest 전체(`pytest tests/ fin2/tests/` — `[[feedback-pytest-scope-raw-report-symlink]]` 참고, 루트 없이 돌리면 NAS 심링크에서 멈춤)
3. 표본 원문대조(수정 전/후 diff가 기대한 케이스만 바뀌는지)
4. 전수 재표준화(`build_std_v3.py --all --year-min 1999`) — 장시간, 사용자 터미널에서 실행 권장(`[[feedback-long-running-commands]]`)
5. Gate B 재검증(`gateb_audit.py --source v3 --fy-min 1999 --recheck`, 5-shard 병렬 방식 재사용 가능 — 이번 세션에서 검증된 방법)
6. fail_a 재집계: 이번 784건 중 대상 필드(dividends_paid·trade_payables)가 몇 건 해소됐는지, 부작용(새로운 fail 발생) 없는지 확인
