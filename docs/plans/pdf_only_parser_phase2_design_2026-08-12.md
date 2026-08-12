# Phase 2 설계 — ②(1,548건) XBRL taxonomy 확장 트랙

> 상위 문서 = [`pdf_only_parser_plan_2026-08-11.md`](pdf_only_parser_plan_2026-08-11.md)
> (마스터 계획, §6 사전결정 5건 참고) · [`pdf_only_parser_todo_2026-08-11.md`](pdf_only_parser_todo_2026-08-11.md)
> (실행 체크리스트). 조사 근거 = [`pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md`](../qa/pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md)
> (버그①·② 확정 + 후속이슈 A/B/C 60건 정량화). **이 문서는 설계일 뿐 — [정책](../../CLAUDE.md)
> 상 사용자 승인 없이 구현(Phase 3) 착수 금지.**

---

## 0. 이 문서의 범위 — ★스코프 분리 확정(2026-08-12, 사용자 결정 "Phase 2 설계 문서로 편입해줘")

`pdf_only_structure_probe_2026-08-11.md` §6-7이 남겨둔 질문("②를 Phase 2 설계 문서에
'②(1,548건) 트랙' 절로 편입할지, 별도 소규모 트랙으로 분리할지")에 대해 **편입으로
확정**됐다. 단, "편입"의 의미를 명확히 해둔다 — ①+pre-2015(1,870건, 새 PDF 텍스트파서)와
②(1,548건, XBRL taxonomy 확장)는 **기술적으로 완전히 다른 작업**(파서 신규개발 vs 기존
추출기 버그수정)이라 실제 구현은 별개로 진행된다. "편입"은 "같은 Phase 2 계획 문서 안에
두 절로 함께 관리한다"는 뜻이지 "하나의 구현으로 합친다"는 뜻이 아니다.

| 절 | 대상 | 건수 | 작업 성격 | 설계 상태 |
|---|---|---:|---|---|
| §A(이 문서) | ②: XBRL 있으나 추출기 미지원 | 1,548 | 기존 `report_lines_xbrl.py`/`role_map.py` 버그 수정 | **이 문서에서 완료** |
| §B(별도 세션) | ①+pre-2015: 진짜 PDF-only | 1,870 | 신규 PDF 텍스트파서 개발(todo 2-1~2-6) | **미착수** — `pdf_only_parser_todo_2026-08-11.md` Phase 2 2-1~2-6 그대로 남음 |

**이 문서는 §A(②트랙)만 다룬다.** §B는 별도 설계 세션이 필요하다(오늘 조사는 XBRL
taxonomy 쪽만 진행했고, 새 PDF파서의 tree 표현·앵커탐지·정정처리 설계는 아직 손대지
않았다 — 섣불리 한 문서에 욱여넣으면 두 트랙의 승인 단위가 뒤섞인다, [[feedback-plan-then-wait]]).

---

## A. ②(1,548건) XBRL taxonomy 확장 트랙 설계

### A-1. 배경 요약

조사 문서(`pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md`)가 확정한 사실:
- 구형 taxonomy(접두사 `ifrs`, 2010-04-30판)에도 basis 축 개념이 신형과 로컬명 그대로
  동일 존재(48/48 표본 확정).
- 미적재 원인은 **독립된 두 버그**: ①`report_lines_xbrl.py`의 `nsmap.get("ifrs-full")`
  리터럴 접두사 하드코딩, ②`role_map.py`의 외부 taxonomy BFS(`_EXTERNAL_FETCH_BUDGET=12`)
  예산 소진 — DART 자체 role 정의 파일(`rol_dart_*.xsd`)이 import 순서상 항상 마지막
  근처라 도달 전에 소진.
- 두 버그를 함께 우회하면 36건 e2e 표본 **100% 성공**.
- 60건 표본 정량화로 후속이슈 3건 확정: **A**(라벨 미해석, vintage 편중, 원인=외부 라벨
  linkbase 구조결함) · **B**(중복행처럼 보인 것, 재확인 결과 대부분 정상 — 이미
  `report_lines` 아키텍처가 예견한 케이스) · **C**(BS 최상위 합계행 부재, 89~97%,
  원인=필러 `_pre.xml`이 합계 노드를 트리에 아예 안 실음).

### A-2. 스코프

- 대상: `download_tasks.file_type='xbrl_zip' AND status='completed'` 이면서
  `report_lines`에 해당 rcept_no 행이 0건인 전량(현재 1,548건 추정치 — 정확한 재확인은
  구현 착수 시 재쿼리). 원문 zip은 이미 전량 디스크에 확보됨(2026-08-12 전량 다운로드
  완료) — 신규 다운로드 불요.
- **note(주석) 미포함** — `report_lines_xbrl.py`는 애초에 face(BS/IS/CF/SCE)만 다루는
  모듈이라(모듈 docstring 명시) 이번 트랙도 자연히 face만. ①+pre-2015 PDF파서 트랙의
  note 제외 방침(§4)과 일관.
- **신규 모듈 불요** — 기존 `fin2/extract/report_lines_xbrl.py`·
  `parser/xbrl_instance/role_map.py`·`parser/xbrl_instance/taxonomy_linkbase.py` 세
  파일의 **지역적 수정**만으로 해결(§A-3~A-6). [[architecture-report-read-layer2-only]]
  불변식 위반 없음 — 이미 계층2 전용으로 설계된 모듈을 고치는 것뿐, 새 read 경로 추가 아님.

### A-3. 버그① 수정설계 — 접두사 리터럴 매치 → 네임스페이스 URI 패턴 매치

`fin2/extract/report_lines_xbrl.py:814`:

```python
# 현재
basis_axis_ns = instance.nsmap.get("ifrs-full")
```

일반화안:

```python
# 신형: ifrs-full -> http://xbrl.ifrs.org/taxonomy/{date}/ifrs-full
# 구형: ifrs      -> http://xbrl.iasb.org/taxonomy/{date}/ifrs
_IFRS_NS_PATTERN = re.compile(r"(iasb\.org/taxonomy|ifrs\.org/taxonomy)")

def _resolve_ifrs_namespace(nsmap: dict[str, str]) -> str | None:
    if "ifrs-full" in nsmap:          # 기존 동작 우선 보존(이미 검증된 다수 필링)
        return nsmap["ifrs-full"]
    for uri in nsmap.values():
        if _IFRS_NS_PATTERN.search(uri):
            return uri
    return None

basis_axis_ns = _resolve_ifrs_namespace(instance.nsmap)
```

- 패턴은 48/48 조사 표본으로 검증된 두 네임스페이스 형태를 근거로 함(짐작 아님,
  [[feedback-verify-against-source]]). 향후 제3의 vintage가 다른 URI 형태를 쓸 가능성은
  배제 못 하므로, 매치 실패 시 기존과 동일하게 경고 로그 후 스킵(현재 동작 그대로 유지 —
  회귀 없음).
- 하위 로직(`_emit_statement_lines`/`_emit_sce_lines` 등)은 이미 해석된 URI 값을
  주고받는 구조라 **이 함수 하나만** 수정하면 전파됨(모듈 docstring이 이미 그렇게
  설계돼 있음을 확인, 별도 리팩터 불요).

### A-4. 버그② 수정설계 — 외부 taxonomy BFS 예산/순서

`parser/xbrl_instance/role_map.py::_resolve_external_roles()`가 큐를 파일에 적힌
import 순서 그대로 소진하는데, DART 자체 role 정의(`rol_dart_*.xsd`/`rol_dart-added_
*.xsd`)가 항상 그 목록의 맨 끝 근처에 있어(조사 표본에서 47개 중 46·47번째) 예산 12로는
못 미친다. 두 방향 중 하나를 택한다:

| 방식 | 내용 | 장점 | 단점 |
|---|---|---|---|
| (i) 예산 상향 | `_EXTERNAL_FETCH_BUDGET = 12 → 60` | 구현 1줄, 이미 실험으로 검증(§A-1) | vintage당 최대 47회 순차 fetch(단, 디스크 캐시라 vintage당 1회만 비용 발생 — 조사 결과 category②에 걸친 고유 vintage 수는 많아야 5~10개 수준으로 추정, 실측은 구현 시 재확인) |
| (ii) 우선순위 재정렬(권장) | `dart_first()`를 파일명 패턴까지 보도록 확장 — `rol_dart`/`dart-added` 포함 URL을 큐 맨 앞으로 | 예산 그대로 두고도 즉시 도달, 더 빠름 | `role_map.py`/`taxonomy_linkbase.py` 양쪽이 이 BFS 패턴을 재사용하므로 두 곳 다 손봐야 함(§A-5도 같은 BFS 계열) |

**권장: (ii)를 기본으로 하되 (i)도 소폭 병행**(예: 12→20 정도) — 우선순위 재정렬로
대부분 케이스가 앞쪽에서 해결되지만, 미지의 vintage가 더 깊은 import 체인을 가질 가능성에
대한 안전판으로 예산도 약간 여유를 둔다. 구체 구현:

```python
def dart_first(urls: list[str]) -> list[str]:
    def _priority(u: str) -> tuple[int, int]:
        # 0: DART 자체 role/label 정의 파일(우리가 실제로 찾는 것) — 최우선
        # 1: 그 외 dart.fss.or.kr 도메인(개별 IAS/IFRS/SIC 표준 role 등 — 대개 무관)
        # 2: 그 외(w3.org/xbrl.org 프레임워크 스키마)
        if "rol_dart" in u or "dart-added" in u or "dart-label" in u or "dart-gcd" in u:
            return (0, 0)
        if "dart.fss.or.kr" in u:
            return (1, 0)
        return (2, 0)
    return sorted(urls, key=_priority)
```

- `role_map.py::_resolve_external_roles()`와 `taxonomy_linkbase.py::resolve_external_
  labels()` 둘 다 `external_taxonomy.py::dart_first()`를 공유해서 쓰므로, **이 함수 하나만
  고치면 두 곳 모두 동시에 개선**된다(§A-6의 라벨 문제에도 부분적으로 도움이 될 가능성 —
  단 §A-6은 원인이 다르므로 별도 확인 필요, 아래 참고).

### A-5. 후속C 수정설계 — BS 최상위 합계(Assets/Liabilities/Equity) fact-레벨 보조규칙

**선례 확인(중요)**: `docs/plans/xbrl_instance_parser_todo_2026-08-05.md` Phase 6-5가
이미 2026-08-06에 같은 현상(웰킵스하이텍 vintage, Assets/Liabilities/Equity/ProfitLoss/
ComprehensiveIncome/현금잔액이 presentation tree에 안 태깅됨)을 발견했고, **"layer3
소관, 별도 결정 필요"로 수용**하며 layer2에서 손대지 않기로 했었다. 이번 발견이 그
결정을 뒤집는 게 아니라 — **다른 하위 케이스**를 다룬다는 점을 명확히 한다:

| 케이스 | 웰킵스하이텍(2026-08-06 기존 조사) | 이번 60건 표본(2026-08-12) |
|---|---|---|
| BS(Assets/Liabilities/Equity) | 확인 안 됨(BS는 소계 항등식으로 우회검증만 함) | **fact 자체는 89~97% 존재, presentation tree에만 안 실림** |
| CF/IS(ProfitLoss/ComprehensiveIncome 등) | **fact 자체가 0건**(전수 조회 확정 — 진짜 원문 태깅 공백) | 미확인(이번 조사는 BS만 직접 tree 스캔) |

즉 BS 쪽은 "fact는 있는데 tree가 안 읽어준다"(layer2가 손대도 되는 케이스 — 원문에 실제
있는 값을 그대로 옮기는 것뿐, R0 "관찰이지 판단 아니다" 원칙 그대로), CF/IS 쪽은 이미
"진짜 없다"고 확정된 케이스라 이번 설계에서 손대지 않는다(기존 2026-08-06 결정 유지).

**설계**: `_emit_statement_lines()`에서 BS 트리 워크가 끝난 뒤, `basis`별로 아래 3개
개념에 대해 **트리에 노드가 없는 경우만** 보조 검사:

```python
_BS_REQUIRED_TOTALS = ("Assets", "Liabilities", "Equity")

def _emit_missing_totals(tree, facts_by_qname, contexts, basis_axis_ns, basis_axis,
                          basis_member, already_emitted_locals: set[str], ...):
    for local in _BS_REQUIRED_TOTALS:
        if local in already_emitted_locals:
            continue  # 트리에 이미 있으면 기존 경로가 처리 — 이 폴백은 안 건드림
        concept = QName(ns=basis_axis_ns, local=local)
        fact = _find_single_dim_basis_fact(facts_by_qname.get(concept, []), contexts,
                                            basis_axis, basis_member, period_end_date)
        if fact is None:
            continue  # 진짜 없음(웰킵스하이텍류) — 조용히 건너뜀, 지어내지 않음
        yield _row_from_bare_fact(fact, local, labels, depth=0, node_role="P",
                                   section_path=None, row_order=<트리 밖이므로 별도 규약 필요>,
                                   header_hint="xbrl_tree_gap_total")  # 트리 밖 출처를 표시
```

- **`header_hint`(또는 그에 준하는 표식) 값으로 "트리 워크가 아니라 fact 직접 읽기로
  나온 행"임을 명시** — `report_lines.header_hint`는 이미 "헤더 의심행은 삭제 말고
  규칙이름 전사"([[layer2-header-hint-lossless]])라는 무손실 원칙으로 쓰이는 컬럼이라,
  같은 관례로 출처 표식을 얹는 게 자연스럽다. depth/section_path/row_order처럼 "트리
  안에서의 위치"를 나타내는 값은 애초에 정의 불가능하므로 NULL 또는 트리 최상위(depth=0)
  규약을 확정해야 한다 — **이 지점이 구현 착수 전 세부 확정 필요 항목**(아래 A-8).
- IS/CF 동급 개념(당기순이익=ProfitLoss, 총포괄손익=ComprehensiveIncome 등)은 **이번
  설계에 포함하지 않는다** — 2026-08-06 선례가 시사하듯 fact 자체가 없는 케이스일
  가능성이 있어, 포함 전 이번 60건 표본과 동일한 방식(fact_by_qname 직접 조회)으로
  IS/CF도 먼저 정량화해야 한다(§A-8 확인 필요 항목 1번).

### A-6. 후속A 수정설계 — 라벨 미해석(vintage 편중)

조사로 확정된 원인: `taxonomy_linkbase.py::resolve_external_labels()`가 "첫 번째로
찾은 labelLinkbaseRef 파일이면 충분"이라고 가정하는데(`if label_urls: break`), 문제
vintage(`2013-03-31`)는 그 첫 파일(`dart_entry_point_2013-03-31-label.xml`)이 구조적
결함(대량 `undeclared loc/label`)이 있어 개념 18개만 확보되고 멈춘다 — 신형 vintage처럼
"lab_ifrs-ko/en, lab_dart-ko/en, lab_dart-gcd-ko/en 6개를 전부 찾아 합친다"는 패턴이
아니다.

**수정 방향(두 단계)**:
1. **A-4의 `dart_first()` 우선순위 재정렬을 적용하면 부분적으로 나아질 수 있음** —
   현재는 첫 dart.fss.or.kr URL에서 멈추는데, 이게 우연히 결함있는 파일을 먼저 찾아서
   생긴 문제일 수도 있다(확인 필요, §A-8).
2. **근본 수정**: "첫 파일에서 멈춘다"는 가정 자체를 버리고, 신형 vintage와 동일하게
   **entry point가 선언한 labelLinkbaseRef를 전부 모아 병합**하는 방식으로 변경(현재
   신형 vintage 경로는 이미 그렇게 동작 — 6개 파일 병합이 정상 케이스). 즉
   `resolve_external_labels()`의 BFS를 "처음 찾은 1개"가 아니라 "그 entry point가
   선언한 전체 목록"으로 넓힌다. 이러면 `2013-03-31` vintage가 실제로 `lab_ifrs-*`류
   파일을 별도로 갖고 있는지부터 원문 확인이 필요(§A-8 확인 필요 항목 2번 — 아직 안 함).

### A-7. 후속B — 정책 결정 불요(이미 확정된 아키텍처)

`collector/models.py::ReportLine` 클래스 docstring이 이미 명시: **"중복 라벨을 병합하지
않는다 — 같은 계정명이 서로 다른 위치(예 금융업 이중섹션)에 나오면 그대로 둘 다 남는다...
위치가 다르면 서로 다른 행이다."** 이번 조사가 확인한 "중복처럼 보인 행"은 정확히 이
케이스(같은 개념이 요약 라인 + 세부 분해표 두 자리에 실제로 공시됨, row_order/depth/
section_path 전부 다름)라 **별도 결정 불요 — 기존 방침 그대로 적용**(둘 다 저장). XBRL
경로가 HTML 경로와 다른 특별 처리를 할 이유가 없다.

### A-8. 구현 착수 전 확인 필요 항목(설계 미확정, Phase 3에서 먼저 확인)

1. IS/CF의 당기순이익(ProfitLoss)/총포괄손익(ComprehensiveIncome) 등도 A-5와 같은
   "fact는 있는데 tree가 안 읽어주는" 케이스인지, 아니면 2026-08-06 선례처럼 "fact 자체가
   없는" 케이스인지 — 60건 표본 규모로 먼저 정량화(읽기전용, 이번 조사와 같은 방법론).
2. `2013-03-31` vintage의 entry point가 `lab_ifrs-ko`류 파일을 실제로 선언하는지 원문
   확인(A-6 근본수정의 전제조건).
3. A-5의 "트리 밖 출처" 행에 대해 `depth`/`row_order`/`section_path`를 정확히 어떤
   값으로 채울지(NULL vs 관례값) — 계층3 소비 패턴(`node_role='P' OR (S ∧ 값있음)'`
   집계행 판정 규칙)이 이 값들에 의존하므로, 확정 전 계층3 코드 재확인 필요.
4. category② 정확한 최신 건수 재쿼리(오늘 기준 1,548 추정 — 실행 시점에 갱신될 수 있음).
5. A-4/A-6 우선순위 재정렬이 회귀를 일으키지 않는지 — 기존에 이미 정상 동작하던 신형
   vintage(③ 86건 + Phase 5-A 검증분)가 재정렬 후에도 동일 결과를 내는지 회귀 확인 필수.

### A-9. 구현·백필 절차(스코프만 — 실제 실행은 Phase 3)

- **신규 백필 스크립트 불요** — 기존 `collector/xbrl_instance_lines_sync.py::
  sync_xbrl_instance_lines(corps, year_min, recheck=True)`가 이미 "이미 시도했던 rcept도
  재시도"하는 `recheck` 플래그를 갖고 있다. `scripts/backfill_pdf_only_2015plus_xbrl_
  recovery.py`가 쓰던 것과 동일 함수 — A-3~A-6 코드 수정 후 이 함수를 `recheck=True`로
  ②의 corp 목록에 재실행하면 된다.
- **데일리 파이프라인 배선도 이미 완료 상태** — `scripts/collect_new.py::
  _sync_xbrl_instance_lines()`(④-4)가 메인 경로(line 687)·`--standardize-only` 재개
  경로(line 796) **두 곳 모두** 이미 `sync_xbrl_instance_lines()`를 호출 중(Phase 3-5/3-7
  때 배선 완료 확인됨) — 코드 수정만으로 신규 필링은 자동으로 이 개선을 받는다. 런북
  ([[parser-pipeline-integration-runbook]]) 체크리스트 A는 **이미 충족** — 이번 트랙은
  런북 체크리스트 B(소급 백필)만 별도 실행하면 됨.
- **std_v3 반영**: `report_lines` 신규 확보분은 기존 `build_std_v3.py` 전량재빌드
  루틴으로 자동 반영(신규 소스 타입 추가 아님, 이미 있는 `unit_source='xbrl'` 경로가
  건수만 늘어나는 것).

### A-10. 검증 계획(Phase 4 상당, 이 트랙 자체는 별도 Phase 3/4 구분 없이 진행 가능한 소규모 트랙)

- 회귀 테스트: `fin2/tests/test_xbrl_instance.py`(기존, 신형 vintage 표본)가 A-3~A-6
  수정 후에도 그대로 통과하는지(회귀 없음 확인) + 구형 vintage 표본 신규 테스트 추가
  (박셀바이오/한화 패턴과 동일하게 로컬 zip 직접 파싱, DB 비의존).
- BS 항등식(자산=부채+자본) — pre-2015/std_v3 트랙 관례대로 전량 재확인.
- 표본 원문 대조 확대(60건 → 필요시 더 확대) — 값 자체가 맞는지 재확인
  ([[feedback-verify-against-source]]).
- Gate B 무영향 확인(기존 std_v2 경로 안 건드림 — 회귀 로직 없음이 자명하지만 관례상
  실행).
- 백필 후 category② 잔여 건수(완전 해소 vs 일부 잔존) 정직 보고 — 전량 무결측 원칙
  (CLAUDE.md)에 따라, 다 못 지운 잔여분이 있으면 왜인지 보고.

---

## B. ①+pre-2015(1,870건) 새 PDF파서 트랙 — 이 문서 범위 밖

`pdf_only_parser_todo_2026-08-11.md` Phase 2 (2-1~2-6, tree 표현/앵커탐지/정정처리/
OCR·이미지스캔 방침/단위판정/설계문서화)가 그대로 남아있다. 이 트랙은 **오늘 세션에서
다루지 않았다** — 별도 세션에서 착수 필요.

---

## 다음 액션

1. ☑ **사용자 승인 완료(2026-08-12) — §A(②트랙) 구현 착수**.
2. ☑ **§A 구현 완료(2026-08-12)** — A-8 확인 항목(1~4) → A-3~A-7 코드 수정(구현 중 설계
   결함 1건 발견·수정: `header_hint` 대신 `source_ref`로 출처 기록, `fin2/layer3/
   combine.py`의 `header_hint IS NULL` 가드와 충돌 회피) → A-8-5 회귀 확인(0 mismatch) →
   A-9 백필(744개사·1,603건·317,947행·오류0) → BS 항등식 전수검사(99.64% 성립) →
   `docs/PARSING_RULES.md` R14 등재. 카테고리② 1,551→31건(98.0% 해소), 잔여 31건은
   5가지 독립·무관 원인으로 원문 확인 완료 — 전량 목록 =
   [`xbrl_taxonomy_r14_remaining31_2026-08-12.md`](../qa/xbrl_taxonomy_r14_remaining31_2026-08-12.md).
   상세 근거 = `docs/qa/pdf_only_xbrl_taxonomy_expansion_probe_2026-08-12.md`.
   **Gate B 무영향 확인 + std_v3 전량재빌드는 사용자가 별도 세션(controlling_ni
   트랙)에서 진행 중이라 이번 스코프에서 제외 — 그 세션 정리 후 이어서 진행 예정.**
3. §B(새 PDF파서, 1,870건)는 이 완료와 무관하게 별도로 착수 요청 가능(독립 트랙,
   여전히 미착수).
