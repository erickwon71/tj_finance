"""R316 - 'consolidated' + 'quarter / half' + 'net loss' wordings are net income."""
import pytest

from fin2.layer3.combine import _FS, _map_label


@pytest.mark.parametrize("label", ["연결분기순손실", "연결반기순손실", "분기연결순손실", "반기연결순손실"])
def test_connected_quarter_half_net_loss_is_net_income(label):
    r = _map_label(label, _FS["IS"])
    assert r.account_code == "is.net_income" and r.stage == "exact"


