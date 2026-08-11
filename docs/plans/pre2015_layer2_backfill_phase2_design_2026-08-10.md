# Phase 2 설계 — 계층2 pre-2015 2차 패스 파서 (2026-08-10)

> 상태: **설계 완료 — 사용자 승인 대기.** [정책](../../CLAUDE.md) 상 설계 문서 작성 후 자동 구현
> 금지, 별도 실행요청 대기. 상위 계획 = [`pre2015_layer2_backfill_plan_2026-08-10.md`](pre2015_layer2_backfill_plan_2026-08-10.md)
> Phase 2. 실행 체크리스트 = [`pre2015_layer2_backfill_todo_2026-08-10.md`](pre2015_layer2_backfill_todo_2026-08-10.md).
>
> 이 문서는 todo 2-1~2-4 네 가지 결정을 담고, 2-5(이 문서 자체) 승인을 요청한다.
> **Phase 3(구현) 착수는 이 문서 승인 후 별도 요청 필요.**

---

## 0. 한 줄 요약

Phase 1이 "TITLE 계층 vs SPAN vs 앵커, 3세대 구조"로 진단했던 것과 달리, **실제 병목은 TITLE
유무가 아니라 기존 `assign_tables_to_dart_sections`/`iter_section_elements`의 "중첩 SECTION을
만나면 즉시 리셋" 규칙**이었다 — 원문·프로덕션 함수 직접 실행으로 실측 확정. 이 규칙이 K-GAAP의
"가./나./다." 한글서수 하위표제를 만나자마자 섹션 추적을 꺼버려, **1999~2008은 기존 파이프라인
무변경 실행 시 0% 성공**이었다(2011~2014는 반대로 **이미 100% 성공** — 구조가 평탄해져 기존
로직과 우연히 맞았다). 깊이인식 경계walk으로 교체한 프로토타입(프로덕션 코드 미변경, 스크립트
내)으로 재실측하니 **2004~2008 annual은 8/8(100%)**까지 회복됐다. 이 문서는 그 실측을 근거로
Phase 2 네 가지 결정(2-1~2-4)을 내리고 Phase 3 설계를 확정한다.

---

## 1. 실측 근거 (읽기 전용, 코드 무변경)

세 개의 새 프로브를 순서대로 실행했다(전부 read-only, `report_lines`/`note_lines` 미변경):

| 프로브 | 목적 | 산출물 |
|---|---|---|
| ① 기존 파이프라인 무변경 재사용률 | `fin2.extract.report_lines.extract_report_lines`(2015+ 운영 진입점)을 pre-2015 층화표본(1999~2014, 연도당 10건)에 **코드 무변경**으로 그대로 실행 | [`pre2015_existing_pipeline_reuse_probe_2026-08-10.md`](../qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md) |
| ② 근본원인 진단 | ①의 0% 구간(1999~2008) 원인을 원문 XML 트리 직접 대조로 추적 | 이 문서 §2 (별도 파일 없음, 아래 서술) |
| ③ 수정안 프로토타입 검증 | ②에서 찾은 수정안(깊이인식 경계walk + 확장 분류기)을 **스크립트 내부에서만** 구현해 1999~2010 재실측 | [`pre2015_boundary_walk_prototype_probe_2026-08-10.md`](../qa/pre2015_boundary_walk_prototype_probe_2026-08-10.md) |

### 1-1. 프로브 ① 결과 — 기존 파이프라인 그대로 돌린 성공률

| FY 구간 | BS/IS/CF 검출 | 비고 |
|---|---|---|
| 1999~2008 | **0%**(80/80 표본 0행) | 예상과 반대 — Phase 1은 이 구간을 "TITLE 100% 유지"로 가장 쉬운 구간으로 봤었음 |
| 2009 | IS/CF 20%, avg 94행 | 전환기 시작 |
| 2010 | BS 30%·IS/CF 90%, avg 509행 | 전환기 |
| **2011~2014** | **100%**(40/40) | Phase 1이 "TITLE 소멸·신규 파서 필요"로 판단했던 구간이 **이미 무변경 성공** |

### 1-2. 근본원인 (원문 XML 직접 대조로 확정)

`_detect_body_statement_tables`(`fin2/extract/text.py:213`)는 두 경로를 가진다:
1. **주경로** — `assign_tables_to_dart_sections`(`parser/xml/section_detector.py:185`)로 최상위
   `SECTION-2` TITLE이 정확히 "재무제표"/"연결재무제표"인 구간의 TABLE만 후보로 삼음.
