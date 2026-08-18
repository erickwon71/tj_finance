# Gate B 정상화 ⑥순위 ④ — curated 키 재생성기 배선 설계 (2026-08-18)

> 마스터문서 `docs/plans/gateb_remediation_master_2026-08-17.md` 6순위. 5개 트랙(③①P0+⑤②)
> 전부 종료 후 유일하게 남은 항목. **가치 = 신규 필링 재발 차단.**
> 상태: 설계 초안 — **구현 착수 전 사용자 결정 필요**(CLAUDE.md 정책: 계획 후 대기).

---

## 1. 문제 정의

R15~R33 다수가 "curated 키 집합"으로 구현됐다 — 특정 (corp, fy, period[, basis]) 또는
(rcept_no, statement, basis, table_seq, label) 튜플만 예외 처리하는 방식이다(마스터문서
서두: "수정 방식이 5,090개 키 열거로 흘러 신규 필링에서 같은 부류가 재발"). 이 키 집합은
**전부 특정 시점에 DB의 그 순간 상태를 스캔한 1회성 스크립트의 산출물**이고, 소스코드에
리터럴(dict/frozenset) 또는 `fin2/extract/data/*.json`으로 박혀 있다.

**핵심 문제**: 이후 새 필링이 수집돼도 이 키 집합은 자동으로 안 늘어난다. 같은 회사가
같은 구조로 다음 분기를 공시하면, 그 새 필링은 키 집합 밖이라 **원래 있던 버그가 조용히
재발**하거나(예: EPS/COGS 오판이 다시 combine 되어 값이 틀림), Gate B가 **pending으로
넘겨야 할 행을 fail로 잘못 잡는다**(예: 두산밥캣 FX표시통화).

**실측으로 확인한 임박성** (오늘, 2026-08-18): 6개 활성 기업(01032486 두산밥캣,
00108940/00117212/00143527/00163673, 00356361 LG화학)의 DB상 최신 필링 = 전부 **2026 Q1**.
`docs/plans/gateb_remediation_master_2026-08-17.md` §0: "데일리는 `--download-only`,
2026 H1 약 2,200건 미적재" — 즉 **2026 Q2/H1 백로그가 파싱·적재되는 순간**, 이 6개사의
curated 키가 즉시 stale 해진다. 아직 안 터진 건 우연히 데이터 수집이 밀려서일 뿐이다.

---

## 2. 전수 카탈로그

