# 설계안 — 계층2 헤더 판정 무손실화 (B안)

> **상태: 미실행.** 검토용 설계안이며, 실행은 별도 요청을 받는다.
> 배경 실측 = `docs/qa/layer2_fidelity_full_2026-07-30.md`

## 0. 한 줄

계층2가 헤더로 의심되는 행을 **삭제**하는 대신, **어느 규칙에 걸렸는지를 기록하고 전사**한다.
판단은 계층3으로 옮긴다. 규칙(`_is_header_cell`)은 그대로 두고 **결과를 쓰는 방식만** 바꾼다.

```
지금 : _is_header_cell('당기말') == True  →  행 삭제                        (판단 + 파괴)
제안 : _is_header_cell('당기말') == True  →  header_hint='기간라벨' 로 전사   (관찰만)
```

## 1. 왜 — 오늘 실측한 근거

### 1-1. 역방향 검사가 못 보는 사각
`layer2_fidelity_full.py`(역방향)는 **99.99661%** 로 정상을 보고했다. 같은 날 정방향 셀
커버리지를 재보니 원문 금액셀 293,044,443 중 **4.26% 가 DB 에 도달하지 못하고** 있었다.
역방향은 "DB 값이 원문에 있나" 만 보므로 **원문에 있는데 DB에 없는 것**을 구조적으로 못 본다.

### 1-2. 헤더 오판 드롭 — 두 규칙이 95%
`scripts/layer2_forward_cells.py` 규칙별 귀속(표본 200 filing):

| 규칙 | 셀 | 비중 |
|---|---|---|
| **`당기말/전기말`류**(`_is_header_cell:387`) | 2,590 | **75.25%** |
| **날짜**(`:363`) | 678 | **19.70%** |
| 빈셀/대시 | 77 | 2.24% |
| 기수·단위표기·공정가치수준 | 97 | 2.80% |

### 1-3. 실제로 사라지던 데이터 (원문 대조)
```
헤더드롭  '전기초'   12,717,566 | 16,786,820 |  3,607,440 | 119,883,295
헤더드롭  '당기말'   16,184,508 | 36,609,993 |  6,979,285 | 200,967,562
```
유형자산 증감표처럼 **행=기간, 열=자산분류** 인 주석 표에서는 `당기말` 이 열 헤더가 아니라
**데이터 행 라벨**이다. 규칙은 "항상 열 헤더" 를 가정했다.

### 1-4. 결함 부류가 하나다
오늘 찾은 5건이 전부 같은 문장이다 — **"이 열/행은 X를 뜻한다"고 가정한 규칙이 X가 아닌
표에 적용됐다.** 규칙을 하나씩 좁히면 다음 반례까지만 유효하다(`당기말` 다음엔 `수준 1` 이
행 라벨인 표가 나온다). 계층2 의 선언된 원칙은 **"판단 없이 충실전사"** 이고, 이 휴리스틱들은
집계가 필요했던 구 `fact_v2` 파이프라인의 유산이다.

### 1-5. 틀렸을 때의 비용이 계층마다 다르다

| | 계층2에서 판단 | 계층3에서 판단 |
|---|---|---|
| 틀리면 | **행이 사라짐** | 행은 남고 해석만 틀림 |
| 발견 | 원문 대조로만(전용 도구 필요) | SQL 조회로 보임 |
| 복구 | **전량 재추출 약 4시간** | 계층3 재빌드 약 1시간 |

## 2. 계약 변경 (계층2)

기존 관례를 그대로 따른다 — `extract_rows` 에는 이미 계층2 전용 스위치가 셋 있다
(`skip_junk=False` · `date_labels_ok=True` · `preserve_col_positions=True`). 넷째를 같은
방식으로 붙인다. **opt-in 이므로 다른 호출자(biz_section·order_backlog 등)는 무영향.**

```python
# parser/xml/table_extractor.py
def extract_rows(..., keep_header_rows: bool = False):
    ...
    hint = _header_rule_name(first_text, allow_date_label=date_labels_ok)  # 규칙명 or None
    if hint and not keep_header_rows:
        continue                      # 기존 호출자 동작 보존
    # keep_header_rows=True 면 버리지 않고 RowData.header_hint 에 담는다
```

- `_is_header_cell()` 은 **그대로 둔다**. 내부적으로 `_header_rule_name()` 을 호출해
  `bool(hint)` 를 반환하도록만 바꾼다(동작 동일, 판정 근거를 밖에서 쓸 수 있게 됨).
- `RowData` 에 `header_hint: str | None` 추가.
- **값 판단은 하지 않는다** — 라벨·금액·위치는 다른 행과 완전히 동일하게 전사한다.

### hint 값 집합 (고정 — 표 구조마다 늘어나지 않는다)
`날짜` · `기수` · `단위표기` · `구분과목` · `N개월` · `N분기` · `날짜범위` · `기준일` ·
`기간라벨` · `공정가치수준` · `빈셀` · `재무제표제목`

> ★핵심: 특이 구조를 발견할 때마다 정의를 추가하는 게 아니다. 규칙에 안 걸리면
> `header_hint=NULL` 인 평범한 데이터 행이 될 뿐이라 **새 구조에 추가 작업이 없다.**

## 3. 스키마

```sql
ALTER TABLE report_lines ADD COLUMN header_hint TEXT;
ALTER TABLE note_lines   ADD COLUMN header_hint TEXT;
-- 0.6% 만 NOT NULL 이므로 부분 인덱스로 충분하다
CREATE INDEX ix_report_lines_header_hint ON report_lines (header_hint)
    WHERE header_hint IS NOT NULL;
CREATE INDEX ix_note_lines_header_hint   ON note_lines   (header_hint)
    WHERE header_hint IS NOT NULL;
```
볼륨 증가 = 금액셀의 **약 0.6%**(표본 실측 3,442/565,792).
마이그레이션은 `collector/db.py` 에 추가(새 DB 재현성 확보).

