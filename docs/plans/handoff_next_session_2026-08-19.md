# 다음 세션 할 일 — 2026-08-19 인수인계

> **이 문서 = 다음 세션 단일 진입점.** 우선순위·근거·실행명령·검증방법을 항목마다 적었다.
> 직전 세션(2026-08-18) 작업: 2026 H1 백로그 적재 완료 + Gate B ④ 설계 rev2.
> 관련 메모리: `h1-2026-backlog-load-2026-08-18`, `gateb-remediation-track-2026-08-17`.

---

## 0. 직전 세션 요약 (완료분)

| 작업 | 결과 | 커밋 |
|---|---|---|
| Gate B ④ 설계 rev2 | 탐지 모집단을 corp 목록 → 전수 패턴으로 정정, 축 B(신규기업) 신설 | `fb469f5` |
| xbrl_zip 계층2 백필 | 1,741개사 · 1,816필링 · 641,618행 · 오류 0 · 10.3분 | `b4a66a3` |
| xml 경로 계층2 백필 | 371개사 · 2,282보고서 · 본문 106,980 + 주석 835,103행 · 8.6분 | `0f7d083` |
| std_v3 재생성 | 2,128개사 · 161,130행 | — |

**2026 H1 std_v3 커버리지: 402 → 2,499개사** (2025 H1 = 2,496 대비 정상, 2,508 중 99.6%)

원문 대조 완료: POSCO홀딩스(xml 경로)·삼성전자(xbrl 경로) 둘 다 원문 문자열과 정확히 일치.

---

## 1. 우선순위 요약

| 순위 | 항목 | 성격 | 예상 |
|---|---|---|---|
| **P0-1** | ⑤ 후속 단계 미실행 — 사업지표·수주·주식수·배당 **전부 0에 가까움** | 데이터 공백 | 중 |
| **P0-2** | 주가 데이터 **2026-07-20 에서 멈춤**(약 1개월) | 데이터 공백 | 소 |
| **P1-1** | 파이프라인 결함 ① — `xbrl_zip` 이 표준화 대상 선택에서 누락 | 항구 수정 | 중 |
| **P1-2** | 파이프라인 결함 ② — ④-3 이 루프 뒤라 조용한 부분 실패 | 항구 수정 | 중 |
| **P2-1** | 두산밥캣·아남전자 2026H1 추출 0행 (**④ 트랙 T1 직결**) | 원인규명 | 소 |
| **P2-2** | 2026-08 에 `[014]` 폴백이 0% → 70% 로 급증한 원인 | 원인규명 | 소 |
| **P2-3** | PDF 전용 7개사 · 고려아연 원문 XML 깨짐 | 잔여 | 소 |
| **P3-1** | Gate B 전수 재감사 — 신규 대량적재로 **기준선이 이미 바뀌었다** | 검증 | 대(1.2h) |
| **P3-2** | Gate B ④ curated 키 재생성기 — **사용자 결정 5건** | 결정 | — |

---

## 2. P0-1 — ⑤ 후속 단계 미실행 (가장 큰 공백)

### 무엇이 비었나 (2026-08-19 실측)

2026 H1 확정 필링 **2,508건** 대비:

| 데이터 | 적재 | 비고 |
|---|---|---|
| `biz_metrics`(생산·가동률·부문매출) | **0** | ⑤-1 미실행 |
| `order_backlog`(수주) | **0** | ⑤-2 미실행 |
| `report_shares_outstanding` | **37** | ④-5 미실행 |
| `dividend_facts` fy2026 | **12** | ⑤-3 미실행 |
| `employee_stats` fy2026 | **42** | ⑤-3 미실행 |

### 왜 비었나

직전 세션의 `--standardize-only` 실행이 ④-2 까지만 돌고 종료됐다(P1-2 결함). 그리고
계층2 백필 드라이버 2개는 **계층2 전사만** 담당한다 — ④-4/④-5·⑤-1~⑤-3 은 안 부른다.
게다가 데일리가 `--download-only` 라 이 단계들은 **원래부터 매일 생략**되고 있었다.

### 어떻게

`collect_new.py --standardize-only` 를 다시 돌리면 44.4초/기업 × 2,500개사 = 30시간이라
현실적이지 않다. **⑤ 단계만 부르는 드라이버가 필요**하다 —
`scripts/backfill_layer2_lines_2026-08-18.py` 와 같은 구조로 만들면 된다
(`collect_new.py` 의 `_sync_shares_transcribe`·`_sync_biz_metrics`·`_sync_order_backlog`·
`_sync_periodic_apis` 를 배치로 호출).

★ 먼저 확인할 것: ⑤-3(`_sync_periodic_apis`)은 **DART API 호출**이라 쿼터 제약이 있다.
2,500개사 × 5종 API 면 쿼터 초과 가능 — 분할 실행 설계가 선행돼야 한다.

