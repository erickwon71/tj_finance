# 핸드오프 — 재무데이터 재구축 **Phase A-3 완료** (2026-07-17)

> **다음 세션 시작점.** 마스터 계획 = `~/.claude/plans/vast-nibbling-blum.md`
> 직전 핸드오프(A-1/A-2) = `docs/qa/handoff_rebuild_phaseA_2026-07-17.md`
> 커밋: `e30486d`(A-3 1/2 추출기) · `5652db5`(A-3 2/2 build.py)

---

## 0. ⚠ 지금 당장 알아야 할 것 2가지

### ① 야간 launchd 잡이 **중지**돼 있다 (복구 필요)
A-3 작업 중 작업트리가 실 DB 를 오염시키지 않도록 사용자 승인 하에 내렸다.
launchd 잡은 **git HEAD 가 아니라 작업트리를 실행**하므로 중간상태 코드가 밤에 돌아버린다.

```bash
U=$(id -u)
for j in gapfill collect; do
  launchctl enable gui/$U/com.tjfinance.$j
  launchctl load ~/Library/LaunchAgents/com.tjfinance.$j.plist
done
launchctl list | grep -E "gapfill|collect"        # 둘 다 보이면 복구
launchctl print-disabled gui/$U | grep tjfinance  # enabled 여야 함
```
**언제 복구하나**: Phase B/C 로 넘어가기 전, 또는 파서 손대는 작업이 끝났을 때.
(`valuation`·`backup`·`vacuum`·`dqcheck`·`restoredrill` 은 그대로 살아있다.)

### ② **재구축 결과를 DB 에 반영하기 전에 갚아야 할 빚**이 있다
아래 §3 참조. 특히 **퍼지 alias 승격**을 안 하고 Phase C 를 돌리면 커버리지가 무너진다.

---

## 1. 완료된 것 (Phase A-3)

계획서 §4 Phase A 의 Tier 1 추측 로직 중 **A-3 표에 있던 항목 전부**.

| # | 항목 | 처리 |
|---|---|---|
| **M1/M2** | 퍼지 매핑 | canonical 미부여 + `mapping_stage`/`confidence` **기록**. 행은 보존(무손실) |
| **C1/C6/C7** | max-abs 채택 | 폐지 → 값 충돌 시 **보류** + `value_lineage` 에 후보 전체 기록 |
| **C3/C4/C5** | 항등식 재선택 | operating_income·controlling_ni 사후 재선택 **삭제** |
| **F6** | period_end 12월 가정 | filing 권위값 → 결산월 도출 → None. **비12월 결산 오산도 교정** |
| **F7** | is_ifrs=(fy≥2011) | Track A 증거 있을 때만 True, 그 외 None |
| **C17** | shares_out ← 주가테이블 | 제거. record 에서 키를 빼 **기존 보고서값 보존** |
| **D8/D11** | note.da_total 합성 | 원문에 결합라인 있을 때만 방출. 분리공시는 rule_additive_da 가 파생(기록됨) |
| **rd_note** | 전역 TABLE 스캔 | '사업의 내용' 섹션 한정 + 단위추측 제거 |

**스키마**: `fact_v2`(A-2 기적용) + `std_financials_v2.value_lineage` JSONB 신규
(`2026_07_std_v2_value_lineage`, 적용 완료).

---

## 2. ★ 실측으로 잡은 것 (A-1 의 함정 4종에 이어)

계획을 그대로 따랐으면 놓쳤을 것들. **구조·동작 가정은 반드시 실측으로 검증할 것.**

| # | 가정 | 실측 반증 |
|---|---|---|
| 5 | "퍼지 canonical 제거 = 기계적 적용"(핸드오프의 모델 권고) | 퍼지는 **과잉매핑과 정당한 표기변형 구제를 동시에** 하고 있었다. 그냥 끄면 **214/287(74.6%)** 보고서가 지표를 잃는다 |
| 6 | expense_nature 는 표 텍스트에서 단위를 찾는다 | **한 번도 못 찾고 백만원 기본값**을 써왔다. 실제 선언은 **표제표**에 있다(실측 선언: 천원 78·원 24·백만원 21) |
| 7 | expense_nature 값열 = '공시금액' 1열 | 구형은 `[구분\|당기\|전기]` **2열**이고, '가장 오른쪽 숫자'는 **전기**다 → **전년 D&A 를 당기로 적재** |
| 8 | 퍼지가 붙던 `이익잉여금,39>` = 유사 이름 | `<주석19/>` **엘리먼트 잔재**였다. 정제 실패이지 유사성이 아님 → normalizer 수정으로 정확일치 |

---

## 3. ★★ 재구축 전에 갚아야 할 빚 (Phase C 착수 조건)

### (1) 퍼지 alias 승격 — **최우선**
M1/M2 로 퍼지 canonical 을 껐다. 실측(2015+ 287보고서) **214건(74.6%)** 에서 std_v2 소비
canonical 이 사라진다:

```
is.controlling_ni 130 · bs.trade_payables 70 · bs.trade_receivables 64
bs.controlling_equity 54 · is.tax_expense 47 · is.net_income 25 · …
```

퍼지가 하던 두 일을 갈라야 한다:

- **(A) 승격 대상** — alias 미등록인 정당한 표기변형. account_maps 에 추가하면 exact/normalized 가 된다.
  `법인세비용(수익)`(등록된 건 `법인세비용(이익)`) · `판매비와일반관리비`(vs `판매비와관리비`) ·
  `경상연구개발비`(vs `연구개발비`) · `지배기업의 소유주에게 귀속되는 당기순이익(손실)` ·
  `지배기업의 소유주지분`
