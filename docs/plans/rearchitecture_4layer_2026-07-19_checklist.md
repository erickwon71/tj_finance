# 진행 체크리스트 — 4계층 재설계 (파서=원문 tree 전사 / 취합 별도)

> ⚠️ **이 체크리스트는 2026-07-19 시점 스냅샷 — STALE.** 이후 계층3 작업은 별도 트랙에서 진행돼
> 여기 마커에 반영 안 됨. **전체 현황·문서 맵은 마스터 허브 [`rearchitecture_4layer.md`](rearchitecture_4layer.md) 참조.**
> (이 파일은 계층2 세부 이력으로만 보존.)
>
> 마스터 계획 `docs/plans/rearchitecture_4layer_2026-07-19.md` · 착수 문서 `docs/qa/handoff_rearchitecture_2026-07-19.md`
> 관련 메모리 [[rebuild-phase-a3-done]] · [[nightly-jobs-paused-phase-a3]] · 구 Phase C 계획 `docs/plans/loop-vivid-bubble.md`(보존)
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. **각 계층은 검증 통과 후 다음으로.**
> ⚠ 야간 잡(gapfill·collect) **중지 유지** — 계층3 완료·검증 후 복구([[nightly-jobs-paused-phase-a3]]).
> ⚠ 앱은 std_v2 version=1(구 데이터) 계속 사용 중 — **swap 은 계층3 후.**

## 한 줄 요약

파서가 "값/canonical/취합"을 판단하다 **금융업 이중섹션**(평면 fact 로 합산-vs-제외 구분 불가)에서
막힘 → **4계층 분리**(다운로드 / 파서=원문 tree 충실전사 / 취합 별도 / App). 계층2(신규 `report_lines` tree)부터 재설계.
전량 79k·swap 보류.

---

## 권장 모델 (착수 전 `/model` 확인 — 사용자만 전환 가능)

| 단계 | 권장 | 근거 |
|---|---|---|
| 계층2 스키마·추출엔진 재사용 | Sonnet | text.py 로직 재배선, 패턴 명확 |
| 계층2 하위섹션/depth/소계·주석 tree | **Opus** | 구조 인식 휴리스틱 판단 집약 |
| 계층2 검증(원문 1:1·금융업 카나리아) | **Opus** | 원문 대조·엣지 판정 |
| 계층3 취합·값판단(금융업합산·capex·K-IFRS) | **Opus** | 값판단 핵심, 회귀 위험 |
| 전량 79k·swap·App 재연결 | Sonnet | 실행·재배선 |

(Pro 요금제 쿼터 관리: 판단 집약 단계만 Opus, 나머지 Sonnet으로 절약.)

---

## 계층 2 — `report_lines` tree (이번 재설계의 핵심 작업) ☑ 본문+section_path+주석슬라이스+TrackA/B통일 완료

**원칙**: 무손실 충실전사(본문 BS/IS/CF + 주석 전 라인, 보고서 순서·구조 그대로). **판단 없음**(canonical·grouping·값선택/취합 일절 안 함, max-abs·항등식·폴백 없음). **단위만** 원(₩) 정규화.

### 2A. 스키마 ☑ 완료 (2026-07-19)
- ☑ `ReportLine` 모델(`collector/models.py`) — 라인×컬럼 1행, **canonical_account 없음**(계층3 산출)
  - 컬럼: `rcept_no · corp_code · report_fiscal_year · report_fiscal_period · statement(BS|IS|CF) · basis(consolidated|separate) · section_path · row_order · depth · is_subtotal · label_raw · col_index(0당기/1전기/2전전기) · context_fiscal_year · value_won · adecimal · unit_source · period_kind · is_cumulative · source_ref · context_raw · parsed_at`
