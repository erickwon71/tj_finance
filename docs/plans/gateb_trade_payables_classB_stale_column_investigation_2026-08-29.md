# Gate B — trade_payables 클래스B(14건) 원인 확정: 2개의 서로 다른 버그
# 조사 결과 (2026-08-29)

## 0. 배경

[[gateb-trade-payables-45-triage-2026-08-28]] 클래스B 3건(홈캐스트·버넥트·탑코미디어·
이연제약·큐라티스·파라다이스·에이엘티, 14행)을 원문 XML 전건 대조했다. **같은
클래스 안이라도 원인이 다를 수 있다**([[gateb-trade-payables-classC-rootcause-2026-08-29]]
의 교훈과 같은 계열)는 우려대로, 이번에도 **2개의 서로 다른 버그**로 갈렸다. 설계만
담았다 — 미구현([[feedback-plan-then-wait]]).

## 1. 유형1(12행/6개사) — Track B(text.py) 선두 None 절삭 과잉적용

### 원인

`fin2/extract/text.py:944-954`(`_emit_section`, commit `f4819b8`, 2026-06-21)가
비-interim(cum_map 없음) 경로에서 행의 **선두 None 컬럼을 무조건 절삭**하고 남은
값을 col0(당기)부터 다시 번호 매긴다:

```python
amts = row.amounts
lead = 0
while lead < len(amts) and amts[lead] is None:
    lead += 1
pairs = list(enumerate(amts[lead:]))
```

이 가드는 원래 **다른 버그**를 고치려고 만들어졌다(golden 5/5 확인, 한화손해보험
2020 연결 IS "VIII.당기순이익" [None, 48.25B, −69B] — 표 파서가 끼워넣은 **phantom**
선두 빈칸 때문에 진짜 당기값이 col1로 밀려 net_income 소실). 그 케이스는 선두
빈칸이 파서 아티팩트였고 진짜 당기값은 그 다음 칸에 있었다.

이번 6개사는 **정반대** — 선두 빈칸이 파서 아티팩트가 아니라 **원문 자체가 당기
컬럼을 비워뒀다**(원문대조 확인, 인접 ACODE 셀에 ACONTEXT 없이 텍스트만 공백).
비교(전기, 드물게 전전기)컬럼에만 진짜 값이 있는데, 이 가드가 선두 None을 절삭해
그 비교값을 col0(당기)으로 오귀속시킨다.

### 원문대조 실측(8개 파일, corp/fy/period/basis별 acode 라인 직접 확인)

| 회사 | 필링 | basis | 당기(col0) | 전기(comparative) | DB(오염값)=전기 |
|---|---|---|---|---|---|
| 홈캐스트(00385336) | 2025FY(`20260317000796`) | 양쪽 | 203,341,500(정상) | — | (오염 없음, 참고용) |
| 홈캐스트 | 2026Q1(`20260515002885`) | separate | **공백** | 203,341,500 | 203,341,500 |
| 홈캐스트 | 2026H1(`20260814003462`) | 양쪽 | **공백** | 203,341,500 | 203,341,500(양쪽) |
| 홈캐스트 | 2024FY(`20250318000953`) | separate | **공백** | 589,828,289 | 589,828,289 |
| 버넥트(01605529) | 2025Q3(`20251114002040`) | 양쪽 | **공백** | 113,572,319 | 113,572,319(양쪽) |
| 버넥트 | 2025FY(`20260320001235`) | separate | **공백** | 113,572,319(PFY2024) | 113,572,319 |
| 탑코미디어(00608699) | 2024FY(`20250318001254`) | 양쪽 | **공백×2**(당기+전기 둘다) | 1,589,931,587(전전기 BPFY2022) | 1,589,931,587(양쪽) |
| 큐라티스(01357765) | 2025FY(`20260323000808`) | separate | **공백** | 370,141,289 | 370,141,289 |
| 파라다이스(00171265) | 2025Q1(`20250515001099`) | separate | **공백** | 5,441,160 | 5,441,160 |
| 에이엘티(00493325) | 2024FY(`20250321000568`) | separate | **공백×2**(당기+전기 둘다) | 15,363,590(전전기 BPFY2022) | 15,363,590 |

