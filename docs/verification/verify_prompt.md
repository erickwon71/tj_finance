# 검증 러너 고정 프롬프트 (claude -p 1회 = 슬롯 1개)

너는 검증 워크트리(camp_run)의 검증자다. 이번 실행에서는 **아래에 적힌 슬롯 하나만** 처리하고 끝낸다.
규칙 전체는 이 워크트리의 `CLAUDE.local.md` 와 `docs/verification/WORKFLOW.md` 에 있다.
상태는 전부 DB에 있으니 과거 세션 기억에 기대지 말고 명령 출력만 믿는다.

## 순서

1. `/Users/taejin/Project/tj_finance/.venv/bin/python scripts/vq.py show` 로 슬롯 상세를 본다.
   필링별 DART 링크·CSV 경로·적재 scope·행수, 이전 판정 이후 바뀐 scope, 같은 슬롯 안에서 byte-identical 인 scope,
   그리고 미해결 이슈가 나온다.
   `show` 에 **"이미 결론난 셀"** 이 있으면, 그 셀은 수정 쪽이 원문결함·오탐으로 결론낸 것이다(코드수정 불필요). 다시 조사하거나 등록하지 않는다.
   기계 발견이 그 셀이면 건너뛴다. 실수로 등록해도 `issue add` 가 "등록 안 함" 으로 걸러 준다.
   그 필링에 다른 불일치가 없으면 이슈 없이 `pass` 한다.
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
     - `sce_identity`/`bs_identity` 는 아래 4번의 **판정표**로 처리한다. 산수가 깨졌는데 표의 1·2행(이슈 아님)에 해당한다는 근거 없이
       노트만 남기고 pass 하면 규칙 위반이다(사용자 결정 (가) 2026-10-09: 원문 산수 불일치도 반드시 등록한다).
       확인 방법: 자본변동표는 **열마다** `기초 + 변동 합계 = 기말` 을 직접 계산한다(합계 열만 보지 않는다. 원문 표시 단위(원·천원·백만원) 기준으로 차이가 0 또는 ±1 이면 닫힌 것이다 — ±1 은 반올림 차이로 본다).
       당기·전기 블록이 둘이면 블록마다, 연결·별도가 둘이면 각각 한다. pass 노트에 "열 N개 롤포워드 확인" 을 적는다.
     - 기계의 오판(원문과 DB 가 실제로 같음)이면 이슈 없이 `pass` 하고, `--note` 에 `기계오탐: <발견 종류>·<원인 한 줄>` 을 남긴다.
       이 노트는 기계 대조 규칙 개선에 쓰인다.
     - **발견이 많을 때(필링당 10건 이상)**: 셀 사실형 발견(`value`·`missing_row`·`zero_row`·`uncovered_cell`·`extra_row`·`sign_omitted`)은
       종류마다 대표 3건만 웹뷰로 확인한다. 확인한 표본이 모두 기계와 같으면, 그 종류 전체를 한 번에 등록한다:
       `vq.py machine issues-json --rcept <R> --kinds <확인한 종류들> --out <임시 디렉터리>/<R>_issues.json` →
       `vq.py issue add --rcept <R> --json-file <그 파일>`. 표본 중 하나라도 기계가 틀렸으면 그 종류는 하나씩 확인한다.
       `sce_identity`·`bs_identity`·`unmatched_table`·`no_table` 은 판단이 필요하므로 직접 보고 등록한다.
     - 이슈를 명령 인자로 하나씩 등록하지 않는다(턴 낭비). 언제나 JSON 파일 한 번으로 등록한다.
     - **`Write` 가 로그 디렉터리 안에서도 거부될 수 있다(실측: 2026-10-01 거의 모든 run).** 거부되면 재시도하지 말고
       즉시 `vq.py issue add --rcept <R> --basis ... --statement ... --account-label ... --column-label ...
       --db-value ... --source-value ... --source-value-raw ... --source-unit ... --error-type ... --evidence ...`
       형태로 이슈를 하나씩 등록한다(턴은 더 들지만 유일하게 항상 되는 경로). `machine issues-json` 출력(기계 findings 10건↑ 일괄등록)은
       `vq.py` 자체가 파일을 쓰므로 영향받지 않는다 — 영향받는 건 모델이 직접 `Write` 로 만드는 JSON 뿐이다.
   - `clean 이지만 audit`(1% 표본 재확인), `no_source`/`no_structure`/`error` → 아래 방식으로 **적재 scope 전체**를 대조한다.
     audit 슬롯에서 불일치를 찾으면 이슈 evidence 에 `기계 clean 판정 누락` 을 적는다.
   - `기계대조: 없음` 또는 `stale`(재적재 이후) 필링은 **대조하지 않고 그대로 둔다**. 슬롯이 pending 으로 돌아가면 기계가 먼저 대조하고,
     불일치만 다시 모델에게 온다. fixed 이슈 재확인(위 2)만 하고 `done` 한다.
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
4. 불일치 셀 1개 = 이슈 1건이다. JSON 파일(로그 디렉터리)에 모아 한 번에 등록한다:
   `vq.py issue add --rcept <R> --json-file <파일>`
   **`Write` 가 거부되면 위 3-3의 지침대로 개별 플래그(`--account-label` 등)로 하나씩 등록한다 — 등록 없이 포기하지 않는다.**
   각 항목 필드: basis(consolidated|separate), statement(BS|IS|CIS|CF|SCE), account_label(원문 계정명),
   column_label(SCE 열·다열 표일 때), db_value, source_value, source_value_raw(원문 셀 문자열 그대로),
   source_unit(원|천원|백만원|억원), error_type, evidence(한두 줄).
   error_type: missing_row · extra_row · value_mismatch · sign_flip · unit_scale · column_misassign ·
   period_misassign · label_mismatch · source_defect · unclassified.
   **전열 `-`(0) 행이 DB 에 없는 것은 이슈가 아니다**(zero_row 정책 A안, 사용자 결정 2026-09-25). 값·총계 영향이 없으므로 등록하지 않는다.
   **판정표** — 원문 오타·산수 불일치·부호 혼재처럼 **항등식이 관련된 불일치**는 전부 이 표 하나로 정한다.
   (셀 값만 다른 단순 불일치 — 단위·열 위치·누락 행 등 — 는 위 error_type 목록에서 증상에 맞는 것을 고른다.)
   - D = DB 값, S = 원문 셀 값, T = **참값**. 참값은 아래 세 가지가 **모두** 성립할 때만 있다고 본다(`docs/PARSING_RULES.md` R162 와 같은 기준).
     (a) 그 셀을 T 로 바꾸면 항등식이 닫힌다(차이 0 또는 표시 단위 ±1). (b) 닫히게 하는 부호·값 조합이 하나뿐이다.
     (c) 같은 필링 BS/IS 의 같은 항목, 또는 같은 표의 이월잔액(전기말 = 당기초)이 방향을 뒷받침한다.
     하나라도 아니면 T 는 없다. 짐작은 증명이 아니다.
   - "복원 가능한 오류" = 괄호 누락·마침표 소수 같은 **표기 손실**로, 파서가 규칙으로 되돌릴 수 있는 것(R157~R163 계열, Grep 으로 확인).
     원문 숫자 자체가 틀린 경우(합계가 안 맞는 숫자가 적힌 경우)는 참값을 짐작할 수 있어도 복원 가능한 오류가 아니다.

   | # | 상황 | 판정 |
   |---|---|---|
   | 1 | D = S 이고 항등식이 닫힘 (차이 0 또는 표시 단위 ±1) | 이슈 아님 |
   | 2 | D ≠ S 이고 D 로 항등식이 닫힘 (문서화된 복원) | 이슈 아님. pass 노트에 셀 위치·원문·DB 와 **검산식 숫자**(`기초 ○ + 변동 ○ = 기말 ○`)를 적는다 |
   | 3 | D = S 이고, 원인이 **복원 가능한 표기 손실**이며 T 가 있고 T ≠ S 인데 파서가 복원하지 않음 | 증상형 error_type (`sign_flip` 등). 틀린 **셀마다** 1건 |
   | 4 | D ≠ S 인데 D 로도 항등식이 안 닫힘, 또는 같은 행에서 일부 셀만 복원돼 부호가 섞임 | 증상형 error_type (`sign_flip` 등). 틀린 **셀마다** 1건 |
   | 5 | D = S 이고 항등식이 깨졌는데 3행이 아님 — T 가 없거나(위 a·b·c 중 하나라도 불성립), 원문 숫자 자체가 틀린 경우 | `source_defect`. 깨진 **항등식마다** 1건 |
   | 6 | 위 어디에도 맞지 않는 새 구조 문제 | `unclassified` |

   - 판단이 안 서면 5행(`source_defect`)으로 등록한다(수정 쪽이 판단). `unclassified` 는 6행에만 쓴다.
   - **5행 등록 단위**: (필링, basis, scope, 당기·전기 블록, 열)당 1건이고 기말 셀에 등록한다. 기말→다음 기초 이월 불일치는 기초 셀에,
     BS 자산=부채+자본 불일치는 (필링, basis)당 1건을 총계 행에 등록한다. 같은 원인이라도 열이 다르면 따로 등록한다.
     evidence 에는 `기초 ○ + 변동 합계 ○ = ○, 기말 ○, 차이 ○` 를 적는다.
   - 전열 `-`(0) 행이 DB 에 없는 것은 위 표와 별개로 이슈가 아니다(위 zero_row 정책).
