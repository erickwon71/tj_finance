# 계층2 재적재 + 원문대조 검토 캠페인 (2026-09-08)

## Context — 왜 하는가

DB 적재 데이터의 신뢰도를 확인할 수 없다. `report_lines`에는 이미 **184,180 rcept ·
6,296만 행**이 들어 있지만, 그 값들은 2026-07 이후 R28~R84로 **파서가 60번 넘게 바뀌는
동안 여러 시점에 적재된 혼합물**이다. 어떤 행이 어느 세대 파서로 만들어졌는지 알 수 없고,
"보고서 원문 = DB"라는 PRD 00 불변원칙이 실제로 성립하는지 전수로 확인된 적이 없다.

그래서 **현행 파서로 다시 파싱해 적재하고, 그 적재 결과를 보고서 원문과 사람이 직접
1:1로 대조**한다. 산출물은 두 가지다 — ① 검증된 계층2 데이터, ② 대조 과정에서 드러나는
파서 결함 목록(FAIL → 원인규명 → 규칙화).

### 확정된 결정 (2026-09-08, 사용자)

| # | 항목 | 결정 |
|---|---|---|
| 1 | 정정본 처리 | **현행 R3 유지** — 계층2는 원본·정정본을 rcept별로 전부 전사, 덮어쓰기 없음. 정정본도 **별개 검토 대상 1건**으로 취급. (최초 요청이던 "정정값으로 overwrite + 태깅"은 사용자가 철회) |
| 2 | 회사 순서 | **시가총액 큰 순** |
| 3 | 회사 내 범위 | **전부** — 분기·반기·사업보고서 + 정정본, 최신 → 과거 backward |
| 4 | FAIL 시 | **멈추고 원인부터 규명** (루프 중단, 파서 수정 후 재적재→재검토) |
| 5 | 자동검산 | **붙인다** — CSV 상단에 PASS/의심 요약 표시 |

### 규모에 대한 정직한 진술

관리 대상 활성 보통주 **2,531사 / 정기보고서 189,485건**(분기 89,765 · 사업 54,265 ·
반기 45,455). 재파싱 자체는 싸다 — **실측 1건당 ~0.2초**(강원에너지 FY2024 5건 1.5초).
**병목은 100% 사람 검토**다. 1건 3분이라도 전수는 약 9,500시간이므로, 이 캠페인은
"완주"가 아니라 **시총 상위부터 무기한 진행하는 열린 캠페인**으로 설계한다. 진척도는
"검토 완료 기업 수"로 센다.

---

## 설계 개요

세 부품 + CLI 하나.

```
scripts/layer2_review.py  (CLI, 사용자 접점)
   ├─ init        대상 큐 생성 (시총순 × 회사내 최신→과거)
   ├─ next        ① 소스 라우팅 → ② 재파싱 → ③ DB 적재 → ④ 자동검산 → ⑤ CSV 생성
   │              → DART 링크 + CSV 경로 + 검산요약 출력하고 대기
   ├─ pass        통과 기록 후 다음 1건으로 (next 자동 실행)
   ├─ fail --note 실패 기록 후 **루프 정지** + 트리아지 진입점 출력
   ├─ redo        파서 수정 후 현재 대상만 재적재→재검산→CSV 재생성
   ├─ skip --note 원문 부재 등 검토 불가 건 건너뛰기
   ├─ finish-corp 회사 1곳 종료 시 std_v3 재빌드 + calendarize (런북 B5)
   └─ status      캠페인 진척
```

---

## 1. 대상 큐 — `layer2_review_queue` (신규 테이블)

`collector/models.py`에 ORM 클래스 추가 (`Base.metadata.create_all()`로 자동 생성 —
기존 `CorpVerifyStatus`(`collector/models.py:1293`)·`ReconCandidate`(`:1235`)와 같은 방식).

grain = **rcept_no 1건**.

