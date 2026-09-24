# 파싱·적재 규칙 단일 관리 문서

> **이 문서의 목적.** 파싱·적재 규칙이 코드 docstring·핸드오프·메모리에 흩어져 있어,
> 새 파서를 만들 때마다 규칙을 다시 발굴하거나 **모르고 어긋나게 구현**하는 일이 반복된다.
> 이 문서가 규칙의 **단일 진입점**이다. 규칙을 새로 정하거나 바꾸면 **여기에 먼저 적고**,
> 근거가 되는 코드/문서를 링크한다.
>
> **읽는 법.** 각 규칙은 `규칙 / 근거(파일:줄 or 문서) / 어기면 생기는 일` 3단으로 적는다.
> 근거 없는 규칙은 규칙이 아니다 — "그렇게 해왔다"는 여기에 쓰지 않는다.
>
> 최종 갱신 2026-08-13.

---

## R0. ★★ 지배 원칙 — 문서를 그대로 읽는다. 없으면 넘어간다.

**규칙** — 모든 보고서(원본이든 정정본이든)를 **같은 방식으로** 읽는다.
보고서의 각 부분을 차례로 훑으면서, **있으면 파싱하고 없으면 넘어간다.**
부분이 빠진 것은 오류가 아니다 — 정상이다.

- 원본에도 없는 부분은 얼마든지 있다(연결재무제표를 안 만드는 기업 → 별도를 파싱한다).
  이걸 미스매칭으로 보지 않는다. **정정본에 부분이 없는 것도 똑같이 취급한다.**
- 정정본이 원본과 다른 점은 **하나뿐**이다: 같은 항목이 나중에 다시 나오면 **그게 이긴다.**
  판단은 표의 행 개수가 아니라 **항목의 내용**으로 한다
  (원본 손익계산서 50행 → 정정본 30행이면, 30행이 최종이 아니라 **원본 50행 중 그 30개
  항목의 값만 바뀐다**).
- 따라서 '정정본 병합'을 위한 별도 설계·별도 키 체계는 **필요 없다.** 모든 보고서를 같은
  파서로 읽고, 시간순으로 항목을 덮어쓰면 된다.

**우리가 집중할 것은 두 가지뿐이다.**

| 감시 대상 | 뜻 |
|---|---|
| **거짓 부재(false absence)** | 있는데 **없다고 잘못 판단**하는 것 |
| **오파싱(misparse)** | 있는 내용을 **틀리게 읽는** 것 |

**"보고서에 일부가 빠져서 파싱을 못 한다"는 결론은 나와선 안 된다.**

**근거** — 사용자 지침 2026-08-01. `fin2/layer3/combine.py:96`(항목 단위 덮어쓰기·미수록 항목
유지)과 `:184`(대상별 체인 워크)가 재무제표에 대해 이미 이 원칙의 구현이다.

**이 원칙으로 본 오늘의 결함들** — 전부 **거짓 부재**의 사례다:
`is_final` 필터(R2-1, 547건) · 연도 헤더행이 표를 폐기(T7, 생산표 7.9%) ·
1x1 래퍼가 캡션을 잡아먹음(T2) · `</TABLE>` 누락 시 표 0개(T1) · `△` 음수 셀 폐기(T8).

---

## 0. 규칙 색인

| # | 규칙 | 적용 계층 |
|---|---|---|
| **R0** | **★문서를 그대로 읽는다 — 있으면 파싱, 없으면 넘어감. 감시 대상 = 거짓 부재·오파싱** | **전 파싱 경로** |
| R1 | 보고서 원문 read 는 계층2 전용 | 아키텍처 |
| **R2-0** | **정정본은 문서의 부분집합 — 보고서 선택은 '대상 단위 체인 워크'** | **전 파싱 경로** |
| R2 | **정본 정책 = 최초등록본 + 순차 델타 패치** | 계층2→3 |
| R3 | 계층2 는 모든 버전을 전사한다 | 계층2 |
| R4 | 단위는 표가 아니라 **열** 단위로 판정 | 계층2 |
| R4-1 | 로컬 선언 전무 시 문서 전체 기본 단위(요약재무정보/표시통화 주석 텍스트 근거만) | 계층2 |
| R4-2 | 제목+데이터 병합 표 / 제목 자체 없는 표(위치+계정명) — title_text_owned 최후 폴백 | 계층2 |
| R5 | 헤더 의심 행을 삭제하지 않는다(header_hint) | 계층2 |
| R6 | 확정 못 하면 추측하지 않고 NULL + 원문 보존 | 전 계층 |
| R7 | 유니버스 = KOSPI/KOSDAQ 보통주, 외국기업 제외 | 수집 |
| R8 | 새 파서는 배선 2곳 + 소급 백필 + 검증 | 파이프라인 |
| R9 | 검증은 집계가 아니라 원문 대조로 | 작업방식 |
| **R10** | **XBRL 원문(instance) — `preferredLabel=negated*`면 값 부호 반전, `calc:weight`는 저장에 반영 안 함** | 계층2(XBRL) |
| **R11** | **표의 논리적 열 = 헤더·본문을 관통하는 하나의 occupied-grid(본문 행도 ROWSPAN/COLSPAN 확장), 라벨 영역 폭은 `LV′`(본문 값 유무 기반)로 판정** | 계층2(주석·SCE) |
| R12 | 발행주식수("주식의 총수 등")는 BS/IS/CF/주석 tree 밖 cross-cutting 스칼라 — 별도 계층2 테이블·별도 파싱패스 | 계층2(일반현황) |

---

## R1. 보고서 원문 read 는 계층2 전용

**규칙** — 원문 보고서 파일을 읽어 DB에 적재하는 것은 **오직 계층2**(`report_lines` /
`note_lines`)에서만 한다. 계층3(std_v3)·계층4(앱)는 보고서를 직접 읽지 않는다.
**예외 = 검증(원문 대조·감사) 목적만.**

**근거** — 사용자 지침 2026-07-25. `docs/plans/rearchitecture_4layer.md` §6.

**어기면** — 파서=충실전사 / 취합=값판단 의 4계층 분리가 무너지고, 같은 원문을 여러 계층이
제각기 해석해 값이 갈린다. 폐기된 위반 예: "계층3 가 `cf_da.py` 로 보고서를 직접 읽어 std_v3 백필".

> ✅ **위반 해소 완료(2026-08-09)**: `biz_metrics` 계열(`biz_section`·`sales_section`·
> `order_backlog`·`biz_catalog`)이 '사업의 내용' 본문표를 파일에서 직접 읽던 예외를 없앴다.
> `biz_section_tables`(도메인 컬럼 `production`/`sales`/`catalog`/`order_backlog` 4종 공용,
> `collector/models.py::BizSectionTable`)를 계층2 원본 grid 저장소로 일반화하고,
> `collector/biz_metrics.py::sync_biz_metrics_corp`·`collector/order_backlog.py::sync_order_backlog_corp`
> 를 이 테이블만 읽도록 재작성했다. 원문 파일을 여는 지점은
> `fin2/layer2/biz_raw_tables.py::ensure_biz_raw_tables`(이 필링의 raw grid 가 아직 없을 때만
> 온디맨드로 계층2 쓰기를 트리거) 하나뿐이다. 상세 = `docs/plans/biz_content_layer2_migration_2026-08-09.md`
> · `docs/plans/biz_content_layer2_migration_todo_2026-08-09.md`(Phase 0~6 전부 완료, 150개사
> 표본 전/후 diff `biz_metrics` 0건 불일치·`order_backlog` 4,666행 중 1건만 원문대조로 확인된
> 무해한 개선).

---

## R2. ★정본 정책 — 최초등록본 + 순차 델타 패치

**규칙** — 한 (기업, 연도, 기간)에 원본과 정정본이 여러 개 있을 때:

1. **베이스 = 최초등록본**(`filed_at ASC` 첫 건).
2. 이후 정정본을 **시간순으로** 훑으며, **값이 다르거나(edit) 새로 생긴(add) 셀만 덮어쓴다.**
3. 정정본이 **건드리지 않은 셀은 원본 값을 그대로 유지**한다.
4. 덮어쓴 셀은 출처를 표시한다(`amended=True` / `amended_by` / `amend_chain`).

즉 **"최신본 하나를 골라 쓰는 것이 아니다."**

**근거** — `fin2/layer3/combine.py:96` `build_merged_lines()` docstring
("★정본 정책(사용자 2026-07-22): 최초등록본 + 순차 델타 패치").
대상 선택은 `fin2/layer3/combine.py:79` `_period_filings_chrono()` — `is_final` 을 **보지 않고**
그 기간의 **모든** filing 을 시간순으로 가져온다.

**왜 이 방식인가** — 정정본은 대개 **부분 정정**이다. 특히 `[첨부정정]`·`[첨부추가]` 는 본문
XML 이 아예 없거나 일부만 있다. 최신본 하나만 쓰면 **정정이 건드리지도 않은 본문이 통째로
사라진다.** combine.py docstring 원문: *"constructed as original+deltas so partial amendments
(첨부정정 / 부분 본문정정) never drop the untouched base."*

**실측 정합** — 원본↔정정본 60쌍에서 SAME 90.9% / CHANGED 6.4% / ONLY_ORIG 1.2% / ONLY_AMEND 1.5%.
셀 동일성 키 = `(statement, basis, col_index, section_path, label_raw)`.

### R2-0. ★ 정정본은 **문서의 임의의 부분집합**이다 — 완전하다고 가정 금지

**규칙** — 보고서 선택은 **문서 단위가 아니라 추출 대상(target) 단위**로 한다.
대상마다 `is_final → … → 원본` 체인을 거슬러 올라가 **그 대상을 실제로 담고 있는 가장 최신
보고서**를 쓴다. **"나중 보고서가 더 완전하다"는 가정은 틀렸다.**

**근거(실측 2026-07-31, 원본↔정정본 123쌍)**

| 정정본의 사업의 내용 표 수 | 쌍 | 비율 |
|---|---:|---:|
| 원본의 90% 이상(사실상 전체 재제출) | 113 | 91.9% |
| 원본이 0표(비교불가) | 7 | 5.7% |
| **0표 = 해당 부분이 아예 없음** | **3** | **2.4%** |

결정적 사례 — 넥스틸 FY2024 `[첨부정정]` `20250327000660`
(https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250327000660):
문서에 **주석 218표 · (첨부)재무제표 17표 · 감사 관련 표**는 있는데
**`I. 회사의 개요`·`II. 사업의 내용`은 아예 없다.**
→ 같은 기간이라도 **주석은 이 정정본이 최신 소스이고, 사업의 내용은 원본이 최신 소스**다.

사용자 지적(2026-08-01): *"정정본에서 항상 전체 문서를 다시 내지는 않아. 회사 주소 바뀐 내용만
한 페이지로 등록하고 말아."* — 실측이 이를 확인했고, 위 넥스틸 사례는 한 페이지보다 넓은
**부분집합**이라는 더 강한 형태다.

**어기면** — ①최신본만 읽으면 그 대상이 없는 정정본을 만나 **통째로 빈다**(R2-1, 547건).
②최신본을 통째로 채택하면 그 정정본이 담지 않은 부분이 **사라진다.**

**선례** — `fin2/layer3/combine.py:184` `select_canonical_rcepts` 가 재무제표에 대해 이미
이 방식을 쓴다: *"Blindly reading only is_final would yield empty/MISSING. Walking the filing
chain (is_final → … → original) **per statement** recovers 307/321 attachment amendments."*

**어기면** — 아래 R2-1 이 실제 사례다.

### ✅ R2-1. (해결 2026-08-01) `biz_metrics` / `order_backlog` 의 is_final 필터

`collector/biz_metrics.py:30` 의 `find_annual_reports()` 는 **`AND f.is_final = TRUE`** 로
최종본 1건만 고른다. 정본 정책의 **베이스인 최초등록본을 아예 파싱하지 않는다.**

실측(2026-07-31):

| 테이블 | is_final=t rcept | is_final=f rcept |
|---|---:|---:|
| `report_lines` (FY2024) | 9,590 | **1,191** ← 모든 버전 전사(R3) |
| `biz_metrics` (전체) | 26,346 | **38** ← 사실상 최종본만 |

그 결과 **`is_final` 사업보고서인데 XML 본문이 없는 547건(447개사)** 이 통째로 건너뛰어진다.
그중 **505건(92%)** 은 같은 기업·같은 연도에 **XML 이 있는 형제 filing 이 디스크에 존재**한다.

원인 유형: `[첨부정정]` 457 · `[기재정정]` 52 · 그 외 38.
`[첨부정정]` 은 첨부만 고치므로 XML 본문이 없는데, `is_final` 플래그는 가져간다.

구체 사례 — 중앙에너비스 FY2025:

| rcept_no | 종류 | is_final | XML |
|---|---|---|---|
| 20260312000614 | 사업보고서 | f | ✅ |
| 20260730000356 | [기재정정] | f | ✅ |
| 20260730000361 | [첨부정정] | f | ❌ (PDF만) |
| **20260730000551** | **[첨부정정]** | **t** | **❌ (PDF만)** |

→ 본문이 담긴 XML 2건이 모두 `is_final=FALSE` 라 **FY2025 전체가 미파싱**.

**조치 예정** — R2 대로 `find_annual_reports` 를 "그 기간의 모든 filing 을 시간순으로" 로 바꾸고
`biz_metrics` 적재를 원본+델타로 재구성. 미착수(2026-07-31 백필 완료 후).

**조치 내용 (2026-08-01)**

| 구성요소 | 역할 |
|---|---|
| `collector/filing_select.py` | **보고서 선택 단일 지점.** 한 기간의 모든 보고서를 오래된 것부터 반환(`is_final` 미사용) |
| `collector/biz_merge.py` | 시간순 **항목 단위** 병합. 정정본이 다시 낸 항목만 덮어쓰고 나머지는 유지 |
| `collector/biz_metrics.py` | 기간 단위 파싱·병합·적재로 전환. 멱등 범위 rcept → **(corp, fiscal_year)** |
| `collector/order_backlog.py` | 동일 계약 적용(항목 동일성 = `category`) |
| `scripts/nightly_gap_fill_backfill.py`·`phase_c_rebuild.py` | is_final 필터 제거 |
| `tests/test_parsing_rules_r0.py` | **재발 방지** — 적재 모듈이 `is_final` 을 소스 필터로 쓰면 실패. 부분 정정본 병합 동작도 고정 |

**검증** — FY2025 가 통째로 비어 있던 3사가 적재됨(이전 0행):
아이엠바이오로직스 159행 · 케이엘넷 296행 · 중앙에너비스 48행.
중앙에너비스는 `20260730000356 [기재정정]` 에서 나왔다(본문 없는 `[첨부정정]` is_final 이 아니라).
`order_backlog` 오르비텍 22행 → 172행, **삭제 0(추가만)**. 회귀 118건 통과.

**전수 재적재 완료 (2026-08-01 08:21 / 08:49)**

| | 이전 | 이후 |
|---|---:|---:|
| `biz_metrics` 행 | 7,537,995 | **7,718,962** (+2.4%) |
| `biz_metrics` 출처 보고서 | ~26,346 | **38,733** |
| `order_backlog` 행 | 2,211 | **24,687** (11×) |
| `order_backlog` 기업 | 566 | **1,004** |

biz: 2,530사 · 보고서 53,653 · 표 524,007 · 오류 0.
보고서를 29% 더 읽었는데 행은 2.4%만 는 것이 정상이다 — 정정본 대부분이 원본과 같은 내용이라
병합이 접어낸다. **출처 보고서 26,346 → 38,733** 이 실제로 더 많은 판을 읽었다는 증거.

`order_backlog` 의 11배 증가는 병합 효과가 아니라, 종전 적재가 **최신 1건만** 대상이라
과거 연도가 통째로 비어 있었기 때문이다(R2-1 과 별개 결함).

### ⚠ 재적재 중 발견해 고친 것 2건

1. **병합 키가 행을 버리고 있었다(내 구현 결함).** 한 보고서 안에서 식별자가 되풀이되는 행을
   '중복' 으로 보고 버려, **구 적재 방식 대비 21.94% 유실**(일부 기간 60%↑). 재적재를 중단하고
   되풀이를 **순번으로 구분**하도록 고쳐 유실 0% 확인 후 재시작.
   → `tests/test_parsing_rules_r0.py` 에 "단일 보고서 파싱 결과가 그대로 보존되는가" 고정.
2. **`bigint` 범위 초과로 기업 전체가 실패.** 셀 병합 결함(부록 C)이 만든 천문학적 값이
   INSERT 를 터뜨려 **그 기업의 수주 데이터 전부**가 사라졌다(3사). 행을 버리지 않고
   **문제 필드만 NULL** 로 낮추도록 가드 추가 — 같은 행의 정상 값은 보존.

**★ 델타 키 실측(2026-07-31, `scripts/probe_biz_amendment_key.py`, 원본↔정정본 41쌍)**
※ 아래 측정은 '표 단위 델타' 를 검토하던 단계의 것으로, **R0 확정 후 그 설계는 폐기**됐다.
   항목 동일성은 `collector/biz_merge.py` 의 (metric, 캡션, segment, item, period_label) 로 간다.

계층3 의 셀 키를 그대로 못 쓴다 — `biz_metrics` 는 long-format 이라 대응 키를 새로 정해야 하고,
**행 단위 키는 전부 탈락**했다. 한 보고서 안에서조차 유일하지 않기 때문이다.

| 행 키 | 정렬 | **키 충돌** |
|---|---:|---:|
| metric+segment+item+period_label | 99.6% | **9,411** (SAME 6,702 보다 많음) |
| metric+segment+item+period_year | 99.6% | 14,729 |
| metric+segment+period_label | 99.9% | 14,489 |

한 보고서에 같은 `(metric, segment, item, period_label)` 을 내는 표가 여럿이라 절반 이상이
식별 불가다. 실제로 오매칭 증거도 나왔다 — 한화생명 FY2025 `ins_solvency 지급여력(A)`
3,197 → 22,901,084(서로 다른 표의 행이 같은 키로 붙음).

**표 단위 식별은 유효하다:**

| 표 키 | 양쪽 | 원본만 | 정정만 | 정렬 | 키 충돌 |
|---|---:|---:|---:|---:|---:|
| metric+캡션40자 | 513 | 0 | 1 | 99.8% | 150 |
| **metric+캡션40자+표모양** | **572** | **1** | **3** | **99.3%** | **29** |
| metric+표모양 | 518 | 1 | 3 | 99.2% | 137 |

→ **제안: 셀이 아니라 '표' 단위 델타.** 표 식별이 같으면 나중 보고서가 통째로 이기고,
정정본에 없는 표는 원본 것을 유지한다. R2 의 원칙("정정이 건드리지 않은 것은 원본 유지")을
이 데이터의 자연스러운 입자(=DART 정정은 셀이 아니라 표 단위로 다시 낸다)에 맞춘 것.
**미승인 — 사용자 확인 후 착수.**

---

## R3. 계층2 는 모든 버전을 전사한다

**규칙** — 계층2 는 `is_final` 로 거르지 않는다. 원본·정정본을 **전부** 전사한다.
버전 선택·병합 판단은 계층3(R2)의 일이다.

**근거** — 실측: `report_lines` FY2024 에 비최종본 rcept 1,191건 존재.
`collector/filing_collector.py:524` — 다운로드 태스크도 `is_final=TRUE` **에 더해 정정 그룹의
원본까지** 생성한다.

**어기면** — 계층3 가 델타 패치를 할 **베이스가 없어진다**(= R2-1 이 정확히 이 상태).

---

## R4. 단위는 표가 아니라 **열** 단위로 판정

**규칙** — 단위 판정의 근거는 두 가지뿐: ① 표의 단위 선언 토큰 ② **열 헤더 원문**.
**셀 값의 크기·소수점으로 "비율 같다"고 추론하지 않는다.** 열 헤더가 말해주지 않으면
**확정 못 함(NULL)** 으로 두고 셀 원문(`value_raw`)을 남긴다.

**근거** — F1(2026-07-31, 커밋 `681e42a`). `fin2/extract/units.py`, `fin2/extract/report_lines.py`.
메모리 `layer2-unit-column-attribution`.

**어기면** — 표의 첫 금액 배수를 전 열에 적용하던 종전 방식이 **DB 6,130,738 행을 오염**시켰다
(`이자율(%)` 열에 2,228조원). 유실은 '없는 것'이지만 오염은 **틀린 값이 들어 있는 것**이라
계층3 이 그대로 소비하면 산출이 틀어진다.

**함정 2가지(실측)** — 기간 표지를 비금액에 넣지 말 것(만기분석 '6개월이내' 칸은 천원 금액) ·
열 라벨 접두의 단위 선언은 열 성격이 아님.

**단위 상속**은 사용자 결정 D1(2026-07-31)로 좁게만 허용(`unit_source='inherited'`).

### R4-1. 문서 전체 기본 단위 (로컬 선언이 전혀 없을 때만)

**규칙** — 표에 로컬 단위 선언이 전혀 없고(그 표 자신도, `inherited_declaration_text` 도
못 찾음), FX_ONLY 도 아니면, **문서 전체 기본 단위**를 최후 수단으로 쓴다. 근거는
magnitude 추론이 아니라 문서 안 **명시 텍스트 선언 두 곳뿐**(`document_default_unit()`):

1. `요약재무정보` 섹션 데이터표의 단위 선언 — 본문과 같은 회사·같은 기간 수치가 그대로
   반복되므로 같은 단위임이 구조적으로 보장된다.
2. 회계정책 주석의 "표시통화 … 원(KRW)/원화" 문구(재무제표 작성기준 절).

`unit_source='doc_default'` 로 provenance 를 남긴다.

**엘브이엠씨(R4 위 문단)와 다른 점** — 그 사고는 **다른 표의 선언을 statement 경계 너머로
넘겨받는** 패턴이었다(로컬에 아무 선언이 없다고 남의 표 단위를 주움). 이건 **어느 표도
아무것도 선언하지 않았을 때 문서 공통 선언을 쓰는** 패턴이라 다르다 — 그 표 자신에게
이미 통화 선언이 있으면(FX_ONLY 등) 여기까지 오지 않는다.

**근거** — 2026-08-05, 08-04/08-05 잔여공백 24건 재분해 중 발견. '재무제표_직접작성'
수기입력 서식(이엘피 20160330001530·20160513002038·인카금융서비스 20170516000038·
윙스풋 20210517000207)이 본문 표에 단위를 아예 재선언하지 않아 4건 전량이 "단위 미선언"
으로 스킵되고 있었다. `fin2/extract/text.py::document_default_unit()`,
`fin2/extract/report_lines.py::SRC_DOC_DEFAULT`.

**영향 범위 실측(2026-08-05)** — 활성기업 `status=done, n_lines=0` 398건 전수 재검사:
이번 규칙으로 해결된 건 **정확히 4건**(이미 반영), 나머지 397건은 본문 섹션 자체가
감지 안 되는 **별개 원인**이라 무관. 광범위한 소급 백필은 불필요.

**어기면(적용 안 하면)** — 요약재무정보·회계정책 주석에 명시적으로 원(KRW) 이라고 써
있는데도 본문 표를 통째로 스킵해 R0("있으면 파싱한다")를 어기게 된다.

**해결된 카운터 사례 — 특수건설 20151116001903** — 같은 "재무제표_직접작성" 서식이지만
①BS·IS 는 제목+데이터가 **한 TABLE 에 병합**돼 있어 `title_text_owned` 가 제목을 못 찾고
분류 자체가 실패한다(단위 문제 이전에 표 분류 결함) ②요약재무정보 섹션이 비어있고(분기
보고서 플레이스홀더) 회계정책 주석도 없어(분기라 생략) `document_default_unit()` 도
근거를 못 찾는다. **당시엔 이 규칙 밖의 별도 결함이었으나, R4-2(아래)로 해결됐다** —
①은 표 자신의 첫 행에서 제목을 읽고, ②는 사실 표 안쪽(제목 다음 몇 행)에 로컬 단위
선언이 있었다(분류가 막혀 그 지점까지 못 가서 못 찾았을 뿐).

---

## R4-2. 제목+데이터 병합 표 / 제목 자체가 없는 표

**규칙** — `title_text_owned`/`title_text_for_classify`(직전 형제 기반)가 **둘 다** 제목을
못 찾았을 때만 시도하는 최후 폴백 3종. 근거는 이번에도 magnitude 추론이 아니라 표 자신의
**구조 사실**뿐이다:

1. **병합표** (`owned_merged_title`) — 표 자신의 첫 행이 재무제표명 하나뿐이면(제목·기간·
   회사명·단위·헤더·데이터가 전부 한 TABLE 안에 있는 "재무제표_직접작성" 수기입력 서식)
   그 statement 로 확정한다. 단위도 같은 표 안(헤더행 이전 메타행)에 있을 수 있어
   `merged_table_local_unit()` 로 함께 찾는다(못 찾으면 R4-1 doc_default 로 넘어간다).
   **반드시 `table_has_amount_rows(tbl)` 가 참인 표에만** 적용한다 — 아니면 표제/데이터표
   분리 서식의 순수 제목표에도 걸려 다음 idx 의 정상 분류와 **중복 append** 된다(그 서식이
   압도적 다수라 위험이 광범위하다).
2. **위치+계정명 규칙** (`titleless_bs_start`) — 표 안 어디에도 제목 문구가 전혀 없어도,
   그 표가 `2.연결재무제표`/`4.재무제표` 섹션의 **첫 번째 금액표**이고, 헤더행이 곧바로
   "과목"/"계정명"으로 시작하며, 헤더 다음 첫 계정명이 **"자산"** 이면 BS 로 확정한다.
   단위는 표 안에 없으므로 R4-1 doc_default 로 확보한다.
3. **헤더 재등장 분리** (`_split_headed_multi_statement_table`) — 위 둘도 실패했고, 그 표가
   섹션의 **첫 번째 금액표**인데 표 **안**에서 헤더행("과목"류)이 2회 이상 나타나면(복수
   재무제표가 한 물리적 TABLE 에 이어붙은 서식), 헤더 재등장 지점으로 표를 구간별로 잘라
   각 구간을 **내용**(행 라벨)만으로 BS(`_looks_like_balance_sheet`)→
   IS(`_looks_like_income_statement`)→CF(`_looks_like_cashflow`) 순으로 판별한다. 구간이
   2개 미만이거나 어느 구간이든 판별 실패·같은 statement 중복이면 **전체 보류**(부분 성공
   불허). 단위는 표 안에 없으므로 R4-1 doc_default 로 확보(②와 동일 근거).

`unit_source` 는 기존 값을 그대로 쓴다(로컬 발견 시 `declared`, doc_default 위임 시
`doc_default`) — 새 provenance 값을 만들지 않는다.

**근거** — 2026-08-05, 특수건설 census 다음 후보로 실행. 활성기업 `n_lines=0` 398건
census 결과 §1 패턴 정확히 3건(특수건설 20151116001903·팬엔터테인먼트 20181114002948·
포시에스 20171114002836 IS), §2 패턴 정확히 1건(포시에스 BS, 연결+별도 2표) — 다른
기업 오적용 **0건**. `fin2/extract/statement_titles.py::owned_merged_title/
titleless_bs_start`, `fin2/extract/text.py::merged_table_local_unit`,
`docs/plans/merged_title_data_table_r4-2_2026-08-05.md`.
③은 2026-08-07, R4-2 잔여 백로그("표못잡음(헤딩섹션은 있음)") 착수 census 재실행 중 발견.
`n_loaded=0`(활성기업, 2015+) 모집단 안에서 "섹션 있는데 표 못 잡음" 3건을 재확인한 결과
이노시뮬레이션(2018FY `20190405000147`·2019FY `20200330004128`) 2건이 이 패턴, 자비스
2018Q3(`20181114001626`)는 원문 XML 자체에 상세표가 없는 별개 문제(파서로 해결 불가, 보류)
로 갈렸다. 재census로 "헤더 재등장" 신호를 가진 필링이 이 2건이 전수임을 확인 — 다른 기업
오적용 **0건**. `fin2/extract/text.py::_split_headed_multi_statement_table/
_build_synthetic_table/_looks_like_cashflow`.

**함정(실측)** —
- 병합표 폴백을 `table_has_amount_rows` 가드 없이 걸면 표제/데이터표 분리 서식(다수)의
  제목표에도 반응해 데이터가 중복 적재된다.
- 위치+계정명 규칙의 헤더 셀이 `ROWSPAN=2` 면 다음 행 첫 TD 가 날짜값으로 밀린다 —
  기간/날짜 패턴이면 계정명 행이 아니라고 건너뛰어야 한다(안 그러면 날짜를 "자산"과
  비교해 판정이 실패한다).
- 팬엔터테인먼트는 BS 대차합계를 "부채자본총계"(표준 "부채와자본총계"와 다른 순서)로만
  쓰는데, 이게 `_looks_like_appropriation`(처분계산서 배제 가드)의 "진짜 재무제표 확정
  라벨" 목록에 없어 BS 안의 "미처분이익잉여금"(정상 자본 세부항목) 때문에 처분계산서로
  오판됐다 — `_REAL_STMT_ROW_RE` 에 "부채자본총계"·"자본과부채총계" 추가로 해결.
- 요약재무정보 섹션 안에서 단위 선언 표와 데이터 표가 **붙어있지 않을 수 있다**(포시에스:
  단위선언 표 → 연결범위 표(무관) → 데이터 표 순서). `document_default_unit()` 이 데이터
  표의 직전 형제만 보던 것을, 섹션 안 "가장 최근 본 단위 선언"을 기억해두는 방식으로 확장.

**어기면** — 표에 제목·단위가 명시돼 있는데(포시에스는 요약재무정보에, 나머지는 표 안에)
분류 실패 하나로 본문 전체가 스킵돼 R0(있으면 파싱한다)를 어기게 된다.

---

## R5. 헤더 의심 행을 삭제하지 않는다 (header_hint)

**규칙** — 계층2 는 헤더로 의심되는 행을 **삭제하지 않고**, 어느 규칙에 걸렸는지를
`header_hint` 에 전사한다. 판단은 계층3 이 한다. 계층3 소비자는 기본 `header_hint IS NULL` 로 거른다.

**근거** — F2(2026-07-31, 커밋 `14cd8e7`). `fin2/layer3/combine.py:134` 가드.

**어기면** — 행이 기간축인 주석 표에서 '당기말'·'전기초' 는 열 헤더가 아니라 **데이터 행 라벨**인데,
"항상 열 헤더" 가정이 그 행 금액을 통째로 지웠다(정방향 미도달 셀의 95%).

**★ 배선 규칙** — 계층3 가드는 **반드시 같은 커밋에**. 가드 없이 계층2만 바꾸면 D&A 합산이 오염된다.

---

## R6. 확정 못 하면 추측하지 않는다

**규칙** — 후보가 여럿이면 **고르지 않는다.** 값이 갈리면 판정 불가 → 보류(NULL) + 원문 보존.

**근거** — `fin2/extract/rd_note.py` ("후보가 여럿이면 **고르지 않는다**(추측 금지)"),
`fin2/standardize/calendar.py` (flow = ΣCQ, "하나라도 None → None, 추정 금지"),
R4 의 NULL 규약.

**어기면** — 유실은 복구 가능하지만 오염은 조용히 하류로 퍼진다(R4 사례).

---

## R7. 유니버스

**규칙** — 현재 시점 KOSPI/KOSDAQ 상장 **보통주**, 개인이 거래 가능한 기업.
**국내 상장 외국기업 제외** — 식별 = `stock_code` 가 **'9' 로 시작**(900xxx 직상장·950xxx DR/원주).

**근거** — `CLAUDE.md` 개발 목표. 사용자 결정 2026-07-19.
`collector/corp_collector.py:_is_foreign_stock()` — sync 후보 필터 양쪽 브랜치에 적용.

**어기면** — 서식이 이질적이라 파싱 정합이 낮다(로스웰 73%). 기업리스트 갱신 때마다 재유입된다.

---

## R8. 새 파서/로더 추가 3층 (자동 반영 안 됨)

**규칙** — 파싱·적재를 새로 추가하면 **자동으로 전부 반영되지 않는다.** 세 가지를 각각 챙긴다.

1. **데일리 배선** — `scripts/collect_new.py` 의 **두 call site**(메인 + 재개 경로) 모두.
2. **소급 백필** — 과거분은 자동 재파싱되지 않는다. 별도 전수 실행.
3. **검증** — 회귀 테스트 + 원문 대조 + 기존 게이트 무영향.

**근거** — `docs/runbook_new_parser_pipeline_integration.md`(체크리스트 A/B/C), `CLAUDE.md`.

**자주 잊는 것** — 두 call site 모두 배선 / 소급 백필은 수동 /
**재개 플래그가 신규 항목을 못 본다**(예: `--skip-existing` 은 테이블 존재만 보므로 신규 metric
백필에 쓰면 전 기업이 스킵된다 → `--skip-catalog-existing` 신설).

---

## R9. 검증은 집계가 아니라 원문 대조로

**규칙** — 지표가 이상하면 **개별 사례를 원문까지 따라간다.** 집계로 끝내지 않는다.
휴리스틱 신호를 만들 때는 **거짓양성 모드를 먼저 의심**하고, 가능하면 휴리스틱 대신
**실제 코드 경로를 계측**한다. 판단이 안 서면 혼자 결론내지 말고
**DART 링크 + 문제 부분**을 사용자에게 제시한다 (`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<rcept_no>`).

**근거** — 메모리 `feedback-verify-against-source`. 2026-07-29 세션에서 원문 텍스트 휴리스틱으로
**거짓양성 5연속**(38.8%→27.2%→9.4%→21.9%→실제 0%).

**대전제** — **V2 는 정답이 아니다. DART 원문이 기준이다.**

---

## R10. XBRL 원문(instance) — 값 부호는 `preferredLabel`이 결정, `calc:weight`는 저장에 안 씀

**규칙** — DART 표준 XBRL instance(`/pdf/download/ifrs.do` zip, `parser/xbrl_instance/`,
`fin2/extract/report_lines_xbrl.py`)에서 presentation 위치별로 저장할 값의 **부호**를 정하는
신호는 두 가지가 있고, 서로 다른 역할이다 — **섞어 쓰면 틀린다.**

1. **`preferredLabel`이 "negated\*" 계열**(`http://www.xbrl.org/2009/role/negatedLabel` /
   `negatedTerseLabel` / `negatedTotalLabel` / `negatedNetLabel` 등)이면, 그 presentation
   위치에서 raw fact 값에 **-1을 곱해서 저장한다.** 이게 DART 자체 웹뷰어가 사람에게 보여주는
   화면과 부호를 맞추는 유일한 메커니즘이다.
2. **`calc:weight`(calculation linkbase)는 저장값에 절대 반영하지 않는다** — 이건 "부모 =
   Σ(weight×자식)" 항등식을 **검증**할 때만 쓰는 메타데이터다. fact 자체의 저장값은
   `preferredLabel` 반영 후에는 weight 없이 단순합만으로 항등식이 성립해야 정상이다.

**근거** — 2026-08-06, Phase 6-2(`docs/plans/xbrl_instance_parser_todo_2026-08-05.md`)
박셀바이오 CF를 DART 웹뷰어(`/report/viewer.do`)와 셀 단위로 대조하다 발견. `_pre.xml`에서
두 계정(`법인세환급(납부)`/`2. 재무활동으로 인한 현금 유출액`) 모두
`preferredLabel=".../negatedTerseLabel"`이 걸려 있었다. `fin2/extract/report_lines_xbrl.py::
_value_sign()`. Phase 6-5에서 박셀바이오·한화(모던 vintage) 전체 basis에 대해 BS/CF/IS/SCE
4종 항등식을 전수 재검증(불일치 0건)해 이 수정이 일반화됨을 확인.

**어기면** — raw XBRL fact 값을 그대로 저장하면 DART 웹뷰어와 부호가 반대로 들어간다(실측:
`법인세환급(납부)` 저장 -94,664,880 vs DART 화면 +94,664,880; `2. 재무활동으로 인한 현금
유출액` 저장 +347,076,273 vs DART 화면 -347,076,273). 이 프로젝트의 "표시된 그대로 저장한다"
원칙(R0·[[layer2-unit-column-attribution]] 계열)이 XBRL 소스에서만 조용히 깨진다 — HTML
소스(계층2 본류)에선 해당 없는, XBRL instance 고유의 함정이다.

**★기존에 틀렸던 결론** — Phase 0 §11/Phase 3-5는 "저장값은 weight 미반영 원문 그대로가
맞고, weight는 항등식 검증에만 쓴다"고 결론 냈는데, 이는 BS만 검증했을 때는 우연히 맞았을
뿐이고 **CF의 negated-label 케이스에서 틀렸음이 드러났다.** `calc:weight`와
`preferredLabel=negated*`는 서로 다른 메커니즘인데 후자를 놓쳤던 것 — 새 XBRL 파서를 만들 때
이 둘을 같은 것으로 착각하지 말 것.

**XBRL instance 파싱의 나머지 확정 설계(요약, 상세는 링크)** — Phase 0(실측)·Phase 3(구현)이
확정한 것: 다운로드는 1회 GET(`_fetch_pdf`류 2단계 확인 불필요) · basis(연결/별도)는 context의
`dims`가 **정확히 1개**(basis 축만)일 때만 채택 · fact 추출은 반드시 role별 presentation
트리를 먼저 워크한 뒤 그 트리에 실제로 걸린 (element, context) 쌍만 채택(같은 QName이 주석에도
반복 태깅되므로 tag명 단독 검색 금지) · role→statement 매핑은 roleURI 숫자코드가 아니라
`.xsd`의 `link:definition` 한글 텍스트로(버전에 안 변함) · label은 `preferredLabel` 우선 →
표준 `label` → en 폴백 · `order`는 float로 정렬(정수 아님). 전체 근거·실측 수치는
`docs/plans/xbrl_instance_parser_todo_2026-08-05.md`의 "Phase 0 결과"·"Phase 3 설계에 주는
결론" 절.

---

## R11. ★표의 논리적 열 = 헤더·본문을 관통하는 하나의 occupied-grid (본문 행도 ROWSPAN/COLSPAN 확장)

**규칙** — 표의 열 위치는 물리적 `<TD>` 등장 순서가 아니라, 헤더부터 본문까지 이어지는
**하나의 (row,col) occupied-grid**로 정한다. ROWSPAN 이어짐 행·COLSPAN 병합 라벨 행마다
물리적 셀 개수가 논리적 열 개수보다 줄어드는데, "물리적 위치 = 열 인덱스"로 가정하면
그 이후 같은 행의 모든 값이 왼쪽으로 밀려 엉뚱한 열에 저장된다.

라벨 영역의 폭(`L` = `offset`)은 **헤더 구조가 아니라 본문 값의 유무로 정한다** (`LV′`) —
그리드 열 중 "본문 전체를 통틀어 파싱 가능한 금액 또는 `-`/공란 placeholder 가 **한 번도**
나온 적 없는" 선행 열까지가 라벨 영역이다. 헤더 구조 신호(세로로 관통하는 셀·최하단 헤더
행 등)만으로는 판정할 수 없다 — 실측 표의 41.8%가 헤더 행이 1개뿐이라 그런 구조 신호
자체가 없다.

**근거** — 2026-08-07, `docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md`
(§8~§11, 원문→DB 끝단 대조로 확정) · `docs/plans/note_span_fix_plan_2026-08-07.md` Phase 1
(T1.1, 156→800필링·123,475표 재검증으로 `LV′` 확정, 헤더 구조 기반 후보 3종은 11~44%대
정확도로 전부 폐기). `parser/xml/table_extractor.py::_get_cells`(330줄)/`extract_rows`
(253줄)는 물리적 위치만 보고, 헤더 쪽 `fin2/extract/report_lines.py::_build_col_labels`
(500~512줄)만 그리드를 복원하는 **비대칭**이 근본 원인.

**실측 사례** — 텔코웨어 `20240814002630`: `<TD ROWSPAN=6>유동</TD>`가 이어지는 행에서
전기말 값 470,100이 `당반기말` 라벨로 저장됐다. 유진증권 `20220316000791`:
`<TD COLSPAN=2>구분</TD>` 라벨 행 때문에 현재 코드는 `offset=1`(오답)을 쓰는데
`LV′=2`가 원문상 정답이다.

**어기면** — note_lines 값의 11.48%(2,819만 개)가 잘못된 열에 귀속되고 필링의 99.0%가
영향권이다(원문 전수 재파싱 실측). 이 중 0.24%는 값 자체가 무의미해지고(비금액 열
배수를 그대로 먹임), 나머지 89.6%는 크기는 맞고 열 정체(당기/전기 등)만 틀려 계층3의
기간 판정(`note_periods`)·배수 판정(`units.py`)이 어긋난다. SCE(자본변동표)는 더 심하다
(값 슬롯의 25.56%).

**적용 범위** — 주석(note_lines)·SCE 한정. 본문(BS/IS/CF)은 코드 경로가 달라(`extract_rows
(keep_all_amount_cells=False)` → `_split_label_amounts`가 비숫자 셀을 걷어내고 금액을
왼쪽으로 당겨 ROWSPAN 이어짐이 자동 흡수됨) 실측 영향 **0건**
(`docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md` §10, 250필링·1,867표·
145,045값 동치성 검사) — **본문 경로는 건드리지 않는다.**

**상태(2026-08-08) — ★코드 구현 + 검증 + DB 반영(Phase 1~4) 전부 완료.** `parser/xml/
table_extractor.py::expand_table_grid`(그리드 확장 유틸) 신설 + `fin2/extract/report_lines.py
::_grid_header_split`/`_grid_body_rows` 배선(주석·SCE 공용). 전수 재검증(`scripts/census_
note_span_misattribution_mp.py`, 101,327건, 오류 0): 프로덕션 코드 실측 결함 **0건**(원래
28,189,281개→0). 회귀 테스트 434 passed. **note_lines 전량 재적재 완료**(245,452,947 →
247,244,387행, +0.73%) + **std_v3 재빌드 완료**(184,298→184,580행) + 재검증(DB 직접
대조·Gate B `line_value_diff=0`·D&A DB 재확인) 전부 통과 — 상세는 부록 C·
`docs/plans/note_span_fix_plan_2026-08-07.md` Phase 4.

### R11-1. 헤더 경계 판정이 실패하는 경우 (★T3.6에서 발견한 R11 자체 회귀, 2026-08-08 수정)

`_grid_header_split`이 헤더/본문 경계(`n_header`)를 못 찾으면 라벨 영역 폭(`offset`)을
구할 수 없어 값 열이 밀리는 문제가 R11 구현 자체에서 새로 생겼었다(수정 전: note 값 셀
348,099개/1,629필링 영향, 전량 재적재 전 발견해 원문 백필 없이 코드만으로 해소). 판정
실패는 세 형태:

1. **첫 행이 데이터처럼 보임** — 헤더 셀이 콤마 없는 연도("2020")뿐이면 `_NUMBER_PATTERN`이
   숫자로 오인해 헤더가 아니라고 판정. → 첫 행을 헤더로 강제(`n_header=1`).
2. **끝까지 한 번도 안 깨짐** — 데이터가 전부 "-1,339"식 **선행 마이너스**라 정규식이 숫자로
   못 잡음(괄호식 "(1,339)"만 인식). → 마찬가지로 첫 행을 헤더로 강제.
3. **표에 물리 행이 1개뿐** — 위 강제조차 못 한다(본문이 안 남음). 이 경우는 진짜로 헤더가
   없는 표다(아래 R11-2). → 그 행 자신을 본문으로 보고 LV′ 를 그대로 적용(라벨 영역 폭은
   구해지지만 헤더 텍스트가 없으니 `col_label`은 못 채운다 — 원문에 없는 정보라 정상).

### R11-2. 헤더 없는 단일행 주석 표 — 값은 "보고일 현재"로 해석

DART 주석은 "라벨: 값" 한 쌍짜리 사실을 **표 하나에 헤더 없이** 그냥 찍는 관행이 흔하다 —
"1. 연결실체의 개요"류(회사설립일자·주요사업소재지·**납입자본금**·최대주주지분율 등)나
IFRS 필수 단일공시(확정기여제도 퇴직급여비용 등)가 전형적이다. 실측(현대위아
`20240320001675`·DL이앤씨 `20240328001465`·에스디바이오센서 `20260514000917`·현대오토에버
`20241114001111`): 계정명(`label_raw`)과 값은 **처음부터 정상 추출**되고(표 자체는 정상
파싱됨, tree 구조 문제 아님), 없는 건 오직 "이 값이 어느 기간 값인가"를 설명하는
`col_label`뿐 — 원문 자체에 그 설명이 없으니 채울 수 없는 게 정상이다.

**해석 규칙(사용자 결정, 2026-08-08)**: 이런 표의 값은 헤더가 없어도 **보고일 현재
값**으로 해석한다(`context_fiscal_year`는 R11 설계상 주석 열엔 원래 안 채우므로 — 위
문단 참고 — 이 규칙은 저장 스키마를 바꾸는 게 아니라 **소비 시점의 해석 관례**다).

---

## R12. 발행주식수("주식의 총수 등") — 계층2 cross-cutting 스칼라 전사

발행주식수는 사업/반기/분기보고서의 **일반현황** 절에 있고, BS/IS/CF/주석의 계정×기간
tree(`report_lines`/`note_lines`)와 구조가 근본적으로 다르다(계정과목이 아니라 corp×시점
스칼라값 — `stock_prices`와 같은 성격). 그래서 tree에 억지로 끼워 넣지 않고 **별도
계층2 테이블**(`report_shares_outstanding`, `collector/models.py::ReportSharesOutstanding`)
로 둔다.

**파싱**(`fin2/extract/shares.py::extract_issued_common_shares_detailed`): 문서에서
"주식의 총수" 문자열이 나오는 자리마다(목차 포함) 뒤따르는 최대 3개 `<TABLE>`을 훑어
Ⅳ "발행주식의 총수" 행을 우선 채택, 없으면 Ⅱ "현재까지 발행한 주식의 총수"로 폴백. 각
행의 첫 숫자 컬럼(보통주)을 값으로 삼는다. 물리적 상한(10^11, KOSPI 최다주식 삼성전자의
10배 초과)을 넘으면 단위 오인·셀 병합 등 파싱 오류로 보고 채택하지 않는다(R6).

**적재 파이프라인**(`fin2/extract/shares_transcribe.py`): `report_lines`(lxml tree)와
파싱 방식이 근본적으로 달라(raw-text 정규식 스캔) 같은 파싱결과를 공유할 수 없다 — 그래서
`collector/note_lines_sync.py`(본문/주석 전사)와 **별도의 독립 패스**로 둔다(파일을
다시 열지만, 작은 XML이라 비용이 낮고 실패격리가 더 안전하다는 판단, 2026-08-09). Grain =
filing(rcept_no) 단위, `store_report_shares`가 rcept 단위 delete-then-insert(R2/R3와
동일 관례). `as_of_date`는 원문의 "기준일" 문구를 별도 추출하지 않고 **그 filing 의
`filings.period_end_date`로 근사**한다(발행주식수는 보고서가 다루는 회계기간 말 현재
수치를 신고하는 것이 통상 관행이라는 가정 — 실제 기준일과 다를 수 있음을 명시).

**정본선택(계층3, `fin2/layer3/build.py::_select_shares_out`)**: 같은 (corp, fy, period)를
여러 filing이 다른 시점 값으로 보고할 수 있다. ① 그 기간의 재무제표 정본 filing(`src` —
BS>IS>CF 우선순위, `_period_end`와 동일 우선순위 재사용)과 **같은 rcept**의 값을 우선한다
(provenance 일관성). ② 없으면 그 corp+fy+period를 보고한 아무 filing 중 **rcept_no
최대(최신 정정 우선)**로 폴백. 계층3는 이 테이블만 읽고 원문을 직접 read하지 않는다(R1
준수).

실측(2026-08-09 전량 백필): 대상 filing 101,489건 중 95,862건(94.5%) 추출 성공. 나머지는
원문에 섹션 자체가 없거나 3-TABLE 탐색 창을 벗어난 케이스로 추정 — R0 원칙대로 짐작 없이
NULL 유지.

---

## R13. pre-2015(K-GAAP 구서식) 계층2 전사 — 연도 라우팅 신규 모듈, 2015+ 경로 무변경

2015년 이후(현행 서식)와 1999~2014(K-GAAP 구서식)는 XML 골격은 같은 계열(`SECTION-1`/
`SECTION-2`/`TITLE`)이지만 **섹션 계층(의미 구조)이 다르다** — 연결/별도 구분이 리프
`TITLE` 텍스트가 아니라 상위 헤딩 계층에 있고, 2011년부터는 `TITLE` 자체가 소멸해
평문·인라인 `<SPAN>` 텍스트로만 표제가 존재한다(세대가 최소 3종 이상 섞여 있음, 태그
구조만으론 통일된 규칙을 못 만듦).

**규칙**:
- 기존 2015+ 소비 경로(`assign_tables_to_dart_sections`/`iter_section_elements`/
  `_detect_body_statement_tables`/`classify_statement_in_body_section`/
  `classify_legacy_statement_heading`)는 **한 줄도 안 건드린다** — 신규 모듈
  `fin2/extract/legacy_pre2015.py`(`iter_section_span_depth_aware`·
  `classify_pre2015_statement_heading`·`detect_pre2015_body_statement_tables`)로 격리.
- 라우팅은 `fin2/extract/report_lines.py::extract_report_lines`가
  `report_fiscal_year<=2010`일 때만 신규 경로를 시도하고, **섹션코드(BS_C/IS_S 등) 단위로
  병합**한다(문서 단위 all-or-nothing 폴백은 손해로 확인돼 교체 — 신규 경로가 IS/CF는
  잡는데 BS는 못 잡는 2009~2010 전환기 문서에서, "그룹이 안 비었다"는 이유로 기존 경로의
  BS 탐지 기회를 통째로 버리는 문제).
- basis(연결/별도)는 표제 문구의 '연결' 접두가 아니라 **순회 중인 섹션 자체**
  (`SEC_SEP_FS`/`SEC_CONSOL_FS`)를 권위로 삼는다 — 2015+ 주경로와 같은 원칙(R1과 정합).
  접두 없는 표제가 실제로 존재하는지 끝내 확인 못 했기 때문에(표제 기반 판정을 신뢰하면
  별도/연결이 뒤섞일 위험) 더 보수적인 쪽을 택함.
- K-GAAP 전용 표(이익잉여금처분계산서/결손금처리계산서)는 신규 `statement` 코드
  `APPR_C`/`APPR_S`로 전사(DB 마이그레이션 불요, `statement` 컬럼 CHECK 제약 없음 실측
  확인). `table_extractor.py`/`declared_unit` 단위판정은 수정 없이 전량 재사용(프로토타입
  검증 완료).
- **데일리 배선(R8)**: `collector/note_lines_sync.py`의 `FY_MIN`(대상 필터 하한)을
  2015→**1999**로 낮췄다(2026-08-11) — `extract_report_lines()`는 이미 pre-2015를
  처리하는데 이 모듈이 여전히 `fiscal_year>=2015`로 걸러 데일리 경로(`scripts/
  collect_new.py`의 두 call site, `_sync_layer2_lines`)가 pre-2015를 영영 못 보는
  상태였다. 실측 확인: KG케미칼(00101220) rcept `20120330001058`의 `report_lines`를
  지우고 옛 기본값(2015)으로 `sync_layer2_lines`를 호출하니 0행(갭 재현), 수정 후
  기본값(1999)으로는 696행 정상 복원. 향후 corp 재상장·기재정정 등으로 pre-2015 구간이
  재수집되는 경우를 대비.

**소급 백필(R8 2번)**: `scripts/load_report_lines.py`에 `--fy-min`/`--fy-max`/
`--active-only` 신설, 79,628건 신규 전량백필(오류0, 5.32시간, 2026-08-10~11) — 상세는
`docs/plans/pre2015_layer2_backfill_todo_2026-08-10.md` Phase5.

**검증(R8 3번)**: 회귀 테스트 12건(`fin2/tests/test_pre2015_legacy_layout.py`) +
`pytest tests/ fin2/tests/` 전체 통과 + Gate B 무영향(`face_audit.py`는 독립된
`_TEXT_SECTION_META`를 써서 확장된 `SECTION_CODE_OF`/`_SECTION_META`를 참조 안 함).
전량 백필 후 BS 항등식(자산=부채+자본) 전수검사 98.8% 성립(52,343건 표본).

**근거**: `docs/plans/pre2015_layer2_backfill_plan_2026-08-10.md`(설계) ·
`docs/plans/pre2015_layer2_backfill_phase2_design_2026-08-10.md`(Phase2 결정) ·
`docs/qa/pre2015_phase3_canary_verify_2026-08-10.md`(구현 검증) ·
`docs/qa/pre2015_phase4_pilot_verify_2026-08-10.md`(파일럿+버그수정) · T20(부록A).

---

## R14. XBRL 원문(instance) 구형 IFRS taxonomy(2010~2013 계열) 확장 — namespace/외부BFS/라벨/누락총계

2015~2019년 필링 다수가 신형(`ifrs-full`, 2019-10-01+)이 아니라 **구형 IFRS taxonomy**
(접두 `ifrs`, `xbrl.iasb.org` 도메인, 2010-04-30~2013-03-31 계열)를 쓰는데, R10이 만든
`report_lines_xbrl.py`가 `ifrs-full` 리터럴 접두만 인식해 이 필링들이 조용히
`report_lines` 0행으로 스킵되고 있었다(카테고리② 1,551건, `pdf_only_parser_
phase2_design_2026-08-12.md` §A). 독립된 버그 여러 개가 겹쳐 있었다:

**규칙**:
- **네임스페이스**: 리터럴 `nsmap.get("ifrs-full")` 대신 `_resolve_ifrs_namespace()`가
  URI 패턴(`iasb.org/taxonomy` 또는 `ifrs.org/taxonomy`)으로 접두를 찾는다 — `ifrs-full`
  이 있으면 그걸 우선(기존 동작 무변경), 없을 때만 패턴 매치로 확장.
- **외부 taxonomy BFS 우선순위**(`external_taxonomy.py::dart_first()`): dart.fss.or.kr
  URL 안에서도 `rol_dart_`/`rol_dart-added_`/`dart_`/`dart-gcd_` 파일명 패턴을 최우선
  정렬 — 구형 vintage는 DART 자체 role/label 정의 파일이 import 순서상 맨 끝(~47개 중
  46-47번째)이라, 파일명 우선순위 없이는 예산(`_EXTERNAL_FETCH_BUDGET`, 12→20)을 다
  써도 못 찾는다.
- **라벨 linkbase 해석**(`taxonomy_linkbase.py::resolve_external_labels()`): "labelLinkbaseRef가
  하나라도 있는 첫 파일에서 멈춘다"는 옛 가정이 깨지는 vintage가 있다(2013-03-31
  — entry point 자신이 협소한 보충 라벨파일을 직접 선언하면서 **동시에** 진짜
  종합 라벨파일(`lab_ifrs-ko_2010-04-30.xml` 등)을 가진 형제 스키마도 import함 —
  옛 코드는 첫 파일에서 멈춰 형제 스키마까지 못 감). 이제 예산 내에서 도달 가능한
  전체 import 그래프를 계속 훑어 발견한 labelLinkbaseRef를 전부 병합한다(budget 8→15).
- **BS/IS 누락 총계 fact-레벨 보조규칙**(`report_lines_xbrl.py::_emit_missing_totals()`):
  일부 vintage의 `_pre.xml`은 BS Assets/Liabilities/Equity, IS ProfitLoss/
  ComprehensiveIncome을 tree 노드로 아예 안 싣는다(분리된 root 그룹들의 flat forest —
  실측: BS 89~97%, IS 75.7~77.6%가 "fact는 있는데 tree에 없음"). 트리에 없을 때만,
  단일축 basis fact가 존재하면 그대로 옮긴다(존재 안 하면 조용히 skip — 지어내지
  않음). 위치 컬럼 규약: `node_role='P'`(계층3 "집계행 후보" 규칙 충족 —
  `node_role='P' OR (node_role='S' AND value_won IS NOT NULL)`, `collector/models.py`
  참고) / `section_path=NULL`(`combine.py::_depth()`가 depth=0으로 읽어 "얕은 쪽 우선"
  tie-break에서 정확히 이김) / `depth=0` / `row_order=-1`(모든 실제 행보다 앞, unique
  제약 없음 확인) / **`header_hint`는 채우지 않는다**(★`fin2/layer3/combine.py`가
  `header_hint IS NULL` 가드를 이미 걸고 있어— 채우면 이 행들이 계층3에서 조용히
  전부 제외됨, 이번 구현 중 발견). 출처는 `source_ref`에 `/xbrl_tree_gap_total` 접미사로
  기록(이 컬럼은 어디서도 필터링 안 됨, 무손실).
- 지배지분귀속(ProfitLossAttributableToOwnersOfParent 등)은 **포함하지 않음** — 실측
  결과 과반(56~57%)이 진짜 fact 자체가 없는 케이스(2026-08-06 웰킵스하이텍 선례와 동종)라
  보조규칙 효과가 제한적.

**검증**: `fin2/tests/test_xbrl_instance.py` 10/10 통과 + 전체
`pytest tests/ fin2/tests/` 489 passed(무관 기존결함 1건만, `test_biz_section.py`).
이미 정상 적재된 필링(15건 표본) 재추출 회귀 확인 — value_mismatch 0, 기존 행 소실 0,
신규 행은 전부 `xbrl_tree_gap_total` fallback만. 백필(744개사, 1,603건, 317,947행,
오류 0) 후 카테고리② 1,551→31건(98.0% 해소). 잔여 31건은 4가지 독립 원인으로 전부
이 규칙 범위 밖 확인(원문 직접 대조): K-GAAP 시대(2007 taxonomy, IFRS 이전) 9건 /
DART 서버가 최초 vintage(2010-04-30) entry point를 404로 반환(원문 확인) 2건 /
`filings.period_end_date`와 실제 XBRL instance 태깅 기간 불일치 1건(별도 메타데이터
이슈) / USD 표시통화 1건(기존 정책상 KRW만 지원) / `filings.period_end_date` 전체
NULL(전사 1,311건 中 일부) 18건. BS 항등식(자산=부채+자본) 전수검사 2,781개 basis
조합 중 2,771 성립(99.64%) — 잔여 10건 중 4건은 ±1원 반올림, 6건은 원문 직접 대조로
duplicate-context 등 코드 버그 가능성 배제하고 필러 자신의 XBRL 태깅 내부 불일치로
확인(우리 추출 로직 문제 아님, R0 "관찰이지 판단 아니다" 원칙대로 그대로 전사).

**근거**: `docs/plans/pdf_only_parser_phase2_design_2026-08-12.md` §A(설계) ·
`docs/qa/pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md`(조사, 버그①②+후속A/B/C) ·
`docs/qa/xbrl_taxonomy_r14_remaining31_2026-08-12.md`(백필 후 잔여 31건 원인 전수 목록).

---

## R15. 계층3 `_CURRENT_STRICT`(bs.trade_payables 등) — 비유동 후보를 stage-rank 숏컷보다 먼저 걸러낼 것

`fin2/layer3/combine.py::_resolve()`는 canonical별 후보를 모은 뒤, 최고 mapping-stage
(exact > normalized > fuzzy)에서 값이 하나로 모이면 **그 자리에서 즉시 confirm**하고
`_reduce_conflict()`(current-strict/narrow-prefer 등 의미기반 필터)로는 아예 넘어가지
않는다. `_CURRENT_STRICT` = `{bs.trade_receivables, bs.trade_payables,
bs.short_term_debt, bs.current_bonds}`는 "유동 계정이 비유동(장기) 후보를 흡수하면 안
된다"는 필터가 `_reduce_conflict()` 안에 이미 있었지만, **top-stage 값이 이미 하나로
collapse된 경우엔 그 필터가 아예 실행되지 못했다** — 유동 라인이 표준 alias 사전에 없어
whitespace 정규화를 거쳐 `normalized` 단계에 그치고, 그 옆의 비유동 라인이 정확히
alias 사전에 등재돼 `exact` 단계를 얻으면, `exact` 단독값(비유동 값, 종종 훨씬 작음)이
그대로 confirm됐다(경남제약 00307028 2024FY: 유동 매입채무 8,206,288,902원 대신
주석·본문 어디에도 없는 비유동 매입채무 6,000,000원이 적재).

**규칙**:
- `_CURRENT_STRICT` canonical은 stage-rank 비교를 하기 **전에** 먼저 비유동 후보를
  제거한다(제거 후 후보가 하나라도 남을 때만 — 전부 비유동이면 원래 rows 유지, 결측을
  새로 만들지 않음). `_BS_GRAND_TOTAL`(신탁계정 제외) 필터가 이미 이 자리(stage-rank
  이전)에서 하던 것과 같은 패턴.
- 비유동 판정(`_is_noncurrent()`)은 **`label_raw`와 `section_path` 둘 다** 검사한다.
  라벨 텍스트 자체에 "장기"/"비유동"이 없는데 `section_path`가 `부채>비유동부채`인
  케이스가 있다(경남제약처럼 유동/비유동 두 라인의 라벨 문구가 완전히 동일한 경우)
  — `label_raw`만 보면 이 케이스를 놓친다.
- 이 사전필터를 통과하고도 유동 후보끼리 값이 갈리면(진짜 충돌), 그 이후는
  기존 stage-rank/`_reduce_conflict()`/HOLD 경로가 그대로 처리한다 — 이 필터가
  유동-유동 판단을 대신 내리지 않는다.

**검증**: `fin2/tests/test_combine_current_strict.py`(단위, DB 비의존) + 실측 회귀:
`report_lines`에서 같은 (rcept, basis) 안에 유동/비유동 매입채무류 라벨이 공존하는
후보 43,725쌍 전수 재계산 — 수정 전/후 `bs.trade_payables`가 바뀐 6,838쌍 중
5,952쌍은 결측(HOLD)→정상값(순수 커버리지 개선), 884쌍은 잘못된 소액값→report_won과
정확히 일치하는 값으로 교정(fail_a near-zero 52건/21개사가 이 안에 포함, 경남제약·
01061497·00113997·00121941·00670340 등 실측 combine_full() 재확인 — 전부 report_won과
0원 diff), 2쌍은 결측(HOLD)으로 전환(2012년 필링 1건, report_lines 자체의 중복행이
원인 — 이 수정과 무관한 별개 데이터 이슈, HOLD가 안전한 방향이라 미조사 보류). 다른
3개 canonical(trade_receivables/short_term_debt/current_bonds)은 이번 모집단에서
변경 0건(영향 없음 확인). pytest 494 passed(무관 기존결함 1건만, `test_biz_section.py`).

**근거**: `docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md` ③(경남제약 원문대조) ·
`docs/plans/gate_b_fail_a_bugfix_2_3_plan_2026-08-13.md` 버그 #3.

---

## R16. 계층3 `_resolve()` stage-rank 숏컷 — `is.revenue`/`bs.trade_payables` 총계 vs
구성요소는 **일반 규칙 금지, curated override만** (R15와 같은 취약점 계열, 다른 처방)

R15와 정확히 같은 근본원인(`_resolve()`가 top-stage 후보가 하나로 collapse되면
`_reduce_conflict()`의 의미기반 필터를 건너뛰고 즉시 confirm)이 `is.revenue`(총계
vs 구성요소)·`bs.trade_payables`(부모 vs 자식)에도 있다. 자식/구성요소 라벨(예:
`수수료수익`·`매입채무및기타채무`)이 공백·번호 없는 "깨끗한" 문자열이라 alias 사전과
글자 그대로 일치해 `exact`를 얻고, 부모/총계 라벨(예: `I. 영업수익`·`매입채무 및
기타유동채무`)은 로마숫자·공백 때문에 정규화를 거쳐야 `normalized`로만 매칭돼
top_vals가 자식 하나로 collapse된다.

**R15와 달리 여기선 일반 규칙(블랭킷)을 적용하면 안 된다** — `report_lines` 전수
실측(계층2, 백필과 무관한 정적 데이터) 결과:
- `is.revenue`: "총계 라벨 있으면 그것 우선" 규칙 → 현재-PASS 303건 회귀 vs 진짜수정
  8건(**38:1**). SBI인베스트먼트(00156910) 등은 총계가 평가성 항목까지 섞인 넓은
  개념이라 **자식이 이미 정답**(report_won과 일치) — 같은 구조(P=총계/F=구성요소)인데
  회사마다 정답이 반대라 구조적 신호만으로는 구별 불가.
- `bs.trade_payables`: "node_role='P'(부모) 있으면 우선" 규칙 → 현재-PASS 11,761건
  회귀 vs 진짜수정 32건(**368:1**). 대다수 회사는 좁은 값(`_NARROW_PREFER` 기존
  설계의도대로)이 이미 정답, 부모가 정답인 건 원문대조로 확인된 5개사뿐.

**규칙**: 대신 `fin2/layer3/industry_profiles.py`의 `CORP_INDUTY_OVERRIDE`·
`NO_REVENUE_CORPS`와 같은 선례를 따라, **원문/report_won 대조로 개별 확인된 회사만**
curated set에 등재하고 stage-rank 이전(R15의 `_CURRENT_STRICT` 사전필터와 같은
자리)에 적용한다.
- `_REVENUE_TOTAL_OVERRIDE_CORPS`(`fin2/layer3/combine.py`): 한국전자홀딩스
  (00159254)·미래에셋벤처투자(00340096) — `is.revenue` 총계가 정답인 회사만.
- `_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`(같은 파일): 현대공업(00164502)·
  국일신동(00203847)·코아스(00210856)·케이엔솔(00304076)·IPARK현대산업개발
  (01310269)·**KCC건설(00105466)·조일알미늄(00149239)·다스코(00353878)**(2026-08-14
  확장, 아래 참고) — `bs.trade_payables` 부모가 정답인 회사만.
- 신규 등재는 반드시 원문/report_won 대조로 확인 후 추가 — 구조가 같아 보인다고
  블랭킷 규칙으로 일반화하지 말 것(이 문서의 실측 결과가 그 위험을 이미 증명함).

**확장(2026-08-14)**: `docs/qa/gate_b_faila_residual_triage_2026-08-14.md` §2에서
발견한 3개사를 원문 XBRL 직접대조로 추가 확인 후 등재. 세 회사 모두 **동일한
ACODE 쌍**(부모=`ifrs-full_TradeAndOtherCurrentPayables`, 자식=
`ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers`, 예: KCC건설
`20250320001281.xml`:7693-7716)이라 기존 5개사보다 구조적 근거가 더 명확하다.
검증: 3개사 scoped 백필(`build_std_v3.py --corp <3개사>`, 270행·오류0) + Gate B
scoped 재검증(`gateb_audit.py --corp-file <3개사> --recheck`) — trade_payables
fail_a 10→**0**(전부 pass), **fail_b 0**(다른 기간 회귀 없음). 남은 다스코
(00353878) fail_a 8건은 무관한 `cfo` 필드의 기존 별개 결함.

**스코프 밖**(이 override로 못 고침, 별도 트랙): BS에 결합총계 라인 자체가 없어
매입채무+기타채무가 미합산인 케이스(01412822류, additive 규칙 필요) · Gate B
Track A concept_map이 노트 안 비-매입채무 항목을 오매핑하는 케이스(01090471류,
`face_audit.py` 쪽) · 서로 다른 라벨의 형제 후보 충돌(F-vs-F, 149건) ·
bank/credit_finance 레이어2 커버리지 갭(총계 라인 자체가 `report_lines`에 없음).

**검증**: `fin2/tests/test_combine_curated_overrides.py`(단위, DB 비의존, 등재/
비등재 대조군 포함) + 7개사 scoped 백필(`build_std_v3.py --corp <7개사>
--year-min 1999`, 706행·오류0) + Gate B scoped 재검증(`gateb_audit.py --corp-file
<7개사> --recheck`) — 706행 중 fail_a **0**(수정 전 이 7개사 안에 revenue 8행·
trade_payables 32행 fail_a 존재), DB 전체 `fail_a` 686→646(**-40**, 정확히
8+32와 일치, 다른 corp는 이번 recheck 스코프 밖이라 불변).

**근거**: `docs/qa/gate_b_fail_a_revenue_tradepayables_triage_2026-08-13.md`(원문
대조) · `docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md`
(설계+실측) · `fin2/layer3/combine.py::_resolve()`(`_REVENUE_TOTAL_OVERRIDE_CORPS`/
`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`).

---

## R17. `bs.trade_payables` additive override — curated 키는 **corp 단독이 아니라
(corp, fiscal_year, fiscal_period)** (R16의 함정 재발)

R16(§`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`)과 같은 계열의 새 사례 5개사에서,
BS 본문에 결합 총계(P) 라인 자체가 없고 매입채무+형제 유동채무 라인(F) 두 개만
있는 레이아웃을 발견했다. 원문 XBRL 직접대조로 확인: 이 두 라인의 합이
`ifrs-full_TradeAndOtherPayablesUndiscountedCashFlows`[MaturityAxis=1년이내] 또는
`ifrs-full_TradeAndOtherCurrentPayables` — report_lines 텍스트추출로는 안 잡히는
위치의 진짜 XBRL fact와 정확히 일치한다.

**함정 #1(구현 단계에서 실측)**: 형제 라벨(예: '기타지급채무')은 AccountMapper
별칭표를 거쳐 **자기 고유의 canonical**로 매핑된다(`bs.other_current_payables`
등, `bs.trade_payables`가 아니다). `_resolve()`는 canonical별로 이미 분리된
`cands[canonical]`만 보므로, override가 자기 canonical(`rows`)만 뒤지면 형제
라벨을 절대 못 찾아 **한 건도 발동하지 않는다**(최초 구현이 이 상태로 유닛테스트만
통과하고 실제로는 무효였음 — 목이 두 라벨을 인위적으로 같은 canonical 리스트에
넣어놨던 게 원인). 수정: `cands.values()` 전체를 뒤진다.

**함정 #2(더 심각, scoped 백필+Gate B recheck로 실측)**: 위 함정을 고쳐서
override가 실제로 발동하게 만들자, 목표 기간(대부분 FY2025~2026Q1)은 고쳐졌지만
**같은 회사의 과거 모든 분기(2010~2024, LG화학만 100건+)가 새로 fail_b(REVIEW)로
대규모 회귀**했다 — "두 라인 합 = report_won"은 원문대조로 확인한 **그 특정
필링(들)에서만** 성립하고, 같은 회사의 다른 기간엔 성립하지 않는다(실측: LG화학
연결 2010 report_won=1.30조인데 두 라인 합=2.12조). R16의 corp 단독 키를 그대로
가져다 쓴 게 원인 — R16(parent override)은 "이 회사는 항상 부모가 정답"이라는
회사 단위 성격이 실제로 안정적이었지만, 이번 additive 관계는 **회사 단위가 아니라
특정 필링(주로 결합공시 방식이 바뀐 시점 이후)에서만** 성립한다는 게 다르다.

**규칙**: `_TRADE_PAYABLES_ADDITIVE_OVERRIDE`(`fin2/layer3/combine.py`)는 키를
`(corp, fiscal_year, fiscal_period)` 3-튜플로 쓴다 — corp 하나가 늘 이 관계를
만족한다고 가정하지 않는다. `_resolve()`가 `fy`/`period`를 추가로 받아 게이팅한다
(`corp`만 받던 R16 시그니처를 확장, 하위호환: 기본값 `None`이라 미지정 호출은
override 전부 비활성). basis(연결/별도)는 `_resolve()` 호출 자체가 이미
basis별로 분리돼 있어 별도 키가 필요 없다. 신규 등재는 반드시 그 정확한
(corp, fy, period)에서 원문/report_won 대조로 확인 후 추가 — 인접 기간까지
자동으로 넓히지 말 것(이 R17 자체가 그 위험의 실측 증거).

등재: (00356361 LG화학, 2025, FY)·(00356361 LG화학, 2026, Q1)·(00113544 대한화섬,
2025, FY)·(00109310 대동기어, 2025, FY)·(00138446 아가방컴퍼니, 2025, FY)·
(01093007 LS에코에너지, 2025, FY).

**검증**: `fin2/tests/test_combine_curated_overrides.py`(단위, 등재 튜플 발동 +
**같은 corp의 다른 기간은 비발동**하는 회귀재현 방지 테스트 포함) + 5개사 scoped
백필(`build_std_v3.py --corp <5개사> --year-min 1999`, 814행·오류0) + Gate B scoped
재검증(`gateb_audit.py --corp-file <5개사> --recheck`) — fail_a 12→3(trade_payables
9건 전부 pass, 남은 3건은 무관한 controlling_ni 버그), **fail_b 0**(다른 기간
회귀 없음, 함정#2 재발 안 함 확인). DB 전체 `fail_a` 671→662(**-9**, 정확히 일치).

**근거**: `docs/plans/gate_b_faila_trade_payables_additive_design_2026-08-14.md`
(원설계, corp 단독 키 — 이 R17로 교체) · 이 세션 실측(구현 중 함정#1·#2 발견 →
DB 원상복구 → 사용자 승인(회사+기간 범위로 재설계) → period-scoped로 재구현·
재검증) · `fin2/layer3/combine.py::_resolve()`
(`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`) · `fin2/tests/test_combine_curated_overrides.py`.

---

## R18. 계층2 CF `cf.dividends_paid` 부호 — document.xml 인라인 XBRL(Track A) 사실로 대사(오버레이),
**모호하면 손대지 않음**(설계 예상치보다 실제 적용률은 낮음, 짐작 아닌 실측)

버그#2. CF 본문표의 "배당금의 지급" 셀은 회사별 확장 개념(`entity{corp}_...`)으로
태깅돼 있어 부호를 신뢰할 수 없는데, production 텍스트 추출기
(`fin2/extract/text.py`→`report_lines.py`)가 그 셀 **텍스트**(부호 표시 없는
맨숫자)만 읽어 항상 양수로 저장한다 — 원본 문서 **다른 위치**(자본변동/배당상세
표)에는 같은 사실이 표준 IFRS 개념(`ifrs-full_DividendsPaidClassifiedAsFinancingActivities`
등)+정확한 부호(괄호표시)로 이미 태깅돼 있다. Gate B 감사기(`face_audit.py`)는
그 표준개념 태그를 문서 전체에서 직접 읽어 정답을 얻지만, production 추출기는
전혀 안 읽는다. 상세: `docs/qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md`
(원인 조사) · `docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md`(설계).

**규칙**: `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_dividends_paid_sign()`
— `extract_report_lines()`가 텍스트추출 결과(`lines`)를 다 만든 **직후** 호출한다
(원문을 새로 열지 않음, `read_report_face_xbrl()`이 자체적으로 파일을 다시 읽음).
계층2가 canonical 매핑을 하지 않는다는 R0 원칙([[architecture-report-read-layer2-only]])을
지키기 위해 **AccountMapper(퍼지매칭)를 쓰지 않는다** — 대신:
1. `read_report_face_xbrl()`(face_audit.py, **그대로 재사용, 한 글자도 수정 안 함**)로
   canonical(`map_acode()`, 결정적 조회, 짐작 아님)별 사실 테이블을 만든다.
2. 텍스트 후보행은 `label_raw`에 "배당"+"지급"이 **둘 다** 있는지 **키워드 부분일치**로만
   좁힌다(canonical 추론이 아니라 `text.py`가 이미 곳곳에서 쓰는 것과 같은 구조적
   키워드 필터).
3. `(basis, is_cumulative)` 키에서 텍스트 후보가 **정확히 1개**, 사실도 **정확히
   1개**, 그리고 둘의 절대값이 **1% 이내로 일치**할 때만 override — 아니면 손대지
   않는다(★블랭킷 금지, R16/R17과 같은 원칙).
- `fiscal_year < 2024`는 파일도 안 열고 즉시 no-op(커버리지 절벽 실측,
  findings 문서 §5 — 1999~2023 ACODE/ACONTEXT 보유율 0.0%).
- v1 스코프는 `cf.dividends_paid`만(설계 §4-4) — 다른 CF 계정 확장은 각각 회귀
  diff로 확인 후 별도.

**★설계 예상치(92%)보다 실제 적용률이 훨씬 낮음 — 실측으로 확인, 안전하지만
저수확**: 설계 문서는 ACODE 커버리지(2024+ 92%)만 보고 낙관했으나, 실제
fail_a 36건을 전수 재실행하니 **6건만 적용되고 그 6건 전부 report_won과
정확 일치(오탐 0)** — 나머지 30건은 "모호(후보 2개 이상)" 또는 "애초에 부호가
아니라 자릿수/누락 문제"(예: 00138729/LG생활건강 — 부호는 이미 맞고 report_won과
0.005% 차이인 다른 성격의 결함, 이 R18 범위 밖)로 안전하게 스킵됐다. 무작위
샘플(59건, fy≥2024 CF "배당"+"지급" 후보 전체 모집단 10,554건 중)에서도 오탐
0건. **결론: 이 오버레이는 안전하지만(회귀 없음) 이 버그의 부분적 해결이다** —
잔여는 별도 원인규명 필요(예: 다중 배당 라인 명시적 처리, note_lines 폴백 등).

**검증**: `fin2/tests/test_report_lines_inline_xbrl_overlay.py`(단위6건, LG
`20260318001025` 실측 재현 포함) + pytest 514 passed(무관 기존결함 1건 제외) +
fail_a 36건 전수 재실행(적용 6건·전부 report_won 일치·오탐 0, 미적용 30건은
근거 있는 스킵) + 무작위 표본 59건 오탐 0 + 소급 백필
(`load_report_lines.py --rcept-file <10,554건>`).

**근거**: `docs/qa/gate_b_bug2_dividends_paid_findings_2026-08-13.md` ·
`docs/plans/gate_b_bug2_xbrl_inline_overlay_design_2026-08-13.md` ·
`fin2/extract/report_lines_inline_xbrl_overlay.py` ·
`fin2/extract/report_lines.py::extract_report_lines()`.

## R19. `table_extractor.py::_split_label_amounts()` 주석번호 가드 — 콤마 없는 단일 숫자는
**표 단위 컨텍스트(`table_has_note_column`)로만 주석번호 인정, 행 단독 판정 금지**

Gate B revenue 확정버그 B(한진중공업홀딩스). `_split_label_amounts()`가 재무제표 본문
(BS/IS/CF/SCE) 표에서, 라벨 바로 다음 칸(`i==1`)의 콤마 없는 1~3자리 당기 금액을
"주석번호"로 오인해 드롭하는 오탐이 있었다 — 원래 가드는 부국증권형 다중 주석참조
("2,4,32,…")를 막기 위한 것인데, `not amount_cells`라는 간접 조건만 쓰고 실제 콤마
유무·표 구조는 전혀 확인하지 않았다.

**핵심 발견(원리적 한계)**: 콤마 없는 단일 숫자 후보는 **행 하나의 셀 내용만으로는
진짜 주석번호인지 진짜 금액인지 판정 불가능** — 실사례 반증(한양증권 "11"=진짜 주석
vs 진원생명과학 "512"=진짜 금액, 셀 모양 동일·정답 반대)으로 확정. `len(cells)>=6`,
콤마 단독 조건 등 v1~v6 전부 실사례로 폐기(근거: `docs/plans/note_ref_guard_body_
statement_fix_plan_2026-08-14.md`).

**규칙(v7, 최종)**: `parser/xml/table_extractor.py::_split_label_amounts()` +
`_table_has_comma_note_column()`:
- 콤마 다중참조("2,4,32,…")는 행 하나만 보고 **항상** 주석으로 확정(오탐 0건 실측,
  49건 대조).
- 콤마 없는 단일 숫자("34", "11")는 **같은 표의 다른 행에 콤마 다중참조가 있다고
  확인됐을 때만**(`table_has_note_column=True`, `extract_rows()`가 표 순회 전 1회
  선스캔해 전달) 주석으로 인정.
- `i==1` 제한 유지(캐스케이드 차단 — 첫 칸 이후로는 이 가드 자체가 발동하지 않음).
- `fin2/extract/report_lines.py`의 다른 두 호출부(`_detect_period_layout`·
  `_emit_eps_lines`)는 기본값(`table_has_note_column=False`, 콤마 단독 규칙) 유지 —
  전자는 내부 휴리스틱이라 최종값 무영향, 후자는 구조상 진짜 주석 컬럼이 안 나와
  더 안전.

**검증**: 회귀 테스트 9건(`fin2/tests/test_section_p_header.py::
test_note_ref_guard_r19_comma_required` 등, 기존 3건 기대값 갱신 포함) + `extract_facts()`
원문 XML 3건(한진중공업홀딩스 2025H1·부국증권 2018H1·한양증권 2014Q1) end-to-end
대조 + `pytest tests/ fin2/tests/` 515 passed(무관 기존 실패 1건 제외).

**소급 백필**: 부분(후보 89,430건)이 아닌 **전체 185,067건 XML 전수 재추출** 결정
(단순·안전) — `report_lines` 60,534,978행(29GB) 재적재 + `std_financials_v3` 2,537개사·
299,565행 재빌드, 에러 0건(2026-08-14 17:18~20:50, 약 3시간32분,
`scripts/run_r19_backfill_parallel_2026-08-14.sh`).

**Gate B 재감사 결과**(2026-08-14~15, `scripts/run_gateb_audit_parallel.sh --recheck`):
fail_a 686→631(-55, 8.0%↓) / fail_b 2,696→2,704(+8, REVIEW 전용·차단 아님) / pass
195,212→196,773. 타깃 버그(한진중공업홀딩스 00163673 revenue, 2025 H1·Q3 separate)
해소 확인(H1→pass, Q3→pending, 둘 다 더 이상 fail_a 아님, 값 report_won과 직접 대조).
BS 항등식(자산=부채+자본) 전수 재검사(`scripts/probe_bs_identity_post_r19_2026-08-15.py`):
235,562건 중 위반 869건(0.37%) — R19 이전 기준선은 미보유하나 대다수가 1,000원 단위
반올림차라 광범위 회귀 신호 없음.

**부수발견(미착수, 이 R19 범위 밖)**: 같은 필링(한진중공업홀딩스 20250814001174)의
연결 `is.cogs` fail_a — 라벨 "Ⅱ.영업비용/Cost of sales" **총계** 대신 그 아래 하위
상세줄 "(1) 매출원가"(`source_ref`) 값이 채택돼 655,204백만원 대신 611,638백만원이
적재됨. `git stash`로 R19 이전 코드에 동일 XML을 재현해도 **동일 값**이 나와 R19와
무관한 **독립된 선재(pre-existing) 버그**로 확인(R16의 stage-rank 숏컷류와 유사한
"총계 vs 하위상세" 오귀속 패턴으로 추정, 별도 트랙 필요).

**근거**: `docs/plans/note_ref_guard_body_statement_fix_plan_2026-08-14.md`(v1~v7
설계 이력·근거 전부) · `docs/qa/gate_b_revenue_bugB_note_ref_guard_root_cause_2026-08-14.md`
(근본원인+전수스캔) · `scripts/run_r19_backfill_parallel_2026-08-14.sh` ·
`scripts/probe_bs_identity_post_r19_2026-08-15.py`.

---

## R20. 계층3 `_resolve()` stage-rank 숏컷 — 지주회사형 `is.sga`(영업비용 총계 vs
판매비와관리비 서브라인), R16과 같은 계열, **새 대상**·**corp+기간 키**로 등재

R19 검증 중 부수발견(한진중공업홀딩스 `is.cogs`)을 조사하다가 R16과 정확히 같은
근본원인(`_resolve()`가 top-stage 후보 하나로 collapse되면 `_reduce_conflict()`의
의미기반 필터를 건너뛰고 즉시 confirm)이 `is.sga`에도 있음을 확인. 지주회사형 손익
계산서가 "Ⅱ.영업비용"(=매출원가류+판매비와관리비 결합 총계, `ACODE=ifrs-full_
CostOfSales`)을 P라인으로 두고 그 아래 "(n)판매비와관리비" 서브라인을 두는 구조에서,
총계 라벨은 alias 사전과 그대로 일치해 `stage=exact`, 서브라인은 번호 접두어 제거가
필요해 `stage=normalized`로만 매칭 — top_vals가 총계(오염값) 하나로 collapse된다.

**R16과 달리 여기선 corp 단독이 아니라 (corp, fy, period) 3-튜플로 등재**(R17
선례) — 같은 corp도 다른 기간엔 이 패턴이 아닌 구조를 가질 수 있음을 실측으로 확인
(예: 한진중공업홀딩스 00163673 FY2010: "1.지분법손실+2.임대사업원가+3.판매비와관리비"
3항목 혼재, §1의 깨끗한 COGS+SGA 2항목 구조가 아님). Phase 0 정밀스캔(exact-normalize
+구조검증, `docs/qa/is_sga_cogs_holdco_phase0_scan_2026-08-15.md`)으로 진짜 대상을
좁혔다 — substring LIKE 최초추정 "166개사"는 보험사 '기타영업비용' 등 무관 잡음이
대부분이었다.

**규칙**: `_SGA_SUBLINE_OVERRIDE_KEYS`(`fin2/layer3/combine.py`, corp+fy+period
3-튜플 685개, 46개사 — `scripts/generate_sga_subline_override_2026-08-15.py`로
재현 가능, Phase 0 target_rows와 1:1) — is.sga stage-rank 이전(R16/R17과 같은
자리)에 `_SGA_SUBLINE_LABELS`(`판매비와관리비`/`기타판매비와관리비`) 매치 서브라인
후보로 rows를 좁힌다. 신규 등재는 반드시 Phase 0와 같은 방식(exact-normalize 후보
좁히기 + 자식 라벨 COGS/SGA 둘 다 존재 + child_sum==parent 항등식)으로 확인 후
추가 — 일반화(블랭킷) 금지는 R16/R17과 동일 근거.

**스코프 밖(이 R20으로 못 고침, 후속 트랙 필요)**:
- `is.cogs` 자체 — 회사마다 증상이 다르다(정확/과소계상/충돌), 서브라인 합산이
  필요한 회사(두산류)는 R17 additive override 패턴 재사용 후보지만 개별 등재 필요.
- Gate B `report_won`(cogs) 개념 문제 — 이 corp군의 XBRL은 `ifrs-full_CostOfSales`를
  총계(COGS+SGA 결합)에 태깅해, `is.cogs`를 아무리 정확히 고쳐도(순수 COGS로) Gate B는
  report_won(총계)과 다르다며 계속 fail_a를 띄운다. 비교 대상 개념이 애초에 다르다 —
  `face_audit.py` 로직 조정 여부는 별도 사용자 결정 필요.
- Phase 0에서 XBRL로 실제 검증 가능한 건 46개사 중 **4개사·15건뿐**(전부
  2024~2026년 필링) — 나머지 42개사는 XBRL 비교 데이터 자체가 없어 `is.sga`가
  오염돼 있어도 Gate B가 원래 못 잡았던 "침묵 오염" 케이스(R20 적용으로 조용히
  해소되지만 Gate B 수치로는 드러나지 않음).

**검증**: `pytest tests/ fin2/tests/` 515 passed(무관 기존 실패 1건 제외,
`fin2/tests/test_biz_section.py::test_lxintl_facility_table_dropped`, `git stash`로
main에서도 동일 확인) + 46개사 scoped 백필(`build_std_v3.py --corp <46개사>`) +
Gate B scoped 재검증(`gateb_audit.py --source v3 --corp-file <46개사> --recheck`) —
sga 필드 fail(fail_a+fail_b) **전체 46개사·전체기간 0건**(회귀 없음), 3개 알려진
케이스(한진중공업홀딩스·두산·대성홀딩스) 전부 원문대조 기대값과 정확히 일치 확인.
잔존 cogs fail_a 10건은 위 "스코프 밖" §3 문제 그대로(예견됨, R20과 무관).

**근거**: `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md`(설계) ·
`docs/qa/is_sga_cogs_holdco_phase0_scan_2026-08-15.md`(Phase 0 정밀스캔) ·
`fin2/layer3/combine.py::_resolve()` (`_SGA_SUBLINE_OVERRIDE_KEYS`/
`_SGA_SUBLINE_LABELS`) · `scripts/generate_sga_subline_override_2026-08-15.py`.

---

## R21. `is.cogs` additive override — 매출원가류 서브라인 **합산**(stage-rank/충돌
해소가 아니라 SUM), **raw-label 직접매칭**으로 전역 alias 오염 회피(R16/R20 자매규칙)

R20과 같은 46개사 '영업비용' P라인 구조가 `is.cogs`도 오염시키지만 메커니즘이 다르다.
COGS 서브라인이 **2개 이상**(상품매출원가/제품매출원가/용역매출원가/공사매출원가 등)
공존하는데, 이들은 총계의 상호배타적 구성요소라 **합산**이 정답이지 stage-rank나
`_reduce_conflict()`의 대상이 아니다. 두 실패 양상 확인(`scripts/probe_cogs_
phase2_2026-08-15.py`, 39개사·883행):
- **(a) 충돌**: 서브라인들이 이미 기존 fuzzy alias(예: `상품매출원가`)로 `is.cogs`에
  매핑되지만 서로 다른 값이라 `_resolve()`가 HELD(NULL)로 묻는다(223행/15개사).
- **(b) 침묵드롭**: 서브라인 라벨(`상품및제품매출원가`/`임대매출원가-임대수익원가`/
  `제ㆍ상품매출원가`/`제품및상품매출원가`/`천연가스매출원가`)이 alias 사전에 없어
  `unknown`(conf=0)으로 `_map_rows()`의 신뢰도 게이트(<0.88)에서 `_resolve()`가 보기도
  전에 드롭된다(95행/3개사).

**★일반 alias 추가로 (b)를 고치면 안 되는 이유(전역 위험 실측 확인)**:
`scripts/probe_cogs_alias_global_risk_2026-08-15.py`로 5개 미매핑 라벨의 **전역**
사용처(이 39개사 밖 포함 전체)를 조회한 결과, 2개는 **다른 회사에서 '매출원가'
총계와 형제로 공존**한다 — `상품및제품매출원가`(8개사, 64/162 콤보가 총계와 공존)·
`임대매출원가/임대수익원가`(35개사, 514/548 콤보가 총계와 공존). 이는
`account_maps/is_accounts.py`가 이미 2026-07-18에 `제품매출원가`/`상품매출원가`
세부 alias를 **바로 이 이유로 제거**한 것과 정확히 같은 충돌 패턴(총계+세부 동시
alias → conflict-hold 회귀) — 일반 alias로 추가하면 00109286·00787376 등 이 트랙과
무관한 회사에 새 회귀를 유발한다. (나머지 3개 라벨은 전역 충돌 0건으로 안전하지만,
단일 메커니즘 유지를 위해 이들도 같은 방식으로 처리한다.)

**규칙**: `_COGS_ADDITIVE_OVERRIDE`(`fin2/layer3/combine.py`, (corp, fy, period,
basis) 4-튜플 319개, 19개사 — R16/R17/R20과 달리 **basis도 키에 포함**한다. 연결/
별도가 같은 corp+기간이라도 COGS 서브라인 구성이 다를 수 있어서다(다른 override는
`_resolve()`가 이미 basis별로 분리 호출돼 불필요했지만, 이 override는 `combine_full()`
레벨에서 동작해 명시적으로 필요). `scripts/generate_cogs_additive_override_
2026-08-15.py`로 재현 가능) — `combine_full()`에서 `_resolve()` 이후, raw
`merged`(`build_merged_lines()` 결과, `_map_rows()`/AccountMapper를 거치지 않음)를
`_cogs_additive_labels()`로 직접 라벨텍스트 매칭해 합산, `col["cogs"]`를 덮어쓴다.
전역 alias 테이블은 전혀 건드리지 않아 이 19개사 밖으로 영향이 전혀 없다.
`_cogs_additive_labels()`는 `_map_rows()`의 H1/Q3 누적셀 dedup 로직을 라벨텍스트
기준으로 그대로 복제한다(같은 interim/cum_seen 알고리즘).

**신뢰성 검증**(생성 시점 항등식과 별개로, 실제 runtime 파이프라인 재검증): 319개
키 전부를 `build_merged_lines()` + `_cogs_additive_labels()`로 재실행해 `len(picked)
== len(want)` 확인 — **불일치 0건**. 70개 다중-rcept(정정) 키의 서브라인 구성도
전부 확인(rcept 간 라벨셋 불일치 0건) — 대표 1개 rcept로 override를 만들어도 안전함을
사전 확인.

**Gate B 재검증 결과의 해석(중요 — REVIEW 신호이지 회귀가 아님)**: scoped 재검증
(19개사) 결과 fail_a(cogs) 14건은 **전부 예견된 것**(R20 §3, Phase 0가 미리 확인한
XBRL Track A가 `ifrs-full_CostOfSales`를 총계에 태깅한 4개사 — 00108940·00117212·
00143527·00163673; 이번에 00143527이 NULL(conflict-hold)→실값으로 바뀌면서 처음
드러남, 새 버그 아님). fail_b(cogs) 196건은 원문 직접대조(2건, 00808022·01412822)로
근본원인 확인: Gate B Track B(`read_report_face_text`)도 **같은 AccountMapper**를
써서 서브라인을 **개별 라인으로만** 읽고 합산 개념이 없다 — 표준화값(정확한 합산,
파이프라인 재실행으로 재검증됨)과 Track B의 개별 서브라인 값이 다른 게 당연하다.
Track B는 unmapped 라벨(예: `상품및제품매출원가`)도 **똑같이** 드롭해 일부는 완전
누락 상태로 비교한다. Gate B 감사기 자체의 알려진 한계(비차단 REVIEW)이지 표준화
데이터 오류가 아니다 — R20 §3와 같은 계열의 "비교대상 개념 불일치" 문제.

**검증**: `pytest tests/ fin2/tests/` 515 passed(무관 기존 실패 1건 제외) + 19개사
scoped 백필(`build_std_v3.py --corp <19개사>`) + Gate B scoped 재검증 — sga 필드
회귀 재확인(46개사 전체 fail 0건, 불변) + cogs 값 5개 샘플(한진중공업홀딩스·두산·
대성홀딩스·00108135 4서브라인 합산·01412822 unknown라벨 포함 합산) 전부 자체 항등식과
정확히 일치.

**근거**: `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md`(설계
Phase 2) · `scripts/probe_cogs_phase2_2026-08-15.py`·`scripts/probe_cogs_unmapped_
labels_2026-08-15.py`·`scripts/probe_cogs_alias_global_risk_2026-08-15.py`(조사) ·
`fin2/layer3/combine.py::combine_full()`/`_cogs_additive_labels()`
(`_COGS_ADDITIVE_OVERRIDE`) · `scripts/generate_cogs_additive_override_2026-08-15.py` ·
`account_maps/is_accounts.py`(2026-07-18 제품/상품매출원가 제거 선례).

### R21 부기 — `_cogs_additive_labels()` 라벨충돌 버그(Phase 3 착수 중 발견·수정, 2026-08-15)

Phase 3(Gate B 비교로직) 착수 전 `00143527 2025 Q1 consolidated` fail_a 1건을 원문대조하다
발견: `_norm_label()`(`fin2/layer3/industry_profiles.py::norm()`)은 라벨을 첫 `(`에서
자른다(`"영업이익(손실)"→"영업이익"`처럼 후행괄호를 벗기려는 의도). 그런데 괄호 뒤에
텍스트가 더 있는 라벨 — `"기타수익(매출액)에 대한 매출원가"`(진짜 COGS 서브라인) — 은
`"기타수익(매출액)"`(매출액 세부내역, 전혀 다른 계정)·`"기타수익"`(별개 손익항목)과 같은
정규화 키로 충돌한다. `_cogs_additive_labels()`는 `picked[label]=value`로 마지막 매칭을
그냥 덮어써서, 어느 쪽이 채택될지 iteration 순서에 좌우되는 취약점이었다.

**전수 스캔**(319개 키): 충돌 노출 31키(00143527 24개·00163673 3개, 3-way 충돌이라
fy/period로 퍼짐). 실제로 틀린 값이 나온 건 **5건** — `00143527 2025 Q1`(fail_a로
드러남) + `00163673 2017FY/2018FY/2018H1/2019Q1`(**전부 2024년 이전이라 XBRL Track A
커버리지가 없어 Gate B가 전혀 못 잡던 침묵오염**, R21 Phase 0가 경고한 "빙산의 일각"이
실제로 여기서 나타났다).

**수정**: `_cogs_additive_labels()`에 라벨충돌 가드 추가(`_is_cogs_labeled()`) — 같은
정규화 키에 라벨 2개 이상이 붙으면 원문 라벨텍스트에 `'매출원가'` 부분문자열을 포함하는
쪽을 신뢰한다(이 override의 want 라벨은 전부 "매출원가류" 개념이라 원칙적으로 항상 성립).
실측 31건 전부 이 규칙 하나로 모호함 없이(그룹당 후보 정확히 1개) 갈렸다. 그런 후보가
없거나 여럿이면(미관측) 기존 동작(마지막 매칭 승) 유지 — 방어적으로만 개입.

**검증**: 수정 후 31건 전부 재실행 → 5건 전부 정답으로 전환(오답 0건 잔존). 319키 전체
`len(picked)==len(want)` 재확인(불일치 0건, 회귀 없음). pytest 515 passed(무관 기존
실패 1건 제외, 불변). 2개사 scoped 백필(`build_std_v3.py --corp 00143527,00163673`) +
19개사 scope Gate B 재검증 — cogs fail_a **14/14 전부 `report_won == cogs+sga` 항등식
정확히 일치**(이전 13/14, 이제 00143527 2025 Q1도 합류) 확인.

**근거**: `scripts/probe_cogs_additive_label_collision_2026-08-15.py`(전수 충돌 스캔) ·
`scripts/probe_cogs_collision_impact_2026-08-15.py`(수정 전/후 대조) ·
`scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py`(Gate B 재검증) ·
`fin2/layer3/combine.py::_cogs_additive_labels()`/`_is_cogs_labeled()`.

---

## R22. Gate B `face_audit.py` — `is.cogs` vs `report_won` **개념 자체가 다른** 4개사는
curated pending 예외처리(R21 §3 후속, 사용자 결정 2026-08-15 옵션 a)

R21 §3이 확인한 문제: 19개사 중 4개사(00108940 대성홀딩스·00117212 두산·00143527·00163673
한진중공업홀딩스)는 XBRL `ifrs-full_CostOfSales`가 순수 COGS가 아니라 **COGS+SGA 결합
총계**에 태깅돼 있다. `is.cogs`(std)를 아무리 정확히 계산해도(순수 COGS) Gate B의
`report_won`(결합 총계)과 구조적으로 못 맞는다 — std_v3 데이터 버그가 아니라 **비교
개념 자체가 다른** 케이스.

**세 옵션 중 (a) 채택**(사용자 결정): (b) `is.cogs`+`is.sga` 합을 report_won과 비교하는
로직 추가는 4개사 중 두산(00117212) 1개사만 SGA XBRL개념(`dart_TotalSellingGeneral
AdministrativeExpenses`)이 태깅돼 적용 가능하고 나머지 3개사는 그 개념 자체가 없어
채택 안 함. (c) 방치는 매 전수재검증마다 14건이 계속 "확인 필요" 신호로 재부상해 반복
조사 비용이 남음. (a)는 `face_audit.py`에 이미 있는 `_PENDING_REASONS` 패턴
(`COMPARATIVE_ROW`/`SOURCE_NOT_TRACK_A`/`LABEL_UNMATCHED`/`GAPFILL_UNVERIFIED`)을 그대로
재사용 — 4개사 전부 균일 적용 가능하며 std_v3 데이터/파이프라인은 전혀 건드리지 않는다
(Gate B 감사 레이어 국한).

**구현**: `fin2/audit/face_audit.py`에 새 pending 사유 `"COGS_SGA_CONCEPT_MISMATCH"`을
`_PENDING_REASONS`에 등재 + curated 4-튜플 키집합 `_COGS_CONCEPT_MISMATCH_KEYS`
(`(corp_code, fiscal_year, fiscal_period, basis)`, 14개 — R16~R21 override와 같은
원칙, 블랭킷 금지) + `audit_fields()`에서 `canon=="is.cogs"`이고 현재 행 키가 그
집합에 있으면 정상 대조를 건너뛰고 즉시 pending 처리하는 분기.

**Phase 3 착수 중 부수발견(중요)**: 이 14건을 원문대조로 확정하는 과정에서 R21의
`_cogs_additive_labels()` 라벨충돌 실버그를 발견·수정했다(위 "R21 부기" 참고) — pending
예외처리 전에 반드시 먼저 고쳐야 했다(안 그러면 진짜 데이터버그를 "어쩔 수 없는 개념
불일치"로 위장할 뻔했다).

**검증**: pytest 515 passed(무관 기존 실패 1건 제외) + 4개사 scoped Gate B 재검증
(`gateb_audit.py --source v3 --corp-file <4개사> --recheck`) — cogs fail_a **14→0**
(전부 pending 전환, `pending_detail`에 `COGS_SGA_CONCEPT_MISMATCH` 확인) + 이 4개사의
fail_a(총) 0(비관련 필드 회귀 없음) + fail_b(Track B, 64건 — R21에서 이미 문서화된
별개 이슈, 불변) 확인.

**근거**: `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md` Phase 3 ·
`scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py` · `fin2/audit/face_audit.py`
(`_COGS_CONCEPT_MISMATCH_KEYS`/`_PENDING_REASONS`/`audit_fields()`).

---

## R23. `fin2/taxonomy/concept_map.py` — `bs.trade_payables` concept_map 갭 5종 추가
(Gate B 리더 전용, std_v3 무관) + 우연일치 가드 1건

전수스캔(`gateb-reader-concept-gap-scan-2026-08-15` 메모리, `scripts/probe_gateb_reader_
concept_gap_2026-08-15.py`)이 확정한 `trade_payables` fail_a 148/167건의 원인: Gate B
감사기(`fin2/audit/face_audit.py`)가 원문 XML을 재파싱할 때 쓰는 `concept_map.py`에 그
회사가 실제로 쓰는 ACODE 5종이 아예 등록돼 있지 않아, 후보 자체가 없거나 엉뚱한 값으로
좁혀졌다(std_v3 데이터 버그 아님).

**범위 확정(구현 전 재조사, 중요)**: 원설계 메모는 이 파일이 "Gate B 리더 전용, std_v3
무관"이라 적었는데, 세션 시작 시 `fin2/extract/xbrl.py`가 실제 프로덕션 Track A
추출기(E-레이어)라는 사실을 발견하고 한 차례 "std_v3에도 영향" 으로 재평가했다가,
`fin2/layer3/combine.py`(std_v3/`std_financials_v3`를 실제로 만드는 코드)를 추적한 결과
`report_lines`(계층2 텍스트)만 읽고 `fact_v2`/`concept_map.py`는 전혀 참조하지 않음을
확인 — 원설계의 "저위험" 판단이 맞았다(`fin2.layer3.build.build_corp`도
`scripts/build_std_v3.py`에서만 호출, 데일리 미배선). `fin2/standardize/build.py`
(std_financials_v2)는 `fact_v2.canonical_account`를 읽지만 이건 뷰 스왑(2026-08-09) 이후
아무도 안 읽는 레거시 경로라 무관.

**구현**: `fin2/taxonomy/concept_map.py`의 `_BS`에 5개 ACODE 추가, 전부 `bs.trade_payables`:
`ifrs-full_TradeAndOtherCurrentPayablesToTradeSuppliers`(66)·
`ifrs-full_TradeAndOtherPayablesToTradeSuppliers`(51)·`dart_ShortTermOtherPayables`(13)·
`dart_LongTermTradeAndOtherNonCurrentPayables`(11)·`ifrs-full_NoncurrentPayables`(6).
비유동 개념 2종도 포함하지만 std_v3의 `_CURRENT_STRICT`(R15)와는 무관한 별도 코드경로라
문제 없음 — Gate B(`audit_fields()`)는 `val in won_vals`(집합 멤버십) 판정이라 후보 추가는
원칙적으로 단조 개선(기존 PASS를 FAIL로 되돌릴 수 없음).
`ifrs-full_CurrentTaxAssets`(1건, 아이텍)는 의미상 매입채무와 무관해 매핑하지 않음.

**부수발견·가드**: 매핑 직후 31개사 scoped 재검증에서 아이텍(00626011) 2025FY separate
1건이 **가짜 PASS**로 바뀌는 걸 발견 — 이 행은 std_v3 자체에 진짜 버그가 있다
(`trade_payables=0` 저장, 원문은 5,068,265,299원, `ifrs-full_TradeAndOtherCurrentPayables`
separate 라인). 새로 매핑한 `ifrs-full_NoncurrentPayables`가 이 필링에서 우연히 값=0(비유동
매입채무 없음, 정상)이라 `won_vals`에 0이 섞여 `db_won=0`과 우연일치 — 수정 전엔 정확히
fail_a로 잡히던 진짜 버그가 가려질 뻔했다. `face_audit.py`에 curated 4-튜플 제외집합
`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`(R16~R22와 같은 원칙, 이 1건만) 추가 —
`audit_fields()`가 이 행에서만 값=0 후보를 후보집합에서 제거해 기존 fail_a 노출을 보존.
148행 중 `db_won==0`인 유일 케이스(전수 확인, 나머지 147건 무관).

**검증**: pytest 31 passed(`test_concept_map.py`+`test_face_audit.py`) + 31개사 scoped
Gate B 재검증(`gateb_audit.py --source v3 --corp-file <31개사> --recheck`, 가드 전/후 2회) —
trade_payables fail_a 148건 중 147건 해소(가드 대상 1건은 fail_a 유지 확인, DB 직접 조회로
`fail_detail` 재현), 남은 fail_a 3건은 전부 이 fix와 무관(00149354 separate 2건=원래
scope 밖, 00349732 FY2024=원래 UNRESOLVED 별개 이슈) — 회귀 없음. `dart_ShortTermOther
Payables`/`LongTermTradeAndOtherNonCurrentPayables` 표본(딥노이드·지앤비에스에코·
한국정보인증) pass 전환 개별 확인.

**근거**: 메모리 `gateb-reader-concept-gap-scan-2026-08-15` · `scripts/probe_gateb_reader_
concept_gap_2026-08-15.py`(결과 CSV 포함) · `fin2/taxonomy/concept_map.py` ·
`fin2/audit/face_audit.py`(`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`).

---

## R24. 계층3 `combine.py::_map_rows()` — `is.controlling_ni`/`is.noncontrolling_ni`
구조기반 후보보강(structural candidate injection), mismap 하위메커니즘 Phase 1

Gate B `controlling_ni` fail_a 그룹A(78건)를 원문대조로 재분류하니 단일 원인이 아니라
최소 3갈래였다(`gateb-controlling-ni-groupa-rootcause-2026-08-15` 메모리): ①라벨오귀속
(mismap, 51건) ②완전미매핑(~24건) ③5dbecac 항등식 안전망 자체 오류(3건). 이 R24는 ①만
다룬다.

**근본원인**: `_map_rows()`가 report_lines 라벨을 AccountMapper로 canonical에 매핑할 때
`section_path`(섹션 구조)를 전혀 안 쓰고 라벨 텍스트만 본다. 원문이 이 가정을 두 방식으로
깨뜨린다 — (a) 지배지분 귀속 행이 상위 라벨을 그대로 재사용(삼성전자: `분기순이익의 귀속`
섹션의 지배지분 행 라벨이 그냥 `분기순이익`, ACODE는 정확히
`ifrs-full_ProfitLossAttributableToOwnersOfParent`) → `is.net_income`으로 오귀속.
(b) fuzzy 매칭이 `지배`/`비지배` 방향을 헷갈림(동성케미컬: `지배지분 당기순이익`이
`is.noncontrolling_ni`로 오귀속). 결과: `is.controlling_ni` 후보풀엔 오답(총포괄손익
섹션 값) 단 1개만 남아 `_resolve()`의 `_NI_ATTRIBUTION_CANON` 분기가 그대로 자동확정 —
5dbecac(2026-08-12)의 항등식 안전망(`_resolve_ni_attribution`)은 `conflicts`에 걸린
경우만 호출되므로 **호출 자체가 안 됨**(5dbecac이 고친 다중후보 오선택과는 다른, 더 앞선
선행조건 실패).

**구현**: 새 선택로직을 만들지 않는다. `_ni_attribution_structural_candidates()`
(`fin2/layer3/combine.py`)를 신설해 `_map_rows()`가 반환 직전에 호출 — 라벨이 아니라
섹션 구조로 지배/비지배 귀속 행을 식별한다: `section_path`에 `귀속`+`순이익` 포함,
`포괄` 미포함(당기순이익 귀속 섹션만, 총포괄손익 귀속 섹션은 명시적으로 배제)인 섹션에서,
라벨에 `비지배`가 든 행이 정확히 1개·안 든 행이 정확히 1개일 때만 발동. 그 값들을
`is.controlling_ni`/`is.noncontrolling_ni` 후보풀에 **추가만**(대체 아님) 하고, 나머지는
이미 검증된(유닛테스트 12개) `_resolve()`→`_resolve_ni_attribution()` 파이프라인이 그대로
처리 — 새 오답을 낼 수 있는 새 코드경로를 만들지 않는다는 뜻. H1/Q3는 `_map_rows()`와
동일한 cumulative-only 컨벤션 적용(중복행으로 섹션모양이 깨지는 것 방지).
`stage="structural"`을 `_STAGE_RANK`에 `fuzzy`와 동률(최하위)로 등록 —
`_top_stage_corroborated()`의 동점처리에서 실제 라벨매칭을 절대 앞지르지 않게 함.

**측정 커버리지**: 읽기전용 사전검증(mismap 51건)에서 구조규칙 단독 32건(63%) 오탐 0건.
실제 `combine_full()`→`_resolve()`→`_resolve_ni_attribution()` 전체 경로(기존 EBT유도·
nci=0·epsilon 폴백까지 함께 작동)로는 그룹A 78건 중 **48건 정답 수정**, 회귀 0(신규NULL
0·제3의 오답 0). 부수효과(범위 밖, 측정만): 같은 규칙이 완전미매핑 24건 중 11건, 안전망
자체오류 3건 중 1건도 부수적으로 회복.

**백필**: `scripts/build_std_v3.py --corp <35개사>`(그룹A 소속 corp, 3,054행, 59초) +
`scripts/gateb_audit.py --source v3 --corp-file <35개사> --recheck`(4,190행 재감사) —
그룹A 78건 중 48건 해소·30건 잔존(Phase 2 범위, 미해결) 확인. "신규 fail_a 3건"으로 보였던
것은 전부 db_won 불변(제 fix와 무관한 사전존재 fail_a — KBI메탈 2025H1=그룹B 부호불일치,
제이스코홀딩스 2건=`AXIS_EXCLUDED_UNMAPPED`, Gate B 리더측 별개 이슈)로 확인, 진짜 회귀
아님. 전체 pytest 517→522 passed(+5 신규, 무관 1건 기존 실패 `test_lxintl_facility_
table_dropped` 그대로).

**남은 범위(Phase 2, 미설계)**: mismap 잔여 19건(섹션명에 `순이익` 없이 라벨에 `귀속`
텍스트만 있는 경우·귀속섹션이 1행뿐인 경우·컴팩트 단일라벨 포맷 등 서로 다른 패턴) ·
완전미매핑 24건 중 13건 · 안전망자체오류 3건 중 2건 · 그룹B(7건, 부호불일치, 무관 별도
메커니즘).

**근거**: 메모리 `gateb-controlling-ni-groupa-rootcause-2026-08-15` ·
`gateb-controlling-ni-mismap-design-2026-08-15` · 설계문서 `docs/plans/
std_v3_controlling_ni_mismap_structural_fix_design_2026-08-15.md` ·
`fin2/layer3/combine.py::_ni_attribution_structural_candidates` ·
`fin2/tests/test_combine_ni.py`.

---

## R25. Gate B `face_audit.py::_ni_attribution_structural_candidates()` — `is.controlling_ni`/
`is.noncontrolling_ni` 구조기반 후보보강, raw XML 독립 재구현(R24 의 발상을 Gate B 쪽에 이식)

R24(std_v3 쪽)와 **같은 근본원인**이 원문을 직접 읽는 Gate B 리더에도 독립적으로 있었다
(`gateb-controlling-ni-new30-rootcause-2026-08-15` 메모리 §1-B): 일부 필터社가 지배/비지배
귀속 행에 회사고유 확장 ACODE(`entity{corp}_...`)를 쓰고, 표준 `ifrs-full_`/`dart_` ACODE는
총포괄손익 귀속 절·SCE·EPS 행에 오태깅해놓는다. `read_report_face_xbrl()`의
`_XBRL_PREFIXES` 필터가 확장 ACODE를 애초에 후보 풀에서 배제하므로 정답 후보 자체가
없다 — std_v3 데이터(db_won)는 항상 정답이었고, Gate B(report_won)가 오답이었다.

**구현**: `fin2/layer3/combine.py::_ni_attribution_structural_candidates()`(R24)를
모듈 재사용이 아니라(face_audit 의 파이프라인 독립성 원칙, 모듈 docstring) **raw XML
TR 시퀀스 위에 독립 재구현**. `read_report_face_xbrl()`이 만든 `FaceLine` 리스트 끝에
후보만 추가(대체 아님 — `audit_fields()`의 PASS 판정이 "후보 집합에 db_won 있으면 PASS"
라 넓히기만 해도 충분, 단조 개선). 상태기계:
1. **앵커(섹션 시작)**: 아직 섹션 밖일 때, TR 라벨이 `^당?(기|분기|반기)순(이익|손익)`로
   **시작**하면(예: `당기순이익(손실)`·`분기순이익(손실)의귀속`·`반기순손익`·
   `당분기순손익` — 필터社마다 표현이 갈림, 코렌텍은 분기별로도 다르게 씀) 그 행(헤더든
   실값행이든)을 앵커로 섹션 진입. `법인세비용차감전순이익(손실)`(세전이익, 뒤에 귀속
   분해가 안 옴) 같은 상위 소계가 오매칭되지 않도록 접두어 전체일치로 좁힘(느슨한
   부분일치 `순이익|손익` 는 코아시아씨엠 FY 케이스에서 실측 회귀 — 아래 검증 참고).
2. **회원 판정**: 섹션 안에서는 앵커 재판정을 하지 않는다(멤버 행 중 일부가 자체
   서브분해를 가져 `손익` 텍스트만으로는 새 앵커와 구분 안 됨 — 코렌텍의
   `계속영업분기순손익`/`중단영업분기순손익`이 실측 사례). 라벨에 `지배`가 있는 행만
   회원 후보(`비지배` 포함 여부로 controlling/noncontrolling 판정), 값이 없는 라벨행도
   회원으로 카운트(NCI 미태깅 필터社에서 "정확히 1개씩" 판정이 깨지지 않게).
3. **종료**: `비지배` 회원 1개·비`비지배` 회원 1개가 모이는 즉시 종료·후보추출("가장
   가까운 매치"가 곧 정답이라 뒤쪽 무관 표를 안 봄). 안전판으로 `_MAX_SECTION_SPAN`(20행)
   초과 시 강제종료(모양이 안 맞으면 짐작 없이 폐기).

**검증**: 원설계 문서의 24행(7개사: 코아시아씨엠·이노메트리·진영·모비데이즈·유니온·
코렌텍·판타지오) 전수 fail_a → pass 전환(SQL 재확인 잔여 0건). 구현 도중 3차례
실측 회귀 발견+수정(코아시아씨엠·이노메트리·코렌텍 세 회사가 서로 다른 레이아웃 — 상세는
`fin2/audit/face_audit.py::_ni_attribution_structural_candidates` 도크스트링). `pytest
tests/ fin2/tests/` 522 passed(무관 기존 실패 1건 `test_lxintl_facility_table_dropped`
불변). 40개사 무작위표본 회귀검증: fail_a 총량 불변(15=15), controlling_ni 관련 회귀 0건
(내 변경은 이 두 canonical 에만 후보를 추가하는 구조라 다른 필드는 건드릴 수 없음).
`docs/plans/gate_b_facereader_controlling_ni_fix_design_2026-08-15.md` §2-B.

**이번 범위 밖**: 같은 30건 중 ①FX표시통화(두산밥캣 6행)는 별개 메커니즘 — R26(아래)으로
구현 완료. 그룹A mismap 잔여19건(Phase2, std_v3 쪽) 도 무관.

---

## R26. Gate B `face_audit.py` — FX 표시통화(두산밥캣) curated pending 강등, 옵션 B
(2026-08-15)

R25 와 같은 30건 조사 중 발견된 ①FX 표시통화 메커니즘(설계문서 §1-A). 두산밥캣
(01032486) **연결**재무제표만 표시통화가 USD 다(원문 각주: "지배기업의 기능통화는
대한민국 원화이며, 연결재무제표는 달러(USD)로 표시"). Track A(XBRL)는 ADECIMAL 로
단위만 환산하고 통화는 검사하지 않아 USD 원값을 그대로 원화로 취급 → `report_won` 이
그 필링의 **전 필드**(22개 전부)에서 구조적으로 어긋난다. `std_v3`(db_won)은 DART 가
USD 표시 필터社에 요구하는 필수 별첨 "원화기준 재무정보"(서울외국환중개 매매기준율
환산표, 비XBRL 참고표)를 정확히 읽어와 이미 원문대조로 확인됐다(6/6행 백만원 단위까지
일치, 설계문서 §1-A).

**전수 스캔**(NAS+SD카드 dart_data 양쪽 독립·교차검증): "원화기준 재무정보" 계열 문자열
매치 5개사 중 4개사(딥커머스·씨엑스아이·JTC·소마젠)는 `corporations`/`face_audit` 자체에
행이 없는 유니버스 밖 외국기업([[foreign-corps-excluded]] 대상) — Gate B 영향 0.
실제 대상은 **두산밥캣 1개사·연결 6행뿐**(2024FY·2025FY·2025H1·2025Q1·2025Q3·2026Q1).

**구현(옵션 B, 저비용 pending 강등)**: 두산밥캣 1개사·6행이라는 규모(옵션 A "Track D
신설"의 투자 대비 회수가 작다는 판단, 설계문서 §2-A)로 인해 curated key 세트를
`fin2/audit/face_audit.py::_FX_PRESENTATION_CURRENCY_KEYS`(4-튜플
`(corp_code, fiscal_year, fiscal_period, basis)`, R21/R23 와 같은 원칙 — 블랭킷 규칙
금지)로 등록. `audit_std_row()`가 이 키와 일치하는 행을 만나면 정상 face 대조를 아예
건너뛰고 그 행의 전 필드를 새 pending 사유 `FX_PRESENTATION_CURRENCY`로 표시(값 오류
감사가 아니라 통화가 달라 비교 자체가 성립하지 않는 케이스, `_PENDING_REASONS`에 등록).
별도(개별) 재무제표는 원화 그대로라 `basis='consolidated'` 행만 대상 — 별도 재무제표
행은 이 키에 안 걸려 기존 로직 그대로 감사된다.

**검증**: `python scripts/gateb_audit.py --source v3 --corp 01032486 --recheck` 재감사
결과 대상 6행 전부 `gate_status=pending`·`pending_detail={'FX_PRESENTATION_CURRENCY': N}`
로 전환(N=그 행의 in-scope 필드 수), 두산밥캣 전체 fail_a 6→0(`fail 0`). 같은 회사의
별도(separate) 재무제표 행·다른 기간 연결 행은 영향 없음(기존 pass/pending 그대로 —
curated key 는 정확히 6개 4-튜플만 매치하므로 다른 corp·행에는 원천적으로 도달 불가).
`pytest tests/ fin2/tests/` 522 passed(무관 기존 실패 1건 `test_lxintl_facility_table_
dropped` 불변, R25 와 동일). `docs/plans/gate_b_facereader_controlling_ni_fix_design_
2026-08-15.md` §2-A.

---

## R27. `fin2/extract/report_lines.py` — EPS(주당손익) 행 판정의 라벨 부분문자열
오판 수정, 값 크기 게이트(KBI메탈, 2026-08-15)

R24~R26 과 달리 이번엔 Gate B(원문 독립 재추출기)가 아니라 **std_v3 본류(Layer 2
`report_lines.py`)의 진짜 데이터 버그**였다 — KBI메탈(00158024) 4개 기간에서 std_v3
(db_won)가 틀리고 Gate B(report_won)가 맞는, 이 population 안에서 유일한 역방향
사례(그룹B/C 잔존 4건 원문대조 중 발견, 설계문서 `docs/plans/gate_b_controlling_ni_
groupbc_kbimetal_eps_label_trap_fix_design_2026-08-15.md`).

**근본원인**: EPS 행 판정이 라벨 안 **우연한 부분문자열**(`"주당" in label`)로만
이뤄져서, "지배주주당기순이익(손실)"/"비지배주주당기순이익"(= "지배"+"주주"(주주들)+
"당기순이익", 우연히 "주당" 부분문자열이 생김) 같은 NI귀속(총액, 원 단위) 라벨이
EPS(원/주)로 오판됨. 그 결과 (a) 정상 IS본문 추출 경로(`_emit_section_lines`)에서
그 행이 통째로 드롭되고 (b) EPS 전용 경로(`_emit_eps_lines`)로 잘못 들어가서는 그
경로의 "당기/전기 2열" 가정이 실제 4열(3개월/누적×당기/전기, H1·Q3 필링) 구조와
안 맞아 엉뚱한 열(3개월, 비누적)이 "누적" 딱지 달고 저장됨 → `_is_loadable()`(col_
index=0만 저장 정책)이 그 잘못된 열만 남김. 결과: 정답 후보가 `report_lines`에
**아예 없어져서** combine.py 의 어떤 후보선택/안전망(`_resolve_ni_attribution` 항등식
체크 포함)도 못 구함 — R24/R25 류 "후보를 넓히기만 한다" 전략은 넓힐 후보 자체가
없어서 안 통하는 케이스.

**왜 라벨 텍스트 규칙으로 못 고치나**(실측 확인, 설계문서 §4): "보통주주당이익"
(=보통주+주당이익, 진짜 EPS)과 "지배주주당기순이익"(=지배+주주+당기순이익, 버그)은
**서로 다른 조어구조에서 나온 문자열 레벨 동일 부분열**이라 정규식으로 원리적으로
구분 불가. "주당기"(주당+기) 뒤 글자로 가르는 것도 기각 — `기본주당기순이익`류
(DART 관행상 매우 흔한 정상 EPS 표기)가 대량으로 걸림.

**구현**: 값 크기 게이트. `_EPS_MAX_PLAUSIBLE_WON = 10_000_000`(실측 확정 — 2015년
이후·깨끗한 라벨·알려진 버그회사 제외 시 진짜 EPS 실측 최댓값 5,890,065원, 1.7배
여유). `_looks_like_eps_amounts()` 헬퍼를 `_emit_section_lines`의 스킵 조건(라벨에
"주당" 있어도 금액이 비현실적으로 크면 스킵 안 함 → 본류가 처리)과 `_emit_eps_lines`
의 진입 게이트(금액이 크면 그 TR 자체를 emit 안 함 → 본류로 흘려보냄) 양쪽에 적용.
코드는 **전역**(회사 curated 아님 — 값 크기라는 독립검증 신호로 좁힌 게이트, 블랭킷
규칙 아님)이지만 실제 데이터 변경은 재추출한 회사에만 반영된다. `_emit_section_lines`
(본류)는 4열(3개월/누적) 레이아웃을 이미 올바르게 처리하는 것으로 확인돼(`cum_map`
메커니즘) 그쪽 로직은 안 건드림 — "게이트만 좁히면" 충분.

**검증**: `scripts/reload_report_lines_corp.py --corp 00158024` 재추출 →
`scripts/build_std_v3.py --corp 00158024` 재빌드 → `gateb_audit.py --recheck` 재감사.
대상 4개 기간(2024FY·2025Q1·2025H1·2025Q3) `controlling_ni` 값이 원문(XBRL
`ifrs-full_ProfitLossAttributableToOwnersOfParent`) 과 정확히 일치하도록 수정 확인,
fail_a 4→0. `pytest tests/ fin2/tests/` 522 passed(무관 기존 실패 1건 불변). 다른
회사 표본(00121941) in-memory 추출로 정상 EPS 계속 올바르게 분류되는 것도 확인
(단조성). **부수 발견**: 같은 재빌드로 KBI메탈의 다른 17개 과거 기간(2019~2024,
대부분 Track B/비XBRL 구서식)이 `pass`→`fail_b`로 전환됨 — 원문대조(2023Q1·2024H1
표본)로 db_won 이 전부 **더 정확해졌음**을 확인(예: 2024H1 1,744,628,069 원문 정확
일치). report_won 쪽이 안 맞는 건 Gate B `face_audit.py` Track B(텍스트 휴리스틱)
리더의 **별개·기존 결함**으로 추정(이 필링들은 ACODE/ACONTEXT 없는 순수 텍스트
표라 Track B 경로를 탐) — 이전엔 db_won 도 같이 틀려서 우연히 일치(숨은 false
PASS)했던 것으로 보임. `fail_b`는 설계상 비차단(REVIEW)이라 메인뷰엔 영향 없음.
**이 Track B 결함 자체는 이번 수정 범위 밖 — 별도 조사 필요**(다음 세션 후보).

**이번 범위 밖**: 쿠콘(01311055)·피에스케이(01365825) — 같은 라벨패턴 보유하나
원문 rcept 파일열람 문제로 미착수(현재 fail_a 0, 저긴급). `00269852`류 레거시
텍스트블럽 패턴(K-GAAP 2003~2007년대) — 이번 4열 XBRL 구조와 무관, 별도 트랙.

---

## R28. `fin2/extract/report_lines.py` — K-GAAP 구서식(00269852류) 헤드라인
당기순이익 행의 EPS 오판, curated skip-gate (2026-08-16)

R27이 "이번 범위 밖"으로 남겨둔 `00269852`류 K-GAAP 구서식(2003~2010년) 텍스트블럽
패턴의 후속. 설계문서
`docs/plans/report_lines_eps_kgaap_legacy_label_unit_fallback_fix_design_2026-08-15.md`.

**근본원인**(R27과 같은 계열, 다른 서식): K-GAAP 구서식 IS 표의 "ⅩⅢ.당기순이익
(주당순이익: 당기 108원, 전기 181원)" 같은 **헤드라인 당기순이익 행에 EPS 노트가
괄호로 통짜 곁들여진 라벨**이 "주당" 부분문자열 때문에 `_emit_eps_lines`로 잘못
들어간다. 라벨 자체엔 단위선언이 없어 `unit=1`(원)이 적용되고, 표가 천원/백만원
단위면 값이 1,000배~100만배 과소 저장된다(R27 값크기 게이트 도입 전엔 무조건
emit, 도입 후엔 대부분 게이트에 걸려 **EPS 행 자체가 안 생기고 본류 후보도 없어져
결측**됨 — §설계문서 §4-E-A 실측).

**왜 일반규칙(라벨 단위선언 없으면 표 단위로 폴백)이 아니라 curated 인가**: DB
전수 실측(설계문서 §2) — 라벨에 단위선언 없는 EPS-경로 행 168,579건 중 표가
천원/백만원인 위험군 9,495건의 절대다수(≈7,258건+)가 **정상 EPS 라벨**(DART 관행상
EPS는 표 전체 단위와 무관하게 항상 원/주). 일반규칙을 적용하면 이 정상 값들을
1,000~100만배 부풀려 원래 버그(추정 1,417행)보다 훨씬 큰 규모의 회귀를 만든다.
라벨 텍스트 규칙(헤드라인 단어·임베드 "숫자+원" 토큰·라벨 길이)도 전부 오탐/누락이
있어 단독 최종판정 불가(R27 §4와 동일 결론 재현).

**구현 — curated 허용목록 + skip 메커니즘**(R16/R17/R20/R21/R23/R24/R27 계열):
- `(rcept_no, statement, basis, table_seq, label_raw)` 5-튜플 키
  **2,205개**(1,858 rcept_no / 1,549 filing / 286개사 / FY 1999~2008)를
  `fin2/extract/data/eps_kgaap_headline_not_eps_keys_2026-08-15.json`에 데이터파일로
  둠(리터럴 616KB라 소스에 안 박음). 생성: `scripts/build_eps_curated_override_
  final_2026-08-15.py`(위험군을 std_v3 독립 총계 교차검증(CONFIRMED 271건) +
  텍스트신호(LIKELY 1,947건)로 분류) → `scripts/purge_eps_curated_false_positives_
  2026-08-15.py`(오탐 13건 퇴출, 규칙 G∪L, 근거 아래).
- `_emit_eps_lines`에 라벨 확정 직후 **3줄** skip 게이트:
  `if (rcept_no, statement, basis, table_seq, label) in _EPS_KGAAP_HEADLINE_NOT_EPS_KEYS: continue`.
  동작은 "표 단위로 재계산"이 아니라 **"이 행은 EPS가 아니다 → EPS 패스 skip,
  본류(`_emit_section_lines`)에 위임"**이다 — 폴백 재계산안은 R27 값크기 게이트와
  충돌해 99.5%가 결국 emit 자체가 안 되므로(설계 §4-E-A), 의도를 그대로 쓰는 쪽이
  정직·단순하고 `table_unit` 배선도 불필요해진다.
- **무손실 불변식**: 본류의 대응 가드(`"주당" in row.account_name and
  _looks_like_eps_amounts(row.amounts): continue`, R27)는 값크기 기준이라, curated
  키는 `|raw × table_unit| > 1,000만원`인 행만 담아야 skip된 행을 본류가 반드시
  줍는다. 퇴출 규칙: **G**(게이트생존군, `|raw×table_unit|≤1,000만원`이면 불변식
  위반이라 퇴출) ∪ **L**(라벨 선두 토큰이 주당/기본주당/희석주당/보통주주당으로
  시작 & std_v3 교차검증 미확인이면 진짜 EPS 오탐 가능성 → 퇴출) = 13행/5개사.

**부수 발견·수정 — 공용 함수 `parser/xml/table_extractor.py::_header_rule_name`
"기수" 규칙 부분일치 버그**(R28 검증 중 발견, 같은 세션에 동시 수정): 이 규칙이
`re.search(r'제\s*\d+\s*기', text)`(부분일치)라서, curated 헤드라인 라벨처럼 "제54기:
1,713원" 같은 EPS 노트를 담은 **실데이터 행**이 표 헤더(열 기수 표기)로 오분류돼
`extract_rows`에서 통째로 드롭됐다 — EPS 패스(`table_direct_rows` 직접 순회)는 이
필터를 안 거쳐 지금까지 우회로로 이 행들을 잡아왔는데, R28이 그 우회로를 skip시키자
"틀린 값"이 "행 자체 소실"로 바뀌는 무손실 불변식 위반이 curated 459/2,205키
(20.8%)에서 드러났다. 2026-07-30에 이미 같은 계열의 "날짜" 규칙 부분일치 버그가
고쳐진 전례가 있었으나 "기수" 규칙은 그 교정을 안 받은 상태였다. **수정**: 진짜
기수 헤더 셀("제 21기(당기)", "제59기 기초(2016.1.1)")은 "원"/"%"를 포함하지 않고,
오염된 데이터 행(배당금·EPS 노트)은 전부 포함한다는 실측 신호로 가른다 —
`re.search(r'제\s*\d+\s*기', text) and not re.search(r'원|%', text)`. `note_lines`
실측(header_hint='기수')으로 검증, 회귀 테스트
`fin2/tests/test_header_rule_name_r28.py`. **★공용 함수라 파급범위가 R28의 286개사
보다 훨씬 넓다**(BS/IS/CF/주석 전체) — 이번엔 R28 대상 286개사 재추출에만 반영,
**전사 소급 백필은 별도 후속 작업**(미착수, `docs/runbook_new_parser_pipeline_
integration.md` 절차 필요).

**검증**(설계문서 §8 Phase 5): 286개사 `reload_report_lines_corp.py` 재추출(전
연도) → `build_std_v3.py --year-min 1999` 재빌드, 헤더규칙 수정 후 **재실행**(첫
실행은 459/2,205키 미달로 재작업).
- curated 2,205키의 EPS-경로 행 2,205→**0**(완전 소멸, 의도한 효과).
- 무손실 불변식(본류 행 생성) **2,192/2,205(99.4%)**. 잔여 13건은 헤더규칙과
  무관한 **별도 구조 이슈**(`extract_rows`가 특정 표의 물리적 마지막 행을 드롭하는
  것으로 추정, 원인 미확정) — 사용자 승인 하에 후속트랙으로 분리, 이번 범위 밖.
- 원문대조 5건(CONFIRMED 2 + LIKELY 3): 본류가 계산한 값이 curated 생성 스크립트의
  단순 순차파싱 예측치와 다른 경우(3/5)가 있었는데, 직접 원문·CF표 대조 결과 **본류
  값이 더 정확했다** — 반기/3분기 2단 헤더(3개월/누적) `cum_map` 로직을 본류는
  올바르게 적용하지만 curated 생성 스크립트의 단순 파싱은 "당기"를 첫 번째 셀(3개월
  치)로 잘못 가정했었다(예: 00117337 2004H1, 본류 513,810천원 = CF표의 "당반기"
  누적값과 정확 일치, curated 예측 6,369,007천원은 당2분기 3개월치로 오분류).
- 퇴출 13건은 재추출 후에도 EPS 값·행 불변 확인(오탐 제외가 실제로 지켜짐).
- std_v3 diff: `net_income`/`controlling_ni` 등 다수 필드 변경 — 대부분 **R27 재추출
  부수효과**(이 286개사가 R27 이후 처음 재추출됨, 설계 §4-E-C) 및 재추출 기간 중
  데일리 파이프라인이 유기적으로 수집한 신규(2026년) 필링. Gate B
  `--recheck`(net_income/controlling_ni 변경 57개사, `--source v3`): R28 대상 기간
  (FY1999~2008)은 fail_a/fail_b **0건**(전량 pending, 예년과 같은 패턴). 전체
  범위(FY1999+) 재검증의 fail_a 7건/fail_b 73건은 표본대조 결과 **전부 2022~2026년
  최근 필링**(처리 중 유기적으로 수집된 신규 공시) 소관으로, 커브 대상(FY1999~2008)
  과 무관함을 개별 확인.
- `pytest tests/ fin2/tests/` 527 passed(무관 기존 실패 1건 불변, R28 신규 테스트
  3개 + 헤더규칙 수정 신규 테스트 2개 포함).

**후속트랙**(미착수, 범위 밖): (1) 잔여 13/2,205키 무손실 불변식 위반(별도 구조
이슈, 원인 미확정). (2) `_header_rule_name` "기수" 규칙 수정의 **전사 소급
백필**(R28 대상 286개사 밖 — BS/IS/CF/주석 전체, 배당주석 등에서 같은 부분일치
버그로 드롭된 행이 있을 수 있음). (3) `net_income` 결측 복구 가능성(설계문서 §3/§6,
LIKELY 티어 1,947행 중 상당수가 겹칠 가능성, 표본 조사만 됨).

---

## R29. `fin2/layer3/combine.py` — K-GAAP 구서식 헤드라인 NI `net_income` 결측 복구
(재추출 없이 계층3 매핑만, 2026-08-16)

R28 후속트랙 T3(구 "후속트랙 N"). 설계문서
`docs/plans/eps_r28_followup_tracks_design_2026-08-16.md` §4/§6.

**근본원인**: R28이 K-GAAP 구서식(00269852류) 헤드라인 당기순이익 행("ⅩⅢ.당기순이익
(주당경상이익:...) (주당순이익:...)")을 EPS 오판에서 구제해 본류로 정상 전사하게
고쳤지만, 그 라벨은 `account_mapper`가 **거대 병합 텍스트**라 `confidence<0.88`로
탈락시켜 애초에 candidate pool에 못 들어온다(`cands["is.net_income"]` 자체가 비어
있음) — 재추출이 아니라 **계층3 매핑 한 곳만** 고치면 되는 이유. 재측정(설계문서
§4-1): curated 2,205키 population(1,840셀) 중 net_income NULL **1,187셀(64.5%)**,
그중 **1,142셀(96.2%)**이 이미 `report_lines`에 R28 헤드라인 행을 값째로 갖고 있었다.

**구현 — curated 재키잉 + 후보주입**(R16/R17/R20/R21/R23/R24/R27/R28 계열):
- R28 curated 5-튜플 키(rcept_no 기반)를 **`(corp_code, fiscal_year, fiscal_period,
  basis) → [label_raw, ...]`**로 재키잉(1,840그룹, 라벨 최대 2). `_map_rows()`(계층3
  후보 매핑 지점)엔 `rcept_no`가 없고(정본+델타 패치 설계상 의도적) 셀 병합 키가
  `(statement, basis, col_index, section_path, label_raw)`라서 원본 5-튜플을 그대로
  못 쓴다. 재키잉 손실 0(1,840셀과 정확히 일치, rcept 미매칭 0) 실측 확인.
  생성: `scripts/build_ni_recovery_keys_2026-08-16.py` →
  `fin2/extract/data/eps_kgaap_ni_recovery_keys_2026-08-16.json`.
- `_kgaap_headline_ni_candidates(rows, corp, fy, period, basis)` 신설
  (R24 `_ni_attribution_structural_candidates`와 같은 모양) — 재키잉 라벨과 정확히
  일치하는 IS 행만 `is.net_income` 후보로 주입(`stage="structural"`). 대상 canonical은
  **`is.net_income` 하나만** — `is.controlling_ni`는 채우지 않는다(K-GAAP 구서식엔
  지배주주 개념 자체가 없는 경우가 많아, 채우면 "없는 개념을 만드는" 위험).
- `_map_rows()`에 선택 인자 `corp=None, fy=None` 추가(기존 호출자는 무변경 no-op).
  `"IS" in stmt_set` 가드 안에서 **`cands.get("is.net_income")`가 이미 있으면
  주입하지 않는다**(보수적 기본값 — 이 population은 정상경로가 애초에 후보를 못
  만드는 경우가 대부분이라, 다른 경로로 이미 후보가 있다면 그쪽을 신뢰).
- 호출부 3곳(`collect_candidates()`·`combine_full()` 기본경로·basis fallback경로)에
  `corp=corp, fy=fy` 전달.

**단위테스트 6개**(순수·DB 비의존) — `fin2/tests/test_combine_kgaap_ni_recovery_r29.py`:
curated 라벨 주입 확인, corp/fy 없으면 no-op, 라벨 텍스트 불일치 시 미주입(블랭킷
아님), 회사 불일치 시 미주입, 기존 후보 있으면 미주입(보수적 기본값).

**백필**: `build_std_v3.py --corp <286개사> --year-min 1999`(286개사·51,403행·
1,267초). 재추출 아님 — `report_lines` 완전 불변(체크섬 확인).

**검증**(설계문서 §4-8):
- curated population net_income NULL **1,187 → 34**(목표 ≤45 초과 달성).
- `report_lines` 286개사 체크섬 before/after **완전 일치**(계층2 불변, 의도대로).
- std_v3 대상 필드 diff: `net_income` 1,837행 + **`controlling_ni` 1,145행**(전부
  separate basis) 변경. controlling_ni는 T3가 직접 주입하지 않았지만, `net_income`이
  채워지자 `fin2/layer3/build.py:118-126`의 **기존(R29 이전부터 있던) 무조건 규칙**
  ("별도재무제표는 controlling_ni=net_income" — 회계정의) 이 자연히 따라 채운
  부수효과. `git diff`로 R29 변경분이 이 규칙과 무관함을 확인, 표본(00428251
  2003H1 separate) 원문대조로도 확인. 그 외 필드(revenue/total_assets 등) diff 0.
- Gate B: T3 대상 기간(FY1999~2008) 286개사는 gate_status 전량 `pending`(XBRL·Track B
  소스 자체가 이 시대엔 없어 감사 불가 — T4 설계문서 §5-3과 동일 사실) →
  net_income을 몇 건 채우든 fail로 넘어갈 경로가 없어 fail_a 증가 **구조적으로
  불가능**. 전체기간 fail_a 46건은 전부 FY2024~2026(재키잉 데이터가 애초에
  FY1999~2008만 있어 도달 불가 — 데일리 파이프라인 신규수집 소관, R29와 무관 확인).
- `pytest tests/ fin2/tests/` **533 passed**(527 기존 + R29 신규 6, 무관 기존 실패
  1건 `test_biz_section.py::test_lxintl_facility_table_dropped` 불변).

**후속트랙**(미착수, 범위 밖): 잔여 34셀 NULL(대부분 "2-라벨 그룹" — 같은 기간에
헤드라인 NI 행이 2개, 값이 달라 conflict로 보류된 케이스. 결측>오염 원칙대로 정상
동작, 추측하지 않음).

---

## R30. `fin2/extract/text.py`/`statement_titles.py` — 표제/계정구분 중복 마커가
단위 룩백을 막던 버그 (2026-08-16)

R28 후속트랙 T4 M3(단위 배수 과대적용 22,720행 중 코드로 안전하게 고칠 수 있는 부분).
설계문서 `docs/plans/eps_r28_followup_tracks_design_2026-08-16.md` §5-6~§5-8.

**근본원인**: `declaration_text()`/`inherited_declaration_text()`가 단위 선언을 찾아
룩백할 때 "재무제표명을 만나면 멈춘다"(LVMC 회귀 방지 안전판, 남의 재무제표 단위를
훔치지 않기 위함)는 규칙을 지키는데, 표제표(단위 선언 보유)와 데이터표 사이에
**내용 없는 중복 캡션**(같은 재무제표 이름만 되풀이하는 형제, 또는 은행업 계정구분
괄호라벨 `(은행계정)` 등)이 끼는 서식이 실재한다 — 이건 "다른 재무제표로 넘어갔다"는
뜻이 아니라 **같은 재무제표 표제의 되풀이**일 뿐인데, 안전판이 이걸 구분 못 해
룩백이 여기서 멈추고 진짜 선언에 못 닿아 `doc_default`(문서 전체 기본단위) 최후
폴백으로 떨어졌다. `doc_default`가 이 표의 실제 단위와 다르면 값이 10⁶배 등으로
과대적용된다(T4 §5 "단위 배수 과대적용" 증상).

**실측(설계문서 §5-7-1, 667개 `doc_default` 그룹 전수 재파싱)**: 22,720행 중 이
메커니즘(M3)에 해당하는 건 **30그룹/288행(1.3%)뿐** — 나머지(M1 원문 자체가 선언과
실값이 모순·M2 로컬 선언이 진짜 없음)는 코드로 고칠 수 없는 정책 결정 대상이라
**범위에서 제외**하고 문서화만 했다(사용자 결정, T4-3). M3 30그룹은 13개사에
편중(57%가 3개사) — 전사적 패턴이 아니라 소수 회사·업종의 반복 서식.

**구현**:
- `fin2/extract/statement_titles.py`에 `_is_bare_structural_marker(txt)` 신설 —
  텍스트가 (a) 수식어(연결/별도/개별/반기/분기/중간/당/전) + 재무제표명(BS/IS/CF/SCE/
  이익잉여금처분계산서/결손금처리계산서) + 선택적 괄호 동의어뿐이거나(자간벌림 포함,
  예: "현 금 흐 름 표", "(3) 연결자본변동표(연결잉여금계산서)"), (b) 은행/보험업
  계정구분 괄호라벨(`은행계정`/`신탁계정`/`보험계정`/`특별계정`, 닫힌 목록)이면
  True. **기간·단위 등 다른 정보가 조금이라도 섞이면 False**(정규식이 끝까지 못
  먹으면 매칭 실패) — 표제표 자신(진짜 선언 후보)은 걸리지 않는다.
- `declaration_text()`의 (3)번 절(range 3→6, 스킵 반복 대비)과
  `inherited_declaration_text()` 둘 다, 텍스트 형제를 만났을 때 이 마커면 **건너뛰고
  계속**(`continue`) 하도록 최우선으로 배선. TABLE 형제(제목+단위가 한 표에 묶인 경우,
  LVMC 사고 발생 경로)는 손대지 않았다 — 이 함수는 **텍스트 전용 형제**에만 적용된다.

**단위테스트 9개**(순수·DB 비의존) —
`fin2/tests/test_declaration_lookback_bare_marker_r30.py`: 마커 판정 정오·안전판
유지(다른 정보 섞이면 여전히 경계)·기업은행류 은행계정 통합 시나리오·APPR 표제
반복 통합 시나리오·2단 연쇄 스킵·빈 단위선언은 여전히 채우지 않음(M2 오염 방지).

**백필**: `reload_report_lines_corp.py`로 13개사(M3 30그룹이 걸친 회사) 전체 이력
재추출(1,509 filing) → `build_std_v3.py --corp <13개사> --year-min 1999`. 재추출
필요(T3와 달리 계층2 결과 자체가 바뀜 — declaration_text 결과가 unit을 바꾸므로).

**검증**:
- report_lines(13개사): 541,468 → 541,704행(+236, doc_default→declared 전환으로
  일부 표가 다시 emit됨), 스코프 밖(전체 60,557,582→60,557,818) 정확히 동일 증가분만
  — 다른 회사 영향 0.
- 30그룹 중 **23그룹(76.7%)/288행 중 144행(50.0%) 실제 복구**
  (`unit_source: doc_default → declared`, `|value_won|>10¹⁵` 0건으로).
  나머지 7그룹은 화이트리스트 밖으로 **의도적으로 남겨둠**(회사명 단독 마커 1건·
  인용부호 안내문 1건·표제표 자체 단위선언이 빈 경우 다수 — 채우면 M2를 M3로
  오염시키는 것이라 하지 않음, 단위테스트로 회귀 확인).
- Gate B 재감사(13개사, fy≥1999): pass 1,383 / **fail_a 0** / fail_b 92 / pending 877,
  in-scope 일치율 93.8%. fail_b 92건은 전부 `cogs`(00108940, 2009~2024)·
  `revenue`(00149646, 2023~2024) — R30이 건드린 시대(pre-2010 K-GAAP 레거시 BS/CF/
  APPR/SCE)와 무관한 필드·시대라 R30 회귀가 아님(기존 결함으로 판단, 별도 트랙).
- `pytest tests/ fin2/tests/` **542 passed**(533 기존 + R30 신규 9, 무관 기존 실패
  1건 `test_lxintl_facility_table_dropped` 불변).

**후속트랙**(미착수, 범위 밖 — 설계문서 §6 T4-3에 문서화만): M1(11,150행, declared
인데 원문 선언 자체가 실값과 모순)·M2(10,914행, 로컬 선언 진짜 없음)는 계층2 원칙
("값 크기로 단위 추론 금지")상 코드로 고칠 수 없다 — quarantine 등 정책 결정 필요,
사용자가 방향을 정하지 않아 이번 트랙에서는 진행하지 않았다.

---

## R31. `parser/xml/table_extractor.py::_NUMBER_PATTERN` — 괄호 없는 순수
하이픈 음수("-N")를 "숫자 아님"으로 오판해 셀이 통째로 드롭되던 버그 (2026-08-17)

T21("(-)N" 이중마커)의 자매결함(부록A **T22**) — T21이 고친 건 `(-)N`뿐, 순수 `-N`은
그때도 지금도 미수정이었다. 설계문서 `docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md`.

**근본원인**: `_NUMBER_PATTERN`의 첫 대안 `^[\s\-─—―]$`는 대시 **한 글자**(공란 마커)만
잡는다. `"-466,274"`처럼 뒤에 숫자가 붙은 셀은 어느 대안에도 안 걸려 `_split_label_amounts`가
"숫자 아님"으로 판정해 **placeholder도 안 남기고 셀 자체를 드롭** → 뒤 컬럼이 배열 안에서
앞으로 밀린다. interim 2단헤더(3개월/누적) 표는 `cum_map`이 헤더 위치 기준인데 밀린 데이터
배열과 좌표계가 어긋나 **전기/무관 컬럼값이 당기 자리로 오emit되거나 당기값 자체가 유실**된다
— 결측(0행)보다 나쁨(틀린 숫자가 조용히 적재됨), T21과 동일한 성격. `parse_amount`는 순수
`-N`을 이미 정상적으로 음수 처리한다(`amount_normalizer.py`) — T21과 달리 **게이트만의 결함**.

**스코프 census**(Phase 1, 층화표본 259필링, `scripts/census_t22_hyphen_negative_2026-08-16.py`,
전 구간·모든 report_type 커버): 본문 BS/IS/CF 행식별자의 corrected(조용한 오염 교정) 0.25%·
new_value(신규값 등장) 0.27% — 표본상 corrected 8필링/259가 **전부 1995~2009 버킷**(2010+ 0건).
원문대조로 진짜 결함 교정임을 확인(예: 20031114000665 "감가상각누계액" 행 원문 셀이 실제로
`-765,846,474`, 종전엔 드롭됨). 이 규모가 "13건 복구"가 아니라 "전사 데이터 교정"에 해당해
⛔게이트 발동 → 사용자 재승인(2026-08-17) 후 Phase 2 진행.

**구현**: `_NUMBER_PATTERN`에 `r'^-[\d,]+\.?\d*$|'` 대안 1줄 추가(`(-)` 대안 **뒤**, 대시
한글자 대안과 뒤에 숫자를 요구해 충돌 없음). `report_lines.py:573`(`_grid_header_split`,
콤마 보존 문자열 검사)와 `table_extractor.py`(콤마 제거 문자열 검사) 양쪽 다 같은 `_NUMBER_PATTERN`
객체를 import해 공유하므로 **한 곳 수정으로 둘 다 반영**(T21 때와 달리 별도 배선 불필요 —
census 스크립트는 이 사실을 monkeypatch 검증으로 명시적으로 확인했다). `parse_amount`는
수정 불필요. `_split_label_amounts`의 `cell_stripped in ('-','—','')` 공란 폴백은 그대로 둠
(공란 마커 의미 보존).

**단위테스트 7개**(`fin2/tests/test_hyphen_negative_gate_r31.py`) — 패턴 매칭·8칸 전부 보존·
`parse_amount` 부호 왕복·회귀가드(대시 한 글자·"- 유동자산"·괄호음수/`(-)N`/△/▲/양수 불변)·
실측 원문(20031114000665) 기반 cum_map 밀림 재현(수정 전 패턴 monkeypatch로 오답, 수정 후
정답을 같은 테스트에서 직접 assert).

**표적 백필 스코프 확정에서 겪은 실수(중요, 재발 방지용 기록)**: Phase 1 census 대상이 전부
pre-2010이라 그 구간을 `grep -l -E '>-[0-9][0-9,]*(\.[0-9]+)?</T[DE]>'`로 넓게 프리필터한 뒤
프로덕션 함수(monkeypatch before/after)로 정밀 재확인하는 2단 깔때기를 썼다. **1차 grep이
macOS 기본 로케일(`LANG=ko_KR.UTF-8`)에서 EUC-KR 인코딩 파일(대부분의 2007년 이전 XML)을
잘못 스캔**(`-a` 플래그로도 못 고침 — 로케일이 유효하지 않은 멀티바이트 시퀀스를 만나면
조용히 매칭을 중단)해 116개사만 잡혔다. `LC_ALL=C`(바이트 그대로 매칭)로 재스캔하니
775개사로 3배 이상 늘었고, 정밀 재확인(전체 XML 파싱 재실행)에서도 775개사가 확정됐다.
**교훈**: 레거시(pre-2010) 원문을 텍스트 검색으로 스캔할 때는 `grep`에 `LC_ALL=C`를 반드시
명시할 것 — UTF-8 로케일에서는 `-a`(binary 취급 무시)만으로 부족하다.

**표적 백필**: 2라운드로 나뉨 — 1라운드(잘못된 116개사 프리필터 기반) 완료 후 로케일 버그
발견, 2라운드(delta 659개사)로 보정. 최종 **775개사**, `reload_report_lines_corp.py --year-max
2010`(fiscal_year≤2010만 — census가 2010+ 영향 0건임을 확인했으므로 표적 유지) +
`build_std_v3.py --year-min 1999`. 대량 배치가 백그라운드 실행시간 제한에 반복적으로 걸려
`reload_report_lines_corp.py`에 corp 경계 커밋을 추가(전엔 루프 끝에 한 번만 커밋 — 죽으면
전부 롤백)하고 ~100개사 단위로 청크 실행.

**검증**(Phase 6):
- 스코프 밖 불변(두 라운드 모두 exact match): 1라운드 — global 행 델타 = target 행 델타
  = 19,288, checksum 델타 정확히 일치. 2라운드 — 63,114행 동일 일치. **다른 회사 영향 0**이
  산술적으로 증명됨(집계로 끝내지 않고 delta 자체를 비교).
- BS 항등식 위반(T21 안전망) 감소: 1라운드 185→172(−13), 2라운드 950→914(−36) — 둘 다
  감소(T21 전례와 일치, 진짜 결함 교정의 신호).
- Gate B 재감사(대표표본, 이 세션): 775개사 전수는 `gateb_audit.py`가 이 세션 시간 안에
  못 끝낼 만큼 느려(기존 스크립트 성능 특성, R31과 무관 — corp 1개(00101044)가 36분+
  걸림) 대표표본(census 검증 8개사, 502행)으로 축소 — **fail 0 / fail_a 0**, in-scope
  일치율 100%.
- **Gate B 재감사(775개사 전수, 사용자 직접 실행, 2026-08-17)**: 43,864행 감사 —
  pass 3,860 / **fail_a 0**(차단 기준 통과) / fail_b 51(REVIEW) / pending 39,953,
  in-scope 일치율 98.7%. fail_b 51건 조사(집계로 끝내지 않고 원인 추적) — 전부
  `revenue`/`cogs`(+파생 `gross_profit`/`operating_income`/`net_income`, BS 결합행 1건)
  **concept-mapping 불일치**이지 R31이 고치는 값 유실/오emit 패턴이 아님. 22개사 중
  T22가 실제로 값을 교정한 (corp,fy,period)와 겹치는 건 10/51뿐, 그중 하나(00108940
  cogs 2009FY)는 **R30 문서에 이미 기록된 기존 미해결 항목과 정확히 일치**(R31 이전부터
  있던 결함, 위 R30 항목 "fail_b 92건은 전부 cogs(00108940...)" 참고) — R31 신규 회귀
  아니라 R20~R23 시대의 기존 revenue/cogs 매핑 gap이 전수 재감사로 새로 노출된 것으로
  판단.
- T1(R28 후속 잔여 13건) 재확인: 그룹A 6건 중 **5건 col_index=0로 복구**(LOADED).
  나머지 1건(20040619000015)은 `_split_label_amounts`까지는 정상 복구됐으나(하이픈 음수
  셀 보존 확인) **num_cols가 cum_map 헤더폭(4)로 truncate**돼 그 뒤에 온 실제 값이 잘려
  나가는 **별개 결함**(T22 범위 밖, 신규 후보 — 미착수) 때문에 여전히 미해결. 그룹B 7건은
  기존대로 T4/M2 범위. **13 → 8**(그룹A 1 + 그룹B 7).
- `pytest tests/ fin2/tests/` **549 passed**(542 기존 + R31 신규 7, 무관 기존 실패 1건
  `test_lxintl_facility_table_dropped` 불변).

---

## R32. Gate B — 업종 프로파일 파생 `revenue` 검증 (증권/은행/보험/여신전문, 2026-08-17)

설계 `docs/plans/gateb_industry_derived_revenue_design_2026-08-17.md`, census
`docs/qa/industry_profile_component_census_2026-08-17.md`.

**배경**: `fin2/layer3/industry_profiles.py::compose()`가 증권/은행/보험/여신전문 4개
업종의 `revenue`를 성분 합성으로 만든다(예: 증권 순영업수익 = 영업이익+판관비). Gate B
감사기(`face_audit.py`)는 "원문에 그 값이 단일 라인으로 있는가"만 보는데, 파생값은 정의상
그렇게 존재하지 않아 **전부 fail** 처리되고 있었다 — Gate B 전체 fail 의 81%(2,721/3,348)가
이 노이즈였다(census §1-A).

**해결**: 면제가 아니라 **파생 검증**. `std_financials_v3.industry_lines`(JSONB)에 계층3이
남긴 성분(예: `{"profile":"securities","operating_income":..,"sga":..}`)을 읽어, 그 성분들이
원문 face 에 실재하는지 확인하고 재합산해 std 값과 대조한다. 성분 하나라도 못 찾으면
`DERIVED_COMPONENTS_UNVERIFIED`(pending, fail 아님) — 재계산이 std 값과 다르면 그대로
`VALUE_DIFF`(fail 유지, 면제로 퇴화하지 않음).

**성분 → canonical 매핑**(Phase 0 census 46개사 실측으로 확정, 짐작 없음):

| 성분 | Track A(XBRL concept_map) | Track B(텍스트) |
|---|---|---|
| `operating_income` | 기존(`dart_OperatingIncomeLoss`) | 기존(`is.operating_income`) |
| `sga` | **신규** `ifrs-full_SellingGeneralAndAdministrativeExpense` | 기존(`is.sga`) |
| `interest_revenue` | 기존(`ifrs-full_RevenueFromInterest`) | 없음 → raw value 우회 |
| `fee_revenue` | **신규** `ifrs-full_FeeAndCommissionIncome` | 없음 → raw value 우회 |
| `insurance_revenue` | 기존 + `is.operating_revenue_ins`(재매핑 안 함, 둘 다 인정) | 없음 → raw value 우회 |
| `other_op_revenue` | **신규** `dart_OtherOperatingIncome`/`ifrs-full_MiscellaneousOtherOperatingIncome` | 없음 → raw value 우회 |
| `investment_revenue` | **신규** `ifrs-full_InvestmentIncome` | 없음 → raw value 우회 |

**★교훈(실제 사고, 구현 도중 발견)**: `fee_revenue`/`interest_revenue`/`insurance_revenue`/
`other_op_revenue`/`investment_revenue` 5종 전부 Track B 에 **새 canonical 을 신설하지
않는다.** 처음엔 "기타영업수익"/"투자영업수익"을 `account_maps/is_accounts.py`에 새 exact
alias 로 추가했는데(정확일치 충돌은 없다고 확인했음), 46개사 표적 재감사에서 실제 회귀가
났다 — 동양생명(00117267) 2023Q1: "투자영업수익"이 기존 alias "영업수익"의 **부분문자열**
이라 원래 stage-3(fuzzy/포함관계) 매칭으로 `is.revenue` 에 우연히 잡히고 있었는데, 새 exact
alias 가 그 매칭을 가로채 버렸다. **`account_maps/*.py`는 Gate B 전용이 아니라 layer2/3
표준화 본체(`combine.py`/`build.py`)도 쓰는 공용 사전**이라(`concept_map.py`의 XBRL ACODE
사전과 다름 — 그건 R23 으로 이미 Gate B 전용임이 확정돼 있다), exact-alias 충돌이 없어도
fuzzy 매칭 부작용으로 std_v3 실값까지 흔들릴 수 있다. → 다섯 성분은 canonical 없이 **그
행의 face 전체에서 값(won)만 직접 검색**(census 와 동일 기법, `face_audit.py::
_PROFILE_VALUE_FALLBACK_KEYS`)해 우회한다. 회귀는
`test_account_mapper_unchanged_for_fuzzy_matched_revenue_labels`로 고정.

**구현**: `fin2/audit/face_audit.py::_recompute_profile_revenue()` — `audit_fields()`의
`is.revenue` 분기에서 일반경로가 이미 실패한 뒤에만 실행(단조성, 기존 PASS 무영향).
`gross_fallback`(공시 총계를 그대로 쓴 행)은 일반경로로 이미 통과하므로 이 경로를 타지 않음.

**검증**:
- 단위테스트 12개(`fin2/tests/test_face_audit.py`) — PASS/VALUE_DIFF 유지/성분결측 pending/
  gross_fallback 무영향/profile 없는 행 무영향/raw-value 우회/fuzzy 매칭 회귀고정. 전체
  `pytest tests/ fin2/tests/` 557 passed(무관 기존 실패 1건 불변).
- **46개사 표적 재감사**(전·후 스냅샷 대조, `scripts/gateb_r32_snapshot_before_2026-08-17.json`):
  pass 1,580→3,984(+2,404) / fail 2,683→33(fail_a **177→4**, 전부 revenue 무관 기존 결함) /
  pending 2,623→2,869. **단조성 위반 0**(pass→fail/pending 전이 0건, 첫 실행에서 3건 나왔던
  건 위 fuzzy 사고를 고치고 재실행해 0건 확정). 신규 fail_a 0건.
- 원문대조 8개사(profile 4종×2개사, 집계 아닌 손으로 확인): 대신증권·유진증권(securities),
  미래에셋생명·코리안리(insurance), 케이뱅크·BNK금융지주(bank), 삼성카드·메이슨캐피탈
  (credit_finance) — 성분 전부 원문 실재 확인. BNK금융지주는 `other_op_revenue` 성분이
  face 에 없어 정확히 `pending`(허위 PASS 아님, 안전설계 확인).
- R23 교훈검사(우연일치 0값): newly-passed 2,404행 중 revenue=0 인 행 0건, 성분=0 인 행
  1건(유진증권 2017Q1 `operating_income=0`) — 원문에 실제 "Ⅲ.영업이익 0" 라인 존재, 우연
  아닌 진짜 값으로 확인.
- **전수 재감사**(2026-08-18, 사용자 직접 실행 `run_gateb_audit_parallel.sh` 5-shard, ~1.2h,
  `--fy-min 1999`): 299,651행 전량. pass 199,113→**201,518**(+2,405) / fail_a **412→239**
  (신규 0건) / fail_b 3,081→603 / pending 97,045→97,291. **46사 밖 292,765행 산술검산** —
  pass/fail_a/fail_b/pending 4개 항목 전부 이전 기준선과 **정확히 일치**(뺄셈으로 확인,
  트랙 밖 영향 0 확정). 46사 안 fail_a 는 여전히 4건, 전부 revenue 무관(dividends_paid×3
  ·controlling_ni×1, 기존 결함). §2(마스터 문서) 공통게이트 6개 전부 충족, 트랙 완전 종료.

---

## R33. Gate B — 증거강도(축2) 계측 + `fail_a` 승격의 gapfill 예외 1건 (2026-08-18)

설계 `docs/plans/gateb_evidence_grade_redesign_2026-08-17.md`(§6 2026-08-18 개정),
실측 `docs/qa/gateb_evidence_census_2026-08-18.md`.

**축 분리**: Gate B 는 이제 **판정**(`match`/`VALUE_DIFF`/pending)과 **증거강도**(그 판정의
근거)를 분리해 기록한다. `FieldAudit.evidence` + `face_audit.evidence_detail`(JSONB).

| 등급 | 의미 |
|---|---|
| `E1_EXACT` | 원문 face 라인 값과 정확 일치 |
| `E2_SIGN` | 절대값 일치, 부호만 다름(표준화 규약) |
| `E3_ROUNDING` | 표시단위 1단위 이내(발행사 반올림) |
| `E4_IDENTITY` | 회계 항등식으로 재구성해 일치(revenue=cogs+gp / NI=CF대체 / NI=지배+비지배 / R32 업종파생) |
| `E5_HEURISTIC` | 저신뢰 리더 후보(`from_gapfill`)와 일치 |
| `M1_STRONG` | 불일치 — 최근접 후보가 non-gapfill |
| `M2_WEAK` | 불일치 — 최근접 후보가 `from_gapfill` |

**★게이팅은 여전히 리더 트랙(A/B/C) 축이다.** `gate_status_for_row()`가 evidence 축으로
**교체되지 않은 이유**는 전수 census 실측(299,651행)이다:

```
mismatch 필드 1,129건(fail_a 253 + fail_b 876)  →  전부 M1_STRONG, M2_WEAK 0건
pass 필드 4,218,532건  →  E1 99.89% / E4 3,600 / E2 945 / E3 45 / E5 0건
```

`from_gapfill=True` 가 붙는 곳은 `_supplement_with_text()`(`face_audit.py:621`)와 PDF
리더(`:721`) **둘뿐**이다. Track B(텍스트) 리더가 보고서를 **원본으로** 읽은 라인은
`from_gapfill=False` → `M1_STRONG`. 따라서 "M1_STRONG 이면 차단"으로 축을 바꾸면 지금
`fail_b` 603행이 전부 차단으로 흡수돼 **REVIEW 등급이 소멸**한다(설계서 §6 초안의 A/B/C
세 안이 M2·E5 가 0 이라 현재 데이터에서 **전부 같은 결과** — 그 표는 2026-08-18 개정됨).
게다가 §1-A 가 축 교체의 근거로 든 "같은 회사·같은 필드인데 연도에 따라 등급이 뒤집힘"은
트랙①(R32) 이후 **(corp,field) 480쌍 중 1쌍**만 남아 실질 소멸했다.

**채택(A′) — 좁은 봉합 1건**: 축은 track 그대로 두고, 설계서 §1-A 의 **부수결함만** 막는다.
Track A 보고서라도 그 실패 필드의 최근접 후보가 gapfill(`M2_WEAK`)이면 `fail_a` 로 세지
않는다(증거는 휴리스틱인데 등급만 최고신뢰인 모순 제거). `evidence` 가 `None` 인 불일치
(R32 파생 재구성 후 불일치 — 단일 최근접 후보가 없어 M1/M2 판정 자체가 성립 안 함,
`face_audit.py:1106-1108`)는 **보수적으로 기존과 동일하게 차단** 쪽으로 센다.

현재 `M2_WEAK` 가 0건이라 **판정 무변화**다(미래 방어 전용). 실측 확인: 00117212
(fail_b 다수) pass 65/fail_a 0/fail_b 56/pending 57, 00155258(fail_a 최다) pass 102/
fail_a 14/fail_b 0/pending 68 — 둘 다 DB 현재값과 완전 일치.

**전수 재감사(299,651행)로 확정**(2026-08-18): 사전 스냅샷 대비 `gate_status` 전이 행렬
**대각선만**(비대각 0), 판정 6개 항목 행 단위 대조 **변화 0행**, `M2_WEAK`/`E5_HEURISTIC`
둘 다 0. 검증 SQL = `scripts/verify_gateb_aprime_no_change.sql`(재개 트리거 점검도 포함).

**재개 트리거(명문화)**: 다음 전수 재감사에서 아래 중 하나라도 관측되면 게이팅 축 재검토
(설계서 Phase 3)를 재개한다. 계측이 이미 배선돼 있어 자동 감지된다.

```sql
-- ① M2_WEAK 출현 → A′ 예외가 실제로 발동하기 시작 = 축 재검토 신호
SELECT count(*) FROM face_audit fa, LATERAL jsonb_array_elements(fa.fail_detail) f
WHERE fa.source_version='v3' AND f->>'evidence'='M2_WEAK';

-- ② E5_HEURISTIC 출현 → 휴리스틱 근거만으로 통과한 pass 발생 = 설계서 C안 재평가 신호
SELECT count(*) FROM face_audit
WHERE source_version='v3' AND evidence_detail ? 'E5_HEURISTIC';
```

**미결**: `E4_IDENTITY` 3,600건은 4개 서브경로(revenue=cogs+gp / NI=CF대체 / NI=지배+비지배
/ R32 업종파생)가 한 등급으로 뭉쳐 있어 저장값만으로 분해할 수 없다. 설계서 C안("약한
근거 통과를 `pass` 로 인정하지 않음")을 진지하게 평가하려면 E4 세분화가 선행되어야 한다
(부록 C 등재).

관련 코드: `fin2/audit/face_audit.py`(`EVIDENCE_*`·`gate_status_for_row()`·`audit_fields()`),
`scripts/gateb_audit.py`(`evidence_detail` 집계), `collector/models.py`·`collector/db.py`
(마이그레이션 `2026_08_face_audit_evidence_detail`).
회귀: `fin2/tests/test_face_audit.py`(증거등급 9경로 + A′ 분기 6종).

---

## R34. `fin2/layer3/combine.py::_resolve()` — R2 델타패치가 정정본의 표 재렌더링에
무력화되던 결함(depth-우선이 section_path 만 다른 정정본 셀을 통째로 무시)

**증상** — P3-1 전수 재감사(2026-08-19) 스냅샷 대비 비교에서 689건 단조성 위반(기존
pass → fail/pending) 발견. 원인규명 결과 그중 30건(6개사)이 이 결함으로 확정됐다(나머지는
무관 — R34 부록C 참고).

**근거(실측, 고려아연 00102858 2023FY 연결)** — `build_merged_lines()` 로 라이브 재실행:

```
label='자산총계' value=12,046,071,311,650 source_rcept=20240311000892(최초등록) amended=False
label='자산총계' value=11,768,590,335,824 source_rcept=20260813001690(2026-08-13 정정) amended=True
```

셀 키(`statement,basis,col_index,section_path,label_raw`)가 R2 가 요구하는 것보다 좁다.
정정본이 표를 재렌더링하며 `section_path`에 래퍼가 한 겹 추가되면(`'자산'` → `'재무상태표
[개요]>자산'`) 두 필링의 "자산총계"가 **다른 셀**로 살아남아, `build_merged_lines()`의
델타패치(R2, "정정이 이긴다")가 발동하지 않는다. 그러면 두 후보가 `_resolve()`에서 같은
canonical(`bs.total_assets`)로 충돌하고, `_reduce_conflict()`의 "얕은 depth 우선"(원래
목적 = 한 필링 안에서 합계가 하위상세항목에 안 밀리게 하는 것)이 **section_path 가 얕은
원본을 정정본보다 이겨버린다** — `_eps_dup()`(0.1% 근사중복→큰 값)는 2.3% 차이라 안
걸린다.

label_raw 완전일치로도 못 잡는 경우가 흔하다 — 정정본이 각주번호까지 같이 바꾼다
(`"(5) 이익잉여금 (주27)"` 원본 vs `"(5) 이익잉여금"` 정정본).

**수정(2026-08-20)** — `_resolve()`가 canonical 별 candidate 를 depth 판정에 넘기기
**전에**, `industry_profiles.norm()`(번호/각주 제거 정규화, 기존 `is.revenue` grand-total
매칭에 이미 쓰던 함수)으로 정규화한 label 이 같고 값이 다른 후보 그룹 중, `amended=True`
(=더 나중 필링에서 patch 된 셀)가 하나라도 있으면 그 라벨의 `amended=False`(base) 후보를
버린다. `amended` 후보가 아예 없으면(=진짜 같은 필링 안의 총계/하위항목 구조 차이) 손대지
않는다 — 기존 depth-우선의 원래 목적은 그대로 유지.

**검증** — 6개사(00102858·00141608·00145437·00243067·00403793·01303029) `build_std_v3.py`
재생성 + `gateb_audit.py --recheck`: 이 결함으로 잡힌 43개 (corp,fy,period,statement_type)
중 31건 pass 전환, fail_a **38→0**. 나머지 12건은 `LABEL_UNMATCHED`/`SOURCE_NOT_TRACK_A`
pending — 이 결함과 무관한 별개 원인(부록C 참고, 별도 트랙). `pytest tests/ fin2/tests/`
576 passed(기존 무관 실패 1건 `test_lxintl_facility_table_dropped` 그대로) — 회귀 없음.
회귀 테스트 = `fin2/tests/test_combine_amended_label_depth.py`(4종).

**미조치 범위** — 이 수정은 코드 전역에 즉시 적용되지만(향후 모든 `build_std_v3` 재생성에
자동 반영), **std_v3 에 이미 저장된 값**은 재생성한 6개사만 갱신했다. 이 패턴이 P3-1의
689건 밖에(즉 이번에 처음 fail 로 드러나지 않고 이미 예전부터 fail 이던 회사에) 잠복해
있을 가능성은 미확인 — 전수 조사 안 함(부록C에 등재).

---

## R35. `fin2/audit/face_audit.py` — NI 귀속표 전체가 XBRL 미태깅인 문서에서
`is.controlling_ni`가 감사기 후보 풀에 전혀 안 들어오던 결함(P3-1 '원인 A' 후속)

**증상** — P3-1 재감사 잔여 668건(원인 A, R34 제외분) 중 527건(56개사)이 `LABEL_UNMATCHED`
로 pending. **std_v3 값 자체는 원문과 일치**(케이씨씨 00105271·엘에스일렉트릭 00105855
원문 XML 직접 대조 확인, 값이 CP949 원문 안에 그대로 존재) — std_v3 버그가 아니라 감사기
커버리지 공백.

**근거(실측)** — 두 필링 모두 NI 귀속('...의 귀속') 표 전체가 `<TE ACODE>` 태그 없이 순수
`<TD>`(구형 렌더링)만으로 되어 있다(`root.findall('.//TE[@ACODE]')` 중 `ifrs-full_`/`dart_`
접두 매칭 0건). `_ni_attribution_structural_candidates()`(R24)는 `tr.findall("TE")`를
전제하므로 이런 문서를 통째로 못 본다.

**왜 `account_mapper`(범용 텍스트 매퍼)로 안 고쳤나** — Track B(`read_report_face_text`)가
이미 문서 전체를 제네릭 라벨매퍼로 읽지만, 흔한 축약 라벨 `'지배주주지분'`(6자)이
`'비지배주주지분'`(`is.noncontrolling_ni`)의 **부분문자열**이라 `AccountMapper._fuzzy_match()`
의 포함매칭(`normalized in alias_norm`)이 이걸 비지배로 오귀속한다(실측 유사도 0.977,
`account_maps/bs_accounts.py:296` 이 2026-07-18 에 BS쪽(`bs.controlling_equity`)에서 이미
같은 함정을 겪고 그 alias 를 **의도적으로 빼뒀다** — IS 쪽엔 그 코멘트가 없었을 뿐 같은
공백이 있었다). 라벨 텍스트만으로는 이 짧은 형태를 안전하게 못 구분한다.

**수정** — `fin2/audit/face_audit.py::_ni_attribution_text_candidates()` 신설: R24 TE
자매함수와 **동일한 앵커/섹션 상태기계**(`_NI_TOTAL_RE` 앵커 + 섹션 안 '비지배' 유무로 정확히
한 쌍만 인정)를 쓰되, 라벨 사전 의미가 아니라 **섹션 내 구조적 위치**만 본다 — 그래서 짧은
라벨도 안전하다. 두 안전장치: ① `_detect_body_statement_tables()`(Track B 와 공유하는
본문표 식별)로 IS 본문표에만 스캔 국한(주석 오염 차단, TE 판은 ACONTEXT 존재 자체가
안전장치라 문서 전체를 훑어도 됐지만 태그 없는 TD 는 그 신호가 없다), ② `from_gapfill=True`
(불일치는 GAPFILL_UNVERIFIED/pending 유지, FAIL 승격 금지 — R24/`_supplement_with_text`와
동일한 단조성 계약).

호출 지점 = `read_report_face()`/`read_report_face_tracked()`에서 **Track A/B 확정 이후**
(`_with_ni_attribution_text_fallback()`), `is.controlling_ni`·`is.noncontrolling_ni` **둘
다** 이미 있으면 스킵(비용 절감, 대부분 문서는 태그가 있거나 Track B 제네릭 매퍼가 이미
잡는다). ★ 최초 구현은 이 폴백을 `read_report_face_xbrl()` **내부**에 붙였다가 즉시 회귀를
실측했다: 그 함수의 반환이 "비었는가"가 Track A/B 채택 신호로도 쓰이는데, 완전 미태깅
문서에서 이 폴백만으로 반환이 non-empty 가 되면 원래 Track B 전체(`read_report_face_text`,
from_gapfill=False)로 떨어져야 할 문서가 "Track A(사실상 텅 빈)+`_supplement_with_text`
(from_gapfill=True 로 격하)"로 오분류됐다 — 그 결과 원래 실증거(M1_STRONG)로 잡히던 진짜
값불일치(fail_b, 성도이엔지 등)가 근거강도만 깎여 GAPFILL_UNVERIFIED 나 심하면 가짜 PASS
로 가려졌다(측정 51건 중 34건). 트랙 확정 이후 지점으로 옮겨 해소·재검증(아래).

**검증** — 668건(원인 A 잔여, R34 제외) 재감사(읽기전용 실측, `scripts/
investigate_p3_cause_a_impact_measure.py`): **382건 pass 회복**, 235건 pending(잔여,
SOURCE_NOT_TRACK_A 8개사 등 별개 원인), **51건 fail 그대로**(기존 Group B, 이 수정과
무관 — 정확히 원래의 51건과 일치, 새 fail 0건). `pytest tests/ fin2/tests/` 583 passed
(기존 무관 실패 1건 `test_lxintl_facility_table_dropped` 그대로) — 회귀 없음. 회귀 테스트
= `fin2/tests/test_ni_attribution_text_fallback.py`(3종).

**미조치 범위** — DB(`face_audit`)에 대한 실제 재체크·커밋은 영향받은 74개사로 스코프해
`gateb_audit.py --source v3 --corp-file <74개사> --recheck` 로 반영(전수 재감사는 아직).
잔여 235건 pending 중 다수는 KCC 처럼 NI 귀속 섹션 자체가 실제로는 총포괄손익 귀속 라벨로
잘못 렌더링된 필러 특이 케이스이거나(구조상 안전하게 못 넓힘), 8개사(`SOURCE_NOT_TRACK_A`,
위지윅스튜디오 등)는 필링 전체가 Track A/B 모두 못 읽는 별개 문제(부록C 참고). 51건 fail(Group
B, 카카오게임즈·폴라리스오피스 등 13개사)은 **손대지 않음** — 실제 값불일치 의심으로
회사별 개별 원인규명 필요(R24~R27급).

---

## R36. `fin2/audit/face_audit.py` — `_ni_attribution_text_candidates()`(R35) 열(컬럼)
선택 누락으로 전기/전전기 값이 값불일치 오탐을 낸 결함(P3-1 '원인 A' 그룹② 후속)

**증상** — R35 신설 함수가 잡은 51건/13개사(카카오게임즈·성도이엔지 등)가 `fail`/
`M1_STRONG`로 나왔으나, 51건 전건(53개 필드-기간) 원문 문자열 대조 결과 **std_v3 값이
전부 원문에 실재**(데이터 오류 0건) — 감사기 오탐으로 확정([[p3-1-cause-a-group2-root-cause-2026-08-20]]).
당초 "부모 섹션 구분 없음"(포괄손익/EPS주석/정정비교표와 혼동)으로 가설을 세웠으나,
실제 원문 구조를 직접 대조(카카오게임즈 63개 필링 전건 재추출)한 결과 **가설이 틀렸다** —
실제 원인은 훨씬 기계적이었다.

**근거(실측)** — TD(비XBRL) 표는 ACONTEXT 가 없어 TE 자매함수(`_ni_attribution_
structural_candidates()`, `ctx.col_index != 0` 로 당기만 선택)와 달리 어느 열이 당기인지
구조적으로 모른다. R35 최초 구현은 이 구분 없이 지배/비지배 행의 **모든 값 열**(당기·전기·
전전기, H1/Q3 는 [당기3개월,당기누적,전기3개월,전기누적] 4열)을 전부 후보로 냈다 — 같은
행 안의 전기/전전기(또는 당기3개월, 당기누적과 다름) 값이 엉뚱하게 "값불일치 증거"로 잡힘.
실측: 카카오게임즈 2022 FY 지배주주지분 행 `[(233,641,194,325) 당기 / 528,656,449,171 전기
/ 85,970,818,329 전전기]`— std_v3=`-233,641,194,325`(당기, 첫 열)와 정확히 일치, 나머지
둘은 잘못 섞인 전기/전전기. 성도이엔지 2023H1 지배주주지분 행 `[1,451,210,911 당기3개월 /
**1,296,834,534 당기누적(std_v3 일치)** / 2,501,296,907 전기3개월 / 8,399,952,262
전기누적]` — H1/Q3 는 **첫 열도 아니다**(당기3개월≠당기누적). 카카오게임즈·성도이엔지
63개 필링 전건 재census 결과 51건 fail 전체가 이 매커니즘 하나로 설명됨(cross-table/
cross-section 오염 사례는 0건 관측 — 애초 가설과 달리 섹션 경계 자체는 문제없었다).

**수정** — `fin2.extract.text._interim_cumulative_cols()`(Track B 추출기가 같은 문제를
표 헤더의 '누적' 토큰 위치로 이미 해결해둔 구조 판정 함수)를 재사용해 표 헤더에
`[3개월|누적]` 2단 구조가 있으면 '누적' 토큰이 붙은 첫 컬럼(당기누적)만, 없으면(FY 또는
헤더 미검출) 첫 값 컬럼만 채택 — 결과적으로 라벨당 값 1개(TE 판의 `col_index=0` 채택과
동형)만 후보로 낸다. 이건 값 파싱이 아니라 **표 레이아웃 판정**이라, 이 함수가 이미
공유 중인 `_detect_body_statement_tables()`류와 같은 성격 — 모듈 독립성 원칙("숫자를
어떻게 읽는가")과 충돌하지 않는다(이미 확립된 선례를 그대로 따름).

**검증** — 카카오게임즈·성도이엔지 63개 필링 전건 재추출: 값 충돌(같은 canonical 에 서로
다른 값) 0/63(수정 전 다수). std_v3 대조 341개 필드 중 332개 일치(9개 잔차는 전부
2012~2014 pre-2015 성도이엔지 — R36 적용 전에도 이미 값불일치였던 **별개**·미해결 이슈,
회귀 아님 확인). `--recheck --no-commit` 표본 재감사(200사 랜덤 + fail_fields 에
controlling_ni 잡힌 51개사) — fail_a/fail_b 건수 변화 없음, pending→pass 전환만 관측
(51사 표본: pending 816→807, pass 5131→5140). 회귀 테스트 2종 추가(`fin2/tests/
test_ni_attribution_text_fallback.py`) — FY(첫 열만 채택)·interim(누적 열만 채택) 각각.
`pytest tests/ fin2/tests/` 기존 무관 실패 1건(`test_lxintl_facility_table_dropped`) 외
전부 통과.

---

## R37. `scripts/gateb_audit.py::select_corps()` — Gate B 감사 유니버스가 상장폐지사를
걸러내지 않던 결함(P3-1 '원인 A' 그룹③-a 후속)

**증상** — 위지윅스튜디오(01276327, 2026-08-18 상장폐지 확정)가 전수/범위 재감사에서
여전히 대상으로 잡혀 `SOURCE_NOT_TRACK_A`(pending) 58건을 냈다. std_v3/R35 로직은
버그가 아니다 — ⓪-4 파이프라인이 `raw_report`를 NAS 아카이브로 정상 이관한(의도된 동작,
[[delisting-archive-automated]]) 결과일 뿐인데, 감사 유니버스 쿼리가 이 사실을 몰라
아카이브된 문서를 계속 "감사 대상"으로 붙잡았다.

**수정** — `select_corps()`의 기본/범위(`--corps`) 쿼리에 `corporations.is_active=true`
조인 필터 추가. `--corp`/`--corp-file`(명시적 단일/목록 지정, 조사 목적) 두 분기는 그대로
둔다 — 상장폐지 후 이력도 명시적으로는 여전히 조회 가능. CLAUDE.md 스코프("현재 시점
KOSPI/KOSDAQ 상장된 보통주")에 맞춰 **감사 유니버스에서 아예 제외**(옵션 A, 기존
`face_audit` 이력은 보존 — 신규 재감사 대상에서만 빠짐)로 결정(사용자 확인).

**검증** — 필터 적용 후 기본 유니버스 2,543→2,528사(현재 `is_active=false` 15개사,
1,780행 제외 — 위지윅스튜디오 외 스타코링크·더존비즈온·신세계푸드·일정실업 등도 동일
사유). 위지윅스튜디오는 `--corp` 명시 지정 시에는 여전히 pending(원문 파일이 로컬에
없어 정상 — 이 트랙에서 "고치는" 대상이 아니라 애초에 감사 스코프 밖으로 빼는 것).
`pytest tests/ fin2/tests/` 회귀 없음.

---

## R38. `fin2/audit/face_audit.py::read_report_face_xbrl_zip()` + `scripts/gateb_audit.py`
배선 3곳 — Track D(xbrl_zip) 신설, `document.xml` 없는 filing 의 감사 커버리지 공백
해소(P3-1 '원인 A' 그룹③-b 후속)

**증상** — 일부 filing 은 `download_tasks`에 `xbrl_zip` 파일타입만 `completed`로 등록되고
`xml`(document.xml)이 없다(전사 1,639건 중 1,627건, 2015~2019 집중 — 표본 30건 재다운로드
전부 `[014]` 회복 0건으로 "종종 영구적" 확정, `redownload_202608_xbrl_zip_bulk.py`
docstring 참고). `file_path_map()`이 `file_type IN ('xml','pdf')`만 찾아 이런 filing 을
통째로 못 읽어 `SOURCE_NOT_TRACK_A`(pending)로 떨어졌다.

**근거(실측)** — 이건 데이터 갭이 아니다. `fin2/extract/report_lines_xbrl.py::
extract_report_lines_xbrl()`(R10, XBRL_INSTANCE zip 전용 파서)가 daily 파이프라인에서
이미 zip 을 정상 처리해 report_lines/std_v3 에 값이 들어가 있다(오리엔탈정공 2015Q3
`[기재정정]분기보고서`, rcept 20151123000202: `revenue` 연결 131,915,704,465/별도
97,795,299,224, `controlling_ni` -4,000,961,350 — 전부 std_v3 와 zip 재추출 값이 정확히
일치). 유일한 문제는 face_audit 의 대조 경로 부재(그룹①/R35 와 동류).

**수정** — `read_report_face_xbrl_zip()` 신설: `extract_report_lines_xbrl()`(R10)을 감사
시점에 재호출(저장된 report_lines 를 읽지 않고 zip 을 다시 열어 Track A/B/C 와 같은
"항상 원본 재유도" 관례 유지), `col_index=0`(당기)만, `account_mapper` 텍스트 매핑(Track
B 와 동일 — canonical 은 report_lines 에 없음). 독립성 잔여 한계: R10 파서 자체의 추출
버그(부호·스케일·개념매핑 오류)는 이 경로로는 못 잡는다 — Track A(문서 내 별개 XBRL 태그
직접 스캔)만큼 완전독립은 아니다. 배선 3곳(전부 필수, 하나라도 빠지면 조용히 결함):
① `file_path_map()` — `file_type IN (...)`에 `'xbrl_zip'` 추가(xml>pdf>zip 우선순위).
② `face_of()` — `fp`가 `.zip`이면 `read_report_face_xbrl_zip()` 호출, `track="D"`.
③ `gate_status_for_row()` — `("B","C")` 하드코딩 allowlist를 `("B","C","D")`로 확장(★
가장 잊기 쉬운 지점 — 안 하면 Track D 의 모든 불일치가 조용히 `fail_a`로 오승격한다.
Track D 는 R10 재사용이라 Track A 보다 독립성이 약해 최고신뢰를 주면 안 됨).

**검증** — 오리엔탈정공 2015Q3(위 실측 필링): 수정 전 `SOURCE_NOT_TRACK_A` 42개 필드
전량 pending → 수정 후 `pass` 전환(잔여 pending 5개는 R10 자체 추출 갭, 별도). 오리엔탈정공
전체(2015~2026, 132행): pass 112 / fail 0 / pending 20, 일치율 100.0%. `xbrl_zip`-only
777개사 중 80개사 표본 `--recheck --no-commit` 재감사 — **fail_a 신규 발생 0건**(9→9,
§ 게이팅 수정의 핵심 검증 포인트) 확인. pending 1790→1698 이 pass +40·fail_b +52 로
분해(새로 읽히게 된 값 중 실제 불일치는 fail_b/REVIEW 로 안전하게 분류, fail_a 로 오승격
안 됨 — 이 fail_b 52건 자체의 개별 원인규명은 범위 밖, 향후 트랙). `pytest tests/
fin2/tests/` 회귀 없음.

---

## R39. `fin2/layer3/combine.py::_resolve()` — BS 총계 3종의 라벨-표현 드리프트가
정정 전 값을 되살리던 결함(R38 fail_b 52건 후속, P3-1 Track D 패턴A)

**증상** — R38(Track D) 재감사가 새로 드러낸 fail_b 774건을 `fail_tracks[field]=="D"`로
정밀 필터한 진짜 541행(239개사) 중, BS 총계 3종(`bs.total_assets`/`bs.total_liabilities`/
`bs.total_equity`) 684개 필드가 db(std_v3)와 Track D 재파싱 값이 서로 다르게 나왔다. db
쪽이 정정 전(stale) 값을 잔존시키는 패턴이었다.

**근거(실측, 00103130/플레이그램 2017 Q1)**:

| 필링 | 라벨 | 값 |
|---|---|---|
| 원본(`20170515004380`) | "자산총계" | 68,523,148,315(=수정 전 db) |
| [기재정정](`20180322000560`) | "자산" | 68,145,914,314(=원문 검산상 정확한 최신값) |

`account_mapper.map()`은 `"자산총계"→stage=exact`, `"자산"→stage=fuzzy`(둘 다
`bs.total_assets`)로 매핑한다. R34(위)는 `industry_profiles.norm()`으로 라벨을 정규화해
묶은 뒤 `amended=True` 후보가 있으면 `amended=False` 후보를 depth 판정 전에 버리는데,
`norm()`은 번호/각주/공백만 지우고 **단어 자체("총계")는 지우지 않는다** —
`norm("자산총계")≠norm("자산")`이라 이번 케이스는 R34의 그룹핑을 그냥 통과해버린다.
그 결과 `_STAGE_RANK`(exact=3>fuzzy=1) 타이브레이크가 정정으로 갱신된 값이 아니라
정정 전(exact) 값을 채택했다. R34가 고친 건 "표기 잡음(formatting) 드리프트"이고, 이번은
"단어 자체가 바뀌는(wording) 드리프트"라는 게 차이 — R34 문서의 "미조치 범위"가 정직하게
남겨둔 잠복 가능성이 이번에 실측으로 확인된 사례다.

**수정** — `bs.total_assets`/`bs.total_liabilities`/`bs.total_equity` 3개 canonical에
한해, R34의 `by_label` 그룹핑 키를 `norm(label)`이 아니라 **라벨 무시(canonical 전체를
한 그룹)**로 넓혔다. 이 3종은 한 필링·basis 안에 "진짜" 값이 하나뿐이어야 하는 총계라서
"라벨이 달라도 같은 canonical이면 같은 개념"이라는 가정이 안전하다(`_trust_account_
table_seqs` 가드가 이미 같은 전제로 특별취급하는 것과 동일 논리). **순서 안전장치**: 그룹
범위가 넓어지면서 신탁계정의 amended 총계가(라벨이 달라도 이제 같은 그룹에 섞일 수 있어)
실제 재무제표 총계를 오염시킬 위험이 R34 때보다 커져, `trust_seqs` 필터를 `by_label`
그룹핑보다 **먼저** 적용하도록 순서를 바꿨다(원래는 그룹핑 다음이었음).

**검증** — 00103130 2017 Q1 `build_std_v3.py` 재생성 → `total_assets` 68,523,148,315
(정정 전) → 68,145,914,314(정정 후, 원문 일치)로 전환, `gateb_audit.py --recheck
--no-commit` pass 114/fail 0/pending 18(fail_a·fail_b 0). 회귀 테스트 2종 추가
(`fin2/tests/test_combine_amended_label_depth.py`: 라벨-표현 드리프트 재현 + 신탁계정
비오염). `pytest tests/ fin2/tests/` 588 passed(기존 무관 실패 1건
`test_lxintl_facility_table_dropped` 그대로) — 회귀 없음.

**전사 영향범위(사전측정, 2026-08-20)** — std_v3 전체 (corp,fy,period) 151,961건을 BS
전용 경량 스캔(zip 재파싱 없음)한 결과, "BS 총계 3종 candidate 값충돌+amended 후보존재"가
1,058건(218개사) — 이 중 R34가 이미 처리 중인 302건을 빼면 **이번 수정이 실제로 새로
고치는 건 156개사/756건**(total_assets 280·total_equity 266·total_liabilities 210).
**138개사(719건)는 xbrl_zip-only(R38 Track D) 대상과 겹치지만, 18개사(37건)는 완전히
그 밖**(Track A/B 커버리지, fy 2004~2025 전구간) — 이 결함은 Track D/xbrl_zip과 무관한
std_v3 전역 결함이며, 백필 시 이 18개사를 xbrl_zip-only 백필과 별도로 반드시 포함해야
한다.

**미조치 범위** — 코드 수정은 향후 재생성분에 자동 반영되지만, 이미 저장된 std_v3 값은
영향받은 (corp,fy,period,basis)를 `build_std_v3.py`로 별도 소급 재생성해야 한다(156개사/
756건, 대상 목록은 재스캔 필요 — 스캔 스크립트는 세션 스크래치라 repo 미포함, 재현 로직은
[[p3-1-trackd-failb-rootcause-2026-08-20]] 부록A).

---

## R40. Track D(xbrl_zip 재파싱) — 다중필링 narrow-prefer 재현 불가(알려진 감사 커버리지
공백, 수정 안 함)

**증상** — R38(Track D) 재감사가 새로 드러낸 fail_b 541행 중 232건이 `bs.trade_payables`
(매입채무)에서 db(std_v3)와 Track D 재파싱 값이 불일치했다.

**근거(실측, 00107987 2018H1·00112651 2017Q1 — 2건 모두 동일 구조)**:

| 필링 | "매입채무" 표기 | 값 |
|---|---|---|
| 원본 | "매입채무 및 기타(유동)채무"(광의, 부모) + "단기매입채무/매입채무"(협의, 자식) | 광의 80,992,526,676 / **협의 39,217,873,634(=db)** |
| [기재정정] | 광의 라벨만 재게재, 협의 세부항목 생략 | 80,992,526,676(=Track D 재파싱) |

`combine.py`의 `_NARROW_PREFER`/`_BROAD_RE`(`_reduce_conflict()`, R23)가 그 기간의 원본+
정정 **전체를 풀링**한 후보군에서 원본의 협의값을 정확히 우선 채택한다 — **db는 정확**.
반면 `read_report_face_xbrl_zip()`(R38, Track D)은 감사 대상 rcept **하나(대개 정정본)만
연다** — 정정본엔 협의 세부항목이 아예 없으니 광의값만 후보로 갖게 되고, db의(정확한)
협의값과 불일치로 fail_b가 뜬다.

**결론: 데이터 결함이 아니라 Track D 설계 자체의 한계다.** db 값도, 판정 등급(fail_b/
REVIEW, fail_a 오승격 없음)도 이미 올바르므로 **수정하지 않는다** — Track D는 애초에
"완전독립 감사가 아님"을 전제로 하는 트랙(R38 자체가 이미 "R10 재사용이라 Track A보다
독립성이 약함"을 명시)이고, 여기에 다중필링 폴백까지 추가하면 그 존재의미(휴리스틱 REVIEW용
대조)가 흐려진다. 개선하려면 후보가 db와 안 맞을 때 같은 기간의 다른(원본) 필링도 열어보는
확장이 필요하지만 우선순위 낮음(별도 요청 시에만 착수) — [[p3-1-trackd-failb-rootcause-2026-08-20]].

**R38 후속 — xbrl_zip 전사 반영 완료(2026-08-21)**: R38(Track D 신설)+R39(패턴A 수정)+
R40(패턴B 문서화)이 전부 안전 검증된 뒤, `scripts/run_gateb_audit_parallel.sh`
(5-shard, `--source v3 --recheck`)로 **std_v3 전체 303,859행**(제한된 xbrl_zip-only
표본이 아니라 전 유니버스)을 실제 commit 재감사했다. 재감사 전 `face_audit_snap_20260820`
기준선 스냅샷 대비 행단위 gate_status 전이:

| 전이 | 건수 | 해석 |
|---|---|---|
| pending → pass | 558 | Track D 커버리지 공백 해소(정상 일치) |
| pending → fail_b | 300 | Track D로 새로 읽혔으나 값불일치 — REVIEW 등급(R40류, 안전) |
| fail_b → pass | 7 | R39(패턴A) 수정으로 정정 |
| fail_a → pass | 2 | R39(패턴A) 수정으로 정정 |
| fail_b → pending | 1 | 개별 원인 미조사(경미, 저위험 방향 — pending 은 out-of-scope 일 뿐 오탐 아님) |

**pass→fail 전이, X→fail_a 전이는 0건**(전수 확인 — `fail_a` 283건 중 BS 총계 3종
[`bs.total_assets`/`bs.total_liabilities`/`bs.total_equity`] 포함 행 0건). 사전 --no-commit
표본 테스트(R38/R39 각 검증절)의 "fail_a 신규 0건" 예측이 전수 commit 규모에서도 정확히
재현됨 — [[gateb-full-reaudit-is-required-to-close]] 원칙대로 표본이 아닌 전수로 트랙 종료.

---

## R41. `fin2/audit/curated_key_scan.py` 신설 — Gate B curated 키 재생성기(전수 패턴
스캔 → 신규/재발 후보 탐지, 자동 코드 반영 없음)

**배경** — R15~R33 다수가 특정 (corp, fy, period[, basis]) 를 리터럴로 열거한 override
로 구현돼 있다(`combine.py`/`face_audit.py`). 이 키 집합은 생성 당시 DB 스냅샷의 1회성
산출물이라, 새 필링이 들어와도 자동으로 안 늘어난다 — 같은 회사가 같은 구조로 다음
분기를 공시하면 버그가 조용히 재발하거나(값이 틀림) Gate B 가 pending 을 fail 로
잘못 잡는다. 설계: `docs/plans/gateb_curated_key_regenerator_design_2026-08-18.md`
(§6 결정사항 2026-08-19 확정, 구현은 2026-08-21).

**구현 범위(§6 확정 1차 범위)** — 4개 family:
- **T2**(`report_lines` 직접 전수 스캔, 원 생성 스크립트 corp 조건 없음 재사용):
  `sga_subline`(`_SGA_SUBLINE_OVERRIDE_KEYS`) · `cogs_additive`(`_COGS_ADDITIVE_OVERRIDE`).
- **T1**(XML/PDF 재파싱 없이 이미 계산된 `face_audit`(v3) 의 `fail_detail` 재사용,
  R38 xbrl_zip 전사 반영으로 항상 최신 유지):
  `trade_payables_additive`(`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`, BS 부채성 라인 2-조합
  합이 report_won 과 일치하는 후보를 찾는 휴리스틱) ·
  `cogs_concept_mismatch`(`_COGS_CONCEPT_MISMATCH_KEYS`, `report_won==cogs+sga`±1 재확인).

**T1/T2 비대칭(구현 중 발견, 설계 §5-C 캐비엇의 실제 사례)** — T2 는 모집단(`report_lines`)
이 override 등록과 무관해 ①일치(=동치성 증명)/④소멸까지 전부 계산 가능하다. 반면 T1 은
모집단(`face_audit.fail_detail`)이 **구조적으로 이미 등재분을 제외**한다 — 등재 키는
`cogs_concept_mismatch` 는 face_audit.py 가 pending 재분류, `trade_payables_additive` 는
combine.py 가 build 시점에 db_won 자체를 고쳐 PASS 로 뜨기 때문에, 애초에 VALUE_DIFF 로
안 잡힌다. 그래서 T1 은 forward/lateral 후보만 내고 matched/vanished 는 계산하지 않는다
(계산해도 등재분 100%가 항상 "vanished"로 나와 의미 없음 — `_classify_residual()`).

**동치성 검증(①일치, 최초 실행 2026-08-21)** — T2 두 family 전부 등재 키와 **정확히 일치**:
`sga_subline` 685/685, `cogs_additive` 319/319(소멸 0, 재구현이 원 생성 스크립트와
100% 동일 로직임을 실측 확인). 실행 시간 T2 두 family 합산 ~90초, T1 두 family 합산 ~5초
(report_lines 전수가 아니라 face_audit 재사용이라 빠름) — daily/반기 배치 오버헤드로 무해.

**최초 실행 결과(2026-08-21)** — 신규후보 31건(소멸 0): `sga_subline` forward 14 ·
`cogs_additive` forward 2(전부 2026 H1, 설계문서가 예견한 "2026 반기 백로그 적재 시
curated 키 stale" 시나리오가 실제로 재현됨) · `trade_payables_additive` lateral 15
(원문대조 전 후보, §4 경고대로 자동반영 대상 아님) · `cogs_concept_mismatch` 0.
`curated_key_candidates` 테이블(신규, `collector/models.py`)에 적재, status='new'로
사람 리뷰 대기.

**배선** — `scripts/collect_new.py` 두 call site(메인 ④ 이후 · `--standardize-only`
재개 이후) 모두 `_run_curated_key_scan()` 호출(`docs/runbook_new_parser_pipeline_
integration.md` 체크리스트 ① 준수). 알림은 기존 `scripts/notify.py::notify_macos()`
재사용(설계문서가 "알림 코드 전무"라 적었던 2026-08-18 이후 이미 C10 트랙에서 추가돼
있었음 — 새로 안 만들어도 됐음). 후보 0건이면 로그만, 1건 이상이면 macOS 알림 팝업+로그
요약(§6 결정사항 1).

**범위 밖(§6 결정사항 2·3, 별도 트랙)**: `_FX_PRESENTATION_CURRENCY_KEYS`(T1-3, 원문
표시통화 판정 규칙 신설 필요) · T0 축B(신규 회사가 blanket override 대상이 되는 경우,
수동 작성 부담 큼).

**자동 코드 반영 없음** — 후보는 사람이 원문대조 후 수동 등재(R15~R33 워크플로우와 동일).

---

## R42. `bs.trade_payables` 정정본 하위라인 재구성이 남긴 stale 셀 오채택 — R16 계열의
신규 확인 사례(R41 lateral 스캔 후속)

**배경** — R41(위) 의 `trade_payables_additive` lateral 후보 15건을 원문대조하다 발견.
"2-라인 합" 이 아니라 **단일 셀 오채택**이었다 — `_NARROW_PREFER`/
`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`(R16) 와 **근본적으로 같은 트레이드오프의 신규
사례**, 새 버그 메커니즘이 아니다. 설계:
`docs/plans/gateb_trade_payables_stale_subline_r42_2026-08-21.md`.

**메커니즘** — 원본(최초등록본) BS 는 "매입채무 및 기타유동채무"(부모총계) 아래
"단기매입채무" 하위라인을 별도로 보여주는데, 정정본이 하위라인 구성을 바꾸면서(삭제하거나
각주번호만 추가) 같은 라벨의 셀을 다시 쓰지 않는다. **R2 정본 정책대로**(정정이 건드리지
않은 셀은 원본 유지) 그 stale 한 "단기매입채무" 셀이 후보 풀에 그대로 남고, exact-stage
alias 라 `_NARROW_PREFER`의 일반정책과 같은 이유로 정정본의 현재 부모총계보다 먼저
확정돼버린다.

**basis 의존성(신규 발견)** — `_TRADE_PAYABLES_ADDITIVE_OVERRIDE`(R17)는 "basis 는 별도
키 불필요"라 가정했으나, 쏠리드(00364403) 2015Q3 실측으로 이 가정이 깨진다 — 연결은
current 라벨이 정답, 별도는 non-current 라벨이 정답이다. 그래서 R42 의
`_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE` 는 **(corp, fy, period, basis) 4-튜플**로 키를
잡는다(`_resolve()` 에 `basis` 파라미터 신규 추가).

**`_CURRENT_STRICT` 우회 필요** — 일신석재(00146296)처럼 정답이 비유동인 경우, current
라벨(오답)이 후보 풀에 있으면 `_CURRENT_STRICT` 사전필터가 정답(비유동)을 먼저 지워버린다
→ override 는 `rows`(필터 후)가 아니라 `cands[canonical]`(필터 전 원본)에서 직접 검증된
라벨을 찾는다.

**0-값 중복 셀 함정(구현 중 실측 발견, 코스나인 00442455 2021Q3)** — 같은 rcept 안에
목표 라벨이 **두 번**(정상값 1건 + 스퓨리어스 0값 1건) 나타날 수 있다(원인 미상 파서
중복행, R2/정정과 무관) — `len(vals)==1` 판정 전에 0-값을 제외해야 한다
(`_reduce_conflict()`의 shallowest-depth 풀과 같은 관례).

**적용 범위 · 검증** — 14건(00626011 아이텍은 이미 알려진 R23 결함과 동일 corp라 제외) 전부
report_lines 정정 전/후 rcept 비교로 원문 계보 확인(2026-08-21). `build_std_v3.py --corp` +
`gateb_audit.py --recheck` 재실행으로 14건 전부 fail_detail 에서 `bs.trade_payables`
VALUE_DIFF 소멸 확인, 같은 corp 의 다른 전체 기간에 새 fail 0(pre-existing 미등재 사례만
잔존, 회귀 아님). `pytest tests/ fin2/tests/` 597건 통과(기존 무관 실패
`test_lxintl_facility_table_dropped` 1건 그대로, +5 신규).

근거: `fin2/layer3/combine.py::_resolve()`(`_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`) ·
`fin2/tests/test_combine_curated_overrides.py` · 메모리
`gateb-trade-payables-stale-subline-r42-2026-08-21`.

**★2026-08-29 추가(신규 인스턴스, 새 R번호 아님 — 같은 메커니즘)** — trade_payables
클래스B 트리아지([[gateb-trade-payables-45-triage-2026-08-28]])에서 이연제약
(00145598) 2025Q1(연결·별도 둘 다)이 R42 완료(2026-08-21) **이후** 접수된 필링이라
당시 스캔 대상이 아니었을 뿐, 원문대조 결과 정확히 같은 메커니즘으로 확인됨(원본
"매입채무" 7,837,235,184 vs 정정본 결합라벨 "매입채무 및 기타유동채무" 당기
14,467,303,399(연결)/14,421,377,063(별도) — DB 는 원본의 stale 셀을 채택하고
있었음). `_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`에 2줄 추가(레시피 동일, 새 코드
없음). 표본 재백필(`build_std_v3.py --corp 00145598`, 130행 무손실 확인)+재감사
(`--recheck`) → fail_a 1→0, 같은 corp 다른 130행 무변동. DB 전체: trade_payables
fail_a 17→15, face_audit 전체 fail_a 85→83. `pytest tests/ fin2/tests/` 632/633
pass(기존 무관 실패 1건 그대로). 근거 추가: `docs/plans/
gateb_trade_payables_classB_stale_column_investigation_2026-08-29.md` §2 · 메모리
`gateb-trade-payables-classB-two-bugs-2026-08-29`.

---

## R43. `account_mapper.py` 포괄손익 귀속 가드 — '포괄이익'/'포괄손실'(쪼개진 표기) 미포착
(NH투자증권 Gate B controlling_ni fail_b 근본원인, 2026-08-25)

**배경** — 옵션 A(R19/버그①) 전수 재감사 직후 pass/pending→fail_b 77건 중 75건이
NH투자증권(00120182) `controlling_ni` 하나에 몰려 발견. `read_report_face_xbrl()`
메인 ACODE 루프·`_ni_attribution_structural_candidates()`(R25) 둘 다 이 회사 표에서
빈 리스트 — XBRL 태깅 자체가 없는 표라 `read_report_face()` → `_supplement_with_text()`
(Track B 텍스트) → `account_mapper.map()` 라벨매핑이 최종값을 결정한다.

**근본원인** — 기존 "포괄손익 귀속 가드"(같은 파일, R24/25 인접 코드)는 문자열
`"포괄손익"`(붙임표기)만 검사했다. NH를 포함한 다수 필터社는 `"지배주주지분포괄이익"`
`"비지배지분포괄손실"`처럼 **"손익"이 아니라 "이익"/"손실"로 쪼개서** 표기 — 이 변형은
가드를 못 넘어 fuzzy 매칭(신뢰도 0.89~0.95)으로 `is.controlling_ni`/`is.noncontrolling_ni`
에 오매핑된다(총포괄이익 귀속 값이 순이익 귀속 자리를 오염 — NH FY2015 실측:
215,832백만 오답 vs 215,070백만 db_won 정답).

**연쇄 메커니즘** — 이 오탐이 `is.controlling_ni`/`is.noncontrolling_ni` 후보를
(틀린 값으로) 먼저 채우면, R35(`_with_ni_attribution_text_fallback()`)의 스킵
게이트("두 개념 다 있으면 스킵")가 오발동해 **정답을 정확히 찾는**
`_ni_attribution_text_candidates()`가 아예 호출되지 않는다 — 그 함수 자체는 처음부터
정답(215,070)을 정확히 반환하고 있었지만 정상 파이프라인에서는 도달 못 하는 코드였다.

**전수검사(과차단 위험 확인)** — SD카드 미러(`/Volumes/dart_data/raw_report`)
283,030개 XML 전체 → 1차 그렙(`"포괄이익"`/`"포괄손실"`) 30,449개 후보 → 실 추출게이트
(`read_report_face_text()`의 "라벨+숫자값 모두 있는 행"만)와 동일 조건으로 병렬(9워커)
정밀 파싱, 5,242건/2,778 filing/오류 0. 그중 `"지배"`+(`"포괄이익"`|`"포괄손실"`, 이미
가드된 `"포괄손익"` 제외)가 현재 `is.controlling_ni`/`is.noncontrolling_ni`로 오매핑된
건수 = **3,273건(254개사/2,778 filing)** — 증권사(삼성증권·대신증권·미래에셋증권·
교보증권·DB증권 등)뿐 아니라 일반 상장사(고려아연·LS·금호석유화학·DL·대한제강 등)까지
광범위. 전체 5,242건 중 `"순이익"`/`"당기순"`이 함께 들어간 하이브리드 라벨은 **0건**
— 가드 확장이 정답을 잘못 차단할 위험 없음을 확인 후 적용.

**현재 실 DB(Gate B) 영향 범위** — 254개사 중 실제로 `fail_b`로 잡히던 건 73건(대부분
NH)뿐 — 나머지 대다수는 Track A(XBRL)가 이 개념을 이미 커버해 Track B 텍스트 폴백
자체가 발동 안 되는 구조라 "잠재적/휴면" 오염이었다(당장 틀린 값은 안 나오지만 XBRL
태깅이 불완전한 새 filing 이 들어오면 같은 패턴으로 재발 가능).

**구현** — 가드 조건을 `"포괄손익"` 단독에서 `"포괄손익" or "포괄이익" or "포괄손실"`
(모두 `"지배"` 동반, IS 한정)로 확장. 새 분류 로직을 만들지 않고 기존 가드를 넓히기만
함(R24/25 계열과 같은 "무매핑으로 차단, 구조기반 후보보강이 대신 처리" 원칙).
`account_mapper.py` 는 `face_audit.py` 뿐 아니라 `fin2/layer3/combine.py`
(`_map_rows()`, R24)·`fin2/extract/text.py`·`fin2/extract/report_lines.py` 등
**실 DB 표준화 파이프라인에서도 공유**되므로, 이 수정은 감사도구뿐 아니라 실 데이터
경로의 잠재 리스크도 함께 줄인다.

**검증** — NH투자증권 FY2015 실 코드(몽키패치 아님) 재실행으로 `is.controlling_ni`
215,070백만(=db_won) 정확 복원 확인. `pytest fin2/tests tests/` 610 passed(기존 무관
실패 `test_lxintl_facility_table_dropped` 1건 제외, +3 신규 —
`test_account_mapper_comprehensive_income_guard.py`). `gateb_audit.py --corp 00120182
--recheck`: fail_b 27→0(전부 pass 로 회복), 신규 fail_a 0.

**소급 백필·Gate B 전수 재감사(2026-08-25 완료)** — 254개사 드라이런(트랜잭션
rollback, `fin2.layer3.build.build_corp`를 직접 호출하되 최종 `session.rollback()`
으로 프로덕션 무변경 확인)으로 실 영향 범위를 먼저 좁힘: 48개사·265행만 실제로
값이 바뀜(나머지 206개사는 R24 안전망이 이미 보호 중이었음 — 위 "미확정" 우려가
실측으로 해소됨). 205행은 NULL→값(결측 해소), 22행은 값→다른값(오염값 교정),
35행은 값→NULL(오염 제거, 결측>오염). **22건 전수 원문(report_lines) 대조 검증**
— 항등식 `controlling_ni + noncontrolling_ni = net_income`이 실제 공시값과 정확히
일치함을 다건 확인(윌비스·NC·KB금융 등, KB금융은 net_income 자체의 연쇄 오염까지
같이 교정됨). 검증 후 실 커밋(`build_std_v3.py --corp <254개사>`, 27,846행,
482초) → `gateb_audit.py --source v3 --corp-file <254개사> --recheck`. 전이표:
**fail_a 회귀 0건**(안전 기준 충족), fail_b→pass 22건·fail_b→pending 17건·
pending→pass 2건(개선 합계 41건), pass→pending 50건(오염값 제거로 인한 의도된
결측 전환), **pass→fail_b 1건**(DRB동일 00118266 — 아래 "신규 발견" 항목, R43과는
무관한 별개의 "계속영업" 라벨 자매가드 갭). 스크립트 =
`scripts/census_r43_comprehensive_income_labels_2026-08-25.py`(전수검사)·
`scripts/r43_comprehensive_income_guard_backfill_diff_2026-08-25.py`(드라이런+실커밋
겸용, `SessionLocal()` 직접 열어 rollback 가능). 스냅샷 테이블
`std_v3_snap_r43_20260825`·`face_audit_snap_r43_20260825` 존치 중.

근거: `parser/common/account_mapper.py`(라인 191 인접 가드) ·
`fin2/tests/test_account_mapper_comprehensive_income_guard.py` · 메모리
`gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25`.

---

## R44. '계속영업' 귀속 성분 자매가드 — DRB동일(00118266) 부수발견 후속조사
(2026-08-25, R43 254개사 Gate B 재감사 중 pass→fail_b 1건에서 시작)

**배경** — `account_mapper.py`의 "지배/비지배 귀속 중단영업 성분 가드"(2026-08-23,
케이엔더블유 00606664)는 `"중단"` 한정어만 검사해 **대칭 케이스인 `"계속영업"`을
놓쳤다**: DRB동일 FY2012 연결 IS에서 `"지배기업의 소유주에 귀속될 계속영업당기순이익"`
(부분값, 18,327,708,908)이 헤드라인 합산(계속+중단, `"지배기업의 소유주에게 귀속되는
당기순이익(손실)"`=29,912,789,124) 대신 `is.controlling_ni`로 채택됐다.

**1단계 수정(구현·검증·커밋됨)** — `account_mapper.py`의 해당 가드 조건을 `"중단"`
단독에서 `"중단" or "계속영업"`(모두 `"지배"`+속성 한정어 동반, IS 한정)으로 확장.
`fin2/tests/test_account_mapper_discontinued_attribution_guard.py`(4건) 신설.
전수검사(SD카드 미러, `"계속영업"` 포함 20,523개 후보 파일 → 실 추출게이트 동일 정밀
파싱 10,155건/436개사, 오류 0): 과차단 위험 사실상 0건(유일한 non-unknown 매치는
병합표 추출결함 1건, 이 가드와 무관 — T2류 기존 함정).

**2단계 조사(구조적 우회 발견, 시도했다 되돌림)** — 위 라벨가드만으로는 DRB동일 값이
전혀 안 바뀜을 실측으로 확인(old-code/new-code 격리 리빌드 diff, 436개사 전체 0건
변화). 원인: `fin2/layer3/combine.py::_ni_attribution_structural_candidates()`가
section_path(구조)만 보고 라벨 텍스트를 무시해 — `"계속영업당기순이익"`이라는
section_path가 `"순이익"`+`"포괄"`부재 필터를 통과, 라벨가드로 막힌 행을 section_path
기반으로 **다시 후보 풀에 채워넣어 무력화**했다. 대칭적으로 `"계속영업"`/`"중단"`도
그 필터에서 배제하는 수정을 시도했으나, **시알홀딩스(00148984) FY2015에서 새 회귀를
유발함을 실측으로 확인하고 되돌렸다**: 그 회사는 section_path만 성분(`"계속영업
당기순이익"`)이고 라벨 자체는 이미 깨끗한 헤드라인 문구(`"지배기업의 소유주에게
귀속되는 당기순이익(손실)"`)라 account_mapper 라벨매칭이 단독으로(성분값임을 못 보고)
그 값을 채택하는데, 이 section이 구조적 후보 풀에 남아있는 덕분에(다른 section_path
`"중단영업 당기순이익"`과 값이 달라 conflict 유발) 그동안 NULL(안전)로 held 됐었다 —
배제하면 유일후보가 되어 오히려 확신에 찬 오값으로 확정된다(NULL→오염, 결측>오염
원칙 위반). 즉 이 필터 하나로는 "라벨은 깨끗한데 section_path만 성분"인 케이스(시알
홀딩스, 안전망 필요)와 "라벨도 section_path도 성분"인 케이스(DRB동일, 안전망이 오히려
헤드라인 후보를 가림)를 구분 못 한다.

**남은 것(다음 세션, 설계 재작업 필요)**:
1. `_ni_attribution_structural_candidates()`의 section_path 필터 자체가 아니라
   `_resolve()`의 단일후보 자동확정 분기(또는 `_resolve_ni_attribution`)에서
   `"계속영업"`/`"중단"` section 유래 후보를 "신뢰 대상에서는 빼되 conflict 유발
   용도로는 유지"하는 식으로 더 정밀하게 재설계해야 함 — 후보 풀 자체를 건드리는
   방식은 위 트레이드오프 때문에 위험.
2. 조사 중 발견한 **별개의 두 결함**(DRB동일 자체를 완전히 못 고치는 잔여 원인,
   범위 밖으로 분리):
   - (c) 맨몸(bare) `"...에게 귀속되는 지분"` 라벨이 `"귀속"` 키워드를 포함해
     bare-지배지분 가드(2026-08-22)의 예외 조건("귀속" 포함 시 가드 미발동)를 타고
     빠져나가 fuzzy(0.907)로 `is.controlling_ni`에 오매핑됨 — 원래 총포괄이익 귀속
     서브라인인데 라벨 자체엔 `"포괄"`이 없어(부모 section_path에만 있음) 기존
     포괄손익 가드(R43)도 못 잡음.
   - (d) `_derive_net_income_from_ebt()`(EBT−tax 앵커)가 IFRS5식으로 중단영업을
     세후 단일라인으로 별도 표시하는 회사(=계속영업세전이익만 EBT로 표기)에서
     "계속영업만의" net_income을 앵커로 써버려 identity 대조 자체가 무의미해짐 —
     중단영업이 있는 회사 전반에 걸친 구조적 한계, DRB동일 국한 아님.
3. 위 2건 모두 **아직 미착수**. DRB동일 자체는 이번 세션 수정으로 "확신에 찬 오값"
   에서 "NULL(REVIEW 필요)"로 후퇴하긴 했으나(1단계 라벨가드 자체는 커밋됐지만
   std_v3 에는 2단계가 되돌려져 실질 효과 없음 — 여전히 fail_b 상태로 남음), 완전
   해결은 위 1~2 항목 설계 완료 후로 이연.

**실측 커밋 범위**: `account_mapper.py` 라벨가드(1단계)만 실제 코드 변경 — 436개사
전체에 대해 old-code/new-code 격리 리빌드 diff **0건**(std_v3 실 영향 없음, 순수
방어적 하드닝). 단 `fin2/audit/face_audit.py`는 `account_mapper.map()`을 직접
호출하는 지점이 있어(736·884·960행) Gate B 감사 정확도에는 잠재적으로 도움이 될 수
있음(미검증) — `face_audit.py`의 구조적 후보 함수(`_ni_attribution_structural_
candidates`, 265행 `_NI_TOTAL_RE`)는 앵커 정규식이 `"계속영업"` 접두 라벨과 애초에
매치 안 돼(`^당?(기|분기|반기)순(이익|손익)`) 이 특정 우회로부터는 구조적으로 이미
안전. `pytest fin2/tests tests/` 615 passed(기존 무관 실패 1건 제외, 순증 +4/-2 =
net +2 신규, `test_account_mapper_discontinued_attribution_guard.py` 4건 신규 +
`test_combine_ni.py` 순증 2건).

근거: `parser/common/account_mapper.py`(중단/계속영업 귀속 성분 가드) ·
`fin2/layer3/combine.py::_ni_attribution_structural_candidates()`(주석만, 로직
불변) · `fin2/tests/test_account_mapper_discontinued_attribution_guard.py` ·
`fin2/tests/test_combine_ni.py` · 스크립트
`scripts/census_continuing_ops_attribution_labels_2026-08-25.py`·
`scripts/continuing_ops_isolated_diff_2026-08-25.py`·
`scripts/verify_continuing_ops_val_to_val_2026-08-25.py` · 메모리
`gateb-continuing-ops-attribution-sibling-guard-2026-08-25`.

---

## R45. `fin2/layer3/combine.py::_resolve_ni_attribution()` — net_income 앵커
재설계, DRB동일(00118266) `is.controlling_ni` 근본수정(2026-08-25, R44 후속)

**배경/근본원인** — R44가 남긴 미해결 과제("DRB동일 자체는 여전히 fail_b")를
이어받아 조사한 결과, `cands["is.controlling_ni"]`엔 이미 정답(exact stage,
29,912,789,124)이 들어 있음을 확인했다. 확정을 가로막은 건 `_resolve()`가
아니라 그 다음에 도는 `_resolve_ni_attribution()`의 EBT−tax 폴백 앵커
(`_derive_net_income_from_ebt`)였다: DRB동일의 `"법인세비용차감전순이익
(손실)"` 라인은 **계속영업만의** 세전이익인데(라벨 자체엔 아무 표식도
없음), 앵커 계산이 이를 회사 전체로 착각해 `EBT−tax`가 우연히 "계속영업
성분(controlling)+계속영업 성분(nci)"과 정확히 일치 → identity 매치가
"유일 매치"로 확정되어 확신에 찬 오값(18,327,708,908)이 나왔다.

**설계안 §A(기각)** — `_resolve()`의 `_NI_ATTRIBUTION_CANON` 분기에 "성분
(계속/중단/포괄 마커) vs 비성분" 분리 후 비성분 후보만 stage-rank로 확정하는
안. 436개사 격리 diff로 실측했으나, **00372226**(계속/중단 구분 자체가 없는
회사인데 exact-stage 비성분 후보가 net_income과 4.4십억원 불일치 — 기존
identity 검증이 정상적으로 NULL 보류 중이던 걸 §A가 우회해 확신에 찬 오답을
만듦)이 결정적 반례로 나와 **identity 검증을 우회하는 설계 자체가 안전하지
않음**이 실증되어 기각.

**설계안 §B(채택)** — `_resolve()`는 전혀 건드리지 않는다(기존 identity
검증 100% 보존). 신설 `_derive_net_income_from_continuing_discontinued()`
(`_map_rows()`가 IS 스코프에서 매 호출마다 계산해 `cands["__ni_total_anchor__"]`
로 주입 — DIRECT_MAP에 없는 내부 전용 키라 `_resolve()`를 무해하게 통과)가
"계속영업(류) 총계 + 중단영업(류) 총계"(귀속분리 **전**, section_path IS
None인 회사 전체 합계 라인, account_mapper 우회 직접 스캔)를 합산해 새
net_income 앵커를 만든다. 동의어는 report_lines 전수 census(계속영업/계속
사업/계속기업 3종, 중단영업/중단사업 2종, 로마숫자 접두 다수 — 스크립트
`scripts/census_continuing_total_labels_2026-08-25.py`·
`census_gyesokgiub_2026-08-25.py`)로 확인해 `"계속"`/`"중단"` 단일문자
substring 하나로 전부 포괄한다(enumerated list 안 씀).

`_resolve_ni_attribution()`은 이 §B 앵커가 있으면 **먼저 단독으로 시도**
하고, 매치가 전혀 없을 때만(union 아님, 순차 폴백) EBT−tax(§A)를 시도한다.
§B 앵커 함수 자체에도 두 겹 자체 억제 가드가 있다: (1) section_path IS
None에 계속/중단/포괄 수식어 없는 순수 헤드라인 순이익류 라인이 **따로
존재하고** 그 값이 계속+중단 합과 **다르면** 앵커를 None으로 억제(00401731
2011H1/Q3 반례 — 이 필자는 `"중단영업이익(손실)"`이 H1·Q3에 걸쳐 완전
동일값인 1회성 메모성 수치라 헤드라인에 아예 안 더함), (2) 그 헤드라인
후보가 **2개 이상**(모호)이면 무조건 억제(00103547 2020Q1 반례 — 같은 표에
`"당기순이익"`과 `"분기순이익"`이 서로 다른 값으로 공존하는 원문 자체
모호 케이스, 합이 우연히 하나와 일치한다고 그게 정답이라는 보장 없음).
§A로의 순차 폴백은 00238782 2014Q3(§B 앵커는 있지만 이 필자의 귀속 섹션이
계속영업만 반영해 §B와는 안 맞고 §A와는 정확히 일치하는 반례)에서 필요성이
드러났다 — union이면 DRB동일에서 §A의 스코프오염 매치가 §B의 정답 매치와
경쟁해 다시 모호함(NULL)으로 후퇴함을 실측 확인, 순차 폴백만이 양쪽을 다
안전하게 만족시킨다.

**실측** — 1,440개사(report_lines 전수, IS 스코프 `계속`/`중단` 라벨 보유
corp, 근사치였던 R44의 436개사보다 정밀) 격리 diff(old-code rebuild vs
new-code rebuild, DB 커밋값과 무관): **19행 변경, 7개사, 회귀 0건.** 전부
원문 자체의 회계 항등식(계속+중단=직접보고 헤드라인, 또는 지배+비지배=총계)
으로 개별 검증 완료. 00118266(DRB동일) 2012FY controlling_ni:
18,327,708,908(오답)→**29,912,789,124**(정답) 등 5개사는 최초 216개사 표본
에서, 00238782·00103547 발견 이후의 두 자체 억제 가드는 전체 1,440개사
백필 검증 중 발견·수정했다(두 회사 모두 diff에서 완전히 사라짐 — 구코드와
동일 결과로 안전 복원, 회귀 아님).

**소급 백필** — `build_std_v3.py --corp <1,440개사> --year-min 2000`
4-way 샤딩(오류 0, 213,813행). 최종검증(old-code rollback rebuild vs
재백필 후 DB, 1,440개사 전체): 19행 변경, 신규 이상 0건.

**Gate B 재감사** — `scripts/gateb_audit.py --source v3 --recheck`(값이
실제로 바뀐 7개사, 846행). **fail_a(차단) 신규 회귀 0건.** DRB동일 포함
4행이 face_audit의 독립 리더(raw XBRL 직접 재구현, combine.py와 무관)로
정답 재확인됨 — 원문 항등식에 이은 2차 독립 검증. 2행은 안전하게 pending
(계속+중단 합산 유도값이라 단순 라벨매칭 리더가 증거를 못 찾을 뿐 — 이전엔
필드가 NULL이라 무검증 pass였던 것보다 오히려 정직). **예외 1건**:
01137383 2024Q3은 R45 값(원문 항등식 2건으로 이중검증)과 face_audit 리더
값이 불일치(fail_b) — `face_audit.py::_ni_attribution_structural_candidates()`
가 combine.py 동명함수를 "미러링만 하고 독립 재구현"하는 별도 컴포넌트라
이번 §B 수정이 전혀 반영 안 됨. **별개 컴포넌트 이슈로 분리, 미착수**
(아래 부록 C).

근거: `fin2/layer3/combine.py`(`_derive_net_income_from_continuing_
discontinued()`·`_resolve_ni_attribution()`) · `fin2/tests/test_combine_ni.py`
(9건 신규) · `docs/plans/gateb_r44_resolve_redesign_2026-08-25.md` ·
스크립트 `scripts/census_continuing_total_labels_2026-08-25.py`·
`scripts/census_gyesokgiub_2026-08-25.py` · 메모리
`gateb-r44-resolve-redesign-2026-08-25`. 커밋 `ed4ffa4`(§B 초판)·
`287100e`(§B→§A 순차폴백+헤드라인 모호성 가드)·`87e07c4`/`82fd1cb`/`7719b0a`
(문서).

## R46. `fin2/audit/face_audit.py::_with_ni_attribution_text_fallback()` —
NI 귀속 스킵게이트 결함 수정, 171건/26개사(2026-08-26, R45 후속)

**배경** — R45 Gate B 재감사 중 발견된 예외 1건(01137383, 위 R45 항목·
부록C)을 조사하다 `face_audit.py` is.controlling_ni fail 247건(fail_b 245
+ fail_a 2) 전체로 스코프를 넓혀 원문 XML 직접 실행 대조(추측 없음, 스크립트
`scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py`)로 재분류했다.

**근본원인** — `_with_ni_attribution_text_fallback()`이 `is.controlling_ni`/
`is.noncontrolling_ni`가 이미 `lines`에 있으면(옳든 그르든) 섹션 헤더 기반
구조인식 함수(`_ni_attribution_text_candidates()`, R35)를 아예 안 불렀다.
일반 라벨매퍼(`account_mapper.map()`)가 총포괄손익 귀속 섹션을 순이익
귀속으로 먼저 오매핑해 두 canonical을 채워버리는 문서에서, 정답을 정확히
아는 구조인식 함수가 호출 기회 자체를 못 얻었다. 원문실측으로 확인된
오매핑 경로 2종:
- **변종A**: `account_mapper.py`의 bare 지배지분 가드(`endswith("지분")`)가
  트레일링 마침표(`"지배기업 소유주지분."`, EUC-KR 문서 필자 관행)에
  우회당해 fuzzy로 is.controlling_ni(0.93)에 오매핑(00913689 세경하이테크
  2021H1 실측).
- **변종B**: `"…지분순이익(손실)"`류 라벨은 "포괄"/"중단"/"계속영업"
  리터럴이 없어 기존 가드 어디에도 안 걸리고 정상 alias로 통과 —
  총포괄손익 귀속 섹션인데도 라벨만으론 구분 불가(01137383 카카오게임즈·
  00117027 알루코 실측). 부수발견(알루코): `"지배회사지분순이익"`이 fuzzy로
  **is.noncontrolling_ni**(0.88, 방향까지 틀림)에, `"지배기업소유주지분
  합계"`(BS 자본총계 개념)가 is.controlling_ni(IS 개념, 0.91)에 오매핑되는
  제3의 하위패턴도 확인 — 오늘 스코프(controlling_ni) 밖, 미조치.

**수정** — 스킵게이트를 제거하고 구조인식 함수를 항상 추가 실행(선택이
아니라 순수 가산). `audit_fields()`의 PASS 판정이 "후보 집합 어디든
일치하면 성립"(`val in won_vals`)이라 이 변경은 기존 후보를 하나도 지우지
않는 단조 개선 — 새 오탐을 만들 수 없다.

**실측/검증** — 247건 원문실행대조 분류: CONFIRMED_PATTERN(=수정으로
해소 가능) 171건/26개사, REPRODUCED_BUT_STRUCT_FUNC_ALSO_MISSES(=R47
사각지대, 아래 별도) 70건(01137383·fail_a 2건 포함), NOT_REPRODUCED 4건
(이 결함과 무관, 파일변경 의심), NO_XML_FILE 2건(도구 한계). 수정 후
Gate B 재감사(38개사, source=v3, fy≥2010, 4260행, 드라이런→실커밋 동일
결과): pass 3113→3272(+159) · fail_b 253→78(−175) · **fail_a 10→10
(변화 없음, 회귀 0건)** · pending 884→900(+16, 전부 안전한 방향). `pytest
fin2/tests/ tests/` 624 passed(무관 기존실패 1건 제외, 신규 회귀테스트 1건
포함).

**미해결(R47로 분리, 부록C)** — 70건(01137383 포함)은 정답 행이 `<TE>`
태그(ACODE 없음)로 렌더링돼 TE 전용 구조함수(ACODE 필수)와 TD 전용
구조함수("TE 있는 행은 자매함수가 처리했다"고 가정하고 skip) 양쪽 다에서
빠지는 별개 사각지대 — 이 수정으로는 안 풀린다. 설계는
`docs/plans/faceaudit_ni_attribution_skipgate_design_2026-08-26.md` §2-B
(미확정, 별도 승인 필요).

근거: `fin2/audit/face_audit.py::_with_ni_attribution_text_fallback()` ·
`fin2/tests/test_ni_attribution_text_fallback.py`(신규 회귀 1건) ·
`scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py` ·
`docs/plans/faceaudit_ni_attribution_skipgate_design_2026-08-26.md` ·
메모리 `faceaudit-ni-attribution-skipgate-2026-08-26`. 커밋 `5f07d39`.

---

## R54. `fin2/audit/face_audit.py::read_report_face_xbrl()` — 회사고유 확장(UDF)
acode 라벨매칭 폴백, `bs.trade_payables` 25건 해소(2026-08-28~29)

**배경** — [[gateb-trade-payables-45-triage-2026-08-28]] 세션에서 trade_payables
fail_a 45건을 원문 리터럴 대조(`re.escape(db_won)` + 콤마포맷)로 4클래스 분류한 것 중
**클래스A(24건, 이후 실측으로 25건 확정)**를 해소.

**근본원인** — BS face 본문의 진짜 매입채무 행이 회사·타임스탬프별 고유 확장(UDF)
acode(`entity{corp8}_udf_BS_{timestamp}_CurrentLiabilities` 류, 또는
`entity{corp8}_AccountsPayableOfCurrentLiabilities` 처럼 타임스탬프 없는 변형)를
쓴다. 이 접미사는 **의미가 없다** — KX(00657987) 원문에서 같은 접미사 패턴
(`OfCurrentLiabilities`)이 기타의투자자산·매각예정자산·장기차입금 등 전혀 다른
계정에도 재사용되는 것을 확인 — 그래서 R53(inventory/ppe)처럼 정적 acode alias
사전으로는 원천적으로 해결 불가. `read_report_face_xbrl()`의 admission gate
(`acode.startswith(_XBRL_PREFIXES)`, `_XBRL_PREFIXES=("ifrs-full_","dart_")`)가
`entity...` 접두 acode를 애초에 전부 걸러내 후보 집합에서 탈락 → 유일 후보로 남는
다른 계정(장기매입채무 등)과 대조돼 VALUE_DIFF(fail_a) 오탐.

**수정** — acode 사전이 아니라 **같은 `<TR>` 행의 라벨 셀(형제 TE, ACODE 없음)
텍스트**로 정체를 확인하는 좁은 admission-gate 예외를 추가했다. 10개사 원문 확인
결과 라벨은 공백(일반/전각 `　`) 제거 시 정확히 3종으로 수렴: `매입채무` ·
`매입채무및기타채무` · `유동매입채무`(폐집합 exact-match — 부분일치는 "장기매입채무"
같은 무관 계정 오염 위험이 있어 배제). `entity\d{8}_` 접두이면서 라벨이 이 3종
중 하나일 때만 `canonical="bs.trade_payables"`로 admit — 그 외 entity acode는
기존과 동일하게 skip(스코프 확대 없음, 다른 필링의 Track A/B 선택에 영향 없음).

★ **설계 초안의 함정** — 최초안은 `_map_acode_face(acode, te)`처럼 acode 매핑
함수 안에서 라벨을 확인하려 했으나, 이 함수에 도달하기도 전에 admission gate
(`_XBRL_PREFIXES` 미포함)가 `entity...` acode를 전부 걸러내 실행조차 안 됨을
표본 재감사(`--no-commit`)에서 fail_a 불변으로 실측 발견 — **admission gate
자체를 좁게 여는 방식으로 재설계**했다. 짐작으로 "될 것"이라 판단하지 말고
반드시 실제 코드 경로로 검증할 것([[feedback-verify-against-source]]).

**안전성** — `audit_fields()`의 PASS 판정이 `val in {후보집합}`(소속검사)이라
후보 추가는 순수 가산 — 기존 PASS를 깨뜨릴 수 없다(R53과 동일 원칙, 코드 주석
face_audit.py L781 참고).

**실측/검증** — class A 10개사 25건 표본(`--corp-file`, `--no-commit`) fail_a
25→0, 회귀 0. 400개사 무작위 표본(seed=42, 39,792행) fail_a 15건 — 전부 이번
수정과 무관한 기존 클래스B/C/기타. 전수 재감사+커밋(2,532개 활성사, 약 6시간)
결과 DB `fail_a` **113→88**(정확히 25건 해소, trade_payables 45→20).

★ **부수 함정 1건** — 일정실업(00146542)은 전수 재감사 직후에도 DB에 stale
fail_a 2건이 남았다(`checked_at`이 재감사 시작 이전 — R37(`select_corps()`가
상장폐지사를 감사 유니버스에서 제외) 때문에 이 회사가 **전수 재감사에 아예
포함되지 않음**, 코드 버그 아님). `--corp 00146542 --recheck`로 단독 재감사해
해소(fail_a 90→88). **교훈**: 전수 재감사 후 DB 카운트가 예상과 안 맞으면
상장폐지사 제외 유니버스부터 의심할 것.

근거: `fin2/audit/face_audit.py::read_report_face_xbrl()`(admission gate +
`_ENTITY_EXT_ACODE_RE`/`_TRADE_PAYABLES_ROW_LABELS`/`_row_label_text()`) ·
`docs/plans/gateb_trade_payables_classA_udf_acode_label_fallback_design_2026-08-28.md` ·
메모리 `gateb-trade-payables-classA-label-fallback-design-2026-08-28`.

---

## R55. `account_maps/bs_accounts.py` — `bs.trade_payables` 결합형 alias의
퍼지 포함관계 오매핑 alias 갭 메움, 39개사/339행 해소(2026-08-29)

**배경** — [[gateb-trade-payables-45-triage-2026-08-28]] 클래스C 3건 중
종근당홀딩스(00149354, 지주회사) 2건을 원문 대조하다 발견. 클래스C의 나머지
1건(갤럭시아에스엠)은 원인이 정반대(face_audit acode-라벨 뒤바뀜 오탐, DB는
정답)라 별도 트랙 — 이 R55는 다루지 않는다.

**근본원인** — 종근당홀딩스 별도 BS엔 "매입채무" 라인 자체가 없다(순수 지주회사).
있는 건 "미지급금"·"기타유동채무"뿐인데, `parser/common/account_mapper.py::
_fuzzy_match()`의 Stage3 포함관계 규칙이 `bs.trade_payables`에 등록된 **결합형
alias** `"매입채무및기타유동채무"`/`"매입채무및기타비유동채무"`(2026-07-18 승급분)의
**뒷부분이 그대로 원문 라벨과 문자 그대로 일치**하는 것을 이용해 "매입채무" 부분이
실제로는 없는데도 오매핑한다(포함관계 점수 0.90+len_ratio·0.09 — "매입채무" 토큰
존재 여부는 검사 안 함). "기타유동채무"/"기타비유동채무"는 형제 라벨("미지급금"·
"기타채무"·"기타지급채무")과 달리 `bs_accounts.py`에 단독 alias로 등록돼 있지
않아 Stage1/2를 못 거치고 Stage3까지 흘러갔다.

**파급범위 실측** — `report_lines` 전수 SQL 스캔(같은 필링·basis 안에 진짜
"매입채무" 라벨이 전혀 없는데 `std_financials_v3.trade_payables`가 이 값과 정확히
일치): **339행 · 39개사**. 트리아지의 "2건"은 face_audit이 acode로 report_won을
찾을 수 있어 fail_a로 뜬 것만 잡은 것 — 나머지 337행은 face_audit도 acode를 못
찾아 **Gate B가 못 잡던 잠복 오염**(표본 00132354=쿠쿠홀딩스도 지주회사로 확인,
가설과 부합).

**수정** — `account_maps/bs_accounts.py`에 "기타유동채무"→`bs.other_current_payables`,
"기타비유동채무"→`bs.other_noncurrent_liabilities` exact alias 2줄 추가(둘 다
`std_financials_v3`에 저장 컬럼 없는 흡수용 버킷 — 신규 canonical 도입 없음). Stage1이
Stage3보다 먼저 실행되므로 이 두 alias 등록만으로 결합형 alias의 포함관계 매칭에
영영 도달하지 않는다 — `_fuzzy_match()` 엔진 자체는 불변, 순수 사전 갭 메우기.

**안전성** — 이 두 canonical은 저장 컬럼이 없어 alias 추가가 새로 값을 오염시킬
위험이 없다. 유일한 효과는 `bs.trade_payables` 후보 풀에서 잘못된 후보가 사라지는
것 — 39개사 재백필 결과 339행 중 337행이 정확히 NULL(결측, "결측>오염" 원칙대로
안전한 미확정 처리)로 전환됐고, 나머지 2행(01021949)은 같은 필링의 다른 정당한
후보(비교기간 컬럼의 진짜 결합라벨 후보)로 값 불변 유지 — 정보 손실 없이 오염만
제거됨을 확인.

**실측/검증(39개사 표본)** — 39개사 std_v3 재백필(`build_std_v3.py --corp ...`,
4,228행) → 스냅샷(`gateb_snap_classc_pre_20260829`) 대비 diff로 위 337/2 결과 확인.
39개사 Gate B 재감사(`--corp-file`, `--recheck`) → trade_payables fail_a **0건**
(종근당홀딩스 2건 포함 완전 해소), 신규 회귀 없음. `pytest fin2/tests/ tests/`
632/633 pass(기존 무관 실패 1건, R54와 동일 — `test_lxintl_facility_table_dropped`).

**전수 재백필/재감사(완료, 커밋 `82c501e` 이후)** — `build_std_v3.py --all`
5-shard 병렬(`scripts/run_build_std_v3_parallel.sh`, 신규) 2,546개사·303,887행,
에러 0. 전수 오염 스캔 재실행 결과 339행/39개사 → **2행/1개사**(01021949 — 다른
정당한 후보로 값 유지되는 케이스, §3에서 이미 확인한 무해 잔존)로 감소, 신규
오염 0. `gateb_audit.py --all --recheck` 5-shard 병렬
(`scripts/run_gateb_audit_parallel.sh`) 2,546개사·303,887행 감사, 에러 0 —
DB `face_audit` fail_a **88 → 86**(정확히 2건 해소), trade_payables fail_a
**20 → 18**(클래스B 14 + 기타 3 + 갤럭시아에스엠형 1, 트리아지 예상과 정확히
일치, 신규 fail_a 0). 트랙 종료.

근거: `account_maps/bs_accounts.py`(`bs.other_current_payables`/
`bs.other_noncurrent_liabilities` 항목) ·
`docs/plans/gateb_trade_payables_classC_accountmapper_containment_alias_gap_design_2026-08-29.md` ·
메모리 `gateb-trade-payables-classC-rootcause-2026-08-29`.

---

## R56. `fin2/audit/face_audit.py` — 갤럭시아에스엠 라벨-acode 뒤바뀜
1건 curated 예외로 face_audit 오탐 해소(2026-08-29)

**배경** — [[gateb-trade-payables-45-triage-2026-08-28]] 클래스C 3건 중 마지막
1건(갤럭시아에스엠 00129554, 2026H1 연결). R55(종근당홀딩스형)와 겉보기 증상은
같지만(원문 당기 컬럼에 db_won이 리터럴로 존재, acode는 매입채무와 무관) 원인이
**정반대** — 이번은 std_v3(DB)가 정답이고 face_audit(검증기)이 오탐이다.

**근본원인** — 2026H1 연결 BS 원문(`20260814002461.xml` L3260-3282, 원문대조
확인)에서 필자(공시대리인)가 라벨과 acode를 서로 바꿔 태깅했다: "단기매입채무"
라인(매입채무 계열, `bs_accounts.py` exact alias로 정확히 등록됨)에 엉뚱한
acode(`ifrs-full_OtherCurrentFinancialLiabilities`)를, 매입채무와 무관한
"기타유동채무" 라인에 표준 매입채무 acode(`ifrs-full_TradeAndOtherCurrentPayables`)를
붙였다(전기 비교컬럼도 동일 패턴 — 체계적 오태깅). 별도(separate) 기준(L9398)엔
같은 금액(172,864,613)이 정상 alias(`dart_ShortTermTradePayables`)로 "단기매입채무"에
태깅돼 있어 교차확인됨. std_v3(AccountMapper)는 acode 를 보지 않고 라벨 텍스트로
판별해 정답(172,864,613)을 잡았고, face_audit(`read_report_face_xbrl()`)은 acode를
신뢰해 오태깅된 값(1,483,956,477)을 후보로 채택 → false VALUE_DIFF(fail_a). 별도
basis는 `dart_ShortTermTradePayables` 정상후보가 함께 있어 membership 대조로 이미
PASS(영향 없음) — consolidated 1건만 영향.

**수정** — 일반 라벨힌트 가드 대신(설계문서 §2 "대안" 채택) 이 필링 1건만 curated
예외로 등록. `face_audit.py`에 `_TRADE_PAYABLES_ACODE_LABEL_SWAP_KEYS =
{("00129554", 2026, "H1", "consolidated")}` 추가, `bs.trade_payables` 후보 비교
직전(`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`/R23 와 같은 자리) 이 키에 해당하면
`acode == "ifrs-full_TradeAndOtherCurrentPayables"` 후보를 배제. std_v3 변경 없음 —
face_audit 코드만 수정, 재백필 불필요.

**안전성** — 4-튜플 키가 정확히 이 1건만 가리켜 다른 회사 acode 신뢰도는 전혀
건드리지 않는다(R23/R55 후속 부수효과와 무관, 순수 additive). 배제 후 정답
("단기매입채무")은 정상 acode 가 없어 후보 자체가 없으므로 fail_a 가 아니라
LABEL_UNMATCHED(pending)로 남는다 — VALUE_DIFF(확정 오류)를 주장하지 않는
보수적 처리.

**실측/검증** — 원문(raw_report) L3260-3283 재확인으로 XML 값 그대로 일치.
`--corp 00129554 --recheck --no-commit` 드라이런: 이 필링만 fail_a 1→0, 다른
131행 무변동. Phase B 라인 전수대조 fail_a 7건은 수정 전/후 동일(무관, 회귀
아님). `--corp 00129554 --recheck`(커밋) 실행 후 DB 확인: 해당 행 status
`fail`→`pending`. DB 전체 latest-snapshot 집계: `trade_payables` fail_a
**18 → 17**, `face_audit` 전체 fail_a **86 → 85**(정확히 1건 해소, 신규 0).
`pytest fin2/tests/test_face_audit.py` 52/52 pass.

근거: `fin2/audit/face_audit.py`(`_TRADE_PAYABLES_ACODE_LABEL_SWAP_KEYS`) ·
`docs/plans/gateb_trade_payables_classC_faceaudit_acode_label_swap_design_2026-08-29.md` ·
메모리 `gateb-trade-payables-classC-rootcause-2026-08-29`.

---

## R57. `fin2/layer3/combine.py::_resolve()` — `_CURRENT_STRICT` 탈락분을
`_NONCURRENT_SIBLING`으로 재라우팅(B1-D1, `net_debt` 회복) — **구현+단위테스트+
전수재감사 완료(회귀 0), 단 net_debt 잔여격차 대부분은 별도 원인(순서4 범위
재검토 필요)**(2026-08-30~31)

**배경** — [[valuation-daily-blockers-rootcaused-2026-08-30]] §2. `net_debt =
short_term_debt + long_term_debt − cash`인데, v3의 `bs.short_term_debt`/
`bs.long_term_debt` FY2024/2025 불일치율이 67.6%/69.6%로 절벽을 이룬다(P1A/lease·
borrowings 분해와는 **무관** — 그 세 컬럼은 이 식에 안 들어감, 실측 확인).

**근본원인** — `_CURRENT_STRICT`(경남제약형 오염 방지 가드, R… 계열)가 `_is_noncurrent()`
로 `section_path='부채>비유동부채'`를 읽고 `bs.short_term_debt` 후보에서 **제외만
하고 짝 canonical로 재라우팅하지 않는다** → 금액이 소실된다. 실측(`00130763` FY2024
연결): 라벨 `차입금`(장기 표기 없음)이 `bs.short_term_debt`에 exact 매핑 → 가드가
제외 → `bs.long_term_debt` 미도달 → `net_debt`가 정확히 101,825,482,368 부족.
std_v2는 XBRL acode(`dart_LongTermBorrowingsGross`)로 만기를 알았지만, v3는 라벨
텍스트만 보고 `section_path`가 가진 같은 신호를 버리고 있었다.

**수정** — `_NONCURRENT_SIBLING = {"bs.short_term_debt": "bs.long_term_debt",
"bs.current_bonds": "bs.bonds"}`를 신설, `_resolve()` 본문 루프 **앞**에 pre-pass로
적용(설계문서는 `_CURRENT_STRICT` 필터 두 자리(`:1749`/`:1607`)에서 인라인 처리를
제안했으나, canonical 순회 순서가 보장되지 않고 `cands`에 없던 키를 순회 도중 추가하면
`RuntimeError`가 나므로 **pre-pass로 구현 방식을 변경** — 순서 무관하게 짝
canonical이 항상 재라우팅된 후보를 보게 됨).

**가드 4가지** (설계문서는 3가지, 구현 중 1가지 추가 발견):
1. 짝 canonical에 이미 후보가 있으면 추가 안 함(이중계상 방지).
2. **(설계문서에 없던 가드, 필수)** `_src`(예: `bs.short_term_debt`)의 후보가
   **전부** 비유동이면 재라우팅 안 함 — 기존 `_is_noncurrent()`의 "current 후보가
   하나도 없으면 그대로 둔다"(MISSING 방지) 안전장치가 이미 있어, 그 경우 그 행은
   **`_src` 자신의 확정값으로도 쓰인다** — 짝 canonical에 사본을 추가하면 회복이
   아니라 **2배**가 된다.
3. `label_raw`에 이미 `장기`/`비유동`이 있으면 추가 안 함(`section_path`만으로
   비유동인 행, 즉 `00130763`형만 대상 — `_is_noncurrent_by_section_only()`).
4. `rule_additive_debt`(`fin2/standardize/rules.py:282`)의 `total_liabilities×1.05`
   이중계상 가드 확인 결과: **v3(combine.py)는 이 규칙을 아예 호출하지 않는다**
   (import 목록에 없음 — v2 전용). v3는 `bs.short_term_debt`/`bs.long_term_debt`를
   합산이 아니라 `_resolve()`의 단일값 판정(충돌 시 보류)으로 다루므로, 재라우팅된
   행은 짝 canonical의 "유일한" 후보가 되어 그대로 확정되거나(단일값) 충돌로 보류될
   뿐 — 별도 이중계상 방어선이 필요 없다는 것을 코드 추적으로 확인.

**실측/검증** — `00130763` FY2024 연결을 `combine()`으로 직접 재계산(DB write 없음,
읽기전용 진단 경로):

| | 수정 전(v3) | 수정 후(v3) | v2(정답) |
|---|---:|---:|---:|
| `short_term_debt` | 113,802,813,293 | 113,802,813,293(불변) | 113,802,813,293 |
| `long_term_debt` | (소실) | **101,825,482,368** | 101,825,482,368 |
| `net_debt` | 36,346,724,254 | **138,172,206,622** | 138,172,206,622 |

수정 후 v3가 v2와 **원 단위까지 정확히 일치**. 단위테스트 5건 신설
(`fin2/tests/test_combine_noncurrent_sibling_reroute.py`) — 정상 재라우팅, 가드1~3
각각의 회귀 케이스. `pytest tests/ fin2/tests/` 639 passed / 1 failed(기존 무관,
`test_lxintl_facility_table_dropped`, biz_section — 이 트랙과 무관).

**★전수재감사 완료(2026-08-30/31)** — `std_financials_v3` 전체 재빌드
(`scripts/run_r57_verification.sh`) 후 Gate B 전수재감사: **pass→fail_a 전이 0**
(사실은 전이 자체가 0건 — `s.gate_status <> c.gate_status`인 행이 v3 전체에서
0건). ★단, 이 결과는 **약한 증거**다 — `face_audit`의 `fail_fields`는
`short_term_debt`/`long_term_debt`/`net_debt`를 **애초에 검사 항목으로 갖고 있지
않다**(실측: 해당 3개 필드가 걸린 fail 0건. `_NONCURRENT_SIBLING`도
`bs.trade_receivables`/`bs.trade_payables`(face_audit가 실제로 감사하는 항목)는
건드리지 않는다 — 그래서 "0 전이"는 "다른 계정을 오염시키지 않았다"는 안전성
확인이지, "net_debt이 좋아졌다"는 증거가 아니다.

**net_debt 자체의 개선폭은 v2/v3 직접 비교로 별도 측정**(설계문서 §2-2 재현):

| fy | both_have | mismatch(수정전, 설계문서) | mismatch(수정후) |
|---:|---:|---:|---:|
| 2024 | 2,714 | 67.6% | **67.0%**(거의 무변화) |
| 2025 | 2,677 | 69.6% | **70.9%**(거의 무변화) |

**표본 재현 케이스(`00130763`)는 DB에 정확히 반영**(`net_debt` 138,172,206,622,
v2와 원 단위 일치, `built_at` 확인됨) — 코드는 의도대로 동작한다. 그런데 FY2024/25
집계 불일치율은 거의 안 움직였다. 원인: 설계문서 §2-3의 표본 60건 분석에서
**원인 A(alias 갭/오매핑)가 원인 B(이 트랙의 대상)보다 압도적으로 크다**고 이미
암시돼 있었고(60건 중 원인 A류 20건+ vs 원인 B류 소수), 이번 실측이 그걸 확정한다
— `mismatch` 중 롱텀뎁트가 **완전히 비어있는** 행은 43~67건뿐, **값은 있는데 다른**
행이 1,637~1,665건으로 압도적이다.

**★새 발견(순서4 착수 전 재검토 필요)**: `lt_present_but_wrong` 표본을 직접
대조하니 alias 매핑 문제만이 아니다 — **v2는 `rule_additive_debt`
(`fin2/standardize/rules.py:282`)로 단기/장기차입금 세부항목(유동성장기부채·
유동성사채 등, `_ST_DEBT_PARTS`/`_LT_DEBT_PARTS`)을 합산하는데, v3(combine.py)는
이 규칙을 아예 호출하지 않고 `bs.short_term_debt`/`bs.long_term_debt`를
`_resolve()`의 단일값 판정(충돌 시 보류)으로만 다룬다** — 한 회사가 차입금을
여러 줄(단기차입금+유동성장기부채 등)로 나눠 공시하면 v2는 다 더하는데 v3는
그중 하나만 취한다. 이건 alias 카탈로그 갭(순서4/B1-D2)과 **별개의 구조적
차이**이고, 표본(`00126380`/`00117337` 등, 자릿수가 다른 수준으로 벌어짐)이
이 가설과 부합한다. B1-D2를 alias 보강만으로 진행하면 이 클래스는 그대로 남을
가능성이 높다 — 착수 전 규모 실측 권고.

근거: `fin2/layer3/combine.py`(`_NONCURRENT_SIBLING`, `_is_noncurrent_by_section_only`,
`_resolve()` pre-pass) · `fin2/tests/test_combine_noncurrent_sibling_reroute.py` ·
`scripts/run_r57_verification.sh` · `fin2/standardize/rules.py:282`(`rule_additive_debt`,
v3 미호출) ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-4(B1-D1) ·
메모리 `valuation-daily-blockers-rootcaused-2026-08-30`.

---

## R58. `fin2/layer3/combine.py::_apply_enrichment()` — 원인 C(v3가 차입금
세부항목을 합산하지 않는 구조적 결함) 순서4 시리즈, **step1 "wiring"** 구현
(net_debt-only 합산, DIRECT_MAP 컬럼 자체는 불변) (2026-08-31)

**배경** — [[valuation-daily-blockers-rootcaused-2026-08-30]] §2-6/§2-7,
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-6/§2-7.
R57(원인 B)을 전수재감사까지 마쳤는데도 FY2024/25 `net_debt` v2/v3 불일치율이
67.0%/70.9%로 거의 안 움직였다 — 지배적 원인은 **원인 C**: v2의
`rule_additive_debt`(`fin2/standardize/rules.py:282`)는 단기/장기차입금
세부항목(`bs.current_lt_debt`/`bs.current_bonds_plain`/`bs.current_bonds_conv`/
`bs.bonds`)을 합산하는데, v3(`combine.py`)는 이 규칙을 아예 호출하지 않고
`bs.short_term_debt`/`bs.long_term_debt`를 `_resolve()`의 단일값 판정으로만
다룬다. v3의 라벨 매퍼(`account_maps/bs_accounts.py`)엔 이미 이 개념들의
동등물이 **등록은 돼 있다**(`bs.current_portion_lt_debt`=유동성장기부채/
유동성장기차입금/유동성사채, `bs.current_bond`=유동성회사채/단기사채,
`bs.bond`=사채/장기사채/회사채) — `_resolve()`에서 정상 확정까지 되는데,
`DIRECT_MAP`(`_BS_MAP`)에 목적지가 없어 `col` 조립 루프(`combine()`의
`std_col = DIRECT_MAP.get(canon); if std_col is None: continue`)가 **조용히
버린다**. 순수 배선 누락(orphan canonical) — 새 alias 등록이 전혀 필요 없다.

**측정(2026-08-31, v2 비교가 아니라 v3 자체 `collect_candidates`+`_resolve`를
직접 재실행한 정밀재측정, 방법론은 설계문서 §2-7)** — 이 3개 orphan canonical을
`_resolve()`에 그대로 태워 FY2024/25 mismatch 3,715건을 재계산: **wiring만으로
(alias 추가 없이) 823건(22.2%) 완전 일치 해소 + 736건(19.8%) 개선**. 반례
발견(삼성전자 00126380, §2-7): 원문 BS엔 `단기차입금` 13.17조 한 줄뿐인데
`fact_v2`엔 그 acode 자체가 없고 작은 값(`bs.current_lt_debt`)만 있음 — v2가
XBRL에서 놓친 사례. → **v2=정답 전제는 위험**, 그래서 v2 비교가 아니라 v3
자체 로직으로 재측정했고, 사후 검증도 v2 비교만으로 끝내지 않는다
([[feedback-verify-against-source]]).

**구현 — net_debt 전용 스코프, DIRECT_MAP 컬럼 자체는 절대 안 건드림**:

```python
_V3_ST_DEBT_PARTS = ("bs.short_term_debt", "bs.current_portion_lt_debt", "bs.current_bond")
_V3_LT_DEBT_PARTS = ("bs.long_term_debt", "bs.bond")

def _additive_debt_for_net_debt(canon, col):
    # rule_additive_debt(rules.py:282)의 total_liabilities*1.05 이중계상 가드를
    # v3 canonical 이름으로 그대로 이식. 합이 그 상한을 넘으면 (None, None) —
    # 롤업+세부 이중태깅 의심, 합산 전체를 불신.
    ...
```

`_apply_enrichment()`에서 `rule_derive_net_debt(ctx)` 호출 **직전**에 `ctx.col`의
`short_term_debt`/`long_term_debt`를 이 합산값으로 덮어쓴 뒤 `rule_derive_net_debt`를
호출한다. **이게 안전한 이유**: `_apply_enrichment()` 끝의 copy-back 루프가
`("cash", "capex", "fcf", "net_debt", "depreciation", "amortization", "da_total",
"ebitda")`만 바깥 `col`(영속화되는 std 컬럼)로 복사하고 `short_term_debt`/
`long_term_debt`는 그 목록에 원래부터 없다 — `ctx.col`을 이 함수 안에서
덮어써도 **영속 컬럼엔 절대 전파되지 않는다**. `rule_additive_debt`(v2)를
직접 호출하지 않은 이유도 이것: v2는 그 두 컬럼 자체를 합산값으로 **덮어쓰는**
설계라 검증된 컬럼을 건드리는 리스크가 있지만, v3는 net_debt 계산에만 쓰고
버린다 — 위험이 구조적으로 더 작다.

**단위테스트** 6건 신설(`fin2/tests/test_combine_debt_wiring_net_debt.py`) —
정상 합산, 결측측 None 유지(0 아님), 이중계상 가드(초과/미초과), total_liabilities
없을 때 가드 미작동. `pytest tests/ fin2/tests/` 645 passed / 1 failed(기존 무관,
`test_lxintl_facility_table_dropped`).

**★전수재감사 완료(2026-08-31, `scripts/run_step1_debt_wiring_verification.sh`,
109분 소요)**: face_audit 스냅샷(`face_audit_snap_20260831_step1`) → std_v3
전체 재빌드(5-shard, 2,546개사·303,986행) → Gate B 전수재감사(5-shard) →
**pass→fail_a 전이 0**(회귀 없음). `net_debt` v2/v3 불일치율(`scripts/
measure_net_debt_v2_v3_mismatch.py`): FY2024 67.0%→**56.2%**, FY2025
70.9%→**59.9%**(둘 다 약 11pt 개선, §2-7의 wiring 단독 exact_fix 측정치
22.2%/19.8%와 방향·규모가 일치).

**★원문 대조(3건, `scripts/inspect_net_debt_case.py`)** — v2 비교만으로 끝내지
않는다는 원칙([[feedback-verify-against-source]])대로 face BS(`table_seq=0`)와
직접 대조:
- `00126380`(삼성전자) FY2024연결 — `단기차입금`/`장기차입금`/`사채` 3줄, `사채`
  14,530,000,000이 `bs.bond`로 정상 확정돼 `long_term_debt` 합산에 들어감.
  `net_debt` 재계산이 저장값과 원 단위까지 일치 확인(수식 직접 재현).
- `00115977` FY2024연결 — LT측(`장기차입금`+`사채`→`bs.bond`)이 **v2와 원
  단위까지 정확히 일치**(247,831,892,331). 독립적 교차검증.
- `00102858`/`00115977` 둘 다에서 **새 발견(버그 아님, 안전하게 보수적으로
  동작)**: `bs.current_portion_lt_debt`(`유동성장기부채`/`유동성장기차입금`/
  `유동성사채`)가 서로 다른 3개 개념을 **한 canonical에 합쳐놨다** — 한 회사가
  `유동성장기차입금`과 `유동성사채`를 **별도 줄로 동시에** 공시하면(실측:
  두 사례 다 해당) `_resolve()`가 값 충돌로 HELD 처리해 그 canonical 전체가
  `None`이 된다(가드가 막아서가 아니라 `_resolve()`의 기본 단일값 정책).
  `_additive_debt_for_net_debt`는 `canon.get(c) is not None`만 확인하므로
  이 경우 **조용히 빠지고 안전하게 보수적으로 동작**(이중계상·오류 없음) —
  다만 그만큼 wiring의 실제 회수율은 §2-7의 "3개 canonical 전부 확정" 가정보다
  현실에선 약간 낮다. v2는 XBRL acode로 이 둘을 애초에 별도 canonical
  (`current_lt_debt`/`current_bonds_plain`)로 갖고 있어 이 충돌이 없다 —
  **후속 백로그**: `bs.current_portion_lt_debt`를 v2처럼 2개로 쪼개는 안(§6에
  등재, 지금 범위 아님).

근거: `fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`/
`_additive_debt_for_net_debt`/`_apply_enrichment`) ·
`fin2/tests/test_combine_debt_wiring_net_debt.py` ·
`scripts/measure_net_debt_v2_v3_mismatch.py` ·
`scripts/run_step1_debt_wiring_verification.sh` ·
`account_maps/bs_accounts.py:213-219,260-262`(기존 등록된 orphan alias) ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-6/§2-7.

## R58 순서4-② "alias 3종" (2026-08-31) — `account_maps/bs_accounts.py` +
`fin2/layer3/combine.py`, 구현 완료·전수재감사는 후속 갱신

§2-7의 no_orphan(원인A, 1,389건) 라벨 전수집계가 지목한 몸통 3개 라벨군을
등록:

1. `유동차입금(사채포함)`(355건, unknown) → `bs.short_term_debt`.
2. `비유동차입금(사채포함)의유동성대체부분`(185건, unknown) →
   `bs.current_portion_lt_debt`(개념상 `유동성장기부채`와 동일 — "비유동
   차입금(사채포함)"의 1년 내 만기도래분).
3. `전환사채`류(165+건) → **신규 canonical 2개**: `bs.convertible_bond`(비유동,
   `전환사채`) / `bs.current_convertible_bond`(유동, `전환사채(유동)`/
   `유동전환사채`/`유동성전환사채`).

**★설계 각주 1개를 넘어 신규 canonical 2개가 필요했던 이유(실측, 2026-08-31)**
— 메모리/설계문서 초안은 "신규 canonical 1개"로 적었으나, 값 충돌 위험을
직접 실측하니 **반드시 2개**여야 했다: `사채`와 `전환사채`가 같은 필링에
별도 줄로 함께 등장하는 사례가 **231건**, 유동성장기부채류와 유동
전환사채류가 함께 등장하는 사례가 **1,300건**(둘 다 FY2022+ BS, table_seq=0
실측) — 하나의 canonical에 몰아넣으면 `_resolve()`가 두 값을 충돌로 보고
그 canonical 전체를 HELD(NULL) 처리해버려 **회수가 아니라 오히려 손실**이
난다. v2도 같은 이유로 `bonds`/`current_bonds_plain`과 별도로
`current_bonds_conv`를 갖고 있다 — 그 구조를 그대로 재현.

`유동성전환사채`/`유동성교환사채`는 이미 `bs.current_portion_lt_debt`에
fuzzy 0.93으로 우연히 걸려 있었다(§2-7 각주) — `전환사채` 계열 3개를 exact
alias로 등록하면 그 fuzzy 매치를 이기고 새 canonical로 옮겨간다. 이건
버그 수정 보너스이기도 하다: `유동성전환사채`가 `유동성장기부채`와 같은
필링에 동시 등장하면(1,300건 겹침 실측) 종전엔 **`bs.current_portion_lt_debt`
자체가 충돌로 HELD**됐을 것 — 새 canonical로 분리한 뒤로는 그 필링들의
`bs.current_portion_lt_debt`도 이제 깨끗하게 확정될 가능성이 높다(부수 개선,
`유동성교환사채`는 이번엔 손대지 않음 — 순서4-③ 소관).

`fin2/layer3/combine.py`의 `_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`에 두
canonical을 추가해 순서4-①의 net_debt 합산 경로에 그대로 편입(신규 배선
불필요, 튜플에 추가만).

**검증**: 단위테스트 6건 신설(`fin2/tests/
test_combine_debt_wiring_step2_aliases.py`) — 3개 alias 매핑(exact stage
확인) + 신규 canonical 2개 매핑 + `사채`/`전환사채` 동시 등장·
`유동성장기부채`/`유동성전환사채` 동시 등장 각각 충돌 없이 독립 확정되는지
+ 신규 canonical이 합산에 편입되는지. `pytest tests/ fin2/tests/` 651
passed / 1 failed(기존 무관). `AccountMapper.map()` 직접 호출로 대상 10개
라벨(alias 3종 + 전환사채 변형 4개 + 유동성교환사채/교환사채/신주인수권부사채
대조군) 전수 확인 완료.

**★전수재감사 완료(2026-08-31, 107분 소요)**: std_v3 전체 재빌드(2,546개사) →
Gate B 전수재감사 → **pass→fail_a 전이 0**(순서4-①과 정확히 같은 pass/
fail_a/pending 분포 — face_audit이 애초에 이 필드들을 안 보므로 당연한
안전성 확인). `net_debt` v2/v3 불일치율: FY2024 56.2%→**38.4%**, FY2025
59.9%→**48.8%** — 순서4-① 단독 개선폭(11pt대)보다 훨씬 큰 도약, "몸통 3개
라벨군" 가설(§2-7)이 실측으로 확정됨.

**★원문 대조 2건**: `00100601` FY2024연결 — `유동차입금(사채포함)`
27,920,346,589 + `비유동차입금(사채포함)의유동성대체부분` 500,000,000이
합산돼 `net_debt`가 **v2와 원 단위까지 정확히 일치**(42,281,467,274),
persisted `short_term_debt`는 설계대로 27,920,346,589(단일값)로 안전하게
남음. `00103130` FY2024연결 — 흥미로운 부수 관찰: `전환사채`가 label엔
"유동" 표기가 없는데 `section_path='부채>유동부채'`(현재 항목)로 공시됨 —
`bs.convertible_bond`는 `_CURRENT_STRICT`/`_NONCURRENT_SIBLING` 가드가
없어 만기 구분 없이 그대로 합산되지만, **net_debt은 ST/LT 배분과 무관하게
총합만 맞으면 되므로 무해함**을 직접 확인(계산: 원문 5개 부채줄 합계
62,065,151,232 중 아직 미등록인 `교환사채` 3,562,931,149만 제외한
58,502,220,083이 정확히 wired net_debt 계산과 일치) — **이 필링이 정확히
순서4-③이 필요한 이유**(교환사채 아직 미등록)를 실측으로 보여준 사례.

근거: `account_maps/bs_accounts.py`(short_term_debt/current_portion_lt_debt
alias 추가, `bs.convertible_bond`/`bs.current_convertible_bond` 신설) ·
`fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS` 확장) ·
`fin2/tests/test_combine_debt_wiring_step2_aliases.py` ·
`scripts/run_step2_alias_verification.sh` ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-7.

## R58 순서4-③ "나머지 소수 라벨"(신주인수권부사채/교환사채) + 순서4-②의
fuzzy 충돌 부작용 일괄 수정 (2026-08-31)

**본편**: `account_maps/bs_accounts.py`에 신규 canonical 4개 등록 — `bs.exchange_bond`
(교환사채, 비유동)/`bs.current_exchange_bond`(교환사채, 유동)/`bs.warrant_bond`
(신주인수권부사채, 비유동)/`bs.current_warrant_bond`(신주인수권부사채, 유동). 전환사채와
같은 이유로 반드시 4개(2쌍) 분리 — 실측 동시등장(FY2022+ BS, table_seq=0): `사채`↔
`교환사채` 35건, `사채`↔`신주인수권부사채` 30건, `전환사채`↔`교환사채` 139건,
`전환사채`↔`신주인수권부사채` **434건**, `교환사채`↔`신주인수권부사채` 37건, 각 계열
자체의 유동/비유동 동시등장 63건/88건. `fin2/layer3/combine.py`의
`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`에 편입.

**★부수 발견 — 순서4-②/③이 만든 새 exact alias들이 서로 텍스트 유사도로 간섭하며
연쇄적 fuzzy 오매핑을 냈다(2026-08-31, alias 카탈로그 전체 스윕으로 발견)**. 새
canonical/alias를 등록할 때마다 그와 한 글자(`유동`/`비유동`/`(유동)`/`(비유동)`)만
다른 반의어 라벨이 fuzzy로 잘못 끌려가는 패턴이 반복됐다:

| 문제 라벨(FY2022+ 실측 건수) | 등록 전 오매핑 | 원인 | 수정 후 정답 |
|---|---|---|---|
| `비유동전환사채`(118)/`비유동성전환사채`(14)/`전환사채(비유동)`(71)/`장기전환사채`(7+) | `bs.current_convertible_bond`(fuzzy) | 순서4-②가 만든 `유동전환사채`류와 한 글자 차이 | `bs.convertible_bond` |
| `사채(유동)`(11+) | `bs.current_convertible_bond`(fuzzy 0.968) | `전환사채(유동)`류와 유사 | `bs.current_bond` |
| `비유동사채`(125)/`비유동성회사채`(8) | `bs.convertible_bond`/`bs.current_bond`(fuzzy) | 등록 전엔 애초에 unknown(0.80 미만), 순서4-② 이후 넘어감 | `bs.bond` |
| `유동사채`(60) | `bs.bond`(fuzzy 0.972) | ★**실측 충돌위험**: `사채`/`장기사채`/`회사채`와 동시등장 **43건** — 방치 시 그 필링들의 `bs.bond` 전체가 `_resolve()` 충돌로 HELD, net_debt 손실 | `bs.current_bond` |
| `비유동성사채`(42) | `bs.current_portion_lt_debt`(fuzzy 0.975) | ★**실측 충돌위험**: 유동성장기부채류와 동시등장 **38건** | `bs.bond` |
| `사채(비유동)`(38) | `bs.convertible_bond`(fuzzy 0.970) | ★실측 충돌위험: 전환사채류와 동시등장 4건 | `bs.bond` |
| `비유동차입금(사채포함)의비유동성부분`(187)/`비유동차입금의비유동성부분`(14) | `bs.current_portion_lt_debt`(fuzzy) | 순서4-②의 `...의유동성대체부분`(반대 개념: 유동 전환 vs 비유동 잔여)과 유사 | `bs.long_term_debt` |
| `비유동차입금의유동성대체부분`(**512건**, `(사채포함)` 없는 축약형) | ★위 항목을 고치는 과정에서 **새로 뒤집힘**(0.956 > 0.940로 역전) | 방금 추가한 `...의비유동성부분` alias가 오히려 이 라벨을 더 가깝게 끌어감(휘프-어-몰) | `bs.current_portion_lt_debt`(exact 재등록으로 고정) |
| `비유동교환사채`/`비유동신주인수권부사채`(순서4-③ 등록 시 선제 차단) | (등록 안 했으면 fuzzy로 반대쪽) | 같은 패턴 선제 인지 | `bs.exchange_bond`/`bs.warrant_bond` |

**중요한 안전성 구분**: 이 표의 "오매핑"은 대부분 **net_debt 총액엔 무해**했다 —
`_V3_ST_DEBT_PARTS`/`_V3_LT_DEBT_PARTS`는 둘 다 net_debt 하나로 합산되므로 ST/LT
버킷을 틀려도 총합은 안 변한다(`00103130` 사례, R58 순서4-② 절 참고). **진짜
위험은 같은 canonical 안에서 값이 다른 두 후보가 만나 `_resolve()`가 통째로
HELD시키는 경우뿐**이다 — 위 표에서 ★표시한 3건(유동사채/비유동성사채/
사채(비유동))은 실측으로 그 충돌이 **실제로 발생하는** 필링이 있었기(43/38/4건)
때문에 우선 수정했고, 나머지는 ST/LT 분류 정확도 개선(데이터 품질) 차원에서
같이 정리했다. `차입금및사채`/`단기차입금및유동성장기부채` 류의 **결합(rollup)
라벨**은 원래부터 단일 개념이 아니라 정확한 재배분이 불가능 — 손대지 않고
그대로 둠(fuzzy가 아무 wired canonical에나 떨어져도 net_debt엔 무해).

**검증**: 단위테스트 7건 추가(`fin2/tests/test_combine_debt_wiring_step3_aliases.py`)
— 신규 canonical 4개 매핑 + 4개 사채계열 동시존재 무충돌 + 합산 편입 + 위 표의
반의어 혼동 회귀 3건(exact 재확인) + 실측 충돌 위험 케이스의 `_resolve()` 무충돌
확인. `pytest tests/ fin2/tests/` 658 passed / 1 failed(기존 무관).

**★전수재감사 1차 실행 결과 — pass→fail_a 0(안전)이지만 net_debt은 오히려
악화**(2026-08-31, 106분): FY2024 38.4%→**40.5%**, FY2025 48.8%→**51.2%**.
both_have 증가분(+21/+40)보다 mismatch 증가분(+76/+95)이 훨씬 커서, **기존에
이미 v2와 맞던 행 다수가 새로 틀어졌다**는 신호 — 원인 추적 결과 **R57과
같은 계열의 새 버그**를 발견했다: `bs.convertible_bond`/`bs.bond` 등 4개
canonical의 "무표기(bare)" alias(`전환사채`/`사채` 등)는 만기 불분명 시
**비유동 기본값**으로 등록했는데, 일부 필러가 그 무표기 라벨을 정확히
"유동" 몫 전용으로 쓰면서(`section_path='부채>유동부채'`) **동시에**
`비유동전환사채` 같은 명시적 비유동 라벨을 별도 줄로 공시한다. 그러면 둘 다
같은 canonical에 몰려 `_resolve()`가 충돌로 HELD — R57이 고친 "제외만 하고
회수 안 함"보다 더 나쁘게, **canonical 전체(두 값 다)가 net_debt에서
소실**된다. 실측 재현(`00172079` FY2024연결): `전환사채` 19,550,499,832
(section=유동부채) + `비유동전환사채` 1,794,834,765(section=비유동부채) →
수정 전엔 `bs.convertible_bond` 충돌로 21,345,334,597 전액 소실.

**수정** — `_NONCURRENT_SIBLING`의 정반대 방향 미러: 이번엔 canonical의
"기본" 등록이 비유동 쪽이므로, section_path가 유동인데 라벨이 안 그런
행(bare 무표기)을 그 canonical에서 **제거**해 대응 유동 canonical로 재라우팅
(단순 복사가 아니라 제거+이동 — `_src`가 `_CURRENT_STRICT` 소속이 아니라
나중에 필터링해줄 단계가 따로 없어서, 복사만 하면 `_src` 쪽 충돌이 그대로
남는다). 코드: `fin2/layer3/combine.py`
`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`/`_is_current_by_section_only()`.
가드: ①대응 유동 canonical에 이미 후보 있으면 재라우팅 안 함(이중계상
방지) ②전부 유동-signal뿐이면(진짜 비유동 후보 없음) 재라우팅 안 함
(00103130류 — 그대로 둬도 net_debt 무해, `_additive_debt_for_net_debt`가
ST/LT 상관없이 다 더함).

단위테스트 4건 추가(11건으로 확장) — `00172079` 실제 재현 + `bs.bond`
동형 + "전부 유동" 무재라우팅 + "대응 canonical 이미 있음" 가드. 전체
`pytest tests/ fin2/tests/` 662 passed/1 failed(기존 무관).

**★2차 전수재감사 결과 — pass→fail_a 0(안전), 그런데 net_debt 지표는
거의 그대로**(FY2024 40.5%→40.6%, FY2025 51.2%→51.4%, 사실상 무변화).
방금 고친 HELD-충돌 버그는 실제로 사라졌는데(단위테스트로 확인) 왜 지표가
안 움직였는지 **원인을 끝까지 추적**했다(사용자 지시, 2026-08-31):

**원인 규명 — 지표 악화의 대부분은 버그가 아니라 v3가 v2보다 좋아진 것**.
FY2024 mismatch 1,304건 중 **1,169건(90%)이 v3_net_debt > v2_net_debt**
방향이었고, 그중 **910건(78%)이 이번 순서4-②/③이 새로 배선한 라벨
(유동성장기부채/유동성사채/전환사채/교환사채/신주인수권부사채 계열)이
그 필링에 실제로 존재**했다. 원문 직접대조(`00103130` FY2024연결) —
face BS에 차입금·사채 관련 줄이 **정확히 5개**(단기차입금/유동성장기차입금/
전환사채/교환사채/장기차입금) 있는데, **v3는 5개 전부(합계
62,065,151,232)를 합산**하는 반면 **v2는 단기차입금+전환사채 2개만
잡고(55,728,052,087) 유동성장기차입금+교환사채는 통째로 놓친다** — 차이
6,337,099,145이 정확히 그 두 항목의 합과 일치. **v2가 불완전한 것이지
v3가 틀린 게 아니다**(삼성전자 반례, §2-7에서 이미 확인된 "v2=정답 전제는
위험하다"가 이번엔 대규모로 재현됨). "v2와의 불일치율"이라는 지표 자체가
**v3가 v2를 앞지르는 구간에서는 구조적으로 나빠질 수밖에 없는 지표**라는
뜻 — 순서4-②/③처럼 v2가 원래 못 잡던 세부항목을 v3가 새로 잡을수록
"불일치"가 늘어나는 게 정상이다.

**★그런데 이 조사 과정에서 별개의 진짜 버그(이번 순서1~3 범위 밖, 훨씬
전부터 있던 것)를 하나 더 찾았다** — v3_net_debt < v2_net_debt인 135건
(반대 방향) 중 표본 대조: `00181712` FY2024연결에서 `long_term_debt`가
통째로 `None`이었다. 원인: 원문 BS에 `사채 및 장기차입금`(14,788,886,000,000,
**유동부채** 소속)과 `사채및장기차입금`(48,073,129,000,000, **비유동부채**
소속)이 — **같은 정규화 텍스트, 서로 다른 섹션** — 둘 다 존재하는데, 이
"차입금및사채"류 **결합(rollup) 라벨**이 `bs.long_term_debt`에 fuzzy(0.96대)로
매핑되고, `bs.long_term_debt`는 (R57의 `_CURRENT_STRICT`도, 이번 순서4-③의
`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`도) 보호 대상이 아니라서
두 값이 그대로 충돌 → HELD → **62,861,073,000,000 전액 소실**(net_debt
62.9조 오차 — 이번 세션에서 발견한 것 중 금액 기준 최대). 전수 스캔(2011~2025,
`차입금및사채`/`사채및차입금`/`사채및장기차입금`/`장기차입금및사채`류만):
**538건**의 필링이 같은 패턴(같은 정규화 라벨이 유동+비유동 양쪽에 존재)에
해당 — R57/순서4-③과 **완전히 같은 병리**(만기 불분명 결합 라벨이 유동/
비유동 양쪽에 동시 존재 시 HELD)가 `bs.long_term_debt`/`bs.short_term_debt`
본체에도 있다는 뜻이다.

★**이 버그는 오늘 세션(순서1~3)이 만든 게 아니다** — 관련 alias
(`장기차입금및사채` 등)는 이번에 손대지 않은 훨씬 이전 alias이고, R57(원인
B) 이후 죽 있었을 것으로 추정된다. `bs.long_term_debt`/`bs.short_term_debt`는
net_debt 전용이 아니라 std_financials_v3의 **핵심 DIRECT_MAP 컬럼**(다른
소비자도 있음)이라 고치려면 순서4-③과 같은 net_debt-scoped 우회가 아니라
그 컬럼 자체를 건드려야 해서 **파급범위가 다르다** — 별도 설계·전수재감사
트랙으로 분리 권고(§6 후속 백로그, 가칭 R59). 지금은 발견·규모실측까지만.

근거: `account_maps/bs_accounts.py`(exchange_bond/warrant_bond 신설 4종 +
반의어 혼동 수정 alias 다수) · `fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`/
`_V3_LT_DEBT_PARTS` 재확장, `_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`) ·
`fin2/tests/test_combine_debt_wiring_step3_aliases.py` ·
`scripts/inspect_net_debt_case.py`(00103130/00181712 원문대조) ·
`docs/plans/valuation_daily_blockers_da_netdebt_design_2026-08-30.md` §2-7/§2-10/§6.

## R59. `fin2/layer3/combine.py::_resolve()` — `bs.long_term_debt` 결합(rollup)
라벨의 유동/비유동 동시존재 시 canonical 전체 HELD(★★★★★완전 종료 2026-08-31)

**증상** — `bs.long_term_debt`는 R58(`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING`)이
보호하는 4개 사채계열 canonical과 같은 취약점을 안고 있었다: 만기 구분이 라벨 자체에
없는 **결합 라벨**(`장기차입금및사채`/`사채및장기차입금`/`사채및차입금`/`차입금및사채`
등, "사채+차입금"을 하나로 합친 개념)이 `bs.long_term_debt`의 비유동 기본 alias로
등록돼 있는데, 같은 필링 안에서 이 결합 라벨이 유동부채 섹션과 비유동부채 섹션에
각각 별도 줄로 동시 존재하면 두 인스턴스가 같은 canonical로 몰려 `_resolve()`가
충돌로 보고 **`bs.long_term_debt` 전체를 HELD**(=None) — 유동분만 버려지는 게 아니라
비유동분(진짜 장기차입금)까지 통째로 소실된다. 실측(`00181712` FY2024연결): `사채 및
장기차입금`(14,788,886,000,000, 유동) + `사채및장기차입금`(48,073,129,000,000,
비유동) 동시존재 → `long_term_debt`=`None` → net_debt 62,861,073,000,000 과소(이
프로젝트에서 발견된 net_debt 단일 결함 중 금액 최대). 전수 스캔(2011~2025,
`report_lines` FY BS) 약 500여건 필링이 같은 패턴.

**R58과 재사용할 수 없었던 이유** — R58의 재라우팅 판정 함수
`_is_current_by_section_only()`는 "label_raw에 `장기`/`비유동` 문자열이 있으면
재라우팅 안 함"을 전제한다(전환사채/사채/교환사채/신주인수권부사채 계열은 현재분
라벨이 실제로 비유동 표시가 없어 이 전제가 맞다). 그런데 `bs.long_term_debt`의 결합
라벨은 그 자체에 이미 "장기"라는 단어가 들어있다(`장기차입금및사채` 등) — 그리고
실측된 유동측 변형(`사채 및 장기차입금`)에도 "장기"가 그대로 남아있다. 즉 **라벨
텍스트만으로는 유동/비유동을 구분할 수 없는 canonical**이라 R58의 판정 함수를 그대로
재사용하면 이 병리를 못 잡는다 — 실측(2026-08-31): 유동측 인스턴스 417건 중
label_raw에 장기/비유동이 포함된 건 단 1건(0.2%)이고, 그 1건이 바로 대표 사례
`00181712` 자신이었다(즉 라벨검사를 그대로 썼다면 정작 발견 계기가 된 사례를 놓쳤을
것).

**수정** — 라벨 검사 없이 `section_path`만 보는 새 판정 함수
`_is_current_by_section_only_pure()`와 별도 dict
`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING_PURE = {"bs.long_term_debt":
"bs.short_term_debt"}`, `_resolve()` 안의 별도 재라우팅 루프. R58의 기존 4개
canonical 처리 코드는 한 글자도 건드리지 않음(diff 0, 회귀위험 최소화 우선) — 이번
수정이 그 4개에 영향 없음을 코드만으로 확인 가능. `bs.long_term_debt`는 net_debt
전용 파생 컬럼이 아니라 `std_financials_v3`의 핵심 DIRECT_MAP 컬럼(다른 소비자도
있음)이므로, R58의 `_additive_debt_for_net_debt` 같은 net_debt-scoped 우회가 아니라
canonical 자체(`_resolve()`)를 고쳤다 — 다른 소비자에도 값이 정상적으로 전파된다.

가드는 R58과 동일: sibling(`bs.short_term_debt`)에 이미 자체 후보(예: 진짜
`단기차입금`)가 있으면 재라우팅된 유동측 rollup 값은 합산되지 않고 버려진다(이중계상
방지 우선) — 이 경우도 `bs.long_term_debt`는 충돌에서 벗어나 비유동값을 정상
확정하므로 수정 전(전액 소실)보다는 개선이지만 "완전 복구"는 아니다. 이 guard가
실제로 몇 %에서 발동하는지는 전수재감사 시 `scripts/run_r59_verification.sh` 5단계
(`recovered_after` vs `still_held_after`)로 측정한다.

★face_audit(Gate B)은 `long_term_debt`/`short_term_debt`를 애초에 감사하지 않는다
(실측: `fail_fields`에 등장하는 필드 23종에 두 컬럼 모두 없음) — 그래서 이 수정의
Gate B 회귀 확인은 R57/R58과 동일하게 "전체 pass→fail_a 전이"만으로 보고, 값 복구
자체는 `std_financials_v3`의 두 컬럼을 전/후 스냅샷으로 직접 비교해서 본다.

**상태(2026-08-31) — 완전 종료**: 코드+단위테스트(`fin2/tests/test_combine_debt_r59_
rollup_label_pure_reroute.py`, 6건) 구현 → `scripts/run_r59_verification.sh` 1차
전수재빌드+Gate B 전수재감사 실행 결과 **Gate B 회귀 0건**, 영향 필링 304건 중 HELD
287건 → **243건(84.7%) 복구**.

★1차 재검증 중 **R59와 무관한 별개 신규 버그를 하나 더 발견**: 잔여 44건을 원문+
매퍼로 전수 대조한 결과 42건이 "사채및차입금"(사채가 앞에 오는 어순)이 fuzzy 매칭
threshold 밑으로 떨어져 아예 `unknown`으로 빠지는 **별도의 alias 갭**이었다(반대
어순 "차입금및사채"는 이미 정상 매칭됨 — v2도 동일 실패, 이번 세션 이전부터 있던
것). `account_maps/bs_accounts.py`에 "사채및차입금" exact alias 추가 후 **2차
전수재빌드+재감사**를 다시 실행: Gate B 회귀 여전히 0건, 복구 **283/287(98.6%)**로
상승. 잔여 4건은 전부 원문대조로 원인 특정 완료 — sibling guard 트레이드오프(설계상
의도, `00181712` FY2024) 1건, 3-way 섹션분할(`00160588`) 1건, **또 다른 별개
alias 갭**("차입금 및 전환사채" 결합 라벨 미매핑, `00653194` 단독 실측 — 스코프가
좁아 이번 트랙에서는 미수정, 범위 밖으로 기록) 2건. `pytest tests/ fin2/tests/`
668 passed/1 failed(기존 무관 — `test_biz_section.py`).

근거: `fin2/layer3/combine.py`(`_CURRENT_CONTAMINATED_NONCURRENT_SIBLING_PURE`,
`_is_current_by_section_only_pure`, `_resolve()` 내 별도 루프) ·
`account_maps/bs_accounts.py`("사채및차입금" exact alias) ·
`fin2/tests/test_combine_debt_r59_rollup_label_pure_reroute.py` ·
`scripts/run_r59_verification.sh` ·
`docs/plans/r59_rollup_debt_label_held_bug_design_2026-08-31.md` §4-1~§4-3.

## R60. `account_maps/bs_accounts.py` — `bs.current_portion_lt_debt` 개념분리
("유동성사채" → `bs.current_bond_plain` 신설)(★★★★★완전 종료 2026-09-01)

**증상** — `bs.current_portion_lt_debt`에 "유동성장기부채"/"유동성장기차입금"(장기
부채·차입금의 유동성 대체분)과 "유동성사채"(사채의 유동성 대체분, 개념이 다름)가
한 canonical에 섞여 있었다. 한 회사가 둘을 같은 필링에 별도 줄로 동시 공시하면
`_resolve()`가 서로 다른 값을 가진 두 후보로 보고 canonical 전체를 HELD. v2는
XBRL acode로 애초에 `bs.current_lt_debt`/`bs.current_bonds_plain` 2개로 분리돼
있어 이 문제가 없다(`fin2/taxonomy/concept_map.py:59`
`dart_CurrentPortionOfBonds → bs.current_bonds_plain`). 실측 사례(`00102858`
FY2008 연결): "유동성사채" 75,056,000,000 vs "유동성장기부채" 53,884,912,604 동시
존재 → HELD. 전수 실측(2026-08-31, `report_lines` 전체 BS): 동시존재 필링
**3,405건/487개사**.

**"기존 `bs.current_bond`로 병합" 대안 기각** — `bs.current_bond`(유동성회사채/
단기사채/사채(유동)/유동사채)로 "유동성사채"를 그냥 합치는 손쉬운 안을 실측으로
검증한 결과 기각: 동시존재 227건 중 176건이 값이 달라 **새 충돌**을 만든다(51건만
우연히 같은 값). 전환사채/교환사채/신주인수권부사채와 동일한 패턴으로, 완전히
새로운 leaf canonical(`bs.current_bond_plain`)로 분리하는 것이 유일한 안전한 해법.

**수정** — `account_maps/bs_accounts.py`에 `bs.current_bond_plain: ["유동성사채"]`
신규 등록(기존 `bs.current_portion_lt_debt`에서 "유동성사채" 제거), `fin2/layer3/
combine.py`의 `_V3_ST_DEBT_PARTS`에 `bs.current_bond_plain` 편입(net_debt 합산
전용 leaf — DIRECT_MAP 연결 없음, 기존 `bs.current_portion_lt_debt`/
`bs.current_bond`와 동일).

★face_audit(Gate B)은 이 두 canonical(`bs.current_portion_lt_debt`/
`bs.current_bond_plain`)을 애초에 감사하지 않는다(net_debt 전용 파생 집계 leaf라
`std_financials_v3`에 자체 컬럼조차 없음, R59와 동일 실측) — Gate B 회귀는
"전체 pass→fail_a 전이"만 보고, 값 복구 자체는 `std_financials_v3.net_debt`
전/후 스냅샷 비교로 검증(`_additive_debt_for_net_debt`의 결과가 `net_debt`에만
copy-back되고 `short_term_debt`/`long_term_debt` 영속 컬럼은 건드리지 않음 —
`_apply_enrichment` 참고).

**상태(2026-09-01) — 완전 종료**: 코드+단위테스트(`fin2/tests/
test_combine_debt_r60_current_bond_plain_split.py`, 5건) 구현 →
`scripts/run_r60_verification.sh` 전수재빌드(5-shard, 2,546개사)+Gate B
전수재감사(5-shard) 실행 결과 **Gate B 회귀 0건**(pass→fail_a 전이 0). net_debt
값이 실제로 바뀐 필링 **2,241건**(영향 3,158건 중 — report_lines 전체기간 기준
3,405건이었으나 std_v3 FY period 결합 조건상 3,158건으로 좁혀짐), 회수 총액
**약 350.3조원**(`sum(net_debt_after - net_debt_before)`). 잔여 24건은 전부
"still held"인데 원문대조 결과 이번 수정과 **무관**(cash 컬럼 자체가 비어있어
net_debt 산식이 애초에 계산 불가 — 별개의 기존 이슈). `pytest tests/ fin2/tests/`
673 passed/1 failed(기존 무관 — `test_biz_section.py`).

★교훈 — 검증 스크립트 설계 시 "canonical이 HELD→net_debt가 NULL"만 복구지표로
잡으면 안 된다: `_V3_ST_DEBT_PARTS`처럼 여러 canonical을 더하는 additive 합산
구조에서는 하나가 HELD여도 다른 구성요소 덕에 net_debt가 NULL이 아닌 채로
"과소계상"되는 경우가 대부분이라(R60 실측: NULL 기준 recovered_after=0였지만
실제 값변경 2,241건/350.3조원) — **값 자체의 전/후 diff**를 반드시 함께 봐야
진짜 복구율이 드러난다.

근거: `fin2/layer3/combine.py`(`_V3_ST_DEBT_PARTS`) ·
`account_maps/bs_accounts.py`(`bs.current_bond_plain`) ·
`fin2/tests/test_combine_debt_r60_current_bond_plain_split.py` ·
`scripts/run_r60_verification.sh` ·
`docs/plans/bs_current_portion_lt_debt_concept_split_design_2026-08-31.md` §4.

---

## R61. Gate B Phase B(`fin2/audit/line_audit.py`) DB측 원천 `fact_v2`→`report_lines`
이식 + 전수재감사로 발견한 Track A/B 감사리더 버그 3종(★완전 종료 2026-09-01)

**배경** — Phase B(본문 전 계정 라인 전수대조, `face_line_audit`)는 계층2 GC(`fact_v2`
55GB DROP) 트랙의 마지막 살아있는 소비자였다. `fact_v2`는 acode 키인데 계층3이 실제
소비하는 원천은 라벨 키인 `report_lines`라 이식 없이는 DROP이 막힌다(R23·R35·R46·R47과
같은 계열 — Gate B 감사리더는 파싱·적재 규칙과 별개 코드경로지만 같은 이유로 이 문서에
쌓여왔다). 이식 자체는 규칙 변경이 아니라 원천 교체지만, 게이트1(라벨 매칭률 95%
목표, 실측 100.00% — `FaceLine.in_body_section`으로 Track A도 Track B의 DART
섹션기반 본문표 식별을 공유해 도달)을 통과시키는 과정과 Phase 4 전수재감사 과정에서
**Track A/B 감사리더 자체의 진짜 버그 3종**을 발견·수정했다:

1. **Track B dedup 키 누락** — `read_report_face_text()`의 중복제거 키가 `label`을
   빠뜨려 동명이의 라벨(같은 표기, 다른 계정)이 충돌·서로를 덮어썼다.
2. **Track A 값-집합 매칭 재설계** — 라벨 단일값 비교 대신 값-집합 매칭으로 바꿔
   1차 실행의 대량 오탐(악화 74,220건)을 해소.
3. **지배/비지배·EPS 계열 Track B 확장 제외** — 이 계열은 R27/R45~R47이 이미 다루는
   별도 함정(라벨 부분문자열·귀속 오매핑)이 Phase B 라인대조에도 새어 들어와 있어
   감사 대상에서 뺐다(수정이 아니라 제외 — 근본 함정 자체는 R27/R45~R47 관할).

**결과(전수재감사 전이표, PK=`rcept_no`)** — 최초 실행(수정 0건): 개선 4,151 : 악화
74,220. 위 3개 수정 반영 최종(4차) 실행: **개선 14,014 : 악화 209 = 67:1**.

**잔여 209건(R-트랙 후보, 미해결)** — 트리아지 결과 상위 2개 클러스터는 원인 가설만
확정, 수정은 이 트랙 범위 밖:
- Track B, corp `01032486` 등(34/209) — `read_report_face_text()`가 `fx_declared`
  정책(R? 미등재, 메모리 `fx-declared-statements` 참고 — 환산 없이 표시통화 그대로
  저장) 대상 문서를 문서 기본단위(원 환산 가정)로 잘못 읽는 것으로 의심(미검증).
- Track A, `ifrs-full_Inventories` 등 BS/CF 공용 라벨(58개사 분산) — CF 조정항목
  섹션에서 재사용된 라벨을 BS 값과 오대사하는 것으로 의심(미검증).

근거: `docs/plans/gateb_phaseb_line_audit_v3_migration_design_2026-09-01.md`(Phase
0~4 전체) · `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §4-3 · 메모리
`gateb-phaseb-line-audit-migration-phase0-1-2026-09-01` · `fin2/audit/line_audit.py`
· `scripts/gateb_audit.py::audit_lines()` · 커밋 `bcd8998`/`e3267da`/`e1af6d5`/
`37c6e81`/`ca6dfa3`/`4e6b767`.

---

## R62. `account_maps/is_accounts.py` + `parser/common/amount_normalizer.py` —
`is.net_income` '(당기)' 삽입형·'총당기순이익' 계열 alias 누락 + 로마숫자 혼합표기
정규화 버그 (2026-09-02, std_v3 상류결함① 부분 해소)

**배경** — [[gateb-factv2-backlog-1to5-calendar-v3-scoping-2026-09-02]] Phase2에서
발견된 "std_v3 상류결함①"(interim 행의 ~4%가 `ebt`/`tax_expense`는 정상인데
`net_income`만 NULL, 9,468~9,768건) 후속 원인규명 트랙. 재현 표본: 현대차(00164742)
separate 2012~2016 전 분기 + 2017 Q1/H1.

**근본원인 2건, 같은 원인규명 세션에서 함께 발견**:

1. **alias 누락** — 원문 헤드라인 당기순이익 라벨이 "분기(당기)순이익"(현대차 2012~
   2016)처럼 duration 접두어와 '(당기)'를 **같이** 쓰는 변형, 또는 K-GAAP 구서식
   "총당기순이익"(총-접두) 계열인데 `account_maps/is_accounts.py`의 `is.net_income`
   alias 목록엔 접두어 없는 형태("분기순이익", "당기순이익" 등)만 등록돼 있었다. 퍼지
   매치도 구제 못 함 — "분기(당기)순이익" vs "분기순이익" SequenceMatcher ratio
   0.7143, 임계 0.88 미달.
2. **로마숫자 혼합표기 정규화 버그**(공용 함수, R28 계열) —
   `amount_normalizer.normalize_account_name()`이 로마숫자 접두어를 "유니코드
   전용"/"ASCII 전용" 정규식 **둘로 따로** 처리했다. 유니코드 로마숫자 한 글자
   (`Ⅲ`)는 실제로 여러 자리('III')를 나타내는데, DART 필자가 "XⅢ."(ASCII 'X' +
   유니코드 'Ⅲ')처럼 섞어 쓰면 유니코드 정규식은 맨 앞이 ASCII라 매치 실패, ASCII
   정규식은 'X' 한 글자만 로마숫자로 오인식해 지우고 뒤의 'Ⅲ.'을 그대로 남긴다 —
   "Ⅲ. 총당기순이익" 같은 잔재 형태가 만들어져 위 alias 추가로도 매치 안 됨.

**항등식 대조로 안전성 확인** — 후보 라벨을 alias로 승격하기 전, 같은 문서 안에서
`ebt − tax_expense`와 정확히 일치하는지, 그리고 bare `당기순이익`과 공존할 때 값이
갈리지 않는지(발산 0건, 전수) 확인한 것만 등록. **의도적으로 등록 안 한 것**:
`계속영업이익(손실)`(IFRS 계속영업=중단영업 **제외**분이라 중단영업이 있는 문서에서
등록하면 net_income 과소 오염 — 실측 00102113 2024FY: 계속영업 −5,678,950,649 ≠
실제 net_income 1,315,633,234, 중단영업이익 6,994,583,883 별도 존재), `총포괄손익`
(다른 canonical, `is.total_comprehensive_income`), `법인세비용차감전순이익(손실)`
(이미 `is.ebt`), `지배기업소유주지분`(bare 라벨 함정, R49/2026-08-22 선례와 동일
이유로 기존에도 제외됨) — 전부 "ebt−tax와 우연히 값이 같아 보이는" 이웃 개념이었다.

**구현**:
- `account_maps/is_accounts.py::IS_ACCOUNTS["is.net_income"]`에 8개 alias 추가:
  `분기(당기)순이익`·`반기(당기)순이익`·`당(분)기순이익(손실)`·`당(반)기순이익(손실)`·
  `당기(전기)순이익(손실)`·`총당기순이익`·`총당기순이익(손실)`·
  `총당기순이익(Net Income-Total)`.
- `amount_normalizer.py`: 선두 로마숫자류 구간(`^[A-Za-zⅠ-Ⅹⅰ-ⅹ]+`)의 유니코드
  문자만 ASCII 다중문자로 치환(`_ROMAN_UNICODE_TO_ASCII`)한 뒤, 기존 ASCII 로마숫자
  문법 정규식 **하나로 통일**(과매칭 방지 문법은 그대로 재사용 — 일반 라벨 동작
  불변). 순수 유니코드/순수 ASCII 접두어는 종전과 동일하게 동작(회귀 없음).
- 계층2(`report_lines.py`)는 `account_mapper`를 안 씀(파일 상단 독스트링에 명시) —
  이번 수정은 **계층3(combine.py 매핑)에만 영향**, R29와 동일하게 `report_lines`
  재추출 불필요.

**검증**:
- 회귀 테스트 신설 2개: `fin2/tests/test_account_mapper_net_income_paren_variants_
  r62.py`(alias 8종 exact 매치 + `계속영업이익` 등 4종 미등록 확인)、
  `fin2/tests/test_amount_normalizer_roman_prefix_r62.py`(혼합/순수 로마숫자 접두어
  + 비-로마숫자 라벨 무변경). `pytest tests/ fin2/tests/` 694 pass(무관 기존 실패
  1건 `test_biz_section.py::test_lxintl_facility_table_dropped` 불변).
- 실측 회수 규모(DB 전수 스캔, `ebt−tax_expense` 항등식 매치 기준): 대상 인구
  9,768행 중 **1,239행(12.7%)/297개사**가 새 alias+정규화 수정으로 `is.net_income`
  후보를 얻게 됨. **잔여 8,529행은 다른 원인**(표본 00220969 확인 —
  `report_lines`에 헤드라인 당기순이익 행 자체가 **아예 없음**, 계층2 추출 결함 또는
  원문 표 형태 자체가 다른 것으로 추정, 미확정) — 이번 트랙 범위 밖, 별도 트랙
  후보로 분리.

**백필**: `build_std_v3.py --corp <297개사> --year-min 1999`(대상 corp 목록은 위
검증 스크립트 산출물, 커밋에는 안 실음 — R29 선례와 동일하게 스크래치패드 산출물).
**사용자 실행 대기**(장시간 명령 직접실행 금지 정책) — 실행 전 `std_financials_v3`
pg_dump 백업 필수.

**후속트랙**(미착수, 범위 밖): 잔여 8,529행(계층2 헤드라인 행 결측 의심, 별도
원인규명 필요) — 이번 alias/정규화 수정 범위 밖.

---

## R63. `fin2/layer3/combine.py` + `fin2/layer3/build.py` — K-GAAP시대 연결 인터림
IS "직전연차 재게재" 배제 + 요약재무정보 브래킷라벨 누출 배제 (2026-09-02, std_v3
상류결함②)

**배경** — [[gateb-factv2-backlog-1to5-calendar-v3-scoping-2026-09-02]] 후속,
`docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_design_
2026-09-02.md`. revenue 기준 corp×basis×fiscal_year 83,844건 중 3,516건(906개사)
누적행 단조성 위반(Q1≤H1≤Q3≤FY 깨짐)에서 시작한 조사.

**근본원인 1(원문대조 2건으로 확정)** — K-GAAP 시대(~2010년까지) 인터림(Q1/H1/Q3)
필링의 "손익계산서"/"연결손익계산서" 재무제표 본문 표는 당해분기 데이터가 아니라
**직전 확정 연차 재무제표를 그대로 재게재**한 것. 2011년 K-IFRS 연결의무화
이전엔 연결 인터림 재무제표 작성·공시 자체가 법정의무가 아니었다는 규제상의
사실(별도는 원래도 분기공시 의무 대상이라 진짜 당해분기 데이터) — 계층2/계층3
버그가 아니라 원문 자체가 그렇게 작성됐다는 사실. 실측:
- 현대차(00164742) 2004 연결 — "연결손익계산서" 섹션이 Q1·Q3 필링에 바이트
  단위로 동일.
- KG스틸/동부제강(00115676) 2006 — 별도 "손익계산서" 표는 컬럼헤더가 필링마다
  정확히 다른 기간(Q1: "제25기 분기(2006.1.1~3.31)", Q3: "제25기 3분기
  (2006.1.1~9.30)")인데, 연결 "연결손익계산서" 표는 Q1·H1·Q3 전부 "제24기/제23기"
  (2005/2004 연차)로 완전 동일 — 세부계정 15개 이상 동일값(iconv EUC-KR→UTF-8
  후 grep 원문대조).
- 전사 정량화(report_lines raw): "필링간 값 하나라도 일치"하는 쌍 중 "10개+
  동시일치"(=표 전체 재게재) 비율이 **연결 97.2%(10,519/10,818쌍) vs 별도
  29.6%(8,128/27,470쌍)** — 압도적 비대칭.

**근본원인 2(전사 SQL로 확정)** — "요약(연결)재무정보" 표는 "[유동자산]" 식
대괄호로 섹션을 나누는데, 이 표가 간혹(전사 712개 (corp,rcept,statement,basis,
table_seq) 조합) 정식 BS/IS/CF/SCE/APPR statement+basis로 잘못 분류돼
`report_lines`에 들어가 있다. 결정적 확인(00171867, rcept 20081114001440,
2009H1): "[유동자산]" 라벨이 있는 **같은 table_seq 안에** `매출액`·`부채총계`·
`자산총계`·`자본총계`·`영업이익`·`지배회사지분순이익` 등 DIRECT_MAP 캐노니컬
정확일치 라벨이 그대로 섞여 있었다 — account_mapper가 대괄호 여부를 안 보므로
이 값들이 진짜 재무제표 본문 대신 요약표에서 채택될 위험이 실재.

**왜 "요약재무정보"로 대체하지 않는가** — 사용자 확인(2026-09-02): 그 표는
단위가 백만원(재무제표 본문 표는 원 단위)이라 std_v3의 정밀도 기준 미달, 소스로
채택 안 함. 즉 이 시대·이 basis엔 원천적으로 정밀 당해분기 연결 IS 데이터가
없다 — 복구가 아니라 **오염된 값을 배제(NULL)**하는 방향으로만 구현.

**구현**:
1. `combine.py::_stale_annual_reprint_table_seqs(session, corp, fy, period, basis)`
   신설 — 같은 corp×fiscal_year×basis의 **다른 interim period**(Q1/H1/Q3 중 현재
   period 제외)와 (label_raw, value_won) 10개 이상 동시일치하는 table_seq를
   cross-period DB 조회로 탐지(`report_fiscal_year <= 2012`로 조기 게이팅 — 실측
   연도분포 밖 구간에서 매 period마다 불필요한 쿼리 방지). `_resolve()`에
   `stale_is_table_seqs` 파라미터로 주입돼 `cands`의 is.* 캐노니컬에서 배제
   table_seq 후보를 제거하는 **cands-레벨 pre-pass**(main 루프 진입 전) — 남는
   후보가 없으면 그 캐노니컬은 아예 `cands`에서 삭제(=NULL). 기존 `trust_seqs`/
   `degenerate_eq_ids` 가드와 달리 "빈 풀 방지" 안전장치를 **의도적으로 안 둠**
   (그게 이 규칙의 목적 — 대체소스가 없는 시대엔 NULL이 맞는 결과).
   `combine_full()`이 매 period 호출마다 계산해 `_resolve()`에 전달.
2. `build_merged_lines()`/`collect_candidates()`의 SQL에 `NOT EXISTS` 서브쿼리
   추가 — 같은 (rcept_no, statement, basis, table_seq) 안에 `label_raw ~
   '^\[.*\]$'`(대괄호 라벨)인 행이 하나라도 있으면 그 table_seq 전체를 제외
   (`_trust_account_table_seqs()`와 같은 "특징적 신호로 table_seq 전체 배제"
   패턴, 신호가 값항등성 대신 라벨텍스트라 cross-period 조회 불요).
3. **부수 발견·수정**: `build.py::build_corp()`가 `if not col: continue`로 delete
   자체를 건너뛰고 있었다 — 위 두 배제 규칙이 새로 만드는 "이 (corp,fy,period,
   basis)는 이제 후보가 하나도 없다"는 케이스에서, 재빌드해도 **예전(수정 전)의
   틀린 값이 담긴 행이 영구히 안 지워지는** 버그를 노출시켰다(모듈 자체 독스트링의
   "delete-then-insert" 계약 위반, R63으로 처음 발현됐을 뿐 잠재적으로 기존에도
   있었을 수 있는 결함). `delete()`를 `if not col` 체크보다 먼저 실행하도록 이동 —
   `col`이 비어도 그 키의 기존 행은 항상 지워지고, insert만 조건부로 스킵.

**검증**: 회귀 테스트 신설 2개 — `test_combine_r63_stale_reprint_resolve.py`(pure,
합성 cands+stale_is_table_seqs로 `_resolve()` pre-pass 동작 검증, 5개), `test_
combine_r63_stale_reprint_db.py`(DB-backed, KG스틸 00115676/2006 Q1 연결
table_seq=1 탐지+별도 미탐지+FY 무영향, 00171867 브래킷라벨 table_seq 배제 실측
재현, 4개). `pytest tests/ fin2/tests/` 703 pass(무관 기존실패 1건
`test_lxintl_facility_table_dropped` 불변, R62와 동일).

**백필 완료**: 영향 corp 전사 스캔(같은 로직 SQL 재현) — §1 대상 1,112개사, §6 대상
49개사, 합집합 **1,117개사**. pg_dump 백업(`/Volumes/tj_finance_data/db_backups/
std_financials_v3_pre_r63_backfill_20260902.dump`, 51MB) 후 `build_std_v3.py
--corp <1,117개사> --year-min 1999` 백그라운드 실행(corp 목록은 R62 선례와 동일하게
스크래치패드 산출물, git 비추적 — 세션마다 SQL로 재현 가능). **실행 결과**:
1,117/1,117 corp 성공(에러 0), 197,861행, 6,290초(105분).

**후속조치 — calendar_v3 재동기화(필수, 놓치기 쉬움)**: std_v3 백필 직후
`dq_assertions.py`를 돌려보니 `calendar_orphan_cq`(ERROR) 위반이 345건 새로
잡혔다 — `calendarize_corp_v3()`가 corp+basis 단위 delete-then-insert라서, std_v3
쪽만 바뀌고 그 corp의 달력테이블(`std_financials_calendar`)을 다시 안 돌리면
예전 std_v3 행을 가리키던 달력분기가 유령행으로 남는다(`diag_calendar_orphans.py`
문서화된 기존 패턴, 이번에 실측으로 재확인). 같은 1,117개사에 대해
`calendarize_corp_v3()`를 재실행(226,319행, 173초)해 완전 해소(`calendar_orphan_cq`
345→**0**). **교훈**: std_v3 백필 후에는 항상 이 재동기화까지 한 세트 —
`docs/runbook_new_parser_pipeline_integration.md`에 "std_v3 값을 바꾸는 백필은
calendar_v3 재동기화까지 포함"으로 명시 필요(다음 세션 후속).

**최종 검증**:
- `dq_assertions.py` 전체 실행: ERROR 위반 어서션 2→**1**(`calendar_orphan_cq`
  345→0, `statement_magnitude_impossible`는 이 트랙과 무관한 기존 결함 —
  150→146으로 오히려 소폭 개선, 이번 백필로 신규 유입된 corp 없음 확인:
  71개 위반 corp 중 59개가 R63 영향권과 겹치지만 이건 두 결함 모두 "옛 K-GAAP
  시대 문제 필링"에 몰리는 자연스러운 상관관계일 뿐 — 배제 로직은 NULL/삭제만
  하므로 구조적으로 새 magnitude-impossible 값을 만들 수 없음).
  `calendar_adjacent_year_cq1_identical`(WARN)도 부수 개선 73→9.
- 표본 원문대조 4건 재확인: 현대차 00164742 2004 연결 Q1/H1/Q3 전부 NULL,
  KG스틸 00115676 2006 연결 Q1/H1/Q3 전부 NULL(별도 Q1은 진짜값 505,829,999,432
  보존), 00171867 2009H1 연결 행 자체가 삭제(브래킷라벨 오염만 있고 대체소스가
  없었던 케이스).
- 단조성 위반(Q1≤H1≤Q3≤FY, revenue 기준, 2002~2011): 3,516→**1,225**(65% 감소).
  "Q1=H1=Q3 완전동일값" 서명: 824→**82**(90% 감소) — 잔존 82건은 임계값10 미달
  또는 fy>2012 범위밖 케이스로 추정(미확인, 범위 밖).

**부수 발견(범위 밖, 후속 트랙 후보)**: KG스틸 2006 별도 H1의 "Ⅰ. 매출액(주석13과
14)"가 account_mapper에 안 걸림(Q1의 "매출액(주석10)"는 걸림) — 복수 주석번호를
"와/과"로 묶은 표기 정규화 갭으로 추정, R63과 무관한 기존 account_mapper 라벨매칭
버그. 이 때문에 해당 corp의 별도 H1/Q3 revenue가 R63 이후 (틀린 재게재값 대신)
NULL로 전환됐지만 진짜 데이터 복구는 못 함 — 별도 트랙 후보로만 기록.

### R63 후속 §8 — CF(현금흐름표) 확장 (2026-09-02, 다음 세션)

**배경** — 후속 트랙 후보 3건 중 사용자가 "CF도 §1 패턴인지 검증"을 선택. 설계문서
§8/§9(`docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_design_
2026-09-02.md`).

**근본원인 — IS와 완전 동일, 원문대조로 확정**: KG스틸(00115676) 2006 Q1·Q3 원문 —
같은 필링 안에 "현 금 흐 름 표" TITLE 표가 2개. ①"제25기 **분기**"(당해 Q1, 진짜,
필링마다 값 다름) vs ②"제24기"(**분기접미어 없음**, 직전 연차, IS와 동일하게
재게재 — "영업활동으로 인한 현금흐름"=54,870,597,628원이 Q1·Q3 필링 원문에
바이트단위로 동일하게 등장, grep 확인). 전사 정량화(방법론 보강 — `is_final=true`
+서로다른period쌍만, 아래 §9 오탐 제거 전 수치): IS consolidated 97.2%(재현)/
separate 16.0%. **CF consolidated 67.5%(247개사)/separate 32.8%(1,284개사)**.

**구현**: `_stale_annual_reprint_table_seqs()`에 `statement: str = "IS"` 파라미터
추가(table_seq는 statement별 독립 카운터라 IS/CF를 섞으면 안 됨 — 반드시 statement별
로 따로 호출). `_resolve()`의 파라미터를 `stale_is_table_seqs: set`에서
`stale_reprint_table_seqs: dict[str, set]`(예: `{"is": {...}, "cf": {...}}`)로
일반화 — pre-pass가 각 prefix(`is.`/`cf.`)의 자기 자신의 set만 그 prefix
캐노니컬에 적용(다른 prefix의 set과 절대 안 섞임). `build_merged_lines()`의
브래킷라벨 가드(§6)는 원래부터 statement 무관하게 전체 적용이라 코드 변경 불요.
`combine_full()` 호출부가 IS/CF 각각 한 번씩(2회) `_stale_annual_reprint_table_
seqs()`를 불러 dict로 조립.

### R63 후속 §9 — ★탐지로직 버그 발견·수정: 같은 period 내 원본+정정신고 중복집계
오탐 (2026-09-02, 같은 세션 — CF 확장 원문대조 중 발견, **R63 원안(IS)에도 소급
영향**)

**발견 경위**: CF 확장 검증 중 현대차(00164742) 2004 Q1 **별도**(연결 아님) CF를
원문대조하다가 table_seq=0(진짜 당해분기 표 — "I. 영업활동으로 인한 현금흐름"이
Q1=-248,693백만/H1=1,485,674백만/Q3=1,812,881백만으로 분기마다 전부 다름, 원문
확인)이 **오탐으로 배제**돼 있는 것을 발견.

**근본원인**: `_stale_annual_reprint_table_seqs()`의 원래 SQL은 `cur`/`other` 양쪽을
그대로 report_lines 원본 행으로 JOIN해 `count(*)`를 셌다. 같은 (corp,fy,period,basis)
안에 필링이 2개 이상(원본+기재정정)이고 **둘 다 같은 label+value를 그대로 담고
있으면**(정정이 그 값을 안 건드린 흔한 경우), 매칭 행 수가 필링 개수만큼
배가된다 — 실측: 현대차 2004 Q1 별도는 원본(20040515000203)+정정(20040618000205)
2개 필링이 있고, H1과 우연히 일치하는 세부계정이 5개뿐인데 5×2필링=**10**으로
임계값(10)에 정확히 걸려 "재게재"로 오판정됨. **"몇 번 겹쳤는지"가 아니라
"몇 개 계정이 겹치는지"를 세야 하는데, 필링 중복이 전자로 오염시킨 것**.

**영향 규모(전사 재계산, table_seq 단위)**: IS 13,692→11,892(**1,800건/13.1%
오탐**), CF 19,659→17,759(**1,900건/9.7% 오탐**) — 두 statement 다 영향, **이미
커밋된 R63 원안(IS, `915d456`)의 1,117개사 백필도 이 오탐을 일부 포함**하고
있었음(수정 전에는 이 사실을 몰랐음). 새 로직으로 다시 계산해도 old_flagged ⊇
new_flagged가 항상 성립(dedup은 카운트를 줄이기만 함 → 오탐 제거는 항상 "배제를
푸는" 방향, 새로 배제를 만들지 않음 — 구조적으로 안전한 방향의 수정).

**수정**: cur/other 양쪽을 `(label_raw, value_won)` 기준으로 먼저 `DISTINCT` 시킨
뒤 매칭 — 같은 값을 여러 필링이 중복 보고해도 1건으로만 집계.

**검증**: 회귀 테스트 신설 2개(현대차 2004Q1 별도 CF 오탐 미발생 확인,
IS/CF stale set 독립성 재확인) + 기존 KG스틸 재현 테스트 불변 통과.
`pytest tests/ fin2/tests/` 708 pass(무관 기존실패 1건 불변).

**재백필(IS∪CF 합집합, 구탐지 기준 영향 corp 전체)**: pg_dump 백업(`/Volumes/
tj_finance_data/db_backups/std_financials_v3_pre_r63cf_backfill_20260902.dump`,
110MB) 후 CF 신규 1,405개사 1차 백필(238,499행/7,913초) → 오탐버그 발견 →
IS∪CF 합집합 **1,406개사** 수정된 코드로 재백필(238,800행/7,005초, 에러 0) →
`calendarize_corp_v3()` 재동기화(269,317행/207초, 실패 0, runbook B5) →
`dq_assertions.py`: `calendar_orphan_cq` 0 유지, `statement_magnitude_impossible`
146→147(+1, 무관 노이즈), `std_v3_conflicts_unresolved` 32,595→32,846(+251 —
오탐 수정으로 예전에 "후보 전멸→NULL"이던 일부 canonical이 이제 "진짜+오매치
후보 2개 있는 채로 HELD"로 바뀐 것으로 추정, HELD가 NULL보다 안전한 상태이므로
증가 자체는 우려사항 아님, 원인 확정은 미착수).
- 표본 원문대조 재확인: 현대차 00164742 2004Q1 별도 cfo=**-248,693,000,000**
  (수정 전 NULL 오탐 → 수정 후 원문과 정확히 일치하는 값으로 복구), KG스틸
  00115676 2006(H1 별도 cfo=4,941,866,221 불변, Q1/Q3 여전히 NULL — 진짜
  재게재라 회귀 아님).

**커밋 대기**(정책상 사용자 요청 시에만 커밋).

---

## R64. `parser/common/amount_normalizer.py::normalize_account_name()` — 주석번호
와/과/및 결합표기 정규화 갭 (2026-09-02, R63 후속 후보 착수)

**배경** — R63 §후속트랙 후보②(KG스틸 00115676 2006 H1/Q3 별도 revenue 복구
실패 원인으로 부수발견). 복수 주석번호를 콤마 대신 한글 접속사("와"/"과"/"및")로
묶는 표기(`"Ⅰ. 매출액(주석13과 14)"`, `"자본금(주석1과15)"`, `"매도가능금융자산
(주석5,7과29)"` 등, 콤마와 접속사 **혼합**형도 포함)를 구 정규식
`\(주석?\s*\d[\d,\s]*\)`이 못 잡았다 — 숫자 뒤 '과'/'와'/'및'에서 매치가 끊겨
괄호가 안 지워지고 라벨에 그대로 잔류.

**실측 영향(DB 전수 스캔)**: 이 결합표기 패턴을 포함하는 라벨 3,537종/10,226행
(197개사) 중, **`mapper.map(raw_label)` 실제 호출 경로**(combine.py 가 쓰는
그대로 — `normalize_account_name()`을 먼저 별도 호출해 미리 정규화한 뒤 넘기면
`map()` 내부가 또 한 번 정규화해 이중적용 착시가 생기므로 주의)로 수정 전/후를
정확히 대조한 결과 **1,943종/5,229행(178개사)**이 old-fail→new-pass 로 회복됨
— 자본금·매출액·유형자산·매입채무·재고자산 등 DIRECT_MAP 핵심 계정 다수 포함.
짧은 canonical(예: "매출액", 3자)일수록 잔류 노이즈("(주석13과 14)")가 fuzzy
ratio 를 임계값(0.88) 밑으로 끌어내려 완전 매치실패로 이어진다(긴 라벨은 노이즈
비중이 작아 fuzzy 로 우연히 구제되는 경우가 많았음).

**수정**: 주석 참조 제거 정규식 2곳(선두 미고정형·후방 고정형)의 숫자 목록
구분자 문자셋에 '와'/'과'/'및'을 추가 — `[\d,\s]*` → `[\d,\s와과및]*`. 콤마만
쓰는 기존 형태는 종전과 동일하게 동작(문자셋에 추가만 했을 뿐 제거 없음,
무손실 불변식 유지). `<주석N,...>` 리터럴 잔재 제거 정규식(2026-07-30 도입)은
DB 전수 스캔 결과 이 결합표기가 0건이라 변경 불필요.

**잔존 실패(무관 별개 원인)**: 위 회복분을 뺀 나머지는 **이 갭과 무관한 별개
원인 2가지**로 확인(둘 다 이 트랙 범위 밖, 별도 후보로만 기록):
1. 괄호 없는 연번 접두 "1)"/"2)" 류가 안 벗겨짐(`normalize_account_name()`은
   `(1)` 괄호형만 벗김, 예: `"2) 보험금비용(주석26과27)"` → 정규화 후에도
   `"2) 보험금비용"` 잔류) — 보험사 IS 세부계정에 집중.
2. `account_maps/*.py` 자체에 alias 미등록(정규화는 정상이지만 canonical 이
   없음, 예: `"만기보유금융자산"`·`"책임준비금"`·`"부동산임대수익"`) — 보험/
   특수업종 전용 계정 다수.

**계층 영향**: 계층2(`report_lines.py`)는 `account_mapper`를 안 씀(R62/R63과
동일) — 이번 수정은 **계층3(combine.py 매핑)에만 영향**, 계층2 재추출 불요.

**검증**: 회귀 테스트 신설(`fin2/tests/test_amount_normalizer_note_ref_conjunction_
r64.py`, 3개 — 결합표기 정규화, 기존 콤마전용 무회귀, end-to-end 매핑 복구 확인).
`pytest tests/ fin2/tests/` 711 pass(무관 기존실패 1건 `test_biz_section.py::
test_lxintl_facility_table_dropped` 불변).

**백필 완료**(같은 세션, 사용자 승인 후 직접 실행): pg_dump 백업(`/Volumes/
tj_finance_data/db_backups/std_financials_v3_pre_r64_backfill_20260902.dump`,
52.9MB) 후 `build_std_v3.py --corp <178개사> --year-min 1999` 실행 —
178/178 corp 성공, 31,036행, 1,010초(17분), 에러 0. 이어서 `calendarize_corp_
v3()` 재동기화(178개사, 33,977행, 29초, 실패 0, runbook B5).

**검증 완료**:
- `dq_assertions.py`: `calendar_orphan_cq` 0 유지, `statement_magnitude_
  impossible` 147(R63 §9 종료 시점 기준선과 동일, R64로 인한 신규 위반 0),
  `std_v3_conflicts_unresolved` 32,846→**32,803(−43, 개선)** — 기존엔 후보
  전멸로 NULL이던 canonical이 이번 수정으로 단일 정답 후보를 얻어 HELD 없이
  깔끔하게 resolve 된 것으로 추정(우려사항 아님).
- 원문대조(KG스틸 00115676, 2006 separate revenue): Q1=505,829,999,432(기존
  정상)·**H1=557,076,012,411**(수정 전 NULL → 원문 rcept 20060814001339 값과
  정확히 일치)·**Q3=563,912,093,240**(수정 전 NULL → 원문 rcept 20061114001258
  값과 정확히 일치). Q1≤H1≤Q3 단조성도 정상(진짜 누적매출 패턴, R63이 걸러낸
  "직전연차 재게재" 정적값과 무관한 진짜 당해분기 데이터).

**R64 트랙 완전 종료 — 커밋만 대기**(정책상 사용자 요청 시에만 커밋).

---

## R65. `parser/xml/table_extractor.py` — 헤더 `<TH>주석</TH>` 기반 주석열
탐지 신설, note-ref multicol 압축 값오염 근본수정 (2026-09-03)

**배경** — [[note-ref-multicol-compaction-value-corruption-2026-09-02]](메모리),
설계문서 `docs/plans/note_ref_multicol_compaction_value_corruption_design_
2026-09-02.md`. R64 후속 트리아지(TINY_VALUE_BUG 56건) 표본조사 중 우연발견한
계층2(layer2) 원천 버그 — R19(2026-08-24)의 안전장치가 발동하지 않는 조건이
있었다.

**근본원인** — `_table_has_comma_note_column()`(R19)은 표 안 어딘가에 콤마로
묶인 다중 주석참조("10,37")가 **하나라도 있어야만** 그 표를 "주석열이 있는
표"로 판정한다. 그런데 매 행이 주석을 하나씩만 인용하는 표(콤마가 표 전체에
단 한 번도 안 나옴, 드물지 않음)에서는 이 신호가 영원히 False로 남아 안전장치
자체가 발동하지 않았다. 그러면 라벨 바로 다음 칸의 주석번호("5"/"21"/"22" 등)
가 진짜 금액 후보로 그대로 살아남고, `report_lines.py`의 multicol(보험/증권
다열) 압축 경로가 "None 아닌 값을 위치 그대로" 압축하면서 주석번호가
`col_index=0`("당기" 슬롯)을 차지해버려 **진짜 당기금액이 `col_index=1`
("전기" 슬롯)로 밀려 오분류**되고, `_is_loadable()`(BS/IS/CF는 `col_index==0`
만 적재)에 걸려 **진짜 당기금액 자체가 DB에서 소실**됐다(00537337 2011FY
실측 — "Ⅰ.매출액"=5원, 진짜 458억은 DB에 아예 없었음).

**수정**: `_table_has_note_header()` 신설 — 표 헤더 `<TH>` 셀 텍스트에 "주석"
문자열이 있으면 콤마 여부와 무관하게 주석열로 판정(값 모양이 아니라 원문
헤더 선언 그 자체에 기대는 구조적 신호). `table_direct_rows()`가 THEAD 행도
포함해 순회하므로(TABLE 경계만 자름) 기존 `trs` 순회에 이미 헤더 행이 들어
있다 — 새 함수만 추가하고 `_table_has_comma_note_column()`과 OR로 병행:
```python
table_has_note_column = (
    _table_has_comma_note_column([_get_cells(tr) for tr in trs])
    or _table_has_note_header(trs))
```
`_table_has_comma_note_column`은 콤마 신호가 있으면 여전히 그대로 True를
주므로 기존 동작에 무손실(추가만, 제거 없음).

**원문대조 확정 2건**:
- 00537337(앤씨앤) 2011FY(rcept 20120329000506, K-GAAP→IFRS 전환기): "Ⅰ.매출액"
  col_index0=5원(오염)→**45,830,369,541원**(원문 XML 직접대조 일치)으로 복원 —
  수정 전엔 진짜 당기값이 DB에서 아예 소실됐었음.
- 00132202(선진뷰티사이언스) 2020FY(rcept 20210323001110, K-IFRS 정상표기
  시대): 연결·별도 양쪽 동시오염(21/22로 오채택)→**연결 46,392,320,333원 /
  별도 43,725,183,663원**으로 복원. **2020년대까지 재현 확정** — K-GAAP 한정
  버그가 아니라 현재도 활성인 상시 구조적 갭.

**규모(ground-truth 정밀 스캔, 값-휴리스틱 아님)**: 전 코퍼스(187,413건 완료
XML filing) 단일패스 스캔 — 기존 콤마신호는 False인데 새 헤더신호가 True로
바뀌는 테이블 유무를 5-shard 병렬로 직접 재현(86분/shard). **4,475개 필링(rcept)
/ 882개사**가 실제 영향권(2001~2026 전 기간, IS 1,750·H1 961·Q1 852·Q3 912
분포). 설계문서 §3.1의 값-충돌 휴리스틱 추정(고신뢰 296개사/1,116필링)은
과소추정이었음이 이 정밀스캔으로 확인됨(§5.3-2 우려가 실측으로 입증) — R19
전례(`run_r19_backfill_parallel_2026-08-14.sh`, 같은 클래스의 탐지로직 변경)가
전수 재추출을 관행으로 삼은 이유와 일치.

**검증**: 회귀 테스트 신설 2개(`fin2/tests/test_report_lines.py`, 00537337·
00132202 원문대조 실측값 재현). `pytest tests/ fin2/tests/` 712 tests, 711
pass — 유일한 실패 `test_biz_section.py::test_lxintl_facility_table_dropped`는
OLD `table_extractor`로도 동일 재현되는 **이 수정과 무관한 사전 존재 결함**임을
직접 대조로 확인(R63/R64와 동일한 불변 실패). 코드 커밋 `86a560b`.

**백필 완료**(같은 세션, 사용자 승인 하 직접 실행 — "4번까지 쭉 이어서 직접
실행"): pg_dump 백업(`/Volumes/tj_finance_data/db_backups/
std_financials_v3_pre_r65_backfill_20260902.dump`, 52.9MB) 후
1. `load_report_lines.py --fy-min 1999 --rcept-file <4,475건>` — **4,475/4,475
   완료, 에러 0**, report_lines 1,588,820행, 이상치 277건(26분). ⚠**첫 두 차례
   시도는 `--fy-min` 기본값(2015)을 빠뜨려 2001~2014 구간 1,066건이 조용히
   누락됐다가 재실행으로 정정** — 이 클래스 스크립트를 다시 쓸 때 fy-min 기본값
   함정 재확인 필요.
2. `build_std_v3.py --corp <882개사> --year-min 1999` — **882/882 corp 성공,
   123,409행, 3,890초(65분), 에러 0**.
3. `calendarize_corp_v3()` 재동기화(882개사, 140,269행, 110초, 실패 0).

**검증 완료**:
- `dq_assertions.py`: 유일한 ERROR 위반 `statement_magnitude_impossible`
  147건 — pg_dump 백업 대비 **row-key 단위 정확 대조로 147=147, 신규위반
  0건** 확정(R65와 완전 무관한 R63-era 기존결함). WARN
  `std_v3_conflicts_unresolved` 32,803→**32,789(−14, 개선)**,
  `operating_income_eq_net_income` 23=23(불변).
- Gate B(`gateb_audit.py --recheck`) 전수 재감사(5-shard): `face_audit_
  snap_20260902_pre_r65`(303,903행) 대비 등급전이 매트릭스 — **fail_a
  63=63(같은 63건, 신규 fail_a 0건)**, fail_b 525→**477(−48, 개선)**,
  pass 207,276→207,328(pending 왕복 포함 순증 +52). **pass→pending 3건**
  (00135917 2022 Q1/H1/Q3 consolidated) 개별 원인규명 완료 — `tax_expense`가
  수정 전 주석번호 "34"(오염값)로 **거짓으로 항등식을 통과**하고 있었는데,
  수정 후 진짜 값(226~289억원대)으로 교체되면서 Phase B 라인 대조가 아직
  확증을 못 찾아 `pending`(정직한 불확실 표시)으로 재분류된 것 — **데이터
  품질 개선의 정상 부작용**, 회귀 아님(원문대조로 확정).

**R65 트랙 완전 종료**. 코드 `86a560b`, 문서 이 커밋.

---

## R66. `fin2/layer3/combine.py::combine_full()` — 증권/보험/은행/여신전문
표준매출액 계산기(`apply_revenue_profile()`)에 R63 stale-reprint 필터 배선
(2026-09-03)

**배경** — [[std-v3-upstream-defects-r62-and-monotonicity-2026-09-02]](메모리),
설계문서 `docs/plans/std_v3_kgaap_interim_consolidated_stale_annual_reprint_
design_2026-09-02.md` §10. R65 종료 직후 세션, 잔존 단조성위반 트리아지(§9)의
EXACT_EQUAL_RESIDUAL(25건) 후속 조사. 최초 가설("R63 임계값 10개 미달, 증권업
특수계정이라 매치가 안 됨")을 00104856(삼성증권) 표본 직접 SQL 재현(매치
165개, 임계값을 압도적으로 초과)으로 반증.

**진짜 근본원인** — `combine_full()`이 `_resolve()` 호출 직전에 R63의
`_stale_annual_reprint_table_seqs()`로 stale-reprint table_seq를 계산해
`stale_reprint_seqs` dict(`{"is": ..., "cf": ...}`)를 만들지만, 이 값은
`_resolve()`(→ DIRECT_MAP `cands` 정제)에만 전달되고, **같은 함수 뒤쪽의
`apply_revenue_profile(is_lines, ...)` 호출**(증권/보험/은행/여신전문 업종
전용 "표준 매출액 = 명명된 소계 조합" 계산기, 예: 증권 `net_op_formula` =
영업이익+판매관리비)은 필터링 안 된 원본 `merged` IS 라인을 그대로 읽는다 —
같은 원인(K-GAAP 시대 연결 인터림 재게재)의 **두 번째 소비 경로**가 R63
구현 당시 누락됐던 것.

**00104856 원문/DB대조로 메커니즘 확정**: FY2004 영업이익
(154,594,395,676)+판관비(517,609,979,403, `conflicts.is.sga`에 남아있던
후보값과 정확 일치)=**672,204,375,079** — 2005 Q1/H1/Q3 std_v3 revenue와
정확히 일치. 둘 다 R63이 이미 "직전연차 재게재"로 확정한 stale
table_seq=0 출처. EXACT_EQUAL_RESIDUAL 25건 중 23건(92%, 13개사 중
11개사)이 증권/보험 업종(`SECURITIES`/`INSURANCE` 프로파일 적용대상).

**수정**: `combine_full()`의 `apply_revenue_profile()` 호출 앞에서, 이미
계산돼 있는 `stale_reprint_seqs["is"]`로 `is_lines`를 필터링한 뒤 호출.
`basis_fallback` 케이스(별도 basis만 있는 회사의 연결 폴백)도 `_resolve()`가
기존에 하던 것과 같은 처리(요청 basis로 계산된 stale set을 그대로 재사용)로
일관성 유지.
```python
is_lines = [r for r in is_lines
            if r.get("table_seq") not in stale_reprint_seqs["is"]]
applied = apply_revenue_profile(is_lines, _get_induty(session, corp), corp)
```

**전체스케일 정밀 스캔(ground-truth, R65식, 실제 프로덕션 함수 직접호출)**:
증권/보험/은행/여신전문 induty_prefix 대상 103개사×2002~2011×Q1/H1/Q3×연결/
별도 전수 재계산 — **checked=2,885 / profile_applied=651 / changed=312건
(18개사)** — 최초 증상신호(25건)의 12.5배, R65와 동일한 "좁은 증상신호 ≪
실제 영향범위" 패턴. 전부 `securities` 프로파일에서만 발생(보험/은행/여신전문
0건), 연결 206/별도 106, **312건 전부 old(오염값)→new=None**(대체 후보
없음, R63의 "복구 아닌 배제" 원칙과 동일 성격, 새 오염 0건). 구현 세션에서
production 코드로 재현한 결과도 정확히 동일(changed=312건/18개사) — 값
확정.

**검증**: 회귀 테스트 신설 `fin2/tests/test_combine_r66_revenue_profile_
stale_reprint.py`(00104856 FY2005 Q1/H1/Q3 consolidated old→None 확인 +
separate 비영향 확인). `pytest tests/ fin2/tests/` 717 pass(유일한 무관
기존실패 `test_biz_section.py::test_lxintl_facility_table_dropped` 불변,
R63~R65와 동일).

**백필 완료**(같은 세션, 사용자 승인 하 — "1번으로 진행하자"): pg_dump
백업(`/Volumes/tj_finance_data/db_backups/
std_financials_v3_pre_r66_backfill_20260903.dump`, 52.8MB) 후
1. `build_std_v3.py --corp <18개사> --year-min 1999` — 18/18 corp 성공,
   3,106행, 98초, 에러 0.
2. `calendarize_corp_v3()` 재동기화(18개사, 3,163행, 실패 0).

**검증 완료**:
- `dq_assertions.py`: 유일한 ERROR 위반 `statement_magnitude_impossible`
  147건 — 세션 시작 전 기준값과 **147=147, 신규위반 0건** 확정(R66과 무관한
  기존결함). WARN `std_v3_conflicts_unresolved` 32,846→**32,789(개선)**.
- Gate B: 이번 백필이 정확히 18개사에만 스코프돼 다른 회사 std_v3는 전혀
  변경되지 않았으므로, R63/R65의 전체 5-shard 대신 **이 18개사만 스코프한
  PK조인 전이표**로 검증(총량비교 아닌 row-key 단위 대조,
  [[gateb-482-backlog-cluster-ab-rootcause-2026-08-27]] 교훈과 동일 원칙).
  `face_audit_snap_20260903_pre_r66`(3,145행) 대비 `gateb_audit.py --recheck
  --corp-file <18개사> --fy-min 1999` 재실행 후 PK(corp_code, fiscal_year,
  fiscal_period, statement_type, is_stub) 조인 — **pass→pass 1655 /
  pending→pending 1486 / fail_b→fail_b 4, 전이 0건**(신규 fail_a 0, 등급
  하락 0). 312건의 revenue가 오염값→NULL로 바뀌었음에도 face_audit 행수준
  gate_status가 완전히 불변인 것은, 이 시대(2002~2011) 필링엔 대조할 XBRL
  원천이 없어(Track A 미적용) Track B(텍스트 대조)도 이 필드를 이미
  pending으로 다루고 있었기 때문으로 추정(원문대조 아님, 정황).

**R66 트랙 완전 종료**. 코드 커밋 완료(`1b47f44`).

---

## R67. `fin2/extract/text.py`/`fin2/extract/report_lines.py` — 계층2 문서레벨
단위폴백(`document_default_unit`) 오귀속, "같은 SECTION-2 우선 참조 + 더 작은
배수 선호" 가드레일로 수정 (2026-09-03)

**배경** — R66 종료 직후 세션, IRREGULAR 하위클러스터링(818건, 100+ ratio
버킷) 표본 조사 중 발견. 설계문서 `docs/plans/std_v3_kgaap_interim_
consolidated_stale_annual_reprint_design_2026-09-02.md` §12(근본원인+
스케일산정)에 이어 같은 세션에서 구현+백필까지 완료.

**근본원인** — `document_default_unit()`은 본문 표에 로컬 단위선언이 없을 때
"요약재무정보" 섹션 첫 데이터표의 단위를 "문서 전체 기본값"으로 반환한다.
이 값은 **그 요약표 자신에게는 정당**(요약표는 흔히 천원/백만원 압축표기)하지만,
"같은 진짜 값을 가리킨다"는 것과 "같은 배수를 곱해야 원래 자릿수가 나온다"는
것은 별개다 — 로컬선언이 공란인 본문 표가 이미 **압축 없는 원 단위 숫자**를
그대로 인쇄해놨을 수 있다.

**표본 1**(00240857/바이오스마트 2005H1): 손익계산서 "매출액" 로컬선언
공란, 요약재무정보 표는 천원 단위로 "10,859,787"(=10,859,787,838원 압축
표기) 표시. 반면 본문 표는 이미 "10,859,787,838"(압축 없는 원 단위)을
그대로 인쇄 — 요약재무정보의 ×1000을 그대로 적용하면 H1=10,859,787,838,000
(1000배 과다). **표본 2**(00101549/경동제약 2003Q3 CF): 다른 회사·다른
statement로 동일 메커니즘 재현(백만원 오귀속).

**첫 시도(단순 "같은 SECTION-2 첫 선언 우선") — dry-run으로 반례 발견,
가드레일로 재설계**: 처음엔 "로컬선언 공란 시 요약재무정보보다 먼저 **같은
SECTION-2("재무제표" 등) 안의 다른 표** 선언을 찾는다"는 단순 규칙
(`nearest_section_default_unit()`)만 구현했으나, 976개 필링 전체
dry-run에서 **00171867(에스씨디) 2006Q3 반례 발견**: 같은 "4. 재무제표"
섹션 **안에서도** 인쇄 관행이 섞여 있었다 — 본문 대차대조표/손익계산서는
정상적으로 "(단위 :천원)" 선언(진짜 이 섹션 대부분의 관행)인데, 그 뒤쪽
같은 섹션에 로컬선언 공란인 별도 "3개월/누적" 상세표가 있었고 이 상세표는
이미 **압축 없는 원 단위**("18,805,337,508")를 인쇄해놨다. 단순 규칙대로
"같은 섹션 첫 선언"(천원)을 그대로 적용했다면 18.8억원이 18.8조원이
됐을 것 — 인접 분기값들(7~38억원대, 전부 `declared`, 신뢰 가능)과 3~4자리
어긋나는 명백한 회귀. 반면 `document_default_unit()`(이 필링은 요약재무정보에
선언이 없어 회계정책 주석의 "…원(KRW)…" 문구로 unit=1)이 이미 정답을
갖고 있었다 — "같은 섹션이 항상 더 안전하다"는 가정이 깨지는 실측 사례.

**최종 수정(`_pick_fallback_unit()`)**: 로컬 선언도 FX도 아닐 때,
`nearest_section_default_unit()`(같은 SECTION-2)과 `document_default_unit()`
(요약재무정보/회계정책주석) 두 후보를 **모두** 계산해, **배수가 더 작은
쪽**을 택한다(동률이면 더 국지적인 section_def 우선). 근거: 976개 필링
전수 dry-run 결과 진짜 교정의 **97.98%가 "과다배수 오적용 → 축소가
정답"** 방향이었다(과소배수 오적용은 극소수) — "더 작은 배수가 옳다"가
가장 안전한 보수적 선택. 이 가드레일 적용 후 재검증: 인플레이션(교정 후
값이 더 커지는) 방향 잔존 10건(0.02%)까지 축소, 그중 확인된 것들은 이미
백업(교정 전) 시점부터 존재하던 퇴화값(old=0 등)이라 R67 기인 신규 회귀
아님. 00171867/00240857/00101549 세 표본 전부 최종 코드로 재검증 통과.

**unit_source 신규값**: `section_def`(varchar(14) 제약으로 축약, 원래
"section_default") — "같은 SECTION-2 안 다른 표에서 찾음"을 표시.
`doc_default`(기존, "요약재무정보/회계정책주석에서 찾음")와 별도 provenance로
구분.

**검증**: 회귀 테스트 신설 8개 — `fin2/tests/test_report_lines.py`(파일
기반: 00240857 H1/Q3 값 정확 복원, 00101549 CF 복원, 기존 4건 무회귀
가드 갱신[인카금융서비스만 doc_default→section_def로 provenance 변경,
값은 동일 unit=1이라 무회귀], 합성 XML 3개 — 같은섹션탐지·타섹션배제·
캐시재사용). `pytest tests/ fin2/tests/` 723 pass(유일한 무관 기존실패
`test_lxintl_facility_table_dropped` 불변, R63~R66과 동일).

**전체스케일 dry-run**(재파싱만, DB 미변경 — 976개 필링 전부 재추출해
현재 DB와 대조): **47,561건 실제값 변경**(SQL 신호 스캔의 14,936건보다
3.2배 큼 — R65/R66과 같은 "좁은 신호≪실제스코프" 패턴), 그 중
99.98%(47,551건)가 축소 방향(과다배수 제거). statement별 CF
22,229·IS 14,102·BS 10,601·SCE 1,568 — **BS도 실제로 영향받음**(§12.2의
SQL신호는 BS 0건으로 과소추정했던 부분, dry-run 직접재현으로 드러남).

**백필 완료**(pg_dump `std_financials_v3_pre_r67_backfill_20260903.dump`
52.8MB + `report_lines_snap_20260903_pre_r67` 스코프 스냅샷 308,056행
백업 후):
1. `load_report_lines.py --fy-min 1999 --rcept-file <976건>` — 974/976
   완료(2건 파일누락, 기존 결측과 무관), 에러 0, report_lines 311,812행,
   이상치 53건, 5분.
2. `build_std_v3.py --corp <485개사> --year-min 1999` — 485/485 성공,
   84,348행, 2,681초(45분), 에러 0.
3. `calendarize_corp_v3()` 재동기화(485개사, 93,291행, 실패 0).

**검증 완료**:
- `dq_assertions.py`: `statement_magnitude_impossible` **147→32**(115건
  개선 — R63~R66은 이 지표가 항상 불변이었는데 R67은 처음으로 큰 폭
  개선, 이 어서션이 정확히 겨냥하는 "단위 ×10³~10⁶ 오염" 클래스와 R67
  근본원인이 정확히 일치하는 신호). 잔존 32건 중 14건이 R67 스코프
  485개사 안에 있으나, pg_dump 백업 텍스트 직접대조로 **전부 백필
  이전부터 존재하던 값**(신규 회귀 0건) 확정. `bs_identity_gt5pct`
  970→947(개선).
- Gate B: 변경 스코프가 485개사로 R66(18개사)보다는 크지만 전체
  코퍼스(2,546개사)보다는 훨씬 작아, R66과 동일하게 **스코프 PK조인
  전이표**로 검증(전체 5-shard 대신). `face_audit_snap_20260903_pre_r67`
  (84,903행) 대비 `gateb_audit.py --recheck --corp-file <485개사>`
  재실행(XBRL 처리 포함 약 2.5시간) 후 PK(corp_code, fiscal_year,
  fiscal_period, statement_type, is_stub) 조인 — **pass→pass 51,873 /
  pending→pending 32,858 / fail_b→fail_b 153 / fail_a→fail_a 19,
  전이 0건**(신규 fail_a 0, 등급 하락 0). R66과 같은 이유(이 시대 필링
  다수가 XBRL 미존재로 Track A 미적용, Track B도 이미 pending 처리)로
  face_audit 행수준 gate_status가 완전 불변으로 추정(정황).

**R67 트랙 완전 종료**. 코드 커밋 완료(`6cfb456`).

---

## R68. `account_maps/bs_accounts.py`+`cf_accounts.py`+`fin2/layer3/combine.py` —
P1A: `lease_liability`/`borrowings_proceeds`/`borrowings_repaid` v2 파리티 3컬럼
신설 + bare "리스부채" 섹션기반 재분류 (2026-09-03) — **완전 종료(구현+테스트+
전사백필+검증)**

**배경**: `docs/plans/std_v2_retirement_port_to_v3_2026-08-22.md` §Phase 1(P1A,
2026-08-22 설계·안전성조사 T0~T7 완료·SPLIT_DRAFT 확정)의 마지막 미착수 항목.
`v2-drop-remaining-backlog-2026-09-03`(메모리) 체크리스트 3번.

**구현**: `account_maps/bs_accounts.py`에 `bs.lease_current`/`bs.lease_noncurrent`
신설(SPLIT_DRAFT 그대로, `bs.lease_liability`는 무수식 총계 라벨만 남김),
`account_maps/cf_accounts.py`에 `cf.borrow_proceeds_st`/`_lt`·`cf.borrow_repaid_
st`/`_lt` 신설(단기/장기 명시 라벨만 이동, "기타금융부채"·"유동성장기..." 등
만기귀속 애매한 변형은 SPLIT_DRAFT 원안대로 집계에 그대로 둠). `std_financials_
v3`에 3컬럼 추가(마이그레이션 `2026_09_std_financials_v3_lease_borrowings`).
`combine.py`에 `_lease_liability_value()`/`_borrowings_values()`(부품 합산, 없으면
집계 라벨로 폴백) 신설, `_apply_enrichment()`에 배선 + `_VALUE_COLS`(build.py) 추가.

**원문대조로 SPLIT_DRAFT 자체의 갭 발견·수정**: 무수식 "리스부채"/"금융리스부채"
라벨을 "총계, 그대로 둠"으로 가정한 원 설계가 실측과 어긋남 확인 — DB 전수 스캔
결과 이 무수식 라벨의 대다수가 실제로는 `section_path`상 `부채>유동부채`
(13,654행/574개사) 또는 `부채>비유동부채`(20,085행/779개사) 섹션 안에 위치(라벨
자체엔 유동/비유동 wording이 없을 뿐). 원문 2건 직접대조:
- 경농(00101433) 2025FY 별도: bare "리스부채"(772,424,809, `section_path=
  '부채>유동부채'`)와 "비유동 리스부채"(938,907,694)가 같은 필링에 공존 — 진짜
  총계는 두 값의 합(1,711,332,503). 섹션신호 없이 폴백만 쓰면 비유동분만
  채택되고 유동분(bare)이 통째로 누락됨.
- 00101664: 완전히 동일한 "리스부채" 텍스트가 같은 필링 안에서 유동/비유동
  섹션에 각각 다른 값으로 존재(2020H1: 802,546,265/1,201,208,120) — 분해 후에도
  같은 canonical로 충돌해 HELD(분해 전과 동일 결함).

**수정**: `_route_bare_lease_by_section()` 신설 — 다른 부채계정에 이미 있는
sibling 재라우팅 패턴(`_NONCURRENT_SIBLING`/`_CURRENT_CONTAMINATED_NONCURRENT_
SIBLING` 계열)과 같은 자리(cands 전체 순회 전 pre-pass)에서, `bs.lease_liability`
후보를 `section_path`로 먼저 판정 — 유동/비유동이 명확하면 해당 split canonical로
옮기고(사용자 지시: "위치를 알 수 있으면 위치로 판단, 위치가 명확하지 않으면
이름으로"), 섹션도 애매한 잔여만 진짜 집계로 유지. sibling이 이미 자기 라벨로
후보를 가진 경우엔 중복합산 방지를 위해 옮기지 않음(기존 guard 1과 동일 원칙).
CF 차입 쪽(`cf.borrow_proceeds/repaid`)은 실측 결과 section_path가 전부
"재무활동현금흐름"류로 균일해 이 문제 없음(BS 리스부채만의 결함).

**격리성 확인**: `bs.lease_liability`/`bs.lease_current`/`_noncurrent`,
`cf.borrow_proceeds_*`/`cf.borrow_repaid_*`는 이번 P1A 코드 밖에서 아무도 안 읽음
(grep 확인) — 기존 검증된 다른 컬럼(net_debt/total_liabilities 등)에 영향 불가,
신설 3컬럼만 채워지거나 NULL로 남는다.

**검증**: 신규 회귀테스트 18개(`fin2/tests/test_combine_p1a_lease_borrowings.py`,
순수함수 단위테스트), `pytest tests/ fin2/tests/` 741 pass(무관 기존실패 1건
`test_lxintl_facility_table_dropped` 불변). 표본 4개사(00100601·00101433·
00101549·00101664) 재빌드 후 위 두 원문대조 사례 전부 정확히 일치 확인
(1,711,332,503·2,003,754,385).

**전사 백필 완료(같은 날, 사용자 승인)**: pg_dump 백업(`std_financials_v3_
pre_r68_backfill_20260903.dump`, 53MB) 후 `build_std_v3.py --all --year-min
1999`을 5-shard 병렬(10코어 중 5개)로 실행 — **2,546/2,546 corp 전부 성공,
에러 0**, 302,436행(총 984초/샤드당 약16분, 5개 동시실행). 위 두 원문대조
표본값(1,711,332,503·2,003,754,385) 전사 백필 후에도 정확히 유지 확인.
**채움 규모**: `lease_liability` 91,679행/2,044개사, `borrowings_proceeds`
210,267행·`borrowings_repaid` 219,659행/합계 2,492개사.

**calendar_v3 재동기화 불요**(런북 B5과 달리 이번엔 스킵 — 근거): `std_financials_
calendar`/`fin2/standardize/calendar_v3.py`의 `_FLOW_COLS`/`_STOCK_COLS`에 이
3컬럼 자체가 없어(달력 스키마 미확장, 별도 후속 트랙 필요시) 재동기화해도 이번
백필 결과가 반영될 곳이 없다 — 이산분기/스크리너 화면에는 아직 안 나타남(알려진
범위 제한, 필요시 별도 트랙).

**검증**: `dq_assertions.py` ERROR `statement_magnitude_impossible` 32=32(신규
0, R68과 무관한 기존 이슈 불변). WARN `std_v3_conflicts_unresolved` 32,858→
33,632(+774, 신설 6개 canonical — `bs.lease_current`(36)·`bs.lease_noncurrent`
(581)·`cf.borrow_proceeds_st`(191)·`cf.borrow_proceeds_lt`(172)·`cf.borrow_
repaid_st`(222)·`cf.borrow_repaid_lt`(118) — 가 새로 잡히기 시작한 것으로 정확히
설명됨, "결측이 오염보다 안전" 원칙대로 해당 행은 NULL 유지). **Gate B 전수/스코프
재감사는 생략**(위 격리성 확인대로 이 3컬럼은 Gate B가 감사하는 기존 필드
어디에서도 안 읽혀 gate_status 전이가 원리적으로 불가능 — R66/R67의 "스코프 좁으면
PK조인 전이표"보다 한 단계 더 강한 케이스, 코드리뷰(grep)만으로 충분).

**R68 트랙 완전 종료**. 코드+백필 커밋 완료(`8b8d3a0` 코드, 문서 커밋은 이어서).
`v2-drop-remaining-backlog-2026-09-03`(메모리) 체크리스트 3번 완료.

---

## R69. `parser/xml/section_detector.py`+`fin2/extract/text.py`+`fin2/extract/
statement_titles.py` — Category C fy2004~2017 레거시 헤딩 갭 (E)+(D)+(B) 묶음
수정 (2026-09-05) — **완전 종료(구현+테스트+백필+검증)**

**배경**: `v2-drop-remaining-backlog-2026-09-03`(메모리) 항목 1-b 원인규명
(`docs/plans/factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3) — Category C
fy2004~2017 실패 5,739건이 절단(다운로드 결함)이 아니라 **레거시 XML 레이아웃
변종을 파서가 못 알아보는 5가지 서로 다른 갭**으로 확인됨. 이번 R69는 그중 규모가
가장 큰 (E)와, (E)를 실질적으로 완성시키는 (D)·(B) 3개를 묶어 처리한다(설계 문서:
`docs/plans/category_c_legacy_appendix_variant_design_2026-09-05.md`, (E) 단독
구현 시 실측 회수율이 낮음을 사전 확인한 근거 포함). (A)(SECTION-3 서브헤딩
리셋, fy2004~2006 943건)와 (C)("요약" 접두, fy2014류)는 이번 스코프 밖 — 별도
트랙.

**규칙**:
- **(E) 레거시 컨테이너 동의어**: `section_detector.py`에 `SEC_LEGACY_APPENDIX =
  "부속명세서"` 신설. `_DART_SECTION_EXACT`엔 안 넣는다(`SEC_LEGACY_FS`와 같은
  이유 — 주석표 유입 차단). `_detect_legacy_body_statement_tables()`
  (`fin2/extract/text.py`)가 `SEC_LEGACY_FS`("재무제표등")로 못 찾을 때만 이
  컨테이너로 재시도 — 기존 "재무제표등" 경로는 이 분기 자체가 안 타 100% 무변경.
  근거: fy2007~2010(특히 2009) 분기/반기보고서는 재무제표를 "XI.부속명세서"
  SECTION-1 아래 나열하는데, 내부 헤딩→표 인접구조는 "XI.재무제표 등"과
  동일하다(실측 무작위 300건: 부속명세서 249 · 재무제표등 14).
- **(D) 괄호 병기 표제**: `classify_legacy_statement_heading()`
  (`fin2/extract/statement_titles.py`)이 재무제표명 직후 `(대차대조표)`류
  괄호병기(IFRS 전환기 신·구 명칭 병기)를 표제의 일부로 소비하고 남은 텍스트로
  재판정하도록 `_LEGACY_ALT_NAME_PAREN` 신설. 실측(부속명세서 버킷 40건): BS
  헤딩의 92.5%가 "재무상태표(대차대조표)" 형태라 이걸 안 고치면 (E)를 넣어도
  BS만 계속 빠진다.
- **(B) 한글 가나다 열거접두**: 숫자·로마숫자 접두(`_LEGACY_ENUM_PREFIX`, 주석
  항목번호 표지 — 그대로 거부 유지)와 별개로, "가.","나."… 열거기호는 이
  레이아웃에서 재무제표 목록 전용 표지다. `_LEGACY_KO_ENUM_PREFIX`로 한 글자만
  벗기고 재판정 — 벗긴 뒤에도 재무제표명이 안 걸리면(예 "가.대손충당금설정내역")
  그대로 거부되므로 새 오탐 경로가 생기지 않는다.
- 세 변경 다 **추가적**(기존에 `None`/빈 결과로 끝나던 곳에 재시도 한 번을
  끼워넣는 것) — 표 선택·단위판정(`declared_unit`)·pending 거리제한
  (`_LEGACY_PENDING_SPAN`)·주석마커 차단(`is_legacy_note_marker`)은 무변경.
  이 폴백은 애초에 `SEC_CONSOL_FS`/`SEC_SEP_FS` 둘 다 없을 때만 호출돼(오늘
  기준 이 경로를 타는 문서는 전부 현재 0행) 회귀 가능 범위가 원천적으로 좁다.

**검증(합성 XML, `fin2/tests/test_legacy_layout_tables.py`)**: 신규 회귀테스트 6개
추가(컨테이너 폴백 성공/미발동, section_kind provenance 정확성, 괄호병기 소비,
가나다접두 제거, 가나다접두 제거 후에도 재무제표명 아니면 계속 거부 확인,
숫자접두는 계속 거부). `pytest tests/ fin2/tests/` **747 pass**(무관 기존실패 1건
`test_lxintl_facility_table_dropped` 불변, R68 시점과 동일).

**실측 검증(원문대조)**: 원인규명 때 실패로 확인했던 실제 표본 재실행 — 에너토크
2009H1(D+E, `20090814000347`): 533행 복구, BS 항등식(자산총계 21,229,332,600 =
부채총계 5,189,699,015 + 자본총계 16,039,633,585) **정확 일치**, `unit_source=
declared`(단위 추측 아님 확인). 카페24 2011Q3(B+E, `20111115000196`): 301행
복구, 항등식(20,208,992,731 = 11,758,872,932 + 8,450,119,799) **정확 일치**.
호텔신라 2005H1·SK네트웍스 2007FY(버그A, 스코프 밖)·삼성증권 2014Q1(버그C,
스코프 밖)는 예상대로 계속 0행 — 설계대로 정확히 동작.

**정량 회수율(dry-run, 250건 무작위 표본, fy2007~2014)**: **91.6%(229/250)
회수**, 회수분의 BS/IS/CF 각 ~99%·SCE 67.7% 존재. fy2007~2008 표본 일부는 회수율이
낮았는데(0/5·0/5) 원인 추적 결과 이 fy대의 일부 문서는 "부속명세서" 섹션이
존재해도 **거기엔 순수 부속 명세(예 기업어음 발행현황)만 있고 재무제표 자체가
다른 곳(SECTION 중첩, 버그A 계열)에 있는 경우**임을 확인(NH투자증권
`20080630000311` 원문 확인) — (E) 컨테이너 인식 자체의 결함이 아니라 그 문서의
실제 재무제표가 애초에 이번 스코프(버그A) 밖에 있는 것.

**전사 백필 완료(2026-09-05, 사용자 승인)**: `scripts/backfill_r69_legacy_
appendix_2026-09-05.py`(신규, rcept 단위 정밀 타겟팅 — `sync_layer2_lines`의
corp 단위 "그 corp 전체 이력 재스캔"은 이번엔 과해서 안 씀, 대신 이미 정확히 아는
대상 rcept 4,794건에만 직접 `extract_report_lines`→`store_note_lines`/
`store_report_tables`/`store_report_lines` 호출) 실행 — **대상 4,794건 중 4,263건
(88.9%) 성공, 빈 결과 504건(스코프 밖), 오류 0, 파일소실 27건**(별개 이슈, 항목1
"6건 재수집 대기"류와 같은 성격 — 미조사), **본문행 1,422,544행, 영향 corp
1,295개사**(corp 목록 `/tmp/r69_backfill_touched_corps.txt`, 세션 스크래치패드
휘발 — 재실행 시 백필 스크립트가 같은 SQL로 재생성).

이어서 `build_corp(year_min=2004)` 1,295개사 전체 실행 — **1,295/1,295 성공(실패
0), 220,887행**(7,380초). 이후 `dq_assertions.py`에서 `calendar_orphan_cq`(ERROR)
18건 신규 발견 — 전수 확인 결과 **18건 전부 이번 백필로 새로 채워진 corp**(std_v3
백필 후 달력 재동기화 누락, R63과 같은 패턴) → `calendarize_corp_v3()` 1,295개사
전체 재실행(198초, 260,711행)으로 **18→0 완전 해소**.

**최종 `dq_assertions.py` 결과(2026-09-05, R69 백필 전량 반영 후)**:
- ERROR: `statement_magnitude_impossible` 32건 **불변**(R68 시점과 정확히 동일 —
  R69와 무관한 기존 이슈, §항목2). `calendar_orphan_cq` 0(위 재동기화로 해소).
  그 외 전부 0 — **R69로 인한 신규 ERROR 0건**.
- WARN(전부 "새로 채워진 자리의 애매한 값이 안전하게 보류"로 설명되는 증가,
  기존 데이터 손상 아님): `bs_identity_gt5pct` 947→961(+14, 0.3%/4,263 신규),
  `std_v3_conflicts_unresolved` 33,632→34,369(+737), `calendar_adjacent_year_
  cq1_identical` 9→10(+1). BS 항등식 무작위 15건 표본은 **전부 정확 일치**
  확인(자산총계=부채총계+자본총계, layer3 전 경로 원문대조 완료).

**R69 트랙 완전 종료**. 코드+테스트+백필 커밋 대기(사용자 확인 후 커밋).
`v2-drop-remaining-backlog-2026-09-03`(메모리) 체크리스트 1-b 중 (E)+(D)+(B)
구현·백필·검증 완료로 갱신. 잔존: (A) SECTION-3 서브헤딩 리셋(fy2004~2006,
943건 추정)·(C) "요약" 접두(fy2014류)는 별도 트랙, 파일소실 27건은 미조사 저우선.

## R70. `fin2/extract/legacy_pre2015.py`+`fin2/extract/statement_titles.py` —
Category C fy2004~2017 레거시 헤딩 갭 잔존 (A-1)+(A-2)+(C) 수정 (2026-09-05) —
**완전 종료(구현+테스트+백필+검증)**

**배경**: R69가 스코프 밖으로 명시한 (A) SECTION-3 서브헤딩 리셋(fy2004~2006,
943건 추정)·(C) "요약" 접두(fy2014류)를 이어서 착수. 설계문서: `docs/plans/
category_c_fy2004_2006_section3_and_summary_prefix_design_2026-09-05.md`.

**원문 재현 결과, 배경(백로그) 문서의 원인규명이 부분적으로 틀렸음이 드러남**:

- **(C)**: 배경문서는 게이트가 하나(`_LEGACY_HEAD` 수식어 목록에 "요약" 없음)라고
  적었으나, 실제로는 `_LEGACY_EXCLUDE`가 "요약"을 **더 앞 단계에서 먼저 하드
  거부**해 `_LEGACY_HEAD`에 도달조차 못 함(2단계 게이트). 삼성증권
  `20140515001582`(2014 Q1) 실측 — "요약분기연결재무상태표"는 완전한 본문
  재무상태표(축약표 아님, 증권/보험 분기보고서 관행).
- **(A)**: 배경문서는 "원인 규명 완료·설계만 남음"이라 적었으나, 이미 배포된
  R13(`iter_section_span_depth_aware`, 2026-08-11)이 바로 이 문제를 고치려던
  경로였음에도 호텔신라 `20050915000066`·SK네트웍스 `20080331001324` 둘 다
  현재 코드로 여전히 0행 — 최소 3개의 서로 다른 원인이 있음이 밝혀짐:
  - **(A-1)**: `iter_section_span_depth_aware()` 자체 버그 — docstring은
    "하위표제 통과 시 TITLE 텍스트만 낸다"고 약속했지만 실제 코드엔 그 필터가
    없어 SECTION 컨테이너 자신(서브트리 전체가 통짜문자열로 뭉침)이 append돼
    헤딩판정이 깨짐.
  - **(A-2)**: `normalize_dart_section_title()`이 한글 가나다 접두를 안 벗겨,
    `SEC_SEP_FS`/`SEC_CONSOL_FS`와 정확일치하는 제목이 SECTION-3에
    "라. 재무제표"처럼 붙어있는 문서는 진입판정 자체가 실패.
  - **(A-3, 발견만 하고 이번 스코프에서 제외)**: 표 하나가 물리적으로 TR 1개뿐이고
    계정과목·금액이 각각 줄바꿈 없이 셀 하나에 통짜로 이어붙은 옛 포맷
    (호텔신라·한국팩키지 `20040528000335` 2/2 실측 확인). `table_has_amount_rows()`
    의 "셀 전체가 숫자 하나와 정확히 일치" 전제가 깨져 표 자체가 스킵된다.
    숫자를 정규식으로 잘라 재구성해야 해서 "결측"보다 나쁜 "틀린 값 적재" 위험이
    있는 별도 트랙 — **미착수, 사용자 재승인 필요**.

**코드 변경(전부 추가적, 기존 통과 경로 무변경)**:
- `fin2/extract/legacy_pre2015.py::iter_section_span_depth_aware()` —
  (A-1) SECTION 컨테이너 자신은 이제 절대 append 안 함(`if is_section:` 블록 끝에
  항상 `continue`), 하위표제 통과 시 TITLE 텍스트만 별도로 냄. (A-2) 진입판정에서
  `_PRE2015_ORDINAL_PREFIX`로 가나다 접두를 추가로 벗겨 재비교(`normalize_dart_
  section_title` 자체는 2015+ 주경로와 공유되므로 안 건드림).
- `fin2/extract/statement_titles.py::_LEGACY_EXCLUDE`/`_LEGACY_HEAD` — (C)
  "요약"이 재무제표명 바로 앞 수식어일 때만 예외 허용(부정형 lookahead), 그 외
  위치("연결재무제표 요약", "요약재무정보" 단독)는 계속 배제.

**검증**: `pytest tests/ fin2/tests/` 748 passed(무관 기존실패 1건 `test_biz_
section.py::test_lxintl_facility_table_dropped` 제외 — HEAD 상태에서도 재현
확인, 이번 변경과 무관). `test_legacy_layout_tables.py`에 기존 규약대로 안 맞는
케이스("요약연결재무상태표" 무조건 거부) 하나를 새 규약("요약"+재무제표명 앞
수식어는 허용, 그 외는 배제)에 맞춰 갱신 + 신규 케이스 추가. 40개 표본(이미
report_lines 있는 fy1999~2010 20건 + fy2011~2017 20건) 패치 전/후 byte-identical
비교로 **격리성 확인 — diff 0/40**(기존 정상 데이터 무변경).

**정량화(드라이런, fy2004~2017 전체 후보)**: fy2004~2006(A) 861건 중 파일 존재
656건 재실행 — 회수 11건(1.3%), 나머지는 (A-3)에 막혀 여전히 0행(예상대로).
fy2011~2017(C) 368건 중 파일 존재 172건 재실행 — 회수 30건(8.2%). 실제 백필은
fy2004~2017 전체 재스캔(`scripts/backfill_a1_a2_c_2026-09-05.py`, R69와 같은
"대상 전체 재시도, 성공만 저장" 패턴) — **대상 1,285건 중 218건 성공(17.0%),
130,770행, 영향 corp 114개사, 오류 0, 파일소실 32건**(별개 이슈, R69의 27건과
같은 성격).

이어서 `build_corp(year_min=1999)` 114개사 전체 실행 — **114/114 성공(실패 0),
21,964행**(785초). `dq_assertions.py`에서 `calendar_orphan_cq`(ERROR) 46건 신규
발견 — 전수 확인 결과 **46건 전부 이번 백필로 새로 채워진 114개사**(std_v3 백필
후 달력 재동기화 누락, R69와 같은 패턴) → `calendarize_corp_v3()` 114개사 전체
재실행(22,993행)으로 **46→0 완전 해소**.

**최종 `dq_assertions.py` 결과**: ERROR — `statement_magnitude_impossible` 40건
(R69 시점 32건에서 자연 증가, 전수 확인 결과 **40건 전부 이번 백필 스코프
[fy2004~2017 × 터치한 114개사] 밖의 기존 이슈** — R70과 무관, §항목2 계속
추적). `calendar_orphan_cq` 0(재동기화로 해소). 그 외 전부 0 — **R70으로 인한
신규 ERROR 0건**.

**R70 트랙 완전 종료(A-1+A-2+C만, A-3은 별도 트랙)**. `v2-drop-remaining-
backlog-2026-09-03`(메모리) 체크리스트 1-b 갱신 — (A) SECTION-3 리셋은 (A-1)
(A-2) 부분 해소(회수 11건 규모, (A-3) 통짜-셀 표가 남은 대다수를 막음), (C)
"요약" 접두 완전 해소(회수 30건). (A-3)은 정량화만 하고 미착수 — 별도 설계·
승인 필요.

## R71. `fin2/extract/legacy_pre2015.py` — (A-3) 통짜-셀 레거시 BS 표
`total_assets` 한정 안전 복구 (2026-09-05) — **완전 종료(설계+구현+테스트+
백필+검증)**

**배경**: R70이 발견만 하고 미룬 (A-3, 통짜-셀 레거시 표 — 표 하나가 물리적으로
TR 1개뿐이고 계정과목·금액이 각각 줄바꿈 없이 셀 하나에 통짜로 이어붙는 옛
포맷)을 이어서 설계·구현. fy2004~2006 무작위 60건 재조사 — **96.7%(58/60)가
이 포맷**으로, 잔존 버킷의 예외가 아니라 지배적 구조임을 확인(R70 종료 시점의
"2/2 표본" 추정보다 훨씬 큼). 설계문서: `docs/plans/category_c_a3_squished_
cell_bs_total_assets_design_2026-09-05.md`.

**핵심 아이디어(실측 검증)**: 개별 라인아이템 재구성은 라벨 셀의 항목 간 공백
폭이 불규칙(실측: "미착자재 Ⅱ.고정자산"이 한 항목으로 오분리)해 여전히
안전하지 않다고 판단, 스코프를 **`total_assets`(=`total_liabilities_and_
equity`) 한 값만**으로 좁혔다. "부채와자본총계"가 DART 서식상 항상 BS의
마지막 줄이라는 관행 + 회계항등식(자산=부채+자본)을 쓰면, 몇 번째 항목인지
셀 필요 없이 각 열의 **마지막 콤마-그룹 숫자 토큰**만 취해도 정확한 값이
나온다. 실측검증(3개사 원문대조 — 호텔신라·한국팩키지·삼표시멘트) + 인접기간
성장궤적 일치(한국팩키지 fy2004 Q1 35.3B가 H1 36.9B·Q3 37.7B 사이에 정확히
들어맞음) + 무작위 80건 라벨꼬리 게이트 재현율 100%.

**구현 중 원문 실측으로 발견한 추가 함정 2종(설계 단계에선 안 보였음, 3개
표본만으로는 안 드러났던 변종)**:
1. **기간이 섞이는 문제**(롯데에너지머티리얼즈 `20040802000167`) — 검증된
   3개사는 "계속"(P텍스트)+PGBRK 명시 마커로 이어진 **같은 기간의 연속
   페이지**들이었는데, 일부 문서는 그런 마커 없이 **서로 다른 기간의 완결된
   BS**가 바로 이어 나온다(제18기1분기/제17기/제16기 각각 자체 완결). 이어
   붙이면 다른 기간 값이 섞인다. **수정**: 마커 유무를 직접 찾지 않고, 표를
   하나씩 추가할 때마다 누적 라벨이 이미 "총계"로 끝나는지 그 자리에서 확인해
   끝나면 **즉시 확정하고 더 이상 모으지 않는** 단일 규칙으로 양쪽 다 안전하게
   처리(`detect_squished_bs_total_assets`).
2. **한 기간에 값열이 여러 개인 문제**(빙그레 `20050429000950`) — 항목수가
   적은(15~18개, 부분/차감 세부로 추정) 열과 많은(56~76개, 완전한 값) 열이
   나란히 있는데, 무조건 "첫 값열"을 취하면 부분열을 총계로 오인해 값이
   1000배 이상 벗어난다. **수정**: 열마다 토큰 개수를 세어 최댓값의 75% 이상인
   **첫(왼쪽) 열**만 채택(`_extract_squished_bs_total`, 임계 0.5는 프로텍
   `20050506000182`에서 부분열(34)이 완전열(68)의 정확히 절반이라 경계
   오탐이 남아 0.75로 상향).
3. **단위 오적용**(손오공 `20050331001512`·코데즈컴바인 `20060814001461`·
   KTcs `20060515002002`) — 로컬 단위선언이 "(단위 : )"처럼 원문 자체가
   비어있는 표에서, 문서 전체 폴백(`document_default_unit`)이 이 문서의
   **다른 곳**(요약재무정보 등)에서 찾은 단위(백만원 등)를 잘못 물려받아
   값이 10³~10⁶배 뻥튀기됐다(실측: 95.9B원이 95.9경원으로). **수정**: 이
   폴백 경로(`_pick_fallback_unit`, 정상표에서는 국지성 있는 신뢰할 근거)를
   통짜-셀 복구에는 아예 쓰지 않는다 — **로컬 선언이 없으면 폴백 없이 조용히
   포기**(드라이런 실측 656건 중 7건만 로컬 선언이 없었음 — 손실은 작고 이
   위험군 전체를 원천 차단).

**검증**: `pytest tests/ fin2/tests/` 753 passed(무관 기존실패 1건 제외).
신규 회귀테스트 5개(`fin2/tests/test_pre2015_legacy_layout.py`) — 정상 복구·
라벨꼬리 불일치 거부·비양수 값 거부·구간 내 정상표 혼재 시 포기·연결 미보유
기업 스킵. **드라이런**(fy2004~2006 후보 861건 중 파일 존재 656건) →
**649건 복구(unit_source='squished_total')**, 인접기간(`std_financials_v3`)
대비 정합성 자동검사 **97.4%(632/649)가 0.3~3.0배 밴드 안**, 잔여 17건은
전수 원문대조로 재확인 — 전부 (a) 여러 해 격차 있는 참조와 비교해 생긴 내
검증스크립트의 "가장 가까운 연도" 조잡한 매칭 오탐(예 스페코 `00136165`:
실제로는 fy2006 전체가 DB에 비어있던 자리 그 자체 — 값이 fy2005→fy2007
추세와 정확히 들어맞음), (b) 기존 DB의 손상된 참조값(신풍 `00137368`,
`statement_magnitude_impossible` 계열 기존 이슈, 항목② 참고), (c) 내부적으로
정합적인 값과 함께 나타난 그럴듯한 연결범위 변경(케이피티유 `00357607`) —
**진짜 추출 버그 0건**으로 확인.

**전사 백필**(fy2004~2017 전체 재스캔, `scripts/backfill_a1_a2_c_2026-09-05.py`
재실행): **신규 720행, 104개사** 영향(`unit_source='squished_total'`).
`build_corp(year_min=1999)` 104개사 전체(실패 0, 19,764행) +
`calendarize_corp_v3()` 104개사 전체(실패 0, 20,982행, `calendar_orphan_cq`
0 유지). **최종 dq_assertions**: R71로 인한 신규 ERROR **0건**
(`statement_magnitude_impossible` 40건 불변, 겹치는 2개사 확인 결과 전부
R71 스코프[fy2004~2017] 밖의 기존 이슈). WARN `bs_identity_gt5pct`만
+84(1,079→1,163) — **이 폴백은 `total_liabilities`/`total_equity`를 아예
안 채우므로**(§스코프 밖, 설계 §2-2) `build_corp()`의 기존 항등식 검증이 이
신규 행을 자동으로 `data_quality>=3`(격리) 처리한 것 — "완전한 값처럼
노출"이 아니라 "불완전함을 정직하게 표시"이므로 안전(`nonpositive_total_
assets` 등 DQ<3 전제 어서션에는 전혀 안 잡힘).

**R71 트랙 완전 종료**. `v2-drop-remaining-backlog-2026-09-03`(메모리)
체크리스트 1-b 최종 항목 — (A-3) 완전 종료로 갱신, 항목 1-b 전체(A-1+A-2+C+
A-3) 완료.

---

## R72. `fin2/layer3/combine.py::_reduce_conflict()` — is.revenue grand-total
override가 "수익(매출액)"류 정정 후보를 못 알아봄 (2026-09-06) — **완전 종료
(설계+구현+테스트+2개사 백필+검증)**

**배경**: `statement_magnitude_impossible` 잔존건 트리아지(항목②, 메모리
`v2-drop-remaining-backlog-2026-09-03`) 중 발견. 키네마스터(00535375)
2018H1·나이스디앤비(00606293) 2019Q3 원문대조로 확정: 원본 필링의
"영업수익"(bare grand-total 라벨)이 단위오류(×10³~10⁶, 별도 이슈 — 아래
"근본원인 구분" 참고)로 오염됐는데, 같은날/익일 정정본이 **다른 라벨**
("수익(매출액)")로 정확한 값을 재보고했다. `build_merged_lines()`의
델타패치(R2)는 셀 신원을 `(statement, basis, col_index, section_path,
label_raw)`로 판정하므로 라벨이 다르면 "같은 셀의 정정"이 아니라 "별개
후보"로 남는다(`amended=True` 플래그만 붙음) — 이 자체는 의도된 동작(라벨이
완전히 바뀌는 정정은 R2가 원래 못 따라감, R71 이전에도 알려진 한계).

**진짜 버그**는 그 다음 단계다: `_reduce_conflict()`의 "revenue grand-total
preference"(R16, 2026-08-13)가 `norm(label) in _REVENUE_TOTAL_LABELS`
(`{"매출액","영업수익","매출","순매출액"}`)로 grand 후보를 고르는데, `norm()`
(`fin2/layer3/industry_profiles.py`)이 라벨을 첫 `"("` 앞까지만 남기고
자른다(각주참조 "이익잉여금(주27)"→"이익잉여금" 제거가 원래 목적) — "수익
(매출액)"에 적용하면 의미있는 "(매출액)"까지 날아가 bare "수익"만 남고, 이건
`_REVENUE_TOTAL_LABELS`에 없다. 결과: 오염된 "영업수익"만 grand 후보 풀에
남아 `len(gvals)==1`로 그 오염값이 즉시 확정되고, 라벨이 달라 목숨을 건
정정본의 정확한 값은 애초에 경쟁조차 못 한다(R2 "정정이 이긴다" 위반).
"수익(매출액)"은 전사 최다빈도 매출 라벨(1,725개사/71,520행, R52)이라 이
결함의 잠재 노출면이 넓다.

**설계 제약(중요)**: `_REVENUE_TOTAL_LABELS`를 그냥 넓히거나(예: "수익" 추가)
`norm()`의 괄호 제거 자체를 바꾸는 **블랭킷 확장은 하지 않는다** —
2026-08-13 주석에 이미 기록된 반증 사례(같은 종류의 "그랜드토탈 우선을
일반화" 시도가 303:8로 회귀)와 같은 함정이 재현될 위험이 크다(예:
경창산업·LS 등 정당하게 "영업수익"≠"수익(매출액)"인 회사가 이미 DB에 다수
존재 — 연결/별도 다른 개념이거나 진짜 다른 계정, 실측 스캔에서 1,320행
/302개사 규모로 확인, 전부 버그가 아님). 대신 **R2 델타패치 provenance
(`amended` 플래그)가 실제로 존재할 때만** 개입한다 — 다른 라벨로 재보고된
후보가 (a) `amended=True`이고 값이 하나로 수렴하며, (b) 기존 bare grand
풀에 amended 멤버가 하나도 없을 때(=원본이 여태 안 고쳐진 채 남아있다는
신호)만 그 정정값을 확정한다. 그 외의 모든 경우(정정 관계 불명확·양쪽 다
amended·라벨이 달라도 애초에 값이 같음)는 기존 로직을 한 글자도 안 건드리고
그대로 통과한다.

**구현**: `_REVENUE_TOTAL_PAREN_RE = re.compile(r"^수익\((매출액|영업수익|매출
|순매출액)\)")`(정확히 `"수익(" + 총계라벨 + ")"`로 시작하는 라벨만 인식,
"재화의 판매로 인한 수익(매출액)"처럼 접두사 붙은 IFRS15 분해 하위라인이나
"...에 대한 매출원가" 접미사가 붙은 COGS류는 앵커(`^`) 때문에 매치 안 됨 —
이런 압축형이 애초에 `is.revenue`+`exact` 스테이지까지 오는 것 자체는
R52 가드가 이미 별도로 막고 있다). `_reduce_conflict()`의 is.revenue 분기에
"amended-paren이 bare-grand의 유일한 개정 신호일 때만" 우선권 부여 — 코드
변경 2곳, 둘 다 `fin2/layer3/combine.py`(`_REVENUE_TOTAL_PAREN_RE` 상수
신설 + `_reduce_conflict()` 개입 4줄).

**검증**: 신규 회귀테스트 4개(`fin2/tests/test_combine_curated_overrides.py`)
— 키네마스터/나이스디앤비 재현(정정값 확정) · 정정 관계 없을 때 무변화(대조군)
· bare grand 쪽에 이미 amended 멤버가 있을 때 개입 안 함(가드). `pytest
tests/ fin2/tests/` 758 passed(무관 기존실패 1건 `test_lxintl_facility_
table_dropped` 제외, 회귀 0). **2개사 스코프 재빌드**(`build_std_v3.py
--corp 00535375,00606293`): 키네마스터 revenue 5,042,936,384,000,000→
5,042,936,384(정답)·4,927,330,912,000,000→4,927,330,912, 나이스디앤비
revenue 59,247,429,676,000→59,247,429,676(정답)·39,912,392,874,000→
39,912,392,874 — 두 회사 전체 시계열(2011~2026) 재조회로 다른 기간·값
무변화 확인. `dq_assertions.py` 전수: `statement_magnitude_impossible`
40→**38**(키네마스터 2행 해소, 신규 위반 0건).

**근본원인 구분(스코프 밖, 별도 트랙)**: 이 R72는 **하류(resolve) 버그만**
고친다. 상류(왜 "영업수익" 원본 자체가 애초에 단위오염됐는가)는 두 회사가
서로 다르다 — 키네마스터는 그 rcept 하나만 단위판정이 튄 상류 추출버그로
보이고(같은 라벨의 다른 74개 필링은 전부 정상), 나이스디앤비는 원본 필링
자체가 BS/IS/CF 전체에 걸쳐 "(단위:천원)" 선언과 실제 자릿수가 안 맞는
**(가+라)류 원문 자기모순**(항목② 참고)이라 revenue 외에 total_assets도
오염돼 있는데, **그쪽은 XBRL 정정본이 재보고를 안 해 경쟁 후보 자체가 없어
이번 수정으로 해소되지 않는다**(resolve 로직 문제가 아니라 애초에 고칠 재료가
없음 — DQ격리 또는 R71 A-3류 규모/항등식 휴리스틱이 별도로 필요, 나이스디앤비
total_assets는 애초에 `statement_magnitude_impossible`의 1,000조 임계 밑이라
이 어서션에 잡힌 적도 없었다 — 완전히 별개의, 지금까지 안 보이던 결함).

**R72 트랙 완전 종료**(revenue 스코프만). `v2-drop-remaining-backlog-
2026-09-03`(메모리) 항목② 갱신 — 카테고리(사) revenue 하류버그 해소.

**★전사 백필 완료 및 회귀 0건 확정(2026-09-06, 같은 세션 이어서)**: 사용자가
`build_std_v3.py --all --year-min 1999`를 5-shard 병렬로 실행(전체
2,546개사, 1999년부터 전 기간 재빌드). `dq_assertions.py` 결과:
`statement_magnitude_impossible` 38→**41**(+3). 신규 3행 원인규명 —
corp 00198697(일진디스플 2000Q1)·00260958(케이티알파 2000H1×2행),
report_lines 직접조회로 `unit_source='pdf'` 확인 → Category C fy1999~2003
PDF복구 트랙(R69~R71) 산출물이며 XBRL시대 어휘("수익(매출액)")가 2000년
필링에 존재할 수 없어 R72 코드경로가 물리적으로 발동 불가 — **R72 회귀
아님, 확정**. 이번이 `--all --year-min 1999` 전사 규모의 첫 실행이라(기존엔
R69~R71가 스코프 한정 백필 스크립트로만 실행) 이 두 회사의 잠재된 기존
결함이 처음 드러난 것. 키네마스터·나이스디앤비는 재검증 결과 41건 목록에
없음(해소 유지). 신규 발견 2개사는 (가+라) 원문자기모순 그룹에 합류(별도
트랙, 항목②).

## R73. `fin2/layer3/unit_overrides.py` — 원문 자기모순 필링 수동 단위교정
메커니즘 신설 + 1호 사례(00138516 아남전자 FY2006) 적용 (2026-09-06)

**배경**: `statement_magnitude_impossible` 항목②의 (가+라) 그룹 — 표 자신이
인쇄한 단위 라벨이 실제 자릿수 규모와 안 맞는 케이스(코드 버그 아님, 원문
필링 자체의 표기 오류, R71/R72와 달리 자동 판정 규칙으로 일반화 불가). 지금까지
이런 건은 방치되거나(잘못된 값 노출) DQ<3 격리(값 자체를 숨김) 둘 뿐이었다 —
사용자 요청으로 **세 번째 선택지**: 사람이 원문을 직접 확인해 올바른 배수를
판정하면 그 판정을 DB에 반영해 정확한 값을 적재하고, 수동 교정임을 별도로
표시하는 메커니즘을 신설.

**설계**: `docs/plans/unit_override_self_contradictory_filings_design_2026-09-06.md`.
`report_lines`(원문 그대로 추출)는 손대지 않고, 기존 curated override들
(R16/R20/R21/R72)이 사는 `fin2/layer3/combine.py::combine_full()` 집계
단계의 마지막 순서에서 적용 — `(corp_code, fiscal_year, fiscal_period,
statement_type, concept)`(concept=DIRECT_MAP canonical, std 컬럼명 아님 —
한 필링 안에서도 개념별로 원인이 다를 수 있음, 나이스디앤비 revenue[하류
버그]/total_assets[원문모순] 분리 사례 참고) 키로 `col[std_col]`에 curated
배수(`multiplier`)를 곱한다. 각 항목은 근거(rcept_no·인쇄된 값·원문대조
일자)를 주석으로 필수 기재(★원본대조검증 원칙). 신규 컬럼
`std_financials_v3.unit_overrides`(jsonb, nullable)에 `{std_col: {concept,
declared_value, corrected_value, multiplier, note}}` 형태로 실제 적용된
셀만 기록 — SQL로 바로 조회 가능, 향후 시각화 화면 배지/각주 노출 가능.
`data_quality`(자동 항등식검증 점수)와는 별개 컬럼(의미 혼용 방지).

**마이그레이션**: `collector/db.py` MIGRATIONS
`"2026_09_std_financials_v3_unit_overrides"` — `ALTER TABLE
std_financials_v3 ADD COLUMN IF NOT EXISTS unit_overrides JSONB;`
(nullable, DEFAULT 없음 — PG11+ 즉시 완료). `collector/models.py`에
`StdFinancialV3.unit_overrides` 컬럼 추가.

**1호 사례 검증(00138516 아남전자 FY2006, bs.retained_earnings)**:
BS "1.처분전이익잉여금(결손금)" 행 **라벨 자체가** 괄호 안에 "당기순이익(손실):
제34기: 2,146,172,472원"이라고 원 단위로 명시하는데, 같은 표의 단위선언
"(단위:백만원)"을 따라 `adecimal=-6`이 적용돼 report_lines.value_won이
2,146,172,472,000,000(×10⁶ 과대)으로 저장됨. 같은 rcept(`20070330000181`)
안의 이익잉여금처분계산서(APPR)가 독립적으로 2,146,172,472(원 단위,
adecimal=0)를 재확인 — 두 표가 교차검증되는 명백한 원문 표기 오류.
`multiplier=1e-6`으로 등재(consolidated+separate 둘 다, 이 회사는
basis_fallback으로 별도=연결).

**구현/검증**: 신규 회귀테스트 5개(`fin2/tests/test_unit_overrides.py`,
순수 함수 — 매칭/비매칭/None가드/프로덕션 항목 검증). `pytest tests/
fin2/tests/` 762 passed(신규 5개 포함, 무관 기존실패 1건
`test_lxintl_facility_table_dropped` 제외, 회귀 0). 스코프 재빌드
(`build_std_v3.py --corp 00138516 --year-min 1999` — 기본 `--year-min
2015`로는 2006년이 안 걸린다는 점 확인 필요) + `calendarize_corp_v3`
동기화. **DB 반영 확인**: FY consolidated/separate 둘 다
`retained_earnings` 2,146,172,472,000,000→**2,146,172,472**로 교정,
`unit_overrides` 컬럼에 근거 기록됨. `dq_assertions.py` 전수:
`statement_magnitude_impossible` 41→**39**(00138516 2행 해소, 전수
재조회로 신규 위반 0건 확인, 나머지 39건 목록 불변).

**같은 세션 이어서 — (가+라) 그룹 나머지 원문대조 진행(2026-09-06)**:
9건+신규 2개사(00198697·00260958) 전수를 원문(SD카드 raw_report XML, EUC-KR
필요시 iconv/encoding='euc-kr')·PDF복구 트랙 산출물(unit_source='pdf')
내부정합성으로 대조. **10개사 등재 완료**(00102858 고려아연·00113207
대한전선·00117601·00138701 아세아·00143226 엠투엔·00163673·00260958
케이티알파·00366942 미코·00400121 유아이디·00487546 웰크론한텍) —
각 항목 BS 항등식(자산=부채+자본) 재성립 확인 또는 원문 라벨 자체에 실제값이
박힌 교차검증(00366942는 APPR 전기이월+반기순이익 합=BS raw÷10⁶ 정확 일치,
00400121은 각주 "(단위:원)" 명시 표+요약표 반올림 일치)으로 검증. 신규
회귀테스트 8개 추가(총 13개, `fin2/tests/test_unit_overrides.py`), `pytest
tests/ fin2/tests/` 770 passed(신규 8개 포함, 무관 기존실패 1건 제외, 회귀
0). 10개사 스코프 재빌드(`build_std_v3.py --corp ... --year-min 1999`)
+ `calendarize_corp_v3` 동기화. `dq_assertions.py` 전수:
`statement_magnitude_impossible` 39→**20**(19건 해소, 전수 재조회로 신규
위반 0건 확인).

★**등재 중 원문대조로 발견한 함정 — 00204226(소프트센 FY2022)은 (가+라)가
아니라 별개의 코드버그로 재분류**: raw XML 직접대조 결과, BS "이익잉여금
(결손금)" 행이 있는 3개년 비교표에서 report_lines가 뽑은 값(6,570,137,526)은
사실 **전기(FY2021) comparative 컬럼**이고, 진짜 당기(FY2022) 값은
**17,293,933,213**(전혀 다른 숫자, 단순 배수 관계 아님)임을 확인 — declared
unit이 실제 자릿수와 안 맞는 게 아니라 **애초에 컬럼을 잘못 골랐다**. 이
경우 unit_override로 "교정"하면 그럴듯해 보이는 오답(6,570,137,526)을
확정시켜버리므로 **등록하지 않음** — 별도의 컬럼선택 버그 트랙으로 이관
(원인: 이 표의 다년비교 레이아웃에서 col_index=0 판정 로직이 아직 안 맞는
것으로 추정, 코드 위치 미탐색). `fin2/tests/test_unit_overrides.py::
test_softcen_2022fy_is_not_registered`로 이 결론을 회귀 고정(향후 실수로
등록되는 것 방지). **같은 이유로 00378363(3S)도 미등록 유지** — raw XML에서
IS 매출액 행 후보가 여러 개(요약표·본문표) 나왔는데 그 중 어느 것이
report_lines가 실제로 뽑은 값과 일치하는지 이번 세션 내 확정 못 함(모호,
다음 세션 재조사 필요). **00163691·00198697도 미등록 유지** — PDF
추출 자체에 부호반전·계정쌍 뒤바뀜 등 단순 배수교정으로 설명 안 되는 노이즈가
있어(예: 00198697 연결 BS "자본금"↔"보통주자본금"이 부호만 반대인 동일크기
쌍으로 나타남) 원문 재조사 없이 배수만 곱하면 위험 — 원문 PDF 직접 재수집
(LegacyDartScraper) 후 재판단 필요.

**남은 (가+라) 그룹 잔여**: 위 4건(00204226·00378363·00163691·00198697,
성격이 서로 다름 — 앞 2건은 컬럼선택/모호성 버그 후보, 뒤 2건은 PDF노이즈)
+ 이번 세션 범위 밖이던 (나)`section_def`폴백 3건(00108746·00140168·
00258421)·(다)declared 경계오판정 계열 2건(00133751 세명전기·01344363
다원넥스뷰) + 재수집 트랙 4건(00122825·00124799·00125488·00133618, DART
503) + (마)임계값 오탐 후보 1건(00126380 삼성전자, 실제 초대형사라 버그
아닐 가능성 높음, 미확정) — 전부 unit_override 스코프 밖, 각자 다른
트랙(코드버그 수정·원문 재수집·정책결정)에서 별도 처리.

★**(다) 그룹 사후 재분류(2026-09-06, R74 사전조사)**: "declared 경계오판정"이라는
분류명 자체가 오분류였음이 드러남 — 01344363(다원넥스뷰)은 R74(else 분기)와 완전히
같은 메커니즘으로 이미 해소(재수정 불필요, `report_lines_sanemax_reject_
compaction_shift_design_2026-09-06.md` "후속 발견" 참고). 00133751(세명전기)은
컬럼 밀림이 아예 없는(값이 사한 상한 밑이라 거부 자체가 안 일어남) 순수 자기모순
단위 필링 — (가+라) 그룹(R73 unit_overrides 등재 후보)으로 재편입. **(다) 카테고리
소멸.**

★**(마)+"재수집 트랙 4건" 사전조사(2026-09-06, 구현 안 함)**: (마) 00126380
삼성전자는 원문대조 불필요 — `dq_assertions` 임계값을 근소하게 넘겼을 뿐(예:
total_equity 579조원, 임계 500조원) 실측상 진짜 초대형사 정상값. **버그 아님,
임계값 캘리브레이션 문제**(코드수정 아님, 필요시 향후 임계값 상향 검토).
"재수집 트랙 4건"(00122825·00124799·00125488·00133618, 원래 "DART 503"로
분류)도 원문대조 결과 **파일 자체는 전부 온전**(에러페이지 아님, 정상 크기) — 실제로는:
- 00122825·00125488·00133618 3건: 연결(consolidated) 표만 "(단위:백만원)"
  자기모순 선언(별도는 정상 원 선언) — (가+라) 그룹과 완전히 같은 패턴,
  unit_overrides 등재 후보로 재편입.
- 00124799(사조산업) FY2000(rcept `20010403000157`, `unit_source='pdf'`):
  연결 IS 전 라인이 **부호까지 반전**(매출액·매출원가 등이 전부 음수로 저장) —
  이건 단위 문제가 아니라 진짜 PDF추출 손상(Track④ 00198697 자본금↔보통주자본금
  부호반전 사례와 같은 성격) → **Track④(PDF재수집)로 재편입**. 같은 회사
  FY2001(rcept `20020401000221`)은 부호반전 없이 자기모순 단위만 있어(가+라)
  그룹 후보.
- Track④ 원래 2건(00163691·00198697)은 재확인 결과 이전 세션 판단 그대로
  유효(00198697: 자본금/보통주자본금 동일크기 부호반전쌍 재확인) — PDF 재수집
  필요, 변동 없음.

**전체 그림**: 애초 "6개 트랙"의 실제 근본원인은 사실상 2~3가지로 수렴 —
① 컬럼압축 버그(R74, 해소) ② 연결/별도 단위선언 불일치형 자기모순 필링(압도적
다수, unit_overrides 대상 — 지금까지 00133751·01344363(주1)·00122825·00125488·
00133618·00124799(FY2001) 6건 신규 확인, 기존 등재 11건과 합쳐 총 후보 다수)
③ PDF추출 자체 손상(00163691·00198697·00124799(FY2000), 재수집 필요). (주1)
01344363은 근본원인은 자기모순 단위지만 증상(컬럼밀림)은 R74로 이미 해소.

★**00258421 기산텔레콤 2006Q3 등재(2026-09-08, R84 이후 세션)** —
item2(나) 그룹(`docs/plans/section_def_fallback_wrong_sibling_unit_design_
2026-09-06.md`) 마지막 잔여. DKME(00108746)와 같은 구조: SECTION-2
"5.연결재무제표" 안 "가.요약연결재무정보"(단위:백만원)가 앞에 있고, 바로 뒤
실제 연결BS·IS 본표는 트레일러 단위선언이 공란이라 `nearest_section_
default_unit`이 앞쪽 요약표의 백만원을 잘못 물려받음. DKME(열선택버그)·
HS애드(R84로 별도 해결된 개념매핑버그)와 달리 이 건은 컬럼선택·개념매핑
둘 다 정상 — 순수 단위 문제뿐. **3중 교차검증**(원문대조 2026-09-08):
①BS "III.연결이익잉여금" 라벨 자체에 원단위 순이익 실측값 "당기
(8,101,839,101)원" 명시 ②IS "XV.연결당기순이익"(÷10⁶ 후 -8,101,839,101)이
①과 정확일치, "XIII.총당기순이익"=`"XIV.외부주주지분순이익"+"XV.연결당기
순이익"` 항등식도 ÷10⁶ 후 정확 성립 ③"가.요약연결재무정보"의 유동자산
65,047·당좌자산49,184·자본금7,059·연결이익잉여금3,493 전부와 본표÷10⁶
값이 정확 일치. rcept `20061114000692`의 BS/consolidated 74행+
IS/consolidated 79행 전부가 동일 오염이라 이 필링에서 도출되는 std_
financials_v3 canonical 15개(bs.cash/ppe/intangibles/short_term_debt/
long_term_debt/retained_earnings/trade_payables, is.cogs/sga/rd_expense/
operating_income/interest_expense/ebt/tax_expense/net_income) 전부
`multiplier=1e-6`으로 등재(참고: bs.total_assets/total_liabilities/
total_equity는 원문 "자 산 총 계" 류 글자간격 헤더를 파서가 못 걸러
report_lines에 아예 없어 NULL — 별개의 추출 갭, 이번 스코프 밖). 신규
회귀테스트 1개(`fin2/tests/test_unit_overrides.py::
test_kisan_telecom_2006q3_full_table_correction`), `pytest tests/
fin2/tests/` 859 passed(신규 1개 포함, 무관 기존실패 1건
`test_lxintl_facility_table_dropped` 제외, 회귀 0). 스코프 재빌드
(`build_std_v3.py --corp 00258421 --year-min 1999`, 205행, 에러 0) +
`calendarize_corp_v3`(212행, 에러 0). DB 반영 확인: 15개 컬럼 전부
×10⁻⁶ 교정, `unit_overrides`에 근거 기록됨. `dq_assertions.py` 전수:
`statement_magnitude_impossible` 3→**2**(기산텔레콤 소거, 잔존 2건은
이번 수정과 무관한 DKME[00108746, "결측 유지" 정책 결정된 채 값 자체는
아직 미정리]·삼성전자[00126380, 임계값 캘리브레이션 문제] — 전수
재확인으로 신규 위반 0건). 이걸로 item2(나) 3건(DKME/HS애드/기산텔레콤)
전수 원문대조·처리 완료(DKME=결측 유지, HS애드=R84 계정매퍼 수정,
기산텔레콤=본 unit_override 등재). 커밋은 사용자 확인 대기.

## R74. `_AMOUNT_SANE_MAX` 값-거부 셀이 선두절삭 컬럼압축과 충돌해
컬럼이 밀리는 버그 수정 (2026-09-06)

R73 잔여 트랙①(00204226 "컬럼선택버그 후보") 원문대조 중 정확한 메커니즘을 코드
실행으로 확정. 00204226 FY2022 연결BS는 "(단위 : 백만원)" 선언인데 실제 인쇄값은
이미 원 단위인 자기모순 필링(R73 (가+라) 그룹과 같은 클래스)이다. `adecimal=-6`이
적용되면 당기값(17,293,933,213×10⁶)이 `parser/common/amount_normalizer.py:56
_AMOUNT_SANE_MAX`(1경원, R3 — 원래 셀 병합 날조값을 거르는 가드) 상한을 넘어 **정당하게**
`None`이 된다. 그런데 `fin2/extract/report_lines.py::_emit_section_lines`(+ 쌍둥이
`fin2/extract/text.py::_emit_section`)의 3열 본문 압축 분기가 이 `None`을 "원문이
그 기간을 공시 안 함"으로 오인해 **선두절삭** — 전기값이 당기 열로, 전전기값이 전기
열로 한 칸씩 밀린다. `statement_magnitude_impossible`로 발각된 것도 이 오적재값
자체가 비정상 크기였기 때문. 00204226 한 건이 아니라 `_AMOUNT_SANE_MAX`가 실제로
발동하는 모든 표에서 구조적으로 재현되는 일반 버그(같은 표의 다른 행에서도 재현
확인, 부록A T21/T22과 같은 계열의 "값-거부→컬럼압축 오작동" 결함).

기존 §5.4(classB, 2026-08-29) `acontext_missing[i]=True` 가드와 같은 원리를
확장 — `RowData.raw_amounts[i]`(그 칸의 원문 텍스트, 항상 보존됨)가 진짜 공백류가
**아닌데** `amounts[i] is None`이면(값이 있었는데 거부된 것) 선두절삭을 멈춘다.
거부된 칸 자체는 여전히 결측으로 남는다 — "오염보다 결측을 택한다"는 R3 자신의
원칙을 압축 단계까지 일관되게 적용한 것.

- 코드: `fin2/extract/report_lines.py::_emit_section_lines`,
  `fin2/extract/text.py::_emit_section`(반드시 같이 고침, 쌍둥이 로직)
- 신규 테스트: `fin2/tests/test_report_lines.py`·`fin2/tests/test_text.py`의
  `test_softcen_2022_sanemax_reject_no_longer_shifts_columns` 각 1개
- 설계: `docs/plans/report_lines_sanemax_reject_compaction_shift_design_2026-09-06.md`
- 전수 영향범위 census: `scripts/census_sanemax_shift_2026-09-06.py`(진행 중/완료 시
  이 절 갱신 예정) — 백필은 별도 절차(runbook 3단계: 배선·백필·Gate B).

**같은 세션 후속 — cum_map(반기/분기 2단[3개월|누적] 헤더) 폴백의 같은 계열
변종도 발견·수정**: 트랙① 두 번째 대상 00378363(3S) FY2023 Q3 연결IS "매출액" —
같은 원인(자기모순 단위→`_AMOUNT_SANE_MAX` 거부)이 이번엔 cum_map 분기의 "누적컬럼이
둘 다 비면 존재값 아무거나 순서대로 채택" 폴백과 충돌해, **전기 3개월**값을 당기
누적값으로 둔갑시켰다(컬럼 밀림이 아니라 3개월/누적처럼 성격이 다른 값이 뒤바뀌는
더 위험한 변종). 같은 두 파일의 cum_map 분기에 같은 `raw_amounts` 기반 가드 적용.
신규 테스트 2개 추가(`test_3s_2023q3_sanemax_reject_cum_map_no_longer_wrong_column`),
`pytest tests/ fin2/tests/` 774 passed(무관 기존실패 1건 제외 회귀 0). else 분기
census로는 이 변종이 안 잡힌다(지문 형태가 다름) — cum_map 전용 census는 미실시.

### R74 후속 — 트랙②③④⑤ 재조사분 구현 결과 (2026-09-06, 같은 세션)

R74 커밋(`2ba5d44`) 시점에 트랙③(다원넥스뷰/세명전기)·⑤(재수집 4건)·⑥(삼성전자)은
**조사만** 하고 구현은 미뤘던 상태(위 "전체 그림" 절 참고). 이번 후속에서 실제 구현·
백필·검증까지 진행한 결과:

**트랙① 추가 발견 — Track C(PDF-only) 파서 자체 버그, 00198697 완전 해소**: 00163691·
00198697 "PDF재수집 필요" 판정을 검증하려고 `LegacyDartScraper.fetch()`로 실제 PDF를
재수집(원문 XML은 표지만 있고 재무제표 본문 자체가 없는 절단본이었음 — 로컬 캐시가
아예 다른 문서였다)해 텍스트를 직접 읽어보니, 00198697(일진디스플 2000Q1)은 "재수집"이
필요한 게 아니라 **`fin2/extract/pdf.py::_SUBTOTAL_HEADER_RE`의 진짜 버그**였다: 같은
PDF 안에서도 로마숫자가 "Ⅴ."(유니코드)와 "I."/"II."/"III."/"IV."(라틴 문자, pdfplumber가
같은 문서의 폰트 서브셋 차이로 다르게 뽑아냄)로 섞여 나오는데, 정규식이 유니코드
로마숫자만 인식해 라틴 로마숫자 헤더("I. 자본금 (22,083,500,000)")의 소계 괄호값을
음수로 오판정 — 헤더와 바로 아래 유일한 세부항목("보통주자본금")이 크기는 같고 부호만
반대인 쌍으로 저장되는 버그였다. `_SUBTOTAL_HEADER_RE`에 라틴 로마숫자(`[IVX]{1,4}\.`)
분기 추가로 수정, 회귀테스트 1개(`test_ascii_roman_numeral_subtotal_header_not_negative`,
`fin2/tests/test_pdf.py`) 추가. `recover_one()` 재실행으로 00198697 rcept
20000515000126 재적재(62행) → std_v3 재빌드(205행)+calendarize(219행) 백필 완료 —
연결 BS 자본금류 부호오염 해소 확인. **00163691은 다른 문제**(라벨과 값이 별개 줄에
분리되고 영문 대역까지 끼는 이중언어 레이아웃 — 지금 파서의 "한 줄에 라벨+숫자" 전제
자체가 안 맞음, 다줄 페어링 기능 신규 필요·미착수)로 판명, **00124799 FY2000은 현재
DB에 연결 행이 아예 0건**(원문 자체에 "제30기 별도 보고" 명시 — 이 회사가 그 해
연결재무제표를 아예 작성 안 했다는 뜻, 5개년 요약표 "연결당기순이익" 행도 제30기만
"-"로 재확인 — 파서 결함이 아니라 원문의 진짜 결측, 복구 대상 아님·완전 종결)이라
셋 다 "PDF재수집" 한 트랙으로 묶여 있던 게 실제로는 성격이 다른 세 문제였다.

**같은 세션 후속 — 00163691류 다줄 레이아웃 전수 census(2026-09-06)**: 이 시그니처
(같은 rcept·basis에서 BS 행수≤2·CF 행수≥8)로 `unit_source='pdf'` 전체를 재조회한
결과 **72개사·195건**(대부분 별도basis, 연결 3건)이 적중 — 전부 1999~2002년
필링(Category C 시기와 정확히 겹침). 신규 2개사(00101488·00102432) 원문 재수집으로
표본검증해 동일 3줄 레이아웃 재현 확인(우연 아님). `statement_magnitude_impossible`
등 금액 이상탐지로는 못 잡히는 **조용한 결측**이라 지금까지 안 드러났던 것으로 보임.
census 스크립트: `scripts/census_multiline_layout_2026-09-06.py`. 설계·구현 착수점:
`docs/plans/pdf_multiline_bilingual_layout_2026-09-06.md`(구현 미착수 — 다음 세션
시작점으로 인수인계, 오늘 트랙②(section_def) 반례 교훈을 반영해 "탐지 게이트 우선·
dry-run 먼저·열-위치 보존 원칙" 명시).

**트랙②(section_def 무관 표 단위 물림) — 안 B 구현 시도 → 즉시 반례로 반증 → 되돌림**:
`has_blank_unit_declaration()`(공란 선언 탐지기, `parser/common/amount_normalizer.py`)를
만들고 "표 자기 선언이 명시적으로 공란이면 폴백을 걸지 않고 결측으로 남긴다"를
`report_lines.py`에 배선했으나, 회귀 스위트의 `test_r67_section_default_fixes_1000x_
inflation`(00240857 바이오스마트, R67이 이미 정확히 고쳐놓은 사례)이 즉시 깨졌다 —
"표 자기 선언 공란"이라는 증상만으로는 00108746류(폴백이 무관한 표 단위를 잘못
물림)와 00240857류(폴백이 같은 섹션의 진짜 정답 선언을 올바르게 찾음)를 구분 못 한다.
설계 문서가 예견했던 "1차 구현→반례로 반증→재설계" 그대로 재현돼, **코드는 완전히
되돌렸다**(`has_blank_unit_declaration()` 탐지기 자체와 그 테스트 3개만 남김,
`fin2/extract/text.py::own_declaration_is_blank`와 그 호출부는 삭제). 00108746·
00140168·00258421 셋 다 **여전히 미해결**(`statement_magnitude_impossible`에 계속
남아 있음). 상세: `docs/plans/section_def_fallback_wrong_sibling_unit_design_
2026-09-06.md`.

**트랙③(다) 카테고리 소멸 후속 + 트랙④(가+라) 신규 등재**: (다) 그룹 사후 재분류에서
확정한 대로 01344363(다원넥스뷰)은 위 트랙① 버그(00204226와 같은 else 분기 메커니즘)로
증상은 해소됐지만, 근본원인인 자기모순 단위 자체는 별도로 `unit_overrides` 등록이
필요했다 — 등록 완료. 00133751(세명전기)·00122825·00125488·00133618(옛 "DART503재수집"
그룹 중 재분류된 3건)·00124799 FY2001(재분류)도 원문(report_lines 라벨 내부 실측값 +
BS/IS/CF 교차검증, 상세 근거는 `fin2/layer3/unit_overrides.py` 각 항목 주석)으로
확인 후 `unit_overrides`에 등록(총 6개사, `is.`/`bs.`/`cf.` 개념 다수 — 00133751은
IS·CF 전체가 자기모순이라 12개 개념을 별도+연결 양쪽에 등록). 00124799 FY2001은
등록 과정에서 `is.revenue`/`is.cogs`가 실제로는 계정매퍼가 엉뚱한 세부항목(수수료수익·
기타매출원가 한 줄)을 골라온 **별개의 매핑 버그**임을 발견해 그 두 개념은 등록하지
않고 매핑이 맞다고 확인된 개념만 등록했다(짐작으로 등록했으면 오답을 확정시켰을
사례 — 이번 세션의 두 번째 "등록 직전 원문대조로 오답 차단" 사례, 첫 번째는 R73의
00204226 소프트센).

신규 회귀테스트: `fin2/tests/test_pdf.py`(+1), `fin2/tests/test_unit_tokens.py`(+3,
`has_blank_unit_declaration` 전용), `pytest fin2/tests/` 618 중 617 pass(무관 기존
실패 `test_lxintl_facility_table_dropped` 1건 제외 회귀 0 — `tests/`는 NAS 전수스캔이
느려 스코프 밖). 6개사 재빌드(`build_std_v3.py --corp ...`)+calendarize, 00198697
1개사 추가 재빌드. `statement_magnitude_impossible` **16 → 5**(00198697 해소분 포함
11건 해소). 잔여 5건: 00108746·00140168·00258421(트랙② 미해결, 위 참고)·00126380
(임계값 오탐, 버그 아님, 종결)·00163691(트랙①-b 다줄 레이아웃, 신규 기능 필요,
미착수). 커밋은 사용자 확인 대기, origin push 미완.

---

## R75. `fin2/extract/pdf.py` — Track C(PDF-only) "3줄 이중언어" 레이아웃
지원 신규 구현 (2026-09-06)

R74 후속에서 인수인계한 `docs/plans/pdf_multiline_bilingual_layout_2026-09-06.md`
(72개사·195건, 1999~2002년대, BS/IS 표가 "한글라벨/숫자단독/영문번역" 3줄 1항목이라
`_iter_data_lines()`의 "라벨+숫자 같은 줄" 전제가 안 맞아 거의 통째로 유실되던 문제)
구현 착수. **설계문서 §구현방향 그대로**: 게이트로 판별된 리전에서만 별도 파싱을
태우고(대다수 정상 필링은 기존 단일줄 경로 무영향), 열 위치를 보존한 채 파싱한다
(대시="-"는 결측 None으로 그 자리를 유지, 왼쪽으로 채우지 않음 — R74 컬럼압축 함정과
같은 원칙).

신규 함수: `_looks_multiline_bilingual()`(게이트 — "한글단독행(진짜 숫자 없음) 다음이
숫자단독행" 비율 ≥60%·후보 ≥3건일 때만 3줄 모드), `_iter_data_lines_multiline()`
(페어링+파싱), `_parse_numline_tokens()`(헤더행은 모든 토큰 괄호 벗김·대시는 열보존
None). BS/IS만 대상(CF는 2단-페이지 별개 레이아웃이라 범위 밖, 설계문서 §CF).

**실측 dry-run(00163691 rcept 20010515000229, 원문 재수집 — DB 미기록) 중 설계문서에
없던 변종 3개 추가 발견·수정**(00101488 rcept 20010814000979로 재현):

1. **라벨+짧은영문+숫자가 한 줄에 붙음** — "자 산 총 계 (Total Assets) 120,860,966,620…"
   (설계문서는 항상 라벨/숫자/영문이 물리적으로 분리된다고 가정했으나, 영문이 짧으면
   숫자까지 같은 줄에 온다). `normalize_account_name()`은 `(net)`류 짧은 약어 괄호만
   지우고 이런 전체 문구 괄호는 안 지워서 `mapper.map()`이 "자산총계 (Total Assets)"를
   못 알아봐 **자산총계가 통째로 결측**됐다. 한글이 없는 trailing 괄호를 라벨에서
   떼는 `_strip_inline_english_gloss()` 신설, `_parse_single_line()`(기존 단일줄
   공용 함수)과 라벨-숫자줄 페어링 양쪽에 적용.
2. **긴 영문 번역이 2줄로 줄바꿈되며 진짜 숫자가 그 첫 영문줄 끝에 섞여 나옴** —
   "(Appropriated Retained Earnings 622,000,000\nfor Overseas Market Development)".
   앞쪽 영문 단어 토큰들을 대시와 똑같이 결측(None)으로 취급하면 뒤 실측값이 col0이
   아닌 다른 열로 밀린다(대시=열 보존해야 할 진짜 결측 / 잡음=열 자체가 없는 것 —
   둘을 같은 None으로 섞으면 안 됨). `_parse_numline_tokens()`에서 대시가 아니면서
   숫자도 아닌 토큰은 **자리를 만들지 않고 통째로 버리도록** 수정.
3. **순수 섹션헤더가 pdfplumber 오독(추정: 밑줄/구분선)으로 "0" 짜리 가짜 숫자줄을
   달고 나옴** — "부 채\n0\n(Liabilities)"("자산\n(Assets)"처럼 원래 숫자 없는
   섹션헤더인데 이 문서에선 예외적으로 숫자줄이 붙음). 이 라벨이 `bs.total_liabilities`
   에 매핑되면 진짜 "부채총계" 값과 경합하는 가짜 0원 후보가 생겨 하류 결합로직(Layer3
   `_reduce_conflict()`)에 불필요한 위험을 얹는다 — 모든 기간이 문자 그대로 0이면
   결측과 동일하게 스킵(R3 "오염보다 결측" 원칙의 연장).

같은 각주참조("(주석 2, 3)")·항목번호 접두어("(1)", "2.")의 작은 숫자가 "이 줄에
진짜 데이터 숫자가 있다"고 3줄 게이트/페어링 판정을 오도하는 문제도 원문대조로
발견해 `_has_real_number()`에서 두 패턴 모두 선제거 후 판정하도록 처리.

- 코드: `fin2/extract/pdf.py`(`_looks_multiline_bilingual`, `_iter_data_lines_
  multiline`, `_parse_numline_tokens`, `_parse_single_line`, `_has_real_number`,
  `_strip_inline_english_gloss`)
- 신규 테스트: `fin2/tests/test_pdf.py` +9(3줄 게이트·헤더다중값·각주참조 페어링·
  대시 열보존·푸터잡음/순수헤더 스킵·라벨+영문+숫자 동일줄·줄바꿈영문 숫자열보존·
  전부-0 헤더행 드롭·end-to-end 항등식), `pytest fin2/tests/ tests/` 787 passed
  (무관 기존실패 `test_lxintl_facility_table_dropped` 1건 제외 회귀 0).
- dry-run 원문검증(00163691·00101488, `LegacyDartScraper.fetch()`로 실시간 재수집,
  **DB에는 아직 미기록**): 두 필링 모두 별도/연결 기준 `자산총계=부채총계+자본총계`
  항등식 정확히 성립. 00163691의 `bs.current_assets`(971,735,843,010원)는 설계문서
  실측 인용값과 정확히 일치.
- **미해결로 확인된 별개 결함(이번 트랙 범위 밖, 참고용)**: 00102432(rcept
  20000512000074)는 BS/IS 앵커 자체가 안 잡힘 — 원문이 "제 34-1 분기"(정정회차
  포함) 형식 기간표기를 쓰는데 `_find_anchors`의 `_PERIOD_MARK_RE`(`제\s*\d+\s*기`)가
  "34-1"처럼 숫자 뒤에 비숫자가 낀 표기를 인식 못 함. 3줄 레이아웃과 무관한 기존
  앵커탐지 갭 — 별도 트랙.
- **아직 안 한 것(다음 단계)**: 195건(72개사) 소급 백필(`collector/pdf_lines_
  sync.py::sync_pdf_recovery()` 재실행 또는 표본 확대 dry-run 먼저) + std_v3
  재빌드+calendarize + Gate B/dq_assertions 전후 비교(runbook 체크리스트 B·C).
  이 로더는 daily(`collect_new.py`)에 안 걸려 있음(수동 백필 스크립트,
  `scripts/run_pdf_recovery_2026-09-03.py`류)이 확인돼 체크리스트 A(데일리 배선)는
  해당 없음 — B(소급 백필)만 남음. 커밋·백필 모두 사용자 확인 대기.

**같은 세션 후속 — 표본 확대 dry-run(72개사, 회사당 1건, DB 미기록) 결과 및 신규
발견 2종**: `scripts/dryrun_multiline_sample_2026-09-06.py`로 census 대상 72개사
전부에서 1건씩 실시간 재수집+파싱(예외 0건·0건 필링 0건 — 모든 필링에서 최소한
뭔가는 추출됨, 이전 "거의 통째로 유실"에서 크게 개선). 단, 회계항등식(자산=부채+자본)
검사는 **35건 통과 / 26건 실패 / 23건은 A·L·E 중 하나 이상 결측이라 검사 자체가
불가**. 실패 26건을 원문(PDF 페이지 이미지 직접 렌더링·육안대조)까지 파고들어
분류한 결과:

1. **"자본총계"↔"부채와자본총계" 값-라벨 도치(5건, 근본원인 확정)**: pdfplumber의
   `extract_text()`가 이 두 헤드라인 합계 행에서만 **값이 자기 라벨보다 먼저,
   그것도 한 행 밀려서** 나온다 — 실측(00134565 rcept 20010331000135, 페이지
   이미지 직접 확인): 원문은 "자본총계=37,627,936,640" "부채와자본총계=
   57,440,835,448"인데, 추출텍스트는 "...(전행 라벨 continuation)"익"\n37,627,936,640…
   \n자본총계\n57,440,835,448…\n부채와자본총계\n(숫자 없음)" 순으로 나와 **"자본총계"
   라벨이 "부채와자본총계"의 값을 가로채고, "부채와자본총계"는 빈손이 된다**. 4개사
   전부(00134565·00135050·00152783·00159573) 같은 패턴 재현 확인 — 페이지 넘김과
   무관(00134565는 페이지 안 끊김에도 재현), 이 두 행 전용의 텍스트-추출 순서 결함.
   **이번 세션엔 수정 안 함**(내 3줄 파싱 로직이 아니라 `_read_pdf_text()`가 넘겨주는
   원시 텍스트 자체가 이미 도치돼 있어, 지금의 "라벨 다음 숫자" 전제를 이 두 행에서만
   "숫자 다음 라벨"로 뒤집는 별도 처리가 필요 — 설계·검증 없이 손대면 다른 정상 문서를
   깰 위험).
2. **"부채와자본총계" 대신 괄호 전체음수 포맷이 부채·자본 쪽에만 걸림(2건)**: 00113526
   실측 — "자본총계(Total Stockholders' Equity) (3,675,008,885,502)"처럼 **부채·자본
   섹션 전체가 괄호(=음수 아님, 서식)로 찍히는데 자산 섹션은 정상**. 기존
   `_fix_paren_formatted_bs()`는 "BS 전체(자산·부채·자본 셋 다) 음수"만 뒤집도록
   설계돼 있어(안전장치) 이 "한쪽만 괄호" 변종은 안 걸린다 — 별도 일반화 필요, 미착수.
3. 나머지(missing 9건·기타 4건·근접오차<10% 6건)는 표본이 다양해 개별 원문대조가
   더 필요 — 트리아지만 하고 미착수(missing 9건 중 상당수는 "총계" 라벨 자체가
   `_region_has_anchor_labels`는 통과했지만 실제로는 그 basis의 표가 부분적으로만
   존재하는 것으로 보이는 사례들이 섞여 있어 근본원인이 하나가 아닐 가능성).

**결론(1차)**: 3줄 레이아웃 구현으로 "거의 전부 유실"은 확실히 해소됐으나, 헤드라인
3종 합계(자산총계/부채총계/자본총계)의 **정확도**는 이 표본에서 절반을 조금 넘는
수준(35/61, 확인 불가 23건 제외)에 그친다. 사용자 결정: 원인 1·2(체계적으로 확정된
7건)만 먼저 고치고, 나머지 15건은 다음 세션으로 미룬다.

**★같은 세션 후속 — 원인 1·2 수정 완료**:

1. **원인①의 진짜 근본원인 재정정**: 처음엔 "pdfplumber 텍스트 순서가 이 두 행에서만
   도치된다"고 봤으나, 00134565 페이지 이미지 직접 대조로 재확인한 결과 실제로는
   **한글 라벨이 숫자줄을 사이에 두고 단어 중간에서 줄바꿈**되는 경우였다("1.투자
   유가증권 평가이" → [숫자] → "익", 영문 줄바꿈과 같은 부류지만 한글이라
   `_HANGUL_RE` 필터를 못 피해간다). 잔여 조각("익")이 새 라벨 후보로 오인돼 다음
   숫자줄(원래 "자본총계"의 값)을 가로채고, 그 여파로 "자본총계"→"부채와자본총계"까지
   한 칸씩 밀린다. **수정 방식**: 라벨 파싱을 역추적하는 대신, 같은 문서에서 이미
   올바르게 뽑힌 자산총계·부채총계로 항등식(자본=자산-부채) 역산해 복원하는 신규
   함수 `_fix_swapped_grand_total_equity()` 추가(`_fix_paren_formatted_bs()`와 같은
   "항등식으로 게이트" 원칙 — bs.total_equity==bs.total_assets 인 특징적 증상으로
   판별, 부채=0인 경우는 판별 불가라 미발동).
2. **원인②+거울상 변종**: `_fix_paren_formatted_bs()`의 항등식 게이트를 "자산·부채·
   자본 셋 다 음수"뿐 아니라 "자산만 양수·부채와자본 둘 다 음수"(00113526) **및
   그 거울상인 "자산만 음수·부채와자본 둘 다 양수"(00160047, 표본 확대 검증 중
   추가 발견)** 까지 확장. 전자는 헤드라인 두 총계(부채·자본)만, 후자는 헤드라인
   자산총계 하나만 반전 — 하위 세부계정까지 같은 문제인지는 미검증이라 안 건드림.

**검증**: 목표 7건(00134565·00135050·00139719·00152783·00159573·00113526·00160047,
별도+연결 전부) 각 basis 후보값을 직접 덤프해 항등식이 정확히 성립함을 확인(00113526
consolidated·00160047 consolidated는 원래 목록에 없었는데도 같은 일반화된 코드로
같이 해소됨). 신규 회귀테스트는 추가 안 함(항등식 역산 로직이라 합성 fixture보다
실측 사례 재현이 더 신뢰도 높음 — 위 dry-run 스크립트가 그 역할). `pytest fin2/tests/
tests/` 787 passed(무관 기존실패 1건 제외, 회귀 0).

**표본 72개사 재검증(개선된 dry-run — 후보값이 여러 개인 canonical 은 "조합 중 항등식이
성립하는 조합이 존재하는가"로 판정, 기존 "마지막 후보가 맞다"는 가정이 00148276에서
반증돼 폐기)**: identity_ok **42** / identity_fail **10**(원래 카탈로그의 missing·
근접오차·기타 부류와 대부분 일치 — 새 회귀 없음) / no_identity_data 9. 예외 0·0건필링
0 그대로 유지. `scripts/dryrun_multiline_sample_2026-09-06.py`(DB 미기록, 재실행 가능)
— 단, 이 스크립트의 "조합 중 존재" 판정은 Layer3 `_reduce_conflict()` 가 실제로 그
조합을 고를지까지 보장하진 않는다(원리적 도달가능성만 확인, 별개 검증 필요로 기록).

**남은 것**: identity_fail 10건(missing류·근접오차류·기타)은 원인 다양, 미착수 —
다음 세션 후보. 195건(72개사) 소급 백필 + std_v3 재빌드+calendarize + Gate B/dq_
assertions 전후 비교는 전부 미착수, **사용자 확인 대기**(커밋도 미완).

**★같은 세션 후속 — 195건 소급 백필 완료(2026-09-06)**: `scripts/backfill_pdf_
multiline_195_2026-09-06.py` 신설·실행(R76 조사 직후, `collector/pdf_lines_sync.
py::recover_one()` 재사용 — 이미 report_lines 가 존재하는 rcept 도 재처리하도록
census 목록을 직접 순회, `sync_pdf_recovery()`의 기본 `NOT EXISTS` 후보 SQL은
이번 대상엔 안 맞아 우회). 195/195건 전부 PDF 재수집 성공(recovered_pdf=195,
errors=0), report_lines 21,269행 적재. 영향받는 72개사 전부 `build_corp(year_min=
1999)`+`calendarize_corp_v3()` 재실행(오류 0).

항등식(자산총계=부채총계+자본총계) before/after 전이표(72개사, fy1999~2003
스코프 PK조인):

| before → after | 건수 |
|---|---|
| ok → ok | 974 |
| missing → missing | 484 |
| fail → fail | 122 |
| **missing → ok** | **94** |
| **absent → ok** | **21** |
| missing → fail | 11 |
| absent → missing | 4 |

**회귀(이전 ok였던 키가 after에 ok 아님) 0건.** 순개선 115건(이전엔 아예 값이
없어 검사 자체가 불가하던 것 중 94건 + std_v3에 없던 21건이 새로 항등식까지
정확히 성립). 잔여 미해결 133건(fail→fail 122 + missing→fail 11)은 R75 본문의
"자본총계↔부채와자본총계 도치"류와 다른, 아직 트리아지 안 된 원인들 — 다음
세션 후보.

`scripts/dq_assertions.py` 전후 비교(DB 전체 스코프): `statement_magnitude_
impossible`(ERROR) 5→**4**(개선, 회귀 아님), `bs_identity_gt5pct`(WARN) 1,605→
1,613(+8, 위 missing→fail 11건과 정합), `std_v3_conflicts_unresolved`(WARN)
39,226→39,292(+66, 신규 21,269행 적재분의 정상적 conflict 노이즈). ERROR 레벨
회귀 0건. 커밋은 사용자 확인 대기(`docs/PARSING_RULES.md` 이 절 + 신규 스크립트
`scripts/backfill_pdf_multiline_195_2026-09-06.py`).

---

## R76. OpenDART `document.xml` 아카이브 자체의 2001년 접수분 인코딩 손상
— T5 재정정("자동감지로 해결됨"은 착시), 사실상 전수, fail_a/b 양쪽 다 못 잡음
(2026-09-06)

R75 표본검증(00111218 등) 원문대조 중, 사용자가 "총계가 옆으로 있는데 그 아래 값을
취한다"고 지적한 필링을 DART 실제 뷰어에서 열어보다가 **레이아웃 문제와는 별개의,
훨씬 근본적인 문제**를 발견했다.

**증상**: 로컬 `raw_report`의 해당 XML(`00111218` `20010814000291`)에 재무제표
숫자(`24,164,567` 등)가 **UTF-8/CP949 어느 쪽으로 디코딩해도 존재하지 않음** — 파일
바이트 자체에 `U+FFFD`(UTF-8 바이트열 `EF BF BD`)가 리터럴로 박혀 있어, 어느 인코딩을
가정해도 복구가 안 된다(T5가 가정하는 "실제 EUC-KR인데 UTF-8로 잘못 디코딩" — 즉
**디코딩 시점에 자동감지로 고칠 수 있는** 문제 — 와는 다르다. 이건 파일에 저장되기
**전에 이미 파괴**된, 로컬 사본만으론 원리적으로 복구 불가능한 손상이다).

**원인 규명(3단 대조로 확정, 짐작 아님)**:

1. **DART 자체 웹뷰어는 멀쩡하다** — `dart.fss.or.kr`의 내부 API
   (`report/viewer.do?rcpNo=...&dcmNo=...&eleId=...&offset=...&length=...&dtd=...`,
   브라우저 network 로그로 실제 요청 URL 확보 후 동일 파라미터로 재요청)를 직접
   fetch 하면 `U+FFFD` **0건**, `자산총계`·`24,164,567` 모두 정상 포함.
2. **`collector/downloader.py`는 결백** — ZIP에서 파일을 꺼내 저장하는 경로
   (`_download_one()`, 561~565줄)는 `shutil.copyfileobj(src, dst)` 순수 바이트
   복사뿐, 디코딩·인코딩을 전혀 거치지 않는다. 우리 파이프라인이 만들어낼 수 있는
   손상이 아니다.
3. **OpenDART `document.xml` API 자체가 손상된 바이트를 서빙한다** — `.env`의
   `OPENDART_API_KEY`로 이 필링을 지금 다시 호출해 받은 ZIP의 내용물과 로컬
   `raw_report` 사본의 MD5가 **완전히 동일**(`0861f16ab...`). 즉 재다운로드는
   복구책이 아니다 — 같은 API를 몇 번을 다시 불러도 항상 이 손상된 바이트가 온다.
   DART가 2001년치 필링을 OpenDART 아카이브용으로 변환할 때 이미 이렇게 저장해둔
   것으로 보인다(원본 XML 프롤로그가 `encoding="utf-8"`이라 선언하지만 실제 내용은
   EUC-KR — DART **자신의** 변환 과정에서 그 잘못된 선언을 그대로 믿고 깨진 것으로
   추정, 검증은 안 됨).

**규모(전수 실측, `find`+바이트 스캔, 디코딩 없이 `\xef\xbf\xbd` 바이트열 직접 카운트)**:

- R75 census 195건(72개사) 중 **149건(76%) 손상**, 그중 28건은 숫자 텍스트 완전
  전멸. 손상 vs 정상이 **rcept_no 접수연도로 완벽하게 갈림**(2000년 접수 20건 전부
  정상 / 2001년 접수 149건 전부 손상 / 2002년 접수 26건 전부 정상) — 우연이 아니라
  DART 쪽의 **2001년치 배치 전체**에 걸린 결함임을 시사.
- 이 가설을 `raw_report` 전체(282,710개 XML)로 검증: 파일명이 `2001*.xml`인 것
  **3,625건 중 3,624건(99.97%) 손상**. 유일한 예외는 삼성전자 2000 사업보고서
  (`00126380` `20010331000297`, 874KB). 손상 비율은 파일당 5.0%~69.6%(중앙값
  12.9%), 3,625개 파일 합계 13억 바이트 중 **약 1.56억 바이트(약 12%)가 `U+FFFD`**.
  이 census(R75)가 잡아낸 195건은 이 훨씬 큰 문제의 부분집합일 뿐이며, 영향받는
  회사 수는 195건/72개사보다 넓을 것(2001년에 무엇이든 접수한 모든 상장사가 후보).

**왜 Gate B(`fail_a`/`fail_b`)도, `dq_assertions`(`statement_magnitude_impossible`)도
못 잡았나 — 구조적 이유, 짐작 아니라 코드+실측 확인**:

- `dq_assertions.py::statement_magnitude_impossible`은 **절대 크기 임계**(자산
  >1,000조·자본/이익잉여금>500조·매출>400조)만 본다 — 이 손상은 대개 값의 자릿수
  자체는 정상 범위라 걸리지 않는다.
- `fin2/audit/face_audit.py` 1329~1330줄의 자체 설계 주석: `fail_a` = **Track
  A(XBRL ADECIMAL, 독립 태그값과의 대조) 불일치 = 확정 버그**(메인뷰 차단),
  `fail_b` = Track B(텍스트 리더 휴리스틱) 불일치 = **REVIEW**(비차단, false-fail
  가능 취급). `read_report_face_xbrl()`은 문서에 XBRL(ACODE+ACONTEXT) 태그가
  없으면 **빈 리스트를 반환**(730줄 docstring)한다 — 한국 XBRL 의무화는 2011년
  이후라 **2001년 K-GAAP 필링은 원리적으로 Track A 대상이 될 수 없다.** 즉 이
  손상이 아무리 심해도 최고등급 차단 게이트(`fail_a`)에는 애초에 도달할 경로가
  없다.
- `face_audit` 테이블 실측 대조(위 손상 확정 회사 6곳의 2000~2001년 행 전수 조회)
  — **`n_fail` 이 0이 아닌 행이 단 하나도 없다.** 전부 `pass`(Track B 휴리스틱이
  주 파서와 "합의"했다는 뜻 — 그런데 Track B도 같은 손상된 원문을 다시 읽으므로,
  둘 다 같은 손상을 보고 같은 틀린 결론에 동의하면 그게 `pass`로 찍힌다. 즉
  self-consistency 검증은 **원본 자체가 오염된 경우 원리적으로 무력**하다) 아니면
  `pending`(대조할 근거 자체가 없어 판정 보류). `00111218` H1 2001(이 문제의
  발단이 된 그 필링)은 `face_audit`에 **행 자체가 없다** — 애초에 감사 시도조차
  안 됨. 결론: 이 결함군은 **fail_a로도 fail_b로도 절대 뜨지 않는 사각지대**다 —
  놓친 게 아니라, 지금 감사 아키텍처가 원리적으로 볼 수 없는 지점이다.

**복구 경로는 이미 코드에 있다, 다만 이 트리거 조건에서 안 걸린다** —
`collector/legacy_downloader.py::LegacyDartScraper`가 정확히 그 `report/viewer.do`
스크래핑 폴백을 이미 갖고 있다. 다만 지금은 OpenDART가 `[014]`(문서 없음) 오류를
낼 때만 발동한다(`collector/downloader.py` 483~500줄). 이번처럼 OpenDART가
`200 OK`+정상 ZIP을 반환했지만 내용물이 인코딩 손상인 경우는 **아무것도 감지하지
못하고 그대로 저장**된다 — 트리거 조건이 "다운로드 실패"만 볼 뿐 "다운로드는
성공했지만 내용이 깨졌다"는 못 본다.

- **아직 안 한 것(다음 단계, 사용자 결정 대기)**: ①`std_v3`에 이미 이 손상이 얼마나
  스며들었는지 스코프 산정(회사 수·건수, XML 경로로 정상 파싱된 것처럼 보이는
  "조용한 오염" 포함) ②`report/viewer.do` 복구 경로가 표본에서 실제로 안전하게
  동작하는지 검증(다운로드 코드에 손상 감지+폴백 배선은 이번 트랙 밖, 구현 전
  별도 설계 필요) ③커밋 없음 — 이 섹션 자체가 진단 기록.
- 근거: 브라우저 network 로그(2026-09-06 세션) + `.env` `OPENDART_API_KEY` 재요청
  MD5 대조 + `fin2/audit/face_audit.py:717-746,1329-1366` + `face_audit` 테이블
  실측 조회 + `find /Volumes/dart_data/raw_report` 전수 바이트 스캔.

---

## R77. `fin2/extract/pdf.py::_PERIOD_MARK_RE` — 정정회차·당기/전기 표기가 낀
"제 N 기" 변형을 못 잡아 그 basis 의 BS/IS 앵커 자체가 통째로 안 잡힘
(195건 백필 잔여결측 원문대조 중 발견, 2026-09-06)

R75/R76 195건 백필 후에도 남은 잔여 결측 76건(별도 아티팩트 "195건 백필 잔여결측")을
사용자가 하나씩 DART 원문과 대조하다가, "web 화면에는 표에 값이 정상적으로 들어
있다"는 제보로 발견. 근본원인은 R75가 이미 각주로 남겨뒀던 "제 34-1 분기" 앵커
갭(§R75 "미해결로 확인된 별개 결함")과 **같은 계열**이지만 실제로는 변형이 최소
2종 있었다:

1. **하이픈 부기(副記) 표기**: `00102432`(계룡건설산업) rcept `20000512000074` —
   "제 34-1 분기 2000. 03. 31 현재"(정정회차 포함). 숫자 뒤 "-1"이 낀다.
2. **괄호 당기/전기 표기**: `00115694`(DB증권) rcept `20010214000346` — "제19(당)기
   분기 2000년 12월 31일 현재"/"제18(전)기 분기 1999년 12월 31일 현재". 숫자와
   "기" 사이에 "(당)"/"(전)" 괄호가 낀다.

옛 `_PERIOD_MARK_RE = r"제\s*\d+\s*기"`는 숫자 바로 뒤에 "기"가 와야 해서 둘 다
놓친다. `_find_anchors()`(313줄)는 statement 제목을 찾아도 그 직후 ~50자 안에
이 기간마커가 없으면 "목차·주석 속 언급"으로 보고 **앵커 후보 자체를 버린다**
(320~322줄 주석 그대로) — 그러면 그 basis 의 BS/IS 리전이 통째로 안 잡혀 표가
아무리 단순·정상이어도 A/L/E 전부 결측이 된다. `00115694`는 특히 연결(consolidated)
쪽은 다른 "제 18 기"(괄호 없음) 형식 표가 하나 더 있어 그쪽만 정상 추출되고,
별도(separate)만 이 갭에 걸려 결측이었다 — **부채총계·자본총계는 다른 필링의
델타패치로 이미 채워져 있는데 자산총계만 결측**인 비대칭도 이 비대칭 원인으로
설명됨(같은 (corp,fy,period,basis) 키를 다른 rcept 가 이미 부분적으로 채워둔
상태에서, 이 rcept 만 실패해 그 필드만 못 덮어씀).

**수정**: `_PERIOD_MARK_RE`에 두 변형 모두 수용 — `r"제\s*\d+(?:-\d+)?\s*(?:\([^)]
{1,4}\)\s*)?(?:기|분기)"`(하이픈 접미사 선택적 + 괄호 짧은 remark 선택적, 순서
무관하게 둘 다 있어도 됨). 두 필링 모두 실측 재현: `00102432`는 이후 자산총계=
237,213,104,850/부채총계=139,574,641,275/자본총계=97,638,463,575(항등식 성립,
DART 웹뷰어 원문과 일치) 정상 추출, `00115694` separate 는 자산총계=316,770,277,742
/부채총계=168,222,750,184/자본총계=148,547,527,558(항등식 성립) 정상 추출 —
둘 다 std_v3 반영 완료.

- 코드: `fin2/extract/pdf.py:47`(`_PERIOD_MARK_RE`)
- 신규 테스트 2개(`fin2/tests/test_pdf.py`): `test_anchor_period_mark_accepts_
  hyphenated_subperiod`, `test_anchor_period_mark_accepts_parenthetical_current_
  prior_remark`. `pytest fin2/tests/ tests/` 789 passed(무관 기존실패
  `test_lxintl_facility_table_dropped` 1건 제외, 회귀 0).
- 백필: `scripts/backfill_pdf_missing76_2026-09-06.py` 신설 — 195건 백필 후에도
  결측이던 76건(32개사) 전체에 재적용(00102432·00115694는 발견 직후 수동으로
  이미 반영, 나머지 75건은 이 스크립트로). 75/75건 전부 PDF 재수집 성공(에러 0),
  report_lines 5,816행 추가. 영향받는 31개사 재빌드(오류 0). 항등식 전이표:
  ok→ok 495 / missing→missing 155 / fail→fail 56 / **missing→ok 17** /
  **absent→ok 7** / missing→fail 3 / absent→fail 1 — **회귀 0건**, 순개선 24건.
  `dq_assertions.py` 전후 비교: ERROR 레벨 무변화(`statement_magnitude_impossible`
  4 그대로), WARN 두 개 소폭 증가(`bs_identity_gt5pct` +1, `std_v3_conflicts_
  unresolved` +8, 둘 다 신규 반영분의 정상적 노이즈). 잔여 결측은 139건/76건/32개사
  → **106건/55건/19개사**로 축소. 남은 것은 R77 두 변형과 다른 원인(앵커 자체가
  아예 없거나 다른 표 구조) — 다음 세션 후보, 아티팩트 "195건 백필 잔여결측"
  갱신본에서 계속 원문대조 중.

---

## R78. `fin2/extract/pdf.py` — 라벨이 숫자를 사이에 두고 줄바꿈되는 세 번째
변형 → pdfplumber `extract_tables()` 표-격자 폴백 신설(사용자 제안, 2026-09-06)

R77 잔여 55건을 사용자가 계속 원문대조하다가 `00116268`(동성제약)에서 발견 — 자산
총계/부채총계/자본총계뿐 아니라 다른 항목도 라벨이 좁은 열 폭 때문에 줄바꿈되는데,
**줄바꿈 지점이 숫자를 사이에 두고 걸친다**:

```
자 산 총                    9.주주임원종업
107,638,242,656 …            원단기 77,353,675 …
계                            대여금
```

R75의 3줄 게이트(한글라벨→숫자단독→영문)와도, R77의 정규식 갭과도 다른 변형이다 —
영문이 전혀 없고, 텍스트 스트림(`extract_text()`)만으론 라벨 조각과 숫자가 서로
다른 줄로 흩어져 **원리적으로 복원이 안 된다**(`_region_has_anchor_labels()`가
"자산총계" 등을 개행 때문에 못 찾아 리전 전체를 거부 — 실측: 00116268 BS는 별도·
연결 둘 다 0행이었다).

**사용자 제안(표 구조로 보면 확률이 올라가지 않겠냐)을 실측으로 검증**: 같은
페이지에 pdfplumber `extract_tables()`(기본 설정)를 돌려보니 `'자 산 총\n계'`가
줄바꿈째로 **하나의 셀**에 합쳐지고, 같은 행에 숫자 4개가 정확히 붙어 나온다 —
텍스트 스트림에서 안 보이던 라벨-숫자 대응이 표 구조로 보면 애초에 멀쩡했다.

**설계 — 순수 폴백(정상 필링 무영향)**: `_region_has_anchor_labels()`가 텍스트
리전을 거부할 때만(=대다수 정상 필링은 이 분기 자체를 안 탐) 그 앵커가 걸치는
페이지의 표를 대신 읽는다. 텍스트 방식을 표 방식으로 **전면 교체하지 않는다** —
① 표 인식이 모든 필링에서 되리란 보장이 없고(제출사마다 PDF 생성 도구가 달라
경계선 없는 문서도 있음) ② 지금 텍스트 스트림 경로는 이미 수백 건 실측으로 다듬인
코드라 전면 교체 시 검증 없이 회귀 위험이 크다. 그래서 텍스트 게이트가 실패한
리전에 한해서만(=텍스트로 원리적으로 복구 불가능했던 경우만) 표를 시도한다.

신규 함수(`fin2/extract/pdf.py`): `_pages_overlapping()`(앵커 리전이 걸치는 페이지
찾기), `_table_rows_for_span()`(그 페이지들의 `extract_tables()` 행 수집),
`_clean_table_label()`/`_table_has_anchor_labels()`(셀의 줄바꿈까지 포함한 공백을
지워 라벨 재구성 — 이미 한 셀이라 3줄 게이트처럼 다음 줄을 추측할 필요가 없다),
`_iter_data_lines_from_table_rows()`(라벨셀+금액셀 → `_parse_numline_tokens()`
재사용, 표 격자가 열을 실제보다 잘게 쪼개 넣는 빈 칸 잡음만 필터링). `extract_pdf_
facts()`는 `_read_pdf_text()`(텍스트만 뽑고 파일 즉시 닫음) 대신 `with pdfplumber.
open()`을 파싱 내내 열어둔 채 페이지 경계(`page_bounds`)와 함께 `facts_from_text()`
에 넘긴다 — `pdf`/`page_bounds` 는 선택 인자라 기존 텍스트-fixture 테스트는 전부
무변경으로 통과.

**실측 검증**: `00116268` H1 2001 — 표 폴백 전 BS 0행(별도·연결 둘 다) → 후 **55행**,
자산총계=107,638,242,656/부채총계=61,277,762,838/자본총계=46,360,479,818(항등식
정확히 성립, DART 원문과 일치). FY/Q3 2001도 같은 문서 내 다른 기간 표에서 동일
패턴으로 정상 복구.

- 신규 테스트 3개(`fin2/tests/test_pdf.py`, `_FakePdf`/`_FakePage`로 pdfplumber
  의존성 없이 검증): `test_table_has_anchor_labels_reconstructs_wrapped_cell`,
  `test_iter_data_lines_from_table_rows_yields_full_reconstructed_label`,
  `test_table_fallback_recovers_wrapped_grand_totals_end_to_end`(pdf 미전달 시
  기존처럼 BS 전멸 → pdf 전달 시 항등식 성립까지 한 테스트 안에서 대조). `pytest
  fin2/tests/ tests/` 792 passed(무관 기존실패 1건 제외, 회귀 0).
- 백필: `scripts/backfill_pdf_table_fallback_2026-09-06.py`(R77 잔여 55건 재적용
  — missing→ok 18, 회귀 0) + `scripts/backfill_pdf_multiline_195_2026-09-06.py`
  재실행(195건 census 재조회 — 이번엔 후보가 45건으로 줄어 있었다, 이미 고쳐진
  필링은 census 자체 탐지 신호(BS≤2행)에서 빠지므로 당연함).
- **최종 정산(195건 census, 원래 static 목록 기준 390행=195필링×별도/연결)**:
  ok 230 / fail 26 / missing 134. 고유 필링 기준 93건(41개사)이 아직 완전히 ok는
  아님 — 그중 **19건은 fail 포함**(값은 있으나 항등식 불일치, 원인 미상), **74건은
  missing만**(값 자체가 없음). fail 리스트는 R78 스코프 밖(표 폴백은 "텍스트가
  아예 못 찾은 경우"만 다루고, "값은 뽑았는데 틀린" 경우는 원인이 다름 — 다음
  세션 후보). 아티팩트 "195건 백필 잔여결측"을 fail+missing 93건 전체로 갱신.
- 커밋 대기: `fin2/extract/pdf.py`, `fin2/tests/test_pdf.py`, 신규 스크립트,
  `docs/PARSING_RULES.md` 이 절.
- **★잔여 93건 신규 4번째 패턴 발견 + 진행방식 문서화**: 원문검토 중 00111218에서
  R76/77/78 어디에도 안 걸리는 새 변형(라벨열·숫자열 전체가 문서 중간부터 한 칸씩
  밀림) 발견 — 사례 1건뿐이라 일반화 보류(사용자 결정: 짐작으로 일반화하지 않고
  하나씩 원문대조하며 카탈로그화). 진행방식·사례로그는
  `docs/plans/pdf_track_c_parser_robustness_2026-09-06.md`.

## R79. `account_mapper` — "차/대"·"임차/임대" 처럼 한 글자 차이로 뜻이
정반대(자산↔부채)가 되는 라벨 쌍이 fuzzy 매칭에서 서로 오매핑됨

배경: DB증권(00115694, 20010214000346) HTML뷰어 경로 검증 중 BS 155행 전수
원문대조(`docs/plans/html_viewer_extractor_design_2026-09-07.md` §8-11 후속,
사용자 지시 "155개 행 전수 원문대조 진행해줘")로 발견. `account_mapper`는 Stage 1/2
(exact/정규화 일치)가 Stage 3(Jaro-Winkler 퍼지)보다 항상 우선하는데, 문제의 두
쌍은 **정확한 쪽(alias) 자체가 등록 안 돼 있어서** 편집거리만 보는 퍼지가 뜻이
정반대인 반대쪽 alias 에 붙어버렸다:

- **"임차보증금"**(세입자가 낸 보증금, 자산) — exact alias 없음 → "임대보증금"
  (임대인이 받은 보증금, 부채, 한 글자 "임차"↔"임대"만 다름)에 오매핑. 실측: DB증권
  별도 BS 174억원이 `bs.other_noncurrent_liabilities`로 잘못 적재.
- **"이연법인세대"**(K-GAAP 구세대 대변=부채 표기) — exact alias 없음(신세대 표기
  "이연법인세부채"만 등록) → "이연법인세자산"(신세대, 자산)에 오매핑. 실측: DB증권
  별도 BS 2.3억원이 `bs.deferred_tax_asset`로 잘못 적재(진짜는 부채).

두 계정 모두 그랜드토탈(자산총계/부채총계/자본총계) 자체는 별도 라벨로 직접
뽑히므로 항등식 검증(T1 판정)엔 영향 없었지만, 세부 라인아이템이 계속 오염된
채 남아있었다 — HTML/PDF 두 추출기가 같은 `account_mapper`를 공유하므로 이
버그는 HTML뷰어 전용이 아니라 PDF 추출기에도 동일하게 존재했다.

수정: `account_maps/bs_accounts.py` 에 exact alias 4개 추가 — `bs.deferred_
tax_asset`+"이연법인세차", `bs.deferred_tax_liability`+"이연법인세대",
`bs.other_noncurrent_assets`+"임차보증금"(기존 "임대보증금"/`bs.other_noncurrent_
liabilities`는 그대로 유지, 정반대 뜻이라 병존해야 함). Stage 1/2가 이제 두
라벨 모두 exact 로 먼저 잡아 Stage 3 퍼지까지 안 감.

회귀테스트: `fin2/tests/test_account_mapper_lessee_deposit_and_kgaap_deferred_
tax.py`(5개, 반대쪽 alias 안 깨졌는지도 확인). `pytest fin2/tests/ tests/`
816 passed(무관 기존실패 1건 그대로, 회귀 0). 일반화 시사점: 이 프로젝트
account_mapper 어휘 전반에 "차/대"·"임차/임대" 류 1글자-반의어 쌍이 몇 개나
더 있는지는 미조사 — 이번엔 실측으로 걸린 2건만 수정(카탈로그화 원칙, 짐작
확장 안 함).

## R80. `account_mapper` 전체 어휘 스캔 — R79 패턴의 체계적 재현(형태소 반의어
갭 213건 발견, 실질위험 2그룹 확정·수정)

배경: R79(DB증권 155행 원문대조로 반의어쌍 2건 발견) 직후 사용자 지시
"전체 어휘 스캔을 별도 진행해봐"로, 등록된 818개 alias 전체(BS 294·IS
221·CF 253·NOTE 50)에 회계 반의어 11쌍(채권/채무, 매입/매출, 선급/선수,
예치/예수, 취득/처분, 차입/대여, 미수/미지급 등)을 적용해 미등록 변형이
`mapper.map()`에서 실제로 뭘로 판정되는지 전수 실행(스크립트는 job tmp,
비영속). 순수 유사도(Jaro-Winkler) 전수쌍 스캔도 병행(470건)했으나 대부분
이미 양쪽 다 정확히 등록된 "유동/비유동"류 정상 쌍(노이즈)이었고, 형태소
반의어 치환 스캔(213건) 쪽이 실질 신호였다.

**그룹1(간단한 alias 추가로 해결) — "비유동기타채무"**: 어순만 뒤집힌
"기타비유동채무"는 등록돼 있는데 이 변형은 없어 자산쪽 "비유동기타채권"에
fuzzy 오매핑됨. `account_maps/bs_accounts.py`의 `bs.other_noncurrent_
liabilities`에 exact alias 추가로 해결(R79와 동일 수법).

**그룹2(더 근본적 — canonical 자체가 없음) — CF/NOTE "취득"↔"처분" 반의어
6종**: "종속기업의처분"·"관계기업의처분"·"공동기업투자의처분"·"공동기업의
처분"·"투자부동산의취득"·"기계장치의취득"·"차량운반구의취득"·"산업재산권의
처분"·"자기주식의처분"(CF)·"자기주식처분금액"(NOTE) — "취득"(현금유출)
canonical 은 있는데 그 반의어 "처분"(현금유입) 전용 canonical 이 스키마에
아예 없어서, 처분 라벨이 찍히면 부호가 반대인 취득 계정으로 fuzzy 오매핑됨.
alias 추가로는 못 고침(정확한 반대쪽 코드가 없으니까) — 신규 canonical
코드 신설은 스키마 확장(하류 소비 코드 영향 검토 필요)이라 더 큰 결정이지만,
사용자가 "방어 우선"을 택해 `parser/common/account_mapper.py`의
`_FUZZY_BLOCK`(기존에 있던, 지금까지 빈 집합이었던 퍼지차단 메커니즘)에
정규화된 라벨 10개를 등록 — 부호오염 대신 무매핑(unknown)으로 떨어지게
방어만(결측이 오염보다 낫다). **전용 처분(inflow) canonical 신설 자체는
미착수 — 향후 별도 결정 사항으로 남음.**

회귀테스트: `fin2/tests/test_account_mapper_full_vocab_scan_2026-09-07.py`
(4개, 그룹1·그룹2 양쪽 + 원래 취득쪽/기존 처분쪽 매핑 안 깨졌는지도 확인).
`pytest fin2/tests/ tests/` 820 passed(무관 기존실패 1건 그대로, 회귀 0).

## R81. R80 "처분(inflow) 전용 canonical 미신설" 후속 — 사용자 지시 "처분
부분 추가하는것 진행해"로 실제 신설

R80 이 방어(`_FUZZY_BLOCK`)만 하고 미룬 "전용 처분 canonical 신설"을 진행.
먼저 하류 영향범위부터 확인: `cf.capex`/`cf.capex_intangible`만 FCF 계산
(`_CAPEX_CANON`, fin2/standardize/rules.py)에 쓰이고, M&A류(취득/처분 전부)는
원래 FCF 계산에 안 잡힘(대칭 유지 가능 확인). `app/registry/extended.py`
(확장재무 UI 표시)·`app/data/shareholder_return.py`(자사주 순취득 계산, 지금은
취득쪽만 읽음)도 확인.

**신규 canonical 4개**(account_maps/cf_accounts.py + note_accounts.py):
- `cf.disposal_of_subsidiaries`("종속기업의처분") — 대응 `cf.acquisition_of_
  subsidiaries`와 짝. M&A 현금흐름이라 `_CAPEX_CANON`엔 안 넣음(취득쪽도 원래
  안 잡힘, 대칭 유지).
- `cf.disposal_of_associates`("관계기업의처분"·"공동기업투자의처분"·"공동기업
  의처분") — 대응 `cf.acquisition_of_associates`와 짝.
- `cf.investment_property_acquisition`("투자부동산의취득") — 대응 `cf.
  investment_property_proceeds`와 짝. ★`_CAPEX_CANON`엔 **의도적으로 미포함**
  — FCF 정의를 조용히 넓히는 셈이라 별도 확인 필요, 미결정으로 남김.
- `cf.treasury_stock_proceeds`/`note.treasury_stock_proceeds`("자기주식의
  처분"/"자기주식처분금액") — 대응 `cf.treasury_stock_purchase`/`note.
  treasury_stock_purchase`와 짝. ★`app/data/shareholder_return.py`는 아직
  이 신규 canonical 을 안 읽음(순취득금액 넷팅은 별도 후속).

**신규 canonical 없이 기존 코드로 해결한 것**: "산업재산권의처분"은
`cf.ppe_proceeds`(일반 유형/무형자산 처분 버킷)에 등록 — 같은 문서의
"무형자산의처분"이 이미 그렇게 매핑되는 것과 동일 패턴(선례 확인 후 재사용,
새 코드 안 만듦).

**끝까지 무매핑으로 남긴 것**: "기계장치의취득"/"차량운반구의취득" 2개만
`_FUZZY_BLOCK`에 계속 유지 — 대응 처분쪽(`cf.ppe_proceeds_detail`)은 있지만
취득쪽은 보통 총계 라인(유형자산의취득→`cf.capex`)과 같이 찍혀 세부항목까지
별도 canonical 로 잡으면 총계와 중복계상 위험. 임시방편이 아니라 영구 방어.

**부수 발견(수정 안 함, 기록만)**: 이 조사 중 `cf.available_for_sale_net`가
취득·처분 양쪽을 **같은 canonical 하나로** 등록해둔 기존 패턴을 발견 —
실제 report_lines 에 "유동성매도가능증권의취득"(14억)과 "…의처분"(1억)이
같은 필링에 별도 행으로 동시에 존재하는 사례 실측 확인(00100601). 계층3에서
같은 canonical·같은 기간에 값이 둘 이상이면 `_resolve()`가 하나만 선택하는
구조라, 이 "순증감 공유코드" 패턴이 실제로는 둘 중 하나를 조용히 버리고
있을 가능성이 있음(진짜 net 합산이 아님) — 이번 스코프 밖이라 손 안 댐,
후속 조사 후보로만 기록.

`app/registry/extended.py`에 신규 canonical 4개 표시 라벨 등록.
`fin2/tests/test_account_mapper_full_vocab_scan_2026-09-07.py` 갱신(방어
기대→정확매핑 기대로 5개 테스트 재작성). `pytest fin2/tests/ tests/`
829 passed(무관 기존실패 1건 그대로, 회귀 0).

## R82. Category C(fy1999~2003 절단 복구) 배치 경로 — HTML→PDF T1/T2/T3
조정 배선 완료

`collector/pdf_lines_sync.py::recover_one()`가 PDF만 파싱하던 옛 방식 대신
`fin2/extract/reconcile.py::reconcile()`(HTML→PDF T1/T2/T3 조정, §8-8~§8-11)
을 쓰도록 바뀌었다. ★이건 `scripts/collect_new.py` 데일리 두 call site 배선이
아니다(그건 XBRL 원문이 있는 현재 필링용, 무관) — `sync_pdf_recovery()`는
Category C(fy1999~2003 절단 복구, 6,598건 population) 전용 독립 배치 경로고,
Track C 93건은 이 population 의 부분집합이다.

basis별 decision 이 "html"/"pdf"(자동채택)인 facts 만 report_lines 로 변환,
"unresolved"는 제외하고 `report_recon_candidates` 리뷰 큐에 적재(`persist_
unresolved()`). `facts_to_report_lines()`의 `unit_source`도 하드코딩 "pdf"
대신 `source_format`("html"/"pdf")을 그대로 써서 값의 출처를 report_lines
에 남긴다. `sync_pdf_recovery()` 카운터도 basis별(`bases_html`/`bases_pdf`/
`bases_unresolved`)로 재정의. ★`store_report_lines()`가 rcept 단위 무조건
delete-then-insert라 `lines`가 빈 리스트일 때 호출하면 delete 만 되고 이전
데이터가 지워질 위험 — 옛 코드에 있던 `if lines:` 가드 유지 확인.

테스트: `fin2/tests/test_pdf_lines_sync.py` 5개 신설(순수 로직, `reconcile()`
mock). `pytest fin2/tests/ tests/` 834 passed(무관 기존실패 1건 그대로, 회귀0).

라이브 스모크(실제 미복구 후보 3건, 진짜 DB write): DB증권·일성건설·제일기획
각 1건 — `{'candidates': 3, 'bases_html': 3, 'bases_pdf': 0, 'bases_
unresolved': 3, 'rows': 329, 'dq_rows': 3, 'errors': 0}`. 별도(separate) 3건
전부 `unit_source='html'`로 BS/IS/CF 정상저장, 연결(consolidated) 3건 전부
report_lines 미저장(의도) 대신 `report_recon_candidates` 정확 적재(제일기획
T3/T3, DB증권·일성건설 T2/T2 — 연결재무제표 자체가 없는 정상케이스).
`dq_assertions.py` WARN 2→5(신규 3건 정확 반영), ERROR 그대로 0.

**남은 것**: 나머지 Category C 후보(93건 잔여 포함) 전체를 이 경로로 실제
돌리는 소급 백필은 별도 단계(런북 원칙) — 미착수, 별도 지시 대기.

## R83. Track C 93건 전체 소급 백필 실행 중 `reconcile()` T2 분기 오채택
버그 발견·수정 — "PDF가 완전공백만 아니면 채택" → "PDF가 T1일 때만 채택"

93건 전체 백필(`scripts/backfill_track_c_93_reconcile_2026-09-07.py`) 1차
실행 후, report_lines 재저장분을 독립적으로 재계산(`account_mapper.map()`
을 label_raw 에 다시 돌려 `reconcile()` 판정과 무관하게 자체 검산)해 3건
발견: "DQ 리뷰 큐에 없는데(=자동채택) 항등식은 실제로 불성립" — 일성건설
(00146232) 연결, 일진디스플(00198697) 별도+연결, 씨아이테크(00127158) 연결.

**근본원인**: `reconcile_basis()`의 T2(HTML 완전공백) 분기가 원래
`pdf_conf != T2_EMPTY`(T1 이든 T3 이든 "완전공백만 아니면") 조건으로 PDF를
채택했다. "원인B 안전망"의 원래 취지는 "PDF가 스스로 항등식을 증명했을
때"였는데 실제 조건은 "PDF가 뭐라도 찾기만 하면"이었다. HTML이 아무것도
못 찾은 이상(T2) 교차검증할 상대가 없어, PDF의 T3(항등식 불성립·부분값)를
봐줄 근거가 없었다 — R81(§8-11)에서 T3(html)+T1(pdf) 분기엔 교차검증을
넣었는데, 이 T2 분기는 그보다도 느슨한 기준(T1조차 요구 안 함)이 그대로
남아있었다. 최초 스모크 4건(§8-9)에서 안 걸린 이유: 그때는 우연히 pdf_conf
가 전부 T1이었던 케이스만 표본이었다.

**수정**: T2 분기 조건 `pdf_conf != T2_EMPTY` → `pdf_conf == T1_CONFIDENT`
(T3 분기와 동일 엄격도로 통일). 회귀테스트 `test_t2_html_and_t3_pdf_stays_
unresolved_not_auto_adopted` 추가. `pytest fin2/tests/ tests/` 835
passed(무관 기존실패 1건 그대로, 회귀 0).

**93건 재백필**(수정 반영, delete-then-insert라 안전하게 덮어씀):
`bases_pdf` 7→3(오염됐던 4건이 정확히 unresolved로 강등), `rows` 7939→7745
(오염 행 194개 제거). **독립 재검증 재실행 결과 "자동채택됐는데 항등식
불성립"인 경우 0건**(3건→0건, 완전 해소).

**93건 전체 최종 결과(186 basis)**: 별도(separate) 항등식성립 59/93(63%,
확실 개선), 별도 unresolved 34/93, 연결(consolidated) 항등식성립 0/93
(설계상 항상 그럼), 연결 unresolved 93/93(수정 후 전부 사람 확인 대기).
report_lines 신규 7,745행, DQ 리뷰 큐 누적 130행, 에러 0.

**남은 것**: std_financials_v3 재빌드(계층3)는 아직 안 함(report_lines
레벨까지만). unresolved(별도34+연결93) 는 사람 원문대조 대기.

---

## R84. `parser/common/account_mapper.py` — Stage 3 fuzzy containment 가
2026-07-18 에 의도적으로 제외한 "미처분이익잉여금" 을 되살려 `bs.retained_
earnings` 오매핑 (item2(나) 트랙, HS애드 등 247개사/656행 실측 오염)

배경: 항목2(나)(`docs/plans/section_def_fallback_wrong_sibling_unit_design_
2026-09-06.md`) 재조사 중 00140168(HS애드) "미처분연결이익잉여금"이
`bs.retained_earnings`로 매핑되는 걸 확인, "개념 불일치 의심" → 계정매퍼
코드로 원인 추적.

**근본원인**: "미처분이익잉여금"은 2026-07-18(D4 2R)에 `account_maps/
bs_accounts.py`의 `bs.retained_earnings` exact alias 목록에서 **의도적으로
제거**됐다(총계='이익잉여금'의 sub-line 이라 총계 자리에 오면 과소·값충돌).
그런데 `AccountMapper._fuzzy_match()`의 "포함관계"(containment) 매칭이 alias
'이익잉여금'이 '미처분이익잉여금'의 부분문자열이라는 이유만으로(`len_ratio
=0.5`, `score=0.90+0.5*0.09=0.945 ≥ threshold 0.88`) 그대로 되살려 다시
`bs.retained_earnings`에 오매핑했다 — '미처분연결이익잉여금'·'미처분전이익
잉여금'·'당기말/분기말/반기말미처분이익잉여금'·'미처분이익잉여금(미처리
결손금)' 등 접두/접미 변형까지 전부 같은 경로로 새어나왔다. 같은 필링에
진짜 총계 라인('이익잉여금'/'이익잉여금(결손금)')이 있으면 `_resolve()`가
값 다른 후보 2개로 보고 conflict 로 안전하게 보류하지만, 없으면(흔함 —
인터림 BS 가 적립금 세부내역 없이 미처분 잔액만 보여주는 서식) 유일한
후보로 그대로 확정됐다.

**실측 규모**(DB 전수 SQL + `AccountMapper.map()` 직접 실행, 2026-09-08):
BS 통계표에 "이익잉여금" 계열 라벨이 있는 274,659개 (corp,rcept,basis)
조합 중, "미처분" 계열 라벨만 있고 비-미처분 총계 라벨이 없는 위험군
1,101행/247개사를 실제 `AccountMapper.map()`에 통과시킨 결과 **100%
(1,093/1,093)**가 `bs.retained_earnings`에 fuzzy 매핑됨을 확인(허위양성
없음). `std_financials_v3`와 교차대조 결과 **656행이 이미 라이브 DB에
이 오염값 그대로 저장돼 있었음**(26행 NULL, 419행 다른값=미조사). 표본
(00152437, 위험군 내 최다 108행) 자체 시계열로 "진짜 다른 값"임을 확인
(2007~2008년 매 기간 총계≠미처분, 적립금 차이 5~6억원+, 2011년부터
적립금 공시 자체가 빠지며 위험군 진입).

**수정**: `AccountMapper.map()`에 Stage 3 진입 전 가드 추가 — 정규화된
라벨에 "미처분"과 ("이익잉여금" 또는 "결손금")이 함께 있으면(`fs_section
in (None, "bs")` 한정) 무매핑(`unknown.*`)으로 차단. "결손금" 단독(음수
총계 표현, 기존 exact alias)은 "미처분"이 없으면 안 건드림 — Stage 1/2가
먼저 처리하므로 영향 없음. 코드 위치: `parser/common/account_mapper.py::
map()`, Stage 3(`_fuzzy_match()`) 호출 직전.

**회귀테스트**: `fin2/tests/test_account_mapper_undistributed_retained_
earnings_guard_r84.py`(8개 — 차단 대상 5종 변형 + 정상 매핑 3종 유지
확인). `pytest tests/ fin2/tests/` 857 passed(무관 기존실패 1건
`test_biz_section.py::test_lxintl_facility_table_dropped` 그대로, 회귀 0
— 코드 수정 전 동일 실패 재현으로 무관함 확인). 위험군 1,093행 재스캔
결과 사후 100%(1,093/1,093) `unknown`으로 차단 확인.

**백필(247개사, `--year-min 1999` 스코프 재빌드)**: `build_std_v3.py
--corp <247개사> --year-min 1999`(44,679행, 에러 0) + `calendarize_corp_v3`
247/247 성공(에러 0). 전/후 diff(`std_financials_v3.retained_earnings`,
같은 corp/fy/fp/statement_type): **786행 변경** — 627행 NULL로 전환(오염값
제거), **159행은 오히려 NULL→정답값으로 신규 확정**(진짜 총계 라인이 sub-
line 과 conflict 로 묶여 보류돼 있다가, sub-line 이 배제되며 단독후보로
승격된 경우 — 00427483 2009FY 연결 실측: `Ⅴ. 연결이익잉여금(주20)`=
154,120,712,864원이 이제 정확히 확정, 이전엔 `미처분연결이익잉여금`=
61,157,599,700원과 conflict 로 NULL 이었음).

**dq_assertions 전수 검증**: `statement_magnitude_impossible` 4→**3**
(00140168 HS애드 소거, 나머지 00258421 기산텔레콤·00108746 DKME·00126380
삼성전자는 이 수정과 무관한 별개 트랙 — DKME 는 "결측 유지" 정책 결정
완료, 기산텔레콤은 원문대조 미착수, 둘 다 이번 수정 대상 아님). 247개사
스코프 내 절대값 5×10¹⁵원 초과 잔존 0건. 다른 ERROR/WARN 어서션에 247개사
관련 신규 위반 없음(전수 재확인).

DKME(00108746)·기산텔레콤(00258421)은 이번 수정과 무관(라벨에 "미처분"이
없음 — "연결이익잉여금"/BS 전체 오염, 원인은 section_def 단위폴백이지
account_mapper 개념매핑이 아님, item2(나) 문서 참고). 커밋은 사용자 확인
대기.

---

## R85. `fin2/extract/report_lines.py::_emit_eps_lines()` — H1/Q3 EPS 행이
2단[3개월|누적] 헤더를 모르고 파싱 순서 앞 3개를 그대로 [당기,전기,전전기]로
잘못 라벨링(누적 대신 3개월 값 저장) (2026-09-09)

**발견 경위**: 사용자가 DART 뷰어(rcpNo=20250814003156, 삼성전자 2025H1)에서
기본주당이익 원문 값을 눈으로 대조하다 DB 저장값(411)이 화면에 보이는 4개
값 중 "3개월" 열이지 "누적" 열(1,360)이 아닌 것 같다고 지적, 원문/DB 대조로
확정.

**근본원인**: `_emit_section_lines()`는 H1/Q1/Q3 IS·CF 표에서 `_interim_
cumulative_cols()`(`text.py`)로 2단[3개월|누적] 헤더를 감지해 '누적' 토큰이
붙은 컬럼만 값으로 채택한다(H1/Q3 는 [당기3개월,당기누적,전기3개월,전기누적]
4열이 정상 구조 — R36/R74 등 여러 규칙이 이미 이 컬럼판정을 전제로 함).
그런데 EPS(주당손익) 행은 라벨 자체에 인라인 단위(원/주)가 있어(표 단위
천원/백만원 미적용) `_emit_eps_lines()`라는 **완전히 분리된 별도 패스**로
처리되는데, 이 함수는 그 2단 헤더 구조를 전혀 모르고 파싱된 값을 그냥
`present[:3]`(컬럼 위치 순서 앞 3개)로 잘라 [당기(col_index=0),전기(1),
전전기(2)]로 라벨링했다 — H1/Q3 표에서 앞 3개는 실제로
[당기3개월,당기누적,전기3개월]이라 "당기" 자리에 3개월(당분기 단독)값이,
"전기" 자리에 당기누적값이 뒤섞여 들어갔다. 추가로 emit 되는 행의
`is_cumulative`는 `(report_fiscal_period != "FY")`로 무조건 True라, 실제로는
비누적(3개월) 값인데 메타데이터는 "누적"이라고 주장하는 내부 모순까지
있었다.

**실측**(원문 XML 대조, 삼성전자 20250814003156 별도): "23. 주당이익" 주석
표·손익계산서 본문 표 둘 다 헤더가 "3개월 누적 3개월 누적"(보통주 기준)이고
데이터 행은 `기본주당이익(손실) (단위 : 원) 411.0 1,360.0 1,045.0 2,479.0`
= [당기3개월,당기누적,전기3개월,전기누적]. `report_lines`에는 col_index=0
(context_fiscal_year=2025)에 **411**(3개월)이 저장돼 있었다 — 같은 필링·
같은 basis의 `반기순이익`(cum_map 경로를 타는 일반 라인)은 정확히
**9,139,217백만원**(누적)로 저장돼 있어, 같은 표 안에서 라인 종류에 따라
컬럼선택 결과가 서로 어긋나는 것으로 확정.

**영향 범위**: Q1은 3개월=누적이 같은 기간이라 결과적으로 무해. **H1·Q3는
전 종목·전 기간 EPS/DPS 계열 행("주당" 라벨 전체)에 걸쳐 체계적으로
재현**되는 함수 자체의 구조적 결함(회사별 예외 아님) — 기존 R27/R45~R47
(EPS 오분류)과는 다른 별개 결함으로, 이번까지 문서화된 적 없었다. 전사
스코프(몇 건/몇 개사) census 는 아직 안 함 — 사용자 지시로 삼성전자
(00126380) 재적재만 우선 진행.

**수정**: `_emit_eps_lines()`에 `cum_map` 파라미터 추가 — 호출측
(`_emit_section_lines()`)이 같은 표에서 이미 계산해둔 `_interim_cumulative_
cols()` 결과를 그대로 넘겨받는다. `cum_map is not None`(2단 헤더 검출)이면
표 본류와 동일하게 '누적' 토큰 붙은 컬럼만 **위치 기준**으로 선택
(`amounts_by_pos`는 `_split_label_amounts()`가 이미 위치보존으로 반환하는
`amt_cells`를 그대로 파싱 — 라벨/주석컬럼 제외 외에는 압축하지 않으므로
cum_map 의 절대위치 인덱싱과 정렬이 맞다). `cum_map is None`(FY 또는 2단
헤더 미검출)이면 기존 동작(파싱 순서 앞 3개) 그대로 유지 — FY EPS 행은
원래도 컬럼이 [당기,전기,전전기] 3개뿐이라 회귀 없음.

**회귀테스트**: `fin2/tests/test_eps_interim_cum_map_r85.py`(신설) — H1 2단
헤더 합성표에서 EPS 행이 누적컬럼(1,360/2,479)을 선택하는지, 기존 R28(FY
K-GAAP 헤드라인 skip-gate)·`test_review_csv.py`(EPS row_order=NULL 불변식)
전부 무회귀 확인.

**미조치**: 전사 재백필(다른 회사들의 H1/Q3 EPS 행)은 스코프 미결정 —
`docs/runbook_new_parser_pipeline_integration.md` 절차대로 두 call site
배선 확인 + 소급 백필은 별도 세션 필요.

---

## R86. `fin2/extract/report_lines.py::_emit_section_lines()` — else 분기(선두 None
절삭)가 순수 기간열(주석 컬럼 없는) FY 표에서 진짜 공백을 파서 아티팩트로 오인해
전기/전전기 값을 당기 열로 밀어넣는 결함 (2026-09-09)

**발견 경위**: 사용자가 DART 뷰어(rcpNo=20200330003851, 삼성전자 2019FY)에서 별도
현금흐름표 "장기매도가능금융자산의 처분/취득" 행을 원문과 대조하다, 원문엔 당기·전기
칸이 비어 있는데 CSV엔 값이 채워져 있는 것을 발견. 뒤이어 포괄손익계산서 "매도가능
금융자산평가손익"에서도 같은 증상을 지적 — 원문 확인 결과 사용자가 스스로 메커니즘을
정확히 짚었다: "해당 기수에 값이 없는 경우에 전기, 전전기 칸에 있는 값을 취해서
저장한 것으로 보여."

**근본원인 — R85와 달리 신규 결함이 아니라 이미 알려진(2026-08-29, classB §5.1) 잔여
갭이 실전에서 처음 확인된 것**. `_emit_section_lines()`의 `else` 분기(§5.4, cum_map도
multicol도 아닌 순수 FY 3열[당기/전기/전전기] 표)는 선두 None 컬럼을 무조건 절삭하고
남은 값을 col_index=0부터 다시 라벨링한다. classB 조사가 이미 이 절삭의 **유일한 정당
동기**(한화손해보험 2020FY류 — 라벨 바로 다음 주석참조 컬럼이 빈 값으로 amount_cells에
잘못 섞여들어와 생기는 phantom 선두 None)를 확인했고, 그 근본원인은 R19(2026-08-24)가
`_split_label_amounts_ex()` 단계에서 이미 제거했다(주석 컬럼이 있는 표에서는 빈칸도
항상 주석 칸으로 인정). 그런데 그 조사는 TE(XBRL ACONTEXT) 셀에 대해서만 새 정지신호
(`acontext_missing`)를 추가했고, `<TD>`(ACODE/ACONTEXT 개념 자체가 없는 구형·비XBRL
렌더링) 셀은 "신호가 없다"는 이유로 **의도적으로 그대로 뒀다**("한화손해보험류(TD, 신호
없음)는 로직 분기 자체가 안 건드리므로 완전히 무변경" — 당시엔 R19가 이미 그 표들의
근본원인을 없앴으니 절삭이 "무해하게 통과할 뿐"이라고 판단). 삼성전자 2019FY 별도
재무제표는 정확히 이 사각지대(순수 `<TD>`, 주석참조 컬럼 자체가 없는 표)에 해당하고,
"무해"였던 원 가정이 깨지는 구체적 실측 사례다 — IFRS9 전환(2018)으로 `장기매도가능
금융자산`류 K-GAAP 전용 계정이 전전기(2017)에만 존재하고 당기·전기(2019/2018)는
원문 자체가 진짜 공백([공란,공란,전전기값] 3열)인데, 절삭이 이를 "파서 아티팩트"로
오인해 전전기값을 당기 열로 둔갑시켰다.

**실측**(원문 XML 직접 대조, `20200330003851.xml`은 CP949 인코딩): 별도 현금흐름표
`<TD>` 셀 3개 그대로(값 손실·컬럼 붕괴 없음) — "장기매도가능금융자산의 처분" =
`[공란,공란,98,265]`, DB엔 col_index=0에 98,265(전전기값)가 저장돼 있었음. "장기금융
상품의 취득" = `[공란,(1,860,000),(500,000)]`, DB엔 col_index=0에 -1,860,000
(전기값)이 저장. "장기매도가능금융자산의 취득"·"매도가능금융자산평가손익"(포괄손익
계산서)도 동일 패턴.

**전수조사(삼성전자, 최근 필링 → 20200330003851, 27건)**: 임시 계측(구현 완료 후
원복, diff로 확인)으로 실제 값이 동반된(구조상 전부 공란인 헤더행 제외) 절삭 발동
건수 census. **20200330003851(2019FY)에 약 20건 집중**(IFRS9 전환 경계 — 단기/장기
매도가능금융자산·만기보유금융자산·상각후원가금융자산·매도가능금융자산평가손익·
장기금융상품의 취득·장기매도가능금융자산의 처분/취득·당기손익-공정가치금융자산의
취득·자기주식의 취득·장기차입금의 차입·사업양도로 인한 현금유입액 등), 산발적으로
20211115001965(2021Q3) 1건·20230515002335(2023Q1) 1건·20230814002534(2023H1) 3건.
나머지 22개 필링(2020Q1~2020FY·2021 전체·2022 전체·2023~2024 대부분·**2024FY
이후 최신 2026H1까지**)은 0건.

**수정**: `_emit_section_lines()`에 세 번째 정지신호 추가 — `table_has_note_column`
(R19/R65가 이미 표 단위로 계산하는 "이 표에 주석참조 컬럼이 있다"는 구조적 신호,
`_table_has_comma_note_column()` OR `_table_has_note_header()`)을 `extract_rows()`가
아닌 `_emit_section_lines()` 자신이 표 하나당 한 번 재계산(값은 항상 같음, `RowData`가
이 값을 밖으로 안 돌려주므로 로직 복제 없이 같은 두 헬퍼를 그대로 재사용). 선두절삭
while 루프에 `and table_has_note_column` 조건을 추가 — 주석참조 컬럼이 있는 표(원 동기
사례)는 기존 동작 완전히 무변경, 없는 표(사각지대)는 진짜 공백류 선두 셀 앞에서 절삭을
멈춰 결측으로 남긴다("오염보다 결측을 택한다"는 R3/classB/R74와 같은 원칙의 연장선).
`fin2/extract/text.py::_emit_section`(원래 "쌍둥이 로직"으로 명시된 함수)은 이번에
**같이 고치지 않음** — `scripts/collect_new.py`(데일리 파이프라인)가 `report_lines`만
읽고 fact_v2/text.py 경로는 안 쓴다(fact_v2 DROP 완전종료, 2026-09-01) 확인, 프로덕션
비활성 코드라 스코프 밖으로 판단.

**회귀테스트**: `fin2/tests/test_report_lines.py` 2건 신설 — ①
`test_samsung_2019fy_leading_blank_no_longer_shifted_to_current_period`(실측 파일,
장기매도가능금융자산의 처분/취득이 더 이상 col_index=0에 안 실리고 원래 자리
col_index=2에 남는지 + 선두 1칸만 공백인 행·선두가 안 비어있는 행도 확인) ②
`test_hanwha_2020fy_note_column_table_unchanged`(classB 원 동기 사례, 주석참조 컬럼
있는 표는 수정 전/후 완전 동일값 — 회귀 없음 가드). `pytest tests/ fin2/tests/`
927 passed(무관 기존실패 2건 그대로 — `test_lxintl_facility_table_dropped`,
`test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix`, 둘 다 이번 수정과 무관,
회귀 0).

**미조치**: 이번 수정은 삼성전자 스코프만 실측·검증했다. `table_has_note_column=False`
표 전체(전사)에 대한 census(classB가 TE/ACONTEXT 모집단에 했던 것과 같은 규모의
"OLD vs NEW 최종값이 실제로 달라지는 행" 표본조사)는 미실시 — 이 조건이 유일한 정당
동기(한화손해보험류)를 넘어서는 **다른** 합법적 절삭 사례를 놓치고 있을 가능성은
이론상 남아있으나(classB 조사 범위가 TE 모집단이었으므로 TD 모집단에 대한 직접 증거는
없음), 이번 수정으로 "결측으로 남는" 방향의 변화만 발생하고(트림이 멈출 뿐 새 값을
만들어내지 않음) 트림이 실제로 필요했던 케이스가 있다면 그 행이 결측(NULL)이 되는
정도이지 오염값이 새로 생기진 않는다(R3 "오염보다 결측" 원칙과 부합). 전사 백필은
별도 세션 필요.

---

## R87. `parser/xml/table_extractor.py::extract_rows()` — "6-column IS 형식 대응"
선두 None 절삭이 R86과 동일 결함을 별도 위치에서 재현 (2026-09-09, R86 후속)

**발견 경위**: 사용자가 R86 검증 직후 다른 삼성전자 필링(rcpNo=20170515003806,
2017Q1)의 별도 현금흐름표에서 같은 증상("단기매도가능금융자산의 처분"=650,743이
CSV에 채워짐)을 재발견, 이어서 "연결 현금흐름표에도 나타난다"·"단기매도가능금융자산의
처분, 자기주식의 처분 이 부분"으로 구체적 대상까지 직접 짚었다.

**근본원인**: 이 필링의 CF는 R86이 다뤘던 표준 3열([당기/전기/전전기]) FY 표가
아니라 **4열**([당기1분기,전기1분기,전기(FY),전전기(FY)]) 구조다 — 2017Q1 당시
DART 구서식 관행(같은 분기 IS/포괄손익계산서는 이 두 "1분기" 컬럼만 추가로
[3개월|누적] 2단 분할하지만, CF는 분할 없이 이 4열을 그대로 인쇄). `_interim_
cumulative_cols()`가 CF 헤더에서 3개월/누적 토큰을 못 찾아 `cum_map=None` →
`_emit_section_lines()`가 `extract_rows(..., preserve_col_positions=(cum_map is
not None))`를 **False**로 호출한다. 그런데 `extract_rows()` 자신에 R86이 고친
`_emit_section_lines()`의 else 분기보다 **먼저** 실행되는, 완전히 별도 위치의
동형 결함이 있었다 — "6-column IS 형식 대응"이라는 이름의 선두 None 절삭
(`amount_cells≥4개`면 무조건 절삭, `preserve_col_positions`/`keep_all_amount_cells`
가 False일 때)이다. 이 절삭이 `_emit_section_lines()`가 자기 배열을 보기도 전에
이미 선두 공란을 지우고 뒤 값들을 앞으로 당겨버려, R86이 else 분기에 추가한
`table_has_note_column` 가드가 작동할 기회조차 없었다(볼 때는 이미 늦음) — 2026-
08-24 설계문서(`gateb_bugA_col_misselect_optionA_rootfix_plan_2026-08-24.md` §1)
가 "else/multicol 경로는 `extract_rows()`가 압축을 하든 안 하든 자기 앞단에서
이미 동등한 압축을 하므로 결과가 같다"고 결론 낸 바 있는데, 그건 **당시 else
분기도 무조건 절삭**이었기 때문에 성립한 얘기였다 — R86이 else 분기만 조건부로
바꾸면서 그 전제가 깨졌고, `extract_rows()`의 원 절삭이 더 이르게 실행돼 R86의
보호를 무력화하는 사이드채널이 됐다.

**실측**(원문 XML 대조, rcpNo=20170515003806 별도·연결 둘 다 동일 패턴): "단기매도
가능금융자산의 처분" = `[공란,650,743(전기1분기),3,010,003(전기FY),2,143,384
(전전기FY)]` — 수정 전 DB엔 당기 열에 650,743(전기1분기 값)이 저장. "자기주식의
처분" = `[공란,공란,공란,3,034(전전기FY)]` — 수정 전 DB엔 당기 열에 3,034(전전기FY
값, **3칸** 밀림)가 저장. "장기금융상품의 처분"(별도)도 같은 패턴("단기매도가능…
취득"은 연결에서 4열 전부 실공시라 원래도 정상이었음 — 회귀 없음 확인).

**수정**: `extract_rows()`의 이 절삭 조건에 R86과 **같은** `table_has_note_column`
가드를 추가(`extract_rows()`가 이미 표 하나당 한 번 계산해두는 값이라 추가 비용
없음). multicol/cum_map 경로는 위 2026-08-24 설계문서·2026-08-24 커밋(옵션 A,
`preserve_col_positions=(cum_map is not None)`)으로 이미 각자 안전하므로 이 변경의
영향을 받지 않는다(전자는 자체 재압축, 후자는 애초에 이 절삭 자체가 꺼져 있음) —
영향받는 건 else 분기 + `amount_cells≥4개` 조합뿐이라 R86보다도 더 좁게 스코프된
변경이다.

**회귀테스트**: `fin2/tests/test_report_lines.py::
test_samsung_2017q1_four_column_cf_leading_blank_not_shifted`(신설, 실측 파일) —
"단기매도가능금융자산의 처분"·"자기주식의 처분"(별도·연결 둘 다) 당기 열 소거 확인
+ 선두가 안 비어있는 행(연결 "단기매도가능금융자산의 취득") 무변경 확인. 기존 R86
테스트(한화손해보험 note-column 무변경 가드) 포함 전부 무회귀. `pytest tests/
fin2/tests/` 927 passed(무관 기존실패 2건 그대로, 회귀 0) — `extract_rows()`가
biz_section/note_lines 등 report_lines 밖 소비처에서도 널리 쓰이는 공용 함수라
전체 스위트로 확인.

**미조치**: R86과 같은 스코프 한정 — 삼성전자 확인 필링만 검증. `amount_cells≥4개`
+ `table_has_note_column=False` 조합 전체(전사)에 대한 census는 미실시(4열 이상
구조는 2018년경 표준 3열 서식으로 정리된 것으로 보이나 확인은 표본 수준). 전사
백필은 별도 세션 필요.

**후속 조사(2026-09-09, 같은 세션) — `multicol` 분기(원문 금액셀≥6개)는 R86/R87
가드 적용 대상이 **아님**을 실측으로 확정, 코드 변경 없음**: 사용자 질문("열 개수가
늘어나면 또 문제가 발생하나?")에 답하기 위해 `_detect_period_layout()`의 세 번째
문턱(원문 금액셀 수 ≥ 2×n_periods, n_periods≤3 캡이라 사실상 문턱=6)이 R86/R87
가드가 없는 `multicol` 분기(`present = [a for a in row.amounts if a is not None];
pairs = enumerate(present[:n_periods])`)로 빠진다는 것을 코드로 확인하고, 실제 사례
(삼성생명 00126256, 2016 사업보고서/분기보고서 연결 CF)로 검증했다.

결과 — **이 분기는 R86/R87과 근본적으로 다른, 정당한 구조**: 삼성생명 CF는 기(期)
마다 열이 2개(명세/소계 쌍)로 인쇄되고, 소계행은 짝수쪽만·명세행은 홀수쪽만 채워지는
**완전히 규칙적인 구조적 패딩**(예: `가.당기순이익 [2,149,956,공란,1,209,573,공란,
1,337,030,공란]`, `Ⅰ.영업활동으로부터의현금흐름 [공란,4,834,400,공란,5,288,088,
공란,8,946,403]`)이다 — R86/R87의 "계정마다 공란 개수가 들쭉날쭉"(개별 계정의 진짜
결측)과 달리, 이 공란은 "이 행 유형은 이 열 절반을 원래 안 쓴다"는 뜻이라 압축이
**정답**이다. 4개 필링(2016 사업보고서·반기·1·3분기) 전 CF 데이터행(`extract_rows`
직접 실행, non-null count vs n_periods 대조) 실측 결과, 규칙에서 벗어나는 사례는
전부 진짜 부분공시(예: "사채의 발행"이 1개 값만 — 전기·전전기가 진짜 "-"[0]로 명시
공시)였고 R86/87류 오염(계정값이 엉뚱한 회계연도로 밀림)은 0건.

이 분기에 `table_has_note_column` 가드를 그대로 적용하면 "Ⅰ.영업활동으로부터의
현금흐름"의 진짜 당기값(4,834,400)이 결측으로 사라지는 **회귀**가 된다는 것도
확인(가드 적용 시뮬레이션, 실제 코드는 변경 안 함) — **의도적으로 손대지 않는다.**
삼성전자 스코프에서는 이 문턱(≥6열)에 닿는 표를 찾지 못함(2017Q1 CF=4열, 2017반기
CF=2열). 회귀테스트: `fin2/tests/test_report_lines.py::
test_samsunglife_multicol_paired_columns_unaffected_by_r86_r87`(신설, 실측 파일,
소계·명세 두 행 유형 값 고정 — 두 R86/R87 가드가 이 분기를 건드리지 않음을 잠금).

---

## R88. `parser/xml/table_extractor.py::parse_header_columns()`/
`select_by_header_columns()` 신설 — THEAD COLSPAN/ROWSPAN 그리드로 표 구조를 먼저
읽어 cum_map/multicol/else(R85~R87) 3갈래 추측을 대체 (2026-09-09, 사용자 제안)

**배경**: R85~R87 전부 "표가 몇 열이고 각 열이 어느 회계기간인지 데이터 행의 공란
패턴으로 사후 추측"해온 결함이었다. 사용자가 "표의 타이틀(헤더) 부분을 먼저 검토하고
그 형태에 따라 항목 값을 선택해야 하는 것 아니냐"고 지적 — 실제로 DART 원문 THEAD가
COLSPAN/ROWSPAN(+ 종종 `ENG` 속성)으로 표 구조를 이미 명시적으로 선언하고 있음을
원문 5개사·6개 형태로 확인(설계문서 §1). 근본적으로 추측 자체를 없애는 재설계.

**설계**: `docs/plans/report_lines_header_grid_column_map_design_2026-09-09.md`.
`parse_header_columns(table)`가 THEAD를 표준 HTML COLSPAN/ROWSPAN 규칙으로 그리드
해석 → 각 열의 헤더텍스트 스택(위→아래)에서 기간패턴("제 N 기"/"당기"/"전기"/"전전기")을
찾아 `position→(period_rank, subtype)` 맵을 만든다. `select_by_header_columns()`가
그 맵 + `extract_rows(..., keep_all_amount_cells=True)`(위치보존 원시배열)로 데이터
행을 직접 인덱싱 — subtype 구분이 있는 그룹(H1/Q3 3개월/누적)은 cumulative만 채택(값이
없어도 3개월로 대체 안 함, R85와 동일 원칙), subtype 전부 None인 병합군(삼성생명류
명세/소계)은 값 있는 열 하나만 채택(2개 이상이면 R6 원칙대로 보류). 실패(THEAD 없음·
기간패턴 인식 실패·같은 subtype 중복이라 텍스트만으론 구분 불가)하면 `None`을 반환해
`_emit_section_lines()`가 기존 cum_map/multicol/else 3갈래(R85~R87 가드 포함)로 완전히
그대로 폴백 — 이 세션에서 검증 못한 표는 안 건드린다.

**실측 카탈로그(5개사)**: 삼성전자 2019FY CF(순수 3열)·2017Q1 CF(순수 4열, R87 대상
바로 그 표)·2025H1 IS(ROWSPAN 라벨+COLSPAN=2×2기간+3개월/누적 하단행, `ENG="CFHY"`/
`"THREE MONTH"` 등 영문 태그까지 확인)·삼성생명 2016FY CF(COLSPAN=2, 하위 구분텍스트
없는 병합군)·대한제분 2026H1 CF(순수 2열, TE 렌더링). 전부 `parse_header_columns`가
정확히 해석함을 확인(2026-09-09 세션 실측 스크립트).

**구현 중 발견·수정한 결함 2건** (실측 회귀로 잡음, 최종 코드엔 반영 완료):
1. **라벨열 과다흡수** — 처음엔 "기간패턴 없으면 라벨"로 라벨열 경계를 계속 늘렸는데,
   그러면 라벨 바로 다음의 **명시적 "주석" 열**(예: 한화손해보험 IS `<TH>주석</TH>`)까지
   라벨로 흡수해 `position`이 `keep_all_amount_cells=True`의 실제 데이터 배열과 한 칸씩
   어긋났다(실측: 한화손해보험·코리안리 등에서 값 전체가 한 칸씩 밀림). **수정**: 라벨열은
   항상 정확히 1개(`cells[0]`) — `keep_all_amount_cells=True`가 라벨로 취급하는 것과
   정확히 같은 규칙으로 고정. 주석열은 `is_note=True`로 자기 위치를 그대로 갖고 안전하게
   제외된다.
2. **텍스트로 구분 불가한 중복 하위열** — K-GAAP 구서식(2003년대, 00132725 SB성보
   2003Q3 IS)은 "3개월"/"누적" 아래 **다시** COLSPAN=2 하위열이 있는데 그 하위열 텍스트가
   둘 다 "금액"으로 동일해 헤더만으론 어느 쪽이 진짜 금액칸인지 구분이 안 된다. 처음엔
   그냥 첫 번째를 골랐는데, 그러면 R31이 고쳐놓은 정답(당기 -466,274,000)이 다시 유실됐다
   (`test_hyphen_negative_gate_r31.py` 회귀로 발각). **수정**: `subtype`이 있는데(예:
   "cumulative") 같은 `(period_rank, subtype)`에 열이 2개 이상이면 표 전체를 인식 실패로
   보고 폴백(subtype=None인 병합군의 정상적 중복은 예외 — 그건 애초에 `select_by_header_
   columns`가 "값 있는 열 하나" 로직으로 안전하게 처리하므로 구분해서 둠).
3. (버그, 커밋 전 발견) — cumulative 열이 있는데 그 특정 행에서 값이 `None`(진짜 결측)일
   때 `select_by_header_columns`가 결과 딕셔너리에 `None`을 그대로 넣던 것을 수정(진짜
   결측은 결과에서 아예 빠져야 `for col_idx, amount in pairs: if amount is None: continue`
   가 정상 동작).

**통합 지점**: `fin2/extract/report_lines.py::_emit_section_lines()` — `statement in
("BS","IS","CF")`에서만(SCE는 열이 기간이 아니라 자본 구성요소 축이라 기존과 동일 제외)
표 하나당 한 번 `parse_header_columns()`를 시도, 성공하면 그 표의 `n_cols`/추출 모드
(`keep_all_amount_cells=True`)와 행별 `pairs` 선택을 전부 이 경로로 대체. 실패하면
`cum_map`/`multicol`/`else`(R85~R87) 완전히 그대로. EPS(`_emit_eps_lines`, R85)는 이번
스코프에서 안 건드림(다음 확장 지점).

**회귀테스트**: `fin2/tests/test_header_grid_column_map_r88.py`(신설, 8개) — 합성 XML로
§1 카탈로그 6개 형태(순수 N열·2단 3개월/누적·병합군·주석열·THEAD없음·K-GAAP 중복하위열)
각각 잠금 + `select_by_header_columns`의 cumulative 우선/병합군 단일값 채택 규칙. 기존
`fin2/tests/test_report_lines.py`의 R85~R87 실측 파일 테스트 전부가 이제 이 신규 경로를
그대로 타면서 무회귀 확인(별도 파일 재작성 불필요 — 답이 같으면 그게 핵심 회귀가드).
`pytest tests/ fin2/tests/` 937 passed(신규 8개 포함, 무관 기존실패 2건 그대로, 회귀 0).

**미조치**: THEAD 없는 구형(K-GAAP TD-only 무헤더) 표 지원, EPS 통합, 전사 census(THEAD
있는 표 중 `parse_header_columns`가 `None`을 반환하는 비율) 전부 다음 세션 확장 지점
(설계문서 §7). 이번 세션은 사용자가 직접 삼성전자(`rcpNo=20170515003806`) 재적재로
확인.

---

## R89. 헤더 먼저 읽기(R88) 확장 — `parser/xml/table_extractor.py` §7(THEAD 없는
XML)·`fin2/extract/html_viewer.py`(DART 웹뷰어) — 2026-09-10

**배경**: R88이 XML `<THEAD>` 기반으로 국한됐던 헤더그리드 방식을, 사용자 지시("이후
표 형태로 읽는 파서 부분에 모두 헤더 파싱 부분을 추가")로 나머지 표 파서 전체로
넓히는 첫 트랙. 설계: `docs/plans/header_first_parsing_expansion_design_2026-09-10.md`
— 대상별 적용 가능성이 다름을 먼저 확인(표 마크업 자체가 없는 PDF 주경로는 대상 제외,
`biz_section.py` 계열은 이미 자체 헤더선독 보유라 별도 트랙, 주석/주식수류는 스코프
제외) — html_viewer.py를 최우선 대상으로 확정.

**① XML §7 확장(`parser/xml/table_extractor.py`)** — R88 설계문서 §7이 다음 세션
확장 지점으로 찜해뒀던 것: `<THEAD>`가 없는 구서식(pre-2015 K-GAAP 등)에서 헤더행이
`<TBODY>` 선두 `<TR>`(들)로 섞여 오는 경우, 그 TR들을 THEAD 대용으로 모아 R88과 같은
경로를 태운다.
- `_looks_like_header_row(cell_texts)` 신설 — 라벨열 제외 나머지 셀 중 **하나라도
  진짜 금액처럼 보이면**(`_NUMBER_PATTERN` 매치) 즉시 데이터행으로 판정(False), 그 외
  기간패턴(`_PERIOD_KEY_RE`)이나 서브타입 토큰(3개월/누적)이 하나라도 있으면 헤더행
  (True) — 모양이 아니라 내용으로 판정(R6 원칙과 같은 맥락). "제28기" 류는 문자와
  숫자가 섞여 있어 `_NUMBER_PATTERN`(순수 금액 패턴)에 안 걸린다.
- `_headerless_header_trs(table)` 신설 — `<TBODY>` 선두 TR들 중 `_looks_like_
  header_row`에 걸리는 것만 모으고, 처음으로 안 걸리는(=진짜 데이터) TR을 만나면
  멈춘다.
- `parse_header_columns()`의 그리드→`HeaderColumn` 해석 부분을 `_columns_from_grid()`
  로 추출(THEAD 경로와 §7 경로가 공유 — 로직 중복 없음). 실패 조건·안전원칙은 R88과
  동일(모르는 헤더 모양이면 `None` → 기존 cum_map/multicol/else 로 완전 폴백).
- **적용 범위**: `parse_header_columns()`가 `report_lines.py`에서 이미 **모든**
  BS/IS/CF 표에 무조건 호출되므로(pre-2015 뿐 아니라 THEAD 없는 모든 XML 표), 이
  확장은 실질적으로 전사 적용된다 — 안전원칙(내용 기반 엄격 판정 + 실패시 완전 폴백)
  덕에 새 오탐 위험은 낮지만, 전사 census는 아직 안 함(§미조치).

**② `fin2/extract/html_viewer.py` 헤더그리드 통합** — 레이아웃 B(행별-TR형) 표에
`<THEAD>`(없으면 §7과 같은 TBODY-선두 내용판정)를 먼저 읽어 위치→회계기간 맵을
만들고, 성공하면 옛 "숫자로 파싱되는 첫 셀=당기" 값-위치 휴리스틱을 완전히 우회한다.
- `_resolve_bs4_header_grid()`(COLSPAN/ROWSPAN 그리드, `table_extractor.py::
  _resolve_header_grid()`와 같은 알고리즘을 BeautifulSoup Tag용으로 독자 재구현 —
  `fin2/extract/pdf.py`의 `_TITLE_TOKENS` 처럼 서로 다른 트리 API는 각자 사본을
  갖는 이 프로젝트 기존 관례를 따름), `_detect_header_trs_bs4()`, `_parse_header_
  columns_bs4()` 신설 — 그리드→`HeaderColumn` 해석은 `table_extractor.py::
  _columns_from_grid()`를 그대로 import 해 공유(①과 같은 함수, 중복 없음).
- **★실측 확인** — 이 파일의 기존 테스트 fixture(동성제약·제일기획·DB증권류) 전부가
  이미 `<THEAD>`를 갖고 있었다(모듈 기존 docstring이 "THEAD가 없다"고 잘못 적어뒀던
  것을 이번에 정정). 구현 중 DART 라이브 재확인(rcpNo=20010814000859, 제일기획
  00148276 연결재무제표)으로 THEAD 존재를 직접 재확인.
- **★부수 발견 — 잠복 버그 1건**: 위 라이브 재확인 중, 제일기획 연결 2001H1의
  연결대차대조표(THEAD="과목/제28기/제27기/제 26 기")는 "부채·외부주주지분 및
  자본총계" 등 **모든 행에서 제28기(당기)·제27기(전기)가 진짜 대시**(그 시절
  연결재무제표를 당기/전기는 작성하지 않고 참고용 과거 2개년만 실음)이고, 값은
  제 26 기(전전기) 칸에만 있었다. 옛 값-위치 휴리스틱("숫자로 파싱되는 첫 셀")은
  이 전전기 값을 **당기로 오채택**하고 있었다 — R86/R87과 같은 클래스의 결함(진짜
  결측을 다른 기간 값으로 몰래 메꿈). 기존 테스트(`test_dash_placeholder_columns_
  are_skipped_to_reach_real_value`)가 이 오채택 값(259,653,479,057)을 "정답"으로
  기대하고 있었던 것도 같이 발견해 정정(`test_dash_columns_genuinely_missing_are_
  not_backfilled_from_older_period`로 개명, 기대값을 (None,None,None)으로 수정 —
  헤더그리드 경로는 이제 이 행을 정직하게 결측으로 남긴다, R3 원칙).
- **3개월/누적 갭 해소**: 모듈이 자인하던 기존 갭("interim IS/CF 3개월 vs 누적
  구분을 안 함")이 헤더그리드 경로에서 R85와 동일 원칙(cumulative 우선, 없어도
  3개월로 대체 안 함)으로 해소됨을 합성 fixture로 확인.

**회귀테스트**: `fin2/tests/test_header_grid_column_map_r88.py`에 §7 확장 3건 추가
(THEAD 없이 TBODY 선두 헤더행 단일행/2행(ROWSPAN+COLSPAN)/마커 없는 행 불흡수).
`fin2/tests/test_html_viewer.py`에 2건 추가(헤더그리드 경로가 실제로 당기 열을
정확히 고름, cumulative 우선 채택) + 기존 1건 정정(위 잠복 버그). `pytest tests/
fin2/tests/` 942 passed(무관 기존실패 2건 그대로 — `test_lxintl_facility_table_
dropped`·`test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix`, 둘 다 이번
변경 전에도 동일 재현되는 사전 존재 결함임을 `git stash`로 직접 대조 확인, 회귀 0).

**미조치**: html_viewer.py Track C 잔여 93건 census 재실행(이번엔 실측 1건 + 합성
fixture로만 검증), XML §7 확장의 전사 census(THEAD 없는 표 중 새로 성공하는 비율),
`biz_section.py`/`sales_section.py`/`order_backlog.py` 자체 헤더선독 로직과의 중복
통합, PDF `extract_tables()` 폴백 경로 — 전부 설계문서 §4/§6 순서대로 다음 세션
확장 지점(사용자 결정 필요, 설계문서 §8).

---

## R90. `fin2/extract/shares.py` "단위 : 천주" 미인식 ×1000 축소 +
`scripts/fin2_market_cap_daily.py`/`dq_assertions.py` — std_v2 DROP 이후 시총
파이프라인 8일 조용한 정체 (2026-09-09, 코드는 이전 세션 작성·이번 세션 검토·문서화·커밋)

**배경**: 계층2 검토 캠페인 진행 중 사용자가 "시총 오류 확인해봐"로 조사 지시 →
`stock_prices.market_cap` 전종목 정체(9/1~) 조사에서 **원인이 다른 두 갈래**로 갈렸다.
이 문서에 규칙 번호가 없던 채로 코드만 작성돼 있었음(`shares.py`가 스스로를 "R86"이라
잘못 적어뒀던 것도 이번에 R90으로 정정 — R86은 이미 `_emit_section_lines()` else분기
절삭 규칙이 선점).

**① `shares.py` "천주" 단위 미인식** — 표 헤더가 "(단위 : 천주, %)"인 서식(현대로템·
크린앤사이언스·에스텍·서산·해성디에스·파이버프로·CJ씨푸드 등 다수 실측)에서 발행주식수
파서가 인쇄된 숫자를 "주" 단위로 그대로 채택해 정확히 1000배 축소 저장되고 있었다
(현대로템 실측: 표에 "200,000" 인쇄, 비고란 "정관상 발행 가능한 주식 총수 : 2억주"로
200,000×1,000=200,000,000 검증, DART 라이브 API 대조로 확인).

**함정** — "(단위 : 천주)" 캡션 자체를 그대로 믿으면 안 된다. 일승(01396676)·한일철강
(00163196)은 캡션이 "천주"인데 실제로는 표에 인쇄된 숫자가 이미 "주" 단위다(캡션만
믿었으면 새 불가값을 만들 뻔함). 그래서 `_table_multiplier()`는 프로즈("...총수는
[보통주] N주")·비고("N억주")의 평문 숫자를 Ⅰ(발행할)/Ⅱ(현재까지 발행한) 행과 **대조**해
표 전체 배수를 정하고, 교차검증 대상이 없을 때만 캡션을 그대로 신뢰한다(Ⅳ는 산술값이라
프로즈에 거의 안 나와 그것만 대조하면 못 잡는다 — 한일철강 실측). R0/R6 원칙(짐작 금지,
근거 있는 것만 바꾼다) 그대로.

**② `fin2_market_cap_daily.py` — std_financials_v2 DROP(2026-09-01) 이후 8일간 조용한
크래시** — 이 스크립트가 이미 삭제된 `std_financials_v2`를 계속 조회해 매일
`UndefinedTable`로 실패하고 있었는데, `nightly_valuation_refresh.py`의 단계별
try/except(파이프라인 전체를 막지 않으려는 의도적 설계, R8/작업방식과 같은 맥락)가 이
실패를 삼켜 `stock_prices.market_cap`/`shares_out` 전종목이 2026-08-31 이후 정체된
채로 아무도 몰랐다. **수정**: 소스를 `std_financials_v3`로 전환 — v3엔 `version`/
`is_discrete`/`is_stub` 컬럼이 없다(PK 중복 자체가 없어 그 필터가 애초에 불필요,
`dq_assertions.py::check_completeness` 주석 참고), `basis` 역할은 `statement_type`
(separate/consolidated) 컬럼이 대신한다.

**재발 방지**: `dq_assertions.py`에 `market_cap_stale`(WARN) 신설 — 종목별 최신
시세일과 최신 market_cap 갱신일의 격차(공휴일 하드코딩 없이 상대 비교, 2일 초과)로
잡는다. ★종목별로 봐야 한다 — 전체 `max(trade_date)` 하나만 보면 단 1종목만 갱신돼도
"정상"으로 오판된다(이번 사고가 8일간 안 잡힌 이유이기도 함, 이 체크 만들 때 실측 확인).

**검증**: `pytest tests/ fin2/tests/` 942 passed(무회귀, R89와 같은 실행) —
`test_shares_unit_multiplier_r90.py`(신설, 6개) 통과. `fin2_market_cap_daily.py`/
`dq_assertions.py`는 DB 마이그레이션 스크립트/쿼리라 별도 pytest 단위테스트 없음(기존
관례와 동일 — SQL 자체가 실행 검증).

**미조치**: 8일 정체 기간(2026-08-31~2026-09-09) 동안의 `stock_prices.market_cap`
과거값 소급 재계산은 별도 수동 실행 필요(스크립트 자체는 멱등이라 그냥 재실행하면
최신 시세 기준으로 갱신됨 — 과거 특정 일자 시점 스냅샷을 쓰는 소비처가 있다면 그
구간만 백필 검토).

---

## R92. `parser/xml/dart_xml_parser.py::_parse_xml_file()` — DART archive 원문
자체의 인코딩 손상(리터럴 '?' 치환) 감지 (2026-09-12)

**배경**: 솔트웨어(01390399) `[기재정정]반기보고서` r20220802000208 — 계층2가 0행을
냈는데 사용자가 원문에 별도재무제표가 있다고 확인. 조사 결과 **원본 XML 자체가
DART OpenDART `document.xml` archive 단계에서 한글을 리터럴 '?'(0x3F)로 치환한 채
손상**돼 있었다(384KB 중 42,184바이트=11%). DART API에서 재다운로드해도 **바이트까지
완전 동일**함을 직접 확인 — 저희 다운로드/인코딩 처리 문제가 아니라 DART 서버측
archive 손상(R76 "2001년 접수분 인코딩 손상"과 같은 계열이 2022년 필링에서도 재현).
설계: `docs/plans/parser_source_fallback_cascade_design_2026-09-12.md`.

**수정**: `_parse_xml_file()`이 파싱 시도 **전에** 원문 바이트의 '?' 비율을 재서
1%(`_CORRUPTION_QMARK_THRESHOLD`) 초과면 `logger.warning` 남기고 파싱 없이 `None`
반환. 임계치는 DB 표본 200건(2000~2025년 분포) 실측으로 검증 — 정상 파일 비율 최대
0.0001(0.01%), 손상 파일 0.1098(11%), 1000배 격차라 오탐 여지 거의 없음. 한글이 이미
파괴된 문서는 인코딩을 아무리 잘 감지해도 복구가 안 되므로(계정명 자체가 소실),
시도조차 안 하고 바로 걸러 다른 소스(PDF/HTML)로 넘어갈 신호를 남긴다.

**복구 경로**: `scripts/recover_and_report_corrupted_xml_2026-09-12.py`(신규) —
`collector/pdf_lines_sync.py::recover_one()`(기존 Track C 경로 재사용, HTML→PDF
신뢰도 조정 `reconcile()`)로 PDF/HTML 복구 시도. 솔트웨어는 PDF 텍스트 자체는
멀쩡했으나(`pdfplumber`로 확인) 좌표기반 추출값이 BS 항등식을 만족 못 해(reconcile()
T1 미달) 자동채택 안 되고 `report_recon_candidates`에 적재 — 스크립트가 그 자리에서
DART 링크+사유를 사람이 읽을 형태로 출력한다(`--report-pending`으로 언제든 재조회).

**의도적으로 안 한 것**: 이 복구 경로를 `sync_pdf_recovery()`(Category C 1999~2003
하드코딩)에 상시 배선하지 않음 — 손상 사례가 아직 1건뿐이라 독립 스크립트로 필요할
때 호출하는 쪽을 택함(`docs/plans/parser_source_fallback_cascade_design_2026-09-12.md`
§4 결정 참고). raw_report 전체 상시 스캔도 안 함 — `_parse_xml_file()` 파싱 시도
시점에만 검사(저비용).

**검증**: `pytest tests/ fin2/tests/` 959 passed(R91 이후 953 대비 +6 신규, 기존 무관
실패 2건 그대로). `test_xml_corruption_detection.py` 순수로직 4건 + 솔트웨어 실제
파일 종단 테스트 1건.

---

## R93. `fin2/extract/pdf.py` — 헤더 구조 우선 파싱 재설계: 주석번호 열 오인식 +
"반기" 복합어로 인한 앵커 누락 (2026-09-12)

**배경**: R92로 솔트웨어 20220802000208의 원본 XML 손상을 확인해 PDF 폴백으로
전환했는데, 사용자가 그 PDF 강제적재 CSV를 원문과 대조해 "표 헤더 구성(과목/주석/
당반기말/전기말)을 파싱하는 부분이 없는 것 같다"고 지적 — 실제로 `fin2/extract/
pdf.py`는 헤더를 전혀 안 읽고 텍스트 줄의 숫자를 순서대로 컬럼에 배정하는 "any-column"
방식이었다(모듈 자체 docstring에 명시). 설계: `docs/plans/pdf_header_aware_table_
parsing_redesign_2026-09-12.md`.

★사용자가 원래 의심한 "행 병합"(줄바꿈 유실)은 이 파일에서 실제로는 안 일어났다
(pdfplumber 재추출 텍스트는 줄바꿈 멀쩡) — 헤더 우선 파싱 게이트를 실제로 구현해
돌려보고서야 드러난 **진짜** 원인 2가지, 둘 다 "반기"(半期)라는 단어 하나 때문:

1. **주석번호 열 오인식** — "현금및현금성자산 4,5,6 2,351,294,869 2,403,931,716"에서
   "4,5,6"(주석 참조번호 목록)이 콤마 있는 숫자토큰이라 `_NUM_TOKEN_RE`가 금액과
   구분 못 해 그대로 집었다(컬럼이 밀려 실제 값 대신 "456"/"45,718" 같은 엉뚱한
   값 산출). **수정**: `_looks_like_real_amount()` 신설 — 진짜 금액은 천단위 콤마
   그룹(첫 그룹 1~3자리, 나머지 정확히 3자리)인데 주석번호 나열은 자릿수가
   불규칙(1~2자리)하다는 차이로 구분.
2. **"반기" 복합어로 인한 앵커 누락(더 심각)** — 기존 `_PERIOD_MARK_RE`("제 N 기"/
   "제 N 분기"만 인식)는 "제4(당)반기"("반"이 "기" 앞에 낌)를 못 잡는다. 이
   반기보고서는 포괄손익계산서·자본변동표·현금흐름표 제목이 전부 이 형태를 써서
   **앵커가 하나도 안 잡혔다** — 유일하게 잡힌 BS 앵커의 리전이 다음 앵커 없이
   문서 끝까지 뻗어나가, 현금흐름표·주석의 합계·소계까지 전부 "재무상태표" 값으로
   섞여 들어갔다(사용자가 발견한 CSV 오염 행들의 진짜 정체). **수정**: 헤더 컬럼
   수를 세려고 만든 `_HEADER_PERIOD_MARK_RE`("반기말"/"분기말"/"반기"/"분기"까지
   인식, `_PERIOD_MARK_RE`의 상위집합)를 `_find_anchors()`의 앵커 확정에도 재사용.

**헤더 우선 파싱 게이트 본체**: `PdfTableHeader`/`_parse_pdf_table_header()` —
앵커 리전 선두에서 "과목 [주석] 제N(당/전)기…" 헤더 줄을 찾아 기간 컬럼 수를 읽는다
(못 찾으면 `None`, R6). 데이터 줄의 숫자 개수가 이 컬럼 수를 **초과**하면(병합·주석
오염 등의 신호) 격자 폴백(`extract_tables()`)을 시도하고, 격자 결과도 여전히 초과하면
그 줄은 결측 처리한다(결측이 오염보다 낫다) — `parser/xml/table_extractor.py::
parse_header_columns()`(R88/89)와 같은 철학.

**종단 검증**: 수정 전 27개 사실(대부분 다른 표/주석 값이 섞여 항등식 불성립) → 수정
후 별도 BS 17행(자산총계=부채총계+자본총계 정확히 일치) + 별도 CF 11행(현금흐름표
전용 앵커로 정상 분리)으로 정리. **`reconcile()`이 이제 이 basis를 T1(확신)로 자동
채택**(`decision='pdf'`, 이전엔 사람 확인 대기열行) — 강제 우회 없이도 자동 파이프라인
신뢰 수준에 도달.

**검증**: `pytest tests/ fin2/tests/` 966 passed(R92 이후 959 대비 +7 신규, 기존 무관
실패 2건 그대로). 신규 테스트 8개(`fin2/tests/test_pdf.py`) — 주석번호 오인식 정오탐,
헤더 파싱 성공/None, 컬럼수 불일치 판정, "반기" 앵커 회귀, 실제 솔트웨어 PDF 종단
테스트 포함.

**Phase 2(하위기간 열까지 헤더가 완전히 기술 — 3개월/누적 2단 헤더 등)는 범위 밖** —
이번에 실제 발견된 문제는 전부 Phase 1(헤더 파싱 + 검증 게이트) 안에서 해결됨.

★**정정(R94 참고)**: 이 결론은 틀렸다 — "3개월/누적 2단 헤더"는 **바로 이 필링의
IS(별도 손익계산서)에 실제로 존재**했다(BS/CF만 확인하고 IS는 확인 안 해서 놓침).
Phase 2 로 미룬 게 아니라 발견을 못 한 것이었다. R94에서 실제 발견·수정.

---

## R94. `fin2/extract/pdf.py` — 손익계산서가 통째로 0행이었던 3중 원인: 서브컬럼
헤더 미인식 + 적자기업 앵커라벨 누락 + BS 전용 부호규칙의 IS/CF 오적용 (2026-09-12)

**배경**: R93 종단검증에서 "별도 BS 17행 + CF 11행"까지만 확인하고 넘어갔는데,
사용자가 "손익계산서는 왜 누락되었나?"라고 물어서 조사 — R93이 "Phase 2(3개월/누적
2단헤더)는 범위 밖, 이번 사례엔 없었음"이라고 기록했던 게 **틀렸다**: 이 필링의
IS(요약반기포괄손익계산서, page 16)에 정확히 그 2단 헤더가 있었는데 BS/CF만 원문대조
하고 IS는 확인을 안 해서 놓쳤다. 원문에는 멀쩡히 있는데 계층2가 0행으로 적재한
케이스 — 사용자 지시로 "BS/IS/CF 무조건 3개 다 있어야 하는데 없는 경우"를 원칙적으로
의심하게 된 계기.

**원인 ①: 헤더 서브컬럼("3개월/누적") 미인식** — IS 헤더는 2단 구조다: 1단
"제4(당) 반기  제3(전) 반기"(기간마커 2개), 2단 "과 목 주 석  3개월 누적 3개월
누적"(각 기간이 3개월/누적 두 컬럼으로 재분할, 실제 데이터 컬럼 4개).
`_parse_pdf_table_header()`는 1단 줄만 보고 `n_period_cols=2`로 확정했다 — R93이
갓 도입한 최종 안전망(`len(nums) <= header.n_period_cols`)이 실제 4컬럼 데이터줄을
전부 "헤더선언 초과"로 오판, IS 전 항목이 결측 처리됐다. **수정**: 기존
`_is_interim_cumulative(region)`(interim IS/CF의 누적열 채택용으로 이미 있던 탐지
함수)를 재사용해, 헤더 확정 시 이 신호가 있으면 `n_period_cols`를 2배로 잡는다.

**원인 ②: `_ANCHOR_LABELS["IS"]`가 흑자 워딩만 화이트리스트에 있었음** — 원인①을
고쳐도 여전히 0행이었다. 추적해보니 이 회사(적자)가 "영업손실"/"당기순손실"을 쓰는데
`_ANCHOR_LABELS["IS"] = ("매출", "영업이익", "당기순이익", "분기순이익", "반기순이익",
"영업수익")`엔 흑자 워딩만 있어 "영업수익" 1건만 걸리고(≥2건 필요) 게이트를 못
넘었다 — `_region_has_anchor_labels()`/`_table_has_anchor_labels()`가 이 리전을
"엉뚱한 표/false-positive 앵커"로 오판해 텍스트 경로도 격자 폴백도 둘 다 스킵. 이
게이트의 목적 자체는 정당하다(제목 문자열만 보고 앵커를 잡으면 주석 속 문장 언급까지
앵커로 잡힐 위험 — 위 R93/이전 실측 "재무상태표의 현금및현금성자산입니다" 오탐 참고).
문제는 화이트리스트가 **흑자만** 대칭이 안 맞았던 것. **수정**: 각 흑자 라벨의 적자
대응어(영업손실/당기순손실/분기순손실/반기순손실)를 대칭으로 추가.

**원인 ③(가장 위험 — 부호소실, 격자폴백 경로에만 존재)**: 원인①②를 고치자 IS 7행이
나왔지만 **부호가 다 사라져 있었다**(영업손실 -68,052,797 → 68,052,797로 양수 저장).
추적: `_parse_numline_tokens()`의 "로마숫자/괄호번호 헤더행은 괄호를 벗기고 양수로
읽는다" 규칙 — 원래 pre-2015 K-GAAP BS의 "Ⅰ.유동자산 (45,700,051)"(괄호=하위 항목
합계의 **미리보기**, 진짜 음수 아님) 전용으로 만들어진 관례인데, `statement` 구분 없이
라벨 패턴(로마숫자로 시작)만으로 적용되고 있었다. IS의 "Ⅲ.영업손실"/"Ⅷ.당기순손실",
CF의 "Ⅰ.영업활동으로 인한 현금흐름"도 로마숫자로 시작하지만 이건 미리보기가 아니라
**그 자체가 최종 계산된 소계**이고 괄호는 **진짜 음수**다. 텍스트 경로
(`_parse_single_line`)는 이미 `len(nums)==1`(단일값)일 때만 이 관례를 적용하도록
좁혀져 있어 문제가 없었지만, 격자 폴백 경로(`_iter_data_lines_from_table_rows` →
`_parse_numline_tokens`, "같은 헤더 행 안에서도 괄호 유무가 값마다 들쭉날쭉하다"는
2026-09-06 실측으로 그 제약이 풀린 버전)는 컬럼 수와 무관하게 걸려 있었다. ★이 버그는
**IS 전용이 아니다** — 같은 필링의 CF "Ⅰ.영업활동으로 인한 현금흐름"도 격자폴백을
타면서 이미 부호를 잃고 있었다(원인①②를 고치기 전, 즉 R93 커밋 시점부터 잠복해
있던 버그 — IS 조사 과정에서 우연히 같이 드러남). **수정**: `_parse_numline_tokens(
label, tokens, statement="BS")`에 `statement` 파라미터 추가, `is_header` 판정을
`statement == "BS"`일 때만 발동하도록 좁힘. 호출측 3곳(`_iter_data_lines_from_
table_rows()`, `_iter_data_lines_multiline()`, 그리고 이 둘을 부르는
`facts_from_text()`)에 `anc.statement`를 명시적으로 관통시킴 — 인자를 안 주는 기존
BS 전용 호출부는 기본값 "BS"로 하위호환.

**종단 검증**: 별도 IS 7행(영업손실 -68,052,797/당기순손실 -24,180,887 등, 부호 정상)
+ 별도 CF의 "영업활동으로인한현금흐름"도 -52,636,847로 정정됨. 두 항등식 모두 정확히
성립: `영업손실 + 금융수익 - 금융원가 = 세전손실`(EBT), `기초현금 + 현금의증가 =
반기말현금`(CF 순증감) — R93 시점엔 후자가 성립 안 했었다(부호가 틀려서).

**검증**: `pytest tests/ fin2/tests/` 970 passed(R93 이후 966 대비 +4 신규, 기존
무관 실패 2건 그대로). `fin2/tests/test_pdf.py` 신규 4개(서브컬럼 배가·비발동 회귀,
적자 워딩 앵커 게이트, BS 전용 부호규칙 statement 분기) + 솔트웨어 실제 PDF 종단
테스트에 IS 부호·CF 항등식 단언 추가.

**교훈**: "행수가 나왔다"만으로는 부호소실 같은 조용한 오염을 못 잡는다 — 항등식까지
검산해야(R6 계열 전체의 근본 이유). 그리고 "이번 사례엔 없었다"는 **원문을 실제로
다 훑었을 때만** 유효한 결론이다 — BS/CF만 보고 IS는 확인 안 한 채 "Phase 2는 범위
밖"이라고 적었던 게 이번 재발의 직접 원인.

---

## R91. `collector/filing_collector.py` — 제목 태그 없는 정정본 회계연도 오판정 +
`fin2/extract/report_lines.py` era 라우팅 편방향 무재시도 (2026-09-12)

**배경**: 계층2 2015+ 전수 재적재 배치(`reload_report_lines_2015plus_2026-09-12.py`)
중 "0행(보류)" 표본 원문대조에서 발견. 진원생명과학(00118521) `[기재정정]사업보고서`
r20220908000421 — 사용자가 원문에 별도재무제표가 정상적으로 들어있음을 확인했는데
계층2가 0행을 냈다. 설계문서: `docs/plans/era_routing_fallback_and_fiscal_year_
correction_parsing_design_2026-09-12.md`.

**근본원인 체인**: `report_nm = "[기재정정]사업보고서"`(★"(YYYY.MM)" 꼬리표 없음) →
`_parse_fiscal_info()` 1차(제목 태그) 실패 → 2차(유일한 폴백, 접수일 기반 추정) →
접수일(2022-09-08)로 fiscal_year=2022 확정. 실제로는 원문 CORRECTION 섹션에
"정정대상 공시서류의 최초제출일: 2006.03.31" = 제30기(2005 회계연도) 대상이라고
명시돼 있었다(안 읽었을 뿐). `filings.fiscal_year=2022`가 저장되자
`extract_report_lines()`가 `report_fiscal_year(2022) > _PRE2015_ROUTING_MAX_FY(2010)`
로 2015+ 전용 파서로만 라우팅했고, 실제 원문은 2005년식 구K-GAAP 서식이라 표를
하나도 못 찾아 0행 → **다른 시대 파서로 재시도하는 코드가 없어 그대로 종료**.

**두 군데 모두 "1차 실패해도 검증·재시도 없이 그대로 확정"하는 같은 패턴의 갭**이었다:

1. **입력측** — `relabel_corp_filings()`의 `pe is None`(제목 태그 없음) 분기에,
   정정본(`_is_amendment`)이면 원문 CORRECTION 섹션의 "최초제출일"을 파싱해 재확인하는
   3차 방법 추가(`_fiscal_period_from_correction_section()`, `_CORRECTION_ORIG_DATE_RE`).
   ★"최초제출일"은 결산기말이 아니라 **원본의 접수일**이다 — 그 날짜를 그대로
   `compute_fiscal_year_period()`에 넣으면 또 틀린다(원본도 결산기말 후 ~3개월 뒤에
   접수되므로). 대신 `_parse_fiscal_info()`의 기존 "접수일 기반 추정" 폴백을 **원본
   접수일**에 대해 다시 태운다 — 원본은 정상적으로 대상 기간 직후에 접수됐을 것이므로
   그 폴백의 전제가 원본 접수일 기준으로는 성립한다(정정본 자신의 접수일 기준으로는
   수십 년 차이가 나 성립하지 않았을 뿐).
2. **추출측** — `_detect_pre2015_body_statement_tables_merged()`(pre-2015→2015+
   방향, R70/2026-08-10 기존 구현)는 이미 섹션코드 단위 병합-폴백이 있었으나, **반대
   방향**(2011+ 라우팅, `else` 분기)엔 폴백 자체가 없었다. `_merge_missing_codes()`
   헬퍼로 그 병합 로직을 범용화해 재사용하고, `else` 분기에 "완전히 0행일 때만" 반대
   방향(pre-2015 탐지기) 폴백 추가 — pre-2015→2015+ 방향과 달리 이 방향은 전수 실측이
   없어 섹션코드 단위 상시 병합까지는 가지 않고 보수적으로 시작(폴백 성공 시
   `logger.warning`으로 fiscal_year 오판정 의심 신호를 남김, 조용히 성공 처리 안 함).

**부수 안전망**: `scripts/dq_assertions.py`에 `filings_isfinal_grain_duplicate`(ERROR)
신설 — 같은 (corp_code, report_type, fiscal_year, fiscal_period)에 `is_final=True`
2개 이상 있으면 걸린다. ★naive 4필드 그룹핑은 **380건**이 걸리는데, 그중 342건은
결산월 변경으로 인한 **정상 stub 연도 공존**(`relabel_corp_filings()` 자신의
그레인키 설계가 이미 이걸 정상으로 취급 — period_end_date 가 다르면 fiscal_year
라벨이 같아도 둘 다 final 이 맞다)이라 `period_end_date IS NULL 인 행이 낀 경우만`
으로 조건을 좁혀 진짜 신호 **38건**만 남겼다. 이 38건은 전부 "태그 없는 정정/첨부정정
(대부분 `[첨부정정]`, 원본과 며칠 차)이 태그 있는 형제와 그레인이 갈라짐" — 같은
근본 메커니즘의 더 흔한 하위유형이나, §1 트리거(`_is_amendment`)가 첨부정정
(`_is_attachment_amendment`)까지는 안 잡아 이번 수정으로 안 고쳐진다. **후속
백로그로 이월**(부록 C 참고).

**검증**: `pytest tests/ fin2/tests/` 943 passed(무회귀 — 나머지 2건 실패는 기존
무관 실패, `git stash`로 사전 확인). `fin2/tests/test_report_lines.py`에 진원생명과학
실제 파일로 §2 폴백 단독 검증 회귀 테스트(§1 없이 **일부러 틀린** fiscal_year=2022를
넘겨도 폴백만으로 617행 복구) + `_merge_missing_codes` 단위 테스트.
`tests/test_filing_collector_correction_recheck.py`(신규)에 정규식 단위 테스트 3개 +
실제 DB 연동 테스트. 원본 사고 건은 이 세션에서 `relabel_corp_filings(s, "00118521")`
직접 실행으로 DB 즉시 정정(fiscal_year 2022→2005, is_final 충돌 해소,
`layer2_review_queue` 스테일 행 삭제) — `extract_report_lines()`를 정정된 fiscal_year
로 재호출해 617행 정상 추출 확인.

**미조치**: 38건 백로그의 명시적 백필(해당 corp 들에 `relabel_corp_filings()` 직접
호출) — `relabel_corp_filings()`는 그 corp가 **오늘 새 필링을 실제로 냈을 때만**
데일리 사이클에서 재호출되므로(`scripts/collect_new.py`→`sync_filings(force=True)`,
휴면 기업은 자연 재실행 안 됨) 후속 세션에서 별도 스크립트 필요. 주석(`_emit_note_
lines`) 쪽 era 라우팅은 애초에 분기 자체가 없음(이번 조사로 확인만, 범위 밖).

---

## R95. `parser/xml/table_extractor.py::_headerless_header_trs()` — THEAD 없는
구서식 표에서 배너/캡션행이 R88/R89 헤더그리드 인식을 처음부터 무산시킴, 그
결과 legacy multicol 압축이 **당기 완전공백 항목에 전기값을 오적재** (2026-09-12,
같은 날 후속 — 손익계산서 표의 "완전공백행"까지 2차 수정)

**배경**: 2015+ 전수 재적재 배치(`reload_report_lines_2015plus_2026-09-12.py`)
결과를 사용자가 원문과 직접 대조하던 중 발견. 특수건설(00186939) `20151116001903`
2015Q3 별도재무상태표 — 미착품·장기차입부채·장기차입금(그 외 다수)이 원문엔
**당기(제45기) 값이 아예 없고 전기(제44기)만 인쇄돼 있는데**, DB엔 그 전기값이
당기값으로 그대로 들어가 있었다.

**근본원인**: 이 표는 `<THEAD>`가 없는 구서식이라 R88/R89(`parse_header_columns`)가
`_headerless_header_trs()`로 TBODY 선두 TR들을 훑어 헤더 대용을 모으는데, 실제
헤더행("계정명｜주석｜제45(당)기｜제44(전)기") **앞에** 표제목("재무상태표")·기준일
캡션("제 45기 2015년 09월 30일 현재")·"회사명 : (주)특수건설 / (단위 : 원)" 같은
COLSPAN 병합 배너행이 여러 줄 끼어 있었다. `_looks_like_header_row()`는 라벨열
제외 나머지 셀에 금액도 마커도 없으면 "헤더 아님"(=데이터 도달, 스캔 중단)으로
판정하는데, 이 배너행들은 **금액도 마커도 없어서 "자산"류 진짜 섹션행과 신호가
동일**해 첫 줄("재무상태표")에서 곧바로 멈춰버렸다 — `header_trs=[]` →
`parse_header_columns()`가 `None` 반환 → `report_lines.py`의 legacy
`_detect_period_layout`/multicol 폴백(비어있지 않은 금액을 위치 그대로 당기→전기→
전전기 순으로 압축)으로 떨어짐. 이 표는 기간당 2열(spacer+값) 인쇄 방식이라 이
폴백의 "raw ≥ 2×n_periods" 조건에 걸려 multicol 로 오판되고, 당기 쪽 2열이
통째로 비면 전기 쪽의 유일한 값이 압축 후 첫 자리(=당기)로 밀려온다.

**수정**: 배너/캡션행과 "자산"류 빈 섹션행은 **내용 신호가 완전히 같아** 텍스트만
으론 못 가른다 — 대신 `<COLGROUP>`이 선언한 표의 총 물리 열수 대비 **이 행의
실제 TD 개수가 적은가**로 가른다(배너행은 COLSPAN 병합 때문에 항상 물리 셀이
적고, "자산"류는 값이 전부 공란이어도 칸 자체는 표 전체 폭을 채운다). 물리 셀이
적은 행("배너")은 마커가 있으면 헤더로 흡수하고, 없으면(진짜 캡션) **건너뛰고
계속 스캔**(스캔을 멈추지 않음) — 단 배너 모양이라도 진짜 금액이 있으면(안전장치)
데이터로 보고 멈춘다. `<COLGROUP>`이 없는 표는 판정 근거가 없어 기존 동작 그대로
(R6 원칙 — 모르면 확장 않음). 헬퍼 `_row_has_amount()`/`_table_colgroup_ncols()`
신설, `_headerless_header_trs()`에 `is_banner` 분기 추가.
설계: `docs/plans/table_header_banner_row_skip_design_2026-09-12.md`.

**후속 수정(같은 날, 사용자가 "손익계산서 쪽은 수정이 안 됐다"고 지적해 재확인)**:
BS는 배너행이 전부 COLSPAN 병합(물리 셀 < 선언 열수)이었지만, 이 필링의
포괄손익계산서 표는 표제목 바로 다음 줄이 **COLSPAN 없이 개별 빈 `<TD>` 5개를
나열한 완전공백행**이었다 — 물리 셀 수(5)가 선언 열수(5)와 같아 `is_banner`
판정을 피해가 여전히 첫 줄에서 멈췄다(대손상각비·연구개발비 등 당기 완전공백
항목이 전기값으로 오적재되고 있었음, 매출액 등 당기값 있는 항목은 원래도 정상).
**라벨칸까지 포함해 모든 물리 셀이 빈 행**은 애초에 라벨이 없어 "자산"류 섹션행이
될 수 없으므로(그건 라벨은 반드시 있음) — 폭 비교보다 먼저 무조건 건너뛰도록
`_headerless_header_trs()`에 한 줄 추가.

**검증**:
- `parse_header_columns()`가 BS 표에서 `None`→성공(주석열 1개 + 당기 2열(rank0) +
  전기 2열(rank1))으로, IS 표에서도 `None`→성공(당기 2열(rank0) + 전기 2열(rank1))
  으로 바뀜을 각각 직접 재현 확인.
- 실제 필링 재적재(`extract_report_lines`+`store_report_lines`+`store_report_tables`)
  후 DB 확인:
  - BS — 미착품·장기차입부채·장기차입금·저장품평가손실충당금 전부 잘못된 당기
    행이 사라지고(진짜 결측으로 정직하게 남음, R3 원칙) 자산총계=부채총계+
    자본총계(148,659,906,395) 항등식은 그대로 PASS. 행수 110→92(오적재 18행 제거).
  - IS — 대손상각비·연구개발비 전부 잘못된 당기 행이 사라짐. 매출액
    (109,300,142,706)·매출총이익·영업이익 등 당기값이 실제로 존재하는 항목은
    불변, `is_waterfall`(매출액−매출원가=매출총이익) 항등식 그대로 PASS. 행수
    71→61(오적재 10행 제거).
- `fin2/tests/test_header_grid_column_map_r88.py`에 회귀 테스트 4건 추가: 배너행
  건너뛰고 헤더 도달(BS 구조 재현) · `<COLGROUP>` 없으면 기존 동작 유지 · 배너가
  아닌 진짜 전체폭 빈 섹션행("자산")은 여전히 스캔 중단 · **완전공백행은 전체폭이라도
  무조건 건너뜀**(IS 구조 재현).
- `pytest tests/ fin2/tests/` 974 passed(970 대비 +4 신규, 기존 무관 실패 2건
  `test_lxintl_facility_table_dropped`/`test_nyuintek_2007q1_dkme_style_not_
  affected_by_this_fix` 그대로 — `git checkout HEAD -- parser/xml/table_extractor.py`
  로 수정 전 버전에 직접 대조해 이번 변경과 무관함을 확인).

**미조치**: `parse_header_columns()`가 `report_lines.py`에서 **모든** BS/IS/CF 표에
호출되므로 이 확장도 R89처럼 전사 적용되지만, "THEAD 없는 표 중 배너행/완전공백행
때문에 실패하던 비율"의 전사 census는 안 함. 이 필링 하나(20151116001903)는 이번
세션에서 직접 재적재해 정정했지만(BS+IS 둘 다), **같은 구조(구서식+배너행/완전
공백행)의 다른 필링들은 2015+ 전수 재적재 배치를 다시 돌려야 반영된다**(자동
소급 아님 — `docs/runbook_new_parser_pipeline_integration.md` §소급백필 원칙).
재적재 범위·시점은 별도 결정 필요. CF/SCE 는 이 필링에서 여전히 "단위 미선언"으로
0행(별개 문제, R95 스코프 밖).

**R95 전사 영향 표본조사(2026-09-12, 같은 세션)**: fiscal_year 층화표본 972건(연도당
80건, 2015~2027)에서 현재 DB(구 파서 결과)와 수정된 파서의 신선 추출 결과를
(statement,basis,label_raw)→value_won 로 비교 — **실제 값 diff는 2/972(0.2%)**.
(1차·2차 시도는 비교 스크립트 자체 결함으로 각각 1447/1452·970/972 라는 비현실적
결과를 냈다 — row_order 를 키에 넣어 R95가 옮기는 물리적 순번 자체를 오탐지, 이어서
new_vals/old_vals 의 statement 필터가 비대칭. 둘 다 스크립트 버그였지 실제 영향이
아니었다.) **결론: 표적 재적재용 사전필터를 따로 만들 실익이 없다**(THEAD/ACONTEXT
전체문서 유무로 표 단위 위험을 못 가른다는 것도 함께 확인 — 90%/0% 표본히트로 판별력
없음 확인) — 전면 2015+ 재실행이 표적화보다 공학적으로 더 싸다(스크립트 자체가
멱등·안전하다고 이미 설계돼 있음).

---

## R96. `collector/downloader.py::_pick_best_file_by_size()` — DART `document.xml`
ZIP에 xml이 여러 개(본문+첨부)일 때 "가장 큰 파일" 휴리스틱이 첨부(감사보고서)를
본문으로 오채택 (2026-09-12)

**배경**: R95 조사 중 사용자가 별도로 큐레이션해둔 "0행" 표본 9건("한국화장품제조
같은 list")을 검토하던 중 발견. 이 중 6건(웰킵스하이텍·대한방직·자비스·한국화장품
제조·파세코·스모트로닉)은 **원본 필링 자체가 재무제표 첨부를 누락**했다가 정정본
에서 보완된, 파서와 무관한 정상 케이스로 확인됐다(사용자 확인 + 정정본 문서구조
직접 대조). 나머지 2건(양지사 `20150930000130`, 티로보틱스 `20180402000209`)은
**정정본 자체가 없는데도** 0행이었다 — DART 웹뷰어로 직접 열어보면 "본문문서선택"에
멀쩡히 "사업보고서"가 있는데, 로컬 `raw_report`엔 `<DOCUMENT-NAME>감사보고서</
DOCUMENT-NAME>`인 **첨부문서**가 저장돼 있었다.

**근본원인**: DART `document.xml` API가 반환하는 ZIP은 본문·첨부를 **여러 개의
개별 XML 파일**로 담아 보낸다 — 파일명 규칙은 접미사 없는 `{접수번호}.xml`=본문,
`_{ACODE}` 접미사(예 `_00760`=감사보고서)=첨부. `_pick_best_file_by_size()`는
`.xml`이 여러 개면 **이름을 보지 않고 바이트가 제일 큰 파일을 무조건 선택**했다
(`_PICK_LARGEST_EXTS`). 대부분은 본문(사업보고서)이 제일 커서 문제가 안 되지만,
이 두 건은 **첨부(외부감사인이 작성한 감사보고서 — 재무제표+주석 전문 포함이라
본문보다 큼)가 더 커서** 크기 비교가 뒤집혔다. 실측(라이브 재요청으로 ZIP 내 파일
크기 직접 대조):
- 양지사: 본문 342,379B vs 첨부(`_00760`) 354,948B — 첨부가 3.7% 더 큼
- 티로보틱스: 본문 313,936B vs 첨부(`_00760`) 503,797B — 첨부가 60% 더 큼

파서(`assign_tables_to_dart_sections`)는 "2.연결재무제표"/"4.재무제표" 섹션이
없다고 정직하게 판정했을 뿐이다 — 잘못은 그 앞 단계(콜렉터가 잘못된 파일을 준 것)
에 있었다.

**수정**: `.xml`/`.xbrl` 후보가 2개 이상일 때, 파일명이 정확히 `{접수번호}.xml`
(첨부 접미사 없음)인 것이 있으면 크기 비교보다 그것을 우선 채택(`_pick_body_by_
filename()` 신설). 없으면(구형/미확인 명명) 기존 "가장 큰 파일" 동작 그대로
폴백 — R6 원칙, 모르는 모양이면 확장하지 않는다.

**검증**:
- 신규 유닛테스트(`tests/test_downloader_body_vs_attachment_r96.py`) 4건: 첨부가
  더 커도 파일명으로 본문 정확히 선택 · 이름 매치 실패시 기존 크기폴백 유지 ·
  xml 1개뿐이면 무변경 · 선행 `/` 유무 무관하게 매치.
- 라이브 재다운로드로 실제 두 파일 교체 확인(수정된 함수가 정확히 본문을 선택함을
  직접 확인) → `extract_report_lines()` 재실행: 양지사 0→587행(BS/CF/IS/SCE),
  티로보틱스 0→453행(BS/IS/SCE). 자산총계=부채총계+자본총계 항등식 둘 다 성립
  (양지사 82,959,399,402원 정확히 일치, 티로보틱스 43,378,342,172≈173원 — 레거시
  K-GAAP 반올림 1원차, 정상범위).
- `pytest tests/ fin2/tests/` 978 passed(974 대비 +4 신규, 기존 무관 실패 2건
  그대로).

**미조치**: 이 두 건은 즉석에서 원인을 확인하며 바로 재다운로드+재적재로 해결했다
(임시 스크립트, 정식 배치 아님). `_pick_best_file_by_size()`가 이제부터 새로
받는 모든 필링에 자동 적용되지만, **과거에 이미 이 버그로 잘못 저장된 다른 필링이
더 있는지 전사 census는 안 했다** — "xml이 여러 개인 ZIP에서 첨부가 본문보다
컸던 사례"가 이 2건 말고 또 있을지는 미확인. 필요하면 `download_tasks`에 저장된
파일의 `DOCUMENT-NAME` 태그를 전수 스캔해 "감사보고서"/"연결감사보고서" 등 본문이
아닌 문서가 `file_type='xml'`로 저장된 건을 찾는 방식으로 census 가능(다음 세션
후보).

**★전사 census 실행 결과(2026-09-12, 같은 날 후속)**: `scripts/census_r96_body_
attachment_swap_2026-09-12.py`로 fiscal_year>=2011(2011 이전은 별개의 레거시
인코딩 손상 이슈가 있어 제외 — 아래 참고) × report_type IN (annual/half/quarter)
× file_type='xml' 132,913건 전수 스캔(SD카드 미러에서 `DOCUMENT-NAME` 태그만
읽음, `[[feedback-bulk-read-use-sdcard]]`). 결과: **486건이 본문 키워드
(사업/반기/분기보고서) 아님**(감사보고서 250 · 연결감사보고서 235 · 기타 1) →
NAS 원본과 직접 대조해 이미 해결된 2건(양지사·티로보틱스) 제외 **484건이 여전히
NAS에도 잘못된 파일로 남아있음** 확정(진짜 미해결, 353개사). report_type별
483 annual · 1 half(반기·분기는 첨부가 "검토보고서"라 이 패턴에 거의 안 걸림 —
감사보고서는 사업보고서 필수첨부라 annual에 집중). fiscal_year 분포는 2011~2013에
편중(161·74·50건, 오래된 필링일수록 첨부가 본문보다 커지는 경우가 많았던 것으로
추정) 하지만 2025까지 전 연도에 소수씩 존재. 목록: `manual_review/
_r96_census_2026-09-12/still_wrong_on_nas.csv`(rcept_no·corp_code·report_type·
fiscal_year·SD/NAS 각각의 doc_name·DART링크·file_path).

**미조치(갱신)**: 484건 재다운로드(수정된 `_pick_best_file_by_size()`로 자동 본문
채택)+`report_lines` 재적재 캠페인은 아직 미실행 — 규모(353개사)상 별도 세션에서
계획 후 진행 필요. 2011년 이전(레거시 인코딩 손상 구간)은 이 census에서 제외돼
있어 미확인 상태로 남음(별도 조사 필요, 단 그 구간은 이 census 스크립트의 방식
그대로는 안 됨 — 파일 자체 인코딩 선언과 실제 바이트가 어긋나는 별개 문제라 전처리
방식부터 다시 설계해야 함).

**★재다운로드 실행 결과(2026-09-12, 같은 날 후속 — 사용자 지시로 즉시 진행)**:
`scripts/redownload_r96_body_attachment_swap_2026-09-12.py`로 484건 전부
`_download_one()`(수정된 `_pick_best_file_by_size()` 포함)로 재다운로드:
- **218건 — 진짜 R96 버그였음, 수정 확인**: ZIP 안에 본문 xml이 실제로 존재했는데
  기존 크기비교 로직이 첨부를 골랐던 것 — 파일명 매치로 본문을 정확히 재선택,
  각 파일 재다운로드 직후 `<DOCUMENT-NAME>` 재확인까지 완료.
- **266건 — 다른 원인, 버그 아님**: 재다운로드해도 여전히 감사보고서/연결감사보고서만
  나옴 → ZIP 안에 xml 후보가 **애초에 1개뿐**(본문 자체가 DART document.xml API
  응답에 없음, R96 필터가 손댈 여지가 없음). 형제필링(같은 corp+fiscal_year+
  fiscal_period) 검산 결과 **266/266 전부** 정정본에 `is_final=True`+실데이터가
  이미 있어 `[[held-zero-line-filing-triage-sibling-check-2026-09-12]]`와 같은
  패턴으로 확정(추가 조치 불필요 — 원본은 원래 본문없이 정상, 정정본이 진짜
  데이터).
- 실패 0건. `download_tasks.completed_at`이 이번엔 `_mark_completed()`로
  정상 갱신되어(부록1의 갭 재발 안 함) `scripts/sync_storage_mirror.py`
  증분동기화로 484건 전부 SD에 반영됨(90MB 전송, 43초). 원래 알려진 2건(양지사·
  티로보틱스, 6월에 수동 수정된 건 — 이번 484건 목록에는 없음)은 `completed_at`이
  그때 갱신 안 된 채 남아있어 이번 sync로도 안 잡혔으나, 수동으로 NAS→SD 직접
  복사해 마무리(SD/NAS 완전 일치 확인).
- **결론: R96 버그로 인한 실제 오적재는 218건 전부 해결. 나머지는 전부 별개
  현상(본문 자체 없음, 정정본으로 이미 커버됨)이라 조치 불필요.**
- `report_lines`/`report_tables` 재적재는 사용자 지시대로 미실행(진행 중인 전사
  재적재 `scripts/reload_report_lines_2015plus_2026-09-12.py` 완료 후 별도 진행
  예정) — 파일만 고쳐진 상태.

---

## R98. 연결재무제표 없는 회사가 "연결 basis 존재"로 오판되는 두 갈래 원인 —
`fin2/extract/text.py::_detect_fin_type()` 기본값 + `fin2/extract/html_viewer.py::
find_statement_nodes()` TOC placeholder 미필터 (2026-09-12)

**배경**: 자비스(01174038) 정정본(`20181114002329`) PDF 복구 결과, 존재하지 않는
연결재무제표를 찾다가 `report_recon_candidates`에 "판정불가"로 헛되이 등록됐다
(사용자 확인: "자비스는 원래 연결이 없어"). 원인을 좇다 **서로 다른 경로에 각각
독립적인 원인 2개**를 발견 — 사용자 지시("파서가 여러 개니까 각각 적용할 수 있는
것들은 적용")로 둘 다 수정.

**원인 ①** — `_detect_fin_type()`: `SUMMARY/EXTRACTION`의 `FIN_TYPE` 태그(A=연결
있음/B=별도만; 실측으로 'Z' 등 미문서화 값도 나옴)가 없으면 무조건 'A'로 가정했다.
그런데 **분기/반기 보고서는 이 태그가 원래 없다**(실측: 자비스 분기 원문 18건
전수 태그 없음, 연간 원문은 전부 있음 — 2016~2018년 전부 'Z'). FIN_TYPE은 회사
단위 속성(종속회사 유무)이라 보고서마다 거의 안 바뀌므로, 태그가 없을 때 **같은
회사의 annual/half 필링에서 빌려오도록**(`_lookup_fin_type_from_sibling_filing`,
`raw_report/` 트리 규약 의존, 대상 연도와 가장 가까운 필링 우선, corp별 in-process
캐시) 확장. `file_path`를 넘기는 호출측만 혜택을 보고(`report_lines.py`/
`text.py::extract_facts`/`report_line_audit.py::read_face_amounts`/
`face_audit.py::read_report_face_text`), 안 넘기면 완전 폴백(회귀 0).
`parser/xml/dart_xml_parser.py`도 자체 fin_type 로직(기본값 'B', 별개 구현)이
있지만 **라이브 파이프라인에서 호출되는 곳이 없어**(`parse_dart_xml`/`_extract_meta`
전수 grep, `fin2/`·`collector/` 안 0건 — `_parse_xml_file`만 재사용됨) 손대지 않음.

**원인 ②(실제 근본원인)** — `fin2/extract/html_viewer.py::find_statement_nodes()`가
DART TOC(`main.do`) 노드 중 "재무제표" 문자열이 든 것만 걸렀는데, **TOC는 회사가
실제로 연결재무제표를 작성하는지와 무관하게 "2.연결재무제표"~"5.재무제표 주석" 5종
표준 골격을 항상 나열한다** — 연결이 없으면 그 자리엔 "해당사항이 없습니다" 류
한 줄짜리 내용만 있다. `fin2/extract/reconcile.py::reconcile()`이 이 TOC 노드
목록만으로 "이 basis가 존재하는가"를 판정해(`bases_present`) 자비스의 이 placeholder
를 "연결 basis 존재"로 오인 — 실제 근본원인은 여기였다(①은 부수적으로 같이 고칠
가치가 있었을 뿐, `reconcile()`은 애초에 `_detect_fin_type()`을 안 씀).

실측(라이브 TOC 재요청, `TocNode.length`):
| 필링 | "2.연결재무제표" length | "4.재무제표" length |
|---|---|---|
| 자비스 정정본(연결 없음) | **138 B** | 29,908 B |
| 대한방직 정정본(연결 있음, 대조군) | 94,857 B | 89,344 B |

**687배 차이** — 텍스트("해당사항 없습니다" 등, 필자마다 문구가 다를 수 있어 매칭이
불안정할 위험)를 찾는 대신, 실제 표는 HTML 마크업만으로도 최소 수천 바이트인 반면
"해당없음" 한 줄은 아무리 길어도 수백 바이트를 못 넘는다는 **구조적 크기 격차**로
가른다 — `_TOC_PLACEHOLDER_MAX_LENGTH = 1000` 이하면 placeholder로 보고 제외.
`length` 파싱 불가(빈 문자열 등)면 판정 근거 없음으로 보고 기존대로 포함(R6 원칙).
`reconcile()`이 이 함수를 그대로 재사용하므로 별도 배선 없이 자동 적용.

**검증**:
- 실측 재현: 자비스 `report_recon_candidates`의 기존 오탐 행 삭제 후 `recover_one()`
  재실행 → **`basis=consolidated` 자체가 결과에서 사라짐**(수정 전엔 항상
  `decision=unresolved`로 찍혔음). `persist_unresolved` 결과도 1건→**0건**.
  별도(separate) 38행(BS 17/IS 9/CF 12) 적재는 그대로 정상 유지.
- 신규 회귀 테스트: `fin2/tests/test_html_viewer.py`에 2건(placeholder 연결 섹션
  제외 재현 — 자비스 실측값 그대로 픽스처화, length 파싱 불가시 포함 유지) — 기존
  `test_find_statement_nodes_excludes_유의점_and_감사의견`의 "4.연결재무제표"
  fixture length(520→25936)도 이번에 현실적인 값으로 정정(이전 값은 유의점/
  감사의견 텍스트 배제만 검증하려던 임의값이라 이번 필터와 우연히 충돌할 뻔함).
- `pytest tests/ fin2/tests/` 980 passed(978 대비 +2, 기존 무관 실패 2건 그대로).

**미조치**: `find_statement_nodes()`는 `html_viewer.py`의 다른 소비 경로(직접 표
추출)에도 쓰이는데 그쪽 전사 영향은 안 쟀다(reconcile() 경로만 실측 확인) — 다만
"내용 없는 섹션을 걸러낸다"는 방향 자체가 그쪽에도 해로울 이유가 없다(R6 원칙상
안전 방향). `parser/xml/dart_xml_parser.py`의 별개 fin_type 로직은 죽은 코드로
확인만 하고 그대로 둠 — 나중에 되살아나면 재검토 필요.

---

## R100. `fin2/extract/statement_titles.py::classify_legacy_statement_heading()` —
구형 레이아웃 표제의 "괄호숫자 순번" 접두("(1)연결재무상태표") 미인식 (2026-09-13)

**배경**: R96 재다운로드로 파일이 고쳐졌는데도 SBI인베스트먼트(00156910)
`20120329001048`(fy2011 annual)가 여전히 0행이었다. 원문에 재무상태표(7)·손익계산서
(3)·현금흐름표(2) 키워드가 전부 있는데도 `extract_report_lines()`가 못 찾음 —
R96과 무관한 별개 파싱 결함.

**원인**: "XI. 재무제표 등" 섹션 안에서 4대 재무제표를 **괄호숫자**로 순번매김한다
("(1)연결재무상태표"·"(2)연결포괄손익계산서"·"(4)연결현금흐름표", 별도 쪽도 (1)(2)(4)
동일). `classify_legacy_statement_heading()`의 `_LEGACY_ENUM_PREFIX`(`^[\dⅠ-Ⅻ]+\s*
[.．)）]`)는 **여는 괄호 없이** 숫자로 시작하는 노트번호("29.", "1)")만 거르는
규칙이라, 양쪽에 괄호가 있는 "(1)" 형태는 애초에 이 필터에 걸리지 않고 그냥
`_LEGACY_HEAD`가 문자열 시작에서 재무제표명을 못 찾아 미인식이었을 뿐이다.

**수정**: `_LEGACY_PAREN_NUM_PREFIX = re.compile(r"^[(（]\d{1,2}[)）]")` 신설,
`classify_legacy_statement_heading()`에서 한글 가나다 접두 제거와 같은 자리에 한 겹만
벗기고 재판정(중첩 없음, R69 한글접두와 동일한 안전판 — 벗긴 뒤 재무제표명이 안 걸리면
그대로 거부되므로 "(1)유동자산" 같은 주석 항목이 새로 오탐될 경로는 없음).

**검증**:
- SBI 재추출: 최초엔 IS/CF/SCE(연결+별도) 455행 확보(BS는 아래 R101/R102로 후속 완결).
- `pytest fin2/tests/ tests/` 979 passed — 기존 무관 실패 3건 그대로(그중 1건은
  `git stash`로 수정 전 코드에서도 동일 실패 확인해 무관 확정, 나머지 2건은 완전히
  다른 서브시스템).
- ★★**전사 영향도 최초 측정("0건")은 방법론 버그로 틀렸음이 이후 확인됨 — R101 항목
  참고.** 최초 원문 grep(패턴 부분일치)은 6만여 건 오탐(문맥 없이 "(1)재무상태표" 등
  부분일치라 주석·서술 어디서든 걸림)이라 폐기하고, `classify_legacy_statement_
  heading`을 직접 호출하는 정밀 스캔으로 재검사했으나, 그 스캔이 "이미 R100이 반영된
  현재 함수"를 기준으로 존재여부만 봐서(원본 코드와 비교 안 함) 이미 R100으로 걸리는
  케이스들이 전부 "기존에 이미 인식됨(95건)" 버킷에 숨어버렸다 — 그래서 "구제 0건"은
  측정 오류였다. **진짜 수치는 R101 항목에 정리된 54건**(이후 R102까지 더하면 더 늘어날
  수 있음, R101/R102 항목 참고).

**BS 후속**: SBI의 BS(연결·별도)는 이 시점엔 여전히 0행 — R101/R102로 완결.

---

## R101. `fin2/extract/statement_titles.py` — 구형 레이아웃 표제가 **다른 문장 뒤에
같은 요소 안에 이어붙는** 경우 미인식 + `fin2/extract/text.py`의 빈 요소가 pending
거리제한을 헛되이 소모하는 문제 (2026-09-13, R100 후속 같은 날)

**배경**: R100 적용 후에도 SBI의 BS(연결)는 여전히 0행이었다. 실측: "(1) 연결재무
상태표" 표제가 독립 요소가 아니라 K-IFRS 재작성 공시문구("※ 당사의 제26기... 재작성
되었으며... 감사를 받지 않았습니다.") **뒤에 같은 `<P>` 안에 이어붙어** 있다(IS/CF
표제는 깔끔한 독립 `<P>`라 이 문제가 없었음). `classify_legacy_statement_heading`은
"재무제표명으로 문자열 시작"을 요구하는데 이 텍스트는 disclaimer로 시작해 표제가
맨 끝에 온다.

**수정 1(꼬리표제 폴백)**: 전체 텍스트 판정이 실패하면 **"다."(한글 종결어미+마침표)
뒤 마지막 조각만** 다시 판정한다(`_LEGACY_SENTENCE_SPLIT = re.compile(r"다\.")`) —
단, 오탐 방지로 그 조각은 **B형(명칭 단독, `rest==""`)만** 인정. ★단순 "."으로 나누면
회귀 재현("29. 현금흐름표"의 "29."도 분리돼 뒷부분만 남아 주석헤딩이 본문으로 오인식,
`test_rejects_numbered_note_heading` 실패) — "다."로 좁혀 해결(서술어 종결과 열거번호는
마침표 앞 글자로 구분됨: 전자는 항상 '다', 후자는 숫자).

**수정 2(pending 나이 계산)**: 그래도 BS(연결)이 안 잡혀 추적해보니, 헤딩과 데이터표
사이에 **내용 없는 빈 SPAN 5개**가 끼어있어(문서 작성툴의 장식용 잔재) 원래 거리
(3~4)가 8로 부풀려져 `_LEGACY_PENDING_SPAN=4`를 초과, 진짜 데이터표를 못 물었다.
`fin2/extract/text.py`의 pending age 카운터를 "내용 있는 요소(TABLE 포함)만" 세도록
수정 — 빈 요소는 정보가 없으므로 "헤딩에서 멀어졌다"는 신호가 아니다.

**검증**:
- SBI: BS(연결) 28행 확보(이 시점 BS(별도)는 R102로 후속 완결).
- `pytest fin2/tests/ tests/` 979 passed(위 R100과 동일 기존 실패 3건만, 신규 회귀 0).
- **전사 영향도(정확한 방법 — `git show HEAD:...`로 원본 코드를 복원해 별도 모듈로
  로드하고, 같은 4,842건에 대해 원본 vs 현재 `classify_legacy_statement_heading`을
  나란히 비교)**: `scripts/census_r101_tail_heading_2026-09-13.py` — 레거시섹션없음
  3,853 · **★신규 헤딩인식 54건**(R100 단독으로 해결되는 케이스가 대부분이었음 —
  최초 census의 "0건"이 방법론 버그였던 걸 이걸로 확정) · 변화없음 863 · 읽기실패
  72. 54건 전부 `extract_report_lines()`로 실제 재추출해 **54/54 전부 실데이터 확보**
  (937~2391행 등) 확인 후 DB 반영 완료 — 경동제약·태광산업·대우건설·인선이엔티·
  케이티앤지·씨아이테크·중앙백신·삼성생명·와이엠·신성이엔지·아진전자부품·에스코넥·
  현대로템·삼영·NICE인프라·디오·한화투자증권·에프앤가이드·모아라이프플러스·글로본,
  그리고 SBI인베스트먼트 자신도 다른 연도 필링 9건 추가 확보(2012~2014년대).

**교훈**: 파서 버그의 "다른 필링 영향도"를 잴 때 **원본 코드와 정확히 비교**해야 한다
— "지금 함수가 이미 찾는지"만 보면 오늘 고친 부분이 이미 반영된 채로 자기 자신과
비교하는 꼴이라 영향도가 통째로 숨는다(이번처럼 "0건"이 실은 "54건"이었음).

---

## R102. `fin2/extract/text.py::_detect_legacy_body_statement_tables()` — 주석마커
판정이 헤딩판정보다 먼저 실행돼, 주석 참조문구로 시작하는 복합 요소의 꼬리표제를
검사조차 못 함 (2026-09-13, R100/R101 후속 같은 날)

**배경**: R101까지 적용해도 SBI의 **BS(별도)는 여전히 0행**이었다. 실측: 별도 BS
표제가 들어있는 요소의 전체 텍스트가 "(5) 연결재무제표에 대한 주석- 연결감사보고서
상의 연결재무제표에 대한 주석과 동일하므로 첨부된 연결감사보고서를 참고하시기
바랍니다. 2. 재무제표 ※ 당사의 제26기 별도재무제표와... 받지 않았습니다.(1)
재무상태표"였다 — **주석 참조 안내문구로 시작**해서 `is_legacy_note_marker()`가
맨 앞 40자만 보고 곧장 참으로 판정, `pending=None`으로 초기화하고 `continue`해버려
뒤쪽의 진짜 "(1) 재무상태표" 꼬리표제는 `classify_legacy_statement_heading` 호출
자체가 안 됐다(사용자 제안으로 이 줄 아래 내용을 몇 줄 더 확인해보다가 발견).

**수정**: `classify_legacy_statement_heading` 판정을 `is_legacy_note_marker` 판정
**앞으로** 옮겼다 — 헤딩이 잡히면 그걸 우선 채택하고, 못 잡으면(=진짜 순수 주석전환
문구뿐이면) 기존대로 주석마커 검사로 넘어간다. R101의 꼬리표제 폴백이 이미 B형만
엄격히 인정하므로(오탐 위험 낮음) 순서만 바꿔도 안전하다.

**검증**:
- SBI: BS(별도) 27행 추가 확보 — **SBI 전체 완결(BS/IS/CF/SCE 연결+별도, 510행)**.
- `pytest fin2/tests/ tests/` 979 passed(R100/R101과 동일 기존 실패 3건만, 신규
  회귀 0).
- **전사 영향도(정확한 방법)**: `scripts/census_r102_precise_2026-09-13.py` —
  "이 요소가 `is_legacy_note_marker`엔 걸리는데 `classify_legacy_statement_heading`
  으로도 인식되는가"(=R102가 바뀌는 조건 그 자체)를 4,788건에 직접 재현: **R102가
  실제로 바꾸는 건 0건**(SBI 별도-BS가 유일 사례). ★주의: 처음엔 "report_lines가
  DB에 있는지"로 전후비교해 939건이 나왔었는데, 표본 확인해보니 오늘 수정과 무관한
  파일(레거시 섹션 자체가 사실상 비어있음)까지 걸려있었다 — 그 방식은 수개월치
  누적된 다른 개선사항까지 다 섞여 부풀어 오른 것이라 **폐기**(파일 삭제). "DB에
  있는지"가 아니라 **"이 특정 수정이 바꾸는 조건 자체"를 직접 재현**해야 정확한
  영향도가 나온다 — R101 항목의 교훈과 같은 계열의 함정.

---

## R103. `collector/downloader.py` — 정기보고서가 접수 당시 PDF만 있고 표준파일
(XML/XBRL)은 나중에 등록되는 경우, "완료"로 마감되어 재확인이 없었음 (2026-09-13)

**배경**: 2015+ 항목수 분포 리포트 작성 중 발견한 결측 8건 중 5건(2026 반기보고서,
2026-08-14 접수)이 `download_tasks.file_type='pdf'`였다. 사용자 질문("XML은 없고
PDF만 있다는 거야?")에 답하려고 DART document.xml API를 **지금 다시** 조회해보니
5건 다 XML이 이미 올라와 있었다(나머지 2건은 지금도 014 — `[첨부정정]`이라 본문
재발행 자체가 없는 것으로 보임, 별개 사유).

**원인**: `_download_one()`은 ZIP에서 고른 `best` 파일이 무슨 확장자든 일단
받으면 `_mark_completed()`로 무조건 완료 처리한다. 회사가 사람이 읽는 서식(PDF)을
먼저 내고 표준파일(XBRL)은 며칠~몇 주 뒤에 뒤늦게 올리는 관행이 있는데(이미 알려진
[014](document.xml 자체가 없음) 케이스와 같은 근본원인의 다른 얼굴), "일단 뭔가
받았으니 완료"로 처리해버리면 나중에 표준파일이 올라와도 재확인할 방법이 없었다
(daily는 `status IN (pending,failed)`만 재시도 대상으로 봄).

**수정**: `report_type IN (annual,half,quarter)`인 필링에서 고른 파일이 `.xml`/
`.xbrl`이 아니면 `_mark_completed()` 대신 신설한 `_handle_standard_file_pending()`을
호출 — 기존 [014] 정책(`XML_PENDING_ALERT_START_DAYS`=30일부터 알림, 무기한 재시도)과
**같은 메커니즘을 재사용**한다. 차이는 이미 받은 파일(PDF 등)이 있으므로
`file_path`/`file_type`/`file_size`를 잠정 채워두는 것 — 단 `status='pending'`이라
`report_lines` 재적재 유니버스(`dt.status='completed'` 필터)엔 안 들어간다. 표준파일이
실제로 올라오면 다음 데일리 재시도에서 정상적으로 `_mark_completed()`를 타 완료 처리
+ report_lines 재적재 대상 진입.

**검증**:
- 실측 5건 전부 재다운로드해서 XML 확보 확인(`_download_one()`을 직접 호출해 실제
  성공 재현) 후 `report_lines` 재적재 — BS/IS/CF/SCE 연결+별도 전부 정상 확보.
- `pytest fin2/tests/ tests/` 979 passed — 기존 무관 실패 3건 그대로, 신규 회귀 0
  (`tests/test_downloader_body_vs_attachment_r96.py`·`tests/test_download_5corps.py`
  포함).

**미조치**: 이 수정은 **앞으로의 신규 다운로드에만** 적용된다 — 과거에 이미
`status='completed', file_type='pdf'`로 마감된 필링(오늘 발견한 5건 제외)은 전수
백필 대상에서 안 걸러졌다. 그런 필링이 얼마나 더 있는지(전사 census)는 미실시 —
필요하면 `download_tasks WHERE file_type NOT IN ('xml','xbrl') AND status='completed'
AND report_type IN (annual,half,quarter)`로 후보를 뽑아 DART에 XML이 지금은
올라왔는지 표본 재확인하는 census를 다음 세션에서 고려.

---

## R104. `collector/filing_collector.py` — 같은 날 접수된 "최초본+첨부정정/첨부추가"
그룹에서 최초본이 download_tasks에 영영 안 잡히는 결함 (2026-09-13, R103 후속 같은 날)

**배경**: R103으로 부국증권·멤레이비티의 2026 반기보고서를 살펴보다가, 사용자 질문
("정정보고서 이전 최초 보고서가 있었을 텐데, 그 기의 본문이 적재 안 된 거냐")으로
발견 — 두 회사 다 **최초본 자체가 `download_tasks`에 행 자체가 없었다**(다운로드
시도조차 안 됨). DART에 직접 확인해보니 최초본에 진짜 본문 XML이 있었다(부국증권
3.2MB · 멤레이비티 1.7MB) — 지금 `is_final=True`로 잡혀 있는 "[첨부정정]"/
[첨부추가] 쪽은 오히려 document.xml 자체가 없거나(014) 본문이 아니다.

**원인**: download_tasks 생성 SQL이 "`is_final=TRUE`인 것" 또는 "그룹에
`is_amendment=TRUE`인 필링이 있으면 그 그룹 전체"를 큐에 넣는데, `_is_amendment()`는
**"[기재정정]"만** amendment로 인정하고 "[첨부정정]"/"[첨부추가]"는 의도적으로
제외한다(`_is_attachment_amendment()` docstring: "본문은 동일, 첨부만 정정" —
그래서 재무 본문 신호로 안 씀). 최초본과 첨부정정이 **다른 날** 접수되면 문제가
없다(최초본이 먼저 도착했을 때 이미 `is_final=True`로 큐에 잡혔을 것이므로). 하지만
**같은 날** 접수되면 그룹이 생성되는 시점에 이미 `is_final`이 첨부정정 쪽으로
넘어가 있고 `is_amendment` 신호도 없어 최초본이 이 EXISTS 조건에 전혀 안 걸린다 —
"첨부만 정정, 본문 동일"이라는 가정이 이 타이밍에서는 "본문 자체를 안 받는다"는
결과로 뒤집힌다.

**수정**: EXISTS 조건에 `f2.is_attachment_amendment = TRUE`도 추가 — 그룹에 첨부
정정이 있으면(같은 날이든 아니든) 최초본도 항상 큐에 포함시킨다.

**검증**:
- 부국증권 `20260814002623`(최초 반기보고서)·멤레이비티 `20260814002334`([첨부추가]
  반기보고서) 둘 다 실제로 download_tasks 행 생성 → `_download_one()` 재현 →
  XML 확보(3.1MB/1.6MB) → `report_lines` 재적재까지 완료(BS/IS/CF/SCE 연결+별도
  정상).
- `pytest fin2/tests/ tests/` 979 passed — 기존 무관 실패 3건 그대로, 신규 회귀 0
  (`tests/test_filing_collector_correction_recheck.py` 포함).

**전사 census(같은 날 실시, 2026-09-13)**: 위와 같은 조건(그룹에 첨부정정이 있는데
어떤 필링은 download_tasks 자체가 없음)으로 전체를 스캔 — **잔여 0건**. 즉 이번에
백필한 부국증권·멤레이비티 2건이 이 버그의 전체 이력이었다(같은 날 접수되는
최초본+첨부정정 조합 자체가 드묾). R103의 "PDF로 완료 마감된 과거분" census는
성격이 다른 별개 항목이라 그쪽은 여전히 미실시 상태로 남아있음(R103 항목 참고).

---

## R105. `standard_financials.consolidation_status` VARCHAR(20) 길이초과로 std_v3
재빌드 5-shard 전체 즉시 크래시 (2026-09-13)

**배경**: Track1(2015+) 연결비대상 확정 컬럼(`consolidation_status`)을 std_v3
재빌드에 반영하려는데, 사용자가 실행한 5-shard가 **전부 첫 행에서 즉시 실패**했다.

**원인**: 컬럼을 `VARCHAR(20)`으로 선언했는데 실제 값 `'no_subsidiary_confirmed'`가
24자라 모든 INSERT가 `StringDataRightTruncation`으로 실패(partial write 없음).

**수정**: `VARCHAR(30)`으로 확장(마이그레이션 2건 — `standard_financials`가 이
컬럼에 의존하는 뷰 `standard_financials_verified`를 CASCADE로 지웠다가 재생성).

**검증**: pytest 재확인(무관 기존 실패 3건 그대로, 회귀 0). 재빌드는 이 수정
이후 재실행해서 완료.

---

## R106. `fin2/extract/consolidation_evidence.py` — IFRS1109/1115 소급재작성
각주가 "연결비대상" 선언으로 오매칭 (2026-09-13)

**배경**: 사용자 질문("report_lines에 연결이 없는데 데이터가 들어있는 케이스가
있을 수 있어?")으로 발견 — `consolidation_evidence='no_consolidated_fs_track1'`
확정 18,230건 중 52건이 실제로는 `report_lines`에 연결 BS/IS/CF 데이터를 갖고
있었다.

**원인**: `작성\s*(?:하지|치)\s*않` 패턴이 너무 느슨해 "전기 실적은 이를
소급적용하여 재작성하지 않았습니다"(IFRS1109/1115 도입 시 소급재작성 안 함을
알리는 흔한 각주, 연결 존재여부와 무관 — 웅진씽크빅 00628189 실측)에 걸렸다.

**수정**: `재무제표[^.<]{0,15}작성\s*(?:하지|치)\s*않`로 좁혀 "재무제표"가
바로 앞(≤15자)에 붙어야만 매칭하도록 함.

**검증**: 회귀테스트 9건 추가·전체 pass. 재검증 결과 52건 중 41건은 여전히
확정 유지(별개 원인, R107 이하 참고), 11건은 미확정으로 정정.

---

## R107. 같은 파일 — "OO재무제표를 재작성하지 않았습니다" 문장구조 잔여
오탐 28건 (2026-09-13, R106 잔여 재검증)

**원인**: R106 수정 후에도 "재무제표"가 "재작성" **바로 앞**에 오는 문장구조
("OO재무제표를 재작성하지 않았습니다")는 R106의 15자 근접조건을 그대로 통과해
여전히 오매칭됐다(28건/11개사: 세동·에스피지·현대에버다임·파워로직스 등).

**수정**: 문장구조 자체를 배제하는 조건 추가.

**검증**: 41건 재검증에서 이 유형 28건 해소.

---

## R108. 같은 파일 — SPAC 합병보고서에서 SPAC 껍데기 법인의 "해당사항 없음"
선언이 실제 합병대상 법인 전체에 오적용 (2026-09-13)

**배경**: R107 이후 잔여 13건 원문대조 중 발견(애니플러스·밸로프·SFA넥셀).

**원인**: SPAC 합병보고서는 문서 안에 SPAC 껍데기 법인 자신의 "연결재무제표
해당사항 없음" 선언이 있는데, 이게 실제 합병대상 법인(실사업 보유, 연결
작성 대상)에까지 잘못 적용됐다.

**수정**: "[기업인수목적]" 브래킷 뒤 다음 브래킷부터 재스캔하도록 스코프 조정.

---

## R109. 같은 파일 — 비교연도(전기)만 지칭하는 결측선언이 당기 확정
근거로 오매칭 (2026-09-13)

**배경**: YBM넷(00307222) 20220323000611 실측 — "비교표시되는 제N(전)기는
연결없음"이라는, **전기만** 지칭하는 서술이 **당기** 연결비대상 확정 근거로
잘못 채택됐다.

**수정**: `_looks_like_prior_year_only()`(가칭) — 매칭 직전 지역문맥에 당기/전기
표지가 있는지로 가려내는 가드 추가. R108(SPAC 껍데기 블록 건너뛰기)을 먼저
적용한 뒤 이 가드를 적용하는 순서.

---

## R110. 같은 파일 — 순번↔회계연도 매핑이 불가능한 케이스(SGA솔루션즈)를
영구 예외로 기록 (2026-09-13)

**배경**: "제1기[2년전]만 없음"류 서술은 순번과 실제 회계연도의 매핑 정보가
문서에 없어 일반 규칙화가 불가능했다.

**처리**: 사용자가 DART 원문의 당기 자산총계를 직접 확인해 "당기 연결·별도
둘 다 실데이터 존재"를 확정 → 텍스트판정을 건너뛰는 영구 예외로 코드에
하드코딩(rcept 2건).

**같은 세션 후속**: D유형(유진로봇 4건·디어유 1건·CSA코스믹 1건) —
한 표 안에서 열마다 basis가 다른데 파서가 표 전체를 'consolidated'로만
태깅해 당기(실제로는 연결재무제표 없음) 데이터가 중복 적재된 별개 결함.
사용자가 DART 원문 직접 확인 후 "연결 불필요, 삭제 확정"으로 report_lines
1,519행 삭제(`scripts/delete_consolidation_r_fixes_2026-09-13.py`). 아이퀘스트
1건은 원문이 "개별재무제표를 연결란에도 그대로 기재"라고 명시 — 버그 아님.

**검증(R105~R110 종합)**: 회귀테스트 4건 추가, pytest 992 passed. 재백필+
std_v3 재빌드 후 41건 재현쿼리 → 1건(아이퀘스트, 의도된 예외)만 남아 완전
종결. 상세: `docs/plans/consolidation_scope_confirmation_design_2026-09-13.md`.

---

## R111. `parser/xml/table_extractor.py`/`fin2/extract/text.py` — 글자당
공백("3 개 월", "누  적") 서브헤더 정규식 미매칭 (2026-09-13)

**원인**: `_SUBTYPE_CUM_RE`/`_SUBTYPE_3M_RE`(및 `text.py`의 동형 사본
`_CUM_RE`/`_THREE_M_RE`)가 "3개월" 한 칸만, "누적" 공백 자체를 불허해
장식체 서브헤더("3 개 월", "누  적")를 인식하지 못했다 — 파워넷(00231354)
20150515001597 실측: 당기누적 25,781,758,600 대신 무관한 제22기 열
82,662,901,775을 엉뚱하게 채택.

**수정**: 두 파일 양쪽 정규식에 글자당 공백(`\s*`) 허용 추가(같은 문서에 두
벌 존재 — 동시 수정 필요).

---

## R112. 같은 파일 — 글자당 공백 주석헤더("주  석") 인식 실패로 헤더그리드
전체 폴백 (2026-09-13)

**배경**: 한양증권(00162416) CF_separate 항목수 분포 이상치 조사 중 발견.

**원인**: `_NOTE_HEADER_RE`가 없어(또는 공백 미허용) "주  석" 헤더열을 못
알아채 `parse_header_columns()`가 None을 반환, 구버전 cum_map/multicol/else
폴백으로 떨어졌다.

**수정**: `_NOTE_HEADER_RE` 도입/확장.

---

## R113. 같은 파일 `select_by_header_columns()` — 순수 대시("-") 셀을 구조적
0으로 채택하는 `raw_amounts` 파라미터 도입 (2026-09-13)

**배경**: 넥슨게임즈(전 엔에이치기업인수목적9호) 사용자 원문대조로 발견.

**원인**: `amounts[pos]`가 None인 칸이 "진짜 결측"인지 "원문이 명시적으로
'-'(공란 아님, 0의 의미)라고 쓴 것"인지 구분이 안 됐다 — DART 관행상 순수
대시는 결측이 아니라 0을 의미.

**수정**: `raw_amounts`(원시 텍스트)를 같이 넘겨, `amounts[pos]`가 None인 칸의
원시 텍스트가 순수 대시뿐이면 0으로 채택. `parse_amount()` 자체는 불변(게이트
계층에서만 처리).

---

## R114. 같은 함수 — R113 직후 회귀: 무표지 병합군(COLSPAN 다중열)에서
구조적 대시 채택이 실제 값을 삼킴 (2026-09-14)

**배경**: 케이엠제약(20160516000811) IS/CF 별도 원문대조로 발견. SPAC 합병
첫 사업연도 표는 "제1(당)기" 하나의 라벨이 COLSPAN=2로 물리열 2개를 덮으면서
(subtype 구분 텍스트 없음) 그중 **한 열 전체가 구조적으로 순수 대시**고 실제
값은 나머지 한 열에만 있었다("영업비용" 열1="-" 열2="(21,402,210)"). R113이
열1의 대시도 0으로 채택해버리면 두 열 다 "값 있음"이 돼 R6 판정불가로 행
전체가 유실됐다(IS 별도 11행 중 9행, CF 별도도 동형 붕괴).

**수정**: 먼저 **진짜 파싱값**(대시 아님)만으로 후보를 추리고, 정확히 1개면
그 값을 채택. 진짜 값이 하나도 없을 때만(그룹 **전체**가 대시뿐일 때만) 구조적
0(R113 취지)으로 채택. 진짜 값이 2개 이상이면 기존대로 판정불가(R6).

---

## R115. `parser/xml/table_extractor.py::drop_mismatched_granularity_columns()`
(신규) — 분기/반기 표의 연간참고열이 엉뚱한 회계연도로 오매핑 (2026-09-14)

**원인**: 분기/반기 보고서 IS/BS/CF 표가 자사 분기열(제N기 1분기 3개월/누적)
뒤에 분기/반기 접미사 없는 순수 연도서수 참고열(제(N-1)기/제(N-2)기)을
붙이는 서식에서, 위치기반 `context_fiscal_year` 공식이 그 참고열을 엉뚱한
연도로 계산해 진짜 실적행이 잘못된 `col_index`로 밀려났다.

**수정**: `drop_mismatched_granularity_columns()` 신설 — 분기/반기 보고서에서
순수 연도서수 열을 배제하고 남은 rank를 재부여.

---

## R116. `fin2/extract/report_lines.py::_Q1_CUM_BLANK_USE_3M_RCEPTS` — Q1
보고서 "3개월=누적" 등식을 이용한 누적란 공백 대체 (예외목록, 2026-09-14~15)

**배경**: 형지I&C(20160516001490)·드림시큐리티(20160511001294) 2016 Q1
보고서는 IS 표 전체가 "3개월" 칸만 채우고 "누적" 칸은 공란이거나(형지) 서브타입
구분 없이 두 물리열에 완전히 같은 값을 중복 기재(드림)한다 — 두 필링 모두
"당기순이익" 행이 두 칸에 동일값을 채워 **1분기는 정의상 3개월=누적**이라는
등식을 필자 스스로 증명한다.

**설계 결정(R6 유지)**: 이 등식이 Q1에서만 성립하고(H1/Q3는 다름) 실측도
소수 필링에서만 확인되므로, "누적 공란 → 3개월로 대체 안 함"이라는 전사
원칙을 뒤집지 않고 **예외목록으로만 좁힌다**. `select_by_header_columns()`에
`allow_three_month_as_cumulative` 옵션 추가, `report_lines.py`가
`report_fiscal_period=="Q1" and rcept_no in _Q1_CUM_BLANK_USE_3M_RCEPTS`일 때만
전달.

**예외목록 누적 이력**: 형지I&C·드림시큐리티(원조) → 조광페인트
(20170512001930)·자이글(20190527000008, 2026-09-14 후속 실측, 동일 패턴) →
평화산업(20180515002398, 2026-09-15, IS_separate 이상치 재검증 중 발견 — 별도
손익계산서만 이 패턴, 연결은 정상이라 필링 하나만의 기재누락).

---

## R117. `parser/xml/table_extractor.py::_columns_from_grid()` — 완전공란
주석헤더열이 헤더그리드 전체를 폴백시키던 결함 (2026-09-14)

**배경**: 아주IB투자(20150817001086) CF 연결 실측.

**원인**: 주석번호 참조열의 `<TH/>`가 "주석"이라는 글자조차 없이 완전공란
(자기닫힘)인 서식에서, 기존엔 "기간패턴도 주석표시도 없는 열"로 판정해
`parse_header_columns()` 전체가 None을 반환 → 구버전 cum_map/multicol/else
폴백으로 떨어져 CF 본체(영업/투자/재무활동현금흐름 등)가 32행 중 30행
유실됐다.

**수정**: 헤더 스택이 전부 빈 문자열이면(주석열이든 진짜 빈 열이든 "period
값을 못 낸다"는 결론은 같음) 주석열과 동일하게 `is_note=True`로 건너뛴다
— `select_by_header_columns`가 이미 is_note 열을 무조건 skip하므로 안전.

---

## R118. `fin2/extract/report_lines.py::_R118_DUPLICATE_PERIOD_LABEL_FIX` —
원문 헤더 자체가 기간라벨을 중복 오기재한 필링들의 개별 교정 (예외목록,
2026-09-14~15)

**공통 패턴**: 표 헤더가 서로 다른 두(또는 세) 물리열에 **완전히 동일한
기간라벨 텍스트**를 중복 기재(원문 자체의 오타). 구분 텍스트가 전혀 없어
일반 규칙으로는 판별 불가 — 매번 **회계항등식 역산**(기초현금=전기말현금 등)
또는 사용자 원문대조로 올바른 rank를 확정하고, `(rcept_no, statement, basis)
→ {position: 교정된 rank}` 형태로 그 필링 하나에만 한정한 예외 교정을
`_apply_duplicate_period_label_fix()`가 적용한다.

**목록**:
- 제주은행(20160516002967) CF 연결, 2016 Q1 — "제57기 1분기" 2번 반복. 첫
  열의 기초현금이 3번째 열("제56기" 연간표)의 기말현금과 일치.
- 제주은행(20230314001271) CF 연결, 2022FY 후속(3중 중복) — "제62기"×2/
  "제61기" 순으로 한 기수씩 밀려 중복.
- 이노시뮬레이션(20200330004128) IS 별도, 2019FY — "제19기" 2번 반복(같은
  필링 BS 별도는 정상이라 IS만의 오타로 확정).
- DSC인베스트먼트(20230515002273) IS 별도, 2023 Q1 — "제11(당)기 1분기"
  COLSPAN=2 그룹째로 2번 반복. 두 그룹 값이 서로 다름(영업수익 두 값)으로
  확정.
- 이랜시스(20190401000391) CF 별도, 2018FY — "제1(당)기" 2번 반복(설립
  첫해 신설법인). 2번째 열 기말현금이 1번째 열 기초현금과 일치 → 전기로 교정.
- 신영증권(20220615000399) CF 별도, 2022FY(2026-09-15) — "제68기"(당기)/
  "제67기"(전기)/"제66기"(전전기) 순이어야 할 걸 "제67기" 2번 반복해 첫
  그룹(당기)까지 전기와 같은 텍스트로 오기재. 연결 현금흐름표는 68/67/66으로
  정상(별도 표만의 오타). 회계항등식 2개(영업+투자+재무+환율=순증감,
  기초+순증감=기말) 검증.

---

## R119. `parser/xml/table_extractor.py::_columns_from_grid()` — 같은 셀 안
괄호 서브타입 접미사("(3개월)"/"(누적)") 미인식 (2026-09-14)

**배경**: 푸른저축은행(20150213000097) IS 별도 실측.

**원인**: THEAD 없는 구서식은 헤더가 한 줄뿐이라 서브타입 표시가 별도
스택행이 아니라 **같은 셀 안에서 기간 텍스트 바로 뒤 괄호**로 붙는다
("제 45기 반기(3개월)"/"제 45기 반기(누적)"). 기존 로직은 매치된 셀 이후의
다른 스택행만 subtype_text로 모아, 매치된 셀 자신의 잔여 텍스트(괄호 부분)가
버려져 두 물리열 다 subtype=None으로 남았다 — 결과: 두 열 다 "값 있음"이 돼
R6 판정불가로 IS 24행 중 23행 유실.

**수정**: 매치된 셀 자신의 잔여 텍스트(정규식 매치 끝 이후)도 subtype_text에
포함.

---

## R120. `parser/xml/table_extractor.py::select_by_header_columns()`
`prefer_last_of_two_as_cumulative` — 무표지 2열 병합군, 두 열 다 실값이고
서로 다른 경우 (예외목록, 2026-09-14~15)

**배경**: 웹케시(20180814001946)·우리기술투자(20200813000621) H1 IS 표 —
같은 라벨("제20기 반기" 등)을 구분 텍스트 전혀 없이 물리적으로 다른 2열에
반복하는데, 두 열 다 실제 값이고 서로 다르다(H1이라 3개월≠누적, R116과
달리 "값이 같을 때만 통과"가 안 통하는 진짜 판정불가 상황).

**설계 결정(R6 유지)**: DART 관행상 무표지 2열은 항상 [3개월 먼저, 누적
나중] 순서 — 산수로 직접 검증(Q1 당기순이익 + 이 표 1번째 열 = 이 표 2번째
열, 웹케시·우리기술투자 둘 다 확인)했지만 일반 규칙화 대신 예외목록으로만
좁힌다.

**예외목록 누적 이력**: 웹케시·우리기술투자(원조) → 삼성생명(20150817000794,
2015 H1, 2026-09-15 후속) — 연결 포괄손익계산서가 "제N(당)반기"/"제N(전)반기"
무표지 COLSPAN=2 병합군 2개 + 단일 FY열 2개, 총 6열인 이례적 헤더. 당반기
병합군 뒷열(14,198,956백만원)이 "요약연결재무정보" 표의 같은 기간 값과
정확히 일치함을 대조 확인. 같은 회사 앞뒤 20여 개 필링(2013~2017)은 전부
정상이라 이 필링 하나만의 이례적 서식.

**후속(2026-09-16, 5번 임계값 재검토 스캔 — 사용자 지시 "지금 원인
조사+수정") 3건 추가** — 새로운 하위 유형: "요약재무정보" 서식(공식
"2.연결재무제표"/"4.재무제표" 섹션이 빈 placeholder이고, 실제 데이터는
"1.요약재무정보" 절의 "요약분기(연결)손익계산서" 표에만 있는 소형사 분기
보고서)에서, **"3개월"/"누적" 서브헤더 행 자체가 통째로 빠진** 경우:
- 바이오플러스 20191129000890(2019 Q3, IS_consolidated) — 별도 표는 서브헤더
  정상 보유(2단 THEAD), 연결 표만 서브헤더 행이 없어 물리열 4개가 전부
  subtype=None. 매출액 열값(3,630,992,617 / 12,050,665,141)이 별도 표의
  이미 정상 추출된 값(12,050,665,141)과 뒤쪽 열에서 일치.
- 우리기술투자 20201116001931(2020 Q3, IS_consolidated) — 서브헤더 텍스트
  ("3개월"/"누 적")가 `<THEAD>`가 아닌 `<TBODY>` 첫 행에 있어 R88
  grid파서가 못 읽음(`header_cols`는 성공하지만 subtype 정보 없이). 영업수익
  물리값(16,495,257,853 / 18,344,549,484)이 [3개월<누적] 순서와 일치.
- 메이슨캐피탈 20210210000442(2021 Q3, **IS_separate**) — 위 2건과 반대로
  연결 표는 서브헤더 정상 보유, **별도** 표만 없음(같은 문서 안에서도 basis별로
  결함 유무가 다를 수 있음을 보여준 사례). 영업수익(1,201,859,418 /
  4,499,489,903)이 [3개월<누적] 순서와 일치.

3건 모두 "공식 재무제표 섹션이 빈 문서"라는 공통 배경을 갖지만, 판정 자체는
R120과 동일한 코드 분기(무표지 2열, 서로 다른 실값, `len(cols)==2`)를 그대로
타므로 예외목록만 확장했다(코드 변경 없음). 테스트:
`test_r120_followup_headerless_merge_missing_subheader_row_picks_cumulative`.

---

## R121. `fin2/extract/report_lines.py::_MANUAL_NO_CONSOLIDATED_FS_RCEPTS` —
문서에 물리적으로 표는 있으나 그 값이 이 필링의 당기/전기 것이 아닌 케이스
(예외목록, 2026-09-14~15)

**배경**: 더블유게임즈(20160520000534, 2015FY) — 사용자 확인("해당 기간
3,4기는 연결대상이 아니야... 삭제하고 연결비대상으로 표시해"). 문서의
"2. 연결재무제표" 섹션에 물리적으로 표가 있어(유진로봇류 "완전공백 섹션"과
다름) 정상 추출 경로를 그대로 타지만, 그 값은 이 필링 당기(제4기)·전기
(제3기) 것이 아니라 지주사 전환 이전 시절인 **제2기(2013) 시점의 옛 자본
변동표/EPS 수치**뿐이다(SCE 전 col_index가 "2013.01.01"/"2013.12.31" 날짜
라벨, IS는 EPS 2줄만).

**처리**: "빈 섹션"이 아니라서 `_detect_body_statement_tables`가 정상적으로
찾아버리고, 값 자체도 억지로 재계산할 근거가 없어(제2기 수치를 당기/전기로
재배정할 방법이 없음) 연결(_C) 섹션 코드를 통째로 스킵 — 별도(_S)는 무영향.

**목록**: 정정본(20160520000534) + 같은 회사·같은 기간의 원본(정정 전,
2026-09-15 후속 — 4개 이상치 카테고리 재검증 중 원본도 report_lines에
적재돼 IS_consolidated=2건으로 걸림을 발견, 동일 처리).

---

## R122. `parser/xml/table_extractor.py::_PERIOD_KEY_RE` — 괄호 뒤 "기"
탈락 오타("제N(당) 반기"류) (2026-09-14)

**배경**: CF_separate 저조 이상치 스크리닝 중 발견 — "제N(당)기 반기"/
"제N(당)기 1분기"류 표기에서 괄호 바로 뒤 "기"를 빠뜨리고 "제N(당) 반기"/
"제N(당) 1분기"로 적는 오타가 서로 무관한 최소 3개 회사(레이크머티리얼즈·
케이엠제약·자비스)에 걸쳐 반복 확인 — 같은 회계 SW/템플릿을 쓰는 소형사
군의 공통 결함으로 추정, 일반 규칙로 확장.

**수정**: "기" 뒤 "분기"/"반기" 접미사만 옵션이던 것을, "기" 자체도 옵션화.

---

## R123. 같은 파일 — 증권사류 헤더 4가지 미인식 변형 (2015+ 전수 폴백
스캔 후속, 2026-09-14)

**배경**: `scripts/scan_header_fallback_2015plus_2026-09-14.py`로 2015+ 전수
스캔(표 559,701건 중 폴백 1,333건, 0.24%) — 상위 다수가 증권사(유안타증권·
NH투자증권·다올투자증권·대신증권 등)에 몰려있었다.

**수정**: `_PERIOD_KEY_RE`에 4가지 대안 추가 — ① "2015회계연도 1분 기"(제
접두 없음, 연도+회계연도, 글자당 공백) 등 증권업 특유 표기 변형.

---

## R124. (시도했다가 되돌림) 명세/소계 COLSPAN=2 중복 서브타입 열의 전사
일반 규칙화 — SB성보 회귀로 폐기, R125로 대체 (2026-09-14~15)

**배경**: 명세/소계(1열=세부항목, 2열=subtotal) COLSPAN=2 구조를 전사 규칙로
일반화하려는 첫 시도.

**폐기 사유**: SB성보(2003Q3, pre-2015 K-GAAP)에서 이 규칙을 적용하면
조용히 틀린 값을 내는 회귀가 발생함을 `test_hyphen_negative_gate_r31.py`로
발견 — 이 명세/소계 서식과 pre-2015 K-GAAP의 비슷한 모양 서식이 **헤더
텍스트만으론 구분 불가**. **되돌림.** R125로 스코프를 좁혀 재도입.

---

## R125. `parser/xml/table_extractor.py`/`fin2/extract/report_lines.py` —
명세/소계 중복 서브타입 열 해석을 **2015+ 전용**으로 스코프 좁혀 재도입
(2026-09-15)

**배경**: 현대해상·다올투자증권·대신증권 등 2015+ 폴백 스캔 후속 실측 —
2015+ 보험/증권사 서식은 COLSPAN=2 하위열이 "명세행(1열)/소계행(2열)"로
역할이 고정돼 같은 행에서 둘 다 채워지는 일이 없음을 확인(사용자: "3개월
아래에 2열로 되어서 1열에 세부항목 2열에 subtotal... 연결 별도 동일한
형태").

**수정**: `_columns_from_grid()`/`parse_header_columns()`에
`allow_duplicate_subtype` 파라미터 추가, `select_by_header_columns()`에
`_pick_from_group()`(실값 정확히 1개면 채택, 전부 대시/공란이면 구조적 0,
그 외는 판정불가) 도입. 호출측(`report_lines.py`)이
**`report_fiscal_year>=2015`일 때만** `allow_duplicate_subtype=True`를
넘기도록 좁혀 SB성보류(pre-2015)는 이 분기를 절대 안 탐(R124 회귀 방지).

---

## R126. `parser/xml/table_extractor.py::_PERIOD_KEY_RE` — 달력날짜
기간라벨·전환일/설립일 참조열·괄호오타 3종 추가 인식 (2015+ 폴백 스캔 잔여
72건, 2026-09-15)

**배경**: R123+R125 적용 후에도 남아있던 잔여 72건 실측 재조사.

**3종**:
1. "제N기" 서수 체계 대신 달력 날짜/연도로만 기간을 표기하는 회사들
   ("2015.03.31", "2015-03-31", "2015년 1Q", "2018년 12월" 등) — 신라젠·
   FSN·우리금융지주·티로보틱스·토박스코리아 실측.
2. 전환일/설립일 자체를 가리키는 참조열(분할·전환 신설법인).
3. "제N당)기"/"제N전)기"류 여는 괄호 누락 오타.

**수정**: `_PERIOD_KEY_RE`에 각각 대안 추가.

---

## R127. `fin2/extract/text.py::_looks_like_equity_changes_header()`(신규) —
원문 캡션 오류로 자본변동표(SCE) 데이터가 CF/IS/BS로 오적재 (2026-09-15)

**배경**: header-fallback 잔여 14건 재조사 중 발견 — 단순 미인식이 아니라
**실제 데이터 오염**.

**원인**: 한화투자증권(00148610) 20200515000970·비큐AI(00980043)
20210323000745 — 원문 자체가 "라. 연결현금흐름표"/"라. 현금흐름표" 캡션을
자본변동표(SCE) 데이터 표 바로 앞에 잘못 붙여놓고(문서 작성 오류), 진짜 CF
데이터는 그 뒤 별도 무제목 표에 있었다. 표제만 믿고 검증 없이 붙이는 기존
로직이 SCE 데이터를 CF/IS/BS로 오적재.

**수정**: `_looks_like_equity_changes_header()` 신설(SCE 특유의 자본항목
열이름 3개 이상 동시 검출) — `_detect_body_statement_tables()`의 "정상
서식"(제목+데이터 한 표) 분기에 `misattached_sce` 가드로 배선.

---

## R127b. 같은 함수 — SCE 오염 가드를 "제목표/데이터표 분리 서식" forward-scan
경로에도 확장 (같은 날 후속, 2026-09-15)

**배경**: "2015+ BS/IS/CF layer2 오적재 청소" 요청으로 전수 스캔하다 R127
사각지대 발견 — R127은 "제목+데이터가 한 표"(정상 서식)만 가드했다.

**원인**: 현대차증권(00137997) 20180515002185 IS_C는 다른 경로(제목표/
데이터표 분리 서식의 forward-scan)를 탄다 — 각주 문장("...연결포괄손익
계산서는...")이 `title_text_owned`에 의해 본문 제목처럼 오분류돼(단순
텍스트 포함 매칭이라 각주 속 재무제표명에도 반응) forward-scan이 SCE 요약
표를 IS 데이터로 잘못 연결.

**수정**: forward-scan 루프에도 `stmt != "SCE" and _looks_like_equity_
changes_header(nxt)` 가드 확장.

**전수 재검증**: 전수 스캔+개별 재처리 결과 현대차증권 1건만 잔존 →
`--corp` 개별 재적재로 해소, 재검증 0건 잔존 확인.

---

## R128. 같은 파일 `_PERIOD_KEY_RE` — "당N분기"/"전N분기" 표기가 서수
브랜치에 접두어 무시되고 병합 (2026-09-15)

**배경**: 4개 이상치 카테고리(IS_separate/IS_consolidated/CF_consolidated/
CF_separate) 재검증 중 발견(바이오솔루션 20161114001893 IS 별도 실측).

**원인**: "당3분기"/"전3분기"(상대어+숫자+분기, 서수 없는 관행) 헤더에서
`_PERIOD_KEY_RE`의 서수 브랜치가 R123("제" 접두 옵션화)의 부작용으로 "당"/
"전" 글자를 그냥 건너뛰고 "3분기"부터 매치해버렸다 — "당3분기"와 "전3분기"
둘 다 `period_key="3분기"`로 병합돼 당기/전기가 같은 rank로 합쳐졌다.

**수정**: `당\s*[1-4]\s*분\s*기|전\s*전\s*[1-4]\s*분\s*기|전\s*[1-4]\s*분\s*기`
전용 브랜치를 서수 브랜치보다 먼저 배치.

---

## R128b. 같은 파일 — 2자리 연도 축약형+N분기("19년 3분기") 미인식 (2026-09-15,
CF_separate 이상치 재검증)

**배경**: 4개 이상치 카테고리 재검증 후 CF_separate ≤10 97건을 최신 코드로
자동 재추출·비교(65건은 이미 R123~R128 수정으로 해소), 값이 그대로인 25건을
개별 대조하다 발견 — 이노시뮬레이션(20191129001722) CF 연결(THEAD 없음),
"19년 3분기"/"18년 3분기"(연도 2자리 축약형+N분기) 미인식으로 당기/전기
병합, 73행 중 다수 유실.

**수정**: `_PERIOD_KEY_RE`에 `\d{2}\s*년\s*[1-4]\s*분\s*기` 등 2자리 연도
대안 추가(4자리 연도 브랜치와 매치 순서 충돌 없음 확인).

**같은 커밋에 포함된 R118 후속 2건**: DSC인베스트먼트(20230515002273)
IS 별도, 이랜시스(20190401000391) CF 별도 — 위 R118 항목 참고.

---

## R129. `parser/xbrl_instance/taxonomy_linkbase.py::_drop_prohibited_only_locs()`
(신규) — `presentationArc`/`calculationArc`의 `use="prohibited"` 무시로 인한
값 중복 (2026-09-15)

**배경**: CF_separate 이상치 재검증 중 XBRL 소스 필링(코아스템켐온
20151126000316)에서 "단기금융상품의 처분"/"유형자산의 취득"/"무형자산의
취득" 3개 계정이 `report_lines`에 정확히 2번씩 중복 저장됨을 발견.

**원인**: DART 표준 taxonomy는 회사가 실제로 안 쓰는 표준 계정과목도 전부
`<link:loc>`+arc로 나열해두고, 그 arc를 `use="prohibited"`로 명시한다(실측:
`dart_ProceedsFromSalesOfShortTermFinancialInstruments` arc는
`order=50 use="prohibited"`, 회사 확장 태그의 arc는 `order=4 use="optional"`
— 회사는 표준 계정 대신 자기 확장 태그를 쓴다는 뜻). 수정 전엔 `use` 속성을
안 읽어 prohibited 표시된 표준 계정 loc도 트리에 남았고, 우연히 fact가 있어
3개 계정이 정확히 2번씩 중복 방출됐다.

**수정**: `_drop_prohibited_only_locs()` 신설 — `presentationArc`/
`calculationArc` 양쪽 파싱 루프에서 `use="prohibited"`인 arc의 대상 loc을
추적, `optional`로도 안 걸린 loc만 최종 제거.

---

## R130. `fin2/extract/report_lines_xbrl.py::_emit_missing_cf_lines()`(신규) —
CF 통계에 BS/IS와 같은 "트리-미연결 시 fact 직접조회 백업" 경로 부재
(2026-09-15)

**배경**: "XBRL-only 필링 7건"(본문 XML 없이 XBRL zip만 존재)을 "XBRL 태그
자체가 최소한만 달린 원문 한계"로 분류했던 판단이 틀렸음을 사용자가 DART
웹 화면(현대에이치티 20150518000061 현금흐름표 스크린샷)으로 반박, 재조사해서
발견.

**원인**: 인스턴스에 4개 기간 × 별도/연결 기준의 완전한 현금흐름표 값이
전부 태깅돼 있었다(당기순이익/영업·투자·재무활동현금흐름/이자지급·수취/
배당금수취/법인세납부/환율변동효과/기초·기말현금). 문제는 이 필링들의
표시(presentation) 링크베이스가 낡은 taxonomy 버전이라 이 개념들 중 상당수를
트리 노드로 연결해두지 않았다는 것 — R129에서 고친 BS/IS의 "flat forest"
(총계 트리 연결 누락)와 본질적으로 같은 유형. BS/IS는 이미
`_emit_missing_totals()`(트리-미연결 시 fact 직접조회 백업, `_REQUIRED_
TOTALS_BY_STATEMENT`)로 우회됐지만, CF에는 이 경로가 없어 트리에 안 걸린
값은 통째로 누락됐다.

**수정**: `_emit_missing_cf_lines()` 신설 — CF는 BS/IS와 달리 단일 "Assets"류
총계가 없어 개별 라인아이템 목록(`_REQUIRED_CF_LINES`)을 쓰고, 여러 개념이
`dart:` 확장 네임스페이스(버전마다 URI가 바뀜)라 로컬명 기준 전 네임스페이스
검색(`_find_qnames_by_local`)으로 조회.

**잔여 갭(이번 수정 범위 밖, 테스트로 명시 고정)**: 트리엔 이미 노드로 있지만
당기(col0) 값이 원문에도 없는 개념(예: 이자지급/재무활동현금흐름 — 그
분기엔 실제 공란)은 `_resolve_columns`의 별개 설계(col0 없으면 그 개념
전체를 버림)로 인해 전기(col1) 값이 있어도 여전히 못 건짐.

**검증**: 현대에이치티 CF_separate 8→20행. XBRL-only 7건 전체 같은 패턴
확인(코아스템켐온·경남제약·플레이그램×2·아스타·썸에이지).

---

## R131. `parser/xml/table_extractor.py::select_by_header_columns()` —
무표지 병합군 "값 동일" 판정을 예외목록 없이 일반화 (2026-09-16)

**배경**: 재적재 완료 후 4개 이상치 카테고리 재검증 중 KD(케이디) 2020Q1
20200515002825 발견 — IS 별도 헤더가 "제47기 분기"/"제46기 분기"를 구분
텍스트 없는 COLSPAN=2 병합군으로 반복하는데, 두 물리열이 행마다 예외 없이
완전히 같은 값을 담고 있었다(매출액 10,672,141,199 이 두 열 모두 동일 등).

**원인**: `select_by_header_columns()`의 no-subtype 분기는 이 "값 동일"
판정 자체는 R116 도입 때부터 갖고 있었지만(드림시큐리티류), `allow_three_
month_as_cumulative` 플래그(Q1 누적-공란 대체라는 전혀 다른 취지로 설계된
게이트) 뒤에 갇혀 있었다. 예외목록에 없는 KD 같은 필링은 이 게이트를 못
통과해 매출액·영업이익·당기순이익 등 핵심 행 전체가 유실됐다(수정 전
IS_separate 4행).

**수정과 결정**: 값이 완전히 같은 경우는 R6 이 막으려는 "서로 다른 값 중
하나를 짐작"하는 판정불가 상황이 **아니다**(모호함 자체가 없다) — 사용자
확정: "값이 완전히 같으면 항상 채택해도 R6 취지에 안 어긋난다". 이 분기를
`allow_three_month_as_cumulative` 게이트에서 떼어내 rcept 예외목록 없이
항상 적용하도록 일반화했다. R116(공란 대체)/R120(서로 다른 값 중 마지막
열 채택)은 각각 진짜 판정을 담당하므로 예외목록 그대로 유지 — 이번
일반화 대상은 "값 동일" 케이스 하나뿐이다.

**검증**: KD IS_separate 4→32행(매출액~당기순이익 전부 항등식 성립 확인).
`test_r116_merge_group_duplicate_equal_values_accepted_when_allowed()`
갱신(플래그 없이도 채택하는 것이 새 기대값), 전체 스코프 테스트(1,034건)
회귀 없음(사전에 존재하던 뉴인텍 basis_fallback 실패 1건과 무관 확인).
`fin2/tests/test_report_lines.py::test_r131_kd_...`.

---

## R132. `fin2/extract/report_lines.py::_MANUAL_UNIT_OVERRIDE_MULTIPLIER_
RCEPTS`(신규) — 자기모순 단위선언 rcept 단위 강제 교정 (2026-09-16)

**배경**: 같은 재검증 중 넷마블 2017FY 20180402005173 발견 — 연결·별도
IS·CF·BS 표 전부 "(단위: 백만원)"이라고 선언돼 있는데, 실제 셀 값은 이미
원(WON) 단위 그대로다. 별도 영업수익 "1,668,776,658,371"을 정말 백만원
으로 읽으면 1.67×10¹⁸원(불가능)이 되고, 연결 영업수익 "2,424,755,040,569"
는 그대로 2.42조원(넷마블 2017 실제 공시 매출과 일치)이라 원문 자체의
단위 오기재임을 확정할 수 있다.

**원인**: `_AMOUNT_SANE_MAX`(1경원 상한, R3)가 ×1,000,000 을 적용한
결과(10¹⁸ 오더)를 정상적으로 거부 — 값 자체는 안전장치가 맞게 걸렀지만,
그 결과 매출액·영업이익·당기순이익 등 핵심 행 대부분이 통째로 결측
처리됐다(수정 전 IS_separate 12행 중 대부분 유실, CF/BS 도 같은 패턴).

**수정**: `_MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS: dict[str, int]`
신설(rcept_no → 강제 배수) — `_emit_section_lines()`에서 표별 선언 배수
해석보다 먼저 이 예외목록을 확인해, 있으면 선언값을 무시하고 강제로
덮어쓴다(`unit_source="manual_unit"`로 근거를 남김). 문서 전체(4개 표×
연결/별도)에 걸친 자기모순이라 표 단위가 아니라 rcept 단위로 스코프를
잡았다.

**일반화하지 않는 이유**: "선언 배수가 실제 자릿수와 10⁶배 어긋남"은
단위 declaration 파싱 성공/실패와 무관한 필자의 오기재라, 다른 필링에도
이 정도로 큰 자기모순이 흔하다고 가정할 근거가 없다 — 원문대조로 확인된
rcept 에만 좁힌다(R6 유지, R121/R118류와 같은 정책).

**검증**: 넷마블 2017FY 문서 전체 라인 수 대폭 증가(IS_separate 12→48,
IS_consolidated →69, CF_separate →108, CF_consolidated →132, BS 도 동반
증가). 연결 영업수익 2,424,755,040,569원이 실제 공시 매출과 일치함을
대조 확인. `fin2/tests/test_report_lines.py::test_r132_netmarble_...`.

**후속(2026-09-16, 같은 날 — BS 전수스캔, 사용자 지시 "1,3,5번 이어서")**:
BS_consolidated≤20/BS_separate≤16 저조행수 스캔(`is_final=TRUE`)에서 같은
유형(재무상태표가 "(단위 : 백만원)"이라 선언했는데 실제 셀 값이 이미
원(WON))을 4건 추가 발견 — 아즈텍WB 20191114000246(2019 Q3)·HL D&I
20210817001851(2021 H1)·동성케미컬 20170814002311(2017 H1)·소노스퀘어
20241114002786(2024 Q3). 넷마블과 같은 메커니즘(`_AMOUNT_SANE_MAX`가
×1,000,000 적용 후 초과값인 총계행만 거부 → 총계행 결측 + 문턱 바로
아래인 세부항목행은 비현실적으로 큰 값으로 잔존)이라 BS 만 저조행수로
걸렸다(IS/CF 도 같은 문서 내에서 총계행이 빠졌을 수 있으나 이번 스캔
범위 밖). 각 필링 원문 내 별도 표(부채비율 주석 등, 다른 단위로 같은
계정 재공시)와 대조해 확정 — 예: 아즈텍WB 자산총계 원문 그대로
114,055,541,787원이 부채비율 주석의 "(단위:천원)" 부채총계
20,117,419천원=20,117,419,000원과 일치. `_MANUAL_UNIT_OVERRIDE_
MULTIPLIER_RCEPTS`에 4건 추가(배수 1). `reload_report_lines_corp.py`로
4개사 전체 재적재 완료. 테스트:
`test_r132_followup_bs_self_contradictory_declared_unit_overridden_to_won`.
★교훈: R132 최초 발견 시 "다른 필링에 이 정도 자기모순이 흔하다고
가정할 근거가 없다"고 판단했으나, 같은 세션에서 BS만 스캔했는데도 바로
4건이 더 나왔다 — 이 자기모순 패턴 자체는 드물지 않다(다만 자동 일반화는
여전히 위험하므로 원문대조 확정 후 개별 추가하는 정책은 유지).

---

## R133. `fin2/extract/report_lines_xbrl.py::_emit_missing_leaf_lines()`
(`_emit_missing_cf_lines`에서 일반화) — IS 통계도 CF와 같은 개별 항목
트리-미연결 백업 필요 (2026-09-16, 사용자 지시로 R130 즉시 확장)

**배경**: 넵튠 20150817000007(2015 H1) IS_separate 재검증 — 인스턴스에
`dart:OperatingIncomeLoss`(영업이익)/`ifrs:ProfitLossBeforeTax`(법인세비용
차감전순이익)/`ifrs:ProfitLossFromContinuingOperations`(계속영업이익)가
모두 당기 컨텍스트까지 정상 태깅돼 있는데도, 표시 트리엔 SGA·금융수익·
`_REQUIRED_TOTALS_BY_STATEMENT["IS"]`가 이미 백업하는 ProfitLoss/
ComprehensiveIncome 만 연결돼 있었다(수정 전 IS_separate 4행) — R130이
CF에서 고친 것과 똑같은 flat-forest 유형이 IS의 waterfall 중간 항목에도
있음을 확인.

**설계**: `OperatingIncomeLoss`는 IFRS 국제표준에 대응 개념이 없어 DART가
`dart:` 네임스페이스로 직접 확장한 계정이라(CF의 다수 개념과 같은 사정),
`_emit_missing_totals()`의 고정 `ifrs`/`ifrs-full` 네임스페이스 조회로는
못 찾는다. R130의 `_emit_missing_cf_lines()`를 `_emit_missing_leaf_lines()`
로 일반화(`statement` 매개변수화, `_REQUIRED_LEAF_LINES_BY_STATEMENT =
{"CF": _REQUIRED_CF_LINES, "IS": _REQUIRED_IS_LINES}`로 디스패치) — CF쪽
동작은 완전히 그대로(같은 리스트·같은 호출부, `source_ref` 접미사 문자열만
"xbrl_tree_gap_cf_line"→"xbrl_tree_gap_leaf_line"로 통일, 순수 진단용
컬럼이라 하류 소비 없음 확인). `_REQUIRED_IS_LINES = (OperatingIncomeLoss,
ProfitLossBeforeTax, ProfitLossFromContinuingOperations)`.

**의도적으로 안 넣은 것**: Revenue/CostOfSales/GrossProfit — 넵튠 인스턴스엔
`Revenue` fact 자체가 아예 태깅돼 있지 않다(직접 grep으로 확인, 트리 문제가
아니라 진짜 결측). 이 함수가 되살릴 근거(트리엔 없지만 fact는 있다)가 없는
개념을 목록에 넣는 건 추측이라 R0 원칙 위반 — 이후 다른 필링에서 이 패턴이
실측 확인되면 그때 추가.

**검증**: 넵튠 IS_separate 4→7행(영업이익 -30,393,449 / 법인세비용차감전
순이익 -27,151,170 / 계속영업이익 -22,961,058). 계속영업이익=당기순이익
(중단영업 없는 회사, 항등식 교차검증). 전체 스코프 테스트(1,037건) 회귀
없음(뉴인텍 basis_fallback 무관 실패 1건 제외). `fin2/tests/
test_xbrl_instance.py::test_r133_is_leaf_gap_backfill_recovers_waterfall_
subtotals`.

---

## R134. `parser/xml/table_extractor.py::_header_rule_name()` — SCE 전용
`allow_date_label=True`에서도 "기수" 규칙이 계속 걸려 앵커 행(기초/기말
잔액)이 통째로 드롭 (2026-09-17)

**배경**: 2015+ SCE(자본변동표) 전수 이상치 스캔(히스토그램 기반 임계값
산정 → 기초+변동=기말 자동 항등식 검증 → 원문대조, 438건 후보 중 59건
원문대조 완료) 중 발견. `allow_date_label=True`는 이미 "기간 날짜" 규칙
(예: "2023.01.01~2023.12.31")을 꺼서 SCE의 날짜 라벨 행이 헤더로 오판정
드롭되는 걸 막고 있었는데, **"기수" 규칙**(`제\s*\d+\s*기` 패턴 + 원/%
없으면 헤더로 판정, BS/IS/CF 주석 헤더 셀 판정용)은 별개 규칙이라 여전히
켜져 있었다.

**증상**: SCE 앵커 행 라벨이 "2014.04.01 (제26기 분기초)"처럼 날짜에
"제N기"까지 같이 붙으면(원/% 없음) "기수" 규칙에 걸려 행 전체(모든 열)가
드롭됐다. 메이슨캐피탈(20150817001754) 원문대조로 확정.

**수정**: `_header_rule_name()`의 "기수" 판정 조건에 `not allow_date_label`
을 추가 — SCE(`allow_date_label=True`)에서는 "기수" 규칙도 함께 꺼진다.
BS/IS/CF 경로는 `allow_date_label=False`라 영향 없음.

**검증**: 본문(BS/IS/CF/SCE) 전체 재적재(104,318건)로 백필. `pytest
tests/ fin2/tests/` 1044 passed(기존 무관 실패 1건 제외).

## R135. `fin2/extract/report_lines.py::_grid_body_rows()` — 라벨 영역에
물리 셀이 둘 이상인 행에서 physical[0]만 라벨로 채택, 두 번째 이후 라벨
셀 유실 (2026-09-17, R134와 같은 스캔에서 발견)

**배경**: 위 R134와 같은 SCE 전수 이상치 스캔에서 발견. `_grid_body_rows()`
가 라벨 영역(`grid_col < offset`)에 물리 셀이 둘 이상인 행 — ROWSPAN
카테고리 헤더("자본의 변동")와 그 아래 구체 항목명("배당금지급")이 같은
행에 나란히 있는 경우 — 에서 `physical[0]`(첫 번째 셀)만 라벨로 쓰고
두 번째 이후 라벨 셀을 통째로 버리고 있었다.

**영향**: 원익피앤이(20161128000288) 원문대조로 확정 — SCE "자본의 변동"
행이 실은 "자본의 변동>배당금지급"이었다. **금액 자체는 원래도 정확**
(offset 정의상 라벨 영역엔 금액이 나온 적이 없어 값 손상은 아니었음) —
라벨 텍스트만 부정확했던 순수 표시 결함.

**수정**: 라벨 영역 물리 셀(`grid_col < offset`)이 둘 이상이면 전부 ">"로
이어붙인다(`_label_dict_from_header`의 헤더 다단 조인과 같은 관례를 본문
행에도 적용). `header_hint` 판정은 의도적으로 `physical[0]` 하나만
계속 본다 — 뒤에 붙는 구체 라벨까지 합치면 header_hint 정규식(예:
"구분과목")이 새로 오탐할 위험이 있어 보수적으로 유지.

**검증**: SCE는 R134와 같은 본문 재적재로, 주석(note_lines, 2.47억 행 중
R135 영향 7.01%=1,772만행)은 전용 스크립트(`scripts/reload_note_lines_
r135_2026-09-17.py`, 신규 `note_line_reload_progress` 체크포인트 테이블)
로 별도 백필(104,232건, 오류 0). `pytest tests/ fin2/tests/` 1044
passed(기존 무관 실패 1건 제외).

**★참고(2026-09-18)** — 이 두 규칙은 commit `d03e177`에서 이미 구현·백필
됐으나 그때 이 문서에 등재가 안 됐다(커밋 메시지에만 R134/R135로 남음).
같은 날 이후 세션이 PDF 복구 경로 작업에 R134/R135를 새로 배정하려다
번호가 이미 코드/테스트(`parser/xml/table_extractor.py`,
`fin2/extract/report_lines.py`, `fin2/tests/test_header_rule_name_r134_
sce.py`, `fin2/tests/test_grid_body_rows_r135_multicell_label.py`)에 쓰여
있는 걸 뒤늦게 발견 — 그 PDF 작업은 R136/R137로 재배정하고(코드/테스트/
설계문서의 R134/R135 언급도 전부 R136/R137로 같이 수정) 이 문서에 SCE
몫(R134/R135, 위)을 뒤늦게 등재했다.
"신규 규칙은 반드시 이 문서에 먼저 적는다"는 원칙이 지켜지지 않아 생긴
사례 — 커밋 메시지·테스트 파일명에만 번호를 쓰고 이 문서에 실제 절을
안 쓰면, 다음 세션이 같은 번호를 "비어있다"고 오판해 재사용할 수 있다.

---

## R136. `fin2/extract/pdf.py` — 콤마 없는 단독 주석번호가 금액으로 오인식되는
결함(has_note_col 미배선) 수정 — XML 경로(R19/R65)와 동형 수정 (2026-09-18)

**배경**: 솔트웨어(01390399) 20220802000208(2022 H1, XML archive 손상으로
PDF 복구 경로 사용) 사용자 원문대조로 발견. `_looks_like_real_amount()`는
콤마 있는 다중 주석참조("4,5,6")는 걸러내지만 **콤마 없는 단독 주석번호
("14"/"9"/"10"/"11")는 무조건 "진짜 금액"으로 통과**시킨다(함수 자체 계약,
`fin2/tests/test_pdf.py::test_looks_like_real_amount_accepts_proper_
thousands_grouping`의 `"148"` 케이스가 이미 이 계약을 고정하고 있다 —
그래서 이 함수만으로는 원리적으로 못 고친다). 결과: 라벨 바로 다음이
콤마없는 단독 주석번호인 행은 숫자 개수가 헤더 기간수를 초과해 **행 전체가
드롭**(header 감지 성공 시, 결측) 되거나, header 감지가 실패하는 경로에선
**주석번호 자체가 금액으로 저장**(오염, 훨씬 위험 — 2026-09-17 세션에서
`report_lines.unit_source='pdf' AND value_won BETWEEN 1 AND 99` 스캔으로
1999~2002년대 최소 2,407개 필링에서 재현 확인, 라벨이 "(주석"으로 잘려있는
1,193행은 스모킹건 수준 확정).

★핵심: XML 경로(`parser/xml/table_extractor.py`)는 이미 2026-09(R19/R65)에
같은 문제를 두 신호(`_table_has_comma_note_column`/`_table_has_note_header`
OR 결합)로 해결해뒀다. PDF 경로도 동형 신호(`PdfTableHeader.has_note_col`,
헤더 줄의 "주석"/"Note" 텍스트 탐지)를 **이미 계산은 하고 있었는데 어디에도
쓰지 않고 버리고 있었다**(`has_note_col` 필드 정의·대입만 있고 읽는 코드
0곳, grep으로 확인) — XML 쪽이 이미 검증한 해법을 PDF 쪽에 배선만 하면
되는 문제였다.

**수정**: `_parse_single_line()`/`_parse_numline_tokens()`에 `has_note_col`
매개변수 추가 — 라벨 바로 다음 자리(첫 토큰, i==0)에서만, `has_note_col=
True`이고 토큰이 `_NOTE_REF_PATTERN`(콤마 유무 무관 주석번호 형태)에 맞고
`_AMOUNT_GROUPED_PATTERN`(정상 3자리그룹 금액)엔 안 맞으면 주석번호로 보고
건너뛴다(XML `table_extractor.py`의 두 패턴을 그대로 import해 재사용, 새
정규식 발명 안 함). `facts_from_text()`에서 `header = _parse_pdf_table_
header(region)` 계산을 **`_iter_data_lines*` 호출보다 먼저**로 옮겨(원래는
라인부터 파싱한 뒤에야 header를 알아 걸러낼 기회가 없었다) `has_note_col`을
`_iter_data_lines`/`_iter_data_lines_multiline`/`_iter_data_lines_from_
table_rows` 세 소비 경로 전부에 배선. **`_parse_numline_tokens`의 3줄
이중언어(숫자단독줄) 호출부는 배선 안 함** — 그 레이아웃에서 주석번호가
숫자단독줄에 섞여 나오는 실측 사례가 아직 없어 증거 없는 확장은 보류(R6).

**검증**: `fin2/tests/test_pdf.py` 신규 6건(솔트웨어 실측 4계정 재현 +
콤마다중참조 이중필터 없음 확인 + 정상행 비영향 확인 + region 종단 확인).
`recover_one()` 재실행 실측: 솔트웨어 BS separate 17→20행(보통주자본금
648,200,000 / 이연법인세부채 42,726,070 / 주식발행초과금 11,764,905,920
전부 정확히 복구, 원문 노트번호와 일치). 잔여 1개(미처분이익잉여금)는 이
버그와 무관 — `account_maps/bs_accounts.py`가 "총액 이익잉여금과 혼동
방지" 목적으로 2026-07-18에 의도적으로 지도에서 제거해둔 것(unknown 처리),
사용자 원문대조 확정값(11,495,730)으로 `unit_source='manual'` 개별 삽입.
CF의 별개 결함(스코프 밖 "단기금융상품" 가짜행 1개, 원인 미조사 — 앵커
리전 경계 오판 추정)은 이 수정과 무관하게 남아 데이터에서 개별 삭제.
★후속(같은 날, R137) — "계정지도에서 의도적으로 제외"라는 이 설명은
캐노니컬 개념(총액 이익잉여금 vs 미처분이익잉여금) 혼동 방지로서는 맞지만,
그게 **저장 자체를 막아도 되는 이유는 아니었다** — PDF 경로만의 별도 설계
결함(account_mapper 매핑 성패를 report_lines 저장 게이트로 오용)이었음이
드러나 R137로 근본 수정. 자세한 내용은 아래 R137 참고.
`pytest tests/ fin2/tests/` 1051 passed(기존 무관 실패 1건 그대로,
`test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix`).

**★소급 백필 미실시(다음 세션 후보)** — 2,407개 필링(1999~2002년대) 전체
재적재는 이번 세션 스코프 밖(별도 Track C 캠페인으로 이월, 사용자 지시
2026-09-18 "2015+로 돌아가서 마무리하자"). 코드 수정 자체는 완료·검증됐고
솔트웨어(2015+ 유일 사례) 1건만 데이터 반영 완료.

## R137. `fin2/extract/pdf.py::facts_from_text()`/`collector/pdf_lines_
sync.py::facts_to_report_lines()` — "저장"과 "캐노니컬 매핑"이 뒤섞여 있던
설계 결함 근본 수정 (2026-09-18, 같은 날 R136 후속)

**배경**: R136 조사 중, 솔트웨어 BS separate에 남은 마지막 결측 1건
(미처분이익잉여금)이 R136(주석번호 오인식)와 무관한 **별개 원인**임을 확인
— `account_maps/bs_accounts.py`가 "이익잉여금(총액)과 미처분이익잉여금(총액의
하위 sub-line)을 혼동하면 안 된다"는 이유로 이 라벨을 계정지도에서 의도적으로
제거해둔 상태(`unknown.미처분이익잉여금`)였다. 사용자가 이 설명 자체에
날카로운 반문을 제기: "sub total 아래에 세부항목으로 두면 될 것 같은데, 이
회사 보고서만 봐서는 파서에서 제외한다는 논리가 이해되지 않는다" — 캐노니컬
개념 혼동을 피하려는 판단이 왜 **저장 자체를 막는 근거**가 되어야 하는지.

**근본원인 확정**: 코드로 직접 대조한 결과, 이 질문이 정확했다.
- **XML 정상 경로**(`fin2/extract/report_lines.py`, 전체 필링의 절대다수)는
  자기 docstring에 명시된 대로 "판단 없이 충실전사"한다 — `account_mapper.
  map()`을 아예 호출하지 않는다(`canonical_account` 컬럼 자체가 없음).
  계정지도에 있든 없든 원문 라벨 그대로 report_lines에 저장되고, 캐노니컬
  해석은 계층3(`combine.py`)에서 나중에 따로 한다.
- **PDF 복구 경로**(`fin2/extract/pdf.py::extract_pdf_facts()`, 원래는
  1999~2003년대 소수 핵심계정 항등식 검증용으로 설계됐다가 report_lines
  전체를 채우는 용도로 재사용됨)만 `if not canon or canon.startswith
  ("unknown."): continue`로, **계정지도 매핑에 실패한 라벨은 저장 자체를
  거부**했다. "미처분이익잉여금"뿐 아니라 계정지도에 없는 임의의 라벨이
  이 경로에서는 전부 조용히 통째로 빠질 수 있었다는 뜻 — 솔트웨어 사례는
  이 구조적 결함의 한 표본일 뿐, 범위가 훨씬 넓다.
- `collector/pdf_lines_sync.py::facts_to_report_lines()`가 `ExtractedFact→
  ReportLineRow` 변환 시 `f.canonical_account.split(".", 1)[0].upper()`로
  `statement`(BS/IS/CF)를 **유추**하는 게 이 게이트가 생긴 진짜 이유였다 —
  `extract_pdf_facts()`는 앵커(`anc.statement`) 단계에서 이미 소속
  재무제표를 알고 있는데, 그 정보를 `ExtractedFact`에 직접 실어 보내지
  않고 canonical_account를 거쳐 역산해야 했던 게 설계상 병목.

**수정**: "저장"과 "캐노니컬 매핑"을 분리(①~③), 그 분리로 노출된 리전
경계 결함 2건도 같은 세션에서 근본수정(④~⑤ — 사용자 확인 후 진행, 아래
"부작용 발견" 참고).
1. `fin2/extract/xbrl.py::ExtractedFact`에 `statement: str | None = None`
   필드 신설 — canonical_account와 독립적으로 원문상 소속 재무제표를 표시.
2. `extract_pdf_facts()`(`facts_from_text()`): 매핑 실패(`unknown.`)·섹션
   불일치(라벨 오매핑)·세전이익 오매핑가드 세 경우 전부 `continue`(행 드롭)
   대신 `canon = None`으로만 처리 — 행 자체(`label`/`amount`)는 그대로
   저장, `ExtractedFact.statement=anc.statement`를 항상 채워 넘긴다. 물리적
   불가능값 필터(10^16 절대상한·핵심 4개념 매그니튜드 캡)는 canon 유무와
   무관한 별개 안전장치라 그대로 유지.
3. `facts_to_report_lines()`: `statement` 결정 시 `f.statement`를 최우선
   사용, 없으면(HTML 경로 등 아직 이 필드를 안 채우는 구경로) 기존처럼
   `canonical_account`에서 유추, 그것도 없으면 스킵(둘 다 없으면 소속
   재무제표를 알 방법이 없는 진짜 예외 케이스만 남음).

**부작용 발견(같은 날, 구현 직후 end-to-end 재검증 중)**: 위 ①~③을 실제
솔트웨어 필링에 재실행해보니, CF separate 리전에 "제2기(전전기)"=110,
"특정금전신탁"=12,493,953,976, 지분율 표("(주)손앤컴퍼니"/"기타"/"합계")
같은 **명백히 CF가 아닌 값**이 같이 따라 나왔다. 원인: `_find_anchors()`가
문서에서 가장 마지막(다음 앵커가 없는) statement 앵커의 리전을
`end=len(text)`로 잡아, 그 뒤 이어지는 **주석(note) 섹션 전체**가 통째로
그 리전에 포함되고 있었다(솔트웨어는 연결 대상이 없는 SPAC이라 CF
separate가 문서상 마지막 statement). 지금까지 이게 문제가 안 됐던 이유는
계정지도 매핑 실패(`unknown.`) 게이트가 이 노이즈를 **우연히** 걸러주는
방화벽 역할을 겸하고 있었기 때문 — ①~③으로 그 게이트를 없애면서 노출됐다.
사용자에게 "지금 같이 고칠지, 별도 세션으로 미룰지" 확인 후 "지금 같이
고친다"는 답변으로 계속 진행:
4. `_NOTES_SECTION_RE`(`재\s*무\s*제\s*표\s*주\s*석`, DART 표준 SECTION-2
   제목이자 PDF 페이지 각주에도 그대로 찍힘) 신설 — 각 앵커의 리전 `end`를
   계산할 때, 그 구간 안에서 이 패턴이 처음 나오는 위치가 있으면 거기서
   잘라낸다. 중간 앵커(이미 다음 앵커로 좁게 닫힌 리전)는 이 문구가 그
   범위 안에 나타날 일이 거의 없어 영향이 없는 범용 클램프.
5. 위 ④로 텍스트 리전은 깨끗해졌지만, `_lines_disagree_with_header()`가
   격자 폴백(`_table_rows_for_span`)으로 승격시키는 경로는 별개 결함이
   남아있었다 — `pdfplumber.extract_tables()`가 **페이지 단위**로 표를
   긁어와(문자 offset 무관) 클램프된 `end`와 같은 물리 페이지에 있는 다음
   섹션(주석 1번 "일반사항"의 주주현황 표 등)까지 같이 끌려왔다. 격자에서
   재구성한 각 행의 라벨이 이미 올바르게 클램프된 `region`(텍스트) 안에도
   실제로 존재하는지로 되짚어 필터링(없으면 드롭 — 결측이 오염보다 낫다).
6. (부수 발견) `_parse_pdf_table_header()`의 주석열 감지 정규식이 "주석"이
   붙어있는 경우만 잡고 "주 석"(자간공백 서식)은 놓쳤다 — 솔트웨어 CF의
   "나. 당기순이익 조정을 위한 가감"/"다. 영업활동으로 인한 자산부채의
   변동"(둘 다 주석번호 "17" 보유)이 이 갭으로 숫자개수 초과 판정을 받아
   드롭되고 있었다(R136와 동일 증상의 다른 헤더 서식 변형). `주\s?석|Note`
   로 정규식 확장.

**스코프**: ①~③(canon/storage 분리)은 **PDF 경로만**(사용자 지시 "PDF
경로의 저장과 캐노니컬 매핑을 분리"). `fin2/extract/html_viewer.py::
facts_from_sections()`도 구조가 완전히 동일한 게이트를 갖고 있어 같은
결함이 잠재하지만, 이번 세션 스코프 밖 — `.statement`를 안 채우는
구경로로 그대로 남겨뒀다(`facts_to_report_lines()`의 폴백 분기가 이 경로를
그대로 지원). ④~⑥(리전 경계·헤더 감지)은 PDF 경로 전체에 적용되는 범용
수정(특정 필링에 한정되지 않음).

**검증**: 신규 유닛테스트 6건(`fin2/tests/test_pdf.py::
test_unmapped_label_stored_with_null_canon_not_skipped`,
`test_last_anchor_region_clamped_at_notes_section_boundary`,
`test_header_note_column_detected_with_letter_spaced_label`,
`fin2/tests/test_pdf_lines_sync.py::test_facts_to_report_lines_keeps_
unmapped_pdf_fact_when_statement_set` 등) + 기존 회귀 2건(canonical_
account 대신 `.statement`로 재무제표 판정하도록 수정) 전부 통과.
`recover_one()` 솔트웨어 재실행 실측(원문 항등식 전부 재대조): BS
separate 21→23행(수동삽입했던 미처분이익잉여금 11,495,730과 R137로 추가
복구된 전환권대가 166,216,647 포함해 전부 `unit_source='pdf'` 자동
추출 — manual 행 소멸), CF separate 10→10행(내용 교체 — 노이즈 3건 제거
+ 누락됐던 "나"/"다" 세부항목 2건 복구, 항등식 영업에서창출된현금=당기
순이익+가감+변동 재확인), IS separate 8행(SCE 오염 4행 제거로 12→8).
`store_report_lines(overwrite_manual=True)`로 DB 반영 완료(최종
BS/CF/IS=23/10/8행, 전부 `unit_source='pdf'`). `pytest tests/ fin2/tests/`
1053 passed(기존 무관 실패 1건 그대로, `test_nyuintek_2007q1_dkme_style_
not_affected_by_this_fix` — R130 트랙 별개 이슈, R136/R137와 무관).

**소급 백필 미실시** — R136와 동일 사유·동일 스코프(2,407개 필링 Track C
캠페인으로 이월). 이번 세션은 솔트웨어(2015+ 유일 대상) 1건만 데이터 반영
완료, 코드 수정은 전체 PDF 경로에 적용됨(④~⑥은 범용이라 향후 백필 시
자동으로 같이 적용).

---

## R138. `scripts/scan_header_fallback_2015plus_2026-09-14.py` — R125
플래그(`allow_duplicate_subtype`) 미배선으로 2015+ 폴백 잔여 559건 중
548건(98%)이 오탐(false positive)이었음 확정 (2026-09-18)

**배경**: `docs/plans/report_lines_legacy_fallback_hardening_design_
2026-09-17.md`(구버전 헤더 파싱 폴백 고도화 설계) §3의 2026-09-17 재스캔이
"2015+ BS/IS/CF 표 559건이 `parse_header_columns()`로 미인식"이라고
보고했고, 그중 98%(548건)가 IS·상위 8개사(보험/증권/은행)에 집중돼
있어 "THEAD-IS 정밀화부터 착수"하기로 사용자와 합의했다. 8개사 중
현대해상(00164973) 표본 1건을 직접 열어 THEAD를 확인하는 중 발견.

**근본원인**: `fin2/extract/report_lines.py`(운영 경로)는
`report_fiscal_year>=2015`면 `parse_header_columns(table,
allow_duplicate_subtype=True)`를 호출한다(R125, 2026-09-15 — 보험/증권사
서식의 "명세/소계" COLSPAN=2 중복 서브타입 열 처리). 그런데 §3 재스캔에
쓰인 `scan_header_fallback_2015plus_2026-09-14.py`는 이 플래그 없이
(기본값 `False`) `parse_header_columns(tbl)`을 호출해서, **R125가 운영
경로에서 이미 정확히 해석하고 있는 표까지 "미인식"으로 오탐**했다.

**재검증**(559건 전체를 운영과 동일한 `allow_duplicate_subtype=
(fiscal_year>=2015)` 플래그로 재실행): 548건(98%)이 오탐, **진짜 잔여는
11건**(회사 6곳 — 안트로젠·대신증권·팬엔터테인먼트·에스바이오메딕스·
넥사다이내믹스·아이로보틱스). 이 11건도 report_lines 조회+항등식
검산(CF: 영업+투자+재무=현금증가, 기초+증가(+환율효과)=기말)으로
전부 정상값임을 확인 — 기존 위치기반 폴백(cum_map/multicol/else)이
이미 정확히 처리 중이라 **고칠 버그가 없다**. 상세 경위는 위 설계문서
§7 참고.

**부수 확인**: R125 문서 자체에 남아있던 미해결 의문("2026-09-14
스냅샷 1,333건 대비 메모리의 '1,319건 해소(1,333→14)' 수치가 안
맞음")도 이 스캔 스크립트 버그가 원인이었을 가능성이 높다(확정은
아님 — 그 세션 측정 방법 직접 재현은 안 함).

**수정**: `scan_header_fallback_2015plus_2026-09-14.py`의
`parse_header_columns(tbl)` 호출에 `allow_duplicate_subtype=
(fiscal_year >= 2015)` 배선 — 운영 경로와 동형화. 이 스크립트를 다시
돌리면 이제 진짜 잔여(11건 근방)만 나올 것으로 예상(재실행으로
재확인은 안 함 — 이미 수동 재검증으로 559→11 확정됨).

**교훈**: 스캔/감사 스크립트가 운영 코드와 **다른 인자로 같은 함수를
호출**하면, 운영 코드가 이미 고친 결함을 계속 "미해결"로 재보고할 수
있다 — 진단 스크립트를 새로 만들 때 운영 호출부의 인자를 그대로
복사했는지 확인할 것(R9 원칙의 한 변형: 검증 스크립트 자체도 검증
대상이다).

---

## R139. `store_report_lines()` — 원문대조 완료(`layer2_review_queue.status='pass'`)
행도 `unit_source='manual'`과 같은 방식으로 재적재 보호 (2026-09-18)

> ★**2026-09-24 폐지·대체(사용자 결정)** — 아래 하드 차단은 **R167** 로 대체됐다.
> pass 판정은 이제 `verification` 스키마가 들고, 재적재 자체는 허용하되 **내용이 실제로 바뀐
> 경우에만** 그 필링을 pending 으로 되돌려 재검증한다. `overwrite_reviewed` 인자는 호환용으로
> 받기만 한다. 이 절은 이력으로 남긴다.

**배경**: 2015+ 전체를 대상으로 "화면에서 원문대조 → DB의 BS/IS/CF/SCE
값과 비교"하는 캠페인을 자동화하는 설계 중, 사용자가 요구사항을 명확히
했다 — "눈으로 확인된 것과 같은 효과가 있어야 하고, 확인된 것은
manual 처리해서 재적재에서 제외하고, 이전에 manual 처리된 것도 제외돼야
한다." 이걸 실제로 보장하려면 "확인 완료" 표시가 **어느 재적재 경로로
와도** 그 필링을 보호해야 하는데, 코드를 확인해보니 그렇지 않았다.

**발견**: `layer2_review_queue.status='pass'`(`scripts/layer2_review.py
pass` — 사람 또는 원문대조 에이전트가 그 rcept의 report_lines를 원문과
대조해 통과시킨 표시)는 `layer2_review_queue` 테이블 자체의 컬럼만
바꿀 뿐, `report_lines`에는 어떤 흔적도 남기지 않는다(`_mark()`,
`scripts/layer2_review.py:292-299`). 이 상태를 실제로 존중해서 재적재를
건너뛰는 곳은 `reload_report_lines_2015plus_2026-09-12.py`·
`reload_report_lines_xbrl_2015plus_2026-09-15.py` 딱 2개 스크립트뿐이고,
둘 다 자기 SELECT 쿼리에 `WHERE status <> 'pass'`를 각자 복붙해둔
것일 뿐 공용 가드가 아니었다. `store_report_lines()`를 직접 부르는
나머지 15개+ 호출부(`reload_report_lines_corp.py`, `run.py`의 표준
적재, `note_lines_sync.py`/`pdf_lines_sync.py`/
`xbrl_instance_lines_sync.py`, 각종 backfill 스크립트 등)는 이 상태를
전혀 모른다 — 즉 `status='pass'`로 확정된 필링도 이런 경로로 다시
처리되면 **아무 경고 없이 통째로 지우고 다시 써서 검증된 상태가 조용히
무효화**된다. 기존 `unit_source='manual'` 가드(R8/2026-09-08)는 이미
`store_report_lines()` 안에 내장돼 모든 호출부에 자동 적용되는데, 이번
"원문대조 완료" 표시는 그런 공용 보호가 없는 비대칭이었다.

**수정**: `fin2/extract/report_lines.py::store_report_lines()`에
`overwrite_reviewed: bool = False` 매개변수 신설. 기본값에서는
`unit_source='manual'` 체크와 같은 자리(같은 함수 안, delete 실행 전)에
`layer2_review_queue.status == 'pass'` 존재 여부를 확인해, 있으면
`ValueError`로 거부한다(`overwrite_manual`과 독립된 별도 스위치 —
의미가 다르므로: 하나는 "값 자체가 사람 손입력", 하나는 "자동추출값을
사람/에이전트가 원문과 대조해 맞다고 확인"). 의도적으로 재검토해
덮어써야 하면 `overwrite_reviewed=True`를 명시. 기존 2개 스크립트의
`WHERE status <> 'pass'` 사전 필터는 그대로 둔다(불필요한 재추출 작업
자체를 건너뛰는 최적화라 무해 — 이제는 이중 방어).

**검증**: `fin2/tests/test_store_report_lines_manual_guard.py`에 회귀
테스트 5건 추가(총 9건) — 거부/`overwrite_reviewed=True` 허용/무표시시
정상진행/다른 rcept 비영향/`overwrite_manual=True`을 줘도
`overwrite_reviewed`는 별도로 거부되는지(두 가드의 독립성). `pytest
tests/ fin2/tests/` 전체 1059 passed(기존에 알려진 무관 실패
`test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix` 1건 제외).

**이 캠페인 설계에서 이 R139가 의미하는 것**: 원문대조 캠페인이 어떤
필링을 "확인 완료"로 표시하려면 `layer2_review_queue.status='pass'`로
갱신하면 되고, 그 순간부터 이 필링의 `report_lines`는 어떤 재적재
스크립트를 쓰든 자동으로 보호된다 — 캠페인 쪽에서 "재적재 대상에서
빼는" 로직을 따로 구현할 필요가 없다. 마찬가지로 이미 과거에
`status='pass'`로 확정된 필링(이전 계층2 캠페인 잔재)도 이 가드
신설 시점부터 자동으로 같은 보호를 받는다 — 별도 마이그레이션 불필요.

---

## R140. 계층2 검토 CSV에 SCE 포함 + `layer2_review.py`에 `--min-severity` 단계
필터 추가 (2026-09-18, 사용자 지시)

**배경**: R139와 같은 브라우저 에이전트 원문대조 캠페인 설계
(`docs/plans/layer2_review_browser_agent_automation_design_2026-09-18.md`)에서
사용자가 "bs is cf **sce** 데이터와 비교"라고 명시했는데, `fin2/extract/
review_csv.py::SCOPE_ORDER`와 `fin2/audit/layer2_selfcheck.py::STATEMENTS`는
2026-09-08 당시 사용자 범위 결정으로 **BS/IS/CF 3종만**이었다("SCE/APPR은
대상 밖" 주석). `report_lines` 자체에는 SCE 행이 이미 적재돼 있었다 —
`load_rows()`의 SQL이 애초에 statement로 거르지 않아서 CSV 생성 단계에서만
숨겨지고 있었을 뿐.

**수정**: ① `review_csv.py`의 `SCOPE_ORDER`에 `("separate","SCE")`/
`("consolidated","SCE")` 추가(각 basis 안에서 BS→IS→CF→SCE 순), `scope_counts()`·
`build_preamble()` 요약도 SCE 포함하도록 확장. `layer2_selfcheck.py`의
`STMT_KO`에 `"SCE": "자본변동표"` 추가(단, **자동검산 대상(`STATEMENTS`)은
그대로 BS/IS/CF만** — 자본변동표는 항등식이 BS/CF처럼 단순하지 않아 이
파일의 라벨-앵커 방식이 안 맞는다. 최종 판정은 어차피 브라우저 원문대조이므로
자동검산 확장은 불필요). APPR(이익잉여금처분계산서)은 사용자가 언급하지
않아 그대로 범위 밖.
② `scripts/layer2_review.py::_pick()`에 `min_severity` 매개변수, `next`/`pass`
서브커맨드에 `--min-severity` 옵션 추가 — 캠페인 단계(B): 사전 스크리닝
(`layer2_screen.py`)이 뭔가 걸어놓은 건(`screen_severity>0`, 2015+ 실측
27,136건)부터 먼저 처리하고, 그 다음 단계(A)로 나머지(`severity=0`,
80,369건)까지 이어서 전체를 돈다(사용자 지시: "B 먼저 하고 이어서 결국
전체를 한 번은 돌린다 — 파서 수정 건이 나올 가능성이 높은 쪽부터"). 미지정시
필터 없음(기존 동작 그대로, 다른 시대 캠페인에 영향 없음). `cmd_status`에도
이 두 그룹의 pending 잔량을 따로 보여주는 절 추가.

**검증**: `fin2/tests/test_review_csv.py`에 SCE 순서/카운트 테스트 2건
추가(`test_scope_counts_counts_bs_is_cf_and_sce`,
`test_scope_order_places_sce_after_cf_in_each_basis`) — 총 22건 통과.
`_pick(min_severity=1)`을 실제 2015+ 큐로 실행해 severity>0인 항목만
반환됨을 확인(`corp_rank=3, screen_severity=5`). `pytest tests/ fin2/tests/`
전체 1060 passed(기존 무관 실패 1건 제외).

---

## R141. `fin2/extract/statement_titles.py::classify_statement_in_body_section()` —
병합된 각주+헤딩 표제에서 리스트 순서가 아니라 **텍스트 내 위치**로 재무제표명을
고른다 (2026-09-19, 계층2 원문대조 캠페인 fail #5~#8)

**배경**: 계층2 원문대조 캠페인이 누적 fail 10건에서 정지한 뒤, 사용자 지시로
10건 전부 코드 레벨 근본원인을 조사했다. 그중 4건(KB금융 2018H1/Q1 원본+기재정정
`20180814002480`/`20210427000389`/`20180515001957`/`20210427000369`)이 "연결
손익계산서(포괄손익계산서) 완전 0행" 증상으로 동일했다.

**발견**: DART 는 "N번 재무제표의 각주"와 "N+1번 재무제표의 헤딩"을 같은 XML
형제 텍스트에 병합해두는 서식이 있다(실측: `"주) 당반기말 연결재무상태표는
기업회계기준서 제1109호를 적용하여 작성되었으며, 비교표시된 전기말 및 전전기말
연결재무상태표는 소급재작성되지 아니함 나. 연결손익계산서(포괄손익계산서)"`).
`classify_statement_in_body_section()`은 이 병합 텍스트에서 `_BODY_STMT_ORDER`
리스트 순서상 **먼저 오는 이름**("재무상태표", BS)을 텍스트 내 실제 위치와
무관하게 채택했다 — 정작 이 표를 지배하는 헤딩은 텍스트 **끝쪽**의 "나.
연결손익계산서"(IS)인데도. 그 결과 진짜 IS 데이터 표가 BS 로 오분류돼 BS 그룹에
붙었다가(라벨 체계가 안 맞아) 사실상 유실됐다.

**수정**: `_BODY_STMT_ORDER` 를 순서대로 순회하며 첫 매치에서 `return`하던 루프를,
각 이름의 `rfind()` 위치를 비교해 **텍스트 내 가장 나중(=표에 가장 가까운) 위치**의
이름을 채택하도록 바꿨다. 브라우저 원문대조 스크레이퍼(`bucketOfLine()`)가 이미
같은 문제(같은 서식)에 대해 쓰던 "마지막 매치 헤딩" 원리를 XML 파서 쪽에도
동일하게 적용한 것이다. `_SCE_RE`/`_APPROPRIATION_RE` 조기 배제는 그대로 유지
(자본변동표·처분계산서 배제 정책 불변).

**검증**: 4건 모두 연결 IS 0→50/50/44/44행 복원. `raw_report/` XML 을
`parser.xml.dart_xml_parser._parse_xml_file()`로 직접 재파싱해 review CSV 와
대조하는 Python 스크립트(브라우저 없이, `build_run_js.py`와 동일 로직)로
별도+연결 전체(BS/IS/SCE/CF) 373/373/363/363쌍 전량 원문과 정확히 일치(mismatch
0) 확인. `pytest tests/ fin2/tests/` 전체 1061 passed(기존 무관 실패 1건 제외).

---

## R142. `fin2/extract/statement_titles.py::is_substatement_marker()` 신설 +
`fin2/extract/text.py::_detect_body_statement_tables()` `last_stmt` 캐리포워드 —
재무제표명을 반복하지 않는 하위표 구분 표지 (2026-09-19, 계층2 원문대조 캠페인
fail #3)

**배경**: R141 과 같은 조사에서, 삼성바이오로직스 20170331005571(2016FY) 별도
자본변동표가 "40행 전부가 2013~2014년(제3~4기) 데이터뿐이고 2015~2016년(제5~6기,
당기 데이터 포함)은 통째로 누락"됨을 발견했다.

**발견**: 원문 구조가 SCE 표 하나를 기간대역별 하위표 2개로 쪼갠 서식이었다 —
`"다. 자본변동표(1) 별도재무제표(2013년 및 2014년)"`[데이터 19행] 다음에
`"(2) 개별재무제표(2015년 및 2016년)"`[데이터 26행, 당기(2016) 포함]가 옴. 뒤쪽
하위표 표제는 재무제표명("자본변동표")을 **아예 반복하지 않는다** — 앞 표제가
이미 확정한 문맥에 기대어 "이건 그냥 다음 기간대역"이라고만 알린다.
`classify_statement_in_body_section()`은 텍스트에 재무제표명이 있어야만 매치하므로
이 표제에서 stmt=None 이 됐고, `_detect_body_statement_tables()` 메인 루프는 그
표를 그냥 건너뛰었다(표제/데이터표 분리서식용 forward-scan 은 "표제가 성공적으로
분류된 경우"에만 발동하므로 여기선 발동 안 함). 결과: 당기 데이터 26행 전체 유실.

**수정**: `statement_titles.py`에 `is_substatement_marker()` 신설 —
`"(N) 개별/별도/연결재무제표(기간)"` 형태(재무제표명 없음, 순번+기간뿐)를
인식한다. `text.py::_detect_body_statement_tables()`의 메인 루프에 `last_stmt`
변수를 두어 매 idx 에서 stmt 가 확정될 때마다 갱신하고, 기존 폴백들이 모두
실패했을 때 표제가 이 표지에 매치하면 `last_stmt`(직전에 성공 분류된 statement)를
그대로 물려받는 폴백을 추가했다. "재무제표명이 있는데 다른 데이터로 넘어간
게 아니라, 이름이 없을 뿐 같은 재무제표의 다음 기간대역"이라는 판단을 순수하게
표제 문구(순번+기간 패턴)로만 내리므로 R6(추측 금지) 원칙 위반이 아니다 —
`is_substatement_marker` 매치 자체가 "재무제표명이 없다"는 사실에 기반한 구조적
판정이다.

**검증**: 별도 SCE 40→116행. "제6기 기말(2016.12.31)" 행이 원문 그대로의 정답값
(자본금165,412,500,000/자본잉여금2,487,313,082,024/이익잉여금1,424,706,873,013/
합계4,082,379,459,573)으로 복원, "제6기 기초(2016.01.01)" 행과 더 이상 값이
겹치지 않음 확인. `fin2/tests/test_r142_substatement_marker.py` 회귀테스트 3건
신규(순수 목 테스트 2건 + 실측 파일 재현 1건). `raw_report/` XML 직접 재파싱
대조로 별도+연결 전체 405/405쌍 전량 일치(mismatch 0). `pytest tests/
fin2/tests/` 전체 1064 passed(기존 무관 실패 1건 제외).

---

## R143. `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_tax_expense_value()`
— "차감후"(OCI 세후) 라벨도 EBT 가드처럼 후보에서 제외 (2026-09-19, 계층2
원문대조 캠페인 fail #9~#10)

**배경**: 같은 조사에서 KB금융 2026년 신규 DOM 패턴(재무제표별 전용 트리노드)
필링 2건(`20260814004200` 2026H1, `20260515002888` 2026Q1)의 별도
포괄손익계산서에서 "법인세비용차감후 (반)기기타포괄손익"(OCI 세후) 값이 바로 위
"법인세수익(비용)" 행과 동일한 값으로 오귀속됨을 발견했다.

**발견**: raw XML 원문 자체는 완전히 정확했다(직접 재파싱 확인 — 두 행 모두
서로 다른 값). `overlay_tax_expense_value()`(R18/버그②, 2026-08-23 신설)의
후보 필터가 `_TAX_EXPENSE_LABEL_KEYWORD="법인세비용"` 포함 + `"차감전"` 미포함만
확인했는데, "법인세비용차감후 반기기타포괄손익"도 "법인세비용" 부분문자열을
가지면서 "차감전"은 없어(대신 "차감후") 그대로 통과했다. 별도(separate) 쪽은
진짜 법인세비용 행의 라벨이 "법인세수익(비용)"이라 애초에 키워드 자체와
매치되지 않아 후보가 이 OCI 행 하나뿐이 됐고, `is.tax_expense` XBRL 사실값이
그 자리에 잘못 덮어써졌다. 연결(consolidated) 쪽은 진짜 "법인세비용" 라벨이
별도로 존재해 후보가 2개가 되어 모호성 가드(`len(row_list) != 1`)에 걸려
스킵됐다 — 그래서 연결만 항상 정상이었다.

**수정**: `_TAX_EXPENSE_EXCLUDE_KEYWORD`(단일 문자열) → `_TAX_EXPENSE_EXCLUDE_
KEYWORDS`(튜플 `("차감전", "차감후")`)로 확장. 후보 필터를
`not any(kw in label for kw in _TAX_EXPENSE_EXCLUDE_KEYWORDS)`로 변경.

**검증**: 두 필링 모두 별도 OCI 행이 원문값(405/-62 백만원)으로 복원,
`source_ref`에 오버레이 흔적 없음(미적용) 확인. `fin2/tests/
test_report_lines_inline_xbrl_overlay.py`에 회귀테스트 1건 추가(총 14건 통과).
`raw_report/` XML 직접 재파싱 대조로 별도+연결 전체 265/265·249/249쌍 전량
일치(mismatch 0). `pytest tests/ fin2/tests/` 전체 1064 passed(기존 무관 실패
1건 제외).

**★캠페인 방법론 교훈(R139/R140 캠페인 후속)**: 이번 10건 조사 중 4건(SK스퀘어
`20230814001786`·현대자동차 `20231114002201`·삼성바이오로직스
`20260814003375`)은 실제로는 **코드 결함이 이미 사라진 stale review CSV**였다 —
`git stash`로 당시 세션 수정 유무와 무관하게 `extract_report_lines()`를 직접
호출하면 이미 정답이 나왔다(다른 배경 작업이 DB `report_lines`를 이미 고쳐놨는데
`layer2_review_queue`의 CSV/노트가 재생성 안 된 상태). **fail 판정 재조사 시
코드를 고치기 전에 먼저 `git stash`로 현재 HEAD 코드가 이미 정답을 내는지부터
확인할 것** — `layer2_review.py redo --rcept <rcept>`가 값을 안 바꾸면 stale
CSV, 바뀌면 진짜 결함.

---

## R144. EPS(주당손익) 경로와 본류의 **판정 불일치** 3종 + 셀 안 줄바꿈으로
쪼개진 숫자 (계층2 원문대조 캠페인 fail 20건, 2026-09-19)

사용자 지시("문제 20개 확인해서 수정까지 진행해")로 캠페인 fail 20건을 근본원인
조사한 결과, **원인은 4가지**였다(삼성생명 18건·삼성물산 2건).

### (1) EPS 이중 전사 — 단위 오귀속 유령행 (17건, 가장 광범위)

`_emit_eps_lines`(EPS 전용 경로)와 `_emit_section_lines`(본류)가 **각자**
`_looks_like_eps_amounts()`를 부른다. 그런데 두 곳이 넘기는 금액의 **스케일이
다르다** — EPS 경로는 행 인라인 단위(없으면 원=1)로 파싱한 값을, 본류는 **표 단위를
이미 곱한** 값을 넘긴다. 그래서 표가 `(단위: 백만원)`이면 같은 행을 두고 판정이
갈린다:

| | EPS 경로가 보는 값 | 본류가 보는 값 | `_EPS_MAX_PLAUSIBLE_WON`(10⁷) 판정 |
|---|---|---|---|
| 기본주당이익 7,049원 | 7,049 | 7,049,000,000 | EPS 경로=EPS ✓ / 본류=EPS 아님 ✗ |

→ EPS 경로가 정상 행(원)을 담고, 본류도 "EPS 아님"이라 판단해 **표 단위(백만원)를
적용한 ×10⁶ 유령 중복행**을 하나 더 담았다. DB엔 동일 개념이 4행(백만원 쌍 +
원 쌍)으로 남는다. 실측: 삼성생명 2019Q3~2023H1 전 기간 연결·별도, DB 전체로는
**6,697행 / 3,129필링 / 313개사**.

**수정**: `_emit_eps_lines`가 **자기가 전사한 행의 라벨 집합**을 돌려주고 본류가
그 행을 건너뛴다(상보관계를 한 곳의 판정으로 보장). 단 그 집합에는 **그 표의
'주당' 라벨이 원(₩)을 명시 선언한 경우만** 넣는다 — 백만원 표에서는 금액 크기로
진짜 EPS와 NI귀속 오판 행(R27 `지배주주당기순이익`=지배+주주+당기순이익)을 가를
수 없어서, 증거 없이 본류에서 빼면 그 **NI 총액이 통째로 사라진다**(회귀테스트로
고정). 본류의 기존 게이트는 **그대로 두고 OR로 더한다** — 종전보다 빠지는 행이
늘지 않고 중복만 준다.

### (2) EPS 기간열 오선택 — 2단[3개월|누적] 표에서 3개월이 당기로 (2건)

`_emit_eps_lines`는 R85가 준 `cum_map`을 썼는데, `cum_map`은 **헤더 행의 논리열
위치**(`[3개월, 누적, 3개월, 누적]` = 4칸)로 만들어진다. 그런데 데이터 행은 값마다
빈칸이 끼어 **8칸**인 표가 있다(실측 삼성생명 20230814002621 IFRS17 서식). 위치가
어긋나 `position 1`이 헤더로는 '누적'인데 데이터로는 **당기 3개월**을 가리켰다 →
당기=1,489(3개월), 전기=5,425(당기누적)로 저장. 본류는 이미 R88 헤더 그리드
(`parse_header_columns`)를 **우선** 쓰고 있어 다른 라인은 전부 정상이었다 — EPS만
옛 추측 경로에 남아 있었다.

**수정**: `_emit_eps_lines`에 `header_cols`를 넘겨 본류와 **같은 순서**
(header_cols → cum_map → 위치순)로 고르게 했다. 수정 후 당기=5,425(누적)
전기=3,512(누적)로 원문과 일치.

### (3) EPS 열 밀림 — 당기 공란 시 전기 값이 당기로 (2건, 삼성물산)

`_emit_eps_lines`의 FY 분기가 `present`(None을 **제거한 압축 리스트**)에
`enumerate`를 걸었다. 당기 셀이 공란인 행에서 열이 통째로 왼쪽으로 밀린다.
실측 삼성물산 20160330002954·20170331003913 연결IS `중단사업 주당이익` — 원문
당기=공란/전기=3,418/전전기=470인데 DB엔 당기=3,418/전기=470. **공란은 공란으로
남긴다**(R0/R6)로 고쳐 위치 보존(`amounts_by_pos`)으로 바꿨다. 본류와 `cum_map`
분기는 이미 위치 기준이라 이 분기만 같은 규약으로 맞춘 것.

### (4) ★셀 안에서 줄바꿈으로 쪼개진 숫자 — 행 유실/열 밀림 (라인드롭 전부)

DART 원문 XML이 한 금액을 `<TD>` 안에서 **개행으로 끊어** 담는 경우가 있다:

```
['Ⅳ.기타금융부채', '22,270,03\n9', '21,335,183', '20,377,319']
['3. 이자의 지급',  '(102,6\n41\n)', '', '(105,187)', …]
['마.\n 해외사업환산손익', '44,75\n4', '57,460', …]
```

`parse_amount`와 `_split_label_amounts_ex`는 반각·전각·ZWSP·NBSP 공백은 이미
지우면서 **개행만 안 지웠다**. 그래서 `_NUMBER_PATTERN`(`^…$` 앵커)이 못 맞춰 그
셀이 `amount_cells`에서 통째로 빠지고 → **뒤 열이 당기 열로 밀리거나**(전기 값이
당기로 둔갑) **행 자체가 사라졌다**(모든 칸이 None이면 emit 0건). 부록 A의 T11이
주석 차원키 문맥에서 이미 지적한 함정인데 금액 경로엔 적용돼 있지 않았다.

실측: 삼성생명 20210517001864 연결 BS 2행(`Ⅳ.기타금융부채` 22,270,039 ·
`Ⅸ.기타부채` 1,264,181) + CF 1행(`3. 이자의 지급` -102,641) + IS 2행
(`라.특별계정기타포괄손익` -133,572 · `마.해외사업환산손익` 44,754), 20220516002463
연결 SCE 6값. **복원값 교차검증**: 22,270,039의 전기 칸 21,335,183이 직전 사업보고서
(20210310001045)의 당기값과 정확히 일치 — 재조립이 옳다는 독립 근거.

**수정**: `strip_cell_whitespace()`(신설, `amount_normalizer.py`)로 개행/탭도
나머지 공백과 **같은 취급**. 새 해석 규칙이 아니라 기존 공백 처리의 누락분을
메우는 것이다. 두 숫자가 개행으로 나열된 진짜 다중값 셀은 그 앞의 R1 가드
(`cell_text.split()` — 모든 공백류 분리)가 먼저 잡으므로 안전하다(회귀테스트 고정).

**검증**: `pytest tests/ fin2/tests/` 1,071 passed(무관 기존 실패 1건 불변 —
`test_nyuintek_2007q1_dkme_style_not_affected_by_this_fix`, HEAD 원본에서도 동일
실패 확인). fail 20건 전수 재추출로 각 노트가 기술한 결함이 전부 해소됨을 확인하고
`layer2_review.py redo --rcept`로 재적재 — 재적재 행수가 원문 DOM 실측과 전부 일치
(예 20210517001864 연결 BS 38/CF 32/IS 54/SCE 151, 20220516002463 연결 SCE 152).

**소급 백필 필요**(R8 ③): 위 (1)만으로도 DB에 6,697행/3,129필링/313개사가 남아
있다. (4)는 DB만으론 셀 수 없다(유실된 행이라 흔적이 없음) — 재추출해야 드러난다.

---

## R145. EPS 행 판정을 `"주당"` 부분문자열에서 **구조 패턴**으로 교체 +
EPS 경로에 **실제 `section_path`** 부여 (2026-09-19)

설계·실측 전문: `docs/plans/eps_label_structural_rule_r145_design_2026-09-19.md`.
사용자 질문("섹션을 본다면서 왜 다른 섹션 항목이 EPS 로 오분류되나")에서 출발했다.

**결함.** 계층2 IS 전사는 EPS 를 per-row 원(₩) 단위로 담으려 본류와 **다른 경로**
(`_emit_eps_lines`)로 처리하는데, 두 경로를 가르는 판정이 라벨의 `"주당"` 부분문자열
**하나**였다. `지배기업주주당기순이익` 은 `지배기업주주`+`당기순이익` 인데 `주주`의
`주` 와 `당기`의 `당` 이 붙어 `주당` 이 된다 → 총액이 EPS 로 끌려간다. 뒤이은 게이트는
`_looks_like_eps_amounts()`(값 크기)뿐이라 **구조를 한 번도 안 본다** — 백만원 표에서
원문 셀은 `270,700` 이라 EPS 크기로 완벽히 그럴듯하다.

실측(00160588 `20170515004474` 연결IS, 표 단위 백만원). 616,201 = 270,700 + 345,501
로 지배지분 순이익임이 산술 확정된다:

| 라벨 | 수정 전 | 수정 후 |
|---|---|---|
| `지배기업주주당기순이익(손실)` | **270,700** 원(`eps/`, `주당손익`) | **270,700,000,000** 원(`IS_C/`, `당기순이익(손실)의 귀속`) |
| `(1) 주당계속영업이익` | 3,839 원(`주당손익`) | 3,839 원(`XV. 주당이익(단위:원)>1. 보통주`) |

**왜 섹션을 못 봤나 — 3중 구조.** ① 본류는 `_assign_section_paths` 로 들여쓰기
`section_path` 를 이미 만들지만 `{id(RowData): path}` 키잉이라, 원본 `<TR>` 을 따로
훑는 EPS 경로는 **넘겨받아도 키가 안 맞는다**. ② EPS 경로 진입 조건이 부분문자열
하나뿐. ③ 통과하면 본류가 그 행을 스킵해 **총액이 제 섹션에서 유실**된다.

★더 깊은 원인: `extract_rows` 가 `_header_rule_name` 의 `단위표기` 규칙으로
`XV. 주당이익(단위:원)` 같은 **EPS 섹션 헤더를 통째로 드롭**한다(실측:
`기본주당기순이익 (단위 : 원)` 도 동일). 그래서 본류의 섹션 트리는 EPS 경계에서
이미 불완전했고, 들여쓰기 스택이 직전 섹션(`포괄손익의 귀속`)을 EPS 행에
물려주고 있었다. **같은 문서에서 연결/별도가 갈린다**(별도는 `XIV.주당이익` 이라
단위 표기가 없어 생존) — 서식 우연에 좌우되던 결함.

**규칙.** 자간 공백 제거 후(R111) 판정하며, **`(A 또는 B) 또는 (C 그리고 라벨에
`주당` 포함)`**:

```
A) 산정방식 선행 : (기본|희석) …≤8자… 주당
B) 수익어 후행   : 주당 (계속영업|중단영업|계속사업|중단사업|분기|반기|당기|연결|별도)?
                        (순이익|순손익|순손실|이익|손익|손실)
C) 섹션 문맥     : section_path 체인 **어디에라도** '주당'
```

`B` 의 수식어에 **`기` 단독을 넣지 않는 것**이 `보통주주당이익`(=EPS)과
`지배주주당기순이익`(=총액)을 가르는 지점이다 — R27 이 "라벨로는 원리적 구분 불가"라
결론냈던 바로 그 쌍이다. **실측으로 뒤집혔다**: `주당` **뒤**를 보면 갈린다.

| 측정(2015+) | |
|---|---|
| A∪B 커버리지 | 363,500 / 363,565행 = **99.982%** |
| 함정 배제 | 7/7 |
| `기본주당기순이익` 계열 | 213행 / 32종 / 0.059%(R27 이 "대량"이라 한 것과 다름) |

**`C` 는 필수도 단독도 아니다**(표본 1,011필링 실측, 설계문서 §6-2): EPS 섹션 헤더가
**아예 없는 표가 0.55%**(20/3,631행, 그중 13행은 단위 선언조차 없음) 있어 필수로 걸면
유실되고, `C` 단독으로만 걸리는 4행은 전부 라벨에 `주당` 을 포함해 보수화 비용이 0 이다.
체인 전체를 보는 이유도 실측 — 말단만 97.80% vs 체인 전체 99.17%
(`주당이익(단위 : 원)>계속영업` 류가 흔하다).

★그 0.55% 구간을 받치는 것이 **신호 `D`**(사용자 제안): EPS 절 제목이 없는 표에서,
**직전 최상위 행이 포괄손익 총계**인 최상위 `주당` 행을 EPS 로 인정한다. 실측 10개사
전부에서 성립(코리안리 `Ⅹ. 반기연결총포괄이익` · 현대엘리베이터 `총포괄손익` · DSC
`Ⅷ.당기총포괄이익(손실)` · 천일고속 `ⅩlV. 총포괄손익` · GMI벤처 `IX. 당기총포괄이익`).
앵커 조건은 **뺄 수 없다** — "헤더 없음+최상위"로만 좁히면 `지배주주당기순이익` 이
최상위인 표에서 총액을 삼켜 본류에서 유실시킨다(회귀 테스트가 잡아냈다). 앵커를
`순이익` 까지 넓히지 않는 이유도 같다. 안전성: A∪B 거부 라벨 보유 필링 80건 전수에
"헤더 없음+최상위+A∪B 실패" **0건**. 지금 D 로 새로 구제되는 행은 0 이고, 목적은 안전망.

**★적용 = 2015+ 한정**(`_EPS_STRUCTURAL_RULE_MIN_FY`). pre-2015 에 적용하면 양방향
사고다: 진짜 EPS 1,834행/204종(2.2%) 회귀 + K-GAAP 통짜 블럽
(`ⅩⅢ. 당기순이익주당 경상이익: 주당 순이익 :` = R28 이 본류에 위임해 둔 패턴)
11,519행/7,350종 신규 오염. `_PRE2015_ROUTING_MAX_FY`(=2010)와는 **다른 경계**다.

**구현.** ① `_indent_stack_paths()` 신설 — 들여쓰기 스택 알고리즘의 **단일 출처**
(`_assign_section_paths` 도 여기 위임). ② `_emit_eps_lines` 가 **원본 `<TR>` 위에서**
섹션 트리를 만든다 — 헤더 필터가 없어 `XV. 주당이익(단위:원)` 이 처음부터 안 사라진다.
③ EPS 경로와 본류가 **같은 `_is_eps_label()`** 을 쓴다(R144 교훈: 같은 판정을 두 경로가
각자 구현하면 갈린다). ④ `section_path="주당손익"` 하드코딩 → 실제 조상 체인.
⑤ R144 의 `in_eps_section` one-way latch 제거 — 스택이 대신하며 래치가 아니라서
"총액 섹션이 EPS 섹션 뒤에 오는 표"에서도 오판하지 않는다.

★`row_order`/`depth`/`node_role` 은 **NULL 로 유지**한다(본류 순회 순번이라 의미가
섞인다 + `row_order IS NULL` 을 EPS 식별자로 쓰는 코드가 실재). 대신 `section_path=
'주당손익'` 술어를 쓰던 3개 스크립트를 **`source_ref LIKE 'eps/%'`** 로 교체했다
(`build_eps_curated_override_final_2026-08-15.py`·`check_rcept_key_granularity_risk_
2026-08-15.py`·`snapshot_eps_r28_before_after_2026-08-15.py`) — 안 바꾸면 R28 curated
키 **재생성 시 조용히 빈 목록**이 나온다.

**소급 백필**(R8 ③) — 2026-09-19 처리 완료, 방식이 바뀌었다:

- **표적 재적재 32건** = R145 로 값이 바뀌는 전부(한화 10 · NH투자증권 7 · 티케이지애강 9 ·
  KBI메탈 2 · 디모아 1 · 케이티 1 · 케이뱅크 1 · 에어부산 1). 검증: 2015+ 유령행 38→**0**,
  한화 `지배기업주주당기순이익` 10행이 eps/ → 본류(−2,850억~4,917억)로 정정.
- **나머지는 캠페인이 한다** — `layer2_review.py next` 가 매 건 `_reload_one()` 으로 현재
  파서 재적재를 하므로 `pending` 107,131건의 stale 은 캠페인이 닿는 순간 해소된다.
  **전수 백필을 돌릴 이유가 없다**(사용자 지적 2026-09-19). 따로 챙길 것은 캠페인이
  영영 안 지나가는 `status IN ('pass','blocked')` 454건뿐 —
  `scan_report_lines_stale_vs_parser.py --never-revisited` 로 3분이면 전수 대조된다.
- **`section_path`** 는 재적재된 필링부터 실제 조상 체인이 되고 나머지는 옛 상수
  `'주당손익'` 이 남는다(값 무관, 두 규약 공존). 이 상수에 의존하던 스크립트 3개는
  `source_ref LIKE 'eps/%'` 로 옮겨놨다.

★**SK스퀘어 3건**(`20230814001786`·`20231115000283`·`20240419000596`, 2023 반기 정정
3판)은 `status='pass'` 라 R139 가드에 막혀 있었다. R144 를 알기 전의 판정이었고 결함
2종이 동시에 남아 있었다 — 반기 EPS 가 누적(−8,713) 대신 **3개월(−4,969)** 로 적재되고,
본류에는 `−8,713,000,000` 유령행. 검산으로 확정: 반기연결순이익 −1,227,754백만 ÷ 8,713원
≈ 1.41억주 = 발행주식수. 사용자 지시로 `--overwrite-reviewed` 재적재 + `status='reloaded'`
되돌림(note 에 경위 보존).

★★**유령행 시그니처의 한계**(여기서 드러남). R144 백필이 쓰던 판정식
`본류값 = EPS값 × 10^(-adecimal)`(같은 숫자·다른 단위)은 **두 경로가 서로 다른 열을
고른 경우를 못 잡는다** — 위 SK스퀘어가 −4,969×10⁶ ≠ −8,713,000,000 이라 통과했다.
DB 시그니처로 영향 필링을 고를 때는 이 맹점을 전제할 것. 확실한 방법은 재추출 대조다.

---

## R146. `rule_additive_da()` 가 **같은 감가상각비를 CF·IS·주석에서 각각 더해** D&A
##      와 EBITDA 를 정수배로 부풀린다 — ★**미해결, 캠페인 종료 후 착수**(2026-09-19)

**★이 규칙은 아직 고쳐지지 않았다.** 사용자 지시로 별도 트랙에 등재만 해 둔 것이다
(2026-09-19). 아래는 발견 경위·실측 규모·설계 쟁점이고, **코드는 손대지 않았다.**

**증상.** `std_financials_v3.depreciation` / `amortization` / `da_total` 이 원문 값의
정확히 **2배**(CF+IS) 또는 **약 3.2배**(CF+IS+주석)로 저장된다. `rule_derive_ebitda`
가 `ebitda = operating_income + da_total` 이므로 **EBITDA 까지 그대로 전파**된다.

```
제주은행 2021FY 별도   감가상각비  5,451,000,000 → std_v3 10,902,000,000  (×2.00)
클리오 2017Q3 연결     감가상각비  1,665,242,528 → std_v3  3,330,485,056  (×2.00)
나이스디앤비 2019FY 연결 감가상각비 2,235,732,580 → std_v3  4,471,465,160  (×2.00)
더블유게임즈 2016Q3 별도 감가상각비   184,311,032 → std_v3    368,622,064  (×2.00)
```

**원인.** `fin2/standardize/rules.py:220 rule_additive_da()` 는 `_DEP_CANON` 을 **단순
합산**한다. 그런데 그 튜플이 같은 개념을 **출처별로 세 벌** 담고 있다:

```python
_DEP_CANON = ("cf.depreciation", "is.depreciation", "note.depreciation",
              "cf.rou_depreciation", "is.rou_depreciation", "note.rou_depreciation",
              "cf.roa_depreciation", "is.roa_depreciation", "note.roa_depreciation")
_AMORT_CANON = ("cf.amortization", "is.amortization", "note.amortization")
```

`cf.depreciation` 과 `is.depreciation` 은 **다른 항목이 아니라 같은 금액의 다른 출처**다
— 은행·증권처럼 감가상각비를 IS(판관비)에도 적고 CF(비현금 가산)에도 적는 서식에서
둘 다 잡히면 그대로 두 번 더해진다. `_DA_TOTAL_CANON` 은 `next()` 로 하나만 고르지만,
뒤이어 `da_total = da_direct + dep + amo` 로 **이미 2배가 된 dep/amo 를 다시 더한다**.

★같은 파일 `rule_additive_debt()` 의 주석 "각 leaf 개념은 단일 canonical 로만 매핑되므로
합산해도 이중계상 없음"이 **D&A 에는 성립하지 않는다** — 차입금 세부항목은 서로 배타적
이지만 `cf.*`/`is.*`/`note.*` 는 같은 것의 사본이다. 합산 규칙을 새로 쓸 때 "세부항목
합산"과 "출처 중복"을 구분할 것.

**실측 규모(2015+).** 라벨·금액이 **완전히 같은** CF∩IS 쌍만 센 하한값:

| | |
|---|---|
| 중복 개념 쌍 | 2,880 |
| 영향 `std_v3` 행 | **2,389행 / 119개사** |
| 그중 `ebitda` 가 NULL 아님 | 2,791 |
| 비율 분포(감가상각비 한정) | **×2.00 이 486행**, ×3.2 대역 21행(주석까지 3중) |

**★R144/R145 와 무관한 기존 결함이다.** 2026-09-19 std_v3 재빌드(304개사) 진단 중
제주은행에서 드러났지만, 재빌드 대상이 **아닌** 회사들(클리오·나이스디앤비·더블유게임즈·
HS애드)이 2026-09-17 빌드인 채로 이미 ×2 다. 제주은행에서 이제야 보인 이유는, 그전엔
별도 IS 자체가 유실돼(R144 ④ 셀 안 줄바꿈) **CF 값만 세어지며 우연히 맞았기** 때문이다
— 상류를 고치자 하류의 기존 버그가 드러난 사례.

**미결 설계 쟁점**(착수 시 실측으로 정할 것):

1. **출처 우선순위인가 최댓값인가.** `cf` 우선이 자연스러워 보이지만, CF 가 결합 표기
   (`감가상각비및무형자산상각비`)만 싣고 IS 가 분해해 싣는 서식이 있으면 해상도를 잃는다.
2. **"같으면 하나만"으로 충분한가.** 값이 미세하게 다를 때(반올림·표시단위) 중복인지
   진짜 별도 항목인지 구분이 필요하다. 단순 동일값 배제는 그 구간을 놓친다.
3. **`rou_`/`roa_` 파생도 같은 문제**를 갖는다 — 출처 3벌 × 개념 3종.
4. R145 §소급백필과 같은 질문: 고친 뒤 **std_v3 전수 재빌드**가 필요하다
   ([[gateb-full-reaudit-is-required-to-close]] — 표본으로 닫으면 재등장한다).

**재현 쿼리**(위 표를 그대로 다시 만든다):

```sql
WITH d AS (
  SELECT rl.corp_code, f.fiscal_year, f.fiscal_period, rl.basis, rl.statement,
         rl.label_raw, abs(rl.value_won) v
  FROM report_lines rl JOIN filings f USING(rcept_no)
  WHERE rl.report_fiscal_year >= 2015 AND rl.col_index = 0
    AND rl.statement IN ('CF','IS') AND rl.label_raw IN ('감가상각비','무형자산상각비')
    AND rl.value_won <> 0)
SELECT corp_code, fiscal_year, fiscal_period, basis, label_raw, v
  FROM d WHERE statement='CF'
INTERSECT
SELECT corp_code, fiscal_year, fiscal_period, basis, label_raw, v
  FROM d WHERE statement='IS';
```

---

## R147. `_is_eps_label()` 이 라벨에 `주당` 이 없는 EPS **자식행**(계속영업/중단영업
##      세부이익)을 인식 못 해 통째로 결측 — `E` 규칙 추가로 종결(2026-09-20)

**발견 경위.** 계층2 원문전체대조 캠페인(`camp_run` 워크트리, 별도 세션)이 두산에너
빌리티(00159616) [연결] 손익계산서에서 EPS 결측을 6건 연속 발견 → `fail --note` 로
누적, 근본원인 미조사 상태로 캠페인이 사실상 이 지점에서 정체됐다. 상세는
`docs/qa/eps_continuing_ops_subline_gap_r147_2026-09-20.md`.

**증상.** DART 원문은 `기본주당이익(손실) (단위 : 원)`/`희석주당이익(손실) (단위 :
원)` 아래에, **같은 라벨을 반복**해 한 단계 더 들여쓴 `계속영업이익(손실) (단위 :
원)`/`중단영업이익(손실) (단위 : 원)` 세부이익을 중첩 표시한다(중단영업 분류가 있는
회사·기간에 한함). 이 4개 자식행이 `report_lines` 에 아예 안 실렸다 — 값이 부모행과
우연히 같을 수 있어(중단영업 없는 분기) 산술 self-check 로는 절대 안 걸리는 유형.

**원인.** `_is_eps_label()` 은 `"주당" not in s → return False` 로 조기 반환한다.
그런데 자식 라벨(`계속영업이익(손실) (단위 : 원)`) 자체엔 `주당` 이 전혀 없다 — 오직
**조상 체인**(`section_path`)에 `주당` 이 있을 뿐이다. R145 의 `C`(섹션 문맥)는
"라벨에 `주당` 이 있어야" 라는 조건이 걸려 있어(EPS 절 아래 섞여든 주식수·비율 행
오염 방지, R145 문서 참고) 이 자식행도 `C` 자격이 없다. 결과: `_emit_eps_lines` 의
게이트를 통과 못 해 아예 emit 되지 않는다 — 그리고 같은 라벨이 `extract_rows` 의
'단위표기' 헤더규칙(`(단위 :` 매치, R145 가 이미 지적한 함정)에도 걸려 **본류
(`table_rows`)에도 애초에 없다**. 이중으로 새는 구멍.

**수정.** `_is_eps_label()` 에 `E` 규칙 추가 — 라벨에 `주당` 이 없어도, **조상 체인이
EPS 절이고(`C`) 이 행 자신이 원(₩)을 명시 선언했다면**(`detect_unit_declaration(label)
== 1`) EPS 로 인정한다. `C` 단독 인정을 안 하는 이유(주식수·비율 행 오염)는 원(₩)
명시 선언을 **추가로** 요구해 회피 — 주식수·비율 행은 "(단위 : 주)"/"(단위 : %)" 를
선언하지 원(₩) 을 선언하지 않는다. 같은 라벨의 **본문**(EPS 절 밖) 총액 행(예:
`계속영업이익(손실)` 억원대 총계)은 원(₩) 인라인 선언이 없어 `E` 가 삼키지 않는다.

```python
if "주당" not in s:
    return _in_eps_section(section_path) and detect_unit_declaration(label) == 1
```

**실측 규모(2026-09-20, 두산에너빌리티 단독 확정분).** 2015+ 61개 필링 전수 재추출
스캔 결과 **25건**에서 R147 자식행이 발생(2017~2023FY 기간 전체 + 정정본, 중단영업
분류가 종료된 2024+ 는 해당 없음). 재적재 완료(신규 82행, `report_lines`). 그중
**19건은 이미 `layer2_review_queue.status='pass'` 로 검토완료 판정된 필링**이었다 —
이 버그가 그 판정 이전엔 알려지지 않았던 것. `store_report_lines(overwrite_reviewed=
True)` 로 원문(raw XML) 재대조 후 명시적으로 재판정해 덮어썼다(스크립트:
`scripts/backfill_eps_continuing_ops_subline_r147_2026-09-20.py`).

**전사 스코프 확정(같은 날 후속).** SQL 후보(EPS 원선언 스타일 + 같은 필링 IS
본문에 `중단영업이익` 존재, 5,904건/708개사)는 **하한**이었다 — 두산 자신의 확정
25건 중 9건(중단영업이 0에 가까워 본문에 라벨이 안 뜨는 분기)을 놓쳤다. 그 SQL
후보에서 나온 12개 회사의 2015+ 전체 필링(630건)을 회사단위로 완전 재스캔해
**132건**(12개사)을 확정했다. `layer2_review_queue` 조인 결과 **이미 pass/fail
판정된 건은 두산에너빌리티 25건뿐**(전부 재적재 완료) — 나머지 11개사 107건은
전부 `pending`, 캠페인이 도달할 때 재적재로 자연 해소될 예정(단 그 시점에 이 코드
수정이 캠페인 워크트리에 반영돼 있어야 함). 상세 회사별 목록:
`docs/qa/eps_continuing_ops_subline_gap_r147_2026-09-20.md`.

**회귀 테스트**: `fin2/tests/test_report_lines_r147_eps_continuing_ops_subline.py`
(7건 — 자식행 인정/본문 오염 방지/pre-2015 무변경/원문 재현 end-to-end).

---

## R148. `fin2/extract/text.py::_detect_body_statement_tables()` — 자본변동표가
##      **표지 문구 없이** 물리적 `<TABLE>` 2개로 분할되는 서식에서 당기 롤포워드
##      구간 전체가 유실 — 표 내용 기반 판정으로 종결(2026-09-20)

**발견 경위.** 계층2 원문전체대조 캠페인(`camp_run` 워크트리, 별도 세션)이 신한지주
(00382199)의 자본변동표(SCE)에서 자본총계 불일치를 발견해 `docs/qa/
layer2_review_campaign_issues_2026-09-20.md` 이슈#7·#8·#10·#11 로 누적 보고(연간·
반기·분기 전부 재발). 캠페인은 파서를 고치지 않고 계속 진행하는 규약이라 이 세션이
근본원인을 조사·수정했다.

**증상.** [연결]·[별도] 재무상태표의 자본총계가 DB에 적재된 자본변동표(SCE) 마지막
행의 총계와 불일치. 원문을 직접 확인하면 자본변동표가 페이지 폭 제약으로 물리적
`<TABLE>` 2개로 나뉘어 렌더링돼 있다 — 첫 표는 이전 비교기간 롤포워드(예:
2019.01.01→2020.12.31), 둘째 표가 당기 롤포워드(예: 2020.01.01→2021.12.31, 재무
상태표와 정합해야 하는 바로 그 구간)다. DB에는 첫 표만 적재되고 **둘째 표(당기)가
통째로 결측** — [연결]·[별도] 양쪽 다 동일.

**원인.** 첫 표 앞에는 정상적인 표제("연 결 자 본 변 동 표")가 있어
`classify_statement_in_body_section` 이 SCE 로 인식하지만, 그 표 자신은 데이터가
없으므로(제목표/데이터표 분리 서식) forward-scan 이 "다음 재무제표 제목 전까지
**첫 데이터표 하나만** 연결"하는 규칙(2026-07-23 설계, 재무제표 하나당 데이터표
하나 가정)에 따라 첫 데이터표만 채택하고 `break` 한다. 문제는 이 문서의 SCE 가
그 가정을 깬다 — 첫 데이터표 바로 다음에 **표지 문구가 전혀 없는 둘째 데이터표**가
바로 이어진다(R142 의 `is_substatement_marker` 가 잡는 `"(2) 개별재무제표(2015년
및 2016년)"` 같은 최소한의 순번+기간 표지조차 없다 — 앞 표 마지막 TR 이 끝나자마자
새 `<TABLE>` 이 시작하고, 자기 `<THEAD>` 에 SCE 자본 구성요소 열이름(자본금/자본
잉여금/이익잉여금 등)을 그대로 반복할 뿐이다). 텍스트 표지가 없으니
`is_substatement_marker` 매치가 실패해 `stmt` 가 `None` 으로 남고, 메인 루프가
그 표를 그냥 `continue` 로 건너뛴다.

**수정.** 텍스트 표지가 원천적으로 없으므로 표 자신의 **내용**으로 판정한다 —
`last_stmt == "SCE"` 이고 표에 데이터행이 있고 `_looks_like_equity_changes_header()`
(R127 이 이미 쓰던 "SCE 자본 구성요소 열이름 ≥3개" 판정, 표제가 아니라 내용 기반)가
참이면 직전 statement(SCE)를 물려받는다. `last_stmt == "SCE"` 로 좁혀 다른 재무제표의
헤더리스 연속표에는 적용하지 않는다(R6: 확정 못 하면 추측하지 않는다 — 이 조건은
"SCE 표 뒤에 SCE 모양 표가 표지 없이 바로 옴"이라는 순수 구조 신호일 뿐, 라벨이나
회사를 겨냥한 하드코딩이 아니다).

```python
if (stmt is None and last_stmt == "SCE" and _table_has_data_rows(tbl)
        and _looks_like_equity_changes_header(tbl)):
    stmt = last_stmt
```

**검증.** `extract_report_lines()` 직접 재호출(DB 미개입)로 신한지주 3건 재현 —
2021FY(`20220316000748`)·2018FY(`20190401004307`)·2021Q3(`20211115002302`)·
2021H1(`20210817001629`) 전부 둘째 표(`table_seq=1`) 복원, 마지막 행 총계가 각 필링의
재무상태표 자본총계와 정확히 일치([연결] 49,538,422백만/48,466,392백만 등, [별도]
26,405,376백만/26,842,076백만 등 — 전부 이슈 문서에 사용자가 기록한 DART 원문값과
동치). 이전 구간(`table_seq=0`)은 그대로 보존(가산적 수정). `pytest tests/
fin2/tests/` 전체 1112 passed(회귀 없음).

**회귀 테스트**: `fin2/tests/test_r148_headerless_sce_continuation.py`.

**백필 상태(2026-09-20)**: 위 4건은 `layer2_review.py redo --rcept` 로 `report_lines`
재적재 완료(★캠페인 워크트리에 이 커밋을 pull 하기 전엔 이 4건을 큐에서 재적재하지
말 것 — 옛 코드로 재실행하면 방금 고친 값이 조용히 되돌아간다, 워크트리 DB 공유
규약 참고). 신한지주 다른 기간·동일 레이아웃을 쓰는 다른 은행지주 등으로의 전사
스코프 확정은 **미실시** — 캠페인 종료 후(또는 여유 있을 때) 별도 스캔 필요.

---

## R149. `parse_amount()` 가 `'2,564원'`(셀이 스스로 원 단위를 밝힌 표기)을 못 읽어
## **EPS 행이 통째로 결측** — 금융지주/증권 19개사 324건 (2026-09-20)

**발견 경로**: 계층2 원문전체대조 캠페인이 신한지주 2022Q1(`20220516002487`)에서
"[별도]·[연결] 손익계산서 EPS 섹션이 통째로 결측"으로 보고(이슈#16). R147(계속영업/
중단영업 **세부행**만 결측)과 달리 EPS 절 전체가 사라진 것이라 별건.

**증상**: DART 원문 [별도] IS 에 `Ⅷ. 주당이익 / 기본 및 희석주당이익 2,564원` 이
명백히 있는데 `report_lines` 에 `'주당'` 포함 행이 **0건**. CSV 도 EPS 없이 바로 다음
표로 넘어간다. 값을 틀리게 읽은 것이 아니라 **행 자체가 없다**.

**원인**: 금융지주 IS 는 표 전체를 `(단위: 백만원)` 으로 선언하면서 **주당이익 행만
원 단위로 인쇄**한다 — 그래서 그 행의 셀 원문이 `'2,564원'`/`'2,552 원'` 처럼 숫자에
`원` 이 붙어 온다. `parser/common/amount_normalizer.py::parse_amount()` 는 이 접미사를
처리하지 않아 `None` 을 반환했고, EPS 경로(`_emit_eps_lines`)·본류(`_emit_section_lines`)
**양쪽 모두** 금액 0개로 보고 행을 버렸다. EPS 경로는 이미 단위를 1(원)로 옳게 잡고
있었으므로(R28/R147 계열) 결함은 오직 숫자 파싱 한 곳이었다.

실측 확인(신한지주 20220516002487 원문 `<TR>` 덤프):
- `Ⅶ. 총포괄이익` → 셀 `'1,406,564'` (접미사 없음) → 정상 전사됨
- `기본 및 희석주당이익` → 셀 `'2,564원'` → `parse_amount('2,564원', 1)` = `None` → 행 소실

**수정**: 셀이 **스스로** 원 단위를 밝힌 경우 접미사를 떼고 값을 원 그대로 읽는다.
이때 **표의 배수를 이 셀에 적용하지 않는다** — 안 누르면 반대로 2,564 × 10⁶ 이라는
날조가 된다(표가 백만원 선언이므로).

```python
# 앞이 한글이면 배수를 품은 접미사('1,234천원')라 걸리면 안 된다 → 부정 후방탐색.
_CELL_OWN_WON_RE = re.compile(r"(?<![가-힣])원$")
...
if _CELL_OWN_WON_RE.search(s):
    s = _CELL_OWN_WON_RE.sub('', s).strip()
    multiplier = 1
```

`'천원'`·`'백만원'` 접미사가 붙은 **데이터칸**은 실측 표본(필링 150건, `원` 계열 셀
74건 **전부 EPS 라벨**)에서 한 건도 없었다 → 근거 없는 처리를 넣지 않았다(추측 금지,
R0/R6). 그런 셀은 종전대로 `None`.

**검증**: 신한지주 20220516002487 재추출 — [별도] `기본 및 희석주당이익` 2,564/2,428,
[연결] `기본주당순이익`·`희석주당순이익` 2,552/2,173 으로 복원. 전부 원문값과 정확히
일치(원문 셀 `'2,552 원'`·`'2,173 원'` 직접 대조). 총 행수 894 → 900 = **정확히 EPS
6행만 증가** — 본류 중복 전사(×10⁶ 유령행, R144 가 밟았던 지뢰)가 없음을 확인.
`pytest tests/ fin2/tests/` 1116 passed(회귀 없음 — `parse_amount` 는 전 경로 공용
함수라 전체 스위트로 확인).

**회귀 테스트**: `fin2/tests/test_r149_eps_won_suffix_cell.py`.

**전사 스코프(2026-09-20 실측)**: "IS 행은 있는데 `'주당'` 행이 0건"인 후보 2,905건
/858개사 중, 원문을 열어 `주당` 행에 `원` 접미사 셀이 실재하는 것으로 확정된 것이
**324건 / 19개사** — KB금융 59, 하나금융지주 40, 신한지주 39, LG씨엔에스 35, 제주은행
34, 유안타증권 30, NH투자증권 27, 에이플러스에셋 18, 지누스 12, 노바렉스 7,
카카오뱅크 7, SK스퀘어 7, 나머지 6개사 1~2건. **신한지주 단독 결함이 아니다.**
★후보 2,905건 중 1,395건은 이 머신에서 원문 파일이 안 잡혀(로컬 `raw_report` 미보유,
SD/NAS 쪽) 확인하지 못했으므로 **324건은 하한**이다 — SD카드 마운트 상태에서 재스캔
필요.

**백필 상태**: 코드 수정만 완료. 확정 324건 중 `pending` 242건은 캠페인이 그 건을
검토할 때 `_reload_one()` 이 자동 재적재하므로 별도 백필 불요(R145 때 사용자 지시
"★전수백필 돌리지 말 것" 과 같은 취지). ★조치 필요 = **이미 `status='pass'` 인 79건** —
EPS 가 결측된 상태로 "원문대조 통과" 판정이 찍혀 있어 거짓 인증이다. `pending` 리셋
(재검토 유도) 여부는 큐 상태 변경이라 **사용자 판단 대기**.

---

## R150. `parse_amount()` 가 천단위 콤마 **바로 뒤**에서 공백으로 쪼개진 금액
## (`'4,244, 863'`)을 결측으로 처리해 재무상태표 행이 통째로 유실 (2026-09-20)

**발견 경로**: 행 단위 결측 탐지기(`fin2/audit/row_coverage.py`, 같은 날 신설)가 잡아낸
**첫 실제 결함**. 캠페인 사람 대조로는 잡히지 않던 종류다 — 대조 방향이 CSV → 원문
단방향이라 CSV 에 없는 행은 순회 대상에 들어오지 않는다(R149 참고).

**증상**: 신한지주 20150515002196(2015Q1) [연결] 재무상태표에서 적재된 라벨이
`Ⅷ.유형자산` 다음 `Ⅹ.관계기업에 대한 투자자산` 으로 **건너뛴다**. `Ⅸ.무형자산`
4,244,863(백만원 = **4.24조**)과 `XIV.기타자산` 18,245,860(= **18.2조**)이 통째로 없다.

**원인**: 그 두 행의 당기 칸 원문이 `'4,244, 863'`·`'18,245, 860'` — 천단위 콤마
**직후에 공백이 끼어** 있다. `parse_amount()` 의 R1 가드는 "한 셀에 온전한 숫자가 둘
이상이면 어느 것이 그 셀 값인지 원문이 말하지 않으므로 결측"으로 처리한다(날조 방지,
정당한 규칙). 그런데 `_is_complete_number()` 가 `.rstrip(",")` 를 하기 때문에
**`'4,244,'` 를 온전한 숫자로 판정**한다 — 실제로는 조각인데. 그래서 R1 이 두 값으로
보고 `None` 을 돌려주고, BS 는 당기만 적재하므로 행이 사라졌다.

**수정**: 마지막을 뺀 토큰이 **전부 콤마로 끝나면** 한 숫자가 쪼개진 것으로 보고
이어붙인다. 이어붙인 결과가 온전한 숫자일 때만 채택한다.

```python
if len(toks) >= 2 and all(tk.endswith(",") for tk in toks[:-1]):
    joined = "".join(toks)
    if _is_complete_number(joined):
        cell_text = joined
        toks = [joined]
```

**안전성 — 실측으로 확인한 오작동 3종이 전부 막힌다**:
- **주석번호 목록**(가장 위험) — 한국금융지주 20150515002047 [연결] BS 는 주석 열에
  `'4, 27, 30'`·`'15, 30'` 처럼 번호를 나열한다(스코프 스캔에서 25칸). 이어붙이면
  42,730 이라는 **날조**가 된다. 3자리 그룹이 아니라 `_is_complete_number('4,27,30')`
  = False → 이어붙이지 않고 기존 R1 가드가 결측으로 받는다.
- **진짜 두 금액이 나열된 셀** — `'1,234 5,678'`·`'723,570,750 723,570,750'` 은 첫
  토큰이 콤마로 끝나지 않아 이 분기에 걸리지 않는다(R1 동작 불변).
- **자릿수 폭발** — `'316,305268, 96147,344'` 는 이어붙여도 R2 의 `_AMOUNT_SANE_MAX`
  가드가 결측으로 받는다.

**검증**: 신한지주 20150515002196 재추출 — [연결] `Ⅸ.무형자산` 4,244,863,000,000 ·
`XIV.기타자산` 18,245,860,000,000 복원, 이웃 `Ⅷ.유형자산` 3,114,557,000,000 불변
(가산적 수정). 행 단위 결측 탐지 2건 → **0건**. `parse_amount` 는 전 경로 공용 함수라
전체 스위트로 확인: `pytest tests/ fin2/tests/` **1135 passed**.

**회귀 테스트**: `fin2/tests/test_r150_amount_split_by_space.py`(주석번호 날조 방지
케이스 포함).

**스코프(실측)**: 회사별 1건씩 146건 스캔 — 이 서식 보유 2건(1.4%). 금액칸에 실제로
해당하는 것은 **신한지주 20150515002196 의 2칸**뿐이고, 한국금융지주 25칸은 위의
주석번호 열이라 대상이 아니다. ★전수 스코프는 미확정 — `parse_amount` 는 공용 함수라
수정 효과가 전 경로에 자동 적용되므로, 캠페인이 각 건을 검토할 때 `_reload_one()` 이
재적재하면서 해소된다(R145/R149 와 같은 취지로 전수 백필은 돌리지 않는다).

---

## R151. `_looks_like_equity_changes_header()` 가 열이름의 **자간 공백**을 처리하지 않아
## R148(표지 없는 SCE 물리분할표)이 신한지주 외에서는 발동하지 못했다 (2026-09-20)

**발견 경로**: 캠페인이 KB금융 20180814002480(2018H1) 별도 자본변동표에서 "R148 과
동일한 결함(당기 롤포워드 표 통째 결측)이 재현된다"고 보고(이슈#18). 두 가지가 단서였다
— ① 비-신한지주 회사에서 처음 확인, ② 재적재 시각이 R148 커밋보다 **뒤**인데도 재현.

**원인**: R148 은 표지 없는 둘째 표를 "표 자신의 내용"(= SCE 자본 구성요소 열이름 ≥3개,
`_looks_like_equity_changes_header`)으로 이어붙인다. 그런데 그 술어가 열이름을 **원문
그대로** 매칭했다. DART 는 자간을 벌려 넣는 서식을 흔히 쓴다:

    '과 목  자 본 금  자 본잉여금  기타포괄손익누계액  이 익잉여금  자기주식  총 계'

여기서 `자본금`·`자본잉여금`·`이익잉여금` 이 전부 빗나가고 공백 없는
`기타포괄손익누계액` 1개만 걸려 임계값(3) 미달 → False → R148 이 발동하지 못한다.
**신한지주 열이름엔 자간 공백이 없어서** 거기서만 통했던 것이다.

같은 함정을 `_is_metadata_only`(2026-08-05 '분 기 연 결 재 무 상 태 표')와
`classify_statement_in_body_section`(공백 제거 후 판정)은 **이미 처리하고 있었다** —
이 술어만 규약에서 빠져 있었다. 즉 R148 은 처음부터 반쪽이었다.

**수정**: 매칭 전에 공백을 제거한다.

```python
joined = re.sub(r"\s+", "", "".join(cells))
return len(_SCE_COLUMN_LABELS_RE.findall(joined)) >= 3
```

**검증**: KB금융 20180814002480 별도 SCE 가 `table_seq` 0(45행)뿐이던 것이 0(45행) +
**1(40행)** 로 복원. 둘째 표 마지막 행(`2018.6.30(당반기말)`)의 자본금 2,090,558과
자본잉여금 14,742,814 가 **재무상태표 당기 값과 정확히 일치**(독립 교차검증). 연결에서도
seq=1 의 자본잉여금 17,122,969 가 BS 와 맞고 seq=0(17,122,228)은 전기라 구분된다.
첫째 표는 그대로 보존(가산적 수정). `pytest tests/ fin2/tests/` 1142 passed.

**회귀 테스트**: `fin2/tests/test_r151_spaced_sce_column_labels.py`. ★공백을 제거하지
않으면 그 표를 못 잡는다는 것까지 monkeypatch 로 고정했다 — 안 그러면 "왜 공백 제거가
필요한가"가 코드에서 사라진다.

**스코프(실측)**: 회사별 1건씩 399건 스캔 — 자간 공백 SCE 헤더 표는 20건/18개사에
있지만(DB손해보험·BNK금융지주·삼성화재·한화생명·현대해상·케이뱅크·크래프톤·
삼성바이오로직스 등), 대부분은 자기 표제로 이미 귀속돼 있어 **실제 행 유실은 훨씬
좁다**. 수정 전/후 SCE 행수를 직접 비교하니 같은 399건 중 늘어난 것은 1건
(BNK금융지주 20150515001930, 115 → 185행) + 보고된 KB금융 건. 즉 "자간 공백 + 표지 없는
물리분할" 두 조건이 겹쳐야 한다.

---

## R152. 금융업 보충표기(대손준비금·비상위험준비금)가 본항목과 **같은 칸**에 압축돼
## 자본/손익 본항목 행이 통째로 유실 (2026-09-20)

**발견 경로**: 행 단위 결측 탐지기(`fin2/audit/row_coverage.py`) 전수 센서스. 회사별
1건씩 400개사에서 발화 3건이었고 그중 2건이 이 계열이었다(나머지 1건은 거짓양성).

**증상**: 대신증권 20150515002053 [연결] 재무상태표에 **연결이익잉여금 행이 없다**
(1.자본금 → 2.연결자본잉여금 → 3.연결기타포괄손익누계액 → 5.자본조정 으로 4번이
건너뛰어짐). 코리안리 20150515002691 은 [연결]·[별도] 손익계산서에서 **분기순이익 행이
없다**.

**원인**: 금융업(은행·증권·보험)은 감독규정상 **보충 표기**를 재무제표 본문에 함께
인쇄한다 — 이익잉여금 밑에 "(대손준비금 적립액)/(대손준비금 적립예정액)", 당기순이익
밑에 "대손준비금 반영후 조정이익/비상위험준비금 반영후 조정이익". 원문이 이 **3개 논리
행을 물리적 `<TR>` 1개**에 담고(`HEIGHT="76"`~`"99"` = 3줄), 라벨 3개와 금액 3개가 각각
한 칸에 병합돼 온다:

    <TD>4. 연결이익잉여금(주석25)  (대손준비금 적립액)  (대손준비금 적립예정금액)</TD>
    <TD>581,929,430 5,320,412647,720</TD>

`parse_amount` 의 R1 가드("한 셀에 온전한 숫자 둘 이상 → 어느 것이 이 셀 값인지 원문이
말하지 않으므로 결측")가 이 칸을 받아 `None` 이 되고, BS 는 당기열만 적재하므로 **행이
사라진다**. R1 자체는 정당한 규칙이지만, **이 서식에서는 원문이 순서로 말해준다** —
[본항목, 보충1, 보충2].

**수정**: `parser/xml/table_extractor.py::extract_rows` 에서 **라벨이 대손준비금/
비상위험준비금을 포함할 때만** 금액칸을 본항목(첫 값)으로 줄인다
(`_first_of_compacted_supplementary_cell`). 두 서식 변형을 처리한다:
- 공백 구분 `'60,042,793,551 54,525,604,742 40,084,010,260'` → 첫 토큰
- 괄호 결합 `'1,828,134(13,701)(2,886)'` → 선행 금액

**★가장 위험한 오작동(실측으로 막음)**: 미래에셋증권 20150515001242 의 이익잉여금 행은
주석칸이 `'26, 27'`(주석 26·27번)이다. 라벨 게이트에 걸리므로 그냥 첫 토큰을 취하면
**26 × 단위배수라는 날조**가 생긴다. 그래서 첫 값이 **금액다울** 것(천단위 콤마 묶음이
있거나 4자리 이상)을 요구한다 — 주석번호는 배제된다. 스코프 스캔 599건에서 압축칸
6개 중 2개가 이 주석번호 패턴이었다(드물지 않다).

**하지 않는 것**: 보충표기 값(둘째·셋째)은 **버린다** — 라벨 경계가 원문 마크업에
없어(코리안리 TD 는 평문 한 덩어리) 어느 값이 어느 보충 이름인지 단정할 수 없고 4대
재무제표 항목도 아니다. 라벨도 원문 그대로(병합된 채) 남긴다 — 쪼개면 추측이 된다
(R0/R6). 구분자 없이 이어붙은 칸(`'576,044,2464,652,625667,787'`, 대신증권 전기열)도
손대지 않는다(자릿수 경계가 원문에 없다).

**검증 — 3사 전부 독립 산술로 확인**:
- 대신증권 [연결] BS: 지배기업의 소유주지분 1,632,979,218 = 자본금 434,867,000 +
  연결자본잉여금 694,981,258 + 연결기타포괄손익누계액 99,813,409 + 자본조정
  △178,611,879 + **연결이익잉여금 581,929,430** → **차이 0**(천원)
- 코리안리 IS: [연결] 세전 79,277,840,399 − 법인세비용 19,235,046,848 =
  **60,042,793,551** = 복원값. [별도] 79,135,024,646 − 19,140,671,607 =
  **59,994,353,039** = 복원값.
- 미래에셋증권 [연결] BS: 지배기업소유주지분 항등식 **차이 0**(이익잉여금 1,828,134 백만원)

`extract_rows` 는 fact_v2/std_v2 와 공용이라 전체 스위트로 확인: `pytest tests/
fin2/tests/` **1149 passed**.

**회귀 테스트**: `fin2/tests/test_r152_compacted_supplementary_rows.py`(주석번호 날조
방지 케이스 포함).

**스코프(실측)**: 회사별 1건씩 599건 스캔 — 이 서식 보유 2건(0.3%), 압축칸 6개. 회사는
코리안리·미래에셋증권·대신증권 3사 확인. 금융업 한정 서식이고 2015년 구서식에 몰려
있다. ★전수 스코프 미확정 — 공용 함수 수정이라 캠페인 재적재 시 자동 해소된다
(R145/R149/R150 과 같은 취지로 전수 백필은 돌리지 않는다).

---

### R152-b — 보충표기의 0 을 **붙임표**로 찍는 변형(2026-09-23, 캠페인 이슈#32)

**증상.** 우리금융지주 2019FY `20200330004490` [별도] 재무상태표에서 **`5. 이익잉여금`
행이 통째로 없다**(자본금 → 신종자본증권 → 자본잉여금 → 기타자본 다음이 바로 자본총계).
값이 틀린 게 아니라 행이 사라졌다.

**원인.** R152 와 같은 압축칸인데 **보충표기 중 값이 0 인 것을 `-` 로 찍는다**:

    라벨  '5. 이익잉여금 (대손준비금 적립액) (대손준비금 전입필요액) (대손준비금 전입예정액)'
    금액칸 '623,930- (692)(692)'
             └본항목  └적립액=0  └전입필요액  └전입예정액

`_COMPACTED_PAREN_HEAD_RE` 는 본항목 **바로 뒤가 `(`** 일 것을 요구했는데 여기서는 `-` 다
→ 정규식이 빗나가 칸이 `None` → BS 는 당기열만 적재하므로 행이 사라진다. 붙임표·전각
대시는 한국 재무제표에서 0(해당없음)의 관용 표기다.

**수정.** 본항목과 첫 괄호 사이에 **0 자리표시 대시**(`-`·`−`·`–`·`—`)를 허용한다.
버릴 값이므로 자리만 건너뛴다. 라벨 게이트(`대손준비금|비상위험준비금`)가 이미 좁히고
있어 일반 금액칸에는 닿지 않는다.

**검증(앵커는 행 자신이 아닌 독립 합계).**

    복구된 이익잉여금            623,930
    자본금 3,611,338 + 신종자본증권 997,544 + 자본잉여금 14,874,084
      + 기타자본 (631) + 이익잉여금 623,930 = 20,106,265 = **자본총계**  ✓  (단위 백만원)

camp_run 이 DART 원문에서 읽은 자본총계와 정확히 일치한다. 회귀 테스트 3건 추가
(변이 검사 — 정규식을 되돌리면 2건 실패). 날조 방지 가드도 같이 고정했다: 주석번호 칸
`'26, 27'` 과 괄호 없는 `'1,234-5,678'` 은 여전히 결측이다.

**규모 — 4필링(★첫 측정은 모집단이 틀려 1건으로 보였다).**
SD 미러에서 `대손준비금|비상위험준비금` 을 가진 필링을 뽑아 수정 전/후로 재추출해 비교했다
(`scripts/measure_r152b_dash_variant.py`).

```
모집단 3,954 파일 → 2015+ 메타 보유 2,981 필링 측정
  변화 4필링 / 4행 · 손실 0
    20200330004490  우리금융지주 2019FY  별도BS 5. 이익잉여금   ← 최초 발견건(pending→백필)
    20190814002431  우리금융지주 2019H1  별도BS 4. 이익잉여금   ★status=pass
    20191114002590  우리금융지주 2019Q3  별도BS 5. 이익잉여금   ★status=pass
    20190329002351  푸른저축은행 2018FY  별도BS V. 이익잉여금   (pending→백필, 항등식 확인)
```

푸른저축은행 검산: `15,082,800,000 + 7,745,887,580 - 7,559,010,226 - 891,559,115
+ 233,234,921,544 = 247,613,039,783` = 자본총계 ✓

★★**첫 측정은 "1,520필링 / 변화 0건" 이었고 그게 틀렸다.** 모집단을 만든
`grep "대손준비금"` 이 **EUC-KR 필링을 통째로 놓쳤다**(그 바이트열이 파일에 없다) —
정작 당사자인 우리금융지주 `20200330004490` 이 목록에 없었다. 두 인코딩 패턴으로 다시
훑자 1,567 → **3,954 파일**로 늘고 숨어 있던 3건이 나왔다. 교훈은
[[feedback-grep-euckr-locale-trap]] 에 함정 ②로 기록했다.

★그리고 그 목록을 **검증**하다 두 번째로 오판할 뻔했다: `grep -c "우리금융"` 이 0건이라
"또 실패했다" 고 볼 뻔했는데, macOS 파일명이 **NFD** 라 NFC 문자열과 바이트가 달랐을
뿐이고 목록은 맞았다(ASCII 키 `20200330004490` 으로 확인). 같은 메모리 함정 ③.

**`pass` 보호 2건 — 사용자 승인받아 적재 완료(2026-09-23).**
`20190814002431`·`20191114002590` 은 `status='pass'` 라 R139 가드가 막았고, R162/R163
선례대로 **전용 스크립트에 rcept 를 하드코딩**해 `overwrite_reviewed=True` 로 적재했다
(`scripts/apply_r152b_reviewed_2.py`). 가드는 그대로 두고 이 2건만 예외다.
큐 `status` 는 건드리지 않았다 — 값만 채우고 검토 이력은 보존한다.

    20190814002431  이익잉여금 647,431,000,000   4 구성요소 합 = 자본총계 18,613,443,000,000 ✓
    20191114002590  이익잉여금 632,918,000,000   5 구성요소 합 = 자본총계 19,614,341,000,000 ✓

★그 스크립트는 **적재 후 자본 항등식을 검산하고 닫히지 않으면 그 건을 롤백**한다.
실제로 1차 실행에서 두 건 모두 롤백됐다 — 원인은 데이터가 아니라 **내 검산 코드**였다
(라벨에 '부채' 가 든 행을 미리 걸러내 `부채총계` 라는 정지 표지가 사라져, 역방향 탐색이
자산 행까지 쓸어담아 구성요소가 12~13개가 됐다). 가드가 잘못된 커밋을 막아준 셈이다.
검산을 고친 뒤 이미 백필된 2건(푸른저축은행·우리금융 2019FY)에서 `True` 가 나오는지
먼저 확인하고 다시 적용했다.

**잔여 — 남은 것은 전부 '고치면 날조' 라서 의도적 결측이다.**
같은 모집단에서 **적재되는 열(col_index=0)** 이 여전히 안 읽히는 칸은 **16필링 / 33셀**
이고 형태는 전부 자릿수 경계가 원문에 없는 것이다
(`scripts/scan_r152_unparsed_variants.py`):

```
구분자 없음              29   '1,633,162,5758,107,575210,886'   (대신증권 계열)
공백은 있으나 머리가 붙음   4   '114,026,569,60196,789,335,646 236,423,461,583 …'
```

R152 본문이 정한 대로 **손대지 않는다** — 어디서 끊는지 원문이 말하지 않으므로 복원하면
날조다(R6). 주석번호 칸(`'26, 27'`)은 금액이 아니라 집계에서 제외했다.

★**camp_run 은 "신규 패턴" 으로 보고했지만 R152 계열이다.** 이슈 로그에서 `대손준비금`
을 검색해 매치가 없어 그렇게 판단했는데, 이 계열은 이슈 로그가 아니라 **이 문서 R152**
에 있다. 교훈: 결함 계열 조회는 `docs/PARSING_RULES.md`(단일 진입점)를 먼저 볼 것.

---

### R152-c — 셀 안 `<SPAN>` 경계 개행이 첫 숫자를 쪼갠다(2026-09-24, 캠페인 이슈#41)

**증상.** 미래에셋증권 `20160516002286`(2016Q1) [연결] 재무상태표에서 `5. 이익잉여금`
행이 통째로 없다. 같은 필링 [별도] BS 의 같은 행은 멀쩡하다 — **연결만 깨지고 별도는
안 깨지는 비대칭**이라 R152/R152-b 로는 설명이 안 됐다.

**원인.** 압축칸이 평문 `<TD>` 가 아니라 여러 `<SPAN>` 으로 나뉘어 오는 변형이 있다.
DART 원문이 첫 `<SPAN>` 앞에서 줄을 바꾸면 그 개행이 본항목 금액 **한가운데**로 들어간다:

```
[연결] (깨짐)  <TD>1,\n<SPAN>958,360&cr;</SPAN><SPAN>(19,556)&cr;</SPAN><SPAN>3,315</SPAN></TD>
[별도] (정상)  <TD>1,882,018&cr;(19,556)&cr;3,315</TD>                       ← 평문, SPAN 없음
```

`_get_cells`(`''.join(child.itertext())`)는 그 개행을 그대로 보존하므로, R152 가 받는
칸 텍스트가 `'1,\n958,360\n(19,556)\n3,315'` 다. 토큰화(`.split()`)하면 첫 토큰이
`'1,'` 뿐이라 `_AMOUNT_LIKE_RE` 를 통과 못 하고, `_COMPACTED_PAREN_HEAD_RE` 도 콤마
바로 뒤에 숫자 3자리가 와야 하는데 개행이 끼어 있어 빗나간다 — 두 경로 모두 실패해
칸이 결측, 행이 통째로 사라진다. **R150(콤마 뒤 공백으로 쪼개진 숫자)과 원인은 같지만,
이번엔 셀 경계가 아니라 셀 안의 개행**이다.

**수정.** `_first_of_compacted_supplementary_cell` 토큰화 직후, R150 과 같은 방식으로
콤마로 끝나는 선행 토큰을 다음 토큰과 이어붙여 본다(`toks[0]+toks[1]` 이 온전한 숫자일
때만 채택). 주석번호 가드는 그대로 유지된다 — `'26,'+'27'='26,27'` 은 3자리 그룹이
아니라 `_is_complete_number` 가 거부한다.

**검증(독립 항등식, 지배기업소유주지분).**

```
자본금 1,703,883 + 자본잉여금 660,085 + 자본조정 (113,962) + 기타포괄손익누계액 130,233
  + 이익잉여금 1,958,360 = 4,338,599 = 지배기업소유주지분  ✓
지배기업소유주지분 4,338,599 + 비지배지분 679 = 4,339,278 = 자본총계  ✓ (단위 백만원)
```

**규모(`scripts/scan_r152c_span_newline_scope.py`, 2026-09-24).** 모집단 = `report_lines`
에 대손준비금/비상위험준비금 라벨이 이미 있는 필링(1,820건, DB 인구로 좁혀서 전수 XML
스캔보다 저렴하게). 각 필링을 현재 코드로 재추출해 `col_index=0` 인 보충표기 라벨이
DB 에 없는 것만 센다(★초판은 이 `col_index=0` 필터가 없어 전기/전전기 열까지 "DB 에
없음"으로 잡혀 84% 가 오탐이었다 — 적재 스코프와 같은 조건으로 비교해야 한다):

```
측정 1,820건 · 오류 0 · 영향(재추출하면 생기는데 DB 엔 없음) 171필링
```

교보증권·LS증권(구 이베스트투자증권)·제주은행·대신증권·푸른저축은행·한양증권·
유화증권 — 금융업(증권·은행·저축은행) 반기/분기/사업보고서에 몰려 있다(같은 회사가
매 분기 재현).

**백필(`scripts/backfill_r152c_span_newline.py --apply`, 2026-09-24).** 171필링 전부
성공(보호/실패 0). 안전장치: 전체 행수 감소 금지 + 보충표기 라벨 행수 감소 금지, 위반
시 롤백.

**회귀 테스트**: `fin2/tests/test_r152_compacted_supplementary_rows.py`
(`test_comma_split_by_span_boundary_newline_is_rejoined` 등 3건 추가, 실측 필링 1건
포함). `pytest fin2/tests/` 1,129 passed.

## R153. R116/R120 열선택 **예외 플래그**가 EPS 경로에 전달되지 않아 EPS 행이
## **두 경로 사이 틈으로 증발** (2026-09-20)

**발견 경로**: 행 단위 결측 탐지기(`fin2/audit/row_coverage.py`) 전수 센서스(회사별
1건씩 2,528개사). 형지I&C 20150514004898 [연결]·[별도] IS 에서 기본/희석/계속영업
주당이익 4행이 전부 결측으로 적출됐다.

**증상**: 같은 표의 일반 손익 행 17개는 정상 적재되는데 **EPS 4행만** 없다.

**원인 — 두 경로가 같은 함수를 다른 인자로 부른다**:
일부 필링은 손익계산서 열이 `[3개월|누적]` 2단인데 **누적 칸을 통째로 비워둔다**. R116 은
그런 Q1 필링을 예외목록(`_Q1_CUM_BLANK_USE_3M_RCEPTS`)에 두고 3개월 값을 누적으로 채택한다.
본류(`_emit_section_lines`)는 그 플래그를 넘겨 정상 행을 싣는다:

```python
pairs = list(select_by_header_columns(
    header_cols, row.amounts, raw_amounts=row.raw_amounts,
    allow_three_month_as_cumulative=(report_fiscal_period == "Q1"
                                     and rcept_no in _Q1_CUM_BLANK_USE_3M_RCEPTS),
    prefer_last_of_two_as_cumulative=(...)).items())
```

그런데 `_emit_eps_lines` 는 **같은 함수를 플래그 없이** 불렀다. EPS 행은 누적 칸이
공란이라 `pairs` 가 비어 `continue` 로 빠진다. 그리고 그 직후 본류의 EPS 위임 가드가
"`_is_eps_label` 이고 EPS 금액처럼 보이면 **무조건** 건너뜀" 이라 본류도 싣지 않는다 →
**행이 증발한다**. 어느 쪽도 "상대가 실었는지"를 확인하지 않는 구조다.

★R144 의 교훈("같은 판정을 두 경로가 각자 구현하면 갈린다")이 판정 **함수**만이 아니라
그 **인자**에도 적용된다. 같은 함수를 부르더라도 인자가 갈리면 결과가 갈린다.

**수정**: `_emit_eps_lines` 의 `select_by_header_columns()` 호출에 본류와 **같은 두
플래그**를 넘긴다(`report_fiscal_period`·`rcept_no` 는 이미 인자로 받고 있다).

**검증**: 예외목록 13건 전부 재추출 — **전건 EPS 행 복원 + 행 단위 결측 0건**.
형지I&C 20150514004898 은 EPS 16행 복원, 값도 원문과 일치(`'(7)'` → -7, `'4'` → 4).
같은 표의 일반 행은 불변(가산적 수정, 매출액 29,893,315,770 유지).
`pytest tests/ fin2/tests/` **1154 passed**.

**회귀 테스트**: `fin2/tests/test_r153_eps_column_exception_flags.py`. 상수 이름이 바뀌면
조용히 깨지므로 **플래그 배선 자체가 살아 있는지**도 소스에서 확인한다.

**스코프**: 예외목록에 든 필링 전부(현재 13건). 목록에 필링을 추가할 때마다 이 경로가
자동으로 같이 적용된다.

---

## R154. Q1 표가 **스스로 증명한** `3개월 = 누적` 등식을 읽어, 누적 칸이 공란인
## 행을 구제한다 — R116 예외목록의 일반화 (2026-09-21)

**발견 경로**: 계층2 원문전체대조 캠페인 이슈#20(peer 세션 `camp-run-79` 보고).
기아 00106641 `20240516001819`(2024Q1) [연결]·[별도] 손익계산서에서
`기본주당이익` 행이 DB 에 **통째로 결측**. 원문에는 연결 7,125/전년 5,323,
별도 5,495/전년 2,251 이 있다.

**증상 — R153 과 같은 자리, 다른 이유**:
R153 은 플래그 **배선**이 빠져 EPS 경로가 열선택 예외를 못 썼다(배선 수정 완료).
이 건은 배선은 살아 있는데 **플래그가 켜지지 않는다** — R116 예외목록
(`_Q1_CUM_BLANK_USE_3M_RCEPTS`)에 기아가 없기 때문이다.

**원문 구조**(연결, 별도 동형):

```
헤더:        [3개월(0), 누적(1), 3개월(2), 누적(3)]
매출액:      26,212,851 | 26,212,851 | 23,690,660 | 23,690,660
매출원가:    19,976,744 | 19,976,744 | 18,317,258 | 18,317,258
…(전 행 동일)…
기본주당이익:      7,125 |    (공란) |      5,323 |    (공란)   ← 유실
```

R144 정책상 2단 헤더 표는 **누적 열만** 싣는다. EPS 행은 누적이 공란이라 `pairs` 가
비고 → EPS 경로가 `continue`, 본류는 EPS 위임 가드로 건너뜀 → **행 증발**.

**왜 예외목록으로는 부족한가**:
R116 이 rcept 예외목록으로 좁힌 이유는 "실측이 두 필링에서만 확인됐다"였지 **등식이
의심스러워서가 아니다** — 1분기는 정의상 연초부터 분기말까지의 누적이 곧 그 3개월
자체다. 목록 방식은 같은 서식을 쓰는 다른 회사·연도를 계속 흘린다.

★**정정**(2026-09-21, 백필 dry-run 중 확인): 처음 이 규칙을 쓸 때 "현대사료
`20260515002785` 도 같은 모양"이라고 적었는데 **틀렸다**. 현대사료는
`['기본주당이익(손실)', '', '', '15', '']` 로 **당기 칸이 3개월·누적 둘 다 공란**이다 —
원문에 당기 EPS 가 아예 없는 것이라 구제 대상이 아니다(R154 가 켜져도 전기만 나오고,
전기는 `_PERIOD_AXIS_STATEMENTS` 정책상 애초에 적재 대상이 아니다). 기아는 당기
3개월이 **채워져 있다**(7,125) — 그게 이 규칙이 구제하는 모양이다. 실제 규모는 아래
검증란의 백필 실측치를 볼 것.

★같은 이유로 **이화공영 `20250515002174`·로보티즈 `20220816000335` 류도 결함이
아니다** — 전기 누적만 차 있고 당기가 공란이라, DB 에 당기 EPS 가 없는 게 정상이다.
"추출됐다"와 "DB 에 실린다"는 다르다(IS 는 col_index=0 만 적재).

**수정 — 목록 대신 표 자신의 증거**
(`fin2/extract/report_lines.py::_q1_cumulative_proved_equal_to_three_month`):

같은 period_rank 안에 `three_month` 와 `cumulative` 열이 둘 다 있는 표에서,
**양쪽이 다 실값인 행**을 증인으로 센다.

- 증인이 1개 이상이고 **전부 3개월 == 누적** → 증명됨 → `allow_three_month_as_
  cumulative=True`
- 반례가 **하나라도** 있으면(3개월 ≠ 누적) 즉시 거짓 — 그 표는 애초에 이 축이 아니다
- 한쪽이 공란인 행(= 구제 대상)은 증인이 못 된다(자기 자신으로 자기를 증명할 수 없다)

호출측이 `report_fiscal_period == "Q1"` 을 확인한 뒤에만 부른다(등식은 Q1 에서만 성립 —
H1/Q3 는 3개월 ≠ 누적).

★**R6 와 충돌하지 않는다**. R6 이 막는 것은 "서로 다른 값 중 하나를 짐작하는" 것이다.
여기서는 짐작하지 않는다 — **필링 자신이 표에 적어 둔 등식을 읽을 뿐**이다. 반례가
하나라도 보이면 규칙이 꺼지므로, 등식을 지키지 않는 표에는 절대 발동하지 않는다.

★**판정은 표당 한 번**, 본류와 EPS 경로에 **같은 값**을 넘긴다. R144/R153 의 교훈
("같은 판정을 두 경로가 각자 하면 갈린다")을 그대로 지킨다.

**R116 예외목록은 그대로 둔다** — 그 목록의 필링들은 증인이 1행(당기순이익)뿐이라
자기증명 규칙으로도 통과하지만, 목록을 지우면 원문이 바뀌었을 때 조용히 동작이 달라진다.

**검증**:
- 기아 `20240516001819` — 원문 네 값 전부 복원(연결 7,125/5,323, 별도 5,495/2,251)
- 같은 표의 일반 행 불변(연결 매출액 26,212,851백만, 별도 15,711,802백만 유지)
- 증거 판정 단위 테스트: 반례 1개로 규칙이 꺼지는지 / 공란 행이 증인이 안 되는지 /
  무표지 병합군(R120/R131 축)은 대상 밖인지
- `pytest tests/ fin2/tests/` **1163 passed**

**스코프**: Q1 필링 중 `[3개월|누적]` 2단 헤더 표 전부.

**백필 실측**(`scripts/backfill_r154_q1_eps.py`, 2026-09-21 완료): 2015+ Q1 손익계산서
적재 26,339건 중 EPS 0건인 후보 906건을 전수 재추출 → **77건 복원(273행) 적재, 오류 0**.
나머지는 원문에 당기 EPS 가 없는 정상 건이다(전기만 있거나 EPS 행 자체가 없음).

★**77건을 R154 의 성과로 읽으면 안 된다.** 재추출은 그동안 쌓인 **모든 미백필 수정을
한꺼번에** 반영한다. 표별로 R154 발동 여부를 다시 판정해 나눈 결과:

| 구분 | 건수 | 내용 |
|---|---:|---|
| **R154 발동** | 21 | 2단 헤더 + 자기증명 성립 (아즈텍WB·엠로 등) |
| 2단 헤더 아님 | 54 | **다른 규칙**이 이미 고쳤는데 Q1 필링에 백필이 안 돌았던 것 — 대부분 R149(`'3,682원'` 원 접미사). 하나금융지주·카카오뱅크·LG씨엔에스 등 |
| 2단인데 미증명 | 2 | 다른 경로로 복원 |

★교훈: **백필 복원 건수를 특정 규칙의 효과로 귀속하지 말 것.** 세 번 연속 같은 실수를
했다 — "추출됐다 ≠ DB 에 실린다", "복원됐다 ≠ 이 규칙이 고쳤다". 귀속하려면 그 규칙의
발동 조건을 **표별로 다시 판정**해야 한다.

**관련**: R116(예외목록 원형) · R144(누적 열 정책) · R153(플래그 배선) · R6(짐작 금지)

---

## R155. **[R168 로 대체 — 산수 자기증명 시 적재]** 구형 2단 열(내역칸/잔액칸) 서식에서 양쪽이
## 다 찬 "그룹 마감행"이 R6 판정불가로 유실된다 (2026-09-21, 전수 스캔으로 종결)

**발견 경로**: 행 단위 결측 탐지기(`fin2/audit/row_coverage.py`) 전수 센서스.
티로보틱스 `20180402000209`(FY2017) [별도] 대차대조표에서 14행 유실.

**구조**: 구형 인쇄 서식은 한 연도를 물리적으로 **2열**([내역칸, 잔액칸])로 찍는다.
헤더는 `['과목','2017년','2016년','2015년']` + `['금액','금액','금액']` 이고 각 연도가
COLSPAN=2 로 2칸을 덮는다. 대부분 행은 둘 중 **한쪽만** 채우지만, **그룹 마감행**은
양쪽을 다 채운다:

```
(2) 재고자산                      2,824,871,561   ← 잔액칸만
원  재  료       2,348,042,580                    ← 내역칸만
원재료평가충당금     30,712,381   2,317,330,199   ← 양쪽 다 → 유실
```

**원인**: `select_by_header_columns()` 의 무표지 병합군 분기는 실값이 2개 이상 서로
다르면 **판정불가로 그 rank 를 건너뛴다**(R6 "오염보다 결측"). `pairs` 가 비면 행 자체가
emit 되지 않아 **흔적 없이 사라진다**.

**값 자체는 확정 가능하다** — 왼쪽=그 행 자신의 금액, 오른쪽=직전 그룹의 잔액이고
산수로 검증된다:

- 건물 2,939,077,158 − 감가상각누계액 470,337,475 = **2,468,739,683** (오른쪽 칸)
- 원재료 2,348,042,580 − 평가충당금 30,712,381 = **2,317,330,199** (오른쪽 칸)

**그런데 고치지 않기로 했다**(2026-09-21, 사용자 위임 후 판단). 근거는 전수 스캔이다
(`scripts/scan_dual_column_periods.py`, 회사별 1건씩 **2,528개사**):

| 지표 | 값 |
|---|---|
| 발화 필링 | **1건**(티로보틱스 `20180402000209`) |
| 유실 행 | 14행, 전부 `sep/BS` |
| 오류 | 0 |

1. **빈도**: 2,528개사 중 1건. 티로보틱스 자신의 37개 필링 중에서도 1건뿐이다.
2. **영향**: 유실된 14행은 전부 차감성 보조행(대손충당금·평가충당금·감가상각누계액·
   국고보조금·신주인수권조정·퇴직연금운영자산)이다. **본항목**(재고자산 2,824,871,561,
   유형자산 11,273,240,628 등)은 정상 적재돼 재무제표 골격에 구멍이 없다.
3. **대가**: 고치려면 R6 안전장치를 완화해야 하는데, 이 코드 경로는 **보험·증권사
   명세/소계 서식 전체**가 쓴다(R125). 14행을 얻자고 수천 건이 의존하는 안전장치를
   푸는 것은 손익이 맞지 않는다.

**★`is_ifrs` 로는 이 계열을 못 찾는다.** 2015+ 에 K-GAAP **회계기준** 필링은 사실상
0건인데(실측: 2016년 링크제니시스 2건뿐) 티로보틱스는 IFRS 필링이면서 **인쇄 서식**만
구형이다. 회계기준이 아니라 **구조**로 세야 한다.

**★2026-09-24 R168 로 뒤집힘** — 회사×필링 스캔에서 크래프톤 16필링 94행이 나왔고, R6 을 풀지 않는 산수 자기증명 방식으로 고쳤다. 아래 판단 근거는 당시 기록으로 남긴다.

**재발 감시**: 탐지기(`scripts/scan_dual_column_periods.py`)를 남겨 둔다. 같은 서식이
늘어나면 다시 세어 판단을 뒤집을 수 있다. 판정 오라클은 `select_by_header_columns()`
**자신**이고, `rank 0`(당기)만 센다 — BS/IS/CF 는 `_PERIOD_AXIS_STATEMENTS` 정책상
col_index=0 만 적재하므로 전기가 안 뽑혀도 DB 에서 잃는 게 없다.

**스캔의 한계**(정직하게 남긴다): breadth 모드는 **회사별 가장 오래된 1건**만 본다.
구형 서식은 오래된 필링에 몰리므로 이 표본이 유리하긴 하지만, 어떤 회사가 중간 연도에만
이 서식을 썼다면 놓칠 수 있다. 전수(회사×필링)는 돌리지 않았다.

**관련**: R6(짐작 금지) · R125(명세/소계 COLSPAN=2) · R131(값이 같으면 항상 채택) ·
R114(대시 열 제외)

---

## R156. **[설계대로 — 캠페인 판정 기준]** 분기·반기 필링에서 **누적 칸이 공란인 행**은
## 적재되지 않는다(3개월만 있어도) — Q1 이 아니면 구제하지 않는다 (2026-09-21)

**발견 경로**: 계층2 캠페인 이슈#21(peer 세션 `camp-run-79`). 현대모비스
`20201116000573`(2020**Q3**) [연결] 기타포괄손익 표에서
`기타포괄손익-공정가치 측정 금융자산 처분이익(손실)`(3개월 −363) 한 줄만 결측.
위·아래 행은 정상 적재돼 "딱 한 줄만 빠지는" 모양이라 신규 패턴으로 보였다.

**원문**(연결 CI 표, 헤더 `[3개월, 누적, 3개월, 누적]`):

```
평가이익(손실)     36,135 |  34,004 | (2,241) | (3,263)   → 적재
처분이익(손실)      (363) |  (공란) |  (공란) |  (공란)   → 안 실림 ←
지분법자본변동      5,641 | (27,032)|  (공란) |  (공란)   → 적재
```

**원인 = 설계**: R144 정책상 분기·반기 표는 **누적 열만** 싣는다. 이 행은 누적 칸이
**원문에서 비어 있어** `select_by_header_columns()` 가 아무 값도 채택하지 않고
(`picked={}`) 행이 emit 되지 않는다.

**왜 구제하지 않는가**: Q3 는 3개월 ≠ 누적이다 — 같은 표 바로 위 행이 그것을 증명한다
(3개월 36,135 vs 누적 34,004). 그러니 −363 을 누적 값으로 저장하면 **날조**다
(R3/R85 "짐작 금지"). R154 의 자기증명 규칙은 **Q1 에서만** 성립하는 등식에 기대므로
Q2·Q3 에는 적용할 수 없다. 또한 같은 표에서 바로 아래 행은 누적을 채웠으니, 빈 칸은
제출사 자신의 기재누락이다.

**구조적으로 저장할 자리도 없다**: `report_lines` 는 BS/IS/CF 를
`_PERIOD_AXIS_STATEMENTS` 정책상 `col_index=0`(당기 **누적**)만 적재한다. "3개월만
있는 값"을 담을 축이 애초에 없다.

**★camp_run 의 두 가설은 둘 다 아니었다**(다음 세션이 같은 데를 파지 않도록 기록):
- ✗ "유사 라벨 쌍(`평가이익(손실)`/`처분이익(손실)`)을 같은 개념으로 오인해 dedup" —
  라벨 정규화는 개입하지 않는다. `extract_rows` 산출물에 두 행이 **각각 살아 있다**.
- ✗ "값이 작아(−363) 임계값 필터에 걸림" — 임계값이 아니다. 같은 표의 `350`·`334`
  (더 작은 값)는 정상 적재된다.

실제 갈림점은 **누적 칸이 찼는지 하나뿐**이다.

### 캠페인 판정 기준(이 모양을 만나면)

| 원문 상태 | 판정 |
|---|---|
| 분기·반기에서 **3개월만 있고 누적이 공란** | **정상**(R156) — 비고에 적고 pass |
| **Q1**에서 3개월만 있고 누적 공란인데, 같은 표 다른 행들이 3개월=누적을 증명 | **결함** → R154 가 고침. 재적재하면 나옴 |
| **Q1**에서 당기가 3개월·누적 **둘 다** 공란 | **정상** — 원문에 당기 값이 없다 |
| **전기에만** 값이 있다 | **정상** — 전기는 애초에 적재 대상이 아니다 |
| 누적 칸이 **차 있는데도** 결측 | **결함** → 이슈로 올릴 것 |

**관련**: R144(누적 열 정책) · R3/R85(짐작 금지) · R154(Q1 자기증명 예외) ·
R116(Q1 예외목록) · R155(다른 '수정 안 함' 건)

---

## R157. `parse_amount()` 가 소수부를 **단위 배수 적용 전에** 버려, 선언 단위가 있는
## 표에서 값이 조용히 깎였다 (2026-09-22)

**발견 경로**: 캠페인 이슈#22(엘에스일렉트릭) 조사 중 `parse_amount` 를 읽다가 발견.

**원인**(`parser/common/amount_normalizer.py`):

```python
val = int(s) if _PLAIN_INT_RE.fullmatch(s) else int(float(s))   # ← 소수부 절삭
val *= multiplier                                                # ← 그 뒤에 배수
```

소수부를 먼저 버리고 배수를 곱하므로, 단위가 선언된 표에서 소수부만큼이 사라진다:

| 셀 | 선언 단위 | 종전 | 정확값 |
|---|---|---|---|
| `1,234.5` | 백만원 | 1,234,000,000 | 1,234,500,000 |
| `1,234.56` | 천원 | 1,234,000 | 1,234,560 |
| `0.5` | 백만원 | **0** | 500,000 |

`0.5` → **0** 이 특히 나쁘다 — 결측이 아니라 **값 왜곡**이라 기존 검산이 못 잡는다
(그럴듯한 값이 들어 있다).

**수정**: 배수를 **먼저** 적용하고 `ROUND_HALF_UP` 으로 반올림한다.
★`float` 대신 `Decimal` 을 쓴다 — float64 는 유효자릿수 15~17 자리라 큰 값에서 조용히
틀어진다(바로 위 정수 경로가 float 를 피하는 것과 같은 이유). `decimal.InvalidOperation`
은 `ValueError` 가 아니라 `ArithmeticError` 계열이라 except 절에 따로 추가했다.

**배수 1 인 경우는 결과 불변**: 주당손익 소수(`'69.0'`·`'343.0'`·`'213.00'`)는 소수부가
0 이라 반올림해도 그대로다.

**스코프**: 전수 스캔(회사별 1건씩 2,528개사) 결과 **선언 단위가 있는 표의 소수 셀은
0건**이었다 — 코드상 실재하는 결함이지만 실측 피해는 확인되지 않았다. 백필 불필요.
★규모를 부풀려 보고하지 않기 위해 이 사실을 명시한다.

---

## R158. 천단위 구분자가 **마침표**로 깨진 셀 — 행 안의 정수 짝과 대조해 복원
## (2026-09-22, 캠페인 이슈#22)

**발견 경로**: 계층2 캠페인 이슈#22(peer 세션 `camp-run-e2`). 엘에스일렉트릭 00105855
`20260318001243`(2025FY) [별도]·[연결] SCE 값이 10⁻⁶ 로 왜곡.

**증상**: 같은 열 안에서 표기가 섞인다.

```
2023 배당지급      (32,291,650,600)   ← 원 단위 정수
2024 배당지급      (82,196.9288)      ← 깨진 셀
2024 기말자본      1,628,305,256,299  ← 다시 정수
```

DB 실측: `배당금의 지급` 에 `-82196`·`-86133` 이 정상값 `-32,495,350,600` 과 **나란히**
들어가 있었다. 결측이 아니라 값 왜곡이라 검산을 통과한다.

**원인 — 단위 표기 문제가 아니다**: 콤마 하나가 **마침표로 렌더**돼 소수점처럼 보이는
것이다. 결정적 증거 둘:

- **트리니티항공 `20260515001132`** — **같은 값**이 연결 표엔 `'41,106,779.959'`,
  별도 표엔 `'41,106,779,959'` 로 찍혔다.
- **코오롱 `20260515002605`** — 한 행 안에 나란히 있다: `'393,211,876'`, `'393,211.876'`.

**수정**(`parser/xml/table_extractor.py::_repair_dot_grouped_cells`): 깨진 셀의 숫자열이
같은 행의 **정수 칸** 숫자열의 접두사이고 남는 꼬리가 전부 0 이면, 그 정수 칸의 자릿수를
채택한다.

```
'42,549.493'   ↔ '42,549,493'      (정확히 일치)
'10,590,556.9' ↔ '10,590,556,900'  (꼬리 '00' — 잘린 뒤 0)
'2,168.045996' ↔ '2,168,045,996'   (두 그룹이 깨진 경우)
```

★**추측이 아니다** — 정확한 값이 필링 자신의 같은 행에 정수로 적혀 있고 그 자릿수만
가져온다(R154 자기증명 규칙과 같은 논리). 텍스트만으로는 배율이 안 나온다(뒤 0 이
잘리므로) — 이 대조가 유일한 근거다.

★**손대지 않는 것**: 짝이 없거나 후보가 둘 이상이면(판정불가, R6) 그대로 둔다. 그래서
주당손익처럼 **원 단위 소수가 정상인** 값이 보호된다(에스티아이 `20260515000677`
`희석당기순이익 (단위 : 원) '343.0'` — 행 안에 짝이 없어 손대지 않는다).

**★두 추출 경로 모두에 배선해야 한다**:
① `extract_rows`(BS/IS/CF) ② `report_lines.py` 의 **SCE 그리드 경로**(셀을 개별
`parse_amount` 하는 별도 경로). 처음에 ①만 고치고 "복원 OK" 라고 판정했는데, 보였던
정상값은 **복원된 게 아니라 옆 칸 자기 값**이었고 깨진 칸에는 `-6,105` 가 그대로
남아 있었다(엘에스일렉트릭 별도 SCE col=3). R144/R153 의 교훈("같은 판정을 두 경로가
각자 하면 갈린다")이 또 나왔다 — 회귀 테스트가 두 경로의 배선을 소스에서 확인한다.

**검증**:
- 엘에스일렉트릭 별도 SCE 6개 값 전부 원문과 일치, 왜곡값 잔존 **0**
- 복원 대상 7계열(아이에스동서·금호석유화학·SNT다이내믹스·와이지-원·코오롱·SOOP·
  롯데이노베이트) 정확히 복원, 보호 대상 2계열(에스티아이 EPS·트리니티항공 짝 없음)
  불변
- `pytest tests/ fin2/tests/` **1202 passed**

**스코프**: 전수 스캔(`scripts/scan_decimal_cells.py`, 회사별 1건씩 2,528개사) →
**11필링 32셀**(0.4%). 그중 4셀은 오탐(에스티아이 EPS). ★발화가 전부 fy2026 이지만
breadth 표본이 **회사별 최신 1건**만 보므로 시간 추세는 주장할 수 없다.

**행 안에 짝이 없는 경우**: 정확한 값이 **같은 열의 다른 행·반대 basis 표·다른
재무제표**에 있거나 **합계 항등식**으로만 확정되는 셀은 이 규칙(같은 행 대조)으로
복원되지 않는다. 그런 셀은 **R159 예외목록**으로 개별 교정했다(핸즈코퍼레이션 4셀·
트리니티항공 3셀·코오롱 2셀 — 전부 사용자 확정 후 등재, 백필 완료).

★이 규칙을 같은 **열**이나 표 전체로 넓히지 않은 이유: 열/표 범위로 넓히면 "우연히
숫자열이 접두사인 무관한 값"을 짝으로 잡을 위험이 커진다. 같은 행은 의미적으로 한
항목이라 안전하고, 그 밖은 사람이 원문을 확인해 예외목록에 넣는 편이 안전하다.

**관련**: R157(같은 함수의 다른 결함) · R6(짐작 금지) · R154(자기증명 규칙) ·
R144/R153(두 경로 배선) · R149/R150(같은 함수 계열)

---

## R159. **원문 자체의 오타 셀**을 rcept 예외목록으로 교정 (2026-09-22, R118 패턴)

**발견 경로**: R158 적용 후 잔여 8행 조사. 핸즈코퍼레이션 00119140 `20260515002776`
(2026Q1) 연결·별도 자본변동표 **자본금** 열의 `'10,937,873.5'`.

**사용자 진단**(2026-09-22): `,500` 이 `.5` 로 찍힌 **오타**다.

**정정값이 원문으로 확정된다** — 같은 표 `2025.01.01 (기초자본)` 행의 같은 열에
`10,937,873,500` 이 정수로 인쇄돼 있고, 자본금은 그 사이 변동이 없다. 추측이 아니다.

```
2025.01.01 (기초자본)   '10,937,873,500'   ← 정수(정답)
2026.01.01 (기초자본)   '10,937,873.5'     ← 깨진 셀, 같은 자본금 열
```

★R158(같은 **행**의 정수 짝 대조)은 이 건을 복원하지 못한다 — 정답이 같은 **열**의
다른 행에 있기 때문이다.

**왜 `manual_report_lines` 를 쓰지 않는가**(사용자 확인 후 A안 채택):
`store_manual_report_lines()` 는 `(rcept_no, statement, basis)` 스코프를 통째로
delete-then-insert 한다. 셀 4개를 고치려고 **SCE 연결 52행 + 별도 28행 = 80행을 전부
손으로 옮겨 적어야** 하고, 그 스코프는 `unit_source='manual'` 이 되어 이후 자동 재추출의
manual 보호 가드에 막힌다 — 정상인 나머지 76행이 파서 개선 혜택에서 영구 제외된다.
게다가 파서 산출물을 옮겨 적는 것은 "사람이 원문을 읽고 입력한다"는 manual 의 취지와도
맞지 않는다.

**수정**(`parser/xml/table_extractor.py`):

```python
_SOURCE_TYPO_CELL_FIXES = {
    ("20260515002776", "10,937,873.5"): "10,937,873,500",
}

def apply_source_typo_fixes(cells, rcept_no): ...
```

**등재 조건**(사용자 확정): 정정값이 **원문으로 추측 없이 확정될 때만**. 근거를 주석에
반드시 남긴다(회귀 테스트가 항목마다 근거 주석 존재를 검사한다). 인정되는 근거 두 가지:

**(가) 정수판이 원문 다른 곳에 인쇄돼 있다** — 같은 열의 다른 행, 반대 basis 표, 다른
재무제표 어디든. 실측 등재:

| 필링 | 깨진 셀 | 정수판 위치 |
|---|---|---|
| 핸즈코퍼레이션 `20260515002776` | `10,937,873.5` | [별도SCE] `2025.01.01 (기초자본)` 같은 열 |
| 트리니티항공 `20260515001132` | `41,106,779.959` | [연결SCE] `2025.01.01 (기초자본)` 같은 열 |
| 트리니티항공 | `64,885,221.582` | [연결SCE] `유상증자` |
| 트리니티항공 | `281,021,610.634` | [연결BS] `주식발행초과금` |

**(나) 그 행의 합계 항등식이 정확히 닫힌다** — 합계 열이 원문에 인쇄돼 있으므로 이것도
추측이 아니다. 실측 등재 — 코오롱 `20260515002605` 연결SCE `주식선택권의 부여`
(열 구조 `[… 기타자본구성요소, 지배지분 합계, 비지배지분, 자본 합계]`):

```
138,959,866 + 43,752,934 = 182,712,800   ← 자본 합계 열(원문 인쇄값)
393,211,876 +  7,823,674 = 401,035,550
```

★코오롱은 **한 행에 오타가 두 칸** 있다(사용자 지적). 왼쪽 `지배지분 합계` 칸은 바로 옆
정수와 같은 값이라 R158 이 행 안 대조로 복원하고, 남는 `비지배지분` 칸을 (나)로 등재했다.

HD한국조선해양 `20250515002500`(2025Q1 연결SCE, 사용자 DART 원문 직접확인 2026-09-23)도
(나)에 해당한다 — 세 행 모두 정수판이 다른 칸에 없어 R6/R160 목록(`docs/qa/
dot_typo_needs_dart_2026-09-23.md`)으로 확인을 요청했었다. 사용자가 원문을 보고 셋 다
콤마 오타로 확정:

```
자본 총계>비지배지분 열, [연결] 자본변동표
'(41.423)'      → -41,423,000   (기타포괄손익-공정가치측정금융자산평가손익, row_order=2)
'(1,259.803)'   → -1,259,803,000 (파생상품평가손익, row_order=3)
'3,082.923'     → 3,082,923,000  (파생상품평가손익, row_order=15)
```

복원값은 그 행 자신의 항등식으로 검산된다 — 지배기업 소유주지분 합계 + 비지배지분 =
자본 총계 합계(세 행 모두 정확히 닫힘). `apply_r158_dot_typo_confirmed.py --apply` 로
재적재(status='pass' 라 R139 가드 우회 필요, `overwrite_reviewed=True`).

HD한국조선해양 `20250318001131`(2024 사업보고서) 연결SCE `파생상품평가손익`
**비지배지분** 칸도 사용자가 확정했지만, 이 건은 `report_dot_typo_candidates.py`
의 항등식 검사기 자체가 **놓치고 있던 패턴**을 드러냈다 — 자세한 원인·수정은 바로
아래 "확인요청 스캔 스크립트 — 2단 항등식 놓침 수정" 참고.

### 확인요청 스캔 스크립트 — 2단 항등식 놓침 수정 (2026-09-23)

`scripts/report_dot_typo_candidates.py` 의 근거(나)(행 항등식) 검사가 **`vals[:t]`
전부를 더해 `vals[t]` 와 비교**하는 방식이었다. SCE 는 흔히 2단 구조다 —
구성요소(자본금..이익잉여금) → **부분합**(지배기업 소유주지분 합계) → **부분합 +
비지배지분 = 총계**. 전부 누적하면 구성요소와 그 부분합을 **동시에** 더해
이중계산이 되어 절대 안 닫힌다.

HD한국조선해양 `20250318001131` `파생상품평가손익` 행에서 사용자가 손으로 이
항등식(부분합+비지배지분=총계)을 확정하고 나서야 드러났다 — 스캔은 이 셀을
"근거 없음"(DART 확인 필요)으로 분류했지만 실제로는 항등식이 명확히 닫혔다.

**수정**: `_find_identity()` 로 교체 — `vals[:t]` 전체가 아니라 **깨진 셀 값을
포함하는 작은 부분집합**(최대 4개, 총계에 가까운 열부터 우선)을 찾는다. 부분합
열 자신이 총계인 경우(`t == mi`)는 기존처럼 "그 앞 전부의 합"으로 정의를 유지한다
(그건 부분합의 정의 자체이지 탐색이 아니다).

**효과**(전수 233필링 재스캔, 2026-09-23): `dot_typo_needs_dart` 목록
40필링/166셀 → **27필링/105셀** (58셀이 자동으로 근거를 얻어 DART 확인 불필요
해짐). ★근거가 붙어도 **자동 등재는 안 한다** — R6 원칙대로 사람 확인 후 여전히
`_SOURCE_TYPO_CELL_FIXES` 수동 등재.

★**적용 순서** — 오타 교정을 R158 복원보다 **먼저** 한다(교정된 셀은 정상 정수가 되므로
복원이 건드릴 일이 없어진다). 테스트가 소스에서 이 순서까지 확인한다.

★**두 경로 모두에 배선**: `extract_rows`(BS/IS/CF)와 `report_lines._grid_body_rows`
(SCE). `rcept_no` 를 두 함수에 optional kwarg 로 넘긴다 — R158 때 한 경로만 고쳐
SCE 가 새는 일을 이미 겪었다.

**검증**: 자본금 8행(연결·별도 × 4기간) 전부 `10,937,873,500` 으로 정정, 남은 왜곡 0.
같은 필링 EPS 4행 불변(`-1,500`·`-1,483`·`-768`·`-758`).

---

### R158 후속 — EPS 라벨 가드 추가 (2026-09-22)

R158 복원 함수에 **주당손익 배제**가 없었다. 핸즈코퍼레이션 같은 필링의 연결 IS 에는
이런 행이 실제로 있다:

```
['계속영업 기본주당순손실 (단위 : 원)', '(1,500.00)', '(1,500)', '(167.00)', '(167.00)']
```

지금 규칙으로는 우연히 안 걸리지만(`1,500.00` 의 숫자열 `150000` 이 `1500` 보다 길어
후보에서 빠진다), `['주당이익', '(1,500.00)', '(1,500,000)']` 배치가 나오면 EPS 를
**1,500,000 으로 날조**한다. 주당 금액은 원 단위 소수가 정상이므로 **라벨로 먼저
배제**한다(`_EPS_ROW_LABEL_RE`). 스캐너에는 이 배제가 처음부터 있었는데 복원 함수에는
없던 비대칭을 해소한 것이다.

★이 가드는 사용자 승인 대기 중이던 항목이지만, 내가 방금 넣은 코드가 값을 **날조할**
경로였고 사용자가 자리를 비우는 상황이라 방어 조치로 먼저 적용했다(위험 차단이 지연보다
안전하다고 판단). 되돌리려면 `_repair_dot_grouped_cells` 의 라벨 인자만 제거하면 된다.

---

## R160. 해결되지 않은 **마침표 셀은 적재하지 않는다** — 결측으로 남기고 확인 요청
## 목록으로 보고 (2026-09-22, 사용자 정책)

**사용자 정책**(2026-09-22): *"재무문서에 '.' 으로 되어 있는 큰 금액 오타를 반올림해서
적재하거나 그대로 하지 말고, 오타로 보고해서 나에게 확인 요청할 리스트 문서를
제공하라."*

**왜** — 종전 동작은 **어느 쪽이든 정밀해 보이는 틀린 값**을 DB 에 남겼다:

| 동작 | 결과 | 오차 |
|---|---|---|
| 종전 `int(float())` 절삭 | `10,937,873.5` → 10,937,873 | 10³ 배 작음 |
| R157 반올림 | `10,937,873.5` → 10,937,874 | **여전히** 10³ 배 작음 |
| R160 (현재) | **결측** | 사실이 드러난다 |

값이 그럴듯하니 기존 검산을 전부 통과한다 — 결측보다 위험하다. R6("오염보다 결측")를
이 자리에도 적용한다.

**대상 조건** — 둘 다 만족할 때:
1. 마침표-구분자 패턴(`_DOT_GROUPED_RE`)
2. **주당손익 행이 아니다** — per-row 단위 행은 소수가 정상이다

★**단위 선언으로 예외를 두지 않는다**(사용자 결정, B안). 초판 설계는
`multiplier != 1`(천원/백만원 선언 표)을 "소수가 정상 표기"라며 제외했는데, 그건
**관측 없이 단정한 것**이었다 — 전수 스캔 2,528개사에서 나온 소수 셀 32개는 **전부
선언단위 '원'** 이고 천원/백만원 표의 소수는 **0건**이다. 정상이라는 증거가 없으므로
예외를 두지 않는다. 실측 0건이라 당장 바뀌는 동작은 없고, 그런 필링이 나타날 때 파서가
임의로 판단하지 않게 된다. 함수 시그니처에서 `multiplier` 를 **아예 없앴다** — 그 실수가
되살아나지 않도록(테스트가 시그니처를 검사한다).

★**주당손익 판정은 '주당' 문자열만으로 부족하다.** 실측: 에스티아이 `20260515000677`
별도IS `['희석당기순이익 (단위 : 원)', '343.0', …]` — 라벨에 '주당' 이 없지만 343원은
주당 금액이다. 이걸 결측으로 만들면 **실제 데이터를 잃는다**(R160 회귀 테스트에서
드러났다). 그래서 **라벨이 자기 단위를 원으로 선언한 행**(`(단위 : 원)`)도 배제한다 —
R149 가 셀 단위 '원' 접미사를 같은 취지로 다루는 것과 짝을 이룬다.

**적용 순서**: R159(오타 교정) → R158(행 안 정수 짝 복원) → **R160(남은 것 결측)**.
앞 둘이 해결한 셀은 이미 정상 정수 텍스트라 이 패턴에 걸리지 않는다. 두 추출 경로
(`extract_rows`, `report_lines._grid_body_rows`) 모두에 배선했고 테스트가 소스에서
확인한다.

**확인 요청 목록**(`scripts/report_dot_typo_candidates.py`): 셀마다 DART 링크·재무제표·
행·열·단위·원문 셀과 **근거 두 갈래**를 붙여 Markdown 문서로 출력한다.

- (가) **정수판** — 같은 필링 원문 다른 곳에 인쇄된 정수(숫자열이 접두사로 일치하고
  남는 꼬리가 전부 0)
- (나) **합계 항등식** — 마침표를 콤마로 되돌린 값으로 행 합계가 정확히 닫히는 조합

★(나)는 **깨진 셀의 가설값이 그 식에 실제로 들어갈 때만** 근거로 싣는다. 초판은 행 안에서
합이 맞는 아무 두 값을 잡아, 핸즈코퍼레이션 자본금 칸에
`93,409,170,815 + 208,771 = 93,409,379,586`(지배지분+비지배지분 항등식, 자본금과 무관)을
근거처럼 붙였다 — 확인을 요청하는 문서에 무관한 산수를 싣는 것은 판단을 흐린다.

★근거가 있어도 **자동 등재하지 않는다.** 등재는 사람 확인 후 R159 예외목록에 수동으로
넣고 백필한다.

**관련**: R157(소수부 처리) · R158(행 안 복원) · R159(오타 예외목록) · R6(짐작 금지) ·
R149(셀 단위 '원')

---

## R161. **각주 문장이 표제 앞에** 붙어 재무제표 분류가 한 칸씩 밀렸다
## (2026-09-22, 캠페인 이슈#26)

**발견 경로**: 계층2 캠페인 이슈#26(peer 세션 `camp-run-e2`). 삼성화재해상보험
00139214 `20190515002191`(2019Q1) [별도] 현금흐름표 82행이 **자본변동표로 오분류**
적재 — 별도 CF 는 0행, 별도 SCE 는 398행으로 부풀었다.

**원인**: 하나의 `<P>` 가 **[직전 표의 각주] + [다음 표의 제목]** 을 함께 담는다.

```
<P> '註) 당분기 자본변동표는 … 아니하였습니다. 분 기 현 금 흐 름 표'
      └─ 직전 SCE 표의 각주 ─┘                  └─ 이 표의 진짜 제목 ─┘
```

이 `<P>` 가 CF 데이터표의 직전 형제다. 분류기가 텍스트를 읽으면 각주에 언급된 **앞
재무제표명**이 먼저 걸려 `'SCE'` 가 되고, 제목 판정이 한 재무제표씩 밀린다. 별도 섹션의
BS·IS 는 각주 문장에 다음 재무제표명도 섞여 **우연히** 맞았고, CF 만 틀렸다.

**★자간 공백은 원인이 아니다.** `'분 기 현 금 흐 름 표'` 는 공백이 그대로 있어도
`'CF'` 로 정확히 분류된다(분류기가 이미 처리한다 — 실측 확인). 이 오진을 막기 위해
회귀 테스트에 그 사실을 명시해 뒀다.

**수정**(`fin2/extract/statement_titles.py::strip_leading_note_sentences`): 표제 판정
텍스트 **맨 앞**의 각주 문장(`註)`/`주)` 로 시작해 `~니다.` 로 끝나는 문장)을 제거한다.
각주뿐인 형제는 빈 문자열이 되어 메타줄처럼 건너뛰어진다(데이터표 경계 검사가 남의
제목을 막는다).

★**맨 앞에서만** 각주를 인정한다 — `(주)삼성화재…` 처럼 **회사명의 '주)'** 를 각주로
오인하면 그 뒤 실제 텍스트를 전부 먹어버린다. 회사명은 앞에 `(` 가 붙으므로 이 패턴에
걸리지 않는다(테스트로 고정).

★**두 경로 모두 고쳐야 한다** — `title_text_for_classify` 에만 넣었더니 각주표(5행)가
`title_text_owned` 경로로 여전히 `'SCE'` 로 분류돼, '제목표/데이터표 분리' 분기가 CF
데이터를 SCE 로 끌어왔다(별도 SCE 398행에 CF 라벨 28행 잔존). R144/R153 의 교훈이
여기도 그대로 적용된다.

★**`title_text` 자체는 고치지 않는다** — `declared_unit` 이 단위줄 원문을 필요로 한다
(그 함수 docstring 이 이미 "둘의 요구가 반대"라고 적어 둔 계약). 테스트가 이것도 검사한다.

**검증**(DB 저장 기준 = `_is_loadable` 적용 후):

| scope | 수정 전 | 수정 후 |
|---|---|---|
| CF separate | **0** | **81** |
| SCE separate | 398(CF 혼입) | **104** |
| BS/IS 연결·별도, CF 연결, SCE 연결 | — | **전부 불변** |

별도 SCE 의 CF 라벨 잔존 **0행**. `pytest tests/ fin2/tests/` 전건 통과.

★**조사 중 내가 두 번 틀렸고 둘 다 기록해 둔다**:
1. "CF 표에 제목이 없다" — 틀렸다. 제목은 원문에 있었고(각주와 같은 `<P>`), 나는
   `title_text_owned` 의 반환값(기간줄)만 보고 단정했다. 실제 분류에 쓰이는
   `title_text_for_classify` 가 무엇을 읽는지 확인하지 않았다.
2. "연결 CF 가 2배로 중복됐다" — 틀렸다. DB 는 `col_index=0` 만 저장하는데
   추출기 전체 출력(166행)과 비교했다(166/2 = 83). "추출됐다 ≠ DB 에 실린다"를
   또 반복한 것이다.

**스코프**: 연결 CF 는 있는데 별도 CF 가 0행인 필링은 2015+ **10건/9개사**뿐이고, 전수
재추출 결과 **실제로 scope 가 바뀌는 건은 삼성화재 1건**뿐이었다(백필 완료). 이 메커니즘은
삼성화재 계열로 좁게 본다.

★**두산밥캣 `20170331005642` 은 결함이 아니다**(2026-09-22 조사 종결). 표 분류는 정상
(`분류='CF'`)이고, 별도 CF 가 0행인 이유는 **원문 자체가 전부 0** 이기 때문이다 —
31행 × 3기간 전부 `'0'` 이고 헤더의 기수 표기 외에 숫자가 하나도 없다:

```
TR0: ['', '제 3 기', '제 2 기', '제 1 기']
TR1: ['영업활동으로 인한 현금흐름', '0', '0', '0']
…  (31행 전부 동일)
```

`table_has_amount_rows()` 가 False 를 돌려 그룹에서 제외된 것이고, **실재하는 값을 잃은
게 아니다.** 같은 필링을 다시 조사하지 않도록 기록한다. 나머지 8건도 재추출에서 변화가
없었으므로 진짜 '별도 CF 미제출' 로 본다.

**관련**: R144/R153(두 경로 배선) · R148(표제 못 믿을 때 내용 판정) ·
`title_text_for_classify` 의 2026-08-04 데이터표 경계 수정(같은 함수의 이전 결함)

---

파서를 새로 쓸 때 **반드시** 확인할 것. 전부 실측으로 확인된 것만 적는다.

| # | 함정 | 증상 | 대응 |
|---|---|---|---|
| T1 | **`</TABLE>` 누락** → 문서 전체가 한 표 안에 중첩 | 중첩깊이로 최상위 표를 판정하면 표 **0개** | 자손 TABLE 없는 **잎(leaf)** 만 데이터 표로. 실측 KT&G `20260318001422` |
| T2 | 서술 문단을 **1x1 TABLE 로 감쌈** | 인벤토리 2배 부풀고 **뒤 표의 캡션을 잡아먹음** | 텍스트 블록으로 판정해 캡션 후보로 흡수. 실측 삼성전자 2024(85→37표) |
| T3 | 페이지 레이아웃용 바깥 TABLE 이 실제 표들을 감쌈 | `.//TR` 이 중첩 표 TR 까지 끌어와 거대 오염 grid | `table_direct_rows()` / `_direct_trs()` 사용. 실측 LG 2011(중첩 859개) |
| T4 | **XML 속성 따옴표 미이스케이프** | 조용한 데이터 손실 | `_load_root` sanitize. 실측 성일하이텍 셀 1,143→6,011 |
| T5 | 구형 보고서가 UTF-8 선언인데 실제 EUC-KR | 파싱 실패/깨짐 | 인코딩 자동감지 폴백 — **단, 아래 T5-b는 이 폴백으로 못 고침(디코딩 시점 문제가 아니라 파일에 이미 파괴돼 저장된 경우)** |
| T5-b | **OpenDART `document.xml` 아카이브 자체가 2001년 접수분을 이미 깨진 채(`U+FFFD` 리터럴) 서빙** — 재다운로드해도 MD5 동일, 로컬 사본만으론 복구 불가 | `raw_report` 2001년 접수 XML 3,625건 중 3,624건(99.97%) 손상. `fail_a`(XBRL 대조 전제)·`fail_b`(같은 손상원문 재대조라 self-consistency 무력) 둘 다 못 잡음 — 감사 사각지대 | DART 웹뷰어 내부 API(`report/viewer.do`)는 같은 내용을 깨끗하게 서빙 확인. `LegacyDartScraper`가 그 경로를 이미 스크래핑하지만 지금은 OpenDART가 `[014]` 오류를 낼 때만 발동 — "성공했지만 내용 손상"은 감지 안 됨. 상세: R76 |
| T6 | **표 전체폭 단위 선언행**(`(단위 : 백만원)` COLSPAN 복제) | 모든 열 헤더에 '단위' → **라벨열이 단위열로 오인**, segment 전부 NULL | 전폭 선언행을 열 헤더 판정에서 제외. 실측 한솔홈데코 `20260311003988` |
| T7 | **연도만 있는 헤더행**(`구분\|2025\|2024`) | 숫자로 세어져 데이터행으로 오판 → **표 전체 폐기** | 기간 헤더 셀을 수치에서 제외(`_is_period_header_cell`). 실측 보험사 표 21개·생산표 33/420(7.9%). **가드 배선 현황**(2026-08-09 재확인): production/catalog 는 있었는데 `order_backlog.py::map_order_table` 은 누락 — 싸이맥스 FY2017 롤포워드형 수주표(`구분\|2017년\|2016년`)가 이 경로로 0행 처리되고 있었다(가드 추가 완료) |
| T8 | 음수 표기 **`△`** | 셀이 통째로 버려짐 | 부호로 정규화. `▲`는 증감 의미도 있어 **건드리지 않음** |
| T9 | 괄호음수 `(703)` 의 닫는 괄호 | **단위 `')'`** 로 적재 | 부호 해석 후 제거 |
| T10 | 결측 표기 `-`, `N/A` | 라벨로 세면 값열이 차원열로 뒤집혀 **숫자가 라벨이 됨** | 빈 칸과 동일 취급. 실측 한국컴퓨터 `20260316000809` |
| T11 | 셀 안 줄바꿈 | 차원 키가 깨짐 | 공백으로 접기 |
| T12 | 자간 벌린 라벨(`가 동 율`) | 키워드 매칭 실패 → 전치형 승격 무산 | 공백 제거 후 매칭. 실측 엠플러스. `order_backlog.py`의 롤포워드형 파서(2026-08-09 신설)도 같은 함정에 걸림(00164724 "수 익 인 식 액") — 동일하게 공백 제거 후 매칭으로 수정 |
| T13 | 주석 `<P>` 헤딩 미추적 | section_path 57.5% 붕괴 | `section_detector` 수정(2026-07-27) |
| T14 | **제출사가 열 전체를 셀 하나에 몰아넣음** | 값이 이어붙어 날조된 수치(`2.025e+175`). 웹은 고정폭 줄바꿈으로 정상처럼 보이지만 **행 구조가 문서에 없다** | `is_merged_column_table()` 로 그 표는 값 생성 중단(원본 grid 는 보존). 실측 일양약품 `20260318000595`: 열별 항목 44/68/56 으로 짝이 안 맞음. **구분자 유무 전수조사 결과 98.3%가 평문 한 덩어리 = 복원 불가**(BeautifulSoup·lxml 모두 동일). **가드 배선 현황**(2026-08-09 재확인): `biz_section.map_biz_table`(production/utilization)·`biz_catalog.py`(catalog) = 원래부터 있음. `order_backlog.py::map_order_table`·`sales_section.py::map_sales_table` 은 **누락돼 있었다** — order_backlog 는 크래시로 드러남(실측 남광토건류 `00633835` FY2010, 69개 프로젝트 금액이 한 셀에 뭉쳐 `float('inf')`→`OverflowError`), sales 는 크래시 없이 조용히 날조된 값이 들어가는 미검증 구멍이었다(실측 16개사·86개 표, `docs/qa/handoff_biz_content_followup_issues_2026-08-09.md`). 두 파서 모두 가드 추가 완료 |
| T15 | 연도 접미사 표기 흔들림 `2024연도` vs `2024년도` | 기간 헤더를 데이터행으로 오판 → **표 통째 폐기** | 두음법칙 변형(`년도\|연도\|년\|연`) 모두 수용. 실측 나무에이엑스가 이것 때문에 0행이었다(수정 후 134행) |
| T16 | **ROWSPAN 이어짐 행** — 앞 행의 라벨 셀이 상속돼 그 행의 물리적 `<TD>` 개수가 줄어듦 | "물리적 위치=열 인덱스" 가정이 깨져 그 이후 값이 왼쪽으로 밀려 엉뚱한 열/라벨에 저장 | 헤더·본문을 관통하는 occupied-grid로 확장(R11, **구현·검증 완료 2026-08-08**). 실측 텔코웨어 `20240814002630`(전기말 값이 `당반기말` 라벨로 저장), POSCO홀딩스 `20171114002151`(7.35경원 오염) |
| T17 | **COLSPAN'd 라벨 행** (예: `<TD COLSPAN=2>구분</TD>`) | 라벨이 여러 칸을 차지하는데 코드는 "라벨 1개 + 나머지"로 가정 → `offset` 오판 | occupied-grid 기반 `L`(=`LV′`) 재계산(R11, **구현·검증 완료 2026-08-08**). 실측 유진증권 `20220316000791`·풍강 `20150429000186` |
| T18 | **절 경계 정규식이 한글순번(가./나.)만 인식, 아라비아숫자 순번은 못 잡음** — 정작 트리거인 "N. 수주상황" 자신부터 아라비아숫자 표기 | 다음 절이 안 잘려 창이 무관한 표(위험관리/파생상품 등)까지 쓸어담을 수 있음(단, `map_order_table`의 컬럼형태 가드가 최종 방어선이라 실질 피해는 드묾) | **수정 시도했다가 되돌림(2026-08-09)**. `_NUMBERED_HEADING_RE`에 `\d{1,2}\.` 추가해 STX엔진 `20150331003320`("5.수주상황"→"6.시장위험과 위험관리" 경계 누락) 사례는 고쳤지만, 대기업 보고서의 **수주현황 표 안 항목 라벨**("1. 한국전력기술(주)" 같은 회사명 리스트, 한글 포함이라 한글가드로도 못 거름)까지 절 경계로 오인해 진짜 데이터를 대량 삭제하는 훨씬 심한 회귀 발생(실측 KEPCO 등 6개사, 전수 스캔 1,002개사 재계산으로 확인). 원래 버그의 실측 영향(1/150표본, 최종표 무손상)보다 회귀 피해가 커 **원래 규칙(한글순번만) 유지 확정** — 아라비아숫자 확장은 향후 시도 금지 또는 훨씬 정교한 판별(표 내부/외부 구조 신호 등) 필요. 상세: `docs/qa/handoff_biz_content_followup_issues_2026-08-09.md` |
| T19 | **롤포워드형 수주현황**(행=기초/신규수주/수익인식/기말 수주잔액, 열=당기/전기) | 열-기반 판정(수주총액/기납품/수주잔고 헤더열 필요)에 안 걸려 0행 | `_map_rollforward_table()` 폴백 신설(order_backlog.py, 2026-08-09). 실측 싸이맥스 FY2017 `20180330000166`. 전수 실측(기존 캐시 grid 기준): 244개 표·24개사 회수 |
| T20 | **K-GAAP 중첩 하위표제**(`가.대차대조표` 같은 한글서수 하위표제가 `3.재무제표` 상위섹션 아래 있음) | `assign_tables_to_dart_sections`/`iter_section_elements`가 "SECTION 태그를 만나면 중첩 깊이 무관하게 즉시 재판정"하는 구조라, 최상위 매치(`3.재무제표`)가 이미 성공했음에도 하위표제를 만나는 순간 섹션 추적이 **즉시 리셋**됨 → 표 전체 미검출. 2015+엔 이런 중첩 하위표제가 없어 안 드러나던 결함 | `fin2/extract/legacy_pre2015.py::iter_section_span_depth_aware`(깊이인식 경계walk) 신규 모듈로 격리(R13). 기존 2015+ 공유 함수는 무변경. 실측 2004~2007 annual 8/8=100% 회복 |
| T21 | **비표준 금액표기 `(-)N`**(괄호+명시 마이너스 이중접두, 일부 K-GAAP filer) | `parser/xml/table_extractor.py::_NUMBER_PATTERN`(금액 후보 판정 게이트) 먼저 막힘 → `parser/common/amount_normalizer.py::parse_amount`까지 못 감. 파싱실패(None)를 컬럼압축 로직(`_emit_section_lines`)이 "앞쪽 None=과거 미보고"로 오인해 **전기값이 당기 열로 밀려 들어감**(연도무관 공용 코드라 2015+에도 잠재, K-GAAP 서식에서 더 자주 노출됐을 뿐). 결측(0행)보다 나쁨 — 틀린 숫자가 조용히 적재됨 | 두 곳 다 수정 필요(하나만 고치면 무효, 재적재로 직접 확인): `_NUMBER_PATTERN`+`parse_amount` 둘 다 `(-)N`을 음수로 인식하게 확장. 회귀테스트 9건(`fin2/tests/test_amount_normalizer_parse.py`). 잔여 유사패턴(부채총계만 항상 괄호, 결합행은 항상 정확 — KG케미칼류)은 원문만으론 진짜 부호 확정 불가 → R0 원칙상 **의도적 미수정**, 대신 `detect_bs_identity_anomalies`(이상치탐지) 안전망으로 표시만(부록B R13 이하 참고). 전량백필 실측: 큰폭(≥100만원) BS항등식 위반 346건 중 179건(51.7%)이 이 안전망(`bs_identity_confirmed`/`SIGN`/`high`)에 정상 포착됨(원문 5건 무작위대조로 확인), 63개사에서 재현(동남합성·HLB파나진·에스엠벡셀 등) — KG케미칼 한 회사 국한이 아니었음이 스케일에서 드러남. 나머지 167건은 결합행(부채와자본총계)이 없거나 그것도 안 맞아 `low`신뢰도 `OTHER`로만 표시(추측 금지) |
| T22 | **비표준 금액표기 `-N`**(괄호 없는 순수 하이픈 음수, T21과 자매결함) | `_NUMBER_PATTERN`의 6개 대안 중 어디에도 안 걸림(첫 대안 `^[\s\-─—―]$`는 "-" **한 글자만**인 셀만 잡아, "`-466,274`" 같은 다글자 셀은 통과 못 함) → `_split_label_amounts`가 이 셀을 "숫자 아닌 텍스트"로 판정해 **placeholder도 안 남기고 완전히 드롭** → 뒤 컬럼들이 배열 안에서 앞으로 밀림 → interim 2단헤더(3개월/누적) 표는 `_interim_cumulative_cols`의 헤더-위치 기반 `cum_map`이 밀린 배열의 엉뚱한 자리를 가리키게 돼 **전기/비관련 컬럼값이 당기 자리로 오emit**되거나 진짜 당기값이 통째로 유실됨. `parse_amount` 자체는 순수 `-N`을 정상적으로 음수 처리하므로(`amount_normalizer.py:344`) **게이트만의 결함** | **✅ R31로 수정 완료(2026-08-17)**. `_NUMBER_PATTERN`에 대안 1줄 추가. 실측 스코프 = pre-2010(fiscal_year≤2010) 775개사·약 13,700 filing, `report_lines` 82,402행 교정(1라운드 19,288 + 2라운드 63,114). BS항등식 위반 2라운드 합계 −49건 감소. R31 본문 참고 |

## R162. SCE 표 원문에서 음수 괄호가 빠져 자본변동표 셀이 부호 반대로 적재된다
## — **교차대조(방향) + 열 롤포워드 항등식(자격)** 으로 복원 (2026-09-22, 이슈#28)

**성격**: **파서 결함이 아니다.** DART 원문 자체가 같은 개념을 표에 따라 다르게
렌더링한다 — BS·IS 는 괄호로 음수를 표시하는데 같은 필링의 SCE 표에서는 괄호가
빠져 있다. 파서는 원문 그대로 전사했다.

**실측 원문**(효성중공업 `20190515002585`, 2019Q1):

```
BS_S  TR38: ['기타자본구성요소', '(29,461,715,719)', '(30,162,524,009)']
IS_S  TR21: ['순확정급여부채의 재측정요소', '(307,150,286)', '(307,150,286)']
SCE_S TR5 : ['순확정급여부채의 재측정요소', '', '', '307,150,286', '', '307,150,286']
```

원문 문자열 카운트로도 교차확인했다 — `'307,150,286'` 8회 중 괄호가 붙은 것은 4회
(IS 연결·별도 각 2회)뿐이고 SCE 쪽 4회는 괄호가 없다.

**참값은 추정이 아니라 항등식으로 확정된다** (열 롤포워드가 두 군데서 정확히 닫힘):

| 열 | 기초 | 변동 | 기말 |
|---|---|---|---|
| 이익잉여금 | 15,091,684,311 | 당기순이익 3,797,842,048 **−** 307,150,286 | 18,582,376,073 |
| 기타자본구성요소 | **−**30,162,524,009 | 448,570 + 700,359,720 | **−**29,461,715,719 |

이익잉여금 열은 재측정요소를 **음수로** 넣을 때만 닫힌다(양수면 4,104,992,334 로
불일치). 자본합계 기초도 기타자본을 음수로 넣어야 닫힌다:
46,622,740,000 + 908,732,724,016 + 15,091,684,311 − 30,162,524,009 = 940,284,624,318 ✓

★**열 전체가 부호반전된 것이 아니다** — 기타자본구성요소 열은 **기초·기말 잔액만**
괄호를 잃었고 변동행(448,570 / 700,359,720)은 양수가 맞다. 일괄 부호반전으로
"고치면" 멀쩡한 변동행을 망친다. 셀 단위로 항등식이 증명하는 것만 손댈 수 있다.

**계층3 영향 = 없다**(코드로 확인, 2026-09-22). SCE 는 애초에 계층3 입력이 아니다:

- `fin2/layer3/combine.py:1757` — `_FS = {"IS": "is", "BS": "bs", "CF": "cf"}`, SCE 없음.
- 같은 파일 `_map_rows()` 가 `if r["statement"] not in stmt_set` 로 걸러내고,
  호출부 기본값은 전부 `("BS","IS","CF")`(3091·3138·3159행). SCE 를 넘기는 호출부 없음.
- `fin2/audit/face_audit.py:1163`, `fin2/extract/pdf.py:717` — `if anc.statement == "SCE": continue`.
- `scripts/gateb_audit.py:316` — SQL 에 `statement <> 'SCE'` 를 박아 둠.

즉 "BS 값을 우선한다"가 아니라 **SCE 를 아예 읽지 않는다**. std_v3 오염은 없고,
손상 범위는 `report_lines` 의 SCE 행 자체에 국한된다.

**규모**(프록시 스캔: 같은 필링·같은 basis·같은 라벨이 IS/BS 엔 음수, SCE 엔 같은
절대값 양수. 2015+): **1,209필링 / 2,552셀.** 상위 라벨 = 당기순이익(손실) 410필링 ·
기타포괄손익 164 · 확정급여제도의 재측정요소 113 · 해외사업환산손익 105 ·
지분법자본변동 102 · 순확정급여부채의 재측정요소 67.

**수정**(사용자 결정 2026-09-22 — "교차대조 + 항등식"):
`fin2/extract/sce_sign_repair.py::repair_sce_sign_loss()`. **근거 두 갈래를 둘 다**
요구한다.

| 근거 | 역할 |
|---|---|
| (가) BS/IS 교차대조 | **부호 방향(앵커)** — 같은 필링·같은 basis 에 같은 개념이 어느 쪽 부호로 있는지가 orientation 을 확정한다 |
| (나) 열 롤포워드 항등식 | **적용 자격** — `기초 + Σ변동 = 기말` 이 닫히는 배정만 채택한다 |

★**어느 한쪽만으로는 안 된다.** (가) 만으로는 **잔액행에 못 닿는다** — 잔액행의
`label_raw` 는 날짜("2019.01.01 (당기초)")이고 개념은 `col_label` 에 있다. 게다가
**기초** 잔액은 BS 의 전기말과 대조해야 하는데 BS 는 `col_index=0`(당기)만 적재하므로
DB 안에 짝이 없다 — 라벨 교차대조로는 원리적으로 못 닿고 항등식으로만 증명된다.
(나) 만으로는 **방향을 못 정한다** — 어떤 배정이 항등식을 만족하면 그 전체 부호반전
(mirror)도 반드시 만족하므로(양변에 −1) 항등식 혼자서는 둘 중 하나를 고를 수 없다.

★**`col_label` 은 계층 접두어를 뗀 마지막 조각으로 맞춘다** — `'자본>기타자본구성요소'`
→ `'기타자본구성요소'` (헤더 그리드가 상위 헤더를 이어 붙인다).

**손대지 않는 경우**(R6 — 오염보다 결측): 항등식이 이미 닫힘 / 만족 배정이 여러 개 /
앵커가 하나도 없음 / 앵커와 모순 / 후보 셀이 `_MAX_AMBIGUOUS_CELLS`(14) 초과.
실측 후보 150건 중 **49건(33%)이 이렇게 기각**됐다 — 기각이 정상 동작이다.

★**열 전체를 일괄 반전하지 않는다.** 효성중공업 기타자본구성요소 열은 기초·기말
잔액만 괄호를 잃었고 변동행(448,570 / 700,359,720)은 양수가 맞다. 일괄 반전은 멀쩡한
변동행을 망친다 — 그래서 셀 단위 배정을 항등식으로 검증한다(회귀 테스트가 고정).

★**음수로 파싱된 셀은 후보가 아니다** — 원문에 괄호가 있었다는 뜻이므로 부호가 명시된
것이고 추측 대상이 아니다.

**배선**: `extract_report_lines()` **맨 마지막**에서 돈다 — 부호 방향을 BS/IS 값으로
확정하므로 inline XBRL overlay 들이 BS/IS 를 손본 뒤의 최종값을 봐야 한다. 프로덕션
경로 두 곳(`run.py::cmd_extract_lines`, `collector/note_lines_sync.py`)이 모두 이
함수를 부르므로 런북 ① 배선은 구조상 충족된다(별도 배선 불필요).

**실측 복원**(효성중공업 `20190515002585`): 별도 4셀 + 연결 3셀 = 7셀. 별도 5개 열
**전부 항등식이 닫혔다**. ★연결 3셀(`결손금 대체`·`기타포괄손익-공정가치측정지분상품
평가손익`)은 **라벨 교차대조만으로는 영원히 못 찾는 셀**이다(BS/IS 에 같은 라벨의 짝이
없고, 잔액행 앵커 + 항등식으로만 증명된다). 반대로 연결 이익잉여금 열은 항등식이 닫히지
않아(회계정책변경 효과 행 + `307,150,285` vs `286` 1원 불일치) **그대로 남겼다** — 의도된
기각이다.

**R162-b — 전기 비교 블록은 '이월잔액' 으로 잇는다**(사용자 결정, 같은 날 후속)

SCE 는 당기·전기 블록이 **세로로 쌓이는데** BS 는 당기만 적재하므로 전기 블록에는
(가) 앵커가 **원리적으로 없다**. 그래서 1차 구현은 당기 블록만 복원하고 전기 블록을
그대로 남겼다(실측 엠케이전자 `20150515000634`: 2015 블록은 복원, 2013·2014 블록은
그대로).

해법: **한 블록의 기말은 다른 블록의 기초와 같은 잔액 그 자체**다. 이미 확정된 블록의
잔액 셀에서 `{절대값: 부호}` 를 모아 미확정 블록의 잔액행 앵커로 쓴다. 진전이 없을
때까지 반복한다(당기 → 전기 → 전전기로 부호가 전파된다).

★**잔액행에만** 적용한다 — 변동행까지 절대값으로 맞추면 우연 일치로 날조된다(테스트
`test_carried_balance_only_anchors_balance_rows` 가 고정).
★같은 절대값에 부호가 **엇갈리면 그 절대값은 버린다**(판정 근거로 쓸 수 없다).
★**인접 블록이 아니라 같은 열 전체에서 찾는다** — 엠케이전자의 2015 기초는 바로 앞
블록(2014.03.31 기말)이 아니라 **2014.12.31 기말**과 이어진다(분기 표가 연차 표
뒤에 또 쌓인다). 인접성으로 좁히면 못 잇는다.

실측 효과(엠케이전자 `20150515000634`): 복원 **29셀 → 100셀**. 되돌린 셀들은
`연차배당`·`평가손실`·`자기주식취득`·`주식할인발행차금`·`부의지분법자본변동` 처럼
음수가 맞는 항목이고, `주식선택권 소멸` 은 자본잉여금 `+359,760,000` / 기타자본
`−359,760,000` 짝으로 정확히 상계된다(원문 TR16 구조와 일치).

**한계(알고 남긴다)**: 백필 후보는 프록시가 `label_raw` 로만 매칭하므로, 앵커가
`col_label` 쪽에만 있는 필링(잔액행만 깨진 경우)은 후보에 안 잡힌다. 그런 필링은
캠페인·데일리 재적재가 돌 때 자동 교정된다(수정이 `extract_report_lines` 안에 있다).

**백필 최종 결과와 잔여의 정체**(2026-09-22): 프록시 기준 2,552셀/1,209필링 →
**1,048셀/556필링**. 1차(당기) 883필링/4,977셀 + 2차(R162-b 전기) 90필링/599셀 적재.

잔여 556필링을 표본 30건으로 **기각 사유별로 분해**했다(블록 단위):

| 사유 | 블록 수 |
|---|---|
| 항등식 이미 닫힘(정상 — 프록시 오탐이거나 이미 고쳐진 열) | 986 |
| **앵커는 있는데 항등식을 못 닫음** | 419 |
| 블록(기초/기말) 미검출 | 13 |
| 후보 없음(전부 음수) | 10 |
| 앵커 없음 | **0** |

★**앵커 부족이 아니다** — 방향은 알지만 `기초 + Σ변동 = 기말` 이 안 닫힌다.

**R162-c — 소계 행 이중계상 제외**(사용자 승인 2026-09-22)

원인은 **소계 행 이중계상**이 맞았다. SCE 는 구성요소 행 뒤에 그 합('총포괄손익' 등)을
한 줄 더 찍는 서식이 흔하고, 그걸 Σ변동에 같이 넣으면 항등식이 절대 닫히지 않는다.
실측 디에이치엑스컴퍼니 `20150515000944` 연결 기타포괄손익누계액 열:

```
기초   2013.01.01 (기초자본)      127,312,821
변동   지분법기타포괄손익             21,360,989
변동   매도가능증권평가손익            -6,006,966
변동   총포괄손익                 15,354,023   ← 앞 두 행의 합(소계)
기말   2013.12.31 (기말자본)      142,666,844
→ 기초+Σ변동 = 158,020,867 / 기말 142,666,844 / 차이 15,354,023 ← 정확히 그 소계
```

★**내가 처음에 틀린 것**: "부모 행(`node_role='P'`)이 값을 갖고 자식도 값을 가지면"
이라고 적었는데 **틀렸다.** 이 표들은 **모든 행이 `depth=0`·`node_role='F'`** 다
(원문에 들여쓰기가 없다). 소계는 **부모가 아니라 형제**로 찍힌다. `node_role='P'` 로
찾는 가설을 40필링에 돌려 보니 **0건**이었다 — 효성중공업 한 열을 훑고 구조적 원인이라
단정한 것이었다. 판정은 **산술**로 해야 한다.

**판정 = 근거 두 갈래를 둘 다 요구한다**(R159 와 같은 원칙):

| 근거 | 내용 |
|---|---|
| (가) 라벨 | `_SUBTOTAL_LABEL_RE` = `소계|합계|총계|총포괄|총기타포괄`(자간 공백·접두 기호 허용) |
| (나) 산술 | 그 행의 절대값이 **앞선 연속 구간의 합**과 같다 |

★**산술만으로는 안 된다** — 실측에서 `당기순이익(손실)`(18건)·`해외사업환산손익`·
`감자차손보전` 처럼 소계가 아닌 행이 앞 구간 합과 절대값이 같아 걸렸다. 그걸 Σ에서
빼면 항등식이 **거짓으로** 닫혀 엉뚱한 부호 배정을 채택한다.
★**라벨만으로도 안 된다** — 산술이 안 맞으면 그 행은 이 구간의 소계가 아니다.
★**구성요소가 1개인 소계도 인정한다** — '총포괄손익' 아래 '당기순이익' 하나뿐인 서식이
흔하다. "2개 이상"을 요구하면 실측 커버리지가 절반으로 줄었다(20셀 → 9셀).
★**소계 자신의 부호는 구성요소의 합으로 확정한다** — Σ에서 빠져 있어 항등식이 정해
주지 않는다. 추측하지 않고 구성요소 합의 부호를 그대로 쓴다(`_subtotal_fixes`).
★소계로 판정된 행은 다음 구간의 합산 대상에서 뺀다(소계의 소계를 만들지 않는다).

**한계**: 구성요소가 부호를 잃으면 (나)가 깨져 소계 판정 자체가 실패한다 — 그런 블록은
여전히 기각된다. 즉 R162-c 가 푸는 것은 "구성요소는 멀쩡하고 잔액행이나 이중계상 때문에
닫히지 않던" 블록이다.

잔여 후보 60건 표본 실측: **6필링 / 20셀** 추가 복원. 그 밖의 잔여는 여전히 증명이
없어 R6 대로 **손대지 않는다**(부호가 틀린 채 남아 있지만 추측으로 뒤집지 않는다).


★**캠페인 세션 지침**: 같은 증상(SCE 만 부호 없음 + BS/IS 는 괄호)은 **신규 결함으로
올리지 말고** 이슈#28 참조로 묶는다. 이 필링은 파서 결함이 아니므로 pass 대상이다.

**R162-manual — (가)앵커가 원리적으로 없는 필링의 개별 확정**(camp_run 이슈#38,
사용자 결정 2026-09-23)

SK텔레콤 `20210517001554`(2021Q1) [별도] SCE `2021.03.31 (기말자본)` **자기주식**
열 — 일반 `repair_sce_sign_loss()` 는 손대지 않았다. 원인: 이 필링 BS 에 '자기주식'
단독 행이 없어(자본조정에 뭉쳐 있음) (가)BS/IS 교차대조 앵커가 **원리적으로 없다**
(R6, 정상 동작 — 오탐 아님).

그런데 이 필링은 R162-d 와 **같은 원리**(행 내부 항등식이 orientation 을 거울
모호성 없이 확정)로 독립된 두 증거가 일치한다:

```
열 롤포워드: 2021.01.01(기초) −2,123,661,000,000 + 취득 −72,982,000,000
             + 처분 +26,983,000,000 = −2,169,660,000,000
행 내부 분해: 기타불입자본합계(245,841,000,000) = 주식발행초과금(2,915,887,000,000)
             + 자기주식 + 신종자본증권(398,759,000,000) + 주식선택권(1,528,000,000)
             + 기타(−900,673,000,000)  →  자기주식 = −2,169,660,000,000
```

DB 는 원문 그대로 `+2,169,660,000,000`(괄호 누락)으로 적재돼 있었다.

★R162-d **전체 백필은 여전히 보류**다(2026-09-22 결정 유지) — 이건 그 범위를
넓히는 게 아니라, camp_run 이 실측 발견하고 사용자가 개별 승인한 **이 필링 1건만**의
확정이다. `fin2/extract/sce_sign_repair.py::_MANUAL_SIGN_FIXES` 에 등재
(`apply_manual_sign_fixes()`, R159 의 `_SOURCE_TYPO_CELL_FIXES` 와 같은 패턴 —
old_value 일치 확인 후에만 적용). 배선은 `repair_sce_sign_loss()` 바로 다음, 같은
`extract_report_lines()` 안이라 별도 call site 배선이 필요 없다.

재적재: `scripts/apply_r162_manual_issue38.py --apply`(rcept 하드코딩, 신규 승인
없이 항목 추가 금지).

**R162-e — 앵커 없는 셀을 롤포워드 '단일 셀 반전'으로 복원**(사용자 지시 2026-09-25 03시,
"R162 확장 배치로 자동 이슈 처리 진행")

**발견**: 검증 캠페인 기계 대조(mc2~, `fin2/verification/machine_compare.py`)가 자동 등록한
`sign_flip`(rule R162) 이슈는 **82,567건/16,888필링**이었다. 이 가운데 약 5.4만 건이 배당
(`배당금지급`·`연차배당`·`현금배당`…)이다. 원문이 배당을 **괄호 없이 양수**로 적는 관행이 있다
(실측 `20260313000835` 현금배당 15,182,251,900 · `20180525000233` 배당금지급 454,554,457,200).
BS/IS 에는 배당 행이 없으므로 R162 의 (가) 앵커가 **원리적으로 없고**, 그래서 R162 는 손대지
않았다(R6, 정상 동작).

**규칙**: R162/R162-b/R162-c 가 끝난 뒤에도 닫히지 않는 블록에서만 적용한다.
**양수 셀 하나의 부호만** 뒤집으면 롤포워드(`기초 + Σ변동 = 기말`, 소계는 R162-c 로 제외)가
정확히 닫히고, 그런 셀이 **정확히 하나**일 때 그 셀을 뒤집는다(`_solve_single_flip`).

- **거울 모호성은 '최소 변경'으로 끊는다.** R162 가 (나) 단독을 금지한 이유는 전체 반전(mirror)도
  항등식을 만족하기 때문이다. 그러나 전체 반전은 나머지 모든 셀의 원문 부호를 부정하는 다셀
  변경이다. R162-e 는 "원문 부호가 대부분 맞고 틀린 셀은 하나" 라는 배정만 받는다.
- 후보가 둘 이상이면 판정불가다(R6, 테스트 `test_no_anchor_two_single_flip_candidates_is_left_alone`).
- 음수로 파싱된 셀은 여전히 후보가 아니다. 앵커/이월잔액이 그 셀을 양수로 정해 두었으면 뒤집지 않는다.
- 소계 행의 부호는 R162-c 대로 구성요소 합으로 따라간다(`_subtotal_fixes`).
- 교정 내역의 `anchor_label` 은 `R162-e 롤포워드 단일셀` 이다.

**기존 테스트 변경**: `test_no_anchor_means_no_repair` 는 R162-e 로 동작이 의도적으로 바뀌어
`test_no_anchor_single_flip_repairs_under_r162e` 로 대체했다. 같은 입력(100 + 30 = 70)에서
평가손익 한 셀만 뒤집어야 닫히므로 이제 복원한다.

**배선**: `repair_sce_sign_loss()` 안(같은 함수 말미)이다. 그래서 `extract_report_lines()`
프로덕션 두 경로에 자동 반영된다(별도 call site 배선 불필요). 소급은 검증 캠페인 fix 배치
(`vq.py batch`)로 재적재하고, 재확인은 기계 대조가 한다(`vq.py machine recheck`).

**소급 결과**(fix batch #2, 2026-09-25 03:40~05:10, 커밋 `51ba241`):

| 항목 | 값 |
|---|---|
| 재적재 | 16,888필링(6샤드 병렬, 약 1시간), 실패 0 |
| 이슈 | 82,567건 → 기계 재확인 **closed 70,719(86%)** · reopened 11,848 |
| 배당 행 | closed 56,719 · reopened 6,155 |
| 잔액 행 | closed 5,519 · reopened 823 |
| 기타 | closed 8,481 · reopened 4,870 |

- reopened 중 3,627 셀은 **원문에 괄호가 명시된 음수**다. R162-e 비대상이다.
  - 예 `20150512000105`: 배당금지급 행 전체가 거울 반전돼 있다. 자본금 `(93,072,000)` 인데 실제로는 주식배당으로 증가한다.
- 나머지 reopened 는 후보가 둘 이상이거나 같은 블록에 다른 원문 이상이 섞여 단일 셀로 닫히지 않는 경우다. 수정 쪽 후속 판단 대상이다.
- 파일럿 10필링: 부호 발견 92 → 6, 8필링 clean.

## R163. CF **현금 조정 구간**에서 원문이 빠뜨린 음수 부호를 복원한다
## — R162 의 자매(자본변동표 → 현금흐름표) (2026-09-22, 캠페인 이슈#29)

**성격**: R162 와 같다 — **파서 결함이 아니고** DART 원문이 부호를 빠뜨린다.
한화오션(舊 대우조선해양) `20180330001629`(2017FY) [별도] CF 당기(제18기) 열:

```
현금및현금성자산의 증가(감소)         16,367,553,617
기초의 현금및현금성자산             144,292,901,261
외화표시 현금및현금성자산의 환율변동효과     521,074,352   ← 참값은 −521,074,352
기말의 현금및현금성자산             160,139,380,526

144,292,901,261 + 16,367,553,617 − 521,074,352 = 160,139,380,526 ✓
```

같은 필링의 비교연도 2개 열과 [연결] CF 는 부호가 정상이다 — 이 한 셀만 깨졌다.

**★부호만으로는 절대 판정할 수 없다.** `환율변동효과` 행은 **양수가 정상인 경우가 더
많다**(2015+ 실측 양수 114,412셀 / 음수 83,639셀 — 환율이 오르면 외화현금 평가이익이
나서 양수다). 그래서 이 규칙은 **항등식이 깨진 경우에만** 작동한다.

**왜 R162 의 블록 로직을 재사용하지 않는가**: SCE 는 `기초 → 변동들 → 기말` 순서지만
CF 는 **순증감 행이 기초보다 앞**에 온다(위 실측). "기초가 열고 기말이 닫는" 블록
탐색이 맞지 않는다. 그래서 `fin2/extract/cf_cash_sign_repair.py` 는 현금 조정 4행
(기초·순증감·환율효과·기말)을 **라벨로 직접 지목**한다 — 관측된 결함 계열에만 좁게
대응하고, 라벨을 못 찾으면 손대지 않는다.

**라벨 판정에서 반드시 갈라야 하는 두 행**(실측 에이루트 `20190814001339`):

| 라벨 | 정체 |
|---|---|
| `환율변동효과 **반영전** 현금및현금성자산의 순증가(감소)` | **순증감** 행(환율은 그 뒤에 더한다) |
| `현금및현금성자산에 대한 환율변동효과` | **환율효과** 행 |

둘 다 '환율변동' 을 포함하므로 `반영전` 배제 규칙이 없으면 환율효과 행 식별이 2건이
되어 아무것도 못 고친다. 반대로 `환율변동효과 **후**의 … 순증가(감소)` 는 이미 환율이
반영된 총계라 이 항등식의 항이 아니다 → 순증감 후보에서 배제한다.

**손대지 않는 경우**(R6): 4행 중 하나라도 라벨로 못 찾음(또는 후보가 2건 이상) /
항등식이 이미 닫힘 / **단일 셀 뒤집기**로 닫히는 경우가 없거나 둘 이상 / 기초·기말
현금이 음수(현금 잔액은 음수일 수 없다 = 우리가 이해 못 한 표다).

**규모**(`scripts/scan_cf_cash_sign_loss.py`, 2015+ DB 당기 열):
4행이 전부 식별된 (필링,basis,표) 106,959개 중 **단일 셀 뒤집기로 닫히는 것 61개**.
★같은 스캐너가 보고하는 "항등식 깨짐 49,173" 은 **결함 수가 아니다** — 대부분 이
4행 라벨 지목이 그 서식에 안 맞은 것이다(닫히지 않으면 손대지 않으므로 무해).
표본 8건을 눈으로 검산했고 전부 4행이 인접 `row_order` 로 정확히 잡혔다.
★필러 편중이 크다 — 유비온이 반복 등장한다(회사별 서식 습관).

**배선**: `extract_report_lines()` 맨 마지막, R162 바로 뒤. 프로덕션 두 경로가 모두
이 함수를 부르므로 런북 ① 은 구조상 충족.

**백필**(`scripts/backfill_r163_cf_cash_sign.py --apply`): 후보 61 → **CF 45셀 ·
적재 51건**(함께 SCE 44셀도 반영). 잔여 19 중 **3건만 실제로 바뀔 것**이고 그 3건은
R139 원문대조-pass 보호로 거부됐다(한화오션 `20180330001629`·`20180403001678`·
`20180523000409` — 캠페인 세션에 redo 요청). 나머지 16건은 **추출 시점 행 집합이
DB 와 달라**(DB 는 `col_index=0` 의 적재 대상 행만 갖는다) 4행 지목이 유일하지 않아
파서가 스스로 기각한 것이다 — 설계대로다.

★**내가 여기서 또 틀렸다**(같은 계열 4번째): 백필 1차 드라이런에서 "CF 음수 65→172
(+107)" 같은 수치를 보고했다. CF 는 `col_index=0` 만 DB 로 가는데(`_is_loadable`)
추출기 **전체 열** 출력과 DB 를 비교한 것이다. 바로잡은 뒤 실제 델타는 필링당 1~2셀
(총 45셀)이었다. 적재 전에 잡았다. 메모리
`feedback-do-not-attribute-backfill-recoveries-to-one-rule` 의 "추출됐다 ≠ DB 에
실린다" 항목 그대로다.

## R164. 처분계산서 가드가 **SCE 를 구조적으로 판별 못 해** 자본변동표를 통째로 버렸다

**증상.** 한화오션(舊 대우조선해양) 2017Q1 `20170515004751` 의 **[별도] 자본변동표
74행이 DB 에 0행**. 같은 필링의 **[연결] 자본변동표는 185행 정상 적재**. 원문은
쪼개지지 않은 단일 `<TABLE>` 이고 표제도 정상(`<P USERMARK="F-12 B">자본변동표</P>`)
이라 R148(표지 없는 물리분할)·R142(하위표 연속)와 **메커니즘이 다르다**.
자동검산 `ORPHAN_BODY_TABLE` 이 정확히 이 표를 지목했다(캠페인 이슈#30, camp_run 보고).

**원인.** `fin2/extract/text.py::_detect_body_statement_tables()` 의 내용기반 최종 가드

```python
if _table_has_data_rows(tbl) and _looks_like_appropriation(tbl):
    continue        # 처분계산서는 본문 재무제표가 아니다
```

`_looks_like_appropriation()` 은 **두 조건을 모두** 요구한다:

| | 조건 | 판별력 |
|---|---|---|
| ① | 처분계산서 계정이 있다 (`미처분이익잉여금`·`이익잉여금처분액`·`차기이월`…) | 모든 표에서 유효 |
| ② | `_REAL_STMT_ROW_RE`(`자산총계`·`매출액`·`영업활동현금흐름`…)가 **없다** | **BS/IS/CF 에서만 유효** |

②는 "처분계산서인가, 아니면 진짜 BS/IS/CF 인가" 를 가르는 장치다. 그런데 **SCE 에는
그 계정이 애초에 없다** — SCE 의 행 라벨은 변동사유(`당기순이익`·`배당금지급`)이고 헤더
행은 자본 구성요소 이름이다. 즉 SCE 에 대해 ②는 **구조적으로 항상 참**이고, 가드는
①만으로 발동한다. 그래서 `미처분이익잉여금`(완전히 정상적인 자본 구성요소!)을 품은
SCE 는 예외 없이 처분계산서로 오판돼 **표 전체가 버려졌다**.

**왜 연결만 살았나(비대칭의 정체).** 이 회사 별도 자본변동표에는 `미처분이익잉여금`
열이 있고 연결에는 없다. 게다가 그 블록 헤더 행의 첫 셀이 열이름 2개가 한 셀에 병합된
`'미처분이익잉여금재평가차익'` 이라 ①이 성립했다(74행 중 4개 블록 헤더 = 12·30·48·66행).
**가드가 데이터 행이 아니라 헤더 행 라벨을 읽은 것**도 함께 작용한다.

**수정(2026-09-22).** 가드를 풀지 않고 **양성 증거를 요구해 면제**한다 — 표제와 내용이
모두 SCE 를 가리킬 때만이다(R6: 짐작으로 가드를 약화시키지 않는다).

```python
sce_confirmed = stmt == "SCE" and _looks_like_equity_changes_header(tbl)
if (_table_has_data_rows(tbl) and not sce_confirmed
        and _looks_like_appropriation(tbl)):
    continue
```

`_looks_like_equity_changes_header` 는 R127/R148 이 이미 쓰는 내용 판정(SCE 자본 구성요소
열이름 ≥3개)이다. `_looks_like_appropriation` 자체는 **건드리지 않았다** — BS/IS/CF 에서
그 술어가 틀렸다는 증거가 없다. 런북 요구대로 같은 가드의 **두 번째 call site**(표제표/
데이터표 분리 서식의 forward scan)에도 대칭으로 배선했다.

★**정직하게 적어둔다 — 두 번째 call site 는 단독 증명을 못 했다.** 변이 검사에서 그쪽만
되돌려도 테스트가 통과한다. 그 서식에서는 데이터표가 자기 인덱스에서도
`title_text_for_classify` 로 SCE 로 분류돼 첫 번째 call site 가 같은 표를 잡기 때문이다.
"한쪽만이 결과를 가르는 서식" 은 만들어내지 못했다(R158 때 한 경로만 고쳐 샌 전례가
있어 대칭 배선은 유지).

**규모(전수 스캔).** `scripts/scan_r164_sce_appropriation_guard.py` 가 필링마다 실제
탐지기를 다시 돌려, **이 가드가 운명을 결정하는 SCE 표**를 `recovered`(수정 후 탐지기가
살린다) / `dropped`(여전히 버린다) 로 나눠 센다.

```
★수정이 살린 것              127 필링 / 131 표 / 원문 4,279 행  → 백필 완료(12,192 DB행)
   22개사(코미팜 21 · KD 14 · 롯데케미칼 14 · 우양에이치씨 13 · 한화솔루션 11 …)

★★여전히 버려지던 것       119 필링 / 145 표 / 원문 5,037 행  → **R164-b 로 해소(아래)**
   연결 101 표 · 별도 44 표
```

**즉 잔여가 수정분보다 크다.** 원인은 R164 면제가 요구하는 양성 증거
`_looks_like_equity_changes_header` 가 **첫 두 행만** 본다는 점이다(구현:
`rows[0] + rows[1]`). 이 서식들은 0행이 `['', '자본']` 같은 COLSPAN 배너이고 자본
구성요소 열이름이 **1~2행에 걸쳐** 있어 창(window)을 벗어난다. 실측 3건:

| 필링 | basis | 0행 | 열이름이 있는 행 | 판정 |
|---|---|---|---|---|
| 삼진엘앤디 `20260513000016` | 연결 | `['', '자본']` | 2행(자본금·연결자본잉여금·연결기타포괄손익누계액·연결이익잉여금) | False |
| 삼화전자공업 `20160330003638` | 연결 | `['', '자본']` | 2행(자본금·주식발행초과금·기타포괄손익누계액·이익잉여금) | False |
| KD `20150515001189` | 별도 | `['', '자본']` | 1행이지만 목록 토큰이 **2개뿐**(자본금·미처분이익잉여금) | False |

앞의 두 건은 창을 3행으로 넓히면 해소되지만 **세 번째는 아니다** — `_SCE_COLUMN_LABELS_RE`
에 `기타불입자본`·`기타자본구성요소` 가 없어 임계값(3) 미달이다.

### R164-b — 그 잔여를 없앤 후속 수정(2026-09-22, 사용자 승인)

잔여의 원인은 면제가 요구하는 양성 증거 `_looks_like_equity_changes_header` 가
**첫 두 행만** 보던 것(`rows[0] + rows[1]`)이다. 두 가지를 넓혔다:

1. **창을 세 행으로.** 이 서식들은 0행이 COLSPAN 배너(`['', '자본']`), 1행이 그룹 계층
   ('지배기업의 소유주에게 귀속되는 지분 / 비지배지분 / 자본 합계'), **2행**에 자본
   구성요소 열이름이 온다. 배너+그룹계층+구성요소가 관측된 최대 깊이다.
2. **토큰 2개 추가** — `기타불입자본`·`기타자본구성요소`. KD `20150515001189` 별도 SCE 의
   열이름은 '자본금·기타불입자본·기타자본구성요소·미처분이익잉여금(미처리결손금)·자본 합계'
   인데 옛 목록으로는 `자본금` 과 (미처분)`이익잉여금` **2개만** 걸려 임계값(3) 미달이었다.
   둘 다 자본변동표에만 쓰이는 명칭이라 BS/IS/CF 헤더에는 나타나지 않는다.

**★이 술어는 R127·R127b·R148 이 공유**하므로(캡션이 SCE 데이터에 잘못 붙은 것 가려내기,
표지 없는 SCE 분할표 이어붙이기) 느슨해지면 R127 이 막던 오염이 되살아날 수 있다. 그래서
**2015+ 전수 104,533필링**에 대해 수정 전/후 **표 귀속 diff** 를 돌려 판정했다
(`scripts/measure_r164b_predicate_widening.py`).

```
측정 104,533   변화 없음 104,380   변화 152   원문손상 1(기존 triage 건)

  ★얻은 것   SCE_C 100필링 · SCE_S 42필링          원문 4,842행
             + 기존 코드에 SCE_S 표가 하나 더 붙음 34필링   원문   518행
                                                    합계 5,360행
  ★★잃은 것  statement 코드 소멸      0
             기존 코드에서 표 제거     0
             표가 다른 statement 로 재배정  0
```

즉 **전수에서 손실이 한 건도 없고 전부 가산**이다. 34필링(BNK금융지주 33·삼성카드 1)은
코드 단위로는 차이가 안 보이는 건인데, 표 단위로 diff 해 보니 **SCE_S 표가 하나씩 더
붙은 것**(R148 계열이 더 넓게 발동)이고 제거는 0이었다. 백필 대상 152필링은 전부
`pending` 이라 R139 override 불요.

**수정 후 잔여 — 2필링/3표/원문 195행에서 종결(더 넓히지 않음).**
`scripts/scan_r164_sce_appropriation_guard.py` 를 수정 후 다시 돌리면
`dropped` 가 **119필링/145표 → 2필링/3표**로 줄었다(코스리거글로벌
`20150513003244`·`20150813000705`). 그 표의 열이름은
'보통주납입자본 · 주식발행초과금 · 기타자본항목 · 이익잉여금 · 자본 합계' 인데
목록에 걸리는 것이 `주식발행초과금`·`이익잉여금` **2개**뿐이라 임계값(3) 미달이다.
`보통주납입자본`·`기타자본항목` 을 더 넣으면 해소되지만 **넣지 않았다**:

- 이 술어는 R127·R127b·R148 이 공유하고, 토큰을 늘리는 것은 그 셋의 발동 범위를 같이
  넓히는 일이다. 느슨해지면 R127 이 막던 오염(SCE 데이터가 CF 로 적재)이 되살아난다.
- 검증 비용도 매번 전수 재측정(약 3시간)이다.
- **2필링 195행을 얻기 위해 공유 가드를 또 느슨하게 할 이유가 없다** — 오염보다 결측(R6).

재검토한다면 그 두 토큰이 후보다. 그때도 전수 diff(`lost=0`) 확인이 조건이다.

★**측정 도구를 두 번 틀렸다**(도구 docstring 에 상세):
① 표를 `id(tbl)` 로 키잉해 "재배정 25건" 이라는 허깨비를 봤다 —
`_split_headed_multi_statement_table` 이 표를 deepcopy 하므로 매 실행 주소가 다르다.
내용 해시로 바꾸니 0건. ② 32워커 `multiprocessing.Pool` 이 **워커 전멸 후 4시간 무한대기**
했다(부모 CPU 1.19초). `Pool` 은 워커가 죽어도 예외를 안 낸다. 이 프로젝트엔 이미
"8워커 메모리부족" 기록이 있었는데 32를 쓴 것이 잘못이다. 지금 도구는
`ProcessPoolExecutor`(죽으면 즉시 예외)+JSONL 체크포인트(재개)+속도/ETA/`lost` 주기 출력이다.

★**두 장치 분할**: `find`/`grep` 전수는 SD카드가 압도적이지만, **경로를 아는 파일의 전수
재파싱**은 SD 5.33 files/s · NAS 5.66 files/s 로 거의 동등하다(같은 목록·각 사본 콜드로
측정). `_parse_xml_file` 이 이미 통짜 read 를 하고 시간 대부분을 `sanitize_dart_xml`+lxml
에 쓰기 때문이다. `--storage both` 로 나누면 벽시계가 줄지만, 지속 부하에서 죽은 이력이
있어 기본값은 SD 단독으로 두었다.

★**첫 스캐너가 틀린 것도 남긴다**: 처음엔 "지문"(두 술어가 모두 참)을 셌다. 지문은
수정 전후로 변하지 않으므로(수정은 결과를 바꾸고 술어는 그대로다) 백필 후 다시 돌렸을
때도 같은 숫자가 나왔고, 한동안 "아직 60건 남았다" 로 읽었다. 스캐너를 **결과 측정**
(탐지기가 그 코드를 반환하는가)으로 고쳐서야 recovered/dropped 가 갈렸다.
교훈: 진행률 지표는 **결과**를 재야 한다 — 원인 지문을 세면 고쳐도 줄지 않는다.

pre-2015 는 `_detect_pre2015_body_statement_tables_merged` 를 타고 이 가드를 **거치지 않으므로** 영향 없다(호출부 2곳 모두 2015+ 경로 안에 있다).

**검증.** 한화오션 `20170515004751` 별도 SCE 102행 복구, 기말 자본합계
**453,861,699,196** 이 ①camp_run 의 DART 원문 판독값 ②같은 필링 **별도 BS 자본총계**
(SCE 자신이 아닌 독립 앵커) 와 일치하고, ③열 구성요소 합이 정확히 총계와 맞는다
(332,884,800,000 − 16,797,720,223 − 726,096,000 + 1,000,000,000,000 + 11,613,759,725
+ 416,743,353,153 − 1,289,856,397,459 = 453,861,699,196).
회귀 테스트 `fin2/tests/test_r164_sce_appropriation_guard.py` 8건(변이 검사로 비침묵
확인 — 첫 번째 call site 를 되돌리면 3건 실패). `pytest tests/ fin2/tests/` 1,278 passed.

**관련 발견(R164 와 무관, 착수 안 함).** 위 분리 서식 실험에서 **같은 물리 표가 두 번
append** 되는 것을 확인했다(forward scan 과 정상 분기가 겹침). 라벨을 무해한 것으로
바꿔도 재현되므로 R164 가 만든 것이 아니라 **기존 성질**이다. 적재 데이터에서 같은
(rcept, basis, statement) 안에 서명이 동일한 table_seq 쌍은 2015+ 에서 **5필링 17쌍**
뿐이고 BS/IS/CF 에도 나타난다 — 원문이 같은 표를 두 번 싣는 경우(정상 전사)일 수
있어 단정하지 않는다. 사용자 판단 대기(부록 C).

## R165. SCE 기말잔액 행의 한 셀만 원문에서 값이 틀려 있다(행 항등식+BS 이중앵커로 확정)

**발견.** 캠페인 이슈#31(camp_run) — 한화오션 2015FY 기재정정 `20170511004419` ·
`20171019000325` 의 별도 SCE '2015.12.31 기말자본' 행에서 **이익잉여금 셀만** 정정 이전
값(`-1,563,903,332,495`)이고 같은 행의 나머지 전부와 자본합계(`415,242,474,443`)는
정정 후 값이다. R162/R163(음수 괄호 누락)과 달리 **절대값 자체가 틀린** 계열이라 부호
규칙으로는 못 찾는다.

★**camp_run 의 최초 판단은 틀렸고 내가 정정했다**: "1차본은 DB 가 우연히 맞다" 고
보고됐지만 실측하면 **두 자매 필링의 DB 값이 완전히 동일**하다(둘 다 스테일). BS 쪽 값을
보고 SCE 가 맞다고 오판한 것이다. 그래서 1차본의 `pass` 도 `fail` 로 재판정됐다.

**판정 = 이중 앵커.** SCE 기말잔액 행에서

1. **행 항등식** — 구성요소 열 합 = 자본 합계 열.
2. **BS 앵커** — 각 구성요소는 **같은 필링 재무상태표**의 같은 개념 행과 일치해야 한다
   (SCE **밖**의 독립 앵커).

셋을 모두 만족할 때만 후보로 센다: ①항등식이 깨졌고 ②BS 와 어긋나는 구성요소가 **정확히
하나**이고 ③그 BS 값을 넣으면 항등식이 **정확히** 닫힌다. 그러면 참값이 두 번 고정되고
결함이 한 셀로 특정된다. 그 외는 별 버킷으로 보고하고 손대지 않는다.

한화오션 검산: `1,372,076,840,000 - 14,677,080,363 + 14,967,109,054 + 424,385,260,709
= 1,796,752,129,400`; `415,242,474,443 - 1,796,752,129,400 = -1,381,509,654,957`
= 별도 BS 이익잉여금. 오차 `182,393,677,538`.

**★규모 — 한 숫자로 보고하면 틀린다.** 이 검사에 **서로 다른 네 계열**이 걸린다
(`scripts/scan_r165_stale_sce_cell.py` 가 분류해 센다). 처음 돌렸을 때 1,943건이 나와
"이슈#31 계열 1,943건" 이라 보고할 뻔했다.

```
기말잔액 행(단일 총계 + 구성요소 2개 이상)      104,690
  행 항등식 성립                                 95,331
  ★깨짐 + BS 불일치 1개로 정확히 닫힘             1,943
      sign   1,332셀 / 1,323필링   R162·R163(부호만 반대, 절대값 동일)
      scale      9셀              R157~R159(정확히 10^n 배)
      trunc      7셀              R157(배수 전 절삭)
      other    595셀 /   594필링  ★R165 후보
  깨짐 + 여러 셀이 BS 와 불일치                      555
  깨짐 + BS 로 설명 안 됨                          6,861
```

`other` 595셀도 그대로 R165 가 아니다 — 오차 크기로 다시 갈린다:

```
|적재값 - BS| 분포(595셀)
  = 1원 39 · ≤10 26 · ≤100 15 · ≤1,000 41     → 121셀(20%)은 원문 반올림, 결함 아님
  ≤1M 112 · ≤1B 216 · ≤1T 144 · >1T 2         → ★>1B 146셀이 실질적 오류
```

**★파서 결함이 아니다(중요).** 표본 120건을 원문으로 triage 한 결과 **"원문에 참값만 있고
우리가 딴 값을 넣은" 경우 0건**이다. 그리고 최대 오차 5건은 SCE 셀 원문을 직접 읽어
확인했다 — 전부 **원문 셀 자체가 틀렸고 우리는 충실히 전사**했다:

| 필링 | 회사 | 원문 SCE 셀 | BS(참값) | 정체 |
|---|---|---|---|---|
| `20160816000038` | 대상 | `735,467,953,000` | `73,467,953,000` | 같은 열이 다른 모든 기간 행에서는 `73,467,953,000` — **마지막 행만 숫자 하나 끼어듦** |
| `20150515002082` | 유비쿼스홀딩스 | `1,744,044,351,834` | `174,044,351,834` | 앞에 `1` 하나 더 |
| `20171114000448` | 백산 | `297,141,751,479` | `29,714,175,149` | 자릿수 밀림 |
| `20230811001638` | 한국앤컴퍼니 | `1,697,838,418` | `1,697,838,414,885` | 원문에서 잘림 |
| `20260813001675` | 고려아연 | `7,090,846,932,215` | `7,287,193,766,723` | 스테일 |

대상(20160816000038)이 특히 결정적이다 — **같은 열의 다른 기간 행들이 전부 정상값**이라
원문 자체의 오타임이 그 표 안에서 자기증명된다.

**상태: 미조치(사용자 판단 대기).** 셀 하나를 고치는 데 `manual_report_lines` 를 쓰면
**스코프가 통째로 삭제**되므로(R159 실측) R159 식 예외목록 설계가 필요하다. 규모 파악까지가
사용자 지시(2026-09-22)였고 여기까지가 그 결과다. 참값은 이중앵커로 확정돼 있으므로
복원 자체는 가능하다.

**부수 수확 — `sign` 1,332셀은 R162 잔여에 대한 더 강한 증거다.** R162 는 열 롤포워드
항등식 + BS/IS 교차대조를 쓰는데, 여기 걸린 1,332셀은 **BS 라는 SCE 외부 앵커**가 직접
붙어 있다. R162-d(아래) 후보와 겹치지만 앵커가 더 강하다 — 백필 결정 시 이 집합을 우선
후보로 볼 것.

## R166. 라벨 칸이 ROWSPAN 으로 이어지는 **두 번째 물리행**이 유실·오라벨된다

**발견.** 캠페인 이슈#34(SK이노베이션 2023FY `20240320000950`)·이슈#35(한미반도체
2023H1 `20230814001921`) — camp_run. 스크린샷 + computed style 로 **화면과 XML 이
일치**함을 확인했다(라벨 셀만 2행 높이) — 렌더 괴리가 아니라 원문 레이아웃이다.

**원인.** DART 는 라벨이 길면 라벨 `<TE>` 에 `ROWSPAN=2` 를 주고 값을 **둘째 물리행**에
싣는다. 그 행에는 자기 라벨 칸이 없어 `_grid_body_rows` 의 `physical[0]` 이 **첫 금액
칸**이 된다. 그 다음이 갈린다 — **증상이 두 가지**다:

| 첫 금액 칸 | 종전 결과 |
|---|---|
| 비어 있음 (`''`) | `if not label: continue` → **행 전체가 값째로 유실** (이슈#34) |
| `'0'` | 라벨이 비지 않으므로 통과 → **라벨이 `'0'` 인 행으로 오적재**, 게다가 `physical[1:]` 규약 때문에 그 `0` 칸 값은 버려짐 (이슈#35) |

★이슈#35 는 **결측이 아니라 오라벨**이었다. camp_run 이 `자기주식처분이익` 으로 찾아서
결측으로 보였을 뿐, 값 3개는 라벨 `'0'` 로 적재돼 있었다. 실측 확인:
`label='0' col=1 자본잉여금 / col=5 지배기업지분 합계 / col=6 자본 합계`.

**수정 — 상속 라벨을 붙여 별도 행으로 낸다(병합하지 않는다).**
상속 칸은 origin 텍스트를 이미 들고 있으므로 라벨은 복원된다. 이어짐 행은 자기 값만
가진 **독립 행**으로 나가고, 직전 행은 **건드리지 않는다**(순수 가산, 덮어쓰기 없음).

★**처음엔 "한 논리행이 쪼개진 것" 으로 보고 직전 행의 빈 열(뒤엔 0 인 열까지)을 채우게
했다가, 그 전제가 틀린 실측을 만나 설계를 바꿨다** — SK이노베이션 `20260316000827`
[별도] SCE:

```
라벨행    기타자본구성요소 16,264,649 · 자본합계 16,264,649                  ← 자기완결
이어짐행  이익잉여금 17,201,204 · 기타자본구성요소 (17,201,204) · 자본합계 0   ← 자기완결
```

같은 캡션 아래 **서로 다른 두 변동**(평가손익 증가 / 이익잉여금↔기타자본 재분류)이고
**각각 항등식이 닫힌다**. 병합하면 둘이 섞여 `17,201,204 + 16,264,649 = 33,465,853`
인데 합계는 `0` 인 **날조된 행**이 나왔다. 원문이 두 행으로 인쇄한 것은 두 행으로
전사한다 — 그것이 유일하게 안전한 처리다.

**★병합안이 데이터를 더 나쁘게 만들었다는 것도 남긴다**: 병합 버전은 이슈#35 의 행을
직전 행에 흡수시켜 **아예 사라지게** 했고(라벨 `'0'` 로라도 남아 있던 값이 없어졌다),
그 뒤 "0 인 열은 대체" 규칙(옛 R166-b)으로 되살리는 모양이 됐다. 지금 설계에는 그
규칙이 필요 없다 — 덮어쓰기 자체가 없다.

**규모(2015+ 전수 104,533필링, 개정 설계 기준 재측정 완료 2026-09-23,
`scripts/measure_r166_rowspan_continuation.py`).** 측정은 **DB 대조가 아니라 원문
XML 구조를 직접 센다**(현재 코드가 이미 반영된 필링도 "해당 패턴 있음"으로 잡힌다 —
정상. 백필 여부와 무관하게 트리거 존재 자체를 잰다):

```
측정 104,533 · 오류/판독불가 1 · 영향 필링 55 · 트리거 행 188
  ★결측(첫 금액 칸이 비어 통째로 버려졌던 행, 이슈#34 계열): 67행 → 183셀
  ★오라벨(라벨 '0' 으로 적재돼 그 칸 값이 버려졌던 행, 이슈#35 계열): 121행 → 121셀
  SCE_C 40필링 · SCE_S 15필링 · BS_C 1 · BS_S 1     ← 주석 표는 영향 없음
```

★`_grid_body_rows` 는 SCE 와 주석뿐 아니라 **BS 에서도** 이 패턴을 만난다(2필링) —
헤더가 긴 BS 라벨이 ROWSPAN 으로 접힌 드문 서식. 코드 수정은 SCE 전용이 아니라
`_grid_body_rows` 공유 함수 자체라 자동으로 같이 잡혔다.

**백필(`scripts/backfill_r166_affected.py --apply`, 2026-09-23).** 55필링 전부
성공(보호/실패 0). 라벨 `'0'` 로 남아 있던 행이 전부 정상 라벨로 교정됐다(휴맥스홀딩스
18→0, 사조씨푸드 30→0, 유성기업 21→0×2, BNK금융지주·자화전자(4건)·동국산업 각 14→0).
결측 행은 대부분 행수 증가로 나타났다(예: KG파이낸셜 3필링 346→351, 데브시스터즈
3필링 각 +6). 이미 개별 승인으로 먼저 고쳤던 3건(SK이노베이션 `20240320000950`·
`20260316000827`, 한미반도체 `20230814001921`)도 목록에 포함돼 재적재됐지만 변화
없음(멱등 확인 — 이미 정확했다는 뜻).

**검증.** 이슈#34 필링 [연결] SCE 셀 **211 → 221**(+10, camp_run 이 원문에서 센 10개와
일치). 이슈#35 필링은 라벨이 `'0'` → `자기주식처분이익` 으로 교정되고 값 3개 유지.
`20260316000827` [별도] SCE 는 모든 행이 **각자 항등식을 닫는다**(병합안에서 깨졌던 것).
회귀 테스트 9건, 변이 검사로 비침묵 확인(R166 이전 코드로 되돌리면 4건 실패).
`pytest fin2/tests/` — 1,126 passed(2026-09-23 재확인, R159/R162-manual 추가분 포함).

## R167. 검증 ↔ 재적재 규칙 — 적재 스탬프·lease·내용버전 (2026-09-24, R139 대체)

**배경**: 몇 달짜리 원문대조 캠페인의 상태를 DB(`verification` 스키마)에 두면서, 검증 중이거나
이미 검증된 데이터와 재적재가 섞이는 문제를 **규약이 아니라 DB 가 강제하도록** 정했다.
실제 사고 두 건이 계기다: 검증 세션이 구코드로 재적재해 백필을 되돌린 일(R164 백필 SCE
12,192행), 그리고 보지 않은 필링에 pass 가 찍힌 일. 설계:
`docs/plans/verification_schema_two_worktree_design_2026-09-24.md` §4.

**규칙**
1. **적재 스탬프는 트리거가 찍는다.** `report_lines` 의 INSERT/UPDATE/DELETE 는 커밋 시점에
   필링별 **내용 해시**(BS/IS/CF/SCE, scope 별)로 요약된다. 내용이 바뀌었을 때만
   `verification.filing_loads.load_seq` 가 +1 된다. 이력은 `filing_load_events` 에 남는다
   (바뀐 scope, git commit, 워크트리, reason). 호출부 배선이 필요 없다 — 데일리·백필·임시
   스크립트 모두 같은 경로로 기록된다. `collector/db.py` 는 연결마다 `verification.actor`
   (워크트리)와 `verification.parser_commit`(HEAD, 미커밋 변경이 있으면 `-dirty`)을 세션에 싣는다.
   해시에서 빼는 것: `id`, `source_ref`, `context_raw`(출처 표기일 뿐 검증 대상 값이 아니다).
2. **같은 결과로 다시 파싱하면 아무 일도 없다.** 해시가 같으면 판정은 그대로 유지된다.
3. **검증 중(lease) 필링은 수정 계정이 바꿀 수 없다.** 트리거가 커밋을 거부한다(SQLSTATE `55P03`).
   `vq.py batch reload` 는 그 건을 `deferred` 로 두고 다음에 다시 시도한다. 관리자 계정(데일리
   파이프라인)은 막지 않는다 — 대신 규칙 4 가 판정을 무효화한다.
4. **판정은 적재 버전에 묶인다.** `pass`/`issue add` 는 점유 시점의 `load_seq` 와 현재 값이
   다르면 거부된다. passed 필링의 내용이 바뀌면 그 필링은 pending 으로 돌아가고, 슬롯은 다시
   큐에 들어간다. `vq.py show` 는 판정 당시 해시와 비교해 **바뀐 scope 만** 알려준다.
5. **`fixed` 는 데이터가 바뀐 재적재를 요구한다**(이슈 트리거). 커밋만으로는 fixed 가 되지 않는다.
6. `unit_source='manual'` 보호(2026-09-08)는 그대로 유지된다(별개 규칙).

**범위 밖**: `note_lines`·`report_tables` 는 스탬프하지 않는다. 캠페인이 대조하는 것은 본문 재무제표이고,
`note_lines`(2억 행)에 트리거를 거는 비용을 피하기 위해서다.

**근거 코드**: `fin2/verification/schema.sql`(trg_finalize_load, trg_issue_before),
`fin2/extract/report_lines.py::store_report_lines`(R139 제거), `collector/db.py`
(`_set_verification_identity`). 테스트: `fin2/tests/test_verification_schema.py`,
`fin2/tests/test_verification_ops.py`. 실측: pending 필링 1건 연속 2회 재적재 → load_seq 1 유지
(해시 안정), 해시 계산 ~40ms/필링(SCE 900행 규모).

---

## R168. 구형 2단 열(내역칸/잔액칸) 서식의 **그룹 마감행**을 산수로 자기증명될 때만 적재한다 (2026-09-24, R155 뒤집음)

**발견 경로**: verification 캠페인 fix_batch(`missing_row`) — 이슈 #59~#102(크래프톤
2017H1~2018Q3 별도 BS 44건). R155 가 "전수 스캔 2,528개사 중 1건"으로 닫았던 결함인데,
R155 스캔은 **회사별 가장 오래된 1건**만 봤다(R155 에 적어 둔 한계 그대로). 크래프톤은
중간 연도(2017~2018) 필링에만 이 서식을 써서 빠졌다. 회사×필링으로 다시 세니
크래프톤 **16필링 94행**(최초본+정정본 쌍 포함).

**구조**(R155 와 동일): 한 기간을 [내역칸, 잔액칸] 2열로 찍고, 그룹 마감행만 양쪽을 채운다.

```
단기대여금        5,917,135,510
대손충당금          402,125,052   5,515,010,458   ← 양쪽 → R6 판정불가로 유실
기계장치          6,264,756,463
감가상각누계액    3,327,312,560
국고보조금            3,338,881   2,934,105,022   ← 차감 사슬(티로보틱스)
```

**규칙**: 서브타입 없는 **2열** 병합군에서 두 칸이 모두 실값이면, 직전 잔액행 이후
**내역칸만 찬 행들의 값**(run)과 이 행의 왼쪽 값으로 오른쪽 값이 **정확히** 재현될
때만 왼쪽(그 행 자신의 금액)을 채택한다.

- 차감 사슬: `run[0] − |run[1]| − … − |left| == right` (괄호 없이 찍힌 차감 계정)
- 부호 합: `run[0] + run[1] + … + left == right` (괄호로 찍힌 차감 계정, 가산 그룹)

오차 허용 없음. 증명이 안 되면 **기존대로 건너뛴다(R6 유지)**. 그래서 R155 가 걱정한
"R6 을 풀면 보험·증권사 명세/소계 서식(R125) 전체가 위험"은 해당하지 않는다 — 그 서식에서
이 등식이 우연히 맞으려면 그룹 전체가 인쇄된 잔액과 원 단위까지 일치해야 한다.

- run 은 **표마다·rank 마다** 따로 센다. 잔액칸이 찬 행이나 두 칸 다 빈 행에서 끊는다.
- `closing_runs` 인자를 넘기지 않는 호출자(`html_viewer` 등)는 동작이 바뀌지 않는다.
- 부호는 원문 그대로다(왼쪽 칸이 괄호 없이 양수면 양수로 적재 — 다른 BS 행과 같은 원칙).

**안 되는 것(정직하게)**: 원문 자신의 산수가 1원 어긋나면 복원하지 않는다. 실측:
티로보틱스 `20180402000209` `제품평가충당금` — 553,874,570 − 46,333,209 = 507,541,361
인데 원문 잔액칸은 507,541,362. 14행 중 이 1행은 여전히 유실(R6).

**근거 코드**: `parser/xml/table_extractor.py::select_by_header_columns`(`closing_runs`),
`_dual_closing_row_proved`, `update_dual_closing_runs` ·
`fin2/extract/report_lines.py`(표 단위 `dual_closing_runs`).
**테스트**: `fin2/tests/test_r168_dual_column_closing_row.py`.
**스캔**: `scripts/scan_dual_column_periods.py --all-years --workers N`(결과의 `recovered`
= R168 이 새로 적재하는 값).

**전수 측정(2026-09-25, 2015+ 캠페인 범위)**: `scan_dual_column_periods.py --workers 4`,
`layer2_review_queue` fiscal_year≥2015 중 XML 원문이 있는 **104,533필링 전부**(회사×필링).

| 지표 | 값 |
|---|---|
| R6 판정불가로 유실된 행이 있는 필링 | 51 |
| 그중 유실 행 | 1,255 |
| R168 이 복원하는 행 | 129(중복표 제거 후 고유값 107) · **23필링 7개사** |
| 오류 | 1(솔트웨어 20220802000208 — `_CONFIRMED_NON_XML_RCEPTS` 기존 손상 건) |

복원 23필링: 크래프톤 16 · 티로보틱스 1 · 특수건설 1 · 토박스코리아 1 · 와이즈버즈 2 ·
태성 1 · 넥사다이내믹스 1. 복원 라벨은 전부 차감 계정(대손충당금·감가상각누계액·
손상차손누계액·평가충당금·전환권조정·국고보조금·퇴직연금운영자산).

**복원 안 되는 나머지 1,126행은 R168 대상이 아니다** — 대부분 `sep/IS`·`con/CF`·`con/IS` 의
이자수익·영업수익·수수료 등 금융사(삼성생명·삼성카드·제주은행·메이슨캐피탈 등) 명세/소계
서식이고, 산수 증명이 안 되므로 R6 그대로 건너뛴다(의도대로). 이 행들이 진짜 결측인지는
별도 조사 대상이다(R168 로 판단하지 않는다).

2015 이전 필링은 스캔·백필하지 않았다(캠페인 범위 밖). 재적재되는 시점에 R168 이 적용된다.

**관련**: R155(이 규칙이 뒤집음) · R6 · R125 · R131 · R154(자기증명 패턴의 선례)

---

## R169. 자기모순 단위선언(선언 백만원·천원, 실제 원)을 **타 필링 동일값 대조**로 섹션별 확정해 교정한다 (2026-09-25, R132 일반화)

**발견**: verification 캠페인 missing_row 이슈 318건(fix batch #3). 휴젤 2022FY `20230322000822`
147건, 알테오젠 2022FY `20230320000985` 96건, LIG디펜스앤에어로스페이스 2018FY `20190401002321`
74건, 한국타이어앤테크놀로지 2022FY `20230324001066` 1건. 네 필링 모두 재무제표가 "(단위 : 백만원)"
(한국타이어 IS 는 천원)을 선언했지만 셀은 이미 원 단위다. 예: 휴젤 연결 유동자산 `617,863,083,758`,
같은 문서 다른 표에는 같은 숫자가 "(단위 : 원)"으로 다시 나온다.

**증상(R132 와 같은 메커니즘)**: 선언 배수 ×10⁶ 적용 후 `_AMOUNT_SANE_MAX`(1경원)를 넘는 총계·
소계는 거부돼 **행이 통째로 결측**되고, 문턱 아래 세부 행은 **×10⁶ 부풀린 값으로 적재**된다.
휴젤 연결 BS 는 115행 중 12행만 남았고 그 12행도 값이 틀렸다. R132 는 이것을 수기 예외목록
(rcept 6건)으로만 고쳤다. 게다가 **SCE 방출기(`_emit_sce_lines`)에는 override 가 닿지 않아**
R132 6건의 자본변동표도 ×10⁶ 값으로 남아 있었다.

**규모(2015+ 전수, `abs(value_won) ≥ 1e15` 인 declared 행을 가진 필링)**: 111필링 / 637섹션.
1,000조원 이상 계정은 상장사에 존재하지 않는다(실측 최대 총계 약 5×10¹⁴). 증권사 CF 의 총액
매매흐름만 예외이고, 아래 판정이 그것을 걸러낸다.

**왜 문서 안에서 판정하지 않나**: 선언 백만원이 불가능하다는 것까지는 문서가 증명한다(1경 초과).
그러나 원인지 천원인지는 문서만으로 가를 수 없다(R6). 같은 숫자가 "(단위 : 원)" 표에 다시 나오는
문서 내 증거는 111필링 중 약 절반에만 있었다(실측).

**판정(섹션 = rcept × BS/IS/CF/SCE × 연결/별도 단위)** — `fin2/audit/unit_self_contradiction.py`:
1. 의심 섹션: 선언 단위 행에 `|value_won| ≥ 1e15` 가 있거나, 선언 단위에서 섹션이 통째로 사라짐.
   단 그 섹션의 선언 배수가 전부 1(원)이면 제외한다. 큰 값이 배수 탓이 아니기 때문이다(실측: R152 계열
   대손준비금 칸에 금액 두 개가 붙은 금융사 6필링). 증거가 선언 배수와 같은 k 를 가리키면
   `declared_correct` 로 두고 override 하지 않는다.
2. 그 섹션을 배수 1 로 다시 읽은 원문 금액 A(≥1e7)에 k ∈ {1, 1,000, 1,000,000} 을 곱해,
   **같은 회사의 다른 필링**에 이미 적재된 값(같은 basis·statement·context_fiscal_year, SCE 는
   같은 basis 의 SCE·BS)과 **정확히 같은** 금액 수를 센다 = hits(k). 의심 필링 자신들은 증거에서 뺀다.
   이 필링의 전기 비교열은 앞선 정상 필링의 당기열이므로 원 단위 12자리 금액이 그대로 겹친다.
3. 확정: hits(k) ≥ 3 이고, 다른 k(선언 배수 포함)는 전부 hits ≤ 1 이면서 hits(k) ≥ 10×그 값.
   hits ≤ 1 을 허용하는 이유는 둥근 숫자 우연 1건(예: 5,000,000×1,000 = 자본금 5,000,000,000)이
   정확일치 80건을 거부하지 않게 하려는 것이다.
4. 2차: 타 필링 증거가 없는 섹션은 **같은 문서에서 이미 k=1 로 확정된 섹션**(같은 basis)의 금액을
   증거로 같은 규칙을 적용한다. 당기순이익·현금·자본총계가 IS/CF/SCE/BS 에 반복되기 때문이다.
5. 확정분만 `fin2/extract/data/unit_self_contradiction_overrides.json` 에 `{rcept: {섹션코드: k}}`
   로 기록한다(`scripts/unit_self_contradiction_scan.py --apply`). 파서는
   `report_lines._unit_override()` 에서 R132 수기목록 다음으로 이 파일을 보고, BS/IS/CF 와 SCE
   **두 방출기 모두** 같은 자리에서 적용한다. `unit_source='proved_unit'`(R132 는 `manual_unit`).
   파일에 없는 섹션은 선언 단위 그대로다(R6).

**측정(2026-09-25 스캔, `docs/qa/r169_unit_self_contradiction_scan_2015plus.jsonl`)**:

| 지표 | 값 |
|---|---|
| 의심 필링 | 111 (그중 6 은 배수 무관 — 위 1번 제외 규칙) |
| 판정 섹션 | 631 |
| 확정 섹션 (전부 k=1, 원) | 594 · **87필링 84개사** (2차 문서내 증거로 확정 11섹션) |
| 확정 섹션의 행 수 (선언 단위 → 원 단위 추출) | 32,865 → 43,655 |
| 미확정 | 37섹션 — NH투자증권 18필링 CF 36섹션(선언 백만원이 맞음: hits(10⁶)>0, hits(1)=0) · 제주항공 `20170814001427` IS_C 1섹션(증거 2건뿐) |
| 기존 수기 확정과의 일치 | R132 6필링 전부, 계층3 R73 2슬롯(유아이디 2020Q1·다원넥스뷰 2024H1) 전부 k=1 로 독립 재확정 |

**함께 바꾼 것**: R143 법인세비용 인라인 XBRL 오버레이(`overlay_tax_expense_value`)는 크기 검사 없이
값을 덮는다. 그 fact 는 틀린 선언 배수로 환산돼 있어, override 된 행(`manual_unit`·`proved_unit`)을
다시 ×10⁶ 로 부풀렸다(실측 3필링: HL홀딩스 2024FY 법인세비용 5,127,350,201 → ×10⁶). override 된 행은
오버레이 대상에서 뺀다. 계층3 `fin2/layer3/unit_overrides.py` 의 유아이디 2020Q1(3항목)·다원넥스뷰
2024H1(20항목) ×10⁻⁶ 교정을 삭제했다. 계층2가 원 단위로 적재하므로 남겨두면 이중 교정된다.
테스트 `test_3s_2023q3_sanemax_reject_cum_map_no_longer_wrong_column` 의 기대값이 "매출액 결측"에서
"원문 누적값 28,371,524,760 / 18,062,116,780"으로 바뀌었다. 전기 3개월값을 누적으로 둔갑시키지
않는다는 R74 가드 확인은 그대로 둔다.

**데일리(런북 A3)**: `scripts/collect_new.py::_report_unit_self_contradiction()` 을
`_run_standardize_batches` 안 `_sync_layer2_lines` 직후에 배선했다. 두 call site 가 모두 이 함수를
지난다. 데일리는 **탐지·보고만** 하고(`logs/unit_self_contradiction_pending.jsonl` + 경고 로그) 데이터
파일은 쓰지 않는다. 추적 파일을 main 체크아웃에서 더럽히지 않기 위해서다. 교정은 수정 워크트리에서
`--apply` → 커밋 → `vq.py batch reload` 로 한다. 선언 백만원이 맞는 섹션(hits(10⁶)>0)은 보고하지 않는다.

**재적재·결과(fix batch #3, 2026-09-25)**: `vq.py batch reload 3` 1차 93필링(commit 7146776) done 93 ·
deferred 0 · failed 0. 후속 수정(96ba37c) 뒤 9필링(오버레이 3 + 배수 무관 6) 재적재 done 9. 대상 93필링의
BS/IS/CF/SCE 행은 23,424 → 30,606 이고, |값|≥1e15 행은 6,765 → 11 이다. 남은 11행은 제주항공 IS_C 미확정
5행과 R152 계열 붙은 대손준비금 칸 6행이다. 이슈 318건 전부 원문 값·라벨이 DB 와 일치해 **fixed 318 /
not_fixed 0**. std_v3·calendar_v3 는 85개사를 재빌드했다(실패 0, 런북 B1+B5). DQ `calendar_orphan_cq` 1,020건은 전부
이 배치 밖 283개사로 기존 잔존이다. `statement_magnitude_impossible` 는 0이다. 다원넥스뷰 2024H1 자본총계는
12,990,187,922 로 원문 당기열과 일치한다. 삭제된 R73 항목의 메모 "38억원"(3,783,475,775)은 원문 **전기**열
값이었다.

**범위 밖(남은 것)**: ① 선언 천원·실제 원인데 금액이 작아 1e15 에 못 미치는 섹션은 트리거가 안 걸린다.
② 2015 이전은 스캔하지 않았다. ③ XBRL/PDF 경로 필링은 대상이 아니다(XML 원문 전용).

**테스트**: `fin2/tests/test_r169_unit_self_contradiction.py`(휴젤·한국타이어·넷마블 SCE·NH투자증권
비대상·판정 규칙·데이터파일 형식).

**관련**: R132(수기판의 일반화) · R73(계층3 교정, 2건 이관) · R6 · R74 · R154/R168(자기증명 선례)

---

## R170. XBRL 경로: 회사 `_pre.xml` 은 **DART 표준 base 표시링크베이스에 대한 델타**다 — base 를 병합하고 arc 는 **개념 단위**로 잇는다 (2026-09-25)

**발견**: verification 캠페인 missing_row 이슈 177건(fix batch #4). XBRL instance zip 경로(PDF-only) 10필링:
한화엔진 2015Q1 `20150515002710`, 엘앤에프 2015Q3 `20151104000116`·`20151221000346`, 롯데케미칼 2016H1
`20160816002306`, SK가스 2017Q1·H1·Q3 `20170529000325`·`20170816000261`·`20171117000389`, 대한광통신 2017H1
`20170818000262`, 케어젠 2019Q1 `20190515002560`, 로보티즈 2019Q1 `20190522000395`. 매출총이익·영업이익·
법인세비용·EPS·단기차입금·이연법인세부채·비지배지분·SCE 전체 등이 빠져 있었다. 사실(fact)은 instance 에 전부 있다.

**원인 1 — base 미병합**: 2013-03-31·2017-10-01·2018-07-01 vintage 의 회사 `_pre.xml` 은 완전한 트리가 아니다.
`dart_{vintage}.xsd` 가 `presentationLinkbaseRef` 로 선언한 **공유 base**(`ifrs_for_dart/pre_dart_{vintage}_role-D310005.xml`
등, 즉 필링 DTS 의 일부) 위에 얹는 델타다. 한화엔진 회사 파일 arc 1,488개 중 1,301개가 `use="prohibited"`(base arc 취소)다.
GrossProfit·IncomeTaxExpense 는 base 에만 있다. 회사 파일만 읽으면 조용히 사라진다. 9필링 전부 prohibited 1,290~2,652개(델타형).
2019-10-01 vintage 는 공유 스키마에 base 표시링크베이스 선언이 없다(회사가 전체 트리를 번들). 병합 대상이 아니다.

**원인 2 — 고아 부모 loc(R129 부작용)**: 회사는 base arc 를 prohibit 한 뒤 **같은 개념을 새 loc 이름으로** 다시 건다.
그런데 자식 arc 는 옛 loc 이름에서 나간다. 엘앤에프: `Loc_label_ifrs_CurrentLiabilities` 는 prohibited arc 로만 도달돼
R129 가 지우고, 새 loc `..._CurrentLiabilities2015102910317929` 가 걸렸다. 단기차입금·유동성장기차입금 arc 는
`from=Loc_label_ifrs_CurrentLiabilities` 라 "undeclared loc" 로 통째로 버려졌다. XBRL 에서 arc 는 **개념 사이의 관계**이고
loc 이름은 파일 안의 포인터일 뿐이다.

**원인 3 — EPS unit**: 2013 vintage 회사가 EPS 를 `unitRef="SHARES"`(measure `shares`)로 태깅한다(한화엔진
BasicEarningsLossPerShare −115 = 원문 주당손실 (115)원). `_numeric_value` 가 KRW·KRW/shares 만 받아 버려졌다.

**규칙** (`parser/xbrl_instance/taxonomy_linkbase.py::_build_merged_presentation_tree`, `resolve_external_base_presentation`):
1. 핵심 재무제표 role 마다 필링 xsd 의 import 체인에서 `dart_{vintage}.xsd` 를 찾는다. 그 `presentationLinkbaseRef` 중
   role id(`..._role-D310005.xml`)가 맞는 파일을 받아 **그 role URI 를 실제로 담은 것만** base 로 쓴다. 캐시는
   `external_taxonomy.fetch` 를 쓴다. base 가 없는 role 은 기존 회사 파일 단독 빌더를 그대로 쓴다(무변경).
2. 병합망의 동등 관계(from·to 개념, order, preferredLabel 이 같음)는 **priority 최고값**이 이긴다. 그 최고값에
   prohibited 가 있으면 관계를 제거한다(XBRL 2.1 §3.5.3.9).
3. 같은 개념+preferredLabel 을 회사가 한 번이라도 배치했으면 base 의 배치는 버린다(재배치 중복 방지).
4. arc 의 부모는 **개념으로** 찾는다. from loc 이 배치된 노드가 아니면 같은 개념의 노드에 붙인다.
5. **IS role 만** base 의 `negated*` preferredLabel 을 뗀다(label role 은 유지, `_denegate_role`). base IS 템플릿은
   법인세비용·판관비를 차감 표시(negatedTerseLabel)한다. 국내 손익계산서는 비용을 양수로 인쇄하므로 fact 부호가
   곧 원문이다(batch #4 법인세비용 9/9: 원값 일치, negation 시 9/9 반대). **CF 의 base negation 은 유지한다**:
   유출(이자지급·법인세납부·차입금상환·리스부채상환 8/8)을 원문 괄호대로 음수로 만든다. 회사 자신의 negated arc 는 R10 그대로다.
6. `*PerShare*` 개념은 measure `shares` 로 잘못 선언돼도 값을 받는다(R170-c). 다른 개념엔 적용하지 않는다.

**검증(2015+ XBRL 경로 전수 1,627필링, 수정 전후 추출 diff)**: 행 494,205 → 890,058. **값 소실 0**(부호 무시 비교).
SCE 가 새로 생긴 필링: 별도 1,620 · 연결 1,266(수정 전엔 axis/LineItems 노드가 base 에만 있어 "노드 없음, 스킵").
새 SCE 2,895블록은 전부 기말자본이 BS 자본총계와 일치한다(2,895/2,895). 부호가 바뀐 기존 행 5,102개:
법인세납부 3,309 · 이자지급 1,775 는 R130 트리-갭 백업 행(원값 양수)이 트리 노드(base CF negation, 원문 괄호)로
바뀐 것이다. 나머지 18행(7필링)은 회사 자신의 negated arc(R10)가 고아 loc 로 떨어져 있다가 붙은 것이다
(지배력 획득·소유지분 변동 지급·재무활동 법인세납부·차입금상환, 전부 유출).
batch #4 이슈 177건 중 176건이 원문 값·부호와 일치한다. 1건(#83818 대한광통신 연결 CF 퇴직금의 지급)은 행이 생겼으나
부호가 반대다. base·회사 모두 negation 이 없고 회사가 fact 를 +363,582,949 로 태깅했다(원문 (363,582,949)).
→ sign_flip 계열로 넘긴다.

**배선**: `fin2/extract/report_lines_xbrl.py::extract_report_lines_xbrl` 안쪽 변경이라 데일리
`collector/xbrl_instance_lines_sync.py` 는 그대로 반영된다. `fin2/verification/ops.py::_reload_rcept` 가 이제
`xbrl_zip` 필링도 재적재한다(그전엔 "PDF/XBRL 경로는 전용 스크립트로" 실패 처리).

**테스트**: `fin2/tests/test_xbrl_base_presentation_merge.py`(합성 링크베이스 7 + 실필링 3: 한화엔진 IS·엘앤에프 BS·
대한광통신 CF). `fin2/tests/test_xbrl_instance.py::test_r130_…` 의 법인세납부 기대값을 +5,582,220 → −5,582,220
(라벨 "법인세납부(환급)")으로 바꿨다. 트리 노드가 되면서 원문 괄호 부호가 됐다.

**관련**: R10(negated 부호) · R14(구형 taxonomy) · R129(prohibited — 이 규칙이 병합 경로에서 대체) · R130/R133(트리-갭 백업,
병합 후엔 대부분 발동 안 함)

**재적재·결과(fix batch #4, 2026-09-25)**: 커밋 5b824c8. `vq.py batch reload 4 --shard i/6` 1,622필링(이슈 10 + 이슈 미등록
1,612) done 1,622 · failed 0(lease deferred 1건은 재시도로 done). 이슈 177건 DB 셀 대조 176/176 일치 → **fixed 176**.
#83818 은 행은 생겼으나 부호가 회사 태깅 탓이라 batch 에서 빼 open 으로 되돌렸다. 계층3: std_v3 + calendar_v3 772개사 재빌드,
실패 0, 그 corp 범위 `calendar_orphan_cq` 0. std_v3 셀 변화(122,041행 중): D&A/EBITDA 채움 약 7,500(CF 조정 구간이
트리에 들어옴) · 차입금상환 부호 431 · 매출총이익/영업이익/EBT 값 변경 약 550. 값 변경은 대부분 **XBRL 정정본이
이제 소계행을 가져서** 원본 소계와 정정 매출이 섞이던 조합이 풀린 것이다(엠엑스로보틱스 2016Q1 별도: 영업이익
1,216,916,032 → −2,057,838,187, 정정본 매출 14,743,387,117 기준). 변경 421행의 항등식은 영업이익=매출총이익−판관비
238/387 → 375/399, 매출총이익≤매출 381 → 400 으로 좋아졌다.
BS 항등식(자산=부채+자본)은 2행이 새로 깨졌다: 00242378 2019Q3 연결, 00453488 2018Q1 연결. 00242378 의 XBRL 정정본
`20191206000533` 은 자체로 맞는다(자산 1,912,137,914,170 = 부채 1,135,133,772,680 + 자본 777,004,141,490). 원인은 계층3
조립이다. 원본 → XBRL 정정 → XML 정정(`20200721000363`) 세 필링에서 자산은 XML 정정, 부채는 XBRL 정정 값을 골랐다.
R170 추출 결함이 아니며 R171 로 해소. DQ: `statement_magnitude_impossible` 0.

**★R170-d 정정(2026-09-25 오전, R171 작업 중 발견) — 5번(IS base negation 제거) 단독은 틀렸다**: 법인세 fact 부호 관례는
제출자마다 다르다. 엘앤에프 `20151104000116` 별도는 fact −38,948,803 인데 세전 −207,824,678·순이익 −246,773,481 이라
원문 법인세비용은 +38,948,803 이다(같은 필링 연결은 + 관례). R170 적재 후 XBRL 손익계산서 2,896개 중
**437개가 세전+법인세=순이익**(부호 반대)이었다. 규칙: `report_lines_xbrl._settle_is_tax_sign()` —
같은 (basis, col)에서 세전 + 법인세 = 계속영업이익(없으면 당기순이익)이고 세전 − 법인세 ≠ 그 값일 때만 법인세 부호를
뒤집는다. 어느 쪽도 성립하지 않으면(중단영업 등, 26개) 그대로 둔다(R6). 적용 후 ok 2,530 · 반대 0 · 판정불가 366.
변화 438필링 / 법인세 셀 866(col0+col1)만 바뀌고 다른 셀은 무변화다. 5번의 "법인세 9/9" 표본은 이 관례 차이를 대표하지 못했다.

---

## R171. 정정 체인에 추출 경로가 섞이면(XML → XBRL → XML) **나중 XML 필링이 앞선 XBRL 셀을 스코프 단위로 대체**한다 (2026-09-25)

**발견**: R170 재빌드 후 std_v3 BS 항등식 신규 위반 2행. 00242378 2019Q3 연결: 원본 XML `20191114002491` →
정정1 XBRL `20191206000533` → 정정2 XML `20200721000363`. 세 필링은 각자 항등식이 성립한다. 그런데 std 는 자산·자본을
정정2, 부채(1,135,133,772,680)를 정정1 에서 골랐다. 정답은 정정2(부채 1,134,848,933,304)다. 00453488 2018Q1 연결도 같은 체인이다.

**원인**: R2 델타패치 셀 키 `(statement, basis, col_index, section_path, label_raw)` 는 **같은 추출 경로끼리만** 맞는다.
XBRL 은 "재무상태표 [abstract]>부채 [abstract]" 같은 section_path 를 쓴다. 그래서 경로가 바뀐 정정본의 셀은 '추가'로만
쌓이고, 그 뒤 필링도 그것을 덮지 못한다. R170 전에는 XBRL 정정본에 총계행이 거의 없어 드러나지 않았다.
경로 혼합 기간은 1,497개다(xbrl+xml 1,495 · pdf+xml 2). XBRL 필링은 거의 전부 XML 원본의 정정본이다(XBRL 단독 기간 3).

**규칙** (`fin2/layer3/combine.py::build_merged_lines`, `_filing_source_kind`): 나중 필링이 **XBRL 이 아니고**(xml/pdf)
어떤 (statement, basis) 스코프를 실제로 담고 있으면, 그 스코프의 **XBRL 출처 셀**을 지운 뒤 델타패치한다.
그 필링이 담지 않은 스코프는 그대로 둔다(R2-0).

**왜 반대 방향(XBRL 이 XML 을 대체)은 안 하나**: 양방향으로 적용해 보면(드라이런, 776개사) 법인세 2,122 · 지배순이익 305셀이 비었다.
계층3 매퍼가 XBRL 라벨("법인세비용, 계속영업", "[abstract]" section_path 아래 귀속행)을 못 읽기 때문이다. 이것은
**계층3 XBRL 개념(source_ref) 기반 매핑이 생겨야 풀린다 — 별도 과제, 미착수**. 그때까지 XBRL 정정본이 마지막인
체인은 현행(두 경로 셀 공존)을 유지한다.

**검증(드라이런, 경로 혼합 776개사, 롤백)**: 핵심 컬럼이 바뀐 std 행 8개. BS 항등식 위반→성립 2(위 두 건), 성립→위반 0.
부수 변화는 전부 교정이다. HD현대 `20191114002747`(XBRL 정정)이 천원 값을 배수 없이 태깅해 매출 414,877,871 로 들어가 있던
2019Q3 별도가 나중 XML 정정 기준 414,877,871,000 이 됐다. 차입금상환 부호 33은 XML 원문 표기를 따른다.
※드라이런에서 사라진 std 776행(2026Q1 별도 등)은 R171 무관이다. 옛 코드로 재빌드해도 똑같이 사라진다(아래 재빌드는 경로 혼합 기간만 한다).

**테스트**: `fin2/tests/test_combine_cross_source_amendment_r171.py`(가짜 세션) ·
`fin2/tests/test_xbrl_base_presentation_merge.py`(R170-d 등식 3건).

**관련**: R2/R2-0 · R170 · R63(delete-then-maybe-insert)

**적용 결과(2026-09-25 08시대, 커밋 8167bb6)**: R170-d 로 법인세가 바뀐 438필링을 batch #4 로 재적재했다(done 437,
`20160816002306` 롯데케미칼 2016H1 은 검증 lease 로 deferred → 다음 reload 재시도, batch #4 는 reloading 유지).
std_v3 는 **경로 혼합 기간 + 그 필링 기간 1,498개만** 재빌드했다(`build_corp` 의 `_periods` 를 좁힘, 777개사, 2,848행,
실패 0). 회사 전체 재빌드는 R171 과 무관하게 2026Q1 별도 등 776행을 지우므로(옛 코드도 동일) 피했다.
calendar_v3 는 777개사를 재동기화했고 orphan 0 이다.
std 변화: BS 항등식 위반→성립 2(00242378 2019Q3 연결 1,909,991,807,496 = 1,134,848,933,304 + 775,142,874,192 ·
00453488 2018Q1 연결 250,442,096,694 = 172,573,069,934 + 77,869,026,760), 성립→위반 0, 소실 행 0,
법인세 부호 교정 258셀. 부수 변화로 판관비 2셀이 비었다. 엘앤에프 2015Q3 별도는 최종 XML 정정의 '판매비'·'관리비'
분리 표기를 계층3 가 합산하지 못한다(기존 계층3 한계). DQ `statement_magnitude_impossible` 0.

## 부록 B. 규칙이 사는 곳 (원출처)

| 규칙 | 원출처 |
|---|---|
| R1 | 메모리 `architecture-report-read-layer2-only` · `docs/plans/rearchitecture_4layer.md` §6 · 위반 해소 = `docs/plans/biz_content_layer2_migration_2026-08-09.md` |
| R2 | `fin2/layer3/combine.py:79,96` docstring |
| R3 | `collector/filing_collector.py:524` · 실측 |
| R4 | 메모리 `layer2-unit-column-attribution` · `fin2/extract/units.py` |
| R4-1 | 사용자 결정 2026-08-05 · `fin2/extract/text.py::document_default_unit` |
| R4-2 | 사용자 결정 2026-08-05 · `fin2/extract/statement_titles.py::owned_merged_title/titleless_bs_start` · `docs/plans/merged_title_data_table_r4-2_2026-08-05.md` |
| R5 | 메모리 `layer2-header-hint-lossless` · `fin2/layer3/combine.py:134` |
| R6 | `fin2/extract/rd_note.py` · `fin2/standardize/calendar.py` |
| R7 | 메모리 `foreign-corps-excluded` · `CLAUDE.md` |
| R8 | `docs/runbook_new_parser_pipeline_integration.md` · `CLAUDE.md` |
| R9 | 메모리 `feedback-verify-against-source` |
| R10 | `docs/plans/xbrl_instance_parser_todo_2026-08-05.md` Phase 6-2/6-5 · `fin2/extract/report_lines_xbrl.py::_value_sign()` |
| R11 | 사용자 지시 2026-08-07 · `docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md` §8~§11 · `docs/plans/note_span_fix_plan_2026-08-07.md` Phase 1(T1.1)~Phase 3(T3.6, 2026-08-08 완료) |
| R12 | 사용자 결정 2026-08-09(옵션A, 계층2 신설) · `docs/plans/std_v3_dq_shares_period_backfill_plan_2026-08-09.md` §3.3 · `fin2/extract/shares_transcribe.py`·`fin2/layer3/build.py::_select_shares_out` |
| R13 | 사용자 결정 2026-08-10(Phase1~5 순차 승인) · `docs/plans/pre2015_layer2_backfill_plan_2026-08-10.md`·`..._todo_2026-08-10.md` · `fin2/extract/legacy_pre2015.py`·`fin2/extract/report_lines.py::extract_report_lines`·`collector/note_lines_sync.py::FY_MIN` |
| R14 | `docs/plans/pdf_only_parser_phase2_design_2026-08-12.md` §A · `docs/qa/pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md` · `fin2/extract/report_lines_xbrl.py`·`external_taxonomy.py::dart_first()`·`taxonomy_linkbase.py::resolve_external_labels()` |
| R15 | `docs/qa/gate_b_v3_fail_a_784_triage_2026-08-13.md` ③ · `docs/plans/gate_b_fail_a_bugfix_2_3_plan_2026-08-13.md` 버그 #3 · `fin2/layer3/combine.py::_resolve()/_is_noncurrent()` · `fin2/tests/test_combine_current_strict.py` |
| R16 | `docs/qa/gate_b_fail_a_revenue_tradepayables_triage_2026-08-13.md` · `docs/plans/gate_b_faila_combine_stage_rank_shortcut_fix_design_2026-08-13.md` · `fin2/layer3/combine.py::_resolve()` (`_REVENUE_TOTAL_OVERRIDE_CORPS`/`_TRADE_PAYABLES_PARENT_OVERRIDE_CORPS`) · `fin2/tests/test_combine_curated_overrides.py` |
| R17 | `docs/plans/gate_b_faila_trade_payables_additive_design_2026-08-14.md`(원설계) · 이 세션 실측(구현 중 발견) · `fin2/layer3/combine.py::_resolve()` (`_TRADE_PAYABLES_ADDITIVE_OVERRIDE`) · `fin2/tests/test_combine_curated_overrides.py` |
| R20 | `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md` · `docs/qa/is_sga_cogs_holdco_phase0_scan_2026-08-15.md` · `fin2/layer3/combine.py::_resolve()` (`_SGA_SUBLINE_OVERRIDE_KEYS`/`_SGA_SUBLINE_LABELS`) · `scripts/generate_sga_subline_override_2026-08-15.py` |
| R21 | `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md`(Phase 2) · `scripts/probe_cogs_phase2_2026-08-15.py`·`probe_cogs_unmapped_labels_2026-08-15.py`·`probe_cogs_alias_global_risk_2026-08-15.py` · `fin2/layer3/combine.py::combine_full()`/`_cogs_additive_labels()` (`_COGS_ADDITIVE_OVERRIDE`) · `scripts/generate_cogs_additive_override_2026-08-15.py`. 부기(라벨충돌 버그수정) = `scripts/probe_cogs_additive_label_collision_2026-08-15.py`·`probe_cogs_collision_impact_2026-08-15.py` · `_is_cogs_labeled()` |
| R22 | `docs/plans/is_sga_cogs_holding_co_label_mismap_plan_2026-08-15.md`(Phase 3) · `scripts/probe_gateb_cogs_concept_mismatch_2026-08-15.py` · `fin2/audit/face_audit.py`(`_COGS_CONCEPT_MISMATCH_KEYS`/`_PENDING_REASONS`) |
| R23 | 메모리 `gateb-reader-concept-gap-scan-2026-08-15` · `scripts/probe_gateb_reader_concept_gap_2026-08-15.py` · `fin2/taxonomy/concept_map.py` · `fin2/audit/face_audit.py`(`_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS`) |
| R24 | 메모리 `gateb-controlling-ni-mismap-r24-implemented-2026-08-15` · `docs/plans/std_v3_controlling_ni_mismap_structural_fix_design_2026-08-15.md` · `fin2/layer3/combine.py::_ni_attribution_structural_candidates()` |
| R25 | 메모리 `gateb-facereader-fix-design-2026-08-15` · `docs/plans/gate_b_facereader_controlling_ni_fix_design_2026-08-15.md`(§2-B) · `fin2/audit/face_audit.py::_ni_attribution_structural_candidates()` |
| R26 | `docs/plans/gate_b_facereader_controlling_ni_fix_design_2026-08-15.md`(§2-A) · `fin2/audit/face_audit.py`(`_FX_PRESENTATION_CURRENCY_KEYS`/`_PENDING_REASONS`) |
| R27 | `docs/plans/gate_b_controlling_ni_groupbc_kbimetal_eps_label_trap_fix_design_2026-08-15.md` · `fin2/extract/report_lines.py`(`_EPS_MAX_PLAUSIBLE_WON`/`_looks_like_eps_amounts()`) · `scripts/reload_report_lines_corp.py`/`scripts/build_std_v3.py` |
| R31 | `docs/plans/t22_hyphen_negative_gate_todo_2026-08-16.md` · `parser/xml/table_extractor.py::_NUMBER_PATTERN` · `fin2/tests/test_hyphen_negative_gate_r31.py` · `scripts/census_t22_hyphen_negative_2026-08-16.py`·`scripts/scan_r31_true_targets_2026-08-16.py`·`scripts/reload_report_lines_corp.py`(`--year-max`)/`scripts/build_std_v3.py`/`scripts/snapshot_r31_backfill_2026-08-16.py` |
| R34 | P3-1 재감사 후속(2026-08-20) · `fin2/layer3/combine.py::_resolve()` · `fin2/tests/test_combine_amended_label_depth.py` · `scripts/investigate_p3_combine_live_check.py`·`scripts/investigate_p3_depth_bug_census.py`·`scripts/verify_p3_depth_bug_fix.py` |
| R35 | P3-1 원인 A 후속(2026-08-20) · `fin2/audit/face_audit.py::_ni_attribution_text_candidates()`/`_with_ni_attribution_text_fallback()` · `fin2/tests/test_ni_attribution_text_fallback.py` · `scripts/investigate_p3_cause_a_field_census.py`·`scripts/investigate_p3_cause_a_trackb_probe.py`·`scripts/investigate_p3_cause_a_impact_measure.py` |
| R42 | `docs/plans/gateb_trade_payables_stale_subline_r42_2026-08-21.md` · 메모리 `gateb-trade-payables-stale-subline-r42-2026-08-21` · `fin2/layer3/combine.py::_resolve()` (`_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE`) · `fin2/tests/test_combine_curated_overrides.py` |
| R43 | 메모리 `gateb-nh-investment-controlling-ni-comprehensive-income-contamination-2026-08-25` · `parser/common/account_mapper.py`(포괄손익 귀속 가드) · `fin2/tests/test_account_mapper_comprehensive_income_guard.py` · `scripts/census_r43_comprehensive_income_labels_2026-08-25.py`·`scripts/r43_comprehensive_income_guard_backfill_diff_2026-08-25.py` |
| R44 | 메모리 `gateb-continuing-ops-attribution-sibling-guard-2026-08-25` · `parser/common/account_mapper.py`(중단/계속영업 귀속 성분 가드) · `fin2/tests/test_account_mapper_discontinued_attribution_guard.py`·`fin2/tests/test_combine_ni.py` · `scripts/census_continuing_ops_attribution_labels_2026-08-25.py`·`scripts/continuing_ops_isolated_diff_2026-08-25.py`·`scripts/verify_continuing_ops_val_to_val_2026-08-25.py` |
| R45 | 메모리 `gateb-r44-resolve-redesign-2026-08-25` · `docs/plans/gateb_r44_resolve_redesign_2026-08-25.md` · `fin2/layer3/combine.py`(`_derive_net_income_from_continuing_discontinued()`·`_resolve_ni_attribution()`) · `fin2/tests/test_combine_ni.py` · `scripts/census_continuing_total_labels_2026-08-25.py`·`scripts/census_gyesokgiub_2026-08-25.py` |
| R46 | 메모리 `faceaudit-ni-attribution-skipgate-2026-08-26` · `docs/plans/faceaudit_ni_attribution_skipgate_design_2026-08-26.md` · `fin2/audit/face_audit.py::_with_ni_attribution_text_fallback()` · `fin2/tests/test_ni_attribution_text_fallback.py` · `scripts/probe_faceaudit_ni_oci_mislabel_2026-08-26.py` |
| R105/R106/R107 | `docs/plans/consolidation_scope_confirmation_design_2026-09-13.md` §8 · `fin2/extract/consolidation_evidence.py` · `fin2/tests/test_consolidation_evidence.py` · 마이그레이션(consolidation_status VARCHAR 확장) |
| R108/R109/R110 | `docs/plans/consolidation_scope_confirmation_design_2026-09-13.md` §11-12 · `fin2/extract/consolidation_evidence.py` · `scripts/delete_consolidation_r_fixes_2026-09-13.py` |
| R111~R114 | 커밋 `c6c115f` · `parser/xml/table_extractor.py`(`_SUBTYPE_CUM_RE`/`_SUBTYPE_3M_RE`/`_NOTE_HEADER_RE`/`select_by_header_columns()`) · `fin2/extract/text.py`(`_CUM_RE`/`_THREE_M_RE` 동형 사본) · `fin2/tests/test_header_grid_column_map_r88.py` |
| R115 | 커밋 `77eb4bd` · `parser/xml/table_extractor.py::drop_mismatched_granularity_columns()` |
| R116 | 커밋 `0fd3915`·`0454d86`·`3b3a716` · `fin2/extract/report_lines.py::_Q1_CUM_BLANK_USE_3M_RCEPTS` · 부록 D |
| R117 | 커밋 `a047036` · `parser/xml/table_extractor.py::_columns_from_grid()` |
| R118 | 커밋 `6d36f49`·`2a2c1ac`·`eaaaacc`·`43b09c3`·`cf7de2f` · `fin2/extract/report_lines.py::_R118_DUPLICATE_PERIOD_LABEL_FIX` · 부록 D |
| R119 | 커밋 `fe16c14` · `parser/xml/table_extractor.py::_columns_from_grid()` |
| R120 | 커밋 `ea289cb`·`3b3a716` · `parser/xml/table_extractor.py::select_by_header_columns()`(`prefer_last_of_two_as_cumulative`) · `fin2/extract/report_lines.py::_HEADERLESS_MERGE_LAST_IS_CUMULATIVE_RCEPTS` · 부록 D |
| R121 | 커밋 `ebd817d` · `fin2/extract/report_lines.py::_MANUAL_NO_CONSOLIDATED_FS_RCEPTS` · 부록 D |
| R122 | 커밋 `40bf13c` · `parser/xml/table_extractor.py::_PERIOD_KEY_RE` |
| R123 | 커밋 `b02acf1` · `scripts/scan_header_fallback_2015plus_2026-09-14.py` · `parser/xml/table_extractor.py::_PERIOD_KEY_RE` |
| R124 | 커밋 `461bec9`(되돌림 기록) — 되돌려짐, R125로 대체 |
| R125 | 커밋 `461bec9` · `parser/xml/table_extractor.py::_columns_from_grid()`(`allow_duplicate_subtype`) · `fin2/extract/report_lines.py` |
| R126 | 커밋 `4afe938` · `parser/xml/table_extractor.py::_PERIOD_KEY_RE` |
| R127/R127b | 커밋 `82522df`·`3420b9a` · `fin2/extract/text.py::_looks_like_equity_changes_header()`/`_detect_body_statement_tables()` |
| R128/R128b | 커밋 `7799788`·`43b09c3` · `parser/xml/table_extractor.py::_PERIOD_KEY_RE` |
| R129 | 커밋 `ac80d52` · `parser/xbrl_instance/taxonomy_linkbase.py::_drop_prohibited_only_locs()` · `fin2/tests/test_xbrl_instance.py` |
| R130 | 커밋 `5a1bdac` · `fin2/extract/report_lines_xbrl.py::_emit_missing_cf_lines()`(`_REQUIRED_CF_LINES`) · `fin2/tests/test_xbrl_instance.py` |
| R131 | 최종 전체 재적재 후 이상치 재검증(2026-09-16) · `parser/xml/table_extractor.py::select_by_header_columns()` · `fin2/tests/test_header_grid_column_map_r88.py`·`fin2/tests/test_report_lines.py::test_r131_kd_...` |
| R132 | 최종 전체 재적재 후 이상치 재검증(2026-09-16) · `fin2/extract/report_lines.py::_MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS` · `fin2/tests/test_report_lines.py::test_r132_netmarble_...` · 부록 D |
| R133 | 사용자 지시로 R130 즉시 확장(2026-09-16) · `fin2/extract/report_lines_xbrl.py::_emit_missing_leaf_lines()`(`_REQUIRED_IS_LINES`) · `fin2/tests/test_xbrl_instance.py::test_r133_...` |
| R134/R135 | 커밋 `d03e177`(2026-09-17, 이 문서엔 2026-09-18 뒤늦게 등재) · `parser/xml/table_extractor.py::_header_rule_name()` · `fin2/extract/report_lines.py::_grid_body_rows()` · `fin2/tests/test_header_rule_name_r134_sce.py`·`fin2/tests/test_grid_body_rows_r135_multicell_label.py` |
| R136/R137 | 커밋 `3fb4d01`(2026-09-18) · `fin2/extract/pdf.py`·`fin2/extract/xbrl.py`·`collector/pdf_lines_sync.py` · `fin2/tests/test_pdf.py`·`fin2/tests/test_pdf_lines_sync.py` |
| R138 | 2026-09-18(사용자 지시 "8개사부터 시작"→표본조사 중 발견) · `scripts/scan_header_fallback_2015plus_2026-09-14.py` · `docs/plans/report_lines_legacy_fallback_hardening_design_2026-09-17.md` §7 |
| R139 (2026-09-24 폐지→R167) | 사용자 지시 2026-09-18(원문대조 캠페인 자동화 설계 중) · `fin2/extract/report_lines.py::store_report_lines()` · `fin2/tests/test_store_report_lines_manual_guard.py` |
| R167 | 사용자 결정 2026-09-24(verification 캠페인) · `fin2/verification/schema.sql` · `collector/db.py::_set_verification_identity` · `fin2/tests/test_verification_*.py` |
| R169 | verification fix batch #3(2026-09-25, 야간 자율) · `fin2/audit/unit_self_contradiction.py` · `scripts/unit_self_contradiction_scan.py` · `fin2/extract/data/unit_self_contradiction_overrides.json` · `fin2/extract/report_lines.py::_unit_override()` · `scripts/collect_new.py::_report_unit_self_contradiction()` · `fin2/tests/test_r169_unit_self_contradiction.py` |
| R170 | verification fix batch #4(2026-09-25, 야간 자율) · `parser/xbrl_instance/taxonomy_linkbase.py::_build_merged_presentation_tree()`/`resolve_external_base_presentation()`/`_denegate_role()` · `fin2/extract/report_lines_xbrl.py::_numeric_value()` · `fin2/verification/ops.py::_reload_rcept()` · `fin2/tests/test_xbrl_base_presentation_merge.py` |
| R171 | 사용자 지시 2026-09-25(R170 후속 판단 1번) · `fin2/layer3/combine.py::build_merged_lines()`/`_filing_source_kind()` · `fin2/extract/report_lines_xbrl.py::_settle_is_tax_sign()`(R170-d) · `fin2/tests/test_combine_cross_source_amendment_r171.py` |
| R140 | 사용자 지시 2026-09-18(SCE 포함 + 단계(B) 지정) · `fin2/extract/review_csv.py`·`fin2/audit/layer2_selfcheck.py`·`scripts/layer2_review.py` · `fin2/tests/test_review_csv.py` · `docs/plans/layer2_review_browser_agent_automation_design_2026-09-18.md` |
| R141 | 사용자 지시 2026-09-19("확인시작해" — 계층2 원문대조 캠페인 fail 10건 근본원인 조사) · `fin2/extract/statement_titles.py::classify_statement_in_body_section()` |
| R142 | 위와 동일 조사(2026-09-19) · `fin2/extract/statement_titles.py::is_substatement_marker()` · `fin2/extract/text.py::_detect_body_statement_tables()`(`last_stmt`) · `fin2/tests/test_r142_substatement_marker.py` |
| R143 | 위와 동일 조사(2026-09-19) · `fin2/extract/report_lines_inline_xbrl_overlay.py::overlay_tax_expense_value()`(`_TAX_EXPENSE_EXCLUDE_KEYWORDS`) · `fin2/tests/test_report_lines_inline_xbrl_overlay.py::test_overlay_tax_expense_oci_after_tax_label_excluded` |
| R144 | 사용자 지시 2026-09-19("문제 20개 확인해서 수정까지 진행해" — 캠페인 fail 20건 근본원인 조사) · `fin2/extract/report_lines.py::_emit_eps_lines()`(반환 라벨집합·`header_cols`·위치보존)·`::_emit_section_lines()` · `parser/common/amount_normalizer.py::strip_cell_whitespace()` · `parser/xml/table_extractor.py::_split_label_amounts_ex()` · `fin2/tests/test_report_lines_r144_eps_dup_and_cell_linebreak.py` |
| R145 | 사용자 질문 2026-09-19("섹션을 본다면서 왜 다른 섹션 항목이 EPS 로 오분류되나") · `fin2/extract/report_lines.py::_is_eps_label()`/`_in_eps_section()`/`_indent_stack_paths()`/`_emit_eps_lines()`(`section_path` 부여)·`::_emit_section_lines()` · `scripts/scan_eps_section_context_r145.py`(실측 재현) · `fin2/tests/test_report_lines_r145_eps_structural_label.py` · `docs/plans/eps_label_structural_rule_r145_design_2026-09-19.md` |
| R146 | ★**미해결 — 캠페인 종료 후 착수**(사용자 지시 2026-09-19). R144/R145 백필 뒤처진 std_v3 304개사 재빌드 진단 중 발견 · 결함 위치 `fin2/standardize/rules.py::rule_additive_da()`(`_DEP_CANON`/`_AMORT_CANON` 이 `cf.*`/`is.*`/`note.*` 3벌을 단순합산)·`::rule_derive_ebitda()`(전파) · 실측 2,389행/119개사 · 메모리 `stdv3-da-double-count-r146-2026-09-19` |
| 부록 A | 각 행의 파서 docstring(`biz_catalog.py`·`biz_section.py`·`report_lines.py`·`section_detector.py`) |
| 부록 D | rcept 단위 예외목록 카탈로그(`fin2/extract/report_lines.py`에 흩어진 5개 딕셔너리 — R116/R118/R120/R121/R132) |

## 부록 C. 미결 / 위반 현황

| 항목 | 상태 |
|---|---|
| **캠페인 큐 — `status='pass'` 인데 `verified_scopes` 결측 486건** | **✅종결 — 재대조 대상 0건(2026-09-22 재측정)**. pass 총 1,249건 중 486건 결측이고, **전건이 컬럼 신설 이전**이다. `verified_scopes` 컬럼과 `--verified-scopes` 게이트는 커밋 `ed1529a`(2026-09-20 **16:07**)에서 같이 들어왔고, 플래그 없이 pass 된 마지막 건은 **15:31**(두산에너빌리티 `20240327001228`), 플래그를 처음 담은 건은 **16:56:49** 다. 즉 결측 = 컬럼이 없던 시절의 정상 상태이며 부실 근거가 아니다(손대지 않는다). ★**직전 기록의 '24건(09-20 13:05~15:31)은 컬럼이 있는데도 비었다' 는 오판이었다** — 마이그레이션 *파일명*의 날짜로 경계를 `13시경`이라 **짐작**했고, 실제 커밋 시각을 확인하지 않았다. 경계는 `git log -S` 와 `min(reviewed_at) WHERE verified_scopes<>''` 두 가지로 재측정해 일치를 확인했다. 그 오판으로 캠페인 세션에 지시한 24건 재대조는 철회했다. ★교훈: 컬럼 신설 시점은 파일명이 아니라 커밋(`git log -S '<컬럼명>'`)으로 잡을 것. 함께: SK하이닉스 `20191114002661`·두산에너빌리티 `20170811000844` 는 별건으로 이미 8-scope 재대조 pass 완료 |
| **R166 — 라벨 ROWSPAN 둘째 물리행이 유실·오라벨** | **✅수정 완료 · 규모 재측정 필요(2026-09-23)**. 증상 2갈래: 첫 금액 칸이 비면 **행 전체 유실**(이슈#34), `'0'` 이면 **라벨이 `'0'` 인 행으로 오적재**(이슈#35 — 결측이 아니라 오라벨이었다). 수정=**상속 라벨로 별도 행 emit, 병합 안 함**. ★병합안을 만들었다가 SK이노베이션 `20260316000827` 에서 각각 자기완결인 두 변동을 섞어 **날조된 행**을 만든 것을 확인하고 폐기했다(그 병합안은 이슈#35 행을 아예 사라지게도 했다). 전수 55필링/트리거 188행(SCE 위주, 주석 무영향)이나 그 측정은 병합안 기준이라 **재측정 필요** |
| **R165 — SCE 기말잔액 행의 한 셀만 원문 값이 틀림(>1B 오차 146셀)** | **규모파악 완료 · 조치 대기(2026-09-22 사용자 지시 범위 종료)**. 판정=행 항등식 + **BS 이중앵커**. 이 검사에 네 계열이 섞여 든다: sign 1,332셀(R162·R163) · scale 9 · trunc 7 · **other 595(R165 후보)**. other 중 121셀(20%)은 오차 ≤1,000원 = 원문 반올림이라 결함 아님, **>1B 146셀이 실질**. ★**파서 결함 아님** — 표본 120건에서 '원문엔 참값인데 우리가 딴 값' 0건, 최대오차 5건은 SCE 셀 원문 직접 확인(대상 `20160816000038` 은 같은 열 다른 기간 행이 전부 정상값이라 원문 오타가 자기증명). 셀 단위 교정은 `manual_report_lines` 가 스코프를 통째 삭제하므로 R159식 예외목록 설계 필요 — **착수 지시 대기** |
| **R162-d — SCE 행 내부 항등식(지배기업+비지배=자본합계)을 부호 앵커로** | **스캔·증명 완료 · 백필 보류(사용자 결정 2026-09-22)**. R162 의 열 롤포워드 항등식은 전기 블록 잔액 행에 앵커가 닿지 않는다(한화오션 `20160330004251` 4셀 중 1셀만 복원된 이유, camp_run 관찰). 행 내부 항등식은 한 셀을 **유일하게 결정**해 거울 모호성이 없다. 후보 3,903셀/2,398필링(비지배 2,508 · 지배기업 870 · 합계열 525), 열 역할 모호 행 10.9만은 배제. 표본 246셀 중 **63%가 이중증거**(같은 문서에 그 금액이 괄호로 존재), 37%는 앵커 하나뿐. ★R165 의 `sign` 1,332셀은 BS 외부앵커가 붙어 더 강하니 백필 시 우선 후보 |
| **R164 — 처분계산서 가드가 SCE 를 판별 못 해 자본변동표 통째 유실(2015+ 127필링/131표/원문 4,279행)** | **✅수정 완료 · 백필 진행 2026-09-22**. `_looks_like_appropriation` 의 조건②(진짜 재무제표 계정 부재)가 SCE 에서는 **구조적으로 항상 참**이라 `미처분이익잉여금` 열을 가진 SCE 가 전부 버려졌다. 양성 증거(`_looks_like_equity_changes_header`)를 요구해 면제. 발견=캠페인 이슈#30(한화오션 `20170515004751` 별도 SCE 74행). ★`pass` 보호 대상 0건 — 127건 전부 pending/fail 이라 override 불요. 대상 22개사. ★★잔여 119필링/145표는 **R164-b 로 해소**(사용자 승인 2026-09-22): 양성 증거 `_looks_like_equity_changes_header` 의 창을 3행으로 넓히고 `기타불입자본`·`기타자본구성요소` 토큰 추가. 그 술어를 R127·R127b·R148 이 공유하므로 **2015+ 전수 104,533필링 표귀속 diff** 로 검증 — 변화 152필링이 **전부 가산**(원문 5,360행 회복), **소멸 0·제거 0·재배정 0**. 백필 152필링 전부 `pending`(override 불요). 수정 후 잔여는 **2필링/3표/195행**(코스리거글로벌)에서 **종결** — `보통주납입자본`·`기타자본항목` 토큰을 더 넣으면 풀리지만 2필링 때문에 공유 가드를 또 느슨하게 하지 않는다(R6) |
| **같은 물리 표가 두 번 append 되는 서식(2015+ 5필링 17쌍)** | **미결 — 사용자 판단 대기(2026-09-22)**. 표제표/데이터표 분리 서식에서 forward scan 과 정상 분기가 같은 표를 각각 잡는 것을 합성 문서로 확인했다. ★R164 가 만든 것이 아니다(라벨을 무해한 값으로 바꿔도 재현 — 기존 성질). 적재 데이터에서는 같은 (rcept, basis, statement) 안에 서명이 같은 table_seq 쌍이 5필링 17쌍이고 BS/IS/CF 에도 나타난다. ★**원문이 같은 표를 두 번 싣는 경우(정상 전사)와 구분되지 않아 결함이라 단정하지 않는다** — 판정하려면 그 5필링 원문을 열어봐야 한다. 착수 지시 대기 |
| **R162 — SCE 원문 음수괄호 누락(2015+ 프록시 1,209필링/2,552셀)** | **✅수정·백필 완료 2026-09-22**. 교차대조(방향)+열 항등식(자격), 전기 블록은 이월잔액으로 연결(R162-b). 백필 883필링/4,977셀. ★R139 보호 3건은 캠페인 redo 대기(두산에너빌리티 `20170811000844`·효성중공업 `20190515002585`·SK하이닉스 `20191114002661`). 상세 = R162 |
| **R163 — CF 현금 조정 구간 원문 부호 누락(2015+ 61건)** | **✅수정·백필 완료 2026-09-22**. R162 의 자매. 기초+순증감+환율효과=기말 이 깨졌고 단일 셀 뒤집기로 닫힐 때만 적용. ★환율변동효과는 양수가 정상인 경우가 더 많아(114,412셀) 부호만으로는 판정 불가. 잔여 3건은 R139 보호(한화오션 3필링) — 캠페인 redo 대기. 상세 = R163 |
| **R94 후속 census(2026-09-12) — PDF 복구경로(`unit_source='pdf'`) 1999~2002년대 결측, BS/IS/CF 중 하나 이상 통째로 없는 (rcept,basis) 1,585건/7,029건(22.5%)** | **분류 완료, 조치는 미착수** — 사용자 지시("BS/IS/CF 무조건 3개 다 있어야 하는데 없는 경우 조사")로 census. 6개 유형으로 분해 후 표본 원문대조(로컬 XML 텍스트에 해당 statement 제목이 실제로 있는지 직접 확인)로 "정상 결측" vs "진짜 버그" 판별: **정상 결측**(조치 불요) — CF만없음 1,327건(표본 3/3 원문에 "현금흐름표" 0회, 2011년 이전 K-GAAP 연결CF 면제 관행과 일치 — **사용자가 직접 3건 원문대조로 검증 확인**), CF만있음(BS+IS없음) 8건(표본 3/3 원문에 BS/IS 제목 0회). **진짜 버그로 보임**(원문에 제목이 실제로 있는데 0행) — IS만없음 114건(표본 3/3 "손익계산서" 5~8회 등장), BS만없음 24건(표본 3/3 "대차대조표/재무상태표" 1~7회), IS만있음(BS+CF없음) 71건(표본 2/3 원문에도 있음), BS만있음(CF+IS없음) 41건(표본 2/3 원문에도 있음) — 합쳐서 약 250건. ★**오늘 고친 R94(헤더서브컬럼/적자워딩앵커/BS전용부호규칙) 3개 버그와는 별개 원인으로 확인됨** — IS만없음 표본(대한제분 00113243, 20000214000011)에 오늘 코드로 `recover_one()`을 실제 재실행해봤으나 여전히 0행(오히려 `reconcile()`이 HTML경로를 T3로 판정해 자동채택 거부 — 지금 DB에 있는 값 자체가 이 스크립트가 아니라 이전 세션 "Track C 93건" 캠페인 같은 별도 방식으로 적재된 것으로 추정). **★★재실행 주의**: 위와 같이 `recover_one()`을 지금 코드로 무작정 재실행하면 T1 미만은 거부되므로, 이미 사람이 검토해 확정한 값(예: 대한제분 consolidated BS+IS)이 오히려 사라질 위험이 있다 — 손대기 전 그 값들이 어느 캠페인/스크립트로 적재됐는지부터 확인 필요. 다음 세션 착수 시: 진짜 버그로 보이는 ~250건(특히 IS만없음 114건, annual 24건 포함 — annual에 IS 없는 건 K-GAAP 이라도 절대 정상일 수 없음)부터 원인 규명. **표본 3건 추가 원문대조 결과(2026-09-12, 사용자 지시로 착수 후 중단) — 이 ~250건은 단일 원인이 아니다**: ①세명전기(00133751, 20000328000070) — `CLASS="NON-EXTRACTION"` 구식 표가 라벨 13개·값 13개를 각각 구분자 없이 한 셀에 통째로 이어붙임(오늘 R94와 무관한 완전히 다른 파싱 문제, 콤마도 안 믿을 수 있어 단순 split 불가). ②경방(20010328000207)·신원종합개발(20020330000952) — R92 손상감지가 못 잡는 **별개의 mojibake 인코딩 손상**(COMPANY-NAME 등이 "寃쎈갑"/"ſհ"류로 깨짐, 리터럴 '?' 는 2개뿐이라 R92 임계값 밑) — EUC-KR을 UTF-8로 잘못 읽은 것으로 추정, 원문에 재무제표 키워드가 전부 0회. **★★★사용자 지시로 스코프 확정(2026-09-12): 현재 캠페인은 2015+ 전용이다 — 이 1999~2002년대 전체(1,585건, 위 ~250건 포함)는 명시적으로 스코프 밖. 별도 세션에서 착수할 것, 지금 당겨서 하지 말 것.** ★2015+ 스코프 재확인: `unit_source='pdf' AND report_fiscal_year>=2015`인 (rcept,basis)는 전사에 **솔트웨어 20220802000208 딱 1건뿐**이고 이미 BS+IS+CF 전부 정상(R94로 완결) — 즉 R94는 2015+ 스코프 안에서는 완전히 마무리됨, 이 census와는 무관. ★후속(같은 날, 별도 세션): `scripts/reload_report_lines_2015plus_2026-09-12.py` 전사 재적재가 이 필링을 매번 다시 XML로 시도해 "손상 의심" 경고를 반복 출력하는 것 확인(재다운로드도 바이트 동일 재현 — DART archive 자체 손상 확정, `download_tasks.last_error`에 기록됨). 사용자 지시로 **개별 확인된 이 필링 하나만** `_CONFIRMED_NON_XML_RCEPTS` 목록으로 재적재 대상에서 제외(★`unit_source='pdf'` 전체를 일괄 제외하지 않음 — 회사/문서 단위로 확정된 것만 하나씩 추가하는 방식). |
| **R91 부수발견 — `filings_isfinal_grain_duplicate` 38건(태그 없는 첨부정정 그레인 미병합)** | **미조치** — 대부분 `[첨부정정]`(원본과 며칠 차)이 제목에 "(YYYY.MM)" 없어 `period_end_date=NULL`로 남고, 태그 있는 형제(원본)와 그레인이 영영 갈라져 둘 다 `is_final=True`. R91의 §1 수정(정정본 CORRECTION 섹션 재확인)은 `_is_amendment`(기재정정)만 트리거해 이 38건 대부분(`_is_attachment_amendment`)엔 안 걸림 — 별도 트리거 확장 또는 그레인키 자체 재설계 필요. 휴면 기업이면 데일리 사이클로 자연 재실행 안 됨(`relabel_corp_filings()`는 그 corp가 그날 새 필링을 냈을 때만 재호출) — 백필 스크립트 별도 필요. `scripts/dq_assertions.py::filings_isfinal_grain_duplicate`로 상시 감시 중 |
| **`report_tables.declared_unit` 이 표의 첫 행 adecimal 로 유도돼 IS 에서 오염** | **미조치(잠복)** — `store_report_tables()`(`fin2/extract/report_lines.py:1408`)는 그 표에서 **처음 만난 행의 `adecimal`** 로 `declared_unit` 을 정하는데, IS 는 EPS 행(`_emit_eps_lines`, `adecimal=0`)이 먼저 방출돼 **백만원 표가 `declared_unit=1`(원)** 으로 적힌다(2026-09-09 실측: 삼성전자 `20260814003699` IS 별도·연결 둘 다. 행의 `adecimal` 은 정상 `-6`). 현재 이 컬럼을 **읽는 프로덕션 소비자가 없어**(전수 grep 확인) 실피해는 0 이지만, 앞으로 누가 '표의 단위' 를 여기서 읽으면 조용히 틀린다. 계층2 검토 CSV(`fin2/extract/review_csv.py`)와 검산(`fin2/audit/layer2_selfcheck.py::row_unit`)은 이 컬럼 대신 **행의 `adecimal`** 을 쓴다 — `value_won` 을 만든 바로 그 값이라 표시금액과 어긋날 수 없기 때문. 고치려면 `store_report_tables` 를 최빈 adecimal 기준으로 바꾸고 R8 대로 전수 백필 필요 |
| ~~R44 — DRB동일(00118266) controlling_ni 자체는 여전히 fail_b(미해결)~~ | **✅ 해소 완료 2026-08-25 — R45**. `_resolve_ni_attribution()`에 net_income 앵커(계속+중단 총계 합산, 자체 교차검증 내장, EBT−tax보다 먼저 시도)를 신설해 근본수정. 18,327,708,908(오답)→29,912,789,124(정답), 원문 항등식+face_audit 독립 리더로 이중 검증. 1,440개사 소급 백필+Gate B 재감사까지 완료. R45 항목 참고. 부수 발견 (c)(bare `"...에게 귀속되는 지분"` 라벨의 bare-지배지분 가드 우회)는 R45 범위 밖 — 여전히 미착수(아래 신규 항목과 별개) |
| **P3-1 "원인 A" — 처음으로 전수 재처리(`fy=all`)된 회사가 R16~R32 등 그동안 표적백필로만 적용되던 규칙변경분을 한꺼번에 맞아 값이 흔들림** | **부분 조치(2026-08-20, R35)**. 실측(2026-08-19 재감사): 689건 단조성 위반 중 R34(depth결함) 30건을 뺀 668건을 field 단위로 재분해하니 실제로는 성격이 다른 3그룹(감사기 커버리지 공백 527건/56개사 · 진짜 값불일치 의심 51건/13개사 · Track A/B 자체가 못 읽는 문서 87건/8개사)이었다. **감사기 커버리지 공백 그룹만 R35 로 해소**(382건 pass 회복, DB 반영 = 74개사 `--recheck`). 나머지(값불일치 51건 + 미판독 87건 + 잔여 pending)는 **여전히 미조치 — 별도 트랙**. 원 트리거(8/18 `build_std_v3.py` 전체이력 재생성 2,128개사)는 여전히 유효한 구조적 재발 경로 — 메모리 `gateb-full-reaudit-is-required-to-close` 그대로. 다음 착수 시 `face_audit_snap_20260819` 를 기준선으로 재사용 가능 |
| **R34 depth-우선 결함 — 30건(6개사) 밖의 잠복 사례 미조사** | **미조치**. 코드 수정(`_resolve()`)은 전역 적용되나, 이미 저장된 std_v3 값 중 "정정본이 section_path 다르게 재렌더링 + depth 우선으로 원본이 이김" 패턴이 P3-1의 689건 밖(=이미 예전부터 fail 이던 회사)에도 있는지는 전수 조사 안 함. 필요 시 `scripts/investigate_p3_depth_bug_census.py` 를 `face_audit` 필터 없이 std_v3 전체 corp 로 확장해 재실행 |
| ~~T22 순수 하이픈 음수(`-N`) `_NUMBER_PATTERN` 미인식(T21 자매결함)~~ | **✅ 해소 완료 2026-08-17** — R31. 775개사 표적 백필+검증 완료. 부록A T22·부록B R31 참고 |
| R2-1 `biz_metrics`·`order_backlog` 가 정본 정책 미적용 | **미조치** — 547건(447개사) 미파싱, 505건 회수 가능. 2026-07-31 백필 완료 후 착수 예정 |
| ~~R1 '사업의 내용' 이 계층2 를 우회~~ | **✅ 해소 완료 2026-08-09** — `biz_section_tables` 4도메인 공용화+재배선. R1 본문 참조. |
| **셀 병합 결함(`biz_metrics` 한정)** | **✅ 조치 완료 2026-08-01** — 아래 T14 참조. `biz_section.py`(사업의 내용) 전용, 이상치 2,599행 → **162행**(94% 제거) |
| ~~note_lines/SCE 본문행 ROWSPAN/COLSPAN 미확장(= 단위(배수) 오귀속의 실제 원인)~~ | **✅ 전체 완료 2026-08-08**(코드+검증+DB 반영, Phase 1~4) — R11/R11-1/R11-2 참조. `expand_table_grid`+`_grid_header_split`/`_grid_body_rows` 신설·배선. 원인·규모는 `docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md` §9~§10 확정: 전수 재파싱 실측 11.48%(2,819만 개) 컬럼 오귀속이지만 **값 자체가 무의미해지는 건 0.24%뿐**(비금액 열 배수 오적용) · 회수가능 누락 0.75% · 나머지 **89.6%(전체 값의 9.25%)는 크기는 맞고 열 정체(당기/전기 등)만 틀림**(`label_diff`, `note_periods`/`units.py` 기간·배수 판정에 영향). **본문(BS/IS/CF)은 실측 0건**(§10, 코드 경로가 달라 ROWSPAN 이어짐이 `_split_label_amounts`에서 자동 흡수됨 — 재적재 불필요, F1 회귀 가설도 기각). 전수 재검증(101,327건) 프로덕션 결함 0건(원래 28,189,281개→0). **진행 중 R11 자체의 새 회귀 2종 발견+수정**(R11-1: 헤더판정실패 폴백 offset=0, note 348,099셀/1,629필링→480셀/107필링, 잔여는 R11-2로 정상 분류). **Phase 4(2026-08-08) — note_lines 전량 재적재 완료**(245,452,947→247,244,387행, +0.73%) + std_v3 재빌드(184,298→184,580행) + 재검증(DB 직접 대조 텔코웨어·풍강 값 일치·Gate B `line_value_diff=0`·D&A DB 재확인) 전부 통과. 상세 = `docs/plans/note_span_fix_plan_2026-08-07.md` |
| 계정별 예외단위(자본금류, `report_lines`) | **미조치·미재검증** — 에스티아이 사례(자본금류 계정이 표 선언 배수 무시하고 원 단위 그대로 표기) 위 ROWSPAN 결함과 별개로 남아 있음. 상세 = `docs/qa/handoff_unit_multiplier_misattribution_2026-08-07.md` §4-2 |
| 캡션 상속(연속표) 회수율 | 미측정 |
| `가. 매출유형별 매출액` 류 캡션 | `sales_section`·카탈로그 모두 미포착(실측 나무에이엑스). 캡션 규칙 확장 대상 |
| pre-2015 구서식 | 카탈로그 미검증 |
| ~~특수건설 20151116001903 — 제목+데이터 병합 표~~ | **✅ 조치 완료 2026-08-05** — R4-2 참조. 같은 census 로 팬엔터테인먼트 20181114002948(병합표)·포시에스 20171114002836(BS 위치+계정명)도 함께 해결(활성기업 398건 전수 재검사, 오적용 0건) |
| ~~R8 위반 3연속 — `face_audit` source_version PK 확장(2026-08-11) 이후 소비자 4곳 중 3곳 미배선(`standard_financials` 뷰·`run_dq_gate`·`app/data/trust.py`)~~ | **✅ 해소 완료 2026-08-18** — 뷰는 v2/v3 감사행이 조건 없이 둘 다 매치돼 행 2배 중복(244,585키)+등급 오귀속(50,104행)+`fail_a` 게이트 우회(487행)를 일으켰다. 신규 마이그레이션 `2026_08_standard_financials_view_source_version`(`collector/db.py`)로 각 UNION ALL 분기에 `source_version` 조건 명시 → 321,141행 전량 dedup, `gate_b_status` 불일치 0, 은닉 214행 전부 v3 `fail_a`로 설명(미설명 0). `app/data/trust.py`도 `source_version='v3'` 한정. **검증 중 4번째 소비자(`scripts/verify_corp_sequential.py`)도 같은 결함(같은 `args.source` 미배선 `AttributeError` + `rollup_corp()`의 source_version 미필터)임을 회귀 테스트가 실측으로 발견 — 함께 수정.** `run_dq_gate`/`verify_corp_sequential.py` 둘 다 자신이 직접 만든 `std_financials_v2`를 감사하므로 `source="v2"`(v3 아님 — v3는 별도 수동 배치 `scripts/build_std_v3.py`만 채움, v3로 두면 신규 수집분이 v3에 아직 없어 "이상없음" 위양성 그린이 됨). 회귀: `fin2/tests/test_standard_financials_view.py`(뷰 dedup·등급정합·`face_audit` 미배선 소비자 grep 가드). 설계 `docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md`, 적용전후 기록 `docs/qa/view_dup_baseline_2026-08-18.md` |
| Gate B `E4_IDENTITY` 서브경로 미분해 | **미조치** — 3,600건이 4개 경로(revenue=cogs+gp / NI=CF대체 / NI=지배+비지배 / R32 업종파생)로 뭉쳐 있어 저장값만으로 못 나눈다. 설계서 C안(약한 근거 통과를 `pass` 로 불인정) 평가의 선행조건. R33 참고 |
| Gate B 게이팅 축(track vs evidence) 재검토 | **보류(조건부 재개)** — 2026-08-18 A′ 채택으로 track 축 유지. `M2_WEAK` 또는 `E5_HEURISTIC` 가 전수 재감사에서 1건이라도 관측되면 재개(트리거 SQL = R33). 현재 둘 다 0건 |
| R43(포괄이익/포괄손실 가드) — std_v3 소급 백필·Gate B 전수 재감사 | **✅ 완료 2026-08-25** — 254개사 드라이런(트랜잭션 rollback)으로 실 영향 48개사/265행 확인 후 22건(값→다른값) 전수 원문대조 검증(항등식 controlling_ni+noncontrolling_ni=net_income 다건 정확 일치 확인, KB금융 등) → 실 커밋(`build_std_v3.py --corp <254개사>`, 27,846행) → `gateb_audit.py --recheck`. 전이: fail_a 회귀 **0건**, fail_b→pass 22건·fail_b→pending 17건(개선), pass→fail_b 1건(신규, 아래 별도 항목) |
| ~~신규 발견(R43 재감사 중) — "계속영업" 귀속 라벨이 "중단영업" 자매가드(2026-08-23)에 안 걸림~~ | **✅ 해소 완료 2026-08-25 — R44(라벨가드)+R45(근본수정)**. 위 R44 항목 참고 |
| ~~신규 발견(R45 Gate B 재감사 중) — `fin2/audit/face_audit.py` 독립 리더가 R45와 같은 계열의 net_income 스코프 오판을 별도로 안고 있을 가능성~~ | **부분 해소 완료 2026-08-26 — R46**. 247건 원문실행대조로 파급범위 확정(1건→247건, is.controlling_ni 전용): 171건(26개사)은 `_with_ni_attribution_text_fallback()`의 스킵게이트 결함(근본원인은 R45와 무관, `account_mapper.py` 오매핑 경로 2변종)으로 확정·수정·Gate B 재감사(fail_a 회귀 0건) 완료. R46 항목 참고 |
| **R47(신규, R46 조사 중 발견) — `face_audit.py` TE/TD 구조인식 함수의 사각지대(01137383 등 70건)** | **완전 해소·Gate B 전수 재감사로 검증 완료 2026-08-27 — 70건 전부 설명 완료(코드 수정 66건 + 기존 문서화된 형태게이트 한계 2건 + face_audit.py 무관으로 확정된 std_v3 upstream 오류 2건)** — R47-a(22건, ACODE 없는 TE)→R47-b(24건, 앵커 정규식 접두/순손실)→R47-c 재조사(19건 중 13건 앵커 정규식 추가보강, 나머지는 R47-a 한계 1건+R47-d로 재귀속+아래 2건 중 1건)→R47-d(8건, ACONTEXT 없는 XBRL 방언) 순으로 4단계 순차 해소. **Gate B 전수 재감사**(`gateb_audit.py --source v3 --recheck`, 2,527개사·fy≥2010·245,761행·기업오류 0) 결과 `is.controlling_ni` fail 6건만 잔존, 전부 사전 설명과 정확히 일치(00152127·01137383 2024Q3·00363769·00136925 = fail_b, 형태게이트 한계/NO_XML_FILE 기존 케이스; **00201432·00124504만 fail_a — R47 착수 전부터 이미 fail_a였던 바로 그 2건과 동일, fail_a 회귀 0건 확인**). `is.noncontrolling_ni` fail 0건. **재조사 결과 00201432·00124504(원래 fail_a 2건)는 face_audit.py 버그가 아니었음이 확정됨** — `face_audit.fail_detail`의 `report_won`이 이미 원문 XBRL ACODE(`ProfitLossAttributableToOwnersOfParent`)와 정확히 일치하는 진짜 정답이고, std_v3의 `db_won`이 오히려 **총포괄손익 개념**(`ComprehensiveIncomeAttributableToOwnersOfParent`)을 잘못 채택한 것 — face_audit.py는 이미 정확히 fail_a로 잡아내는 중이었다. `account_mapper.py`의 "맨몸 지배지분 라벨 가드"(187~227줄, 2026-08-22 도입)가 오늘 코드로 검증한 결과 두 문서의 실제 오염 라벨을 이미 정확히 차단하므로, 두 필링(rcept 2025-05-15/2026-03-18, 둘 다 가드 도입일 이전) 모두 **재표준화 미반영 stale 값일 가능성이 높음** — `build_std_v3.py` 재빌드로 해소 여부 확인 필요(DB 쓰기라 사용자 확인 후, 미착수). 코드: `fin2/audit/face_audit.py`(스킵게이트+앵커정규식+ACONTEXT 게이트 3종 수정), 테스트 15건 신설(`fin2/tests/test_ni_attribution_text_fallback.py`). 매 단계 연결기준 PASS 300건 결정론적 스모크 회귀 0건 확인. **R47-a(§2-B, ACODE 없는 TE)** — `_ni_attribution_text_candidates()`의 스킵 조건을 "TE 있으면 skip"→"**ACODE 있는** TE가 있으면 skip"으로 좁히고 셀 추출도 `tr.findall("TD") or tr.findall("TE")`로 확장(22건 전수 실측 결과 라벨/값 혼재 없이 균일하게 ACODE 전무 — 부분오염 위험 없음 확인). **적용 결과 21/22(95%) 해소**(production reader 재실행 db_won 일치 확인) — 잔여 1건(01137383 2024Q3)은 귀속 섹션 안에 계속/중단영업 세부분해 행이 끼어 "지배/비지배 정확히 1개씩" 형태게이트가 실패하는, `_ni_attribution_structural_candidates()` docstring 에도 이미 문서화된 **기존 한계**(코렌텍 사례와 동일 메커니즘, R47 무관) — 별도 트랙 필요시 개설. |
| **R47-b — 앵커 정규식(`_NI_TOTAL_RE`) 불일치(34%, 24/70건)** | **✅ 해소 완료 2026-08-26** — TE판·TD판이 공유하던 정규식 `^당?(기|분기|반기)순(이익|손익)`이 실제 라벨 변형(로마숫자/번호 접두 `"XⅢ."`(ASCII 'X'+유니코드 'Ⅲ' 혼용 표기 포함)·괄호번호 `"(1)"`·`"연결"`/`"별도"` 등 개체 접두·`"순손실"`(이익\|손익 대안에 없어 원천 미매치, 서희건설 00219848 실측))을 다수 놓쳤다. `_is_ni_total_anchor()` 헬퍼 신설 — 앵커 매칭 전 접두사(번호/개체)를 벗겨내고 `순(이익\|손익\|손실)`로 확장, `^`-앵커 자체(법인세비용차감전순이익 등 상위 소계가 앵커를 잘못 여는 걸 막는 R24 안전장치)는 유지. TE판·TD판 양쪽 호출부 배선. 24건 전수 실측 100% 해소(production reader 재실행 db_won 일치), 연결기준 PASS 300건 전수 회귀 스모크 0건(기준선과 동일 300/300), EBT 소계 오채택 방지 테스트 포함 회귀 테스트 3건 신설 |
| **R47-c — `_detect_body_statement_tables()` 스코프 미스로 분류했던 19건** | **재분류 완료 — "스코프 미스"는 오판정이었음(방법론 결함), 진짜 원인 3갈래로 재해소** — 최초 진단 스크립트가 "지배"-라벨 행을 문서 전체에서 **첫 매치만** 찾고 멈춰, "1. 요약재무정보" 데코이 표(첫 매치, 스코프 밖 — 의도된 배제)에서 멈추고 그 뒤 진짜 본문표(IS_C/IS_S, `_detect_body_statement_tables()` 반환 집합 안)에 있는 두 번째 매치를 못 봤다 — **19건 전수 재확인 결과 예외 없이 전부 본문표 안에 정답이 있었다**(스코프 미스는 0건). 진짜 막힌 이유는: **①앵커 정규식 추가 변형 2종**(아래 보강으로 13건 해소 — "괄호 별칭" `"당기(분기)순이익(손실)의 귀속"`(심텍홀딩스 00152127 실측)과 "기간어 없는 재오픈" `"순이익의 귀속"`(TOTAL 행 매치 후 OCI 거쳐 총포괄 CLOSE 된 뒤 별도로 다시 나오는 헤더, 삼영 00127255 실측) — `_NI_TOTAL_RE`에 `(?:\([^)]{1,6}\))?` 및 `^순(?:이익\|손익\|손실)의\s*귀속` 대안 추가, `법인세비용차감전순이익` 등 EBT 오채택 방지 회귀 테스트 포함), **②R47-a 스킵게이트가 정확히 의도대로 작동한 4건**(TE 자매행에 ACODE 있어 defer 했으나 그 자매행이 R47-d 방언(ACONTEXT 없음)이라 결국 침묵 — 진짜 원인은 R47-d, 아래), **③R47-a에서 이미 문서화된 "섹션 내 지배-라벨 서브라인" 형태게이트 한계 1건**(00152127: "지배기업의 소유주 귀속 당기순이익"처럼 값 없는 서브라인도 "지배" 부분문자열을 포함해 `cni` 멤버가 2개로 늘어 1:1 게이트 실패 — 01137383 2024Q3와 동일한 기존 한계, R47 무관). **미해결로 남겼던 1건**(00201432) — 재조사 결과 face_audit.py 무관(std_v3 upstream 오류)으로 확정, 위 R47 상단 요약 참고 |
| **R47-d — ACONTEXT 없는 XBRL 방언(8건, 4→8 확대 확인)** | **✅ 해소 완료 2026-08-26** — ACODE 는 있으나 별도 ACONTEXT 속성이 없고 컨텍스트/축/단위 정보가 ACODE 문자열 자체에 파이프(`concept\|context_axis\|decimals\|unit\|`)로 붙어 있는 필러 방언(01137383 카카오게임즈: 문서 전체 `TE[@ACODE]` 4,016개 전수 확인 결과 별도 ACONTEXT 속성 0개; `entity{corp}_udf_IS_...` 회사확장 ACODE 필러 다수 포함). `parse_acontext()`가 이 형식을 못 읽어 TE 구조함수가 침묵하는데, R47-a 스킵게이트가 "ACODE 있으면 skip"(ACONTEXT 유무는 안 봄)이라 TD/text 함수도 defer한 채 결국 양쪽 다 못 찾음. **수정**: 스킵 조건을 TE 자매함수의 실제 채택 기준(`ACODE and ACONTEXT` 둘 다)과 정확히 동형으로 맞춤 — ACONTEXT 없으면(방언이든 미태깅이든) TD 처럼 물리 컬럼 위치로 직접 읽는다(R47-a 폴백 재사용, XBRL 경로 새로 안 태움). 8건(원래 4건 + R47-c 재조사로 4건 추가: 00761059·00876908·01061558·00545929) 전수 production reader 재실행 100% 해소, 연결기준 PASS 300건 결정론적 스모크 회귀 0건. 회귀 테스트 1건 신설 |
| **R48(신규, R46 조사 중 발견) — `account_mapper.py` 방향성/개념 교차 오매핑 2건(controlling_ni 스코프 밖)** | **미조치** — (a) `"지배회사지분순이익"`이 fuzzy로 **is.noncontrolling_ni**에 오매핑(방향까지 틀림, 알루코 00117027 실측), (b) `"지배기업소유주지분 합계"`(BS 자본총계 개념)가 is.controlling_ni(IS 개념)에 오매핑. 둘 다 R46 조사 중 부수발견, 파급범위 미측정 — 별도 트랙 필요 |
| **R49(R47 조사 중 발견) — std_v3 controlling_ni 에 총포괄손익 값이 잘못 채택된 필링 2건** | **✅ 해소 완료 2026-08-27** — 최초 가설("재표준화 미반영 stale 값")은 `build_std_v3.py --corp 00201432,00124504` 재빌드로 **반증**(값 불변). 원문 대조로 서로 다른 진짜 근본원인 2건 확정: **버그A**(00201432 비츠로시스 2025Q1) — 같은 날 최초신고(오류값)+기재정정이 났는데 정정본이 이 라인 라벨을 "지배기업의 소유주에게 귀속되는 당기순이익(손실)"→"지배회사순이익(손실)"로 바꿔 실었고, 이 새 라벨이 `is_accounts.py` alias 미등록이라 `combine.py::build_merged_lines()`(1372줄, cell-identity 키에 label_raw 포함)가 최초신고의 오류값을 "정정 안 건드린 별개 셀"로 오인해 그대로 확정. **버그B**(00124504 포스코인터내셔널 2025FY) — 원문 IS표의 "당기순이익의 귀속:"(정답)과 "총포괄이익의귀속:"(오답) 두 섹션이 완전히 동일한 bare 라벨("지배기업소유주")을 쓰는데, `report_lines`(Layer2) 추출 시 두 번째 섹션 헤더가 `section_path`를 못 갱신하고 첫 섹션 값을 물려받아(원인은 `parser/xml/table_extractor.py:336` `_first_cell_indent()`가 반각/전각 스페이스를 동일 취급 — 이 문서 헤더행이 반각으로 오기재됨) `build_merged_lines()`의 cell-identity가 두 섹션을 충돌시킴. **"근본해결" 재검토**(사용자 지시) — Layer2 반각/전각 재가중(B1)과 구조적 폴백 단독멤버 확장(A3, 신규검토)을 원문 실측으로 검증한 결과 **둘 다 기각**(반각 스페이스가 전각보다 흔함[597/599 문서]/실제 오탐 사례 발견[OCI 재분류 소제목이 controlling_ni 후보로 주입됨]). **적용한 수정**: (1) `is_accounts.py`에 원문 대조로 안전 확인된 relabel 변형 3종만 등록("지배주주지분순손실"은 01137383에서 총포괄 섹션에 재사용되는 게 확인돼 **의도적으로 제외**). (2) `combine.py::build_merged_lines()`의 같은-rcept 내부 중복 처리를 "필링 종류(최초/정정)"가 아니라 "현재 셀 점유 rcept와 동일한지"로 대칭화 — 단, 전 statement 무제한 적용은 실측으로 6,958개 기간에 영향(무관한 레거시 BS/SCE 라벨충돌까지 건드림)을 확인해 **스코프를 IS+'순이익'/'순손실' 섹션+'포괄' 제외+라벨에 '지배'/'비지배' 포함으로 한정**(00126089 DH오토넥스의 무관한 '계속사업손익' 충돌도 실측으로 제외 확인). 검증: 6개사(00201432·00124504·00367695·00389970·00540605·00795135) 재빌드+Gate B 재감사 — fail_a 0, 무관 fail_b 4건(00367695, 기존 결함)만 잔존. `pytest fin2/tests/ tests/` 632 passed(무관 기존실패 1건 제외). **사용자가 `scripts/run_gateb_audit_parallel.sh`(5-shard, fy≥1999, 전체 corp)로 전수 재감사 직접 실행 완료** — `is.controlling_ni` fail_a **전사 0건**(00201432·00124504 포함 회귀 없음) 확인. DB 직접 조회로 fail(REVIEW) 14건 전수 확인: 4건은 R47 종료 시점 기존 문서화 한계(00152127·01137383 2024Q3·00363769·00136925)와 정확히 일치, 나머지 10건(00114792 3기간·00139764 7기간)은 A1/B2 트리거 조건(신규 alias 라벨 문자열, same-rcept 중복+지배/비지배 라벨) 자체가 이 두 회사 데이터에 존재하지 않음을 SQL로 확인 — R49와 무관한 기존 이슈, 등급도 fail_b(REVIEW)로 동일 수준. **R49 트랙 완전 종료(2026-08-27).** 설계문서 `docs/plans/r49_controlling_ni_cell_identity_design_2026-08-27.md` |
| **R50(R49 종료 직후 발견) — Gate B fail_a 482건 백로그 클러스터A(cash)·B(두산밥캣 FX) — 둘 다 `face_audit.py`/`concept_map.py` 검증기 갭, std_v3 은 정답** | **✅ 해소 완료 2026-08-27** — R49 종료 직후 fy≥1999·`is.controlling_ni` 외 필드 fail_a 482건 트리아지(cash 324건 67%·두산밥캣 21건 특이케이스·잔여 클러스터C ~137건 미착수). **클러스터A(cash)**: std_v3 cash 는 `report_lines`(라벨텍스트)→`account_mapper`→`account_maps/bs_accounts.py`("현금및예치금"→`bs.cash_deposits_combined`, 2026-07-18 기존 별칭) 경로로 정답을 내는데, `face_audit.py`의 독립 XBRL 검증(`read_report_face_xbrl`)은 `fin2/taxonomy/concept_map.py`(ACODE→canonical, 라벨과 무관한 별개 사전)만 보고 이 사전엔 금융업(증권/캐피탈/지주) 확장개념 `dart_CashAndDuefromBanks`("현금및예치금" 결합라인)가 없어 canonical 미매핑→cands 누락→VALUE_DIFF 오탐(한국금융지주 00432102 2023FY 별도 원문대조로 확정, KB금융·iM금융지주 등 클러스터A 31개사 원문에서 공통 ACODE 확인). 2026-08-22 P1C-2(cash+deposits identity 우회체크, `face_audit.py:1485`)는 이미 있었지만 `by_canon["bs.deposits"]`가 concept_map 갭 때문에 애초에 안 채워져 무력화돼 있었음. **수정**: ① `concept_map.py`에 `"dart_CashAndDuefromBanks": "bs.cash_deposits_combined"` 등록. ② P1C-2 게이트를 `dep_vals` 없어도 `combined_vals`가 val 과 직접 일치하면 PASS하도록 완화(exact-won 만 허용). **클러스터B(두산밥캣 01032486)**: 연결재무제표가 USD 표시(R25/2026-08-15 기존 발견)라 정상대조 불가·PENDING 처리해야 하는데, `face_audit.py:1134` `_FX_PRESENTATION_CURRENCY_KEYS`(매 분기 수동 갱신 필요한 정적 카탈로그)에 신규 필링 기간 **2026 H1이 누락**돼 정상대조 경로로 떨어져 21개 필드가 동일 비율(~1541배, USD를 원화로 착각)로 fail_a. std_v3 값(`total_assets=13,590,943,000,000`)은 [[p2-2026-08-19-doosanbobcat-anam-zero-rows-rootcause]]에서 이미 원문대조 확정된 정답 그대로(재퇴행 아님). **수정**: 카탈로그에 `("01032486", 2026, "H1", "consolidated")` 1행 추가(2026 Q3 도 같은 이유로 재발 예정 — 다음 분기 카탈로그 확인 필요, 구조적 일반화는 과우회 위험으로 비채택). **검증**: `pytest fin2/tests/ tests/` 632 passed(무관 기존실패 1건 제외, 회귀 0). 영향받은 31개사(cash 30사+두산밥캣) `gateb_audit.py --source v3 --recheck` 재감사 — DB 전체(fy≥1999, v3) fail_a **482→170(−312, −65%)**, std_v3 재백필 전혀 없이 검증기 수정만으로 달성. 잔존 fail_a 12건 중 8건은 cash 이지만 클러스터A와 다른 원인(00245472=1000배 단위스케일 버그, 00148832 제주은행=db<report 반대방향 패턴 — 별개 미착수 이슈로 분리), 4건은 net_income/dividends_paid(클러스터 무관 기존 이슈). **잔여 클러스터C(~137건, trade_payables/dividends_paid/revenue/inventory 등 산발)는 미조사** — 다음 세션 과제. 설계문서 `docs/plans/gateb_482_backlog_cluster_ab_design_2026-08-27.md` |
| **R51(R50 후속, 클러스터C 착수) — 포스코스틸리온(00155258) `bs.total_equity` 14건 — `_reduce_conflict()` shallow-depth 휴리스틱이 EquityAndLiabilities-shaped 라인을 지분으로 오채택** | **✅ 해소 완료 2026-08-27** — 최초 설계(`account_maps/bs_accounts.py`에서 `"총자본"` alias 통째 제거)는 **구현 직후 회귀로 반증**: 00369657(리노공업) 2026H1은 "총자본"이 **유일한** equity 라인(ACODE=`ifrs-full_Equity`, section_path='자본')이라 alias 제거 즉시 total_equity가 NULL로 깨짐(즉시 원상복구, DB diff로 원상태 확인). 같은 한국어 라벨 "총자본"이 필자마다 다른 XBRL 개념을 가리킨다는 게 실측으로 확정됨: 포스코스틸리온은 `ifrs-full_EquityAndLiabilities`(=자산총계, 오답)로, 리노공업은 `ifrs-full_Equity`(정답)로 쓴다 — 라벨 텍스트만으로는 두 용법을 구분 불가. **진짜 근본원인**은 alias 등록이 아니라 `fin2/layer3/combine.py::_reduce_conflict()`의 "얕은 section_path-depth 우선" 휴리스틱: 포스코스틸리온 원문(rcept 20250408001924) table_seq=0 안에 자본총계(section_path='자본', depth=1, 385,299,788,248, 정답)와 총자본(section_path=**빈 문자열**, depth=**0**, 556,803,723,173=자산총계와 정확히 동일값)이 공존하는데, "총자본"이 어느 섹션에도 안 속해 depth가 인위적으로 0(=가장 얕음)이 돼 진짜 자본 섹션 값을 이겨버림. **수정**: `account_maps/bs_accounts.py`의 "총자본" alias는 그대로 두고(리노공업 보존 필수), `fin2/layer3/combine.py`에 `_degenerate_total_equity_row_ids()` 신설 — 기존 `_trust_account_table_seqs()`와 동일 패턴(값 항등성 교차대조)으로, 같은 table_seq에서 `bs.total_equity` 후보값이 `bs.total_assets` 후보값과 **정확히 일치**하면(=EquityAndLiabilities를 지분으로 착각) 그 행을 제외 — 단 그 table_seq에 다른 total_equity 후보가 남아있을 때만(무차입 등 진짜 자산=자본인 회사를 MISSING으로 만들지 않도록 안전장치). `_resolve()`의 trust_seqs 필터와 같은 자리(by_label 그룹핑 전)에 배선. **검증**: 원문 대조로 회사별 라벨 의미 차이 확정(포스코스틸리온 FY2024 report_lines 직접 조회 — 자본총계 depth=1/총자본 depth=0 실측), `pytest fin2/tests/ tests/` 632 passed(무관 기존실패 1건 제외, 회귀 0), 영향 3개사(00155258·00369657·01150515) `build_std_v3.py` 재빌드 후 DB diff로 00155258 14건만 정확히 바뀌고 나머지 2개사 무변경 확인, `gateb_audit.py --recheck` 3개사 전부 `is.total_equity` fail_a 0(00155258 face_audit.gate_status 184행 전부 pass/pending, Phase B 라인감사 잔존 fail_a 7건은 EPS단위스케일/RightofuseAssets 등 전부 total_equity 무관 기존 이슈로 확인). DB 전체(fy≥1999, v3) fail_a **170→156(−14)**. 설계문서 `docs/plans/gateb_r51_posco_steelion_total_equity_alias_design_2026-08-27.md`(최초안, 구현 중 반증돼 본문에 pivot 기록 필요 — 다음 세션 갱신) |
| **R52(R51 후속) — `account_mapper.py` 퍼지매칭 결함으로 IFRS15 매출유형별 주석의 COGS/수수료행이 `is.revenue`로 오매핑(revenue H1 2026 21건, 전수영향 최소 47개사/140행)** | **✅ 완전 해소 2026-08-27~28** — 원인 2종: **(a)** exact alias `"수익(매출액)"`(7자)이 IFRS15 매출유형별 주석의 COGS행("재화의 판매로 인한 수익(매출액)에 대한 매출원가" 등)에 부분문자열로 포함돼 `account_mapper.py::_fuzzy_match()`의 짧은-alias 가드(4자 이하만 보호)를 통과, confidence 0.92~0.94로 오매치(실측 291개사/9,698행에 이 라벨 존재). alias 자체는 제거 불가(1,725개사/71,518행이 정확한 매출총액으로 씀, load-bearing). **(b)** "수입수수료"(일반기업 기타수익, 값0인 경우 多)가 보험대리점 전용 alias `"보험판매수입수수료"`(9자)의 부분문자열이라 반대방향 오매치(실측 279개사/3,303행). **범용 가드 임계값 변경은 기각** — 카탈로그 전수스캔 결과 같은 escape-zone(len_ratio<0.65, 4<min_len≤12)에 232개 alias 충돌쌍이 있고, 상당수가 R44~R49(controlling_ni/noncontrolling_ni 귀속 시리즈)에서 이미 세밀히 튜닝해둔 지대와 겹쳐 범용 변경 시 예측 어려운 회귀 위험. **수정**: `fin2/layer3/combine.py::_map_rows()`에 `is.revenue`+`stage='fuzzy'` 후보에만 canonical-scoped 배제 추가 — 라벨에 "매출원가" 포함 시 제외, `matched_alias=="보험판매수입수수료"`인데 라벨에 "보험" 없으면 제외(기존 `_REVENUE_TOTAL_OVERRIDE_CORPS` 등 curated override와 같은 패턴). **검증**: `pytest tests/ fin2/tests/` 632 passed(무관 기존실패 1건 제외, 회귀 0). 원 fail_a 21건의 14개사 재빌드 후 `gateb_audit.py --recheck` 전부 `is.revenue` fail_a 0(회귀 0), 21건 전부 오염값(revenue=cogs 등 오매치값)→NULL로 전환(값 없음이 오염값보다 안전, "결측>오염" 원칙). DB 전체 fail_a 156→135(−21). **미해결 발견(§3-1, 범위 밖)**: 이 수정은 오매핑을 막을 뿐 — 진짜 매출총액 라벨이 콤마구분 복수 각주번호("수익 (주6,22)" 등) 형태라 `normalize_account_name()`이 처리 못 해 그 자체가 unknown 처리되는 별개 갭이 있음(고치면 이 21건이 NULL 대신 정답으로 채워질 가능성, 미조사). **DB 전체 백필 완료 2026-08-28**(사용자 실행, `build_std_v3.py --all --year-min 1999`) — `revenue=cogs` 잔존 시그니처 140행/47개사→**8행/6개사**(잔여는 R52 무관, 2009~2012년 18~34원대 초소액 우연일치). 이어서 `run_gateb_audit_parallel.sh`(5-shard 전수 재감사, 사용자 실행)로 face_audit 갱신 — **DB 전체 fail_a 필드분포에서 `revenue` 완전 소멸(0건)**, fail_a 총건수 135(pass/pending 사이 재배분만, fail_a 순증감 없음, 회귀 0). **R52 트랙 완전 종료.** 설계문서 `docs/plans/gateb_r52_revenue_cogs_note_mismap_design_2026-08-27.md` |
| **R53(R52 후속) — `face_audit.py` inventory/ppe concept_map acode 갭(`ifrs-full_InventoriesTotal`/`ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets` 미등록) — 5개 클러스터로 보였던 fail_a 25건이 사실은 전부 같은 원인** | **✅ 완전 해소 2026-08-28** — [[gateb-session-handoff-2026-08-28]] 인계 시점 fail_a 135건 중 inventory(16)+ppe(9)=25건을 db/report 비율로 재분류하면 스케일 x1,000,000(5)·x1,000(5)·근소한 차이<1%(5)·비율 불규칙 2~6배(8)·report_value=0(2) 5개 클러스터로 갈라져, 처음엔 서로 다른 버그로 보였다. **원문+코드 대조 결과 25건 중 22건이 단일 원인**임이 드러남: BS face 본문의 정답 XBRL fact 가 `ifrs-full_InventoriesTotal`(inventory)/`ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets`(ppe) acode 를 쓰는데(HD현대일렉트릭 01205851·NC 00261443·오션인더블유 00349811·세미파이브 01627363 원문 4/4 확인), `fin2/taxonomy/concept_map.py::ACODE_TO_CANONICAL` 에는 `ifrs-full_Inventories`/`ifrs-full_PropertyPlantAndEquipment`(변형 없는 짧은 acode)만 등록돼 있어 정답 fact 의 `canonical`이 `None`이 되고, `audit_fields()`의 `by_canon["bs.inventory"/"bs.ppe"]` 후보집합에서 아예 탈락한다. 남는 유일한 후보가 그 회사의 주석 상세표 합계행인데, 이 행은 **DART 원문 자체의 렌더러 결함**으로 ADECIMAL 이 잘못 태깅돼 있어(형제 세부 라인은 정확, 노루페인트 00583442 계열과 동일한 함정 클래스) `val in won_vals`가 항상 실패 → VALUE_DIFF 오탐. 정답 후보가 아예 없다 보니 그 회사·필드의 유일한 비교대상인 그 오태깅 행과의 거리(=report_value 와 db 의 비율)만 관측되는데, 이 거리가 우연히 스케일 배수에 가까우면 "ADECIMAL 스케일오독"으로, 우연히 db 에 가까우면 "근소한 차이"로, 전혀 안 가까우면 "비율 불규칙"으로 **보였을 뿐** — 5클러스터 분류 자체가 진단 오류였다(원인 진단에 report_value 근접도를 쓰면 안 된다는 교훈). **std_v3(DB)는 처음부터 정확**(라벨 기반 파서라 이 acode 갭 영향 없음) — 검증기(face_audit.py)만 고치면 되는 문제였다(R50 계열과 동일 패턴). **중요 부수발견**: `face_audit.py`의 기존 주석("`concept_map.py` 소비자=face_audit.py/line_audit.py 뿐, R23")은 **stale** — `fin2/extract/xbrl.py`(운영 `store_facts`, `run.py` 라이브 파이프라인에서 호출)도 이 사전을 쓴다. 그래서 `concept_map.py` 자체는 건드리지 않고, **`face_audit.py` 전용 로컬 alias 오버레이**(`_FACE_AUDIT_EXTRA_ACODE`/`_map_acode_face()`, `map_acode()`가 `None`일 때만 폴백)로 스코프를 감사 모듈 안에 한정했다 — 운영 XBRL 추출 경로 영향 0. **검증**: `pytest tests/ fin2/tests/` 632 passed(무관 기존실패 1건 `test_biz_section.py::test_lxintl_facility_table_dropped` 제외 — face_audit.py/concept_map.py 를 아예 안 쓰는 모듈이라 무관 확인, 회귀 0). `gateb_audit.py --source v3 --recheck` 전수 재감사(5-shard) — DB 전체 fail_a **135→113(−22)**. inventory/ppe 25건 중 22건 pass 전환(스케일 10건 + "근소한 차이" 5건 전부 + "비율 불규칙" 8건 중 7건, 스타코링크 00373571 6건 포함 — alias 하나 추가로 5클러스터 중 4클러스터가 동시에 해소된 셈, acode 기반 오버레이라 애초 표본 4개사를 넘어 일반화). **잔존 3건은 진짜 별개 원인**(이 alias 갭과 무관, 확인됨): 랩지노믹스(00545114) 2025FY consolidated ppe 1건(report_value 가 db 의 약 1/1139, 다른 후보 오염 — 미조사), 광무(00186452) inventory 2건(report_value=0, 후보 완전 누락 — 미조사). 설계문서 `docs/plans/gateb_faceaudit_inventory_ppe_acode_gap_design_2026-08-28.md` |

---

## 부록 D. rcept 단위 예외목록 카탈로그 (2026-09-15 취합)

**배경**: `fin2/extract/report_lines.py`에 "이 필링 하나(또는 이 statement×basis
조합)에만" 적용되는 특정 rcept_no 하드코딩 딕셔너리/frozenset이 늘어났다.
전부 R6 원칙("판정불가면 짐작 금지")을 지키기 위해 **일반 규칙화 대신 예외목록으로
좁힌** 결과물 — 매번 회계항등식 역산 또는 사용자 원문대조로 개별 확정한 값이다.
report_lines DB 자체에는 "이 행이 예외목록을 거쳤다"는 tagging이 없으므로(2026-09-15
확인 — `source_ref`/`unit_source`가 일반 경로와 동일 형식), 이 카탈로그가 유일한
색인이다. 새 항목을 추가할 때마다 여기도 같이 갱신할 것.

### `_Q1_CUM_BLANK_USE_3M_RCEPTS` (R116) — Q1 필링, "누적" 칸 공백 시 "3개월" 값을
누적으로 채택(1분기=3개월=누적 등식 이용)

| rcept_no | 회사 | 기간 | statement |
|---|---|---|---|
| 20160516001490 | 형지I&C | 2016 Q1 | IS |
| 20160511001294 | 드림시큐리티 | 2016 Q1 | IS |
| 20170512001930 | 조광페인트 | 2017 Q1 | IS 별도 |
| 20190527000008 | 자이글 | 2019 Q1 | IS 연결 |
| 20180515002398 | 평화산업 | 2018 Q1 | IS 별도 |
| 20210517001891 | APS | 2021 Q1 | IS 별도 |
| 20150514004898 | 형지I&C | 2015 Q1(같은 회사 다른 rcept·다른 연도) | IS 별도 |

### `_HEADERLESS_MERGE_LAST_IS_CUMULATIVE_RCEPTS` (R120) — 무표지 2열 병합군에서
물리적 마지막 열을 "누적"으로 채택(DART 관행: [3개월 먼저, 누적 나중])

| rcept_no | 회사 | 기간 | statement |
|---|---|---|---|
| 20180814001946 | 웹케시 | 2018 H1 | IS |
| 20200813000621 | 우리기술투자 | 2020 H1 | IS |
| 20150817000794 | 삼성생명 | 2015 H1 | IS 연결(6열 헤더, 무표지 쌍 2개+단일FY열 2개) |
| 20191129000890 | 바이오플러스 | 2019 Q3 | IS 연결(서브헤더 행 자체 누락, 별도는 정상) |
| 20201116001931 | 우리기술투자 | 2020 Q3 | IS 연결(서브헤더가 THEAD 아닌 TBODY에 있어 grid파서 미인식) |
| 20210210000442 | 메이슨캐피탈 | 2021 Q3 | IS **별도**(연결은 정상, 별도만 서브헤더 누락) |

### `_R118_DUPLICATE_PERIOD_LABEL_FIX` (R118) — 헤더가 기간라벨을 중복 오기재,
회계항등식 역산으로 올바른 position→rank 매핑을 개별 확정

| (rcept_no, statement, basis) | 회사 | 교정 내용 |
|---|---|---|
| (20160516002967, CF, consolidated) | 제주은행 2016 Q1 | "제57기1분기" 2회 중복 → position1을 전기(rank1)로 |
| (20230314001271, CF, consolidated) | 제주은행 2022FY | 3중 중복(제62기×2/제61기) → position2,3→rank1 / 4,5→rank2 |
| (20200330004128, IS, separate) | 이노시뮬레이션 2019FY | "제19기" 2회 중복 → position1→rank1 / 2→rank2 |
| (20230515002273, IS, separate) | DSC인베스트먼트 2023 Q1 | "제11(당)기1분기" COLSPAN=2 그룹째 2회 중복 → position2,3→rank1 |
| (20190401000391, CF, separate) | 이랜시스 2018FY | "제1(당)기" 2회 중복(신설법인) → position2→rank1 |
| (20220615000399, CF, separate) | 신영증권 2022FY | "제67기" 2회 중복(첫 그룹이 실제론 제68기) → position2,3→rank1 / 4,5→rank2 |

### `_MANUAL_NO_CONSOLIDATED_FS_RCEPTS` (R121) — 문서에 표는 있으나 그 값이 이
필링의 당기/전기 것이 아님(지주사 전환 이전 시절 데이터 잔존) — 연결 섹션 전체 스킵

| rcept_no | 회사 | 비고 |
|---|---|---|
| 20160520000534 | 더블유게임즈 2015FY | [기재정정]사업보고서 — 제3·4기 연결비대상(사용자 확인) |
| 20160329000657 | 더블유게임즈 2015FY | 정정 전 원본, 동일 이슈 |

### `_MANUAL_UNIT_OVERRIDE_MULTIPLIER_RCEPTS` (R132) — 문서 전체에 걸친 자기모순
단위선언(선언 배수가 실제 자릿수와 10⁶배 어긋남)을 rcept 단위로 강제 교정

| rcept_no | 회사 | 강제 배수 | 비고 |
|---|---|---|---|
| 20180402005173 | 넷마블 2017FY | 1 (원) | "(단위: 백만원)" 선언이 자기모순, 실제는 원(WON) 그대로. 문서 전체(BS·IS·CF×연결/별도) |
| 20191114000246 | 아즈텍WB 2019Q3 | 1 (원) | 자산총계 원문 그대로 114,055,541,787 = 부채비율 주석(천원 단위) 대조 확정 |
| 20210817001851 | HL D&I 2021H1 | 1 (원) | 장기매출채권 원문 그대로 5,178,755,690 = 부채비율 주석(백만원 단위) 대조 확정 |
| 20170814002311 | 동성케미컬 2017H1 | 1 (원) | 유동자산 원문 그대로 363,304,597,206, 회사 규모상 원 단위가 타당 |
| 20241114002786 | 소노스퀘어 2024Q3 | 1 (원) | 유동자산 원문 그대로 61,190,747,942, 회사 규모상 원 단위가 타당 |
| 20230323001157 | 소프트센 2022FY | 1 (원) | 재고자산 원문 그대로 4,334,282,109(43억원), R73(2026-09-06)에서 컬럼시프트만 막고 값은 결측 처리했던 것을 R132 메커니즘으로 완전 복구 |

**R169(2026-09-25)**: 이 6건은 R169 스캔으로 전부 독립 재확정됐다. 수기 목록이 우선 적용되지만, 이제 SCE 에도 적용된다(그전엔 BS/IS/CF 만). 신규 건은 이 딕셔너리가 아니라 R169 데이터파일 `fin2/extract/data/unit_self_contradiction_overrides.json`(스캔이 생성, 87필링 594섹션)에 들어간다.

### 기타 개별 하드코딩 (참고, 위 5개 딕셔너리와 별개 위치)

- `fin2/extract/consolidation_evidence.py::_MANUAL_HAS_CONSOLIDATED_OVERRIDE`
  (R110) — SGA솔루션즈 2건(20151113001023·20160329000826), 순번↔회계연도 매핑
  불가로 텍스트판정을 건너뛰는 영구 예외(사용자가 원문 자산총계 직접 확인).
- `scripts/reload_report_lines_2015plus_2026-09-12.py::_CONFIRMED_NON_XML_RCEPTS` —
  솔트웨어 20220802000208(DART archive 자체 손상 확정, 재다운로드해도 바이트 동일 재현)
  1건. 재적재 스크립트가 이 필링만 XML 재시도 대상에서 제외.
- `fin2/audit/face_audit.py::_FX_PRESENTATION_CURRENCY_KEYS`(R50 클러스터B) — 두산밥캣
  등 연결재무제표를 USD로 표시하는 회사·기간 카탈로그. 매 분기 수동 갱신 필요(2026 Q3부터
  재발 예정 — 다음 분기 확인 필요).

**주의**: 이 카탈로그는 R116/R118/R120/R121·기타 참고 항목까지만 다룬다. R43/R44
(`_REVENUE_TOTAL_OVERRIDE_CORPS` 등 corp 단위 override), R52(`is.revenue` fuzzy
배제) 같은 **corp 단위**(rcept 아님) override는 부록 B의 해당 R번호를 볼 것 —
성격이 다르다(회사 전체에 적용 vs 특정 필링 하나에만 적용).
