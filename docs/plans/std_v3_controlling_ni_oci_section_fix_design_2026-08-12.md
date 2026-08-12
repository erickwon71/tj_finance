# 설계 — `controlling_ni` fail_a(404건) 수정 (2026-08-12 작성)

> **이 문서는 설계뿐이다. 코드는 전혀 건드리지 않았다. 실행은 별도 승인 필요**
> (정책상 계획 문서 작성이 곧 실행 허가가 아님). 원인조사 전체 내역 =
> [`std_v3_native_gate_b_plan_2026-08-11.md`](std_v3_native_gate_b_plan_2026-08-11.md) §10.

배경: [`rearchitecture_4layer.md`](rearchitecture_4layer.md) §7 후속 1번(v3-native 품질게이트)
아래에서 §8 옵션 정리 후 fail_a 필드분포를 처음 확정했더니 `controlling_ni`(404건, 372개사)가
`trade_payables`(§8-D, 300건)보다도 큰 최대 미조사 덩어리로 드러났다(std_v3_native_gate_b_plan
§9). 사용자 지시로 원인조사 착수 → 5개사 원문(원시 후보) 대조로 근본원인 확정(§10) → 이 문서는
그 위에서 **수정 설계**만 다룬다.

---

## 0. 요약

- **근본원인**: 원문에 "지배기업(의) 소유주지분"류의 거의 동일한 라벨이 `당기순이익(손실)의
  귀속`(정답) 섹션과 `총포괄손익의 귀속`(OCI 포함, 오답) 섹션 **양쪽**에 독립적으로 등장한다.
  이 모호성을 풀 안전장치(`_resolve_ni_attribution`, `fin2/layer3/combine.py:401`, 2026-08-08
  신설)가 이미 있지만 **`conflicts`에 걸린 경우만** 작동하도록 설계돼 있어서, 두 후보의 매핑
  stage가 다르면(각주접미사 등으로 정답이 `normalized`/`fuzzy`, 오답이 `exact`) `_resolve()`의
  stage tiebreak가 `conflicts`로 넘기지도 않고 오답을 곧장 확정 — 안전장치를 건너뛴다.
- **자동분류(404건 전수)**: `section_confusion_stage_masked` 278건(68.8%) +
  `section_confusion_single_wrong` 38건(9.4%) + `canonical_mismap` 40건(9.9%) = **97.9%가 한
  원인계열**. 나머지 소수(00118345류 `_reduce_conflict` shallow-depth 오작동 등)는 이질적.
- **이 설계의 범위**: **Phase 1**(section_confusion 316건, 78.2%)만 구체적으로 설계한다 —
  원인이 명확하고 기존 코드 패턴(trust-account 필터)을 그대로 재사용할 수 있어 리스크가 낮다.
  Phase 2(canonical_mismap, 40건)·Phase 3(shallow-depth, 소수)는 **별도 조사가 더 필요해
  이 문서에서 방향만 스케치**하고 범위 밖으로 명시한다(§8-C/§8-D를 별도 트랙으로 뗀 것과 같은
  이유 — 한 번에 다 하려다 검증이 흐려지는 것을 피한다).

---

## 1. 왜 기존 두 안전장치가 이 케이스를 못 잡았나

### 1-A. `_resolve_ni_attribution`의 conflicts-한정 트리거

`_resolve()`(`combine.py:333`)의 흐름:

```
vals = {r["value"] for r in rows}
if len(vals) == 1: confirmed[c] = ...; continue
best = max(stage_rank for r in rows)
top = [rows at best stage]
top_vals = {r["value"] for r in top}
if len(top_vals) == 1: confirmed[c] = ...; continue   # ← 여기서 이미 "해결"돼버림
...
if c in CONSUMED_CANON: conflicts[c] = top   # 여기까지 못 옴
```

