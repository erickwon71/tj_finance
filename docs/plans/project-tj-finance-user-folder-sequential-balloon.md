# TJ Finance 앱 개선 계획 — 외부 평가(2026-07-15) 대응

## ✅ P2 진행 (2026-07-17, 사용자 선택: 듀폰·EBITDA·백테스트)
- **듀폰 분해**: master_metrics 에 ROE 3분해(순이익률×자산회전율×재무레버리지, 총자본 기준) + 대가지표 탭 표시.
- **EBITDA/D&A 커버리지**: nightly_gap_fill_backfill Phase4 year_min 2024→**2015**(과거연도 D&A 복원 확대,
  샘플 검증: 65 facts/2사 복원). 밸류에이션 탭에 EV/EBITDA '—' 사유 안내(D&A 미공시). 전수는 야간 자동화 진행.
- **스크리너 백테스트**: app/compute/backtest.py 신설. 현재 스크린 조건을 과거 FY 코호트에 적용(익년 5월 매수,
  as-of 가격 오버라이드→build_base_frame→run_quant_passes), forward 1/3/5년 수익률 vs 유니버스 벤치마크.
  screen_window 에 year_max 파라미터 추가. 스크리너에 백테스트 expander. 격리테스트로 검증(FY2019=+66% 등 합리적).
- 컨센서스·알림은 사용자 선택 제외(외부데이터/인프라 → 별도 스코핑).

## Context

외부 평가자가 데스크탑 앱(Streamlit)을 Playwright로 전수 조작하고 PostgreSQL을 직접 read-only 검증해
`~/Project/tj_finance_user/앱_평가보고서_2026-07-15.md`를 남겼다. 골격은 우수하나, **전문투자자의 신뢰를
즉시 깨뜨리는 두 유형의 결함**이 다수 발견됐다: ① 같은 회사·같은 지표가 화면마다 다른 값(밸류에이션 배치
정체) ② 화면에 원시값 `None` 노출. 본 계획은 사용자 결정에 따라 **P0(신뢰성 치명) + P1(코드품질·해석리스크)**
범위로 수정한다. P2(신규기능)는 문서 끝 백로그로만 정리한다.

평가 주장은 이번 세션에서 라이브 DB로 교차검증 완료. **중요 정정(2026-07-16 실측)**: 평가·1차 분석 모두
`stock_prices`가 07-14까지 신선하다고 봤으나, 이는 **테스트 1종목(삼성 005930)의 착시**였다. 실제로는
**전 유니버스(2,556종목)가 06-26에 정체**돼 있었고 valuation_daily matview도 06-26 내용이었다. 따라서
근본 수정은 (a) 주가 전수 재동기화 + (b) matview refresh 분리·자동화 둘 다 필요했다.

---

## ✅ P0 실행 완료 상태 (2026-07-16/17)

| 항목 | 상태 | 검증 |
|---|---|---|
| P0-1 밸류에이션 스케줄 분리+모니터링 | ✅ | 전수 주가 catch-up(2554종목·0오류)→market_cap→refresh(11.2M행) 완료. valuation_daily 전수커버 최신=**07-16**. launchd `com.tjfinance.valuation`(19:30) 설치·등록. dq 어서션 `valuation_daily_stale`=0 |
| P0-2 멀티플 기준일 표시 | ✅ | 밸류에이션 탭(FY말 종가 캡션)·DCF(현재가 기준일)·섹터피어·기업비교(기준 안내). ValuationMultiples/DCFResult 에 price_date 추가. import 스모크 통과 |
| P0-3 shares_out 10^6 교정+가드 | ✅ | 229640·258790 교정(std_v2 287행·market_cap 재전파). 시총 정상화(0.6조·2.86조). 파서 물리상한 가드+dq 어서션 `shares_out_impossible`/`market_cap_impossible`=0 |
| P0-4 None 노출 제거(공통헬퍼) | ✅ | `app/format.render_dataframe` 신설. 생산·매출/분기변화/주주환원 6개 렌더지점 이관. import 스모크 통과 |
| P0-5 BS 매핑오류 교정+가드 | ✅ | 3테이블(std_v2 123·calendar 72·legacy view 자동) 항등식 재구성, 잔여 0. table_extractor 스킵리스트에 부채와자본총계 등 변형 등재 |

