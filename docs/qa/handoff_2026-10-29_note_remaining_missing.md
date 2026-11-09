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
## 2026-11-01 추가: 전체 재적재 이후 extra_row 정리 (mn11·mn12·retriage·R273-b·R296-b)

- **전체 재적재(배치 256/257, 열린 note 필링 약 2.3만)** 뒤 extra_row 1,355건이 새로 생겼고 절반은 기계가 원문을 못 읽은 탓이었다 → **mn11**(R294 꼬리 셀·쪼개진 숫자 셀을 로더처럼 읽음), **mn12**(R296 줄 쌓인 행을 줄 단위로 읽음). 원칙: 기계의 원문 읽기는 로더가 읽는 것과 같아야 한다.
- **`scope retriage`**(`scope_issues.retriage`): `scope recheck` 는 fixed 이슈만 보므로 open/reopened 인 묵은 이슈(옛 기계 버전 산물)는 안 닫힌다. 현재 기계가 더는 내지 않는 열린 이슈를 닫는다(dry-run 기본, `--apply`). 필링의 발견이 400건(MAX_FINDINGS)에서 잘렸으면 그 필링 이슈는 남긴다. 결과: 16,437 닫고 66,015 유지(extra_row other 19.6k→5.4k, total 1,553→309).
- **extra_row total 309건 분류**(원문 셀 모양): 깨진 쉼표 묶음 137 · `-&cr;금액` 부호 9 · 끝 마침표·`(-N)`·잡문자 약 23(기계 한계, 로더가 읽고 기계가 거절) · 같은 금액이 다른 곳에 깨끗한 셀로 있음 약 65(근거 부족) · 원문 표에 있음 38 · 다른 note 표에 있음 37.
- **R273-b**(깨진 쉼표 4모양 → NULL+value_raw)·**R296-b**(칸 시작 `-` 뒤 `&cr;` 금액 → 결측) 적용(커밋 `fbd0403`), 해당 123필링 note 재적재(배치 262, 이슈 352 중 closed 114). 대상이던 146건 중 `-&cr;` 9건 전부·깨진 쉼표 92건이 닫혔고 45건은 두 묶음(`552,24`)·기타 모양이라 남음. extra_row total 309→215.
- **현재(2026-11-01 02시)**: extra_row other 5,424 · total 215 · shares 33 · currency 18; extra_table other 1,495; missing_row other 31,733 · unlabeled 17,391 · shares_or_price 8,201 · total 1,199 · currency 170; value_mismatch other 285.
- **열린 일**: ① 두 묶음 깨진 쉼표(`552,24` 등 약 40건)는 소수/주석번호와 구분이 안 돼 R273 이 일부러 제외 — 사용자 판단 대기. ② 끝 마침표·`(-N)`·잡문자(`2/,109,336`) 셀은 로더만 읽는다 — 기계 한계로 둘지 로더를 맞출지 미정. ③ 재적재는 이슈가 있는 필링에만 했다(이슈 없는 필링의 같은 모양 셀은 그대로; 전체 note 재적재는 사용자 결정). ④ 엔브이에이치코리아 20240514001365 table 56 `12,410,000JPY 78,000` ROWSPAN 셀 등 R294 꼬리 셀이 DB 에 실제로 없는 건. ⑤ missing_row 3.1만/1.7만/8천 범주 분류.
- **함정**: `pytest` 전체는 `fin2/tests/test_r168_dual_column_closing_row.py` 가 알려진 실패(파일째 `--deselect`); `-x` 를 쓰면 거기서 멈춘다. `batch new --type` 은 error_types 의 값(extra_row 등)만 허용한다(`note` 불가).

## 2026-11-01 (오후) 추가: extra_row other 5,424 분류와 R297

