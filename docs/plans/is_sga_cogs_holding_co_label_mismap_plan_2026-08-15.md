# 계획 — 지주회사형 IS "영업비용" 라벨 오분류(`is.sga`/`is.cogs`) 조사+설계 (2026-08-15)

> 배경 = R19 검증 중 발견한 `is.cogs` 부수발견(한진중공업홀딩스). 조사해보니 진짜 메커니즘은
> **`is.sga`의 R16류 stage-rank 숏컷**이었고, `is.cogs`는 회사마다 다른 별도 문제였다.
> **이 계획은 문서일 뿐 — 실행은 별도 승인 후 착수**([정책](../../CLAUDE.md)).

## 요약

Gate B `fail_a` cogs 17건 중 3건(한진중공업홀딩스·두산·대성홀딩스)을 원문 XML 직접대조로
조사한 결과, 진짜 버그는 `is.cogs`가 아니라 **`is.sga`가 R16과 동일한 stage-rank 숏컷으로
오염**되는 것이었다. `is.cogs` 자체는 회사마다 증상이 다르다(정확/과소계상/충돌). 나머지
fail_a 2건(두산밥캣·세니젠)은 **이 문제와 전혀 무관한 별도 버그**로 확인해 범위에서 제외한다.

## 1. 핵심 메커니즘 — `is.sga` stage-rank 숏컷 (R16과 동일 계열, 대상만 다름)

원문 XML 직접대조(3개사 전부)로 확인된 공통 구조:

```
Ⅱ.영업비용 (ENG="Cost of sales", ACODE=ifrs-full_CostOfSales, 총계)
   (1) <매출원가류 서브라인> (1~2개)
   (2) 판매비와관리비 (서브라인)
```

세 회사 모두 총계 = 매출원가류 서브라인 합 + 판매비와관리비 서브라인(직접 검산 확인):
- 한진중공업홀딩스(00163673, `20250814001174.xml:7386`대): 611,638 + 43,566 = 655,204 ✓
- 두산(00117212, `20250814002379.xml:92254`대): (558,389+204,305) + 222,190 = 984,884 ✓
- 대성홀딩스(00108940, `20260319000799.xml:38172`대): (용역+통신매출원가) + 판매비와관리비 = 영업비용 ✓ (라벨만 확인, 금액 미검산이나 구조 동일)

`AccountMapper.map()` 실측(`parser/common/account_mapper.py`):

| 라벨 | 매핑 결과 | stage |
|---|---|---|
| "영업비용" | `is.sga` conf=1.0 | **exact** |
| "판매비와관리비"(서브라인) | `is.sga` conf=1.0 | normalized |

`fin2/layer3/combine.py::_STAGE_RANK = {"exact": 3, "normalized": 2, ...}` — `_resolve()`가
stage 숫자가 높은 "영업비용"(총계, exact)을 "판매비와관리비"(서브라인, normalized)보다
우선시켜 **`is.sga`에 총계(COGS+SGA 결합값)가 그대로 들어간다**. R16 문서(`docs/PARSING_RULES.md`
R16)가 이미 경고한 정확히 같은 취약점(`_resolve()`가 top-stage 후보로 collapse되면
`_reduce_conflict()`의 의미기반 필터를 건너뜀) — 다만 R16은 `is.revenue`/`bs.trade_payables`
가 대상이었고 이번엔 **`is.sga`가 처음 걸린 사례**.

**실측 확인**(std_financials_v3 직접조회, 2026-08-15):

| corp | sga(DB, 오염) | 실제 총계(참고) | 진짜 SG&A(서브라인) |
|---|---:|---:|---:|
| 한진중공업홀딩스 H1 2025 연결 | 655,204백만 | 655,204백만 | 43,566백만 |
| 두산 FY2024 별도 | 984,884백만 | 984,884백만 | 222,190백만 |
| 대성홀딩스 FY2025 별도 | 14,124,456,632 | 14,124,456,632 | (미검산, 서브라인 존재 확인만) |

