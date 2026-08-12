# TODO — 계층2 PDF-only 3차 패스 실행 체크리스트 (2026-08-11)

> 설계 = [`pdf_only_parser_plan_2026-08-11.md`](pdf_only_parser_plan_2026-08-11.md)
> (설계 완료, §6 사전 결정 5건 전부 확정). 마스터 허브 = [rearchitecture_4layer.md](rearchitecture_4layer.md).
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. **이 문서는 계획일 뿐 — 실행은 별도 승인 후 착수**
> (결정 확정 자체가 실행 지시는 아님). [파서/로더 파이프라인 편입 절차](../runbook_new_parser_pipeline_integration.md)를 Phase 6에 그대로 적용.

---

## 사전 결정 사항 — 전부 확정(2026-08-11, 계획서 §6)
- ☑ Q1. 계층2 tree 표현 방법 — "PDF는 구조 없음" 단정 안 함. Phase 1-6에서 들여쓰기 보존
  실측 후, **보존되는 세대는 XML과 동일 방식(depth/node_role 유지)**, 안 되는 세대만 NULL
- ☑ Q2. 이미지 스캔 PDF(OCR) 처리 방침 — **OCR로 최신 방식(구조화된 tree)과 동등한 결과를
  낼 수 있으면 포함**(2026-08-11 범위 확장, "OCR은 범위 밖" 초안 철회). Phase 1-8에서
  정확도(금액 숫자 오인식률 최우선)·구조복원가능성·비용 실측 후 채택/skip 최종 결정
- ☑ Q3. 정정(is_final=False) 필링 297건(2015+) 스코프 — **정정 계보까지 포함**
- ☑ Q4. 기존 legacy PDF 코드(`parser/pdf/*`, `fin2/extract/pdf.py`) 처리 — 프로덕션 호출자
  0개 확인됨 → 재사용 로직만 흡수 후 Phase 3 완료 시점에 원본 삭제(아래 3-5)
- ☑ Q5. 승인 단위 — **Phase 1만 먼저 실행, 결과 보고 후 Phase 2 재승인 요청**(pre-2015
  트랙과 동일 패턴)

---

## Phase 1 — 구조 정밀 실측 (읽기 전용) — ☑ 완료 (2026-08-11)
- ☑ 1-1. 층화 표본 설계(271건, fiscal_year×report_type) — `scripts/probe_pdf_only_structure.py`
- ☑ 1-2. **2015-2019 몰림 원인 조사 — ★확정(원인) + 정정(적재율)**: 다운로더가
  `_try_xbrl_instance_fallback()`(ifrs.do) 신설(2026-08-06) 이전에 다운로드된 필링이라
  재시도된 적이 없었을 뿐 — "DART가 원래 PDF만 줬다"는 오판이었음을 확인(원인 진단은
  확정, 표본으로 충분). 단, 최초 실측(40건, **XBRL 원문 zip 다운로드 82.5% 성공**)을
  "82.5% 회수 가능"으로 해석한 건 성급했다 — 50건 파일럿(사용자 실행) 후속조사에서 다운로드
  성공 44건 전부 report_lines **0행**으로 나와 조사한 결과, `report_lines_xbrl.py`가
  `instance.nsmap.get("ifrs-full")` 접두사만 인식하는데 **2015~2019년 필링은 구형 taxonomy
  (`ifrs` 접두사, 2010-04-30판)**를 써서 조용히 스킵됨을 확인(원문 zip 직접 열어 확인).
  확장표본(30건, 2015~2020년)에서 **2015~2019년 27건 전부 0행, 2020년 1~2월 3건만 정상
  적재(339~480행)** — 실제 정상 작동 경계는 2019년말 무렵. pre-2015는 0% 그대로 진짜
  PDF-only 확정. 회수 스크립트 `scripts/backfill_pdf_only_2015plus_xbrl_recovery.py`
  신설(year_min 버그 수정 완료) — **사용자가 전체 2,104건 다운로드 백그라운드 실행 중**,
  완료 후 정확한 3분할(진짜 PDF-only/taxonomy 문제로 미적재/정상 적재) 확정 예정.
  결과 = `docs/qa/pdf_only_xbrl_recoverable_probe_2026-08-11.md` +
  `docs/qa/pdf_only_xbrl_extraction_rate_probe_2026-08-11.md`(★신규, 정정 근거)
