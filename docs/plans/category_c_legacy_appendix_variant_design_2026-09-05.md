# Category C (E) "XI.부속명세서" 컨테이너 인식 추가 — 설계 (2026-09-05)

> **상태: 설계 완료, 구현 미착수(승인 대기).** CLAUDE.md 정책 — 계획 문서 작성은
> 실행 승인이 아니다. 아래 코드 변경은 **한 줄도 적용되지 않았다.**

## 0. 배경

`v2-drop-remaining-backlog-2026-09-03`(메모리) 항목 1-b, `docs/plans/
factv2_stdv2_gc_backfill_backlog_2026-09-01.md` §3 2026-09-05 블록의 원인규명
결과 — Category C fy2004~2017 실패 5,739건 중 **(E) "XI.부속명세서" 컨테이너
미인식이 4,228건(73.7%)으로 최대 버킷**, fy2009 한 해에만 3,928건이 몰려 있다.

이 문서는 (E) 하나만 고치는 계획이 아니다 — **아래 §1에서 보이듯 (E)만 고치면
이 4,228건의 BS(재무상태표)가 거의 전부 여전히 빠진다.** 그래서 (E)+(D)+(B) 3개를
묶어서 설계했다. 사용자가 (E)만 원하면 §5의 "축소 옵션"대로 (E)만 떼어 갈 수 있다.

## 1. 왜 (E) 단독으로는 부족한가 — 실측(2026-09-05, 무작위 40건 재추출)

fy2007~2010 "부속명세서" 버킷 40건에서 실제 헤딩 텍스트를 뽑아
`classify_legacy_statement_heading()`에 직접 통과시킨 결과:

| 헤딩 텍스트 | 결과 | 건수 |
|---|---|---|
| `손익계산서` | ✅ 인식 | 39 |
| `현금흐름표` | ✅ 인식 | 39 |
| `자본변동표` | ✅ 인식 | 37 |
| **`재무상태표(대차대조표)`** | ❌ **미인식** | **37** |
| `나. 손익계산서` / `라. 자본변동표` / `마. 현금흐름표` 등(가나다 접두) | ❌ 미인식 | 8 |
| `18./23./24.·· 포괄손익계산서` 등(숫자 접두) | — 정상 거부(주석 헤딩, 의도된 동작) | 8 |

즉 **BS 헤딩은 40건 중 37건(92.5%)이 "재무상태표(대차대조표)" 병기 표기**라
(D)를 같이 안 고치면 (E)를 고쳐도 IS/CF/SCE만 살아나고 **가장 많이 쓰이는
BS(총자산·총자본 등)는 계속 빠진다.** 소수(8건)는 가나다 열거접두 문제(B)도
겹친다. (E) 단독 구현은 "고쳤는데 체감 회수율이 낮다"는 재작업을 부른다.

## 2. 코드 변경안 (3개, 전부 추가적·기존 케이스 무변경)

### (E) 레거시 컨테이너 동의어 추가 — `parser/xml/section_detector.py`

`SEC_LEGACY_FS = "재무제표등"` 옆에 신설(라인 269 부근):

```python
# ★2026-09-05(설계, R69 예정) — "XI.재무제표 등"의 동의어 컨테이너. fy2007~2010
# (특히 2009, 후보 3,928건) 분기/반기보고서는 재무제표를 "XI.부속명세서"
# SECTION-1 아래 나열한다 — 헤딩→표 인접구조는 SEC_LEGACY_FS와 완전히 동일하고
# 컨테이너 표제 문자열만 다르다(실측 무작위 300건: 부속명세서 249 · 재무제표등 14).
# `_DART_SECTION_EXACT`엔 일부러 안 넣는다(SEC_LEGACY_FS와 같은 이유 — 주석표
# 유입 차단), `_detect_legacy_body_statement_tables`의 전용 폴백으로만 쓴다.
SEC_LEGACY_APPENDIX = "부속명세서"
```

