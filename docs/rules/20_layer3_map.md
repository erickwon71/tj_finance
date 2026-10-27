# 계층3 — 계층2 를 표준 계정으로 바꾸고 값을 보정하는 규칙

> 이 파일은 `docs/PARSING_RULES.md` 에서 **내용을 바꾸지 않고 옮긴** 절들이다(2026-10-12, `scripts/split_parsing_rules.py`). 규칙 번호·본문은 그대로이고, 분류 기준은 [판정 순서](../plans/parsing_rules_split_2026-10-11.md#분류-기준--판정-순서-사용자-확정-2026-10-11). 새 규칙도 같은 판정 순서로 파일을 고르고 머리에 `적용 계층:` 을 적는다.
> 규칙 문서 수정은 **main 과 camp_err_review 에서만** 한다(사용자 결정 2026-10-11).

계정 매핑·정정본 병합·정규화, 그리고 인쇄된 숫자와 **다른 값**을 만드는 모든 규칙(부호 복원·숫자 교정·빈칸 채움·행 이동·다른 원천 덮어쓰기 — R0-2). 코드가 `fin2/extract` 에 있어도 `as_printed` STEPS 뒤에서 `layer3_cell_corrections` 로만 나간다.

---

## R15. 계층3 `_CURRENT_STRICT`(bs.trade_payables 등) — 비유동 후보를 stage-rank 숏컷보다 먼저 걸러낼 것

> **상태** 유효 · **적용 계층** 3

`fin2/layer3/combine.py::_resolve()`는 canonical별 후보를 모은 뒤, 최고 mapping-stage
(exact > normalized > fuzzy)에서 값이 하나로 모이면 **그 자리에서 즉시 confirm**하고
`_reduce_conflict()`(current-strict/narrow-prefer 등 의미기반 필터)로는 아예 넘어가지
않는다. `_CURRENT_STRICT` = `{bs.trade_receivables, bs.trade_payables,
bs.short_term_debt, bs.current_bonds}`는 "유동 계정이 비유동(장기) 후보를 흡수하면 안
된다"는 필터가 `_reduce_conflict()` 안에 이미 있었지만, **top-stage 값이 이미 하나로
collapse된 경우엔 그 필터가 아예 실행되지 못했다** — 유동 라인이 표준 alias 사전에 없어
whitespace 정규화를 거쳐 `normalized` 단계에 그치고, 그 옆의 비유동 라인이 정확히
alias 사전에 등재돼 `exact` 단계를 얻으면, `exact` 단독값(비유동 값, 종종 훨씬 작음)이
그대로 confirm됐다(경남제약 00307028 2024FY: 유동 매입채무 8,206,288,902원 대신
주석·본문 어디에도 없는 비유동 매입채무 6,000,000원이 적재).

**규칙**:
- `_CURRENT_STRICT` canonical은 stage-rank 비교를 하기 **전에** 먼저 비유동 후보를
  제거한다(제거 후 후보가 하나라도 남을 때만 — 전부 비유동이면 원래 rows 유지, 결측을
  새로 만들지 않음). `_BS_GRAND_TOTAL`(신탁계정 제외) 필터가 이미 이 자리(stage-rank
  이전)에서 하던 것과 같은 패턴.
- 비유동 판정(`_is_noncurrent()`)은 **`label_raw`와 `section_path` 둘 다** 검사한다.
  라벨 텍스트 자체에 "장기"/"비유동"이 없는데 `section_path`가 `부채>비유동부채`인
  케이스가 있다(경남제약처럼 유동/비유동 두 라인의 라벨 문구가 완전히 동일한 경우)
  — `label_raw`만 보면 이 케이스를 놓친다.
- 이 사전필터를 통과하고도 유동 후보끼리 값이 갈리면(진짜 충돌), 그 이후는
  기존 stage-rank/`_reduce_conflict()`/HOLD 경로가 그대로 처리한다 — 이 필터가
  유동-유동 판단을 대신 내리지 않는다.

**검증**: `fin2/tests/test_combine_current_strict.py`(단위, DB 비의존) + 실측 회귀:
`report_lines`에서 같은 (rcept, basis) 안에 유동/비유동 매입채무류 라벨이 공존하는
후보 43,725쌍 전수 재계산 — 수정 전/후 `bs.trade_payables`가 바뀐 6,838쌍 중
5,952쌍은 결측(HOLD)→정상값(순수 커버리지 개선), 884쌍은 잘못된 소액값→report_won과
정확히 일치하는 값으로 교정(fail_a near-zero 52건/21개사가 이 안에 포함, 경남제약·
01061497·00113997·00121941·00670340 등 실측 combine_full() 재확인 — 전부 report_won과
0원 diff), 2쌍은 결측(HOLD)으로 전환(2012년 필링 1건, report_lines 자체의 중복행이
원인 — 이 수정과 무관한 별개 데이터 이슈, HOLD가 안전한 방향이라 미조사 보류). 다른
3개 canonical(trade_receivables/short_term_debt/current_bonds)은 이번 모집단에서
변경 0건(영향 없음 확인). pytest 494 passed(무관 기존결함 1건만, `test_biz_section.py`).

**근거**: `docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md` ③(경남제약 원문대조) ·
`docs/plans/gate_b_fail_a_bugfix_2_3_plan_2026-08-13.md` 버그 #3.

---

## R16. 계층3 `_resolve()` stage-rank 숏컷 — `is.revenue`/`bs.trade_payables` 총계 vs

> **상태** 유효 · **적용 계층** 3
구성요소는 **일반 규칙 금지, curated override만** (R15와 같은 취약점 계열, 다른 처방)

R15와 정확히 같은 근본원인(`_resolve()`가 top-stage 후보가 하나로 collapse되면
`_reduce_conflict()`의 의미기반 필터를 건너뛰고 즉시 confirm)이 `is.revenue`(총계
vs 구성요소)·`bs.trade_payables`(부모 vs 자식)에도 있다. 자식/구성요소 라벨(예:
`수수료수익`·`매입채무및기타채무`)이 공백·번호 없는 "깨끗한" 문자열이라 alias 사전과
글자 그대로 일치해 `exact`를 얻고, 부모/총계 라벨(예: `I. 영업수익`·`매입채무 및
기타유동채무`)은 로마숫자·공백 때문에 정규화를 거쳐야 `normalized`로만 매칭돼
top_vals가 자식 하나로 collapse된다.

**R15와 달리 여기선 일반 규칙(블랭킷)을 적용하면 안 된다** — `report_lines` 전수
실측(계층2, 백필과 무관한 정적 데이터) 결과:
- `is.revenue`: "총계 라벨 있으면 그것 우선" 규칙 → 현재-PASS 303건 회귀 vs 진짜수정
  8건(**38:1**). SBI인베스트먼트(00156910) 등은 총계가 평가성 항목까지 섞인 넓은
  개념이라 **자식이 이미 정답**(report_won과 일치) — 같은 구조(P=총계/F=구성요소)인데
  회사마다 정답이 반대라 구조적 신호만으로는 구별 불가.
- `bs.trade_payables`: "node_role='P'(부모) 있으면 우선" 규칙 → 현재-PASS 11,761건
  회귀 vs 진짜수정 32건(**368:1**). 대다수 회사는 좁은 값(`_NARROW_PREFER` 기존
  설계의도대로)이 이미 정답, 부모가 정답인 건 원문대조로 확인된 5개사뿐.

**규칙**: 대신 `fin2/layer3/industry_profiles.py`의 `CORP_INDUTY_OVERRIDE`·
`NO_REVENUE_CORPS`와 같은 선례를 따라, **원문/report_won 대조로 개별 확인된 회사만**
curated set에 등재하고 stage-rank 이전(R15의 `_CURRENT_STRICT` 사전필터와 같은
자리)에 적용한다.
- `_REVENUE_TOTAL_OVERRIDE_CORPS`(`fin2/layer3/combine.py`): 한국전자홀딩스
  (00159254)·미래에셋벤처투자(00340096) — `is.revenue` 총계가 정답인 회사만.
- `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`(같은 파일): 현대공업(00164502)·
  국일신동(00203847)·코아스(00210856)·케이엔솔(00304076)·IPARK현대산업개발
  (01310269)·**KCC건설(00105466)·조일알미늄(00149239)·다스코(00353878)**(2026-08-14
  확장, 아래 참고) — `bs.trade_payables` 부모가 정답인 회사만.
- 신규 등재는 반드시 원문/report_won 대조로 확인 후 추가 — 구조가 같아 보인다고
  블랭킷 규칙으로 일반화하지 말 것(이 문서의 실측 결과가 그 위험을 이미 증명함).

**확장(2026-08-14)**: `docs/qa/gate_b_faila_residual_triage_2026-08-14.md` §2에서
발견한 3개사를 원문 XBRL 직접대조로 추가 확인 후 등재. 세 회사 모두 **동일한
ACODE 쌍**(부모=`ifrs-full_TradeAndOtherCurrentPayables`, 자식=
`ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers`, 예: KCC건설
`20250320001281.xml`:7693-7716)이라 기존 5개사보다 구조적 근거가 더 명확하다.
검증: 3개사 scoped 백필(`build_std_v3.py --corp <3개사>`, 270행·오류0) + Gate B
scoped 재검증(`gateb_audit.py --corp-file <3개사> --recheck`) — trade_payables
fail_a 10→**0**(전부 pass), **fail_b 0**(다른 기간 회귀 없음). 남은 다스코
(00353878) fail_a 8건은 무관한 `cfo` 필드의 기존 별개 결함.

**스코프 밖**(이 override로 못 고침, 별도 트랙): BS에 결합총계 라인 자체가 없어
매입채무+기타채무가 미합산인 케이스(01412822류, additive 규칙 필요) · Gate B
Track A concept_map이 노트 안 비-매입채무 항목을 오매핑하는 케이스(01090471류,
`face_audit.py` 쪽) · 서로 다른 라벨의 형제 후보 충돌(F-vs-F, 149건) ·
bank/credit_finance 레이어2 커버리지 갭(총계 라인 자체가 `report_lines`에 없음).

**검증**: `fin2/tests/test_combine_curated_overrides.py`(단위, DB 비의존, 등재/
비등재 대조군 포함) + 7개사 scoped 백필(`build_std_v3.py --corp <7개사>
--year-min 1999`, 706행·오류0) + Gate B scoped 재검증(`gateb_audit.py --corp-file
<7개사> --recheck`) — 706행 중 fail_a **0**(수정 전 이 7개사 안에 revenue 8행·
trade_payables 32행 fail_a 존재), DB 전체 `fail_a` 686→646(**-40**, 정확히
8+32와 일치, 다른 corp는 이번 recheck 스코프 밖이라 불변).

**근거**: `docs/qa/gate_b_fail_a_revenue_tradepayables_triage_2026-08-13.md`(원문
대조) · `docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md`
(설계+실측) · `fin2/layer3/combine.py::_resolve()`(`_REVENUE_TOTAL_OVERRIDE_CORPS`/
`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`).

---

## R17. `bs.trade_payables` additive override — curated 키는 **corp 단독이 아니라

> **상태** 유효 · **적용 계층** 3
(corp, fiscal_year, fiscal_period)** (R16의 함정 재발)

R16(§`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`)과 같은 계열의 새 사례 5개사에서,
BS 본문에 결합 총계(P) 라인 자체가 없고 매입채무+형제 유동채무 라인(F) 두 개만
있는 레이아웃을 발견했다. 원문 XBRL 직접대조로 확인: 이 두 라인의 합이
`ifrs-full_TradeAndOtherPayablesUndiscountedCashFlows`[MaturityAxis=1년이내] 또는
`ifrs-full_TradeAndOtherCurrentPayables` — report_lines 텍스트추출로는 안 잡히는
위치의 진짜 XBRL fact와 정확히 일치한다.

**함정 #1(구현 단계에서 실측)**: 형제 라벨(예: '기타지급채무')은 AccountMapper
별칭표를 거쳐 **자기 고유의 canonical**로 매핑된다(`bs.other_current_payables`
등, `bs.trade_payables`가 아니다). `_resolve()`는 canonical별로 이미 분리된
`cands[canonical]`만 보므로, override가 자기 canonical(`rows`)만 뒤지면 형제
라벨을 절대 못 찾아 **한 건도 발동하지 않는다**(최초 구현이 이 상태로 유닛테스트만
통과하고 실제로는 무효였음 — 목이 두 라벨을 인위적으로 같은 canonical 리스트에
넣어놨던 게 원인). 수정: `cands.values()` 전체를 뒤진다.

**함정 #2(더 심각, scoped 백필+Gate B recheck로 실측)**: 위 함정을 고쳐서
override가 실제로 발동하게 만들자, 목표 기간(대부분 FY2025~2026Q1)은 고쳐졌지만
**같은 회사의 과거 모든 분기(2010~2024, LG화학만 100건+)가 새로 fail_b(REVIEW)로
대규모 회귀**했다 — "두 라인 합 = report_won"은 원문대조로 확인한 **그 특정
필링(들)에서만** 성립하고, 같은 회사의 다른 기간엔 성립하지 않는다(실측: LG화학
연결 2010 report_won=1.30조인데 두 라인 합=2.12조). R16의 corp 단독 키를 그대로
가져다 쓴 게 원인 — R16(parent override)은 "이 회사는 항상 부모가 정답"이라는
회사 단위 성격이 실제로 안정적이었지만, 이번 additive 관계는 **회사 단위가 아니라
특정 필링(주로 결합공시 방식이 바뀐 시점 이후)에서만** 성립한다는 게 다르다.

**규칙**: `_TRADE_PAYABLES_ADDITIVE_OVERRIDE`(`fin2/layer3/combine.py`)는 키를
`(corp, fiscal_year, fiscal_period)` 3-튜플로 쓴다 — corp 하나가 늘 이 관계를
만족한다고 가정하지 않는다. `_resolve()`가 `fy`/`period`를 추가로 받아 게이팅한다
(`corp`만 받던 R16 시그니처를 확장, 하위호환: 기본값 `None`이라 미지정 호출은
override 전부 비활성). basis(연결/별도)는 `_resolve()` 호출 자체가 이미
basis별로 분리돼 있어 별도 키가 필요 없다. 신규 등재는 반드시 그 정확한
(corp, fy, period)에서 원문/report_won 대조로 확인 후 추가 — 인접 기간까지
자동으로 넓히지 말 것(이 R17 자체가 그 위험의 실측 증거).

등재: (00356361 LG화학, 2025, FY)·(00356361 LG화학, 2026, Q1)·(00113544 대한화섬,
2025, FY)·(00109310 대동기어, 2025, FY)·(00138446 아가방컴퍼니, 2025, FY)·
(01093007 LS에코에너지, 2025, FY).

**검증**: `fin2/tests/test_combine_curated_overrides.py`(단위, 등재 튜플 발동 +
**같은 corp의 다른 기간은 비발동**하는 회귀재현 방지 테스트 포함) + 5개사 scoped
백필(`build_std_v3.py --corp <5개사> --year-min 1999`, 814행·오류0) + Gate B scoped
재검증(`gateb_audit.py --corp-file <5개사> --recheck`) — fail_a 12→3(trade_payables
9건 전부 pass, 남은 3건은 무관한 controlling_ni 버그), **fail_b 0**(다른 기간
회귀 없음, 함정#2 재발 안 함 확인). DB 전체 `fail_a` 671→662(**-9**, 정확히 일치).

**근거**: `docs/plans/gate_b_faila_trade_payables_additive_design_2026-08-14.md`
(원설계, corp 단독 키 — 이 R17로 교체) · 이 세션 실측(구현 중 함정#1·#2 발견 →
DB 원상복구 → 사용자 승인(회사+기간 범위로 재설계) → period-scoped로 재구현·
재검증) · `fin2/layer3/combine.py::_resolve()`
(`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`) · `fin2/tests/test_combine_curated_overrides.py`.

---

## R18. 계층2 CF `cf.dividends_paid` 부호 — document.xml 인라인 XBRL(Track A) 사실로 대사(오버레이),

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 `fiscal_year ≥ 2024` 필링의 CF `cf.dividends_paid` 부호를 document.xml 인라인 XBRL 사실로 대사한다. `(basis, is_cumulative)` 키에서 텍스트 후보행(`label_raw` 에 "배당"과 "지급"이 둘 다 있는 키워드 부분일치)이 정확히 1개, 사실도 정확히 1개, 둘의 절대값이 1% 이내로 일치할 때만 덮고, 아니면 손대지 않는다(블랭킷 금지). 배당 지급을 양수로 바꾸지 않는다(R232 절에서 추가된 가드, R232 결과를 되돌리는 것도 막는다).
> **판정 예** LG `20260318001025` 실측 재현. fail_a 36건 재실행: 6건 적용(전부 report_won 과 정확 일치, 오탐 0), 30건은 후보 2개 이상 또는 부호가 아닌 자릿수/누락 문제로 스킵.
> **하지 않는 것** `fiscal_year < 2024` 는 파일도 열지 않고 no-op. 후보가 2개 이상이면(모호) 손대지 않는다. 자릿수·누락 문제는 범위 밖(00138729/LG생활건강: 부호는 맞고 report_won 과 0.005% 차이). 다른 CF 계정으로 확장하지 않는다(v1 스코프). AccountMapper(퍼지매칭)를 쓰지 않는다. 인쇄 음수를 양수로 바꾸지 않는다(예 `20251114001409` −84,588 → +84,588 은 오보정이었음).
> **코드** `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_dividends_paid_sign()`(`extract_report_lines()` 가 텍스트추출 직후 호출) · `face_audit.py::read_report_face_xbrl()`(수정 없이 재사용) · 테스트 `fin2/tests/test_report_lines_inline_xbrl_overlay.py`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.
**모호하면 손대지 않음**(설계 예상치보다 실제 적용률은 낮음, 짐작 아닌 실측)

버그#2. CF 본문표의 "배당금의 지급" 셀은 회사별 확장 개념(`entity{corp}_...`)으로
태깅돼 있어 부호를 신뢰할 수 없는데, production 텍스트 추출기
(`fin2/extract/text.py`→`report_lines.py`)가 그 셀 **텍스트**(부호 표시 없는
맨숫자)만 읽어 항상 양수로 저장한다 — 원본 문서 **다른 위치**(자본변동/배당상세
표)에는 같은 사실이 표준 IFRS 개념(`ifrs-full_DividendsPaidClassifiedAsFinancingActivities`
등)+정확한 부호(괄호표시)로 이미 태깅돼 있다. Gate B 감사기(`face_audit.py`)는
그 표준개념 태그를 문서 전체에서 직접 읽어 정답을 얻지만, production 추출기는
전혀 안 읽는다. 상세: `docs/qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md`
(원인 조사) · `docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md`(설계).

**규칙**: `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_dividends_paid_sign()`
— `extract_report_lines()`가 텍스트추출 결과(`lines`)를 다 만든 **직후** 호출한다
(원문을 새로 열지 않음, `read_report_face_xbrl()`이 자체적으로 파일을 다시 읽음).
계층2가 canonical 매핑을 하지 않는다는 R0 원칙([[architecture-report-read-layer2-only]])을
지키기 위해 **AccountMapper(퍼지매칭)를 쓰지 않는다** — 대신:
1. `read_report_face_xbrl()`(face_audit.py, **그대로 재사용, 한 글자도 수정 안 함**)로
   canonical(`map_acode()`, 결정적 조회, 짐작 아님)별 사실 테이블을 만든다.
2. 텍스트 후보행은 `label_raw`에 "배당"+"지급"이 **둘 다** 있는지 **키워드 부분일치**로만
   좁힌다(canonical 추론이 아니라 `text.py`가 이미 곳곳에서 쓰는 것과 같은 구조적
   키워드 필터).
3. `(basis, is_cumulative)` 키에서 텍스트 후보가 **정확히 1개**, 사실도 **정확히
   1개**, 그리고 둘의 절대값이 **1% 이내로 일치**할 때만 override — 아니면 손대지
   않는다(★블랭킷 금지, R16/R17과 같은 원칙).
- `fiscal_year < 2024`는 파일도 안 열고 즉시 no-op(커버리지 절벽 실측,
  findings 문서 §5 — 1999~2023 ACODE/ACONTEXT 보유율 0.0%).
- v1 스코프는 `cf.dividends_paid`만(설계 §4-4) — 다른 CF 계정 확장은 각각 회귀
  diff로 확인 후 별도.

**★설계 예상치(92%)보다 실제 적용률이 훨씬 낮음 — 실측으로 확인, 안전하지만
저수확**: 설계 문서는 ACODE 커버리지(2024+ 92%)만 보고 낙관했으나, 실제
fail_a 36건을 전수 재실행하니 **6건만 적용되고 그 6건 전부 report_won과
정확 일치(오탐 0)** — 나머지 30건은 "모호(후보 2개 이상)" 또는 "애초에 부호가
아니라 자릿수/누락 문제"(예: 00138729/LG생활건강 — 부호는 이미 맞고 report_won과
0.005% 차이인 다른 성격의 결함, 이 R18 범위 밖)로 안전하게 스킵됐다. 무작위
샘플(59건, fy≥2024 CF "배당"+"지급" 후보 전체 모집단 10,554건 중)에서도 오탐
0건. **결론: 이 오버레이는 안전하지만(회귀 없음) 이 버그의 부분적 해결이다** —
잔여는 별도 원인규명 필요(예: 다중 배당 라인 명시적 처리, note_lines 폴백 등).

**검증**: `fin2/tests/test_report_lines_inline_xbrl_overlay.py`(단위6건, LG
`20260318001025` 실측 재현 포함) + pytest 514 passed(무관 기존결함 1건 제외) +
fail_a 36건 전수 재실행(적용 6건·전부 report_won 일치·오탐 0, 미적용 30건은
근거 있는 스킵) + 무작위 표본 59건 오탐 0 + 소급 백필
(`load_report_lines.py --rcept-file <10,554건>`).

**근거**: `docs/qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md` ·
`docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md` ·
`fin2/extract/report_lines_inline_xbrl_overlay.py` ·
`fin2/extract/report_lines.py::extract_report_lines()`.

## R20. 계층3 `_resolve()` stage-rank 숏컷 — 지주회사형 `is.sga`(영업비용 총계 vs

> **상태** 유효 · **적용 계층** 3
판매비와관리비 서브라인), R16과 같은 계열, **새 대상**·**corp+기간 키**로 등재

R19 검증 중 부수발견(한진중공업홀딩스 `is.cogs`)을 조사하다가 R16과 정확히 같은
근본원인(`_resolve()`가 top-stage 후보 하나로 collapse되면 `_reduce_conflict()`의
의미기반 필터를 건너뛰고 즉시 confirm)이 `is.sga`에도 있음을 확인. 지주회사형 손익
계산서가 "Ⅱ.영업비용"(=매출원가류+판매비와관리비 결합 총계, `ACODE=ifrs-full_
CostOfSales`)을 P라인으로 두고 그 아래 "(n)판매비와관리비" 서브라인을 두는 구조에서,
총계 라벨은 alias 사전과 그대로 일치해 `stage=exact`, 서브라인은 번호 접두어 제거가
필요해 `stage=normalized`로만 매칭 — top_vals가 총계(오염값) 하나로 collapse된다.

**R16과 달리 여기선 corp 단독이 아니라 (corp, fy, period) 3-튜플로 등재**(R17
선례) — 같은 corp도 다른 기간엔 이 패턴이 아닌 구조를 가질 수 있음을 실측으로 확인
(예: 한진중공업홀딩스 00163673 FY2010: "1.지분법손실+2.임대사업원가+3.판매비와관리비"
3항목 혼재, §1의 깨끗한 COGS+SGA 2항목 구조가 아님). Phase 0 정밀스캔(exact-normalize
+구조검증, `docs/qa/is_sga_cogs_holdco_phase0_scan_2026-08-15.md`)으로 진짜 대상을
좁혔다 — substring LIKE 최초추정 "166개사"는 보험사 '기타영업비용' 등 무관 잡음이
대부분이었다.

**규칙**: `_SGA_SUBLINE_OVERRIDE_KEYS`(`fin2/layer3/combine.py`, corp+fy+period
3-튜플 685개, 46개사 — `scripts/generate_sga_subline_override_2026-08-15.py`로
재현 가능, Phase 0 target_rows와 1:1) — is.sga stage-rank 이전(R16/R17과 같은
자리)에 `_SGA_SUBLINE_LABELS`(`판매비와관리비`/`기타판매비와관리비`) 매치 서브라인
후보로 rows를 좁힌다. 신규 등재는 반드시 Phase 0와 같은 방식(exact-normalize 후보
좁히기 + 자식 라벨 COGS/SGA 둘 다 존재 + child_sum==parent 항등식)으로 확인 후
추가 — 일반화(블랭킷) 금지는 R16/R17과 동일 근거.

**스코프 밖(이 R20으로 못 고침, 후속 트랙 필요)**:
- `is.cogs` 자체 — 회사마다 증상이 다르다(정확/과소계상/충돌), 서브라인 합산이
  필요한 회사(두산류)는 R17 additive override 패턴 재사용 후보지만 개별 등재 필요.
- Gate B `report_won`(cogs) 개념 문제 — 이 corp군의 XBRL은 `ifrs-full_CostOfSales`를
  총계(COGS+SGA 결합)에 태깅해, `is.cogs`를 아무리 정확히 고쳐도(순수 COGS로) Gate B는
  report_won(총계)과 다르다며 계속 fail_a를 띄운다. 비교 대상 개념이 애초에 다르다 —
  `face_audit.py` 로직 조정 여부는 별도 사용자 결정 필요.
- Phase 0에서 XBRL로 실제 검증 가능한 건 46개사 중 **4개사·15건뿐**(전부
  2024~2026년 필링) — 나머지 42개사는 XBRL 비교 데이터 자체가 없어 `is.sga`가
  오염돼 있어도 Gate B가 원래 못 잡았던 "침묵 오염" 케이스(R20 적용으로 조용히
  해소되지만 Gate B 수치로는 드러나지 않음).

**검증**: `pytest tests/ fin2/tests/` 515 passed(무관 기존 실패 1건 제외,
`fin2/tests/test_biz_section.py::test_lxintl_facility_table_dropped`, `git stash`로
main에서도 동일 확인) + 46개사 scoped 백필(`build_std_v3.py --corp <46개사>`) +
Gate B scoped 재검증(`gateb_audit.py --source v3 --corp-file <46개사> --recheck`) —
sga 필드 fail(fail_a+fail_b) **전체 46개사·전체기간 0건**(회귀 없음), 3개 알려진
케이스(한진중공업홀딩스·두산·대성홀딩스) 전부 원문대조 기대값과 정확히 일치 확인.
잔존 cogs fail_a 10건은 위 "스코프 밖" §3 문제 그대로(예견됨, R20과 무관).

**근거**: `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md`(설계) ·
`docs/qa/is_sga_cogs_holdco_phase0_scan_2026-08-15.md`(Phase 0 정밀스캔) ·
`fin2/layer3/combine.py::_resolve()` (`_SGA_SUBLINE_OVERRIDE_KEYS`/
`_SGA_SUBLINE_LABELS`) · `scripts/generate_sga_subline_override_2026-08-15.py`.

---

## R21. `is.cogs` additive override — 매출원가류 서브라인 **합산**(stage-rank/충돌

> **상태** 유효 · **적용 계층** 3
해소가 아니라 SUM), **raw-label 직접매칭**으로 전역 alias 오염 회피(R16/R20 자매규칙)

R20과 같은 46개사 '영업비용' P라인 구조가 `is.cogs`도 오염시키지만 메커니즘이 다르다.
COGS 서브라인이 **2개 이상**(상품매출원가/제품매출원가/용역매출원가/공사매출원가 등)
공존하는데, 이들은 총계의 상호배타적 구성요소라 **합산**이 정답이지 stage-rank나
`_reduce_conflict()`의 대상이 아니다. 두 실패 양상 확인(`scripts/probe_cogs_
phase2_2026-08-15.py`, 39개사·883행):
- **(a) 충돌**: 서브라인들이 이미 기존 fuzzy alias(예: `상품매출원가`)로 `is.cogs`에
  매핑되지만 서로 다른 값이라 `_resolve()`가 HELD(NULL)로 묻는다(223행/15개사).
- **(b) 침묵드롭**: 서브라인 라벨(`상품및제품매출원가`/`임대매출원가-임대수익원가`/
  `제ㆍ상품매출원가`/`제품및상품매출원가`/`천연가스매출원가`)이 alias 사전에 없어
  `unknown`(conf=0)으로 `_map_rows()`의 신뢰도 게이트(<0.88)에서 `_resolve()`가 보기도
  전에 드롭된다(95행/3개사).

**★일반 alias 추가로 (b)를 고치면 안 되는 이유(전역 위험 실측 확인)**:
`scripts/probe_cogs_alias_global_risk_2026-08-15.py`로 5개 미매핑 라벨의 **전역**
사용처(이 39개사 밖 포함 전체)를 조회한 결과, 2개는 **다른 회사에서 '매출원가'
총계와 형제로 공존**한다 — `상품및제품매출원가`(8개사, 64/162 콤보가 총계와 공존)·
`임대매출원가/임대수익원가`(35개사, 514/548 콤보가 총계와 공존). 이는
`account_maps/is_accounts.py`가 이미 2026-07-18에 `제품매출원가`/`상품매출원가`
세부 alias를 **바로 이 이유로 제거**한 것과 정확히 같은 충돌 패턴(총계+세부 동시
alias → conflict-hold 회귀) — 일반 alias로 추가하면 00109286·00787376 등 이 트랙과
무관한 회사에 새 회귀를 유발한다. (나머지 3개 라벨은 전역 충돌 0건으로 안전하지만,
단일 메커니즘 유지를 위해 이들도 같은 방식으로 처리한다.)

**규칙**: `_COGS_ADDITIVE_OVERRIDE`(`fin2/layer3/combine.py`, (corp, fy, period,
basis) 4-튜플 319개, 19개사 — R16/R17/R20과 달리 **basis도 키에 포함**한다. 연결/
별도가 같은 corp+기간이라도 COGS 서브라인 구성이 다를 수 있어서다(다른 override는
`_resolve()`가 이미 basis별로 분리 호출돼 불필요했지만, 이 override는 `combine_full()`
레벨에서 동작해 명시적으로 필요). `scripts/generate_cogs_additive_override_
2026-08-15.py`로 재현 가능) — `combine_full()`에서 `_resolve()` 이후, raw
`merged`(`build_merged_lines()` 결과, `_map_rows()`/AccountMapper를 거치지 않음)를
`_cogs_additive_labels()`로 직접 라벨텍스트 매칭해 합산, `col["cogs"]`를 덮어쓴다.
전역 alias 테이블은 전혀 건드리지 않아 이 19개사 밖으로 영향이 전혀 없다.
`_cogs_additive_labels()`는 `_map_rows()`의 H1/Q3 누적셀 dedup 로직을 라벨텍스트
기준으로 그대로 복제한다(같은 interim/cum_seen 알고리즘).

**신뢰성 검증**(생성 시점 항등식과 별개로, 실제 runtime 파이프라인 재검증): 319개
키 전부를 `build_merged_lines()` + `_cogs_additive_labels()`로 재실행해 `len(picked)
== len(want)` 확인 — **불일치 0건**. 70개 다중-rcept(정정) 키의 서브라인 구성도
전부 확인(rcept 간 라벨셋 불일치 0건) — 대표 1개 rcept로 override를 만들어도 안전함을
사전 확인.

**Gate B 재검증 결과의 해석(중요 — REVIEW 신호이지 회귀가 아님)**: scoped 재검증
(19개사) 결과 fail_a(cogs) 14건은 **전부 예견된 것**(R20 §3, Phase 0가 미리 확인한
XBRL Track A가 `ifrs-full_CostOfSales`를 총계에 태깅한 4개사 — 00108940·00117212·
00143527·00163673; 이번에 00143527이 NULL(conflict-hold)→실값으로 바뀌면서 처음
드러남, 새 버그 아님). fail_b(cogs) 196건은 원문 직접대조(2건, 00808022·01412822)로
근본원인 확인: Gate B Track B(`read_report_face_text`)도 **같은 AccountMapper**를
써서 서브라인을 **개별 라인으로만** 읽고 합산 개념이 없다 — 표준화값(정확한 합산,
파이프라인 재실행으로 재검증됨)과 Track B의 개별 서브라인 값이 다른 게 당연하다.
Track B는 unmapped 라벨(예: `상품및제품매출원가`)도 **똑같이** 드롭해 일부는 완전
누락 상태로 비교한다. Gate B 감사기 자체의 알려진 한계(비차단 REVIEW)이지 표준화
데이터 오류가 아니다 — R20 §3와 같은 계열의 "비교대상 개념 불일치" 문제.

**검증**: `pytest tests/ fin2/tests/` 515 passed(무관 기존 실패 1건 제외) + 19개사
scoped 백필(`build_std_v3.py --corp <19개사>`) + Gate B scoped 재검증 — sga 필드
회귀 재확인(46개사 전체 fail 0건, 불변) + cogs 값 5개 샘플(한진중공업홀딩스·두산·
대성홀딩스·00108135 4서브라인 합산·01412822 unknown라벨 포함 합산) 전부 자체 항등식과
정확히 일치.

**근거**: `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md`(설계
Phase 2) · `scripts/probe_cogs_phase2_2026-08-15.py`·`scripts/probe_cogs_unmapped_
labels_2026-08-15.py`·`scripts/probe_cogs_alias_global_risk_2026-08-15.py`(조사) ·
`fin2/layer3/combine.py::combine_full()`/`_cogs_additive_labels()`
(`_COGS_ADDITIVE_OVERRIDE`) · `scripts/generate_cogs_additive_override_2026-08-15.py` ·
`account_maps/is_accounts.py`(2026-07-18 제품/상품매출원가 제거 선례).

### R21 부기 — `_cogs_additive_labels()` 라벨충돌 버그(Phase 3 착수 중 발견·수정, 2026-08-15)

Phase 3(Gate B 비교로직) 착수 전 `00143527 2025 Q1 consolidated` fail_a 1건을 원문대조하다
발견: `_norm_label()`(`fin2/layer3/industry_profiles.py::norm()`)은 라벨을 첫 `(`에서
자른다(`"영업이익(손실)"→"영업이익"`처럼 후행괄호를 벗기려는 의도). 그런데 괄호 뒤에
텍스트가 더 있는 라벨 — `"기타수익(매출액)에 대한 매출원가"`(진짜 COGS 서브라인) — 은
`"기타수익(매출액)"`(매출액 세부내역, 전혀 다른 계정)·`"기타수익"`(별개 손익항목)과 같은
정규화 키로 충돌한다. `_cogs_additive_labels()`는 `picked[label]=value`로 마지막 매칭을
그냥 덮어써서, 어느 쪽이 채택될지 iteration 순서에 좌우되는 취약점이었다.

**전수 스캔**(319개 키): 충돌 노출 31키(00143527 24개·00163673 3개, 3-way 충돌이라
fy/period로 퍼짐). 실제로 틀린 값이 나온 건 **5건** — `00143527 2025 Q1`(fail_a로
드러남) + `00163673 2017FY/2018FY/2018H1/2019Q1`(**전부 2024년 이전이라 XBRL Track A
커버리지가 없어 Gate B가 전혀 못 잡던 침묵오염**, R21 Phase 0가 경고한 "빙산의 일각"이
실제로 여기서 나타났다).

**수정**: `_cogs_additive_labels()`에 라벨충돌 가드 추가(`_is_cogs_labeled()`) — 같은
정규화 키에 라벨 2개 이상이 붙으면 원문 라벨텍스트에 `'매출원가'` 부분문자열을 포함하는
쪽을 신뢰한다(이 override의 want 라벨은 전부 "매출원가류" 개념이라 원칙적으로 항상 성립).
실측 31건 전부 이 규칙 하나로 모호함 없이(그룹당 후보 정확히 1개) 갈렸다. 그런 후보가
없거나 여럿이면(미관측) 기존 동작(마지막 매칭 승) 유지 — 방어적으로만 개입.

**검증**: 수정 후 31건 전부 재실행 → 5건 전부 정답으로 전환(오답 0건 잔존). 319키 전체
`len(picked)==len(want)` 재확인(불일치 0건, 회귀 없음). pytest 515 passed(무관 기존
실패 1건 제외, 불변). 2개사 scoped 백필(`build_std_v3.py --corp 00143527,00163673`) +
19개사 scope Gate B 재검증 — cogs fail_a **14/14 전부 `report_won == cogs+sga` 항등식
정확히 일치**(이전 13/14, 이제 00143527 2025 Q1도 합류) 확인.

**근거**: `scripts/probe_cogs_additive_label_collision_2026-08-15.py`(전수 충돌 스캔) ·
`scripts/probe_cogs_collision_impact_2026-08-15.py`(수정 전/후 대조) ·
`scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py`(Gate B 재검증) ·
`fin2/layer3/combine.py::_cogs_additive_labels()`/`_is_cogs_labeled()`.

---

## R24. 계층3 `combine.py::_map_rows()` — `is.controlling_ni`/`is.noncontrolling_ni`

> **상태** 유효 · **적용 계층** 3
구조기반 후보보강(structural candidate injection), mismap 하위메커니즘 Phase 1

Gate B `controlling_ni` fail_a 그룹A(78건)를 원문대조로 재분류하니 단일 원인이 아니라
최소 3갈래였다(`gateb-controlling-ni-groupa-rootcause-2026-08-15` 메모리): ①라벨오귀속
(mismap, 51건) ②완전미매핑(~24건) ③5dbecac 항등식 안전망 자체 오류(3건). 이 R24는 ①만
다룬다.

**근본원인**: `_map_rows()`가 report_lines 라벨을 AccountMapper로 canonical에 매핑할 때
`section_path`(섹션 구조)를 전혀 안 쓰고 라벨 텍스트만 본다. 원문이 이 가정을 두 방식으로
깨뜨린다 — (a) 지배지분 귀속 행이 상위 라벨을 그대로 재사용(삼성전자: `분기순이익의 귀속`
섹션의 지배지분 행 라벨이 그냥 `분기순이익`, ACODE는 정확히
`ifrs-full_ProfitLossAttributableToOwnersOfParent`) → `is.net_income`으로 오귀속.
(b) fuzzy 매칭이 `지배`/`비지배` 방향을 헷갈림(동성케미컬: `지배지분 당기순이익`이
`is.noncontrolling_ni`로 오귀속). 결과: `is.controlling_ni` 후보풀엔 오답(총포괄손익
섹션 값) 단 1개만 남아 `_resolve()`의 `_NI_ATTRIBUTION_CANON` 분기가 그대로 자동확정 —
5dbecac(2026-08-12)의 항등식 안전망(`_resolve_ni_attribution`)은 `conflicts`에 걸린
경우만 호출되므로 **호출 자체가 안 됨**(5dbecac이 고친 다중후보 오선택과는 다른, 더 앞선
선행조건 실패).

**구현**: 새 선택로직을 만들지 않는다. `_ni_attribution_structural_candidates()`
(`fin2/layer3/combine.py`)를 신설해 `_map_rows()`가 반환 직전에 호출 — 라벨이 아니라
섹션 구조로 지배/비지배 귀속 행을 식별한다: `section_path`에 `귀속`+`순이익` 포함,
`포괄` 미포함(당기순이익 귀속 섹션만, 총포괄손익 귀속 섹션은 명시적으로 배제)인 섹션에서,
라벨에 `비지배`가 든 행이 정확히 1개·안 든 행이 정확히 1개일 때만 발동. 그 값들을
`is.controlling_ni`/`is.noncontrolling_ni` 후보풀에 **추가만**(대체 아님) 하고, 나머지는
이미 검증된(유닛테스트 12개) `_resolve()`→`_resolve_ni_attribution()` 파이프라인이 그대로
처리 — 새 오답을 낼 수 있는 새 코드경로를 만들지 않는다는 뜻. H1/Q3는 `_map_rows()`와
동일한 cumulative-only 컨벤션 적용(중복행으로 섹션모양이 깨지는 것 방지).
`stage="structural"`을 `_STAGE_RANK`에 `fuzzy`와 동률(최하위)로 등록 —
`_top_stage_corroborated()`의 동점처리에서 실제 라벨매칭을 절대 앞지르지 않게 함.

**측정 커버리지**: 읽기전용 사전검증(mismap 51건)에서 구조규칙 단독 32건(63%) 오탐 0건.
실제 `combine_full()`→`_resolve()`→`_resolve_ni_attribution()` 전체 경로(기존 EBT유도·
nci=0·epsilon 폴백까지 함께 작동)로는 그룹A 78건 중 **48건 정답 수정**, 회귀 0(신규NULL
0·제3의 오답 0). 부수효과(범위 밖, 측정만): 같은 규칙이 완전미매핑 24건 중 11건, 안전망
자체오류 3건 중 1건도 부수적으로 회복.

**백필**: `scripts/build_std_v3.py --corp <35개사>`(그룹A 소속 corp, 3,054행, 59초) +
`scripts/gateb_audit.py --source v3 --corp-file <35개사> --recheck`(4,190행 재감사) —
그룹A 78건 중 48건 해소·30건 잔존(Phase 2 범위, 미해결) 확인. "신규 fail_a 3건"으로 보였던
것은 전부 db_won 불변(제 fix와 무관한 사전존재 fail_a — KBI메탈 2025H1=그룹B 부호불일치,
제이스코홀딩스 2건=`AXIS_EXCLUDED_UNMAPPED`, Gate B 리더측 별개 이슈)로 확인, 진짜 회귀
아님. 전체 pytest 517→522 passed(+5 신규, 무관 1건 기존 실패 `test_lxintl_facility_
table_dropped` 그대로).

**남은 범위(Phase 2, 미설계)**: mismap 잔여 19건(섹션명에 `순이익` 없이 라벨에 `귀속`
텍스트만 있는 경우·귀속섹션이 1행뿐인 경우·컴팩트 단일라벨 포맷 등 서로 다른 패턴) ·
완전미매핑 24건 중 13건 · 안전망자체오류 3건 중 2건 · 그룹B(7건, 부호불일치, 무관 별도
메커니즘).

**근거**: 메모리 `gateb-controlling-ni-groupa-rootcause-2026-08-15` ·
`gateb-controlling-ni-mismap-design-2026-08-15` · 설계문서 `docs/plans/
std_v3_controlling_ni_mismap_structural_fix_design_2026-08-15.md` ·
`fin2/layer3/combine.py::_ni_attribution_structural_candidates` ·
`fin2/tests/test_combine_ni.py`.

---

## R29. `fin2/layer3/combine.py` — K-GAAP 구서식 헤드라인 NI `net_income` 결측 복구

> **상태** 유효 · **적용 계층** 3
(재추출 없이 계층3 매핑만, 2026-08-16)

R28 후속트랙 T3(구 "후속트랙 N"). 설계문서
`docs/plans/eps_r28_followup_tracks_design_2026-08-16.md` §4/§6.

**근본원인**: R28이 K-GAAP 구서식(00269852류) 헤드라인 당기순이익 행("ⅩⅢ.당기순이익
(주당경상이익:...) (주당순이익:...)")을 EPS 오판에서 구제해 본류로 정상 전사하게
고쳤지만, 그 라벨은 `account_mapper`가 **거대 병합 텍스트**라 `confidence<0.88`로
탈락시켜 애초에 candidate pool에 못 들어온다(`cands["is.net_income"]` 자체가 비어
있음) — 재추출이 아니라 **계층3 매핑 한 곳만** 고치면 되는 이유. 재측정(설계문서
§4-1): curated 2,205키 population(1,840셀) 중 net_income NULL **1,187셀(64.5%)**,
그중 **1,142셀(96.2%)**이 이미 `report_lines`에 R28 헤드라인 행을 값째로 갖고 있었다.

**구현 — curated 재키잉 + 후보주입**(R16/R17/R20/R21/R23/R24/R27/R28 계열):
- R28 curated 5-튜플 키(rcept_no 기반)를 **`(corp_code, fiscal_year, fiscal_period,
  basis) → [label_raw, ...]`**로 재키잉(1,840그룹, 라벨 최대 2). `_map_rows()`(계층3
  후보 매핑 지점)엔 `rcept_no`가 없고(정본+델타 패치 설계상 의도적) 셀 병합 키가
  `(statement, basis, col_index, section_path, label_raw)`라서 원본 5-튜플을 그대로
  못 쓴다. 재키잉 손실 0(1,840셀과 정확히 일치, rcept 미매칭 0) 실측 확인.
  생성: `scripts/build_ni_recovery_keys_2026-08-16.py` →
  `fin2/extract/data/eps_kgaap_ni_recovery_keys_2026-08-16.json`.
- `_kgaap_headline_ni_candidates(rows, corp, fy, period, basis)` 신설
  (R24 `_ni_attribution_structural_candidates`와 같은 모양) — 재키잉 라벨과 정확히
  일치하는 IS 행만 `is.net_income` 후보로 주입(`stage="structural"`). 대상 canonical은
  **`is.net_income` 하나만** — `is.controlling_ni`는 채우지 않는다(K-GAAP 구서식엔
  지배주주 개념 자체가 없는 경우가 많아, 채우면 "없는 개념을 만드는" 위험).
- `_map_rows()`에 선택 인자 `corp=None, fy=None` 추가(기존 호출자는 무변경 no-op).
  `"IS" in stmt_set` 가드 안에서 **`cands.get("is.net_income")`가 이미 있으면
  주입하지 않는다**(보수적 기본값 — 이 population은 정상경로가 애초에 후보를 못
  만드는 경우가 대부분이라, 다른 경로로 이미 후보가 있다면 그쪽을 신뢰).
- 호출부 3곳(`collect_candidates()`·`combine_full()` 기본경로·basis fallback경로)에
  `corp=corp, fy=fy` 전달.

**단위테스트 6개**(순수·DB 비의존) — `fin2/tests/test_combine_kgaap_ni_recovery_r29.py`:
curated 라벨 주입 확인, corp/fy 없으면 no-op, 라벨 텍스트 불일치 시 미주입(블랭킷
아님), 회사 불일치 시 미주입, 기존 후보 있으면 미주입(보수적 기본값).

**백필**: `build_std_v3.py --corp <286개사> --year-min 1999`(286개사·51,403행·
1,267초). 재추출 아님 — `report_lines` 완전 불변(체크섬 확인).

**검증**(설계문서 §4-8):
- curated population net_income NULL **1,187 → 34**(목표 ≤45 초과 달성).
- `report_lines` 286개사 체크섬 before/after **완전 일치**(계층2 불변, 의도대로).
- std_v3 대상 필드 diff: `net_income` 1,837행 + **`controlling_ni` 1,145행**(전부
  separate basis) 변경. controlling_ni는 T3가 직접 주입하지 않았지만, `net_income`이
  채워지자 `fin2/layer3/build.py:118-126`의 **기존(R29 이전부터 있던) 무조건 규칙**
  ("별도재무제표는 controlling_ni=net_income" — 회계정의) 이 자연히 따라 채운
  부수효과. `git diff`로 R29 변경분이 이 규칙과 무관함을 확인, 표본(00428251
  2003H1 separate) 원문대조로도 확인. 그 외 필드(revenue/total_assets 등) diff 0.
- Gate B: T3 대상 기간(FY1999~2008) 286개사는 gate_status 전량 `pending`(XBRL·Track B
  소스 자체가 이 시대엔 없어 감사 불가 — T4 설계문서 §5-3과 동일 사실) →
  net_income을 몇 건 채우든 fail로 넘어갈 경로가 없어 fail_a 증가 **구조적으로
  불가능**. 전체기간 fail_a 46건은 전부 FY2024~2026(재키잉 데이터가 애초에
  FY1999~2008만 있어 도달 불가 — 데일리 파이프라인 신규수집 소관, R29와 무관 확인).
- `pytest tests/ fin2/tests/` **533 passed**(527 기존 + R29 신규 6, 무관 기존 실패
  1건 `test_biz_section.py::test_lxintl_facility_table_dropped` 불변).

**후속트랙**(미착수, 범위 밖): 잔여 34셀 NULL(대부분 "2-라벨 그룹" — 같은 기간에
헤드라인 NI 행이 2개, 값이 달라 conflict로 보류된 케이스. 결측>오염 원칙대로 정상
동작, 추측하지 않음).

---

## R34. `fin2/layer3/combine.py::_resolve()` — R2 델타패치가 정정본의 표 재렌더링에

> **상태** 유효 · **적용 계층** 3
무력화되던 결함(depth-우선이 section_path 만 다른 정정본 셀을 통째로 무시)

**증상** — P3-1 전수 재감사(2026-08-19) 스냅샷 대비 비교에서 689건 단조성 위반(기존
pass → fail/pending) 발견. 원인규명 결과 그중 30건(6개사)이 이 결함으로 확정됐다(나머지는
무관 — R34 부록C 참고).

**근거(실측, 고려아연 00102858 2023FY 연결)** — `build_merged_lines()` 로 라이브 재실행:

```
label='자산총계' value=12,046,071,311,650 source_rcept=20240311000892(최초등록) amended=False
label='자산총계' value=11,768,590,335,824 source_rcept=20260813001690(2026-08-13 정정) amended=True
```

셀 키(`statement,basis,col_index,section_path,label_raw`)가 R2 가 요구하는 것보다 좁다.
정정본이 표를 재렌더링하며 `section_path`에 래퍼가 한 겹 추가되면(`'자산'` → `'재무상태표
[개요]>자산'`) 두 필링의 "자산총계"가 **다른 셀**로 살아남아, `build_merged_lines()`의
델타패치(R2, "정정이 이긴다")가 발동하지 않는다. 그러면 두 후보가 `_resolve()`에서 같은
canonical(`bs.total_assets`)로 충돌하고, `_reduce_conflict()`의 "얕은 depth 우선"(원래
목적 = 한 필링 안에서 합계가 하위상세항목에 안 밀리게 하는 것)이 **section_path 가 얕은
원본을 정정본보다 이겨버린다** — `_eps_dup()`(0.1% 근사중복→큰 값)는 2.3% 차이라 안
걸린다.

label_raw 완전일치로도 못 잡는 경우가 흔하다 — 정정본이 각주번호까지 같이 바꾼다
(`"(5) 이익잉여금 (주27)"` 원본 vs `"(5) 이익잉여금"` 정정본).

**수정(2026-08-20)** — `_resolve()`가 canonical 별 candidate 를 depth 판정에 넘기기
**전에**, `industry_profiles.norm()`(번호/각주 제거 정규화, 기존 `is.revenue` grand-total
매칭에 이미 쓰던 함수)으로 정규화한 label 이 같고 값이 다른 후보 그룹 중, `amended=True`
(=더 나중 필링에서 patch 된 셀)가 하나라도 있으면 그 라벨의 `amended=False`(base) 후보를
버린다. `amended` 후보가 아예 없으면(=진짜 같은 필링 안의 총계/하위항목 구조 차이) 손대지
않는다 — 기존 depth-우선의 원래 목적은 그대로 유지.

**검증** — 6개사(00102858·00141608·00145437·00243067·00403793·01303029) `build_std_v3.py`
재생성 + `gateb_audit.py --recheck`: 이 결함으로 잡힌 43개 (corp,fy,period,statement_type)
중 31건 pass 전환, fail_a **38→0**. 나머지 12건은 `LABEL_UNMATCHED`/`SOURCE_NOT_TRACK_A`
pending — 이 결함과 무관한 별개 원인(부록C 참고, 별도 트랙). `pytest tests/ fin2/tests/`
576 passed(기존 무관 실패 1건 `test_lxintl_facility_table_dropped` 그대로) — 회귀 없음.
회귀 테스트 = `fin2/tests/test_combine_amended_label_depth.py`(4종).

**미조치 범위** — 이 수정은 코드 전역에 즉시 적용되지만(향후 모든 `build_std_v3` 재생성에
자동 반영), **std_v3 에 이미 저장된 값**은 재생성한 6개사만 갱신했다. 이 패턴이 P3-1의
689건 밖에(즉 이번에 처음 fail 로 드러나지 않고 이미 예전부터 fail 이던 회사에) 잠복해
있을 가능성은 미확인 — 전수 조사 안 함(부록C에 등재).

---

## R39. `fin2/layer3/combine.py::_resolve()` — BS 총계 3종의 라벨-표현 드리프트가

> **상태** 유효 · **적용 계층** 3
정정 전 값을 되살리던 결함(R38 fail_b 52건 후속, P3-1 Track D 패턴A)

**증상** — R38(Track D) 재감사가 새로 드러낸 fail_b 774건을 `fail_tracks[field]=="D"`로
정밀 필터한 진짜 541행(239개사) 중, BS 총계 3종(`bs.total_assets`/`bs.total_liabilities`/
`bs.total_equity`) 684개 필드가 db(std_v3)와 Track D 재파싱 값이 서로 다르게 나왔다. db
쪽이 정정 전(stale) 값을 잔존시키는 패턴이었다.

**근거(실측, 00103130/플레이그램 2017 Q1)**:

| 필링 | 라벨 | 값 |
|---|---|---|
| 원본(`20170515004380`) | "자산총계" | 68,523,148,315(=수정 전 db) |
| [기재정정](`20180322000560`) | "자산" | 68,145,914,314(=원문 검산상 정확한 최신값) |

`account_mapper.map()`은 `"자산총계"→stage=exact`, `"자산"→stage=fuzzy`(둘 다
`bs.total_assets`)로 매핑한다. R34(위)는 `industry_profiles.norm()`으로 라벨을 정규화해
묶은 뒤 `amended=True` 후보가 있으면 `amended=False` 후보를 depth 판정 전에 버리는데,
`norm()`은 번호/각주/공백만 지우고 **단어 자체("총계")는 지우지 않는다** —
`norm("자산총계")≠norm("자산")`이라 이번 케이스는 R34의 그룹핑을 그냥 통과해버린다.
그 결과 `_STAGE_RANK`(exact=3>fuzzy=1) 타이브레이크가 정정으로 갱신된 값이 아니라
정정 전(exact) 값을 채택했다. R34가 고친 건 "표기 잡음(formatting) 드리프트"이고, 이번은
"단어 자체가 바뀌는(wording) 드리프트"라는 게 차이 — R34 문서의 "미조치 범위"가 정직하게
남겨둔 잠복 가능성이 이번에 실측으로 확인된 사례다.

**수정** — `bs.total_assets`/`bs.total_liabilities`/`bs.total_equity` 3개 canonical에
한해, R34의 `by_label` 그룹핑 키를 `norm(label)`이 아니라 **라벨 무시(canonical 전체를
한 그룹)**로 넓혔다. 이 3종은 한 필링·basis 안에 "진짜" 값이 하나뿐이어야 하는 총계라서
"라벨이 달라도 같은 canonical이면 같은 개념"이라는 가정이 안전하다(`_trust_account_
table_seqs` 가드가 이미 같은 전제로 특별취급하는 것과 동일 논리). **순서 안전장치**: 그룹
범위가 넓어지면서 신탁계정의 amended 총계가(라벨이 달라도 이제 같은 그룹에 섞일 수 있어)
실제 재무제표 총계를 오염시킬 위험이 R34 때보다 커져, `trust_seqs` 필터를 `by_label`
그룹핑보다 **먼저** 적용하도록 순서를 바꿨다(원래는 그룹핑 다음이었음).

**검증** — 00103130 2017 Q1 `build_std_v3.py` 재생성 → `total_assets` 68,523,148,315
(정정 전) → 68,145,914,314(정정 후, 원문 일치)로 전환, `gateb_audit.py --recheck
--no-commit` pass 114/fail 0/pending 18(fail_a·fail_b 0). 회귀 테스트 2종 추가
(`fin2/tests/test_combine_amended_label_depth.py`: 라벨-표현 드리프트 재현 + 신탁계정
비오염). `pytest tests/ fin2/tests/` 588 passed(기존 무관 실패 1건
`test_lxintl_facility_table_dropped` 그대로) — 회귀 없음.

**전사 영향범위(사전측정, 2026-08-20)** — std_v3 전체 (corp,fy,period) 151,961건을 BS
전용 경량 스캔(zip 재파싱 없음)한 결과, "BS 총계 3종 candidate 값충돌+amended 후보존재"가
1,058건(218개사) — 이 중 R34가 이미 처리 중인 302건을 빼면 **이번 수정이 실제로 새로
고치는 건 156개사/756건**(total_assets 280·total_equity 266·total_liabilities 210).
**138개사(719건)는 xbrl_zip-only(R38 Track D) 대상과 겹치지만, 18개사(37건)는 완전히
그 밖**(Track A/B 커버리지, fy 2004~2025 전구간) — 이 결함은 Track D/xbrl_zip과 무관한
std_v3 전역 결함이며, 백필 시 이 18개사를 xbrl_zip-only 백필과 별도로 반드시 포함해야
한다.

**미조치 범위** — 코드 수정은 향후 재생성분에 자동 반영되지만, 이미 저장된 std_v3 값은
영향받은 (corp,fy,period,basis)를 `build_std_v3.py`로 별도 소급 재생성해야 한다(156개사/
756건, 대상 목록은 재스캔 필요 — 스캔 스크립트는 세션 스크래치라 repo 미포함, 재현 로직은
[[p3-1-trackd-failb-rootcause-2026-08-20]] 부록A).

---

## R42. `bs.trade_payables` 정정본 하위라인 재구성이 남긴 stale 셀 오채택 — R16 계열의

> **상태** 유효 · **적용 계층** 3
신규 확인 사례(R41 lateral 스캔 후속)

**배경** — R41(위) 의 `trade_payables_additive` lateral 후보 15건을 원문대조하다 발견.
"2-라인 합" 이 아니라 **단일 셀 오채택**이었다 — `_NARROW_PREFER`/
`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`(R16) 와 **근본적으로 같은 트레이드오프의 신규
사례**, 새 버그 메커니즘이 아니다. 설계:
`docs/plans/gateb_trade_payables_stale_subline_r42_2026-08-21.md`.

**메커니즘** — 원본(최초등록본) BS 는 "매입채무 및 기타유동채무"(부모총계) 아래
"단기매입채무" 하위라인을 별도로 보여주는데, 정정본이 하위라인 구성을 바꾸면서(삭제하거나
각주번호만 추가) 같은 라벨의 셀을 다시 쓰지 않는다. **R2 정본 정책대로**(정정이 건드리지
않은 셀은 원본 유지) 그 stale 한 "단기매입채무" 셀이 후보 풀에 그대로 남고, exact-stage
alias 라 `_NARROW_PREFER`의 일반정책과 같은 이유로 정정본의 현재 부모총계보다 먼저
확정돼버린다.

**basis 의존성(신규 발견)** — `_TRADE_PAYABLES_ADDITIVE_OVERRIDE`(R17)는 "basis 는 별도
키 불필요"라 가정했으나, 쏠리드(00364403) 2015Q3 실측으로 이 가정이 깨진다 — 연결은
current 라벨이 정답, 별도는 non-current 라벨이 정답이다. 그래서 R42 의
`_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE` 는 **(corp, fy, period, basis) 4-튜플**로 키를
잡는다(`_resolve()` 에 `basis` 파라미터 신규 추가).

**`_CURRENT_STRICT` 우회 필요** — 일신석재(00146296)처럼 정답이 비유동인 경우, current
라벨(오답)이 후보 풀에 있으면 `_CURRENT_STRICT` 사전필터가 정답(비유동)을 먼저 지워버린다
→ override 는 `rows`(필터 후)가 아니라 `cands[canonical]`(필터 전 원본)에서 직접 검증된
라벨을 찾는다.

**0-값 중복 셀 함정(구현 중 실측 발견, 코스나인 00442455 2021Q3)** — 같은 rcept 안에
목표 라벨이 **두 번**(정상값 1건 + 스퓨리어스 0값 1건) 나타날 수 있다(원인 미상 파서
중복행, R2/정정과 무관) — `len(vals)==1` 판정 전에 0-값을 제외해야 한다
(`_reduce_conflict()`의 shallowest-depth 풀과 같은 관례).

**적용 범위 · 검증** — 14건(00626011 아이텍은 이미 알려진 R23 결함과 동일 corp라 제외) 전부
report_lines 정정 전/후 rcept 비교로 원문 계보 확인(2026-08-21). `build_std_v3.py --corp` +
`gateb_audit.py --recheck` 재실행으로 14건 전부 fail_detail 에서 `bs.trade_payables`
VALUE_DIFF 소멸 확인, 같은 corp 의 다른 전체 기간에 새 fail 0(pre-existing 미등재 사례만
잔존, 회귀 아님). `pytest tests/ fin2/tests/` 597건 통과(기존 무관 실패
`test_lxintl_facility_table_dropped` 1건 그대로, +5 신규).

근거: `fin2/layer3/combine.py::_resolve()`(`_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`) ·
`fin2/tests/test_combine_curated_overrides.py` · 메모리
`gateb-trade-payables-stale-subline-r42-2026-08-21`.

**★2026-08-29 추가(신규 인스턴스, 새 R번호 아님 — 같은 메커니즘)** — trade_payables
클래스B 트리아지([[gateb-trade-payables-45-triage-2026-08-28]])에서 이연제약
(00145598) 2025Q1(연결·별도 둘 다)이 R42 완료(2026-08-21) **이후** 접수된 필링이라
당시 스캔 대상이 아니었을 뿐, 원문대조 결과 정확히 같은 메커니즘으로 확인됨(원본
"매입채무" 7,837,235,184 vs 정정본 결합라벨 "매입채무 및 기타유동채무" 당기
14,467,303,399(연결)/14,421,377,063(별도) — DB 는 원본의 stale 셀을 채택하고
있었음). `_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`에 2줄 추가(레시피 동일, 새 코드
없음). 표본 재백필(`build_std_v3.py --corp 00145598`, 130행 무손실 확인)+재감사
(`--recheck`) → fail_a 1→0, 같은 corp 다른 130행 무변동. DB 전체: trade_payables
fail_a 17→15, face_audit 전체 fail_a 85→83. `pytest tests/ fin2/tests/` 632/633
pass(기존 무관 실패 1건 그대로). 근거 추가: `docs/plans/
gateb_trade_payables_classB_stale_column_investigation_2026-08-29.md` §2 · 메모리
`gateb-trade-payables-classB-two-bugs-2026-08-29`.

---

## R43. `account_mapper.py` 포괄손익 귀속 가드 — '포괄이익'/'포괄손실'(쪼개진 표기) 미포착

> **상태** 유효 · **적용 계층** 3
(NH투자증권 Gate B controlling_ni fail_b 근본원인, 2026-08-25)

**배경** — 옵션 A(R19/버그①) 전수 재감사 직후 pass/pending→fail_b 77건 중 75건이
NH투자증권(00120182) `controlling_ni` 하나에 몰려 발견. `read_report_face_xbrl()`
메인 ACODE 루프·`_ni_attribution_structural_candidates()`(R25) 둘 다 이 회사 표에서
빈 리스트 — XBRL 태깅 자체가 없는 표라 `read_report_face()` → `_supplement_with_text()`
(Track B 텍스트) → `account_mapper.map()` 라벨매핑이 최종값을 결정한다.

**근본원인** — 기존 "포괄손익 귀속 가드"(같은 파일, R24/25 인접 코드)는 문자열
`"포괄손익"`(붙임표기)만 검사했다. NH를 포함한 다수 필터社는 `"지배주주지분포괄이익"`
`"비지배지분포괄손실"`처럼 **"손익"이 아니라 "이익"/"손실"로 쪼개서** 표기 — 이 변형은
가드를 못 넘어 fuzzy 매칭(신뢰도 0.89~0.95)으로 `is.controlling_ni`/`is.noncontrolling_ni`
에 오매핑된다(총포괄이익 귀속 값이 순이익 귀속 자리를 오염 — NH FY2015 실측:
215,832백만 오답 vs 215,070백만 db_won 정답).

**연쇄 메커니즘** — 이 오탐이 `is.controlling_ni`/`is.noncontrolling_ni` 후보를
(틀린 값으로) 먼저 채우면, R35(`_with_ni_attribution_text_fallback()`)의 스킵
게이트("두 개념 다 있으면 스킵")가 오발동해 **정답을 정확히 찾는**
`_ni_attribution_text_candidates()`가 아예 호출되지 않는다 — 그 함수 자체는 처음부터
정답(215,070)을 정확히 반환하고 있었지만 정상 파이프라인에서는 도달 못 하는 코드였다.

**전수검사(과차단 위험 확인)** — SD카드 미러(`/Volumes/dart_data/raw_report`)
283,030개 XML 전체 → 1차 그렙(`"포괄이익"`/`"포괄손실"`) 30,449개 후보 → 실 추출게이트
(`read_report_face_text()`의 "라벨+숫자값 모두 있는 행"만)와 동일 조건으로 병렬(9워커)
정밀 파싱, 5,242건/2,778 filing/오류 0. 그중 `"지배"`+(`"포괄이익"`|`"포괄손실"`, 이미
가드된 `"포괄손익"` 제외)가 현재 `is.controlling_ni`/`is.noncontrolling_ni`로 오매핑된
건수 = **3,273건(254개사/2,778 filing)** — 증권사(삼성증권·대신증권·미래에셋증권·
교보증권·DB증권 등)뿐 아니라 일반 상장사(고려아연·LS·금호석유화학·DL·대한제강 등)까지
광범위. 전체 5,242건 중 `"순이익"`/`"당기순"`이 함께 들어간 하이브리드 라벨은 **0건**
— 가드 확장이 정답을 잘못 차단할 위험 없음을 확인 후 적용.

**현재 실 DB(Gate B) 영향 범위** — 254개사 중 실제로 `fail_b`로 잡히던 건 73건(대부분
NH)뿐 — 나머지 대다수는 Track A(XBRL)가 이 개념을 이미 커버해 Track B 텍스트 폴백
자체가 발동 안 되는 구조라 "잠재적/휴면" 오염이었다(당장 틀린 값은 안 나오지만 XBRL
태깅이 불완전한 새 filing 이 들어오면 같은 패턴으로 재발 가능).

**구현** — 가드 조건을 `"포괄손익"` 단독에서 `"포괄손익" or "포괄이익" or "포괄손실"`
(모두 `"지배"` 동반, IS 한정)로 확장. 새 분류 로직을 만들지 않고 기존 가드를 넓히기만
함(R24/25 계열과 같은 "무매핑으로 차단, 구조기반 후보보강이 대신 처리" 원칙).
`account_mapper.py` 는 `face_audit.py` 뿐 아니라 `fin2/layer3/combine.py`
(`_map_rows()`, R24)·`fin2/extract/text.py`·`fin2/extract/report_lines.py` 등
**실 DB 표준화 파이프라인에서도 공유**되므로, 이 수정은 감사도구뿐 아니라 실 데이터
경로의 잠재 리스크도 함께 줄인다.

**검증** — NH투자증권 FY2015 실 코드(몽키패치 아님) 재실행으로 `is.controlling_ni`
215,070백만(=db_won) 정확 복원 확인. `pytest fin2/tests tests/` 610 passed(기존 무관
실패 `test_lxintl_facility_table_dropped` 1건 제외, +3 신규 —
`test_account_mapper_comprehensive_income_guard.py`). `gateb_audit.py --corp 00120182
--recheck`: fail_b 27→0(전부 pass 로 회복), 신규 fail_a 0.

**소급 백필·Gate B 전수 재감사(2026-08-25 완료)** — 254개사 드라이런(트랜잭션
rollback, `fin2.layer3.build.build_corp`를 직접 호출하되 최종 `session.rollback()`
으로 프로덕션 무변경 확인)으로 실 영향 범위를 먼저 좁힘: 48개사·265행만 실제로
값이 바뀜(나머지 206개사는 R24 안전망이 이미 보호 중이었음 — 위 "미확정" 우려가
실측으로 해소됨). 205행은 NULL→값(결측 해소), 22행은 값→다른값(오염값 교정),
35행은 값→NULL(오염 제거, 결측>오염). **22건 전수 원문(report_lines) 대조 검증**
— 항등식 `controlling_ni + noncontrolling_ni = net_income`이 실제 공시값과 정확히
일치함을 다건 확인(윌비스·NC·KB금융 등, KB금융은 net_income 자체의 연쇄 오염까지
같이 교정됨). 검증 후 실 커밋(`build_std_v3.py --corp <254개사>`, 27,846행,
482초) → `gateb_audit.py --source v3 --corp-file <254개사> --recheck`. 전이표:
**fail_a 회귀 0건**(안전 기준 충족), fail_b→pass 22건·fail_b→pending 17건·
pending→pass 2건(개선 합계 41건), pass→pending 50건(오염값 제거로 인한 의도된
결측 전환), **pass→fail_b 1건**(DRB동일 00118266 — 아래 "신규 발견" 항목, R43과는
무관한 별개의 "계속영업" 라벨 자매가드 갭). 스크립트 =
`scripts/census_r43_comprehensive_income_labels_2026-08-25.py`(전수검사)·
`scripts/r43_comprehensive_income_guard_backfill_diff_2026-08-25.py`(드라이런+실커밋
겸용, `SessionLocal()` 직접 열어 rollback 가능). 스냅샷 테이블
`std_v3_snap_r43_20260825`·`face_audit_snap_r43_20260825` 존치 중.

근거: `parser/common/account_mapper.py`(라인 191 인접 가드) ·
`fin2/tests/test_account_mapper_comprehensive_income_guard.py` · 메모리
`gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25`.

---

## R44. '계속영업' 귀속 성분 자매가드 — DRB동일(00118266) 부수발견 후속조사

> **상태** 유효 · **적용 계층** 3
(2026-08-25, R43 254개사 Gate B 재감사 중 pass→fail_b 1건에서 시작)

**배경** — `account_mapper.py`의 "지배/비지배 귀속 중단영업 성분 가드"(2026-08-23,
케이엔더블유 00606664)는 `"중단"` 한정어만 검사해 **대칭 케이스인 `"계속영업"`을
놓쳤다**: DRB동일 FY2012 연결 IS에서 `"지배기업의 소유주에 귀속될 계속영업당기순이익"`
(부분값, 18,327,708,908)이 헤드라인 합산(계속+중단, `"지배기업의 소유주에게 귀속되는
당기순이익(손실)"`=29,912,789,124) 대신 `is.controlling_ni`로 채택됐다.

**1단계 수정(구현·검증·커밋됨)** — `account_mapper.py`의 해당 가드 조건을 `"중단"`
단독에서 `"중단" or "계속영업"`(모두 `"지배"`+속성 한정어 동반, IS 한정)으로 확장.
`fin2/tests/test_account_mapper_discontinued_attribution_guard.py`(4건) 신설.
전수검사(SD카드 미러, `"계속영업"` 포함 20,523개 후보 파일 → 실 추출게이트 동일 정밀
파싱 10,155건/436개사, 오류 0): 과차단 위험 사실상 0건(유일한 non-unknown 매치는
병합표 추출결함 1건, 이 가드와 무관 — T2류 기존 함정).

**2단계 조사(구조적 우회 발견, 시도했다 되돌림)** — 위 라벨가드만으로는 DRB동일 값이
전혀 안 바뀜을 실측으로 확인(old-code/new-code 격리 리빌드 diff, 436개사 전체 0건
변화). 원인: `fin2/layer3/combine.py::_ni_attribution_structural_candidates()`가
section_path(구조)만 보고 라벨 텍스트를 무시해 — `"계속영업당기순이익"`이라는
section_path가 `"순이익"`+`"포괄"`부재 필터를 통과, 라벨가드로 막힌 행을 section_path
기반으로 **다시 후보 풀에 채워넣어 무력화**했다. 대칭적으로 `"계속영업"`/`"중단"`도
그 필터에서 배제하는 수정을 시도했으나, **시알홀딩스(00148984) FY2015에서 새 회귀를
유발함을 실측으로 확인하고 되돌렸다**: 그 회사는 section_path만 성분(`"계속영업
당기순이익"`)이고 라벨 자체는 이미 깨끗한 헤드라인 문구(`"지배기업의 소유주에게
귀속되는 당기순이익(손실)"`)라 account_mapper 라벨매칭이 단독으로(성분값임을 못 보고)
그 값을 채택하는데, 이 section이 구조적 후보 풀에 남아있는 덕분에(다른 section_path
`"중단영업 당기순이익"`과 값이 달라 conflict 유발) 그동안 NULL(안전)로 held 됐었다 —
배제하면 유일후보가 되어 오히려 확신에 찬 오값으로 확정된다(NULL→오염, 결측>오염
원칙 위반). 즉 이 필터 하나로는 "라벨은 깨끗한데 section_path만 성분"인 케이스(시알
홀딩스, 안전망 필요)와 "라벨도 section_path도 성분"인 케이스(DRB동일, 안전망이 오히려
헤드라인 후보를 가림)를 구분 못 한다.

**남은 것(다음 세션, 설계 재작업 필요)**:
1. `_ni_attribution_structural_candidates()`의 section_path 필터 자체가 아니라
   `_resolve()`의 단일후보 자동확정 분기(또는 `_resolve_ni_attribution`)에서
   `"계속영업"`/`"중단"` section 유래 후보를 "신뢰 대상에서는 빼되 conflict 유발
   용도로는 유지"하는 식으로 더 정밀하게 재설계해야 함 — 후보 풀 자체를 건드리는
   방식은 위 트레이드오프 때문에 위험.
2. 조사 중 발견한 **별개의 두 결함**(DRB동일 자체를 완전히 못 고치는 잔여 원인,
   범위 밖으로 분리):
   - (c) 맨몸(bare) `"...에게 귀속되는 지분"` 라벨이 `"귀속"` 키워드를 포함해
     bare-지배지분 가드(2026-08-22)의 예외 조건("귀속" 포함 시 가드 미발동)를 타고
     빠져나가 fuzzy(0.907)로 `is.controlling_ni`에 오매핑됨 — 원래 총포괄이익 귀속
     서브라인인데 라벨 자체엔 `"포괄"`이 없어(부모 section_path에만 있음) 기존
     포괄손익 가드(R43)도 못 잡음.
   - (d) `_derive_net_income_from_ebt()`(EBT−tax 앵커)가 IFRS5식으로 중단영업을
     세후 단일라인으로 별도 표시하는 회사(=계속영업세전이익만 EBT로 표기)에서
     "계속영업만의" net_income을 앵커로 써버려 identity 대조 자체가 무의미해짐 —
     중단영업이 있는 회사 전반에 걸친 구조적 한계, DRB동일 국한 아님.
3. 위 2건 모두 **아직 미착수**. DRB동일 자체는 이번 세션 수정으로 "확신에 찬 오값"
   에서 "NULL(REVIEW 필요)"로 후퇴하긴 했으나(1단계 라벨가드 자체는 커밋됐지만
   std_v3 에는 2단계가 되돌려져 실질 효과 없음 — 여전히 fail_b 상태로 남음), 완전
   해결은 위 1~2 항목 설계 완료 후로 이연.

**실측 커밋 범위**: `account_mapper.py` 라벨가드(1단계)만 실제 코드 변경 — 436개사
전체에 대해 old-code/new-code 격리 리빌드 diff **0건**(std_v3 실 영향 없음, 순수
방어적 하드닝). 단 `fin2/audit/face_audit.py`는 `account_mapper.map()`을 직접
호출하는 지점이 있어(736·884·960행) Gate B 감사 정확도에는 잠재적으로 도움이 될 수
있음(미검증) — `face_audit.py`의 구조적 후보 함수(`_ni_attribution_structural_
candidates`, 265행 `_NI_TOTAL_RE`)는 앵커 정규식이 `"계속영업"` 접두 라벨과 애초에
매치 안 돼(`^당?(기|분기|반기)순(이익|손익)`) 이 특정 우회로부터는 구조적으로 이미
안전. `pytest fin2/tests tests/` 615 passed(기존 무관 실패 1건 제외, 순증 +4/-2 =
net +2 신규, `test_account_mapper_discontinued_attribution_guard.py` 4건 신규 +
`test_combine_ni.py` 순증 2건).

근거: `parser/common/account_mapper.py`(중단/계속영업 귀속 성분 가드) ·
`fin2/layer3/combine.py::_ni_attribution_structural_candidates()`(주석만, 로직
불변) · `fin2/tests/test_account_mapper_discontinued_attribution_guard.py` ·
`fin2/tests/test_combine_ni.py` · 스크립트
`scripts/census_continuing_ops_attribution_labels_2026-08-25.py`·
`scripts/continuing_ops_isolated_diff_2026-08-25.py`·
`scripts/verify_continuing_ops_val_to_val_2026-08-25.py` · 메모리
`gateb-continuing-ops-attribution-sibling-guard-2026-08-25`.

---

## R45. `fin2/layer3/combine.py::_resolve_ni_attribution()` — net_income 앵커

> **상태** 유효 · **적용 계층** 3
재설계, DRB동일(00118266) `is.controlling_ni` 근본수정(2026-08-25, R44 후속)

**배경/근본원인** — R44가 남긴 미해결 과제("DRB동일 자체는 여전히 fail_b")를
이어받아 조사한 결과, `cands["is.controlling_ni"]`엔 이미 정답(exact stage,
29,912,789,124)이 들어 있음을 확인했다. 확정을 가로막은 건 `_resolve()`가
아니라 그 다음에 도는 `_resolve_ni_attribution()`의 EBT−tax 폴백 앵커
(`_derive_net_income_from_ebt`)였다: DRB동일의 `"법인세비용차감전순이익
(손실)"` 라인은 **계속영업만의** 세전이익인데(라벨 자체엔 아무 표식도
없음), 앵커 계산이 이를 회사 전체로 착각해 `EBT−tax`가 우연히 "계속영업
성분(controlling)+계속영업 성분(nci)"과 정확히 일치 → identity 매치가
"유일 매치"로 확정되어 확신에 찬 오값(18,327,708,908)이 나왔다.

**설계안 §A(기각)** — `_resolve()`의 `_NI_ATTRIBUTION_CANON` 분기에 "성분
(계속/중단/포괄 마커) vs 비성분" 분리 후 비성분 후보만 stage-rank로 확정하는
안. 436개사 격리 diff로 실측했으나, **00372226**(계속/중단 구분 자체가 없는
회사인데 exact-stage 비성분 후보가 net_income과 4.4십억원 불일치 — 기존
identity 검증이 정상적으로 NULL 보류 중이던 걸 §A가 우회해 확신에 찬 오답을
만듦)이 결정적 반례로 나와 **identity 검증을 우회하는 설계 자체가 안전하지
않음**이 실증되어 기각.

**설계안 §B(채택)** — `_resolve()`는 전혀 건드리지 않는다(기존 identity
검증 100% 보존). 신설 `_derive_net_income_from_continuing_discontinued()`
(`_map_rows()`가 IS 스코프에서 매 호출마다 계산해 `cands["__ni_total_anchor__"]`
로 주입 — DIRECT_MAP에 없는 내부 전용 키라 `_resolve()`를 무해하게 통과)가
"계속영업(류) 총계 + 중단영업(류) 총계"(귀속분리 **전**, section_path IS
None인 회사 전체 합계 라인, account_mapper 우회 직접 스캔)를 합산해 새
net_income 앵커를 만든다. 동의어는 report_lines 전수 census(계속영업/계속
사업/계속기업 3종, 중단영업/중단사업 2종, 로마숫자 접두 다수 — 스크립트
`scripts/census_continuing_total_labels_2026-08-25.py`·
`census_gyesokgiub_2026-08-25.py`)로 확인해 `"계속"`/`"중단"` 단일문자
substring 하나로 전부 포괄한다(enumerated list 안 씀).

`_resolve_ni_attribution()`은 이 §B 앵커가 있으면 **먼저 단독으로 시도**
하고, 매치가 전혀 없을 때만(union 아님, 순차 폴백) EBT−tax(§A)를 시도한다.
§B 앵커 함수 자체에도 두 겹 자체 억제 가드가 있다: (1) section_path IS
None에 계속/중단/포괄 수식어 없는 순수 헤드라인 순이익류 라인이 **따로
존재하고** 그 값이 계속+중단 합과 **다르면** 앵커를 None으로 억제(00401731
2011H1/Q3 반례 — 이 필자는 `"중단영업이익(손실)"`이 H1·Q3에 걸쳐 완전
동일값인 1회성 메모성 수치라 헤드라인에 아예 안 더함), (2) 그 헤드라인
후보가 **2개 이상**(모호)이면 무조건 억제(00103547 2020Q1 반례 — 같은 표에
`"당기순이익"`과 `"분기순이익"`이 서로 다른 값으로 공존하는 원문 자체
모호 케이스, 합이 우연히 하나와 일치한다고 그게 정답이라는 보장 없음).
§A로의 순차 폴백은 00238782 2014Q3(§B 앵커는 있지만 이 필자의 귀속 섹션이
계속영업만 반영해 §B와는 안 맞고 §A와는 정확히 일치하는 반례)에서 필요성이
드러났다 — union이면 DRB동일에서 §A의 스코프오염 매치가 §B의 정답 매치와
경쟁해 다시 모호함(NULL)으로 후퇴함을 실측 확인, 순차 폴백만이 양쪽을 다
안전하게 만족시킨다.

**실측** — 1,440개사(report_lines 전수, IS 스코프 `계속`/`중단` 라벨 보유
corp, 근사치였던 R44의 436개사보다 정밀) 격리 diff(old-code rebuild vs
new-code rebuild, DB 커밋값과 무관): **19행 변경, 7개사, 회귀 0건.** 전부
원문 자체의 회계 항등식(계속+중단=직접보고 헤드라인, 또는 지배+비지배=총계)
으로 개별 검증 완료. 00118266(DRB동일) 2012FY controlling_ni:
18,327,708,908(오답)→**29,912,789,124**(정답) 등 5개사는 최초 216개사 표본
에서, 00238782·00103547 발견 이후의 두 자체 억제 가드는 전체 1,440개사
백필 검증 중 발견·수정했다(두 회사 모두 diff에서 완전히 사라짐 — 구코드와
동일 결과로 안전 복원, 회귀 아님).

**소급 백필** — `build_std_v3.py --corp <1,440개사> --year-min 2000`
4-way 샤딩(오류 0, 213,813행). 최종검증(old-code rollback rebuild vs
재백필 후 DB, 1,440개사 전체): 19행 변경, 신규 이상 0건.

**Gate B 재감사** — `scripts/gateb_audit.py --source v3 --recheck`(값이
실제로 바뀐 7개사, 846행). **fail_a(차단) 신규 회귀 0건.** DRB동일 포함
4행이 face_audit의 독립 리더(raw XBRL 직접 재구현, combine.py와 무관)로
정답 재확인됨 — 원문 항등식에 이은 2차 독립 검증. 2행은 안전하게 pending
(계속+중단 합산 유도값이라 단순 라벨매칭 리더가 증거를 못 찾을 뿐 — 이전엔
필드가 NULL이라 무검증 pass였던 것보다 오히려 정직). **예외 1건**:
01137383 2024Q3은 R45 값(원문 항등식 2건으로 이중검증)과 face_audit 리더
값이 불일치(fail_b) — `face_audit.py::_ni_attribution_structural_candidates()`
가 combine.py 동명함수를 "미러링만 하고 독립 재구현"하는 별도 컴포넌트라
이번 §B 수정이 전혀 반영 안 됨. **별개 컴포넌트 이슈로 분리, 미착수**
(아래 부록 C).

근거: `fin2/layer3/combine.py`(`_derive_net_income_from_continuing_
discontinued()`·`_resolve_ni_attribution()`) · `fin2/tests/test_combine_ni.py`
(9건 신규) · `docs/plans/gateb_r44_resolve_redesign_2026-08-25.md` ·
스크립트 `scripts/census_continuing_total_labels_2026-08-25.py`·
`scripts/census_gyesokgiub_2026-08-25.py` · 메모리
`gateb-r44-resolve-redesign-2026-08-25`. 커밋 `ed4ffa4`(§B 초판)·
`287100e`(§B→§A 순차폴백+헤드라인 모호성 가드)·`87e07c4`/`82fd1cb`/`7719b0a`
(문서).

## R55. `account_maps/bs_accounts.py` — `bs.trade_payables` 결합형 alias의

> **상태** 유효 · **적용 계층** 3
퍼지 포함관계 오매핑 alias 갭 메움, 39개사/339행 해소(2026-08-29)

**배경** — [[gateb-trade-payables-45-triage-2026-08-28]] 클래스C 3건 중
종근당홀딩스(00149354, 지주회사) 2건을 원문 대조하다 발견. 클래스C의 나머지
1건(갤럭시아에스엠)은 원인이 정반대(face_audit acode-라벨 뒤바뀜 오탐, DB는
정답)라 별도 트랙 — 이 R55는 다루지 않는다.

**근본원인** — 종근당홀딩스 별도 BS엔 "매입채무" 라인 자체가 없다(순수 지주회사).
있는 건 "미지급금"·"기타유동채무"뿐인데, `parser/common/account_mapper.py::
_fuzzy_match()`의 Stage3 포함관계 규칙이 `bs.trade_payables`에 등록된 **결합형
alias** `"매입채무및기타유동채무"`/`"매입채무및기타비유동채무"`(2026-07-18 승급분)의
**뒷부분이 그대로 원문 라벨과 문자 그대로 일치**하는 것을 이용해 "매입채무" 부분이
실제로는 없는데도 오매핑한다(포함관계 점수 0.90+len_ratio·0.09 — "매입채무" 토큰
존재 여부는 검사 안 함). "기타유동채무"/"기타비유동채무"는 형제 라벨("미지급금"·
"기타채무"·"기타지급채무")과 달리 `bs_accounts.py`에 단독 alias로 등록돼 있지
않아 Stage1/2를 못 거치고 Stage3까지 흘러갔다.

**파급범위 실측** — `report_lines` 전수 SQL 스캔(같은 필링·basis 안에 진짜
"매입채무" 라벨이 전혀 없는데 `std_financials_v3.trade_payables`가 이 값과 정확히
일치): **339행 · 39개사**. 트리아지의 "2건"은 face_audit이 acode로 report_won을
찾을 수 있어 fail_a로 뜬 것만 잡은 것 — 나머지 337행은 face_audit도 acode를 못
찾아 **Gate B가 못 잡던 잠복 오염**(표본 00132354=쿠쿠홀딩스도 지주회사로 확인,
가설과 부합).

**수정** — `account_maps/bs_accounts.py`에 "기타유동채무"→`bs.other_current_payables`,
"기타비유동채무"→`bs.other_noncurrent_liabilities` exact alias 2줄 추가(둘 다
`std_financials_v3`에 저장 컬럼 없는 흡수용 버킷 — 신규 canonical 도입 없음). Stage1이
Stage3보다 먼저 실행되므로 이 두 alias 등록만으로 결합형 alias의 포함관계 매칭에
영영 도달하지 않는다 — `_fuzzy_match()` 엔진 자체는 불변, 순수 사전 갭 메우기.

**안전성** — 이 두 canonical은 저장 컬럼이 없어 alias 추가가 새로 값을 오염시킬
위험이 없다. 유일한 효과는 `bs.trade_payables` 후보 풀에서 잘못된 후보가 사라지는
것 — 39개사 재백필 결과 339행 중 337행이 정확히 NULL(결측, "결측>오염" 원칙대로
안전한 미확정 처리)로 전환됐고, 나머지 2행(01021949)은 같은 필링의 다른 정당한
후보(비교기간 컬럼의 진짜 결합라벨 후보)로 값 불변 유지 — 정보 손실 없이 오염만
제거됨을 확인.

**실측/검증(39개사 표본)** — 39개사 std_v3 재백필(`build_std_v3.py --corp ...`,
4,228행) → 스냅샷(`gateb_snap_classc_pre_20260829`) 대비 diff로 위 337/2 결과 확인.
39개사 Gate B 재감사(`--corp-file`, `--recheck`) → trade_payables fail_a **0건**
(종근당홀딩스 2건 포함 완전 해소), 신규 회귀 없음. `pytest fin2/tests/ tests/`
632/633 pass(기존 무관 실패 1건, R54와 동일 — `test_lxintl_facility_table_dropped`).

**전수 재백필/재감사(완료, 커밋 `82c501e` 이후)** — `build_std_v3.py --all`
5-shard 병렬(`scripts/run_build_std_v3_parallel.sh`, 신규) 2,546개사·303,887행,
에러 0. 전수 오염 스캔 재실행 결과 339행/39개사 → **2행/1개사**(01021949 — 다른
정당한 후보로 값 유지되는 케이스, §3에서 이미 확인한 무해 잔존)로 감소, 신규
오염 0. `gateb_audit.py --all --recheck` 5-shard 병렬
(`scripts/run_gateb_audit_parallel.sh`) 2,546개사·303,887행 감사, 에러 0 —
DB `face_audit` fail_a **88 → 86**(정확히 2건 해소), trade_payables fail_a
**20 → 18**(클래스B 14 + 기타 3 + 갤럭시아에스엠형 1, 트리아지 예상과 정확히
일치, 신규 fail_a 0). 트랙 종료.

근거: `account_maps/bs_accounts.py`(`bs.other_current_payables`/
`bs.other_noncurrent_liabilities` 항목) ·
`docs/plans/gateb_trade_payables_classC_accountmapper_containment_alias_gap_design_2026-08-29.md` ·
메모리 `gateb-trade-payables-classC-rootcause-2026-08-29`.

---

## R57. `fin2/layer3/combine.py::_resolve()` — `_CURRENT_STRICT` 탈락분을

> **상태** 유효 · **적용 계층** 3
`_NONCURRENT_SIBLING`으로 재라우팅(B1-D1, `net_debt` 회복) — **구현+단위테스트+
전수재감사 완료(회귀 0), 단 net_debt 잔여격차 대부분은 별도 원인(순서4 범위
재검토 필요)**(2026-08-30~31)

**배경** — [[valuation-daily-blockers-rootcaused-2026-08-30]] §2. `net_debt =
short_term_debt + long_term_debt − cash`인데, v3의 `bs.short_term_debt`/
`bs.long_term_debt` FY2024/2025 불일치율이 67.6%/69.6%로 절벽을 이룬다(P1A/lease·
borrowings 분해와는 **무관** — 그 세 컬럼은 이 식에 안 들어감, 실측 확인).

**근본원인** — `_CURRENT_STRICT`(경남제약형 오염 방지 가드, R… 계열)가 `_is_noncurrent()`
로 `section_path='부채>비유동부채'`를 읽고 `bs.short_term_debt` 후보에서 **제외만
하고 짝 canonical로 재라우팅하지 않는다** → 금액이 소실된다. 실측(`00130763` FY2024
연결): 라벨 `차입금`(장기 표기 없음)이 `bs.short_term_debt`에 exact 매핑 → 가드가
제외 → `bs.long_term_debt` 미도달 → `net_debt`가 정확히 101,825,482,368 부족.
std_v2는 XBRL acode(`dart_LongTermBorrowingsGross`)로 만기를 알았지만, v3는 라벨
텍스트만 보고 `section_path`가 가진 같은 신호를 버리고 있었다.

**수정** — `_NONCURRENT_SIBLING = {"bs.short_term_debt": "bs.long_term_debt",
"bs.current_bonds": "bs.bonds"}`를 신설, `_resolve()` 본문 루프 **앞**에 pre-pass로
적용(설계문서는 `_CURRENT_STRICT` 필터 두 자리(`:1749`/`:1607`)에서 인라인 처리를
제안했으나, canonical 순회 순서가 보장되지 않고 `cands`에 없던 키를 순회 도중 추가하면
`RuntimeError`가 나므로 **pre-pass로 구현 방식을 변경** — 순서 무관하게 짝
canonical이 항상 재라우팅된 후보를 보게 됨).

**가드 4가지** (설계문서는 3가지, 구현 중 1가지 추가 발견):
1. 짝 canonical에 이미 후보가 있으면 추가 안 함(이중계상 방지).
2. **(설계문서에 없던 가드, 필수)** `_src`(예: `bs.short_term_debt`)의 후보가
   **전부** 비유동이면 재라우팅 안 함 — 기존 `_is_noncurrent()`의 "current 후보가
   하나도 없으면 그대로 둔다"(MISSING 방지) 안전장치가 이미 있어, 그 경우 그 행은
   **`_src` 자신의 확정값으로도 쓰인다** — 짝 canonical에 사본을 추가하면 회복이
   아니라 **2배**가 된다.
3. `label_raw`에 이미 `장기`/`비유동`이 있으면 추가 안 함(`section_path`만으로
   비유동인 행, 즉 `00130763`형만 대상 — `_is_noncurrent_by_section_only()`).
4. `rule_additive_debt`(`fin2/standardize/rules.py:282`)의 `total_liabilities×1.05`
   이중계상 가드 확인 결과: **v3(combine.py)는 이 규칙을 아예 호출하지 않는다**
   (import 목록에 없음 — v2 전용). v3는 `bs.short_term_debt`/`bs.long_term_debt`를
   합산이 아니라 `_resolve()`의 단일값 판정(충돌 시 보류)으로 다루므로, 재라우팅된
   행은 짝 canonical의 "유일한" 후보가 되어 그대로 확정되거나(단일값) 충돌로 보류될
   뿐 — 별도 이중계상 방어선이 필요 없다는 것을 코드 추적으로 확인.

**실측/검증** — `00130763` FY2024 연결을 `combine()`으로 직접 재계산(DB write 없음,
읽기전용 진단 경로):

| | 수정 전(v3) | 수정 후(v3) | v2(정답) |
|---|---:|---:|---:|
| `short_term_debt` | 113,802,813,293 | 113,802,813,293(불변) | 113,802,813,293 |
| `long_term_debt` | (소실) | **101,825,482,368** | 101,825,482,368 |
| `net_debt` | 36,346,724,254 | **138,172,206,622** | 138,172,206,622 |

수정 후 v3가 v2와 **원 단위까지 정확히 일치**. 단위테스트 5건 신설
(`fin2/tests/test_combine_noncurrent_sibling_reroute.py`) — 정상 재라우팅, 가드1~3
각각의 회귀 케이스. `pytest tests/ fin2/tests/` 639 passed / 1 failed(기존 무관,
`test_lxintl_facility_table_dropped`, biz_section — 이 트랙과 무관).

**★전수재감사 완료(2026-08-30/31)** — `std_financials_v3` 전체 재빌드
(`scripts/run_r57_verification.sh`) 후 Gate B 전수재감사: **pass→fail_a 전이 0**
(사실은 전이 자체가 0건 — `s.gate_status <> c.gate_status`인 행이 v3 전체에서
0건). ★단, 이 결과는 **약한 증거**다 — `face_audit`의 `fail_fields`는
`short_term_debt`/`long_term_debt`/`net_debt`를 **애초에 검사 항목으로 갖고 있지
않다**(실측: 해당 3개 필드가 걸린 fail 0건. `_NONCURRENT_SIBLING`도
`bs.trade_receivables`/`bs.trade_payables`(face_audit가 실제로 감사하는 항목)는
건드리지 않는다 — 그래서 "0 전이"는 "다른 계정을 오염시키지 않았다"는 안전성
확인이지, "net_debt이 좋아졌다"는 증거가 아니다.

**net_debt 자체의 개선폭은 v2/v3 직접 비교로 별도 측정**(설계문서 §2-2 재현):

| fy | both_have | mismatch(수정전, 설계문서) | mismatch(수정후) |
|---:|---:|---:|---:|
| 2024 | 2,714 | 67.6% | **67.0%**(거의 무변화) |
| 2025 | 2,677 | 69.6% | **70.9%**(거의 무변화) |

**표본 재현 케이스(`00130763`)는 DB에 정확히 반영**(`net_debt` 138,172,206,622,
v2와 원 단위 일치, `built_at` 확인됨) — 코드는 의도대로 동작한다. 그런데 FY2024/25
집계 불일치율은 거의 안 움직였다. 원인: 설계문서 §2-3의 표본 60건 분석에서
**원인 A(alias 갭/오매핑)가 원인 B(이 트랙의 대상)보다 압도적으로 크다**고 이미
암시돼 있었고(60건 중 원인 A류 20건+ vs 원인 B류 소수), 이번 실측이 그걸 확정한다
— `mismatch` 중 롱텀뎁트가 **완전히 비어있는** 행은 43~67건뿐, **값은 있는데 다른**
행이 1,637~1,665건으로 압도적이다.

**★새 발견(순서4 착수 전 재검토 필요)**: `lt_present_but_wrong` 표본을 직접
대조하니 alias 매핑 문제만이 아니다 — **v2는 `rule_additive_debt`
(`fin2/standardize/rules.py:282`)로 단기/장기차입금 세부항목(유동성장기부채·
유동성사채 등, `_ST_DEBT_PARTS`/`_LT_DEBT_PARTS`)을 합산하는데, v3(combine.py)는
이 규칙을 아예 호출하지 않고 `bs.short_term_debt`/`bs.long_term_debt`를
`_resolve()`의 단일값 판정(충돌 시 보류)으로만 다룬다** — 한 회사가 차입금을
여러 줄(단기차입금+유동성장기부채 등)로 나눠 공시하면 v2는 다 더하는데 v3는
그중 하나만 취한다. 이건 alias 카탈로그 갭(순서4/B1-D2)과 **별개의 구조적
차이**이고, 표본(`00126380`/`00117337` 등, 자릿수가 다른 수준으로 벌어짐)이
이 가설과 부합한다. B1-D2를 alias 보강만으로 진행하면 이 클래스는 그대로 남을
가능성이 높다 — 착수 전 규모 실측 권고.

근거: `fin2/layer3/combine.py`(`_NONCURRENT_SIBLING`, `_is_noncurrent_by_section_only`,
`_resolve()` pre-pass) · `fin2/tests/test_combine_noncurrent_sibling_reroute.py` ·
`scripts/run_r57_verification.sh` · `fin2/standardize/rules.py:282`(`rule_additive_debt`,
v3 미호출) ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-4(B1-D1) ·
메모리 `valuation-daily-blockers-rootcaused-2026-08-30`.

---

## R58. `fin2/layer3/combine.py::_apply_enrichment()` — 원인 C(v3가 차입금

> **상태** 유효 · **적용 계층** 3
세부항목을 합산하지 않는 구조적 결함) 순서4 시리즈, **step1 "wiring"** 구현
(net_debt-only 합산, DIRECT_MAP 컬럼 자체는 불변) (2026-08-31)

**배경** — [[valuation-daily-blockers-rootcaused-2026-08-30]] §2-6/§2-7,
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-6/§2-7.
R57(원인 B)을 전수재감사까지 마쳤는데도 FY2024/25 `net_debt` v2/v3 불일치율이
67.0%/70.9%로 거의 안 움직였다 — 지배적 원인은 **원인 C**: v2의
`rule_additive_debt`(`fin2/standardize/rules.py:282`)는 단기/장기차입금
세부항목(`bs.current_lt_debt`/`bs.current_bonds_plain`/`bs.current_bonds_conv`/
`bs.bonds`)을 합산하는데, v3(`combine.py`)는 이 규칙을 아예 호출하지 않고
`bs.short_term_debt`/`bs.long_term_debt`를 `_resolve()`의 단일값 판정으로만
다룬다. v3의 라벨 매퍼(`account_maps/bs_accounts.py`)엔 이미 이 개념들의
동등물이 **등록은 돼 있다**(`bs.current_portion_lt_debt`=유동성장기부채/
유동성장기차입금/유동성사채, `bs.current_bond`=유동성회사채/단기사채,
`bs.bond`=사채/장기사채/회사채) — `_resolve()`에서 정상 확정까지 되는데,
`DIRECT_MAP`(`_BS_MAP`)에 목적지가 없어 `col` 조립 루프(`combine()`의
`std_col = DIRECT_MAP.get(canon); if std_col is None: continue`)가 **조용히
버린다**. 순수 배선 누락(orphan canonical) — 새 alias 등록이 전혀 필요 없다.

**측정(2026-08-31, v2 비교가 아니라 v3 자체 `collect_candidates`+`_resolve`를
직접 재실행한 정밀재측정, 방법론은 설계문서 §2-7)** — 이 3개 orphan canonical을
`_resolve()`에 그대로 태워 FY2024/25 mismatch 3,715건을 재계산: **wiring만으로
(alias 추가 없이) 823건(22.2%) 완전 일치 해소 + 736건(19.8%) 개선**. 반례
발견(삼성전자 00126380, §2-7): 원문 BS엔 `단기차입금` 13.17조 한 줄뿐인데
`fact_v2`엔 그 acode 자체가 없고 작은 값(`bs.current_lt_debt`)만 있음 — v2가
XBRL에서 놓친 사례. → **v2=정답 전제는 위험**, 그래서 v2 비교가 아니라 v3
자체 로직으로 재측정했고, 사후 검증도 v2 비교만으로 끝내지 않는다
([[feedback-verify-against-source]]).

**구현 — net_debt 전용 스코프, DIRECT_MAP 컬럼 자체는 절대 안 건드림**:

```python
_V3_ST_DEBT_PARTS = ("bs.short_term_debt", "bs.current_portion_lt_debt", "bs.current_bond")
_V3_LT_DEBT_PARTS = ("bs.long_term_debt", "bs.bond")

def _additive_debt_for_net_debt(canon, col):
    # rule_additive_debt(rules.py:282)의 total_liabilities*1.05 이중계상 가드를
    # v3 canonical 이름으로 그대로 이식. 합이 그 상한을 넘으면 (None, None) —
    # 롤업+세부 이중태깅 의심, 합산 전체를 불신.
    ...
```

`_apply_enrichment()`에서 `rule_derive_net_debt(ctx)` 호출 **직전**에 `ctx.col`의
`short_term_debt`/`long_term_debt`를 이 합산값으로 덮어쓴 뒤 `rule_derive_net_debt`를
호출한다. **이게 안전한 이유**: `_apply_enrichment()` 끝의 copy-back 루프가
`("cash", "capex", "fcf", "net_debt", "depreciation", "amortization", "da_total",
"ebitda")`만 바깥 `col`(영속화되는 std 컬럼)로 복사하고 `short_term_debt`/
`long_term_debt`는 그 목록에 원래부터 없다 — `ctx.col`을 이 함수 안에서
덮어써도 **영속 컬럼엔 절대 전파되지 않는다**. `rule_additive_debt`(v2)를
직접 호출하지 않은 이유도 이것: v2는 그 두 컬럼 자체를 합산값으로 **덮어쓰는**
설계라 검증된 컬럼을 건드리는 리스크가 있지만, v3는 net_debt 계산에만 쓰고
버린다 — 위험이 구조적으로 더 작다.

**단위테스트** 6건 신설(`fin2/tests/test_combine_debt_wiring_net_debt.py`) —
정상 합산, 결측측 None 유지(0 아님), 이중계상 가드(초과/미초과), total_liabilities
없을 때 가드 미작동. `pytest tests/ fin2/tests/` 645 passed / 1 failed(기존 무관,
`test_lxintl_facility_table_dropped`).

**★전수재감사 완료(2026-08-31, `scripts/run_step1_debt_wiring_verification.sh`,
109분 소요)**: face_audit 스냅샷(`face_audit_snap_20260831_step1`) → std_v3
전체 재빌드(5-shard, 2,546개사·303,986행) → Gate B 전수재감사(5-shard) →
**pass→fail_a 전이 0**(회귀 없음). `net_debt` v2/v3 불일치율(`scripts/
measure_net_debt_v2_v3_mismatch.py`): FY2024 67.0%→**56.2%**, FY2025
70.9%→**59.9%**(둘 다 약 11pt 개선, §2-7의 wiring 단독 exact_fix 측정치
22.2%/19.8%와 방향·규모가 일치).

**★원문 대조(3건, `scripts/inspect_net_debt_case.py`)** — v2 비교만으로 끝내지
않는다는 원칙([[feedback-verify-against-source]])대로 face BS(`table_seq=0`)와
직접 대조:
- `00126380`(삼성전자) FY2024연결 — `단기차입금`/`장기차입금`/`사채` 3줄, `사채`
  14,530,000,000이 `bs.bond`로 정상 확정돼 `long_term_debt` 합산에 들어감.
  `net_debt` 재계산이 저장값과 원 단위까지 일치 확인(수식 직접 재현).
- `00115977` FY2024연결 — LT측(`장기차입금`+`사채`→`bs.bond`)이 **v2와 원
  단위까지 정확히 일치**(247,831,892,331). 독립적 교차검증.
- `00102858`/`00115977` 둘 다에서 **새 발견(버그 아님, 안전하게 보수적으로
  동작)**: `bs.current_portion_lt_debt`(`유동성장기부채`/`유동성장기차입금`/
  `유동성사채`)가 서로 다른 3개 개념을 **한 canonical에 합쳐놨다** — 한 회사가
  `유동성장기차입금`과 `유동성사채`를 **별도 줄로 동시에** 공시하면(실측:
  두 사례 다 해당) `_resolve()`가 값 충돌로 HELD 처리해 그 canonical 전체가
  `None`이 된다(가드가 막아서가 아니라 `_resolve()`의 기본 단일값 정책).
  `_additive_debt_for_net_debt`는 `canon.get(c) is not None`만 확인하므로
  이 경우 **조용히 빠지고 안전하게 보수적으로 동작**(이중계상·오류 없음) —
  다만 그만큼 wiring의 실제 회수율은 §2-7의 "3개 canonical 전부 확정" 가정보다
  현실에선 약간 낮다. v2는 XBRL acode로 이 둘을 애초에 별도 canonical
  (`current_lt_debt`/`current_bonds_plain`)로 갖고 있어 이 충돌이 없다 —
  **후속 백로그**: `bs.current_portion_lt_debt`를 v2처럼 2개로 쪼개는 안(§6에
  등재, 지금 범위 아님).

근거: `fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`/
`_additive_debt_for_net_debt`/`_apply_enrichment`) ·
`fin2/tests/test_combine_debt_wiring_net_debt.py` ·
`scripts/measure_net_debt_v2_v3_mismatch.py` ·
`scripts/run_step1_debt_wiring_verification.sh` ·
`account_maps/bs_accounts.py:213-219,260-262`(기존 등록된 orphan alias) ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-6/§2-7.

## R58 순서4-② "alias 3종" (2026-08-31) — `account_maps/bs_accounts.py` +

> **상태** 유효 · **적용 계층** 3
`fin2/layer3/combine.py`, 구현 완료·전수재감사는 후속 갱신

§2-7의 no_orphan(원인A, 1,389건) 라벨 전수집계가 지목한 몸통 3개 라벨군을
등록:

1. `유동차입금(사채포함)`(355건, unknown) → `bs.short_term_debt`.
2. `비유동차입금(사채포함)의유동성대체부분`(185건, unknown) →
   `bs.current_portion_lt_debt`(개념상 `유동성장기부채`와 동일 — "비유동
   차입금(사채포함)"의 1년 내 만기도래분).
3. `전환사채`류(165+건) → **신규 canonical 2개**: `bs.convertible_bond`(비유동,
   `전환사채`) / `bs.current_convertible_bond`(유동, `전환사채(유동)`/
   `유동전환사채`/`유동성전환사채`).

**★설계 각주 1개를 넘어 신규 canonical 2개가 필요했던 이유(실측, 2026-08-31)**
— 메모리/설계문서 초안은 "신규 canonical 1개"로 적었으나, 값 충돌 위험을
직접 실측하니 **반드시 2개**여야 했다: `사채`와 `전환사채`가 같은 필링에
별도 줄로 함께 등장하는 사례가 **231건**, 유동성장기부채류와 유동
전환사채류가 함께 등장하는 사례가 **1,300건**(둘 다 FY2022+ BS, table_seq=0
실측) — 하나의 canonical에 몰아넣으면 `_resolve()`가 두 값을 충돌로 보고
그 canonical 전체를 HELD(NULL) 처리해버려 **회수가 아니라 오히려 손실**이
난다. v2도 같은 이유로 `bonds`/`current_bonds_plain`과 별도로
`current_bonds_conv`를 갖고 있다 — 그 구조를 그대로 재현.

`유동성전환사채`/`유동성교환사채`는 이미 `bs.current_portion_lt_debt`에
fuzzy 0.93으로 우연히 걸려 있었다(§2-7 각주) — `전환사채` 계열 3개를 exact
alias로 등록하면 그 fuzzy 매치를 이기고 새 canonical로 옮겨간다. 이건
버그 수정 보너스이기도 하다: `유동성전환사채`가 `유동성장기부채`와 같은
필링에 동시 등장하면(1,300건 겹침 실측) 종전엔 **`bs.current_portion_lt_debt`
자체가 충돌로 HELD**됐을 것 — 새 canonical로 분리한 뒤로는 그 필링들의
`bs.current_portion_lt_debt`도 이제 깨끗하게 확정될 가능성이 높다(부수 개선,
`유동성교환사채`는 이번엔 손대지 않음 — 순서4-③ 소관).

`fin2/layer3/combine.py`의 `_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`에 두
canonical을 추가해 순서4-①의 net_debt 합산 경로에 그대로 편입(신규 배선
불필요, 튜플에 추가만).

**검증**: 단위테스트 6건 신설(`fin2/tests/
test_combine_debt_wiring_step2_aliases.py`) — 3개 alias 매핑(exact stage
확인) + 신규 canonical 2개 매핑 + `사채`/`전환사채` 동시 등장·
`유동성장기부채`/`유동성전환사채` 동시 등장 각각 충돌 없이 독립 확정되는지
+ 신규 canonical이 합산에 편입되는지. `pytest tests/ fin2/tests/` 651
passed / 1 failed(기존 무관). `AccountMapper.map()` 직접 호출로 대상 10개
라벨(alias 3종 + 전환사채 변형 4개 + 유동성교환사채/교환사채/신주인수권부사채
대조군) 전수 확인 완료.

**★전수재감사 완료(2026-08-31, 107분 소요)**: std_v3 전체 재빌드(2,546개사) →
Gate B 전수재감사 → **pass→fail_a 전이 0**(순서4-①과 정확히 같은 pass/
fail_a/pending 분포 — face_audit이 애초에 이 필드들을 안 보므로 당연한
안전성 확인). `net_debt` v2/v3 불일치율: FY2024 56.2%→**38.4%**, FY2025
59.9%→**48.8%** — 순서4-① 단독 개선폭(11pt대)보다 훨씬 큰 도약, "몸통 3개
라벨군" 가설(§2-7)이 실측으로 확정됨.

**★원문 대조 2건**: `00100601` FY2024연결 — `유동차입금(사채포함)`
27,920,346,589 + `비유동차입금(사채포함)의유동성대체부분` 500,000,000이
합산돼 `net_debt`가 **v2와 원 단위까지 정확히 일치**(42,281,467,274),
persisted `short_term_debt`는 설계대로 27,920,346,589(단일값)로 안전하게
남음. `00103130` FY2024연결 — 흥미로운 부수 관찰: `전환사채`가 label엔
"유동" 표기가 없는데 `section_path='부채>유동부채'`(현재 항목)로 공시됨 —
`bs.convertible_bond`는 `_CURRENT_STRICT`/`_NONCURRENT_SIBLING` 가드가
없어 만기 구분 없이 그대로 합산되지만, **net_debt은 ST/LT 배분과 무관하게
총합만 맞으면 되므로 무해함**을 직접 확인(계산: 원문 5개 부채줄 합계
62,065,151,232 중 아직 미등록인 `교환사채` 3,562,931,149만 제외한
58,502,220,083이 정확히 wired net_debt 계산과 일치) — **이 필링이 정확히
순서4-③이 필요한 이유**(교환사채 아직 미등록)를 실측으로 보여준 사례.

근거: `account_maps/bs_accounts.py`(short_term_debt/current_portion_lt_debt
alias 추가, `bs.convertible_bond`/`bs.current_convertible_bond` 신설) ·
`fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS` 확장) ·
`fin2/tests/test_combine_debt_wiring_step2_aliases.py` ·
`scripts/run_step2_alias_verification.sh` ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-7.

## R58 순서4-③ "나머지 소수 라벨"(신주인수권부사채/교환사채) + 순서4-②의

> **상태** 유효 · **적용 계층** 3
fuzzy 충돌 부작용 일괄 수정 (2026-08-31)

**본편**: `account_maps/bs_accounts.py`에 신규 canonical 4개 등록 — `bs.exchange_bond`
(교환사채, 비유동)/`bs.current_exchange_bond`(교환사채, 유동)/`bs.warrant_bond`
(신주인수권부사채, 비유동)/`bs.current_warrant_bond`(신주인수권부사채, 유동). 전환사채와
같은 이유로 반드시 4개(2쌍) 분리 — 실측 동시등장(FY2022+ BS, table_seq=0): `사채`↔
`교환사채` 35건, `사채`↔`신주인수권부사채` 30건, `전환사채`↔`교환사채` 139건,
`전환사채`↔`신주인수권부사채` **434건**, `교환사채`↔`신주인수권부사채` 37건, 각 계열
자체의 유동/비유동 동시등장 63건/88건. `fin2/layer3/combine.py`의
`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`에 편입.

**★부수 발견 — 순서4-②/③이 만든 새 exact alias들이 서로 텍스트 유사도로 간섭하며
연쇄적 fuzzy 오매핑을 냈다(2026-08-31, alias 카탈로그 전체 스윕으로 발견)**. 새
canonical/alias를 등록할 때마다 그와 한 글자(`유동`/`비유동`/`(유동)`/`(비유동)`)만
다른 반의어 라벨이 fuzzy로 잘못 끌려가는 패턴이 반복됐다:

| 문제 라벨(FY2022+ 실측 건수) | 등록 전 오매핑 | 원인 | 수정 후 정답 |
|---|---|---|---|
| `비유동전환사채`(118)/`비유동성전환사채`(14)/`전환사채(비유동)`(71)/`장기전환사채`(7+) | `bs.current_convertible_bond`(fuzzy) | 순서4-②가 만든 `유동전환사채`류와 한 글자 차이 | `bs.convertible_bond` |
| `사채(유동)`(11+) | `bs.current_convertible_bond`(fuzzy 0.968) | `전환사채(유동)`류와 유사 | `bs.current_bond` |
| `비유동사채`(125)/`비유동성회사채`(8) | `bs.convertible_bond`/`bs.current_bond`(fuzzy) | 등록 전엔 애초에 unknown(0.80 미만), 순서4-② 이후 넘어감 | `bs.bond` |
| `유동사채`(60) | `bs.bond`(fuzzy 0.972) | ★**실측 충돌위험**: `사채`/`장기사채`/`회사채`와 동시등장 **43건** — 방치 시 그 필링들의 `bs.bond` 전체가 `_resolve()` 충돌로 HELD, net_debt 손실 | `bs.current_bond` |
| `비유동성사채`(42) | `bs.current_portion_lt_debt`(fuzzy 0.975) | ★**실측 충돌위험**: 유동성장기부채류와 동시등장 **38건** | `bs.bond` |
| `사채(비유동)`(38) | `bs.convertible_bond`(fuzzy 0.970) | ★실측 충돌위험: 전환사채류와 동시등장 4건 | `bs.bond` |
| `비유동차입금(사채포함)의비유동성부분`(187)/`비유동차입금의비유동성부분`(14) | `bs.current_portion_lt_debt`(fuzzy) | 순서4-②의 `...의유동성대체부분`(반대 개념: 유동 전환 vs 비유동 잔여)과 유사 | `bs.long_term_debt` |
| `비유동차입금의유동성대체부분`(**512건**, `(사채포함)` 없는 축약형) | ★위 항목을 고치는 과정에서 **새로 뒤집힘**(0.956 > 0.940로 역전) | 방금 추가한 `...의비유동성부분` alias가 오히려 이 라벨을 더 가깝게 끌어감(휘프-어-몰) | `bs.current_portion_lt_debt`(exact 재등록으로 고정) |
| `비유동교환사채`/`비유동신주인수권부사채`(순서4-③ 등록 시 선제 차단) | (등록 안 했으면 fuzzy로 반대쪽) | 같은 패턴 선제 인지 | `bs.exchange_bond`/`bs.warrant_bond` |

**중요한 안전성 구분**: 이 표의 "오매핑"은 대부분 **net_debt 총액엔 무해**했다 —
`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`는 둘 다 net_debt 하나로 합산되므로 ST/LT
버킷을 틀려도 총합은 안 변한다(`00103130` 사례, R58 순서4-② 절 참고). **진짜
위험은 같은 canonical 안에서 값이 다른 두 후보가 만나 `_resolve()`가 통째로
HELD시키는 경우뿐**이다 — 위 표에서 ★표시한 3건(유동사채/비유동성사채/
사채(비유동))은 실측으로 그 충돌이 **실제로 발생하는** 필링이 있었기(43/38/4건)
때문에 우선 수정했고, 나머지는 ST/LT 분류 정확도 개선(데이터 품질) 차원에서
같이 정리했다. `차입금및사채`/`단기차입금및유동성장기부채` 류의 **결합(rollup)
라벨**은 원래부터 단일 개념이 아니라 정확한 재배분이 불가능 — 손대지 않고
그대로 둠(fuzzy가 아무 wired canonical에나 떨어져도 net_debt엔 무해).

**검증**: 단위테스트 7건 추가(`fin2/tests/test_combine_debt_wiring_step3_aliases.py`)
— 신규 canonical 4개 매핑 + 4개 사채계열 동시존재 무충돌 + 합산 편입 + 위 표의
반의어 혼동 회귀 3건(exact 재확인) + 실측 충돌 위험 케이스의 `_resolve()` 무충돌
확인. `pytest tests/ fin2/tests/` 658 passed / 1 failed(기존 무관).

**★전수재감사 1차 실행 결과 — pass→fail_a 0(안전)이지만 net_debt은 오히려
악화**(2026-08-31, 106분): FY2024 38.4%→**40.5%**, FY2025 48.8%→**51.2%**.
both_have 증가분(+21/+40)보다 mismatch 증가분(+76/+95)이 훨씬 커서, **기존에
이미 v2와 맞던 행 다수가 새로 틀어졌다**는 신호 — 원인 추적 결과 **R57과
같은 계열의 새 버그**를 발견했다: `bs.convertible_bond`/`bs.bond` 등 4개
canonical의 "무표기(bare)" alias(`전환사채`/`사채` 등)는 만기 불분명 시
**비유동 기본값**으로 등록했는데, 일부 필러가 그 무표기 라벨을 정확히
"유동" 몫 전용으로 쓰면서(`section_path='부채>유동부채'`) **동시에**
`비유동전환사채` 같은 명시적 비유동 라벨을 별도 줄로 공시한다. 그러면 둘 다
같은 canonical에 몰려 `_resolve()`가 충돌로 HELD — R57이 고친 "제외만 하고
회수 안 함"보다 더 나쁘게, **canonical 전체(두 값 다)가 net_debt에서
소실**된다. 실측 재현(`00172079` FY2024연결): `전환사채` 19,550,499,832
(section=유동부채) + `비유동전환사채` 1,794,834,765(section=비유동부채) →
수정 전엔 `bs.convertible_bond` 충돌로 21,345,334,597 전액 소실.

**수정** — `_NONCURRENT_SIBLING`의 정반대 방향 미러: 이번엔 canonical의
"기본" 등록이 비유동 쪽이므로, section_path가 유동인데 라벨이 안 그런
행(bare 무표기)을 그 canonical에서 **제거**해 대응 유동 canonical로 재라우팅
(단순 복사가 아니라 제거+이동 — `_src`가 `_CURRENT_STRICT` 소속이 아니라
나중에 필터링해줄 단계가 따로 없어서, 복사만 하면 `_src` 쪽 충돌이 그대로
남는다). 코드: `fin2/layer3/combine.py`
`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`/`_is_current_by_section_only()`.
가드: ①대응 유동 canonical에 이미 후보 있으면 재라우팅 안 함(이중계상
방지) ②전부 유동-signal뿐이면(진짜 비유동 후보 없음) 재라우팅 안 함
(00103130류 — 그대로 둬도 net_debt 무해, `_additive_debt_for_net_debt`가
ST/LT 상관없이 다 더함).

단위테스트 4건 추가(11건으로 확장) — `00172079` 실제 재현 + `bs.bond`
동형 + "전부 유동" 무재라우팅 + "대응 canonical 이미 있음" 가드. 전체
`pytest tests/ fin2/tests/` 662 passed/1 failed(기존 무관).

**★2차 전수재감사 결과 — pass→fail_a 0(안전), 그런데 net_debt 지표는
거의 그대로**(FY2024 40.5%→40.6%, FY2025 51.2%→51.4%, 사실상 무변화).
방금 고친 HELD-충돌 버그는 실제로 사라졌는데(단위테스트로 확인) 왜 지표가
안 움직였는지 **원인을 끝까지 추적**했다(사용자 지시, 2026-08-31):

**원인 규명 — 지표 악화의 대부분은 버그가 아니라 v3가 v2보다 좋아진 것**.
FY2024 mismatch 1,304건 중 **1,169건(90%)이 v3_net_debt > v2_net_debt**
방향이었고, 그중 **910건(78%)이 이번 순서4-②/③이 새로 배선한 라벨
(유동성장기부채/유동성사채/전환사채/교환사채/신주인수권부사채 계열)이
그 필링에 실제로 존재**했다. 원문 직접대조(`00103130` FY2024연결) —
face BS에 차입금·사채 관련 줄이 **정확히 5개**(단기차입금/유동성장기차입금/
전환사채/교환사채/장기차입금) 있는데, **v3는 5개 전부(합계
62,065,151,232)를 합산**하는 반면 **v2는 단기차입금+전환사채 2개만
잡고(55,728,052,087) 유동성장기차입금+교환사채는 통째로 놓친다** — 차이
6,337,099,145이 정확히 그 두 항목의 합과 일치. **v2가 불완전한 것이지
v3가 틀린 게 아니다**(삼성전자 반례, §2-7에서 이미 확인된 "v2=정답 전제는
위험하다"가 이번엔 대규모로 재현됨). "v2와의 불일치율"이라는 지표 자체가
**v3가 v2를 앞지르는 구간에서는 구조적으로 나빠질 수밖에 없는 지표**라는
뜻 — 순서4-②/③처럼 v2가 원래 못 잡던 세부항목을 v3가 새로 잡을수록
"불일치"가 늘어나는 게 정상이다.

**★그런데 이 조사 과정에서 별개의 진짜 버그(이번 순서1~3 범위 밖, 훨씬
전부터 있던 것)를 하나 더 찾았다** — v3_net_debt < v2_net_debt인 135건
(반대 방향) 중 표본 대조: `00181712` FY2024연결에서 `long_term_debt`가
통째로 `None`이었다. 원인: 원문 BS에 `사채 및 장기차입금`(14,788,886,000,000,
**유동부채** 소속)과 `사채및장기차입금`(48,073,129,000,000, **비유동부채**
소속)이 — **같은 정규화 텍스트, 서로 다른 섹션** — 둘 다 존재하는데, 이
"차입금및사채"류 **결합(rollup) 라벨**이 `bs.long_term_debt`에 fuzzy(0.96대)로
매핑되고, `bs.long_term_debt`는 (R57의 `_CURRENT_STRICT`도, 이번 순서4-③의
`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`도) 보호 대상이 아니라서
두 값이 그대로 충돌 → HELD → **62,861,073,000,000 전액 소실**(net_debt
62.9조 오차 — 이번 세션에서 발견한 것 중 금액 기준 최대). 전수 스캔(2011~2025,
`차입금및사채`/`사채및차입금`/`사채및장기차입금`/`장기차입금및사채`류만):
**538건**의 필링이 같은 패턴(같은 정규화 라벨이 유동+비유동 양쪽에 존재)에
해당 — R57/순서4-③과 **완전히 같은 병리**(만기 불분명 결합 라벨이 유동/
비유동 양쪽에 동시 존재 시 HELD)가 `bs.long_term_debt`/`bs.short_term_debt`
본체에도 있다는 뜻이다.

★**이 버그는 오늘 세션(순서1~3)이 만든 게 아니다** — 관련 alias
(`장기차입금및사채` 등)는 이번에 손대지 않은 훨씬 이전 alias이고, R57(원인
B) 이후 죽 있었을 것으로 추정된다. `bs.long_term_debt`/`bs.short_term_debt`는
net_debt 전용이 아니라 std_financials_v3의 **핵심 DIRECT_MAP 컬럼**(다른
소비자도 있음)이라 고치려면 순서4-③과 같은 net_debt-scoped 우회가 아니라
그 컬럼 자체를 건드려야 해서 **파급범위가 다르다** — 별도 설계·전수재감사
트랙으로 분리 권고(§6 후속 백로그, 가칭 R59). 지금은 발견·규모실측까지만.

근거: `account_maps/bs_accounts.py`(exchange_bond/warrant_bond 신설 4종 +
반의어 혼동 수정 alias 다수) · `fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`/
`_V3_LT_DEBT_PARTS` 재확장, `_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`) ·
`fin2/tests/test_combine_debt_wiring_step3_aliases.py` ·
`scripts/inspect_net_debt_case.py`(00103130/00181712 원문대조) ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-7/§2-10/§6.

## R59. `fin2/layer3/combine.py::_resolve()` — `bs.long_term_debt` 결합(rollup)

> **상태** 유효 · **적용 계층** 3
라벨의 유동/비유동 동시존재 시 canonical 전체 HELD(★★★★★완전 종료 2026-08-31)

**증상** — `bs.long_term_debt`는 R58(`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`)이
보호하는 4개 사채계열 canonical과 같은 취약점을 안고 있었다: 만기 구분이 라벨 자체에
없는 **결합 라벨**(`장기차입금및사채`/`사채및장기차입금`/`사채및차입금`/`차입금및사채`
등, "사채+차입금"을 하나로 합친 개념)이 `bs.long_term_debt`의 비유동 기본 alias로
등록돼 있는데, 같은 필링 안에서 이 결합 라벨이 유동부채 섹션과 비유동부채 섹션에
각각 별도 줄로 동시 존재하면 두 인스턴스가 같은 canonical로 몰려 `_resolve()`가
충돌로 보고 **`bs.long_term_debt` 전체를 HELD**(=None) — 유동분만 버려지는 게 아니라
비유동분(진짜 장기차입금)까지 통째로 소실된다. 실측(`00181712` FY2024연결): `사채 및
장기차입금`(14,788,886,000,000, 유동) + `사채및장기차입금`(48,073,129,000,000,
비유동) 동시존재 → `long_term_debt`=`None` → net_debt 62,861,073,000,000 과소(이
프로젝트에서 발견된 net_debt 단일 결함 중 금액 최대). 전수 스캔(2011~2025,
`report_lines` FY BS) 약 500여건 필링이 같은 패턴.

**R58과 재사용할 수 없었던 이유** — R58의 재라우팅 판정 함수
`_is_current_by_section_only()`는 "label_raw에 `장기`/`비유동` 문자열이 있으면
재라우팅 안 함"을 전제한다(전환사채/사채/교환사채/신주인수권부사채 계열은 현재분
라벨이 실제로 비유동 표시가 없어 이 전제가 맞다). 그런데 `bs.long_term_debt`의 결합
라벨은 그 자체에 이미 "장기"라는 단어가 들어있다(`장기차입금및사채` 등) — 그리고
실측된 유동측 변형(`사채 및 장기차입금`)에도 "장기"가 그대로 남아있다. 즉 **라벨
텍스트만으로는 유동/비유동을 구분할 수 없는 canonical**이라 R58의 판정 함수를 그대로
재사용하면 이 병리를 못 잡는다 — 실측(2026-08-31): 유동측 인스턴스 417건 중
label_raw에 장기/비유동이 포함된 건 단 1건(0.2%)이고, 그 1건이 바로 대표 사례
`00181712` 자신이었다(즉 라벨검사를 그대로 썼다면 정작 발견 계기가 된 사례를 놓쳤을
것).

**수정** — 라벨 검사 없이 `section_path`만 보는 새 판정 함수
`_is_current_by_section_only_pure()`와 별도 dict
`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING_PURE = {"bs.long_term_debt":
"bs.short_term_debt"}`, `_resolve()` 안의 별도 재라우팅 루프. R58의 기존 4개
canonical 처리 코드는 한 글자도 건드리지 않음(diff 0, 회귀위험 최소화 우선) — 이번
수정이 그 4개에 영향 없음을 코드만으로 확인 가능. `bs.long_term_debt`는 net_debt
전용 파생 컬럼이 아니라 `std_financials_v3`의 핵심 DIRECT_MAP 컬럼(다른 소비자도
있음)이므로, R58의 `_additive_debt_for_net_debt` 같은 net_debt-scoped 우회가 아니라
canonical 자체(`_resolve()`)를 고쳤다 — 다른 소비자에도 값이 정상적으로 전파된다.

가드는 R58과 동일: sibling(`bs.short_term_debt`)에 이미 자체 후보(예: 진짜
`단기차입금`)가 있으면 재라우팅된 유동측 rollup 값은 합산되지 않고 버려진다(이중계상
방지 우선) — 이 경우도 `bs.long_term_debt`는 충돌에서 벗어나 비유동값을 정상
확정하므로 수정 전(전액 소실)보다는 개선이지만 "완전 복구"는 아니다. 이 guard가
실제로 몇 %에서 발동하는지는 전수재감사 시 `scripts/run_r59_verification.sh` 5단계
(`recovered_after` vs `still_held_after`)로 측정한다.

★face_audit(Gate B)은 `long_term_debt`/`short_term_debt`를 애초에 감사하지 않는다
(실측: `fail_fields`에 등장하는 필드 23종에 두 컬럼 모두 없음) — 그래서 이 수정의
Gate B 회귀 확인은 R57/R58과 동일하게 "전체 pass→fail_a 전이"만으로 보고, 값 복구
자체는 `std_financials_v3`의 두 컬럼을 전/후 스냅샷으로 직접 비교해서 본다.

**상태(2026-08-31) — 완전 종료**: 코드+단위테스트(`fin2/tests/test_combine_debt_r59_
rollup_label_pure_reroute.py`, 6건) 구현 → `scripts/run_r59_verification.sh` 1차
전수재빌드+Gate B 전수재감사 실행 결과 **Gate B 회귀 0건**, 영향 필링 304건 중 HELD
287건 → **243건(84.7%) 복구**.

★1차 재검증 중 **R59와 무관한 별개 신규 버그를 하나 더 발견**: 잔여 44건을 원문+
매퍼로 전수 대조한 결과 42건이 "사채및차입금"(사채가 앞에 오는 어순)이 fuzzy 매칭
threshold 밑으로 떨어져 아예 `unknown`으로 빠지는 **별도의 alias 갭**이었다(반대
어순 "차입금및사채"는 이미 정상 매칭됨 — v2도 동일 실패, 이번 세션 이전부터 있던
것). `account_maps/bs_accounts.py`에 "사채및차입금" exact alias 추가 후 **2차
전수재빌드+재감사**를 다시 실행: Gate B 회귀 여전히 0건, 복구 **283/287(98.6%)**로
상승. 잔여 4건은 전부 원문대조로 원인 특정 완료 — sibling guard 트레이드오프(설계상
의도, `00181712` FY2024) 1건, 3-way 섹션분할(`00160588`) 1건, **또 다른 별개
alias 갭**("차입금 및 전환사채" 결합 라벨 미매핑, `00653194` 단독 실측 — 스코프가
좁아 이번 트랙에서는 미수정, 범위 밖으로 기록) 2건. `pytest tests/ fin2/tests/`
668 passed/1 failed(기존 무관 — `test_biz_section.py`).

근거: `fin2/layer3/combine.py`(`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING_PURE`,
`_is_current_by_section_only_pure`, `_resolve()` 내 별도 루프) ·
`account_maps/bs_accounts.py`("사채및차입금" exact alias) ·
`fin2/tests/test_combine_debt_r59_rollup_label_pure_reroute.py` ·
`scripts/run_r59_verification.sh` ·
`docs/plans/r59_rollup_debt_label_held_bug_design_2026-08-31.md` §4-1~§4-3.

## R60. `account_maps/bs_accounts.py` — `bs.current_portion_lt_debt` 개념분리

> **상태** 유효 · **적용 계층** 3
("유동성사채" → `bs.current_bond_plain` 신설)(★★★★★완전 종료 2026-09-01)

**증상** — `bs.current_portion_lt_debt`에 "유동성장기부채"/"유동성장기차입금"(장기
부채·차입금의 유동성 대체분)과 "유동성사채"(사채의 유동성 대체분, 개념이 다름)가
한 canonical에 섞여 있었다. 한 회사가 둘을 같은 필링에 별도 줄로 동시 공시하면
`_resolve()`가 서로 다른 값을 가진 두 후보로 보고 canonical 전체를 HELD. v2는
XBRL acode로 애초에 `bs.current_lt_debt`/`bs.current_bonds_plain` 2개로 분리돼
있어 이 문제가 없다(`fin2/taxonomy/concept_map.py:59`
`dart_CurrentPortionOfBonds → bs.current_bonds_plain`). 실측 사례(`00102858`
FY2008 연결): "유동성사채" 75,056,000,000 vs "유동성장기부채" 53,884,912,604 동시
존재 → HELD. 전수 실측(2026-08-31, `report_lines` 전체 BS): 동시존재 필링
**3,405건/487개사**.

**"기존 `bs.current_bond`로 병합" 대안 기각** — `bs.current_bond`(유동성회사채/
단기사채/사채(유동)/유동사채)로 "유동성사채"를 그냥 합치는 손쉬운 안을 실측으로
검증한 결과 기각: 동시존재 227건 중 176건이 값이 달라 **새 충돌**을 만든다(51건만
우연히 같은 값). 전환사채/교환사채/신주인수권부사채와 동일한 패턴으로, 완전히
새로운 leaf canonical(`bs.current_bond_plain`)로 분리하는 것이 유일한 안전한 해법.

**수정** — `account_maps/bs_accounts.py`에 `bs.current_bond_plain: ["유동성사채"]`
신규 등록(기존 `bs.current_portion_lt_debt`에서 "유동성사채" 제거), `fin2/layer3/
combine.py`의 `_V3_ST_DEBT_PARTS`에 `bs.current_bond_plain` 편입(net_debt 합산
전용 leaf — DIRECT_MAP 연결 없음, 기존 `bs.current_portion_lt_debt`/
`bs.current_bond`와 동일).

★face_audit(Gate B)은 이 두 canonical(`bs.current_portion_lt_debt`/
`bs.current_bond_plain`)을 애초에 감사하지 않는다(net_debt 전용 파생 집계 leaf라
`std_financials_v3`에 자체 컬럼조차 없음, R59와 동일 실측) — Gate B 회귀는
"전체 pass→fail_a 전이"만 보고, 값 복구 자체는 `std_financials_v3.net_debt`
전/후 스냅샷 비교로 검증(`_additive_debt_for_net_debt`의 결과가 `net_debt`에만
copy-back되고 `short_term_debt`/`long_term_debt` 영속 컬럼은 건드리지 않음 —
`_apply_enrichment` 참고).

**상태(2026-09-01) — 완전 종료**: 코드+단위테스트(`fin2/tests/
test_combine_debt_r60_current_bond_plain_split.py`, 5건) 구현 →
`scripts/run_r60_verification.sh` 전수재빌드(5-shard, 2,546개사)+Gate B
전수재감사(5-shard) 실행 결과 **Gate B 회귀 0건**(pass→fail_a 전이 0). net_debt
값이 실제로 바뀐 필링 **2,241건**(영향 3,158건 중 — report_lines 전체기간 기준
3,405건이었으나 std_v3 FY period 결합 조건상 3,158건으로 좁혀짐), 회수 총액
**약 350.3조원**(`sum(net_debt_after - net_debt_before)`). 잔여 24건은 전부
"still held"인데 원문대조 결과 이번 수정과 **무관**(cash 컬럼 자체가 비어있어
net_debt 산식이 애초에 계산 불가 — 별개의 기존 이슈). `pytest tests/ fin2/tests/`
673 passed/1 failed(기존 무관 — `test_biz_section.py`).

★교훈 — 검증 스크립트 설계 시 "canonical이 HELD→net_debt가 NULL"만 복구지표로
잡으면 안 된다: `_V3_ST_DEBT_PARTS`처럼 여러 canonical을 더하는 additive 합산
구조에서는 하나가 HELD여도 다른 구성요소 덕에 net_debt가 NULL이 아닌 채로
"과소계상"되는 경우가 대부분이라(R60 실측: NULL 기준 recovered_after=0였지만
실제 값변경 2,241건/350.3조원) — **값 자체의 전/후 diff**를 반드시 함께 봐야
진짜 복구율이 드러난다.

근거: `fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`) ·
`account_maps/bs_accounts.py`(`bs.current_bond_plain`) ·
`fin2/tests/test_combine_debt_r60_current_bond_plain_split.py` ·
`scripts/run_r60_verification.sh` ·
`docs/plans/bs_current_portion_lt_debt_concept_split_design_2026-08-31.md` §4.

---

## R62. `account_maps/is_accounts.py` + `parser/common/amount_normalizer.py` —

> **상태** 유효 · **적용 계층** 3
`is.net_income` '(당기)' 삽입형·'총당기순이익' 계열 alias 누락 + 로마숫자 혼합표기
정규화 버그 (2026-09-02, std_v3 상류결함① 부분 해소)

**배경** — [[gateb-factv2-backlog-1to5-calendar-v3-scoping-2026-09-02]] Phase2에서
발견된 "std_v3 상류결함①"(interim 행의 ~4%가 `ebt`/`tax_expense`는 정상인데
`net_income`만 NULL, 9,468~9,768건) 후속 원인규명 트랙. 재현 표본: 현대차(00164742)
separate 2012~2016 전 분기 + 2017 Q1/H1.

**근본원인 2건, 같은 원인규명 세션에서 함께 발견**:

1. **alias 누락** — 원문 헤드라인 당기순이익 라벨이 "분기(당기)순이익"(현대차 2012~
   2016)처럼 duration 접두어와 '(당기)'를 **같이** 쓰는 변형, 또는 K-GAAP 구서식
   "총당기순이익"(총-접두) 계열인데 `account_maps/is_accounts.py`의 `is.net_income`
   alias 목록엔 접두어 없는 형태("분기순이익", "당기순이익" 등)만 등록돼 있었다. 퍼지
   매치도 구제 못 함 — "분기(당기)순이익" vs "분기순이익" SequenceMatcher ratio
   0.7143, 임계 0.88 미달.
2. **로마숫자 혼합표기 정규화 버그**(공용 함수, R28 계열) —
   `amount_normalizer.normalize_account_name()`이 로마숫자 접두어를 "유니코드
   전용"/"ASCII 전용" 정규식 **둘로 따로** 처리했다. 유니코드 로마숫자 한 글자
   (`Ⅲ`)는 실제로 여러 자리('III')를 나타내는데, DART 필자가 "XⅢ."(ASCII 'X' +
   유니코드 'Ⅲ')처럼 섞어 쓰면 유니코드 정규식은 맨 앞이 ASCII라 매치 실패, ASCII
   정규식은 'X' 한 글자만 로마숫자로 오인식해 지우고 뒤의 'Ⅲ.'을 그대로 남긴다 —
   "Ⅲ. 총당기순이익" 같은 잔재 형태가 만들어져 위 alias 추가로도 매치 안 됨.

**항등식 대조로 안전성 확인** — 후보 라벨을 alias로 승격하기 전, 같은 문서 안에서
`ebt − tax_expense`와 정확히 일치하는지, 그리고 bare `당기순이익`과 공존할 때 값이
갈리지 않는지(발산 0건, 전수) 확인한 것만 등록. **의도적으로 등록 안 한 것**:
`계속영업이익(손실)`(IFRS 계속영업=중단영업 **제외**분이라 중단영업이 있는 문서에서
등록하면 net_income 과소 오염 — 실측 00102113 2024FY: 계속영업 −5,678,950,649 ≠
실제 net_income 1,315,633,234, 중단영업이익 6,994,583,883 별도 존재), `총포괄손익`
(다른 canonical, `is.total_comprehensive_income`), `법인세비용차감전순이익(손실)`
(이미 `is.ebt`), `지배기업소유주지분`(bare 라벨 함정, R49/2026-08-22 선례와 동일
이유로 기존에도 제외됨) — 전부 "ebt−tax와 우연히 값이 같아 보이는" 이웃 개념이었다.

**구현**:
- `account_maps/is_accounts.py::IS_ACCOUNTS["is.net_income"]`에 8개 alias 추가:
  `분기(당기)순이익`·`반기(당기)순이익`·`당(분)기순이익(손실)`·`당(반)기순이익(손실)`·
  `당기(전기)순이익(손실)`·`총당기순이익`·`총당기순이익(손실)`·
  `총당기순이익(Net Income-Total)`.
- `amount_normalizer.py`: 선두 로마숫자류 구간(`^[A-Za-zⅠ-Ⅹⅰ-ⅹ]+`)의 유니코드
  문자만 ASCII 다중문자로 치환(`_ROMAN_UNICODE_TO_ASCII`)한 뒤, 기존 ASCII 로마숫자
  문법 정규식 **하나로 통일**(과매칭 방지 문법은 그대로 재사용 — 일반 라벨 동작
  불변). 순수 유니코드/순수 ASCII 접두어는 종전과 동일하게 동작(회귀 없음).
- 계층2(`report_lines.py`)는 `account_mapper`를 안 씀(파일 상단 독스트링에 명시) —
  이번 수정은 **계층3(combine.py 매핑)에만 영향**, R29와 동일하게 `report_lines`
  재추출 불필요.

**검증**:
- 회귀 테스트 신설 2개: `fin2/tests/test_account_mapper_net_income_paren_variants_
  r62.py`(alias 8종 exact 매치 + `계속영업이익` 등 4종 미등록 확인)、
  `fin2/tests/test_amount_normalizer_roman_prefix_r62.py`(혼합/순수 로마숫자 접두어
  + 비-로마숫자 라벨 무변경). `pytest tests/ fin2/tests/` 694 pass(무관 기존 실패
  1건 `test_biz_section.py::test_lxintl_facility_table_dropped` 불변).
- 실측 회수 규모(DB 전수 스캔, `ebt−tax_expense` 항등식 매치 기준): 대상 인구
  9,768행 중 **1,239행(12.7%)/297개사**가 새 alias+정규화 수정으로 `is.net_income`
  후보를 얻게 됨. **잔여 8,529행은 다른 원인**(표본 00220969 확인 —
  `report_lines`에 헤드라인 당기순이익 행 자체가 **아예 없음**, 계층2 추출 결함 또는
  원문 표 형태 자체가 다른 것으로 추정, 미확정) — 이번 트랙 범위 밖, 별도 트랙
  후보로 분리.

**백필**: `build_std_v3.py --corp <297개사> --year-min 1999`(대상 corp 목록은 위
검증 스크립트 산출물, 커밋에는 안 실음 — R29 선례와 동일하게 스크래치패드 산출물).
**사용자 실행 대기**(장시간 명령 직접실행 금지 정책) — 실행 전 `std_financials_v3`
pg_dump 백업 필수.

**후속트랙**(미착수, 범위 밖): 잔여 8,529행(계층2 헤드라인 행 결측 의심, 별도
원인규명 필요) — 이번 alias/정규화 수정 범위 밖.

---

## R63. `fin2/layer3/combine.py` + `fin2/layer3/build.py` — K-GAAP시대 연결 인터림

> **상태** 유효 · **적용 계층** 3
IS "직전연차 재게재" 배제 + 요약재무정보 브래킷라벨 누출 배제 (2026-09-02, std_v3
상류결함②)

**배경** — [[gateb-factv2-backlog-1to5-calendar-v3-scoping-2026-09-02]] 후속,
`docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_design_
2026-09-02.md`. revenue 기준 corp×basis×fiscal_year 83,844건 중 3,516건(906개사)
누적행 단조성 위반(Q1≤H1≤Q3≤FY 깨짐)에서 시작한 조사.

**근본원인 1(원문대조 2건으로 확정)** — K-GAAP 시대(~2010년까지) 인터림(Q1/H1/Q3)
필링의 "손익계산서"/"연결손익계산서" 재무제표 본문 표는 당해분기 데이터가 아니라
**직전 확정 연차 재무제표를 그대로 재게재**한 것. 2011년 K-IFRS 연결의무화
이전엔 연결 인터림 재무제표 작성·공시 자체가 법정의무가 아니었다는 규제상의
사실(별도는 원래도 분기공시 의무 대상이라 진짜 당해분기 데이터) — 계층2/계층3
버그가 아니라 원문 자체가 그렇게 작성됐다는 사실. 실측:
- 현대차(00164742) 2004 연결 — "연결손익계산서" 섹션이 Q1·Q3 필링에 바이트
  단위로 동일.
- KG스틸/동부제강(00115676) 2006 — 별도 "손익계산서" 표는 컬럼헤더가 필링마다
  정확히 다른 기간(Q1: "제25기 분기(2006.1.1~3.31)", Q3: "제25기 3분기
  (2006.1.1~9.30)")인데, 연결 "연결손익계산서" 표는 Q1·H1·Q3 전부 "제24기/제23기"
  (2005/2004 연차)로 완전 동일 — 세부계정 15개 이상 동일값(iconv EUC-KR→UTF-8
  후 grep 원문대조).
- 전사 정량화(report_lines raw): "필링간 값 하나라도 일치"하는 쌍 중 "10개+
  동시일치"(=표 전체 재게재) 비율이 **연결 97.2%(10,519/10,818쌍) vs 별도
  29.6%(8,128/27,470쌍)** — 압도적 비대칭.

**근본원인 2(전사 SQL로 확정)** — "요약(연결)재무정보" 표는 "[유동자산]" 식
대괄호로 섹션을 나누는데, 이 표가 간혹(전사 712개 (corp,rcept,statement,basis,
table_seq) 조합) 정식 BS/IS/CF/SCE/APPR statement+basis로 잘못 분류돼
`report_lines`에 들어가 있다. 결정적 확인(00171867, rcept 20081114001440,
2009H1): "[유동자산]" 라벨이 있는 **같은 table_seq 안에** `매출액`·`부채총계`·
`자산총계`·`자본총계`·`영업이익`·`지배회사지분순이익` 등 DIRECT_MAP 캐노니컬
정확일치 라벨이 그대로 섞여 있었다 — account_mapper가 대괄호 여부를 안 보므로
이 값들이 진짜 재무제표 본문 대신 요약표에서 채택될 위험이 실재.

**왜 "요약재무정보"로 대체하지 않는가** — 사용자 확인(2026-09-02): 그 표는
단위가 백만원(재무제표 본문 표는 원 단위)이라 std_v3의 정밀도 기준 미달, 소스로
채택 안 함. 즉 이 시대·이 basis엔 원천적으로 정밀 당해분기 연결 IS 데이터가
없다 — 복구가 아니라 **오염된 값을 배제(NULL)**하는 방향으로만 구현.

**구현**:
1. `combine.py::_stale_annual_reprint_table_seqs(session, corp, fy, period, basis)`
   신설 — 같은 corp×fiscal_year×basis의 **다른 interim period**(Q1/H1/Q3 중 현재
   period 제외)와 (label_raw, value_won) 10개 이상 동시일치하는 table_seq를
   cross-period DB 조회로 탐지(`report_fiscal_year <= 2012`로 조기 게이팅 — 실측
   연도분포 밖 구간에서 매 period마다 불필요한 쿼리 방지). `_resolve()`에
   `stale_is_table_seqs` 파라미터로 주입돼 `cands`의 is.* 캐노니컬에서 배제
   table_seq 후보를 제거하는 **cands-레벨 pre-pass**(main 루프 진입 전) — 남는
   후보가 없으면 그 캐노니컬은 아예 `cands`에서 삭제(=NULL). 기존 `trust_seqs`/
   `degenerate_eq_ids` 가드와 달리 "빈 풀 방지" 안전장치를 **의도적으로 안 둠**
   (그게 이 규칙의 목적 — 대체소스가 없는 시대엔 NULL이 맞는 결과).
   `combine_full()`이 매 period 호출마다 계산해 `_resolve()`에 전달.
2. `build_merged_lines()`/`collect_candidates()`의 SQL에 `NOT EXISTS` 서브쿼리
   추가 — 같은 (rcept_no, statement, basis, table_seq) 안에 `label_raw ~
   '^\[.*\]$'`(대괄호 라벨)인 행이 하나라도 있으면 그 table_seq 전체를 제외
   (`_trust_account_table_seqs()`와 같은 "특징적 신호로 table_seq 전체 배제"
   패턴, 신호가 값항등성 대신 라벨텍스트라 cross-period 조회 불요).
3. **부수 발견·수정**: `build.py::build_corp()`가 `if not col: continue`로 delete
   자체를 건너뛰고 있었다 — 위 두 배제 규칙이 새로 만드는 "이 (corp,fy,period,
   basis)는 이제 후보가 하나도 없다"는 케이스에서, 재빌드해도 **예전(수정 전)의
   틀린 값이 담긴 행이 영구히 안 지워지는** 버그를 노출시켰다(모듈 자체 독스트링의
   "delete-then-insert" 계약 위반, R63으로 처음 발현됐을 뿐 잠재적으로 기존에도
   있었을 수 있는 결함). `delete()`를 `if not col` 체크보다 먼저 실행하도록 이동 —
   `col`이 비어도 그 키의 기존 행은 항상 지워지고, insert만 조건부로 스킵.

**검증**: 회귀 테스트 신설 2개 — `test_combine_r63_stale_reprint_resolve.py`(pure,
합성 cands+stale_is_table_seqs로 `_resolve()` pre-pass 동작 검증, 5개), `test_
combine_r63_stale_reprint_db.py`(DB-backed, KG스틸 00115676/2006 Q1 연결
table_seq=1 탐지+별도 미탐지+FY 무영향, 00171867 브래킷라벨 table_seq 배제 실측
재현, 4개). `pytest tests/ fin2/tests/` 703 pass(무관 기존실패 1건
`test_lxintl_facility_table_dropped` 불변, R62와 동일).

**백필 완료**: 영향 corp 전사 스캔(같은 로직 SQL 재현) — §1 대상 1,112개사, §6 대상
49개사, 합집합 **1,117개사**. pg_dump 백업(`/Volumes/tj_finance_data/db_backups/
std_financials_v3_pre_r63_backfill_20260902.dump`, 51MB) 후 `build_std_v3.py
--corp <1,117개사> --year-min 1999` 백그라운드 실행(corp 목록은 R62 선례와 동일하게
스크래치패드 산출물, git 비추적 — 세션마다 SQL로 재현 가능). **실행 결과**:
1,117/1,117 corp 성공(에러 0), 197,861행, 6,290초(105분).

**후속조치 — calendar_v3 재동기화(필수, 놓치기 쉬움)**: std_v3 백필 직후
`dq_assertions.py`를 돌려보니 `calendar_orphan_cq`(ERROR) 위반이 345건 새로
잡혔다 — `calendarize_corp_v3()`가 corp+basis 단위 delete-then-insert라서, std_v3
쪽만 바뀌고 그 corp의 달력테이블(`std_financials_calendar`)을 다시 안 돌리면
예전 std_v3 행을 가리키던 달력분기가 유령행으로 남는다(`diag_calendar_orphans.py`
문서화된 기존 패턴, 이번에 실측으로 재확인). 같은 1,117개사에 대해
`calendarize_corp_v3()`를 재실행(226,319행, 173초)해 완전 해소(`calendar_orphan_cq`
345→**0**). **교훈**: std_v3 백필 후에는 항상 이 재동기화까지 한 세트 —
`docs/runbook_new_parser_pipeline_integration.md`에 "std_v3 값을 바꾸는 백필은
calendar_v3 재동기화까지 포함"으로 명시 필요(다음 세션 후속).

**최종 검증**:
- `dq_assertions.py` 전체 실행: ERROR 위반 어서션 2→**1**(`calendar_orphan_cq`
  345→0, `statement_magnitude_impossible`는 이 트랙과 무관한 기존 결함 —
  150→146으로 오히려 소폭 개선, 이번 백필로 신규 유입된 corp 없음 확인:
  71개 위반 corp 중 59개가 R63 영향권과 겹치지만 이건 두 결함 모두 "옛 K-GAAP
  시대 문제 필링"에 몰리는 자연스러운 상관관계일 뿐 — 배제 로직은 NULL/삭제만
  하므로 구조적으로 새 magnitude-impossible 값을 만들 수 없음).
  `calendar_adjacent_year_cq1_identical`(WARN)도 부수 개선 73→9.
- 표본 원문대조 4건 재확인: 현대차 00164742 2004 연결 Q1/H1/Q3 전부 NULL,
  KG스틸 00115676 2006 연결 Q1/H1/Q3 전부 NULL(별도 Q1은 진짜값 505,829,999,432
  보존), 00171867 2009H1 연결 행 자체가 삭제(브래킷라벨 오염만 있고 대체소스가
  없었던 케이스).
- 단조성 위반(Q1≤H1≤Q3≤FY, revenue 기준, 2002~2011): 3,516→**1,225**(65% 감소).
  "Q1=H1=Q3 완전동일값" 서명: 824→**82**(90% 감소) — 잔존 82건은 임계값10 미달
  또는 fy>2012 범위밖 케이스로 추정(미확인, 범위 밖).

**부수 발견(범위 밖, 후속 트랙 후보)**: KG스틸 2006 별도 H1의 "Ⅰ. 매출액(주석13과
14)"가 account_mapper에 안 걸림(Q1의 "매출액(주석10)"는 걸림) — 복수 주석번호를
"와/과"로 묶은 표기 정규화 갭으로 추정, R63과 무관한 기존 account_mapper 라벨매칭
버그. 이 때문에 해당 corp의 별도 H1/Q3 revenue가 R63 이후 (틀린 재게재값 대신)
NULL로 전환됐지만 진짜 데이터 복구는 못 함 — 별도 트랙 후보로만 기록.

### R63 후속 §8 — CF(현금흐름표) 확장 (2026-09-02, 다음 세션)

**배경** — 후속 트랙 후보 3건 중 사용자가 "CF도 §1 패턴인지 검증"을 선택. 설계문서
§8/§9(`docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_design_
2026-09-02.md`).

**근본원인 — IS와 완전 동일, 원문대조로 확정**: KG스틸(00115676) 2006 Q1·Q3 원문 —
같은 필링 안에 "현 금 흐 름 표" TITLE 표가 2개. ①"제25기 **분기**"(당해 Q1, 진짜,
필링마다 값 다름) vs ②"제24기"(**분기접미어 없음**, 직전 연차, IS와 동일하게
재게재 — "영업활동으로 인한 현금흐름"=54,870,597,628원이 Q1·Q3 필링 원문에
바이트단위로 동일하게 등장, grep 확인). 전사 정량화(방법론 보강 — `is_final=true`
+서로다른period쌍만, 아래 §9 오탐 제거 전 수치): IS consolidated 97.2%(재현)/
separate 16.0%. **CF consolidated 67.5%(247개사)/separate 32.8%(1,284개사)**.

**구현**: `_stale_annual_reprint_table_seqs()`에 `statement: str = "IS"` 파라미터
추가(table_seq는 statement별 독립 카운터라 IS/CF를 섞으면 안 됨 — 반드시 statement별
로 따로 호출). `_resolve()`의 파라미터를 `stale_is_table_seqs: set`에서
`stale_reprint_table_seqs: dict[str, set]`(예: `{"is": {...}, "cf": {...}}`)로
일반화 — pre-pass가 각 prefix(`is.`/`cf.`)의 자기 자신의 set만 그 prefix
캐노니컬에 적용(다른 prefix의 set과 절대 안 섞임). `build_merged_lines()`의
브래킷라벨 가드(§6)는 원래부터 statement 무관하게 전체 적용이라 코드 변경 불요.
`combine_full()` 호출부가 IS/CF 각각 한 번씩(2회) `_stale_annual_reprint_table_
seqs()`를 불러 dict로 조립.

### R63 후속 §9 — ★탐지로직 버그 발견·수정: 같은 period 내 원본+정정신고 중복집계
오탐 (2026-09-02, 같은 세션 — CF 확장 원문대조 중 발견, **R63 원안(IS)에도 소급
영향**)

**발견 경위**: CF 확장 검증 중 현대차(00164742) 2004 Q1 **별도**(연결 아님) CF를
원문대조하다가 table_seq=0(진짜 당해분기 표 — "I. 영업활동으로 인한 현금흐름"이
Q1=-248,693백만/H1=1,485,674백만/Q3=1,812,881백만으로 분기마다 전부 다름, 원문
확인)이 **오탐으로 배제**돼 있는 것을 발견.

**근본원인**: `_stale_annual_reprint_table_seqs()`의 원래 SQL은 `cur`/`other` 양쪽을
그대로 report_lines 원본 행으로 JOIN해 `count(*)`를 셌다. 같은 (corp,fy,period,basis)
안에 필링이 2개 이상(원본+기재정정)이고 **둘 다 같은 label+value를 그대로 담고
있으면**(정정이 그 값을 안 건드린 흔한 경우), 매칭 행 수가 필링 개수만큼
배가된다 — 실측: 현대차 2004 Q1 별도는 원본(20040515000203)+정정(20040618000205)
2개 필링이 있고, H1과 우연히 일치하는 세부계정이 5개뿐인데 5×2필링=**10**으로
임계값(10)에 정확히 걸려 "재게재"로 오판정됨. **"몇 번 겹쳤는지"가 아니라
"몇 개 계정이 겹치는지"를 세야 하는데, 필링 중복이 전자로 오염시킨 것**.

**영향 규모(전사 재계산, table_seq 단위)**: IS 13,692→11,892(**1,800건/13.1%
오탐**), CF 19,659→17,759(**1,900건/9.7% 오탐**) — 두 statement 다 영향, **이미
커밋된 R63 원안(IS, `915d456`)의 1,117개사 백필도 이 오탐을 일부 포함**하고
있었음(수정 전에는 이 사실을 몰랐음). 새 로직으로 다시 계산해도 old_flagged ⊇
new_flagged가 항상 성립(dedup은 카운트를 줄이기만 함 → 오탐 제거는 항상 "배제를
푸는" 방향, 새로 배제를 만들지 않음 — 구조적으로 안전한 방향의 수정).

**수정**: cur/other 양쪽을 `(label_raw, value_won)` 기준으로 먼저 `DISTINCT` 시킨
뒤 매칭 — 같은 값을 여러 필링이 중복 보고해도 1건으로만 집계.

**검증**: 회귀 테스트 신설 2개(현대차 2004Q1 별도 CF 오탐 미발생 확인,
IS/CF stale set 독립성 재확인) + 기존 KG스틸 재현 테스트 불변 통과.
`pytest tests/ fin2/tests/` 708 pass(무관 기존실패 1건 불변).

**재백필(IS∪CF 합집합, 구탐지 기준 영향 corp 전체)**: pg_dump 백업(`/Volumes/
tj_finance_data/db_backups/std_financials_v3_pre_r63cf_backfill_20260902.dump`,
110MB) 후 CF 신규 1,405개사 1차 백필(238,499행/7,913초) → 오탐버그 발견 →
IS∪CF 합집합 **1,406개사** 수정된 코드로 재백필(238,800행/7,005초, 에러 0) →
`calendarize_corp_v3()` 재동기화(269,317행/207초, 실패 0, runbook B5) →
`dq_assertions.py`: `calendar_orphan_cq` 0 유지, `statement_magnitude_impossible`
146→147(+1, 무관 노이즈), `std_v3_conflicts_unresolved` 32,595→32,846(+251 —
오탐 수정으로 예전에 "후보 전멸→NULL"이던 일부 canonical이 이제 "진짜+오매치
후보 2개 있는 채로 HELD"로 바뀐 것으로 추정, HELD가 NULL보다 안전한 상태이므로
증가 자체는 우려사항 아님, 원인 확정은 미착수).
- 표본 원문대조 재확인: 현대차 00164742 2004Q1 별도 cfo=**-248,693,000,000**
  (수정 전 NULL 오탐 → 수정 후 원문과 정확히 일치하는 값으로 복구), KG스틸
  00115676 2006(H1 별도 cfo=4,941,866,221 불변, Q1/Q3 여전히 NULL — 진짜
  재게재라 회귀 아님).

**커밋 대기**(정책상 사용자 요청 시에만 커밋).

---

## R64. `parser/common/amount_normalizer.py::normalize_account_name()` — 주석번호

> **상태** 유효 · **적용 계층** 3
와/과/및 결합표기 정규화 갭 (2026-09-02, R63 후속 후보 착수)

**배경** — R63 §후속트랙 후보②(KG스틸 00115676 2006 H1/Q3 별도 revenue 복구
실패 원인으로 부수발견). 복수 주석번호를 콤마 대신 한글 접속사("와"/"과"/"및")로
묶는 표기(`"Ⅰ. 매출액(주석13과 14)"`, `"자본금(주석1과15)"`, `"매도가능금융자산
(주석5,7과29)"` 등, 콤마와 접속사 **혼합**형도 포함)를 구 정규식
`\(주석?\s*\d[\d,\s]*\)`이 못 잡았다 — 숫자 뒤 '과'/'와'/'및'에서 매치가 끊겨
괄호가 안 지워지고 라벨에 그대로 잔류.

**실측 영향(DB 전수 스캔)**: 이 결합표기 패턴을 포함하는 라벨 3,537종/10,226행
(197개사) 중, **`mapper.map(raw_label)` 실제 호출 경로**(combine.py 가 쓰는
그대로 — `normalize_account_name()`을 먼저 별도 호출해 미리 정규화한 뒤 넘기면
`map()` 내부가 또 한 번 정규화해 이중적용 착시가 생기므로 주의)로 수정 전/후를
정확히 대조한 결과 **1,943종/5,229행(178개사)**이 old-fail→new-pass 로 회복됨
— 자본금·매출액·유형자산·매입채무·재고자산 등 DIRECT_MAP 핵심 계정 다수 포함.
짧은 canonical(예: "매출액", 3자)일수록 잔류 노이즈("(주석13과 14)")가 fuzzy
ratio 를 임계값(0.88) 밑으로 끌어내려 완전 매치실패로 이어진다(긴 라벨은 노이즈
비중이 작아 fuzzy 로 우연히 구제되는 경우가 많았음).

**수정**: 주석 참조 제거 정규식 2곳(선두 미고정형·후방 고정형)의 숫자 목록
구분자 문자셋에 '와'/'과'/'및'을 추가 — `[\d,\s]*` → `[\d,\s와과및]*`. 콤마만
쓰는 기존 형태는 종전과 동일하게 동작(문자셋에 추가만 했을 뿐 제거 없음,
무손실 불변식 유지). `<주석N,...>` 리터럴 잔재 제거 정규식(2026-07-30 도입)은
DB 전수 스캔 결과 이 결합표기가 0건이라 변경 불필요.

**잔존 실패(무관 별개 원인)**: 위 회복분을 뺀 나머지는 **이 갭과 무관한 별개
원인 2가지**로 확인(둘 다 이 트랙 범위 밖, 별도 후보로만 기록):
1. 괄호 없는 연번 접두 "1)"/"2)" 류가 안 벗겨짐(`normalize_account_name()`은
   `(1)` 괄호형만 벗김, 예: `"2) 보험금비용(주석26과27)"` → 정규화 후에도
   `"2) 보험금비용"` 잔류) — 보험사 IS 세부계정에 집중.
2. `account_maps/*.py` 자체에 alias 미등록(정규화는 정상이지만 canonical 이
   없음, 예: `"만기보유금융자산"`·`"책임준비금"`·`"부동산임대수익"`) — 보험/
   특수업종 전용 계정 다수.

**계층 영향**: 계층2(`report_lines.py`)는 `account_mapper`를 안 씀(R62/R63과
동일) — 이번 수정은 **계층3(combine.py 매핑)에만 영향**, 계층2 재추출 불요.

**검증**: 회귀 테스트 신설(`fin2/tests/test_amount_normalizer_note_ref_conjunction_
r64.py`, 3개 — 결합표기 정규화, 기존 콤마전용 무회귀, end-to-end 매핑 복구 확인).
`pytest tests/ fin2/tests/` 711 pass(무관 기존실패 1건 `test_biz_section.py::
test_lxintl_facility_table_dropped` 불변).

**백필 완료**(같은 세션, 사용자 승인 후 직접 실행): pg_dump 백업(`/Volumes/
tj_finance_data/db_backups/std_financials_v3_pre_r64_backfill_20260902.dump`,
52.9MB) 후 `build_std_v3.py --corp <178개사> --year-min 1999` 실행 —
178/178 corp 성공, 31,036행, 1,010초(17분), 에러 0. 이어서 `calendarize_corp_
v3()` 재동기화(178개사, 33,977행, 29초, 실패 0, runbook B5).

**검증 완료**:
- `dq_assertions.py`: `calendar_orphan_cq` 0 유지, `statement_magnitude_
  impossible` 147(R63 §9 종료 시점 기준선과 동일, R64로 인한 신규 위반 0),
  `std_v3_conflicts_unresolved` 32,846→**32,803(−43, 개선)** — 기존엔 후보
  전멸로 NULL이던 canonical이 이번 수정으로 단일 정답 후보를 얻어 HELD 없이
  깔끔하게 resolve 된 것으로 추정(우려사항 아님).
- 원문대조(KG스틸 00115676, 2006 separate revenue): Q1=505,829,999,432(기존
  정상)·**H1=557,076,012,411**(수정 전 NULL → 원문 rcept 20060814001339 값과
  정확히 일치)·**Q3=563,912,093,240**(수정 전 NULL → 원문 rcept 20061114001258
  값과 정확히 일치). Q1≤H1≤Q3 단조성도 정상(진짜 누적매출 패턴, R63이 걸러낸
  "직전연차 재게재" 정적값과 무관한 진짜 당해분기 데이터).

**R64 트랙 완전 종료 — 커밋만 대기**(정책상 사용자 요청 시에만 커밋).

---

## R66. `fin2/layer3/combine.py::combine_full()` — 증권/보험/은행/여신전문

> **상태** 유효 · **적용 계층** 3
표준매출액 계산기(`apply_revenue_profile()`)에 R63 stale-reprint 필터 배선
(2026-09-03)

**배경** — [[std-v3-upstream-defects-r62-and-monotonicity-2026-09-02]](메모리),
설계문서 `docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_
design_2026-09-02.md` §10. R65 종료 직후 세션, 잔존 단조성위반 트리아지(§9)의
EXACT_EQUAL_RESIDUAL(25건) 후속 조사. 최초 가설("R63 임계값 10개 미달, 증권업
특수계정이라 매치가 안 됨")을 00104856(삼성증권) 표본 직접 SQL 재현(매치
165개, 임계값을 압도적으로 초과)으로 반증.

**진짜 근본원인** — `combine_full()`이 `_resolve()` 호출 직전에 R63의
`_stale_annual_reprint_table_seqs()`로 stale-reprint table_seq를 계산해
`stale_reprint_seqs` dict(`{"is": ..., "cf": ...}`)를 만들지만, 이 값은
`_resolve()`(→ DIRECT_MAP `cands` 정제)에만 전달되고, **같은 함수 뒤쪽의
`apply_revenue_profile(is_lines, ...)` 호출**(증권/보험/은행/여신전문 업종
전용 "표준 매출액 = 명명된 소계 조합" 계산기, 예: 증권 `net_op_formula` =
영업이익+판매관리비)은 필터링 안 된 원본 `merged` IS 라인을 그대로 읽는다 —
같은 원인(K-GAAP 시대 연결 인터림 재게재)의 **두 번째 소비 경로**가 R63
구현 당시 누락됐던 것.

**00104856 원문/DB대조로 메커니즘 확정**: FY2004 영업이익
(154,594,395,676)+판관비(517,609,979,403, `conflicts.is.sga`에 남아있던
후보값과 정확 일치)=**672,204,375,079** — 2005 Q1/H1/Q3 std_v3 revenue와
정확히 일치. 둘 다 R63이 이미 "직전연차 재게재"로 확정한 stale
table_seq=0 출처. EXACT_EQUAL_RESIDUAL 25건 중 23건(92%, 13개사 중
11개사)이 증권/보험 업종(`SECURITIES`/`INSURANCE` 프로파일 적용대상).

**수정**: `combine_full()`의 `apply_revenue_profile()` 호출 앞에서, 이미
계산돼 있는 `stale_reprint_seqs["is"]`로 `is_lines`를 필터링한 뒤 호출.
`basis_fallback` 케이스(별도 basis만 있는 회사의 연결 폴백)도 `_resolve()`가
기존에 하던 것과 같은 처리(요청 basis로 계산된 stale set을 그대로 재사용)로
일관성 유지.
```python
is_lines = [r for r in is_lines
            if r.get("table_seq") not in stale_reprint_seqs["is"]]
applied = apply_revenue_profile(is_lines, _get_induty(session, corp), corp)
```

**전체스케일 정밀 스캔(ground-truth, R65식, 실제 프로덕션 함수 직접호출)**:
증권/보험/은행/여신전문 induty_prefix 대상 103개사×2002~2011×Q1/H1/Q3×연결/
별도 전수 재계산 — **checked=2,885 / profile_applied=651 / changed=312건
(18개사)** — 최초 증상신호(25건)의 12.5배, R65와 동일한 "좁은 증상신호 ≪
실제 영향범위" 패턴. 전부 `securities` 프로파일에서만 발생(보험/은행/여신전문
0건), 연결 206/별도 106, **312건 전부 old(오염값)→new=None**(대체 후보
없음, R63의 "복구 아닌 배제" 원칙과 동일 성격, 새 오염 0건). 구현 세션에서
production 코드로 재현한 결과도 정확히 동일(changed=312건/18개사) — 값
확정.

**검증**: 회귀 테스트 신설 `fin2/tests/test_combine_r66_revenue_profile_
stale_reprint.py`(00104856 FY2005 Q1/H1/Q3 consolidated old→None 확인 +
separate 비영향 확인). `pytest tests/ fin2/tests/` 717 pass(유일한 무관
기존실패 `test_biz_section.py::test_lxintl_facility_table_dropped` 불변,
R63~R65와 동일).

**백필 완료**(같은 세션, 사용자 승인 하 — "1번으로 진행하자"): pg_dump
백업(`/Volumes/tj_finance_data/db_backups/
std_financials_v3_pre_r66_backfill_20260903.dump`, 52.8MB) 후
1. `build_std_v3.py --corp <18개사> --year-min 1999` — 18/18 corp 성공,
   3,106행, 98초, 에러 0.
2. `calendarize_corp_v3()` 재동기화(18개사, 3,163행, 실패 0).

**검증 완료**:
- `dq_assertions.py`: 유일한 ERROR 위반 `statement_magnitude_impossible`
  147건 — 세션 시작 전 기준값과 **147=147, 신규위반 0건** 확정(R66과 무관한
  기존결함). WARN `std_v3_conflicts_unresolved` 32,846→**32,789(개선)**.
- Gate B: 이번 백필이 정확히 18개사에만 스코프돼 다른 회사 std_v3는 전혀
  변경되지 않았으므로, R63/R65의 전체 5-shard 대신 **이 18개사만 스코프한
  PK조인 전이표**로 검증(총량비교 아닌 row-key 단위 대조,
  [[gateb-482-backlog-cluster-ab-rootcause-2026-08-27]] 교훈과 동일 원칙).
  `face_audit_snap_20260903_pre_r66`(3,145행) 대비 `gateb_audit.py --recheck
  --corp-file <18개사> --fy-min 1999` 재실행 후 PK(corp_code, fiscal_year,
  fiscal_period, statement_type, is_stub) 조인 — **pass→pass 1655 /
  pending→pending 1486 / fail_b→fail_b 4, 전이 0건**(신규 fail_a 0, 등급
  하락 0). 312건의 revenue가 오염값→NULL로 바뀌었음에도 face_audit 행수준
  gate_status가 완전히 불변인 것은, 이 시대(2002~2011) 필링엔 대조할 XBRL
  원천이 없어(Track A 미적용) Track B(텍스트 대조)도 이 필드를 이미
  pending으로 다루고 있었기 때문으로 추정(원문대조 아님, 정황).

**R66 트랙 완전 종료**. 코드 커밋 완료(`1b47f44`).

---

## R68. `account_maps/bs_accounts.py`+`cf_accounts.py`+`fin2/layer3/combine.py` —

> **상태** 유효 · **적용 계층** 3
P1A: `lease_liability`/`borrowings_proceeds`/`borrowings_repaid` v2 파리티 3컬럼
신설 + bare "리스부채" 섹션기반 재분류 (2026-09-03) — **완전 종료(구현+테스트+
전사백필+검증)**

**배경**: `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` §Phase 1(P1A,
2026-08-22 설계·안전성조사 T0~T7 완료·SPLIT_DRAFT 확정)의 마지막 미착수 항목.
`v2-drop-remaining-backlog-2026-09-03`(메모리) 체크리스트 3번.

**구현**: `account_maps/bs_accounts.py`에 `bs.lease_current`/`bs.lease_noncurrent`
신설(SPLIT_DRAFT 그대로, `bs.lease_liability`는 무수식 총계 라벨만 남김),
`account_maps/cf_accounts.py`에 `cf.borrow_proceeds_st`/`_lt`·`cf.borrow_repaid_
st`/`_lt` 신설(단기/장기 명시 라벨만 이동, "기타금융부채"·"유동성장기..." 등
만기귀속 애매한 변형은 SPLIT_DRAFT 원안대로 집계에 그대로 둠). `std_financials_
v3`에 3컬럼 추가(마이그레이션 `2026_09_std_financials_v3_lease_borrowings`).
`combine.py`에 `_lease_liability_value()`/`_borrowings_values()`(부품 합산, 없으면
집계 라벨로 폴백) 신설, `_apply_enrichment()`에 배선 + `_VALUE_COLS`(build.py) 추가.

**원문대조로 SPLIT_DRAFT 자체의 갭 발견·수정**: 무수식 "리스부채"/"금융리스부채"
라벨을 "총계, 그대로 둠"으로 가정한 원 설계가 실측과 어긋남 확인 — DB 전수 스캔
결과 이 무수식 라벨의 대다수가 실제로는 `section_path`상 `부채>유동부채`
(13,654행/574개사) 또는 `부채>비유동부채`(20,085행/779개사) 섹션 안에 위치(라벨
자체엔 유동/비유동 wording이 없을 뿐). 원문 2건 직접대조:
- 경농(00101433) 2025FY 별도: bare "리스부채"(772,424,809, `section_path=
  '부채>유동부채'`)와 "비유동 리스부채"(938,907,694)가 같은 필링에 공존 — 진짜
  총계는 두 값의 합(1,711,332,503). 섹션신호 없이 폴백만 쓰면 비유동분만
  채택되고 유동분(bare)이 통째로 누락됨.
- 00101664: 완전히 동일한 "리스부채" 텍스트가 같은 필링 안에서 유동/비유동
  섹션에 각각 다른 값으로 존재(2020H1: 802,546,265/1,201,208,120) — 분해 후에도
  같은 canonical로 충돌해 HELD(분해 전과 동일 결함).

**수정**: `_route_bare_lease_by_section()` 신설 — 다른 부채계정에 이미 있는
sibling 재라우팅 패턴(`_NONCURRENT_SIBLING`/`_CURRENT_CONTAMINATED_NONCURRENT_
SIBLING` 계열)과 같은 자리(cands 전체 순회 전 pre-pass)에서, `bs.lease_liability`
후보를 `section_path`로 먼저 판정 — 유동/비유동이 명확하면 해당 split canonical로
옮기고(사용자 지시: "위치를 알 수 있으면 위치로 판단, 위치가 명확하지 않으면
이름으로"), 섹션도 애매한 잔여만 진짜 집계로 유지. sibling이 이미 자기 라벨로
후보를 가진 경우엔 중복합산 방지를 위해 옮기지 않음(기존 guard 1과 동일 원칙).
CF 차입 쪽(`cf.borrow_proceeds/repaid`)은 실측 결과 section_path가 전부
"재무활동현금흐름"류로 균일해 이 문제 없음(BS 리스부채만의 결함).

**격리성 확인**: `bs.lease_liability`/`bs.lease_current`/`_noncurrent`,
`cf.borrow_proceeds_*`/`cf.borrow_repaid_*`는 이번 P1A 코드 밖에서 아무도 안 읽음
(grep 확인) — 기존 검증된 다른 컬럼(net_debt/total_liabilities 등)에 영향 불가,
신설 3컬럼만 채워지거나 NULL로 남는다.

**검증**: 신규 회귀테스트 18개(`fin2/tests/test_combine_p1a_lease_borrowings.py`,
순수함수 단위테스트), `pytest tests/ fin2/tests/` 741 pass(무관 기존실패 1건
`test_lxintl_facility_table_dropped` 불변). 표본 4개사(00100601·00101433·
00101549·00101664) 재빌드 후 위 두 원문대조 사례 전부 정확히 일치 확인
(1,711,332,503·2,003,754,385).

**전사 백필 완료(같은 날, 사용자 승인)**: pg_dump 백업(`std_financials_v3_
pre_r68_backfill_20260903.dump`, 53MB) 후 `build_std_v3.py --all --year-min
1999`을 5-shard 병렬(10코어 중 5개)로 실행 — **2,546/2,546 corp 전부 성공,
에러 0**, 302,436행(총 984초/샤드당 약16분, 5개 동시실행). 위 두 원문대조
표본값(1,711,332,503·2,003,754,385) 전사 백필 후에도 정확히 유지 확인.
**채움 규모**: `lease_liability` 91,679행/2,044개사, `borrowings_proceeds`
210,267행·`borrowings_repaid` 219,659행/합계 2,492개사.

**calendar_v3 재동기화 불요**(런북 B5과 달리 이번엔 스킵 — 근거): `std_financials_
calendar`/`fin2/standardize/calendar_v3.py`의 `_FLOW_COLS`/`_STOCK_COLS`에 이
3컬럼 자체가 없어(달력 스키마 미확장, 별도 후속 트랙 필요시) 재동기화해도 이번
백필 결과가 반영될 곳이 없다 — 이산분기/스크리너 화면에는 아직 안 나타남(알려진
범위 제한, 필요시 별도 트랙).

**검증**: `dq_assertions.py` ERROR `statement_magnitude_impossible` 32=32(신규
0, R68과 무관한 기존 이슈 불변). WARN `std_v3_conflicts_unresolved` 32,858→
33,632(+774, 신설 6개 canonical — `bs.lease_current`(36)·`bs.lease_noncurrent`
(581)·`cf.borrow_proceeds_st`(191)·`cf.borrow_proceeds_lt`(172)·`cf.borrow_
repaid_st`(222)·`cf.borrow_repaid_lt`(118) — 가 새로 잡히기 시작한 것으로 정확히
설명됨, "결측이 오염보다 안전" 원칙대로 해당 행은 NULL 유지). **Gate B 전수/스코프
재감사는 생략**(위 격리성 확인대로 이 3컬럼은 Gate B가 감사하는 기존 필드
어디에서도 안 읽혀 gate_status 전이가 원리적으로 불가능 — R66/R67의 "스코프 좁으면
PK조인 전이표"보다 한 단계 더 강한 케이스, 코드리뷰(grep)만으로 충분).

**R68 트랙 완전 종료**. 코드+백필 커밋 완료(`8b8d3a0` 코드, 문서 커밋은 이어서).
`v2-drop-remaining-backlog-2026-09-03`(메모리) 체크리스트 3번 완료.

---

## R72. `fin2/layer3/combine.py::_reduce_conflict()` — is.revenue grand-total

> **상태** 유효 · **적용 계층** 3
override가 "수익(매출액)"류 정정 후보를 못 알아봄 (2026-09-06) — **완전 종료
(설계+구현+테스트+2개사 백필+검증)**

**배경**: `statement_magnitude_impossible` 잔존건 트리아지(항목②, 메모리
`v2-drop-remaining-backlog-2026-09-03`) 중 발견. 키네마스터(00535375)
2018H1·나이스디앤비(00606293) 2019Q3 원문대조로 확정: 원본 필링의
"영업수익"(bare grand-total 라벨)이 단위오류(×10³~10⁶, 별도 이슈 — 아래
"근본원인 구분" 참고)로 오염됐는데, 같은날/익일 정정본이 **다른 라벨**
("수익(매출액)")로 정확한 값을 재보고했다. `build_merged_lines()`의
델타패치(R2)는 셀 신원을 `(statement, basis, col_index, section_path,
label_raw)`로 판정하므로 라벨이 다르면 "같은 셀의 정정"이 아니라 "별개
후보"로 남는다(`amended=True` 플래그만 붙음) — 이 자체는 의도된 동작(라벨이
완전히 바뀌는 정정은 R2가 원래 못 따라감, R71 이전에도 알려진 한계).

**진짜 버그**는 그 다음 단계다: `_reduce_conflict()`의 "revenue grand-total
preference"(R16, 2026-08-13)가 `norm(label) in _REVENUE_TOTAL_LABELS`
(`{"매출액","영업수익","매출","순매출액"}`)로 grand 후보를 고르는데, `norm()`
(`fin2/layer3/industry_profiles.py`)이 라벨을 첫 `"("` 앞까지만 남기고
자른다(각주참조 "이익잉여금(주27)"→"이익잉여금" 제거가 원래 목적) — "수익
(매출액)"에 적용하면 의미있는 "(매출액)"까지 날아가 bare "수익"만 남고, 이건
`_REVENUE_TOTAL_LABELS`에 없다. 결과: 오염된 "영업수익"만 grand 후보 풀에
남아 `len(gvals)==1`로 그 오염값이 즉시 확정되고, 라벨이 달라 목숨을 건
정정본의 정확한 값은 애초에 경쟁조차 못 한다(R2 "정정이 이긴다" 위반).
"수익(매출액)"은 전사 최다빈도 매출 라벨(1,725개사/71,520행, R52)이라 이
결함의 잠재 노출면이 넓다.

**설계 제약(중요)**: `_REVENUE_TOTAL_LABELS`를 그냥 넓히거나(예: "수익" 추가)
`norm()`의 괄호 제거 자체를 바꾸는 **블랭킷 확장은 하지 않는다** —
2026-08-13 주석에 이미 기록된 반증 사례(같은 종류의 "그랜드토탈 우선을
일반화" 시도가 303:8로 회귀)와 같은 함정이 재현될 위험이 크다(예:
경창산업·LS 등 정당하게 "영업수익"≠"수익(매출액)"인 회사가 이미 DB에 다수
존재 — 연결/별도 다른 개념이거나 진짜 다른 계정, 실측 스캔에서 1,320행
/302개사 규모로 확인, 전부 버그가 아님). 대신 **R2 델타패치 provenance
(`amended` 플래그)가 실제로 존재할 때만** 개입한다 — 다른 라벨로 재보고된
후보가 (a) `amended=True`이고 값이 하나로 수렴하며, (b) 기존 bare grand
풀에 amended 멤버가 하나도 없을 때(=원본이 여태 안 고쳐진 채 남아있다는
신호)만 그 정정값을 확정한다. 그 외의 모든 경우(정정 관계 불명확·양쪽 다
amended·라벨이 달라도 애초에 값이 같음)는 기존 로직을 한 글자도 안 건드리고
그대로 통과한다.

**구현**: `_REVENUE_TOTAL_PAREN_RE = re.compile(r"^수익\((매출액|영업수익|매출
|순매출액)\)")`(정확히 `"수익(" + 총계라벨 + ")"`로 시작하는 라벨만 인식,
"재화의 판매로 인한 수익(매출액)"처럼 접두사 붙은 IFRS15 분해 하위라인이나
"...에 대한 매출원가" 접미사가 붙은 COGS류는 앵커(`^`) 때문에 매치 안 됨 —
이런 압축형이 애초에 `is.revenue`+`exact` 스테이지까지 오는 것 자체는
R52 가드가 이미 별도로 막고 있다). `_reduce_conflict()`의 is.revenue 분기에
"amended-paren이 bare-grand의 유일한 개정 신호일 때만" 우선권 부여 — 코드
변경 2곳, 둘 다 `fin2/layer3/combine.py`(`_REVENUE_TOTAL_PAREN_RE` 상수
신설 + `_reduce_conflict()` 개입 4줄).

**검증**: 신규 회귀테스트 4개(`fin2/tests/test_combine_curated_overrides.py`)
— 키네마스터/나이스디앤비 재현(정정값 확정) · 정정 관계 없을 때 무변화(대조군)
· bare grand 쪽에 이미 amended 멤버가 있을 때 개입 안 함(가드). `pytest
tests/ fin2/tests/` 758 passed(무관 기존실패 1건 `test_lxintl_facility_
table_dropped` 제외, 회귀 0). **2개사 스코프 재빌드**(`build_std_v3.py
--corp 00535375,00606293`): 키네마스터 revenue 5,042,936,384,000,000→
5,042,936,384(정답)·4,927,330,912,000,000→4,927,330,912, 나이스디앤비
revenue 59,247,429,676,000→59,247,429,676(정답)·39,912,392,874,000→
39,912,392,874 — 두 회사 전체 시계열(2011~2026) 재조회로 다른 기간·값
무변화 확인. `dq_assertions.py` 전수: `statement_magnitude_impossible`
40→**38**(키네마스터 2행 해소, 신규 위반 0건).

**근본원인 구분(스코프 밖, 별도 트랙)**: 이 R72는 **하류(resolve) 버그만**
고친다. 상류(왜 "영업수익" 원본 자체가 애초에 단위오염됐는가)는 두 회사가
서로 다르다 — 키네마스터는 그 rcept 하나만 단위판정이 튄 상류 추출버그로
보이고(같은 라벨의 다른 74개 필링은 전부 정상), 나이스디앤비는 원본 필링
자체가 BS/IS/CF 전체에 걸쳐 "(단위:천원)" 선언과 실제 자릿수가 안 맞는
**(가+라)류 원문 자기모순**(항목② 참고)이라 revenue 외에 total_assets도
오염돼 있는데, **그쪽은 XBRL 정정본이 재보고를 안 해 경쟁 후보 자체가 없어
이번 수정으로 해소되지 않는다**(resolve 로직 문제가 아니라 애초에 고칠 재료가
없음 — DQ격리 또는 R71 A-3류 규모/항등식 휴리스틱이 별도로 필요, 나이스디앤비
total_assets는 애초에 `statement_magnitude_impossible`의 1,000조 임계 밑이라
이 어서션에 잡힌 적도 없었다 — 완전히 별개의, 지금까지 안 보이던 결함).

**R72 트랙 완전 종료**(revenue 스코프만). `v2-drop-remaining-backlog-
2026-09-03`(메모리) 항목② 갱신 — 카테고리(사) revenue 하류버그 해소.

**★전사 백필 완료 및 회귀 0건 확정(2026-09-06, 같은 세션 이어서)**: 사용자가
`build_std_v3.py --all --year-min 1999`를 5-shard 병렬로 실행(전체
2,546개사, 1999년부터 전 기간 재빌드). `dq_assertions.py` 결과:
`statement_magnitude_impossible` 38→**41**(+3). 신규 3행 원인규명 —
corp 00198697(일진디스플 2000Q1)·00260958(케이티알파 2000H1×2행),
report_lines 직접조회로 `unit_source='pdf'` 확인 → Category C fy1999~2003
PDF복구 트랙(R69~R71) 산출물이며 XBRL시대 어휘("수익(매출액)")가 2000년
필링에 존재할 수 없어 R72 코드경로가 물리적으로 발동 불가 — **R72 회귀
아님, 확정**. 이번이 `--all --year-min 1999` 전사 규모의 첫 실행이라(기존엔
R69~R71가 스코프 한정 백필 스크립트로만 실행) 이 두 회사의 잠재된 기존
결함이 처음 드러난 것. 키네마스터·나이스디앤비는 재검증 결과 41건 목록에
없음(해소 유지). 신규 발견 2개사는 (가+라) 원문자기모순 그룹에 합류(별도
트랙, 항목②).

## R73. `fin2/layer3/unit_overrides.py` — 원문 자기모순 필링 수동 단위교정

> **상태** 유효 · **적용 계층** 3
메커니즘 신설 + 1호 사례(00138516 아남전자 FY2006) 적용 (2026-09-06)

**배경**: `statement_magnitude_impossible` 항목②의 (가+라) 그룹 — 표 자신이
인쇄한 단위 라벨이 실제 자릿수 규모와 안 맞는 케이스(코드 버그 아님, 원문
필링 자체의 표기 오류, R71/R72와 달리 자동 판정 규칙으로 일반화 불가). 지금까지
이런 건은 방치되거나(잘못된 값 노출) DQ<3 격리(값 자체를 숨김) 둘 뿐이었다 —
사용자 요청으로 **세 번째 선택지**: 사람이 원문을 직접 확인해 올바른 배수를
판정하면 그 판정을 DB에 반영해 정확한 값을 적재하고, 수동 교정임을 별도로
표시하는 메커니즘을 신설.

**설계**: `docs/plans/unit_override_self_contradictory_filings_design_2026-09-06.md`.
`report_lines`(원문 그대로 추출)는 손대지 않고, 기존 curated override들
(R16/R20/R21/R72)이 사는 `fin2/layer3/combine.py::combine_full()` 집계
단계의 마지막 순서에서 적용 — `(corp_code, fiscal_year, fiscal_period,
statement_type, concept)`(concept=DIRECT_MAP canonical, std 컬럼명 아님 —
한 필링 안에서도 개념별로 원인이 다를 수 있음, 나이스디앤비 revenue[하류
버그]/total_assets[원문모순] 분리 사례 참고) 키로 `col[std_col]`에 curated
배수(`multiplier`)를 곱한다. 각 항목은 근거(rcept_no·인쇄된 값·원문대조
일자)를 주석으로 필수 기재(★원본대조검증 원칙). 신규 컬럼
`std_financials_v3.unit_overrides`(jsonb, nullable)에 `{std_col: {concept,
declared_value, corrected_value, multiplier, note}}` 형태로 실제 적용된
셀만 기록 — SQL로 바로 조회 가능, 향후 시각화 화면 배지/각주 노출 가능.
`data_quality`(자동 항등식검증 점수)와는 별개 컬럼(의미 혼용 방지).

**마이그레이션**: `collector/db.py` MIGRATIONS
`"2026_09_std_financials_v3_unit_overrides"` — `ALTER TABLE
std_financials_v3 ADD COLUMN IF NOT EXISTS unit_overrides JSONB;`
(nullable, DEFAULT 없음 — PG11+ 즉시 완료). `collector/models.py`에
`StdFinancialV3.unit_overrides` 컬럼 추가.

**1호 사례 검증(00138516 아남전자 FY2006, bs.retained_earnings)**:
BS "1.처분전이익잉여금(결손금)" 행 **라벨 자체가** 괄호 안에 "당기순이익(손실):
제34기: 2,146,172,472원"이라고 원 단위로 명시하는데, 같은 표의 단위선언
"(단위:백만원)"을 따라 `adecimal=-6`이 적용돼 report_lines.value_won이
2,146,172,472,000,000(×10⁶ 과대)으로 저장됨. 같은 rcept(`20070330000181`)
안의 이익잉여금처분계산서(APPR)가 독립적으로 2,146,172,472(원 단위,
adecimal=0)를 재확인 — 두 표가 교차검증되는 명백한 원문 표기 오류.
`multiplier=1e-6`으로 등재(consolidated+separate 둘 다, 이 회사는
basis_fallback으로 별도=연결).

**구현/검증**: 신규 회귀테스트 5개(`fin2/tests/test_unit_overrides.py`,
순수 함수 — 매칭/비매칭/None가드/프로덕션 항목 검증). `pytest tests/
fin2/tests/` 762 passed(신규 5개 포함, 무관 기존실패 1건
`test_lxintl_facility_table_dropped` 제외, 회귀 0). 스코프 재빌드
(`build_std_v3.py --corp 00138516 --year-min 1999` — 기본 `--year-min
2015`로는 2006년이 안 걸린다는 점 확인 필요) + `calendarize_corp_v3`
동기화. **DB 반영 확인**: FY consolidated/separate 둘 다
`retained_earnings` 2,146,172,472,000,000→**2,146,172,472**로 교정,
`unit_overrides` 컬럼에 근거 기록됨. `dq_assertions.py` 전수:
`statement_magnitude_impossible` 41→**39**(00138516 2행 해소, 전수
재조회로 신규 위반 0건 확인, 나머지 39건 목록 불변).

**같은 세션 이어서 — (가+라) 그룹 나머지 원문대조 진행(2026-09-06)**:
9건+신규 2개사(00198697·00260958) 전수를 원문(SD카드 raw_report XML, EUC-KR
필요시 iconv/encoding='euc-kr')·PDF복구 트랙 산출물(unit_source='pdf')
내부정합성으로 대조. **10개사 등재 완료**(00102858 고려아연·00113207
대한전선·00117601·00138701 아세아·00143226 엠투엔·00163673·00260958
케이티알파·00366942 미코·00400121 유아이디·00487546 웰크론한텍) —
각 항목 BS 항등식(자산=부채+자본) 재성립 확인 또는 원문 라벨 자체에 실제값이
박힌 교차검증(00366942는 APPR 전기이월+반기순이익 합=BS raw÷10⁶ 정확 일치,
00400121은 각주 "(단위:원)" 명시 표+요약표 반올림 일치)으로 검증. 신규
회귀테스트 8개 추가(총 13개, `fin2/tests/test_unit_overrides.py`), `pytest
tests/ fin2/tests/` 770 passed(신규 8개 포함, 무관 기존실패 1건 제외, 회귀
0). 10개사 스코프 재빌드(`build_std_v3.py --corp ... --year-min 1999`)
+ `calendarize_corp_v3` 동기화. `dq_assertions.py` 전수:
`statement_magnitude_impossible` 39→**20**(19건 해소, 전수 재조회로 신규
위반 0건 확인).

★**등재 중 원문대조로 발견한 함정 — 00204226(소프트센 FY2022)은 (가+라)가
아니라 별개의 코드버그로 재분류**: raw XML 직접대조 결과, BS "이익잉여금
(결손금)" 행이 있는 3개년 비교표에서 report_lines가 뽑은 값(6,570,137,526)은
사실 **전기(FY2021) comparative 컬럼**이고, 진짜 당기(FY2022) 값은
**17,293,933,213**(전혀 다른 숫자, 단순 배수 관계 아님)임을 확인 — declared
unit이 실제 자릿수와 안 맞는 게 아니라 **애초에 컬럼을 잘못 골랐다**. 이
경우 unit_override로 "교정"하면 그럴듯해 보이는 오답(6,570,137,526)을
확정시켜버리므로 **등록하지 않음** — 별도의 컬럼선택 버그 트랙으로 이관
(원인: 이 표의 다년비교 레이아웃에서 col_index=0 판정 로직이 아직 안 맞는
것으로 추정, 코드 위치 미탐색). `fin2/tests/test_unit_overrides.py::
test_softcen_2022fy_is_not_registered`로 이 결론을 회귀 고정(향후 실수로
등록되는 것 방지). **같은 이유로 00378363(3S)도 미등록 유지** — raw XML에서
IS 매출액 행 후보가 여러 개(요약표·본문표) 나왔는데 그 중 어느 것이
report_lines가 실제로 뽑은 값과 일치하는지 이번 세션 내 확정 못 함(모호,
다음 세션 재조사 필요). **00163691·00198697도 미등록 유지** — PDF
추출 자체에 부호반전·계정쌍 뒤바뀜 등 단순 배수교정으로 설명 안 되는 노이즈가
있어(예: 00198697 연결 BS "자본금"↔"보통주자본금"이 부호만 반대인 동일크기
쌍으로 나타남) 원문 재조사 없이 배수만 곱하면 위험 — 원문 PDF 직접 재수집
(LegacyDartScraper) 후 재판단 필요.

**남은 (가+라) 그룹 잔여**: 위 4건(00204226·00378363·00163691·00198697,
성격이 서로 다름 — 앞 2건은 컬럼선택/모호성 버그 후보, 뒤 2건은 PDF노이즈)
+ 이번 세션 범위 밖이던 (나)`section_def`폴백 3건(00108746·00140168·
00258421)·(다)declared 경계오판정 계열 2건(00133751 세명전기·01344363
다원넥스뷰) + 재수집 트랙 4건(00122825·00124799·00125488·00133618, DART
503) + (마)임계값 오탐 후보 1건(00126380 삼성전자, 실제 초대형사라 버그
아닐 가능성 높음, 미확정) — 전부 unit_override 스코프 밖, 각자 다른
트랙(코드버그 수정·원문 재수집·정책결정)에서 별도 처리.

★**(다) 그룹 사후 재분류(2026-09-06, R74 사전조사)**: "declared 경계오판정"이라는
분류명 자체가 오분류였음이 드러남 — 01344363(다원넥스뷰)은 R74(else 분기)와 완전히
같은 메커니즘으로 이미 해소(재수정 불필요, `report_lines_sanemax_reject_
compaction_shift_design_2026-09-06.md` "후속 발견" 참고). 00133751(세명전기)은
컬럼 밀림이 아예 없는(값이 사한 상한 밑이라 거부 자체가 안 일어남) 순수 자기모순
단위 필링 — (가+라) 그룹(R73 unit_overrides 등재 후보)으로 재편입. **(다) 카테고리
소멸.**

★**(마)+"재수집 트랙 4건" 사전조사(2026-09-06, 구현 안 함)**: (마) 00126380
삼성전자는 원문대조 불필요 — `dq_assertions` 임계값을 근소하게 넘겼을 뿐(예:
total_equity 579조원, 임계 500조원) 실측상 진짜 초대형사 정상값. **버그 아님,
임계값 캘리브레이션 문제**(코드수정 아님, 필요시 향후 임계값 상향 검토).
"재수집 트랙 4건"(00122825·00124799·00125488·00133618, 원래 "DART 503"로
분류)도 원문대조 결과 **파일 자체는 전부 온전**(에러페이지 아님, 정상 크기) — 실제로는:
- 00122825·00125488·00133618 3건: 연결(consolidated) 표만 "(단위:백만원)"
  자기모순 선언(별도는 정상 원 선언) — (가+라) 그룹과 완전히 같은 패턴,
  unit_overrides 등재 후보로 재편입.
- 00124799(사조산업) FY2000(rcept `20010403000157`, `unit_source='pdf'`):
  연결 IS 전 라인이 **부호까지 반전**(매출액·매출원가 등이 전부 음수로 저장) —
  이건 단위 문제가 아니라 진짜 PDF추출 손상(Track④ 00198697 자본금↔보통주자본금
  부호반전 사례와 같은 성격) → **Track④(PDF재수집)로 재편입**. 같은 회사
  FY2001(rcept `20020401000221`)은 부호반전 없이 자기모순 단위만 있어(가+라)
  그룹 후보.
- Track④ 원래 2건(00163691·00198697)은 재확인 결과 이전 세션 판단 그대로
  유효(00198697: 자본금/보통주자본금 동일크기 부호반전쌍 재확인) — PDF 재수집
  필요, 변동 없음.

**전체 그림**: 애초 "6개 트랙"의 실제 근본원인은 사실상 2~3가지로 수렴 —
① 컬럼압축 버그(R74, 해소) ② 연결/별도 단위선언 불일치형 자기모순 필링(압도적
다수, unit_overrides 대상 — 지금까지 00133751·01344363(주1)·00122825·00125488·
00133618·00124799(FY2001) 6건 신규 확인, 기존 등재 11건과 합쳐 총 후보 다수)
③ PDF추출 자체 손상(00163691·00198697·00124799(FY2000), 재수집 필요). (주1)
01344363은 근본원인은 자기모순 단위지만 증상(컬럼밀림)은 R74로 이미 해소.

★**00258421 기산텔레콤 2006Q3 등재(2026-09-08, R84 이후 세션)** —
item2(나) 그룹(`docs/plans/section_def_fallback_wrong_sibling_unit_design_
2026-09-06.md`) 마지막 잔여. DKME(00108746)와 같은 구조: SECTION-2
"5.연결재무제표" 안 "가.요약연결재무정보"(단위:백만원)가 앞에 있고, 바로 뒤
실제 연결BS·IS 본표는 트레일러 단위선언이 공란이라 `nearest_section_
default_unit`이 앞쪽 요약표의 백만원을 잘못 물려받음. DKME(열선택버그)·
HS애드(R84로 별도 해결된 개념매핑버그)와 달리 이 건은 컬럼선택·개념매핑
둘 다 정상 — 순수 단위 문제뿐. **3중 교차검증**(원문대조 2026-09-08):
①BS "III.연결이익잉여금" 라벨 자체에 원단위 순이익 실측값 "당기
(8,101,839,101)원" 명시 ②IS "XV.연결당기순이익"(÷10⁶ 후 -8,101,839,101)이
①과 정확일치, "XIII.총당기순이익"=`"XIV.외부주주지분순이익"+"XV.연결당기
순이익"` 항등식도 ÷10⁶ 후 정확 성립 ③"가.요약연결재무정보"의 유동자산
65,047·당좌자산49,184·자본금7,059·연결이익잉여금3,493 전부와 본표÷10⁶
값이 정확 일치. rcept `20061114000692`의 BS/consolidated 74행+
IS/consolidated 79행 전부가 동일 오염이라 이 필링에서 도출되는 std_
financials_v3 canonical 15개(bs.cash/ppe/intangibles/short_term_debt/
long_term_debt/retained_earnings/trade_payables, is.cogs/sga/rd_expense/
operating_income/interest_expense/ebt/tax_expense/net_income) 전부
`multiplier=1e-6`으로 등재(참고: bs.total_assets/total_liabilities/
total_equity는 원문 "자 산 총 계" 류 글자간격 헤더를 파서가 못 걸러
report_lines에 아예 없어 NULL — 별개의 추출 갭, 이번 스코프 밖). 신규
회귀테스트 1개(`fin2/tests/test_unit_overrides.py::
test_kisan_telecom_2006q3_full_table_correction`), `pytest tests/
fin2/tests/` 859 passed(신규 1개 포함, 무관 기존실패 1건
`test_lxintl_facility_table_dropped` 제외, 회귀 0). 스코프 재빌드
(`build_std_v3.py --corp 00258421 --year-min 1999`, 205행, 에러 0) +
`calendarize_corp_v3`(212행, 에러 0). DB 반영 확인: 15개 컬럼 전부
×10⁻⁶ 교정, `unit_overrides`에 근거 기록됨. `dq_assertions.py` 전수:
`statement_magnitude_impossible` 3→**2**(기산텔레콤 소거, 잔존 2건은
이번 수정과 무관한 DKME[00108746, "결측 유지" 정책 결정된 채 값 자체는
아직 미정리]·삼성전자[00126380, 임계값 캘리브레이션 문제] — 전수
재확인으로 신규 위반 0건). 이걸로 item2(나) 3건(DKME/HS애드/기산텔레콤)
전수 원문대조·처리 완료(DKME=결측 유지, HS애드=R84 계정매퍼 수정,
기산텔레콤=본 unit_override 등재). 커밋은 사용자 확인 대기.

## R79. `account_mapper` — "차/대"·"임차/임대" 처럼 한 글자 차이로 뜻이

> **상태** 유효 · **적용 계층** 3
정반대(자산↔부채)가 되는 라벨 쌍이 fuzzy 매칭에서 서로 오매핑됨

배경: DB증권(00115694, 20010214000346) HTML뷰어 경로 검증 중 BS 155행 전수
원문대조(`docs/plans/html_viewer_extractor_design_2026-09-07.md` §8-11 후속,
사용자 지시 "155개 행 전수 원문대조 진행해줘")로 발견. `account_mapper`는 Stage 1/2
(exact/정규화 일치)가 Stage 3(Jaro-Winkler 퍼지)보다 항상 우선하는데, 문제의 두
쌍은 **정확한 쪽(alias) 자체가 등록 안 돼 있어서** 편집거리만 보는 퍼지가 뜻이
정반대인 반대쪽 alias 에 붙어버렸다:

- **"임차보증금"**(세입자가 낸 보증금, 자산) — exact alias 없음 → "임대보증금"
  (임대인이 받은 보증금, 부채, 한 글자 "임차"↔"임대"만 다름)에 오매핑. 실측: DB증권
  별도 BS 174억원이 `bs.other_noncurrent_liabilities`로 잘못 적재.
- **"이연법인세대"**(K-GAAP 구세대 대변=부채 표기) — exact alias 없음(신세대 표기
  "이연법인세부채"만 등록) → "이연법인세자산"(신세대, 자산)에 오매핑. 실측: DB증권
  별도 BS 2.3억원이 `bs.deferred_tax_asset`로 잘못 적재(진짜는 부채).

두 계정 모두 그랜드토탈(자산총계/부채총계/자본총계) 자체는 별도 라벨로 직접
뽑히므로 항등식 검증(T1 판정)엔 영향 없었지만, 세부 라인아이템이 계속 오염된
채 남아있었다 — HTML/PDF 두 추출기가 같은 `account_mapper`를 공유하므로 이
버그는 HTML뷰어 전용이 아니라 PDF 추출기에도 동일하게 존재했다.

수정: `account_maps/bs_accounts.py` 에 exact alias 4개 추가 — `bs.deferred_
tax_asset`+"이연법인세차", `bs.deferred_tax_liability`+"이연법인세대",
`bs.other_noncurrent_assets`+"임차보증금"(기존 "임대보증금"/`bs.other_noncurrent_
liabilities`는 그대로 유지, 정반대 뜻이라 병존해야 함). Stage 1/2가 이제 두
라벨 모두 exact 로 먼저 잡아 Stage 3 퍼지까지 안 감.

회귀테스트: `fin2/tests/test_account_mapper_lessee_deposit_and_kgaap_deferred_
tax.py`(5개, 반대쪽 alias 안 깨졌는지도 확인). `pytest fin2/tests/ tests/`
816 passed(무관 기존실패 1건 그대로, 회귀 0). 일반화 시사점: 이 프로젝트
account_mapper 어휘 전반에 "차/대"·"임차/임대" 류 1글자-반의어 쌍이 몇 개나
더 있는지는 미조사 — 이번엔 실측으로 걸린 2건만 수정(카탈로그화 원칙, 짐작
확장 안 함).

## R80. `account_mapper` 전체 어휘 스캔 — R79 패턴의 체계적 재현(형태소 반의어

> **상태** 유효 · **적용 계층** 3
갭 213건 발견, 실질위험 2그룹 확정·수정)

배경: R79(DB증권 155행 원문대조로 반의어쌍 2건 발견) 직후 사용자 지시
"전체 어휘 스캔을 별도 진행해봐"로, 등록된 818개 alias 전체(BS 294·IS
221·CF 253·NOTE 50)에 회계 반의어 11쌍(채권/채무, 매입/매출, 선급/선수,
예치/예수, 취득/처분, 차입/대여, 미수/미지급 등)을 적용해 미등록 변형이
`mapper.map()`에서 실제로 뭘로 판정되는지 전수 실행(스크립트는 job tmp,
비영속). 순수 유사도(Jaro-Winkler) 전수쌍 스캔도 병행(470건)했으나 대부분
이미 양쪽 다 정확히 등록된 "유동/비유동"류 정상 쌍(노이즈)이었고, 형태소
반의어 치환 스캔(213건) 쪽이 실질 신호였다.

**그룹1(간단한 alias 추가로 해결) — "비유동기타채무"**: 어순만 뒤집힌
"기타비유동채무"는 등록돼 있는데 이 변형은 없어 자산쪽 "비유동기타채권"에
fuzzy 오매핑됨. `account_maps/bs_accounts.py`의 `bs.other_noncurrent_
liabilities`에 exact alias 추가로 해결(R79와 동일 수법).

**그룹2(더 근본적 — canonical 자체가 없음) — CF/NOTE "취득"↔"처분" 반의어
6종**: "종속기업의처분"·"관계기업의처분"·"공동기업투자의처분"·"공동기업의
처분"·"투자부동산의취득"·"기계장치의취득"·"차량운반구의취득"·"산업재산권의
처분"·"자기주식의처분"(CF)·"자기주식처분금액"(NOTE) — "취득"(현금유출)
canonical 은 있는데 그 반의어 "처분"(현금유입) 전용 canonical 이 스키마에
아예 없어서, 처분 라벨이 찍히면 부호가 반대인 취득 계정으로 fuzzy 오매핑됨.
alias 추가로는 못 고침(정확한 반대쪽 코드가 없으니까) — 신규 canonical
코드 신설은 스키마 확장(하류 소비 코드 영향 검토 필요)이라 더 큰 결정이지만,
사용자가 "방어 우선"을 택해 `parser/common/account_mapper.py`의
`_FUZZY_BLOCK`(기존에 있던, 지금까지 빈 집합이었던 퍼지차단 메커니즘)에
정규화된 라벨 10개를 등록 — 부호오염 대신 무매핑(unknown)으로 떨어지게
방어만(결측이 오염보다 낫다). **전용 처분(inflow) canonical 신설 자체는
미착수 — 향후 별도 결정 사항으로 남음.**

회귀테스트: `fin2/tests/test_account_mapper_full_vocab_scan_2026-09-07.py`
(4개, 그룹1·그룹2 양쪽 + 원래 취득쪽/기존 처분쪽 매핑 안 깨졌는지도 확인).
`pytest fin2/tests/ tests/` 820 passed(무관 기존실패 1건 그대로, 회귀 0).

## R81. R80 "처분(inflow) 전용 canonical 미신설" 후속 — 사용자 지시 "처분

> **상태** 유효 · **적용 계층** 3
부분 추가하는것 진행해"로 실제 신설

R80 이 방어(`_FUZZY_BLOCK`)만 하고 미룬 "전용 처분 canonical 신설"을 진행.
먼저 하류 영향범위부터 확인: `cf.capex`/`cf.capex_intangible`만 FCF 계산
(`_CAPEX_CANON`, fin2/standardize/rules.py)에 쓰이고, M&A류(취득/처분 전부)는
원래 FCF 계산에 안 잡힘(대칭 유지 가능 확인). `app/registry/extended.py`
(확장재무 UI 표시)·`app/data/shareholder_return.py`(자사주 순취득 계산, 지금은
취득쪽만 읽음)도 확인.

**신규 canonical 4개**(account_maps/cf_accounts.py + note_accounts.py):
- `cf.disposal_of_subsidiaries`("종속기업의처분") — 대응 `cf.acquisition_of_
  subsidiaries`와 짝. M&A 현금흐름이라 `_CAPEX_CANON`엔 안 넣음(취득쪽도 원래
  안 잡힘, 대칭 유지).
- `cf.disposal_of_associates`("관계기업의처분"·"공동기업투자의처분"·"공동기업
  의처분") — 대응 `cf.acquisition_of_associates`와 짝.
- `cf.investment_property_acquisition`("투자부동산의취득") — 대응 `cf.
  investment_property_proceeds`와 짝. ★`_CAPEX_CANON`엔 **의도적으로 미포함**
  — FCF 정의를 조용히 넓히는 셈이라 별도 확인 필요, 미결정으로 남김.
- `cf.treasury_stock_proceeds`/`note.treasury_stock_proceeds`("자기주식의
  처분"/"자기주식처분금액") — 대응 `cf.treasury_stock_purchase`/`note.
  treasury_stock_purchase`와 짝. ★`app/data/shareholder_return.py`는 아직
  이 신규 canonical 을 안 읽음(순취득금액 넷팅은 별도 후속).

**신규 canonical 없이 기존 코드로 해결한 것**: "산업재산권의처분"은
`cf.ppe_proceeds`(일반 유형/무형자산 처분 버킷)에 등록 — 같은 문서의
"무형자산의처분"이 이미 그렇게 매핑되는 것과 동일 패턴(선례 확인 후 재사용,
새 코드 안 만듦).

**끝까지 무매핑으로 남긴 것**: "기계장치의취득"/"차량운반구의취득" 2개만
`_FUZZY_BLOCK`에 계속 유지 — 대응 처분쪽(`cf.ppe_proceeds_detail`)은 있지만
취득쪽은 보통 총계 라인(유형자산의취득→`cf.capex`)과 같이 찍혀 세부항목까지
별도 canonical 로 잡으면 총계와 중복계상 위험. 임시방편이 아니라 영구 방어.

**부수 발견(수정 안 함, 기록만)**: 이 조사 중 `cf.available_for_sale_net`가
취득·처분 양쪽을 **같은 canonical 하나로** 등록해둔 기존 패턴을 발견 —
실제 report_lines 에 "유동성매도가능증권의취득"(14억)과 "…의처분"(1억)이
같은 필링에 별도 행으로 동시에 존재하는 사례 실측 확인(00100601). 계층3에서
같은 canonical·같은 기간에 값이 둘 이상이면 `_resolve()`가 하나만 선택하는
구조라, 이 "순증감 공유코드" 패턴이 실제로는 둘 중 하나를 조용히 버리고
있을 가능성이 있음(진짜 net 합산이 아님) — 이번 스코프 밖이라 손 안 댐,
후속 조사 후보로만 기록.

`app/registry/extended.py`에 신규 canonical 4개 표시 라벨 등록.
`fin2/tests/test_account_mapper_full_vocab_scan_2026-09-07.py` 갱신(방어
기대→정확매핑 기대로 5개 테스트 재작성). `pytest fin2/tests/ tests/`
829 passed(무관 기존실패 1건 그대로, 회귀 0).

## R84. `parser/common/account_mapper.py` — Stage 3 fuzzy containment 가

> **상태** 유효 · **적용 계층** 3
2026-07-18 에 의도적으로 제외한 "미처분이익잉여금" 을 되살려 `bs.retained_
earnings` 오매핑 (item2(나) 트랙, HS애드 등 247개사/656행 실측 오염)

배경: 항목2(나)(`docs/plans/section_def_fallback_wrong_sibling_unit_design_
2026-09-06.md`) 재조사 중 00140168(HS애드) "미처분연결이익잉여금"이
`bs.retained_earnings`로 매핑되는 걸 확인, "개념 불일치 의심" → 계정매퍼
코드로 원인 추적.

**근본원인**: "미처분이익잉여금"은 2026-07-18(D4 2R)에 `account_maps/
bs_accounts.py`의 `bs.retained_earnings` exact alias 목록에서 **의도적으로
제거**됐다(총계='이익잉여금'의 sub-line 이라 총계 자리에 오면 과소·값충돌).
그런데 `AccountMapper._fuzzy_match()`의 "포함관계"(containment) 매칭이 alias
'이익잉여금'이 '미처분이익잉여금'의 부분문자열이라는 이유만으로(`len_ratio
=0.5`, `score=0.90+0.5*0.09=0.945 ≥ threshold 0.88`) 그대로 되살려 다시
`bs.retained_earnings`에 오매핑했다 — '미처분연결이익잉여금'·'미처분전이익
잉여금'·'당기말/분기말/반기말미처분이익잉여금'·'미처분이익잉여금(미처리
결손금)' 등 접두/접미 변형까지 전부 같은 경로로 새어나왔다. 같은 필링에
진짜 총계 라인('이익잉여금'/'이익잉여금(결손금)')이 있으면 `_resolve()`가
값 다른 후보 2개로 보고 conflict 로 안전하게 보류하지만, 없으면(흔함 —
인터림 BS 가 적립금 세부내역 없이 미처분 잔액만 보여주는 서식) 유일한
후보로 그대로 확정됐다.

**실측 규모**(DB 전수 SQL + `AccountMapper.map()` 직접 실행, 2026-09-08):
BS 통계표에 "이익잉여금" 계열 라벨이 있는 274,659개 (corp,rcept,basis)
조합 중, "미처분" 계열 라벨만 있고 비-미처분 총계 라벨이 없는 위험군
1,101행/247개사를 실제 `AccountMapper.map()`에 통과시킨 결과 **100%
(1,093/1,093)**가 `bs.retained_earnings`에 fuzzy 매핑됨을 확인(허위양성
없음). `std_financials_v3`와 교차대조 결과 **656행이 이미 라이브 DB에
이 오염값 그대로 저장돼 있었음**(26행 NULL, 419행 다른값=미조사). 표본
(00152437, 위험군 내 최다 108행) 자체 시계열로 "진짜 다른 값"임을 확인
(2007~2008년 매 기간 총계≠미처분, 적립금 차이 5~6억원+, 2011년부터
적립금 공시 자체가 빠지며 위험군 진입).

**수정**: `AccountMapper.map()`에 Stage 3 진입 전 가드 추가 — 정규화된
라벨에 "미처분"과 ("이익잉여금" 또는 "결손금")이 함께 있으면(`fs_section
in (None, "bs")` 한정) 무매핑(`unknown.*`)으로 차단. "결손금" 단독(음수
총계 표현, 기존 exact alias)은 "미처분"이 없으면 안 건드림 — Stage 1/2가
먼저 처리하므로 영향 없음. 코드 위치: `parser/common/account_mapper.py::
map()`, Stage 3(`_fuzzy_match()`) 호출 직전.

**회귀테스트**: `fin2/tests/test_account_mapper_undistributed_retained_
earnings_guard_r84.py`(8개 — 차단 대상 5종 변형 + 정상 매핑 3종 유지
확인). `pytest tests/ fin2/tests/` 857 passed(무관 기존실패 1건
`test_biz_section.py::test_lxintl_facility_table_dropped` 그대로, 회귀 0
— 코드 수정 전 동일 실패 재현으로 무관함 확인). 위험군 1,093행 재스캔
결과 사후 100%(1,093/1,093) `unknown`으로 차단 확인.

**백필(247개사, `--year-min 1999` 스코프 재빌드)**: `build_std_v3.py
--corp <247개사> --year-min 1999`(44,679행, 에러 0) + `calendarize_corp_v3`
247/247 성공(에러 0). 전/후 diff(`std_financials_v3.retained_earnings`,
같은 corp/fy/fp/statement_type): **786행 변경** — 627행 NULL로 전환(오염값
제거), **159행은 오히려 NULL→정답값으로 신규 확정**(진짜 총계 라인이 sub-
line 과 conflict 로 묶여 보류돼 있다가, sub-line 이 배제되며 단독후보로
승격된 경우 — 00427483 2009FY 연결 실측: `Ⅴ. 연결이익잉여금(주20)`=
154,120,712,864원이 이제 정확히 확정, 이전엔 `미처분연결이익잉여금`=
61,157,599,700원과 conflict 로 NULL 이었음).

**dq_assertions 전수 검증**: `statement_magnitude_impossible` 4→**3**
(00140168 HS애드 소거, 나머지 00258421 기산텔레콤·00108746 DKME·00126380
삼성전자는 이 수정과 무관한 별개 트랙 — DKME 는 "결측 유지" 정책 결정
완료, 기산텔레콤은 원문대조 미착수, 둘 다 이번 수정 대상 아님). 247개사
스코프 내 절대값 5×10¹⁵원 초과 잔존 0건. 다른 ERROR/WARN 어서션에 247개사
관련 신규 위반 없음(전수 재확인).

DKME(00108746)·기산텔레콤(00258421)은 이번 수정과 무관(라벨에 "미처분"이
없음 — "연결이익잉여금"/BS 전체 오염, 원인은 section_def 단위폴백이지
account_mapper 개념매핑이 아님, item2(나) 문서 참고). 커밋은 사용자 확인
대기.

---

## R116. `fin2/extract/report_lines.py::_Q1_CUM_BLANK_USE_3M_RCEPTS` — Q1

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 `_Q1_CUM_BLANK_USE_3M_RCEPTS` 목록의 Q1 필링에서 누적 칸이 공란인 행에 3개월 값을 채운다(표의 자기 증명 없이 목록으로). 계층2 에는 공란 그대로다. 일반 규칙은 R154.
> **코드** `fin2/extract/report_lines._Q1_CUM_BLANK_USE_3M_RCEPTS` · `_q1_cum_fill_on` · STEP `R154_q1_cum_fill`
보고서 "3개월=누적" 등식을 이용한 누적란 공백 대체 (예외목록, 2026-09-14~15)

> **★적용 계층: 3 (2026-10-11 사용자 결정, 2026-10-12 이행 완료)**. 누적 칸이 공란인 행에 3개월 값을 싣는 것은 **빈칸 채움**(R0-2)이다. 계층2 는 공란 그대로(인쇄값), 3개월 값은 계층3 보정(`layer3_cell_corrections` fill, STEP `R154_q1_cum_fill`)으로 싣는다. 이행 결과는 R154 절 끝.

**배경**: 형지I&C(20160516001490)·드림시큐리티(20160511001294) 2016 Q1
보고서는 IS 표 전체가 "3개월" 칸만 채우고 "누적" 칸은 공란이거나(형지) 서브타입
구분 없이 두 물리열에 완전히 같은 값을 중복 기재(드림)한다 — 두 필링 모두
"당기순이익" 행이 두 칸에 동일값을 채워 **1분기는 정의상 3개월=누적**이라는
등식을 필자 스스로 증명한다.

**설계 결정(R6 유지)**: 이 등식이 Q1에서만 성립하고(H1/Q3는 다름) 실측도
소수 필링에서만 확인되므로, "누적 공란 → 3개월로 대체 안 함"이라는 전사
원칙을 뒤집지 않고 **예외목록으로만 좁힌다**. `select_by_header_columns()`에
`allow_three_month_as_cumulative` 옵션 추가, `report_lines.py`가
`report_fiscal_period=="Q1" and rcept_no in _Q1_CUM_BLANK_USE_3M_RCEPTS`일 때만
전달.

**예외목록 누적 이력**: 형지I&C·드림시큐리티(원조) → 조광페인트
(20170512001930)·자이글(20190527000008, 2026-09-14 후속 실측, 동일 패턴) →
평화산업(20180515002398, 2026-09-15, IS_separate 이상치 재검증 중 발견 — 별도
손익계산서만 이 패턴, 연결은 정상이라 필링 하나만의 기재누락).

**2026-10-23 추가**: 형지I&C 2015 Q1 정정 제출본 20150515000009·20150519000237(웹뷰 인쇄본 출처) —
이미 목록에 있던 원본 20150514004898 과 같은 문서(별도 3개월 39,865,625, 누적 열 전부 공란)라 정정본도 같은
채움을 받게 했다(batch 233, 이슈 128298~128302). 테스트 `tests/test_r116_hyeongji_amendments.py`.

**2026-10-27 추가**: 강원랜드 2016 Q1(20160516001323, IS 연결·별도)·2017 Q1(20170515004574, IS 별도) —
IS 표가 3개월 열만 채우고 누적 열은 당기순이익 행까지 전부 공란이라 R154 자기증명이 없고, 계층3 에 IS 가 통째로
없었다(기계대조 `unmatched_table` 로 발견). 같은 회사 반기보고서의 `반기 누적 − 2분기 3개월` 이 이 1분기 3개월
값과 정확히 일치함을 외부 증거로 확인했다(20160816000077: 연결·별도 매출·매출원가, 20170811000749: 연결·별도 매출·
매출원가·당기순이익). 사용자 결정으로 예외목록에 추가. 테스트 `tests/test_r116_hyeongji_amendments.py`.

---

## R143. `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_tax_expense_value()`

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 `overlay_tax_expense_value()` 의 법인세비용 후보에서 라벨에 "차감전" 또는 "차감후"가 들어간 행을 제외한다(`_TAX_EXPENSE_EXCLUDE_KEYWORDS = ("차감전", "차감후")`, `not any(kw in label for kw in …)`). 그래서 "법인세비용" 부분문자열이 있어도 "법인세비용차감후 … 기타포괄손익"(OCI 세후) 행은 `is.tax_expense` 사실값으로 덮지 않는다. override 된 행(`manual_unit`·`proved_unit`)도 오버레이 대상에서 뺀다(R169 절).
> **판정 예** KB금융 `20260814004200`(2026H1)·`20260515002888`(2026Q1) 별도 포괄손익계산서: "법인세비용차감후 (반)기기타포괄손익" 행이 바로 위 "법인세수익(비용)" 값으로 덮이던 것 → 원문값(405/−62 백만원), `source_ref` 에 오버레이 흔적 없음. 연결 쪽은 진짜 "법인세비용" 행이 따로 있어 후보 2개 → `len(row_list) != 1` 가드로 스킵돼 원래 정상.
> **하지 않는 것** 후보가 2개 이상이면 스킵하는 기존 모호성 가드는 그대로다. 별도 쪽 "법인세수익(비용)" 라벨은 키워드 "법인세비용"과 매치되지 않는다.
> **코드** `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_tax_expense_value()` · 테스트 `fin2/tests/test_report_lines_inline_xbrl_overlay.py`
— "차감후"(OCI 세후) 라벨도 EBT 가드처럼 후보에서 제외 (2026-09-19, 계층2
원문대조 캠페인 fail #9~#10)

**배경**: 같은 조사에서 KB금융 2026년 신규 DOM 패턴(재무제표별 전용 트리노드)
필링 2건(`20260814004200` 2026H1, `20260515002888` 2026Q1)의 별도
포괄손익계산서에서 "법인세비용차감후 (반)기기타포괄손익"(OCI 세후) 값이 바로 위
"법인세수익(비용)" 행과 동일한 값으로 오귀속됨을 발견했다.

**발견**: raw XML 원문 자체는 완전히 정확했다(직접 재파싱 확인 — 두 행 모두
서로 다른 값). `overlay_tax_expense_value()`(R18/버그②, 2026-08-23 신설)의
후보 필터가 `_TAX_EXPENSE_LABEL_KEYWORD="법인세비용"` 포함 + `"차감전"` 미포함만
확인했는데, "법인세비용차감후 반기기타포괄손익"도 "법인세비용" 부분문자열을
가지면서 "차감전"은 없어(대신 "차감후") 그대로 통과했다. 별도(separate) 쪽은
진짜 법인세비용 행의 라벨이 "법인세수익(비용)"이라 애초에 키워드 자체와
매치되지 않아 후보가 이 OCI 행 하나뿐이 됐고, `is.tax_expense` XBRL 사실값이
그 자리에 잘못 덮어써졌다. 연결(consolidated) 쪽은 진짜 "법인세비용" 라벨이
별도로 존재해 후보가 2개가 되어 모호성 가드(`len(row_list) != 1`)에 걸려
스킵됐다 — 그래서 연결만 항상 정상이었다.

**수정**: `_TAX_EXPENSE_EXCLUDE_KEYWORD`(단일 문자열) → `_TAX_EXPENSE_EXCLUDE_
KEYWORDS`(튜플 `("차감전", "차감후")`)로 확장. 후보 필터를
`not any(kw in label for kw in _TAX_EXPENSE_EXCLUDE_KEYWORDS)`로 변경.

**검증**: 두 필링 모두 별도 OCI 행이 원문값(405/-62 백만원)으로 복원,
`source_ref`에 오버레이 흔적 없음(미적용) 확인. `fin2/tests/
test_report_lines_inline_xbrl_overlay.py`에 회귀테스트 1건 추가(총 14건 통과).
`raw_report/` XML 직접 재파싱 대조로 별도+연결 전체 265/265·249/249쌍 전량
일치(mismatch 0). `pytest tests/ fin2/tests/` 전체 1064 passed(기존 무관 실패
1건 제외).

**★캠페인 방법론 교훈(R139/R140 캠페인 후속)**: 이번 10건 조사 중 4건(SK스퀘어
`20230814001786`·현대자동차 `20231114002201`·삼성바이오로직스
`20260814003375`)은 실제로는 **코드 결함이 이미 사라진 stale review CSV**였다 —
`git stash`로 당시 세션 수정 유무와 무관하게 `extract_report_lines()`를 직접
호출하면 이미 정답이 나왔다(다른 배경 작업이 DB `report_lines`를 이미 고쳐놨는데
`layer2_review_queue`의 CSV/노트가 재생성 안 된 상태). **fail 판정 재조사 시
코드를 고치기 전에 먼저 `git stash`로 현재 HEAD 코드가 이미 정답을 내는지부터
확인할 것** — `layer2_review.py redo --rcept <rcept>`가 값을 안 바꾸면 stale
CSV, 바뀌면 진짜 결함.

---

## R146. `rule_additive_da()` 가 **같은 감가상각비를 CF·IS·주석에서 각각 더해** D&A 와 EBITDA 를 정수배로 부풀린다 — ★**미해결, 캠페인 종료 후 착수**(2026-09-19)

> **상태** 미해결로 적혀 있음(2026-09-19 제목 기준 — 현재 상태 확인 필요) · **적용 계층** 3

**★이 규칙은 아직 고쳐지지 않았다.** 사용자 지시로 별도 트랙에 등재만 해 둔 것이다
(2026-09-19). 아래는 발견 경위·실측 규모·설계 쟁점이고, **코드는 손대지 않았다.**

**증상.** `std_financials_v3.depreciation` / `amortization` / `da_total` 이 원문 값의
정확히 **2배**(CF+IS) 또는 **약 3.2배**(CF+IS+주석)로 저장된다. `rule_derive_ebitda`
가 `ebitda = operating_income + da_total` 이므로 **EBITDA 까지 그대로 전파**된다.

```
제주은행 2021FY 별도   감가상각비  5,451,000,000 → std_v3 10,902,000,000  (×2.00)
클리오 2017Q3 연결     감가상각비  1,665,242,528 → std_v3  3,330,485,056  (×2.00)
나이스디앤비 2019FY 연결 감가상각비 2,235,732,580 → std_v3  4,471,465,160  (×2.00)
더블유게임즈 2016Q3 별도 감가상각비   184,311,032 → std_v3    368,622,064  (×2.00)
```

**원인.** `fin2/standardize/rules.py:220 rule_additive_da()` 는 `_DEP_CANON` 을 **단순
합산**한다. 그런데 그 튜플이 같은 개념을 **출처별로 세 벌** 담고 있다:

```python
_DEP_CANON = ("cf.depreciation", "is.depreciation", "note.depreciation",
              "cf.rou_depreciation", "is.rou_depreciation", "note.rou_depreciation",
              "cf.roa_depreciation", "is.roa_depreciation", "note.roa_depreciation")
_AMORT_CANON = ("cf.amortization", "is.amortization", "note.amortization")
```

`cf.depreciation` 과 `is.depreciation` 은 **다른 항목이 아니라 같은 금액의 다른 출처**다
— 은행·증권처럼 감가상각비를 IS(판관비)에도 적고 CF(비현금 가산)에도 적는 서식에서
둘 다 잡히면 그대로 두 번 더해진다. `_DA_TOTAL_CANON` 은 `next()` 로 하나만 고르지만,
뒤이어 `da_total = da_direct + dep + amo` 로 **이미 2배가 된 dep/amo 를 다시 더한다**.

★같은 파일 `rule_additive_debt()` 의 주석 "각 leaf 개념은 단일 canonical 로만 매핑되므로
합산해도 이중계상 없음"이 **D&A 에는 성립하지 않는다** — 차입금 세부항목은 서로 배타적
이지만 `cf.*`/`is.*`/`note.*` 는 같은 것의 사본이다. 합산 규칙을 새로 쓸 때 "세부항목
합산"과 "출처 중복"을 구분할 것.

**실측 규모(2015+).** 라벨·금액이 **완전히 같은** CF∩IS 쌍만 센 하한값:

| | |
|---|---|
| 중복 개념 쌍 | 2,880 |
| 영향 `std_v3` 행 | **2,389행 / 119개사** |
| 그중 `ebitda` 가 NULL 아님 | 2,791 |
| 비율 분포(감가상각비 한정) | **×2.00 이 486행**, ×3.2 대역 21행(주석까지 3중) |

**★R144/R145 와 무관한 기존 결함이다.** 2026-09-19 std_v3 재빌드(304개사) 진단 중
제주은행에서 드러났지만, 재빌드 대상이 **아닌** 회사들(클리오·나이스디앤비·더블유게임즈·
HS애드)이 2026-09-17 빌드인 채로 이미 ×2 다. 제주은행에서 이제야 보인 이유는, 그전엔
별도 IS 자체가 유실돼(R144 ④ 셀 안 줄바꿈) **CF 값만 세어지며 우연히 맞았기** 때문이다
— 상류를 고치자 하류의 기존 버그가 드러난 사례.

**미결 설계 쟁점**(착수 시 실측으로 정할 것):

1. **출처 우선순위인가 최댓값인가.** `cf` 우선이 자연스러워 보이지만, CF 가 결합 표기
   (`감가상각비및무형자산상각비`)만 싣고 IS 가 분해해 싣는 서식이 있으면 해상도를 잃는다.
2. **"같으면 하나만"으로 충분한가.** 값이 미세하게 다를 때(반올림·표시단위) 중복인지
   진짜 별도 항목인지 구분이 필요하다. 단순 동일값 배제는 그 구간을 놓친다.
3. **`rou_`/`roa_` 파생도 같은 문제**를 갖는다 — 출처 3벌 × 개념 3종.
4. R145 §소급백필과 같은 질문: 고친 뒤 **std_v3 전수 재빌드**가 필요하다
   ([[gateb-full-reaudit-is-required-to-close]] — 표본으로 닫으면 재등장한다).

**재현 쿼리**(위 표를 그대로 다시 만든다):

```sql
WITH d AS (
  SELECT rl.corp_code, f.fiscal_year, f.fiscal_period, rl.basis, rl.statement,
         rl.label_raw, abs(rl.value_won) v
  FROM report_lines rl JOIN filings f USING(rcept_no)
  WHERE rl.report_fiscal_year >= 2015 AND rl.col_index = 0
    AND rl.statement IN ('CF','IS') AND rl.label_raw IN ('감가상각비','무형자산상각비')
    AND rl.value_won <> 0)
SELECT corp_code, fiscal_year, fiscal_period, basis, label_raw, v
  FROM d WHERE statement='CF'
INTERSECT
SELECT corp_code, fiscal_year, fiscal_period, basis, label_raw, v
  FROM d WHERE statement='IS';
```

---

## R153. R116/R120 열선택 **예외 플래그**가 EPS 경로에 전달되지 않아 EPS 행이 **두 경로 사이 틈으로 증발** (2026-09-20)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`

**발견 경로**: 행 단위 결측 탐지기(`fin2/audit/row_coverage.py`) 전수 센서스(회사별
1건씩 2,528개사). 형지I&C 20150514004898 [연결]·[별도] IS 에서 기본/희석/계속영업
주당이익 4행이 전부 결측으로 적출됐다.

**증상**: 같은 표의 일반 손익 행 17개는 정상 적재되는데 **EPS 4행만** 없다.

**원인 — 두 경로가 같은 함수를 다른 인자로 부른다**:
일부 필링은 손익계산서 열이 `[3개월|누적]` 2단인데 **누적 칸을 통째로 비워둔다**. R116 은
그런 Q1 필링을 예외목록(`_Q1_CUM_BLANK_USE_3M_RCEPTS`)에 두고 3개월 값을 누적으로 채택한다.
본류(`_emit_section_lines`)는 그 플래그를 넘겨 정상 행을 싣는다:

```python
pairs = list(select_by_header_columns(
    header_cols, row.amounts, raw_amounts=row.raw_amounts,
    allow_three_month_as_cumulative=(report_fiscal_period == "Q1"
                                     and rcept_no in _Q1_CUM_BLANK_USE_3M_RCEPTS),
    prefer_last_of_two_as_cumulative=(...)).items())
```

그런데 `_emit_eps_lines` 는 **같은 함수를 플래그 없이** 불렀다. EPS 행은 누적 칸이
공란이라 `pairs` 가 비어 `continue` 로 빠진다. 그리고 그 직후 본류의 EPS 위임 가드가
"`_is_eps_label` 이고 EPS 금액처럼 보이면 **무조건** 건너뜀" 이라 본류도 싣지 않는다 →
**행이 증발한다**. 어느 쪽도 "상대가 실었는지"를 확인하지 않는 구조다.

★R144 의 교훈("같은 판정을 두 경로가 각자 구현하면 갈린다")이 판정 **함수**만이 아니라
그 **인자**에도 적용된다. 같은 함수를 부르더라도 인자가 갈리면 결과가 갈린다.

**수정**: `_emit_eps_lines` 의 `select_by_header_columns()` 호출에 본류와 **같은 두
플래그**를 넘긴다(`report_fiscal_period`·`rcept_no` 는 이미 인자로 받고 있다).

**검증**: 예외목록 13건 전부 재추출 — **전건 EPS 행 복원 + 행 단위 결측 0건**.
형지I&C 20150514004898 은 EPS 16행 복원, 값도 원문과 일치(`'(7)'` → -7, `'4'` → 4).
같은 표의 일반 행은 불변(가산적 수정, 매출액 29,893,315,770 유지).
`pytest tests/ fin2/tests/` **1154 passed**.

**회귀 테스트**: `fin2/tests/test_r153_eps_column_exception_flags.py`. 상수 이름이 바뀌면
조용히 깨지므로 **플래그 배선 자체가 살아 있는지**도 소스에서 확인한다.

**스코프**: 예외목록에 든 필링 전부(현재 13건). 목록에 필링을 추가할 때마다 이 경로가
자동으로 같이 적용된다.

---

## R154. Q1 표가 **스스로 증명한** `3개월 = 누적` 등식을 읽어, 누적 칸이 공란인 행을 구제한다 — R116 예외목록의 일반화 (2026-09-21)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층2 는 Q1 누적 칸이 공란인 행을 싣지 않는다(인쇄된 그대로). 계층3 보정은 그 표가 스스로 "3개월 = 누적"을 증명할 때 — 3개월·누적이 둘 다 실값인 행이 하나 이상이고 그 행들이 **예외 없이** 같은 값 — 또는 R116 목록의 필링일 때, 3개월 값을 누적 값으로 채운다(`layer3_cell_corrections` fill).
> **판정 예** 기아 `20240516001819` 연결 IS `매출액 26,212,851 | 26,212,851`(증인) · `기본주당이익 7,125 | (공란)` → 계층2 없음, 계층3 fill 7,125
> **하지 않는 것** 반례가 하나라도 있으면(3개월 ≠ 누적) 그 표는 채우지 않는다. Q1 이 아니면 채우지 않는다(R156). 한쪽이 공란인 행은 증인이 아니다.
> **코드** `fin2/extract/report_lines._q1_cum_fill_on` · STEP `R154_q1_cum_fill` · **테스트** `fin2/tests/test_r154_q1_self_proving_cumulative.py`

> **★적용 계층: 3 (2026-10-11 사용자 결정, 2026-10-12 이행 완료 — 이 절 끝 "계층3 이행")**. 등식이 증명돼도 공란에 3개월 값을 싣는 것은 **빈칸 채움**(R0-2)이다. 계층2 를 공란 그대로 두면 검증(기계대조: DB = 인쇄값)이 이 셀을 다시 확인할 일이 없어진다. 증명 조건(아래)은 계층3 보정의 조건으로 그대로 쓴다.

**발견 경로**: 계층2 원문전체대조 캠페인 이슈#20(peer 세션 `camp-run-79` 보고).
기아 00106641 `20240516001819`(2024Q1) [연결]·[별도] 손익계산서에서
`기본주당이익` 행이 DB 에 **통째로 결측**. 원문에는 연결 7,125/전년 5,323,
별도 5,495/전년 2,251 이 있다.

**증상 — R153 과 같은 자리, 다른 이유**:
R153 은 플래그 **배선**이 빠져 EPS 경로가 열선택 예외를 못 썼다(배선 수정 완료).
이 건은 배선은 살아 있는데 **플래그가 켜지지 않는다** — R116 예외목록
(`_Q1_CUM_BLANK_USE_3M_RCEPTS`)에 기아가 없기 때문이다.

**원문 구조**(연결, 별도 동형):

```
헤더:        [3개월(0), 누적(1), 3개월(2), 누적(3)]
매출액:      26,212,851 | 26,212,851 | 23,690,660 | 23,690,660
매출원가:    19,976,744 | 19,976,744 | 18,317,258 | 18,317,258
…(전 행 동일)…
기본주당이익:      7,125 |    (공란) |      5,323 |    (공란)   ← 유실
```

R144 정책상 2단 헤더 표는 **누적 열만** 싣는다. EPS 행은 누적이 공란이라 `pairs` 가
비고 → EPS 경로가 `continue`, 본류는 EPS 위임 가드로 건너뜀 → **행 증발**.

**왜 예외목록으로는 부족한가**:
R116 이 rcept 예외목록으로 좁힌 이유는 "실측이 두 필링에서만 확인됐다"였지 **등식이
의심스러워서가 아니다** — 1분기는 정의상 연초부터 분기말까지의 누적이 곧 그 3개월
자체다. 목록 방식은 같은 서식을 쓰는 다른 회사·연도를 계속 흘린다.

★**정정**(2026-09-21, 백필 dry-run 중 확인): 처음 이 규칙을 쓸 때 "현대사료
`20260515002785` 도 같은 모양"이라고 적었는데 **틀렸다**. 현대사료는
`['기본주당이익(손실)', '', '', '15', '']` 로 **당기 칸이 3개월·누적 둘 다 공란**이다 —
원문에 당기 EPS 가 아예 없는 것이라 구제 대상이 아니다(R154 가 켜져도 전기만 나오고,
전기는 `_PERIOD_AXIS_STATEMENTS` 정책상 애초에 적재 대상이 아니다). 기아는 당기
3개월이 **채워져 있다**(7,125) — 그게 이 규칙이 구제하는 모양이다. 실제 규모는 아래
검증란의 백필 실측치를 볼 것.

★같은 이유로 **이화공영 `20250515002174`·로보티즈 `20220816000335` 류도 결함이
아니다** — 전기 누적만 차 있고 당기가 공란이라, DB 에 당기 EPS 가 없는 게 정상이다.
"추출됐다"와 "DB 에 실린다"는 다르다(IS 는 col_index=0 만 적재).

**수정 — 목록 대신 표 자신의 증거**
(`fin2/extract/report_lines.py::_q1_cumulative_proved_equal_to_three_month`):

같은 period_rank 안에 `three_month` 와 `cumulative` 열이 둘 다 있는 표에서,
**양쪽이 다 실값인 행**을 증인으로 센다.

- 증인이 1개 이상이고 **전부 3개월 == 누적** → 증명됨 → `allow_three_month_as_
  cumulative=True`
- 반례가 **하나라도** 있으면(3개월 ≠ 누적) 즉시 거짓 — 그 표는 애초에 이 축이 아니다
- 한쪽이 공란인 행(= 구제 대상)은 증인이 못 된다(자기 자신으로 자기를 증명할 수 없다)

호출측이 `report_fiscal_period == "Q1"` 을 확인한 뒤에만 부른다(등식은 Q1 에서만 성립 —
H1/Q3 는 3개월 ≠ 누적).

★**R6 와 충돌하지 않는다**. R6 이 막는 것은 "서로 다른 값 중 하나를 짐작하는" 것이다.
여기서는 짐작하지 않는다 — **필링 자신이 표에 적어 둔 등식을 읽을 뿐**이다. 반례가
하나라도 보이면 규칙이 꺼지므로, 등식을 지키지 않는 표에는 절대 발동하지 않는다.

★**판정은 표당 한 번**, 본류와 EPS 경로에 **같은 값**을 넘긴다. R144/R153 의 교훈
("같은 판정을 두 경로가 각자 하면 갈린다")을 그대로 지킨다.

**R116 예외목록은 그대로 둔다** — 그 목록의 필링들은 증인이 1행(당기순이익)뿐이라
자기증명 규칙으로도 통과하지만, 목록을 지우면 원문이 바뀌었을 때 조용히 동작이 달라진다.

**검증**:
- 기아 `20240516001819` — 원문 네 값 전부 복원(연결 7,125/5,323, 별도 5,495/2,251)
- 같은 표의 일반 행 불변(연결 매출액 26,212,851백만, 별도 15,711,802백만 유지)
- 증거 판정 단위 테스트: 반례 1개로 규칙이 꺼지는지 / 공란 행이 증인이 안 되는지 /
  무표지 병합군(R120/R131 축)은 대상 밖인지
- `pytest tests/ fin2/tests/` **1163 passed**

**스코프**: Q1 필링 중 `[3개월|누적]` 2단 헤더 표 전부.

**백필 실측**(`scripts/backfill_r154_q1_eps.py`, 2026-09-21 완료): 2015+ Q1 손익계산서
적재 26,339건 중 EPS 0건인 후보 906건을 전수 재추출 → **77건 복원(273행) 적재, 오류 0**.
나머지는 원문에 당기 EPS 가 없는 정상 건이다(전기만 있거나 EPS 행 자체가 없음).

★**77건을 R154 의 성과로 읽으면 안 된다.** 재추출은 그동안 쌓인 **모든 미백필 수정을
한꺼번에** 반영한다. 표별로 R154 발동 여부를 다시 판정해 나눈 결과:

| 구분 | 건수 | 내용 |
|---|---:|---|
| **R154 발동** | 21 | 2단 헤더 + 자기증명 성립 (아즈텍WB·엠로 등) |
| 2단 헤더 아님 | 54 | **다른 규칙**이 이미 고쳤는데 Q1 필링에 백필이 안 돌았던 것 — 대부분 R149(`'3,682원'` 원 접미사). 하나금융지주·카카오뱅크·LG씨엔에스 등 |
| 2단인데 미증명 | 2 | 다른 경로로 복원 |

★교훈: **백필 복원 건수를 특정 규칙의 효과로 귀속하지 말 것.** 세 번 연속 같은 실수를
했다 — "추출됐다 ≠ DB 에 실린다", "복원됐다 ≠ 이 규칙이 고쳤다". 귀속하려면 그 규칙의
발동 조건을 **표별로 다시 판정**해야 한다.

**관련**: R116(예외목록 원형) · R144(누적 열 정책) · R153(플래그 배선) · R6(짐작 금지)

---


**계층3 이행 (2026-10-12, fix batch #126, 커밋 `b966e31`·`e8bf11d`)**
- 코드: `as_printed` STEP `R154_q1_cum_fill`. 본류·EPS 경로가 같은 `_q1_cum_fill_on()` 하나를 묻는다(R153). 인쇄값 추출(규칙 끔)에서는 그 행이 계층2 에 없고, 규칙 켬 추출과의 차이가 `layer3_cell_corrections` fill(`row_data` 포함)로 간다. 채움은 표를 읽는 단계(첫 checkpoint 전)에서 일어나 단계 추적으로 이름을 붙일 수 없으므로, 이름 없는 Q1 누적 차이가 있는 필링만 이 STEP 하나를 끈 추출을 한 번 더 해 달라지는 셀에 `R154_q1_cum_fill` 을 붙인다(`layer3_corrections._r154_keys`).
- 대상: 계층2 행에는 채움 표시가 없어 원문을 다시 읽었다(`scripts/scan_r154_q1_cum_fill.py`, 읽기 전용, SD 미러). 2015+ Q1 XML·웹뷰 필링 26,397건 → **399건**(326개사, 2024~2026 224건 — EPS 칸만 공란인 기아형), 오류 0. 목록 `docs/qa/r154_q1_cum_fill_targets.txt`.
- 재적재 `vq.py batch reload 126 --sd`(4샤드): done 399 · deferred 0 · failed 0. 계층2 IS **538행 감소**(전부 채움 행). `report_lines_l3` 는 재적재 전과 같다 — 차이는 `20160513004276` 별도 EPS 2행이 원래 같은 키로 두 번 적재돼 있던 것이 하나로 합쳐진 것뿐(값 동일).
- 계층3: 326개사 `build_std_v3.py --year-min 2015`·calendar(orphan 0). std_v3 44,664행 **값 차이 0**(`amended_cols` 목록 순서만 다른 12행 — 기존 비결정성). 재빌드에서 드러난 결함 하나를 고쳤다: `select_canonical_rcepts` 가 계층2 를 봐서, 별도 IS 전체가 fill 뿐인 00874803 2017Q1(`20170512006316`)의 `source_rcepts` 에서 IS 가 빠졌다 → `report_lines_l3` 를 보게 수정(`e8bf11d`), 재빌드 후 복구.
- Gate B(326개사 `--recheck`, 2015+): pass 23,370 · fail_a 6 · fail_b 31 · pending 2,947. std_v3 값이 그대로이므로 이 변경으로 바뀐 판정은 없다(1분기 실패 4행: 00108135 cogs 는 같은 회사 전 기간 공통, 00157636 2017Q1 별도 tax_expense 는 DB 368,467,239 = 세전 2,364,598,040 − 순이익 1,996,130,801 이고 대조 원천이 36,846,729). DQ ERROR 0.

## R159. **원문 자체의 오타 셀**을 rcept 예외목록으로 교정 (2026-09-22, R118 패턴)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 원문 자체의 오타 셀을 rcept 예외목록 `_SOURCE_TYPO_CELL_FIXES`(`(rcept_no, 깨진 셀 문자열) → 정정 문자열`)로 교정한다. 정정값이 원문으로 추측 없이 확정될 때만 등재하며, 인정 근거는 두 가지다: (가) 정수판이 원문 다른 곳(같은 열의 다른 행, 반대 basis 표, 다른 재무제표 어디든)에 인쇄돼 있다, (나) 그 행의 합계 항등식(인쇄된 합계 열)이 정확히 닫힌다. 근거는 항목마다 주석으로 반드시 남기고, 오타 교정은 R158 복원보다 먼저 적용하며, `extract_rows`(BS/IS/CF)와 `report_lines._grid_body_rows`(SCE) 두 경로 모두에 `rcept_no` 를 넘겨 배선한다.
> **판정 예** 핸즈코퍼레이션 `20260515002776` 자본변동표 자본금 열 `'10,937,873.5'` → `10,937,873,500`(같은 열 `2025.01.01 (기초자본)` 행에 정수 인쇄, 근거 가). HD한국조선해양 `20250515002500` 연결SCE 비지배지분 열 `'(41.423)'` → -41,423,000, `'(1,259.803)'` → -1,259,803,000, `'3,082.923'` → 3,082,923,000(지배기업 소유주지분 합계 + 비지배지분 = 자본 총계가 세 행 모두 정확히 닫힘, 근거 나, 사용자 원문 확인).
> **하지 않는 것** 정정값이 원문으로 확정되지 않으면 등재하지 않는다. 스캔 스크립트가 근거를 찾아도 자동 등재하지 않고 사람 확인 후 수동 등재한다. 같은 행에 정수 짝이 있는 경우는 R158 의 몫이다. 셀 몇 개를 고치려고 `manual_report_lines` 로 스코프 전체를 delete-then-insert 하지 않는다.
> **코드** `parser/xml/table_extractor.py::apply_source_typo_fixes`, `_SOURCE_TYPO_CELL_FIXES`; 후보 스캔 `scripts/report_dot_typo_candidates.py::_find_identity`(깨진 셀을 포함하는 최대 4개 부분집합, `t == mi` 이면 그 앞 전부의 합)
> **코드 확인** (2026-10-12) 교정 목록은 `parser/xml/table_extractor.py::_SOURCE_TYPO_CELL_FIXES`, 적용은 `as_printed` STEP `R159_typo`(`repair_on`) 뒤 — 계층2 인쇄값 추출에서는 꺼져 있고 차이가 `layer3_cell_corrections` 로 간다. 본문 위치와 상태 줄이 둘 다 맞다.

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견 경로**: R158 적용 후 잔여 8행 조사. 핸즈코퍼레이션 00119140 `20260515002776`
(2026Q1) 연결·별도 자본변동표 **자본금** 열의 `'10,937,873.5'`.

**사용자 진단**(2026-09-22): `,500` 이 `.5` 로 찍힌 **오타**다.

**정정값이 원문으로 확정된다** — 같은 표 `2025.01.01 (기초자본)` 행의 같은 열에
`10,937,873,500` 이 정수로 인쇄돼 있고, 자본금은 그 사이 변동이 없다. 추측이 아니다.

```
2025.01.01 (기초자본)   '10,937,873,500'   ← 정수(정답)
2026.01.01 (기초자본)   '10,937,873.5'     ← 깨진 셀, 같은 자본금 열
```

★R158(같은 **행**의 정수 짝 대조)은 이 건을 복원하지 못한다 — 정답이 같은 **열**의
다른 행에 있기 때문이다.

**왜 `manual_report_lines` 를 쓰지 않는가**(사용자 확인 후 A안 채택):
`store_manual_report_lines()` 는 `(rcept_no, statement, basis)` 스코프를 통째로
delete-then-insert 한다. 셀 4개를 고치려고 **SCE 연결 52행 + 별도 28행 = 80행을 전부
손으로 옮겨 적어야** 하고, 그 스코프는 `unit_source='manual'` 이 되어 이후 자동 재추출의
manual 보호 가드에 막힌다 — 정상인 나머지 76행이 파서 개선 혜택에서 영구 제외된다.
게다가 파서 산출물을 옮겨 적는 것은 "사람이 원문을 읽고 입력한다"는 manual 의 취지와도
맞지 않는다.

**수정**(`parser/xml/table_extractor.py`):

```python
_SOURCE_TYPO_CELL_FIXES = {
    ("20260515002776", "10,937,873.5"): "10,937,873,500",
}

def apply_source_typo_fixes(cells, rcept_no): ...
```

**등재 조건**(사용자 확정): 정정값이 **원문으로 추측 없이 확정될 때만**. 근거를 주석에
반드시 남긴다(회귀 테스트가 항목마다 근거 주석 존재를 검사한다). 인정되는 근거 두 가지:

**(가) 정수판이 원문 다른 곳에 인쇄돼 있다** — 같은 열의 다른 행, 반대 basis 표, 다른
재무제표 어디든. 실측 등재:

| 필링 | 깨진 셀 | 정수판 위치 |
|---|---|---|
| 핸즈코퍼레이션 `20260515002776` | `10,937,873.5` | [별도SCE] `2025.01.01 (기초자본)` 같은 열 |
| 트리니티항공 `20260515001132` | `41,106,779.959` | [연결SCE] `2025.01.01 (기초자본)` 같은 열 |
| 트리니티항공 | `64,885,221.582` | [연결SCE] `유상증자` |
| 트리니티항공 | `281,021,610.634` | [연결BS] `주식발행초과금` |

**(나) 그 행의 합계 항등식이 정확히 닫힌다** — 합계 열이 원문에 인쇄돼 있으므로 이것도
추측이 아니다. 실측 등재 — 코오롱 `20260515002605` 연결SCE `주식선택권의 부여`
(열 구조 `[… 기타자본구성요소, 지배지분 합계, 비지배지분, 자본 합계]`):

```
138,959,866 + 43,752,934 = 182,712,800   ← 자본 합계 열(원문 인쇄값)
393,211,876 +  7,823,674 = 401,035,550
```

★코오롱은 **한 행에 오타가 두 칸** 있다(사용자 지적). 왼쪽 `지배지분 합계` 칸은 바로 옆
정수와 같은 값이라 R158 이 행 안 대조로 복원하고, 남는 `비지배지분` 칸을 (나)로 등재했다.

HD한국조선해양 `20250515002500`(2025Q1 연결SCE, 사용자 DART 원문 직접확인 2026-09-23)도
(나)에 해당한다 — 세 행 모두 정수판이 다른 칸에 없어 R6/R160 목록(`docs/qa/
dot_typo_needs_dart_2026-09-23.md`)으로 확인을 요청했었다. 사용자가 원문을 보고 셋 다
콤마 오타로 확정:

```
자본 총계>비지배지분 열, [연결] 자본변동표
'(41.423)'      → -41,423,000   (기타포괄손익-공정가치측정금융자산평가손익, row_order=2)
'(1,259.803)'   → -1,259,803,000 (파생상품평가손익, row_order=3)
'3,082.923'     → 3,082,923,000  (파생상품평가손익, row_order=15)
```

복원값은 그 행 자신의 항등식으로 검산된다 — 지배기업 소유주지분 합계 + 비지배지분 =
자본 총계 합계(세 행 모두 정확히 닫힘). `apply_r158_dot_typo_confirmed.py --apply` 로
재적재(status='pass' 라 R139 가드 우회 필요, `overwrite_reviewed=True`).

HD한국조선해양 `20250318001131`(2024 사업보고서) 연결SCE `파생상품평가손익`
**비지배지분** 칸도 사용자가 확정했지만, 이 건은 `report_dot_typo_candidates.py`
의 항등식 검사기 자체가 **놓치고 있던 패턴**을 드러냈다 — 자세한 원인·수정은 바로
아래 "확인요청 스캔 스크립트 — 2단 항등식 놓침 수정" 참고.

### 확인요청 스캔 스크립트 — 2단 항등식 놓침 수정 (2026-09-23)

`scripts/report_dot_typo_candidates.py` 의 근거(나)(행 항등식) 검사가 **`vals[:t]`
전부를 더해 `vals[t]` 와 비교**하는 방식이었다. SCE 는 흔히 2단 구조다 —
구성요소(자본금..이익잉여금) → **부분합**(지배기업 소유주지분 합계) → **부분합 +
비지배지분 = 총계**. 전부 누적하면 구성요소와 그 부분합을 **동시에** 더해
이중계산이 되어 절대 안 닫힌다.

HD한국조선해양 `20250318001131` `파생상품평가손익` 행에서 사용자가 손으로 이
항등식(부분합+비지배지분=총계)을 확정하고 나서야 드러났다 — 스캔은 이 셀을
"근거 없음"(DART 확인 필요)으로 분류했지만 실제로는 항등식이 명확히 닫혔다.

**수정**: `_find_identity()` 로 교체 — `vals[:t]` 전체가 아니라 **깨진 셀 값을
포함하는 작은 부분집합**(최대 4개, 총계에 가까운 열부터 우선)을 찾는다. 부분합
열 자신이 총계인 경우(`t == mi`)는 기존처럼 "그 앞 전부의 합"으로 정의를 유지한다
(그건 부분합의 정의 자체이지 탐색이 아니다).

**효과**(전수 233필링 재스캔, 2026-09-23): `dot_typo_needs_dart` 목록
40필링/166셀 → **27필링/105셀** (58셀이 자동으로 근거를 얻어 DART 확인 불필요
해짐). ★근거가 붙어도 **자동 등재는 안 한다** — R6 원칙대로 사람 확인 후 여전히
`_SOURCE_TYPO_CELL_FIXES` 수동 등재.

★**적용 순서** — 오타 교정을 R158 복원보다 **먼저** 한다(교정된 셀은 정상 정수가 되므로
복원이 건드릴 일이 없어진다). 테스트가 소스에서 이 순서까지 확인한다.

★**두 경로 모두에 배선**: `extract_rows`(BS/IS/CF)와 `report_lines._grid_body_rows`
(SCE). `rcept_no` 를 두 함수에 optional kwarg 로 넘긴다 — R158 때 한 경로만 고쳐
SCE 가 새는 일을 이미 겪었다.

**검증**: 자본금 8행(연결·별도 × 4기간) 전부 `10,937,873,500` 으로 정정, 남은 왜곡 0.
같은 필링 EPS 4행 불변(`-1,500`·`-1,483`·`-768`·`-758`).

---

## R162. SCE 표 원문에서 음수 괄호가 빠져 자본변동표 셀이 부호 반대로 적재된다 — **교차대조(방향) + 열 롤포워드 항등식(자격)** 으로 복원 (2026-09-22, 이슈#28)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 셀의 원문 음수 괄호가 빠져 부호가 반대로 적재된 경우, (가) BS/IS 교차대조(같은 필링·같은 basis·같은 개념의 부호 = 방향 앵커)와 (나) 열 롤포워드 `기초 + Σ변동 = 기말`(적용 자격)을 **둘 다** 충족하는 셀 단위 배정만 복원한다. `col_label` 은 계층 접두어를 뗀 마지막 조각으로 맞춘다. 잔액행 앵커는 이미 확정된 블록의 잔액 셀에서 모은 `{절대값: 부호}` 를 **잔액행에만** 쓰고(인접 블록이 아니라 같은 열 전체에서 찾고, 진전이 없을 때까지 반복, 같은 절대값에 부호가 엇갈리면 그 절대값은 버림)(R162-b), 소계는 (가) 라벨 `_SUBTOTAL_LABEL_RE`(`소계|합계|총계|총포괄|총기타포괄`, 자간 공백·접두 기호 허용)와 (나) 그 행 절대값 = 앞선 연속 구간의 합을 **둘 다** 만족할 때만 인정해 Σ변동에서 빼고, 부호는 구성요소 합의 부호로 정하며(구성요소 1개인 소계도 인정, 소계로 판정된 행은 다음 구간 합산에서 제외)(R162-c), 그 뒤에도 닫히지 않는 블록에서 **양수 셀 하나**의 부호만 뒤집으면 롤포워드가 정확히 닫히고 그런 셀이 **정확히 하나**이면 그 셀을 뒤집는다(R162-e, anchor_label `R162-e 롤포워드 단일셀`). 앵커가 원리적으로 없는 셀은 사용자가 개별 승인해 `_MANUAL_SIGN_FIXES`(키 `(rcept, basis, label_raw, concept, row_order)`)에 등재된 것만 old_value 가 일치할 때 적용하며, 신규 승인 없이 항목을 추가하지 않는다.
> **판정 예** 효성중공업 `20190515002585`(2019Q1) SCE `순확정급여부채의 재측정요소` `307,150,286`(IS 는 `(307,150,286)`) → 이익잉여금 열이 음수일 때만 닫히므로 음수로 복원; 기타자본구성요소 열은 기초 `30,162,524,009`·기말 `29,461,715,719` 잔액만 음수로 복원하고 변동행 448,570 / 700,359,720 은 양수 유지. SK텔레콤 `20210517001554` 별도 SCE `2021.03.31 (기말자본)` 자기주식: 열 롤포워드와 행 내부 분해가 일치해 `+2,169,660,000,000` → `−2,169,660,000,000` 개별 확정.
> **하지 않는 것** 열 전체 일괄 반전(멀쩡한 변동행을 망침). 음수로 파싱된 셀은 후보가 아니다. 항등식이 이미 닫힘 / 만족 배정이 여러 개 / 앵커가 하나도 없음 / 앵커와 모순 / 후보 셀이 `_MAX_AMBIGUOUS_CELLS`(14) 초과면 손대지 않는다(R6; 효성중공업 연결 이익잉여금 열은 회계정책변경 효과 행 + `307,150,285` vs `286` 1원 불일치로 닫히지 않아 그대로 둠). (가) 단독·(나) 단독 금지. 소계를 산수만으로(`당기순이익(손실)`·`해외사업환산손익`·`감자차손보전` 오탐) 또는 라벨만으로 판정하지 않는다. 변동행을 이월잔액 절대값으로 맞추지 않는다. R162-e 후보가 둘 이상이면 판정불가이고, 앵커/이월잔액이 양수로 정한 셀은 뒤집지 않는다. R162-d 전체 백필은 보류. 수동 revert 는 camp_run 등록값을 믿지 않고 열 롤포워드로 직접 역산해 방향을 정한다(두산 batch #13 revert 5항목 삭제). 한화오션 2015FY #84772, 두산 2019 row44 `-확정급여제도의 재측정요소`·두산 2017·2018 잔여·제주반도체 2018 `회계정책변경`·`기타포괄손익` 형제열은 손대지 않는다(sign_flip 동결). 같은 증상은 캠페인에서 신규 결함으로 올리지 않고 이슈#28 로 묶는다.
> **코드** `fin2/extract/sce_sign_repair.py::repair_sce_sign_loss()`(`extract_report_lines()` 맨 마지막), `_subtotal_fixes`, `_solve_single_flip`, `_MANUAL_SIGN_FIXES`/`apply_manual_sign_fixes()`; IS 예외 `fin2/extract/report_lines_xbrl.py::_MANUAL_IS_SIGN_FIXES`/`_apply_manual_is_sign_fixes()`(E1 `20180130000271`); 재적재 `scripts/apply_r162_manual_issue38.py --apply`; 테스트 `fin2/tests/test_r162_sce_sign_repair.py`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**성격**: **파서 결함이 아니다.** DART 원문 자체가 같은 개념을 표에 따라 다르게
렌더링한다 — BS·IS 는 괄호로 음수를 표시하는데 같은 필링의 SCE 표에서는 괄호가
빠져 있다. 파서는 원문 그대로 전사했다.

**실측 원문**(효성중공업 `20190515002585`, 2019Q1):

```
BS_S  TR38: ['기타자본구성요소', '(29,461,715,719)', '(30,162,524,009)']
IS_S  TR21: ['순확정급여부채의 재측정요소', '(307,150,286)', '(307,150,286)']
SCE_S TR5 : ['순확정급여부채의 재측정요소', '', '', '307,150,286', '', '307,150,286']
```

원문 문자열 카운트로도 교차확인했다 — `'307,150,286'` 8회 중 괄호가 붙은 것은 4회
(IS 연결·별도 각 2회)뿐이고 SCE 쪽 4회는 괄호가 없다.

**참값은 추정이 아니라 항등식으로 확정된다** (열 롤포워드가 두 군데서 정확히 닫힘):

| 열 | 기초 | 변동 | 기말 |
|---|---|---|---|
| 이익잉여금 | 15,091,684,311 | 당기순이익 3,797,842,048 **−** 307,150,286 | 18,582,376,073 |
| 기타자본구성요소 | **−**30,162,524,009 | 448,570 + 700,359,720 | **−**29,461,715,719 |

이익잉여금 열은 재측정요소를 **음수로** 넣을 때만 닫힌다(양수면 4,104,992,334 로
불일치). 자본합계 기초도 기타자본을 음수로 넣어야 닫힌다:
46,622,740,000 + 908,732,724,016 + 15,091,684,311 − 30,162,524,009 = 940,284,624,318 ✓

★**열 전체가 부호반전된 것이 아니다** — 기타자본구성요소 열은 **기초·기말 잔액만**
괄호를 잃었고 변동행(448,570 / 700,359,720)은 양수가 맞다. 일괄 부호반전으로
"고치면" 멀쩡한 변동행을 망친다. 셀 단위로 항등식이 증명하는 것만 손댈 수 있다.

**계층3 영향 = 없다**(코드로 확인, 2026-09-22). SCE 는 애초에 계층3 입력이 아니다:

- `fin2/layer3/combine.py:1757` — `_FS = {"IS": "is", "BS": "bs", "CF": "cf"}`, SCE 없음.
- 같은 파일 `_map_rows()` 가 `if r["statement"] not in stmt_set` 로 걸러내고,
  호출부 기본값은 전부 `("BS","IS","CF")`(3091·3138·3159행). SCE 를 넘기는 호출부 없음.
- `fin2/audit/face_audit.py:1163`, `fin2/extract/pdf.py:717` — `if anc.statement == "SCE": continue`.
- `scripts/gateb_audit.py:316` — SQL 에 `statement <> 'SCE'` 를 박아 둠.

즉 "BS 값을 우선한다"가 아니라 **SCE 를 아예 읽지 않는다**. std_v3 오염은 없고,
손상 범위는 `report_lines` 의 SCE 행 자체에 국한된다.

**규모**(프록시 스캔: 같은 필링·같은 basis·같은 라벨이 IS/BS 엔 음수, SCE 엔 같은
절대값 양수. 2015+): **1,209필링 / 2,552셀.** 상위 라벨 = 당기순이익(손실) 410필링 ·
기타포괄손익 164 · 확정급여제도의 재측정요소 113 · 해외사업환산손익 105 ·
지분법자본변동 102 · 순확정급여부채의 재측정요소 67.

**수정**(사용자 결정 2026-09-22 — "교차대조 + 항등식"):
`fin2/extract/sce_sign_repair.py::repair_sce_sign_loss()`. **근거 두 갈래를 둘 다**
요구한다.

| 근거 | 역할 |
|---|---|
| (가) BS/IS 교차대조 | **부호 방향(앵커)** — 같은 필링·같은 basis 에 같은 개념이 어느 쪽 부호로 있는지가 orientation 을 확정한다 |
| (나) 열 롤포워드 항등식 | **적용 자격** — `기초 + Σ변동 = 기말` 이 닫히는 배정만 채택한다 |

★**어느 한쪽만으로는 안 된다.** (가) 만으로는 **잔액행에 못 닿는다** — 잔액행의
`label_raw` 는 날짜("2019.01.01 (당기초)")이고 개념은 `col_label` 에 있다. 게다가
**기초** 잔액은 BS 의 전기말과 대조해야 하는데 BS 는 `col_index=0`(당기)만 적재하므로
DB 안에 짝이 없다 — 라벨 교차대조로는 원리적으로 못 닿고 항등식으로만 증명된다.
(나) 만으로는 **방향을 못 정한다** — 어떤 배정이 항등식을 만족하면 그 전체 부호반전
(mirror)도 반드시 만족하므로(양변에 −1) 항등식 혼자서는 둘 중 하나를 고를 수 없다.

★**`col_label` 은 계층 접두어를 뗀 마지막 조각으로 맞춘다** — `'자본>기타자본구성요소'`
→ `'기타자본구성요소'` (헤더 그리드가 상위 헤더를 이어 붙인다).

**손대지 않는 경우**(R6 — 오염보다 결측): 항등식이 이미 닫힘 / 만족 배정이 여러 개 /
앵커가 하나도 없음 / 앵커와 모순 / 후보 셀이 `_MAX_AMBIGUOUS_CELLS`(14) 초과.
실측 후보 150건 중 **49건(33%)이 이렇게 기각**됐다 — 기각이 정상 동작이다.

★**열 전체를 일괄 반전하지 않는다.** 효성중공업 기타자본구성요소 열은 기초·기말
잔액만 괄호를 잃었고 변동행(448,570 / 700,359,720)은 양수가 맞다. 일괄 반전은 멀쩡한
변동행을 망친다 — 그래서 셀 단위 배정을 항등식으로 검증한다(회귀 테스트가 고정).

★**음수로 파싱된 셀은 후보가 아니다** — 원문에 괄호가 있었다는 뜻이므로 부호가 명시된
것이고 추측 대상이 아니다.

**배선**: `extract_report_lines()` **맨 마지막**에서 돈다 — 부호 방향을 BS/IS 값으로
확정하므로 inline XBRL overlay 들이 BS/IS 를 손본 뒤의 최종값을 봐야 한다. 프로덕션
경로 두 곳(`run.py::cmd_extract_lines`, `collector/note_lines_sync.py`)이 모두 이
함수를 부르므로 런북 ① 배선은 구조상 충족된다(별도 배선 불필요).

**실측 복원**(효성중공업 `20190515002585`): 별도 4셀 + 연결 3셀 = 7셀. 별도 5개 열
**전부 항등식이 닫혔다**. ★연결 3셀(`결손금 대체`·`기타포괄손익-공정가치측정지분상품
평가손익`)은 **라벨 교차대조만으로는 영원히 못 찾는 셀**이다(BS/IS 에 같은 라벨의 짝이
없고, 잔액행 앵커 + 항등식으로만 증명된다). 반대로 연결 이익잉여금 열은 항등식이 닫히지
않아(회계정책변경 효과 행 + `307,150,285` vs `286` 1원 불일치) **그대로 남겼다** — 의도된
기각이다.

**R162-b — 전기 비교 블록은 '이월잔액' 으로 잇는다**(사용자 결정, 같은 날 후속)

SCE 는 당기·전기 블록이 **세로로 쌓이는데** BS 는 당기만 적재하므로 전기 블록에는
(가) 앵커가 **원리적으로 없다**. 그래서 1차 구현은 당기 블록만 복원하고 전기 블록을
그대로 남겼다(실측 엠케이전자 `20150515000634`: 2015 블록은 복원, 2013·2014 블록은
그대로).

해법: **한 블록의 기말은 다른 블록의 기초와 같은 잔액 그 자체**다. 이미 확정된 블록의
잔액 셀에서 `{절대값: 부호}` 를 모아 미확정 블록의 잔액행 앵커로 쓴다. 진전이 없을
때까지 반복한다(당기 → 전기 → 전전기로 부호가 전파된다).

★**잔액행에만** 적용한다 — 변동행까지 절대값으로 맞추면 우연 일치로 날조된다(테스트
`test_carried_balance_only_anchors_balance_rows` 가 고정).
★같은 절대값에 부호가 **엇갈리면 그 절대값은 버린다**(판정 근거로 쓸 수 없다).
★**인접 블록이 아니라 같은 열 전체에서 찾는다** — 엠케이전자의 2015 기초는 바로 앞
블록(2014.03.31 기말)이 아니라 **2014.12.31 기말**과 이어진다(분기 표가 연차 표
뒤에 또 쌓인다). 인접성으로 좁히면 못 잇는다.

실측 효과(엠케이전자 `20150515000634`): 복원 **29셀 → 100셀**. 되돌린 셀들은
`연차배당`·`평가손실`·`자기주식취득`·`주식할인발행차금`·`부의지분법자본변동` 처럼
음수가 맞는 항목이고, `주식선택권 소멸` 은 자본잉여금 `+359,760,000` / 기타자본
`−359,760,000` 짝으로 정확히 상계된다(원문 TR16 구조와 일치).

**한계(알고 남긴다)**: 백필 후보는 프록시가 `label_raw` 로만 매칭하므로, 앵커가
`col_label` 쪽에만 있는 필링(잔액행만 깨진 경우)은 후보에 안 잡힌다. 그런 필링은
캠페인·데일리 재적재가 돌 때 자동 교정된다(수정이 `extract_report_lines` 안에 있다).

**백필 최종 결과와 잔여의 정체**(2026-09-22): 프록시 기준 2,552셀/1,209필링 →
**1,048셀/556필링**. 1차(당기) 883필링/4,977셀 + 2차(R162-b 전기) 90필링/599셀 적재.

잔여 556필링을 표본 30건으로 **기각 사유별로 분해**했다(블록 단위):

| 사유 | 블록 수 |
|---|---|
| 항등식 이미 닫힘(정상 — 프록시 오탐이거나 이미 고쳐진 열) | 986 |
| **앵커는 있는데 항등식을 못 닫음** | 419 |
| 블록(기초/기말) 미검출 | 13 |
| 후보 없음(전부 음수) | 10 |
| 앵커 없음 | **0** |

★**앵커 부족이 아니다** — 방향은 알지만 `기초 + Σ변동 = 기말` 이 안 닫힌다.

**R162-c — 소계 행 이중계상 제외**(사용자 승인 2026-09-22)

원인은 **소계 행 이중계상**이 맞았다. SCE 는 구성요소 행 뒤에 그 합('총포괄손익' 등)을
한 줄 더 찍는 서식이 흔하고, 그걸 Σ변동에 같이 넣으면 항등식이 절대 닫히지 않는다.
실측 디에이치엑스컴퍼니 `20150515000944` 연결 기타포괄손익누계액 열:

```
기초   2013.01.01 (기초자본)      127,312,821
변동   지분법기타포괄손익             21,360,989
변동   매도가능증권평가손익            -6,006,966
변동   총포괄손익                 15,354,023   ← 앞 두 행의 합(소계)
기말   2013.12.31 (기말자본)      142,666,844
→ 기초+Σ변동 = 158,020,867 / 기말 142,666,844 / 차이 15,354,023 ← 정확히 그 소계
```

★**내가 처음에 틀린 것**: "부모 행(`node_role='P'`)이 값을 갖고 자식도 값을 가지면"
이라고 적었는데 **틀렸다.** 이 표들은 **모든 행이 `depth=0`·`node_role='F'`** 다
(원문에 들여쓰기가 없다). 소계는 **부모가 아니라 형제**로 찍힌다. `node_role='P'` 로
찾는 가설을 40필링에 돌려 보니 **0건**이었다 — 효성중공업 한 열을 훑고 구조적 원인이라
단정한 것이었다. 판정은 **산술**로 해야 한다.

**판정 = 근거 두 갈래를 둘 다 요구한다**(R159 와 같은 원칙):

| 근거 | 내용 |
|---|---|
| (가) 라벨 | `_SUBTOTAL_LABEL_RE` = `소계|합계|총계|총포괄|총기타포괄`(자간 공백·접두 기호 허용) |
| (나) 산술 | 그 행의 절대값이 **앞선 연속 구간의 합**과 같다 |

★**산술만으로는 안 된다** — 실측에서 `당기순이익(손실)`(18건)·`해외사업환산손익`·
`감자차손보전` 처럼 소계가 아닌 행이 앞 구간 합과 절대값이 같아 걸렸다. 그걸 Σ에서
빼면 항등식이 **거짓으로** 닫혀 엉뚱한 부호 배정을 채택한다.
★**라벨만으로도 안 된다** — 산술이 안 맞으면 그 행은 이 구간의 소계가 아니다.
★**구성요소가 1개인 소계도 인정한다** — '총포괄손익' 아래 '당기순이익' 하나뿐인 서식이
흔하다. "2개 이상"을 요구하면 실측 커버리지가 절반으로 줄었다(20셀 → 9셀).
★**소계 자신의 부호는 구성요소의 합으로 확정한다** — Σ에서 빠져 있어 항등식이 정해
주지 않는다. 추측하지 않고 구성요소 합의 부호를 그대로 쓴다(`_subtotal_fixes`).
★소계로 판정된 행은 다음 구간의 합산 대상에서 뺀다(소계의 소계를 만들지 않는다).

**한계**: 구성요소가 부호를 잃으면 (나)가 깨져 소계 판정 자체가 실패한다 — 그런 블록은
여전히 기각된다. 즉 R162-c 가 푸는 것은 "구성요소는 멀쩡하고 잔액행이나 이중계상 때문에
닫히지 않던" 블록이다.

잔여 후보 60건 표본 실측: **6필링 / 20셀** 추가 복원. 그 밖의 잔여는 여전히 증명이
없어 R6 대로 **손대지 않는다**(부호가 틀린 채 남아 있지만 추측으로 뒤집지 않는다).


★**캠페인 세션 지침**: 같은 증상(SCE 만 부호 없음 + BS/IS 는 괄호)은 **신규 결함으로
올리지 말고** 이슈#28 참조로 묶는다. 이 필링은 파서 결함이 아니므로 pass 대상이다.

**R162-manual — (가)앵커가 원리적으로 없는 필링의 개별 확정**(camp_run 이슈#38,
사용자 결정 2026-09-23)

SK텔레콤 `20210517001554`(2021Q1) [별도] SCE `2021.03.31 (기말자본)` **자기주식**
열 — 일반 `repair_sce_sign_loss()` 는 손대지 않았다. 원인: 이 필링 BS 에 '자기주식'
단독 행이 없어(자본조정에 뭉쳐 있음) (가)BS/IS 교차대조 앵커가 **원리적으로 없다**
(R6, 정상 동작 — 오탐 아님).

그런데 이 필링은 R162-d 와 **같은 원리**(행 내부 항등식이 orientation 을 거울
모호성 없이 확정)로 독립된 두 증거가 일치한다:

```
열 롤포워드: 2021.01.01(기초) −2,123,661,000,000 + 취득 −72,982,000,000
             + 처분 +26,983,000,000 = −2,169,660,000,000
행 내부 분해: 기타불입자본합계(245,841,000,000) = 주식발행초과금(2,915,887,000,000)
             + 자기주식 + 신종자본증권(398,759,000,000) + 주식선택권(1,528,000,000)
             + 기타(−900,673,000,000)  →  자기주식 = −2,169,660,000,000
```

DB 는 원문 그대로 `+2,169,660,000,000`(괄호 누락)으로 적재돼 있었다.

★R162-d **전체 백필은 여전히 보류**다(2026-09-22 결정 유지) — 이건 그 범위를
넓히는 게 아니라, camp_run 이 실측 발견하고 사용자가 개별 승인한 **이 필링 1건만**의
확정이다. `fin2/extract/sce_sign_repair.py::_MANUAL_SIGN_FIXES` 에 등재
(`apply_manual_sign_fixes()`, R159 의 `_SOURCE_TYPO_CELL_FIXES` 와 같은 패턴 —
old_value 일치 확인 후에만 적용). 배선은 `repair_sce_sign_loss()` 바로 다음, 같은
`extract_report_lines()` 안이라 별도 call site 배선이 필요 없다.

재적재: `scripts/apply_r162_manual_issue38.py --apply`(rcept 하드코딩, 신규 승인
없이 항목 추가 금지).

**R162-manual 확장 — 배치#13 개별확정 60셀(+E1 IS 2셀 별도) + row_order 키 추가**(verification fix
batch #13, 2026-09-26)

**발견**: sign_flip 잔여 61건(9필링) — 기존 reload 로 26건은 R162/R162-d/R176/R177 이
공짜로 해소했으나, 남은 61건은 R162-d 가 **이중증거 요건**(다른 곳에 같은 크기가
음수로 있어야 함) 때문에 채택하지 못한 셀이었다. 실측 결과 두 부류다:

1. **미착수** — 항등식으로 정답은 유일하게 나오는데(행 내부 열 항등식·소계행
   직접비교·연간 롤포워드 중 **둘 이상**이 교차확인) 그 값이 필링 다른 곳에 음수로
   재등장하지 않아 R162-d 의 이중증거 게이트를 못 넘었다(고려아연·SK하이닉스·
   제주반도체·SKC 대부분).
2. **오수정** — R162-d/e/f 가 반대 방향으로 뒤집어놓은 셀. 고려아연
   `(부의)지분법자본변동`(원문·형제열 모두 양수인데 이 셀만 음수), POSCO `자기주식의
   처분`(자본잉여금+자기주식=자본합계 항등식이 자기주식을 양수로 요구하는데 음수),
   두산 `-자기주식의 이익소각`/`-인적분할`/`소계.`(2017·2019 두 개의 서로 다른
   자본거래 열-롤포워드 블록이 같은 열 안에서 부호가 엇갈려 있었다), SKC `기타거래`
   비지배지분·`IFRS16 도입`(C8=C6+C7 역산이 양수를 요구하는데 음수) — 전부 각 행의
   또 다른 독립 항등식(형제열·소계행·연간 롤포워드)으로 **되돌릴 방향**까지 확정된다.

일반화된 알고리즘(다중 행이 한 열을 공유하는 연립방정식, 예 두산의 3개 행이 같은
"2017 자본거래" 열을 공유)을 새로 설계하는 대신, 각 셀을 원문·항등식으로 개별
확정하고(모두 카카오·태광산업 R162-d 케이스와 달리 **자본거래/이월잔액** 라벨이라
basis 무관하게 참이라는 R162-d 4번 규칙의 전제를 그대로 만족) `_MANUAL_SIGN_FIXES`
에 등재했다 — R159 개별확정과 같은 위험관리(old_value 일치해야 적용, 값이 달라지면
조용히 덮지 않음).

**키 스키마 변경**: `(rcept, basis, label_raw, concept)` → `(rcept, basis, label_raw,
concept, row_order)`. 같은 라벨이 같은 표 안에서 서로 다른 기간 블록에 반복 등장하는
경우(고려아연 '기타포괄손익>매도가능증권평가손익'이 2016 연간·2016 Q1 두 블록에,
두산 '소계.'가 이익잉여금 열·자본금 열 두 곳에)를 row_order 없이는 가를 수 없어 딕셔너리
키가 충돌했다(2026-09-25 SK텔레콤 단일 항목일 때는 드러나지 않던 갭). 기존 SK텔레콤
항목도 실측 row_order(17)를 채워 새 스키마로 이전했다 — 동작은 그대로.

**E1 IS 별도 예외목록**: E1 2017Q1 `20180130000271` `당기손익으로 재분류되는
기타포괄손익의 구성요소와 관련된 법인세`(연결·별도 각 1셀)는 SCE 가 아니라 IS 이고,
R170-d(`_settle_is_tax_sign`)가 보는 법인세비용 본선(`IncomeTaxExpenseContinuingOperations`)
과 다른 개념(`IncomeTaxRelatingToComponentsOf…ReclassifiedToProfitOrLoss`)이라 별도
메커니즘이 필요했다. 세전재분류OCI−OCI 등식으로 원문 부호가 자기증명되는데(연결
-3,541,999,661-(-4,712,736,047)=+1,170,736,386, 별도 55,600,396-73,351,436=
-17,751,040) 파서가 반대로 저장했다(원인 미상). `fin2/extract/report_lines_xbrl.py::
_MANUAL_IS_SIGN_FIXES`/`_apply_manual_is_sign_fixes()`, `_settle_is_tax_sign()` 바로
다음(같은 반환식)에 배선.

**검증**: `pytest tests/ fin2/tests/` 1,398 passed. 회귀
`fin2/tests/test_r162_sce_sign_repair.py`(row_order 충돌 방지·revert 케이스),
`fin2/tests/test_xbrl_base_presentation_merge.py`(E1 IS 예외목록).

**재적재·결과(batch #13)**: 표적 9필링 재적재. 1차(기존 규칙)로 26건, 2차(이번 수정)로
60건 fixed = 86/87. 미수정 1건: #84772(한화오션 2015FY, 원문 자체가 2013 흐름검산과
모순되고 DB 는 이미 롤포워드-일치값을 담고 있어 손대지 않음 — source_defect 성격의
오등록으로 판단, sign_flip 으로 남겨둠 — 수정측은 closed 권한이 없어 검증측 재검토
대상).

**R162-manual 정정 — 배치#27(2026-09-26 야간): batch #13 의 두산 revert 5항목은 반대방향이었다**

**발견**: unclassified 4건(#83588 제주반도체, #84793/#84804/#84815 두산 2019 별도 SCE
`-인적분할`/자본 합계)이 batch #15·#25 를 거치고도 셀 값이 그대로여서 다시 열렸다.

1. **두산 `20200330004497`(+byte-identical `20240418000398`·`20241002000388`)**: 원문 2019
   자본거래 블록(row52~58)은 **모든 셀에 괄호가 없다**(`-인적분할` 원문 =
   `11,107,630,000 | 62,490,051,174 | 802,198,724,892 | 804,793,372 | 804,793,372 |
   750,816,303,718`). 부호는 열 롤포워드(기초 row40 + 포괄손익소계 row48 + 자본거래소계
   row58 = 기말 row59)로만 정해진다. 역산하면 자본금 −11,107,630,000(원문 주석에 "회사분할에
   따라 자본금이 감소" 명시)·기타자본구성요소 −802,198,724,892·기타포괄손익누계액
   −804,793,372·이익잉여금 +804,793,372·자본 합계 −750,816,303,718 로 유일하게 정해진다(행
   항등식도 닫힘). **R162-e/f 는 자본금·기타포괄손익누계액·이익잉여금을 이미 맞게 복원해
   놓았다.** 그런데 batch #13 이 camp_run 등록값(부호를 거꾸로 적은 #84788~#84792 계열)을
   근거로 `# revert` 5항목(row55·58 의 자본금·기타포괄손익누계액, row55 이익잉여금)을 넣어
   그 값을 다시 틀린 쪽으로 뒤집고 있었다.
   → 5항목을 **삭제**했다. R162-e/f 가 남긴 미복원 셀 10개(row52 기타자본, row54 배당
   이익잉여금·합계, row55 기타자본·합계, row57 자기주식 기타자본·합계, row58 기타자본·
   이익잉여금·합계)를 등재했다. 결과로 블록 6개 열 모두에서 소계 = 구성요소 합,
   기초 + 소계 = 기말이 성립한다.
2. **제주반도체 `20200330002326` 연결 `연결대상범위의 변동`(row22)**: 형제 기타자본구성요소
   칸만 batch #13 이 음수화했고 지배합계 칸(+259,656,740)은 빠졌다. 지배합계 = 기타자본
   (−259,656,740)과 지배합계 + 비지배지분 21,837,466,740 = 자본합계 21,577,810,000 이
   **둘 다** 음수를 요구한다. R162-d 가 이 셀을 못 잡은 이유는 두 가지다. 이중증거 게이트가
   같은 금액의 음수를 필링 다른 곳에서 찾지 못했다. 또 행 라벨이 `_CAPITAL_TRANSACTION_RE`
   의 `연결범위변동` 과 매치되지 않는다(`연결대상범위의 변동`). → 1셀 등재.

**범위 밖(손대지 않음, sign_flip 동결 결정 2026-09-26 유지)**: 두산 2019 포괄손익 구간
row44 `-확정급여제도의 재측정요소` 이익잉여금·합계(+7,499,246,560 → row48 소계가 음수를
요구, 이슈 미등록). 두산 2017·2018 블록 잔여(#85011/#85017 계열). 제주반도체 2018 블록
`회계정책변경`(row13)·`기타포괄손익`(row17) 형제열(#84645~#84650, #83580/#83581).

**교훈**: 수동 revert 항목은 camp_run 이 등록한 "원문값"만 믿으면 안 된다. **열 롤포워드로
직접 역산**해 방향을 확정한다. 원문에 괄호가 전혀 없는 표에서는 등록값의 부호도 추측이다.

**검증**: `fin2/tests/test_r162_sce_sign_repair.py::test_manual_fix_doosan_2019_spinoff_block_closes_rollforward`
(3 rcept × 6열 롤포워드·소계·행항등식), `::test_manual_fix_jeju_semi_scope_change_parent_total`.
`pytest tests/ fin2/tests/` 1,421 passed. 추출 실측(재적재 전 live extract)으로 위 값 확인.

---

**R162-manual 확장 — 비에이치 정정 2019Q1 별도 자기주식 2셀 (verification 이슈 #86399, 사용자 승인 2026-10-26)**

`적용 계층: 3` (계층2 `report_lines` 는 인쇄값 그대로, 보정은 `layer3_cell_corrections` 에만 남는다)

비에이치 `20190821000012`([기재정정]분기보고서 2019.03) 별도 SCE 의 자기주식 열은
`2019.01.01 (기초자본)`·`2019.03.31 (기말자본)` 두 잔액을 **괄호 없이** `49,929,862,900` 으로
인쇄한다. 일반 체인(R162·R190-d)은 이 두 셀을 건드리지 않았다. 음수라는 증거는 셋이다.
① 주석 자기주식 표가 `(49,929,863)`(천원)을 인쇄한다. ② 같은 회사 FY2018 사업보고서의
`2018.12.31` 자기주식 잔액(`49,929,862,900`)은 이미 `-49,929,862,900` 으로 보정돼 있고
(R190-d), 2019 반기·3분기 보고서는 같은 잔액을 `-49,929,862,900` 으로 인쇄한다. ③ 자기주식은
자본의 차감 항목이다.
→ `_MANUAL_SIGN_FIXES` 에 2셀 등재(`row_order` 6·11, old = 49,929,862,900 일치 확인 후 적용).
이 이슈의 원래 지적(missing_row: `자기주식 거래로 인한 증감` 행)은 이미 해소돼 있었다(값
`-19,939,404,600` 이 원문과 같음).

★이 필링의 열 합계는 어느 부호로도 닫히지 않는다(기초 차이 364,072,800, 기말 차이 1,730,506,240) —
원문 자체의 불일치이며 이 보정의 범위가 아니다. 같은 분기 최초본 `20190515000715` 에도 같은 두 셀이
양수로 남아 있으나 `is_final=false` 라 등재하지 않았다.

**R162-manual 확장 — HD현대일렉트릭 2020Q1 연결 SCE `연결대상범위의 변동` 이익잉여금 1셀 (verification 이슈 #84221, 사용자 승인 2026-10-26)**

`적용 계층: 3` (계층2 `report_lines` 는 인쇄값 그대로, 보정은 `layer3_cell_corrections` 에만 남는다)

HD현대일렉트릭 `20200515002598`(분기보고서 2020.03) 연결 SCE 의 `연결대상범위의 변동` 행은
기타포괄손익누계액 `497,572,079`·이익잉여금 `(497,572,079)` 로 두 칸의 괄호가 **서로 바뀌어**
인쇄돼 있다. 기타포괄손익누계액 칸은 R162_sign_loss 가 이미 `-497,572,079` 로 보정했지만
이익잉여금 칸은 인쇄값 `-497,572,079` 그대로여서 두 칸이 어긋나 있었다. 증거: 이익잉여금 열 롤포워드
(기초 -427,892,647,018 + 분기순손익 -25,894,566,796 + 나머지 변동 +10,568,324,939 -1,290,295,242 +
이 셀)가 `+497,572,079` 일 때만 인쇄된 기말 `-418,117,045,242` 와 일치한다(`-497,572,079` 면
`-419,109,761,400`). 두 칸은 합이 0 인 재분류라 비지배지분(-252,729,825)·자본 합계는 그대로다.
→ `_MANUAL_SIGN_FIXES` 에 1셀 등재(`row_order` 14, old = -497,572,079 일치 확인 후 적용).
테스트 `test_manual_fix_flips_hd_hyundai_electric_2020q1_retained_earnings_scope_change`.
이 이슈는 지난 결정(2026-10-26 오전 defer)을 같은 날 사용자가 뒤집어 보정으로 처리했다.

**R162-e — 앵커 없는 셀을 롤포워드 '단일 셀 반전'으로 복원**(사용자 지시 2026-09-25 03시,
"R162 확장 배치로 자동 이슈 처리 진행")

**발견**: 검증 캠페인 기계 대조(mc2~, `fin2/verification/machine_compare.py`)가 자동 등록한
`sign_flip`(rule R162) 이슈는 **82,567건/16,888필링**이었다. 이 가운데 약 5.4만 건이 배당
(`배당금지급`·`연차배당`·`현금배당`…)이다. 원문이 배당을 **괄호 없이 양수**로 적는 관행이 있다
(실측 `20260313000835` 현금배당 15,182,251,900 · `20180525000233` 배당금지급 454,554,457,200).
BS/IS 에는 배당 행이 없으므로 R162 의 (가) 앵커가 **원리적으로 없고**, 그래서 R162 는 손대지
않았다(R6, 정상 동작).

**규칙**: R162/R162-b/R162-c 가 끝난 뒤에도 닫히지 않는 블록에서만 적용한다.
**양수 셀 하나의 부호만** 뒤집으면 롤포워드(`기초 + Σ변동 = 기말`, 소계는 R162-c 로 제외)가
정확히 닫히고, 그런 셀이 **정확히 하나**일 때 그 셀을 뒤집는다(`_solve_single_flip`).

- **거울 모호성은 '최소 변경'으로 끊는다.** R162 가 (나) 단독을 금지한 이유는 전체 반전(mirror)도
  항등식을 만족하기 때문이다. 그러나 전체 반전은 나머지 모든 셀의 원문 부호를 부정하는 다셀
  변경이다. R162-e 는 "원문 부호가 대부분 맞고 틀린 셀은 하나" 라는 배정만 받는다.
- 후보가 둘 이상이면 판정불가다(R6, 테스트 `test_no_anchor_two_single_flip_candidates_is_left_alone`).
- 음수로 파싱된 셀은 여전히 후보가 아니다. 앵커/이월잔액이 그 셀을 양수로 정해 두었으면 뒤집지 않는다.
- 소계 행의 부호는 R162-c 대로 구성요소 합으로 따라간다(`_subtotal_fixes`).
- 교정 내역의 `anchor_label` 은 `R162-e 롤포워드 단일셀` 이다.

**기존 테스트 변경**: `test_no_anchor_means_no_repair` 는 R162-e 로 동작이 의도적으로 바뀌어
`test_no_anchor_single_flip_repairs_under_r162e` 로 대체했다. 같은 입력(100 + 30 = 70)에서
평가손익 한 셀만 뒤집어야 닫히므로 이제 복원한다.

**배선**: `repair_sce_sign_loss()` 안(같은 함수 말미)이다. 그래서 `extract_report_lines()`
프로덕션 두 경로에 자동 반영된다(별도 call site 배선 불필요). 소급은 검증 캠페인 fix 배치
(`vq.py batch`)로 재적재하고, 재확인은 기계 대조가 한다(`vq.py machine recheck`).

**소급 결과**(fix batch #2, 2026-09-25 03:40~05:10, 커밋 `51ba241`):

| 항목 | 값 |
|---|---|
| 재적재 | 16,888필링(6샤드 병렬, 약 1시간), 실패 0 |
| 이슈 | 82,567건 → 기계 재확인 **closed 70,719(86%)** · reopened 11,848 |
| 배당 행 | closed 56,719 · reopened 6,155 |
| 잔액 행 | closed 5,519 · reopened 823 |
| 기타 | closed 8,481 · reopened 4,870 |

- reopened 중 3,627 셀은 **원문에 괄호가 명시된 음수**다. R162-e 비대상이다.
  - 예 `20150512000105`: 배당금지급 행 전체가 거울 반전돼 있다. 자본금 `(93,072,000)` 인데 실제로는 주식배당으로 증가한다.
- 나머지 reopened 는 후보가 둘 이상이거나 같은 블록에 다른 원문 이상이 섞여 단일 셀로 닫히지 않는 경우다. 수정 쪽 후속 판단 대상이다.
- 파일럿 10필링: 부호 발견 92 → 6, 8필링 clean.

## R163. CF **현금 조정 구간**에서 원문이 빠뜨린 음수 부호를 복원한다 — R162 의 자매(자본변동표 → 현금흐름표) (2026-09-22, 캠페인 이슈#29)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 CF 현금 조정 4행(기초·순증감·환율효과·기말)을 라벨로 직접 지목하고, 항등식(기초 + 순증감 + 환율효과 = 기말)이 깨져 있으며 단일 셀 뒤집기로 닫히는 경우가 정확히 하나일 때만 그 셀의 부호를 뒤집는다. 부호만으로는 판정하지 않는다(환율변동효과는 양수가 더 많다: 2015+ 양수 114,412셀 / 음수 83,639셀).
> **판정 예** 한화오션 `20180330001629`(2017FY) [별도] CF 당기열: 144,292,901,261 + 16,367,553,617 − 521,074,352 = 160,139,380,526 → 환율효과 521,074,352 를 −521,074,352 로. 에이루트 `20190814001339`: `환율변동효과 반영전 현금및현금성자산의 순증가(감소)` = 순증감 행, `현금및현금성자산에 대한 환율변동효과` = 환율효과 행.
> **하지 않는 것** 4행 중 하나라도 라벨로 못 찾거나 후보가 2건 이상 / 항등식이 이미 닫힘 / 단일 셀 뒤집기로 닫히는 경우가 없거나 둘 이상 / 기초·기말 현금이 음수 → 손대지 않는다. `환율변동효과 후의 … 순증가(감소)` 는 순증감 후보에서 배제한다. R162 의 블록 로직은 재사용하지 않는다(CF 는 순증감이 기초보다 앞). 스캐너의 "항등식 깨짐 49,173" 은 결함 수가 아니다.
> **코드** `fin2/extract/cf_cash_sign_repair.py`(`extract_report_lines()` 맨 마지막, R162 바로 뒤) · `scripts/scan_cf_cash_sign_loss.py` · `scripts/backfill_r163_cf_cash_sign.py --apply`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**성격**: R162 와 같다 — **파서 결함이 아니고** DART 원문이 부호를 빠뜨린다.
한화오션(舊 대우조선해양) `20180330001629`(2017FY) [별도] CF 당기(제18기) 열:

```
현금및현금성자산의 증가(감소)         16,367,553,617
기초의 현금및현금성자산             144,292,901,261
외화표시 현금및현금성자산의 환율변동효과     521,074,352   ← 참값은 −521,074,352
기말의 현금및현금성자산             160,139,380,526

144,292,901,261 + 16,367,553,617 − 521,074,352 = 160,139,380,526 ✓
```

같은 필링의 비교연도 2개 열과 [연결] CF 는 부호가 정상이다 — 이 한 셀만 깨졌다.

**★부호만으로는 절대 판정할 수 없다.** `환율변동효과` 행은 **양수가 정상인 경우가 더
많다**(2015+ 실측 양수 114,412셀 / 음수 83,639셀 — 환율이 오르면 외화현금 평가이익이
나서 양수다). 그래서 이 규칙은 **항등식이 깨진 경우에만** 작동한다.

**왜 R162 의 블록 로직을 재사용하지 않는가**: SCE 는 `기초 → 변동들 → 기말` 순서지만
CF 는 **순증감 행이 기초보다 앞**에 온다(위 실측). "기초가 열고 기말이 닫는" 블록
탐색이 맞지 않는다. 그래서 `fin2/extract/cf_cash_sign_repair.py` 는 현금 조정 4행
(기초·순증감·환율효과·기말)을 **라벨로 직접 지목**한다 — 관측된 결함 계열에만 좁게
대응하고, 라벨을 못 찾으면 손대지 않는다.

**라벨 판정에서 반드시 갈라야 하는 두 행**(실측 에이루트 `20190814001339`):

| 라벨 | 정체 |
|---|---|
| `환율변동효과 **반영전** 현금및현금성자산의 순증가(감소)` | **순증감** 행(환율은 그 뒤에 더한다) |
| `현금및현금성자산에 대한 환율변동효과` | **환율효과** 행 |

둘 다 '환율변동' 을 포함하므로 `반영전` 배제 규칙이 없으면 환율효과 행 식별이 2건이
되어 아무것도 못 고친다. 반대로 `환율변동효과 **후**의 … 순증가(감소)` 는 이미 환율이
반영된 총계라 이 항등식의 항이 아니다 → 순증감 후보에서 배제한다.

**손대지 않는 경우**(R6): 4행 중 하나라도 라벨로 못 찾음(또는 후보가 2건 이상) /
항등식이 이미 닫힘 / **단일 셀 뒤집기**로 닫히는 경우가 없거나 둘 이상 / 기초·기말
현금이 음수(현금 잔액은 음수일 수 없다 = 우리가 이해 못 한 표다).

**규모**(`scripts/scan_cf_cash_sign_loss.py`, 2015+ DB 당기 열):
4행이 전부 식별된 (필링,basis,표) 106,959개 중 **단일 셀 뒤집기로 닫히는 것 61개**.
★같은 스캐너가 보고하는 "항등식 깨짐 49,173" 은 **결함 수가 아니다** — 대부분 이
4행 라벨 지목이 그 서식에 안 맞은 것이다(닫히지 않으면 손대지 않으므로 무해).
표본 8건을 눈으로 검산했고 전부 4행이 인접 `row_order` 로 정확히 잡혔다.
★필러 편중이 크다 — 유비온이 반복 등장한다(회사별 서식 습관).

**배선**: `extract_report_lines()` 맨 마지막, R162 바로 뒤. 프로덕션 두 경로가 모두
이 함수를 부르므로 런북 ① 은 구조상 충족.

**백필**(`scripts/backfill_r163_cf_cash_sign.py --apply`): 후보 61 → **CF 45셀 ·
적재 51건**(함께 SCE 44셀도 반영). 잔여 19 중 **3건만 실제로 바뀔 것**이고 그 3건은
R139 원문대조-pass 보호로 거부됐다(한화오션 `20180330001629`·`20180403001678`·
`20180523000409` — 캠페인 세션에 redo 요청). 나머지 16건은 **추출 시점 행 집합이
DB 와 달라**(DB 는 `col_index=0` 의 적재 대상 행만 갖는다) 4행 지목이 유일하지 않아
파서가 스스로 기각한 것이다 — 설계대로다.

★**내가 여기서 또 틀렸다**(같은 계열 4번째): 백필 1차 드라이런에서 "CF 음수 65→172
(+107)" 같은 수치를 보고했다. CF 는 `col_index=0` 만 DB 로 가는데(`_is_loadable`)
추출기 **전체 열** 출력과 DB 를 비교한 것이다. 바로잡은 뒤 실제 델타는 필링당 1~2셀
(총 45셀)이었다. 적재 전에 잡았다. 메모리
`feedback-do-not-attribute-backfill-recoveries-to-one-rule` 의 "추출됐다 ≠ DB 에
실린다" 항목 그대로다.

## R165. SCE 기말잔액 행의 한 셀만 원문에서 값이 틀려 있다(행 항등식+BS 이중앵커로 확정)

> **상태** 유효 · **적용 계층** 3 · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견.** 캠페인 이슈#31(camp_run) — 한화오션 2015FY 기재정정 `20170511004419` ·
`20171019000325` 의 별도 SCE '2015.12.31 기말자본' 행에서 **이익잉여금 셀만** 정정 이전
값(`-1,563,903,332,495`)이고 같은 행의 나머지 전부와 자본합계(`415,242,474,443`)는
정정 후 값이다. R162/R163(음수 괄호 누락)과 달리 **절대값 자체가 틀린** 계열이라 부호
규칙으로는 못 찾는다.

★**camp_run 의 최초 판단은 틀렸고 내가 정정했다**: "1차본은 DB 가 우연히 맞다" 고
보고됐지만 실측하면 **두 자매 필링의 DB 값이 완전히 동일**하다(둘 다 스테일). BS 쪽 값을
보고 SCE 가 맞다고 오판한 것이다. 그래서 1차본의 `pass` 도 `fail` 로 재판정됐다.

**판정 = 이중 앵커.** SCE 기말잔액 행에서

1. **행 항등식** — 구성요소 열 합 = 자본 합계 열.
2. **BS 앵커** — 각 구성요소는 **같은 필링 재무상태표**의 같은 개념 행과 일치해야 한다
   (SCE **밖**의 독립 앵커).

셋을 모두 만족할 때만 후보로 센다: ①항등식이 깨졌고 ②BS 와 어긋나는 구성요소가 **정확히
하나**이고 ③그 BS 값을 넣으면 항등식이 **정확히** 닫힌다. 그러면 참값이 두 번 고정되고
결함이 한 셀로 특정된다. 그 외는 별 버킷으로 보고하고 손대지 않는다.

한화오션 검산: `1,372,076,840,000 - 14,677,080,363 + 14,967,109,054 + 424,385,260,709
= 1,796,752,129,400`; `415,242,474,443 - 1,796,752,129,400 = -1,381,509,654,957`
= 별도 BS 이익잉여금. 오차 `182,393,677,538`.

**★규모 — 한 숫자로 보고하면 틀린다.** 이 검사에 **서로 다른 네 계열**이 걸린다
(`scripts/scan_r165_stale_sce_cell.py` 가 분류해 센다). 처음 돌렸을 때 1,943건이 나와
"이슈#31 계열 1,943건" 이라 보고할 뻔했다.

```
기말잔액 행(단일 총계 + 구성요소 2개 이상)      104,690
  행 항등식 성립                                 95,331
  ★깨짐 + BS 불일치 1개로 정확히 닫힘             1,943
      sign   1,332셀 / 1,323필링   R162·R163(부호만 반대, 절대값 동일)
      scale      9셀              R157~R159(정확히 10^n 배)
      trunc      7셀              R157(배수 전 절삭)
      other    595셀 /   594필링  ★R165 후보
  깨짐 + 여러 셀이 BS 와 불일치                      555
  깨짐 + BS 로 설명 안 됨                          6,861
```

`other` 595셀도 그대로 R165 가 아니다 — 오차 크기로 다시 갈린다:

```
|적재값 - BS| 분포(595셀)
  = 1원 39 · ≤10 26 · ≤100 15 · ≤1,000 41     → 121셀(20%)은 원문 반올림, 결함 아님
  ≤1M 112 · ≤1B 216 · ≤1T 144 · >1T 2         → ★>1B 146셀이 실질적 오류
```

**★파서 결함이 아니다(중요).** 표본 120건을 원문으로 triage 한 결과 **"원문에 참값만 있고
우리가 딴 값을 넣은" 경우 0건**이다. 그리고 최대 오차 5건은 SCE 셀 원문을 직접 읽어
확인했다 — 전부 **원문 셀 자체가 틀렸고 우리는 충실히 전사**했다:

| 필링 | 회사 | 원문 SCE 셀 | BS(참값) | 정체 |
|---|---|---|---|---|
| `20160816000038` | 대상 | `735,467,953,000` | `73,467,953,000` | 같은 열이 다른 모든 기간 행에서는 `73,467,953,000` — **마지막 행만 숫자 하나 끼어듦** |
| `20150515002082` | 유비쿼스홀딩스 | `1,744,044,351,834` | `174,044,351,834` | 앞에 `1` 하나 더 |
| `20171114000448` | 백산 | `297,141,751,479` | `29,714,175,149` | 자릿수 밀림 |
| `20230811001638` | 한국앤컴퍼니 | `1,697,838,418` | `1,697,838,414,885` | 원문에서 잘림 |
| `20260813001675` | 고려아연 | `7,090,846,932,215` | `7,287,193,766,723` | 스테일 |

대상(20160816000038)이 특히 결정적이다 — **같은 열의 다른 기간 행들이 전부 정상값**이라
원문 자체의 오타임이 그 표 안에서 자기증명된다.

**상태: 미조치(사용자 판단 대기).** 셀 하나를 고치는 데 `manual_report_lines` 를 쓰면
**스코프가 통째로 삭제**되므로(R159 실측) R159 식 예외목록 설계가 필요하다. 규모 파악까지가
사용자 지시(2026-09-22)였고 여기까지가 그 결과다. 참값은 이중앵커로 확정돼 있으므로
복원 자체는 가능하다.

**부수 수확 — `sign` 1,332셀은 R162 잔여에 대한 더 강한 증거다.** R162 는 열 롤포워드
항등식 + BS/IS 교차대조를 쓰는데, 여기 걸린 1,332셀은 **BS 라는 SCE 외부 앵커**가 직접
붙어 있다. R162-d(아래) 후보와 겹치지만 앵커가 더 강하다 — 백필 결정 시 이 집합을 우선
후보로 볼 것.

## R171. 정정 체인에 추출 경로가 섞이면(XML → XBRL → XML) **나중 XML 필링이 앞선 XBRL 셀을 스코프 단위로 대체**한다 (2026-09-25)

> **상태** 유효 · **적용 계층** 3

**발견**: R170 재빌드 후 std_v3 BS 항등식 신규 위반 2행. 00242378 2019Q3 연결: 원본 XML `20191114002491` →
정정1 XBRL `20191206000533` → 정정2 XML `20200721000363`. 세 필링은 각자 항등식이 성립한다. 그런데 std 는 자산·자본을
정정2, 부채(1,135,133,772,680)를 정정1 에서 골랐다. 정답은 정정2(부채 1,134,848,933,304)다. 00453488 2018Q1 연결도 같은 체인이다.

**원인**: R2 델타패치 셀 키 `(statement, basis, col_index, section_path, label_raw)` 는 **같은 추출 경로끼리만** 맞는다.
XBRL 은 "재무상태표 [abstract]>부채 [abstract]" 같은 section_path 를 쓴다. 그래서 경로가 바뀐 정정본의 셀은 '추가'로만
쌓이고, 그 뒤 필링도 그것을 덮지 못한다. R170 전에는 XBRL 정정본에 총계행이 거의 없어 드러나지 않았다.
경로 혼합 기간은 1,497개다(xbrl+xml 1,495 · pdf+xml 2). XBRL 필링은 거의 전부 XML 원본의 정정본이다(XBRL 단독 기간 3).

**규칙** (`fin2/layer3/combine.py::build_merged_lines`, `_filing_source_kind`): 나중 필링이 **XBRL 이 아니고**(xml/pdf)
어떤 (statement, basis) 스코프를 실제로 담고 있으면, 그 스코프의 **XBRL 출처 셀**을 지운 뒤 델타패치한다.
그 필링이 담지 않은 스코프는 그대로 둔다(R2-0).

**왜 반대 방향(XBRL 이 XML 을 대체)은 안 하나**(→ R172 에서 해소, 양방향화): 양방향으로 적용해 보면(드라이런, 776개사) 법인세 2,122 · 지배순이익 305셀이 비었다.
계층3 매퍼가 XBRL 라벨("법인세비용, 계속영업", "[abstract]" section_path 아래 귀속행)을 못 읽기 때문이다. 이것은
**계층3 XBRL 개념(source_ref) 기반 매핑이 생겨야 풀린다 — 별도 과제, 미착수**. 그때까지 XBRL 정정본이 마지막인
체인은 현행(두 경로 셀 공존)을 유지한다.

**검증(드라이런, 경로 혼합 776개사, 롤백)**: 핵심 컬럼이 바뀐 std 행 8개. BS 항등식 위반→성립 2(위 두 건), 성립→위반 0.
부수 변화는 전부 교정이다. HD현대 `20191114002747`(XBRL 정정)이 천원 값을 배수 없이 태깅해 매출 414,877,871 로 들어가 있던
2019Q3 별도가 나중 XML 정정 기준 414,877,871,000 이 됐다. 차입금상환 부호 33은 XML 원문 표기를 따른다.
※드라이런에서 사라진 std 776행(2026Q1 별도 등)은 R171 무관이다. 옛 코드로 재빌드해도 똑같이 사라진다(아래 재빌드는 경로 혼합 기간만 한다).

**테스트**: `fin2/tests/test_combine_cross_source_amendment_r171.py`(가짜 세션) ·
`fin2/tests/test_xbrl_base_presentation_merge.py`(R170-d 등식 3건).

**관련**: R2/R2-0 · R170 · R63(delete-then-maybe-insert)

**적용 결과(2026-09-25 08시대, 커밋 8167bb6)**: R170-d 로 법인세가 바뀐 438필링을 batch #4 로 재적재했다(done 437,
`20160816002306` 롯데케미칼 2016H1 은 검증 lease 로 deferred → 다음 reload 재시도, batch #4 는 reloading 유지).
std_v3 는 **경로 혼합 기간 + 그 필링 기간 1,498개만** 재빌드했다(`build_corp` 의 `_periods` 를 좁힘, 777개사, 2,848행,
실패 0). 회사 전체 재빌드는 R171 과 무관하게 2026Q1 별도 등 776행을 지우므로(옛 코드도 동일) 피했다.
calendar_v3 는 777개사를 재동기화했고 orphan 0 이다.
std 변화: BS 항등식 위반→성립 2(00242378 2019Q3 연결 1,909,991,807,496 = 1,134,848,933,304 + 775,142,874,192 ·
00453488 2018Q1 연결 250,442,096,694 = 172,573,069,934 + 77,869,026,760), 성립→위반 0, 소실 행 0,
법인세 부호 교정 258셀. 부수 변화로 판관비 2셀이 비었다. 엘앤에프 2015Q3 별도는 최종 XML 정정의 '판매비'·'관리비'
분리 표기를 계층3 가 합산하지 못한다(기존 계층3 한계). DQ `statement_magnitude_impossible` 0.

---

## R172. 계층3: XBRL 셀은 라벨이 매핑 안 되면 **XBRL 개념(source_ref)** 으로 매핑한다 — R171 양방향화 (2026-09-25)

> **상태** 유효 · **적용 계층** 3

**배경**: R171 은 "XBRL 정정본이 앞선 XML 셀을 대체"하는 방향을 막아 두었다. 계층3 라벨 매퍼가 XBRL 라벨을 못 읽어
(법인세 "법인세비용, 계속영업", "[abstract]" 경로 아래 귀속행) 법인세 2,122·지배순이익 305셀이 비었기 때문이다.
XBRL 필링은 거의 전부 XML 원본의 정정본(경로 혼합 기간 1,495, XBRL 단독 3)이다. 따라서 이 방향이 막히면 XBRL 정정의
재작성 값이 std 에 반영되지 않는다(예: 00163196 2017H1 연결 정정 순이익 5,124,145,921 대신 원본 9,579,248,640 유지).

**규칙**:
1. `build_merged_lines` 가 XBRL 셀에 개념(`source_ref` 두 번째 구간 = local name)을 싣는다(`xbrl_local`, 셀 키는 불변).
2. `_map_rows`: **라벨 먼저**, 라벨이 안 맞을 때만(`confidence<0.88` 또는 unknown) `_map_xbrl_concept` —
   `fin2/taxonomy/concept_map.map_acode("ifrs-full_"+local 또는 "dart_"+local)`. 그 statement 의 canonical 만 받는다.
   회사 확장개념(udf_*)·미등록 개념은 매핑하지 않는다.
   ★개념 먼저로 해 보면(드라이런) trade_payables 충돌 357건이 새로 생겼다. 개념사전은 부모 `TradeAndOtherCurrentPayables` 를
   trade_payables 로 보지만, 라벨 트랙 관례(`_NARROW_PREFER`)는 좁은 하위행을 고른다. 그래서 라벨 우선이다.
3. `_ni_attribution_structural_candidates`: XBRL section_path(`[abstract]` 포함)는 **직전 부모 구간만** 보고 '순이익'·'포괄'을
   판정한다. 루트 '포괄손익계산서 [abstract]' 에 '포괄'이 늘 들어 있어, 전에는 XBRL 귀속 구간 전부가 OCI 구간으로 배제됐다.
4. R171 은 이제 양방향이다. 나중 필링이 다른 경로면 그 필링이 담은 스코프의 다른 경로 셀을 대체한다.

**검증(드라이런 롤백, 경로 혼합 777개사·1,498기간, R171 적용 상태 대비)**: 핵심 컬럼이 바뀐 std 행 138. BS 항등식
성립→위반 0 · 위반→위반 1(기존). 채움: 무형자산 627 · 지배순이익 53 · 법인세 35 · 장기차입금 27 · 단기차입금 15.
교정: 법인세 부호 154(바뀐 법인세 273셀 중 세전−법인세=순이익 성립 0 → 265), 감가상각/D&A 이중계상 119(XML·XBRL 셀이
둘 다 합산돼 정확히 2배였다), 지배순이익 값 41(표본 00101220 2017Q1: 4,336,258,781 + 비지배 10,120,192,838 = 순이익).
비워진 것: 판관비 23(표본 00329093: 확장 태깅 '판매원가'·'관리비'가 둘 다 판관비로 매핑돼 충돌 보류, 기존 값은 관리비 일부),
D&A 11 · capex 10 · fcf 13(최종 XBRL 정정이 유형자산 취득을 기계장치·차량·비품으로만 나열해 합계행 없음),
0원 차입·배당 칸 약 60(0 → 공란).

**재빌드**: `build_corp` 의 `_periods` 를 경로 혼합 기간으로 좁혀 실행한다(회사 전체 재빌드는 무관한 2026Q1 별도 등 776행을
지우는 기존 부작용이 있다, R171 참고). 이어서 calendar_v3 를 재동기화한다.

**테스트**: `fin2/tests/test_combine_cross_source_amendment_r171.py`(XBRL 최종 정정 대체 · 개념 매핑 · XBRL 귀속 구간).

**관련**: R2 · R171 · R16/R42(trade_payables 라벨 관례) · 2026-08-15 NI 귀속 구조 복구

**적용 결과(2026-09-25 12시, 커밋 157da1e)**: std_v3 경로 혼합 1,498기간(777개사) 재빌드 2,848행, 실패 0. 드라이런과 일치한다
(핵심 컬럼 변경 136행, 소실 0, BS 항등식 성립→위반 0). calendar_v3 777개사, orphan 0.
DQ: `statement_magnitude_impossible` 0, `std_v3_conflicts_unresolved` 37,459 → 37,440.
★Gate B 재감사(런북 C3)는 **미실행**이다. `scripts/gateb_audit.py` 가 시작 시 `init_db()`(DDL)를 불러 수정 역할
(tjf_fix)로는 `permission denied for schema public`. main(관리자)에서 돌려야 한다:
`python scripts/gateb_audit.py --corp-file <경로혼합 777개사> --fy-min 2015 --fy-max 2025 --recheck`.

**★R172-b (같은 날 13시, Gate B 재감사 결과로 수정)**: 사용자 지시로 Gate B 를 admin 계정(환경변수 DATABASE_URL)으로 돌렸다.
경로 혼합 기간 pending→fail_b 5건 중 2건이 R172 결함이었다. 개념 폴백을 `exact` 로 둬서 라벨 매치와 동급으로 경쟁했다.
00158024 2017Q1 연결은 회사가 해외사업환산손익(OCI)을 `ProfitLoss` 로 오태깅해 −87,243,237 이 순이익 후보가 됐다
(실제 2,086,131,213). 01089378 2019Q3 은 법인세 두 줄 중 개념 쪽 109,605,787 이 이겼다(원문·Gate B 227,964,000).
→ 개념 폴백 stage 를 `normalized`(라벨 exact 보다 아래)로 내렸다. 개념은 라벨 후보가 없을 때만 결정한다.
나머지 3건은 우리 값이 맞다(00122551·00456218 지배순이익: Gate B report_won 이 총포괄 귀속값을 잡았다).
경로 혼합 기간 전이(첫 재감사, R172-b 전): fail_b→pass 47 · pending→pass 384 · pass→pass 76 · pass→pending 8(n_fail 0,
LABEL_UNMATCHED) · pending→fail_b 5(위). 경로 혼합 밖 pass→fail_b 148 은 비교 기준이 2026-09-02/03 감사라 3주 누적 변화다.
그 가운데 R170 재빌드 772개사에 속한 124건도 실패 필드의 std 값이 R170 재빌드 전후 동일해 오늘 작업과 무관하다(별도 조사 대상).
**R172-b 적용 후 재감사(13시53분~, 커밋 9e35c40)**: 경로 혼합 기간 fail_b→pass 47 · pending→pass 385 · pass→pending 8(값 오류 아님) ·
pending→fail_b **2**(둘 다 Gate B 기준값이 총포괄 귀속값인 건: 00456218 2016H1·00122551 2019Q3 연결 지배순이익, 우리 값이
순이익 귀속으로 맞다). **R172 로 새로 틀린 값은 0건이다.**

---

## R176. XBRL SCE 소유주거래 행 부호 = 롤포워드 등식(기초 + Σ변동 = 기말)이 **증명할 때만** 반전 (2026-09-25)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 XBRL SCE 소유주거래 행의 부호를 롤포워드 등식이 증명할 때만 뒤집는다. 기간 블록 × 자본구성요소 열마다 기초 + Σ(말단 변동 행) = 기말 을 계산하고, 소계 행(트리 자식이 있거나, 값(≠0)이 바로 뒤·앞의 연속 행 합(부호 무관 |v| = Σ|x| 포함)과 같은 행)은 뺀다. 행 개념 하나를 뒤집어 깨진 칸이 줄고 성립하던 칸은 하나도 안 깨질 때만 뒤집으며, 가장 많이 고치는 개념부터 반복한다. 손익계산서가 이미 부호를 정한 개념(ProfitLoss*, *ComprehensiveIncome*, OtherComprehensiveIncome*, ChangesInEquity)은 후보에서 뺀다.
> **판정 예** SK가스 2017Q3 `20171117000389`(XBRL) '연차배당': fact +22,340,715,800, 원문 (22,340,715,800) → 음수(기타자본 열 +429,625,000 은 유지). 소계 예: 00161116 `20150331003085` 에서 '총포괄손익'이 순이익·기타포괄손익 뒤에 오거나 '자본 증가(감소) 합계'가 블록을 닫는 경우.
> **하지 않는 것** 행 누락·XBRL 태깅 불완전으로 등식이 애초에 안 서는 블록은 건드리지 않는다. 손익계산서가 부호를 정한 개념으로 이중계산 블록을 맞추지 않는다(44개 재무제표 실측).
> **코드** `report_lines_xbrl._settle_sce_signs_by_rollforward` · 테스트 `fin2/tests/test_xbrl_base_presentation_merge.py::test_r176_…`
> **코드 확인** (2026-10-12) 동수일 때(R200 `_R176_TIE_POLICY = "strict"`): 후보를 트리 행 순서로 정렬하고, 고친 셀 수가 같은 후보가 둘 이상이면 배당·자기주식 취득처럼 성질상 음수인 개념/라벨 + 양수 팩트 행만 남겨 그중 행 순서 첫째를 뒤집는다. 그런 행이 없으면 아무것도 뒤집지 않는다(`report_lines_xbrl.py:1689-1708`).

**발견**: sign_flip 45건(원문에 음수 표기가 있는데 DB 가 양수) 중 12건은 SK가스 2017Q3 `20171117000389`(XBRL) '연차배당'이었다.
fact 가 +22,340,715,800 인데 원문은 (22,340,715,800) 이다. XBRL SCE 부호는 preferredLabel(R10)로만 정하는데, 회사가 base 배치를
자기 배치로 바꾸면 그 negation 이 사라진다. 나머지 33건(XML)은 이미 DB 가 원문 셀 부호와 같았다(이전 재적재로 해소, 2건은 원문
자체가 행 안에서 부호가 엇갈림 — 삼성중공업 2020H1 파생상품평가손익·삼성전기 2015 해외사업환산손익).

**규칙** (`report_lines_xbrl._settle_sce_signs_by_rollforward`):
1. 기간 블록 × 자본구성요소 열마다 기초 + Σ(말단 변동 행) = 기말 을 계산한다. 소계 행은 뺀다. 소계 = 트리 자식이 있거나, 값(≠0)이
   바로 뒤·앞의 연속 행 합(부호 무관 |v| = Σ|x| 포함)과 같은 행이다. 앞 행 합이 소계가 되는 경우: '총포괄손익' 이 순이익·기타포괄손익
   뒤에 오거나 '자본 증가(감소) 합계' 가 블록을 닫는 경우(00161116 `20150331003085`).
2. 행 개념 하나를 뒤집어 깨진 칸이 줄고 **성립하던 칸은 하나도 안 깨질 때만** 뒤집는다. 가장 많이 고치는 개념부터 반복한다.
3. **손익계산서가 이미 부호를 정한 개념은 후보에서 뺀다**(ProfitLoss*, *ComprehensiveIncome*, OtherComprehensiveIncome*,
   ChangesInEquity). 빼지 않으면 이중계산 블록을 '총포괄손익 반전'으로 맞춰 버렸다(44개 재무제표, 실측).

**검증(2015+ XBRL 경로 전수 1,627필링 / SCE 2,895개)**: 롤포워드 칸 34,831 중 깨진 칸 19,306 → 18,466(−840). 반전된 재무제표 361,
**나빠진 재무제표 0**. 반전 개념: DividendsPaid 290 · TreasuryShareTransactions 5 · OtherDistributionsToOwners 5 ·
OtherTransactions 3 · IssueOfEquity 2 · 회사 확장개념 등. 깨진 칸이 여전히 많은 이유는 행 누락·XBRL 태깅 불완전으로 등식이 애초에
안 서는 블록이 많아서다. R176 은 그런 블록을 건드리지 않는다.

**테스트**: `fin2/tests/test_xbrl_base_presentation_merge.py::test_r176_…`(SK가스 배당 음수, 기타자본 열 +429,625,000 유지).

**재적재·결과(fix batch #7, 2026-09-25, 커밋 426ba13)**: 45건 + R176 이 반전하는 XBRL 246필링 = 271필링, done 271 / failed 0.
이슈 셀 45/45 가 DB 에서 원문 괄호 부호와 일치한다. mark-fixed 결과 **fixed 21**. 나머지 **24건은 등록 시점부터 DB 가 이미 원문과
같았다**(load_seq 불변 — 이슈의 db_value 가 같은 행의 다른 열·basis 값). 그래서 fixed 가 거부됐고, open 으로 되돌려 검증측 withdraw
검토 대상으로 넘겼다(fix 역할은 withdraw 권한 없음). std_v3 488행(해당 기간) 재빌드: 핵심컬럼 무변화, orphan 0, D&A 18 채움.

---

## R183. SCE **원문 자체 오류**(값 오기·기간블록 오배치·중복행) — rcept 예외목록 + **적재시점 항등식 재증명** 가드 (2026-09-26, 사용자 확인)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 `sce_source_defects` 의 rcept 예외목록(`_VALUE_FIXES`·`_ROW_MOVES`·`_ROW_DROPS`·`_CELL_FILLS`)에 등재된 SCE 원문 오류에만 적용하고, 등재 항목도 매 적재마다 표 자신의 항등식으로 다시 증명해 안 되면 경고만 남기고 손대지 않는다. 값 교정: 원래 값으로는 열 롤포워드와 행 항등식이 둘 다 깨지고 교정값으로는 둘 다 닫혀야 한다(같은 행 교정 셀이 여럿이면 함께 적용한 상태로 판정). 행 이동: 그 행이 채우는 구성요소 열(합계 열 제외)마다 원래 블록·대상 블록이 이동 전엔 둘 다 안 닫히고 이동 후엔 둘 다 정확히 닫혀야 하며, 대상 row_order 가 이미 차 있으면 거부한다. 행 제외: 기대값이 정확히 일치할 때만 부호복원 체인(R162…R163) 전에 빼고, 체인 뒤 `verify_row_drops()` 가 그 블록 구성요소 열이 정확히 닫히는지 보아 안 닫히면 되돌린다. 셀 채움(보강): 합계 열에만 인쇄된 변동행의 구성요소 열 셀을, 채우기 전엔 그 열 블록 잔차가 정확히 −값이고 행 항등식(합계 열 1개일 때 Σ비합계 = 합계)이 깨져 있으며 채운 뒤엔 둘 다 정확히 닫힐 때만 합계 셀을 복제해 추가하고(값 교정 직후·부호복원 체인 전), 셀이 이미 있으면 손대지 않는다.
> **판정 예** 동진쎄미켐 `20170515004289` 연결 비지배지분 원문 6,768,899,293 → 6,768,889,293 (6,708,169,143 + 90,585,596 − 29,865,446). 에코프로 `20180402002079` 연결 SCE '전환상환우선주행사' 2016 블록 → 2015 블록 빈 같은 라벨 자리로 row_order 이동, 별도 SCE 2015 '지분법이익잉여금변동' 104,092,712 행은 적재하지 않음. 현대위아 `20240320001675` 별도 SCE 2021 '배당금의 지급' 이익잉여금 열(원문 U+3000) → −18,593(백만원) 채움.
> **하지 않는 것** 같은 패턴을 자동 탐지 규칙으로 일반화하지 않는다(R6) — 합계 열 단독 변동행 전수 스캔 567필링·652행은 측정만 하고 등재하지 않았다(이후 일반화는 R184, 이 입력 밖). 증명이 안 되면 낡은 교정값으로 덮어쓰지 않는다. 행 이동 판정에서 합계 열은 뺀다(무관한 sign_flip 혼입). R159 셀 텍스트 치환·R162 계열(부호만)로는 이 문제를 다루지 않는다.
> **코드** `fin2/extract/sce_source_defects.py`(`_VALUE_FIXES`·`_ROW_MOVES`·`_ROW_DROPS`·`_CELL_FILLS`·`verify_row_drops()`), 배선 XML `extract_report_lines()`(R162 직전 + R163 뒤 사후검증)·XBRL `extract_report_lines_xbrl()` 반환 직전

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: fix batch #29, source_defect 15건. DB = 원문인데 원문이 틀린 셀들이다. 사용자가 DART 원문을 확인해
세 건 모두 원문 오류로 확정했다(2026-09-26).

1. **값 오기** — 동진쎄미켐 2017Q1 `20170515004289`(XBRL) 기말자본 행. 셋 다 같은 날짜 BS 인쇄값이 정답이고,
   **열 롤포워드**(기초+변동=기말)와 **행 항등식**(구성요소 합=자본합계)이 모두 정답값으로만 닫힌다.
   - 연결 비지배지분: 원문 6,768,**899**,293 → 6,708,169,143 + 90,585,596 − 29,865,446 = **6,768,889,293**
   - 별도 기타불입자본: 원문 131,021,198,642 → 61,191,597,597 + 9,871,658,837 − 1,233,655,389 = **69,829,601,045**
     (원문값 = 정답 + 기초. 기초와 기말을 더해 적은 오기)
   - 별도 기타자본잉여금: 원문 40,200,228,190 → 20,743,089,545 − 1,285,950,900 = **19,457,138,645**(같은 오기)
2. **기간블록 오배치** — 에코프로 2017FY `20180402002079`(+정정 `20181206000084`, 표 byte-identical) 연결 SCE의
   '전환상환우선주행사'(534,187,500 / 7,897,249,244 / 8,431,436,744)가 2016 블록에 인쇄됐다. 자본금 열은 2015 블록이
   정확히 534,187,500 모자라고, 2016 블록은 정확히 그만큼 넘친다(자본잉여금 열도 같은 식). 같은 필링 별도 SCE는
   같은 금액을 2015 블록 '유상증자' 행에 넣었다. SCE 행의 기간은 블록 위치(row_order)로만 표현되므로
   **row_order 를 2015 블록의 빈 같은 라벨 자리로 옮긴다**.
3. **중복행** — 같은 두 필링의 별도 SCE 2015 블록 '지분법이익잉여금변동' 104,092,712. 별도 포괄손익계산서는
   이 항목을 제19기(2016)에만 (104,092,712)로 인쇄하고 제18기(2015)는 빈칸이다. 2016 블록에는 이 행이 따로 있다.
   이 행을 빼면 이익잉여금 열이 닫힌다(5,831,180,301 + 189,521,071 − 475,719,069 = 5,544,982,303). **행을 적재하지 않는다.**

**왜 기존 규칙이 못 풀었나**: R159(`_SOURCE_TYPO_CELL_FIXES`)는 XML 경로의 셀 **텍스트** 치환이라 XBRL fact와
행 이동·행 삭제를 표현하지 못한다. R162 계열은 **부호**만 다룬다.

**수정** (`fin2/extract/sce_source_defects.py`): 세 목록 `_VALUE_FIXES` · `_ROW_MOVES` · `_ROW_DROPS` 를 두고,
**등재 항목도 매 적재마다 표 자신의 항등식으로 다시 증명한다**(사용자 요청 가드). 증명이 안 되면 경고만 남기고 손대지 않는다.
원문이나 파서가 바뀌어도 낡은 교정값으로 조용히 덮어쓰지 않는다.
- 값 교정: 원래 값으로는 열 롤포워드와 행 항등식이 **둘 다 깨지고**, 교정값으로는 **둘 다 닫혀야** 적용한다.
  같은 행에 교정 셀이 여럿이면(동진 별도 2셀) 행 항등식을 **함께 적용한 상태로** 판정한다.
- 행 이동: 그 행이 채우는 **구성요소 열**(합계 열 제외)마다, 원래 블록과 대상 블록이 이동 전엔 둘 다 안 닫히고
  이동 후엔 둘 다 정확히 닫혀야 한다. 대상 row_order 가 이미 차 있으면 거부한다.
  합계 열은 무관한 부호 결함(sign_flip)이 섞일 수 있어 판정에서 뺀다.
- 행 제외: 기대값이 정확히 일치할 때만 뺀다. **부호복원 체인(R162…R163) 전에** 빼고, 체인이 끝난 뒤
  `verify_row_drops()` 가 그 블록의 구성요소 열이 정확히 닫히는지 본다. 안 닫히면 행을 되돌린다.
  같은 열에 부호 결함이 함께 있으면 가짜 행이 R162 를 막고 있기 때문에 이 순서가 필요하다.
  에코프로 별도는 행을 빼자 R162-e 가 '확정급여제도의재측정요소' 부호를 복원해 닫혔다.
- 배선: XML `extract_report_lines()`(R162 직전 적용 + R163 뒤 사후검증), XBRL `extract_report_lines_xbrl()` 반환 직전.
  공용 추출기라 `collect_new.py` 두 call site 는 자동 반영된다.

**측정(재추출 전후 SCE diff, 3필링)**: 동진 3셀 교정. 에코프로 두 필링은 각각 RCPS 행 4셀 이동, 104M 행 2셀 제외.
그 뒤 R162 가 2015 '확정급여제도의재측정요소' 셀 4개(연결 합계 2·별도 2)의 부호를 새로 복원했다.
그 밖의 셀 변화는 0이다.

**회귀 테스트**: `fin2/tests/test_sce_source_defects.py`(12건: 교정·가드 거부·타 rcept 무영향·배선 순서).

**재적재·백필**: fix batch #29, 3필링. 같은 패턴은 자동 탐지 규칙으로 일반화하지 않는다(R6). 다른 필링은 검증 측
source_defect 이슈로 올라오면 원문을 확인한 뒤 등재한다.

### R183-보강. **합계 열에만 인쇄된 변동행** — 구성요소 셀 채움 `_CELL_FILLS` (2026-09-26, fix batch #30)

**발견**: 이슈 #84768. 현대위아 2023FY `20240320001675` 별도 SCE 2021 블록 '배당금의 지급' 행은
자본합계 열에만 (18,593)이 있고, 이익잉여금 열은 원문 자체가 전각공백(U+3000)이다(원문 XML 60460행 확인).
2022/2023 블록의 같은 행은 두 열 모두 인쇄돼 있다. 빈칸은 라인이 생기지 않으므로 DB 에 셀이 없다.
- 열 롤포워드: 2,440,374 + 14,193 + 108,944 − 18,593 = 2,544,918(백만원). 이 셀이 있어야만 닫힌다.
- 행 항등식: 같은 행의 다른 구성요소가 모두 0이라 Σ구성요소 = 자본합계가 이 셀로만 닫힌다.
- 검증 측 두 번째 reopen 근거("세 블록 모두 이익잉여금 열에 값 존재")는 원문과 다르다. 2021 블록은 빈칸이다.
- **타 필링 교차대조**(외부 근거, main 세션 확인 + DB 재확인): 같은 2021 기간을 담은 2021 사업보고서 `20220315001247`(EUC-KR)과
  2022 사업보고서 `20230314000727`는 별도 SCE 2021 블록 '배당금지급' 행의 이익잉여금 열에 (18,593)을 인쇄한다.
  자본합계 열도 (18,593)이다. 두 필링 모두 DB 에 이익잉여금 −18,593,000,000 이 적재돼 있다. 2021 사업보고서의
  이익잉여금 변동 주석도 배당금의 지급 (18,593), 기말 2,544,918 이다. 2023 사업보고서만 이 칸을 빠뜨렸다.
  → 이 건의 성격은 파서 누락이 아니라 원문 결함(source_defect)이다.

**수정**: `sce_source_defects._CELL_FILLS` = `(rcept, basis, label_raw, row_order, col_label) → value`.
그 행의 합계 셀을 복제해 구성요소 열 셀을 추가한다(col_index 는 같은 열의 다른 행에서, context_raw 의 `:cN` 도 맞춘다).
가드는 두 조건을 모두 요구한다. 채우기 전에는 그 열의 블록 잔차가 정확히 −값이고 행 항등식(합계 열이 1개일 때 Σ비합계 = 합계)이
깨져 있어야 한다. 채운 뒤에는 둘 다 정확히 닫혀야 한다. 셀이 이미 있으면 손대지 않는다. 적용 위치는 값 교정 직후,
부호복원 체인 전이다.

**측정**: 재추출 diff(1필링)에서 DB 가 보관하는 셀 중 바뀐 것은 목적 셀 1개뿐이다(별도 SCE row 7 col 3, None → −18,593,000,000).

**같은 패턴 전수 스캔(측정만, 미등재)**: SCE 에서 0 아닌 값이 합계 열 한 칸뿐인 변동행을 찾은 뒤,
그 블록에서 구성요소 열 **정확히 하나**의 롤포워드 잔차가 −값과 같은 경우만 셌다. 결과는 **567필링 · 652행**이다
(후보 행 10,727 / 5,332필링 중, `scripts/scan_r183_total_only_row_2026-09-26.py` → `docs/qa/r183_total_only_row_scan_2026-09-26.jsonl`). 라벨에 '당기순이익'이 들어간 행이 339, 채울 열 이름에 '이익잉여금'이 들어간 행이 471이다.
표본 2건(인지디스플레 `20250321001959`, 뉴프렉스 `20240320002028`)도 원문 빈칸으로 확인했다.
필링별 사용자 확인 원칙(위 R183)에 따라 일괄 등재하지 않았다. → 사용자가 일반화를 결정했다(R184).

## R184. **합계 열에만 인쇄된 SCE 변동행** — 빈 구성요소 셀을 항등식으로 채우는 일반 규칙 (2026-09-27, 사용자 결정, fix batch #31)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 합계 열에만 인쇄된 SCE 변동행에서 아래를 **모두** 만족할 때만 합계 셀을 복제해 구성요소 열에 셀을 추가한다. (1) 표의 합계 열(`합계|총계`)이 정확히 1개다(계층형 표 제외). (2) 그 행에서 0 아닌 셀은 합계 열 하나뿐이다. (3) 그 행에 셀이 없는 구성요소 열 중 블록 롤포워드 잔차가 정확히 −값인 열이 딱 하나다(원문이 0 을 인쇄한 칸은 덮어쓰지 않는다). (4) 합계 열 자신의 블록이 닫힌다. (5) 채운 뒤 그 구성요소 열도 정확히 닫힌다. `apply_source_defect_fixes` 안에서 R183 셀 채움 직후, 부호복원 체인 전에 적용한다.
> **판정 예** 본문에 개별 셀 예는 없다. 측정: 스캔 567필링 652행 중 셀 추가 322개(290필링), 나머지 330행은 조건 미충족으로 채우지 않음.
> **하지 않는 것** 원문이 인쇄한 0 은 덮어쓰지 않는다. 후보 열이 2개 이상이거나, 합계 열 블록이 닫히지 않거나, 합계 열이 2개인 표(계층형은 R184-b)는 채우지 않는다. 행 항등식은 조건 1·2로 자동 성립하므로 따로 검사하지 않는다.
> **코드** `sce_source_defects.fill_total_only_rows` (`apply_source_defect_fixes` 안)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**배경**: R183-보강 스캔에서 같은 패턴이 567필링 · 652행 나왔다(표본 원문 모두 빈칸). 사용자가 필링별 등재 대신
일반 규칙화와 전수 백필(A안)을 결정했다.

**규칙** (`sce_source_defects.fill_total_only_rows`, `apply_source_defect_fixes` 안에서 R183 셀 채움 직후, 부호복원 체인 전):
아래를 **모두** 만족할 때만 합계 셀을 복제해 구성요소 열에 셀을 추가한다.
1. 표의 합계 열(`합계|총계`)이 정확히 1개다. 계층형 표(지배기업 합계 + 자본 합계)는 제외한다.
2. 그 행에서 0 아닌 셀은 합계 열 하나뿐이다.
3. 그 행에 **셀이 없는** 구성요소 열 중 블록 롤포워드 잔차가 정확히 −값인 열이 **딱 하나**다.
   원문이 0 을 인쇄한 칸은 원문의 답이므로 덮어쓰지 않는다.
4. 합계 열 자신의 블록이 닫힌다. 제목행이나 이중계상 소계가 아니라 실제 변동이라는 증거다.
5. 채운 뒤 그 구성요소 열도 정확히 닫힌다.
행 항등식(Σ구성요소 = 합계)은 조건 1·2로 자동으로 성립한다. 추측이 아니라 표 자신의 두 항등식이 유일해를 줄 때만 쓴다(R6 위반 아님).

**측정** (스캔 567필링 전부 재추출해 DB 와 비교, R184 켬/끔 두 번):
- R184 로 인한 변화는 **셀 추가 322개(290필링)뿐**이고 스캔 밖 추가는 0이다. 스캔 652행 중 나머지 330행은 조건 미충족이라 채우지 않았다.
  미충족 사유별 분류는 하지 않았다(측정 안 함).
- 별도로 89필링 216셀은 R184 를 꺼도 바뀐다. 기존 코드와 DB 적재본의 차이(예전 코드로 적재된 뒤 재적재 안 됨)다.
  이 216셀은 SCE 이슈와 겹치는 것이 0건이다. 롤포워드 판정은 새 값만 닫힘 189, 둘 다 안 닫힘 18(주로 배당금 행 음수화),
  둘 다 닫힘 2, 판정불가 2, **옛 값만 닫힘 5**다.
- 옛 값만 닫히는 5셀은 2필링(`20110516003437` 자본조정 기말/기초 부호, `20220816002529` 자본잉여금 기초/기말 부호)에 있다.
  현재 코드가 악화시키는 경우라 **이번 재적재에서 제외**했다. R184 와 무관한 별건 조사 대상이다.
- **정정(2026-09-27 조사)**: 위 측정은 `include_notes=False` 로 추출했다. 실제 재적재(`ops._reload_rcept`)는 `include_notes=True` 이고,
  R162-d 는 주석의 음수 금액도 이중증거로 쓴다. 그래서 주석 없이 측정하면 결과가 달라질 수 있다.
  - 재적재한 288필링은 주석 포함/미포함 추출 결과가 0셀 차이라 영향이 없다. DB = 주석 포함 추출로 재확인했다.
  - `20220816002529`(모비데이즈)는 주석 포함 시 현재 코드 = DB 라 **악화가 아니었다**(측정 착시).
  - `20110516003437`(도이치모터스)만 진짜 악화다. SCE 자본조정 열 전체가 괄호 없이 인쇄됐고 BS 는 (17,791,068,388)이다.
    R162-d 가 증거 있는 금액(17,791,068,388)의 3행만 뒤집고, 증거 없는 2010 기초 14,636,161,542 와 합병 3,154,906,846 은 그대로 둔다.
    그래서 2010 블록 롤포워드가 깨진다. 행 항등식상으로는 자본조정 전 셀이 음수다. 수정안(R162-d 열 일관성 가드)은 미착수다.
  - 216셀·옛 값만 닫힘 5 등의 드리프트 수치도 주석 미포함 기준이다.

**재적재**: fix batch #31, 288필링(290 − 제외 2).
**회귀 테스트**: `fin2/tests/test_sce_source_defects.py` R184 5건(채움, 인쇄된 0 보존, 후보 2열 거부, 합계열 불닫힘 거부, 합계 2열 표 거부).

---

## R184-b. R184 를 **계층형 표**(그룹 소계 + 자본 합계)로 확장 — 두 합계 칸에만 인쇄된 변동행 (2026-10-01, fix queue missing_row, 야간 자율 결정)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 계층형 SCE 표(그룹 소계 + 자본 합계)에서 아래를 **모두** 만족할 때만 그룹 소계 셀을 복제해 구성요소 열에 셀을 추가한다. (1) 행의 0 아닌 셀이 정확히 둘이고 둘 다 합계 열이며 값이 같다(하나는 경로가 한 단계 더 깊은 그룹 소계, 하나는 전체 합계). (2) 그 그룹 아래 구성요소 열 중 그 행에 셀이 없는 열(인쇄된 0 은 제외)에서 블록 롤포워드 잔차가 정확히 −값인 열이 딱 하나다. (3) 그룹 소계 열과 전체 합계 열의 블록이 모두 닫힌다. (4) 채운 뒤 그 구성요소 열도 정확히 닫힌다. `apply_source_defect_fixes` 안에서 R184 직후 적용한다.
> **판정 예** 지역난방공사 `20240321000860` 연결 SCE 2021 블록 '현금흐름위험회피의 세후차익(차손)': 앞 4칸(납입자본·이익잉여금·신종자본증권·기타자본구성요소)이 전각공백 빈칸이고 `지배기업 귀속 합계`와 `자본 합계`에만 (9,700,895,037) 인쇄 → 구성요소 열에 셀 추가. 측정: 변화 91필링·셀 100개, 전부 None→값 추가.
> **하지 않는 것** 인쇄된 0 칸은 채우지 않는다. 이미 닫힌 열, 그룹 합계 불닫힘, 그룹·전체 합계 값 불일치는 거부한다. 원인을 "colspan 병합"으로 보지 않는다(colspan 은 헤더에만 있다).
> **코드** `sce_source_defects.fill_hierarchical_total_only_rows` (`apply_source_defect_fixes` 안, R184 직후)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: 지역난방공사 2023FY `20240321000860` 연결 SCE 2021 블록 '현금흐름위험회피의 세후차익(차손)'(#84941, 재오픈 2회).
원문 행은 앞 4칸(납입자본·이익잉여금·신종자본증권·기타자본구성요소)이 전각공백 빈칸이고 `지배기업 귀속 합계`와 `자본 합계`에만
(9,700,895,037)이 인쇄돼 있다(원문 XML 확인). 이슈 근거의 "colspan 병합"은 사실과 다르다(colspan 은 헤더에만 있다).
R184 조건 1("합계 열이 정확히 1개")이 계층형 표를 제외해서 채워지지 않았다.

**규칙** (`sce_source_defects.fill_hierarchical_total_only_rows`, `apply_source_defect_fixes` 안에서 R184 직후):
아래를 **모두** 만족할 때만 그룹 소계 셀을 복제해 구성요소 열에 셀을 추가한다.
1. 행의 0 아닌 셀이 **정확히 둘**이고 둘 다 합계 열이며 값이 같다. 하나는 그룹 소계(경로가 한 단계 더 깊음), 하나는 전체 합계다.
2. 그 그룹 아래 구성요소 열 중 **그 행에 셀이 없는** 열(인쇄된 0 은 원문의 답이라 제외)에서 블록 롤포워드 잔차가 정확히 −값인 열이 **딱 하나**다.
3. 그룹 소계 열과 전체 합계 열의 블록이 모두 닫힌다(제목행·이중계상이 아니라 실제 변동이라는 증거).
4. 채운 뒤 그 구성요소 열도 정확히 닫힌다.
행 항등식(Σ그룹 구성요소 = 그룹 소계)은 조건 1 로 자동 성립한다. 표 자신의 항등식만 쓰며 추측이 아니다(R6 위반 아님).

**측정**: 스캔(DB 기준, `scripts/scan_r184b_hierarchical_total_only_2026-10-01.py` → `docs/qa/r184b_hier_total_only_scan_2026-10-01.jsonl`):
0 아닌 셀이 합계 열 둘뿐인 행이 있는 919필링 중 후보 **129필링 · 139행**(채울 열 이름은 이익잉여금 계열이 대부분).
재추출 켬/끔(`scripts/sce_onoff_tools_2026-09-27/measure_onoff_r184b.py`, 같은 워커·같은 DB 상태): 변화 **91필링 · 셀 100개, 전부 None→값 추가**(기존 셀 값 변경 0).
나머지 38필링은 현재 추출 체인에서 규칙이 발동하지 않았다(무변화; 원인 분류는 하지 않았다). 스캔은 DB 적재본 기준이라 스캔 밖 필링에서 발동하는지는 측정하지 않았다.

**회귀 테스트**: `fin2/tests/test_sce_source_defects.py` R184-b 6건(채움, 진입점 배선, 인쇄된 0 보존, 이미 닫힌 열 거부, 그룹 합계 불닫힘 거부, 그룹·전체 합계 값 불일치 거부).
**데일리 배선**: 별도 배선 불필요(`apply_source_defect_fixes` 는 `extract_report_lines` / XBRL 추출기 공용 경로 안). **소급**: 91필링(`docs/qa/r184b_backfill_targets_2026-10-01.txt`)을 `batch add-targets` + `batch reload`.

---

## R185. R162-d **부분 뒤집기 열**의 열 일관성 가드 — 증명될 때만 열 전체로 확장 (2026-09-27, 사용자 결정 B, fix batch #32)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 R162-d 가 뒤집은 셀이 있는 열마다, 뒤집기 전에 닫히던 블록이 뒤집은 뒤 깨졌으면 그 열의 남은 양수 셀을 모두 함께 뒤집어 본다. ① 열의 모든 블록 롤포워드가 닫히고 ② 관련 행의 행 항등식(`_row_identities`)이 모두 성립하고(R185-b 로 완화됨) ③ 어느 셀도 양수 앵커가 없을 때만 적용한다(`anchor_label='R185 열일관성 확장'`). 조건을 못 채우면 R162-d 결과를 그대로 둔다.
> **판정 예** 도이치모터스 2011Q1 `20110516003437` 별도 SCE 자본조정 열: 원문은 열 전체를 괄호 없이 인쇄, BS 는 (17,791,068,388). R162-d 는 17,791,068,388 인 3행만 음수로 만들어 2010 블록 롤포워드가 깨졌고, 행 항등식으로는 7셀(2010 기초 14,636,161,542·합병 행 3,154,906,846 포함) 모두 음수다.
> **하지 않는 것** "부분 뒤집기 되돌리기"는 채택하지 않는다(엔켐 `20240516001964` 이익잉여금 기말 −338,557,163,873 은 R162-d 가 증명한 값이고 BS 와 같음). 롤포워드 하나만으로 악화를 판정하지 않는다. 현재 DB 의 기존 부분 뒤집기(2,362열/2,021필링)는 이번 범위 밖이며(사용자 결정 B) 다음 재적재 때 자동 적용된다.
> **코드** `sce_sign_repair._column_consistency_guard`(`repair_sce_row_identity` 끝) · 테스트 `fin2/tests/test_r162d_row_identity.py`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: 도이치모터스 2011Q1 `20110516003437` 별도 SCE 자본조정 열. 원문은 열 전체를 괄호 없이(양수) 인쇄했고 BS 는
(17,791,068,388)이다. R162-d 는 행마다 따로 판정하고 같은 금액의 음수 증거가 있는 셀만 뒤집는다. 그래서 17,791,068,388 인
3행(2010 기말·2011 기초·2011 기말)만 음수가 됐다. BS 에 없는 2010 기초 14,636,161,542 와 합병 행 3,154,906,846 은 양수로 남아
2010 블록 롤포워드가 깨졌다. 행 항등식으로는 자본조정 7셀 모두 음수다.

**판단 정정(중요)**: 처음에는 "옛 DB(전부 양수, 롤포워드는 닫힘)보다 악화"로 봤다. 셀 단위로 보면 옛 DB 는 7셀이 모두 틀렸고
R162-d 결과는 3셀이 맞다. R162-d 의 뒤집기는 행 항등식과 외부 음수 증거로 **셀마다 증명**된 값이다.
롤포워드 하나만으로 악화를 판정하면 안 된다.
- 반례: 엔켐 `20240516001964` 이익잉여금 기말 −338,557,163,873 은 R162-d 가 뒤집은 값이고 BS 와 같다.
  "부분 뒤집기 되돌리기" 안을 적용하면 이 증명된 셀이 +338.5B 로 망가졌다. 그래서 되돌리기는 채택하지 않는다.

**규칙** (`sce_sign_repair._column_consistency_guard`, `repair_sce_row_identity` 끝):
R162-d 가 뒤집은 셀이 있는 열마다, 뒤집기 **전에 닫히던 블록이 뒤집은 뒤 깨졌으면** 그 열의 남은 양수 셀을 모두 함께 뒤집어 본다.
① 열의 모든 블록 롤포워드가 닫히고 ② 관련 행의 행 항등식(`_row_identities`)이 모두 성립하고 ③ 어느 셀도 양수 앵커가 없을 때만
적용한다(`anchor_label='R185 열일관성 확장'`). 조건을 못 채우면 R162-d 결과를 그대로 둔다.

**측정** (잠재 후보 = 잔액이 전부 양수이고 행 항등식은 열 음수로만 닫히는 열, 161열/156필링,
`scripts/scan_r162d_partial_flip_scope_2026-09-27.py`, 모두 `include_notes=True` 재추출):
- R185 전: 부분 뒤집기로 블록이 깨짐 61열/59필링, 열 전체 뒤집힘 55, 변화 없음 39, 기타 6.
- R185 후: 열 전체 뒤집힘 79(+24 확장), 부분 뒤집기 유지 37열/35필링(셀별 증명값), 변화 없음 39, 기타 6.
- R185 가 바꾸는 셀은 156필링 중 27필링 102셀이다. 모두 양수를 음수로 바꾸는 확장이고, 양수로 만드는 셀은 0이다.

**재적재 대상 선정**(59필링): 재추출과 DB 가 다른 셀은 960개다(R185 확장 99, 나머지 861 은 옛 적재 이후 다른 규칙들의 기존 차이).
롤포워드와 행 항등식 두 기준으로 셀마다 판정했다. 한 기준이 악화되고 다른 기준은 개선되지 않는 셀이 19개(12필링)였다.
이 19셀은 모두 R185 와 무관한 기존 차이다(자기주식 취득·매도가능증권평가이익·종속기업배당 등). 이 12필링은 제외하고
**47필링을 재적재**한다. 제외 목록: `docs/qa/r185_excluded_2026-09-27.txt`.

**현재 DB 에 이미 있는 부분 뒤집기**(① 스캔: 잔액 부호가 섞이고 블록이 깨졌는데 양수 셀을 뒤집으면 닫히는 열
2,362열/2,021필링)는 이번 범위가 아니다(사용자 결정 B). 다음 재적재 때 R185 가 자동으로 적용된다.

**회귀 테스트**: `fin2/tests/test_r162d_row_identity.py` R185 3건(열 전체 확장, 닫히지 않으면 증명된 뒤집기 유지, 닫힌 블록이 안 깨지면 무관여).

---

## R187. SCE 잔액 행의 **날짜 앵커** — 같은 필링 BS 전기말 열 + 직전 사업보고서 BS (2026-09-27, 사용자 결정, fix batch #35)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 잔액 행 라벨의 날짜 D 로 부호 앵커를 만든다(기초는 D−1일, 기말은 D 시점 BS 잔액). 키는 `(basis, 개념 라벨, 날짜)`. 1단계는 같은 필링 BS col 0·1·2(열 날짜는 SCE 잔액 날짜로 정함: col 0 = 최신 기말, col 1 = 최신 기초 전날, col 2 = 다음 기초 전날·사업보고서만), 2단계는 적재 쪽이 `load_prior_balances()`(같은 회사, 이 필링보다 앞선 사업보고서 최근 3개 기간 BS col 0)로 읽어 `extract_report_lines(prior_balances=)` 로 넘긴다. 그 날짜 BS 자본총계가 같은 날짜 SCE 합계 열과 같을 때만 그 날짜 앵커를 쓴다.
> **판정 예** 본문에 개별 셀 예는 없다(설계 문서 `docs/plans/sce_opening_prior_period_anchor_design_2026-09-27.md`).
> **하지 않는 것** 앵커는 증거일 뿐이며 R162 계열은 여전히 항등식이 정확히 닫혀야 적용한다. 자본총계가 SCE 합계 열과 다른 날짜의 BS 는 앵커로 쓰지 않는다. XBRL 경로는 대상이 아니다. 추출기는 DB 를 조회하지 않는다.
> **코드** `fin2/extract/sce_dated_anchors.py`(`_required_sign` 에서 먼저 조회), `load_prior_balances()`; 배선 `collector/note_lines_sync.py`, `ops._reload_rcept`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**설계**: `docs/plans/sce_opening_prior_period_anchor_design_2026-09-27.md`(측정 포함).
SCE 잔액 행 라벨의 날짜 D 로, 기초는 D−1일, 기말은 D 시점의 BS 잔액이 부호를 증명한다. 기존 앵커(`build_sign_anchors`)는
BS col 0 만 쓰고 금액만 맞췄다.

**수정** (`fin2/extract/sce_dated_anchors.py`, `_required_sign` 에서 먼저 조회):
- 키 `(basis, 개념 라벨, 날짜)`. **1단계**: 같은 필링 BS col 0·1·2 를 쓴다. 열 날짜는 SCE 자신의 잔액 날짜로 정한다
  (col 0 = 최신 기말, col 1 = 최신 기초 전날, col 2 = 다음 기초 전날·사업보고서만). **2단계**: 적재 쪽이
  `load_prior_balances()`(같은 회사, 이 필링보다 앞선 사업보고서 최근 3개 기간의 BS col 0)로 읽어 `extract_report_lines(prior_balances=)`
  로 넘긴다. 추출기는 DB 를 모른 채로 둔다.
- **가드**: 그 날짜 BS 의 자본총계가 같은 날짜 SCE 합계 열과 **같을 때만** 그 날짜 앵커를 쓴다(재작성·열 매핑 오류 차단).
- 앵커는 증거일 뿐이다. R162 계열은 여전히 항등식이 정확히 닫혀야 적용한다.
- 배선: `collector/note_lines_sync.py`(collect_new 두 call site 공용 경로, rcept 순서 = 시간순이라 직전 보고서가 먼저 적재됨),
  `ops._reload_rcept`, 검증 상세(`ops.py` 필링 상세). XBRL 경로는 부호가 fact 에 있어 대상이 아니다.
- **연쇄**: 직전 사업보고서가 다시 적재되면 다음 해 필링도 결과가 바뀔 수 있다. 참조 관계는 `filings`(회사·기간)로 계산된다
  (스키마 변경 없음). 대량 재적재 뒤에는 다음 해 필링을 후속 재적재 대상으로 검토한다.

## R188. SCE 잔액 셀 **1,000원 허용오차 이중 항등식** (2026-09-27, 사용자 결정: 소액 차이 1,000원 이하 허용, fix batch #35)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 양수 잔액 셀(기초·기말) 하나를 뒤집었을 때 열 롤포워드 블록과 행 항등식이 **둘 다 |잔차| ≤ 1,000원**이 되고, 뒤집기 전에는 둘 다 1,000원을 넘으면 그 셀을 뒤집는다(정확히 0 으로 닫히는 경우 포함). 양수를 가리키는 앵커(R187 날짜 앵커 또는 BS col 0)가 있으면 적용하지 않는다. R162…R185 뒤에 적용한다.
> **판정 예** 원익큐브 `20160330000801` 별도 "2013.01.01 (기초자본)" 기타포괄손익누계액 705,022,515: 롤포워드 −705,022,513, 기초 행 합계 −705,022,515(2원 차) → −705,022,515.
> **하지 않는 것** 행 항등식이 없는 행은 대상이 아니다. 한쪽 항등식만 1,000원 이내면 적용하지 않는다. 양수 앵커가 있으면 뒤집지 않는다.
> **코드** `sce_sign_repair.repair_sce_balance_tolerance`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: 원익큐브 `20160330000801` 별도 "2013.01.01 (기초자본)" 기타포괄손익누계액 705,022,515. 2012 보고서에는 이 열이 없고
(이익잉여금에 포함), 2013 블록 롤포워드로 −705,022,513, 기초 행 합계로 −705,022,515(2원 차)가 나온다. 원 단위 반올림으로
정확히 닫히지 않아 R162 계열이 건너뛰었다.

**수정** (`sce_sign_repair.repair_sce_balance_tolerance`, R162…R185 뒤): 양수 잔액 셀(기초·기말) 하나를 뒤집었을 때
**열 롤포워드 블록과 행 항등식이 둘 다 |잔차| ≤ 1,000원**이 되고, 뒤집기 전에는 둘 다 1,000원을 넘으면 뒤집는다.
양수를 가리키는 앵커(R187 날짜 앵커 또는 BS col 0)가 있으면 적용하지 않는다. 행 항등식이 없는 행은 대상이 아니다.
- 이 조건은 정확히 0으로 닫히는 경우도 포함한다. 서로 독립인 두 항등식이 같은 부호를 요구하는 것이 이중 증거다.

**측정** (후보 = 직전 보고서와 부호 불일치 3,828필링 ∪ DB 스캔으로 찾은 R188 후보 1,802필링 = 4,827필링,
`scripts/scan_r188_balance_tolerance_2026-09-27.py`, 주석·직전 보고서 포함 재추출, 켬/끔 + R187 단독 비교):
- 바뀌는 셀 3,152개(883필링): R187 2,753(음수화 2,141 / 양수화 612), R188 399(모두 음수화).
- 셀마다 켬/끔 값으로 롤포워드·행 항등식을 판정했다. R188 399셀은 모두 개선 또는 유지다. R187 은 개선·유지 2,468,
  혼재 221, **명확한 악화 64**(41필링)다. 악화는 대부분 롤포워드는 전후 모두 닫히는데 행 항등식이 깨지는 경우다. 날짜 앵커로
  블록의 해가 바뀌면서 변동 행까지 함께 뒤집혔다(예: `20131128000817` 해외사업환산차이).
- 재적재 대상: 883 − R187 악화 41 − DB 대비 기존 차이 악화 15 = **827필링**(pre-2015 142).
  `docs/qa/r187_reload_targets_2026-09-27.txt`, 제외 `docs/qa/r187_excluded_2026-09-27.txt`.
- 원익큐브 "2013.01.01 (기초자본)": 자본조정 −9,615,576, 기타포괄 −705,022,515 가 된다(기초 행 합계 2원 차).

**회귀 테스트**: `fin2/tests/test_sce_dated_anchors.py` 7건(기초 날짜 = 전날, 1단계 증명, 자본총계 불일치 시 무증거,
2단계 증명, R188 적용·한쪽 항등식만이면 미적용·양수 앵커 거부권).

**악화 64셀 조사 결과(2026-09-27, 착시로 판명)**: 원문이 구성요소 열 하나(기타포괄·자기주식·비지배지분 등)를 **통째로 반대 부호로**
인쇄한 경우다. R187 이 BS 로 잔액 부호를 확정하면 R162 가 열 전체(변동 행 포함)를 바로잡는다. 이 결과는 맞다. 그런데 같은 행
**합계 열에 별개의 다셀 부호 누락**이 남아 행 항등식이 깨졌고, 그래서 "악화"로 잡혔다.
근거별 셀 수: 합계 열 롤포워드도 새 부호 지지 53, 구성요소 열 롤포워드 정확히 닫힘 6(대화제약 `20171114001482`, 대동 `20190814000290`),
직전 보고서 IS 일치 1(신성이엔지 `20221114000839` 2021Q3 연결 NI −11,651,865,523), 형제 열 미수정 1(케이엘넷), 불명 1(인터엠 `20160516001934`),
진짜 악화 2(씨에스베어링 `20220516002123` '주식선택권' 합계 열 −3,426,150 → +). → 41필링 중 39필링을 추가 재적재했다(batch #36,
`docs/qa/r187_followup_reload_targets_2026-09-27.txt`). 씨에스베어링·인터엠은 제외를 유지한다.
★교훈: 행 항등식만으로 판정하면 형제 열 미수정을 악화로 잡는다. 구성요소 열·합계 열의 롤포워드를 함께 본다.
재확인 목록 1,150셀/848필링은 2015+ 작업 시점에 다시 본다(사용자 결정).

---

## R189. 체인 뒤에도 깨진 행 항등식 — **형제 셀**을 열 롤포워드와 외부 증거로 맞춤 (2026-09-27, 사용자 지시, fix batch #37)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 체인 뒤에도 깨진 행 항등식을, 그 항등식을 닫는 **유일한 최소 양수 셀 조합**(R162-d 탐색)을 뒤집어 맞추되 아래를 모두 요구한다. (1) 뒤집는 셀마다 자기 열의 블록 롤포워드 잔차가 **엄격히 줄어야** 하고, 양수를 가리키는 앵커(R187 날짜 앵커·BS col 0)가 있으면 거부한다. (2) **변동 행**은 추가로 (a) 같은 행의 나머지 0 아닌 셀이 각자 자기 열에서 정확히 닫히고, (b) 부호가 표 밖에서 알려져야 한다(같은 필링 IS 에 같은 금액이 음수로 있거나, 배당·자기주식 취득 행). R188 뒤에 적용한다.
> **판정 예** 조건 1만 쓴 1차에서는 `20231114002833` NI 합계를 IS +1,392,030,273 과 반대로 음수화하는 등 IS 반대 60셀이 나와 조건 2를 추가했다. 최종 1,765셀 / 1,128필링(잔액 1,039 · 변동 726).
> **하지 않는 것** 외부 증거 없는 기타포괄·순이익류 변동 행(2,708셀)은 적용하지 않는다. `20131128000817` 2011 블록 해외사업환산차이의 합계 열도 여기에 속해 고쳐지지 않는다.
> **코드** `sce_sign_repair.repair_sce_sibling_cells`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: R187 악화 64셀 조사. 구성요소 열(기타포괄·자기주식·비지배지분)이 통째로 반대 부호로 인쇄된 표는 R187/R162 가 바로잡는다.
그런데 같은 행 **합계 열에 다셀 부호 누락**이 남아 행 항등식이 깨졌다(`20131128000817` 해외사업환산차이: 기타포괄 −254,104,651,
지배합계·자본합계 +254,104,651, 자본합계 열 잔차 = 2 × (1,429,817,000 + 254,104,651)). 단일 셀 규칙(R162-e)으로는 못 푼다.

**규칙** (`sce_sign_repair.repair_sce_sibling_cells`, R188 뒤): 행 항등식을 닫는 **유일한 최소 양수 셀 조합**(R162-d 탐색)에 대해 아래를 모두 요구한다.
1. 뒤집는 셀마다 **자기 열의 블록 롤포워드 잔차가 엄격히 줄어야** 한다. 양수를 가리키는 앵커(R187 날짜 앵커·BS col 0)가 있으면 거부한다.
2. **변동 행**은 추가로 다음 둘을 모두 만족해야 한다.
   - (a) 같은 행의 나머지 0 아닌 셀(항등식이 참값으로 쓰는 셀)이 **각자 자기 열에서 정확히 닫혀야** 한다.
   - (b) 부호가 **표 밖에서 알려져야** 한다. 같은 필링 IS 에 같은 금액이 음수로 있거나, 배당·자기주식 취득 행(성격상 음수)이어야 한다.

**측정과 범위를 좁힌 과정** (후보 = DB 에 R189 를 적용해 바뀌는 5,457필링, 주석·직전 보고서 포함 켬/끔 재추출,
`scripts/scan_r189_sibling_cells_2026-09-27.py`, `scripts/eval_r189_outside_evidence_2026-09-27.py`):
- 1차(조건 1만): 5,679셀 / 2,310필링. **잔액 셀**은 BS 대조 261 일치 / **0 불일치**였다. **변동 셀**은 IS 증거가 있는 145셀 중 **60셀이 IS 와 반대**였다
  (예: `20231114002833` NI 합계를 IS +1,392,030,273 과 반대로 음수화, `20120417000015` 매도가능증권평가이익을 음수화). 원인은 항등식이 참값으로
  쓰는 구성요소 셀 자체가 잘못 음수여서, 그 오류가 합계로 번진 것이다.
- 조건 2(a)만 추가하면 IS 반대 60셀 중 40셀이 걸러지고 20셀이 남는다. 그래서 외부 증거 없는 기타포괄·순이익류 변동 행(2,708셀)은 적용하지 않는다(2(b)).
- **최종: 1,765셀 / 1,128필링**(잔액 1,039 · 변동 726). 잔액은 BS 일치 261 / 불일치 0. 변동 셀의 IS/CF 불일치 14셀은 모두 CF 인쇄 관행
  (재무활동 유출을 괄호 없이 인쇄)이다.
- 적용하지 않은 범위: 외부 증거 없는 기타포괄·순이익류 변동 행이다. 대표 사례 `20131128000817` 2011 블록 해외사업환산차이의 합계 열도 여기에 속해
  이번에는 고쳐지지 않는다. 필요하면 직전 보고서 IS 를 증거로 쓰는 확장(R187 2단계와 같은 방식)을 검토한다.

**재적재**: fix batch #37, 1,101필링. 1,128 중 다른 규칙의 기존 차이가 DB 대비 명확히 악화되는 27필링(49셀, R189 셀은 0)은 제외했다
(`docs/qa/r189_reload_targets_2026-09-27.txt`, 제외 `docs/qa/r189_excluded_2026-09-27.txt`).

**회귀 테스트**: `fin2/tests/test_sce_dated_anchors.py` R189 3건(IS 증거 있는 합계 셀 맞춤, 열 잔차가 커지면 거부, 외부 증거 없는 변동 행 미적용).

---

## R189-b. R189 변동 행의 외부 증거에 **이전 보고서 IS**(블록과 같은 기간) 추가 (2026-09-27, 사용자 지시, fix batch #38)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 R189 에서 외부 증거가 없던 변동 행 셀에 대해, 블록 기간(기초일·기말일)과 정확히 같은 기간의 같은 회사 이전 보고서 IS col 0(사업보고서 = 연간, 분·반기 = 누적 `is_cumulative`, 기간 시작 = 전 사업연도말 + 1일)에 같은 금액이 음수로만 있으면 외부 증거로 인정해 음수화하고, 양수로만 있으면 거부한다. IS 행은 같은 성격(평가·환산·재측정·지분법·순이익·재평가·위험회피)이거나 성격 없는 포괄 소계 행('기타포괄손익', '…재분류되지 않는 항목', '지배기업 소유주 귀속')이어야 한다(`_same_income_item`).
> **판정 예** 에스앤에스텍 2013 사업보고서: IS 매도가능증권평가손익 −24,882,000, 같은 보고서 SCE +24,882,000 → SCE 가 아니라 OCI 의 1차 원천인 IS 를 따라 음수.
> **하지 않는 것** 다른 기간·다른 항목의 IS 는 증거가 아니다(예: `20140717000223` SCE '해외사업환산손익' vs IS '해외사업장순투자의 위험회피'). 이전 IS 에 해당 행이 없으면 그대로 둔다(`20131128000817` 2011 블록 해외사업환산차이). SCE 는 검증 기준으로 쓰지 않는다.
> **코드** `sce_dated_anchors.load_prior_income`·`load_prior_evidence`, `sce_sign_repair._prior_income_signs`, `_same_income_item`, `extract_report_lines(prior_income=)`, 배선 `note_lines_sync`·`ops._reload_rcept`
> **코드 확인** (2026-10-12) 이전 보고서 IS 에 같은 금액이 양수·음수로 모두 있으면 증거 없음으로 본다: R192 앵커는 부호가 하나일 때만 만들고, R189 는 그 증거를 쓰지 않아 다른 근거(올해 IS 부호 등)가 있어야 뒤집는다(`_prior_income_signs`, `sce_sign_repair.py:1823-1834`).

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**배경**: R189 는 외부 증거 없는 기타포괄·순이익류 변동 행(2,708셀)을 적용하지 않았다. 비교 블록(예: 2013 3분기 보고서의 2012 블록)의
증거는 그 기간을 보고한 **이전 보고서의 IS** 에 있다.

**수정** (`sce_dated_anchors.load_prior_income`/`load_prior_evidence`, `sce_sign_repair._prior_income_signs`):
- 적재 쪽이 같은 회사 이전 보고서의 IS col 0(사업보고서 = 연간, 분·반기 = 누적 `is_cumulative`)을 `(기간 시작, 기간 끝)` 키로 넘긴다
  (`extract_report_lines(prior_income=)`). 기간 시작은 그 전 사업연도말 + 1일이다.
- R189 변동 행 셀의 블록 기간(기초일·기말일)과 **정확히 같은 기간**의 IS 에 같은 금액이 음수로만 있으면 외부 증거로 인정한다. 양수로만 있으면 거부한다.
- **라벨 성격 가드**(`_same_income_item`): IS 행은 같은 성격(평가·환산·재측정·지분법·순이익·재평가·위험회피)이거나, 성격 없는 포괄 소계 행
  ('기타포괄손익', '…재분류되지 않는 항목', '지배기업 소유주 귀속')이어야 한다. 측정에서 363건 중 67건이 성격이 달랐다. 대부분은 항목이 하나뿐인
  OCI 절의 소계였지만, 우연 일치도 있었다(`20140717000223` SCE '해외사업환산손익' vs IS '해외사업장순투자의 위험회피').
- 배선: `note_lines_sync`, `ops._reload_rcept`, 검증 상세 모두 `load_prior_evidence()` 하나로 BS·IS 증거를 함께 읽는다.

**측정** (후보 = R189 에서 외부 증거가 없어 적용하지 않은 변동 셀이 있는 1,060필링, 이전 IS 켬/끔):
- 최종 **339셀 / 184필링**, 전부 음수화.
- 독립 검증으로 그 기간을 처음 보고한 보고서의 SCE 부호와 비교했다. 일치 293 / 불일치 66(가드 적용 전 363셀 기준).
  불일치 표본은 **처음 보고한 SCE 쪽이 괄호를 잃은 경우**였다. 예: 에스앤에스텍 2013 사업보고서는 IS 매도가능증권평가손익 −24,882,000,
  같은 보고서 SCE 는 +24,882,000, 2015년 이후 보고서 SCE 는 −24,882,000. 그래서 SCE 는 검증 기준이 되지 못하고, OCI 변동의 1차 원천인 IS 를 따른다.
- 한계: 20131128000817 2011 블록 해외사업환산차이는 2011 사업보고서 DB 의 IS 에 해당 행이 없다(그 보고서 SCE 에는 −254,104,651 이 있다).
  이 경우는 IS 증거가 없어 그대로 남는다.

**재적재**: fix batch #38, 173필링. 184 중 다른 규칙의 기존 차이가 DB 대비 명확히 악화되는 11필링(19셀, R189-b 셀은 0)은 제외했다
(`docs/qa/r189b_reload_targets_2026-09-27.txt`, 제외 `docs/qa/r189b_excluded_2026-09-27.txt`).

**회귀 테스트**: `fin2/tests/test_sce_dated_anchors.py` R189-b 3건(같은 기간 이전 IS 증거로 적용, 다른 기간·다른 항목은 무증거, 양수 IS 거부).

---

## R190. SCE **거울해 가드** — 분기·반기 BS 날짜 앵커(G-A) + 잔액 행 자체 증명(G-B(i)) + 앵커 해법 자기일관성(R190-b) (2026-09-27, 사용자 결정, fix batch #39)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 거울해를 세 가드로 막는다. (G-A) `load_prior_balances` 2단계 앵커를 사업보고서뿐 아니라 분기·반기 보고서 BS col 0(이 필링보다 앞선 3년, 날짜별 최신 rcept)까지 읽고, BS 라벨에서 주석 번호(`자본금 (주20)`)를 뗀 키도 넣는다. 기존 가드(그 날짜 BS 자본총계 = SCE 합계 열)는 그대로다. (G-B(i), R162 에서만) SCE 잔액 행의 최상위 합계 셀이 그 날짜에 채택된 BS 자본총계와 같고 그 행의 행 항등식이 인쇄 그대로 모두 성립하면, 행의 0 아닌 셀마다 인쇄 부호를 날짜 앵커로 준다. (R190-b, `_solve_block` 끝) R186 자기일관성(`_closes_after_flip`)을 앵커 해법에도 적용해, 뒤집은 뒤 소계가 증명되고 블록이 닫히지 않으면 거부한다.
> **판정 예** LB인베스트먼트 `20260318000708` 연결 자본 합계 2025 블록: G-B 로 기말이 앵커되자 "배당 −, 소계 −" 가 블록을 닫았으나, 뒤집은 뒤 소계가 증명되고 블록이 닫히지 않으므로 R190-b 가 거부. 씨에스베어링 `20220516002123`·넵튠 2건·제닉스로보틱스 `20241114000214` 의 거울해 악화가 해소됨.
> **하지 않는 것** 기각: "약한 증거 뒤집기로 인쇄 상태에서 성립하던 행 항등식이 깨지면 되돌린다"(G1). 보류: G-B(ii)(열 전체 반전, `20191114000117`). 효성중공업 `20190618000144`(XBRL)는 제외. G-B(i) 앵커는 뒤 단계(R162-d·R188·R189)에 쓰지 않는다.
> **코드** `sce_dated_anchors.load_prior_balances`, `sce_sign_repair.add_row_proven_anchors`, `sce_sign_repair._solve_block`(`_closes_after_flip`)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**설계**: `docs/plans/sce_mirror_guard_design_2026-09-27.md`. 사용자 결정: G-A·G-B(i)만 진행, G-B(ii)는 보류.

**발견**: 인계 1-1(M 집합 = DB 부분 뒤집기 2,021필링) 2015+ 재측정. 현재 코드로 바뀌는 308필링 중 6필링이 명확히 악화했다.
R162 의 전제(원문은 괄호를 **빠뜨리기만** 한다)가 깨진 표에서, 잔액의 부호가 외부로 확정되지 않은 블록을 R162-e(단일셀) 또는
R162-b(이월잔액)가 인쇄된 잔액에 맞춰 옳은 셀을 뒤집어 닫았다(거울해).
- 씨에스베어링 `20220516002123`: 2021 비교 블록 잔액만 괄호 누락. 주식선택권 +3,426,150 을 뒤집음.
- 넵튠 `20210817001798`·`20220906000316`: 2020.01.01 기초 자본금이 음수로 인쇄(가짜 괄호). 기말 자본금까지 음수로 뒤집음.
- 제닉스로보틱스 `20241114000214`: 변동 '주식매수선택권' 에 가짜 괄호. 기말 +121,834,279(행 합계 = BS 자본총계)를 뒤집음.
- `20191114000117`(열 전체 반전, G-B(ii) 범위)·효성중공업 `20190618000144`(XBRL 경로)는 제외로 남긴다.

**기각**: "약한 증거 뒤집기로 인쇄 상태에서 성립하던 행 항등식이 깨지면 되돌린다"(G1). 체인 끝에서 판정해도 맞는 셀(디알텍
BS 자본총계 증명·신성델타테크·티이엠씨씨엔에스·케이아이엔엑스)을 되돌렸다. 원문이 한 행 전체에서 괄호를 **일관되게** 빠뜨리면
인쇄 상태로도 행 항등식이 성립하므로, "인쇄 상태에서 성립"은 부호 증거가 아니다.

**수정**:
- **G-A** (`sce_dated_anchors.load_prior_balances`): 2단계 앵커를 사업보고서만이 아니라 **분기·반기 보고서 BS col 0** 까지
  (이 필링보다 앞선 3년, 날짜별 최신 rcept) 읽는다. 비교 블록의 분기말·반기말 잔액에 앵커가 생긴다. BS 라벨의 주석 번호
  (`자본금 (주20)`)를 뗀 키도 함께 넣는다(SCE 열 개념은 주석 번호가 없다). 기존 가드(그 날짜 BS 자본총계 = SCE 합계 열)는 그대로다.
- **G-B(i)** (`sce_sign_repair.add_row_proven_anchors`, R162 에서만): SCE **잔액 행**의 최상위 합계 셀이 그 날짜에 채택된
  BS 자본총계와 같고, 그 행의 행 항등식이 **인쇄 그대로 모두 성립**하면 행의 0 아닌 셀마다 인쇄 부호를 날짜 앵커로 준다.
  합계가 BS 에 고정돼 있어 "행 전체 일관 누락"(G1 기각 사유)이 불가능하다. 뒤 단계(R162-d·R188·R189)는 이미 고친 값을 보므로 쓰지 않는다.
- **R190-b** (`_solve_block` 끝): R186 자기일관성(`_closes_after_flip`)을 **앵커 해법에도** 적용한다. LB인베스트먼트
  `20260318000708` 연결 자본 합계 2025 블록: 기초 합계가 오기(= 기말 126,962,988,014, 전기말은 119,034,309,285)이고, 배당 괄호 누락으로
  '자본 증가(감소) 합계' 가 증명되지 못해 변동으로 합산됐다. G-B 로 기말이 앵커되자 "배당 −, 소계 −" 가 블록을 닫았다.
  뒤집은 뒤 소계가 증명되고 블록이 닫히지 않으므로 거부한다.

**측정**:
- M 2015+ 307필링(현재 코드 대비): 악화 6필링 중 4필링 해소(씨에스베어링·넵튠 2·제닉스). 새로 바뀐 23셀은 모두 외부 증거로 확인
  (포스코엠텍 `20180814001838` 2017H1 IS 재측정요소 −595,839,019 · CSA 코스믹 BS 결손금 · 씨에스베어링 BS 기타포괄 −3,557,232,139 등).
- 전사 표본(2015+ SCE 필링 무작위 1만, 기준선 = HEAD `12dca70`): 바뀌는 필링 56(0.56%), 261셀(양→음 236, 음→양 25).
  두 기준 판정 + BS 금액 대조로 의심 셀을 모두 원문 대조했다. 악화는 LB인베스트먼트 1셀이었고 R190-b 로 해소됐다.
  나머지 의심 셀은 판정기 착시였다(형제 합계 열 미수정: 비츠로테크 `20171114001907` 비지배 열 롤포워드 −9,727,000 으로 닫힘,
  하이로닉 `20170515003990` 기타불입자본 BS 잔액 역산으로 변동 +30,577,779; BS 금액 우연 일치: 배당·풋옵션부채·전환권대가).
- R190-b 단독 효과(표본 1만): 1셀(LB).

**재적재**: fix batch #39. ① M 2015+ 303필링(XML 291 + XBRL 12, `docs/qa/sce_m2015_reload_targets_2026-09-27.txt`,
제외 2필링 `docs/qa/sce_m2015_excluded_2026-09-27.txt`) — done 303, 재적재 후 드라이런 차이 0.
② 전사 소급: 2015+ SCE XML 104,133필링 드라이런 → DB 와 다른 2,063필링을 HEAD `12dca70` 기준선으로 다시 돌려 R190 효과만 분리
→ **572필링 2,561셀**. 두 기준 판정 + 형제 열 검사 + BS 금액 대조로 의심 246셀을 원문·이전 보고서 SCE·IS·BS 로 대조했다
(제닉·일월지엠엘은 같은 기간 이전 보고서 SCE 가 전 셀 음수, 우정바이오·에쓰씨엔지니어링은 이전 IS 순손실로 새 값 증명).
재적재 557필링(`docs/qa/r190_backfill_targets_2026-09-27.txt`) — done 557, 재적재 후 드라이런 차이 0.
제외 15필링(`docs/qa/r190_backfill_excluded_2026-09-27.txt`): 신규 5(씨에스윈드·넥스트아이 증거 부족, 미래에셋생명 2 — 새 앵커가
기준선의 정답 해법(이월잔액, 소계 −357,223,730)을 잃게 함, 잉크테크 원문 오류 행) + 이전 제외 목록 중복 10.
- ★남은 한계: 미래에셋생명 `20240320002014` 처럼 앵커가 늘어 기존 해법이 사라지는 경우가 있다(원인 미분석).
- 이번 드라이런에서 R190 과 무관하게 HEAD 코드와 DB 가 다른 필링 1,491개가 확인됐다(과거 배치에서 재적재되지 않은 기존 차이). 별도 과제.

**회귀 테스트**: `fin2/tests/test_sce_mirror_guard_r190.py` 6건(잔액 행 자체 증명이 거울해 거부 · BS 자본총계 불일치면 무증거 ·
인쇄 항등식 불성립이면 무증거 · 주석번호 BS 라벨 앵커 · 분기 BS 로 비교 블록 해소 · R190-b 앵커 해법의 소계 자기일관성).

## R190-c. SCE **중첩 소계** 판정·부호 (2026-09-27, fix batch #40)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 소계 증명에서 누적 구간 `run` 외에 닫힌 소계를 대표값으로 남기는 `wide` 구간을 함께 유지해, 소계 라벨 행이 둘 중 하나의 합과 절대값이 같으면 소계로 증명한다. 소계 바로 다음 소계(앞 소계 반복)도 `wide` 로 증명하며, `_subtotal_fixes` 도 같은 방식으로 부호를 정한다(안쪽 소계는 확정된 부호로 대표). 기존에 증명되던 소계는 그대로 증명된다.
> **판정 예** 미래에셋생명 `20240320002014`·`20240430001080` 자본조정: 취득 −2,054,753,945 · 처분 2,064,968,675 → '자기주식 거래에 따른 증가(감소) 합계' 10,214,730, 기타변동 347,009,000 → '소유주와의 거래 합계' 357,223,730 → '자본 증가(감소) 합계' 357,223,730 → 2022 블록 잔액 음수·소계 +357,223,730(BS −371,633,476,625 → −371,276,252,895). 주식발행초과금 2021 블록 두 소계 −20,664,124.
> **하지 않는 것** 앵커와 반대인 닫힌 블록(변동 없이 인쇄 그대로 닫힌 블록, 예: 2023 블록)을 뒤집지 않는다 — 그런 규칙은 없고, 블록이 안 닫혀도 BS 앵커로 적용할지는 사용자 판단 대기 과제다. 소급 제외 3필링(DB 값이 정답): 대화제약 `20221114000343`·화승엔터프라이즈 `20210319000901`(기준선이 우연히 맞춘 잔액), 대화제약 `20201116000664`(원문 가짜 괄호를 소계 부호가 따라감).
> **코드** `sce_sign_repair._proven_subtotals`, `sce_sign_repair._subtotal_fixes`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: R190 전사 소급에서 제외했던 미래에셋생명 `20240320002014`·`20240430001080` 을 조사했다. R190 의 부작용이 아니었다.
**DB(이전 코드)가 거울해**였다. BS 자본조정은 −371,633,476,625 → −371,276,252,895 인데, 이전 코드는 잔액을 양수로 둔 채 변동 소계를
−357,223,730 으로 뒤집어 맞췄다. R190 날짜 앵커가 이 거울해를 막았다. 그런데도 정답이 나오지 않은 원인은 **중첩 소계**다:
자기주식 취득 −2,054,753,945 · 처분 2,064,968,675 → '자기주식 거래에 따른 증가(감소) 합계' 10,214,730, 기타변동 347,009,000 →
'소유주와의 거래 합계' 357,223,730 → '자본 증가(감소) 합계' 357,223,730.
`_proven_subtotals` 는 안쪽 소계를 닫으면서 누적 구간을 비웠다. 그래서 바깥 두 소계가 증명되지 못하고 변동으로 이중 합산됐다.

**수정** (`sce_sign_repair._proven_subtotals`, `_subtotal_fixes`): 누적 구간 `run` 외에, 닫힌 소계를 대표값으로 남기는 `wide` 구간을
함께 유지한다. 소계 라벨 행이 둘 중 하나의 합과 절대값이 같으면 소계다. 소계 바로 다음 소계(앞 소계를 반복)도 `wide` 로 증명한다.
`_subtotal_fixes` 도 같은 방식으로 부호를 정한다(안쪽 소계는 **확정된 부호**로 대표). 기존에 증명되던 소계는 그대로 증명된다.
- 결과: 미래에셋생명 자본조정 2022 블록 잔액 음수 · 소계 +357,223,730, 주식발행초과금 2021 블록 두 소계 −20,664,124
  (BS 자본잉여금 181,405,147,964 → 181,384,483,840 과 일치). 2021·2023 블록의 자본조정 잔액은 여전히 양수다. 2023 블록은 변동이 없어
  인쇄 그대로 "닫혀" 있다. 앵커와 반대인 닫힌 블록을 뒤집는 규칙은 없다(별도 과제).

**측정** (같은 DB 상태에서 HEAD `9d88f2f` 대비, 2015+ SCE 무작위 1만): 12필링 26셀. 대부분 '자본 증가(감소) 합계' 류 소계가
구성요소 합의 부호로 맞춰진다(행 항등식 깨짐 → 성립). 케어젠 `20200515000560` 잔액은 BS 가 새 값을 지지한다. 행 항등식이 나빠지는 3셀
(시지메드텍 `20160530000228`, NH농우바이오 `20200814001813`)은 원문 소계 행 전체가 괄호를 잃은 표에서 해당 열만 구성요소 합에 맞춘 것이다.
★측정 교훈: 두 드라이런 사이에 재적재가 끼면 "DB 대비 차이" 끼리의 비교가 가짜 차이를 만든다(에이루트 배당 +/− 착시).
기준선과 후보는 **같은 DB 상태**에서 돌린다.

**회귀 테스트**: `fin2/tests/test_sce_mirror_guard_r190.py` R190-c 2건(중첩 소계 증명 + 앵커 해법, 중첩 소계 부호).

**재적재**: fix batch #40. 미래에셋생명 2필링 + 전사 소급 51필링. 소급 대상은 2015+ 드라이런(df6a411) 결과를 기준선 `9d88f2f` 와 비교해 찾았다:
R190-c 효과 54필링 135셀. 둘 다 재적재 후 차이 0. 제외 3(`docs/qa/r190c_backfill_excluded_2026-09-27.txt`, DB 값이 정답):
- 대화제약 `20221114000343`·화승엔터프라이즈 `20210319000901`: 기준선이 **우연히** 맞춘 잔액이다(R185 확장 / 이중 합산 소계에 기댄 R189).
  새 코드에서는 그 우연이 사라진다. BS 날짜 앵커가 부호를 증명하는데도, 블록이 닫히지 않거나 변동 없이 인쇄 그대로 닫혀 있어 고치지 못한다.
- 대화제약 `20201116000664`: 원문 구성요소의 가짜 괄호(IS 기타포괄 +541,645,353)를 소계 부호가 따라갔다.
- ★다음 과제: 잔액 셀의 BS 날짜 앵커가 인쇄 부호와 반대일 때 블록이 닫히지 않아도 적용할지(원칙 변경, 사용자 판단).

## R190-d. SCE 잔액 셀의 **BS 날짜 부호 우선** — 블록이 닫히지 않아도 적용 (2026-09-27, 사용자 결정 "측정 후 적용", fix batch #41)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 잔액 행 셀의 절대값이 그 날짜 BS 의 같은 개념 잔액(R187 날짜 앵커)과 같고 앵커가 반대 부호만 가지면, 블록이 닫히지 않아도 BS 부호로 바꾼다. 앵커 채택 조건은 R187 과 같고(그 날짜 BS 자본총계 = SCE 합계), 변동 행은 건드리지 않는다. 체인 맨 끝(R189 뒤)에서 적용한다.
> **판정 예** 화승엔터프라이즈 `20210319000901` 2018.01.01 기타자본구성요소 −14,306,637,624(BS 2017-12-31, 같은 열 별개 결함으로 블록 미닫힘) → BS 부호. 미래에셋생명 `20240320002014` 2021·2023 자본조정, 대화제약 `20221114000343` 2021 자기주식(변동 없이 인쇄 그대로 닫힌 블록) → 대상.
> **하지 않는 것** 셀의 블록이 닫혀 있고 그 셀의 열을 포함한 행 항등식이 하나 이상 있으며 모두 성립하면 적용하지 않는다(비엘팜텍 `20260515000210`, 인지컨트롤스 `20180515001307`). 행 항등식이 없거나 다른 열만의 항등식이면 증명으로 치지 않는다. 보강 ① '결손금' 열(이익잉여금 결합 라벨 제외)은 BS 앵커가 양수일 때 쓰지 않는다(R215 로 좁힘, 음수 앵커는 쓴다). ② 블록을 판정할 수 없어도(잔차 None) 셀의 열을 포함한 행 항등식이 인쇄 그대로 성립하면 적용하지 않는다. ③ 뒤집으면 열 잔차와 행 항등식 오차가 둘 다 커지면 적용하지 않는다(상아프론테크 `20260515001959`, 코스나인 `20240514000995`, 케스피온 `20160816000082`). 롤포워드 폐쇄는 거울해에도 성립하므로 증거가 아니다.
> **코드** `sce_sign_repair.apply_dated_balance_signs` · 테스트 `fin2/tests/test_sce_mirror_guard_r190.py`
> **코드 확인** (2026-10-12) 제외 조건은 정규식이 아니라 열 개념 문자열: `'결손금' in concept and '잉여금' not in concept and value < 0` 이면 건너뛴다(`sce_sign_repair.py::apply_dated_balance_signs`). '이익잉여금(결손금)' 같은 결합 라벨은 '잉여금'이 있어 제외되지 않는다.

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**배경**: R162 계열은 BS 앵커가 있어도 블록 롤포워드가 정확히 닫혀야 부호를 고친다. 그래서 두 경우를 못 고쳤다.
① 같은 열에 별개 결함이 있어 블록이 닫히지 않는 경우(화승엔터프라이즈 `20210319000901` 2018.01.01 기타자본구성요소 −14,306,637,624, BS 2017-12-31).
② 변동 없이 인쇄 그대로 "닫힌" 블록(미래에셋생명 `20240320002014` 2021·2023 자본조정, 대화제약 `20221114000343` 2021 자기주식).
이전 코드가 이런 곳을 우연히 맞춘 경우가 있었는데, R190-c 가 그 우연을 없애 R190-c 소급에서 제외가 생겼다.

**수정** (`sce_sign_repair.apply_dated_balance_signs`, 체인 맨 끝 = R189 뒤): SCE **잔액 행** 셀의 절대값이 그 날짜 BS 의
같은 개념 잔액(R187 날짜 앵커)과 같고, 앵커가 반대 부호만 가지면 BS 부호로 바꾼다. 앵커 채택 조건은 R187 과 같다
(그 날짜 BS 자본총계 = SCE 합계). 변동 행은 건드리지 않는다.
- **가드 — SCE 안의 이중 증명은 BS 가 이기지 못한다**: 셀의 블록이 닫혀 있고 **그 셀의 열을 포함한** 행 항등식이
  하나 이상 있으며 모두 성립하면 적용하지 않는다. BS 도 틀릴 수 있기 때문이다(비엘팜텍 `20260515000210`: DB 연결 BS 자본금
  −13,341,512,500, 별도는 +. 인지컨트롤스 `20180515001307`: SCE 기타포괄은 괄호가 명시된 음수이고 블록·행이 모두 닫히는데 BS 는 +).
  행 항등식이 없거나(그룹 합계 열이 없는 표) 다른 열만의 항등식이면 증명으로 치지 않는다. 닫힌 블록의 거울해도 닫히기 때문이다.
- 가드 없이 측정하면 1만 표본에서 6셀이 악화했다(자본금 음수화 등). 가드 후 0셀.
- **가드 보강**(전사 소급 판정에서 추가, 2026-09-28 00시):
  ① '결손금' 열(이익잉여금 결합 라벨 제외)은 쓰지 않는다. BS 가 결손을 양수 금액으로 표시한다(롤링스톤 `20190329004131`, 온코크로스). → **R215 로 좁힘**: 이제는 BS 앵커가 양수일 때만 제외하고, 음수 앵커(결손=음의 자본)는 쓴다.
  ② 블록을 판정할 수 없어도(잔차 None) 셀의 열을 포함한 행 항등식이 인쇄 그대로 성립하면 적용하지 않는다
     (인지컨트롤스 2018.01.01, 수산인더스트리, 코스모화학: 원문에 괄호가 명시돼 있음).
  ③ 뒤집으면 열 잔차와 행 항등식 오차가 **둘 다** 커지면 적용하지 않는다. BS 값이 의심스럽다는 뜻이다
     (상아프론테크 `20260515001959`, 코스나인 `20240514000995`, 케스피온 `20160816000082`).
- 전사(2015+ 104,133필링) R190-d 효과: 보강 전 539필링 1,129셀 → 보강 후 498필링 1,050셀.

**측정** (같은 DB 상태, HEAD 대비 2015+ 무작위 1만): 46필링 87셀(양→음 69, 음→양 18). 행 항등식이 새로 깨지는 셀 0.
음→양 18셀은 대부분 자본금·이익잉여금·자본잉여금이 음수로 들어가 있던 오류를 바로잡는다(서호전기·더블유에스아이·링크드·영풍 자본금,
종근당 이익잉여금 등). 인쇄 상태로 닫혀 있던 블록을 깨는 셀(잔액만 BS 로 바뀌고 변동은 그대로)은 블록 전체 괄호 누락이다.
롤포워드 폐쇄는 거울해에도 성립하므로 증거가 아니다.

**회귀 테스트**: `fin2/tests/test_sce_mirror_guard_r190.py` R190-d 4건(블록 미닫힘에도 적용, 자본총계 불일치면 무증거,
변동 행 불변, SCE 이중 증명 셀은 BS 가 뒤집지 않음).

## R191. SCE **선행 소계**(구성요소 위에 먼저 찍힌 소계)의 인쇄 부호 유지 (2026-09-28, fix batch #45)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 소계 행 바로 **다음 행부터 다음 소계 라벨 행 직전까지**의 합이 그 소계의 (현재 배정) 값과 **부호까지** 같으면 그 행을 선행 소계로 보고 인쇄 부호를 유지한다. 앞 구간 합으로 부호를 바꾸지 않는다. 소계 판정(Σ변동에서 빼는 것)은 그대로다.
> **판정 예** BNK금융지주 `20260515002476` 연결 비지배지분 열 `총포괄손익` 두 칸(+5,255,684,930, +5,304,999,998) → 양수 유지(이전 코드는 위쪽 `신종자본증권배당` −5,255,684,930 과 절대값이 우연히 같아 음수로 뒤집었고, 그 결과 행 항등식 지배 111,824,710,115 + 비지배 = 합계 117,080,395,045 를 깼다).
> **하지 않는 것** 위쪽 구간과 절대값이 일치하지 않는 선행 소계는 이 규칙으로 소계 증명이 되지 않는다(Σ변동에 이중 합산) — 이 규칙은 부호만 다루며, 아래 행 합으로의 증명은 R193.
> **코드** `sce_sign_repair._subtotal_fixes` (회귀 테스트 `fin2/tests/test_sce_mirror_guard_r190.py` R191 2건)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: handoff 2 재판정(`docs/qa/handoff2_flip_excluded_review_2026-09-28.md`)에서 BNK금융지주 `20260515002476` 연결 비지배지분 열의
`총포괄손익` 두 칸(+5,255,684,930, +5,304,999,998)을 현재 코드가 음수로 뒤집었다. DB(이전 적재값)와 IS '비지배지분에 귀속되는 총포괄손익'은 양수다.
**원인** — 이 표는 `총포괄손익` 을 **구성요소 위에** 먼저 찍는다(`총포괄손익` → `당기순이익(손실)` … `총기타포괄손익`).
`_proven_subtotals`(R162-c)는 소계를 **앞선 구간의 합**으로만 증명한다. 그런데 비지배지분(신종자본증권)은 순이익이 곧 배당이라
위쪽 `신종자본증권배당` −5,255,684,930 과 절대값이 **우연히** 같다. 그래서 뒤쪽 소계로 확정되고, `_subtotal_fixes` 가 부호를 위쪽 합(−)에 맞춰 뒤집었다.
뒤집은 결과는 행 항등식(지배 111,824,710,115 + 비지배 = 합계 117,080,395,045)을 깬다.

**수정** (`sce_sign_repair._subtotal_fixes`): 소계 행 바로 **다음 행부터 다음 소계 라벨 행 직전까지**의 합이 소계의 (현재 배정) 값과
**부호까지** 같으면, 그 행은 선행 소계다. 인쇄 부호를 유지하고 앞 구간 합으로 부호를 바꾸지 않는다. 소계 판정(Σ변동에서 빼는 것)은 그대로다.
아래쪽 구간이 부호까지 증명하는 쪽이 위쪽 절대값 일치보다 강한 증거다(R159 2근거 원칙).

**한계**: 위쪽 구간과 절대값이 일치하지 않는 선행 소계는 여전히 소계로 증명되지 않는다(Σ변동에 이중 합산). 이 규칙은 **부호**만 다룬다.
→ **R193** 에서 아래 행의 합으로 증명한다(2026-09-29).

**측정** (2015+ SCE 105,684필링 전수 재추출, `_subtotal_fixes` 출력을 HEAD `79c2f77` 과 호출마다 비교; XML 없음 1,551): **7필링 10셀, 전부 BNK금융지주**
연결 비지배지분 `총포괄손익`. 그중 6필링 8셀은 DB 가 음수(이전 코드의 오판정)로 들어가 있다. 새 값(양수) 가운데 5셀은 같은 보고서 IS
'비지배지분에 귀속되는 총포괄손익' 과 금액·부호가 일치한다. 나머지 3셀은 이번 보고서 IS 에 없는 비교기간 칸이다(구조 동일).
행 항등식이 새로 깨지는 셀 0. 다른 회사는 결과가 바뀌지 않는다.

**회귀 테스트**: `fin2/tests/test_sce_mirror_guard_r190.py` R191 2건(선행 소계 부호 유지, 블록 전체 인쇄 그대로).

## R192. SCE 변동 셀의 **이전 보고서 IS 부호**를 R162 앵커로 사용 (2026-09-28, 사용자 결정 "측정 후 보고", fix batch #46)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 변동 셀 중 R189-b 증거(`_prior_income_signs`: 블록 기간과 정확히 같은 이전 보고서 IS, 같은 basis·절대값·같은 항목 계열)가 한 부호뿐인 셀에 셀 단위 앵커 `("prior_is", id(line))` 를 붙여 R162 에 넘긴다. 가드: 산술 소계 행(바로 위 변동들의 합이나 바로 아래 변동들의 합과 절대값이 같은 행)에는 붙이지 않는다. IS 앵커만으로는 블록 방향을 정하지 않는다(단, IS 가 인쇄 부호와 반대면 허용). IS 앵커만으로 풀린 해는 자본 합계 열 잔액을 음수로 만들 수 없다. `load_prior_income` 은 기간마다 IS 행이 있는 보고서만 고르고, IS 라벨의 영문 로마 숫자('VIII. 기타포괄손익', 'ⅥI.')도 소계 라벨로 인식한다(R189-b 에도 적용).
> **판정 예** DMS `20151113001218` 별도 기타자본구성요소 2013: 원문 420,359,510 / 413,584,791 / 6,774,719, BS 2013-12-31 −6,774,719, 2013 IS 기타포괄 +413,584,791 → 기초 −420,359,510 · 변동 +413,584,791 · 기말 −6,774,719.
> **하지 않는 것** 산술 소계 행에 앵커를 붙이지 않는다(강남제비스코 `20150515001398` '기타포괄손익 계', 코스모화학 `20181005000496` 선행 '총포괄손익'). 재판정 증거로 같은 법인 다른 필링의 DB 부호는 쓰지 않는다(순환). 필링 전체를 `_PRIOR_IS_ANCHOR_EXEMPT`(R197-c)로 면제하지 않는다.
> **코드** `sce_sign_repair.add_prior_income_anchors`, `_required_sign`, `_solve_block`, `load_prior_income`, `_prior_income_signs`, `_INCOME_SUBTOTAL_RE`; `report_lines` 가 `prior_income` 을 R162 에도 넘김
> **코드 확인** (2026-10-12) 코드 목록은 둘: `_AS_PRINTED_CELLS`(`sce_as_printed.py`, 22필링 105키 — R206 첫 등재 103셀 + 2026-10-03 R215(batch #99)가 서울전자통신 `20181114001142` 별도 2017 기초·기말 결손금 잔액 2셀을 더함) 와 `_PRIOR_IS_ANCHOR_EXEMPT`(`sce_sign_repair.py:348`, 4필링: 제닉 20150515001151·신신제약 20191114000854·미창석유공업 20200514000260·20200522000329 — 필링 전체에서 R192 앵커를 끈다). 22필링의 불확실 셀이 아닌 셀에는 R192 가 그대로 적용된다(R206 은 체인 결과가 정확히 R192 값일 때만 그 셀을 인쇄값으로 되돌림). '26필링'은 코드 상수가 아니라 재판정 기록(`docs/qa/r192_excluded_rejudged_2026-09-29.txt`) 계수다.

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: handoff 2 재판정에서 DMS `20151113001218`·CMG제약 `20150331003486`·트리니티항공 `20220816001096` 은 현재 코드가 IS 와 반대로 변동 셀을 뒤집었다.
괄호가 빠진 잔액 열(결손금, 음수 기타자본)에서 **기초 잔액에 날짜 앵커가 없으면**, R162 솔버가 기초 잔액 대신 IS 로 증명되는 변동 셀을 뒤집어 블록을 닫는다.
예) DMS 별도 기타자본구성요소 2013: 원문 420,359,510 / 413,584,791 / 6,774,719, BS 2013-12-31 −6,774,719, 2013 IS 기타포괄 +413,584,791
→ 정답 기초 −420,359,510 · 변동 +413,584,791 · 기말 −6,774,719. 이전 코드는 변동을 −로 뒤집었다(DB 는 잔액 부호가 틀림).

**수정** (`sce_sign_repair.add_prior_income_anchors`, `_required_sign`, `_solve_block`; `report_lines` 가 `prior_income` 을 R162 에도 넘긴다):
1. R189-b 증거(`_prior_income_signs`: 블록 기간과 정확히 같은 이전 보고서 IS, 같은 basis·절대값·같은 항목 계열)가 한 부호뿐인 **변동 셀**을
   셀 단위 앵커 `("prior_is", id(line))` 로 R162 에 넘긴다.
2. **산술 소계 행에는 붙이지 않는다** — 바로 위 변동들의 합이나 바로 아래 변동들의 합과 절대값이 같은 행. 라벨로 소계를 못 알아보는 표에서
   소계에 앵커가 붙으면 구성요소를 뒤집는 가짜 해가 생긴다(강남제비스코 `20150515001398` '기타포괄손익 계', 코스모화학 `20181005000496` 선행 '총포괄손익').
3. **IS 앵커만으로는 블록 방향을 정하지 않는다** — 단, IS 가 인쇄 부호와 반대(괄호 누락의 직접 증거)면 허용한다(CMG제약 2012 결손금 블록:
   인쇄 그대로 닫히지만 IS 는 순손실·보험수리손실이 음수). 태웅 `20150515001603`(행이 어긋난 열에서 음수로 인쇄된 셀의 IS 앵커만으로 풀림)을 막는다.
4. IS 앵커만으로 풀린 해는 **자본 합계 열의 잔액을 음수로 만들 수 없다**(BS 가 필요). 제닉 `20150515001151` 지배 자본 합계 2014 블록.
5. IS 증거 로더 `load_prior_income` 은 기간마다 **IS 행이 있는 보고서**만 고른다(`load_prior_balances` 의 BS 조건과 같다).
   CMG제약 2013 사업보고서가 뒤이은 '[첨부정정]'(IS 없음)에 밀려 2013 기간 증거가 통째로 없었다. R189-b 도 같은 증거를 쓴다.
6. IS 라벨의 **영문 로마 숫자**('VIII. 기타포괄손익', 'ⅥI.')도 소계 라벨로 인식한다(`_INCOME_SUBTOTAL_RE`). R189-b 에도 적용된다.

**측정** (켬/끔 재추출, 2015+ SCE 105,684 + 2015년 이후 접수 FY2014 2,474 = 108,158필링, 같은 DB 상태): **392필링 1,982셀**, 전부 부호 변경.
외부 증거(같은 법인 3년 BS/IS 같은 절대값, 배당=감소 등): 새 값 1,347 · DB 값 5(3필링) · 증거 없음 584(롤포워드/행 항등식 개선 480 · 악화 60 · 판단불가 44).
DB 값이 맞는 5셀은 모두 열 자체가 어긋난 필링이다(제닉 기타포괄 열 BS·IS 로도 닫히지 않음, 신신제약 배당 행에 잔액이 밀려 들어감,
슈프리마는 HEAD 해가 절반만 맞아 R192 가 블록을 손대지 않음).
가드 도입 경위: 가드 없는 1차 측정은 580필링이었고 강남제비스코 9필링·태웅·제닉 자본합계·코스모화학·글로본에서 명백한 악화가 나와 2~4번 가드를 추가했다.
소급: 악화·판단불가 셀이 없는 340필링(`docs/qa/r192_backfill_targets_2026-09-28.txt`), 제외 52(`docs/qa/r192_excluded_2026-09-28.txt`).

**회귀 테스트**: `fin2/tests/test_sce_mirror_guard_r190.py` R192 5건(IS 앵커로 기초 잔액 반전, IS 단독 방향 금지, 영문 로마 숫자, 미증명 소계·선행 소계 앵커 금지).

**R192 제외 52필링 재판정 (2026-09-29, R193 이후, fix batch #51)**: 같은 켬/끔 재추출(`measure_onoff_r192.py`, 현재 HEAD)을 52필링에 다시 돌렸다. 597셀.
- 롤포워드: 개선 367 · 악화 48 · 이전·새 값 모두 닫힘 113 · 둘 다 안 닫힘 66 · 판정 불가 3. 행 항등식: 개선 136 · 악화 58.
- 외부 증거(BS/IS 동일 절대값 + 경제적 자명성): 새 값 356 · DB 값 7 · 증거 없음 234.
- **독립 증거만 근거로 삼는다.** 같은 법인 다른 필링의 DB 부호는 쓰지 않는다 — R192 로 이미 재적재된 340필링의 결과일 수 있어 순환이다.
- 재적재 **15필링**(`docs/qa/r192_rejudge_reload_2026-09-29.txt`): 지금은 DB 값이 맞다는 증거, 내부 악화, 판단불가 셀이 모두 없는 14필링(R193 이후 문제 셀이 사라졌다) + 에스넷.
  엠케이전자 2건은 판단불가 셀이 '자기주식매입'(기타자본 감소, 경제적 자명)뿐이다. 테스는 롤포워드 악화 1셀이 있으나 IS 외부 증거가 새 값을 지지한다(R193 과 같은 원칙).
  에스넷 `20150515002278` 의 OLD_OK 2셀은 우연 일치다: 증거 도구가 잡은 BS '(10)기타유동부채' 749,699,200 은 미지급배당금 잔액이고, 같은 필링의 '(2)배당금지급'과 다른 모든 기간 필링이 −749,699,200 이다(R193 의 "배당·미지급배당금 우연 일치"와 같은 유형).
  재적재 후 DB 값 = 측정한 새 값: 124/124셀(15필링).
- 계속 제외 **26필링**(batch #53 에서 9필링 추가 재적재, 아래 sibling-proof 참고)(`docs/qa/r192_excluded_rejudged_2026-09-29.txt`, 필링별 사유): 재판정에서 R192 결함 후보로 남은 것은 DB 값이 맞다는 증거가 있는 제닉(기타포괄손익누계액 열 어긋남)·신신제약(배당 행에 잔액 밀림)·슈프리마(기타포괄손익-공정가치 2셀),
  그리고 판단불가 셀이 남은 필링(동원금속, 미창석유공업 2 등)이다.
- **아이톡시 `20250325001098`·`20250813000810` 은 R192 결함이 아니다(batch #52 로 재적재, 32/32셀 일치).** '출자전환예정채무의 제거' 를 이전 값(+)이 맞을 것으로 의심했으나 원문 대조로 뒤집혔다.
  ① 원문 2번 열(기타자본 성격) 2024 블록은 41·42·45행이 모두 괄호 없이 양수로 인쇄돼 있다(부호 손실). ② 2번 열 2023 블록은 이전 보고서 IS 앵커 2개(평가이익 +667,777,110, 해외사업환산손익 −8,558,832)로
  `−4,196,087,695 + 25,875,850 + 667,777,110 − 8,558,832 = −3,510,993,567` 이 정확히 닫히고, 2024 블록은 `−3,510,993,567 + 162,312,150 − 263,860,225 − 1,390,554,165 − 4,590,971 = −5,007,686,778` 이 41행 −일 때만 닫힌다.
  ③ 원문 IS 의 기타포괄손익 합계 (1,399,556,067) = −1,390,554,165 − 9,001,902 이므로 IS 의 해외사업환산손익 9,001,902 도 괄호가 빠진 손실이다(2023: 667,777,110 − 16,782,024 = 650,995,086).
  ④ 총계 열에서는 '출자전환 +263,860,225' 과 '출자전환예정채무의 제거 −263,860,225' 가 상쇄돼 순 0 이다(자본 구성요소 사이 이체).
  경로: R192 는 2번 열 2023 블록에 IS 앵커를 붙여 잔액 부호(이월잔액)를 −로 정하고, 그 이월잔액이 2024 블록을 풀어 41행을 −로 만든다. 그 뒤 R162-d 행 항등식이 5·7열의 같은 행 셀을 2번 열에 맞춰 따라 뒤집는다.
  41행 5·7열 자체에는 앵커가 없다. 증거 도구가 '판단불가'였던 것은 5·7열 블록이 다른 이유로 이전·새 값 모두 안 닫혔기 때문이다.
  교훈: **행의 총계 열 셀은 같은 행의 성분 열 블록이 정확히 닫히는지로 증명할 수 있다**(같은 행 절대값이 같은 단일 성분 행).
- **sibling-proof 규칙과 batch #53**: 판단불가(NOEVID·내부 변화 없음) 셀은, **같은 행의 다른 열 셀 중 절대값과 부호가 같고 블록이 정확히 닫히는(켬 `new=0`, 끔 `old=x`) 셀**이 있으면 증명된 것으로 본다.
  같은 행 절대값이 같은 단일 성분 행에서 총계 열이 성분 열을 그대로 따라가기 때문이다. 다른 차단 사유(DB 값이 맞다는 증거, 증거 없는 내부 악화, 형제로 증명 안 되는 판단불가 셀)가 없는 9필링만 재적재했다:
  신원 `20171114001629`·위닉스 `20180402001988`·국보디자인 `20200515001494`/`20210517001094`·새로닉스 `20210322000440`·우신시스템 `20230515001022`·대한전선 `20230515002453`·SKAI `20250321001988`/`20250515002382`
  (`docs/qa/r192_sibling_proof_reload_2026-09-29.txt`). 재적재 후 DB 값 = 측정한 새 값 106/106셀. 한계: 형제가 성분 열이고 미증명 셀이 다른 성분일 때(절대값이 우연히 같음)는 이 규칙이 틀릴 수 있으나 같은 필링에서 확인된 예는 없다.

**R192 제외 22필링 — 사용자 결정 (2026-10-02)**: `docs/qa/manual_check_2026-09-30.md` 2번의 22필링(유니슨 2·EG 5·동원금속 2·위닉스·서울전자통신·다우데이타·차바이오텍·대동·이렘·다산네트웍스 2·오텍·슈프리마·한국경제TV 2·케이지에이·글로본)은
사용자가 DART 원문을 봐도 불확실 셀의 부호를 판정하지 못했다. 결정: **"있는대로 적재" = 이 필링들에 R192 를 적용하지 않고 DB 를 그대로 둔다(재적재 없음).**
- 필링 전체를 `_PRIOR_IS_ANCHOR_EXEMPT`(R197-c)에 넣는 방식은 **채택하지 않았다.** 문서의 대조 대상 셀은 불확실 셀뿐이고 나머지 셀은 BS/IS 증거가 R192 값을 지지한다. 22필링을 면제로 재추출하면 DB 와 0~19셀씩 다르고
  (13필링), 면제를 풀어도 DB 와 다른 필링이 17개다. 면제는 증거가 있는 셀까지 되돌린다.
- 대신 **셀 단위 예외 R206**(아래)으로 불확실 셀 103개만 원문 부호로 고정했다.

## R193. SCE **선행 소계**(구성요소 위에 먼저 찍힌 소계·제목행)를 아래 행의 합으로 증명 (2026-09-29, fix batch #47)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 구성요소 위에 먼저 찍힌 선행 소계를 두 근거를 모두 만족할 때만 인정한다: ① 소계 라벨(`_SUBTOTAL_LABEL_RE`)이거나 `node_role='P'`(다음 행이 더 깊게 들여쓰기된 부모 행), ② 바로 아래 행들을 앞에서부터 누적한 합이 그 값과 인쇄 부호까지 같아지는 첫 지점(거기서 멈춤). 이미 증명된 중첩 제목행은 건너뛰어 그 구성요소를 한 번만 세고, 선행 소계가 아닌 소계 라벨 행을 만나면 멈춘다. 선행 소계가 있는 블록은 항(term) 목록(일반 행, 또는 자기 그룹 전체를 대신하는 증명된 소계)으로 읽고, 뒤쪽 소계 라벨 행은 항 목록 끝부분(suffix) 합과 절대값이 같으면(가장 짧은 것부터) 증명되어 그 끝부분을 대신하며 부호는 그 항들의 합에서 정한다; 선행 소계가 없는 블록은 기존 알고리즘을 쓴다.
> **판정 예** 코스모화학 `20181005000496` 별도 SCE: '총포괄손익' 31,040,544,566 = 당기순이익 30,909,429,018 + '기타포괄손익' 131,115,548, '기타포괄손익' = 166,687,950 + (−35,572,402) → 제목행이 변동으로 이중 합산되지 않는다. 에코프로 `20160829000269` 2015 반기 비교 IS 당기순손실 (727,640,754)·총포괄손실 (885,598,908) = 새 값.
> **하지 않는 것** 절대값 일치나 제목행 표시 하나만으로는 인정하지 않는다(연속된 같은 값 취득·처분 오인). 구성요소가 괄호를 잃어 인쇄 부호로 안 맞으면 종전대로 합산한다(추측 금지). `node_role='F'` 이고 소계 라벨도 아닌 반복 행(한섬 '기타포괄손익'(P) 그룹 뒤 '포괄손익', 성도이엔지 `20250515001100` '총포괄손익'(P) 아래 '기타포괄손익'(F))은 여전히 합산되어 인쇄값으로 남는다. `sce_source_defects._residual_at` 은 `node_role` 을 보지 못해 원문 결함 판정은 라벨 기준 선행 소계만 쓴다(범위 밖).
> **코드** `sce_sign_repair._leading_subtotal_parts`, `_trailing_by_terms`, `_proven_subtotals`, `_subtotal_fixes`, 스위치 `_LEADING_SUBTOTALS`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: R191 한계(인계 문서 2026-09-28 1번). 코스모화학 `20181005000496` 별도 SCE 는 소계를 **구성요소 위에** 먼저 찍는다.
중첩도 있다.

    총포괄손익                 31,040,544,566   ← 당기순이익 + 기타포괄손익
      당기순이익               30,909,429,018
      기타포괄손익                131,115,548   ← 아래 두 행의 합
        - 매도가능금융자산평가이익   166,687,950
        - 부의지분법자본변동        −35,572,402
        - 신주인수권대가          3,789,598,460

`_proven_subtotals`(R162-c)는 소계를 **앞선 구간의 합**으로만 증명한다. 그래서 이런 제목행은 변동으로 이중 합산됐고 블록이 닫히지 않았다.
앵커가 있으면 R162/R162-e 가 이중 합산된 Σ 로 **가짜 해**를 찾았다. 예를 들어 한섬 `20250514000903` '포괄손익', 미원에스씨 `20260515000421`
'자본 증가(감소) 합계', 에코프로 `20160829000269` 는 괄호 누락 셀을 풀지 못했다.

**수정** (`sce_sign_repair._leading_subtotal_parts`, `_trailing_by_terms`, `_proven_subtotals`, `_subtotal_fixes`):
1. **선행 소계 판정 — 두 근거를 모두 요구한다(R159).** ① 소계 라벨(`_SUBTOTAL_LABEL_RE`)이거나 `node_role='P'`(원문에서 다음 행이 더 깊게 들여쓰기된 부모 행)이다.
   ② 바로 아래 행들의 합이 그 값과 **부호까지** 같다. 앞에서부터 누적해 처음 일치하는 지점에서 멈춘다.
   이미 증명된 중첩 제목행은 건너뛰어 그 구성요소를 한 번만 센다. 선행 소계가 아닌 소계 라벨 행을 만나면 멈춘다.
   **인쇄 부호만** 쓴다. 구성요소가 괄호를 잃었으면 일치하지 않으므로 종전대로 합산된다(추측 금지).
   절대값 일치나 제목행 표시 하나만으로는 인정하지 않는다. 같은 값이 연속된 두 변동(취득·처분)이 소계로 오인되기 때문이다.
2. **선행 소계가 있는 블록은 '항(term) 목록'으로 읽는다.** 항은 일반 행이거나, 자기 그룹 전체를 대신하는 증명된 소계다
   (선행 소계는 그 아래 행들을, 뒤쪽 소계는 자기가 닫은 항들을 대신한다). 뒤쪽 소계 라벨 행은 **항 목록의 끝부분(suffix) 합**과
   절대값이 같으면(가장 짧은 것부터) 증명되고, 그 끝부분을 대신한다. 부호는 그 항들의 합에서 정한다.
   기존 `run`/`wide` 는 제목행에서 시작하는 그룹을 따라가지 못한다. 미래에셋생명 `20250318001228` 별도 자본 합계 2023 블록이 그 예다:
   '총포괄손익' = 당기순이익 + '총기타포괄손익'이고, '총기타포괄손익' 그룹은 제목행 '…관련손익 합계'에서 시작한다.
   1차 구현(제목행에서 `run` 을 끊음)은 당기순이익을 떨어뜨려 '자본 증가(감소) 합계'를 음수로 뒤집었다. 전사 측정에서 발견했다.
   선행 소계가 **없는** 블록은 기존 알고리즘을 그대로 쓴다.
3. `_subtotal_fixes`: 선행 소계는 아래 행의 합으로, 뒤쪽 소계는 항 목록의 합으로 부호를 정한다. R191 은 1번의 특수한 경우다.
4. 스위치 `_LEADING_SUBTOTALS`(켬/끔 측정용 모듈 속성).

**한계**:
- 제목행이 아니고(`node_role='F'`) 소계 라벨도 아닌 반복 행은 여전히 합산된다. 예: 한섬 '기타포괄손익'(P) 그룹 뒤에 다시 찍힌 '포괄손익',
  성도이엔지 `20250515001100` '총포괄손익'(P) 아래 '기타포괄손익'(F). 이런 블록은 닫히지 않은 채 인쇄값으로 남는다
  (이전 코드의 가짜 해보다는 낫다).
- 판정기 주의: `sce_source_defects._residual_at` 은 `line=None` 으로 셀을 만들어 `node_role` 을 보지 못한다.
  이 모듈의 원문 결함 판정은 라벨 기준 선행 소계만 쓴다(이번 범위 밖). 켬/끔 판정은 `drift_identity_noderole.py` 로 했다.

**측정**: 켬/끔 재추출(`scripts/sce_onoff_tools_2026-09-27/measure_onoff_r193.py`, 같은 워커·같은 DB 상태). 대상은 2015+ SCE 105,684필링 + 2015년 이후 접수된 FY2014 이전 2,474필링 = 108,158필링이다.
결과: **243필링 806셀**(부호 변경 802, R184 채움 등 4). 판정은 `drift_identity_noderole.py`(롤포워드가 `node_role` 을 봄) + `external_sign_evidence.py` 로 했다.
- 롤포워드: 개선 481 · 악화 13 · 변화 없음 312. 행 항등식: 개선 335 · 악화 14.
- 외부 증거(같은 법인 3년 BS/IS 같은 절대값, 배당=감소 등): 새 값 465(+ 배당·미지급배당금 우연 일치 21 = 새 값) · DB 값 3 · 증거 없음 317.
- 롤포워드 '악화' 13셀은 **이전 코드의 가짜 해가 사라진 것**이다. 이중 합산된 Σ 에서 R162-e 가 셀 하나를 뒤집어 우연히 닫았고, 이제 원문 인쇄값으로 돌아간다
  (한섬 IS 기타포괄 +348,704,293, 다스코 IS 재측정 +46,626,004, 성도이엔지 인쇄 +2,987,386,808).
- 원문 대조: 에코프로 `20160829000269` 2015 반기 비교 IS 당기순손실 (727,640,754)·총포괄손실 (885,598,908) = 새 값(원문 SCE 는 괄호 누락).
  미원에스씨·비상교육·유안타증권·성도이엔지 '자본 증가(감소) 합계'·'기타포괄손익'은 원문이 괄호 없이 인쇄한 양수이고 새 값과 같다. 이전 값은 가짜 반전이었다.
- 1차 구현 측정(`run` 을 제목행에서 끊음)에서 미래에셋생명 9필링의 '자본 증가(감소) 합계' 악화가 나와 2번(항 목록)으로 고쳤다. 고친 뒤 9필링 모두 차이 0이다.
소급: 234필링 749셀(`docs/qa/r193_backfill_targets_2026-09-29.txt`). 제외 9필링 57셀(`docs/qa/r193_excluded_2026-09-29.txt`):
DB 값이 맞다는 외부 증거가 있는 필링(케일럼 `20250515000242` — 원문 이익잉여금 열 기말이 IS 와 불일치)과 행 항등식 악화 셀이 있는 필링
(신세계인터내셔날 2020H1, 에프엔에스테크 2, 신라교역, 호텔신라 2, 펩트론, 흥아해운 — 같은 행의 일부 열만 바뀜).

**회귀 테스트**: `fin2/tests/test_sce_leading_subtotal_r193.py` 7건(코스모 중첩 제목행, 스위치 끔, 비제목 동일값 행, 인쇄 부호 필요,
단일 반전이 닫히는 블록, 미원에스씨 두 제목행 뒤 합계, 미래에셋생명 제목행에서 시작하는 그룹).

## R197. R162-e 교차 열 가드 + 원문 결함 앵커 예외목록 (2026-09-29, fix batch #55)

> **상태** 유효(내부 R197-a 만 측정 후 폐기) · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 (R197-b) R162-e(앵커 없는 블록의 단일 셀 반전)의 반전이 성립하던 행 항등식을 깨고 그 항등식의 총계 열 블록이 인쇄 부호로 이미 정확히 닫혀 있으면 그 반전을 기각한다. 근거로 삼는 열은 항등식의 총계 열뿐이고(이동 없는 형제 성분 열은 근거 아님), 본성상 음수 행(`_NEGATIVE_BY_NATURE_RE`: 배당·자기주식취득, 또는 '자기주식'+'취득' 라벨)은 가드에서 제외한다. (R197-c) 원문이 틀린 것을 확인한 필링만 `_PRIOR_IS_ANCHOR_EXEMPT` 에 등재하고, 등재하면 R162 가 이전 보고서 IS 앵커(R192)를 쓰지 않는다.
> **판정 예** 케일럼 `20250515000242`: R162-e 가 이익 행을 −로 뒤집고 R193·R162-d 가 따라 뒤집던 것 → R197-b 로 이익 행이 +로 돌아가 총계 열·IS 와 맞는다. 예외목록: 제닉 `20150515001151`, 신신제약 `20191114000854`, 미창석유공업 `20200514000260`·`20200522000329`(등재 후 추출값 = DB 값).
> **하지 않는 것** R197-a("앵커 해가 없으면 IS 앵커를 빼고 다시 푼다")는 측정 후 폐기·코드 제거(48셀 중 24셀이 IS 증거와 반대). R198 후보("IS 단독 앵커 해가 무앵커 최소 뒤집기 해보다 많이 뒤집으면 거절")는 일반 가드로 채택하지 않는다. 예외목록은 일반화하지 않는다. 슈프리마 `20240318000679` 는 R192 결함 후보로 남긴다.
> **코드** `sce_sign_repair._breaks_closed_partner_column` · `_R162E_ROW_GUARD`(스위치) · `GUARD_EVENTS`(`_RECORD_GUARD_EVENTS`) · `_PRIOR_IS_ANCHOR_EXEMPT` · 테스트 `fin2/tests/test_sce_r197_guards.py`
> **코드 확인** (2026-10-12) R197-b 가드의 '성립하던 행 항등식'은 허용오차 없이 정확히 같아야 한다(`_row_identities_hold`: `sum(members) != total` 이면 불성립, `_block_residual_at(...) == 0`). R188 의 1,000원 허용오차(`_TOLERANCE_WON`)는 쓰지 않는다.

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: R192·R193 결함 후보 4건 조사(`docs/qa/r192_r193_defect_candidates_2026-09-29.md`).

**R197-b (채택)** — `sce_sign_repair._breaks_closed_partner_column`. R162-e(앵커 없는 블록의 단일 셀 반전)는 열 하나의 롤포워드만 보고 반전을 받는다.
그 반전이 **성립하던 행 항등식을 깨고, 그 항등식의 총계 열 블록이 인쇄 부호로 이미 정확히 닫혀 있으면** 기각한다(R6: 짐작 금지). 케일럼 `20250515000242`: 이익잉여금 잔액이 총계·IS 와 모순인 원문 결함에서
R162-e 가 이익 행을 −로 뒤집고, R193 이 선행 소계 행을, R162-d 가 총계 열을 따라 뒤집었다(R162-d 이중증거가 앞 단계가 만든 음수를 서로의 증거로 셈).
- 근거로 삼는 열은 **항등식의 총계 열뿐**이다. 이동 없는 형제 성분 열은 자명하게 닫히므로 근거가 아니다(제닉스로보틱스 테스트가 잡았다).
- **본성상 음수 행은 제외**: `_NEGATIVE_BY_NATURE_RE`(배당·자기주식취득) 또는 '자기주식'+'취득' 라벨. 첫 측정에서 와이엔텍 `배당금지급`·레드캡투어 `자기주식의 처분(취득)` 두 셀이 가드에 막혀 틀렸다.
- 스위치 `_R162E_ROW_GUARD`, 측정용 `GUARD_EVENTS`(`_RECORD_GUARD_EVENTS`).

**R197-a (측정 후 폐기)** — "앵커 해가 없으면 IS 앵커를 빼고 다시 푼다"(슈프리마 `20240318000679` 대응). 전수 측정에서 18필링 48셀이 바뀌었고 **24셀이 같은 항목의 IS 증거와 반대**였다
(BS 앵커만으로 만든 해가 블록을 닫지만 IS 의 같은 기간·항목 부호와 충돌). 이득은 슈프리마 한 필링뿐이고 그 필링도 해외사업장환산 2행이 IS 와 충돌한다. 코드는 제거했다.
슈프리마는 R192 결함 후보로 남긴다(IS 앵커 대 BS 앵커 충돌, 어느 쪽이 맞는지 원문으로 정해야 함).

**R197-c (원문 결함 예외목록)** — `_PRIOR_IS_ANCHOR_EXEMPT`. R183 목록과 같은 원칙: 원문이 틀린 것을 확인한 필링만 등재하고 일반화하지 않는다. 등재하면 R162 가 이전 보고서 IS 앵커(R192)를 쓰지 않는다 = R192 이전 값.
- 제닉 `20150515001151`: 앞의 두 블록은 실제로 FY2012·FY2013 인데 라벨 날짜가 한 해 늦고 괄호가 빠졌다. FY2014 사업보고서·반기·FY2015 사업보고서는 같은 값을 `(17,035,939)`·`(88,087,827)`·`(99,791,101)` 로 인쇄한다.
  R192 는 라벨 날짜(2014)로 FY2014 IS 를 찾았고 우연히 같은 크기(5,332,665)의 반대 부호를 앵커로 잡았다.
- 신신제약 `20191114000854`: 표 행 라벨이 어긋나 `배당금지급` 행이 조정 후 기초 잔액(52,245,318,744 = 52,270,977,917 − 25,659,173)이다. 2열은 행 항등식으로 −9,340,500 이 맞다.
- 등재 후 두 필링의 추출값 = DB 값(각각 차이 0). 예외 없이는 23셀·3셀이 달랐다.
- 미창석유공업 `20200514000260`·`20200522000329`(2026-09-30 추가): 별도 2019 비교 블록에서 `확정급여제도의 재측정요소` 39,788,585 와 당기순이익이 괄호 없이 인쇄된 것을 사용자가 DART 원문으로 확인했다.
  블록은 배당 하나만 음수이면 인쇄 그대로 닫힌다. 그런데 2019Q1 IS 는 재측정손익을 (39,788,585) 로 갖고 있어 R192 가 이익잉여금 열 4셀을 전부 뒤집었다(기초 −2,307억, 다음 블록 기초는 +2,430억).
  등재 후 두 필링의 추출값 = DB 값(각각 차이 0, 105셀) — 재적재 불필요.
- **R198 후보 폐기(2026-09-30)**: "IS 단독 앵커 해가 무앵커 최소 뒤집기 해보다 많이 뒤집으면 거절" 가드를 R192 가 손댄 702필링에 켬/끔 측정했다. 75필링 333셀이 바뀌었고 외부 증거는 R192 값 175셀 · 가드 값 0셀 · 증거 없음 158셀이었다
  (아이톡시 등 원문으로 R192 가 맞다고 확인한 필링도 되돌림). 일반 가드로 채택하지 않는다. 미창석유공업은 IS 증거도 R192 를 지지하므로 원문 결함 예외목록으로만 처리한다.

**측정(전수)**: 켬/끔 재추출 107,951필링(2015+ SCE 필링 + 2015년 이후 접수 FY2014), 같은 워커·같은 DB 상태, `scripts/sce_onoff_tools_2026-09-27/measure_onoff_r197.py`.
1차(a+b): 107필링 204셀, 가드 발동 150필링(a 82회·b 102회). R197-a 그룹 48셀 중 OLD_OK 24; R197-b 그룹 156셀 중 개선 145·악화 9(IS 증거가 새 값 지지 5, 경제적 자명 1, 증거 없음 3)·OLD_OK 2(배당·자기주식 → 제외 조항 추가).
최종(b + 본성상 음수 제외, 발동 필링만 재측정): **85필링 152셀**. 롤포워드 개선 90 · 악화 45(설계된 결과 — 반전을 거부해 그 열이 안 닫힘), 행 항등식 개선 117 · 악화 2. 외부 증거 새 값 56 · DB 값 **0** · 증거 없음 96.
소급: 84필링(`docs/qa/r197_backfill_targets_2026-09-29.txt`), 제외 1(인스웨이브 `20240814002777`, 증거 없는 악화 셀 2, `docs/qa/r197_excluded_2026-09-29.txt`).
케일럼은 이 배치로 이익 행이 +로 돌아가 총계 열·IS 와 맞는다(R193 제외 목록에서 해소).

**회귀 테스트**: `fin2/tests/test_sce_r197_guards.py` 9건(R197-b 거부·스위치 끔·파트너 열 미폐쇄·배당/자기주식 제외, R197-c 예외 적용/비적용/증거 존재, 앵커 충돌 블록 고정).

## R185-b. 열 일관성 확장의 행 항등식 조건 완화 (2026-09-27, fix batch #34)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 R185 열 일관성 확장의 행 항등식 조건을 완화한다: 관련 행마다 ① 확장 전에 성립하던 항등식은 확장 후에도 성립하고 ② 완전히 닫히지 않는 행은 오차 합이 엄격히 줄어야 한다. 열의 모든 블록이 닫혀야 한다는 조건과 앵커 조건은 그대로다.
> **판정 예** 모두투어 `20130829001679`/`20130829001868` 연결 자기주식 열: 기초 행 4,200 + 29,881 + 8,081 + 37,022 + 588 = 79,771 ≠ 합계 63,609(자기주식 음수일 때만 성립, 백만원). 2013.06.30 기말 행이 다른 열의 별개 결함(당기순이익 행 지배합계 49,581,008 차이)으로 닫히지 않아 R185 가 못 확장하던 것 → 확장.
> **하지 않는 것** 성립하던 행 항등식을 깨면 확장하지 않는다. 강원랜드·이엔에프·SNT홀딩스는 열에 별개 결함이 있어 전체 반전으로도 블록이 닫히지 않으므로 확장되지 않는다. 열 전체 반전은 롤포워드를 저절로 닫으므로 롤포워드는 확장의 증거가 아니다. 추가 확장 201필링 중 194필링(① DB 부분 뒤집기 집합)은 이번 범위 밖(사용자 결정 B).
> **코드** `_row_identity_residuals` · `_row_not_worse` · 테스트 `fin2/tests/test_r162d_row_identity.py`
> **코드 확인** (2026-10-12) '오차 합' = 확장 대상 셀의 행과 R162-d 가 이미 뒤집은 행(touched_rows)의 모든 행 항등식 |Σ구성원 − 합계| 를 더한 값. 확장 뒤 합이 확장 전보다 엄격히 작아야 하고, 확장 전 0 이던 항등식이 0 이 아니게 되면 바로 거부, 확장 뒤 모두 0 이면 통과(`_row_identity_residuals`·`_row_not_worse`·`_column_consistency_guard`).

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: batch #32 제외 필링 조사. 모두투어 `20130829001679`/`20130829001868` 연결 자기주식 열은 원문이 열 전체를 괄호 없이 인쇄했다
(기초 행 4,200 + 29,881 + 8,081 + 37,022 + 588 = 79,771 ≠ 합계 63,609, 자기주식 음수일 때만 성립, 백만원).
R162-d 는 CF 증거가 있는 '자기주식 취득' 행만 뒤집었다. R185 가 열 전체로 확장하지 못한 이유는 2013.06.30 기말 행 때문이다.
이 행은 다른 열의 별개 결함(당기순이익 행의 지배합계 49,581,008 차이)으로 행 항등식이 어차피 닫히지 않아,
"관련 행의 행 항등식이 모두 성립" 조건에 걸렸다.

**수정** (`_row_identity_residuals`, `_row_not_worse`): 관련 행마다 ① 확장 전에 성립하던 항등식은 확장 후에도 성립하고
② 완전히 닫히지 않는 행은 오차 합이 **엄격히 줄어야** 한다. 열의 모든 블록이 닫혀야 한다는 조건과 앵커 조건은 그대로다.

**주의 — 열 전체 반전은 롤포워드를 저절로 닫는다**: 열의 모든 셀 부호를 뒤집으면 블록은 거울처럼 닫힌다. 그래서 확장의 실질 증거는
행 항등식(행별 오차 감소)이다. 외부 증거로도 검증했다.

**측정** (후보 = ① DB 부분 뒤집기 2,021필링 + ② 잠재 156필링 + batch #32 제외 12필링 = 2,172필링, 주석 포함, 완화/엄격 비교):
- 완화로 추가 확장되는 셀은 541개(201필링)이고 모두 양수를 음수로 바꾼다.
- 확장된 249열의 기초·기말 잔액을 같은 필링 BS 금액과 대조했다. 같은 금액이 BS 에 있는 152열은 **전부 부호가 일치**했고
  불일치는 0열이다. 97열은 BS 에서 같은 금액을 찾지 못했다.
- 201필링 중 194필링은 ① 집합이라 이번 범위 밖이다(사용자 결정 B, 별도 판단). 강원랜드·이엔에프·SNT홀딩스는 열에 별개 결함이
  있어 전체 반전으로도 블록이 닫히지 않으므로 확장되지 않는다(SNT 2011 블록 75.6M 부족).

**재적재**: fix batch #34, 7필링(모두투어 2, 고려아연 4, 엔켐 `20240516001964`; `docs/qa/r185b_reload_targets_2026-09-27.txt`).
7필링의 모든 차이 셀을 두 기준으로 판정했다. 롤포워드는 새 값으로 모두 닫히고(개선 120, 유지 46), 행 항등식은 개선 66,
유지 88, 둘 다 불성립 12, 악화 0이다.

**회귀 테스트**: `fin2/tests/test_r162d_row_identity.py` R185-b 2건(다른 열의 별개 결함이 있어도 확장, 성립하던 행 항등식을 깨면 미확장).

---

## R186. R162-e **자기일관성** — 뒤집은 뒤 소계를 다시 판정해도 블록이 닫혀야 채택 (2026-09-27, fix batch #33)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 R162-e 단일 뒤집기 해를 적용한 뒤 소계를 다시 판정하고, 그 Σ 로도 블록이 정확히 닫힐 때만 채택한다. 뒤집기 전에 증명된 소계는 계속 소계로 두고, 뒤집은 뒤 새로 증명된 소계만 추가한다.
> **판정 예** 고려아연 `20130515000822`·`20130814000828`·`20131114000500`·`20140331002753` 연결 SCE 기타포괄손익누계액 열: 매도가능증권평가이익 43,051,561,400 하나만 뒤집어 45,693.6 → 48,107.4(백만원)로 "닫히는" 거울해를 거부하고 + 유지(43,051,561,400 + 325,846,581 NCI = 43,377,407,981). 비엘팜텍 `20170512006122`/`20180330002704` 해외사업환산차이·웰킵스하이텍 `20221111000638` 확정급여 재측정요소: DB 음수 → +(원문 소계가 + 를 증명).
> **하지 않는 것** R162-f 경로(라벨로 식별한 소계를 일부러 빼는 경로, LG전자 `20250317001029`)에는 적용하지 않는다. "원문대로 성립하던 행 항등식을 깨는 R162-e 뒤집기 금지" 안은 기각됐다(1,233필링 3,272셀 올바른 배당 음수화를 되돌림). 뒤집은 뒤 맞지 않게 된 뒤집기 전 증명 소계(샘표 `20141128001686`)를 다시 합산하지 않는다.
> **코드** `sce_sign_repair._closes_after_flip`, `_solve_single_flip` 기본 경로 끝

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: batch #32 제외 필링 조사. 고려아연 `20130515000822`/`20130814000828`/`20131114000500`/`20140331002753` 연결 SCE
기타포괄손익누계액 열. 원문이 파생상품평가손실·(부의)지분법자본변동·해외사업환산손익 세 셀의 괄호를 빠뜨렸다.
그래서 '기타포괄손익합계'·'총포괄손익합계'(2,413,817,620)가 소계로 증명되지 못하고(R162-c 산술 불일치) 변동으로 이중 합산됐다.
그 상태에서는 매도가능증권평가이익 43,051,561,400 하나만 뒤집으면 45,693.6 → 48,107.4(백만원) 블록이 "닫히는" 거울해가 생기고,
R162-e 가 이를 채택했다. 이 셀은 원문대로 행 항등식이 맞는 정답이다(43,051,561,400 + 325,846,581 NCI = 43,377,407,981).

**수정** (`sce_sign_repair._closes_after_flip`, `_solve_single_flip` 기본 경로 끝): 해를 적용한 뒤 소계를 다시 판정하고, 그 Σ 로도
블록이 정확히 닫혀야 채택한다. 뒤집기 **전에** 증명된 소계는 계속 소계로 둔다(뒤집은 뒤 새로 증명된 소계만 추가).
- 이유: 샘표 `20141128001686` 2014 블록 '자본 증가(감소) 합계' 3,379,965,224 = 2,451,790,724 + 928,174,500 은 회사가 배당 부호를
  빼고 더한 소계다. 올바른 뒤집기 뒤에는 이 소계가 더 이상 맞지 않는다. 이것까지 다시 합산하면 정답 뒤집기를 거부하게 된다.
- R162-f 경로(라벨로 식별한 소계를 일부러 빼는 경로, LG전자 `20250317001029`)에는 적용하지 않는다.

**기각한 안(기록)**: "원문대로 성립하던 행 항등식을 깨는 R162-e 뒤집기 금지"는 1,233필링 3,272셀에서 올바른 배당 음수화를 되돌렸다.
행 전체가 괄호를 잃고 R162-e 가 일부 열만 고친 경우(예: `20150515000153` 배당금지급 지배합계 −1,890,000,000)도 원문대로는
행 항등식이 양수로 맞는다. 그래서 행 항등식만으로는 거울해와 부분 복원을 구분할 수 없다.

**측정** (후보 = DB 에서 행 항등식이 깨졌고 음수 셀 하나를 양수로 돌리면 성립하는 행: 5,628행/3,969필링
`scripts/scan_r186_row_identity_single_cell_2026-09-27.py` + batch #32 제외 12필링, 주석 포함 재추출, R186 켬/끔):
R186 이 바꾸는 셀은 **7필링 10셀뿐**이다.
- 고려아연 4필링 7셀: 매도가능증권평가이익이 +로 유지된다. DB 도 + 라서, 재적재 때 망가지는 것을 막는다.
- 비엘팜텍 `20170512006122`/`20180330002704` 해외사업환산차이, 웰킵스하이텍 `20221111000638` 확정급여 재측정요소: DB 의 음수가 +로
  바로잡힌다. 원문 소계가 + 를 증명한다(−955,775,184 + 181,796,306 = −773,978,878; 116,789,812 − 34,916,597 = 81,873,215).
- 한계: 후보는 DB 상태 기준이다. DB 가 원문대로 +(정답)인데 다음 재적재 때 거울해가 생길 잠재 필링은 전사 재추출 없이는 셀 수 없다.
  R186 은 그런 필링도 재적재 때 막는다.

**재적재**: fix batch #33, 7필링(`docs/qa/r186_reload_targets_2026-09-27.txt`). 이 7필링의 다른 기존 차이도 두 기준으로 판정했다.
명확한 악화 후보는 고려아연 2013H1 '종속기업배당' 비지배지분 1셀뿐이다. 이 셀은 음수가 경제적으로 맞고, 같은 행의 자본합계만
미복원인 부분 개선이다.

**회귀 테스트**: `fin2/tests/test_r162_sce_sign_repair.py` R186 3건(거울해 거부, 소계 없는 단일 뒤집기 유지, 뒤집기 전 증명 소계 유지).

---

## R159-보강. 백만원 선언 표의 **진짜 소수 정밀도** 셀 — R158/R160 콤마-오타 판정으로 못 푸는

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 백만원 선언 표의 진짜 소수 정밀도 셀(R158/R160 콤마-오타 판정으로 못 푸는 경우)을 반올림한 정수 문자열로 `_SOURCE_TYPO_CELL_FIXES` 에 rcept 예외 등재해, 기존 `apply_source_typo_fixes`/`parse_amount` 경로가 표 배수(×10⁶)로 해석하게 한다. 등재 근거는 R159 와 같은 이중증거다: 같은 열의 다른 기간 칸이 그 정수로 이미 적재돼 있고, 그 분기 자본 변동 세부항목이 전부 0 이라 기말=기초 항등식으로 반올림값이 자기증명될 때.
> **판정 예** 미래에셋증권 `20250515002840` 연결 SCE "2025.03.31 (기말자본)": 자본금 `4,101,960.79` → `4,101,961`(4,101,961,000,000원), 자본잉여금 `2,157,082.249016` → `2,157,082`(2,157,082,000,000원). 같은 열 2024.03.31·2025.01.01 칸이 `4,101,961`·`2,157,082`.
> **하지 않는 것** 이 셀들을 R159 콤마 오타(예 `"50,747,524.119"` → `"50,747,524,119"`)처럼 이어붙이지 않는다. 회사 전용 1회성 예외라 소급 스캔 대상이 아니다.
> **코드** `parser/xml/table_extractor.py::apply_source_typo_fixes`, `_SOURCE_TYPO_CELL_FIXES`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.
경우는 반올림 예외등재 (2026-09-26)

**발견**: fix batch #12 조사 중 미래에셋증권 2025Q1 `20250515002840` 연결 SCE
"2025.03.31 (기말자본)" 행의 자본금·자본잉여금 열이 DB에 없음. 원문 셀은 각각
`4,101,960.79`·`2,157,082.249016`(백만원 선언, ADECIMAL=-6) — `_DOT_GROUPED_RE`엔 걸리지만
같은 행에 이어붙여 맞춰볼 "온전한 정수" 짝이 없어 `_repair_dot_grouped_cells`가 못 풀고,
R160(해결 안 된 마침표 셀은 결측)이 값을 버렸다.

**판단**: 기존 R159 예외목록 항목들(예 "50,747,524.119"→"50,747,524,119")과 **반대 해석**이
필요하다 — 그쪽은 콤마 자리에 마침표가 찍힌 오타(이어붙여야 정답)지만, 이 표는 실제로 소수
정밀도가 있는 값이라 **반올림**이 정답이다. 등재 근거는 R159와 동일한 이중증거 원칙: 같은 열의
2024.03.31·2025.01.01 칸이 각각 정수 `4,101,961`·`2,157,082`로 이미 적재돼 있고, 이 분기 자본의
변동 세부항목이 전부 0이라 기말=기초 항등식으로 반올림값이 자기증명된다.

**수정**: `_SOURCE_TYPO_CELL_FIXES`에 반올림 두 항목 등재(`"4,101,960.79"→"4,101,961"`·
`"2,157,082.249016"→"2,157,082"`) — 콤마-이어붙이기가 아니라 정수 문자열을 직접 넣어 기존
`apply_source_typo_fixes`/`parse_amount` 경로가 표 배수(×10⁶)로 재해석하게 한다.

**검증**: 재추출 결과 두 셀 모두 4,101,961,000,000원·2,157,082,000,000원으로 복원, 이슈
(#84643·#84644)와 일치. `pytest tests/ fin2/tests/` 1,396 passed.

**재적재·백필**: fix batch #12, 표적 rcept 1건. 회사 전용(1회성 rcept 예외목록) 항목이라
별도 소급 스캔 대상 없음 — R157 전수 스캔(2,528개사)에서 이미 "선언단위 있는 표의 소수 셀
0건"으로 결론 났던 전제가 이번 1건으로 갱신됐다는 점만 기록해 둔다(R160 문서의 "실측 0건"
서술은 이 필링 발견 이전 스냅샷).

---

## R159-보강②. **콤마 그룹핑 결손**(자릿수 누락) — dot-typo 계열이 아니어도 같은

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 콤마 그룹핑 결손(그룹이 3자리가 아닌 자릿수 누락)으로 인쇄된 셀을, 정정값이 원문 다른 곳에 그대로 인쇄돼 있을 때만(R159 등재 조건) `_SOURCE_TYPO_CELL_FIXES` 에 (rcept, 원문 셀) → 정정 셀로 등재해 교정한다. `apply_source_typo_fixes` 는 순수 문자열 치환이라 깨짐 형태(dot-typo 여부)와 무관하게 동작한다.
> **판정 예** 한화투자증권 `20180515001426`(2018Q1) 연결 손익계산서 `I. 영업수익` 제58기1분기 열 원문 `637,930,27,772`(`parse_amount` 는 `63,793,027,772` 로 읽음) → `637,930,827,772`. 근거: 같은 필링 서두 "(2) 요약연결포괄손익계산서"(narrative)에 `637,930,827,772` 정수 인쇄.
> **하지 않는 것** PDF만 제출된 정정신고 `20180515002604` 를 반영하려고 PDF 파서를 새로 배선하지 않는다(원본 필링 원문을 예외목록으로 교정). 회사 전용 1회성 예외목록이라 별도 소급 스캔 대상 없음.
> **코드** `_SOURCE_TYPO_CELL_FIXES` / `apply_source_typo_fixes` (회귀 테스트 `test_source_typo_fix_hanwha_investment_missing_digit`)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.
예외목록으로 교정 (2026-09-26, 검증 이슈 #84907)

**발견**: fix batch #16 조사 중 한화투자증권 2018Q1 `20180515001426` 연결 손익계산서
'I. 영업수익' 제58기1분기 열이 원문에 `637,930,27,772`로 인쇄돼 있다 — "27" 그룹이
3자리가 아니라 2자리인 콤마 그룹핑 결손("8"이 통째로 빠짐). `parse_amount`가 콤마를
지우고 숫자만 이어 붙여 `63,793,027,772`(정답의 1/10)로 읽어 DB에 그대로 적재됐다.

**판단**: 등재 조건(R159와 동일 — 정정값이 원문 다른 곳에 그대로 인쇄돼 있을 때만)을
충족한다: 같은 필링의 사업보고서 서두 "(2) 요약연결포괄손익계산서"(narrative 섹션)에
같은 계정이 `637,930,827,772`로 정수 인쇄돼 있다(이중증거). 회사도 이 오타를 인지해
정정신고(`20180515002604`, [기재정정])를 냈으나 그 정정신고 본문은 **PDF만** 제출돼
(XML/XBRL 없음) `vq.py batch reload`의 통상 재적재 경로(`_reload_rcept`)로는 반영할
수 없다 — 원본 필링(001426)의 원문 자체를 예외목록으로 직접 교정하는 쪽이 근본
해결이다(PDF 파서를 정정신고 1건을 위해 새로 배선하는 쪽은 규모 대비 과함).

**수정**: `_SOURCE_TYPO_CELL_FIXES`에 `("20180515001426", "637,930,27,772") →
"637,930,827,772"` 등재. dot-typo 계열이 아니라 comma-grouping 계열이지만
`apply_source_typo_fixes`는 순수 문자열 치환이라 깨짐의 형태와 무관하게 동작한다.

**검증**: 재추출 결과 637,930,827,772원으로 복원, 이슈(#84907)와 일치.
`pytest tests/ fin2/tests/` 1,404 passed(회귀 테스트
`test_source_typo_fix_hanwha_investment_missing_digit` 추가).

**재적재·백필**: fix batch #16, 표적 rcept 1건(회사 전용 1회성 예외목록이라 별도
소급 스캔 대상 없음).

---

## R159-보강③. **마침표 오타 + 숫자 오타**가 한 칸에 겹친 셀 — 항등식·정수판으로

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 한 칸에 마침표 오타와 숫자 오타가 겹친 셀을, 사람이 원문의 두 근거 — (나) 같은 행 항등식이 정하는 값, (가) 같은 필링 다른 곳에 정수로 인쇄된 값 — 를 확인해 정정값이 추측 없이 확정되면 `_SOURCE_TYPO_CELL_FIXES` 에 등재해 교정한다. 이 패턴은 자동 복원하지 않는다(R6).
> **판정 예** 삼성E&A `20240313000522`(2023FY, + 기재정정 `20240314001768`, 표 byte-identical) 별도 SCE 2023 `당기순이익(손실)` 이익잉여금 칸 `633,492,278.632` → `633,492,277,632`. 근거: 자본금 `0` + X + 기타자본구성요소 `0` = 자본 합계 `633,492,277,632`, 별도 손익계산서 당기순이익 `633,492,277,632`(정수 5회 인쇄). 두 rcept 모두 등재.
> **하지 않는 것** 자동 복원하지 않는다. 소급 스캔(`decimal_cell_scan.jsonl` 발화 233필링, 미해결 마침표 셀 169개, "행 항등식 값과 셀 숫자열이 정확히 1자리만 다른" 패턴)은 이 2필링뿐이라 추가 백필 없음. R158(숫자열이 같아야 짝)·`report_dot_typo_candidates.py` 근거 (나)(dot→comma 가설값만)가 못 풀어 R160 이 숫자로 읽지 않은 것 — 계층2 는 값 NULL 행은 올바른 동작이며 파서 결함이 아니다.
> **코드** `_SOURCE_TYPO_CELL_FIXES` (회귀 테스트 `test_source_typo_fix_samsung_ena_dot_plus_digit_typo`)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.
확정되면 같은 예외목록으로 교정 (2026-09-26, 검증 이슈 #18060/#18208)

**발견**: value_mismatch 배치. 삼성E&A 2023FY `20240313000522`(+ 기재정정
`20240314001768`, 표 byte-identical) 별도 SCE 2023 '당기순이익(손실)' 이익잉여금 칸 원문이
`633,492,278.632` 다. 정답 `633,492,277,632` 와 비교하면 콤마가 마침표로 찍혔고 **숫자 하나**
(7→8)도 다르다. 이슈 등록 당시 DB 는 633,492,278(10³ 배 축소)이었다. 이후 R160 재적재로
**결측**이 됐고, 그래서 검증 측 recheck 가 reopen 했다.

**왜 기존 규칙이 못 풀었나**: R158(같은 행 정수 짝)은 숫자열이 같아야 짝으로 인정한다.
여기선 278≠277 이라 짝이 없다. `report_dot_typo_candidates.py` 의 근거 (나)도
dot→comma 가설값(633,492,278,632)만 넣어 보므로 항등식이 닫히지 않았다. 그래서 R160 이
정책대로 결측으로 남겼다. 이는 올바른 동작이며 파서 결함이 아니다.

**판단**: 등재 조건(R159)을 충족한다. 정정값이 원문 인쇄값으로 추측 없이 확정된다.
- (나) 같은 행 항등식: 자본금 `0` + **X** + 기타자본구성요소 `0` = 자본 합계
  `633,492,277,632`(원문 인쇄), 따라서 X = 633,492,277,632.
- (가) 같은 필링 별도 손익계산서 당기순이익 `633,492,277,632`(원문에 정수 5회 인쇄).

**수정**: `_SOURCE_TYPO_CELL_FIXES` 에 두 rcept 모두 등재
(`"633,492,278.632"` → `"633,492,277,632"`). 회귀 테스트
`test_source_typo_fix_samsung_ena_dot_plus_digit_typo`.

**소급 스캔**: `decimal_cell_scan.jsonl` 발화 필링 233건, 미해결 마침표 셀 169개를 대상으로
"행 항등식이 정하는 값과 셀 숫자열이 정확히 1자리만 다른" 패턴을 찾았다. 결과는 이 2필링뿐
이라 추가 백필 대상은 없다. ★이 패턴은 **자동 복원하지 않는다**. 숫자 오타는 사람이 원문의
두 근거를 확인한 뒤 예외목록에 넣는다(R6).

---

## R159-보강④. 합계 항등식이 확정하는 **'.5' 꼴 마침표 셀** — 롯데에너지머티리얼즈 (2026-10-01, 검증 이슈 #86151)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 '.5' 꼴 마침표 셀의 값이 같은 행 항등식으로 확정되고 그 값이 셀 숫자열과 일치하며 원문에서 그 셀 텍스트가 한 곳뿐일 때, 사람이 근거를 확인한 뒤 `_SOURCE_TYPO_CELL_FIXES` 에 (rcept, 셀 원문 텍스트) → 교정값으로 등재해 복원한다. 같은 패턴의 자동 복원은 하지 않는다.
> **판정 예** 롯데에너지머티리얼즈 2025FY `20260310002974` 별도 SCE 2025 '유상증자' 행 `[3,127,314,000, 171,554,527.5, 0, 0, 174,681,841,500]`: 3,127,314,000 + X + 0 + 0 = 174,681,841,500 → X = 171,554,527,500, 숫자열 1715545275 일치, `171,554,527.5` 검색 1건 → `("20260310002974", "171,554,527.5"): "171,554,527,500"` 등재.
> **하지 않는 것** 같은 패턴의 자동 소급 복원은 하지 않는다(R159/R160). R158 은 같은 행에 숫자열이 같은 정수가 있어야 복원하므로 이 셀에는 해당하지 않고, R160 은 정책대로 숫자로 읽지 않았다(2026-10-12 부터 값 NULL + `value_raw` 행). 재적재는 이 1필링만.
> **코드** `_SOURCE_TYPO_CELL_FIXES` · 테스트 `test_source_typo_fix_lotte_energy_materials_dot_five`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: missing_row 큐. 롯데에너지머티리얼즈 2025FY `20260310002974` 별도 SCE 2025 '유상증자' 행은
`[3,127,314,000, 171,554,527.5, 0, 0, 174,681,841,500]` 이고 기타불입자본 칸의 `,500` 이 `.5` 로 찍혔다(핸즈코퍼레이션 `10,937,873.5` 와 같은 모양).
R158 은 같은 행에 숫자열이 같은 정수가 있어야 복원한다(여기선 없음). R160 이 정책대로 결측으로 남겼고, 그래서 검증 측이 missing_row 로 등록했다(파서 결함 아님).
`docs/qa/dot_typo_needs_dart_2026-09-23.md` 의 "DART 확인 요청" 목록에 올라 있던 건이다(같은 행 항등식이 자동 근거로 붙지 않았다).

**판단**: R159 등재 조건 충족. 같은 행 항등식 자본금 3,127,314,000 + X + 0 + 0 = 자본 합계 174,681,841,500 → X = 171,554,527,500 이고
셀 숫자열(1715545275)과 일치한다. 원문에서 이 셀 텍스트는 한 곳뿐이다(`171,554,527.5` 검색 1건).
**수정**: `_SOURCE_TYPO_CELL_FIXES` 에 `("20260310002974", "171,554,527.5"): "171,554,527,500"` 등재.
**회귀 테스트**: `test_source_typo_fix_lotte_energy_materials_dot_five`.
**소급**: 같은 패턴의 자동 복원은 하지 않는다(R159/R160: 사람이 근거를 확인한 뒤 등재). 재적재는 이 1필링.

---

## R162-f. 원문 **소계행이 틀려** R162-c 산술증명이 실패하면, 라벨로 식별한 소계행을 빼고 R162-e(단일셀 반전)를 다시 시도한다 (2026-09-25)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 원문 소계행이 틀려 R162-c 산술증명이 실패하고 R162-e 표준 모형에서 반전 후보가 0개일 때만, `_SUBTOTAL_LABEL_RE`(합계·소계·총계·총포괄…)에 걸리는 변동행을 빼고 R162-e(단일셀 반전)를 다시 센다. 명시적 기초·기말이 정확히 닫히고 반전 후보가 정확히 하나여야 하며, 음수 셀은 후보가 아니고 앵커가 양수라 하면 거부한다. 라벨 소계의 부호는 건드리지 않는다.
> **판정 예** LG전자 2024FY `20250317001029` 연결 SCE '배당'(153,915 / 126,905 / 234,945 …, 원문 괄호 없음): 블록 끝 '자본 증가(감소) 합계' 2,389,964 가 실제 변동 2,393,964 와 4,000(사업결합) 어긋나 R162-c 가 소계로 증명 못 함 → 소계행을 빼고 단일 반전으로 배당 3개년 음수.
> **하지 않는 것** R162-e 반전 후보가 이미 있으면 이 규칙을 쓰지 않는다. 라벨 소계의 부호는 바꾸지 않는다. 구성요소 열 합 = 합계 열·BS 대조를 근거로 한 건(SKC·삼성E&A·두산 등)은 R162-d 영역이다. DB 행에 수리 루틴을 다시 돌리는 스캔은 멱등이 아니므로 규모는 재추출 전후 비교로만 잰다.
> **코드** `sce_sign_repair._solve_single_flip` · 테스트 `fin2/tests/test_xbrl_base_presentation_merge.py::test_r162f_…`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: sign_flip 220건(원문 음수표기 없음) 조사. LG전자 2024FY `20250317001029` 연결 SCE '배당'(153,915 / 126,905 / 234,945 …)은
원문에 괄호가 없다. 그래도 R162-e 가 못 풀었다. 블록 끝 '자본 증가(감소) 합계' 2,389,964 가 실제 변동(기말−기초) 2,393,964 와
4,000(사업결합) 어긋나 R162-c 가 이 행을 소계로 증명하지 못했다. 그래서 Σ변동에 이중으로 들어가 **어떤 단일 반전으로도 닫히지 않았다.**

**규칙** (`sce_sign_repair._solve_single_flip`): R162-e 표준 모형에서 반전 후보가 **0개**일 때만, `_SUBTOTAL_LABEL_RE`(합계·소계·총계·
총포괄…)에 걸리는 변동행을 빼고 다시 센다. 명시적 기초·기말이 정확히 닫히고 반전 후보가 **정확히 하나**여야 한다(음수 셀은 후보 아님,
앵커가 양수라 하면 거부 — R162-e 와 같은 안전장치). 라벨 소계의 부호는 건드리지 않는다.

**측정(2015+ SCE 보유 XML 전수 DB 스캔 → 후보 1,084필링 수정 전후 재추출)**: 바뀐 셀 4,165 — **전부 순수 부호반전**
(배당금지급 1,465 · 연차배당 458 · 자본의 변동>배당금지급 357 · 현금배당 202 · 기타포괄손익-공정가치 53 · 자기주식 취득 45 · 재측정요소 41 …).
★DB 행에 수리 루틴을 다시 돌리는 스캔은 적재 시점 행 집합과 달라 멱등이 아니다(오늘 재적재한 필링에서도 '고칠 셀'이 나옴).
그래서 규모는 반드시 **재추출 전후 비교**로만 잰다.
sign_flip 220건 중 이 규칙으로 해소 43 + 이미 해소 4. **나머지 대부분(SKC·삼성E&A·두산 등)은 행 내부 항등식(구성요소 열 합 = 합계 열)과
BS 대조를 근거로 한 것**이다. 이는 R162-d 의 영역이고, R162-d 는 사용자 결정(2026-09-22)으로 백필 보류 중이다.

**테스트**: `fin2/tests/test_xbrl_base_presentation_merge.py::test_r162f_…`(LG전자 배당 3개년 음수).

**재적재·결과(fix batch #8, 커밋 715a4e1)**: 1,085필링 done / failed 0. 이슈 47건 DB 원문부호 일치 47/47 → fixed 47. std_v3 355개사 해당 기간 재빌드: 핵심컬럼 무변화, orphan 0, D&A/EBITDA 842 채움(재적재된 주석 반영).

## R162-d. SCE 행 내부 **열 항등식**(구성요소 합 = 그룹 합계)으로 빠진 음수 괄호를 복원 — **이중증거 셀만 적용** (사용자 결정 2026-09-25, 최종 설계 확정)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE 한 행에서 `col_label` 그룹마다 '합계'(정규식 `합\s*계|총\s*계`) 열이 정확히 하나면 Σ(형제 열) = 그 합계 열(중첩은 재귀, 최상위는 지배기업 소유주 귀속 자본 합계 + 비지배지분 = 자본 합계)이라는 열 항등식으로 빠진 음수 괄호를 복원한다. 한 행의 깨진 항등식을 모두 닫는 양수 셀의 최소 부분집합이 유일해야 하고(≤3, 원래 성립하던 항등식은 깨지 않음), 뒤집는 셀 모두가 이 필링 안 다른 곳(BS/IS/CF 본문·다른 SCE 행·주석)에 같은 금액 음수로 있어야 한다(이중증거) — 그 "다른 곳"이 지금 푸는 항등식 자체의 구성원(같은 행 총계·형제 칸)이면 증거가 아니고, 다른 항등식(중첩 안쪽 합계 등)의 구성원이면 같은 행이라도 유효하다. 교차-basis SCE 증거·반대-basis BS/IS/CF 증거·주석뿐인 증거는 자본거래/이월잔액 행(`_CAPITAL_TRANSACTION_RE` + `_is_balance_label`)에만 인정하고, 같은-basis BS/IS/CF 앵커·같은-basis 다른 SCE 행 증거는 이 제한이 없다.
> **판정 예** 제이씨현시스템 `20210517000597` 배당금지급(자본거래) → 음수 복원, 원문 대조 참. 이니텍 `20171114002176` 확정급여채무의재측정요소(손익결과) → 같은 basis 별도 IS '확정급여제도의 재측정손익'(col_index=1) 음수 인쇄가 같은-basis 앵커가 되어 복원, 참.
> **하지 않는 것** 음수로 파싱된 셀은 후보가 아니다(R6). 손익결과 항목(당기순이익·기타포괄손익 재측정·지분법·처분손익 등)은 교차-basis SCE 증거만으로 뒤집지 않는다. 2칸짜리 단일 항등식(구성요소·합계 둘뿐)은 순환참조라 행 밖 독립 증거가 없으면 손대지 않는다(코아스템켐온 `20170515004679` 당기순이익(손실)).
> **코드** `fin2/extract/sce_sign_repair.py::repair_sce_row_identity()` (`fin2/extract/report_lines.py::extract_report_lines()` 안, R162·R162-manual 다음, R163 이전)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**배경**: 2026-09-22 최초 연구(3,903셀/2,398필링)를 사용자가 백필 보류시켰다 —
"같은 금액이 다른 곳에 음수" 증거가 작은/둥근 금액의 우연일치로 너무 느슨할 수
있다는 우려였다. 2026-09-25 밤 재추정에서 후보가 8,753필링(증거 무시)으로 급증해
(이전 연구의 4.5배) `docs/qa/r162d_row_identity_handoff_2026-09-25.md` 로 표본
원문대조 전까지 WIP 코드를 커밋하지 않고 보류했다.

**규칙**:
1. `col_label` 계층에서 그룹마다 '합계'(정규식 `합\s*계|총\s*계`) 열이 정확히 하나면
   Σ(형제 열) = 그 합계 열이다(중첩도 재귀 — 형제가 그 자신의 그룹이면 그 그룹의
   합계 열로 대신 들어간다). 최상위도 같다: 지배기업 소유주 귀속 자본 합계 +
   비지배지분 = 자본 합계.
2. 한 행에서 깨진 항등식을 모두 닫는 **양수 셀의 최소 부분집합이 유일**해야
   한다(≤3, 원래 성립하던 항등식은 깨지 않음). 음수로 파싱된 셀은 후보가 아니다
   (괄호가 명시된 것이므로 추측 대상이 아니다 — R6).
3. **이중증거(사용자 결정)**: 뒤집는 셀 **모두**가 이 필링 안 다른 곳에 같은 금액이
   음수로 있어야 한다 — BS/IS/CF 본문(같은 basis 든 다른 basis 든), 다른 SCE 행,
   또는 주석. ★단, 그 "다른 곳"이 **지금 풀려는 항등식 자체의 구성원**(같은 행의
   총계/형제 칸)이면 증거로 안 친다 — 그건 새 증거가 아니라 항등식을 순환
   재사용하는 것이다. 반대로 **다른** 항등식(중첩계층의 안쪽 합계 등)의 구성원이면
   같은 행이라도 유효한 증거다.
4. **교차-basis(연결↔별도) SCE 증거, 반대-basis BS/IS/CF 증거, 주석뿐인 증거**는
   **자본거래/이월잔액**(자기주식·배당·자본조정·결손금·증자·감자·전환·상환·
   신종자본증권·주식기준보상·기초자본/기말자본 등, `_CAPITAL_TRANSACTION_RE` +
   `_is_balance_label`) 행에만 인정한다. 같은-basis BS/IS/CF 앵커나 같은-basis
   다른 SCE 행 증거는 이 제한이 없다(아래 근거 참조).

**근거(2026-09-25 표본 원문대조, 8건 실측 — `scripts/verify_r162d_live_extraction.py`)**:
자본거래/이월잔액 계열(흥국 `20230814000814` 자본조정, 제이씨현시스템
`20210517000597` 배당금지급, 종근당바이오 `20190814001930` 자기주식, 차AI헬스케어
`20151120000371` 연결범위변동)은 전부 참(true positive)으로 확인됐다 — 이런 항목은
같은 회사의 자본거래가 basis 와 무관하게 같은 사실이라 basis 간 부호가 갈릴 이유가
없다. 반면 이니텍 `20171114002176` 확정급여채무의재측정요소(손익결과 항목)는 처음
SCE 원문표만 보고 "별도·연결이 원문상 다른 부호로 정상 인쇄된 오탐"이라 의심했으나,
**별도 basis 자체의 IS 문**(`확정급여제도의 재측정손익`, col_index=1)에 이미 같은
금액이 음수로 있어(같은-basis 앵커) 사실은 참으로 판명됐다 — 즉 이 표본에서
**확인된 오탐은 0건**이었지만, 손익결과(당기순이익·기타포괄손익 재측정·지분법·
처분손익 등) 항목은 자회사 실적 반영으로 basis 간 부호가 실제로 달라질 수 있는
구조적 여지가 있어 "교차-basis SCE 증거만"으로는 뒤집지 않는 **방어적** 조건을
유지한다(`fin2/tests/test_r162d_row_identity.py::test_oci_remeasurement_cross_basis_only_rejected`,
가상 사례로 그 게이트 자체를 검증). 코아스템켐온 `20170515004679` 당기순이익(손실)
같은 **2칸짜리 단일 항등식**(구성요소·합계 둘뿐)은 서로가 서로의 유일한 후보 증거라
순환참조이므로, 행 밖에 독립 증거가 없으면 손대지 않는다(이중증거 없음 → R6).

**구현**: `fin2/extract/sce_sign_repair.py::repair_sce_row_identity()`.
`fin2/extract/report_lines.py::extract_report_lines()` 안에서 R162(열 롤포워드)·
R162-manual 다음, R163 이전에 돈다 — 별도 call site 배선 불필요(R162-manual 과 같은
이유, `extract_report_lines()` 를 부르는 모든 경로가 자동으로 물린다).
**테스트**: `fin2/tests/test_r162d_row_identity.py`(5건: 자본거래 참·손익결과
교차-basis 기각·중첩계층 같은-basis 증거·2칸 순환기각·주석증거도 같은 게이트).

**측정(DB 근사 스캔)**: `scripts/scan_r162d_dual_evidence_db.py` — DB 행에 다시
돌리는 스캔은 적재 시점 행 집합과 달라 멱등이 아니라 근사치다. 최종 설계로
candidates(증거 무시) 8,753필링/32,121셀, 이중증거+게이트 통과 7,030필링/18,068셀.
표본 원문대조 8건 전부 기대와 일치.

**재적재·결과(batch #9, 커밋 fe70a2a)**: `vq.py batch add-targets`(6,995건, 이슈경유
35건 중복 제외)+이슈 경유 237건 → `vq.py batch reload --sd --shard i/4`(SD 미러
우선, 없으면 NAS 폴백, 4-way 병렬) — **done 7,066 / deferred 0 / failed 0**.
★**실측 재추출 규모(근사 스캔이 아니라 이게 최종값)**: 실제로 셀이 바뀐 필링
**5,645 / 셀 17,646**(근사 스캔의 7,030/18,068 과 차이는 스캔의 비-멱등성 때문 —
위 캐비어트 그대로). 이슈 237건 중 **fixed 194 / not_fixed 43**(재적재는 됐지만
그 이슈가 가리키던 정확한 셀은 안 바뀜 — 다른 원인이거나 이미 R162-e/f 로
해소돼 있었던 것으로 추정, 강제로 fixed 처리하지 않고 열어 둠).

**재적재 방법**: `docs/qa/r162d_row_identity_handoff_2026-09-25.md`(2026-09-22
최초 연구 문서)·`docs/qa/r162d_dual_evidence_candidates_2026-09-25.jsonl`(후보
목록, 로컬 — 9MB 라 커밋하지 않음, 스캔 스크립트로 재생성 가능). 재추출은 SD
(`/Volumes/dart_data/raw_report`, `batch reload --sd`)+NAS 자동폴백 병렬 샤딩으로
돌렸다(NAS 단독은 SMB 병목으로 3.5시간에 13%만 진행됐던 전례, 메모리
`feedback-bulk-read-use-sdcard`) — `fin2/verification/ops.py::_sd_path()`.

## R200. R176 XBRL SCE 부호 정산의 **동률 처리를 결정적으로** — 순회 순서 고정 + 동률은 본성상 음수 행만 (2026-09-30, fix batch #57)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 R176 XBRL SCE 부호 정산(`_settle_sce_signs_by_rollforward`)의 동률을 결정적으로 처리한다(`_R176_TIE_POLICY = "strict"`). (1) 후보를 행 순서(`order_of`)로 정렬해 순회한다(set 을 그대로 돌지 않는다). (2) 최다 수정 후보가 하나면 종전과 같이 뒤집는다. (3) 동률이면 본성상 음수이면서 양수 fact 가 있는 행(라벨이 배당·자기주식 취득이거나 개념명이 Dividend·TreasuryShares 계열, 확장 개념 `udf_CE_*` 는 라벨로 판정)이 이긴다. 이미 모든 fact 가 음수인 배당 행은 우선권이 없다. (4) 그런 행이 없으면 뒤집지 않고 멈춘다.
> **판정 예** 케이피티유 `20180816000025`: `PYTHONHASHSEED` 0~4 와 5~7 이 다른 행을 뒤집던 것을 고정. '배당' −253,000,000 이 +로 뒤집히던 회귀를 "모든 fact 가 음수인 배당 행은 우선권 없음"으로 막음.
> **하지 않는 것** "본성상 음수 행이 이미 음수면 후보에서 제외"는 접었다(동률 처리에만 씀). `first`·`legacy` 는 측정용 스위치로만 남긴다. 배당 행이 셀마다 부호가 섞인 경우(인터로조·일동제약 `배당금지급`)는 이번 범위 밖이다.
> **코드** `_settle_sce_signs_by_rollforward`, `_R176_TIE_POLICY`

**발견**: R199 batch #56 재적재 뒤 재스캔에서 같은 코드인데 DB 와 추출이 다른 필링이 남았다. 원인은 `_settle_sce_signs_by_rollforward` 의 후보 순회 `for loc in {set} - flipped - anchored` 였다.
set 순서가 `PYTHONHASHSEED` 에 따라 달라 **같은 수의 깨진 칸을 고치는 후보들 중 먼저 만난 것**이 다르게 뒤집혔다(케이피티유 `20180816000025`, seed 0~4 와 5~7 이 다른 행을 뒤집음).

**규칙** (`_R176_TIE_POLICY = "strict"`):
1. 후보를 **행 순서(`order_of`)로 정렬**해 순회한다. set 을 그대로 돌지 않는다.
2. 최다 수정 후보가 하나면 종전과 같이 뒤집는다.
3. 동률이면 **본성상 음수이면서 양수 fact 가 있는 행**(라벨이 배당·자기주식 취득이거나 개념명이 Dividend·TreasuryShares 계열. 확장 개념 `udf_CE_*` 는 라벨로 판정)이 이긴다.
   이미 모든 fact 가 음수인 배당 행은 괄호를 잃은 것이 아니라서 우선권을 주지 않는다(케이피티유 '배당' −253,000,000 이 +로 뒤집히던 회귀).
4. 그런 행이 없으면 **뒤집지 않고 멈춘다**(R6: 등식이 어느 행이 괄호를 잃었는지 못 가린다).
`first`(결정적 첫 행)·`legacy`(set 순서) 는 측정용 스위치로만 남긴다.

**측정**(전수 xbrl_zip 1,639, 같은 워커): legacy 대비 결과가 달라지는 필링 12(seed 0)~22, `first` 대 `strict` 차이 필링 9. 외부 증거(BS/IS·배당=감소): 동률을 `first` 로 풀 때 대비 `strict` 가 맞은 셀 41 / 틀린 셀 3
(엠젠솔루션 종업원급여재측정요소 3셀 — IS 는 손실인데 strict 는 동률 미해소로 인쇄 그대로). seed 0·3·6 에서 12필링 산출물 해시가 동일하다.
현재 DB 와 다른 필링 10(`docs/qa/r200_backfill_targets_2026-09-30.txt`), 이 중 외부 증거가 있는 셀은 케이피티유 8셀이 모두 strict 지지, 나머지는 증거 없음.
시도했다가 접은 것: "본성상 음수 행이 이미 음수면 후보에서 제외" — 전사 23필링이 DB 와 달라지고 배당 행이 섞인 부호(일부 셀만 괄호 손실)에서 유효한 수정을 막아 OLD_OK 75 대 NEW_OK 33 이 나왔다. 후보 제외가 아니라 동률 처리에만 쓴다.
한계: 배당 행이 셀마다 부호가 섞여 있으면(인터로조·일동제약 `배당금지급`) 행 단위 뒤집기가 일부 셀을 틀리게 만든다 — 이번 범위 밖(별도 과제).

**batch #57 결과**: 10필링 재적재 done 10 / failed 0. 재적재 뒤 전사 XBRL 1,639필링 재스캔을 `PYTHONHASHSEED` 2·9 로 두 번 돌려 **DB 와 다른 필링 0**(추출이 seed 와 무관, DB 가 그 값). 이 배치는 verification 이슈 없이 진행(대상 목록만).

**회귀 테스트**: `fin2/tests/test_xbrl_sce_settle_determinism.py`(seed 0·5 서브프로세스 산출물 동일, 배당 동률, 자기주식 확장 행, strict ⊆ first).

## R162-d2. R162-d 행 항등식 — **그룹 합계 칸이 공란이고 구성요소가 하나만 인쇄된 행** (2026-09-30, fix batch #61)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 행 항등식에서 그룹 아래 '합계' 칸이 없고 인쇄된 칸이 정확히 하나(더 깊은 하위 열 없음)이면 그 칸을 그룹 합계로 보아 부모 합계 = 이 칸 항등식을 만든다. 이 확장은 R162-d(`repair_sce_row_identity`)와 R189(`repair_sce_sibling_cells`) 두 곳에서만 켠다. R162-d 에서 이 확장이 만든 항등식에 기댄 해법은 뒤집는 셀 자신의 열 롤포워드 잔차가 엄격히 줄 때만 적용하고(같거나 커지거나 블록이 없으면 건너뜀), 이중증거 요건은 그대로다.
> **판정 예** 남해화학 `20220317000080` 연결 SCE 2019 '연차배당'(#86977): 이익잉여금·자본 합계 칸에 같은 금액 무괄호, 지배기업 귀속 합계·비지배지분 칸 공란, 이익잉여금은 R162 가 음수 복원 → 자본 합계 −2,397,434,750 (424,691,069,854 + 16,040,767,746 + 25,142,194 − 4,399,383,571 − 2,397,434,750 = 433,960,161,473).
> **하지 않는 것** 같은 함수를 읽는 다른 가드(R190 G-B(i), R197-b 등)에는 켜지 않는다. 남해화학 2019·2021 '확정급여제도의 재측정요소' 자본 합계(행 3·19)는 본성상 음수 라벨이 아니고 IS 부호 증거·다른 곳 음수 금액이 없어 +로 남는다(#86976 not_fixed). 연차배당 뒤집기 뒤 R162-e 를 한 번 더 도는 방법은 체인 순서 변경이라 별도 측정 전까지 하지 않는다.
> **코드** `sce_sign_repair._R162D_BLANK_GROUP_TOTAL`, `_row_identities(blank_group_total=True)`, `_block_residual`
> **코드 확인** (2026-10-12) 문서와 코드가 같다. 이 절이 더한 잔차 가드(뒤집은 뒤 잔차가 엄격히 줄어야 함)는 R162-d(`repair_sce_row_identity`)에서 해가 이 확장 항등식에 기댈 때만 걸린다(`sce_sign_repair.py:1331-1348`). R189(`repair_sce_sibling_cells`)의 같은 모양 조건(`:1768-1790`)은 R189 자기 규칙 (1)항(커밋 `cfd6303`, 이 절보다 먼저)이라 이 절의 가드가 아니다.

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: 남해화학 `20220317000080` 연결 SCE 2019 '연차배당'·'확정급여제도의 재측정요소'(#86977·#86976). 원문은 이익잉여금 칸과 자본 합계 칸에 같은 금액을 무괄호로 인쇄하고
`지배기업 귀속 합계`·`비지배지분` 칸은 **공란**이다. 이익잉여금은 열 롤포워드(R162)가 음수로 복원했는데 자본 합계는 +로 남았다(자본 합계 롤포워드는
424,691,069,854 + 16,040,767,746 + 25,142,194 − 4,399,383,571 − 2,397,434,750 = 433,960,161,473 로 두 행이 모두 음수여야 닫힌다). 이슈 문구("지배기업 합계 누락")와 달리
누락된 셀은 없다(원문이 공란). 결함은 자본 합계 칸의 부호다.
R162-d(`_row_identities`)는 그룹마다 '합계' 칸이 정확히 하나여야 항등식을 만든다. 공란인 그룹이 있으면 항등식 전체를 버려 이 행은 행 항등식이 없었다.

**규칙** (`sce_sign_repair._R162D_BLANK_GROUP_TOTAL`, `_row_identities(blank_group_total=True)`):
1. 그룹 아래 '합계' 칸이 없고 **인쇄된 칸이 정확히 하나**(더 깊은 하위 열 없음)이면, 그 칸을 그룹 합계로 본다(구성요소 하나의 합 = 그 칸). 부모 합계 = 이 칸이라는 항등식이 생긴다.
2. 이 확장은 **R162-d(`repair_sce_row_identity`)와 R189(`repair_sce_sibling_cells`) 두 곳에서만** 켠다. 같은 함수를 읽는 다른 가드(R190 G-B(i), R197-b 등)는 종전 의미를 유지한다
   (켜 두었을 때 가드 쪽 의미가 바뀌어 악화 셀이 남았다).
3. R162-d 에서 이 확장이 만든 항등식에 기댄 해법은 **뒤집는 셀 자신의 열 롤포워드 잔차가 엄격히 줄 때만** 적용한다(`_block_residual`). 잔차가 같거나 커지거나 블록이 없으면 건너뛴다(R6).
   이중증거(다른 곳의 음수 같은 금액) 요건은 그대로다.

**측정**(켬/끔 같은 워커, `scripts/sce_onoff_tools_2026-09-27/measure_onoff_r162d2.py` + 셀별 잔차 판정): 후보 = DB 에서 3단계 이상 열 경로의 그룹이 1칸·합계 없음인 필링 4,957(2단계 경로 630 필링은 차이 0).
- 가드 없이: 123필링·189셀 변경(pos→neg 187 / neg→pos 2). 잔차 개선 135·닫힘 7·**악화 31**(닫혀 있던 순이익·배당 열이 깨짐)·불변 6·블록 없음 10.
- 잔차 가드 + 두 호출부 한정: **92필링·136셀**(개선 130·닫힘 5·악화 1). 악화 1셀은 `20180402005394` 재측정요소 기타포괄손익누계액 109,769,108 → −109,769,108 로, 같은 금액이 IS 에 음수로 인쇄돼
  있어(외부 증거) 잔차 증가는 그 열의 다른 셀 오류 탓으로 본다. 변경 셀의 대부분은 배당·자기주식(본성상 음수)이다.

**남은 것(미수정)**: 남해화학 2019·2021 '확정급여제도의 재측정요소' 자본 합계(행 3·19)는 여전히 +로 남는다. 본성상 음수 라벨이 아니고 IS 부호 증거·다른 곳의 음수 금액이 없어 R162-d·R189 가 건너뛴다.
연차배당 행이 뒤집힌 뒤 그 열 블록은 단일 양수 셀 하나로 닫히므로 R162-e 를 한 번 더 도는 방법이 후보지만, 체인 순서를 바꾸는 일이라 별도 측정이 필요하다.
그래서 #86976 은 이 배치에서 fixed 가 아니다.

**batch #61 결과(2026-09-30)**: 재적재 92필링 done 92 / failed 0. #86977 fixed(연차배당 자본 합계 −2,397,434,750, 열 롤포워드와 일치), #86976 은 open 으로 반환(not_fixed). 근거 목록: `docs/qa/r162d2_backfill_targets_2026-09-30.txt`.

**회귀 테스트**: `fin2/tests/test_r162d2_blank_group_total.py`. **데일리 배선**: 별도 배선 불필요(`extract_report_lines` 체인 안). **소급**: 92필링(`docs/qa/r162d2_backfill_targets_2026-09-30.txt`)을 `batch add-targets` + `batch reload`.

## R162-e2. R162-d/d2 가 셀을 바꾼 필링은 **부호 복원 체인(R162/R162-e)을 한 번 더** 돈다 (2026-09-30, fix batch #62)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 R162-d/d2 가 셀을 **하나라도** 바꾼 필링에서만 `repair_sce_sign_loss` 를 한 번 더 돈다(같은 풀이기·같은 가드, R162-d 뒤에 호출). 두 번째 패스의 변경 중 ① 원문에 괄호로 인쇄된 음수를 양수로 바꾸는 변경, ② 그 셀 열 블록의 롤포워드 잔차 절대값이 커지는 변경은 되돌린다(refuse).
> **판정 예** 남해화학 `20220317000080` `확정급여제도의 재측정요소`(#86976): R162-d2 가 `연차배당` 자본 합계를 음수로 뒤집은 뒤 재측정요소 자본 합계 +4,399,383,571 → −4,399,383,571(연차배당 −2,397,434,750 과 합쳐 롤포워드 −6,796,818,321 일치).
> **하지 않는 것** R162-d/d2 가 셀을 바꾸지 않은 필링은 다시 돌지 않는다. 같은 금액이 IS 에 양수로 인쇄된 셀(닫히는 11셀)은 IS 매칭이 금액만 보는 약한 증거라 막지 않는다(알려진 한계).
> **코드** `sce_sign_repair.rerun_sign_loss_after_row_identity`, `_R162E_RERUN_AFTER_D` (`report_lines.py` 에서 R162-d 뒤 호출; 회귀 `fin2/tests/test_r162e2_rerun_after_row_identity.py`)

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: 남해화학 `20220317000080` '확정급여제도의 재측정요소'(#86976). R162-d2 가 같은 표의 '연차배당' 자본 합계를 음수로 뒤집은 뒤에도 재측정요소 자본 합계(+4,399,383,571)가 남았다.
열 롤포워드 풀이(R162/R162-e)는 체인 **맨 앞**에서 이미 지나갔고, 그 뒤 R162-d 가 바꾼 셀 때문에 열 블록이 "단일 양수 셀 하나"로 닫히는 상태가 되어도 아무도 다시 풀지 않았다.

**규칙** (`sce_sign_repair.rerun_sign_loss_after_row_identity`, `_R162E_RERUN_AFTER_D`, `report_lines.py` 에서 R162-d 뒤에 호출):
1. R162-d/d2 가 하나라도 셀을 바꾼 필링에서만 `repair_sce_sign_loss` 를 한 번 더 돈다(같은 풀이기·같은 가드).
2. 두 번째 패스의 변경 중 **되돌린다**(refuse): ① 원문에 괄호로 인쇄된 음수를 양수로 바꾸는 변경(복원은 잃어버린 괄호만 되살린다), ② 그 셀 열 블록의 롤포워드 잔차 절대값이 커지는 변경.

**측정**(`scripts/sce_onoff_tools_2026-09-27/measure_r162e_rerun.py` 계측 1회 추출 + `measure_onoff_r162e2.py` 켬/끔 + 셀별 잔차 판정):
후보 = DB 에 저장된 SCE 에서 열 블록 잔차가 어떤 셀의 2배와 같은(단일 셀 뒤집기로 닫히는) 필링 11,178(전체 SCE 필링 153,867 중; 표본 240 에서 변경 필링 4/4 가 후보에 포함).
- 필터 전: 716필링·2,235셀 — 블록을 정확히 닫는 셀 2,137 · 개선 30 · 불변 67(소계 행) · **악화 1** · **음수→양수 7**.
- 필터 후(실제 코드 켬/끔): **613필링·1,796셀** — 닫힘 1,651 · 개선 111 · 불변 34(소계) · 악화 0 · 음수→양수 0. 변경은 전부 양수→음수(배당·자기주식·재측정요소·기타포괄손익 등).
- 남해화학: 재측정요소(행 3·19)·지분법자본변동(행 10) 자본 합계·지배 합계가 닫힌다(#86976 의 셀 포함).
- 알려진 한계: 닫히는 11셀은 같은 금액이 IS 에 양수로 인쇄돼 있다(IS 매칭은 금액만 보는 약한 증거라 막지 않았다).

**회귀 테스트**: `fin2/tests/test_r162e2_rerun_after_row_identity.py`. **데일리 배선**: 별도 배선 불필요(`extract_report_lines` 체인 안).
**소급**: 613필링(`docs/qa/r162e2_backfill_targets_2026-09-30.txt`)을 `batch add-targets` + `batch reload`.

**batch #62 결과(2026-09-30)**: 재적재 613필링 done 613 / failed 0. #86976 fixed(남해화학 재측정요소 자본 합계 −4,399,383,571, 연차배당 −2,397,434,750 과 합쳐 롤포워드 −6,796,818,321 일치), not_fixed 0.

## R206. R192 제외 22필링의 **불확실 셀 103개는 원문 부호 그대로 적재** — 셀 단위 예외 (2026-10-02, 사용자 결정)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 R192 제외 22필링의 불확실 셀을 원문 인쇄 부호로 되돌린다. 목록 `_AS_PRINTED_CELLS` 의 `(rcept, basis, label_raw, col_label, row_order) → (R192 값, 원문 값)` 에서, 부호 복원 체인이 그 셀에 정확히 R192 값을 남겼을 때만 원문 값으로 되돌리고, 다른 값이면 건드리지 않는다. `extract_report_lines` 의 부호 복원 체인 맨 뒤·`verify_row_drops` 앞에서 적용한다. 목록은 103셀이며 R215 가 `20181114001142` 별도 2017 블록 잔액 2셀을 더해 105셀이다.
> **판정 예** 22필링 재추출 시 103셀 전부 원문 값. DB 는 67셀만 원문 값이고 36셀(위닉스 `20171114001661`·서울전자통신 `20181114001142`·이렘 `20191114002009`·슈프리마 `20240318000679`·한국경제TV `20240516000677`/`20240814003810`·케이지에이 `20260814002235`)은 R192 값이라 재적재.
> **하지 않는 것** 필링 전체 면제(`_PRIOR_IS_ANCHOR_EXEMPT`)는 증거가 있는 셀까지 되돌려 채택하지 않았다. 목록에 없는 셀·다른 필링·다른 표는 건드리지 않는다. 열 이름 "지배기업의 소유주에게 귀속"은 DB 열 `…귀속되는 자본(지분) 합계`(합계 열)다.
> **코드** `fin2/extract/sce_as_printed.py`(`_AS_PRINTED_CELLS`)
> **코드 확인** (2026-10-12) 목록은 지금 22필링 105셀이다 — 첫 등재 103셀에 2026-10-03 R215(batch #99, 커밋 `03c9e9a`)가 서울전자통신 `20181114001142` 별도 2017 기초·기말 결손금 잔액 2셀을 더했다(R215 의 새 결손금 앵커로 체인이 잔액을 뒤집게 되어, 사용자가 인쇄 그대로로 정한 블록을 지키려고). 아래 본문의 '103' 은 첫 등재 시점 수다.

**배경**: R192(이전 보고서 IS 앵커)를 적용하지 않고 제외했던 22필링(`docs/qa/manual_check_2026-09-30.md` 2번)에서 일부 셀의 부호를 사용자가 DART 원문을 봐도 판정하지 못했다.
결정: "있는대로 적재" — 불확실 셀만 R192 이전(원문 인쇄) 부호를 유지한다. 나머지 셀은 BS/IS 증거가 R192 값을 지지하므로 체인이 정한 값을 그대로 둔다.

**규칙** (`fin2/extract/sce_as_printed.py`, `extract_report_lines` 의 부호 복원 체인 **맨 뒤**·`verify_row_drops` 앞): 목록 `_AS_PRINTED_CELLS` 의
`(rcept, basis, label_raw, col_label, row_order) → (R192 값, 원문 값)`. 체인이 그 셀에 정확히 R192 값을 남겼을 때만 원문 값으로 되돌린다. 다른 값이면 건드리지 않는다(원문·코드 변경 시 오적용 방지).
- 필링 전체 면제(`_PRIOR_IS_ANCHOR_EXEMPT`)는 증거가 있는 셀까지 되돌려 채택하지 않았다(위 R192 제외 22필링 결정 참고).
- 열 이름 "지배기업의 소유주에게 귀속"은 문서 표기이며 DB 열은 `…귀속되는 자본(지분) 합계` 이다(구성요소 열이 아님 — 같은 값을 갖는 두 열 중 합계 열). 103셀 모두 유일 매칭.
- 목록은 문서 표에서 기계적으로 만들었다(셀 103개 = 문서 표 103행, 매칭 실패 0).

**측정**: 22필링을 재추출하면 103셀 전부 원문 값이다. DB 는 67셀만 원문 값이고 36셀(7필링: 위닉스 `20171114001661`·서울전자통신 `20181114001142`·이렘 `20191114002009`·
슈프리마 `20240318000679`·한국경제TV `20240516000677`/`20240814003810`·케이지에이 `20260814002235`)은 R192 값이라 재적재한다.

**회귀 테스트**: `fin2/tests/test_sce_as_printed_r206.py` 4건(복원·다른 값 불변·타 필링/타 표 불변·표 구조 22필링 103셀 부호쌍).

**추가(2026-10-03, R215 fix batch #99, 커밋 `03c9e9a`)**: 목록에 서울전자통신 `20181114001142` 별도 2017 기초·기말 결손금 잔액 2셀을 더했다 — 22필링 **105셀**(테스트 기대값도 103→105). R215 가 결손금 열에 음수 BS 앵커를 쓰게 되면서 체인이 이 블록 잔액을 뒤집게 됐고, 이 블록 변동 셀은 R206 결정으로 인쇄 그대로이므로 잔액도 인쇄 그대로 두어 결정 당시 상태를 유지한다(R215 절에도 기록). 이 절 위의 '103' 은 첫 등재 시점의 수다(2026-10-12 문서 정합).

## R213. 계층3 EPS 는 **적재기의 EPS 행을 자체 규칙으로 분류**한다 — 일반 매퍼 라벨 공백 (2026-10-03, R212 후속, 사용자 지시)

> **상태** 유효 · **적용 계층** 3

**발견**: R212 재빌드 후 계층2 소수 EPS 3,872셀 중 계층3(`amount_exact`)에 이른 것이 228행뿐이었다.
원인은 계층3 이 EPS 를 일반 매퍼(AccountMapper)로 찾는 데 있다. 매퍼는 `주당` 라벨을 퍼지에서 의도적으로 막고(이월드 원 단위 순이익 오염 가드), 정확 일치 alias 는 `기본주당이익`·`희석주당이익`·`주당순이익` 류만 안다.
2015+ HTML EPS 행(`source_ref 'eps/…'`) 363,756건 중 라벨로 매핑된 것은 12,622건(3.5%)이었다. 매핑되지 않은 라벨 형태는 2,264가지이고, 1위가 `기본주당이익(손실) (단위 : 원)` 96,904건이다.
결과적으로 대부분 기업의 EPS 가 앱(`extended_financials`)에 정수로도 없었다. R212 이전부터 있던 공백이다.

**규칙** (`fin2/layer3/combine.py::_eps_canonicals`, `_map_rows`)
1. `build_merged_lines`·`collect_candidates` 가 `source_ref LIKE 'eps/%'` 를 `eps_row` 로 싣는다. `eps_row` 행은 일반 매퍼를 거치지 않고 EPS 규칙으로만 분류한다.
   적재기가 이미 구조 규칙(R145)과 금액 크기로 EPS 임을 증명한 행이라서 라벨에서 이름만 읽는다.
2. 이름 규칙: `기본`·`희석` 이 둘 다 있으면 → basic+diluted 둘 다(`기본및희석주당이익`, `기본/희석…`). `희석` 만 있으면 → diluted. 그 밖은 → basic(`주당이익`, `기본주당손실` 등).
   `(단위 : 원)` 은 무시한다. 라벨에 `주당` 이 없는 자식행(`(1) 기본주당이익` > `1. 보통주`)은 section_path 로 이름을 읽는다.
3. 헤드라인이 아닌 행은 제외: 라벨에 `계속`·`중단`·`우선주` 가 있는 행. 또는 가장 가까운 조상이 `계속영업`/`중단영업` 중 하나만 이름 짓는 행(`계속영업` > `기본주당손익`).
   `계속영업과 중단영업` 은 합계라서 남긴다.
4. 부호는 원문 인쇄 부호 그대로 둔다. 2015+ 실측에서 저장 EPS 부호는 라벨과 무관하게 지배순이익 부호와 약 99% 일치한다(`손실` 단독 라벨: 같음 1,298+128 / 다름 79+5).
   손실 라벨이라고 뒤집으면 오히려 틀린다. 양수 손실 라벨 79건은 근거가 없어 그대로 둔다(R6).
5. stage `eps` 는 `_STAGE_RANK` 에서 `exact` 와 같은 3 이다.

**측정**(무작위 400 기간 + 사례 4, R213 전(216a4b4) 코드와 R213 코드를 같은 데이터로 계산)
- std_v3 컬럼 차이 0, EPS 외 확장 캐노니컬 차이 0.
- EPS 칸: 있음 53 → 669(808칸 중 6.6% → 83%). 기존 값이 사라지거나 바뀐 칸은 0.
- 기본·희석 쌍 294 중 이익인데 기본<희석 인 것은 1건이다(노루페인트 2022H1 별도 587/589). 원문 인쇄값이 그렇다.
- 남은 빈칸 30기간의 원인: 계속/중단 성분 EPS 만 있고 합계 EPS 가 없음 23(합을 추론하지 않는다), 계층2 EPS 행 없음 6, 흥국화재 2023Q1(본류 경로 행, 보통주/기타보통주 두 값) 1.

**회귀 테스트**: `fin2/tests/test_r213_layer3_eps_mapping.py`(8건). `test_combine_cross_source_amendment_r171.py` 픽스처에 `eps_row` 를 추가했다.

**데일리 배선**: 계층3 내부 변경이라 추가 배선이 필요 없다(신규 빌드부터 적용된다).
**소급**: 계층3 전사 재빌드(`build_std_v3.py --all` + `calendarize_corps.py`)가 필요하다. 수 시간짜리 전체 재빌드라서 사용자 판단 후 실행한다.

**소급 결과(2026-10-03, 사용자 결정 decision #5 = A)**: `build_std_v3.py --all --year-min 1999` 4분할(2,528개사, 오류 0, 구간당 약 20분) + `calendarize_corps.py` 전사(350,381행, calendar_orphan_cq 0).
- EPS 확장 행 33,268 → 394,582. 그중 `amount_exact`(R212 소수 EPS) 228 → 3,625.
- std_v3 는 319,557 → 320,093행이다(변경 32,983 · 사라짐 84 · 새로 생김 620). EPS 외 확장 캐노니컬도 바뀌었다. **R213 때문이 아니다**: 변경 200 표본 + 사라진 84 전부를 같은 현재 데이터로 R213 이전 코드(216a4b4)와 R213 코드로 계산해 std·EPS 외 확장 차이 0 이었다.
  이전 계층3 이 그동안의 fix batch 계층2 재적재를 반영하지 못한 묵은 상태였던 몫이다. 사라진 84행은 2000~2010 FY 연결이고, 현재 계층2 로는 해당 기간 연결 값이 만들어지지 않는다.
- ★교훈: fix batch 는 계층2 만 재적재하고 계층3 재빌드는 수동이라서, 재빌드를 빠뜨린 배치들의 몫이 3.3만 행 쌓여 있었다. 런북 B5(재적재 → std_v3·달력 재빌드)를 배치마다 지킬 것.

---

## R215. SCE '결손금' 열은 **음수** BS 앵커를 쓴다 — `이익잉여금(결손금)` 결합 라벨도 '결손금' 개념으로 잇는다 (2026-10-03, unclassified 큐 처리 중 발견)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections` · 이 절 안의 "판정 기준은 R0-1 … R0-1 이 이긴다" 문구는 2015+ 에서 **R0-2 로 대체됨**(PARSING_RULES.md 맨 위 표)
>
> **규칙** 계층3 보정은 SCE '결손금' 열에 음수 BS 앵커를 쓴다. (1) `add_dated_anchors` 는 BS 라벨이 `(미처분)이익잉여금((미처리)결손금)`(공백·번호 제거 후 전체 일치)이고 값이 음수일 때만 `(basis, "결손금", date)` 키를 추가한다. (2) `apply_dated_balance_signs`(R190-d)는 '결손금' 열을 앵커가 양수일 때(셀을 양수로 바꾸는 방향)만 건너뛰고, 음수 앵커를 쓸 때는 그 열 블록 잔차가 나빠지지 않을 때만 적용한다. (3) R206 목록에 `20181114001142` 별도 2017 블록 잔액 2셀을 추가해 인쇄 그대로 둔다.
> **판정 예** 인투셀 `20260515002144` 별도 SCE 2025 비교 블록 잔액: 인쇄 기초 +80,414,712,473 · 기말 +84,030,840,664 → BS(`20250327000702`·`20250515002326`)와 같은 −80,414,712,473 / −84,030,840,664.
> **하지 않는 것** 양수인 결합 라인은 키를 만들지 않는다. 결손금 열 전체(잔액+변동)를 양수 크기로 인쇄한 회사(`20210323001020` 등 12필링)는 표시 방식이라 잔액만 바꾸지 않는다(블록 잔차가 나빠지므로 인쇄 그대로). XBRL 경로는 이 체인을 쓰지 않는다.
> **코드** `sce_dated_anchors.add_dated_anchors`, `sce_sign_repair.apply_dated_balance_signs`, `sce_as_printed._AS_PRINTED_CELLS`

> **판정 기준은 R0-1** (2026-10-09). 이 절의 허용오차·증거·후보 범위·"사람 확인 후 등재"/"일반화 금지"·캠페인 판정 지침이 R0-1 과 다르면 R0-1 이 이긴다. 다른 부분은 R0-1 "정합화 대기" 표에 있다.

**발견**: 인투셀 2026Q1 `20260515002144` 별도 SCE(이슈 #87155~#87159). 원문 결손금 열은 두 블록 모두 결손 크기를 양수로 인쇄했다.
2026 블록은 R162-d 가 음수(BS 와 같은 부호)로 복원했다. 그런데 2025 비교 블록은 잔액 2셀(기초 +80,414,712,473 · 기말 +84,030,840,664)만 양수로 남았다.
변동 행은 이미 음수였기 때문에 이 블록은 열·행 항등식이 모두 깨져 있었다. BS(20250327000702 FY · 20250515002326 Q1)는 −80,414,712,473 / −84,030,840,664 다.
지적된 4셀 자체(2026 잔액·2025 순손실·재측정)는 DB 가 정답이었다. 따라서 이슈는 no_fix 로 처리했고, 이 규칙은 이슈로 등록되지 않은 형제 셀을 고친다.

**원인 두 가지**:
① 앵커 키 불일치 — BS 라벨이 `이익잉여금(결손금)` 이라 dated anchor 키가 그 문자열로 생기고, SCE 열 개념 `결손금` 과 맞지 않았다(`sce_dated_anchors.add_dated_anchors`). R162 계열 해법도, R190-d 도 증거를 못 받았다.
② R190-d 가드 보강 ① 이 '결손금' 열을 통째로 뺐다. 근거는 "BS 가 결손을 양수로 표시하는 회사"(롤링스톤)였는데, 그것은 **양수 앵커**의 문제다.

**수정**:
- `sce_dated_anchors.add_dated_anchors`: BS 라벨이 `(미처분)이익잉여금((미처리)결손금)`(공백·번호 제거 후 전체 일치)이고 값이 **음수**면, `(basis, "결손금", date)` 키도 추가한다. 양수인 결합 라인은 잉여금이므로 키를 만들지 않는다.
- `sce_sign_repair.apply_dated_balance_signs`(R190-d):
  - '결손금' 열은 앵커가 양수일 때(=셀을 양수로 바꾸는 방향)만 건너뛴다.
  - 음수 앵커를 쓸 때는 **그 열 블록 잔차가 나빠지지 않아야** 한다. 결손금 열 전체(잔액+변동)를 양수 크기로 인쇄하는 회사가 있기 때문이다(`20210323001020` 등 12필링). 이것은 괄호 누락이 아니라 표시 방식이다. 이 경우 잔액만 바꾸면 롤포워드가 깨지므로 인쇄 그대로 둔다.
- `sce_as_printed._AS_PRINTED_CELLS`(R206): `20181114001142` 별도 2017 블록 잔액 2셀을 추가했다. 새 앵커로 R162 가 잔액을 뒤집지만, 이 블록의 변동 셀은 사용자 결정(R206, 인쇄 그대로)으로 되돌려진다. 그래서 잔액도 인쇄 그대로 두어 결정 당시 상태를 유지한다.

**측정**: 2015+ XML 필링 중 SCE 에 '결손금' 열이 있는 2,954필링을 HEAD 와 수정 코드로 재추출해 A/B 비교했다(로딩 없음, 에러 0).
- 가드·키 수정만 넣은 1차 측정은 40필링 81셀이었다. 행이 좋아지고 블록이 나빠진 12필링은 위 '양수 크기 열'이었다. 블록 가드를 추가해 이 12필링을 뺐다.
- 최종 **28필링 57셀**이 바뀐다.
- 필링별 행 항등식 잔차 합과 잔액 셀 블록 잔차 합을 비교했다. 26필링은 둘 다 같거나 좋아졌다. 인투셀은 행·블록 모두 0으로 닫혔다.
- 나머지 2필링(`20250321001238`·`20250813001397` 연결 2023.12.31)은 블록이 좋아지고 행이 나빠졌다. 원문 지배기업 합계 270,494,313,162 가 결손금을 **양수로 더해** 인쇄된 원문 결함이다. 다음 행 2024.01.01 과 BS 는 −104,890,730,996 이므로 바뀐 값이 정답이다.
- 측정 스크립트는 세션 scratchpad 의 `r215_measure.py`/`r215_validate.py` 다(HEAD 모듈을 별도 import 해 같은 프로세스에서 A/B).

**회귀 테스트**: `fin2/tests/test_sce_deficit_anchor_r215.py`(결합 라벨 키, 양수 결합 라인 비키, R162 블록 해법, 블록 개선 시 잔액 반전, 양수 크기 열 불변). `test_sce_as_printed_r206.py` 셀 수 103→105.

**데일리 배선**: XML 추출 체인 내부 변경이라 추가 배선은 필요 없다. XBRL 경로는 이 체인을 쓰지 않는다.


**재적재 결과(2026-10-03, batch #99)**: 대상 28필링 done 28 / failed 0. 측정한 57셀을 재적재 후 DB 에서 하나씩 대조했고 불일치는 0이다.
인투셀 `20260515002144` 2025 기초 −80,414,712,473 · 기말 −84,030,840,664 가 BS 와 일치한다. 인투셀 이슈 4건은 지적된 셀이 이미 정답이라 no_fix 로 처리했다.
계층3 은 SCE 를 읽지 않으므로 재빌드가 필요 없다.

## R217. 계층3 은 **XBRL IS '주당' 행도 R213 EPS 규칙으로 분류**한다 — 라벨에 '계속'·'중단'이 함께 있으면 합계 후보 (2026-10-03, R216 후속, 사용자 지시)

> **상태** 유효 · **적용 계층** 3

**발견**: R213 은 HTML 경로의 `source_ref 'eps/…'` 행만 EPS 규칙으로 보낸다. XBRL 행은 일반 매퍼를 거친 뒤 개념 폴백(`_map_xbrl_concept`)으로 간다.
- 회사 확장 개념(`udf_…EarningsPerShareAbstract` 등)은 개념 폴백에도 걸리지 않는다. XBRL 주당 행이 udf 개념인 214기간 중 148기간에 `is.eps_basic` 이 없었다(예: 송원산업 2016H1 별도 1,317).
- 표준 개념(`BasicEarningsLossPerShare`/`DilutedEarningsLossPerShare`)은 개념만 보고 매핑했다. 그래서 '계속영업 EPS'·'우선주 EPS'·'중단영업 EPS' 행이 그 개념으로 태깅되면 헤드라인으로 올라갔다. 예: 00117337 2018Q3 희석EPS 85(구형우선주, 보통주는 47), 00152862 2016Q3 3,684(계속영업, 보통주 기본주당순이익은 3,516).

**규칙** (`fin2/layer3/combine.py`)
1. `_EPS_ROW_SQL`: `eps_row` = `source_ref LIKE 'eps/%'` 이거나, XBRL IS 행이면서 라벨에 '주당' 이 있고 '주식수|배당' 이 없으며 |값| < 1,000,000 인 행이다. 금액 상한은 R216 과 같다. `build_merged_lines`·`collect_candidates` 두 SQL 이 같은 식을 쓴다.
2. `_eps_classify`: 라벨 → 가장 가까운 조상 → (라벨에 '주당' 이 없는 자식행이면) 전체 경로 순으로 판정한다. '계속'·'중단' 둘 다 있으면 `total`(헤드라인 후보), 하나만 있으면 component(제외), 우선주는 제외다. R213 과 달라진 점은 **라벨**에 둘 다 있는 경우(`기본 및 희석주당이익(계속영업과중단영업)`)도 헤드라인 후보로 본다는 것이다.

**넣지 않은 것(측정으로 기각)**
- *계속영업 EPS 대체*: 헤드라인 행이 없고 0 아닌 중단영업 EPS 도 없으면 계속영업 EPS 를 헤드라인으로 쓰는 안이다. HTML 에서 추가 셀 5,167개가 생겼지만 43.4% 가 '지배순이익 ÷ EPS = 암시 주식수' 지표에서 같은 회사 FY 중앙값과 ±42% 이상 어긋났다. 기존 EPS 기준선은 20~34% 다. 중단영업 EPS 가 EPS 행으로 잡히지 않는 경우가 많아 믿을 수 없다(00100601 2023FY: 계속 168, 지배순이익 기준 약 286).
- *합계 라벨 우선*: '계속영업과 중단영업' 라벨이 평이한 라벨 형제를 이기게 하는 안이다. 측정 28셀 중 10셀이 나빠졌다. 오리엔트정공 2012Q3 은 계층2 구형 표 열 오적재로 전기 값(−8,109)이 당기 칸에 있었다. 그래서 두 헤드라인이 다르면 충돌로 두고 `_resolve` 가 보류한다(LS 2018H1 14,662 vs 4,751 → 보류).

**측정** (A/B, 같은 DB 로 HEAD `57daa84` vs 수정 코드의 `combine_full`). 대상은 IS '주당' 행이 XBRL 이거나 라벨·경로에 '계속'/'중단' 이 있는 18,285기간 × 2 basis 다. 에러 0.
- **std 열 변화 0.** 확장 EPS 만 바뀐다. 542기간이고 추가 1,161 · 사라짐 130 · 값 변경 17 이다.
- 추가 셀의 암시 주식수 '멀다' 비율은 XBRL 18.8% · HTML 24.5% 로 기준선 이하다.
- 값 변경 기본EPS 4셀은 모두 개선이다(우선주·중단영업 → 보통주 헤드라인).
- 사라지는 셀의 기존 값은 59%(68 중 40)가 '멀다' 로 기준선보다 훨씬 나쁘다. 내역은 계속영업+0아닌 중단 31 · 우선주 3 · 합계/평이 라벨 충돌 보류 등 56 · 계속영업만 있는 기간 40(R213 규약상 헤드라인 아님) 이다.
- 측정 스크립트는 세션 scratchpad 의 `r217_measure.py`·`r217_split.py`·`r217_shares_check.py`·`r217_baseline.py` 다.

**회귀 테스트**: `fin2/tests/test_r217_layer3_xbrl_eps.py`(SQL 플래그, 분류 종류, udf 행 계층3 도달, 계속영업 비헤드라인, 합계 라벨 동급 후보, 우선주 제외). `test_r213_layer3_eps_mapping.py` 그대로 통과.

**데일리 배선**: 계층3 combine 내부 변경이라 `build_std_v3`·달력 경로가 그대로 쓴다. 추가 배선은 필요 없다. **소급**: 변경 542기간의 회사만 std_v3·달력을 재빌드한다(전사 재빌드 불필요, std 열 불변).

**소급 결과(2026-10-03)**: 변경 542기간의 156개사를 std_v3(`--year-min 1990`, 25,938행)·달력(28,161행)으로 재빌드했다. ★기본 `--year-min 2015` 로 먼저 돌렸을 때는 2015 이전 197셀이 반영되지 않았다. 계층3 에 2015 이전 기간도 있으므로 소급 재빌드는 연도 하한을 낮춰야 한다.
A/B 로 측정한 1,308셀(추가·사라짐·변경)을 재빌드 후 `extended_facts_v3` 에서 하나씩 대조했고 불일치는 0이다. 송원산업 2016H1 별도 `is.eps_basic` 1,317, 00117337 2018Q3 연결 희석 47 이다.

## R220. 달력 CY(12월 결산 native)의 flow 는 **같은 회계연도 FY as-filed 값**을 쓴다 (2026-10-05, 삼양식품 '배당금 지급 2021년 이후 비어 있음')

> **상태** 유효 · **적용 계층** 3

**발견**: std_v3 FY 의 dividends_paid 는 2021~2025 모두 있는데 `std_financials_calendar` CY 만 NULL. 삼양식품은 배당을 4월에 지급해 Q1 CF 에 배당 줄이 없고(Q1=None), `_cy_record` 는 ΣCQ 를 "4분기 모두 non-None 일 때만" 만들었다. 전사 FY 배당 23,325건 중 15,256건이 Q1 None.

**규칙** (`fin2/standardize/calendar_v3.py::_native_fy_row`/`_cy_record(fy_row=)`): CY 의 네 분기가 한 회계연도에서 왔고(native) 그 FY 행의 period_end 가 그 해 12-31 이면, flow 컬럼은 FY 행 값을 그대로 쓴다. Q1+(H1−Q1)+(Q3−H1)+(FY−Q3)=FY 항등식이라 ΣCQ 와 같은 값이고 추정이 아니다. recomposed(비12월 결산)는 기존 ΣCQ 그대로. 0 으로 채우는 안(배당 줄 부재=0)은 미매핑 라벨과 구분할 수 없어 기각.

**측정**: 기존 native CY 64,221행 중 ΣCQ 가 있는 값은 FY 와 일치(불일치 7행은 std_v3 재빌드 이후 달력이 갱신 안 된 낡은 행). 새로 채워지는 값: dividends_paid 25,686 · da_total 9,028 등.

**회귀 테스트**: `fin2/tests/test_calendar_v3.py`(R220 4건).

## R221. 계층3 std 비용 컬럼은 **비용 = 양수** 관례로 정규화한다 — 항등식 증명 + 성질상 비음수 비용 (2026-10-05, 삼양식품 '2024년부터 비용 음수')

> **상태** 유효 · **적용 계층** 3

**발견**: 삼양식품 2024·2025 사업보고서 원문이 비용을 괄호로 인쇄한다(`매출원가 (1,004,797,694,924)`, 2023 은 양수). 계층2 는 원문 그대로(정상), 계층3 이 부호를 그대로 옮겨 std cogs/sga/법인세/이자비용이 음수가 됐다. FY cogs 음수 회사 2022 14 → 2025 372. Gate B(face_audit)는 부호만 다른 값을 E2_SIGN 으로 PASS 하며 "std 는 비용을 양수로 정규화" 를 전제하고 있었다 — 규약은 있었고 구현이 없었다.

**규칙** (`fin2/layer3/expense_sign.py::normalize_expense_signs`, `fin2/layer3/build.py` 가 행 저장 직전 호출)
1. 항등식(±max(1,000원, 값/10⁵)): cogs `gross_profit = revenue ∓ cogs`, sga `operating_income = gross_profit ∓ sga`, tax `net_income = ebt ∓ tax`. `+` 만 성립 → 음수관례 증명 → 부호 반전. `−` 만 성립 → 그대로.
2. cogs·sga·interest_expense 는 성질상 음수가 될 수 없는 비용이라 자기 증명이 없어도 음수면 반전(같은 표 안에서도 관례가 섞임: 00145260 FY2018 매출원가 양수·판관비/금융비용 음수). 단 1 의 `−` 증명이 있으면 그대로.
3. 법인세는 환급(음수)이 정상값이라 자기 증명이 있을 때만 반전한다. 음수관례 표에서 양수로 인쇄된 환급(5,992행)은 음수가 된다.
4. rd_expense 는 대상 아님(주석 소스, `rules.py::rule_rd_fallback` 이 이미 abs).

**측정**(정규화 전 std_v3 전체 시뮬레이션): 반전 cogs 4,084 · sga 8,584 · interest 16,509 · tax 15,072. 남는 음수 cogs 148 · sga 338 은 모두 자기 항등식이 그 음수값을 증명한 행.

**회귀 테스트**: `fin2/tests/test_expense_sign.py`. **데일리 배선**: build_corp 내부라 추가 배선 없음. **소급**: std_v3 전사 재빌드(`--year-min 1990`) + 달력 재빌드(R219 D&A 와 한 번에).

## R223. 계층3 문서 매퍼는 **머리 경로(header path)로 열을 찾고**, 숫자·단위·날짜는 공통 규칙으로 읽는다 (2026-10-05, API→문서 전환 Phase 1~6)

> **상태** 유효 · **적용 계층** 3

모듈: `fin2/layer3/doc_common.py`(공통) · `doc_dividend` · `doc_shareholders` · `doc_people` · `doc_pay` · `doc_investments` · `doc_treasury`, 적재 `collector/doc_sections_sync.py`(테이블명·컬럼 유지, 회사 단위 fy≥2015 delete-then-insert).

1. **필링 선택**: (corp, FY) 사업보고서를 is_final→최초 순으로 보며 해당 서식 코드 표가 있는 첫 필링(첨부정정은 본문이 없어 자연히 원본으로 내려감).
2. **머리행**: 0열 라벨이 같은 선행 행 묶음. 그 묶음이 1행이면 숫자 셀 없는 선행 행(최대 5) — EMPLOYEE 4단 머리.
3. **열 찾기**: `find_col(paths, *needles, leaf=)` — 측정 항목(주식수·지분율 등)은 **맨 아래 머리**(`leaf`)로만 찾는다. 상위 배너 '소유주식수 및 지분율' 에 두 이름이 다 들어 있어 부분일치하면 주식수 열이 지분율로 잡혔다(삼양식품 2024 BSH_SPCL 실측). 열 번호 0 이 유효하므로 후보 연쇄는 `or` 금지, `coalesce` 사용.
4. **숫자**: 셀 안 공백·줄바꿈 제거 후 파싱('3,388,\n417', 삼양식품 2024 BSH_SPCL 계 행 — R150 계열). '-'·빈칸 → NULL, 그 외 파싱 실패 → NULL(추측 금지).
5. **단위**: 금액은 그룹 캡션의 '(단위 : 천원)' 을 곱해 원으로, 수량은 '천주' 면 ×1,000. 금액 단위 선언이 없으면 금액 NULL.
6. **날짜**: 'YYYY년 MM월 DD일'·'YYYY-MM-DD' → 'YYYY.MM.DD'(API 판 형식). '-' 대표값(부문·목적·종류)은 NULL.
7. **API 판과 다르게 한 것(원문 기준)**: 임원 등기·상근 여부를 원문 문자열로 판정(API 판은 'Y/N' 만 읽어 대부분 거짓/NULL), 근속연수 '6년 5개월'→6.42, 자기주식 취득방법 라벨·행 순서 원문 그대로, 원문에 표가 없는 연도는 행 없음(API 판의 전부-NULL 자리표시 행 없음).

**검증(부분 적재 시점 표본, 전사 수치는 컷오버 기록에)**: 원문판 vs API 판 (corp, FY) 그룹 완전일치 — 임원보수(개인) 100% · 요약 99.9% · 소액주주 98.8% · 최대주주 98.6% · 직원 98.9% · 자기주식 97.9% · 변동 97.4% · 배당 96.6%. 표본으로 확인한 불일치는 모두 원문판이 맞다: 2026 기재정정 반영(API 는 정정 전 값), API 의 '#######' 칸 넘침 값, 주식배당 '0.07주'→API 0.0 절삭, 정규직 수 등 API NULL.

**회귀 테스트**: `fin2/tests/test_doc_dividend.py` · `test_doc_shareholders.py` · `test_doc_people_pay_inv_treasury.py`.

## R227. R170-d 법인세 부호 정산은 **필러 확장 개념의 계속영업 순이익 행**도 후보로 쓴다 (2026-10-08, fix batch #117, unclassified #89274)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 XBRL IS 법인세 부호 정산(R170-d)에서 표준 후보(`ProfitLossFromContinuingOperations`·`ProfitLoss`)로 판정이 서면 종전 그대로 하고, 표준 후보가 없거나 어느 등식도 안 맞을 때만 같은 (basis, col) 의 IS 행 값 전체(세전·세금 행 제외)를 후보로 쓴다. 세전 + 세금 이 그 후보 중 하나이고 세전 − 세금 은 어느 것도 아닐 때만 세금 부호를 뒤집고, 둘 다 아니면 건드리지 않는다(R6).
> **판정 예** 베노티앤알 `20191101000282`(2019H1) 연결 IS 법인세비용 +8,422,622: 세전 4,191,042,672 + 8,422,622 = 계속영업반기순손익 4,199,465,294(필러 확장 개념 행), `ProfitLoss` 4,188,448,493 은 중단영업(−11,016,801) 포함으로 등식 불성립 → −8,422,622. 같은 필링 별도 −14,549,431 유지.
> **하지 않는 것** 표준 후보로 판정이 서면 이 확장을 쓰지 않는다(R170-d 무변경). 세전 − 세금 이 후보 중 하나와 맞으면 뒤집지 않는다.
> **코드** `fin2/extract/report_lines_xbrl.py::_settle_is_tax_sign`

**발견**: 베노티앤알 `20191101000282`(2019H1) 연결 IS 법인세비용이 +8,422,622 로 적재됐는데 같은 필링 별도는 -14,549,431 이다.
두 기준의 XBRL fact 는 모두 양수(법인세**수익**을 양수로 태깅)이고, 연결은 세전 4,191,042,672 + 8,422,622 = 계속영업반기순손익 4,199,465,294 로 수익이 맞다.

**원인**: R170-d(`_settle_is_tax_sign`)는 세후 이익 후보를 표준 개념 `ProfitLossFromContinuingOperations`·`ProfitLoss` 두 개로만 찾는다.
연결은 계속영업 순이익 행이 필러 확장 개념(`udf_IS_…StatementOfComprehensiveIncomeAbstract`)이고 `ProfitLoss`(4,188,448,493)는 중단영업(-11,016,801)을 포함해 등식이 서지 않아, 판정이 아예 안 났다.

**수정** (`fin2/extract/report_lines_xbrl.py::_settle_is_tax_sign`): 표준 후보로 판정이 서면 종전 그대로(R170-d 무변경).
표준 후보가 없거나 어느 등식도 안 맞을 때만, 같은 (basis, col) 의 IS 행 값 전체(세전·세금 행 제외)를 후보로 쓴다.
세전 + 세금 이 그 값 중 하나이고 세전 − 세금 은 어느 것도 아닐 때만 부호를 뒤집는다. 둘 다 아니면 건드리지 않는다(R6).

**전수 측정**(DB report_lines IS col 0, 세전·세금 쌍 2,338): 위 조건에 해당하는 셀 **11개 · 11필링** — 경창산업 2건, 일신석재 2건, 휴맥스, 휴맥스홀딩스 2건, 엠케이전자 2건, 팜스토리, 베노티앤알.
**회귀 테스트**: `fin2/tests/test_xbrl_is_tax_sign_pool_r227.py` 6건. **데일리 배선**: `_settle_is_tax_sign` 내부라 추가 배선 없음.

**소급 결과(2026-10-08)**: batch #117 로 11필링 재적재 → done 11 / failed 0, #89274 fixed. 모든 필링에서 연결·별도의 법인세 부호가 같은 기준이 됐다(예: 베노티앤알 연결 +8,422,622 → -8,422,622, 별도 -14,549,431 유지).
계층3 은 7개사만 재빌드했다(std_v3 `--year-min 2015` 644행, 달력 1,294행, orphan 0). 복원 건수를 특정 규칙 효과로 귀속하지 않는다.

## R229. 인쇄 계정명이 **택소노미 한국어 표준 라벨**이면 그 개념으로 계층3 계정을 정한다 (2026-10-10, 사용자 결정 "근본적인 방법으로")

> **상태** 유효 · **적용 계층** 3

**발견**: 웹뷰 인쇄본 재적재(XBRL 적재 1,639필링 → 인쇄값) 후 계층3 비교에서 `intangibles` 622칸이 NULL 이 됐다. XBRL 셀은 개념(R172 `xbrl_local`)으로 `bs.intangibles` 가 됐지만 인쇄본 `영업권 이외의 무형자산` 은 별칭 사전(`account_maps`)에 없다.
같은 라벨을 인쇄한 **원본 XML** 필링도 이미 같은 상태였다 — 2015+ 31,842기간 중 29,777기간 `intangibles` NULL. DART XML 의 ACODE 는 서식 항목(CS_DIV, SH5_* …)만 달고 재무제표 행에는 개념이 없으므로, 인쇄본 경로(XML·웹뷰·PDF)는 라벨만으로 매핑된다.
DART 편집기로 작성한 재무제표는 택소노미의 한국어 라벨을 그대로 인쇄하는 경우가 많다.

**정의**:
- 색인 `fin2/taxonomy/ko_label_index.json` = DART 택소노미 한국어 라벨 링크베이스(`taxonomy_cache/*labels_lab_{ifrs,dart}-ko_*`, 2010~2024 vintage, gcd 제외)의 **표준·terse·total 라벨** → 개념. 기초/기말 라벨(SCE 문맥), negated 라벨(부호 반대), DART `dart_label` 역할(`기말 장부금액` 같은 문맥 캡션), `[abstract]`·`[text block]` 등은 넣지 않는다. 키 = `normalize_account_name` 후 공백 제거. 옛 vintage 의 `ifrs_` 접두는 `ifrs-full_` 로 통일. 생성 `scripts/build_ko_label_index.py`.
- 조회 `fin2/taxonomy/ko_labels.canonical_for_label`: 라벨을 가진 **모든 개념이 같은 canonical** 로 갈 때만 그 canonical(`concept_map.map_acode`), 아니면 모호 → 사용 안 함.
  `concept_map.AUDIT_ONLY_CONCEPTS`(Gate B 감사용으로 넓게 묶은 `dart_ShortTermOtherPayables`·`dart_LongTermTradeAndOtherNonCurrentPayables`·`ifrs-full_NoncurrentPayables` → `bs.trade_payables`, R23 "후보 추가는 단조 개선")는 값 식별에 쓰지 않는다(미지급금 ≠ 매입채무).
- 계층3 `combine._map_rows` 순서: ① 별칭 exact/normalized ② (XBRL 셀) 개념 R172 ③ **택소노미 라벨(R229)** ④ 퍼지(≥0.88). 택소노미 라벨 일치는 동일성 증거라 유사도 추정인 퍼지보다 앞선다. 경로 라벨(`A>B`)은 끝 조각으로 찾는다.
  후보 순위(`_STAGE_RANK`)는 별도 단계 `taxonomy`(1.5) — 별칭(exact 3·normalized 2)보다 낮고 퍼지(1)보다 높다. 처음 `normalized` 로 두었다가 전사 재빌드 비교에서 새 충돌 10칸(→NULL)이 나왔다: 머리행 같은 `자본` 행(퍼지라 `자본총계` 에 밀리던 것)이 동순위가 되고, `무형자산` 합계 옆에 인쇄된 `영업권 이외의 무형자산` 이 동순위가 됐다. 별칭 사전은 회사들의 인쇄 관례로 다듬어진 것이라 택소노미 일치보다 앞선다.
- 주당이익(`is.eps_basic/diluted`)은 적재기 EPS 경로(R213) 소관이라 이 단계에서 분류하지 않는다.

**전수 측정**(2015+ BS/IS/CF col 0 라벨, 필링 수 가중, 읽기 전용):
새 매핑 — `bs.intangibles` 22,430 · `cf.acquisition_of_subsidiaries` 12,663 · `bs.investments_in_subsidiaries` 10,592 · `cf.short_term_investment_net` 9,064 · `cf.bond_repaid` 4,259 · `is.revenue` 1,118(`수익`) 등.
퍼지 교정 — `비유동 기타포괄손익-공정가치 측정 금융자산` 단기투자→장기투자 4,251 · `기타영업수익` other_income→other_op_revenue 1,391 · `유동부채 합계` 부채총계→유동부채 89 · `유동자산 합계` 자산총계→유동자산 88 등. 퍼지와 택소노미가 같은 결과 67,313.
**데일리 배선**: 계층3 빌드 내부 변경이라 추가 배선 없음(색인 JSON 은 저장소에 커밋). **소급**: 계층3 전사 재빌드(2015+). **회귀 테스트**: `fin2/tests/test_r229_taxonomy_labels.py`.

**소급 결과(2026-10-10)**: 계층3 전사 재빌드(2,528개사, 2015+, 189,138행) 전후 비교(사본 `r02_r226_std_before`·`r02_r226_ext_before`).
std — 바뀐 행 36,690: `intangibles` 채워짐 33,976 · 값 변경 1,311(표본 전부 자식 행 `기타무형자산`·`산업재산권` 대신 인쇄 합계 `영업권 이외의 무형자산`) · `revenue` 채워짐 1,729(`수익`) · `current_assets` 194 · `current_liabilities` 185 · `receivables` 채워짐 127 / 값 13 · NULL 이 된 칸 **0**.
extended — 새 칸 42,139 · 부호 3,061(`cf.dividends_received` 2,814: 조정 항목 `배당금수익` 대신 `배당금수취(영업)`, 상당수 0→0) · 값 2,266 · 빠짐 1,710(`is.other_income` 1,402 → `is.other_op_revenue` 로 이동).
남은 계층3 과제(이 규칙 이전부터 있던 것): `cf.short_term_investment_net`·`cf.govt_grant` 같은 순액 계정에 취득/처분·수취/상환 여러 행이 붙어도 extended 는 한 행만 고른다(전·후 모두 순액이 아님) → 계층3 백로그.
웹뷰 재적재로 비었던 `intangibles` 622칸은 이 재빌드로 채워졌다.

## R230. 주석 표 열이 **[기간 > 기능]** 2단이면 그 기간의 **합계 열**을 쓴다 — 계층3 D&A (2026-10-10, 사용자 지시 "바로 착수", 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**발견**: 웹뷰 `<BR>` 수정 후 재빌드에서 D&A 가 바뀐 사례를 원문과 대조 — 00110431 2015Q3 연결(`20151209000350`) 비용의 성격별 분류 열이 `누적>매출원가 | 누적>판매비와 관리비 | 누적>성격별 비용` 인데 `parser/common/note_periods.cumulative_col` 이 "누적" 이 든 **첫 열**(매출원가)만 당기로 잡아 감가상각비 343,401,000 만 읽고, 그 열이 빈 무형자산상각비는 통째로 빠졌다(정답 721,815,000 + 1,076,024,000). FY 도 같다 — `당기>매출원가` 처럼 기간이 마지막 조각이 아니면 기간으로 못 읽어 위치 추측(MULTICOL)으로 떨어졌다.

**정의** (`parser/common/note_periods.py`, 소비처는 `fin2/layer3/note_da.py` 뿐):
- 열 헤더 경로를 조각으로 나눠(단위 조각 제외, **자간 공백 제거** — `누 적`·`당 분 기`·`전 분 기`) 기간 조각(당기·전기·누적·3개월·제N기·연도)과 나머지(기능·자산분류)로 가른다. 당기/전기는 **모든 조각**에서 찾는다.
- interim 누적 열: "누적" 조각이 있고 `3개월` 조각·전기 조각(`전기`·`전분기`·`전누적`·`전년`)이 없는 열 중 첫 열의 기간과 같은 열들(헤더 `당누적3분기>3개월` 은 누적 열이 아니다 — 00126487 2021Q3 `20211115001068`).
- 같은 기간의 열이 여럿이면 **합계 열**(`합계`·`계`·`총계`·`총액`·`성격별 비용`·`비용 합계`) — 정확히 하나일 때만. 아니면 종전처럼 앞 열(합산 추측은 하지 않는다). 형제표 경로도 같다.

**측정**(계층3 전사 재빌드 2,528개사, 사본 `r02_r230_std_before`): `da_total` 이 바뀐 11,211행을 같은 필링 **주석 현금흐름표 조정 표**(감가상각비·무형자산상각비 등 당기 열, 독립 증거)와 1% 이내 일치로 판정 — 좋아짐 **4,425** · 나빠짐 **154** · 둘 다 일치 262 · 둘 다 불일치 2,004 · 근거 없음 4,366.
나빠짐 표본은 모두 같은 유형: 열은 맞게 읽었지만 그 표에 무형자산상각비 행이 없고 다른 표에 있다(00295547 성격별 분류 감가상각비 합계 248,511,000 / 현금흐름 주석 262,598,000 = +상각비 14,086,000). `note_da` 가 **표 하나만** 채택하는 기존 한계 → 계층3 백로그(완결형 표에 없는 버킷을 다른 소스에서 보충).
**기각한 보강 R230-b**(2026-10-11 새벽): "현금흐름 주석이 성격별 분류보다 항목 종류가 많으면 현금흐름 주석" — 전사 재빌드에서 11,874행이 바뀌었는데 그중 6,380행은 두 표의 **감가상각비 자체가 1% 넘게 다르다**(범위가 다른 표 — 사용권자산·중단영업 포함 여부 등). 현금흐름 주석과의 일치율로 재면 좋아 보이지만 그 주석을 고르는 규칙이라 순환 측정이다. 근거가 없어 되돌렸다(코드 미반영). 상각비 보충은 "두 표의 감가상각비가 같을 때만" 같은 조건으로 따로 설계한다.
**회귀 테스트**: `fin2/tests/test_r230_note_period_function_columns.py`. **배선**: 계층3 빌드 내부 — 추가 배선 없음.

## R231. D&A = **현금흐름표 조정 금액**. 출처는 하나만, 출처를 기록한다 (2026-10-11, 사용자 결정 A, 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**근거**: 같은 보고서 안에서도 비용의 성격별 분류와 현금흐름 조정의 감가상각비가 다르고(자본화 감가상각·사용권자산 포함 여부 등) 보고서 안에서 맞출 근거가 없다(R230-b 측정 6,380행). 실측 JW중외제약 2019 연결 `20200330004416` 주석 30 성격별 14,148,486,000 / 주석 36 현금흐름 12,573,022,000 + 사용권 1,937,197,000 · 디지아이 2023H1 `20230814000945` 229,799,000 / 263,201,000 · 자화전자 2025 `20260318000870` 45,471,761,000 / 45,272,768,000. → 정의를 하나로 정한다: EBITDA·FCF 는 현금 기준 지표라 **현금흐름 조정**.

**정의** (`fin2/layer3/combine._apply_enrichment`, `fin2/layer3/note_da.py`):
- 우선순위 — 본문 CF(`cf.*`) → 주석 현금흐름 → 주석 성격별 → 주석 판관비 → 주석 구성요소(유형·무형·투자부동산·리스 증감표 합산) → 본문 IS(`is.*`, 대개 판관비 몫). **한 출처만** 쓰고 출처끼리 더하지 않는다(종전엔 본문 CF 와 본문 IS 가 둘 다 있으면 합산 — 같은 금액 2배, 실측 00957735 2017H1 2,794,907,222 → 1,397,453,611).
- 완결형 = 감가상각(또는 결합 표기)이 있는 결과. 사용권자산 감가상각만으로는 완결형이 아니다.
- `parser/common/note_labels.classify_da_label`: `유형자산상각비` = 감가상각(실측 애경산업 2025H1 `20250813000751` 현금흐름 주석 6,537,320,000 — 놓치면 사용권자산 행만으로 D&A 가 됐다).
- `std_financials_v3.da_source`(마이그레이션 `2026_10_11_std_v3_da_source`): `cf_body` / `cf_note` / `nature_note` / `sga_note` / `component_note` / `is_body`.

**소급 결과**(계층3 전사 재빌드 2,528개사, 사본 `r02_r231_std_before` = R230 상태): 출처 cf_note 113,670 · cf_body 54,939 · nature_note 9,544 · sga_note 3,284 · component_note 2,960 · is_body 97.
da_total 바뀐 45,359행(비율 새/옛): 0.9~1.1 28,578 · 1.1~2 6,081 · 0.5~0.9 6,076 · >2 3,782 · <0.5 842 · 비게 됨 2.
표본 원문 대조(전부 새 값이 맞음): 성격별 표에 무형자산상각비가 없던 것(초록뱀미디어 2022Q3 2,726,735,000 → 15,514,186,000 = 감가 + 콘텐츠 상각 12,787,451,000), 성격별 표 단위 선언 오류(신대양제지 2018 `(단위 : 원)` 인데 천원 숫자 7,435,732 → 7,435,732,000, 쓰리에이로직스 2026Q1 204,276,944,000 → 315,647,000), 매출원가 열만 읽던 것(지어소프트 2023H1 267,983,000 → 828,061,000), 앱튼 2021 1,434,665,000 → 117,257,000(증감표 감가 77,327,000 + 사용권 33,158,000 + 투자부동산 2,649,000 + 무형 ≈ 117M).
비게 된 2행(다날 2025H1·Q3 연결)은 옛 값이 사용권자산 증감표의 `건물` 열(1,331,536,000, 합계 1,834,447,000)이던 오값.
**회귀 테스트**: `fin2/tests/test_r231_da_source_cash_flow_first.py`. **배선**: 계층3 빌드 내부 — 추가 배선 없음.

## R232. CF "현금유출액" 구간에 유출 금액의 **크기**를 인쇄한 양식 → 계층3 이 부호를 붙인다 (2026-10-11, 사용자 지시 "부호 정리부터", 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 CF 구간(같은 (basis, table_seq, col_index) 에서 `section_path` 마지막 단계가 유출 표제인 행; 표제 = `현금유출`(뒤에 `입` 없음) + 표제나 부모 단계에 활동어(`영업|투자|재무`) + 부정어(`없|업는|않|아니|수반`) 없음)에서 S = 자식 합, H = 표제 행(부모 경로·같은 계정명·자식보다 위), T = 활동 합계 행, I = 형제 유입 구간 합, 허용오차 max(1,000원, 단위 × 자식 수)로 본다. 크기 관례 증명((H<0 ∧ S≈−H) ∨ (H>0 ∧ S≈H) ∨ (T≈I−S ∧ ¬T≈I+S))만 성립하면 0 아닌 자식 전부에 −1 을 곱하고(크기 관례 안의 음수 자식은 양수가 된다), H>0 이면 H 도 −1 을 곱한다.
> **판정 예** `배당금의 지급 413,409,970`(괄호 없음) → 음수. 음수→양수 8행 예: `20150515002674` 유출 소계 −185,625,848,252 = 상환들 − 배당 2,298,867,380, 활동 항등식도 일치(표 산수가 그 배당 행을 유출 차감으로 다룸).
> **하지 않는 것** 부호 관례 증명((H<0 ∧ S≈H) ∨ (T≈I+S ∧ ¬T≈I−S))·두 증명 충돌·증명 없음 / 크기 관례인데 자식이 전부 음수 / 손자 행 / XBRL 행 / 다른 규칙이 이미 보정한 셀이 다른 값을 가진 구간은 손대지 않는다. `현금유출이 없는 비용등의 가산`·`현금유출입이없는손익항목` 같은 비현금 조정 구간은 제외한다. R232-b(증명 없이 "H<0 · 자식 전부 양수"면 뒤집기)는 기각(2014 이전 25,085구간 중 96% 가 S>|H|, H 오염). R18 은 배당 지급을 양수로 바꾸지 않는다. 소급은 2015+ 만(2015 이전은 R0-2 이행 때 재추출).
> **코드** `fin2/extract/cf_outflow_sign.py` · `as_printed.STEPS` 의 `R232_cf_outflow_sign`(`report_lines.py` 에서 `_base` 바로 다음, R18 앞) · `scripts/r232_cf_outflow_backfill.py` · 테스트 `fin2/tests/test_r232_cf_outflow_section_sign.py`, `test_report_lines_inline_xbrl_overlay.py::test_overlay_never_turns_dividends_paid_positive`
> **코드 확인** (2026-10-12) 허용오차의 '단위' = 그 구간의 0 아닌 값을 모두 나누어떨어지게 하는 가장 큰 10의 거듭제곱(최대 1,000,000) — `cf_outflow_sign._unit`, `tol = max(1_000, _unit(...) * len(children))`.

**근거**: 투자·재무활동을 `…현금유입액 / …현금유출액` 구간으로 나눠 인쇄하는 양식 중 상당수가 유출 항목을 괄호 없이 인쇄한다(`배당금의 지급 413,409,970`, 소계는 괄호일 때도 아닐 때도 있음). 계층2 는 인쇄값 그대로(R0-2)인데 계층3 에 이 양식의 부호 규칙이 없어 `std_financials_v3.dividends_paid` 2015+ 5,231행·`borrowings_repaid` 8,923행이 양수였다. R18(인라인 XBRL 배당 대사)은 태그 있는 필링의 배당 행만 덮는다(52셀).

**규칙** (`fin2/extract/cf_outflow_sign.py`, 계획·측정 `docs/plans/r232_cf_outflow_section_sign_2026-10-11.md`):
- 구간 = 같은 (basis, table_seq, col_index) 에서 `section_path` 마지막 단계가 유출 표제인 CF 행. 표제 = `현금유출`(뒤에 `입` 없음) + 표제나 부모 단계에 활동어(`영업|투자|재무`) + 부정어(`없|업는|않|아니|수반`) 없음 — `현금유출이 없는 비용등의 가산`·`현금유출입이없는손익항목` 같은 비현금 조정 구간을 막는다(첫 측정에 섞여 들어옴).
- S = 자식 합, H = 표제 행(부모 경로·같은 계정명·자식보다 위), T = 활동 합계 행, I = 형제 유입 구간 합. 허용오차 max(1,000원, 단위 × 자식 수).
- 크기 관례 증명: (H<0 ∧ S≈−H) ∨ (H>0 ∧ S≈H) ∨ (T≈I−S ∧ ¬T≈I+S). 부호 관례 증명: (H<0 ∧ S≈H) ∨ (T≈I+S ∧ ¬T≈I−S).
- **크기 관례만 증명되면** 0 아닌 자식 전부 × −1(크기 관례 안의 음수 자식은 유출 차감이라 양수가 된다), H>0 이면 H 도 × −1.
- 손대지 않음: 부호 관례 증명·두 증명 충돌·증명 없음 / 크기 관례인데 자식이 전부 음수(유입까지 음수로 인쇄한 이해 못 한 표) / 손자 행 / XBRL 행 / 다른 규칙이 이미 보정한 셀이 다른 값을 가진 구간.
- **R232-b(증명 없이 "H<0 · 자식 전부 양수"면 뒤집기)는 기각**(reviewer 2026-10-11): 2014 이전 해당 25,085구간 중 96% 가 S>|H| — 행 누락이 아니라 H 자체가 오염된 표(예 `20111111000419` 별도: 유출 표제 값 = 활동 합계)라 H 부호를 증거로 쓸 수 없다.

**배선**: 추출기 rules-on 단계 `as_printed.STEPS` `R232_cf_outflow_sign` — `report_lines.py` 에서 `_base` 바로 다음(R18 앞). 모든 적재 경로(`extract_*_with_corrections`)가 지나므로 call site 추가 없음.
**R18 가드 추가**: 배당 **지급**을 양수로 바꾸지 않는다(인라인 XBRL 태그 부호가 회사마다 달라 보정 52건 중 15건이 인쇄 음수를 양수로 바꿨음 — 예 `20251114001409` −84,588 → +84,588). R232 뒤에 R18 이 R232 결과를 되돌리는 것도 이 가드가 막는다.
**소급**: 2015+ 만(R0-2 소급 범위) — `scripts/r232_cf_outflow_backfill.py` 가 저장된 인쇄값에 같은 함수를 돌려 보정 행을 쓴다(재추출 없음). 2015 이전은 R0-2 이행 때 재추출로 함께.
**소급 결과**(2026-10-11): 2015+ 6,496필링 98,370셀 `R232_cf_outflow_sign`, R18 오보정 15행 삭제, 계층3 재빌드 529개사(사본 `r02_r232_std_before`·`r02_r232_ext_before`, 1,785개사). std 행 수 불변(151,312).
std 변동은 부호뿐 — `borrowings_repaid` 6,960 · `dividends_paid` 4,426 · `borrowings_proceeds` 5(전부 `기타금융상품의 증가` → 차입 조달 기존 오매핑, 부호는 맞음) · `borrowings_repaid` 값 3(합산 구성 변화: 01042979 2017Q3 정정본과 일치하게 −2,182,192,000, 00159023 2017FY 유입 구간 `단기차입금의 순감소`를 상환에 합산하는 기존 문제).
2015+ `dividends_paid` 양수 5,231 → 816, `borrowings_repaid` 양수 8,923 → 1,961. 음수→양수 8행은 표 자체 산수가 그 배당 행을 유출 차감으로 다루는 경우(20150515002674: 유출 소계 −185,625,848,252 = 상환들 − 배당 2,298,867,380, 활동 항등식도 일치).
extended 부호 변동 44,886셀, 사라진 80셀 = 순액 계정(`cf.short_term_investment_net` 등)에 처분·취득 두 행이 붙어 같은 부호 근사치 하나를 고르던 것이 이제 부호가 달라 보류(백로그 "순액 계정 한 행 선택").
Gate B: 부호만 반대는 PASS(`face_audit.py:1764`)라 영향 없음. 재추출 대조 63필링 2015+ 전부 일치.
**회귀 테스트**: `fin2/tests/test_r232_cf_outflow_section_sign.py`, `test_report_lines_inline_xbrl_overlay.py::test_overlay_never_turns_dividends_paid_positive`.

## R159-보강⑤. 천원 표에 **원 단위까지 소수 3자리**로 인쇄한 셀 — CJ제일제당 2025 사업보고서 (2026-10-11, 사용자 지시 "처리해", 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3 · 코드는 `fin2/extract` 의 `as_printed` STEP 뒤 → `layer3_cell_corrections`
>
> **규칙** 계층3 보정은 천원 선언 표에 원 단위까지 소수 3자리로 인쇄된 진짜 소수 셀(`_DOT_GROUPED_RE` 에 걸려 R160 이 숫자로 읽지 않은 것 — 계층2 는 값 NULL 행)을 `_SOURCE_TYPO_CELL_FIXES` 에 쉼표를 뺀 형태로 등재해, `parse_amount`(R157, Decimal)가 ×1,000 한 정확한 원 값으로 `layer3_cell_corrections` 보정(`R159_typo`)으로 싣는다 — 2026-10-12(R160) 부터 계층2 에 값 NULL + `value_raw` 행이 있어 그 행의 value 보정이다(전에는 fill). 천원 × 소수 3자리 = 정확한 원이라 반올림하지 않는다.
> **판정 예** CJ제일제당 `20260316001116`(2025 사업보고서) 연결 손익계산서 지배기업 소유주 귀속 당기순이익(손실)·계속·중단 3행 `(571,455,619.874)`·`(322,517,146.659)`·`(248,938,473.216)`(천원, ADECIMAL=-3) → `(571455619.874)` 등으로 등재, −571,455,619,874 원 등. 근거: 당기순이익 (416,955,408) = 지배 (571,455,619.874) + 비지배 154,500,212(천원 반올림), 계속 + 중단 = (571,455,619.875).
> **하지 않는 것** 반올림하지 않는다. 계층2 에 값을 쓰지 않는다(R0-2).
> **코드** `_SOURCE_TYPO_CELL_FIXES`, `parse_amount`(R157) (회귀 `tests/test_r159_cj_exact_decimal_cells.py`; 재적재 이 필링 1건 + 00635134 계층3 재빌드)
> **충돌·불명확** 근거 산수에서 지배 (571,455,619.874) 와 계속+중단 (571,455,619.875) 이 0.001천원(1원) 어긋나는데, 이를 허용하는 오차 기준은 본문에 없다.

**발견**: R0-2 drift 재적재(2026-10-10) 뒤 `20260316001116` 연결 손익계산서의 "지배기업의 소유주에게 귀속되는 당기순이익(손실)"·계속·중단 3행이 계층2 에 없음. 원문 셀 `(571,455,619.874)`·`(322,517,146.659)`·`(248,938,473.216)`(천원 선언, ADECIMAL=-3) — `_DOT_GROUPED_RE` 에 걸려 R160(해결 안 된 마침표 셀은 결측)이 값을 버렸다.
**판단**: R159-보강(미래에셋증권)과 같은 "진짜 소수" 계열. 천원 × 소수 3자리 = 정확한 원이라 반올림하지 않는다. 표 자체 산수가 증명한다: 당기순이익 (416,955,408) = 지배 (571,455,619.874) + 비지배 154,500,212(천원 반올림), 계속 (322,517,146.659) + 중단 (248,938,473.216) = (571,455,619.875).
**수정**: `_SOURCE_TYPO_CELL_FIXES` 에 쉼표를 뺀 형태로 등재(`"(571,455,619.874)"→"(571455619.874)"` 등) — `_DOT_GROUPED_RE` 를 지나지 않고 `parse_amount`(R157, Decimal)가 ×1,000 해 −571,455,619,874 원. R0-2 에 따라 계층2 는 결측 그대로, 값은 `layer3_cell_corrections` fill(`R159_typo`).
**재적재**: 이 필링 1건 + 00635134 계층3 재빌드. **회귀 테스트**: `tests/test_r159_cj_exact_decimal_cells.py`.

## R233. CF 이자·배당 현금 계정은 **현금 행**이 있으면 손익 계정명 후보를 버린다 (2026-10-11, 사용자 지시 "행 순서에 따라 값이 달라지는 extended 15건 처리", 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**근거**: `account_maps/cf_accounts.py` 의 `cf.interest_paid`·`cf.interest_received` 별칭에 K-GAAP 직접법용 `이자비용`·`이자수익` 이 있다. 간접법 CF 에서는 이 계정명이 **조정 구간**(당기순이익 조정을 위한 가감)의 손익 가산·차감 행이라, 실제 현금 행(`이자지급`·`이자수취`)과 크기는 같고 부호가 반대인 후보가 둘 생긴다. 어느 쪽이 이기는지가 후보 순서에 달렸다(R0-2 재적재 뒤 extended 15건 중 2건 — 00112679 2015Q1 별도 `cf.interest_paid` 19,794,068 ↔ −19,794,068, 00154718 2020FY 별도 `cf.interest_received`; 후보 순서를 뒤집어 재현).
**규칙** (`fin2/layer3/combine._drop_accrual_cash_aliases`): `cf.interest_paid`·`cf.interest_received`(명사 `이자`)·`cf.dividends_received`(명사 `배당`) 후보 중 계정명에 현금 동사(`지급|수취|수령|납부|유입|유출`)와 **그 계정의 명사**가 함께 있는 행이 하나라도 있으면, 나머지(손익 계정명 `이자비용`·`이자수익`·`배당금수익` 등)는 후보에서 뺀다. 그런 행이 없으면(직접법 K-GAAP 표) 그대로 둔다. ★초판은 `cf.dividends_paid` 도 넣고 명사 조건이 없어, 배당 후보로 잘못 잡혀 있던 `재무활동으로 분류된 이자지급`(00223434 2025FY −5,120,278,275)이 다른 후보를 밀어내고 배당 지급으로 확정됐다 — 전사 재빌드 비교에서 발견, 명사 조건 추가·`cf.dividends_paid` 제외.

## R234. BS 자산마다 붙은 **차감 계정 행**은 같은 표 안에서 합산해 총액으로 쓴다 (2026-10-11, 사용자 결정, 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**근거**: 로젠 2018 사업보고서 `20190401002764` 연결재무상태표 유형자산 — `건물 / 감가상각누계액 / 구축물 / 감가상각누계액 / 기계장치 / 감가상각누계액 …` 처럼 자산마다 바로 아래 차감 계정을 한 줄씩 둔다. 사용자 판독(2026-10-11): "토지·건물의 감가상각누계액, 구축물의 감가상각누계액 … 으로 해석되어야 하고, 평가충당금·대손충당금도 같은 방식 — 합산해서 적재". 계층3 병합(`build_merged_lines`)은 (statement, basis, 열, section_path, 계정명) 이 같은 셀을 하나로 보고 첫 행만 남겨, 차감 계정 canonical 에 첫 자산 몫만 담겼고(−5,235,758,293, 7행 합 −47,665,605,633) 고른 행이 적재 순서를 따랐다(R0-2 재적재 뒤 extended 15건 중 13건의 원인).
**측정**(2015+, 값이 다른 같은 키): 감가상각누계액 5,081키/3,007필링 · 대손충당금 3,291/1,920 · 평가충당금 1,863/1,170 · 정부보조금 1,281/777 · 손상차손누계액 432 · 현재가치할인차금 278 · 평가손실충당금 155 · 손실충당금 83 · 국고보조금 61 · 상각누계액 50.
**규칙** (`fin2/layer3/combine._sum_contra_rows`, 필링마다 병합 전에): BS, 공백·괄호를 뺀 계정명이 위 차감 계정명과 정확히 같고, (basis, 열, section_path, 계정명, **table_seq**) 가 같은 행이 둘 이상이면 한 셀로 합산한다. 같은 표 안에서만(같은 BS 가 두 번 실린 필링에서 이중 합산 방지), **부호가 한쪽일 때만**(양·음이 섞인 17키는 부호 문제라 종전대로). 그 밖의 계정명의 같은 키 행은 종전대로 첫 행.
**소급 결과(R233·R234, 2026-10-11)**: 계층3 전사 재빌드 2,528개사(2015+) + R233 수정 뒤 628개사, 사본 `r234_std_before`·`r234_ext_before`. std 컬럼 변화 0(초판 R233 이 만든 `dividends_paid` 2행은 수정 후 원복). extended — `bs.accumulated_depreciation` 값 4,121(4,062 = 같은 부호로 커짐, 합산) · 보류 59(유형자산 합계와 투자부동산 감가상각누계액이 다른 후보로 충돌, 예 00186559 2016FY −9,210,870,577 / −1,136,046,681; 종전 값은 유형자산 한 행) · `cf.interest_paid` 값 4,898 · 부호 1,984 · 채워짐 1,027 · 보류 18 · `cf.interest_received` 값 4,622 · 부호 1,374 · 채워짐 1,093 · 보류 1 · `cf.dividends_received` 부호 541 · 값 23 · 채워짐 49. 표본 00624998 2015FY 별도 `cf.interest_received` 50,000,000(조정 구간 이자수익) → 324,303,288(이자의 수령).

### R232-c. 증명된 유출 구간의 하위 항목은 **−|값|** (구간 이름 = 유출) (2026-10-11, 사용자 결정)

R232 초판은 구간 전체에 −1 을 곱해, 괄호로 인쇄된 하위 항목(크기 관례 표 안의 음수)을 **양수**로 만들었다 — "유출의 차감"으로 본 것. 사용자 판독(일진홀딩스 2015.03 `20150515002674`): 배당금의 지급 (2,298,867,380) 은 실제로 나간 돈이고, 회사가 괄호 친 배당을 그대로 빼서 소계 (185,625,848,252) 를 낸 원문 계산 실수다(부호를 뺀 합 190,223,583,012 — 비교 열들은 부호를 뺀 합이 소계와 같다). "계층3 에서는 소계 항목명에 맞춰 부호를 맞춘다 — 유출은 −".
**변경**: 범위(크기 관례 증명 구간)는 그대로, 변환만 **하위 항목·소계 모두 −|값|**. 원문이 이미 음수인 셀은 바뀌지 않는다. 음수→양수 8행(일진홀딩스·아주IB투자 연결/별도·하이록코리아·아이디스홀딩스·우리산업홀딩스 2022/2023·HC홈센타)은 인쇄값(음수)으로 돌아간다. 증명 없는 구간은 사용자 결정으로 계속 손대지 않는다.

## R235. CF **배당금 지급**은 성질상 유출 — 계층3 에서 −|값| (2026-10-11, 사용자 결정, 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**근거**: R232 뒤에도 std `dividends_paid` 2015+ 양수 808행. 출처 계정명 분류: `배당금(의) 지급` 류 769 · 오타 `배당금의지금`(00684802) 12 — 유출 구간이 없는 양식에서 괄호 없이 인쇄된 배당 지급. 사용자: "유출은 −, 유입은 + 로 계층3 로 옮길 때 판단" (R221 비용 양수 관례와 같은 성질 기준).
**규칙** (`fin2/layer3/combine._sign_dividends_paid`): `cf.dividends_paid` 후보 중 공백을 뺀 계정명에 `배당` 과 `지급|지불|지금` 이 있는 행은 값을 −|값| 으로 바꾼다(후보 dict 를 복사해 바꿈). 계정명이 배당 지급이 아닌 후보(오매핑: `배당금수취` 4 · `재무활동으로 분류된 차입금` 11 · `이자지급` 3 · `주식의 발행` 1 · 기타)는 손대지 않는다 — 부호가 아니라 매핑 문제라 별도 과제.
**소급 결과(R232-c·R235, 2026-10-11)**: R232 백필 재실행(2015+ 13,470필링) — 음수→양수 보정 137셀 제거, 98,233셀/6,496필링. 계층3 재빌드 R232 529개사 + R235 212개사. std `dividends_paid` 2015+ 양수 808 → **13**(남은 13 = 오매핑: `재무활동으로 분류된 차입금` 10 · `재무활동으로 분류된 이자지급` 3), 바뀐 795행은 전부 부호만(값·다른 컬럼 변화 0), 일진홀딩스 등 8행은 인쇄값(음수)으로 복귀. 참고: 00667373 2024Q1 은 정정본이 같은 금액 행을 `배당금지급`→`주식의 발행` 으로 고쳤는데 병합 키가 계정명이라 원본 셀이 남아 배당 지급으로 쓰인다(별도 과제).

## R236. CF 계정명 앞의 **"(영업|투자|재무)활동으로 분류된"** 한정어는 떼고 매핑한다 — 뗀 나머지는 정확·정규화 일치만 (2026-10-11, 사용자 지시 "매핑 문제 확인", 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**근거**: R235 뒤 std `dividends_paid` 양수 13행이 전부 오매핑 — `재무활동으로 분류된 차입금`(10)·`재무활동으로 분류된 이자지급`(3). 별칭 `재무활동으로분류된배당금지급`(2026-07-18 승급) 과 접두 `재무활동으로분류된` 을 길게 공유해 퍼지(Jaro-Winkler) 점수가 0.91~0.93 → `cf.dividends_paid`. 같은 원인으로 `투자활동으로 분류된 이자수취`·`…기타 장기성 자산의 취득` 등이 `cf.capex` 로, `영업활동으로 분류된 이자수취/이자지급`(825행)은 매핑 안 됨.
**규칙** (`fin2/layer3/combine._map_label`): CF 에서 계정명이 그 한정어로 시작하면 ① 떼어 낸 나머지(그리고 꼬리 `…으로 인한 현금유입/유출(액)` 까지 뗀 것)가 **정확·정규화 일치**면 그것을 쓰고, ② 아니면 전체 계정명으로 종전처럼 매핑하되 **퍼지 매칭의 별칭이 그 한정어로 시작하면**(점수가 한정어에서 나온 것) 버린다. 뗀 나머지로 퍼지를 허용하면 `선수금의 증가(감소)`→`cf.net_change_in_cash` 같은 새 오매핑이, 정확 일치만 허용하면 `영업활동으로 분류된 법인세납부(환급)`(458행)→`cf.tax_paid` 같은 정상 퍼지가 사라진다(둘 다 측정으로 기각).
**측정**(2015+ CF, 한정어 계정명 135종): 매핑이 바뀌는 13종 1,253행, 전부 개선 — 이자수취/지급 `cf.interest_*` 로 842행(신규)·`투자활동으로 분류된 이자수취` capex→`cf.interest_received` 43·`재무활동으로 분류된 이자지급` dividends_paid→`cf.interest_paid` 61, `유형자산의 처분` capex→`cf.ppe_proceeds` 88, 오매핑 해제(무매핑): `무형자산의 처분` capex_intangible(처분이 취득으로) 172·`재무활동으로 분류된 차입금` dividends_paid 21·`기타 장기성 자산의 취득`/`금융상품의 취득`/`종속기업 투자자산의 취득`/`기타자산의 감소` capex 25·`보증금 증가` dividends_paid 1.
**소급 결과(R236, 2026-10-11)**: 한정어 계정명을 가진 665개사 2015+ 재빌드. std `dividends_paid` 양수 13 → **0**(오매핑 13 해제) · 음수였던 20행도 NULL(전부 `재무활동으로 분류된 이자지급`이 배당 지급으로 들어가 있던 값) · `capex` 12(오매핑 후보 해제 — 00225159 2025FY −10,470,000 → −10,540,557,298, 00109514 2025Q3 금융상품 취득 −900,000,000 → NULL) · `borrowings_*` 4 · 그 밖의 std 컬럼 0. extended CF: `cf.interest_received` +414 · `cf.interest_paid` +340/값 62 · `cf.ppe_proceeds` +87 · `cf.capex_intangible` −12 등.

## R237. 정정본에서 **같은 위치·같은 금액** 셀의 계정명이 바뀌면 그 셀이 최초본 셀을 대체한다 — 계층3 병합만 (2026-10-11, 사용자 승인, 적용 계층: 3)

> **상태** 유효 · **적용 계층** 3

**근거**: 00667373 2024Q1 — 최초본 `20240522000014` 연결 CF 23행 `배당금지급 36,762,530,400` 을 다음 날 정정본 `20240523000228` 이 같은 행·같은 금액으로 `주식의 발행` 으로 고쳤다. 정본 병합(`build_merged_lines`, 최초본 + 순차 델타 패치)은 셀을 (statement, basis, 열, section_path, **계정명**) 으로 맞추므로 정정 셀은 "추가"로 들어가고 최초본 셀이 고쳐지지 않은 채 남아 배당 지급과 주식 발행에 같은 금액이 함께 잡혔다(R2 "정정이 이긴다" 가 계정명 정정에는 안 걸림).
**측정**(2015+, 최초본·정정본 같은 (statement, basis, table_seq, row_order), 같은 0 아닌 금액, 공백 뺀 계정명 다름): 14,026셀. 같은 계정으로 매핑(표기 차이) 11,919 · 계정이 바뀜 868 · 무매핑→매핑 642 · 매핑→무매핑 597 — 계정 영향 2,107셀/정정본 710건. 예: 00475985 2017Q3 `기타금융자산`→`기타유동/비유동금융자산`, 00140061 2016FY `법인세의 수취`→`법인세의 납부`, 00126937 2023FY `당기순이익`→`계속영업당기순이익`.
**규칙** (`fin2/layer3/combine.build_merged_lines` + `_relabelled_cell`): 나중 필링(같은 추출 경로)의 셀이 기존 키에 없고, 앞선 필링 셀 중 같은 (statement, basis, 열, table_seq, row_order) 이며 값이 같은 셀이 있으면 그 셀을 지우고 정정본 셀로 대체한다(정정 표시 amended). **대체하지 않는 경우**(재빌드 비교에서 하나씩 발견):
- 새 계정명이 어느 계정에도 매핑되지 않음 — 00126937 2023FY `당기순이익`→`계속영업당기순이익`: 대체하면 순이익 후보가 사라져 비지배지분 546억이 순이익이 됐다.
- 새 계정명의 계정이 같은 필링·같은 범위에 **다른 금액으로 이미 있음** = 정정본 자체의 오인쇄 — 00528791 2025FY 3차 정정본이 `자산총계` 자리에 `자본총계 (E=C+D)` 를 찍고 44행에 진짜 `자본총계 (D)` 가 따로 있다(대체하면 총자산 NULL).
- 공백·줄바꿈·전각/반각만 다름(표기 차이) — 00260611 2024H1 `…반기순이익\n(손실)`→`…반기순이익（손실）`: 전각 괄호 계정명이 퍼지로 순이익에 잡혀 지배지분 순이익이 비었다. (매퍼 전체에서 전각을 반각으로 바꾸는 안은 측정 결과 `２．투자활동으로 인한 현금유출액`→투자활동 합계 등 새 오매핑이 생겨 기각.)
**계층2·보정 무변경**: `report_lines`·`layer3_cell_corrections` 를 바꾸지 않고 병합 메모리에서만 판단한다 — 필링 단위로는 두 셀 모두 자기 원문과 같으므로 verify machine·verify(필링별 `report_lines`/`report_lines_l3` 대조)에는 영향이 없다. 최초본 셀을 drop 보정으로 넣는 구현은 그 필링의 `report_lines_l3` 항등식을 깨므로 쓰지 않는다(사용자 확인 2026-10-11).
**소급 결과(R237, 2026-10-11)**: 계정명이 바뀐 정정본이 있는 627개사 2015+ 재빌드(행 수 불변 51,748). 핵심 값 변화 3행 — 00119140 2023Q3 별도 순이익 +3,422,840,792 → −3,422,840,792(정정본 `분기순손실`), 00573269 2022H1 연결 순이익 456,478,107 → −1,843,485,162(최초본이 기타포괄손익 행을 `반기순이익(손실)` 로 찍었고 정정본이 바로잡음; 지배 −987,284,576 + 비지배 −856,200,586 와 일치), 00527464 2018FY 연결 지배지분 순이익 NULL → 3,628,292,184(정정본 인쇄값 — 정정본 자체가 지배+비지배≠순이익이라 최초본 3,632,490,364 가 맞아 보이나 R2 정정 우선). 그 밖 std: EBITDA·D&A 33 · net_debt 12 · borrowings_repaid 9 · ebt 3 · dividends_paid 2(00667373 2024Q1 −36,762,530,400 → NULL, `cf.equity_issuance` 36,762,530,400) 등. extended 추가 34 · 삭제 142 · 값 85.
Gate B(41개사 재감사·저장, 사본 비교): fail_b→pass 1(00573269 2022H1 net_income), 새 실패 0, pass→pending 31 은 전부 `LABEL_UNMATCHED`(줄 단위 계정명 대조)이고 R237 로 std 가 바뀐 행이 아님 — 10-08 이후 계층2 재적재(R0-2·웹뷰 `<BR>`)가 대장에 반영된 것. verify machine·verify 는 필링별 `report_lines`/`report_lines_l3` 만 보므로 영향 없음(계층2·보정 무변경).
**회귀 테스트**: `fin2/tests/test_r237_amendment_relabel.py`(R171 테스트 행에 row_order 추가).


## R218-b. 계층3 은 **|값| ≥ 1,000,000 인 EPS 후보를 버린다** — 절 제목 행에 실린 순이익·포괄이익 (2026-10-04)

> **상태** 유효 · **적용 계층** 3 · 2026-10-12 R218(계층2) 절 안의 하위 절이던 것을 계층3 으로 옮김(내용 그대로)

**발견(2015+ 전수, `extended_facts_v3` `is.eps_*` |값| ≥ 1,000,000 은 2건뿐)**
- DB증권 2016Q1 별도 `is.eps_basic` 280,029,785. 원문의 절 제목 행 `주당손익` 이 `분기총포괄이익` 280,029,785 를 같은 값으로 싣고 있다(`IS_S/주당손익`, 일반 매퍼가 EPS 로 연결). 진짜 EPS 는 `기본및희석주당순이익` 13(별도)·28(연결)이다.
- 멀티캠퍼스 2018Q1 연결 `is.eps_basic` 5,890,065. 절 제목 `지배회사 소유주 지분에 대한 주당이익`(`eps/…`) 행의 금액이다. 진짜 EPS 는 같은 필링의 `기본주당이익` 458 이다.
- 같은 범위의 삼부토건 2016 EPS 419,850·491,392 는 원문 값이다(가중평균주식수 1,218,754). 정상이다.

**규칙** (`fin2/layer3/combine._map_rows::_add`): 후보가 `is.eps_basic`/`is.eps_diluted` 이고 |값| ≥ `_EPS_MAX_PER_SHARE_WON`(1,000,000) 이면 후보로 올리지 않는다. R216·R217 과 같은 상한이며, 상장사 주당 금액이 100만원에 닿은 사례는 없다.
**회귀 테스트**: `fin2/tests/test_r218_eps_doubled_cell_split.py::test_layer3_drops_per_share_candidates_of_one_million_or_more`.
**소급**: 자동 아님. 2015+ 대상 2건(DB증권 00115694, 멀티캠퍼스 00425351)만 std_v3·달력 재빌드(`--year-min 1990` 아님, 해당 연도 포함하면 충분)한다.

**소급 결과(2026-10-04)**: DB증권·멀티캠퍼스 2개사 std_v3(`--year-min 2015`, 184행)·달력(385행)을 재빌드했다. DB증권 2016Q1 EPS 연결 28·별도 13, 멀티캠퍼스 2018Q1 연결 458·별도 431 로 원문 EPS 와 일치한다. 2015+ `is.eps_*` |값| ≥ 1,000,000 은 0건이다.