# P3-1 원인 A — 그룹②·③ 잔여 3건 수정 설계 (2026-08-20)

> **상태: 설계만, 구현 미착수.** CLAUDE.md 정책상 계획 문서 작성은 실행 승인이 아니다.
> 아래 3건 각각 사용자 승인 후 개별 착수한다.

## 배경

[[p3-1-r35-cause-a-groupA-fixed-2026-08-20]]에서 "원인 A"(689건 단조성 위반, R34의 30건을
뺀 668건)를 3그룹으로 분해했다. 그룹①(감사기 커버리지 공백, 527건/56개사)은 R35로
해소 완료. 이 문서는 나머지 두 그룹(그룹②·③, 총 138건/21개사)의 원인규명 결과와
수정 설계를 다룬다. 원인규명 상세는 각 메모리에 있다:
[[p3-1-cause-a-group2-root-cause-2026-08-20]], [[p3-1-cause-a-group3-root-cause-2026-08-20]].

---

## 1. 그룹② — R35 `_ni_attribution_text_candidates()` 섹션 경계 버그 (51건/13개사)

### 원인

`fin2/audit/face_audit.py::_ni_attribution_text_candidates()`(R35 신설)가 `<TD>`(비XBRL)
표에서 `"지배...지분/귀속"` 류 레이블을 찾을 때 **부모 섹션을 구분하지 않고** 문서 전체를
스캔한다. 같은 짧은 레이블이 서로 다른 개념의 표에 구조적으로 반복 등장한다:

- 당기순이익 귀속표(진짜 `controlling_ni`) vs 당기총포괄이익 귀속표(다른 개념) — 성도이엔지 실증
- EPS 산정근거 주석(진짜 값) vs 정정 전/후 비교표·SCE 롤포워드 — 카카오게임즈 2022FY 정정본 실증
- 고려아연(BS 필드 `total_assets` 등)도 동일 매커니즘, 2026-08-13 접수 최신 정정 반기보고서

**검증**: 51건(53개 필드-기간, 고려아연은 필드 3개) 전건을 `f"{std_val:,}"` 문자열로
원문 XML(UTF-8/EUC-KR 폴백)에 직접 검색 → **53/53 발견**. std_v3 값은 전부 원문에 실재 —
데이터 오류 0건, 순수 감사기 오탐으로 확정.

### 수정 방향 (안)

앵커 상태기계에 **부모 섹션 헤더 스코프**를 추가한다:
- 직전에 만난 섹션 헤더가 `"당기순이익"`/`"당기순손실"` 류면 후보로 채택
- `"당기총포괄이익"`/`"총포괄손실"`/`"포괄손익"` 류를 만나면 그 섹션이 끝날 때까지
  (다음 `"당기순이익"` 재등장 또는 표/섹션 종료까지) 후보에서 제외
- BS 필드(고려아연류)도 같은 매커니즘인지 1~2건 추가 원문 구조 확인 필요 — 정정 비교표
  판별 규칙이 IS NI 표와 다를 수 있음

### 위험

R35 자체가 어제 신설된 함수라 재수정 시 그룹①(527건→382건 pass 회복)을 깨지 않는지
회귀가 필수. `fin2/tests/test_ni_attribution_text_fallback.py`에 케이스 추가 + 전수 재감사
필요(부록 B 게이트, [[gateb-full-reaudit-is-required-to-close]]).

### 예상 산출물

- `fin2/audit/face_audit.py::_ni_attribution_text_candidates()` 섹션 스코프 조건 추가
- `fin2/tests/test_ni_attribution_text_fallback.py`에 포괄손익/SCE/정정비교표 오탐 케이스 추가
- `docs/PARSING_RULES.md` R36(가칭) 등재
- 전수 재감사로 그룹② 51건 pass 회복 확인 + 그룹① 회귀 없음 확인

---

## 2. 그룹③-a — 상장폐지사 감사 유니버스 미제외 (58건/1개사, 위지윅스튜디오)

### 원인

