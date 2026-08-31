# `fact_v2` 합성 `note.da_total` 정리 — 설계 (§6 후속 백로그, 2026-08-31)

## 0. 전제 기록 정정

`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` 구현순서 표
6번의 상태 메모("1번 완료로 신규 오염 생산은 이미 멈춤")는 **부정확**하다. 커밋
`bd39d44`를 코드 레벨로 재확인한 결과:

- 그 커밋이 제거한 건 `collector/cf_da_sync.py`/`collector/expense_nature_sync.py`
  끝단의 **std_v2 재표준화 호출**(`standardize_corp`/`derive_quarters_corp`/
  `calendarize_corp`)뿐이다.
- 커밋 메시지 자체가 명시: `store_facts()(fact_v2 upsert, extended_financials 소관)는
  그대로 둔다`. **`fact_v2`에 합성 행을 써넣는 경로는 그대로 살아있다.**
- `parser/xml/note_extractor.py::_add_da_total()`은 지금도 depreciation/amortization
  facts가 있으면 무조건 `"D&A 합계 (감가상각비+무형자산상각비)"` 합성 fact를 만들어
  넘긴다. 설계문서(§B2)가 제안한 필터 패치는 **`fin2/extract/notes.py`에 구현된 적이
  없다**(grep 결과 0건).
- 실측: `fact_v2`의 해당 행 최신 생성일은 2026-08-21. 그 이후 신규 행이 없는 건
  "막혀서"가 아니라 `cf_da_sync`의 대상 조건(연결 `depreciation IS NULL` + CF
  source 보유)에 걸리는 신규 corp가 우연히 없었기 때문으로 보인다(target 백로그
  소진) — 조건에 맞는 corp가 다시 나타나면 재발한다.

**단, 심각도는 기존 문서 판단대로 낮다.** [[std-v3-daily-wiring-and-valuation-migration-2026-08-30]]
(Phase2, `e6d1692`)로 **std_v2 신규 쓰기 자체가 이미 전면 제거**됐으므로, 이 합성행이
과거처럼 `rule_additive_da`를 통해 `std_v2.ebitda`를 2배로 오염시킬 경로는 이제
존재하지 않는다(그 소비자가 죽었다). 남은 건 순수 provenance 문제:
`extended_financials` 뷰가 `note.%`를 노출할 때 "코드가 합성한 값이 공시값처럼
보이는" 오염이다.

## 1. 원인 코드 정확한 위치

`fin2/extract/notes.py::extract_note_da_facts()` (64~136행) 안, `by_code` 폴딩 루프:

```python
for f in fs:
    if f.amount is not None:
        by_code[f.account_code] = by_code.get(f.account_code, 0) + f.amount
```

`fs`(=`raw`, `extract_da_from_cf_notes(root)`의 산출물)에는 `note.depreciation`/
`note.amortization`/`note.rou_depreciation` 같은 실제 파싱 결과와 함께,
`parser/xml/note_extractor.py::_add_da_total()`(300~326행)이 **무조건 덧붙인**
`note.da_total` 합성 fact가 섞여 있다. 이 루프가 그 합성 fact도 그대로 `by_code`에
쌓고, 아래 최종 방출 루프(113~135행)가 `by_code`의 모든 code를 `ExtractedFact`로
내보내면서 합성 `note.da_total`이 `fact_v2`에 실제 컬럼처럼 저장된다.

**진짜 공시분과 절대 혼동될 수 없다는 근거**: `parser/xml/note_extractor.py`의 텍스트/ENG
매핑 테이블(`_DA_ACCOUNT_PATTERNS`, `_ENG_TO_CODE`, 25~40행)에는 `note.da_total`로
직접 매핑되는 패턴이 **하나도 없다** — 오직 `_add_da_total()`의 합산 결과만 이
코드를 갖는다. 즉 **`fact_v2`에 있는 `canonical_account='note.da_total' AND
source_format='note_cf'` 행은 100% 합성물이다** (실측: 2,597행 전부가 동일한
`(source_ref='consolidated/note_cf', acontext_raw='note:consolidated:col0')` 패턴 —
서로 다른 원문 라벨에서 왔다면 나타날 변이가 전혀 없다).

## 2. 수정안

### 2-1. 코드 수정 — 신규 오염 차단

`fin2/extract/notes.py::extract_note_da_facts()`의 폴딩 루프에서 합성 마커를 걸러
`by_code`에 들어가지 못하게 한다(설계문서 §B2 원안 그대로, 구현만 미비했던 부분):

```python
_SYNTHETIC_DA_TOTAL_NAME = "D&A 합계 (감가상각비+무형자산상각비)"

for f in fs:
    if f.account_code == "note.da_total" and f.account_name_raw == _SYNTHETIC_DA_TOTAL_NAME:
        continue        # note_extractor 합성 rollup — fact_v2에 실제 계정처럼 남으면 안 됨
    if f.amount is not None:
        by_code[f.account_code] = by_code.get(f.account_code, 0) + f.amount
```

