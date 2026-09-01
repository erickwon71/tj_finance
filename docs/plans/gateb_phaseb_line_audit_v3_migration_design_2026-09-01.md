# Gate B Phase B(`line_audit.py`) fact_v2 이탈 설계 — 계층2 GC §4-3 (2026-09-01)

★이 문서는 **설계 전용**이다. 구현은 포함하지 않는다(`CLAUDE.md` "계획 후 대기" 정책).

★★**방향 결정 완료(2026-09-01, 사용자)**: **Option 2 — 라벨 기반 이식 + 주당/주식수 계열
명시 제외**(§5 권고안 채택). Phase 0-5는 결정 완료로 소진됐다. 다만 **착수 지시는 아직
별건**이다 — 실제 실행은 사용자의 명시적 요청을 기다린다.

- 상위 트랙: `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §4-3
- 선행 완료: §4-1(reconcile 확인) · §4-2(`extended_financials` 뷰 라벨 기반 재설계, 커밋 `243e9ee`)
- 후속: §4-4 `fact_v2` DROP(55GB 회수)

---

## 0. 결론 선행 (요약)

1. **스코핑 문서의 "가장 고위험" 평가는 실측 결과 과대평가였다.** 근거: 지난 한 달간
   R15~R60 전수재감사의 "회귀 0건" 판정은 전부 **Phase A(`face_audit.py` →
   `face_audit` 테이블)** 기준이었고, Phase A는 `fact_v2`를 **단 한 줄도 읽지 않는다**
   (§2-1 코드 근거). §4-3이 건드리는 Phase B(`line_audit.py` → `face_line_audit`)는
   **완전히 분리된 측정 전용 축**이다. → **§4-3이 R-트랙 기준선을 깨뜨릴 경로는 구조적으로
   없다.**
2. 다만 Phase B는 죽어 있지 않다 — **데일리 알림의 실제 소비자**가 하나 살아 있다
   (`collect_new.py:765`, `line_value_diff`가 verify 단계 실패 알림을 띄운다). "측정 전용"은
   promote 뷰 기준이지 배선 기준이 아니다.
3. **진짜 난점은 위험이 아니라 키 설계다.** `report_lines`에는 `acode`가 없고
   (§3-2 스키마 실측), 게다가 현재 `FaceLine.label`은 **계정 라벨이 아니라 금액 셀
   텍스트**다(`face_audit.py:790`, `label=text[:80]`) — 즉 **지금 있는 재료만으로는
   라벨 조인조차 불가능**하다. 이식하려면 리더에 행 라벨 확보를 먼저 넣어야 한다(Phase 1).
4. **현재 Phase B 신호의 품질은 이미 심각하게 낮다.** Track A는 감사된 17,552 rcept 중
   **9,609건(54.7%)이 fail_a**이고, 그 값불일치 89,660줄 중 **57,368줄(64.0%)이
   EPS·주식수 계열 단일 오탐 클러스터**다(§3-3). 이식 여부와 무관하게 이 축은 이미
   트리아지되지 않은 채 방치돼 있었다.
5. **권고 = Option 2(라벨 기반 이식) + EPS/주식수 계열 명시 제외.** 이유는 §5. 단,
   Option 1(은퇴)도 방어 가능한 선택지였다.
   → ★**2026-09-01 사용자 결정: Option 2 채택.** 결정 근거로 제시된 것은 "②로 갔다가
   실패하면 ①로 내려갈 수 있지만 역은 성립하지 않는다"(가역성)와 "감사 대상이 곧 버릴
   `fact_v2`에서 실제 소스인 `report_lines`로 옮겨간다"(정정 성격)이다.

---

## 1. 이 단계가 하는 일 / 하지 않는 일

| | 대상 |
|---|---|
| **범위 안** | `fin2/audit/line_audit.py`(Phase B 리콘실러), `scripts/gateb_audit.py::audit_lines()`의 `fact_v2` 쿼리, `face_line_audit` 테이블 의미, `corp_verify_status.line_*` 롤업, 데일리 알림축 |
| **범위 밖** | Phase A(`face_audit.py`·`audit_std_row`·`face_audit` 테이블) — `fact_v2` 무관, 손대지 않는다 |
| **범위 밖** | `fact_v2` DROP 자체와 나머지 잔여 소비자(§7) — §4-4 |
| **범위 밖** | Track A fail_a 9,609건의 **원인 트리아지**(EPS 오탐 수정 등) — 이식 후 별도 R-트랙 후보(§8) |

---

## 2. 현재 구조 실측

### 2-1. Phase A와 Phase B는 완전히 분리돼 있다 (★핵심 근거)

```
Gate B (scripts/gateb_audit.py)
├─ Phase A  audit_corp() → audit_std_row()      [fin2/audit/face_audit.py]
│    비교: 원문 XML 독립 재추출(FaceLine) ↔ std_financials_v3 의 25개 표준필드
│    산출: face_audit 테이블 (gate_status: pass/fail_a/fail_b/pending)
│    ★ fact_v2 참조 0건 — grep 확인(fin2/audit/ 내 "fact_v2" 히트는 line_audit.py 뿐)
│    ★ R15~R60 전 트랙의 "전수재감사 회귀 0건" 판정 = 전부 이 표의 gate_status 전이
│
└─ Phase B  audit_lines()  → reconcile_report_lines{,_text}()  [fin2/audit/line_audit.py]
     비교: 같은 FaceLine ↔ fact_v2 (col_index=0, NOT is_dimensional)
     산출: face_line_audit 테이블 (line_gate_status: pass/fail_a/pending)
     ★ 이번 §4-3의 유일한 대상
