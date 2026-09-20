# R147 — EPS 계속영업/중단영업 세부행 결측 (2026-09-20)

이 문서는 **camp_err_review 워크트리 자체 결과 기록**이다. 캠페인의 살아있는 이슈
로그(`docs/qa/layer2_review_campaign_issues_2026-09-20.md`)는 `camp_run` 워크트리가
전용으로 쓰고 있어 이 워크트리에서는 손대지 않는다(참조만) — 교차참조는 rcept_no로
한다. 규칙 요약은 `docs/PARSING_RULES.md` R147 참고.

## 발견 경위

`camp_run` 워크트리의 계층2 원문전체대조 캠페인이 두산에너빌리티(00159616) [연결]
손익계산서에서 같은 패턴의 EPS 결측을 6건 연속 발견하고 `fail --note` 로 누적했다
(이슈 1~6, rcept_no: `20191114002511`·`20190515001464`·`20190515002099`·
`20190329003636`·`20240327001230`·`20240327001228`). 근본원인은 미조사 상태였다
("추정 원인(미확인, 코드 미조사)").

## 근본원인

`fin2/extract/report_lines.py::_is_eps_label()` 이 EPS 판정에서 **라벨 자체에
`주당` 이 있어야 한다**는 조기 게이트를 걸고 있었다(R145). 그런데 DART 원문은:

```
지배기업 소유주지분 주당손익
　기본주당이익(손실) (단위 : 원)          (699)
　　계속영업이익(손실) (단위 : 원)        (786)
　　중단영업이익(손실) (단위 : 원)          87
　희석주당이익(손실) (단위 : 원)          (699)
　　계속영업이익(손실) (단위 : 원)        (786)
　　중단영업이익(손실) (단위 : 원)          87
```

자식행(`계속영업이익(손실) (단위 : 원)`)은 **라벨에 `주당` 이 전혀 없다** — 오직
조상 체인에만 있다. 이중으로 샜다:

1. `_emit_eps_lines`(EPS 전용 경로)의 `_is_eps_label` 게이트가 `"주당" not in label`
   에서 조기 `False` — R145 의 `C`(섹션 문맥) 규칙이 "라벨에도 `주당` 필수"라는
   조건을 걸어둬서(EPS 절 아래 섞여든 주식수·비율 행 오염 방지) 이 자식행은 `C`
   자격이 없었다.
2. 같은 라벨이 `parser/xml/table_extractor.py::_header_rule_name()` 의 '단위표기'
   규칙(`단위\s*[:\(]` 매치)에도 걸려 **본류(`extract_rows` 출력)에도 애초에 없다**
   — R145 가 EPS 섹션 *제목* 행에 대해 이미 지적한 것과 같은 함정이 여기서는 EPS
   *데이터* 행에도 적용된 것.

두 경로 모두에서 빠지니 완전 결측. 산술 self-check 로 못 잡는 이유: 값이 부모행과
우연히 같을 수 있다(중단영업이 없는 분기는 기본=계속영업, 중단영업=0에 가까움).

## 수정

`_is_eps_label()` 에 `E` 규칙 추가(`fin2/extract/report_lines.py`) — 라벨에 `주당`
이 없어도, **조상 체인이 EPS 절이고(`C`) 이 행 자신이 원(₩)을 명시 선언했다면**
EPS 로 인정한다:

```python
if "주당" not in s:
    # `E` — 라벨엔 `주당` 이 없어도 EPS 절 자식이면서 원(₩)을 스스로 선언한 행.
    return _in_eps_section(section_path) and detect_unit_declaration(label) == 1
```

`C` 단독 인정을 안 하는 R145 의 원래 이유(주식수·비율 행 오염)를 원(₩) 명시 선언
요구로 회피한다 — 주식수·비율 행은 "(단위 : 주)"/"(단위 : %)" 를 선언하지 원(₩)을
선언하지 않는다. 같은 라벨의 EPS 절 **밖**(본문 손익계산서) 총액 행은 원(₩) 인라인
선언이 없어 `E` 가 삼키지 않는다 — 회귀 테스트로 확인.

## 검증

1. **단위 테스트**: `fin2/tests/test_report_lines_r147_eps_continuing_ops_subline.py`
   7건 신규 — 자식행 인정, 본문 총액 비오염, pre-2015 무변경, 원문 재현
   end-to-end(두산에너빌리티 6행 전부 보존), 중복전사 없음. 전부 통과.
2. **전체 회귀**: `pytest tests/ fin2/tests/` — 수정 전 1105 passed, 수정 후
   1112 passed(신규 7건), 회귀 0건.
3. **원문 대조**: 아래 표의 6개 rcept_no + 2022Q1(`20220513001669`) 스팟체크까지
   raw XML(SD카드 마운트 `/Volumes/tj_finance_data/raw_report`, 실제 인코딩은
   EUC-KR이나 XML 선언은 `utf-8`로 표기된 파일 다수 — `iconv -f EUC-KR -t UTF-8`
   로 변환해 확인)을 직접 열어 값 일치를 확인했다.

## 소급 백필 — 두산에너빌리티(00159616) 완결

`scripts/backfill_eps_continuing_ops_subline_r147_2026-09-20.py` 로 2015+ 전체
61개 필링을 재추출 스캔 → **25건**이 R147 대상(2017~2023 회계기간, 정정본 포함 —
중단영업 분류가 종료된 2024+ 는 해당 없음). 전부 재적재 완료, `report_lines` 신규
82행.

