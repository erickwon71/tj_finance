"""DB 용량 낭비 원장 — 회수 가능한 바이트를 유형별로 계량한다 (READ-ONLY).

왜 필요한가
-----------
과거에 `financial_facts`(27 GB)를 뒤늦게 드롭한 일이 있었고(commit 1329d57), 2026-07-30
실측에서는 `note_lines.table_title` 한 컬럼이 **행마다 반복 저장**되며 30 GB 대를 쓰고 있음이
드러났다. 둘 다 "한 번 보고 끝난 조사" 였다면 재발했을 것이다. 그래서 이 도구는 보고서가
아니라 **반복 실행하는 계량기**다 — 같은 명령으로 언제든 현재 낭비를 다시 잰다.

계량 유형
---------
  W1 반복저장   : 컬럼값이 **더 굵은 키에 함수종속**이라 행마다 되풀이됨(정규화 대상)
  W2 미사용인덱스: idx_scan 이 0 에 가까운 인덱스. ★통계 창 + UNIQUE 여부를 함께 봐야 판정 가능
  W3 상수/NULL  : n_distinct=1 (상수) 또는 null_frac=1.0 (전량 NULL) 컬럼
  W4 정렬패딩   : 컬럼 선언 순서 때문에 튜플에 생기는 빈틈(재배치로 회수)
  W5 고아테이블 : 코드에서 참조가 0인 테이블
  B  bloat      : dead tuple 비율

★ 초판의 거짓양성 두 건 — 같은 실수를 반복하지 않기 위해 기록한다(2026-07-30)
  ① W1 을 **반복도(rows/n_distinct)** 로만 판정해 `value_won`(진짜 행별 데이터, 306×)까지
     '정규화 후보' 로 올렸다. 반복도가 높은 것과 **더 굵은 키에 함수종속인 것**은 다르다.
     ⇒ 이제 후보 컬럼마다 `GROUP BY 후보키 HAVING count(DISTINCT col) > 1` 을 **실제로
       질의해** 종속을 확인한다(표본 rcept_no). 측정이지 추측이 아니다.
  ② W2 가 `uq_stock_prices`·`ux_valuation_daily_corp_date` 를 미사용으로 올렸다. 둘 다
     **ON CONFLICT 대상 UNIQUE 제약**이다 — 업서트 경로는 `idx_scan` 을 올리지 않으므로
     통계상 0 으로 보이지만 지우면 writer 가 깨진다.
     ⇒ 이제 UNIQUE/제약 여부와 ON CONFLICT 코드 참조를 함께 출력하고, **UNIQUE 는
       회수액 합계에서 제외**한다.

★ 판정하지 않는 것: 이 도구는 **회수 가능액을 제시**할 뿐 drop 을 권하지 않는다.
  `idx_scan=0` 은 "안 쓰인다"의 증명이 아니다(통계 리셋·재생성 직후일 수 있다). 그래서
  W2 는 항상 **통계 창의 길이**와 **같은 창에서 가장 많이 쓰인 인덱스**를 함께 출력해,
  창 자체가 유효한지 사람이 판단할 수 있게 한다.

Usage
-----
    python scripts/audit_db_waste.py                       # 요약만
    python scripts/audit_db_waste.py --out docs/qa/db_waste_ledger_2026-07-30.md
    python scripts/audit_db_waste.py --min-mb 100          # 임계 조정
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from collector.db import get_session

MB = 1024 * 1024
GB = 1024 * MB

# 반복도(rows/n_distinct)가 이 값을 넘고 총 바이트가 --min-mb 를 넘으면 정규화 후보로 본다.
_REPETITION_MIN = 50

# W4: attalign → 정렬 경계(바이트). varlena(attlen<0)는 short header(1B)면 정렬이 필요 없어
# 실무상 1 로 본다 — 그래서 W4 는 **고정폭 컬럼의 배치**만 계량한다(근사임을 명시).
_ALIGN = {"c": 1, "s": 2, "i": 4, "d": 8}


# ══════════════════════════════════════════════════════════════════════════
# 수집
# ══════════════════════════════════════════════════════════════════════════

_SQL_TABLES = """
SELECT c.relname                        AS name,
       pg_total_relation_size(c.oid)    AS total_bytes,
       pg_relation_size(c.oid)          AS heap_bytes,
       pg_indexes_size(c.oid)           AS index_bytes,
       COALESCE(s.n_live_tup, 0)        AS live,
       COALESCE(s.n_dead_tup, 0)        AS dead
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY pg_total_relation_size(c.oid) DESC
"""

# n_live_tup 은 통계라 부정확할 수 있다. 반복저장 계량은 행 수에 비례하므로, 통계가 0 인
# 테이블(ANALYZE 이력 없음)은 reltuples 로 보정한다.
_SQL_RELTUPLES = """
SELECT c.relname, GREATEST(c.reltuples, 0)::bigint AS est
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
"""

_SQL_STATS = """
SELECT tablename, attname, avg_width, n_distinct, null_frac
FROM pg_stats
WHERE schemaname = 'public'
"""

_SQL_INDEXES = """
SELECT i.relname                          AS table_name,
       s.indexrelname                     AS index_name,
       pg_relation_size(s.indexrelid)     AS bytes,
       s.idx_scan                         AS scans,
       x.indisunique                      AS is_unique,
       x.indisprimary                     AS is_primary,
       (con.oid IS NOT NULL)              AS is_constraint
