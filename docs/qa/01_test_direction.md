# TJ Finance 시각화 앱 — 감리(QA) 테스트 방향서

> 감리 담당(Auditor) 확정본. 실제 테스트는 테스트 담당자(Sonnet)가 `02_checklist.md`로 수행한다.
> 기준 스펙: **`docs/user_manual_app.md`(2026-07-06)** — 이 문서가 유일한 기대동작의 근거다.

---

## 0. 목적
신규 재무·주가 시각화/스크리너 Streamlit 앱(8페이지·9탭·50종 지표)의 출시 품질을 담보한다.
현재 앱을 실제 구동해 화면을 검증하는 테스트가 전무하므로(기존 `tests/`는 데이터·계산 계층 단위테스트뿐), 매뉴얼을 스펙으로 한 블랙박스 감리 체계를 수립한다.

## 1. 감리 원칙
- **블랙박스**: 기대동작의 근거는 앱 소스가 아니라 `docs/user_manual_app.md`. 매뉴얼과 실제 화면이 다르면 결함(앱 버그 또는 매뉴얼 오류)으로 보고한다.
- **화면 직접 검증**: 렌더된 페이지를 실제로 확인(헤드리스 Chromium 스크린샷/DOM)해 결과를 판정한다. 로그·DB만으로 판정하지 않는다.
- **전수 + 심층 2계층**: 데이터 표시는 전 기업(2,554사) 전수, 기능 인터랙션은 엣지케이스 층화표본.
- **재현 가능한 결함 보고**: 개발자가 그대로 재현하도록 기업코드·페이지·토글상태·단계·기대/실제·스크린샷을 포함한다.

## 2. 확정된 감리 결정사항 (사용자 확인 완료)
1. **전수검증 방식** = 자동 스윕 + 이상건만 스크린샷. 단, **기업 시각화 화면은 연간·분기·별도·연결 4조합 모두 × 전 대상기업**을 확인하고, **값 표시 자체의 문제(특히 시계열 중간이 비는 mid-series gap)** 를 집중 점검한다.
2. **값 정확성** = **UI 표시값 ↔ DB값 기간별 자동대조**(앱이 DB를 올바르게 표시/단위환산하는지).
3. **기능 심층 테스트 표본** = 엣지케이스 층화표본(§7).

## 3. 테스트 환경 & 사전조건
| 항목 | 값 |
|---|---|
| 실행 | 프로젝트 루트에서 `.venv_tj_finance/bin/streamlit run app/main.py` |
| URL | `http://localhost:8501` (기본 8501) |
| 페이지 딥링크 | `url_path`로 이동: `/company`(기본) `/screener` `/quarter-change` `/valuation` `/compare` `/chart-builder` `/collect` `/help`. **기업 선택은 URL 불가** — 사이드바 검색창에 코드/명 입력 |
| 사전조건 | PostgreSQL 기동 + `.env`의 `DATABASE_URL`이 적재된 DB를 가리킴. 사이드바 "DB 상태" expander가 **"DB 연결 OK"** 인지 먼저 확인 |
| 자동화 | venv에 **Playwright 1.60 + Chromium 사전설치**. 구동/캡처 스크립트는 미존재 → 담당자가 `scripts/qa/`에 신규 작성 |
| DB 조회 | 앱: `from collector.db import get_session`. 스크립트: psycopg2 DSN `dbname=tj_finance user=taejin` |

**착안점(리스크)**: Playwright는 사이드바 텍스트 입력→자동선택 대기→탭 라디오 클릭 순으로 구동해야 하고, 기업 선택이 세션상태 기반이라 병렬 워커는 세션 격리(별도 브라우저 컨텍스트)가 필요하다.

## 4. 대상 유니버스 & 기간 산정 (전수검증 기준선)
- **활성 대상기업 = 2,554사** (`corporations` where `is_active=TRUE AND COALESCE(coverage_class,'periodic')<>'non_periodic'`).
- 회사별 시작연도/최신연도 산정은 `scripts/check_period_completeness.py`(`fetch_corps`, `fetch_corp_first_period`) 재사용 또는 아래 SQL로 기준선 테이블 생성:

```sql
SELECT c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month,
       MIN(s.fiscal_year) AS earliest_fy, MAX(s.fiscal_year) AS latest_fy
FROM corporations c
JOIN std_financials_v2 s ON s.corp_code = c.corp_code
WHERE c.is_active = TRUE AND COALESCE(c.coverage_class,'periodic') <> 'non_periodic'
GROUP BY c.corp_code, c.corp_name, c.stock_code, c.market, c.fiscal_month
ORDER BY c.market, c.corp_name;
```
- **비-12월 결산 주의**: `fiscal_month`≠12 기업은 FY 연도와 달력분기(CQ) 매핑이 달라 mid-gap 오탐 위험이 크다 → "시작연도" 판정 시 `fiscal_month` 동반 해석(매뉴얼 부록 D·주1), 별도 검증 규칙 적용.

