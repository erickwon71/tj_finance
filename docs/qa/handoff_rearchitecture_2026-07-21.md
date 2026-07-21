# 핸드오프 — 계층2 엔진 완료 + 검증 완료 (새 세션 시작점, 2026-07-21)

> **이 문서부터 읽을 것.** 계획 = `docs/plans/rearchitecture_4layer_2026-07-19.md` ·
> 진행 체크리스트 = `docs/plans/rearchitecture_4layer_2026-07-19_checklist.md` ·
> DB 구조 = `docs/db_structure_report_pipeline.md` · 관련 메모리 = [[rebuild-phase-a3-done]] ·
> 이전 핸드오프 = `docs/qa/handoff_rearchitecture_2026-07-19.md`(보존)

---

## 0. 한 줄 요약

**계층2(report_lines) 엔진 완성 + 검증 완료.** 본문 실질금액 1:1 대조 FY 398/400(EPS 포함) ·
section_path well-formedness 300/300 · 금융업 이중섹션 CF정합 100%. **다음 = 계층2 전량 적재
4패스(1차 2015+원본 → 2차 pre-2015 → 3차 PDF-only → 4차 정정+원문1개선택), 그게 다 끝나야
계층3 착수**(사용자 확정). 이번 세션 커밋 3개, 작업트리 clean.

## 1. 이번 세션 커밋 (최신순)

- `b16bc0d` docs: 계층2 진행 체크리스트 + DB 구조 문서 + 적재순서 재확정
- `f3a746b` fix(collector): 국내상장 외국기업 유니버스에서 제외 (sync 필터 + 기존분 삭제)
- `efc66f3` feat(fin2): 계층2 report_lines — 원문 tree 충실전사 엔진 (4계층 재설계)

## 2. 계층2 완료 내역

### 2A/2B (스키마·추출엔진)
- `collector/models.py:ReportLine` — canonical_account 없음, rcept 단위 delete-then-insert
- `fin2/extract/report_lines.py:extract_report_lines()` — text.py 엔진 재사용, canonical 매핑
  호출 제거, `label_raw` 정규화 안 함(원문 그대로)

### 2C (신규 tree 로직 — 전부 완료)
- **section_path**: 원문 XML의 계층은 **선행 전각공백(U+3000)**로 인코딩됨(`_get_cells`가
  strip해서 죽어있던 신호를 `raw_indent`로 복원). 순수 indent-stack으로 tree 경로 생성
  (자산/부채/자본 하드코딩 없음 — 원문 자체 top 행이 조상이 됨). **금융업 이중섹션 구분 성공**
  (KG케미칼·리드코프 현금 유동+금융업 합 = CF기말현금 정확 일치).
- **주석 슬라이스1**: `_emit_note_lines` — 단위선언+금액행 있는 화폐 표만. 컬럼=위치(연도
  아님), context_fiscal_year=NULL. `--notes` CLI 플래그.
- **Track A/B 통일**: 설계상 이미 통일(source-format 분기 없음, 가시 표+들여쓰기로 양쪽 처리).
  실측 Track A 보고서(다원넥스뷰)에서 권위값과 정확 일치 확인.

### 슬라이스2 (이번 세션 후속 요청으로 완료)
- **보험/증권 다열 포맷**: `_detect_period_layout` — 헤더 제N기 수 vs 데이터행 금액셀 수로
  기간당 다열(명세/소계) 감지 → 비어있지 않은 금액 압축 매핑. 밑줄장식(`====`) 제거
  (`_TRAIL_DECOR_RE`, amount_normalizer.py+table_extractor.py). 삼성생명 89.7%→100%.
- **EPS per-row 단위 override**: `_emit_eps_lines` — 주당손익 행을 표 단위 무시하고 인라인
  단위(원/주)로 직접 전사. `_NUMBER_PATTERN` 소수 허용(6,130.0 등).
- **`extract_rows(skip_junk=False)`**: ★검증이 발견한 실버그 수정 — `_JUNK_ACCOUNT_NAMES`
  (fact_v2 집계용 블록리스트)를 report_lines가 상속해 지분법자본변동·미처분이익잉여금·
  대손충당금 등 원문 face 라인을 드롭하고 있었음. report_lines만 스킵 해제.

