# valuation_daily std_v2→v3 이식 + std_v2 잔여 쓰기 제거 — 설계 문서 (2026-08-30)

> **미구현 — 승인 대기.** 이 문서는 설계까지만 담는다. 구현은 사용자가 별도로 지시한 뒤
> 착수한다([[feedback-plan-then-wait]]).

---

## 0. 배경 — 왜 지금인가

`std_v3_daily_wiring_plan_2026-08-30.md` Phase 2(std_v2 쓰기 제거) 구현 중, std_v2 쓰기가
**완전히는** 끊기지 않았음을 발견했다. `collect_new.py`의 `_sync_cf_da()`가 부르는
`cf_da_sync.sync_cf_da()` / `expense_nature_sync.sync_expense_nature()`가 각자
`std_financials_v2 WHERE depreciation IS NULL`을 직접 SELECT해 그 corp에 대해 독자적으로
`standardize_corp(v2)→derive_quarters_corp→calendarize_corp`를 재전파한다 —
`process_corp`의 stages 축소와는 완전히 별개인 경로다.

이 문서는 그 잔여 경로의 **유일하게 확인된 살아있는 소비자**(`valuation_daily.ev_ebitda`)를
v3로 이식해, 잔여 쓰기를 마저 끊기 위한 설계다.

이미 알려진 배경(중복 설명 생략, 링크만):
- `std_v2_retirement_port_to_v3_2026-08-22.md` §3.9(`extended_financials`), §3.10(R17,
  이 잔여 경로를 최초 식별) — "이식할 로직은 없다(v3 note_da.py가 상위집합), 문제는 배관"
  이라고 이미 결론 내려둔 지점.
- `std_v3_daily_wiring_plan_2026-08-30.md` §2-3(Phase 2 구현 중 재확인) · §8(valuation_daily
  v3 재작성이 이미 백로그 항목으로 등재돼 있었음).

---

## 1. 실측 근거 (2026-08-30 확인)

### 1-1. `valuation_daily`가 정확히 무엇을 std_v2에서 읽는가

`collector/db.py:247` 정의(matview) 발췌:

```sql
LEFT JOIN LATERAL (
    SELECT f.fiscal_year, f.statement_type AS basis,
           COALESCE(f.controlling_ni, f.net_income)       AS ni,
           COALESCE(f.controlling_equity, f.total_equity) AS eq,
           f.revenue, f.cfo, f.ebitda, f.operating_income, f.net_debt, f.dividends_paid
    FROM std_financials_v2 f
    WHERE f.corp_code = c.corp_code AND f.fiscal_period = 'FY' AND f.version = 1
      AND NOT COALESCE(f.is_discrete, false) AND NOT COALESCE(f.is_stub, false)
      AND f.period_end <= sp.trade_date
    ORDER BY f.period_end DESC,
             CASE f.statement_type WHEN 'consolidated' THEN 0 ELSE 1 END
    LIMIT 1
) fin ON true
```

`ev_ebitda`(EV/EBITDA) 컬럼이 `fin.ebitda`에 직접 의존 — 이게 cf_da_sync/expense_nature_sync가
FY2024+ CF-미태깅 기업을 위해 patch하는 바로 그 필드다. `_refresh_valuation_daily()`가
`collect_new.py`의 같은 데일리 실행 안(⑥ 단계)에서 매일 이 matview를 갱신하므로, 이 patch를
멈추면 신규 영향 기업의 `ev_ebitda`가 **다음날부터 조용히 틀어진다**(재현 가능한 실사용
경로 — 이론적 리스크가 아니다).

### 1-2. `extended_financials`는 std_v2가 아니라 `fact_v2`만 쓴다

`app/data/extended.py:2` docstring: "확장 재무항목 로더 — extended_financials 뷰
(fact_v2×statement_source) 소비." `collector/db.py`의 뷰 정의도 `fact_v2`만 조인한다.
→ `_sync_cf_da`의 두 절반은 소비처가 다르다:

| 절반 | 쓰는 곳 | 먹는 곳 | 이번 트랙에서 손댈지 |
|---|---|---|---|
| `store_facts()`(fact_v2 upsert) | `fact_v2` | `extended_financials`(§0-A 계층2 축) | **아니오** — 무관, 계속 필요 |
| `standardize_corp(v2)→quarterly→calendar` | `std_financials_v2` | **`valuation_daily.ev_ebitda`**(확인됨) | **예 — 이 문서의 대상** |

