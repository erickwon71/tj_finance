# P3-1 Track D fail_b 패턴 A/B 수정 설계 (2026-08-20)

**상태: 설계만, 구현 미착수 — 사용자 승인 대기** (CLAUDE.md 정책: 계획 문서 작성 후
자동실행 금지)

**전제 문서**: [`p3-1-trackd-failb-rootcause-2026-08-20.md`](../../.claude 메모리, 이 문서와
동일 세션) — 전사 xbrl_zip-only 777개사 Track D(R38) 재감사에서 새로 노출된 fail_b
774건을 `fail_tracks[field]=="D"` 기준으로 정밀 분리(진짜 541행/239개사) 후, 대표 표본을
원문(zip)과 직접 대조해 두 개의 독립된 원인으로 확정한 결과를 이어받는다.

| | 패턴 A(BS 총계 3행) | 패턴 B(trade_payables) |
|---|---|---|
| 규모(xbrl_zip-only 표본) | 541행 중 684개 필드(총계 3종) | 232건 |
| **전사 영향범위(2026-08-20 실측, §1.5-4)** | **156개사/756건**(R34 기처리 302건 제외) — 이 중 **18개사/37건은 xbrl_zip 밖**(Track A/B 커버리지에도 존재) | 미측정(패턴 B는 수정 불필요라 전사스캔 불필요) |
| db(std_v3) 상태 | **틀림**(정정 전 값 잔존) | **맞음**(원본의 협의값을 정확히 채택) |
| 원인 위치 | `fin2/layer3/combine.py::_resolve()` | `fin2/audit/face_audit.py::read_report_face_xbrl_zip()`(Track D) 설계 자체의 한계 |
| 조치 | **수정 필요**(본 문서 §1) | **수정 불필요**, 문서화만(본 문서 §2) |

---

## §1. 패턴 A — BS 총계 라벨-표현 드리프트가 정정 전 값을 되살리는 결함

### 1.1 원인 재요약 (원문대조 완료, 00103130/플레이그램 2017 Q1)

| 필링 | 라벨 | 값 |
|---|---|---|
| 원본(`20170515004380`, 2017-05-15) | "**자산총계**" | 68,523,148,315 (=db) |
| [기재정정](`20180322000560`, 2018-03-22) | "**자산**" | 68,145,914,314 (=Track D 재파싱, 원문 검산상 정확한 최신값) |

`account_mapper.map()` 실측: `"자산총계"→stage=exact`, `"자산"→stage=fuzzy` (둘 다
canonical=`bs.total_assets`). `_resolve()`의 단계우선(`_STAGE_RANK`: exact=3 > fuzzy=1)
타이브레이크가 **정정으로 갱신된 값이 아니라 정정 전(exact) 값을 채택**한다.

### 1.2 왜 오늘 이미 들어간 R34 수정이 이 케이스를 못 잡는가

`combine.py::_resolve()`에는 오늘(2026-08-20) 이미 R34로 매우 비슷한 결함이 고쳐졌다
(`docs/PARSING_RULES.md` R34, 고려아연 00102858 사례) — `build_merged_lines()`의 셀 키
(`statement,basis,col_index,section_path,label_raw`)가 정정본의 표 재렌더링으로
`section_path`가 미묘하게 바뀌면(래퍼 한 겹 추가 등) 같은 항목의 두 셀이 "다른 셀"로
살아남아 델타패치가 무력화되는 문제였다. R34는 `industry_profiles.norm()`(번호·각주·
공백 정규화)으로 라벨을 정규화해 묶은 뒤, 그 그룹 안에 `amended=True` 후보가 있으면
`amended=False`(base) 후보를 버리는 방식으로 고쳤다.

**R34의 `norm()`은 "자산총계"와 "자산"을 같은 그룹으로 묶지 못한다** — `norm()`이
제거하는 건 번호 접두사·괄호·각주 접미사뿐이고, "총계"라는 단어 자체는 지우지 않는다
(실측: `norm("자산총계")=="자산총계"`, `norm("자산")=="자산"`, 서로 다른 문자열).
즉 이번 패턴 A는 R34가 고친 **"표기 잡음(formatting) 드리프트"**가 아니라
**"단어 자체가 바뀌는(wording) 드리프트"**라서 R34의 그룹핑을 그냥 통과해버린다.
R34 자체 문서("미조치 범위")에도 "이 패턴이 전수 잠복해 있을 가능성은 미확인"이라고
정직하게 남겨져 있었는데, 이번이 바로 그 잠복 사례를 실측으로 확인한 것.

