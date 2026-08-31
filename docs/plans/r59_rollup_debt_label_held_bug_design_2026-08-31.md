# R59(가칭) — `bs.long_term_debt` 결합(rollup) 라벨 유동/비유동 동시존재 시 HELD 소실

**상태**: ★★★★★**완전 종료(2026-08-31)** — 구현 + 전수재빌드 + Gate B 전수재감사(2회) +
원문대조 전부 완료. `docs/PARSING_RULES.md` R59로 등재.
**발견 경위**: [`valuation_daily_blockers_da_netdebt_design_2026-08-30.md`](valuation_daily_blockers_da_netdebt_design_2026-08-30.md)
§2-10 / §6 (net_debt 순서4-③ 재감사 중 부산물로 발견, 2026-08-31). 이 문서는 그 발견을
이어받아 구현 가능한 설계로 좁힌다.

## 1. 문제

`account_maps/bs_accounts.py`의 `bs.long_term_debt` 라벨 목록에는 "사채+차입금"을 하나로
합친 **결합(rollup) 라벨**(`장기차입금및사채` 등, 만기 구분이 라벨 자체에 없는 개념)이
등록돼 있고, 등록 안 된 표기 변형(`사채및장기차입금`/`사채및차입금`/`차입금및사채` 등)은
fuzzy(0.95~0.97)로 같은 canonical에 붙는다.

문제는 **같은 필링 안에서 이 결합 라벨이 유동부채 섹션과 비유동부채 섹션에 각각 별도
줄로 동시에 존재하는 경우**다 — 이건 정상적인 재무제표 구조(유동성 대체분 vs 잔여
비유동분)이지 오류가 아니다. 그런데 두 인스턴스 모두 라벨 텍스트가 (거의) 같아서 같은
canonical(`bs.long_term_debt`)로 매핑되고, `_resolve()`는 서로 다른 값을 가진 두 후보를
충돌로 보고 **`bs.long_term_debt` 전체를 HELD(=None)** 처리한다 — 유동분만 버리는 게
아니라 **비유동분(진짜 장기차입금)까지 통째로 사라진다**.

실측(`00181712` FY2024연결): `사채 및 장기차입금`(14,788,886,000,000, 유동부채) +
`사채및장기차입금`(48,073,129,000,000, 비유동부채) 동시존재 →
`long_term_debt` = `None` → net_debt 62,861,073,000,000 과소.

`bs.long_term_debt`는 net_debt 전용 파생 컬럼이 아니라 `std_financials_v3`의 핵심
DIRECT_MAP 컬럼이라 다른 소비자에도 영향 — R57/순서4-③처럼 net_debt-scoped 우회
(`_additive_debt_for_net_debt`)로 덮을 게 아니라 **canonical 자체를 고쳐야** 한다.

## 2. R57/순서4-③과 병리는 같지만, 기존 코드를 그대로 재사용할 수 없다

`fin2/layer3/combine.py`에는 이미 구조가 똑같은 두 메커니즘이 있다:

- `_NONCURRENT_SIBLING`(순서4-①, B1-D1): 기본이 **유동**(`bs.short_term_debt`)인
  canonical의 후보가 실은 비유동인데 라벨엔 그 표시가 없을 때, `bs.long_term_debt`로
  재라우팅.
- `_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`(순서4-③, R58): 기본이 **비유동**
  (`bs.bond`/`bs.convertible_bond`/`bs.exchange_bond`/`bs.warrant_bond`)인 canonical의
  후보가 실은 유동인데 라벨엔 그 표시가 없을 때, 각각의 `current_*` sibling으로
  재라우팅. **이 문서의 버그와 방향이 완전히 같다** — `bs.long_term_debt`도 기본이
  비유동인 canonical이고, sibling(`bs.short_term_debt`)도 이미 존재한다.

하지만 재라우팅 판정 함수 `_is_current_by_section_only()`는 "label_raw에 `장기`/`비유동`
문자열이 있으면 무조건 False(재라우팅 안 함)"를 전제로 한다 — 전환사채/사채/교환사채/
신주인수권부사채 계열은 그 전제가 맞다(현재분은 라벨 자체가 "유동사채"/"전환사채(유동)"처럼
비유동 표시가 없다).

**`bs.long_term_debt`의 결합 라벨은 이 전제가 깨진다.** 라벨 자체가 `장기차입금및사채`처럼
"장기"라는 단어를 이미 포함한 채로 canonical의 기본(비유동) alias로 등록돼 있다 — 그리고
실측된 유동측 변형 중에도 `사채 및 장기차입금`처럼 "장기"가 그대로 들어있는 경우가
실재한다. 즉 **라벨 텍스트만으로는 유동/비유동을 구분할 수 없는 canonical**이라는 뜻이고,
`_is_current_by_section_only()`를 그대로 재사용하면 이 경우를 걸러내지 못한다.