탑코미디어·에이엘티는 당기+전기 **두 컬럼 다 공백**이고 전전기(2년전)만 값이
있는 더 심한 변형 — 같은 `while` 루프가 몇 칸이든 앞의 None을 다 절삭하므로
매커니즘은 동일(정도만 다름).

### ★중요 — 이 버그는 trade_payables 전용이 아니다

`_emit_section`의 이 경로는 **Track B(비XBRL/텍스트) 로 읽히는 모든 BS/IS
canonical 필드**가 지나간다 — 원문 당기 컬럼이 진짜로 빈(널/보고 안 함) 행이면
어떤 필드든 같은 방식으로 전기값이 당기로 오귀속될 수 있다. 이번 14건 트리아지는
trade_payables 라는 **하나의 필드**만 봤을 뿐, 잠재 파급범위는 face_audit이
독립적으로(Track A) 대조할 수 있는 XBRL 보고서에서만 fail_a로 드러난다 — Track
B**만** 있는(순수 텍스트, XBRL 자체가 없는) 구형/중소형 보고서에서는 std_v3와
face_audit이 **같은 소스(Track B)를 이중으로 읽어 서로 대조하는 게 아니라 사실상
자기 자신과 비교**하게 돼(face_audit도 Track B 폴백을 씀), **Gate B가 원천적으로
못 잡는 잠복 오염**일 가능성이 있다(R55가 발견한 "검증기가 못 잡는 잠복 오염"과
같은 계열 우려). 전수 파급범위는 별도 SQL/스크립트 실측 필요 — 아래 §3 참고.

### 수정 방향(설계만, 미확정)

핵심 난제: **"파서 아티팩트로 생긴 선두 공백"(원래 가드의 대상, 절삭이 정답)**과
**"원문이 실제로 당기 컬럼을 비워둔 것"(이번 6개사, 절삭하면 안 됨)**을 Track B의
`RowData.amounts`(문자열 리스트→파싱값 리스트, ACODE/ACONTEXT 정보 이미 소실)만
가지고는 **행 하나만 봐서는 구분할 수 없다** — 두 경우 다 `[None, value, ...]`로
동일하게 관측된다.

후보 방향(우선순위 미정, 검토 필요):
1. **테이블 단위 신호**: phantom 컬럼은 원래 사례(보험 IS 총계행)처럼 **그 표의
   일부 행에서만** 나타나는 렌더링 아티팩트일 가능성이 있다 — 같은 표의 다른
   행들 대다수가 col0에 실값을 갖는데 이 행만 선두 None이면 "행 고유의 진짜 빈값"
   신호로 보고 **절삭하지 않는** 쪽으로 기울일 수 있음. 단, 원래 동기가 된 사례도
   "총계행 하나만" 문제였을 가능성이 있어 이 신호가 두 경우를 실제로 가르는지
   표본 검증 필요.
2. **선두 None 개수 상한**: 지금은 몇 칸이든 다 절삭한다. 탑코미디어·에이엘티처럼
   2칸 이상 절삭해 전전기(2년 전) 값을 당기로 삼는 것은 원래 가드의 동기
   ("phantom 컬럼 1개")를 벗어난 과잉적용 — **최대 1칸만 절삭**하도록 캡을 씌우면
   이 2개사 4행은 (절삭 안 됨 → col0=None(스킵), 진짜 값은 col1=전기로 정확히
   슬롯됨) 안전하게 고쳐진다. 단, 나머지 4개사(홈캐스트 대부분·버넥트·큐라티스·
   파라다이스, 선두 1칸만 빈 케이스)는 이 캡만으로는 해결 안 됨 — 여전히 1칸
   절삭되어 오염 지속.
