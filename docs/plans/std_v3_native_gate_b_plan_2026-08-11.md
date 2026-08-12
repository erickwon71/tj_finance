# 계획 — v3-native Gate B 품질게이트 (`face_audit` 의 std_v2 의존 제거) (2026-08-11 작성, 2026-08-12 갱신)

> **Phase 0~3(구조확인·마이그레이션·러너확장·전량실행) 전부 완료.** Phase 3 부록으로 fail
> 패턴 원문대조 조사까지 마쳤고(§7 Phase 3-부록), 그 결과 **Phase 4 착수 전에 먼저 처리하는
> 게 나은 선행 결함(Gate B 감사기 자체의 오탐)을 발견**했다(§8 신규 제안, 아직 미승인).
> **이 문서 갱신은 조사 결과 정리일 뿐 — 코드/DB는 전혀 건드리지 않았다. 실행은 별도 승인
> 필요(자동 착수 금지).**

배경: [`rearchitecture_4layer.md`](rearchitecture_4layer.md) §7 후속 트랙 1번(v3-native 품질게이트).
사용자가 "v2는 필요없을텐데 뭔가 걸리는게 있어서 삭제를 못했다"고 지적 → 조사 결과 원인이
`face_audit`(Gate B 감사대장)이 구조적으로 std_v2 전용이라는 것으로 확정됨(§1).

---

## 0. 요약

- **막고 있는 것**: `scripts/gateb_audit.py`(Gate B 생산 감사기, `face_audit` 대장을 채우는 유일한
  경로)가 처음부터 끝까지 `std_financials_v2`만 읽는다. std_v3용 감사 경로가 아예 없다.
- **더 나쁜 것**: `standard_financials` 뷰는 std_v3 행에도 `gate_b_status`를 붙이지만, 이건
  **키(corp,fy,fp,basis)로 `face_audit`을 조인해 v2 감사결과를 빌려주는 것**이지 v3 자신의
  값을 감사한 게 아니다. 실측: 현재 "pass"로 표시되는 v3 행 243,684건 중 **22,935건(9.5%)은
  `total_assets`가 v2와 다른데도 pass 라벨을 달고 있다** — 대조된 숫자(v2)와 화면에 뜨는 숫자
  (v3)가 다른 상태에서 "검증됨"이라고 주장하는 것.
- **다행인 점**: 감사 판정 엔진 자체(`fin2/audit/face_audit.py::audit_std_row`/`audit_fields`)는
  `db_row: dict` 를 받는 범용 함수라 std_v2/v3 어느 쪽이든 재사용 가능하다 — 문제는 감사엔진이
  아니라 **러너(`gateb_audit.py`)의 배선**과 **`face_audit` 테이블이 v2/v3 병행 저장을
  지원 못하는 스키마**다.
- **결정이 필요한 핵심 지점**: v2·v3가 겹치는 corp-period(240,353건 실측)를 **양쪽 다 감사해서
  병행 보관**해야 하는데, `face_audit` PK(`corp_code,fiscal_year,fiscal_period,statement_type,
  is_stub`)엔 버전 구분이 없어 나중에 돌린 쪽이 먼저 것을 덮어쓴다(§2-2).

---

## 1. 현재 결함 — 확정 (코드·DB 대조 완료)

### 1-A. 감사 러너가 std_v2 하드코딩

- `scripts/gateb_audit.py:77` — 대상 기업: `SELECT DISTINCT corp_code FROM std_financials_v2 WHERE version=1`
- `scripts/gateb_audit.py:92-98` — 대상 행: `SELECT * FROM std_financials_v2 WHERE ...`
- `collector/models.py:1097,1100` — `face_audit` 테이블 자체가 "grain = std_financials_v2 와
  동일"이라고 명시. 버전 컬럼이 없음.

### 1-B. 뷰가 v3 행에 v2 감사결과를 "빌려주는" 구조

`collector/db.py:846`(std_v3 분기)·`:873`(std_v2 분기) 둘 다 같은 `face_audit` 테이블을
`(corp_code,fiscal_year,fiscal_period,statement_type)` 키로만 LEFT JOIN한다. `face_audit`
행 자체가 v2 값만 감사한 결과이므로, v3 분기의 `gate_b_status`는 "이 v3 행과 같은 키의
v2 값이 예전에 감사를 통과했다"는 의미이지 "이 v3 값이 감사를 통과했다"는 의미가 아니다.

**DB 실측(2026-08-11, 이번 세션)**:

| 항목 | 건수 | 비율 |
|---|---|---|
| std_v3 전체 행 | 297,429 | 100% |
| `face_audit` 키 매치 없음(`unaudited`) | 52,545 | 17.7% |
| `gate_status='pass'`로 표시되는 v3 행 | 243,684 | 81.9% |
| 그중 v2 대응행 존재 | 240,353 | — |
| 그중 `total_assets` 값이 v2와 **다른** 행 | **22,935** | **9.5%**(pass 표시분 대비) |

쿼리:
```sql
-- v3 행별 face_audit 매치/게이트 분포
SELECT count(*) v3_total, count(fa.corp_code) matched, count(*) FILTER (WHERE fa.gate_status='pass') pass
FROM std_financials_v3 v3
LEFT JOIN face_audit fa ON fa.corp_code=v3.corp_code AND fa.fiscal_year=v3.fiscal_year
  AND fa.fiscal_period=v3.fiscal_period AND fa.statement_type=v3.statement_type
  AND NOT COALESCE(fa.is_stub,false);

-- pass 라벨 중 v2와 값이 다른 행
SELECT count(*) FILTER (WHERE v3.total_assets IS DISTINCT FROM s.total_assets)
FROM std_financials_v3 v3
JOIN face_audit fa ON ... AND fa.gate_status='pass'
JOIN std_financials_v2 s ON ... AND s.version=1 AND NOT s.is_stub AND NOT s.is_discrete;
```

