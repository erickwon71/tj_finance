# PRD 16 — Phase 5: 자유조합 차트빌더 고급 기능

> 마스터 계획: `10_gap_fill_plan.md`. 체크리스트: `10_16_checklist.md`. 권장 모델: **Sonnet**
> (UI 증분, 기존 컴포넌트 재사용 — 판단 요소 적음).

## 0. 왜 이 PRD 인가

목표 4("수집된 모든 항목을 쉽게 조합해 볼 수 있어야 함")의 마지막 조각. Phase 1~4 로 데이터는
크게 늘었지만, 차트빌더 자체의 UX 한계(파생연산 3종뿐, 다기업 비교 불가, PER/PBR 시계열 접근 불가)
는 별도로 풀어야 한다.

## 1. 목표

- 파생연산 확장: YoY(%), TTM(분기 그레인).
- `valuation_daily` 시계열(PER/PBR/PSR/EV-EBITDA/배당수익률)을 차트빌더에서 선택 가능하게.
- 다기업 비교 모드(2~4사 동시 차트).
- 금액 단위 스케일 토글(원/억원/조원).

## 2. 범위

- 기존 `METRIC_REGISTRY`/`resolver.build_metric_frame`/Phase 1~4 의 extended 카탈로그는 불변 —
  이 Phase 는 **UI·연산 레이어**만 확장.

## 3. 비범위

- 신규 데이터 수집 없음(순수 앱 레이어 작업).
- 스크리너 통합(별도 검토).

## 4. 설계

### 4.1 파생연산 확장 — `app/compute/derived.py`

기존 `OP_LABELS`(ratio/diff/pershare) 에 추가:
- `yoy`: 전년 동기 대비 % 변화. `needs_prev` 방식(기존 GROWTH 카테고리 지표의 `needs_prev=True`
  패턴과 동일한 shift 로직 재사용) — 연간 그레인은 전년, 분기 그레인은 전년동기(4분기 전).
- `ttm`: 분기 그레인 전용, 직전 4분기 합산(스크리너의 `_ttm_row` 로직과 동일 원칙 재사용,
  `app/compute/screen_eval.py` 참고).
- 각 연산은 `derived.py` 의 `validate()` 에 적절한 가드 추가(예: ttm 은 amount 계열만, yoy 는
  전기 존재 확인).
- **프리셋 하위호환**: 프리셋 JSON 스키마는 이미 `{op, a, b}` 형태로 op-키드 — 신규 op 추가는
  기존 저장된 프리셋을 깨지 않음(구 프리셋 로드 시 새 op 미인식 문제 없음, 검증만 필요).

### 4.2 밸류에이션 시계열 — `app/views/chart_builder_page.py`

- 별도 섹션(주가 오버레이와 유사하지만 독립) — 기존 `app/cache.py::valuation_series` 캐시 함수
  재사용(company_page 밸류에이션 탭이 이미 소비 중인 헬퍼, 신규 쿼리 불요).
- **그레인 주의**: `valuation_daily` 는 일별 — 재무 지표 프레임(연간/분기 기간)과 시간축이
  다르므로 같은 축에 억지로 합치지 않고 **독립 서브플롯 또는 별도 차트**로 렌더(주가 오버레이가
  이미 "가격은 다른 시간축" 문제를 푼 방식을 참고).

### 4.3 다기업 비교 모드

- 사이드바 기업검색 헬퍼를 재사용한 `st.multiselect` 로 2~4개 기업 선택.
- 선택된 각 기업에 대해 `cache.annual_series`(또는 `fetch_ext_frame`) 반복 호출 → tidy frame 에
  `corp_code`/`corp_name` 컬럼 추가.
- `app/views/chart_panel.py::render_metric_chart` 에 `color=corp / dash=metric`(또는 유사) 변형
  옵션 추가 — 단일회사 모드와 분기(branch)해 기존 단일회사 렌더 경로는 무회귀 유지.
- 비교 모드는 `compare_page.py`(정적 스냅샷 표)와 별개 — 시계열 차트라는 점이 차별점, 다만 두
  기능이 혼동되지 않도록 UI 문구로 구분("스냅샷 비교는 기업 비교 페이지, 시계열 비교는 여기").

### 4.4 스케일 토글 — `app/registry/units.py`

- AMOUNT_EOK(억원) 계열에 대해 원/억원/조원 표시 스케일 선택 옵션. 저장값(내부 계산)은 불변,
  표시 레이어에서만 나눗셈.

## 5. 검증

- `yoy`/`ttm` 계산 로직에 대한 단위 테스트(`tests/` 신규, 알려진 시계열로 수기 대조 — 삼성전자
  매출 YoY 등 오라클 대조, `_growth_rate`/`_cagr` 기존 테스트 패턴 참고).
- AppTest 헤드리스 무예외(다기업 비교 2~4사, extended+yoy 조합).
- 수동 UI 확인: 프리셋 저장/로드가 신규 연산 포함 상태로 정상 동작.

## 6. 사용자 실행

없음 — 순수 코드 변경, 백필 불필요.

## 7. 완료 기준

- yoy/ttm 연산이 파생 섹션에서 선택 가능 + 정확도 검증 통과.
- 밸류에이션 시계열이 차트빌더에서 조회 가능.
- 다기업 비교 모드 2~4사 렌더, 기존 단일회사 모드 무회귀.
- 구버전 프리셋(op 3종만 포함) 로드 시 에러 없음.