```

`face_audit.py`가 `fact_v2`를 안 읽는다는 사실이 이 트랙 전체의 안전 근거다 — Phase B를
어떻게 바꾸든(심지어 통째로 지워도) Phase A의 판정은 **비트 단위로 동일**하다.

### 2-2. `fact_v2` 의존 지점 — 정확히 한 곳

`scripts/gateb_audit.py:303-311`

```sql
SELECT rcept_no, acode, canonical_account, basis, is_cumulative, adecimal, amount_won
FROM fact_v2
WHERE rcept_no = ANY(:rs) AND col_index = 0 AND NOT COALESCE(is_dimensional, false)
```

`line_audit.py` 자체는 **순수 함수**(DB/IO 없음)라 `fact_v2`라는 이름만 docstring에
등장할 뿐, 실제 의존은 위 쿼리 하나다. → **이식 표면적은 생각보다 작다.**

### 2-3. Phase B 산출물의 소비자 인벤토리 (전수 grep)

| 소비자 | 성격 | 조치 |
|---|---|---|
| `scripts/collect_new.py:229-235, 761-767` | **데일리 알림** — `line_value_diff>0`이면 verify 실패 알림 + `fail_corps` 목록에 등재 | ★유일한 살아있는 소비자. 이식/은퇴 어느 쪽이든 배선 조치 필요 |
| `scripts/verify_corp_sequential.py:137-141, 182` | `corp_verify_status.line_total/line_value_diff/line_missing` 롤업 | 배선 조치 |
| `collector/models.py::FaceLineAudit` (1157) · `CorpVerifyStatus.line_*` (1252) | 스키마 | 의미 재정의 또는 DROP |
| promote 뷰(`standard_financials`) | **미참조**(`collector/db.py:151` 주석, models.py:1154) | 조치 불필요 |
| `scripts/dq_assertions.py` | **미참조**(grep 0건) | 조치 불필요 |
| `scripts/restore_drill.py:39` · `purge_foreign_corps.py:53` | 테이블 목록 리터럴 | 은퇴 시에만 정리 |
| `scripts/archive/gateb/line_audit_trackb.py` | 아카이브(1회성 진단) | 무시 |
| `fin2/tests/test_line_audit.py` | 단위테스트 12건 | 재작성 또는 삭제 |

---

## 3. 실측 데이터 (2026-09-01, psql)

### 3-1. `face_line_audit` 현황 — 155,216 rcept

| line_gate_status | rcept | 라인 | match | value_diff | missing | extra |
|---|---:|---:|---:|---:|---:|---:|
| pass | 111,361 | 12,989,310 | 12,950,419 | 0 | 38,891 | 6,233 |
| fail_a | 14,403 | 3,231,706 | 3,130,580 | 97,476 | 3,650 | 10,565 |
| pending | 29,452 | 0 | 0 | 0 | 0 | 0 |

트랙별:

| track | rcept | pass | fail_a | pending | value_diff 라인 |
|---|---:|---:|---:|---:|---:|
| A (XBRL acode 정확대조) | 17,552 | 7,943 | **9,609 (54.7%)** | 0 | 89,660 |
| B (텍스트 canonical 값집합) | 108,908 | 103,418 | 4,794 (4.4%) | 696 | 7,816 |
| C(PDF) / D(xbrl_zip) / NULL | 28,756 | 0 | 0 | 28,756 | 0 |

★2026-08-17 두 설계문서(`gateb_audit_performance_design`·`gateb_evidence_grade_redesign`)의
**"n_missing 86%로 사실상 미작동"이라는 서술은 이제 낡았다** — 그 사이 XBRL 원문 파서가
`fact_v2`를 채워(현재 74,189,269행 / 138,254 rcept) missing은 전체 라인 16,221,016줄 중
42,541줄(0.26%)로 떨어졌다. Phase B는 **지금은 실제로 작동 중**이다. 문제는 커버리지가
아니라 **신호 품질**로 옮겨갔다(아래).

### 3-2. `report_lines`에 없는 것 (`\d` 실측)

| 컬럼 | `fact_v2` | `report_lines` |
|---|---|---|
| `acode` | ✅ (`varchar(255)`, `uq_fact_v2_cell(rcept_no, acode, acontext_raw)`) | ❌ **없음** |
| `canonical_account` | ✅ | ❌ **없음** |
| `is_dimensional` | ✅ | ❌ 없음(차원 셀 자체를 안 만듦) |
| `basis` / `is_cumulative` / `col_index` / `adecimal` | ✅ | ✅ 전부 있음 |
| 금액 | `amount_won` | `value_won` |
| 라벨 | (acode가 대신) | `label_raw` ★ **원문 그대로, 정규화 없음**(`report_lines.py:277`) |
| 기타 | `acontext_raw` | `context_raw`(합성 마커 `text:BS:con:e:c0:2023`), `source_ref`, `node_role`, `section_path`, `depth`, `header_hint` |

원문 표본 확인(`20240312000736` 삼성전자 FY2023 BS): `label_raw="현금및현금성자산 (주4,28)"`,
`context_raw="text:BS:con:e:c0:2023"` — XBRL ACODE/ACONTEXT는 **저장되지 않는다**.
`report_lines.py`가 ACODE를 읽기는 하지만(`:520` `acontext_missing` 신호 산출) 그건
컬럼 절삭 판단용 내부 신호일 뿐 영속화되지 않는다.

**커버리지는 문제없다** — 감사된 Track A rcept 17,552건 중 `report_lines` 보유
**17,552건(100%)**, Track B 108,908건 중 108,398건(99.5%).

### 3-3. ★Track A fail_a의 64%는 단일 오탐 클러스터다

`value_diff_detail` 전수 분해(89,660줄, 상세 캡 200에 걸린 행 없음 — 합계 정확 일치):

| acode | 라인 | rcept |
|---|---:|---:|
| `ifrs-full_BasicEarningsLossPerShare` | 26,442 | 8,604 |
| `ifrs-full_DilutedEarningsLossPerShare` | 21,010 | 6,933 |
| `ifrs-full_BasicEarningsLossPerShareFromContinuingOperations` | 2,621 | 1,234 |
| `ifrs-full_DepreciationInvestmentProperty` | 2,058 | 1,180 |
| `ifrs-full_DilutedEarningsLossPerShareFromContinuingOperations` | 1,893 | 919 |
| `ifrs-full_RightofuseAssets` | 1,112 | 600 |
| `dart_BasicEarningsLossPerSharePreferredStock` | 1,077 | 331 |
| `dart_InterestIncomeFinanceIncome` | 1,028 | 563 |
| `dart_InterestExpenseFinanceExpense` | 844 | 469 |
| `ifrs-full_NumberOfSharesAuthorised` / `NumberOfSharesIssued` | 728 / 649 | 381 / 345 |

**주당·주식수 계열(`~ 'PerShare|NumberOfShares'`) 합계 = 57,368줄 / 89,660줄 = 64.0%.**

표본 원문 확인(3건 무작위):

```
20250515002122  acode=ifrs-full_BasicEarningsLossPerShare  basis=consolidated
                report_won=151,000   db_won=151        (셀 리터럴 "151")
