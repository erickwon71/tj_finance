# 4계층 재설계 — 파서=원문 tree 충실전사, 취합=별도 계층

> ★ **승인됨(2026-07-19).** 이 계획은 Phase C(단일 파이프라인 재구축)의 **계층 2~3 접근을 대체**한다.
> 착수 문서 = `docs/qa/handoff_rearchitecture_2026-07-19.md`. 구 Phase C 계획 =
> `docs/plans/loop-vivid-bubble.md`(보존). 관련: [[rebuild-phase-a3-done]] · [[feedback-plan-docs-in-project]]

## Context — 왜 재설계하나

이번 세션의 반복된 고통(finance_cost·retained_earnings·capex·**금융업 이중섹션**)은 전부
**파서가 "값/canonical/취합"을 판단**해서 생겼다. 특히 KG케미칼 금융업 이중섹션(현금및현금성자산이
유동자산 288.7B + 금융업자산 2.1B 두 곳 = 합 290.8B, CF 기말현금과 정확 일치)은 **평면 fact 로는
합산-vs-제외를 구분할 수 없어** 헤드라인(현금·유형자산·차입금)이 통째로 결측됐다. 원인은 **tree(계층)가
없고 판단이 파서에 섞여서**다.

**목표**: 책임을 4계층으로 분리해 각 계층의 논리오류를 격리한다(사용자 확정).
1. **Downloader** — 보고서만 다운로드(주기적). 오류는 다운로드 계층에서만.
2. **파서 → 원문 raw tree** — 보고서 항목·값을 **tree 구조 그대로** DB화. canonical/grouping 없음.
   단위만 원(₩)으로 정규화 + 단위선언 오류 확인. **검증 = 보고서 원문과 1:1 대조.**
3. **취합 계층** — raw tree 를 원하는 canonical(+capex 등 파생·사용자 커스텀)로 매핑·취합.
   **모든 값판단(금융업 합산·capex 소계·K-IFRS)은 여기서**, tree 문맥 + 기업별 리뷰로.
4. **App** — 취합 계층 계정 시각화(기존 앱 재사용).

## 확정 결정 (2026-07-19)
- 계층2 = **신규 `report_lines` tree 테이블**(greenfield). fact_v2 는 계층3 전환까지 공존→퇴역.
- tree 충실도 = **섹션경로 + 행순서 + depth + 소계flag**(부모=성분합 강제 안 함; 반올림·공란 대비).
- 기존 취합자산(concept_map·account_maps·std_v2·reconcile·D4 로직) = **계층3으로 이관·재사용**.
- **전량 79k·swap 보류** → 계층2 재설계 → 계층3 이관 → 그다음 전량.

---

## 계층 2 — `report_lines` (이번 재설계의 핵심 작업)

### 원칙
- **무손실 충실전사**: 본문(BS/IS/CF) + **주석** 의 모든 라인을 보고서 순서·구조 그대로.
- **판단 없음**: canonical 매핑·계정 grouping·값 선택/취합 **일절 안 함**. 새 계정명은 그대로 저장
  (사전 등록 불요 — grouping 은 계층3의 일). max-abs·항등식·폴백 전부 없음.
- **단위만**: 선언된 단위로 원(₩) 정규화. **미선언은 보류(스킵)+flag**(추측 금지 — 기존 원칙 계승).

### 신규 테이블 `report_lines` (개략)
```
rcept_no, corp_code, report_fiscal_year, report_fiscal_period,
statement (BS|IS|CF|SCE|note), basis (consolidated|separate),
section_path (예: '자산>유동자산' / '자산>금융업자산' / '부채>유동부채'),  ← 금융업 구분 핵심
row_order (표 내 등장 순서), depth (들여쓰기/중첩), is_subtotal (섹션헤더·소계 여부),
label_raw (원문 계정명 그대로), col_index (0당기/1전기/2전전기), context_fiscal_year,
value_won (원 정규화), adecimal, unit_source (declared|none),
period_kind, is_cumulative, source_ref, acontext_raw, parsed_at
```
- 라인 × 컬럼 1행. canonical_account **없음**(계층3 산출).

### 재사용(기존 → 계층2 엔진)
- `fin2/extract/text.py`: 섹션 네비게이터·`declared_unit`·`_AMOUNT_CELL_RE`·`table_direct_rows`·
  `_row_to_fact`(값/단위/col 로직) — **그대로 계층2 추출엔진**. (canonical 호출만 제거.)
- `fin2/extract/statement_titles.py`·`parser/xml/section_detector.py` — 섹션·하위섹션 항해.
- `fin2/extract/xbrl.py`(Track A) — XBRL 은 calc linkbase 로 tree 구성.

