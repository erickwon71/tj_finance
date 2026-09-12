# 회계기간 오판정 + 시대 라우팅 무재시도 — 설계 (2026-09-12)

**상태**: ✅구현 완료(2026-09-12, 사용자 지시 "구현 진행해줘"). §1·§2·§4 전부 반영·검증됨.
아래 §7에 구현 결과와 **구현 중 §4에서 발견된 더 큰 범위의 부수 패턴(38건)**을 기록한다.
§8에 사용자 지시로 추가 검증한 두 가지("태그 있는 정상경로 오류 가능성", "결산월변경
회사의 interim 기간귀속 오류 가능성") 조사 결과를 기록 — 둘 다 오류 미발견.

**계기**: `reload_report_lines_2015plus_2026-09-12.py` 배치 중 "0행(보류)" 표본 원문대조에서
발견. 진원생명과학(00118521) `[기재정정]사업보고서` r20220908000421 — 사용자가 원문에
별도재무제표가 정상적으로 들어있음을 확인했는데 계층2가 0행을 냈다. 원인 규명 결과
**파서 결함이 아니라 입력 메타데이터(`filings.fiscal_year`) 오판정** 때문이었고, 그 오판정이
그대로 통과된 것은 **추출 단계에 재시도(다른 시대 파서로 다시 시도) 로직이 없기 때문**임이
드러났다. 두 군데 모두 "1차가 실패해도 검증·재시도 없이 그대로 확정"하는 같은 패턴의 갭이다.

## 1. 재현된 사고 체인

```
DART report_nm = "[기재정정]사업보고서"  (★ "(YYYY.MM)" 꼬리표 없음)
  ↓ collector/filing_collector.py::_parse_fiscal_info()
  1차: report_nm 정규식 "\(\d{4}\.\d{2}\)" 매칭 실패(태그 없음)
  2차(유일한 폴백): 접수일(2022-09-08) 기반 추정 → fiscal_year=2022, FY 확정. 검증 없음.
  ↓ (실제로는 원문 CORRECTION 섹션에 "정정대상 최초제출일: 2006.03.31"
     = 제30기(2005 회계연도) 대상이라고 명시돼 있었다 — 안 읽었을 뿐)
filings.fiscal_year = 2022 로 저장
  ↓ fin2/extract/report_lines.py::extract_report_lines()
  report_fiscal_year(2022) > _PRE2015_ROUTING_MAX_FY(2010) → else 분기(2015+ 전용 파서)로만 라우팅
  2005년식 구 서식(대차대조표/결손금처리계산서 등 K-GAAP 이전 명칭) → 신파서가 표를 못 찾음
  groups = {} → 0행. **다른 시대 파서로 재시도하는 코드가 없어 그대로 종료.**
```

부수 피해: 이 오분류 때문에 (corp=00118521, fiscal_year=2022, FY, annual) 그레인에
`is_final=True`가 2개(이 건 + 진짜 2022 정정본 `20230711000247`) 찍혀 있다. 이번엔 0행이라
무해했지만 그레인 자체는 오염된 상태다.

## 2. 현재 구조 재확인 — 갭이 있는 지점과 이미 있는 지점

### 2-1. 입력측(`_parse_fiscal_info`) — 재시도 없음
1차(제목 태그) 실패 시 2차(접수일 추정)로 바로 확정한다. 3차 방법이 없고, 2차 결과를
검증하는 로직도 없다. 원문 XML은 이 함수 호출 시점엔 아직 다운로드되지 않았을 수도 있어
(공시목록 API 메타데이터만으로 호출), 원문을 열어보는 자체가 지금은 설계에 없다.

**범위 재확인**: 전체 정기공시(19만+건) 중 제목에 "(YYYY.MM)" 없는 건 45건, 그중 정정본
3건. 2건(2002·2004년 정정)은 원본 직후 정정이라 접수일 추정이 우연히 맞았다. **완전히
틀린 건 이번 1건이 유일** — 원본(2006) 대비 16년 뒤 정정이라는 극단적 시간차 때문.

### 2-2. 추출측(`extract_report_lines` era 라우팅) — 한쪽 방향만 이미 방어돼 있음
★재확인 결과 **완전히 무방비는 아니었다.** `_detect_pre2015_body_statement_tables_merged()`
(report_lines.py:80, 2026-08-10 설계 `docs/plans/pre2015_layer2_backfill_phase2_design_
2026-08-10.md` §2-1 기반)는 `report_fiscal_year <= 2010` 라우팅에서 이미 **양쪽 탐지기를
다 돌려 섹션코드(BS_C/IS_S 등) 단위로 병합**한다 — 구파서가 못 채운 코드만 신파서 결과로
보충(`setdefault`, 덮어쓰지 않음). 이건 "전부 아니면 전무"로 파서를 바꿔치기하는 게
아니라 **부분 보충** 설계라 안전하다(구파서가 채운 건 그대로 유지, 못 채운 것만 보충).

**갭은 반대 방향(`else` 분기, 2011+ 라우팅)에 있다** — 여기는 병합은커녕 폴백 자체가
없다. `report_fiscal_year`가 (이번 건처럼) 잘못 커서 2011+ 로 잘못 라우팅되면, 신파서가
못 찾은 걸 구파서로 보충하는 코드가 없어 그냥 0행으로 끝난다. 이번 사고의 직접 원인.

### 2-3. 주석 파서(`_emit_note_lines`/`assign_note_tables_with_titles`) — 애초에 시대 분기 자체가 없음
본문(BS/IS/CF/SCE)과 달리 주석은 `report_fiscal_year` 에 따른 분기가 아예 없다 —
`assign_note_tables_with_titles()`(parser/xml/section_detector.py:365) 는 시대 구분 없이
단일 경로로 `SECTION-2` 제목을 `classify_dart_section()`으로 분류해 주석 표를 모은다.
지금은 프로덕션에서 `include_notes=False`(본문 우선 단계, report_lines.py 주석 참고)라
드러나지 않았을 뿐 — **주석에서도 구서식(`XI. 재무제표 등`처럼 본문·주석이 한 섹션에
같이 사는 구조, `_detect_legacy_body_statement_tables` docstring 참고)이 이 단일 경로로
못 잡힐 가능성은 검증된 바 없다.** 이번 조사 범위 밖(별도 조사 필요)이지만, 사용자 요청대로
이번 설계의 재시도 메커니즘은 **주석에도 나중에 그대로 얹을 수 있는 모양**으로 만든다.

## 3. 제안 설계

### §1. 입력측 — 원문 CORRECTION 섹션 파싱으로 재확인 (확정: 다운로드 후 별도 패스)

**삽입 지점 확정**: `_parse_fiscal_info()` 자체는 손대지 않는다 — 공시목록 API 메타데이터
만으로 호출되는 시점이라 이 시점엔 XML이 아직 없을 수 있고, 그 함수의 책임(제목 파싱)을
원문 파싱 책임과 섞으면 안 된다(단일 책임 유지). 대신 **`relabel_corp_filings()` 안에 이미
있는 `pe is None`(=제목에 "(YYYY.MM)" 없음) 분기**(`collector/filing_collector.py:274`,
현재는 "구형: 기존 라벨 유지")를 확장한다 — 이 함수는 corp 단위로 매 sync 후 재호출되는
멱등 함수라, XML이 나중에 다운로드돼도 다음 sync에서 자연히 재확인된다(추가 스케줄링 불요).

```python
if pe is None:
    # 구형(YYYY.MM 없음) — ★신규: 정정본이면 원문 CORRECTION 섹션에서 재확인 시도.
    # `_is_amendment(report_nm)`(filing_collector.py:36, 이미 존재하는 일반 정정 판정 —
    # `info["att"]`인 `_is_attachment_amendment`와는 다른 함수, 혼동 주의)로 트리거한다.
    fy, fp = info["fy"], info["fp"]
    if _is_amendment(r.report_nm):
        recovered = _fiscal_period_from_correction_section(rcept, corp_code)
        if recovered is not None:
            fy, fp = recovered
    upd.append({"rcept": rcept, "fy": fy, "fp": fp, "ped": None, ...})
    continue
```

- **트리거 조건**: `report_nm`에 "(YYYY.MM)" 없음 **AND** `is_amendment=True`뿐. 일반 원본
  문서(42건)는 이 CORRECTION 섹션 자체가 없으므로 시도해도 항상 실패 → 자동으로 기존
  접수일 추정 유지. 트리거를 정정본으로 좁혀 불필요한 XML 파싱 비용·오탐 여지를 없앤다.
- **XML 미다운로드 시**: 조용히 `None` 반환(기존 접수일 추정 유지) — 실패로 취급하지
  않는다. 다음 sync 때 XML이 있으면 다시 시도된다(멱등, 재시도 자연 발생).
- **정규식**: `최초제출일\s*[:：]\s*(\d{4})[.\-년]\s*(\d{1,2})` — 실측 샘플 1건
  (`정정대상 공시서류의 최초제출일 : 2006.03.31`) 기준. 매칭 실패는 조용히 폴백(R6 —
  확신 없는 형식은 지어내지 않는다). 구현 착수 시 표본을 더 모아(정정본 3건 전부 +
  가능하면 유사 오래된 정정 샘플) 표기 변형을 검증한다.
- 찾은 날짜는 `compute_fiscal_year_period("annual", year, month, fiscal_month)`에 그대로
  넣어 기존 로직과 동일하게 회계연도·기간을 산출한다(별도 계산식 새로 안 만듦).
- 성공 시 `relabel_corp_filings()`의 나머지 흐름(is_final 재그룹 등)은 무변경 — fy/fp만
  정확해지면 그 다음은 기존 로직이 알아서 올바른 그룹키로 분류한다.

### §2. 추출측 — 양방향 병합-폴백으로 일반화
기존 `_detect_pre2015_body_statement_tables_merged()`의 "섹션코드 단위 setdefault 병합"
패턴을 재사용 가능한 헬퍼로 뽑아낸다:

```python
def _merge_missing_codes(primary: dict, fallback_fn) -> dict:
    """primary 가 못 채운 섹션코드만 fallback_fn() 결과로 보충. 덮어쓰지 않는다.

    본문 탐지기 전용이 아니다 — 딕셔너리 {섹션코드: [(표, 단위, ...)]} in/out 계약만
    지키면 어떤 탐지기 쌍이든(나중에 주석용 pre-2015 탐지기가 생기면 그것도) 재사용 가능.
    호출측이 "언제 fallback_fn 을 부를지"(항상/primary 가 비었을 때만)를 정한다 —
    이 헬퍼 자체는 "채우는 방법"만 담당(단일 책임).
    """
    groups = dict(primary)
    for code, tables in fallback_fn().items():
        groups.setdefault(code, tables)
    return groups
```

`_detect_pre2015_body_statement_tables_merged()`는 이 헬퍼로 재작성(항상 호출, 기존 동작
무변경): `_merge_missing_codes(detect_pre2015_body_statement_tables(root, fin_type, include_sce=True), lambda: _detect_body_statement_tables(root, fin_type, include_sce=True))`.

`extract_report_lines()`의 `else` 분기(2011+ 라우팅)에도 대칭 적용:

```python
if report_fiscal_year <= _PRE2015_ROUTING_MAX_FY:
    groups = _detect_pre2015_body_statement_tables_merged(root, fin_type)
    ...
else:
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    if not groups:   # ★신규 — 완전히 빈 경우에만 반대 방향 폴백. 같은 헬퍼 재사용(§ 위)
        groups = _merge_missing_codes(
            groups, lambda: detect_pre2015_body_statement_tables(root, fin_type, include_sce=True))
        if groups:
            logger.warning(f"[report_lines] {rcept_no}: fiscal_year={report_fiscal_year} 로 "
                            f"2015+ 라우팅했으나 0행 — pre-2015 폴백으로 {len(groups)}개 섹션 "
                            f"복구. fiscal_year 메타데이터 오판정 의심, 확인 필요.")
```

- **확정: 트리거는 "완전히 빈 경우"로 제한**(부분적으로 잡힌 경우는 재시도 안 함) — 2-2에서
  확인한 pre-2015→2015+ 방향과 달리, 이 방향은 아직 실측 검증이 안 됐다. 섣불리 섹션코드
  단위 상시 병합까지 가면(양쪽 다 뭔가 잡히는 애매한 전환기 문서에서) 위험이 늘어난다 —
  1단계는 "0행일 때만 반대쪽 시도"로 보수적으로 시작한다. §5 실측(2011+ 전체에서 폴백이
  실제로 몇 건·어떤 문서에서 발동하는지)으로 안전성이 확인되면, 후속 세션에서 pre-2015
  방향처럼 섹션코드 단위 상시 병합으로 확장할지 별도로 재검토한다(지금 범위는 아님).
- **폴백이 실제로 뭔가 찾으면 반드시 로그** — 조용히 성공 처리하지 않는다. 이건 데이터가
  맞았다는 뜻이 아니라 "라우팅 근거(fiscal_year)가 의심된다"는 신호이므로, 사람이 나중에
  걸러볼 수 있어야 한다(§4 dq_assertion과 연결).

### §3. 주석 파서로의 확장 지점 (지금 당장 구현 아님 — 재사용 가능한 모양만 확보)
`_merge_missing_codes()` 헬퍼는 시그니처를 본문 전용으로 좁히지 않는다(딕셔너리 in/out,
탐지 함수는 인자로 주입) — 나중에 주석에도 pre-2015 전용 탐지기가 생기면 같은 헬퍼를
그대로 재사용할 수 있게. **주석 자체에 지금 시대 분기를 새로 만들지는 않는다** — 2-3에서
확인했듯 주석은 아직 시대 분기가 없고, 그게 실제로 문제인지(구서식 문서에서 주석이
얼마나 새는지)는 별도 census가 필요한 독립 작업이다(이번 설계 범위 밖, 후속 항목으로
기록만 해둔다).

## 4. 부수 안전망 — is_final 그레인 충돌 감시 (확정: 포함)
§1·§2가 이번 근본 원인을 막아도, 미래의 다른 이유(또 다른 무태그 정정본, 결산월 변경
엣지케이스 등)로 같은 그레인 충돌이 또 생길 수 있다 — 이번 사고에서 실제로 관측된 부수
피해(진원생명과학 FY2022 그레인에 `is_final=True` 2개)를 감시할 저비용 안전망을 상시
게이트에 추가한다.

`scripts/dq_assertions.py`의 `CHECKS` 리스트에 신규 항목 추가:

```python
{
    "name": "filings_isfinal_grain_duplicate",
    "sev": "ERROR",
    "desc": "같은 (corp_code, report_type, fiscal_year, fiscal_period)에 is_final=True 2개 이상"
            "이고 그중 period_end_date NULL 인 행이 있음 — 제목 태그 없는 정정/첨부정정이 "
            "태그 있는 형제와 그레인이 갈라진 신호(정상 stub 연도 공존은 이 조건으로 걸러짐)",
    "count": "SELECT count(*) FROM ("
             "  SELECT corp_code, report_type, fiscal_year, fiscal_period, "
             "         bool_or(period_end_date IS NULL) has_null_ped"
             "  FROM filings WHERE is_final AND report_type IS NOT NULL AND fiscal_year IS NOT NULL"
             "  GROUP BY 1,2,3,4 HAVING count(*) > 1"
             ") dup WHERE has_null_ped",
    "sample": "SELECT corp_code, report_type, fiscal_year, fiscal_period, "
              "array_agg(rcept_no ORDER BY rcept_no) rcepts "
              "FROM filings WHERE is_final AND report_type IS NOT NULL AND fiscal_year IS NOT NULL "
              "GROUP BY 1,2,3,4 HAVING count(*) > 1 AND bool_or(period_end_date IS NULL) LIMIT 10",
},
```

- ★★**구현 중 실측 수정** — 최초 설계대로 `(corp_code, report_type, fiscal_year,
  fiscal_period)` 4개 필드만으로 그룹핑했더니 **380건**이 걸렸다. 표본 확인 결과
  그중 **342건은 결산월 변경으로 인한 정상 stub 연도 공존**이었다 —
  `relabel_corp_filings()` 자신의 그레인키 설계(§ 위 재확인)가 "period_end_date 가
  다르면(=진짜 다른 기간) fiscal_year 라벨이 같아도 둘 다 is_final=True 가 맞다"고
  이미 명시하고 있었는데, 최초 설계의 어서션이 그 의도를 반영하지 않고 fy/fp 만 봐서
  거짓양성을 380배(38의 10배) 부풀렸다. **`period_end_date IS NULL 인 행이 하나라도
  낀 경우만**으로 조건을 좁혀 진짜 신호(38건)만 남겼다.
- **38건의 정체**: 전부 "태그 없는 정정/첨부정정이 태그 있는 형제와 그레인이 갈라짐"
  패턴 — 이번 사고(진원생명과학, 원본-정정 16년 격차)와 **같은 근본 메커니즘이지만 더
  흔한 하위유형**이다: 대부분 `[첨부정정]`(`_is_attachment_amendment`, 원본과 며칠 차
  — §1 트리거 대상인 `_is_amendment`=일반 정정과 다름, 원본 문서 참고)이 원본과 같은
  날 또는 며칠 뒤 접수되면서도 제목에 "(YYYY.MM)" 없이 나와 `period_end_date=NULL`로
  영구히 남고, 그레인 키가 원본(ped 있음)과 영영 갈라진다. **§1 은 이 38건을 고치지
  않는다** — §1 트리거는 `_is_amendment`(기재정정)뿐이고, 이 38건 대부분은
  `is_amendment=False`인 첨부정정이라 범위 밖이다.
- **범위 결정(2026-09-12)**: 이 38건은 오늘 설계·구현 범위가 아니다. 이번 세션은
  "회계연도가 완전히 틀리는" 극단 사례(원본-정정 격차가 신고기한을 훨씬 넘는 경우) 1건을
  근본 수정하는 것이 목표였고, 이 38건은 **연도 자체는 대체로 맞지만 그레인 병합이
  안 되는** 별개의(관련은 있는) 버그다. `filings_isfinal_grain_duplicate` 어서션이
  이제 상시 감시하므로, 후속 세션에서 별도 설계 문서로 다룰 백로그로 남긴다(§7).
- **sev=ERROR** — 이 그레인은(stub 예외를 뺀 나머지는) 항상 1개여야 정상이다. 레거시
  `_update_is_final_flags()`(filing_collector.py:175, 정확히 `PARTITION BY corp_code,
  report_type, fiscal_year, fiscal_period`를 그레인으로 쓴다)가 여전히 이 키를 그레인으로
  취급하는 코드로 남아있고, 현재 쓰이는 `relabel_corp_filings()`도 정상 케이스(제목에
  태그 있음)에선 같은 값으로 수렴한다.
- 이번 사고 건은 §1 수정 후 재실행하면 이 어서션에서 사라져야 한다(실측 확인됨, §7).

## 5. 검증 계획
- 회귀 테스트: `fin2/tests/test_report_lines.py`(또는 신규 파일)에 진원생명과학
  20220908000421 재현 케이스 + 기존 pre-2015→2015+ 방향 병합 테스트가 안 깨지는지.
- `collector/` 쪽 테스트에 §1 재확인 로직 단위 테스트(CORRECTION 섹션 있음/없음/형식
  변형 각각) 추가.
- `scripts/dq_assertions.py`에 §4 신규 어서션 추가 후 전체 실행 — 이번 사고 건이
  사라지는지, 기존 어서션들에 회귀가 없는지 확인.
- `docs/PARSING_RULES.md`에 이 라우팅 규칙 변경 기록 + 이 설계문서 링크(CLAUDE.md 정책).
- `docs/runbook_new_parser_pipeline_integration.md` 체크리스트 적용:
  ① 데일리 파이프라인 배선(두 call site: 메인 + `--standardize-only` 재개) 영향 확인,
  ② 소급 백필 필요 여부(§2 폴백이 새로 채우는 rcept가 있으면 그 기간 std_v3 재빌드,
  §1 수정으로 fiscal_year 가 바뀐 corp 는 `relabel_corp_filings()` 재실행만으로 자연히
  정정되지만 이미 잘못된 fiscal_year 로 계층2/3 에 뭔가 적재돼 있었다면 그 부분은 별도
  재적재 필요),
  ③ Gate B 무영향 확인.
- 범위 재확인: §2 폴백 도입 후 2011+ 전체에서 "0행 → 폴백으로 복구됨" 로그가 몇 건
  뜨는지 실측(이번 건 외에 숨어있던 케이스가 더 있을 수 있음 — 지금까지는 재시도 자체가
  없어서 아예 안 보였다).

## 6. 확정된 결정 사항 (2026-09-12)
| 항목 | 결정 |
|---|---|
| §1 삽입 지점 | `_parse_fiscal_info()`는 무변경. `relabel_corp_filings()`의 기존 `pe is None` 분기를 확장(정정본만 트리거) — XML 다운로드 여부와 무관하게 멱등하게 재시도됨 |
| §2 폴백 트리거 범위 | "완전히 0행일 때만" 보수적으로 시작. 섹션코드 단위 상시 병합으로의 확장은 §5 실측 후 별도 재검토(이번 구현 범위 아님) |
| §4 is_final 충돌 감시 | 포함 확정. `scripts/dq_assertions.py`에 ERROR 등급 신규 어서션 추가(구현 중 조건 정교화, §4 본문 참고) |
| §3 주석 파서 확장 | 지금 시대 분기를 새로 만들지 않음. 헬퍼만 재사용 가능한 모양으로 설계(범위 밖 후속 항목으로 기록) |

## 7. 구현 결과 (2026-09-12)

**변경 파일**:
- `collector/filing_collector.py` — `_CORRECTION_ORIG_DATE_RE`, `_fiscal_period_from_
  correction_section()` 신설. `relabel_corp_filings()`의 `pe is None` 분기가 정정본이면
  이걸 호출하도록 확장. `parsed[...]`에 `"amendment"` 키 추가.
- `fin2/extract/report_lines.py` — `_merge_missing_codes()` 헬퍼 신설(범용, 딕셔너리
  in/out). `_detect_pre2015_body_statement_tables_merged()`를 이 헬퍼로 재작성(동작
  무변경). `extract_report_lines()`의 `else`(2011+ 라우팅) 분기에 "0행일 때만" 역방향
  폴백 추가 + 성공 시 `logger.warning`.
- `scripts/dq_assertions.py` — `filings_isfinal_grain_duplicate`(ERROR) 신규 어서션.
- `fin2/tests/test_report_lines.py` — `_merge_missing_codes` 단위 테스트 + 진원생명과학
  실제 파일 기반 역방향 폴백 회귀 테스트(2개).
- `tests/test_filing_collector_correction_recheck.py`(신규) — 정규식 단위 테스트 3개 +
  실제 DB/원문 연동 테스트 1개.

**검증**:
- `pytest tests/ fin2/tests/` — 943 pass(§1·§2 도입 전과 동일한 2건만 실패, 둘 다
  `git stash`로 사전 확인된 이번 변경과 무관한 기존 실패 — biz_section 표 판정 1건,
  뉴인텍 DKME류 basis_fallback 회귀 1건).
- **원본 사고 건 종단 검증**: `relabel_corp_filings(s, "00118521")` 실행 →
  `filings.fiscal_year` 2022 → **2005**로 정정 확인. `extract_report_lines()`를 정정된
  fiscal_year=2005 로 재호출 → **617행** 정상 추출(별도 재무제표, 사용자가 원문에서
  확인한 그 데이터). `is_final` 충돌도 정리(원본 `20060331000117`→False, 정정본
  `20220908000421`→True) + `layer2_review_queue`의 스테일 스냅샷 행 삭제(이제 2005년
  귀속이라 2015+ 캠페인 스코프 밖).
- **§2 폴백 단독 검증**: 같은 파일에 **일부러 틀린** fiscal_year=2022 를 넘겨도
  `extract_report_lines()`가 역방향 폴백만으로 617행을 복구함을 확인(§1 없이도 §2
  단독으로 방어선이 되는지 검증, 회귀 테스트로 고정).
- **§4 어서션 튜닝**: naive 그레인키(380건 위반) → 실측으로 342건이 정상 stub 연도
  공존임을 확인 → `period_end_date IS NULL` 조건 추가로 38건(진짜 신호)만 남김. 이
  38건은 오늘 범위 밖(§4 본문 참고, 후속 백로그).

**소급 백필 — 구현 중 재확인해 정정한 사실(런북 §2 필수 체크)**: `relabel_corp_filings()`는
그 corp가 **오늘 새 필링을 실제로 냈을 때만** 재호출된다(`scripts/collect_new.py` →
`sync_filings(corp_codes=오늘 정기공시 낸 회사만, force=True)` →
`collector/filing_collector.py:587`). 휴면 기업(문제의 필링 이후 한동안 새 공시가 없는
회사)은 **데일리 사이클로 자연 재실행되지 않는다** — 처음에 적어뒀던 "다음 사이클에
자연 반영"은 틀린 가정이었다.
- **원본 사고 건(00118521)**: 이미 이 세션에서 `relabel_corp_filings(s, "00118521")`를
  직접 실행해 DB 를 수정 완료(위 "종단 검증" 참고) — 별도 백필 불요, 이미 끝남.
- **정정본 3건 중 나머지 2건(2002·2004년)**: `_fiscal_period_from_correction_section`
  실측 결과 둘 다 `None`(원문 CORRECTION 섹션 파싱 실패 또는 미다운로드) → 기존 라벨
  유지 → 회귀 없음 확인. 이미 올바른 라벨이었으므로 조치 불필요.
- **38건 백로그**: 이 corp 들도 휴면 상태면 데일리 사이클로 저절로 안 고쳐진다.
  후속 세션에서 **명시적 백필 스크립트**(해당 38개사 corp_code 목록에 대해
  `relabel_corp_filings()`를 직접 호출)가 필요하다.

**아직 안 한 것(의도적, 범위 밖)**:
- 38건짜리 "태그 없는 첨부정정 그레인 미병합" 백로그 — 별도 세션·별도 설계 필요,
  위 백필 스크립트 포함.
- `docs/PARSING_RULES.md` 규칙 기록 — R91로 등재 완료(§7 위 커밋과 함께).

## 8. 추가 검증 — "이미 채워졌는데 회계기간이 틀린 경우"가 더 있는지 (2026-09-12)

사용자 질문: 오늘 고친 건 "0행(보류)"로 실패한 사례인데, **회계연도가 틀렸는데도 추출은
성공해서(0행이 아니라 뭔가 채워져서) 조용히 잘못된 기간에 실데이터가 붙어있는 경우**는
없는지. 두 경로로 조사했다(전부 스크래치패드 1회성 스크립트, DB 직접 조회 — 코드 변경 없음).

### 8-1. 태그 있는 정상 경로(99.98%, 190,973건 전수) — 오류 미발견

1. **다중 태그 매치 위험**: `report_nm`에 `\(\d{4}\.\d{2}\)` 패턴이 2번 이상 나오는 필링
   — **0건**. `_parse_fiscal_info()`의 `re.search`(첫 매치만 씀)가 잘못된 매치를 고를
   여지 자체가 없다.
2. **report_type ↔ fiscal_period 정합성**: annual→FY(54,726) · half→H1(45,790) ·
   quarter→Q1(46,701)/Q3(43,756) = 190,973건 **전수 일치**, 이상 조합 0건.
3. **결정론성**: 같은 (corp_code, report_type, period_end_date)를 가진 서로 다른 rcept가
   다른 (fiscal_year, fiscal_period)를 받은 경우 — **0건**. 입력이 같으면 항상 같은
   결과.

**한계(못 채운 부분)**: DART가 제목 태그 자체에 원문 오류로 틀린 날짜를 인쇄했을 가능성은
이 조사로 배제 못 한다 — 문서 실제 내용(XBRL ACONTEXT의 진짜 회계연도)과 교차검증해야
잡히는데, ACODE/ACONTEXT 속성이 모든 필링에 균일하게 있지 않다(신버전 렌더링에만 존재 —
예: 삼성전자 20200330003851 은 `ACODE`/`ACONTEXT` 속성 자체가 0개, SK스퀘어
20260514001477 은 있음). 전수 교차검증은 커버리지가 고르지 않아 지금 범위에서 보류 —
있다면 그건 저희 파싱 버그가 아니라 DART 원문 자체의 데이터 품질 문제.

### 8-2. `_governing_annual()` — 결산월(FYE) 변경 회사의 interim 기간귀속 — 오류 미발견

**가설**: annual 보고서 타임라인에 결측(gap)이 있는 회사에서, 그 gap 안에 낀
분기/반기보고서가 `_governing_annual()`(gap 이상인 것 중 가장 이른 annual 선택)에
의해 엉뚱하게 먼 미래의 annual 로부터 결산월을 물려받아 `compute_fiscal_year_period()`의
`months_into`/`fiscal_year` 계산이 틀어질 수 있다.

**방법**: annual 타임라인에서 연속 period_end_date 간격이 13개월 초과인 회사를 전수
스캔 → **32개사** 발견. 그중 이 리스크가 실제로 작동할 전제조건(FYE 월 자체가 timeline
안에서 여러 값 = 진짜 결산월 변경 이력)을 가진 회사만 추림 → **9개사**. 이 9개사 전부
직접 원본 타임라인을 열어 확인:
- 8개사(간격 15~23개월)는 결산월 전환 자체가 만드는 **정상적인 간격**이었다(예:
  1월결산→12월결산 전환 시 1개월짜리 스텁 annual과 다음 정상 annual 사이가 원래
  23개월 — 결측이 아니라 전환 산술 그 자체). 그 안에 낀 interim 들의 fiscal_year/
  fiscal_period 도 직접 대조해 전부 정확함을 확인(예: 00365989 는 6월결산 시절
  "quarter 2003-09-30 → FY2004 Q1"처럼 "회계연도=결산이 끝나는 해" 규약대로 정확).
- 1개사(00365989, 84개월 간격, 2010~2015년 공백)는 진짜 장기 결측이었으나, **그 공백
  안에 분기/반기보고서 자체가 아예 없어서**(휴면) 애초에 잘못 귀속될 대상이 없었다.

**결론**: 이론적 실패 조건(장기 annual 결측 **+** 진짜 결산월변경 **+** 그 안에 낀
interim 존재)이 190,973건 전체에서 **한 번도 동시에 발생하지 않았다.** 확인된 오류
없음 — 단, 이 조합을 가진 회사가 미래에(또는 아직 안 본 corp에) 생기면 여전히 이론상
위험은 남아있다(코드 자체를 고친 건 아니라 방어선이 새로 생긴 건 아님, 어디까지나 현재
데이터에 대한 관측).

**종합**: 오늘 R91에서 고친 "0행(보류)" 유형 외에, "이미 채워졌는데 기간이 틀린" 유형은
두 가지 조사 경로 모두에서 확인되지 않았다. 두 조사 다 스크래치패드 1회성 스크립트로
수행(코드/DB 변경 없음, 순수 관측).