`fin2/extract/text.py`의 `_detect_legacy_body_statement_tables()`(현재 L388-390):

```python
# 현재
elements = iter_section_elements(root, SEC_LEGACY_FS)
if not elements:
    return {}
```

```python
# 변경 후
elements = iter_section_elements(root, SEC_LEGACY_FS)
if not elements:
    # R69(설계) — SEC_LEGACY_APPENDIX 주석 참고. "재무제표등"이 있으면 그걸 그대로
    # 쓰고(이 분기 자체가 안 탐, 기존 동작 100% 무변경), 없을 때만 시도.
    elements = iter_section_elements(root, SEC_LEGACY_APPENDIX)
    if not elements:
        return {}
```

import 줄(`fin2/extract/text.py` 상단)에 `SEC_LEGACY_APPENDIX` 추가.
**그 아래 pending/heading/데이터표 로직은 한 글자도 안 건드린다** — 두 컨테이너가
같은 내부 구조라 재사용이 곧 검증(87건 실측 근거 그대로 승계).

### (D) 괄호 병기 표제 — `fin2/extract/statement_titles.py`

L413 부근에 상수 추가:

```python
# ★2026-09-05(설계) — IFRS 전환기 신·구 명칭 병기("재무상태표(대차대조표)").
# 실측(부속명세서 버킷 40건): BS 헤딩의 92.5%가 이 형태. 괄호 안이 6종 재무제표명
# 중 하나면 통째로 "명칭의 일부"로 보고 건너뛴다(사람이 참고용으로 구명칭을
# 덧붙인 것뿐 — 새 정보 없음, 짐작 아니라 표기 관행 그 자체).
_LEGACY_ALT_NAME_PAREN = re.compile(
    r"^[（(](?:연결|별도|개별)?"
    r"(?:재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표)[)）]"
)
```

`classify_legacy_statement_heading()` 본문(현재 L480-484):

```python
# 현재
rest = t[m.end():].lstrip("：:·-—")
if rest:
    if not _LEGACY_PERIOD_AFTER.match(rest):
        return None
```

```python
# 변경 후
rest = t[m.end():].lstrip("：:·-—")
if rest:
    alt = _LEGACY_ALT_NAME_PAREN.match(rest)
    if alt:
        rest = rest[alt.end():]           # 병기 괄호 소비 — 나머지로 재판정
    if rest and not _LEGACY_PERIOD_AFTER.match(rest):
        return None
```

### (B) 한글 가나다 열거접두 — `fin2/extract/statement_titles.py`

L413 부근(숫자접두 규칙 옆)에 상수 추가:

```python
# ★2026-09-05(설계) — 숫자/로마숫자 접두(_LEGACY_ENUM_PREFIX)와 의미가 다르다:
# 이 문서군에서 숫자 접두("18.포괄손익계산서")는 여전히 주석 항목번호이지만(그대로
# 거부 유지), 가나다 접두("가.대차대조표")는 재무제표 목록 전용 열거기호다.
# 딱 한 글자만 벗기고(중첩 없음), 벗긴 뒤 _LEGACY_HEAD 가 재무제표명에 안 걸리면
# (예 "가.대손충당금설정내역") 그대로 거부되므로 새 오탐 경로가 생기지 않는다.
_LEGACY_KO_ENUM_PREFIX = re.compile(r"^[가나다라마바사아자차카타파하]\s*[.．)）]")
```

`classify_legacy_statement_heading()` 본문(현재 L468-470):

```python
# 현재
t = re.sub(r"\s+", "", text)
if not t or _LEGACY_ENUM_PREFIX.match(t):
    return None
```

```python
# 변경 후
t = re.sub(r"\s+", "", text)
if not t or _LEGACY_ENUM_PREFIX.match(t):
    return None
t = _LEGACY_KO_ENUM_PREFIX.sub("", t, count=1)
```