정답(당기순이익 귀속)이 `normalized`/`fuzzy`, 오답(총포괄손익 귀속)이 `exact`이면
`top_vals`는 오답 단독(길이 1)이 되어 **`conflicts`에 진입하지 않고 곧장 confirmed**된다.
`_resolve_ni_attribution`(`combine.py:401`)은 `if "is.controlling_ni" not in conflicts: return`
로 시작하므로 이 경우 아예 호출 자체가 무의미해진다. 실측: 278건(68.8%)이 이 경로.

### 1-B. account_mapper의 기존 "포괄손익 귀속" 가드는 다른 라벨 스타일을 겨냥한 것

`parser/common/account_mapper.py:167-172`에 이미 가드가 있다:

```python
# '포괄손익, 지배기업소유주귀속지분'·'총포괄손익,비지배지분' 은 ... controlling_ni 가 아니다
if "포괄손익" in normalized and "지배" in normalized and fs_section in (None, "is"):
    return MappingResult(f"unknown.{normalized[:80]}", 0.0, "unknown")
```

이 가드는 **라벨 텍스트 자체**에 "포괄손익"과 "지배"가 함께 있는 스타일(예: '포괄손익,
지배기업소유주귀속지분')을 겨냥한 것이다. 그런데 이번 근본원인 표본(00112651/00105101/
00112165/00110884/00109693)의 라벨은 그냥 "지배기업의 소유주지분"/"지배기업 소유주지분"
— **라벨 자체엔 "포괄손익"이라는 단어가 아예 없다.** OCI/순이익 구분은 라벨이 아니라 그 라인이
속한 **`section_path`**(표 상위 섹션 헤딩: "총포괄손익의 귀속" vs "당기순이익의 귀속")로만
표현된다. `get_mapper().map(label_raw, fs_section=fs)`는 `fs_section`(bs/is/cf 대분류)만 받고
`section_path`(세부 섹션)는 **애초에 안 보이므로**, account_mapper 레벨에서는 구조적으로 이
케이스를 구분할 수 없다. `section_path`는 `combine.py`의 후보 dict에만 실려 있다 — 그래서
수정은 **account_mapper가 아니라 combine.py에 있어야 한다**(section_path를 볼 수 있는 유일한
지점).

---

## 2. Phase 1 설계 — `_resolve()`에 OCI-섹션 구조적 사전필터 추가

### 2-1. 핵심 아이디어

`is.controlling_ni`/`is.noncontrolling_ni` 두 canonical에 한해, 원시 후보들 중
`section_path`에 "포괄"이 들어간 것(OCI 귀속 섹션)과 안 들어간 것(순이익 귀속 섹션 또는
섹션 미표시)이 **공존하면, OCI 쪽을 후보 풀에서 제거하고 나머지로 `_resolve()`를 계속
진행**한다. 기존 신탁계정(trust-account) BS 그랜드토탈 필터(`combine.py:342-351`,
`_BS_GRAND_TOTAL`/`_trust_account_table_seqs`)와 **동일한 코드 패턴**을 재사용한다 — 이미
검증된 스타일(narrow·self-verifying·좁은 신호만 사용, `[[std-v3-side-findings-...]]`류 교훈과
일치).

### 2-2. 코드 스케치 (설계용, 실제 diff 아님)

```python
# fin2/layer3/combine.py, 상단 상수 근처
_NI_ATTRIBUTION_CANON = {"is.controlling_ni", "is.noncontrolling_ni"}
_OCI_SECTION_RE = re.compile(r"포괄")


def _is_oci_section(section_path) -> bool:
    """section_path 가 총포괄손익/포괄손익 귀속 섹션인지(당기순이익 귀속과 구분).
    §10(std_v3_native_gate_b_plan_2026-08-11.md) 근본원인: 같은 라벨('지배기업 소유주지분')이
    '당기순이익의 귀속'과 '총포괄손익의 귀속' 양쪽에 등장 — 후자는 controlling_ni 가 아니다."""
    return bool(section_path) and bool(_OCI_SECTION_RE.search(section_path))


# _resolve() 본문, trust-account 필터 바로 다음(c in _BS_GRAND_TOTAL 블록 다음)
if c in _NI_ATTRIBUTION_CANON:
    non_oci = [r for r in rows if not _is_oci_section(r.get("section_path"))]
    if non_oci:
        rows = non_oci
    else:
        # 이 canonical 로 잡힌 후보가 전부 OCI 귀속 섹션뿐 — 진짜 순이익귀속 라인이
        # 아예 이 canonical 로 안 잡혔거나(다른 canonical 로 오매핑, Phase 2 대상) 원문에
        # 순이익귀속 섹션이 따로 없는 경우. 결측 > 오염 — 짐작해서 채우지 않는다
        # (_resolve_ni_attribution 의 기존 정책과 동일선상, combine.py:422 참고).
        continue
```

