# std_v3 데일리 배선 — 작업 계획서 (2026-08-30)

> **이 문서의 위치.** `docs/plans/std_v3_daily_wiring_scoping_2026-08-22.md`(조사 메모)의
> 후속 **설계 확정본**이다. 스코핑 메모가 "다음 세션에서 결정"으로 남긴 미결정 4건에
> 권고안과 근거를 붙였다.
>
> **미구현 — 승인 대기.** 이 문서는 설계까지만 담는다. 구현은 사용자가 별도로 지시한 뒤
> 착수한다([[feedback-plan-then-wait]]).

---

## 0-0. ★ 상위 방향 (사용자 확정, 2026-08-30 — 잠금)

> "layer2, layer3 모두 신세대로 옮겨가고 부족한 것을 채워가는 방향으로 해서
> **이중으로 채우고 관리하지 않도록** 하자."

- **구세대를 남겨두고 병행 운영하는 선택지는 폐기됐다.** 부족분은 구세대를 유지해
  메우는 게 아니라 **신세대를 채워서** 해결한다.
- 두 축(계층2·계층3)은 소비자와 작업 내용이 달라 **따로 진행**하되 **목적지는 하나**다 —
  각 계층에 살아 있는 테이블은 하나씩.
- 이 문서는 그중 **계층3 축의 첫 단계**(데일리 배선)다. 계층2 축(`fact_v2`)은 §8.

---

## 0-A. ★ 용어 — "v2"는 두 개다 (혼동 주의)

`fact_v2`의 "v2"와 `std_financials_v2`의 "v2"는 **서로 무관한 세대 카운터**다.
같은 접미사 때문에 하나로 묶기 쉬운데, **폐기 축이 다르고 같이 죽지 않는다.**

| 축 | 구세대 | 신세대 | 구세대 크기 | 소관 |
|---|---|---|---|---|
| **계층2(추출)** | `financial_facts` → **`fact_v2`** | **`report_lines`** · `note_lines` | 55 GB | **별도 트랙** |
| **계층3(표준화)** | **`std_financials_v2`** + `std_financials_calendar` | **`std_financials_v3`** | 633 MB | **T9 = 이 문서** |

- `financial_facts`는 이미 DB에서 드롭됐다(2026-08-30 확인: `relation does not exist`).
  즉 `fact_v2`의 "v2"는 **계층2 테이블의 2세대**라는 뜻이다.
- 의존 방향은 `fact_v2 → std_v2` **단방향**이다. `std_v2`를 지워도 `fact_v2`에는
  **std_v2와 무관한 소비자가 셋** 남는다 — `statement_source`(`fin2/reconcile.py`),
  `extended_financials` 뷰(앱 확장 재무항목), `line_audit`(Gate B Phase B).
- **이 문서는 계층3 축만 다룬다.** `fact_v2`(55 GB) 폐기는 `report_lines`가 이미
  대체했으므로 정당한 목표지만 소비자·작업내용이 달라 별도 트랙이다(§8).

> **T9의 회수분은 633 MB다.** DB 용량이 목적이라면 실익은 전부 계층2 축에 있다.
> T9의 동기는 용량이 아니라 **이중 유지보수 제거**와 **데일리 감사 정합성**이며,
> 둘 다 Phase 1 한 번으로 해소된다.

---

## 0. 왜 지금인가

`std_v2` 폐기 트랙(T9)에서 **쓰기를 멈추는 것을 막고 있는 유일한 항목**이다. 읽기 폴백
(뷰의 v2 UNION 브랜치, 16,866행)은 v3가 커버리지를 따라잡을 때까지 남겨두면 되지만,
**쓰기**는 이 배선이 없으면 영원히 못 끈다.

현 상태를 한 줄로: **`collect_new.py`(데일리)는 `std_financials_v3`를 절대 만들지 않는다.**
v3는 `scripts/build_std_v3.py`를 사람이 돌릴 때만 채워진다(2026-08-21 발견).

그래서 지금 매일 벌어지는 일:

| | 현재 | 배선 후 |
|---|---|---|
| 신규 필링의 표준화 산출물 | std_v2 **만** | std_v2 + std_v3 |
| 데일리 Gate B·DQ 감사 대상 | std_v2 (`source="v2"` 고정) | std_v3 |
| v3 커버리지 | 사람이 배치를 돌린 시점에 고정 → **매일 벌어짐** | 매일 따라감 |
| `fact_v2` | 매일 증가(현재 55 GB) | 여전히 증가(쓰기 제거는 별도 후속) |

★ **이 배선만으로는 std_v2 쓰기가 멈추지 않는다.** 이 계획의 목표는 "v3가 매일 채워지고,
데일리 품질 게이트가 v3를 본다"까지다. v2 쓰기 제거·테이블 드롭은 읽기 소비자 4갈래
이식이 끝난 뒤의 별도 트랙이다(§8 범위 밖).

---

