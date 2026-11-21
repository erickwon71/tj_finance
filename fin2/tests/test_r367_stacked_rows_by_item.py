"""R367: stacked rows expand per item when exactly one label cell has as many lines as the values;
R366-b: a raw newline inside a value-only cell is printed whitespace, not a stack."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lxml import etree  # noqa: E402

from collector.biz_metrics import _map_row  # noqa: E402
from fin2.extract.biz_section import (  # noqa: E402
    biz_raw_prepass, expand_stacked_rows, expand_table_grid, join_wrapped_number)
from fin2.extract.order_backlog import map_order_table  # noqa: E402
from parser.xml.dart_xml_parser import sanitize_dart_xml  # noqa: E402


def _grid(xml: str) -> list[list[str]]:
    raw = sanitize_dart_xml(biz_raw_prepass(xml.encode("utf-8")))
    return expand_table_grid(etree.fromstring(raw, etree.XMLParser(recover=True)))


def test_prepass_keeps_label_lines_only_in_stacked_rows():
    g = _grid("<TABLE><TR><TD>알루미늄폼(임대)&cr;판넬폼(갱폼)</TD><TD>167,334&cr;23,018</TD></TR>"
              "<TR><TD>대손충당금&cr;환입</TD><TD>1,234</TD></TR>"
              "<TR><TD>A&cr;B</TD><TD>728&cr;2,397</TD></TR></TABLE>")
    assert g[0] == ["알루미늄폼(임대)\n판넬폼(갱폼)", "167,334\n23,018"]
    assert g[1] == ["대손충당금환입", "1,234"]          # not stacked: R224 as before
    assert g[2] == ["A\nB", "728\n2,397"]                # R246 alone could not split 728&cr;2,397


def test_prepass_raw_newline_in_value_cell_is_whitespace():
    g = _grid("<TABLE><TR><TD>배 치</TD><TD>1\n55</TD><TD>-\n15.71</TD><TD>제품\n상품</TD></TR></TABLE>")
    assert g[0] == ["배 치", "1 55", "- 15.71", "제품\n상품"]
    assert join_wrapped_number("1 55") == "155" and join_wrapped_number("- 15.71") == "-15.71"
    assert join_wrapped_number("1,000 2,000") == "1,000 2,000"


def test_expand_one_label_with_n_lines_shared_other_labels():
    rows = [["강북\n힐튼점", "바카라\n블랙잭\n룰렛", "35\n6\n3", "34\n7\n3"]]
    assert expand_stacked_rows(rows, [0, 1], [2, 3]) == [
        ["강북힐튼점", "바카라", "35", "34"], ["강북힐튼점", "블랙잭", "6", "7"], ["강북힐튼점", "룰렛", "3", "3"]]


def test_no_expand_when_two_labels_have_n_lines_or_single_value_beside():
    assert expand_stacked_rows([["의약품 및\n의약외품", "향남공장\n광주영업", "21,035\n196"]], [0, 1], [2]) == []
    assert expand_stacked_rows([["A\nB", "1\n2", "1,217,500"]], [0], [1, 2]) == []
    # dash lines are values of single items
    assert expand_stacked_rows([["A\nB", "14,884\n-"]], [0], [1]) == [["A", "14,884"], ["B", "-"]]


def test_order_table_expands_per_item():
    # 금강공업 FY2015 20160330001190 수주 (after the R367 re-read)
    grid = [
        ["품 목", "수주일자", "납 기", "수주총액", "수주총액", "기납품액", "기납품액", "수주잔고", "수주잔고"],
        ["품 목", "수주일자", "납 기", "수 량", "금 액", "수 량", "금 액", "수 량", "금 액"],
        ["알루미늄폼(임대)\n판넬폼(갱폼)", "2015.01~12\n2015.01~12", "2016.12\n2016.12", "",
         "167,334\n23,018", "", "120,178\n9,464", "", "47,156\n13,554"],
        ["합    계", "합    계", "합    계", "", "190,352", "", "129,642", "", "60,710"],
    ]
    rows = {r.category: r for r in map_order_table(grid)}
    assert (rows["알루미늄폼(임대)"].contract_total, rows["알루미늄폼(임대)"].backlog_amt) == (167334, 47156)
    assert (rows["판넬폼(갱폼)"].contract_total, rows["판넬폼(갱폼)"].backlog_amt) == (23018, 13554)


def test_sales_table_channel_lines():
    # 금강공업 FY2019 sales: 매출유형 cell keeps 내수/수출/계 lines after the R367 re-read
    grid = [
        ["구 분", "품목", "매출유형", "제41기 연간"],
        ["구 분", "품목", "매출유형", "금 액"],
        ["제 품", "강  관", "내  수\n수  출\n계", "89,661\n18,076\n107,737"],
    ]
    vals = sorted(r["value"] for r in _map_row("sales", "sales", "", grid, 2019))
    assert vals == [18076, 89661, 107737]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok {name}")
            except AssertionError as e:
                failed += 1
                print(f"  FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
