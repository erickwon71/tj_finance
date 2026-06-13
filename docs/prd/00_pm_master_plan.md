# PRD 00 — PM Master Plan (전체 총괄)

> 작성 2026-06-13. 본 문서는 TJ Finance 재무데이터 파이프라인을 **4개 전문가 역할 + PM** 으로
> 분리하고, 두 개의 차단 게이트로 운영하기 위한 총괄 문서다. 개별 전문가 PRD 는 `01~04` 참조.
> 마스터 계획: `~/.claude/plans/merry-conjuring-lark.md`. 진행 상태 메모리: `project-status`.

## 0. 최우선 원칙 (변경 불가)

> **DB 에 적재된 재무 금액은 원본 보고서와 100% 동일해야 한다.**
> 이는 데이터가 투자판단 backdata 로 쓰이기 때문이다. 일치하지 않으면 그 데이터는 다음 단계로
> 넘어갈 수 없다(차단 게이트). 추정·보간으로 빈칸을 채우지 않는다 — 모르면 비워두고 보고한다.

## 1. 배경 / 현 상태

- fin2 재구축 완료: `std_financials_v2`(view=`standard_financials`) = 1997~2025·2,553사 단일 진실원.
- 금액 단위는 이미 **원(KRW) 단일 단위**로 통일(XBRL `ADECIMAL` 권위, `fact_v2.amount_won`).
- **구조적 공백**(이 과제가 메움):
  1. **보고서-vs-DB 검증 부재** — 기존 검증은 전부 DB-vs-DB(parity) 또는 DB 내부 회계항등식. 원본을 다시 읽어 대조하는 게이트가 없음.
  2. **분기 환산 부재** — 누적값을 `is_cumulative` 로 저장만 함. Q2/Q4 이산값 미생성.
  3. **대표기업 기준 계정 표준화 부재** — concept_map + account_mapper(별칭)뿐.
  4. **다운로더 공백** — 결산월 변경 이력 미처리, 첨부정정 미탐지, 파일 무결성 사전검증 없음.

## 2. 아키텍처 (파이프라인 + 게이트)

```
[corp 목록]
    │
    ▼  ① Report Downloader (PRD 01)
raw_report 파일 + filings/download_tasks
    │
    ▼  ── 게이트 A ── ② Download Validator (PRD 02)
   (파일 무결성·재무제표 존재·정정 완전성)  ── FAIL → PM 보고, #3 진입 차단
    │ PASS
    ▼  ③ Financial DB Builder (PRD 03)
fact_v2 → statement_source → std_financials_v2 (+ 분기 이산행)
    │
    ▼  ── 게이트 B ── ④ DB Validator (PRD 04) ★최우선
   (본문 전 계정 표시단위 100% 일치)  ── FAIL → promote 차단, 감사대장 기록
    │ PASS
    ▼
standard_financials (view) — 게이트 B 통과분만 노출
```

handoff 핵심: **게이트 B 미통과 (corp, year, period, basis) 는 `standard_financials` 가 노출하지 않는다.**

## 3. 단위·용어 규약

- **저장 단위**: 모든 금액은 **원(KRW) 정수**로 `fact_v2.amount_won` 에 저장. `amount_won = 표시값 × 10^(-ADECIMAL)`.
- **표시단위 환산**: `표시값 = amount_won × 10^(ADECIMAL)`. 보고서가 백만원 단위면 ADECIMAL=-6.
- **100% 일치 정의**: `round(DB_amount_won × 10^ADECIMAL) == 보고서_표시값`. 즉 **보고서 표시단위 자리까지 정확 일치**. 표시단위 이하(원·천원 자리 등 보고서에 없는 자리)는 검증불가로 인정.
- **basis**: `consolidated`(연결) / `separate`(별도). ACONTEXT member 토큰으로 판정.
- **period**: `FY`(연간)·`H1`(반기 누적)·`Q1`/`Q3`(분기). 환산 후 추가: `Q2`/`Q4`(이산, flow 한정).
- **statement**: `BS`(재무상태표·시점)·`IS`(손익계산서·기간)·`CF`(현금흐름표·기간).
- **flow vs stock**: IS/CF = 기간(flow, 분기 차감 가능). BS = 시점 잔액(stock, 차감 불가 → 환산 안 함).
- **2층 모델**: **Layer 1(원본/as-filed)** = 보고서 회계기간 그대로(`std_v2`/view `standard_financials`) → **게이트 B·진실원**. **Layer 2(달력 정규화)** = 전 기업 12월 달력기준 분기/연간 파생(`std_financials_calendar`) → 비교·시각화용, 파생 플래그, 게이트 B 비적용. 설계 PRD 03 §5.3.

