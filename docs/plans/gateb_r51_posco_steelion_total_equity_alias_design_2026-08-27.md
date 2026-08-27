# Gate B fail_a 클러스터C — C-1: 포스코스틸리온 `total_equity` alias 오귀속 설계 (R51, 2026-08-27)

상태: **✅ 완료(단, §1~§3의 최초 설계는 구현 중 반증됨 — §6 "실제 구현" 참고).**
[[gateb-482-backlog-cluster-c-triage-2026-08-27]] 유형1 1순위 후보를 원문 대조로 확정하고
아래 §1~§3(alias 통째 제거)을 승인받아 구현했으나, 00369657(리노공업)에서 즉시 회귀가
드러나 원상복구 후 진짜 근본원인(`combine.py::_reduce_conflict()`의 depth 휴리스틱)을
재조사·재구현했다. `docs/PARSING_RULES.md` R51 등재 완료. DB 전체 fail_a 170→156(−14).

**이 문서는 조사 과정 기록으로 원문 그대로 남긴다 — §1~§3은 "왜 alias 제거가 틀렸는지"의
근거이지 실제 적용된 수정이 아니다. 실제 적용된 수정은 §6 참고.**

배경: [[gateb-482-backlog-cluster-ab-rootcause-2026-08-27]](R50)로 fail_a 482→170 해소 후
남은 클러스터C 트리아지 결과, 포스코스틸리온(00155258) `total_equity` 14건이 원인이 가장
명확하고 범위가 작아 1순위 착수 후보로 지정됨.

---

## 1. 근본원인 (원문 대조로 확정)

`account_maps/bs_accounts.py:285-289`:

```python
"bs.total_equity": [
    "자본총계", "자본 합계", "자본의 합계", "자본 총계",
    "총자본",
],
```

"총자본"이 `bs.total_equity`의 별칭으로 등록돼 있다. 그러나 원문에서 "총자본"은
**자본이 아니라 "부채와 자본의 합계"(total assets와 항등)를 가리키는 라벨**이다 — 순수
자산=자본조달총액이라는 관용적 회계 용어이지 지분(equity)이 아니다.

**실측 근거** (`00155258` FY2024 사업보고서, rcept `20250408001924`,
`/Volumes/dart_data/raw_report/KOSPI/00155258_포스코스틸리온/annual/2024/20250408001924.xml`):

같은 BS 요약표 안에 두 줄이 연속으로 존재한다(연결 기준, 라인 4810~4832):

| 순서 | 라벨(원문) | ENG(XBRL) | ACODE | 값(CFY2024) |
|---|---|---|---|---|
| 1 | "자본총계" | `Total equity` | `ifrs-full_Equity` | 385,299,788,248 |
| 2 | "총자본" | `Total equity and liabilities` | `ifrs-full_EquityAndLiabilities` | 556,803,723,173 |

DB(`std_financials_v3`)의 `total_equity`는 556,803,723,173 — 즉 **"총자본"(2번줄, 오답)이
"자본총계"(1번줄, 정답)를 덮어쓴 채 채택**돼 있다. 같은 필링의 `total_assets`도
556,803,723,173으로, `total_equity == total_assets`가 정확히 성립 — "총자본"이 자산총계와
항등이라는 원문 라벨 의미와 일치한다.

```
corp_code | fiscal_year | fiscal_period | statement_type | total_assets  | total_equity
00155258  |        2024 | FY            | consolidated    | 556803723173  | 556803723173  ← 버그
00155258  |        2024 | FY            | separate        | 530859806774  | 530859806774  ← 버그
00155258  |        2025 | FY/H1/Q1/Q3   | consolidated/separate (7개 period)              ← 전부 동일 패턴
```

**두 줄이 왜 충돌하는가**: `account_mapper.map()`은 정확일치 매칭만 하고 어느 한 줄을
선택하는 tiebreak은 하지 않는다(별개 alias 문자열이라 애초에 같은 매칭 슬롯을 다투지 않음).
문제는 downstream 셀 채택 단계(`fin2/layer3/combine.py`)에서 같은 canonical
(`bs.total_equity`)로 매핑된 두 후보 라인 중 **테이블상 나중에 나오는 줄("총자본")이
채택**된 것 — R39(`_resolve()` 라벨-표현 드리프트, `docs/PARSING_RULES.md:2116`)와 같은
클래스의 "동일 canonical에 복수 후보, tiebreak 오채택" 패턴이다. 다만 R39는 라벨 표기가
갈린 정정본 케이스였고, 이번은 **애초에 "총자본" alias 등록 자체가 개념적으로 틀렸다** —
어느 tiebreak 로직을 쓰든 "총자본"이 `bs.total_equity` 후보 풀에 들어가는 것 자체가 잘못.

## 2. 영향 범위 (전사 스캔 결과, 재확인)

