# PRD 11 — Phase 0: 전수 인벤토리 감사

> 마스터 계획: `10_gap_fill_plan.md`. 체크리스트: `10_16_checklist.md`. 권장 모델: **Fable/Opus**
> (헤딩 분류 룰북 설계·표 유형 판별이 판단 집약적).

## 0. 왜 이 PRD 인가

이후 Phase 1~5 는 "무엇을 채울지"를 이미 가정하고 설계됐다(주주환원/부문매출/비용성격/일반현황).
그 가정이 맞는지, 그리고 **그 4개 밖에 다른 중요한 갭이 더 있는지**를 사전에 정량·정성으로
확인하는 것이 Phase 0 다. DART 정기보고서 본문에 등장하는 모든 숫자 표를 항목 단위로
'수집됨/미수집/수집불가' 로 분류한 매트릭스를 만들어, Phase 1~5 착수의 근거와 완료 기준을 마련한다.

## 1. 목표

- fact_v2 에 이미 파싱됐으나 std_v2 에 미승격된 캐노니컬 계정의 **정량 규모**(행수·corp×fy 커버율)를 측정.
- 보고서 본문/주석에 등장하는 숫자 표 전체를 **항목 유형별로 분류**하고, 현재 추출기 커버리지와 대조.
- Phase 1~5 착수 근거 문서(`docs/data_inventory_matrix.md`) 산출 — 이후 각 Phase 완료 시 상태 갱신.

## 2. 범위

- **Pass 1 (SQL 정량)**: 기존 DB(fact_v2/statement_source/std_financials_v2/biz_metrics/
  order_backlog/executives/capital_events/major_shareholders 등) 대상 커버리지 쿼리.
- **Pass 2 (표본 심층)**: 로컬 raw_report XML 대상 층화표본 파싱 — 새 코드로 DB 변경 없음(읽기 전용).
- 189K 파일 전수 제목-레벨 스캔은 **선택**(사용자 실행 옵션, 이 PRD 의 필수 스코프 아님).

## 3. 비범위

- 신규 파서 구현(Phase 3/4 소관). Phase 0 은 감사만 — DB 적재 없음, 코드는 read-only 스크립트 하나.
- concept_map.py 캐노니컬 확장(향후 Phase 별도).

## 4. 설계

### 4.1 Pass 1 — SQL 정량 쿼리 (수 분)

신규 스크립트 `scripts/audit_table_inventory.py --pass1`(또는 별도 `--sql-only`) 가 실행:

1. **미매핑 acode 상위 빈도**: `SELECT acode, COUNT(*) FROM fact_v2 WHERE canonical_account IS NULL
   GROUP BY acode ORDER BY 2 DESC LIMIT 100` — 상위 미매핑 계정명 확인(신규 concept_map 후보 발견용).
2. **미승격 캐노니컬 행수·커버율**: concept_map.py 의 canonical vocabulary 중 std_v2 컬럼에 없는
   ~30종에 대해 `SELECT canonical_account, COUNT(DISTINCT corp_code||fiscal_year) FROM fact_v2
   WHERE canonical_account = :c AND col_index=0 AND NOT is_dimensional GROUP BY 1` — Phase 1
   extended_financials 뷰의 실제 payoff 를 사전 정량화.
3. **기존 부가 테이블 커버리지**: biz_metrics/order_backlog/executives/capital_events/
   major_shareholders 각각 corp 수·연도 범위·행수 — 이미 알려진 값(메모리 기록)과 대조해 drift 확인.

### 4.2 Pass 2 — 표본 심층 스캔 (30~60분)

신규 스크립트 `scripts/audit_table_inventory.py --pass2`:

- **표본 설계**: 활성 보통주 중 층화표본 ~300사 (시장 KOSPI/KOSDAQ × 업종 대분류 × 시가총액 3분위).
  `corporations`/`std_financials_v2` 조인으로 계층 산출.
- **대상 파일**: 표본 기업당 {최신 사업보고서, 2020 사업보고서, 2016 사업보고서} 3개
  (`download_tasks.file_path` 조회, annual report_type 한정).
