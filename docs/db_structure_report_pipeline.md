# 보고서 적재 DB 구조

작성: 2026-07-21. 4계층 재설계(`docs/plans/rearchitecture_4layer_2026-07-19.md`) 검토 세션에서
사용자 질의에 답하며 코드/DB 실측으로 정리. 계층2 검증 이후 커밋 전 구조 확인 목적.

## 전체 그림

```
collector(계층1: 다운로드만)
        │  corporations / filings / download_tasks
        │
        ├── fact_v2 ──────────► statement_source ──► std_financials_v2/calendar ──► 앱 (현재 라이브)
        │   (E-layer, 구)         (R-layer)              (S-layer)
        │
        └── report_lines (신규, 계층2 — 엔진 완성·검증됨, 전량 미적재)
                    │
                    └── (계층3, 미착수) ──► std_financials_v2 v2 ──► swap ──► 앱
```

`fact_v2`와 `report_lines`는 같은 원본 파일을 각자 독립적으로 추출하는 **병행 상태**다. 아래
흐름 중 `report_lines`를 읽는 하류는 아직 없다 — 앱은 지금도 전부 `fact_v2 → statement_source
→ std_v2` 체인으로 돌아간다.

---

## 1. Collector 계층 — **다운로드만 한다** (판단 없음)

4계층 재설계 원칙의 첫 계층: "다운로더가 다운로드만 하듯"이 실제로 이 계층의 동작이다.
DART가 준 제출본을 **판단 없이 전부 기록**하고 파일을 받아둘 뿐, 어느 게 정본인지·값이
맞는지는 여기서 결정하지 않는다.

### `corporations` — 기업 유니버스

corp_code, stock_code, corp_name, market, is_active, coverage_class. `sync-corps`가 관리.
외국기업 필터(`_is_foreign_stock`, stock_code가 '9'로 시작하면 제외)가 이 동기화 시점에 적용된다.

### `filings` — 제출본 메타데이터 (원본·정정 전부 별도 행)

DART가 준 **모든 제출본**(원본 + 기재정정 + 첨부정정)을 rcept_no별로 **각자 별개 행**으로
저장한다. 덮어쓰지도, 병합하지도 않는다.

주요 컬럼:
- `rcept_no` (PK) · `corp_code` · `report_type`(annual/half/quarter) · `fiscal_year` · `fiscal_period`
- `is_amendment` — report_nm에 `[기재정정]` 포함 → **본문 정정**(재무 수치가 바뀔 수 있음)
- `is_attachment_amendment` — report_nm에 `[첨부정정]` 포함 → **첨부만 정정**(본문 동일)
  (실측: 두 플래그는 상호배타. `[기재정정]` 22,889건 / `[첨부정정]` 1,141건 / 무정정 164,160건)
- `is_final` — 같은 (corp_code, report_type, period_end_date)(없으면 fy+fp 폴백) 그룹에서
  **rcept_no가 가장 큰(=가장 늦게 접수된) 행 1개만 True**. `relabel_corp_filings()`가 재계산.
  rcept_no는 날짜+일련번호라 숫자가 클수록 최신 → 재정정이 또 나오면 is_final이 그쪽으로 이동
  (실측: 2차 정정이 있었던 2017.12 사업보고서의 1차 정정본이 is_final=False로 확인됨).
- `superseded_by` — **사문화(정의만 있고 미사용)**. DB 188,190행 전부 NULL. 이 컬럼을 채우던
  로직(`_manage_superseded`/`run.py recalc-superseded`)은 fin2 이전 `financial_facts` 테이블
  대상인데 그 테이블은 P5 컷오버로 이미 DROP됨(`\dt financial_facts` → 관계 없음). 즉 지금
  이 명령을 돌려도 죽은 코드 — **정본 판단은 이 컬럼이 아니라 하류(R-layer/계층3)에서 한다.**

### `download_tasks` — 실제 파일 다운로드 상태

rcept_no별 1행: file_path, file_type(xml/pdf), status(pending/downloading/completed/failed/skipped).
`report_lines`/`fact_v2` 추출은 여기서 file_path를 읽어 원본을 연다.

**다운로드 대상 선정(원본도 남긴다)** — 다음 둘 다에 대해 생성:
1. `is_final=TRUE`인 행
2. **그 그룹에 `is_amendment=TRUE`(본문정정)가 하나라도 있으면, 그 그룹 전체**
   (최종본이 아닌 원본도 포함)

즉 **본문정정이 있었던 기간은 원본과 정정본 파일이 둘 다 디스크에 남는다** — 정정 전후 값을
나중에 비교/재구성할 수 있게 하려는 설계다. 첨부정정만 있는 그룹은 이 "전부 보존" 규칙이
적용되지 않고 is_final 1개만 받는다(첨부정정은 재무 본문이 안 바뀌므로).