즉 `is.sga` 값이 **총계와 완전히 동일** — R16 stage-rank 숏컷 증상과 정확히 일치.

## 2. `is.cogs` 자체는 회사마다 증상이 다르다 (일반화 금지, R16 교훈 그대로 적용)

| corp | 서브라인 구조 | 현재 `is.cogs`(DB) | 문제 |
|---|---|---:|---|
| 한진중공업홀딩스 | 매출원가류 서브라인 **1개** ("(1)매출원가") | 611,638백만 | **이미 정확**(순수 COGS와 일치) — 손댈 필요 없음 |
| 두산 | 매출원가류 서브라인 **2개**("상품 및 제품매출원가"+"기타매출원가") | 204,305백만 | "상품 및 제품매출원가"가 alias 테이블에 **없음**(`unknown.상품및제품매출원가`, conf=0) → 큰 쪽(558,389백만)이 통째로 누락, **과소계상** |
| 대성홀딩스 | 매출원가류 서브라인 **2개**("용역매출원가"+"통신매출원가") | 4,488,185,656 | 둘 다 `is.cogs`에 fuzzy매치(conf 0.96)돼 서로 다른 값 2개로 **충돌** — `_resolve()`가 어떻게 처리했는지 추가 확인 필요 |

→ **`is.cogs`는 corp마다 다른 원인이라 블랭킷 규칙 불가**(R16/R17이 이미 증명한 위험). 서브라인
합산이 필요한 corp는 R17 `_TRADE_PAYABLES_ADDITIVE_OVERRIDE`(corp+기간 3-튜플 키 + 합산할
라벨 목록) 패턴을 그대로 재사용할 수 있어 보이나, **회사마다 합산 대상 라벨 세트가 다르다**
(1개 vs 2개, 라벨 텍스트도 제각각) — 개별 검증 후 개별 등재 필요.

## 3. ★중요 — Gate B의 `report_won`(cogs) 자체가 이 회사군에겐 "순수 COGS"가 아니다

`face_audit.py`가 읽는 `report_won`은 XBRL `ACODE=ifrs-full_CostOfSales` 태그값을 그대로
쓰는데, 이 회사들의 XBRL은 그 태그를 **총계(COGS+SGA 결합)**에 붙였다(위 §1 구조).
**`is.cogs`를 아무리 정확하게 고쳐도(순수 COGS로), Gate B는 report_won(총계)과 다르다며
계속 fail_a를 띄울 것** — 이건 std_v3 데이터 버그가 아니라 **비교 대상 개념이 애초에 다른
것**이다. `is.sga`를 고치면 Gate B는 `sga` 필드도 새로 비교하게 될 텐데, `sga`용 XBRL
개념(`ifrs-full_SellingGeneralAndAdministrativeExpense` 등)이 이 필링들에 별도로 태깅돼
있는지도 미확인 — Phase 0에서 같이 확인 필요.

## 4. 무관한 두 건(같은 cogs fail_a 목록에 있었으나 이 트랙과 무관, 범위 제외)

- **두산밥캣(01032486)**: cogs 포함 **모든 필드**(total_assets·revenue·cfo 등 20여개)가
  동시에 report_won과 큰 배율차. 통화(USD 재무제표 원문 그대로 적재, [[fx-declared-statements]])
  관련 별도 이슈로 판단 — 라벨매핑과 무관. 이 트랙에서 손대지 않음, 별도 트랙 필요.
