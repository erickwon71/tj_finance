# 계층3 옵션 A 검증 프로브 — "2015+ 가 지표 레벨에서 표준화됐는가" (2026-07-22)

> 핸드오프 = `docs/qa/handoff_layer2_complete_2026-07-22.md` · 설계 = `docs/plans/layer3_design_2026-07-22.md`
> 프로브 = `scripts/layer3_label_norm_probe.py`(본체) · `scripts/layer3_probe_missing_drill.py`(MISSING 특성)
> **성격: 읽기전용 검증. DB 무변경. 계층3 를 만든 게 아니라 "만들 수 있는가"를 측정.**

## 0. 목적
사용자 우려("2015+ 가 그나마 표준화된 구간인데 여기서 애매하면 pre-2015 에서 악화")에 답하기
위해, **기존 라벨 카탈로그**(`account_maps/` + `parser.common.account_mapper`)를 **계층2
`report_lines.label_raw`** 에 그대로 걸어서 **std_financials_v2 를 재현하는지**를 지표 레벨로 측정.

## 1. 방법
1. std_v2 (2015+, FY, version=1, not stub/discrete)에서 무작위 표본 추출.
2. 각 (corp, fy, period, basis)에 대해 report_lines 의 당기열(col_index=0) IS/BS 행을
   `AccountMapper.map(label_raw, fs_section)` 로 canonical 변환.
3. 핵심 6지표를 뽑아 std_v2 값과 **정확 일치(원 단위)** 비교.
   - MISSING=프로브 무값 · UNIQUE→MATCH/DIFF · CONFLICT=서로 다른 후보 다수.

## 2. 결과 (n=400, seed=7 / n=150 seed=42 재현)

| 지표 | N | MATCH | DIFF | CONFLICT | MISSING | match% |
|---|---:|---:|---:|---:|---:|---:|
| is.revenue | 392 | 339 | 0 | 18 | 35 | 86.5 |
| is.operating_income | 399 | 353 | 0 | 9 | 37 | 88.5 |
| is.net_income | 398 | 344 | **1** | 16 | 37 | 86.4 |
| bs.total_assets | 399 | 352 | 0 | 10 | 37 | 88.2 |
| bs.total_equity | 399 | 350 | 0 | 12 | 37 | 87.7 |
| bs.retained_earnings | 394 | 325 | 0 | 33 | 36 | 82.5 |

매핑 단계 분포: exact 61.8% · unknown 13.5% · fuzzy 12.6% · normalized 11.0% · guard 1.2%.

## 3. 핵심 결론

**① 라벨 카탈로그는 계층2 로 깨끗이 이식된다 — DIFF ≈ 0 (400건 중 1).**
유니크하게 값이 뽑히면 **std_v2 와 원 단위까지 정확 일치**. 즉 값을 틀리게 만드는 라벨
오매핑은 사실상 없다. 기존 카탈로그는 새 체인에서도 유효.

**② MISSING(~9%)은 카탈로그 결함이 아니라 출처/커버리지 문제.**
`total_assets` MISSING 드릴 결과: NO_BS_ROWS 31 / HAS_ROWS_NOMAP **0**. BS 행이 있으면
**369/369 전부 매핑**. 없는 이유는 그 (corp,fy,period,basis) 키에 report_lines 행이 애초에
없어서 — std_v2 가 다른 리포트/열(예: 다음해 보고서의 전기열)이나 다른 basis 에서 값을
가져온 케이스. → **계층3 출처우선순위 엔진이 다룰 영역**(라벨 문제 아님).

**③ CONFLICT(1~8%)가 계층3 의 실제 작업.** 한 canonical 에 서로 다른 값 다수 —
retained_earnings 가 최악(8%, 이익잉여금/미처분이익잉여금/처분전 변이). 소계 이중계상·2표식
IS·금융업 이중섹션 등. 설계가 이미 예정한 **node_role(P/S) + 출처우선순위 선택**으로 해소.

**④ fuzzy 의존 12.6%** — 값은 안 틀리지만(DIFF≈0) 계층3 확정 시 exact 승급 여지.

## 4. 판정 — 사용자 우려에 대한 답
**2015+ 표준화 가정은 지표 레벨에서 성립한다.** 남은 격차는 (a)잘못된 값이 아니라 (b)출처
선택·충돌해소라는 **계층3 본연의 조합 로직**이다. 라벨 정규화를 맨땅에서 만들 필요 없음 —
기존 카탈로그가 건재. → **옵션 A 진행 근거 확보.** layer3_design §4 로 되돌아갈 트리거(표준화
가정 붕괴)는 발생하지 않았다.

## 5. 다음 (재계획 입력)
- CONFLICT 해소 규칙(node_role P/S + 출처우선순위)을 소수 지표로 end-to-end 프로토타입.
- MISSING 의 출처매칭(어느 리포트/열/basis 에서 채울지) 규칙 — std_v2 lineage(bs/is/cf_rcept) 참고.
- 표본을 분기(H1/Q1/Q3)·비FY 로 확장해 재현성 확인.
- venv 경로: `.venv_tj_finance` → `.venv` 로 통일 완료(2026-07-22, mv 후 내부 shebang 44개 교정 + 문서/plist 참조 일괄 갱신). archive 문서만 이력상 옛 경로 유지.