### 1-C. 앱은 현재 이걸 안 본다(당장 화면 오류는 아님)

`gate_b_status`/`standard_financials_verified`를 소비하는 곳은 `app/` 어디에도 없음(grep 확인).
따라서 지금 당장 사용자에게 잘못된 숫자가 노출되는 건 아니지만, PRD 04가 정한 "Gate B
통과=원문 100% 일치 보증"이라는 계약이 v3에 대해 성립하지 않는 상태로 방치되어 있다 —
v2를 지우는 순간 이 계약을 되살릴 방법이 없어진다(§1-A).

---

## 2. 설계 결정 지점 (착수 전 확정 필요)

### 2-1. 감사 엔진 자체는 재사용 가능 — 확인됨

`fin2/audit/face_audit.py::audit_std_row`/`audit_fields`는 `db_row: dict`(필드명 기반, `total_assets`
`revenue` 등)를 받는 범용 함수다. `STD_FIELD_CANONICAL`(line 31) 키도 std_v2/v3 공통 컬럼명이라
**수정 불필요** — 러너에서 v3 행을 같은 dict 모양으로 만들어 넘기기만 하면 된다.

### 2-2. ★face_audit PK 충돌 — 반드시 결정해야 함

v2·v3가 겹치는 240,353개 corp-period를 **양쪽 다** 감사해 병행 보관해야 한다(v2 브랜치는
v3가 못 채우는 잔여 — PDF-only 등 — 를 위해 계속 살아있어야 하므로, 뷰 브리지 트랙 종료
전까지는 v2 감사결과도 여전히 필요). 그런데 `face_audit` PK가
`(corp_code,fiscal_year,fiscal_period,statement_type,is_stub)`라 버전 구분이 없다 —
v3 감사기를 그냥 돌리면 같은 키의 기존 v2 감사결과를 **덮어쓴다**.

**제안(결정 필요)**: `face_audit`에 `source_version` 컬럼을 추가해 PK를 `(corp_code,fiscal_year,
fiscal_period,statement_type,is_stub,source_version)`로 확장. 기존 행은 백필 마이그레이션으로
`source_version='v2'`를 채운다. 뷰의 두 분기도 조인 조건에 `fa.source_version='v3'`
(std_v3 분기) / `='v2'`(std_v2 분기)를 추가.

### 2-3. rcept 조회 방식 차이 — 어댑터 필요

- v2: `bs_rcept`/`is_rcept`/`cf_rcept` 평면 컬럼(`gateb_audit.py:113-115`)
- v3: `source_rcepts` JSONB `{"BS":rcept,"IS":rcept,"CF":rcept}`(`collector/models.py:1778`)

`file_path_map`/`face_of` 호출부에서 `d.get("bs_rcept")` 대신 `d["source_rcepts"].get("BS")`로
바꾸는 어댑터 함수 하나로 흡수 가능(로직 자체는 무변경).

### 2-4. `is_comparative`(비교컬럼 폴백) 개념이 v3엔 없음

v2는 `applied_rules`에 `"comparative_fallback"`이 있으면 `is_comparative=True`로 넘겨
`audit_std_row`가 all-columns 대조(약한 검증)로 전환한다(`gateb_audit.py:144-152`). v3
(`fin2/layer3/combine.py`)엔 이 개념 자체가 없음(grep 0건) — 즉 v3는 값이 있으면 항상
그 filing 자신의 col0 출처다. **제안**: v3 감사에선 `is_comparative`를 항상 `False`로 고정
(엄격 대조만) — 결측이 늘 수는 있어도 거짓 pass는 안 나옴("결측 > 오염" 기존 원칙과 일치).

### 2-5. `is_stub`/`is_discrete` 필터 — v3엔 해당 컬럼이 없음 — ✅**Phase 0으로 확인 완료(2026-08-11)**

v2 쿼리는 `NOT is_stub AND NOT is_discrete`로 걸러낸다. `StdFinancialV3` 모델엔 이 두 컬럼이
없다. `fin2/layer3/build.py:41` 코드 주석이 이미 명시: "std_v3 has no version/is_stub columns
(unlike std_v2)". DB 실측으로 재확인:

- **fiscal_period 값 자체가 깨끗함**: std_v3 전체 297,429행이 `FY`/`Q1`/`H1`/`Q3` 4종뿐(다른
  변종 없음) — stub 기간을 나타내는 별도 표기가 새지 않는다.
- **is_discrete(49%!)는 원래도 기본 뷰에서 제외되는 행**: v2 전체 518,052행 중 253,775행
  (49.0%)이 `is_discrete=True`(PRD 03 §5.1 이산분기 파생행)인데, 기존 std_v2 뷰 분기도
  `NOT is_discrete`로 걸러 애초에 노출 안 됨. v3는 이 파생행 자체를 만들지 않으므로
  **커버리지 손실이 아니다** — 원래 뷰에 없던 것이 v3에도 없을 뿐.
- **is_stub(460건, 0.09%)은 규모가 무시할 만큼 작고, v3는 구분 없이 같은 키로 값을 채움**:
  v2 stub 460건 중 436건(94.8%)이 std_v3에도 같은 키(corp,fy,fp,basis)로 존재 — v3가
  "이 기간이 결산월 변경 stub이다"라고 특별 취급하는 게 아니라, report_lines에 있는 대로
  그냥 한 행을 만드는 것. **감사 관점에선 문제 없음**: stub이든 아니든 그 filing의 face
  표에 실제로 신고된 금액과 대조하면 되므로, v3 감사 러너는 v2처럼 별도 stub/discrete
  필터를 걸 필요가 없다(v3엔 걸러낼 대상 자체가 없음 — 규모도 0.09%로 무시 가능).

