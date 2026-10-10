# 본문 XML 없는 필링 = 웹뷰 인쇄본 적재 + 6개월 재시도 (2026-10-10)

> 상태: 사용자 결정 반영, 구현 중. 근거: `docs/PARSING_RULES.md` R0-2(계층2 = 인쇄값).

## 1. 문제
- DART 원본 묶음에 본문 XML이 없는 필링(XBRL만 1,639, PDF만 462)은 계층2 가 XBRL/PDF 에서 왔다.
- XBRL 은 인쇄본이 아니다: 차감·유출 항목 부호가 반대, 계정명이 표준 라벨(검증 이슈 sign_flip 약 1,170 · XBRL 라벨 약 1,550).
- 웹뷰(`report/viewer.do`)는 인쇄 문서를 DART XML 렌더링 그대로 준다 → `fin2/extract/viewer_xml.py` 가 DART XML 골격으로 감싸 본 파서가 읽는다.
  시험(피노 20150827000474): BS/IS/CF 277칸 — XBRL 과 같음 246 · 부호만 다름 30(인쇄 관례) · 그 밖 0.
- 기존 정책: 2026-08-19([014])·2026-09-13(R103 PDF/XBRL 만) — document.xml 을 **무기한 매일** 재시도, 대체 없음. 실제로 뒤늦게 올라온 사례 있음(xbrl 폴백 1,841건이 나중에 .xml 확보).

## 2. 결정 (사용자 2026-10-10)
| # | 결정 |
|---|---|
| 1 | 본문 XML 이 없으면 **그날 웹뷰 XML 을 만들어 적재**(출처 표시). XBRL·PDF 는 보관(계층3 증거) |
| 2 | document.xml 재시도는 **6개월(180일)** 까지. 넘으면 웹뷰 출처로 확정(재시도 중단) |
| 3 | 재시도 중 document.xml 이 올라오면 **원본 XML 로 자동 재적재** |
| 4 | 재시도 때 웹뷰 목차의 재무제표 섹션 서명(제목·길이)을 비교 — 바뀌면 웹뷰 XML 재생성·재적재 |
| 5 | 웹뷰 출처 필링이 든 슬롯은 기계 clean 이어도 **audit 10%**(변환기 오류는 파서·기계가 같은 파일을 읽어 못 잡으므로 모델이 웹뷰로 직접 확인) |
| 6 | PDF-only 중 [첨부정정] 353건은 섹션 구성이 달라 별도 단계 |

## 3. 구현
- `download_tasks` 컬럼: `viewer_xml_path`, `viewer_sig`, `viewer_built_at`, `layer2_reload_pending`.
- **웹뷰 출처 필링** = `viewer_xml_path IS NOT NULL` 이고 완료된 본문 XML(`status='completed' AND file_type='xml'`)이 없는 필링.
- `collector/viewer_source.py`: 웹뷰 XML 생성(`build_viewer_xml`)·목차 서명(`toc_sig`)·출처 판정 SQL.
- 다운로더(`collector/downloader.py`): [014]·R103 대기 처리 시 웹뷰 XML 생성/서명 비교 → 바뀌면 재적재 표시. 대기 재시도는 `xml_pending_since` 180일까지만. `_mark_completed` 는 웹뷰 출처였던 필링이면 재적재 표시.
- 적재: 데일리 ④-4(`collector/xbrl_instance_lines_sync.py`, 두 call site·계층3 재빌드 대상에 이미 배선)가 웹뷰 출처 필링을 XML 경로(인쇄값 + 계층3 보정, 주석 포함)로 적재하고, XBRL 은 웹뷰가 없는 필링만. 대상 선택 `app/data/collect.py::needs_xbrl_instance_corps` 도 같은 기준.
  ④-3(`collector/note_lines_sync.py`)은 `layer2_reload_pending` 인 본문 XML 필링을 이미 적재됐어도 다시 적재(원본 XML 등장 시 자동 재적재).
- 재적재(`ops._reload_rcept`)·기계대조(`machine_pass._source_path`)는 본문 XML 이 없으면 웹뷰 XML 을 원문으로 쓴다.
- 기존 수집분(`logs/r0_2/viewer_xml_manifest.jsonl`): 경로·서명 등록 → document.xml 1회 재시도(없으면 위 6개월 대기로) → 재적재 → 계층3 재빌드·비교 → 기계대조.
