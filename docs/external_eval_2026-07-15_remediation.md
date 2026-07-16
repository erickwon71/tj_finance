# 외부 앱 평가(2026-07-15) 대응 — 조치 완료 정리

**원본 평가**: `~/Project/tj_finance_user/앱_평가보고서_2026-07-15.md` (스크린샷 16장)
**조치 기간**: 2026-07-16 ~ 07-17
**검증 방식**: 라이브 DB 교차검증 + 실행 중인 앱을 Playwright 로 실물 조작·스크린샷 육안 확인
**커밋(main)**: `9266147`(P0+P1) · `6da074a`(P2) · `92c60db`(분기변화 모달 QA)

---

## 1. 핵심 발견 (평가와 달랐던 점)

| # | 평가 주장 | 실측 결과 |
|---|---|---|
| A | 주가는 07-14까지 신선, valuation_daily만 06-26 정체 | **전 유니버스(2,556종목)가 06-26 정체**였음. 삼성(005930) 1종목만 07-14 → `max(trade_date)` 착시. |
| B | `use_container_width` deprecated → `width="stretch"` 권장 | 설치된 **Streamlit 1.50 의 `st.plotly_chart` 는 `width` 파라미터가 없음** → `width="stretch"` 가 오히려 경고 유발. 올바른 무경고 API 는 `use_container_width=True`(평가와 반대). st.dataframe 은 `width` 유효 → 유지. |
| C | `None` 노출 = 포맷터 누락 | Streamlit 1.50 은 st.dataframe 에서 **NaN 도 문자 'None' 으로 렌더**(NumberColumn 유무 무관). 유일한 해법 = **문자열화(결측→"—")**. |

---

## 2. P0 — 신뢰성 치명결함 (커밋 9266147)

| 항목 | 조치 | 산출물 |
|---|---|---|
| P0-1 valuation_daily 정체 | refresh 를 collect 잡에서 분리한 독립 잡. collect DART예외 비치명화. 전수 catch-up 완료(→07-16). 지연 모니터링 어서션. | `scripts/nightly_valuation_refresh.py`, `deploy/launchd/com.tjfinance.valuation.plist`(19:30, **설치·등록됨**), `dq_assertions.valuation_daily_stale` |
| P0-2 기준일 표시 | ValuationMultiples/DCFResult 에 `price_date`. 밸류에이션·DCF·섹터피어·기업비교에 기준일 캡션. | valuation_engine·dcf_engine·company_page·valuation_page·compare_page |
| P0-3 shares_out 10⁶ 과다 | 229640·258790 교정(÷10⁶). 파서 물리상한 가드. 물리불가 어서션. | `scripts/fix_shares_out_anomaly.py`(실행완료), `fin2/extract/shares.py`, `dq_assertions`(shares_out/market_cap_impossible) |
| P0-4 `None` 노출 | `render_dataframe` 공통 헬퍼(문자열화). 생산·매출/분기변화/주주환원 등 8개 렌더지점 이관. | `app/format.py`, company_page, quarter_change_page |
| P0-5 BS 매핑오류 | 부채=자산 항등식 재구성(std_v2 123·calendar 72행). 스킵리스트에 "부채와자본총계" 등 변형. | `scripts/fix_bs_liability_mapping.py`(실행완료), `parser/xml/table_extractor.py` |

**검증**: dq 신규 어서션 3종 위반 0 · 무결성 OK. 앱: 생산·매출/주주환원 'None'→"—", 기준일 캡션 육안 확인.

---

## 3. P1 — 코드품질·해석리스크 (커밋 9266147)

| 항목 | 조치 |
|---|---|
| P1-6 plotly 경고 | 전 plotly 차트(16곳) `use_container_width=True` 로 통일(발견 B). 앱 로그 경고 0. |
| P1-7 물결표 취소선 | format.py·help_page.py 범위표기 `~`→en-dash(–). |
| P1-8 금융업 가드 | `ksic.is_financial_sector`(KSIC 64~66). 영업이익률 sanity·부채비율/영업이익률 백분위 제외 + 안내 캡션. resolve_corp 에 induty_code 추가. |
| P1-9 TTM 멀티플 | `cache.company_multiples_ttm`(screen_eval `_ttm_row` 재사용). 밸류에이션 탭 연간(FY)/분기(TTM) 토글. |

**검증**: 앱에서 KB금융 금융업 안내·부채비율 제외, 삼성 TTM 토글(PER 18.1x) 육안 확인.

---

## 4. P2 — 기능확장 (커밋 6da074a·92c60db, 사용자 선택 3+QA)

