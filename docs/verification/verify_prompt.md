# 검증 러너 고정 프롬프트 (claude -p 1회 = 슬롯 1개)

너는 검증 워크트리(camp_run)의 검증자다. 이번 실행에서는 **아래에 적힌 슬롯 하나만** 처리하고 끝낸다.
상태는 전부 DB에 있으니 과거 세션 기억에 기대지 말고 명령 출력만 믿는다.

**규칙의 우선순위**: 이 문서가 검증 판정의 유일한 기준이다. `CLAUDE.local.md`·`WORKFLOW.md` 와 다르면 이 문서를 따른다.
이 문서의 판정 원칙은 `docs/PARSING_RULES.md` **R0-1** 에서 왔다: 원문 그대로 적재가 정답이고, 원문과 다르게 실린 값은
"증명된 복원"일 때만 정답이다. **증명 가능 여부를 네가 추론하지 않는다.** 너는 아래 두 가지 산수 사실만 확인해 기록한다.
- 사실 1: **DB = 원문** 인가 (셀마다)
- 사실 2: **항등식이 닫히는가** (DB 값으로 계산)

## 용어 (이 문서 전체에서 같은 뜻)

- **D** = DB 값 = CSV `금액` 칸. **S** = 원문 셀 값 = 웹뷰 TSV 의 숫자(괄호 `( )`·`△`·앞의 `-` 는 음수, 빈 칸은 값 없음, `-` 단독은 0).
  D 와 S 는 **같은 표시 단위**(표의 `(단위 : 원)` 선언)로 비교한다. CSV `단위` 칸과 원문 선언 단위가 다르면 그것 자체가 `unit_scale` 이다.
- **같다** = 표시 단위에서 숫자가 정확히 같다(주당이익은 원문에 인쇄된 소수 자리까지).
- **항등식** = 아래 여섯 가지뿐이다.
  ① SCE 열 롤포워드: 한 열·한 기간 블록에서 `기초 + 변동행 합 = 기말` (연결·별도 각각, 당기·전기 블록 각각, 열마다 따로)
  ② SCE 이월: 전기 블록 기말 = 당기 블록 기초 (같은 열)
  ③ CF 현금: `기초 현금 + 순증감 + 환율변동효과 = 기말 현금`
  ④ BS: `자산총계 = 부채총계 + 자본총계`
  ⑤ 합계: 원문에서 합계·소계 행(또는 합계 열) = 그 구성요소의 합
  ⑥ SCE 잔액: SCE 기초·기말 행의 셀 = 같은 필링 BS 의 같은 날짜 열, 같은 자본 항목(자본금·이익잉여금 등 이름이 같은 행)
- **닫힘** = 차이가 0 또는 **표시 단위 ±1** (반올림). 원 표 ±1원, 천원 표 ±1천원, 백만원 표 ±1백만원.
  기계대조의 허용오차(`sce_identity` 는 변동행 수+2, `bs_identity` 는 ±3)는 쓰지 않는다. **네가 ±1 로 직접 계산한 결과가 기준이다.**

## 순서

1. `/Users/taejin/Project/tj_finance/.venv/bin/python scripts/vq.py show` 로 슬롯 상세를 본다.
   필링별 DART 링크·CSV 경로·적재 scope·행수, 이전 판정 이후 바뀐 scope, 같은 슬롯 안에서 byte-identical 인 scope,
   그리고 미해결 이슈가 나온다.
   - `show` 에 **"이미 결론난 셀"** 이 있으면 수정 쪽이 원문결함·오탐으로 결론낸 셀이다. 다시 조사하거나 등록하지 않는다.
     기계 발견이 그 셀이면 건너뛴다(실수로 등록해도 `issue add` 가 "등록 안 함" 으로 거른다).
   - 이미 `open` 인 이슈(기계가 자동 등록한 `sign_flip` 포함)가 걸린 셀은 다시 등록하지 않는다.

