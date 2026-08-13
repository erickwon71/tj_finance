# combine.py stage-rank shortcut 우회 버그 — 수정설계 (2026-08-13)

**상태: 구현 완료(2026-08-14).** 코드 원인 확정 + "명백해 보이는" 일반 수정안을
전수 실측으로 검증했더니 **블랭킷 수정은 위험**하다는 게 드러나 좁은 curated-list
방식으로 재설계했다. §3의 curated override(`_REVENUE_TOTAL_OVERRIDE_CORPS`/
`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`) 구현 + §4 검증계획 전부 완료. `docs/
PARSING_RULES.md` R16으로 등재. 상세: [[gate-b-r16-override-implemented-2026-08-14]].

## 0. 배경

`docs/qa/gate_b_fail_a_revenue_tradepayables_triage_2026-08-13.md`에서 revenue 8건
(한국전자홀딩스·미래에셋벤처투자)·trade_payables 42건(부모/자식쌍) 잔여가 같은 계열의
코드 결함(`combine.py`)으로 추정된다고 보고했다. 본 문서는 그 원인을 코드 레벨로
확정하고, 수정 범위를 실측 검증까지 마친 설계다.

## 1. 확정 근본원인

`fin2/layer3/combine.py::_resolve()`, 437~447행:

```python
vals = {r["value"] for r in rows}
if len(vals) == 1:
    confirmed[c] = next(iter(vals))
    continue
best = max(_STAGE_RANK.get(r.get("stage"), 0) for r in rows)
top = [r for r in rows if _STAGE_RANK.get(r.get("stage"), 0) == best]
top_vals = {r["value"] for r in top}
if len(top_vals) == 1:
    confirmed[c] = next(iter(top_vals))   # ← 즉시 확정, _reduce_conflict() 호출 안됨
    continue
reduced = _reduce_conflict(c, top)
```

**stage 랭킹에서 유일하게 최고 stage를 차지한 후보가 있으면 그 값을 즉시 confirm**한다.
`_reduce_conflict()`(289~358행) 안에는 이미 다음 두 규칙이 구현돼 있는데, 이 shortcut
때문에 **top-stage 후보가 하나뿐이면 아예 호출되지 않는다**:

- 306~317행: `is.revenue` 전용 "총계 라벨(매출액/영업수익 등)이 구성요소보다 우선"
- 337~358행: 범용 "얕은 depth(section_path `>` 개수 적음)가 깊은 depth보다 우선"

실측(매퍼 직접 호출, 짐작 아님):

```
is '수수료수익'          -> is.revenue,        stage='exact'        (공백없는 등록별칭 그대로 일치)
is 'I. 영업수익'         -> is.revenue,        stage='normalized'   (로마숫자 접두사 → 정규화 후 매칭)
bs '매입채무및기타채무'      -> bs.trade_payables, stage='exact'
bs '매입채무 및 기타유동채무' -> bs.trade_payables, stage='normalized'
```

자식/구성요소 라벨이 공백·번호 없는 "깨끗한" 문자열이라 등록 별칭과 **글자 그대로**
일치해 `exact`를 얻고, 부모/총계 라벨은 로마숫자·공백·"유동" 같은 부가어 때문에
정규화를 거쳐야 `normalized`로만 매칭된다 — 그 결과 top_vals가 자식 하나로 collapse
되어 즉시 confirm되고, 이미 구현된 총계/depth 우선 규칙은 도달 불가.

이건 버그#3(R15, `f2d232c`)가 고친 것과 **같은 계열의 취약점**(stage-rank가 유일하게
남은 후보를 무조건 신뢰) — 그때는 `_CURRENT_STRICT`(유동/비유동)에 대해 380~395행에
"stage 랭킹 전에 미리 거르기" 가드를 추가했다. 이번엔 같은 패턴을 `is.revenue`(총계
vs 구성요소)·`bs.trade_payables`(부모 vs 자식)에도 적용하면 되는 것처럼 보였다 —
그런데 실측해보니 그렇게 간단하지 않았다(§2).

