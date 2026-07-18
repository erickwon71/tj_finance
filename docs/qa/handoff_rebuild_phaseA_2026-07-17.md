# 핸드오프 — 재무데이터 재구축 Phase A (2026-07-17)

> **다음 세션 시작점.** 마스터 계획 = `docs/plans/vast-nibbling-blum.md` (먼저 읽을 것)
> 상세 조사기록 = `docs/qa/plan_note_body_separation_2026-07-17.md`

---

## 0. 이 작업이 왜 시작됐나 (한 문단)

`extended_financials_n_facts_outlier` 트리아지 중 사용자 질문("주석에서 읽은 재무 data는 어떻게
처리하나?")에서 출발해, **주석·요약·단위추측 오염이 소비계층까지 도달**한 사실이 드러났다.
std_v2 에 물리적 불가값 **307행/56개 기업**이 DQ<3 으로 **앱에 정상 데이터처럼 노출** 중이다
(DB손해보험 2023 별도 이익잉여금 **8.5경원** 등). 조사 결과 **코드가 원본을 읽는 대신 추측**하고
(단위 배율 대입·max-abs 채택·항등식 강제) **그 추측을 기록하지 않아** 추측값과 원본값이 DB 에서
구분되지 않았다 → "오염된 것만 삭제"가 SQL 로 표현 불가 → **전수 재파싱 확정**.

---

## 1. 사용자 확정 원칙 (모든 판단에 우선)

> **"오염된 데이터는 없는게 더 좋아."**
> **"로직으로 값을 정해서 db에 적재하는 것은 없도록 해."**
> **"명확하지 않은 것은 나와함께 명확히하고 파서 개선하면서 넘어가고."**

1. **결측 > 오염.** 애매하면 넣지 않는다.
2. **추측·선택·강제 금지**(단위추측·max-abs·항등식강제·열위치추론).
3. **투명한 파생은 허용하되 표시 필수**(EBITDA=영업이익+D&A 등). 입력 하나라도 없으면 NULL.
4. **애매하면 사용자 확인 → 파서 개선.** **패턴 단위**로 묶어 대표 사례만 확인(값 하나씩 X).

**★ 사용자 협업 규칙**: *"네가 판단이 명확하지 않은 경우 해당 보고서를 직접 확인해 줄테니 매번
명확하지 않을때 내 확인을 요청해."* · *"과도한 금액 변화는 나에게 확인요청하면 될 것 같아."*
→ **추측하지 말고 원문 확인을 요청할 것.** 실증: 3S(진짜 결함)·네오크레마(진짜 결함)·
엔케이젠(정상·오탐)이 **모두 같은 신호**였고 사용자 원문 확인으로만 갈렸다.

---

## 2. 완료된 것 (이번 커밋)

### Phase A-1 — 섹션 기반 추출기 ✅
`parser/xml/section_detector.py` 신규 4함수:
- `classify_dart_section()` — DART `<SECTION-2><TITLE>` **정확일치** 분류(요약/연결재무제표/
  연결재무제표주석/재무제표/재무제표주석). 실측 TITLE 12종 검증 — 함정 배제 확인
  (`합병전ㆍ후의재무제표`·`연결재무제표에대한감사인의감사의견등`·`재무제표이용상의유의점`).
- `assign_tables_to_dart_sections()` — **문서 순서** 귀속(포함관계 X, 아래 함정1 참조).
- `table_direct_rows()` — **직접 행만**(깨진 XML 대응, 함정2).
- `normalize_dart_section_title()`

`fin2/extract/statement_titles.py`: `classify_statement_in_body_section()` — 섹션 내부 전용
BS/IS/CF 분류(공백·`반기`/`분기` 접두 허용, **자본변동표 배제**).

`fin2/extract/text.py`:
- `_detect_body_statement_tables()` → 섹션 기반으로 **전면 교체**
- **폴백 2종 폐지**: F4 레거시 `detect_sections` 갭필 · F5 `_extract_summary` 요약폴백
  (⚠ **되살리지 말 것** — 둘 다 실제 오염원. 코드에 이유 주석 있음)
- **max-abs dedup 폐지**(X1) → 값 충돌 시 **양쪽 다 보류**
- `_declared_unit()` — **명시 선언만**(표제 or 표 자기 첫행). 형제 스캔·기본값 제거
- `_table_has_data_rows()` — **콤마 금액 패턴** 요구(함정4)

### Phase A-2 — provenance 컬럼 ✅
`collector/models.py` + `collector/db.py` 마이그레이션 `2026_07_fact_v2_provenance`:
`section_kind` · `mapping_stage` · `mapping_confidence` · `unit_source`
→ **적용 완료**(20초, nullable·DEFAULT 없음 = PG11+ 메타데이터 전용, 87M 행 rewrite 없음).
⚠ 인덱스는 **의도적 미생성**(전 행 NULL이라 이득 없고 87M CREATE INDEX 는 테이블 장기 잠금).
재구축 후 별도 마이그레이션으로 추가할 것.

### Phase 1 어서션(출혈 차단) ✅
`scripts/dq_assertions.py`: `statement_magnitude_impossible`(ERROR, 307건 검출) ·
`statement_magnitude_spike`(WARN, 36건). 임계 실측 보정(자산 1,000조/자본·이익잉여금 500조/
매출 400조 — 삼성전자 2025 자산 567·자본 436·이익잉여금 402·매출 334조, KB금융 자산 830조 기준).
**오탐 0 확인.** ⚠ 절대임계로는 중간대역을 못 잡는다(코리아써키트 매출 339조 오염 < 삼성전자
334조 정상 — **구간이 겹침**) → spike 어서션이 보완.

### 검증 결과
```
DB손해보험 20230927000457 별도 이익잉여금
  구: 8,564,682,463,043,000,000 (8.5경)  →  신: 8,564,682,463,043 (8.56조) ✅
  (FY2023 정답 8.65조와 정합)
3S 20230209000202 → 여전히 ×10^6 = **정상 동작**(원문이 (단위:백만원) 오기 = garbage-in)
fin2 회귀 전체 GREEN (test_fiscal_relabel·test_notes 의 ModuleNotFoundError 는 사전존재·무관)
```

---

## 3. ★ 구현 중 실측으로 잡은 함정 4종 (다시 밟지 말 것)

| # | 틀린 가정 | 실측 반증 |
|---|---|---|
| 1 | SECTION-2 가 자기 표를 포함 → `.//TABLE` | DB손해보험은 **계단식 중첩**(각 섹션이 다음을 품음) → 연결재무제표 **777개**(본문8+주석769) |
| 2 | 표의 행 = `.//TR` | **깨진 XML**(`</TABLE>` 누락)로 wrapper 가 문서 전체를 품음 → BS 51행이 **5,218행** |
| 3 | 단위=표제 선언만 인정 | 표 **자신의 첫 행** 선언도 정당 |
| 4 | 데이터행 = 라벨+`\d{2,}` | 표제표의 **날짜('제4기 2023.12.31')가 숫자로 인식** → 표제표 147개가 데이터표로 오인(미선언 160개의 92%) |

**공통 교훈**: 구조 가정은 **반드시 실측으로 검증**할 것. 넷 다 그냥 넘어갔으면 고치려던
오염을 그대로 재현했다.

---

## 4. 남은 작업 — Phase A-3 (다음 세션 시작점)

**Tier 1 추측 로직 제거** (전수 인벤토리 = 계획서 §2-A). Phase A-1 에서 U1~U6(단위추측 일부)·
X1(max-abs dedup)·F4/F5(폴백) 처리됨. **남은 것**:

| # | 위치 | 할 일 |
|---|---|---|
| **M1/M2** | `parser/common/account_mapper.py:243-266` | 퍼지 매핑(부분포함 0.90~0.99·JW 0.88+). `text.py:123` 에서 `confidence`/`stage` 폐기 중 → **컬럼에 기록**하고 **fuzzy 는 `canonical=NULL`**(원문 보존) |
| **C3/C4/C5** | `build.py:94-107,117-133,389-404` | operating_income 재선택 · **controlling_ni 항등식 재선택** 제거(`run_rules` 이전 실행이라 `applied_rules` 기록 불가) |
| **C1/C6/C7** | `build.py:63-65,371-375`·`rules.py:78-81` | max-abs 채택 → 후보 전체 기록(`reconcile.lineage` 패턴) |
| **X4~X7** | `table_extractor.py:219-225`·`text.py:269-285` | 열 위치 추론(→`col_index`+**`context_fiscal_year`**) |
| **F6/F7** | `build.py:146-157,292` | `period_end` 재구성(12월 가정)·**`is_ifrs=(fy>=2011)`** |
| **C17** | `build.py:166-177` | `shares_out` 을 주가테이블 최근접 거래일(−30/+7)에서 |
| **D8/D11** | `expense_nature.py:198-199`·`cf_da.py:70` | `note.da_total` 합성 |
| **rd_note** | `rd_note.py:49` | `root.findall(".//TABLE")` 전역스캔 = `text.py` 와 동일 결함 |

**모범 선례**(따를 것): `fin2/reconcile.py::select_source` 의 `lineage` JSONB(후보 전체+근거+
chosen 기록) · `quarterly.py`(is_discrete+DQ2) · `calendar.py`(derivation+source_lineage) ·
`fin2/extract/xbrl.py`(ADECIMAL 그대로 = 진짜 충실한 추출기).

이후 Phase B(대상 선별) → C(재구축+패턴루프) → D(검증). 상세 = 계획서 §4.

### ★ 모델 운용 권고 (작업 복잡도 기준)

| 구간 | 권장 | 이유 |
|---|---|---|
| **A-3 대부분** — M1/M2 매핑기록 · C1/C6/C7 max-abs 제거 · F6/F7 · C17 · D8/D11 · rd_note | **Sonnet 으로 시작** | 위 표에 **위치·할 일이 특정**돼 있고 따를 모범(`reconcile.lineage`)도 정해져 있다. "이 줄 제거하고 후보를 기록" 식의 기계적 적용이 대부분 |
| **A-3 중 C3/C4/C5**(`build.py` 항등식 재선택 제거) | **여기서 Opus 로 전환** | controlling_ni 재선택은 과거 대형 사고 지점(총포괄 오염 16,114행 여정). 제거 시 **어떤 값이 되살아나는지** 판단이 필요하고, `run_rules` 이전 실행이라 기록도 안 남아 영향 추적이 어렵다 |
| **Phase C 패턴 루프**(애매건 분류 → 사용자 확인 → 파서 개선) | **Opus** | 판단·설계의 연속. Phase A-1 처럼 **가정이 틀렸음을 실측으로 잡아내는** 작업 |

**근거**: Phase A-1 에서 구조 가정이 **4번 틀렸고**(§3) 매번 반증 설계가 필요했다 — 코드 작성이
아니라 **의심과 검증**이 본질인 구간이었다. 반면 A-3 앞부분은 대상이 이미 확정돼 있다.

---

## 5. 범위 (사용자 확정)

- **Track 1 = 2015+ 만** (86,699건·57.9%). 구형은 Track 3.
- **최초 보고서만** — 정정본은 fact_v2 에서도 제외(추출 대상 배제) → **Track 2** 에서 재편입.
  ⚠ `is_amendment` **사용 금지**([기재정정] 23,000 만 잡고 **[첨부정정] 1,145 누락**) →
  `report_nm NOT LIKE '%정정%'` 사용. 판정은 **(기업,기간) 단위**(보고서 단위 X — 리메드 사례).
- **다른 테이블**(order_backlog·biz_metrics 등)은 범위 밖 — 단 **오염 없음이 아님**(계획서 §4-A).

### 시대별 서식 (실측)
| 시대 | 구조 | 건수 | 본문검출 |
|---|---|---|---|
| **2015+** | 표준 5섹션 | **86,699 (57.9%)** | ✅ |
| 2014 | 혼재 | 7,090 (4.7%) | 일부 |
| 2009~2013 | **`XI. 재무제표 등`** + `<P>` | 31,444 (21.0%) | ❌ Track 3 |
| 2000~2008 | `III` 만. 위치 **미확인** | 24,473 (16.3%) | ❌ Track 3 |

---

## 6. ⚠ 실행 전 반드시 인지할 리스크

1. **`shares_out` 소실**: `shares.py` 가 `std_financials_v2` 에 쓰므로 **재구축 시 날아간다**
   → **직후 재백필 필수**. 놓치면 `valuation_daily`(PER/PBR/시총) 전부 NULL.
2. **Track A(XBRL) 가 fact_v2 의 21.6%**(18.6M팩트/16,384보고서). Track B 만 재구축하면
   **DB 의 1/5 이 옛 방식**으로 남는다. 영향 확인은 보류 중 → 나중에 확인 시 **재파싱 2회** 위험.
3. **소비자 영향**: 앱·valuation_daily·스크리너가 std_v2 를 읽는다 → 신규 테이블 구축 후
   **교체(swap)** 검토.
4. **Track 1 이 2015+ 한정이라 그동안 과거 데이터가 DB 에서 빠진다**(장기 시계열·백테스트 영향).

---

## 7. 보류 목록 (사용자: "다 뒤로 미뤄")

1. 307행 DQ=3 격리 여부 — 그동안 앱은 8.5경원 등 계속 노출.
   목록 = `docs/qa/list_impossible_values_exposed_2026-07-17.md`(56사·255건·DART 링크)
2. 제외 리스트(본문없음·정정본만 108개 기간) 사후 처리 + 규모 전수 측정
3. Track A 영향 확인
4. ~~Phase 1 어서션 desc 문구 정정~~ → **이번 커밋에서 완료**
5. `order_backlog` 납기 컬럼 추가(납기 기반 잔고 판정의 전제 — 현재 스키마에 없음)
6. `app/data/order_backlog.py:43` 단위 혼합 합산 버그(`sum(backlog_amt)`+`max(unit)`)
7. `shares.py` 단위 로직 부재(`(단위:천주)` 시 1000배 과소)
8. **외화 표시 재무제표** — `(단위:CNY)`·`(단위:USD)`. 현재 적재 거부(정답). FX 환산 설계 필요.
   실측 1.6%.

---

## 8. 재현용 명령

```bash
# 회귀
for f in fin2/tests/test_*.py; do python "$f"; done   # fiscal_relabel·notes 는 사전존재 오류

# 핵심 검증(8.5경 사고 원본)
python -c "
from fin2.extract.text import extract_facts
f = extract_facts('raw_report/KOSPI/00159102_DB손해보험/half/2023/20230927000457.xml',
    rcept_no='20230927000457', corp_code='00159102',
    report_fiscal_year=2023, report_fiscal_period='H1')
print([x.amount_won for x in f
       if x.canonical_account=='bs.retained_earnings' and x.basis=='separate' and x.col_index==0])
# 기대: [8564682463043]  (구버전: 8564682463043000000)
"

# 불가값 현황
psql -d tj_finance -c "
SELECT data_quality, count(*) FROM std_financials_v2 WHERE version=1
 AND (abs(total_assets)>1e15 OR abs(total_equity)>5e14
      OR abs(retained_earnings)>5e14 OR abs(revenue)>4e14) GROUP BY 1;"
```