- **세니젠(01305869)**: `report_lines` 직접조회로 라벨매핑은 이미 정확함을 확인(label_raw="매출원가
  (주11,23,35,36)"→`is.cogs` exact). 문제는 **기재정정 체인**: FY2023 별도 원신고서
  (`20240321000444`/`20240327000615`, 2024-03-21/27 제출, cogs=19,229,612,227)와 **1년10개월
  뒤** 제출된 동일 회계연도 재제출(`20260130000582`, 2026-01-30, cogs=17,324,688,227)이 공존.
  `std_financials_v3.source_rcepts`는 후자를 가리키는데 실제 DB 값은 전자와 일치 — merge
  로직(`build_merged_lines()`, "최초등록본+순차 델타패치")이 이 늦은 재제출을 정상적인
  기재정정 델타패치로 인식하지 못하는 것으로 추정(미검증). 라벨매핑과 무관, 별도 트랙 필요.

## 5. 모집단 추정 (Phase 0에서 좁혀야 할 후보군)

```sql
-- report_lines 전체: IS에 "영업비용" 라벨은 있는데 "매출원가" 라벨이 전혀 없는 회사
```
결과: **166개사**. "영업비용"만 쓰고 "매출원가"를 전혀 안 쓰는 회사군 — 이 패턴(총계에
COGS+SGA를 묶어 "영업비용"으로 공시)에 노출됐을 가능성이 있는 후보. 지금 Gate B fail_a로
잡힌 3건은 **XBRL Track A 비교 데이터가 있어야 드러나는데(R18의 ACODE 커버리지 절벽 —
1999~2023 보유율 0.0%) 그게 최근 필링(2024+)에만 있어 빙산의 일각일 가능성**이 높다 —
`sga`가 이미 오염됐어도 XBRL 비교 데이터가 없는 회사·연도는 Gate B가 아예 못 잡고 조용히
넘어간다(침묵 오염, fail_a보다 나쁨).

부수: "상품 및 제품매출원가" 라벨은 **13개사**가 씀(두산 포함) — alias 테이블에 없어 전부
같은 방식으로 `unknown.`으로 빠지고 있을 가능성, 두산 전용이 아닌 **일반 alias 후보**로도
검토할 만함(Phase 0에서 같이 확인).

## 6. 설계 제안 (단계별, 승인 후 순서대로 착수)

### Phase 0 — 조사(읽기전용, 구현 전 필수) — ★완료(2026-08-15), 결과 `docs/qa/is_sga_cogs_holdco_phase0_scan_2026-08-15.md`
1. ~~166개사 후보군을~~ → 정밀 재확인 결과 **진짜 대상은 46개사**(309개사 중 §1 패턴 항등식이
   실제로 성립하는 것만). XBRL 교차검증은 `fact_v2`가 아니라 Gate B와 동일 경로
   (`read_report_face_xbrl` 원문 재파싱)로 수행 — `ifrs-full_CostOfSales` 총계 태깅 확인은
   **4개사·15건, 전부 2024~2026년**(00143527 신규 발견 포함). 상세는 위 QA 문서 참고.
2. `is.sga`용 XBRL 개념은 `ifrs-full_SellingGeneralAndAdministrativeExpense`가 아니라
   `dart_TotalSellingGeneralAdministrativeExpenses`(concept_map.py 기존 매핑) — **5개사**에서
   태깅 확인, 두산은 총계+SGA 둘 다 동시 태깅(Phase 3 (b) 옵션 가능), 한진중공업홀딩스·
   대성홀딩스는 SGA 개념 없음(Phase 3 (b) 불가) → **Phase 3은 회사별로 갈릴 수 있음**.
3. "상품 및 제품매출원가"는 13개사가 아니라 **7개사**, target 46개사와 겹치는 건 두산 1개뿐.
   4개 라벨 변형 전부 충돌 없이 `unknown.`으로 일관 실패 — 일반 alias 추가 저위험으로 판단.
4. 세니젠류 기재정정 체인 병합 문제는 **범위 밖으로 명시 확정**(별도 트랙 티켓화만) — 변경 없음.

### Phase 1 — `is.sga` 수정 (우선, 상대적 저위험 — R16과 동일 패턴 재사용)
Phase 0에서 검증된 corp만 curated override 등재(R16 `_REVENUE_TOTAL_OVERRIDE_CORPS`와 같은
자리, 같은 원칙 — 블랭킷 금지):
- `_SGA_SUBLINE_OVERRIDE_CORPS`(가칭, `fin2/layer3/combine.py`): "영업비용"(exact) 대신
  "판매비와관리비"류 서브라인(normalized)을 stage-rank 이전에 우선 채택.
- stage-rank 이전 지점(`_resolve()` 진입 전, R15/R16과 같은 자리)에 필터 삽입.

### Phase 2 — `is.cogs` 수정 (더 복잡, 회사별 개별 검증 필요)
- 서브라인 1개뿐인 회사(한진중공업홀딩스류): 이미 정확 — **손대지 않음**.
- 서브라인 2개 이상 합산이 필요한 회사(두산류): R17 additive override 패턴(corp+기간 키 +
  합산 라벨 목록) 재사용, 회사별 개별 원문대조 후 개별 등재.
- fuzzy 충돌이 나는 회사(대성홀딩스류): `_resolve()`가 실제로 어떤 값을 뱉는지부터 재현·확인
  후 별도 처방 결정.

### Phase 3 — Gate B 비교 로직 조정 여부 결정 (★사용자 결정 필요)
§3에서 확인한 "report_won(cogs)=COGS+SGA 결합값" 문제를 어떻게 처리할지:
- (a) 이 curated corp군은 `face_audit.py`에서 cogs 비교를 `pending`(범위밖)으로 예외처리, 또는
- (b) `is.cogs`+`is.sga` 합을 report_won과 비교하도록 Gate B 쪽 로직 추가, 또는
- (c) 그냥 놔두고 "구조적으로 못 맞는 fail_a"로 문서에 기록만.
Phase 1/2를 구현해도 (a)/(b) 없이는 이 corp들의 cogs fail_a가 안 사라질 수 있음을 미리 인지.

### Phase 4 — 백필 + 검증
Phase 1/2 확정 corp만 scoped 백필(`build_std_v3.py --corp <확정 목록>`) + Gate B scoped
재검증(`gateb_audit.py --corp-file <확정 목록> --recheck`), R16/R17과 동일 절차.

## 7. 리스크 / 열린 질문 (사용자 결정 필요)

1. **Phase 0 스캔 범위** — 166개사 전부 원문 자동스캔할지, 아니면 fail_a로 이미 잡힌 3개사만
   우선 구현하고 나머지는 후속 트랙으로 미룰지.
2. **Phase 2(is.cogs) 착수 여부** — Phase 1(sga)보다 훨씬 복잡하고 회사별 개별 처방이 필요해
   투입 대비 효과(회사 수가 적을 수 있음)를 먼저 가늠할지.
3. **Phase 3 방향** — (a)/(b)/(c) 중 어느 쪽으로 갈지는 `face_audit.py` 설계 철학(무엇을
   "정답"으로 볼지)에 대한 결정이라 사용자 판단 필요.
4. **"상품 및 제품매출원가" 일반 alias 추가 여부** — corp-curated가 아니라 alias 테이블
   자체를 바꾸는 거라 R16이 경고한 블랭킷 리스크와 같은 종류의 검토 필요(13개사 전수 확인 후).

## 근거
`fin2/layer3/combine.py`(`_resolve`/`_STAGE_RANK`/R16 override 자리) ·
`parser/common/account_mapper.py`(AccountMapper) · 원문 XML 직접대조 3건(한진중공업홀딩스
`20250814001174.xml`·두산 `20250814002379.xml`·대성홀딩스 `20260319000799.xml`) ·
`docs/PARSING_RULES.md` R16(stage-rank 숏컷 선례) · R17(additive override 선례) ·
[[note-ref-guard-r19-phase3-verify-done-2026-08-15]](이 부수발견의 출처).
