# TODO — DART 표준 XBRL 원문(ifrs.do) 파서 구현

계획 원문: [`xbrl_instance_parser_2026-08-05.md`](xbrl_instance_parser_2026-08-05.md). 이 문서는 그 계획을 실행 가능한 세부 작업 단위로 쪼갠 체크리스트다. **아직 구현 시작 전 — 다음 세션에서 Phase 0부터.**

각 항목은 순서대로 진행하되, Phase 0의 결론이 나오기 전엔 Phase 2(파서 핵심 로직) 세부 설계를 확정하지 않는다.

---

## Phase 0 — 실제 샘플 조사 (구현 착수 전 필수, 코드 작성 없음)

- [x] `LegacyDartScraper._get_view_params("20250828000534")` 실행해 박셀바이오 `dcm_no` + 세션 쿠키 확보
- [x] 같은 세션으로 `https://dart.fss.or.kr/pdf/download/ifrs.do?rcp_no=20250828000534&dcm_no=...&lang=ko` 요청 — 원샷 다운로드인지 2단계(main.do 확인→실제 다운로드)인지 확인
- [x] 응답이 실제 zip인지 매직바이트(`PK\x03\x04`)로 확인, HTML 오류 페이지와 구분
- [x] zip 다운로드 후 `dart.fss.or.kr`가 요청을 차단(캡차/레이트리밋)하지 않는지, OpenDART API 쿼터(40,000/일)와 무관한지 확인
- [x] unzip 후 파일 목록·크기 기록 (`.xbrl`/`.xsd`/`_def.xml`/`_cal.xml`/`_pre.xml`/`_lab-ko.xml`/`_lab-en.xml`)
- [x] instance(`.xbrl`) 루트 네임스페이스 선언 전체 기록 — `ifrs-full:` vs `dart:` 확장 프리픽스 확인
- [x] `<xbrli:context>` 3~5개 원문 그대로 기록 — period(instant/duration), entity, segment/scenario 내용 확인
- [x] 연결/별도(basis) 구분 방식 확정 — context 안의 dimension/member인지, 별도 instance 파일 2개인지
- [x] `<xbrli:unit>` 5~10개 원문 기록 (통화/단위 declaration 방식)
- [x] fact 10~15개 샘플(BS성 5개 + IS성 5개 이상) 원문 기록 — QName/contextRef/unitRef/decimals/값
- [x] context의 실제 날짜를 박셀바이오 2024H1 `Filing.period_end_date`와 대조해 col_index(0/1/2) 매핑 규칙·허용 오차 확정
- [x] `_pre.xml`의 distinct roleURI 전부 나열, 각 role의 정의(`link:definition`)로 BS/IS/CF/SCE/note 매핑표 초안 작성
- [x] `_pre.xml`에서 재무상태표로 보이는 role 하나의 `presentationLink`(loc/presentationArc, order, preferredLabel) 40줄 정도 원문 기록
- [x] `_lab-ko.xml` 라벨 5~10개 원문 기록 — `xml:lang="ko"` + DART가 쓰는 표준 라벨 role 확인 (label vs terseLabel vs verboseLabel)
- [x] `_cal.xml`에서 weight 속성 샘플 확인 — document.xml도 있는 유사 taxonomy 필링과 값 대조해 부호 반전 필요 여부 판정
- [x] `sanitize_dart_xml()`/`_parse_xml_file()`(`parser/xml/dart_xml_parser.py`)를 XBRL instance에 그대로 먹여도 되는지, 순수 `lxml.etree.parse`가 나은지 결론
- [x] Phase 0 조사 결과를 짧은 메모로 정리(이 문서 하단 "Phase 0 결과" 섹션에 채워넣기) — 이후 세션이 재조사 없이 이어받을 수 있도록
- [x] (추가 실측) 한화에어로스페이스(`20260513000860`, 2026Q1)로 교차검증 — 이 트랙의 실제 동기가 된 사례라 박셀바이오(소형·별도만) 외에 대형·연결+별도 병존 케이스도 확인

## Phase 1 — 데이터 모델 변경 (완료 2026-08-05)

- [x] `collector/db.py::_run_migrations()`에 `dcm_no` 컬럼 추가 마이그레이션 항목 추가 (`ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS dcm_no VARCHAR(20)`)
- [x] 같은 곳에 `file_type` 폭 확장 마이그레이션 추가 (`String(5)→String(10)`)
- [x] `collector/models.py`의 `DownloadTask`에 `dcm_no` 컬럼 선언 추가, `file_type` 컬럼 타입/코멘트 갱신
- [x] `parser_track` 코멘트에 `XBRL_INSTANCE` 값 추가 (폭 변경 불필요, `String(15)`로 충분)
- [x] 로컬 DB에 마이그레이션 적용 후 스키마 반영 확인 (`information_schema.columns` 조회 — `dcm_no VARCHAR(20)`/`file_type VARCHAR(10)` 확인)

migration id: `2026_08_download_tasks_dcm_no` / `2026_08_download_tasks_file_type_widen` (schema_migrations 에 기록됨, 멱등). `pytest fin2/tests/` 263 passed(기존 실패 1건 `test_lxintl_facility_table_dropped` 은 이 변경과 무관 — stash 재확인, 이번 변경 전부터 실패).

## Phase 2 — 다운로더 확장 (완료 2026-08-06)

- [x] `collector/legacy_downloader.py`에 `LegacyDartScraper._fetch_xbrl_instance(rcept_no, dcm_no)` 구현 (`_fetch_pdf()` 패턴 — Referer 헤더, 매직바이트 확인)
- [x] 같은 파일에 공개 메서드 `fetch_xbrl_zip(rcept_no)` 추가 (내부에서 `_get_view_params` 호출 후 위 메서드 호출)
- [x] `collector/downloader.py::_download_one()`의 `status_code == "014"` 분기에서 `_try_legacy_fallback()` 호출 전에 `_try_xbrl_instance_fallback()` 신설·삽입
- [x] 성공 시 zip 저장 로직 — `_build_file_path()` + tmp-then-move 패턴 재사용, `file_type='xbrl_zip'`, `parser_track='XBRL_INSTANCE'`, `dcm_no` 저장
- [x] 실패/부재 시 기존 `_try_legacy_fallback()`(PDF 폴백)으로 자연스럽게 이어지는지 확인 (기존 동작 회귀 없음)
- [x] `_mark_completed()`에 `dcm_no` 저장용 파라미터 추가

**★Phase 0 기록 정정(실제 구현 중 재확인, 2026-08-06)**: Phase 0 §1 "1회 GET으로 충분"은 맞지만,
`ifrs.do` 요청의 **`Referer` 헤더는 `/pdf/download/main.do?rcp_no=...&dcm_no=...` 여야 함** —
`/dsaf001/main.do?rcpNo=...`(Phase 0 조사 스크립트가 실제로 썼던 값과 다르게 최초 구현 시 잘못
추정한 값)로 보내면 서버가 **200 + `Content-Length: 0`(빈 바디)**를 반환해 조용히 실패한다
(HTML 오류 페이지도 아니고 매직바이트 불일치로만 드러남 — 로그만 보면 "XBRL 없음"으로 오판하기 쉬움).
`main.do`를 실제로 먼저 호출할 필요는 없음(Referer 값만 올바르면 충분, 재확인됨) — 계획대로 1회 GET 유지.
`_fetch_xbrl_instance()`가 올바른 Referer로 수정 후 박셀바이오(44,076B)·한화에어로스페이스(1,144,829B)
둘 다 Phase 0 기록과 정확히 일치하는 크기로 재현 확인(zip 매직바이트·박셀바이오 7파일 구성도 확인).

`pytest fin2/tests/` 263 passed(기존 무관 실패 1건 유지, Phase 1과 동일).

## Phase 3 — 파서 핵심 (Phase 0 결론 확정 후 착수)

