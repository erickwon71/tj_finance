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

### Class B — 연결 단위/스케일 오류 = ★소스 데이터 오류(파서 아님) ◻
- **우진플라임 2012FY 연결**: `is.controlling_ni`=69,067억 vs net 69억 (정확히 1000×).
  **원문 대조 결과 소스 파일 자체의 오타**: 손익계산서에 `6,906,699,699,581`(자릿수그룹 '699'
  중복) 기재. 동일 값이 자본변동표엔 정상 `6,906,699,581`(69억). 파서는 소스를 충실히 추출 =
  garbage-in. 후보 1개라 재선택 불가.
- 규모: 연결 ratio>2 & |net|≥10억(=net 신뢰, 순수 B) 89행 · ratio>5 극단 105행. 대부분 소스오타.
- **수정 안 함(백로그)**: 소스 오류라 파서 교정 불가. 안전한 자동교정(항등식으로 controlling=
  net−nci 강제)은 net 오추출 케이스(Class C)와 구분 못하면 위험 → 보류. 향후 옵션: |controlling|
  >|net|×K(극단) AND net 이 CF 당기순이익과 교차확인될 때만 net−nci 로 override.

### Class C — net_income≈0 = ★EPS 오매핑(파서 버그) ✅수정
- **이월드 2013H1**: `is.net_income`=0.00억 ← 출처가 `기본주당기순손익(손실)`·`희석주당기순손익
  (손실)` = **주당(EPS, 원/주) 라인**. 실 당기순이익 라인이 없거나 작을 때 dedup max-abs 가
  주당값(수십 원)을 채택 → net_income ~0 오염, controlling_ni 비율 폭증.
- **근본**: `account_mapper.map` is-섹션 퍼지가 '기본주당기순손익'을 '당기순손익'과 0.94 유사도로
  `is.net_income` 매핑. (line 188 주석은 '주당' 차단을 의도했으나 **코드 미구현**이었음.)
- 규모: fact_v2 에서 주당 출처 `is.net_income` **8,301 facts / 644사**(+is.controlling_ni 348·
  is.ordinary_income 332·is.noncontrolling_ni 67 등). ★net_income(헤드라인) 광범위 오염.

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

## 3b. 해결 — Class C (2026-07-16)

**수정** (`parser/common/account_mapper.py::map`, 커밋 3b023d1): is-섹션 가드에 `'주당' in
normalized → unknown` 추가(원단위 손익 canonical 에서 EPS 라인 배제). '당기순이익(손실)'(주당
없음)은 정상 매핑 유지.

**검증(롤백 재추출)**: 이월드 net 0억 오염행 제거, 무림페이퍼·서울식품(실 net 존재)·삼성전자
무변(무회귀). fin2 테스트 통과.

**백필**: `scripts/fin2_fix_controlling_ni_reextract.py --corps-file`(EPS 오염 686사 재추출→
재표준화). 완료 시 Gate B 대신 잔여 EPS-net facts=0 확인 + 어서션.

## 4. 백로그 (미해결)

- **Class B (연결 소스 오타/스케일)**: `우진플라임`류 = 소스 파일 자체 오타(자릿수 중복). 파서
  교정 불가. 안전한 자동교정 가드는 Class C(net 오추출)와 혼동 위험이라 보류. CF 당기순이익
  교차확인 기반 override 가 향후 옵션. 규모 작음(순수 B ~89행).
- 이후 잔여 controlling_ni WARN 은 (정당 비지배음수 + 소스 미보고 + Class B 소스오타)로 구성.
