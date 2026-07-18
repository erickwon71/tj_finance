# 핸드오프 — Phase C 착수 논의 (다음 세션 시작점, 2026-07-18)

> **이 문서부터 읽을 것.** 계획 = `~/.claude/plans/vast-nibbling-blum.md`
> 앞선 핸드오프: A-3 완료 = `handoff_rebuild_phaseA3_2026-07-17.md` ·
> Phase B 인벤토리 = `phase_b_target_inventory_2026-07-18.md`

---

## 0. ⚠ 먼저 알아야 할 상태

### 야간 잡이 **중지**돼 있다 (아직 복구 안 함)
`gapfill`·`collect` 가 disabled(작업트리를 실행하므로 재구축 중 오염 방지). 복구 명령은
[[nightly-jobs-paused-phase-a3]] 또는 아래:
```bash
U=$(id -u); for j in gapfill collect; do
  launchctl enable gui/$U/com.tjfinance.$j
  launchctl load ~/Library/LaunchAgents/com.tjfinance.$j.plist; done
```
**Phase C 는 이 잡들과 무관한 별도 오케스트레이션**이 필요하다(아래 §2). collect 재개는 Phase C
완료 후가 안전(중간상태 파서로 신규수집분을 뽑지 않도록).

### 지금까지 한 것 (커밋됨, `git log` e30486d..f8ad211)
- **Phase A(A-1/A-2/A-3)**: 섹션기반 추출 재설계 + provenance 4컬럼 + 추측로직 제거(단위·max-abs·
  항등식재선택·period_end/is_ifrs/shares_out 추론·note.da_total 합성·rd_note 전역스캔).
- **퍼지 alias 승급**: 커버리지 손실 **90.5%→36.1%**. stage 우선 `_collect`(exact>normalized>fuzzy)로
  공존 회귀 방지. 금융사 현금+예치금 규칙. 잔여 36%는 대부분 정당한 결측.
- **Phase B**: 대상 **79,010 보고서 / 2,452 기업** 확정 → `rebuild_target_track1` 테이블.

**중요**: 위 파서 변경은 전부 **staged** 상태다 — 현 fact_v2 는 구 추출본이라 아직 반영 안 됨.
Phase C 재파싱이 실제로 이걸 DB 에 적용한다. (그래서 stage 우선 _collect 도 현재는 무효 =
전 행 stage NULL → 재파싱 후 활성.)

---

## 1. Phase C 가 하는 일 (계획 §4 Phase C)

```
rebuild_target_track1 (79,010) 을 샤딩
  → 각 보고서 재파싱(신 text.py) → fact_v2 재구축(엄격 추출, 추측 0)
  → 확정분 적재 / 애매분 보류(value_lineage 기록)
  → 기업단위: statement_source → std_v2 → quarterly → calendar 재전파
  → 보류큐를 원인 패턴별 그룹핑 → 대표사례 사용자 확인 → 파서개선 → 재실행(패턴루프)
```
체인: `fact_v2` → `statement_source`(reconcile) → `std_financials_v2` → quarterly → calendar.

---

## 2. ★ 착수 전 논의할 결정들 (다음 세션 주제)

### D1. 재구축 방식 — **in-place vs 신버전 swap**
- **in-place**: 기존 fact_v2 를 재파싱값으로 덮어씀(ON CONFLICT). 단순하나 **재파싱 중 앱이
  반쯤 갱신된 상태**를 본다. 롤백 어려움.
- **swap**(계획 권장, §5-3): std_v2 를 `version=2` 로 구축 → 검증(Phase D) → 통과하면 소비계층을
  version 2 로 교체. 안전하나 fact_v2 도 버전 개념이 필요(현재 fact_v2 는 버전 없음) → 설계 필요.
  - fact_v2 는 rcept 단위라, 대상 rcept 의 기존 행을 지우고 재삽입하는 방식이 현실적일 수도.
- **결정 필요**: 이게 Phase C 전체 구조를 정한다. **가장 먼저 합의할 것.**

### D2. 샤딩 + 오케스트레이션
- 규모: 79,010 보고서, 실측 ~150파일/분 → **순수 파싱 ~9시간** + 표준화. 며칠 야간 소요.
- 패턴: `scripts/verify_corp_sequential.py` 의 **기업 순차 루프**(2,452사) 재사용 가능.
  기업단위 원자커밋(DB 가 체크포인트) → 중단/재개 안전.
