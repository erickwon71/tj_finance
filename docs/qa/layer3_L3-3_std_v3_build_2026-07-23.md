# L3-3 std_v3 빌드 — 스키마 + 빌더 프로토타입 (2026-07-23)

> 계획 = `docs/plans/layer3_rebuild_plan_2026-07-22.md`(L3-3) · 선행 = L3-1/L3-1b/L3-2
> 코드 = `collector.models.StdFinancialV3` · `fin2/layer3/build.py` · `fin2/layer3/combine.py:combine_full`
> 드라이버 = `scripts/build_std_v3.py`

## 0. 한 줄
계층3 산출 테이블 `std_financials_v3` 생성 + report_lines→std 조립 빌더. std_v2 값 계약
미러링 + **provenance**(정본filing·기재정정 반영표시·basis폴백·충돌). 샘플 3사 검증:
std_v2 대조 MATCH 334·DIFF 1·v3만 41(복구분). 삼성전자 4년 전지표 완벽일치.

## 1. 스키마 (`std_financials_v3`)
- grain = (corp_code, fiscal_year, fiscal_period, statement_type=basis). 멱등(키 단위 delete-then-insert).
- 값 컬럼 = std_v2 미러링(BS/IS/CF DIRECT_MAP 산출분). 합산/파생(D&A·EBITDA·차입합계·capex)은 후속.
- **provenance(구 체인엔 없던 것)**:
  · `source_rcepts` {statement: rcept} — 각 재무제표를 읽은 정본 filing(statement 단위, L3-1b).
  · `amended_cols` — 기재정정 반영으로 값이 온 std 컬럼(최초등록본+델타패치).
  · `amend_chain` {std_col: [rcept…]} — 그 컬럼을 고친 정정본 순서(as-filed 복원·감사용).
  · `basis_fallback` — 단일 basis 기업 반대 basis 폴백 사용(L3-2).
  · `conflicts` — 값 갈려 보류한 canonical(결측 근거).

## 2. 빌더 (`build_corp`)
`combine_full`(조립+provenance) 호출 → DIRECT_MAP 값 + provenance 를 std_v3 행으로. corp 단위
루프, (corp,fy,period,basis) 멱등. combine 은 (col,conflicts) 2-tuple 래퍼로 유지(프로브 무회귀).

## 3. 검증 (샘플 3사: 흥국화재·삼성전자·KG케미칼, 270행)
std_v3 ↔ std_v2 (FY 2015+, 6지표):
- **MATCH 334 · DIFF 1 · v3만 41 · v2만 13** (대조가능 389).
- **v3만 41** = split-table 백필로 복구된 흥국화재 등 연도(v2 는 gap 이었던 것) → 신 체인 우위.
- **삼성전자 4년(2022~25) 전지표 완벽일치**(revenue 300조대 정확).
- **DIFF 1** = 흥국화재 2023 separate revenue v3=0 vs v2=2.6조. 원인: 정답 `1.보험영업수익`
  =2.6조가 stage=fuzzy 인데, 값 0 인 하위항목 `(3)보험료수익`이 stage=normalized(상위) → _resolve
  가 0 채택. **엔진 버그 아님 = account_maps 보험 매출 alias 롱테일**(보험영업수익 승급 필요).

## 3b. 전량 빌드 완료 (2026-07-23)
- **185,208행 · 2,534사 · 25분**. 전 기간 커버(Q1 49,130·FY 46,545·Q3 45,024·H1 44,509).
- provenance: **정정반영(amended array) 3,328행** · basis폴백 18,744 · 충돌보류 있는 행 56,198.
- 성능: 매핑 lru_cache + 병합 재사용으로 대형사 30s→4s(7.5×). 전량 25분.
- ⚠ provenance 버그 수정(커밋): 원본 없이 [기재정정]본만 있는 기간(603)에서 베이스 셀 전체가
  amended 오표시 → i==0(베이스)은 amended=False 로 교정(값 무관, 플래그만).
  · JSONB 주의: 빈 값이 SQL NULL 아니라 JSONB `null` 스칼라로 저장됨 → 배열 카운트는
    `jsonb_typeof='array'` 로. (기능상 무해)

## 3c. L3-4 전수 parity baseline (std_v3 ↔ std_v2, FY version=1)
| 지표 | both | MATCH% | DIFF | v3only | v2only |
|---|---:|---:|---:|---:|---:|
| total_assets | 42,450 | 98.2 | 744 | 167 | 82 |
| total_equity | 42,385 | 98.3 | 716 | 204 | 106 |
| revenue | 41,284 | 98.7 | 546 | 296 | 914 |
| operating_income | 42,503 | 98.6 | 615 | 118 | 61 |
| net_income | 42,321 | 97.8 | 922 | 113 | 230 |
| retained_earnings | 41,984 | 98.2 | 736 | 295 | 250 |
| cfo | 42,143 | 98.7 | 531 | 174 | 189 |
| cash | 41,884 | 99.1 | 379 | 161 | 569 |

**MATCH ~98% 전 지표.** DIFF 성격(net_income 922 표본): **353(38%)이 amended=v3 재작성 반영**
(정책 P1 대로, 구 체인과 다르나 오히려 정확 — 회귀 아님). 나머지 569=카탈로그/부호/반올림(L3-4
정제 대상). v3only=split-table 등 복구분. v2only(revenue 914 최다)=보험/증권 매출 alias +
비교열-소싱 잔여.

## 4. 판정 & 다음
- ✅ std_v3 스키마·빌더·provenance 동작. 일반사 완벽, parity 강함.
- ⚠ 보험/증권 매출 alias 롱테일(account_maps) — 소수. L3-4 parity 에서 유형 집계 후 일괄 정제.
- **다음 = 전량 빌드**(전 corp → std_v3, report_lines 로드처럼 배치) → **L3-4 전수 parity**
  (std_v3 ↔ std_v2 전수 대조, DIFF 를 정상불일치[재작성·연결범위] vs 회귀 vs 카탈로그로 분류).
- 이후 L3-5 swap(앱 재배선 + 구 체인 제거 + report_lines 데일리 배선).
- 후속: 합산/파생 규칙(rules.py additive) 이식 → D&A/EBITDA/차입/capex 컬럼.
