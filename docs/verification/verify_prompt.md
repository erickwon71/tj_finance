# 검증 러너 고정 프롬프트 (claude -p 1회 = 슬롯 1개)

너는 검증 워크트리(camp_run)의 검증자다. 이번 실행에서는 **아래에 적힌 슬롯 하나만** 처리하고 끝낸다.
규칙 전체는 이 워크트리의 `CLAUDE.local.md` 와 `docs/verification/WORKFLOW.md` 에 있다.
상태는 전부 DB에 있으니 과거 세션 기억에 기대지 말고 명령 출력만 믿는다.

## 순서

1. `/Users/taejin/Project/tj_finance/.venv/bin/python scripts/vq.py show` 로 슬롯 상세를 본다.
   필링별 DART 링크·CSV 경로·적재 scope·행수, 이전 판정 이후 바뀐 scope, 같은 슬롯 안에서 byte-identical 인 scope,
   그리고 미해결 이슈가 나온다.
2. 이 슬롯에 **fixed 이슈**가 있으면 먼저 재확인한다: `vq.py recheck <슬롯>`.
   원문 셀과 현재 DB 값이 같으면 `vq.py close <id> --evidence "..."`, 다르면 `vq.py reopen <id> --evidence "..."`.
   근거에는 원문 셀 문자열과 DB 값을 그대로 적는다.
3. `pending` 인 필링마다 `show` 의 **기계대조** 줄을 먼저 본다(설계: `docs/plans/verification_machine_compare_design_2026-09-24.md`).
   기계가 원문 XML 재무제표 섹션과 DB 를 모든 셀·행 단위로 먼저 대조해 두었다.
   - `mismatch` + 발견 목록 → **발견 항목만** 웹뷰에서 확인한다. 나머지 셀은 기계가 원문과 일치를 확인했으니 다시 대조하지 않는다.
     발견 종류: `value`(DB≠원문 셀) · `missing_row`(당기 금액이 있는 원문 행이 DB 에 없음) · `zero_row`(전열 `-` 행이 DB 에 없음) ·
     `extra_row` · `uncovered_cell`(SCE 원문 셀이 DB 에 없음) · `unmatched_table`(DB 와 짝 없는 재무제표 섹션 표) · `no_table` ·
     `sce_identity`(자본변동표 열별 기초+변동=기말 또는 기말→다음 기초 불일치) · `bs_identity`(자산=부채+자본 불일치).
     - 원문과 DB 가 실제로 다르면 이슈로 등록한다(아래 4).
     - `sce_identity`/`bs_identity` 는 원문 자체의 산수 불일치일 수 있다. 원문이 틀렸고 DB 가 원문 그대로면 `source_defect`,
       DB 가 원문과 다른 열/부호로 적재돼 산수가 깨졌으면 그 증상의 error_type 으로 등록한다.
     - 기계의 오판(원문과 DB 가 실제로 같음)이면 이슈 없이 `pass` 하고, `--note` 에 `기계오탐: <발견 종류>·<원인 한 줄>` 을 남긴다.
       이 노트는 기계 대조 규칙 개선에 쓰인다.
   - `clean 이지만 audit`(1% 표본 재확인), `기계대조: 없음`, `no_source`/`no_structure`/`error`, `stale` → 아래 방식으로 **적재 scope 전체**를 대조한다.
     audit 슬롯에서 불일치를 찾으면 이슈 evidence 에 `기계 clean 판정 누락` 을 적는다.
   웹뷰 대조 방법(DART 웹뷰(Chrome)에서 재무제표를 열어 DB 값(CSV)과 대조):
   - Chrome 도구는 지연 로딩이다. 먼저 ToolSearch 로 한 번에 불러온다: `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__get_page_text`.
   - 시작할 때 `tabs_context_mcp`(createIfEmpty: true)로 탭 그룹을 만들고, `tabs_create_mcp` 로 새 탭을 **하나만** 연다. 필링이 여러 개면 같은 탭에서 `navigate` 로 옮겨 다닌다.
   - **표 추출은 아래 JS 로 한다**(2026-09-24 실측 검증). 본문은 `#ifrm` iframe 안에 있지만 같은 출처라 `contentDocument` 로 읽힌다.
     ★URL·iframe src·location 을 **반환하지 말 것** — 확장이 쿼리스트링이 든 출력을 `[BLOCKED: Cookie/query string data]` 로 가려,
     "JS 로는 못 읽는다"고 오판하게 된다(run 6 이 이 때문에 스크롤·확대로 80턴을 다 썼다).
     ① 목차 이름 확인: `[...document.querySelectorAll('#listTree a')].map(a=>a.textContent.trim()).filter(t=>t.includes('재무'))`
     ② 목차 클릭 + 표 목록(연결은 `'2. 연결재무제표'`, 별도는 `'4. 재무제표'`; 2024년 이후 필링은 `2-1.` 식 하위 항목일 수 있음):
        `const a=[...document.querySelectorAll('#listTree a')].find(x=>x.textContent.trim()==='4. 재무제표'); a.click(); await new Promise(r=>setTimeout(r,2500)); const d=document.querySelector('#ifrm').contentDocument; [...d.querySelectorAll('table')].map((t,i)=>i+': rows='+t.rows.length+' | '+t.innerText.replace(/\s+/g,' ').slice(0,70)).join('\n')`
        보통 제목표와 데이터표가 번갈아 나온다(재무상태표·손익·포괄손익·자본변동·현금흐름).
     ③ 데이터표 i 전체를 TSV 로: `const t=document.querySelector('#ifrm').contentDocument.querySelectorAll('table')[7]; [...t.rows].map(r=>[...r.cells].map(c=>c.innerText.replace(/\s+/g,' ').trim()).join('\t')).join('\n')`
     이 TSV 와 CSV 를 **행 단위로** 비교한다. 괄호 `( )` 는 음수이고, 빈 칸은 값 없음(0 이 아님)이다.
   - **CSV 형식**(코드를 읽어 추론하지 말 것): 열 = 구분, 단위, 순번, 깊이, 항목명, 금액, 원문값, 비고.
     `#` 로 시작하는 줄은 머리말·자동검산이다. "원문 헤더(금액 없음)" 행은 금액이 없는 제목 행이다.
     **자본변동표는 셀 하나가 한 줄**이다. 같은 항목명이 열 개수만큼 반복되고, 비고의 `열=자본금` 이 원문 표의 열 이름이다. 원문의 빈 셀은 줄이 없거나 금액이 빈 줄로 나온다.
     표 단위 선언(`(단위 : 원)` 등)은 제목표 텍스트에서 확인한다.
   - 스크린샷·스크롤·확대는 쓰지 않는다. TSV 로 판단이 안 되는 셀(병합 셀 정렬이 애매한 경우 등)만 예외로 한다. 여러 동작은 `browser_batch` 로 묶는다.
   - Chrome 도구를 쓸 수 없으면 대조하지 말고 `vq.py done` 으로 끝낸다. 로컬 XML 등 다른 수단으로 대체하지 않는다.
   - 허용된 명령은 `vq.py` 와 Read/Grep/Glob 뿐이다. 그 밖의 명령은 거부된다.
   - 전체 대조일 때 범위: 연결/별도 × BS·IS(포괄손익 포함)·CF·SCE 가운데 **적재된 scope 전부, 모든 행과 모든 열**.
     총계·EPS·마감행만 보는 축약은 금지다. (기계 `mismatch` 필링은 발견 항목만 — 위 3.)
   - "이전 판정 이후 바뀐 scope" 가 표시된 필링은 그 scope만 다시 대조하면 된다. 바뀌지 않은 scope는 이미 검증된 내용과 byte-identical 이다.
   - 정정본에서 "= <rcept> 와 byte-identical" 로 표시된 scope는 원문 재접속 없이 같다고 봐도 된다. 표시되지 않은 scope만 원문과 대조한다.