`account_maps/bs_accounts.py`에서 "총자본" 라벨이 실제 등장하는 회사는 DB 전체에서
**3개사뿐**(2026-08-27 세션 SQL 스캔, 재확인 안 함 — 다음 스텝에서 재확인 필요):

| 회사 | 상태 | 확인 내용 |
|---|---|---|
| 00155258 포스코스틸리온 | **충돌 발생** | "자본총계"+"총자본" 같은 표 공존 → 오채택. fail_a 14건 |
| 00369657 리노공업 | 충돌 없음(확인) | 2001~2008 DB값 재검증: `total_assets != total_equity` 전 구간 정상 — "총자본" alias가 현재 안 걸리고 있음(원문에서 "총자본"이 실제로 등장하는지, 등장해도 tiebreak에서 안 이기는지는 미확인) |
| 01150515 대명에너지 | 충돌 없음(확인) | 최신 분기보고서(`20260514001384.xml`) 원문에 "총자본" 라벨 자체가 없음("부채및자본총계"만 사용) — alias가 현재 load-bearing 아님 |

→ "총자본" alias를 **완전히 제거**해도 2개사는 영향 없고(현재도 안 쓰이거나 정상), 포스코
스틸리온만 고쳐진다. 새 canonical이 필요 없다 — 그냥 목록에서 지운다.

## 3. 제안 수정

`account_maps/bs_accounts.py:289`에서 `"총자본"` 한 줄만 제거:

```python
"bs.total_equity": [
    "자본총계", "자본 합계", "자본의 합계", "자본 총계",
],
```

## 4. 소급 백필 필요 (★자동 반영 안 됨 — `docs/runbook_new_parser_pipeline_integration.md` 절차)

이건 face_audit.py(검증기)가 아니라 **std_v3 실값 경로**(`account_maps/bs_accounts.py`)
수정이므로, R50(클러스터A/B)과 달리 **std_v3 소급 재생성이 필요하다**:

- 대상: `00155258`(포스코스틸리온) 전체 기간 — "총자본" alias가 언제부터 이 필링에
  등장했는지 미확인(2023 FY 이전은 DB값이 이미 정상이라 그 시점부터는 원문에 "총자본"
  줄 자체가 없었거나 tiebreak에서 안 이겼을 가능성 — **재생성 전 확인 필요**).
  안전하게는 전체 기간 재생성 후 diff로 실제 변경된 (fy,period,basis)만 확인.
- 방법: `build_std_v3.py --corp 00155258` (또는 해당 스크립트의 정확한 재생성 커맨드 —
  세션 내 재확인 필요, `docs/PARSING_RULES.md` R39/R45 사례의 재생성 커맨드 패턴 참고).
- 검증: 재생성 후 `total_equity != total_assets` 전 기간 확인 + `gateb_audit.py --corp
  00155258 --source v3 --recheck` 로 fail_a 14건 → 0 확인.

## 5. §결정 필요

1. `account_maps/bs_accounts.py`에서 "총자본" alias 제거를 **구현해도 되는지 승인**.
2. 00369657/01150515 "충돌 없음" 확인이 표본 1건씩(각 1개 필링)만 본 것이라 — 전체
   히스토리(특히 2개사 각각의 全 rcept)까지 훑을지, 아니면 alias 제거 후 두 회사
   `gateb_audit.py --recheck`로 회귀 여부만 확인할지.
3. 소급 백필 커맨드(`build_std_v3.py` 정확한 인자)를 구현 직전에 재확인 필요 — 이 문서엔
   플레이스홀더만 있음.

---

## 6. 실제 구현 (§1~§5 승인 후 진행, 구현 중 pivot)

**§3 alias 제거를 승인받아 구현 → 즉시 회귀 발견 → 원상복구 → 재조사 → 다른 코드에
재구현.** 아래는 그 경위와 최종 코드다.

### 6-1. §3 최초안(alias 제거) 구현 후 회귀 발견

`account_maps/bs_accounts.py`에서 `"총자본"` 제거 → `pytest`(632 passed, 무관 기존
실패 1건 제외, 회귀 0) 통과 → `build_std_v3.py --corp 00155258,00369657,01150515
--year-min 1999` 재빌드 → DB diff 확인 중 **00369657(리노공업) 2026H1 `total_equity`가
NULL로 규명**(연결+별도 둘 다). §2의 "충돌 없음(표본 1건)" 확인이 다른 필링(2001~2008,
분기)이었고 최신 필링(2026H1)은 확인하지 않았던 게 원인 — §5-2의 "표본 1건씩만 확인했다"
우려가 그대로 적중했다.

