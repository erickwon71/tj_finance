# ③ Gate B 감사 성능 — 실측 기반 설계 (2026-08-17)

> **착수 순위 2** (`gateb_view_source_version_join_fix_design_2026-08-17.md` §9).
> **측정 도구**: `scripts/profile_gateb_audit_2026-08-17.py`(읽기 전용, `--no-commit`).
> **★이 문서는 "36분/기업" 이라는 기존 서술을 실측으로 정정한다** — §1-B.

---

## 0. 이 문서가 하는 일 (3줄 요약)

1. **정정**: "corp 1개 36분+ → 전수 재감사 불가" 는 **실측으로 재현되지 않는다.** 실제
   측정값은 **31.4초**(00101044, 91필링). 전수 재감사는 기존 5-shard 러너로 **오늘도
   약 3시간**이면 끝난다 — 물리적 불가가 아니었다.
2. 그럼에도 병목은 명확하고 **고칠 값어치가 크다**: 시간의 **40%가 `account_mapper._fuzzy_match`
   가 alias 사전을 매 호출마다 재정규화**하는 데 쓰인다(`re.sub` 1,519만 회). 이건 이미
   init 에서 계산해 둔 값의 재계산이다 — **순수 낭비**.
3. 두 가지 수정(사전계산 + 파싱 트리 캐시)으로 **31.4초 → 약 12초(2.6배)**. 부수효과로
   **계층3 재빌드(`combine.py`)도 같이 빨라진다** — 같은 mapper 를 쓴다.

---

## 1. 측정

### 1-A. 조건

```
python scripts/profile_gateb_audit_2026-08-17.py --corp 00101044 --source v3
corp=00101044(에이프로젠바이오로직스) · std_v3 130행 · 고유 rcept 91 · 원문 131MB
결과: wall 31.4s · status={'pass':111,'pending':19} · errors 0
```

부수 실측:

| 항목 | 값 |
|---|---|
| face reader, 11.4MB 필링 1건 end-to-end | 0.78s |
| NAS(SMB, `//192.168.0.96`) 콜드 읽기 | 50 MB/s |
| SD 미러(`/Volumes/dart_data`) | 93 MB/s |
| 00101044 원문 총량 | 131MB / 91파일 / 평균 1.44MB |

→ I/O 는 콜드여도 **131MB ÷ 50MB/s ≈ 2.6초**. 즉 이 작업은 **I/O 바운드가 아니라 CPU
바운드**다. NAS→SD 전환은 이 트랙의 해법이 아니다.

### 1-B. ★ 기존 서술 정정

`docs/PARSING_RULES.md` R31 주석과 그에 근거한 이전 조사 서술은 *"corp 1개(00101044)가
36분+ 걸려 전수 재감사가 불가능"* 이라고 적고 있다. **재현되지 않는다 — 실측 31.4초.**

- 원인 미상. 콜드 NAS·5-shard 동시 실행 시 SMB 경합·당시 다른 코드 경로 등이 후보이나
  **확인되지 않았다.** 짐작으로 적지 않는다.
- 실무적 결론: **"전수 재감사 불가" 라는 전제를 폐기**한다. 그 전제 위에서 "표본으로
  검증하고 트랙 종료 → 나중에 잔여 재등장" 이라는 순환을 정당화해 왔으나, 전수 재감사는
  이미 실행 가능했다(§4-B).
- 단, 이 측정은 **페이지 캐시가 따뜻한 상태**였다(직전 프로브에서 같은 파일들을 읽음).
  콜드 재측정을 Phase 0 에 둔다 — 다만 위 I/O 상한 계산상 결론이 뒤집힐 여지는 작다.

### 1-C. 프로파일 (cumulative, 상위)

```
31.386  audit_corp
 31.011    face_of                     (455회 호출, 61개 파일 — 캐시는 이미 동작 중)
 31.010      read_report_face_tracked  (61회)
 20.688        read_report_face_text   (55회)   ← 66%
 14.433          _read_table (296)
 14.166            account_mapper.map (10,760)
 13.992              _fuzzy_match (4,065)              ← ★ 44.6%
 12.453                normalize_account_name (1,011,495)
 13.736                  re.sub (15,194,456)           ← ★ 실질 병목
  1.024                jellyfish.jaro_winkler (985,201)
 13.386        _parse_xml_file (116회 / 61파일 = 1.90배)  ← ★
 10.198          sanitize_dart_xml
  4.285            _escape_attr_quotes (7,972,715)
  9.936        read_report_face_xbrl (61회)
  0.657          _adecimal_signals
  0.403          _ni_attribution_structural_candidates
  0.294        audit_std_row (130회)                     ← 감사 판정 자체는 1% 미만
```

