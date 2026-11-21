# 단위 미선언 섹션의 증명 확장 (R169-c) 계획 — B-1-f (2026-11-21)

상태: **실행 완료(2026-11-21, 사용자 지시 "단계별로 이어서 진행")** — 결과는 `docs/rules/10_layer2_parse.md` R169-c. 단계 1·2·3 수행, 별도 BS std NULL 은 R63 가드 문제로 TODO B-1-g.
출처: `docs/qa/todo_2026-11-18.md` B-1-f, 오늘이엔엠 00623184 2015Q1 `20150515001311`.

## 1. 결론 요약

| | 내용 | 판정 |
|---|---|---|
| ① 별도 BS·IS·CF·SCE 4섹션 | 표에 단위 선언이 없어 `단위 미선언 → 스킵` (`report_lines.py:1357`, SCE `:2429`) | **진짜 결함 — 이 계획의 대상** |
| ② 연결 IS | 계층2 에 행이 없음 | **결함 아님(2026-11-21 정정)**. Q1 누적 열이 통째로 공란인 서식이라 R116/R154 대로 계층2 는 인쇄값(공란)만 두고, 3개월 값은 계층3 `layer3_cell_corrections` 의 `R154_q1_cum_fill`(연결 IS 11행)로 채운다. 이 rcept 는 2026-10-27 에 `_Q1_CUM_BLANK_USE_3M_RCEPTS` 에 이미 등재돼 있고 std 연결 2015Q1 매출 1,417,039,419 로 들어와 있다. 앞서 "연결 IS 누락"이라 한 것은 계층2 만 보고 한 오판. |

## 2. 조사로 확인한 것

- 재현: `extract_report_lines` 를 이 필링에 그대로 돌리면 연결 BS 25·CF 28·SCE 56 만 나오고 별도 4섹션은 로그만 남기고 사라진다(DB 쓰기 없음).
- **이미 있는 도구가 증명까지 해 낸다**: `scripts/unit_self_contradiction_scan.py --rcepts 20150515001311`(`--apply` 없이) 결과 4섹션 전부 `confirmed:1`.
  BS_S hits(1)=23 · CF_S 3 · SCE_S 21 · IS_S 는 타 필링 증거 0 이지만 같은 문서의 확정 섹션 금액과 5건 일치(`evidence: same_document`), 다른 배수 hits 는 전부 0.
  (`scan_rcept` 의 의심 조건 중 `vanished and not decl` — "선언 단위에서 섹션이 통째로 사라짐" — 이 이 경우를 이미 받는다.)
- 빠진 것은 **지명(nomination)** 이다. `suspect_rcepts()` 는 `report_lines` 에 이미 적재된 행(1e15 이상·비율 이상)에서 의심 필링을 고르는데, 단위 미선언으로 스킵된 섹션은 **행이 없어서** 영원히 지명되지 않는다. 그래서 필링을 직접 지정해야만 돈다.
- 적용 경로: `_unit_override()` 는 `if unit is None` 폴백보다 **앞**에서 불린다(`report_lines.py:1336`). 선언이 없는 섹션에도 JSON 등재만 하면 `proved_unit` 으로 읽힌다. SCE 방출기도 같은 override 를 읽는다(R169).

## 3. 계획

### 단계 1 — 필링 1건 먼저 (이 건 해결)
1. `scripts/unit_self_contradiction_scan.py --rcepts 20150515001311 --apply` → `fin2/extract/data/unit_self_contradiction_overrides.json` 에 4섹션 등재.
2. 이 필링 재적재(`vq.py batch add-targets` + `batch reload`, 또는 `ops._reload_rcept`) → 별도 BS/IS/CF/SCE 행 생김, `unit_source='proved_unit'`.
3. 00623184 계층3 재빌드 → `std_financials_v3` 2015 Q1 별도 행 생성 확인. **재빌드 뒤 `calendarize_corps.py` 필수**(std_v3 를 건드렸으므로).
4. 검증: 별도 BS 자산총계 항등식·18기 열 = FY2014 별도 값 일치 / 같은 필링 연결 값 무변화 / Gate B 영향 없음.

