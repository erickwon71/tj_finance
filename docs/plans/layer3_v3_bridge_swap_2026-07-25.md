# 계획 — std_v2→std_v3 브리지 swap (L3-5 선행, C-1 포함) 2026-07-25

> 상태: **§4 단계 5(뷰 교체) 실행 완료(2026-08-09)**. 사용자 결정(2026-07-25): **브리지 swap 선행**
> → 그 위에 C-1(계층4) 자동. 최종 목표 = **v2 제거·v3 단독**. 마스터 허브
> [`rearchitecture_4layer.md`](rearchitecture_4layer.md).
> 관련: [`layer4_industry_tearsheet_design_2026-07-24.md`](layer4_industry_tearsheet_design_2026-07-24.md)(C-1 설계) ·
> [`financial_sector_revenue_standards.md`](financial_sector_revenue_standards.md)(금융 revenue 표준) · 메모리 [[rebuild-phase-a3-done]]
>
> **2026-08-09 갱신 — 뷰 교체 실행 결과**: `collector/db.py` 마이그레이션
> `2026_08_standard_financials_v3_bridge_swap` 로 `standard_financials` 뷰를 std_v3(2015+) +
> std_v2 UNION ALL 폴백(pre-2015 전체 + 2015+ 중 std_v3 미빌드 corp-period 6,390건)으로 교체.
> §2 원안(pre-2015만 UNION)에서 **폴백 조건을 확장**했다 — 2015+ 갭 6,390건(927개사, 대부분
> total_assets 등 실값 보유)을 그대로 두면 앱에서 사라지는 회귀가 생기므로, `NOT EXISTS`
> 조건으로 std_v3 미보유 2015+ corp-period 도 std_v2 로 폴백(G1 무손실 요구사항 충족).
> **G1 결과**: 구뷰 263,792행 → 신뷰 279,860행, **손실 0 · 순증 16,068**(std_v3 가 std_v2 에
> 없던 corp-period 도 보유). **G2 결과**: 2015+ 공통 corp-period(168,512건) 표본대조 시
> total_assets/revenue/net_income 등 핵심계정 2~6% 가 std_v2 와 값이 다름 — 표본조사(지아이에스
> 2019 basis_fallback 사례·00426068 2018 Q3 사례)로 원인 확인: **std_v2 쪽의 기존 버그**(비교연도
> 컬럼이 다른 시점 필링에서 잘못 유입되는 "comparative bleed" 패턴, own-report 원칙 위반)이고
> std_v3 가 이를 바로잡은 것으로 판단(정밀 전수감사는 미실행, 표본 근거). **G3**: 금융섹터
> industry_lines 정상 노출·revenue 성분합 정합 확인(기업은행 등). **G4**: `ratio_engine`
> 데이터 계층 스모크(삼성전자 10개년 무크래시, gate_b_status 전부 pass) — Streamlit UI 자체
> 풀스모크는 미실행. pytest 439 passed / 1 failed(기존에도 실패하던 무관 테스트,
> `test_lxintl_facility_table_dropped`, 뷰와 무관한 사업의내용 파서 이슈). **미커밋** — git 승인 대기.
> ⚠ **알려진 잔여 이슈**: `app/data/shareholder_return.py::load_dividend_series_for_chart` 가
> `standard_financials` 뷰를 거치지 않고 `std_financials_v2` 를 직접 조인(period_end 정렬용) —
> 이번 작업 범위 밖, v2 폐기 단계(§7-6)에서 함께 정리 필요.

---

