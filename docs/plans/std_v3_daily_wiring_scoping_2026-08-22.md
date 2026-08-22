# std_v3 정기 배선 — 스코핑 메모 (2026-08-22)

> Phase 5(`docs/plans/collection_pipeline_restore_2026-07-31.md` §7) §6 미결정 항목의 후속.
> 이 문서는 **결정 전 조사 결과**다. 구현은 별도 세션에서 이 문서를 설계로 확장한 뒤 진행한다.

## 배경

`collect_new.py`(데일리 파이프라인)는 `std_financials_v3`를 절대 만들지 않는다
(2026-08-21 발견). std_v3는 `scripts/build_std_v3.py`로만 수동/별도 배치로 채워진다.
2026-08-22 Phase 5(`--download-only` 해제)로 daily가 파싱·표준화(std_v2)까지는 다시
매일 돌지만, std_v3는 여전히 배선 밖이다 — 매일 새로 쌓이는 데이터가 std_v3엔 영영
안 들어갈 수 있다는 뜻.

## 현재 구조 실측 (2026-08-22)

### `standard_financials` 뷰는 v3 우선 + v2 폴백이라 앱은 당장 안 깨진다

```sql
SELECT ... FROM std_financials_v3 v3
  LEFT JOIN face_audit fa ON ... AND fa.source_version = 'v3'
  WHERE COALESCE(fa.gate_status,'unaudited') <> 'fail_a'
UNION ALL
SELECT ... FROM std_financials_v2 s
  LEFT JOIN face_audit fa ON ... AND fa.source_version = 'v2'
  WHERE s.version=1 AND NOT is_stub AND NOT is_discrete
    AND COALESCE(fa.gate_status,'unaudited') <> 'fail_a'
    AND NOT EXISTS (SELECT 1 FROM std_financials_v3 v3b WHERE ... 같은 키)
```

`NOT EXISTS v3` 조건 덕에 v3에 없는 (기업,연도,기간)은 v2로 자동 폴백된다. **std_v3를
안 돌려도 앱에 빈 구멍은 안 생긴다.** 다만:
- v2 폴백 행엔 `industry_lines`(업종별 세부) 같은 v3 전용 필드가 없다.
- v2 폴백 행의 `gate_b_status`는 `face_audit.source_version='v2'` 감사 결과를 본다 —
  아래 Gate B 문제와 직결.

### `build_std_v3.py`는 std_v2가 아니라 report_lines(계층2)에서 직접 재구축한다

`fin2.layer3.build.build_corp()` — std_v2 파이프라인과 별개 소비 경로. 배선하려면
daily의 `_sync_layer2_lines`(report_lines 적재, ④-3) **이후**에 붙여야 순서가 맞다.

### Gate B `source="v2"` 고정은 의도된 것 — 무작정 못 바꾼다

`_run_dq_gate`(collect_new.py L152-165 부근)는 `gateb_audit.audit_corp(..., source="v2")`
로 고정돼 있다. 2026-08-17에 발견/수정된 사유(코드 주석 원문):
> "std_financials_v3 는 이 파이프라인이 안 만든다 — 별도 수동 배치만 채운다. source='v3'
> 로 두면 방금 수집한 신규 기간이 std_v3 에 아직 없어 감사 대상 0건인 채로 '이상없음'을
> 반환하는 위양성 그린(false-green) 게이트가 된다."

즉 지금 상태(v3 미배선)에서 Gate B가 v2를 보는 건 정답이다. **std_v3를 배선하면 이
전제가 바뀌므로 Gate B source 도 같이 재설계해야 한다** — 안 그러면 두 가지 나쁜 선택지만
남는다: (a) v3가 매일 새로 쌓이는데 감사는 계속 v2만 봐서 v3 커버리지가 영영 안 늘거나,
(b) source를 그냥 v3로 바꿔서 당일 수집분에 대해 다시 위양성 그린이 재발하거나.

## 미해결 설계 질문 (다음 세션에서 결정)

1. **Gate B source 전환 방식** — 같은 날 두 번(v2 즉시 + v3는 하루 지연 후) 감사할지,
   아니면 v3 빌드를 ④ 직후로 당겨 같은 실행 안에서 v2→v3 순서로 만들고 감사는 v3만
   할지. 후자면 `_run_dq_gate` 호출 위치 자체도 옮겨야 한다.
2. **두 call site 배선** — 런북(`docs/runbook_new_parser_pipeline_integration.md`)
   체크리스트대로 메인 경로 + `--standardize-only` 재개 경로 둘 다.
3. **비용 실측** — 데일리 신규 대상은 보통 수 개사 수준(오늘 실측 1~5개사)이라 부담은
   작을 것으로 예상되나, 실측 전이라 확정 아님.
4. **face_audit 이중 관리** — v2/v3 두 source_version이 계속 공존하게 둘지, 장기적으로
   v2 감사를 걷어낼지도 같이 정리 필요(범위 크면 별도 트랙으로 분리 가능).

## 참고
[[phase5-remaining6-resolved-2026-08-22]](메모리), `docs/plans/collection_pipeline_restore_2026-07-31.md` §7,
`docs/runbook_new_parser_pipeline_integration.md`, `docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md`.