위지윅스튜디오(01276327)는 2026-08-18 상장폐지 확정(`corporations.delisted_at`).
⓪-4 파이프라인([[delisting-archive-automated]])이 `raw_report`를
`/Volumes/tj_finance_data/archive/delisted/2026/01276327_위지윅스튜디오`로 정상 이관 —
로컬(NAS 정상 위치·SD카드 미러 둘 다)에서 안 보이는 게 **의도된 동작**이다.

CLAUDE.md 스코프("현재 시점 KOSPI/KOSDAQ 상장된 보통주")상 상장폐지사는 이미 대상 밖 —
**std_v3 데이터도, R35 감사기 로직도 버그 아님.** 진짜 문제는 Gate B 감사(재감사/
`face_audit` 생성) 유니버스 쿼리가 상장폐지사를 걸러내지 않아, 아카이브된 문서를 여전히
"감사 대상"으로 붙잡고 `SOURCE_NOT_TRACK_A`로 떨어뜨리는 것.

### 수정 방향 (안)

Gate B 전수 재감사/`face_audit` 생성 스크립트(`gateb_audit.py` 등, 정확한 진입점은
착수 시 확인)의 대상 코드 선정 쿼리에 `corporations.is_active=false` 또는
`delisting_status='confirmed'` 제외 조건 추가. 두 가지 옵션:

- **(A) 감사 유니버스에서 상장폐지사를 아예 제외** — 신규 감사 대상에서 빠짐. 단,
  상장폐지 이전 데이터의 과거 감사 이력(`face_audit` 기존 행)은 남겨둘지 결정 필요
- **(B) 상장폐지사는 별도 상태(`gate_status='archived'` 등)로 표시** — pending/fail로
  안 잡히게 하되 이력은 보존

재발성 있음(상장폐지는 계속 발생) — **단발 백필이 아니라 파이프라인 배선**이 맞다.
`docs/runbook_new_parser_pipeline_integration.md`급 배선 체크 필요할 수 있음.

### 위험

낮음 — 감사 유니버스 필터만 추가, 판정 로직 자체는 무변경.

---

## 3. 그룹③-b — `xbrl_zip`-only 미변환 (29건/7개사, 전사 잔여 1,639건)

### 원인

`download_tasks`에 해당 rcept가 **`xbrl_zip` 파일타입만 `completed`로 등록되고 `xml`이
없음** → `fin2/audit/face_audit.py`의 `file_path_map()`이 `file_type IN ('xml','pdf')`만
찾아서 아예 못 읽음(`SOURCE_NOT_TRACK_A`). 7개사(오리엔탈정공·코디·영우디에스피·링네트·
미원화학·컴투스엔·한울반도체, 29건) 전부 동일 패턴 확인 — 전부 상장 유지 중(제외 대상
아님), 실제 데이터 갭.

**전사 스코프**: `xbrl_zip` completed ∧ 동일 rcept `xml` completed 없음 = **1,639건**,
2015(339)·2016(225)·2017(326)·2018(370)·2019(350)·2020(23)·이후 소수. **2015~2019 집중.**

### 기존 백필과의 관계 — 다른 잔여분

`scripts/redownload_202608_xbrl_zip_bulk.py`(2026-08-19, [[p2-2026-08-19-doosanbobcat-anam-zero-rows-rootcause]]류)는
**2026-08 접수분 한정**으로 이미 처리 완료. 그 스크립트 docstring이 명시적으로 이렇게
적어뒀다:

> Older xbrl_zip completions (2015-2020, pre-2015 backfill era) are untouched —
> different, unrelated, **often-permanent** cases.

즉 "종종 영구적"이라는 전제가 이미 깔려 있다 — **재다운로드만으로 해결 안 될 가능성을
먼저 검증해야 한다.**

### 소표본 재다운로드 결과 (2026-08-20, 실측 완료 — 경로 A 기각)

2015~2019년 각 6건(연도별 고르게, 서로 다른 회사) 총 **30건**을 표본추출해
`download_tasks`를 리셋(`completed/xbrl_zip` → `pending`)하고 실제 `run_downloads()`로
재다운로드 시도:

**결과: 30/30 전부 `[014]`(document.xml 아직 없음) — 회복 0건.**

