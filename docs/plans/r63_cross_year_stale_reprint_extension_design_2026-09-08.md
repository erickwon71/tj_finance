# 설계: R63 "직전연차 재게재" 배제 — 교차연도(cross-year) 비교 확장 + table_seq
없는 PDF복구 필링 대응 (버킷B 잔여 58건) (2026-09-08)

## 배경

[[basis_fallback_stale_reprint_exclusion_design_2026-09-08]]에서 버킷B 111건 중
코드수정(`stale_basis`)으로 53건 해소, **58건 미해소**로 다음 세션에 인계됨. 이번
세션에 재현(census + `combine_full()` 직접 호출, DB 미변경) — **정확히 재현되지는
않았지만(51 해소/49+11=60 미해소, 문서의 53/48+10=58과 소폭 차이, DB가 그 사이
버킷A 작업 등으로 약간 흔들린 영향으로 추정, 무시 가능한 수준) 2갈래 원인 구조는
그대로 확인**:

- **카테고리1 (49건)** — `report_lines.table_seq`가 NULL인 필링(Track C PDF복구
  경로, `unit_source='pdf'`).
- **카테고리2 (11건)** — table_seq는 정상인데 R63이 이 지문을 애초에 검사하지 않음.

## 근본원인

### R63 현재 메커니즘 재확인 (`combine.py:1697-1753`)

`_stale_annual_reprint_table_seqs(session, corp, fy, period, basis, statement)`은
**같은 corp×fiscal_year×basis** 안에서, 이 period(Q1/H1/Q3 중 하나)의 표
(table_seq)를 **"현재 fy의 다른 interim period"**(`report_fiscal_period != :p
AND report_fiscal_period IN ('Q1','H1','Q3')`)와 (label_raw, value_won) 10개
이상 동시일치로 비교해 재게재 table_seq를 찾는다. **"직전 회계연도(FY, 사업보고서)
자체"는 비교 대상에 아예 없다** — `_STALE_REPRINT_PERIODS = ("Q1","H1","Q3")`이고
`other_distinct` 쿼리도 같은 fy 안에서만 돈다.

R63이 애초에 잡도록 설계된 지문은 "Q1과 H1과 Q3가 서로 같은 값을 재탕"(같은 회계
연도 안 인터림끼리 중복)이었다. 버킷B/버킷A census가 쓰는 지문(이번 분기 revenue
= **작년 사업보고서(FY)** revenue)은 처음부터 다른 지문이라 — 53건이 해소된 건
"그 회사가 마침 같은 해 다른 interim과도 겹쳐서" R63이 우연히 잡아준 것뿐이었다
(설계문서 인용대로).

### 카테고리2 실측 — 00112059(2003 Q1, 증권사) 원문 대조

- `report_lines`엔 두 개의 후보 table_seq(0="I. 영업수익"=467억, 1="I. 영업수익"
  =2,390억)가 있고 **둘 다 std_v3의 최종 확정값(1,119.5억)과 다르다** — R63이
  table_seq를 못 걸러낸 게 아니라, **std_v3.revenue 자체가 이 두 후보 중 하나를
  직접 쓰지 않는다.**
- 증권업은 `apply_revenue_profile()`(industry_profile) 경로로 `revenue =
  operating_income + sga`를 조립한다(R66으로 R63 필터가 이미 배선돼 있음). 실측:
  `operating_income=212.1억 + sga=907.4억 = 1,119.5억` — **정확히 일치**.
- **그런데 그 2003 Q1 FY2002 사업보고서(직전연차)의 col_index=0 "I. 영업수익"
  값이 정확히 239,071,633,721원인데, 이게 2003 Q1 필링 table_seq=1의 값과
  바이트단위로 동일**(재게재 확정). `operating_income`/`sga`는 이 table_seq=1
  (혹은 그 자매행)에서 조립됐을 것으로 보이는데, R63이 "직전연차(FY) 자체와의
  비교"를 안 하니 이 table_seq를 애초에 재게재로 인식 못 해 필터링이 무력.
