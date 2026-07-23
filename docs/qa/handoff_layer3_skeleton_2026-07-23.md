# 핸드오프 — 계층3 골격 완성(L3-1~L3-4 baseline), 신 체인 std_v3 전량 빌드 (새 세션 시작점, 2026-07-23)

> **이 문서부터 읽을 것.** 이전 핸드오프 = `docs/qa/handoff_layer2_complete_2026-07-22.md`(보존) ·
> 재계획 = `docs/plans/layer3_rebuild_plan_2026-07-22.md`(빌드순서·결정 잠금) · 관련 메모리 = [[rebuild-phase-a3-done]]
>
> 세부 보고서: L3-1 `layer3_L3-1_combine_prototype_2026-07-22.md` · L3-1b `layer3_L3-1b_filing_selection_2026-07-22.md` ·
> L3-2 `layer3_L3-2_source_matching_2026-07-22.md` + split-table `layer2_split_table_gap_2026-07-23.md` ·
> L3-3/L3-4 `layer3_L3-3_std_v3_build_2026-07-23.md` · 옵션A `layer3_option_a_probe_2026-07-22.md` ·
> 셀키 정규화 `layer3_cellkey_normalization_finding_2026-07-22.md`

---

## 0. 한 줄 요약

**신 체인 계층3 골격 완성.** report_lines(계층2) → `std_financials_v3`(계층3) **전량 빌드 완료
(185,208행·2,534사)**, 전수 parity **MATCH ~98%**. 기재정정 반영·출처 provenance 포함. 작업트리
clean, 이번 세션 커밋 22개. **다음 = L3-4 DIFF 전수 유형분류 + 카탈로그 정제 → L3-5 swap.**

## 1. 이번 세션에 한 일 (신 체인 단독 진행 — 사용자 결정)

**정리·환경**
- venv `.venv_tj_finance`→`.venv` 통일(내부 shebang 44 + 문서/plist/스크립트). NAS 미마운트 import 크래시 방어(`collector/config.py`).
- 야간 launchd 잡 **7종 전량 삭제**(재부팅 부활 안 함, 원본은 repo `deploy/launchd/`) — [[nightly-jobs-paused-phase-a3]].
- **raw_report 심링크 = SD카드 `/Volumes/dart_data/raw_report` 로 전환(사용자 지시, 유지 중)**. 원래=NAS `/Volumes/tj_finance_data/raw_report`.

**계층3 (핵심)**
- **옵션A 검증**: 기존 라벨카탈로그(account_maps+AccountMapper)를 계층2에 걸어 std_v2 재현 → DIFF≈0. 2015+ 표준화 성립.
- **L3-1 조합엔진**(`fin2/layer3/combine.py`): 구 체인 `_resolve`/`_reduce_conflict` 이식(acode→label_raw).
- **L3-1b 정본 정책**(★사용자 확정): **최초등록본 + 순차 델타 패치**. 기재정정의 바뀐/추가 셀만 오버레이,
  패치셀에 "기재정정 반영" 표시(amended/amended_by/amend_chain). 값=P1(as-restated)이되 부분정정서 원본 보존.
  정본 선택은 statement 단위 폴백(첨부정정 대응).
- **L3-2 출처매칭**: basis 폴백(단일 basis 기업 연결→별도) + **split-table 추출기 수정**(§2).
- **L3-3 std_v3 전량 빌드**: 185,208행. provenance(source_rcepts·amended_cols·amend_chain·basis_fallback·conflicts).
- **L3-4 parity baseline**: 전수 std_v3↔std_v2 MATCH ~98%.

## 2. ★ 계층2 추출기 수정 (split-table) — 이번 세션 큰 곁가지

**근본원인**: 재무제표명(제목표)과 숫자(데이터표)가 **다른 표**로 분리된 서식에서 추출기가 0행
(보험/증권 + 일반사 특정연도, 로더 done 중 2.9%=2,974 filing). 수정=`fin2/extract/text.py:
_detect_body_statement_tables` 전방연결(데이터없는 분류표→다음 데이터표, 단위도 따라옴, 가산적·무회귀).
- 런북 3층: C=흥국화재 0행→846행·std_v2 6/6일치·회귀테스트2종·fin2 186pass / B=`load_report_lines.py
  --redo-empty`(신규옵션) **0행 2,974→591(2,383복구·+1.19M행)** / A=report_lines 데일리 미편입(swap시점 과제).