FROM pg_stat_user_indexes s
JOIN pg_class i ON i.oid = s.relid
JOIN pg_index x ON x.indexrelid = s.indexrelid
LEFT JOIN pg_constraint con ON con.conindid = s.indexrelid
ORDER BY pg_relation_size(s.indexrelid) DESC
"""

# W1 후보키 — "이 컬럼은 행보다 굵은 무엇에 종속되는가" 의 가설. 실제 종속은 질의로 확인한다.
# 키를 좁은 것부터 넓은 것 순으로 둔다(좁은 키에 종속되면 회수액이 크다).
_FD_KEYS: list[tuple[str, ...]] = [
    ("rcept_no",),
    ("rcept_no", "statement", "basis"),
    ("rcept_no", "statement", "basis", "table_seq"),
]

# W4 계량용 물리 컬럼 배치. attnum>0 = 사용자 컬럼, attisdropped 제외.
_SQL_ATTRS = """
SELECT c.relname AS table_name, a.attname, a.attnum, a.attlen, a.attalign
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

_SQL_RESET = "SELECT stats_reset, now() - stats_reset AS age FROM pg_stat_database WHERE datname = current_database()"


def human(n: float) -> str:
    """바이트를 사람이 읽는 단위로. 원장은 사람이 우선순위를 정하는 문서다."""
    for unit, div in (("GB", GB), ("MB", MB), ("KB", 1024)):
        if abs(n) >= div:
            return f"{n / div:,.1f} {unit}"
    return f"{n:,.0f} B"


