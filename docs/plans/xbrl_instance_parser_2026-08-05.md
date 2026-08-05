# 새 파서 — DART 표준 XBRL 원문(ifrs.do) 지원

## Context (배경 및 목표)

DART는 필링마다 두 가지 다른 원본을 따로 제공한다:
1. **공시서류원본 XML**(`document.xml`) — DART 독자 서식(`<TABLE>/<TD>`, 임베디드 `<TE ACODE="ifrs-full_...">`). 기존 `parser/xml/dart_xml_parser.py` + `fin2/extract/report_lines.py`가 읽는 바로 그 포맷.
2. **재무제표 원문 XBRL**(`/pdf/download/ifrs.do?rcp_no=...&dcm_no=...&lang=ko`) — 표준 XBRL instance(`.xbrl`) + schema(`.xsd`) + linkbase(`_def/_cal/_pre/_lab-ko/_lab-en.xml`) zip. **이 프로젝트 어디에도 이 엔드포인트를 건드리는 코드가 없다.**

2026-08-05 심야 조사(`docs/qa/handoff_xml_parse_failure_xbrl_finding_2026-08-05.md`)에서, 활성기업 2015+ 범위의 "완전 잔여공백"(어떤 데이터도 못 채운 필링) 전수 6건 중 5건이 이 XBRL 원문을 갖고 있음을 확인했다: 박셀바이오(`20250828000534`, 2024H1), 웰킵스하이텍×3(`20191118000002`/`20191119000045`/`20191119000058`, 2019Q3), 한화에어로스페이스(`20260513000860`, 2026Q1). 자비스(`20181114002329`)는 XBRL도 없어 범위 밖.

당시엔 "복구 가능 5건뿐, 새 파서 투자 대비 효과 낮음"으로 판단해 트랙을 종료했으나, **한화에어로스페이스가 2026 Q1 — 최근·활성 대형 기업**이라는 점에서 이 패턴(document.xml 없음+XBRL 있음)이 과거 잔재가 아니라 앞으로도 재발할 수 있다고 보고, 사용자가 선제적으로 파서를 구축하기로 결정했다(2026-08-05). 목표는 5건 백필이 아니라 **이 패턴이 재발할 때 데일리 파이프라인이 자동으로 잡아내는 상시 지원 체계**를 만드는 것.

## 범위와 현실적 난이도

이건 "폴백 하나 추가"가 아니라 **새 XBRL 파서를 처음부터 만드는 규모**다 (프로젝트에 XBRL 처리 라이브러리 없음 — `requirements.txt`엔 `lxml`뿐, `arelle`/`xbrl` 계열 미설치, 기존 `fin2/extract/xbrl.py`는 이름과 달리 `document.xml` 안의 DART 자체 `TE[@ACODE]` 셀 추출기라 무관). context/dimension 해석, presentation linkbase 트리 워크(행 순서·깊이·section_path), label linkbase(한글 라벨), unit/decimals 처리, 필요시 calculation linkbase 부호 해석까지 — 기존 `document.xml` 파서 하나 만드는 것과 비슷한 규모의 작업. 대략 **1.5~2주 분량**(Phase 0 조사 0.5~1일, 파서 핵심 3~5일, 기간/컨텍스트 매칭 1~2일, 파이프라인 배선 1일, 백필+검증 1일)으로 추정.

**가장 큰 리스크**: 검증 가능한 샘플이 5~6건뿐이라, presentation linkbase 기반 구조가 기존 `document.xml` 파서와 얼마나 다른 결과를 낼지(특히 depth/row_order/section_path 충실도, 그리고 부호 규약 — `_cal.xml`의 weight 적용 필요 여부) 확신하기 어렵다. Phase 0에서 실제 샘플을 열어보고 답을 확정하기 전까지는 파서 로직을 쓰지 않는다(R9: 짐작 금지, 원문 대조).

## Phase 0 — 실제 샘플 확보·조사 (파서 코드 작성 전 필수)

대상: 박셀바이오(`20250828000534`).