```
rcept_no PK / corp_code / corp_name / market
corp_rank INT              -- init 시점 시총 순위 스냅샷
market_cap BIGINT
seq_in_corp INT            -- 회사 내 검토 순번
fiscal_year / fiscal_period / report_type / filed_at / report_nm
is_amendment / is_attachment_amendment
source_kind VARCHAR(10)    -- xml | pdf | html | none
status VARCHAR(12)         -- pending | reloaded | pass | fail | blocked | skipped
reloaded_at / n_lines INT / n_lines_by_scope JSONB
check_status VARCHAR(8)    -- ok | suspect | na
checks JSONB               -- 자동검산 상세
csv_path TEXT / reviewed_at / note TEXT
Index(corp_rank, seq_in_corp), Index(status)
```

`ReconCandidate`의 관례를 따른다 — **기계가 다시 채우는 컬럼과 사람이 남긴 컬럼
(`status`/`note`/`reviewed_at`)을 분리**하고, `init` 재실행이 사람 판단을 덮어쓰지 않는다.

### 정렬 정의

**회사 순서** — `stock_prices.market_cap`, `market_cap IS NOT NULL`인 **최신 거래일**
스냅샷 기준 내림차순. (실측: 최신일 2026-09-08은 market_cap 미채움, **2026-08-31에
2,500종목** 채워져 있음 → 그 날짜를 자동 선택.) market_cap이 없는 소수 종목은
`close_price × shares_out` 폴백, 그것도 없으면 맨 뒤.
유니버스는 R7 그대로 — `is_active AND stock_code IS NOT NULL AND stock_code NOT LIKE '9%'`
(`app/data/corp.py:27` 관례).

**회사 내 순서** — `(fiscal_year DESC, period_rank DESC, filed_at ASC, rcept_no ASC)`
where `period_rank`: Q1=1, H1=2, Q3=3, FY=4.
→ 기간은 **최신에서 과거로**, 같은 기간 안에서는 **최초등록본 → 정정본** 순.
사용자 요청 "최신부터 backward" + "최초 → 정정 순서"를 둘 다 만족한다.

`is_final`은 **필터로 쓰지 않는다** (R3 / `collector/filing_select.py` 도크스트링).

---

## 2. 재적재 (`next` / `redo`의 ①~③)

### 소스 라우팅

| 조건 | 경로 | 비고 |
|---|---|---|
| `download_tasks.file_type='xml'` & 파일 존재 | `extract_report_lines()` (`fin2/extract/report_lines.py:1200`) | 절대다수. 2010년 이하는 내부에서 `legacy_pre2015.py`로 자동 라우팅 |
| xml 없음, PDF/HTML만 | `collector/pdf_lines_sync.py::recover_one()` + `LegacyDartScraper` | **네트워크 필요 + 값조작 결함 이력 있음**(`docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md` Pattern A) → CSV 상단에 `⚠ PDF복구 경로` 경고 표시 |
| 원문 없음 | 적재 안 함, `status='blocked'` + 사유 기록 | 검토 큐에서 제외하고 별도 집계 |

### 적재 호출 (두 개를 **반드시 같이**)

```python
store_report_lines(session, rcept_no, lines)      # report_lines.py:1340, rcept 단위 delete-then-insert
store_report_tables(session, rcept_no, lines)     # report_lines.py:1408, 단위 선언 원문(unit_decl_raw)
```

`cmd_extract_lines`(`run.py:2788`)는 `store_report_tables`를 부르지 않는다 —
그대로 베끼면 CSV에 찍을 **단위 선언 원문이 갱신되지 않으므로** 반드시 둘 다 호출한다.

- `store_report_lines`의 **manual 보호가드**(`report_lines.py:1373`)는 그대로 둔다.
  `unit_source='manual'` 행이 있는 rcept는 `ValueError` → `status='blocked'`로 빠지고
  루프는 계속한다(사람이 이미 검증한 값을 이 캠페인이 덮어쓰지 않는다).
- `note_lines` / `ifrs_evidence`는 **건드리지 않는다** (BS/IS/CF 범위 밖).
  → 그 결과 같은 rcept의 `note_lines`가 구세대 파서 산출로 남는다. 이 계획의
  스코프 밖임을 명시하고 백로그로 기록한다.
