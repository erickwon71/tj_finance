# Gate B — trade_payables 클래스A(24건) UDF acode 라벨 폴백 설계 (2026-08-28)

## 0. 배경

[[gateb-trade-payables-45-triage-2026-08-28]] 에서 trade_payables fail_a 45건을
원문 리터럴 대조로 4클래스 분류했다. 이 문서는 그중 **클래스A(24건, 가장 안전)**만
다룬다 — 클래스B(14건, std_v3 stale 값 의심)·클래스C(3건, std_v3 개념오독 의심)는
성격이 달라 별도 설계 필요([[gateb-session-handoff-2026-08-28]] 권고).

## 1. 원인 (원문+코드 확정, [[feedback-verify-against-source]])

BS face 본문의 진짜 매입채무 행이 회사·타임스탬프별로 고유한 **entity 확장 acode**
(예: `entity00236863_udf_BS_2020327111229714_CurrentLiabilities`,
`entity00657987_AccountsPayableOfCurrentLiabilities`)를 쓴다. 10개사 원문을 직접
읽어 다음을 확인했다:

1. 이 acode 이름의 접미사(`...CurrentLiabilities`, `...OfCurrentLiabilities` 등)는
   **의미가 없다** — DART 사용자정의확장(UDF) 태그명이 회사마다 임의로 생성되고
   같은 회사 안에서도 다른 계정(기타의투자자산·매각예정자산·장기차입금 등)에
   똑같은 패턴의 acode 가 재사용된다(KX 00657987 원문에서 실측). **acode 형태만으로
   "매입채무" 여부를 regex 판별할 수 없다** — R53(inventory/ppe)과 달리 정적
   alias 사전 확장으로는 원천적으로 불가능(핸드오프 메모의 사전 결론과 일치).
2. 대신 같은 `<TR>` 행의 **라벨 셀**(ACODE 없는 형제 `<TE>`)에 항상 한글 라벨이
   박혀 있고, 공백(일반/전각 `　`)을 제거하면 정확히 3가지 변형 중 하나로
   수렴한다: `매입채무` · `매입채무및기타채무` · `유동매입채무`. 10개사 24건 전건
   확인.
3. `concept_map.py::map_acode()` 는 이 acode 들을 당연히 모른다(회사·타임스탬프
   고유) → `canonical=None` → `read_report_face_xbrl()` 의 후보 집합에서 탈락 →
   유일 후보로 남는 다른 계정(예: `dart_LongTermTradeAndOtherNonCurrentPayables`
   장기매입채무, `ifrs-full_TradeAndOtherCurrentPayables` 등 무관 계정)과 대조돼
   `VALUE_DIFF`(fail_a) 오탐.

**결론**: DB(std_v3)는 정확하다(별도 라벨 기반 파서가 acode 를 안 봐서 갭 영향
없음). 버그는 100% face_audit.py(검증기) 쪽 — "acode 미등록"이 아니라 "애초에
등록 불가능한 회사고유 acode"이므로 **acode 사전이 아니라 같은 행의 라벨 텍스트로
정체를 확인하는 구조적 폴백**이 필요하다.

## 2. 제안 수정 (스코프 제한, 운영 경로 영향 0)

R53 과 동일하게 `concept_map.py`(운영 `fin2/extract/xbrl.py` 와 공유)는 건드리지
않는다. `fin2/audit/face_audit.py` 안에 두 번째 감사 전용 폴백을 추가한다 — acode
사전이 아니라 "회사고유 확장 acode + 같은 행 라벨 매칭"으로 판별:

```python
# face_audit.py 전용 — concept_map.py 는 건드리지 않는다. entity 확장(회사·타임스탬프
# 고유) acode 는 태그명 자체에 의미가 없어(§1 확인, KX 00657987 원문에서 같은 접미사가
# 다른 계정에도 재사용됨) 정적 alias 로 등록 불가 — 같은 <TR> 행의 라벨 셀 텍스트로만
# 정체를 확인한다(2026-08-28,
# gateb_trade_payables_classA_udf_acode_label_fallback_design_2026-08-28.md).
_ENTITY_EXT_ACODE_RE = re.compile(r"^entity\d{8}_")
_TRADE_PAYABLES_ROW_LABELS: frozenset[str] = frozenset({
    "매입채무",
    "매입채무및기타채무",
    "유동매입채무",
})


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s", "", s)


def _row_label_text(te) -> str | None:
    """te 와 같은 <TR> 의 첫 번째 셀(라벨 셀, ACODE 없음) 텍스트. face 표는 항상
    라벨 셀이 행의 첫 <TE> — 레이아웃이 다르면(첫 셀도 ACODE 있음) None 반환(안전)."""
    parent = te.getparent()
    if parent is None:
        return None
    children = list(parent)
    if not children or children[0].get("ACODE"):
        return None
    return _cell_text(children[0])


def _map_acode_face(acode: str, te=None) -> str | None:
    """map_acode() 폴백 — R53 정적 alias + 이번 UDF 라벨매칭(te 전달 시)."""
    canon = map_acode(acode) or _FACE_AUDIT_EXTRA_ACODE.get(acode)
    if canon is not None:
        return canon
    if te is not None and _ENTITY_EXT_ACODE_RE.match(acode):
        label = _row_label_text(te)
        if label is not None and _normalize_ws(label) in _TRADE_PAYABLES_ROW_LABELS:
            return "bs.trade_payables"
    return None
```

