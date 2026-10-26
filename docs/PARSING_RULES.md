# 파싱·적재 규칙 단일 관리 문서

> **이 문서의 목적.** 파싱·적재 규칙이 코드 docstring·핸드오프·메모리에 흩어져 있어,
> 새 파서를 만들 때마다 규칙을 다시 발굴하거나 **모르고 어긋나게 구현**하는 일이 반복된다.
> 이 문서가 규칙의 **단일 진입점**이다. 규칙 본문은 2026-10-12 부터 `docs/rules/` 의 계층별 파일에 있다(아래 0-0·0-1).
> 규칙을 새로 정하거나 바꾸면 **판정 순서로 고른 계층 파일에 먼저 적고**(머리에 `적용 계층:`), 0-1 색인에 한 줄 더하고,
> 근거가 되는 코드/문서를 링크한다.
>
> **읽는 법.** 각 규칙은 `규칙 / 근거(파일:줄 or 문서) / 어기면 생기는 일` 3단으로 적는다.
> 근거 없는 규칙은 규칙이 아니다 — "그렇게 해왔다"는 여기에 쓰지 않는다.
> **원칙끼리 겹쳐 보이면 바로 아래 "지금 유효한 원칙" 표가 이긴다**(R0-2 가 R0-1 의 일부를 대체한 뒤 두 절을 읽는 순서에 따라 해석이 갈렸다).
>
> 최종 갱신 2026-10-12 (계층별 분리 · 지금 유효한 원칙 표 · R116/R154 계층3 이행).

## 지금 유효한 원칙 (2026-10-12 — 아래 R0·R0-2·R0-1 본문을 요약한 것, 새 결정 아님)

| 질문 | 2015+ 의 답 | 근거 | 2015 이전 |
|---|---|---|---|
| 보고서를 어떻게 읽나 | 모든 보고서를 같은 방식으로, 있으면 파싱·없으면 넘어감. 정정본은 같은 항목이 나중에 나오면 이긴다 | R0 | 같음 |
| 계층2(`report_lines`)에 무엇을 싣나 | **인쇄된 숫자를 그 표의 선언 단위로 읽은 값 그대로** | R0-2 | R0-2 이행 전 — 옛 보정값이 남아 있음 |
| 계층2 에서 허용되는 "읽는 법" | 괄호·△·마이너스=음수, 마침표 천단위 구분자(R158·R158-b), 쪼개진 숫자 잇기(R202), 이어붙은 EPS 나누기(R218), 증명된 실제 단위(R169·R207·R238, 숫자는 그대로), XBRL 표현 규칙(R10, XBRL 폴백 필링만) | R0-2 표 왼쪽, R0-1 머리 | — |
| 인쇄값과 **다른 값**(부호 복원·숫자 교정·빈칸 채움·행 이동/삭제·다른 원천 덮어쓰기) | **계층3 에서만** — `layer3_cell_corrections`(value·fill·drop), 각 규칙의 증명 조건으로. 코드가 `fin2/extract` 에 있어도 `as_printed` STEPS 뒤 | R0-2 "계층3 보정의 범위" | 계층2 에 옛 보정값 |
| R0-1 의 "후보는 부호 복원 하나뿐"·"증거 범위"·"판정에서는 이 절이 이긴다"·"정합화 대기" 표 | **대체됨(→R0-2)** — 2015+ 계층2 판정에 쓰지 않는다. 계층3 보정에도 1항 후보 제한·3항 증거 제한은 적용하지 않는다 | R0-1 머리 인용, R0-2 72행 | — |
| 항등식이 "닫혔다"의 기준 | 표시 단위 × ⌈항 수 ÷ 2⌉ 이하(계층3 증명·기계대조 공통) | R0-1 2항(유효) | 같음 |
| 계층3 은 무엇을 읽나 | `report_lines_l3` 뷰(인쇄값 + value·fill·drop 보정). 계층2 에 표가 있는지 물을 때도 이 뷰 | R0-2 "계층3 읽기" | — |
| 본문 XML 이 없는 필링의 계층2 원천 | 웹뷰 인쇄본(`<rcept>.viewer.xml`). XBRL 은 계층3 증거, 웹뷰도 없을 때만 XBRL 폴백 | R0-2 "본문 XML 없는 필링" | — |
| 검증(기계·모델)이 이슈로 만드는 것 | **DB 셀 = 원문 인쇄값인가**만. 산수는 기록용(계층3 보정 후보), 위치 신호 `sce_identity`·`bs_identity` 만 판정 | R0-2 "검증 캠페인 범위" | — |
| 확정 못 하면 | 추측하지 않는다 — 값을 못 읽으면 NULL + `value_raw`, 기간·열을 못 정하면 싣지 않음 | R6, R0-1 4항 | 같음 |
| 규칙이 어느 파일에 있나 | 0-1 색인. 계층은 "규칙이 무엇을 결정하는가"(판정 순서) | 0-0 | — |

---

## R0. ★★ 지배 원칙 — 문서를 그대로 읽는다. 없으면 넘어간다.

**규칙** — 모든 보고서(원본이든 정정본이든)를 **같은 방식으로** 읽는다.
보고서의 각 부분을 차례로 훑으면서, **있으면 파싱하고 없으면 넘어간다.**
부분이 빠진 것은 오류가 아니다 — 정상이다.

- 원본에도 없는 부분은 얼마든지 있다(연결재무제표를 안 만드는 기업 → 별도를 파싱한다).
  이걸 미스매칭으로 보지 않는다. **정정본에 부분이 없는 것도 똑같이 취급한다.**
- 정정본이 원본과 다른 점은 **하나뿐**이다: 같은 항목이 나중에 다시 나오면 **그게 이긴다.**
  판단은 표의 행 개수가 아니라 **항목의 내용**으로 한다
  (원본 손익계산서 50행 → 정정본 30행이면, 30행이 최종이 아니라 **원본 50행 중 그 30개
  항목의 값만 바뀐다**).
- 따라서 '정정본 병합'을 위한 별도 설계·별도 키 체계는 **필요 없다.** 모든 보고서를 같은
  파서로 읽고, 시간순으로 항목을 덮어쓰면 된다.

**우리가 집중할 것은 두 가지뿐이다.**

| 감시 대상 | 뜻 |
|---|---|
| **거짓 부재(false absence)** | 있는데 **없다고 잘못 판단**하는 것 |
| **오파싱(misparse)** | 있는 내용을 **틀리게 읽는** 것 |

**"보고서에 일부가 빠져서 파싱을 못 한다"는 결론은 나와선 안 된다.**

**근거** — 사용자 지침 2026-08-01. `fin2/layer3/combine.py:96`(항목 단위 덮어쓰기·미수록 항목
유지)과 `:184`(대상별 체인 워크)가 재무제표에 대해 이미 이 원칙의 구현이다.

**이 원칙으로 본 오늘의 결함들** — 전부 **거짓 부재**의 사례다:
`is_final` 필터(R2-1, 547건) · 연도 헤더행이 표를 폐기(T7, 생산표 7.9%) ·
1x1 래퍼가 캡션을 잡아먹음(T2) · `</TABLE>` 누락 시 표 0개(T1) · `△` 음수 셀 폐기(T8).

---

## R0-2. ★★★ 계층2 는 인쇄된 값만 싣는다. 값을 고치는 일은 모두 계층3 에서 한다 (2026-10-10, 사용자 결정 — 반복해서 깨진 원칙이라 맨 위에 둔다)

**규칙** — 계층2(`report_lines`)의 금액은 **DART 보고서에 인쇄된 숫자를 그 표의 선언 단위로 읽은 값 그대로**다.
부호 복원·숫자 교정·빈 칸 채움·행 이동/삭제·XBRL 태그로 덮어쓰기 등 **값을 바꾸는 코드는 계층2(추출·적재) 경로에 두지 않는다.**
원문 오류로 보이는 값을 고쳐 쓰는 일은 계층3(`fin2/layer3/`)이 R0-1 의 증명(닫힘·무악화·셀 수 최소 유일)을 코드로 계산해 **증명될 때만** 한다(선례: R221 비용 부호 정규화).

| 계층2 에서 해도 되는 것 (인쇄된 것을 **읽는 방법**) | 계층2 에서 하면 안 되는 것 (인쇄된 것을 **바꾸는** 일) → 계층3 |
|---|---|
| 괄호·△·마이너스 = 음수, 마침표 천단위 구분자 읽기(R158), 공백으로 쪼개진 숫자 잇기(R202), 두 번 이어붙은 EPS 나누기(R218) | 괄호 빠진 셀의 부호 복원(R162 계열·R163·R185~R193·R215), 수동 부호 목록(R162-manual) |
| 표 선언 단위로 원 환산, 단위=열 판정(R4), 선언이 스스로 모순인 표의 실제 단위(R169·R207·R238, 숫자는 그대로) | 숫자 오타 교정(R159 `_SOURCE_TYPO_CELL_FIXES`·R159 보강), 반올림 교정 |
| XBRL 원문의 표현 규칙(preferredLabel 부호 R10 등 — XBRL 이 원문인 필링의 "인쇄" 방식) | 빈 칸 채우기·행 이동·행 삭제(R183·R184) |
| 읽을 수 없으면 NULL + `value_raw` 보존(R6), 기간·열을 정할 수 없으면 싣지 않음 | 다른 원천(inline XBRL 태그·BS·IS·다른 보고서)으로 값이나 부호를 덮어쓰기(R18 배당 부호, 법인세 overlay) |

**확인 방법(이 규칙을 지키는지 매번 볼 수 있게)**
1. 새 파서·규칙을 만들 때: "이 코드가 인쇄된 숫자와 다른 값을 계층2 에 쓰는가?" — 그렇다면 계층2 가 아니라 계층3 에 둔다. 이 문서에 R번호를 적을 때 **적용 계층(2/3)을 반드시 쓴다.**
2. 기계대조(`fin2/verification/machine_compare.py`): 이행 완료 후에는 DB = 원문 인쇄값이 아닌 셀은 모두 발견이다(`sign_restored` 같은 예외 없음). `vq.py status` 의 부호복원 셀 수가 0 이어야 한다.
3. 회귀 테스트: 괄호가 빠진 원문 픽스처를 추출하면 계층2 값이 **인쇄된 부호 그대로**여야 한다(이행 때 추가).

**이행 상태**: 이행 설계 `docs/plans/layer2_as_printed_migration_2026-10-10.md`. **2015+ 이행 완료(2026-10-10)** — 결과 `docs/qa/layer2_as_printed_impact_2026-10-10.md`, 본문 XML 없는 1,720필링은 웹뷰 인쇄본으로 재적재(아래).
2015+ 에서 R0-1 의 "원문과 다르게 싣는 것" 은 계층3 에만 적용된다. 2015 이전은 이행 전이다.
계층3 의 계정 매핑(라벨 → canonical)은 별칭 사전 > XBRL 개념(R172) > 택소노미 한국어 라벨(R229) > 퍼지 순이다 — 값을 바꾸지 않는 분류라 계층2 값과 무관하다.

**계층3 보정의 범위와 구현 (2026-10-10 사용자 결정 D5~D8 — 적용 계층: 3)**
- 계층3 은 **적용 가능한 논리적 방법을 모두** 써서 정상화한다: 부호 복원뿐 아니라 숫자 오타 교정(R159), SCE 원문결함 교정(R183 값·채움·이동·삭제), inline XBRL 태그를 증거로 쓰는 보정(R18 배당 부호·법인세 overlay), XBRL 경로 부호 정산(R170-d·R176), SCE 부호 체인 전체(R162 계열·R163·R185~R193·R188·R189·R190-d·R215), Q1 누적 공란의 3개월 값 채움(R116·R154, 2026-10-11 사용자 결정 — STEP `R154_q1_cum_fill`).
  즉 R0-1 1항의 "후보는 부호 복원 하나뿐"·3항의 증거 범위 제한은 **계층2 판정에만** 해당하고, 계층3 보정에는 적용하지 않는다(위 규칙들의 개별 증명 조건은 그대로).