### 1-3. `is_stub`/`is_discrete` — v3엔 컬럼 자체가 없다, 그런데 이미 선례가 있다

`fin2/layer3/build.py:41` 주석: "std_v3 has no `version`/`is_stub` columns". 실측(2026-08-30):

| | v2(FY, non-stub, version=1) | v3(FY) |
|---|---|---|
| 행수 | 63,110 | **78,213**(더 넓음) |
| 최초 period_end | 1997-11-30 | 1999-11-30 |

- v3가 겹치는 구간에서는 v2보다 커버리지가 넓다(D0의 +21개사 순증과 같은 패턴).
- **v3가 못 미치는 구간은 1997~1999(2년)뿐** — `std_v3_daily_wiring_plan_2026-08-30.md`
  §8에 이미 "fy<1999 249행 정책 결정 — v3 범위 확대 vs 유니버스 제외, 사용자 결정 필요"로
  등재된 바로 그 249행이다. **새 리스크가 아니라 이미 트래킹 중인 결정 대기 항목.**
- `is_stub=true` 행: **323건 / 전체 std_v2(version=1) 503,269건 = 0.064%**. 이미
  `scripts/gateb_audit.py:139`가 정확히 같은 결론을 내려둔 선례가 있다: *"is_stub 는 v2
  기준 0.09%뿐이라 무시 가능 — 별도 필터 없이 std_v3 전체를 감사한다"*(v3 소스 face_audit
  행은 `is_stub=False`로 고정, `gateb_audit.py:242`). **같은 근거로 valuation_daily
  이식에서도 is_stub 필터를 그냥 뺀다** — 새로 정당화할 필요 없이 기존 선례 재사용.
- `is_discrete`는 애초에 이 쿼리가 `fiscal_period='FY'`만 보므로(이산분기는 Q1~Q4 3개월
  개념, PRD 03 §5.1) FY 행에는 원래도 해당사항이 없었다 — 필터를 빼도 동작 불변.

### 1-4. 소비처 인벤토리 — 전부 matview의 **출력 컬럼**만 본다(내부 소스 무관)

`grep -rl valuation_daily`: `app/data/valuation_bands.py`(밴드 계산, PER/PBR/PSR/EV-EBITDA)
· `app/views/chart_builder_page.py`(차트) · `app/cache.py`(캐시 위임) ·
`scripts/dq_assertions.py`(`valuation_daily_stale` — `trade_date` 최신성만 봄, 소스 테이블
무관) · `scripts/nightly_valuation_refresh.py`(refresh 트리거) · `scripts/phase_c_rebuild.py`
(shares_out 백필 순서 언급, 매트뷰 재구축 로직 아님). **전부 matview가 이미 계산해 낸
per/pbr/psr/ev_ebitda/dps/dividend_yield 컬럼만 읽는다** — 내부 SELECT가 v2를 보든 v3를
보든 이 소비처들은 코드 변경이 필요 없다.

---

## 2. 설계 결정

### D1. matview 재정의 — `std_financials_v2 f` → `std_financials_v3 f`

- `f.version = 1` 조건 제거(v3엔 컬럼 없음).
- `NOT COALESCE(f.is_discrete, false)` 제거(§1-3 — FY 행엔 원래 해당 없음).
- `NOT COALESCE(f.is_stub, false)` 제거(§1-3 — 0.064%, `gateb_audit.py` 선례 재사용).
- 나머지 컬럼(`ebitda`/`net_debt`/`operating_income`/`controlling_ni`/`controlling_equity`/
  `revenue`/`cfo`/`dividends_paid`/`period_end`/`statement_type`)은 v3에 **동일 이름으로
  전부 존재**(Phase 0, `std_v3_daily_wiring_plan_2026-08-30.md`에서 스키마 확인 완료) —
  SELECT 리스트 자체는 안 바뀐다.

