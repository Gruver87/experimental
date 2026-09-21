"""ADR 0021 wire money cutover: fee_satoshi / amount_satoshi canonical on P2P."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.mempool import MempoolTransaction
from blockchain.mempool_wire import (
    WireMoneyMismatch,
    WireMoneyMissing,
    mempool_tx_to_wire,
    resolve_wire_amount_sat,
    resolve_wire_fee_sat,
)
from crypto import native
from network.p2p_node import P2PNode
from runtime.amount import from_satoshi_float, to_satoshi
from runtime.config import Config


def _node(*, require_wire_satoshi: bool = True) -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    cfg.p2p_mempool_min_fee_refuse = False
    cfg.p2p_mempool_max_gas_refuse = False
    cfg.p2p_mempool_max_calldata_refuse = False
    cfg.p2p_mempool_negative_value_refuse = True
    cfg.p2p_mempool_negative_fee_refuse = True
    cfg.p2p_mempool_require_wire_satoshi = require_wire_satoshi
    chain = MagicMock()
    chain.get_height.return_value = 1
    chain.get_state_root.return_value = "ee" * 32
    chain.validate_transaction = MagicMock(return_value={"valid": True})
    mp = MagicMock()
    mp.min_fee = 0.0
    mp.min_fee_satoshi = 0
    mp.has_transaction = MagicMock(return_value=False)
    return P2PNode(cfg, chain, mp)


def _build(node: P2PNode, payload: dict):
    if native.validate_p2p_wire_tx(payload):
        return node._build_mempool_tx_from_wire(payload)
    orig = native.validate_p2p_wire_tx
    try:
        native.validate_p2p_wire_tx = lambda _d: True  # type: ignore
        return node._build_mempool_tx_from_wire(payload)
    finally:
        native.validate_p2p_wire_tx = orig  # type: ignore


def test_mempool_tx_to_wire_emits_satoshi_canonical():
    amount_sat = int(to_satoshi(3.5))
    fee_sat = int(to_satoshi(0.01))
    tx = MempoolTransaction(
        tx_hash="0xwire1",
        from_addr="0x" + "1" * 40,
        to_addr="0x" + "2" * 40,
        amount=3.5,
        fee=0.01,
        amount_satoshi=amount_sat,
        fee_satoshi=fee_sat,
        nonce=0,
        signature="0xsig",
        public_key="0xpub",
        data="0x",
        gas=21000,
    )
    wire = mempool_tx_to_wire(tx)
    assert wire["amount_satoshi"] == amount_sat
    assert wire["fee_satoshi"] == fee_sat
    assert wire["amount"] == from_satoshi_float(amount_sat)
    assert wire["fee"] == from_satoshi_float(fee_sat)
    assert wire["value"] == wire["amount"]


def test_resolve_prefer_satoshi_matching_dual_write():
    amount_sat = 1_500_000
    fee_sat = 2_000
    a_sat, a_abs = resolve_wire_amount_sat(
        {"amount_satoshi": amount_sat, "value": from_satoshi_float(amount_sat)}
    )
    assert a_sat == amount_sat
    assert a_abs == from_satoshi_float(amount_sat)
    f_sat, f_abs = resolve_wire_fee_sat(
        {"fee_satoshi": fee_sat, "fee": from_satoshi_float(fee_sat)}
    )
    assert f_sat == fee_sat
    assert f_abs == from_satoshi_float(fee_sat)


def test_resolve_fee_mismatch_raises():
    fee_sat = 2_000
    try:
        resolve_wire_fee_sat(
            {
                "fee_satoshi": fee_sat,
                "fee": from_satoshi_float(fee_sat + 1),
            }
        )
        assert False, "expected WireMoneyMismatch"
    except WireMoneyMismatch as exc:
        assert "fee_satoshi_mismatch" in str(exc)


def test_resolve_mismatch_amount_raises():
    try:
        resolve_wire_amount_sat({"amount_satoshi": 1000, "value": 2.0})
        assert False, "expected WireMoneyMismatch"
    except WireMoneyMismatch as exc:
        assert "value_satoshi_mismatch" in str(exc)


def test_resolve_float_only_raises_when_required():
    try:
        resolve_wire_amount_sat({"value": 1.0}, require_satoshi=True)
        assert False, "expected WireMoneyMissing"
    except WireMoneyMissing as exc:
        assert "amount_satoshi_required" in str(exc)
    try:
        resolve_wire_fee_sat({"fee": 0.01}, require_satoshi=True)
        assert False, "expected WireMoneyMissing"
    except WireMoneyMissing as exc:
        assert "fee_satoshi_required" in str(exc)


def test_resolve_float_only_ok_when_not_required():
    a_sat, _ = resolve_wire_amount_sat({"value": 1.25}, require_satoshi=False)
    assert a_sat == int(to_satoshi(1.25))
    f_sat, _ = resolve_wire_fee_sat({"fee": 0.002}, require_satoshi=False)
    assert f_sat == int(to_satoshi(0.002))


def test_ingest_prefers_fee_satoshi():
    node = _node()
    fee_sat = int(to_satoshi(0.05))
    amount_sat = int(to_satoshi(1.0))
    payload = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "amount_satoshi": amount_sat,
        "fee_satoshi": fee_sat,
        "nonce": 0,
        "gas": 21_000,
        "signature": "sig",
        "public_key": "pk",
        "hash": "ab" * 32,
        "data": "",
    }
    out = _build(node, payload)
    assert out is not None
    mp_tx, _ = out
    assert mp_tx.fee_satoshi == fee_sat
    assert mp_tx.amount_satoshi == amount_sat
    assert mp_tx.fee == from_satoshi_float(fee_sat)
    assert mp_tx.amount == from_satoshi_float(amount_sat)


def test_ingest_mismatch_fee_refuses():
    node = _node()
    fee_sat = int(to_satoshi(0.05))
    payload = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1.0,
        "amount_satoshi": int(to_satoshi(1.0)),
        "fee": from_satoshi_float(fee_sat + 7),
        "fee_satoshi": fee_sat,
        "nonce": 0,
        "gas": 21_000,
        "signature": "sig",
        "public_key": "pk",
        "hash": "cd" * 32,
        "data": "",
    }
    out = _build(node, payload)
    assert out is None
    assert node._last_tx_wire_reject == "fee_satoshi_mismatch"
    node.blockchain.validate_transaction.assert_not_called()


def test_ingest_mismatch_value_refuses():
    node = _node()
    amount_sat = int(to_satoshi(1.0))
    payload = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 2.0,
        "amount_satoshi": amount_sat,
        "fee": 0.01,
        "fee_satoshi": int(to_satoshi(0.01)),
        "nonce": 0,
        "gas": 21_000,
        "signature": "sig",
        "public_key": "pk",
        "hash": "ef" * 32,
        "data": "",
    }
    out = _build(node, payload)
    assert out is None
    assert node._last_tx_wire_reject == "value_satoshi_mismatch"
    node.blockchain.validate_transaction.assert_not_called()


def test_legacy_float_only_refused_by_default():
    """ADR 0021 complete: float-only wire refused (require_wire_satoshi=True)."""
    node = _node(require_wire_satoshi=True)
    payload = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1.25,
        "fee": 0.002,
        "nonce": 0,
        "gas": 21_000,
        "signature": "sig",
        "public_key": "pk",
        "hash": "11" * 32,
        "data": "",
    }
    out = _build(node, payload)
    assert out is None
    assert node._last_tx_wire_reject == "amount_satoshi_required"
    node.blockchain.validate_transaction.assert_not_called()


def test_legacy_float_only_still_ingests_when_flag_off():
    """Lab escape hatch: require_wire_satoshi=False keeps mixed-mesh float admit."""
    node = _node(require_wire_satoshi=False)
    payload = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1.25,
        "fee": 0.002,
        "nonce": 0,
        "gas": 21_000,
        "signature": "sig",
        "public_key": "pk",
        "hash": "11" * 32,
        "data": "",
    }
    out = _build(node, payload)
    assert out is not None
    mp_tx, _ = out
    assert mp_tx.amount_satoshi == int(to_satoshi(1.25))
    assert mp_tx.fee_satoshi == int(to_satoshi(0.002))


def test_wave51_wire_roundtrip_includes_satoshi():
    from blockchain.mempool import Mempool

    mp = Mempool()
    tx = MempoolTransaction(
        tx_hash="0xwire1",
        from_addr="0x" + "1" * 40,
        to_addr="0x" + "2" * 40,
        amount=3.5,
        fee=0.01,
        nonce=0,
        signature="0xsig",
        public_key="0xpub",
        data="0x",
        gas=21000,
    )
    wire = mempool_tx_to_wire(tx)
    assert "fee_satoshi" in wire and "amount_satoshi" in wire
    assert mp.add_raw(tx)
    got = mp.get_transaction("0xwire1")
    assert got is not None
    assert got.amount_satoshi == wire["amount_satoshi"]
    assert got.fee_satoshi == wire["fee_satoshi"]