- 구현: 위 규칙들은 `fin2/extract/as_printed.py` 스위치(`STEPS`) 뒤에 있고 **기본값 = 끔**(계층2 = 인쇄값). 적재 경로는 `fin2/extract/layer3_corrections.py` 로 규칙 끔(인쇄값)·켬(보정값) 두 번 추출해, 차이만 `layer3_cell_corrections`(계층3 테이블, `report_lines.id` 참조·재적재 시 cascade 삭제)에 셀 단위로 쓴다(규칙 이름 포함). 원문 파일이 필요한 규칙(inline XBRL)이 있어 적재 시점에 계산한다 — 결과는 계층2 테이블에 쓰지 않는다.
- 계층3 읽기: `report_lines_l3` 뷰 = `report_lines` + 보정 세 종류 — kind='value'(값 대체)·'drop'(행 숨김)·'fill'(`row_data` 로 행 추가, id = −보정 id). 처음(2026-10-10 오전)엔 value 만 반영했고, 같은 날 마이그레이션 `2026_10_10_report_lines_l3_fill_drop`(`collector/db.py`)으로 fill·drop 도 반영한다(R159 로 고친 BS 셀·R154 Q1 누적 채움이 fill 로 온다). `fin2/layer3/combine.py`(정본 필링 선택 `select_canonical_rcepts` 포함)·R187 근거(`sce_dated_anchors.py`)가 이 뷰를 읽는다. ★계층3 코드가 계층2 존재 여부를 물을 때도 이 뷰를 본다 — fill 로만 존재하는 표가 있다(2026-10-12 `e8bf11d`).
- 배선: `ops._reload_rcept`, `collector/note_lines_sync.py`(데일리 XML — `collect_new.py` 두 call site 모두 이 함수를 거친다), `collector/xbrl_instance_lines_sync.py`(데일리 XBRL).
- 옛 동작 비교: `TJF_LAYER2_AS_PRINTED=0` 이면 규칙이 계층2 에 다시 쓴다(한 릴리스 유지 후 삭제, D4).
- **본문 XML 없는 필링의 원천 = 웹뷰 인쇄본(2026-10-10 사용자 결정)**: DART 원본 묶음에 본문 XML 이 없으면(XBRL 만·PDF 만) XBRL/PDF 는 인쇄본이 아니므로(XBRL 은 차감·유출 부호와 계정명이 다름) 웹뷰(`report/viewer.do`) 문서를 DART XML 골격으로 감싼 `<rcept>.viewer.xml` 을 계층2 원천으로 쓴다(`fin2/extract/viewer_xml.py`, `collector/viewer_source.py`). document.xml 은 180일 재시도, 오면 자동 재적재. 설계 `docs/plans/viewer_xml_source_policy_2026-10-10.md`. XBRL 은 계층3 증거로만 남는다.
  변환 규칙: 웹뷰 HTML 의 `<BR>` 은 **지운다**(꼬리 텍스트는 유지) — 웹뷰가 DART 의 셀 안 줄바꿈 `&cr;` 를 `<BR>` 로 그린 것이고, DART XML 리더는 `&cr;` 를 지운다(R224 절). 처음엔 그대로 옮겨 DART 태그 화이트리스트 밖이라 글자 `<BR/>` 로 읽혔다: 176필링 5,430행 계정명 오염(`Ⅴ. 이익잉여금<BR/>`), 빈 문단 `<P><BR/></P>` 이 제목 탐색을 막아 티로보틱스 20180906000287 0행. 1,721개 파일을 `scripts/r0_2_migration/strip_viewer_br.py` 로 다시 쓰고 재적재했다(2026-10-10). 웹뷰 파일의 태그 중 DART 화이트리스트 밖은 `BR` 뿐이었다(전수).
- **검증 캠페인 범위 = 계층2 충실도만 (2026-10-10 사용자 결정)**: 검증(기계·모델)은 "DB 셀 = 원문 인쇄값" 만 본다. 산수(롤포워드·합계·BS 항등식)와 괄호 누락 추정은 계층2 이슈가 아니다 — 이슈를 만들지 않고, 기계대조 결과(`machine_checks.findings` 의 `sce_arith`·`sce_identity`·`sign_omitted`·`bs_identity`, 계층3 이 이미 닫는 것은 `l3_covered`)에 기록만 남겨 **계층3 보정 후보 목록**으로 모은다(`scripts/r0_2_migration/layer3_backlog.py`). 계층3 보정은 이 목록을 모아 한 번에 한다. 기계대조 mc10, `verify_prompt.md` 항등식 규칙(I1~I3)·결정 (가) 폐지. **보강(mc11, 같은 날 사용자 결정)**: 값 위치를 의심하게 하는 신호 `sce_identity`(옆 열 값으로 산수가 맞음)·`bs_identity` 는 계층3 이 닫지 않으면 판정에 남겨 모델이 웹뷰(제3의 독립 판독)로 위치를 확인한다 — 기계와 파서가 같은 표 구조를 똑같이 잘못 읽는 사각지대 때문. 웹뷰 위치가 DB 와 다르면 `column_misassign`/`value_mismatch`, 같으면 아무것도 하지 않는다. 순수 산수(`sce_arith`·`sign_omitted`)만 기록용.
- 소급 범위: **2015+ 먼저**(사용자 결정 2026-10-10). 2015 이전은 같은 규칙으로 나중에 한다 — 그때까지 2015 이전 계층2 에는 옛 보정값이 남아 있고 `layer3_cell_corrections` 행이 없다(계층3 값은 같다).

---

## R0-1. ★★ 원문 그대로 적재한다. 원문과 다르게 싣는 것은 "증명된" 경우뿐이다 (2026-10-09, 사용자 결정)

> **★ 이 절의 지금 범위 (2026-10-10, R0-2 이행 후)** — 계층2 에서 원문과 다르게 싣는 것은 1항의 **표기 해석**(R158·R158-b·R202·R218, R169·R207·R238)뿐이다. 부호 복원 증명·"정합화 대기" 표·"판정에서는 이 절이 이긴다"는 문장은 **2015+ 계층2 판정에 더는 쓰지 않는다**(R0-2 가 대체). 이 절의 증명 조건은 계층3 보정 규칙 각각의 조건으로만 남고, 2015 이전 필링은 R0-2 이행 전이라 옛 값이 남아 있다.

**목표** — 계층2(`report_lines`)는 DART 보고서에 **인쇄된 값을 그대로** 담는다.
원문에 부호·표기 오류가 있어 보이면 **보고서 내용으로 증명될 때만** 고쳐 싣고, 증명이 안 되면 **인쇄된 그대로** 싣는다.
이 절은 원문과 다른 값을 싣는 모든 규칙(R18·R159·R162 계열·R163·R165·R183~R193·R215 등)과, 이 문서 곳곳의 "캠페인 판정 기준"·"사람 확인 후 등재" 같은 옛 절차 문구의 **상위 규칙**이다.
- 개별 R번호가 이 절보다 느슨하거나 다르면, **판정(검증·수정)에서는 이 절이 이긴다.** 그 규칙의 코드는 사용자 승인 뒤 정합화 배치에서만 고친다(아래 "정합화 대기" 표).
- 판정은 규칙 이름이 아니라 **그 셀에 이 절을 계산한 결과**로 한다(정합화 대기 규칙이 바꾼 셀이라도 이 절의 증명을 만족하면 맞는 값이다).
- 섹션 제목에 "사용자 결정"이 붙은 규칙도 일반 규칙이다. 아래 0항의 고정 목록이 아니다.

**0. 사용자 결정 우선** — 아래는 이 절의 계산보다 앞선다. 바꾸려면 사용자에게 다시 묻는다(`vq.py ask --category irreversible`, 만료 자동 적용 없음).
| 목록 | 처리 |
|---|---|
| R206 `_AS_PRINTED_CELLS` (원문 부호 그대로 고정한 셀) | 목록대로 싣는다 |
| 동결 ①: `sign_flip` 이슈 중 `rule_id=R162-e` 이고 2026-09-26 이전에 등록된 것(잔존 8,006건, 2026-09-26 결정) | **해소(2026-10-10 D3)**: R0-2 이행으로 계층2 = 인쇄값이 정답이 되어 7,995건 close(`scripts/r0_2_migration/close_d3_issues.py`). drift 필링 11건만 남음(재적재 결정 후 처리) |

(옛 동결 ②(R165 유형: SCE 잔액 셀 숫자 오기를 BS 로 교정하는 후보 595건)는 2026-10-09 사용자 결정 "부호만 고친다"로 정해졌다 — 숫자 교정은 후보가 아니므로 원문대로 싣고, 수정 쪽은 `no_fix`.)

**1. 증명의 정의**

- **항등식**(이것만 쓴다): 열 롤포워드(기초+변동=기말), SCE 이월(기말 다음 날이 기초인 두 블록의 같은 열), CF 현금(기초+순증감+환율효과=기말),
  BS(자산=부채+자본), 합계(구성요소 합=합계 행·열), **같은 날짜 잔액**(SCE 잔액 = 같은 날짜 BS 의 같은 자본 항목 — 같은 필링 또는 아래 3의 다른 정기보고서).
- **후보**(바꿀 수 있는 것)는 **부호 복원 하나뿐**이다(2026-10-09 사용자 결정: "원문에 없는 값을 채워 넣지 않는다. 부호 정도만 고친다").
  - **부호 복원**: 원문에 **양수로 인쇄된** 셀(괄호·△·마이너스 없음)을 음수로 바꾸기. 원문에 음수로 인쇄된 셀은 후보가 아니다(괄호가 "빠진" 것만 복원한다).
  - 그 밖은 후보가 아니다: 숫자를 다른 숫자로 바꾸기(숫자 오타 교정 — 맞는 숫자가 다른 곳에 인쇄돼 있어도), 잔차만큼 맞춘 값, **빈 칸 채우기**(R183-보강·R184·R184-b),
    **행 이동·행 삭제**(R183), 음수 인쇄 셀의 반전(R190-d 일부).
  - 값 교정이 아닌 것(인쇄된 숫자를 **읽는 방법**): 마침표로 찍힌 천단위 구분자(R158·R158-b, 정수 짝이 있을 때만), 공백으로 쪼개진 숫자 잇기(R202), 한 셀에 두 번 이어붙은 주당이익 나누기(R218),
    그리고 단위 선언 교정(R169·R207·R238, 숫자는 그대로 두고 같은 회사 다른 정기보고서로 증명된 실제 단위로 읽음 — 선언이 실제보다 클 때 R169·R207, 작을 때 R238). 이것들은 후보 규칙이 아니라 표기 해석이며, 해석이 하나로 정해지지 않으면 R6(NULL)이다.

| # | 조건 | 뜻 |
|---|---|---|
| ① 닫힘 | 후보를 적용하면 **깨져 있던 항등식이 하나 이상** 허용오차 안에서 닫힌다 | "잔차가 줄어든다"는 닫힘이 아니다 |
| ③ 무악화 | 후보를 적용해도 그 셀이 항으로 들어 있는 다른 항등식이 나빠지지 않는다: **닫혀 있던 것은 계속 닫혀 있고, 안 닫혀 있던 것은 차이가 커지지 않는다** | 하나라도 나빠지면 그 후보는 탈락 |
| ② 유일 | ①③ 을 통과한 후보 가운데 **바꾸는 셀 수가 가장 적은 것**이 **정확히 1개**다 | 2개 이상이면 방향 증거(같은 항목의 BS·IS 부호, 이전 보고서 IS 포함)와 **반대 방향인 후보만** 지운다. 남은 것이 0개이거나 2개 이상이면 증명이 아니다 |

- 판정 순서: 후보를 모두 나열 → ① → ③ → 남은 후보 중 셀 수 최소만 → ②. ①②③ 이 성립하면 방향 증거가 따로 없어도 증명이다.
  (예: 기초 100 + 10 + 10 = 기말 100 은 1셀짜리 후보가 둘이라 증명이 아니다. 열 전체 반전은 그것만이 ①③ 을 통과할 때만 증명이다.)
- 방향 증거(같은 항목의 BS·IS **인쇄 부호**, 이전 보고서 IS 포함)는 ②에서 후보를 지우는 데만 쓴다. 그것만으로 부호를 정하지 않는다.
  라벨("성질상 음수"·배당·자기주식 취득 등)·"경제적 자명성"은 어디에도 근거로 쓰지 않는다.