**남은 수동 절차**: (1) 앱 시각 확인(streamlit) 권장 — 캡션·None 소거 실물 확인. (2) 파서 가드(P0-3/P0-5)는
**신규 파싱 재발방지**용이며 과거 소급 백필은 완료됨. 커밋은 사용자 요청 대기.

---

## ✅ P1 실행 완료 상태 (2026-07-17)

| 항목 | 상태 | 비고 |
|---|---|---|
| P1-6 deprecated API | ✅ | **평가 권고와 반대로 수정**: 설치된 Streamlit 1.50 의 `st.plotly_chart` 는 `width` 파라미터가 없어 `width="stretch"` 가 오히려 경고를 유발(→ `**kwargs`). 올바른 무경고 API 는 `use_container_width=True`. 전 plotly 차트(16곳, 기존 회귀 2곳 포함) 이 값으로 통일. **st.dataframe 은 `width="stretch"` 유효 → 유지**. 격리테스트+로그로 검증 |
| P1-7 물결표 취소선 | ✅ | format.py·help_page.py 범위표기 `~`→en-dash(–). 도움말 `<del>` 태그 0 |
| P1-8 금융업 가드 | ✅ | `analyzer.ksic.is_financial_sector`(KSIC 64~66) 신설. checks.py 영업이익률 sanity 제외, peers.py 영업이익률·부채비율 백분위 제외, company_page 이상치·섹터피어에 안내 캡션. resolve_corp 에 induty_code 추가 |
| P1-9 TTM 멀티플 | ✅ | `cache.company_multiples_ttm`(screen_eval `_ttm_row` 재사용, 직전 4분기 합산+현재가). 밸류에이션 탭에 **연간(FY)/분기(TTM) 토글** |

**★ P0-4 정정(앱 검증 중 발견)**: 최초 `NumberColumn+NaN` 접근은 무효였다 — Streamlit 1.50 은 st.dataframe 에서
NaN 을 **문자 'None' 으로** 렌더한다(NumberColumn 유무 무관, 격리테스트 확인). 유일한 안전책은 **문자열화
(결측→"—")**. `render_dataframe` 를 그 방식으로 재작성 → 실물 스크린샷으로 생산·매출·주주환원 표 'None' 0 확인.

---

## P0 — 즉시 수정 (신뢰성·정확성 직결)

### P0-1. `valuation_daily` 배치 정체 → 독립 스케줄 + 모니터링
**근본원인(코드로 확인):** matview 리프레시에 **전용 스케줄러가 없다.** 유일한 호출처가
`scripts/collect_new.py`의 마지막 단계 ⑥(`_refresh_valuation_daily()`, line 341·405-408)인데, 이 잡은
매일 18:00 실행되지만 **단계 ①(`discover_recent_corps`)에서 DART 일일한도 초과(`DartApiError [020]`)로
크래시**하여 ⑥에 도달하지 못한다(`logs/collect.err.log` 오늘 18:00 트레이스백 확인). DART 40k 쿼터를
야간 `com.tjfinance.gapfill` 잡이 먼저 소진하는 경합도 원인. 마지막 성공 리프레시 로그 = 2026-07-13.

**수정:**
1. **리프레시를 collect 잡에서 분리** — 새 launchd plist `com.tjfinance.valuation.plist`로
   `scripts/refresh_valuation_daily.py --concurrent`를 **가격 동기화 직후** 별도 실행(예: 매일 18:40).
   가격 동기화(`scripts/fin2_sync_prices_daily.py`→`scripts/fin2_market_cap_daily.py`)는 pykrx/Naver
   기반이라 **DART 쿼터를 쓰지 않으므로** collect 잡 성공 여부와 무관하게 안정적으로 돈다.
   → 참고: 두 가격 스크립트도 현재 어느 launchd에도 배선되지 않음(`scripts/README.md` "run on demand").
   이번에 같은 새 plist에 체인으로 배선한다: `sync_prices_daily → market_cap_daily → refresh_valuation_daily`.
2. **지연 모니터링 가드** — `scripts/dq_nightly.py`(기존 DQ 잡, `com.tjfinance.dqcheck`)에 어서션 추가:
   `max(valuation_daily.trade_date)`가 오늘−N일보다 오래되면 `scripts/notify.py`로 알림.
   `scripts/dq_assertions.py` 패턴 재사용.