- ☑ 1-3. 텍스트 레이어 전수(3,509건) 스캔 — **이미지 스캔 PDF 0건(100% 텍스트기반)**.
  결과 = `docs/qa/pdf_only_text_layer_probe_2026-08-11.md`
- ☑ 1-4. face 섹션 앵커 패턴 실측 — BS 라벨 확인 57.6%(156/271), 실패 42.4% 카탈로그화됨
  (특히 pre-2015 1999~2002 anchor=0 다수) — Phase 2에서 원인 재확인 필요
- ☑ 1-5. 표/숫자 표기 실측 — 괄호 음수가 전 era 압도적 다수, `parse_number()` 재사용 가능
- ☑ 1-6. **들여쓰기/구조 보존 실측(Q1) — ★확정**: probe 성공 164건 중 163건(99.4%)에서
  x0 좌표 클러스터 2개 이상 확인 — 거의 전 세대에서 들여쓰기 보존. XML과 동일 방식
  (depth/node_role) 재사용 가능으로 결론, "전부 NULL" 우려 기각
- ☑ 1-7. 대체 구조 신호 조사 — 폰트굵기(fontname 매칭)는 기각(DART 임베드 폰트가 굵기
  정보 없는 서브셋명), 번호매김은 보조신호로만 유효, bbox padding/줄간격은 1-6 결론에 따라
  우선순위 낮춤(들여쓰기가 이미 주신호로 충분)
- ☑ 1-8. **이미지 스캔 PDF OCR 조사 — 불필요로 종결**: 1-3에서 이미지 스캔 PDF 0건 확인,
  OCR 인프라(tesseract) 설치·조사 자체가 불필요
- ☑ 1-9. 정정 PDF 쌍 비율 실측 — `superseded_by` 죽은 컬럼(전체 0% 채워짐) 발견,
  `amended_by`는 XML 파이프라인에도 없는 신규 스키마 개념으로 확정. is_final=False 506건 중
  306건(60%)이 진짜 PDF 정정쌍. 3분류 실측 시 PARTIAL_COVER 0건 관측(임계값 재검토 필요).
  결과 = `docs/qa/pdf_only_amendments_probe_2026-08-11.md`
- ☑ 1-10. 산출물 = `docs/qa/pdf_only_structure_probe_2026-08-11.md`(§6에 전체 종합 결론 +
  4개 보조 문서 링크)
