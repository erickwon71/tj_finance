# Phase B — 재구축(Track 1) 대상 인벤토리 (2026-07-18)

> 재구축 계획 = `docs/plans/vast-nibbling-blum.md` §4 Phase B
> 산출 스크립트 = `scripts/phase_b_build_targets.py` (재현가능)
> 결과 테이블 = `rebuild_target_track1` (Phase C 가 읽어 진행추적)

---

## 결론 — 재파싱 대상

| | 값 |
|---|---|
| **대상 보고서(rcept)** | **79,010** |
| **대상 기업(corp)** | **2,452** |
| 파일 실재(표본 200) | 결측 0 |

**대상 기준**(사용자 확정):
- **2015+** 만(Track 1). 구형(2000~2014)은 Track 3 별도.
- **Track B(xml_text)** 만. Track A(xbrl_acode) 16,384 은 범위 밖(§5-1).
- **최초 보고서만**. `report_nm NOT LIKE '%정정%'` (정정본 24,145 제외).
- 본문없음은 **여기서 거르지 않음** — 파싱시점 판정이라 Phase C 가 빈 결과→보류로 처리.

---

## 실측으로 확정된 사실

### 1. Track A/B 는 report 단위로 **깨끗이 분리**
```
pure_A 16,384 · pure_B 86,699 · mixed 0   (2015+ report_fiscal_year 기준)
```
한 보고서가 두 Track 을 섞지 않는다 → `NOT EXISTS(xbrl_acode fact)` 로 Track B 판정이 견고.

### 2. 2015+ 에는 **정정본만 있는 기간이 0건**
```
(corp,fy,period) 93,532개 전부 원본 보유. amend_only = 0.
```
계획서의 "정정본만 108개 기간"은 **pre-2015(Track 3)** 였다. Track 1 은 정정본 제외가 단순
(원본이 항상 있으므로 `NOT LIKE '%정정%'` 만으로 충분, 별도 재편입 리스트 불요).

### 3. 정정 스코핑 등가 확인
`report_nm LIKE '%정정%'`(24,145) == `is_amendment`(23,000) + `is_attachment_amendment`(1,145).
현 DB 는 `is_attachment_amendment` 컬럼이 생겨 구 함정([첨부정정] 누락)이 해소됐으나,
**report_nm 기준을 유지**(가장 견고, 플래그 누락에 무관).

### 4. 79,010 이 86,699(xml_text)보다 작은 이유
86,699 = **정정본 포함** xml_text 보유 report. 79,010 = 그중 **정정본 제외**.
차이 ≈ 7,689 은 xml_text 를 가진 정정 보고서(대상에서 제외됨, Track 2 에서 재검토).

---

## 분포

| 기간 | 보고서 | | 시장 | 보고서 |
|---|---|---|---|---|
| Q3 | 20,245 | | KOSDAQ(K) | 49,797 |
| H1 | 20,120 | | KOSPI(Y) | 29,213 |
| Q1 | 19,889 | | | |
| FY | 18,756 | | | |

**연도별**: 2015~2023 각 6,500~9,300. **2024 급감(7,296→2025 337·2026 69)** = DART iXBRL
전환으로 최근 보고서가 Track A(xbrl_acode)라 Track B 대상에서 빠짐(cf_da.py 의 '2024+ Track A
전환' 주석과 정합). → **최근 연도 재무는 Track A 재구축(별도)이 필요**(§5-1 재확인).

---

## `rebuild_target_track1` 스키마

| 컬럼 | 용도 |
|---|---|
| `rcept_no` (PK) | 재파싱 단위(파일 1개) |
| `corp_code`·`corp_cls`·`fiscal_year`·`fiscal_period` | 표준화·샤딩 메타 |
| `file_path` | 파싱 대상 raw_report 경로 |
| `status` | 진행추적(pending → done/held/no_body). Phase C 가 갱신 |
| `processed_at` | 처리 시각 |

재생성: `python scripts/phase_b_build_targets.py` · 요약만: `--summary`

---

## Phase C 로 넘어갈 때 유의 (규모·순서)

- **규모**: 79,010 보고서 재파싱. 실측 파싱속도(~150파일/분)면 **순수 파싱 ~9시간** + 표준화.
  → **샤딩 + 기업단위 원자커밋**(`verify_corp_sequential.py` 루프 패턴 재사용). 야간자동화가
  필요하나 **현재 gapfill·collect 잡은 중지 상태**([[nightly-jobs-paused-phase-a3]]).
- **shares_out 재백필 필수**: C17 로 재구축 시 std_v2.shares_out 은 NULL 로 시작 →
  직후 `shares.py` 재백필 안 하면 valuation_daily(PER/PBR/시총) 전부 NULL.
- **소비자 교체(swap)**: 앱·valuation·스크리너가 std_v2 를 읽으므로, 신규 구축 후 검증→교체.
- **provenance 인덱스**: 재구축 후 `fact_v2` provenance 4컬럼 + `value_lineage` 에 인덱스 추가
  (지금은 전 행 NULL 이라 미생성). Phase D 어서션 성능용.

## 미결(Track 1 범위 밖, 기록)
- **Track A 16,384 재구축** — 최근 연도(2024+) 재무가 여기 몰려 있어 영향 큼. 3S/네오크레마형
  단위오기가 Track A 에도 있을 수 있음(§5-1). 별도 트랙.
- **정정본 7,689(xml_text 보유)** — Track 2 에서 재편입.
- 본문없음 리스트 — Phase C 파싱시점 산출.
