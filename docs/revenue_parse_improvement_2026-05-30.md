# 매출액 파싱 개선 작업 결과
**작업일**: 2026-05-30  
**작업 범위**: standard_financials.revenue no-parse 해소

---

## 최종 성과

| 지표 | 작업 전 | 작업 후 | 개선율 |
|---|---|---|---|
| 전체 no-parse 행 | 6,422 | **4,441** | **-31%** |
| FY no-parse 행 | 4,193 | **2,781** | **-34%** |
| 2022-2025 FY no-parse 기업 | 40개 | **5개** | **-88%** |

---

## 수정 내용

### 1. 보완 ① 개선 — unit_multiplier 우선순위 (`analyzer/aggregator.py`)

**문제**: IS_C col_index≥1 폴백 쿼리가 일부 단위(unit_multiplier=1,000,000)를 무시  
**원인**: COALESCE(unit_m=1, unit_m=1000)로 unit_m=1,000,000 제외  
**수정**: `COALESCE(unit_m=1 우선, MAX 전체 폴백)`으로 변경

```sql
SELECT COALESCE(
  MAX(ABS(ff.amount)) FILTER (WHERE ff.unit_multiplier = 1),
  MAX(ABS(ff.amount))
)
```

**효과**: SK(00181712) 2022 FY consolidated 1,320,793억 복구

---

### 2. 보완 ③ 추가 — IS_C 부분공시 시 IS_S 폴백 (`analyzer/aggregator.py`)

**문제**: XBRL에서 연결 IS가 영업이익 이하만 공시(매출 누락)하는 기업  
**대상 패턴**: IS_C에 `is.ebt`, `is.net_income`만 있고 `is.revenue` 없음  
**수정**: `statement_type=consolidated`이고 revenue=NULL일 때 IS_S col_index=0 값 사용 (DQ=2)

```python
# revenue 보완 ③: IS_C 매출 없을 때 IS_S로 폴백 (DQ=2 표시)
SELECT COALESCE(
  MAX(ABS(ff.amount)) FILTER (WHERE ff.unit_multiplier = 1 AND ABS(ff.amount) >= 100000000),
  MAX(ABS(ff.amount)) FILTER (WHERE ABS(ff.amount) >= 100000000)
)
FROM financial_facts ff
WHERE ff.fs_type = 'IS_S' AND ff.account_code = 'is.revenue'
  AND ff.fiscal_year = :fy AND ff.fiscal_period = :fp
  AND NOT ff.is_superseded
```

**주요 수혜 기업**: HPSP(2024), 힘스(2025), 참좋은여행(2024/2025), 비큐AI(2023), 램테크놀러지(2023), 플레이디(2023), 캐리(2022/2023), 바이오인프라(2024/2025), 유니드비티플러스(2022/2023), 한양증권(2022), 흥국화재(2024/2025), 롯데손해보험(2024/2025) 등 28개사 해소

---

### 3. revenue 중복 최대값 버그 수정 (`analyzer/aggregator.py`)

**문제**: IS에 동일 account_code(is.revenue)가 col_index=0,1,2 여러 개 존재할 때 MAX 선택  
**원인**: `col_index=2`의 과거 비교 데이터(큰 값)가 `col_index=0`의 현재 값을 덮어씀  
**예시**: 캐리(00863038) 2024 → 82억(정상)이 523억(2022 비교값)으로 덮힘  
**수정**: 현재값이 1억 미만일 때만 더 큰 값으로 교체

```python
# 변경 전
elif col_name == "revenue" and abs(v) > abs(sf_values["revenue"]):
# 변경 후
elif col_name == "revenue" and abs(sf_values["revenue"]) < 100_000_000 and abs(v) > abs(sf_values["revenue"]):
```

---

### 4. 계정 매핑 추가 (`account_maps/is_accounts.py`)

| 추가 계정명 | 매핑 | 대상 기업 |
|---|---|---|
| `보험판매수입수수료` | `is.revenue` | 인카금융서비스(01013694) |

---

## 잔여 no-parse (수정 불필요)

### 2022-2025 FY — 5건 (genuine no-revenue)

| 기업코드 | 기업명 | 연도 | 사유 |
|---|---|---|---|
| 01221752 | 지에프씨생명과학 | 2022 | 해당 연도 매출 없음 |
| 01235296 | 셀리드 | 2023 | 임상 단계, 매출 0원 |
| 01335851 | 박셀바이오 | 2022 | pre-revenue 바이오 |
| 01351080 | 지아이이노베이션 | 2024 | pre-revenue 바이오 |
| 01495180 | 파로스아이바이오 | 2025 | pre-revenue 바이오 |

### 전체 잔여 4,441건

- **2010년 이전 K-GAAP**: K-IFRS 전환 전 구형 계정명 미매핑 (대다수)
- **IFRS 17 보험사**: 2024+ IS 구조 변경 (흥국화재·롯데손해보험은 IS_S 폴백으로 해소)

---

## DQ=2 기업 목록 (IS_S 폴백 사용, 정상 범위)

`statement_type=consolidated`이고 IS_C에 직접 매출이 없어 IS_S 값을 사용한 경우.  
값은 정확하나 IS_C 직접 공시가 아님을 나타냄.

- 흥국화재(00103176), 롯데손해보험(00113562) — IFRS 17 IS_C 부분공시
- HPSP(01288827), 힘스(00556712), 참좋은여행(00606770) 등 XBRL 부분공시 기업
- 한양증권(00162416) 2022 — IS_C col_index=0 누락

---

## 향후 개선 가능 항목

1. **`dart_xml_parser.py`**: `ifrs-full_InsuranceRevenue` → `is.revenue` 추가  
   → IFRS 17 보험사 IS_C에서 보험수익 직접 추출 (현재는 IS_S 폴백)
2. **2010년 이전 K-GAAP 계정명**: 대용량 추가 매핑 작업 필요
3. **웹케시·한양증권 IS_C**: 연결 IS XML 구조 별도 파서 개선 필요