**결론**: §3 구현 방향 변경 없음 — v3 감사 러너는 stub/discrete 필터를 아예 안 넣고 std_v3
전체를 감사 대상으로 삼으면 된다.

### 2-6. `source_rcepts` 결측 케이스 — ✅**Phase 0으로 확인 완료(2026-08-11)**

DB 실측(297,429행 전수):
| 항목 | 건수 | 비율 |
|---|---|---|
| `source_rcepts IS NULL` | 0 | 0% |
| `BS` 키 없음 | 12,677 | 4.3% |
| `IS` 키 없음 | 767 | 0.3% |
| `CF` 키 없음 | 1,211 | 0.4% |
| **BS/IS/CF 전부 없음**(완전 결측) | **0** | **0%** |

NULL도 없고 3키가 동시에 다 빠지는 경우도 없음 — `d["source_rcepts"].get("BS")`처럼 dict
`.get()`으로 안전하게 처리 가능(§2-3 어댑터 그대로 유효, 방어코드 추가 불필요). 개별 키
결측(BS 4.3% 등)은 정상 시나리오(그 statement가 그 filing에 없는 경우)로, 기존
`face_of(rc)`가 `rc=None`이면 빈 리스트 반환하는 로직으로 이미 커버됨.

---

## 3. 구현 방향 (아직 코드 안 건드림)

1. **마이그레이션**: `face_audit`에 `source_version VARCHAR(2) NOT NULL DEFAULT 'v2'` 추가,
   PK 재구성. 기존 행 전부 `'v2'`로 백필(디폴트로 자동 충족). `collector/db.py` 신규 migration
   ID로 등재.
2. **`scripts/gateb_audit.py` 확장**: `--source {v2,v3}` 인자 추가(디폴트 `v2`=기존 동작 무변경).
   `v3`일 때:
   - `select_corps`/`audit_corp`의 `FROM std_financials_v2` → `FROM std_financials_v3`로 스위치
   - rcept 조회를 §2-3 어댑터로 교체
   - `is_comparative`를 §2-4 결정대로 항상 `False`
   - `face_audit` upsert 시 `source_version='v3'` 포함, `on_conflict_do_update`의
     `index_elements`에도 `source_version` 추가
3. **뷰 갱신**(`collector/db.py`, 신규 migration): std_v3 분기 JOIN에 `fa.source_version='v3'`,
   std_v2 분기 JOIN에 `fa.source_version='v2'` 추가. `CREATE OR REPLACE VIEW`라 무손실.
4. **`face_line_audit`(Phase B, 본문 라인 전수대조)는 이번 범위 밖** — `fact_v2` 기반이고
   현재도 `standard_financials` 뷰가 참조하지 않는 별도 측정 지표(`collector/models.py:1140`
   docstring 확인). 손대지 않는다.

---

## 4. 실행 순서 (승인 후)

1. **Phase 0 — 구조 확인(읽기전용)**: v3 표본 20~30건으로 §2-5(is_stub/is_discrete 유무) 확인,
   `source_rcepts` 결측/이상 케이스 유무 확인. 코드 변경 없음.
2. **Phase 1 — 마이그레이션 + 러너 확장**: §3-1·§3-2 구현. `--no-commit` 드라이런으로 소표본
   (`--sample 20 --source v3`) 검증.
3. **Phase 2 — 알려진 문제 케이스 재확인**: §1-B의 22,935건 중 표본을 v3 감사로 실제 돌려서
   — v2에선 pass였지만 v3 자체 값 대조로는 어떻게 나오는지 확인(신규 fail/pending 발생이
   기대되는 정상 시나리오인지 원문 대조로 판정).
4. **Phase 3 — 전량 실행**: `--source v3`로 std_v3 전체 감사(사용자 터미널, 장시간 —
   `[[feedback-long-running-commands]]`).
5. **Phase 4 — 뷰 갱신 + 검증**: §3-3 마이그레이션 적용 → `gate_b_status` 분포 재측정(v3
   분기 pass/fail/pending/unaudited), Gate B strict 뷰(`standard_financials_verified`) 무손실
   확인(v3 커버 케이스가 이전보다 줄지 않아야 함 — 단, 부정확 pass가 정직한 fail/pending으로
   바뀌는 것 자체는 이 트랙의 목표이므로 허용).
6. **문서화**: 이 문서·마스터 허브 §2/§5/§7 갱신.

---

## 5. 검증 계획

- **자기일관성**: v3 자체 감사에서 `is.controlling_ni` 등 이미 알려진 v2/v3 값 차이 케이스
  (삼성전자 FY2023 연결 등, `std_v3_controlling_ni_gap_fix_plan_2026-08-08.md` 표본)가
  v3 감사에서 실제로 pass 나오는지 원문 대조로 재확인.
- **회귀**: 마이그레이션 후 기존 `face_audit`(v2) 행 수·값 무변경 확인(`source_version='v2'`
  백필이 데이터를 안 건드리는지).
- **전수 대조**: v3 감사 전/후 `gate_b_status` 분포표(pass/fail_a/fail_b/pending/unaudited)를
  비교 — pass 비율이 줄어드는 게 정상(거짓 pass 제거)이므로 "감소=결함"이 아니라 "감소=기대값"
  임에 주의, 대신 **fail_a(확정버그로 차단) 급증**은 원문 대조로 진짜 문제인지 확인.
- pytest 전체 재확인(`pytest tests/ fin2/tests/`).

