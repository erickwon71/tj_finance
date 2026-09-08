# 설계: `basis_fallback` 시 "직전연차 재게재" 배제(R63) 무력화 버그 수정 (2026-09-08)

## 배경 — v2-drop-remaining-backlog 항목2 표본검증 중 발견

`std_financials_v3`에서 **연결(consolidated) 인터림(Q1/H1/Q3) 매출액이 직전 사업연도(FY)
매출액과 원 단위까지 완전 일치**하는 지문으로 전수 스캔한 결과 146건(fy2000~2010,
68개사) 발견. 사용자가 10개 표본(뉴인텍·LS·농심·비비안·삼목에스폼×2·원풍×2·
진흥기업×2·우리엔터프라이즈)을 DART 원문과 직접 대조해 **전부 "결측 처리가 맞다"**로
확인됐고, 원인이 명확히 두 갈래로 갈렸다:

- **버킷A**(35건/27개사, 뉴인텍·LS·농심·진흥기업[2005Q1] 등): 원문 자체에 연결
  당기(분기) 데이터가 없음(그 시대 연결 인터림 작성의무 없음 — DKME 사례와 동일).
  `report_lines`에 해당 rcept·`consolidated` 행이 **존재**(값은 있지만 원문상
  직전연차 비교열을 당기로 잘못 취급).
- **버킷B**(111건/43개사, 비비안·삼목에스폼·원풍·우리엔터프라이즈·진흥기업[2002H1]
  등): 원문에 연결 섹션 자체가 아예 없음. `report_lines`에 해당 rcept·`consolidated`
  행이 **0개** — 그런데 `std_financials_v3`엔 값이 채워져 있음. 이 문서가 다루는
  범위.

버킷 분류는 `report_lines`에 그 rcept·`consolidated` 행이 있는지(A)/없는지(B) 만으로
DB에서 기계적으로 판별 가능함을 표본 10건 100% 일치로 검증했다(`v2-drop-remaining-
backlog-2026-09-03.md` 항목2 최신 갱신 참고).

## 근본원인 — `fin2/layer3/combine.py::combine_full()` (라인 3173~3200 부근)

`basis_fallback`(자회사 없는 회사가 별도만 제출 → 연결 = 별도로 대신 쓰는 기존 정당한
설계, 라인 3181-3191)이 트리거되면:

```python
if not cands:
    other = "separate" if basis == "consolidated" else "consolidated"
    bases_present = {r["basis"] for r in merged}
    if bases_present == {other}:
        cands = _map_rows(merged, period, other, statements, corp=corp, fy=fy)
        prov["basis_fallback"] = True
```

`cands`(사용할 원문 행 후보)는 실제로 `other`(예: `separate`) 쪽 데이터로 채워지는데,
바로 다음의 "직전연차 재게재 배제"(R63, 2026-09-02 도입) 호출은 여전히 원래 요청받은
`basis`(예: `consolidated`)로 조회한다:

```python
stale_reprint_seqs = {
    "is": _stale_annual_reprint_table_seqs(session, corp, fy, period, basis, statement="IS"),
    "cf": _stale_annual_reprint_table_seqs(session, corp, fy, period, basis, statement="CF"),
}
confirmed, conflicts = _resolve(cands, corp, fy, period, basis, stale_reprint_seqs)
```

`_stale_annual_reprint_table_seqs()`는 `WHERE ... basis=:b`로 조회한다
(`combine.py:1731,1738`). 버킷B 회사는 `consolidated` 행이 애초에 0개이므로 이 조회는
**항상 빈 결과** → 배제 대상 table_seq 집합이 빈 set() → R63 배제가 아무것도 못 걸러냄.
그런데 실제 후보(`cands`)는 `separate`에서 빌려온 것이라, **`separate`라면 정상적으로
걸러졌을 "직전연차 재게재" 표가 `consolidated`로는 그대로 통과**해 `_resolve()`가 그
값을 confirmed로 확정해버린다.

증거: 표본 회사들의 `separate` 자체 값은 (같은 재게재 표 때문에) 정상적으로 NULL/충돌
처리되는데, `basis_fallback`으로 파생된 `consolidated` 값만 재게재 값이 그대로 채워져
있음 — `separate`엔 있는 방어가 `consolidated` 파생 경로에만 없다는 정확한 증거.

라인 3313-3326(산업별 revenue profile의 2번째 소비처)의 주석 "Reuse the same stale
set _resolve() already used (mirrors its basis handling, including the basis_fallback
edge case)"는 **이미 처리됐다고 착각한 흔적**으로 보인다 — 실제로는 `stale_reprint_seqs`
자체가 애초에 잘못된 basis로 계산돼 있어 이 재사용도 같이 무력화된다.

## 수정안

`other`가 `if not cands:` 블록 안에서만 정의되므로(폴백 미발동 시 미정의), 블록 밖에서
안전하게 참조 가능한 `stale_basis` 변수를 도입한다.

