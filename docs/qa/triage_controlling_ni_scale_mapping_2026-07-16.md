# Triage — controlling_ni 극단 이상치 (총포괄 오염과 무관한 라인오매핑·스케일 버그)

- **작성일**: 2026-07-16
- **분류**: 데이터결함 (라인 오매핑 · 단위/스케일 · net_income 오추출 혼재)
- **상태**: 부분 해결 (Class A 수정·백필 완료, Class B·C 백로그)
- **관련**: [[bug-controlling-ni-total-comprehensive]] · 선행 트리아지
  `docs/qa/triage_controlling_ni_residual_2026-07-14.md` · `fin2/standardize/rules.py`
- **맥락**: 총포괄 오염(P1~P3b) 교정 후 잔여 genuine 위반 1,414건의 대형주 스팟체크에서,
  총포괄과 **성격이 다른** 극단 이상치 발견(기업은행 30×·CJ제일제당 1000× 등). 별건 트리아지.

---

## 1. 요약

잔여 위반 중 `|controlling_ni| > |net_income|×2` 인 **극단 이상치 262행**(연결 235·별도 27,
그중 >10× 80행 · >100× 15행)은 총포괄 오염(같은 자릿수)이 아니라 **세 가지 다른 버그**다.

| Class | 내용 | 규모 | 상태 |
|---|---|---:|---|
| **A. 별도재무 지배분 오매핑** | 별도(standalone)엔 지배/비지배 구분이 없는데 '지배기업 주주지분'(자본)·XBRL오류·스케일오류로 controlling_ni≠net | **394행 / 256사** | ✅ 수정·백필 |
| **B. 연결 단위/스케일 오류** | 연결 손익표에서 controlling_ni 라인만 ~1000× (단위 오인식) | ~15행(>100×) 등 | ◻ 백로그 |
| **C. net_income≈0 아티팩트** | net 이 0 근처로 오추출돼 비율만 폭증(controlling 은 정상일 수 있음) | 다수(저net) | ◻ 백로그 |

---

## 2. 근본원인 (원문 대조)

### Class A — 별도재무제표 지배분 오매핑 ✅
별도재무제표는 단일 법인이라 **비지배지분이 없어 지배순이익 ≡ 당기순이익**(회계 정의). 그런데:
- **기업은행 2013Q1 별도**: `is.controlling_ni`=138,722억 ← 원문 `IS_S/I. 지배기업 주주지분`
  (= **자본(equity) 라인**을 손익 지배분으로 오매핑). 정답 분기순이익 2,749억.
- **CJ제일제당 2025FY 별도**: −5,896,052억 (adec=−3, XBRL `ProfitLossAttributableToOwners`
  가 별도 컨텍스트에 1000× 값). 정답 −5,896억.
- **현대차증권 2025H1 별도**: 404,292,647억 (XBRL 값 자체가 ~1e6× 오류).

→ **원인 불문**(자본 오매핑·XBRL 오류·스케일), 별도는 controlling≡net 이 참이므로 표준화에서
강제하면 일괄 교정된다.

### Class B — 연결 단위/스케일 오류 ◻
- **우진플라임 2012FY 연결**: `is.controlling_ni`=69,067억 vs net 69억 (정확히 1000×).
  라벨은 정상(`지배기업의 소유주에게 귀속되는 당기순이익`), **값만 1000× 오파싱**. 같은 표의
  net(69억)은 정상 → controlling_ni 셀의 단위/자릿수 파싱 오류(라인 국소적).
- 후보 1개(69,067)라 재선택 불가. 원문 셀 단위선언 재검 필요.

### Class C — net_income≈0 아티팩트 ◻
- 이월드·서울식품 등 net≈0 → 비율만 수백만×. controlling 은 정상일 수 있고 **net 오추출**이
  본질일 가능성. controlling_ni 버그로 보기 어려움 → net_income DQ 로 별도 추적.

---

## 3. 해결 — Class A (2026-07-16)

**수정** (`fin2/standardize/rules.py::rule_controlling_ni_fill`, 커밋 3bfba52):
`NULL 일 때만 채움` → **별도는 net 과 다르면 항상 net 으로 강제**. 연결은 실제 비지배분이
있으므로 불변. 데이터 재추출 불필요(fact_v2 불변, 규칙만 재적용 = 재표준화).

**검증(롤백 재표준화)**: 기업은행·CJ제일제당·현대차증권 별도 위반 전부 0, 우진플라임(연결
스케일) 불변. fin2 테스트 통과(별도 강제·연결 불변 케이스 추가).

**백필**: `scripts/fin2_fix_controlling_ni_separate.py` — 별도 위반 256사 재표준화(+comparative
+quarterly+calendar). 별도 위반 394 → 0 목표.

---

## 4. 백로그 (미해결)

- **Class B (연결 단위/스케일)**: `우진플라임`류. 텍스트 추출기의 라인 단위 선언 처리
  재검(`amount_normalizer.detect_unit_declaration` + 표 내 국소 단위) 필요. 소수지만 절대오차 큼.
  가드 대안: `|controlling_ni| > |net_income|×N AND 후보 1개 AND 연결` → controlling_ni 를
  버리고 net−nci 로 대체(과한 자동교정 위험 있어 신중).
- **Class C (net≈0)**: net_income 오추출이 본질. controlling 과 분리해 net_income 완전성/정확성
  DQ 로 트래킹. (별도 이슈)
- 이후 잔여 controlling_ni WARN 은 (정당 비지배음수 + 소스 미보고 + Class B·C)로 구성.
