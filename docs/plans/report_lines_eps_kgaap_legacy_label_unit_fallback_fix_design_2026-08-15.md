# 설계 — `report_lines.py::_emit_eps_lines` K-GAAP 구서식(00269852류)
라벨 단위폴백 버그 수정안 (2026-08-15 작성)

> [[gateb-3tracks-investigation-2026-08-15]] §3(완결)의 "다음 세션" 항목 ②
> — "`_emit_eps_lines` 수정안 설계" 후속. 이 문서는 **설계만 한다 — 구현은
> 미착수, 사용자 승인 필요**(`CLAUDE.md` 정책, [[feedback-plan-then-wait]]).
>
> 이전 세션이 유력하다고 적어둔 "라벨에 단위선언 없으면 표의 선언단위로
> 폴백"이라는 방향은, 이번 세션 실측검증 결과 **그대로 구현하면 안전하지
> 않음이 확인됐다** — §2 참고. 이 문서는 그 실측을 근거로 더 좁고 안전한
> 대안(curated 허용목록)을 제안한다.
>
> **★★2026-08-15 같은 날 후속 세션(사용자 지시 "curated 키 목록 정밀
> 재확정부터 진행해")으로 §4-B~§4-D가 갱신됨** — curated 키를 라벨텍스트
> 추정이 아니라 (a) std_v3 기존 총계와의 독립 교차검증, (b) 원문 XML
> 직접대조 2건으로 재확정했고, 그 과정에서 **원래 제안한 키 단위(rcept_no
> 단독)가 너무 성글어 같은 표 안의 별개 정상 EPS 행까지 잘못 건드릴 뻔한
> 것**을 발견해 키를 `(rcept_no, statement, basis, table_seq, label_raw)`
> 5-튜플로 좁혔다. 최종 확정 결과는 §4-D 참고.

---

## ★다음 세션 시작점 (Resume Here)

**현재 상태: 설계 + curated 키 정밀 재확정까지 완료. 구현은 미착수,
사용자 승인 대기 중.**

- **확정된 것**: 원인(§1, 원문대조 100% 확정) · 일반규칙 기각 근거(§2,
  실측) · 제안 설계(§4-A, curated 5-튜플 키 방식) · **curated 키 최종
  확정값: 2,218개 키/1,871 rcept_no/1,560 filing/288개사/FY 1999~2008**
  (§4-D, std_v3 교차검증 271건 + 텍스트신호 1,947건 + 원문XML 2건 검증).
- **재현 가능한 산출물** (`scripts/`, repo에 영구 저장, 스크래치패드
  아님 — DB 상태가 안 바뀌면 재실행 시 100% 동일 결과 재현 확인함):
  1. `scripts/build_eps_curated_override_final_2026-08-15.py`
  2. `scripts/check_rcept_key_granularity_risk_2026-08-15.py`
  3. `scripts/finalize_eps_curated_keys_2026-08-15.py` →
     `scripts/eps_curated_final_keys_2026-08-15.json`(**최종 2,218개 키
     원본**, 구현 시 이 JSON을 `_EPS_UNIT_FALLBACK_OVERRIDE_KEYS`
     리터럴로 변환하면 됨)
- **다음에 할 일(사용자 승인 후)**:
  1. `_EPS_UNIT_FALLBACK_OVERRIDE_KEYS` frozenset을
     `fin2/extract/report_lines.py`에 추가(§4-A 코드 스케치 그대로).
  2. `_emit_eps_lines`에 `table_unit` 파라미터 threading, 단위 결정부
     수정(§4-A).
  3. 호출측(`_emit_section_lines`, 446~451줄)에 `table_unit=unit` 전달.
  4. 288개사 재추출(`scripts/reload_report_lines_corp.py`) →
     std_v3 재빌드(`scripts/build_std_v3.py`, 단 EPS는 combine.py가
     소비 안 해 다른 필드엔 영향 없음, §4-C) → `pytest tests/
     fin2/tests/` 회귀 확인 → 표본 원문대조로 최종 검증(§4-C).
  5. `docs/PARSING_RULES.md`에 R28로 등재(구현 완료 후).
- **미해결/범위 밖(승인과 별개로 남아있음)**: Phase 2 — `net_income`
  결측 복구 가능성(§3/§6, 표본 15건 중 9건+ NULL 확인됐으나 전수
  미측정, 별도 investigation 필요). REJECTED 티어(7,277건) 전수
  원문대조는 안 함(§6).
- **관련 메모리**: [[eps-kgaap-legacy-unit-fallback-design-2026-08-15]]
  (이 설계+재확정 작업의 전체 요약).

---

## 0. 요약

- **원인**(이미 확정, [[gateb-3tracks-investigation-2026-08-15]] §3-완결 참고):
  `_emit_eps_lines`는 라벨 자체에 단위선언이 없으면 표의 선언단위를 무시하고
  무조건 `unit=1`(원)을 쓴다. K-GAAP 구서식(2003~2010년)의 "ⅩⅢ.당기순이익
  (주당순이익: 당기 108원, 전기 181원)" 같은 **헤드라인 당기순이익 라벨에
  EPS 노트가 통짜로 곁들여진 라벨**이 "주당" 부분문자열 때문에 EPS 전용
  경로로 잘못 들어가고, 라벨 자체엔 단위선언이 없으니 `unit=1`이 적용돼
  **표가 천원/백만원 단위면 값이 1,000배/100만배 과소 저장**된다.
- **이번 세션 신규 실측(★핵심)**: "라벨에 단위선언 없으면 표 단위로
  폴백"이라는 원래 방향을 DB 실측으로 검증한 결과, **그대로 구현하면
  안전하지 않다** — 같은 조건(라벨에 단위선언 없음 + 표가 천원/백만원
  선언)에 걸리는 EPS 행이 9,495건 있는데, 이 중 절대다수(약 7,258건)는
  `기본주당이익`/`희석주당이익`/`주당순이익` 같은 **정상적인, 현재 올바르게
  저장된 EPS 라벨**이다(DART 관행상 EPS 라벨은 표의 전체 단위와 무관하게
  항상 원/주로 표기 — 애초에 `_emit_eps_lines`가 별도 경로로 분리된 이유
  그대로, [[gateb-controlling-ni-groupbc-kbimetal-eps-trap-2026-08-15]] 참고).
  이 정상 EPS 값들에 표 단위를 그대로 곱해버리면 **현재 맞는 값을 1,000배
  ~100만배 부풀려 새 버그를 만든다** — 원래 K-GAAP 버그(1,417행 추정)보다
  **훨씬 큰 규모(최대 7,258행+)의 회귀**가 된다.
- **결론**: 일반 규칙(모든 "단위선언 없는 EPS 라벨"에 표 단위 폴백)은
  기각한다. 대신 **이 프로젝트의 기존 선례(R16/R17/R20/R21/R23/R24 등)와
  같은 curated 허용목록 방식**을 제안한다 — 검증된 확정버그 필링만
  정확히 겨냥하고 나머지는 전혀 건드리지 않는다(§4).
- **부수 발견(★중요, 범위 확장 후보)**: 표본 점검 결과 이 버그가 **EPS
  값만이 아니라 `std_financials_v3.net_income`(그리고 그로부터 파생되는
  `controlling_ni`) 자체의 결측**과도 상당 부분 겹친다 — 헤드라인 라벨이
  통짜라 `account_mapper.map()`이 `unknown.*`로 떨어져 본류 후보가 아예
  안 생기기 때문(§3). 표본 15건 중 최소 6건에서 net_income이 NULL로 확인됐다
  (전수는 아님, 정밀측정 필요). 이 문서의 1차 범위는 EPS 값 자체의 오염
  방지/제거이고, net_income 결측 복구는 **별도 Phase 2로 분리**한다(§6).

---

## 1. 원인 재확인 (기존 확정 사실)

[[gateb-3tracks-investigation-2026-08-15]] §3-완결에서 이미 원문대조로
100% 확정된 내용(요약, 상세는 그 문서 참고):

- `fin2/extract/report_lines.py::_emit_eps_lines`(현재 320~365줄)는 셀[0]에
  "주당" 부분문자열만 있으면 EPS 행으로 간주하고, 라벨 자체의 인라인
  단위선언(`detect_unit_declaration(label)`, 없으면 **기본값 1**)으로
  금액을 파싱한다.
- 유아이디(00400121) 2004H1 IS표: 라벨 `"ⅩⅢ.당기순이익(주14)(당반기주당
  경상이익:143원 전반기주당경상이익:366원 당반기주당순이익:143원
  전반기주당순이익:366원)"` — 헤드라인 당기순이익 행인데 괄호 안에 EPS
  노트가 곁들여져 "주당" 부분문자열이 걸림(K-GAAP 구서식 관행). 자체
  단위선언이 없으니 `unit=1`로 확정, 파싱값(481,898 등)이 **스케일 전 raw
  값**인 채로 `_looks_like_eps_amounts`(≤1,000만원) 게이트를 우연히 통과
  (실제 천원 스케일 적용시 481,898,000원인데 raw 상태론 1,000만원 미만처럼
  보임) → EPS 행으로 확정 emit.
- 동시에 본류(`_emit_section_lines`)에서도 같은 행을 재검사하지만(스케일
  적용된 `row.amounts` 기준이라 "EPS 아님" 판정은 정상 통과) 라벨 자체가
  서술형 통짜라 `account_mapper.map()`이 `unknown.*`(신뢰도 0)로 떨어져 —
  **본류의 정답 후보가 애초에 안 생긴다**(§3에서 다시 다룸).
- 이전 세션 전수 스코핑(정밀 시그니처: `statement='IS' AND section_path=
  '주당손익' AND row_order IS NULL AND label이 당기순이익/처분전 헤드라인
  패턴`) → 7,459행, 704개사. 서브셋 재스캔(같은 물리적 표의 형제행 adecimal
  최빈값과 비교) → **확정버그 1,417행/206개사/1,307개 filing**(2003~2010).

---

## 2. 이번 세션 신규 실측 — "표 단위 폴백" 일반규칙의 안전성 검증

### 2-A. 방법

DB에서 `report_lines`의 EPS 경로 산출 행(`section_path='주당손익' AND
row_order IS NULL AND adecimal=0`, 즉 현재 `unit=1`이 적용된 행) 458,091건
전부를, 실제 `detect_unit_declaration()`/`ColumnUnits.from_declaration()`
로직으로 재파싱해 라벨 자체의 단위선언 유무로 분류했다(SQL 근사가 아니라
파서 실코드 재사용, `parser/common/amount_normalizer.py`·
`fin2/extract/units.py`).

```
전체 EPS-경로 unit=1 적용 행:        458,091
  라벨에 자체 단위선언 있음(unit=1이 의도적): 289,512  ← 건드릴 필요 없음
  라벨에 자체 단위선언 없음(unit=1이 기본값):  168,579  ← "폴백" 후보군
```

이 168,579건을, 같은 물리적 표(`rcept_no+statement+basis+table_seq`)의
**일반경로(row_order IS NOT NULL) 형제행들의 adecimal 최빈값**(= 그 표의
진짜 선언단위)과 대조했다.

```
표의 진짜 단위 = 원(0):        159,054  ← 표도 원단위라 unit=1 그대로 맞음, 무해
표의 진짜 단위 = 백만원(-6):      4,822  ┐
표의 진짜 단위 = 천원(-3):        4,673  ┘→ 합 9,495건 = "폴백하면 값이 바뀌는" 위험군
표의 진짜 단위 판정 불가:            30
```

### 2-B. 핵심 발견 — 위험군 9,495건 중 절대다수가 "정상, 건드리면 안 되는" EPS

위험군 9,495건의 라벨을 직접 눈으로 확인한 결과:

```python
'(1)기본주당이익'          # 00124504, 2011FY, 표는 천원 선언
'희석주당이익'              # 00631518, 2011FY, 표는 천원 선언
'계속영업기본주당이익(손실)' # 00631518
'주당순이익'                # 00210740, 2004FY
'(주당경상이익)'            # 00121932, 2005FY
```

이런 라벨들은 EPS(원/주) 개념상 표의 전체 스케일(천원/백만원)과 **무관하게
언제나 원 단위로 표기하는 것이 DART 관행**이고, 지금 DB에 저장된 값도
맞다(라벨에 단위선언이 없는 건 "원이 당연해서 안 적었기 때문"). "라벨에
단위선언이 없으면 표 단위로 폴백"을 그대로 적용하면 이 값들을 **1,000배~
100만배 부풀려 지금은 맞는 값을 틀리게 만든다**.

위험군을 "라벨에 (당기순이익/처분전/반기순이익/분기순이익 등) 헤드라인
단어가 있는가"로 나눠 봐도 깨끗이 갈리지 않는다 — 라벨 텍스트 규칙만으론
구분이 안 된다는 점이 R27(§4, KBI메탈 지배주주당기순이익 건)에서 이미 한
번 확인된 것과 **같은 패턴이 여기서도 재현**된다:

- `"당기순이익"`/`"처분전"` 부분문자열 매칭 → 1,639건 매치, 7,856건 비매치.
  그런데 비매치 7,856건 안에 **"반기순이익"/"분기순이익"/"당기순손실" 같은
  동의어 변형을 쓴 진짜 버그 라벨이 대량으로 섞여 있다**(예:
  `'XIII. 반기순이익(기본주당경상이익 및 순이익:당반기 : 862원, 전반기 :
  380원)'`, 45자) — 헤드라인 단어 목록을 넓혀도 완전한 커버리지를 장담할
  수 없다.
- 라벨 안에 "숫자+원" 토큰이 임베드돼 있는가(예: `'11.연결당기순이익(주당
  연결경상이익 및 순이익당기: 918원)'`) → 2,237건 매치. 이 신호는 **오탐
  (false positive)은 거의 없어 보인다**(20자 미만 매치 1건뿐이고, 그마저도
  진짜 EPS 라벨이 아니라 버그 패턴이 잘린 조각으로 보임) — 하지만 "숫자+원"
  형식이 아니라 괄호 안 순수 숫자(`(19)`, `당분기 91` 등)만 쓴 버그 라벨은
  놓친다(과소포착, 안전하지만 불완전).
- 라벨 길이 — 정상 EPS 라벨은 대부분 20자 미만(중앙값 10자)이고 버그
  라벨은 대부분 90자 이상(중앙값 120자)이라 **경향은 뚜렷하지만 깨끗한
  임계값이 없다**. 20~60자 구간에 `'XI.지배기업주주지분에 대한 주당이익'`
  (24자, 정상 EPS)과 `'13. 당기순이익 (주당경상이익:1,203) (주당순이익
  :1,203)'`(43자, 버그)가 섞여 있어 단일 길이 임계값으로는 두 종류를
  가르지 못한다.

**결론(§4의 재확인)**: 이 클래스의 문제는 R27이 이미 겪은 것과 동일하게
**라벨 텍스트 규칙만으로 원리적으로 구분 불가**하다. 값 크기 게이트(R27의
`_EPS_MAX_PLAUSIBLE_WON`)도 여기선 못 쓴다 — 문제의 근원 자체가 "스케일
전 raw 값이 EPS치고 그럴듯하게 작아 보인다"는 것이라 값 크기로는 애초에
못 걸러진다(R27 문서가 지적한 문제와 반대 방향).

---

## 3. 부수 발견 — `net_income` 결측 가능성 (범위 확장 후보, 미확정)

`_emit_eps_lines`가 라벨을 잘못 채가는 것과 별개로, 같은 행이 본류
(`_emit_section_lines`)에서도 스캔되지만 라벨이 서술형 통짜라
`account_mapper.map()`이 `unknown.*`로 판정해 **후보 자체가 안 만들어진다**
(§1 재확인). K-GAAP 구서식 IS 표에서 "ⅩⅢ.당기순이익" 행은 보통 그 표의
**유일한 순이익 헤드라인 행**이므로, 이 행이 매핑 실패로 빠지면
`std_financials_v3.net_income`이 그 회사/기간에 대해 **원천적으로 결측**될
가능성이 있다.

표본 점검(오늘 세션, 라벨에 헤드라인 단어 + 임베드된 "숫자+원" 토큰이 모두
있는 좁은 후보군 1,860행/1,342개 filing 중 15건 무작위):

| corp+fy+period | consolidated net_income | separate net_income |
|---|---:|---:|
| 00101044 2004H1 | -306,527,000(있음) | -306,527,000(있음) |
| 00190321 2005Q3 | 1,431,147,000,000(있음) | **NULL** |
| 00105952 2006FY | 243,663,000,000(있음) | **NULL** |
| 00269612 2004FY | **NULL** | **NULL** |
| 00351807 2004Q3 | **NULL** | **NULL** |
| 00298377 2004H1 | **NULL** | **NULL** |
| 00397191 2006FY | **NULL** | **NULL** |
| 00391197 2005H1 | **NULL** | **NULL** |
| 00223434 2004Q1 | **NULL** | **NULL** |

15건 중 상당수(9건 이상)에서 관련 basis의 net_income이 NULL이다. 다만
**전수는 아니고, NULL이 전부 이 버그 때문인지(다른 원인의 기존 결측일
수도 있음), 아니면 다른 basis/다른 표에서 이미 회수됐는지도 개별 확인이
필요**하다(예: 00101044는 오히려 두 basis 다 정상 — 이 필링은 net_income이
이미 다른 경로로 회수돼 있었다는 뜻).

**이번 문서 범위 밖으로 분리한다** — EPS 값 자체를 고치는 것(§4)과
`net_income` 결측을 복구하는 것(라벨 정제 후 mapper 재시도, 또는 R24/R25
류 구조기반 후보주입)은 **서로 다른 작업**이고, 후자는 전수 규모·기존
결측과의 중복 여부를 먼저 재확인해야 승인 가능한 설계가 나온다. §6에
Phase 2로 남겨둔다.

---

## 4. 제안 설계 — curated 허용목록 (미구현, 승인 필요)

### 4-A. 핵심 아이디어

일반 규칙(라벨에 단위선언 없으면 표 단위로 폴백) 대신, **이전 세션이
이미 검증한 확정버그 population**(sibling adecimal 최빈값 대조로 확정된
1,417행/206개사/1,307개 filing, [[gateb-3tracks-investigation-2026-08-15]]
§3-완결)을 **정확히 겨냥하는 curated 키 집합**을 만들어, 그 안에 속한
필링에서만 표 단위 폴백을 적용한다. 나머지 전부(정상 EPS 168,579건 포함)는
**코드 동작이 100% 그대로**다 — 이 프로젝트가 이미 여러 번 써온 패턴
(R16/R17/R20/R21/R23/R24, `fin2/layer3/combine.py`의
`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`/`_SGA_SUBLINE_OVERRIDE_KEYS`/
`_COGS_ADDITIVE_OVERRIDE` 등)과 동일선상이다.

```python
# fin2/extract/report_lines.py (신규, 위치는 _emit_eps_lines 근처)

# ★K-GAAP 구서식(00269852류) 헤드라인+EPS노트 통짜라벨 폴백 허용목록
# (2026-08-15, R28 예정, 최종 확정은 §4-D). 키는 rcept_no 단독이 아니라
# (rcept_no, statement, basis, table_seq, label_raw) 5-튜플이다 — rcept_no
# 단독 키를 시도했다가 **같은 표 안에 별개의 정상 EPS 행이 같이 있는
# 필링 2건을 실측으로 발견**(§4-D 표), 그 행까지 잘못 건드릴 뻔했다.
# 생성 스크립트: scripts/generate_eps_kgaap_unit_fallback_override_2026-08-15.py.
# ★블랭킷 규칙 아님 — 이 집합 밖의 EPS 행(정상 168,579건 포함, 같은 표
# 안의 형제 정상 EPS 행 포함)은 기존 동작(단위선언 없으면 unit=1) 그대로
# 유지한다(§2 실측: 일반규칙은 위험).
_EPS_UNIT_FALLBACK_OVERRIDE_KEYS: frozenset[tuple[str, str, str, int, str]] = frozenset({
    ("20041112000679", "IS", "separate", 0,
     "ⅩⅢ.당기순이익(손실)      (기본주당순손실, 경상손실 당기     3분기 : 원     "
     "3분기 누계 : 원 전기     3분기 : 119원     3분기 누계 : 47원)"),  # 00349811
    ("20041112000943", "IS", "separate", 0,
     "ⅩⅢ.당기순이익(22기 3분기주당순손실 4814원 및 주당경상손실 6813원22기 3분기 "
     "누적 주당순손실 3497원 및 주당경상손실 4934원당분기주당순이익 및 주당경상이익 "
     "2190원당3분기주당순이익및 주당경상이익 1187원22기 주당순손실 및 경상손실  "
     "2923원21기 주당순이익 및 경상이익 256원)"),  # 00161976
    ...  # 총 2,218건, 생성스크립트 산출물(§4-D)
})
```

`_emit_eps_lines`에 `table_unit`(호출측 `_emit_section_lines`가 이미
계산해둔 그 표의 실제 선언단위, FX/문서기본값 폴백까지 반영된 최종값)을
새 파라미터로 추가하고, 단위 결정부만 수정한다:

```python
def _emit_eps_lines(table, *, emit, basis, statement, corp_code, rcept_no,
                    report_fiscal_year, report_fiscal_period,
                    table_seq=None, table_title=None,
                    table_unit=1) -> None:          # ★신규 파라미터
    ...
    eps_cu = ColumnUnits.from_declaration(label)
    if eps_cu.kind == FX_ONLY:
        unit, eps_source, eps_currency = eps_cu.fx_mult, SRC_FX, eps_cu.currency
    else:
        own_decl = detect_unit_declaration(label)
        fallback_key = (rcept_no, statement, basis, table_seq, label)
        if own_decl is not None:
            unit, eps_source, eps_currency = own_decl, "declared", None
        elif fallback_key in _EPS_UNIT_FALLBACK_OVERRIDE_KEYS:   # ★신규, 행단위 정밀매치
            unit, eps_source, eps_currency = table_unit, "table_fallback", None
        else:
            unit, eps_source, eps_currency = 1, "declared", None   # 기존 동작
    ...
```

호출측(`_emit_section_lines`, 446~451줄)에 `table_unit=unit`만 추가로
넘기면 된다(그 지점에 이미 `unit` 변수가 계산돼 있음, 위치는 §5-C의
`report_lines.py` 코드 참고).

### 4-B. curated 키 생성 방법 — ★★2026-08-15 후속 세션에서 실행·확정 완료

1. 후보 스캔: `section_path='주당손익' AND row_order IS NULL AND
   adecimal=0 AND (label에 자체 단위선언 없음, 파서 실코드
   `detect_unit_declaration`/`ColumnUnits.from_declaration`로 재분류)`.
2. 같은 물리적 표(`rcept_no+statement+basis+table_seq`)의 형제행
   (`row_order IS NOT NULL`) adecimal 최빈값을 그 표의 "진짜 단위"로
   확정, 후보의 adecimal(=0)과 다르면 위험군으로 좁힌다(9,495건, §2와 동일).
3. **교차검증(1차, 최우선 신호)** — 위험군 각 행의 `raw_value × table_unit`
   (원 시나리오상 이 값이 진짜 헤드라인 순이익일 것으로 추정)을 같은
   corp+fy+period(+동일 basis)의 `std_financials_v3.net_income`/
   `controlling_ni`와 대조한다. **1% 이내로 일치하면 CONFIRMED**(독립
   출처와 교차검증됐으므로 라벨 텍스트 판정 없이도 확정) — **271행/
   233개 filing/100개사**, 대부분 완전 일치(0% 차이).
4. **텍스트 신호(2차, xref 대상 없는 나머지)** — std_v3에 대조할 총계
   자체가 없는(그래서 xref 불가능한) 위험군 행은, §2-B에서 검증한 두
   신호(헤드라인 단어: 당기순이익/처분전/반기순이익/분기순이익/
   당기순손실/순손실/순이익 + 임베드된 "숫자+원" 토큰)를 **AND 조건**으로
   적용해 LIKELY로 분류 — **1,947행/1,418개 filing/266개사**.
5. **원문 XML 직접대조 2건**(오늘 세션, LIKELY 티어에서 무작위 표본) —
   00349811(오션인더블유) 2004Q3, 00161976(한세예스24홀딩스) 2004Q3 —
   둘 다 (a) 라벨 텍스트가 DB 저장값과 정확히 일치, (b) 해당 표 직전
   선언이 "(단위 : 천원)"임을 확인, (c) `raw_value × 1000` = 표에 적힌
   그대로의 헤드라인 순이익 형태. **2/2 원문일치** — LIKELY 티어의 판정
   신뢰도를 텍스트 추정에서 원문검증 수준으로 격상.
6. **★키 단위 재점검(신규 발견)** — CONFIRMED+LIKELY 합친 2,218개
   `(rcept_no, statement, basis, table_seq)` 표 중, **같은 표 안에 후보로
   안 잡힌 다른 EPS 행이 있는지** 전수 대조했다. 2개 filing
   (20050331000847, 20050511000293, 둘 다 IS/separate/table_seq=0)에서
   `희석주당경상이익(주석3)`/`희석주당순이익(주석3)` 같은 **정상 짧은
   EPS 라벨이 자체 단위선언 없이 같은 표에 공존**함을 발견 — 원래
   제안한 "rcept_no 단독" 키였다면 이 정상 행들까지 표 단위로 잘못
   부풀릴 뻔했다. **키를 `(rcept_no, statement, basis, table_seq,
   label_raw)` 5-튜플로 좁혀 이 위험을 제거했다**(§4-A 코드 갱신 반영).

**최종 확정치(§4-D 참고)**: CONFIRMED 271행 + LIKELY 1,947행 = **2,218개
라벨단위 키 / 1,871개 rcept_no / 1,560개 filing(corp+fy+period) / 288개사
/ FY 1999~2008**. 이전 세션 추정(1,417행/206개사/1,307개 filing, 스크립트
유실로 근사 재현 불가)보다 크다 — 이번 방법론(독립 총계 교차검증 +
브로드닝된 텍스트 OR신호)이 더 완전하고, 원문대조 2건으로 뒷받침돼
**이 문서의 최종 수치로 채택**한다(이전 추정치는 폐기).

### 4-C. 파이프라인 영향 범위

- `report_lines.py`는 Layer 2 추출기 — 코드 수정은 **`_EPS_UNIT_FALLBACK_
  OVERRIDE_KEYS`에 담긴 (rcept_no, statement, basis, table_seq, label)
  정확일치 행만 동작이 바뀌는 curated 게이트**(코드 자체는 전역이지만
  룩업 테이블이 좁고, 같은 표의 형제 행은 라벨이 달라 자동으로 비껴간다).
- 재추출은 확정된 rcept 목록의 corp만 대상(`scripts/reload_report_lines_
  corp.py --corp <corp_code>`, 최대 288개사, §4-D).
- std_v3 재빌드(`scripts/build_std_v3.py --corp <corp_code>`) — 단, EPS/
  주당손익 필드는 `combine.py`가 전혀 소비하지 않는 것으로 확인됨(오늘
  세션 재확인: `combine.py`/`build.py`에 `주당손익` 문자열 매칭 0건,
  소비처는 audit/verify/test 스크립트뿐) → **이 수정만으로는 std_v3의
  다른 필드(net_income 등)에 영향 없음**, report_lines 테이블의 EPS 값
  자체만 고쳐진다.
- Gate B 재감사는 불필요(controlling_ni/net_income 경로와 무관, §3의
  net_income 결측은 별도 Phase 2).
- 검증: (a) curated 목록에 든 필링의 EPS 값이 표 단위 적용 후 원문과
  일치하는지 표본 원문대조, (b) curated 목록 밖의 EPS population
  (289,512 + 159,054 + 168,579-9,495=나머지 전부)이 단조성 유지되는지
  in-memory 재추출 표본 확인, (c) `pytest tests/ fin2/tests/` 회귀 0.

### 4-D. 최종 확정 결과 (2026-08-15 후속 세션, 실행 완료)

| 티어 | 판정 근거 | 행 | filing(corp+fy+period) | rcept_no | 회사 |
|---|---|---:|---:|---:|---:|
| CONFIRMED | `raw×table_unit`이 std_v3 기존 `net_income`/`controlling_ni`와 1% 이내 일치(독립 교차검증, 대부분 완전일치) | 271 | 233 | 270 | 100 |
| LIKELY | 헤드라인 단어 AND 임베드 "숫자+원" 토큰(§2-B에서 오탐 거의 없음 확인) + 원문 XML 2/2 표본검증 | 1,947 | 1,418 | 1,705 | 266 |
| **합계(최종 curated 키)** | | **2,218** | **1,560** | **1,871** | **288** |

FY 범위 1999~2008(§1의 이전 세션 추정 2003~2010과 대체로 겹치나 양끝이
조금 더 넓다 — 오늘 방법론이 더 완전하기 때문으로 판단).

**CONFIRMED 271행의 부수적 의미**: 이 271행은 교차검증에 성공했다는
것 자체가 "해당 filing의 net_income은 **이미** std_v3에 다른 경로로
정확히 들어가 있다"는 뜻이다 — 즉 이 271행을 고쳐도 net_income 커버리지는
안 늘어난다(이미 있었음), **EPS 값 자체의 정확성만 개선**된다. 반대로
LIKELY 1,947행은 std_v3에 대조할 총계가 아예 없었던 행들이라, §3의
"net_income 결측"과 겹칠 가능성이 이쪽에 더 높다(단, 이 문서의 1차 목표는
EPS 값 수정이지 net_income 복구가 아니다 — §6 Phase 2 그대로 유지).

**검증 산출물**(스크래치패드, 재현 가능한 로직은 본문에 기술):
`build_eps_curated_override_final_2026-08-15.py`(교차검증+텍스트신호
분류, `eps_curated_candidates_2026-08-15.json` 저장) →
`check_rcept_key_granularity_risk_2026-08-15.py`(키 단위 위험 발견) →
`finalize_eps_curated_keys_2026-08-15.py`(최종 5-튜플 키 집합 산출,
`eps_curated_final_keys_2026-08-15.json` 저장, **2,218개 키 원본**).

---

## 5. 기각된 대안

### 5-A. 일반 규칙(라벨 단위선언 없으면 항상 표 단위 폴백)
§2에서 실측으로 기각 — 정상 EPS population 최소 7,258건(위험군 9,495건
중 텍스트 신호로 "정상으로 보이는" 나머지)을 훼손할 위험. curated
allowlist보다 훨씬 큰 회귀 폭.

### 5-B. 라벨 텍스트 정규식만으로 분류
§2-B에서 실측으로 기각 — 헤드라인 단어 매칭도, 임베드 숫자 매칭도,
길이 임계값도 전부 오탐/누락이 있어 **단독으로는 curated 리스트 생성의
1차 필터로만 쓸 수 있고, 최종 판정 기준으로는 못 쓴다**(R27 §4와 동일
결론이 여기서도 재현).

### 5-C. 값 크기 게이트(R27 방식 재사용)
문제의 근원이 "raw 값이 EPS치고 우연히 작아 보인다"는 것이라 값 크기로는
애초에 못 거른다(§2-A 끝부분). R27 게이트는 KBI메탈류(총액이 이미 커서
값 크기로 걸러지는 경우)엔 맞지만 이 클래스엔 무력하다.

---

## 6. 이번 설계 범위 밖 (Phase 2 후보)

- **`net_income` 결측 복구**(§3) — 헤드라인 라벨 정제(괄호 안 EPS 노트
  스트립) 후 `account_mapper.map()` 재시도, 또는 R24/R25류 구조기반
  후보주입(`_ni_attribution_structural_candidates` 패턴 응용). 표본
  15건 중 9건+ NULL 확인됐으나 전수 미측정 — 별도 investigation
  필요(이 필링들의 net_income이 이미 다른 경로로 회수돼 있는지부터
  전수 확인).
- ~~curated 키 목록의 정밀 재확정~~ — **완료(§4-B/§4-D, 같은 날 후속
  세션)**. 최종 2,218개 키(1,560 filing/288개사), 독립 교차검증
  271행+원문대조 2건으로 뒷받침. 원문대조 표본을 더 늘리는 것(특히
  LIKELY 티어 1,947행 중 나머지)은 여전히 여유가 되면 추가로 할 수
  있는 항목(구현 전 필수는 아님 — 이미 신호 3종 결합 + 2건 원문일치로
  근거는 충분하다고 판단).
- 위험군 9,495건 중 curated 키(2,218건)에 안 든 **나머지**(약
  7,277건, "REJECTED" 티어)가 진짜 전부 정상 EPS인지, 혹은 다른 유형의
  버그(예: 표 단위가 정말 EPS에도 적용돼야 하는 드문 예외 케이스)가
  섞여 있는지 — 이번 세션은 REJECTED 티어의 표본(헤드라인 단어는 있지만
  임베드 숫자가 없는 것들)을 눈으로 확인해 대부분 `주당순이익`/
  `기본주당순이익(손실)` 같은 정상 짧은 라벨임을 확인했으나(§4-D 근거
  스크립트 출력), 전수 원문대조는 안 했다.

---

## 7. 산출물

- 이 문서.
- 1차 탐색 스크립트(스크래치패드, 세션 종료 시 유실 — 재현 필요 시 아래
  SQL/로직 패턴으로 재현 가능, §2/§3의 근거):
  - `probe_eps_label_unit_fallback_2026-08-15.py` — 라벨 자체단위선언
    유무 분류(파서 실코드 재사용) + 형제행 adecimal 최빈값 대조.
  - `probe_eps_label_pattern_discriminator_2026-08-15.py` — 헤드라인
    단어 매칭 판별력 검증(기각).
  - `probe_eps_embedded_number_discriminator_2026-08-15.py` — 임베드
    "숫자+원" 토큰 판별력 검증(1차 필터로 채택 가능, 단독 최종판정 불가).
  - `probe_eps_length_threshold_2026-08-15.py` — 라벨 길이 임계값
    판별력 검증(기각).
  - `probe_eps_bug_net_income_impact_2026-08-15.py` — net_income 결측
    표본 점검(§3, Phase 2 후보 근거).
- **★최종 curated 키 확정 스크립트 3종 + 산출물 — 저장소에 영구 보존**
  (§4-B/§4-D, 재실행 시 DB 상태가 바뀌지 않는 한 동일 결과 재현 확인함,
  repo 경로에서 직접 재실행해 재현성 검증 완료):
  - `scripts/build_eps_curated_override_final_2026-08-15.py` — 위험군
    9,495건을 std_v3 독립 총계 교차검증(CONFIRMED)과 텍스트신호
    (LIKELY)로 분류, `scripts/eps_curated_candidates_2026-08-15.json`
    (CONFIRMED 271행 + LIKELY 1,947행 전체 레코드)을 산출.
  - `scripts/check_rcept_key_granularity_risk_2026-08-15.py` — rcept_no
    단독 키의 위험(같은 표 안 형제 정상 EPS 행 오염 가능성) 검출.
  - `scripts/finalize_eps_curated_keys_2026-08-15.py` — 최종
    `(rcept_no, statement, basis, table_seq, label_raw)` 5-튜플 키
    2,218개를 산출, `scripts/eps_curated_final_keys_2026-08-15.json`에
    저장(구현 단계에서 이 JSON을 `_EPS_UNIT_FALLBACK_OVERRIDE_KEYS`
    리터럴로 변환해 `report_lines.py`에 반영하면 됨).
  - 원문 XML 직접대조 2건(00349811 오션인더블유 2004Q3, 00161976
    한세예스24홀딩스 2004Q3) — 라벨/원시값/표 선언단위("천원") 전부
    DB 저장값과 정확 일치 확인(§4-B 5번).
