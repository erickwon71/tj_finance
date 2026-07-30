"""문서 전 섹션 표 귀속 감사 — 보고서의 숫자가 **어디로도 가지 않는 곳**을 찾는다 (READ-ONLY).

왜 필요한가
-----------
지금까지의 검증은 전부 "만들어 둔 추출기가 제 일을 하는가" 였다. 그래서 **추출기가 아예 없는
섹션**은 어떤 지표에도 나타나지 않는다 — 완전성 100%, 충실성 100% 를 받아도 보고서의 절반이
DB 에 없을 수 있다. 이 도구는 방향을 뒤집어 **원문 문서에서 시작**해, 모든 섹션의 모든 표를
세고 각 섹션에 소비자가 있는지 확인한다.

무엇이 증명되고 무엇이 안 되는가 (과장 금지)
--------------------------------------------
  증명됨   : 섹션별 표 수·숫자 셀 수 (원문 실측)
  증명됨   : 그 섹션을 읽는 추출기가 코드에 있는지 (아래 _CONSUMERS 는 코드 독해로 선언)
  증명됨   : 선언된 목적지 테이블에 그 filing 의 행이 실제로 있는지 (DB 조회)
  **안 됨**: 개별 원문 표 하나가 DB 의 특정 행으로 갔는지. report_lines/note_lines 는
             table_seq 로 추적되지만 biz_metrics 등은 추출기 고유 순번을 쓰므로 1:1 대응이
             복원되지 않는다. 그래서 이 도구는 **섹션 단위**로만 귀속을 말한다.

`_CONSUMERS` 는 추측이 아니라 코드에서 읽어낸 것이다:
  · report_lines/note_lines : section_detector.DART_BODY_SECTIONS / DART_NOTE_SECTIONS
  · biz_metrics 계열        : biz_section/sales_section/order_backlog/rd_note 가 모두
                              '사업의 내용' 섹션 안에서 heading 키워드로 표를 찾는다
  · shares                  : '주식의 총수 등' 섹션 직후 표
  · 그 외 부가 테이블       : collector/dart_periodic.py·dart_client.py = **DART API 유래**
                              (문서를 읽지 않는다) → 문서 관점에서는 '미귀속' 으로 센다.
                              CLAUDE.md 원칙("문서로부터 가져올 것")과의 괴리를 드러내기 위함.

Usage
-----
    python scripts/audit_document_census.py --limit 300           # 층화표본(권장 1차)
    python scripts/audit_document_census.py --shard 0/6           # 전수
    python scripts/audit_document_census.py --limit 300 --out docs/qa/document_census.md
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (assign_tables_to_dart_sections,
                                         normalize_dart_section_title,
                                         table_direct_rows)
from parser.xml.table_extractor import _get_cells

_NUMERIC_CELL = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?%?$")

# ── 섹션 → 소비 추출기 / DB 테이블. **코드 독해로 선언**한다(추측 아님. docstring 참고).
#    값 = (표시명, [그 filing 의 적재를 확인할 테이블…]). 빈 리스트 = 의도적 미적재.
_CONSUMERS: dict[str, tuple[str, list[str]]] = {
    "연결재무제표":     ("report_lines", ["report_lines"]),
    "재무제표":         ("report_lines", ["report_lines"]),
    "연결재무제표주석": ("note_lines", ["note_lines"]),
    "재무제표주석":     ("note_lines", ["note_lines"]),
    "사업의내용":       ("biz_metrics·order_backlog·biz_section_tables",
                        ["biz_metrics", "biz_section_tables", "order_backlog"]),
    "주식의총수등":     ("shares", []),
    "요약재무정보":     ("의도적 제외(본문으로 안 씀)", []),
}

# API 유래 테이블이 '같은 주제' 를 담고 있는 섹션 — 문서에서는 안 읽지만 값이 DB 에 있다.
# 미귀속으로 세되 이 사실을 함께 표시해, 원문 대조가 불가능한 항목을 가려낸다.
# 'II. 사업의 내용' 의 하위 항목 표제(실측 40건 전수에서 확인된 표기). 이들이 자기
# SECTION-2 를 가지면 `assign_tables_to_dart_sections` 가 분류 불가 TITLE 에서 current 를
# 해제하므로, 그 아래 표는 '사업의내용' 귀속에서 빠지고 biz 추출기 3종이 못 본다.
_BIZ_SUBSECTIONS = frozenset({
    "사업의개요", "주요제품및서비스", "원재료및생산설비", "매출및수주상황",
    "위험관리및파생거래", "주요계약및연구개발활동", "기타참고사항",
    "영업의현황", "영업설비", "재무건전성등기타참고사항",
    "생산설비(연구설비)에관한사항(상세)", "지적재산권현황(상세)",
})

_API_TOPIC: dict[str, str] = {
    "배당에관한사항":          "dividend_facts (API)",
    "주주에관한사항":          "major_shareholders (API)",
    "소액주주현황":            "retail_ownership (API)",
    "최대주주변동내역":        "shareholder_changes (API)",
    "임원및직원등의현황":      "executives·employee_stats (API)",
    "임원의보수등":            "exec_pay_summary (API)",
    "타법인출자현황(상세)":    "other_investments (API)",
    "자본금변동사항":          "capital_events (API)",
    "주식의총수등":            "treasury_activity (API)",
}

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
      {year_clause}
    ORDER BY f.rcept_no
"""