> **★2026-08-30 Phase 0-2 실측 후 수정 — "전체를 한 번에 스왑"은 안전하지 않다.**
> §Phase 0-2에서 확인: `eq`(→pbr, 추정상 `ni`/`revenue`도 동일 패턴) 계열은 2012년 이후
> 95%+ 일치로 이식이 안전하지만, `ebitda`(→ev_ebitda)는 최근 연도(2016~2024)에서도 5~7%가
> 두 자릿수% 크기로 어긋난다(원인: v2 `rule_additive_da`의 "결합공시+별도계상분" 합산
> 로직이 v3 `note_da.py`에 없는 것으로 추정 — ★P1A**아님**, 별도 미해결 이슈, §Phase 0-2
> 정정 참고). `net_debt`는 별개로 P1A(lease/borrow, 기존 설계 문서 있음, 미실행) 소관.
> D1을 두 갈래로 나눈다:
> - **D1-a(안전, 즉시 가능)**: `per`/`pbr`/`psr`/`eps`/`bps`/`dps`/`dividend_yield` —
>   `ni`/`eq`/`revenue`/`cfo`/`dividends_paid`/`shares_out` 기반, v3로 스왑.
> - **D1-b(보류)**: `ev`/`ev_ebitda`/`ev_ebit` — `ebitda`/`net_debt`/`operating_income`
>   기반. `operating_income`은 D&A와 무관해 안전하지만(`ev_ebit`), `ebitda`는 위 결합공시
>   로직이, `net_debt`는 P1A가 각각 v3에 이식되기 전까지 **v2 값을 계속 써야 한다**.
> → matview를 컬럼별로 다른 소스에서 조합해야 한다(LATERAL 두 개, 하나는 v3 하나는 v2) —
>   §3 Phase 1 설계를 이에 맞게 갱신 필요(아래 참고).

### D2. pre-1999 249행 — 이 문서 범위 밖, 별도 결정 대기