- 적재 후 CSV는 **메모리의 파싱 결과가 아니라 DB에서 다시 읽어** 만든다 — 적재 경로
  자체(`_is_loadable` 필터·컬럼 매핑)까지 검증 대상에 넣기 위해서다.

---

## 3. 자동검산 — `fin2/audit/layer2_selfcheck.py` (신규)

```python
@dataclass(frozen=True)
class CheckResult:
    code: str; scope: str; verdict: str; message: str   # verdict: PASS|FAIL|NA
def run_checks(session, rcept_no) -> list[CheckResult]
```

계층2에는 canonical account가 없으므로 판정은 **`label_raw` 정규식**으로 한다.
**R6 준수 — 근거 라벨을 못 찾으면 `NA`(판정불가)로 두고 추측하지 않는다.**

| 코드 | 내용 | 성격 |
|---|---|---|
| `bs_balance` | 자산총계 = 부채총계 + 자본총계 (또는 부채와자본총계) — basis별 | 차단 |
| `cf_closing_cash` | 기초현금 + 영업 + 투자 + 재무 (+환율효과) = 기말현금 — basis별 | 차단 |
| `scope_presence` | 별도/연결 × BS/IS/CF 6칸 중 0행인 칸. 같은 회사 형제 기간과 비교해 "원래 연결이 없는 회사"와 구분 | 차단 |
| `unit_sanity` | `unit_source ∈ {undetermined, undeclared}` 행 존재 / 같은 statement·basis 안에서 `report_tables.declared_unit` 불일치 | 차단 |
| `row_count_outlier` | 같은 corp·basis·statement의 다른 기간 행수 중앙값 대비 ±50% 이탈 (`docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md` 방법 재사용) | 의심 |
| `duplicate_rows` | 같은 `(statement, basis, table_seq)` 안 라벨+값 완전중복 = 파서 이중 append 신호(R4-2 함정) | 의심 |
| `bs_rollup` | 유동+비유동 = 총계 (자산/부채) | 참고 |
| `is_waterfall` | 매출액 − 매출원가 = 매출총이익 | 참고 |

`check_status`: 차단 검산에 FAIL이 하나라도 있으면 `suspect`, 전부 PASS/NA면 `ok`.
**검산은 표시만 하고 진행을 막지 않는다** — 최종 판정은 사람의 원문 대조다(R9).

---

## 4. 검토 CSV — `fin2/extract/review_csv.py` (신규)

경로: `layer2_review/<시장>/<corp_code>_<회사명>/<report_type>/<연도>/<rcept_no>_review.csv`
(`raw_report/` 트리 미러링 = `fin2/extract/manual_report_lines.py:39` 관례 재사용,
프로젝트 로컬, `.gitignore`).
**`manual_review/`와는 별도 디렉터리** — 그쪽은 사람이 값을 타이핑해 넣는 입력용
CSV라 컬럼 스키마가 다르고, `load_manual_report_lines.py`가 잘못 집어삼키면 안 된다.

인코딩 **UTF-8 with BOM**(엑셀 한글), `rcept_no`는 `="20250320001312"`로 감싼다
(엑셀 지수표기 함정 — `manual_report_lines.py:24` 실측).

```
# 회사,삼성전자 (00126380) KOSPI  시총순위 1
# 보고서,FY2025 반기보고서 [기재정정]
# 접수번호,="20250814001234"
# DART 원문,https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814001234
# 접수일,2025-08-14
# 파싱 소스,xml
# 재적재,2026-09-08 23:50:12
#
# ── 자동검산 ──
# [별도] BS 대차평형,PASS,자산총계 4,559,060,000,000 = 부채+자본
# [연결] BS 대차평형,FAIL,자산총계 ... ≠ 부채+자본 (차 1,000)
# [별도] CF 기말현금,PASS
# 범위 존재,PASS,별도/연결 × BS/IS/CF 6칸 모두 존재
# 단위,PASS,전부 declared (천원)
# 행수 이상치,의심,[연결] IS 41행 (동일회사 중앙값 58)
#
구분,단위,순번,깊이,항목명,금액,원문값,비고
[별도] 재무상태표,천원,1,1,유동자산,77913047,,
[별도] 재무상태표,천원,2,2,현금및현금성자산,221261,,
...
[별도] 손익계산서,천원,1,0,매출액,...
[별도] 현금흐름표,천원,...
[연결] 재무상태표,천원,...
[연결] 손익계산서,천원,...
[연결] 현금흐름표,천원,...
```