```python
prov = {"basis_fallback": False, "amended_cols": [], "amend_chain": {}}
stale_basis = basis          # ★신규 — 실제로 데이터를 가져온 basis(재게재 배제 조회용)
if rcept_by_stmt is not None:
    ...
elif select_filing:
    if merged is None:
        merged = build_merged_lines(session, corp, fy, period)
    cands = _map_rows(merged, period, basis, statements, corp=corp, fy=fy)
    if not cands:
        other = "separate" if basis == "consolidated" else "consolidated"
        bases_present = {r["basis"] for r in merged}
        if bases_present == {other}:
            cands = _map_rows(merged, period, other, statements, corp=corp, fy=fy)
            prov["basis_fallback"] = True
            stale_basis = other      # ★신규 — 실제 데이터 출처로 맞춤
else:
    ...
stale_reprint_seqs = {
    "is": _stale_annual_reprint_table_seqs(session, corp, fy, period, stale_basis, statement="IS"),
    "cf": _stale_annual_reprint_table_seqs(session, corp, fy, period, stale_basis, statement="CF"),
}
```

`basis` 자체(그 뒤 `_resolve(cands, corp, fy, period, basis, ...)` 호출 등)는 그대로
둔다 — `_resolve()`는 "이 값이 어느 std_v3 컬럼(consolidated row)으로 갈지" 판정이지
"어느 원문 basis에서 재게재를 걸러낼지"와는 다른 관심사이므로 바꾸지 않는다. 바꾸는 건
`_stale_annual_reprint_table_seqs()` 호출 두 곳뿐 — 최소 변경.

라인 3313-3326(revenue profile) 쪽은 `stale_reprint_seqs`를 그대로 재사용하는 기존
코드라 이 수정만으로 자동으로 같이 고쳐진다(별도 수정 불필요).

## 영향범위 — 111건/43개사보다 클 수 있음(★확인 필요)

지금까지 잡은 111건은 "매출액이 직전 FY와 원 단위까지 정확히 일치"라는 **좁은 지문**으로
찾은 것이다. 이 버그 자체는 `basis_fallback` + `_stale_reprint`가 겹치는 모든 경우에
발동하므로:
- **매출액이 아닌 다른 concept**(net_income, operating_income 등)에도 같은 경로로
  재게재 값이 샜을 수 있다(census를 매출액 하나로만 했음).
- **`report_fiscal_year - 1`이 아닌 더 먼 과거 재게재**(예: 2년 전)는 이번 census
  필터(`fy = fy-1`)에 안 걸렸을 수 있다.
- **CF 쪽 재게재**(R63이 IS 다음에 CF까지 확장됐음, `_STALE_REPRINT_PERIODS`/
  `_STALE_REPRINT_MAX_FY` 스코프 내)도 같은 구조로 샜을 가능성.

→ 구현 후 **111건 좁은 재확인**뿐 아니라, `basis_fallback=True`인 전체 std_v3 행을
전/후 비교하는 **넓은 dry-run diff**를 반드시 돌려 실제 영향범위를 재실측한다(아래
검증계획 참고).

## 검증 계획

1. **신규 회귀 테스트** — `fin2/tests/test_combine_*.py`에 버킷B 표본 1~2개사
   (예: 우리엔터프라이즈 00155692 또는 비비안 00107677)로 "basis_fallback +
   재게재 표 공존" 케이스를 픽스처로 구성, 수정 전 재현(현재 버그값 확정) →
   수정 후 NULL/충돌로 바뀜을 확인하는 테스트 추가.
2. **`pytest tests/ fin2/tests/` 전체** — 회귀 0건 확인(기존 실패 1건
   `test_lxintl_facility_table_dropped`는 무관, 불변 확인).
3. **좁은 재확인** — 이번에 찾은 111건(43개사) 재조회, 전부 해소(NULL 또는 새 값)
   확인.
4. **넓은 dry-run diff**(★신규, 위 "영향범위" 문제의식 반영) — `basis_fallback=True`로
   기록된 std_v3 전체 행(현재/수정후 두 버전)을 비교해, 111건 밖에서 추가로
   바뀌는 행이 있는지 전수 확인. 바뀌는 행은 전부 "NULL로 감" 방향이어야 정상
   (R63 배제가 새로 작동해 값을 없애는 것이지 값을 새로 만들지 않으므로) — 혹시
   값이 새로 생기거나 다른 값으로 바뀌는 행이 있으면 그건 이 설계가 놓친 부작용,
   구현 중단하고 재검토.
5. **`dq_assertions.py` 전수** — 신규 ERROR 0건 확인.
6. **버킷A(35건/27개사)는 이 수정과 무관** — `report_lines`에 실제 값이 있어
   `cands`가 처음부터 비지 않으므로 `basis_fallback` 자체가 발동 안 함. 별도
   트랙(DKME와 동일한 개별 report_lines 삭제+재빌드)으로 처리.

## 롤백 안전성