`read_report_face_xbrl()` L733 의 `canonical = _map_acode_face(acode)` 를
`canonical = _map_acode_face(acode, te)` 로 교체(1줄, 호출부 유일).

**안전성**: `audit_fields()` 의 PASS 판정은 `val in {ln.amount_won for ln in cands}`
(집합 소속 — 후보가 늘어도 기존에 있던 정답 후보는 그대로 있음, line 1590/1597)
— 순수 가산이라 기존 PASS 를 깨뜨릴 수 없다(R53·`_with_ni_attribution_text_fallback`
과 동일 원칙, face_audit.py L781 주석). 신규 트리거 조건(`entity\d{8}_` 접두 +
현재 미등록 + 라벨 정확히 3종 중 하나)이 매우 좁아 다른 회사·다른 계정에 우연히
걸릴 위험은 무시 가능 — `entity{corp}_` 접두 자체가 DART 표준상 그 회사 필링에만
등장하는 태그다.

## 3. 검증 (실제 코드 경로로 사전 시뮬레이션 완료)

`fin2/audit/face_audit.py` 는 수정하지 않고, `_map_acode_face`/`_row_label_text` 를
그대로 복제한 드라이런 스크립트로 **`read_report_face_xbrl` 이 실제로 쓰는
`parse_acontext`/`_cell_text`/`_parse_adecimal`/`_amount_won` 함수를 그대로 호출**해
현재 fail_a 45건 전체(class A 아닌 것 포함)에 대해 "새 후보 집합에 db_won 이
들어가는가"를 확인했다.

- **class A 24건 전건 해소 확인**(원래 핸드오프의 "일정실업 2025H1 은 미확인,
  같은 패턴으로 추정"도 이번에 실측으로 **확정** — 같은 acode/라벨로 25번째 해소
  대상 추가. 즉 이 수정은 24건이 아니라 **25건** 해소).
- **class B/C/기타의 나머지 20건은 예상대로 미해소**(라벨이 3종 집합에 없거나
  entity 확장 acode 자체가 아님 — 설계 범위 밖 그대로 유지, 부수효과 없음).
- 아이텍(00626011, db=0, R23 기지정 제외 케이스)은 시뮬레이션 단순화(R23
  `_TRADE_PAYABLES_ZERO_MATCH_EXCLUDE_KEYS` 미반영) 때문에 우연히 "해소"로
  보였을 뿐 — 실제 코드에는 그 가드가 이미 있어 이번 변경과 무관, 영향 없음.

## 4. 남은 절차(승인 후)

1. 위 코드 반영(신규 함수 3개 + 상수 2개 + 호출부 1줄).
2. 표본 재감사(class A 10개사 25건) → fail_a→pass 전환 확인.
3. **전수 재감사**([[gateb-full-reaudit-is-required-to-close]] — 표본만으로 닫지
   않는다) — 장시간 명령, 사용자 실행 권장([[feedback-long-running-commands]]).
4. fail_a 회귀 0건 확인(트래킹: 113 → 88 예상, 25건 해소).
5. `docs/PARSING_RULES.md` 에 R54(가칭)로 등재.

## 5. 범위 밖

- 클래스B(14건, std_v3 stale 값 의심) — R42 커버리지 확인부터, 별도 설계.
- 클래스C(3건, std_v3 개념오독 의심) — 원문 라벨 재확인만 하면 되는 작은 트랙,
  별도 설계(작지만 이 문서와 성격이 달라 묶지 않음).
- 제일엠앤에스·엔케이젠바이오텍코리아(기타 2건) — 이미 알려진 별도 이슈와 연관
  가능성, 이번 범위와 묶지 않음.

## 6. 승인 대기

이 문서는 설계만 담았다. 구현(코드 수정 + 표본 검증 + 전수 재감사)은 사용자 승인
후 별도로 진행한다([[feedback-plan-then-wait]]).