**규칙**
- 순서 = 사용자 요청대로 **별도 BS → IS → CF → 연결 BS → IS → CF**.
  행 순서는 원문 순서 = **`ORDER BY table_seq, row_order`** (`collector/models.py:377`).
  연결이 없으면 별도만 나온다.
- **금액 = 보고서에 인쇄된 그대로** — `value_won × 10^adecimal`
  (`fin2/audit/report_line_audit.py:45::_rl_displayed` 재사용). `단위` 열은
  `report_tables.unit_decl_raw`(없으면 `declared_unit`에서 유도)에서 온다.
- `value_won IS NULL`이면 `금액`은 비우고 `원문값`에 `value_raw`를 넣는다(R4의 NULL 규약).
- `unit_source='fx_declared'`면 환산하지 않고 `단위` 열에 통화코드
  (`report_tables.currency`)를 찍고 `비고`에 `표시통화` 표시.
- `header_hint IS NOT NULL` 행도 **숨기지 않고 보여준다** — 원문에 인쇄된 행이므로
  대조 대상이다. `비고`에 `header_hint:날짜` 식으로 표시(R5).
- SCE/APPR은 제외(사용자 범위 = BS/IS/CF). 단 `scope_presence` 검산에는 안 쓴다.

---

## 5. 상호작용 흐름

```bash
python scripts/layer2_review.py init --top 50
```

```bash
python scripts/layer2_review.py next
```

출력(사용자가 바로 쓸 수 있는 형태 — [[feedback-manual-review-show-dart-link-and-csv-path]]):

```
[1위 삼성전자 00126380]  3/112건
  보고서  FY2025 반기보고서 [기재정정]  r20250814001234  (2025-08-14)
  DART   https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250814001234
  CSV    layer2_review/KOSPI/00126380_삼성전자/half/2025/20250814001234_review.csv
  적재    별도 BS 62 / IS 41 / CF 33 · 연결 BS 65 / IS 44 / CF 35  (총 280행)
  검산    ⚠ 의심 1건 — [연결] BS 대차평형 FAIL (차 1,000)

  open "layer2_review/KOSPI/00126380_삼성전자/half/2025/20250814001234_review.csv"
```

사용자가 CSV ↔ DART 원문 대조 후:

```bash
python scripts/layer2_review.py pass
```
→ `status='pass'` 기록 + 즉시 다음 1건 `next` 실행.

```bash
python scripts/layer2_review.py fail --note "[연결] BS 유동자산 이후 한 행씩 밀림"
```
→ `status='fail'` 기록 + **루프 정지**. 트리아지 진입점을 출력한다:
원문 파일 경로, `scripts/verify_report_lines.py --rcept <R>`,
`scripts/layer2_fidelity_roundtrip.py --rcept <R>`,
`scripts/layer2_forward_cells.py --rcept <R>` (전부 기존 스크립트, `--rcept` 지원 확인됨).

파서를 고친 뒤:
```bash
python scripts/layer2_review.py redo
```
→ 같은 rcept만 재적재→재검산→CSV 재생성. 통과하면 `pass`.

회사 1곳을 다 본 뒤 — **런북 B5 필수 후속**(안 하면 `dq_assertions::calendar_orphan_cq`
ERROR가 유령으로 남는다):
```bash
python scripts/layer2_review.py finish-corp
```
→ 내부에서 `scripts/build_std_v3.py --corp <corp> --year-min 1999` 실행 +
`calendarize_corp_v3(corp)` 재동기화 + `calendar_orphan_cq` 0건 확인.

---

## 6. 변경/신규 파일

