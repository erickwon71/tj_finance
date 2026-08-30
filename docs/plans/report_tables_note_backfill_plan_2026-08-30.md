# report_tables(주석) 소급 백필 — 설계 문서 (2026-08-30)

> **미구현 — 승인 대기.** 이 문서는 설계까지만 담는다. 구현은 사용자가 별도로 지시한 뒤
> 착수한다([[feedback-plan-then-wait]]).

---

## 0. 배경 — 왜 이 문서가 따로 있는가

`valuation_daily_v3_migration_plan_2026-08-30.md` §Phase 0-1을 실행하던 중(v2 vs v3
`ebitda` 표본 대조), v3의 D&A/EBITDA가 FY2024+ 표본의 상당수에서 **완전히 NULL**임을
발견했다. 원인을 추적한 결과 `valuation_daily`나 std_v2 잔여 쓰기 문제보다 훨씬 근본적인
계층3 D&A 파이프라인 전체의 결함(정확히는 **결함이 아니라 백필 누락**)으로 밝혀져, 별도
문서로 분리한다. `std_v2_retirement_port_to_v3_2026-08-22.md` §3.10에도 정정 사항을
교차기록해뒀다.

**한 줄 요약**: `fin2/layer3/note_da.py`(std_v3의 주석 기반 D&A 추출)가 의존하는
`report_tables.section_path`(주석 표 제목)가, **note_lines 전체 corpus 대비 극히 일부만
채워져 있다** — 코드 버그가 아니라 2026-08-08 이후 22일간 소급 백필이 재실행되지 않은
운영 공백이다.

---

## 1. 실측 근거 (2026-08-30, 로그·DB 직접 대조로 확인)

### 1-1. `note_da.py`가 정확히 무엇에 의존하는가

`fin2/layer3/note_da.py::_ROWS_SQL`:

```sql
SELECT rt.section_path, n.table_seq, n.row_order, n.col_index, n.col_label,
       n.label_raw, n.value_won
FROM note_lines n
LEFT JOIN report_tables rt
       ON rt.rcept_no = n.rcept_no AND rt.statement = 'note'
      AND rt.basis = n.basis AND rt.table_seq = n.table_seq
WHERE n.rcept_no = :rcept AND n.basis = :basis AND n.statement = 'note'
  AND n.value_won IS NOT NULL AND n.header_hint IS NULL
```

`section_path`(주석 표 제목, 예: "비용의 성격별 분류")가 있어야 `note_topics.map_topic()`이
주제를 판정하고, 그래야 `DA_SOURCE_BROAD`/`DA_SOURCE_COMPONENT`에 태울 수 있다.
`section_path`는 **F3 리팩터(2026-07-31)로 `note_lines`에서 분리되어 `report_tables`로
옮겨졌다**(주석 코멘트: "행마다 반복하던 33B×2.2억행(6.4GB)을 없앤 것").

### 1-2. 원문 데이터 자체는 멀쩡하다 — 표본 직접 확인

`00162586`(FY2025 consolidated, rcept `20260318001637`) 표본:
- `note_lines`에 "감가상각비"·"무형자산상각비"가 "기능별 항목 합계" col_label로 **정확한
  값**으로 존재(직접 조회 확인, 무형자산상각비=374,137,000 — v2가 patch한 값과 정확히 일치).
- 그런데 `std_financials_v3`의 이 corp/기간 행은 depreciation/amortization/da_total/ebitda
  **전부 NULL**.
- `report_tables WHERE rcept_no='20260318001637' AND statement='note'` → **0행**. 조인이
  아예 안 걸린다 — 원인 확정.

### 1-3. 규모 — `report_tables`의 `note` 통계는 딱 하루치, 그것도 일부뿐

`report_tables`를 `parsed_at` 날짜 × `statement`로 집계(2026-08-30 실측):