- [x] `parser/xbrl_instance/` 패키지 신설 (`__init__.py`)
- [x] `instance_parser.py` — `.xbrl` instance 로드, context/unit/fact 구조화 파싱 (Phase 0에서 확정한 sanitize 필요 여부 반영)
- [x] `taxonomy_linkbase.py` — `_pre.xml` 파싱(role→트리 구조, order→row_order/depth), `_lab-ko.xml`/`_lab-en.xml` 파싱(라벨), `_cal.xml` 파싱(weight 부호) — 완료 2026-08-06
- [x] `role_map.py` — roleURI→statement(BS/IS/CF/SCE/note) 매핑표, Phase 0 조사 결과로 초기 채움 — 완료 2026-08-06
- [x] `fin2/extract/report_lines_xbrl.py` — `extract_report_lines_xbrl()` 진입점 구현, 기존 `ReportLineRow` 형태로 반환 — 완료 2026-08-06(BS/IS/CF만, SCE 보류 — 아래 "Phase 3 진행 기록" 참고)
- [x] basis(연결/별도) 해석 로직 구현 — context dims 정확히 1개(basis dim만)일 때만 채택
- [x] col_index/period_kind/is_cumulative 판정 로직 구현 — 허용오차 없이 날짜 정확매치(아래 기록 참고, 필요성이 없었음)
- [x] presentation 트리 워크로 section_path/table_seq/row_order/depth/node_role 산출
- [x] 라벨 해석(한글 우선, 폴백 영문) 구현
- [x] 값/단위 추출(KRW/KRWEPS만), weight 는 저장 시 미반영(Phase 0 §11 그대로 — 항등식 검증에만 필요함을 재확인, 아래 기록), `unit_source='xbrl'` 신설
- [x] note 포함 여부(`include_notes`) 처리 — Phase 3-5 범위 밖으로 확정(본문 BS/IS/CF만, SCE 도 이번엔 보류 — 아래 기록)
- [x] 3-7: SCE(자본변동표) 구현 — 완료 2026-08-06(아래 "Phase 3-7 진행 기록" 참고)

## Phase 4 — 데일리 파이프라인 배선 (두 call site 필수) — 완료 2026-08-06

- [x] `collector/xbrl_instance_lines_sync.py` 신설 — `note_lines_sync.py` 구조 재사용, `file_type='xbrl_zip'` 대상 쿼리
- [x] `scripts/collect_new.py`에 `_sync_xbrl_instance_lines(corps)` 래퍼 함수 추가 (비치명 try/except)
- [x] call site 1: `collect_new.py`의 `--standardize-only` 재개 분기(기존 `_sync_layer2_lines(affected)` 호출 직후)에 추가
- [x] call site 2: `collect_new.py`의 메인 경로(기존 `_sync_layer2_lines(affected)` 호출 직후)에 추가
- [x] 두 call site 모두에서 실제로 호출되는지 로그로 확인 (더미/드라이런)
- [x] 기존 `sync_layer2_lines`(`file_type='xml'`)와 겹치는 rcept_no가 없는지 재확인 (중복 적재 가드 불필요 여부 최종 검증)

### Phase 4 진행 기록

**4-1**: `collector/xbrl_instance_lines_sync.py` 신설 — `sync_xbrl_instance_lines(corps, year_min=2015,
recheck=False)`. `note_lines_sync.py`와 구조 동일(corp 바운드 재개, rcept 단위 delete-then-insert
멱등, 한 건 실패가 전체를 안 막음)이지만 대상이 다르다: `download_tasks.file_type='xbrl_zip'`.
`extract_report_lines_xbrl()`(Phase 3)은 본문(BS/IS/CF/SCE)만 만들고 주석은 안 만들어서
`store_report_lines`/`store_report_tables`만 호출(`store_note_lines` 불필요). 재개 판정은
`report_lines.unit_source='xbrl'`로 좁혔다(단순 rcept_no 존재 여부가 아니라) — 아래 4-6 검증으로
이게 실제로 구분이 필요 없는 상황(두 경로가 애초에 안 겹침)임이 드러났지만, 안전장치로 유지.

**4-2**: `scripts/collect_new.py`에 `_sync_xbrl_instance_lines(corps)` 래퍼(`④-4` 마커) 신설,
`_sync_layer2_lines`(`④-3`) 바로 뒤에 배치. 두 call site 모두 배선 — `--standardize-only` 재개
분기(`main():664`)와 메인 경로(`main():772`), 둘 다 `_sync_layer2_lines(affected)` 직후.

**4-마지막 항목(dedup 가드 필요성 검증, 2026-08-06)**: 결론 — **불필요, 구조적으로 겹칠 수 없다.**
세 층위로 확인했다:
1. **스키마**: `download_tasks.rcept_no`에 `ix_download_tasks_rcept_no` UNIQUE INDEX가 실제로
   걸려 있음(`pg_indexes` 조회로 확인, `collector/models.py::DownloadTask.rcept_no`의
   `unique=True` 선언대로 반영됨) — 필링(rcept_no) 하나당 `download_tasks` 행이 **정확히 하나**이므로
   `file_type` 값도 하나뿐이다. 같은 rcept_no가 `'xml'`이면서 동시에 `'xbrl_zip'`인 상태 자체가
   DB 레벨에서 불가능.
2. **코드 경로**: `collector/downloader.py::_download_one()`(:411~415) — `_try_xbrl_instance_fallback()`
   은 오직 OpenDART API 응답이 `status_code == "014"`(파일없음)일 때만 호출된다. 이 상태코드는 그
   필링이 실제로 `document.xml`을 아예 안 가지고 있다는 DART 서버측 사실이라 재시도해도 값이
   안 바뀐다 — 즉 어떤 rcept_no 가 한 번 `'xml'` 로 성공했다면 그 rcept_no 는 절대 이 분기에
   진입할 수 없고, 반대로 `'014'`가 뜨는 rcept_no 는 재시도해도 계속 `'014'`만 뜬다(같은 이유로
   `'xbrl_zip'`이 나중에 `'xml'`로 뒤집히는 것도 불가능). 두 경로가 필링 콘텐츠 자체로 영구히
   갈린다.
3. **실측(DB 쿼리)**: `SELECT file_type, status, count(*) FROM download_tasks GROUP BY 1,2` —
   현재 `xbrl_zip` 완료 행 **0건**(Phase 5 백필 미실행 상태라 예상대로), `report_lines`에서
   `unit_source='xbrl'`인 rcept_no 도 0건(당연히 아직 없음) — 겹칠 데이터 자체가 아직 없어
   "현재 겹침 없음"은 자명하지만, 위 1·2 번이 "앞으로도 구조적으로 못 겹친다"는 걸 보장한다.
   `report_lines`에 unit_source 가 2종 이상 섞인 rcept_no 44건이 실제로 있긴 했으나(전부
   `declared`/`doc_default`/`fx_declared` 조합, 기존 HTML 파서 내부의 열 단위 판정 다중값 —
   `[[layer2-unit-column-attribution]]` 범위, XBRL 경로와 무관) `'xbrl'`이 낀 것은 0건.

**부수 발견(작업 중, Phase 4 범위 밖 — 사용자에게 별도 보고·조치 완료)**: 4-5(call site 로그 확인)용
dry-run 스크립트가 `_run_mirror_and_audit()`를 스텁 처리 못 해 실제로 실행시켰고, 그 감사가 진짜
갭(한일철강 정정공시 2건, 오늘 18:00 정기배치가 NAS 미마운트로 저장소 계약 위반 중단된 여파)을
발견해 실제 알림 이메일이 나갔다. 사용자 확인 후 `--days 1 --download-only` 수동 실행으로 즉시
해소(미탐지 0으로 재확인). 이 과정에서 상장폐지 원문 이관 보류 알림도 별도로 발생(3개사, NAS
파일수 부족 — 가드 정상 동작, 데이터 유실 아님, 미해결로 남김).