**감사 로직(판정)은 비용이 아니다.** 전부 **읽기 전처리**에서 나온다.

---

## 2. 병목 3종

### B1. `_fuzzy_match` 가 alias 사전을 매 호출마다 재정규화 — 12.45s (40%)

`parser/common/account_mapper.py:212-265`:

```python
for code, aliases in self._aliases_by_code.items():
    for alias in aliases:
        alias_norm = normalize_account_name(alias)   # ★ 매 호출마다 전 alias 재계산
```

`normalize_account_name()`(`parser/common/amount_normalizer.py:386`)은 alias 하나당
`re.sub` 를 **약 15회** 돌린다. 퍼지매칭 **4,065회**를 위해 정규화가 **1,011,495회**
(호출당 249회), `re.sub` 가 **15,194,456회** 실행된다.

**이 값은 이미 계산돼 있다.** `_build_index()`(`account_mapper.py:66-104`)가 같은
`normalize_account_name(alias)` 를 alias 전체에 대해 **이미 두 번** 돌려
`self._normalized` / `self._normalized_by_prefix` 를 만든다. 다만 **code→alias 단위로는
보관하지 않아** `_fuzzy_match` 가 다시 계산한다.

> `normalize_account_name` 은 **인자에만 의존하는 순수 함수**이고 alias 집합은 init 이후
> 불변이다 → 사전계산은 **정의상 결과가 동일**하다(§6-A 에서 증명한다).

### B2. 같은 파일을 1.90회 파싱 — 약 6.7s

`_parse_xml_file` 116회 / 61파일. `read_report_face_tracked`(`face_audit.py:634-641`)가
`read_report_face_xbrl` 로 한 번 파싱하고, `_supplement_with_text` → `read_report_face_text`
가 **같은 파일을 다시 열어 다시 파싱**한다. 파싱 비용의 **76%가 `sanitize_dart_xml`**
(`_escape_attr_quotes` 797만 회)이라 재파싱이 특히 비싸다.

### B3. 텍스트 보충이 61건 중 55건에서 발동 — 구조적

`_supplement_with_text`(`face_audit.py:595-597`)는 Track A 가 BS·IS·CF 를 모두 커버하면
건너뛴다. 이 기업은 **90%(55/61)** 에서 발동했다 = Track A 커버리지가 낮은 구형 필링이
많다는 뜻. **이건 결함이 아니라 데이터 특성**이다 — B2 를 고치면 비용의 절반이 사라지므로
B3 자체는 손대지 않는다(§7).

---

## 3. 설계

### Fix 1 — alias 정규화 사전계산 (B1)

`_build_index()` 에서 code→[(alias, alias_norm)] 을 만들어 두고 `_fuzzy_match` 가 그것을 읽는다.

```python
# account_mapper.py::_build_index()
# Precompute the normalized form of every alias once. _fuzzy_match() used to call
# normalize_account_name() on the entire alias dictionary on EVERY map() call --
# 1,011,495 calls / 15.2M re.sub for just 4,065 fuzzy matches (measured 2026-08-17,
# docs/plans/gateb_audit_performance_design_2026-08-17.md B1). normalize_account_name()
# is pure and the alias set is immutable after init, so this is a semantics-preserving
# memoization, not a behavior change.
self._aliases_norm_by_code: dict[str, list[tuple[str, str]]] = {
    code: [(a, n) for a in aliases if (n := normalize_account_name(a))]
    for code, aliases in self._aliases_by_code.items()
}
```

> ⚠ Python 3.9 환경이다(`.venv` 실측). walrus 는 3.8+ 라 사용 가능하나, 프로젝트 스타일에
> 맞춰 명시 루프로 쓸지는 구현 시 결정.

**부수효과(의도된 이득)**: `get_mapper()` 소비자는 감사기만이 아니다 —
`fin2/layer3/combine.py:1188`(**계층3 표준화**), `fin2/extract/pdf.py:192`(계층2 PDF)도
같은 mapper 를 쓴다. 따라서 **std_v3 전량 재빌드도 함께 빨라진다.**
동시에 이것이 **최대 리스크**이기도 하다 → §6-A 의 동치성 증명이 필수.