`ADDITIVE_CANON` 분기보다 먼저(또는 그 이후 아무 canonical 이나 상관없는 지점, 단
`vals = {...}` 계산 이전) 삽입한다. `is.controlling_ni`/`is.noncontrolling_ni`는
`ADDITIVE_CANON`도 `_BS_GRAND_TOTAL`도 아니므로 삽입 위치는 유연하다.

### 2-3. 예상 효과 (자동분류 기준 재계산)

- **section_confusion_stage_masked (278건)**: OCI 후보 제거 후 비-OCI 후보 단독 생존 →
  `vals` 길이 1 → 즉시 confirmed에 정답 값. **수정됨.**
- **section_confusion_single_wrong (38건)**: OCI 후보만 있고 비-OCI 후보가 없음 → 전부 제거
  → 이 canonical 은 `confirmed`에 안 들어감(NULL) → gate_status 는 fail_a(오염값)에서
  pending(결측)으로 전환. **오염 제거**(값 자체를 되찾는 건 아님 — 정답이 다른 canonical 로
  샜거나 원천적으로 안 잡힌 경우라 Phase 1 범위 밖).
- **canonical_mismap (40건)**: `is.controlling_ni` 후보가 OCI 섹션뿐이라 위 단독폴백 경로로
  가 NULL이 됨(현재의 틀린 값보다는 개선) — 하지만 **진짜 정답을 되찾지는 못한다**(정답이
  `is.net_income`으로 새고 있는 것은 account_mapper 쪽 문제, Phase 2 대상). 이 40건은 Phase 1
  으로 "틀림→결측" 전환까지만 되고, Phase 2 가 별도로 필요.

즉 Phase 1 하나로 **278건은 완전 수정**, **78건(38+40)은 오염 제거(결측화)**, 합쳐서 404건 중
**316건(78.2%)에서 fail_a 오염이 사라진다**(그 중 68.8%는 진짜 정답으로 교체).

---

## 3. 회귀 리스크 및 검증 계획

### 3-1. 우려 지점

§8-A 에서 "형제 태그 일치"만 믿었다가 두 차례 회귀를 낸 교훈([[feedback-verify-against-source]])이
있으므로 이번에도 같은 수준의 경계가 필요하다. 구체적 우려:

1. **OCI=0인 기간**: 그 기간 총포괄손익=당기순이익이라 "총포괄손익 귀속" 섹션의 숫자가
   우연히 진짜 정답과 같을 수 있다. 이런 케이스가 현재 **PASS**로 잡혀 있다면(원천이 OCI
   섹션인데 값이 우연히 맞아서), 필터가 그 값을 지워버려 PASS→pending 회귀를 만들 수 있다.
2. **당기순이익 귀속 섹션 자체가 없는 문서 포맷**: 일부 필사(연결포괄손익계산서 단일서식)
   기업은 "총포괄손익의 귀속"만 있고 "당기순이익의 귀속"이 별도로 없을 수 있다 — 이 경우
   지금은(운좋게?) OCI 섹션 값이 쓰이고 있었을 수 있는데 필터가 이를 지운다.