3. **1번+2번 조합, 또는 완전히 다른 신호**(예: 문서 전체에서 같은 acode/라벨의
   다른 필링에서 이 (corp,fy,period) 조합이 정말 "무보고/0"인지 교차확인) — 설계
   심화 필요.

**리스크**: 이 함수는 광범위하게 쓰이는 공용 경로라, 섣부른 변경은 원래 동기가
된 한화손해보험류 사례(및 그 계열 미상 회귀)를 되살릴 수 있다. 변경 전 그
케이스의 회귀 테스트 확보 필수(`git show f4819b8` 참고, 전용 golden 테스트는
현재 저장소에 없어 보임 — 확인 필요).

## 2. 유형2(2행/1개사) — 이연제약(00145598) 2025Q1, R42류 정정본 하위구성변경

### 원인

`filings` 조회: 원본(`20250515003051`, is_amendment=False, is_final=False) →
정정(`20250530002768`, is_amendment=True, is_final=True). **원본**의 BS엔 순수
"매입채무"(acode `dart_ShortTermTradePayables`, 당기 CFY2025eFQA)가 **당기 컬럼에
정상적으로** 7,837,235,184로 태깅돼 있다(공백 아님). 하지만 **정정본**은 이 라인을
"매입채무 및 기타유동채무"(acode `ifrs-full_TradeAndOtherCurrentPayables`)로
결합해 재렌더링했고 그 당기값은 14,467,303,399(원본의 7,837,235,184와 다름,
합병 총계라 당연히 다름).

DB(std_v3)의 trade_payables=7,837,235,184는 **원본(superseded)의 값**이다 —
[[gateb-trade-payables-stale-subline-r42-2026-08-21]](R42)가 이미 고친 것과
**정확히 같은 메커니즘**("정정본이 BS 하위구성을 바꿔 결합 라벨로 재렌더링하면,
`combine.py`가 원본의 개별 stale 라인을 여전히 채택") — 다만 이 (corp, fy, period,
basis) 조합은 R42의 `_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`(14개사 curated)에
**아직 등재돼 있지 않다**(새 인스턴스, R42 완료 이후 2025Q1 필링이라 그때는 존재
안 했음).

### 수정 방향(낮은 위험, R42 레시피 그대로)

`fin2/layer3/combine.py::_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`에 1줄 추가:

```python
("00145598", 2025, "Q1", "consolidated"): "매입채무 및 기타유동채무",
("00145598", 2025, "Q1", "separate"): "매입채무 및 기타유동채무",   # separate 도 같은 패턴인지 확인 필요(§3)
```

R42와 동일 절차(std_v3 재백필 필요, 표본 검증 → 전수 재감사)로 닫을 수 있는
**가벼운 트랙** — 이미 검증된 메커니즘의 새 인스턴스일 뿐, 새 코드 경로 없음.
단, separate basis(2번째 fail 행)는 아직 원문 확인 안 함 — 착수 전 확인 필요.

## 2.5 파급범위 실측 결과(2026-08-29, 유형2 구현 직후 착수)

§1 "이 버그는 trade_payables 전용이 아니다"에서 제기한 우려에 따라 실측을 시도했다.

**(b) Track A 대조가 있는 다른 필드** — 현재 fail_a 백로그(trade_payables 외
123행)에 "같은 corp+basis+필드에서 값이 다른 기간에도 반복"하는지 SQL로 대조.
26건 검출됐으나 **21건이 `dividends_paid`**(누적 YTD CF 필드 — 연중 특정 시점에
1회 배당하면 그 뒤 H1→Q3→FY 에 걸쳐 값이 그대로 반복되는 게 **정상 동작**,
버그 신호 아님). 나머지 2건(케이알엠 00536888 tax_expense·광무 00186452
inventory)은 원문 직접 대조 결과 **둘 다 유형1과 무관**함을 확인 — 케이알엠은
최종(is_final) 필링에 법인세비용 라인 자체가 없어 combine.py가 구필링으로
폴백하는 **다른 메커니즘**, 광무는 당기 컬럼이 정상적으로 직접 태깅돼 있어
선두공백 패턴이 아님(휴면 소형사의 실제 무변동 가능성).