---

## 6. 범위 밖 (이번 계획에 안 넣음)

- **std_v2 물리적 삭제 자체** — 이 트랙은 전제조건(v3 자체 감사 경로)만 만든다. 삭제는
  §7 항목1이 끝나고 별도 판단(3차 PDF-only 패스가 남아있는 한 v2 UNION 폴백 자체는 계속
  필요할 수 있음 — [[pre2015-layer2-backfill-plan-2026-08-10]] 7-3 참고).
- **3차 PDF-only 패스**(1,405건) — 별도 트랙.
- **야간 잡 재설치** — 별도 트랙.
- **`face_line_audit`(Phase B) v3 대응** — 뷰가 안 쓰는 지표라 후순위.
- v2 잔여 감사 결함(18건 소액 불일치 등) — 기존에도 우선순위 낮음으로 분류된 것 그대로.
- **★신규(Phase 2 부수발견, 2026-08-11)**: `trade_payables` 라벨매핑 결함 — "장기매입채무및
  기타채무"(비유동)가 `bs.trade_payables`(유동 개념)와 오매칭됨(00825959 FY2024 연결에서
  확정, account_maps 카탈로그 소관 추정 — 다른 corp 영향 규모는 미측정). 이 계획(Gate B
  인프라)과는 무관한 combine/account_maps 버그라 별도 트랙 필요, 원인은 특정됨(§7 Phase 2 참고).

---

## 7. TODO 체크리스트 (승인 후 실행 순서)

> 이 계획을 사용자가 검토·승인한 뒤에만 착수한다. 체크박스는 진행하며 갱신한다.

### Phase 0 — 구조 확인(읽기전용) — ✅**완료(2026-08-11)**
- [x] v3 표본 20~30건에서 is_stub/is_discrete 상당 케이스 유무 확인(§2-5) — 전수 쿼리로 확인,
      필터 불필요 결론(discrete는 원래 뷰 미노출이라 손실 아님·stub은 0.09%뿐)
- [x] `source_rcepts` 결측/이상 케이스 표본 확인(§2-6) — 전수 쿼리로 확인, NULL 0건·3키 동시
      결측 0건, 어댑터 설계 그대로 유효

**결론: 걸리는 것 없음 — Phase 1(마이그레이션+러너 확장) 착수 가능.**

### Phase 1 — 마이그레이션 + 러너 확장 — ✅**완료(2026-08-11)**
- [x] `face_audit`에 `source_version` 컬럼 + PK 확장 마이그레이션(§3-1) — 마이그레이션
      `2026_08_face_audit_source_version` 적용, 기존 271,695행 전부 `source_version='v2'`
      무손실 백필 확인. PK = `(corp_code,fiscal_year,fiscal_period,statement_type,is_stub,
      source_version)`.
- [x] `scripts/gateb_audit.py --source v3` 구현(§3-2) — `_row_rcepts()` 어댑터(v2 평면컬럼/v3
      JSONB 통일), `_field_track()` source-agnostic화, v3는 `is_comparative` 항상 `False`
      고정(§2-4), `select_corps`/`audit_corp` 양쪽 source 분기, upsert에 `source_version`
      포함. `ensure_table()`을 `init_db()` 호출로 교체(신규 마이그레이션이 create_all만으론
      안 걸려서 필요).
- [x] **v2 무회귀 검증**: 리팩토링 전 코드(`git stash`)와 후 코드로 동일 corp(00126380,
      `--recheck --no-commit`) 감사 — **pass 124/fail 6, FAIL 6건 전부 동일**(byte-identical).
      리팩토링이 기존 v2 감사 로직/결과를 전혀 안 건드림을 확인.
- [x] **v3 신규 경로 동작 확인**: 같은 corp를 `--source v3`로 감사 → **pass 118/fail 1/pending
      11**(v2와 다른 결과 — 정상, v3 자신의 값을 실제로 대조하기 때문). v2가 잡던
      dividends_paid 6건 fail은 사라지고(v3 값이 v2와 달라 원문과 일치) controlling_ni 1건의
      새 fail_a가 나옴 — "v3 자체 값을 처음으로 감사"한다는 이 트랙의 목표가 실제로 작동함을
      보여주는 사례.
- [x] `--sample 20 --source v3 --recheck --no-commit` 크래시 확인(장시간이라 백그라운드 실행) —
      **완료, 크래시 0**: 20개사·1,952행 감사, pass 1,570 / fail 8 / pending 374(기업오류 0).
      in-scope(pass+fail) 일치율 99.5%. fail 8건은 전부 한 기업(00825959)의 `trade_payables`
      1개 필드에 몰려있음(2024~2025년 여러 기간) — 원문대조는 Phase 2 대상, 이번엔 "대량
      실행이 죽지 않고 도는지"만 확인.

### Phase 2 — 알려진 문제 케이스 재확인 — ✅**완료(2026-08-11)**
- [x] §1-B 22,935건 표본에서 v3 자체 감사 결과 원문 대조