3. **collect 잡 견고화(경합 완화)** — `collect_new.py`의 DART 예외를 단계 ①에서 잡아 비치명 처리하고,
   가격/valuation 단계는 어차피 별도 잡으로 옮겼으므로 collect 실패가 밸류에이션에 전파되지 않게 함.
   gapfill vs collect DART 쿼터 경합은 gapfill 시작 시각/일일 상한 조정으로 별도 검토(런북에 메모).

**대상 파일:** `deploy/launchd/com.tjfinance.valuation.plist`(신규), `deploy/launchd/README.md`,
`scripts/collect_new.py`(예외 처리), `scripts/dq_nightly.py`·`scripts/dq_assertions.py`(지연 가드).

### P0-2. 가격 기반 멀티플에 "기준일(YYYY-MM-DD)" 명시
근본 수정 전까지의 최소 안전장치이자, 페이지 간 기준일 차이(FY말 종가 vs 최신가 vs valuation_daily)를
사용자가 인지하게 하는 항구적 개선.
- 💰 밸류에이션 탭·🏢 섹터·피어 탭·💎 밸류에이션(DCF) 페이지·⚖️ 기업 비교의 PER/PBR/시총 표시 옆에
  기준 `trade_date`를 캡션으로 노출.
- **대상:** `app/views/company_page.py`(`_valuation_df` line 81-89, `_peer_panel` line 218-254),
  `app/views/valuation_page.py`, `app/views/compare_page.py`. 기준일은 각 소스(`stock_prices` /
  `valuation_daily`)에서 이미 읽는 `trade_date`를 그대로 표기.

### P0-3. `shares_out` 10⁶ 과다 저장 수정 + 재발방지 가드
**확인:** `std_financials_v2.shares_out`이 소프트캠프(258790)=24,991,284,000,000(실제 ≈2,499만주),
LS에코에너지(229640)=30,624,879,000,000으로 **정확히 10⁶배**. `scripts/fin2_market_cap_daily.py`
(line 36-59)가 이 값을 `stock_prices.shares_out`으로 복사하고 `market_cap=close×shares_out`으로 증폭.
유입 경로는 보고서 본문 파서 `fin2/extract/shares.py`(`_pick`, line 64-74, 첫 숫자컬럼을 단위검증 없이
채택) 또는 DART API `analyzer/price_fetcher.py:get_shares_from_dart`.

**수정:**
1. **두 종목 값 교정** — DART `stockTotqySttus`(정상 발행주식수) 또는 pykrx 상장주식수로 재취득해
   `std_financials_v2.shares_out` 정정 → `fin2_market_cap_daily.py` 재실행으로 `stock_prices`·`market_cap`
   전파. 1회성 교정 스크립트 `scripts/fix_shares_out_anomaly.py`(신규, 대상 corp만).
2. **파서 단위 가드** — `fin2/extract/shares.py`에 크로스체크 추가: 채택 발행주식수로 계산한
   내재 시총(close×shares) 또는 DART 발행주식수와 **자릿수(orders of magnitude) 비교**해 10³~10⁶
   이탈 시 채택 거부/경고. 재발방지 어서션은 `scripts/dq_assertions.py`에 전역 상한 추가:
   `shares_out`로 계산한 시총 > 국내 증시 총액의 일정비율, 또는 PER>500x 등 물리적 상한 플래그.
3. **UI 이상치 가드** — 재무 "이상치 점검"과 동일 개념을 시총/PER/PBR에도 적용(P1-8과 같은
   `app/compute/checks.py` 레이어에 밸류에이션 sanity 추가).

### P0-4. 화면 `None` 원시값 노출 제거 (공통 유틸화)
**확인된 3곳(모두 공통 원인 = `st.dataframe`에 `None`을 그대로 전달):**
- 🏭 생산·매출: `app/views/company_page.py` `_production_panel`(576-582)·`_sales_panel`(631-635)·
  `_order_backlog_panel`(686-692)
- 📊 분기 변화: `app/views/quarter_change_page.py` `_eok`/`_pct`(47-53)→`_to_display`(56-80),
  `_modal_table`(96-112)
- 💸 주주환원: `app/views/company_page.py` `_shareholder_return_panel`(436-457, column_config·None처리 전무)