- **(B) 무매핑 확정** — 다른 개념에 붙던 것. **이번 재구축의 표적이므로 없어지는 게 정답.**
  `금융부채`→short_term_debt · `기타무형자산`→intangibles(상위개념의 부분집합!) ·
  `매출채권 및 기타유동채권`→trade_receivables · `I. 현금및예치금`→cash
  (뒤 둘은 `_FUZZY_BLOCK` 의 `현금및예적금` 과 같은 **합산성 라벨** 계열)

**작업목록 추출**(이제 가능 — stage 를 기록하므로):
```sql
SELECT acode, count(*) FROM fact_v2 WHERE mapping_stage='fuzzy'
GROUP BY 1 ORDER BY 2 DESC LIMIT 100;
```
⚠ 단 이 SQL 은 **재추출 후**라야 의미가 있다(현 fact_v2 는 구 추출본이라 전 행 NULL).
그 전에는 `scripts/` 에 표본 스크립트를 두고 파일에서 직접 뽑아야 한다.

### (2) expense_nature 전기→당기 오적재 (사용자 결정: **A-3 후 Phase C 에서 함께**)
`note_expense` 2015~2023 구간 **~29k facts** 가 전년값을 당기로 갖고 있을 수 있다
(2024+ iXBRL 1열 서식은 무영향). 표본 200건 중 dep/amo **149/198** 이 달라진다
(배율이 10의 거듭제곱이 아님 = 전기/당기 차이). 파서는 이미 고쳤으므로 재추출하면 교정된다.
EBITDA 커버리지 지표에 반영돼 있다.

### (3) 잔존 Tier 1 (A-3 표에 없었으나 §2-A 에 있음)
- `notes.py:43-61` `_unit_factor` — 배율 5종 대입 + 매출비율 근접 채택(U1). **미제거**.
- `parser/xml/note_extractor.py:60-65` `_detect_unit_in_text` — 미표기 시 **백만원 기본**(U4). **미제거**.
- `cf_da` 의 note 경로가 위 둘을 소비한다 → cf_da 의 D11 만 고친 상태.
- `cf_da._synth_facts` 는 CF 본문 여러 라인의 합이라 `section_kind=None`(정직). **note.\* 를
  운반수단으로 쓰는 설계 자체**가 Phase C 재검토 대상(주석이 아닌데 note.* 를 단다).

---

## 4. 다음 단계

**Phase B(대상 선별)** → **Phase C(재구축 + 패턴루프)** → **Phase D(검증)**. 상세 = 계획서 §4.

- Phase B: `filings.report_nm NOT LIKE '%정정%'` · **(기업,기간) 단위 판정**
  (⚠ `is_amendment` 사용 금지 — [첨부정정] 1,145 누락).
- Phase C 착수 전 **§3 (1) 필수**, (2)는 재추출로 자연 교정.
- Phase C 직후 **shares 재백필 필수**(C17 로 신규 INSERT 행은 shares_out NULL 로 시작 →
  놓치면 valuation_daily PER/PBR/시총 전부 NULL).
- Phase D 어서션은 계획서 §4 Phase D 참조. `unit_source <> 'declared'` = 0 ·
  `mapping_stage='fuzzy' AND canonical_account IS NOT NULL` = 0 이 이제 **성립 가능**해졌다.

---

## 5. 재현/검증 명령

```bash
# 회귀 (fiscal_relabel·notes 의 ModuleNotFoundError 는 사전존재·무관)
for f in fin2/tests/test_*.py; do python "$f"; done

# ★ 8.5경 카나리아 (이제 테스트로도 고정됨: test_text.py::test_db_insurance_retained_earnings_canary)
python - <<'PY'
from fin2.extract.text import extract_facts
f = extract_facts('raw_report/KOSPI/00159102_DB손해보험/half/2023/20230927000457.xml',
    rcept_no='20230927000457', corp_code='00159102',
    report_fiscal_year=2023, report_fiscal_period='H1')
print([(x.amount_won, x.mapping_stage, x.unit_source, x.section_kind) for x in f
       if x.canonical_account=='bs.retained_earnings' and x.basis=='separate' and x.col_index==0])
# 기대: [(8564682463043, 'normalized', 'declared', '재무제표')]
PY

# 보류(충돌) 현황 — 재구축 후
psql -d tj_finance -c "
SELECT jsonb_object_keys(value_lineage) AS canon, count(*)
FROM std_financials_v2 WHERE value_lineage IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 20;"
```

---

## 6. 보류 목록 (직전 핸드오프 §7 계승, 변동분만)

1. 307행 DQ=3 격리 여부 — 여전히 보류. 목록 = `docs/qa/list_impossible_values_exposed_2026-07-17.md`
2. 제외 리스트(본문없음·정정본만 108개 기간) 사후 처리
3. Track A(XBRL) 영향 확인 — fact_v2 의 21.6%
4. `order_backlog` 납기 컬럼 추가
5. `app/data/order_backlog.py:43` 단위 혼합 합산 버그
6. `shares.py` 단위 로직 부재(`(단위:천주)` 시 1000배 과소)
7. 외화 표시 재무제표(CNY/USD) — 현재 적재 거부(정답), FX 환산 설계 필요
8. **(신규)** rd_note 후보 다중 시 연결/별도 판별 — 현재 보류 처리(실측 60건 중 12건 보류)