`std_v3_daily_wiring_plan_2026-08-30.md` §8에 이미 있는 결정 대기 항목("v3 범위 확대 vs
유니버스 제외")과 동일 사안. 이 이식이 먼저 끝나도 그 249행은 여전히 valuation_daily에서
빠진 채로 있는다 — **새로 생기는 손실이 아니라 기존에 알려진 손실의 연장**이다. 그
결정이 나면(범위 확대 쪽으로 나면) v3에 채워지는 즉시 valuation_daily도 자동으로 커버.

### D3. `cf_da_sync`/`expense_nature_sync` 분리 — D1 검증 통과 **후**

D1이 검증(§4)까지 끝나 valuation_daily가 v3 기반으로 안정 확인되면:
- `collector/cf_da_sync.py::sync_cf_da()`, `collector/expense_nature_sync.py::sync_expense_nature()`
  양쪽에서 마지막 for-loop의 `standardize_corp(session, corp)` /
  `derive_quarters_corp(session, corp)` / `calendarize_corp(session, corp)` **세 줄만 제거**.
  `store_facts()`(fact_v2 upsert, extended_financials 소관)는 그대로 둔다.
- 반환 dict의 `std_recalc`/`n_std` 카운트도 항상 0이 되므로 로그 문구 정리
  (`std_v3_daily_wiring_plan_2026-08-30.md` Phase 2의 `_run_standardize_batches`
  카운터 정리와 동일한 패턴).
- 이 시점 이후 std_v2에 대한 쓰기 경로는 **전무**해진다(신규·잔여 모두).

### D4. 롤백 안전성 — 왜 이 변경이 낮은 리스크인가

`valuation_daily`는 **파생 matview**다(원본 테이블이 아님). `REFRESH MATERIALIZED VIEW`가
매번 SELECT 결과로 전체를 다시 채우므로, 재정의가 잘못됐다는 게 드러나면 이전 `CREATE
… AS …` SQL을 다시 실행하고 재refresh하면 즉시 원상복구된다 — **기저 테이블(`std_financials_
v2`/`v3`)은 이 작업으로 전혀 건드리지 않는다.**

---

## 3. 구현 Phase (미착수 — 승인 대기)

### Phase 0 — 착수 전 실측 (읽기 전용) — ★★★ 실행 결과: 대형 블로커 발견, 0-2 착수 보류

- [x] **0-1.** 표본 corp 20개(시대별 층화: 1999-2010/2011-2019/2020-2023/2024-2025 각 5개,
      두 basis) v2 vs v3 `ebitda`/`net_debt`/`operating_income`/`ni`/`eq` 직접 대조.
      **결과: 20건 중 7건(35%) 불일치** — §1-3에서 "무시 가능"이라 봤던 is_stub 0.064%와는
      전혀 다른 규모. 그중 2건(00348034 FY2024, 00162586 FY2025)은 **v2엔 ebitda가 있는데
      v3는 depreciation/amortization/da_total/ebitda 전부 NULL.**
- [x] **0-1★ 근본 원인 추적(계획에 없던 항목, 발견 직후 추가 실행)** —
      **`report_tables`(주석 제목/section_path 저장 테이블, F3 리팩터 2026-07-31) 소급
      백필 누락.**
  - `fin2/layer3/note_da.py::_ROWS_SQL`은 `note_lines`가 아니라 `report_tables.section_path`
    로 주제(`map_topic`)를 판정한다(F3가 note_lines에서 분리해 옮긴 것, 행 반복 33B×2.2억행
    절감 목적). 원문 `note_lines`엔 "감가상각비"/"무형자산상각비"가 정확한 값으로
    이미 있는데도(직접 확인), `report_tables`에 매칭 행이 없으면 `map_topic(None)`이
    분류에 실패해 조용히 빈 dict를 반환한다.
  - 실측: `report_tables.parsed_at`은 **2026-08-06~08-29뿐**. FY2024+ note를 가진
    고유 rcept **26,518건 중 report_tables 매칭 19건(0.07%)**.
  - `store_report_tables()`는 데일리 두 경로(`note_lines_sync.py:132`
    `xbrl_instance_lines_sync.py:114`) + 벌크 로더(`scripts/load_report_lines.py:261,264`)
    **전부에 이미 배선돼 있다** — 코드는 맞다. F3 도입 **이전**에 이미 추출된 기존
    corpus(대다수)가 재추출된 적이 없어 `report_tables` 행이 없는 것뿐이다.
  - → `docs/runbook_new_parser_pipeline_integration.md` "② 소급 백필은 자동이 아니다"의
    실제 사례. **코드 버그가 아니라 백필 누락** — `load_report_lines.py`(멱등, rcept
    단위 delete-then-insert) 재실행으로 해소될 가능성이 높다.
  - `std_v2_retirement_port_to_v3_2026-08-22.md` §3.10의 "v3가 상위집합이라 이식할 로직
    없음"은 **설계상으론 맞지만 지금은 사실이 아니다** — `report_tables` 미채움 때문에
    `note_da.py`가 사실상 거의 항상 빈손이다. v2가 값을 갖는 건 `cf_da_sync`가
    `note_lines`를 거치지 않고 **원문 XML을 직접 재파싱**(`recover_cf_da()`)해서지, v3
    보다 v2가 더 넓은 소스를 봐서가 아니다.
  - **이 발견은 이 문서(valuation_daily 이식) 범위를 넘어선다** — Gate B, 다른 note_da
    소비자 전부에 영향. 별도 트랙(가칭 `report_tables_backfill_plan`)으로 분리 필요.
- [x] **0-2.** `report_tables` 백필 완료 후(§Phase 0-1★) 재개 — v3 기반 새 정의를
      `valuation_daily` 전체(corp×trade_date, 11,196,547행)와 전수 대조.

  **결과 — per/pbr/psr(D&A 무관)와 ev_ebitda(D&A 관련)가 완전히 다른 그림을 보인다.**

  전체 집계: `no_old_row` 0(커버리지 자체는 완전) · `per_diff` 21.6% · `pbr_diff` 23.8% ·
  `psr_diff` 23.8% · `ev_ebitda_diff` **51.1%**(`max_ev_ebitda_diff` 8천만배 — division
  근처 극단치). ★단순 %만 보면 안 된다 — 연도별로 완전히 다른 이야기가 나온다.

  **`eq`(→pbr) 연도별 분해**: 2000~2011은 K-GAAP/IFRS 전환기라 both_have_disagree·
  v3_loss가 크다(예: 2010 v3_loss 165,686/325,552=51%!). **그러나 2012년부터 급격히
  좋아진다** — `both_have_match`가 2012 89.6% → 2016 93.2% → 2020 95.4% → 2024
  97.2% → 2025 97.5%. **2012+ 구간은 사실상 신뢰 가능.** 2000~2011의 나쁜 매칭은
  이미 알려진 시대(전환기) 문제와 같은 성격 — `ni`/`revenue` 도 같은 패턴일 것으로
  추정(직접 확인은 안 함, 필요시 후속).

  **`ebitda`(→ev_ebitda) 연도별 분해**: report_tables 백필 덕에 "v3가 완전히 NULL"
  문제(v3_loss)는 2016~2024 구간에서 이미 매우 작다(123~2,030/40만~57만 = 0.5% 이하).
  **그런데 "둘 다 값이 있는데 다름"(both_have_disagree)이 2016~2024 내내 5~7%
  수준으로 꾸준히 남아있다** — eq처럼 시대가 지나도 줄지 않는다. 표본 15건 직접
  대조(2024년, 둘 다 non-null): 차이 0.1~1.3%(작음) 4건, **12.6~70.3%(큼) 11건**.

  **근본 원인(1건 직접 확인, `00855093` FY2024 consolidated)**:
  ```
                    v2            v3
  depreciation      37,695,301,000  45,892,647,000
  amortization       1,424,750,000   1,424,750,000
  da_total          78,240,102,000  47,317,397,000   ← v3 = depreciation+amortization 정확히 일치
                                                        v2 는 그보다 훨씬 큼(제3의 성분 포함)
  ebitda           202,325,617,096 171,402,912,096
  ```

  > **★2026-08-30 정정 — 이건 P1A가 아니다.** 처음엔 P1A(lease/borrow 카탈로그 분해)와
  > 같은 문제로 오판했으나, `docs/plans/p1a_p1c_implementation_plan_2026-08-22.md`를
  > 다시 확인한 결과 **P1A는 `bs.lease_liability`(BS 리스부채 유동/비유동)·
  > `cf.borrowings_proceeds/_repaid`(CF 차입 단기/장기) 분해다 — `net_debt`/
  > `short_term_debt`/`long_term_debt`에 영향을 줄 뿐 `ebitda`/`da_total`과는 무관**하다.
  > (§Phase 0-1의 net_debt 불일치 3~4건은 P1A 소관일 수 있다 — 그건 별개로 맞다.)
  >
  > 진짜 원인은 v2의 `rule_additive_da`(`fin2/standardize/rules.py:220-243`)에 있다 —
  > 회사가 "감가상각비 및 무형자산상각비"를 **결합 한 줄로 공시**하면서 동시에
  > 사용권자산상각비 등을 **별도 줄로도 공시**하면, v2는 `da_total = 결합값(da_direct) +
  > 별도계상분(dep+amo)` 을 **의도적으로 더한다**(주석의 실측 근거: 00176914사, 결합값만
  > 취하면 200억 누락). `v3의 note_da.py`가 이 "결합값+별도계상분" 이중 처리를 하는지는
  > **미확인** — da_total이 `depreciation+amortization`과 정확히 일치하는 걸 보면 안 하고
  > 있을 가능성이 높지만, 정확한 재현(note_lines 원문 대조)은 이번 세션에서 안 함.
  > **별도 조사·설계 필요, 이번 세션은 여기서 기록만 하고 중단**(사용자 결정, 2026-08-30).

  **결론**: pbr(및 추정상 per/psr)은 2012+ 구간에서 v3 이식이 안전. **ev_ebitda는
  이 결합공시 로직(가칭)이 v3에 이식되기 전까지 이식하면 안 된다** — 표본의 73%(11/15)가
  두 자릿수 %의 실질적 차이를 보여, 사용자가 보는 EV/EBITDA 배수가 상당히 달라진다.
  net_debt는 P1A(기존 설계 문서 있음, 미실행) 소관으로 별도.

### Phase 1 — matview 재정의 (한 커밋)

- [ ] **1-1.** `collector/db.py`의 마이그레이션 목록에 새 항목 추가 —
      `DROP MATERIALIZED VIEW IF EXISTS valuation_daily;` → `CREATE MATERIALIZED VIEW
      valuation_daily AS (D1의 새 SELECT) WITH NO DATA;` → 같은 마이그레이션 안에서
      unique index(`ux_valuation_daily_corp_date`) 재생성.
      (matview는 `CREATE OR REPLACE`가 안 된다 — DROP+CREATE 필수, 기존 `standard_financials`
      의 v2→v3 스왑은 일반 VIEW라 `CREATE OR REPLACE`를 썼지만 이건 다르다.)
- [ ] **1-2.** 마이그레이션 적용 직후 `REFRESH MATERIALIZED VIEW valuation_daily`(non-concurrent
      최초 1회 — WITH NO DATA 상태에선 CONCURRENTLY 불가) 1회 수동 실행해 데이터 채움.
- [ ] **1-3.** `scripts/refresh_valuation_daily.py`/`scripts/nightly_valuation_refresh.py`는
      코드 변경 불필요(matview 이름 그대로, REFRESH CONCURRENTLY 대상 동일).

### Phase 2 — `cf_da_sync`/`expense_nature_sync` 분리 (별도 커밋, D3)

- [ ] **2-1.** 두 파일에서 `standardize_corp`/`derive_quarters_corp`/`calendarize_corp`
      호출 제거, import 정리.
- [ ] **2-2.** 반환 dict·로그 문구 정리(`std_recalc`/`n_std`가 항상 0이 되는 값 제거).
- [ ] **2-3.** `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` §3.10과
      `std_v3_daily_wiring_plan_2026-08-30.md` §2-3에 "잔여 경로 완전 종료" 기록.

---

## 4. 검증 계획

- [ ] **4-1.** Phase 0-1/0-2 diff 결과 — 불일치가 크면(스케일·건수 모두) Phase 1 착수 전
      원인부터 규명(이 세션의 다른 계획들과 동일한 원칙, [[feedback-verify-against-source]]).
- [ ] **4-2.** 회귀 테스트 `pytest tests/ fin2/tests/`(회귀 0 기준은 기존 baseline과 동일).
- [ ] **4-3.** 재정의 직후 표본 corp의 `per`/`pbr`/`ev_ebitda` 시계열을 이식 전후로 비교
      (그래프 아니라도 값 diff로 충분) — 사용자가 실제로 보는 화면(밸류에이션 밴드 차트)
      이므로 눈으로 한 번 더 확인 권장(§viz-app-status 참고 — `streamlit run app/main.py`).
- [ ] **4-4.** `scripts/dq_assertions.py`의 `valuation_daily_stale` 어서션이 계속 통과하는지
      (trade_date 최신성 — 로직 자체는 안 바뀌므로 회귀 없어야 정상).
- [ ] **4-5.** Phase 2(cf_da_sync 분리) 후 — 표본 FY2024+ CF-미태깅 기업 하나를 골라
      `sync_cf_da`가 `fact_v2`엔 여전히 쓰고 std_v2엔 더 이상 안 쓰는지 직접 확인.

---

## 5. 롤백

- **Phase 1**: §2 D4 — 이전 `CREATE MATERIALIZED VIEW` SQL을 그대로 재실행 + refresh.
  기저 테이블 무변경이므로 위험 없음.
- **Phase 2**: 제거한 세 줄(`standardize_corp`/`derive_quarters_corp`/`calendarize_corp`)을
  되돌리면 즉시 원복 — 이 세 줄은 다른 로직과 얽혀 있지 않다(§1-2의 표 참고).

---

## 6. 명시적 범위 밖

- **is_stub의 v3 PK 재도입**(결산월 변경 stub 기간을 v3가 별도 grain으로 구분) —
  `std_v2_retirement_port_to_v3_2026-08-22.md` Phase 2(`is_stub` v3 PK 확장)가 이미
  별도 트랙으로 잡아둔 사안. 이 문서는 그 트랙 완료를 기다리지 않고 "0.064%는 무시"
  선례로 우회한다 — 재도입은 그 문서 소관.
- **pre-1999 249행 정책 결정**(§8, 이 문서의 D2) — 별도 사용자 결정.
- **`app/data/extended.py`/`shareholder_return.py`의 std_v2 직접 조인 정리** —
  `std_v3_daily_wiring_plan_2026-08-30.md` §8에 이미 등재된 별개 항목. 이 문서가 다루는
  `valuation_daily`와는 다른 소비처라 범위에 넣지 않았다(필요하면 같은 패턴으로 후속).
- **`std_financials_v2`/`std_financials_calendar` 물리 드롭** — 이 문서(§D3)까지 끝나야
  "쓰기는 0"이 되지만, **읽기 폴백**(뷰의 v2 UNION 브랜치, 16,866행)이 남아있는 한 드롭은
  안 된다 — 그건 §8의 최종 단계.

---

## 7. 참고

- `docs/plans/std_v3_daily_wiring_plan_2026-08-30.md` — Phase 2 §2-3에서 이 잔여 경로를
  재확인, §8에 valuation_daily 이식이 이미 백로그로 등재.
- `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` §3.9/§3.10(R17) — 잔여 경로
  최초 식별, "이식할 로직 없음, 배관 문제"라는 결론의 출처.
- `scripts/gateb_audit.py:137-139,242` — is_stub 0.09%(v2 기준) 무시 결정의 선례.
