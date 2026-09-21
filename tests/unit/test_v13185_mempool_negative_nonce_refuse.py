#!/usr/bin/env python3
"""v1.3.185: P2P refuses nonce<0 before validate_transaction."""

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
    cfg.p2p_mempool_negative_nonce_refuse = True
    cfg.p2p_mempool_min_fee_refuse = False
    cfg.p2p_mempool_max_gas_refuse = False
    cfg.p2p_mempool_max_calldata_refuse = False
    cfg.p2p_mempool_negative_value_refuse = False
    chain = MagicMock()
    chain.get_height.return_value = 1
    chain.get_state_root.return_value = "ee" * 32
    chain.validate_transaction = MagicMock(return_value={"valid": True})
    mp = MagicMock()
    mp.min_fee = 0.0
    mp.has_transaction = MagicMock(return_value=False)
    return P2PNode(cfg, chain, mp)


def _wire(*, nonce: int, fee: float = 1.0, tx_hash: str = "ab" * 32) -> dict:
    return {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1,
        "nonce": nonce,
        "gas": 21_000,
        "fee": fee,
        "signature": "sig",
        "public_key": "pk",
        "hash": tx_hash,
        "data": "",
    }


def _build(node: P2PNode, payload: dict):
    if native.validate_p2p_wire_tx(payload):
        return node._build_mempool_tx_from_wire(payload)
    orig = native.validate_p2p_wire_tx
    try:
        native.validate_p2p_wire_tx = lambda _d: True  # type: ignore
        return node._build_mempool_tx_from_wire(payload)
    finally:
        native.validate_p2p_wire_tx = orig  # type: ignore


def test_needles_v13185():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "nonce_negative" in p2p
    assert "p2p_mempool_negative_nonce_refuse" in p2p
    assert "native_mempool_negative_nonce_refuse" in p2p
    assert "_mempool_nonce_refuse_total" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_mempool_negative_nonce_refuse" in cfg
    assert "P2P_MEMPOOL_NEGATIVE_NONCE_REFUSE" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.185.md").read_text(encoding="utf-8")
    assert "1.3.185-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_negative_nonce_refuse" in metrics
    assert "abs_p2p_mempool_nonce_refuse_total" in metrics


def test_refuse_negative_nonce_before_validate():
    node = _node()
    out = _build(node, _wire(nonce=-1))
    assert out is None
    assert node._last_tx_wire_reject == "nonce_negative"
    assert node._mempool_nonce_refuse_total >= 1
    node.blockchain.validate_transaction.assert_not_called()


def test_ok_zero_nonce_reaches_validate():
    node = _node()
    out = _build(node, _wire(nonce=0))
    assert out is not None
    node.blockchain.validate_transaction.assert_called()
    assert node._mempool_nonce_refuse_total == 0


def test_security_status_gauge():
    node = _node()
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_negative_nonce_refuse") is True