### 1.3 수정 설계

#### 옵션 검토

| 옵션 | 내용 | 채택여부 |
|---|---|---|
| **A(권장)** | `_BS_GRAND_TOTAL`(`bs.total_assets`/`bs.total_liabilities`/`bs.total_equity`) 3개 canonical에 한해, R34의 그룹핑 키를 `norm(label)`이 아니라 **canonical 전체**(=이미 `cands[c]`로 canonical 단위 분리돼 있으므로, 사실상 "라벨 무시하고 그 canonical의 모든 후보를 한 그룹으로")로 넓힌다. | **채택** |
| B | `industry_profiles.norm()` 자체를 고쳐 "총계"/"total" 접미사를 전역적으로 제거 | 기각 — `norm()`은 `is.revenue` grand-total 매칭 등 다른 곳에서도 쓰임. 전역으로 "총계" 제거 시 "유동자산총계"(중간 소계) vs "유동자산"(같은 걸 가리키는 게 아닐 수 있음, 계층상 다른 개념)까지 잘못 묶일 위험 — 파급범위가 넓고 검증이 어려움 |
| C | `account_mapper`가 이미 두 라벨을 같은 canonical로 매핑한다는 사실을 이용해, **전체 canonical**(BS 총계 3종에 국한하지 않고 모든 계정)에 대해 그룹핑 키를 canonical 기준으로 넓힘 | 기각(이번 범위 밖) — 더 근본적이지만 다른 400여 개 canonical 전체에 영향, 이번에 관측된 건 BS 총계 3종뿐이라 과잉수정. 향후 유사 사례가 더 나오면 일반화를 재검토 |

**옵션 A가 안전한 이유**: `bs.total_assets`/`bs.total_liabilities`/`bs.total_equity`는
구조적으로 **한 필링·basis 안에 "진짜" 값이 하나뿐이어야 하는 총계**다(중간 소계나
같은 canonical의 여러 정당한 하위 항목이 공존할 수 있는 일반 계정과 다름). 그래서
"라벨이 달라도 같은 canonical이면 같은 개념"이라는 가정이 이 3종에 한해서는 항상 안전
하다 — `_BS_GRAND_TOTAL`이 신탁계정 가드(`_trust_account_table_seqs`)에서 이미 같은
전제로 특별취급되고 있는 것과 동일한 논리.

#### 상세 구현 스케치 (`fin2/layer3/combine.py::_resolve()`)

```python
# BEFORE (현재, R34):
by_label: dict[str, list[dict]] = defaultdict(list)
for r in rows:
    by_label[_norm_label(r.get("label_raw"))].append(r)

# AFTER (제안):
by_label: dict[str, list[dict]] = defaultdict(list)
for r in rows:
    # ★[신규] BS 총계 3종은 라벨 표현이 통째로 바뀌어도(예: "자산총계"→"자산") 같은
    # 개념이라는 게 구조적으로 보장된다(한 필링에 "진짜" 총계는 하나뿐) — R34의
    # norm(label) 그룹핑은 표기 잡음(각주/공백)만 흡수하고 단어 자체가 바뀌는 경우는
    # 못 묶는다(00103130/플레이그램 2017Q1 실측, "자산총계"→"자산").
    # canonical 이 이미 이 loop 진입 시점에 c 로 고정돼 있으므로(cands 는 canonical
    # 단위 dict), 이 3종에 한해 라벨 무시하고 전부 한 그룹으로 취급해도 안전하다.
    key = "\0GRAND_TOTAL" if c in _BS_GRAND_TOTAL else _norm_label(r.get("label_raw"))
    by_label[key].append(r)
```

**순서 안전장치(중요)** — 현재 코드는 `by_label`(R34) 그룹핑이 **먼저** 돌고, 신탁계정
제외(`trust_seqs` 필터)가 **그다음**이다. 옵션 A로 그룹 범위를 "라벨 무시, canonical
전체"로 넓히면, 신탁계정의 "자산총계"(별개 하위statement, 정당하게 `자산==부채`)가
실제 재무제표의 "자산총계"와 같은 그룹에 섞여 들어갈 위험이 R34 때보다 커진다(R34는
라벨이 같아야 묶였지만 이제는 라벨이 달라도 묶이므로). **따라서 `trust_seqs` 필터를
`by_label` 그룹핑보다 먼저 적용하도록 순서를 바꿔야 한다** — 신탁계정 후보를 먼저
`rows`에서 제거한 뒤에 그룹핑하면 이 위험이 사라진다:

```python
# 순서 변경: trust_seqs 필터를 by_label(R34) 루프보다 앞으로 이동
if c in _BS_GRAND_TOTAL and trust_seqs:
    filtered = [r for r in rows if r.get("table_seq") not in trust_seqs]
    if filtered:
        rows = filtered

by_label: dict[str, list[dict]] = defaultdict(list)
for r in rows:
    key = "\0GRAND_TOTAL" if c in _BS_GRAND_TOTAL else _norm_label(r.get("label_raw"))
    by_label[key].append(r)
# ... (R34 stale-drop 로직은 그대로)
```

### 1.4 안전성 검토(edge case)

- **값이 같은 경우(무해)**: 00103130의 `total_liabilities`("부채총계" vs "부채", 둘 다
  12,127,501,450)처럼 두 라벨의 값이 우연히 같으면 `len({값}) < 2` 가드에 걸려 그룹이
  그냥 스킵된다 — 기존 동작과 동일, 회귀 없음.
- **amended 후보가 아예 없는 경우(무해)**: 정정 이력이 없는 필링은 애초에 `amended=True`
  후보가 없으므로 `any(g.get("amended") ...)` 가드에서 스킵 — 기존 depth-우선 로직이
  그대로 담당(변경 없음).
- **신탁계정 오염(위 순서 변경으로 해소)**.
- **정정이 여러 번(다단 amend_chain)인 경우**: `build_merged_lines()`가 이미 chrono
  순서로 순차 오버레이하므로 최종 `amended=True` 후보는 항상 "가장 최근" 값 — 옵션 A는
  이 provenance를 그대로 신뢰한다(새로 만드는 가정 없음).

### 1.5 검증 계획

1. **단위 회귀 테스트** — `fin2/tests/test_combine_amended_label_depth.py`(R34 테스트
   파일)에 이번 케이스 추가:
   ```python
   def test_amended_wording_drift_wins_over_stale_exact_label():
       # 00103130/플레이그램 2017Q1 실측 재현 — "자산총계"(exact,정정전) vs
       # "자산"(fuzzy,정정후)이 norm() 으로는 안 묶이는 경우.
       cands = {
           "bs.total_assets": [
               _row(68_523_148_315, "exact", "자산총계", None, amended=False),
               _row(68_145_914_314, "fuzzy", "자산", None,
                    amended=True, amended_by="20180322000560"),
           ],
       }
       confirmed, conflicts = _resolve(cands)
       assert confirmed["bs.total_assets"] == 68_145_914_314
   ```
   + 신탁계정 비오염 확인 테스트(같은 canonical, 다른 table_seq, `trust_seqs`에 포함된
     후보가 그룹에 안 섞이는지) 1종 추가.
2. **표본 재현** — 00103130 2017 Q1/H1/Q3 6개 필링 `build_std_v3.py` 재생성 후
   `gateb_audit.py --source v3 --corp 00103130 --recheck --no-commit` → pass 전환 확인.
3. **xbrl_zip-only 777개사 회귀** — `--recheck --no-commit`으로 fail_a 신규 발생 0건인지,
   기존 pass였던 행이 안 바뀌는지(스냅샷 비교, [[gateb-full-reaudit-is-required-to-close]]
   원칙) 확인.
4. **영향범위 사전 측정 — 완료(2026-08-20, 같은 세션)**. `build_merged_lines()`+
   `_map_rows()`를 BS 전용으로 경량 재구현해 std_v3 전체 (corp,fy,period) 151,961건을
   전수 스캔(순수 DB조회, zip 재파싱 없음 — 약 17분 소요). "같은 (corp,fy,period,basis)의
   BS 총계 3종 candidate가 2개 이상·값이 다르며·`amended=True`가 있는" 케이스 1,058건
   (218개사) 발견. 이 중 R34(오늘 이미 반영, `norm(label)` 그룹 내부에서 이미 값충돌이
   보이는 경우)가 이미 정확히 처리 중인 302건을 제외하면, **이번 신규 수정이 실제로
   새로 고치는 건 756건/156개사**(canonical별: total_assets 280·total_equity 266·
   total_liabilities 210).

   **결정적으로**, 이 756건 중 **138개사(719건)는 xbrl_zip-only 777사 안**(=Track D
   재감사로 이미 알려진 대상)이지만, **18개사(37건)는 그 밖** — 즉 XML로 정상 추적되는
   Track A/B 커버리지 기업에서도 이 결함이 존재함을 실측으로 확인(회계연도 2004~2025
   전 구간 분포). "Track A/B/C도 동일 결함 노출 가능"이라는 가설이 참으로 확정됐다 —
   **패턴 A는 Track D 트랙 자체와 무관한 std_v3 전역 결함**이며, xbrl_zip-only 777사
   재감사 반영 여부와 독립적으로 다뤄야 한다.

   재현 스크립트: `scan_pattern_a_impact.py`(세션 스크래치, repo 미포함 — 재실행 시
   재작성 필요, 본 문서 부록 A에 핵심 로직 보존).