## 5. Tier 1 — 전 기업 데이터 표시 무결성 스윕 (전수 2,554사)
**목표**: 매뉴얼 §3(기업 시각화)의 데이터 표시가 전 기업에서 정확·완전한지. **판정은 자동, 스크린샷은 이상건 + 무작위 감사표본(≈2%, 50사)만.**

**실행 매트릭스**: 각 기업 × **{연간, 분기} × {연결, 별도} = 4조합** × 9개 탭. 연결/별도 대체가 일어나면 주2 캡션과 함께 대체본으로 판정.

자동 판정 항목(DS-1~8)과 산출물은 `02_checklist.md` §A에 정의한다.

## 6. Tier 2 — 전기능 인터랙션 체크리스트 (엣지케이스 표본)
매뉴얼의 모든 페이지·위젯을 항목화(`02_checklist.md` §B). 표본 기업(§7)에서 실행하고 `results/checklist_run.csv`에 PASS/FAIL/N/A + 스크린샷 경로 기록.

## 7. 엣지케이스 층화표본 정의 (20~30사)
각 축에서 최소 2사씩 선정(SQL 추출 → `results/sample_set.csv`):
- 결산월: 12월 / 비-12월(주1) · 시장: KOSPI / KOSDAQ · 규모: 시총 대형 / 소형(최소).
- 재무기준: 연결 존재 / **별도만 존재(주2 대체 발생)**.
- 이력: 관리·상폐·매매정지(주3) / 기재정정(DB반영·원본유지 둘 다) / 신규상장(짧은 이력).
- 데이터 특성: 보유기간 최장/최단, 무배당/배당, 생산·수주 있음/없음, 자본이벤트(증자·CB) 있음, 시총 없음(대가지표 제한).
- **삼성전자·SK 등 2026 Q1 합성/시드 구간 보유 기업** 포함(정상값 확인 대상, phantom 아님).

## 8. 실행 안전 규칙 (부작용 조작)
- 스윕/체크리스트의 **읽기 조작**은 자유 실행.
- **보고서 수집(COL-2/3)**, 관심종목/스크린/프리셋 **저장** 등 **쓰기·외부호출**은 운영 DB에 영향 → (a) 가급적 별도/복제 DB, (b) 최소 1회 기능검증만, (c) 파괴적/대량 수집은 **사용자 승인 후** 실행. 무단 대량 DART 호출 금지.

## 9. 산출물 & 파일 배치
```
docs/qa/
  01_test_direction.md      # 본 방향서
  02_checklist.md           # 전기능 체크리스트(담당자 실행본)
  03_defect_template.md     # 결함 보고 템플릿
  90_audit_report.md        # (최종) 감리보고서 — 감리 담당 작성
  results/                  # 담당자 산출: sweep/gap/diff CSV, shots/, checklist_run.csv, defects/, sample_set.csv
scripts/qa/
  sweep_company_pages.py    # Playwright 전수 스윕 + UI↔DB 대조(담당자 신규작성)
  build_expected_coverage.py# §4 SQL로 기대 보유구간 기준선 생성
```

## 10. 역할 분담 & 흐름
1. **감리(Auditor)**: 방향서·체크리스트·결함템플릿 확정(`01~03`) → 담당자 브리핑. ← 현재 완료
2. **테스트 담당(Sonnet)**: 환경 기동 → `scripts/qa/*` 작성/실행 → Tier1 전수 스윕 + Tier2 표본 체크리스트 → `results/` 채움 + 결함 등록.
3. **감리(Auditor)**: 결과 검수·재현 스팟체크 → **감리보고서(`90_audit_report.md`)** 작성.

## 11. 감리보고서(최종 산출) 목차
1. 감리 개요(범위·방법·기준=매뉴얼·기간)
2. 커버리지 요약(전수 2,554사×4조합 진행률, 표본 기능 커버율, 미검증 항목)
3. 결함 집계(심각도·페이지·유형별)
4. 중대결함 상세(재현·증거·영향)
5. **mid-gap/값불일치 분석**(앱버그 vs 데이터결함 구분, 대표사례)
6. 매뉴얼↔구현 불일치 목록
7. 위험도 평가·출시 판정(Go/조건부/No-Go)
8. 조치 권고(우선순위)·재검증 범위

## 12. 감리 산출물 자체 검증
- **체크리스트 완전성**: 매뉴얼 §2~10 + 부록 A~D의 모든 위젯/버튼/토글/다운로드/각주가 체크리스트 ID로 1:1 매핑됐는지 역추적표(`02_checklist.md` §D)로 확인(누락 0).
- **전수 스윕 재현 스팟체크**: `results/sweep_all_companies.csv`에서 무작위 10사를 감리가 직접 앱에서 재현(4조합)해 판정 일치 확인.
- **결함 재현성**: 등록된 S1/S2 결함을 재현 단계대로 재현 가능한지 검증(재현 불가 결함은 반려).
- **값대조 정확성**: `results/value_diffs.csv` 표본을 DB 원값·단위환산 규칙으로 수기 검산.
