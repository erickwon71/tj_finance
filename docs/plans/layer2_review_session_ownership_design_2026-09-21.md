# 계층2 캠페인 — 판정 대상 세션 소유권(owner) 설계

**작성** 2026-09-21 · **상태** ✅**구현 완료**(사용자 승인 2026-09-21, ④ 포함)
**대상 파일** `scripts/layer2_review.py` · `collector/models.py` · `collector/db.py`

---

## 1. 무엇을 막으려는 설계인가

**병렬화 설계가 아니다.** 사용자 결정(2026-09-21): 캠페인 러너를 늘리지 않는다.
그런데도 이 수정이 필요한 이유는, **지금 이 순간에도 큐를 만지는 세션이 둘**이기
때문이다.

| 세션 | 역할 | 큐에 하는 일 |
|---|---|---|
| `camp-run-79` | 캠페인 진행 | `next` → 원문대조 → `pass`/`fail` |
| `camp-err-review-c2`(이 워크트리) | 결함 조사·수정·백필 | `redo --rcept`, 백필 스크립트, 상태 UPDATE |

두 세션이 같은 `layer2_review_queue` 를 보는데, **판정 대상을 고르는 함수 3개가 전부
"전역에서 가장 최근"을 집는다.** 즉 한쪽 세션의 작업이 다른 쪽의 판정 대상을 바꾼다.

### 이미 일어난 사고

`cmd_redo` 를 `--rcept` 없이 불러 **캠페인 세션이 보고 있던 항목을 가로챘다**
(실측, 2026-09-20). 그 뒤로 이 워크트리는 "백필에 `redo` 를 쓰지 않는다"는 **규약**으로
회피하고 있다 — 코드는 그대로다. 규약은 autocompact 를 못 견딘다(지시사항 유실이 이
프로젝트의 반복 문제이고, 그래서 `_full_comparison_reminder()` 를 디스크에서 매번
다시 읽는 장치까지 만들었다).

### 왜 지금 고칠 가치가 있는가

`pass` 는 **되돌리기 어려운 마지막 관문**이다. R139 보호가 걸려 있어 한 번 `pass` 가
찍히면 `store_report_lines()` 가 그 rcept 를 거부한다(`--overwrite-reviewed` 명시
필요). **검토하지 않은 필링에 통과 판정이 찍히는 것**이 이 설계가 막으려는 최악의
결과다.

---

## 2. 결함 3곳 (코드 근거)

### ② `_current()` — 전역 최신 (`scripts/layer2_review.py:385`)

```python
def _current(session):
    """가장 최근에 재적재돼 사람 검토를 기다리는 건(= `pass`/`fail` 의 기본 대상)."""
    return session.execute(
        text("""SELECT * FROM layer2_review_queue
                WHERE status = 'reloaded'
                ORDER BY reloaded_at DESC NULLS LAST LIMIT 1""")).mappings().first()
```

`cmd_pass`(`:632`)·`cmd_fail`(`:670`) 이 `--rcept` 없을 때 이걸 쓴다.

**사고 시나리오**: A 가 X 를 `next` 로 받아 원문대조 중인데, 그 사이 B(이 세션)가
어떤 건 Y 를 재적재해 `status='reloaded'` 로 만든다. A 가 `pass` 를 부르면
`reloaded_at` 이 더 최신인 **Y** 가 잡힌다 → **Y 에 통과 판정이 찍힌다.**
A 는 Y 를 본 적이 없다.

★`--verified-scopes` 게이트도 이걸 못 막는다. 그 게이트는 "적재된 scope 를 다
명시했는가"만 보므로, A 가 X 를 보고 적은 scope 목록이 우연히 Y 의 scope 집합과
같으면 그대로 통과한다.

### ③ `cmd_next` 의 미판정 가드 — 전역 (`:598`)

```python
pending = None if (args.rcept or args.force) else _current(session)
if pending is not None:
    print("\n⚠ 아직 검토가 끝나지 않은 건이 있습니다 ...")
    return
```