3. **section_path 텍스트 변형**: "포괄" 이 아닌 다른 표현(예: 드물게 로마자/영문 라벨)으로
   OCI 섹션을 표시하는 문서가 있다면 필터가 못 잡아 이미 아는 오염이 그대로 남는다(안전한
   방향의 실패 — 새 회귀는 아니고 미해결로 남을 뿐).

### 3-2. 검증 순서 (§8-A 방법론 재사용)

1. **유닛테스트**: `fin2/tests/test_face_audit.py` 또는 신규 `fin2/tests/test_combine_ni.py` —
   404건 자동분류에 쓴 3가지 케이스(stage_masked/single_wrong/canonical_mismap)와 §10에서
   원문대조한 5개사를 합성/실측 오라클로 등록. §3-1 우려 1·2 를 각각 반례 테스트로 명시
   추가(OCI=0인 기간을 합성해 "필터가 지우면 안 되는 경우"를 회귀로 잡는다).
2. **알려진 fail_a 표본 재현**: 404건 전체(스크래치패드 스캔 스크립트 재사용/재작성)를
   수정된 `_map_rows`+필터 로직으로 재계산 — §2-3 예상치(278 수정/126 결측화)와 실측이
   맞는지 대조.
3. **무작위 PASS 광역 재검증**(§8-A 필수 패턴): controlling_ni/noncontrolling_ni 가 존재하는
   PASS 레코드에서 수백~천 건 표본을 뽑아 필터 적용 전/후 값이 그대로인지 대조 — §3-1 우려
   1·2 가 실제로 발생하는지, 발생한다면 몇 건인지 정량화. **신규 회귀 0건을 목표**, 0이 아니면
   되돌리고 재설계(§8-A 전례를 따른다).
4. **Gate B 재감사**: 영향받는 corp_code만(404건의 corp 목록, 372개사) `gateb_audit.py
   --source v3 --corp-file <목록> --recheck`로 재감사해 fail_a 실제 감소를 확인.

### 3-3. 승인 체크포인트

- Phase 1 코드 작성 전: 이 설계 문서 사용자 승인.
- Phase 1 코드 작성 후, DB 커밋 전: §3-2의 1~3단계(유닛테스트+표본재현+PASS 광역재검증)
  결과를 사용자에게 보고 후 커밋 승인.
- DB 커밋(`--recheck`) 전: 영향범위(몇 개사·몇 건)를 다시 한번 확인 후 실행.

---

## 4. 백필·배선 (`docs/runbook_new_parser_pipeline_integration.md` 체크리스트 대조)

이번 변경은 "새 파서 추가"가 아니라 **기존 std_v3 빌드 엔진(`fin2/layer3/combine.py`)의
버그 수정**이라 런북의 체크리스트 A(collect_new.py 두 call site 배선)는 다른 방식으로
적용된다 — **현재 std_v3 빌드(`build_corp`)는 애초에 `collect_new.py` 데일리 흐름에 배선돼
있지 않다**(확인됨: `collect_new.py` grep 결과 무매치, 오직 `scripts/build_std_v3.py`가
`build_corp`를 호출하는 유일한 경로 — nightly-jobs-paused-phase-a3 이후 std_v3 는 수동/전량
재실행 방식으로 유지되고 있다, `[[nightly-jobs-paused-phase-a3]]`). 따라서:

- **① 전방(신규 공시) 반영**: 코드 수정만으로 **다음 `build_std_v3.py` 실행부터 자동 적용**
  (기존 구조 그대로, 새 배선 불필요 — std_v3 자체가 아직 데일리 자동화 대상이 아니라는 기존
  아키텍처 상태를 그대로 인정하고 넘어간다. 이 상태 자체를 바꾸는 건 이 설계의 범위 밖).
