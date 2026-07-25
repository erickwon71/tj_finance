# 핸드오프 — 계층2 주석 전사 완료 + 계층3 note→D&A 매핑 착수점 (새 세션 시작점, 2026-07-26)

> **이 문서부터 읽을 것.** 이전 핸드오프 = `docs/qa/handoff_layer3_profiles_2026-07-24.md`(보존) ·
> 마스터 허브 = `docs/plans/rearchitecture_4layer.md` · 브리지 swap = `docs/plans/layer3_v3_bridge_swap_2026-07-25.md` ·
> 주석 전사 설계 = `docs/plans/layer2_notes_transcription_2026-07-25.md` · 메모리 = [[rebuild-phase-a3-done]]
>
> git main 최신 = **`9541a66`** (미커밋 코드 없음)

---

## 0. 한 줄 요약
**계층2 주석(note) 전반 전사 = 완결**(별도 테이블 `note_lines` ~2.1억행 · 정확한 번호 주석제목 · 백필 완료).
다음 = **계층3 note→D&A 매핑**. 이는 std_v2→std_v3 **브리지 swap**(→C-1)의 선행 관문.

## 1. ★아키텍처 불변식 (잠금)
**원문 보고서 직접 read = 계층2 전용**. 계층3·4는 `report_lines`/`note_lines` 에서만 읽는다(검증만 예외).
파생계정(D&A) 소스가 주석이면 계층2 전사 → 계층3 매핑. 메모리 [[architecture-report-read-layer2-only]].

## 2. 이번 세션 완료 (전부 main 커밋·머지)
- **금융 revenue**: 여신전문·저축은행 gross 프로파일 + 다올 override(`d0c5dc0`), 잔여 KSIC census 종결 =
  프로파일 불필요(`ff54fb0`), 원문대조 15건 PASS. → `docs/plans/financial_sector_revenue_standards.md`.
- **브리지 swap 계획**(`254766f`·`94a8d77`): std_v3(2015+) UNION std_v2(≤2014), enrichment v3-native, C-1 자동.
- **std_v3 enrichment steps 1-2**(`d43974e`): 스키마 9컬럼 + combine 이 **capex/fcf/net_debt** 산출
  → **2026-07-26 전량 재빌드로 std_v3 반영 완료**(§3.1b). ⚠ D&A/ebitda · shares_out · data_quality 미채움.
- **★계층2 주석 전사**: `note_lines` 테이블(트윈, `38100fe`) + 로더 `--notes`(`2590191`) + **note 제목
  정확화**(running-header 번호제목, `9541a66`) + **백필 완료**(6shard SUCCESS · 에러 0 · ~2.1억행).

## 3. 현재 상태

### 3.1 검증된 사실 (2026-07-26 재확인)
| 항목 | 값 |
|---|---|
| `note_lines` | 210,346,832행 (reltuples) |
| `report_lines` | 64,508,192행 |
| `std_financials_v3` | 185,266행 · 2,534 corp (enrichment 반영 완료) |
| git main | `9541a66`, 워킹트리 clean |

### 3.1b ★std_v3 전량 재빌드 완료 (2026-07-26)
`build_std_v3.py --all` 실행 — **2,534 corp · 185,266 rows · 1,885s · 오류 0**.
⚠ 재빌드 전에는 enrichment 3컬럼이 **전부 0행**이었다(코드 `d43974e` 는 커밋됐으나 std_v3 미반영 상태였음.
이전 핸드오프의 "capex/fcf/net_debt ✅완료"는 **combine 단계 스팟검증만** 한 것이었고 전량 빌드는 미실행).

| 컬럼 | 채움 | 커버리지 |
|---|---|---|
| capex | 169,859 | 91.7% |
| fcf | 168,966 | 91.2% |
| net_debt | 128,158 | 69.2% |
| da_total · ebitda | **0** | D&A 매핑(§4-1) 전이라 정상 |

