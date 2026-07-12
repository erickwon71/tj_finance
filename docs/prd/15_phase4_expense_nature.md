# PRD 15 — Phase 4: 비용의 성격별 분류 주석 파서 + EBITDA 커버리지 상승

> 마스터 계획: `10_gap_fill_plan.md`. 체크리스트: `10_16_checklist.md`. 권장 모델: **Fable/Opus**
> (표준화 파이프라인 접점 — 재표준화→분기→달력 전파 회귀 위험, cf_da 급 판단 난이도).

## 0. 왜 이 PRD 인가

우선순위 ③(주석 상세)의 핵심 항목. '비용의 성격별 분류' 주석은 급여/원재료비 등 비용 구성을
주지만, **동시에 감가상각비·무형자산상각비 라인도 포함** — 이는 현재 연결 EBITDA 커버리지가
42% 천장에 막혀 있는 근본 원인(`data-coverage-gaps` 메모리)과 정확히 같은 데이터를 다른 경로로
제공한다. 즉 이 파서 하나로 ③ 항목 신규 확보 + 기존 알려진 데이터 갭(EBITDA) 개선을 동시 달성한다.

## 1. 목표

'비용의 성격별 분류' 주석 표에서 급여·원재료비·감가상각비·무형자산상각비 등을 추출해
`note.*` 합성 fact 로 적재, D&A 항목은 기존 표준화 규칙에 자동 반영되도록 한다.

## 2. 범위

- 대상: 손익계산서 주석 중 '비용의 성격별 분류'(nature-of-expense) 표.
- 신규 canonical: `note.employee_benefits`(급여·복리후생), `note.raw_materials_used`(원재료비).
- 기존 canonical 재사용: `note.depreciation`/`note.amortization`/`note.da_total`(이미 `rules.py`
  `_DA_TOTAL_CANON` 이 소비 — 신규 배선 불필요, 파서만 새 소스를 공급).

## 3. 비범위

- 별도(separate) basis 확장(`data-coverage-gaps` 메모리에 이미 "dry-run 결과 실행 불필요" 결론
  기록됨 — 이 Phase 는 연결(consolidated) 우선, 별도는 자동으로 따라오는 만큼만).
- 판매비와관리비 상세 항목별 분해(급여 외 세부 계정) — 향후 검토.

## 4. 설계

### 4.1 신규 추출기 — `fin2/extract/expense_nature.py`

`fin2/extract/rd_note.py` 를 그대로 모델로 사용(구조 동일 — 표 탐색+합계 추출+단위 보정):
- `_find_expense_nature_table(root)`: 헤딩 "비용의 성격별 분류" 매칭(rd_note.py `_find_rd_table`
  패턴 재사용).
- `_rows_from_table(table) -> dict[str, int]`: 라벨(급여/복리후생/원재료비/감가상각비/무형자산
  상각비/기타)별 금액 추출.
- `_unit_factor(...)`: rd_note.py 의 매출 앵커 단위보정 로직 재사용(표 자체 단위 표기가 신뢰
  불가할 때 매출 대비 스케일로 역산).
- `extract_expense_nature_facts(file_path, corp_code, fiscal_year) -> list[dict]`: 방출 canonical
  = `note.employee_benefits`, `note.raw_materials_used`, `note.depreciation`, `note.amortization`,
  `note.da_total`(= depreciation+amortization 합, cf_da.py 와 동일 관례).

### 4.2 영속화 — `collector/expense_nature_sync.py`(신규, `cf_da_sync.py` 클론)

`collector/cf_da_sync.py::sync_cf_da` 의 정확한 패턴 복제:
1. 대상 선정: `depreciation IS NULL`(std_v2, 연결) 인 corp×fy — 기존 D&A 파이프라인이 못 채운
   잔여만 타겟(이중 계상 방지, cf_da.py 와 동일 가드 철학).
2. `extract_expense_nature_facts` 호출 → `store_facts`(기존 fact_v2 upsert 헬퍼) 로 synthetic
   fact 삽입.
3. `standardize_corp(corp)` 재표준화 → `fin2_quarterly_all` 상당 재이산화 → `fin2_calendar_all`
   상당 재달력화. **순서 필수**(`data-coverage-gaps` 메모리 교훈: "누적(standardize) → 이산
   (quarterly_all) → 달력(calendar_all), calendar_all 단독은 stale").
4. 단위 가드: da_total/매출(동일 basis) ∈ [0.3%, 60%](cf_da.py 와 동일 임계치 재사용 — 새로
   튜닝하지 않음, 검증된 값 그대로).

### 4.3 일일 증분 — `scripts/collect_new.py`

기존 ④-2 단계(`cf_da_sync` 배선 지점)를 확장해 `expense_nature_sync` 도 같은 자리에서 비치명적
호출(신규 표준화 기업의 최신 annual 만).

### 4.4 앱 노출

- `app/registry/extended.py`: `note.employee_benefits`/`note.raw_materials_used` 를 "extended"
  kind 항목으로 추가(Phase 1 카탈로그에 편입 — 신규 kind 불필요, canonical_account 경로가 이미
  `note.*` 도 커버 가능하도록 `extended_financials` 뷰 WHERE 절이 note.* 를 배제하지 않는지
  Phase 1 구현 시점에 확인 필요 — 현재 뷰는 `left(canonical_account,3)` 로 bs/is/cf 만 매칭하므로
  **note.* 는 이 Phase 에서 뷰 조건을 완화하거나 별도 UNION 브랜치 추가**가 필요함. 착수 시 Phase 1
  뷰 정의를 재확인하고 필요 시 `OR f.canonical_account LIKE 'note.%'` 분기 추가).
- da_total/ebitda 는 이미 std_v2 컬럼이라 기존 지표 카탈로그(46종)에 자동 반영 — 신규 UI 작업 불요,
  값 자체가 개선됨.

## 5. 검증

- **Golden set 전후 비교**: da_total/ebitda NULL 비율이 파서 적용 전/후 얼마나 줄었는지 측정
  (목표: 연결 42% 천장에서 유의미한 상승 — 정확한 목표치는 Phase 0 Pass 1 정량 결과 참고).
- da/매출 [0.3%, 60%] 가드 재사용 확인 — 가비지 EBITDA(예: |ebitda|/revenue > 5) 0건.
- **Gate B 무영향**: note.* 는 non-face synthetic fact 이므로 `face_audit` 대상 아님 — 기존 Gate B
  pass/fail 카운트에 변화가 없는지 확인(회귀 없음 재확인).
- 100사 스윕 → EBITDA 커버리지 이동량 리포트(before/after).

## 6. 사용자 실행

전수 백필 + 재표준화 스윕(로컬 파일, DART API 미호출 — 쿼터 무관이나 재표준화가 장시간):
`caffeinate -i .venv_tj_finance/bin/python scripts/fin2_extract_expense_nature.py --year-min 2024`
(스크립트명은 착수 시 `fin2_extract_cf_da_consolidated.py` 네이밍 컨벤션에 맞춰 확정) — 순서 준수:
추출 → 재표준화 → 이산 → 달력.

## 7. 완료 기준

- EBITDA(연결) 커버리지가 측정 가능한 수준으로 상승(수치는 Phase 0/이 Phase 검증 리포트에 기록).
- `fin2/tests` 회귀 테스트 통과, Gate B fail 카운트 무변화.
- `note.employee_benefits`/`note.raw_materials_used` 가 차트빌더에서 조회 가능.
