# fin2 재설계 계획 + 세션 핸드오프 (2026-05-31)

> 새 세션에서 이 문서로 바로 이어서 시작할 것. context/quota 절약을 위해 이전 세션 종료.

## 한 줄 요약
report→DB(파싱/표준화) 계층을 새 스키마로 **병행 재구축(fin2/)**. 수집·다운로드는 완료·유지. golden 파리티 통과 후 **호환 view로 무중단 전환**. PostgreSQL 유지.

## ✅ Phase 0 완료 (2026-05-31) — 다음은 Phase 1
**완료 내역:**
1. **774 복구**: `git revert d3577ae`(→cf90295) + recalc-superseded + aggregate. **DQ=3=774 확인**.
   한양증권 2012 FY 별도 영업수익 193,144,577,956(=1,931억) 유지. ⚠ 리메드 등 ~200 over-supersede 손실 재유입(의도된 baseline; fin2 P3가 복구).
2. **golden 바스켓** `fin2/tests/golden/golden.yaml` + 러너 `golden_check.py` (PyYAML 추가). **5케이스, current 기대와 0 불일치**:
   - financial_x1000: 00162416 한양증권 2012 revenue (pass, ×1000 폭증 가드)
   - partial_amend(손실): 01275665 리메드 2023 con (**current=fail**, assets NULL/revenue 283,638 — fin2 P3 타깃, 정답 assets≈550.6억/rev≈185.4억)
   - partial_amend(정상): 01367586 제이아이테크 2020-22 별도 revenue (pass, 무회귀 가드)
   - pre_revenue: 01492651 큐로셀 2023 con (pass, 매출 0+자산 1,049.7억)
   - kgaap: 00327396 옵트론텍 2008 별도 자본 346.3억 (pass)
3. **파리티 하네스** `fin2/tests/parity.py` (capture/diff/report, 39컬럼 자동수집). baseline774 캡처(289,341행×39, `parity_baseline.json` gitignore). self-diff=0 검증.

**⚠ Phase 1 E-레이어가 풀어야 할 데이터 품질 발견:**
- **period_end 라벨링 신뢰 불가**: 현대바이오(00313649) FY2018→period_end 2020-06-17 등 fiscal_year↔period_end 불일치. 옵트론텍 FY별도 period_end=2009-02-18(공시일 누수). → ACONTEXT 기간 파싱(start/end)으로 정합 필요. **비12월 결산 golden은 이것 해결 후 추가**(현 DB에 깨끗한 표본 없음).
- **is_ifrs 플래그가 같은 기업/연도 내 FY(false)↔분기(true)로 뒤집힘**(옵트론텍 2008). taxonomy_version을 ACONTEXT/스키마에서 권위있게 도출.
- **K-GAAP 커버리지 희소**: 전체 DB에서 is_ifrs=false+자본 보유 FY행은 옵트론텍 2007/2008뿐.

**원래 계획에서 정정된 golden 표본**(현 DB 실측 불일치): 092440≡00106614(둘 다 기신정기, Dec결산이라 non-dec 부적합)·HPSP(2020 매출 611억으로 pre-revenue 아님)·휴메딕스(2012부터 IFRS로 K-GAAP 표본 아님) → 각각 큐로셀/옵트론텍 등으로 교체.

## 목표 아키텍처 (5단계)
`파일 →(E) fact_v2 →(R) statement_source →(S) std_financials_v2 →(V) DQ →(view) standard_financials`