## 1. 실측 근거 (2026-08-30 확인)

설계 판단의 전제가 되는 사실들. 전부 코드/로그/DB로 직접 확인했다.

### 1-1. 비용은 무시할 수 있다 — 0.74초/기업

`build_v3.log`(전수 빌드 기록):

```
[build-std-v3] 대상 corp 2,534
[build-std-v3] 완료 — 2534 corp · 185,266 rows · 1885s
```

→ **1,885s / 2,534 corp = 0.74s/corp**. 데일리 신규 대상은 보통 1~5개사, 배치 상한이
50개사(`_run_standardize_batches`의 `batch_size=50`)이므로 **최악의 배치도 약 37초**.
④ 자체가 기업당 44.4초인 것과 비교하면 1.7% 수준의 추가 비용이다.

### 1-2. `build_corp()`는 멱등이다

`fin2/layer3/build.py:127-134` — 기간·basis 단위 **delete-then-insert**:

```python
session.execute(
    delete(StdFinancialV3).where(
        StdFinancialV3.corp_code == corp,
        StdFinancialV3.fiscal_year == fy,
        StdFinancialV3.fiscal_period == period,
        StdFinancialV3.statement_type == basis,
    )
)
```

`year_min` 밖의 기간은 건드리지 않는다 → 재실행 안전, 부분 실행 안전. 런북 A1
("멱등, corp 리스트를 인자로 받는 형태") 충족.

### 1-3. `gateb_audit.py`는 이미 `source="v3"`를 완전 지원한다

`scripts/gateb_audit.py`의 `args.source`가 감사 대상 조회(L159)·rcept 해석(L167, L211)·
`face_audit` upsert 키(L242, L260-263)까지 전 구간에 배선돼 있고, `face_audit` 테이블은
`source_version`을 PK 구성요소로 갖는다. **감사 쪽은 파라미터 한 줄 변경이면 된다** —
새로 만들 코드가 없다.

### 1-4. `build_corp`는 계층2(`report_lines`)를 읽는다 — 순서 제약이 생긴다

`build_std_v3.py`의 대상 선정이 `SELECT DISTINCT corp_code FROM report_lines`이고
`build_corp` → `build_merged_lines`가 `report_lines`를 소비한다. 데일리에서 `report_lines`를
채우는 것은 **④-3 `_sync_layer2_lines`(xml 경로)** 와 **④-4 `_sync_xbrl_instance_lines`
(xbrl_zip 경로)** 두 개다.

→ **v3 빌드는 ④-4보다 뒤여야 한다.** ④-3만 끝난 시점에 돌리면 xbrl_zip-only 기업이
누락된다. 사용자가 이미 확정한 배선 위치(`std_v2_retirement_port_to_v3_2026-08-22.md:87`,
**④-6 신설 = ④-4 직후 · ⑤ Gate B 직전**)가 이 제약과 정확히 일치한다.

### 1-5. ④-4는 배치 루프 **밖**에 있다 — ④-6도 밖이어야 한다

`_run_standardize_batches()`(L118-120)는 배치마다 `_sync_cf_da` / `_sync_layer2_lines`
(④-3) / `_sync_shares_transcribe`(④-5)를 돌리지만, **④-4는 배치 루프 밖**에서 별도
셀렉터(`needs_xbrl_instance_corps`)로 한 번 돈다(메인 L862-866, 재개 L752-756).

→ ④-6을 배치 루프 안에 넣으면 ④-4 이전이 되어 §1-4 제약을 위반한다.
**④-6은 배치 루프 밖, ④-4 직후에 놓는다.**

---

## 2. 확정 전제 (재확인 불필요)

| 항목 | 확정 내용 | 출처 |
|---|---|---|
| 배선 위치 | 데일리 내부 **④-6 신설** — ④-4 직후, ⑤ Gate B 직전 | 사용자 기확정, `std_v2_retirement_port_to_v3_2026-08-22.md:87` |
| 두 call site | 메인 + `--standardize-only` 재개 경로 **둘 다** | 런북 A3 |
| 실패 격리 | 비치명적 `try/except` + `logger.warning` | 런북 A2 |

---

## 3. 설계 결정 — 스코핑 메모의 미결정 4건

### D0. 셀렉터 전환 — 실측으로 블로커 아님이 확인됨 ★

`collect.needs_standardize_corps()`(`app/data/collect.py:96-117`)는 **std_v2 존재를
"처리 완료" 표시로** 쓴다. 그래서 std_v2 쓰기를 빼려면 **셀렉터를 반드시 같이** 바꿔야
한다 — 안 그러면 매일 같은 기업을 무한 재처리한다.

당초 이 전환이 "v3 결측분이 쏟아진다"는 이유로 위험하다고 봤으나(초안 D4), **실측 결과
반대였다**:

| 셀렉터 기준 | 대상 기업 | corp-period |
|---|---|---|
| 현재(`std_financials_v2`) | 1,315 | — |
| **v3로 전환 시** | **1,336** | 13,336 |
| **차이** | **+21개사** | — |
| v3 기준 + `fy>=2015` 한정 | **4개사** | **33** |

1,315라는 기존 백로그는 대부분 pre-2015 구간이고 v2 셀렉터에서도 이미 있던 것이다.
**전환 순증은 21개사**에 불과하다.

**권고: Phase 1에서 셀렉터도 같이 전환한다.** 부수 이득이 크다 — 셀렉터가 v3 기준이면
데일리가 건드리는 기업마다 **v3 결측을 스스로 메운다**(self-healing). §8의 16,617행
백필 트랙을 데일리가 점진적으로 갉아먹는다.

> **초안 D4 철회.** "셀렉터를 v3로 바꾸면 16,617행이 데일리로 쏟아진다"는 초안의 우려는
> 실측(위 표)으로 반증됐다. 셀렉터는 이번 범위 **안**이다.

### D1. Gate B `source` 전환 방식 ★가장 중요

**스코핑 메모의 선택지**
- (a) 같은 날 두 번 감사 — v2 즉시 + v3는 하루 지연
- (b) v3 빌드를 ④ 직후로 당겨 같은 실행 안에서 만들고 감사는 v3만

**배선 위치가 ④-6(⑤ 직전)으로 확정된 시점에서 (a)는 이미 탈락**했다. v3가 ⑤ 전에
만들어지므로 지연 감사를 할 이유가 없다.

**그러나 (b)를 그대로 쓰면 false-green이 형태만 바꿔 재발한다.** ④-6은 런북 A2에 따라
비치명적으로 감싸므로 **실패해도 파이프라인이 계속 간다**. 그 corp는 v3 행이 없는데
⑤가 `source="v3"`로 감사하면 → 감사 대상 0건 → "이상없음". `collect_new.py:160-165`
주석이 경고한 바로 그 함정이 "v3 미배선" 대신 "v3 빌드 실패"를 원인으로 재현된다.

**권고: `source="v3"` 단독 전환 + ④-6 실패의 명시적 집계.**

false-green을 막는 데 필요한 것은 병행 감사가 아니라 **"감사 대상 0건"이 조용히
통과하지 못하게 하는 것**뿐이다. ④-6이 corp별 실패 리스트를 반환하고(Phase 1-1),
⑤가 그 corp를 **명시적 실패로 집계**하면 이 함정은 닫힌다.

> **초안의 2단계(v2·v3 병행 감사 14일) 철회.** D0 실측으로 셀렉터 전환이 안전함이
> 확인된 이상, 감사만 14일간 이중으로 돌릴 근거가 없다. 병행 감사는 비용(감사 2배)에
> 비해 얻는 것이 "판정 차이 관측"뿐인데, 그건 Phase 0-3의 표본 대조로 착수 전에
> 확인하는 편이 빠르고 싸다.

### D1-b. std_v2 쓰기 제거를 Phase 1에 포함할 것인가

**권고: 포함하되 Phase 2로 분리한다(같은 세션, 별도 커밋).**

D0 덕분에 기술적 블로커는 없다. Phase 1이 끝나면 아래 4개가 전부 v3를 보므로
`process_corp`의 `standardize`·`quarterly`·`calendar` 단계를 빼도 파이프라인은 성립한다.

| 바꿀 것 | 현재 | 바꿀 값 |
|---|---|---|
| ④-6 | 없음 | `build_corp` 호출 |
| 셀렉터 | `NOT EXISTS std_financials_v2` | v3 기준(D0) |
| dq3 체크(`collect_new.py:174`) | `std_financials_v2 … data_quality>=3` | v3의 같은 컬럼 |
| Gate B `source` | `"v2"` | `"v3"` |

**★ 다만 잃는 것이 있다 — 이산분기와 달력 정규화.**

`fin2/layer3/`에는 `quarterly`·`calendar`에 해당하는 모듈이 **없다**(모듈 목록:
`build.py` `combine.py` `industry_profiles.py` `note_da.py`). `is_discrete`는
`std_v2`의 PK 구성요소일 뿐 v3엔 컬럼 자체가 없고(`collector/models.py:750`),
`std_financials_calendar`는 정의상 "Layer 1(`std_financials_v2`, as-filed)의
**이산분기**를 `period_end`로 달력분기에" 매핑한 것이라(`models.py:831`) v2가 멈추면
같이 멈춘다.

- **영향**: 분기별 3개월 실적, 결산월 다른 기업의 비교 정규화가 신규 기간에 대해 중단.
  현재 뷰·스크리너 미사용이라 즉각적 문제는 없다(사용자 확인, 2026-08-30).
- **복구 가능성**: v3는 `report_lines`에서 언제든 재생성되므로 **정보 손실이 아니다.**
  §8의 소비자 재구현 단계에서 v3 기반 `quarterly`/`calendar`를 만든 뒤 소급 생성하면
  공백이 메워진다.