- **분류(원문 셀 모양)**: DB 금액이 원문 셀의 쉼표만 지운 숫자 3,811 · 짝지은 표에 있음 762 · 다른 note 표에 있음 707(둘 다 기계의 표 짝짓기·중복 행 한계로 보임, 셀 단위 분류 안 됨) · 원문에 없음 144.
- 3,811 내역: R273-b 모양(재적재 전 옛 값) 약 1,680 · `주석`/`관련주석` 열의 주석번호 목록 약 1,380 · 두 묶음 오타(`160,21`→16,021: 합계 160,211 과 비교해 10배 틀림) 약 710(열 머리가 주석이 아닌 것) · 정상 모양인데 기계가 못 찾음 약 613(원인 미확인).
- **R297**(주석 표의 마지막 머리글 마디가 `주석`·`주석번호`·`주기`·`관련주석` 인 열은 싣지 않음, 커밋 대상 fin2/extract/report_lines.py) + 배치 263(1,080필링 note 재적재, 이슈 3,535 중 closed 2,471). extra_row other 5,424→2,986, total 215→213.
- **열린 일**: ① 두 묶음 오타(`999,99` 등) 처리 — 사용자 판단 대기(선택지: 단위가 선언된 금액 열에서 `00` 아닌 모양만 NULL / 기계 한계로 기록). ② 정상 모양인데 못 찾는 약 613건 원인 조사. ③ 짝지은 표에 값이 있는 762건·다른 표 707건의 짝짓기 한계. ④ 이슈 없는 필링의 주석 열·깨진 셀은 그대로(전체 note 재적재는 사용자 결정).

## 2026-11-01 evening - machine mn13 and the 613 "valid-looking" cells

- Decision (user): two-group damaged cells (`160,21`, `119,55`, `99,99`, ~730 non-note-column extra_row issues) are recorded as a **machine limit**; no rule, no NULL. They stay open as known noise.
- The ~613 "valid grouped number the machine cannot find" were a machine reading bug, not a data bug: a cell whose digits are split over tags/lines (`<SPAN>1</SPAN>` `<SPAN>4</SPAN>` `<SPAN>9,810</SPAN>`, 에이치케이 20161114000399 table 23) is joined by the loader to 149,810, but `machine_note._read_source_cell` read the first line (`1`). mn13 (`47126a6`) tries the joined reading first.
- Re-classification of the 2,986 open extra_row other issues: valid grouped not found 619 -> 259, value in paired table 751 -> 1,418.
- `scope retriage` (note, 8 shards, dry-run then apply): 1,194 stale issues closed. extra_row other 2,986 -> 2,168, total 213 -> 108, value_mismatch other 284 -> 111.
- Still open: 259 valid-looking grouped values not found (mostly trailing-dot and 4-digit/2-digit shapes, see `xo3_sum.py` output), 1,418 "value exists in the paired table" (table pairing / duplicate-row limits, not analysed by cell), 357 in another note table, 145 nowhere, 730 two-group (machine limit).

## 2026-11-02 - cell-level pass over the remaining extra_row other issues (mn14, mn15, batches 264/265)

- **Method that worked**: compare the CURRENT parser's note cells with the DB per issue cell (`scratchpad/stale.py`) and per filing (`stale2.py`). A cell the current parser no longer loads the way the DB has it = stale DB (reload), anything else = machine reading limit or a real table-pairing case.
- Batch 264: 478 stale cells (e.g. 삼보판지 20150515000896 `-&cr;3,200,000&cr;JPY...` loaded as -3.2B, 포니링크 20200813000190 `1,6000,000`) -> 8-shard note reload, failed 0. Batch 265: the 39 filings whose DB differs from the current parser anywhere (first run refused: dirty tree - commit before `batch reload`; rerun ok).
- mn14 (`trailing dot`, `810,000.`, 105 issues) and mn15 (R158 dot-grouped cell `8.490`/`(109.886)`/`2.939,347` is the integer when the row prints the same digits with commas) are machine-reading fixes mirroring the loader; `scope retriage` closed ~236 more.
- State now: extra_row other 1,328 (1,009 filings), total 60, shares 21, currency 2. Remaining: two-group damaged cells ~730 (machine limit, user decision 2026-11-01), valid-looking grouped values the machine cannot find ~86, odd shapes ~68, nowhere ~130, value in another note table ~100, paired-table cases (duplicates / row counting) rest of the ~420.
- Untouched: filings without open issues keep their old note rows (full note reload = user decision).