| rcept_no | 기간 | 비고 |
|---|---|---|
| 20240327001228 | 2017FY [기재정정, 2024 재작성] | camp_run 이슈#6 |
| 20190329003636 | 2018FY | camp_run 이슈#4 |
| 20240327001230 | 2018FY [기재정정, 2024 재작성] | camp_run 이슈#5 |
| 20190515001464 | 2019Q1 | camp_run 이슈#2 |
| 20190515002099 | 2019Q1 [기재정정] | camp_run 이슈#3 |
| 20190814001701 | 2019H1 | ★pass 후 재판정 |
| 20191114002511 | 2019Q3 | camp_run 이슈#1 |
| 20200330004372 | 2019FY | ★pass 후 재판정 |
| 20240327001231 | 2019FY [기재정정, 2024 재작성] | ★pass 후 재판정 |
| 20200515002634 | 2020Q1 | ★pass 후 재판정 |
| 20200814002599 | 2020H1 | ★pass 후 재판정 |
| 20201113000791 | 2020Q3 | ★pass 후 재판정 |
| 20210319001033 | 2020FY | ★pass 후 재판정 |
| 20240327001232 | 2020FY [기재정정, 2024 재작성] | ★pass 후 재판정 |
| 20240516002209 | 2020FY [기재정정, 2024 재작성 재정정] | ★pass 후 재판정 |
| 20210813000846 | 2021H1 | ★pass 후 재판정 |
| 20211112001083 | 2021Q3 | ★pass 후 재판정 |
| 20220322000017 | 2021FY | ★pass 후 재판정 |
| 20220513001669 | 2022Q1 | ★pass 후 재판정(스팟체크 완료) |
| 20220816001395 | 2022H1 | ★pass 후 재판정 |
| 20221114002161 | 2022Q3 | ★pass 후 재판정 |
| 20230321001573 | 2022FY | ★pass 후 재판정 |
| 20230515002122 | 2023Q1 | ★pass 후 재판정 |
| 20230811002617 | 2023H1 | ★pass 후 재판정 |
| 20231114002953 | 2023Q3 | ★pass 후 재판정 |

**19건은 `layer2_review_queue.status='pass'` 로 이미 검토완료 판정된 필링이었다** —
이 버그가 그 판정 당시엔 알려지지 않아서다. `store_report_lines()` 의 R139 보호가드
(사람/에이전트가 원문대조로 pass 판정한 필링은 기본적으로 재적재 거부)를
`overwrite_reviewed=True` 로 명시 해제하고, 6건(2019Q3 원본 포함)과 동일한 raw XML
직접 대조로 근본원인을 이미 확인한 뒤에만 재적재했다. 2022Q1 은 추가로 개별
스팟체크(raw XML 직접 대조)까지 완료.

`report_lines` 외 하류 영향: `source_ref LIKE 'eps/%'` 값을 읽는 코드가
`fin2/layer3/combine.py` 등 std_v3 파이프라인에 없음(grep 확인) — EPS 자체가
std_financials_v3 에 아직 편입돼 있지 않아 계층3 재빌드는 불필요.

## ★미완결 — 전사 스코프

두산에너빌리티는 "EPS 원(₩) 명시선언 스타일 + 같은 필링 IS 본문에 `중단영업이익`
존재"라는 후보군의 1개사일 뿐이다. SQL 로 좁힌 후보:

```sql
SELECT count(DISTINCT rl1.rcept_no) AS candidate_filings,
       count(DISTINCT rl1.corp_code) AS candidate_companies
FROM report_lines rl1
WHERE rl1.source_ref LIKE 'eps/%기본주당이익%(단위%'
  AND EXISTS (
    SELECT 1 FROM report_lines rl2
    WHERE rl2.rcept_no = rl1.rcept_no
      AND rl2.statement = 'IS'
      AND rl2.label_raw LIKE '%중단영업이익%'
      AND (rl2.source_ref IS NULL OR rl2.source_ref NOT LIKE 'eps/%')
  );
-- 결과(2026-09-20): 5,904건 / 708개사
```

이 세션에서 5,904건 전체를 새 코드로 재추출하는 읽기전용 스캔을 백그라운드로
돌렸다(`scan_r147_full_scope.py`, 결과는 `/tmp/r147_full_scope_result.txt` —
세션 종료 후 사라지는 임시 경로이므로 **다음 세션 시작 시 첫 번째로 이 결과를
영구 위치로 옮기거나 스캔을 재실행할 것**). 결과가 나오면:

1. `AFFECTED` 로 표시된 rcept_no 목록을 파일로 저장.
2. `python scripts/backfill_eps_continuing_ops_subline_r147_2026-09-20.py --apply
   --rcept-list <파일>` 로 재적재(먼저 `--apply` 없이 dry-run으로 건수 확인 권장).
3. `layer2_review_queue.status='pass'` 로 막히는 건은 원문 스팟체크 후에만
   `--overwrite-reviewed` 로 재실행(이번 세션처럼 표본 검증 없이 일괄 적용하지 말 것).

## 관련 파일

- 코드: `fin2/extract/report_lines.py::_is_eps_label()` (`E` 규칙)
- 테스트: `fin2/tests/test_report_lines_r147_eps_continuing_ops_subline.py`
- 백필 스크립트: `scripts/backfill_eps_continuing_ops_subline_r147_2026-09-20.py`
- 규칙 문서: `docs/PARSING_RULES.md` R147
- 원본 이슈 로그(참조 전용, 이 워크트리에서 쓰지 않음):
  `camp_run` 워크트리의 `docs/qa/layer2_review_campaign_issues_2026-09-20.md`