**결론**: "값 반복" SQL 휴리스틱으로는 trade_payables 6개사 외 유형1의 추가
확증 사례를 찾지 못했다. 이 신호는 노이즈가 너무 커서(값이 정상적으로 안
변하는 필드가 많음) 신뢰할 만한 탐지 수단이 아니다 — trade_payables(부채
잔액, 매기 변동이 자연스러움) 특성상 겹치는 값 자체가 이례적이었기 때문에
유효했을 뿐, 일반화되지 않는다.

**(c) Track B-only(XBRL 없는) 필링의 잠복 오염** — face_audit이 원천적으로
못 잡는 영역이라 SQL 프록시로 측정 불가(측정하려면 원문 재파싱+표본 수작업
검증이 필요, 이번 세션 범위 밖). **미측정 — 열린 리스크로 남김.**

→ 유형1의 수정 범위는 **현재 확증된 6개사 12행(trade_payables)으로 한정**해
진행하는 것이 근거에 부합한다. 다른 필드·Track B-only 잠복오염은 이 세션의
얕은 SQL 방법으로는 안전하게 배제할 수 없으므로, "영향 없다"고 단정하지 않고
미상으로 남긴다.

## 3. 다음 단계(승인 대기)

1. **유형2(이연제약)**: R42 레시피 그대로, 낮은 리스크 — separate basis 원문
   확인 후 override 2줄 추가 + 표본 재백필/재감사로 바로 착수 가능.
2. **유형1(6개사 12행)**: 수정 설계 미확정(§1 "후보 방향" 중 택일/조합 필요),
   **파급범위 실측 우선 권장** — trade_payables 외 다른 필드도 같은 패턴으로
   오염됐는지, 그리고 Track B-only(XBRL 없는) 필링에서 Gate B가 원천적으로
   못 잡는 잠복 오염이 얼마나 되는지 SQL/스크립트로 먼저 재봐야 수정 우선순위와
   범위를 정할 수 있음. 유형2보다 훨씬 무거운 트랙.
3. 어느 쪽부터, 혹은 파급범위 실측부터 할지 사용자 결정 필요.

## 4. 범위 밖

- 클래스A(24건, R54로 이미 종료)·클래스C(3건, R55+R56로 이미 종료) — 이 문서는
  클래스B(14건)만 다룬다.

## 5. 유형1 재조사(2026-08-29 속행) — 원문 직접 재현으로 §1의 가정을 재검증

§1은 "선두 None이 파서 아티팩트(절삭 정답)인지 원문 실공백(절삭 오답)인지 행 하나만
봐서는 구분 불가"를 전제로 3가지 후보 방향을 냈다. 이번 속행에서 실제 원문 XML을
`extract_rows()`에 직접 태워 재현한 결과, 이 전제 자체가 갱신이 필요함을 확인했다 —
**두 사례는 서로 다른 표 구조이며, 각자 이미 존재하는 더 정밀한 신호로 구분 가능하다.**

### 5.1 f4819b8의 원 동기(한화손해보험)는 R19(2026-08-24 확장)가 이미 근본 해소함

한화손해보험 2020FY 원문(`annual/2020/20210310000259.xml`)의 "VIII. 당기순이익(손실)"
행을 직접 확인: `<TD>` 표(ACODE 없음, 구형 비XBRL 렌더링)이고, THEAD에 "주석" 열이
따로 있으며(폭 76, 당기/전기 열은 폭 147), 같은 표의 다른 행들에 콤마 다중참조 주석
("9,28", "28,40" 등)이 실재한다. `extract_rows()`를 이 표에 직접 실행한 결과:

```
row.amounts == [48250117187, -69073849554, None]   # 선두 None 없음(재현 스크립트로 확인)
```