- 잔여 591=split-table 아닌 구서식(2014·비12월Q1) 별건. NO_LINES 범위내 ~439→~31.

## 3. 신 체인 자산 지도 (코드/테이블)

| 계층 | 코드 | 테이블 |
|---|---|---|
| 2 원문tree | `fin2/extract/report_lines.py`·`text.py` / 로더 `scripts/load_report_lines.py` | `report_lines`(62.87M행) |
| 3 조합 | `fin2/layer3/combine.py`(combine_full·build_merged_lines·select_canonical_rcepts) · `fin2/layer3/build.py` | `std_financials_v3`(185,208행) |
| 빌드 드라이버 | `scripts/build_std_v3.py`(--all·--corp·--shard, 멱등) | |
| 진단 프로브 | `scripts/layer3_*.py`(combine_probe·ablation·diff_characterize·amendment_*·cellkey_normalize) | |

**핵심 설계 포인트(다시 매달리지 말 것)**:
- 값 안 고침(report_lines 원문 보존). 조합만 계층3.
- SIGN 자동판정 3회 실패→포기(격리). 셀키 라벨 정규화=지금 하면 SCE 충돌 454>드리프트189 순손해(세부항목 확장 시 SCE제외 scoped).
- 정본=최초등록본+델타(P1), as-filed 복원은 amend_chain 으로.

## 4. 전수 parity 현황 (L3-4 baseline, FY)

8지표 MATCH **97.8~99.1%**. DIFF~2% 성격(net_income 922 표본): **38%(353)=amended(v3 재작성반영·
회귀아님)**, 나머지=카탈로그(보험 매출 alias)·부호·반올림. v3only=split-table 복구분. v2only(revenue
914 최다)=보험/증권 매출 alias + 비교열-소싱 잔여.

## 5. 다음 세션 — 무엇을 할지 (순서 제안)

### ★ 착수 지점(사용자 확정) = 1. L3-4 DIFF 전수 유형분류
8지표 DIFF(전수 std_v3↔std_v2, §4 baseline ~2%)를 자동 분류:
- (a) **정상 불일치** [소급재작성·연결범위변동] — v3 의 `amended_cols`/`amend_chain` 있거나
  source_rcept 가 v2 와 다르면 대량 자동식별(net_income 표본 38%가 여기). 회귀 아님.
- (b) **회귀** — 같은 filing·같은 출처인데 값이 다른 것(엔진/매핑 결함). ★우선 조사 대상.
- (c) **카탈로그 롱테일** — 보험/증권 매출 alias 등(2번에서 정제).
착수 방법: `scripts/layer3_diff_characterize.py` 확장 or SQL 전수 집계(§4 쿼리 재사용) →
지표별 (a)/(b)/(c) 비율 + (b) 표본 원문대조. 산출 = `docs/qa/layer3_L3-4_diff_classification_*.md`.
DB 무변경(읽기전용 분석). 심링크 SD카드·야간잡 삭제 상태 그대로 이어감.
2. **카탈로그 롱테일 정제** — 보험/증권 매출 alias(보험영업수익 승급 등). account_maps 수정 →
   ⚠계층2 재추출 불요(계층3 조합 재실행만: `build_std_v3.py --all` 25분).
3. **합산/파생 지표 이식** — rules.py additive(D&A·EBITDA·차입합계·capex) → std_v3 컬럼 추가.
4. **L3-5 swap** — 앱을 std_v3 로 재배선(app/data 소비처) + 구 체인(fact_v2·statement_source·구 std_v2·
   text.py 텍스트트랙) 제거 + report_lines 데일리 배선(collect_new.py) + 야간 잡 재설치.

## 6. 상태 주의

- ⚠ **야간 잡 전량 삭제 유지** — swap 전까지 구 체인 오염 방지([[nightly-jobs-paused-phase-a3]]).
- ⚠ **앱은 여전히 구 체인**(std_v2) 사용 — swap 안 함(L3-5).
- ⚠ **raw_report 심링크 = SD카드**(`/Volumes/dart_data`) 유지 중(사용자 지시). NAS 원복은 별도 결정.
- ⚠ std_v3 provenance: 빈 값이 **JSONB `null` 스칼라**(SQL NULL 아님) → 배열 카운트는 `jsonb_typeof='array'`.
- report_lines 대용량(62.87M) — `node_role`·`label_raw` 전량 정규식 스캔은 인덱스 없어 느림(측정기반 인덱스는 L3-6 미정).
- venv=`.venv`(CLAUDE.md 반영됨).