### 검증
```
SELECT (SELECT count(DISTINCT rcept_no) FROM biz_metrics b JOIN filings f USING(rcept_no)
        WHERE f.fiscal_year=2026 AND f.fiscal_period='H1') AS biz;
```

---

## 3. P0-2 — 주가 데이터가 1개월 밀려 있다

| 항목 | 최신 |
|---|---|
| `stock_prices.trade_date` | **2026-07-20** (해당일 1,986종목) |
| `valuation_daily.trade_date` | **2026-07-16** |

오늘이 2026-08-19 이므로 약 **1개월 공백**이다. 데일리 수집이 `--download-only` 라
주가 수집·밸류에이션 갱신이 도는지부터 확인해야 한다(`com.tjfinance.collect.plist` 는
공시 수집 잡이고, 주가는 별도 잡이었는지 확인 필요 — `~/Library/LaunchAgents/` 에는
현재 `com.tjfinance.collect` **하나뿐**이라 주가 잡이 아예 없을 가능성이 높다).

★ 메모리 `viz-app-status`·`data-coverage-gaps` 와 교차 확인할 것.

---

## 4. P1-1 — 결함 ①: `xbrl_zip` 필링이 표준화 대상 선택에서 누락

### 근거
`app/data/collect.py:106` — `needs_standardize_corps()` 가
`AND dt.file_type='xml'` 로 좁힌다. OpenDART `[014]` 폴백으로 XBRL instance zip 을 받은
필링(`collector/downloader.py:169` `_try_xbrl_instance_fallback`)은 대상에 안 들어온다.

실측(2026-08-18): 2026-08 접수 2,628건 중 **1,845건이 xbrl_zip 전용**. 미전사 1,765개사
중 **930개사는 도달 불가**였고, 도달되던 835개사도 무관한 pre-2008 공백 덕에 **우연히**
목록에 올라간 것이었다.

### 수정 방향(안)
`needs_standardize_corps()` 에 xbrl_zip 대기 조건을 OR 로 추가하거나, 별도 셀렉터를
만들어 `collect_new.py` **두 call site 모두**에 배선
(`docs/runbook_new_parser_pipeline_integration.md` 체크리스트 ①).

### 회귀 주의
이 함수는 표준화 대상을 정하는 공용 셀렉터다 — 넓히면 매 데일리 실행의 대상 기업 수가
늘어 런타임이 증가한다. 44.4초/기업이므로 영향이 크다. **범위를 넓히기 전에
"xbrl_zip 만 필요한 기업은 계층2 전사만 하고 std_v2 재표준화는 건너뛴다"** 를 검토할 것
(실측상 그게 10분 vs 20시간의 차이였다).

---

## 5. P1-2 — 결함 ②: ④-3 이 루프 뒤라 조용한 부분 실패를 만든다

### 근거
`scripts/collect_new.py:700` 부근 — `--standardize-only` 경로는
`_standardize_with_timeout()`(기업당 44.4초) 루프가 **전부 끝난 뒤에야** ④-3
`_sync_layer2_lines()` 를 부른다. 중간에 끊기면 **std_v2 는 커밋됐는데 report_lines 는
0행**인 상태로 남고, 재실행하면 2.5시간 루프를 처음부터 다시 돈다.

실제로 겪음(2026-08-18): 374개사 표준화 2h27m 완료 → 후속 단계 중 종료 →
374개사 전부 report_lines 0행.

### 수정 방향(안)
기업 단위로 "표준화 → 계층2 전사"를 묶어 배치마다 완결시키거나, 최소한 ④-3 을
루프 앞으로 옮긴다. 어느 쪽이든 **두 call site 모두** 반영.

---

## 6. P2-1 — 두산밥캣·아남전자 2026H1 추출 0행 (★④ 트랙 직결)

| 기업 | 접수번호 | 상태 |
|---|---|---|
| **두산밥캣** | 20260814003597 | `is_final=t`, xbrl_zip completed, 추출 0행 |
| 두산밥캣 | 20260813001784 | `is_final=f`(대체됨) — 무해 |
| 아남전자 | 20260811000654 | `is_final=t`, xbrl_zip completed, 추출 0행 |

둘 다 `period_end_date` 는 정상이라 그 원인은 아니다. `extract_report_lines_xbrl()` 이
예외 없이 빈 리스트를 반환했다 — **왜 비었는지 로그가 없다.**

★ **두산밥캣은 ④ 설계서 T1 의 유일한 대상 기업**
(`_FX_PRESENTATION_CURRENCY_KEYS`, `face_audit.py:780`). 그 회사의 2026 H1 이 공백이면
④ 트랙의 forward 검증 자체를 못 한다 — ④ 착수 전에 이걸 먼저 풀어야 한다.

### 착수법
```
.venv/bin/python -c 로 하지 말 것(메모리 feedback-no-python-c) — 조사 스크립트를 만들어
raw_report/.../20260814003597.zip 을 직접 열고 컨텍스트/사실 개수를 세어 어디서 0이 되는지
단계별로 출력할 것.
```

