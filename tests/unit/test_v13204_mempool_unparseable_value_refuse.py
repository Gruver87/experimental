#!/usr/bin/env python3
"""v1.3.204: P2P refuses unparseable value before validate_transaction."""

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
    cfg.bootstrap_peers = []
    cfg.p2p_mempool_unparseable_value_refuse = True
    cfg.p2p_mempool_unparseable_gas_refuse = False
    cfg.p2p_mempool_negative_value_refuse = False
    cfg.p2p_mempool_nonfinite_value_refuse = False
    cfg.p2p_mempool_max_value_refuse = False
    cfg.p2p_mempool_max_fee_refuse = False
    cfg.p2p_mempool_min_fee_refuse = False
    cfg.p2p_mempool_negative_fee_refuse = False
    cfg.p2p_mempool_nonfinite_fee_refuse = False
    cfg.p2p_mempool_empty_from_refuse = False
    cfg.p2p_mempool_empty_to_refuse = False
    cfg.p2p_mempool_max_from_refuse = False
    cfg.p2p_mempool_max_to_refuse = False
    cfg.p2p_mempool_empty_hash_refuse = False
    cfg.p2p_mempool_max_hash_refuse = False
    cfg.p2p_mempool_empty_sig_refuse = False
    cfg.p2p_mempool_empty_pubkey_refuse = False
    cfg.p2p_mempool_max_sig_refuse = False
    cfg.p2p_mempool_max_pubkey_refuse = False
    cfg.p2p_mempool_max_gas_refuse = False
    cfg.p2p_mempool_max_calldata_refuse = False
    cfg.p2p_mempool_negative_nonce_refuse = False
    cfg.p2p_mempool_max_nonce_refuse = False
    cfg.p2p_mempool_negative_gas_refuse = False
    chain = MagicMock()
    chain.get_height.return_value = 1
    chain.get_state_root.return_value = "ee" * 32
    chain.validate_transaction = MagicMock(return_value={"valid": True})
    mp = MagicMock()
    mp.min_fee = 0.0
    mp.has_transaction = MagicMock(return_value=False)
    return P2PNode(cfg, chain, mp)


def _wire(*, value, fee: float = 1.0, tx_hash: str = "ab" * 32) -> dict:
    return {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": value,
        "nonce": 0,
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


def test_needles_v13204():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "value_unparseable" in p2p
    assert "p2p_mempool_unparseable_value_refuse" in p2p
    assert "native_mempool_unparseable_value_refuse" in p2p
    assert "_mempool_value_unparseable_refuse_total" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_mempool_unparseable_value_refuse" in cfg
    assert "P2P_MEMPOOL_UNPARSEABLE_VALUE_REFUSE" in cfg
    notes = (ROOT / "RELEASE_NOTES_v1.3.204.md").read_text(encoding="utf-8")
    assert "1.3.204-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_unparseable_value_refuse" in metrics
    assert "abs_p2p_mempool_value_unparseable_refuse_total" in metrics


def test_refuse_junk_value_before_validate():
    node = _node()
    out = _build(node, _wire(value="not-a-number"))
    assert out is None
    assert node._last_tx_wire_reject == "value_unparseable"
    assert node._mempool_value_unparseable_refuse_total >= 1
    node.blockchain.validate_transaction.assert_not_called()


def test_refuse_object_value_before_validate():
    node = _node()
    out = _build(node, _wire(value={"x": 1}, tx_hash="cd" * 32))
    assert out is None
    assert node._last_tx_wire_reject == "value_unparseable"


def test_ok_numeric_value_reaches_validate():
    node = _node()
    out = _build(node, _wire(value=1.25, tx_hash="ef" * 32))
    assert out is not None
    node.blockchain.validate_transaction.assert_called()
    assert node._mempool_value_unparseable_refuse_total == 0


def test_refuse_bool_value_before_validate():
    node = _node()
    out = _build(node, _wire(value=True, tx_hash="b0" * 32))
    assert out is None
    assert node._last_tx_wire_reject == "value_unparseable"
    node.blockchain.validate_transaction.assert_not_called()


def test_refuse_hex_value_before_validate():
    node = _node()
    out = _build(node, _wire(value="0xde0b6b3a7640000", tx_hash="b1" * 32))
    assert out is None
    assert node._last_tx_wire_reject == "value_unparseable"


def test_refuse_bool_fee_before_validate():
    node = _node()
    out = _build(node, _wire(value=1.0, fee=True, tx_hash="b2" * 32))
    assert out is None
    assert node._last_tx_wire_reject == "fee_unparseable"


def test_security_status_gauge():
    node = _node()
    st = node.get_p2p_security_status()
    assert st.get("native_mempool_unparseable_value_refuse") is True
