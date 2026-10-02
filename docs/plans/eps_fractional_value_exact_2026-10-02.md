# 소수 EPS 보존 설계 (batch #92, decision #4 = B) — 2026-10-02

## 배경
- 비투엔 2020FY `20210317000884` 별도 기본·희석주당이익: 원문은 13.42이고 DB는 13이다(#88194, #88195).
- 원인은 `report_lines.value_won` 이 BIGINT 라는 데 있다. 모든 경로가 EPS 를 정수로 만든다.
- 표본: 2015+ EPS 필링 296건 중 5건(약 1.7%)의 원문 EPS 에 소수가 있었다. 2015+ 104,615필링에 비례하면 약 1,800필링이다(표본 추정치이며 전수가 아니다).
- 사용자 결정 B: 소수 EPS 를 보존한다. 승인된 범위는 report_lines 에 numeric 컬럼 추가(DDL), EPS 경로 수정, 소수 EPS 필링 전수 스캔·재적재다.

## ★승인 범위 밖에서 새로 확인된 것 (실행 전에 확인 필요)
1. **계층3도 BIGINT 다.** `extended_facts_v3.amount_won` 이 BIGINT 다(`collector/models.py:1982`).
   EPS(`is.eps_basic`/`is.eps_diluted`)는 `fin2/layer3/combine.py:3189-3208` 에서 `int(value_won)` 으로 읽혀 이 테이블로 간다.
   report_lines 만 고치면 **앱 화면의 EPS 는 계속 정수**다. 앱에서 소수 EPS 를 보려면 extended_facts_v3 에도 컬럼을 추가하고(두 번째 DDL) 계층3을 재빌드해야 한다.
2. **검증 트리거 해시.** `fin2/verification/schema.sql:378` 의 적재 내용 해시는 컬럼 목록이 고정돼 있다.
   새 컬럼을 넣지 않으면 재적재 후에도 "데이터 변경 없음"으로 판정돼 이슈를 fixed 처리할 수 없다(트리거가 막는다). 함수 교체도 DDL 이다.
3. **권한.** report_lines 의 소유자는 `taejin` 이다. fix 워크트리(`tjf_fix`)로는 ALTER 할 수 없고, 워크트리 규약상 DDL 도 금지돼 있다. 마이그레이션은 사용자가 직접 실행해야 한다.

## 설계
### 스키마 (추가만, 기존 값 무변경)
- `report_lines.value_exact NUMERIC NULL` — `value_won` 이 정확한 값을 반올림한 결과일 때만 채운다(소수 EPS). 나머지는 NULL 이다.
  nullable 이고 DEFAULT 가 없는 ADD COLUMN 이라 26 GB 테이블에서도 카탈로그만 바뀐다(즉시).
- note_lines 는 `LIKE report_lines` 로 생성된 테이블이다. 주석에는 EPS 가 없으므로 note_lines 에는 추가하지 않는다. 단, `_NOTE_INSERT_COLS` 가 명시 목록이라 영향이 없는지 확인한다.
- (1번을 진행하는 경우) `extended_facts_v3.amount_exact NUMERIC NULL` 을 추가하고, `extended_financials` 뷰는 `COALESCE(amount_exact, amount_won)` 를 노출한다.
- 검증 트리거 해시에 `value_exact` 를 추가한다.
- 방식: `collector/db.py` migrations 리스트에 항목을 추가하고 `collector/models.py` 의 `ReportLine` 에 컬럼을 추가한다.

### `value_won` 은 그대로 둔다
- 반올림 정수를 계속 저장한다. 기존 소비자(계층3 병합 비교 `combine.py:1968/1973`, 검토 CSV, 기계대조)가 바뀌지 않게 하기 위해서다.
- 소수가 필요한 소비자만 `COALESCE(value_exact, value_won)` 을 쓴다.

### 경로별 수정
| 경로 | 위치 | 수정 |
|---|---|---|
| HTML EPS | `parser/common/amount_normalizer.py:518-519`(R157 소수 경로), `report_lines.py::_emit_eps_lines`(:946/:971 → :1040) | 정확값을 함께 돌려주는 변형 함수(`parse_amount_exact`)를 추가하고, EPS 행에서 소수부가 0이 아니면 `value_exact` 를 채운다. 기존 `parse_amount` 의 시그니처는 바꾸지 않는다. |
| XBRL EPS | `report_lines_xbrl.py::_numeric_value`(:628-632) | `Decimal(value_raw)` 가 정수가 아니고 단위가 KRW/shares(EPS)일 때 `value_exact` 를 채운다. 부호 반전 패스(:1604)에서도 함께 반전한다. |
| 수동 CSV | `manual_report_lines.py:146` | 같은 변형 함수를 쓴다. |
| PDF | `fin2/extract/pdf.py:64` 토크나이저가 `.` 을 허용하지 않는다 | 이번 범위에서 제외한다. 현재 PDF-only 는 보류 정책 대상이고, 소수 EPS 가 두 토큰으로 갈리는 별도 결함 후보로 기록만 한다. |
| 계층3 (1번 진행 시) | `combine.py:3189-3208` → `build.py:212-216` | EPS canonical 은 `value_exact` 를 함께 실어 `amount_exact` 에 적재한다. |

### 대상 선정·재적재
- 전수 스캔: 2015+ EPS 필링 원문에서 `주당` 행에 소수 셀이 있는 필링을 찾는다. 기계대조 `load_statement_tables` 를 재사용하고, raw_report 대량 read 는 SD카드 경로를 쓴다. XBRL 필링은 instance 의 EPS fact 에 소수가 있는지 본다.
- 스캔 결과를 `docs/qa/eps_fractional_targets_2026-10-0X.txt` 로 남긴 뒤 `batch add-targets 92`, `batch reload 92` 순으로 진행한다.
- 1번을 진행하면 대상 기업의 계층3을 재빌드한다.

### 검증
- 회귀 테스트: HTML(13.42), XBRL(소수 fact, 부호 반전 포함), 정수 EPS는 `value_exact` NULL, 백만원 표 안의 EPS.
- 원문 대조: 비투엔 2건과 스캔 표본 10건의 DB `value_exact` 를 원문과 비교한다.
- Gate B 무영향: `value_won` 이 바뀌지 않았음을 재적재 전후로 비교한다.
- 이슈 #88194·#88195 는 `value_exact = 13.42` 를 DB 에서 확인한 뒤 fixed 처리한다.
- `docs/PARSING_RULES.md` 에 R212 를 먼저 기록한다.

## 사용자가 정할 것
1. 계층3(`extended_facts_v3`)까지 포함할지: 포함하면 DDL 이 하나 더 필요하고, 앱에 소수 EPS 가 보인다.
2. 마이그레이션 실행 주체: 코드 준비 후 사용자가 `init_db` 마이그레이션을 실행한다(소유자 권한 필요).
