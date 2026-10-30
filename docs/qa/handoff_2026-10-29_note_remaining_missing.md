# 인계 — note(주석) 남은 누락 이슈를 하나씩 보기 (2026-10-29)

> 다음 세션 시작점. 설계·경과: `docs/plans/verification_note_biz_expansion_design_2026-10-27.md` §6-5~6-7.
> 메모리: `verify-note-biz-expansion-2026-10-27`.

## 0. 갱신 (2026-10-29 밤) — `total` 범주 5 사이클 결과

| 사이클 | 규칙 | 배치 | total 범주 missing_row |
|---|---|---|---|
| 시작 | | | 21,556 |
| 1 | R294 (금액 + 외화/기호 꼬리 칸의 첫 금액, `edcf0af`) + 보완 `a9cd234`(꼬리가 금액에 붙어 옴) | 249·250 | 12,760 |
| 2 | R295 (첫 물리 칸이 빈 행의 라벨, `edd1f29`) | 251 | 6,912 |
| 3 | 기계 mn9 (`a00b9c8`, DB `value_raw` 꼬리 읽기) + R294-b (`$`·`US$`·임의 통화코드, `8d80b64`) | 252 | 2,385 |
| 4 | R295-b (값 영역의 합계 단어를 라벨로) + R294-c (전각 `＄`) (`b247ac8`) | 253 | **1,380** (필링 489) |
| 5 | R294-d (꼬리 셀만 있는 열은 값 열 + 꼬리 항목 확장) + 기계 mn10 (value_raw 64자 잘림) (`5d0117f`) | 254 | **1,249** (필링 430) |
| 6 | R296 (한 행에 여러 논리 행이 줄로 압축된 칸을 줄 단위로 나눔, 주석 섹션 한정) (`adf96a2`) | 255 | **1,097** (필링 415) |

- 이슈: closed 298,118 · reopened 100,368 · open 1,395.
- 교훈: ① 격자가 `&cr;` 를 공백으로 접거나 **아예 지운다** — 셀 문자열 규칙은 붙은 꼴도 시험한다(R294 1차는 공백을 요구해 3,302건만 닫음). ② 이슈 분류는 "원문 셀"과 "DB 행 상태" 두 방향으로 본다 — 후자가 기계 문제(M)를 드러냈다. ③ A/B 는 `row_order` 가 아니라 (표, 라벨, 열, 값)으로 비교한다(행이 끼면 아래 행 순번이 밀린다). ④ 규칙 문서는 R294/R294-b/R294-c/R295/R295-b(`10_layer2_parse.md`), 기계는 설계 문서 §6-8.
- 남은 1,249건(2026-10-30 재분류, 원문 셀 모양 기준 1,380건 시점): 숫자만 여러 개 평탄화된 칸 519 · 일반 칸 339 · 한글 포함 272 · 원화+통화꼬리 89 · 원화+기타 꼬리 89 · 표 못 찾음 64. ★평탄화된 칸의 상당수는 외화가 아니라 **한 칸에 여러 행의 원화 값이 줄로 들어간 압축 칸**(`수익&cr;금융수익&cr;…&cr;소계` 라벨 칸 + `151,568,153 - 151,568,153 …` 값 칸) — 라벨 줄 수와 값 줄 수가 같을 때만 줄별로 나누는 규칙이 다음 후보(R152 계열). 외화(통화별) 저장은 스키마 변경이 필요해 사용자가 필요하다고 할 때 추가한다(원화만 적재가 현재 방침, 2026-10-30). 한글 꼬리·통화 표시 없는 외화 숫자 칸은 기계가 비교에서 제외할지(R6 유지) 결정 대기.
- 그 밖의 범주(`other` 49k·`unlabeled` 17.5k·`shares_or_price` 8.3k)는 R295/R295-b 가 일부 닫았을 수 있다 — 숫자는 `python scripts/note_remaining_triage.py` 로 다시 본다.

## 1. 지금 상태 (2026-10-29)

