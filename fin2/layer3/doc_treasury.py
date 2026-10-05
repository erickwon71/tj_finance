"""계층3 — 자기주식 취득 및 처분 현황(treasury_activity)을 원문 표에서 만든다
(API→문서 전환 Phase 6). 서식 코드 OWN_SHR (DART tesstkAcqsDspsSttus 가 같은 표를 옮긴 것).

API 판과 다른 점: 취득방법 라벨을 DART 표준명('소계', '총계', '기타취득')으로 바꾸지 않고 **원문
라벨 그대로**('소계(a)', '총 계(a+b+c)', '기타 취득(c)'), 행 순서도 원문 순서 그대로 담는다.
앱(`app/data/shareholder_return.load_treasury_activity_detail`)은 라벨로 거르지 않고 전 행을
표시하므로 원문 표기가 그대로 보이는 쪽이 맞다. 수량 단위는 '주'.
"""
from __future__ import annotations

from fin2.layer3.doc_common import (find_col, header_paths, main_grid, parse_int,
                                    pick_filing_grids, split_header, text_or_none)


def _cell(row, c):
    return row[c] if c is not None and c < len(row) else None


def map_treasury(grid) -> list[dict]:
    header, body = split_header(grid)
    p = header_paths(header)
    method_cols = [i for i, path in enumerate(p) if path and "취득방법" in path[0]][:3]
    c = {
        "kind": find_col(p, "종류"), "begin": find_col(p, "기초"),
        "acq": find_col(p, "변동", leaf="취득"), "dsp": find_col(p, "변동", leaf="처분"),
        "inc": find_col(p, "변동", leaf="소각"), "end": find_col(p, "기말"),
        "rm": find_col(p, "비고"),
    }
    if not method_cols or c["kind"] is None or c["end"] is None:
        return []
    out = []
    for row in body:
        methods = [text_or_none(_cell(row, i), 60) for i in method_cols] + [None, None, None]
        if not any(methods):
            continue
        rm = text_or_none(_cell(row, c["rm"]), 200)
        kind = text_or_none(_cell(row, c["kind"]), 20)
        out.append({
            "stock_kind": None if kind == "-" else kind,
            "acqs_method1": methods[0], "acqs_method2": methods[1], "acqs_method3": methods[2],
            "qty_begin": parse_int(_cell(row, c["begin"])),
            "qty_acquired": parse_int(_cell(row, c["acq"])),
            "qty_disposed": parse_int(_cell(row, c["dsp"])),
            "qty_incinerated": parse_int(_cell(row, c["inc"])),
            "qty_end": parse_int(_cell(row, c["end"])),
            "remark": None if rm == "-" else rm,
        })
    return out


def build_rows(session, corps: list[str], fy_min: int = 2015) -> list[dict]:
    out = []
    for (corp, fy), (rcept, grids) in pick_filing_grids(session, corps, "OWN_SHR", fy_min).items():
        for r in map_treasury(main_grid(grids)):
            out.append({"corp_code": corp, "fiscal_year": fy, "rcept_no": rcept, **r})
    return out