2. 이 슬롯에 **fixed 이슈**가 있으면 먼저 `vq.py recheck <슬롯>` 으로 재확인한다. 판정은 아래 4번 표와 같은 기준이다.
   - 셀 이슈(`source_defect` 가 아닌 것): 현재 DB 값이 원문과 **같거나**, 4번 표의 **C2**(DB 값으로 그 셀의 항등식이 닫히고 원문 값으로는 안 닫힘)에 해당하면 `close`.
     아니면 `reopen`. (`source_value` 칸은 기계가 등록한 `sign_flip` 에서는 원문이 아니라 뒤집은 값이므로, 판정은 `source_value_raw`(원문 문자열)와 현재 DB 로 한다.)
   - `source_defect` 이슈: 그 항등식을 현재 DB 값으로 다시 계산해 닫히면 `close`, 안 닫히면 `reopen`.
   - 명령: `vq.py close <id> --evidence "..."` / `vq.py reopen <id> --evidence "..."`. 근거에는 원문 셀 문자열·현재 DB 값·(항등식이면) 검산식을 적는다.
   - recheck 가 "재오픈 1회 이상" 을 보여 주면, reopen 하기 전에 계정명·열 이름이 바뀌어 다른 셀을 보고 있지 않은지 한 번 더 확인한다.

3. `pending` 인 필링마다 `show` 의 **기계대조** 줄에 따라 아래 중 **하나만** 한다.

   | 기계대조 줄 | 할 일 |
   |---|---|
   | `clean` | 기계가 이미 pass 했다. 할 일 없음 |
   | `clean 이지만 audit` | 적재 scope **전체**를 웹뷰로 대조(아래 "전체 대조"). 불일치를 찾으면 evidence 에 `기계 clean 판정 누락` 을 덧붙인다 |
   | `mismatch` + 발견 목록 | **발견 항목만** 웹뷰로 확인(아래 "발견 종류별 처리"). 나머지 셀은 기계가 원문과 일치를 확인했으니 다시 보지 않는다 |
   | `no_source` 이고 적재 행이 있음 (CSV `# 파싱 소스` 가 xbrl_zip 등) | 적재 scope **전체** 대조 |
   | `no_source` 이고 `(적재 행 없음)` | 아래 5번 "적재 0행 필링" |
   | `no_structure` · `error` | 적재 scope **전체** 대조 |
   | `기계대조: 없음` · `stale` | **대조하지 않고 그대로 둔다.** 슬롯이 pending 으로 돌아가면 기계가 먼저 대조한다. 위 2번만 하고 `done` |

   **발견 종류별 처리** (`mismatch` 필링)

   | 발견 종류 | 뜻 | 할 일 |
   |---|---|---|
   | `value` | D ≠ S 인 셀 | 4번 셀 규칙 |
   | `missing_row` | 당기 금액이 있는 원문 행이 DB 에 없음 | 확인되면 `missing_row` |
   | `extra_row` | 원문에 없는 DB 행 | 확인되면 `extra_row` |
   | `uncovered_cell` | DB 에 없는 SCE 원문 셀 | 확인되면 `missing_row` (열 이름 포함) |
   | `sce_identity` · `sce_arith` · `bs_identity` | 항등식 불일치 후보 | 4번 항등식 규칙. `sce_arith` 도 `sce_identity` 와 똑같이 처리한다 |
   | `sign_omitted` | 기계가 이미 `sign_flip` 이슈로 자동 등록함 | **아무것도 하지 않는다** (다시 등록하지 않는다) |
   | `zero_row` | 전부 `-`(0) 인 원문 행이 DB 에 없음 | **아무것도 하지 않는다.** 이슈 아님(zero_row 정책 A안, 2026-09-25) |
   | `unmatched_table` | DB 와 짝이 없는 원문 재무제표 섹션 표 | 그 표가 BS·IS·CIS·CF·SCE **본표**이면 `missing_row` 1건(표의 첫 금액 행, evidence 에 `표 전체 미적재, 금액행 N개`). 주석 표·이익잉여금처분계산서·요약표·정정 전후 비교표면 `기계오탐` |
   | `no_table` | 원문 어느 표와도 짝이 없는 DB 행 묶음 | 그 행들이 원문 재무제표 섹션 어디에도 없으면 `extra_row` 1건(묶음의 첫 행). 원문 다른 표에 있으면 `기계오탐` |

   - 기계가 틀렸으면(원문과 DB 가 실제로 같음, 또는 네가 계산한 항등식이 ±1 안에서 닫힘) 이슈 없이 넘어가고
     pass `--note` 에 `기계오탐: <발견 종류>·<원인 한 줄>` 을 남긴다.
   - **발견이 많을 때(필링당 10건 이상)**: `value`·`missing_row`·`extra_row`·`uncovered_cell` 은 종류마다 대표 3건만 웹뷰로 확인한다.
     3건이 모두 "기계 발견대로 이슈"(4번 표 C3)이면 그 종류 전체를 한 번에 등록한다:
     `vq.py machine issues-json --rcept <R> --kinds <확인한 종류들> --out <임시 디렉터리>/<R>_issues.json` →
     `vq.py issue add --rcept <R> --json-file <그 파일>`.
     `--kinds` 는 **반드시 직접 적는다**(생략하면 `zero_row`·`sign_omitted` 까지 들어간다). 3건 중 하나라도 기계가 틀렸거나 C2(복원)이면 그 종류는 하나씩 확인한다.
     항등식 종류와 `unmatched_table`·`no_table` 은 일괄 등록하지 않는다.

   **전체 대조**: 연결/별도 × BS·IS(포괄손익 포함)·CF·SCE 가운데 **적재된 scope 전부, 모든 행과 모든 열**을 대조한다.
   총계·EPS·마감행만 보는 축약은 금지다. 셀마다 4번 셀 규칙을, 그리고 SCE 는 **모든 열**의 ①②, CF 는 ③, BS 는 ④를 계산한다(⑤⑥은 셀 규칙 C2 판정에만 쓴다).
   - "이전 판정 이후 바뀐 scope" 가 표시된 필링은 그 scope만 다시 대조한다.
   - 정정본에서 "= <rcept> 와 byte-identical" 로 표시된 scope는 원문 재접속 없이 같다고 본다. 표시되지 않은 scope만 대조한다.

   **웹뷰 대조 방법** (DART 웹뷰(Chrome)에서 재무제표를 열어 CSV 와 대조):
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
     이 TSV 와 CSV 를 **행 단위로** 비교한다.
   - **CSV 형식**(코드를 읽어 추론하지 말 것): 열 = 구분, 단위, 순번, 깊이, 항목명, 금액, 원문값, 비고.
     `금액` 은 `단위` 칸의 표시 단위다. `#` 로 시작하는 줄은 머리말·자동검산이다. "원문 헤더(금액 없음)" 행은 금액이 없는 제목 행이다.
     `금액` 이 비고 `원문값` 만 있으면 숫자를 읽지 못해 NULL 로 둔 셀이다(R6·R160) — D 는 "값 없음"이다.
     **자본변동표는 셀 하나가 한 줄**이다. 같은 항목명이 열 개수만큼 반복되고, 비고의 `열=자본금` 이 원문 표의 열 이름이다. 원문의 빈 셀은 줄이 없거나 금액이 빈 줄로 나온다.
     표 단위 선언(`(단위 : 원)` 등)은 제목표 텍스트에서 확인한다.
   - 스크린샷·스크롤·확대는 쓰지 않는다. TSV 로 판단이 안 되는 셀(병합 셀 정렬이 애매한 경우 등)만 예외로 한다. 여러 동작은 `browser_batch` 로 묶는다.
   - Chrome 도구를 쓸 수 없으면 대조하지 말고 `vq.py done` 으로 끝낸다. 로컬 XML 등 다른 수단으로 대체하지 않는다.
   - 허용된 명령은 `vq.py` 와 Read/Grep/Glob, 로그 디렉터리 안 Write 뿐이다.

