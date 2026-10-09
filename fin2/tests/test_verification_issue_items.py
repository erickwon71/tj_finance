"""Issue items built from machine findings (vq.py machine issues-json --findings): the tool,
not the model, decides error_type, field strings and the (#n) key, so every verifier model
registers the same issue for the same finding (2026-10-09, Haiku/Sonnet parity)."""
from fin2.verification import machine_pass as mp


def _value(db, src, scale=1, found=(), flipped=(), st="SCE", label="배당", **kw):
    return {"kind": "value", "basis": "consolidated", "statement": st, "label": label, "db": db,
            "src": src, "scale": scale, "found_at": list(found), "flipped_at": list(flipped),
            "src_col": 2, "header": "이익잉여금", "db_col": "자본>이익잉여금",
            "block_end": "2023.12.31 (기말자본)", **kw}


def test_error_type_follows_symptom_table():
    assert mp.cell_error_type(_value(-100, 100.0))[0] == "sign_flip"
    assert mp.cell_error_type(_value(100_000, 100.0))[0] == "unit_scale"
    assert mp.cell_error_type(_value(-100_000, 100.0))[1].endswith("(부호도 다름)")
    assert mp.cell_error_type(_value(5, 0.0, found=[1])) == ("value_mismatch", "원문 빈 칸")
    # D = 0 never becomes a misassign just because some other column is blank
    assert mp.cell_error_type(_value(0, 7.0, found=[3])) == ("value_mismatch", "DB 빈 칸")
    assert mp.cell_error_type(_value(8, 7.0, found=[3]))[0] == "column_misassign"
    assert mp.cell_error_type(_value(8, 7.0, found=[3], st="IS"))[0] == "period_misassign"
    assert mp.cell_error_type(_value(8, 7.0))[0] == "value_mismatch"
    assert mp.cell_error_type(_value(8, "1.234.5"))[0] == "value_mismatch"


def test_select_keeps_the_same_key_whatever_subset_is_registered():
    fs = [_value(-1, 1.0, label="배당"), _value(-2, 2.0, label="배당"), _value(-3, 3.0, label="배당")]
    both = mp.findings_to_issues(fs, select=[2, 3], prefix="[확인 x]")
    only3 = mp.findings_to_issues(fs, select=[3], prefix="[확인 x]")
    assert [i["account_label"] for i in both] == ["배당 (#2)", "배당 (#3)"]
    assert only3[0]["account_label"] == "배당 (#3)"
    assert only3[0]["column_label"] == "자본>이익잉여금 @ 2023.12.31"
    assert only3[0]["evidence"].startswith("[확인 x]")


def test_identity_finding_becomes_source_defect_only_when_source_breaks_too():
    f = {"kind": "sce_arith", "basis": "separate", "statement": "SCE", "check": "flow", "col": 1,
         "from": "2023.01.01 (기초자본)", "to": "2023.12.31 (기말자본)", "start": 10.0, "end": 30.0,
         "sum": 20.0, "diff": 10.0, "scale": 1000, "header": "이익잉여금", "src_broken": True}
    [it] = mp.findings_to_issues([f], select=[1], prefix="[확인 x]")
    assert it["error_type"] == "source_defect"
    assert it["column_label"] == "이익잉여금 @ 2023.12.31 #항등식"
    assert it["db_value"] == 30_000 and it["source_unit"] == "천원"
    assert mp.findings_to_issues([dict(f, src_broken=False)], select=[1]) == []   # I2


def test_kinds_path_unchanged_for_bulk_registration():
    fs = [_value(-1, 1.0), {"kind": "zero_row", "basis": "consolidated", "statement": "BS",
                            "label": "기타", "cells": [0.0]}]
    items = mp.findings_to_issues(fs, ("value",))
    assert len(items) == 1 and items[0]["error_type"] == "sign_flip"


def test_source_defect_reports_the_printed_closing_not_the_db_value():
    # mc8: a column whose closing cell the DB stores with the other sign - the identity item
    # must carry the printed value as source_value (the reviewer compares the web view with it)
    f = {"kind": "sce_arith", "basis": "consolidated", "statement": "SCE", "check": "flow", "col": 2,
         "from": "2023.01.01 (기초자본)", "to": "2023.09.30 (기말자본)", "start": -5.0, "end": -129.0,
         "src_start": -5.0, "src_end": 129.0, "sum": -35.0, "diff": -94.0, "scale": 1,
         "header": "기타자본구성요소", "db_col": "자본>기타자본구성요소", "src_broken": True}
    [it] = mp.findings_to_issues([f], select=[1], prefix="[확인 x]")
    assert it["db_value"] == -129 and it["source_value"] == 129 and it["source_value_raw"] == "129"
    assert it["column_label"] == "자본>기타자본구성요소 @ 2023.09.30 #항등식"


def test_source_defect_column_tail_is_normalized():
    from fin2.verification.ops import _identity_column_label
    assert _identity_column_label("자본>이익잉여금 @ 2019.06.30 #롤포워드") == "자본>이익잉여금 @ 2019.06.30 #항등식"
    assert _identity_column_label("자본>이익잉여금 @ 2019.06.30") == "자본>이익잉여금 @ 2019.06.30 #항등식"
    assert _identity_column_label(None) == "#항등식"
    assert _identity_column_label("# 항등식") == "#항등식"