같은 `_current()` 를 쓴다. **B 가 남긴 reloaded 건이 A 의 `next` 를 막는다.** A 는
영문을 모른 채 막히고, `--force` 로 뚫으면 ②가 활성화된다.

### ①′ `owner` 를 찍는 지점이 없다 (`_run_target:481`, `_mark:456`)

`_run_target` 은 `status='reloaded'` 만 남기고 **누가 이 건을 집었는지 기록하지
않는다.** ②③을 고치려면 이 기록이 먼저 필요하다.

★**원래 ①이던 `FOR UPDATE SKIP LOCKED` 는 이 설계에서 제외한다** — 두 러너가 같은
`pending` 행을 동시에 집는 상황을 막는 장치이고, 러너가 하나면 발생하지 않는다.
나중에 병렬화한다면 그때 추가한다(§7).

### ④ `cmd_redo` — 전역 최신 (`:692`) ★①~③ 밖의 항목

```python
item = session.execute(
    text("""SELECT * FROM layer2_review_queue
            WHERE status IN ('fail','reloaded','blocked')
            ORDER BY reviewed_at DESC NULLS LAST, reloaded_at DESC NULLS LAST
            LIMIT 1""")).mappings().first()
```

**실제 사고를 낸 함수가 이것이다.** ②와 완전히 같은 결함이고 수정도 같은 한 줄이다.
사용자가 지시한 ①~③에는 없으므로 **별도 항목으로 표시**한다 — 빼셔도 되지만,
빼면 규약으로만 막고 있는 위험이 그대로 남는다.

---

## 3. 설계

### 3.1 소유자 식별 — 무엇을 `owner` 로 쓰는가

프로세스는 명령 1회마다 죽으므로 PID 는 쓸 수 없다. **워크트리 경로**가 자연스러운
키다 — 세션마다 워크트리가 다르고, 값이 안정적이며, 사람이 읽고 바로 이해한다.

```python
_OWNER_ENV = "L2_REVIEW_OWNER"


def _owner() -> str:
    """이 실행의 소유자 식별자 — 기본값은 **워크트리 경로**.

    프로세스는 명령 1회마다 죽으므로 PID 는 못 쓴다. 세션마다 워크트리가 다르고
    경로는 안정적이라 이걸 키로 쓴다(camp_run = 메인 체크아웃 또는 자기 워크트리,
    조사 세션 = `.claude/worktrees/camp_err_review`).

    같은 워크트리에서 굳이 둘로 나눠야 하면 `L2_REVIEW_OWNER` 로 덮는다.
    """
    override = os.environ.get(_OWNER_ENV, "").strip()
    return override or str(Path(__file__).resolve().parents[1])
```

표시용 짧은 이름은 `Path(owner).name` 을 쓴다.

### 3.2 스키마

`collector/models.py::Layer2ReviewQueue` — **"재적재 결과(기계)" 블록**에 추가한다
(사람 판단 블록이 아니다 — `init`/재적재가 갱신하는 값이므로).

```python
    owner         = Column(Text, nullable=True,
                           comment="이 건을 reloaded 상태로 만든 세션(워크트리 경로). "
                                   "pass/fail/redo 의 기본 대상 선택을 이 세션 것으로 "
                                   "한정해, 다른 세션이 보고 있는 건에 판정이 꽂히는 "
                                   "사고를 막는다(2026-09-21).")
```

인덱스 — `_current()` 가 `(status, owner)` 로 조회하므로:

```python
        Index("ix_l2rq_status_owner", "status", "owner"),
```

마이그레이션 — `collector/db.py` 의 `_MIGRATIONS` 리스트 끝에 추가
(기존 `2026_09_20_l2rq_verified_scopes` 다음):

```python
        ("2026_09_21_l2rq_owner",
         # 2026-09-21: pass/fail/redo 의 기본 대상 선택이 "전역에서 가장 최근"이라
         # 다른 세션이 보고 있는 건에 판정이 꽂힐 수 있었다(실측: redo 로 캠페인
         # 세션의 현재 항목을 가로챈 사고 2026-09-20). 소유 세션 것으로 한정한다.
         "ALTER TABLE layer2_review_queue ADD COLUMN IF NOT EXISTS owner TEXT"),
        ("2026_09_21_l2rq_status_owner_idx",
         "CREATE INDEX IF NOT EXISTS ix_l2rq_status_owner "
         "ON layer2_review_queue (status, owner)"),
```