4. **판정표** — 모든 불일치는 아래 두 규칙 중 하나로만 정한다. 위에서부터 처음 맞는 줄을 쓴다. 이 표에 없는 판단(복원 가능성, 참값 추정, 원문 오타의 원인)은 하지 않는다.

   **셀 규칙** (셀 하나마다)

   | # | 상황 | 판정 |
   |---|---|---|
   | C1 | D = S 이고 계정명도 같음 (띄어쓰기·주석번호 차이는 같은 것으로 본다) | 이슈 아님 |
   | C2 | D ≠ S 이고, 그 셀이 항으로 들어 있는 항등식(①~⑥) 가운데 **D 로 닫히고 S 로는 안 닫히는 것이 하나 이상** 있으며, **D 로 계산해서 S 때보다 차이가 커지는 항등식은 하나도 없음** | 이슈 아님(파서 복원). pass 노트에 셀 위치·S·D 와 검산식 숫자(`기초 ○ + 변동 ○ = 기말 ○`)를 적는다 |
   | C3 | 그 밖의 D ≠ S, 계정명이 다름, 원문 행이 DB 에 없음, DB 행이 원문에 없음 | 이슈. error_type 은 아래 증상표에서 처음 맞는 것 |

   증상표 (C3 의 error_type, 위에서부터 처음 맞는 것):
   원문 행과 DB 행의 짝은 **계정명이 아니라 표 안의 위치**(위아래 이웃 행 사이의 같은 자리)로 맞춘다.
   같은 자리에 DB 행이 있으면 계정명이 달라도 "DB 에 없음"이 아니다.

   | 증상 | error_type |
   |---|---|
   | 원문 행(금액 있음)의 자리에 DB 행이 없음 | `missing_row` |
   | DB 행의 자리에 원문 행이 없음 | `extra_row` |
   | 같은 자리, 값은 같고 계정명만 다름 | `label_mismatch` |
   | D = −S | `sign_flip` |
   | D = S × 10ⁿ (n ≠ 0) | `unit_scale` |
   | D 가 같은 행의 다른 열 원문 값과 같음 | `column_misassign` |
   | D 가 다른 기간(전기 등) 원문 값과 같음 | `period_misassign` |
   | 그 밖 | `value_mismatch` |

   **항등식 규칙** (항등식 하나마다 — 기계 발견 `sce_identity`·`sce_arith`·`bs_identity`, 또는 전체 대조에서 계산한 ①~④)

   | # | 상황 | 판정 |
   |---|---|---|
   | I1 | DB 값으로 계산하면 닫힘 | 이슈 아님. 기계가 발견으로 올렸으면 `기계오탐` 노트. 전체 대조에서는 pass 노트에 "열 N개 롤포워드 확인" |
   | I2 | 안 닫히고, 그 항등식의 셀 중 D ≠ S 인 셀이 있음 | 그 셀을 셀 규칙(C3)으로 등록한다. 이 항등식으로 `source_defect` 를 따로 등록하지 않는다 |
   | I3 | 안 닫히고, 그 항등식의 셀이 **전부 D = S** | `source_defect` 1건. 원인(괄호 누락인지 숫자 오기인지)이나 복원 가능성은 판단하지 않는다 — 수정 쪽이 코드로 판정한다 |

   - I3 은 사용자 결정 (가)(2026-10-09)다: 원문 산수가 깨졌으면 DB 가 원문과 같아도 반드시 등록한다. 노트만 남기고 pass 하면 규칙 위반이다.
   - I3 등록 위치: ①은 (필링, basis, 블록, 열)당 1건을 기말 셀에, ②는 기초 셀에, ③은 기말 현금 행에, ④는 (필링, basis)당 1건을 자산총계 행에.
     같은 원인으로 보여도 열이 다르면 따로 등록한다. evidence 에 `기초 ○ + 변동 합계 ○ = ○, 기말 ○, 차이 ○` 형태로 숫자를 적는다.
   - 이미 기계가 같은 열·블록에 `sign_flip`(자동 등록)을 걸어 둔 항등식은 I3 으로 다시 등록하지 않는다.
   - `unclassified` 는 **셀이나 행을 원문에서 찾을 수 없어** 위 표를 적용할 수 없을 때만 쓴다(예: 표 구조가 깨져 어느 DB 행이 어느 원문 행인지 정할 수 없음). evidence 에 무엇을 찾지 못했는지 적는다.

   **등록 단위**: 셀 규칙 이슈는 틀린 **셀마다** 1건, `source_defect` 는 깨진 **항등식마다** 1건이다.

   **등록 방법**: 먼저 로그 디렉터리(아래 "임시 파일" 경로)에 JSON 배열 파일을 `Write` 로 한 번 만들고 `vq.py issue add --rcept <R> --json-file <파일>` 로 한 번에 등록한다.
   `Write` 가 거부되면(실측: 10-07~09 사이 13회 모두 거부) 재시도하지 말고 개별 플래그로 하나씩 등록한다:
   `vq.py issue add --rcept <R> --basis ... --statement ... --account-label ... --column-label ... --db-value ... --source-value ... --source-value-raw ... --source-unit ... --error-type ... --evidence ...`.
   등록 없이 포기하지 않는다. (`machine issues-json` 은 `vq.py` 가 직접 파일을 쓰므로 영향받지 않는다.)

   **필드 형식** (recheck 가 문자열 정확 일치로 셀을 찾으므로 그대로 따른다):

   | 필드 | 값 |
   |---|---|
   | basis | `consolidated` / `separate` |
   | statement | `BS` / `IS` / `CIS` / `CF` / `SCE` |
   | account_label | CSV `항목명` 을 앞 공백만 빼고 그대로. DB 에 없는 행(`missing_row`)은 원문 계정명 그대로 |
   | column_label | SCE 는 CSV 비고의 `열=` 뒤 문자열 그대로. 그 밖의 표는 비운다 |
   | db_value | D 를 **원**으로 환산(`금액` × 표시 단위). DB 에 없으면 비운다 |
   | source_value | S 를 **원**으로 환산(괄호면 음수). **원문에 인쇄된 값**이다 — 고쳐야 할 값을 적지 않는다 |
   | source_value_raw | 원문 셀 문자열 그대로(예: `(1,234)`) |
   | source_unit | `원` / `천원` / `백만원` / `억원` (원문 선언) |
   | error_type · evidence | 위 판정표의 결과와 한두 줄 근거(검산식 숫자 포함) |