`pytest fin2/tests/` — NAS 마운트 상태에서 263 passed(기존 무관 실패 1건 유지, 이번 변경과 무관).

## Phase 5 — 소급 백필 (5건)

- [ ] 대상 5건 corp_code 확인: 박셀바이오·웰킵스하이텍(3필링, 동일기업)·한화에어로스페이스
- [ ] 해당 `download_tasks.status`를 `pending`으로 리셋하는 원샷 스크립트 작성
- [ ] `run_downloads(only_corp_codes=[...])` 실행 — XBRL zip 다운로드 확인
- [ ] `sync_xbrl_instance_lines(corps=[...], recheck=True)` 실행 — `report_lines`/`report_tables`/`note_lines` 신규 행 확인
- [ ] 6건(자비스 제외 5건) 각각 `n_loaded>0`으로 전환됐는지 재확인 (`probe_residual_gap_breakdown.py` 재실행)
- [ ] layer3(std_v2/std_v3) 재표준화 필요 여부 확인 (`needs_standardize_corps()` 조건) — 필요시 타겟 재실행

## Phase 6 — 검증

- [ ] `fin2/tests/test_xbrl_instance.py` 신설 — 박셀바이오 실 샘플 기반, 주요 계정 하드코딩 대조, 구조/라벨/instant-duration 검증
- [ ] 박셀바이오 2024H1 값 3~5개 DART 웹뷰어와 수동 대조
- [ ] 한화에어로스페이스 2026Q1 값 3~5개 DART 웹뷰어와 수동 대조 (실거래 활성기업 — 공개된 실제 수치와도 대조 가능하면 추가 확인)
- [ ] Gate B 전/후 비교 — 이 6건이 "무데이터→pass/fail"로만 이동하고 기존 다른 필링 회귀 없는지 (`run_dq_gate`/`face_audit`)
- [ ] 항등식 점검 (자산=부채+자본 등) — 부호 규약 오류 조기 발견용
- [ ] `pytest` 전체 회귀 실행 — 기존 테스트 통과 유지 확인
- [ ] `docs/PARSING_RULES.md`에 이번에 확정한 규칙(있다면, 예: XBRL 원문 unit/기간 판정 방식)을 R-번호로 반영

---

## Phase 0 결과 (2026-08-05 실측 완료)

조사 대상 2건: **박셀바이오**(`20250828000534`, 2024H1, 소형·별도만) + **한화에어로스페이스**(`20260513000860`, 2026Q1, 대형·연결+별도 병존 — 이 트랙의 실제 동기). 조사 스크립트/원본 zip은 세션 scratchpad에만 저장(레포 미포함), 재현 가능(코드는 아래 "다운로드 흐름" 참고).

### 1. 다운로드 흐름 — 계획보다 단순함

- `LegacyDartScraper._get_view_params(rcept_no)`로 `dcm_no` 획득(세션 쿠키도 같이 확보됨) → **곧바로** `GET /pdf/download/ifrs.do?rcp_no=...&dcm_no=...&lang=ko` 하면 **원샷으로 zip이 온다.** PDF 흐름(`_fetch_pdf`)처럼 `/pdf/download/main.do`로 먼저 존재 확인하는 2단계가 **필요 없음** — 오히려 `main.do`는 "PDF 파일 보려면 Adobe Reader 설치…" HTML만 반환(PDF 없다는 뜻일 뿐, XBRL 존재와 무관).
- 응답 `Content-Type: application/zip`, 매직바이트 `PK\x03\x04` 확인됨. HTML 오류 페이지와 확실히 구분됨(2866B HTML vs 44KB~1.1MB zip).
- 두 회사 다 1회 요청으로 성공, 캡차/차단 없음(2초 쓰로틀 유지). OpenDART API(`opendart.fss.or.kr`) 쿼터와는 무관한 `dart.fss.or.kr` 웹 엔드포인트라 확인대로 무관.
- 계획의 `_fetch_xbrl_instance()` 설계는 **`_fetch_pdf()`의 2단계 패턴을 따르지 말고** 1회 GET으로 단순화할 것.

### 2. zip 구성 — 계획과 정확히 일치

파일명 패턴: `entity{CIK}_{period_end}.{ext}` (`.xbrl`/`.xsd`/`_def.xml`/`_cal.xml`/`_pre.xml`/`_lab-ko.xml`/`_lab-en.xml` 7개, 예외 없음). 박셀바이오 44KB→7파일 합계 ~720KB(대부분 라벨/정의), 한화 1.1MB→7파일 합계 ~26MB(`_def.xml`/`_lab-*.xml`가 각 5MB대 — 대형 연결기업은 주석까지 광범위하게 태깅돼 훨씬 큼).

### 3. 루트 네임스페이스

`ifrs-full:`(IFRS 표준), `dart:`(DART 확장 계정), `dart-gcd:`(DART 공통정보축 — 작성자/기간축 등 메타), `entity{CIK}:`(**기업별 커스텀 확장** — 예: 박셀바이오 `entity01335851:udf_CF_...PaymentsOfFinanceLeaseLiabilities...`) 4종 프리픽스가 항상 나옴. 커스텀 확장 element는 해당 기업의 `.xsd`에 선언되고 라벨은 `_lab-ko.xml`에서 옴 — role_map/label 해석 시 이 네임스페이스도 반드시 커버해야 함.

### 4. 연결/별도(basis) — 별도 instance 파일 아님, context dimension으로 구분 (실측 확정)

`ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis` 축의 멤버로 구분됨: `ifrs-full:ConsolidatedMember`(연결) / `ifrs-full:SeparateMember`(별도). **하나의 `.xbrl` 파일 안에 둘 다 들어있음.**
- 박셀바이오(자회사 없는 소형 바이오): **`SeparateMember`만 존재**, `ConsolidatedMember` 컨텍스트 0개 — 연결 자체가 작성 대상이 아닌 케이스도 있다는 뜻, 파서가 "연결 없으면 그냥 없는 것"으로 처리해야 함(에러 아님).
- 한화에어로스페이스(대형 지주): 2,850개 컨텍스트 중 `ConsolidatedMember` 1,635개 + `SeparateMember` 1,207개 **둘 다 풍부하게 존재**.
- → basis 판정 로직은 각 context의 `xbrldi:explicitMember[@dimension='ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis']` 값을 보면 되고, "연결/별도 인스턴스 파일 2개" 가설은 **기각**.

### 5. context 명명 규칙 — ID 문자열은 힌트일 뿐, 실제 판정은 period 값으로

관측된 패턴: `{CFY|PFY|BPFY}{연도}{d|e}{보고유형코드}[A|Q]_...`
- `CFY`=당기(Current FY), `PFY`=전기(Prior FY), `BPFY`=전전기(Before-Prior FY, 주석 비교용으로만 등장)
- `d`=duration(구간), `e`=instant(시점)
- 보고유형코드는 **보고서 종류에 따라 달라짐** — 반기보고서(박셀바이오)는 `HY`(반기)/`HYA`(반기누적)/`HYQ`(반기중 분기), 분기보고서(한화 Q1)는 `FQ`(분기)/`FQA`(분기누적)/`FQQ`(분기중 분기). **다른 보고서 종류(사업보고서 등)에서 또 다른 접미사가 나올 가능성이 있음 — 하드코딩 매핑 대신 이 명명 패턴을 정규식으로 일반화하되, 최종 판정은 반드시 `<xbrli:period>`의 실제 `instant`/`startDate+endDate` 값을 `Filing.period_end_date`와 대조해서 확정할 것(R9, 문자열만 믿지 않기).**
- 예시(박셀바이오, 반기): `CFY2024eHYA`→instant 2024-06-30(당기말) / `PFY2023eHYA`→instant 2023-06-30(전년동기말) / `PFY2023eHY`→instant 2023-12-31(직전 사업연도말, 비교 BS) / `CFY2024dHYA`→2024-01-01~06-30(당기누적) / `CFY2024dHYQ`→2024-04-01~06-30(당기 2분기 단독).
- 예시(한화, 분기): `CFY2026eFQA`→instant 2026-03-31 / `PFY2025eFQA`→instant 2025-03-31(전년동기말) / `PFY2025eFQ`→instant 2025-12-31(직전 사업연도말) / `BPFY2024eFQ`→instant 2024-12-31(전전 사업연도말, 주석 비교용).