### Fix 2 — 파싱 트리 캐시 (B2)

파싱 결과(`root`)를 **한 파일당 1회**로 줄인다. 두 가지 층위 중 **(b)를 채택**한다.

| 안 | 내용 | 판단 |
|---|---|---|
| (a) `_parse_xml_file` 에 전역 LRU | 가장 간단 | ❌ `lxml` 트리는 무겁고(11MB 파일 → 수백 MB), 파서 공용 함수라 전 파이프라인 메모리에 영향 |
| **(b) 감사 reader 내부 스코프 캐시** | `read_report_face_tracked` 가 `root` 를 1회 파싱해 `read_report_face_xbrl` / `read_report_face_text` 에 **주입** | ✅ 수명이 한 파일 처리 구간으로 한정 — 메모리 상한 명확, 파서 공용 코드 무변경 |

구현: 두 reader 에 `root: etree._Element | None = None` 선택 인자를 추가하고, 주어지면
재파싱하지 않는다. 기존 호출부(단독 호출)는 그대로 동작한다.

> `_supplement_with_text` 는 `file_path` 만 받으므로(`face_audit.py:580`) 시그니처에
> `root` 를 함께 넘기도록 확장한다.

### Fix 3 — (보류) 트리 순회 통합

`_adecimal_signals`(0.66s) + `_ni_attribution_structural_candidates`(0.40s) + 본 루프가
트리를 3회 순회하지만 **합쳐 1.1초(3.5%)** 뿐이다. **하지 않는다** — 이득 대비 회귀
위험(두 함수 모두 회귀 이력이 많다)이 크다.

---

## 4. 예상 효과

### 4-A. 기업 1개

```
현재                       31.4s
 Fix 1 (정규화 사전계산)   -12.4s  →  19.0s
 Fix 2 (파싱 1회로)         -6.7s  →  12.3s
                                      ≈ 2.6배
```

### 4-B. 전수 재감사 시간표 (2,538개사, corp당 평균 59 rcept / 중앙값 66)

00101044 는 91 rcept 로 평균 이상 → rcept 비례 환산 시 평균 기업 ≈ 20.4초.

| | 단일 프로세스 | 5-shard (`run_gateb_audit_parallel.sh`) |
|---|---|---|
| **현재** | ≈ 14.4시간 | **≈ 2.9시간** |
| **Fix 1+2 후** | ≈ 5.6시간 | **≈ 1.1시간** |

**핵심**: 전수 재감사는 **지금도 하룻밤이면 끝난다.** 수정 후에는 **점심시간에 끝난다** —
"고칠 때마다 전수로 확인" 이 일상 작업이 된다. 이것이 반복 루프를 끊는 실제 지렛대다.

---

## 5. Phase

| Phase | 내용 | 산출물 |
|---|---|---|
| **0** | 콜드 캐시 재측정(§1-B 단서) + 대형 기업 1개(rcept 99, 최대) 추가 측정 | 측정 로그 |
| **1** | Fix 1 구현 + **§6-A 동치성 증명** | `parser/common/account_mapper.py` |
| **2** | Fix 2 구현(`root` 주입) | `fin2/audit/face_audit.py` |
| **3** | 재측정 — 통과선 = 00101044 **15초 이하** | 프로파일 로그 |
| **4** | 전수 재감사 1회(5-shard) + 결과를 ①·② 의 기준선으로 확정 | `logs/gateb_shard_*.log` |
| **5** | `docs/PARSING_RULES.md` 부록 C 등재 + R31 주석의 "36분" 서술 정정 | 문서 |

> Phase 4 는 사용자 실행(장시간) — [[feedback-long-running-commands]].

---

## 6. 검증 규약

### A. ★ Fix 1 동치성 증명 (최우선 — 계층3에 영향이 가는 유일한 변경)

성능 최적화가 **매핑 결과를 1건도 바꾸지 않음**을 기계적으로 증명한다.

```
① 실제 라벨 코퍼스 추출: report_lines.label_raw DISTINCT 전량
   (+ fs_section 조합) — 표본이 아니라 전수
② 수정 전/후 mapper 로 각각 map(label, fs_section) 실행
③ (account_code, confidence, stage) 3튜플이 전건 동일한지 대조
통과선: 불일치 0건. 1건이라도 나오면 Fix 1 철회
```

이 대조 스크립트는 `scripts/verify_account_mapper_equivalence_2026-08-17.py` 로 커밋한다
(재실행 가능·읽기 전용).

