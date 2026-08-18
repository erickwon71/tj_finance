# `standard_financials` 뷰 조인 결함 — 적용 전/후 기록 (2026-08-18)

> 설계: `docs/plans/gateb_view_source_version_join_fix_design_2026-08-17.md`
> 마이그레이션: `2026_08_standard_financials_view_source_version` (`collector/db.py`)

## P0-2. 적용 전 기준선 (스냅샷)

```sql
SELECT count(*) FROM standard_financials;
-- 565,940

SELECT n, count(*) FROM (
  SELECT corp_code,fiscal_year,fiscal_period,statement_type,version, count(*) n
  FROM standard_financials GROUP BY 1,2,3,4,5) t GROUP BY 1 ORDER BY 1;
-- 1 |  76,770   (감사행 v2/v3 중 하나만 있는 키)
-- 2 | 244,585   (v2·v3 감사행이 둘 다 붙어 뷰에 2번 나오는 키)
```

08-17 설계서 스냅샷(565,785 / 244,439)과 거의 동일 — 데이터가 하루치 늘었을 뿐 결함 자체는
그대로 재현됐다. (참고: 설계서의 §3-D "은닉 394행" 수치는 트랙①(업종 파생 revenue, R32)
적용 **전** 값이다. ①이 그 사이 fail_a 412→239로 줄여, 아래 dry-run 검증에서는 214행으로
갱신됐다 — 아래 참고.)

## P0-4. 사전 dry-run 검증 (실제 뷰 교체 전, `standard_financials_dryrun` 임시 뷰로 대조)

**B. 중복 소멸**

```
dry-run 총 행수     321,141
등장 1회            321,141   ← 전부. n=2 는 0건.
```

**C. 무손실** — 적용 전 키 집합 ⊇ 적용 후 키 집합

```
old − new (사라지는 키)   214건
new − old (새로 생기는 키)  0건   ← 통과
```

214건 전부 v3 브랜치이고, 전부 `face_audit`의 v3 감사결과가 `fail_a`인 키였다(검산: v3
쪽인데 매칭되는 v3 `fail_a` 행이 없는 케이스 0건). v2 브랜치에서 새로 사라진 키는 0건.
→ 설계서 §3-D 가 예상한 "정확한 fail_a 게이트가 되살아나며 은닉되는 행"과 정확히 부합.
(예상치가 394→214로 줄어든 건 결함이 아니라, 그 사이 트랙①이 fail_a 모집단 자체를
412→239로 줄였기 때문 — 마스터 문서 §1 순위3 참고.)

**D. `gate_b_status` 정합**

```
dry-run 뷰의 gate_b_status ≠ 매칭되는 v3 face_audit.gate_status 인 행: 0건
```

**E. 다운스트림 스모크(대표 사례)**

```
삼성전자(00126380) 2024FY 연결 — 적용 전 2행(완전 동일 값 중복) → dry-run 1행
```

## P0-3. 실제 적용

`init_db()`(마이그레이션 러너)로 `2026_08_standard_financials_view_source_version` 적용.
`CREATE OR REPLACE VIEW` 단일 트랜잭션, 데이터 변경 없음.

## P0-4(사후). 실제 뷰 재검증

아래는 마이그레이션 적용 **후** `standard_financials`(실물 뷰) 대상 재실행 결과다.
`init_db()`로 `2026_08_standard_financials_view_source_version` 1건 신규 적용 확인
(로그: "마이그레이션 1건 신규 적용 완료 (전체 95건 중 스킵 94건)").

```
총 행수                 321,141    ← dry-run 과 정확히 일치
중복(n≥2) 키             0건       ← 전부 n=1
gate_b_status 불일치      0건       ← v3 face_audit 와 100% 정합
삼성전자 2024FY 연결      1행       ← 적용 전 2행(동일값 중복) 해소
```

dry-run 예측치와 실제 적용 결과가 완전히 일치 — §6 검증 규약 B/D/E 통과.

## 결론

- 증상①(2배 중복) 해소: 565,940 → 321,141행 (dedup, 손실 없이 감사행만 1:1 대응)
- 증상②(등급 오귀속) 해소: `gate_b_status` 가 자신이 표시하는 체인(v3/v2)의 감사결과만 반영
- 증상③(`fail_a` 게이트 우회) 해소: v3 `fail_a` 214건이 다시 정상적으로 은닉됨
  (당초 설계서 추정 394건보다 적은 건, 그 사이 트랙①이 fail_a 모집단을 412→239로
  줄였기 때문 — 데이터 오류가 아니라 앞선 트랙의 정상적 효과)
- P0-5(`app/data/trust.py` source_version 한정)·P0-6(회귀 테스트)는 별도 커밋으로 이어서 진행.
