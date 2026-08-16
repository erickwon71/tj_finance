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

## 부록 A. 원문(DART XML) 함정 카탈로그

파서를 새로 쓸 때 **반드시** 확인할 것. 전부 실측으로 확인된 것만 적는다.

| # | 함정 | 증상 | 대응 |
|---|---|---|---|
| T1 | **`</TABLE>` 누락** → 문서 전체가 한 표 안에 중첩 | 중첩깊이로 최상위 표를 판정하면 표 **0개** | 자손 TABLE 없는 **잎(leaf)** 만 데이터 표로. 실측 KT&G `20260318001422` |
| T2 | 서술 문단을 **1x1 TABLE 로 감쌈** | 인벤토리 2배 부풀고 **뒤 표의 캡션을 잡아먹음** | 텍스트 블록으로 판정해 캡션 후보로 흡수. 실측 삼성전자 2024(85→37표) |
| T3 | 페이지 레이아웃용 바깥 TABLE 이 실제 표들을 감쌈 | `.//TR` 이 중첩 표 TR 까지 끌어와 거대 오염 grid | `table_direct_rows()` / `_direct_trs()` 사용. 실측 LG 2011(중첩 859개) |
| T4 | **XML 속성 따옴표 미이스케이프** | 조용한 데이터 손실 | `_load_root` sanitize. 실측 성일하이텍 셀 1,143→6,011 |
| T5 | 구형 보고서가 UTF-8 선언인데 실제 EUC-KR | 파싱 실패/깨짐 | 인코딩 자동감지 폴백 |
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
| 부록 A | 각 행의 파서 docstring(`biz_catalog.py`·`biz_section.py`·`report_lines.py`·`section_detector.py`) |

## 부록 C. 미결 / 위반 현황

| 항목 | 상태 |
|---|---|
| R2-1 `biz_metrics`·`order_backlog` 가 정본 정책 미적용 | **미조치** — 547건(447개사) 미파싱, 505건 회수 가능. 2026-07-31 백필 완료 후 착수 예정 |
| ~~R1 '사업의 내용' 이 계층2 를 우회~~ | **✅ 해소 완료 2026-08-09** — `biz_section_tables` 4도메인 공용화+재배선. R1 본문 참조. |
| **셀 병합 결함(`biz_metrics` 한정)** | **✅ 조치 완료 2026-08-01** — 아래 T14 참조. `biz_section.py`(사업의 내용) 전용, 이상치 2,599행 → **162행**(94% 제거) |
| ~~note_lines/SCE 본문행 ROWSPAN/COLSPAN 미확장(= 단위(배수) 오귀속의 실제 원인)~~ | **✅ 전체 완료 2026-08-08**(코드+검증+DB 반영, Phase 1~4) — R11/R11-1/R11-2 참조. `expand_table_grid`+`_grid_header_split`/`_grid_body_rows` 신설·배선. 원인·규모는 `docs/qa/handoff_note_lines_span_misattribution_2026-08-07.md` §9~§10 확정: 전수 재파싱 실측 11.48%(2,819만 개) 컬럼 오귀속이지만 **값 자체가 무의미해지는 건 0.24%뿐**(비금액 열 배수 오적용) · 회수가능 누락 0.75% · 나머지 **89.6%(전체 값의 9.25%)는 크기는 맞고 열 정체(당기/전기 등)만 틀림**(`label_diff`, `note_periods`/`units.py` 기간·배수 판정에 영향). **본문(BS/IS/CF)은 실측 0건**(§10, 코드 경로가 달라 ROWSPAN 이어짐이 `_split_label_amounts`에서 자동 흡수됨 — 재적재 불필요, F1 회귀 가설도 기각). 전수 재검증(101,327건) 프로덕션 결함 0건(원래 28,189,281개→0). **진행 중 R11 자체의 새 회귀 2종 발견+수정**(R11-1: 헤더판정실패 폴백 offset=0, note 348,099셀/1,629필링→480셀/107필링, 잔여는 R11-2로 정상 분류). **Phase 4(2026-08-08) — note_lines 전량 재적재 완료**(245,452,947→247,244,387행, +0.73%) + std_v3 재빌드(184,298→184,580행) + 재검증(DB 직접 대조 텔코웨어·풍강 값 일치·Gate B `line_value_diff=0`·D&A DB 재확인) 전부 통과. 상세 = `docs/plans/note_span_fix_plan_2026-08-07.md` |
| 계정별 예외단위(자본금류, `report_lines`) | **미조치·미재검증** — 에스티아이 사례(자본금류 계정이 표 선언 배수 무시하고 원 단위 그대로 표기) 위 ROWSPAN 결함과 별개로 남아 있음. 상세 = `docs/qa/handoff_unit_multiplier_misattribution_2026-08-07.md` §4-2 |
| 캡션 상속(연속표) 회수율 | 미측정 |
| `가. 매출유형별 매출액` 류 캡션 | `sales_section`·카탈로그 모두 미포착(실측 나무에이엑스). 캡션 규칙 확장 대상 |
| pre-2015 구서식 | 카탈로그 미검증 |
| ~~특수건설 20151116001903 — 제목+데이터 병합 표~~ | **✅ 조치 완료 2026-08-05** — R4-2 참조. 같은 census 로 팬엔터테인먼트 20181114002948(병합표)·포시에스 20171114002836(BS 위치+계정명)도 함께 해결(활성기업 398건 전수 재검사, 오적용 0건) |