def is_top_level_table(el) -> bool:
    """중첩 TABLE 의 안쪽은 세지 않는다 — 깨진 원문에서 wrapper 가 문서 전체를 품으면
    같은 표를 몇 번씩 세게 된다(table_direct_rows docstring 의 그 사고와 같은 뿌리)."""
    anc = el.getparent()
    while anc is not None:
        if isinstance(anc.tag, str) and anc.tag.upper() == "TABLE":
            return False
        anc = anc.getparent()
    return True


def numeric_cells(tbl) -> int:
    n = 0
    for tr in table_direct_rows(tbl):
        for c in _get_cells(tr):
            s = c.strip().replace(" ", "").replace("　", "")
            if s and _NUMERIC_CELL.match(s) and any(ch.isdigit() for ch in s):
                n += 1
    return n


def scan_filing(root) -> dict[str, tuple[int, int]]:
    """{정규화 섹션명: (표 수, 숫자셀 수)}.

    ★ 귀속은 **문서 순서**로 한다 — DART 의 SECTION-2 는 형제가 아니라 계단식 중첩이라
    포함관계로는 경계가 안 잡힌다(section_detector.assign_tables_to_dart_sections 의 실측 근거).
    분류 가능한 섹션만 보는 그 함수와 달리, 여기서는 **모든 TITLE** 을 추적한다 — 분류
    불가한 섹션이야말로 이 감사의 대상이기 때문이다.
    """
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    current = "(섹션 없음)"
    for el in root.iter():
        tag = el.tag.upper() if isinstance(el.tag, str) else ""
        if tag.startswith("SECTION"):
            te = el.find("TITLE")
            if te is not None:
                t = normalize_dart_section_title("".join(te.itertext()))
                if t:
                    current = t
        elif tag == "TABLE" and is_top_level_table(el):
            out[current][0] += 1
            out[current][1] += numeric_cells(el)
    return {k: (v[0], v[1]) for k, v in out.items()}