적용: `python run.py init`(기존 관행과 동일 — `screen_severity`·`verified_scopes` 도
이 경로로 들어갔다).

### 3.3 `owner` 를 찍는 지점 — `_run_target`

`_run_target`(`:481`)의 **두 `_mark` 호출 모두**에 `owner=_owner()` 를 넣는다.
blocked 경로를 빠뜨리면 그 건이 무소유로 남는다.

```python
    if err:
        _mark(session, item["rcept_no"], status="blocked", source_kind=kind,
              reloaded_at=now, note=err, owner=_owner())          # ← 추가
        ...
    _mark(session, item["rcept_no"], status="reloaded", source_kind=kind,
          reloaded_at=now, n_lines=n_lines, n_lines_by_scope=counts,
          check_status=sc.rollup(checks),
          checks=[c.as_dict() for c in checks], csv_path=str(path),
          owner=_owner())                                          # ← 추가
```

`_mark` 는 `**fields` 를 ORM update 로 넘기므로 **수정 불필요**.

### 3.4 `_current()` 를 소유자 범위로 (②)

```python
def _current(session, *, owner: str | None = None):
    """이 세션이 재적재해 검토를 기다리는 건(= `pass`/`fail` 의 기본 대상).

    ★`owner` 로 한정하는 이유(2026-09-21) — 예전엔 `status='reloaded'` 중 전역
      최신을 집었다. 큐를 만지는 세션이 둘(캠페인 + 결함조사)이라, 조사 세션이
      어떤 건을 재적재한 직후 캠페인 세션이 `pass` 를 부르면 **자기가 본 적 없는
      건에 통과 판정이 찍혔다.** `pass` 는 R139 보호가 걸리는 되돌리기 어려운
      관문이라 이 사고의 대가가 크다. `--verified-scopes` 게이트도 scope 집합이
      우연히 같으면 못 막는다.
    """
    return session.execute(
        text("""SELECT * FROM layer2_review_queue
                WHERE status = 'reloaded' AND owner = :o
                ORDER BY reloaded_at DESC NULLS LAST LIMIT 1"""),
        {"o": owner or _owner()}).mappings().first()
```

**`owner IS NULL` 을 포함시키지 않는다.** 포함시키면 위험이 그대로 남는다
(전환 처리는 §5).

### 3.5 `cmd_next` 가드를 소유자 범위로 (③)

`_current()` 시그니처만 바뀌므로 `cmd_next`(`:598`)는 **코드 변경 없이** 자동으로
소유자 범위가 된다. 다만 메시지가 오해를 부르므로 문구를 고친다.

```python
            print("\n⚠ 이 세션이 아직 판정하지 않은 건이 있습니다 "
                  f"(r{pending['rcept_no']}, status=reloaded).")
```

### 3.6 `pass`/`fail` 에 소유자 불일치 경고 (②의 마무리)

`--rcept` 로 **명시 지정**하는 것은 세션 간 의도적 개입이라 막지 않는다. 다만
**남의 건이면 경고**한다.

```python
        item = _pick(session, args.rcept, statuses=("reloaded",)) if args.rcept \
            else _current(session)
        if item is None:
            print("판정할 대상이 없습니다 — 이 세션이 재적재한 reloaded 건이 없습니다.")
            print("  다른 세션이 재적재한 건을 판정하려면 `--rcept <번호>` 로 지목하세요.")
            return
        if args.rcept and item["owner"] and item["owner"] != _owner():
            print(f"\n⚠ 이 건의 소유 세션은 {Path(item['owner']).name} 입니다"
                  f"(현재: {Path(_owner()).name}).")
            print("  그 세션이 원문대조 중일 수 있습니다 — 확인하고 진행하세요.")
```