이유: `_split_label_amounts()`의 R19 v7 규칙(`table_has_note_column=True`인 표에서는
**빈칸도** 항상 주석 칸으로 인정, 2026-08-24 확장분)이 이 행의 빈 주석 칸을
`amount_cells`에서 이미 제외한다 — `_emit_section`의 선두 None 절삭이 관여하기도 전에
문제가 사라져 있다. `report_lines.py:478-483`의 기존 주석도 이 사실(cum_map 분기 한정)을
이미 인지하고 있었다 — else 분기(선두 None 절삭 루프)만 그 인지 반영 없이 그대로 남아
있었을 뿐이다.

⟹ **f4819b8을 정당화했던 원 사례는 지금은 R19가 이미 고쳐놓은 상태** — `_emit_section`의
선두 None 절삭은 이 사례에 대해 더 이상 필요하지 않다(무해하게 통과할 뿐, 발동 안 함).

### 5.2 클래스B 6개사는 "주석 컬럼"과 무관 — ACONTEXT 자체가 없는 진짜 미공시

**6개사 12행 전건 원문 재확인 완료(2026-08-29, 2차 속행)** — 홈캐스트·탑코미디어에
이어 버넥트(2025Q3 양쪽basis·2025FY separate)·큐라티스(2025FY separate)·파라다이스
(2025Q1 separate)·에이엘티(2024FY separate) 원문도 전부 직접 대조. **예외 0건, 전부
동일 시그니처**: 문제의 셀은 예외 없이 `<TE ACODE="dart_ShortTermTradePayables" ...>`
(ACONTEXT 속성 자체가 없음) 이고, 같은 행의 정상 값이 있는 셀은 예외 없이 같은 ACODE에
`ACONTEXT="..."`가 실제로 붙어 있다 — "ACODE 있고 ACONTEXT 없음 ⟺ 원문이 실제로 그
기간을 미공시" 신호가 12행 전부에서 **필요충분**하게 성립함을 확인(반례 0건). 표 구조는
한화손해보험류와 다르다:

```xml
<!-- 홈캐스트 2026Q1 별도 매입채무: 주석 컬럼 자체가 표에 없음(순수 [당기,전기] 2열) -->
<TE ACODE="dart_ShortTermTradePayables" ...>　</TE>                                    <!-- 당기: ACONTEXT 없음 -->
<TE ACODE="dart_ShortTermTradePayables" ACONTEXT="PFY2025eFQ_..._SeparateMember">      <!-- 전기: ACONTEXT 있음 -->
  203,341,500</TE>
```

```xml
<!-- 탑코미디어 2024FY 매입채무: 순수 [당기,전기,전전기] 3열(연간 표준 비교표), 주석 컬럼 없음 -->
<TE ACODE="dart_ShortTermTradePayables" ...>　</TE>              <!-- 당기: ACONTEXT 없음 -->
<TE ACODE="dart_ShortTermTradePayables" ...>　</TE>              <!-- 전기: ACONTEXT 없음 -->
<TE ACODE="..." ACONTEXT="BPFY2022eFY_..._ConsolidatedMember">   <!-- 전전기: ACONTEXT 있음 -->
  1,589,931,587</TE>
```

두 표 다 주석(비고) 컬럼이 아예 존재하지 않는 순수 기간열 구조다. 대신 **당기(탑코미디어는
전기도) 셀에 `ACONTEXT` 속성 자체가 없다** — Track A(`fin2/extract/xbrl.py:144-145`
`if not acontext: continue`)가 "이 셀은 Track A 대상 아님"으로 스킵하는 것과 **동일한
신호**다. 즉 DART 원문 자신이 "이 계정을 이 기간엔 이 acode로 공시하지 않았다"(합채 라벨로
재편 등)고 구조적으로 명시한 것 — Track A는 이 신호를 보고 정확히 값을 안 만드는데, Track
B(`_get_cells`→`extract_rows`)는 TE 셀도 TD와 동일하게 **텍스트만** 읽어 ACONTEXT 유무를
아예 보지 않는다. 그래서 "표시 안 함"과 "파서가 만든 phantom 칸"을 구분할 신호가 원천적으로
없었고, `_emit_section`이 그 자리를 지금까지 **항상 후자로 단정**해 온 것이 이번 6개사
오염의 실제 원인이다.