- **파싱**: `fin2/extract/biz_section.py::_load_root`(인코딩 자동감지) + `expand_table_grid`
  (기존 ROWSPAN/COLSPAN 그리드 확장기 — 신규 구현 없이 그대로 재사용) 로 모든 `TABLE` 요소 순회.
  - "숫자표" 판정: 셀 중 `_looks_numeric`/`_is_clean_number`(기존 함수 재사용) 비율 ≥30%.
  - 직전 헤딩(가장 가까운 상위 `<P>`/번호매김 제목) 텍스트 캡처.
- **헤딩 분류 룰북**: `ITEM_STATUS: dict[str, ItemStatus]` — 키워드 매칭으로 헤딩을 ~40개 항목
  유형에 매핑(신규, 이 Phase 의 핵심 산출물). 각 유형은 다음 필드를 가짐:
  - `section`(예: "II.사업의 내용", "III.재무에 관한 사항", "VIII.임원 및 직원 등의 현황" 등)
  - `status`: `collected`(이미 API/파서로 수집) | `planned_phase_N`(1~5 중 어느 Phase 가 다룸)
    | `not_collectible`(구조적으로 불가) | `deferred`(결정 5 보류 항목) | `unclassified`(신규 발견)
  - `source`: 최적 소스 힌트(XBRL face / 본문 표 / 주석 / DART API)
  - 초기 룰북 시드는 다음을 포함해야 함(마스터 PRD 결정 1~5 반영):
    재무제표 본문(BS/IS/CF) → collected(XBRL Track A/B), 배당에 관한 사항 → planned_phase_2,
    자기주식 취득·처분 → planned_phase_2, 임원 보수(전체/개인별) → planned_phase_2,
    직원 현황 → planned_phase_2, 타법인 출자현황 → planned_phase_2,
    매출실적/판매실적 → planned_phase_3, 비용의 성격별 분류 → planned_phase_4,
    생산능력/생산실적/가동률 → collected(B4), 수주상황 → collected(B1),
    차입금 등 → deferred, 최대주주/소액주주 현황 → collected(B3),
    증자/감자/CB/BW/EB → collected(B2), 회사의 개요/연혁/자본금 변동 → 대부분 서술형(수치 희박,
    not_collectible 로 시작 후 표본에서 재평가), 우발부채/약정사항 → deferred,
    특수관계자 거래 → deferred, 리스 주석 → 부분(collected via note.rou_depreciation, 나머지 deferred).
  - **`unclassified`로 남는 헤딩이 있으면 그것이 이 Phase 의 진짜 발견** — 룰북에 없는 헤딩은
    원문 그대로 보존해 사람이 검토(자동 폐기 금지).

### 4.3 산출물

- `docs/data_inventory_matrix.md` — 매트릭스 표: `항목 | 절 | 최적소스 | 상태 | 표본 출현빈도(%) |
  Pass1 정량(해당 시)`. Pass 1 SQL 결과 요약 + Pass 2 표본 통계(항목별 등장 기업 수/비율) 포함.
- 미분류(unclassified) 헤딩 목록 별첨 — 후속 세션에서 룰북에 추가할 후보.

## 5. 검증

- 10개 기업으로 Pass 2 인라인 실행 → 결과 육안 확인(그리드 확장 정상, 헤딩 매칭 합리적).
- 무작위 30개 헤딩-분류 결과를 사람이 육안 검수 — 명백한 오분류(예: 매출실적을 재무제표로 오분류)
  0건 목표.
- Pass 1 쿼리 결과가 기존 메모리 기록(예: biz_metrics 1,724사, order_backlog 567사)과 정합.

## 6. 사용자 실행 (장시간)

- 300사 표본 스윕 전체 실행(30~60분, 로컬 파일 read-only, DART API 미호출 — 쿼터 무관).
- (선택) 189K 파일 전수 제목-레벨 정규식 스캔 — 파싱 없이 헤딩 태그만 카운트, 별도 커맨드.

## 7. 완료 기준 (Definition of Done)

- `docs/data_inventory_matrix.md` 존재, 위 5개 절 항목 이상 커버.
- Pass 1 쿼리 스크립트 + Pass 2 샘플러 스크립트 모두 커밋됨, read-only(DB/파일 변경 없음) 확인.
- unclassified 헤딩 목록이 5% 미만(또는 명시적으로 "구조적 서술형이라 정상" 처리).