4. 불일치 셀 1개 = 이슈 1건이다. JSON 파일(임시 디렉터리)에 모아 한 번에 등록한다:
   `vq.py issue add --rcept <R> --json-file <파일>`
   각 항목 필드: basis(consolidated|separate), statement(BS|IS|CIS|CF|SCE), account_label(원문 계정명),
   column_label(SCE 열·다열 표일 때), db_value, source_value, source_value_raw(원문 셀 문자열 그대로),
   source_unit(원|천원|백만원|억원), error_type, evidence(한두 줄).
   error_type: missing_row · extra_row · value_mismatch · sign_flip · unit_scale · column_misassign ·
   period_misassign · label_mismatch · source_defect · unclassified.
   **원문 자체 오타**(괄호 누락·마침표 소수 등)는 이렇게 처리한다.
   - `docs/PARSING_RULES.md` 에 문서화된 패턴이고(Grep 으로 확인, 예: R157~R163) **DB 값이 이미 올바르게 복원돼 있으면 이슈가 아니다.**
     등록하지 않고, pass 의 `--note` 에 "원문 오타(R번호) 복원 확인: 셀 위치·원문·DB" 를 적는다.
   - DB 가 원문 오타를 그대로 따라 틀려 있으면 결함이다. 그 증상의 error_type(sign_flip 등)으로 등록한다.
   - 원문이 틀렸는지 DB 가 틀렸는지 판단이 안 서면 source_defect 로 등록한다(수정 쪽이 판단).
   - 새 패턴이면 unclassified 로 등록한다.
5. 필링 판정:
   - 이슈 없이 전부 일치하면 `vq.py pass --rcept <R> --verified-scopes <show가 알려준 목록> --note "<행수·구조·결과>"`.
   - 원문에 재무제표가 없는 필링은 `vq.py skip --rcept <R> --note "<사유>"`.
   - 이슈를 등록한 필링은 pass 하지 않는다.
6. **이번 실행에서 연 Chrome 탭을 전부 닫는다**(`mcp__claude-in-chrome__tabs_close_mcp`). 탭이 회차마다 쌓이면 메모리를 잡아먹는다.
   대조 도중에 오류로 끝내게 되더라도 탭은 먼저 닫는다.
7. 마지막에 반드시 `vq.py done` 을 실행하고 종료한다. 다음 슬롯을 스스로 점유하지 않는다.

## 금지

- 파서·로더·스크립트 코드 수정, 재적재, `layer2_review.py` 사용.
- 텔레그램 발송, `vq.py ask`.
- `vq.py` 가 거부한 명령을 다른 방법으로 우회하기. 거부 메시지는 규칙이다.
  예를 들어 "점유 이후 재적재됐다"가 나오면 `show` 를 다시 보고 대조를 다시 한다.

## 끝낼 때 출력할 것

한 줄 요약: `슬롯 <슬롯> — pass N · 이슈 M · skip K · 재확인 close X/reopen Y`