- ☑ 신규 테이블(FactV2 와 동일 관례) — `Base.metadata.create_all()` 자동 생성, 별도 마이그레이션 불요. `init_db()` 로 생성 확인 완료(`psql \d report_lines` 스키마 실측 대조)
- ☑ 인덱스: `ix_report_lines_lookup(corp_code, report_fiscal_year, statement, basis)` + `rcept_no`/`corp_code`/`report_fiscal_year`/`context_fiscal_year` 개별 인덱스 + FK(`filings.rcept_no`)
- **설계 결정**: 값 충돌 dedup(fact_v2 의 max-abs/보류) 없음 — 같은 라벨이 다른 위치(금융업 이중섹션 등)에 나와도 둘 다 그대로 보존. 재추출은 upsert 대신 **rcept_no 단위 delete-then-insert**(재현성, phase_c_rebuild.py 관례와 동일)

### 2B. 추출엔진 재사용 ☑ 완료 (2026-07-19)
- ☑ 신규 모듈 `fin2/extract/report_lines.py`: `fin2/extract/text.py` 재배선 — 섹션네비(`_detect_body_statement_tables`)·`declared_unit`·interim 누적컬럼(`_interim_cumulative_cols`)·단위역산(`_adecimal_from_unit`) 그대로 재사용, **canonical 매핑(`account_mapper.map()`) 호출 자체를 제거**
- ☑ `label_raw` = `row.account_name` 그대로(정규화 없음 — text.py 의 `acode`와 달리 `normalize_account_name` 미적용, "원문 그대로" 원칙)
- ☑ **범위 조정(스코프 정정)**: `row_order`·`depth`(indent_level)·`is_subtotal` 은 애초 계획 문서가 "신규 구현(2C)"으로 분류했으나, 실제로는 `parser.xml.table_extractor.RowData` 가 **이미 계산**해 두는 필드(`_detect_indent`·`_is_subtotal`, 기존 엔진 산출물)임을 확인 → 신규 로직이 아니라 **순수 재사용**이라 2B 범위로 당겨 완료. 2C 는 진짜 신규 로직(섹션헤더 인식·주석 tree·Track A/B 통일)만 남음
- ☑ 단위: 선언단위만 원(₩) 정규화, 미선언 표는 스킵(보류) — 기존 원칙 재사용 그대로
- ☑ CLI: `run.py extract-lines --corp CODE [--year Y] [--dry-run]` — `cmd_extract2` 패턴과 동일, **파일럿 전용**(데일리 파이프라인 미배선, 계층2 검증 통과 전까지 수동 실행만)
- **검증(실측)**:
  - 큐로셀 2023FY(`20240319000229`, `fin2/tests/test_text.py` golden 대상과 동일 픽스처): `자산총계` col0 = 104,969,385,964 / `자본총계` col0 = 59,099,540,497 — **golden 값과 정확 일치**
  - `is_subtotal` 플래그: 자산총계·부채총계·자본총계·매출총이익·영업이익·당기순이익 정확 검출
  - 제이아이테크 2024 H1(`20240814001863`) interim 누적컬럼: col0=30,488,775,643(2024누적) / col1=23,273,515,096(2023누적) — **golden 값과 정확 일치**(3개월 컬럼 미혼입)
  - DB round-trip: `init_db()` 로 테이블 생성 → `store_report_lines()` 저장(222행) → 재저장 시 **행수 불변**(delete-then-insert 멱등성 확인) → 검증 후 테스트 데이터 정리
  - CLI dry-run: 큐로셀 전체 11개 보고서(FY/H1/Q1/Q3) 무오류 추출, 3,613행