### 검증 도구 + 결과
- `fin2/audit/report_line_audit.py` — 독립 리더(report_lines 추출과 다른 경로로 원문 표를
  평면 스캔) + 실질금액(|v|≥1000) 집합 대조. "원문" 정의 = 원본 XML face 표 표시값.
- `scripts/verify_report_lines.py` — `--corp`/`--rcept`/`--sample`/`--period`(fy|all)
- `scripts/verify_section_paths.py` — well-formedness + 금융업 이중섹션 CF정합
- **결과**: 카나리아 3사(KG케미칼·큐로셀·리드코프) FY 100% · 광역 랜덤 FY 398/400(99.5%,
  EPS 포함) · all-period 400/400 · section_path 300/300 · 이중섹션 CF정합 100%.
- **잔여 롱테일(미추적, 문서화만)**: 증권 '대손준비금 반영후 조정이익' 다행 라벨 · 주당
  '보통주/기타보통주' 원-suffix 세부(주당 키워드 없음) · 주석 EXTRA 소수(실측상 날조 아님,
  독립 주석리더 커버갭).

## 3. 부수 작업 — 국내상장 외국기업 유니버스 제외

계층2 검증 중 로스웰(중국계) 정합률이 73%로 낮아 조사 → 국내 상장 외국기업은 서식이
이질적이고 관심 대상도 아님(사용자 결정) → **완전 제외**.
- 식별: `stock_code`가 '9'로 시작(900xxx·950xxx, 실측 전건 외국기업, 21개사).
- `collector/corp_collector.py:_is_foreign_stock()` — sync_corporations 필터에 적용(재유입 차단).
- `scripts/purge_foreign_corps.py --apply` 실행 완료 — DB 종속데이터(fact_v2 297,646 등) +
  원문 파일 951개(21개 기업폴더) 하드 삭제. active 2554→**2533**, orphan 0 확인.
- 관련 메모리: [[foreign-corps-excluded]]

## 4. 다음 세션 첫 작업 — 계층2 전량 적재 4패스

`docs/plans/rearchitecture_4layer_2026-07-19.md` §진행순서·`..._checklist.md` §"계층 2 전량
parsing → DB 적재" 참고. **순서 확정(사용자, 2026-07-19)**:

1. **공통 인프라**: `extract-lines`를 파일럿 → 전량 실행 경로로 확장(샤딩·재개·원자커밋,
   `phase_c_rebuild.py` 패턴 참고). 데일리 파이프라인 배선(`scripts/collect_new.py` 두
   call site — [[parser-pipeline-integration-runbook]] 절차 필수). 주석 포함 여부 결정
   (볼륨 5배).
2. **1차 — 2015+ 원본(93,801, TrackA 14,791+TrackB 79,010 한 번에)**. report_lines가 A/B
   동일 경로 처리하므로 분리 불요.
3. **2차 — pre-2015 원본(70,374)**. ⚠ 신규 파서 개발 필요(현 섹션검출기는 2015+ 전용,
   2009~13 `XI.재무제표 등`+`<P>`, 2000~08 미확인).
4. **3차 — PDF-only(3,575)**. ⚠ 신규 파서 개발(Track C `fin2/extract/pdf.py` → report_lines
   어댑트). PDF는 들여쓰기 없어 section_path 품질 낮음(인지하고 진행).
5. **4차 — 정정 처리 + 기간당 원문 1개 선택**. 정본선택(reconcile)을 여기로 이관("결국
   원문 1개만 남아야", 사용자 확정) — 계층3은 항상 정리된 1개 report_lines만 보게 함.

**4패스 전부 완료 = 전량 적재 완료. 그때 계층3(취합) 착수**(사용자 재확정, 이 순서를
뒤집지 말 것 — 엔진/파일럿 완성만으로 계층3 시작하지 않음).

## 5. 상태 주의

- ⚠ 야간 잡(gapfill·collect) **중지 유지** — [[nightly-jobs-paused-phase-a3]]. 4패스 전량 적재
  완료 후 복구 검토.
- ⚠ 앱은 `fact_v2 → statement_source → std_v2`(구 체인) 그대로 사용 중 — swap 안 함(계층3 후).
- ⚠ `report_lines` 테이블은 현재 **비어있음**(파일럿/검증 데이터는 세션 중 정리함) — 4패스가
  실제 전량 적재를 시작하는 지점.
- DB: `corporations` active **2533**(외국기업 21개 제외 후).