| 날짜 | BS | CF | IS | SCE | APPR | **note** |
|---|---|---|---|---|---|---|
| 2026-08-06 | 9 | 9 | 9 | 3 | – | – |
| 2026-08-08 | 173 | 173 | 191 | 173 | – | **14,739** |
| 2026-08-10~24(산발) | 소량 | 소량 | 소량 | 소량 | 22 | – |
| **2026-08-29**(전수 body 재적재) | **273,481** | **272,373** | **302,860** | **249,820** | **23,942** | **0** |

→ **`statement='note'` 행은 전체 기간을 통틀어 2026-08-08 하루, 14,739건이 전부다.**
그 뒤 2026-08-29에 본문(BS/CF/IS/SCE/APPR)은 전수 재적재됐지만 **주석은 손대지 않았다** —
이게 바로 §Phase 0-1에서 마주친 "본문(operating_income)은 있는데 D&A만 없는" 패턴의 정확한
원인이다.

FY2024+ note_lines를 가진 고유 rcept **26,518건 중 report_tables(note) 매칭 19건(0.07%)**
— 계층2(`note_lines`, `report_lines`)나 계층3(`combine.py`) 자체는 멀쩡하고, **정확히
`report_tables`의 note 부분만** 사실상 비어있다.

### 1-4. 타임라인 재구성 — `logs/full_reload_*` 포렌식

- **07-31 07:29~12:48 실행**(`full_reload_20260731_072933`): 본문+주석 **전량** TRUNCATE 후
  재적재, **0건 에러**로 완료(`전체 완료`). 이때 `report_tables` **5980MB** — 당시엔
  주석까지 포함해 포괄적으로 채워졌던 것으로 보인다.
- **08-08 15:51:44 실행**(`full_reload_20260808_155144`, `SKIP_BODY=1`,
  R11 note/SCE 열 오귀속 수정 반영 목적): `note_lines` **TRUNCATE 실행됨** → "② 주석 적재
  시작" 로그 직후 **로그가 끊김**(샤드 완료 기록 전혀 없음 — 도중에 중단된 것으로 추정).
- **08-08 16:38:02 실행**(`full_reload_20260808_163802`, `RESUME_NOTES=1`): 시작 시점에
  이미 `note_lines` 51,696,913행 존재("이어서" 모드) → 6샤드 각 2.2~2.4시간, **0건 에러로
  완료**. 그러나 **`RESUME_NOTES` 모드는 "note_lines에 그 rcept가 이미 있으면 스킵"만
  판정하고 `report_tables` 존재 여부는 안 본다** — 이미 note_lines에 있던(즉 대다수인)
  rcept는 이 실행에서 `store_report_tables()`가 아예 안 불려 report_tables(note)가
  안 채워진 채로 넘어갔다. 이 실행이 실제로 처리한 건 14,739건뿐이었고, 그게 §1-3의
  "08-08 하루치"와 정확히 일치한다.
- **08-08 이후 22일**(~08-30): 주석 전체 재적재가 다시 실행된 적이 없다(로그 없음).
  08-29의 대규모 재적재는 본문만 대상이었다(§1-3).

★ **07-31의 "완료" 실행이 왜 지금 안 보이는지는 로그만으로 완전히 재구성되지 않는다** —
`report_tables`는 TRUNCATE가 ①(본문) 단계에만 걸려 있어 이론상 07-31 이후 주석 쪽이
지워질 이유가 없는데, 실측은 08-08 이전 데이터가 전무함을 보여준다(가능성: 07-31과 08-08
사이에 이 스크립트 밖에서 별도 TRUNCATE가 있었거나, 07-31 실행의 report_tables 결과가
애초에 주석까지 포괄적이지 않았을 수 있다). **원인 재구성은 여기서 멈춘다 — 지금 상태를
고치는 데는 필요하지 않다.** 필요하면 Phase 3(재발방지)에서 스크립트 자체를 더 견고하게
만드는 것으로 대신한다.

### 1-5. 재발 방지 포인트 — `RESUME_NOTES`의 재개판정 허점

