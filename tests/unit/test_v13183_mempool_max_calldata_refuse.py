#!/usr/bin/env python3
"""v1.3.183: P2P refuses oversized calldata before validate_transaction."""

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


def _node(*, max_cd: int = 64) -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.bootstrap_peers = []
    cfg.p2p_mempool_max_calldata_refuse = True
    cfg.p2p_mempool_max_calldata_bytes = max_cd
    cfg.p2p_mempool_min_fee_refuse = False
    cfg.p2p_mempool_max_gas_refuse = False
    chain = MagicMock()
    chain.get_height.return_value = 1
    chain.get_state_root.return_value = "ee" * 32
    chain.validate_transaction = MagicMock(return_value={"valid": True})
    mp = MagicMock()
    mp.min_fee = 0.0
    mp.has_transaction = MagicMock(return_value=False)
    return P2PNode(cfg, chain, mp)


def _wire(*, data: str, fee: float = 1.0, tx_hash: str = "ab" * 32) -> dict:
    return {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1,
        "nonce": 0,
        "gas": 21_000,
        "fee": fee,
        "signature": "sig",
        "public_key": "pk",
        "hash": tx_hash,
        "data": data,
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


def test_needles_v13183():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "calldata_too_large" in p2p
    assert "_wire_calldata_byte_len" in p2p
    assert "native_mempool_max_calldata_refuse" in p2p
    assert "_mempool_calldata_refuse_total" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_mempool_max_calldata_refuse" in cfg
    assert "P2P_MEMPOOL_MAX_CALLDATA_REFUSE" in cfg
    assert "p2p_mempool_max_calldata_bytes" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.183.md").read_text(encoding="utf-8")
    assert "1.3.183-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_max_calldata_refuse" in metrics
    assert "abs_p2p_mempool_calldata_refuse_total" in metrics


def test_refuse_oversized_hex_before_validate():
    node = _node(max_cd=16)
    # 0x + 40 hex chars => 20 bytes > 16
    out = _build(node, _wire(data="0x" + "ab" * 20))
    assert out is None
    assert node._last_tx_wire_reject == "calldata_too_large"
    assert node._mempool_calldata_refuse_total >= 1
    node.blockchain.validate_transaction.assert_not_called()


def test_ok_small_calldata_reaches_validate():
    node = _node(max_cd=64)
    out = _build(node, _wire(data="0x" + "cd" * 8))
    assert out is not None
    node.blockchain.validate_transaction.assert_called()
    assert node._mempool_calldata_refuse_total == 0


def test_security_status_gauge():
    node = _node()
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_max_calldata_refuse") is True
