# 핸드오프 — R4-2 제목+데이터 병합 표/제목 없는 표 구현 완료 (2026-08-05 밤~심야)

새 세션은 이 문서 → 필요하면 `docs/plans/merged_title_data_table_r4-2_2026-08-05.md`
(구현 상세) → `docs/PARSING_RULES.md` R4-2 순으로 읽으면 된다.

---

## 1. 이번 세션에 한 일 (요약)

1. 저녁 핸드오프(`handoff_doc_default_unit_gap5_2026-08-05.md`) §7-1 "특수건설 census"를
   실행 — 활성기업 `n_lines=0` 398건 전수를 구조 census, "제목+데이터 병합 표" 패턴
   정확히 3건(특수건설·포시에스·팬엔터테인먼트) 확인.
2. 사용자와 함께 포시에스 BS(제목 자체가 없는 표)를 "위치+계정명" 규칙으로 추가 조사 —
   1차 census는 9건(오검출 다수)이었으나, 사용자 지시로 위치 조건을 더해 재검증하니
   정확히 포시에스 2표(연결+별도 BS)만 남음(다른 기업 오적용 0건 확인).
3. 계획 문서(`docs/plans/merged_title_data_table_r4-2_2026-08-05.md`) 작성 후 사용자
   승인("이 계획대로 구현 진행해줘") 받아 구현.
4. 구현·회귀 테스트 6건 추가·전체 pytest 통과·3건 소급 백필·원문 대조 검증·
   `docs/PARSING_RULES.md` R4-2 기록·git 커밋·main 병합·**push 완료**.

## 2. 최종 상태

```
report_lines            37,406,154   (+570, 이번 세션)
active n_lines=0 필링    398 → 395   (정확히 -3, 부작용 없음)
```

- git main = `03ddc45`, **origin 에 push 완료**.
- pytest: `fin2/tests tests` 415 passed — 사전부터 있던 무관 실패 1건
  (`test_lxintl_facility_table_dropped`, biz_section 소관)만 남음.
- 브랜치 `fix/layer2-merged-title-table-r4-2` 는 ff-only 병합 후 삭제됨.

## 3. 무엇을 고쳤나 (R4-2)

`title_text_owned`/`title_text_for_classify`(직전 형제 기반)가 **둘 다** 제목을 못 찾을 때만
시도하는 최후 폴백 2종. `fin2/extract/statement_titles.py`:

1. **`owned_merged_title(tbl)`** — 표 자신의 첫 행이 재무제표명 하나뿐이면(제목·기간·
   회사명·단위·헤더·데이터가 전부 한 TABLE 안, '재무제표_직접작성' 수기입력 서식) 그
   statement 로 확정. **반드시 `table_has_amount_rows(tbl)` 가 참인 표에만** 적용 — 아니면
   표제/데이터표 분리 서식(다수)의 순수 제목표에도 걸려 데이터가 중복 append 된다.
   단위도 표 안(헤더행 이전 메타행)에 있을 수 있어 `text.py::merged_table_local_unit()`
   로 함께 찾는다(못 찾으면 R4-1 doc_default 로 넘어감).
2. **`titleless_bs_start(tbl)`** — 제목이 전혀 없어도, 그 표가 `2.연결재무제표`/
   `4.재무제표` 섹션의 **첫 번째 금액표**이고 헤더가 곧바로 "과목"으로 시작하며 헤더
   다음 첫 계정명이 **"자산"** 이면 BS 로 확정(포시에스 패턴). 단위는 표 안에 없으므로
   R4-1 doc_default 로 확보.

두 함수 모두 `fin2/extract/text.py::_detect_body_statement_tables`(report_lines/fact_v2
공유 진입점)에 배선했다.

### 함정 2가지(구현 중 실측)

- **ROWSPAN 날짜행 함정** — "과목" 헤더 셀이 `ROWSPAN=2` 면 다음 TR 은 1열이 없어져 첫
  TD 가 날짜값("2017-09-30")이 된다 — 그대로 읽으면 날짜를 계정명으로 오인해 "자산"
  판정이 실패한다. 기간/날짜 패턴이면 건너뛰도록 처리.
- **9건 오검출** — "제목 없이 과목으로 바로 시작"만 조건으로 걸면 주석/CF/IS 표까지
  9건 걸린다(미래아이앤지·메지온·올리패스·라파스·이엔플러스·한탑 3개년). 원문 대조로
  전부 주석/CF/IS 표(다른 섹션·다른 계정명)임을 확인해 배제 — 위치(`2.연결재무제표`/
  `4.재무제표` 섹션의 첫 금액표) + 계정명("자산") 4조건으로 좁혀 포시에스만 남겼다.

## 4. 구현 중 발견한 기존 결함 2건 (계획엔 없던 것)

1. **`_looks_like_appropriation` 오탐** — 팬엔터테인먼트 BS 는 대차합계를 "부채자본총계"
   (표준 "부채와자본총계"와 순서가 다름)로만 쓴다. 처분계산서 배제 가드의 "진짜
   재무제표 확정 라벨" 목록(`_REAL_STMT_ROW_RE`)에 이 표기가 없어서, 같은 표 안의
   "미처분이익잉여금"(자본 세부 항목, 정상 BS 구성) 때문에 처분계산서로 오인돼 **BS
   전체가 배제**됐다. R4-2 로 분류가 성공하기 전엔 `stmt=None` 에서 먼저 걸러져 이 가드에
   도달하지 못해 드러나지 않던 결함. "부채자본총계"·"자본과부채총계" 추가로 해결.