2. **구형 레이아웃 폴백**(2026-08-04 신설) — 주경로 결과가 **완전히 비었을 때만**
   `_detect_legacy_body_statement_tables`(`fin2/extract/text.py:343`)로 전환, `SEC_LEGACY_FS`
   ="재무제표등"(병합 단일 섹션) 안을 표제 앵커로 훑음.

1999~2008 실제 문서 구조(현대모비스 20000330000228 등 정상 크기 표본 직접 대조):

```
<SECTION-2><TITLE>3. 재무제표</TITLE>                 ← 주경로가 정확히 일치(kind=재무제표)
  <SECTION-3><TITLE>가. 대차대조표</TITLE>              ← ★여기서 문제 발생
    <TABLE-GROUP>
      <TITLE ATOC="N">대 차 대 조 표</TITLE>
      <TABLE>...(기간/단위 메타)...</TABLE>
      <TABLE>...(실제 데이터, 자산총계 등)...</TABLE>
    </TABLE-GROUP>
  </SECTION-3>
  <SECTION-3><TITLE>나. 손익계산서</TITLE>...</SECTION-3>
  ...
```

`assign_tables_to_dart_sections`는 `root.iter()`로 문서 전체를 훑으며 **"SECTION으로 시작하는
태그를 만날 때마다"** `current`를 재판정한다(중첩 깊이 무관하게 매번). "가. 대차대조표"는
`_DART_SECTION_EXACT`에 없는 키라 `classify_dart_section`이 `None`을 반환 → `current = None`
으로 **즉시 리셋** → 그 안의 `TABLE-GROUP`은 **최상위 매치가 이미 성공했음에도** 후보에서
탈락한다. `_detect_legacy_body_statement_tables`가 쓰는 `iter_section_elements`(`section_detector.py:272`)
도 같은 결함을 공유한다 — "다음 SECTION 표제를 만나면 구간 종료"가 깊이를 보지 않아 "가.대차대조표"
에서 즉시 `break`한다. 게다가 이 폴백은애초에 `SEC_LEGACY_FS`="재무제표등"(**병합 단일 섹션**,
2015+ 일부 구형 문서 전용 명칭)만 찾으므로 1999~2010의 **분리형**("3.재무제표"/"4.연결재무제표")
구조에는 이름 자체가 안 맞아 발동조차 하지 않는다.

**결론**: 주경로·폴백 모두 "최상위 섹션은 정확히 찾지만, 그 안의 개별 재무제표 하위표제(가/나/다)를
만나는 순간 무너진다"는 **같은 결함**을 갖고 있다. 2011~2014가 우연히 성공한 이유는 정확히 이
결함의 반대편이다 — 그 구간은 SECTION-3 하위표제 자체가 없어졌고(TITLE 소멸), 재무제표명이
`<P>`/`<SPAN>` 평문으로 TABLE 바로 앞 형제 자리에 남아 2015+용 `title_text_owned`/
`title_text_for_classify`(형제 back-scan)가 그대로 맞아떨어졌다.

### 1-3. 프로브 ③ 결과 — 수정 프로토타입 재실측(1999~2010, 연도당 8건)

수정안: ①SECTION 깊이를 추적해 **형제-이하 레벨 표제 변경에서만** 구간을 종료(중첩
하위표제는 통과) + ②`classify_legacy_statement_heading`을 한글서수 접두("가."~"바.") 제거 +
K-GAAP 전용 표(이익잉여금처분계산서/결손금처리계산서) 포함으로 확장.

| FY | BS/IS/CF | 비고 |
|---|---|---|
| 2004~2007 | **8/8(100%)** | 목표 달성 |
| 2008 | BS/IS/CF 8/8, **APPR 1/8**만 | K-GAAP 전용 표 검출만 별도 저하 — 원인 미규명(§4 후속) |
| 1999~2003 | 25~63%, 전부0 사례 다수가 **half/quarter** | report_type별 구조 차이 의심(§1-4) |
| 2009~2010 | 낮음(0~13%) | 이 프로토타입은 K-GAAP형 전용이라 예상된 결과 — 이 구간은 **기존 2015+ 경로가 이미 담당**(§1-1) |

### 1-4. 잔여 원인 — half/quarter 보고서의 하위표제 누락

