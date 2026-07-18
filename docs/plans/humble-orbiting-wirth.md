# Phase B — 본문 전 계정 라인 전수 비교 (Gate B 확장)

## Context

PRD 04 §1·§2 의 본래 목표는 게이트 A 통과 보고서의 **재무제표 본문(BS/IS/CF) 전 계정 모든 라인**을
원본에서 재추출해 DB 값과 표시단위 100% 일치하는지 판정하는 것이다. 그러나 현재 구현된 게이트 B
(Phase A)는 `std_financials_v2` 의 **25개 표준 필드(`STD_FIELD_CANONICAL`)만** 보고서 face 와 대조한다
(`fin2/audit/face_audit.py::audit_std_row`). 즉 소계·기타 계정 등 본문의 나머지 라인은 보고서↔DB
일치가 한 번도 검증된 적이 없다.

Phase B 는 이 갭을 메운다: 보고서 Track A(XBRL) 의 **전 face 라인**을 `fact_v2`(추출된 전 셀)와
**정확 대조**한다. 사용자 확정 정책:
- **측정 우선**: `VALUE_DIFF`(fact_v2 행이 존재하나 won 값 불일치 = 실제 추출 손상)만 promote 차단
  (fail_a). `MISSING_IN_DB`(보고서엔 있으나 fact_v2 에 없음)는 **완전성 지표로 기록만** 하고 차단하지
  않는다 → 규모 파악 후 차단 여부 후속 결정 (PRD §9·§10 단계적 promote 와 정합).
- **Track A 전수·정확대조만**: XBRL 비차원 col0 `TE[@ACODE]` 전 라인을 acode 정확매칭으로 `fact_v2`
  와 1:1 대조 (ADECIMAL 권위 → won 동치 정확). Track B/C(텍스트·PDF)는 acode 부재로 휴리스틱이라
  본 단계 비대상(향후).

기대 산출: 보고서 본문 전 라인의 보고서↔DB 일치율 + 불일치 클래스(VALUE_DIFF/MISSING/EXTRA) 규모
측정. 전수 통과 시 PRD 04 DoD(본문 전 계정 100% 일치)를 진짜로 충족.

## 핵심 재사용 자산

- `fin2/audit/face_audit.py::read_report_face_xbrl(fp)` — 이미 **전 비차원 col0 TE[@ACODE] 라인**을
  `FaceLine`(acode·basis·displayed_value·adecimal·`amount_won`·is_cumulative)로 반환. canonical 미매핑
  라인도 `canonical=None` 으로 포함 → **보고서 진실집합 그대로**. 새 reader 불필요.
- `fact_v2` 테이블 — 추출된 전 셀. unique `(rcept_no, acode, acontext_raw)`, 컬럼 `amount_won`·
  `adecimal`·`basis`·`col_index`·`is_dimensional`·`is_cumulative`. **Phase B 대조 상대.**
- `gateb_audit.py::audit_corp` — 이미 각 rcept 의 face 를 `face_cache` 에 1회 파싱(XML 1회 읽기).
  Phase B 를 같은 패스에 끼워 **추가 파싱 없이** 재사용.
- 표시단위 ±1 허용 로직 — `audit_fields`(face_audit.py 698행 부근, `tol = 10**(-adecimal)`). 공용
  헬퍼로 추출해 라인 대조에 재사용.
- promote 뷰 `standard_financials` (collector/db.py 132행) — `gate_status='fail_a'` 차단. 측정 우선
  이므로 **이번엔 뷰 변경 없음**(Phase A 게이트 유지).

## 변경 사항

### 1) 신규 `fin2/audit/line_audit.py` — 라인 단위 대조 코어
순수 함수(독립성·테스트 용이). DB 세션/IO 없음, 입력은 이미 읽은 face 라인 + fact 행.

```python
@dataclass
class LineAudit:        # 한 보고서 라인의 대조 결과
    acode: str; basis: str|None; statement: str|None; label: str
    report_won: int|None; db_won: int|None
    match: bool; reason: str|None   # None=match / VALUE_DIFF / MISSING_IN_DB / EXTRA_IN_DB

@dataclass
class ReportLineAudit:  # rcept 단위 롤업
    rcept_no: str
    n_match:int; n_value_diff:int; n_missing:int; n_extra:int
    value_diffs: list[LineAudit]    # 차단 후보(상세 기록)
    missing: list[LineAudit]        # 완전성 지표(상세 기록)

def won_match(a:int, b:int, adecimal:int|None) -> bool:
    # 표시단위 ±1 허용(부호반대 포함) — audit_fields 와 동일 규약, 공용 헬퍼로 추출

def reconcile_report_lines(rcept_no, face_lines, fact_rows) -> ReportLineAudit:
    # face_lines: read_report_face_xbrl 결과 중 acode 가 ifrs-full_/dart_ 접두(=Track A 순수라인)만.
    #   (텍스트 보충 라인은 acode=라벨 → 접두 불일치로 자연 제외)
    # fact_rows: fact_v2 WHERE rcept_no=? AND col_index=0 AND NOT is_dimensional.
    # 인덱스: (acode, basis, is_cumulative) → fact.amount_won
    # 각 face 라인:
    #   fact 있고 won_match → n_match
    #   fact 있고 불일치   → VALUE_DIFF (차단 후보)
    #   fact 없음          → MISSING_IN_DB (지표)
    # 역방향: fact 행 중 face 에 없는 것 → EXTRA_IN_DB (지표; 대개 감사 reader 커버 갭)
```

