# 핸드오프 — 4계층 재설계 착수 (새 세션 시작점, 2026-07-19)

> **이 문서부터 읽을 것.** 승인된 계획 = `docs/plans/rearchitecture_4layer_2026-07-19.md`
> 관련 메모리 = [[rebuild-phase-a3-done]] · 구 Phase C 계획 = `docs/plans/loop-vivid-bubble.md`(보존)

---

## 0. 한 줄 요약

파서가 "값/canonical/취합"을 판단하다 **금융업 이중섹션**(평면 fact 로 합산-vs-제외 구분 불가)에서
막혔다 → 사용자 결정: **4계층 분리**(다운로드 / 파서=원문 tree 충실전사 / 취합 별도 / App).
**계층2(신규 `report_lines` tree)부터 재설계.** 전량 79k·swap 보류.

## 1. 왜 여기까지 왔나 (맥락)

- 이번 세션은 Phase C 재구축 파일럿(11사, version=2) + D4 충돌 정리(finance_cost·retained_earnings·
  capex·K-IFRS·금융업)를 진행.
- **결정적 발견**: KG케미칼(금융업 부문) 현금및현금성자산이 `유동자산 288,717,146,272` +
  `금융업자산 2,112,712,279` **두 섹션**에 존재(합 290,829,858,551 = CF 기말현금과 정확 일치).
  **평면 fact 로는 "합산(이중섹션) vs 제외(sub-line)"를 구분 불가** → 헤드라인(현금·유형자산·차입금)
  통째 결측. 원인 = **tree 없음 + 판단이 파서에 섞임**.
- ⟹ 사용자 재framing: 계층별 책임 분리로 논리오류 격리. (파서=전사만, 다운로더가 다운로드만 하듯.)

## 2. 확정 결정 (재설계, 2026-07-19)

1. 계층2 = **신규 `report_lines` tree 테이블**(greenfield). fact_v2 는 전환기 공존→퇴역.
2. tree 충실도 = **섹션경로 + 행순서 + depth + 소계flag** (부모=성분합 강제 안 함).
3. 기존 취합자산(concept_map·account_maps·std_v2·reconcile·D4 로직) = **계층3으로 이관·재사용**.
4. **전량 79k·swap 보류** → 계층2 → 계층3 → 그다음 전량.

## 3. 다음 세션 첫 작업 (계획 §계층2)

**`report_lines` 스키마 설계 + 추출 구현.** 핵심:
- 재사용: `fin2/extract/text.py`(섹션 네비·`declared_unit`·`_AMOUNT_CELL_RE`·`table_direct_rows`·
  `_row_to_fact`) — canonical 호출만 제거하고 tree 컬럼 채움.
- 신규: 하위섹션 경로(유동/비유동/**금융업**), row_order·depth·is_subtotal, 주석 tree(본문 먼저·주석 다음).
- 단위만 원(₩) 정규화, 미선언 보류+flag. **canonical/grouping 없음.**
- 검증: 보고서 원문 ↔ report_lines 1:1(라벨·값·위치). face_audit/line_audit 확장.
- **금융업 카나리아**: KG케미칼 2023FY(rcept 20240321001911) 현금 두 섹션 라인 모두 존재해야.

## 4. 현재 코드 상태 (전부 main 커밋됨, 작업트리 clean)

이번 세션 커밋(최신순): `3c87e27`(capex 소계-only) · `c814539`(D4 2R) · `2a69802`(K-IFRS 전용
+잔존차단+무결성) · `a09df33`(concept_map A/C+Track A 재map) · `dd70db3`(face_audit 복구) ·
`3aa8cd5`(D4 1R) · `b2eec3c`(Phase C 파이프라인+파일럿) · `082cee3`(plan 이관).

**★ 이 커밋들은 폐기 아님 — 계층3(취합) 로직으로 재사용.** D4/K-IFRS/금융업/capex 판단은
계층3에서 tree 기반으로 재정리. 단 **std_v2/fact_v2 파일럿 데이터는 재설계 후 재생성 대상**.

### 재사용 산출물
- `scripts/phase_c_rebuild.py` — 기업 순차·원자커밋·재개·재-map 패턴(계층2/3 오케스트레이션 참고).
- `scripts/phase_c_integrity_check.py` — 무결성 8종(stale/dup/orphan/혼입/순수성/재map/clean_slate).
- `scripts/phase_c_review_digest.py` — 보류큐 패턴 다이제스트.
- `fin2/audit/face_audit.py`·`line_audit.py` — 보고서↔DB 대조(Phase A 호환 복구됨).
- `docs/qa/audit_concept_map_collapse_2026-07-18.md` — concept_map collapse 전수감사(20종).

## 5. 계층3에서 해결할 이월 이슈 (tree 있으면 깨끗)
- **금융업 이중섹션 합산**(section_path 기반; 총계로 검증) — 이번 세션 미해결의 핵심.
- **capex 소계-우선/성분합**(is_subtotal 기반). 위지트 원문: 성분합≠소계, 소계가 정답.
- K-IFRS 영업이익(dart_ 전용)·dual-section·sub-line 제외 — D4 로직 이관.
- D4 잔여 충돌(파일럿) 14: short_term_debt 6(금융업)·note D&A 5·retained 2·investing 1.
- fuzzy 승급 빚(A): text.py docstring 경고 — 정당한 alias 승격(계층3 사전에서).

## 6. 상태 주의
- ⚠ 야간 잡(gapfill·collect) **중지 유지** — 재설계 중 오염 방지([[nightly-jobs-paused-phase-a3]]).
  계층3 완료·검증 후 복구.
- ⚠ 앱은 std_v2 version=1(구 데이터) 계속 사용 중 — swap 안 함(재설계 후).