1. `LegacyDartScraper._get_view_params("20250828000534")`(`collector/legacy_downloader.py:180-256`) 재사용해 `dcm_no` + 세션 쿠키 확보 — 재구현 금지.
2. 같은 `httpx.Client`로 `https://dart.fss.or.kr/pdf/download/ifrs.do?rcp_no=...&dcm_no=...&lang=ko` 요청 — `_fetch_pdf()`(`legacy_downloader.py:128-178`)의 Referer 헤더 패턴을 따름. 한 번의 GET으로 zip이 바로 오는지, 아니면 `/pdf/download/main.do`→실제 다운로드 두 단계가 필요한지 확인(매직바이트 `PK\x03\x04` vs HTML 확인).
3. unzip 후 파일 목록 확인(`.xbrl`/`.xsd`/`_def/_cal/_pre/_lab-ko/_lab-en.xml`).
4. `.xbrl` instance 열어서 다음을 **실측**으로 확정:
   - 루트 네임스페이스/taxonomy(`ifrs-full:` vs `dart:` 확장 프리픽스)
   - 연결/별도 구분 방식 — context의 dimension/segment 멤버인지, 아예 별도 instance 파일 2개인지
   - context들의 실제 period(instant/duration)를 필링의 `Filing.period_end_date`와 대조해 col_index 0/1/2 매핑 방식과 허용 오차 확정
   - `_pre.xml`의 roleURI들을 나열해 BS/IS/CF/SCE/note로 매핑
   - `_lab-ko.xml`에서 `xml:lang="ko"` + DART가 쓰는 표준 라벨 role 확인
   - `_cal.xml`의 weight 속성으로 부호 반전이 필요한지, 아니면 값이 이미 표시된 대로 저장돼 있는지 — 가능하면 `document.xml`도 있는 유사 taxonomy 필링과 대조
   - `parser.xml.dart_xml_parser.sanitize_dart_xml()`/`_parse_xml_file()`(`parser/xml/dart_xml_parser.py:260,271`)를 그대로 XBRL instance에 먹여도 되는지, 아니면 순수 `lxml.etree.parse`가 나은지

이 단계의 답이 나오기 전엔 모듈 분리(연결/별도를 한 패스로 처리할지, calculation linkbase 반영이 실제로 필요한지 등) 세부 설계를 확정하지 않는다.

## 모듈/파일 구성

**다운로더** (`dart.fss.or.kr` 웹 스크래핑 확장 — `legacy_downloader.py` 옆):
- `collector/legacy_downloader.py`: `LegacyDartScraper._fetch_xbrl_instance(rcept_no, dcm_no)` 신설(`_fetch_pdf()` 패턴 따름, PDF `%PDF` 대신 zip `PK\x03\x04` 매직바이트 확인) + `fetch_xbrl_zip(rcept_no)` 공개 메서드(내부에서 `_get_view_params` 호출).
- `collector/downloader.py`: `_download_one()`의 `status_code == "014"` 분기(현재 `:368-370`, 바로 `_try_legacy_fallback()` 호출)에서, **XBRL 우선 시도**를 위해 `_try_legacy_fallback()` 호출 전에 `_try_xbrl_instance_fallback()`을 신설해 먼저 시도 — 성공 시 zip 저장(`_build_file_path()` + tmp-then-move 패턴, `file_type='xbrl_zip'`, `parser_track='XBRL_INSTANCE'`, `dcm_no` 저장), 실패/부재 시 기존 PDF 폴백으로 자연스럽게 이어짐(기존 동작 불변).
- `_mark_completed()`(`:504-522`)에 `dcm_no` 저장을 위한 파라미터 추가.

**파서** (새 포맷이라 `parser/xml/`과 나란히 새 패키지):
- `parser/xbrl_instance/instance_parser.py` — `.xbrl` instance 로드, context/unit/fact 구조화 파싱.
- `parser/xbrl_instance/taxonomy_linkbase.py` — `_pre.xml`(row_order/depth/section_path) · `_cal.xml`(부호, Phase 0에서 필요 확인시만) · `_lab-ko.xml`/`_lab-en.xml`(라벨) 로딩.
- `parser/xbrl_instance/role_map.py` — roleURI → statement(BS/IS/CF/SCE/note) 매핑표. 필러마다 새 role이 나올 수 있어 확장하기 쉽게 독립 모듈로 유지.
- `fin2/extract/report_lines_xbrl.py` — layer2 진입점. `extract_report_lines_xbrl(zip_path, *, rcept_no, corp_code, report_fiscal_year, report_fiscal_period, include_notes=False) -> list[ReportLineRow]`. 기존 `ReportLineRow`(`fin2/extract/report_lines.py:107`)를 그대로 반환해 `store_report_lines()`/`store_report_tables()`/`store_note_lines()`(`:858,902,954`)에 그대로 넘긴다 — 새 DB 쓰기 코드를 만들지 않는다(R1 계층2 불변식 준수).

**데일리 동기화** (새 형제 모듈 — 기존 `note_lines_sync.py`의 `_TARGETS_SQL`이 `dt.file_type='xml'`로 하드코딩돼(`collector/note_lines_sync.py:38`) 있어 그대로는 이 새 포맷을 못 잡음):
- `collector/xbrl_instance_lines_sync.py` — `note_lines_sync.py`와 구조 동일하되 `file_type='xbrl_zip'` 대상, `extract_report_lines_xbrl()` 호출. 저장 함수는 동일하게 재사용.

## 데이터 모델 변경