basis 대조는 Phase A 규약 따름(face.basis 명시일 때만 강제, None 라인은 양쪽 허용). statement 는
진단용(`_statement_of` 재사용).

### 2) 신규 테이블 `face_line_audit` — 라인 감사 대장 (collector/models.py + db.py)
그레인 = `rcept_no`(보고서 단위, fact_v2 키와 일치). 라인 전건 저장은 과대(2557사×전기간×수십라인)
→ **롤업 카운트 + 불일치 상세 JSONB**로 face_audit 패턴(fail_detail/pending_detail) 미러.

| 컬럼 | 형 | 비고 |
|---|---|---|
| rcept_no | varchar(14) PK | FK filings |
| corp_code | varchar(8) | 조회용 |
| track | varchar(2) | 'A'(이번 범위). B/C 는 향후 |
| n_lines / n_match / n_value_diff / n_missing / n_extra | int | 롤업 |
| line_gate_status | varchar(8) | `pass`(value_diff=0) / `fail_a`(value_diff>0) / `pending`(Track≠A·0라인) |
| value_diff_detail | jsonb | [{acode,basis,statement,label,report_won,db_won}] |
| missing_detail | jsonb | 동(완전성 지표) |
| reader_version / checked_at | | |

`collector/db.py` 의 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 멱등 패턴으로 create_all 보강.
**promote 뷰는 변경 안 함**(측정 우선). value_diff 규모 확인 후 별도 결정으로 뷰에
`line_gate_status<>'fail_a'` 조인 추가 가능(후속, 본 계획 비범위).

### 3) `gateb_audit.py::audit_corp` 에 라인 감사 통합 (같은 face_cache 재사용)
- corp 의 std_v2 가 참조하는 distinct source rcept 집합(이미 `rcepts` 로 수집됨)에 대해, 각 rcept 의
  `face_cache` Track A 라인(접두 필터)으로 `fact_v2` col0 비차원 행을 한 번에 로드해
  `reconcile_report_lines` 실행 → `face_line_audit` upsert.
- 별도 XML 파싱 없음(face_cache 재사용). fact_v2 는 rcept 별 1쿼리.
- 신규 `--line-audit`(기본 on) 플래그로 토글, `--no-commit` 기존대로 존중.
- 집계(agg)에 line 카운터 추가(러너 요약 출력에 value_diff/missing 규모 표시).

### 4) `verify_corp_sequential.py` 롤업 확장
- step 6 `_rollup` 에 `face_line_audit` 집계 추가 → `corp_verify_status` 에 컬럼
  `line_value_diff`·`line_missing`·`line_total` 추가(collector/models.py `CorpVerifyStatus`).
- step 5 는 그대로 `gateb_audit.audit_corp` 호출(라인 감사가 함께 수행됨).

## 검증 (DoD)

1. **단위 테스트** `fin2/tests/test_line_audit.py`:
   - won_match(표시단위 ±1·부호반대) 케이스.
   - reconcile: match / VALUE_DIFF / MISSING_IN_DB / EXTRA_IN_DB 각 1+ 합성 케이스.
2. **표본 파일럿**: PRD §8 표본(삼성전자·신흥에스이씨·리메드·큐로셀) 최근 연간/분기 rcept 로
   `reconcile_report_lines` 실행 → value_diff 상세 수기 확인(Track A 정확대조라 0 이어야 정상,
   불일치 시 acode·won 출력으로 추출버그 vs 감사reader 구분).
3. **소표본 전수**: `python scripts/verify_corp_sequential.py --corps 0:20 --skip-download --recheck`
   → `face_line_audit` 적재 확인. 쿼리:
   ```sql
   SELECT count(*) rpt, sum(n_value_diff) vd, sum(n_missing) miss, sum(n_match) m
   FROM face_line_audit;
   SELECT corp_code, rcept_no, n_value_diff, value_diff_detail
   FROM face_line_audit WHERE n_value_diff>0 ORDER BY n_value_diff DESC LIMIT 20;
   ```
4. **전수(후속, 사용자 실행)**: 8-way 샤딩 재실행으로 전 보고서 라인 감사 → value_diff(차단후보)·
   missing(완전성갭) 전사 규모 측정 → 트리아지(추출버그=PRD03 회부 / 감사reader갭=face_audit 보강).

## 비범위 / 후속
- Track B/C 라인 전수 대조(텍스트·PDF, label 휴리스틱) — 별도 단계.
- value_diff 를 promote 뷰에 실제 차단 연결 — 규모 측정 후 결정.
- 주석 재무항목(PRD 04 2단계).