2. **`document_default_unit` 인접성 가정 오류** — 포시에스는 요약재무정보 섹션 안에서
   [단위선언 표] → [연결범위 표(단위·데이터 둘 다 없음)] → [실제 데이터 표] 순서라,
   데이터 표의 "직전 형제"만 보던 종전 로직이 사이에 낀 무관 표 때문에 단위선언 표를
   놓쳤다. 데이터 없는 표를 지나며 단위 선언을 "기억"해뒀다가 데이터 표 자신에게 선언이
   없을 때 쓰도록 확장 — R4-1 "요약재무정보 섹션 전체가 하나의 단위를 공유한다"는 원칙을
   표 단위 인접성이 아니라 섹션 단위로 넓힌 것이라 R4-1 정책과 모순되지 않는다.

## 5. 검증

- **원문 대조**: 특수건설 유동자산 `95,539,541,976`·매출액 `109,300,142,706`, 포시에스
  자산총계(연결) `44,370,779,689`, 팬엔터 부채자본총계(연결) `62,471,323,149` — DB
  적재값과 원문 정확 일치.
- **회귀**: `fin2/tests/test_report_lines.py` 신규 6건(owned_merged_title 2·
  merged_table_local_unit 1·titleless_bs_start 2·3건 종단 검증 1). 전체
  `fin2/tests tests` 415 passed(사전 무관 실패 1건 제외).
- **영향 범위 재실측**: 활성기업 `n_lines=0` 398 → 395(정확히 -3) — 광범위 부작용 없음.
- **소급 백필**: `scripts/load_report_lines.py --rcept-file`(3건) 실행, `status=done`
  전건, `n_lines` 173/300/97(합 570행), 오류 0.
- **파이프라인**: 새 파서가 아니라 기존 공유 함수(`_detect_body_statement_tables`·
  `document_default_unit`) 수정이라 `scripts/collect_new.py` 의 두 call site(메인 +
  `--standardize-only` 재개)에 별도 배선 불필요 — 둘 다 이미 같은 `extract_report_lines()`
  를 거치므로 자동 적용됨을 코드 추적으로 확인.

## 6. 남은 미해결 (이번 스코프 밖)

- **특수건설 SCE_S·CF_S** — BS/IS 는 해결됐지만 SCE·CF 는 로컬 단위도 doc_default 근거
  (요약재무정보 없음·회계정책 주석 없음, 분기보고서 간이서식)도 없어 여전히 스킵.
  텍스트 근거가 전혀 없는 케이스라 R0/R6 원칙상 추측으로 채우지 않는다.
- **08-05 저녁 핸드오프 §7-2 "XML 파싱 자체 실패 9건"** — 아직 미착수. ★주의: 이번 세션
  census로 그 목록의 "포시에스"·"팬엔터테인먼트"가 이번에 해결한 rcept_no와 **다른 건**일
  가능성이 확인됐다(`download_tasks.parse_status` 가 이번 건들은 `success`/`partial` 이지
  `failed` 아님). 착수 시 rcept_no 단위로 재확인 필요(회사명만으로 같은 건이라 단정 금지).
- **표못잡음(현대섹션있음) 6건** — 미착수.
- **③ 표제 인식 수정(0b93816) 소급 미반영 ~260건** — 미착수.
- **08-04 병행 트랙 나머지**(download-only 백로그 64건+) — Phase 5 재개 선행조건.

## 7. 다음 세션 첫 행동

1. 위 §6 우선순위대로 진행하거나, 재설계 본류(4계층 재설계 마스터 허브)로 복귀할지 확인.
2. "XML 파싱 자체 실패 9건" 착수 전, 목록의 rcept_no 를 실제로 재수집(이번 세션처럼
   회사명이 아니라 rcept_no 로 확정)할 것.

## 8. 이번에 만든/바꾼 파일

| 파일 | 내용 |
|---|---|
| `fin2/extract/statement_titles.py` | `owned_merged_title()`·`titleless_bs_start()` 신설 |
| `fin2/extract/text.py` | `merged_table_local_unit()` 신설·`_detect_body_statement_tables()` 배선·`document_default_unit()` 확장·`_REAL_STMT_ROW_RE` 확장 |
| `fin2/tests/test_report_lines.py` | 신규 테스트 6건 |
| `docs/PARSING_RULES.md` | R4-2 신설(규칙색인·본문·부록B·부록C 갱신) |
| `docs/plans/merged_title_data_table_r4-2_2026-08-05.md` | 계획+구현 완료 기록(§8) |
| `scripts/census_merged_title_data_table.py` 등 4개 | census/검증 스크립트(읽기전용) |

커밋: `03ddc45 fix(layer2): R4-2 제목+데이터 병합 표/제목 없는 표 — 특수건설·팬엔터·포시에스 3건 복구`
(main 에 ff-only 병합, **push 완료**)

## 9. 실행 명령 (재현용)

```bash
# 회귀
.venv/bin/python -m pytest fin2/tests tests -q

# 3건이 지금 상태 그대로인지 재확인
PYTHONPATH=. .venv/bin/python -c "
import psycopg2
conn = psycopg2.connect(dbname='tj_finance')
cur = conn.cursor()
rcepts = ['20151116001903','20181114002948','20171114002836']
cur.execute('SELECT rcept_no, status, n_lines FROM report_line_load_progress WHERE rcept_no = ANY(%s) ORDER BY rcept_no', (rcepts,))
print(cur.fetchall())
"

# 영향 범위 재확인(census, 읽기전용)
PYTHONPATH=. .venv/bin/python scripts/census_merged_title_data_table.py
PYTHONPATH=. .venv/bin/python scripts/census_titleless_bs_position_rule.py
```