- **사용자 결정(2026-08-30)**: 소비자는 현재 미사용이므로 **재구현 시점에 v3만 쓰도록**
  만든다 → 이산분기·달력도 그 소비자 목록에 포함해 함께 이식한다.

### D2. `build_corp`의 `year_min`

**권고: `year_min=2015`(= `build_std_v3.py` 기본값 유지).**

- 데일리가 다루는 신규 필링은 당연히 2015 이후다.
- `build_corp`는 그 corp의 **2015 이후 전 기간**을 다시 만든다 — 신규 기간만이 아니다.
  이건 낭비가 아니라 이득이다: 정정본이 늦게 들어와 과거 기간이 바뀐 경우가 자동 반영되고,
  그 corp의 v3 결측 기간이 있으면 **덤으로 메워진다**(§8의 백필 트랙을 조금씩 갉아먹는다).
- pre-2015(1999~2014) 구간은 이 경로로 건드리지 않는다 — 별도 백필 트랙 소관(§8).
  `year_min`을 1999로 낮추는 것은 비용·회귀 범위가 달라지므로 **이번 범위에서 제외**한다.

### D3. `face_audit` v2/v3 이중 관리

**권고: 이번 트랙에서는 유지, 정리는 후속.**

Phase 1이 애초에 두 source를 동시에 쓰므로 이중 관리가 전제다. Phase 2 이후에도 과거
v2 감사 결과는 뷰의 v2 폴백 브랜치(`fa.source_version='v2'` 조인)가 계속 소비한다 —
읽기 폴백이 살아 있는 한 지울 수 없다. **v2 감사 레코드 정리는 뷰의 v2 브랜치를 걷어낼
때 같이** 한다(§8).

### D4. ④ 셀렉터를 v3 기준으로 바꿀 것인가

**→ D0으로 이동·철회.** 초안은 "바꾸지 않는다"였으나 실측(+21개사)으로 뒤집혔다.
**바꾼다** — 근거는 §3 D0 참고.

---

## 4. 구현 Phase

### Phase 0 — 착수 전 실측 (읽기 전용, 30분) — ★ 완료 (2026-08-30)

- [x] **0-1.** 최근 7일 데일리 로그에서 ④ 대상 corp 수 분포 확인 → §1-1 비용 추정 검증.
- [x] **0-2.** 표본 3개사(신규 필링 보유)에 `build_std_v3.py --corp <3개사>` 수동 실행 →
      소요 시간·행 수 실측, DB diff로 기존 행 무손상 확인.
- [x] **0-3.** 같은 3개사에 `gateb_audit.py --corp <..> --source v3 --recheck` 실행 →
      v2 감사 결과와 판정 대조. **여기서 대량 불일치가 나오면 배선 전에 원인부터 규명**한다.

**실측 결과**

0-1. `logs/dart_202608{24..28}.log` 5일치에서 `[standardize2] corp=` 유니크 카운트:

| 날짜 | ④ 대상 corp 수 |
|---|---|
| 08-24 | 3 |
| 08-25 | 2 |
| 08-26 | 6 |
| 08-27 | 3 |
| 08-28 | 6 |

→ 관측 범위 2~6개사/일. §1-1이 가정한 "1~5개사, 배치상한 50개사" 안에 들어온다
(08-26/08-28의 6개사는 가정 상한을 살짝 넘지만 배치상한 50과는 거리가 멀어 비용
결론에 영향 없음).

0-2. 표본: `00109514`(168행) · `00163512`(186행) · `00207375`(186행), 총 540행.

```
[build-std-v3] 대상 corp 3
[build-std-v3] 완료 — 3 corp · 276 rows · 6s
```

3개사·6초(≈2s/corp, 소규모 실행이라 고정 오버헤드 비중이 커서 §1-1의 대량 평균
0.74s/corp보다 높게 나옴 — 예상된 차이). 실행 전/후 `std_financials_v3`
전체 컬럼(`built_at` 제외) 스냅샷 540행을 대조한 결과 **diff 0줄** — 기존 행
완전 무손상 확인.

0-3. 같은 3개사에 `gateb_audit.py --corp-file <..> --source {v2,v3} --recheck --no-commit`
(주의: `--corp`는 단일값만 받는다 — 복수는 `--corp-file` 필요, 문서에 반영 필요할 수 있음):

| | source=v2 | source=v3 |
|---|---|---|
| 행 감사 | 309행 (pass 301 / fail 0 / pending 8) | 396행 (pass 292 / fail 0 / pending 104) |
| in-scope 일치율 | 100.0% | 100.0% |
| 필드 | PASS 6108 / FAIL 0 | PASS 6015 / FAIL 0 |
| 보고서 gate(Phase B) | pass 178 / **fail_a 20** / pending 0 | pass 175 / **fail_a 20** / pending 3 |