### 6. 단위(unit) — 단순함

관측 3종뿐: `KRW`(`iso4217:KRW`), `PURE`(`xbrli:pure`, 비율/배수), `KRWEPS`(KRW÷`xbrli:shares` divide 단위, EPS 전용). 계획의 "5~10개 기록" 대비 실제로 매우 단순 — 통화 혼재나 이상 단위 케이스는 이번 샘플엔 없었음(외화 표시 필링이 섞일 가능성은 [[fx-declared-statements]] 규약과 별개로 추후 확인 필요).

### 7. ★가장 중요한 발견 — fact는 tag+context만으론 유일하지 않음, presentation 트리 워크 필수

같은 QName(`ifrs-full:Assets`/`Liabilities`/`Equity` 등)이 **본문 재무제표 총계뿐 아니라 주석의 세그먼트별/거래처별/카테고리별 분해표에도 반복 태깅됨.** 한화 샘플에서 `ifrs-full:Assets` 태그로 단순 검색하면 40개 이상 걸리는데(세그먼트 자산, 계약별 자산 등 포함, 심지어 증감내역 주석이라 음수도 섞임), 그중 실제 재무상태표 총자산은 **`ConsolidatedAndSeparateFinancialStatementsAxis` 축 하나만 걸린(다른 axis 없는) context 것 정확히 1개**였음(56,659,594,923,000원 — 유동자산 32,208,963,769,000 + 비유동자산 24,450,631,154,000과 일치, 부채(39,219,529,796,000)+자본(17,440,065,127,000)과도 정확히 일치해 항등식 검증 통과).
→ **계획의 "presentation linkbase 트리 워크로 section_path/depth/row_order 산출" 설계가 필수임을 재확인.** tag명 기반 스캔이나 "axis 개수" 같은 얕은 휴리스틱으로 본문 vs 주석을 구분하려 하지 말 것 — 반드시 대상 role(D2/D4/D5/D6)의 `_pre.xml` loc/arc 트리에 실제로 걸린 (element, context) 쌍만 채택.

### 8. `_pre.xml` role 매핑 — roleURI 숫자 대신 `link:definition`의 한글 텍스트로 매핑 (강력 추천)

roleURI 자체(`http://dart.fss.or.kr/role/ifrs/dart_2024-06-30_role-D210005`)는 taxonomy 버전 날짜가 박혀 있어 필링마다 달라짐 — 하드코딩 매핑표로 관리하면 매번 깨짐. 대신 `.xsd`의 `<link:roleType roleURI="..."><link:definition>` 텍스트에 **역할이 한글로 그대로 적혀 있음**:
- `[D210005] 재무상태표, 유동/비유동법 - 별도` / `[D210000] ... - 연결`
- `[D431415] 단일 포괄손익계산서, 기능별 분류, 세후 - 별도` / `[D431410] ... - 연결`
- `[D520005] 현금흐름표, 간접법 - 별도` / `[D520000] ... - 연결`
- `[D610005] 자본변동표 - 별도` / `[D610000] ... - 연결`
- 한화 샘플엔 이 4쌍(8개) 외에 `D8xxxxx`/`U8xxxxx` 계열 role이 **310개 더** 있음 — 전부 주석(금융위험관리·공정가치측정·유형자산·무형자산 등 번호가 매겨진 주석 챕터). 박셀바이오(반기, 소형)는 이 4개 role만 존재, 주석 role 0개.
- → `role_map.py`는 `link:definition` 문자열에서 "재무상태표"/"포괄손익계산서"/"현금흐름표"/"자본변동표" 키워드 매칭 + "- 연결"/"- 별도" 접미사로 분류(숫자 코드는 참고용 로그에만 사용). 본문(BS/IS/CF/SCE) 4역할만 있는 필링과 주석까지 수백 개 있는 필링이 둘 다 존재함을 전제로 설계할 것.

### 9. presentation 트리 구조 — 계획대로 loc/arc/order로 깊이·순서 산출 가능

`<link:loc>`(요소 참조, 표준 IFRS 요소는 `href`가 외부 IFRS taxonomy URL, 커스텀 확장은 자사 `.xsd#element`) + `<link:presentationArc>`(`xlink:from`/`xlink:to`/`order`/`use="optional"`/`priority`) 구조 확인. **`order`는 정수 아님 — `1`, `1.5`, `3`, `7`, `12`, `12.8` 등 소수 섞여 있음** → 정렬 시 반드시 float 파싱(문자열/int 캐스팅 금지). 트리 깊이는 arc의 from→to 체인을 재귀적으로 따라가면 산출됨(계획대로).

### 10. 라벨(`_lab-ko.xml`) — `preferredLabel` 속성이 있으면 그대로 따르면 됨

관측된 label role 10종: 표준 `label`(기본), DART 자체 `dart_label`(원문 표시와 더 가까운 경우 있음, 예: `기타이익` vs 표준 `기타수익`), `terseLabel`/`verboseLabel`/`totalLabel`/`periodStartLabel`/`periodEndLabel`/`negatedLabel`/`negatedTerseLabel`/`netLabel`. **`presentationArc`에 `preferredLabel` 속성이 박혀 있어(관측: terseLabel 8건·dart_label 7건·totalLabel 6건·negatedTerseLabel 2건 등) 트리의 그 위치에서 어떤 label role을 써야 하는지 필링이 직접 알려줌** — 별도 추론 로직 불필요, `preferredLabel` 있으면 그 role 우선 조회, 없으면 표준 `label`로 폴백, 한글 없으면 `_lab-en.xml` 폴백(계획대로).

### 11. `_cal.xml` weight — 부호 반전 불필요, 값은 이미 "표시된 그대로" 저장돼 있음

박셀바이오 BS calc: weight `1`(59건)/`-1`(11건) 혼재. 그런데 실제 fact 값(자산=83,142,583,571 / 부채=4,867,937,672 / 자본=78,274,645,899)은 **부호 반전 없이 그대로 더하면 항등식이 맞음**(부채+자본=자산 정확히 일치). weight=-1은 calculation linkbase가 "합산 시 이 항목을 빼라"는 rollup 검증용 메타데이터일 뿐, **fact 자체의 표시값에는 이미 반영돼 있어 저장 시 추가 부호처리 불필요**로 잠정 결론. 다만 IS(포괄손익계산서)의 비용 항목처럼 "빼는 게 자연스러운" 계정에서 실제로 음수로 저장돼 있는지는 화면에 보이는 표시 그대로 저장하면 되므로 파서 구현 시 값 그대로 적재 후 항등식 검증(Phase 6)에서 최종 확인.

### 12. `sanitize_dart_xml()` 불필요 — 순수 `lxml.etree.parse()`로 충분

박셀바이오(87KB)·한화(6.6MB) 양쪽 다 7개 파일 전부 `lxml.etree.parse()`로 **에러 0, 파싱 시간 30ms 이내**로 성공. `document.xml`(DART 자체 `<TABLE>/<TE>` 서식)에서 나타났던 속성 따옴표 절단·PI 이스케이프 등 [[layer2-silent-loss-patterns]]류 함정은 **표준 XBRL instance엔 해당 없음**(별개 생성 파이프라인이라 추정). → `parser/xbrl_instance/instance_parser.py`는 `sanitize_dart_xml()` 호출하지 말고 `lxml.etree.parse()` 직접 사용.

### Phase 3 진행 기록