## 2. ★실측 — "명백한" 일반 수정안 둘 다 위험함을 확인

수정 전 반드시 해야 하는 것([[feedback-verify-against-source]]·`[[key-bugs-fixed]]`
전통): **fail_a 784건 안에서만 보지 말고, DB 전체(현재 PASS인 행 포함)에 대고 몇 건이
바뀌는지 먼저 세어본다.** 계층2(`report_lines`, 백필과 무관한 정적 데이터)만으로 두
후보 규칙을 시뮬레이션하고, 그 결과를 `face_audit`(현재 스냅샷, 08-13 01:08)과
대조했다.

### 2-1. `is.revenue`: "총계 라벨이 있으면 그것 우선" — 8 fix vs 303 regression

`_REVENUE_TOTAL_LABELS`(매출액/영업수익/매출/순매출액) 기반 사전필터를 stage 랭킹
전에 넣는 안을 시뮬레이션(`fin2/layer3/industry_profiles.py::apply_revenue_profile`이
나중에 덮어쓰는 회사는 결과가 무의미하므로 실제 함수를 그대로 호출해 제외):

| | 건수 |
|---|---:|
| 후보 flip(다른 top-stage 값 존재 + 총계 후보 존재) | 859 |
| — industry profile이 나중에 덮어써서 무관 | 296 |
| — 남은 것 중 현재 **PASS**(고치면 회귀 위험) | **303** |
| — 남은 것 중 현재 **fail_a**이고 고치면 report_won과 일치(진짜 수정) | **8** |

**303 : 8 = 38 : 1로 회귀가 압도적으로 많다.** 원인을 원문으로 확인(SBI인베스트먼트
00156910 2015년 1분기 별도): "I. 영업수익"(P, 4,637,783,457)은 트레이딩평가손익·
매도가능금융자산처분이익 등 **평가성 항목까지 섞인 총계**이고, "수수료수익"(F,
1,614,747,527)이 오히려 face_audit의 report_won과 **이미 일치**(gate_status=pass) —
즉 이 회사는 지금 자식 선택이 맞다. `induty_code=64992`(SBI인베스트먼트)·`649`(아주IB
투자)·`201`(KPX홀딩스, 지주회사인데 화학업 코드로 등록됨)로 `REVENUE_PROFILES`의
증권/은행 프로파일이 induty만으론 안 걸리는 회사들인데도, **개별적으로는 자식이
report_won과 이미 맞다.** 반대로 한국전자홀딩스(00159254)·미래에셋벤처투자(00340096)
는 원문대조로 총계가 맞음을 이미 확인했다(triage 문서 §1-1). **같은 구조(P=총계/
F=수수료수익)인데 회사마다 정답이 다르다** — 구조적 신호(라벨 존재 여부)만으로는
구별이 안 되는, 사용자 결정([[fx-declared-statements]]·증권 프로파일과 같은 계열의)
개별판단 영역이다.

### 2-2. `bs.trade_payables`: "node_role='P'(부모)가 있으면 우선" — 32 fix vs 11,761 regression

| | 건수 |
|---|---:|
| 후보 flip(유동/비유동 필터 후에도 다른 top-stage 값 + P후보 존재) | 11,965 |
| — 현재 **PASS**(고치면 회귀 위험) | **11,761** |
| — 현재 **fail_a**이고 고치면 report_won과 일치(진짜 수정) | **32**(5개사) |

**11,761 : 32 = 368 : 1로 훨씬 더 위험하다.** 대다수 회사는 "매입채무 및 기타유동채무"
(P, 부모, 트레이드+기타 다 합친 넓은 개념)가 아니라 "단기매입채무"/"매입채무"(F, 자식,
순수 매입채무만)가 report_won과 이미 일치 — 즉 지금 좁은(narrow) 값을 고르는 게
**대개는 맞다**(기존 `_NARROW_PREFER`의 설계 의도와 정확히 부합). 부모가 맞는 건
**5개사(32건)뿐**: 원문대조 완료된 현대공업(00164502)·국일신동(00203847)·
코아스(00210856)·케이엔솔(00304076)·IPARK현대산업개발(01310269).

