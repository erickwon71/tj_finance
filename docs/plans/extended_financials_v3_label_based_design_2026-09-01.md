# `extended_financials` 뷰 라벨 기반 재설계 — 설계문서 (§4-2, 계층2 GC 트랙)

> **미구현 — 승인 대기.** 이 문서는 조사·설계까지만 담는다. 구현은 사용자가 별도로
> 지시한 뒤 진행한다.

## 0. 배경

`docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §4의 계층2 GC(fact_v2 55GB DROP) 순서
중 2단계. 1단계(`fin2/reconcile.py` 소비처 확인)는 저위험으로 끝났고(부수적으로
`standardize_corp`류 dead-code 가드 발견·수정, 커밋 `97ff39d`), 이 문서는 그 다음
"미해결 설계 질문"(§2-2/§5-b)을 다룬다:

`extended_financials` 뷰(정의: `collector/db.py`
`"2026_07_extended_financials_view_distinct"`)는 `fact_v2.canonical_account`(acode 기반,
XBRL Track A/텍스트 Track B account_mapper 산출)를 그대로 조회한다. `report_lines`/
`note_lines`(계층2 신 체인)는 **의도적으로** `canonical_account` 컬럼이 없다
(`fin2/extract/report_lines.py:9`: "account_mapper.map() 호출 없음"). `fact_v2` DROP 전에
이 뷰가 신 체인만으로 동작하도록 재설계해야 한다.

## 1. 핵심 발견 — 이미 계산되고 버려지는 값이다

`fin2/layer3/combine.py::combine_full()`(std_v3 조립 함수, layer3 빌드 때마다 corp당
period×basis 조합 수만큼 호출됨)의 내부 흐름을 추적한 결과:

```
_map_rows(report_lines 원문 행들)              → cands   {canonical: [candidate,...]}  (전체 어휘)
  L2703, 매 행마다 _map_label() = account_mapper.get_mapper().map() 호출(라벨기반, Track B와 동일 엔진)
_resolve(cands, ...)                            → confirmed {canonical: value}          (전체 어휘, 충돌해소 완료)
  L1924 `for c, rows in cands.items():` — DIRECT_MAP으로 필터링하지 않고 cands의 모든 canonical을 순회
combine_full() 내부, L2940-2945:
  col = {}
  for canon, value in confirmed.items():
      std_col = DIRECT_MAP.get(canon)
      if std_col is None: continue        # ← 여기서 확장 캐노니컬이 통째로 버려짐
      col[std_col] = value
  return col, conflicts, prov             # confirmed 자체는 반환되지 않음
```

즉 **`confirmed`는 이미 `report_lines` 원문 라벨을 account_mapper로 매핑하고, std_v3와
똑같은(R15~R60로 검증된) 충돌해소 로직까지 거친, 확장 캐노니컬 전체(약 80종, bs./is./cf.
접두)의 (canonical → 확정값) 딕셔너리다.** DIRECT_MAP(약 40종, `_VALUE_COLS`)에 없는
나머지는 `combine_full()` 리턴 직전에 조용히 버려질 뿐 — 새로 계산할 게 없다.

`fin2/layer3/build.py::build_corp()`도 동일 패턴으로 한 번 더 버린다(L145-147):
```python
for c in _VALUE_COLS:      # std_v3 wide 컬럼 40종만
    if c in col: setattr(row, c, col[c])