**판정: 대량 불일치 없음 — 배선 진행에 지장 없음.**
- `fail_a`(차단 등급) 20건이 v2·v3 **완전히 동일** — 판정이 뒤집힌 corp 0건.
- 늘어난 건 전부 `pending`(코드 주석 기준 "범위밖" — pass/fail 어느 쪽으로도 등급이
  매겨지지 않은 것이지, 오판정이 아니다: 행 8→104, 보고서 0→3). v3가 v2보다 커버리지가
  넓어(D0의 +21개사 순증과 같은 맥락) 아직 대조 기준이 없는 기간이 pending으로 잡히는
  것으로 해석되며, 이는 §Phase 0-3이 경계한 "대량 불일치"(판정 자체의 충돌)가 아니다.

**결론: Phase 0 전 항목 통과. Phase 1 착수를 막을 근거 없음.** (Phase 1은 여전히
사용자의 별도 실행 지시를 기다린다 — [[feedback-plan-then-wait]].)

### Phase 1 — v3 배선 + 축 전환 (한 커밋) — ★ 구현·검증 완료(커밋 대기, 2026-08-30)

- [x] **1-1.** `scripts/collect_new.py`에 `_sync_std_v3(corps)` 신설.
  - `fin2.layer3.build.build_corp`를 corp 루프로 호출, 기업별 `try/except`로 격리.
  - 함수 전체를 다시 비치명적으로 감싸고 `logger.warning` (런북 A2).
  - 반환: `{"corps": n_ok, "rows": n_rows, "failed": [corp, ...]}` —
    **실패 corp 리스트를 반드시 반환**한다(1-6에서 쓴다).
  - docstring에 "두 call site에서 불린다" 명시 (기존 ④-3/④-4/④-5와 동일 관례).

- [x] **1-2. ★ 메인 경로 배선** — `collect_new.py:866` `_sync_xbrl_instance_lines(...)`
      **직후**, `_verify_and_log(agg, args)`(⑤) **직전**.

- [x] **1-3. ★ 재개 경로 배선** — `collect_new.py:756` 같은 위치
      (`_sync_xbrl_instance_lines(xbrl_affected)` 직후, `_verify_and_log` 직전).
      **여기를 빠뜨리는 것이 이 프로젝트에서 가장 흔한 누락이다**(런북 A3).

- [x] **1-4. 셀렉터 전환(D0)** — `app/data/collect.py:96-117`
      `needs_standardize_corps()`의 `NOT EXISTS` 대상을 `std_financials_v2` →
      `std_financials_v3`로. docstring도 갱신("std_v2에 없는" → "std_v3에 없는").

- [x] **1-5. dq3 체크 전환** — `collect_new.py:174`의
      `SELECT count(*) FROM std_financials_v2 … data_quality>=3`을 v3 기준으로.
      (v3는 `version` 컬럼이 없어 `AND version=1` 조건도 함께 제거.)

- [x] **1-6. Gate B `source` 전환 + false-green 차단(D1)**
  - `collect_new.py:165`의 `source="v2"` → `"v3"`.
  - `_verify_and_log` 집계에 **1-1이 반환한 실패 corp를 명시적 실패로 승격** —
    감사 대상 0건이 "이상없음"으로 통과하지 못하게.
  - **L152-165의 기존 주석은 지우지 말고 갱신**한다 — 왜 v2 고정이었는지, 무엇이
    바뀌어 이제 v3인지, false-green을 무엇으로 막는지.
    (이 주석이 2026-08-17에 실제 버그를 막았다.)

- [x] **1-7.** 로그 문구 — `[collect] ④-6 계층3 std_v3 — 기업 N · 행 M` 형식으로
      기존 ④-2~④-5와 통일. 실패 corp 수도 함께 찍는다.

**구현 결과 요약** — `scripts/collect_new.py`(+105/-19줄) · `app/data/collect.py`(+10/-1줄).
`_sync_std_v3()`는 corp별 `with get_session()` 블록(개별 커밋)으로 격리해, 한 corp의
실패가 이전 corp들의 이미 커밋된 결과를 롤백하지 않게 했다(`build_std_v3.py`의 배치당
단일 커밋과 다른 선택 — 데일리 배치는 훨씬 작아 corp당 커밋 오버헤드가 무시할 만하고,
격리 이득이 더 크다). `_verify_and_log`는 `ok`(표준화 성공 corp)가 비어 있어도
`std_v3_failed`가 있으면 게이트를 계속 돈다(`run_dq_gate` 스킵 대신 빈 summ로 대체) —
표준화 자체는 성공했는데 std_v3 빌드만 실패한 경우도 놓치지 않기 위해서다.

### Phase 2 — std_v2 쓰기 제거 (같은 세션, 별도 커밋) — ★ 구현·검증 완료(커밋 대기, 2026-08-30)

Phase 1 검증(§6)이 끝난 뒤. 커밋을 분리해 롤백 단위를 유지한다.

