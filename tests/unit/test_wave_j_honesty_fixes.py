"""Wave J: L2 satoshi debit, eth_call honesty, fee satoshi, smart-account 501, tip prod."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_will_debit_uses_satoshi_helpers():
    from features.crypto_will import CryptoWillManager
    from runtime.amount import to_satoshi

    class _DB:
        def __init__(self):
            self.sat = { "0xa": to_satoshi(100) }
            self.deltas = []

        def get_balance_satoshi(self, addr):
            return int(self.sat.get(addr, 0))

        def balance_delta_satoshi(self, addr, delta):
            self.deltas.append((addr, int(delta)))
            self.sat[addr] = int(self.sat.get(addr, 0)) + int(delta)

    db = _DB()
    mgr = CryptoWillManager(db=db, blockchain=None)
    assert mgr._debit("0xa", 25.0) is True
    assert db.deltas == [("0xa", -to_satoshi(25))]
    assert mgr._debit("0xa", 1000.0) is False


def test_eth_call_missing_adapter_errors():
    from api.fake_rpc import FakeRpcClient

    client = FakeRpcClient()
    # FakeRpc has no EVM → must not return success "0x"
    out = client.call("eth_call", [{"to": "0x" + "11" * 20, "data": "0x"}])
    assert out.get("error") is not None
    assert "evm adapter unavailable" in str(out["error"].get("message", "")).lower() or \
           "evm adapter unavailable" in str(out.get("error"))


def test_p2p_negative_fee_uses_to_satoshi_not_float_compare():
    root = Path(__file__).resolve().parents[2]
    src = (root / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "to_satoshi(fee))" in src or "to_satoshi(fee)" in src
    assert "float(fee) < 0.0" not in src


def test_smart_account_create_refuses_without_executor():
    from features.smart_accounts import SmartAccountManager

    out = SmartAccountManager().create_account("0x" + "a" * 40)
    assert out["success"] is False
    assert out["http_status"] == 501


def test_tip_evidence_prod_unbound_refuse():
    from network.p2p_dispatch.tip_evidence import TipSafetyEvidenceBridge

    d = TipSafetyEvidenceBridge(
        shadow_provider=lambda: None,
        deployment_mode="prod",
    ).evaluate_block_candidate({"height": 1, "hash": "aa" * 32}, MagicMock())
    assert d.ok is False
    assert d.reason_code == "tip_evidence_unbound"
