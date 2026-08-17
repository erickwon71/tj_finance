# P0(잠복) — `standard_financials` 뷰 ↔ `face_audit` 조인 결함 수정 설계 (2026-08-17)

> **선행 문서**: 없음(신규 발견).
> **관련 규칙**: `docs/PARSING_RULES.md` R8(새 파서는 배선 2곳 + 소급 백필 + 검증) —
> 본 결함은 R8 위반의 세 번째 사례다(§1-C).
>
> **★2026-08-17 시급도 재분류 (사용자 확인: "아직 app은 사용하고 있지 않아")**
> 뷰를 읽는 프로세스가 **현재 하나도 가동되지 않는다** — 소비자는 `app/`(미사용)과
> `run.py`(aggregate/valuation/verify, 수동 실행)뿐이고, launchd 에 등록된 작업은
> `com.tjfinance.collect.plist` **하나**이며 그것도 `--download-only` 라 뷰를 읽지 않는다.
> 따라서 본 결함은 **전면 잠복**이다 — 지금 잘못된 값을 누구에게도 보여주고 있지 않다.
> **결함의 실체와 수정 내용은 아래 그대로 유효**하나, 착수 순위는 ①·③ 뒤로 내린다(§9).
> 앱 가동 **전에는 반드시** 닫아야 한다.

---

## 0. 이 문서가 하는 일 (3줄 요약)

1. `standard_financials` 뷰가 `face_audit` 를 조인할 때 **`source_version` 을 지정하지
   않아** v2·v3 감사행이 둘 다 붙는다 → 뷰 행이 **2배로 중복**되고(244,439키),
   `gate_b_status` 가 **엉뚱한 체인의 결과**를 표시하며(50,104행), `fail_a` 차단
   게이트가 **v2 결과로 우회**된다.
2. 조인 서술부에 `AND fa.source_version = 'v3'`(v3 브랜치) / `'v2'`(v2 브랜치) 를
   추가한다. 데이터 변경 없음, `CREATE OR REPLACE VIEW` 한 번.
3. 앱 미사용이라 **지금 당장의 피해는 0**이다. 다만 이 뷰는 향후 검증·스크리너의 단일
   소비 표면이므로, **앱을 켜기 전** 또는 **뷰를 검증 근거로 쓰기 전**에 닫아야 한다.

---

## 1. 결함

### 1-A. 코드 위치

`collector/db.py` 마이그레이션 `2026_08_standard_financials_view_v3`:

```sql
-- v3 브랜치 (collector/db.py:734-740)
FROM std_financials_v3 v3
LEFT JOIN face_audit fa
  ON  fa.corp_code      = v3.corp_code
  AND fa.fiscal_year    = v3.fiscal_year
  AND fa.fiscal_period  = v3.fiscal_period
  AND fa.statement_type = v3.statement_type
  AND NOT COALESCE(fa.is_stub, false)
  --  ★ fa.source_version 조건 없음
WHERE COALESCE(fa.gate_status, 'unaudited') <> 'fail_a'
```

```sql
-- v2 브랜치 (collector/db.py:761-768) — 동일 결함
FROM std_financials_v2 s
LEFT JOIN face_audit fa
  ON  fa.corp_code = s.corp_code AND fa.fiscal_year = s.fiscal_year
  AND fa.fiscal_period = s.fiscal_period AND fa.statement_type = s.statement_type
  AND NOT COALESCE(fa.is_stub, false)
  --  ★ 동일하게 없음
```

`face_audit` 의 PK 는 마이그레이션 `2026_08_face_audit_source_version`(`collector/db.py:893-907`)
에서 **`source_version` 을 포함하도록 확장**됐다:

```
PK = (corp_code, fiscal_year, fiscal_period, statement_type, is_stub, source_version)
```