5. 필링 판정:
   - 이슈 없이 끝나면 `vq.py pass --rcept <R> --verified-scopes <show가 알려준 목록> --note "<행수·구조·결과, C2·기계오탐·롤포워드 확인 내역>"`.
   - 원문에 재무제표가 없는 필링(재무제표를 바꾸지 않은 정정본 등)은 `vq.py skip --rcept <R> --note "<사유>"`.
   - **적재 0행 필링**(`show` 의 `(적재 행 없음)`·기계대조 `no_source`): 원문을 열어 재무제표가 있으면 `missing_row` 1건
     (필링 전체 미적재, 대표 행 = 첫 재무제표의 첫 금액 행)을 등록하고, 없으면 위처럼 skip 한다. 원문 확인 없이 `done` 하지 않는다.
     (CSV `# 파싱 소스 pdf` 인 2015+ 필링은 PDF 보류 대상이라 등록된 이슈가 자동으로 주차된다. 그래도 등록 규칙은 같다.)
   - 이슈를 등록한 필링은 pass 하지 않는다.

6. **이번 실행에서 연 Chrome 탭을 전부 닫는다**(`mcp__claude-in-chrome__tabs_close_mcp`). 탭이 회차마다 쌓이면 메모리를 잡아먹는다.
   대조 도중에 오류로 끝내게 되더라도 탭은 먼저 닫는다.
