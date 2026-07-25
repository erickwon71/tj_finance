# 계획 — 계층2 주석(note) 전반 전사 (D&A·R&D·리스 등 파생계정의 소스 적재) 2026-07-25

> 상태: **계획 초안 (미실행)**. 사용자 결정(2026-07-25): **(b) 주석 표 전반 전사** + 아키텍처 준수 +
> **코드 파편화 방지**. 마스터 허브 [`rearchitecture_4layer.md`](rearchitecture_4layer.md).
> 선행/후속: 이 적재가 완료돼야 [`layer3_v3_bridge_swap_2026-07-25.md`](layer3_v3_bridge_swap_2026-07-25.md)
> 의 D&A/EBITDA enrichment 이 **아키텍처 준수로** 성립(계층3는 계층2에서만 읽는다).

---

## 0. 한 줄 요약
계층2(파서=충실전사)가 지금 **본문(BS/IS/CF/SCE)만** report_lines 에 전사하고 **주석은 미전사**다
(플래그 `include_notes=False`). 파생계정(D&A/EBITDA)·R&D·리스 등의 **원천이 주석**이라, 계층3가 이를
만들려면 계층2가 먼저 주석을 report_lines 에 담아야 한다. **주석 전사 코드(`_emit_note_lines`)는 이미
작성돼 있고 꺼져 있을 뿐** — 이 계획은 그것을 **활성화·검증·백필**하고, 흩어진 note 추출기
(`notes.py`·`rd_note.py`·`expense_nature.py`·`cf_da.py`)를 **하나의 계층2 전사 + 계층3 매핑으로 흡수**해
파편화를 없앤다.

## 1. 아키텍처 기준 (마스터 허브 §계층표)
| 계층 | 책임 | 이 계획의 위치 |
|---|---|---|
| **2 파서(충실전사)** | 원문 tree 를 판단 없이 전사(단위만 원 정규화) → report_lines | ★여기 = 주석 표 전사 활성화 |
| **3 취합(값판단)** | 매핑·합산·**파생계정**·프로파일 = report_lines 에서만 읽음 | note.* canonical 매핑 → D&A/R&D 파생 |

⇒ 원칙: **주석 "어떤 표를 담을지"는 판단 최소(전사)**, **"어느 라인이 D&A/R&D인지"는 계층3 판단.**
계층3가 보고서를 직접 읽는 일(이번에 폐기한 접근)은 없다.

## 2. 현 상태 (실측)
- report_lines statement = **BS/CF/IS/SCE 뿐**(note 0행). 볼륨 64M행.
- `fin2/extract/report_lines.py`:
  - `extract_report_lines(..., include_notes: bool = False)` — **주석 게이트(기본 off)**.
  - `_emit_note_lines()`(L473) — **이미 구현**. 연결/별도 주석 섹션(`SEC_CONSOL_NOTE`/`SEC_SEP_NOTE`)의
    표를 `statement="note"` 로 전사. 첫 슬라이스 = **단위 선언 + 금액 데이터행이 있는 주석 표만**
    (정책·서술 텍스트 주석 제외). 컬럼은 연도판단 없이 위치 그대로(`_NOTE_MAX_COLS=8`), period_kind=NULL,
    section_path=주석 제목(로케이터).
  - 공유 섹션 식별 = `parser/xml/section_detector.assign_tables_to_dart_sections`(text.py·rd_note.py·
    expense_nature.py 와 **공용**).
- **파편화 현황(없앨 대상)**: 주석을 각자 읽어 fact_v2 로 넣는 추출기들 —
  `fin2/extract/notes.py`(CF주석 D&A)·`cf_da.py`(D&A 하이브리드)·`rd_note.py`(R&D주석)·
  `expense_nature.py`(비용성격). 각기 note_extractor 를 호출하는 **중복 경로**.

## 3. 목표 산출물
1. report_lines 에 `statement='note'` 행 적재(연결/별도, 단위선언 금액 주석 표 전반).
2. 계층3 combine 이 note.* canonical 을 매핑해 **D&A/depreciation/amortization/da_total→ebitda**,
   **R&D(note.rd_expense)** 등을 파생(기존 `rule_additive_da`·`rule_rd_fallback` 재사용).
3. 흩어진 note 추출기 흡수 → **단일 소스(계층2 전사)**.

## 4. 리스크 ①: 볼륨 (★최대 관건)
- 주석은 **표 수의 96%**. 본문 64M행 기준, 주석 전사 시 report_lines 가 수억 행으로 팽창 가능.
- 프로젝트 제약: "DB 커져도 query 속도 일정"(CLAUDE.md). → **볼륨을 먼저 실측**하고 설계에 반영.
- 완화 레버(계획에서 결정):
  - (a) **금액 주석 표만**(첫 슬라이스 이미 그렇게 스코프 — 정책/서술 텍스트 배제).
  - (b) **계층3 소비 대상 주석만 화이트리스트**(감가상각·유형/무형자산·리스·R&D·비용성격·부문/매출
       분해 등)로 1차 한정 → 이후 확대. "전반"이되 **금액표 중심·단계 확대**.
  - (c) 인덱스/파티셔닝 전략(note 행은 조회 패턴이 본문과 다름 — corp+rcept+section_path 로 바운드).
