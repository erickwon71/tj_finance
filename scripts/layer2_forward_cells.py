"""계층2 정방향 셀 커버리지 — **원문 셀 → 추출기** 구간 (READ-ONLY, 샤딩 지원).

`layer2_fidelity_full.py` 가 못 보는 구간을 메운다. 그쪽의 "정방향"은
**추출기 출력 → DB** 비교라서, 추출기가 원문 셀을 애초에 못 본 경우엔 추출 결과와 DB가
똑같이 비어 있어 통과한다. 2026-07-29 sanitize 결함(성일하이텍 셀 1,143→6,011)이 바로
그 실패 모드였고, 그 도구로는 재발을 못 잡는다.

측정 방식 — 추측하지 않고 **추출기와 같은 코드 경로를 계측**한다(교훈 §7)
------------------------------------------------------------------
적재 대상 표마다 원문 금액 셀을 전수로 세고, 방출되지 않은 셀을 **사유별로 전부
귀속**시킨다. 사유 없이 사라지는 셀(`설명안됨`)이 0 이어야 한다.

    원문 금액셀
      ├─ 헤더행드롭   : `_is_header_cell`/`_is_fs_title_row` 가 데이터행을 헤더로 오판
      │                 (★SCE date_labels_ok 결함이 이 버킷이었다 — 2,519행 유실)
      ├─ 라벨없음     : `_split_label_amounts` 가 라벨을 못 뽑음 → 귀속 불가로 폐기
      ├─ 열절단       : `extract_rows(num_cols=N)` 의 `range(num_cols)` 가 N 번째 이후를
      │                 **조용히 버린다**. 본문 3(다열 8) · 주석 8 · SCE 12
      ├─ interim3개월 : 누적열 표에서 3개월 열 배제(의도)
      └─ 방출         : 추출기가 실제로 낸 셀
    표 단위 폐기       : 단위미선언 · 데이터행없음 · 2단표중복배제 (전부 의도)

`열절단`·`헤더행드롭`·`라벨없음` 은 **의도된 폐기가 아니다** — 0 이 목표이며 값이 크면
그만큼 원문이 DB 에 없다는 뜻이다.

Usage
-----
    python scripts/layer2_forward_cells.py --limit 30            # 표본
    python scripts/layer2_forward_cells.py --shard 0/6           # 전수(샤드)
    python scripts/layer2_forward_cells.py --year 2024 --limit 0 # 특정 연도 전수
    python scripts/layer2_forward_cells.py --rcept 20250311000123 --limit 0  # 1건 상세
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from collector.db import get_session
from fin2.extract.report_lines import (_NOTE_MAX_COLS, _SCE_MAX_COLS,
                                       _detect_period_layout,
                                       extract_report_lines)
from fin2.extract.text import (_SECTION_META, _detect_body_statement_tables,
                               _detect_fin_type, _interim_cumulative_cols,
                               _table_has_data_rows, declared_unit)
from parser.common.amount_normalizer import parse_amount
from parser.xml.dart_xml_parser import _parse_xml_file
from parser.xml.section_detector import (SEC_CONSOL_NOTE, SEC_SEP_NOTE,
                                         assign_note_tables_with_titles,
                                         table_direct_rows)
from parser.xml.table_extractor import (_get_cells, _is_fs_title_row,
                                        _is_header_cell, _split_label_amounts)

TARGETS_SQL = """
    SELECT f.rcept_no, f.corp_code, f.fiscal_year, f.fiscal_period, d.file_path
    FROM filings f JOIN download_tasks d USING (rcept_no)
    WHERE d.status='completed' AND d.file_type='xml' AND d.file_path IS NOT NULL
      AND f.fiscal_year >= 2015
      {year_clause}{rcept_clause}
    ORDER BY f.rcept_no