| 항목 | 값 |
|---|---|
| note 이슈 | closed 277,942 · reopened 120,535 · open 884 |
| 슬롯(note) | passed 71,624 · has_issues 22,319 · pending 188 |
| 기계 mismatch 필링 | 24,953 (처음 50,267) |
| 기계 | `fin2/verification/machine_note.py` **mn8** (연도 대칭 제외) |
| 반영된 규칙 | R290(주석 R160) · R291(두 값 셀/헤더 경계) · R292(환율변동=금액) · R293(비금액 열 R158 제외) |
| 마지막 커밋 | `21e0b64` (origin/main 반영) |
| 돌고 있는 작업 | 없음(report 기계 데몬 `machine_daemon` 만 상시 가동) |

남은 **누락(missing_row)** 은 약 9.7만 건:

| 범주 | 건수 | 필링 | 범주 판정(account_label) |
|---|---|---|---|
| `other` | 49,222 | 10,733 | 아래 넷에 안 걸린 것 — 은행명·항목명 등 다양 |
| `total` | 21,556 | 4,781 | `합계|소계|총계|^계$` |
| `unlabeled` | 17,532 | 4,385 | `열 N` / `행 N` (라벨을 못 찾은 행) |
| `shares_or_price` | 8,267 | 2,154 | `보통주|우선주|행사가격|주식수|주당` |
| `currency_code` | 219 | 92 | `USD/EUR/JPY…` 통화 코드 (R290 으로 9,213 → 219) |

그 밖의 열린 이슈: extra_row ≈ 2.2만 · extra_table 2,749 · value_mismatch/unit_scale ≈ 620.

## 2. 하나씩 보는 법 (읽기 전용 — 아무것도 쓰지 않는다)

```bash
python scripts/note_remaining_triage.py
python scripts/note_remaining_triage.py --cat total -n 10
python scripts/note_remaining_triage.py --show 252328
```

- 첫 줄: 오류유형 × 범주별 건수.
- `--cat <범주> -n N`: 그 범주의 무작위 이슈 N건과 `--show` 명령.
- `--show <issue_id>`: DART 링크 · 원문 XML 경로 · DB `note_lines` 의 그 표(앞 30행) · 원문 표(DB 표와 금액이 가장 많이 겹치는 표, 값이 든 행 + 앞 3행). 수동 검토 때는 **DART 링크와 XML 경로를 항상 함께** 본다.
- 범주: `other` `total` `unlabeled` `shares_or_price` `currency_code`.

### 시작용 표본 (범주별 5건)

```
### total
#252328 [reopened] 20171114001696 separate 표80 '합계' [원문 c4] 257,040  원문값=257,040
#322699 [reopened] 20191114002058 consolidated 표117 '합계' [원문 c3] 19,932,066  원문값=19,932,066
#368089 [reopened] 20210517000791 separate 표31 '합계' [원문 c5] 105,000,000  원문값=105,000,000
#221799 [reopened] 20170331000025 separate 표166 '합계' [원문 c2] 7,500,000  원문값=7,500,000
#189575 [reopened] 20160330001559 consolidated 표51 '합계' [원문 c2] 229,268  원문값=229,268
### unlabeled
#348548 [reopened] 20200819000066 separate 표25 '열 5' [원문 c5] -867,557  원문값=-867,557
#370140 [reopened] 20210521000347 consolidated 표72 '열 5' [원문 c5] 6,260,518  원문값=6,260,518
#216979 [reopened] 20161114002347 separate 표5 '열 4' [원문 c4] 302,583  원문값=302,583
#462640 [reopened] 20240516001124 consolidated 표173 '열 0' [원문 c0] 1,000,000  원문값=1,000,000
#354049 [reopened] 20201113000752 consolidated 표69 '열 3' [원문 c3] 16,657,628  원문값=16,657,628
### shares_or_price
#530312 [reopened] 20260515001921 separate 표49 '보통주' [원문 c3] 5,000  원문값=5,000
#496647 [reopened] 20250515001046 separate 표29 '보통주자본금' [원문 c1] 27,947,646,000  원문값=27,947,646,000
#557165 [reopened] 20231113000447 separate 표76 '행사가격' [원문 c7] 2,187  원문값=2,187
#408185 [reopened] 20220811000410 separate 표13 '(주)옵토레인상환전환우선주' [원문 c4] 5,011  원문값=5,011
#282096 [reopened] 20181114000255 consolidated 표60 '행사가격(주1)' [원문 c4] 3,670  원문값=3,670
### other
#201209 [reopened] 20160504000303 consolidated 표41 '우리은행' [원문 c4] 6,000,000  원문값=6,000,000
#197854 [reopened] 20160330003788 consolidated 표65 'CrossroadsEquimentLeasea' [원문 c3] 370,062  원문값=370,062
#438822 [reopened] 20230811001879 separate 표113 '관계기업' [원문 c3] 4,900,000  원문값=4,900,000
#201053 [reopened] 20160330004244 consolidated 표88 '파생상품거래손실' [원문 c4] 4,840,580  원문값=4,840,580
#367215 [reopened] 20210514000057 consolidated 표30 '토지' [원문 c2] 158,989,803  원문값=158,989,803
### currency_code
#392012 [reopened] 20220211000593 consolidated 표51 'USD' [원문 c4] 27,169,384  원문값=27,169,384
#170136 [reopened] 20150513003942 separate 표105 'JPY' [원문 c4] 1,837,815  원문값=1,837,815
#437245 [reopened] 20230320000944 consolidated 표202 'EUR' [원문 c2] 9,207  원문값=9,207
#185011 [reopened] 20151116000870 separate 표108 'JPY' [원문 c2] 3,426,515  원문값=3,426,515
#171820 [reopened] 20150515001189 consolidated 표62 'CNY' [원문 c4] 858,666  원문값=858,666
```

