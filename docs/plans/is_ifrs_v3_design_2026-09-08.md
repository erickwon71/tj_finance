# `std_financials_v3.is_ifrs` 설계 (2026-09-08)

상태: **✅구현+전사백필+검증 완전 종료(2026-09-08, 같은 날)**. 아래는 설계 근거
기록(변경 없음) — 실제 구현 결과는 메모리 `is-ifrs-v3-design-2026-09-08.md` 참고.
요약: 스코프가 설계 당시 "pre-2015"에서 구현 중 "전사"로 확장됨(2015+ 필링도 컬럼
신설 직후 일시적으로 NULL 회귀가 생기는 걸 발견해 같이 해결) — filings.ifrs_evidence
177,884건 판정 + std_financials_v3.is_ifrs 전사 재빌드, dq_assertions 신규 ERROR 0,
`pytest tests/ fin2/tests/` 873 passed(회귀0). 부산물로 `store_report_lines()`에
수동입력(`unit_source='manual'`) 데이터 보호 가드도 신설(비대칭 보호 gap 발견·수정).

관련 메모리: [[v2-drop-remaining-backlog-2026-09-03]] 항목4, `std_v2_retirement_port_to_v3_2026-08-22.md` §4.

## 1. 문제

`std_financials_v3`에는 `is_ifrs` 컬럼 자체가 없다. 이를 노출하는 `standard_financials`
뷰(`collector/db.py:733,848,946,1169` 등 5곳)는 전부 `TRUE AS is_ifrs` 상수로 채우고,
`fin2/standardize/calendar_v3.py:56`(`_load_asfiled_v3`)도 같은 이유로 `d["is_ifrs"] = True`를
강제한다.

이 상수화의 원래 근거(`collector/db.py:719` 주석): "v3는 2015+ 데이터만 있고, 2015+는
전량 K-IFRS 의무화 이후라 TRUE로 둬도 된다."

**이 근거가 지금은 사실이 아니다.** 그동안(Category C 백필, R69~R71 등) v3는 1999년까지
소급 확장됐다. 실측(2026-09-08, `std_financials_v3` 전수):

| 구간 | 행수 | 비고 |
|---|---:|---|
| pre-2011 (K-GAAP 시대) | 85,159 | 대부분 실제 K-GAAP일 가능성 높음 |
| 2011–2014 (의무화 전환기) | 46,867 | 조기도입/의무화 혼재, 개별 확인 필요 |
| 2015+ | 190,566 | 원 가정(전량 IFRS)이 유효한 구간 |

즉 전체 322,592행 중 **132,026행(약 41%)**이 원 가정이 성립하지 않는 구간인데도
`is_ifrs=TRUE`로 노출되고 있다 — 표시 정확도 이슈가 아니라 **실제로 상당수가 오답일
가능성이 있는 데이터 결함**이다.

## 2. 기존 v2 선례 — 재사용할 설계 원칙

`fin2/standardize/build.py::_derive_is_ifrs()`(std_v2용, 이미 폐기된 테이블이지만 로직은
유효)가 이미 이 문제를 풀어본 적이 있고, 그 설계 원칙이 이 프로젝트의 핵심 정책과
일치한다:

> ★ 2026-07-17(F7): "로직으로 값을 정해서 db에 적재하는 것은 없도록 해" — 연도 기준
> 추론(`fy >= 2011`)을 제거하고, **원문에서 읽은 증거가 있을 때만 값을 채운다.**

v2의 3분류:
- **True**: 해당 rcept가 Track A(ACODE 태깅, `ifrs-full_`/`dart_` 접두 XBRL 개념)로
  추출된 fact를 하나라도 가짐 — 원문이 IFRS 택소노미를 실제로 썼다는 직접 증거.
- **False**: `standardize_kgaap_gap_corp()`가 만든 파생행(`kgaap_gap` 마커) — 이건 K-GAAP
  갭 채우기 전용 합성 경로라 별도 트랙, v3에 곧바로 대응 개념 없음(§5 참고).
- **None(NULL)**: 증거 없음. 소비 측(`curr.get('is_ifrs', True)`, `analyzer/display/table_view.py:120`)이
  이미 NULL을 "IFRS로 표시"로 관례화해 처리하므로 하위호환 안전.

이 원칙을 그대로 v3에 이식하는 것이 이번 설계의 핵심이다 — **연도로 추측하지 않고,
원문 증거로만 채운다.**

## 3. v3에서 쓸 수 있는 증거