### 단계 2 — 같은 부류 전수 지명 (규칙 R169-c)
1. 지명 쿼리(측정 완료, 20초): `report_tables` 로 "같은 회사·같은 회계연도의 다른 최종 필링엔 있는 (basis, statement) 섹션이 이 필링엔 없고, 이 필링엔 다른 섹션이 있다" 를 찾는다 → **6,613 섹션 / 1,667 필링**(FY2015+). 정당한 부재(분기에 연결 없음 등)도 섞이지만 **지명은 과대해도 안전하다** — 확정은 정확 일치 증거가 정한다(hits≥3, 다른 k 는 ≤1, 10배 차).
2. `unit_self_contradiction.py` 에 `undeclared_gap_suspects()` 추가 → `suspect_rcepts()` 에 합류(또는 `--include-undeclared` 옵션). 확정 로직·JSON 형식·`proved_unit` 은 그대로.
3. 1,667필링 **dry-run**(`--apply` 없이, 필링당 추출 2회) → 결과를 사용자에게 보여 주고 `confirmed` 건만 `--apply`. `unconfirmed` 는 손대지 않는다(R6).
4. 확정분 재적재 + 해당 회사 계층3 재빌드 + calendarize. 일반 연결 8개사 13슬롯(`00260745·00486097·00657002·00683007·00791209·01764099` 등)이 여기서 분류된다.
5. 데일리: `scripts/collect_new.py::_report_unit_self_contradiction()` 은 **탐지·보고만**(데이터 파일을 쓰지 않음, R169 원칙) — 같은 지명 함수를 넣어 새 미선언 스킵 필링이 보고되게 한다. **두 call site(메인 + `--standardize-only`) 여부는 이 함수가 어느 쪽에서 불리는지 먼저 확인**(런북 체크리스트 ①).

### 단계 3 — 문서·테스트
- 규칙: `docs/rules/10_layer2_parse.md` 의 R169 아래에 **R169-c**(머리에 `적용 계층: 2`) → `docs/PARSING_RULES.md` 색인 한 줄 → 코드 링크. main 에서만 수정, 다른 워크트리는 받기만.
- 테스트: ① 합성 표(단위 선언 없음 + 값이 다른 필링에 정확 일치) 에서 scan 이 `confirmed:1` ② 증거 없으면 `unconfirmed` 이고 override 없음 ③ 지명 쿼리가 선언 없는 부재 섹션을 잡고 정당한 부재도 확정은 안 함 ④ 이 필링 회귀(`unit_source='proved_unit'`, 별도 4섹션 존재).

## 4. 위험·주의

- R0-2: 계층2 는 인쇄된 값만 — 여기서 하는 일은 **읽는 배수 결정**이지 값 보정이 아니다(R169 와 같은 계열, 숫자는 그대로).
- 엘브이엠씨 사고(다른 표의 단위를 주워 쓰기) 와 구별: 여기서는 **남의 선언을 빌리지 않고** 타 필링/같은 문서의 정확 일치 금액이 k 를 증명할 때만 쓴다.
- 지명 과대 → 실행 시간만 늘 뿐 데이터는 안 바뀐다. 반대로 확정 기준은 완화하지 않는다.
- 재적재는 필링 단위, 계층3 은 회사 단위. 전수(1,667필링)를 한 번에 재적재하지 말고 `confirmed` 만.
- Pro 요금제: 탐색·집계는 스크립트로, 한 세션에 한 배치. 야간 자율 실행 대상 아님(사용자 확인 후).

## 5. 사용자 확인이 필요한 결정

1. 단계 1 만 먼저 할지, 단계 2 까지 한 번에 할지.
2. 단계 2 의 `confirmed` 적용 전에 dry-run 결과를 보고 승인받을지(권장).