전부0 사례 중 하나(한일사료 20000810000060, 2000 half)를 직접 대조: 최상위 "3.재무제표" 구간은
정확히 잡히지만, 그 아래 하위표제 목록이 "가.재무제표작성기준" 다음 곧바로 "마.…주석"으로
건너뛴다 — "나.대차대조표"/"다.손익계산서"/"라.현금흐름표"에 해당하는 SECTION-3 자체가 **이
문서에 없다**. 즉 일부 half/quarter 제출분은 개별 재무제표를 하위표제 없이 평문/구조로만
표기하는 **네 번째 변종**이 있다 — Phase 1의 §label_pattern_probe(앵커 기반, CF 91% 적중)가
이미 실측·검증해 둔 방식이 바로 이런 사례의 방어선이다.

---

## 2. 결정 (todo 2-1~2-4)

### 2-1. `section_detector.py` 확장 방식 — **기존 함수 수정 대신 신규 모듈**

**결정: `assign_tables_to_dart_sections`/`iter_section_elements`는 건드리지 않는다.** 새
모듈(`parser/xml/section_detector_legacy2015.py` 가칭, 또는 `fin2/extract/legacy_pre2015.py`)에
아래 3개 함수를 신설한다.

- `iter_section_span_depth_aware(root, normalized_title)` — §1-3 프로토타입을 정식화. SECTION
  깊이를 `etree.iterwalk`(start/end)로 추적해 **진입 깊이와 같거나 얕은** 레벨의 표제 변경에서만
  구간을 종료한다. 중첩 SECTION-N(가/나/다 하위표제)은 통과하며 그 TITLE 텍스트도 후보로 낸다.
- `classify_pre2015_statement_heading(text, include_sce=False)` — `classify_legacy_statement_heading`
  (`fin2/extract/statement_titles.py:394`)을 **그대로 복사해 확장**(원본은 2015+ 구형 레이아웃
  폴백이 계속 쓰므로 손대지 않는다): 한글서수 접두("가."~"하.") 사전 제거 + K-GAAP 전용 표
  (이익잉여금처분계산서/결손금처리계산서 → 신규 코드 `APPR`) 인식 추가.
- `detect_pre2015_body_statement_tables(root, fin_type, include_sce)` — `_detect_legacy_body_statement_tables`
  (`fin2/extract/text.py:343`)의 pending-anchor-then-data-table 패턴을 그대로 재사용하되, 훑는
  대상을 `SEC_LEGACY_FS`(병합 섹션) 대신 **`SEC_SEP_FS`/`SEC_CONSOL_FS`(분리형 최상위 섹션,
  1999~2010의 실제 구조)** + 위 depth-aware 워커로 교체.

**왜 기존 함수를 안 건드리나**: `assign_tables_to_dart_sections`의 "정확일치 아니면 즉시 리셋"은
2015+ 문서에서 **의도된 안전장치**다(요약재무정보·주석 섹션을 본문으로 오인하지 않기 위함,
`section_detector.py:89-93` 실측 근거 — 부분일치 허용 시 '재무제표이용상의유의점' 등이 오분류됐던
전례). 이 규칙을 깊이인식으로 바꾸면 2015+ 문서에도 영향이 가 회귀 위험이 크고, 정작 2015+엔
이런 중첩 하위표제 문제가 없어 이득이 없다. **신규 함수 + 연도 라우팅**(pre-2015만 새 경로)이
안전하고, todo가 이미 제안했던 두 옵션 중 정확히 이 방향과 일치한다.

### 2-2. K-GAAP 전용 표 스코프 — **포함, 신규 코드 `APPR`**