전건이 `xml_pending_since`만 찍히고 `status=pending`으로 남았다(다운로더가 최대 2개월
재시도하는 정상 동작이지만, 이 시기 filing은 DART가 document.xml을 애초에 제공하지
않는 것으로 사실상 확정). `redownload_202608_xbrl_zip_bulk.py` docstring의 "often-permanent"
예상이 정확히 들어맞음 — **경로 A(재다운로드) 기각.**

테스트 후 30건은 물리 `.zip` 파일 위치(SD카드에서 재확인)로 DB를 원상복구했다
(`completed`/`xbrl_zip`, 원래 `file_path`/`file_size` 그대로) — 리밥 대기 상태로
방치하면 일일 파이프라인이 2개월간 무의미한 [014] 재시도만 반복하기 때문.

### R13(pre-2015 레거시 파서) 재사용 여부 확인 (2026-08-20, 완료 — 재사용 불가·불필요 둘 다)

`fin2/extract/legacy_pre2015.py`(R13)는 **이미 추출된 단일 XML 파일**(`document.xml`)을
입력받아(`extract_report_lines()` → `_parse_xml_file(Path(file_path))`) K-GAAP 구서식의
섹션 중첩 판정만 다르게 하는 모듈이다 — ZIP을 열 수 없다. `document.xml` 자체가 없는
이번 문제와는 입력 형태부터 다르므로 **재사용 불가**(구조적으로 무관).

그런데 표본 zip(`00122694_2015Q1`)을 직접 열어보니 **완전한 XBRL 정본 패키지**였다
(`.xbrl` 인스턴스 + `.xsd` 엔트리포인트 + `dim/cal/pre` 링크베이스 + `lab` 라벨,
8개 파일). 이건 R13이 아니라 **이미 존재하는 별도 파서**(R10,
`fin2/extract/report_lines_xbrl.py::extract_report_lines_xbrl()` +
`collector/xbrl_instance_lines_sync.py`, `parser_track='XBRL_INSTANCE'`)가 정확히
소비하도록 설계된 형식이었다.

**그리고 실제로 이미 돌아가 있었다.** 그룹③-b 7개사 전건(오리엔탈정공·코디·영우디에스피·
링네트·미원화학·컴투스엔·한울반도체)의 `report_lines`를 직접 조회하니 전부 XBRL 인스턴스
출처(`source_ref`가 IFRS 택소노미 영문 개념명, 예: `BS_separate/PropertyPlantAndEquipment`)
행이 27~309개씩 이미 저장돼 있었고, `std_financials_v3`도 정상값(오리엔탈정공 2015Q3
매출 131,915,704,465 등)을 갖고 있었다.

### 진짜 원인 (재확정) — 데이터 갭이 아니라 감사기(face_audit) 커버리지 공백

**그룹③-b는 데이터 누락이 아니다.** R10 파서가 이미 `xbrl_zip`을 정상 처리해 std_v3에
값이 들어가 있다. 유일한 문제는 `fin2/audit/face_audit.py`가 값을 **대조·검증**할 때
쓰는 `file_path_map()`/`read_report_face_tracked()`가 `file_type IN ('xml','pdf')`만
찾아서, xbrl_zip 밖에 없는 filing은 대조할 "face"를 못 만들어 `SOURCE_NOT_TRACK_A`로
떨어뜨리는 것뿐 — **성격상 그룹①(R35, 감사기 커버리지 공백)과 동류**다.

### 수정 방향 (상세 설계, 2026-08-20)

#### 독립성 트레이드오프 — 먼저 결정할 것

`face_audit.py` 모듈 docstring의 핵심 원칙(PRD 04): "표준화 파이프라인과 독립 —
reconcile·standardize 를 거치지 않고 원본 보고서의 face 표를 **직접 다시 읽는다** →
같은 버그를 양쪽이 공유하지 않음." Track A(XBRL inline)·B(텍스트)·C(PDF) 모두 원본
파일을 매번 독자적으로 재파싱한다(DB를 전혀 읽지 않음).

두 가지 구현 옵션:

| 옵션 | 방식 | 잡아내는 버그 | 못 잡는 버그 |
|---|---|---|---|
| **(A, 권장)** `extract_report_lines_xbrl()`을 감사 시점에 **다시 호출**해 zip을 재파싱 | DB 저장(`store_report_lines`) 버그, layer3 `combine.py`(계층3 집계) 버그 | `report_lines_xbrl.py`(R10) 파서 자체의 추출 로직 버그(부호·스케일·개념매핑 오류) |
| (B) 저장된 `report_lines` 행을 그대로 읽어 `FaceLine`으로 변환 | 위 둘 다 못 잡음(변환만 검증) | 위 + 저장 버그까지 통과 |

**(A) 권장** — zip이 작아 재파싱 비용이 낮고(표본 30건 다운로드 시 이미 실측: zip 자체는
수백KB, `extract_report_lines_xbrl()`은 daily 파이프라인에서 이미 상시 실행되는 비용),
Track A/B/C와 같은 "항상 원본에서 재유도" 관례를 지킨다. 단, **R10 파서 자체의 버그는
여전히 못 잡는다** — Track A(문서 내 별개 XBRL 태그 직접 스캔)만큼 완전독립은 아니다.
이 잔여 한계는 아래 Track 분류에서 명시적으로 반영한다(확정버그로 승격 금지).

#### 새 함수: `read_report_face_xbrl_zip()`

`fin2/audit/face_audit.py`에 신설:

```python
def read_report_face_xbrl_zip(
    zip_path: str | Path, *, corp_code: str, rcept_no: str,
    report_fiscal_year: int, report_fiscal_period: str,
    period_end_date: date | None,
) -> list[FaceLine]:
    """Track D(XBRL_INSTANCE zip) face 재추출. extract_report_lines_xbrl()(R10)을
    감사 시점에 재호출 — 저장된 report_lines 를 읽지 않고 원본 zip 을 다시 연다
    (Track A/B/C 와 같은 '항상 원본 재유도' 관례, 위 독립성 표 참고)."""
    from fin2.extract.report_lines_xbrl import extract_report_lines_xbrl
    from parser.common.account_mapper import get_mapper

    rows = extract_report_lines_xbrl(
        zip_path, rcept_no=rcept_no, corp_code=corp_code,
        report_fiscal_year=report_fiscal_year, report_fiscal_period=report_fiscal_period,
        period_end_date=period_end_date,
    )
    mapper = get_mapper()
    lines = []
    for r in rows:
        if r.col_index != 0 or r.value_won is None:
            continue
        mapping = mapper.map(r.label_raw, fs_section=r.statement.lower())
        canon = mapping.account_code
        if not canon or canon.startswith("unknown."):
            continue
        lines.append(FaceLine(
            statement=r.statement, basis=r.basis, acode=r.label_raw[:80],
            canonical=canon, label=r.label_raw[:80],
            displayed_value=r.value_won, adecimal=None,
            is_cumulative=r.is_cumulative, from_gapfill=False,
        ))
    return lines
```

필드 매핑 근거:
- `canonical`은 `report_lines`에 없다(계층2는 canonical 미보유가 설계, 모듈 docstring
  "canonical 이 없으니 애초에 합쳐야 할 이유가 없다" 참고) — **Track B와 동일하게
  `account_mapper.get_mapper().map(label_raw, fs_section=...)`로 텍스트 매핑**한다.
  `label_raw`는 R10이 이미 라벨 카탈로그(`lab_*.xml`)로 해석한 한글 라벨이라 Track B의
  입력과 동질적 — 매퍼 재사용에 무리 없음.
- `displayed_value=value_won, adecimal=None` — R10이 이미 원 단위로 환산 완료(XBRL
  `ADECIMAL`/scale 처리를 R10 내부에서 끝냄). `FaceLine.amount_won`은 `adecimal=None`이면
  `displayed_value`를 그대로 원값으로 쓰므로 이 조합이 맞다.
- `from_gapfill=False` — 이 값은 R35의 "표제인식실패→휴리스틱 텍스트폴백" 의미와 달리
  **정식 XBRL 인스턴스 사실**이라 `from_gapfill` 의미론과 안 맞는다. 신뢰도 격하는
  아래 Track "D" 분류로 별도 처리한다(from_gapfill 오버로드하지 않음).

#### 배선 지점