**세부**: 22,935건을 3그룹으로 분해(전수 쿼리) — `v3_null_only` 8,460건(v3가 값 자체를
못 채움, held conflict)·`v2_null_only` 3,296건(v3가 새로 채운 값, v2엔 전혀 없던 필드)·
`both_present_differ` **11,179건**(양쪽 다 값 있고 실제로 다름 — 가장 직접적인 "누가
맞나" 케이스). `both_present_differ`에서 무작위 6건을 뽑아 `fin2/audit/face_audit.py`
엔진으로 **v2 rcept·v3 rcept 양쪽을 독립적으로 원문 재대조**:

| corp | 기간 | 결과 |
|---|---|---|
| 00145190 | 2015Q3 separate | 같은 rcept, v3 값이 원문과 **정확히 일치**(628,272,691,470) — v2 저장값(628,273,000,000)은 반올림 오차로 **자체가 이미 틀림** |
| 01047707 | 2015Q3 consolidated | v2의 bs_rcept(`20161114002226`)를 report_lines에서 역조회하니 **실제로는 FY2016 Q3 필링**(comparative bleed 확정) — v3는 진짜 FY2015Q3 필링(`20151110000039`) 사용, v3가 맞음 |
| 00463342 | 2012H1 consolidated | 동일 패턴: v2 rcept(`20140826000396`)는 실제 **FY2014 H1** 필링(comparative bleed 확정) — v3(`20120814001496`)가 맞음 |
| 00385336 | 2011H1 consolidated | 동일 패턴: v2 rcept(`20131128000547`)는 실제 **FY2013 H1** 필링(comparative bleed 확정) — v3(`20110816001525`)가 맞음 |
| 00939331 | 2013FY separate | 둘 다 진짜 FY2013FY 필링이지만 서로 다른 정정본 — v3는 `amend_chain`으로 **최신 정정**(2014-03) 채택, v2는 원본(2013-06) 유지. 설계상 "최신 정정 우선" 정책이 v3에서 의도대로 작동 |
| 00367695 | 2014FY consolidated | 같은 패턴, v3가 2016-12 정정본 채택(v2는 2015-06본) |

**결론(6건 전부 v3가 동등 이상)**: 6건 중 3건은 std_v2의 **기존 "comparative bleed" 결함
(이미 알려진 클래스, [[std-v3-controlling-ni-fix-complete-2026-08-09]] 등에서도 발견된 것과
동일 패턴)이 이번에 새 사례로 재확인**됐고, 2건은 v3가 "최신 정정 우선" 정본선택 정책을
v2보다 더 정확히 따른 것, 1건은 v3가 반올림 없이 더 정밀한 것. **v2가 "맞고" v3가 "틀린"
사례는 6건 중 0건.**

**부수 발견 — v3 자체의 진짜 결함 1건 확인**: 20개사 드라이런(Phase 1)에서 나온 유일한
`fail_a`(00825959, `trade_payables`, FY2024 연결)를 `report_lines` 원문과 직접 대조 —
v3가 `trade_payables`에 **"장기매입채무및기타채무"(비유동, 98,065,436원)를 잘못 매핑**해
놓았고, 진짜 유동 매입채무는 "매입채무 및 기타유동채무"(30,166,400,982원, 같은
table_seq=0의 다른 행)이었다. **account_maps 라벨매핑 결함**(비유동 항목이 `bs.trade_
payables`와 오매칭) — 이번 신규 감사경로가 없었으면 안 잡혔을 진짜 v3 버그. 수정은 이
계획 범위 밖(§6에 후속 후보로 등재), 원인은 특정돼 있어 후속 세션에서 바로 착수 가능.

**Phase 2 종합 결론**: v3-native 감사가 (a) 구조적으로 정상 작동하고 (b) v2의 숨은
결함(comparative bleed)을 새로 재확인하며 (c) v3 자체의 진짜 결함도 처음으로 잡아낸다 —
Phase 3(전량 실행) 진행 근거 충분.

### Phase 3 — 전량 실행 — ✅**완료(2026-08-12 새벽 확인)**
- [x] `--source v3` 전량 실행(사용자 터미널)

**진행 상황**: 먼저 이번 세션이 백그라운드로 시도했으나 47분·97개사(16,867행: pass
10,243/fail 154/pending 6,470) 진행 후 환경에 의해 강제종료(`killed`, 파이썬 예외 아님) —
corp 단위 커밋이라 데이터 손상 없음, 멱등 재개 가능함을 확인. 이후 사용자가 본인 터미널에서
직접 실행:
```
python -u scripts/gateb_audit.py --source v3 --fy-min 1999 --no-line-audit 2>&1 | tee gateb_v3_full.log
```

**완료 확인(2026-08-12)**: `gateb_v3_full.log`(2026-08-11 19:29 ~ 08-12 07:44, 약 12시간) —
**2,525개사 전량·`err=0` 전 구간·로그가 요약배너까지 안 끊기고 완주**. DB 실측 교차검증:
이번 run 280,562행 + 이전 부분실행 97개사·16,867행 = **297,429행**(=corp 2,525 전체와
정확히 일치), `--recheck` 없이 돌려 97개사 자동스킵(멱등재개 확인)도 수치가 정확히 맞아떨어짐.

**누적 v3 gate_status(297,429행)**:

| gate_status | 건수 | 비율 |
|---|---|---|
| pass | 197,635 | 66.4% |
| pending | 96,012 | 32.3%(이중 74%가 pre-2015) |
| fail_b(REVIEW) | 2,688 | 0.9% |
| fail_a(차단) | 1,094 | 0.4% |

in-scope(pass+fail) 일치율 = **98.1%**(v2 99.87%와는 in-scope 범위 자체가 달라 단순비교
무의미 — v2 pending은 1.4%뿐).

### Phase 3-부록 — fail 패턴 원문대조 조사 — ✅**완료(2026-08-12, 읽기전용)**

전량 실행 결과의 fail_a/fail_b를 그냥 숫자로만 두지 않고, 대표 사례를 원문(raw XBRL·
`report_lines`·`read_report_face()`)과 직접 대조해 세 가지 서로 다른 버그 유형을 분리해냈다.
**전부 조사만 완료, 코드 미수정.**

**A) `revenue` fail_b(2,514/2,688건, fail_b의 93.6%) — 증권사·금융지주 집중**