### 5.3 §1의 "표/개수 신호" 계열 후보는 기각

"amount_cells 개수로 note-column 의심 여부를 가른다"(예: ≥3개면 절삭, ≤2개면 금지) 같은
셀-개수 기반 규칙을 검토했으나 **탑코미디어 사례가 즉시 반증한다**: 그 행은 amount_cells가
3개([당기,전기,전전기])지만 주석 컬럼과 전혀 무관한, 코드베이스 전체에서 가장 흔한 연간
3기 비교표 형태다. 셀 개수만으로는 "주석 컬럼이 있는 표"와 "3기 비교표"를 구분할 수 없다
— §1이 우려했던 함정과 같은 종류다.

### 5.4 재설계: ACONTEXT 유무를 절삭 여부의 판정 신호로 사용(신규 방향, 구조적·무모호)

- **핵심**: `<TE ACODE=...>`인데 `ACONTEXT` 속성이 없는 셀은 DART 원문이 스스로 "이 기간
  미공시"라고 표시한 것 — 판단이 아니라 원문 구조 그대로 전사(계층2 원칙에 부합). `<TD>`
  (ACODE 자체 없는 구형 비XBRL 셀)는 이 신호가 없으므로 기존 로직(R19 포함) 그대로 둔다.
- 구현 스케치(가산적, `_get_cells` 자체는 불변): `parser/xml/table_extractor.py`에 병렬
  헬퍼 `_get_cell_acontext_missing(tr) -> list[bool]` 신설(TE+ACODE 있고 ACONTEXT 속성
  없으면 True, 그 외 전부 False) → `extract_rows()`가 `_get_cells(tr)`와 나란히 호출해
  `RowData`에 새 필드(예: `acontext_missing: list[bool]`, `amounts`와 동일 인덱스)로
  실어 나른다.
- `_emit_section`(text.py) 및 동형 else 분기(report_lines.py:519-523)의 선두 None
  절삭 루프 변경: 선두 None 위치의 `acontext_missing[i]`가 **True**면 절삭하지 않고
  그 칸을 그대로 None으로 둔 채(다음 실값부터 정상 열거) 진행, **False**면 기존 동작
  그대로 절삭(R19 사각지대 안전망 유지, 회귀 없음).
- 효과: 6개사 12행(TE+ACONTEXT無 확인)은 절삭 안 됨 → col0=None(스킵), 실값은 원래
  열 위치(전기/전전기)에 정확히 슬롯 → trade_payables fail_a 해소. 한화손해보험류
  (TD, 신호 없음=False)는 로직 분기 자체가 안 건드리므로 **완전히 무변경**(회귀
  구조적으로 불가능).

### 5.5 구현 범위·리스크·검증 계획(설계만, 미착수)

- 변경 파일 3개: `parser/xml/table_extractor.py`(신규 헬퍼+`RowData` 필드 추가, 기존
  호출자 시그니처는 불변) · `fin2/extract/text.py::_emit_section` · `fin2/extract/
  report_lines.py`(519-523행 동형 분기) — 두 소비처가 쌍둥이 로직이라 **반드시 함께**
  고쳐야 함(하나만 고치면 나머지가 계속 오염).
- 리스크: `RowData`/`extract_rows`는 광범위 공용 함수 — 필드 추가는 가산적이라 기존
  호출자엔 영향 없어야 하나, `_split_label_amounts` 쪽에서 amount_cells 필터링(주석 칸
  스킵 등)이 셀을 **드롭**하는 경우 신규 `acontext_missing` 리스트도 같은 인덱스로
  같이 드롭돼야 정합이 맞는다 — 구현 시 정확한 동기화 필요.