### 2C. 신규 tree 로직 ☑ (section_path + 주석슬라이스 + TrackA/B통일 완료 2026-07-19)
- ☑ **하위섹션 경로(section_path)** — 완료. 금융업 이중섹션이 구조로 구분됨
  - ☑ **핵심 발견**: 원문 XML 이 계층을 **선행 전각공백(U+3000)**으로 인코딩(section header=공백1, component=공백2). 단 `_get_cells` 의 `.strip()` 이 이 신호를 지워 `RowData.indent_level` 은 **항상 0(사문화)** 이었음(소비처도 없었음 — legacy 파서/PDF 는 row_order·is_subtotal 만 사용)
  - ☑ `parser/xml/table_extractor.py`: `RowData.raw_indent` 필드 추가(가산적) + `_first_cell_indent(tr)` 헬퍼(strip 전 raw itertext 에서 구조적 개행만 건너뛰고 선행공백 카운트). **위치 판단이지 값 판단 아님**
  - ☑ `fin2/extract/report_lines.py:_assign_section_paths`: **순수 indent-stack** — raw_indent 로 조상 헤더 체인 산출. **자산/부채/자본 top 주입·총계 특례·라벨 사전 전부 없음**(원문 top 행이 조상이라 자동으로 `자산>유동자산`/`자산>금융업자산` 생성 = 충실전사). depth 컬럼 = raw_indent
  - **검증(실측)**:
    - ★ 금융업 카나리아 **KG케미칼**(00101220): 현금 `자산>유동자산` 288,717,146,272 + `자산>금융업자산` 2,112,712,279 = **290,829,858,551 = CF 기말현금 정확 일치**. 단기차입금(`부채>유동부채`)/차입금(`부채>금융업부채`) 별도 라인
    - ★ 독립 2차 카나리아 **리드코프**(00117708, 다른 라벨서식 `자산>I. 유동자산`/`자산>III. 금융업자산`): 현금 42,786,165,648 + 600,180,078 = **43,386,345,726 = CF 기말현금 정확 일치**
    - 200사 파일럿(2023 annual): **크래시 0**, 131,591행, 금융업 이중섹션 2사 자동 검출
    - 비금융사(큐로셀) section_path 정상(`자산>Ⅰ.유동자산` 등, 로마숫자 원문 보존)
    - DB round-trip: section_path/depth 저장 확인 후 테스트데이터 정리
  - 회귀: test_text 11/11 · test_body_statement_tables 10/10 · **신규 test_report_lines**(카나리아 + 합성 RowData 로직 + no-doubling)
- ☑ **주석 tree 확장(첫 슬라이스)** — `_emit_note_lines`(report_lines.py), `extract_report_lines(include_notes=True)` + CLI `--notes`
  - 커버: 주석 섹션(연결/별도) 표 중 **단위 선언 + 금액행 있는 화폐 표만**(종속기업 요약재무·D&A·비용성격·부문손익·만기·PP&E 롤포워드 등). 비화폐 텍스트 표(종속기업목록·회계정책)는 **단위 미선언 → 스킵(보류)** = 본문 '미선언은 보류' 원칙 계승
  - **본문과 차이 — 컬럼을 연도로 판단 안 함**: 주석 컬럼은 자산/부채/자본총계·만기구간·5개년 등이라 '당기/전기' 아님 → `col_index`=위치, `context_fiscal_year`=**NULL**, `period_kind`=NULL. section_path=주석 제목(로케이터, 순수 단위선언 라인은 건너뜀). 최대 8컬럼 위치 전사
  - **검증**: KG케미칼 4,748 주석행, 단위환산 정확(KG ETS 자산총계 767,614,120천원→767,614,120,000원), context_fy 전부 NULL(DB 실측). 60사 파일럿 주석포함 **크래시 0**(주석 189,886행=본문 5배, 96% 표 통계와 정합). CLI+DB round-trip 확인. 신규 test 2건(off-by-default·화폐전사 위치/단위)
  - **알려진 한계(슬라이스1)**: 주석 제목 로케이터 66%만 서술형(34%는 인접 제목 없어 '(단위:천원)'만), 8컬럼 초과·비화폐(날짜/비율/텍스트) 셀 미전사. 필요 시 슬라이스2에서 확장