상위 실패기업 15곳이 거의 전부 증권사/금융지주(삼성증권·미래에셋증권·DB증권·교보증권·
유안타증권·SK증권·신영증권·현대차증권·키움증권·LS증권·하나금융지주·KB금융 등).
신영증권(00136721)을 3중 원문대조(`read_report_face()` 재추출 + `report_lines` 검색 +
raw XML grep): v3 저장값이 face 표의 두 값(누적/단일분기) 어느 쪽과도 안 맞고, 그 rcept의
`report_lines`에 **값 자체가 존재하지 않음** — v2의 올바른 이산분기 파생값과도 다르다.
초기가설("금융업 매출정의 차이")은 **기각**. raw XBRL엔 `ifrs-full_Revenue`가 이산분기
(dFQQ)/누적(dFQA) 두 컨텍스트로 나뉘고 별도 `ifrs-full_RevenueFromInterest` 개념까지
공존(제조업 필링엔 없는 구조) — **std_v3의 concept/context 선택 로직이 금융업 필링에서
잘못된 컨텍스트를 고르는 결함으로 추정**(정확한 메커니즘은 `fin2/layer3` 코드레벨 추적
필요, 이번엔 증상만 확정. §8-C 후보).

**B) Gate B 감사기 자체의 doc_default_unit 미적용 — fail_a/b 오탐(false positive) 확정**

`trade_payables` fail_a(310건·80개사) 전수의 db_won/report_won 비율을 계산하다 정확히
×1000(일부 ×0.1/×10)인 클러스터를 발견. 노루페인트(00583442)로 확정: 문서 표시값이
"111,249,978"(실제 단위=천원)인데 감사기가 **문서 기본단위(doc_default_unit, R4-1에서
메인 추출기엔 이미 구현된 로직)를 안 읽어 원 단위로 오인식** → report_won을 111,249,978원
(틀림)으로 계산, 실제 std_v3 값 111,249,977,575원이 **맞는 값**이었다. 즉 이 케이스들은
std_v3 버그가 아니라 **Gate B 감사기 자체의 결함으로 인한 오탐**.

전체 fail_a/fail_b로 스캔 범위를 넓혀 규모를 확정했다(±2% 허용 오차로 10ⁿ배 매칭):

| 대상 | 총 행수 | 10ⁿ배수 의심 | 필드분포 | 영향기업 |
|---|---|---|---|---|
| fail_a | 1,094 | **53건** | trade_payables 23·inventory 19·revenue 5·ppe 3·cash 2·dividends_paid 1 | 23개사 |
| fail_b | 2,688 | 8건 | revenue 6·net_income 1·cff 1 | 5개사 |
| **합계(고유기업)** | — | 61건 | — | **28개사** |

배율은 거의 전부(47/53) 정확히 ×1000. **결론: doc_default_unit 미적용은 trade_payables
국지적 문제가 아니라 Gate B face reader(`read_report_face_xbrl`) 전반의 결함**이다. 단,
(A)의 증권사 revenue fail_b는 이 스캔으로 거의 안 걸림(6건뿐) — (A)는 확정적으로 별개 버그.

**C) `trade_payables` account_maps 라벨매핑 결함 — 00825959 외 3개사 추가확인, 이질적 버그**

(B)의 10ⁿ배 오탐 23건을 제외한 나머지 ~285건은 배율이 0.02배~226배로 기업마다 제각각.
Phase 2에서 00825959(FY2024 연결, "장기매입채무및기타채무"(비유동)를 `bs.trade_payables`에
오매칭) 1건으로 원인규명된 것과 같은 계열임을 코아스(00210856)·FSN(01061497)·
솔루스첨단소재(01412822) 3개사 추가로 확인(전부 db_won이 report_won의 약 1/3~1/4로
일관되게 작음, 같은 방향) — **단발성이 아니라 반복되는 account_maps 결함**이다. 단
배율이 기업마다 달라 "표 구조가 다르면 어떤 부분항목이 걸리는지도 다른" 이질적
(heterogeneous) 버그로, 일괄 자동수정보다는 계정매핑 카탈로그(account_maps) 점검이 필요.

**중요 시사점**: fail_a 1,094건 전체(controlling_ni 등 아직 안 본 필드 포함)에 (B)류
오탐이 더 섞여있을 가능성은 위 표로 이미 배제됨(전수 스캔 완료). 즉 (B)를 고치면 fail_a가
1,094 → 약 1,041건으로 줄고, 남는 fail_a는 (A)·(C) 계열의 "진짜" 결함 신호로 더 선명해진다.

---

## 8. 다음 단계 제안 (미승인 — 실행 대기)

Phase 3-부록 조사로 우선순위가 바뀌었다. **Phase 4(뷰 마이그레이션)를 그대로 진행하면
(B)의 오탐이 fail_a에 계속 섞인 채로 확정되므로, (B) 수정이 먼저인 게 낫다는 제안.**
아래 중 무엇을 먼저 할지, 순서를 어떻게 할지는 **사용자 결정 대기** — 이 문서는 옵션
정리까지만 하고 착수하지 않는다.

- **8-A. Gate B face reader에 doc_default_unit 폴백 이식**(R4-1 로직을
  `read_report_face_xbrl`로 이식) — (B) 오탐 제거. 수정 후 영향 28개사만 `--recheck`로
  재감사해 오탐이 실제로 사라지는지 검증. 범위가 좁고 원인이 명확해 착수 난이도 낮음.
- **8-B. Phase 4(뷰 JOIN에 `source_version` 반영 마이그레이션)** — 원 계획대로 진행.
  8-A 이후에 하면 더 정확한 상태로 뷰가 교체됨.
