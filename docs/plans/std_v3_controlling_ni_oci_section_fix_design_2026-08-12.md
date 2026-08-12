# 설계 — `controlling_ni` OCI-섹션 혼동 수정 (2026-08-12 작성, 같은 날 오후 재설계)

> **진행 상태(2026-08-12 저녁)**: Phase 0~2 전부 완료(§7). `fin2/layer3/combine.py` 코드
> 수정 + 유닛테스트 12개 + DB 재검증까지 끝났다(fail_a 404건 중 311건 정답 확정, PASS
> 5,000건 표본 changed→NULL 18건까지 축소). **DB(std_financials_v3)는 아직 미변경** —
> Phase 3(전량 백필)은 다음 승인 대상.
>
> **이 문서는 설계뿐이다. 코드는 전혀 건드리지 않았다. 실행은 별도 승인 필요**
> (정책상 계획 문서 작성이 곧 실행 허가가 아님). 원인조사 전체 내역 =
> [`std_v3_native_gate_b_plan_2026-08-11.md`](std_v3_native_gate_b_plan_2026-08-11.md) §10.
>
> **개정 이력**: 최초안(오전)은 `section_path` 텍스트 필터(§2, "포괄" 있으면 후보 제거)로
> 설계했었으나, 실행 승인 직후 Phase 0 사전확인 중 **그 필터가 이미 알려진 라벨-스왑 사례
> 2건에서 실제 오답을 낸다는 게 재현 확인**돼 전면 재설계했다(§1-C). 아래는 재설계된 버전 —
> **identity 트리거 확장** 방식이다. 최초안의 §1-A/§1-B(근본원인 분석)는 여전히 유효해 유지.

배경: [`rearchitecture_4layer.md`](rearchitecture_4layer.md) §7 후속 1번(v3-native 품질게이트)
아래에서 §8 옵션 정리 후 fail_a 필드분포를 처음 확정했더니 `controlling_ni`(404건, 372개사)가
`trade_payables`(§8-D, 300건)보다도 큰 최대 미조사 덩어리로 드러났다(std_v3_native_gate_b_plan
§9). 사용자 지시로 원인조사 착수 → 5개사 원문(원시 후보) 대조로 근본원인 확정(§10) → 이 문서는
그 위에서 **수정 설계**만 다룬다.

---

## 0. 요약

- **근본원인**(최초안과 동일): 원문에 "지배기업(의) 소유주지분"류의 거의 동일한 라벨이
  `당기순이익(손실)의 귀속`(정답) 섹션과 `총포괄손익의 귀속`(OCI 포함, 오답) 섹션 **양쪽**에
  독립적으로 등장한다. 이 모호성을 풀 안전장치(`_resolve_ni_attribution`,
  `fin2/layer3/combine.py:401`, 2026-08-08 신설, controlling_ni+noncontrolling_ni=net_income
  항등식으로 역산)가 이미 있지만 **`conflicts`에 걸린 경우만** 작동해서, 두 후보의 매핑 stage가
  다르면(각주접미사 등으로 정답이 `normalized`/`fuzzy`, 오답이 `exact`) `_resolve()`의 stage
  tiebreak가 `conflicts`로 넘기지도 않고 오답을 곧장 확정 — 안전장치를 건너뛴다.
- **최초안(텍스트 필터)은 기각됨**: `section_path`에 "포괄" 있으면 후보를 버리는 방식은 이미
  2026-08-08에 한 번 검토됐다가 라벨-스왑 반례 2건(DH오토웨어 00110583, 에프알텍 00442561 —
  원문 자체에서 두 섹션의 실제 내용이 뒤바뀌어 있음) 때문에 기각된 이력이 있다
  (`[[std-v3-controlling-ni-fix-complete-2026-08-09]]`). 이번 재설계 착수 직후 그 반례 2건을
  DB로 재현 검증했더니, **최초안 필터를 적용하면 정확히 그 2건에서 오답을 채택**한다는 게
  확인됐다(§1-C). 텍스트를 신뢰하는 방식 자체가 구조적으로 위험함이 재확인됨.