- ☑ **Track A(XBRL)/Track B(text) tree 통일** — **설계상 이미 통일**(실측 확인)
  - report_lines 는 **source-format 분기가 없다**: `_detect_body_statement_tables`+`extract_rows`(가시 표+들여쓰기)로 Track A·B 무관하게 동일 처리. DART Track A 보고서도 재무제표를 **가시 TABLE 로 임베드**(ACODE 셀이 그 표 안)하므로 calc-linkbase 별도 tree 불필요
  - **실측**: 실제 Track A 보고서(다원넥스뷰 2024, `source_format='xbrl_acode'`) — report_lines 자산총계 = **28,019,420,026 = Track A 권위값 정확 일치**. 계획이 우려한 '두 tree 모델 분기'는 미발생(단일 들여쓰기 tree). (삼성/SK/LG 등 최근 대형사 2023은 실측상 Track B — `TE@ACODE`는 DART 자체 `LST_*` 마커, ifrs-full ACONTEXT 아님)

> ✅ **현 상태(2026-07-19)**: **계층2(엔진) 완료** — 본문 BS/IS/CF tree + 금융업 이중섹션 구분 + 주석 화폐표 슬라이스 + Track A/B 통일. **다음 순서 = 계층2 검증 → 계층2 전량 parsing/DB 적재 → (그 후에야) 계층3.** (주석 슬라이스2·비화폐 셀은 필요 시.)
>
> ★ **일정 확정(2026-07-19, 사용자):** **계층3 은 계층2 전량 DB 적재가 끝난 뒤 착수.** 파일럿·엔진 완성만으로 계층3 를 시작하지 않는다 — 원문 tree 가 DB 에 다 들어간 상태를 입력 전제로, 취합을 **완성된 전량 데이터 위에서** 개발·검증한다. (구 순서 '계층3→전량'을 '전량→계층3'으로 뒤집음.)

## 계층 2 검증 (완료 판정) ◐ (2026-07-19 진행 중)
> **"원문" 정의**: 제출된 원본 DART 보고서 XML(raw_report/…)의 **재무제표 face 표에 실제 표시된 값**.
> 사람이 보고서를 열어 보는 그 숫자. 검증은 그 표를 **독립 리더**(report_lines 추출 경로와 다른
> 평면 스캔)로 다시 읽어 대조 → 같은 버그를 공유하지 않음.
- ☑ **검증 인프라 구축**: `fin2/audit/report_line_audit.py`(독립 리더 = 표 평면스캔으로 콤마3자리
  금액 다중집합 추출) + `scripts/verify_report_lines.py`(러너: `--corp`/`--rcept`/`--sample`/`--period`).
  기존 face_audit(Track A·canonical 지향)와 별개 — report_lines 는 canonical 없는 충실전사라
  **라벨/canonical 무관 값-집합 대조**가 맞다. 대조 = 실질금액(|v|≥1000) 집합, MISSING/EXTRA 판정.
- ☑ **★검증이 실버그 발견·수정**: `_JUNK_ACCOUNT_NAMES`(fact_v2 집계 이중계산 회피용 블록리스트)를
  report_lines 가 `extract_rows` 통해 상속 → **지분법자본변동·미처분이익잉여금·대손충당금·재고/비용
  세부 등 원문 face 라인을 통째 드롭**. 계층2(충실전사) 원칙 위반 = "판단이 파서에 섞임". 수정 =
  `extract_rows(skip_junk=False)` 파라미터(기본 True=fact_v2 동작 보존, report_lines 만 False).
  실측: KG 지분법자본변동 `(86,572,672)/(259,625,455)/3,204,931,313` 복원.
- ☑ **EPS(주당손익) 슬라이스1 범위 밖으로 확정**: 주당이익은 원(₩)/주 단위라 표 단위(천원/백만원)와
  달라 per-row 단위 override 필요(슬라이스2). `_is_header_cell`('단위:' 매치)로 드롭 중. 검증은
  원문·DB 양측 '주당' 라벨 대칭 제외. (계층3 은 net_income/shares 로 EPS 산출 가능 — 무영향.)