- **선결 태스크 = 표본 N개 filing 로 note 행수 실측**(전수 백필 전 규모 확정).

## 5. 리스크 ②: 계층3 매핑 커버리지
- note 라벨 → canonical 매핑(`get_mapper()`)이 D&A/R&D 등 대상 note 라인을 인식해야 함.
  - 기존 note.* canonical: `note.depreciation`·`note.amortization`·`note.da_total`·`note.rou_depreciation`
    ·`note.rd_expense`. 매핑 확장이 필요한 note 계정 식별(리스·부문매출 등은 후속).
- combine 은 이미 CONSUMED_CANON(note.* 포함)을 resolve → `rule_additive_da`·`rule_rd_fallback` 로 흐름.
  **주석이 report_lines 에 들어오면 계층3는 추가 개발 거의 없이 파생**(steps 1-2 에서 깐 rule 재사용 기반).
- ⚠ 중복합산 가드: 본문(cf./is.) D&A 가 있는데 주석 D&A 도 매핑되면 이중계상 → `rule_additive_da`
  기존 가드(da_total 직접공시 우선·본문 폴백) 로직 확인·이식.

## 6. 파편화 방지 (사용자 지침 핵심)
- **단일 경로**: 계층2 `_emit_note_lines`(전사) → 계층3 combine(매핑·파생). note 를 읽는 곳은 계층2 하나.
- 기존 추출기 처리:
  - v3 경로에서는 `notes.py`/`cf_da.py`/`rd_note.py` **미사용**(계층2 전사로 대체). 삭제는 v2 폐기 시.
  - 단, 이들이 쓰는 **검증된 저수준 파서**(`parser/xml/note_extractor.py`)는 `_emit_note_lines` 가
    이미 같은 `section_detector`/`extract_rows` 계열을 쓰는지 확인 → **공용 저수준으로 수렴**(중복 파싱 금지).
- ⇒ "note 읽기 로직"이 계층2 한 곳에만 존재하도록 수렴시키는 것이 이 작업의 성공 기준.

## 7. 구현 순서 (제안)
1. **볼륨 실측**: 표본 filing(대·중·소 재무구조 각 N)로 `include_notes=True` 추출 → note 행수·표수 집계.
   → 스코프 확정(§4 (a)/(b) 레버).
2. **`_emit_note_lines` 검증·보강**: 첫 슬라이스 커버리지 점검(누락 주석 표·단위 미선언 처리·중복). 필요 시
   화이트리스트/가드 추가. **충실전사 원칙 유지**(값 판단 금지).
3. **파이프라인 배선**(runbook `docs/runbook_new_parser_pipeline_integration.md`, **두 call site**):
   collect_new 의 report_lines 추출 호출에 `include_notes=True`. 데일리 신규분부터 주석 포함.
4. **소급 백필**: 전 filing 재추출(주석 포함) — 볼륨 큼 → 사용자 실행(장시간). idempotent 확인.
5. **계층3 매핑 검증**: combine 이 note D&A/R&D 를 파생하는지 표본 대조(원문). 중복합산 가드 확인.
6. **계층3 재빌드**(`build_std_v3 --all`) → D&A/ebitda/rd_expense 채움율 확인(v2 대비·원문 대비).
7. **→ 브리지 swap 재개**(별도 계획): 이제 D&A enrichment 이 계층2→계층3로 성립. shares_out 은 §8.

## 8. shares_out (별도 판단 — 주석 아님)
- 발행주식수는 재무제표 주석이 아니라 **일반현황(주식의 총수)** 섹션. 주석 전사와 소스가 다름.
- 선택지(swap 계획과 함께 결정): (a) 계층2가 일반현황도 전사(report_lines 확장) vs (b) **별도 shares
  테이블**(주가처럼 cross-cutting, 계층2 추출 → 뷰 조인). **(b) 권장** — 재무제표 tree 와 성격이 달라
  report_lines 오염 방지. 이 계획 범위 밖, 브리지-swap 계획에서 확정.

## 9. 완료기준 (DoD)
1. report_lines 에 note 행 적재(연결/별도, 단위선언 금액 주석), 볼륨이 실측·수용 범위.
2. 계층3가 note 소스로 D&A/da_total/ebitda(+R&D) 파생, 표본 원문 대조 일치.
3. note 읽기 로직이 계층2 한 곳으로 수렴(파편 추출기 v3 경로 미사용).
4. 파이프라인 두 call site 배선 + 백필 idempotent.

## 10. 다음 액션 (이 문서 검토 후, 별도 실행요청 대기)
- 검토 포인트: ① 볼륨 스코프(§4 전반 vs 금액표중심·화이트리스트 단계) ② 파편화 수렴 대상(§6) ③ shares 위치(§8).
- 승인 시 착수 = §7-1(볼륨 실측)부터. 실측 결과로 스코프 확정 후 §7-2~.