- **Track A (ACODE)**: v3 report_lines 자체는 ACODE를 저장하지 않지만
  (`collector/models.py:335` docstring: "acode 처럼 정규화하지 않는다"), 같은 document.xml을
  다시 열어 ACODE 셀 존재를 읽는 기존 재사용 가능 도구가 이미 있다 —
  `fin2/audit/face_audit.py::read_report_face_xbrl()`("Track A가 아니면 빈 리스트")와
  `fin2/extract/report_lines_inline_xbrl_overlay.py`가 실전에서 이미 이 경로를 쓰고 있다.
  즉 "이 rcept에 ifrs-full_/dart_ ACODE 셀이 하나라도 있는가"는 기존 코드로 판정 가능.
- **Track D (XBRL instance zip)**: `fin2/extract/report_lines_xbrl.py`로 추출된 rcept는
  정의상 공식 IFRS 택소노미(instance zip 자체가 IFRS 개념만 담음) — 소스 트랙 자체가
  곧 증거.
- v2의 `kgaap_gap`처럼 "K-GAAP임을 적극적으로 확정"하는 v3 쪽 증거는 아직 없음(§5).

## 4. 제안 설계

1. **컬럼 추가**: `std_financials_v3.is_ifrs BOOLEAN NULL` — 마이그레이션은 R73
   (`unit_overrides` jsonb 추가) 패턴 재사용, idempotent `ALTER TABLE ... ADD COLUMN IF
   NOT EXISTS`.
2. **증거 캐시**: rcept 단위로 한 번만 계산해 캐싱(모든 build_std_v3 호출마다 XML을
   재파싱하지 않도록 — `face_audit` 테이블이 Gate B 감사결과를 캐싱하는 것과 같은 패턴).
   후보:
   - (a) `filings` 테이블에 `has_track_a_evidence BOOLEAN` 컬럼 추가, Layer 2 추출
     시점(`report_lines.py`/`report_lines_xbrl.py`가 이미 그 document.xml을 열어본
     시점)에 같이 채움 — 신규 XML 재오픈 비용 없음. **권장.**
   - (b) 별도 테이블 `rcept_taxonomy_evidence(rcept_no PK, has_track_a, source_track)`.
   - 둘 다 전수 백필 스크립트 1회 필요(기존 raw_report 대상, `feedback-bulk-read-use-sdcard`
     메모리대로 SD카드 경유).
3. **조립 로직**: `fin2/layer3/combine.py`(또는 `build_std_v3.py`가 std_v3 행을 쓰는
   지점)에서 `source_rcepts`(BS/IS/CF)에 걸린 rcept 중 하나라도 Track A 증거가 있거나
   Track D 출처면 `is_ifrs=True`, 그 외엔 `NULL`.
4. **소비처 정리**:
   - `collector/db.py`의 5개 `TRUE AS is_ifrs` → `v3.is_ifrs AS is_ifrs`로 교체.
   - `fin2/standardize/calendar_v3.py:56`의 강제 `True` 제거, 실 컬럼값 사용(`SELECT *`라
     이미 컬럼이 딸려옴).
   - 표시 측(`analyzer/display/table_view.py:120`)은 이미 `curr.get('is_ifrs', True)`로
     NULL-안전 — 변경 불요.
5. **파이프라인 배선 — CLAUDE.md 필수 절차 그대로 적용**:
   ① `scripts/collect_new.py` 두 call site(메인 + `--standardize-only` 재개) 배선,
   ② 전사 소급 백필(별도 스크립트, 자동 아님),
   ③ 검증(회귀 테스트 + `dq_assertions` 무영향 확인 + Gate B 영향 없음 확인 — `gate_b_status`는
   `face_audit` 별개 테이블 조인이라 이 변경과 무관해야 함).

## 5. 열린 질문 — 사용자 결정 완료(2026-09-08)

- **"False" 확정 경로**: ✅ **함께 설계한다** — v2의 `kgaap_gap`(합성 파생행)과 달리,
  이번엔 원문 표지/각주 문구를 직접 판독해 "이 필링은 K-GAAP였다"를 적극적으로 확정하는
  경로를 만든다. §5-1 참고.
- **증거 캐시 저장 위치**: ✅ **`filings` 테이블에 컬럼 추가**(§4-(a) 채택) — Layer 2
  추출이 이미 그 document.xml을 열어보는 시점에 같이 채워 XML 재오픈 비용 없음.
- **백필 순서**: ✅ **pre-2015 전체(132,026행)를 한 번에** — 2011~2014 전환기까지 같이
  처리, 두 번 나눠 할 필요 없음.

### 5-1. "False" 확정 판정 — 실측 근거 (2026-09-08, 원문 표본 확인)