5. **`pytest tests/ fin2/tests/` 전체 스위트** — 기존 무관 실패 1건
   (`test_lxintl_facility_table_dropped`) 외 회귀 없는지 확인.

### 1.6 백필 필요성 (범위 확정, 2026-08-20)

`std_financials_v3`는 `built_at` 컬럼으로 언제 만들어졌는지 추적된다. 코드 수정은
**향후 재생성분에만 자동 반영**되고, 이미 저장된 값은 영향받은 (corp,fy,period,basis)를
`build_std_v3.py`로 **별도 소급 재생성**해야 한다 — R34도 동일 원칙으로 6개사만 갱신하고
"전수는 미조치"로 남겼다.

§1.5-4 실측 기준 백필 대상 = **156개사 / 756건**(R34가 이미 처리한 302건 제외). 이 중
138개사(719건)는 xbrl_zip-only 777사와 겹치므로 그 백필과 통합 진행 가능하고, 나머지
**18개사(37건)는 완전히 별개**(Track A/B 커버리지, xbrl_zip과 무관) — 이 18개사는
xbrl_zip-only 백필 작업과 무관하게 반드시 별도로 포함해야 빠뜨리지 않는다.
`docs/runbook_new_parser_pipeline_integration.md` 절차(②소급 백필은 자동 아님, 수동)
적용 대상 — 대상 corp 목록은 §1.5-4 스캔 결과(`pattern_a_impact_scan.json`, 세션
스크래치)에서 뽑아 재생성 스크립트에 넘기면 됨.

### 1.7 위험도 평가

**낮음~중간.** 순수 로직 확장(3개 canonical 한정, 값이 다르고 amended 후보가 있을 때만
발동)이라 국소적이지만, `_resolve()`는 Gate B 판정의 핵심 경로라 전사 재감사(§1.5-3~5)
없이는 병합 불가 — [[gateb-full-reaudit-is-required-to-close]] 원칙 그대로 적용. 실측
스캔(§1.5-4)으로 영향범위가 156개사/756건으로 유한하게 확정됐고 canonical 3종에 국한된
좁은 트리거 조건이라, 애초 우려했던 "예측불가한 광범위 파급"은 아닌 것으로 확인.

---

## §2. 패턴 B — trade_payables 협의값, 수정 불필요

### 2.1 원인 재요약 (원문대조 완료, 00107987·00112651)

| 필링 | "매입채무" 표기 | 값 |
|---|---|---|
| 원본 | "매입채무 및 기타(유동)채무"(광의, 부모) **+ "단기매입채무/매입채무"(협의, 자식)** | 광의 80,992,526,676 / **협의 39,217,873,634(=db)** |
| [기재정정] | 광의 라벨만 재게재, 협의 세부항목 생략 | 80,992,526,676(=Track D 재파싱) |

`combine.py`에 이미 있는 `_NARROW_PREFER`/`_BROAD_RE`(`_reduce_conflict()`)가
`build_merged_lines()`가 그 기간의 **모든 필링(원본+정정)을 풀링**한 후보군에서 원본의
협의값을 정확히 우선 채택한다 — **db는 정확**. Track D(`read_report_face_xbrl_zip()`)는
**rcept 하나(정정본)만 열어** 재파싱하는데 정정본엔 협의 세부항목이 아예 없어 광의값만
후보로 갖게 되고, db의 (정확한) 협의값과 불일치로 fail_b가 뜬 것.

### 2.2 결론: 데이터 수정 불필요, 문서화만

db 값도, 판정 등급(fail_b/REVIEW, fail_a 오승격 없음)도 이미 올바르다. **조치는
`docs/PARSING_RULES.md`에 R39로 이 한계를 명문화하는 것뿐**이다(예시 초안):