- **E 추출 `fact_v2`**: 단위·기간·연결/별도·차원을 **추론 아닌 저장**. XBRL `ADECIMAL`(단위 권위)·`ACONTEXT`(구조 파싱: CON/SEP member 토큰, period_role/kind/accum/start/end, extra_dims) 완전 활용. 텍스트 proximity 단위탐지 폐기. is_superseded 컬럼 없음.
- **R 정합 `statement_source`**: (period,basis)별 **BS/IS/CF 각각 단일 source filing 선택** → statement 내부 정합 보장. 부분정정은 가진 statement만 이김(over-supersede·item혼합 둘 다 구조적 제거). lineage 기록.
- **S 표준화 `std_financials_v2`**: 현 컬럼 계약 동일 + lineage(bs/is/cf_rcept)+applied_rules. **규칙 엔진**(`fin2/standardize/rules.py`)으로 현 13개 휴리스틱을 명명·순서·테스트가능 규칙으로 이식.
- **V 검증**: 회계 항등식+교차연도 이상치 → data_quality.
- **호환 view**: `standard_financials`를 std_v2 위 view로(version=1 상수). analyze/screen/dcf/dividend/validate 무변경. 롤백=view drop+rename.

### XBRL-우선 핵심
- `fin2/extract/acontext.py`: ACONTEXT 구조 파싱. **현 버그 수정**: `dart_xml_parser.py:495` `"Consolidated" in acontext`가 축 이름 때문에 별도→연결 오분류. member 토큰(`SeparateMember`/`ConsolidatedMember`)으로 판정. 기타 축(ComponentsOfEquity 등)은 extra_dims로 합계 제외.
- `fin2/taxonomy/concept_map.py`: 40개 하드코딩 대체, DART/IFRS 전체 개념(+dart_*)→canonical, taxonomy_version. 미매핑은 unknown_accounts 기록.
- 단위=ADECIMAL만(`10**(-adecimal)`). AUNIT은 금액 단위 아님.
- 텍스트/PDF(`fin2/extract/text.py`·`pdf.py`)는 pre-2015/PDF-only 폴백으로 격리. 기존 table_extractor·section_detector·account_mapper·amount_normalizer·PDF 모듈 재사용.

## 단계별 (각 shippable, 구 파이프라인 무손상; 총 ~12~16일)
- P1: fact_v2 + XBRL 추출(2~3일)
- P2: 텍스트/PDF 폴백(2일)
- P3: statement_source 정합(1~2일)
- P4: 규칙 엔진 + std_v2(3~4일) → parity 전수 검증
- P5: 호환 view 전환(½일)
- P6: 구 파이프라인 폐기(추후)
오케스트레이션: `run.py extract2/reconcile2/standardize2/parity` + pytest.

## 핵심 파일
신규: `fin2/extract/{acontext,xbrl,text,pdf,__init__}.py`, `fin2/taxonomy/concept_map.py`, `fin2/reconcile.py`, `fin2/standardize/rules.py`, `fin2/validate.py`, `fin2/tests/golden/golden.yaml`, `fin2/tests/parity.py`, `scripts/migrate_fin2.py`. 스키마: `collector/models.py`에 fact_v2·statement_source·std_financials_v2.
재사용: collector/*, account_maps/*, parser/common/account_mapper.py, filings.is_amendment, unknown_accounts, verification_results.
규칙 원천: `analyzer/aggregator.py` 13개 휴리스틱(라인 472–696) → 규칙+golden으로 포착.

## 이번 세션 완료(커밋)
- 575e406 단위감사 규칙 정밀화
- **86ff88f XML 단위탐지 ×1000 수정** (가장 가까운 단위선언 채택; golden: 한양증권)
- d3577ae item-merge — **Phase 0에서 revert 대상**
- 그 외(commit c6299fe 이전): 비12월 결산 fiscal_month·fix-fiscal-years, 수집 완전성(NODL=0, 커버리지 98.9%, 기업별 갭/파싱 로그), 단위 audit·verify·download-original-pdf 등.

## 현재 DB 상태 주의
- item-merge(d3577ae)로 DQ=3=1,175 (774보다 악화). Phase 0 revert+재집계로 774 복구 필요.
- 단위 fix(86ff88f) 자체는 유효(한양증권 정상).

## 비범위
수집 재작성, 시각화, Phase 6(경영진/수주), DB 엔진 교체.
