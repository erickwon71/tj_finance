# PRD 14 — Phase 3: 부문·수출/내수 매출 파서

> 마스터 계획: `10_gap_fill_plan.md`. 체크리스트: `10_16_checklist.md`. 권장 모델: **Fable/Opus**
> (이질적 본문 표 파싱 — B4 이력상 트리아지 반복이 잦았던 유형).

## 0. 왜 이 PRD 인가

우선순위 ②(부문·지역별 실적)를 채운다. DART 구조화 API 가 없어 본문 표 파싱이 필요하지만,
B4(생산능력/가동률)·B1(수주상황) 에서 이미 검증된 `biz_section.py` 인프라(범용 ROWSPAN/COLSPAN
그리드 확장기, 헤딩 탐지, 단위 캡처, DB 적재 파이프라인)를 그대로 재사용할 수 있다.

## 1. 목표

II.사업의 내용 절의 '매출실적/판매실적' 표를 부문×수출/내수×연도 단위로 파싱해 `biz_metrics`
에 적재하고, company_page 에 매출 구성 패널 + 수출비중 시계열을 노출한다.

## 2. 범위

- 대상: 사업보고서 본문의 매출실적/판매실적 표(집계형 — 부문별 국내/수출/합계 매출액).
- **IFRS8 영업부문 주석은 비범위**(결정 5 보류 — 이질성이 훨씬 높아 별도 설계 필요).

## 3. 비범위

- IFRS8 세그먼트 주석(부문별 자산/부채/영업이익까지 포함하는 재무제표 주석) — 보류.
- 지역별(국가 단위) 세분 매출 — 이번 범위는 수출/내수 이분류까지만. 국가별 세분이 표에 흔히
  나타나면 Phase 0 감사 결과를 보고 확장 검토.

## 4. 설계

### 4.1 핵심 발견 — 기존 가드가 매출표를 버리고 있음

`fin2/extract/biz_section.py:313` `_SALES_KW = ("매출", "판매", "수출액", "내수액")` 는 현재
**생산 표에 매출 키워드가 섞이면 그 표를 통째로 버리는** 가드(생산능력 표와 매출표 혼동 방지용).
즉 매출표 자체가 지금 명시적으로 폐기되고 있다 — 신규 파서는 이 표를 **버리지 않고 별도
캡처**하도록 라우팅해야 하며, 기존 생산(B4) 파서의 동작을 회귀시키지 않아야 한다(이중 캡처 금지).

### 4.2 신규 추출기 — `fin2/extract/sales_section.py`

`biz_section.py` 의 검증된 하위 함수를 최대한 재사용(신규 그리드 확장기 작성 금지):
- `find_sales_tables(root)`: `find_biz_subsections` 와 동일한 헤딩 탐지 전략(길이≤40자+키워드
  느슨매칭, 순번소제목 인식)을 매출 키워드("매출실적"/"판매실적"/"매출현황")로 재사용.
  `expand_table_grid`(기존 함수, import 재사용) 로 그리드화.
- `map_sales_table(bt, fiscal_year) -> list[SalesMetricRow]`: 열 분류(부문/품목 차원 열 vs
  수출/내수/합계 채널 열 vs 금액 값 열), 기간 해석(제N기→연도, 기존 `map_biz_table` 의 기간매핑
  로직 재사용), 채널 판정(열 헤더에 "수출"/"내수"/"합계"/"국내" 포함 여부).
- 결합형 레이아웃(삼성전자류 SPAN 개별 vs S-Oil류 P순번 결합형) 대응은 B4 에서 이미 검증된 헤딩
  탐지 패턴을 그대로 적용 — 신규 로직 최소화.

### 4.3 스키마 확장 — `biz_metrics.channel`

신규 테이블 대신 **가산 컬럼**: `biz_metrics.channel VARCHAR(12)`(nullable, 값: 수출/내수/합계/기타)
+ `metric='sales'` 신규 값. `collector/db.py` 에 멱등 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
마이그레이션. 기존 `biz_metrics` 로더(`app/data/biz.py`)·rcept 멱등 sync(`collector/biz_metrics.py`)
전부 그대로 재사용 — sales 도 동일 sync 진입점에 연결(`scripts/collect_sales_metrics.py` 는
`collect_biz_metrics.py` 의 얇은 래퍼 또는 동일 CLI 확장, 신규 함수는 파서 호출부만 교체).

### 4.4 UI

- `app/data/biz.py`: `load_sales_composition(corp_code)` — segment×channel×year 피벗.
- `app/views/company_page.py` "🏭 생산·가동률" 탭(기존)에 매출 구성 패널 추가: 부문별 매출 스택
  막대 + 수출비중(%) 라인. 별도 탭 신설이 필요할 정도로 크면 이름을 "🏭 생산·매출" 로 확장 검토
  (착수 시 판단, PRD 는 기존 탭 확장을 기본안으로 함).
- 차트빌더: `app/registry/extended.py` 에 "biz" kind 확장(이미 Phase 1 에서 만든 kind 체계 재사용,
  segment×channel 조합은 corp별로 동적 discover).

## 5. 검증 (B4 확립 절차 동일)

1. **프로토타입**: 삼성전자(SPAN 개별형)·S-Oil(P순번 결합형) 2사로 정확도 확인.
2. **20사 확대 스윕**: 업종 다양화(전자/정유/조선/제약 등), 오포착·미포착 트리아지.
3. **단위·항등식 가드**: 부문 매출 합계 ≈ std_v2 `revenue` (±20% 허용 — cf_da.py 의 D&A/매출
   비율가드와 동일 철학, 완전 일치는 기대하지 않음: 표에 특수관계자 매출 등 조정 항목 있을 수 있음).
4. **100~300사 스윕**: 구조적 오염 유형 트리아지(중첩 TABLE, 매출/생산 혼동, 계산근거 열 오염 등
   — B4b 8종 버그와 유사 클래스 예상, 동일 가드 패턴 적용).
5. `fin2/tests/test_sales_section.py` 신규(실측 기반 회귀 테스트, `test_biz_section.py` 패턴 모방).

## 6. 사용자 실행

전수 백필(로컬 파일, DART API 미호출 — 쿼터 무관, 수 시간): `scripts/collect_sales_metrics.py
--latest --skip-existing`.

## 7. 완료 기준

- `_SALES_KW` 가드가 생산 파서에서는 여전히 매출표를 배제하되, 신규 매출 파서가 그 표를 정확히
  캡처 — 이중 캡처 0건, 생산 파서 회귀 0건(`test_biz_section.py` 전체 그린 유지).
- 100~300사 스윕에서 매출 합계-std_v2 revenue 괴리가 설명 가능(단위오류 등 버그로 인한 괴리 0건).
- company_page 매출 구성 패널 렌더 + AppTest 무예외.
