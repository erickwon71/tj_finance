# Gate B — face_audit.py inventory/ppe concept_map 갭 설계 (2026-08-28)

## 0. 배경

[[gateb-session-handoff-2026-08-28]] 인계 시점 fail_a 135건 중 inventory(16)+ppe(9)=25건을
원문·코드 대조로 재분류했다. 핸드오프 메모의 "ADECIMAL 스케일 오독, 검증기만 고치면 되는
단일 클래스" 가정은 **부분적으로만** 맞았다 — 25건은 실제로 5개 클러스터로 갈리고, 이
문서는 그중 **스케일 클러스터 10건**(원문·코드 근본원인 확정)만 다룬다.

| 클러스터 | 건수 | 회사 | 이 문서 범위 |
|---|---|---|---|
| 스케일 x1,000,000 | 5 | HD현대일렉트릭(01205851) inventory | ✅ 원인 확정 |
| 스케일 x1,000 | 5 | NC(00261443) ppe×2·오션인더블유(00349811) inventory×1·세미파이브(01627363) inventory×2 | ✅ 원인 확정 |
| 근소한 차이(<1%) | 5 | 랩지노믹스·에이테크솔루션·상신이디피·현대엘리베이터 | ❌ 미대조, 범위 밖 |
| 큰 불일치(비율 불규칙) | 8 | 스타코링크(6)·랩지노믹스(2) | ❌ 미대조, 범위 밖 |
| report_value=0(누락) | 2 | 광무 | ❌ 미대조, 범위 밖 |

## 1. 원인 (원문+코드 확정, [[feedback-verify-against-source]])

두 회사(HD현대일렉트릭 2025FY separate inventory, NC 2026H1 ppe 양쪽 basis)를 원문 XML +
`fin2/audit/face_audit.py` / `fin2/taxonomy/concept_map.py` 코드로 대조해 정확히 같은
메커니즘을 확인했다(오션인더블유·세미파이브도 동일 acode 패턴 재확인, 4/4):

1. 재무상태표(face) 본문의 정답 XBRL fact 는 **`ifrs-full_InventoriesTotal`**
   (inventory) / **`ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets`**
   (ppe) 라는 acode 를 쓴다. 값은 DB(std_v3)와 정확히 일치(won 단위, ADECIMAL="0" 정상).
2. 같은 계정의 주석 상세표("10. 재고자산"/"13. 유형자산")에는 **다른 acode**
   (`ifrs-full_Inventories` / `ifrs-full_PropertyPlantAndEquipment`)의 무차원 합계 행이
   또 있는데, 이 행은 **DART 원문 자체의 렌더러 결함**으로 ADECIMAL="0"이 잘못 태깅되어
   있다(실제로는 그 표의 선언 단위인 백만원/천원 — 형제 세부 라인은 정확한 ADECIMAL을
   가짐). 표시 리터럴이 같은 acode 로 이미 알려진 함정 클래스([[parsing-rules-single-doc]]
   §원문 XML 함정 카탈로그, `_adecimal_signals()` 독스트링의 노루페인트 00583442 사례와
   동일 계열).
3. `fin2/taxonomy/concept_map.py::ACODE_TO_CANONICAL` 에는 `ifrs-full_Inventories`/
   `ifrs-full_PropertyPlantAndEquipment` 만 등록돼 있고, **`...Total`/
   `...IncludingRightofuseAssets` 변형은 등록돼 있지 않다.**
4. 결과: `read_report_face_xbrl()` 이 정답 fact 를 읽어도 `map_acode()` 가 `None` 을
   반환해 `canonical` 이 비고, `audit_fields()` 의 `by_canon["bs.inventory"/"bs.ppe"]` 에
   **정답 후보가 아예 안 들어간다**. 남는 유일한 후보가 ②의 오태깅된 주석 합계 행이라
   `val in won_vals` 가 항상 실패 → `VALUE_DIFF`(fail_a) 오탐.

**결론**: DB(std_v3)는 처음부터 정확했다(별도 라벨 기반 파서가 acode 를 안 봐서 이 갭의
영향을 안 받음). 버그는 100% **face_audit.py(검증기) 쪽 acode 사전 누락**이다 —
[[gateb-session-handoff-2026-08-28]] 가 추정한 "ADECIMAL 오독"이 아니라 "정답 후보가
`map_acode()` 갭으로 후보 집합에서 탈락"이 진짜 메커니즘이다. `_adecimal_signals()`
항등식 로직은 이 갭과 무관하게 정상 동작 중(고칠 필요 없음).

