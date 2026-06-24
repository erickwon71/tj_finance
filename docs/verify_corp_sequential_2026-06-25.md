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

## 다음 단계
1. **엣지 4사 해소** — `--skip-download` 없이 재실행(펀드/리츠는 유니버스 정책 확인).
2. **Phase B — 본문 전 계정 라인 전수 비교**(PRD 04 원안): `fin2/audit/face_audit.py`
   `read_report_face_*` 를 std 40필드 매핑이 아니라 보고서 BS/IS/CF **전 라인**을
   DB와 대조하도록 확장. Phase A 전수 통과 후 착수.
3. (원래 목표) 주가 연동 재무 시각화(Layer 2 calendarization → stock_prices 연동).

관련: [[project-status]] [[prd-role-separation]] [[feedback-long-running-commands]]