**3-1·3-2 완료(2026-08-06)**: `parser/xbrl_instance/__init__.py`(빈 파일, `parser/xml`·`parser/pdf` 컨벤션과 동일) +
`instance_parser.py`(`parse_instance()` — context/unit/fact 순수 구조 파싱, 판정 로직 없음. dataclass
`QName`/`Dimension`/`XbrlContext`/`XbrlUnit`/`XbrlFact`/`XbrlInstance`, `_validate()`로 dangling
contextRef/unitRef 경고 로그).

**실제 두 샘플로 재검증(Phase 0 zip을 다시 받아 파서에 직접 통과)**: 박셀바이오 44,076B/한화 1,144,829B —
크기 Phase 0 기록과 정확히 일치. 박셀바이오 32 contexts/3 units/289 facts, 한화 2,850 contexts/10
units/8,004 facts, 파싱 속도 5ms/139ms(문제 없음). 한화의 "basis 축만 걸린 `Assets`" 값
**56,659,594,923,000원**(연결·당기)이 Phase 0 §7 기록과 정확히 일치 — 파서 정확성 교차검증됨.
Multi-dim context(SCE 성분축 등 basis 외 추가 축) 정상 파싱 확인.

**Phase 0 기록 보완(정정 아님, 미확인 항목 실측 확인)**: Phase 0 §6 "단위 관측 3종뿐(KRW/PURE/KRWEPS),
외화 혼재는 미확인"이라 적었던 것을 한화(대형·연결) 샘플에서 실측 확인 — **10종 단위 관측**
(KRW/PURE/KRWEPS + PHP/USD/AED/ROL/AUD/EUR, 해외종속회사 주석 공시로 추정). 파서 코드 영향 없음
(measure 파싱은 이미 임의 `iso4217:XXX` 통화코드에 범용적으로 대응) — role_map/추출 범위(Phase 3 후속
항목)에서 본문(BS/IS/CF/SCE, 항상 KRW로 추정)만 다루는 한 무관하나, 주석까지 범위를 넓힐 경우 대비 기록.

`pytest fin2/tests/` 263 passed(기존 무관 실패 1건 유지, `test_lxintl_facility_table_dropped`).

**3-3 완료(2026-08-06)**: `taxonomy_linkbase.py` 신설 — `_pre.xml`(presentation)·`_cal.xml`(calculation)
role→트리(loc/arc/order→parent/children/depth, `preferredLabel`/`weight` 보존) + `_lab-ko.xml`/`_lab-en.xml`
라벨 카탈로그(concept→[Label(role,lang,text)], `merge_label_catalogs()`로 ko+en 병합). 핵심 설계:
- `resolve_href_fragment()` — 로케이터 href의 URL fragment(`"{prefix}_{LocalName}"`)를 QName으로 변환.
  prefix가 `_`를 포함하지 않는다는 taxonomy 관례(ifrs-full/dart/dart-gcd/entity{CIK})로 첫 `_`에서만
  split — entity 확장 로컬명 안의 추가 `_`(예: `entity01335851_udf_CF_...`)도 정확히 처리됨. nsmap은
  linkbase 파일 자체엔 선언 안 돼 있어(instance root에만 있음, Phase 0 §3) 호출자가 공급
  (→ `instance_parser.py`에 `XbrlInstance.nsmap` 필드 신규 추가, 순수 기록용·판단 없음).
- 트리 노드는 concept이 아니라 **loc_label(linkbase 고유 wiring id)로 키잉** — 실측 확인: 같은 concept이
  한 role 안에서 두 자리(예: 주석 롤포워드표 기초/기말 잔액, `_periodStartLabel`/`_periodEndLabel` 접미
  loc)를 차지하는 경우가 실재함.
- 실측 검증(두 샘플 재파싱, 예외 0): BS role root=`StatementOfFinancialPositionAbstract` 단일(양쪽 다),
  calc role `Assets`→`CurrentAssets`/`NoncurrentAssets` weight 둘 다 1.0(Phase 0 §11과 일치), `OtherGains`
  라벨 카탈로그가 `label`(기타수익)/`dart_label`(기타이익)/`terseLabel`/`totalLabel` 등 role별로 정확히
  분리돼 나옴. **핵심 4역할(D210/D431/D520/D610)은 두 샘플 전부 깨끗한 단일부모 트리**로 확인.
- **신규 발견(범위 밖으로 확인, 코드 영향 없음)**: 주석/차원 role(D8xxx/U8xxx)에서는 presentation
  "트리"가 실제로는 **DAG**일 수 있음 — 같은 Axis가 여러 Table 로케이터에서 공유돼 한 노드가 둘 이상의
  parent arc를 가짐(한화 샘플에서 189건 관측, 전부 note role, core 4역할 0건). `_build_tree_shape()`는
  첫 arc를 유지하고 경고 로그만 남김 — Phase 3 현재 범위(본문만)엔 무관, role_map.py가 note role을
  걸러내는 한 이 경고는 무해한 노이즈로 봐도 됨(단, 향후 주석까지 범위를 넓히면 트리 대신 DAG 모델링이
  필요해짐 — 미해결 과제로 기록).

`pytest fin2/tests/` 263 passed(기존 무관 실패 1건 유지, 이번 변경과 무관).

**3-4 완료(2026-08-06)**: `role_map.py` 신설 — `.xsd`의 `<link:roleType><link:definition>`
텍스트(`"[{role_id}] {한글정의} | {영문정의}"`)를 키워드+접미사로 분류. 핵심 발견: roleURI
숫자코드(`D210000` 등)는 taxonomy 버전에 종속돼 필링마다 바뀌므로 **절대 매핑 키로 안 씀** —
`definition_ko`의 "재무상태표"/"포괄손익계산서"(손익계산서 폴백)/"현금흐름표"/"자본변동표" 키워드
+ **"- 연결"/"- 별도" 접미사 존재 여부**로만 판정. 이 접미사 유무가 본문(core) role과 동명의
주석(note) role을 가르는 유일한 신호임을 실측으로 확인 — 한화 샘플의 `[D851100] 42. 현금흐름표`
(현금흐름표 관련 주석 챕터, 접미사 없음)이 키워드는 일치하지만 접미사 부재로 정확히 배제됨(수동
검증: `role_map.build_role_map()` 결과에 D851100/D851105 없음 확인).
`build_role_map(xsd_path)`가 두 샘플에서 정확히 Phase 0 §8 기록과 일치하는 개수 산출 — 박셀바이오
4개(별도만, D210005/D431415/D520005/D610005), 한화 8개(연결+별도 각 4, D210000/D210005/
D431410/D431415/D520000/D520005/D610000/D610005). `index_core_roles()`로 (statement,basis)→
RoleInfo 역인덱스 제공(둘 이상 겹치면 raise 대신 경고 로그, Phase 0 "최대 8개" 가정이 깨지는
필링을 조용히 넘기지 않기 위함). 주석 role(D8xxx/U8xxx 등 310개, 한화 기준)은 전부 정상적으로
걸러짐(리크 0건, 수동 확인).

`pytest fin2/tests/` 263 passed(기존 무관 실패 1건 유지, 이번 변경과 무관).

**3-5 완료(2026-08-06)**: `fin2/extract/report_lines_xbrl.py` 신설 — `extract_report_lines_xbrl()`.
두 샘플 zip 을 다시 받아(크기 Phase 0/3-1 과 정확히 일치, `LegacyDartScraper.fetch_xbrl_zip()` 재현)
실제로 파싱·검증했다(레포에는 미포함, 세션 scratchpad 만).

