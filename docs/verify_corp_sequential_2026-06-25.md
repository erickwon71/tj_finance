# 기업별 순차 다운로드 + 보고서↔DB 전기간 검증 — 핸드오프

작성 2026-06-25. 새 세션 시작점. 직전 작업 요약·결과·재현 명령·다음 단계.

## 무엇을 만들었나 (Phase A)

배치(가로) 흐름을 **기업 단위 세로 루프**로 재구성. 활성 보통주를 `corp_code`
오름차순으로 하나씩 돌며, 각 기업의 **전기간(상장 이후 분기/반기/사업보고서 전부)**
에 대해 6단계를 1패스로 실행하고 기업 단위 커밋·재개.

```
for corp (corp_code ASC):
  1) sync-filings   → 공시목록 최신화(+download_tasks 인큐)
  2) download       → 전기간 보고서 다운로드(멱등·재개)
  3) Gate A         → 파일 무결성 + fact_v2 존재 → download_tasks.gate_a_status
  4) fin2 chain     → E→R→S→분기→달력 (run.process_corp)
  5) Gate B         → 보고서 face vs DB(std_v2 40필드, 연결+별도 전 fy) → face_audit
  6) rollup         → corp_verify_status upsert (전기간 pass/fail/pending 요약·재개 마커)
```

실패(보고서≠DB)해도 중단하지 않고 기록 후 다음 기업 계속(사용자 확정). 재개는
`corp_verify_status.stage='audited'` 기업 skip(`--recheck` 로 강제 재검).

### 신규/변경 파일
- **신규** `scripts/verify_corp_sequential.py` — 6단계 오케스트레이터(`--corps`/`--shard`/`--recheck`/`--skip-download`/`--limit`/`--fy-min`).
- **신규** `collector/models.py::CorpVerifyStatus` — 기업별 검증 롤업·재개 마커(테이블 `corp_verify_status`, create_all 자동생성).
- **변경** `run.py` — `cmd_fin2_all` 기업 루프 본문을 `process_corp(session, corp, stages)` 공유 헬퍼로 추출(오케스트레이터와 공유).
- **변경** `scripts/validate_downloads.py` — Gate A `--corp` 필터 추가(기업 단위 스코핑).

## 결과 (전수 완료, 2026-06-25)

| 항목 | 값 |
|---|---|
| 활성 기업 감사 | **2,557 / 2,557 (100%)** |
| PASS (gb_fail_a=0) | **2,557** |
| FAIL (gb_fail_a>0) | **0** |
| ERROR (예외) | **0** |
| Gate B std 행(전 계정·전 기간) | 533,582 |
| → pass / fail / pending | 271,193 / **0** / 3,172 |

- **보고서↔DB 표시단위 불일치 0건**(PRD 00 불변원칙 충족). pending 3,172 = 설계상
  범위밖(비교컬럼·Track B source·미매핑), fail 아님.
- 8-way 샤딩으로 가속: 단일프로세스 ~0.3/min(ETA ~3일) → 8샤드 steady ~7/min(~1h).
  병목은 `process_corp` 재추출(파일 재읽기), Gate B 감사 아님.

### ⚠ 미해결 엣지 — std 0행 4사 (모두 --skip-download 탓 filings 0)
| corp | name | type |
|---|---|---|
| 00435297 | 맥쿼리인프라 | 인프라펀드 |
| 00600013 | 맵스리얼티 | 리츠/부동산 |
| 01880801 | KB발해인프라 | 인프라펀드 |
| 01802928 | 코스모로보틱스 | KOSDAQ(신규/사명변경 추정) |
3사는 펀드/리츠(유니버스 키워드 제외 대상이나 is_active=TRUE). 코스모로보틱스는
실제 다운로드 패스 필요. 해소: `--skip-download` 없이 해당 corp 재실행.

## 재현/운영 명령

```bash
source .venv_tj_finance/bin/activate

# 파일럿
python scripts/verify_corp_sequential.py --corps 0:10 --skip-download

# 전수(이미 받은 파일 재검증, 재추출 포함) — 8-way 샤딩 권장
for a in 0 1 2 3 4 5 6 7; do
  python scripts/verify_corp_sequential.py --shard $a/8 --skip-download > /tmp/verify_s$a.log 2>&1 &
done

# DART 다운로드까지 포함(미수집 기업) — --skip-download 빼고
python scripts/verify_corp_sequential.py --recheck --corps <idx>
```

진행/결과 조회:
```sql
SELECT count(*) done,
       (SELECT count(*) FROM corporations WHERE is_active) total,
       sum((gb_fail_a>0)::int) fail_a, sum((stage='error')::int) err
FROM corp_verify_status;
-- 실패 트리아지: corp_verify_status.fail_periods / face_audit.fail_detail
```

## 진행 경과 (2026-06-25 후속)

### ✅ 엣지 4사 해소
- 펀드/리츠 3사(맥쿼리인프라·맵스리얼티·KB발해인프라) → 이미 `coverage_class='non_periodic'`
  (`scripts/tag_coverage_class.py` 큐레이션). 추가 작업 없음.