pre-2011 표본(00200910 아이즈비전, `annual/2005/20060330001585.xml`) 원문대조로 확인한
결과, K-GAAP 시대 필링은 IFRS 시대와 **어휘 자체가 다른** 표준 표기를 쓴다:

- K-GAAP 시대: "**기업회계기준서 제N호**"(번호 붙은 구 기준서 — 예 "제1호 내지 제17호")
- IFRS 시대: "**한국채택국제회계기준**"/"K-IFRS"(관례상 이 표현)

즉 두 어휘가 상호 배타적인 명확한 신호라 판정기 자체는 원리상 단순 텍스트 매칭으로
가능해 보인다. 단, **이미 알려진 함정 2종**을 피해야 한다(둘 다 기존 코드 주석에서
이미 확인된 패턴, `parser/xml/section_detector.py:53`/`fin2/extract/statement_titles.py:194`):

1. **전환기 각주가 양쪽 어휘를 다 언급**한다 — "종전기준서인 K-IFRS…" 같은 각주표는
   비교 설명이지 그 문서 자체의 작성기준 선언이 아니다. 아무 문장이나 매칭하면 안
   되고, **"재무제표 작성기준"류 특정 섹션/문단에 anchoring**해야 한다(전체 문서 grep
   금지).
2. **무관한 법령 문구와의 혼동** — "주식회사의외부감사에관한법률" 등 "기업회계기준"
   문자열을 포함하지만 회계기준 자체와 무관한 규제 준수 문구가 같은 문서에 다수
   존재(위 표본 실측 확인). "기업회계기준서 제N호"처럼 **번호가 붙은 구체적 기준서
   인용**만 신호로 쓰고, 막연한 "기업회계기준" 단독 매칭은 오탐 위험이 큼.

**결론(1차, 표본 1건)**: 판정기 자체는 만들 수 있어 보이나, section_detector류 기존
"작성기준 섹션 찾기" 로직에 앵커링부터 설계해야 하는지가 불확실 — 아래 §5-2에서 대규모
표본으로 재조사.

### 5-2. 대규모 표본 재조사(2026-09-08, 같은 세션 이어서) — "섹션 앵커링 불필요"로 결론 변경

`<TITLE>가. 재무제표 작성기준</TITLE>` 같은 명시적 제목 태그는 표본 상당수에서
**아예 없음**(제목 없이 바로 문단 텍스트로 시작하는 필링이 다수) — 즉 애초에
"작성기준 섹션에 anchoring"이라는 접근 자체가 v3 report_lines의 section_path 같은
구조를 못 쓴다(그건 표(table) 트리 구조지 이런 서술형 각주 문단 구조가 아님). 대신
**문서 전체에서 "기업회계기준서 제N호" 패턴의 번호 자릿수만으로 훨씬 깨끗하게
갈린다**는 걸 발견 — anchoring 없이도 오탐이 거의 없다:

**근거**: K-GAAP 시대 기준서는 제1호~제30호대(구 넘버링), K-IFRS 채택 후 기준서는
**제1001호부터**(신 넘버링, IAS 번호와 대응 — 예 "제1027호"=IAS27 연결재무제표) —
두 체계가 자릿수 자체로 상호 배타적이다. 전사 raw_report 표본 스캔 결과(연도구간별
필링 단위 집계, "기업회계기준서 제N호" 언급이 있는 파일만 카운트):

| 구간 | 표본 수 | 저자릿수만(K-GAAP) | 고자릿수만(K-IFRS, ≥1000) | 혼재 |
|---|---:|---:|---:|---:|
| pre-2009 | 14 | 14 | 0 | 0 |
| 2009–2010 | 10 | 9 | 1(조기도입 추정) | 0 |
| 2011–2014 | 13 | 0 | 10 | 최초 소표본(15)에서 2건 관측, 이후 60건 재확인표본에선 0건(재현 안 됨 — 희귀 엣지케이스로 추정) |
| 2015+ | 15 | 0 | 15 | 0 |

대조군으로 "한국채택국제회계기준"/"K-IFRS" **단어 자체의 존재 여부**도 같이 셌는데,
**모든 구간(pre-2009 제외 전부, 100%)에서 이 단어가 등장**함이 확인됨 — 2009~2014
필링은 아직 K-GAAP를 쓰면서도 "향후 K-IFRS 전환 영향" 같은 전방참조 각주를 의무
공시하기 때문(§5-1에서 이미 예상한 함정 그대로 재현). **결론: "한국채택국제회계기준"
단어 매칭은 이번 조사로 실측 반증됨(전 구간에 다 나와 변별력 0) — 절대 쓰면 안 됨.
"기업회계기준서 제N호"의 **번호 자릿수(<1000 vs ≥1000)**만이 실제 변별력 있는 신호.**