- **결론**: 카테고리2의 진짜 근본원인은 "table_seq 매칭이 안 됨"이 아니라 **R63의
  비교대상 범위 자체가 교차연도(전기 FY)를 포함하지 않는다**는 설계 갭.

### 카테고리1 실측 — 00103042(2001 Q1/H1/Q3)·00104698(2001 Q1) PDF복구 필링

- 둘 다 `unit_source='pdf'`(Track C PDF복구 경로 산출물), **모든 report_lines
  행의 table_seq가 NULL** — 원본 PDF에 표가 여러 개 있었어도 추출기가 표
  경계(어느 표에서 왔는지)를 구분하지 못하고 통짜로 저장한다. R63은 `GROUP BY
  cur_distinct.table_seq`로 동작하는 구조라 **table_seq가 없으면 그룹 자체가
  안 생겨 배제 로직이 원천적으로 적용 불가**.
- 00104698 2001Q1 실측: 이 필링의 IS 행 7개 중 **핵심 손익 4개(매출액·영업이익·
  경상이익·당기순이익)가 직전 FY(2000)의 col_index=0 값과 전부 정확히 일치** —
  우연으로 보기 어려운 강한 재게재 신호. 다만 총 후보행이 7개뿐이라 R63의 기존
  임계값(10개 동시일치)은 이 카테고리엔 애초에 적용 불가능(모집단 자체가 작음).
- **결론**: table_seq 기반 "표 단위 배제"가 구조적으로 불가능한 카테고리 —
  행(row) 단위 비교로 접근을 바꿔야 한다.

## 수정안 (2트랙, 서로 독립적으로 구현 가능)

### 트랙1 — `_stale_annual_reprint_table_seqs()`에 전기 FY 비교 arm 추가 (카테고리2, 11건)

현재 `other_distinct` CTE에 **"전기(fy-1) FY 사업보고서"**를 추가 소스로 UNION한다.
FY 필링은 애초에 "인터림 누적치" 개념이 없어 `is_cumulative` 플래그가 이
스키마에서 `False`로 채워짐(실측 확인) — 그래서 이 arm만 `is_cumulative` 조건을
빼고 `report_fiscal_period='FY' AND col_index=0`만으로 걸어야 한다(교차연도 arm과
같은 fy 내 arm은 필터 기준이 다르므로 하나의 WHERE로 합치지 말고 UNION ALL로
분리):

```python
def _stale_annual_reprint_table_seqs(session, corp, fy, period, basis,
                                      statement="IS", *, cross_year=True):
    if period not in _STALE_REPRINT_PERIODS or fy > _STALE_REPRINT_MAX_FY:
        return set()
    rows = session.execute(text("""
        WITH cur_distinct AS (
            SELECT DISTINCT table_seq, label_raw, value_won
            FROM report_lines
            WHERE corp_code = :c AND report_fiscal_year = :y
              AND report_fiscal_period = :p AND basis = :b
              AND statement = :stmt AND col_index = 0 AND value_won IS NOT NULL
              AND COALESCE(is_cumulative, false) = true
        ),
        other_distinct AS (
            -- 기존: 같은 fy 안의 다른 interim period
            SELECT DISTINCT report_fiscal_period, label_raw, value_won
            FROM report_lines
            WHERE corp_code = :c AND report_fiscal_year = :y AND basis = :b
              AND statement = :stmt AND report_fiscal_period != :p
              AND report_fiscal_period IN ('Q1', 'H1', 'Q3')
              AND col_index = 0 AND value_won IS NOT NULL
              AND COALESCE(is_cumulative, false) = true
            UNION ALL
            -- ★신규: 전기(fy-1) FY 사업보고서 (is_cumulative 무관 — FY는 애초에
            -- 이 플래그가 False로 채워짐, R63 원안 설계 갭)
            SELECT DISTINCT 'FY' AS report_fiscal_period, label_raw, value_won
            FROM report_lines
            WHERE corp_code = :c AND report_fiscal_year = :y - 1
              AND report_fiscal_period = 'FY' AND basis = :b
              AND statement = :stmt AND col_index = 0 AND value_won IS NOT NULL
        )
        SELECT cur_distinct.table_seq, count(*) AS n
        FROM cur_distinct
        JOIN other_distinct
          ON other_distinct.label_raw = cur_distinct.label_raw
         AND other_distinct.value_won = cur_distinct.value_won
        GROUP BY cur_distinct.table_seq, other_distinct.report_fiscal_period
        HAVING count(*) >= :thresh
    """), {...}).fetchall()
    return {r[0] for r in rows}
```