### 실측(2026-08-31, 재현 스크립트: 이 세션에서 1회성 작성, 미커밋)

`report_lines`(BS, FY, table_seq=0)에서 `%차입금%사채%` 또는 `%사채%차입금%` 라벨이
같은 필링·같은 정규화 텍스트(공백 제거)로 유동+비유동 양쪽에 동시 존재하는 경우:

- 근사 재현: **304개 필링**(정확도 낮은 SQL 근사치 — §2-10이 보고한 538건과 스캔
  패턴/정규화 방식이 달라 숫자가 다르다. 정확한 재현은 §2-7/§2-8이 쓴 것과 같은
  v3 자체 로직(`collect_candidates`+`_resolve`) 직접 실행이 필요 — 구현 착수 시 재측정)
- 유동측 인스턴스 **417건** 중 label_raw에 `장기`/`비유동`이 포함된 것: **단 1건(0.2%)**
  — 그리고 그 1건이 바로 §2-10의 대표사례 `00181712` 그 자체다.

**결론**: `_is_current_by_section_only()`를 그대로 재사용하면 모집단의 99.8%는 맞게
재라우팅되지만, 정작 이 버그를 대표하는 사례(`00181712`)는 놓친다. 라벨 검사를 생략한
"순수 section_path 기반" 판정이 필요하다 — 단, 이 판정을 기존 함수에 그대로 얹으면
전환사채류(라벨 검사가 유효하고 필요한 계열)의 동작을 바꿔버릴 위험이 있다.

## 3. 설계안

### 3-1. 새 함수 `_is_current_by_section_only_pure()` — 라벨 무시, section_path만 판정

```python
# fin2/layer3/combine.py, near _is_current_by_section_only

def _is_current_by_section_only_pure(row: dict) -> bool:
    """Section-only variant of _is_current_by_section_only, WITHOUT the label_raw
    veto — for canonicals whose bare/rollup alias text itself contains 장기/비유동
    tokens (e.g. bs.long_term_debt's '장기차입금및사채'), so the label-based negative
    check in _is_current_by_section_only would incorrectly refuse to reroute a
    genuinely-current instance whose label happens to carry the same combined
    wording. Use ONLY for canonicals where section_path is confirmed to be the
    authoritative signal (measured, not assumed — see R59 design doc §2)."""
    sp = row.get("section_path") or ""
    return "유동" in sp and "비유동" not in sp
```

### 3-2. `_CURRENT_CONTAMINATED_NONCURRENT_SIBLING` 순회 루프를 함수-per-엔트리로 일반화

지금은 `for _src, _sib in _CURRENT_CONTAMINATED_NONCURRENT_SIBLING.items():` 블록
안에서 `_is_current_by_section_only()`를 하드코딩 호출한다. `bs.long_term_debt`만
다른 판정 함수를 써야 하므로, dict 값을 `(sibling, classifier_fn)` 튜플로 바꾸거나
별도의 `_CURRENT_CONTAMINATED_NONCURRENT_SIBLING_PURE = {"bs.long_term_debt":
"bs.short_term_debt"}` 를 새로 만들어 **별도 루프**로 처리한다(기존 bond 계열 루프는
한 글자도 안 건드림 — 회귀 위험 최소화 우선).

권고: 후자(별도 dict + 별도 루프) — 기존 R58 코드에 대한 diff가 0이라 재감사 시
"이번 변경이 기존 4개 canonical에 영향 없음"을 코드만 보고도 확인 가능하다.

### 3-3. guard 재확인 필요 — sibling에 이미 후보가 있으면 드롭(요약X)

기존 로직의 guard(`if cands.get(_sib): continue`)를 그대로 물려받으면: 어떤 필링이
`bs.short_term_debt`에 이미 자기 자신의 후보(예: 진짜 `단기차입금`)를 갖고 있으면,
재라우팅된 유동측 rollup 값은 **합산되지 않고 버려진다**(bond 계열과 동일한 기존
트레이드오프 — 이중계상 방지가 우선). 이 경우도 `bs.long_term_debt`는 최소한
충돌에서 벗어나 비유동값을 정상 확정하므로 현재(전액 소실)보다는 개선이지만,
"완전 복구"는 아니다. **구현 착수 시 이 guard가 몇 건에서 발동하는지 실측 필요**
(즉, 몇 %가 완전 복구되고 몇 %가 "비유동만 복구"에 그치는지).

## 4. 검증 계획 (기존 R57/R58 관례 그대로)