- 코스모로보틱스(01802928, 실 KOSDAQ 보통주) → `--skip-download` 없이 재실행, 2026Q1 1건 다운로드
  →추출→Gate B **PASS**(std 4 / GateB pass 2 fail 0).

### ✅ Phase B 구현 완료 — 본문 전 계정 라인 전수 대조(Track A, 측정 우선)
정책(사용자 확정): **Track A 전수·정확대조만**, **측정 우선**(VALUE_DIFF만 차단 후보, MISSING_IN_DB
는 완전성 지표·비차단). promote 뷰는 미변경(규모 측정 후 결정).

신규/변경:
- **신규** `fin2/audit/line_audit.py` — `won_match`(표시단위 ±1 허용) + `reconcile_report_lines`
  (보고서 Track A face 전 라인 ↔ `fact_v2` col0 비차원, `(acode,basis,is_cumulative)` 정확매칭).
  사유 VALUE_DIFF/MISSING_IN_DB/EXTRA_IN_DB. 순수함수.
- **신규** `collector/models.py::FaceLineAudit` — 테이블 `face_line_audit`(rcept 그레인, 롤업+JSONB
  상세). `corp_verify_status` 에 `line_total/line_value_diff/line_missing` 추가. db.py 멱등 ALTER.
- **변경** `scripts/gateb_audit.py::audit_corp` — 같은 `face_cache` 재사용 라인감사(`audit_lines`),
  `--no-line-audit` 토글. 비-Track-A(pending) 보고서는 n_extra/value_diff 미집계(face 부재).
- **변경** `scripts/verify_corp_sequential.py` — ensure_tables/rollup/요약 확장, gb_args.line_audit.
- **신규** `fin2/tests/test_line_audit.py` — 7 테스트 PASS(face_audit 20 무회귀).

**전수 결과(2026-06-26, 8-way 샤딩)**: 122,683 보고서 / **3,334,396 본문 Track A 라인** 대조 →
**value_diff 0 / extra 0 / fail_a 0**(보고서↔DB 표시단위 100% 일치, PRD 04 §1 목표 충족).
missing 2,474 = 서술형 XBRL 개념(InformationAboutMajorCustomers 등 재무 face 아님)으로 감사 reader
과수집 잡음·비차단. gate: pass 14,836 보고서(Track A) / pending 107,847(텍스트·PDF·구 K-GAAP).
※ basis 필터 수정 후 **라인감사 전용 전수 재실행**(`gateb_audit --corp-file 8샤드 --recheck`, 재추출
없음)으로 전 보고서 카운트 일관화 완료 + `corp_verify_status.line_*` 롤업 갱신.

⚠ 1차 전수에서 value_diff 94건이 잡혔으나 **트리아지=전부 false positive**(DB 손상 아님):
전부 `basis=NULL`(미태깅) 셀 — 세그먼트·특수관계자·담보 등 **주석 표가 동일 표준 XBRL 태그
(Revenue·ProfitLoss·Borrowings…) 재사용**, coarse 매칭키 `(acode,basis,is_cumulative)` 가 주석
다중셀에서 충돌(비율 759×·5×·0.09× 제각각=단위오류 아님). Phase A 가 같은 기업 0 fail_a 로 소비값
정확성 이미 입증. **수정**: `line_audit._track_a_face` 가 본문(연결/별도 태깅) 셀만 대조하고
basis=None(주석=PRD 2단계 범위밖)은 제외 → 재감사 value_diff **94→0**. (테스트
`test_basis_none_notes_cells_excluded` 추가, 8 PASS.)

운영(전수, 사용자 실행 — [[feedback-long-running-commands]]):
```bash
# 라인감사 포함 전수(재추출 포함, 8-way 샤딩). face_line_audit 자동 적재.
for a in 0 1 2 3 4 5 6 7; do
  python scripts/verify_corp_sequential.py --shard $a/8 --skip-download --recheck > /tmp/vs_$a.log 2>&1 &
done
# 라인감사만(재추출 없이) 빠르게: python scripts/gateb_audit.py --corps LO:HI --recheck
```
조회: `SELECT sum(n_value_diff) vd, sum(n_missing) miss FROM face_line_audit;`
차단후보 트리아지: `WHERE n_value_diff>0 ORDER BY n_value_diff DESC` → value_diff_detail.

## 다음 단계
1. **Phase B 전수 실행**(사용자) — 8-way 샤딩. value_diff(차단후보) 규모 측정 → 0 이 아니면
   추출버그(PRD03 회부) vs 감사 reader 갭 트리아지. 0 이면 promote 뷰에 line_gate 연결 검토.
2. **(선택) MISSING 잡음 축소** — 감사 reader 가 서술형/text-type XBRL 개념을 face 라인에서 제외
   (수치 개념만). 측정 정밀도 개선용, 비차단이라 우선순위 낮음.
3. (원래 목표) 주가 연동 재무 시각화(Layer 2 calendarization → stock_prices 연동).

관련: [[project-status]] [[prd-role-separation]] [[feedback-long-running-commands]]