**⟹ 요약**: collector는 "무엇이 제출됐고 무엇을 받았는지"만 기록한다. 원본/정정 중 어느 것이
그 기간의 정답인지는 이 계층에서 결정하지 않는다 — 플래그(is_amendment/is_final)만 남기고
판단은 전부 하류로 넘긴다.

---

## 2. E-layer (추출) — `fact_v2`(구) vs `report_lines`(신규, 계층2)

같은 `download_tasks.file_path`를 읽되 접근 방식이 다르다.

### `fact_v2` — 기존 파이프라인, 현재 앱이 쓰는 테이블

평면 fact 테이블. 각 행 = (acode, acontext) 셀 하나, **`canonical_account`가 추출 시점에
이미 확정**(`concept_map`/`account_mapper`). "판단이 파서에 섞이는" 문제가 있던 테이블 —
KG케미칼 금융업 이중섹션 충돌(현금이 유동자산+금융업자산 두 곳에 있는데 canonical 하나로
합쳐지며 한쪽이 소실)이 여기서 터졌고, 그게 4계층 재설계의 시작이었다.

### `report_lines` — 신규, 계층2 (이번 세션 구축)

같은 원본 파일이지만 **canonical 매핑을 전혀 하지 않는다** — 원문 그대로 충실전사만:
`label_raw`(원문 계정명, 정규화 안 함) · `section_path`(들여쓰기 기반 tree 경로) · `row_order` ·
`depth` · `is_subtotal` · `value_won` · `adecimal` · `statement`(BS/IS/CF/note).
canonical 부여·금융업 합산·capex 소계 판단은 전부 계층3으로 미룬다.

- **현황**: 엔진 완성, 검증 완료(본문 실질금액 1:1 대조 FY 398/400 등). **전량 미적재**
  (지금은 파일럿/검증 실행분만 DB에 있다가 정리됨 — `run.py extract-lines`는 아직 기업 단위
  수동 실행, 데일리 파이프라인 미배선).
- **적재 계획(4패스, 확정)**: 1차 2015+ 원본(93,801, Track A+B 동시) → 2차 pre-2015 원본
  (70,374, 신규 파서 필요) → 3차 PDF-only(3,575, 신규 파서 필요) → 4차 정정 처리 +
  **기간당 원문 1개 선택**. 4패스 전부 끝나야 계층3 착수(사용자 확정).
- **4차의 의미**: collector가 원본을 안 지우고 남겨둔 설계(위 §1) 덕분에, 정정이 있었던
  기간도 원본 파일이 디스크에 그대로 있어 4차에서 원본↔정정 비교 후 정본을 확정할 수 있다.
  이 "정본 선택"(옛 R-layer 역할)을 계층3이 아니라 **계층2 안으로 이관**했다 — 계층3은
  항상 기간당 이미 정리된 1개의 report_lines만 보게 하기 위함.

---

## 3. R-layer (원문 선택, 현재 fact_v2 전용) — `statement_source`

(corp, fiscal_year, fiscal_period, basis, statement)별로, 그 기간을 대표할 단일 rcept_no를
여러 제출본(원본+정정) 중에서 고른다. `fact_v2`의 "어느 보고서가 정본인가" 문제를 실제로
푸는 곳 — collector의 `is_final`/`superseded_by`는 힌트일 뿐, 실질적 정본 결정은 여기서 한다.

계층2/3 체계에서는 이 역할이 report_lines 4차로 옮겨간다(§2 참고).

---

## 4. S-layer (표준화) — 앱이 소비하는 테이블

- **`std_financials_v2`**: 와이드 표준화 테이블(기업/기간/basis별 1행, canonical 계정이 컬럼) —
  `build`/`reconcile`/`rules` 산출물.
- **`std_financials_calendar`**: 같은 데이터를 달력 분기/연도로 재배치(결산월 상이 기업 처리).
- **`standard_financials`, `standard_financials_verified`, `calendar_financials`**: 위 테이블
  위의 **VIEW**(앱/레거시 소비용, 자체 데이터 없음 — 기저 테이블 변경이 자동 반영됨).

---

## 참고

- 계층2 재설계 배경·용어(원문 정의·검증 방법론)는 `docs/plans/rearchitecture_4layer_2026-07-19.md`
  및 진행 체크리스트 `docs/plans/rearchitecture_4layer_2026-07-19_checklist.md` 참고.
- 4계층 원칙: 각 계층은 자기 책임만 진다(다운로더=다운로드, 파서=전사, 취합=판단, 앱=시각화) —
  이 문서의 §1(collector=다운로드만)이 그 원칙이 실제 코드에서 어떻게 구현됐는지의 실측 확인이다.