- **새 설계 — identity 트리거 확장**: 텍스트를 전혀 보지 않는다. 대신 `is.controlling_ni`/
  `is.noncontrolling_ni` 두 canonical에 한해 `_resolve()`의 stage-rank 숏컷을 건너뛰고 **원시
  후보 값이 하나라도 갈리면 항상 `conflicts`로 보내 기존 identity 안전장치
  (`_resolve_ni_attribution`)가 반드시 호출되게** 한다. 이 안전장치는 라벨-스왑 반례 2건에서도
  이미 정답을 내고 있던 검증된 로직이라, 텍스트 필터의 회귀 위험이 원천적으로 없다(§2).
- **실측 스코프 — 최초안보다 훨씬 크다**: fail_a로 보이는 404건뿐 아니라, **현재 PASS로
  잡혀있는 레코드 중에도 같은 메커니즘으로 오염된 게 약 3.1%(추정 ~2,200건, 모집단 70,721건)
  존재**한다(§3). 원인은 Gate B 감사기(`face_audit.py`) 자체가 섹션 구분 없이 "canonical
  라벨로 잡힌 원문 후보 값 집합에 DB값이 있는지"만 보기 때문에, 잘못된(OCI) 섹션값이 들어가도
  통과시킨다(§3-2). 이 감사기 자체를 고치는 건 **이번 설계 범위 밖으로 사용자가 명시적으로
  분리 결정**(§6) — combine.py 수정만 먼저 진행.

---

## 1. 왜 기존 두 안전장치가 이 케이스를 못 잡았나 (+ 최초안이 왜 위험했나)

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
로 시작하므로 이 경우 아예 호출 자체가 무의미해진다. 실측: 404건 중 278건(68.8%)이 이 경로.

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
지점, 이 결론은 재설계 후에도 유효).

### 1-C. ★최초안(텍스트 필터)이 라벨-스왑 반례 2건에서 실제로 오답을 낸다 — 재현 확인(2026-08-12 오후)

`_resolve_ni_attribution`의 docstring(`combine.py:413`)에 이미 경고가 있었다: "Deliberately
NOT a section_path text filter — measured ~0.5% of filings have the two section labels
literally swapped in the source (DH오토웨어 00110583 2022H1, 에프알텍 00442561 2017H1)".
`[[std-v3-controlling-ni-fix-complete-2026-08-09]]`에 이 2건은 **사용자가 원문 표로 직접
대조 확인**해서 텍스트 필터를 이미 한 번 기각한 이력으로 기록돼 있다.

Phase 0 사전확인에서 이 2건을 DB(`report_lines`)로 재조회해 실제로 재현했다:

| 회사 | `당기순이익(손실)의 귀속` 섹션 값 | `총포괄손익의 귀속` 섹션 값 | net_income(항등식 앵커) | 정답 |
|---|---|---|---|---|
| DH오토웨어 00110583 2022H1 | -2,314,224,620 | -2,651,838,029 | -2,667,463,698 | **"포괄" 쪽**(+NCI -15,625,669 = 앵커와 일치) |
| 에프알텍 00442561 2017H1 | -2,046,435,530 | -1,947,034,624 | -1,947,034,624 | **"포괄" 쪽**(NCI=0, 그대로 일치) |

두 회사 모두 원문 자체가 라벨과 실제 내용이 뒤바뀌어 있어서, "section_path에 '포괄' 있으면
버림" 필터를 적용하면 **정답 후보를 지우고 오답을 채택**한다 — §3-1(최초안)의 "안전한 실패"가
아니라 확인된 새 회귀다. 반면 기존 `_resolve_ni_attribution`은 라벨 텍스트가 아니라 net_income
항등식으로 앵커링하므로 이 두 건 모두 이미 정답을 내고 있었다. **이 재현이 최초안 폐기와
재설계의 직접적 근거다.**

---

## 2. 새 설계 — identity 트리거 확장(`_resolve()`가 controlling_ni/noncontrolling_ni를 항상 conflicts로 보냄)

### 2-1. 핵심 아이디어

문제는 "identity 안전장치 자체가 부족한 것"이 아니라 **그 안전장치가 발동하는 조건(§1-A의
`conflicts` 진입)이 너무 좁다는 것**이다. `is.controlling_ni`/`is.noncontrolling_ni` 두
canonical에 한해, 원시 후보 값이 하나라도 갈리면(단일값이 아니면) **stage-rank 숏컷을 건너뛰고
무조건 `conflicts`로 보내 `_resolve_ni_attribution`이 항상 판단 기회를 갖게** 한다. 텍스트
(`section_path`)는 전혀 보지 않으므로 §1-C의 스왑 반례에서도 안전하다 — 그 안전장치가 이미
그 2건에서 검증됐기 때문이다.