- ☑ **금융업 카나리아** — KG케미칼 2023FY(2C 에서 통과): 현금 `자산>유동자산` 288,717,146,272 +
  `자산>금융업자산` 2,112,712,279 = 290,829,858,551 = CF 기말현금. 단기차입금/차입금 별도.
- ☑ **카나리아 3사 FY 전수 100% PASS**(수정 후): KG케미칼 27/27 · 큐로셀 3/3 · 리드코프 27/27
  (원문↔DB 실질금액 완전일치, EXTRA=0=날조 없음).
- ☑ **광역 랜덤 표본(2015+ FY) 300/300 (100%) PASS** — 원문↔DB 실질금액 완전일치·EXTRA=0.
  → **본문 실질금액 1:1 충실전사 검증 완료**(FY 범위).
- ☑ **interim(H1/Q1/Q3) 대조** — report_lines 는 IS/CF 에서 YTD(누적) 컬럼만 채택하므로 3개월 컬럼은
  MISSING 이 정상 → 통과기준 = **EXTRA=0(DB⊆원문, 날조/오파싱 없음)**. 카나리아 3사 전기간 220/220 ·
  광역 all-period 표본 **399/400 (99.75%)**. 1건 실패 = 삼성생명(보험) 광폭 다열 CF/BS 포맷 부분캡처.
- ☑ **section_path 위치검증**(`scripts/verify_section_paths.py`, 값 아닌 tree 위치):
  - well-formedness(조상 실존): 광역 400표본 ~399/400. "자기참조"는 **위반 아님**(원문이 동명계정을
    인접 두 레벨에 인쇄 = 충실전사, 실측 비지배지분·현금 헤더/상세 동일값). 잔여 1건 = 라벨 주석참조
    잔재('지배주주지분 26') 마이너 에지.
  - ★**금융업 이중섹션 CF정합(핵심 semantic)**: 이중섹션 보고서에서 (일반현금+금융업현금 합) == CF
    기말현금. 표본 내 대상 전건 **100% 일치**(KG·리드코프·애경 등, ±1원 원문반올림 허용).
- ☑ **주석 라인 대조** — report_lines 주석값이 원문 주석표의 부분집합인지(날조 없음). db<face(≤8열캡·
  화폐표 한정으로 원문 일부만 담음, 정상). 잔여 소수 EXTRA 는 **실측상 날조 아님**(예 리드코프
  '보통주당기순이익' 35,933,756,131 이 원문에 그대로 존재 — 독립 주석리더 커버 갭). 주석 심화검증=슬라이스2.
- ☑ **슬라이스2 완료(2026-07-19) — 보험/증권 다열 + EPS + 주석심화**:
  - **보험/증권 기간당 다열 포맷**: `_detect_period_layout`(헤더 제N기 수 vs 데이터행 금액셀 수 →
    raw≥2×n_periods 면 multicol) + 비어있지않은 금액 압축 매핑. 합계행 밑줄장식('264,653,801====')
    `_TRAIL_DECOR_RE` 제거(parse_amount+_split_label_amounts). **삼성생명 89.7%→100%**, 삼성증권·
    한화생명 100%. 정상표 무영향(카나리아 유지).
  - **EPS per-row 단위 override**: `_emit_eps_lines` — 주당손익 행을 표 단위 무시하고 **인라인
    단위(원/주)**로 전사(`_is_header_cell` 드롭·표단위 오염 회피). `_NUMBER_PATTERN` 소수 허용
    (6,130.0). 검증기 주당 제외 해제 → **EPS 포함 대조**. 카나리아+주요 보험/증권 FY 100%.
  - **주석 심화**: 독립 주석리더 `read_note_amounts` 주당 필터 제거(report_lines 와 일치) →
    부분집합(날조없음) 48/60·잔여 EXTRA 실측 커버갭(보통주당기순이익 원문 실재). 주석 컬럼 위치
    전사 유지.
  - **회귀**: unit tests(text·report_lines·body·reconcile·quarterly) 전부 pass. **광역 FY 398/400
    (99.5%, EPS 포함)** · section_path well-formed 300/300 · 이중섹션 CF정합 100%.
  - **잔여 롱테일(문서화, 미추적)**: 외국상장사 이질포맷(로스웰) · 증권 '대손준비금 반영후 조정이익'
    다행라벨 · 주당 '보통주/기타보통주' 원-suffix 세부(주당 키워드 없음) · 주석 EXTRA 소수 커버갭.