| 파일 | 변수명 | 키 shape | 규모 | 생성 스크립트 | 대상 R |
|---|---|---|---|---|---|
| `combine.py:55` | `_REVENUE_TOTAL_OVERRIDE_CORPS` | corp 단독(blanket) | 2개사 | `gate_b_faila_combine_stage_rank...` (문서만, 스크립트 미보존) | R16 |
| `combine.py:67` | `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS` | corp 단독(blanket) | 10개사 | 원문 XBRL 수동대조 | R16+확장 |
| `combine.py:103` | `_TRADE_PAYABLES_ADDITIVE_OVERRIDE` | (corp,fy,period) | 6키 | 원문 XBRL 수동대조 | R17 |
| `combine.py:133` | `_SGA_SUBLINE_OVERRIDE_KEYS` | (corp,fy,period) | 46개사/951행 | `generate_sga_subline_override_2026-08-15.py` | R20 |
| `combine.py:860` | `_COGS_ADDITIVE_OVERRIDE` | (corp,fy,period,basis) | 19개사/319키 | `generate_cogs_additive_override_2026-08-15.py` | R21 |
| `combine.py:1966` | `_KGAAP_NI_RECOVERY_KEYS`(JSON) | (corp,fy,period,basis) | 1,840그룹 | `build_ni_recovery_keys_2026-08-16.py` | R29 |
| `report_lines.py:337` | `_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS`(JSON) | (rcept_no,stmt,basis,table_seq,label) | 2,205키/286개사 | `build_eps_curated_override_final...`→`purge_...`→`finalize_...` (3단계) | R28 |
| `face_audit.py:780` | `_FX_PRESENTATION_CURRENCY_KEYS` | (corp,fy,period,basis) | 6키/**1개사** | 원문 수동대조 | R25 |
| `face_audit.py:799` | `_COGS_CONCEPT_MISMATCH_KEYS` | (corp,fy,period,basis) | 14키/4개사 | `probe_gateb_cogs_concept_mismatch...` | R21 Phase3 |
| `face_audit.py:824` | `_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS` | (corp,fy,period,basis) | 1키 | `probe_gateb_reader_concept_gap...` | R23 |
| `industry_profiles.py:198` | `CORP_INDUTY_OVERRIDE` | corp 단독(blanket) | 소수 | 수동 | (업종분류) |

제외: `_PROFILE_VALUE_FALLBACK_KEYS`(`face_audit.py:1012`)는 필드명 allow-list라 corp/기간과
무관 — 재생성 대상 아님.

---

## 3. 재발 위험 등급 (핵심 판단)

키 shape이 **corp 단독(blanket)**이냐 **(corp, fy, period[, basis]) 튜플**이냐로 위험이
완전히 갈린다.

### Tier 0 — 위험 없음 (blanket, 이미 forward-safe)
`_REVENUE_TOTAL_OVERRIDE_CORPS`, `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`,
`CORP_INDUTY_OVERRIDE` — corp만 등재돼 있어 그 회사의 **모든 미래 필링에 자동 적용**된다.
재생성기 불필요.

### Tier 1 — 높음 (period-scoped + 활성 기업 + 최신 커버기간이 데이터 지평선과 일치)
`_FX_PRESENTATION_CURRENCY_KEYS`(두산밥캣), `_COGS_CONCEPT_MISMATCH_KEYS`(4개사),
`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`(LG화학 등 5개사) — **§1에서 실측한 대로 6개사 전부
2026Q1이 최신**. 2026H1 백로그 적재 즉시 재발.

### Tier 2 — 중간 (period-scoped, 최신 커버기간이 예전이라 다음 분기 도래까지 시간 있음)
`_SGA_SUBLINE_OVERRIDE_KEYS`, `_COGS_ADDITIVE_OVERRIDE` — 46개사/19개사 중 상당수가 이미
상장폐지·과거 특정연도 이력이지만, **전부 재조사하지 않으면 어느 corp이 아직 활성인지
모른다**(활성 여부 = 다음 절차 1단계로 확인 필요).

### Tier 3 — 사실상 없음 (닫힌 모집단)
`_EPS_KGAAP_HEADLINE_NOT_EPS_KEYS`, `_KGAAP_NI_RECOVERY_KEYS`,
`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS` — K-GAAP 구서식 라벨은 K-IFRS 전면도입(2011~2012)
이전 필링에서만 나타난다. 이미 공시된 과거 문서 집합은 유한하고 안 변하므로, **신규
공시가 이 패턴을 다시 만들 가능성은 사실상 0**. 재생성 불필요 — 문서에 "닫힌 모집단"으로
명기만 하면 된다.

---

## 4. 핵심 발견 — 기계적 forward-carry(마지막 키를 다음 기간으로 그냥 연장)는 안전하지 않다

`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`의 코드 주석(`combine.py:83-95`)이 이미 실측으로
경고하고 있다: 최초 구현을 **corp 단독 키**로 5개사 전체 이력에 적용했더니, 목표 기간은
고쳐졌지만 **같은 회사의 과거 모든 분기가 대규모로 회귀**했다 — LG화학 2010년 연결
report_won=1.30조인데 두 라인 합=2.12조, 즉 "두 라인 합=report_won" 관계가 **같은 회사
안에서도 기간마다 성립/불성립이 갈린다.**

→ 결론: "이 회사는 이 패턴이니 다음 분기도 그렇겠지"라는 **무검증 자동연장은 이 override
family 자체의 존재 이유(period-scoped로 좁힌 이유)와 정면으로 모순**된다. 재생성기는
캐시를 늘리는 게 아니라 **원 검증 로직을 새 기간에 대해 다시 돌려 재확인**해야 한다.

---

## 5. 설계 방향 (제안)

### 5-A. 탐지 스크립트 도입 — "재검증까지, 자동 반영은 안 함"

각 override family의 원 생성 스크립트를 **재사용 가능한 함수**로 승격하고
(`fin2/audit/curated_key_scan.py` 신설 제안), 다음을 수행:

1. family별로 이미 등재된 corp 목록에서 **`max(fy,period)` 초과 필링이 DB에 있는지** 스캔
   (corp 목록 자체는 이미 curated라 재확인 불필요 — 새 corp 유입 여부는 별도 §5-B).
2. 있으면 그 신규 필링에 대해 **원 검증 로직 그대로**(예: additive override는 "후보 라벨
   합 == report_won" 항등식, COGS concept mismatch는 "report_won == is.cogs + is.sga")를
   재실행 — 이건 이미 각 스크립트에 구현돼 있던 로직을 그대로 재사용(신규 로직 아님).
3. 항등식이 성립하면 **candidate**로, 안 성립하면 **원문 XBRL 직접대조 필요 항목**으로
   분류해 리뷰 큐(`docs/qa/curated_key_regen_candidates_<날짜>.json`)에 적재.
4. **자동 코드 반영 없음.** 사용자/Claude가 리뷰 큐를 원문대조로 확인 후 기존 방식대로
   수동으로 리터럴에 추가 + `docs/PARSING_RULES.md` 갱신 + 회귀 커밋 — 지금까지의 R15~R33
   워크플로우와 동일, 탐지 단계만 자동화.

**자동 반영을 안 하는 이유**: `feedback-verify-against-source` 메모리("집계로 끝내지 말고
원문추적") + §4의 실측(항등식이 성립해도 우연일 수 있다는 보장 없음, LG화학처럼 회사
내부에서도 갈림) — 항등식 통과를 "확인됐다"로 승격하려면 매 override family 최초 도입 때
했던 것과 같은 강도의 원문대조가 최소 1회는 필요하다. 이걸 건너뛰면 R23이 실제로 겪은
"진짜 버그가 가짜 PASS로 가려짐"류 사고가 재생성기를 통해 반복될 수 있다.

### 5-B. 배선 지점

`docs/runbook_new_parser_pipeline_integration.md`의 기존 패턴을 따른다:

- **데일리 자동 실행 아님.** collect_new.py 두 call site에 넣지 않는다 — Tier 1/2 스캔은
  가볍지만(등재 corp 수십 개 한정) 결과가 "반영 대기 큐"일 뿐이라 매일 돌 필요가 없고,
  자동 배선하면 무인 상태로 큐만 쌓이다 아무도 안 볼 위험(기존 gapfill 야간잡과 다른 점 —
  gapfill은 최종 결과가 자기해제되는 백필이지만 이건 판단이 필요한 후보 목록).
- 제안: **월 1회 수동 실행**(또는 2026H1 백로그 적재 완료 시점처럼 "새 데이터 뭉치가
  들어온 직후"에 1회) + `docs/plans/gateb_remediation_master_2026-08-17.md` 같은 진행표에
  실행 이력 기록. 완전 자동화는 이번 단계에서 보류(§6 결정사항 1).

**★ daily pipeline과의 관계 (2026-08-18 확인)**: 이 트랙은 `collect_new.py`에 안 걸지만,
재발 위험의 실제 트리거는 daily pipeline의 상태와 묶여 있다. launchd plist
(`com.tjfinance.collect.plist`)를 확인한 결과 현재 데일리는 `--download-only`가 실제로
걸려 있어 **파싱/표준화(계층2·3)/Gate B가 전부 생략**된다(`collect_new.py:781-787`) —
새 필링은 매일 원문으로 쌓이지만 std_v3/Gate B 반영은 수동이다. §1에서 실측한 "6개사
전부 2026Q1이 최신"이 아직 재발하지 않은 이유가 이거다: 백필·표준화를 수동으로 아직 안
돌렸을 뿐, 원문 자체는 이미 도착해 있을 수 있다.

plist 주석에 이미 이후 계획이 적혀 있다: "파싱/표준화/계층2·3 적재는 **계층3 재설계 완료
후 이 플래그를 빼면 되살아난다**"(`docs/plans/collection_pipeline_restore_2026-07-31.md`
§5.1 · Phase 5). 그 시점부터는 신규 필링이 거의 매일 자동으로 std_v3/Gate B까지 들어가
재발 주기가 "몰아서 가끔"에서 "매일"로 바뀐다 — **`--download-only` 해제는 이 트랙(탐지
주기 포함)의 재검토 트리거로 취급한다.**

### 5-C. 회귀 게이트

- family별 함수를 신설할 때, **현재 코드에 박힌 리터럴을 그대로 재현하는지**를 회귀
  테스트로 고정(`fin2/tests/test_curated_key_scan.py`) — 즉 "지금 시점 DB로 스캔 함수를
  돌리면 §2 카탈로그의 기존 키 집합과 정확히 일치"를 먼저 증명한 뒤에야 "신규 후보 탐지"
  기능을 신뢰할 수 있다(동치성 증명이 게이트라는 ③ 트랙과 같은 원칙).
- `pytest tests/ fin2/tests/` 기준선 유지, Gate B fail_a 증가 0, 단조성 위반 0(마스터문서
  §2 공통 게이트 그대로 적용).

---

## 6. 미결정 — 사용자 결정 필요

1. **Tier 2(SGA/COGS additive 46+19개사) 범위를 이번 트랙에 포함할지, Tier 1(6개사)만 먼저
   할지** — Tier 2는 어느 corp이 활성인지부터 재조사해야 해서 작업량이 커짐.
2. **탐지 실행 주기** — 월 1회 수동 vs 2026H1 백로그 적재 직후 1회성 vs 그 외.
3. **리뷰 큐 형식** — JSON 파일로 충분한지, 아니면 DB 테이블(`curated_key_candidates`)로
   둬서 이력 추적을 할지.
4. **`--download-only` 해제 시점 재검토** — §5-B에서 확인한 대로, 계층3 재설계 완료 후
   daily pipeline이 파싱/표준화까지 자동화되면 재발 주기가 "몰아서 가끔"에서 "매일"로
   바뀐다. 이 트랙을 그 전에 먼저 마칠지, 아니면 `--download-only` 해제와 묶어서(같은
   타이밍에) 재생성기 배선을 같이 넣을지 — 결정 필요.

---

## 참고

- 마스터문서: `docs/plans/gateb_remediation_master_2026-08-17.md`
- 파이프라인 배선 규칙: `docs/runbook_new_parser_pipeline_integration.md`
- 관련 R: R16~R21, R23, R25, R28, R29 (`docs/PARSING_RULES.md`)
- 원본대조 원칙: 메모리 `feedback-verify-against-source`