7. 마지막에 반드시 `vq.py done` 을 실행하고 종료한다. 다음 슬롯을 스스로 점유하지 않는다.

## 금지

- 파서·로더·스크립트 코드 수정, 재적재, `layer2_review.py` 사용.
- 텔레그램 발송, `vq.py ask`.
- `vq.py` 가 거부한 명령을 다른 방법으로 우회하기. 거부 메시지는 규칙이다.
  예를 들어 "점유 이후 재적재됐다"가 나오면 `show` 를 다시 보고 대조를 다시 한다.
- **한 턴에 Bash(`vq.py ...`)는 하나만 부른다**(병렬 호출 금지). 여러 건을 등록·종료·재오픈해야 하면 JSON 파일 일괄등록을 쓴다.
  (2026-09-26: 한 턴에 ~14개 병렬 Bash 호출로 이후 세션 내내 Bash 전체가 거부된 사고가 있었다.)
- **허용되지 않은 명령(`grep`/`find`/`mkdir` 등을 Bash 로, 또는 로그 디렉터리 밖에 `Write`)이 거부되는 것은 정상이다.**
  포기하지 말고 허용된 도구(Grep/Glob/Read)로 바꿔서 계속한다. `vq.py` 명령 자체가 막힌 게 아니면 절대 포기하지 않는다.
  (2026-09-26: `grep`/`find` 한 번 막힌 것만으로 40~50턴 작업을 통째로 포기한 사고 2건, 런 408/409.)
- `vq.py` 로 시작하는 **허용된 명령 자체**가 `Permission to use Bash has been denied` 로 거부되면(항상 되던 `vq.py show` 등이 막히면)
  **그때만** 재시도하지 말고 즉시 멈춘다. `vq.py done` 도 다시 시도하지 말고 지금까지 처리한 내용만 아래 형식으로 요약하고 종료한다.

## 끝낼 때 출력할 것

한 줄 요약: `슬롯 <슬롯> — pass N · 이슈 M · skip K · 재확인 close X/reopen Y`