원문 대조(`20260814000445.xml`): 리노공업은 "총자본"을 **`ifrs-full_Equity`**(정답,
진짜 지분)로 쓰고, "부채와자본총계"를 EquityAndLiabilities에 쓴다 — 포스코스틸리온과
정반대 라벨 관례. 이 필링엔 "자본총계" 라벨 자체가 없어 "총자본"이 유일한 equity
후보였다. **alias 제거는 즉시 원상복구**(`account_maps/bs_accounts.py`에 "총자본"
되돌림 + `build_std_v3.py` 재실행, DB diff로 원래 상태와 완전 일치 확인).

### 6-2. 진짜 근본원인 재조사 — 라벨이 아니라 `_reduce_conflict()`의 depth 휴리스틱

`report_lines`를 직접 조회해 두 회사의 후보 행을 나란히 비교:

```
00155258(포스코스틸리온) rcept 20250408001924, table_seq=0, consolidated:
  자산총계  section_path='자산'  556,803,723,173
  자본총계  section_path='자본'  385,299,788,248  ← 정답
  총자본    section_path=''      556,803,723,173  ← 오답, 자산총계와 정확히 동일값

00369657(리노공업) rcept 20260814000445, table_seq=0, separate:
  부채와자본총계  section_path=''      856,864,674,888
  총자본          section_path='자본'  776,763,916,632  ← 정답(section_path 있음, 여기선 유일후보)
```

같은 "총자본" 라벨이라도 **section_path 유무/값**으로 두 용법이 구조적으로 구분된다.
`fin2/layer3/combine.py::_reduce_conflict()`의 shallowest-`section_path`-depth 우선
규칙(`_depth(r) = 0 if not p else p.count(">")+1`)이 이 구분을 역이용해 오작동시킴:
포스코스틸리온의 "총자본"은 section_path가 비어 있어 depth=0(최상위 취급)이 되고,
"자본총계"(depth=1)를 이겨버린다. 즉 원래 있던 "shallow=상위 총계, deep=하위 성분"
가정이 "총자본"(부채와자본총계, 섹션 밖에 고아로 존재)에는 성립하지 않는데 이 규칙이
그걸 몰랐다.

### 6-3. 최종 수정

`account_maps/bs_accounts.py`는 원상태 유지("총자본" alias 그대로, 리노공업 보존
필수 — 주석만 R51 조사 결과 추가). 대신 `fin2/layer3/combine.py`에 기존
`_trust_account_table_seqs()`와 같은 패턴으로 `_degenerate_total_equity_row_ids()`
신설:

- 같은 table_seq에서 `bs.total_equity` 후보값이 `bs.total_assets` 후보값과 **정확히
  일치**하면(=EquityAndLiabilities를 지분으로 착각한 행) 그 후보를 제외.
- 단, 그 table_seq에 **다른** total_equity 후보가 남아 있을 때만 제외(무차입경영 등
  진짜 총자산==총자본인 회사를 실수로 MISSING 처리하지 않도록 — 리노공업이 실제로
  "무차입경영" 회사라 이 안전장치가 실전에서 유효함을 원문에서 확인).
- `_resolve()` 안에서 기존 `trust_seqs` 필터와 같은 자리(by_label 그룹핑 전)에 배선.

### 6-4. 최종 검증

- `pytest tests/ fin2/tests/` — 632 passed(무관 기존 실패 1건 `test_lxintl_facility_
  table_dropped` 그대로, 회귀 0).
- `build_std_v3.py --corp 00155258,00369657,01150515 --year-min 1999` 재빌드 후 DB
  diff: **00155258 14건만** 정확히 바뀜(자본총계 값으로 교정, `total_assets−
  total_liabilities=total_equity` 항등식 전부 성립), 00369657·01150515는 **무변경**
  (원래 pre-backfill 스냅샷과 완전 일치).
- `gateb_audit.py --source v3 --recheck`: 00155258 face_audit 184행 전부 pass/pending
  (기존 fail_a 14건 전부 pass 전환), 00369657/01150515 각각 in-scope 100% 일치율.
  Phase B 라인 감사에 잔존하는 fail_a(00155258 7건, 01150515 2건)는 EPS 단위스케일·
  RightofuseAssets·OtherProvisions 등 total_equity와 무관한 기존 이슈로 확인(값
  detail에 equity 관련 필드 없음).
- DB 전체(fy≥1999, v3) `face_audit.gate_status='fail_a'`: **170 → 156(−14)**.

`docs/PARSING_RULES.md` R51로 등재 완료. 코드: `fin2/layer3/combine.py`
(`_degenerate_total_equity_row_ids()` 신설 + `_resolve()` 배선), `account_maps/
bs_accounts.py`(주석만 추가, 값 변경 없음).

승인 전까지 코드 수정 없음([[feedback-plan-then-wait]]) — 이 §6은 §3 승인 이후,
구현 과정에서 발견된 반증에 따라 같은 세션 안에서 재설계·재구현한 기록이다.
