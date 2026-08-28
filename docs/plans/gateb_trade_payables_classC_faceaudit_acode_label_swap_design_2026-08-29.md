# Gate B — trade_payables 클래스C(갤럭시아에스엠형) face_audit acode-라벨 뒤바뀜
# 오탐 설계 (2026-08-29)

## 0. 배경

[[gateb-trade-payables-45-triage-2026-08-28]] 클래스C 3건 중 **갤럭시아에스엠
(00129554) 1건**(2026H1 연결). 종근당홀딩스형(같은 클래스C, 2건)과 겉보기 증상
(원문 당기 컬럼에 db_won이 리터럴로 존재하지만 그 acode가 매입채무와 무관)은 같지만
**원인은 정반대** — 이번 건은 **DB(std_v3)가 정답이고 face_audit(검증기)이 오탐**이다.
별도 문서(`gateb_trade_payables_classC_accountmapper_containment_alias_gap_
design_2026-08-29.md`)와 섞지 않는다.

## 1. 원인 (원문+코드 확정, [[feedback-verify-against-source]])

2026H1 연결 BS 원문(`20260814002461.xml` L3260-3282), 유동부채 하위 두 행:

```xml
<TE ENG="Other current financial liabilities">단기매입채무</TE>
<TE ACODE="ifrs-full_OtherCurrentFinancialLiabilities" ...>172,864,613</TE>   ← db_won

<TE ENG="other current payables">기타유동채무</TE>
<TE ACODE="ifrs-full_TradeAndOtherCurrentPayables" ...>1,483,956,477</TE>    ← report_won
```

필자(공시대리인)가 **라벨과 acode를 서로 바꿔** 태깅했다 — 한글 라벨은 분명히
"단기매입채무"(매입채무 계열, `bs_accounts.py`에 `"단기매입채무"` exact alias로
이미 정확히 등록돼 있음)인데 붙은 XBRL acode는 엉뚱한 `ifrs-full_
OtherCurrentFinancialLiabilities`이고, 반대로 "기타유동채무"(매입채무와 무관) 라인에
표준 매입채무 태그 `ifrs-full_TradeAndOtherCurrentPayables`가 붙어 있다. 전기
비교컬럼(PFY2025)도 같은 패턴이라 이 필링 전체의 체계적 오태깅으로 보인다(1회성 셀
오류 아님). 별도(별도) 기준(L9399)에는 `dart_ShortTermTradePayables`(정상 등록 alias)
로 태깅된 "단기매입채무" 172,864,613 행이 **연결과 정확히 같은 금액**으로 존재 —
172,864,613이 이 회사의 진짜 매입채무라는 교차 확인.

std_v3(AccountMapper)는 **acode를 보지 않고 라벨 텍스트**로 판별하므로 "단기매입채무"를
정확히 `bs.trade_payables`로 잡았다(db_won=172,864,613, **정답**). face_audit은
`read_report_face_xbrl()`에서 acode(`ifrs-full_TradeAndOtherCurrentPayables`,
`concept_map.py`에 정상 등록된 alias)를 신뢰해 report_won을 계산하는데, 이 필링에서는
그 acode가 잘못된 행("기타유동채무")에 붙어 있어 **acode 기준으로는 틀린 값
(1,483,956,477)을 "정답"으로 오판**한다. face_audit은 라벨-acode 불일치를 감지하는
장치가 없어(R23 이후 acode는 항상 신뢰 가능하다고 가정) 이 케이스를 걸러내지 못하고
false VALUE_DIFF(fail_a)를 띄운다.

## 2. 제안 수정

std_v3 쪽은 **변경 불필요**(이미 정답). face_audit(검증기) 쪽에, "acode 기준
report_won 후보"와 "같은 행 라벨 기준 판별"이 서로 다른 canonical을 가리킬 때 라벨
쪽을 우선하도록 **좁은 가드**를 추가한다 — R53/R54(라벨 폴백)와 대칭이지만 방향이
반대: R53/54는 "acode 없음 → 라벨로 보완", 이번은 "acode 있지만 같은 행 라벨이
명백히 다른 계정을 가리키면 그 acode 후보를 신뢰하지 않음".