```

**결론**: acode 기반 재구성이나 새 라벨 매퍼 설계가 필요한 게 아니라, `combine_full()`이
이미 만드는 `confirmed`를 반환값에 추가하고, `build_corp()`가 그중 DIRECT_MAP에 없는
나머지를 새 테이블에 얹기만 하면 된다. 계층3의 감사검증된 매핑 엔진을 그대로 재사용하므로
새 매핑 버그를 만들 위험이 낮다.

## 2. 범위 밖 — note.* 확장 캐노니컬 2종

`EXTENDED_CATALOG`(`app/registry/extended.py`) 82종 중 `note.employee_benefits`/
`note.raw_materials_used` 2종은 이 설계의 대상이 아니다:

- `combine.py::build_merged_lines()`는 `report_lines`만 읽는다(L1615 `FROM report_lines`,
  `statement IN (BS/IS/CF/SCE)` 성격) — `note_lines`는 애초에 `cands`/`confirmed`에
  안 들어온다.
- 이 2종은 별도 경로(`collector/expense_nature_sync.py::sync_expense_nature()`)가
  `note_lines`에서 직접 추출해 **지금도 `fact_v2`에 `store_facts()`로 적재**한다
  (v3 셀렉터로 전환됐지만 저장은 여전히 fact_v2, `expense_nature_sync.py:9`).
- → **`fact_v2` DROP(§4-4)의 진짜 잔여 블로커는 이 2종**이다. 이 문서의 재설계로
  `extended_financials`가 report_lines 기반으로 바뀌어도, `expense_nature_sync.py`가
  fact_v2에 쓰기를 멈추지 않는 한 fact_v2는 못 지운다. 별도 후속 작업 필요(이 문서
  범위 밖 — note_lines 기반으로 sync_expense_nature를 다시 쓰거나, 새 테이블에 같이
  적재하도록 바꿔야 함).

## 3. 제안 설계

### 3-1. `combine_full()` 반환값에 확장 캐노니컬 추가

`col, conflicts, prov` 3-튜플 반환 계약을 유지하되(기존 호출자 27곳 영향 없음),
`prov` 딕셔너리에 키 하나 추가:

```python
prov["extended"] = {canon: value for canon, value in confirmed.items()
                     if canon not in DIRECT_MAP}
```

`combine.py` 내부 값(`confirmed`)을 그대로 복사하는 것뿐이라 `_resolve()`/`_map_rows()`
로직은 **한 글자도 안 건드림** — Gate B 감사 리더(R15~R60)의 신뢰 기준선에 영향 없음.

### 3-2. 새 테이블 `extended_facts_v3` (신규, `collector/models.py`)

```python
class ExtendedFactV3(Base):
    """계층3 조립의 부산물 — combine_full()의 confirmed 중 DIRECT_MAP에 없는 확장
    캐노니컬(EXTENDED_CATALOG). std_financials_v3와 같은 그레인, canonical 축만 추가."""
    __tablename__ = "extended_facts_v3"
    corp_code      = Column(String(8),  primary_key=True)
    fiscal_year    = Column(SmallInteger, primary_key=True)
    fiscal_period  = Column(String(5),  primary_key=True)
    statement_type = Column(String(12), primary_key=True)  # basis
    canonical_account = Column(String(40), primary_key=True)
    amount_won     = Column(BigInteger, nullable=False)
    # 신규 테이블 → create_all() 자동 생성(마이그레이션 불요, StdFinancialV3 선례).
```

`n_facts`(옛 뷰의 `COUNT(DISTINCT amount_won)`, DQ 이상치 검출용, §3-4 참고)는 옮기지
않는다 — 옛 acode 세계에선 "같은 canonical에 서로 다른 금액이 여럿 걸리는" 원시적
다중매치가 실제로 있었지만, `confirmed`는 이미 `_resolve()`가 충돌을 해소한 **단일값**이라
그 신호 자체가 다른 형태(§3-4)로 바뀐다.

### 3-3. `build_corp()`에서 upsert

`fin2/layer3/build.py::build_corp()`의 기존 `StdFinancialV3` delete-then-insert 블록
바로 뒤에 병렬로 추가:

```python
session.execute(delete(ExtendedFactV3).where(
    ExtendedFactV3.corp_code == corp, ExtendedFactV3.fiscal_year == fy,
    ExtendedFactV3.fiscal_period == period, ExtendedFactV3.statement_type == basis))
for canon, value in prov.get("extended", {}).items():
    session.add(ExtendedFactV3(corp_code=corp, fiscal_year=fy, fiscal_period=period,
                               statement_type=basis, canonical_account=canon,
                               amount_won=value))
```

멱등(같은 delete-then-insert 패턴), `build_corp()`가 도는 모든 경로(데일리 증분 +
전사 재빌드)에 자동 배선됨 — 별도 배선 지점 불필요.

### 3-4. `extended_financials`를 진짜 뷰로 재정의

```sql
CREATE OR REPLACE VIEW extended_financials AS
SELECT ef.corp_code, ef.fiscal_year, ef.fiscal_period AS fiscal_period,
       ef.statement_type AS basis, ef.canonical_account, ef.amount_won,
       1 AS n_facts,                              -- 옛 컬럼 하위호환용 상수(아래 참고)
       s.source_rcepts ->> left(ef.canonical_account, 2) AS source_rcept_no