5. 필링 판정:
   - 이슈 없이 전부 일치하면 `vq.py pass --rcept <R> --verified-scopes <show가 알려준 목록> --note "<행수·구조·결과>"`.
   - 원문에 재무제표가 없는 필링은 `vq.py skip --rcept <R> --note "<사유>"`.
   - **적재 0행 필링**(show 의 적재 행 0·기계대조 `no_source`·파싱 소스 pdf)은 incomplete 로 두지 않는다.
     원문을 열어 재무제표가 있으면 `missing_row` 이슈 1건(필링 전체 미적재, 대표 행 1개)을 등록하고,
     없으면 위처럼 skip 한다. 원문 확인 없이 `done` 하지 않는다.
   - 이슈를 등록한 필링은 pass 하지 않는다.
6. **이번 실행에서 연 Chrome 탭을 전부 닫는다**(`mcp__claude-in-chrome__tabs_close_mcp`). 탭이 회차마다 쌓이면 메모리를 잡아먹는다.
   대조 도중에 오류로 끝내게 되더라도 탭은 먼저 닫는다.
7. 마지막에 반드시 `vq.py done` 을 실행하고 종료한다. 다음 슬롯을 스스로 점유하지 않는다.

## 금지

- 파서·로더·스크립트 코드 수정, 재적재, `layer2_review.py` 사용.
- 텔레그램 발송, `vq.py ask`.
- `vq.py` 가 거부한 명령을 다른 방법으로 우회하기. 거부 메시지는 규칙이다.
  예를 들어 "점유 이후 재적재됐다"가 나오면 `show` 를 다시 보고 대조를 다시 한다.
