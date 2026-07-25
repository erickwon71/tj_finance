# 계획 — std_v2→std_v3 브리지 swap (L3-5 선행, C-1 포함) 2026-07-25

> 상태: **계획 초안 (미실행)**. 사용자 결정(2026-07-25): **브리지 swap 선행** → 그 위에 C-1(계층4)
> 자동. 최종 목표 = **v2 제거·v3 단독**. 마스터 허브 [`rearchitecture_4layer.md`](rearchitecture_4layer.md).
> 관련: [`layer4_industry_tearsheet_design_2026-07-24.md`](layer4_industry_tearsheet_design_2026-07-24.md)(C-1 설계) ·
> [`financial_sector_revenue_standards.md`](financial_sector_revenue_standards.md)(금융 revenue 표준) · 메모리 [[rebuild-phase-a3-done]]

---

## 0. 한 줄 요약
앱의 단일 read 지점인 뷰 `standard_financials` 를 **std_v2 → std_v3 로 전환**한다. std_v3 는 (a) 2015+
만 있고 (b) enrichment 컬럼 15개가 없으므로: **enrichment 를 std_v3 가 네이티브 산출**(사용자 결정
"새 술은 새 부대에" — capex/fcf/net_debt=combine+run_rules, D&A/ebitda=cf_da 백필, shares_out=shares
백필)하도록 빌드를 확장하고, pre-2015 이력만 std_v2 를 UNION(브리지). 비금융 회귀 0·이력 무손실을
게이트로 확인하면, **C-1(금융 tearsheet·스크리너 정규화 revenue)은 뷰가 industry_lines·조립 revenue 를
이미 실어주므로 자동 성립**한다.

## 1. 배경 — 왜 swap 선행인가 (실측)
- 앱의 모든 재무 read = 뷰 `standard_financials`(collector/db.py:160) → `std_financials_v2`.
  read 위임: `analyzer.ratio_engine.load_standard_financials` → `app/data/series.py`·`screen_window.py`·
  tearsheet 등 ~20 파일.
- **최종이 v3-only** 이므로, C-1 을 std_v2 위에 얹는 타깃 배선은 전부 버릴 코드(설계 §3 이 경계한
  사이드채널). 뷰를 v3 로 돌리면 C-1 은 공짜로 따라온다.
- 단, 지금 당장 뷰만 교체 불가 — 아래 2개 관문.

### 1.1 관문 A: 컬럼 15개 부재 → **v3-native 산출** (사용자 결정 2026-07-25, "새 술은 새 부대에")
enrichment 을 std_v2 에서 빌리지 않고 **std_v3 가 스스로 산출**한다. v3 combine 이 이미 v2 와 **동일한
mapper·rules 모듈**(`get_mapper()`·`from fin2.standardize.rules import DIRECT_MAP, CONSUMED_CANON`)을
쓰므로 재사용이 깨끗하다.

| 컬럼 | v3-native 산출 방법 | 소스·커버리지 |
|---|---|---|
| `capex` | v3 combine 이 CONSUMED_CANON(cf.capex/cf.capex_intangible) resolve → `rule_additive_capex` | **report_lines CF**(유형·무형자산취득 존재) → 풀커버(~95%) |
| `depreciation`·`amortization`·`da_total` | **`fin2/extract/cf_da.py` 를 std_v3 대상 백필**(주석+CF본문 face 추출, 자립) → `rule_additive_da` | raw 보고서 주석/CF본문(report_lines 아님) → v2 와 **동일 ~34%**(주석이연·안 나빠짐) |
| `ebitda` | `rule_derive_ebitda`(=operating_income + da_total) | da_total 의존(~34%) |
| `fcf` | `rule_derive_fcf`(=cfo + capex, capex 음수) | 풀커버(cfo·capex 있음) |
| `net_debt` | `rule_derive_net_debt`(=short+long_debt − cash) | 풀커버(BS) |
| `shares_out` | **`fin2/extract/shares.py` 를 std_v3 대상 백필**(보고서 주식수, 자립) | raw 보고서 → 풀커버(~95%) |
| `data_quality` | v3 DQ 룰 이식(항등식+교차연도) 또는 기본치 | 산출 |
| `gate_b_status`·`version`·`is_ifrs`·`rcept_no`·`calculated_at` | face_audit v3 조인 / 상수·메타 / source_rcepts→rcept_no / 뷰에서 채움 | — |