경고만 하고 **차단하지 않는다**: 이 워크트리가 백필 후 재검토를 대신 처리하는
정상 흐름이 실제로 있다(R154 백필 77건).

### 3.7 `cmd_redo` 도 소유자 범위로 (④, 선택)

```python
            item = session.execute(
                text("""SELECT * FROM layer2_review_queue
                        WHERE status IN ('fail','reloaded','blocked')
                          AND owner = :o
                        ORDER BY reviewed_at DESC NULLS LAST,
                                 reloaded_at DESC NULLS LAST
                        LIMIT 1"""), {"o": _owner()}).mappings().first()
```

이걸 넣으면 이 워크트리가 "백필에 `redo` 를 쓰지 않는다"는 **규약으로 회피하던 것을
코드로 막는** 것이 된다 — autocompact 에 견디는 유일한 방식이다.

---

## 4. 회귀 테스트 (구현 시 같이 쓸 것)

`tests/test_layer2_review_ownership.py`(신규). sqlite in-memory + 최소 DDL 로
기존 큐 테스트 관행을 따른다(★`verified_scopes` 추가 때 테스트 DDL 에 컬럼을
안 넣어 4건이 깨진 전례가 있다 — `owner` 도 DDL 에 넣어야 한다).

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | A·B 가 각각 다른 건을 reloaded 로 만든 뒤 A 가 `pass`(무인자) | **A 의 건**이 잡힌다(B 의 건이 아니다) |
| 2 | B 만 reloaded 건을 갖고 A 가 `pass`(무인자) | "대상 없음" + `--rcept` 안내, **아무것도 판정되지 않는다** |
| 3 | B 의 reloaded 건이 있는데 A 가 `next` | 가드에 안 걸리고 **새 건을 받는다** |
| 4 | A 가 `--rcept` 로 B 의 건을 판정 | 진행되지만 **소유자 불일치 경고**가 출력된다 |
| 5 | `owner IS NULL` 인 reloaded 건 + A 가 `pass`(무인자) | 잡히지 **않는다**(§3.4 의 의도) |
| 6 | `_run_target` 의 blocked 경로 | `owner` 가 찍힌다 |
| 7 | 소스에 배선이 살아 있는지 | `_current` 쿼리에 `owner` 가 있다(상수명 변경 시 조용히 깨지는 것 방지 — R153 테스트와 같은 장치) |

---

## 5. 전환(롤아웃) 절차

기존 행은 `owner IS NULL` 이다. §3.4 가 NULL 을 제외하므로 **전환 시점에 in-flight
건이 있으면 캠페인 세션이 `pass` 를 무인자로 못 부른다.**

1. 적용 전 camp_run 에게 **현재 건을 먼저 판정해 달라고 통지**한다
   (`status='reloaded'` 가 0건이 되게).
2. `python run.py init` 으로 마이그레이션 적용.
3. 남아 있으면 `--rcept` 로 한 번만 처리하면 된다(§3.6 이 안내 문구를 출력).

확인 쿼리:

```sql
SELECT rcept_no, corp_name, owner FROM layer2_review_queue WHERE status = 'reloaded';
```

★과거 `pass`/`fail` 이 찍힌 행의 `owner` 는 **백필하지 않는다** — 그 시점에 누가
했는지 알 수 없고, 추측해 넣으면 감사기록을 오염시킨다. `owner` 는 앞으로의
대상 선택에만 쓰이므로 NULL 로 남아도 무해하다.

---

## 6. 영향 범위와 위험

| 항목 | 평가 |
|---|---|
| 스키마 | 컬럼 1개 + 인덱스 1개. nullable 이라 기존 행 영향 없음 |
| 코드 | `_owner()` 신규 + `_current()` 시그니처 + `_mark` 호출 2곳 + 메시지 2곳 (+④ 1곳) |
| 하류 | 없음 — `report_lines`·`std_v3`·`calendar_v3` 는 `owner` 를 안 본다 |
| 기존 동작 | 세션이 **하나뿐일 때는 완전히 동일**하다(자기 건만 있으므로) |
| 되돌리기 | 컬럼을 NULL 로 두고 `_current()` 만 원복하면 끝 |