## 0. 한 줄 요약
앱의 단일 read 지점인 뷰 `standard_financials` 를 **std_v2 → std_v3 로 전환**한다. std_v3 는 (a) 2015+
만 있고 (b) enrichment 컬럼 15개가 없으므로: **enrichment 를 std_v3 가 네이티브 산출**(사용자 "새 술은
새 부대에")하도록 하되 **아키텍처 준수**(계층3는 계층2 report_lines 만 읽음)로 —
capex/fcf/net_debt=combine+run_rules(✅완료), **D&A/ebitda= 계층2 주석 전사 선행 후** 계층3 파생,
shares_out= 계층2 일반현황 추출. pre-2015 이력만 std_v2 를 UNION(브리지). **G2(v3=원문 기준)** 통과 시,
**C-1(금융 tearsheet·스크리너)은 뷰가 industry_lines·조립 revenue 를 실어주므로 자동 성립**한다.
⇒ 선행 = [`layer2_notes_transcription_2026-07-25.md`](layer2_notes_transcription_2026-07-25.md).

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
| `depreciation`·`amortization`·`da_total` | **★계층2 주석 전사 선행** → combine 이 note.* 매핑 → `rule_additive_da`. (계층3가 보고서 직접 read 금지 — 아키텍처.) | 주석 소스, 계획 [`layer2_notes_transcription_2026-07-25.md`](layer2_notes_transcription_2026-07-25.md) |
| `ebitda` | `rule_derive_ebitda`(=operating_income + da_total) | da_total(=주석 전사 후) 의존 |
| `fcf` | `rule_derive_fcf`(=cfo + capex, capex 음수) | 풀커버(cfo·capex 있음) |
| `net_debt` | `rule_derive_net_debt`(=short+long_debt − cash) | 풀커버(BS) |
| `shares_out` | **계층2 일반현황 추출**(주식의 총수) → 별도 shares 테이블 권장(주석 전사 계획 §8) | raw 보고서 → 풀커버(~95%) |
| `data_quality` | 계층3 DQ 룰 이식(항등식+교차연도) 또는 기본치 | 계층3 값판단 |
| `gate_b_status`·`version`·`is_ifrs`·`rcept_no`·`calculated_at` | face_audit v3 조인 / 상수·메타 / source_rcepts→rcept_no / 뷰에서 채움 | — |

> ★핵심(2026-07-25 아키텍처 교정): report_lines 엔 **주석(note)이 없다**(CF·BS·SCE·IS 뿐). 계층3는
> **보고서를 직접 읽지 않는다**(계층2만 읽음). 따라서 D&A/EBITDA 는 **계층2가 주석을 report_lines 에
> 전사**한 뒤에야 계층3가 note.* 매핑으로 파생한다 → **선행 = [`layer2_notes_transcription_2026-07-25.md`]**
> **(layer2_notes_transcription_2026-07-25.md)**. (이전 초안의 "cf_da.py 를 std_v3 백필"은 계층3가 보고서를
> 읽는 아키텍처 위반 — 폐기.) capex/fcf/net_debt 은 CF/BS 유래·report_lines 에 이미 있어 계층3-native
> 풀커버(steps 1-2 완료). ⇒ 재사용: combine 의 canon resolve + `run_rules(ctx)`(capex/fcf/net_debt),
> 주석 전사 후 `rule_additive_da`(D&A).

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
1. **✅ std_v3 스키마 확장**(완료, `d43974e`): enrichment 9컬럼 ADD + collector/models.py.
2. **✅ v3 combine 확장**(완료, `d43974e`): CONSUMED_CANON resolve → `run_rules` 로 **capex/fcf/net_debt**
   산출(report_lines CF 유래). 스모크 삼성·SK·NAVER capex/fcf v2 완전일치.
3. **★선행 = 계층2 주석 전사**([`layer2_notes_transcription_2026-07-25.md`](layer2_notes_transcription_2026-07-25.md)):
   report_lines 에 주석 적재 → 계층3 combine 이 note.* 매핑으로 **D&A/da_total/ebitda** 파생. shares_out 은
   계층2 일반현황 추출(별도 shares 테이블). **이게 이 swap 의 선행 관문**(아키텍처: 계층3는 계층2만 읽음).
4. **std_v3 전량 재빌드**(`build_std_v3 --all`, ~25분) — 주석 반영 후. enrichment 채움율 원문 대비 확인.
5. **뷰 교체**(collector/db.py `_ensure_views` standard_financials DDL → §2). idempotent CREATE OR REPLACE.
6. **회귀 게이트 실행**(§5). ★G2 는 **v3=원문** 기준(v2 아님 — 예: 차입금은 v3 가 원문 단기차입금 라인,
   v2 는 XBRL 갭. v3 가 정답). 통과 못 하면 롤백(뷰 한 줄 되돌림 — 데이터 무변경).
7. **C-1 렌더**(뷰 통과 후): tearsheet 금융블록 + 스크리너 revenue. 실제 industry_lines 형태 기준.
8. **문서·메모리 갱신**, L3-5 진행표 반영.

> 순서: 1~2 완료. **3(계층2 주석 전사)이 선행 관문** → 4 재빌드 → 5 뷰교체(리스크 격리) → 6 게이트 → 7 C-1.
> capex/fcf/net_debt 은 이미 계층3-native. D&A/shares 만 계층2 선행 필요.

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