def code_references(name: str) -> int:
    """코드에서 이름이 몇 파일에 등장하는가. W2/W5 판정 보조 — 통계만 믿지 않기 위함."""
    try:
        r = subprocess.run(
            ["grep", "-rl", "--include=*.py", "--include=*.sh", "--include=*.sql",
             name, "collector", "fin2", "parser", "scripts", "app", "analyzer", "tests"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        return len([l for l in r.stdout.splitlines() if l.strip()])
    except Exception:  # noqa: BLE001
        return -1                      # 판정 불가를 0 과 구분한다


# ══════════════════════════════════════════════════════════════════════════
# 계량
# ══════════════════════════════════════════════════════════════════════════

def measure_dependency(session, table: str, col: str, key: tuple[str, ...],
                       sample: int) -> tuple[bool, int, int] | None:
    """`col` 이 `key` 에 함수종속인가를 **질의로 확인**한다 (표본 rcept_no).

    반환 (종속 여부, 표본 행 수, 표본 그룹 수) 또는 None(측정 불가).
    종속이면 회수 상한 = avg_width × (rows − groups) — 그룹당 한 벌만 남기면 되므로.

    표본을 쓰는 이유: 2.2억 행 전수 GROUP BY 는 수십 분이 걸린다. rcept_no 단위로 뽑으면
    filing 안의 표 구조가 온전히 들어오므로 종속성 판정에는 충분하다(반쪽 표가 안 생긴다).
    """
    keycols = ", ".join(key)
    sql = f"""
        WITH s AS (
            SELECT DISTINCT rcept_no FROM {table}
            TABLESAMPLE SYSTEM (0.05) LIMIT :n
        ), r AS (
            SELECT {keycols}, {col} FROM {table} t
            WHERE EXISTS (SELECT 1 FROM s WHERE s.rcept_no = t.rcept_no)
        )
        SELECT count(*) AS rows,
               count(DISTINCT ({keycols})) AS groups,
               (SELECT count(*) FROM (
                    SELECT 1 FROM r GROUP BY {keycols}
                    HAVING count(DISTINCT {col}) > 1) v) AS violations
        FROM r
    """
    try:
        r = session.execute(text(sql), {"n": sample}).fetchone()
    except Exception:  # noqa: BLE001
        return None
    if not r or not r.rows:
        return None
    return (r.violations == 0), r.rows, r.groups


def measure_padding(attrs: list, widths: dict[str, int]) -> tuple[int, int]:
    """(현재 배치 바이트, 최적 배치 바이트). 차이가 행당 회수 가능 패딩이다.

    근사임을 분명히 해 둔다 — varlena 는 short header 면 정렬이 필요 없어 1 로 본다.
    그래서 이 값은 **고정폭 컬럼의 선언 순서**가 만드는 빈틈만 잡는다.
    """
    def layout(cols: list) -> int:
        off = 0
        for a in cols:
            if a.attlen > 0:
                align = _ALIGN.get(a.attalign, 1)
                off = ((off + align - 1) // align) * align      # 정렬 경계로 올림
                off += a.attlen
            else:
                off += widths.get(a.attname, 1)                 # varlena: 실측 평균폭
        return off

    # 최적 = 고정폭을 정렬 경계 내림차순으로, varlena 는 뒤로.
    fixed = sorted([a for a in attrs if a.attlen > 0],
                   key=lambda a: (-_ALIGN.get(a.attalign, 1), -a.attlen))
    var = [a for a in attrs if a.attlen <= 0]
    return layout(list(attrs)), layout(fixed + var)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-mb", type=int, default=50,
                    help="이 크기 미만의 회수액은 원장에서 생략(기본 50MB)")
    ap.add_argument("--fd-sample", type=int, default=300,
                    help="W1 함수종속 측정에 쓸 rcept_no 표본 수(기본 300)")
    ap.add_argument("--out", help="마크다운 원장 저장 경로")
    args = ap.parse_args()
    floor = args.min_mb * MB

    with get_session() as s:
        tables = s.execute(text(_SQL_TABLES)).fetchall()
        reltuples = {r.relname: r.est for r in s.execute(text(_SQL_RELTUPLES))}
        stats = s.execute(text(_SQL_STATS)).fetchall()
        indexes = s.execute(text(_SQL_INDEXES)).fetchall()
        attrs_rows = s.execute(text(_SQL_ATTRS)).fetchall()
        reset = s.execute(text(_SQL_RESET)).fetchone()
        db_bytes = s.execute(
            text("SELECT pg_database_size(current_database())")).scalar()

    # 행 수: 통계 우선, 없으면 reltuples 추정.
    rows_of = {t.name: (t.live or reltuples.get(t.name, 0)) for t in tables}
    heap_of = {t.name: t.heap_bytes for t in tables}
    total_of = {t.name: t.total_bytes for t in tables}

    stats_by_table: dict[str, list] = {}
    for r in stats:
        stats_by_table.setdefault(r.tablename, []).append(r)
    attrs_by_table: dict[str, list] = {}
    for r in attrs_rows:
        attrs_by_table.setdefault(r.table_name, []).append(r)

    out: list[str] = []

    def emit(line: str = "") -> None:
        out.append(line)
        print(line)

    emit(f"# DB 용량 낭비 원장 — {datetime.now():%Y-%m-%d %H:%M}")
    emit()
    emit(f"DB 총 크기 **{human(db_bytes)}** · 테이블 {len(tables)}개 · "
         f"임계 {args.min_mb} MB 미만 생략")
    emit()

    # ── 테이블 개요 ────────────────────────────────────────────────────────
    emit("## 0. 테이블 개요 (상위 10)")
    emit()
    emit("| 테이블 | 총 | heap | 인덱스 | 행 | 바이트/행 |")
    emit("|---|---|---|---|---|---|")
    for t in tables[:10]:
        n = rows_of[t.name] or 0
        bpr = f"{t.heap_bytes / n:,.0f}" if n else "—"
        emit(f"| `{t.name}` | {human(t.total_bytes)} | {human(t.heap_bytes)} | "
             f"{human(t.index_bytes)} | {n:,} | {bpr} |")
    emit()

    recoverable = 0

    # ── W1 반복 저장 ───────────────────────────────────────────────────────
    emit("## W1. 반복 저장 — 함수종속 **측정** 결과")
    emit()
    emit("반복도가 높다고 정규화 대상이 아니다(`value_won` 은 306× 반복이지만 행별 실데이터다).")
    emit(f"후보 컬럼마다 `GROUP BY 키 HAVING count(DISTINCT col) > 1` 을 **실제로 질의**해")
    emit(f"종속을 확인한다(표본 {args.fd_sample} rcept_no). 회수액 = `평균폭 × (행 − 그룹)`.")
    emit()
    w1_rows: list[tuple[int, str]] = []
    with get_session() as s2:
        for tname in ("note_lines", "report_lines"):
            n = rows_of.get(tname, 0)
            if not n:
                continue
            have = {a.attname for a in attrs_by_table.get(tname, [])}
            for c in sorted(stats_by_table.get(tname, []),
                            key=lambda c: -(c.avg_width or 0)):
                width = c.avg_width or 0
                if width <= 4 or width * n < floor or c.attname in ("id",):
                    continue
                for key in _FD_KEYS:
                    if not set(key) <= have or c.attname in key:
                        continue
                    got = measure_dependency(s2, tname, c.attname, key, args.fd_sample)
                    if got is None:
                        continue
                    dependent, srows, sgroups = got
                    if not dependent:
                        continue
                    # 표본 그룹/행 비율을 전체에 투영한다(표본은 rcept_no 단위라 편향이 작다).
                    ratio = sgroups / max(srows, 1)
                    gain = int(width * n * (1 - ratio))
                    if gain >= floor:
                        w1_rows.append((gain, f"| `{tname}.{c.attname}` | {width} B | "
                                              f"`{'+'.join(key)}` | {srows:,}행→{sgroups:,}그룹 "
                                              f"| **{human(gain)}** |",
                                        f"{tname}.{c.attname}"))
                    break              # 가장 좁은 종속 키에서 멈춘다(회수액 최대)
    w1_counted: set[str] = set()
    if w1_rows:
        emit("| 컬럼 | 평균폭 | 종속 키(측정됨) | 표본 | 회수액 |")
        emit("|---|---|---|---|---|")
        for gain, line, ref in sorted(w1_rows, reverse=True):
            emit(line)
            recoverable += gain
            w1_counted.add(ref)
    else:
        emit("_해당 없음_")
    emit()

    # ── W2 미사용 인덱스 ───────────────────────────────────────────────────
    emit("## W2. 사실상 미사용 인덱스")
    emit()
    age = reset.age if reset and reset.age else None
    emit(f"통계 창: `stats_reset` = {reset.stats_reset if reset else 'NULL'}"
         f"{f' (경과 {age})' if age else ' — 리셋 이력 없음'}")
    if indexes:
        top = max(indexes, key=lambda r: r.scans or 0)
        emit(f"같은 창에서 최다 사용 인덱스 = `{top.index_name}` **{top.scans or 0:,} 회** "
             f"→ 창이 유효한지 이 값으로 판단한다(0 이면 창 자체를 신뢰할 수 없다).")
    emit()
    emit("★ UNIQUE 는 회수액 합계에서 **제외**한다 — `ON CONFLICT` 업서트는 `idx_scan` 을")
    emit("올리지 않으므로 통계상 0 으로 보이지만 지우면 writer 가 깨진다.")
    emit()
    emit("| 인덱스 | 테이블 | 크기 | 스캔 | 종류 | 코드 참조 | 판정 |")
    emit("|---|---|---|---|---|---|---|")
    for r in indexes:
        if r.bytes < floor or (r.scans or 0) > 100:
            continue
        refs = code_references(r.index_name)
        if r.is_primary:
            kind, verdict = "PK", "보류 — 대리키 필요성 확인"
        elif r.is_unique:
            kind, verdict = "UNIQUE" + (" 제약" if r.is_constraint else ""), "**유지** — 업서트 보호"
        else:
            kind, verdict = "일반", "**drop 후보**"
            recoverable += r.bytes
        emit(f"| `{r.index_name}` | `{r.table_name}` | {human(r.bytes)} | "
             f"{r.scans or 0:,} | {kind} | {refs if refs >= 0 else '?'} | {verdict} |")
    emit()
    emit("⚠ `스캔 0` 은 미사용의 증명이 아니다. drop 전에 '코드 참조'·통계 창·종류를 함께 볼 것.")
    emit("PK 는 `store_report_lines` 가 delete-then-insert 라 조회에 안 쓰이지만, 드롭하려면")
    emit("복제/논리 디코딩·`ctid` 의존 여부를 먼저 확인해야 하므로 별도 판단으로 남긴다.")
    emit()

    # ── W3 상수 / 전량 NULL ────────────────────────────────────────────────
    emit("## W3. 상수·전량 NULL 컬럼")
    emit()
    w3: list[tuple[int, str]] = []
    for tname, cols in stats_by_table.items():
        n = rows_of.get(tname, 0)
        if not n:
            continue
        for c in cols:
            width = c.avg_width or 0
            kind = None
            if (c.null_frac or 0) >= 1.0:
                kind = "전량 NULL"
            elif (c.n_distinct or 0) == 1:
                kind = "상수"
            if kind and width * n >= floor:
                total = int(width * n)
                dup = f"{tname}.{c.attname}" in w1_counted
                w3.append((total, dup, f"| `{tname}.{c.attname}` | {kind} | {width} B | "
                                       f"{n:,} | {human(total)} | "
                                       f"{'W1 중복 — 합계 제외' if dup else '**신규**'} |"))
    if w3:
        emit("상수 컬럼은 W1 에서 이미 함수종속으로 잡히는 경우가 많다 — **중복 계상을 막기 위해**")
        emit("W1 에 이미 든 컬럼은 합계에서 제외하고 표시만 남긴다.")
        emit()
        emit("| 컬럼 | 종류 | 평균폭 | 행 | 회수액 | 합계 반영 |")
        emit("|---|---|---|---|---|---|")
        for total, dup, line in sorted(w3, key=lambda x: -x[0]):
            emit(line)
            if not dup:
                recoverable += total
    else:
        emit("_해당 없음_")
    emit()

    # ── W4 정렬 패딩 ───────────────────────────────────────────────────────
    emit("## W4. 튜플 정렬 패딩 (근사)")
    emit()
    emit("고정폭 컬럼의 **선언 순서**가 만드는 빈틈. varlena 는 short header 면 정렬이")
    emit("필요 없어 1 B 로 본다 — 그래서 이 값은 하한에 가깝다.")
    emit()
    w4: list[tuple[int, str]] = []
    for tname, attrs in attrs_by_table.items():
        n = rows_of.get(tname, 0)
        if not n or total_of.get(tname, 0) < floor:
            continue
        widths = {c.attname: (c.avg_width or 1) for c in stats_by_table.get(tname, [])}
        cur, opt = measure_padding(attrs, widths)
        gain = (cur - opt) * n
        if gain >= floor:
            w4.append((gain, f"| `{tname}` | {cur} B | {opt} B | {cur - opt} B | "
                             f"{n:,} | **{human(gain)}** |"))
    if w4:
        emit("| 테이블 | 현재/행 | 최적/행 | 차 | 행 | 회수액 |")
        emit("|---|---|---|---|---|---|")
        for gain, line in sorted(w4, reverse=True):
            emit(line)
            recoverable += gain
    else:
        emit("_해당 없음_")
    emit()

    # ── W5 고아 테이블 ─────────────────────────────────────────────────────
    emit("## W5. 코드 참조 0 테이블")
    emit()
    emit("과거 `financial_facts`(27 GB) 사례의 재발 감시. 참조 0 이라고 곧 드롭이 아니다 —")
    emit("동적 SQL·문서화된 수동 절차일 수 있으므로 확인 후 판단한다.")
    emit()
    orphans = [(t.total_bytes, t.name) for t in tables
               if t.total_bytes >= floor and code_references(t.name) == 0]
    if orphans:
        emit("| 테이블 | 크기 |")
        emit("|---|---|")
        for b, nm in sorted(orphans, reverse=True):
            emit(f"| `{nm}` | {human(b)} |")
    else:
        emit("_해당 없음_")
    emit()

    # ── bloat ──────────────────────────────────────────────────────────────
    emit("## B. Bloat (dead tuple)")
    emit()
    bl = [(t.dead / max(t.live, 1), t) for t in tables
          if t.dead and t.total_bytes >= floor]
    if bl:
        emit("| 테이블 | live | dead | 비율 |")
        emit("|---|---|---|---|")
        for ratio, t in sorted(bl, reverse=True):
            emit(f"| `{t.name}` | {t.live:,} | {t.dead:,} | {ratio * 100:.1f}% |")
    else:
        emit("_해당 없음_")
    emit()

    # ── 합계 ───────────────────────────────────────────────────────────────
    emit("## 합계")
    emit()
    emit(f"회수 가능 추정 **{human(recoverable)}** / DB {human(db_bytes)} "
         f"({recoverable / max(db_bytes, 1) * 100:.1f}%)")
    emit()
    emit("⚠ 합계는 추정이다 — W1 은 표본 투영, W4 는 하한(varlena 정렬 무시)이고, W3·W4 는")
    emit("서로 완전히 가법적이지 않다(상수 컬럼을 드롭하면 패딩 배치가 바뀐다). 실행 전 항목별 실측 필요.")

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"\n→ 저장: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