## 4. 게이트 운영 규칙

### 게이트 A (Download Validator)
- 통과조건: 파일 존재·무결(0바이트/매직바이트/절단 아님) ∧ BS·IS·CF face 표 존재 ∧ 정정본 있으면 원본+정정본 모두 확보.
- 실패 시: 해당 (corp, year, period) 를 `gate_a_fail` 로 표시, PRD03 진입 차단, PM 리포트.

### 게이트 B (DB Validator) — 차단의 핵심
- 통과조건: 그 (corp, year, period, basis) 의 **본문 BS/IS/CF 전 계정 라인**이 보고서 표시값과 표시단위 기준 정확 일치.
- 단 하나라도 불일치 → **promote 차단**(view 미노출), 감사대장에 FAIL+사유 기록.
- 일치 측정·실패목록은 재현가능해야 함(같은 입력 → 같은 판정).

## 5. 빌드 순서 (의존성 순)

> **원칙**: 게이트 B 는 원본 보고서를 **대조**(소비)하므로, **현재 시점까지 필요한 전 보고서가 확보·검증된 뒤**라야
> 게이트 B 가 완전한(누락 없는) 판정을 낼 수 있다. 게이트 B 는 보고서를 생산하지 않는다 →
> **완전성 확보(다운로드+게이트 A)가 선행**한다. 게이트 B → 다운로더 방향은 *피드백*(불일치 원인이 다운로드 품질일 때 회부)일 뿐 전방 의존이 아니다.

1. **다운로드 완전성 확보 (PRD 01 + 02)** ★선행:
   - PRD 01 다운로더 완주(결산월 변경 이력·첨부정정 포함) → 현재 시점까지 필요한 전 보고서 확보.
   - PRD 02 게이트 A(파일 무결성·재무제표 존재·정정/기간 완전성) → **감사 가능한 모집단 확정**.
   - (병행) **게이트 B 도구 파일럿**: 디스크에 이미 있는 표본으로 `face_audit` 추출기 신뢰성만 사전 검증(생산 감사 아님).
2. **게이트 B 전수 (PRD 04)**: 완전한 모집단 위 보고서-vs-DB 100% 일치 감사 + 미통과분 promote 차단.
3. **분기 환산 + 표준화 (PRD 03)**: 게이트 통과 데이터 위 부가가치 레이어.
- **피드백 루프**: 게이트 B 불일치 원인이 다운로드 품질이면 PRD 01/02 로 회부.
- 각 단계는 `fin2` 테스트 + golden 5/5 + parity 무회귀 확인 후 다음으로.

## 6. 추적 지표 (PM 대시보드)

| 지표 | 정의 | 목표 |
|------|------|------|
| 게이트 A 통과율 | PASS report / 전체 expected report | → 100%(마감유예 지난 분) |
| 게이트 B 일치율 | 본문 전 계정 일치 (corp,yr,pd,basis) / 전체 | → 100% promote 전제 |
| 분기 재합산 일관성 | `ΣQ=FY`, `Q1+Q2=H1` 성립 비율 | 측정 후 목표 설정 |
| 미매핑 계정률 | canonical NULL / 전체 추출 계정 | 표준화로 감소 |
| coverage 갭 | fact_v2 있으나 std_v2 없음 | 0 |

## 7. 리스크 / 롤백

- **게이트 B 가 대량 FAIL** → 즉시 promote 차단이 view 를 비울 수 있음. 완화: 단계적 promote(통과분만), legacy 비교로 회귀 구분, 실패 클래스별 트리아지.
- **분기 환산이 결측분기로 깨짐** → 미생성 원칙(추정 금지). 부분 결측은 NULL.
- 롤백: 모든 변경은 가역. view 스왑·신규행은 `applied_rules` 마커로 식별·제거 가능.

## 8. 비범위

- 시각화(원 개발목표, 데이터 신뢰 확보 후), DB 엔진 교체, 수집 대상 확장(현 KOSPI/KOSDAQ 보통주 유지).
- 주석 100% 검증(2단계), pre-2007 K-GAAP 추가 정밀화.

## 9. 전문가 PRD 색인

- `01_report_downloader.md` — 다운로드 담당
- `02_download_validation.md` — 게이트 A
- `03_financial_db_builder.md` — 파싱·표준화·분기환산
- `04_db_validation.md` — 게이트 B (100% 일치) ★최우선