`full_reload_after_sanitize.sh`의 `RESUME_NOTES=1` 모드가 "이미 처리됨"을 `note_lines`
존재로만 판정하는 것 자체가 이번 사고의 구조적 원인이다 — `report_tables`처럼 **나중에
추가된 파생 테이블**이 있으면, 그 파생 테이블만 비어 있어도 재개 로직은 감지 못 한다.
같은 패턴이 다음에 다른 파생 테이블이 추가될 때 재발할 수 있다.

---

## 2. 설계 결정

### D1. 고칠 것은 주석(notes)뿐 — 본문은 이미 정상

§1-3에서 본문(BS/CF/IS/SCE/APPR)은 08-29 전수 재적재로 이미 포괄적으로 채워져 있음을
확인했다. **이번 백필은 주석만 대상**(`SKIP_BODY=1`).

### D2. 재개(RESUME_NOTES) 대신 전량(TRUNCATE) 재적재

이번엔 애초에 "이어서" 할 게 없다 — 목표가 report_tables(note)의 완전 재구축이므로,
`RESUME_NOTES` 없이 스크립트 기본 동작(② 단계: `TRUNCATE TABLE note_lines` +
인덱스 drop → 6샤드 병렬 재적재 → 인덱스 재생성)을 그대로 쓴다. §1-4의 재발 방지 관점에서도
이번엔 "재개"가 사고를 키운 원인이었으므로 전량 재적재가 맞다.

### D3. std_v3 전수 재빌드 필수(SKIP_STD_V3 끄지 않음)

`report_tables`만 고쳐서는 `std_financials_v3`가 자동으로 바뀌지 않는다 —
`build_std_v3.py --all`을 반드시 같이 돌려야 새 D&A가 std_v3에 반영된다. 스크립트 ③단계가
이미 이걸 한다(`SKIP_STD_V3` 안 주면 기본 실행).

### D4. 비용 실측(07-31 완료 실행 기준)

| 단계 | 07-31 실측 소요(6샤드 병렬) |
|---|---|
| ② 주석 재적재 | 3.07~3.15시간(샤드당) |
| ③ std_v3 전수 재빌드 | 53~65분(2,534 corp · 185,268 rows) |
| **합계(순차)** | **약 4~4.3시간** |