## 4. 계층3 가드 (이 변경과 **반드시 함께** 간다)

가드 없이 계층2만 바꾸면 `당기말` 행이 유형자산 증감표의 실데이터로 섞여 D&A 합산을 오염시킨다.

| 소비처 | 조치 |
|---|---|
| `fin2/layer3/combine.py:130,426` | 기본 `WHERE header_hint IS NULL` |
| `fin2/layer3/note_da.py:44` | 기본 `AND header_hint IS NULL` |
| `parser/common/note_periods.py` | **예외 — `기간라벨` 행을 적극 활용**한다. 행이 기간축인 표를 식별하는 1차 신호가 되므로, 지금 위치 추측으로 하던 판정을 원문 근거로 대체할 수 있다 |
| `fin2/audit/*` | 무영향(추출기 메모리 산출물을 읽으므로 동작 동일) |

## 5. ★일괄조사 — B안의 핵심 이득

지금은 "어떤 행이 왜 사라졌나" 를 알려면 원문 10만 건을 재파싱해야 한다(전용 도구 + 1.4시간).
`header_hint` 가 DB 에 있으면 **재파싱 없이 SQL 로 전수 조사**가 된다.

```sql
-- ① hint 별 분포: 어느 규칙이 얼마나 잡는가
SELECT header_hint, count(*), count(DISTINCT rcept_no)
FROM note_lines WHERE header_hint IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;

-- ② 진짜 데이터 행일 가능성이 높은 것: 헤더로 판정됐는데 금액이 여러 개인 행
SELECT rcept_no, section_path, label_raw, count(*) AS n_amounts
FROM note_lines WHERE header_hint = '기간라벨'
GROUP BY 1,2,3 HAVING count(*) >= 3 ORDER BY 4 DESC LIMIT 50;

-- ③ 행이 기간축인 표 찾기: 한 표에 '기간라벨' 행이 2개 이상
SELECT rcept_no, table_seq, count(DISTINCT label_raw) AS period_rows
FROM note_lines WHERE header_hint = '기간라벨'
GROUP BY 1,2 HAVING count(DISTINCT label_raw) >= 2;

-- ④ 특정 주석 주제에서만 나타나는 패턴(유형자산 증감표 등)
SELECT section_path, header_hint, count(*)
FROM note_lines WHERE header_hint IS NOT NULL
GROUP BY 1,2 ORDER BY 3 DESC LIMIT 40;
```

즉 **"특이 구조를 미리 정의" 하는 게 아니라, 전사해 두고 나중에 전수로 찾아낸다.**
새 패턴이 발견되면 계층3 규칙만 고치고 **재빌드 1시간**으로 반영된다(재추출 불필요).

## 6. 마이그레이션 / 백필

1. `collector/db.py` 마이그레이션 추가(컬럼 + 부분 인덱스)
2. **전량 재적재** — `scripts/full_reload_after_sanitize.sh 10` (약 4시간)
   ⚠ TRUNCATE 후 INSERT 필수(2026-07-27 delete-then-insert 로 디스크 100% → 백필 전멸)
3. 계층3 재빌드는 위 스크립트 ③ 단계에 포함

배선: `store_report_lines`/`store_note_lines` 가 단일 관문이므로 **call site 배선 불필요**
(본문 writer 4곳 전부 이 함수를 지난다). `docs/runbook_new_parser_pipeline_integration.md`
체크리스트 중 ①은 자동 충족, ②소급 백필 = 위 2번, ③검증 = §7.

## 7. 검증 기준

| 항목 | 기준 |
|---|---|
| 정방향 커버리지 | `헤더행 오판 드롭` **0** (`layer2_forward_cells.py` 전수) |
| 설명안됨 | 0 유지 |
| 회귀 테스트 | 253/253 통과 |
| 계층3 D&A | FY 커버리지 97.5% **이상** 유지 · 항등식 위반 0 · 음수 0 |
| std_v3 | 행 수 185,268 ±α, 값 변화는 **증가 방향만**(유실 회복) |
| 다른 호출자 | `biz_section`·`order_backlog` 산출 무변화(opt-in 확인) |

## 8. 리스크

| 리스크 | 대응 |
|---|---|
| 계층3이 안 거르면 오염 | §4 가드를 **같은 커밋**에 포함. 가드 없이 계층2만 배포 금지 |
| 볼륨 증가 | +0.6%(실측). 부분 인덱스로 조회 비용 억제 |
| 기존 호출자 회귀 | `keep_header_rows` 기본 False — 계층2 경로만 opt-in |
| 재적재 4시간 | 다른 수정과 묶어 1회로 |

## 9. 남은 미결(이 설계안 범위 밖, 함께 볼 것)

- **본문 열절단 3.7%** — 잘리는 건 전기·전전기라 현 적재 대상 아님(2026-07-30 결정). 무영향
- **소수 절단** `1,106.52 → 1,106` (0.109%) — `adecimal` 로 소수 보존 여부 별도 판단
- **데일리 본문 미배선** — `scripts/collect_new.py` 는 주석만 증분 적재. 신규 보고서 본문이
  데일리 경로에 없다
- **측정 도구 잔차** — `설명안됨` 5셀/200 filing(0.001%). EPS·cum_map 폴백 회계 잔차로
  좁혀졌으나 완전 규명 전
