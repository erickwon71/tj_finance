# 재다운로드 완료 후 재개 런북 (fin2)

> 작성 2026-05-31. raw_report(OneDrive) 파일 전체 소실 → 재다운로드 진행 중.
> **전체 download 완료 후 이 문서대로 이어서 진행**한다. 마스터 계획: `docs/fin2_rebuild_plan_2026-05-31.md`, 상태 메모리: `project-status`.

## 사고 요약 / 현재 상태
- `raw_report` 가 OneDrive 심볼릭 링크였는데 내용이 **전부 삭제**됨(현재 빈 로컬 폴더).
- DB `download_tasks` 는 188,911건을 `completed` 로 기억 → `reset-missing` 으로 소실 건을 `pending` 리셋 후 재다운로드 중.
- **fin2 DB 데이터(fact_v2/statement_source/std_financials_v2)는 살아 있음** — 약 **1,052사**까지 E→R→S 완주 적재됨(2026-05-31 기준). 파일만 사라졌고 DB 적재분은 보존. 재다운로드는 디스크 파일만 복원하며 fin2 적재분은 그대로다.
- ⚠ 저장위치: 내장 디스크 여유가 빠듯했음. **OneDrive 동기화 폴더는 다시 쓰지 말 것**(사고 재발). 외장 디스크 일반 폴더 심볼릭 링크 또는 `.env` 경로 변경 권장. 전체 코퍼스 ≈ 50~80GB 추정.

---

## 0) 재다운로드가 정말 끝났는지 확인
```bash
cd /Users/taejin/Project/tj_finance
source .venv_tj_finance/bin/activate

# pending/failed 가 0 에 수렴했는지
psql -d tj_finance -tAc "SELECT status, count(*) FROM download_tasks GROUP BY status ORDER BY 2 DESC;"
# 디스크 실제 파일 수(수십만 기대)
find raw_report -type f | wc -l
```
- `pending` 이 남아 있으면 → DART 일일 쿼터(020)로 중단된 것. 다음 날 `python run.py download` 재실행(자연 재개).
- `failed` 소수는 정상(013 문서없음 등). `skipped` 도 정상(구형 미지원 포맷).

---

## 1) fin2 전수 적재 재개 (E→R→S)
이미 끝난 ~1,052사는 건너뛰고 나머지만 처리한다.
```bash
# 청크 분할(병렬 가능). --skip-done = std_v2 에 이미 있는 기업 제외
python run.py fin2-all --corps 0:500     --skip-done 2>&1 | tee -a /tmp/fin2_0.log
python run.py fin2-all --corps 500:1000  --skip-done 2>&1 | tee -a /tmp/fin2_1.log
python run.py fin2-all --corps 1000:1500 --skip-done 2>&1 | tee -a /tmp/fin2_2.log
python run.py fin2-all --corps 1500:2000 --skip-done 2>&1 | tee -a /tmp/fin2_3.log
python run.py fin2-all --corps 2000:2553 --skip-done 2>&1 | tee -a /tmp/fin2_4.log
```
- **중단·재개 안전**: 기업 단위 커밋 + upsert(idempotent). 죽어도 같은 명령 재실행하면 이어짐.
- ⚠ 파일이 다시 OneDrive 온디맨드면 `read()` 가 멈출 수 있음 → 반드시 로컬/외장 실파일로 둘 것.

## 2) 전수 적용 확인
```bash
python scripts/fin2_coverage.py --show 30
```
기대값:
- `std_financials_v2 적재 기업` → **2,553 에 근접**
- `fact_v2 있으나 std_v2 없음` → **0**(아니면 해당 기업 reconcile2/standardize2 재실행)
- `fact_v2 없음(추출 0행)` 중 `★레거시는 성공(진짜 갭)` → 남으면 그 기업 파일포맷/파서 조사 대상

## 3) parity 게이트 (현 파이프라인 무회귀 검증)
```bash
python -m fin2.tests.parity diff fin2/tests/parity_baseline.json \
  --live --table std_financials_v2 --tol 0.005 --out /tmp/parity_v2.json
```
- `compared keys` 가 baseline(289,341) 에 근접해야 전수 비교가 된 것.
- `null_flip`(값 손실) 우선 조사, `changed` 검토. `data_quality` 변동은 리메드류 DQ 개선(의도)일 수 있음.

---

## 4) 그 다음 = fin2 잔여 작업 (우선순위)
1. **Phase 4 잔여 — parity 발산 정밀화**: 6사 시범에서 CF파생 집중 발산 확인됨
   (ebitda/da_total/cfi/depreciation/cff/fcf/capex/amortization).
   - 원인 후보 ①**주석 D&A 귀속 갭**: legacy 는 `note_extractor` 로 CF주석 D&A 추출,
     fin2 는 `note.*` 를 statement_source 에 안 묶음 → `fin2/standardize/rules.py`·`build.py` 에
     note D&A 보강 규칙 추가 검토.  ②cfi/cff source 선택/분기 누적컬럼.
   - 전수 parity 결과(/tmp/parity_v2.json)의 `by_column`·`cases` 로 우선순위 잡기.
2. **Phase 5 — 호환 view**: `standard_financials` 를 `std_financials_v2` 위 view(version=1 상수)로
   무중단 전환. analyze/screen/dcf/dividend/validate 무변경. 롤백 = view drop + rename.
3. **`fin2/extract/pdf.py`** — PDF-only 폴백(A→B→PDF 3단). 낮은 우선순위.

## 참고 — fin2 CLI 요약
| 명령 | 용도 |
|---|---|
| `extract2 --corp C [--year Y] [--dry-run]` | 단일기업 E(추출) |
| `reconcile2 --corp C [--year Y]` | 단일기업 R(source 선택) |
| `standardize2 --corp C [--year Y]` | 단일기업 S(표준화) |
| `fin2-all [--corps S:E] [--limit N] [--stage] [--skip-done]` | 전수 E→R→S |
| `reset-missing [--corp C] [--dry-run]` | 소실 파일 completed→pending 복구 |
| `scripts/fin2_coverage.py [--show N]` | 전수 적재 커버리지 점검 |
| `python -m fin2.tests.parity diff <baseline> --live --table std_financials_v2` | 무회귀 검증 |

## 테스트(언제든)
```bash
for t in test_acontext test_concept_map test_xbrl test_text test_reconcile test_rules; do
  python -m fin2.tests.$t; done   # 현재 37 통과
```