### B. Fix 2 동치성

같은 61개 필링에 대해 수정 전/후 `read_report_face_tracked()` 의 **(track, FaceLine 집합)**
이 완전히 동일한지 대조. 통과선: 불일치 0.

### C. Gate B 결과 불변

Phase 4 전수 재감사 결과가 **성능 수정만으로는 등급을 바꾸지 않아야** 한다.

```
통과선: pass/fail_a/fail_b/pending 행별 등급 전이 = 0
```

> ①(파생 revenue)을 이미 적용한 뒤라면 그 변화분은 ① 의 기대 변화와 일치해야 한다 —
> 두 트랙을 **같은 재감사 실행에 섞지 말 것**(원인 분리 불가). 순서: ③ 검증 → ① 적용 → ① 검증.

### D. 회귀

`pytest tests/ fin2/tests/` — 549 기준선 유지([[feedback-pytest-scope-raw-report-symlink]]).
특히 `test_account_mapper_ebt.py` / `test_account_mapper_opinc.py` 가 Fix 1 의 1차 방어선.

### E. 계층3 무영향 확인

Fix 1 은 `combine.py` 경로에도 걸린다. std_v3 **재빌드는 하지 않되**, 표본 기업 5개에 대해
`combine._map_rows()` 결과가 수정 전후 동일한지 대조한다(A 가 통과하면 논리적으로 따라오나,
공용 컴포넌트 변경이므로 실측으로도 확인 — [[feedback-consider-pipeline]]).

---

## 7. 리스크

| 리스크 | 대응 |
|---|---|
| **Fix 1 이 계층3 표준화 값을 바꾼다** | §6-A 전수 동치성 증명이 게이트. 불일치 1건이라도 철회. `map()` 의 3튜플 전체를 비교(코드만이 아니라 confidence·stage 까지 — stage 는 R16/R20/R21 의 stage-rank 로직 입력이라 특히 중요) |
| Fix 2 의 `root` 재사용으로 **트리 변형 부작용** | 두 reader 는 트리를 읽기만 한다(수정 없음)는 것을 코드 리뷰로 확인 후 적용. §6-B 가 실측 방어선 |
| 메모리 증가 | Fix 2 는 파일 1개 수명 스코프. 5-shard 동시 실행 시 최대 5×(최대 파일 트리). 최대 파일 7.9MB → 문제 없음 |
| §1-B 의 "36분" 이 특정 조건에서 재현될 수 있다 | Phase 0 콜드 측정으로 확인. 재현되면 그 조건을 본 문서에 추가하고 설계를 보강 |
| 성능 수정이 감사 **정확도**를 바꾼다 | §6-B·C 가 이중 방어선. 성능 트랙에서 판정 로직은 **한 줄도 건드리지 않는다** |

---

## 8. 미결 / 범위 밖

- `_fuzzy_match` 의 **알고리즘**(전 alias 선형 스캔 + Jaro-Winkler)은 그대로 둔다. 인덱싱
  구조를 바꾸면 매핑 결과가 달라질 수 있어 성능 트랙의 범위를 넘는다. Fix 1 이후에도
  느리면 별도 트랙.
- `sanitize_dart_xml`(`_escape_attr_quotes` 797만 회)의 자체 최적화는 하지 않는다 —
  파서 공용 경로이고 R2/R4 계열 회귀 이력이 있다. Fix 2 로 **호출 횟수를 절반**으로
  줄이는 것으로 충분.
- `face_line_audit`(Phase B 라인 대조)의 유용성 자체 — `n_missing` 86%로 사실상 미작동.
  이건 성능이 아니라 `fact_v2` 커버리지 문제라 별도 판단 필요(②에서 다룸).
- SD 미러 활용은 **채택하지 않는다**(§1-A: I/O 바운드 아님). 콜드 대량 스캔이 필요한
  다른 작업에는 여전히 유효([[feedback-bulk-read-use-sdcard]]).

---

## 9. 다음 문서

`gateb_evidence_grade_redesign_*.md`(②) — fail_a/fail_b 를 리더 트랙이 아닌 **증거강도**로
재정의하고, 현재 기록되지 않는 **pass 근거를 계측**한다(`gateb_audit.py:213-218` — pass 는
reason 을 남기지 않아 "±1 관용/폴백으로 통과" 와 "정확 일치" 를 구분할 수 없다).