- ☐ **남은 항목**: 전수 스윕(전량 적재 대상 확정 후) · 위 롱테일(필요 시).

## 계층 2 전량 parsing → DB 적재 — 4패스 (★계층3 전제조건) ☐
> **적재 순서 확정(2026-07-19, 사용자):** 아래 4패스를 순서대로. **4패스 전부 완료 = "전량 적재 완료"**,
> 그때 계층3 착수(사용자 확정: 계층3는 4차까지 끝난 뒤). 각 패스는 무결성 어서션 통과 후 다음으로.
>
> **대상 실측(2026-07-19)**: 다운로드 완료 XML — 2015+ 원본 **93,801**(TrackA 14,791 + TrackB 79,010) ·
> 2015+ 정정 9,627 · pre-2015 원본 70,374 · 정정 11,751 · **PDF-only 3,575**. 2015+ 정정제외 기간공백
> ≈0(정정만 있는 기간 1건). 단 2015+ 다중원본 기간 273건(원문 선택 필요 — 4차).

- **공통 인프라(1차 전에 1회)** ☐
  - ☐ `extract-lines` 파일럿 → **전량 실행 경로** 확장(샤딩·재개·원자커밋, `phase_c_rebuild.py` 패턴)
  - ☐ 데일리 파이프라인 배선(`scripts/collect_new.py` 두 call site) — [[parser-pipeline-integration-runbook]]
  - ☐ **주석 포함 여부 결정**(include_notes): 볼륨 5배 → 저장·성능 고려(본문 먼저 or 동시)
  - ☐ 계층2용 무결성 어서션(`phase_c_integrity_check` 확장: 커버리지·행수·금융업 이중섹션 표본)

- **1차 — 2015+ 원본 (93,801, TrackA+B 한 번에)** ☐  ← report_lines가 A/B 동일경로 처리, 분리 불요
- **2차 — pre-2015 원본 (70,374)** ☐  ⚠ **신규 파서 개발**(구형 섹션서식 2009~13 `XI.재무제표 등`+`<P>`·2000~08 미확인). 현 섹션검출기는 2015+ 전용
- **3차 — PDF-only (3,575)** ☐  ⚠ **신규 파서 개발**(Track C `fin2/extract/pdf.py` → report_lines 어댑트). **PDF는 들여쓰기 없어 section_path(tree) 품질 낮음** — 인지하고 진행
- **4차 — 정정/첨부정정 처리 + 원문 1개 선택** ☐  (2번 결정: 정정 파싱·원본값 수정은 여기서 마무리)
  - ☐ 정정·첨부정정(2015+ 9,627 · pre-2015 11,751) report_lines 전사
  - ☐ **기간당 원문 1개 선택**(corp×fy×period×basis 정본 결정) — 옛 statement_source(R-layer) 역할을 **계층2로 이관**("결국 원문 1개만 남아야", 사용자 확정). 다중원본 273건도 여기서 해소
- ☐ 4패스 완료 확인 = **계층3 입력 준비 완료**