---

## 7. P2-2 — `[014]` 폴백 급증 원인

| 월 | xml | xbrl_zip 전용 |
|---|---|---|
| 2026-03 | 2,742 | 0 |
| 2026-05 | 2,621 | 1 |
| 2026-07 | 106 | 0 |
| **2026-08** | 783 | **1,845** |

8월에만 70%가 폴백을 탔다. 가설: ① 시간이 지나면 document.xml 이 생긴다(재시도로 해소),
② DART 측 변경, ③ 반기보고서 특성. **①이면 재다운로드로 xml 을 확보해 정상 경로로
돌릴 수 있으므로 가장 먼저 확인할 가치가 있다** — 표본 몇 건만 지금 다시 받아보면 된다.

메모리 `xbrl-alternate-source-finding` 참고("`document.xml`[014]없음만으로 단정금지").

---

## 8. P2-3 — 잔여 개별 건

- **PDF 전용 7개사**(2026 H1): 동화기업·멤레이비티·부국증권·에이엔피·우듬지팜·캐프·한세실업.
  xml/xbrl 둘 다 없음 → PDF 파서 트랙 소관
  (`docs/plans/pdf_only_parser_plan_2026-08-11.md` §B 미착수).
- **고려아연 20260813001701**(2024H1): 원문 XBRL 자체가 깨짐 —
  `xmlns:XBRLConsultingFirm='한영회계법인'` 이 유효한 URI 가 아니라 `XMLSyntaxError`.
  DART 원문 결함이라 우리 쪽 수정 대상이 아닐 수 있음. 회복하려면 파서에서 잘못된
  네임스페이스를 사전 치환하는 방어코드가 필요.

---

## 9. P3-1 — Gate B 전수 재감사 (★기준선이 이미 바뀌었다)

직전 세션에서 **2,100개사 분량의 2026 H1 이 새로 std_v3 에 들어왔다.** 5개 트랙을 끝내며
확정한 Gate B 기준선(299,651행)은 **더 이상 유효하지 않다.**

메모리 `gateb-full-reaudit-is-required-to-close`: "표본으로 닫으면 다음 전수에서
신규 결함으로 재등장. 재감사 **전에 스냅샷** 필수."

```
CREATE TABLE face_audit_snap_20260819 AS SELECT * FROM face_audit WHERE source_version='v3';
```
스냅샷 뜬 뒤 `scripts/run_gateb_audit_parallel.sh`(5-shard, 약 1.2시간).

★ 이번 재감사는 **신규 기간이 대량 추가된 뒤 첫 감사**라 fail 이 늘어나는 게 정상이다 —
"단조성 위반 0" 게이트를 기존 기간에 한정해 적용할 것(신규 기간은 비교 대상이 없다).

---

## 10. P3-2 — Gate B ④ curated 키 재생성기: 사용자 결정 5건

설계 rev2 = `docs/plans/gateb_curated_key_regenerator_design_2026-08-18.md` §6.

1. **알림 수단** — 프로젝트에 알림 코드가 전무. (a) macOS 팝업(osascript) / (b) 실행 끝
   요약 출력 / (c) 둘 다 / (d) JSON 파일만
2. **`_FX_PRESENTATION_CURRENCY_KEYS`(두산밥캣) 를 이번 범위에 넣을지** — 항등식이 없어
   탐지 규칙부터 새로 정의해야 함(§5-D). ※ P2-1 이 선행돼야 함
3. **T0 축 B(신규 회사가 blanket override 대상이 되는 경우)를 넣을지** — rev2 신규 항목
4. **리뷰 큐 형식** — JSON 파일 vs DB 테이블(`curated_key_candidates`)
5. **2026 반기 백로그 적재 시점** — ✅ **직전 세션에서 적재 완료로 해소됨**(결정 불필요)

---

## 11. 다음 세션 시작 시 먼저 할 것

1. 이 문서와 `docs/plans/gateb_remediation_master_2026-08-17.md` 를 읽는다
2. 아래로 현재 상태를 재확인한다(이 문서 작성 후 시간이 지났을 수 있다)

```
psql -d tj_finance -c "
SELECT fiscal_year, fiscal_period, count(DISTINCT corp_code) FROM std_financials_v3
WHERE fiscal_year>=2025 GROUP BY 1,2 ORDER BY 1,2;"
```

3. 장시간 작업(P3-1 재감사 등)은 **사용자에게 실행을 요청**하거나 백그라운드로 돌리되,
   **결과 확인 전 `ps aux` 로 프로세스 생존을 먼저 본다**(과거 오판 사례 있음).
4. 백그라운드 작업은 약 3시간에서 종료될 수 있다(2026-08-18 실측) — 그보다 긴 작업은
   반드시 **배치 커밋 + 재개 가능** 구조로 만들 것.