| 항목 | 조치 | 검증 |
|---|---|---|
| 듀폰 분해 | ROE = 순이익률×자산회전율×재무레버리지(총자본 기준) 3분해. 대가지표 탭. | 삼성 13.6%×0.59×1.30=10.4% (항등식 성립) |
| EBITDA/D&A 커버리지 | 야간 Phase4 D&A 복원 `year_min 2024→2015`(과거연도 확대). 밸류에이션 탭 EV/EBITDA '—' 사유 안내. | 복원 샘플 검증(facts 생성). 전수는 야간 자동화 진행(§6). |
| 스크리너 백테스트 | 현재 스크린 조건을 과거 FY 코호트에 적용(익년5월 매수, as-of 가격 오버라이드→`build_base_frame`→`run_quant_passes`), forward 1/3/5년 수익률 vs 유니버스. screen_window `year_max` 추가. | 격리테스트 합리적(FY2019 매수 2020-05 +66%). 패널 렌더 확인. |
| 분기변화 모달 QA | **정상 동작**(결함 아님). 평가자 재현실패 = `selection_mode='single-row'` 에서 셀 클릭은 하이라이트만, 행선택(모달)은 **좌측 체크박스**로만 발생. 캡션 명확화. | @st.dialog '기업 분기 시각화' 오픈 확인. |

`app/compute/backtest.py`(신규), master_metrics·company_page·screen_window·screener_page·nightly_gap_fill_backfill.

**백테스트 한계(UI 명시)**: 재무 정정본 포함(정정 lookahead) · 가격수익률(배당 제외) · 상장폐지 종목 경미한 생존편향.

---

## 5. 미착수 (사용자 선택 제외 — 별도 스코핑 필요)

- **컨센서스/애널리스트 목표주가**: DART 에 없음 → 외부 데이터소스(네이버/FnGuide 등) 도입 결정 필요. DART-only 아키텍처와 별개 판단.
- **워치리스트 임계값 알림**: 임계값 설정 UI + 알림 인프라 필요.

---

## 6. ★ 운영 노트 — gap 백필 야간 작업 상태 (2026-07-17 기준)

`com.tjfinance.gapfill`(매일 00:01, 완료 시 자기 등록해제 설계). 오늘 실행(00:01→08:28):

- **Phase 2 (주주환원 API 6종): 완료** — 잔여 0.
- **Phase 3 (부문·수출입 매출): 완료** — 잔여 0.
- **Phase 4 (비용성격 D&A): 진행 중** — 잔여 **1,509사(구범위 2024+) / 2,055사(신범위 2015+)**.
  이번 밤 375사 처리·2,596 facts 복원. 오늘 커밋한 `year_min=2015` 는 **오늘밤(07-18) 실행부터 적용** →
  대상이 2,055사로 확대되어 과거연도 EBITDA 커버리지를 여러 밤에 걸쳐(≈500사/밤) 끌어올린다.

연결 FY EBITDA 커버리지(현재): 2019~2023 = 22~33%, 2024~2025 = ~31% (Phase4 복원 반영으로 상승 중).

### ⚠ 알려진 한계 (조치 판단 필요)
Phase 4 는 **실패한 복원 시도를 기록하지 않는다**(Phase 3 의 상태파일 같은 attempt-tracking 없음).
D&A 를 어느 서식에도 공시하지 않는 기업은 영구 NULL 로 남아 **매일 재시도**되고, 그만큼 `잔여`가
0 에 도달하지 못해 **잡이 자기 해제되지 않을 수 있다**(이 이슈는 year_min 확대 이전에도 존재, 확대로 소폭 증폭).
재시도 비용 자체는 작다(로컬 파일 파싱, 기업당 수 초).

**선택지**:
1. 그대로 두기 — 복원 가능한 기업은 계속 채워지고, 커버리지가 평탄해지면 수동으로 잡 중단.
   (`launchctl unload -w ~/Library/LaunchAgents/com.tjfinance.gapfill.plist`)
2. Phase 4 에 attempt-tracking(Phase 3 방식 상태파일) 추가 → 영구 NULL 기업 스킵 → 정상 자기해제.
   (권장 — 별도 작은 작업)

---

## 7. 재실행·검증 명령 요약

```bash
# 밸류에이션 갱신(수동)
python scripts/nightly_valuation_refresh.py                 # 주가+시총+matview
python scripts/nightly_valuation_refresh.py --skip-prices   # 시총+matview 만(초고속)

# 무결성 어서션(신규 3종 포함)
python scripts/dq_assertions.py

# 앱 실행
streamlit run app/main.py

# gap 백필 수동 실행 / 잡 상태
python scripts/nightly_gap_fill_backfill.py
launchctl list | grep tjfinance          # 등록된 잡 확인
```