임계값(`_STALE_REPRINT_THRESHOLD = 10`)은 그대로 재사용 — 원안이 이미 "10개+
동시일치=표 전체 재게재"로 실측 검증된 값이고, 카테고리2는 table_seq가 정상인
사례라 원안의 모집단 성격(표 크기)과 같다.

### 트랙2 — table_seq NULL 필링용 행(row) 단위 배제 (카테고리1, 49건)

table_seq 그룹이 없으므로 트랙1과 같은 함수로 처리 불가. **신규 함수**
`_stale_annual_reprint_rows_no_table_seq()`를 만들어 "table_seq IS NULL인
후보 각각을, 전기 FY의 (label_raw, value_won)과 직접 대조해 개별 행 단위로
배제"하는 방식으로 설계한다. `_resolve()`의 pre-pass에 "table_seq 배제"뿐 아니라
"row-id 배제"도 받는 경로 하나 추가 필요(cands 필터링 지점 확인 필요, 아래
미해결 항목 참고).

**★★임계값 미정 — 구현 전 반드시 전사 측정 선행**: 카테고리1은 후보 모집단
자체가 작다(00104698 예시: 전체 7행). R63 원안의 "10개+ 동시일치" 임계값을 그대로
쓰면 이 카테고리는 사실상 영원히 안 걸린다. 실측 두 표본(00103042: 4/4 핵심
손익 일치, 00104698: 4/7 일치, 나머지 3행은 PDF파싱 잔재로 보이는 "당기:"/"전기:"
같은 비계정행)은 "핵심 손익 라인(매출액·영업이익·경상이익·당기순이익) 전부
일치"라는 신호가 강하지만, **이걸 그대로 규칙화("4개 핵심계정 전부 일치 시
배제")하면 우연히 이 4개 다 같은 회사(예: 적자 지속 소형사)를 오탐할 위험**이
있다 — R63 원안이 그랬듯 **전사 SQL로 "coincidental overlap 비율"부터 측정**해야
한다(같은 방법론: `docs/PARSING_RULES.md` R63 절의 "연결 97.2% vs 별도 29.6%"
실측처럼, 카테고리1 모집단[49건] vs 무작위 다른 corp×period 쌍에서 우연히
핵심계정 4개가 다 일치하는 비율을 비교). **이 측정 없이 임계치를 짐작으로
정하면 안 됨** — 사용자 승인 전 다음 세션에서 먼저 이 측정부터 하는 것을 제안.

## 영향범위 (★확인 필요 — 두 트랙 다 dry-run 필수)

- 트랙1(전기FY 비교 arm)은 `_stale_annual_reprint_table_seqs()`를 호출하는 모든
  경로(`combine_full()`의 `_resolve()` pre-pass + R66으로 배선된
  `apply_revenue_profile()`)에 자동 적용된다 — **카테고리2 11건 밖에서도 새로
  걸리는 table_seq가 있을 수 있다**(예: 지금까지 "같은 fy 내 인터림끼리는 안
  겹쳤지만 전기 FY와는 겹치는" 케이스가 census 지문[revenue 기준] 밖에 더 있을
  가능성 — 매출액이 아닌 다른 canonical에서). [[basis_fallback_stale_reprint_
  exclusion_design_2026-09-08]]과 동일한 우려 — **좁은 재확인뿐 아니라 넓은
  dry-run diff 필요**(`basis='separate'`이고 `report_fiscal_year<=2012`인 전체
  Q1/H1/Q3 행을 대상으로, 이 함수가 반환하는 table_seq 집합이 수정 전/후 어떻게
  달라지는지 전수 비교).