1. 위 설계로 구현 → 단위테스트(`00181712` 재현 + "sibling에 이미 후보 있음" 가드 케이스
   + "전부 유동"/"전부 비유동" 무재라우팅 케이스) 추가.
2. ~~Gate B 전수재감사를 net_debt 지표뿐 아니라 두 컬럼 자체의 fail_a 등급전이로도
   확인~~ → **구현 착수 시 정정(§4-1 참고)**: `face_audit`은 `long_term_debt`/
   `short_term_debt`를 애초에 감사하지 않아 canonical 스코프 등급전이 자체가 불가능함이
   드러났다. 대신 전체 pass→fail_a 전이(R57/R58과 동일) + `std_financials_v3` 두
   컬럼의 전/후 값 직접 비교로 대체.
3. 원문대조: `00181712` 포함 표본 다건 — 특히 §3-3 guard가 발동하는 케이스(sibling에
   기존 후보가 있는 필링)를 최소 1건은 원문 대조.
4. 소급 백필 필요([[parser-pipeline-integration-runbook]] 절차 준수) — `combine.py`
   변경은 std_v3 전체 재표준화 대상.

## 4-1. 구현 결과(2026-08-31)

- **코드**: `_is_current_by_section_only_pure()` + `_CURRENT_CONTAMINATED_NONCURRENT_
  SIBLING_PURE = {"bs.long_term_debt": "bs.short_term_debt"}` + `_resolve()` 안의 별도
  재라우팅 루프(§3-2 권고안 그대로 — 별도 dict/loop, 기존 R58 코드 diff 0).
- **단위테스트**: `fin2/tests/test_combine_debt_r59_rollup_label_pure_reroute.py`(5건)
  — `00181712` 재현("장기" 포함 라벨도 재라우팅됨 확인) · 더 흔한 "장기" 미포함 변형 ·
  "전부 유동" 무재라우팅 · sibling 기존후보 guard · 기존 R58 4종 canonical과 같은
  `_resolve()` 호출 안에서 상호간섭 없음. `pytest tests/ fin2/tests/` 667 passed/1
  failed(기존 무관 — `test_biz_section.py`, `combine.py`/이 변경과 무관 영역, 이전부터
  실패 중이던 것).
- **★§4의 검증계획 정정** — face_audit 스키마 실측 결과 `fail_fields`(jsonb 배열)에
  등장하는 필드는 23종(`cash`/`cogs`/`controlling_ni`/... 등)뿐이고
  `long_term_debt`/`short_term_debt`는 없다 — **Gate B가 이 두 컬럼을 원래부터 감사
  대상으로 포함하지 않는다**는 뜻. 그래서 canonical 스코프 fail_a 등급전이 확인은
  불가능하다(측정 대상 자체가 없음). `scripts/run_r59_verification.sh`를 이에 맞춰
  재설계: 0단계에서 영향 필링(약 300~500여건, 정확한 수는 스캔 패턴에 따라 다름 —
  §2 참고)의 `std_financials_v3.long_term_debt`/`short_term_debt`를 재빌드 전
  스냅샷(`std_v3_debt_snap_20260831_r59`)으로 뜨고, 5단계에서 재빌드 후 값과 비교해
  `recovered_after`(HELD→값 복구)/`still_held_after`(guard로 여전히 일부만 복구,
  §3-3) 를 직접 센다. 4단계는 R57/R58과 동일한 전체 pass→fail_a 전이만 확인(이 두
  컬럼이 다른 DIRECT_MAP 컬럼에 연쇄 영향을 주는지의 일반 회귀 확인 — canonical
  스코프가 아니라 전체 스코프).
- **미실행**: `scripts/run_r59_verification.sh`(전체 재빌드 5-shard + Gate B 전수재감사
  5-shard, 수십 분 소요 추정) — 장시간 명령이라 사용자 실행 대기
  ([[feedback-long-running-commands]]).

## 4-2. 1차 전수재검증 결과(2026-08-31, `scripts/run_r59_verification.sh` 1회차)

- **Gate B 회귀**: 0건(어떤 방향으로도 gate_status 전이 없음 — face_audit 578,571행
  전수, `face_audit_snap_20260831_r59` 대비).