- **8-C. 증권사/금융지주 revenue concept 선택 결함 코드레벨 추적+수정** — (A). fail_b의
  93%를 차지하는 가장 큰 덩어리지만 코드 추적이 더 오래 걸림(`fin2/layer3` concept
  mapping 레벨).
- **8-D. `trade_payables` account_maps 이질적 오매칭 나머지(~285건) 개별 확인+수정** — (C).
  기업별로 다른 표 구조라 자동화 난이도 높음, 우선순위 낮음.

관련 메모리: `[[std-v3-controlling-ni-fix-complete-2026-08-09]]` `[[std-v3-dq-shares-period-null-2026-08-09]]`
`[[pre2015-layer2-backfill-plan-2026-08-10]]` `[[std-v3-native-gate-b-plan-2026-08-11]]`
`[[doc-default-unit-r4-1]]`

---

## 9. §8-A 확장 재검증 — fail_a 전체(362개사)로 recheck 확장 (2026-08-12, 사용자 실행)

§8-A 실행 직후 "recheck을 30개사(65건 후보)로만 좁힌 게 맞나, fail_a 전체로 확장할 필요는
없나"는 질문에서 착수. **근거**: `_adecimal_signals` 수정은 특정 기업 패치가 아니라
`read_report_face_xbrl`(전 기업 공유 face reader)의 일반 로직이라, 애초 후보를 뽑았던
"정확히 ×10ⁿ 배수" 비율 스캔이 좁은 휴리스틱이라 놓친 케이스가 fail_a 잔여 1,062건 안에
더 있을 수 있다는 가설.

**실행**: 당시 fail_a(v3) 전체 362개사 corp_code를 뽑아(`SELECT DISTINCT corp_code FROM
face_audit WHERE source_version='v3' AND gate_status='fail_a'`) `--corp-file`로 지정,
`python -u scripts/gateb_audit.py --source v3 --corp-file <362개사> --fy-min 1999 --recheck
--no-line-audit`를 사용자 터미널에서 실행(전량재실행 47분/97개사 전례로 하니스 백그라운드
킬 위험 있어 직접 실행 요청, [[feedback-long-running-commands]]). 44,872행(362개사 전체
이력, fy≥1999) 재감사 완료, 기업오류 0.

**결과 — 순변화 0건 확정**: 재실행 후 `fail_a` 여전히 정확히 **1,062건·362개사**(recheck
전과 동일). DB 직접 재조회로 재확인(단순 로그 눈대중 아님, [[feedback-verify-against-source]]).
즉 **확장 스캔이 추가로 잡아낸 케이스는 0건** — 애초 좁은 "×10ⁿ 배수" 후보스캔이 이미 이
수정으로 고칠 수 있는 사례를 전부 찾아냈었다는 뜻(과소탐지 우려는 기각). §8-A 수정은
이걸로 **완결 확인**.

**부수 성과 — 잔여 fail_a 1,062건 필드분포 확정**(이전엔 없던 전체 breakdown):
`controlling_ni` 404 · `trade_payables` 300 · `revenue` 186 · `tax_expense` 115 ·
`dividends_paid` 36 · `cfo` 23 · `total_equity` 19 · `net_income`/`cogs` 17 · `cff` 11 ·
`inventory` 11 · `cfi` 10 · `ebt` 9 · 이하 소수(`operating_income`/`gross_profit`/
`total_assets`/`total_liabilities`/`cash`/`controlling_equity`/`ppe`/`retained_earnings`/
`current_liabilities`/`current_assets` 각 10건 미만). **`controlling_ni`(404건, 372개사에
분산)가 가장 큰 미조사 덩어리로 재확인**(§7 첫 조사 당시엔 원인 미조사로만 남겨뒀던 것,
[[std-v3-native-gate-b-plan-2026-08-11]] 참고) — trade_payables(300, §8-D 대상)보다도 크다.
`tax_expense`(115)는 이번에 처음 규모가 드러난 미조사 항목. `revenue`(186)는 fail_a
쪽인데 §8-C가 다루는 건 fail_b 쪽 증권사 revenue(2,514건)라 같은 원인인지는 미확인 —
별도 원문대조 필요.

**다음 결정 후보(§8 옵션 갱신, 아직 미착수)**: 크기순으로 `controlling_ni`(404, 원인
미조사·최대 덩어리) 조사가 §8-C/§8-D보다 우선순위가 높아질 수 있음 — 사용자 결정 대기.

---

## 10. `controlling_ni` fail_a(404건) 원인조사 완료 (2026-08-12, 읽기전용)

사용자 지시("controlling_ni 원인부터 조사해줘")로 착수. `fin2/layer3/combine.py`의
`build_merged_lines`+`_map_rows`를 직접 호출해 5개사(00112651/00105101/00112165/00110884/
00109693) 표본의 `is.controlling_ni` 원시 후보(raw candidates, 병합 전)를 뽑아 db_won/
report_won과 대조 — **5/5 전부 같은 메커니즘으로 재현**.

### 10-1. 주범(88.1%, 356/404건) — "당기순이익 귀속" vs "총포괄손익 귀속" 섹션 혼동이
`_resolve_ni_attribution` 안전장치를 우회

원문엔 '지배기업의 소유주지분'(또는 표기변형)이라는 거의 동일한 라벨이 **두 섹션**에
독립적으로 등장한다: `당기순이익(손실)의 귀속`(원하는 값)과 `총포괄손익의 귀속`(OCI
포함, 다른 개념). alias 카탈로그는 섹션 구분 없이 둘 다 `is.controlling_ni`로 정확매칭
한다. 이 모호성을 풀기 위한 안전장치(`_resolve_ni_attribution`, `combine.py:401`, 이미
`docs/plans/std_v3_controlling_ni_gap_fix_plan_2026-08-08.md` §3-2에서 신설돼있음, 순이익
항등식 `controlling_ni+noncontrolling_ni=net_income`으로 역산 판별)가 이미 존재하지만,
**`conflicts`에 걸린 경우에만 작동**하도록 설계돼있다.