**v2 대조 검증** (v2 canonical = `not is_stub and not is_discrete`, version desc 최신 1행.
⚠ v2 PK 는 `(corp,fy,fp,statement_type,version,is_stub,is_discrete)` 라 4키 조인만 하면 **팬아웃**한다):
공통 169,257행 기준 capex 일치 91.0% · fcf 90.4% · net_debt 86.7%.
- **대형주 정확 일치**: 삼성전자·현대차·셀트리온 FY2024 consolidated/separate 6/6 OK.
- **불일치 13,885건 분해**: v2가 10배↑ 과대 **38.8%** + 10⁵배↑ 과대 0.1% = **약 39% 가 v2 스케일버그**
  (예: 다원넥스뷰 FY2024Q3 v2 capex −220조 vs v3 −2.2억 = ×10⁶). **v3 가 정답.**
  나머지 59.7% 는 동일 자릿수 차이 = capex 구성 CF라인 정의 차이 → **미조사, 잔여과제**.
  1.4% 는 v3 가 10배↑ 큼 → 소수지만 **v3 쪽 의심 케이스, 우선 확인 대상**.
- 불일치는 연도·분기에 고르게 분포(특정 연도 편중 없음) → 데이터 손상이 아니라 정의 차이 성격.
- ★대전제 유지: **V2는 정답이 아님 — DART 원문이 기준**([[rebuild-phase-a3-done]]).

⚠ `section_path` 인덱스 없음 → `LIKE '%..%'` · `COUNT(*)` full-scan 느림
(**corp_code 바운드 + reltuples** 로 우회할 것).

### 3.2 ★정정 — "현대차·셀트리온·에코프로는 CF주석에 D&A 없음"은 **사실이 아님**
이전 세션(2026-07-25)의 진단은 **틀렸다.** 세 기업 모두 `note_lines` 에 D&A 가 정상 전사돼 있고,
**v2 값과 정확히 일치**한다. FY2024 연결 기준 대조:

| 기업 | 주석 섹션 | table_seq | note 값 | v2 값 | |
|---|---|---|---|---|---|
| 현대자동차 | `29. 비용의 성격별 분류` | 694 | dep 3,397,606백만 / amort 889,400백만 | 동일 | ✅ |
| 셀트리온 | `32. 비용의 성격별 분류` | 943 | dep 72,604백만 / amort 345,638백만 | 동일 | ✅ |
| 에코프로 | `28. 비용의 성격별 분류` | 617 | dep 176,273+3,681=179,954백만 / amort 19,853백만 | 동일 | ✅ |
| 삼성전자 | `27. 현금흐름표` col0 | — | dep 396,500억 | 동일 | ✅ |

**이전 진단이 놓친 실제 원인 3가지 (= 계층3 매핑이 풀어야 할 것):**
1. **CF주석 제목이 기업마다 다름** — 삼성 `27.현금흐름표` / 현대차·에코프로 `33.현금흐름` /
   셀트리온 `35.영업으로부터 창출된 현금`. `LIKE '%현금흐름표%'` 로 찾으면 **삼성만** 걸린다.
2. **라벨 표기가 다름** — `감가상각비` / `감가상각비에 대한 조정` / `감가상각비, 유형자산`
   (+ `감가상각비, 사용권자산` 분리 → **합산 필요**).
3. **당기/전기가 `col_index` 가 아니라 별도 `table_seq` 로 분리됨** — 해당 행은 전부 `col_index=0`,
   `context_fiscal_year` 는 **NULL**. 위 표의 앞 `table_seq`(작은 값)가 당기.

⇒ 난이도는 "소스 부재 → 다중소스 폴백"이 **아니라** **"당기 `table_seq` 식별 + 라벨 정규화"**.
⇒ **`비용의 성격별 분류` 주석이 4사 모두에서 작동하는 공통 소스** → 1차 소스를 CF주석 대신
   이쪽으로 잡는 것이 더 단순. CF주석은 2차 폴백(+ 교차검증)으로.