## 2. 영향범위 확인 — concept_map.py 직접 수정은 위험

`fin2/audit/face_audit.py` 의 기존 주석(§8-A 부근)은 "`map_acode()` 소비자 =
face_audit.py/line_audit.py 뿐(R23, 2026-08-15 확정)"이라고 적혀 있으나, 이번 조사로
**stale 임을 확인**했다: `fin2/extract/xbrl.py` 도 `map_acode()` 를 써서
`ExtractedFact.canonical_account` 를 채우고, 이 모듈은 `run.py`(라이브 수집 파이프라인,
`store_facts`)에서 실제로 호출된다. 즉 `concept_map.py::ACODE_TO_CANONICAL` 은 감사 전용이
아니라 **운영 XBRL 추출 경로와 공유되는 파일**이다.

→ 이 alias 2개를 `concept_map.py` 에 직접 추가하면 face_audit 갭은 고쳐지지만, 운영
`fact_v2` 적재 쪽에 미치는 영향은 **이번 조사 범위에서 확인하지 않았다** (`canonical_account`
가 std_v3 최종 계산에 실제로 소비되는지, 소비된다면 이 두 acode 가 이미 다른 경로로
커버되고 있었는지 등 — 별도 조사 필요, 지금 범위 밖).

## 3. 제안 수정 (스코프 제한, 운영 경로 영향 0)

`concept_map.py` 는 건드리지 않는다. 대신 `fin2/audit/face_audit.py` 안에 **감사 전용
로컬 alias 오버레이**를 추가해 `map_acode()` 가 `None` 을 반환할 때만 폴백으로 쓴다:

```python
# face_audit.py 전용 — concept_map.py(운영 fin2/extract/xbrl.py 와 공유)는 건드리지 않는다.
# BS face 본문이 쓰는 acode 변형인데 concept_map.py 미등록인 것들(2026-08-28,
# gateb_faceaudit_inventory_ppe_acode_gap_design_2026-08-28.md).
_FACE_AUDIT_EXTRA_ACODE: dict[str, str] = {
    "ifrs-full_InventoriesTotal": "bs.inventory",
    "ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets": "bs.ppe",
}

def _map_acode_face(acode: str) -> str | None:
    return map_acode(acode) or _FACE_AUDIT_EXTRA_ACODE.get(acode)
```

`read_report_face_xbrl()` L716 의 `canonical = map_acode(acode)` 를
`canonical = _map_acode_face(acode)` 로 교체(1줄).

이 변경은 face_audit 후보 집합만 넓힌다(기존 PASS 를 깨뜨릴 수 없는 단조 개선 —
`_with_ni_attribution_text_fallback` 와 같은 원칙). DB/std_v3 재백필 불필요 — R50 계열과
동일하게 **검증기만 고치고 전수 재감사**로 닫는다.

## 4. 검증 계획

1. 위 10건(HD현대일렉트릭 5·NC 2·오션인더블유 1·세미파이브 2) 표본으로 `gateb_audit.py
   --corps ...` 재실행 → fail_a→pass 전환 확인.
2. 전수 재감사([[gateb-full-reaudit-is-required-to-close]] — 표본만으로 닫지 않는다) —
   장시간 명령이라 사용자 실행 권장([[feedback-long-running-commands]]).
3. fail_a 회귀 0건 확인(다른 필드에 부수효과 없는지).

## 5. 범위 밖 — 다음 세션 후보

- 근소한 차이(<1%) 5건, 큰 불일치 8건(스타코링크 6건 포함), report_value=0 2건(광무) —
  각각 원문대조 미착수. 스타코링크(00373571) 6건이 비율이 2~6배로 들쭉날쭉해 다음
  우선순위로 보인다.
- `concept_map.py` 자체에 `InventoriesTotal`/`...IncludingRightofuseAssets` 를 정식
  등록할지(운영 `fin2/extract/xbrl.py` 영향 조사 포함)는 별도 트랙 — 이번엔 손대지 않는다.

## 6. 승인 대기

이 문서는 설계만 담았다. 구현(코드 수정 4줄 + 표본 검증 + 전수 재감사)은 사용자 승인 후
별도로 진행한다([[feedback-plan-then-wait]]).