- 한 턴에 Bash(`vq.py ...`)를 여러 개 동시에(병렬) 부르지 말 것 — 순차로 하나씩 호출한다(권장 상한 5개 이하).
  이슈를 여러 건 등록·종료·재오픈해야 해도 반복 병렬호출 대신 위 3-3처럼 JSON 파일 일괄등록(`issue add --json-file`)을 쓴다.
  (2026-09-26: 한 턴에 ~14개 병렬 Bash 호출로 이후 세션 내내 Bash 전체가 거부된 사고가 있었다.)
- **허용되지 않은 명령(`grep`/`find`/`mkdir` 등을 Bash 로, 또는 로그 디렉터리 밖에 `Write`)이
  거부되는 것은 정상이다** — 애초에 허용 목록 밖이라 항상 거부된다. 이때는 포기하지 말고
  그 작업에 맞는 허용된 도구(Grep/Glob/Read, 로그 디렉터리 안 Write)로 바꿔서 계속한다.
  ★2026-09-26: 이 정상적인 단발성 거부를 아래 "즉시 멈춘다" 규칙과 혼동해, `grep`/`find` 한 번
  막힌 것만으로 40~50턴 작업한 세션을 통째로 포기한 사고가 2건 있었다(런 408/409) — 실제로는
  그 다음 `vq.py` 호출이 막혔는지 확인도 안 하고 포기한 것. **`vq.py` 명령 자체가 막힌 게 아니면
  절대 포기하지 않는다.**
- `vq.py` 로 시작하는 **허용된 명령 자체**가 `Permission to use Bash has been denied` 로 거부되면
  (즉 항상 되던 `vq.py show`/`vq.py close` 같은 호출이 막히면) **그때만** 재시도하지 말고 즉시
  멈춘다. 같은 거부가 세션 나머지 내내(읽기전용 `vq.py show` 포함) 반복되므로, `vq.py done` 도
  다시 시도하지 말고 지금까지 처리한 내용만 마지막 출력(아래 형식)으로 요약하고 종료한다.

## 끝낼 때 출력할 것

한 줄 요약: `슬롯 <슬롯> — pass N · 이슈 M · skip K · 재확인 close X/reopen Y`