(그 아래 `_LEGACY_EXCLUDE`/`_LEGACY_HEAD` 매칭은 이 stripped `t`를 그대로 씀 —
로직 변경 없음.)

## 3. 왜 안전한가 (회귀 위험 근거)

- 세 변경 다 **추가적**이다 — 기존에 통과하던 케이스의 판정 경로를 안 건드린다.
  (E)는 `SEC_LEGACY_FS`가 이미 있으면 새 분기 자체가 실행 안 됨. (D)/(B)는 기존에
  `return None`으로 끝나던 곳에 "한 번 더 벗겨보고 그래도 안 되면 여전히 None"을
  끼워넣는 것뿐 — 이미 성공하던 헤딩의 결과는 절대 안 바뀐다(성공 경로는 벗기기
  전에 이미 `_LEGACY_HEAD.match`를 통과해 `if rest:` 분기 자체에 안 들어가거나,
  `rest==""`으로 조기 성립).
- 이 폴백(`_detect_legacy_body_statement_tables`)은 **이미 SEC_CONSOL_FS/SEC_SEP_FS
  둘 다 없을 때만** 호출된다(`_detect_body_statement_tables` 게이트, `text.py:247-249`)
  — 즉 오늘 기준 이 경로가 도는 문서는 전부 **현재 0행**이다. 잘못 걸려도
  "0행→오염된 값"이 아니라 "0행→결측이지만 틀린 값은 아닌 행"이 최악이고, 그마저
  `classify_legacy_statement_heading`의 5조건(§원문 docstring)과 `_table_has_data_rows`
  가 이미 막아온 것과 동일한 안전장치를 그대로 물려받는다.
- 표 선택·단위판정(`declared_unit`)·pending-거리제한(`_LEGACY_PENDING_SPAN`)·
  주석마커 차단(`is_legacy_note_marker`) — **전부 무변경**. 새 컨테이너도 같은
  안전장치를 그대로 통과해야 데이터표를 얻는다.
- account_mapper/build_corp 단의 `_resolve()` 충돌감지(2026-09-05 PDF복구 트랙에서
  실측 검증된 안전망, `v2-drop-remaining-backlog` 항목1)가 이 경로에도 동일하게
  적용된다 — 애매한 값은 NULL+conflicts, 확정값만 채택.

## 4. 검증 계획 (구현 승인 후 순서)

1. **드라이런**: 코드 적용 후 DB에 쓰지 않고 fy2007~2010 "부속명세서" 버킷 표본
   (계층화 추출 — 연간/반기/분기 × KOSPI/KOSDAQ, 최소 40~60건, §1 재사용 가능)에
   `extract_report_lines()` 직접 호출 → 추출된 BS/IS/CF 값을 DART 웹뷰어 원문과
   **전부 대조**(`feedback-verify-against-source` 원칙). 이때 §1에서 확인 못한
   잔존 변종(가나다 6번째 이후 항목, 병합텍스트 "2.연결재무제표(1)연결대차대조표"
   같은 저빈도 케이스)도 같이 걸러진다 — 나오면 스코프 밖으로 명시하고 후속 트랙.
2. **정량 재실측**: §1 스크립트를 5,739건 전체(또는 최소 (E)+(D)+(B) 해당 버킷
   4,228+510건)에 재실행해 회수율(성공/부분성공/여전히실패) 집계.
3. **회귀 테스트**: `pytest tests/ fin2/tests/`(★프로젝트 습관 — 루트 없이 돌리면
   NAS 심링크에서 멈춤). 기존 "재무제표등" 87건 계열 케이스가 안 깨졌는지 특히 확인.
4. **Gate B**: 새로 채워지는 (corp,fy,fp)는 전부 이전에 완전히 비어있던 자리라
   전이표 비교가 무의미 — 항목1(PDF복구) 때와 같은 논리로 **격리성 확인**(새
   report_lines가 기존 비어있던 자리만 채우는지 grep/SQL로 실측)으로 대체.
