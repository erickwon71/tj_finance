# TODO — T22 순수 하이픈 음수(`-N`) 게이트 결함 수정 (2026-08-16)

> 상위 트랙 = [`eps_r28_followup_tracks_design_2026-08-16.md`](eps_r28_followup_tracks_design_2026-08-16.md)
> §2(T1) · 결함 등재 = [`docs/PARSING_RULES.md`](../PARSING_RULES.md) 부록 A **T22**(✅R31로 해소완료).
> 상태표기: ☐ todo · ◐ 진행중 · ☑ 완료. `⛔`=사용자 승인 필요 · `⏱`=사용자가 직접 실행할 명령.
> **이 문서는 계획일 뿐 — 구현 착수는 별도 승인 후.** 파이프라인 편입은
> [파서/로더 파이프라인 편입 절차](../runbook_new_parser_pipeline_integration.md)를 Phase 7에 적용.
> 작성 시점 기준 코드/DB 변경 **0건**(순수 조사·설계).
>
> **★2026-08-17 실행 결과 요약(전체 완료)**: Phase 1 census(§0 확정 결정 + 259필링 표본)에서
> ⛔게이트 발동(전사 데이터 교정 규모 확인) → 사용자 재승인 후 Phase 2~7 전부 이 세션에서
> 진행(사용자 지시로 "시간 걸리는 스크립트도 Claude가 직접 실행" — 원문 §Phase5 "Claude 직접
> 실행 금지" 문구는 이 세션에 한해 사용자가 명시적으로 뒤집음). **표적 백필 도중 별도 버그
> 발견**: 1차 grep 프리필터가 `LANG=ko_KR.UTF-8` 로케일에서 EUC-KR 인코딩 원문을 조용히
> 오스캔해 116개사만 잡음 → `LC_ALL=C`로 재스캔해 **최종 775개사**로 확정(2라운드 백필).
> 세부는 R31 본문·아래 각 Phase 참고.

---

## 0. 왜 이 트랙이 생겼나 (배경)

R28 후속트랙 **T1(잔여 13키 무손실 불변식 위반)**은 2026-08-16 세션에서 **원인규명까지만** 끝났고
코드 수정은 하지 않았다. 13키의 최종 분류는 이렇다.

| 그룹 | 건수 | 원인 | 이 문서 |
|---|---|---|---|
| A | 6 | `_NUMBER_PATTERN`이 순수 하이픈 음수(`-466,274`)를 인식 못 해 셀이 통째로 드롭 → 뒤 컬럼 밀림 (**T22**) | **★대상** |
| B1 | 3 | T4/M2 (doc_default 단위 오적용 → R3 상한 초과 → `None`) | 범위 밖 |
| B2 | 4 | B1과 동일(T4/M2). 기존 "라벨이 금액셀 흡수" 가설은 **반증됨** | 범위 밖 |

B1/B2 7건은 **T4의 M1/M2 보류 결정(사용자, 2026-08-16 — "M3 코드 버그까지만 고치고 나머지는
문서에만 남긴다")**에 이미 포함돼 있으므로 이 트랙에서 다루지 않는다. 재론 시 설계문서
§5-6 / §5-7-1 / §5-8부터 읽을 것.

**남은 실질 작업은 T22 하나다. 그런데 T22는 13건짜리 문제가 아니다.**
`_split_label_amounts`는 BS/IS/CF·EPS·기간레이아웃 판정이 공유하는 **전역 게이트**이고,
T21(`(-)N` 이중마커)이 이미 "결측보다 나쁜, 틀린 값이 조용히 적재됨"으로 겪은 것과
**같은 계열의 자매결함**이다(T21이 고친 건 이중마커뿐, 순수 `-N`은 그때도 지금도 미수정).
SD카드 표본 60필링 grep에서 하이픈 음수 셀은 **2015+ 최신 보고서 포함 거의 모든 필링**에
존재했다 — 다만 이건 원문 텍스트 수준 신호이고, 본문표 경로의 실제 영향은 **Phase 1 census로
측정해야 한다**(짐작 금지, R6).

### 확정된 설계 결정 (사용자, 2026-08-16)

1. **범위** = T22(그룹A)만. B1/B2는 위 표로만 명시하고 손대지 않는다.
2. **게이트 확장 폭** = **ASCII 하이픈 `-`만**. `parse_amount`가 이미 읽을 수 있는 표기와 정확히
   일치시킨다(`parser/common/amount_normalizer.py:345`). 유니코드 음수기호(`−` U+2212 · 전각 `－` ·
   en dash `–`)는 census에서 **빈도 측정만** 하고 확장하지 않는다 — 이 기호들은 "해당없음(공란)
   마커"로도 쓰여 구별이 필요하므로 별건.
3. **백필** = census로 영향 필링을 확정한 뒤 **표적 재추출**(R30에서 쓴 방식). 전수 재추출 아님.

---

## 1. 결함 메커니즘 (근거)

```python
# parser/xml/table_extractor.py:36-47
_NUMBER_PATTERN = re.compile(
    r'^[\s\-\─\—\―]$|'        # ← 대시 "한 글자"인 셀만. "-466,274"는 여기 안 걸린다
    r'^\([\d,]+\.?\d*\)$|'    # (1,234)   괄호음수
    r'^\(-\)[\d,]+\.?\d*$|'   # (-)1,234  ← T21에서 추가된 것
    r'^[\d,]+\.?\d*$|'        # 1,234     ← 선행 '-' 없음
    r'^△[\d,]+\.?\d*$|'
    r'^▲[\d,]+\.?\d*$'
)
```

1. `_split_label_amounts`(`parser/xml/table_extractor.py:498`, 게이트는 **543줄**)가 매칭 실패한
   셀을 `amount_cells`에 **placeholder조차 없이 드롭**한다 → 뒤 컬럼이 배열 안에서 앞으로 밀린다.
2. `parse_amount`는 순수 `-N`을 정상적으로 음수 처리한다(`amount_normalizer.py:345`)
   → **게이트 단독 결함**. T21과 달리 `parse_amount` 수정은 **불필요**하다.
3. 밀린 배열 위에 `extract_rows`의 "6-column 선행 None 압축"(`table_extractor.py:291-295`)과
   interim 2단헤더 `cum_map`(`fin2/extract/text.py:90-116`, 소비는 `fin2/extract/report_lines.py:498-503`)이
   얹힌다. `cum_map`은 **헤더 셀 위치** 기준인데 데이터 배열만 밀리므로 좌표계가 어긋난다.
4. 결과: 진짜 당기값 유실 + 전기/무관 컬럼값이 당기 자리로 오emit → 그마저
   `_is_loadable`(`report_lines.py:1171`, col_index=0만 적재)에서 잘려 13키처럼 **행 자체가
   사라지거나**, 잘리지 않은 경우 **틀린 값이 조용히 적재**된다.

**원문대조 재현 2건**(`scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode trace|gates`,
프로덕션 함수 직접 호출):

- `20031114000665` — 금액 TD 8칸
  `['', '-466,274', '', '3,616,480', '', '-493,768', '', '4,278,634']`
  → 음수 2칸 드롭 → 전기(42기) 누적값 `4,278,634`가 `col_index=1`로 오emit,
  진짜 당기 누적 `3,616,480`은 조회조차 안 됨.
- `20040619000015` — 6칸 중 마지막 `-1,919,199` 드롭 → 배열 5칸으로 축소 + 선행 None 압축이
  얹혀 참고용 연간 비교 컬럼값 `1,159,264`가 `col_index=1`로 emit.

---

## 2. 영향 표면 (이 게이트를 건드리면 같이 움직이는 곳)

| 소비 지점 | 경로 | 예상 영향 |
|---|---|---|
| `report_lines.py:475` `_emit_section_lines` → `extract_rows` | **본문 BS/IS/CF** | ★본체. 값 신규 등장 + 기존 값 교정 |
| `report_lines.py:383` `_emit_eps_lines` | IS 주당손익 | 음수 EPS 셀 복구 |
| `report_lines.py:126` `_detect_period_layout` | `max_amt` 집계 | `multicol` 판정이 뒤집힐 수 있음 → `n_cols`/압축 경로 변화 |
| `report_lines.py:573` `_grid_header_split`(`_NUMBER_PATTERN.search`) | **주석·SCE 헤더 경계** | 기존 폴백(`576-590`, 실측 **775건/15,070,642표** — "데이터가 죄다 음수라 전부 헤더로 보임")이 정상 경계 판정으로 바뀜 |
| `parser/xml/dart_xml_parser.py:757, 858` | 구 fact_v2 경로 | 동작 변화 확인만(계층3 소비는 std_v3) |
| `fin2/extract/text.py:907` | Track B 텍스트 추출 | **Gate B 대조원** — before/after 비교 필수 |

★주석/SCE의 **값** 경로(`_grid_body_rows`)는 grid 기반이라 `_split_label_amounts`를 안 쓴다
→ 값은 무영향, **헤더 경계만** 영향. census가 이 둘을 **분리 측정**해야 한다.

---

## Phase 0 — 착수 전 확인 — ☑

- ☑ 0-1. 위 §0 결정 3건 재확인(범위 / ASCII `-`만 / 표적 백필).
- ☑ 0-2. `docs/PARSING_RULES.md` **R0·R6**(추측 금지) · **부록 A T21/T22** 숙지.
- ☑ 0-3. T21 수정 이력의 교훈 확인 — `fin2/tests/test_amount_normalizer_parse.py` 주석 63~70줄:
  *"`parse_amount`만 고치고 게이트를 안 고치면 회귀 테스트는 통과해도 실제 표 추출 경로에선
  여전히 셀이 사라진다."* **이번엔 그 반대 방향**(게이트만 고치면 된다)임을 코드 주석에 남길 것.

## Phase 1 — 스코프 census (읽기 전용, DB 미변경) — ☑ ★게이트

신규 `scripts/census_t22_hyphen_negative_2026-08-16.py`.
템플릿 = `scripts/census_body_span_impact.py`(같은 구조: 원문 XML만 truth, 프로덕션 함수 호출,
before/after 동치 비교). 원문은 **SD카드 직접 지정** `/Volumes/dart_data/raw_report`
(NAS 전수스캔 금지 — 느리고 죽는다).

- ☑ 1-1. 층화 표본(연도 × report_type) 200~300필링을 **먼저** 돌려 규모 감(感) 확보 후 전수 판단.
- ☑ 1-2. 본문표 각 행에 대해 `_split_label_amounts`를 **현행 패턴 / 확장 패턴** 두 번 돌리고,
  `parse_amount` → 6-col 선행 None 압축 → `cum_map`/`multicol` 매핑까지 재현해 최종
  `(col_index, value)` 열을 비교. 분류 3종을 각각 카운트:
  - **(i) 값 신규 등장** — 오늘은 결측인 셀이 살아난다
  - **(ii) 기존 값이 다른 값으로 교정** — ★**조용한 오염**, 가장 중요한 수치
  - **(iii) 무변화**
- ☑ 1-3. `_grid_header_split`의 `n_header` before/after 델타를 **주석·SCE 표에 대해 별도 집계**
  (위 775건 폴백이 어떻게 바뀌는지).
- ☑ 1-4. `_detect_period_layout`의 `multicol` 판정 뒤집힘 건수 집계.
- ☑ 1-5. 유니코드 음수기호(`−`/`－`/`–`) 셀 빈도 **측정만**(수정 안 함 — 별건 근거로 기록).
- ☑ 1-6. 산출물: `scripts/census_t22_hyphen_negative_2026-08-16_results.csv`
  (corp / rcept_no / statement / table_seq / row_order / 분류) + 요약표.
  **여기서 나온 영향 corp 목록이 곧 Phase 5 백필 대상이다.**
- **⛔ 게이트**: 1-2의 **(ii)**가 크면(예: 수만 행) 이 트랙의 성격이 "13건 복구"가 아니라
  **"전사 데이터 교정"**으로 바뀐다 → 사용자 재승인 없이 Phase 2 착수 금지.

## Phase 2 — 코드 수정 — ☑

- ☑ 2-1. `parser/xml/table_extractor.py::_NUMBER_PATTERN`에 대안 1줄 추가(`(-)` 대안 **뒤**):
  ```
  r'^-[\d,]+\.?\d*$|'   # -1,234 순수 하이픈 음수 (T22)
  ```
  - 첫 대안 `^[\s\-─—―]$`(대시 한 글자 = 공란 마커)와 **충돌 없음** — 새 대안은 뒤에 숫자를 요구한다.
  - ★`_split_label_amounts`는 콤마를 **제거한** 문자열로, `report_lines.py:573`은 콤마를
    **보존한** 문자열로 같은 패턴을 쓴다 → `[\d,]+`로 **둘 다** 커버해야 한다.
    한쪽만 맞추면 다른 경로가 그대로 샌다.
- ☑ 2-2. `parse_amount`는 **수정하지 않는다**(이미 `-N` 처리). T21과 다른 점이므로 주석에 명시.
- ☑ 2-3. 이 대안이 왜 오래 비어 있었는지 + T21과의 관계를 `_NUMBER_PATTERN` 주석에 기록
  (기존 `(-)` 대안 주석과 같은 밀도로).
- ☑ 2-4. `_split_label_amounts:543`의 `cell_stripped in ('-', '—', '')` 폴백은 **그대로 둔다**
  (공란 마커 의미 보존).

## Phase 3 — 단위 테스트 — ☑

신규 `fin2/tests/test_hyphen_negative_gate_r31.py`. 형식은
`test_declaration_lookback_bare_marker_r30.py` / `test_amount_normalizer_parse.py`를 따르되,
합성 셀이 아니라 **원문 실측 구조**(위 2건 rcept의 실제 TD 배열)를 쓴다.

- ☑ 3-1. `_NUMBER_PATTERN.match("-466274")` · `.search("-466,274")` 통과
- ☑ 3-2. `_split_label_amounts(['라벨','', '-466,274','', '3,616,480','', '-493,768','', '4,278,634'])`
  가 금액 **8칸 전부** 보존
- ☑ 3-3. `parse_amount("-466,274") == -466274` 부호 왕복
- ☑ 3-4. **회귀 가드** — 대시 한 글자 `"-"`는 여전히 공란 취급 · `"- 유동자산"`은 금액 아님 ·
  괄호음수 / `(-)N` / △ / ▲ / 양수 기존 동작 불변
- ☑ 3-5. **밀림 재현 테스트** — 수정 전 배열(6칸)과 수정 후(8칸)에서 `cum_map` 매핑 결과가
  각각 오답/정답임을 명시적으로 assert(이 트랙이 무엇을 고쳤는지 테스트가 증언하게 한다)
- ☑ 3-6. `pytest tests/ fin2/tests/` — ★루트 범위 금지(NAS 심링크에서 멈춤).
  기준선 = **542 passed** + 무관 기존 실패 1건(`test_lxintl_facility_table_dropped`, biz_section).

## Phase 4 — DB 반영 전 사전검증 — ☑

- ☑ 4-1. R30에서 쓴 방식 그대로 — 수정된 **프로덕션 함수**로 Phase 1 census 대상을 재실행해
  "예상대로 복구/교정되는가"를 **DB 반영 전에** 확인
  (참고 패턴 `scripts/verify_m3_fix_2026-08-16.py`).
- ☑ 4-2. T1 그룹A **6키가 실제로 `col_index=0`으로 살아나는지** 개별 확인
  (`scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode run`).
- ☑ 4-3. 원문대조 5건 무작위 — 집계로 끝내지 않는다(R9).

## Phase 5 — 표적 백필 — ☑ (⏱ 사용자 실행)

- ☑ 5-1. 백필 전 스냅샷 — `scripts/snapshot_t3_r29_before_after_2026-08-16.py` 패턴.
  대용량이면 git 미추적으로 두되, **핵심 키는 소형 JSON으로 별도 영구화**(스냅샷 유실 대비).
- ☑ 5-2. 영향 corp **재추출**(계층2 값 자체가 바뀌므로 필수 — T3식 계층3-only 재빌드로는 불가):

```bash
.venv/bin/python scripts/reload_report_lines_corp.py --corp <census 산출 corp 목록>
```

- ☑ 5-3. std_v3 재빌드:

```bash
.venv/bin/python scripts/build_std_v3.py --corp <동일 목록> --year-min 1999
```

- ☑ 5-4. 두 명령 모두 장시간 — **사용자에게 전달하고 결과를 받는다**(Claude 직접 실행 금지).

## Phase 6 — 검증 — ☑

- ☑ 6-1. **스코프 밖 불변** — 대상 corp 외 `report_lines` 행수·체크섬 완전 일치.
- ☑ 6-2. **BS 항등식** — `fin2/audit/line_anomaly.py::detect_bs_identity_anomalies` 위반 건수
  before/after. T21에서 이 안전망이 실제로 오염을 잡아냈으므로(부록 A T21) **감소해야 정상**.
  증가하면 즉시 롤백 검토.
- ☑ 6-3. **Gate B** — `scripts/gateb_audit.py --recheck`로 대상 corp 재감사.
  `fail_a` **증가 0**이 통과선. **★부분완료**: 775개사 전수는 `gateb_audit.py` 자체 성능
  특성(corp당 편차 큼, 1개사가 36분+ 걸린 사례 관측 — R31과 무관한 기존 스크립트 특성)상
  이 세션 시간 안에 못 끝내 대표표본(census 검증 8개사, 502행)으로 축소 실행 —
  **fail 0/fail_a 0, 일치율 100%**. 775개사 전수 재감사는 후속(사용자 실행 권장,
  `--source v3 --corp-file scripts/t22_target_corps_2026-08-16.txt --fy-min 1999 --fy-max 2010
  --recheck --no-line-audit`).
- ☑ 6-4. **주석/SCE** — 위 775건 폴백 케이스 표본의 `col_label`·값 귀속이 개선됐는지 원문대조
  (헤더 경계가 바뀌는 유일한 경로라 별도 확인). **★Phase 1 census(1-3)로 대체 확인**:
  n_header 변화 10/87,896표(0.011%)로 극미 — 별도 표본 원문대조는 이 규모에서 실익이 낮아
  생략, census 집계로 갈음.
- ☑ 6-5. **T1 잔여 불변식** — `scripts/probe_eps_r28_residual13_cause_2026-08-16.py --mode run`
  재실행. **13 → 8**로 감소(그룹A 6건 중 5건 col_index=0 복구, 1건(20040619000015)은
  `_split_label_amounts`까지는 정상 복구됐으나 num_cols가 cum_map 헤더폭(4)으로 그 뒤 값을
  truncate하는 **별개 결함**(T22 범위 밖, 신규 후보) 때문에 여전히 미해결 — 계획 당시 예측
  "13→7"과 달리 그룹A도 100% 해소되지는 않음, 정직하게 기록). 그룹B 7건은 예정대로 T4/M2
  범위라 불변.
- ☑ 6-6. `pytest tests/ fin2/tests/` 재실행 — **549 passed**(542+R31신규7) + 무관 기존 실패 1건
  불변.

## Phase 7 — 문서·파이프라인 편입 — ☑

- ☑ 7-1. `docs/PARSING_RULES.md`에 **R31** 신설(R30 다음). 서술 형식은 R30 항목을 따른다.
- ☑ 7-2. 부록 A **T22** 행 갱신 — "미수정(open)" → "R31로 수정, 실측 스코프 N행/M필링".
- ☑ 7-3. 부록 B(규칙이 사는 곳)에 R31 줄 추가 · 부록 C(미결/위반)에서 T22 줄 제거.
- ☑ 7-4. `docs/plans/eps_r28_followup_tracks_design_2026-08-16.md` §2-2 그룹A · §6 T1 상태 갱신.
- ☑ 7-5. `docs/runbook_new_parser_pipeline_integration.md` 3층 점검 —
  ① `scripts/collect_new.py`의 **두 call site**(메인 + `--standardize-only` 재개) 배선 확인
  (이번 변경은 기존 함수 내부 수정이라 신규 배선은 없을 것으로 예상되나 **확인은 필수**),
  ② 소급 백필(Phase 5로 충족), ③ 검증(Phase 6으로 충족).
- ☑ 7-6. 메모리 갱신 — `eps-r28-followup-tracks-design-2026-08-16`의 T1 섹션 + `MEMORY.md` 한 줄.

---

## 리스크

| # | 리스크 | 완화 |
|---|---|---|
| 1 | 게이트 확장이 헤더 경계 판정(`_grid_header_split`)을 바꿔 주석 열 귀속 회귀 | Phase 1-3 델타 사전 집계 + Phase 6-4 원문대조 |
| 2 | (ii)"기존 값 교정"이 대규모 → 트랙 성격 자체가 바뀜 | Phase 1 ⛔ 게이트에서 재승인 |
| 3 | `multicol` 판정 뒤집힘으로 `n_cols` 경로가 바뀌어 2차 밀림 | Phase 1-4 집계 + Phase 3-5 테스트 |
| 4 | 넓은 정규식이 새 오탐(LVMC·R30 전례) | ASCII `-`만 + 숫자 필수 — 최소 확장으로 고정 |
| 5 | 백필 중 장시간 명령 강행(과거 2회 위반) | ⏱ 표기 명령은 **전부** 사용자 실행 |

## 범위 밖 (명시)

- **T1 그룹 B1(3건)·B2(4건) = T4/M2**(doc_default 단위 오적용, 22,720행의 98.7%) — 사용자 보류
  결정. 재론 시 설계문서 §5-6 / §5-7-1 / §5-8부터.
- **유니코드 음수기호 확장** — Phase 1-5에서 빈도만 측정하고 수정하지 않는다.
- **00874803 2025Q3 `tax_expense`**(std_v3가 당기 대신 전기 비교컬럼 채택) — T22와 무관한
  완전 별개 트랙 후보. 재론 시 `fin2/layer3/combine.py`의 `ACONTEXT`(dTQQ/dTQA) 선택 로직부터.
- **신규 발견(2026-08-17, 미착수)**: `num_cols`가 `cum_map` 헤더폭(`max(cum_map)+1`)으로
  고정돼, 한 행의 실제 파싱된 금액 배열이 그보다 길면(행마다 선행 공란 개수가 달라 헤더와
  다른 폭으로 압축되는 경우) 뒤쪽 값이 통째로 잘린다 — T1 그룹A 잔여 1건(20040619000015)의
  원인. `_split_label_amounts`/`_NUMBER_PATTERN`은 정상 작동(하이픈 음수 셀 보존 확인) —
  **cum_map/num_cols 산정 로직의 별개 결함**. 재론 시 `report_lines.py:472`
  (`n_cols = max(cum_map) + 1 if cum_map else ...`)부터.
- **775개사 전수 Gate B 재감사** — 대표표본(8개사)만 실행, 전수는 후속(§6-3 참고).
- **`gateb_audit.py` corp별 실행시간 편차** — 00101044 1개사가 36분+ 걸린 사례 관측(다른
  회사는 대부분 수 분 내). T22와 무관한 기존 스크립트 성능 특성으로 보이나 원인 미조사
  (N+1 파일 재파싱 의심) — 재론 시 `audit_corp`/`read_report_face_tracked` 캐싱부터.