즉 같은 `(corp, fy, fp, basis)` 키에 **v2 행과 v3 행이 정상적으로 공존**한다(설계 의도 —
`scripts/gateb_audit.py:8-11` 모듈 docstring: *"v2/v3 감사결과가 각자 별도 행으로 병행
보관 — 서로 덮어쓰지 않는다"*). 뷰의 조인만 그 확장을 안 따라갔다.

### 1-B. 실측 증상 3종 (2026-08-17, 프로덕션 DB)

**증상 ① — 뷰 행 2배 중복**

```
std_financials_v3                    299,651 행
standard_financials (뷰)             565,785 행

뷰의 (corp, fy, fp, statement_type, version) 키 중복도:
   1회 등장   76,907 키
   2회 등장  244,439 키      ← 감사행이 v2·v3 둘 다 있는 키
```

샘플 — 삼성전자 2024FY 연결이 뷰에 2행:

```
('00126380', 2024, 'FY', 'consolidated', 300870903000000, 'pass')
('00126380', 2024, 'FY', 'consolidated', 300870903000000, 'pass')
```

**증상 ② — `gate_b_status` 오귀속: 50,104행**

v2 감사결과와 v3 감사결과가 서로 다른 키가 50,104개다. 뷰는 둘 다 내보내므로, 소비자가
어느 행을 집으면 **std_v3 데이터에 std_v2 감사결과가 붙은 행**을 보게 된다.

**증상 ③ — `fail_a` 차단 게이트 우회(무력화)**

`WHERE COALESCE(fa.gate_status,'unaudited') <> 'fail_a'` 는 **조인된 행 단위로** 평가된다.
따라서 v3 감사가 `fail_a` 여도 v2 감사행이 `pass` 면 그 행이 살아남는다.

미래에셋증권(00111722) 실측 — v3 감사에서 2026Q1 연결·별도 모두 `fail_a`(revenue)인데
뷰에는 `pass` 로 노출:

```
(2026, 'Q1', 'consolidated', 1624073000000, 'pass')   ← v3 감사는 fail_a
(2026, 'Q1', 'separate',      591948000000, 'pass')   ← v3 감사는 fail_a
(2025, 'H1', 'consolidated', 1265644000000, 'pass')   ┐ 같은 행이 두 번,
(2025, 'H1', 'consolidated', 1265644000000, 'fail_b') ┘ 등급이 서로 다름
```

현재 실제로 은닉되는 행은 487행뿐이고(v2 쪽도 우연히 fail_a 이거나 감사행이 없는 경우),
그것도 **v2 감사결과가 결정한 것**이라 의미가 없다.

### 1-C. 유입 경위 — R8 위반 3연속

`2026_08_face_audit_source_version` 과 v3 병행 감사는 커밋 `e6d0a04`(2026-08-11,
`feat(gateb): v3-native 감사 병행(source_version)`)에서 함께 들어왔다. 이때 **`face_audit`
를 읽는 쪽 3곳 중 1곳만** 갱신됐다:

| 소비자 | 위치 | 상태 |
|---|---|---|
| `gateb_audit.py`(쓰기·재개 스킵) | `scripts/gateb_audit.py:140-143` | ✅ `source_version=:sv` 반영 |
| `standard_financials` 뷰 | `collector/db.py:734, 761` | ❌ **본 문서 대상** |
| `run_dq_gate`(데일리 게이트) | `scripts/collect_new.py:118` | ❌ `source` 미전달 → `AttributeError` (⑤ 대상) |
| `app/data/trust.py`(신뢰도 배지) | `app/data/trust.py:18-21` | ❌ v2/v3 합산 집계 |

CLAUDE.md 가 *"특히 자주 잊는 것: 두 call site 모두 배선"* 이라고 경고한 항목이 같은
커밋에서 3번 재발했다. §7 에 재발 방지를 둔다.

---

## 2. 영향 범위 (다운스트림) — **전부 현재 미가동**

> 아래는 **앱/CLI 를 켰을 때 발현할** 증상이다. 2026-08-17 현재 이 소비자 중 돌고 있는
> 것은 없다(문서 상단 시급도 재분류 참고). 즉 **재현 대기 상태의 결함 목록**이다.

| 소비자 | 코드 | 증상 |
|---|---|---|
| 회사 페이지 시계열 | `analyzer/ratio_engine.py:255-265` — `fiscal_period='ALL'` + `LIMIT :n` | 중복 때문에 **요청한 N기간의 절반만** 반환 |
| 스크리너 | `app/data/screen_window.py:112-140` — `ROW_NUMBER() OVER (PARTITION BY corp_code ORDER BY fiscal_year DESC)` | rn=1,2 가 **같은 연도** → 다년 랭킹·윈도우 계산 왜곡 |
| DB 현황 카운터 | `app/data/corp.py:70` — `SELECT count(*) FROM standard_financials` | 행수 2배 표기 |
| 신뢰도 배지 | `app/data/trust.py:15-21` | v2+v3 합산(모집단 2배) + `fail_a` 카운트에 v2 결과 혼입 |
| 임의 집계(SUM/AVG) | 뷰를 직접 쓰는 모든 쿼리 | **이중 계상** |

> ⚠ 회사 페이지의 **FY 단건 조회**(`fiscal_period='FY'` + 연도 지정)는 중복 행의 값이
> 동일하므로 표시값 자체는 틀리지 않는다. 깨지는 것은 **행 수에 의존하는 연산**
> (LIMIT / ROW_NUMBER / count / sum)이다.

---

## 3. 수정 설계

### 3-A. 원칙

> **뷰는 자신이 표시하는 std 체인의 감사결과만 조인한다.**
> v3 데이터 행에는 v3 감사결과를, v2 폴백 행에는 v2 감사결과를 붙인다.

`face_audit` 에 v2/v3 를 병행 보관하는 것 자체는 의도된 설계(`gateb_audit.py:8-11`)이므로
데이터는 손대지 않는다. 뷰의 조인 서술부만 명시화한다.

### 3-B. 변경 내용

```sql
-- v3 브랜치
LEFT JOIN face_audit fa
  ON  fa.corp_code      = v3.corp_code
  AND fa.fiscal_year    = v3.fiscal_year
  AND fa.fiscal_period  = v3.fiscal_period
  AND fa.statement_type = v3.statement_type
  AND NOT COALESCE(fa.is_stub, false)
  AND fa.source_version = 'v3'          -- ★ 추가
```

```sql
-- v2 브랜치
  AND fa.source_version = 'v2'          -- ★ 추가
```

새 마이그레이션 키: `2026_08_standard_financials_view_source_version`.
기존 `2026_08_standard_financials_view_v3` 은 **수정하지 않는다**(이미 적용된 마이그레이션을
변조하면 재적용 환경과 갈라진다) — 새 키로 `CREATE OR REPLACE VIEW` 를 한 번 더 건다.

### 3-C. 대안 검토

| 대안 | 기각 사유 |
|---|---|
| `DISTINCT ON (corp,fy,fp,type)` 로 중복만 제거 | 중복은 없어지지만 **어느 체인의 감사결과가 남는지 비결정적** → 증상 ②③ 미해결 |
| v2/v3 중 우선순위 `COALESCE` | 조인이 2회로 늘고, "v3 미감사면 v2 결과로 대체" 라는 **새 의미론**을 도입 — 감사기 계약에 없는 규칙을 뷰가 만들어냄 |
| `face_audit` 에서 v2 행 삭제 | v2 감사(271,702행)는 **회귀 비교 기준선**이다. 병행 보관이 설계 의도 |
| 뷰를 MATERIALIZED VIEW 로 | 별개 성능 과제. 본 결함과 무관하고 갱신 배선이 추가로 필요 |

### 3-D. ★ 수정의 부작용 — `fail_a` 차단이 "되살아난다"

지금은 §1-B 증상 ③ 때문에 `fail_a` 게이트가 사실상 작동하지 않는다. 조인을 고치면
**게이트가 의도대로 작동하기 시작**하고, 그 결과 지금 보이던 행이 사라진다.

```
현재 은닉        487행 (v2 결과가 결정 — 의미 없음)
수정 후 은닉     394행 (v3 fail_a, 의미 있음)

   394행 내역:
     금융섹터(KSIC 64/65/66)   178행 / 23개사   ← ①의 구조적 오탐
     비금융                     214행 / 117개사  ← 조사 가치 있는 후보
     업종코드 없음                2행 /  1개사
```

숨겨질 금융 23개사 = 미래에셋증권·신영증권·교보증권·LS증권·다올투자증권·DB증권·부국증권·
키움증권·유진증권·상상인증권·유안타증권 등 **주요 증권사의 2024~2026 최근 재무 전량**.

**이 178행은 데이터 오류가 아니다.** `docs/plans/financial_sector_revenue_standards.md`
(2026-07-24 사용자 결정)의 증권사 **순영업수익 표준(= 영업이익 + 판관비)** 을 계층3이
정확히 적용한 결과이고, 그런 라인은 원문에 존재하지 않으므로 Gate B 의 집합 멤버십
판정(`fin2/audit/face_audit.py:1015`, `val in won_vals`)이 구조적으로 통과시킬 수 없다.

→ **P0 를 단독 적용하면 정확한 데이터가 앱에서 사라진다.** §5 참조.

---

## 4. Phase

| Phase | 내용 | 산출물 | 예상 |
|---|---|---|---|
| **P0-1** | 마이그레이션 `2026_08_standard_financials_view_source_version` 추가(`collector/db.py`) | 코드 | 30분 |
| **P0-2** | 적용 전 기준선 스냅샷(§6 A) 저장 | `docs/qa/view_dup_baseline_2026-08-17.md` | 10분 |
| **P0-3** | `init_db()` 로 마이그레이션 적용 | — | 1분 |
| **P0-4** | 검증(§6 B~E) | 검증 로그 | 30분 |
| **P0-5** | `app/data/trust.py` 를 `source_version='v3'` 로 한정 | 코드 | 15분 |
| **P0-6** | 회귀 테스트 추가(§6 F) + `docs/PARSING_RULES.md` 부록 C 등재 | 코드·문서 | 30분 |

> P0-5 를 같은 묶음에 넣는 이유: `trust.py` 는 뷰가 아니라 `face_audit` 를 직접 읽으므로
> 뷰 수정으로 자동 해결되지 않는다(§1-C 표). 같은 결함·같은 원인이라 함께 닫는다.

---

## 5. 적용 순서 — **해소됨 (사용자 확인 2026-08-17)**

당초 이 절은 "P0 단독 적용 시 §3-D 로 금융 23개사가 앱에서 사라진다"는 이유로 세 가지
적용 순서를 놓고 사용자 결정을 요청했다. **앱 미사용이 확인되어 이 결정은 소멸한다** —
아무도 안 보는 화면에서 무엇이 숨겨지는지는 문제가 되지 않는다.

**확정 방침**

- P0 는 **① 과의 순서 제약이 없다.** 언제 적용해도 된다.
- 다만 **①·② 와 함께 닫는 것을 권장**한다. 셋 다 `gate_status` 의 의미론을 건드리고,
  ② 는 등급 체계 자체를 재정의하므로 뷰의 `WHERE` 절도 그때 같이 손보게 된다. 뷰 DDL 을
  두 번 고치는 것보다 한 번에 끝내는 편이 낫다.
- **불변 조건 하나만 지킨다**: `streamlit run app/main.py` 를 실제로 켜기 전에 §6 검증을
  통과해야 한다. 앱 가동이 이 문서의 **마감 기한**이다.

> 부작용(§3-D)이 사라진 게 아니라 **관측되지 않을 뿐**이다. ① 이 먼저 끝나 있으면
> 178행이 애초에 `fail_a` 가 아니게 되므로 부작용 자체가 없어진다 — 그래서 순서를
> 강제하지는 않되 ① → P0 가 여전히 더 깔끔하다.

---

## 6. 검증 규약

원문 대조는 필요 없다(값을 바꾸지 않음). **행 집합의 동치성**을 증명한다.

**A. 기준선(적용 전)** — 아래를 파일로 저장

```sql
SELECT count(*) FROM standard_financials;                    -- 565,785 예상
SELECT count(*) FROM (SELECT corp_code,fiscal_year,fiscal_period,statement_type,version
                      FROM standard_financials
                      GROUP BY 1,2,3,4,5) t;                 -- 321,346 예상
```

**B. 중복 소멸** — 적용 후 모든 키의 등장 횟수가 1이어야 한다

```sql
SELECT n, count(*) FROM (
  SELECT corp_code,fiscal_year,fiscal_period,statement_type,version, count(*) n
  FROM standard_financials GROUP BY 1,2,3,4,5) t GROUP BY 1 ORDER BY 1;
-- 통과선: n=1 한 줄만 나올 것
```

**C. 무손실** — 적용 전 distinct 키 집합 ⊇ 적용 후 키 집합이고, 차집합이 정확히 §3-D 의
394행 + v2 브랜치 fail_a 분이어야 한다. 그 외 키가 하나라도 사라지면 **실패**.

**D. `gate_b_status` 정합** — 뷰의 등급이 v3 감사결과와 100% 일치

```sql
SELECT count(*) FROM standard_financials sf
JOIN std_financials_v3 v3 USING (corp_code, fiscal_year, fiscal_period, statement_type)
LEFT JOIN face_audit fa
  ON fa.corp_code=sf.corp_code AND fa.fiscal_year=sf.fiscal_year
 AND fa.fiscal_period=sf.fiscal_period AND fa.statement_type=sf.statement_type
 AND NOT COALESCE(fa.is_stub,false) AND fa.source_version='v3'
WHERE sf.gate_b_status IS DISTINCT FROM COALESCE(fa.gate_status,'unaudited');
-- 통과선: 0
```

**E. 다운스트림 스모크** — §2 표의 4개 소비자를 실제로 호출

- `load_standard_financials('00126380','consolidated','ALL',20)` → **20개 서로 다른 기간**
  (현재는 10개 기간이 2번씩)
- `app/data/screen_window.py` 스크리너 1회 실행 → 기업당 1행
- `app/data/trust.py` 배지 → 모집단이 v3 감사 행수와 일치
- `streamlit run app/main.py` 크래시 0 (`docs/qa` C-1 풀스모크 절차 재사용)

**F. 회귀 테스트** — 뷰 정의에 대한 구조 테스트를 신설한다(현재 뷰 회귀 테스트 없음)

```python
# fin2/tests/test_standard_financials_view.py
def test_view_has_no_duplicate_keys():
    """standard_financials must emit exactly one row per (corp, fy, fp, type, version).

    Regression guard for the 2026-08-17 face_audit join defect: the LEFT JOIN omitted
    source_version, so v2 and v3 audit rows both matched and every audited key was
    emitted twice (244,439 keys). See docs/plans/gateb_view_source_version_join_fix_
    design_2026-08-17.md.
    """
```

---

## 7. 리스크 / 재발 방지

| 리스크 | 대응 |
|---|---|
| 뷰 교체 중 앱이 빈 결과를 본다 | `CREATE OR REPLACE VIEW` 는 단일 트랜잭션·원자적. 다운타임 없음 |
| 롤백 필요 | `2026_08_standard_financials_view_v3` 의 DDL 재적용 = 즉시 원복(데이터 무변경) |
| §3-D 은닉이 예상보다 크다 | P0-2 기준선과 P0-4 검증 C 로 **적용 전에** 정확한 은닉 행 목록을 뽑아둔다. 394행 초과면 중단 |
| **같은 결함 4번째 재발** | `face_audit` 를 읽는 지점이 4곳(§1-C 표)뿐이므로, `source_version` 없이 `face_audit` 를 조회하는 코드를 금지하는 테스트를 F 에 함께 넣는다 — `grep -n "FROM face_audit"` 결과 전부가 `source_version` 서술부를 갖는지 검사 |

---

## 8. 미결 / 이 문서 범위 밖

- `fail_a` 게이트의 **의미론 자체**(트랙 기반 → 증거강도 기반)는 ②의 대상. 본 문서는
  기존 의미론을 그대로 두고 **조인만** 고친다.
- 금융섹터 178행의 `derived` 분리는 ①의 대상.
- `app/data/trust.py` 의 배지 산식(pass/fail/pending 비율을 어떻게 보여줄지)은 손대지
  않는다 — `source_version='v3'` 한정만 추가한다.
- v2 감사행(271,702행)의 보존 기간·은퇴 시점은 미정. 회귀 기준선으로 당분간 유지.

---

## 9. 착수 순서 (2026-08-17 확정, 앱 미사용 반영)

기준: **"지금 이 순간 반복 작업 비용을 실제로 줄이는가"**. 앱이 안 돌므로 사용자 노출
결함은 전부 잠복이고, 남는 유일한 실비용은 **개발 루프 자체**다.

| 순위 | # | 문서 | 근거 |
|---|---|---|---|
| **1** | ① | `gateb_financial_sector_derived_revenue_design_2026-08-17.md` | fail 3,348건의 **81%(2,721건)** 가 구조적 오탐 → 제거해야 나머지 627건이 보인다. 조준점 교정이 반복 루프의 1차 원인 |
| **2** | ③ | `gateb_audit_performance_design_2026-08-17.md` | ✅ 작성 완료. **"36분/기업" 은 실측으로 정정됨(31.4초)** — 전수 재감사는 이미 5-shard 2.9시간. 수정 시 1.1시간이 되어 "고칠 때마다 전수 확인" 이 일상화 |
| **3** | ② | `gateb_evidence_grade_redesign_*.md` | fail_a/fail_b 를 트랙이 아닌 증거강도로 재정의 + **pass 근거 계측**(현재 미기록 — `gateb_audit.py:213-218`) |
| **4** | **P0** | 본 문서 | 잠복. ② 와 함께 뷰 DDL 1회로 닫는 것을 권장. **앱 가동 전 필수** |
| 5 | ⑤ | `run_dq_gate` 배선 수정 | 잠복(데일리가 `--download-only`). 소규모 — ② 또는 P0 에 병합 가능 |
| 6 | ④ | curated 키 재생성기 데일리 배선 | 데일리가 `--download-only` 를 벗은 뒤에야 의미 있음 |

> ① 이 ③ 보다 앞서는 이유: ① 의 검증에 필요한 재감사는 **23개사 표적**이라 ③ 없이도
> 수 시간 안에 끝난다. 반대로 ③ 을 먼저 해도 감사 신호의 81% 가 노이즈인 상태에서
> 전수를 돌리면 잡음만 빨리 쌓인다.
