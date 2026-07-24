# 계획 — std_v2→std_v3 브리지 swap (L3-5 선행, C-1 포함) 2026-07-25

> 상태: **계획 초안 (미실행)**. 사용자 결정(2026-07-25): **브리지 swap 선행** → 그 위에 C-1(계층4)
> 자동. 최종 목표 = **v2 제거·v3 단독**. 마스터 허브 [`rearchitecture_4layer.md`](rearchitecture_4layer.md).
> 관련: [`layer4_industry_tearsheet_design_2026-07-24.md`](layer4_industry_tearsheet_design_2026-07-24.md)(C-1 설계) ·
> [`financial_sector_revenue_standards.md`](financial_sector_revenue_standards.md)(금융 revenue 표준) · 메모리 [[rebuild-phase-a3-done]]

---

## 0. 한 줄 요약
앱의 단일 read 지점인 뷰 `standard_financials` 를 **std_v2 → std_v3 로 전환**한다. std_v3 는 (a) 2015+
만 있고 (b) enrichment 컬럼 15개가 없으므로, **브리지 뷰**로 전환한다: 2015+ 코어·`industry_lines`·
조립 revenue 는 std_v3, enrichment 컬럼은 당분간 std_v2 에서 빌려오고, pre-2015 는 std_v2 를 UNION.
비금융 회귀 0·이력 무손실을 게이트로 확인하면, **C-1(금융 tearsheet·스크리너 정규화 revenue)은 뷰가
industry_lines·조립 revenue 를 이미 실어주므로 자동 성립**한다.

## 1. 배경 — 왜 swap 선행인가 (실측)
- 앱의 모든 재무 read = 뷰 `standard_financials`(collector/db.py:160) → `std_financials_v2`.
  read 위임: `analyzer.ratio_engine.load_standard_financials` → `app/data/series.py`·`screen_window.py`·
  tearsheet 등 ~20 파일.
- **최종이 v3-only** 이므로, C-1 을 std_v2 위에 얹는 타깃 배선은 전부 버릴 코드(설계 §3 이 경계한
  사이드채널). 뷰를 v3 로 돌리면 C-1 은 공짜로 따라온다.
- 단, 지금 당장 뷰만 교체 불가 — 아래 2개 관문.

### 1.1 관문 A: 컬럼 15개 부재 (뷰 50 vs std_v3 35)
| 컬럼 | 소스 전략(브리지) | v3-native(후속) |
|---|---|---|
| `ebitda`·`fcf`·`net_debt`·`da_total`·`rcept_no` | **뷰에서 파생** (op_income+da / cfo−capex / 차입−현금 / dep+amo / source_rcepts) | 동일(뷰 파생 유지) |
| `capex`·`depreciation`·`amortization` | **std_v2 에서 조인 차용**(2015+; CF/notes 유래라 profile 무관) | v3 combine 에 canon 추출 추가(rule_additive_capex/da 재사용) |
| `shares_out` | std_v2 에서 조인 차용(보고서 유래·profile 무관) | shares 백필을 v3 대상으로 실행 |
| `data_quality`·`gate_b_status` | std_v2 조인 차용(품질게이트 유지) | v3 DQ/face_audit 재구성 |
| `version`·`is_ifrs`·`calculated_at`·`superseded_at` | 상수/메타(뷰에서 채움) | 동일 |

> ★핵심: enrichment(capex/da/shares/dq)는 **revenue 와 독립**(op_income·CF·차입·현금·주식수는 프로파일
> 변경 무영향)이라, 2015+ 는 std_v2 값을 그대로 빌려도 정확하다. 그래서 **브리지에서는 build 확장 없이
> 조인 차용**으로 최소 위험·최속 전환. v3-native 이식은 **v2 완전제거 단계로 이연**(관문 A 후속 열).

