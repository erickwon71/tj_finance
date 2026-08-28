# Gate B — trade_payables 클래스C(종근당홀딩스형) AccountMapper 퍼지 포함관계
# alias 갭 설계 (2026-08-29)

## 0. 배경

[[gateb-trade-payables-45-triage-2026-08-28]]에서 fail_a trade_payables 45건을
4클래스로 분류했고, 클래스A(24건, R54)는 이미 종료했다. 이 문서는 **클래스C 3건 중
종근당홀딩스(00149354) 2건**을 다룬다. 갤럭시아에스엠(00129554) 1건은 원인이 정반대
(face_audit 쪽 오탐)라 별도 문서(`gateb_trade_payables_classC_faceaudit_acode_label_swap_
design_2026-08-29.md`)로 분리했다.

## 1. 원인 (원문+코드 확정, [[feedback-verify-against-source]])

종근당홀딩스(순수 지주회사)의 별도(별도) BS에는 **"매입채무" 라인 자체가 없다**
(2025FY·2026Q1 둘 다 확인). 있는 건 "미지급금"·"기타유동채무"·"기타비유동채무" 세
줄뿐이다:

```
미지급금 (주29,30,31)      acode=dart_ShortTermOtherPayables         1,282,164,914
기타유동채무 (주29,30,31)  acode=ifrs-full_OtherNoncurrentPayables     303,013,564  ← DB가 이 값을 씀
기타비유동채무 (주29,30,31) acode=(별도)                                  8,740,000
```

`report_lines`에도 동일하게 8행 확인(라벨 그대로, 매입채무 행 없음).

`parser/common/account_mapper.py::_fuzzy_match()`의 Stage 3(퍼지) 포함관계 규칙이
원인이다. `account_maps/bs_accounts.py`의 `bs.trade_payables`에 **결합형(복합) alias**
`"매입채무및기타유동채무"`·`"매입채무및기타비유동채무"`가 등록돼 있는데(2026-07-18
"유동/비유동/장기/단기 변형 → 매입채무" 승급 당시 추가), 이 alias들의 **뒷부분
("기타유동채무"/"기타비유동채무")이 그대로 정규화된 원문 라벨과 문자 그대로 일치**한다.
`_fuzzy_match()`의 포함관계 분기(L318-335)는 `normalized in alias_norm`이면(원문 라벨이
alias의 부분문자열) `len_ratio`만 확인하고 매칭시킨다 — "매입채무" 부분이 실제로
원문 라벨에 있는지는 검사하지 않는다:

```python
len_ratio = min(len(alias_norm), len(normalized)) / max(len(alias_norm), len(normalized), 1)
# "기타유동채무"(6) vs "매입채무및기타유동채무"(11) → len_ratio=0.545
if len_ratio < 0.65 and min(len(alias_norm), len(normalized)) <= 4:
    pass   # ← 6>4 라 이 예외에 안 걸리고 그대로 통과
else:
    score = 0.90 + len_ratio * 0.09   # = 0.9490 (threshold 0.88 초과)
```

`"기타유동채무"`·`"기타비유동채무"`는 `bs_accounts.py` 어디에도 **단독 alias로
등록돼 있지 않다**(반면 "미지급금"·"기타채무"·"기타지급채무"·"기타유동부채"는
`bs.other_current_payables`에 이미 등록돼 있어 Stage 1/2에서 안전하게 소진됨) —
그래서 이 두 라벨만 Stage 3까지 흘러가 위 결합형 alias의 부분문자열 매칭에 걸린다.

**같은 함정을 가진 alias가 하나 더 있다**: `"장기매입채무및기타비유동채무"`도
뒷부분이 `"기타비유동채무"`라 동일 구조.

## 2. 파급 범위 실측 — 예상보다 훨씬 크다

`report_lines` 전수에서 (정규화 라벨 `기타유동채무`/`기타비유동채무`, 같은 필링·
basis 안에 진짜 `매입채무` 라벨 행이 **전혀 없는** 경우, `std_financials_v3.
trade_payables`가 그 값과 정확히 일치)를 스캔한 결과:

**339행 · 39개사**가 이 기제로 잘못 채워졌을 가능성이 높다(트리아지 메모의 "3건"은
face_audit이 acode 기반 report_won을 찾을 수 있어 fail_a로 뜬 것만 잡은 것 — 대부분은
face_audit도 acode를 못 찾아 pending/무증거로 남아 **Gate B가 아예 못 잡는 잠복
오염**이다). 표본 확인(00132354=쿠쿠홀딩스)도 종근당홀딩스와 똑같이 **순수 지주회사**
— 가설(지주회사류는 매입채무 라인이 아예 없어 오매핑된 값이 유일 후보로 확정)과
정확히 부합.

## 3. 제안 수정 (운영 경로, 최소·저위험)

