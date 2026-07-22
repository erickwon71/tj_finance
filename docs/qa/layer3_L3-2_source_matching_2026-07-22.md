# L3-2 출처매칭 (MISSING ~9%) — 특성화 + basis 폴백 (2026-07-22)

> 계획 = `docs/plans/layer3_rebuild_plan_2026-07-22.md`(L3-2) · 선행 = `layer3_L3-1b_...md`
> 코드 = `fin2/layer3/combine.py`(basis 폴백) · **읽기전용 측정 + 폴백 1종 구현.**

## 0. 한 줄
델타패치 병합 후 남은 MISSING 을 특성화: **NO_LINES(자체연도 보고서 미추출→std가 이웃해
비교열에서 취득)** 가 지배 + **OTHER_BASIS(단일 basis 기업)**. basis 폴백 구현으로 MATCH
~90→91.5%. NO_LINES 는 결정 사안(비교열 백필 vs Layer-2 완성).

## 1. MISSING 분류 (n=400, per-metric)
| 유형 | 건수 | 정체 |
|---|---:|---|
| NO_LINES | 171 | build_merged 빈값 — 그 (corp,fy)의 자체 보고서가 report_lines 부재 |
| OTHER_BASIS | 45 | 반대 basis 엔 있음(단일 basis 기업) |
| VALUE_ABSENT | 2 | std 값이 report_lines 어디에도 없음 |
| LABEL_UNMAPPED | 1 | 값은 있는데 라벨 미매핑 |

## 2. NO_LINES 규명 — std 는 "이웃해 비교열"에서 채웠다
갭 기간의 std bs_rcept 2,115/2,778 이 report_lines 에 rcept 로는 존재하나, 그 rcept 의
`report_fiscal_year` 가 std 의 `fiscal_year` 와 다르다:
```
std_fy − report_lines_fy = -1 : 1067   (다음해 보고서의 전기열 col_index=1)
std_fy − report_lines_fy = -2 : 1048   (2년후 보고서의 전전기열 col_index=2)
```
즉 그 해 **자체 보고서가 report_lines 에 미추출**(Track B xml 594·PDF 등 — Layer-2 1차 패스가
std_v2 유니버스를 전부 못 덮음, 전체 (corp,fy) 의 7.1%=1,741 기간). std_v2 는 이웃해 보고서의
비교열(col_index 1/2)로 그 해를 채웠다. combine 은 col_index=0(당기)만 읽어 MISSING.

### 해소 경로 (★결정 필요 — 정본/재작성 정책과 얽힘)
- **(a) Layer-2 완성**: 빠진 자체연도 보고서를 report_lines 로 추출. **당기열(col_index=0)이
  권위값** → 가장 깨끗. 볼륨: ~594 Track B + PDF 다수. 별도 백필 패스.
- **(b) L3-2 비교열 백필**: 이웃 보고서 col_index=1/2 에서 그 해를 채움. std_v2 재현 쉬우나,
  **그 비교열은 이미 재작성됐을 수 있다**(다음해 보고서가 전기를 소급수정) → 델타패치 정본
  정책(원본 우선)과 충돌. 값의 "시점" 의미가 흐려짐.
- 권고: **(a) 우선**(당기열 권위). (b)는 (a)로도 못 채우는 잔여에 한해 폴백, 채운 값에
  "비교열 출처" 표시. 정본 정책과의 정합은 L3-3 빌드에서 확정.

## 3. 구현: basis 폴백 (OTHER_BASIS 45 해소)
단일 basis 기업(종속회사 없음 → 별도만 공시, 연결=별도)에서 요청 basis 가 report_lines 에
전무하고 반대 basis 만 있으면 폴백. 실측: 45/45 전부 단일 basis, 반대 basis 값 = std 정확일치.
구 체인(비연결기업 연결→별도)과 동일. `combine` 에 구현.

## 4. 측정 결과 (n=400, seed 7)
| 단계 | MATCH% | MISSING | CONFLICT | DIFF |
|---|---:|---:|---:|---:|
| L3-1b 델타패치 | ~90.0 | 37 | ~0 | 1~4 |
| **+ basis 폴백(L3-2)** | **~91.5** | **29** | ~0 | 1~6 |

MISSING 37→29(basis 폴백 8 회복). 남은 29(~7%) = 대부분 NO_LINES(§2, 자체연도 미추출).
DIFF 소폭↑(basis 폴백 회복분 일부가 std 와 다름 — L3-4 parity 에서 분류).

## 5. 판정 & 다음
- ✅ basis 폴백 = 깔끔한 조합 승리(단일 basis 기업). 구현·검증 완료.
- ⚠ NO_LINES(7.1% 기간) = **Layer-2 커버리지 갭**이 근본. 조합 로직만으론 못 채움 →
  자체연도 보고서 백필(a) 필요. §2 결정을 L3-3 빌드 전에 확정.
- **다음 = L3-3 std_v3 테이블 빌드** — 6지표(또는 확장)로 2015+ 전량 빌드, applied_rules 에
  amend_chain·basis_fallback·비교열출처 provenance 기록. 그 전에 §2(a/b) 결정.
