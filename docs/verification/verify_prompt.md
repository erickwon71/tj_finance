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
3. `pending` 인 필링마다 DART 웹뷰(Chrome)에서 재무제표를 열어 DB 값(CSV)과 대조한다.
   - Chrome 도구는 지연 로딩이다. 먼저 ToolSearch 로 한 번에 불러온다: `select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__get_page_text`.
   - 시작할 때 `tabs_context_mcp`(createIfEmpty: true)로 탭 그룹을 만들고, `tabs_create_mcp` 로 새 탭을 **하나만** 연다. 필링이 여러 개면 같은 탭에서 `navigate` 로 옮겨 다닌다.
   - `tabs_context_mcp` 에 이전 회차가 남긴 DART 탭이 보이면 먼저 닫는다.
   - 표는 JS(`javascript_tool`)로 `#listTree` 목차를 클릭한 뒤 `table tr` 을 순회해서 추출한다.
   - Chrome 도구를 쓸 수 없으면 대조하지 말고 `vq.py done` 으로 끝낸다. 로컬 XML 등 다른 수단으로 대체하지 않는다.
   - 허용된 명령은 `vq.py` 와 Read/Grep/Glob 뿐이다. 그 밖의 명령은 거부된다.
   - 대조 범위: 연결/별도 × BS·IS(포괄손익 포함)·CF·SCE 가운데 **적재된 scope 전부, 모든 행과 모든 열**.
     총계·EPS·마감행만 보는 축약은 금지다.
   - "이전 판정 이후 바뀐 scope" 가 표시된 필링은 그 scope만 다시 대조하면 된다. 바뀌지 않은 scope는 이미 검증된 내용과 byte-identical 이다.
   - 정정본에서 "= <rcept> 와 byte-identical" 로 표시된 scope는 원문 재접속 없이 같다고 봐도 된다. 표시되지 않은 scope만 원문과 대조한다.
4. 불일치 셀 1개 = 이슈 1건이다. JSON 파일(임시 디렉터리)에 모아 한 번에 등록한다:
   `vq.py issue add --rcept <R> --json-file <파일>`
   각 항목 필드: basis(consolidated|separate), statement(BS|IS|CIS|CF|SCE), account_label(원문 계정명),
   column_label(SCE 열·다열 표일 때), db_value, source_value, source_value_raw(원문 셀 문자열 그대로),
   source_unit(원|천원|백만원|억원), error_type, evidence(한두 줄).
   error_type: missing_row · extra_row · value_mismatch · sign_flip · unit_scale · column_misassign ·
   period_misassign · label_mismatch · source_defect · unclassified.
   이미 `docs/PARSING_RULES.md` 에 있는 원문 오타 패턴이면(Grep 으로 확인) source_defect 로 등록한다. 새 패턴이면 unclassified 로 등록한다.
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
