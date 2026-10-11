# 검증 — 데이터를 쓰지 않고 판정만 하는 규칙

> 이 파일은 `docs/PARSING_RULES.md` 에서 **내용을 바꾸지 않고 옮긴** 절들이다(2026-10-12, `scripts/split_parsing_rules.py`). 규칙 번호·본문은 그대로이고, 분류 기준은 [판정 순서](../plans/parsing_rules_split_2026-10-11.md#분류-기준--판정-순서-사용자-확정-2026-10-11). 새 규칙도 같은 판정 순서로 파일을 고르고 머리에 `적용 계층:` 을 적는다.
> 규칙 문서 수정은 **main 과 camp_err_review 에서만** 한다(사용자 결정 2026-10-11).

Gate B·face_audit·verify(기계대조·모델 검증)·감사 스크립트.

---

## R22. Gate B `face_audit.py` — `is.cogs` vs `report_won` **개념 자체가 다른** 4개사는

> **상태** 유효 · **적용 계층** 검증
curated pending 예외처리(R21 §3 후속, 사용자 결정 2026-08-15 옵션 a)

R21 §3이 확인한 문제: 19개사 중 4개사(00108940 대성홀딩스·00117212 두산·00143527·00163673
한진중공업홀딩스)는 XBRL `ifrs-full_CostOfSales`가 순수 COGS가 아니라 **COGS+SGA 결합
총계**에 태깅돼 있다. `is.cogs`(std)를 아무리 정확히 계산해도(순수 COGS) Gate B의
`report_won`(결합 총계)과 구조적으로 못 맞는다 — std_v3 데이터 버그가 아니라 **비교
개념 자체가 다른** 케이스.

**세 옵션 중 (a) 채택**(사용자 결정): (b) `is.cogs`+`is.sga` 합을 report_won과 비교하는
로직 추가는 4개사 중 두산(00117212) 1개사만 SGA XBRL개념(`dart_TotalSellingGeneral
AdministrativeExpenses`)이 태깅돼 적용 가능하고 나머지 3개사는 그 개념 자체가 없어
채택 안 함. (c) 방치는 매 전수재검증마다 14건이 계속 "확인 필요" 신호로 재부상해 반복
조사 비용이 남음. (a)는 `face_audit.py`에 이미 있는 `_PENDING_REASONS` 패턴
(`COMPARATIVE_ROW`/`SOURCE_NOT_TRACK_A`/`LABEL_UNMATCHED`/`GAPFILL_UNVERIFIED`)을 그대로
재사용 — 4개사 전부 균일 적용 가능하며 std_v3 데이터/파이프라인은 전혀 건드리지 않는다
(Gate B 감사 레이어 국한).

**구현**: `fin2/audit/face_audit.py`에 새 pending 사유 `"COGS_SGA_CONCEPT_MISMATCH"`을
`_PENDING_REASONS`에 등재 + curated 4-튜플 키집합 `_COGS_CONCEPT_MISMATCH_KEYS`
(`(corp_code, fiscal_year, fiscal_period, basis)`, 14개 — R16~R21 override와 같은
원칙, 블랭킷 금지) + `audit_fields()`에서 `canon=="is.cogs"`이고 현재 행 키가 그
집합에 있으면 정상 대조를 건너뛰고 즉시 pending 처리하는 분기.

**Phase 3 착수 중 부수발견(중요)**: 이 14건을 원문대조로 확정하는 과정에서 R21의
`_cogs_additive_labels()` 라벨충돌 실버그를 발견·수정했다(위 "R21 부기" 참고) — pending
예외처리 전에 반드시 먼저 고쳐야 했다(안 그러면 진짜 데이터버그를 "어쩔 수 없는 개념
불일치"로 위장할 뻔했다).

**검증**: pytest 515 passed(무관 기존 실패 1건 제외) + 4개사 scoped Gate B 재검증
(`gateb_audit.py --source v3 --corp-file <4개사> --recheck`) — cogs fail_a **14→0**
(전부 pending 전환, `pending_detail`에 `COGS_SGA_CONCEPT_MISMATCH` 확인) + 이 4개사의
fail_a(총) 0(비관련 필드 회귀 없음) + fail_b(Track B, 64건 — R21에서 이미 문서화된
별개 이슈, 불변) 확인.

**근거**: `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md` Phase 3 ·
`scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py` · `fin2/audit/face_audit.py`
(`_COGS_CONCEPT_MISMATCH_KEYS`/`_PENDING_REASONS`/`audit_fields()`).

---

## R23. `fin2/taxonomy/concept_map.py` — `bs.trade_payables` concept_map 갭 5종 추가

> **상태** 유효 · **적용 계층** 검증
(Gate B 리더 전용, std_v3 무관) + 우연일치 가드 1건

전수스캔(`gateb-reader-concept-gap-scan-2026-08-15` 메모리, `scripts/probe_gateb_reader_
concept_gap_2026-08-15.py`)이 확정한 `trade_payables` fail_a 148/167건의 원인: Gate B
감사기(`fin2/audit/face_audit.py`)가 원문 XML을 재파싱할 때 쓰는 `concept_map.py`에 그
회사가 실제로 쓰는 ACODE 5종이 아예 등록돼 있지 않아, 후보 자체가 없거나 엉뚱한 값으로
좁혀졌다(std_v3 데이터 버그 아님).

**범위 확정(구현 전 재조사, 중요)**: 원설계 메모는 이 파일이 "Gate B 리더 전용, std_v3
무관"이라 적었는데, 세션 시작 시 `fin2/extract/xbrl.py`가 실제 프로덕션 Track A
추출기(E-레이어)라는 사실을 발견하고 한 차례 "std_v3에도 영향" 으로 재평가했다가,
`fin2/layer3/combine.py`(std_v3/`std_financials_v3`를 실제로 만드는 코드)를 추적한 결과
`report_lines`(계층2 텍스트)만 읽고 `fact_v2`/`concept_map.py`는 전혀 참조하지 않음을
확인 — 원설계의 "저위험" 판단이 맞았다(`fin2.layer3.build.build_corp`도
`scripts/build_std_v3.py`에서만 호출, 데일리 미배선). `fin2/standardize/build.py`
(std_financials_v2)는 `fact_v2.canonical_account`를 읽지만 이건 뷰 스왑(2026-08-09) 이후
아무도 안 읽는 레거시 경로라 무관.

**구현**: `fin2/taxonomy/concept_map.py`의 `_BS`에 5개 ACODE 추가, 전부 `bs.trade_payables`:
`ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers`(66)·
`ifrs-full_TradeAndOtherPayablesToTradeSuppliers`(51)·`dart_ShortTermOtherPayables`(13)·
`dart_LongTermTradeAndOtherNonCurrentPayables`(11)·`ifrs-full_NoncurrentPayables`(6).
비유동 개념 2종도 포함하지만 std_v3의 `_CURRENT_STRICT`(R15)와는 무관한 별도 코드경로라
문제 없음 — Gate B(`audit_fields()`)는 `val in won_vals`(집합 멤버십) 판정이라 후보 추가는
원칙적으로 단조 개선(기존 PASS를 FAIL로 되돌릴 수 없음).
`ifrs-full_CurrentTaxAssets`(1건, 아이텍)는 의미상 매입채무와 무관해 매핑하지 않음.

**부수발견·가드**: 매핑 직후 31개사 scoped 재검증에서 아이텍(00626011) 2025FY separate
1건이 **가짜 PASS**로 바뀌는 걸 발견 — 이 행은 std_v3 자체에 진짜 버그가 있다
(`trade_payables=0` 저장, 원문은 5,068,265,299원, `ifrs-full_TradeAndOtherCurrentPayables`
separate 라인). 새로 매핑한 `ifrs-full_NoncurrentPayables`가 이 필링에서 우연히 값=0(비유동
매입채무 없음, 정상)이라 `won_vals`에 0이 섞여 `db_won=0`과 우연일치 — 수정 전엔 정확히
fail_a로 잡히던 진짜 버그가 가려질 뻔했다. `face_audit.py`에 curated 4-튜플 제외집합
`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`(R16~R22와 같은 원칙, 이 1건만) 추가 —
`audit_fields()`가 이 행에서만 값=0 후보를 후보집합에서 제거해 기존 fail_a 노출을 보존.
148행 중 `db_won==0`인 유일 케이스(전수 확인, 나머지 147건 무관).

**검증**: pytest 31 passed(`test_concept_map.py`+`test_face_audit.py`) + 31개사 scoped
Gate B 재검증(`gateb_audit.py --source v3 --corp-file <31개사> --recheck`, 가드 전/후 2회) —
trade_payables fail_a 148건 중 147건 해소(가드 대상 1건은 fail_a 유지 확인, DB 직접 조회로
`fail_detail` 재현), 남은 fail_a 3건은 전부 이 fix와 무관(00149354 separate 2건=원래
scope 밖, 00349732 FY2024=원래 UNRESOLVED 별개 이슈) — 회귀 없음. `dart_ShortTermOther
Payables`/`LongTermTradeAndOtherNonCurrentPayables` 표본(딥노이드·지앤비에스에코·
한국정보인증) pass 전환 개별 확인.

**근거**: 메모리 `gateb-reader-concept-gap-scan-2026-08-15` · `scripts/probe_gateb_reader_
concept_gap_2026-08-15.py`(결과 CSV 포함) · `fin2/taxonomy/concept_map.py` ·
`fin2/audit/face_audit.py`(`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`).

---

## R25. Gate B `face_audit.py::_ni_attribution_structural_candidates()` — `is.controlling_ni`/

> **상태** 유효 · **적용 계층** 검증
`is.noncontrolling_ni` 구조기반 후보보강, raw XML 독립 재구현(R24 의 발상을 Gate B 쪽에 이식)

R24(std_v3 쪽)와 **같은 근본원인**이 원문을 직접 읽는 Gate B 리더에도 독립적으로 있었다
(`gateb-controlling-ni-new30-rootcause-2026-08-15` 메모리 §1-B): 일부 필터社가 지배/비지배
귀속 행에 회사고유 확장 ACODE(`entity{corp}_...`)를 쓰고, 표준 `ifrs-full_`/`dart_` ACODE는
총포괄손익 귀속 절·SCE·EPS 행에 오태깅해놓는다. `read_report_face_xbrl()`의
`_XBRL_PREFIXES` 필터가 확장 ACODE를 애초에 후보 풀에서 배제하므로 정답 후보 자체가
없다 — std_v3 데이터(db_won)는 항상 정답이었고, Gate B(report_won)가 오답이었다.

**구현**: `fin2/layer3/combine.py::_ni_attribution_structural_candidates()`(R24)를
모듈 재사용이 아니라(face_audit 의 파이프라인 독립성 원칙, 모듈 docstring) **raw XML
TR 시퀀스 위에 독립 재구현**. `read_report_face_xbrl()`이 만든 `FaceLine` 리스트 끝에
후보만 추가(대체 아님 — `audit_fields()`의 PASS 판정이 "후보 집합에 db_won 있으면 PASS"
라 넓히기만 해도 충분, 단조 개선). 상태기계:
1. **앵커(섹션 시작)**: 아직 섹션 밖일 때, TR 라벨이 `^당?(기|분기|반기)순(이익|손익)`로
   **시작**하면(예: `당기순이익(손실)`·`분기순이익(손실)의귀속`·`반기순손익`·
   `당분기순손익` — 필터社마다 표현이 갈림, 코렌텍은 분기별로도 다르게 씀) 그 행(헤더든
   실값행이든)을 앵커로 섹션 진입. `법인세비용차감전순이익(손실)`(세전이익, 뒤에 귀속
   분해가 안 옴) 같은 상위 소계가 오매칭되지 않도록 접두어 전체일치로 좁힘(느슨한
   부분일치 `순이익|손익` 는 코아시아씨엠 FY 케이스에서 실측 회귀 — 아래 검증 참고).
2. **회원 판정**: 섹션 안에서는 앵커 재판정을 하지 않는다(멤버 행 중 일부가 자체
   서브분해를 가져 `손익` 텍스트만으로는 새 앵커와 구분 안 됨 — 코렌텍의
   `계속영업분기순손익`/`중단영업분기순손익`이 실측 사례). 라벨에 `지배`가 있는 행만
   회원 후보(`비지배` 포함 여부로 controlling/noncontrolling 판정), 값이 없는 라벨행도
   회원으로 카운트(NCI 미태깅 필터社에서 "정확히 1개씩" 판정이 깨지지 않게).
3. **종료**: `비지배` 회원 1개·비`비지배` 회원 1개가 모이는 즉시 종료·후보추출("가장
   가까운 매치"가 곧 정답이라 뒤쪽 무관 표를 안 봄). 안전판으로 `_MAX_SECTION_SPAN`(20행)
   초과 시 강제종료(모양이 안 맞으면 짐작 없이 폐기).

**검증**: 원설계 문서의 24행(7개사: 코아시아씨엠·이노메트리·진영·모비데이즈·유니온·
코렌텍·판타지오) 전수 fail_a → pass 전환(SQL 재확인 잔여 0건). 구현 도중 3차례
실측 회귀 발견+수정(코아시아씨엠·이노메트리·코렌텍 세 회사가 서로 다른 레이아웃 — 상세는
`fin2/audit/face_audit.py::_ni_attribution_structural_candidates` 도크스트링). `pytest
tests/ fin2/tests/` 522 passed(무관 기존 실패 1건 `test_lxintl_facility_table_dropped`
불변). 40개사 무작위표본 회귀검증: fail_a 총량 불변(15=15), controlling_ni 관련 회귀 0건
(내 변경은 이 두 canonical 에만 후보를 추가하는 구조라 다른 필드는 건드릴 수 없음).
`docs/plans/gate_b_facereader_controlling_ni_fix_design_2026-08-15.md` §2-B.

**이번 범위 밖**: 같은 30건 중 ①FX표시통화(두산밥캣 6행)는 별개 메커니즘 — R26(아래)으로
구현 완료. 그룹A mismap 잔여19건(Phase2, std_v3 쪽) 도 무관.

---

## R26. Gate B `face_audit.py` — FX 표시통화(두산밥캣) curated pending 강등, 옵션 B

> **상태** 유효 · **적용 계층** 검증
(2026-08-15)

R25 와 같은 30건 조사 중 발견된 ①FX 표시통화 메커니즘(설계문서 §1-A). 두산밥캣
(01032486) **연결**재무제표만 표시통화가 USD 다(원문 각주: "지배기업의 기능통화는
대한민국 원화이며, 연결재무제표는 달러(USD)로 표시"). Track A(XBRL)는 ADECIMAL 로
단위만 환산하고 통화는 검사하지 않아 USD 원값을 그대로 원화로 취급 → `report_won` 이
그 필링의 **전 필드**(22개 전부)에서 구조적으로 어긋난다. `std_v3`(db_won)은 DART 가
USD 표시 필터社에 요구하는 필수 별첨 "원화기준 재무정보"(서울외국환중개 매매기준율
환산표, 비XBRL 참고표)를 정확히 읽어와 이미 원문대조로 확인됐다(6/6행 백만원 단위까지
일치, 설계문서 §1-A).

**전수 스캔**(NAS+SD카드 dart_data 양쪽 독립·교차검증): "원화기준 재무정보" 계열 문자열
매치 5개사 중 4개사(딥커머스·씨엑스아이·JTC·소마젠)는 `corporations`/`face_audit` 자체에
행이 없는 유니버스 밖 외국기업([[foreign-corps-excluded]] 대상) — Gate B 영향 0.
실제 대상은 **두산밥캣 1개사·연결 6행뿐**(2024FY·2025FY·2025H1·2025Q1·2025Q3·2026Q1).

**구현(옵션 B, 저비용 pending 강등)**: 두산밥캣 1개사·6행이라는 규모(옵션 A "Track D
신설"의 투자 대비 회수가 작다는 판단, 설계문서 §2-A)로 인해 curated key 세트를
`fin2/audit/face_audit.py::_FX_PRESENTATION_CURRENCY_KEYS`(4-튜플
`(corp_code, fiscal_year, fiscal_period, basis)`, R21/R23 와 같은 원칙 — 블랭킷 규칙
금지)로 등록. `audit_std_row()`가 이 키와 일치하는 행을 만나면 정상 face 대조를 아예
건너뛰고 그 행의 전 필드를 새 pending 사유 `FX_PRESENTATION_CURRENCY`로 표시(값 오류
감사가 아니라 통화가 달라 비교 자체가 성립하지 않는 케이스, `_PENDING_REASONS`에 등록).
별도(개별) 재무제표는 원화 그대로라 `basis='consolidated'` 행만 대상 — 별도 재무제표
행은 이 키에 안 걸려 기존 로직 그대로 감사된다.

**검증**: `python scripts/gateb_audit.py --source v3 --corp 01032486 --recheck` 재감사
결과 대상 6행 전부 `gate_status=pending`·`pending_detail={'FX_PRESENTATION_CURRENCY': N}`
로 전환(N=그 행의 in-scope 필드 수), 두산밥캣 전체 fail_a 6→0(`fail 0`). 같은 회사의
별도(separate) 재무제표 행·다른 기간 연결 행은 영향 없음(기존 pass/pending 그대로 —
curated key 는 정확히 6개 4-튜플만 매치하므로 다른 corp·행에는 원천적으로 도달 불가).
`pytest tests/ fin2/tests/` 522 passed(무관 기존 실패 1건 `test_lxintl_facility_table_
dropped` 불변, R25 와 동일). `docs/plans/gate_b_facereader_controlling_ni_fix_design_
2026-08-15.md` §2-A.

---

## R32. Gate B — 업종 프로파일 파생 `revenue` 검증 (증권/은행/보험/여신전문, 2026-08-17)

> **상태** 유효 · **적용 계층** 검증

설계 `docs/plans/gateb_industry_derived_revenue_design_2026-08-17.md`, census
`docs/qa/industry_profile_component_census_2026-08-17.md`.

**배경**: `fin2/layer3/industry_profiles.py::compose()`가 증권/은행/보험/여신전문 4개
업종의 `revenue`를 성분 합성으로 만든다(예: 증권 순영업수익 = 영업이익+판관비). Gate B
감사기(`face_audit.py`)는 "원문에 그 값이 단일 라인으로 있는가"만 보는데, 파생값은 정의상
그렇게 존재하지 않아 **전부 fail** 처리되고 있었다 — Gate B 전체 fail 의 81%(2,721/3,348)가
이 노이즈였다(census §1-A).

**해결**: 면제가 아니라 **파생 검증**. `std_financials_v3.industry_lines`(JSONB)에 계층3이
남긴 성분(예: `{"profile":"securities","operating_income":..,"sga":..}`)을 읽어, 그 성분들이
원문 face 에 실재하는지 확인하고 재합산해 std 값과 대조한다. 성분 하나라도 못 찾으면
`DERIVED_COMPONENTS_UNVERIFIED`(pending, fail 아님) — 재계산이 std 값과 다르면 그대로
`VALUE_DIFF`(fail 유지, 면제로 퇴화하지 않음).

**성분 → canonical 매핑**(Phase 0 census 46개사 실측으로 확정, 짐작 없음):

| 성분 | Track A(XBRL concept_map) | Track B(텍스트) |
|---|---|---|
| `operating_income` | 기존(`dart_OperatingIncomeLoss`) | 기존(`is.operating_income`) |
| `sga` | **신규** `ifrs-full_SellingGeneralAndAdministrativeExpense` | 기존(`is.sga`) |
| `interest_revenue` | 기존(`ifrs-full_RevenueFromInterest`) | 없음 → raw value 우회 |
| `fee_revenue` | **신규** `ifrs-full_FeeAndCommissionIncome` | 없음 → raw value 우회 |
| `insurance_revenue` | 기존 + `is.operating_revenue_ins`(재매핑 안 함, 둘 다 인정) | 없음 → raw value 우회 |
| `other_op_revenue` | **신규** `dart_OtherOperatingIncome`/`ifrs-full_MiscellaneousOtherOperatingIncome` | 없음 → raw value 우회 |
| `investment_revenue` | **신규** `ifrs-full_InvestmentIncome` | 없음 → raw value 우회 |

**★교훈(실제 사고, 구현 도중 발견)**: `fee_revenue`/`interest_revenue`/`insurance_revenue`/
`other_op_revenue`/`investment_revenue` 5종 전부 Track B 에 **새 canonical 을 신설하지
않는다.** 처음엔 "기타영업수익"/"투자영업수익"을 `account_maps/is_accounts.py`에 새 exact
alias 로 추가했는데(정확일치 충돌은 없다고 확인했음), 46개사 표적 재감사에서 실제 회귀가
났다 — 동양생명(00117267) 2023Q1: "투자영업수익"이 기존 alias "영업수익"의 **부분문자열**
이라 원래 stage-3(fuzzy/포함관계) 매칭으로 `is.revenue` 에 우연히 잡히고 있었는데, 새 exact
alias 가 그 매칭을 가로채 버렸다. **`account_maps/*.py`는 Gate B 전용이 아니라 layer2/3
표준화 본체(`combine.py`/`build.py`)도 쓰는 공용 사전**이라(`concept_map.py`의 XBRL ACODE
사전과 다름 — 그건 R23 으로 이미 Gate B 전용임이 확정돼 있다), exact-alias 충돌이 없어도
fuzzy 매칭 부작용으로 std_v3 실값까지 흔들릴 수 있다. → 다섯 성분은 canonical 없이 **그
행의 face 전체에서 값(won)만 직접 검색**(census 와 동일 기법, `face_audit.py::
_PROFILE_VALUE_FALLBACK_KEYS`)해 우회한다. 회귀는
`test_account_mapper_unchanged_for_fuzzy_matched_revenue_labels`로 고정.

**구현**: `fin2/audit/face_audit.py::_recompute_profile_revenue()` — `audit_fields()`의
`is.revenue` 분기에서 일반경로가 이미 실패한 뒤에만 실행(단조성, 기존 PASS 무영향).
`gross_fallback`(공시 총계를 그대로 쓴 행)은 일반경로로 이미 통과하므로 이 경로를 타지 않음.

**검증**:
- 단위테스트 12개(`fin2/tests/test_face_audit.py`) — PASS/VALUE_DIFF 유지/성분결측 pending/
  gross_fallback 무영향/profile 없는 행 무영향/raw-value 우회/fuzzy 매칭 회귀고정. 전체
  `pytest tests/ fin2/tests/` 557 passed(무관 기존 실패 1건 불변).
- **46개사 표적 재감사**(전·후 스냅샷 대조, `scripts/gateb_r32_snapshot_before_2026-08-17.json`):
  pass 1,580→3,984(+2,404) / fail 2,683→33(fail_a **177→4**, 전부 revenue 무관 기존 결함) /
  pending 2,623→2,869. **단조성 위반 0**(pass→fail/pending 전이 0건, 첫 실행에서 3건 나왔던
  건 위 fuzzy 사고를 고치고 재실행해 0건 확정). 신규 fail_a 0건.
- 원문대조 8개사(profile 4종×2개사, 집계 아닌 손으로 확인): 대신증권·유진증권(securities),
  미래에셋생명·코리안리(insurance), 케이뱅크·BNK금융지주(bank), 삼성카드·메이슨캐피탈
  (credit_finance) — 성분 전부 원문 실재 확인. BNK금융지주는 `other_op_revenue` 성분이
  face 에 없어 정확히 `pending`(허위 PASS 아님, 안전설계 확인).
- R23 교훈검사(우연일치 0값): newly-passed 2,404행 중 revenue=0 인 행 0건, 성분=0 인 행
  1건(유진증권 2017Q1 `operating_income=0`) — 원문에 실제 "Ⅲ.영업이익 0" 라인 존재, 우연
  아닌 진짜 값으로 확인.
- **전수 재감사**(2026-08-18, 사용자 직접 실행 `run_gateb_audit_parallel.sh` 5-shard, ~1.2h,
  `--fy-min 1999`): 299,651행 전량. pass 199,113→**201,518**(+2,405) / fail_a **412→239**
  (신규 0건) / fail_b 3,081→603 / pending 97,045→97,291. **46사 밖 292,765행 산술검산** —
  pass/fail_a/fail_b/pending 4개 항목 전부 이전 기준선과 **정확히 일치**(뺄셈으로 확인,
  트랙 밖 영향 0 확정). 46사 안 fail_a 는 여전히 4건, 전부 revenue 무관(dividends_paid×3
  ·controlling_ni×1, 기존 결함). §2(마스터 문서) 공통게이트 6개 전부 충족, 트랙 완전 종료.

---

## R33. Gate B — 증거강도(축2) 계측 + `fail_a` 승격의 gapfill 예외 1건 (2026-08-18)

> **상태** 유효 · **적용 계층** 검증

설계 `docs/plans/gateb_evidence_grade_redesign_2026-08-17.md`(§6 2026-08-18 개정),
실측 `docs/qa/gateb_evidence_census_2026-08-18.md`.

**축 분리**: Gate B 는 이제 **판정**(`match`/`VALUE_DIFF`/pending)과 **증거강도**(그 판정의
근거)를 분리해 기록한다. `FieldAudit.evidence` + `face_audit.evidence_detail`(JSONB).

| 등급 | 의미 |
|---|---|
| `E1_EXACT` | 원문 face 라인 값과 정확 일치 |
| `E2_SIGN` | 절대값 일치, 부호만 다름(표준화 규약) |
| `E3_ROUNDING` | 표시단위 1단위 이내(발행사 반올림) |
| `E4_IDENTITY` | 회계 항등식으로 재구성해 일치(revenue=cogs+gp / NI=CF대체 / NI=지배+비지배 / R32 업종파생) |
| `E5_HEURISTIC` | 저신뢰 리더 후보(`from_gapfill`)와 일치 |
| `M1_STRONG` | 불일치 — 최근접 후보가 non-gapfill |
| `M2_WEAK` | 불일치 — 최근접 후보가 `from_gapfill` |

**★게이팅은 여전히 리더 트랙(A/B/C) 축이다.** `gate_status_for_row()`가 evidence 축으로
**교체되지 않은 이유**는 전수 census 실측(299,651행)이다:

```
mismatch 필드 1,129건(fail_a 253 + fail_b 876)  →  전부 M1_STRONG, M2_WEAK 0건
pass 필드 4,218,532건  →  E1 99.89% / E4 3,600 / E2 945 / E3 45 / E5 0건
```

`from_gapfill=True` 가 붙는 곳은 `_supplement_with_text()`(`face_audit.py:621`)와 PDF
리더(`:721`) **둘뿐**이다. Track B(텍스트) 리더가 보고서를 **원본으로** 읽은 라인은
`from_gapfill=False` → `M1_STRONG`. 따라서 "M1_STRONG 이면 차단"으로 축을 바꾸면 지금
`fail_b` 603행이 전부 차단으로 흡수돼 **REVIEW 등급이 소멸**한다(설계서 §6 초안의 A/B/C
세 안이 M2·E5 가 0 이라 현재 데이터에서 **전부 같은 결과** — 그 표는 2026-08-18 개정됨).
게다가 §1-A 가 축 교체의 근거로 든 "같은 회사·같은 필드인데 연도에 따라 등급이 뒤집힘"은
트랙①(R32) 이후 **(corp,field) 480쌍 중 1쌍**만 남아 실질 소멸했다.

**채택(A′) — 좁은 봉합 1건**: 축은 track 그대로 두고, 설계서 §1-A 의 **부수결함만** 막는다.
Track A 보고서라도 그 실패 필드의 최근접 후보가 gapfill(`M2_WEAK`)이면 `fail_a` 로 세지
않는다(증거는 휴리스틱인데 등급만 최고신뢰인 모순 제거). `evidence` 가 `None` 인 불일치
(R32 파생 재구성 후 불일치 — 단일 최근접 후보가 없어 M1/M2 판정 자체가 성립 안 함,
`face_audit.py:1106-1108`)는 **보수적으로 기존과 동일하게 차단** 쪽으로 센다.

현재 `M2_WEAK` 가 0건이라 **판정 무변화**다(미래 방어 전용). 실측 확인: 00117212
(fail_b 다수) pass 65/fail_a 0/fail_b 56/pending 57, 00155258(fail_a 최다) pass 102/
fail_a 14/fail_b 0/pending 68 — 둘 다 DB 현재값과 완전 일치.

**전수 재감사(299,651행)로 확정**(2026-08-18): 사전 스냅샷 대비 `gate_status` 전이 행렬
**대각선만**(비대각 0), 판정 6개 항목 행 단위 대조 **변화 0행**, `M2_WEAK`/`E5_HEURISTIC`
둘 다 0. 검증 SQL = `scripts/verify_gateb_aprime_no_change.sql`(재개 트리거 점검도 포함).

**재개 트리거(명문화)**: 다음 전수 재감사에서 아래 중 하나라도 관측되면 게이팅 축 재검토
(설계서 Phase 3)를 재개한다. 계측이 이미 배선돼 있어 자동 감지된다.

```sql
-- ① M2_WEAK 출현 → A′ 예외가 실제로 발동하기 시작 = 축 재검토 신호
SELECT count(*) FROM face_audit fa, LATERAL jsonb_array_elements(fa.fail_detail) f
WHERE fa.source_version='v3' AND f->>'evidence'='M2_WEAK';

-- ② E5_HEURISTIC 출현 → 휴리스틱 근거만으로 통과한 pass 발생 = 설계서 C안 재평가 신호
SELECT count(*) FROM face_audit
WHERE source_version='v3' AND evidence_detail ? 'E5_HEURISTIC';
```

**미결**: `E4_IDENTITY` 3,600건은 4개 서브경로(revenue=cogs+gp / NI=CF대체 / NI=지배+비지배
/ R32 업종파생)가 한 등급으로 뭉쳐 있어 저장값만으로 분해할 수 없다. 설계서 C안("약한
근거 통과를 `pass` 로 인정하지 않음")을 진지하게 평가하려면 E4 세분화가 선행되어야 한다
(부록 C 등재).

관련 코드: `fin2/audit/face_audit.py`(`EVIDENCE_*`·`gate_status_for_row()`·`audit_fields()`),
`scripts/gateb_audit.py`(`evidence_detail` 집계), `collector/models.py`·`collector/db.py`
(마이그레이션 `2026_08_face_audit_evidence_detail`).
회귀: `fin2/tests/test_face_audit.py`(증거등급 9경로 + A′ 분기 6종).

---

## R35. `fin2/audit/face_audit.py` — NI 귀속표 전체가 XBRL 미태깅인 문서에서

> **상태** 유효 · **적용 계층** 검증
`is.controlling_ni`가 감사기 후보 풀에 전혀 안 들어오던 결함(P3-1 '원인 A' 후속)

**증상** — P3-1 재감사 잔여 668건(원인 A, R34 제외분) 중 527건(56개사)이 `LABEL_UNMATCHED`
로 pending. **std_v3 값 자체는 원문과 일치**(케이씨씨 00105271·엘에스일렉트릭 00105855
원문 XML 직접 대조 확인, 값이 CP949 원문 안에 그대로 존재) — std_v3 버그가 아니라 감사기
커버리지 공백.

**근거(실측)** — 두 필링 모두 NI 귀속('...의 귀속') 표 전체가 `<TE ACODE>` 태그 없이 순수
`<TD>`(구형 렌더링)만으로 되어 있다(`root.findall('.//TE[@ACODE]')` 중 `ifrs-full_`/`dart_`
접두 매칭 0건). `_ni_attribution_structural_candidates()`(R24)는 `tr.findall("TE")`를
전제하므로 이런 문서를 통째로 못 본다.

**왜 `account_mapper`(범용 텍스트 매퍼)로 안 고쳤나** — Track B(`read_report_face_text`)가
이미 문서 전체를 제네릭 라벨매퍼로 읽지만, 흔한 축약 라벨 `'지배주주지분'`(6자)이
`'비지배주주지분'`(`is.noncontrolling_ni`)의 **부분문자열**이라 `AccountMapper._fuzzy_match()`
의 포함매칭(`normalized in alias_norm`)이 이걸 비지배로 오귀속한다(실측 유사도 0.977,
`account_maps/bs_accounts.py:296` 이 2026-07-18 에 BS쪽(`bs.controlling_equity`)에서 이미
같은 함정을 겪고 그 alias 를 **의도적으로 빼뒀다** — IS 쪽엔 그 코멘트가 없었을 뿐 같은
공백이 있었다). 라벨 텍스트만으로는 이 짧은 형태를 안전하게 못 구분한다.

**수정** — `fin2/audit/face_audit.py::_ni_attribution_text_candidates()` 신설: R24 TE
자매함수와 **동일한 앵커/섹션 상태기계**(`_NI_TOTAL_RE` 앵커 + 섹션 안 '비지배' 유무로 정확히
한 쌍만 인정)를 쓰되, 라벨 사전 의미가 아니라 **섹션 내 구조적 위치**만 본다 — 그래서 짧은
라벨도 안전하다. 두 안전장치: ① `_detect_body_statement_tables()`(Track B 와 공유하는
본문표 식별)로 IS 본문표에만 스캔 국한(주석 오염 차단, TE 판은 ACONTEXT 존재 자체가
안전장치라 문서 전체를 훑어도 됐지만 태그 없는 TD 는 그 신호가 없다), ② `from_gapfill=True`
(불일치는 GAPFILL_UNVERIFIED/pending 유지, FAIL 승격 금지 — R24/`_supplement_with_text`와
동일한 단조성 계약).

호출 지점 = `read_report_face()`/`read_report_face_tracked()`에서 **Track A/B 확정 이후**
(`_with_ni_attribution_text_fallback()`), `is.controlling_ni`·`is.noncontrolling_ni` **둘
다** 이미 있으면 스킵(비용 절감, 대부분 문서는 태그가 있거나 Track B 제네릭 매퍼가 이미
잡는다). ★ 최초 구현은 이 폴백을 `read_report_face_xbrl()` **내부**에 붙였다가 즉시 회귀를
실측했다: 그 함수의 반환이 "비었는가"가 Track A/B 채택 신호로도 쓰이는데, 완전 미태깅
문서에서 이 폴백만으로 반환이 non-empty 가 되면 원래 Track B 전체(`read_report_face_text`,
from_gapfill=False)로 떨어져야 할 문서가 "Track A(사실상 텅 빈)+`_supplement_with_text`
(from_gapfill=True 로 격하)"로 오분류됐다 — 그 결과 원래 실증거(M1_STRONG)로 잡히던 진짜
값불일치(fail_b, 성도이엔지 등)가 근거강도만 깎여 GAPFILL_UNVERIFIED 나 심하면 가짜 PASS
로 가려졌다(측정 51건 중 34건). 트랙 확정 이후 지점으로 옮겨 해소·재검증(아래).

**검증** — 668건(원인 A 잔여, R34 제외) 재감사(읽기전용 실측, `scripts/
investigate_p3_cause_a_impact_measure.py`): **382건 pass 회복**, 235건 pending(잔여,
SOURCE_NOT_TRACK_A 8개사 등 별개 원인), **51건 fail 그대로**(기존 Group B, 이 수정과
무관 — 정확히 원래의 51건과 일치, 새 fail 0건). `pytest tests/ fin2/tests/` 583 passed
(기존 무관 실패 1건 `test_lxintl_facility_table_dropped` 그대로) — 회귀 없음. 회귀 테스트
= `fin2/tests/test_ni_attribution_text_fallback.py`(3종).

**미조치 범위** — DB(`face_audit`)에 대한 실제 재체크·커밋은 영향받은 74개사로 스코프해
`gateb_audit.py --source v3 --corp-file <74개사> --recheck` 로 반영(전수 재감사는 아직).
잔여 235건 pending 중 다수는 KCC 처럼 NI 귀속 섹션 자체가 실제로는 총포괄손익 귀속 라벨로
잘못 렌더링된 필러 특이 케이스이거나(구조상 안전하게 못 넓힘), 8개사(`SOURCE_NOT_TRACK_A`,
위지윅스튜디오 등)는 필링 전체가 Track A/B 모두 못 읽는 별개 문제(부록C 참고). 51건 fail(Group
B, 카카오게임즈·폴라리스오피스 등 13개사)은 **손대지 않음** — 실제 값불일치 의심으로
회사별 개별 원인규명 필요(R24~R27급).

---

## R36. `fin2/audit/face_audit.py` — `_ni_attribution_text_candidates()`(R35) 열(컬럼)

> **상태** 유효 · **적용 계층** 검증
선택 누락으로 전기/전전기 값이 값불일치 오탐을 낸 결함(P3-1 '원인 A' 그룹② 후속)

**증상** — R35 신설 함수가 잡은 51건/13개사(카카오게임즈·성도이엔지 등)가 `fail`/
`M1_STRONG`로 나왔으나, 51건 전건(53개 필드-기간) 원문 문자열 대조 결과 **std_v3 값이
전부 원문에 실재**(데이터 오류 0건) — 감사기 오탐으로 확정([[p3-1-cause-a-group2-root-cause-2026-08-20]]).
당초 "부모 섹션 구분 없음"(포괄손익/EPS주석/정정비교표와 혼동)으로 가설을 세웠으나,
실제 원문 구조를 직접 대조(카카오게임즈 63개 필링 전건 재추출)한 결과 **가설이 틀렸다** —
실제 원인은 훨씬 기계적이었다.

**근거(실측)** — TD(비XBRL) 표는 ACONTEXT 가 없어 TE 자매함수(`_ni_attribution_
structural_candidates()`, `ctx.col_index != 0` 로 당기만 선택)와 달리 어느 열이 당기인지
구조적으로 모른다. R35 최초 구현은 이 구분 없이 지배/비지배 행의 **모든 값 열**(당기·전기·
전전기, H1/Q3 는 [당기3개월,당기누적,전기3개월,전기누적] 4열)을 전부 후보로 냈다 — 같은
행 안의 전기/전전기(또는 당기3개월, 당기누적과 다름) 값이 엉뚱하게 "값불일치 증거"로 잡힘.
실측: 카카오게임즈 2022 FY 지배주주지분 행 `[(233,641,194,325) 당기 / 528,656,449,171 전기
/ 85,970,818,329 전전기]`— std_v3=`-233,641,194,325`(당기, 첫 열)와 정확히 일치, 나머지
둘은 잘못 섞인 전기/전전기. 성도이엔지 2023H1 지배주주지분 행 `[1,451,210,911 당기3개월 /
**1,296,834,534 당기누적(std_v3 일치)** / 2,501,296,907 전기3개월 / 8,399,952,262
전기누적]` — H1/Q3 는 **첫 열도 아니다**(당기3개월≠당기누적). 카카오게임즈·성도이엔지
63개 필링 전건 재census 결과 51건 fail 전체가 이 매커니즘 하나로 설명됨(cross-table/
cross-section 오염 사례는 0건 관측 — 애초 가설과 달리 섹션 경계 자체는 문제없었다).

**수정** — `fin2.extract.text._interim_cumulative_cols()`(Track B 추출기가 같은 문제를
표 헤더의 '누적' 토큰 위치로 이미 해결해둔 구조 판정 함수)를 재사용해 표 헤더에
`[3개월|누적]` 2단 구조가 있으면 '누적' 토큰이 붙은 첫 컬럼(당기누적)만, 없으면(FY 또는
헤더 미검출) 첫 값 컬럼만 채택 — 결과적으로 라벨당 값 1개(TE 판의 `col_index=0` 채택과
동형)만 후보로 낸다. 이건 값 파싱이 아니라 **표 레이아웃 판정**이라, 이 함수가 이미
공유 중인 `_detect_body_statement_tables()`류와 같은 성격 — 모듈 독립성 원칙("숫자를
어떻게 읽는가")과 충돌하지 않는다(이미 확립된 선례를 그대로 따름).

**검증** — 카카오게임즈·성도이엔지 63개 필링 전건 재추출: 값 충돌(같은 canonical 에 서로
다른 값) 0/63(수정 전 다수). std_v3 대조 341개 필드 중 332개 일치(9개 잔차는 전부
2012~2014 pre-2015 성도이엔지 — R36 적용 전에도 이미 값불일치였던 **별개**·미해결 이슈,
회귀 아님 확인). `--recheck --no-commit` 표본 재감사(200사 랜덤 + fail_fields 에
controlling_ni 잡힌 51개사) — fail_a/fail_b 건수 변화 없음, pending→pass 전환만 관측
(51사 표본: pending 816→807, pass 5131→5140). 회귀 테스트 2종 추가(`fin2/tests/
test_ni_attribution_text_fallback.py`) — FY(첫 열만 채택)·interim(누적 열만 채택) 각각.
`pytest tests/ fin2/tests/` 기존 무관 실패 1건(`test_lxintl_facility_table_dropped`) 외
전부 통과.

---

## R37. `scripts/gateb_audit.py::select_corps()` — Gate B 감사 유니버스가 상장폐지사를

> **상태** 유효 · **적용 계층** 검증
걸러내지 않던 결함(P3-1 '원인 A' 그룹③-a 후속)

**증상** — 위지윅스튜디오(01276327, 2026-08-18 상장폐지 확정)가 전수/범위 재감사에서
여전히 대상으로 잡혀 `SOURCE_NOT_TRACK_A`(pending) 58건을 냈다. std_v3/R35 로직은
버그가 아니다 — ⓪-4 파이프라인이 `raw_report`를 NAS 아카이브로 정상 이관한(의도된 동작,
[[delisting-archive-automated]]) 결과일 뿐인데, 감사 유니버스 쿼리가 이 사실을 몰라
아카이브된 문서를 계속 "감사 대상"으로 붙잡았다.

**수정** — `select_corps()`의 기본/범위(`--corps`) 쿼리에 `corporations.is_active=true`
조인 필터 추가. `--corp`/`--corp-file`(명시적 단일/목록 지정, 조사 목적) 두 분기는 그대로
둔다 — 상장폐지 후 이력도 명시적으로는 여전히 조회 가능. CLAUDE.md 스코프("현재 시점
KOSPI/KOSDAQ 상장된 보통주")에 맞춰 **감사 유니버스에서 아예 제외**(옵션 A, 기존
`face_audit` 이력은 보존 — 신규 재감사 대상에서만 빠짐)로 결정(사용자 확인).

**검증** — 필터 적용 후 기본 유니버스 2,543→2,528사(현재 `is_active=false` 15개사,
1,780행 제외 — 위지윅스튜디오 외 스타코링크·더존비즈온·신세계푸드·일정실업 등도 동일
사유). 위지윅스튜디오는 `--corp` 명시 지정 시에는 여전히 pending(원문 파일이 로컬에
없어 정상 — 이 트랙에서 "고치는" 대상이 아니라 애초에 감사 스코프 밖으로 빼는 것).
`pytest tests/ fin2/tests/` 회귀 없음.

---

## R38. `fin2/audit/face_audit.py::read_report_face_xbrl_zip()` + `scripts/gateb_audit.py`

> **상태** 유효 · **적용 계층** 검증
배선 3곳 — Track D(xbrl_zip) 신설, `document.xml` 없는 filing 의 감사 커버리지 공백
해소(P3-1 '원인 A' 그룹③-b 후속)

**증상** — 일부 filing 은 `download_tasks`에 `xbrl_zip` 파일타입만 `completed`로 등록되고
`xml`(document.xml)이 없다(전사 1,639건 중 1,627건, 2015~2019 집중 — 표본 30건 재다운로드
전부 `[014]` 회복 0건으로 "종종 영구적" 확정, `redownload_202608_xbrl_zip_bulk.py`
docstring 참고). `file_path_map()`이 `file_type IN ('xml','pdf')`만 찾아 이런 filing 을
통째로 못 읽어 `SOURCE_NOT_TRACK_A`(pending)로 떨어졌다.

**근거(실측)** — 이건 데이터 갭이 아니다. `fin2/extract/report_lines_xbrl.py::
extract_report_lines_xbrl()`(R10, XBRL_INSTANCE zip 전용 파서)가 daily 파이프라인에서
이미 zip 을 정상 처리해 report_lines/std_v3 에 값이 들어가 있다(오리엔탈정공 2015Q3
`[기재정정]분기보고서`, rcept 20151123000202: `revenue` 연결 131,915,704,465/별도
97,795,299,224, `controlling_ni` -4,000,961,350 — 전부 std_v3 와 zip 재추출 값이 정확히
일치). 유일한 문제는 face_audit 의 대조 경로 부재(그룹①/R35 와 동류).

**수정** — `read_report_face_xbrl_zip()` 신설: `extract_report_lines_xbrl()`(R10)을 감사
시점에 재호출(저장된 report_lines 를 읽지 않고 zip 을 다시 열어 Track A/B/C 와 같은
"항상 원본 재유도" 관례 유지), `col_index=0`(당기)만, `account_mapper` 텍스트 매핑(Track
B 와 동일 — canonical 은 report_lines 에 없음). 독립성 잔여 한계: R10 파서 자체의 추출
버그(부호·스케일·개념매핑 오류)는 이 경로로는 못 잡는다 — Track A(문서 내 별개 XBRL 태그
직접 스캔)만큼 완전독립은 아니다. 배선 3곳(전부 필수, 하나라도 빠지면 조용히 결함):
① `file_path_map()` — `file_type IN (...)`에 `'xbrl_zip'` 추가(xml>pdf>zip 우선순위).
② `face_of()` — `fp`가 `.zip`이면 `read_report_face_xbrl_zip()` 호출, `track="D"`.
③ `gate_status_for_row()` — `("B","C")` 하드코딩 allowlist를 `("B","C","D")`로 확장(★
가장 잊기 쉬운 지점 — 안 하면 Track D 의 모든 불일치가 조용히 `fail_a`로 오승격한다.
Track D 는 R10 재사용이라 Track A 보다 독립성이 약해 최고신뢰를 주면 안 됨).

**검증** — 오리엔탈정공 2015Q3(위 실측 필링): 수정 전 `SOURCE_NOT_TRACK_A` 42개 필드
전량 pending → 수정 후 `pass` 전환(잔여 pending 5개는 R10 자체 추출 갭, 별도). 오리엔탈정공
전체(2015~2026, 132행): pass 112 / fail 0 / pending 20, 일치율 100.0%. `xbrl_zip`-only
777개사 중 80개사 표본 `--recheck --no-commit` 재감사 — **fail_a 신규 발생 0건**(9→9,
§ 게이팅 수정의 핵심 검증 포인트) 확인. pending 1790→1698 이 pass +40·fail_b +52 로
분해(새로 읽히게 된 값 중 실제 불일치는 fail_b/REVIEW 로 안전하게 분류, fail_a 로 오승격
안 됨 — 이 fail_b 52건 자체의 개별 원인규명은 범위 밖, 향후 트랙). `pytest tests/
fin2/tests/` 회귀 없음.

---

## R40. Track D(xbrl_zip 재파싱) — 다중필링 narrow-prefer 재현 불가(알려진 감사 커버리지

> **상태** 유효 · **적용 계층** 검증
공백, 수정 안 함)

**증상** — R38(Track D) 재감사가 새로 드러낸 fail_b 541행 중 232건이 `bs.trade_payables`
(매입채무)에서 db(std_v3)와 Track D 재파싱 값이 불일치했다.

**근거(실측, 00107987 2018H1·00112651 2017Q1 — 2건 모두 동일 구조)**:

| 필링 | "매입채무" 표기 | 값 |
|---|---|---|
| 원본 | "매입채무 및 기타(유동)채무"(광의, 부모) + "단기매입채무/매입채무"(협의, 자식) | 광의 80,992,526,676 / **협의 39,217,873,634(=db)** |
| [기재정정] | 광의 라벨만 재게재, 협의 세부항목 생략 | 80,992,526,676(=Track D 재파싱) |

`combine.py`의 `_NARROW_PREFER`/`_BROAD_RE`(`_reduce_conflict()`, R23)가 그 기간의 원본+
정정 **전체를 풀링**한 후보군에서 원본의 협의값을 정확히 우선 채택한다 — **db는 정확**.
반면 `read_report_face_xbrl_zip()`(R38, Track D)은 감사 대상 rcept **하나(대개 정정본)만
연다** — 정정본엔 협의 세부항목이 아예 없으니 광의값만 후보로 갖게 되고, db의(정확한)
협의값과 불일치로 fail_b가 뜬다.

**결론: 데이터 결함이 아니라 Track D 설계 자체의 한계다.** db 값도, 판정 등급(fail_b/
REVIEW, fail_a 오승격 없음)도 이미 올바르므로 **수정하지 않는다** — Track D는 애초에
"완전독립 감사가 아님"을 전제로 하는 트랙(R38 자체가 이미 "R10 재사용이라 Track A보다
독립성이 약함"을 명시)이고, 여기에 다중필링 폴백까지 추가하면 그 존재의미(휴리스틱 REVIEW용
대조)가 흐려진다. 개선하려면 후보가 db와 안 맞을 때 같은 기간의 다른(원본) 필링도 열어보는
확장이 필요하지만 우선순위 낮음(별도 요청 시에만 착수) — [[p3-1-trackd-failb-rootcause-2026-08-20]].

**R38 후속 — xbrl_zip 전사 반영 완료(2026-08-21)**: R38(Track D 신설)+R39(패턴A 수정)+
R40(패턴B 문서화)이 전부 안전 검증된 뒤, `scripts/run_gateb_audit_parallel.sh`
(5-shard, `--source v3 --recheck`)로 **std_v3 전체 303,859행**(제한된 xbrl_zip-only
표본이 아니라 전 유니버스)을 실제 commit 재감사했다. 재감사 전 `face_audit_snap_20260820`
기준선 스냅샷 대비 행단위 gate_status 전이:

| 전이 | 건수 | 해석 |
|---|---|---|
| pending → pass | 558 | Track D 커버리지 공백 해소(정상 일치) |
| pending → fail_b | 300 | Track D로 새로 읽혔으나 값불일치 — REVIEW 등급(R40류, 안전) |
| fail_b → pass | 7 | R39(패턴A) 수정으로 정정 |
| fail_a → pass | 2 | R39(패턴A) 수정으로 정정 |
| fail_b → pending | 1 | 개별 원인 미조사(경미, 저위험 방향 — pending 은 out-of-scope 일 뿐 오탐 아님) |

**pass→fail 전이, X→fail_a 전이는 0건**(전수 확인 — `fail_a` 283건 중 BS 총계 3종
[`bs.total_assets`/`bs.total_liabilities`/`bs.total_equity`] 포함 행 0건). 사전 --no-commit
표본 테스트(R38/R39 각 검증절)의 "fail_a 신규 0건" 예측이 전수 commit 규모에서도 정확히
재현됨 — [[gateb-full-reaudit-is-required-to-close]] 원칙대로 표본이 아닌 전수로 트랙 종료.

---

## R41. `fin2/audit/curated_key_scan.py` 신설 — Gate B curated 키 재생성기(전수 패턴

> **상태** 유효 · **적용 계층** 검증
스캔 → 신규/재발 후보 탐지, 자동 코드 반영 없음)

**배경** — R15~R33 다수가 특정 (corp, fy, period[, basis]) 를 리터럴로 열거한 override
로 구현돼 있다(`combine.py`/`face_audit.py`). 이 키 집합은 생성 당시 DB 스냅샷의 1회성
산출물이라, 새 필링이 들어와도 자동으로 안 늘어난다 — 같은 회사가 같은 구조로 다음
분기를 공시하면 버그가 조용히 재발하거나(값이 틀림) Gate B 가 pending 을 fail 로
잘못 잡는다. 설계: `docs/plans/gateb_curated_key_regenerator_design_2026-08-18.md`
(§6 결정사항 2026-08-19 확정, 구현은 2026-08-21).

**구현 범위(§6 확정 1차 범위)** — 4개 family:
- **T2**(`report_lines` 직접 전수 스캔, 원 생성 스크립트 corp 조건 없음 재사용):
  `sga_subline`(`_SGA_SUBLINE_OVERRIDE_KEYS`) · `cogs_additive`(`_COGS_ADDITIVE_OVERRIDE`).
- **T1**(XML/PDF 재파싱 없이 이미 계산된 `face_audit`(v3) 의 `fail_detail` 재사용,
  R38 xbrl_zip 전사 반영으로 항상 최신 유지):
  `trade_payables_additive`(`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`, BS 부채성 라인 2-조합
  합이 report_won 과 일치하는 후보를 찾는 휴리스틱) ·
  `cogs_concept_mismatch`(`_COGS_CONCEPT_MISMATCH_KEYS`, `report_won==cogs+sga`±1 재확인).

**T1/T2 비대칭(구현 중 발견, 설계 §5-C 캐비엇의 실제 사례)** — T2 는 모집단(`report_lines`)
이 override 등록과 무관해 ①일치(=동치성 증명)/④소멸까지 전부 계산 가능하다. 반면 T1 은
모집단(`face_audit.fail_detail`)이 **구조적으로 이미 등재분을 제외**한다 — 등재 키는
`cogs_concept_mismatch` 는 face_audit.py 가 pending 재분류, `trade_payables_additive` 는
combine.py 가 build 시점에 db_won 자체를 고쳐 PASS 로 뜨기 때문에, 애초에 VALUE_DIFF 로
안 잡힌다. 그래서 T1 은 forward/lateral 후보만 내고 matched/vanished 는 계산하지 않는다
(계산해도 등재분 100%가 항상 "vanished"로 나와 의미 없음 — `_classify_residual()`).

**동치성 검증(①일치, 최초 실행 2026-08-21)** — T2 두 family 전부 등재 키와 **정확히 일치**:
`sga_subline` 685/685, `cogs_additive` 319/319(소멸 0, 재구현이 원 생성 스크립트와
100% 동일 로직임을 실측 확인). 실행 시간 T2 두 family 합산 ~90초, T1 두 family 합산 ~5초
(report_lines 전수가 아니라 face_audit 재사용이라 빠름) — daily/반기 배치 오버헤드로 무해.

**최초 실행 결과(2026-08-21)** — 신규후보 31건(소멸 0): `sga_subline` forward 14 ·
`cogs_additive` forward 2(전부 2026 H1, 설계문서가 예견한 "2026 반기 백로그 적재 시
curated 키 stale" 시나리오가 실제로 재현됨) · `trade_payables_additive` lateral 15
(원문대조 전 후보, §4 경고대로 자동반영 대상 아님) · `cogs_concept_mismatch` 0.
`curated_key_candidates` 테이블(신규, `collector/models.py`)에 적재, status='new'로
사람 리뷰 대기.

**배선** — `scripts/collect_new.py` 두 call site(메인 ④ 이후 · `--standardize-only`
재개 이후) 모두 `_run_curated_key_scan()` 호출(`docs/runbook_new_parser_pipeline_
integration.md` 체크리스트 ① 준수). 알림은 기존 `scripts/notify.py::notify_macos()`
재사용(설계문서가 "알림 코드 전무"라 적었던 2026-08-18 이후 이미 C10 트랙에서 추가돼
있었음 — 새로 안 만들어도 됐음). 후보 0건이면 로그만, 1건 이상이면 macOS 알림 팝업+로그
요약(§6 결정사항 1).

**범위 밖(§6 결정사항 2·3, 별도 트랙)**: `_FX_PRESENTATION_CURRENCY_KEYS`(T1-3, 원문
표시통화 판정 규칙 신설 필요) · T0 축B(신규 회사가 blanket override 대상이 되는 경우,
수동 작성 부담 큼).

**자동 코드 반영 없음** — 후보는 사람이 원문대조 후 수동 등재(R15~R33 워크플로우와 동일).

---

## R46. `fin2/audit/face_audit.py::_with_ni_attribution_text_fallback()` —

> **상태** 유효 · **적용 계층** 검증
NI 귀속 스킵게이트 결함 수정, 171건/26개사(2026-08-26, R45 후속)

**배경** — R45 Gate B 재감사 중 발견된 예외 1건(01137383, 위 R45 항목·
부록C)을 조사하다 `face_audit.py` is.controlling_ni fail 247건(fail_b 245
+ fail_a 2) 전체로 스코프를 넓혀 원문 XML 직접 실행 대조(추측 없음, 스크립트
`scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py`)로 재분류했다.

**근본원인** — `_with_ni_attribution_text_fallback()`이 `is.controlling_ni`/
`is.noncontrolling_ni`가 이미 `lines`에 있으면(옳든 그르든) 섹션 헤더 기반
구조인식 함수(`_ni_attribution_text_candidates()`, R35)를 아예 안 불렀다.
일반 라벨매퍼(`account_mapper.map()`)가 총포괄손익 귀속 섹션을 순이익
귀속으로 먼저 오매핑해 두 canonical을 채워버리는 문서에서, 정답을 정확히
아는 구조인식 함수가 호출 기회 자체를 못 얻었다. 원문실측으로 확인된
오매핑 경로 2종:
- **변종A**: `account_mapper.py`의 bare 지배지분 가드(`endswith("지분")`)가
  트레일링 마침표(`"지배기업 소유주지분."`, EUC-KR 문서 필자 관행)에
  우회당해 fuzzy로 is.controlling_ni(0.93)에 오매핑(00913689 세경하이테크
  2021H1 실측).
- **변종B**: `"…지분순이익(손실)"`류 라벨은 "포괄"/"중단"/"계속영업"
  리터럴이 없어 기존 가드 어디에도 안 걸리고 정상 alias로 통과 —
  총포괄손익 귀속 섹션인데도 라벨만으론 구분 불가(01137383 카카오게임즈·
  00117027 알루코 실측). 부수발견(알루코): `"지배회사지분순이익"`이 fuzzy로
  **is.noncontrolling_ni**(0.88, 방향까지 틀림)에, `"지배기업소유주지분
  합계"`(BS 자본총계 개념)가 is.controlling_ni(IS 개념, 0.91)에 오매핑되는
  제3의 하위패턴도 확인 — 오늘 스코프(controlling_ni) 밖, 미조치.

**수정** — 스킵게이트를 제거하고 구조인식 함수를 항상 추가 실행(선택이
아니라 순수 가산). `audit_fields()`의 PASS 판정이 "후보 집합 어디든
일치하면 성립"(`val in won_vals`)이라 이 변경은 기존 후보를 하나도 지우지
않는 단조 개선 — 새 오탐을 만들 수 없다.

**실측/검증** — 247건 원문실행대조 분류: CONFIRMED_PATTERN(=수정으로
해소 가능) 171건/26개사, REPRODUCED_BUT_STRUCT_FUNC_ALSO_MISSES(=R47
사각지대, 아래 별도) 70건(01137383·fail_a 2건 포함), NOT_REPRODUCED 4건
(이 결함과 무관, 파일변경 의심), NO_XML_FILE 2건(도구 한계). 수정 후
Gate B 재감사(38개사, source=v3, fy≥2010, 4260행, 드라이런→실커밋 동일
결과): pass 3113→3272(+159) · fail_b 253→78(−175) · **fail_a 10→10
(변화 없음, 회귀 0건)** · pending 884→900(+16, 전부 안전한 방향). `pytest
fin2/tests/ tests/` 624 passed(무관 기존실패 1건 제외, 신규 회귀테스트 1건
포함).

**미해결(R47로 분리, 부록C)** — 70건(01137383 포함)은 정답 행이 `<TE>`
태그(ACODE 없음)로 렌더링돼 TE 전용 구조함수(ACODE 필수)와 TD 전용
구조함수("TE 있는 행은 자매함수가 처리했다"고 가정하고 skip) 양쪽 다에서
빠지는 별개 사각지대 — 이 수정으로는 안 풀린다. 설계는
`docs/plans/faceaudit_ni_attribution_skipgate_design_2026-08-26.md` §2-B
(미확정, 별도 승인 필요).

근거: `fin2/audit/face_audit.py::_with_ni_attribution_text_fallback()` ·
`fin2/tests/test_ni_attribution_text_fallback.py`(신규 회귀 1건) ·
`scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py` ·
`docs/plans/faceaudit_ni_attribution_skipgate_design_2026-08-26.md` ·
메모리 `faceaudit-ni-attribution-skipgate-2026-08-26`. 커밋 `5f07d39`.

---

## R54. `fin2/audit/face_audit.py::read_report_face_xbrl()` — 회사고유 확장(UDF)

> **상태** 유효 · **적용 계층** 검증
acode 라벨매칭 폴백, `bs.trade_payables` 25건 해소(2026-08-28~29)

**배경** — [[gateb-trade-payables-45-triage-2026-08-28]] 세션에서 trade_payables
fail_a 45건을 원문 리터럴 대조(`re.escape(db_won)` + 콤마포맷)로 4클래스 분류한 것 중
**클래스A(24건, 이후 실측으로 25건 확정)**를 해소.

**근본원인** — BS face 본문의 진짜 매입채무 행이 회사·타임스탬프별 고유 확장(UDF)
acode(`entity{corp8}_udf_BS_{timestamp}_CurrentLiabilities` 류, 또는
`entity{corp8}_AccountsPayableOfCurrentLiabilities` 처럼 타임스탬프 없는 변형)를
쓴다. 이 접미사는 **의미가 없다** — KX(00657987) 원문에서 같은 접미사 패턴
(`OfCurrentLiabilities`)이 기타의투자자산·매각예정자산·장기차입금 등 전혀 다른
계정에도 재사용되는 것을 확인 — 그래서 R53(inventory/ppe)처럼 정적 acode alias
사전으로는 원천적으로 해결 불가. `read_report_face_xbrl()`의 admission gate
(`acode.startswith(_XBRL_PREFIXES)`, `_XBRL_PREFIXES=("ifrs-full_","dart_")`)가
`entity...` 접두 acode를 애초에 전부 걸러내 후보 집합에서 탈락 → 유일 후보로 남는
다른 계정(장기매입채무 등)과 대조돼 VALUE_DIFF(fail_a) 오탐.

**수정** — acode 사전이 아니라 **같은 `<TR>` 행의 라벨 셀(형제 TE, ACODE 없음)
텍스트**로 정체를 확인하는 좁은 admission-gate 예외를 추가했다. 10개사 원문 확인
결과 라벨은 공백(일반/전각 `　`) 제거 시 정확히 3종으로 수렴: `매입채무` ·
`매입채무및기타채무` · `유동매입채무`(폐집합 exact-match — 부분일치는 "장기매입채무"
같은 무관 계정 오염 위험이 있어 배제). `entity\d{8}_` 접두이면서 라벨이 이 3종
중 하나일 때만 `canonical="bs.trade_payables"`로 admit — 그 외 entity acode는
기존과 동일하게 skip(스코프 확대 없음, 다른 필링의 Track A/B 선택에 영향 없음).

★ **설계 초안의 함정** — 최초안은 `_map_acode_face(acode, te)`처럼 acode 매핑
함수 안에서 라벨을 확인하려 했으나, 이 함수에 도달하기도 전에 admission gate
(`_XBRL_PREFIXES` 미포함)가 `entity...` acode를 전부 걸러내 실행조차 안 됨을
표본 재감사(`--no-commit`)에서 fail_a 불변으로 실측 발견 — **admission gate
자체를 좁게 여는 방식으로 재설계**했다. 짐작으로 "될 것"이라 판단하지 말고
반드시 실제 코드 경로로 검증할 것([[feedback-verify-against-source]]).

**안전성** — `audit_fields()`의 PASS 판정이 `val in {후보집합}`(소속검사)이라
후보 추가는 순수 가산 — 기존 PASS를 깨뜨릴 수 없다(R53과 동일 원칙, 코드 주석
face_audit.py L781 참고).

**실측/검증** — class A 10개사 25건 표본(`--corp-file`, `--no-commit`) fail_a
25→0, 회귀 0. 400개사 무작위 표본(seed=42, 39,792행) fail_a 15건 — 전부 이번
수정과 무관한 기존 클래스B/C/기타. 전수 재감사+커밋(2,532개 활성사, 약 6시간)
결과 DB `fail_a` **113→88**(정확히 25건 해소, trade_payables 45→20).

★ **부수 함정 1건** — 일정실업(00146542)은 전수 재감사 직후에도 DB에 stale
fail_a 2건이 남았다(`checked_at`이 재감사 시작 이전 — R37(`select_corps()`가
상장폐지사를 감사 유니버스에서 제외) 때문에 이 회사가 **전수 재감사에 아예
포함되지 않음**, 코드 버그 아님). `--corp 00146542 --recheck`로 단독 재감사해
해소(fail_a 90→88). **교훈**: 전수 재감사 후 DB 카운트가 예상과 안 맞으면
상장폐지사 제외 유니버스부터 의심할 것.

근거: `fin2/audit/face_audit.py::read_report_face_xbrl()`(admission gate +
`_ENTITY_EXT_ACODE_RE`/`_TRADE_PAYABLES_ROW_LABELS`/`_row_label_text()`) ·
`docs/plans/gateb_trade_payables_classA_udf_acode_label_fallback_design_2026-08-28.md` ·
메모리 `gateb-trade-payables-classA-label-fallback-design-2026-08-28`.

---

## R56. `fin2/audit/face_audit.py` — 갤럭시아에스엠 라벨-acode 뒤바뀜

> **상태** 유효 · **적용 계층** 검증
1건 curated 예외로 face_audit 오탐 해소(2026-08-29)

**배경** — [[gateb-trade-payables-45-triage-2026-08-28]] 클래스C 3건 중 마지막
1건(갤럭시아에스엠 00129554, 2026H1 연결). R55(종근당홀딩스형)와 겉보기 증상은
같지만(원문 당기 컬럼에 db_won이 리터럴로 존재, acode는 매입채무와 무관) 원인이
**정반대** — 이번은 std_v3(DB)가 정답이고 face_audit(검증기)이 오탐이다. 비츠로셀 건과 함께 batch #88 에서 release 했다(검증측 withdraw 대상).

**근본원인** — 2026H1 연결 BS 원문(`20260814002461.xml` L3260-3282, 원문대조
확인)에서 필자(공시대리인)가 라벨과 acode를 서로 바꿔 태깅했다: "단기매입채무"
라인(매입채무 계열, `bs_accounts.py` exact alias로 정확히 등록됨)에 엉뚱한
acode(`ifrs-full_OtherCurrentFinancialLiabilities`)를, 매입채무와 무관한
"기타유동채무" 라인에 표준 매입채무 acode(`ifrs-full_TradeAndOtherCurrentPayables`)를
붙였다(전기 비교컬럼도 동일 패턴 — 체계적 오태깅). 별도(separate) 기준(L9398)엔
같은 금액(172,864,613)이 정상 alias(`dart_ShortTermTradePayables`)로 "단기매입채무"에
태깅돼 있어 교차확인됨. std_v3(AccountMapper)는 acode 를 보지 않고 라벨 텍스트로
판별해 정답(172,864,613)을 잡았고, face_audit(`read_report_face_xbrl()`)은 acode를
신뢰해 오태깅된 값(1,483,956,477)을 후보로 채택 → false VALUE_DIFF(fail_a). 별도
basis는 `dart_ShortTermTradePayables` 정상후보가 함께 있어 membership 대조로 이미
PASS(영향 없음) — consolidated 1건만 영향.

**수정** — 일반 라벨힌트 가드 대신(설계문서 §2 "대안" 채택) 이 필링 1건만 curated
예외로 등록. `face_audit.py`에 `_TRADE_PAYABLES_ACODE_LABEL_SWAP_KEYS =
{("00129554", 2026, "H1", "consolidated")}` 추가, `bs.trade_payables` 후보 비교
직전(`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`/R23 와 같은 자리) 이 키에 해당하면
`acode == "ifrs-full_TradeAndOtherCurrentPayables"` 후보를 배제. std_v3 변경 없음 —
face_audit 코드만 수정, 재백필 불필요.

**안전성** — 4-튜플 키가 정확히 이 1건만 가리켜 다른 회사 acode 신뢰도는 전혀
건드리지 않는다(R23/R55 후속 부수효과와 무관, 순수 additive). 배제 후 정답
("단기매입채무")은 정상 acode 가 없어 후보 자체가 없으므로 fail_a 가 아니라
LABEL_UNMATCHED(pending)로 남는다 — VALUE_DIFF(확정 오류)를 주장하지 않는
보수적 처리.

**실측/검증** — 원문(raw_report) L3260-3283 재확인으로 XML 값 그대로 일치.
`--corp 00129554 --recheck --no-commit` 드라이런: 이 필링만 fail_a 1→0, 다른
131행 무변동. Phase B 라인 전수대조 fail_a 7건은 수정 전/후 동일(무관, 회귀
아님). `--corp 00129554 --recheck`(커밋) 실행 후 DB 확인: 해당 행 status
`fail`→`pending`. DB 전체 latest-snapshot 집계: `trade_payables` fail_a
**18 → 17**, `face_audit` 전체 fail_a **86 → 85**(정확히 1건 해소, 신규 0).
`pytest fin2/tests/test_face_audit.py` 52/52 pass.

근거: `fin2/audit/face_audit.py`(`_TRADE_PAYABLES_ACODE_LABEL_SWAP_KEYS`) ·
`docs/plans/gateb_trade_payables_classC_faceaudit_acode_label_swap_design_2026-08-29.md` ·
메모리 `gateb-trade-payables-classC-rootcause-2026-08-29`.

---

## R61. Gate B Phase B(`fin2/audit/line_audit.py`) DB측 원천 `fact_v2`→`report_lines`

> **상태** 유효 · **적용 계층** 검증
이식 + 전수재감사로 발견한 Track A/B 감사리더 버그 3종(★완전 종료 2026-09-01)

**배경** — Phase B(본문 전 계정 라인 전수대조, `face_line_audit`)는 계층2 GC(`fact_v2`
55GB DROP) 트랙의 마지막 살아있는 소비자였다. `fact_v2`는 acode 키인데 계층3이 실제
소비하는 원천은 라벨 키인 `report_lines`라 이식 없이는 DROP이 막힌다(R23·R35·R46·R47과
같은 계열 — Gate B 감사리더는 파싱·적재 규칙과 별개 코드경로지만 같은 이유로 이 문서에
쌓여왔다). 이식 자체는 규칙 변경이 아니라 원천 교체지만, 게이트1(라벨 매칭률 95%
목표, 실측 100.00% — `FaceLine.in_body_section`으로 Track A도 Track B의 DART
섹션기반 본문표 식별을 공유해 도달)을 통과시키는 과정과 Phase 4 전수재감사 과정에서
**Track A/B 감사리더 자체의 진짜 버그 3종**을 발견·수정했다:

1. **Track B dedup 키 누락** — `read_report_face_text()`의 중복제거 키가 `label`을
   빠뜨려 동명이의 라벨(같은 표기, 다른 계정)이 충돌·서로를 덮어썼다.
2. **Track A 값-집합 매칭 재설계** — 라벨 단일값 비교 대신 값-집합 매칭으로 바꿔
   1차 실행의 대량 오탐(악화 74,220건)을 해소.
3. **지배/비지배·EPS 계열 Track B 확장 제외** — 이 계열은 R27/R45~R47이 이미 다루는
   별도 함정(라벨 부분문자열·귀속 오매핑)이 Phase B 라인대조에도 새어 들어와 있어
   감사 대상에서 뺐다(수정이 아니라 제외 — 근본 함정 자체는 R27/R45~R47 관할).

**결과(전수재감사 전이표, PK=`rcept_no`)** — 최초 실행(수정 0건): 개선 4,151 : 악화
74,220. 위 3개 수정 반영 최종(4차) 실행: **개선 14,014 : 악화 209 = 67:1**.

**잔여 209건(R-트랙 후보, 미해결)** — 트리아지 결과 상위 2개 클러스터는 원인 가설만
확정, 수정은 이 트랙 범위 밖:
- Track B, corp `01032486` 등(34/209) — `read_report_face_text()`가 `fx_declared`
  정책(R? 미등재, 메모리 `fx-declared-statements` 참고 — 환산 없이 표시통화 그대로
  저장) 대상 문서를 문서 기본단위(원 환산 가정)로 잘못 읽는 것으로 의심(미검증).
- Track A, `ifrs-full_Inventories` 등 BS/CF 공용 라벨(58개사 분산) — CF 조정항목
  섹션에서 재사용된 라벨을 BS 값과 오대사하는 것으로 의심(미검증).

근거: `docs/plans/gateb_phaseb_line_audit_v3_migration_design_2026-09-01.md`(Phase
0~4 전체) · `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §4-3 · 메모리
`gateb-phaseb-line-audit-migration-phase0-1-2026-09-01` · `fin2/audit/line_audit.py`
· `scripts/gateb_audit.py::audit_lines()` · 커밋 `bcd8998`/`e3267da`/`e1af6d5`/
`37c6e81`/`ca6dfa3`/`4e6b767`.

---

## R140. 계층2 검토 CSV에 SCE 포함 + `layer2_review.py`에 `--min-severity` 단계

> **상태** 유효 · **적용 계층** 검증
필터 추가 (2026-09-18, 사용자 지시)

**배경**: R139와 같은 브라우저 에이전트 원문대조 캠페인 설계
(`docs/plans/layer2_review_browser_agent_automation_design_2026-09-18.md`)에서
사용자가 "bs is cf **sce** 데이터와 비교"라고 명시했는데, `fin2/extract/
review_csv.py::SCOPE_ORDER`와 `fin2/audit/layer2_selfcheck.py::STATEMENTS`는
2026-09-08 당시 사용자 범위 결정으로 **BS/IS/CF 3종만**이었다("SCE/APPR은
대상 밖" 주석). `report_lines` 자체에는 SCE 행이 이미 적재돼 있었다 —
`load_rows()`의 SQL이 애초에 statement로 거르지 않아서 CSV 생성 단계에서만
숨겨지고 있었을 뿐.

**수정**: ① `review_csv.py`의 `SCOPE_ORDER`에 `("separate","SCE")`/
`("consolidated","SCE")` 추가(각 basis 안에서 BS→IS→CF→SCE 순), `scope_counts()`·
`build_preamble()` 요약도 SCE 포함하도록 확장. `layer2_selfcheck.py`의
`STMT_KO`에 `"SCE": "자본변동표"` 추가(단, **자동검산 대상(`STATEMENTS`)은
그대로 BS/IS/CF만** — 자본변동표는 항등식이 BS/CF처럼 단순하지 않아 이
파일의 라벨-앵커 방식이 안 맞는다. 최종 판정은 어차피 브라우저 원문대조이므로
자동검산 확장은 불필요). APPR(이익잉여금처분계산서)은 사용자가 언급하지
않아 그대로 범위 밖.
② `scripts/layer2_review.py::_pick()`에 `min_severity` 매개변수, `next`/`pass`
서브커맨드에 `--min-severity` 옵션 추가 — 캠페인 단계(B): 사전 스크리닝
(`layer2_screen.py`)이 뭔가 걸어놓은 건(`screen_severity>0`, 2015+ 실측
27,136건)부터 먼저 처리하고, 그 다음 단계(A)로 나머지(`severity=0`,
80,369건)까지 이어서 전체를 돈다(사용자 지시: "B 먼저 하고 이어서 결국
전체를 한 번은 돌린다 — 파서 수정 건이 나올 가능성이 높은 쪽부터"). 미지정시
필터 없음(기존 동작 그대로, 다른 시대 캠페인에 영향 없음). `cmd_status`에도
이 두 그룹의 pending 잔량을 따로 보여주는 절 추가.

**검증**: `fin2/tests/test_review_csv.py`에 SCE 순서/카운트 테스트 2건
추가(`test_scope_counts_counts_bs_is_cf_and_sce`,
`test_scope_order_places_sce_after_cf_in_each_basis`) — 총 22건 통과.
`_pick(min_severity=1)`을 실제 2015+ 큐로 실행해 severity>0인 항목만
반환됨을 확인(`corp_rank=3, screen_severity=5`). `pytest tests/ fin2/tests/`
전체 1060 passed(기존 무관 실패 1건 제외).

---

## R167. 검증 ↔ 재적재 규칙 — 적재 스탬프·lease·내용버전 (2026-09-24, R139 대체)

> **상태** 유효 · **적용 계층** 검증

**배경**: 몇 달짜리 원문대조 캠페인의 상태를 DB(`verification` 스키마)에 두면서, 검증 중이거나
이미 검증된 데이터와 재적재가 섞이는 문제를 **규약이 아니라 DB 가 강제하도록** 정했다.
실제 사고 두 건이 계기다: 검증 세션이 구코드로 재적재해 백필을 되돌린 일(R164 백필 SCE
12,192행), 그리고 보지 않은 필링에 pass 가 찍힌 일. 설계:
`docs/plans/verification_schema_two_worktree_design_2026-09-24.md` §4.

**규칙**
1. **적재 스탬프는 트리거가 찍는다.** `report_lines` 의 INSERT/UPDATE/DELETE 는 커밋 시점에
   필링별 **내용 해시**(BS/IS/CF/SCE, scope 별)로 요약된다. 내용이 바뀌었을 때만
   `verification.filing_loads.load_seq` 가 +1 된다. 이력은 `filing_load_events` 에 남는다
   (바뀐 scope, git commit, 워크트리, reason). 호출부 배선이 필요 없다 — 데일리·백필·임시
   스크립트 모두 같은 경로로 기록된다. `collector/db.py` 는 연결마다 `verification.actor`
   (워크트리)와 `verification.parser_commit`(HEAD, 미커밋 변경이 있으면 `-dirty`)을 세션에 싣는다.
   해시에서 빼는 것: `id`, `source_ref`, `context_raw`(출처 표기일 뿐 검증 대상 값이 아니다).
2. **같은 결과로 다시 파싱하면 아무 일도 없다.** 해시가 같으면 판정은 그대로 유지된다.
3. **검증 중(lease) 필링은 수정 계정이 바꿀 수 없다.** 트리거가 커밋을 거부한다(SQLSTATE `55P03`).
   `vq.py batch reload` 는 그 건을 `deferred` 로 두고 다음에 다시 시도한다. 관리자 계정(데일리
   파이프라인)은 막지 않는다 — 대신 규칙 4 가 판정을 무효화한다.
4. **판정은 적재 버전에 묶인다.** `pass`/`issue add` 는 점유 시점의 `load_seq` 와 현재 값이
   다르면 거부된다. passed 필링의 내용이 바뀌면 그 필링은 pending 으로 돌아가고, 슬롯은 다시
   큐에 들어간다. `vq.py show` 는 판정 당시 해시와 비교해 **바뀐 scope 만** 알려준다.
5. **`fixed` 는 데이터가 바뀐 재적재를 요구한다**(이슈 트리거). 커밋만으로는 fixed 가 되지 않는다.
6. `unit_source='manual'` 보호(2026-09-08)는 그대로 유지된다(별개 규칙).

**범위 밖**: `note_lines`·`report_tables` 는 스탬프하지 않는다. 캠페인이 대조하는 것은 본문 재무제표이고,
`note_lines`(2억 행)에 트리거를 거는 비용을 피하기 위해서다.

**근거 코드**: `fin2/verification/schema.sql`(trg_finalize_load, trg_issue_before),
`fin2/extract/report_lines.py::store_report_lines`(R139 제거), `collector/db.py`
(`_set_verification_identity`). 테스트: `fin2/tests/test_verification_schema.py`,
`fin2/tests/test_verification_ops.py`. 실측: pending 필링 1건 연속 2회 재적재 → load_seq 1 유지
(해시 안정), 해시 계산 ~40ms/필링(SCE 900행 규모).

---

## R174. Gate B 판독기 — 증명된 단위 교정(R132/R169)을 따르고, 당기 첫 칸 '-' 는 0 후보로 둔다 (2026-09-25)

> **상태** 유효 · **적용 계층** 검증

**발견**: Gate B 148건 트리아지. DB 는 원문과 맞는데 기준값(report_won)이 틀려 fail_b 가 났다.
(1) R169 교정 필링 3건에서 ×10⁶ — 판독기가 셀 ADECIMAL(−6)/선언 백만원을 그대로 믿었다.
(2) 당기 칸이 '-' 인 행 — Track B any-column 판독은 숫자 칸만 후보로 삼아 정답 0 과 맞을 수 없었다(DB=0 유형 195필드).

**규칙** (`fin2/audit/face_audit.py`):
1. `_apply_proved_unit_overrides`: `read_report_face`/`read_report_face_tracked`(XML A·B 트랙) 결과에
   `report_lines._unit_override(rcept, 섹션)` 을 적용해 adecimal 을 바꾼다. 문서 밖 증거로 확정된 섹션만이라
   "독자 재파싱" 원칙과 충돌하지 않는다.
2. `read_report_face_text._read_table`: 라벨 다음 **첫 비공란** 값 칸(주석열이면 그 뒤부터)이 대시(-, −, –, ―, －, —)면
   그 행 후보에 0 을 더한다. 2단(내역/합계) 서식은 당기 내역 칸이 공란이라 공란을 건너뛴다(디와이디 01089378 2016Q3
   `'', '-', '', 14,765,347,500`).

**테스트**: `fin2/tests/test_r173_r174_eps_note_col_gateb_reader.py`(동성케미컬 R169 · 패션플랫폼 대시).

**결과(Gate B 재감사, 148건 기업 48개사 2015~2021)**: 148건 중 **pass 140** · pending 1 · fail_b 7. 이 48개사 전체로는
fail_b→pass 140 · pending→pass 78 · pass→(fail/pending) 0. 남은 7건은 판독 한계다: 요약표·다른 서식 행(시큐브 00402110 배당은 원문
'-' 가 정답, 제14기 값을 읽음), 주석번호 '32' 를 법인세로 읽은 건(00554352), 2024년 재정정본(00145686 2019FY) 등. DB 결함은 확인되지 않았다.

---

## R201-b. 기계대조(machine_compare)의 **SCE 주석 열 오프셋** 오탐 (2026-09-30, 검증 도구 수정)

> **상태** 유효 · **적용 계층** 검증

**발견**: 카카오게임즈 2023FY `20240320002052`(160건)·기가비스 2023H1 `20230814003197`(32)·카페24 2017FY `20180402005387`(33) column_misassign 이슈는 전부 mc5 가 낸 것이다.
DB 행은 자체 항등식이 맞는다(예: 기가비스 자본금 100,000,000 + 이익잉여금 61,077,361,961 = 합계 61,177,361,961). 기계대조가 SCE 열을 `col_index` 그대로 원문 셀 번호로 쓴 것이 원인이다.
원문 표 파서는 '주석' 열을 버리지만(`_parse_table` `cols`), report_lines 는 헤더에 주석 열이 있으면 첫 구성요소를 col_index 1 부터 매긴다(주석 값이 없는 행도 마찬가지, 주석 열 보유 SCE 226필링 중 195가 1부터).

**규칙** (`machine_compare._rebase_sce_note_column`): 원문 표(윈도우 전체)가 주석 열을 버렸고 DB 그룹의 최소 구성요소 col_index 가 ≥1 이면, 주석 셀을 비교에서 빼고 col_index 를 그 최소값만큼 당긴다.
원문이 주석 열 헤더를 인식 못 해 셀 0 으로 남긴 표(`&cr;주석` 등)는 이동하지 않는다.

**측정**(주석 열 SCE 230필링 + 2016+ 무작위 SCE 150필링, 구·신 비교): 개선 225 / 동일 151 / 악화 0. 세 필링 모두 clean.
DB 데이터는 바뀌지 않는다(재적재 없음). 해당 이슈는 검증 쪽에서 withdraw/재확인해야 한다.

**회귀 테스트**: `fin2/tests/test_xbrl_quarter_only_cell_r201.py`(R201-b 3건).

## R201-c. R201-b 의 주석 열 판정이 **그룹 접두 라벨**(`지배기업 소유주 귀속분>주석`)을 놓친다 (2026-10-01, 검증 도구 수정)

> **상태** 유효 · **적용 계층** 검증

**발견**: 에치에프알 2018FY `20190401005242` 연결 SCE 의 column_misassign 151건 + value_mismatch 8건(#87615~#87744 등)이 전부 mc5 오탐이다.
DB 는 원문과 일치한다(`전기초 잔액` 자본금 2,500,000,000 = col 1, 자본잉여금 2,052,232,079 = col 2, 구성요소 합 = 지배 합계 47,805,530,781).
이 표는 주석 열이 1행 헤더의 그룹(`지배기업 소유주 귀속분`, colspan) 아래에 있어 `col_label` 이 `지배기업 소유주 귀속분>주석` 이다.
R201-b 는 `col_label != "주석"` 정확 일치로 주석 셀을 걸렀기 때문에 이 라벨은 걸러지지 않았고, 최소 구성요소 col_index 가 0 이 돼 **표 전체의 보정이 꺼졌다**
(주석 값이 있는 행만이 아니라 모든 행이 한 칸씩 밀려 비교됨).

**규칙** (`machine_compare._is_note_col_label`): `>` 로 이은 라벨의 **말단**(공백 제거)이 `주석` 이면 주석 열로 본다. `_rebase_sce_note_column` 은 이 판정으로 주석 셀을 빼고 당긴다.

**측정**: 접두 주석 라벨을 가진 SCE 필링 9건을 구/신 `compare_filing` 으로 비교(`finding` 수): 개선 9 / 동일 0 / 악화 0.
에치에프알은 `mismatch`(value 159·sce_arith 15·uncovered_cell 65·zero_row 1) → `clean`(zero_row 1). DB 데이터는 바뀌지 않는다(재적재 없음).
**JW홀딩스 #87404·라온피플 #87605 는 이 수정과 무관**하다(R184/R184-b 가 의도한 합계-전용 행 채움, 검증 쪽 시각의 차이).

**회귀 테스트**: `fin2/tests/test_xbrl_quarter_only_cell_r201.py`(R201-c 2건).

## R211. 기계대조(machine_compare)의 주당 판정은 **`section_path` 도 본다** — EPS 절 자식행(`(1) 기본주당이익 > 1. 보통주`) (2026-10-02, fix batch #90, 검증 도구 수정)

> **상태** 유효 · **적용 계층** 검증

**발견**: 흥국화재 2023Q1 `20230515002741`·`20230630000997`, 2016Q3 `20161114002032` 의 IS EPS 행 16건(#87877~#87896)이 value_mismatch 로 등록됐다.
DB 는 원문과 일치한다(`1. 보통주` 1,457 = 원문 1,457원/주). 표 단위가 백만원이고, EPS 행 라벨에는 `주당` 이 없으며 조상 행(`(1) 기본주당이익`)에만 있다.
적재기는 R145 `_in_eps_section`(조상 체인에 `주당`)으로 이 행을 EPS 로 보고 배수 없이 저장한다. 반면 `machine_compare` 는 `"주당" in label_raw` 로만 판정했기 때문에 원문 1,457 에 ×10⁶ 을 곱해 비교했다.

**규칙** (`machine_compare._per_share`): `label_raw` **또는** `section_path` 에 `주당` 이 있으면 주당 셀이다(배수 1, 허용오차 1원). `DB_SQL` 이 `section_path` 를 함께 읽는다.
배수 후보 집계·값 재정렬(`agrees`)·셀 비교 세 곳이 같은 판정을 쓴다.

**측정**: 미처리 이슈 중 `label_raw` 에 `주당` 이 없고 같은 라벨 행의 `section_path` 에 `주당` 이 있는 것 = 16건 / 3필링(전부 이 배치). 수정 후 세 필링 `compare_filing` = `clean`.
DB 데이터는 바뀌지 않는다(재적재 없음).

**회귀 테스트**: `fin2/tests/test_machine_compare.py::test_eps_child_rows_under_eps_section_are_unscaled`.

**같은 큐에서 다룬 것(value_mismatch)**:
- 에치에프알 2018FY `20190401005242` SCE 8건(#87632~#87744, batch #91): R201-c 와 같은 주석 열 오프셋 오탐이다(390c771 이전 커밋 `8103ac7f84` 에서 검출). DB 의 21~23 은 `주석` 열 값이다. 현재 도구로 재대조하면 `clean` 이다.
- 비투엔 2020FY `20210317000884` 별도 EPS 13.42 → DB 13(#88194·#88195, batch #92): `report_lines.value_won` 이 bigint 라 소수 EPS 는 전사 공통으로 정수가 된다. 표본 296필링 중 5건(약 1.7%)의 원문 EPS 에 소수가 있었다. 고치려면 스키마 변경이 필요하므로 사용자 판단(decision #4)을 기다린다.