**커버리지 구멍**: 두 후보(정답=당기순이익 귀속, 오답=총포괄손익 귀속)의 매핑 stage가
다르면(예: 각주번호 "(주30)" 등 접미사가 붙어 정답 쪽이 `normalized`/`fuzzy`, 오답 쪽이
`exact`) `_resolve()`(`combine.py:386-390`)의 **stage 우선순위 tiebreak가 곧바로 `exact`
쪽 값을 확정**해버려서, 애초에 `conflicts`로 넘어가지 않고 `_resolve_ni_attribution`
안전장치를 건너뛴다. 즉 8/8에 만든 방어가 "같은 stage 동률" 케이스만 잡고 "다른 stage
그림자충돌" 케이스는 못 잡는 사각지대였음이 이번에 확인됨.

세부 하위유형(404건 전체 자동분류, `_map_rows` 원시후보 스캔):
- **section_confusion_stage_masked (278건, 68.8%)**: 위 메커니즘 그대로 — 정답/오답 두
  후보가 다 존재하지만 stage 순위가 오답을 먼저 확정.
- **section_confusion_single_wrong (38건, 9.4%)**: `is.controlling_ni` 후보 자체가
  총포괄손익 쪽 하나뿐(정답 후보가 아예 이 canonical로 안 잡힘 — 10-2 참고).

### 10-2. 부차 패턴 — canonical 오매핑 (40건, 9.9%)

정답('지배기업주주 귀속 당기순이익' 등 라벨)이 `is.controlling_ni`가 아니라
`is.net_income`으로 오매핑되는 경우(00109693 FY2025 원문확인: 정답 -88,007,769,786이
`is.net_income` fuzzy 후보로 잡힘, 정작 `is.controlling_ni`엔 총포괄손익 쪽만 존재).
stage tiebreak를 고쳐도 이 40건은 안 풀림 — alias 카탈로그가 이 라벨 패턴을 애초에
잘못된 canonical로 보내는 별개 결함.

### 10-3. 소수 하위패턴 — `_reduce_conflict` shallow-depth 오작동 (12% 미분류 안에 일부 포함)

00118345(6건 전부)는 다른 메커니즘: 같은 라벨('지배기업소유주지분')이 section_path 없는
무관한 표(table_seq=1, 아마 별도 주석/부속명세)에도 중복 등장 — 두 후보 다 stage='exact'라
`_reduce_conflict`의 "얕은 depth(=합계) 우선" 휴리스틱(`combine.py:309-330`, 원래 취지는
DIRECT_MAP 총계가 하위항목보다 우선하게 하는 것)이 **section_path 없는(depth=0) 무관 표
쪽을 "총계"로 오인**해 선택. 00120030(다른 값 3종 혼재)·00124504(기재정정 케이스) 등
잔여 미분류(48건, 11.9%)는 개별성이 강해 이번 자동분류로 안 걸림 — 후속 개별확인 필요.

### 10-4. 요약 — 이 세션의 조사 범위

전부 **읽기전용**(`build_merged_lines`/`_map_rows` 직접 호출, DB/코드 미수정). 404건
자동분류 스크립트는 스크래치패드에만 존재(세션 종료 시 소실 가능, 필요시 재작성).
`section_confusion_*`(88.1%)과 `canonical_mismap`(9.9%)을 합치면 **97.9%가 하나의 근본
원인 계열**("총포괄손익 귀속 섹션의 라벨이 controlling_ni 매핑을 오염시킨다")로 수렴 —
수정 설계 시 이 계열부터 먼저 다루는 게 임팩트가 가장 큼. **수정 설계·구현은 이번 조사
범위 밖**(정책상 조사 후 자동실행 금지) — 사용자 결정 대기.

**수정 설계 문서 작성 완료(2026-08-12, 같은 날)**: 사용자 지시("수정 설계 문서부터
작성해줘")로 착수. `parser/common/account_mapper.py:167-172`에 이미 있는 "포괄손익 귀속"
가드가 이번 케이스를 못 잡는 이유도 함께 규명 — 그 가드는 **라벨 텍스트 자체**에
"포괄손익"+"지배"가 함께 있는 스타일을 겨냥한 것인데, 이번 근본원인 표본은 라벨 자체엔
"포괄손익"이 없고 OCI 구분이 `section_path`(표 상위 섹션)로만 표현돼 account_mapper
레벨에선 구조적으로 못 봄(`section_path`는 combine.py 후보 dict에만 실림) — **수정은
account_mapper 가 아니라 `fin2/layer3/combine.py::_resolve()`가 맞는 위치**임을 확정.
설계 = `docs/plans/std_v3_controlling_ni_oci_section_fix_design_2026-08-12.md`: Phase 1
(`_resolve()`에 OCI-섹션 구조적 사전필터, 기존 trust-account 필터와 동일 코드 패턴 재사용,
404건 중 316건=78.2% 대상, 그 중 278건은 완전정정·38건은 오염제거) + Phase 2(canonical_mismap
40건, account_mapper 가드 별도설계 필요)·Phase 3(00118345류 shallow-depth 오작동)은 범위밖
분리 + §8-A와 동일한 회귀검증 방법론(유닛테스트+404건 재현+무작위 PASS 광역재검증) 명시.
**설계만 완료, 코드 전혀 미착수** — 실행은 별도 승인 대기.