### 1.2 관문 B: 커버리지 — std_v3 는 2015+ 만
- FY연결: 뷰(v2) 28,112 vs std_v3 23,282. 연도범위 v2=1997~2026 / **v3=2015~2026**.
- v2엔 있고 v3엔 없는 corp-year 8,615(대부분 pre-2015). **지금 v3 단독 전환 시 오래된 기업 이력 손실.**
- 브리지 해법: `standard_financials` = std_v3(2015+) **UNION ALL** std_v2(≤2014). 이력 무손실.
- pre-2015 **2차 패스**(std_v3 백필 1997~2014)는 후속 — 완료 후 UNION 의 v2 부분 제거 → v2 폐기.

## 2. 브리지 뷰 설계 (핵심 산출물)
```
CREATE OR REPLACE VIEW standard_financials AS
-- (1) 2015+ : std_v3 코어 + industry_lines + 조립 revenue, enrichment 는 v2 조인 차용
SELECT  v3.corp_code, v3.fiscal_year, v3.fiscal_period, v3.statement_type,
        1::int AS version, COALESCE(v2.is_ifrs, ...) AS is_ifrs,
        COALESCE(v3.source_rcepts->>0, ...) AS rcept_no,
        v3.total_assets, ... , v3.revenue, ... , v3.operating_income, ... , v3.net_income,
        v3.cfo, v3.cfi, v3.cff,
        v2.capex, v2.depreciation, v2.amortization, v2.da_total,      -- 차용
        (v3.operating_income + v2.da_total)          AS ebitda,        -- 파생
        (v3.cfo + v2.capex)                          AS fcf,           -- capex 음수저장
        (COALESCE(v3.short_term_debt,0)+COALESCE(v3.long_term_debt,0)-COALESCE(v3.cash,0)) AS net_debt,
        v2.shares_out, v2.data_quality,
        v3.industry_lines,                            -- ★C-1 핵심(신규 노출)
        COALESCE(fa.gate_status,'unaudited') AS gate_b_status
FROM std_financials_v3 v3
LEFT JOIN std_financials_v2 v2 ON (키 4개 일치 AND v2.version=1)
LEFT JOIN face_audit fa ON (...)
WHERE v3.fiscal_year >= 2015
UNION ALL
-- (2) ≤2014 : 기존 std_v2 뷰 로직 그대로(브리지·이력)
SELECT ... FROM std_financials_v2 s ... WHERE s.fiscal_year < 2015 AND (기존 필터);
```
- **신규 컬럼 `industry_lines`**(jsonb)를 뷰에 추가 노출 → C-1 소비.
- v2 뷰의 기존 필터(version=1·not stub·not discrete·gate≠fail_a)는 (2) 구간과 (1) 의 face_audit 조인에 유지.
- ⚠ std_v3 엔 있는데 std_v2 엔 없는 2015+ corp-year(v3>v2 증가분): enrichment=NULL 로 노출(허용,
  §5 게이트에서 수량 확인). 반대(2015+ v2 有 v3 無)면 그 corp-year 는 뷰에서 빠짐 → 커버리지 게이트로 감지.

## 3. C-1(계층4)이 자동 성립하는 이유
뷰가 `revenue`(프로파일 조립값)+`industry_lines`(성분·profile·gross_fallback·NULL)를 실어주면:
- **tearsheet**(`app/components/tearsheet.py`): series 행에 `industry_lines` 존재 → 재무요약 표의 매출액
  행을 업종 매출 구성 블록으로 치환(설계 4.2). **실제 industry_lines 형태**(구설계와 다름, ★반영):
  - insurance `{insurance_revenue, investment_revenue}` · bank `{interest_revenue, fee_revenue, insurance_revenue?, other_op_revenue?}`
  - **securities `{operating_income, sga}`(순영업수익) 또는 `{op_revenue_total, revenue_basis:"gross_fallback"}`**
  - **credit_finance `{interest_revenue, fee_revenue, other_op_revenue?}`**
  - revenue NULL(한국금융지주·override 등) → 영업이익 기준 표시(설계 4.3).
