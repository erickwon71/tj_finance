# 계층2 재적재 + 원문대조 검토 캠페인 — 진행 트래킹

**상태**: 진행 중(열린 캠페인). 이 문서는 **진행 로그**다 — 설계는
[`layer2_reload_review_campaign_design_2026-09-08.md`](layer2_reload_review_campaign_design_2026-09-08.md).
자동실행 대상이 아니다. 세션마다 이 문서 + `layer2_review.py status` 만 보고 이어서 진행한다.

## 왜 하는가

`report_lines` 6,296만 행은 2026-07 이후 **R28~R84로 파서가 60번 넘게 바뀌는 동안 여러 시점에
적재된 혼합물**이다. 어떤 행이 어느 세대 파서 산출인지 알 수 없다. 현행 파서로 다시 파싱해
적재하고, 그 결과를 **사람이 보고서 원문과 1:1로 대조**한다.

## 확정된 결정 (2026-09-08, 사용자)

| # | 항목 | 결정 |
|---|---|---|
| 1 | 정정본 | **R3 유지** — 계층2는 원본·정정본을 rcept별로 전부 전사, 덮어쓰기 없음. 정정본도 **별개 검토 대상 1건**. (최초 요청 "정정값 overwrite + 태깅"은 사용자가 철회) |
| 2 | 회사 순서 | **시가총액 큰 순** |
| 3 | 회사 내 범위 | **전부** — 분기·반기·사업보고서 + 정정본, 최신 → 과거 |
| 4 | FAIL 시 | **멈추고 원인부터 규명** |
| 5 | 자동검산 | **붙인다** — CSV 상단에 표시 |

## 규모

활성 보통주 2,531사 / 정기보고서 189,485건. 재파싱은 1건 ~0.2초로 싸지만 **사람 검토가
병목**이라(1건 3분이어도 전수 9,500시간) 완주가 아니라 **시총 상위부터 무기한 진행**한다.
진척도는 **검토 완료 기업 수**로 센다.

## 작업 방식 (매 건 반복)

```bash
python scripts/layer2_review.py next
```
→ 재파싱 → `report_lines` 적재 → 자동검산 → CSV 생성. **DART 링크와 CSV 경로**를 출력한다.

CSV(`layer2_review/<시장>/<corp_code>_<회사명>/<report_type>/<연도>/<rcept_no>_review.csv`)를
열어 DART 원문과 대조한다. 순서는 **별도 BS → IS → CF → 연결 BS → IS → CF**, 금액은
**원문에 인쇄된 그대로**(단위 적용 후), 행 순서는 원문 순서 그대로다.

```bash
python scripts/layer2_review.py pass
```
```bash
python scripts/layer2_review.py fail --note "무엇이 어떻게 틀렸는지"
```

`fail` 이면 **루프가 멈추고** 트리아지 진입점(`verify_report_lines` /
`layer2_fidelity_roundtrip` / `layer2_forward_cells` / `audit_unit_declarations`, 전부
`--rcept` 지원)을 출력한다. 파서를 고친 뒤:

```bash
python scripts/layer2_review.py redo
```

한 회사를 다 본 뒤 — **런북 B5 필수**(안 하면 `dq_assertions::calendar_orphan_cq` 유령행):

```bash
python scripts/layer2_review.py finish-corp
```

**상태값**: `pending` / `reloaded`(적재+CSV 완료, 사람 검토 대기) / `pass` / `fail` /
`blocked`(재적재 불가 — 원문 부재·manual 보호) / `skipped`

## 자동검산 8종

차단 등급(`check_status=suspect` 를 만든다): `bs_balance` · `cf_closing_cash` ·
`scope_presence` · `unit_sanity`
의심: `row_count_outlier` · `duplicate_rows` / 참고: `bs_rollup` · `is_waterfall`

**검산은 표시만 한다 — 진행을 막지 않는다.** 최종 판정은 사람의 원문 대조다(R9).
표본 250건 실측(2026-09-09): `suspect` 14%, `bs_balance` FAIL 0.2%,
`cf_closing_cash` FAIL 6.4%.

## 진행 로그

- **2026-09-09 도구 구축 완료.** `scripts/layer2_review.py`(CLI) ·
  `fin2/audit/layer2_selfcheck.py`(검산 8종) · `fin2/extract/review_csv.py`(CSV) ·
  `collector/models.py::Layer2ReviewQueue`(큐). 회귀 테스트 37건 신규
  (`fin2/tests/test_layer2_selfcheck.py` 21 · `test_review_csv.py` 16).
  스모크 검증: 삼성전자 2026H1(523행, 검산 8종 전부 PASS) 및 2026Q1(495행) 재적재,
  `redo` 2회 멱등(행수·CSV 바이트 동일), YBM넷 `20020814000872` 는 manual 보호가드로
  `blocked`(manual 161행 보존 확인).
  큐 초기화: 시총 상위 20사 + YBM넷 = **2,115건 pending**.
- **2026-09-09 검산 민감도 튜닝** — 표본 스윕에서 나온 **거짓양성 4종을 잡아 회귀로 고정**:
  ① IS 단위 혼재(본문 백만원 + EPS 원)를 결함으로 오인 → 단위 혼재는 R4상 정상이므로
     검산에서 제거. ② 라벨+값 중복 판정에 `section_path` 누락(유동/비유동에 같은 값이
     인쇄되면 걸림, 표본의 21%) → 키에 위치 추가. ③ 형제 보고서 모집단이 전 연도라
     2005년 K-GAAP을 2020년대 IFRS와 비교 → ±3년 창으로 제한(scope_presence FAIL 24→4).
     ④ CF 항등식을 성분합으로 세워 연결범위변동·환율효과 조정행을 놓침 → **기말−기초 =
     순증감 소계** 로 재설계 + 소계 뒤 환율효과 가산 + '~로 인한/~에 따른' 조정행 배제.
- **2026-09-09 부수 발견(별건, 기록만)** — `report_tables.declared_unit` 이 표의 첫 행
  adecimal 로 유도돼 **IS 백만원 표가 `declared_unit=1`(원)** 로 적힌다(EPS 행이 먼저
  방출되기 때문). 읽는 프로덕션 소비자가 없어 실피해 0. `docs/PARSING_RULES.md` 부록 C에
  기록. 이 캠페인의 CSV·검산은 이 컬럼 대신 **행의 `adecimal`** 을 쓴다.

## 다음 세션에서

1. `python scripts/layer2_review.py status` 로 현재 지점 확인.
2. `python scripts/layer2_review.py next` 로 이어서 진행.
3. 큐를 넓히려면 `python scripts/layer2_review.py init --top <N>`
   (사람 판단 컬럼은 덮어쓰지 않는다 — 멱등).