5. `dq_assertions.py` 전수 — 특히 `statement_magnitude_impossible`/
   `std_v3_conflicts_unresolved` 증가폭이 이 스코프 안에서만 나는지 확인.

## 5. 백필 계획 (구현·검증 통과 후)

- **배선은 불요** — `extract_report_lines()`/`_detect_legacy_body_statement_tables()`는
  이미 데일리 파이프라인(`scripts/collect_new.py` L173 `_sync_layer2_lines` 단일
  call site 확인 완료, `--standardize-only` 재개 경로도 같은 함수 재사용)에 배선된
  기존 함수 **내부** 로직만 고치는 것이라, `docs/runbook_new_parser_pipeline_
  integration.md` 체크리스트 ①(신규 파서 배선)은 해당 없음 — **②(소급 백필)만 필요.**
- 백필 대상: 이 원인규명에서 나온 (E)+(D)+(B) 해당 rcept 전체(재실측 필요, §4-2).
  실행 패턴은 `scripts/backfill_stdv3_gap_category_c_2026-09-01.py`와 동일한
  `sync_layer2_lines(corps=…)` → `build_corp(session, corp, …)` 2단계, 멱등
  (rcept 단위 delete-then-insert + corp 단위 delete-then-insert) 그대로 재사용
  가능 — corp 목록만 이번 스코프로 새로 뽑으면 됨.
- 규모가 커서(4,228+α건) 실행 시간 예상 필요 — 항목1(PDF복구, DART 웹 쓰로틀링
  때문에 느림) 케이스와 달리 이건 **로컬 XML 재파싱**이라 훨씬 빠를 것으로
  예상되나, NAS 마운트 I/O가 병목일 수 있음(이번 조사에서 실측: 1,000파일/~24분)
  — 전량이면 대략 2시간대, 정확한 추정은 드라이런 이후 갱신.

## 6. 축소 옵션 — (E)만 원할 경우

(E)만 넣으면: fy2009~2010 "부속명세서" 문서의 **IS/CF/SCE는 대부분 살아나지만
BS는 92.5%가 계속 빠진다**(§1). 그래도 원하면 §2의 (E) 블록만 적용 가능 — 나머지
두 변경과 독립적이라 부분 적용 안전. 다만 총자산/총자본 같은 핵심 BS 지표가 이
스코프에서 계속 빠지는 결과이므로, 사용자 결정 필요.

## 7. 스코프 밖(잔존, 이번 설계로 안 건드림)

- fy2004~2006 (A) SECTION-3 서브헤딩 리셋 문제(943건) — `assign_tables_to_dart_
  sections()` 쪽 별도 설계 필요, 이 문서와 무관.
- "요약" 접두(C, 2014 삼성증권 계열) — `_LEGACY_HEAD` 수식어 목록 확장 필요,
  이번 스코프에 없음(사용자가 원하면 §2와 같은 패턴으로 쉽게 추가 가능 — 별도 승인).
- 저빈도 잔존(§1에서 발견): 가나다 열거 6번째 이후 미확인, 병합텍스트("2.연결
  재무제표(1)연결대차대조표"), "(첨부)재무제표" 표제 변종(300건 중 1건) — 개별
  대응 가치 낮음, 드라이런에서 잔존 실패율로 재확인 후 필요 시 별도 트랙.
- parse_error 52건(파일 자체가 디스크에서 소실 — 별도 `missing_file` 이슈, 이
  설계와 무관).

## 8. PARSING_RULES.md 반영 (구현 승인 시점에 수행, 지금은 안 함)

CLAUDE.md 규칙대로 "규칙을 새로 정하면 `docs/PARSING_RULES.md`에 먼저 적고
코드/문서를 링크"한다 — 구현 승인 직후, 코드 작성 **전에** R69로 이 설계를
정식 등재하고 이 파일을 링크한다(지금은 계획 문서 단계라 미등재).