- **스크리너**(`app/data/screen_window.py`): revenue 소스가 뷰 → PSR·매출성장률 자동 정정(설계 5).
- 별도 사이드채널 reader 불요. 기존 read 코드 무변경(뷰가 계약 유지).

## 4. 구현 순서
1. **뷰 정의 교체**(collector/db.py `_ensure_views` 의 standard_financials DDL을 §2 브리지로). idempotent CREATE OR REPLACE.
   - 컬럼 순서·이름·타입 = 기존 50개 + `industry_lines` 신규. 기존 read 전부 호환.
2. **회귀 게이트 실행**(§5). 통과 못 하면 롤백(뷰 한 줄 되돌림 — 데이터 무변경이라 안전).
3. **C-1 렌더**(뷰 통과 후): tearsheet 금융블록 + 스크리너 revenue 표시. 실제 industry_lines 형태 기준.
4. **문서·메모리 갱신**, L3-5 진행표 반영.

## 5. 검증 게이트 (DoD)
- **G1 커버리지 무손실**: 뷰 corp-year 수(전 basis/period) ≥ 기존. 특히 pre-2015 전건 보존, 2015+
  누락 0(std_v3 미빌드로 빠지는 corp-year 목록화·허용여부 확인).
- **G2 비금융 회귀 0**: profile 없는 corp-year 표본(대량)에서 revenue·operating_income·net_income·
  ebitda·fcf·net_debt·shares_out·자산/자본 = 기존 뷰와 **완전일치**(std_v3 일반 revenue = std_v2 확인 포함).
- **G3 금융 정정**: 보험·은행·증권·여신전문 표본 revenue 가 조립값으로 바뀌고 industry_lines 노출.
  PSR 분모↑ 방향(작아짐) 확인. §금융섹터 원문대조(완료분)와 일치.
- **G4 앱 스모크**: tearsheet/스크리너/기업페이지가 뷰 교체 후 크래시 없이 렌더(대표 금융·비금융 각 수 사).

## 6. 리스크 / 롤백
- 뷰 교체는 **데이터 무변경**(CREATE OR REPLACE VIEW) → 롤백 = 이전 DDL 재적용(즉시·무손실).
- ⚠ enrichment v2 차용 = 2015+ 에서 v2 행이 없으면(신규 v3 corp-year) ebitda 등 NULL. 앱이 NULL 내성
  있는지 스팟(대개 있음 — 기존에도 결측 존재).
- ⚠ gate_b/data_quality 를 v2 에서 차용 → v3-native 품질게이트 재구성 전까지 v2 판정 의존(브리지 성격).
- ⚠ 뷰 컬럼 순서 변경 시 `SELECT *` 소비처 영향 없음(dict 매핑) 확인. `parity.py::_value_columns` 등
  뷰 컬럼 열거 코드 재확인.

## 7. 후속(브리지 이후 → v2 폐기)
1. **pre-2015 2차 패스**: std_v3 백필 1997~2014 → 뷰 (2) UNION 구간 제거.
2. **v3-native enrichment**: capex/da(rule_additive_* 재사용)·shares_out(백필)·DQ/gate 를 v3 에 이식 →
   뷰의 v2 조인 제거.
3. **데일리 파이프라인**: report_lines·std_v3 를 collect_new.py **두 call site** 배선(runbook).
4. **야간 잡 재설치**(deploy/launchd, 현재 전량 삭제)·최근 IPO sync 재개.
5. std_v2·구 체인(fact_v2·text 트랙) 제거 → **v3 단독**.

## 8. 다음 액션 (이 문서 검토 후, 별도 실행요청 대기)
- 검토 포인트: ① enrichment **v2 차용(권장)** vs 지금 v3 build 확장 ② 브리지 뷰 컬럼 계약 ③ G1~G4 게이트.
- 승인 시 착수 순서 = §4 (뷰 교체 → 게이트 → C-1 렌더).