### 2-3. 결론 — 블랭킷 규칙 금지, curated override로 좁힘

두 "명백한" 수정 모두 fail_a보다 훨씬 큰 **현재-정답(PASS) 모집단**을 깨뜨린다.
`[[feedback-verify-against-source]]`·버그#2(dividends_paid) 조사에서 이미 겪은 것과
같은 함정 — "구조가 같아 보이면 규칙 하나로 다 고칠 수 있다"는 가정이 실측에서
깨졌다. 기존 코드에도 정확히 같은 철학의 선례가 있다
(`fin2/layer3/industry_profiles.py`의 `CORP_INDUTY_OVERRIDE`·`NO_REVENUE_CORPS` —
"일반화 규칙으로 안 풀리면 확인된 개별사만 curated set에 등재"). 이 설계도 같은
패턴을 따른다.

## 3. 수정 설계 (curated override, 좁은 스코프)

### 3-1. `is.revenue` — `_REVENUE_TOTAL_OVERRIDE_CORPS`(신규)

```python
# ★revenue grand-total override(2026-08-13): _REVENUE_TOTAL_LABELS 총계 우선 규칙을
# 일반화하면 안 된다 — 실측(report_lines 전수) 결과 303개 현재-PASS 행이 회귀하고
# 겨우 8건만 고쳐짐(SBI인베스트먼트 등은 지금 자식 선택이 이미 정답). 원문대조로
# "총계가 정답"임을 개별 확인한 회사만 여기 등재.
# docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md §2-1
_REVENUE_TOTAL_OVERRIDE_CORPS = frozenset({
    "00159254",   # 한국전자홀딩스
    "00340096",   # 미래에셋벤처투자
})
```

`_resolve()`의 stage-rank shortcut **이전**(392행 `_CURRENT_STRICT` 블록과 같은 위치)에:

```python
if c == "is.revenue" and corp in _REVENUE_TOTAL_OVERRIDE_CORPS:
    grand = [r for r in rows
             if _norm_label(r.get("label_raw")) in _REVENUE_TOTAL_LABELS and r["value"]]
    if grand:
        rows = grand
```

`_resolve()`가 현재 `corp`를 인자로 안 받으므로 시그니처 확장 필요(`cands` 생성 시점의
`combine_full()`이 이미 `corp`를 알고 있음 — 호출부만 한 줄 추가).

### 3-2. `bs.trade_payables` — `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`(신규)

```python
# ★trade_payables parent(P) override(2026-08-13): node_role='P' 우선을 일반화하면
# 안 된다 — 실측 결과 11,761개 현재-PASS 행이 회귀하고 겨우 32건(5개사)만 고쳐짐
# (대다수 회사는 좁은 '매입채무'만이 정답, _NARROW_PREFER 기존 설계와 부합).
# 원문/report_won 대조로 "부모 총계가 정답"임을 개별 확인한 회사만 등재.
_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS = frozenset({
    "00164502",   # 현대공업
    "00203847",   # 국일신동
    "00210856",   # 코아스
    "00304076",   # 케이엔솔
    "01310269",   # IPARK현대산업개발
})
```

`_CURRENT_STRICT` 사전필터(392~395행) 바로 다음에:

```python
if c == "bs.trade_payables" and corp in _TRADE_PAYABLES_PARENT_OVERRIDE_CORPS:
    parents = [r for r in rows if r.get("node_role") == "P" and r["value"]]
    if parents:
        rows = parents
```

### 3-3. 스코프 밖(별도 트랙, 이번 설계에 포함 안 함)

- **01412822류**(BS에 결합총계 라인 자체가 없어 매입채무+기타채무 미합산): 이 override
  메커니즘으로 못 고침 — 두 canonical(trade_payables + 별도 other_payables류)을 더하는
  새 additive 규칙 필요. 별도 설계.