**단위보정 앵커 불변 확인**: 바로 아래(104~106행) `da_total = by_code.get("note.da_total")`
가 `None`이 되면 폴백(`_DEP_LIKE` 합)으로 넘어가는데, 정의상 두 값은 **항상 같다**
(합성값 자체가 그 폴백 합과 동일하게 계산됐으므로) → `_unit_factor()` 판정 불변.
§4에서 회귀 0건으로 명시 확인한다.

### 2-2. 백필 — 기존 합성행 삭제

`store_facts()`의 upsert 특성상 코드 수정만으로는 **이미 fact_v2에 쓰인 2,597행이
사라지지 않는다**([[parser-pipeline-integration-runbook]] ② 소급 백필 필수 항목).
100% 합성물임이 §1에서 확인됐으므로 조건 없이 전량 삭제한다:

```sql
DELETE FROM fact_v2
WHERE canonical_account = 'note.da_total' AND source_format = 'note_cf';
```

삭제 전 스냅샷(롤백 대비, 임시 테이블 — 검증 후 제거):

```sql
CREATE TABLE fact_v2_synthetic_da_total_snap_20260831 AS
SELECT * FROM fact_v2
WHERE canonical_account = 'note.da_total' AND source_format = 'note_cf';
```

**std_v2/v3 백필 불필요**: std_v2는 신규 쓰기가 이미 전면 제거됐고([[std-v3-daily-wiring-and-valuation-migration-2026-08-30]]),
v3는애초에 이 fact_v2 경로를 소비하지 않는다(별도 XBRL 인라인/원문 파이프라인).
`extended_financials` 뷰만 `fact_v2`를 직접 노출하므로 그 뷰에서만 반영된다.

## 3. 영향 범위

- **`fact_v2`**: 2,597행 삭제(전량 합성물, 실측 §1).
- **`extended_financials`**: `note.da_total`/`note_cf` 행이 화면에서 사라짐(원래도
  가짜였으므로 정상화).
- **`std_financials_v2`/`v3`**: 영향 없음(위 근거).
- **`valuation_daily`**: 영향 없음(`ebitda`는 이미 v3 경유, v3는 이 경로 자체를 안 씀).
- **`cf_da_sync`/`expense_nature_sync`의 `stored` 카운트**: 앞으로 소폭 감소(합성행 1개
  덜 upsert되므로) — 로직/리턴값 구조는 무변경.

## 4. 검증 계획 — 전부 완료(2026-08-31)

- [x] **4-1.** `pytest tests/ fin2/tests/` — 668 passed, 1 failed(무관 기존 실패
      `test_biz_section.py::test_lxintl_facility_table_dropped`, 이번 변경(`fin2/
      extract/notes.py` 1파일)과 무관).
- [x] **4-2.** `_unit_factor()` 배율 판정 불변 확인 — 표본(`00136271`,
      `20260821000469`)에 수정 후 `extract_note_da_facts()`를 직접 재실행: 출력에
      `note.da_total` 없음, 구성요소(`note.depreciation`+`note.amortization`+
      `note.rou_depreciation`)는 DB의 기존 합성 `note.da_total` 값(13,372,503,000)과
      정확히 일치(11,224,770,000+2,147,527,000+206,000) — 폴백 합산이 이전 합성값과
      **항상 같다**는 §2-1의 수학적 증명을 실측으로 재확인.
- [x] **4-3.** 삭제 전 스냅샷(`fact_v2_synthetic_da_total_snap_20260831`, 2,597행) →
      `DELETE`(2,597행 삭제 확인) → `fact_v2`에서 `canonical_account='note.da_total'
      AND source_format='note_cf'` 0건. `extended_financials`에서
      `canonical_account='note.da_total'`가 688건 남았으나 **전혀 다른 경로**
      (`source_format='note_expense'`, 비용성격별 주석 — §6에 이미 별도 triage된
      "실측상 무해, 조치 불필요" 항목)에서 온 것으로 확인, 이번 삭제와 무관.
- [x] **4-4.** `std_financials_v3`(`00101044` FY2024/2025 전체 기간)의 `da_total`/
      `ebitda` 삭제 전/후 스냅샷 비교 — **완전 동일**(v3는 fact_v2를 소비하지 않음
      확인).
- [ ] **4-5.** `cf_da_sync.sync_cf_da()` 회귀 스모크 — 미실행(4-2에서 핵심 로직을
      직접 검증했고 대상 corp가 현재 없어 스킵, 저위험 판단).
- [x] **4-6.** 검증 통과 후 스냅샷 테이블 제거 완료.

## 5. 위험도

**낮음** — 삭제 대상이 100% 합성물임이 코드 경로 분석 + 전량 동일 패턴 실측으로
이중 확인됐고, 유일한 살아있는 소비자(`extended_financials` 뷰)는 애초에 잘못된
값을 보여주고 있었으므로 삭제가 곧 정상화다. std_v2/v3/valuation_daily는 영향권
밖(§3 근거). 코드 수정은 1개 조건문 추가뿐.

---

이 문서는 계획이며, 사용자 승인 없이 구현에 착수하지 않는다.