### 2-2. 코드 스케치 (설계용, 실제 diff 아님)

```python
# fin2/layer3/combine.py — _resolve() 본문, ADDITIVE_CANON 분기 처리 후
# (다른 canonical 과 마찬가지로 vals = {...} 계산 직전 지점)
_NI_ATTRIBUTION_CANON = {"is.controlling_ni", "is.noncontrolling_ni"}
...
if c in _NI_ATTRIBUTION_CANON:
    vals = {r["value"] for r in rows}
    if len(vals) > 1:
        # stage-rank 로 조기 확정하지 않는다 — 두 후보(정답=당기순이익귀속,
        # 오답=총포괄손익귀속)의 stage 가 갈리면(각주접미사 등) 오답이 'exact'로
        # 이겨버려 곧장 confirmed 되던 게 §1-A 근본원인. 항상 identity 안전장치
        # (_resolve_ni_attribution, 아래에서 호출됨)에게 판단을 맡긴다.
        conflicts[c] = sorted(rows, key=lambda r: (r["value"] is None, r["value"]))
        continue
    # 값이 하나뿐이면(=원문에 이견 없음) 기존 경로 그대로 confirmed.
```

`_resolve_ni_attribution(cands, confirmed, conflicts)`는 이미 `_resolve()` 직후 호출되고
있으므로(`combine.py:598`) 별도 배선 불필요 — `conflicts`에 들어가는 빈도만 넓어진다.

### 2-3. single_wrong/canonical_mismap(78건, 원 설계 §2-3 분류)은 이 방식으로 못 잡힘 — 범위 밖 유지

원시 후보가 애초에 **하나뿐**(OCI 섹션 값만 이 canonical로 잡힘, 정답 후보가 없거나 다른
canonical로 샘)인 경우는 `vals` 가 이미 단일값이라 `len(vals) > 1` 분기 자체를 안 타서 이
방식으로 개선되지 않는다(최초안의 §2-3에서도 이 78건은 "정답 대신 결측"까지만 됐던 것과
동일 — 최초안의 텍스트 필터가 이 경우에 한해서는 오히려 결측 전환의 이점이 있었으나, 텍스트
자체의 회귀 위험이 더 크므로 포기). Phase 2(canonical_mismap, account_mapper 가드)로 별도
설계 필요, 이번 범위 밖 유지(최초안 §6과 동일 결론).

---

## 3. 정량화 — fail_a 404건 + PASS 안에 숨은 오염(신규 발견, 2026-08-12 오후 Phase 0)

### 3-1. fail_a 404건 재현 (읽기전용 시뮬레이션, DB 미변경)

`face_audit`(source_version=v3, gate_status=fail_a, fail_fields ∋ controlling_ni)에서 실제
404건(174개사)을 뽑아 `combine_full()`을 프로덕션과 동일하게 호출 + `_resolve()`만 위 §2-2
로직으로 몽키패치해 재현:

| 구분 | 건수 | 비고 |
|---|---|---|
| 원시후보 실제 충돌(raw candidates 다중값) | 321건 | |
| → identity로 정답 확정 | **301건(93.8%)** | |
| → 여전히 결측(identity도 애매) | 20건 | 결측>오염 정책대로 안전하게 보류 |
| 원시후보가 애초 단일값(§2-3 케이스) | 83건 | 이 설계로 미해결, Phase 2 대상 |

알려진 스왑 반례 2건(§1-C)도 이 방식으로 회귀 없음 재확인.

### 3-2. ★신규 발견 — Gate B 감사기 자체가 섹션을 구분하지 못해 PASS 안에도 같은 오염이 숨어있다

회귀검증 차 "현재 PASS인 레코드에 이 로직을 적용하면 값이 바뀌는지"를 무작위 표본(800건 →
5,000건으로 정밀화)으로 검사했더니 예상 밖으로 **3.12%(156/5,000)가 값이 바뀐다**는 게
나왔다. 원인을 추적한 결과:

`fin2/audit/face_audit.py`(약 776행 부근)의 매칭 로직은 `by_canon.get(canon, [])`로
**섹션 구분 없이** canonical이 같은 원문 후보를 전부 모아 `won_vals` 집합을 만들고,
`if val in won_vals`면 무조건 PASS 처리한다. 즉 DB에 저장된 값이 "당기순이익의 귀속"
섹션 값이든 "총포괄손익의 귀속" 섹션 값이든 **원문 어딘가에 그 숫자가 있기만 하면 통과**
시킨다 — combine.py의 원래 버그와 **똑같은 맹점**을 감사기도 그대로 갖고 있다. 실제
사례(00113207 2015Q3) 대조: DB엔 "총포괄손익의 귀속" 값(129억)이 들어있고 원문에 그 숫자가
있어서 PASS 처리돼 있지만, 정의상 맞는 값은 "당기순이익의 귀속"(277억)이다 — **지금까지 fail_a
404건 뒤에 숨어서 Gate B로는 안 보이던, 같은 버그의 인스턴스**다.

| 항목 | 값 |
|---|---|
| PASS 모집단(연결·controlling_ni 비NULL) | 70,721건 |
| 표본 | 5,000건 |
| 값 변경 | 156건(3.12%) |
| → 결측(NULL) 전환 | 31건(19.9%, 오염 제거) |
| → 다른 확정값 교체 | 125건(80.1%, identity로 정답 재확정) |
| **모집단 추정 오염 규모** | **약 2,200건** |

**종합 스코프**: fail_a 404건(visible) + PASS 안 추정 ~2,200건(invisible, Gate B로 검증 불가)
≈ **총 ~2,600건**, 원 설계(§10)가 파악했던 404건의 약 6배.

### 3-3. 다른 필드로 번지는 문제인지 확인 — 아니다, 국한됨

같은 `_CONSOLIDATED_ONLY` 그룹인 `controlling_equity`(BS)도 같은 이중섹션 패턴이 있는지
확인했다: BS의 "지배기업 소유주" 라벨 76,050건 중 rcept당 `section_path`가 2개 이상인
경우는 2건(0.003%)뿐이고, 그마저도 "자본 > 기타자본항목" 같은 계층적 하위분류이지
"당기순이익 귀속 vs 총포괄손익 귀속" 같은 개념적 이중섹션이 아니다. 이 버그 패턴은 IFRS
손익계산서의 "당기순이익 귀속"/"총포괄손익 귀속" 개념이 병존하는 구조에서만 발생하므로,
**`is.controlling_ni`/`is.noncontrolling_ni` 2개 필드에 국한**된 것으로 확인됨(다른 필드로
확산될 위험 낮음).

---

## 4. 회귀 리스크 및 검증 계획

### 4-1. §3의 시뮬레이션이 이미 1차 검증 역할을 했다

최초안 §3-1의 우려(OCI=0 기간·단일서식 기업)는 이번 방식에서는 텍스트를 보지 않으므로
원천적으로 해당 없음 — "값이 갈리는 경우에만" 발동하고, 갈리지 않으면(OCI=0이라 두 섹션
숫자가 같으면)애초에 `len(vals)==1`이라 건드리지 않는다. §3-1의 5,000건 PASS 재검증에서
드러난 "changed 156건"은 §4-3에서 다루듯 회귀가 아니라 숨은 오염 발견으로 재해석된다.

### 4-2. 남은 검증 순서 (§8-A 방법론 재사용, 코드 작성 후)

1. **유닛테스트**: `fin2/tests/test_combine_ni.py` 신규 — §1-C 스왑 2건(반례, 정답 유지
   확인) + §3-1 자동분류 3종(합성 오라클) 등록.
2. **404건 전체 재현 재확인**: §3-1과 동일 스캔을 실제 코드 diff로 재실행 — 301/321
   예상치와 실측 일치 확인.
3. **PASS 표본 확대 재검증**: §3-2의 5,000건보다 더 크게(가능하면 전수) 돌려 "changed"
   156건류를 개별 몇 건 원문대조로 **진짜 오염 수정인지, 새 회귀인지** 최종 판별
   (identity가 만든 새 값이 원문의 "당기순이익 귀속" 섹션과 실제로 일치하는지 표본 확인).
4. **Gate B 재감사**: 아래 §5.

### 4-3. 승인 체크포인트

- Phase 1 코드 작성 전: 이 개정판 설계 문서 사용자 승인.
- Phase 1 코드 작성 후, DB 커밋 전: §4-2의 1~3단계 결과를 사용자에게 보고 후 커밋 승인.
- DB 커밋(백필) 전: 영향범위(§5에서 재산정된 스코프) 재확인 후 실행.

---