- **01090471류**(Gate B Track A concept_map이 노트 안 비-매입채무 항목을 잘못 매핑):
  `face_audit.py` 쪽 수정, std_v3/combine.py 범위 밖.
- **trade_payables 149건(F-vs-F, 서로 다른 라벨의 형제 후보)**: 부모/자식 구조가 아니라
  라벨 자체가 다른 계정끼리의 별칭 충돌 — 이 P-preference 메커니즘으로 안 잡힘, 개별
  라벨 조사 필요(범위가 커서 별도 세션 권장).
- **bank/credit_finance 레이어2 커버리지 갭**(신한지주·삼성카드): 총계 라인 자체가
  `report_lines`에 없는 문제, combine.py 선택 로직과 무관.

## 4. 검증 계획(구현 시 필수)

1. **회귀 0 확인**: 이번 실측에 쓴 스크립트(`report_lines` 전수 시뮬레이션)를 재사용해
   `_REVENUE_TOTAL_OVERRIDE_CORPS`/`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`에 등재된
   7개사만 값이 바뀌고, **다른 회사는 단 1건도 안 바뀜**을 코드 실행으로 확인
   (curated set이므로 원리상 자명하지만, `corp in {...}` 조건 오타·스코프 실수 방지
   차원에서 실측 재확인).
2. **pytest**: 기존 `test_combine_current_strict.py` 등 회귀 스위트 통과 확인 +
   두 override 각각에 대한 신규 유닛테스트(등재 회사는 총계/부모 선택, 비등재 회사는
   기존 동작 유지 — 특히 SBI인베스트먼트/현대공업 같은 "child가 정답인" 대조군 포함).
3. **소급 백필**: `[[parser-pipeline-integration-runbook]]` 절차대로 — 이 7개사만
   영향받으므로 `build_std_v3.py --corp 00159254,00340096,00164502,00203847,00210856,
   00304076,01310269 --year-min 1999`로 좁게 재실행 가능(전체 재빌드 불요).
4. **Gate B 재검증**: 위 7개사만 `gateb_audit.py --corp-file <7개사파일> --recheck`로
   재확인 — revenue 8건 + trade_payables 32건 = 40건이 fail_a→pass로 전환되고, 다른
   fail_a/PASS 건수에 변화가 없어야 한다.

## 근거

- 코드: `fin2/layer3/combine.py` 361~455행(`_resolve`)·289~358행(`_reduce_conflict`)
  직접 읽음, `parser.common.account_mapper.get_mapper().map()` 직접 호출로 stage 실측.
- 블랭킷 안전성 실측: `report_lines` 전수(IS revenue 후보 15,926 라벨 중 5,381건 매핑,
  BS trade_payables 후보 11,513 라벨 중 7,713건 매핑) + `face_audit`(source_version='v3',
  08-13 01:08 스냅샷) 대조. `fin2/layer3/industry_profiles.py::apply_revenue_profile()`
  실제 함수를 그대로 호출해 프로파일 오버라이드로 무관해지는 케이스를 제외.
- 대조사례 원문: SBI인베스트먼트(00156910) 2015Q1 별도 — report_lines 직접 조회로
  "수수료수익" 자식이 이미 report_won과 일치함을 확인(자식이 정답인 대조군).
- 5개사 trade_payables 부모-정답 확인은 face_audit.fail_detail.report_won과
  report_lines의 node_role='P' 값이 정확히 일치함을 SQL로 확인(현대공업 등 4개사는
  이번 세션에서 원문 XML까지는 안 내려감 — 코아스 00210856·IPARK현대산업개발
  01310269만 raw XML 직접 확인, 나머지 3개사는 report_won 일치만 확인, 구현 전
  최소 1건씩 원문 재확인 권장).
- `docs/qa/gate_b_fail_a_revenue_tradepayables_triage_2026-08-13.md`(선행 triage) ·
  `docs/PARSING_RULES.md` R15(같은 계열의 이전 수정 사례).