`collector/db.py::_run_migrations()`의 기존 idiom 재사용(예: `:299` `gate_a_status` 추가 사례와 동일 패턴, id-기반 `schema_migrations` 이력 관리):
```python
("2026_08_download_tasks_dcm_no",
 "ALTER TABLE download_tasks ADD COLUMN IF NOT EXISTS dcm_no VARCHAR(20)"),
("2026_08_download_tasks_file_type_widen",
 "ALTER TABLE download_tasks ALTER COLUMN file_type TYPE VARCHAR(10)"),
```
- `collector/models.py`의 `DownloadTask`(`:100-138`)에 `dcm_no = Column(String(20), ...)` 추가, `file_type`을 `String(5)→String(10)`으로 확장(`'xbrl_zip'`이 5자를 초과함 — 현재 컬럼 확인함, `:112`), `parser_track`(`String(15)`, `:126`)은 `'XBRL_INSTANCE'`가 이미 들어감.
- `dcm_no`를 DB에 영구 저장하는 이유: 매번 재파생하면 네트워크 왕복+2초 스로틀(`legacy_downloader.py:36`)이 들고, 백필/검증/재파싱 시 재사용된다.

## 파이프라인 배선 (필수 절차 3층 — `docs/runbook_new_parser_pipeline_integration.md`)

1. **데일리 배선(두 call site)**: `scripts/collect_new.py`에 `_sync_xbrl_instance_lines(corps)` 래퍼 신설(`_sync_layer2_lines()` 형태 그대로, 비치명 `try/except`), 기존 `_sync_layer2_lines(affected)` 호출 바로 뒤에 두 곳 모두 추가 — `collect_new.py:638`(재개 branch)과 `:743`(메인 경로). 이 6건은 현재 `report_lines` 0건이라 기존 `sync_layer2_lines`(`file_type='xml'` 대상)와 겹칠 일이 없음(중복 카운팅 가드 불필요, 다만 구현 시 재확인).
2. **소급 백필(수동)**: 5건(박셀바이오·웰킵스하이텍×3·한화에어로스페이스)의 `download_tasks.status`를 `pending`으로 리셋 → `run_downloads(only_corp_codes=[...])` → `sync_xbrl_instance_lines(corps=[...], recheck=True)` 원샷 스크립트. 5건뿐이라 launchd/장시간잡 불필요, foreground로 충분. `dart.fss.or.kr` 웹 엔드포인트라 OpenDART API 40,000/일 쿼터와 무관(Phase 0에서 실측 확인). 백필 후 이 6건에 대해 layer3(std_v2/std_v3) 재표준화가 필요한지 `needs_standardize_corps()` 조건으로 확인 후 필요시 타겟 재실행.
3. **검증**:
   - `fin2/tests/test_xbrl_instance.py`(신설, 기존 무관한 `test_xbrl.py`와 이름 구분) — 박셀바이오 실 샘플 기반 fixture, 주요 계정(자산총계/매출/자본총계 등) 하드코딩 대조, presentation 구조 충실도·라벨 해석·instant/duration 판정 검증.
   - 박셀바이오·한화에어로스페이스 각각 3~5개 값을 DART 웹뷰어 렌더링과 수동 대조(R9).
   - Gate B 무영향 확인 — 이 6건은 기존 0행이라 다른 필링 회귀 없이 "무데이터→pass/fail"로만 이동해야 함.

## 검증 방법 요약

- `PYTHONPATH=. .venv/bin/python -m pytest fin2/tests/test_xbrl_instance.py -v`
- 백필 스크립트 실행 후 `report_lines`/`report_tables` 6건 신규 행 확인, DART 웹뷰어 대조
- `run_dq_gate`/`face_audit` 전/후 비교로 기존 필링 무영향 확인
- `scripts/collect_new.py --standardize-only`와 메인 경로 양쪽에서 새 sync 함수가 실제로 호출되는지 로그로 확인(두 call site 배선 검증)

## 핵심 파일

- `collector/legacy_downloader.py`, `collector/downloader.py` — 다운로더 확장
- `collector/models.py`, `collector/db.py` — 스키마 변경
- `parser/xbrl_instance/*`(신설) — 파서 핵심
- `fin2/extract/report_lines.py` — 재사용할 `ReportLineRow`/저장 함수
- `collector/xbrl_instance_lines_sync.py`(신설), `scripts/collect_new.py` — 데일리 배선
- `fin2/tests/test_xbrl_instance.py`(신설) — 회귀 테스트

## 상태

계획 확정(2026-08-05, 사용자 검토 완료). 세부 실행 항목은 [`xbrl_instance_parser_todo_2026-08-05.md`](xbrl_instance_parser_todo_2026-08-05.md) 참고. **구현은 아직 시작하지 않음** — 다음 세션에서 Phase 0부터 착수.