**판정 규칙(확정, 구현 대기)**:
- 문서 내 "기업회계기준서 제N호" 언급이 **≥1000만** 있음 → **True**(IFRS)
- **<1000만** 있음 → **False**(K-GAAP)
- **둘 다** 있음 → 짐작하지 않고 **NULL + 사유 기록**(플래그만, 수동검토 후보 — 위
  표의 2011~2014 혼재 2건처럼 진짜 전환기 비교공시일 수도, 노이즈일 수도 있어 원문
  개별대조 없이 자동판정 금지, ★원본대조검증 원칙)
- **언급 자체가 없음**(coverage 갭 — pre-2011 표본 기준 13~33%가 여기 해당) →
  §4의 Track A/D 판정으로 폴백, 그것도 없으면 **NULL**(기존 v2 원칙 그대로)

이 규칙은 "작성기준 섹션 anchoring"이 전혀 필요 없다 — 문서 전체 스캔으로 충분하다는
게 이번 대규모 재조사의 핵심 성과. §5-1에서 우려했던 함정 ②(무관 법령문구 오탐,
"주식회사의외부감사에관한법률" 등)도 정규식이 "기업회계기준서 제 N 호"라는 고유
어구 자체를 요구해 자연히 배제됨(느슨한 "기업회계기준" 단독 매칭이 아님).

### 5-3. 남은 미확정 사항 (구현 시 확정)

- **판정 우선순위**: Track A(ACODE) 증거가 있으면 문서 기준서번호 판정보다 **우선**
  (더 직접적인 원문 증거 — XBRL 태깅 자체가 IFRS 택소노미 사용의 물리적 증거이므로).
  기준서번호 판정은 Track A/D가 둘 다 없을 때만 발동하는 2차 신호.
- **비용**: 전사 rcept 수 기준 스캔 1회 비용 실측 필요(raw_report I/O, SD카드) — 구현
  착수 시 소규모 배치로 먼저 시간 측정 권장.
- **혼재 케이스 최종 처리**: NULL로 둘지, 별도 리뷰 큐(`report_recon_candidates`류
  기존 패턴 재사용)에 적재해 사용자가 개별 확인할지는 구현 설계 단계에서 결정.

## 6. 구현 TODO (상세, 순서대로 — 아직 미착수, 사용자 승인 후 착수)

### 6-1. 스키마
- [ ] `filings` 테이블에 컬럼 추가(마이그레이션, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
  R73 unit_overrides 마이그레이션 패턴 재사용):
  - `ifrs_evidence VARCHAR(20) NULL` — 값 후보: `'track_a'`(ACODE 존재) /
    `'track_d'`(XBRL instance zip 출처) / `'std_no_kgaap'`(저자릿수만) /
    `'std_no_kifrs'`(고자릿수만) / `'std_no_mixed'`(혼재, 수동검토 필요) / NULL(증거없음)
  - `ifrs_evidence_detail JSONB NULL` — 근거 원문 스니펫(예: 매칭된 "제N호" 목록) 보존,
    unit_overrides 컬럼처럼 감사가능성 확보
- [ ] `std_financials_v3`에 `is_ifrs BOOLEAN NULL` 컬럼 추가(같은 마이그레이션)

### 6-2. 증거 판정 모듈(신규)
- [ ] `fin2/extract/ifrs_evidence.py`(가칭) 신설:
  - `detect_std_no_evidence(text: str) -> tuple[str|None, list[int]]` — "기업회계기준서
    제N호" 전수 추출 → 자릿수 분류 → `'std_no_kgaap'`/`'std_no_kifrs'`/`'std_no_mixed'`/None
  - `detect_track_a_evidence(...)` — 기존 `face_audit.py::read_report_face_xbrl()` 재사용
    (non-empty면 Track A). **새로 안 만들고 재사용**(architecture 원칙: 계층2는
    account_mapper 호출 안 함, 이 모듈도 canonical 매핑 없이 존재유무만 판정)
  - `detect_track_d_evidence(...)` — `report_lines.unit_source`/추출 트랙 메타로 XBRL
    instance zip 출처 여부 판정(기존 `report_lines_xbrl.py` 산출물 표시 방식 확인 후 재사용)
  - 최종 `resolve_is_ifrs(rcept_no) -> bool | None` — §5-3 우선순위(Track A/D > 기준서번호
    > NULL) 적용
