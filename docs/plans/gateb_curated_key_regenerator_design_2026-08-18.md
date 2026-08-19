# Gate B 정상화 ⑥순위 ④ — curated 키 재생성기 배선 설계 (2026-08-18)

> 마스터문서 `docs/plans/gateb_remediation_master_2026-08-17.md` 6순위. 5개 트랙(③①P0+⑤②)
> 전부 종료 후 유일하게 남은 항목.
> 상태: 설계 초안 — **구현 착수 전 사용자 결정 필요**(CLAUDE.md 정책: 계획 후 대기).

> **개정 이력**
> - 2026-08-18 rev1 (초안)
> - 2026-08-18 **rev2 — 사용자 지적으로 §3·§5-A 전면 재작성.** rev1 은 탐지 모집단을
>   "이미 등재된 corp 목록"으로 좁혔는데, 그러면 **미등재/신규 기업에서 같은 패턴이
>   나와도 영영 안 잡힌다** — 열거식으로 고쳐서 생긴 문제를 탐지기에서 한 단계 위로
>   그대로 반복하는 구조였다. 실측 결과 **원 생성 스크립트 다수는 이미 전수 패턴
>   스캔**이었고(§2), rev1 이 없던 제약을 새로 넣은 것이었다. §1 의 가치 서술도
>   과장이 있어 정정(Gate B 전수감사가 이미 corp 무관 그물임 — §1-B).

---

## 1. 문제 정의

### 1-A. 열거식 수정의 stale 문제

R15~R33 다수가 "curated 키 집합"으로 구현됐다 — 특정 (corp, fy, period[, basis]) 또는
(rcept_no, statement, basis, table_seq, label) 튜플만 예외 처리하는 방식이다(마스터문서
서두: "수정 방식이 5,090개 키 열거로 흘러 신규 필링에서 같은 부류가 재발"). 이 키 집합은
**전부 특정 시점에 DB의 그 순간 상태를 스캔한 1회성 스크립트의 산출물**이고, 소스코드에
리터럴(dict/frozenset) 또는 `fin2/extract/data/*.json`으로 박혀 있다.

**핵심 문제**: 이후 새 필링이 수집돼도 이 키 집합은 자동으로 안 늘어난다. 같은 회사가
같은 구조로 다음 분기를 공시하면, 그 새 필링은 키 집합 밖이라 **원래 있던 버그가 조용히
재발**하거나(예: EPS/COGS 오판이 다시 combine 되어 값이 틀림), Gate B가 **pending으로
넘겨야 할 행을 fail로 잘못 잡는다**(예: 두산밥캣 FX표시통화).

**실측으로 확인한 임박성** (2026-08-18): 6개 활성 기업(01032486 두산밥캣,
00108940/00117212/00143527/00163673, 00356361 LG화학)의 DB상 최신 필링 = 전부 **2026 Q1**.
같은 날 실측한 적재 현황:

| 항목 | 실측값 |
|---|---|
| 2026-08 접수 필링(반기보고서) | 2,628건 다운로드 완료 |
| 그중 `report_lines` 파싱됨 | **406건** |
| `std_financials_v3` 2026 H1 기업수 | **402개사** (정상이면 ~2,500) |

즉 **2026 반기보고서 약 2,200건이 원문으로는 이미 도착했는데 표준화 전 대기 중**이고
(데일리가 `--download-only`), 이게 적재되는 순간 위 6개사의 curated 키가 즉시 stale 해진다.
아직 안 터진 건 우연히 표준화가 밀려서일 뿐이다.

### 1-B. ★ 이 트랙의 가치 범위 — 과장하지 말 것 (rev2 정정)

**④가 없어도 신규 기업에 대해 눈이 먼 상태는 아니다.** Gate B 전수 감사 자체가 corp 와
무관한 그물이라, 등재 안 된 회사가 같은 패턴으로 공시하면 `fail_a` 로 뜬다 — R16~R33 이
전부 그렇게 발견된 것들이다.

따라서 ④의 실제 가치는 **"못 잡던 걸 잡는 것"이 아니라**:

1. Gate B fail 을 "이건 LG화학 additive 패턴 재발" 로 **자동 분류**해, 매번 처음부터
   원인을 다시 캐는 triage 비용을 없앤다.
2. **조용한 재발**(Gate B 가 fail 을 안 내고 값만 틀리는 경우)을 잡는다 — override 가
   값을 바꾸는 family 는 대부분 report_won 과 어긋나 fail 로 뜨지만, `face_audit.py` 쪽
   **제외 키**(FX표시통화·concept mismatch·zero-match)는 반대로 **fail 을 억누르는**
   방향이라 신규 대상에서 오탐이 늘어나는 형태로 나타난다.
3. 등재 corp 의 다음 분기를 **원 검증 로직으로 재확인**해 forward 안전성을 판단한다(§4).

rev1 은 이 트랙을 "신규 필링 재발 차단"의 유일한 수단처럼 썼는데, 정확히는
**Gate B 전수감사의 triage 보조 + 제외 키 방향의 사각 보완**이다.

---

## 2. 전수 카탈로그

`생성 모집단` 열 = 원 생성 스크립트가 **전체 DB를 패턴으로 훑는지**, 아니면 **미리 정해진
corp 목록에 묶여 있는지**. rev2 의 핵심 판단 근거다.

| 파일 | 변수명 | 키 shape | 규모 | 생성 스크립트 | 생성 모집단 | 대상 R |
|---|---|---|---|---|---|---|
| `combine.py:55` | `_REVENUE_TOTAL_OVERRIDE_CORPS` | corp 단독(blanket) | 2개사 | (문서만, 스크립트 미보존) | ? | R16 |
| `combine.py:67` | `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS` | corp 단독(blanket) | 10개사 | 원문 XBRL 수동대조 | 수동 | R16+확장 |
| `combine.py:103` | `_TRADE_PAYABLES_ADDITIVE_OVERRIDE` | (corp,fy,period) | 6키 | 원문 XBRL 수동대조 | 수동 | R17 |
| `combine.py:133` | `_SGA_SUBLINE_OVERRIDE_KEYS` | (corp,fy,period) | 46개사/951행 | `generate_sga_subline_override_2026-08-15.py` | **전수**(`:31` corp 조건 없음) | R20 |
| `combine.py:860` | `_COGS_ADDITIVE_OVERRIDE` | (corp,fy,period,basis) | 19개사/319키 | `generate_cogs_additive_override_2026-08-15.py` | **전수**(`:46` corp 조건 없음) | R21 |
| `combine.py:1966` | `_KGAAP_NI_RECOVERY_KEYS`(JSON) | (corp,fy,period,basis) | 1,840그룹 | `build_ni_recovery_keys_2026-08-16.py` | rcept 입력목록 | R29 |
| `report_lines.py:337` | `_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS`(JSON) | (rcept_no,stmt,basis,table_seq,label) | 2,205키/286개사 | `build_eps_curated_override_final...`→`purge_...`→`finalize_...` (3단계) | 3단계 파이프 | R28 |
| `face_audit.py:780` | `_FX_PRESENTATION_CURRENCY_KEYS` | (corp,fy,period,basis) | 6키/**1개사** | 원문 수동대조 | 수동 | R25 |
| `face_audit.py:799` | `_COGS_CONCEPT_MISMATCH_KEYS` | (corp,fy,period,basis) | 14키/4개사 | `probe_gateb_cogs_concept_mismatch...` | **corp 묶임**(`:40` 19개사 파일 + `:34` `_KNOWN_CORPS` 4개사) | R21 Phase3 |
| `face_audit.py:824` | `_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS` | (corp,fy,period,basis) | 1키 | `probe_gateb_reader_concept_gap...` | **전수**(`:123` `FROM face_audit`) | R23 |
| `industry_profiles.py:198` | `CORP_INDUTY_OVERRIDE` | corp 단독(blanket) | 소수 | 수동 | 수동 | (업종분류) |

제외: `_PROFILE_VALUE_FALLBACK_KEYS`(`face_audit.py:1012`)는 필드명 allow-list라 corp/기간과
무관 — 재생성 대상 아님.

**★ rev2 실측**: `generate_cogs_additive_override_2026-08-15.py:46` /
`generate_sga_subline_override_2026-08-15.py:31` 의 모집단 쿼리에는 corp 조건이 없다 —

```sql
FROM report_lines
WHERE statement='IS' AND col_index=0 AND node_role='P' AND label_raw LIKE '%영업비용%'
```

전체 DB를 패턴으로 훑은 뒤 항등식으로 "고쳐야 하는 것"만 골라내는 구조다. 즉
**신규 기업을 걸러내는 능력이 원래부터 있었고, rev1 설계가 그걸 버린 것**이었다.

---

## 3. 재발 위험 등급 (rev2 전면 재작성)

rev1 은 "등재 corp 이 활성인가"만 축으로 삼아 **신규/미등재 기업 축이 통째로 빠져 있었다.**
rev2 는 두 축으로 나눈다.

- **축 A — forward(등재 corp 의 다음 기간)**: 이미 등재된 회사가 새 분기를 공시했을 때.
- **축 B — lateral(미등재/신규 corp)**: 등재된 적 없는 회사에서 같은 패턴이 나왔을 때.
  ← rev1 누락분

### 실측 모집단 대비 등재율 (왜 축 B 가 실재하는가)

`%영업비용%` P-line 패턴 전수 스캔(2026-08-18 실측, **44초** / 12,436행):

| 항목 | 값 |
|---|---|
| 패턴 보유 기업 | **393개사** |
| `_SGA_SUBLINE_OVERRIDE_KEYS` 등재 | 46개사 |
| `_COGS_ADDITIVE_OVERRIDE` 등재 | 19개사 |

나머지 300개사 이상은 **"2026-08-15 시점 데이터에서는 항등식상 고칠 필요 없음"으로 판정된
것일 뿐**이고, 그 판정은 그날 기준이다. 구조 변경·정정공시·신규 상장으로 언제든 넘어올 수
있다 — 축 B 는 이론이 아니라 300개사짜리 실재 모집단이다.

| 등급 | family | 축 A(forward) | 축 B(lateral) | 조치 |
|---|---|---|---|---|
| **T0** blanket | `_REVENUE_TOTAL_OVERRIDE_CORPS`, `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`, `CORP_INDUTY_OVERRIDE` | 없음(corp 단독 = 미래 자동적용) | **있음** — 새 회사는 등재돼야 적용됨 | 축 B 만 스캔 |
| **T1** 임박 | `_FX_PRESENTATION_CURRENCY_KEYS`, `_COGS_CONCEPT_MISMATCH_KEYS`, `_TRADE_PAYABLES_ADDITIVE_OVERRIDE` | **높음** — 6개사 전부 2026Q1 최신, H1 적재 즉시 | **있음** — 셋 다 수동/corp묶임 생성이라 lateral 탐지 이력 자체가 없음 | 전수 스캔 신규 작성 |
| **T2** period-scoped | `_SGA_SUBLINE_OVERRIDE_KEYS`, `_COGS_ADDITIVE_OVERRIDE` | 중간 — 활성 corp 재조사 필요 | **있음** — 393개사 중 65개사만 등재 | 원 스크립트 전수 재실행 |
| **T3** 닫힌 모집단 | `_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS`, `_KGAAP_NI_RECOVERY_KEYS`, `_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS` | 사실상 없음 | **사실상 없음** | 문서에 "닫힌 모집단" 명기만 |

T3 근거(rev1 유지): K-GAAP 구서식 라벨은 K-IFRS 전면도입(2011~2012) 이전 필링에서만
나타난다. 이미 공시된 과거 문서 집합은 유한하고 안 변하므로 **신규 공시가 이 패턴을 다시
만들 가능성은 사실상 0** — 축 A·B 둘 다 해당 없음.

★ T0 의 축 B 가 "없음"이 아니라 "있음"인 점에 주의: blanket 은 **등재된 회사에 대해서만**
forward-safe 하다. rev1 은 T0 를 "재생성기 불필요"로 닫았는데, 새 회사가 같은 이유로
override 가 필요해지는 경우는 그대로 남는다.

---

## 4. 핵심 발견 — 기계적 forward-carry(마지막 키를 다음 기간으로 그냥 연장)는 안전하지 않다

(rev1 유지 — 이 절의 결론은 rev2 에서도 그대로다.)

`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`의 코드 주석(`combine.py:83-95`)이 이미 실측으로
경고하고 있다: 최초 구현을 **corp 단독 키**로 5개사 전체 이력에 적용했더니, 목표 기간은
고쳐졌지만 **같은 회사의 과거 모든 분기가 대규모로 회귀**했다 — LG화학 2010년 연결
report_won=1.30조인데 두 라인 합=2.12조, 즉 "두 라인 합=report_won" 관계가 **같은 회사
안에서도 기간마다 성립/불성립이 갈린다.**

→ 결론: "이 회사는 이 패턴이니 다음 분기도 그렇겠지"라는 **무검증 자동연장은 이 override
family 자체의 존재 이유(period-scoped로 좁힌 이유)와 정면으로 모순**된다. 재생성기는
캐시를 늘리는 게 아니라 **원 검증 로직을 새 기간에 대해 다시 돌려 재확인**해야 한다.

**rev2 보강**: 이 발견은 축 B 에도 그대로 적용된다. "미등재 corp 에서 항등식이 성립했다"는
것도 자동 등재 근거가 못 된다 — 성립/불성립이 기간마다 갈리는 관계라면, 처음 걸린 그
기간에서 성립한 것도 우연일 수 있다. 축 B 산출물 역시 **후보**일 뿐이다.

---

## 5. 설계 방향 (제안)

### 5-A. 전수 패턴 스캔 → 3분류 (rev2 전면 재작성)

각 override family 의 원 생성 스크립트를 **재사용 가능한 함수**로 승격하고
(`fin2/audit/curated_key_scan.py` 신설 제안), family 별로 다음을 수행한다.

**모집단 = corp 목록이 아니라 패턴.** §2 의 전수 쿼리를 그대로 쓴다(이미 전수인 family 는
그대로 재사용, T1 의 수동/corp묶임 family 는 전수 쿼리를 새로 작성 — §5-D).

산출물을 **3분류**한다:

| 분류 | 조건 | 의미 | 처리 |
|---|---|---|---|
| **① 일치** | 스캔 결과 == 등재된 키 | 정상 | 로그만. **이게 곧 §5-C 동치성 증명** |
| **② forward 후보** | 등재 corp 인데 등재 안 된 새 기간 | 축 A 재발 | 리뷰 큐 |
| **③ lateral 후보** | 등재된 적 없는 corp | 축 B — **rev1 누락분** | 리뷰 큐 |
| (④ 소멸) | 등재된 키인데 스캔에 안 잡힘 | 정정공시로 구조가 바뀜 | 리뷰 큐(제거 후보) |

각 후보는 **원 검증 로직 그대로**(예: additive override 는 "후보 라벨 합 == report_won"
항등식, COGS concept mismatch 는 "report_won == is.cogs + is.sga") 재실행해 판정하고,
성립/불성립을 리뷰 큐(`docs/qa/curated_key_regen_candidates_<날짜>.json`)에 적재한다.

**자동 코드 반영 없음.** 사용자/Claude 가 리뷰 큐를 원문대조로 확인 후 기존 방식대로 수동
등재 + `docs/PARSING_RULES.md` 갱신 + 회귀 커밋 — 지금까지의 R15~R33 워크플로우와 동일,
**탐지 단계만 자동화**한다.

**자동 반영을 안 하는 이유**: `feedback-verify-against-source` 메모리("집계로 끝내지 말고
원문추적") + §4 의 실측(항등식 성립이 우연일 수 있음, 같은 회사 안에서도 갈림) — 항등식
통과를 "확인됐다"로 승격하려면 매 override family 최초 도입 때 했던 것과 같은 강도의
원문대조가 최소 1회는 필요하다. 이걸 건너뛰면 R23 이 실제로 겪은 "진짜 버그가 가짜 PASS로
가려짐"류 사고가 재생성기를 통해 반복될 수 있다.

**비용**: 전수라고 비싸지 않다. §3 실측대로 대표 패턴 1개 family 전수 스캔이 **44초**
(12,436행/393개사). rev1 이 "등재 corp 수십 개 한정이라 가볍다"고 쓴 건 불필요한 절약이었다.

### 5-B. 배선 지점

`docs/runbook_new_parser_pipeline_integration.md`의 기존 패턴을 따른다.

**rev2 변경 — 달력 기준 수동 실행이 아니라 이벤트 기준 자동 실행.** rev1 은 "월 1회 수동"을
제안했으나 사용자가 수동 주기의 불편함을 지적했고, 타당하다. 스캔은 읽기전용이고 44초라
자동으로 돌려도 위험이 없다. 문제는 주기가 아니라 **"큐만 쌓이고 아무도 안 보는 것"**이었고,
그건 알림으로 푸는 게 맞다.

- **표준화가 실제로 일어나는 지점에 건다** — `scripts/collect_new.py` 의 **두 call site**
  (`:693` `--standardize-only` 재개 · `:794` 메인). 이러면 데일리가 자동으로 돌든 사용자가
  반기 백로그를 손으로 돌리든, **새 데이터가 표준화되는 순간 탐지도 같이 실행**된다.
  달력 기준 launchd 잡(매일/매주)은 새 데이터가 없는 날 헛돌기만 하므로 쓰지 않는다.
- **후보 0건이면 조용히**, 1건 이상이면 알림 — 알림 수단은 §6 결정사항 1.
  ※ 현재 이 프로젝트에는 알림 코드가 **하나도 없다**(2026-08-18 확인: `scripts/`·
  `collector/`·`fin2/`·`deploy/` 에 osascript/terminal-notifier/mail 전무, 결과는 전부
  `logs/*.log` 파일로만 남음). 자동 배선하려면 알림을 같이 만들어야 한다.

**★ daily pipeline 과의 관계 (2026-08-18 확인)**: 재발 위험의 실제 트리거는 daily pipeline
상태와 묶여 있다. launchd plist(`com.tjfinance.collect.plist`)를 확인한 결과 현재 데일리는
`--download-only` 가 실제로 걸려 있어 **파싱/표준화(계층2·3)/Gate B 가 전부 생략**된다
(`collect_new.py:781-787`) — 새 필링은 매일 원문으로 쌓이지만 std_v3/Gate B 반영은 수동이다.
§1-A 의 "6개사 전부 2026Q1 최신"이 아직 재발하지 않은 이유가 이거다.

plist 주석에 이후 계획이 적혀 있다: "파싱/표준화/계층2·3 적재는 **계층3 재설계 완료 후 이
플래그를 빼면 되살아난다**"(`docs/plans/collection_pipeline_restore_2026-07-31.md` §5.1 ·
Phase 5). 그 시점부터는 신규 필링이 거의 매일 자동으로 std_v3/Gate B 까지 들어가 재발
주기가 "몰아서 가끔"에서 "매일"로 바뀐다 — **`--download-only` 해제는 이 트랙의 재검토
트리거로 취급한다.** 단 §5-B 의 이벤트 기준 배선을 쓰면 해제 전/후 모두 같은 코드로
동작한다(해제 시 자동으로 매일 돌게 됨).

※ 참고: 메모리에 "갭채우기 야간 launchd(00:01)" 기록이 있으나, 실제
`~/Library/LaunchAgents/` 에는 `com.tjfinance.collect` **하나뿐**이다(2026-08-18 확인).

### 5-C. 회귀 게이트

- §5-A 의 **분류 ①(일치)이 곧 동치성 증명**이다 — "지금 시점 DB 로 스캔 함수를 돌리면 §2
  카탈로그의 기존 키 집합과 정확히 일치"를 먼저 증명한 뒤에야 ②③ 탐지를 신뢰할 수 있다
  (동치성 증명이 게이트라는 ③ 트랙과 같은 원칙). 이를 회귀 테스트로 고정
  (`fin2/tests/test_curated_key_scan.py`).
- ★ 단, T1 family 는 원 생성이 **수동/corp묶임**이라 동치성 증명이 자명하지 않다 —
  새로 쓴 전수 쿼리가 기존 수동 키를 **재현하지 못할 수 있고**, 그 경우 "쿼리가 틀렸는지 /
  수동 키가 불완전했는지"를 원문대조로 가려야 한다(§5-D).
- `pytest tests/ fin2/tests/` 기준선 유지(현재 560), Gate B fail_a 증가 0, 단조성 위반 0
  (마스터문서 §2 공통 게이트 그대로 적용).

### 5-D. T1 family 전수 쿼리 신규 작성 (rev2 신설)

T1 3종은 전수 스캔 자산이 없어 **새로 써야 한다.** 난이도 순:

1. `_TRADE_PAYABLES_ADDITIVE_OVERRIDE` — 검증 로직이 명확("후보 라인 합 == report_won").
   T2 의 additive 스캔과 같은 형태라 재사용 가능. 가장 쉬움.
2. `_COGS_CONCEPT_MISMATCH_KEYS` — 기존
   `probe_gateb_cogs_concept_mismatch_2026-08-15.py` 를 corp 묶임(`:34` `_KNOWN_CORPS`,
   `:40` 19개사 파일)에서 풀어 `face_audit` 의 cogs fail_a 전수로 돌리면 된다. 항등식
   ("report_won == is.cogs + is.sga")은 이미 구현돼 있음.
3. `_FX_PRESENTATION_CURRENCY_KEYS` — **가장 어려움.** "표시통화가 원화가 아님"은 항등식이
   아니라 원문 표기 판정이라, 자동 탐지 규칙 자체를 새로 정의해야 한다. 후보:
   재무제표 헤더의 통화 표기(`fx-declared-statements` 메모리 규약)를 읽어 KRW 아닌 것을
   전수로 뽑기. **이건 별도 조사가 필요하며, 이번 트랙 범위에 넣을지는 §6 결정사항 2.**

---

## 6. 결정사항 (2026-08-19 확정)

1. **알림 수단** — **(c) macOS 알림 팝업(osascript) + 로그 요약 둘 다.** 팝업으로 즉시
   인지, 로그로 나중에 다시 확인 가능하게.
2. **T1-3 `_FX_PRESENTATION_CURRENCY_KEYS` 를 이번 범위에 넣을지** — **분리.** 1차
   구현은 T1 쉬운 2종(trade_payables additive, cogs concept mismatch) + T2 만. T1-3은
   탐지 규칙 신설(원문 표시통화 판정)이 필요해 별도 트랙으로 이후 진행.
3. **T0 축 B(신규 회사가 blanket override 대상이 되는 경우) 를 이번 범위에 넣을지** —
   **분리.** 수동 작성 부담이 커 1차 구현 범위 밖, 이후 별도 트랙.
4. **리뷰 큐 형식** — **DB 테이블(`curated_key_candidates`).** 이력 추적(발견 시점·처리
   상태) 목적, 프로젝트 전체가 DB 중심이라 일관성도 맞음.
5. **2026 반기 백로그(약 2,200건) 적재 시점** — ✅ 8/18 세션에서 이미 적재 완료로 해소
   (결정 불필요, `h1-2026-backlog-load-2026-08-18` 메모리 참고).

**1차 구현 범위 확정**: T1 쉬운 2종 + T2 전수 탐지 스캔, `collect_new.py` 두 call site
배선(§5-B), 후보 0건이면 조용히·1건 이상이면 macOS 팝업+로그, 결과는
`curated_key_candidates` 테이블에 적재.

---

## 참고

- 마스터문서: `docs/plans/gateb_remediation_master_2026-08-17.md`
- 파이프라인 배선 규칙: `docs/runbook_new_parser_pipeline_integration.md`
- 관련 R: R16~R21, R23, R25, R28, R29 (`docs/PARSING_RULES.md`)
- 원본대조 원칙: 메모리 `feedback-verify-against-source`
