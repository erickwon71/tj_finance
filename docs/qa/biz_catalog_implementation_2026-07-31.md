# B5 · '사업의 내용' 캡션 카탈로그 — 구현 + 파이프라인 편입 기록 (2026-07-31)

대상 항목 근거: [biz_section_items_shortlist_2026-07-31.md](biz_section_items_shortlist_2026-07-31.md)
절차 근거: `docs/runbook_new_parser_pipeline_integration.md`

---

## 1. 무엇을 만들었나

`fin2/extract/biz_catalog.py` — 문서의 **모든 표를 한 번 훑고 캡션으로 분류**하는 범용 추출기.

기존 3종(생산·매출·수주)은 "자기 키워드 소제목을 찾아 그 뒤 표를 읽는" 방식이라 항목을 20개
넘게 늘리면 소제목 탐색 로직이 20벌로 복제된다. 카탈로그는 방향을 뒤집어 주행 1벌 + 규칙 표로
27개 metric 을 커버한다.

### 적재 metric 27종

| 구분 | metric |
|---|---|
| Tier 1 | `product_status` `product_price` `material_status` `material_price` `facility` `segment_fin` |
| Tier 2 | `market_share` `customer` `capex_plan` `ip_right` `order_status` |
| 보험 | `ins_solvency` `ins_premium` `ins_claim` `ins_reserve` `branch` |
| 증권·은행 | `fund_flow` `fund_raise` `fund_use` `brokerage` `underwriting` `derivative` `trust_aum` |
| 건설 | `construction` `inventory` |
| 제약·R&D | `rd_staff` `license` |

### 신규 테이블 없음 — 기존 진입점에 얹었다

`parse_biz_metrics()` 가 이미 (생산 → 매출) 두 파서를 합쳐 `(biz_section_tables, biz_metrics)`
두 리스트를 반환하고, `sync_biz_metrics` 가 rcept 단위 delete-then-insert 로 적재한다.
카탈로그는 여기에 `table_ord` 를 이어붙이는 **세 번째 생산자**로 들어갔다. 결과적으로
스키마 변경·마이그레이션·신규 sync·신규 배선이 모두 불필요하다.

**이중 캡처 차단은 캡션 키워드가 아니라 `grid` 내용 해시(`seen_grids`)로 한다.** 생산/매출
파서는 헤딩 창 방식이라 같은 물리 표를 카탈로그 주행부가 다시 만날 수 있고, 키워드 배제 목록은
규칙이 늘 때마다 구멍이 생긴다. 250사 표본에서 59개 표가 해시로 차단됐다.

### 의도적으로 **안** 읽는 것

`위험관리 및 파생거래` 의 이자율/유동성/신용/외환/자본위험·만기분석 — 재무제표 주석의
재게시라 `note_lines` 에 이미 있다(census F2). 카탈로그 표 2위 규모지만 중복이므로 제외.

---

## 2. 체크리스트 A — 데일리 배선

- [x] **A1 로더 멱등** — 기존 `sync_biz_metrics`(rcept 단위 delete-then-insert) 재사용.
- [x] **A2 비치명적 래퍼** — 기존 `collect_new.py::_sync_biz_metrics` 재사용(try/except + warning).
- [x] **A3 ★ 두 call site 모두** — `collect_new.py:586`(재개 경로), `collect_new.py:690`(메인).
      **새로 배선한 곳은 없다** — 두 call site 모두 `parse_biz_metrics` 를 타므로 자동 편입.
      이 사실을 `_sync_biz_metrics` docstring 에 명시해 두었다(다음 사람이 또 확인하지 않도록).

## 3. 체크리스트 B — 소급 백필 ✅ **완료 2026-07-31 22:10**

전수 백필 완료. 8샤드 병렬(`scripts/launch_biz_backfill.py`), 소요 약 1시간.

| | |
|---|---|
| 적재 기업 | **2,522 / 2,530사 (99.7%)** |
| `biz_metrics` | 1,255,020행 → **7,537,522행** (294MB → 1,616MB) |
| 파싱 오류 | **0** |
| 0행 기업 | 12 (내역 아래) |

**0행 12개사의 정체(전수 확인, 추측 아님)**
- **10개사** — 사업보고서 자체가 0건인 신규 상장사(나무에이엑스·아이엠바이오로직스 제외 전부). 정상.
- **1개사 아이엠바이오로직스** — is_final 이 `[첨부정정]`이라 XML 본문이 없음 → **§5 R2-1 결함 그대로**.
- **1개사 나무에이엑스** — 사업의 내용 표가 2개뿐이고, 그중 매출표 캡션이
  `가. 매출유형별 매출액`. `sales_section`(매출실적/판매실적/매출현황)도 카탈로그도 못 잡는다.
  **버그가 아니라 캡션 규칙 공백** → §7 미분류 캡션 확장 대상.