- [ ] 신규 회귀테스트: 기존 raw_report 표본(§5-2에서 확인한 pre-2009/2009-2010/2011-2014
    /2015+ 각 구간 대표 파일 fixture화) 기준 True/False/NULL 각 케이스 커버, 혼재 케이스
    1개 이상 포함

### 6-3. 파이프라인 배선 (CLAUDE.md 필수 절차 — 두 call site)
- [ ] Layer 2 추출 시점(`fin2/extract/report_lines.py`/`report_lines_xbrl.py`가 이미
  document.xml을 여는 지점)에서 `resolve_is_ifrs()` 호출 → `filings.ifrs_evidence` 갱신
  (XML 재오픈 없이 이미 열린 파일 재사용)
- [ ] `scripts/collect_new.py` **두 call site 모두** 배선: ① 메인 데일리 경로,
  ② `--standardize-only` 재개 경로(runbook 체크리스트 그대로)
- [ ] `fin2/layer3/combine.py`(또는 `build_std_v3.py`가 std_v3 행을 쓰는 지점)에서
  `source_rcepts`(BS/IS/CF)에 걸린 rcept들의 `filings.ifrs_evidence`를 모아
  `std_financials_v3.is_ifrs` 계산 — 여러 rcept 중 하나라도 확정 신호 있으면 그걸
  채택(다중 rcept 간 충돌 시 규칙도 §5-3처럼 "짐작 금지, NULL" 원칙 적용)

### 6-4. 소비처 정리
- [ ] `collector/db.py`의 `standard_financials` 뷰 5곳: `TRUE AS is_ifrs` →
  `v3.is_ifrs AS is_ifrs`
- [ ] `fin2/standardize/calendar_v3.py:56` — 강제 `d["is_ifrs"] = True` 제거, 실제
  컬럼값 사용(주석도 갱신, 현재 주석이 "v3엔 컬럼 자체가 없다"고 설명 중이라 사실과
  달라짐)
- [ ] `analyzer/display/table_view.py:120` — `curr.get('is_ifrs', True)` NULL-안전
  관례 유지 확인(코드 변경 불필요, 회귀테스트로만 확인)

### 6-5. 백필 (자동 아님 — 별도 실행, CLAUDE.md 필수 절차 ②)
- [ ] `filings.ifrs_evidence` 전사 백필 스크립트(신규) — raw_report 전수 스캔,
  SD카드 경유([[feedback-bulk-read-use-sdcard]]), EUC-KR 로케일 주의
  ([[feedback-grep-euckr-locale-trap]])
- [ ] `std_financials_v3.is_ifrs` 재계산 — **결정된 스코프: pre-2015 전체(132,026행)
  한 번에**(§5 결정) — `build_std_v3.py --year-min 1999 --year-max 2014`류 범위 지정
  또는 전사 재실행(2015+ 는 결과가 True로 불변할 것이므로 재실행해도 무해하지만,
  시간 절약 위해 pre-2015만 스코프 지정 검토)

### 6-6. 검증
- [ ] 회귀테스트 전체(`pytest tests/ fin2/tests/`) — 무관 기존실패 1건 제외 회귀0 확인
- [ ] `dq_assertions.py` 전수 — 이 변경은 값 컬럼이 아니라 메타 컬럼이라 기존 ERROR/WARN
  어서션에 영향 없어야 함(영향 있으면 원인 규명 필요)
- [ ] `gate_b_status`(별도 `face_audit` 테이블 조인) 무변화 확인 — 이번 변경과 완전
  독립적이어야 함
- [ ] 표본 원문대조(★원본대조검증 원칙): pre-2011 K-GAAP 확정 표본 5건 + 2011~2014
  전환기 조기도입/의무적용 각 표본 5건 + 혼재 케이스 전수를 실제 원문과 대조해
  True/False/NULL 판정이 맞는지 확인 — 스코프 재빌드 전 필수
- [ ] 전/후 분포 비교: `is_ifrs` True/False/NULL 건수가 §1 표(pre-2011 85,159 /
  2011~2014 46,867 / 2015+ 190,566)와 정합적인 패턴으로 나뉘는지 확인(예: pre-2011의
  대다수가 False로 바뀌고, 2011~2014는 True/False 혼재, 2015+는 전부 True 유지)

이 문서는 여전히 **설계 확정(§5) + 구현 TODO 상세화(§6) 완료, 코드 구현 자체는
미착수** 상태 — 실제 구현은 사용자의 별도 명시적 실행 지시를 받은 뒤에 시작한다
(CLAUDE.md 정책).