- 검증 계획: ① 신규 golden/회귀 테스트 2건 고정(한화손해보험 2020FY net_income=
  48,250,117,187 무변경 확인 + 홈캐스트 2026Q1 별도 trade_payables가 절삭 없이
  col0=None이 되는지) ② 6개사 12행 표본 재검증 ③ `pytest tests/ fin2/tests/` 전체
  ④ 사전 census(전체 corpus에서 "TE ACODE 있고 ACONTEXT 없는 셀이 선두에 오는 행"
  전수 카운트)로 파급범위 추정 후 전수 재백필/재감사.

## 6. 파급범위 census 결과(2026-08-29, 3차 속행)

`scripts/census_classB_leading_none_acontext_2026-08-29.py` — Track B 전체
모집단(`download_tasks.parser_track='B'`, 168,352건) 중 3,000건(1.78%) 무작위
표본. 실제 프로덕션 함수(`_detect_fin_type`·`_detect_body_statement_tables`·
`extract_rows`·`_split_label_amounts`·`_table_has_comma_note_column`)를 그대로
재사용하고, §5.4의 판정 로직만 계측용으로 나란히 시뮬레이션(OLD=현재 무조건절삭
vs NEW=`acontext_missing=True`인 선두 None 앞에서 절삭 중단) — 최종 (col_idx→금액)
페어가 실제로 달라지는 행만 카운트(둘 다 빈 결과인 경우 등 무영향 케이스 제외).

**결과**:
- 검사 대상 행(non-cum_map else 분기): 375,942행
- 현재 선두 None 절삭이 발동하는 행: 33,457행
- 그중 §5.4 적용 시 **최종값이 실제로 바뀌는 행**: **397행(1.19%)**
- 전체 모집단 외삽(표본 1.78%→): **약 22,000행** 규모(오더 추정)
- 영향받은 **필링(rcept_no) 수**: 표본 내 37건(3,000건 중 1.23%) → 전체 외삽
  **약 2,000개 필링** 규모
- 재무제표유형별: **CF 315 / BS 82** — 현금흐름표 항목(장/단기금융상품 처분·취득,
  사채상환, 임대보증금 증감 등)이 압도적 다수. **trade_payables 전용이 아니라는
  §1의 우려가 이번엔 SQL 휴리스틱이 아니라 실제 시뮬레이션으로 확증됨.**
- 연도 분포: 2023년 357행(33개 필링)로 90% 집중, 2022/2024/2025/2026 각 1개
  필링(4~23행). **2023년, 그중에서도 2023Q3(11월 제출분) 필링 소수가 필링당
  5~8개 항목씩** 한꺼번에 영향받는 군집 패턴 — 노이즈성 산발이 아니라 **특정
  시기 필링군의 ACONTEXT 태깅 공백**으로 보임(원인 자체는 이 census 범위 밖,
  DART 원문/제출 소프트웨어 쪽 사정으로 추정, 별도 조사 대상 아님 — 계층2는
  원문을 있는 그대로 반영하면 됨).
- **오검출(회귀) 가능성**: 이 신호(ACONTEXT 유무)는 DART 원문 자신의 명시적
  구조라 논리상 오탐 방향이 없다 — `acontext_missing=True`인 칸은 정의상 "그
  기간 실제로 미공시"이므로, 절삭을 멈추는 쪽이 항상 원문에 더 충실하다(값을
  만들어내는 게 아니라 잘못된 값 하나를 안 만드는 것). 표본에서도 새 값이 old
  값보다 "틀려 보이는" 사례는 없었다(전부 "당기 오염값 제거, 전기/전전기 정상화"
  형태).

## 7. 구현 완료(2026-08-29)

§5.4 그대로 구현. 변경 파일 3개:
- `parser/xml/table_extractor.py` — `RowData.acontext_missing: list[bool]` 신규
  필드, `_split_label_amounts()`는 기존 2-tuple 시그니처 유지(호환), 내부 로직은
  `_split_label_amounts_ex()`(라벨/금액/플래그 3-tuple)로 이전해 **로직 복제 없이**
  래핑. `_get_cell_elements()`/`_cell_acontext_missing()` 신규 헬퍼.