## 계층 3 — 취합 (★4패스 전량 적재 완료 후 착수) ☐
> ⚠ **전제**: 위 4패스(1~4차) **전부** 완료 전에는 착수하지 않는다(사용자 확정 2026-07-19). 완성된
> report_lines 전량(정본 1개/기간) 위에서 개발. 정본선택은 4차에서 끝냈으므로 계층3 입력은 이미 정리됨.

**값판단 = 전부 여기서** (tree 문맥 + 기업별 리뷰).

- ☐ 입력 = `report_lines` tree (**정본 1개/기간** — 정본선택은 계층2 4차에서 이미 끝남)
- ☐ 매핑사전 이관: `concept_map`·`account_maps` 를 계층3 취합사전으로 (파서에서 뗀 것), 신규 계정명은 여기서 확장
- ☐ 값판단 이관(tree 문맥 활용):
  - ☐ **금융업 합산** — `section_path` 로 일반+금융업 동일계정 합산 (총계로 검증)
  - ☐ **capex 소계-우선** — `is_subtotal`·section_path 로 소계 채택, 없으면 성분합(리뷰)
  - ☐ **K-IFRS 영업이익**(dart_ 전용)·dual-section·sub-line 제외 — D4 로직 tree 기반 재정리
- ☐ 파생·커스텀 계정: capex·EBITDA·net_debt + 사용자 커스텀 취합계정 (보고서엔 없는 계정 생성)
- ☐ 출력 = 기존 `std_v2` 와이드 스키마 재사용, `build`/`quarterly`/`calendar` 이관 (입력을 report_lines 로). ★`reconcile`(정본선택)은 **계층2 4차로 이관** — 계층3은 취합만
- ☐ 애매분 = 기업별 리뷰 큐 (`phase_c_review_digest` 패턴, 사용자 확정 방식 계승)
- ☐ **이월 D4 잔여충돌 14 해소**: short_term_debt 6(금융업)·note D&A 5·retained 2·investing 1
- ☐ fuzzy 승급 빚(A): 정당한 alias 승격 (계층3 사전에서)

## swap / App (★계층3 완료 후) ☐
> report_lines 전량 적재는 계층3 **앞** 단계로 이동함(위 '계층2 전량 DB 적재' 참조).
- ☐ std_v2(version=2, 계층3 산출) 무결성 어서션(`phase_c_integrity_check` 8종: stale/dup/orphan/혼입/순수성/재map/clean_slate) 통과 → swap(app version=1→2)
- ☐ **계층4**: Streamlit 앱을 계층3 출력에 재연결 (신규 최소)
- ☐ 야간 잡(gapfill·collect) 복구 ([[nightly-jobs-paused-phase-a3]])

---

## 리스크/주의
- ☐ report_lines 는 주석 tree 포함으로 범위 큼 → **본문 statements 먼저 · 주석 다음** 단계화
- ☐ depth/소계 인식 = 들여쓰기·'합계/소계' 라벨 휴리스틱 — **위치(구조) 판단이지 값 판단 아님** (원칙 유지)
- ☐ 기존 D4/K-IFRS/capex 커밋(`3aa8cd5`·`a09df33`·`2a69802`·`c814539`·`3c87e27`) = **계층3 로직으로 재사용(폐기 아님)**. 단 std_v2/fact_v2 파일럿 데이터는 재설계 후 재생성 대상

## 재사용 산출물 (참고)
- `scripts/phase_c_rebuild.py` — 기업 순차·원자커밋·재개·재-map 패턴 (계층2/3 오케스트레이션 참고)
- `scripts/phase_c_integrity_check.py` — 무결성 8종
- `scripts/phase_c_review_digest.py` — 보류큐 다이제스트
- `fin2/audit/face_audit.py`·`line_audit.py` — 보고서↔DB 대조 (Phase A 호환 복구됨)
- `docs/qa/audit_concept_map_collapse_2026-07-18.md` — concept_map collapse 전수감사(20종)