### 신규 구현 (계층2에 추가)
- **하위섹션 경로**: 섹션 헤더/소계 행(유동자산·비유동자산·**금융업자산**·부채 등)을 인식해
  각 라인에 `section_path` 부여. → 금융업 이중섹션이 구조로 구분됨(합산은 계층3 몫).
- **row_order·depth·is_subtotal**: 표 TR 순서·들여쓰기·'합계/소계/총계' 라벨로 **위치·계층 기록**
  (값 판단 아님 = 충실전사 유지).
- **주석 tree 확장**: 현재 D&A/R&D 만 → 본문 주석 표 전체를 tree 로.

### 검증 (계층2 완료 판정)
- **보고서 원문 ↔ report_lines 1:1**: 라벨·값(원)·위치(section_path·순서) 일치. 기업별·보고서연도별.
- 재사용: `fin2/audit/face_audit.py`·`line_audit.py`(이미 보고서 face↔DB 대조. Phase A 호환
  복구됨=커밋 dd70db3). report_lines 대상으로 확장.
- **금융업 카나리아(KG케미칼 2023FY, rcept 20240321001911)**: 현금및현금성자산이 `자산>유동자산`
  288,717,146,272 **과** `자산>금융업자산` 2,112,712,279 **두 라인 모두** 존재(합 290.8B).
  단기차입금(유동)·차입금(금융업) 별도 라인.

---

## 계층 3 — 취합 (계층2 완료 후 착수)

- **입력**: `report_lines` tree.
- **매핑**: 주요 노드(소계·알려진 계정) → canonical. **사전 = 기존 concept_map/account_maps 이관**
  (파서에서 뗀 것). 신규 계정명은 여기서 계속 확장.
- **파생·커스텀 계정**: capex·EBITDA·net_debt 등 + 사용자 커스텀 취합계정. 보고서엔 없는 계정 생성.
- **값판단 = 전부 여기서**(tree 문맥 활용):
  - **금융업 합산**: `section_path` 로 일반+금융업 동일계정 합산(총계로 검증).
  - **capex 소계-우선**: `is_subtotal`·section_path 로 소계 채택, 없으면 성분합(리뷰).
  - **K-IFRS 영업이익**·dual-section·sub-line 제외 — 이번 세션 D4 로직 **tree 기반으로 재정리·이관**.
- **출력**: 기존 `std_v2` 와이드 스키마 재사용. reconcile/build/quarterly/calendar 로직 이관.
- 애매분 = 기업별 리뷰 큐(사용자 확정 방식 계승).

## 계층 4 — App
- 기존 Streamlit 앱을 계층3 출력에 재연결. 신규 최소.

---

## 기존 작업 처리 (이관·재사용 지도)
| 기존 | 처리 |
|---|---|
| collector/downloader | 계층1 유지 |
| fin2/extract/text.py (섹션·단위·행 로직) | 계층2 추출엔진 재사용(canonical 제거) |
| fact_v2 | report_lines 로 대체(전환기 공존→퇴역) |
| concept_map·account_maps | 계층3 취합사전으로 이관 |
| std_v2·reconcile·build/rules/quarterly/calendar | 계층3 취합으로 이관(입력을 report_lines 로) |
| D4 로직(K-IFRS·금융업·capex·ε·비유동) | 계층3에서 tree 기반으로 재정리 |
| face_audit·line_audit·phase_c_integrity_check | 계층2/3 검증으로 재사용 |
| app/* | 계층4(재연결) |

## 진행 순서
1. **계층2**: `report_lines` 스키마 + 추출(엔진 재사용 + 하위섹션/순서/depth/소계 + 주석 tree).
2. **계층2 검증**: 파일럿(금융업 KG케미칼 포함) 원문 1:1 대조 통과.
3. **계층3**: 기존 취합로직 이관(입력 report_lines), 금융업 합산·capex 소계 tree 기반 구현.
4. **전량 79k → 검증(무결성 어서션) → swap → App 재연결.**

## 리스크/주의
- report_lines 는 주석 tree 포함으로 범위 큼 → **본문 statements 먼저, 주석 다음** 단계화.
- depth/소계 인식은 들여쓰기·'합계/소계' 라벨 휴리스틱 — **위치(구조) 판단이지 값 판단 아님**(원칙 유지).
- Track A(XBRL) tree = calc linkbase, Track B(text) tree = 표 순서/들여쓰기 → 두 소스 tree 모델 통일 필요.
- 이번 세션 D4/K-IFRS/capex 커밋(3aa8cd5·a09df33·2a69802·c814539·3c87e27)은 **계층3 로직으로 재사용**
  (폐기 아님). 다만 std_v2/fact_v2 파일럿 데이터는 재설계 후 재생성 대상.