> ★핵심(확정): report_lines 엔 **주석(note)이 없다**(CF·BS·SCE·IS 뿐). 그래서 D&A/EBITDA 는 report_lines
> 만으로 못 만들고 **cf_da.py(주석+CF본문 추출기)를 std_v3 대상으로 실행**해 백필한다 — v2 와 동일 소스·
> 동일 34% 가 v3 로 그대로 넘어옴(더 나빠지지 않음). **D&A 완성(주석 전량 적재)은 이 swap 과 무관한 별도
> 이연 트랙.** capex/fcf/net_debt/shares_out 은 CF/BS/주식수 유래라 v3-native 풀커버.
> ⇒ 재사용 자산: combine 의 canon resolve + `run_rules(ctx)` + `cf_da.recover_cf_da` + `shares.extract_*`.

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
        v3.capex, v3.depreciation, v3.amortization, v3.da_total,       -- v3-native(신규 컬럼)
        v3.ebitda, v3.fcf, v3.net_debt,                                -- v3 빌드가 run_rules 로 산출
        v3.shares_out, v3.data_quality,                               -- v3 백필/DQ
        v3.industry_lines,                            -- ★C-1 핵심(신규 노출)
        COALESCE(fa.gate_status,'unaudited') AS gate_b_status
FROM std_financials_v3 v3
LEFT JOIN face_audit fa ON (...)          -- gate 는 v3 audit 준비 전까지 v2 face_audit 조인 유지
WHERE v3.fiscal_year >= 2015
UNION ALL
-- (2) ≤2014 : 기존 std_v2 뷰 로직 그대로(브리지·이력, pre-2015 2차패스 완료 시 제거)
SELECT ... FROM std_financials_v2 s ... WHERE s.fiscal_year < 2015 AND (기존 필터);
```
- **std_v3 스키마 확장**: capex·depreciation·amortization·da_total·ebitda·fcf·net_debt·shares_out·
  data_quality 컬럼 추가(§4-1). 뷰는 v3 를 직접 노출(v2 조인 없음 — 순수 v3-native).
- **신규 컬럼 `industry_lines`**(jsonb)를 뷰에 추가 노출 → C-1 소비.
- ⚠ 2015+ 에서 v2엔 있고 v3엔 없는 corp-year → 뷰에서 빠짐 → 커버리지 게이트(§5 G1)로 감지·목록화.

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

## 4. 구현 순서 (v3-native)
1. **std_v3 스키마 확장**: `ALTER TABLE std_financials_v3 ADD` capex·depreciation·amortization·
   da_total·ebitda·fcf·net_debt·shares_out·data_quality (+ 필요 메타). collector/models.py 반영.
2. **v3 combine/build 확장**: combine 이 CONSUMED_CANON(cf.capex 등) resolve → `StdContext(canon,col)` 구성
   → `run_rules(ctx)` 로 capex/da/ebitda/fcf/net_debt 산출 → build 가 새 컬럼 persist.
3. **백필 추출기 v3 배선**: `cf_da.recover_cf_da`(D&A)·`shares.extract_*`(shares_out)를 std_v3 대상으로 실행.
   (기존 std_v2 백필과 동일 로직·소스, 타깃만 v3.) data_quality DQ 룰 이식 or 기본치.
4. **std_v3 전량 재빌드**(`build_std_v3 --all`, ~25분) + 백필 실행. enrichment 채움율 v2 대비 확인.
5. **뷰 교체**(collector/db.py `_ensure_views` standard_financials DDL → §2). idempotent CREATE OR REPLACE.
6. **회귀 게이트 실행**(§5). 통과 못 하면 롤백(뷰 한 줄 되돌림 — 데이터 무변경).
7. **C-1 렌더**(뷰 통과 후): tearsheet 금융블록 + 스크리너 revenue. 실제 industry_lines 형태 기준.
8. **문서·메모리 갱신**, L3-5 진행표 반영.

> 단계 1~4 = std_v3 를 v2 컬럼 파리티까지 끌어올리는 빌드작업(코드+재빌드). 5~7 = swap+C-1.
> 1~4 를 먼저 커밋·검증 후 5(뷰 교체)로 넘어가면, 뷰 교체 리스크가 격리된다.

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
1. **pre-2015 2차 패스**: std_v3 백필 1997~2014 → 뷰 (2) UNION 구간 제거 → v2 폐기 가능.
2. **v3-native 품질게이트**: face_audit(gate_b)를 std_v3 기준 재구성 → 뷰의 v2 face_audit 조인 제거.
3. **주석 전량 적재**: D&A/EBITDA 커버리지 34%→향상(swap 무관 별도 트랙, cf_da 소스 확대).
4. **데일리 파이프라인**: report_lines·std_v3 를 collect_new.py **두 call site** 배선(runbook).
5. **야간 잡 재설치**(deploy/launchd, 현재 전량 삭제)·최근 IPO sync 재개.
6. std_v2·구 체인(fact_v2·text 트랙) 제거 → **v3 단독**.

## 8. 다음 액션 (이 문서 검토 후, 별도 실행요청 대기)
- 결정 완료: enrichment = **v3-native**(사용자 "새 술은 새 부대에", §1.1). 브리지는 pre-2015 이력 UNION 만.
- 검토 포인트: ① std_v3 스키마 확장 컬럼 계약(§1.1 표) ② 브리지 뷰(§2) ③ G1~G4 게이트(§5) ④ 착수 순서(§4).
- 승인 시 착수 = §4 순서(스키마→combine/build 확장→백필→재빌드→뷰 교체→게이트→C-1). 1~4 선커밋·검증 후 5.