```python
# face_audit.py 전용 — 원문 필자가 라벨과 acode를 서로 바꿔 태깅한 경우
# (2026-08-29, gateb_trade_payables_classC_faceaudit_acode_label_swap_
# design_2026-08-29.md). 같은 <TR>의 라벨 셀이 "매입채무"류 3종(R54와 동일
# 폐집합)이 **아닌데** acode가 bs.trade_payables로 매핑되면, 그 acode 태깅을
# 신뢰하지 않고 후보에서 제외한다(라벨이 우선 — R53/54와 동일 원칙, 방향만 반대).
_NON_TRADE_PAYABLES_LABEL_HINTS: frozenset[str] = frozenset({
    "기타유동채무", "기타비유동채무", "기타채무", "기타지급채무", "미지급금",
})

def _acode_label_conflicts_trade_payables(te) -> bool:
    label = _row_label_text(te)
    if label is None:
        return False
    return _normalize_ws(label) in _NON_TRADE_PAYABLES_LABEL_HINTS
```

`canonical = _map_acode_face(acode)`가 `"bs.trade_payables"`를 반환한 직후, 위 가드가
`True`면 해당 TE를 후보에서 skip(R47류 `continue`와 동일 자리).

**대안(더 좁고 안전, 권장)**: 위 일반 가드 대신 이 필링(00129554, 2026H1,
consolidated) 하나만 curated 예외로 등록 — R42의
`_TRADE_PAYABLES_STALE_SUBLINE_OVERRIDE` 같은 `(corp, fy, period, basis)` 키 방식.
1건뿐인 지금 시점엔 일반 가드보다 **오탐 위험이 0에 수렴**하고(다른 회사 acode
신뢰도를 전혀 건드리지 않음), 앞으로 같은 유형(라벨-acode 뒤바뀜)이 재발하면 그때
일반 가드로 승격하는 게 R42→R54 계열의 기존 패턴과 일치. **일반 가드 채택 시** 위
`_NON_TRADE_PAYABLES_LABEL_HINTS` 집합이 다른 정상 케이스(예: 진짜 매입채무 acode가
정확히 "미지급금" 행에 붙는 회사가 실제로 존재할 가능성)를 걸러버릴 위험을 배제
못 하므로, 승인 전 아래 §3 표본 스캔으로 이 라벨 힌트 5종이 등장하는 다른 fail_a/
pass 필링에 부작용이 없는지 확인 필수.

## 3. 검증 절차(승인 후)

1. (권장안 채택 시) `(corp="00129554", fy=2026, period="H1", basis="consolidated")`
   curated 예외 1줄 추가 — 코드 변경 최소, 리뷰 용이.
   (일반 가드 채택 시) 위 3함수/상수 추가 + 호출부 1줄, 그리고 `_NON_TRADE_PAYABLES_
   LABEL_HINTS` 5종이 현재 face_audit acode 매핑 결과에 주는 영향을 전수(또는 큰
   표본) 드라이런으로 사전 확인 — 새로 fail_a가 늘어나는 corp가 있으면 중단.
2. 표본 재감사(00129554 1건) → fail_a→pass 전환 확인.
3. std_v3 재백필은 **불필요**(DB 값 변경 없음, face_audit 검증기만 수정).
4. 전수 재감사(다른 fail_a·pass에 영향 없는지, [[gateb-full-reaudit-is-required-to-close]]).
5. `docs/PARSING_RULES.md`에 신규 R번호로 등재.

## 4. 범위 밖

- 종근당홀딩스형(2건, 39개사 339행 잠재) — 별도 문서, std_v3 본체 버그.

## 5. 승인 대기

이 문서는 설계만 담았다. 구현(curated 예외 또는 가드 추가 + 표본 검증 + 전수
재감사)은 사용자 승인 후 별도로 진행한다([[feedback-plan-then-wait]]).