### 3.3 대조용 원문 (FY2024 사업보고서)
| 기업 | corp_code | rcept_no | DART |
|---|---|---|---|
| 현대자동차 | 00164742 | 20250312001148 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250312001148 |
| 셀트리온 | 00413046 | 20250317000929 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250317000929 |
| 에코프로 | 00536541 | 20250318001116 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250318001116 |
| 삼성전자 | 00126380 | 20250311001085 | https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250311001085 |

로컬 원본 경로: `raw_report/{KOSPI|KOSDAQ}/{corp_code}_{corp_name}/annual/{fy}/{rcept_no}.xml`
(에코프로만 KOSDAQ). 4건 모두 존재 확인.

### 3.4 ⚠ raw_report 저장소 = **SD카드** (현재)
`raw_report` 심링크 → `/Volumes/dart_data` = **SD카드**(`/dev/disk4s1`, Protocol: Secure Digital,
Removable, 477Gi 중 54% 사용). NAS(`//tjkwon@192.168.0.96/tj_finance_data`, 1.5Ti)는 `/Volumes/tj_finance_data`
에 **별도 마운트**돼 있으나 raw_report 는 여기를 쓰지 않는다.
→ 계층2 재파싱·백필 전에 **SD카드 마운트 여부를 먼저 확인**할 것(미마운트 시 심링크가 빈 경로가 됨).
관련 메모리 [[nas-migration-plan]] · [[gapfill-nightly-automation]].

## 4. 다음 착수점 (순서)
1. **★계층3 note→D&A 매핑** — `note_lines` 에서 corp-fy-basis D&A 수집:
   - **1차 소스 = `비용의 성격별 분류` 주석**(4사 공통 확인). 2차 = CF주석(제목 variant 3종 매칭).
   - **당기 `table_seq` 식별 로직**이 핵심 (동일 section_path 내 최소 table_seq = 당기로 보이나 **전수 검증 필요**).
   - 라벨 정규화: `감가상각비{,·에 대한 조정}` + `, 유형자산`/`, 사용권자산` **합산**, `무형자산상각비` 분리.
     `parser/xml/note_extractor._DA_ACCOUNT_PATTERNS` 재사용.
   - v2 `da_total` 캘리브레이션 → `note.*` canonical → combine `_apply_enrichment` 주입 →
     `rule_additive_da` + `rule_derive_ebitda` → std_v3 `depreciation`/`amortization`/`da_total`/`ebitda`.
   - 파편 추출기(`notes.py`·`cf_da.py`·`rd_note.py`) 흡수.
   - ⚠ 이전 세션의 진단초안 `$CLAUDE_JOB_DIR/tmp/find_da_loc.py` 는 **휘발성 경로 → 소실**. `scripts/` 에 새로 작성.
2. **capex 잔여 불일치 조사**(§3.1b): ① v3가 10배↑ 큰 193건(v3 의심, **우선**) ② 동일 자릿수 차이
   8,291건(capex 구성 CF라인 정의 차이) — 원문 대조로 v3 정의 확정.
3. **shares_out**: 계층2 일반현황(주식의 총수) → 별도 shares 테이블(주석 아님).
4. **collect_new 데일리 배선**(runbook 두 call site) — ⚠ 아직 미배선.
5. **뷰 브리지 교체**(`collector/db.py` standard_financials → v3 UNION v2) →
   **G2(★v3 = 원문 기준)** → **C-1 자동**(tearsheet 금융블록·스크리너).
   상세 = `docs/plans/layer3_v3_bridge_swap_2026-07-25.md` §4.

## 5. 관련 문서
`docs/plans/rearchitecture_4layer.md`(허브) · `docs/plans/layer3_v3_bridge_swap_2026-07-25.md` ·
`docs/plans/layer2_notes_transcription_2026-07-25.md` · `docs/plans/financial_sector_revenue_standards.md`.
메모리 [[rebuild-phase-a3-done]] · [[architecture-report-read-layer2-only]].
