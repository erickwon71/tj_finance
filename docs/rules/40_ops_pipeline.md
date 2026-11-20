# 운영 — 수집 대상·파이프라인 배선·재적재 규약

> 이 파일은 `docs/PARSING_RULES.md` 에서 **내용을 바꾸지 않고 옮긴** 절들이다(2026-10-12, `scripts/split_parsing_rules.py`). 규칙 번호·본문은 그대로이고, 분류 기준은 [판정 순서](../plans/parsing_rules_split_2026-10-11.md#분류-기준--판정-순서-사용자-확정-2026-10-11). 새 규칙도 같은 판정 순서로 파일을 고르고 머리에 `적용 계층:` 을 적는다.
> 규칙 문서 수정은 **main 과 camp_err_review 에서만** 한다(사용자 결정 2026-10-11).

---

## R7. 유니버스

> **상태** 유효 · **적용 계층** 운영

**규칙** — 현재 시점 KOSPI/KOSDAQ 상장 **보통주**, 개인이 거래 가능한 기업.
**국내 상장 외국기업 제외** — 식별 = `stock_code` 가 **'9' 로 시작**(900xxx 직상장·950xxx DR/원주).

**근거** — `CLAUDE.md` 개발 목표. 사용자 결정 2026-07-19.
`collector/corp_collector.py:_is_foreign_stock()` — sync 후보 필터 양쪽 브랜치에 적용.

**어기면** — 서식이 이질적이라 파싱 정합이 낮다(로스웰 73%). 기업리스트 갱신 때마다 재유입된다.

---

## R8. 새 파서/로더 추가 3층 (자동 반영 안 됨)

> **상태** 유효 · **적용 계층** 운영

**규칙** — 파싱·적재를 새로 추가하면 **자동으로 전부 반영되지 않는다.** 세 가지를 각각 챙긴다.

1. **데일리 배선** — `scripts/collect_new.py` 의 **두 call site**(메인 + 재개 경로) 모두.
2. **소급 백필** — 과거분은 자동 재파싱되지 않는다. 별도 전수 실행.
3. **검증** — 회귀 테스트 + 원문 대조 + 기존 게이트 무영향.

**근거** — `docs/runbook_new_parser_pipeline_integration.md`(체크리스트 A/B/C), `CLAUDE.md`.

**자주 잊는 것** — 두 call site 모두 배선 / 소급 백필은 수동 /
**재개 플래그가 신규 항목을 못 본다**(예: `--skip-existing` 은 테이블 존재만 보므로 신규 metric
백필에 쓰면 전 기업이 스킵된다 → `--skip-catalog-existing` 신설).

---

## R82. Category C(fy1999~2003 절단 복구) 배치 경로 — HTML→PDF T1/T2/T3

> **상태** 유효 · **적용 계층** 운영
조정 배선 완료

`collector/pdf_lines_sync.py::recover_one()`가 PDF만 파싱하던 옛 방식 대신
`fin2/extract/reconcile.py::reconcile()`(HTML→PDF T1/T2/T3 조정, §8-8~§8-11)
을 쓰도록 바뀌었다. ★이건 `scripts/collect_new.py` 데일리 두 call site 배선이
아니다(그건 XBRL 원문이 있는 현재 필링용, 무관) — `sync_pdf_recovery()`는
Category C(fy1999~2003 절단 복구, 6,598건 population) 전용 독립 배치 경로고,
Track C 93건은 이 population 의 부분집합이다.

basis별 decision 이 "html"/"pdf"(자동채택)인 facts 만 report_lines 로 변환,
"unresolved"는 제외하고 `report_recon_candidates` 리뷰 큐에 적재(`persist_
unresolved()`). `facts_to_report_lines()`의 `unit_source`도 하드코딩 "pdf"
대신 `source_format`("html"/"pdf")을 그대로 써서 값의 출처를 report_lines
에 남긴다. `sync_pdf_recovery()` 카운터도 basis별(`bases_html`/`bases_pdf`/
`bases_unresolved`)로 재정의. ★`store_report_lines()`가 rcept 단위 무조건
delete-then-insert라 `lines`가 빈 리스트일 때 호출하면 delete 만 되고 이전
데이터가 지워질 위험 — 옛 코드에 있던 `if lines:` 가드 유지 확인.

테스트: `fin2/tests/test_pdf_lines_sync.py` 5개 신설(순수 로직, `reconcile()`
mock). `pytest fin2/tests/ tests/` 834 passed(무관 기존실패 1건 그대로, 회귀0).

라이브 스모크(실제 미복구 후보 3건, 진짜 DB write): DB증권·일성건설·제일기획
각 1건 — `{'candidates': 3, 'bases_html': 3, 'bases_pdf': 0, 'bases_
unresolved': 3, 'rows': 329, 'dq_rows': 3, 'errors': 0}`. 별도(separate) 3건
전부 `unit_source='html'`로 BS/IS/CF 정상저장, 연결(consolidated) 3건 전부
report_lines 미저장(의도) 대신 `report_recon_candidates` 정확 적재(제일기획
T3/T3, DB증권·일성건설 T2/T2 — 연결재무제표 자체가 없는 정상케이스).
`dq_assertions.py` WARN 2→5(신규 3건 정확 반영), ERROR 그대로 0.

**남은 것**: 나머지 Category C 후보(93건 잔여 포함) 전체를 이 경로로 실제
돌리는 소급 백필은 별도 단계(런북 원칙) — 미착수, 별도 지시 대기.

## R96. `collector/downloader.py::_pick_best_file_by_size()` — DART `document.xml`

> **상태** 유효 · **적용 계층** 운영
ZIP에 xml이 여러 개(본문+첨부)일 때 "가장 큰 파일" 휴리스틱이 첨부(감사보고서)를
본문으로 오채택 (2026-09-12)

**배경**: R95 조사 중 사용자가 별도로 큐레이션해둔 "0행" 표본 9건("한국화장품제조
같은 list")을 검토하던 중 발견. 이 중 6건(웰킵스하이텍·대한방직·자비스·한국화장품
제조·파세코·스모트로닉)은 **원본 필링 자체가 재무제표 첨부를 누락**했다가 정정본
에서 보완된, 파서와 무관한 정상 케이스로 확인됐다(사용자 확인 + 정정본 문서구조
직접 대조). 나머지 2건(양지사 `20150930000130`, 티로보틱스 `20180402000209`)은
**정정본 자체가 없는데도** 0행이었다 — DART 웹뷰어로 직접 열어보면 "본문문서선택"에
멀쩡히 "사업보고서"가 있는데, 로컬 `raw_report`엔 `<DOCUMENT-NAME>감사보고서</
DOCUMENT-NAME>`인 **첨부문서**가 저장돼 있었다.

**근본원인**: DART `document.xml` API가 반환하는 ZIP은 본문·첨부를 **여러 개의
개별 XML 파일**로 담아 보낸다 — 파일명 규칙은 접미사 없는 `{접수번호}.xml`=본문,
`_{ACODE}` 접미사(예 `_00760`=감사보고서)=첨부. `_pick_best_file_by_size()`는
`.xml`이 여러 개면 **이름을 보지 않고 바이트가 제일 큰 파일을 무조건 선택**했다
(`_PICK_LARGEST_EXTS`). 대부분은 본문(사업보고서)이 제일 커서 문제가 안 되지만,
이 두 건은 **첨부(외부감사인이 작성한 감사보고서 — 재무제표+주석 전문 포함이라
본문보다 큼)가 더 커서** 크기 비교가 뒤집혔다. 실측(라이브 재요청으로 ZIP 내 파일
크기 직접 대조):
- 양지사: 본문 342,379B vs 첨부(`_00760`) 354,948B — 첨부가 3.7% 더 큼
- 티로보틱스: 본문 313,936B vs 첨부(`_00760`) 503,797B — 첨부가 60% 더 큼

파서(`assign_tables_to_dart_sections`)는 "2.연결재무제표"/"4.재무제표" 섹션이
없다고 정직하게 판정했을 뿐이다 — 잘못은 그 앞 단계(콜렉터가 잘못된 파일을 준 것)
에 있었다.

**수정**: `.xml`/`.xbrl` 후보가 2개 이상일 때, 파일명이 정확히 `{접수번호}.xml`
(첨부 접미사 없음)인 것이 있으면 크기 비교보다 그것을 우선 채택(`_pick_body_by_
filename()` 신설). 없으면(구형/미확인 명명) 기존 "가장 큰 파일" 동작 그대로
폴백 — R6 원칙, 모르는 모양이면 확장하지 않는다.

**검증**:
- 신규 유닛테스트(`tests/test_downloader_body_vs_attachment_r96.py`) 4건: 첨부가
  더 커도 파일명으로 본문 정확히 선택 · 이름 매치 실패시 기존 크기폴백 유지 ·
  xml 1개뿐이면 무변경 · 선행 `/` 유무 무관하게 매치.
- 라이브 재다운로드로 실제 두 파일 교체 확인(수정된 함수가 정확히 본문을 선택함을
  직접 확인) → `extract_report_lines()` 재실행: 양지사 0→587행(BS/CF/IS/SCE),
  티로보틱스 0→453행(BS/IS/SCE). 자산총계=부채총계+자본총계 항등식 둘 다 성립
  (양지사 82,959,399,402원 정확히 일치, 티로보틱스 43,378,342,172≈173원 — 레거시
  K-GAAP 반올림 1원차, 정상범위).
- `pytest tests/ fin2/tests/` 978 passed(974 대비 +4 신규, 기존 무관 실패 2건
  그대로).

**미조치**: 이 두 건은 즉석에서 원인을 확인하며 바로 재다운로드+재적재로 해결했다
(임시 스크립트, 정식 배치 아님). `_pick_best_file_by_size()`가 이제부터 새로
받는 모든 필링에 자동 적용되지만, **과거에 이미 이 버그로 잘못 저장된 다른 필링이
더 있는지 전사 census는 안 했다** — "xml이 여러 개인 ZIP에서 첨부가 본문보다
컸던 사례"가 이 2건 말고 또 있을지는 미확인. 필요하면 `download_tasks`에 저장된
파일의 `DOCUMENT-NAME` 태그를 전수 스캔해 "감사보고서"/"연결감사보고서" 등 본문이
아닌 문서가 `file_type='xml'`로 저장된 건을 찾는 방식으로 census 가능(다음 세션
후보).

**★전사 census 실행 결과(2026-09-12, 같은 날 후속)**: `scripts/census_r96_body_
attachment_swap_2026-09-12.py`로 fiscal_year>=2011(2011 이전은 별개의 레거시
인코딩 손상 이슈가 있어 제외 — 아래 참고) × report_type IN (annual/half/quarter)
× file_type='xml' 132,913건 전수 스캔(SD카드 미러에서 `DOCUMENT-NAME` 태그만
읽음, `[[feedback-bulk-read-use-sdcard]]`). 결과: **486건이 본문 키워드
(사업/반기/분기보고서) 아님**(감사보고서 250 · 연결감사보고서 235 · 기타 1) →
NAS 원본과 직접 대조해 이미 해결된 2건(양지사·티로보틱스) 제외 **484건이 여전히
NAS에도 잘못된 파일로 남아있음** 확정(진짜 미해결, 353개사). report_type별
483 annual · 1 half(반기·분기는 첨부가 "검토보고서"라 이 패턴에 거의 안 걸림 —
감사보고서는 사업보고서 필수첨부라 annual에 집중). fiscal_year 분포는 2011~2013에
편중(161·74·50건, 오래된 필링일수록 첨부가 본문보다 커지는 경우가 많았던 것으로
추정) 하지만 2025까지 전 연도에 소수씩 존재. 목록: `manual_review/
_r96_census_2026-09-12/still_wrong_on_nas.csv`(rcept_no·corp_code·report_type·
fiscal_year·SD/NAS 각각의 doc_name·DART링크·file_path).

**미조치(갱신)**: 484건 재다운로드(수정된 `_pick_best_file_by_size()`로 자동 본문
채택)+`report_lines` 재적재 캠페인은 아직 미실행 — 규모(353개사)상 별도 세션에서
계획 후 진행 필요. 2011년 이전(레거시 인코딩 손상 구간)은 이 census에서 제외돼
있어 미확인 상태로 남음(별도 조사 필요, 단 그 구간은 이 census 스크립트의 방식
그대로는 안 됨 — 파일 자체 인코딩 선언과 실제 바이트가 어긋나는 별개 문제라 전처리
방식부터 다시 설계해야 함).

**★재다운로드 실행 결과(2026-09-12, 같은 날 후속 — 사용자 지시로 즉시 진행)**:
`scripts/redownload_r96_body_attachment_swap_2026-09-12.py`로 484건 전부
`_download_one()`(수정된 `_pick_best_file_by_size()` 포함)로 재다운로드:
- **218건 — 진짜 R96 버그였음, 수정 확인**: ZIP 안에 본문 xml이 실제로 존재했는데
  기존 크기비교 로직이 첨부를 골랐던 것 — 파일명 매치로 본문을 정확히 재선택,
  각 파일 재다운로드 직후 `<DOCUMENT-NAME>` 재확인까지 완료.
- **266건 — 다른 원인, 버그 아님**: 재다운로드해도 여전히 감사보고서/연결감사보고서만
  나옴 → ZIP 안에 xml 후보가 **애초에 1개뿐**(본문 자체가 DART document.xml API
  응답에 없음, R96 필터가 손댈 여지가 없음). 형제필링(같은 corp+fiscal_year+
  fiscal_period) 검산 결과 **266/266 전부** 정정본에 `is_final=True`+실데이터가
  이미 있어 `[[held-zero-line-filing-triage-sibling-check-2026-09-12]]`와 같은
  패턴으로 확정(추가 조치 불필요 — 원본은 원래 본문없이 정상, 정정본이 진짜
  데이터).
- 실패 0건. `download_tasks.completed_at`이 이번엔 `_mark_completed()`로
  정상 갱신되어(부록1의 갭 재발 안 함) `scripts/sync_storage_mirror.py`
  증분동기화로 484건 전부 SD에 반영됨(90MB 전송, 43초). 원래 알려진 2건(양지사·
  티로보틱스, 6월에 수동 수정된 건 — 이번 484건 목록에는 없음)은 `completed_at`이
  그때 갱신 안 된 채 남아있어 이번 sync로도 안 잡혔으나, 수동으로 NAS→SD 직접
  복사해 마무리(SD/NAS 완전 일치 확인).
- **결론: R96 버그로 인한 실제 오적재는 218건 전부 해결. 나머지는 전부 별개
  현상(본문 자체 없음, 정정본으로 이미 커버됨)이라 조치 불필요.**
- `report_lines`/`report_tables` 재적재는 사용자 지시대로 미실행(진행 중인 전사
  재적재 `scripts/reload_report_lines_2015plus_2026-09-12.py` 완료 후 별도 진행
  예정) — 파일만 고쳐진 상태.

---

## R103. `collector/downloader.py` — 정기보고서가 접수 당시 PDF만 있고 표준파일

> **상태** 유효 · **적용 계층** 운영
(XML/XBRL)은 나중에 등록되는 경우, "완료"로 마감되어 재확인이 없었음 (2026-09-13)

**배경**: 2015+ 항목수 분포 리포트 작성 중 발견한 결측 8건 중 5건(2026 반기보고서,
2026-08-14 접수)이 `download_tasks.file_type='pdf'`였다. 사용자 질문("XML은 없고
PDF만 있다는 거야?")에 답하려고 DART document.xml API를 **지금 다시** 조회해보니
5건 다 XML이 이미 올라와 있었다(나머지 2건은 지금도 014 — `[첨부정정]`이라 본문
재발행 자체가 없는 것으로 보임, 별개 사유).

**원인**: `_download_one()`은 ZIP에서 고른 `best` 파일이 무슨 확장자든 일단
받으면 `_mark_completed()`로 무조건 완료 처리한다. 회사가 사람이 읽는 서식(PDF)을
먼저 내고 표준파일(XBRL)은 며칠~몇 주 뒤에 뒤늦게 올리는 관행이 있는데(이미 알려진
[014](document.xml 자체가 없음) 케이스와 같은 근본원인의 다른 얼굴), "일단 뭔가
받았으니 완료"로 처리해버리면 나중에 표준파일이 올라와도 재확인할 방법이 없었다
(daily는 `status IN (pending,failed)`만 재시도 대상으로 봄).

**수정**: `report_type IN (annual,half,quarter)`인 필링에서 고른 파일이 `.xml`/
`.xbrl`이 아니면 `_mark_completed()` 대신 신설한 `_handle_standard_file_pending()`을
호출 — 기존 [014] 정책(`XML_PENDING_ALERT_START_DAYS`=30일부터 알림, 무기한 재시도)과
**같은 메커니즘을 재사용**한다. 차이는 이미 받은 파일(PDF 등)이 있으므로
`file_path`/`file_type`/`file_size`를 잠정 채워두는 것 — 단 `status='pending'`이라
`report_lines` 재적재 유니버스(`dt.status='completed'` 필터)엔 안 들어간다. 표준파일이
실제로 올라오면 다음 데일리 재시도에서 정상적으로 `_mark_completed()`를 타 완료 처리
+ report_lines 재적재 대상 진입.

**검증**:
- 실측 5건 전부 재다운로드해서 XML 확보 확인(`_download_one()`을 직접 호출해 실제
  성공 재현) 후 `report_lines` 재적재 — BS/IS/CF/SCE 연결+별도 전부 정상 확보.
- `pytest fin2/tests/ tests/` 979 passed — 기존 무관 실패 3건 그대로, 신규 회귀 0
  (`tests/test_downloader_body_vs_attachment_r96.py`·`tests/test_download_5corps.py`
  포함).

**미조치**: 이 수정은 **앞으로의 신규 다운로드에만** 적용된다 — 과거에 이미
`status='completed', file_type='pdf'`로 마감된 필링(오늘 발견한 5건 제외)은 전수
백필 대상에서 안 걸러졌다. 그런 필링이 얼마나 더 있는지(전사 census)는 미실시 —
필요하면 `download_tasks WHERE file_type NOT IN ('xml','xbrl') AND status='completed'
AND report_type IN (annual,half,quarter)`로 후보를 뽑아 DART에 XML이 지금은
올라왔는지 표본 재확인하는 census를 다음 세션에서 고려.

---

## R104. `collector/filing_collector.py` — 같은 날 접수된 "최초본+첨부정정/첨부추가"

> **상태** 유효 · **적용 계층** 운영
그룹에서 최초본이 download_tasks에 영영 안 잡히는 결함 (2026-09-13, R103 후속 같은 날)

**배경**: R103으로 부국증권·멤레이비티의 2026 반기보고서를 살펴보다가, 사용자 질문
("정정보고서 이전 최초 보고서가 있었을 텐데, 그 기의 본문이 적재 안 된 거냐")으로
발견 — 두 회사 다 **최초본 자체가 `download_tasks`에 행 자체가 없었다**(다운로드
시도조차 안 됨). DART에 직접 확인해보니 최초본에 진짜 본문 XML이 있었다(부국증권
3.2MB · 멤레이비티 1.7MB) — 지금 `is_final=True`로 잡혀 있는 "[첨부정정]"/
[첨부추가] 쪽은 오히려 document.xml 자체가 없거나(014) 본문이 아니다.

**원인**: download_tasks 생성 SQL이 "`is_final=TRUE`인 것" 또는 "그룹에
`is_amendment=TRUE`인 필링이 있으면 그 그룹 전체"를 큐에 넣는데, `_is_amendment()`는
**"[기재정정]"만** amendment로 인정하고 "[첨부정정]"/"[첨부추가]"는 의도적으로
제외한다(`_is_attachment_amendment()` docstring: "본문은 동일, 첨부만 정정" —
그래서 재무 본문 신호로 안 씀). 최초본과 첨부정정이 **다른 날** 접수되면 문제가
없다(최초본이 먼저 도착했을 때 이미 `is_final=True`로 큐에 잡혔을 것이므로). 하지만
**같은 날** 접수되면 그룹이 생성되는 시점에 이미 `is_final`이 첨부정정 쪽으로
넘어가 있고 `is_amendment` 신호도 없어 최초본이 이 EXISTS 조건에 전혀 안 걸린다 —
"첨부만 정정, 본문 동일"이라는 가정이 이 타이밍에서는 "본문 자체를 안 받는다"는
결과로 뒤집힌다.

**수정**: EXISTS 조건에 `f2.is_attachment_amendment = TRUE`도 추가 — 그룹에 첨부
정정이 있으면(같은 날이든 아니든) 최초본도 항상 큐에 포함시킨다.

**검증**:
- 부국증권 `20260814002623`(최초 반기보고서)·멤레이비티 `20260814002334`([첨부추가]
  반기보고서) 둘 다 실제로 download_tasks 행 생성 → `_download_one()` 재현 →
  XML 확보(3.1MB/1.6MB) → `report_lines` 재적재까지 완료(BS/IS/CF/SCE 연결+별도
  정상).
- `pytest fin2/tests/ tests/` 979 passed — 기존 무관 실패 3건 그대로, 신규 회귀 0
  (`tests/test_filing_collector_correction_recheck.py` 포함).

**전사 census(같은 날 실시, 2026-09-13)**: 위와 같은 조건(그룹에 첨부정정이 있는데
어떤 필링은 download_tasks 자체가 없음)으로 전체를 스캔 — **잔여 0건**. 즉 이번에
백필한 부국증권·멤레이비티 2건이 이 버그의 전체 이력이었다(같은 날 접수되는
최초본+첨부정정 조합 자체가 드묾). R103의 "PDF로 완료 마감된 과거분" census는
성격이 다른 별개 항목이라 그쪽은 여전히 미실시 상태로 남아있음(R103 항목 참고).

---

## R139. `store_report_lines()` — 원문대조 완료(`layer2_review_queue.status='pass'`)

> **상태** 대체됨(→R167, 2026-09-24 사용자 결정, 이력으로 보존) · **적용 계층** 운영
행도 `unit_source='manual'`과 같은 방식으로 재적재 보호 (2026-09-18)

> ★**2026-09-24 폐지·대체(사용자 결정)** — 아래 하드 차단은 **R167** 로 대체됐다.
> pass 판정은 이제 `verification` 스키마가 들고, 재적재 자체는 허용하되 **내용이 실제로 바뀐
> 경우에만** 그 필링을 pending 으로 되돌려 재검증한다. `overwrite_reviewed` 인자는 호환용으로
> 받기만 한다. 이 절은 이력으로 남긴다.

**배경**: 2015+ 전체를 대상으로 "화면에서 원문대조 → DB의 BS/IS/CF/SCE
값과 비교"하는 캠페인을 자동화하는 설계 중, 사용자가 요구사항을 명확히
했다 — "눈으로 확인된 것과 같은 효과가 있어야 하고, 확인된 것은
manual 처리해서 재적재에서 제외하고, 이전에 manual 처리된 것도 제외돼야
한다." 이걸 실제로 보장하려면 "확인 완료" 표시가 **어느 재적재 경로로
와도** 그 필링을 보호해야 하는데, 코드를 확인해보니 그렇지 않았다.

**발견**: `layer2_review_queue.status='pass'`(`scripts/layer2_review.py
pass` — 사람 또는 원문대조 에이전트가 그 rcept의 report_lines를 원문과
대조해 통과시킨 표시)는 `layer2_review_queue` 테이블 자체의 컬럼만
바꿀 뿐, `report_lines`에는 어떤 흔적도 남기지 않는다(`_mark()`,
`scripts/layer2_review.py:292-299`). 이 상태를 실제로 존중해서 재적재를
건너뛰는 곳은 `reload_report_lines_2015plus_2026-09-12.py`·
`reload_report_lines_xbrl_2015plus_2026-09-15.py` 딱 2개 스크립트뿐이고,
둘 다 자기 SELECT 쿼리에 `WHERE status <> 'pass'`를 각자 복붙해둔
것일 뿐 공용 가드가 아니었다. `store_report_lines()`를 직접 부르는
나머지 15개+ 호출부(`reload_report_lines_corp.py`, `run.py`의 표준
적재, `note_lines_sync.py`/`pdf_lines_sync.py`/
`xbrl_instance_lines_sync.py`, 각종 backfill 스크립트 등)는 이 상태를
전혀 모른다 — 즉 `status='pass'`로 확정된 필링도 이런 경로로 다시
처리되면 **아무 경고 없이 통째로 지우고 다시 써서 검증된 상태가 조용히
무효화**된다. 기존 `unit_source='manual'` 가드(R8/2026-09-08)는 이미
`store_report_lines()` 안에 내장돼 모든 호출부에 자동 적용되는데, 이번
"원문대조 완료" 표시는 그런 공용 보호가 없는 비대칭이었다.

**수정**: `fin2/extract/report_lines.py::store_report_lines()`에
`overwrite_reviewed: bool = False` 매개변수 신설. 기본값에서는
`unit_source='manual'` 체크와 같은 자리(같은 함수 안, delete 실행 전)에
`layer2_review_queue.status == 'pass'` 존재 여부를 확인해, 있으면
`ValueError`로 거부한다(`overwrite_manual`과 독립된 별도 스위치 —
의미가 다르므로: 하나는 "값 자체가 사람 손입력", 하나는 "자동추출값을
사람/에이전트가 원문과 대조해 맞다고 확인"). 의도적으로 재검토해
덮어써야 하면 `overwrite_reviewed=True`를 명시. 기존 2개 스크립트의
`WHERE status <> 'pass'` 사전 필터는 그대로 둔다(불필요한 재추출 작업
자체를 건너뛰는 최적화라 무해 — 이제는 이중 방어).

**검증**: `fin2/tests/test_store_report_lines_manual_guard.py`에 회귀
테스트 5건 추가(총 9건) — 거부/`overwrite_reviewed=True` 허용/무표시시
정상진행/다른 rcept 비영향/`overwrite_manual=True`을 줘도
`overwrite_reviewed`는 별도로 거부되는지(두 가드의 독립성). `pytest
tests/ fin2/tests/` 전체 1059 passed(기존에 알려진 무관 실패
`test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix` 1건 제외).

**이 캠페인 설계에서 이 R139가 의미하는 것**: 원문대조 캠페인이 어떤
필링을 "확인 완료"로 표시하려면 `layer2_review_queue.status='pass'`로
갱신하면 되고, 그 순간부터 이 필링의 `report_lines`는 어떤 재적재
스크립트를 쓰든 자동으로 보호된다 — 캠페인 쪽에서 "재적재 대상에서
빼는" 로직을 따로 구현할 필요가 없다. 마찬가지로 이미 과거에
`status='pass'`로 확정된 필링(이전 계층2 캠페인 잔재)도 이 가드
신설 시점부터 자동으로 같은 보호를 받는다 — 별도 마이그레이션 불필요.

---

## R219. `store_report_tables()` 는 **넘겨받은 lines 가 다루는 statement 범위만** 지우고 다시 쓴다 — 본문 재적재가 주석 표 메타를 지우지 않는다 (2026-10-05, 삼양식품 분석 리포트 '감가상각비 없음' 추적)

> **상태** 유효 · **적용 계층** 운영

**발견**: 삼양식품 std_v3 D&A 가 2017·2018 FY 에만 있었다. 원문 주석(`note_lines`)에는 2024 '감가상각비 및 무형자산상각비 46,025,094,000' 등이 있다. 계층3 주석 해석(`fin2/layer3/note_da.py`)은 `report_tables.section_path`(주석 제목)로 주제를 찾는데, 그 rcept 들의 주석 메타가 0행이었다(본문 메타 8행만 남음).
- 원인: `store_report_tables()` 가 rcept 의 메타를 **statement 구분 없이 전부** 지우고 lines 에 있는 것만 다시 썼다. 본문만 추출한(`include_notes=False`) 2015+ 전사 재적재(`scripts/reload_report_lines_2015plus_2026-09-12.py`)·각종 R 백필·데일리 `collector/xbrl_instance_lines_sync.py` 가 주석 메타를 지웠다. R135 주석 재적재(2026-09-17)는 `store_note_lines` 만 불러 되살리지 못했다.
- 규모(2026-10-05): note_lines 가 있는 2015+ 필링 중 **77,672필링**이 주석 메타 없음. 2015+ FY std_v3 D&A 채움률 22,726/46,240.

**규칙** (`fin2/extract/report_lines.py::store_report_tables(scope=)`)
1. `scope='body'` → `statement<>'note'` 만 delete-then-insert. `'note'` → 주석만. `'all'` → 전부.
2. `scope=None` 이면 lines 에 주석 행이 있으면 `'all'`, 없으면 `'body'`.
3. `store_note_lines` 를 함께 부르는 호출측(`collector/note_lines_sync.py`, `fin2/verification/ops.py` XML 경로, a1_a2_c·r69 백필)은 `'all'` 을 명시한다 — 주석 0행 추출이어도 note_lines 와 메타가 짝을 이룬다. ops.py 의 XBRL 경로는 `'body'`.

**소급**: `scripts/restore_note_table_meta_r219_2026-10-05.py`. 원문을 `include_notes=True` 로 재추출해 (basis, table_seq) 표 집합이 DB note_lines 와 같고 표마다 라벨이 겹치면 **메타만** 쓴다. 다르면 note_lines 도 현재 코드로 다시 쓴다. report_lines 는 건드리지 않는다. 표본 6필링: 표 집합 6/6 일치, 행 수는 9/17 이후 행 규칙 변경(R136~)으로 대부분 다름 → 행 수는 판정에 쓰지 않는다. 이후 계층3(std_v3·달력) 재빌드로 D&A/EBITDA 가 채워진다.

**회귀 테스트**: `fin2/tests/test_store_report_tables_scope.py`.

**소급 결과(2026-10-05)**: 77,588필링 처리 — 메타만 73,361 · note_lines 재작성 4,227(표 구성이 달라 현재 코드로 다시 씀) · 오류 0, 217.8분(6워커, SD 미러). 이후 'note_lines 있음 AND 주석 메타 없음' 필링 0건. 계층3 std_v3 전사 재빌드(`build_std_v3.py --all --year-min 1990`, 5샤드, 2,525개사 · 약 18분, 오류 0) + 달력 전사 재빌드(2,528개사 · 350,401행 · orphan 0).
결과(FY 2015+ std_v3): D&A 채움 22,726 → **45,102 / 46,240(97.5%)**. 달력 CY(version=1, 2016+): dividends_paid 23,063 · da_total 39,754 · ebitda 39,716 / 40,601, native CY↔FY 불일치 0(R220). std_v3 잔여 음수 cogs 177 · sga 352 는 R221 자기 항등식이 음수를 증명한 행, interest_expense 10. 삼양식품 연결 CY2024: cogs 1,004,797,694,924 · 배당지급 −19,391,132,800 · D&A 46,025,094,000(원문 주석 '감가상각비와 무형자산상각비' 일치) · EBITDA 390,594,244,443.
참고: `std_financials_calendar` 의 version=2 1,106행(2026-07-18)은 `calendar_v3` 가 지우지 않는 옛 행이며 소비자 뷰 `calendar_financials` 는 version=1 만 읽는다.

## R327. 원문 경로는 디스크에 실제 있는 이름(NAS의 NFD 한글)으로 저장하고, NFC 경로는 실제 이름으로 풀어서 연다 (2026-11-17, 적용 계층: 운영)

> **상태** 유효 · **적용 계층** 운영(저장 경로)
>
> **규칙** `collector/raw_paths.py::on_disk` — 경로의 한 마디가 그 철자로 없으면 상위 폴더 목록에서 NFC로 같은 이름을 찾아 바꾼다(없으면 원래 경로 그대로). 다운로더(`collector/downloader.py::_build_file_path`)는 회사 폴더를 이 함수로 풀어 기존 폴더를 쓰고(새 NFC 폴더를 만들지 않는다), DB에는 디스크 이름이 들어간다. 원문을 여는 핵심 지점(`parser/xml/dart_xml_parser._parse_xml_file`, `fin2/extract/biz_section._load_root_uncached`, `fin2/extract/report_lines_xbrl._extract_zip_members`, 연결·IFRS 증거 판정, `fin2/verification/machine_compare.resolve_source`, `ops._sd_path`·재적재 경로)도 같은 함수를 거친다.
> **발견(2026-11-17)** NAS(`/Volumes/tj_finance_data`, SMB)의 회사 폴더 이름은 NFD 한글인데 DB·코드는 NFC 경로를 쓴다. macOS 27.2.1 업데이트 뒤 SMB 클라이언트가 NFC 조회를 NFD 폴더에 맞춰 주는 것이 마운트 직후 잠깐뿐이고, 10:49부터 한글 폴더 2,510개 모두 NFC 경로로 찾지 못했다(영문 폴더 86개는 정상, SD 미러(HFS)와 APFS는 정규화 무관). 기계대조 '원문 없음' 오판정 114건, 재개 표준화 적재 실패 4건, 테스트 31건 실패. 재마운트로도 몇 초 뒤 재발.
> **DB 정리** `scripts/fix_raw_path_on_disk_names_2026-11-17.py`: `download_tasks.file_path` 183,020건·`viewer_xml_path` 2,353건을 디스크 이름으로 바꿨다(옛 값은 `public.raw_path_backup_20261117`). 찾지 못한 975건은 상장폐지로 보관 폴더에 옮겨진 10개사의 옛 경로였다.
> **함께 고친 기존 결함** `collector/delisting_archive._repoint_download_tasks`가 디스크 목록의 NFD 폴더 경로와 NFC로 저장된 경로를 `startswith`로 비교해 한 번도 맞지 않았다("file_path 재배선 0건"). NFC로 비교하도록 고치고 10개사 1,079건을 보관 폴더 경로로 바꿨다(`scripts/repoint_archived_corps_2026-11-17.py`, 옛 값은 같은 백업 테이블).
> **테스트** `tests/test_raw_paths_on_disk.py`(SMB처럼 정확한 철자만 존재하는 환경을 흉내 내 NFC 경로가 NFD 폴더로 풀림, 있는 경로·없는 경로는 그대로).
> **실파일 테스트(2026-11-18)** 원문을 직접 여는 회귀 테스트 16개 파일(31건)이 NFC 한글 경로로 `exists()` 를 검사해 NAS 에서 "raw report not available" 로 조용히 skip 되고 있었다. 테스트도 경로를 `on_disk()` 로 풀어서 연다(`tests/test_r245~r256*`, `fin2/tests/test_r0_2_layer2_as_printed.py`·`test_r152`·`test_r154`·`test_r157_r158`·`test_r161`·`test_r168`·`test_r204`). 새 실파일 테스트도 같은 방식으로 쓴다.

## R329. 웹뷰 인쇄본 적재와 검증 재적재도 필링 판정(IFRS·연결 증거)을 저장한다 (2026-11-17, 적용 계층: 운영)

> **규칙** `collector/xbrl_instance_lines_sync.py::store_filing_evidences` — 필링을 적재한 뒤 `filings.ifrs_evidence` 와 `filings.consolidation_evidence` 를 저장한다(데일리 XML 경로 `collector/note_lines_sync.py` 와 같은 판정, 실패해도 savepoint 로 되돌리고 적재는 유지). 호출부: `sync_viewer_lines`(④-4 웹뷰 인쇄본), `fin2/verification/ops._reload_rcept`(검증 큐 재적재, `scripts/reload_report_lines_corp.py`). XBRL zip 원천이면 IFRS 는 DB 트랙(Track D)만, 연결 증거는 옆의 웹뷰 인쇄본(R325)으로 본다.
> **발견(2026-11-17)** 2015+ 최종본 중 `consolidation_evidence_detail` 이 NULL 인 1,083건을 다시 판정: 865건은 증거 없음(연결재무제표가 있는 회사, 증거가 없으면 detail 도 NULL 로 저장되는 구조라 정상), **179건(172개사)은 "2. 연결재무제표 — 해당사항 없음" 인데 비어 있었다**(162건이 2026-11-12~17 접수, 대부분 11-16 3분기보고서). 적재 기록(`verification.filing_load_events`)상 `viewer_source` 로 적재된 필링이었고, 그 경로와 `_reload_rcept` 는 두 판정을 모두 저장하지 않았다. 같은 원인으로 IFRS 판정이 빈 최종본이 2,198건 있었다.
> **백필** `scripts/backfill_filing_evidence_viewer_reload_2026-11-17.py --apply`(빈 칸만 채움, 기록 `public.filing_evidence_backfill_20261117`): 연결 증거 179건, IFRS 1,202건(track_a 939, std_no_kifrs 260, std_no_mixed 2, track_d 1), 영향 1,018개사 std 재빌드(2015+).
> **테스트** `tests/test_viewer_load_stores_evidence.py`(두 판정 저장·한쪽 실패 비치명·XBRL zip 원천의 경로 선택).

## R333. 시가총액은 그날 실제 종가 × 그날 유통주식수로 계산한다(KRX OpenAPI 일별 매매정보) (2026-11-17, 적용 계층: 운영, 사용자 결정)

> **규칙** `scripts/krx_daily_trade_sync.py` 가 KRX OpenAPI 일별 매매정보(`stk_bydd_trd`, `ksq_bydd_trd`, `collector/krx_client.fetch_daily_trade`)에서 그날 실제 종가(`stock_prices.close_raw`)·상장주식수(`list_shares`)·KRX 시가총액(`krx_mktcap`)을 채운다(받은 날짜는 `public.krx_daily_trade_log`, 이어받기 `--resume`). `scripts/fin2_market_cap_daily.py` 는 `market_cap = close_raw × shares_out`, `shares_out = round(list_shares × 유통비율)`(유통비율 = 그날 직전 정기보고서의 유통주식수 ÷ 보통주, R225 유통주식수 기준)로 계산한다. 자기주식 "수"를 빼지 않고 "비율"을 곱한다 — 분기 중간 액면병합·분할·무상증자 때 자기주식도 같이 바뀌므로, 옛 보고서의 자기주식 수를 빼면 병합 회사 시총이 0 근처로 떨어졌다(2026-11-18 검증, 032190·007460 등). KRX 행이 아직 없는 최근 30일은 마지막 상장주식수를 이어 쓰고, KRX 데이터가 없는 2015 이전은 예전 방식(close_price × 최근 정기보고서 유통주식수, 근사)으로 남긴다. `close_price` 는 수정주가 시계열(차트용)이다. 2026-09-14(애프터마켓 개장)부터는 KRX 일별 단계가 `open/high/low/close_price` 를 KRX 정규장 값으로 바꾼다 — 저장된 기준(수정주가)을 유지하려고 배수 = 중앙값(저장값/KRX값, 시가·고가·저가)을 곱한다. 시가는 애프터마켓 영향을 받지 않아 중앙값이 참 배수다(이후 권리락이 없으면 1). 거래정지 행(KRX 고가 0)은 그대로 둔다(종가 = 기준가로 이미 같음). `valuation_daily` 에 `close_raw` 를 더하고 `dividend_yield = 배당금 / market_cap` 으로 바꿨다(마이그레이션 `2026_11_17_stock_prices_krx_daily`, `2026_11_17_valuation_daily_close_raw`). 야간 갱신(`scripts/nightly_valuation_refresh.py`)에 ①-b(최근 15일 KRX 일별) 단계를 넣었다.
> **발견(2026-11-17, 소비 프로젝트 보고)** `stock_prices.shares_out` 이 2,555종목 중 2,516종목에서 최근 400일 동안 한 번도 바뀌지 않았다. 예전 식은 `close_price × 최신 사업보고서(FY) 유통주식수(상수)` 였고 close_price 를 수정주가로 가정했다. ① 최신 FY 이후 주식수가 30% 넘게 바뀐 회사 307개사(무상증자·액면병합·유상증자)의 지금 시총이 틀렸다 — 티앤엘(2026-07-23 무상증자 결정, 신주 7,942,120주)은 절반, 5:1 병합 회사(한국전자홀딩스·페이퍼코리아·폴라리스AI 등)는 5배. ② 일일 수집은 최근 15일만 다시 받으므로 저장된 과거 가격은 대부분 받은 날의 실제 가격이고 일부 구간만 나중에 수정주가로 다시 받았다(티앤엘 2025-12 약 4.8만 → 2026-01 약 2.4만 가짜 반토막, 2015+ 하루 +45%/−40% 초과 움직임 216종목 247회). pykrx 1.0.51 은 수정 전 가격·시가총액 조회가 빈 응답(KRX 로그인 필요), 네이버는 수정주가만 준다.
> **주의** 무상증자 권리락일부터 신주 상장일까지(보통 2~3주) KRX 상장주식수는 옛 값이라 시총이 작게 잡힌다(KRX 공식 시총과 같은 방식).
> **함정(2026-11-18 발견)** 2026-09-14 한국거래소가 애프터마켓(16:00~20:00, 전 종목)을 열면서 pykrx(네이버) 일별 `종가` 는 20시 마지막 체결가가 됐다. 그날부터 `close_price` 가 KRX 정규장 종가(`close_raw`, 15:30)와 약 80% 종목에서 다르다(그 전 1~2% = 수정주가 차이). 시가총액은 `close_raw` 로 계산하므로 영향 없다(아직 KRX 행이 없는 마지막 하루만 이월 단계에서 `close_price` 를 쓰고, 다음 밤 KRX 값으로 바뀐다). 2026-11-18 사용자 결정으로 `close_price` 도 정규장 종가로 맞췄다(위 규칙, 9-14~11-16 재적재 후 `close_price ≠ close_raw` 9월 1.05%·10월 0.58%·11월 0.22% = 이후 권리락으로 수정주가 기준인 행). pykrx 고가·저가도 애프터마켓을 포함한다(11-11 고가 일치 61%, 시가·거래량은 100% 일치).
> **매일 흐름(launchd `com.tjfinance.valuation`, 19:00)** ① pykrx 최근 15일 OHLCV(수정주가, 애프터마켓 섞임) → ①-b KRX 최근 15일(실제 종가·상장주식수, 9-14 이후 OHLC 정규장 값으로 교체) → ② 시가총액(그날 실제 종가 × 상장주식수 × 직전 보고서 유통비율) → ③ `valuation_daily`. KRX 는 D 일 자료를 D+1 아침에 공개하므로 19:00 실행 시점에 당일 행은 KRX 값이 없다: 당일은 pykrx 값(종가는 19시 애프터마켓 체결가)과 전날 상장주식수로 임시 계산하고 다음 날 밤 KRX 값으로 바뀐다. 주식수 변화(무상증자·병합)는 KRX 상장주식수로 매일 반영된다. 유통비율은 데일리 수집이 새 정기보고서를 적재하고 계층3을 다시 만들면 따라온다. 수정주가는 pykrx 가 매일 최근 15일만 다시 주므로 그보다 오래된 `close_price` 는 권리락 뒤에도 소급 수정되지 않는다(시가총액은 `close_raw` 를 써서 영향 없음).
> **실측(2026-11-18)** KRX 백필 2015-01-01~2026-11-16 3,098일·4,974호출, stock_prices 4,941,936행 갱신(KRX에 있고 stock_prices 에 없는 행 813,510 = 우선주·상폐 등, 넣지 않음). 시총 재계산: KRX 일별 4,371,758행·예전 방식 2,263,778행. `market_cap / krx_mktcap` > 1.001 = 0행, 0.4 미만 184행(다우데이타 2015-06·엘컴텍 2015-03 보고서 주식수 오적재, 계층3 데이터 문제). 티앤엘 2026-08-20 2,424억 → 2026-09-01(신주 상장) 4,886억, 최근 400일 주식수가 바뀐 종목 1,626. `valuation_daily` 11,257,112행.
> **테스트** `tests/test_krx_daily_trade_sync.py`(행 파싱·잘못된 행 제외, 네트워크 재시도·인증 오류 즉시 실패, 평일만).

## R337. 자본이벤트 데일리 조회는 마지막 적재 시점부터 이어서 본다 (2026-11-18, 적용 계층: 운영)

> **상태** 유효 · **적용 계층** 운영(수집)
>
> **규칙** `collector/dart_capital.py::capital_sync_start` — 데일리 ⓪-2(`scripts/collect_new.py::_sync_capital`)의 조회 시작일은 `min(오늘−5일, max(capital_events.fetched_at)−5일)`, 최대 120일 전까지. 적재할 때 `fetched_at = now()` 를 기록한다(예전엔 늘 NULL).
> **발견(2026-11-18, 소비 프로젝트 보고)** tj_asset 이 코나아이 무상증자결정(20260914000031)이 `capital_events` 에 없다고 보고. 조회 창이 "오늘 기준 5일" 고정이라 데일리가 멈췄던 기간(2026-07 말, 2026-09 말~10-03 재개)의 공시는 재개 뒤에도 다시 보지 않았다. 2026년 원본 공시 1,659건 대조: 같은 회사·유형 행이 ±120일 안에 하나도 없는 누락 57건(9월 31, 7월 18). 나머지 원본 400건 "누락"은 상세 API 가 정정 뒤 최종본 한 행만 돌려주는 구조(파일 머리 주석) 때문이며 결함이 아니다.
> **백필** `scripts/backfill_capital_events.py --start-year 2025`(연 단위 창, ON CONFLICT 멱등).
> **테스트** `tests/test_capital_sync_resume.py`(이력 없음·평시·장애 뒤 재개·상한).

## R338. 수정주가는 종목마다 한 기준으로 전체 이력을 받는다 — 기준 단절이 보이면 그 종목 전체를 다시 받는다 (2026-11-18, 적용 계층: 운영)

> **상태** 유효 · **적용 계층** 운영(시세 수집)
>
> **규칙** `analyzer/adjusted_history.py` — 기준계수 `F = close_price / close_raw` 가 바뀐 날 중 **수정종가는 뛰는데 실제 종가는 이어지는 날**(`|ln(c/pc)| > |ln(r/pr)|`, 계수 변화 > max(1%, 1.5/수정종가))을 "낡은 기준 경계"로 본다(진짜 권리락일은 반대로 실제 종가가 뛰고 수정종가가 이어진다). 매일 밤 `nightly_valuation_refresh.py` ①-c 가 최근 20일 안에 경계가 생긴 종목(하루 최대 30)의 상장 이후 전체 이력을 네이버 siseJson 에서 다시 받아 **기존 날짜의 시가·고가·저가·종가만** 바꾼다(새 날짜 추가 없음, 거래량 그대로). 2026-09-14(애프터마켓) 이후 행은 원천 종가가 애프터마켓 체결가라 쓰지 않고, 저장된 KRX 정규장 값을 새 계수(시·고·저 비율 중앙값, `krx_daily_trade_sync` 와 같은 규칙)로 다시 맞춘다. 종목 단위 트랜잭션이며 경계 수가 늘면 되돌린다.
> **발견(2026-11-17, 소비 프로젝트 보고)** 매일 pykrx 로 최근 15일만 다시 받아, 기업행동 뒤 15일 창 안쪽만 새 기준이 되고 그 앞은 옛 기준으로 남았다(코나아이 052400 2026-10-13→14 수정 33,300→22,733, 실제 33,300→34,000; 티앤엘 340570 2026-01-02 -51%). 2015+ 측정: 계수 변화 20% 이상 낡은 경계 235건 약 220종목, 1~20% 396건.
> **원천 확인** pykrx 와 네이버는 겹치는 날 값이 같다(052400: 2,785일 차이 0). pykrx 는 2014-08 부터, 네이버는 상장일부터 → 네이버 한 원천으로 전체를 받는다.
> **원천 쪽 경계(고치지 않음)** 분할 재상장 등으로 KRX 가 기준가를 새로 정한 날은 원천 수정주가에도 경계가 있다(KCC 002380 2020-01-21: 원천 = DB). 다시 받아도 그대로라 남는다.
> **일회성 소급(A안)** `scripts/backfill_adjusted_history_2026-11-18.py` 활성 2,542종목, 백업 `public.stock_prices_ohlc_backup_20261118`(11,323,179행). KRX 일별 매매정보를 2010-01-04 까지 넓혀(`krx_daily_trade_sync.py --start 20100101 --end 20141231`) 판정 범위를 2010 까지 넓혔다. 결과: 193종목 약 73만 행 재기준, 2015+ 경계(계수 변화 65% 초과) 178→13·20~65% 57→38, 최근 400일 225→33(남은 것은 원천과 값이 같은 경계). 거래정지일(거래량 0)은 판정에서 뺀다(주식병합 정지 기간 거짓 경계, 047400). 2010~2014 KRX 1,731,136행 채움 뒤 시가총액 전수 재계산(2010~2014 는 KRX 상장주식수 × 가장 이른 보고서 유통비율).
> **DQ** `dq_assertions.py::adjusted_price_stale_boundary`(WARN, 최근 400일).
> **계획** `docs/plans/adjusted_price_full_history_plan_2026-11-18.md`(2015 이전 연도별 보고서 적재와 맞추는 순서 §7).
> **테스트** `tests/test_adjusted_history.py`.

## R346. 데일리 DQ 게이트(Gate B)는 계층2 가 마지막 감사 뒤에 다시 적재된 것만 재감사하고, 금요일에 전체를 재감사한다 (2026-11-19, 적용 계층: 운영, 사용자 결정)

> **상태** 유효 · **적용 계층** 운영(데일리 ⑤ 검증)
>
> **규칙** `scripts/collect_new.py::run_dq_gate(full=False)` — 회사마다 감사 전에 `face_audit` 중 그 std 행의 원천 filing(`source_rcepts`)이 감사 뒤 다시 적재된 것(`report_tables.parsed_at > checked_at`, 둘 다 UTC)과 `face_line_audit` 중 그 filing 이 다시 적재된 것을 지우고 `gateb_audit.audit_corp(recheck=False)` 를 부른다. 결과가 없는 행·filing(새 기간, 새 공시)은 원래대로 감사된다. ~~금요일 데일리 전체 재감사~~ → **R346-b 지문 방식으로 대체(같은 날)**. `--verify-full` 은 예전처럼 전부 재감사(`recheck=True`). 알림 판단(어제 대비 신규 증가분)과 `corp_verify_status` 집계는 바뀌지 않는다.
> **발견(2026-11-19, 사용자 지적 "데일리가 이렇게 길게 걸리는 것은 문제")** 11-17 데일리 35시간(1,276개사) 중 ⑤ Gate B 가 23.7시간(회사당 67초) — 매일 2015+ 전체 이력을 재감사했다. 그 실행에서 실제로 다시 적재된 것은 std 행 1,134/39,378·filing 634/22,324(약 3%).
> **실측** 00164788: 증분 1.2초(다시 적재된 filing 1건) · 두 번째 0.0초 · 전체 18.9초, 결과 같음.
> **남는 틈** 계층2 재적재 없이 계층3 규칙만 바뀐 행은 증분이 못 본다 — 규칙 수정 때의 전수 재감사([[30_audit_verify]] 원칙)와 금요일 전체 재감사가 잡는다.
> **테스트** `tests/test_collect_new_dq_gate_incremental.py`.

## R346-b. Gate B 면 감사 결과에 그 std 행의 지문을 남기고, 데일리는 지문이나 판독기 버전이 바뀐 것만 재감사한다 — 주간 전체 재감사 없음 (2026-11-19, 적용 계층: 운영, 사용자 결정)

> **상태** 유효 · **적용 계층** 운영(데일리 ⑤ 검증) · R346 의 재감사 판정을 바꾼다
>
> **규칙** `face_audit.input_fp` = 감사한 `std_financials_v3` 행의 `md5((to_jsonb(s) - 'built_at')::text)`(`scripts/gateb_audit.py::INPUT_FP_EXPR`). `audit_corp` 가 결과를 쓴 직후 같은 식으로 찍는다(ORM 모델에는 없음 — upsert 가 지우지 않게). 데일리(`collect_new.run_dq_gate(full=False)`)는 감사 전에 지문이 지금 행과 다르거나 `reader_version` 이 다른 면 결과, 감사 뒤 다시 적재됐거나 `reader_version` 이 다른 라인 결과(`face_line_audit`, 계층2 인쇄값만 읽으므로 재적재만 보면 된다)를 지우고 `recheck=False` 로 감사한다. 지문이 없는 결과(도입 전, v2 잔재 제외)는 처음 한 번 재감사된다.
> **왜** R346(재적재 시각만)은 원문 재적재 없이 값이 바뀌는 경우 — 계층3 규칙 변경, 계층3 셀 보정, 원천 filing(최초본·정정본) 교체, 판독기 변경 — 를 못 봐서 금요일 전체 재감사를 두었다. 지문은 이 넷을 매일 정확히 잡으므로 전체 재감사가 필요 없다.
> **결정성 확인** 무작위 20개사 연속 두 번 재빌드 2,305행 지문 차이 0(`built_at` 만 빼면 된다).
> **실측** 00164788: 첫 실행 18.1초(지문 없음 → 94행 재감사·찍음), 두 번째 0.0초, 한 행 지문을 바꾸면 그 행만 1.1초.
> **스키마** 마이그레이션 `2026_11_19_face_audit_input_fp`(`ALTER TABLE face_audit ADD COLUMN input_fp TEXT`).
> **테스트** `tests/test_collect_new_dq_gate_incremental.py`.

## R350. 데일리 실행 기록은 끝나는 방식과 관계없이 닫힌다 — 예외·SIGTERM·Ctrl-C 는 failed/killed, 죽은 실행은 다음 실행이 abandoned. 소비자는 `load_status` 뷰로 적재 신선도를 읽는다 (2026-11-19, 적용 계층: 운영, 사용자 결정: 새 테이블 대신 뷰)

> **상태** 유효 · **적용 계층** 운영
>
> **규칙** `scripts/collect_new.py` — `_start_run` 이 `summary.pid` 를 남기고, 시작 전에 `status='running'` 인데 프로세스가 없는 이전 행을 `abandoned` 로 바꾼다(pid 없는 R350 이전 행은 다른 데일리 프로세스가 살아 있으면 건드리지 않음). `__main__` 이 SIGTERM 을 SystemExit 로 바꾸고, `main()` 이 예외·종료 신호로 끝나면 열린 실행을 `failed`(예외)/`killed`(SIGTERM·Ctrl-C) 로 닫는다. SIGKILL 은 잡을 수 없어 다음 실행이 abandoned 로 정리한다. 워터마크는 여전히 `success` 만 전진.
> **뷰** `load_status`(`scripts/qa/r350_load_status_view.sql`, `tja_reader` 에 SELECT): 항목별 `last_run_at`·`last_status`·`last_success_at`·`data_through`·`version`·`stale`. 항목 = `pipeline:<mode>`(최근 30일 안에 돈 모드만; data_through = 마지막 성공 실행의 window_end), `filings`(max filed_at), `capital_events`(max filed_at·fetched_at), `stock_prices`(005930 의 max trade_date), `consumer_guide`(guide_version·updated_at). `stale` = 4일 넘게 새 데이터 없음(긴 연휴엔 참이 될 수 있음).
> **왜** tj_asset 요청 5(2026-11-18): 무상증자 정보를 `capital_events` 에서만 읽게 되어 적재가 멈추면 시가총액 보정이 빠지는데 읽는 쪽이 알 수 없음. `pipeline_runs` 는 이미 있었으나 11-16 실행(id 60)이 `running`·`finished_at` 없음으로 남아 믿을 수 없었다(시작만 기록, 종료 경로가 정상 return 뿐). id 60 은 수동으로 abandoned 처리.
> **스키마** 새 테이블 없음(사용자 결정 2026-11-19). 뷰 하나 추가, `load_status`·`pipeline_runs` 를 `docs/consumer_guide/grants.sql` 허용 목록에 넣음(목록 밖은 가이드 적재 때 REVOKE 되므로 GRANT 만으로는 사라진다 — 실제로 한 번 사라짐). 사용법은 가이드 s01.

## R351. 거래정지일 행도 수정주가 기준을 맞춘다 — 정지일 계수가 앞뒤와 다르면 그 종목을 다시 받고, 정지일은 원천 종가를 그대로 쓴다 (2026-11-19, 적용 계층: 운영)

> **상태** 유효 · **적용 계층** 운영(시세 수집)
>
> **규칙** `analyzer/adjusted_history.py` — ① `halt_boundaries`(`_HALT_SQL`): 거래량 0 인 날의 계수 `close_price/close_raw` 가 앞이나 뒤 행과 `max(1%, 1.5/종가)` 넘게 다르면 경계. 야간 ①-c `nightly` 가 R338 의 거래일 경계와 합쳐 다시 받을 종목을 고른다(최근 20일, 하루 최대 30). ② `rebase_after_market_row`: 시가·고가·저가가 없는 행(정지일)은 체결이 없어 애프터마켓도 없으므로 원천 종가가 곧 현재 기준의 기준가 → 그 값을 쓴다. ③ `refetch_stock` 은 거래일 경계 또는 정지일 경계가 늘면 되돌린다.
> **왜** tj_asset 요청 4: 최근 400일 하루 ±30.5% 변동 101건 중 81건(46종목)이 정지일 미보정 — 기업행동 전 정지일 행이 옛 기준(수정종가 = 원래 종가)으로 남고 앞뒤 거래일만 새 기준(047400 2026-10-27..30: 746, 앞뒤 3,730 → 차트에 ×0.2 / ×5). R338 은 병합 정지 기간의 거짓 경계를 피하려고 정지일을 판정에서 빼서 이 행들이 다시 받기 대상이 되지 않았고, 다시 받아도 2026-09-14 이후 행은 시·고·저 비율로만 재기준해서 값이 없는 정지일 행은 그대로 남았다. 원천(네이버)은 정지일도 현재 기준으로 준다(047400 10-27: 3,730).
> **나머지 20건** 19건은 원래 종가도 같이 뛴 날(실제 가격 변동 또는 원천 쪽 경계 — R338 "원천 쪽 경계(고치지 않음)"), 1건은 R338 거래일 경계(472850, 야간 ①-c 대상).
> **분류 쿼리** `scripts/qa/tj_asset_price_breaks_classify.sql`. **일회성 소급** `scripts/backfill_halt_rebase_2026-11-19.py`(`--dry-run` 먼저).
> **테스트** `tests/test_adjusted_history.py`(정지일 원천 종가, 원천 종가 없으면 유지, 정지일 감지 SQL).

## R355. 데일리 ⑤(Gate B·사업지표·분기반기·수주·원문 비재무 섹션)는 "⑤를 거친 필링" 표시로 고른다 — std_v3 에 기간이 있다는 것만으로 끝난 것으로 보지 않는다 (2026-11-20, 적용 계층: 운영)

> **규칙** 다운로드가 끝난 정기보고서 필링마다 ⑤를 거쳤다는 표시를 `pipeline_post_stage_done(rcept_no)` 에 남긴다. 데일리 ⑤ 대상 = 오늘 ④ 기업 ∪ 표시 없는 필링이 있는 기업(`app/data/collect.py::post_stage_pending`, 한 실행에 최대 `POST_STAGE_CATCHUP_MAX`=300개사, 나머지는 다음 실행). ⑤가 다 돈 뒤 그 기업들의 필링 중 ⑤ 선택 시각(UTC, `download_tasks.created_at` 과 같은 기준) 이전에 받은 것을 표시한다(`mark_post_stage_done`). 실행이 ⑤ 도중 죽으면 표시가 안 남아 다음 실행이 다시 집는다. 표시 없는 필링의 연도가 그 기업의 최신 연도가 아니면 ⑤-1c 가 그 연도만 따로 사업지표(annual)·분기반기 지표를 다시 만든다(⑤-1·⑤-1b 는 최신 연도만 봄). 두 call site(메인·`--standardize-only`) 모두 `scripts/collect_new.py::_run_post_stages` 를 부른다.
> **발견** tj_asset 요청 3 재적재 중 아시아종묘(00867478) 2026 Q3(20261116002130) 분기·반기 지표가 0행. 11-16 데일리(run 60)가 ④ 배치 20/34(11-17 01:20)에서 죽었고(⑤ 미실행, 나중에 abandoned), 같은 밤 R321~R324 야간 배치가 약 700개사 std_v3 를 데일리 밖에서 재빌드하면서 run 60 이 막 적재한 계층2로 그 기간 std 행을 만들었다. 다음 데일리(run 61)의 ④ 선택(`needs_standardize_corps` = std_v3 에 기간 없음)이 이 기업들을 건너뛰어 ⑤가 한 번도 돌지 않았다. run 60 다운로드 기준 **529개사**(그 뒤 검증 기록 없음) — 분기·반기 지표만 롤백 dry-run 으로 세어 2026 Q3 53건이 비어 있었다. 따로 01158632 는 2017~2020 분기·반기 21건을 새로 받았지만 ⑤-1b 가 최신 연도만 봐서 비어 있었다(앞으로는 ⑤-1c 가 처리).
> **시드** 마이그레이션 `2026_11_20_pipeline_post_stage_done`(+ `_seed_null_created`: 옛 다운로드 행은 `created_at` NULL) — 받은 필링 전부를 표시하되 run 60 창(`created_at` ≥ 2026-11-16 09:00 UTC)에 받은 필링 중 그 뒤 검증되지 않은 기업 것만 남김 → 대기 529개사·535 (기업, 연도, 종류).
> **소급** `scripts/qa/r355_post_stage_catchup.py --chunk 50 --until 17:40`(50개사씩 ⑤ 후 표시, 18:00 데일리와 겹치지 않게 멈춤, 남은 것은 데일리가 이어받음). **결과(2026-11-20 16:06~17:34)**: 11덩이 529개사·537필링 표시, 대기 0. Gate B 새 fail_a 2건(DS단석 00108612·사조산업 00124799, 둘 다 2026 Q3 별도 — 미조사), DQ3 경고 4. 아시아종묘 2026 Q3 분기·반기 지표 0→142행. 시드가 '나중에 검증됨'으로 표시해 catch-up 에서 빠진 과거 연도 필링(최근 받았는데 그 기업 최신 연도가 아니고 분기·반기 지표 0행)은 2개사뿐이라 연도별 `sync_biz_periodic(year=)` 로 직접 채움: 진코스텍 01158632 2017~2024 9개 연도, 덕산넵코어스 00960623 2022~2025.
> **하지 않은 것** ⑤-2 수주·⑤-3 원문 비재무 섹션은 여전히 최신 사업연도만 다시 만든다(과거 연도 필링 늦은 도착은 ⑤-1c 만 처리).
> **테스트** `tests/test_collect_new_post_stage_r355.py`(대기 기업이 ⑤ 전 단계에 들어감, 표시는 맨 끝·선택 시각 기준, 표시 실패·대기 조회 실패는 비치명, 과거 연도 연도별 동기화).

## R356. 웹뷰 인쇄본으로 적재한 필링에 원본 XML 이 오면(`layer2_reload_pending`) ④ 가 그 기업을 오늘 공시와 상관없이 다시 고르고, 다시 적재한 필링은 ⑤ 도 다시 돈다 (2026-11-20, 적용 계층: 운영)

> **규칙** `app/data/collect.py::needs_standardize_corps` — `download_tasks.layer2_reload_pending` 이 켜진 (원본 XML 완료) 필링의 기업은 `only`(메인 경로 = 오늘 공시 기업) 제한과 "std_v3 에 기간 없음 / 최근 30일 계층2 0행" 조건 밖에서도 ④ 대상이다. ④-3 `collector/note_lines_sync.py::sync_layer2_lines` 는 이미 이 표시를 존중해 원본 XML 로 다시 적재하고 표시를 끈다. 표시를 끌 때 그 필링의 `pipeline_post_stage_done` 행을 지워 ⑤(R355: Gate B·사업지표·수주·원문 비재무 섹션)가 원본 XML 로 다시 돈다 — 웹뷰 인쇄본에는 재무제표·주석 섹션만 있다. 검증 큐 재적재(`fin2/verification/ops._reload_rcept`)도 원본 XML 로 읽었을 때 같은 일을 한다. 선택 함수 하나를 두 call site(메인·`--standardize-only`)가 같이 쓴다.
> **발견** R355 소급 뒤 Gate B 새 fail_a 2건 — DS단석 00108612·사조산업 00124799 2026 Q3 별도(20~21개 항목 전부 VALUE_DIFF). 두 필링(`20261116001018`·`20261116001384`)은 접수 당일 원본 XML 이 없어 웹뷰 인쇄본(`.viewer.xml`)으로 계층2 를 적재했는데(11-17 16:55, `filing_load_events.reason=viewer_source`) 그 인쇄본의 `4. 재무제표` 섹션이 비어 있어 연결만 실렸다. 11-17 19:10 원본 XML(4-1~4-4 별도 재무제표 있음)이 와서 다운로더가 표시를 켰지만, ④ 선택은 std_v3 에 기간이 이미 있고 계층2 가 0행이 아니며 메인 경로는 오늘 공시 기업으로 한정돼 이 기업들을 다시 고르지 않았다(R355 와 같은 꼴 — std_v3 존재를 "끝남"으로 봄). 계층3 basis fallback(`fin2/layer3/combine.py`, 그 기간에 한쪽 basis 만 있으면 다른 쪽에 복사)이 별도 행을 연결값으로 채웠고, Gate B 가 원본 XML 의 별도와 대조해 fail_a. 같은 상태 필링 **335건(330개사, 원본 XML 도착 2026-10-23~11-17)**, 모두 마지막 적재가 원본 도착 전 인쇄본. 별도가 아예 빠진 것은 3건(위 2건 + 도화엔지니어링 00114552 `20261113001594`, Gate B pending 이라 fail_a 로 안 잡힘). 서울평가정보 00260745 는 원문이 "4. 재무제표 — 해당사항 없습니다"라 정상.
> **하지 않은 것** basis fallback 이 연결비대상 증거(`filings.consolidation_evidence`) 없이도 연결→별도 복사를 하는 것은 그대로 둔다(계층2 가 빠졌을 때 별도 값을 지어내는 별개 문제, 사용자 판단 대기).
> **테스트** `tests/test_needs_standardize_reload_pending_r356.py`(로컬 DB 트랜잭션 롤백: 표시된 필링 기업이 `only` 밖에서도·재개 경로에서도 선택, 표시 없는 기업은 여전히 `only` 로 제한).

## R357. 원문 경로의 한글 마디는 `exists()` 가 아니라 폴더 목록의 실제 철자로 정한다 — 마운트 직후 NFC 조회가 잠깐 통해도 NFD 이름을 저장 (2026-11-20, 적용 계층: 운영)

> **규칙** `collector/raw_paths.py::on_disk` — 경로의 ASCII 아닌 마디는 상위 폴더 목록에서 NFC 로 같은 항목을 찾아 그 철자(NAS 는 NFD)로 바꾼다. `exists()` 로 먼저 통과시키지 않는다. 목록에 없는 마디(아직 안 만든 연도 폴더 등)는 그 마디부터 입력 철자를 쓰되, 앞에서 푼 회사 폴더 철자는 유지한다(예전에는 경로 전체를 입력 그대로 돌려줬다).
> **발견** 데일리 run 62 미러 실패(rsync rc=23, 엔케이젠바이오텍코리아 `20261118000208.xml` stat 실패)와 완전성 감사 '유실복구 5'. R327 뒤에도 2026-11-17~20 에 받은 `download_tasks.file_path` 434건이 NFC 로 저장돼 몇 분 뒤 열리지 않았다(R327 발견: SMB 클라이언트가 마운트 직후 잠깐만 NFC 조회를 NFD 폴더에 맞춰 줌 → 그 순간 `exists()` 가 참이라 NFC 철자를 그대로 저장). 이 경로를 그냥 `exists()` 로 확인하는 곳(`collector/note_lines_sync.py` 의 `Path(file_path).exists()` 는 조용히 건너뜀, 미러, 완전성 감사의 '유실' 판정 → pending 으로 되돌림)이 영향을 받는다. 434건 모두 계층2 는 이미 적재돼 있었다(다운로드 직후 조회가 통하던 동안 적재).
> **DB 정리** `scripts/fix_raw_path_on_disk_names_2026-11-17.py --apply --backup-table raw_path_backup_20261120`(새 `--backup-table` 인자 — 11-17 백업 테이블의 ON CONFLICT DO NOTHING 에 옛 값이 묻히지 않게): `file_path` 434건. 못 찾은 98건은 보관 폴더로 옮겨진 에코볼트 00562360 한 회사의 옛 경로(별건, 손대지 않음).
> **검증 기계대조** 11-15 이후 `verification.machine_checks` no_source 17건이 모두 이 434건(NFC 경로)이었다. 9건은 이미 통과, pending 8건은 같은 load_seq 라 기계가 다시 보지 않고 모델 검증으로 넘어갈 상태라 기록을 지움(백업 `verification.machine_checks_nosource_backup_20261120`). SD 미러 누락(R358)은 영향 없음 — SD 를 읽는 곳(`ops._sd_path`, `machine_compare.resolve_source`)은 SD 에 없으면 NAS 로 읽고, 데일리 적재는 NAS 만 읽는다.
> **테스트** `tests/test_raw_paths_on_disk.py`(모든 철자가 "있는" 순간에도 NFD 로 풀림, 없는 연도 폴더 아래에서도 회사 폴더 철자 유지).

## R358. SD 미러 증분은 "마지막 성공 미러 이후"에 받은 파일을 보낸다(최대 30일), 시각은 순간으로 비교, openrsync 전송 건수도 센다 (2026-11-20, 적용 계층: 운영)

> **규칙** `scripts/sync_storage_mirror.py::_recent_relpaths` — 대상 = `download_tasks` 중 받은 시각이 `max(now()-since_hours, 마지막 성공 미러 시작-1일)` 보다 앞서지 않은 것 중 이른 쪽 이후(30일 상한). `completed_at`(naive UTC, `datetime.utcnow`)은 `AT TIME ZONE 'UTC'`, `viewer_built_at`·`storage_sync_log.started_at`(naive 현지시각)은 세션 TZ 로 순간화해 비교한다. 목록 경로는 `on_disk_str` 로 디스크 철자로 바꾼다(R357). `_parse_stats` 는 openrsync 의 `Number of files transferred:` 도 읽는다.
> **발견** R357 조사 중 2026-11-16 이후 받은 파일 2,534개 중 **1,794개가 SD 미러에 없었다** — 전부 11-16 run 60 다운로드분(본문 XML 1,364·웹뷰 인쇄본 430). run 60 이 ⑦ 전에 죽었고 다음 미러(11-19 04:36)는 48시간 창 밖이었다. 게다가 `completed_at`(UTC)을 `now()`(KST)와 그대로 비교해 창이 9시간 더 좁았다. 미러 이력은 openrsync 출력 문구 차이로 매번 `files_sent=0` 이라 전송이 됐는지도 보이지 않았다.
> **보충** `python scripts/sync_storage_mirror.py --since-hours 144` 1회.
> **테스트** `tests/test_sync_storage_mirror_window_r358.py`(openrsync·GNU rsync 통계, 로컬 DB 롤백: 마지막 성공 이후 84시간 전 파일 포함, UTC 44시간 전 파일 포함).