**남는 위험**: 같은 워크트리에서 두 세션을 띄우면 `owner` 가 같아 구분되지 않는다.
`L2_REVIEW_OWNER` 로 덮을 수 있지만 **강제되지는 않는다.** 병렬화하지 않는다는
전제에서는 문제가 안 된다.

---

## 7. 이 설계가 **하지 않는** 것

- **병렬 실행 지원 아님.** `_pick()` 에 `FOR UPDATE SKIP LOCKED` 와 중간 상태
  (`reloading`)를 넣지 않았다. 러너가 둘이면 여전히 같은 `pending` 행을 동시에
  집을 수 있다.
- **corp 단위 샤딩 없음.** `finish-corp` 의 `build_std_v3`/`calendarize_corp_v3`
  경합도 그대로다.
- 나중에 병렬화한다면 위 둘을 추가하면 되고, 이 설계의 `owner` 컬럼을 그대로
  재사용한다(claim 시점에 찍는 것으로 의미만 확장).

---

## 8. 결정이 필요한 것

1. **④(`cmd_redo`)를 포함할지** — 지시하신 ①~③ 밖이다. 포함하면 실제 사고를 낸
   경로가 코드로 막히고, 빼면 규약으로만 막은 채 남는다. **포함 권고.**
2. **소유자 식별을 워크트리 경로로 할지** — 대안은 `L2_REVIEW_OWNER` 필수화
   (명시적이지만 잊으면 동작이 달라진다). **경로 기본값 + env 덮어쓰기 권고.**
3. **전환 시점** — camp_run 이 현재 건을 판정한 뒤로 맞출지, 아니면 바로 적용하고
   `--rcept` 로 한 번 넘길지.

---

## 9. 구현 결과 (2026-09-21)

사용자 승인으로 **①′~③ + ④ 전부 구현**했다.

| 파일 | 변경 |
|---|---|
| `collector/models.py` | `owner` 컬럼 + `ix_l2rq_status_owner` 인덱스 |
| `collector/db.py` | 마이그레이션 2건(`2026_09_21_l2rq_owner`, `..._status_owner_idx`) |
| `scripts/layer2_review.py` | `_owner()`·`_owner_label()` 신규 / `_current(owner=)` / `_run_target` 의 `_mark` 2곳 / `cmd_next` 메시지 / `_print_no_target()`·`_warn_if_other_owner()` 신규 / `cmd_pass`·`cmd_fail` 훅 / `cmd_redo` 소유자 범위(④) |
| `fin2/tests/test_layer2_review_ownership.py` | 신규 17건 |
| `fin2/tests/test_store_report_lines_manual_guard.py` | 테스트 DDL 에 `owner` 추가 |

**마이그레이션 적용 완료** — `python run.py init` → "마이그레이션 2건 신규 적용".
`information_schema` 로 컬럼·인덱스 존재 확인.

**★테스트가 조용한 경보가 아님을 증명했다**: `_current()` 를 일부러 예전(전역) 동작으로
되돌리자 **5건이 실패**했다 — 그중 핵심은
`test_current_picks_my_item_not_the_globally_newest`(남의 건이 **더 최신**일 때 그것이
잡히는지). 되돌린 코드를 복원한 뒤 다시 전건 통과.

**전환 실측**: 적용 시점에 camp_run 의 in-flight 건이 1건 있었고 `owner IS NULL` 이다
(NAVER 2017Q3 `r20171114001543`). §5 대로 그 건만 `--rcept` 로 한 번 판정하면 되고,
이후 `next` 로 받는 건부터는 자동으로 소유자가 찍힌다. 마이그레이션은 **하위 호환**이라
camp_run 이 코드를 pull 하기 전에도 기존 동작에 영향이 없다(컬럼 추가뿐).

★과거 `pass`/`fail` 행의 `owner` 는 백필하지 않았다(§5) — 누가 했는지 알 수 없고
추측해 넣으면 감사기록을 오염시킨다.