사전결정 Q1(포함)과 일치. `report_lines.statement` 컬럼은 `varchar(10)`이고 **CHECK 제약이 없어
DB 마이그레이션 불요**(실측 확인, 현재 값 BS/IS/CF/SCE). `계층3(std_v3)/뷰 소비자는 기존에
`WHERE statement IN ('BS','IS','CF')` 식으로 걸러 쓰므로 `APPR` 신규 코드가 섞여도 자동으로
제외된다 — **가산적, 하위 호환 그대로**. 단, §1-3에서 APPR만 2008년에 급락(8→1)한 원인은
Phase 2에서 규명하지 못했다 — Phase 3 카나리아 표본에 K-GAAP 전용 표 다수 포함해 재확인 필요.

### 2-3. `table_extractor.py` 재사용 범위 — **수정 없이 전량 재사용**

- 셀 태그: `TU`(단위/날짜 셀)가 이미 `TD`/`TH`/`TE`와 동급으로 처리됨(`table_extractor.py:318,335,344`)
  — 1999년 샘플에서 관찰된 TU 셀 그대로 커버.
  ROWSPAN/COLSPAN(R11 `expand_table_grid`) 도 별도 태그 확장 없이 표준 TABLE/TR/TD 파싱 경로를
  타므로 수정 불요 — Phase 1 §5 관찰(2004~2008 표본 75%에서 ROWSPAN>1)과 일치.
- 데이터표 판정(`table_has_amount_rows`)도 프로토타입에서 그대로 재사용해 정상 동작 확인(§1-3).
- **결론: 신규 작업 없음.** Phase 3에서 회귀만 확인.

### 2-4. 단위 판정 로직 — **수정 없이 전량 재사용**

`declared_unit`(`fin2/extract/text.py:430`)은 "직전 형제 표제" 또는 "표 자신의 첫 행"에서 단위를
찾는다. §1-2에서 확인한 K-GAAP `TABLE-GROUP` 구조상 단위 선언("(단위 : 원)")은 데이터표의
**직전 형제인 메타 TABLE**에 있어 이 함수의 가정과 정확히 들어맞는다(섹션 경계 버그와 무관한
레벨이라 영향을 안 받았다). Phase 1 §4(단위 선언 표기 15건 전수, "단위 : 원"/"단위 : 천원"류)도
기존 `detect_unit_declaration` 정규식과 충돌 없음을 이미 확인. **결론: 신규 작업 없음.**

---

## 3. Phase 3로 넘기는 잔여 미해결 항목 (설계 범위 밖, 구현 중 확인 필요)

1. **1999~2003 half/quarter 잔여 저조**(§1-4) — 하위표제(가/나/다) 자체가 없는 네 번째 구조
   변종. Phase 1의 계정라벨 앵커 방식(`자산총계`/`당기순이익`/`영업활동으로 인한 현금흐름`,
   CF 91% 적중 검증됨)을 **2차 폴백**으로 `detect_pre2015_body_statement_tables`에 얹는 안을
   제안 — 정식 구현·검증은 Phase 3.
2. **2008년 APPR 급락 원인** — 8/8 BS/IS/CF는 정상인데 K-GAAP 표만 1/8. 표제 자체가 이 해부터
   달라졌을 가능성(예: "이익잉여금처분계산서" 앞에 다른 수식어) — 원문 대조 필요.
3. **2009~2010 전환기 라우팅** — 이 구간은 신규 pre-2015 경로(위주)와 기존 2015+ 경로가 둘 다
   부분적으로 맞는다. `detect_pre2015_body_statement_tables`가 빈 결과면 기존
   `_detect_body_statement_tables` 정경로로 폴백하는 **순서**를 Phase 3에서 확정(구현 시 결정,
   설계 변경 아님).
4. **1999~2003 전반의 낮은 성공률**(전부0 다수, half/quarter 외에도 일부 annual 포함) — 표본이
   작아(연도당 8건) 통계적으로 얕음. Phase 3 착수 시 카나리아 표본을 이 구간에 두텁게(연도당
   20건+) 재설계해 원인을 넓게 재확인할 것.

---

## 4. Phase 3 진입 조건 (이 문서 승인 후)

- todo 3-1: 위 3개 함수(§2-1) 신규 모듈로 구현.
- todo 3-2: Phase 1 표본(188+165+48건) + 이 문서의 신규 표본(96건) 합쳐 카나리아로 재사용,
  단위 테스트 + 원문 대조.
- **회귀 방지**: 2015+ 소비 경로(`_detect_body_statement_tables`/`assign_tables_to_dart_sections`)
  는 이 트랙에서 **한 줄도 수정하지 않는다** — pytest 전체(fin2/tests 포함) 무변경 통과가
  Phase 3 완료 조건 중 하나.

---

## 5. 산출물

- 프로브 스크립트(읽기 전용, DB/report_lines 미변경):
  - `scripts/probe_pre2015_existing_pipeline_reuse.py`
  - `scripts/probe_pre2015_boundary_walk_prototype.py`
- 결과 문서:
  - [`docs/qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md`](../qa/pre2015_existing_pipeline_reuse_probe_2026-08-10.md)
  - [`docs/qa/pre2015_boundary_walk_prototype_probe_2026-08-10.md`](../qa/pre2015_boundary_walk_prototype_probe_2026-08-10.md)
- 참고: Phase 1 산출물 3종(구조/경계/라벨패턴 프로브, `docs/qa/pre2015_*_probe_2026-08-10.md`)
