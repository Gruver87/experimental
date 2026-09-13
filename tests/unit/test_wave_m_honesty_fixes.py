"""Wave M: BFT int quorum, lightning/plasma satoshi, ZK/WASM honesty."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_bft_quorum_integer_two_thirds():
    from consensus.bft.quorum import quorum_reached

    assert quorum_reached(2, 3) is True
    assert quorum_reached(1, 3) is False
    assert quorum_reached(0, 0) is False


def test_validator_info_stake_satoshi():
    from consensus.bft.types import ValidatorInfo
    from runtime.amount import to_satoshi

    v = ValidatorInfo(validator_id="0xabc", stake=100.0)
    assert v.stake == int(to_satoshi(100.0))
    assert isinstance(v.stake, int)


def test_zk_system_info_fail_closed():
    from core.components.zk_gateway import FeaturesZkGateway

    class _Boom:
        def get_system_info(self):
            raise RuntimeError("probe down")

    info = FeaturesZkGateway(_Boom()).system_info()
    assert info["enabled"] is False
    assert "error" in info


def test_wasm_pseudo_transfer_refused():
    src = (Path(__file__).resolve().parents[2] / "features" / "wasm_vm.py").read_text(
        encoding="utf-8"
    )
    assert "wasm_pseudo_token_host_refused" in src
    assert '"enabled": bool(wt)' in src or "'enabled': bool(wt)" in src


def test_plasma_l2_balance_satoshi_helpers():
    src = (Path(__file__).resolve().parents[2] / "features" / "plasma.py").read_text(
        encoding="utf-8"
    )
    assert "_l2_balance_sat" in src
    assert "float(dep.get(\"amount\"" not in src