### 전수 커버리지 (활성 2,530사 기준)

| metric | 기업 | % | metric | 기업 | % |
|---|---:|---:|---|---:|---:|
| product_status | 2,125 | 84.0 | segment_fin | 673 | 26.6 |
| material_status | 2,091 | 82.6 | customer | 538 | 21.3 |
| facility | 1,742 | 68.9 | fund_raise | 515 | 20.4 |
| ip_right | 1,664 | 65.8 | license | 172 | 6.8 |
| material_price | 1,434 | 56.7 | fund_use | 92 | 3.6 |
| product_price | 1,329 | 52.5 | branch | 76 | 3.0 |
| derivative | 1,163 | 46.0 | construction | 57 | 2.3 |
| order_status | 1,151 | 45.5 | fund_flow | 54 | 2.1 |
| rd_staff | 933 | 36.9 | inventory | 39 | 1.5 |
| capex_plan | 915 | 36.2 | brokerage / underwriting | 34 / 34 | 1.3 |
| market_share | 856 | 33.8 | trust_aum / ins_* | 25 / 18~25 | ~1 |

업종특수 항목은 **해당 업종 기준**으로 봐야 한다(전체 대비 %는 무의미):

| 업종 | 기업수 | 해당 지표 보유 | 비율 |
|---|---:|---:|---:|
| 보험(65) | 12 | 12 | **100%** |
| 증권·금융지원(66) | 26 | 22 | 85% |
| 종합건설(41) | 39 | 27 | 69% |
| 의약품(21) `license` | 179 | 96 | 54% |

### 재실행 방법 (중단 시)

```bash
python scripts/launch_biz_backfill.py --shards 8    # 재개(완료 기업 자동 스킵)
```

⚠ **`for ... & done; wait` 형태로 띄우지 말 것.** 워커가 그 셸의 프로세스 그룹에 묶여, 셸이
종료되면 **전부 같이 죽는다**(2026-07-31 실측: 8샤드가 100~200/315 지점에서 전멸).
`launch_biz_backfill.py` 는 `start_new_session=True`(setsid)로 각 샤드를 세션 리더로 분리한다.
데이터는 기업 단위 커밋이라 중단돼도 완료분은 안전하고, 진행 중이던 기업은 롤백된다.

<details>
<summary>구 절차(참고)</summary>

과거분은 자동 재파싱되지 않는다. **아래를 실행해야 과거 보고서에 신규 27종이 채워진다.**

```bash
# 전수 백필(로컬 파일만 읽음 — DART API 미호출, 쿼터 무관). 수 시간 예상.
python scripts/collect_biz_metrics.py --skip-catalog-existing

# 중단 시 같은 명령으로 재개(카탈로그 metric 이 이미 있는 기업만 건너뜀)
```

`--skip-existing` 를 쓰면 **안 된다** — biz_metrics 존재 여부만 보므로 기존 생산지표가 있는
전 기업이 스킵돼 신규 항목이 하나도 안 들어간다. 그래서 `--skip-catalog-existing` 를 신설했다.

> 백필은 rcept 단위 delete-then-insert 라 **기존 생산·매출 지표도 함께 재적재**된다.
> 아래 §5 의 공용 파서 수정 3건이 그 과정에서 같이 반영된다.

**별도 재실행 필요**: `order_backlog` 는 자체 sync 를 쓰므로 §5 의 `_parse_value` 수정을
반영하려면 `python scripts/collect_order_backlog.py` 를 따로 돌려야 한다. **미실행.**

</details>

## 4. 체크리스트 C — 검증

- [x] **회귀 테스트** `tests/test_biz_catalog.py` 24건 신설, 전체 **107 passed**.
      각 케이스는 합성 예제가 아니라 **실측 원문에서 나온 결함**을 고정한다.
- [x] **원문 대조** — 값을 집계로 끝내지 않고 개별 표를 원문 grid 옆에 놓고 확인
      (`scripts/verify_biz_catalog.py --rcept <R> [--metric M]`).
      · 삼성전자 주요제품: DX 1,748,877/58.1% … 기타 △285,155/△9.5% — 원문 일치
      · 한솔홈데코 부문별: 목재 274,860 / -703, 합계 279,817 / 2,333 — 원문 일치
      · 한화생명 수입보험료: 보장성 10,086,939 / 51.0% — 원문 일치
      · 한국컴퓨터 원재료 가격: C-CHIP 제32/31/30기 5.15/3.40/5.32 — 원문 일치
- [x] **적재 실증** — 6사 sync 후 DB 조회로 실제 행 확인(표 178·지표행 5,355, 오류 0).
      한솔홈데코 `segment_fin` 14행이 원문 표와 정확히 일치함을 SQL 로 재확인.