1. **`read_report_face_tracked()`**(`face_audit.py:778`) — 현재 파일 확장자로만
   Track 분기(`.pdf`→C, 그 외 XML 파싱 시도). `.zip`은 이 시그니처(`file_path` 하나)로
   분기할 수 없다 — `extract_report_lines_xbrl()`이 `corp_code`/`report_fiscal_year`/
   `report_fiscal_period`/`period_end_date`를 요구하는데 이 함수는 그 컨텍스트를 안 받는다.
   **`read_report_face_tracked()` 자체는 건드리지 않고**(Track A/B/C 회귀위험 0),
   Track D는 호출부(아래)에서 별도 분기로 처리한다.
2. **`scripts/gateb_audit.py`**(유일한 프로덕션 호출부 — `fin2/audit/line_audit.py`는
   docstring 참조뿐 실제 호출 없음, 확인 완료) — 두 곳 수정:
   - `file_path_map()`(L76~82): `file_type IN ('xml','pdf')` → `('xml','pdf','xbrl_zip')`로
     확장.
   - `face_of()`(L158~166): `fp`가 `.zip`으로 끝나면 `read_report_face_xbrl_zip()` 호출
     (해당 row의 `corp`/`fiscal_year`/`fiscal_period`/`period_end_date`를 넘겨야 하므로
     `face_of()`가 현재 `rc`만 받는 시그니처를 이 케이스에 한해 row 컨텍스트도 받도록
     확장 필요 — `_row_rcepts()` 호출부에서 이미 row를 순회하므로 배선 자체는 국소적).
     `track="D"`로 `track_of[rc]` 채움.
3. **`gate_status_for_row()`**(`face_audit.py:1010`) — **가장 잊기 쉬운 지점.**
   `if any(fail_field_tracks.get(f) not in ("B", "C") ...)`가 **B/C만 하드코딩된
   비-확정버그 allowlist**라, Track D를 여기 추가 안 하면 Track D의 모든 불일치가
   자동으로 `fail_a`(확정버그, 메인뷰 차단)로 승격된다 — 독립성이 B/C보다도 약한
   Track D에게 A와 같은 최고 신뢰도를 주는 것은 방향이 거꾸로다. **`("B", "C")` →
   `("B", "C", "D")`로 수정 필수.**

#### 검증 범위

- 그룹③-b 표본 7개사 29건 재감사 → `SOURCE_NOT_TRACK_A` 소멸, pass 또는 fail_b/pending
  적절히 재분류되는지 확인.
- 전사 1,627건 재감사(2. 배선 이후) — 신규 fail_a 0건 확인(Track D가 fail_a로 새지
  않는지가 §3 게이팅 수정의 핵심 검증 포인트).
- 진짜 추출 실패 12건은 이 트랙과 무관 — R10 자체 잔여 결함으로 별도 소규모 조사.

### 위험

**중간.** 새 재무제표 파서는 아니지만(R10 재사용), face_audit 핵심 게이팅 로직
(`gate_status_for_row()`)을 건드리는 변경이라 그룹②(R35)만큼 국소적이지 않다.
`("B","C")` 하드코딩 갱신을 빠뜨리면 조용히 대량 fail_a 오탐을 만드는 회귀가 되므로
반드시 전수 재감사로 fail_a 증가 0을 확인해야 한다.

---

## 공통 게이트 (착수 시)

세 건 모두 [[gateb-full-reaudit-is-required-to-close]] 원칙 적용 — 표본으로 닫지 않고
전수 재감사까지 확인. `pytest tests/ fin2/tests/` 회귀 기준선 유지, fail_a 증가 0,
단조성(pass→fail/pending 전이) 0건.

## 다음 세션 시작점

1. 어느 것부터 착수할지 사용자 결정 (독립적 3건, 순서 무관하게 진행 가능)
2. ~~그룹③-b~~ — **원인규명 완료(2026-08-20)**. 재다운로드 기각(30/30 [014]) →
   R13 재사용 불가 확인 → **진짜 원인은 데이터 갭이 아니라 face_audit의 xbrl_zip
   대조 경로 부재**로 재확정(그룹①과 동류). 다음은 §3 수정방향 1~2(어댑터 설계) 착수
   또는 3(전사 1,639건 중 진짜 0행 실패 섞여있는지 DB 쿼리로 선별)부터