## 5. 백필·배선 — ★스코프가 372개사에서 전체(또는 훨씬 넓은 범위)로 확장됨

최초안(§4)은 "fail_a 372개사만 scoped 재실행"으로 충분하다고 봤으나, §3-2에서 **PASS population
전반에 걸쳐 무작위로 분포한 숨은 오염(~2,200건, 특정 회사군에 몰려있지 않음)**이 발견돼 스코프
가정이 깨졌다. 372개사만 재실행하면 fail_a는 고쳐지지만 PASS 안의 ~2,200건은 그대로 남는다.

- **① 전방(신규 공시) 반영**: 코드 수정만으로 다음 `build_std_v3.py` 실행부터 자동 적용(최초안과
  동일, 배선 변경 불필요).
- **② 소급 백필 — 전체 재실행 필요**: 오염이 무작위 분포이므로 **`--corp` scoped가 아니라
  `--all --year-min 1999` 전량 재실행**이 필요(정확한 corp 목록을 사전에 알 수 없음 — 코드
  수정 후 실제로 돌려봐야 어느 corp가 영향받는지 나옴). 규모는 `[[pre2015-layer2-backfill-plan-2026-08-10]]`
  Phase5(81,660건, err0)급 — 실행시간 가늠 필요(사용자에게 장시간 명령 사전 안내,
  `[[feedback-long-running-commands]]`).
- **③ Gate B 재감사**: `gateb_audit.py --source v3 --fy-min 1999 --recheck`(전량, `--corp-file`
  범위 한정 불가 — PASS 쪽도 재확인해야 하므로).

---

## 6. 범위 밖 (사용자 결정으로 분리, 별도 트랙)

- **face_audit 섹션-인식 개선**: §3-2에서 발견된 감사기 자체의 맹점(섹션 구분 없이 canonical
  값 집합 멤버십만 봄). 이번 combine.py 수정과 별개로 감사기를 고쳐야 **이 유형의 버그를 Gate B
  스스로 감지**할 수 있게 된다(지금은 고쳐도 "fail_a→pass 전환분"만 지표로 보이고, 숨은 오염
  수정분(PASS→NULL 31/5000류)은 Gate B 지표에 안 잡혀 별도로 보고해야 함). **사용자가 이번
  세션에서 명시적으로 범위 밖 분리 결정**(2026-08-12) — 이번엔 combine.py만 먼저 진행.
- **Phase 2(canonical_mismap, 40건 + §2-3의 78건)**: "지배기업주주 귀속 당기순이익(손실)"류
  라벨이 `is.net_income`으로 새는 것은 `account_mapper.py`의 별도 가드가 필요(예: "귀속"+"지배"가
  라벨에 있고 "당기순이익"/"당기순손익"을 포함하면 `is.net_income`이 아니라 `is.controlling_ni`로
  우선 배정). 라벨 변형이 더 다양할 수 있어 별도 표본조사가 먼저 필요.
- **Phase 3(shallow-depth 오작동, 00118345류 소수)**: `_reduce_conflict`의 "얕은 depth=총계"
  휴리스틱이 section_path 없는 무관한 표를 오인하는 문제. 발생빈도 낮고 별개 메커니즘.
- **잔여 미분류(개별성 강한 소수)**: 이번 수정 적용 후 재스캔해서 남는 케이스만 개별 확인.

---

## 7. TODO 체크리스트 (승인 후 실행 순서)

### Phase 0 — 사전확인 · ✅완료(2026-08-12)
- [x] `scripts/build_std_v3.py`의 scoped 재실행 방법 확인.
- [x] 최초안(텍스트 필터) 반례 2건 재현 → **기각, identity 트리거 확장으로 재설계**.
- [x] 404건 재현 시뮬레이션(읽기전용) — 321건 중 301건(93.8%) 정답 확정 확인.
- [x] PASS population 회귀검증(800→5,000건 표본) — 오염 규모 정밀 측정(~2,200건, 3.12%).
- [x] 타 필드 확산 여부 확인(controlling_equity) — 국한됨 확인.
- [x] Gate B 감사기 자체의 섹션-맹점 발견·원인규명 — 범위 밖 분리(사용자 결정).

### Phase 1 — 코드 구현 · ✅완료(2026-08-12)
- [x] `_NI_ATTRIBUTION_CANON` 상수 추가.
- [x] `_resolve()`에 §2-2 분기 삽입(stage-rank 숏컷 우회, 항상 conflicts로).
- [x] 유닛테스트 작성(§4-2-1, 스왑 반례 포함) — `fin2/tests/test_combine_ni.py`.