- [x] **표본 스윕** — 250사 × 2회(seed 상이) 파싱오류 0.

### 표본 250사 커버리지(실측)

| metric | 기업 커버 | metric | 기업 커버 |
|---|---:|---|---:|
| material_status | 70% | market_share | 15% |
| product_status | 68% | segment_fin | 15% |
| ip_right | 58% | customer | 12% |
| facility | 54% | license | 6% |
| material_price | 39% | fund_raise / fund_use | 4% / 3% |
| product_price | 33% | 보험·증권·건설 특수 | 각 0.4~2% |
| order_status | 24% | | |

업종특수 항목의 낮은 커버율은 결함이 아니다 — 무작위 표본에 보험 12사·증권 20사뿐이다.
업종 표본에서는 보험 `ins_solvency` 83%, 증권 `fund_use` 65% 였다(shortlist §4).

---

## 5. ★ 작업 중 발견해 함께 고친 **기존** 결함 4건 (공용 파서)

카탈로그가 `_parse_value` / `map_biz_table` 을 공유하면서 드러난 것들. 전부 **조용한 데이터
손실·오염**이었고, 신규 항목뿐 아니라 **기존 capacity/output/utilization/sales 에도 영향**을
준다(위 백필로 반영됨).

| # | 결함 | 실측 영향 | 수정 |
|---|---|---|---|
| 1 | 음수 표기 `△` 를 못 읽어 셀을 통째로 버림 | 삼성전자 기타 부문 △285,155 유실 (카탈로그 대상 표 400사 중 1사 6셀) | `_parse_value` 에서 부호로 정규화. `▲`는 증감 표시로도 쓰여 **건드리지 않음** |
| 2 | 괄호음수 `(703)` 의 닫는 괄호가 **단위 `')'`** 로 적재 | 괄호음수를 쓰는 모든 표 | 부호 해석 후 닫는 괄호 제거 |
| 3 | 연도만 있는 헤더행(`사업부문\|2025년\|2024년`)이 데이터행으로 오판돼 **표 전체 폐기** | 250사 표본 생산표 420개 중 **33개(7.9%)** 유실. 보험사 표 21개도 동일 원인 | `_is_period_header_cell` 로 기간 헤더를 수치에서 제외 |
| 4 | 자간을 벌린 `가 동 율` 매칭 실패 → 전치형 승격 무산 → 전 행이 폴백 metric 으로 뭉개짐 | 엠플러스 '생산실적' 이 `capacity` 로 적재 | 공백 제거 후 매칭 + 전치형 표에서 지표명 아닌 행(`기말재고`)은 제외 |

> #3 수정만 넣으면 되살아난 표에서 `기말재고` 같은 비-생산 행이 폴백으로 `capacity` 에 섞인다.
> #4 의 뒷부분(비지표 행 제외)은 그 회귀를 막기 위해 **같은 커밋에** 넣었다.

---

## 6. 알려진 한계 (과장 금지)

- **`period_label` 이 기간과 측정항목을 함께 담는다.** `biz_metrics` 에 측정항목 컬럼이 없어
  `제34기 부문매출` / `제34기 영업이익` 처럼 붙여 구분한다(안 그러면 같은 키에 값만 다른 행이
  겹쳐 매출/이익 복원이 불가). `period_year` 는 그대로라 시계열 질의는 정상.
- **`segment`/`item` 은 라벨열 앞 두 축만 쓴다.** 3번째 이후(용도·매입처 등 서술열)는
  그룹핑 키로 쓸 수 없어 버린다 — 원문은 `biz_section_tables.grid` 에 무손실 보존.
- **캡션 상속(연속표)** 은 소제목이 바뀌면 끊는다. census 미분류 10.6% 중 얼마가 회수됐는지는
  아직 측정하지 않았다.
- **`inline_unit` 잡음** — 값 뒤 짧은 텍스트를 단위로 받는 기존 규칙 탓에 `지분증권(주` 같은
  단위가 드물게 들어간다(교보증권 trust_aum). 기존 동작이라 이번에 건드리지 않았다.
- 표본은 최신 사업보고서(FY2023+) 기준이다. **구서식(pre-2015) 검증은 안 했다.**

## 7. 다음에 할 만한 것

1. 백필 실행(§3) 후 metric 별 전수 커버리지 재측정.
2. 미분류 캡션 상위(`verify_biz_catalog.py --sample` 하단 출력)로 카탈로그 규칙 확장.
3. shortlist F1 — `매출실적` 표 한 장을 제품/부문/지역/유형 다차원으로 분해하는
   `sales_section` 개선(커버 85%로 신규 항목보다 영향이 크다).