20260323001448  ...                  report_won=407,000,000  db_won=407
20260814000542  ...                  report_won=237,000,000  db_won=237
```

메커니즘: 감사 리더(`read_report_face_xbrl`)가 EPS 셀에 **문서 기본단위 ADECIMAL을
그대로 적용**해 `151 → 151,000`으로 환산하는데, EPS는 원/주라 환산 대상이 아니다.
`fact_v2` 쪽이 정답(151)이고 **감사 리더가 틀렸다**. 이건 이미 알려진 계열의 함정으로,
`report_lines.py`는 `_emit_eps_lines()`(R28 트랙)로 이 문제를 **따로 처리**하고 있다 —
즉 **추출 파이프라인은 고쳐졌는데 감사 리더만 안 고쳐진 상태**다.

두 번째 클러스터(`DepreciationInvestmentProperty`·`RightofuseAssets`·`Interest*` 등)는
`line_audit.py:82-86` docstring이 스스로 경고한 **coarse 키(acode,basis,is_cumulative)의
주석 다중셀 충돌**로 보인다 — 본문 basis 태깅으로 한정해도 남는 잔여. 미확정(Phase 0-4).

### 3-4. 규모 참고

| 테이블 | 행수(est) | 크기 |
|---|---:|---:|
| `fact_v2` | 73,676,192 | **55 GB** ← §4-4 회수 목표 |
| `note_lines` | 254,255,184 | 52 GB |
| `report_lines` | 60,685,464 | 30 GB |
| `face_line_audit` | 155,216 | 166 MB |
| `face_audit` | 578,583 | 159 MB |

---

## 4. 위험 재평가 — 스코핑 문서 §2-2/§4-3 서술의 정정

| 스코핑 문서 서술 | 실측 결과 |
|---|---|
| "Gate B 신뢰성의 핵심 감사 리더" | **부정확.** 핵심 리더는 Phase A(`face_audit.py`)이고 그건 `fact_v2` 무관. Phase B는 별개 축 |
| "감사 리더를 잘못 옮기면 '회귀 0건' 판정 자체를 못 믿게 된다" | **해당 없음.** R-트랙 회귀 판정은 `face_audit.gate_status` 전이만 본다. §4-3은 그 표를 안 건드린다 |
| "가장 크고 리스크 높음" | **작업량은 중간, 리스크는 낮음.** 이식 표면적 = SQL 1개 + 순수함수 1개. 다만 **키 설계 변경 = Phase B 기준선 리셋**이라 트리아지 부담은 실재 |
| "Track A/B 로직 전체 재설계가 필요" | **맞음.** 단 이유가 다르다 — `report_lines`에 acode가 없어서가 아니라, **`FaceLine`에 행 라벨 자체가 없어서**(§3-2 하단, `label=text[:80]`은 금액 텍스트) |

**남는 진짜 리스크 3가지**

1. **기준선 리셋** — 키가 바뀌면 현재 `face_line_audit` 155,216행은 전부 의미가 달라진다.
   전수 재감사(`--recheck`) 필요, 사용자 실행 장시간(Phase A 전수가 90분 규모였으므로
   Phase B 포함 전수는 그 이상). [[feedback-long-running-commands]]
2. **데일리 알림 오작동** — 이식 직후 `line_value_diff`가 새 값 분포로 바뀌면
   `collect_new.py`의 알림이 폭주하거나 반대로 조용해질 수 있다. Phase 4-5에서 임계 재설정.
3. **순환 감사 위험** — DB측을 `report_lines`로 바꾸면 "리더 ↔ 추출기"가 같은
   `document.xml`을 본다. 같은 코드 경로를 공유하면 감사가 무의미해진다.
   → **실제로는 공유하지 않는다**: 감사 리더는 `TE[@ACODE]` + `ACONTEXT` 태그에서
   basis/기간/단위를 직접 얻고(`face_audit.py:702-796`), `report_lines.py`는 표
   렌더링(열 선택·단위=열 판정·섹션 경계·선두 None 절삭 R-규칙)으로 얻는다. **역사적
   버그(R28·classB 유형1·R34/R35 등)가 전부 후자에 있었으므로 감사 가치는 오히려 커진다.**
   단 이 독립성은 **명시적으로 지켜야 할 불변식**이다(Phase 2-1 설계 제약으로 등재).

---

## 5. 선택지 비교

| | Option 1 은퇴 | **Option 2 라벨 기반 이식 (권고)** | Option 3 `report_lines.acode` 추가 | Option 4 Track B만 이식 |
|---|---|---|---|---|
| 내용 | `line_audit.py` 삭제, `face_line_audit` DROP, 배선 제거 | DB측을 `fact_v2`→`report_lines`로, 키를 acode→(정규화 라벨) | 스키마에 acode 컬럼 신설 후 충실 이식 | Track A 은퇴 + Track B만 라벨 이식 |
| 작업량 | 소 (1세션) | 중 (2~3세션) | **대** — 60.7M행 전수 재추출 백필 | 중소 |
| §4-4 차단 해소 | ✅ 즉시 | ✅ | ✅ (백필 완료 후) | ✅ |
| 신호 보존 | ❌ 전량 소실 | ✅ + 감사 대상이 **실제 계층3 소스**(`report_lines`)로 바뀌어 오히려 유의미 | ✅ 충실 | 부분(A 소실) |
| 되돌리기 | 어려움(재구축 비용) | 쉬움(리더/키만) | 쉬움 | 중간 |
| 결정적 단점 | 데일리 알림축 1개 소실 + 완전성 지표(missing/extra) 영구 소실 | 기준선 리셋 트리아지 부담 | Track B는 어차피 acode가 없어 **절반만 해결**되는데 비용은 최대 → **비추천** | Track A가 감사하던 "XBRL 태그 ↔ 표 렌더링" 교차검증이 사라짐 |

### 권고: Option 2 + 주당/주식수 계열 명시 제외

근거 3가지:

1. **감사 대상이 옳은 곳으로 이동한다.** 지금 Phase B는 곧 없어질 `fact_v2`를 감사하고
   있다 — 계층3(std_v3)이 실제로 읽는 건 `report_lines`다. 이식은 "기능 보존"이 아니라
   **감사 대상 정정**이다.
2. **오탐 64%를 값싸게 걷어낼 수 있다.** 주당/주식수 계열 제외는 필터 한 줄이고, 원인이
   감사 리더의 단위 오적용임이 표본으로 확인됐다(§3-3).
3. **은퇴는 언제든 가능하지만 재구축은 비싸다.** Option 2가 실패하면 그때 Option 1로
   내려가면 된다(역은 성립 안 함).

★단, **Option 1도 정당한 선택**이다 — "1,714개사에 fail_a를 띄우면서 한 달간 아무도
트리아지하지 않은 지표"라는 사실은 그 자체로 은퇴 논거다. **Phase 0-5에서 사용자가 결정.**

---

## 6. 단계별 TODO (권고안 Option 2 기준)

> 표기: `[R]`=읽기 전용, `[W]`=코드/DB 변경, `[U]`=사용자 실행(장시간), `[D]`=사용자 결정
> 각 Phase 끝의 **게이트**를 통과하지 못하면 다음 Phase로 넘어가지 않는다.

### Phase 0 — 착수 전 확정 (읽기 전용, 0.5세션)

- [x] **0-1** `[R]` Phase A의 `fact_v2` 무의존 최종 확인 — `grep -rn "fact_v2" fin2/audit/`
      결과가 `line_audit.py` 단독인지 재확인(이 문서 §2-1의 근거를 커밋 시점에 재검증)
      → **완료(2026-09-01)**: `fin2/audit/` 6개 파일 중 `line_audit.py`만 `fact_v2` 참조
      (`face_audit.py`/`curated_key_scan.py`/`line_anomaly.py`/`report_line_audit.py`/
      `__init__.py`는 0건). §2-1 근거 재확인.
- [x] **0-2** `[R]` **기준선 스냅샷 생성** — `face_line_audit` 전체를 별도 테이블로 복제
      (`face_line_audit_snapshot_2026_09_01`). 전이 행렬(Phase 4-3)의 기준이 되므로
      **이걸 안 만들면 이식 후 회귀 판정 자체가 불가능하다**. [[gateb-full-reaudit-is-required-to-close]]
      → **완료(2026-09-01)**: 155,216행(원본과 일치) 복제. `reader_version` 전량
      `trackAB-v2`, `line_gate_status` 분포 `fail_a` 14,403 / `pass` 111,361 / `pending` 29,452.
- [x] **0-3** `[R]` 데일리 알림 실제 발화 이력 확인 — 최근 30일 `collect_new.py` 로그에서
      `line_value_diff` 비0 발화 빈도. **상시 발화 중이면** "기준선 리셋이 회귀가 아니다"의
      근거가 되고, 조용했다면 이식 후 알림 폭주를 방지할 임계 설계가 필요해진다
      → **완료(2026-09-01)**: 실제 launchd 로그는 `logs/collect.err.log`(레포의
      `deploy/launchd/com.tjfinance.collect.plist`는 `--download-only`가 남은 구버전 문서 —
      실제 설치본은 2026-08-22 Phase 5에서 이미 제거됨, 별도 문서 드리프트로 기록만).
      `[verify] 완료` 발화 6회(08-24~08-31, ok corps 있는 날만 발화) 전부
      `line_value_diff > 0`(168/229/77/77/231/664) — **100% 상시 발화**, 매번 ERROR 레벨
      "⚠ 보고서≠DB 확정 불일치" 경보. `fail_a`는 항상 0(Phase A 클린). → 기준선 리셋 = 회귀
      아니라는 근거 확보. 단, 이식 후 Phase 4-6 임계 재설계 시 "현재도 100% 발화 중이라
      노이즈 억제 자체가 필요하다"는 방향으로 참고할 것.
- [x] **0-4** `[R]` 2차 오탐 클러스터 원인 확정 — `DepreciationInvestmentProperty` /
      `RightofuseAssets` / `dart_Interest*` 표본 3건 **원문 XML 직접 대조**로
      "주석 다중셀 coarse 키 충돌" 가설 검증. [[feedback-verify-against-source]]
      (결과에 따라 Phase 2-2의 제외 정책 범위가 달라진다)
      → **완료(2026-09-01), 최초 가설은 부정확 — 실제 메커니즘 재확인 후 정정**:
      원문 XML 표본 대조 직후 "리더가 잘못된 차원분해 셀을 집는다"고 1차 기술했으나,
      `read_report_face_xbrl()` 코드(`face_audit.py:702-796`)를 직접 읽고 정정한다.
      이 함수는 `ctx.is_dimensional` 인 셀을 **명시적으로 skip**(`:762`)하므로 차원분해
      셀 자체를 읽어 들이는 일은 없다. 실제로 벌어지는 일은 더 정교하다 —
      `_adecimal_signals()`(`:178-236`, 2026-08-12 노루페인트 사례로 이미 검증된 기존
      로직)가 **홈(비차원) 셀의 ADECIMAL 을 형제 차원분해 셀들의 산술항등식으로 검증해
      오버라이드**한다: 차원분해 형제(예: 건물/토지)를 각자의 ADECIMAL 로 원화 환산해
      합산한 값이 홈 셀을 어떤 후보 ADECIMAL 로 환산한 값과 실제로 일치할 때만 그
      ADECIMAL 을 "verified"로 채택해 홈 셀에 적용한다(`:772-774`).
      - `ifrs-full_DepreciationInvestmentProperty`(00122056 미창석유공업, `20260515001902`,
        basis=separate): 홈 셀(ClassesOfAssetsAxis 없음) 리터럴 `"(30,367)"`,
        원문 태그 `ADECIMAL="0"`. 형제 — Land `0`(ADECIMAL=-3), Buildings `(30,367)`
        (ADECIMAL=-3). 형제 합산(ADECIMAL=-3 환산) = -30,367,000 = 홈 셀을 ADECIMAL=-3
        으로 환산한 값과 **정확히 일치** → verified override 발동, `report_won`=
        -30,367,000. `db_won`(fact_v2)은 -30,367(원문 태그 그대로, 미보정).
      - `dart_InterestIncomeFinanceIncome`(00878696 에스케이바이오팜, `20260318000773`,
        basis=consolidated)도 동일 구조: 홈 셀 `ADECIMAL="0"` 리터럴 `"7,084,610"` vs
        `FinancialAssetsAtAmortisedCostCategoryMember` 등 형제(ADECIMAL=-3) 합산이
        일치 → verified override로 `report_won`=7,084,610,000.
      - `ifrs-full_RightofuseAssets`(00220613 넥스틸, `20260514001207`): 이 표본은 위
        메커니즘과 다른 변종으로 보인다 — 원문에서 동일 acode+동일 리터럴의 ADECIMAL=-3
        형제 셀을 찾지 못했고, 대신 **다른 acode**(`ifrs-full_PropertyPlantAndEquipment`
        + `RightofuseAssetsMember` 차원)가 같은 리터럴을 가짐. 원인 미확정 —
        `_adecimal_signals`의 키가 acode 를 포함하므로 이 변종이 같은 메커니즘으로
        설명되지 않는다. Phase 1 착수 시 실제 로그/중간값 찍어서 추적 필요(범위는 유지,
        지금 더 파지 않음).
      **핵심 정정 — 어느 쪽이 "정답"인지는 미해결로 남는다**: `_adecimal_signals`는
      2026-08-12 회귀 #1/#2 로 이미 두 번 다듬어진, 산술항등식으로 검증하는 신뢰도 높은
      로직이다(모듈 자체 docstring이 "무차원 홈 fact 가 ADECIMAL=0으로 잘못 태깅되는
      경우가 실제로 있다"는 실측 선례를 남겨둠). 즉 이 2건은 "감사 리더의 버그"가 아니라
      **fact_v2(db_won)가 DART 필러의 알려진 오태깅을 보정 없이 그대로 저장했을 가능성**
      쪽에 무게가 실린다 — Phase 0-4가 원래 전제한 "리더 오탐이니 제외 정책 필요"와
      정반대 결론일 수 있다. `report_lines_xbrl.py`(정식 XBRL instance 소스, `basis`
      판정 시 "정확히 1개 차원만" 요구해 노트 중복을 원천 배제하는 설계, `:43-51`)로
      대체되면 이 클러스터가 아예 안 생길 가능성도 있다 — 다만 이건 **미검증 추정**이다.
      **결론**: 가설 검증 결과 "coarse 키가 못 거르는 주석 다중셀"이라는 원래 진단은
      틀렸다(리더가 차원분해 셀을 직접 읽지 않음이 코드로 확인됨). 실제 원인은 더
      복잡하고, **Phase 2-2에서 이 클러스터를 EPS처럼 단순 제외해서는 안 된다** —
      Phase 1-4 매칭률 실측 + report_lines 쪽 실제 값을 직접 대조해 어느 쪽이 맞는지
      판정한 뒤에 정책을 정할 것(짐작 금지, [[feedback-verify-against-source]]).
- [x] **0-5** `[D]` ~~사용자 결정: Option 1(은퇴) / 2(라벨 이식) / 4(Track B만)~~
      → **완료(2026-09-01): Option 2 채택.** 0-2~0-4보다 먼저 결정됐으므로,
      0-3(경보 발화 이력)·0-4(2차 클러스터 원인)는 **방향 판단용이 아니라 Phase 2-2의
      제외 정책 범위 확정용**으로 성격이 바뀐다(여전히 필수, 순서만 유지)

> **게이트 0**: 0-2 스냅샷이 존재할 것(절대 조건 — 이게 없으면 Phase 4-3 전이 판정 불가).
> ~~Option 1 선택 시 → §6-A로 분기~~ — Option 2 확정으로 §6-A는 **미사용**(중도 후퇴
> 시나리오용으로만 문서에 보존).

### Phase 1 — `FaceLine`에 행 라벨 확보 (Track A 이식의 전제)

- [x] **1-1** `[W]` `FaceLine`에 `row_label: str | None = None` 필드 추가
      (`fin2/audit/face_audit.py:96` 부근). **기존 `label` 필드는 건드리지 않는다** —
      Phase A의 `audit_std_row`/evidence 경로가 그 값을 쓰고 있어 의미를 바꾸면
      **Phase A 회귀**가 된다(§4 리스크 3의 반대 방향 사고)
      → **완료(2026-09-01)**: 필드 추가. `label`은 무변경.
- [x] **1-2** `[W]` `read_report_face_xbrl()`에서 `row_label=_row_label_text(te)` 채우기
      (`face_audit.py:702-796`). `_row_label_text`는 이미 존재(`:685`)하며 UDF acode
      경로에서 실사용 중 — 신규 함수 불요
      → **완료(2026-09-01)**: 채워 넣음. 부수 발견 — `_ni_attribution_structural_candidates()`
      (`:317-407`)가 만드는 합성 `FaceLine`(is.controlling_ni/is.noncontrolling_ni)은
      `read_report_face_xbrl()`의 TE 루프를 안 거쳐 `row_label`이 비었었다. 이 함수는
      이미 라벨 텍스트를 로컬 변수(`label`, `_cell_text(tes[0])`)로 갖고 있어
      `row_label=label` 한 줄 추가로 해소(`:403-408`) — 1-4 매칭률 게이트 측정 중
      드러남, 같은 세션에서 수정.
- [x] **1-3** `[W]` 라벨 정규화 함수 확정 — `_normalize_ws`(`:681`) 재사용 + 주석번호
      꼬리표 제거 필요 여부 판단. ★`report_lines.label_raw`는 **정규화 없는 원문**
      (`"현금및현금성자산 (주4,28)"`)이므로 **양쪽에 같은 정규화를 적용**해야 한다.
      R19(주석번호 가드) 선례 확인 후 결정
      → **완료(2026-09-01)**: R19는 무관(숫자-분리 가드, 라벨 정규화 아님) 확인. 실측
      스크립트로 두 변형(공백제거만 / 공백제거+`(주\d[,\d]*)$` 꼬리표 제거) 비교 —
      매칭률 차이 미미(88.20% vs 88.06%, +0.14pt). **`_normalize_ws`(공백 제거)만으로
      충분** — 주석번호 꼬리표 제거는 효과가 거의 없어 추가 정규화 불필요(단순성 우선).
- [x] **1-4** `[R]` **매칭률 실측(게이트)** — 표본 200 rcept에 대해
      `face.row_label(정규화)` ↔ `report_lines.label_raw(정규화)` 조인 성공률 측정.
      Track A 라인 기준 매칭률을 산출하고, 미매칭 사유를 상위 5개 유형으로 분해
      → **완료(2026-09-01)**: Track A 17,552 rcept 중 무작위 200개, 45,034 face 라인.
      매칭 키는 실제 리콘실러 설계(Phase 2-1)와 동일하게 `(basis, is_cumulative)`
      기준(★`statement`는 키에서 제외 — face 쪽 상당수가 canonical 미매핑으로
      `statement=None`이라 join key에 넣으면 순수 라벨매칭 품질이 안 보임).
      **전체 88.20%**(39,719/45,034). `statement`별 분해로 원인이 뚜렷:
      IS 99.85%(9999/10014) · CF 100.00%(5190/5190) · **BS 83.95%(14077/16769)** ·
      **NONE 80.03%(10453/13061)**. 미스 표본 다수가 재고자산 세부분류
      (상품/제품/재공품/원재료/저장품)·사용권자산 롤포워드·확정급여채무 변동·
      충당부채 변동 같은 **주석(note) 표 항목** — 라벨 정규화 문제가 아니라,
      `read_report_face_xbrl()`의 "basis 태그만 있으면 본문(face)" 휴리스틱이
      **주석 전용 표까지 Track A로 끌어들이고 있다는 신호**(그 표들도 별도 dim 축 없이
      basis 만 태깅됨). `fact_v2` 대조 시절엔 양쪽이 같은 잡음을 공유해 안 드러났다가,
      `report_lines`(presentation-tree 기반, 본문 롤만 저장)로 갈아타면서 노출된
      것으로 보인다 — **미검증 가설**, 표본 사례로만 뒷받침.

> **게이트 1 1차 판정(2026-09-01): 미달** — 88.20% < 95%. IS/CF는 이미 95%를 훨씬
> 웃돌고(99.85%/100%), 미달의 실체는 라벨 키 자체의 불안정성이 아니라 **Track A
> 스코프(본문 vs 주석) 판정 휴리스틱의 정밀도 부족**으로 보임 → 사용자 결정: Phase 1.5
> (본문/주석 판정 로직 보강) 채택.

### Phase 1.5 — 본문(face)/주석 판정 정밀화 (게이트 1 재도전)

- [x] **1.5-1** `[W]` 원인 특정 — `read_report_face_xbrl()`가 "ACONTEXT에 basis 축만
      있으면 본문"이라는 자체 휴리스틱만 쓰는 반면, Track B(`read_report_face_text`)는
      이미 **DART 챕터 섹션 기반 본문표 식별기**(`fin2/extract/text.py::
      _detect_body_statement_tables`, 2026-07-17 재설계 · 무작위 400건 실측 표준섹션
      검출 399/400)를 추출기와 **공유**하고 있었다(모듈 docstring: "표 위치·basis
      식별은 추출기와 공유, 셀 읽기 로직만 독립"). Track A만 이 인프라를 안 쓰고
      있었던 것 — 재고자산 세부분류·사용권자산 롤포워드 등이 basis 축만 갖고
      본문표로 오인된 원인.
- [x] **1.5-2** `[W]` `FaceLine`에 `in_body_section: bool | None = None` 필드 추가
      (`face_audit.py:113` 부근) — **가산 메타데이터**(기존 필터링 대체 아님). Phase A
      (`audit_std_row`/`audit_fields`)는 이 필드를 안 보므로 무영향(직접 확인:
      `asdict`/`vars` 로 FaceLine 필드를 순회하는 코드 없음, grep 0건).
- [x] **1.5-3** `[W]` `read_report_face_xbrl()` 내부에 `_body_te_ids()` lazy 헬퍼 추가
      — `_detect_body_statement_tables(root, _detect_fin_type(root))` 로 얻은 본문
      표들의 `TE[@ACODE]` 원소 id() 집합을 1회 계산(같은 함수의 `_doc_default()` 캐싱
      패턴과 동일). 판정 실패(섹션 미검출) 시 `None` 반환 → 호출측은 배제하지 않음
      (결측>오탐, [[feedback-verify-against-source]]). 각 `FaceLine` 생성 시
      `in_body_section=id(te) in body_ids`(또는 판정불가 시 `None`)로 채움.
      `_ni_attribution_structural_candidates()`의 합성 라인은 미적용(기본값 `None`
      유지 — 이미 IS 본문 총계 행을 앵커로 하므로 배제 대상 아님).
      ★`line_audit.py::_track_a_face()`는 **건드리지 않음** — 그 함수는 지금도 매일
      운영 중인 fact_v2 대상 프로덕션 감사 코드라, Phase 2 착수 전에 바꾸면 오늘의
      실제 Gate B Track A 결과에 영향을 준다. 필터 시뮬레이션은 측정 스크립트에서만
      적용(아래 1.5-4).
- [x] **1.5-4** `[R]` **재측정** — 동일 200-rcept 표본, `_track_a_face()` 결과에
      `in_body_section is not False` 필터를 스크립트 레벨에서만 추가 적용.
      → **전체 100.00%**(38,414/38,414). `in_body_section` 분포(필터 전): `True`
      37,973 · `False` 6,620(제외된 주석표 라인) · `None` 441(판정불가, 배제 안 함).
      `statement`별로도 전부 100%(BS/IS/CF/NONE). 6,620건이 정확히 §1-4가 지목한
      노이즈(재고자산 세부분류류)와 겹침 — 원인 진단이 실측으로 확인됨.
      **성능**: `_detect_body_statement_tables` 추가 호출 비용 실측(2개 표본 ×3회) —
      13~23ms/rcept, 기존 `_adecimal_signals`(46~56ms)·전체 `read_report_face_xbrl`
      (112~144ms) 대비 10~20% 증분. 표본 200건 mean=194.9ms/p50=137.4ms/
      max=1.9s(대형 문서 1건) — 별도 최적화 불요 수준으로 판단.
      **회귀**: `pytest fin2/tests/test_face_audit.py fin2/tests/test_line_audit.py`
      65 passed. `pytest tests/ fin2/tests/`(루트 범위, [[feedback-pytest-scope-raw-report-symlink]])
      673 passed, 무관 사전존재 실패 1건(`test_biz_section.py::
      test_lxintl_facility_table_dropped`, 제조설비지표 추출 — 이번 작업과 무관함을
      `git stash` 전후 비교로 확인, 범위 밖이라 미조치).

> **게이트 1 최종 판정(2026-09-01): 통과** — 100.00% ≫ 95%. Phase 2 진행 가능.

### Phase 2 — 리콘실러 재구현 (`fin2/audit/line_audit.py`)

- [x] **2-1** `[W]` `reconcile_report_lines()` 재작성 — 입력 `fact_rows` →
      `line_rows`(= `report_lines` 행 dict). 비교값 `amount_won` → `value_won`.
      **설계 불변식을 docstring 최상단에 명시**(§4 리스크 3 그대로).
      → **완료(2026-09-01)**: 매칭 키는 설계 초안의 4성분
      `(statement, basis, norm_label, is_cumulative)`이 아니라 **3성분
      `(basis, norm_label, is_cumulative)`**로 구현 — `statement`를 뺀 것은 실측 근거
      (Phase 1-4 게이트 측정 자체가 이미 같은 이유로 `statement`를 키에서 뺀 채
      100.00%를 달성했음, §Phase1 1-4 기록) 그대로 적용한 것. `statement`는
      `LineAudit`의 진단용 필드로만 보존(가능하면 `report_lines` 쪽 값을 권위로).
- [x] **2-2** `[W]` **주당/주식수 계열 제외 정책** — 완료. `_PER_SHARE_ACODE_RE =
      re.compile(r"PerShare|NumberOfShares", re.IGNORECASE)`를 `_track_a_face()`에서
      제외, 상수+주석으로 §3-3 실측 근거(오탐 64%) 링크. **2차 클러스터
      (`DepreciationInvestmentProperty`/`RightofuseAssets`/`dart_Interest*`)는 제외하지
      않았다** — 0-4 최종 결론이 "리더 버그가 아니라 fact_v2 쪽이 DART 오태깅을
      미보정 저장했을 가능성"으로 정정됐고, `report_lines`로 감사 대상을 옮기면 이
      비교축 자체(fact_v2 대비)가 사라지므로 판단을 미룬다 — Phase 4-5 실측(신규
      fail_a 클러스터가 실제로 이 acode 들을 포함하는지)으로 다시 볼 것.
- [x] **2-3** `[W]` `reconcile_report_lines_text()`(Track B) 재작성 — **옵션(b) 채택**
      (라벨 직접 대조로 A/B 통합). `report_lines`에 canonical이 없어 옵션(a)는 애초에
      불가하다는 §3-2 실측을 재확인. 방향성(리더가 당기+비교연도 다중 리터럴을 만들므로
      "DB 당기값 ∈ 보고서 값-집합" 판정)은 구 Track B를 그대로 보존 — 위치 대응(1:1)으로
      바꾸면 비교연도 컬럼이 허위 VALUE_DIFF를 냈을 것(구현 중 직접 확인). **매칭 키는
      Track A와 다르게 `(basis, norm_label)`만 사용**(`is_cumulative` 제외) —
      `read_report_face_text()`가 `is_cumulative`를 실제 축이 아니라 고정 `True`
      placeholder로 채우는 기존 동작을 그대로 보존하기 위함(구 코드도 키에 안 씀,
      회귀가드 테스트로 고정: `test_trackb_is_cumulative_not_in_key`).
- [x] **2-4** `[W]` `fin2/tests/test_line_audit.py` 재작성 완료 — 12건 fixture 전량
      `report_lines` 모양(`label_raw`/`value_won`)으로 갱신 + 6건 신규(EPS 제외·
      in_body_section False만 배제/None 통과·라벨 정규화 경계·라벨 중복행 first-wins·
      Track B is_cumulative 비키 회귀가드 등), 총 18건.
- [x] **2-5** `[R]` `pytest tests/ fin2/tests/` — **완료**: 신규 단위테스트 18/18
      통과. 루트범위 전체 678 passed / 1 failed(`test_biz_section.py::
      test_lxintl_facility_table_dropped`, 이번 작업과 무관한 사전존재 실패,
      [[gateb-phaseb-line-audit-migration-phase0-1-2026-09-01]] 참고) — 회귀 0건.

> **게이트 2**: 단위테스트 전건 통과 + 기존 pytest 회귀 0건. **통과(2026-09-01)**.
> ★`scripts/gateb_audit.py::audit_lines()`는 아직 옛 `fact_v2` SQL과 `LineAudit`의
> 옛 필드(`l.acode`/`l.label`)를 참조하는 채로 **미배선**이다 — 이 시점에 그 스크립트를
> 실행하면 즉시 깨진다(예상된 상태, Phase 3 3-1이 SQL을, `value_diff_detail`/
> `missing_detail` 생성부(`:342-347`)가 새 `LineAudit` 필드(`label`/`acode`/`canonical`)
> 를 쓰도록 같이 고쳐야 함 — 3-1 범위에 이 소비부 수정도 포함시킬 것, 원 체크리스트
> 문구엔 명시가 안 돼 있었음).

### Phase 3 — 배선 (`scripts/gateb_audit.py`)

- [x] **3-1** `[W]` `audit_lines()`의 `fact_v2` 쿼리(`:303-311`)를 `report_lines`
      조회로 교체 — `WHERE rcept_no = ANY(:rs) AND col_index = 0`
      (`is_dimensional` 조건은 `report_lines`에 개념 자체가 없으므로 **삭제**,
      삭제 사유를 주석으로 남길 것)
      → **완료(2026-09-01)**: 조회 컬럼도 `label_raw/basis/is_cumulative/value_won/
      statement`로 교체. Phase 2 인계 메모가 지목한 소비부(`value_diff_detail`/
      `missing_detail` 생성부, `:341-347`)도 새 `LineAudit` 필드(`label`이 매칭 키,
      `acode`(Track A만)/`canonical`(Track B만)는 진단용)에 맞춰 함께 수정 — 3-1
      범위에 포함시킴(원 체크리스트 문구엔 없었으나 Phase 2가 미리 지목).
- [x] **3-2** `[W]` `READER_VERSION` bump (`"trackAB-v2"` → `"trackAB-v3"`) — 완료.
- [x] **3-3** `[W]` `face_line_audit` 컬럼 주석 갱신 — 완료(`collector/models.py:
      1144-1181`). `n_extra`가 report_lines 전환 후 커질 수 있다는 신호 성격 변화도
      컬럼 주석에 명시. **컬럼 자체는 유지**(스키마 변경 없음, 마이그레이션 불요) —
      부수로 §1 스코프에 있던 `CorpVerifyStatus.line_missing`(`:1266`) 코멘트도
      "fact_v2 부재" → "report_lines 부재"로 정정(코드/컬럼 변경 없음, 문구만).
- [x] **3-4** `[W]` `line_audit.py`(Phase 2 기완료)·`gateb_audit.py`·`models.py` 모듈
      docstring의 "fact_v2 커버리지 2.4%" 낡은 서술 정정 완료 — 잔여 `fact_v2` 언급은
      전수 grep 확인 결과 전부 정당(테이블 자체 정의·과거 이력 서술·`fact_v2` DROP
      전 잔여 블로커 문서화 등), 낡은 기술서술 0건.
- [x] **3-5** `[R]` 단일 기업 스모크 — 완료. `--source v3 --corp 00102858 --recheck
      --no-commit`(Track A 위주, 132행: pass 128/fail 0/pending 4, Phase B 라인
      15,589: match 11,564/value_diff 76/missing 3,949, 보고서 gate pass 47/fail_a 19)
      + `--corp 00125521`(Track B 위주, Phase B 라인 15,303: match 10,327/value_diff
      341/missing 4,635, 보고서 gate pass 24/fail_a 40) 둘 다 **크래시 없음**, 라인
      집계 0 아님. `--no-commit`이라 DB 무영향(코드상 `if batch and not args.no_commit`
      가드 확인). Phase A(`gate_status`) 숫자는 이 두 스모크에서 그대로 — Phase 3 는
      Phase A 코드를 안 건드렸으므로 구조적으로 보장.
      `pytest tests/ fin2/tests/` 재확인 678 passed/1 failed(무관 사전존재), 회귀 0건.

> **게이트 3**: 3-5 스모크 통과. `--no-commit`이므로 DB 무영향. **통과(2026-09-01)**.

### Phase 4 — 전수 재감사 + 기준선 재설정 (★가장 오래 걸림)

- [ ] **4-1** `[R]` Phase A 스냅샷도 확보 — `face_audit`의 `gate_status` 현황을
      복제. **Phase B만 바꿨는데 Phase A가 움직였다면 그건 진짜 사고**이므로 이 대조가
      §4-3의 안전 증명이다
- [ ] **4-2** `[U]` **전수 재감사 실행** — `python scripts/gateb_audit.py --source v3
      --recheck` (사용자 터미널 실행, 장시간). 백그라운드 자동실행 ~40분 상한에 걸리므로
      **반드시 사용자 실행** [[feedback-long-running-commands]]
- [ ] **4-3** `[R]` **전이 행렬 작성** — 스냅샷(0-2) × 신규 결과를 `rcept_no` PK 조인해
      `line_gate_status` 전이표 산출. ★**총량 비교로 판단하지 말 것** —
      [[gateb-trade-payables-classB-two-bugs-2026-08-29]]의 교훈(총량은 커버리지 변화에
      오염된다, PK 조인 전이표만이 신호)
- [ ] **4-4** `[R]` **Phase A 무영향 확인** — 4-1 스냅샷과 대조해 `face_audit.gate_status`
      전이 **0건**. 1건이라도 움직이면 즉시 중단하고 원인규명
- [ ] **4-5** `[R]` 신규 fail_a 트리아지 — 상위 클러스터 3개를 acode/라벨별로 분해하고
      각 클러스터에서 표본 2건씩 **원문 XML 직접 대조**. "감사 리더가 틀렸는가 /
      `report_lines`가 틀렸는가"를 판정. **후자면 그건 계층2 진짜 버그**이므로 별도
      R-트랙 후보로 등재(이 트랙에서 고치지 않는다 — 스코프 폭주 방지)
- [ ] **4-6** `[W]` 데일리 알림 임계 재설정 — `collect_new.py:234, 765`.
      4-3/4-5 결과로 나온 정상 배경 수준(baseline noise)을 반영. 무조건 `vd>0` 발화가
      부적절하다고 판명되면 임계 도입 또는 **트랙별 분리 집계**

> **게이트 4**: 4-4가 **전이 0건**일 것(절대 조건). 4-5에서 클러스터가 전부 원인 특정될 것.

### Phase 5 — 정리·문서·인계

- [ ] **5-1** `[W]` `docs/PARSING_RULES.md` 등재 여부 판단 — 파싱 규칙 변경이 아니라
      **감사 규칙 변경**이므로 R번호 부여는 부적절할 수 있다. 이 문서 링크만 걸지
      R-엔트리를 만들지 결정
- [ ] **5-2** `[W]` 스코핑 문서(`factv2_stdv2_gc_scoping_2026-09-01.md`) §4-3 갱신 —
      완료 표시 + §4 위험평가 정정 반영
- [ ] **5-3** `[R]` **§4-4 잔여 블로커 목록 갱신**(§7) — `fact_v2` DROP까지 남은 것 재실측
- [ ] **5-4** `[W]` 커밋 (사용자에게 메시지 복사용으로 제시, `CLAUDE.md` GIT 정책)

### §6-A — Option 1(은퇴) 대체 TODO ★미채택 경로 (중도 후퇴용으로만 보존)

> 2026-09-01 결정으로 Option 2가 채택돼 **이 절은 실행 대상이 아니다.** 게이트 1(라벨
> 매칭률 95%)에서 후퇴하게 될 경우에만 여기로 분기한다.

- [ ] **A-1** `[R]` 0-2 스냅샷을 `pg_dump -Fc`로 파일 백업(`db_backups/`) —
      §6-3 `std_financials_v2` DROP 때와 동일 절차(복원 가능성 확보)
- [ ] **A-2** `[W]` `fin2/audit/line_audit.py` 삭제 + `fin2/tests/test_line_audit.py` 삭제
- [ ] **A-3** `[W]` `scripts/gateb_audit.py` — `audit_lines()`·`--no-line-audit` 인자·
      Phase B 요약 출력(`:415-420`)·import 제거
- [ ] **A-4** `[W]` `scripts/collect_new.py` — `line_audit=True` 인자 제거,
      `line_value_diff` 알림축 제거(`:197, 229-235, 761-767`)
- [ ] **A-5** `[W]` `scripts/verify_corp_sequential.py` 롤업 제거(`:137-141, 182`)
- [ ] **A-6** `[W]` `collector/models.py` — `FaceLineAudit` 클래스 제거 +
      `CorpVerifyStatus.line_*` 3컬럼 제거(마이그레이션 필요)
- [ ] **A-7** `[W]` `scripts/restore_drill.py:39` · `purge_foreign_corps.py:53` 목록 정리
- [ ] **A-8** `[W]` `DROP TABLE face_line_audit` (166MB)
- [ ] **A-9** `[R]` 데일리 1회 완주 확인(`collect_new.py`가 크래시 없이 끝나는지) —
      ★§6-3 DROP 때 `cf_da_sync`/`dq_assertions`가 죽은 채 발견된 전례가 있으므로
      **`pg_depend` 확인 + 실제 1회 실행**을 둘 다 할 것 [[delisting-filepath-nfc-nfd-trap]] 계열 교훈, §5-d 정정 참고

---

## 7. §4-4(`fact_v2` DROP) 잔여 블로커 — 현시점 재실측

§4-3이 끝나도 아직 남는 것:

| 소비자 | 성격 | 상태 |
|---|---|---|
| `collector/cf_da_sync.py:56` | `fact_v2` **읽기+upsert**(D&A note 복원) | ★블로커. 매일 18:00 `collect_new.py`가 호출 |
| `collector/expense_nature_sync.py` | `fact_v2` **upsert**(비용성격 주석 D&A) | ★블로커. §4-2에서 `note.*` 2종 잔여로 이미 문서화됨 |
| `fin2/reconcile.py` | `statement_source` 선택(`fact_v2` 읽기) | 데일리 경로엔 없음 — `run.py:2877, 2926` CLI와 `scripts/phase_c_rebuild.py`만. §4-1 소관 |
| `fin2/extract/*.py` (`notes.py`/`report_lines.py`/`xbrl.py`/`text.py`/`pdf.py`/`statement_titles.py`) | `fact_v2` **쓰기**(추출 파이프라인) | DROP 시 쓰기 경로를 끄는 것이 목적 — 이식 대상 아님 |
| `extended_financials` 뷰 | — | ✅ **해소됨**(§4-2, `243e9ee`) — 현재 뷰 정의는 `extended_facts_v3` JOIN `std_financials_v3`, `fact_v2`/`statement_source` 참조 0건(`pg_get_viewdef` 확인) |
| `scripts/backup_db.py:33` | `EXCLUDE_DATA=("fact_v2",)` | DROP 후 정리 |
| 진단/백필 스크립트 다수 | 1회성 | DROP 후 자연 사망(정리 선택) |

★§4-4 착수 전 **반드시 `pg_depend` 전수 확인**을 다시 할 것 — §5-d에서 텍스트 grep만
믿었다가 `calendar_financials` 뷰를 놓쳐 사고 직전까지 갔던 전례가 있다.

---

## 8. 미결 / 범위 밖

- **Track A fail_a 9,609건의 실제 수정** — EPS 단위 오적용은 **감사 리더 쪽 버그**이며
  (`read_report_face_xbrl`이 EPS에 문서 기본단위를 적용), `report_lines.py`는 R28
  트랙으로 이미 해결했다. Phase 2-2는 그걸 **감사 대상에서 제외**할 뿐 고치지 않는다.
  → 리더를 실제로 고칠지는 별도 판단(고치면 Phase A의 EPS 관련 판정에도 영향 가능 →
  **Phase A 회귀 위험이 있는 유일한 지점**이라 반드시 분리할 것)
- **2차 클러스터(주석 다중셀 coarse 키 충돌)** — 0-4에서 원인만 확정하고 수정은 범위 밖
- **Track C(PDF)·D(xbrl_zip) 28,756 rcept의 영구 pending** — Phase B가 원래 비대상으로
  둔 영역. 이식과 무관
- **`face_line_audit`의 promote 게이트 승격** — 측정 우선 정책(models.py:1154) 유지.
  이식으로 신호 품질이 개선된 뒤에 재론
- **`note_lines`(254M행 / 52GB)** — `fact_v2`보다 크지만 이번 GC 대상 아님. 별도 백로그

---

## 9. 참고

- `docs/plans/factv2_stdv2_gc_scoping_2026-09-01.md` §2-2·§4-3 — 상위 스코핑(이 문서가 §4-3을 구체화하고 §2-2 위험평가를 정정)
- `docs/plans/gateb_audit_performance_design_2026-08-17.md` §8 — "Phase B 유용성 자체" 미결 제기(당시 근거였던 "커버리지 2.4%"는 §3-1로 낡음)
- `docs/plans/gateb_evidence_grade_redesign_2026-08-17.md` §9 — "①`fact_v2`를 채워 살릴 것인가 ②은퇴시킬 것인가" 양자택일 제기 → **이 문서가 ③"감사 대상을 `report_lines`로 옮긴다"는 3안을 추가**
- `docs/plans/std_v3_native_gate_b_plan_2026-08-11.md` §176, §222 — Phase B를 v3 이식 범위 밖으로 미뤄둔 원 결정
- [[gateb-full-reaudit-is-required-to-close]] — 규칙 변경은 전수재감사까지 해야 종료
- [[feedback-verify-against-source]] — 원문대조·짐작 금지
- [[feedback-long-running-commands]] — 장시간 명령은 사용자 실행
