"""R317 - quarter / half / connected total comprehensive income wordings are not net income."""
import pytest

from fin2.layer3.combine import _FS, _map_label


@pytest.mark.parametrize("label", [
    "분기포괄이익(손실)", "반기포괄이익(손실)", "연결분기포괄손실", "연결반기포괄손실", "연결분기총포괄손실",
    "연결반기총포괄손실", "분기순포괄손익", "반기순포괄손익", "당(분)기총포괄이익(손실)", "당(반)기총포괄이익(손실)"])
def test_comprehensive_income_wording_maps_to_total_comprehensive_income(label):
    r = _map_label(label, _FS["IS"])
    assert r.account_code == "is.total_comprehensive_income" and r.stage == "exact"


@pytest.mark.parametrize("label", ["당(반)기순이익", "반기순이익(손실)", "연결반기순손실"])
def test_net_income_wording_is_unchanged(label):
    assert _map_label(label, _FS["IS"]).account_code == "is.net_income"