**수정:** 이미 존재하는 올바른 패턴(`company_page.py:73-78` `_show_statement`의 `None→"—"` 매핑)을
**공통 헬퍼로 승격**한다. `app/format.py`(기존 `fmt_amount`/`fmt_pct` 옆)에
`render_dataframe(df, *, num_cols=..., na="—")` 헬퍼 신설 — `st.dataframe` 호출 전 결측을 `"—"`로
치환하고 NumberColumn 포맷을 일괄 적용. 위 5개 렌더 지점을 이 헬퍼 경유로 리팩터. 향후 신규 표도
이 헬퍼만 쓰도록 규약화(런북/주석에 명시).

### P0-5. BS 매핑 오류(부채총계=자산총계) 재검증·교정
**확인:** 한국석유공업·황금에스티의 old K-GAAP 연도에서 `total_liabilities == total_assets`
(예: 한국석유공업 2011 둘 다 236,295,082,168, 자본은 100,573,058,272 → 부채는 assets−equity여야 함).
**근본원인:** `parser/xml/table_extractor.py` `_JUNK_ACCOUNT_NAMES`(line 126-129)가 "부채및자본총계"
(=자산총계 우변합계)는 차단하나 **"부채와자본총계"(및↔와 변형)는 누락**. `normalize_account_name`
(`parser/common/amount_normalizer.py:122`)이 및/와를 통일하지 않아 스킵리스트를 우회. 레거시 적재는
`analyzer/aggregator.py`(29-43) 경로.

**수정:**
1. **스킵리스트 보강** — `_JUNK_ACCOUNT_NAMES`에 "부채와자본총계" 등 변형 추가, 또는
   `normalize_account_name`에서 및↔와 정규화. 신규 파싱 재발 차단.
2. **기존 오염행 교정** — 대상 corp·연도의 `total_liabilities`를 `total_assets−total_equity`로 재계산
   백필(원문 대조 후). 소급 백필은 수동(프로젝트 규약, `docs/runbook_new_parser_pipeline_integration.md`).
   1회성 스크립트 `scripts/fix_bs_liability_mapping.py`(신규). 유사 오염 전수 스캔 쿼리 포함
   (`total_assets=total_liabilities AND total_equity>0`).

---

## P1 — 단기 (코드품질·해석리스크)

### P1-6. `use_container_width=True` → `width="stretch"` 일괄 마이그레이션 (13곳)
Streamlit deprecated 경고가 사용자 화면에 노출 + 향후 제거 시 렌더 실패 위험. 이미 절반은 마이그레이션됨.
**대상(전부 `st.plotly_chart`):** `app/views/chart_panel.py`(85,158,221,287,325,344,394,414,444),
`app/views/company_page.py`(567,629,657), `app/views/quarter_change_page.py`(175). 기계적 치환.

### P1-7. 도움말·각주 물결표(`~`) 취소선 오렌더 수정
Markdown이 짝수 개 `~`를 GFM 취소선으로 오인. **대상:** `app/format.py:74,76`(`1~3월`,`1~12월`),
`app/views/help_page.py:33-34`(`1~3월`,`4~6월`,`7~9월`,`10~12월`). 이스케이프(`\~`) 또는 구분자를
en-dash(`–`)/"부터"로 교체.

### P1-8. 금융업(은행/보험/지주)에 제조업 기준 스코어링 미적용 — 안내문구 + 제외 가드
**결정:** 전용 지표 템플릿 신설이 아니라, **KSIC 64~66은 해당 평가에서 제외 + 안내 표시.**
- **이상치 점검:** `app/compute/checks.py` `financial_anomalies`(59-121)에 sector 인자 추가 →
  KSIC 64~66이면 영업이익률 sanity(68-78) 스킵. `analyzer/ksic.py` `sector_key()`로 판별.
- **섹터·피어:** `app/data/peers.py` `PEER_METRICS`(17-28)에서 금융업일 때 `op_margin`·`debt_ratio`
  제외하거나 백분위 딱지를 억제. `load_peer_benchmark`(37-76)에 sector 분기.
- **안내문구:** `company_page.py` `_peer_panel`(218-254)·이상치 expander(892-897)에
  "금융업은 업 특성상 일반기준(부채비율·영업이익률) 미적용" 캡션 표시.