### Phase 2 — 검증 · ✅완료(2026-08-12, 같은 날 후속)
- [x] 404건 재현 스캔(§4-2-2) — 실제 코드(몽키패치 없음)로 재확인, §3-1 예상치(301/321,
  93.8%)와 **정확히 일치**.
- [x] PASS 광역 재검증(§4-2-3) — 5,000건 재확인, 157/5000(3.14%) 변경(설계 예상 3.12%와
  거의 일치). changed→다른값 3건(00397289/00939331/00120021) 원문대조 **전부 진짜 수정
  확인**(옛값이 OCI 섹션이거나 심지어 무관한 다른 표 값이었음).
- [x] **★신규 발견 — changed→NULL 36건 내부 불균일**: 사용자 요청("부작용없이 가야지")으로
  심층분석, 그중 10건(28%)은 옛값이 이미 "당기순이익 귀속"(정답) 섹션이었는데 identity가
  재확인 못 해 결측으로 떨어지는 **커버리지 손실**로 확인(오답 아님, 순수 손실).
- [x] **2차 안전장치 추가**(같은 날, 위험 재도입 없이): "최고단계 후보 2개 이상이 값
  일치"(원래 버그 404건 중 0건에서 관측된 패턴 — 안전) 시 신뢰하는 `_top_stage_corroborated`
  추가. NULL 36→34건으로 소폭 개선(1/10 회복), 404건 수치는 불변(301/321) 확인.
- [x] **잔여 9건 원인규명**(사용자 요청 후속) → A(당기순이익 라인 자체 원문無, EBT−세금
  역산 가능 12%) / B(실질NCI=0인데 노이즈 후보 때문에 0 시도 안 됨 24%) / C(반올림 1~2원
  오차로 정확매칭 실패 3%) / D+D'(진짜 불명확 44%) / E(net_income 자체가 확정 안 됨 18%)
  로 분류. **사용자 결정: A+B+C 전부 구현.**
- [x] **A+B+C 구현·검증 완료**: `_derive_net_income_from_ebt`(§A, net_income 후보가
  없을 때만 EBT−tax_expense 로 국소 앵커, `confirmed`엔 안 씀), `nci_vals.add(0)`(§B, 다른
  후보가 있어도 0을 항상 함께 시도), `_match_ni_identity` eps=2원(§C, 정확매칭 실패시만,
  eps로도 복수매칭이면 여전히 결측 유지) — 셋 다 "정확히 1개만 맞을 때만 채택" 원칙 유지.
  최종: fail_a 404건 중 identity 해결 **301→311건(96.9%)**(신규 10건 중 5건 원문대조 전부
  정답 섹션 확인), PASS 5,000건 changed→NULL **36→18건(0.36%)**. 잔여 18건은 진짜 모호
  (여러 조합 동시 성립)이거나 이번 설계 밖 결손(net_income 자체 다중값)이라 결측 유지가 맞음.
  유닛테스트 12개(§A/§B/§C 각 1개 + 모호성 유지 가드 1개 추가) 전부 통과, `pytest tests/
  fin2/tests/` 489 passed(무관한 기존 결함 1건만 — `test_lxintl_facility_table_dropped`,
  main 대비 재현 확인, biz_section 파서 별개 트랙).

### Phase 3 — 백필+DB 반영 (다음 승인 대상)
- [ ] 전량 `build_std_v3.py --all --year-min 1999` 재실행(§5-②, 장시간 명령 — 사전 안내).
- [ ] `gateb_audit.py --source v3 --fy-min 1999 --recheck` 전량 재감사(§5-③).
- [ ] fail_a 실측 감소 확인 + PASS→NULL 전환분 별도 집계(Gate B 지표만으론 전체 개선폭 안 보임).

### Phase 4 — 커밋
- [ ] pytest 전체 통과 확인.
- [ ] 계획서/메모리 갱신.
- [ ] git 커밋(push는 사용자 지시 시).

---

관련 메모리: `[[std-v3-native-gate-b-plan-2026-08-11]]` `[[std-v3-controlling-ni-fix-complete-2026-08-09]]`
`[[feedback-verify-against-source]]` `[[nightly-jobs-paused-phase-a3]]` `[[feedback-long-running-commands]]`