- **범위: BS/IS/CF 만.** SCE(자본변동표)는 이번엔 보류 — 열 축이 기간(당기/전기)이 아니라
  `ifrs-full:ComponentsOfEquityAxis` 이고, 그 멤버 자체가 계층 구조다(한화 연결 SCE 를 직접 실측:
  `EquityMember`(도메인=총계) → `EquityAttributableToOwnersOfParentMember`(지배지분 소계, 자체가 또
  `IssuedCapitalMember`/`CapitalSurplusMember`/… 자식을 가짐) 형제로 `NoncontrollingInterestsMember`).
  게다가 `report_lines.py::_is_loadable()` 는 SCE 를 `col_index==0` 필터에서 제외해 **SCE 행은 나오는
  대로 전부 저장**된다 — 열 의미를 잘못 짚으면 그대로 오염된 채 적재된다. R9(원문 대조 없이 넘겨짚지
  않기) 원칙상 이 구조는 별도 조사 후 다음 스텝에서 다루기로 결정(코드에 이유와 함께 명시적으로 보류
  — 3-3 이 note role 의 DAG 를 범위 밖으로 명시한 것과 같은 방식).

- **basis 재확인**: context dims 가 **정확히 1개**(basis dim 만)일 때만 채택하는 Phase 0 §7 규칙을
  그대로 구현. 실측: 한화 연결 BS `Assets` = 56,659,594,923,000(Phase 0 §7 기록과 정확히 일치),
  `Liabilities`(39,219,529,796,000) + `Equity`(17,440,065,127,000) = `Assets` 정확히 일치, 별도도
  마찬가지(26,535,096,702,000 = 17,268,806,425,000 + 9,266,290,277,000), 박셀바이오도 마찬가지
  (83,142,583,571 = 4,867,937,672 + 78,274,645,899). 항등식이 두 회사·양쪽 basis 전부에서
  맞아떨어져 basis 필터·라벨·값 추출 전체 경로가 교차검증됐다.

- **col_index(당기)는 날짜 정확매치, 허용오차 불필요로 판명**: instant 는 `ctx.instant ==
  period_end_date`, duration 은 `ctx.end_date == period_end_date` 중 `start_date` 가 가장 이른(=
  가장 긴, 즉 누적) 것 채택 — `HYA`/`FQA` 같은 접미사 문자열을 하드코딩하지 않고 날짜 구조 자체로
  "누적" 을 일반화(설계결론 3). 한화 Q1(FQA=FQQ 값이 우연히 동일, Q1 은 전분기가 없어 누적=단일분기)
  로 이 로직이 접미사 없이도 정확히 동작함을 확인. **허용오차(계획에 있던 "tolerance")는 실측상
  전혀 필요 없었다** — 두 샘플 전부 예외 없이 정확히 일치하는 날짜가 존재했다. col_index=2(전전기)
  는 시도하지 않음 — 유일하게 관측된 3번째 기간 컨텍스트(`BPFY...`, 한화 BS 역할에 2개 fact)가
  실제로는 다른 주석 비교용 값이 role 에 새어든 노이즈였다(전체 facts 대비 극소수, 표준 컬럼이
  아님). col_index=1(전기)은 최선노력으로만 채움 — `_is_loadable()` 이 BS/IS/CF 는 col_index==0 만
  저장하므로 정확도가 적재 결과에 영향을 주지 않는다.

- **weight 는 값 저장에 정말 관여하지 않는다는 것을 실측 재확인, 동시에 항등식 검증엔 필수임도
  확인**: 박셀바이오 CF `영업활동현금흐름`(-5,586,995,010) = `영업으로부터창출된현금흐름`
  (-5,931,095,417) + `이자수취`(+249,435,527) + `법인세환급(납부)`(-94,664,880) 는 weight 를 무시하고
  그대로 더하면 안 맞는다(단순합=-5,776,324,770, 차이 189,329,760). `_cal.xml` 을 실제로 조회해보니
  `IncomeTaxesPaidRefundClassifiedAsOperatingActivities` 의 weight 가 **-1**(나머지는 +1) —
  weight 를 반영해 재계산하면 -5,931,095,417 + 249,435,527 - (-1)×(-94,664,880) = 정확히
  -5,586,995,010 로 맞아떨어진다. 즉 **저장된 fact 값 자체는(weight 적용 여부와 무관하게) 원문
  그대로가 맞고**, weight 는 오직 "부모=Σ(weight×자식)" 항등식을 검증할 때만 필요하다 — Phase 0 §11의
  결론이 실측으로 재확인됐고, Phase 6 항등식 점검이 반드시 calc linkbase weight 를 써야 한다는
  근거가 됐다(단순합으로 검증하면 이런 정상 케이스도 오탐된다).
- **교차 통계 검증**: 한화 CF `기초의 현금및현금성자산`(7,713,355,500,000)이 BS 의 전기(PFY) 현금
  잔액과, `분기말의 현금및현금성자산`(6,886,229,564,000)이 BS 당기(CFY) 현금잔액과 정확히 일치.
  CF 전체 항등식(기초현금 + 영업/투자/재무활동현금흐름 + 환율변동효과 = 기말현금)도 두 샘플 모두
  정확히 성립. IS 도 매출-매출원가=매출총이익 등 소계가 정확히 일치.
- **행 수(둘 다 col0+col1 합계, BS/IS/CF 3문·연결+별도)**: 박셀바이오 132행(별도만), 한화 464행
  (연결+별도). `pytest fin2/tests/` 263 passed(기존 무관 실패 1건 유지). 새 모듈에서 발생한 경고
  0건(파싱 중 뜨는 189건 경고는 전부 기존에 문서화된 `taxonomy_linkbase.py` 의 note-role DAG 노이즈,
  이 파일이 새로 만든 것이 아님).

### Phase 3-6 — SCE(자본변동표) 구조 조사 (2026-08-06, 코드 변경 없음)

두 샘플 zip을 다시 받아(`LegacyDartScraper.fetch_xbrl_zip()` 재현) SCE role의 presentation
tree(D610000/D610005)와 실제 `ComponentsOfEquityAxis` context를 전량 walk했다(레포 미포함,
세션 scratchpad만). 목적: 3-5에서 보류한 "열 축이 기간이 아니라 자본구성요소 계층"이라는
구조를 파악해 추출 설계를 확정할 수 있는지 판단.

**결론: 구조는 명확히 파악됐다. 다만 기존 저장 스키마(`report_lines`)와의 호환을 위해
설계 결정이 하나 더 필요해 이번엔 설계만 정리하고 구현은 보류한다** (아래 "핵심 난제" 참고).

#### 1. 열(자본구성요소) — presentation tree로 정확히 산출 가능, 계층형

`StatementOfChangesInEquityTable` 로케이터의 자식 `ComponentsOfEquityAxis` 서브트리가 곧
열 정의다. 도메인 루트(`EquityMember`, "자본"="총계")부터 DFS order-정렬로 순회하면 그대로
열 순서가 나온다:

- 박셀바이오(별도만): `EquityMember`(총계) → `IssuedCapitalMember`(자본금) →
  `CapitalSurplusMember`(자본잉여금) → `ElementsOfOtherStockholdersEquityMember`(기타자본) →
  `RetainedEarningsMember`(이익잉여금). 5열, 평평한 구조(자식이 자식을 안 가짐).
- 한화 연결: `EquityMember`(총계) → `EquityAttributableToOwnersOfParentMember`(지배지분
  **소계**, 그 아래 `IssuedCapitalMember`/`CapitalSurplusMember`/
  `ElementsOfOtherStockholdersEquityMember`/`OtherComprehensiveIncomeLossAccumulatedAmountMember`/
  `RetainedEarningsMember` 5개 자식) → `NoncontrollingInterestsMember`(비지배지분, 형제).
  8열, **2단 계층**(소계 열이 자기 자식 열들을 거느림 — 기존 HTML 파서의 다단 헤더
  `_build_col_labels`의 ">"join 관례와 개념적으로 동일, 오히려 XBRL 쪽이 추측 없이 정확함).