def drill(session, rcept_no: str) -> int:
    """단건 드릴 — 문서 실측 섹션 vs **추출기가 실제로 보는 귀속**을 나란히 보여준다.

    핵심 질문에 답하기 위한 것: '사업의 내용' 하위 항목이 자기 SECTION-2 를 가지면
    `assign_tables_to_dart_sections` 는 분류 불가 TITLE 에서 current 를 **해제**하므로
    그 표들이 사업의내용 귀속에서 빠진다 — 그러면 biz_section·order_backlog·rd_note 가
    표를 못 본다. 그 가설을 문서 하나에서 직접 확인한다(집계로 단정하지 않는다).
    """
    row = session.execute(text(
        "SELECT d.file_path FROM download_tasks d WHERE d.rcept_no=:r "
        "AND d.file_type='xml' AND d.file_path IS NOT NULL LIMIT 1"),
        {"r": rcept_no}).fetchone()
    if not row:
        print(f"{rcept_no}: 원본 없음")
        return 1
    root = _parse_xml_file(Path(row.file_path))
    if root is None:
        print(f"{rcept_no}: 파싱 실패")
        return 1

    secs = scan_filing(root)
    assigned = assign_tables_to_dart_sections(root)
    print(f"\n=== {rcept_no} 문서 실측 섹션 (숫자셀 있는 것만) ===")
    for name, (ntab, ncell) in sorted(secs.items(), key=lambda x: -x[1][1]):
        if ncell == 0:
            continue
        mark = "소비자O" if name in _CONSUMERS else "미귀속 "
        print(f"  {mark} {name:<44} 표{ntab:>5} 셀{ncell:>7}")

    print(f"\n=== assign_tables_to_dart_sections 가 실제로 귀속시킨 표 ===")
    print("  (추출기들이 보는 것. 위 문서 실측과 차이나는 만큼이 추출기 사각이다)")
    for kind, tbls in assigned.items():
        print(f"  {kind:<20} {len(tbls):>6} 표")
    if not assigned.get("사업의내용"):
        print("  ★ '사업의내용' 귀속 표 = 0 → biz_section·order_backlog·rd_note 는 "
              "이 보고서에서 아무 표도 못 본다")

    print(f"\n=== DB 적재 실측 ===")
    for tbl in ("report_lines", "note_lines", "biz_metrics",
                "biz_section_tables", "order_backlog"):
        n = session.execute(text(f"SELECT count(*) FROM {tbl} WHERE rcept_no=:r"),
                            {"r": rcept_no}).scalar()
        print(f"  {tbl:<22} {n:>10,} 행")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--rcept", help="단건 드릴 — 문서 섹션 vs 추출기 귀속 대조")
    ap.add_argument("--limit", type=int, default=300, help="0 = 전수")
    ap.add_argument("--shard", help="a/n")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--out", help="마크다운 저장 경로")
    args = ap.parse_args()

    if args.rcept:
        with get_session() as s:
            return drill(s, args.rcept)

    tables_of: Counter[str] = Counter()
    cells_of: Counter[str] = Counter()
    filings_of: Counter[str] = Counter()
    t = Counter()
    t0 = time.time()

    with get_session() as session:
        rows = list(session.execute(
            text(TARGETS_SQL.format(
                year_clause="AND f.fiscal_year = :y" if args.year else "")),
            {"y": args.year} if args.year else {}).fetchall())
        if args.shard:
            a, n = (int(x) for x in args.shard.split("/"))
            rows = [r for i, r in enumerate(rows) if i % n == a]
        elif args.limit:
            random.Random(args.seed).shuffle(rows)
            rows = rows[: args.limit]
        print(f"대상 {len(rows)} filing", flush=True)

        # 선언된 목적지에 실제로 행이 있는지 — '배선했다는데 비어 있음' 을 잡는다.
        wired_empty: Counter[str] = Counter()
        checked: Counter[str] = Counter()

        for i, f in enumerate(rows, 1):
            if i % 50 == 0:
                el = time.time() - t0
                print(f"  … {i}/{len(rows)} ({el/i:.2f}s/filing)", flush=True)
            p = Path(f.file_path)
            if not p.exists():
                t["파일없음"] += 1
                continue
            try:
                root = _parse_xml_file(p)
                if root is None:
                    t["파싱실패"] += 1
                    continue
                secs = scan_filing(root)
            except Exception as e:  # noqa: BLE001
                t["스캔실패"] += 1
                if t["스캔실패"] <= 3:
                    print(f"  ! {f.rcept_no}: {type(e).__name__}: {e}")
                continue
            t["filing"] += 1

            for name, (ntab, ncell) in secs.items():
                tables_of[name] += ntab
                cells_of[name] += ncell
                filings_of[name] += 1

            # ★ biz 추출기 사각 측정 — '사업의 내용' 하위 항목이 자기 SECTION-2 를 가지면
            #   assign_tables_to_dart_sections 가 표를 귀속시키지 못한다(원문 대조로 확인:
            #   20240613000108 → 사업의내용 귀속 0 표 · biz_metrics 0 행).
            sub_cells = sum(c for nm, (_t, c) in secs.items() if nm in _BIZ_SUBSECTIONS)
            if sub_cells > 0:
                t["biz:하위항목_숫자셀보유_filing"] += 1
                t["biz:하위항목_숫자셀"] += sub_cells
                try:
                    seen = len(assign_tables_to_dart_sections(root).get("사업의내용", []))
                except Exception:  # noqa: BLE001
                    seen = -1
                if seen == 0:
                    t["★biz:추출기가_못보는_filing"] += 1
                    t["★biz:추출기가_못보는_숫자셀"] += sub_cells

            # 그 filing 이 선언된 목적지에 적재됐는지 확인
            for name, (_label, dests) in _CONSUMERS.items():
                if name not in secs or not dests:
                    continue
                for d in dests:
                    checked[f"{name}→{d}"] += 1
                    col = "rcept_no" if d in ("report_lines", "note_lines",
                                              "biz_metrics", "biz_section_tables",
                                              "order_backlog") else None
                    if col is None:
                        continue
                    n = session.execute(
                        text(f"SELECT 1 FROM {d} WHERE {col} = :r LIMIT 1"),
                        {"r": f.rcept_no}).fetchone()
                    if n is None:
                        wired_empty[f"{name}→{d}"] += 1

    el = time.time() - t0
    nf = max(t["filing"], 1)
    out: list[str] = []

    def emit(s: str = "") -> None:
        out.append(s)
        print(s)

    emit(f"# 문서 전 섹션 표 귀속 감사 — filing {nf:,} ({el:.0f}s, {el/nf:.2f}s/filing)")
    emit()
    total_cells = sum(cells_of.values())
    emit(f"표 {sum(tables_of.values()):,} · 숫자셀 {total_cells:,}")
    emit()

    covered_cells = unattributed_cells = 0
    lines_cov: list[tuple[int, str]] = []
    lines_gap: list[tuple[int, str]] = []
    for name, cells in cells_of.items():
        ntab = tables_of[name]
        share = cells / max(total_cells, 1) * 100
        if name in _CONSUMERS:
            label = _CONSUMERS[name][0]
            covered_cells += cells
            lines_cov.append((cells, f"| `{name}` | {ntab:,} | {cells:,} | {share:.2f}% "
                                     f"| {label} |"))
        else:
            api = _API_TOPIC.get(name, "")
            unattributed_cells += cells
            lines_gap.append((cells, f"| `{name}` | {ntab:,} | **{cells:,}** | {share:.2f}% "
                                     f"| {filings_of[name]:,} | {api or '— 없음'} |"))

    emit("## 1. 소비자가 있는 섹션")
    emit()
    emit("| 섹션 | 표 | 숫자셀 | 비중 | 소비 추출기 |")
    emit("|---|---|---|---|---|")
    for _, line in sorted(lines_cov, reverse=True):
        emit(line)
    emit()

    emit("## 2. ★미귀속 — 문서 추출기가 없는 섹션 (숫자셀 내림차순)")
    emit()
    emit("'API' 열이 있으면 같은 주제가 DART API 로 DB 에 들어와 있다는 뜻이다. 값은 있지만")
    emit("**원문 대조 검증이 불가능**하고 CLAUDE.md 원칙(문서로부터 수집)과 어긋난다.")
    emit()
    emit("| 섹션 | 표 | 숫자셀 | 비중 | 보유 filing | 현재 소스 |")
    emit("|---|---|---|---|---|---|")
    for _, line in sorted(lines_gap, reverse=True)[:45]:
        emit(line)
    emit()
    emit(f"**미귀속 숫자셀 {unattributed_cells:,} / {total_cells:,} "
         f"({unattributed_cells / max(total_cells, 1) * 100:.2f}%)**")
    emit()

    if t["biz:하위항목_숫자셀보유_filing"]:
        a = t["biz:하위항목_숫자셀보유_filing"]
        b = t["★biz:추출기가_못보는_filing"]
        emit("## 3. ★'사업의 내용' 섹션 귀속 붕괴 — **`rd_note` 한정**")
        emit()
        emit("`assign_tables_to_dart_sections` 는 분류 불가 TITLE 에서 현재 섹션을 **해제**한다")
        emit("(`section_detector.py:206`, 오귀속 방지 목적). '사업의 내용' 의 하위 항목")
        emit("(`원재료및생산설비`·`매출및수주상황` 등)이 자기 SECTION-2 를 가지면 바로 그 해제가")
        emit("일어나 하위 표 전부가 '사업의내용' 귀속에서 빠진다.")
        emit()
        emit("**영향 범위는 이 귀속 함수를 쓰는 추출기뿐이다** — 코드 확인 결과:")
        emit("- `rd_note.py:56` → `assign_tables_to_dart_sections` 사용 ⇒ **영향 받음**")
        emit("- `biz_section.py:213` · `order_backlog.py:85` → `root.iter()` 로 문서 전체를")
        emit("  훑고 heading 키워드로 찾는다 ⇒ **이 메커니즘의 영향 없음**")
        emit()
        emit("> 초안은 세 추출기 모두가 영향을 받는다고 썼다. 코드를 확인하니 틀렸다.")
        emit("> §4 의 `biz_metrics`·`order_backlog` 공백은 **원인이 다르며 미규명**이다.")
        emit()
        emit("| 하위항목에 숫자셀이 있는 filing | 그중 사업의내용 귀속 0 표 | 비율 |")
        emit("|---|---|---|")
        emit(f"| {a:,} | **{b:,}** | **{b / max(a, 1) * 100:.1f}%** |")
        emit()
        emit(f"귀속에서 빠진 숫자셀 **{t['★biz:추출기가_못보는_숫자셀']:,}** / "
             f"하위항목 총 {t['biz:하위항목_숫자셀']:,}")
        emit()
        emit("원문 대조 확인: `20240613000108` — 사업의내용 귀속 **0 표**인데 문서에는")
        emit("`원재료및생산설비` 8 표·`매출및수주상황` 4 표가 있다 (`--rcept` 로 재현).")
        emit()

    if wired_empty:
        emit("## 4. 배선됐다고 선언했는데 그 filing 에 행이 없음")
        emit()
        emit("섹션은 문서에 있고 추출기도 있는데 DB 에 행이 0 인 경우. 원문에 실제 데이터가")
        emit("없을 수도 있으므로 결함 확정이 아니라 **조사 대상**이다.")
        emit()
        emit("⚠ `biz_section`·`order_backlog` 는 §3 의 귀속 붕괴와 **무관한 경로**(문서 전체")
        emit("`root.iter()` + heading 키워드)를 쓴다. 따라서 아래 공백의 원인은 별도 규명 대상이다 —")
        emit("heading 키워드 미스매치인지, 원문에 데이터가 없는 것인지 아직 모른다.")
        emit()
        emit("| 섹션→테이블 | 대상 filing | 행 0 | 비율 |")
        emit("|---|---|---|---|")
        for k, v in sorted(wired_empty.items(), key=lambda x: -x[1]):
            c = checked[k]
            emit(f"| `{k}` | {c:,} | **{v:,}** | {v / max(c, 1) * 100:.1f}% |")
        emit()

    for k in ("파일없음", "파싱실패", "스캔실패"):
        if t[k]:
            emit(f"- {k}: {t[k]}")

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"\n→ 저장: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