| 파일 | 작업 |
|---|---|
| `collector/models.py` | `Layer2ReviewQueue` ORM 클래스 추가 |
| `fin2/audit/layer2_selfcheck.py` | **신규** — 자동검산 8종 |
| `fin2/extract/review_csv.py` | **신규** — DB → 검토 CSV (순수 빌더 + writer 분리) |
| `scripts/layer2_review.py` | **신규** — CLI (init/next/pass/fail/redo/skip/finish-corp/status) |
| `fin2/tests/test_layer2_selfcheck.py` | **신규** — 합성 오라클로 검산 8종 고정 |
| `fin2/tests/test_review_csv.py` | **신규** — 순서(별도→연결, table_seq/row_order), 표시금액 환산, NULL/fx 규약 |
| `.gitignore` | `layer2_review/` 추가 |
| `docs/plans/layer2_reload_review_campaign_2026-09-08.md` | **신규** — 캠페인 트래킹 문서(`manual_review_queue_2026-09-08.md` 포맷: 표 + 진행 로그) |

**재사용하는 기존 자산** (새로 만들지 않는다):
`extract_report_lines`/`store_report_lines`/`store_report_tables`
(`fin2/extract/report_lines.py:1200,1340,1408`) · `recover_one`
(`collector/pdf_lines_sync.py:84`) · `_rl_displayed`
(`fin2/audit/report_line_audit.py:45`) · `get_session` (`collector/db.py:1362`) ·
`DART_VIEWER` (`app/data/reports.py:12`) · `unwrap_excel_text`
(`fin2/extract/manual_report_lines.py:91`) · `build_std_v3.py` / `calendarize_corp_v3`.

---

## 7. 검증

1. **회귀** — `pytest tests/ fin2/tests/` (873 pass 기준, 알려진 1건 실패
   `test_lxintl_facility_table_dropped` 제외). 범위 지정 필수(NAS 심링크).
2. **파일럿 end-to-end** — 시총 1위 회사의 최신 보고서 1건으로 `init`→`next`까지 돌려
   CSV를 생성하고, **사용자가 DART 원문과 실제로 대조**해 CSV 포맷·순서·단위·금액이
   눈으로 맞춰볼 수 있는지 확인. (여기서 포맷을 확정한 뒤 본 캠페인 시작)
3. **검산기 민감도** — 이미 결함이 확인된 rcept
   (`docs/qa/report_lines_row_count_outlier_scan_2026-09-08.md`의 Pattern A 케이스)에
   `run_checks()`를 돌려 **FAIL/의심이 실제로 뜨는지** 확인. 안 뜨면 검산이 무의미하다.
4. **manual 보호가드** — YBM넷 `20020814000872`(유일한 `unit_source='manual'` rcept)를
   큐에 넣고 `next`를 돌려 `status='blocked'`로 빠지고 사람 입력값이 보존되는지 확인.
5. **Gate B 무영향** — 파일럿 회사에 대해 `run_dq_gate` 샘플 실행, 신규 ERROR 0건.
6. **멱등** — 같은 rcept에 `redo`를 두 번 돌려 행수·CSV 바이트가 동일한지.

---

## 8. 이 계획에 **포함하지 않는 것** (별도 결정 필요)

- **전사 벌크 재적재** — 189,485건 전량 재파싱(샤딩 시 하룻밤 거리)은 넣지 않았다.
  FAIL 시 파서를 고치는 설계라 미리 벌크로 적재해두면 수정 후 stale해지기 때문.
  검토가 어느 정도 진행돼 파서가 안정됐다고 판단되면 그때 별도로 결정한다.
- **`note_lines` 재적재** — BS/IS/CF 범위 밖. 재적재된 rcept의 주석은 구세대 파서
  산출로 남는다(백로그).
- **계층3/std_v3 전면 재빌드** — 회사 단위로 `finish-corp`에서만 돌린다.
- **PDF복구 경로(Pattern A) 근본 수정** — 경고 표시만 하고, 실제 수정은 그 경로 건이
  검토 대상으로 올라올 때 FAIL 트리아지로 처리.