- **게이트 통과**: 사용자 보고 완료. Phase 2 착수는 별도 승인 필요(미승인 상태). §1-2가
  하루 안에 한 번 정정되고(§6-0), 2026-08-12 전량 다운로드 완료로 **전수 확정**됨:
  ①진짜 PDF-only **465건**(22.1%, 새 파서 확정 대상) ②XBRL은 있으나 taxonomy 접두사 문제로
  미적재 **1,548건**(73.6%) ③정상 적재 **86건**(4.1%). 새 PDF파서 확정 최소 모집단 =
  pre-2015 1,405 + ①465 = **1,870건**(기존 3,509건 추정 대비 47%). **사용자 결정
  (2026-08-12): ②(1,548건)는 (a)옵션(`report_lines_xbrl.py` taxonomy 확장) 조사부터
  진행 — 다음 세션 착수 항목, §6-7 참고.**
  - ◐ **(a)옵션 읽기전용 조사 완료(2026-08-12, 같은 날 후속)**: 축 개념 자체는
    48/48 표본에서 확인(참). 단, 진짜 원인은 가정한 1개(`ifrs-full` 하드코딩)가 아니라
    **2개**(★신규 발견: `role_map.py` 외부 taxonomy BFS 예산 소진/순서 문제도 독립 필요
    조건) — 두 버그를 함께 우회한 36건 e2e 표본은 **100% 성공**. 상세 =
    [`pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md`](../qa/pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md).
  - ☑ **후속이슈 A/B/C 60건 표본 정량화 + 근본원인 추적 완료(2026-08-12, 같은 날
    재요청)**: A(라벨 미해석) 24.6%지만 vintage 편중(`2013-03-31`=90%대, `2017-10-01`+
    =0%) — 원인=외부 label linkbase 파일 자체의 구조적 한계(개념 18개만 확보). B(중복
    행처럼 보인 것) 32.9%지만 재확인 결과 대부분 **버그 아님**(같은 개념이 필러
    프레젠테이션에 실제로 두 자리 등장, row_order/depth/section_path 전부 다름) — 저장
    정책 결정 사안으로 재분류. C(자산총계 등 최상위 합계 행 부재) — **가장 심각**, 97%
    (Assets)/96%(Liabilities)/89%(Equity)에서 fact는 존재하나 행 미생성, 원인=해당
    vintage 필러의 `_pre.xml`이 합계 개념을 트리 노드로 아예 안 실음(구조적 결손,
    fact-레벨 보조규칙으로 Phase 2에서 해소 권고).
  - ☑ **Phase 2 설계 문서로 편입 완료(2026-08-12, 사용자 결정)**: "②(1,548건) 트랙 절로
    편입 vs 별도 트랙 분리" 중 **편입**으로 확정 — 단 ①+pre-2015(1,870건) 새 PDF파서와는
    기술적으로 완전히 다른 작업이라 같은 계획 문서 안에서도 절을 분리했다. 상세 설계 =
    [`pdf_only_parser_phase2_design_2026-08-12.md`](pdf_only_parser_phase2_design_2026-08-12.md)
    §A(②트랙 — 버그①·②·후속C 수정설계+후속A 부분수정설계+후속B는 기존 아키텍처로 이미
    해소 확인, 구현착수전 확인필요 5항목). §B(①+pre-2015 새 PDF파서, 이 todo의 2-1~2-6)는
    **여전히 미착수** — 별도 세션 필요.
  - ☑ **§A 구현·백필 완료(2026-08-12, 같은 날 승인 후 진행)**: A-8 확인 4항목(읽기전용)
    → A-3~A-7 코드 수정(`fin2/extract/report_lines_xbrl.py`·`parser/xbrl_instance/
    {role_map,external_taxonomy,taxonomy_linkbase}.py`) → 회귀 확인(기존 정상분 0
    mismatch) → 백필(744개사·1,603건·317,947행·오류0) → BS 항등식 전수검사(99.64%) →
    `docs/PARSING_RULES.md` R14 신설. 카테고리② 1,551→31건(98.0% 해소), 잔여 31건
    전부 이 트랙 범위 밖 원인(K-GAAP 시대/DART 서버 404/메타데이터 불일치/USD/
    period_end_date 전사 갭)으로 원문 확인 완료. **Gate B 무영향 확인 + std_v3
    전량재빌드는 사용자가 별도 세션(controlling_ni 트랙)에서 진행 중이라 제외** —
    그 세션 정리 후 이어서 진행 예정. 상세 = R14(`docs/PARSING_RULES.md`) ·
    `pdf_only_parser_phase2_design_2026-08-12.md` §A "다음 액션".

## Phase 2 — 파서 설계 — ☐ todo (Phase 1 완료 후, §B만 해당 — §A는 위에서 완료)
- ☐ 2-1. tree 표현 방법 확정(Q1 실측 결과 반영 — 보존 세대는 depth/node_role 유지, 나머지
  NULL)
- ☐ 2-2. 앵커 탐지 알고리즘 확정(`fin2/extract/pdf.py` 로직 → 계층2 전사 함수로 재작성,
  표준계정 매핑 호출 제거)
- ☐ 2-3. 정정 처리 재구현(`pdf_amendment_handler.py` 3분류 → 계층2 출력 `amended_by` 계보,
  Q3에 따라 처음부터 포함)
- ☐ 2-4. 이미지 스캔 PDF 처리 방침 확정(1-8 OCR 조사 결과 반영 — 채택 시 OCR 추출 경로
  설계+신규 의존성 설치 안내, 미채택 시 skip 정책·기록 위치만 확정)