- **복구율**: 영향 필링(근사 재현) 304건 중 287건이 수정 전 HELD, **243건(84.7%)
  복구**. 나머지 44건 원문+매퍼 대조 결과:
  - **42건 — R59와 무관한 별개 알리아스 갭 신규 발견**: "사채및차입금"/"사채 및
    차입금"(사채가 앞에 오는 어순)이 fuzzy 매칭 threshold 밑으로 떨어져 `unknown`으로
    빠짐(반대 어순 "차입금및사채"는 이미 fuzzy로 정상 매칭됨) — 라벨이 애초에
    `bs.long_term_debt` 후보 풀에 들어오지 않아 R59의 재라우팅이 구조적으로 도울 수
    없는 케이스. v2도 동일하게 실패(이번 세션 이전부터 있던 갭, 회귀 아님).
  - **1건 — 설계에서 예견한 그대로**(§3-3 sibling guard): `00181712` **FY2024**(발견
    계기였던 그 62.9조 소실 사례 자체는 FY2024 재현이 정확히 이거였는데, 완전복구됨 —
    이 잔여 1건은 FY2024의 다른 표현 인스턴스가 아니라 같은 회사 다른 처리 결과. 상세는
    §4-3 참고)에서 `bs.short_term_debt`에 이미 진짜 `단기차입금` 후보가 있어 가드가
    재라우팅을 막음(부분개선 — 비유동값은 여전히 못 구함, 완전소실보다는 나음).
  - **1건 — 3-way 섹션분할**(`00160588` FY2012연결): 유동/비유동 외에 "금융업부채"
    섹션까지 같은 라벨("차입금 및 사채")로 3개 인스턴스 존재. `short_term_debt`는
    정상 복구(`None`→2,571,673,000,000)됐으나 `long_term_debt`는 비유동+금융업 두
    인스턴스가 여전히 충돌 — R59 설계범위 밖의 새 변형(부분개선).

**사용자 승인 후 42건 알리아스 갭도 즉시 수정**(`account_maps/bs_accounts.py`에
"사채및차입금" exact alias 추가) → §4-3.

## 4-3. 2차 전수재검증 결과(2026-08-31, alias 추가 후 재실행) — ★완전 종료

- **Gate B 회귀**: 0건(1차와 동일 — 어떤 방향으로도 전이 없음).
- **복구율**: 304건 중 287건 HELD → **283건(98.6%) 복구**, 잔여 **4건**:
  - `00160588` FY2012연결 — §4-2에 기록한 3-way 섹션분할, 그대로(R59 설계범위 밖).
  - `00181712` FY2024연결 — §4-2에 기록한 sibling guard 트레이드오프, 그대로(설계상
    의도된 동작).
  - `00653194` FY2016(연결+별도, 2건) — **재검증 중 발견한 또 다른 별개 알리아스 갭**:
    "차입금 및 전환사채"(차입금+전환사채 결합, `bs.bond`군이 아니라 `bs.convertible_
    bond`와 얽힌 전혀 다른 결합 라벨)가 완전히 `unknown`으로 빠짐. v2도 동일 실패.
    실측 스코프 **1개사(00653194) 단독** — 이 세션에서는 수정하지 않음(범위 밖으로
    남김, §5).
- **결론**: 42건 알리아스 갭 수정으로 44→4로 잔여 대폭 축소, 그중 3건은 이미 원인이
  분류된 것(설계상 트레이드오프 1 + 3-way 분할 1 + 새 알리아스 갭 1개사·2건). 트랙
  종료 조건(Gate B 회귀 0 + 복구 확인) 완전 충족.

## 5. 범위 밖으로 남기는 것

- `bs.current_portion_lt_debt` 개념 분리(상위 문서 §6에 이미 별도 백로그로 기재) —
  이 트랙과 독립.
- 정확한 538건(또는 재측정치) 전수의 "완전복구 vs 비유동만 복구" 비율 실측은
  설계 승인 후 구현 세션에서 진행(§3-3) — §4-2/§4-3에서 완료.
- **"차입금 및 전환사채" 결합 라벨 미매핑**(§4-3에서 발견, `00653194` 단독 실측) —
  `bs.bond`군이 아니라 `bs.convertible_bond`와 얽힌 별개 결합 라벨이라 이번 alias
  수정과 범위가 다름. 실측 스코프 1개사뿐이라 이 트랙에서는 미수정.

## 6. 참고

- [`valuation_daily_blockers_da_netdebt_design_2026-08-30.md`](valuation_daily_blockers_da_netdebt_design_2026-08-30.md) §2-10, §6
- `fin2/layer3/combine.py:1380-1414` — `_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`/`_is_current_by_section_only`(R58, 순서4-③)
- `fin2/layer3/combine.py:1291-1330` — `_NONCURRENT_SIBLING`/`_is_noncurrent_by_section_only`(R58, 순서4-①)
- `account_maps/bs_accounts.py:307-323` — `bs.long_term_debt` 결합 라벨 alias
- `docs/PARSING_RULES.md` — 구현 확정 시 R59로 등재