- **결정 필요**: (a) 전용 launchd 야간잡 신설? (b) foreground 배치를 사용자가 수동 실행?
  (c) 샤드 크기(기업 N개씩)? gapfill 잡처럼 완료시 자기해제 패턴 쓸지.

### D3. shares_out 재백필 순서 (필수)
C17 로 재구축 시 std_v2.shares_out 은 NULL 로 시작. **각 기업 재표준화 직후 `shares.py`
재백필**을 파이프라인에 넣어야 valuation_daily(PER/PBR/시총)가 안 깨진다. 놓치면 앱 멀티플 전멸.

### D4. 패턴루프 운영 (사용자 협업)
보류큐(value_lineage + 본문없음 + 단위미선언)를 **원인 패턴별로 묶어** 대표사례만 사용자 확인
요청 → 파서개선 → 재실행. "값 하나씩" 아님. 이 루프를 몇 회 돌릴지·언제 "영구결측 인정"할지.

### D5. Phase D 검증 게이트 (swap 전 통과조건)
```sql
-- 주석섹션이 본문 canonical 생산 금지
SELECT count(*) FROM fact_v2 WHERE section_kind IN ('연결재무제표주석','재무제표주석')
  AND canonical_account ~ '^(bs|is|cf)\.';                    -- 0
-- 본문섹션이 note.* 생산 금지
SELECT count(*) FROM fact_v2 WHERE section_kind IN ('연결재무제표','재무제표')
  AND canonical_account LIKE 'note.%';                        -- 0 (단 cf_da 의 section_kind=NULL 예외 주의)
-- 단위추측 미적재
SELECT count(*) FROM fact_v2 WHERE unit_source <> 'declared'; -- 0
-- 퍼지 매핑 canonical 미부여
SELECT count(*) FROM fact_v2 WHERE canonical_account IS NOT NULL AND mapping_stage='fuzzy'; -- 0
```
+ Gate B(`gateb_audit --no-commit`): fail_a=0·value_diff=0·골든셋 5/5 · fin2 회귀.
+ DB손해보험 카나리아(별도 이익잉여금 8,564,682,463,043) · magnitude 어서션 307→0 수렴.

---

## 3. Phase C 후 마무리 (순서 있음)
1. **shares 재백필**(D3) → valuation_daily 재전파.
2. **provenance 인덱스 추가**(재구축 후 전 행 NULL 아니게 되면) — fact_v2 4컬럼 + value_lineage.
3. **소비자 swap/검증**(D1·D5) → 앱·스크리너 확인.
4. **야간 잡 복구**(§0) — collect 먼저 신 파서로 정상동작 확인 후.

## 4. 범위 밖(별도 트랙, 기록만)
- **Track A(XBRL) 16,384 재구축** — ★ 최근연도(2024+) 재무가 여기 몰려 있어 영향 큼
  (Phase B 에서 2024 이후 Track B 급감 확인). 3S/네오크레마형 단위오기가 Track A 에도 가능.
- **정정본 7,689**(xml_text 보유) → Track 2.
- **구형서식 2000~2014**(63,007) → Track 3.
- **expense_nature 전기→당기 오적재 ~29k**(재추출로 자연교정), notes.py U1·note_extractor U4 잔존.

---

## 5. 재현·검증 명령
```bash
# 대상 인벤토리 재확인
python scripts/phase_b_build_targets.py --summary

# 퍼지 잔여 재측정(파일기반, 재파싱 전에도 동작)
python scripts/fuzzy_alias_survey.py --limit 300 --out docs/qa/fuzzy_alias_worklist.md

# 카나리아(재파싱 전에도 신 파서로 확인 가능)
python - <<'PY'
from fin2.extract.text import extract_facts
f=extract_facts('raw_report/KOSPI/00159102_DB손해보험/half/2023/20230927000457.xml',
  rcept_no='20230927000457',corp_code='00159102',report_fiscal_year=2023,report_fiscal_period='H1')
print([x.amount_won for x in f if x.canonical_account=='bs.retained_earnings'
       and x.basis=='separate' and x.col_index==0])  # [8564682463043]
PY

# 회귀
for f in fin2/tests/test_*.py; do python "$f"; done   # 19/21(fiscal_relabel·notes 사전존재 무관)
```