FROM extended_facts_v3 ef
JOIN std_financials_v3 s
  ON s.corp_code = ef.corp_code AND s.fiscal_year = ef.fiscal_year
 AND s.fiscal_period = ef.fiscal_period AND s.statement_type = ef.statement_type;
```

`n_facts=1` 고정: `confirmed`는 이미 단일값이라 옛 의미(다중매치 개수)가 성립하지 않는다.
`scripts/dq_assertions.py::extended_financials_n_facts_outlier` 어서션은 이 시점부터
**항상 0건**이 되어 무의미해진다 — 폐기하거나, `std_financials_v3.conflicts`(canonical별
보류된 후보 존재 여부)를 보는 새 어서션으로 교체해야 함(§4 열린 질문 ①).

## 4. 열린 질문 (사용자 결정 필요)

1. **`n_facts` DQ 체크 대체**: 폐기 vs `conflicts` 컬럼 기반 재작성 — 후자가 신호는
   더 정확하지만 별도 소규모 설계 필요.
2. **`app/registry/extended.py`/`app/data/extended.py`가 기대하는 컬럼 계약 재확인**:
   현재 `load_extended_all()`은 `canonical_account, amount_won, period_end`만 쓰고
   `n_facts`/`source_rcept_no`는 안 읽음(재확인 완료, `app/data/extended.py:27` 그대로) —
   뷰 재정의가 소비자 쿼리 자체는 안 건드림. `app/registry/extended.py`는 뷰를 직접
   안 읽음(카탈로그 정의만).
3. **note.* 2종(§2) 처리 시점**: 이 트랙과 묶을지, `fact_v2` DROP 직전 별도 트랙으로
   뺄지 — 뺄 것을 권고(원인이 다른 모듈, 리스크 성격도 다름).
4. **소급 백필 범위**: 새 테이블은 `build_corp()`가 다시 돌아야 채워진다(runbook
   패턴 그대로 — 데일리 배선은 자동이지만 **과거 데이터는 소급 안 됨**). 전사
   재빌드(2,845초 규모, 9/1 category-C 백필에서 실측)가 필요 — 계층2 GC 순서(§4-3
   line_audit 이식) 전에 미리 해둘지, line_audit 이식과 묶어 한 번에 재빌드할지 결정 필요.

## 5. 검증 계획 (승인 후)

1. 표본 1~3개사로 `combine_full()`→`prov["extended"]` 결과를 옛 `fact_v2` 기반
   `extended_financials` 결과와 원 단위 대조(예: 삼성전자 `bs.goodwill`,
   `cf.tax_paid`).
2. 전사 `build_corp()` 재실행 후 `extended_financials` 행수/캐노니컬 분포를 DROP 전
   `fact_v2` 기반 뷰 스냅샷과 비교 — 순감소 없는지, 신규 caonical이 튀지 않는지.
3. `extended_financials` 소비자 3개 화면(app/data/extended.py 경유 차트) 스모크.
4. `pytest tests/ fin2/tests/` 회귀 확인 — `combine_full()` 반환 계약(3-튜플)은
   유지하므로(4번째 값은 `prov` 딕셔너리 안에 추가) 기존 27개 호출자 시그니처 영향 없음,
   호출자들이 `prov["extended"]`를 무시해도 무해한지만 확인.
5. Gate B 전수재감사는 **불필요** — DIRECT_MAP/std_v3 값 컬럼(`col`)이나 `_resolve()`/
   `_map_rows()` 로직 자체를 안 건드리므로 std_v3 값에 영향 없음.

## 6. 리스크

낮음 — 새 코드 경로(반환값 1개 필드 추가 + 새 테이블 upsert)일 뿐, `combine.py`의
기존 감사된 로직은 읽기만 하고 안 바꾼다. 유일한 실질 리스크는 §4-④(소급 백필 규모)와
§2(note.* 잔여 블로커)를 놓치고 "재설계 완료"로 착각하는 것.

## 7. 참고

- `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §2-2/§4/§5-b — 이 트랙의 상위 스코핑.
- [[factv2-stdv2-gc-scoping-2026-09-01]] — 메모리, 계층2 GC 트랙 이력.