- 값 조회 규약: `EquityMember`(총계) 열은 context dims==1(basis만, BS/IS/CF와 같은
  `_basis_candidates` 그대로 재사용 가능). 나머지 열은 context dims==2(basis +
  `ComponentsOfEquityAxis`=해당 멤버, 정확히 그 QName)만 채택 — 실측 확인: 한화 연결에서
  같은 축이 주석(하이브리드채권 세부표)에도 재사용돼 멤버 13종 중 6종이 SCE와 무관한
  주석 오염(`The8/9/10ThPrivateUnsecuredConvertibleBondsOf...Member`)이었다. **반드시
  presentation tree에 실제로 걸린 (concept, member) 조합만 채택**해야 한다(3-5의 "tag명
  단독 검색 금지" 원칙이 열 축에도 그대로 적용됨).

#### 2. 행(변동사유) — `StatementOfChangesInEquityLineItems` 서브트리, 기존과 개념 동일

`기초자본`(`EquityAtBeginningOfPeriod`) → `포괄손익`(`ComprehensiveIncome`, 그 아래
당기순이익/기타포괄손익 항목들) → `주식기준보상`/`배당금`/`기타변동` 등 자본거래 항목들 →
`자본`(`Equity`, 기말) 순으로 LineItems 트리를 order-정렬 DFS 순회하면 행이 그대로 나온다.
기존 HTML 파서가 "날짜 라벨 행"(기초/기말)을 별도 규칙(`date_labels_ok=True`)으로 살려야
했던 것과 달리, XBRL은 애초에 `EquityAtBeginningOfPeriod`/`Equity` 자체가 정식 라인아이템
개념이라 특별 취급이 필요 없다.

#### 3. ★핵심 난제 — 기간(당기/전기) 인코딩이 기존 스키마의 "행 안에 날짜 문자열" 관례에 의존

- 각 라인아이템 concept(예: `Equity`=기말자본)은 기간마다 **다른 context**를 가진다 — 당기말
  instant 하나, 전기말 instant 하나(둘 다 같은 concept). BS/IS/CF와 똑같이 "같은 concept,
  다른 날짜 context가 여러 개"인 구조라 겉보기엔 col0/col1 로직을 그대로 쓸 수 있어 보인다.
- 그런데 기존 HTML 기반 SCE 파서(`report_lines.py::_emit_sce_lines`)는 애초에
  `context_fiscal_year=NULL`/`period_kind=NULL`로 저장하고, 기간 구분을 **`label_raw`에
  박힌 실제 날짜 문자열**("2023.12.31(기말자본)")로만 남긴다 — `col_index`는 오직
  자본구성요소 열 위치다. 그리고 `fin2/audit/line_anomaly.py::detect_sce_anomalies()`가
  이 관례에 **직접 의존**한다: `_CLOSE`(정규식 `"기말"`) + `_close_row_year()`(라벨에서
  정규식으로 연도 추출)로 "기말" 행을 찾아 BS의 해당 연도 열과 대조한다.
- 즉 XBRL 추출기가 열=자본구성요소·행=변동사유까지는 정확히 산출해도, **`label_raw`에
  실제 종료일 문자열을 합성해 넣지 않으면** `detect_sce_anomalies()`의 SCE↔BS 교차검증이
  XBRL 유입 행에서 에러 없이 조용히 공백(대조 0건)이 된다 — Gate가 "통과"가 아니라
  "적용 자체가 안 됨"으로 조용히 새는 패턴(참고: `[[layer2-silent-loss-patterns]]`류).
  기간 버킷 자체는 BS/IS/CF의 `_resolve_columns()`를 그대로 재사용 가능(상대적 최신순으로
  당기/전기 판정, `period_end_date` 정확매치가 아니라 "가장 최근"="당기"로 판정해야 함 —
  `EquityAtBeginningOfPeriod`의 instant는 기말일이 아니라 기초일이라 정확매치가 원천적으로
  안 됨).

#### 4. ★★적재 리스크가 BS/IS/CF보다 크다 — `_is_loadable()`이 SCE를 col_index로 안 거른다

`report_lines.py::_is_loadable()`은 BS/IS/CF는 `col_index==0`만 저장하지만 SCE는 전량
저장한다(위 §3 인용, 열축이 기간이 아니므로). 즉 이 설계에서 열/행/기간 판정 중 하나라도
틀리면 **그 오염이 필터 없이 그대로 DB에 들어간다** — BS/IS/CF에서 실수해도 피해가
"최선노력 col1"에 국한됐던 것과 다르다. 구현 시 저장 이전에 항등식 하드 게이트를 강력
권장: 지배지분소계+비지배지분=자본총계(있는 필링만), 기초자본+포괄손익+자본거래=기말자본
(두 샘플 다 이 항등식이 실제로 성립하는지는 아직 값 단위로는 확인 안 함 — 구조만 확인,
다음 단계에서 값 검증 필요).

#### 결정 (2026-08-06, 사용자 확인)

**옵션 A 채택 — SCE도 지금 구현한다.** 위 §1~§4 설계대로:
`label_raw`에 날짜 합성(예: `"자본 (2026-03-31)"`)해 기존 `detect_sce_anomalies()` 정규식과
호환 유지, 열 계층(">"join)은 `col_label`로, 기간 버킷은 BS/IS/CF의 `_resolve_columns()`
재사용(정확매치 아닌 "가장 최근"=당기 판정), 저장 전 항등식 하드 게이트
(지배지분소계+비지배지분=자본총계, 기초자본+포괄손익+자본거래=기말자본) 필수.
→ Phase 3에 **3-7(SCE 구현)** 항목으로 반영, 착수는 별도 명시적 요청 시.

### Phase 3-7 진행 기록 (완료 2026-08-06)

`fin2/extract/report_lines_xbrl.py`에 `_emit_sce_lines()` 신설(기존 BS/IS/CF `_emit_statement_lines()`와
나란히), `extract_report_lines_xbrl()`의 통계 분기에서 SCE를 이 새 함수로 디스패치. 두 샘플 zip을 다시
받아(크기 Phase 0 기록과 정확히 일치) 실제로 파싱·검증했다(레포에는 미포함, 세션 scratchpad만).

- **열**: `ComponentsOfEquityAxis` 로케이터의 domain 자식(들)부터 DFS order-정렬로 순회
  (`_flatten_from()` — `_flatten_preorder()`를 임의 시작 노드로 일반화한 버전). `col_label`은 그 축
  서브트리 안에서만의 조상 라벨 체인(`_col_label_chain()`, Table/LineItems/role-root는 배제) —
  실측: 박셀바이오 5열(평평), 한화 연결 8열(지배지분 소계가 자기 자식 5개를 거느리는 2단 계층), 한화
  별도 6열(평평) — Phase 3-6 §1 기록과 정확히 일치.
- **행**: `StatementOfChangesInEquityLineItems` 서브트리를 같은 방식으로 DFS(`row_flat`).
  `node_role`/`section_path`는 BS/IS/CF와 동일한 함수(`_compute_node_roles`/`_section_path`) 재사용 —
  단 `label_of`는 **행/열 서브트리가 아니라 tree 전체**에서 구해야 한다(행의 조상 체인이 LineItems를
  지나 Table/role-root까지 올라가므로) — 처음엔 서브트리로만 만들어서 `KeyError`가 났다(아래 "실측 중
  발견한 버그" 참고).
- **기간(당기/전기/전전기)**: `_resolve_columns()`(BS/IS/CF, `period_end_date` 정확매치)와
  `_bucket_by_period()`라는 공통 헬퍼를 공유하도록 리팩터(순수 리팩터, BS/IS/CF 동작 불변 —
  pytest 263 그대로 통과 확인). SCE는 **행마다 한 번, 총계열(col0) 후보에서만** 날짜를 최신순으로
  랭킹해 "정본 기간 목록"을 만들고, 그 정본 날짜로 나머지 모든 열의 값을 조회한다(날짜로 직접 매칭,
  열마다 독립적으로 재랭킹하지 않음). `row_order = period_idx * stride + row_index`
  (`stride = len(row_flat)`) — 기간 블록이 절대 겹치지 않게 층으로 쌓는다(HTML 파서의 "당기/전기
  블록이 세로로 두 번 쌓인다"는 것과 같은 효과, 순서는 최신이 먼저).
- **`label_raw` 날짜 합성**: instant 컨텍스트 행에만 날짜 접미사를 붙인다(duration인 흐름 항목은
  원문처럼 그대로 둠). concept이 정확히 `ifrs-full:Equity`(기말자본)일 때만 `"(기말)"` 마커를
  붙여 `detect_sce_anomalies()`의 `기말` 정규식과 호환(그 함수가 실제로 찾는 유일한 마커).
  `ifrs-full:EquityAtBeginningOfPeriod`(기초자본)에도 대칭성을 위해 `"(기초)"`를 붙였으나 이건
  호환에 필수는 아님.
- **저장 전 항등식 하드 게이트**: 계획대로 "지배지분소계+비지배지분=자본총계" 유형의 **열 rollup
  체크**(`_check_sce_column_rollup()` — 부모 열 값과 직계 자식 열 값들의 합을 행·기간마다 비교, 상대오차
  0.1% 초과 시 `logger.warning`만, 저장을 막거나 값을 고치지 않음 — `detect_sce_anomalies()`가 이미
  저장 후 SCE↔BS 대조를 값 제안까지 포함해서 하고 있어 그 역할과 안 겹치게 이건 "우리 파서 배선 버그
  감지용"으로만 씀). **"기초자본+포괄손익+자본거래=기말자본"(행 rollup)은 계획과 달리 이번엔 구현
  안 함** — 실측으로 이유가 드러났다(아래 "실측 중 발견한 버그·판단" 참고): 단순합으로는 두 샘플
  전부 안 맞고(가중치 없이는 배당금처럼 "표시는 양수지만 자본을 줄이는" 항목을 못 구분), Phase 0
  §11처럼 `_cal.xml`의 weight가 SCE role에도 있는지가 먼저 확인돼야 하는데 이번 조사에서 그 확인을
  안 했다(BS/CF는 Phase 0에서 이미 확인됨). R9 원칙상 넘겨짚지 않고 **명시적으로 보류**(Phase 6 항등식
  점검 항목으로 이월 — 거기서 `_cal.xml`을 SCE에도 로드해 weight 반영 여부부터 확인).

**검증(두 샘플 재다운로드해 실파싱, 회귀 없음 확인)**:
- `pytest fin2/tests/` 263 passed(기존 무관 실패 1건 유지, 이번 변경과 무관).
- SCE 행 수: 박셀바이오 별도 37행, 한화 연결 115행 + 별도 109행(=224행).
- 열 rollup 체크(`_check_sce_column_rollup`) **경고 0건**(양 샘플·양 basis 전부) — 수동 재확인으로
  박셀바이오 4개 행에서 col0==sum(col1..4) 4/4 일치 재확인.
- 값 대조: 박셀바이오 SCE 기말(col0, 2024-06-30)=78,274,645,899, 한화 연결 SCE
  기말(col0, 2026-03-31)=17,440,065,127,000, 한화 별도=9,266,290,277,000 — 전부 Phase 0 §7/3-5의
  BS 자본총계 기록과 정확히 일치(같은 개념, 다른 재무제표, 같은 값 — 강한 교차검증).
  한화 연결 지배지분(9,958,578,459,000)+비지배지분(7,481,486,668,000)=17,440,065,127,000 —
  총계와 정확히 일치.

**실측 중 발견한 버그·판단(구현하며 잡음, 계획 문서엔 없던 것)**:
1. **`label_of` 범위 버그**: 처음엔 행/열 서브트리 노드만으로 `label_of`를 만들었다가
   `_section_path()`가 LineItems 밖(Table/role-root)의 조상을 찾다 `KeyError`. `tree.nodes` 전체에서
   라벨을 구하도록 수정(BS/IS/CF `_emit_statement_lines()`가 원래 하던 방식과 통일).
2. **★기간 정렬 버그(값 오염 직행 사례, 고쳐서 다행)**: 최초 구현은 열마다 독립적으로
   `_resolve_sce_periods()`(랭킹 함수, 결국 폐기)를 불러 "최신순=0"을 매겼다. 그런데 특정 열(예:
   비지배지분)이 일부 기간에 값이 없으면 그 열만의 랭킹이 밀려서, 같은 `row_order`(=같은 "기간
   블록"으로 간주됨)에 실제로는 **다른 날짜의 값들이 섞였다** — 실측: `_check_sce_column_rollup`이
   "row_order=17: parent=83,493,267,971(2023-06-30 값) != sum(children)=18,696,472,616(다른 기간
   합)" 같은 거대한 불일치를 잡아냈다(하드 게이트가 실제로 제 역할을 함). 총계열(col0)에서만 정본
   기간 목록을 뽑고 나머지 열은 그 날짜로 직접 조회하도록 다시 설계해서 해결 — 재검증 결과 경고
   0건. **이 버그는 저장 전 자체검증(열 rollup 게이트)이 없었으면 조용히 DB로 들어갔을 뻔한
   사례**라 §4의 "하드 게이트 강력 권장"이 실제로 유효했음을 실측으로 보여준다.
3. **행 rollup 단순합은 실제로 틀린다는 것도 실측 확인**(3번째 항목과 별개, 위 "저장 전 항등식
   하드 게이트" 문단 참고) — 한화 연차배당이 원문엔 양수로 표시되지만 자본을 줄이는 항목이라
   가중치 없는 단순합은 기초+변동 합이 기말보다 정확히 배당액의 2배만큼 크게 나온다(연결
   820,440,670,000 = 2×410,220,335,000, 별도 720,283,032,000 = 2×360,141,516,000 — 정확히
   일치). 구현하지 않기로 한 판단이 맞았다는 근거.

### Phase 3 설계에 주는 결론 (착수 시 그대로 반영)

1. 다운로더: 1단계(`_get_view_params`) + 1회 GET(`ifrs.do`)만으로 충분, `_fetch_pdf()`의 2단계 존재확인 패턴 불필요.
2. basis(연결/별도): context의 `ConsolidatedAndSeparateFinancialStatementsAxis` 멤버로 판정, 별도 파일 처리 로직 불필요. 연결이 아예 없는 필링(소형사)도 정상 케이스로 처리.
3. col_index/period_kind: context ID 명명 패턴(CFY/PFY/BPFY + d/e + 보고유형코드)을 1차 힌트로 파싱하되, **최종 판정은 실제 `<xbrli:period>` 날짜값을 `Filing.period_end_date`와 대조**해서 확정(하드코딩 금지, 필요시 필링마다 새 보고유형코드 나올 수 있음을 전제).
4. role→statement 매핑: roleURI 숫자 코드가 아니라 `.xsd`의 `link:definition` 한글 텍스트로 매핑(버전 불변). 본문 4역할(BS/IS/CF/SCE, 연결+별도 각각 최대 8개)만 우선 지원, 주석(D8/U8 계열)은 계획대로 1차 범위 밖.
5. **fact 추출은 반드시 role별 presentation 트리를 먼저 워크한 뒤, 그 트리에 실제로 걸린 (element, context) 쌍만 채택** — tag명 단독 검색 절대 금지(같은 QName이 주석에도 반복 태깅돼 총계 아닌 값이 섞여 들어옴, 항등식 깨짐의 가장 유력한 원인이 될 것).
6. order는 float로 정렬.
7. label: `preferredLabel` 속성이 있으면 그 role 우선 조회 → 없으면 표준 label → 한글 없으면 en 폴백.
8. calculation linkbase(weight)는 값 저장에 직접 관여 안 함(표시값 그대로 저장), 항등식 자체검증(Gate) 용도로만 사용.
9. sanitize 불필요, `lxml.etree.parse()` 직접 사용.
10. 두 샘플(소형·별도만 / 대형·연결+별도) 다 사이즈·구조 편차가 커서(87KB vs 26MB), 파서 성능/메모리 가정을 소형 샘플만으로 확정하지 말 것 — 대형 필링(한화류) 기준으로도 검증 필요(Phase 6에 반영됨).