**2. 허용오차 (하나로 통일, 2026-10-09 사용자 결정)** — 항등식은 차이가 **표시 단위 × ⌈항 수 ÷ 2⌉ 이하**이면 닫힌 것이다.
인쇄된 숫자는 각각 표시 단위로 반올림돼 있어, n 개를 더하면 반올림만으로 최대 n/2 단위가 어긋나기 때문이다.
**항 수** = 그 계산에 실제로 넣은 0 아닌 숫자의 개수(기초·기말 포함, 0·빈 칸 제외, 계산마다 따로), 허용오차는 최소 1 단위.
**소계 행**: 열 롤포워드에서 계정명에 `소계`·`합계`·`총포괄` 이 들어가거나 `계` 로 끝나는 행과 `수정후`·`재작성`·`조정후` 기초 행은 소계로 본다. 소계를 뺀 계산과 넣은 계산 중 하나라도 닫히면 닫힌 것이고, 항 수는 그 계산의 것이다(`verify_prompt.md` ① 과 같다). 예: 기초 + 변동 3개 + 기말 = 5개 → 3 단위, BS(자산=부채+자본) 3개 → 2 단위, 같은 날짜 잔액 2개 → 1 단위.
**표시 단위** = 원 표 1원, 천원 표 1,000원, 백만원 표 1,000,000원, 주당이익은 원문에 인쇄된 마지막 자리(소수 인쇄면 그 소수 자리).
항들의 표시 단위가 다르면 **그중 가장 큰 단위**를 쓴다. R169/R207/R238 로 단위가 교정된 섹션(`unit_source='proved_unit'`)은 교정된 실제 단위를 쓴다.
파서 복원·기계대조(mc7 부터, `machine_compare.identity_tolerance`)·모델 검증이 모두 이 값을 쓴다.

**3. 증거 범위** — 증명에 쓸 수 있는 숫자는 **같은 회사의 DART 정기보고서(사업·반기·분기보고서, 정정본 포함)에 인쇄된 숫자**뿐이다. 주요사항보고서·증권신고서 등은 쓰지 않는다.
- 해당 보고서 안: 같은 표, 같은 필링의 BS·IS·CF·SCE(연결·별도 모두), 주석, 본문 서술(주석·본문 숫자는 1항 항등식의 항으로만 쓴다).
- 같은 회사의 다른 정기보고서: 같은 날짜 BS 잔액(항등식으로 사용), 같은 기간 IS(방향 증거로만 사용), 다른 필링의 같은 금액(R169 단위 판정).
  숫자는 그 rcept 의 `report_lines` 로 찾고, 쓰기 전에 그 셀을 원문에서 확인한다.
- 그 밖(다른 회사, 외부 데이터)은 증거가 아니다.
- 검증 모델은 같은 필링만 본다. 다른 정기보고서가 있어야 성립하는 증명은 수정 쪽이 확인하고 `no_fix` 노트에 그 rcept 와 셀 값을 적는다.
- 검증의 근사(알려진 차이): 기계대조는 원문이 양수로 인쇄된 SCE 셀의 부호 반전을 그 열 ①② 가 닫히면 복원으로 보고, 검증 모델의 C2 는 ①③ 만 본다(② 유일은 보지 않는다). 유일하지 않은 기존 반전은 정합화 대기 규칙의 몫이다.

**4. 증명이 안 될 때**
| 경우 | 적재 |
|---|---|
| 부호가 의심되지만 증명 안 됨 | **인쇄된 부호 그대로** 적재 (NULL 아님) |
| 숫자 자체가 틀려 보이지만(합계 불일치·오타) 증명 안 됨 | **인쇄된 숫자 그대로** 적재 |
| 빈 칸 | 빈 칸 그대로(채우지 않는다) |
| 숫자를 읽을 수 없음(마침표 셀 등 값이 둘 이상으로 읽힘, R160·R205) | 행은 싣고 값은 NULL + 원문 문자열 보존(`value_raw`) — R6 |
| 기간·열을 정할 수 없음(R156·R168·R201·R226·R228-A) | 그 셀·행·표를 싣지 않음 — R6 |

- 숫자 오타(부호가 아닌 값 오류)는 **고치지 않는다.** 맞는 숫자가 같은 보고서 다른 표에 인쇄돼 있어도 인쇄된 숫자 그대로 싣는다(검증은 `source_defect` 로 기록한다).
- 부호 복원의 등재 형식: **일반 규칙**(코드가 후보를 찾아 ①②③ 을 계산)이 기본이다. 일반 규칙으로 찾을 수 없는 경우만 rcept 목록으로 등재한다.
  어느 쪽이든 적재할 때마다 ①~③ 을 다시 계산하는 가드가 있어야 한다. 마침표·구분자 표기 문제는 R158·R160·R205 를 따른다.
- 과도한 복구 금지: 이 기준을 넘는 새 복원 규칙은 만들지 않는다. 원문과 같게 적재된 셀이 증명되지 않으면 수정 쪽은 `no_fix` 로 닫는다.

**5. 누가 판단하나** — "증명되는가"는 **코드(파서·기계대조)** 가 판단한다. 검증 모델은 산수 사실(DB=원문인가, 항등식이 닫히는가)만 기록하고,
증명 가능 여부는 수정 쪽이 코드로 확인한다(`docs/verification/verify_prompt.md` 4번, 수정 워크트리 `CLAUDE.local.md`).
어느 규칙이 셀을 바꿨는지는 그 규칙을 끄고 다시 추출한 결과와 비교해 확인한다(켬/끔 측정).

**정합화 대기** (이 절과 다르게 동작하는 현행 코드 — 고칠 때까지 검증은 이 셀들을 원문과 다르게 실린 셀로 보고 판정표대로 처리하고, 수정 쪽은 그 셀이 이 절의 증명을 만족하면 `no_fix`, 만족하지 않으면 `defer` 한다.
코드 수정·재적재는 사용자가 승인한 정합화 전용 배치에서만 한다. 이 표에 없는 규칙이라도 이 절과 다르게 동작하면 같은 취급이다):

| 규칙 | 현행 | R0-1 과 다른 점 |
|---|---|---|
| R188 | 1,000원 절대 허용오차 (`sce_sign_repair.py:1526,1649,1659`) | 허용오차 = 2항(표시 단위 × ⌈항 수 ÷ 2⌉) |
| R162 계열·R163·R168 | 원 단위 정확 일치 | 허용오차 = 2항 (반올림 표에서 복원 누락) |
| R189 | 열 잔차가 **줄기만** 하면 반전 (`sce_sign_repair.py:1784`) | ① 닫힘 필요 |
| R185·R185-b | 행 항등식 잔차가 줄기만 하면 열 전체 반전 | ① 닫힘, ② 셀 수 최소 |
| R190-d | 블록이 안 닫혀도 BS 잔액 부호 채택, 두 검사가 **모두** 나빠질 때만 건너뜀, 음수 인쇄 셀도 반전(18셀) (`:1571,1593,1600`) | ③ 하나라도 나빠지면 안 됨, 음수 인쇄 셀은 후보 아님 |
| R189·R197-b | "성질상 음수" 라벨(배당·자기주식 취득)을 부호 근거로 사용 | 라벨은 근거 아님 |
| R162-e·R162-f | ③ 무악화 확인 없음 | ③ 필요 |
| R183 `_VALUE_FIXES`·`_ROW_MOVES`·`_ROW_DROPS`·`_CELL_FILLS`, R184·R184-b | 값 교정·행 이동·행 삭제·빈 칸 채움 | 후보 아님 → 원문대로 |
| R18 | 인라인 XBRL 태그(인쇄 숫자 아님)와 상대오차 1% 로 대사 | 증거 = 인쇄 숫자, 허용오차 = 2항 |
| R162-manual `_MANUAL_SIGN_FIXES` | 적재 시 재증명 없음 | 적재 시 ①~③ 재증명 |
| R159 일괄 194셀 (`table_extractor.py:1650`, 커밋 74e6afc) | 이 문서에 기록 없음 | 근거 기록 필요 |
| R160 마침표 셀(463셀·129필링, `docs/qa/dot_typo_candidates_2026-09-23.md`) | **해소(2026-10-12 사용자 결정)** — 행은 싣고 값 NULL + `value_raw`, 기계대조 mc14·verify_prompt 같이 변경(`docs/rules/10_layer2_parse.md` R160 머리) | 4항: 행은 싣고 값 NULL + `value_raw` |
| XBRL 적재(`xbrl_zip`, 원문 XML 없는 필링 약 1,550건) 계정명 | 택소노미 표준 라벨로 적재(예: `법인세비용, 계속영업`) | 계정명도 인쇄된 그대로(사용자 결정 A, 2026-10-10). 검증은 표당 1건 `label_mismatch`(evidence `XBRL 라벨:`), 수정은 모아서 한 배치로 처리(그때까지 `defer`) |
| R192 | 이전 보고서 IS 부호만으로 반전, "형제 증명"·"경제적 자명성" 근거 | ① 닫힘 필요, 라벨·자명성은 근거 아님 |
| R215 | 블록이 좋아지면 행 항등식이 나빠져도 채택 | ③ 하나라도 나빠지면 안 됨 |
| R159 `_SOURCE_TYPO_CELL_FIXES`·R159-보강①~④ 중 숫자 자체를 바꾼 셀(자릿수·숫자 오타, 반올림 교정) | 다른 곳 인쇄 또는 항등식으로 숫자 교정 | 숫자 교정은 후보 아님 → 원문대로(마침표·구분자 표기 해석만 유지) |
| 기계대조 `sce_arith` 소급분 | mc6 까지 정보용으로만 남기고 기계 pass — clean 필링 17,174건(2026-10-09 집계) | mc7 부터 새로 대조하는 필링은 기계가 `source_defect` 자동 등록(아래). 기존 17,174건 소급은 사용자 결정 대기 |

(정합화가 아닌 오파싱: SCE `주석` 열(154필링·1,894셀)에 주석 번호가 금액으로 적재돼 있다 — 주석 열은 금액이 아니므로 적재하지 않게 파서를 고친다. 수정 쪽 F4-c.)

**검증 도구 반영 (mc7, 2026-10-09)**:
- 기계대조 허용오차 = 2항(`machine_compare.identity_tolerance`). `sce_identity` 는 열마다 ⌈(0 아닌 기초·기말·변동행 수) ÷ 2⌉(최소 1), `bs_identity` 는 2 단위.
- mc8 (2026-10-09, 모델 간 판정 일치): 항등식 발견에도 `db_col` 기록. 원문이 **양수로 인쇄된** 셀만 부호 복원(sign_restored)으로 인정하고 음수 인쇄 셀의 반전은 발견으로 남긴다.
  검증 모델은 mismatch 필링에서 발견 번호만 고르고(`vq.py machine issues-json --findings`) 이슈 필드·error_type 은 도구가 정한다(`machine_pass.cell_error_type`·`identity_issue`).
- SCE 발견에 `block_end`(블록 기말 행)·`db_col`(DB 열 이름) 기록, `sce_arith` 에 `src_broken`(원문 숫자로도 깨짐) 기록.
- 원문 산수만 깨진 clean 필링(`sce_arith` + `src_broken`)은 기계가 `source_defect` 를 자동 등록한다(`machine_pass.arith_issues`, 열 표기 `<열> @ <날짜> #항등식`). 기계 재확인(`machine recheck`)이 이 이슈도 처리한다.
- `sign_omitted` 자동 등록은 **그 종류만 있는 필링에서만** 한다(의도된 동작). 다른 발견이 있는 필링에 이슈를 걸면 그 필링·슬롯이 `has_issues` 가 되어 나머지 발견을 모델이 받지 못하기 때문이다. 그런 필링의 `sign_omitted` 는 모델이 항등식 규칙(I3)으로 처리한다.
- `issues-json` 은 SCE 셀 이슈의 column_label 을 `<DB 열 이름> @ <블록 기말일>` 로, 그 밖의 표는 비운다. `vq.py show` 는 기계대조 없음·stale 필링을 "대조하지 않고 pending" 으로 안내한다.
- 남은 과제: 같은 셀에 셀 이슈와 `source_defect` 를 함께 걸 수 있게 고유 인덱스 재검토(지금은 ` #항등식` 꼬리로 구분), 옛 형식 이슈와의 중복 판정(`_prior_no_fix` 정규화).

---

## 0-0. 이 문서와 docs/rules/ (2026-10-12 분리)

이 문서는 **단일 진입점**이다 — 지배 원칙(R0·R0-2·R0-1·R2·R6·R9)과 전체 색인을 둔다. 나머지 규칙 본문은 아래 파일로 **내용 그대로** 옮겼다(R 번호 불변). 계층은 코드 위치가 아니라 **규칙이 무엇을 결정하는가**로 정한다(판정 순서: `docs/plans/parsing_rules_split_2026-10-11.md`).