`fin2/audit/face_audit.py` 전용 오버레이가 아니라 **운영 `account_maps/bs_accounts.py`
본체**를 고친다 — 이번엔 R53/R54와 달리 회사고유 UDF acode 문제가 아니라 **범용 라벨
사전의 갭**이라 감사 전용 폴백으로는 근본 해결이 안 된다(std_v3 파이프라인 자체가
같은 사전을 쓰기 때문).

`"기타유동채무"`를 `bs.other_current_payables`에, `"기타비유동채무"`를
`bs.other_noncurrent_liabilities`에 **단독 exact alias로 추가**한다(둘 다 이미
"기타채무"·"기타지급채무"·"기타비유동부채"·"기타장기부채" 등 형제 alias가 등록된
버킷 — 신규 canonical 도입 없음, 순수 사전 갭 메우기):

```python
# bs.other_current_payables 안에 추가
"기타유동채무",   # 2026-08-29(gateb_trade_payables_classC_accountmapper_
                  # containment_alias_gap_design_2026-08-29.md) — 미등록이라
                  # Stage3 포함관계가 "매입채무및기타유동채무"의 부분문자열로 오매핑.

# bs.other_noncurrent_liabilities 안에 추가
"기타비유동채무",  # 위와 동일 원인("매입채무및기타비유동채무"/"장기매입채무및
                   # 기타비유동채무"의 부분문자열).
```

Stage 1(exact)이 Stage 3(fuzzy)보다 먼저 실행되므로(`map()` L158-171 vs L281-286),
이 두 alias를 등록하면 해당 라벨은 그 즉시 안전한 버킷으로 확정되고 결합형 alias의
포함관계 매칭에는 영영 도달하지 않는다 — `_fuzzy_match()` 엔진 자체는 건드리지 않는
가장 좁은 수정.

**안전성**: `bs.other_current_payables`·`bs.other_noncurrent_liabilities`는 둘 다
`std_financials_v3`에 저장 컬럼이 없는(§1) "흡수용" 버킷 — 이 두 alias를 추가해도
새로 어딘가에 값이 잘못 채워질 위험이 없다. 유일한 효과는 "지금까지 `bs.trade_payables`
후보 풀을 잘못 오염시키던 후보가 사라지는 것"뿐이라 **순수 차감(subtractive)** 수정
([[gateb-full-reaudit-is-required-to-close]]류 재감사 필요성은 여전히 있지만, R53/54의
"가산이라 회귀 불가" 논리의 반대 방향으로 역시 안전 — 잘못된 후보를 없애는 것이지
진짜 정답 후보를 없애는 게 아님).

## 4. 검증 절차(승인 후)

1. `account_maps/bs_accounts.py` 2줄 추가.
2. 드라이런: 위 §2 SQL로 뽑은 39개사·339행 전체에 대해 `combine.py::_map_label()`을
   직접 호출해 새 canonical이 실제로 `bs.other_current_payables`/
   `bs.other_noncurrent_liabilities`로 바뀌는지, 그리고 그 필링의 `bs.trade_payables`
   후보 풀에서 해당 후보가 사라지는지 확인(코드 미변경 드라이런, R54와 동일 방식).
3. 표본 재감사(종근당홀딩스 2건 우선) → fail_a→pass 전환 확인.
4. **전수 재백필 + 전수 재감사** — 이번 건은 R53/54(순수 검증기 오버레이)와 달리
   `std_financials_v3` 본체 값이 바뀌므로(§2의 39개사 339행), std_v3 재빌드
   (`--standardize-only` 또는 해당 corp 범위 재빌드) → 전수 gateb_audit 재감사까지
   필요. 장시간 작업([[feedback-long-running-commands]]) — 사용자 실행 권장.
5. 재감사 후 fail_a 회귀 0건 확인, 39개사 중 실제로 trade_payables 값이 바뀐
   corp 목록을 최종 보고(전부 지주회사류인지 재확인 — 만약 일부가 실제로는
   진짜 매입채무를 이 라벨에 적어놓은 특수 케이스라면 개별 예외 필요할 수 있음,
   §2는 "가능성이 높다"이지 100% 확정은 아님).
6. `docs/PARSING_RULES.md`에 신규 R번호로 등재.

## 5. 범위 밖

- 갤럭시아에스엠(1건) — 별도 문서, face_audit 쪽 문제.
- §2 스캔에서 나온 39개사가 전부 "매입채무 없는 지주회사류"인지는 표본(2개사)만
  확인했다 — 나머지 37개사는 §4-2 드라이런/§4-5 전수 검증 단계에서 실측 필요.

## 6. 승인 대기

이 문서는 설계만 담았다. 구현(alias 추가 + 드라이런 + std_v3 재백필 + 전수
재감사)은 사용자 승인 후 별도로 진행한다([[feedback-plan-then-wait]]).