디스크: 현재 여유 **130GB**(2026-08-30 실측). `note_lines` 현재 53GB → TRUNCATE 후
재적재로 비슷한 규모로 재성장(스크립트 자체 설계 원칙 — "TRUNCATE 후 순수 INSERT로 bloat
0", §스크립트 코멘트). 07-31 실행 때 여유 165~278GB 구간에서 문제없이 돌았던 것과 지금의
130GB를 비교하면 **여유는 있으나 07-31보다 빠듯하다** — Phase 0에서 실행 직전 재확인 필요.

### D5. 장시간 실행 — 반드시 백그라운드(nohup) + 로그 감시

4시간대 작업이라 대화형으로 막고 있으면 안 된다([[feedback-long-running-commands]]).
`full_reload_after_sanitize.sh` 자체가 이미 `nohup` 없이도 백그라운드 실행에 적합한
구조(로그를 `logs/full_reload_<STAMP>/`에 남김, `wait`로 샤드 완료 기다림)다.

### D6(선택, 별도 커밋) — `RESUME_NOTES` 재개판정 보강

§1-5의 재발방지 — `RESUME_NOTES` 모드의 "이미 처리됨" 판정에 `report_tables`(해당
statement) 존재 여부도 같이 확인하도록 스크립트를 보강. **이번 백필의 필수 전제조건은
아니다** — 이번엔 RESUME 없이 전량 재적재하므로 문제가 안 되지만, 다음에 비슷한 파생
테이블이 또 생기면 같은 사고가 재발할 수 있어 별도로 남겨둔다.

---

## 3. 구현 Phase (미착수 — 승인 대기)

### Phase 0 — 착수 전 최종 확인 (읽기 전용, 대부분 이미 완료)

- [x] 원인 확정(§1) — 표본 직접 대조 + `report_tables` 날짜별 집계 + 로그 포렌식.
- [ ] **0-1.** 실행 직전 디스크 여유 재확인(`df -g $(psql -tAc 'SHOW data_directory')`) —
      D4의 130GB가 유효한지, 그 사이 다른 작업으로 줄지 않았는지.
- [ ] **0-2.** `collector.storage_guard`로 NAS(`raw_report`) 마운트 상태 확인(스크립트
      자체가 시작 시 자동으로 함 — 사전 확인은 실패 시 빨리 알기 위한 것).
- [ ] **0-3.** 실행 전 `report_tables`/`note_lines` 행수·크기 스냅샷 기록(롤백/비교 기준점).

### Phase 1 — 주석 전량 백필 실행 (사용자 승인 후, 백그라운드)

- [ ] **1-1.** `SKIP_BODY=1 nohup bash scripts/full_reload_after_sanitize.sh 6 > logs/report_tables_notes_backfill_2026-08-30.log 2>&1 &`
      (샤드 수 6은 07-31 실행과 동일 — 필요시 조정).
- [ ] **1-2.** 진행 중 `logs/full_reload_<STAMP>/main.log` 주기적 확인(Monitor 또는
      TaskOutput) — ② 주석 적재 완료 → 인덱스 재생성 → ③ std_v3 재빌드 순서.
- [ ] **1-3.** 완료 후 로그의 최종 테이블 크기 요약 확인(스크립트가 자체적으로 출력).

### Phase 2 — 검증 — ★ 실행 완료(2026-08-30, 사용자가 Phase 1 직접 실행)

**Phase 1 실행 결과**(`scripts/backfill_report_tables_notes_2026-08-30.sh`, 12:00:32~16:46:32,
≈4.8시간): 주석 재적재 6샤드 전부 0건 에러(done 105,202 · skip 178 합계) → std_v3 전수
재빌드 2,546 corp · 190,550 rows · 4325s(≈72분) → 전체 완료.

- [x] **2-1.** `report_tables(note)` 커버리지 재측정 — **14,739행(0.07%) → 15,661,687행,
      FY2024+ rcept 매칭 19건 → 26,876건**(백필 전 모집단 26,518건을 오히려 넘어섬 — 그
      사이 신규 필링 반영분 포함, 사실상 완전 커버리지 달성).
- [x] **2-2.** `census_valdaily_v2v3_sample_compare_2026-08-30.py` 재실행 — 표본 20건 중
      불일치 **17건(85%, 백필 전 35%에서 오히려 상승)**. ★단순 % 비교는 오도적이라
      성격별로 분해:

      | 유형 | 건수 | 해석 |
      |---|---|---|
      | v3가 v2엔 없던 값을 새로 확보(순수 gain) | **11건** | 의도한 효과 그대로 — v2의 `cf_da_sync`는 fy≥2024만 패치해 그 이전 연도는 원래 v2에 없었는데, v3의 `note_da.py`는 연도 무관하게 동작해 그 공백까지 메움 |
      | ebitda 값 소폭 차이(둘 다 non-null) | 1건 | v2/v3 소스 선택 차이로 보이는 경미한 차이 |
      | net_debt 손실/차이(D&A와 무관) | 2건(FY2024 포함) | 이 백필 범위 밖 — 별도 이슈 |
      | net_debt+eq 손실 + op_income/ni 차이(1999-2010대) | 3건 | **이번 백필과 무관** — `build_std_v3.py --all`이 기본 `year_min=2015`라 FY2010은 오늘 재빌드 대상이 아니었다. 무작위 표본이 이번에 우연히 다른 corp을 뽑아 드러난 기존 조건 |

      → **원래 목표("v2엔 있는데 v3는 NULL")는 해소 확인.** net_debt/eq 관련 별개 이슈는
      §6(범위 밖)에 기록.
- [x] **2-3.** `pytest tests/ fin2/tests/` — **634 passed, 1 failed**(기존 무관 실패
      `test_biz_section.py::test_lxintl_facility_table_dropped`, baseline과 동일) — 회귀 0.
- [x] **2-4.** Gate B 표본 재감사 — 동일 40개사(`--sample 40 --seed 42 --fy-min 2010`)를
      source=v2/v3 양쪽으로 대조(둘 다 `--no-commit`, DB 미반영):

      | | source=v2 | source=v3 |
      |---|---|---|
      | 행 gate_status | fail_a 0 / fail_b 14 / pending 139 | fail_a 0 / fail_b 8 / pending 788 |
      | 보고서 gate(Phase B) | pass 2001 / **fail_a 170** / pending 0 | pass 1967 / **fail_a 169** / pending 24 |

      **v2·v3 fail_a가 사실상 동일(170 vs 169)** — 오늘 백필/재빌드로 인한 신규 등급
      전이가 아니라 **애초부터 있던 조건**(전수 Gate B 스윕이 안 된 무작위 corp/기간의
      베이스라인 — 이 프로젝트가 지금까지 고쳐온 건 trade_payables/controlling_ni 등
      **특정 개념별** fail_a였지 전체 무작위 스윕이 아니었다). **등급 전이 0건 확인**.
- [x] **2-5.** `std_v2_retirement_port_to_v3_2026-08-22.md` §3.10의 "★2026-08-30 정정"
      문단 — 이 백필 결과로 봤을 때 원래 결론("v3가 상위집합")이 **맞았음이 확인**됐다
      (report_tables만 채워지면 note_da.py가 실제로 v2보다 넓게 커버). 정정문에 이 확인
      결과를 추가.

### Phase 3 — 재발 방지 (선택, 별도 커밋, D6)

- [ ] **3-1.** `full_reload_after_sanitize.sh`의 `RESUME_NOTES` 판정에 `report_tables`
      존재 확인 추가.

---

## 4. 검증 계획

Phase 2와 동일(위 참고). 핵심 기준: **§1-3의 note 커버리지가 26,518건의 대다수로
올라가야 성공**이고, `valuation_daily` 표본 재대조에서 "v2엔 있는데 v3는 NULL" 패턴이
사라져야 한다.

---

## 5. 롤백

`note_lines`/`report_tables`는 **원문 XML(raw_report)에서 재생성 가능한 파생 테이블**이다
— 백필이 잘못돼도 정보 손실이 아니라 재실행하면 된다. 다만 TRUNCATE는 실행 중 실패 시
되돌릴 수 없으므로(Phase 0-3의 스냅샷은 "얼마나 잃었는지" 확인용이지 복구용이 아님),
실행 전 디스크·NAS 상태 확인(Phase 0-1/0-2)이 사실상의 안전장치다.

---

## 6. 명시적 범위 밖

- **`valuation_daily` 이식 자체** — `valuation_daily_v3_migration_plan_2026-08-30.md`
  소관. 이 백필이 끝나야 그 문서의 Phase 0-2를 재개할 수 있다.
- **net_debt 등 D&A와 무관한 v2/v3 불일치**(§Phase 0-1 표본의 00210980/00132804) — 이
  백필로 해소되지 않는다. 별도 원인 규명 필요(그 문서 소관).
- **D6(RESUME_NOTES 판정 보강)** — 위 Phase 3, 이번 백필의 필수 전제 아님.
- **07-31~08-08 사이 report_tables가 정확히 어떻게 비었는지의 완전한 재구성** — §1-4에서
  멈춤. 지금 상태를 고치는 데 필요하지 않다.

---

## 7. 참고

- `docs/plans/valuation_daily_v3_migration_plan_2026-08-30.md` §Phase 0-1 — 이 발견의 출처.
- `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` §3.10 — "v3가 상위집합" 결론의
  정정 기록.
- `scripts/full_reload_after_sanitize.sh` — 백필 실행 스크립트(기존, 신규 작성 불필요).
- `logs/full_reload_20260731_072933/`, `logs/full_reload_20260808_*` — 타임라인 재구성 근거.