> **R39. Track D(xbrl_zip 재파싱) — 다중필링 narrow-prefer 재현 불가(알려진 감사
> 커버리지 공백, 수정 안 함)**
>
> `read_report_face_xbrl_zip()`은 감사 대상 rcept 하나만 연다. `combine.py`의
> `_NARROW_PREFER`(매입채무 등)는 `build_merged_lines()`가 그 기간의 원본+정정 전체를
> 풀링한 후보군에서 협의값을 고르는데, 정정본이 협의 세부항목을 생략하면 Track D는
> 그 필링 하나만으로는 db의 (정확한) 협의값을 재현할 수 없다 — fail_b(REVIEW)로 안전
> 분류되며 fail_a 오승격은 없음. 원문대조 확정(00107987 2018H1, 00112651 2017Q1),
> [[p3-1-trackd-failb-rootcause-2026-08-20]].

### 2.3 (참고, 비권장) Track D 다중필링 확장안

굳이 fail_b 노이즈를 줄이고 싶다면 `read_report_face_xbrl_zip()`이 후보가 db와
안 맞을 때 같은 기간의 다른(원본) 필링도 열어보는 폴백을 추가할 수 있다 — 다만
**권장하지 않는다**: (1) fail_b는 이미 안전 등급이라 실질적 피해가 없고, (2) Track D는
설계상 "완전독립 감사가 아님"을 전제로 하는 트랙인데 여기에 다중필링 폴백까지 추가하면
독립성이 더 옅어져 오히려 Track D의 존재의미(휴리스틱 REVIEW용 대조)가 흐려짐, (3) 구현
복잡도(어느 필링을 얼마나 열어볼지, 무한폴백 방지) 대비 이득이 작음. 우선순위 낮음,
별도 요청 시에만 착수.

---

## §3. 실행 순서 제안

1. ~~§1.5-4 사전측정~~ — **완료(2026-08-20)**: 156개사/756건 확정(R34 기처리 302건
   제외, xbrl_zip-only 밖 18개사/37건 포함).
2. 사용자 승인 후 §1.3 구현 + §1.5 검증
3. §1.6 백필(156개사/756건, xbrl_zip-only 밖 18개사 빠뜨리지 않게 주의) 실행
4. §2.2의 R39 문서화(코드 변경 없음, 언제든 가능)
5. 패턴 A 수정이 fail_a 오승격 없이 반영된 걸 확인한 뒤에만 "xbrl_zip 전사(777개사)
   재감사 반영" 여부 결정(선행세션 판단대로 이 트랙에 종속)

## 부록 A — 영향범위 스캔 재현 방법(§1.5-4, 2026-08-20 실행분)

세션 스크래치에만 존재하고 repo에는 커밋 안 됨 — 재실행 시 아래 로직으로 재작성.

- `build_merged_lines()`(combine.py)의 BS 전용 경량 재구현: `_period_filings_chrono`를
  "그 rcept 에 **BS** report_lines 가 있는 filing만" 조건으로 좁히고, SQL에
  `AND statement='BS'` 추가 — IS/CF를 안 읽어 152K (corp,fy,period) 전수를 ~17분에 처리.
- `fin2.layer3.combine._map_rows(merged, period, basis, ("BS",), corp=corp, fy=fy)` 를
  그대로 재사용해 `{canonical: [candidate]}` 를 얻음(account_mapper 매핑은 실제
  파이프라인과 동일 코드).
- 히트 조건: `_BS_GRAND_TOTAL` 3종 각각에 대해 candidate가 2개 이상, 값이 2가지 이상,
  그중 `amended=True`가 1개 이상 존재.
- "R34가 이미 처리" 판별: 히트한 candidate들을 `industry_profiles.norm(label_raw)`로
  다시 묶었을 때, 어느 한 norm-그룹 **내부**에서 값이 2가지 이상 갈리면(=R34의 그룹핑
  기준으로도 충돌이 보임) 이미 R34가 정확히 처리 중 → 제외. 그렇지 않으면(=모든
  norm-그룹이 내부적으로 값 1개씩 → 그룹 간에만 충돌) R34가 못 잡는 신규 케이스.
- 결과 파일: `pattern_a_impact_scan.json`(세션 스크래치, 1,058건 원본 — 756건 신규분은
  위 필터를 다시 적용해서 골라내야 함).

## 관련 문서

- 원인규명 메모리: `p3-1-trackd-failb-rootcause-2026-08-20.md`
- `docs/PARSING_RULES.md` R34(오늘 이미 반영된 유사 결함, 이번 패턴 A의 직접 선행 사례)
- `fin2/tests/test_combine_amended_label_depth.py`(R34 회귀 테스트, 이번 신규 테스트가
  추가될 파일)
- `docs/runbook_new_parser_pipeline_integration.md`(백필 절차)
- [[gateb-full-reaudit-is-required-to-close]](표본으로 닫지 말 것 원칙)