## 3. 이미 확인한 것 (다시 조사하지 말 것)

- **#252328 (합계, 엠씨넥스 2017Q3 별도 표 80)**: 원문 마지막 줄 `[빈칸] | 합   계 | 187,724 | 31,776 | 257,040` 이 DB 에 **줄째 없다**. 라벨이 첫 칸이 아니라 **둘째 칸**(첫 칸은 앞 행 ROWSPAN 영역)에 있는 합계 행이다. 합계 부류 전체가 이 구조인지는 **아직 모른다** — 표본 5~10건을 더 봐서 확인할 것.
- 병합 라벨(ROWSPAN) 이후 행 밀림: **파서 수정 불필요**였다(R166/R284 가 코드에 있었고 DB 가 낡았음 → 재적재로 해소).
- 외화금액 열 누락·두 값 셀·`환율변동` 비금액·환율/지분율 오귀속: R290~R293 으로 처리 완료.
- 기계 오탐 부류(이미 반영, 다시 만나면 기계 버전부터 의심): 중첩 표 평탄화 · 정정전/후 쌍둥이 표 · 본문 `<…>` · 병합 셀 복제(DB 는 표마다 한 번/전개로 갈림) · 연도 머리글(1900~2100, 양쪽 제외) · `non_monetary` 열은 인쇄값이 `value_raw`(기계가 읽음).
- 기계가 **일부러 비교하지 않는 것**: 1,000 미만 정수(지분율·비율·주석번호), `주당…` 행, 0/대시/소수 셀. 이 때문에 "clean" 이 모든 숫자의 일치를 뜻하지는 않는다.

## 4. 한 사이클(원인을 하나 고친 뒤) — 순서가 중요하다