| 파일 | 담는 것 |
|---|---|
| [10_layer2_parse.md](rules/10_layer2_parse.md) | 계층2 — 원문을 읽어 `report_lines` 에 싣는 규칙 |
| [20_layer3_map.md](rules/20_layer3_map.md) | 계층3 — 계층2 를 표준 계정으로 바꾸고 값을 보정하는 규칙 |
| [30_audit_verify.md](rules/30_audit_verify.md) | 검증 — 데이터를 쓰지 않고 판정만 하는 규칙 |
| [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 — 수집 대상·파이프라인 배선·재적재 규약 |
| [90_case_log.md](rules/90_case_log.md) | 사례 기록 — 판정 문장이 없는 경위·측정·배치 기록 |
| [99_appendix.md](rules/99_appendix.md) | 부록 — 원출처·미결 현황·rcept 예외목록 카탈로그 |

- 규칙을 찾을 때: 아래 **0-1 전체 색인**에서 R 번호로 파일을 찾는다. grep 은 `docs/PARSING_RULES.md docs/rules/` 를 함께 본다.
- 규칙 문서 수정은 **main 과 camp_err_review 에서만**(사용자 결정 2026-10-11). 다른 worktree 는 받기만 한다.
- 상태 `대체됨(→R..)` 인 규칙은 판정에 쓰지 않는다 — 화살표의 규칙을 본다.

## 0-1. 전체 색인 (자동 생성 — `scripts/split_parsing_rules.py`)

| R | 제목 | 파일 | 적용 계층 | 상태 | 비고 |
|---|---|---|---|---|---|
| R0 | R0. ★★ 지배 원칙 — 문서를 그대로 읽는다. 없으면 넘어간다. | 이 문서 | 원칙 | 유효 |  |
| R0-2 | R0-2. ★★★ 계층2 는 인쇄된 값만 싣는다. 값을 고치는 일은 모두 계층3 에서 한다 (2026-10-10, 사용자 결… | 이 문서 | 원칙 | 유효 |  |
| R0-1 | R0-1. ★★ 원문 그대로 적재한다. 원문과 다르게 싣는 것은 "증명된" 경우뿐이다 (2026-10-09, 사용자 결정) | 이 문서 | 원칙 | 일부 대체됨(→R0-2: 2015+ 부호복원 증명·정합화 대기 표·'이 절이 이긴다'. 표기 해석 1항은 … |  |
| R1 | R1. 보고서 원문 read 는 계층2 전용 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R2 | R2. ★정본 정책 — 최초등록본 + 순차 델타 패치 | 이 문서 | 원칙 | 유효(내부 '표 단위 델타' 설계 문단만 폐기) |  |
| R3 | R3. 계층2 는 모든 버전을 전사한다 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R4 | R4. 단위는 표가 아니라 열 단위로 판정 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R4-2 | R4-2. 제목+데이터 병합 표 / 제목 자체가 없는 표 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R5 | R5. 헤더 의심 행을 삭제하지 않는다 (header_hint) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R6 | R6. 확정 못 하면 추측하지 않는다 | 이 문서 | 원칙 | 유효 |  |
| R7 | R7. 유니버스 | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R8 | R8. 새 파서/로더 추가 3층 (자동 반영 안 됨) | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R9 | R9. 검증은 집계가 아니라 원문 대조로 | 이 문서 | 원칙 | 유효 |  |
| R10 | R10. XBRL 원문(instance) — 값 부호는 preferredLabel이 결정, calc:weight는 저장에 안… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R11 | R11. ★표의 논리적 열 = 헤더·본문을 관통하는 하나의 occupied-grid (본문 행도 ROWSPAN/COLSPAN… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R12 | R12. 발행주식수("주식의 총수 등") — 계층2 cross-cutting 스칼라 전사 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R13 | R13. pre-2015(K-GAAP 구서식) 계층2 전사 — 연도 라우팅 신규 모듈, 2015+ 경로 무변경 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R14 | R14. XBRL 원문(instance) 구형 IFRS taxonomy(2010~2013 계열) 확장 — namespace/… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R15 | R15. 계층3 _CURRENT_STRICT(bs.trade_payables 등) — 비유동 후보를 stage-rank 숏컷… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R16 | R16. 계층3 _resolve() stage-rank 숏컷 — is.revenue/bs.trade_payables 총계 vs | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R17 | R17. bs.trade_payables additive override — curated 키는 corp 단독이 아니라 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R18 | R18. 계층2 CF cf.dividends_paid 부호 — document.xml 인라인 XBRL(Track A) 사실로… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R19 | R19. table_extractor.py::_split_label_amounts() 주석번호 가드 — 콤마 없는 단일 숫자는 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R20 | R20. 계층3 _resolve() stage-rank 숏컷 — 지주회사형 is.sga(영업비용 총계 vs | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R21 | R21. is.cogs additive override — 매출원가류 서브라인 합산(stage-rank/충돌 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R22 | R22. Gate B face_audit.py — is.cogs vs report_won 개념 자체가 다른 4개사는 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R23 | R23. fin2/taxonomy/concept_map.py — bs.trade_payables concept_map 갭 5… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R24 | R24. 계층3 combine.py::_map_rows() — is.controlling_ni/is.noncontrollin… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R25 | R25. Gate B face_audit.py::_ni_attribution_structural_candidates() — … | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R26 | R26. Gate B face_audit.py — FX 표시통화(두산밥캣) curated pending 강등, 옵션 B | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R27 | R27. fin2/extract/report_lines.py — EPS(주당손익) 행 판정의 라벨 부분문자열 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R28 | R28. fin2/extract/report_lines.py — K-GAAP 구서식(00269852류) 헤드라인 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R29 | R29. fin2/layer3/combine.py — K-GAAP 구서식 헤드라인 NI net_income 결측 복구 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R30 | R30. fin2/extract/text.py/statement_titles.py — 표제/계정구분 중복 마커가 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R31 | R31. parser/xml/table_extractor.py::_NUMBER_PATTERN — 괄호 없는 순수 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R32 | R32. Gate B — 업종 프로파일 파생 revenue 검증 (증권/은행/보험/여신전문, 2026-08-17) | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R33 | R33. Gate B — 증거강도(축2) 계측 + fail_a 승격의 gapfill 예외 1건 (2026-08-18) | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R34 | R34. fin2/layer3/combine.py::_resolve() — R2 델타패치가 정정본의 표 재렌더링에 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R35 | R35. fin2/audit/face_audit.py — NI 귀속표 전체가 XBRL 미태깅인 문서에서 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R36 | R36. fin2/audit/face_audit.py — _ni_attribution_text_candidates()(R35… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R37 | R37. scripts/gateb_audit.py::select_corps() — Gate B 감사 유니버스가 상장폐지사를 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R38 | R38. fin2/audit/face_audit.py::read_report_face_xbrl_zip() + scripts/… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R39 | R39. fin2/layer3/combine.py::_resolve() — BS 총계 3종의 라벨-표현 드리프트가 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R40 | R40. Track D(xbrl_zip 재파싱) — 다중필링 narrow-prefer 재현 불가(알려진 감사 커버리지 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R41 | R41. fin2/audit/curated_key_scan.py 신설 — Gate B curated 키 재생성기(전수 패턴 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R42 | R42. bs.trade_payables 정정본 하위라인 재구성이 남긴 stale 셀 오채택 — R16 계열의 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R43 | R43. account_mapper.py 포괄손익 귀속 가드 — '포괄이익'/'포괄손실'(쪼개진 표기) 미포착 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R44 | R44. '계속영업' 귀속 성분 자매가드 — DRB동일(00118266) 부수발견 후속조사 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R45 | R45. fin2/layer3/combine.py::_resolve_ni_attribution() — net_income 앵커 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R46 | R46. fin2/audit/face_audit.py::_with_ni_attribution_text_fallback() — | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R54 | R54. fin2/audit/face_audit.py::read_report_face_xbrl() — 회사고유 확장(UDF) | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R55 | R55. account_maps/bs_accounts.py — bs.trade_payables 결합형 alias의 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R56 | R56. fin2/audit/face_audit.py — 갤럭시아에스엠 라벨-acode 뒤바뀜 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R57 | R57. fin2/layer3/combine.py::_resolve() — _CURRENT_STRICT 탈락분을 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R58 | R58. fin2/layer3/combine.py::_apply_enrichment() — 원인 C(v3가 차입금 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R58 순서4-② "al… | R58 순서4-② "alias 3종" (2026-08-31) — account_maps/bs_accounts.py + | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R58 순서4-③ "나머… | R58 순서4-③ "나머지 소수 라벨"(신주인수권부사채/교환사채) + 순서4-②의 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R59 | R59. fin2/layer3/combine.py::_resolve() — bs.long_term_debt 결합(rollup) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R60 | R60. account_maps/bs_accounts.py — bs.current_portion_lt_debt 개념분리 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R61 | R61. Gate B Phase B(fin2/audit/line_audit.py) DB측 원천 fact_v2→report_l… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R62 | R62. account_maps/is_accounts.py + parser/common/amount_normalizer.py… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R63 | R63. fin2/layer3/combine.py + fin2/layer3/build.py — K-GAAP시대 연결 인터림 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R64 | R64. parser/common/amount_normalizer.py::normalize_account_name() — 주… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R65 | R65. parser/xml/table_extractor.py — 헤더 <TH>주석</TH> 기반 주석열 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R66 | R66. fin2/layer3/combine.py::combine_full() — 증권/보험/은행/여신전문 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R67 | R67. fin2/extract/text.py/fin2/extract/report_lines.py — 계층2 문서레벨 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R68 | R68. account_maps/bs_accounts.py+cf_accounts.py+fin2/layer3/combine.p… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R69 | R69. parser/xml/section_detector.py+fin2/extract/text.py+fin2/extract/ | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R70 | R70. fin2/extract/legacy_pre2015.py+fin2/extract/statement_titles.py — | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R71 | R71. fin2/extract/legacy_pre2015.py — (A-3) 통짜-셀 레거시 BS 표 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R72 | R72. fin2/layer3/combine.py::_reduce_conflict() — is.revenue grand-to… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R73 | R73. fin2/layer3/unit_overrides.py — 원문 자기모순 필링 수동 단위교정 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R74 | R74. _AMOUNT_SANE_MAX 값-거부 셀이 선두절삭 컬럼압축과 충돌해 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R75 | R75. fin2/extract/pdf.py — Track C(PDF-only) "3줄 이중언어" 레이아웃 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R76 | R76. OpenDART document.xml 아카이브 자체의 2001년 접수분 인코딩 손상 | [90_case_log.md](rules/90_case_log.md) | 사례 | 유효 |  |
| R77 | R77. fin2/extract/pdf.py::_PERIOD_MARK_RE — 정정회차·당기/전기 표기가 낀 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R78 | R78. fin2/extract/pdf.py — 라벨이 숫자를 사이에 두고 줄바꿈되는 세 번째 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R79 | R79. account_mapper — "차/대"·"임차/임대" 처럼 한 글자 차이로 뜻이 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R80 | R80. account_mapper 전체 어휘 스캔 — R79 패턴의 체계적 재현(형태소 반의어 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R81 | R81. R80 "처분(inflow) 전용 canonical 미신설" 후속 — 사용자 지시 "처분 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R82 | R82. Category C(fy1999~2003 절단 복구) 배치 경로 — HTML→PDF T1/T2/T3 | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R83 | R83. Track C 93건 전체 소급 백필 실행 중 reconcile() T2 분기 오채택 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R84 | R84. parser/common/account_mapper.py — Stage 3 fuzzy containment 가 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R85 | R85. fin2/extract/report_lines.py::_emit_eps_lines() — H1/Q3 EPS 행이 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 일부 대체 후보(→R88 열 판정 3갈래 추측) — D단계 확인 |  |
| R86 | R86. fin2/extract/report_lines.py::_emit_section_lines() — else 분기(선두… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 일부 대체 후보(→R88 열 판정 3갈래 추측) — D단계 확인 |  |
| R87 | R87. parser/xml/table_extractor.py::extract_rows() — "6-column IS 형식 … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 일부 대체 후보(→R88 열 판정 3갈래 추측) — D단계 확인 |  |
| R88 | R88. parser/xml/table_extractor.py::parse_header_columns()/ | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R89 | R89. 헤더 먼저 읽기(R88) 확장 — parser/xml/table_extractor.py §7(THEAD 없는 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R90 | R90. fin2/extract/shares.py "단위 : 천주" 미인식 ×1000 축소 + | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R92 | R92. parser/xml/dart_xml_parser.py::_parse_xml_file() — DART archive … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R93 | R93. fin2/extract/pdf.py — 헤더 구조 우선 파싱 재설계: 주석번호 열 오인식 + | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R94 | R94. fin2/extract/pdf.py — 손익계산서가 통째로 0행이었던 3중 원인: 서브컬럼 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R91 | R91. collector/filing_collector.py — 제목 태그 없는 정정본 회계연도 오판정 + | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R95 | R95. parser/xml/table_extractor.py::_headerless_header_trs() — THEAD … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R96 | R96. collector/downloader.py::_pick_best_file_by_size() — DART docume… | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R98 | R98. 연결재무제표 없는 회사가 "연결 basis 존재"로 오판되는 두 갈래 원인 — | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R100 | R100. fin2/extract/statement_titles.py::classify_legacy_statement_hea… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R101 | R101. fin2/extract/statement_titles.py — 구형 레이아웃 표제가 다른 문장 뒤에 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R102 | R102. fin2/extract/text.py::_detect_legacy_body_statement_tables() — … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R103 | R103. collector/downloader.py — 정기보고서가 접수 당시 PDF만 있고 표준파일 | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R104 | R104. collector/filing_collector.py — 같은 날 접수된 "최초본+첨부정정/첨부추가" | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R105 | R105. standard_financials.consolidation_status VARCHAR(20) 길이초과로 std_… | [90_case_log.md](rules/90_case_log.md) | 사례 | 유효 |  |
| R106 | R106. fin2/extract/consolidation_evidence.py — IFRS1109/1115 소급재작성 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R107 | R107. 같은 파일 — "OO재무제표를 재작성하지 않았습니다" 문장구조 잔여 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R108 | R108. 같은 파일 — SPAC 합병보고서에서 SPAC 껍데기 법인의 "해당사항 없음" | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R109 | R109. 같은 파일 — 비교연도(전기)만 지칭하는 결측선언이 당기 확정 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R110 | R110. 같은 파일 — 순번↔회계연도 매핑이 불가능한 케이스(SGA솔루션즈)를 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R111 | R111. parser/xml/table_extractor.py/fin2/extract/text.py — 글자당 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R112 | R112. 같은 파일 — 글자당 공백 주석헤더("주  석") 인식 실패로 헤더그리드 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R113 | R113. 같은 파일 select_by_header_columns() — 순수 대시("-") 셀을 구조적 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R114 | R114. 같은 함수 — R113 직후 회귀: 무표지 병합군(COLSPAN 다중열)에서 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R115 | R115. parser/xml/table_extractor.py::drop_mismatched_granularity_colu… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R116 | R116. fin2/extract/report_lines.py::_Q1_CUM_BLANK_USE_3M_RCEPTS — Q1 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R117 | R117. parser/xml/table_extractor.py::_columns_from_grid() — 완전공란 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R118 | R118. fin2/extract/report_lines.py::_R118_DUPLICATE_PERIOD_LABEL_FIX — | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R119 | R119. parser/xml/table_extractor.py::_columns_from_grid() — 같은 셀 안 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R120 | R120. parser/xml/table_extractor.py::select_by_header_columns() | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R121 | R121. fin2/extract/report_lines.py::_MANUAL_NO_CONSOLIDATED_FS_RCEPTS… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R122 | R122. parser/xml/table_extractor.py::_PERIOD_KEY_RE — 괄호 뒤 "기" | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R123 | R123. 같은 파일 — 증권사류 헤더 4가지 미인식 변형 (2015+ 전수 폴백 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R124 | R124. (시도했다가 되돌림) 명세/소계 COLSPAN=2 중복 서브타입 열의 전사 | [90_case_log.md](rules/90_case_log.md) | 사례 | 대체됨(→R125, SB성보 회귀로 폐기) |  |
| R125 | R125. parser/xml/table_extractor.py/fin2/extract/report_lines.py — | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R126 | R126. parser/xml/table_extractor.py::_PERIOD_KEY_RE — 달력날짜 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R127 | R127. fin2/extract/text.py::_looks_like_equity_changes_header()(신규) — | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R127b | R127b. 같은 함수 — SCE 오염 가드를 "제목표/데이터표 분리 서식" forward-scan | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R128 | R128. 같은 파일 _PERIOD_KEY_RE — "당N분기"/"전N분기" 표기가 서수 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R128b | R128b. 같은 파일 — 2자리 연도 축약형+N분기("19년 3분기") 미인식 (2026-09-15, | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R129 | R129. parser/xbrl_instance/taxonomy_linkbase.py::_drop_prohibited_onl… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R130 | R130. fin2/extract/report_lines_xbrl.py::_emit_missing_cf_lines()(신규)… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R131 | R131. parser/xml/table_extractor.py::select_by_header_columns() — | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R132 | R132. fin2/extract/report_lines.py::_MANUAL_UNIT_OVERRIDE_MULTIPLIER_ | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R133 | R133. fin2/extract/report_lines_xbrl.py::_emit_missing_leaf_lines() | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R134 | R134. parser/xml/table_extractor.py::_header_rule_name() — SCE 전용 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R135 | R135. fin2/extract/report_lines.py::_grid_body_rows() — 라벨 영역에 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R136 | R136. fin2/extract/pdf.py — 콤마 없는 단독 주석번호가 금액으로 오인식되는 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R137 | R137. fin2/extract/pdf.py::facts_from_text()/collector/pdf_lines_ | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R138 | R138. scripts/scan_header_fallback_2015plus_2026-09-14.py — R125 | [90_case_log.md](rules/90_case_log.md) | 사례 | 유효 |  |
| R139 | R139. store_report_lines() — 원문대조 완료(layer2_review_queue.status='pass… | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 대체됨(→R167, 2026-09-24 사용자 결정, 이력으로 보존) |  |
| R140 | R140. 계층2 검토 CSV에 SCE 포함 + layer2_review.py에 --min-severity 단계 | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R141 | R141. fin2/extract/statement_titles.py::classify_statement_in_body_se… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R142 | R142. fin2/extract/statement_titles.py::is_substatement_marker() 신설 + | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R143 | R143. fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_tax_e… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R144 | R144. EPS(주당손익) 경로와 본류의 판정 불일치 3종 + 셀 안 줄바꿈으로 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R145 | R145. EPS 행 판정을 "주당" 부분문자열에서 구조 패턴으로 교체 + | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R146 | R146. rule_additive_da() 가 같은 감가상각비를 CF·IS·주석에서 각각 더해 D&A 와 EBITDA 를 … | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 미해결로 적혀 있음(2026-09-19 제목 기준 — 현재 상태 확인 필요) |  |
| R147 | R147. _is_eps_label() 이 라벨에 주당 이 없는 EPS 자식행(계속영업/중단영업 세부이익)을 인식 못 해 통… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R148 | R148. fin2/extract/text.py::_detect_body_statement_tables() — 자본변동표가 … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R149 | R149. parse_amount() 가 '2,564원'(셀이 스스로 원 단위를 밝힌 표기)을 못 읽어 EPS 행이 통째로 … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R150 | R150. parse_amount() 가 천단위 콤마 바로 뒤에서 공백으로 쪼개진 금액 ('4,244, 863')을 결측으로… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R151 | R151. _looks_like_equity_changes_header() 가 열이름의 자간 공백을 처리하지 않아 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R148(표지 없는 SC… | R148(표지 없는 SCE 물리분할표)이 신한지주 외에서는 발동하지 못했다 (2026-09-20) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R152 | R152. 금융업 보충표기(대손준비금·비상위험준비금)가 본항목과 같은 칸에 압축돼 자본/손익 본항목 행이 통째로 유실 (20… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R153 | R153. R116/R120 열선택 예외 플래그가 EPS 경로에 전달되지 않아 EPS 행이 두 경로 사이 틈으로 증발 (20… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R154 | R154. Q1 표가 스스로 증명한 3개월 = 누적 등식을 읽어, 누적 칸이 공란인 행을 구제한다 — R116 예외목록의 일… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R155 | R155. [R168 로 대체 — 산수 자기증명 시 적재] 구형 2단 열(내역칸/잔액칸) 서식에서 양쪽이 다 찬 "그룹 마감… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 대체됨(→R168) |  |
| R156 | R156. [설계대로 — 캠페인 판정 기준] 분기·반기 필링에서 누적 칸이 공란인 행은 적재되지 않는다(3개월만 있어도) —… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R157 | R157. parse_amount() 가 소수부를 단위 배수 적용 전에 버려, 선언 단위가 있는 표에서 값이 조용히 깎였다 … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R158 | R158. 천단위 구분자가 마침표로 깨진 셀 — 행 안의 정수 짝과 대조해 복원 (2026-09-22, 캠페인 이슈#22) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R159 | R159. 원문 자체의 오타 셀을 rcept 예외목록으로 교정 (2026-09-22, R118 패턴) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R160 | R160. 해결되지 않은 마침표 셀은 적재하지 않는다 — 결측으로 남기고 확인 요청 목록으로 보고 (2026-09-22, 사… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R161 | R161. 각주 문장이 표제 앞에 붙어 재무제표 분류가 한 칸씩 밀렸다 (2026-09-22, 캠페인 이슈#26) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R162 | R162. SCE 표 원문에서 음수 괄호가 빠져 자본변동표 셀이 부호 반대로 적재된다 — 교차대조(방향) + 열 롤포워드 항… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R163 | R163. CF 현금 조정 구간에서 원문이 빠뜨린 음수 부호를 복원한다 — R162 의 자매(자본변동표 → 현금흐름표) (2… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R164 | R164. 처분계산서 가드가 SCE 를 구조적으로 판별 못 해 자본변동표를 통째로 버렸다 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R165 | R165. SCE 기말잔액 행의 한 셀만 원문에서 값이 틀려 있다(행 항등식+BS 이중앵커로 확정) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R166 | R166. 라벨 칸이 ROWSPAN 으로 이어지는 두 번째 물리행이 유실·오라벨된다 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R167 | R167. 검증 ↔ 재적재 규칙 — 적재 스탬프·lease·내용버전 (2026-09-24, R139 대체) | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R168 | R168. 구형 2단 열(내역칸/잔액칸) 서식의 그룹 마감행을 산수로 자기증명될 때만 적재한다 (2026-09-24, R15… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R169 | R169. 자기모순 단위선언(선언 백만원·천원, 실제 원)을 타 필링 동일값 대조로 섹션별 확정해 교정한다 (2026-09-… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R170 | R170. XBRL 경로: 회사 _pre.xml 은 DART 표준 base 표시링크베이스에 대한 델타다 — base 를 병합… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R171 | R171. 정정 체인에 추출 경로가 섞이면(XML → XBRL → XML) 나중 XML 필링이 앞선 XBRL 셀을 스코프 단… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R172 | R172. 계층3: XBRL 셀은 라벨이 매핑 안 되면 XBRL 개념(source_ref) 으로 매핑한다 — R171 양방향… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R173 | R173. EPS 경로도 본류와 같은 주석열 판정으로 금액 칸을 가른다 (2026-09-25) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R174 | R174. Gate B 판독기 — 증명된 단위 교정(R132/R169)을 따르고, 당기 첫 칸 '-' 는 0 후보로 둔다 (… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R175 | R175. XBRL 경로 CF 표시부호 = 계산링크베이스 weight 누적곱 — 단, 표 자신의 부모=Σ자식 등식이 더 많이… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R176 | R176. XBRL SCE 소유주거래 행 부호 = 롤포워드 등식(기초 + Σ변동 = 기말)이 증명할 때만 반전 (2026-0… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R177 | R177. XBRL SCE row_order 기간 순서(canonical_dates)는 행마다 따로 잡지 않고 표 전체에서 … | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R178 | R178. _header_rule_name의 "단위표기" 규칙이 라벨 부분일치라 자기 라벨에 단위를 부기한 | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R179 | R179. parse_amount() 의 R149 '원' 접미사 규칙이 음수(손실) EPS 셀 '(89원)'(원이 닫는 괄호… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R180 | R180. XBRL SCE 행이 자본합계(total) 열에 fact 를 어디에도 안 가져도 다른 열의 진짜 값을 버리면 안 … | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R181 | R181. XBRL SCE '기초자본' 라벨 날짜 — DART 는 기초 fact 를 블록 기말 instant context … | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R182 | R182. XBRL tree-gap(R133) 계속영업이익 fact 는 표 자신의 법인세차감전 − 법인세 등식과 모순이면 올… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R183 | R183. SCE 원문 자체 오류(값 오기·기간블록 오배치·중복행) — rcept 예외목록 + 적재시점 항등식 재증명 가드 … | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R184 | R184. 합계 열에만 인쇄된 SCE 변동행 — 빈 구성요소 셀을 항등식으로 채우는 일반 규칙 (2026-09-27, 사용자… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R184-b | R184-b. R184 를 계층형 표(그룹 소계 + 자본 합계)로 확장 — 두 합계 칸에만 인쇄된 변동행 (2026-10-0… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R185 | R185. R162-d 부분 뒤집기 열의 열 일관성 가드 — 증명될 때만 열 전체로 확장 (2026-09-27, 사용자 결정… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R187 | R187. SCE 잔액 행의 날짜 앵커 — 같은 필링 BS 전기말 열 + 직전 사업보고서 BS (2026-09-27, 사용자… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R188 | R188. SCE 잔액 셀 1,000원 허용오차 이중 항등식 (2026-09-27, 사용자 결정: 소액 차이 1,000원 이… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R189 | R189. 체인 뒤에도 깨진 행 항등식 — 형제 셀을 열 롤포워드와 외부 증거로 맞춤 (2026-09-27, 사용자 지시, … | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R189-b | R189-b. R189 변동 행의 외부 증거에 이전 보고서 IS(블록과 같은 기간) 추가 (2026-09-27, 사용자 지시… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R190 | R190. SCE 거울해 가드 — 분기·반기 BS 날짜 앵커(G-A) + 잔액 행 자체 증명(G-B(i)) + 앵커 해법 자… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R190-c | R190-c. SCE 중첩 소계 판정·부호 (2026-09-27, fix batch #40) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R190-d | R190-d. SCE 잔액 셀의 BS 날짜 부호 우선 — 블록이 닫히지 않아도 적용 (2026-09-27, 사용자 결정 "측… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R191 | R191. SCE 선행 소계(구성요소 위에 먼저 찍힌 소계)의 인쇄 부호 유지 (2026-09-28, fix batch #4… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R192 | R192. SCE 변동 셀의 이전 보고서 IS 부호를 R162 앵커로 사용 (2026-09-28, 사용자 결정 "측정 후 보… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R193 | R193. SCE 선행 소계(구성요소 위에 먼저 찍힌 소계·제목행)를 아래 행의 합으로 증명 (2026-09-29, fix … | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R194 | R194. SCE 표제 아래 붙은 IS/CF 표는 SCE 데이터가 아니다 — R127 의 거울 가드 (2026-09-29, … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R195 | R195. 표제 분류에서 SCE 이름도 '가장 나중 이름 채택' 에 참여한다 — R141 의 빠진 절반 (2026-09-29… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R196 | R196. 표제 오기 연금흐름표(현금→연금)도 현금흐름표 표제로 인식 (2026-09-29, fix batch #50) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R197 | R197. R162-e 교차 열 가드 + 원문 결함 앵커 예외목록 (2026-09-29, fix batch #55) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효(내부 R197-a 만 측정 후 폐기) | as_printed STEP |
| R185-b | R185-b. 열 일관성 확장의 행 항등식 조건 완화 (2026-09-27, fix batch #34) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R186 | R186. R162-e 자기일관성 — 뒤집은 뒤 소계를 다시 판정해도 블록이 닫혀야 채택 (2026-09-27, fix ba… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R159-보강 | R159-보강. 백만원 선언 표의 진짜 소수 정밀도 셀 — R158/R160 콤마-오타 판정으로 못 푸는 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R159-보강② | R159-보강②. 콤마 그룹핑 결손(자릿수 누락) — dot-typo 계열이 아니어도 같은 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R159-보강③ | R159-보강③. 마침표 오타 + 숫자 오타가 한 칸에 겹친 셀 — 항등식·정수판으로 | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R159-보강④ | R159-보강④. 합계 항등식이 확정하는 '.5' 꼴 마침표 셀 — 롯데에너지머티리얼즈 (2026-10-01, 검증 이슈 #… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R162-f | R162-f. 원문 소계행이 틀려 R162-c 산술증명이 실패하면, 라벨로 식별한 소계행을 빼고 R162-e(단일셀 반전)를… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R162-d | R162-d. SCE 행 내부 열 항등식(구성요소 합 = 그룹 합계)으로 빠진 음수 괄호를 복원 — 이중증거 셀만 적용 (사… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R199 | R199. XBRL 필링의 두 번째 IS role(손익계산서 + 포괄손익계산서 별개 표) 을 적재한다 (2026-09-30,… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R200 | R200. R176 XBRL SCE 부호 정산의 동률 처리를 결정적으로 — 순회 순서 고정 + 동률은 본성상 음수 행만 (2… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R201 | R201. XBRL H1/Q3 IS·CF — 누적 fact 가 없고 3개월 fact 만 있는 칸은 적재하지 않는다 (2026… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R201-b | R201-b. 기계대조(machine_compare)의 SCE 주석 열 오프셋 오탐 (2026-09-30, 검증 도구 수정) | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R201-c | R201-c. R201-b 의 주석 열 판정이 그룹 접두 라벨(지배기업 소유주 귀속분>주석)을 놓친다 (2026-10-01,… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R199-b | R199-b. R199 의 중복 판정에 개념(concept) 을 넣는다 — 순이익 귀속 vs 총포괄손익 귀속 비지배지분 (2… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R162-d2 | R162-d2. R162-d 행 항등식 — 그룹 합계 칸이 공란이고 구성요소가 하나만 인쇄된 행 (2026-09-30, fi… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R162-e2 | R162-e2. R162-d/d2 가 셀을 바꾼 필링은 부호 복원 체인(R162/R162-e)을 한 번 더 돈다 (2026-… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R202 | R202. 셀 안에서 숫자의 첫 1~2자리가 떨어져 공백으로 이어진 서식 — 1 73,918,853,979 = 173,918… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R203 | R203. XBRL EPS 를 회사 확장 개념(perShareItemType) + unitRef="SHARES" 로 태깅한 … | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R158-b | R158-b. 소수부가 전부 0(.0/.00)인 마침표 셀 — 같은 행에 정수부와 같은 온전한 셀이 있으면 정수부로 복원 (… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R204 | R204. XBRL IS — 필링이 base 배치를 옮겨 단 비용 개념도 base 템플릿의 negation 을 물려받아 제거… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R205 | R205. 마침표+쉼표 혼합 구분자 셀(69.792,290 = 69,792,290) — 소수로 읽지 않고 R160(결측)·R… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| 부록 B. 규칙이 사는 … | 부록 B. 규칙이 사는 곳 (원출처) | [99_appendix.md](rules/99_appendix.md) | 부록 | 유효 |  |
| 부록 C. 미결 / 위반… | 부록 C. 미결 / 위반 현황 | [99_appendix.md](rules/99_appendix.md) | 부록 | 유효 |  |
| 부록 D. rcept 단… | 부록 D. rcept 단위 예외목록 카탈로그 (2026-09-15 취합) | [99_appendix.md](rules/99_appendix.md) | 부록 | 유효 |  |
| R206 | R206. R192 제외 22필링의 불확실 셀 103개는 원문 부호 그대로 적재 — 셀 단위 예외 (2026-10-02, 사… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R207 | R207. R169 단위 자기모순 — 1e15 상한에 안 걸리는 ×1,000 부풀림은 자산총계/이웃 필링 비율로 지명한다 (… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R208 | R208. XBRL 누락 총계 보충(R14 A-5)은 문서가 이미 찍은 총계를 다시 넣지 않는다 — udf 총계 행 · 두 … | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R209 | R209. XBRL SCE 부모행 fact 가 자기 자식 합과 모순이면 그 기간 블록의 부모행을 올리지 않는다 (2026-1… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R210 | R210. XBRL SCE 에서 기말 행 하나만 있는 기간 블록은 올리지 않는다 — 재무상태표 비교일 자본 (2026-10-… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R211 | R211. 기계대조(machine_compare)의 주당 판정은 section_path 도 본다 — EPS 절 자식행((1)… | [30_audit_verify.md](rules/30_audit_verify.md) | 검증 | 유효 |  |
| R212 | R212. 소수 EPS 는 정확값을 따로 싣는다 — report_lines.value_exact · extended_fact… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R213 | R213. 계층3 EPS 는 적재기의 EPS 행을 자체 규칙으로 분류한다 — 일반 매퍼 라벨 공백 (2026-10-03, R… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R214 | R214. XBRL SCE 가 전부 instant 로 태깅돼 표 안에 duration 이 없으면, 기초 라벨 날짜는 같은 b… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R215 | R215. SCE '결손금' 열은 음수 BS 앵커를 쓴다 — 이익잉여금(결손금) 결합 라벨도 '결손금' 개념으로 잇는다 (2… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R216 | R216. XBRL 주당 개념이 KRW 단위 + decimals ≤ −6 이면 10^(−decimals) 로 나눠 원으로 되… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R217 | R217. 계층3 은 XBRL IS '주당' 행도 R213 EPS 규칙으로 분류한다 — 라벨에 '계속'·'중단'이 함께 있으… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R218 | R218. 라벨에 EPS 항목이 정확히 둘이고 금액 셀이 전부 같은 두 반쪽이면 반으로 쪼갠다 — 원문 XML 이 두 값을 … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R218-b | R218-b. 계층3 은 |값| ≥ 1,000,000 인 EPS 후보를 버린다 — 절 제목 행에 실린 순이익·포괄이익 (2026-10-04) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | 2026-10-12 R218 안 하위 절에서 분리 |
| R219 | R219. store_report_tables() 는 넘겨받은 lines 가 다루는 statement 범위만 지우고 다시 쓴… | [40_ops_pipeline.md](rules/40_ops_pipeline.md) | 운영 | 유효 |  |
| R220 | R220. 달력 CY(12월 결산 native)의 flow 는 같은 회계연도 FY as-filed 값을 쓴다 (2026-10… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R221 | R221. 계층3 std 비용 컬럼은 비용 = 양수 관례로 정규화한다 — 항등식 증명 + 성질상 비음수 비용 (2026-10… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R222 | R222. 정기보고서 비재무 섹션 표는 계층2 doc_section_tables 에 원문 격자로 담고, 1차 키는 DART … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R223 | R223. 계층3 문서 매퍼는 머리 경로(header path)로 열을 찾고, 숫자·단위·날짜는 공통 규칙으로 읽는다 (20… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R224 | R224. 선언 안 된 명명 엔티티(&cr; 등)는 파싱 전에 정리한다 — libxml2 가 그 뒤의 &amp;·&lt;·&… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R225 | R225. 밸류에이션 주식수는 유통주식수(보통주, Ⅵ = Ⅳ−Ⅴ) 다 — 계층2·3 에 Ⅴ 자기주식수·Ⅵ 유통주식수를 싣고 … | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R226 | R226. XBRL SCE 도 H1/Q3 에서 3개월 단독 사실은 누적 블록에 싣지 않는다 — R201 의 SCE 판 (20… | [10_layer2_parse.md](rules/10_layer2_parse.md) · XBRL 폴백 | 2 | 유효 |  |
| R227 | R227. R170-d 법인세 부호 정산은 필러 확장 개념의 계속영업 순이익 행도 후보로 쓴다 (2026-10-08, fix… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R228 | R228. 기간 하나가 여러 열에 뭉친 본문 표 헤더는 문서 증거로 기간을 나누고, 증거가 없고 두 기간 구조가 뚜렷하면 적… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R229 | R229. 인쇄 계정명이 택소노미 한국어 표준 라벨이면 그 개념으로 계층3 계정을 정한다 (2026-10-10, 사용자 결정… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R230 | R230. 주석 표 열이 [기간 > 기능] 2단이면 그 기간의 합계 열을 쓴다 — 계층3 D&A (2026-10-10, 사용… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R231 | R231. D&A = 현금흐름표 조정 금액. 출처는 하나만, 출처를 기록한다 (2026-10-11, 사용자 결정 A, 적용 … | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R232 | R232. CF "현금유출액" 구간에 유출 금액의 크기를 인쇄한 양식 → 계층3 이 부호를 붙인다 (2026-10-11, 사… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R159-보강⑤ | R159-보강⑤. 천원 표에 원 단위까지 소수 3자리로 인쇄한 셀 — CJ제일제당 2025 사업보고서 (2026-10-11,… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 | as_printed STEP |
| R233 | R233. CF 이자·배당 현금 계정은 현금 행이 있으면 손익 계정명 후보를 버린다 (2026-10-11, 사용자 지시 "행… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R234 | R234. BS 자산마다 붙은 차감 계정 행은 같은 표 안에서 합산해 총액으로 쓴다 (2026-10-11, 사용자 결정, 적… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R235 | R235. CF 배당금 지급은 성질상 유출 — 계층3 에서 −값 (2026-10-11, 사용자 결정, 적용 계층: 3) | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R236 | R236. CF 계정명 앞의 "(영업투자재무)활동으로 분류된" 한정어는 떼고 매핑한다 — 뗀 나머지는 정확·정규화 일치만 (… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R237 | R237. 정정본에서 같은 위치·같은 금액 셀의 계정명이 바뀌면 그 셀이 최초본 셀을 대체한다 — 계층3 병합만 (2026-… | [20_layer3_map.md](rules/20_layer3_map.md) | 3 | 유효 |  |
| R238 | R238. 표머리가 "(단위 : 원)" 인데 숫자가 천원·백만원으로 인쇄된 섹션은 증명된 실제 단위로 읽는다 — R169 의… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R239 | R239. 주당이익 절 아래 `계속영업`·`중단영업`·`보통주`·`우선주` 자식행은 EPS(원/주)다 — 표 단위를 곱하지 않는다 (2026-10-14,… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R240 | R240. 같은 SCE 표가 단위 다르게 두 번 담기면 표 자신의 선언과 같은 단위를 쓴다 (2026-10-14, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R241 | R241. 괄호가 한쪽뿐인 금액 셀은 읽을 수 없는 인쇄 셀이다 — 값 NULL + 인쇄 원문(value_raw) 으로 자리를 지킨다 (2026-10-14,… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R242 | R242. IS·CF 표제표 뒤 첫 데이터표가 재무상태표이고 IS/CF 내용이 아니면 그 표는 BS 데이터다 — 표제표의 데이터로 잇지 않는다 (2026-10-15,… | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R243 | R243. 분기·반기 보고서 헤더의 당기 열(`제N기 당반기` 등)은 기간 키에 접미사를 남긴다 — R115 가 당기 열을 연간 참고열로 버리지 않게 (2026-10-16, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R244 | R244. 라벨 셀이 라벨+주석 두 열을 COLSPAN 으로 합친 행은 주석 칸을 빈 칸으로 채워 금액 열 위치를 맞춘다 (2026-10-16, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R245 | R245. 합병 보고서에서 다른 법인의 재무제표 표는 제출 법인의 표가 아니다 — 같은 섹션의 첫 표 이후, 다른 법인명 표지 뒤의 표는 싣지 않는다 (2026-10-16, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R246 | R246. 한 칸에 `&cr;` 로 쌓인 금액 둘은 줄바꿈으로 남긴다 — `&cr;` 삭제로 두 숫자가 한 숫자로 붙지 않게 (2026-10-17, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R247 | R247. 반기·3분기 IS/CF 2단 헤더의 `6개월`·`9개월`·`12개월` 열은 누적 열이다 — `누적` 글자가 없어도 (2026-10-17, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R248 | R248. 현금흐름표 금액 칸 맨 앞의 인쇄된 대시(`-`)는 실제 칸이다 — 앞쪽 열 잘라내기에서 제외 (2026-10-17, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R249 | R249. SCE 의 `주석`·`주석번호`·`주기` 열은 금액 열이 아니다 (2026-10-17, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R250 | R250. 연도 머리글이 오래된 해부터 인쇄된 표는 가장 최근 연도를 당기(rank 0)로 읽는다 (2026-10-17, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R251 | R251. 기간만 있는 THEAD 아래 첫 TBODY 행이 `3개월 \| 누적` 하위 머리글이면 머리글로 읽는다 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R252 | R252. 첫 머리글 칸이 빈 표제 없는 BS 도 BS 시작으로 본다 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R253 | R253. 수기 병합표(표제+데이터 한 TABLE)가 선언한 단위를 섹션 첫 단위로 쓴다 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R254 | R254. 본문 표제 인식 보강 5종 — 기준 접두 병합표제·`포괄계산서`·`(1) 은행계정` 소제목·괄호 서수 기간줄·`자본변동` 단독 표제 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R255 | R255. SCE 의 `당기초`·`전기초`·`전기말` 행은 열 머리글이 아니라 잔액 데이터 행이다 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R256 | R256. SCE 라벨 영역은 머리글 첫 칸의 span 으로 확인한다 — 기말 행의 빈 칸이 값 열로 오인되는 경우 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R257 | R257. 외화(USD) 본표는 원화 2단 표의 중복 데이터원이 아니다 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R258 | R258. `&cr;` 로 쌓인 금액 사이의 빈 줄·붙임표 줄·괄호 음수 줄도 줄바꿈으로 남기고, 괄호 음수 첫 토큰을 R152 가 인정한다 (2026-10-18, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R259 | R259. 부모 줄과 자식 줄이 한 행에 쌓인 소계행은 첫 값이 나머지의 합일 때 첫 값(부모 합계)만 적재한다 (2026-10-18, 적용 계층: 2 — 읽기, 사용자 결정 A) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R260 | R260. 첫 자리가 한 자리씩 조각난 금액(`2 8 6,763,456,363`)은 하나로 잇는다 — R202 의 다단 변형 (2026-10-19, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R261 | R261. 한 칸 안에서 떨어져 찍힌 앞 한 자리(`8` + `4,153,171`)는 행 합계가 증명할 때만 잇는다 — R202/R260 의 두 토큰 변형 (2026-10-20, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R262 | R262. 기간 그룹 두 칸 중 한 칸이 인쇄된 `0` 이고 다른 칸이 금액이면 그 금액이 행의 값이다 (2026-10-20, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R263 | R263. 표제 없이 BS 바로 뒤에 붙은 IS 표를 행 라벨로 IS 로 본다 (2026-10-20, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R264 | R264. SCE 제목표 뒤 데이터표가 다음 재무제표 소제목 아래에 있으면 내용이 자본변동이고 BS/IS/CF 가 아닐 때 SCE 데이터로 본다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R265 | R265. 헤더 행 없이 이어지는 SCE 표(당기 블록)는 앞 SCE 표의 열 이름을 물려받아 싣는다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R266 | R266. 구형 [세부, 잔액] 2열 마감행은 위 잔액 기준값 + 세부 = 오른쪽 잔액이면 세부칸을 싣는다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R267 | R267. 한 행에 쌓여 인쇄된 병렬 행은 줄 수가 모두 같을 때 행 k개로 나눠 싣는다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R268 | R268. R168·R266 의 산수 증명은 100만 원 이상 금액에서 1원 차이를 반올림 오차로 본다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R269 | R269. 기간 헤더처럼 읽히는 라벨이라도 같은 행에 100만 이상 쉼표 금액이 있으면 데이터 행이다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R270 | R270. 본문 EPS 칸이 한 자리씩 조각난 숫자는 하나로 잇는다 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R272 | R272. `…와 그 종속기업의 … 연결재무제표` 문구도 타 법인 표 표지로 본다 — 효력은 그 연결/별도 구분 안에서만 (2026-10-21, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R273 | R273. 쉼표 묶음이 깨진 금액 칸(`10,921,090,50`)은 읽을 수 없는 칸으로 둔다 — NULL + value_raw (2026-10-22, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R274 | R274. 여러 줄 라벨 `주당이익 / 기본주당순이익 / 희석주당순이익` 행은 줄 수만큼의 행으로 나눈다 (2026-10-22, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R275 | R275. 자본변동표 열 이름 어휘에 `보통주납입자본`·`기타자본항목` 을 추가한다 (2026-10-22, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R276 | R276. 같은 기수가 겹쳐 인쇄된 열은 인쇄된 연도로 기간을 가른다 (2026-10-22, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R277 | R277. 절 번호가 붙은 구형 본문 표제도 재무제표 표제로 읽는다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R278 | R278. 천단위가 공백으로 인쇄된 금액은 한 숫자로 읽는다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R279 | R279. 같은 금액이 구분 없이 두 번 붙은 셀은 읽을 수 없는 인쇄값이다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R280 | R280. 본문 재무제표의 계정명이 빈 행도 인쇄된 금액이 있으면 싣는다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R281 | R281. 포괄손익계산서 표제 아래 인쇄된 재무상태표 본문은 BS 로 읽는다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R282 | R282. 서브헤더 누락 IS 표 4건을 R120 예외목록에, 중복 기간 라벨 1건을 R118 예외목록에 추가 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R283 | R283. THEAD 가 마지막 기간만 적고 앞 기간 칸이 빈 표는 표제의 기간 목록으로 앞 기간을 채운다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R284 | R284. SCE 에서 ROWSPAN 라벨의 둘째 물리행은 그 행의 라벨(앞 행이 인쇄한 라벨 칸)을 쓴다 (2026-10-23, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |
| R285 | R285. 모든 금액 셀이 '원' 접미사를 단 행은 표 단위가 아니라 원(adecimal=0)으로 적재한다 (2026-10-26, 적용 계층: 2 — 읽기) | [10_layer2_parse.md](rules/10_layer2_parse.md) | 2 | 유효 |  |

## 0. 규칙 색인

| # | 규칙 | 적용 계층 |
|---|---|---|
| **R0** | **★문서를 그대로 읽는다 — 있으면 파싱, 없으면 넘어감. 감시 대상 = 거짓 부재·오파싱** | **전 파싱 경로** |
| **R0-2** | **★계층2 = 인쇄된 값만. 부호 복원·숫자 교정·채움·이동·덮어쓰기 등 값을 바꾸는 일은 계층3 에서 R0-1 증명으로만(이행 중)** | **계층2·3 경계** |
| **R0-1** | **★원문 그대로 적재. 바꿀 수 있는 것은 괄호가 빠진 양수 셀의 부호뿐, 그것도 증명(닫힘·무악화·셀 수 최소 유일, 허용오차 표시단위×⌈항 수÷2⌉, 같은 회사 DART 정기보고서 증거)될 때만. 숫자 교정·빈 칸 채움·행 이동 없음** | **전 계층2 경로 + 검증·수정 판정** |
| R1 | 보고서 원문 read 는 계층2 전용 | 아키텍처 |
| **R2-0** | **정정본은 문서의 부분집합 — 보고서 선택은 '대상 단위 체인 워크'** | **전 파싱 경로** |
| R2 | **정본 정책 = 최초등록본 + 순차 델타 패치** | 계층2→3 |
| R3 | 계층2 는 모든 버전을 전사한다 | 계층2 |
| R4 | 단위는 표가 아니라 **열** 단위로 판정 | 계층2 |
| R4-1 | 로컬 선언 전무 시 문서 전체 기본 단위(요약재무정보/표시통화 주석 텍스트 근거만) | 계층2 |
| R4-2 | 제목+데이터 병합 표 / 제목 자체 없는 표(위치+계정명) — title_text_owned 최후 폴백 | 계층2 |
| R5 | 헤더 의심 행을 삭제하지 않는다(header_hint) | 계층2 |
| R6 | 확정 못 하면 추측하지 않고 NULL + 원문 보존 | 전 계층 |
| R7 | 유니버스 = KOSPI/KOSDAQ 보통주, 외국기업 제외 | 수집 |
| R8 | 새 파서는 배선 2곳 + 소급 백필 + 검증 | 파이프라인 |
| R9 | 검증은 집계가 아니라 원문 대조로 | 작업방식 |
| **R10** | **XBRL 원문(instance) — `preferredLabel=negated*`면 값 부호 반전, `calc:weight`는 저장에 반영 안 함** | 계층2(XBRL) |
| **R11** | **표의 논리적 열 = 헤더·본문을 관통하는 하나의 occupied-grid(본문 행도 ROWSPAN/COLSPAN 확장), 라벨 영역 폭은 `LV′`(본문 값 유무 기반)로 판정** | 계층2(주석·SCE) |
| R12 | 발행주식수("주식의 총수 등")는 BS/IS/CF/주석 tree 밖 cross-cutting 스칼라 — 별도 계층2 테이블·별도 파싱패스 | 계층2(일반현황) |

---

## R2. ★정본 정책 — 최초등록본 + 순차 델타 패치

**규칙** — 한 (기업, 연도, 기간)에 원본과 정정본이 여러 개 있을 때:

1. **베이스 = 최초등록본**(`filed_at ASC` 첫 건).
2. 이후 정정본을 **시간순으로** 훑으며, **값이 다르거나(edit) 새로 생긴(add) 셀만 덮어쓴다.**
3. 정정본이 **건드리지 않은 셀은 원본 값을 그대로 유지**한다.
4. 덮어쓴 셀은 출처를 표시한다(`amended=True` / `amended_by` / `amend_chain`).

즉 **"최신본 하나를 골라 쓰는 것이 아니다."**

**근거** — `fin2/layer3/combine.py:96` `build_merged_lines()` docstring
("★정본 정책(사용자 2026-07-22): 최초등록본 + 순차 델타 패치").
대상 선택은 `fin2/layer3/combine.py:79` `_period_filings_chrono()` — `is_final` 을 **보지 않고**
그 기간의 **모든** filing 을 시간순으로 가져온다.

**왜 이 방식인가** — 정정본은 대개 **부분 정정**이다. 특히 `[첨부정정]`·`[첨부추가]` 는 본문
XML 이 아예 없거나 일부만 있다. 최신본 하나만 쓰면 **정정이 건드리지도 않은 본문이 통째로
사라진다.** combine.py docstring 원문: *"constructed as original+deltas so partial amendments
(첨부정정 / 부분 본문정정) never drop the untouched base."*

**실측 정합** — 원본↔정정본 60쌍에서 SAME 90.9% / CHANGED 6.4% / ONLY_ORIG 1.2% / ONLY_AMEND 1.5%.
셀 동일성 키 = `(statement, basis, col_index, section_path, label_raw)`.

### R2-0. ★ 정정본은 **문서의 임의의 부분집합**이다 — 완전하다고 가정 금지

**규칙** — 보고서 선택은 **문서 단위가 아니라 추출 대상(target) 단위**로 한다.
대상마다 `is_final → … → 원본` 체인을 거슬러 올라가 **그 대상을 실제로 담고 있는 가장 최신
보고서**를 쓴다. **"나중 보고서가 더 완전하다"는 가정은 틀렸다.**

**근거(실측 2026-07-31, 원본↔정정본 123쌍)**

| 정정본의 사업의 내용 표 수 | 쌍 | 비율 |
|---|---:|---:|
| 원본의 90% 이상(사실상 전체 재제출) | 113 | 91.9% |
| 원본이 0표(비교불가) | 7 | 5.7% |
| **0표 = 해당 부분이 아예 없음** | **3** | **2.4%** |

결정적 사례 — 넥스틸 FY2024 `[첨부정정]` `20250327000660`
(https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250327000660):
문서에 **주석 218표 · (첨부)재무제표 17표 · 감사 관련 표**는 있는데
**`I. 회사의 개요`·`II. 사업의 내용`은 아예 없다.**
→ 같은 기간이라도 **주석은 이 정정본이 최신 소스이고, 사업의 내용은 원본이 최신 소스**다.

사용자 지적(2026-08-01): *"정정본에서 항상 전체 문서를 다시 내지는 않아. 회사 주소 바뀐 내용만
한 페이지로 등록하고 말아."* — 실측이 이를 확인했고, 위 넥스틸 사례는 한 페이지보다 넓은
**부분집합**이라는 더 강한 형태다.

**어기면** — ①최신본만 읽으면 그 대상이 없는 정정본을 만나 **통째로 빈다**(R2-1, 547건).
②최신본을 통째로 채택하면 그 정정본이 담지 않은 부분이 **사라진다.**

**선례** — `fin2/layer3/combine.py:184` `select_canonical_rcepts` 가 재무제표에 대해 이미
이 방식을 쓴다: *"Blindly reading only is_final would yield empty/MISSING. Walking the filing
chain (is_final → … → original) **per statement** recovers 307/321 attachment amendments."*

**어기면** — 아래 R2-1 이 실제 사례다.

### ✅ R2-1. (해결 2026-08-01) `biz_metrics` / `order_backlog` 의 is_final 필터

`collector/biz_metrics.py:30` 의 `find_annual_reports()` 는 **`AND f.is_final = TRUE`** 로
최종본 1건만 고른다. 정본 정책의 **베이스인 최초등록본을 아예 파싱하지 않는다.**

실측(2026-07-31):

| 테이블 | is_final=t rcept | is_final=f rcept |
|---|---:|---:|
| `report_lines` (FY2024) | 9,590 | **1,191** ← 모든 버전 전사(R3) |
| `biz_metrics` (전체) | 26,346 | **38** ← 사실상 최종본만 |

그 결과 **`is_final` 사업보고서인데 XML 본문이 없는 547건(447개사)** 이 통째로 건너뛰어진다.
그중 **505건(92%)** 은 같은 기업·같은 연도에 **XML 이 있는 형제 filing 이 디스크에 존재**한다.

원인 유형: `[첨부정정]` 457 · `[기재정정]` 52 · 그 외 38.
`[첨부정정]` 은 첨부만 고치므로 XML 본문이 없는데, `is_final` 플래그는 가져간다.

구체 사례 — 중앙에너비스 FY2025:

| rcept_no | 종류 | is_final | XML |
|---|---|---|---|
| 20260312000614 | 사업보고서 | f | ✅ |
| 20260730000356 | [기재정정] | f | ✅ |
| 20260730000361 | [첨부정정] | f | ❌ (PDF만) |
| **20260730000551** | **[첨부정정]** | **t** | **❌ (PDF만)** |

→ 본문이 담긴 XML 2건이 모두 `is_final=FALSE` 라 **FY2025 전체가 미파싱**.

**조치 예정** — R2 대로 `find_annual_reports` 를 "그 기간의 모든 filing 을 시간순으로" 로 바꾸고
`biz_metrics` 적재를 원본+델타로 재구성. 미착수(2026-07-31 백필 완료 후).

**조치 내용 (2026-08-01)**

| 구성요소 | 역할 |
|---|---|
| `collector/filing_select.py` | **보고서 선택 단일 지점.** 한 기간의 모든 보고서를 오래된 것부터 반환(`is_final` 미사용) |
| `collector/biz_merge.py` | 시간순 **항목 단위** 병합. 정정본이 다시 낸 항목만 덮어쓰고 나머지는 유지 |
| `collector/biz_metrics.py` | 기간 단위 파싱·병합·적재로 전환. 멱등 범위 rcept → **(corp, fiscal_year)** |
| `collector/order_backlog.py` | 동일 계약 적용(항목 동일성 = `category`) |
| `scripts/nightly_gap_fill_backfill.py`·`phase_c_rebuild.py` | is_final 필터 제거 |
| `tests/test_parsing_rules_r0.py` | **재발 방지** — 적재 모듈이 `is_final` 을 소스 필터로 쓰면 실패. 부분 정정본 병합 동작도 고정 |

**검증** — FY2025 가 통째로 비어 있던 3사가 적재됨(이전 0행):
아이엠바이오로직스 159행 · 케이엘넷 296행 · 중앙에너비스 48행.
중앙에너비스는 `20260730000356 [기재정정]` 에서 나왔다(본문 없는 `[첨부정정]` is_final 이 아니라).
`order_backlog` 오르비텍 22행 → 172행, **삭제 0(추가만)**. 회귀 118건 통과.

**전수 재적재 완료 (2026-08-01 08:21 / 08:49)**

| | 이전 | 이후 |
|---|---:|---:|
| `biz_metrics` 행 | 7,537,995 | **7,718,962** (+2.4%) |
| `biz_metrics` 출처 보고서 | ~26,346 | **38,733** |
| `order_backlog` 행 | 2,211 | **24,687** (11×) |
| `order_backlog` 기업 | 566 | **1,004** |

biz: 2,530사 · 보고서 53,653 · 표 524,007 · 오류 0.
보고서를 29% 더 읽었는데 행은 2.4%만 는 것이 정상이다 — 정정본 대부분이 원본과 같은 내용이라
병합이 접어낸다. **출처 보고서 26,346 → 38,733** 이 실제로 더 많은 판을 읽었다는 증거.

`order_backlog` 의 11배 증가는 병합 효과가 아니라, 종전 적재가 **최신 1건만** 대상이라
과거 연도가 통째로 비어 있었기 때문이다(R2-1 과 별개 결함).

### ⚠ 재적재 중 발견해 고친 것 2건

1. **병합 키가 행을 버리고 있었다(내 구현 결함).** 한 보고서 안에서 식별자가 되풀이되는 행을
   '중복' 으로 보고 버려, **구 적재 방식 대비 21.94% 유실**(일부 기간 60%↑). 재적재를 중단하고
   되풀이를 **순번으로 구분**하도록 고쳐 유실 0% 확인 후 재시작.
   → `tests/test_parsing_rules_r0.py` 에 "단일 보고서 파싱 결과가 그대로 보존되는가" 고정.
2. **`bigint` 범위 초과로 기업 전체가 실패.** 셀 병합 결함(부록 C)이 만든 천문학적 값이
   INSERT 를 터뜨려 **그 기업의 수주 데이터 전부**가 사라졌다(3사). 행을 버리지 않고
   **문제 필드만 NULL** 로 낮추도록 가드 추가 — 같은 행의 정상 값은 보존.

**★ 델타 키 실측(2026-07-31, `scripts/probe_biz_amendment_key.py`, 원본↔정정본 41쌍)**
※ 아래 측정은 '표 단위 델타' 를 검토하던 단계의 것으로, **R0 확정 후 그 설계는 폐기**됐다.
   항목 동일성은 `collector/biz_merge.py` 의 (metric, 캡션, segment, item, period_label) 로 간다.

계층3 의 셀 키를 그대로 못 쓴다 — `biz_metrics` 는 long-format 이라 대응 키를 새로 정해야 하고,
**행 단위 키는 전부 탈락**했다. 한 보고서 안에서조차 유일하지 않기 때문이다.

| 행 키 | 정렬 | **키 충돌** |
|---|---:|---:|
| metric+segment+item+period_label | 99.6% | **9,411** (SAME 6,702 보다 많음) |
| metric+segment+item+period_year | 99.6% | 14,729 |
| metric+segment+period_label | 99.9% | 14,489 |

한 보고서에 같은 `(metric, segment, item, period_label)` 을 내는 표가 여럿이라 절반 이상이
식별 불가다. 실제로 오매칭 증거도 나왔다 — 한화생명 FY2025 `ins_solvency 지급여력(A)`
3,197 → 22,901,084(서로 다른 표의 행이 같은 키로 붙음).

**표 단위 식별은 유효하다:**

| 표 키 | 양쪽 | 원본만 | 정정만 | 정렬 | 키 충돌 |
|---|---:|---:|---:|---:|---:|
| metric+캡션40자 | 513 | 0 | 1 | 99.8% | 150 |
| **metric+캡션40자+표모양** | **572** | **1** | **3** | **99.3%** | **29** |
| metric+표모양 | 518 | 1 | 3 | 99.2% | 137 |

→ **제안: 셀이 아니라 '표' 단위 델타.** 표 식별이 같으면 나중 보고서가 통째로 이기고,
정정본에 없는 표는 원본 것을 유지한다. R2 의 원칙("정정이 건드리지 않은 것은 원본 유지")을
이 데이터의 자연스러운 입자(=DART 정정은 셀이 아니라 표 단위로 다시 낸다)에 맞춘 것.
**미승인 — 사용자 확인 후 착수.**

---

## R6. 확정 못 하면 추측하지 않는다

**규칙** — 후보가 여럿이면 **고르지 않는다.** 값이 갈리면 판정 불가 → 보류(NULL) + 원문 보존.

**적용 범위 (2026-10-09, R0-1)** — 이 규칙은 두 경우에만 쓴다.
- 숫자를 읽을 수 없음(값이 둘 이상으로 읽힘): 행은 싣고 값만 NULL + 원문 문자열 보존.
- 기간·열을 정할 수 없음: 그 셀(행·표)을 싣지 않는다.

숫자는 읽히는데 부호나 값이 틀려 보이는 경우는 R6 이 아니라 R0-1 4번을 따른다: 증명되면 고치고, 증명이 안 되면 **인쇄된 그대로** 싣는다(NULL 로 지우지 않는다).
R9 의 "판단이 안 서면 사용자에게 제시"는 조사 작업에 대한 것이다. 검증·수정 판정에는 R0-1·판정표를 쓴다.

**근거** — `fin2/extract/rd_note.py` ("후보가 여럿이면 **고르지 않는다**(추측 금지)"),
`fin2/standardize/calendar.py` (flow = ΣCQ, "하나라도 None → None, 추정 금지"),
R4 의 NULL 규약.

**어기면** — 유실은 복구 가능하지만 오염은 조용히 하류로 퍼진다(R4 사례).

---

## R9. 검증은 집계가 아니라 원문 대조로

**규칙** — 지표가 이상하면 **개별 사례를 원문까지 따라간다.** 집계로 끝내지 않는다.
휴리스틱 신호를 만들 때는 **거짓양성 모드를 먼저 의심**하고, 가능하면 휴리스틱 대신
**실제 코드 경로를 계측**한다. 판단이 안 서면 혼자 결론내지 말고
**DART 링크 + 문제 부분**을 사용자에게 제시한다 (`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<rcept_no>`).

**근거** — 메모리 `feedback-verify-against-source`. 2026-07-29 세션에서 원문 텍스트 휴리스틱으로
**거짓양성 5연속**(38.8%→27.2%→9.4%→21.9%→실제 0%).

**대전제** — **V2 는 정답이 아니다. DART 원문이 기준이다.**

---
