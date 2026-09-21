#!/usr/bin/env python3
"""Wave A: unparseable wire fields refuse (no except: pass fallthrough)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from network.p2p_node import P2PNode
from runtime.config import Config


def _node() -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.bootstrap_peers = []
    cfg.p2p_mempool_min_fee_refuse = False
    cfg.p2p_mempool_max_fee_refuse = False
    cfg.p2p_mempool_max_gas_refuse = False
    cfg.p2p_mempool_max_calldata_refuse = False
    cfg.p2p_mempool_negative_value_refuse = True
    cfg.p2p_mempool_nonfinite_value_refuse = False
    cfg.p2p_mempool_max_value_refuse = False
    cfg.p2p_mempool_negative_nonce_refuse = True
    cfg.p2p_mempool_max_nonce_refuse = False
    cfg.p2p_mempool_negative_fee_refuse = True
    cfg.p2p_mempool_nonfinite_fee_refuse = False
    cfg.p2p_mempool_negative_gas_refuse = True
    chain = MagicMock()
    chain.get_height.return_value = 1
    chain.get_state_root.return_value = "ee" * 32
    chain.validate_transaction = MagicMock(return_value={"valid": True})
    mp = MagicMock()
    mp.min_fee = 0.0
    mp.has_transaction = MagicMock(return_value=False)
    return P2PNode(cfg, chain, mp)


def _wire(**overrides) -> dict:
    base = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1,
        "nonce": 0,
        "gas": 21_000,
        "fee": 1.0,
        "signature": "sig",
        "public_key": "pk",
        "hash": "ab" * 32,
        "data": "",
    }
    base.update(overrides)
    return base


def _build(node: P2PNode, payload: dict):
    orig = native.validate_p2p_wire_tx
    try:
        native.validate_p2p_wire_tx = lambda _d: True  # type: ignore
        return node._build_mempool_tx_from_wire(payload)
    finally:
        native.validate_p2p_wire_tx = orig  # type: ignore


def test_value_unparseable_refuses() -> None:
    node = _node()
    out = _build(node, _wire(value="not-a-number"))
    assert out is None
    assert node._last_tx_wire_reject == "value_unparseable"
    node.blockchain.validate_transaction.assert_not_called()


def test_nonce_unparseable_refuses() -> None:
    node = _node()
    out = _build(node, _wire(nonce="x"))
    assert out is None
    assert node._last_tx_wire_reject == "nonce_unparseable"
    node.blockchain.validate_transaction.assert_not_called()


def test_source_no_pass_fallthrough_on_value_gate() -> None:
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert 'self._last_tx_wire_reject = "value_unparseable"' in p2p
    assert 'self._last_tx_wire_reject = "nonce_unparseable"' in p2p
    assert 'self._last_tx_wire_reject = "fee_unparseable"' in p2p