"""


class TableScan:
    """한 표의 셀 회계. 카운트만 하며 값 판단은 하지 않는다."""

    __slots__ = ("header_drop", "no_label", "truncated", "candidate", "cand_pos",
                 "num_cols", "mult", "eps_pass")

    def __init__(self) -> None:
        self.header_drop = 0      # 헤더로 오판된 행의 금액 셀
        self.no_label = 0         # 라벨을 못 뽑은 행의 금액 셀
        self.truncated = 0        # num_cols 밖으로 잘린 셀 ★
        self.candidate = 0        # extract_rows 가 amounts 로 넘긴 non-None 셀
        self.cand_pos = defaultdict(set)  # row_order -> {col 위치}
        self.num_cols = 0         # 이 표에 적용된 절단 한계(진단용)
        self.mult = 1             # 방출기가 이 표를 순회하는 횟수(중복 객체면 >1)
        self.eps_pass = 0         # '주당' 행 — EPS 별도 패스가 방출(유실 아님)

    @property
    def source(self) -> int:
        return (self.header_drop + self.no_label + self.truncated
                + self.candidate + self.eps_pass)


_RULE_HITS: Counter[str] = Counter()


def _which_header_rule(text: str, allow_date_label: bool) -> str:
    """`_is_header_cell` 의 어느 규칙이 이 행을 헤더로 판정했는지 — 오판 원인 계량용."""
    import re as _re
    if not allow_date_label and _re.search(r"\d{4}[.\-년]", text):
        return "날짜"
    if _re.search(r"제\s*\d+\s*기", text):
        return "기수(제N기)"
    if _re.search(r"단위\s*[:\(]", text):
        return "단위표기"
    if _re.fullmatch(r"[구과]\s*[분목]", text):
        return "구분/과목"
    if _re.fullmatch(r"[\s()]*(?:(?:당|전)?(?:분|반)?기?)?[\s()]*\d+\s*개월[\s()]*(?:누적)?[\s()]*", text):
        return "N개월"
    if _re.fullmatch(r"\d분기", text):
        return "N분기"
    if _re.search(r"\d{4}\.\d{2}\.\d{2}[~\-～]", text):
        return "날짜범위"
    if text.startswith("(기준일") or text.startswith("기준일"):
        return "기준일"
    if _re.fullmatch(r"(당기|전기|당기초|전기초|당분기|전분기|당반기|전반기)(말|초)?", text):
        return "★당기말/전기말류"
    if _re.fullmatch(r"수준\s*[123]", text):
        return "공정가치수준"
    if _re.fullmatch(r"[\s\-\─\—\―　]*", text):
        return "빈셀/대시"
    return "재무제표제목행(_is_fs_title_row)"


def scan_table(table, unit: int, num_cols: int, *,
               date_labels_ok: bool = False, preserve: bool = False,
               sink: list | None = None) -> TableScan:
    """`extract_rows` 의 행/셀 취급을 **그대로** 재현하되, 버려지는 셀을 사유별로 센다.

    재현 대상: `table_direct_rows` → `_get_cells` → `_is_header_cell` /
    `_is_fs_title_row` → `_split_label_amounts` → `parse_amount` → 선행 None pop →
    `range(num_cols)` 절단. 계층2 는 `skip_junk=False` 라 블록리스트는 적용하지 않는다.
    """
    sc = TableScan()
    row_order = 0
    for tr in table_direct_rows(table):
        cells = _get_cells(tr)
        if not cells:
            continue
        first_text = cells[0].strip()

        # 헤더/제목 오판으로 데이터행이 통째로 날아가는 경우를 잡으려면, 드롭된 행에도
        # 금액이 몇 개 있었는지 세어야 한다(드롭 자체는 정상 동작일 수도 있다).
        if _is_header_cell(first_text, allow_date_label=date_labels_ok) or _is_fs_title_row(cells):
            _, amt_cells = _split_label_amounts(cells)
            hit = [c for c in amt_cells if parse_amount(c, unit) is not None]
            # ★'주당' 행은 유실이 아니다 — `_is_header_cell` 이 '(단위 : 원)' 을 보고 본류에서
            #   빼는 건 의도된 설계이고, `_emit_eps_lines` 가 인라인 단위로 따로 방출한다.
            #   초판이 이걸 헤더드롭으로 세어 320만 셀을 과대계상했다.
            if "주당" in first_text:
                sc.eps_pass += len(hit)
            else:
                sc.header_drop += len(hit)
                if hit:
                    _RULE_HITS[_which_header_rule(first_text, date_labels_ok)] += len(hit)
            if sink is not None and hit:
                sink.append(("헤더드롭", first_text[:40], -1, " | ".join(hit[:4])))
            continue

        label, amt_cells = _split_label_amounts(cells)
        all_parsed = [parse_amount(c, unit) for c in amt_cells]
        if not label:
            sc.no_label += sum(1 for v in all_parsed if v is not None)
            continue

        # 6-column IS 대응 선행 None pop — 값을 지우진 않지만 위치를 당기므로,
        # 어떤 셀이 num_cols 밖으로 밀리는지가 여기서 갈린다. 반드시 같이 재현해야 한다.
        popped = 0                       # pop 된 만큼 amt_cells 원문 인덱스가 어긋난다
        if len(all_parsed) >= 4 and not preserve:
            while all_parsed and all_parsed[0] is None:
                all_parsed.pop(0)
                popped += 1

        for i, v in enumerate(all_parsed):
            if v is None:
                continue
            if i < num_cols:
                sc.candidate += 1
                sc.cand_pos[row_order].add(i)
            else:
                sc.truncated += 1
                if sink is not None:
                    raw = amt_cells[i + popped] if i + popped < len(amt_cells) else "?"
                    sink.append(("열절단", label.strip()[:40], i, raw))
        row_order += 1
    return sc


def scan_filing(root, f, sink: dict | None = None) -> tuple[Counter, dict]:
    """filing 하나의 셀 회계. 반환 = (카운터, 표별 상세).

    `sink` 를 주면 표별로 버려진 셀의 **원문 텍스트**를 담는다(`--dump`) — 유실이 진짜인지
    원문에서 확인하려면 라벨·열위치·원문 셀값이 필요하다.
    """
    t: Counter[str] = Counter()
    detail: dict[tuple, TableScan] = {}

    # ── 본문 + SCE : `extract_report_lines` 의 표 스코프를 그대로 재현
    fin_type = _detect_fin_type(root)
    groups = _detect_body_statement_tables(root, fin_type, include_sce=True)
    for code, tables_with_unit in groups.items():
        basis = _SECTION_META[code][0]
        is_sce = code.startswith("SCE")
        statement = "SCE" if is_sce else code.split("_")[0]
        tables = [tb for tb, _, _ in tables_with_unit]
        unit_of = {id(tb): u for tb, u, _ in tables_with_unit}
        interim_flow = (not is_sce and statement in ("IS", "CF")
                        and f.fiscal_period in ("H1", "Q1", "Q3"))
        cum_maps = {id(tb): (_interim_cumulative_cols(tb) if interim_flow else None)
                    for tb in tables}
        has_2tier = interim_flow and any(v is not None for v in cum_maps.values())

        # ★방출기의 table_seq 규약을 그대로 재현한다: `doc_seq = {id(t): i ...}` 는 dict 라
        #   **같은 표 객체가 두 번 들어 있으면 마지막 인덱스가 이깁니다**. 그러면 방출기는 그
        #   표를 두 번 순회하며 둘 다 같은 table_seq 로 내보내, 같은 키·같은 값 행이 두 벌
        #   생긴다(전수 실측 `report_lines` 중복 키 1,076,974 그룹의 정체).
        #   여기서 dedupe 하지 않으면 앞 인덱스가 '방출 0' 으로 잡혀 허위 '설명안됨' 이 된다.
        # ★방출기와 **같은 순서로** dedupe 한 뒤 doc_seq 를 매겨야 한다. 방출기는
        #   `tables = list(dict.fromkeys(tables))` 후 인덱스를 매기므로, 중복이 있으면
        #   dedupe 전 인덱스와 어긋나 table_seq 키가 밀린다(그러면 표 전체가 '방출 0' 으로
        #   잡혀 허위 '설명안됨' 이 된다 — 실측 600 filing 에서 6,296 셀).
        t["표:중복객체"] += len(tables) - len(dict.fromkeys(tables))
        tables = list(dict.fromkeys(tables))
        doc_seq = {id(tb): i for i, tb in enumerate(tables)}
        for tb in tables:
            seq = doc_seq[id(tb)]
            unit = unit_of[id(tb)]
            cum_map = cum_maps[id(tb)]
            if unit is None:
                t["표:폐기(단위 미선언)"] += 1
                continue
            if not is_sce and has_2tier and cum_map is None:
                t["표:폐기(2단표 중복배제)"] += 1
                continue
            t["표:적재대상"] += 1

            n_periods, multicol = 0, False
            if is_sce:
                num_cols, dlo, preserve = _SCE_MAX_COLS, True, True
            else:
                dlo = preserve = False
                if cum_map is not None:
                    num_cols = max(cum_map) + 1
                else:
                    n_periods, multicol = _detect_period_layout(tb)
                    num_cols = 8 if multicol else 3

            key = (statement, basis, seq)
            bucket = sink.setdefault(key, []) if sink is not None else None
            sc = scan_table(tb, unit, num_cols, date_labels_ok=dlo, preserve=preserve,
                            sink=bucket)
            sc.num_cols = num_cols
            # ★방출기가 2026-07-30 부터 `tables` 를 dedupe 하므로 순회는 항상 1 회다.
            #   (그 전에는 중복 객체를 두 번 순회해 같은 값 행이 두 벌 쌓였다.)
            sc.mult = 1
            detail[key] = sc
            # ★다열(보험/증권) 표는 비어있지 않은 금액을 압축해 **앞 n_periods 개만** 방출한다
            #   (`_emit_section_lines`: `pairs = list(enumerate(present[:n_periods]))`).
            #   그 뒤는 의도된 배제다 — 이걸 안 세면 '설명안됨' 으로 잡힌다(초판이 그랬다).
            if multicol and n_periods:
                for cols in sc.cand_pos.values():
                    # ★x mult — 중복 객체 표는 방출기가 그 횟수만큼 순회하므로 배제도 그만큼
                    #   일어난다. 안 곱하면 그 차이가 통째로 '설명안됨' 으로 잡힌다.
                    t["cell:multicol압축배제"] += max(0, len(cols) - n_periods) * sc.mult

            # interim 누적열 표는 cum_map 위치만 방출한다(의도된 3개월 열 배제).
            if cum_map is not None:
                keep = set(cum_map)
                for cols in sc.cand_pos.values():
                    # ★x mult — 위와 같은 이유(중복 순회). 실측: IS 중복표에서 이 누락이
                    #   전수 '설명안됨' 104,068 의 대부분(IS 99%)을 만들었다.
                    t["cell:interim3개월"] += sum(1 for c in cols if c not in keep) * sc.mult

    # ── 주석 : `_emit_note_lines` 의 표 스코프를 그대로 재현
    sec_tables = assign_note_tables_with_titles(root)
    for sec_kind, basis in ((SEC_CONSOL_NOTE, "consolidated"), (SEC_SEP_NOTE, "separate")):
        for seq, (tb, _title) in enumerate(sec_tables.get(sec_kind, [])):
            unit = declared_unit(tb)
            if unit is None:
                t["표:폐기(단위 미선언)"] += 1
                continue
            if not _table_has_data_rows(tb):
                t["표:폐기(데이터행 없음)"] += 1
                continue
            t["표:적재대상"] += 1
            key = ("note", basis, seq)
            sc = scan_table(tb, unit, _NOTE_MAX_COLS,
                            sink=sink.setdefault(key, []) if sink is not None else None)
            sc.num_cols = _NOTE_MAX_COLS
            detail[key] = sc

    for k, sc in detail.items():
        # ★statement 별로 나눠 센다 — 절단의 실질 우선순위가 다르기 때문이다.
        #   note  : `note_da.py:44` 가 col 필터 없이 전부 읽고 주석 열은 전부 실데이터 → P0
        #   본문  : 잘리는 건 전기·전전기이고 2026-07-30 결정으로 적재 대상도 아님 → 무영향
        #   SCE   : 열=자본 구성요소. 신 체인은 col_index=0 만 읽음
        bucket = "note" if k[0] == "note" else ("SCE" if k[0] == "SCE" else "본문")
        t["cell:원문"] += sc.source
        t["cell:헤더행드롭"] += sc.header_drop
        t["cell:EPS별도패스"] += sc.eps_pass
        t["cell:라벨없음"] += sc.no_label
        t["cell:열절단"] += sc.truncated
        t["cell:후보"] += sc.candidate
        t[f"cell:원문:{bucket}"] += sc.source
        t[f"cell:열절단:{bucket}"] += sc.truncated
        t[f"cell:후보:{bucket}"] += sc.candidate
    return t, detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--rcept", default=None, help="단건 지정")
    ap.add_argument("--limit", type=int, default=30, help="0 = 전수")
    ap.add_argument("--shard", help="a/n")
    ap.add_argument("--seed", type=int, default=20260730)
    ap.add_argument("--top", type=int, default=10, help="절단/미설명 최악 filing 표시 수")
    ap.add_argument("--dump", type=int, default=0,
                    help="버려진 셀의 원문 텍스트를 N 건까지 출력(원문 대조용). --rcept 와 함께")
    args = ap.parse_args()

    t: Counter[str] = Counter()
    worst: list[tuple[int, str, str]] = []
    worst_unexp: list[tuple[int, str, str]] = []
    t0 = time.time()

    with get_session() as session:
        rows = list(session.execute(
            text(TARGETS_SQL.format(
                year_clause="AND f.fiscal_year = :y" if args.year else "",
                rcept_clause="AND f.rcept_no = :r" if args.rcept else "")),
            {k: v for k, v in (("y", args.year), ("r", args.rcept)) if v},
        ).fetchall())
        if args.shard:
            a, n = (int(x) for x in args.shard.split("/"))
            rows = [r for i, r in enumerate(rows) if i % n == a]
        elif args.limit:
            random.Random(args.seed).shuffle(rows)
            rows = rows[: args.limit]
    print(f"대상 {len(rows)} filing", flush=True)

    for i, f in enumerate(rows, 1):
        if i % 200 == 0:
            el = time.time() - t0
            print(f"  … {i}/{len(rows)} ({el/i:.2f}s/filing)", flush=True)
        p = Path(f.file_path)
        if not p.exists():
            t["파일없음"] += 1
            continue
        try:
            # ★추출기와 같은 파싱 경로(sanitize + 인코딩 판정)를 반드시 쓴다. 직접
            #   fromstring 하면 구형 EUC-KR 보고서에서 허위 결과가 난다(교훈 §7).
            root = _parse_xml_file(p)
            if root is None:
                t["파싱실패"] += 1
                continue
            sink: dict | None = {} if args.dump else None
            ft, detail = scan_filing(root, f, sink)
            emitted = extract_report_lines(
                str(p), rcept_no=f.rcept_no, corp_code=f.corp_code,
                report_fiscal_year=f.fiscal_year,
                report_fiscal_period=f.fiscal_period, include_notes=True)
        except Exception as e:  # noqa: BLE001
            t["스캔실패"] += 1
            if len(worst) < args.top:
                worst.append((0, f.rcept_no, f"스캔실패 {type(e).__name__}: {e}"))
            continue

        t["filing"] += 1
        t.update(ft)

        # 방출 셀을 표 단위로 집계해 '후보' 와 맞춘다. 남는 것이 설명 안 되는 유실이다.
        em_by_tbl: Counter[tuple] = Counter()
        for x in emitted:
            if x.value_won is not None:
                em_by_tbl[(x.statement, x.basis, x.table_seq)] += 1
        t["cell:방출"] += sum(em_by_tbl.values())

        unexplained = 0
        gaps: list[tuple[int, str]] = []
        for k, sc in detail.items():
            # 중복 객체 표는 방출기가 mult 번 순회하므로 기대 방출 = 후보 x mult 다.
            gap = sc.candidate * sc.mult - em_by_tbl.get(k, 0)
            if gap > 0:
                unexplained += gap
                t[f"cell:설명안됨:{k[0]}"] += gap
                gaps.append((gap, f"{k[0]}/{k[1]} seq={k[2]} num_cols={sc.num_cols} "
                                  f"후보={sc.candidate}x{sc.mult} 방출={em_by_tbl.get(k, 0)}"))
        # interim 3개월 열 배제는 의도된 것이므로 미설명에서 뺀다.
        unexplained -= ft["cell:interim3개월"] + ft["cell:multicol압축배제"]
        # 표 스코프 밖에서 방출된 셀(EPS 등 별도 패스)이 있으면 gap 이 음수가 될 수 있어
        # 표별 양수 gap 만 합산했다. 음수는 별도로 드러낸다.
        over = sum(max(0, em_by_tbl.get(k, 0) - sc.candidate * sc.mult)
                   for k, sc in detail.items())
        t["cell:후보초과방출"] += over
        t["cell:설명안됨"] += max(0, unexplained)
        if unexplained > 0 and gaps:
            gaps.sort(reverse=True)
            worst_unexp.append((unexplained, f.rcept_no, gaps[0][1]))
            if len(worst_unexp) > args.top * 8:
                worst_unexp.sort(key=lambda x: x[0], reverse=True)
                del worst_unexp[args.top:]

        if sink is not None:
            shown = 0
            for k, items in sink.items():
                if not items:
                    continue
                sc = detail[k]
                print(f"\n  [{f.rcept_no}] {k[0]}/{k[1]} table_seq={k[2]} "
                      f"num_cols={sc.num_cols} · 원문 {sc.source} 방출후보 {sc.candidate}")
                for kind, lbl, pos, raw in items:
                    print(f"    {kind} col={pos:<3} {lbl:<40} 원문셀='{raw}'")
                    shown += 1
                    if shown >= args.dump:
                        break
                if shown >= args.dump:
                    break

        loss = ft["cell:열절단"] + ft["cell:헤더행드롭"] + ft["cell:라벨없음"] + max(0, unexplained)
        if loss > 0:
            # 최악 N 건을 유지한다(처음 N 건이 아니라 — 전수에서 앞부분만 보면 의미가 없다).
            worst.append((loss, f.rcept_no,
                          f"절단 {ft['cell:열절단']} · 헤더드롭 {ft['cell:헤더행드롭']} · "
                          f"라벨없음 {ft['cell:라벨없음']} · 미설명 {max(0, unexplained)} "
                          f"· 원문 {ft['cell:원문']}"))
            if len(worst) > args.top * 8:
                worst.sort(key=lambda x: x[0], reverse=True)
                del worst[args.top:]

    el = time.time() - t0
    n = max(t["filing"], 1)
    src = max(t["cell:원문"], 1)
    print(f"\n=== 계층2 정방향 셀 커버리지 (filing {n}, {el:.0f}s, {el/n:.2f}s/filing) ===")
    print(f"  적재대상 표 {t['표:적재대상']:,} · 폐기 "
          f"단위미선언 {t['표:폐기(단위 미선언)']:,} · "
          f"데이터행없음 {t['표:폐기(데이터행 없음)']:,} · "
          f"2단중복 {t['표:폐기(2단표 중복배제)']:,}")
    print(f"  원문 금액셀 {t['cell:원문']:,}")
    for k, label, intended in (
        ("cell:방출", "방출(추출기 산출)", True),
        ("cell:interim3개월", "interim 3개월열 배제", True),
        ("cell:multicol압축배제", "다열 압축 배제(보험/증권)", True),
        ("cell:EPS별도패스", "EPS 별도 패스(유실 아님)", True),
        ("cell:열절단", "★열절단(num_cols 초과)", False),
        ("cell:헤더행드롭", "★헤더행 오판 드롭", False),
        ("cell:라벨없음", "★라벨 없는 행", False),
        ("cell:설명안됨", "★설명안됨", False),
    ):
        mark = " " if intended else "!"
        print(f"   {mark} {label:<24} {t[k]:>12,} ({t[k]/src*100:6.3f}%)")
    cov = t["cell:방출"] / src * 100
    print(f"\n  방출 커버리지 {cov:.3f}%  (목표: 절단·헤더드롭·라벨없음·설명안됨 = 0)")

    print("\n  ── statement 별 열절단 (실질 우선순위가 다르다) ──")
    for b, why in (("note", "★P0 — note_da 가 전 열을 읽는다"),
                   ("본문", "무영향 — 잘리는 건 전기·전전기(적재 대상 아님)"),
                   ("SCE", "신 체인은 col0 만 읽음")):
        s_b = max(t[f"cell:원문:{b}"], 1)
        print(f"    {b:<5} 원문 {t[f'cell:원문:{b}']:>12,} · 절단 {t[f'cell:열절단:{b}']:>10,} "
              f"({t[f'cell:열절단:{b}']/s_b*100:6.3f}%)  {why}")
    if t["cell:후보초과방출"]:
        print(f"  참고 후보초과방출 {t['cell:후보초과방출']:,} "
              f"(EPS 등 표 스코프 밖 별도 패스 — 결함 아님)")
    for k in ("파일없음", "파싱실패", "스캔실패"):
        if t[k]:
            print(f"  {k}: {t[k]}")
    if _RULE_HITS:
        print("\n  ── 헤더 오판 드롭: 어느 규칙이 잡았나 ──")
        tot = sum(_RULE_HITS.values())
        for rule, n in _RULE_HITS.most_common(8):
            print(f"    {rule:<28} {n:>8,} ({n/tot*100:5.2f}%)")

    if t["cell:설명안됨"]:
        print("\n  ── ★설명안됨 statement 별 ──")
        for b in ("note", "SCE", "BS", "IS", "CF"):
            if t[f"cell:설명안됨:{b}"]:
                print(f"    {b:<5} {t[f'cell:설명안됨:{b}']:>10,}")
        worst_unexp.sort(key=lambda x: x[0], reverse=True)
        print("  ── 설명안됨 상위 filing ──")
        for n, r, msg in worst_unexp[: args.top]:
            print(f"    {r}  미설명 {n:>6}  최대표: {msg}")

    if worst:
        worst.sort(key=lambda x: x[0], reverse=True)
        print(f"\n--- 확인 대상 filing (유실 상위 {min(args.top, len(worst))}) ---")
        for _, r, msg in worst[: args.top]:
            print(f"  {r}  {msg}")
        print("  → 원문 확인: .venv/bin/python scripts/show_note_source.py <rcept_no>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