## 2026-11-03 - remaining extra_row other, cell by cell (R273-c, R298, mn16-mn18, batches 266/267)

- **R273-c** (`2063932`'s parent commit, see git log): 3+ comma groups with a non-3-digit group after the first (`4,15,36,37`, `2016,05,20`, `9,99,99,99`, `12,5,100`, `27,28,29`) are note lists/dates, NULL + value_raw. This reverses the R273-b decision that left `12,5,100` alone. A/B 242 filings: 36 changed, 68 cells -> NULL, 0 gained, no body change. The earlier commit message mentions the 앱튼 example as `20260...`: the filing is 20260323001074.
- **R298** (`2063932`): a column headed `㎡`/`㎥`/`면적` is no amount (value_won empty, value_raw kept). Found via 진바이오텍 20220318000006 table 30 (7,494 ㎡ loaded as 7,494,000). DB-wide: `㎡` in the header of 14,003 value_won cells (1,642 filings), `면적` 11,500 cells (1,614 filings). A/B 180 filings: 20 changed, 51 cells -> NULL, 0 gained. **Open decision**: only filings with open issues were reloaded (batch 267, 110 filings, failed 0); the other area-column filings (about 1.6-2.5k) keep the old contaminated cells until a targeted note reload (hours).
- Machine: mn16 `(-715,525)`, mn17 printed decimals joined as the ROUND_HALF_UP integer to the alt values (82 of 130 'nowhere'), mn18 numbers broken by `&cr;` inside a cell. `scope retriage` after each.
- Batches: 264 (478 stale cells), 265 (39 filings), 266 (50 filings), 267 (110 filings) - all note-only reloads, failed 0. Pipeline = `scratchpad/pipeN.sh` (8-shard reload --sd, mark-fixed, recheck/run/register-all, set done); the tree must be clean (commit first) or reload is refused.
- Method: `stale.py` (per issue cell) / `stale2.py` (whole filing) compare the current parser with note_lines; filings that differ go into a batch. Run it again after every parser change.
- State: extra_row other 1,060 (846 filings), total 49, shares 20, currency 2; extra_table other 1,492; value_mismatch other 85. Left: two-group damaged cells ~730 (machine limit), nowhere ~90, paired-table duplicates ~200, other note table ~70, valid-looking ~30.

## 2026-11-03 evening - area-column reload, extra_table/value_mismatch, R299/R300

- **Area-column reload done** (user approved: "면적 열 필링 재적재 ... 주석 부분만 2015+"): 1,761 filings of 2015+ with `㎡`/`㎥`/`면적` in a note column header, note-only reload through `scratchpad/area_reload.py` calling `ops._reload_note` (no batch, no issues needed), 8 shards, failed 0, then recheck/run/register-all. `scope --scope note --apply retriage` (the option goes BEFORE the subcommand; a call without `--apply` is a dry run) takes 40-60 minutes.
- **mn19**: a DB note table the pairing score cannot match is no extra_table when all its amounts are printed in the source of the basis. extra_table 1,492 -> 67 (899 of the 1,425 were tables with one or two amounts). **mn20**: a value difference whose two numbers both exist on the other side of the filing is a mis-aligned row. value_mismatch 119 -> 28. Retriage closed 1,484 issues.
- **R299** (note cells with their own `원` suffix get adecimal 0; the machine had reported 75 unit_scale issues, values were right) and **R300** (rows whose label ends in a share count are no amounts: `발행주식수`, `가중평균유통보통주식수(*)`; 6,530,014 shares were stored as 6,530,014,000 won). R300 A/B on 412 filings: 171 changed, 998 cells value -> NULL, 0 gained, 0 body. **Open decision**: 30,510 filings of 2015+ hold such share rows (`scratchpad/share_filings.txt`); the backfill is a note-only reload of about 10 hours (`scratchpad/pipe_share.sh` is ready, NOT started). It also refreshes older note rows (R294-R297, R273-c) of those filings.
- Dropped after measuring: stopping a data table from donating its unit to a later table (케어젠 20230504000817 note 25, bare `5,371,500,000` stored x1000 next to `5,371,500,000원`): 900 cells of 75 of 412 filings would turn NULL, mostly legitimate 천원 amounts.
- Still open: extra_row other 1,062 (two-group machine limit ~730), extra_table 67, value_mismatch 28 (DB amount absent from the source or the other way), unit_scale 0 after retriage should be checked, missing_row 58.8k. Candidate sign defect seen once: 피제이전자 20150813000809 table 13, cell `- &cr;- &cr;1,473,000,000` loaded as -1,473,000,000 (parse_amount reads `- - N` as negative; R296-b covers only a single leading dash line); a 2015+ source scan (`scratchpad/dash_scan.py`, results `dash_hits_*.json`) was still running.
- **R301** (`074ccde`): several lone `-` lines before an amount line (`- &cr;- &cr;1,473,000,000`, 피제이전자 20150813000809 table 13, was -1,473,000,000) are no negative amount (R296-b extension; the row is not loaded). A/B 413 filings: 1 changed, 2 rows lost, 0 gained. Source scan of all 2015+ filings (`scratchpad/dash_scan.py`, about 3.5 h on 8 shards because the XML is read from SD) found 559 filings with a dash-line-then-amount cell; all 559 got a note-only reload (failed 0) followed by recheck/run/register-all and `scope --scope note --apply retriage`. Still waiting for a decision: the 30,510-filing share-count reload (R300, about 10 h, `scratchpad/pipe_share.sh`, not started).

## 2026-11-04 - R302, mn21, value_mismatch/extra_table cleanup

- **Stale-DB check first**: value_mismatch 11 -> 5 after a note reload of 9 filings that still held pre-R299 adecimal (SNT에너지 `3,648,575,000원`, 에스엠지아시아) and a retriage. Left 5: 오상헬스케어 20150515002358 (a cell `90&cr;32` is joined to `9032` in value_raw - a read-stage join across a line break, one case), `$400,000` foreign-currency rows x3, one actuarial row.
- **R302** (`ee2f4a2`, `f1ddab5`): a note row whose label ends in its own unit (`(단위: 주|건|개|명|일|%|배|회)`, `(%)`, `(일)`) is non-money (value_won empty, value_raw kept); `(단위: 원)` is read with multiplier 1 in a 천원 table. Found via 휴맥스 20260814001937 (91 days stored as 91,000). A/B on 231 filings: 36 change, 717 cells, 0 gain a value.
- **mn21**: the machine's 주당 skip reads the innermost label (source: last text cell before the first amount; DB: last `>` segment). Before, the new 2026 note layout (outer stub `기본 및 희석 주당이익 ...` on every row) emptied the source table. 150 random filings: identical findings old vs new. Retriage closed 1,300 (extra_table 66 -> 13, missing_row 58,788 -> 57,526).
- **Reloaded**: 31 extra_table filings (note only). **NOT started**: R300+R302 backfill, union list `scratchpad/union_filings.txt` = 36,766 filings (share list 30,510 + 6,256 with unit-marker labels), about 12 h; Telegram notice sent 2026-11-04 14:20, waits for approval.
- Open note issues now: missing_row 57,526 · extra_row 1,129 (other 1,058: two-group ~730 machine limit, the rest row-specific, e.g. 대원전선 20160504000303 table 41, OCI홀딩스 20230811001879 table 113) · extra_table 13 · unit_scale 6 · value_mismatch 5.

## 2026-11-05 - R300 + R302 backfill done

- User approved ("재적재 36766개 필링 진행해"). Note-only reload of 36,766 filings of 2015+ (share list 30,510 + 6,256 with unit-marker labels): 36,540 done, 226 failed (all "XML 원문 없음": no source file, the old note rows stay). 8 shards took about 6 h (`scratchpad/pipe_union.sh`: reload, recheck, run, register-all, retriage). The reload also refreshed older note rows of those filings (R294-R297, R299, R273-c).
- Machine run after the reload (mn21): clean 98.8% on the first shard (3,922 of 3,969). register-all added a few dozen new issues (extra_row +44, value_mismatch +1) - not yet looked at cell by cell.
- retriage closed 5,833. Open note issues: missing_row 51,996 (was 57,526) · extra_row 1,173 · extra_table 13 · unit_scale 6 · value_mismatch 6.

## 2026-11-05 afternoon - R303, mn22, mn23 (look at the 61 issues the post-reload run registered)

- **R303**: a `가중치` column is no amount column; R158 had turned a printed `1.00` into `10000000` (린드먼아시아 20190813000234, R0-2 violation). 9 filings held such a value_raw, reloaded.
- **mn22**: the source label is the first text cell that is not readable as an amount (`1,500,000 USD 4,000,000` was taken as the label when the other cells were rowspan-covered; 체리부로 and 이천/진천물류센터 rows).
- **mn23**: a `>` inside `<...>` is no label separator (dividend rows `배당금 <주당 배당금(...)>`; mn21 had made the DB side skip differently from the source side).
- retriage closed 57 + 16. Left as machine limits (about 12): rate cells with a tail (`1,161.20원/1USD`, 경남은행 TRF 20200814001310), conversion-price sentences (`전환권에 관한 사항` 2,993, 20190814002252).
- Open note issues: see the counts printed at the end of this session's report.

## 2026-11-06 - mn24: rows with an empty label cell are not loaded (user decision)
- Decision (user, 2026-11-06): loan totals are enough, per-bank detail rows under a blank '구분' cell need not be loaded (대원전선 20160504000303 table 41). The loader already drops them; no R-rule change, no reload.
- Machine mn24 (`_MN24_BLANK_LABEL`): a source row whose first cell is empty but which has other cells is not a source amount row (alt pass only). A/B on 2 x 150 filings with open issues: differing tables 265 -> 191 and 259 -> 197, no table got worse.
- `scope retriage` follows; remaining `unlabeled` issues after it are the non-blank-label cases (date/currency/remark labels).

## 2026-11-07/08 - stale-DB reload of 2,213 filings, mn25
- Stale-DB scan of the filings with open note issues (current parser vs note_lines, `stale5.py`): 2,213 of 8,768 differed (old unit plans, e.g. R299 `18,245원` stored with adecimal -3). Note-only reload: 2,210 done, 3 without source XML. `scope retriage` closed 9,434: missing_row 32,183 -> 22,568.
- Machine mn25 (`_MN25_AMOUNT_IN_LABEL`): a source amount that the loader stored inside the row label ('15,400,000>2019.01.01~ ...', share count in front of a period, undeclared unit) is no missing_cell. A/B on 150 filings: 14 findings fewer, none added.
- mn26: the mn25 label check now accepts the amount anywhere in the DB label text (e.g. a first all-amount row read as header text: 벽산 20170331003108 table 7, '당기순이익  294,713,122'); A/B on 150 filings: 33 findings fewer, none added. mn25 retriage had closed 1,409 (missing_row 22,568 -> 21,2xx); the mn26 retriage follows.
- mn27: the label check also reads `col_label` (a value cell read as a column header lands there: 미래에셋벤처투자 20190828000709 '1주의 금액 | 1,000원', 벽산 20170331003108 table 7). A/B on 150 filings: 284 findings fewer, none added. mn26 retriage had closed 2,656 (missing_row 21,2xx -> 18,703: other 12,868, shares_or_price 3,456, unlabeled 1,343, total 963, currency 73).
- 2026-11-09/10: mn27 retriage closed 10,318 (missing_row 18,703 -> 8,385: other 5,912, total 919, unlabeled 906, shares_or_price 575, currency 73). A strict stale scan (value_won AND value_raw) over the 3,484 filings with open issues found only 70 differing; reloaded 67 (3 without source XML), retriage closed 0. A first try at mn28 (source side: do not read '227,478&cr;(816)') was reverted: it made extra_cell appear where the loader keeps the line break in value_raw.
- mn28 (final): the DB side reads a raw like '227,478(816)' (line break joined, value NULL by the R1 guard) by its first amount, like the same cell with the break kept. 대상 20151113000949: 8 -> 4 differing tables. A/B on 150 filings: differing tables 275 -> 267, none worse. Left: stacked variants like '(21,676)&cr;305'.
