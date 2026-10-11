# 운영 — 수집 대상·파이프라인 배선·재적재 규약

> 이 파일은 `docs/PARSING_RULES.md` 에서 **내용을 바꾸지 않고 옮긴** 절들이다(2026-10-12, `scripts/split_parsing_rules.py`). 규칙 번호·본문은 그대로이고, 분류 기준은 [판정 순서](../plans/parsing_rules_split_2026-10-11.md#분류-기준--판정-순서-사용자-확정-2026-10-11). 새 규칙도 같은 판정 순서로 파일을 고르고 머리에 `적용 계층:` 을 적는다.
> 규칙 문서 수정은 **main 과 camp_err_review 에서만** 한다(사용자 결정 2026-10-11).

---

## R7. 유니버스

**규칙** — 현재 시점 KOSPI/KOSDAQ 상장 **보통주**, 개인이 거래 가능한 기업.
**국내 상장 외국기업 제외** — 식별 = `stock_code` 가 **'9' 로 시작**(900xxx 직상장·950xxx DR/원주).

**근거** — `CLAUDE.md` 개발 목표. 사용자 결정 2026-07-19.
`collector/corp_collector.py:_is_foreign_stock()` — sync 후보 필터 양쪽 브랜치에 적용.

**어기면** — 서식이 이질적이라 파싱 정합이 낮다(로스웰 73%). 기업리스트 갱신 때마다 재유입된다.

---

## R8. 새 파서/로더 추가 3층 (자동 반영 안 됨)

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