- `fin2/extract/text.py::_emit_section` — else 분기 선두 None 절삭 루프가
  `acontext_missing[i]=True`인 칸 앞에서 멈추도록 변경.
- `fin2/extract/report_lines.py::_emit_section_lines` — 동형 else 분기(519행대)
  동일 변경(쌍둥이 로직, 반드시 같이 고쳐야 함 — §5.5).

**검증**:
- 한화손해보험 2020FY 연결 net_income col0=48,250,117,187 **무변경** 확인(원 동기
  사례 회귀 없음).
- 6개사 12행 전건을 `extract_facts()`로 직접 재추출해 §5.2 원문대조 기대값과
  **정확히 일치** 확인(예: 홈캐스트 2026Q1 별도는 col0 자체가 안 나오고 col1=
  203,341,500만 정확히 슬롯).
- `fin2/tests/test_text.py`에 회귀 테스트 2건 신규 추가(`test_hanwha_insurance_
  net_income_no_regression`, `test_classB_genuine_current_period_gap_not_
  misattributed`).
- `pytest tests/ fin2/tests/` — **634 passed, 1 failed**. 실패 1건
  (`test_biz_section.py::test_lxintl_facility_table_dropped`)은 이번 변경 전
  코드(`git checkout` 방식 대신 실수로 `git stash`/`pop` 사용 — 즉시 발견해 전부
  복구, 유실 없음)로도 동일하게 실패함을 확인 — **이번 변경과 무관한 기존 실패**.

**참고**: `fin2/extract/text.py::extract_facts()`는 `fin2/extract/cf_da.py`(CF
D&A 주석 추출)에서도 쓰인다 — 이번 수정으로 그쪽도 같은 방식으로 정확해지지만,
이 트랙의 census(§6)는 std_v3(report_lines.py 경로)만 측정했다. cf_da 쪽 파급은
별도 측정 안 함(범위 밖).

## 8. 백필+재감사 절차(승인 대기 — 사용자 실행)

[[feedback-long-running-commands]]에 따라 장시간·DB쓰기 명령은 직접 실행하지 않고
안내만 한다. `scripts/run_classB_leadingNone_backfill_2026-08-29.sh` 신규(R19
백필 스크립트와 동일 2단계 패턴: report_lines 전량 재추출 → std_v3 재표준화,
각 5-shard 병렬).

**백필 전 기준선(2026-08-29, 이 트랙 착수 직전)**: `face_audit`(source_version=
'v3') 전체 fail_a **83건**, 그중 `trade_payables` fail_a **15건**.

절차:
1. 스냅샷 생성 → 2. 백필 스크립트 실행(수시간 예상, 백그라운드 권장) → 3. Gate B
전수 재감사(`scripts/run_gateb_audit_parallel.sh`, 기존 스크립트 그대로) → 4.
스냅샷 대비 등급 전이 확인([[gateb-full-reaudit-is-required-to-close]]) → 5. 결과를
Claude 에게 공유 → 6. 이상 없으면 커밋.

## 9. 다음 단계

§7 구현 완료. §8 백필 완료(2026-08-30 01:30:40, 1·2단계 모두 에러 0건) — 사용자가
직접 실행. Gate B 전수 재감사(`run_gateb_audit_parallel.sh`)는 사용자가 08:00경
시작, **결과는 다음 세션에서 공유 예정**. 다음 세션 시작점: 재감사 결과를
`face_audit_snap_20260829` 대비 등급 전이 분석 → 이상 없으면 커밋.

Related: [[gateb-trade-payables-45-triage-2026-08-28]],
[[gateb-trade-payables-stale-subline-r42-2026-08-21]],
[[gateb-trade-payables-classC-rootcause-2026-08-29]],
[[feedback-verify-against-source]], [[feedback-plan-then-wait]],
[[feedback-plan-docs-in-project]], [[feedback-long-running-commands]],
[[gateb-full-reaudit-is-required-to-close]], [[feedback-git-stash-pop-hazard]].