- [x] **2-1.** 데일리의 `process_corp` 호출에서 `stages`를 축소 —
      `("extract", "reconcile")`만 남기고 `standardize`·`quarterly`·`calendar` 제외.
      (`run.py:2914` 시그니처가 이미 `stages` 인자를 받는다 — 새 코드 불필요.)
      **검증**: 표본 corp(00109514)에 직접 호출 — `{'e_files': 131, 'e_facts': 29034,
      'r': 307, 's': 0, 'q': 0, 'c': 0}`, `std_financials_v2` 행수 실행 전후 250→250
      (**무변동**) 확인.
- [x] **2-2.** `agg`의 `s`/`q`/`c` 카운터와 로그 문구 정리(0으로 고정될 값 제거) —
      "std_v2 N"류 로그를 `fact N`(추출 사실행)으로 교체, 배치 완결 로그도 "layer2+
      주식수 반영"으로 정리.
- [x] **2-3. ★ 이산분기·달력 중단 + std_v2 쓰기 잔여 경로를 문서에 남긴다.**
      ★★ **구현 중 발견 — Phase 2는 std_v2 쓰기를 "완전히" 제거하지 못한다.**
      `_sync_cf_da`(collect_new.py)가 부르는 `cf_da_sync.sync_cf_da` /
      `expense_nature_sync.sync_expense_nature`는 대상 SELECT 자체를
      `std_financials_v2 WHERE depreciation IS NULL`에서 직접 골라, 그 corp에 대해
      **독자적으로** `standardize_corp`(v2)→`derive_quarters_corp`→`calendarize_corp`
      를 다시 돌린다 — `process_corp`의 stages 축소와 완전히 별개인 경로다.
      - **브랜드뉴 기간**(오늘 처음 생긴 fy/period)은 애초에 std_v2 행이 없어 이
        SELECT의 대상이 되지 않는다 → **신규 std_v2 쓰기는 실제로 없다.**
      - 그러나 **Phase 2 이전에 이미 만들어진 std_v2 행 중 depreciation NULL인 것**은
        그 corp이 이후 어느 날 다른 이유로 `ok_corps`에 다시 들어올 때마다 계속
        재표준화(recompute)된다. 이 경로는 std_v3와 무관하고(std_v3는 `note_da.py`로
        D&A를 이미 직접 처리) v2 전용 패치 메커니즘이다.
      - `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` R17이 이미 같은
        문제를 지적했다("이 단계를 걷어내면 extended_financials가 stale — 폐기
        계획에서 §3.9와 함께 다룰 것"). **그 문서의 결정대로 이번 Phase 2에서는
        손대지 않고 남겨둔다** — §8 소비자 이식(`extended_financials`) 트랙에서
        같이 정리한다.
      - 코드에 이 잔여 경로를 상세히 주석으로 남겼다(`_run_standardize_batches`
        docstring, `collect_new.py`).
      - **이산분기·달력**: D1-b대로 이 Phase 2 커밋(2026-08-30, `scripts/collect_new.py`
        의 `_worker` stages 축소분) 이후 신규 기간에 대해 중단. 소급 생성 필요 범위 =
        이 커밋 이후 ~ §8 "이산분기·달력을 v3 기반으로 신규 구현" 완료 시점까지 새로
        생기는 fy/period 전부. `std_v2_retirement_port_to_v3_2026-08-22.md`에도 동일
        내용 교차기록(§9-1).
- [x] **2-4.** `fact_v2`·`statement_source`는 **건드리지 않는다** — 계층2 축 소관(§0-A).
      (`process_corp`의 "extract"/"reconcile" stage가 그대로 남아 이 둘을 계속 채운다 —
      실측으로 확인: `e_facts`·`r` 카운트가 이전과 동일하게 나옴, 위 2-1 검증 참고.)

---

## 5. 런북 체크리스트 대조

`docs/runbook_new_parser_pipeline_integration.md` 기준.

| 항목 | 상태 | 비고 |
|---|---|---|
| A1 로더 함수(멱등·corp 리스트·실패 격리) | Phase 1-1 | 멱등성은 §1-2로 이미 확인 |
| A2 비치명적 래퍼 | Phase 1-1 | |
| A3 ★ 두 call site | Phase 1-2 / 1-3 | **최우선 확인 항목** |
| A4 순서(추출 → store_facts → standardize → …) | §1-4 / §1-5 | ④-4 이후, 배치 루프 밖 |
| A5 이중 계상 방지 | 해당 없음 | v3는 별도 테이블, `fact_v2` 셀 충돌 없음 |
| B 소급 백필 | **범위 밖** | §8 — 16,617행 백필은 별도 트랙 |
| C 검증 | §6 | |

---

## 6. 검증 계획

- [x] **6-1. 회귀 테스트** — `pytest tests/ fin2/tests/`
      (루트 범위로 돌리면 NAS 심링크에서 멈춘다 — [[feedback-pytest-scope-raw-report-symlink]]).
      기준: 기존 무관 실패 1건(`test_biz_section.py::test_lxintl_facility_table_dropped`)
      외 회귀 0. **결과: 634 passed, 1 failed(바로 그 기존 무관 실패) — 회귀 0.**

- [x] **6-2. 드라이런** — `collect_new.py --standardize-only --corps <표본 3개사>` 로
      재개 경로를 먼저 태운다(메인보다 부작용 범위가 좁다). 로그에 ④-6이 찍히는지,
      실패 corp 리스트가 올바른지 확인.
      **결과**: `[collect] ④-6 계층3 std_v3 — 기업 3 · 행 276` 정확히 찍힘(§1-7 형식대로),
      배치 순서도 설계대로(④-3/④-5 → 재개완료 → **④-6** → ⑤ 검증). 실패 corp 0(모두 성공).

- [x] **6-3. DB diff** — 표본 3개사의 `std_financials_v3` 행을 실행 전후로 비교.
      기대: 신규 기간 추가 + 기존 기간 값 무변동(정정본이 없었다면).
      **결과: diff 0줄**(신규 필링이 없어 신규 기간도 없었고, 기존 540행 완전 무변동).

- [ ] **6-4. 원문 대조** — 새로 생긴 v3 행 중 1개사를 골라 원문 XML과 직접 대조
      ([[feedback-verify-against-source]] — 집계로 닫지 말 것).
      **보류 — 이번 드라이런엔 "새로 생긴 행"이 없었다**(표본 3개사가 이미 Phase 0-2에서
      최신 상태로 빌드돼 있었음). 실제 신규 필링이 들어오는 다음 실운영 회차(6-5)에서
      새로 생기는 v3 행을 대상으로 이어서 한다.

- [ ] **6-5. 하루 실운영 관찰** — launchd 데일리 1회분 로그 확인.
      ④-6 소요 시간, 실패 corp 수, v2/v3 감사 판정 차이.
      **보류 — 다음 launchd 실행 후 확인 필요**(코드는 배선됐으나 아직 스케줄 실행 안 됨).

- [x] **6-6. Gate B 무영향 확인** — 이 배선은 v3 **행을 새로 만들 뿐** 기존 판정 로직을
      건드리지 않는다. 그래도 표본 재감사로 기존 corp의 등급 전이 0건을 확인한다.
      **결과**: 드라이런의 `fail_a=0`(3개사 전부) 확인. 별도로 같은 3개사에
      `source=v2`/`source=v3` 각각 `--fy-min 2015`로 직접 대조한 결과 `fail_a=20`(양쪽
      완전 동일) · `line_value_diff=144`(양쪽 완전 동일) — **드라이런에서 loud error로
      뜬 `line_value_diff=155`(rollup_corp 기준, gateb_audit 자체 집계 144와는 정의가
      달라 절대값이 다름)는 v3 전환으로 새로 생긴 문제가 아니라 v2에도 이미 있던
      사전조건**이다(등급 전이 0건, false-green 아님 — 오히려 게이트가 원래 하던 대로
      정상 작동해 기존 신호를 그대로 잡아낸 것).

---

## 7. 롤백

단일 지점 롤백이 가능하다 — ④-6 호출 두 줄(메인·재개)을 주석 처리하면 배선 이전 상태와
동치다. `build_corp`가 만든 v3 행은 남지만 **뷰가 v3를 우선 브랜치로 이미 소비하므로
그대로 두는 게 정상**이다(지울 이유 없음). `run_dq_gate`의 source만 `"v2"` 단독으로
되돌린다.

---

## 8. 명시적 범위 밖

이 계획에 **포함되지 않는** 것들. 각각 별도 트랙이다.

### 계층3 축(T9) — 이 문서 이후의 후속

| 항목 | 규모 | 왜 분리했나 |
|---|---|---|
| v3 결측 16,617행 백필(fy≥1999) | 미측정 | 통제된 배치로. 단 D0 셀렉터 전환 후 데일리가 점진 소화 |
| fy<1999 249행 정책 결정 | 249행 | v3 범위 확대 vs 유니버스 제외 — 사용자 결정 필요 |
| **이산분기·달력을 v3 기반으로 신규 구현** | — | **Phase 2에서 중단되는 기능**(D1-b). 소비자 재구현과 함께 |
| 뷰의 v2 UNION 브랜치 제거 | 16,866행 | 위 백필이 끝나야 가능 |
| `valuation_daily` v3 기반 재작성 | 3.3 GB | 읽기 소비자 이식 |
| `app/data/extended.py` · `shareholder_return.py`의 std_v2 직접 조인 정리 | — | 읽기 소비자 이식 |
| `std_financials_v2` · `std_financials_calendar` 드롭 | **633 MB 회수** | 위가 전부 끝난 뒤 |
| P1A lease/borrow 카탈로그 분해 | — | v2→v3 코드 이식의 잔여 조각(`net_debt`/`short_term_debt`/`long_term_debt` 영향). 설계 완료·미실행: `docs/plans/p1a_p1c_implementation_plan_2026-08-22.md` |
| **D&A "결합공시+별도계상분" 합산 로직 이식**(가칭, 신규) | 표본 15건 중 11건이 12.6~70.3% 차이 | v2 `rule_additive_da`(`fin2/standardize/rules.py:220-243`)가 "감가상각비 및 무형자산상각비" 결합공시 라인 + 사용권자산 등 별도계상분을 더하는데, v3 `note_da.py`엔 이 이중 처리가 없는 것으로 추정(미확인). `ebitda`/`da_total`에 영향 — **P1A와 무관한 별개 이슈**, `valuation_daily_v3_migration_plan_2026-08-30.md` §Phase 0-2 참고, 2026-08-30 발견·미착수 |

### 계층2 축 — 병행 트랙 (§0-0의 같은 방향, 별도 작업)

`fact_v2`(55 GB)는 `report_lines`가 이미 대체했지만 `std_v2`와 함께 죽지 않는다.
**DB 용량이 목적이라면 실익은 전부 여기에 있다.**

**실측(2026-08-30) — 문서 포착으로는 이미 잉여다:**
- 필링 커버리지 `only_fact_v2` = **0건**(fy 2015/2020/2025 표본). `report_lines`가
  각각 345/74/76건 더 넓다.
- 공통 컬럼 13개 + 금액(`amount_won`↔`value_won`) → **같은 숫자를 두 번 저장**.
- `fact_v2` 전용 = XBRL 태그 층(`acode`·`acontext_raw`·`canonical_account`·`extra_dims`).
  `report_lines`/`note_lines`엔 `acode`가 **없다**(태그 공통 컬럼은 `adecimal` 뿐).
  `report_lines.context_raw`는 원문 ACONTEXT가 **아님** — 합성 위치 태그
  (`text:BS:con:e:c0:2025`).
- ★ **정보 손실은 없다** — `acode`/ACONTEXT는 원문 XML에 그대로 있고
  `face_audit.read_report_face_xbrl()`이 감사 시점에 파일에서 직접 읽는다(fact_v2 미사용).
  SCE 차원도 `report_lines.col_label`에 텍스트 형태로 대응이 있다.
  → `fact_v2` = 태그 층의 **materialized 인덱스**, 원본 아님.

| 소비자 | fact_v2에서 쓰는 것 | 이식 경로 |
|---|---|---|
| `line_audit`(Gate B **Phase B**) | acode 정확매칭 | **선례 있음** — `face_audit`처럼 파일에서 직접 읽으면 된다. 단 쓰기를 먼저 멈추면 신규 필링 라인 감사가 전부 `MISSING_IN_DB`(기록만·비차단)가 되어 **조용히 무의미해진다** → 이식이 선행 |
| `statement_source`(`fin2/reconcile.py`) | 정본 필링 선택 | v3는 `source_rcepts`로 이미 자체 해결 — 소비처만 확인 |
| `extended_financials` 뷰 | `canonical_account` 조회 | **유일한 설계 질문** — `report_lines`엔 canonical 컬럼이 없고 매핑이 계층3(`account_mapper`)에서 일어나므로 acode 기반이 아니라 **라벨 기반으로 재구성**해야 한다 |
| 그 뒤 `fact_v2` 드롭 | **55 GB 회수** | 위 셋이 끝난 뒤 |

### 비재무 콘텐츠 — 이미 신세대 단일 (조치 불필요)

`biz_section_tables`(사업의 내용 원본 2D 그리드, 590K표/1.9 GB) →
`biz_metrics`(7.8M행)·`order_backlog`. 2026-08-09 `b4b63fc`가 R1 위반(계층2 우회)을
해소해 **이미 정리된 구조**이고 구세대 중복이 없다.

다만 별도 백로그 2건이 관찰됐다(이 트랙 범위 밖):
1. `executives`·`major_shareholders`·`dividend_facts`·`treasury_activity` 등은
   **DART API 직접 호출**이라 `CLAUDE.md`의 "로컬 문서에서 가져올 것" 원칙 밖.
   의도된 예외인지 확인 필요.
2. **사업의 내용의 자유 서술(prose)을 담는 테이블이 없다** — `biz_section_tables`는
   표(grid)만 저장하고 `narrative`는 표에 딸린 각주 성격 문단이다.

---

## 9. 참고

- `docs/plans/std_v3_daily_wiring_scoping_2026-08-22.md` — 이 문서의 전신(조사 메모)
- `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` — ④-6 위치 확정 근거(:87)
- `docs/runbook_new_parser_pipeline_integration.md` — 필수 체크리스트
- `docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md` — `source="v2"`
  고정이 도입된 경위(false-green 게이트 사고)
- `docs/plans/collection_pipeline_restore_2026-07-31.md` §7 — Phase 5 미결정 항목의 출처
