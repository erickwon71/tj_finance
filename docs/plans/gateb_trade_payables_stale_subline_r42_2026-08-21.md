# Gate B — bs.trade_payables 원인규명 R42: 정정본 하위라인 재구성이 남긴 stale 셀 (2026-08-21)

> R41(curated 키 재생성기)의 `trade_payables_additive` lateral 후보 15건을 원문대조하다 발견.
> 15건 전부 "2-라인 합" 이 아니라 **단일 셀 오채택**이었다 — 새 버그가 아니라, 이미 알려진
> `_NARROW_PREFER`/`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS` 패턴(주석: "narrow child value
> already matches report_won for MOST corps")의 **신규 발견 예외 사례**로 확정.

## 1. 근본원인 (14/15건 동일 메커니즘, 원문 직접대조로 확정)

같은 (corp, fy, period) 에 **여러 filing**(원본 + 정정본)이 있을 때:

1. **원본**(최초등록본)의 BS는 "매입채무 및 기타유동채무"(부모/총계) 아래 **"단기매입채무"라는
   하위라인을 별도로 보여준다.**
2. **정정본**은 같은 부모 총계를 유지하되, 하위라인 구성을 바꾼다(단기매입채무를 없애고
   다른 항목들로 쪼개거나, 각주번호만 붙여 라벨을 바꾼다).
3. R2 정본 정책("정정이 건드리지 않은 셀은 원본 값을 유지")에 따라 `build_merged_lines()`는
   **"단기매입채무" 셀을 정정본이 다시 안 썼으니 원본 값 그대로 유지**한다 — **이건 정책대로
   맞게 동작한 것**이다.
4. 문제는 이다음 단계 — `_resolve()`가 이 canonical(`bs.trade_payables`)의 후보 풀에서 stage
   순위를 매길 때, **"단기매입채무"(원본, exact-stage alias)가 "매입채무 및 기타유동채무"
   (정정본의 현재 부모 총계, normalized-stage)보다 먼저 확정돼버린다** — `_NARROW_PREFER`의
   일반정책("narrow 가 대개 맞다")과 정확히 같은 메커니즘인데, 이 15건은 그 반대 경우다.

**원문 직접대조 확정 사례** (전부 report_lines 값이 원문 XBRL/렌더링 그대로임을 그 자체로
증명, `20260813000115`류 원본 rcept vs `20260819000058`류 정정본 rcept 비교):

| corp | 정답(report_won) 라벨 · 출처 | 오답(db_won) 라벨 · 출처 |
|---|---|---|
| 00124276 부스타 2019H1 | "매입채무 및 기타유동채무" · **정정본**(`20190819000058`) | "단기매입채무" · **원본**(`20190813000115`) |
| 00146296 일신석재 2015Q3(별도) | "장기매입채무 및 기타비유동채무"(비유동) · **정정본** | "단기매입채무" · **원본** |
| 00364403 쏠리드 2015Q3(별도) | "장기매입채무 및 기타비유동채무"(비유동) · 정정본 | "단기매입채무 (주28)" · 원본 |
| 00923826 일월지엠엘 2020FY | "매입채무 및 기타채무 (주4,5,6,16)" · 최신본(`20230224002432`, 각주번호 추가) | 같은 라벨(각주없음) · 구본(`20210322000148`) — R2 셀키가 라벨 완전일치라 각주번호 추가만으로도 "다른 셀" 취급됨 |

나머지 11건도 동일 패턴(대표 3~4건 원문 직접 XBRL/문서 대조, 전체 15건 report_lines 계보
추적으로 확인) — **15건 중 14건이 이 단일 메커니즘**. 예외 1건(00626011 아이텍)은 이미 알려진
R23(`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`) 버그와 동일 corp — 별개 원인, 이 트랙 범위 밖.

### 왜 `_CURRENT_STRICT`가 이미 있는데도 00146296/00364403(별도)가 못 잡혔나

`_CURRENT_STRICT` 사전필터는 "current 라벨이 하나라도 있으면 non-current 후보를 전부 버린다"다.
00146296은 "단기매입채무"(current, 원본의 stale 셀)가 존재하므로, **정답인 비유동 라벨이 필터
단계에서 이미 삭제된 뒤 아래 override 체크에 도달**한다 — 그래서 이번 override는 `rows`(필터
후)가 아니라 `cands[canonical]`(필터 전 전체 후보)에서 직접 검증된 라벨을 찾는다.

## 2. 왜 "새 버그"가 아니라 "기존 패턴의 신규 사례"인가

`combine.py:83-95`(`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`) 주석이 이미 이 트레이드오프를
설명한다: *"Most corps' narrow child value ('단기매입채무' 등) already matches report_won...
Only corps where report_won/source comparison confirmed the parent total IS the answer go
here."* — 이번 15건(14건)은 바로 그 "확인된 corp" 목록에 들어갈 **신규 사례**일 뿐이다.
R41의 lateral 스캔(미등재 corp 탐지)이 우연히 다른 트랙(additive)을 통해 이 사례들을 잡아낸
것 — 설계상 예견됐던 "T0 축 B"(신규 corp가 override 대상이 되는 경우, §6 결정사항 3 에서
1차범위 밖으로 분리됨)의 실제 사례이기도 하다.

## 3. 이번 15건이 corp-blanket 이 아니라 (corp, fy, period, **basis**) 로 좁아야 하는 이유

`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`의 기존 주석은 "basis 는 별도 키 불필요"라 적었으나, **이번
발견으로 그 가정이 깨진다** — 00364403 쏠리드 2015Q3는 **연결은 current 라벨이 정답, 별도는
non-current 라벨이 정답**이다(같은 corp, 같은 기간, 다른 basis, 다른 정답 concept). 그래서 새
override는 `_TRADE_PAYABLES_ADDITIVE_OVERRIDE`와 달리 **basis 를 키에 포함**한다.

## 4. 조치

`fin2/layer3/combine.py`에 `_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`(신설, (corp,fy,period,basis)
→ 검증된 정답 라벨) 추가. `_resolve()`에 `basis` 파라미터를 새로 받아, 원문대조로 확정된 라벨과
`_norm_label()` 일치하는 후보를 `cands[canonical]`(필터 전 원본, `_CURRENT_STRICT` 우회)에서
찾아 값이 유일하면 그 값을 확정한다. 14건 전부 개별 원문/report_lines 계보 대조 완료.

**등재 대상 14건**(00626011 제외):

00124276(2019H1/2015Q3, 별도) · 00131197(2016H1, 연결+별도) · 00145473(2016Q3, 별도) ·
00146296(2015Q3, 연결+별도) · 00152783(2019H1, 연결+별도) · 00271501(2015H1, 별도) ·
00303217(2017Q1, 별도) · 00317210(2017Q3, 연결+별도) · 00364403(2015Q3/2015H1, 연결+별도) ·
00442455(2021Q3, 연결+별도) · 00603348(2015H1, 연결+별도) · 00923826(2020FY, 연결+별도).

**게이트**: `pytest tests/ fin2/tests/` 회귀 0, 이 14건 face_audit 재실행으로 fail_a→pass 확인,
같은 corp 의 **다른 모든 기간**에 새 fail 발생 0(과거 LG화학 사례처럼 같은 corp 안에서도
기간별로 성립/불성립이 갈릴 수 있다는 경고, §4 참고 — 개별 기간별로만 등재했으므로 다른
기간은 이 override 의 영향을 받지 않아야 정상).

관련: [[gateb-curated-key-candidates-review-2026-08-21]](R41 후속 리뷰, 이 트랙의 출발점),
`docs/PARSING_RULES.md` R2(정본 정책).