- 트랙2(row 단위 배제)는 스코프가 "table_seq IS NULL"로 이미 좁게 게이팅돼 있어
  블라스트 반경은 상대적으로 작다(카테고리1 49건이 상한에 가까움) — 그래도
  임계치 확정 후 전수 dry-run 필요.
- 둘 다 R63 원안과 동일하게 **NULL로 가는 방향으로만 작동**(대체 데이터가 없는
  시대의 특성상 "복구"가 아니라 "배제") — 값이 새로 생기거나 다른 값으로
  바뀌는 행이 있으면 설계 밖 부작용, 구현 중단하고 재검토.

## 검증 계획

1. **트랙1 임계값**은 기존 R63 임계값(10) 재사용이라 별도 측정 불요, 회귀
   테스트만: `test_combine_r63_cross_year_reprint_2026-09-08.py` — 00112059
   2003Q1을 픽스처로, 수정 전 재현(1,119.5억 확정) → 수정 후 NULL 확인.
2. **트랙2 임계값**은 위 "★★임계값 미정" 절의 전사 측정을 먼저 실행 —
   측정 결과를 사용자에게 제시하고 임계치 승인받은 뒤 구현.
3. `pytest tests/ fin2/tests/` 전체 회귀 0건.
4. 좁은 재확인: 카테고리2 11건 + 카테고리1 49건(트랙2 구현 시) 전부 해소(NULL
   또는 새 값이 아니라 반드시 NULL) 확인.
5. 넓은 dry-run diff: 위 "영향범위" 절 대상 전수 비교, 예상 밖 변경 있으면 중단.
6. `dq_assertions.py` 전수 — 신규 ERROR 0건, `statement_magnitude_impossible`
   변화 없음(이 트랙은 NULL화만 하므로 구조적으로 새 magnitude-impossible을
   만들 수 없음, R63 원안과 동일 논리).
7. DB 재빌드 스코프는 [[basis_fallback_stale_reprint_exclusion_design_2026-09-08]]의
   미완료 스코프(68개사)와 함께 한 번에 결정하는 것을 제안(둘 다 같은 corp
   population과 겹칠 가능성 높음 — 중복 재빌드 방지).

## 롤백 안전성

`combine_full()`은 매번 `report_lines`에서 새로 조립하는 순수 함수 경로 —
원본 `report_lines`는 이 수정으로 전혀 건드리지 않는다. 문제가 생기면 코드만
되돌리고 영향받은 corp만 재빌드하면 즉시 원상복구된다([[basis_fallback_stale_
reprint_exclusion_design_2026-09-08]]과 동일 패턴).

## 미해결 질문 (구현 전 결정 필요)

1. **트랙2 임계치** — 위 "★★임계값 미정" 절, 전사 측정 선행 필요.
2. **트랙2의 `_resolve()` 배선 지점** — table_seq 배제는 기존 pre-pass가
   `cands`에서 table_seq로 필터링하는 구조인데, row 단위 배제는 이 필터 인터페이스
   자체를 확장해야 하는지, 아니면 `cands` 생성 이전 단계(`_map_rows()`)에서 미리
   제외하는 게 더 깔끔한지 코드 구조 검토 필요(설계는 이번 문서로 방향만 잡고,
   구현 세션에서 실제 배선 지점을 코드 읽고 확정).
3. **트랙1의 "영향범위 밖 신규 발견" 가능성** — revenue 외 다른 canonical에서도
   전기FY와 겹치는 케이스가 있는지, dry-run 전에는 알 수 없음(위 "영향범위" 절).

## 참고

- [[basis_fallback_stale_reprint_exclusion_design_2026-09-08]] — 버킷A/B
  전체 배경, 이 설계의 상위 문서.
- R63 원 설계: `docs/PARSING_RULES.md` R63 절(직전연차 재게재 배제 도입 배경,
  임계값 10 실측 근거).
- R66: `apply_revenue_profile()`에 R63 필터 배선(카테고리2가 이 경로를 타는 이유).