1. 원인 확인(`--show`) → `PARSING_RULES` 진입점·계층 파일 확인 → 규칙을 `docs/rules/10_layer2_parse.md`(+색인)에 먼저 적는다.
2. 수정 → **회귀 테스트(옛 코드에서 실패 확인)** → 같은 표본으로 DB 와 새 추출 비교(추가/삭제/변경 행 수, 예상 밖 변경이 없는지).
3. 전체 테스트 `pytest tests/ fin2/tests/ --deselect fin2/tests/test_r168_dual_column_closing_row.py::test_no_run_still_skipped_r6 --deselect fin2/tests/test_r168_dual_column_closing_row.py::test_balance_row_ends_the_group` (약 16분, 기존 R168 2건은 변경 전부터 실패).
4. 커밋 → push (`batch reload` 는 push 된 HEAD 가 필요).
5. 이전 배치 `batch_set(N, status="done")` → `python scripts/vq.py batch new --type missing_row --scope note ...` (reopened 는 이전 배치에 묶여 있으므로 배치를 먼저 닫거나 UPDATE 로 합친다).
6. `python scripts/vq.py batch reload N --shard i/8 --sd` ×8 (tmux, 약 250필링/분) — **주석 전용 `ops._reload_note`** 가 쓰인다(본문 report_lines 는 건드리지 않음).
7. `batch mark-fixed N` → `scope recheck --scope note --apply --shard i/8` ×8 → `scope run --scope note --shard i/8` ×8 → `scope register-all --scope note --apply --shard i/8` ×8(재적재로 새로 드러난 불일치) → 필요하면 `scope retriage --scope note --apply --shard i/8`.

## 5. 함정 (이번 작업에서 실제로 겪은 것)

- **scope 를 더하면 기존 조회를 전수 점검한다.** `issues.scope` 도입 후 report 쪽 조회에 필터가 빠져 note 이슈 36만 건이 report 기계를 1.5시간 공회전시켰다(6e0100d).
- note 배치는 반드시 `_reload_note`. 전체 경로(`_reload_rcept`)는 본문 `section_path` 가 바뀌어 검증이 끝난 report 슬롯을 pending 으로 되돌린다.
- 36만 건짜리 `mark-fixed`/`recheck`/`register-all` 은 샤딩(`--shard i/n`) 필수. `tmux kill-session` 은 `&` 로 띄운 자식을 죽이지 않는다(백필 중복 실행 283건 오류) — 재시작 전에 `ps` 로 확인.
- 워커 종료는 PID 지정으로, 패턴 `pkill` 은 권한 판정에서 거부될 수 있다.
- `fixed` 로 가려면 재적재가 데이터를 실제로 바꿔야 한다(트리거). 안 바뀐 필링의 이슈는 `mark-fixed` 가 거부 → `--exclude` 또는 admin `transition` 으로 풀 것(이번에는 거부 0건).
- 새 규칙은 `_emit_note_lines`/`units` 안에 두면 데일리 두 call site 에 추가 배선이 필요 없다(`collect_new.py::_sync_layer2_lines` 공유).

## 6. 열려 있는 결정 (사용자)

- 남은 누락을 어느 범주부터 볼지: 추천은 `total`(구조가 단순해 보임) → `unlabeled` → `shares_or_price` → `other`.
- biz: 저장되지 않은 숫자 표(약 62%)를 "누락"으로 볼지 — 기계는 지금 세기만 한다(`unstored_numeric_tables`).
- 기존 실패 `fin2/tests/test_r168_dual_column_closing_row.py` 2건은 이번 작업과 무관하게 이전 커밋부터 실패 중.


## 2026-10-30 새벽 추가: R296 와 남은 범주
- R296 은 합계 이슈 1,249건 필링만 재적재했다(효과 -152). 압축 칸 구조는 `other`·`unlabeled` 범주에도 있을 가능성이 크지만 그 범주들은 아직 재적재/recheck 대상이 아니다 — 열린 note 이슈 전체(약 2.4만 필링, 약 100분)를 같은 배치 절차로 돌려 효과를 보는 것은 **사용자 승인 후**.
- ★R296 교훈: 읽기 단계(`sanitize_dart_xml`) 변경은 본문 재무제표 경로에도 번진다. 첫 판은 코리안리 IS 를 깨뜨렸다(테스트 2건이 잡음, A/B 표본은 못 잡음) → 주석 섹션(SECTION 제목에 '주석')의 TR 로 한정했다. 읽기 단계 변경은 A/B 표본에 본문 표가 큰 보고서(보험·금융)를 넣고 `tests/test_r258_r259_stacked_amount_cells.py` 를 꼭 돌릴 것.
- 남은 합계 1,097건 중 한글 꼬리·통화 표시 없는 외화 숫자 칸은 기계가 비교에서 제외할지 결정 대기(R6 유지).