`combine_full()`은 `std_financials_v3`를 매번 `report_lines`에서 새로 조립하는
순수 함수 경로다(원본 `report_lines`는 이 수정으로 전혀 건드리지 않음) — 문제가
생기면 코드만 되돌리고 영향받은 corp만 재빌드하면 즉시 원상복구된다.

## 구현 결과 (2026-09-08, 같은 세션 — "1차" 마무리)

**코드 수정 완료**: `fin2/layer3/combine.py::combine_full()`에 `stale_basis` 변수 도입
(위 수정안 그대로). 신규 회귀테스트 3개
(`fin2/tests/test_combine_basis_fallback_stale_reprint_2026-09-08.py`) — 비비안
(00107677 2002H1)·00106395(2000H1) 정상 해소 확인 + 뉴인텍(00105040 2007Q1, 버킷A라
`basis_fallback=False`로 이 수정과 무관함을 확인)으로 두 원인이 코드 경로부터 다름을
고정. `pytest tests/ fin2/tests/` **876 passed**(무관 기존실패 1건
`test_lxintl_facility_table_dropped` 불변, 회귀 0).

**111건 재검증(combine_full 직접 호출, DB 미변경 — 순수 함수 재현)**: **53건 해소
(자연스럽게 revenue=None 또는 다른 값으로) / 58건 미해소**.

★**58건 미해소 원인 추가 조사(같은 세션) — 이 설계 스코프 밖의 별개 문제 2가지 발견**:
1. **48건 — `report_lines.table_seq`가 NULL**(`unit_source='pdf'`, Track C PDF복구
   경로로 들어온 절단본 필링). R63의 재게재 배제는 table_seq로 표를 식별하는 구조라
   NULL이면 배제 대상 자체를 못 정한다. 현재 XML 재추출도 본문을 못 찾음(원래 PDF
   복구가 필요했던 이유 그대로) — PDF 추출 경로(`fin2/extract/pdf.py`)에 table_seq
   개념을 새로 부여하는 별도 작업 필요.
2. **10건 — R63 알고리즘 자체가 이 지문을 검사하지 않음**. 실측(00112059 2003Q1,
   증권사)으로 확인: table_seq는 정상(0,1)이고 두 표가 실제로 **다른 값**(영업수익
   467억 vs 2,390억)이라 "동일값 재게재"가 아닌 별개 현상. R63은 "같은 회계연도 안
   다른 분기와 값이 겹치는지"만 검사하는데(`_stale_annual_reprint_table_seqs`),
   이번 census 지문("이번 분기=작년 사업보고서", 연도 교차비교)은 원래 R63의
   검사 대상이 아니다 — 53건이 해소된 건 "그 회사가 마침 같은 해 다른 분기와도
   겹쳤기 때문"이지 이 지문을 직접 겨냥한 게 아니었다.

**dq_assertions 전수**: `statement_magnitude_impossible` **0건**(DKME 건은 이번
세션 앞부분 별도 작업으로 이미 종료, 이 수정과 무관), 신규 ERROR 0건.

**넓은 dry-run diff는 미실시**: `basis_fallback=true` 전체 행이 std_v3에
**62,150건**(fy≤2012만도 40,057건)이라 `combine_full()`을 행마다 파이썬 루프로 재호출하는
방식은 비현실적으로 오래 걸림(★장시간명령 금지 원칙) — 시도했다가 중단. 이번
세션의 검증은 111건 표본 재확인 + 회귀테스트 + 전체 pytest + dq_assertions로 갈음.
**전사 재빌드는 이번 세션에 안 함**(코드만 커밋, DB엔 아직 반영 안 됨) — 사용자가
다음에 스코프를 정해(예: 이번에 식별된 68개사만, 또는 fy≤2012 전체) 직접 재빌드
실행 권장.

**커밋 대상**: `fin2/layer3/combine.py`(핵심 수정) +
`fin2/tests/test_combine_basis_fallback_stale_reprint_2026-09-08.py`(신규 테스트) +
이 설계문서. **DB 변경 없음**(재빌드 전).

## 다음 세션 인수인계

1. **버킷B 잔여 58건**(위 48건+10건) — R63 확장 필요, 별도 설계 세션.
2. **버킷A 35건/27개사** — DKME와 동일 패턴(report_lines에 실값 있음, 원문상 당기
   데이터 자체 없음). 이번 세션엔 DKME 1건만 처리; 나머지 26개사는 개별 원문대조
   불필요(메커니즘 이미 뉴인텍·LS·농심·진흥기업으로 4개사 검증 완료) — 바로
   report_lines 삭제+재빌드 진행 가능.
3. **오늘 고친 코드의 전사 반영**(재빌드) — 아직 안 함. 스코프 결정 필요(68개사만 /
   fy≤2012 전체 / 전사).

## 참고

- [[v2-drop-remaining-backlog-2026-09-03]] 항목2, 최종 갱신 블록
- R63 원 설계: `docs/PARSING_RULES.md` R63 섹션(직전연차 재게재 배제 도입 배경)
- 표본 검증 아티팩트: https://claude.ai/code/artifact/b7368253-fb6e-4d9e-95ec-13f836d8412c