- 이미 파서층에 선례 있음: `fin2/standardize/rules.py:rule_revenue_fallback`(180-197)이 은행/혼합지주
  구분 → 이 판별 관용구를 스코어링층으로 이식.

### P1-9. 분기 TTM 멀티플을 기업 밸류에이션 뷰에 배선
**현황:** TTM 로직은 스크리너에 이미 존재(`app/compute/screen_eval.py` `_ttm_row` 174-186,
`_latest_multiples` 189-207)하나, 기업 페이지 경로(`analyzer/valuation_engine.py` compute 100-145)는
연간 스냅샷만 사용. `company_page.py:961` 캡션도 "분기 멀티플(TTM)은 후속 단계"로 자인.
**수정:** `screen_eval`의 `_ttm_row` 로직을 재사용 가능한 공용 함수로 승격 후
`valuation_engine`/`app/cache.py:company_multiples`에 grain="quarter" TTM 분기 추가, 밸류에이션 탭에
"연간(FY) / 분기(TTM)" 토글 노출. (P1 중 유일하게 규모 큰 항목 — P0 안정화 후 착수 권장.)

---

## 검증 (End-to-End)

- **P0-1:** 새 valuation plist 수동 kickstart → `psql tj_finance -c "select max(trade_date),count(*)
  from valuation_daily where trade_date=(select max(trade_date) from valuation_daily)"` 가 오늘 근처
  날짜 + ~2,540행인지 확인. dq_nightly 지연 가드가 정상/이상 양쪽에서 동작하는지 시뮬레이션.
- **P0-2:** 앱 실행(`streamlit run app/main.py`) → 삼성전자 💰밸류에이션·🏢섹터피어·💎DCF·⚖️비교에서
  기준일 캡션이 각기 보이고 값-기준일 정합.
- **P0-3:** 교정 후 소프트캠프·LS에코에너지 시총/PER이 정상 범위. `dq_assertions` 재실행 시 잔여 이상치 0.
  스크리너 "시총 상위"·"PER 낮은 순"에서 두 종목이 비정상 최상/최하위를 점유하지 않음.
- **P0-4:** 오텍 🏭생산·매출, 📊분기 변화(신규상장 행), 💸주주환원(무배당 연도)에서 `None` 문자열 0건,
  전부 `"—"`. 공통 헬퍼 단위 스냅샷/회귀 테스트 추가.
- **P0-5:** 교정 후 한국석유공업·황금에스티 BS 항등식(자산=부채+자본) 1% 이내. 전수 스캔 쿼리 재실행 시
  `total_assets=total_liabilities AND total_equity>0` 잔여 0.
- **P1-6/7:** 앱에서 deprecated 경고 배너·취소선 시각 확인 소거. `grep -rn use_container_width app/` = 0.
- **P1-8:** KB금융 이상치 점검에 88% 영업이익률 플래그 미노출, 섹터·피어 부채비율 "열위" 딱지 대신 안내문구.
- **P1-9:** 삼성전자 밸류에이션 탭 분기(TTM) 토글이 스크리너 TTM 값과 일치.

**공통 원칙:** 파서/로더를 건드리는 P0-3·P0-5는 `docs/runbook_new_parser_pipeline_integration.md`
체크리스트(① 배선 두 call site ② 소급 백필 수동 ③ 검증) 준수. Gate B(보고서-DB 일치) 무영향 확인.

---

## P2 — 백로그 (이번 범위 밖, 로드맵 이관)

- EBITDA/D&A 커버리지 확대: `fin2/standardize/rules.py:rule_derive_ebitda`(210-215)가 `da_total>0`
  게이팅 → 결측 구간 EBITDA 공란. 복원은 `collector/cf_da_sync.py`·`fin2/extract/cf_da.py`·
  `expense_nature.py` 진행 중(기존 야간 백필 로드맵과 통합).
- 듀폰 분해(ROE = 순이익률×자산회전율×레버리지) — 대가지표 탭 추가.
- 컨센서스/애널리스트 목표주가 비교(외부 데이터 소스 필요).
- 스크리너 백테스트/워크포워드.
- 워치리스트 임계값 알림.
- 분기 변화 행클릭 모달 동작 수동 재확인(자동화 테스트 미확정 건).