- **② 소급 백필**: 코드를 고쳐도 이미 만들어진 std_v3 행은 자동 재계산되지 않는다
  (`build_corp`가 매번 해당 corp/fy/period 를 delete-then-insert 하는 구조이므로 — 영향받는
  372개사만 다시 `build_corp` 호출하면 됨. 전체 재실행도 가능하지만 372개사 스코프가 확실하니
  좁게 가는 게 안전·검증도 쉽다):
  ```
  python scripts/build_std_v3.py --corp <corp_code1,corp_code2,...> --year-min 1999
  ```
  (확인됨: `build_std_v3.py`는 `--corp-file`이 아니라 `--corp`에 **쉼표구분** corp_code
  목록을 받는다 — 372개사를 콤마로 이어붙이면 됨, 별도 옵션 추가 불필요)
- **③ Gate B 재감사**: 위 §3-2-4.

---

## 5. TODO 체크리스트 (승인 후 실행 순서, 전부 미착수)

### Phase 0 — 사전확인
- [x] `scripts/build_std_v3.py`의 scoped 재실행 방법 확인 — `--corp <comma-separated>` 로
      충분(별도 옵션 추가 불필요, §4 참고).
- [ ] §3-1 우려 1·2(OCI=0 기간, 단일서식 기업)가 실제로 존재하는지 현재 PASS 모집단에서
      사전 스캔(코드 작성 전에 위험도 먼저 가늠).

### Phase 1 — 코드 구현
- [ ] `_is_oci_section()` 헬퍼 + `_NI_ATTRIBUTION_CANON` 상수 추가.
- [ ] `_resolve()`에 필터 블록 삽입(§2-2).
- [ ] 유닛테스트 작성(§3-2-1, 반례 포함).

### Phase 2 — 검증
- [ ] 404건 재현 스캔(§3-2-2), §2-3 예상치와 대조.
- [ ] 무작위 PASS 광역 재검증(§3-2-3), 신규 회귀 0건 확인 — 회귀 발견 시 §8-A 전례대로
      되돌리고 재설계.

### Phase 3 — 백필+DB 반영 (사용자 승인 후)
- [ ] 영향 372개사 `build_std_v3.py` 재실행(scoped).
- [ ] `gateb_audit.py --source v3 --corp-file <372개사> --recheck` 재감사.
- [ ] fail_a 실측 감소 확인(목표: controlling_ni 404 → ~48±α, §2-3 예상치와 대조).

### Phase 4 — 커밋
- [ ] pytest 전체 통과 확인.
- [ ] 계획서/메모리 갱신.
- [ ] git 커밋(push는 사용자 지시 시).

---

## 6. 범위 밖 (별도 트랙으로 분리)

- **Phase 2(canonical_mismap, 40건)**: "지배기업주주 귀속 당기순이익(손실)"류 라벨이
  `is.net_income`으로 새는 것은 `account_mapper.py`의 별도 가드가 필요(예: "귀속"+"지배"가
  라벨에 있고 "당기순이익"/"당기순손익"을 포함하면 `is.net_income`이 아니라
  `is.controlling_ni`로 우선 배정 — 174-179행 지분법 가드와 유사한 스타일). **이번 설계엔
  포함 안 함** — 라벨 변형이 더 다양할 수 있어 별도 표본조사가 먼저 필요.
- **Phase 3(shallow-depth 오작동, 00118345류 소수)**: `_reduce_conflict`의 "얕은 depth =
  총계" 휴리스틱이 section_path 없는 무관한 표(다른 table_seq)를 오인하는 문제. 발생빈도가
  낮고(자동분류 12% 미분류 안에 일부만 해당) 별개 메커니즘이라 별도 조사 필요.
- **잔여 미분류 48건(11.9%)**: 개별성이 강해 이번 자동분류 3종으로 안 걸림 — Phase 1 적용
  후 재스캔해서 남는 케이스만 개별 확인하는 게 효율적(먼저 큰 덩어리부터 처리).

관련 메모리: `[[std-v3-native-gate-b-plan-2026-08-11]]` `[[std-v3-controlling-ni-fix-complete-2026-08-09]]`
`[[feedback-verify-against-source]]` `[[nightly-jobs-paused-phase-a3]]`