- ☐ 2-5. 단위(배수) 판정 — `units.py` `unit_source` enum 정합성 확인
- ☐ 2-6. 설계 문서 작성 = `pdf_only_parser_phase2_design_2026-08-XX.md`
- **게이트**: 사용자 승인 없이 Phase 3(구현) 착수 금지.

## Phase 3 — 구현 + 단위 테스트 — ☐ todo (Phase 2 승인 후)
- ☐ 3-1. 신규 모듈 구현(위치는 Phase 2 확정) — 기존 XML 경로(1차·2차) 무변경, 가산 전용
- ☐ 3-2. 회귀 테스트(`fin2/tests/test_pdf_layer2.py`) — `test_pdf.py` 픽스처 확장 재사용
- ☐ 3-3. Phase 1 표본(150~200건) 직접 호출 실측(읽기전용, DB 미기록) — 실패율·skip율 확정
- ☐ 3-4. `pytest tests/ fin2/tests/` 전체 통과 확인
- ☐ 3-5. **legacy 코드 정리**(Q4 방침 실행) — `parser/pdf/*`·`fin2/extract/pdf.py`에서
  재사용한 로직을 신규 모듈로 흡수 완료 후, 두 세대 원본 파일 삭제(`run.py::_parse_single_pdf`
  등 참조 지점도 함께 제거) + `fin2/tests/test_pdf.py` 등 관련 테스트도 신규 테스트로 대체/삭제

## Phase 4 — 파일럿 백필 + 검증 — ☐ todo (Phase 3 완료 후)
- ☐ 4-1. 표본 회사 파일럿 적재(pre-2015/2015-2019/2020+ 세 구간 고르게)
- ☐ 4-2. BS 항등식 검사 — 위반 표본은 원문 직접 대조로 원인 규명
- ☐ 4-3. 발견사항 보고 후 사용자 판단 대기(전량 백필 승인 요청)

## Phase 5 — 전량 백필 — ☐ todo (Phase 4 승인 후)
- ☐ 5-1. 로더 옵션 추가(샤딩·재개·원자커밋, `load_report_lines.py` 패턴 재사용)
- ☐ 5-2. 3,509건 전량 실행 — 오류율·skip율(OCR 미채택 시 이미지 스캔분 포함) 집계
- ☐ 5-3. 전수 검증(BS 항등식 + 표본 원문 대조 확대)

## Phase 6 — 데일리 파이프라인 배선 (필수, [런북](../runbook_new_parser_pipeline_integration.md)) — ☐ todo
- ☐ 6-1. `collect_new.py` 표준화(④) 단계가 PDF-only 신규 필링을 놓치고 있는지 확인
- ☐ 6-2. **★두 call site 모두**(메인 경로 + `--standardize-only` 재개 경로) 배선
- ☐ 6-3. 향후 신규 PDF-only 필링 자동 적재 확인(다음 데일리 실행 로그 확인)

## Phase 7 — std_v3 반영 + 문서화 — ☐ todo
- ☐ 7-1. `build_std_v3.py` 전량재빌드로 PDF 유래 report_lines 반영
- ☐ 7-2. `standard_financials` 뷰 std_v2 UNION 폴백 대상 축소 확인(뷰 자체 수정 불요 예상)
- ☐ 7-3. `docs/PARSING_RULES.md` 신규 규칙(R14 예상) 등재, `rearchitecture_4layer.md` §2·§5 갱신,
  이 계획 문서·todo 문서 상태 갱신
- ☐ 7-4. 커밋 + main 머지 + push

---

## 참고 — 실측 수치 스냅샷 (2026-08-11, 계획서 §2 발췌)
- PDF-only 합계 3,509건(pre-2015 1,405 + 2015+ 2,104), 1,417개사(합집합)
- report_lines/fact_v2 기존 적재 0건 — 완전 미착수
- 전 회사(1,417/1,417)가 다른 기간엔 XML 보유 — "PDF 전용 회사"가 아니라 "산발적 기간 결손"
- 2015+ 중 2015~2019 다섯 해가 83%(1,745/2,104) — 원인 미규명(Phase 1 최우선)
