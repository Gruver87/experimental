#!/usr/bin/env python3
"""v1.3.143: mempool cheap-refuse — rate primary new_tx, dup skip, sig-before-DB."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from network.p2p_node import MSG_NEW_TX, P2PNode, RATE_LIMIT_EXEMPT_TYPES
from runtime.config import Config


def test_needles_v13143():
    assert MSG_NEW_TX not in RATE_LIMIT_EXEMPT_TYPES
    assert "mempool" in RATE_LIMIT_EXEMPT_TYPES
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "duplicate_tx" in p2p
    assert "native_mempool_cheap_refuse" in p2p
    assert "native_mempool_new_tx_rate_primary" in p2p
    assert "native_tx_sig_before_state" in p2p
    chain = (ROOT / "core" / "blockchain.py").read_text(encoding="utf-8")
    state = (ROOT / "core" / "components" / "state_service.py").read_text(encoding="utf-8")
    tx_pipe = (ROOT / "core" / "components" / "tx_pipeline.py").read_text(encoding="utf-8")
    assert (
        "nonce/balance DB lookups" in chain
        or "nonce/balance DB lookups" in tx_pipe
    )
    assert (
        "Cheap crypto refuse before state lookups" in chain
        or "Cheap crypto refuse before state lookups" in tx_pipe
    )
    assert "tx_pipeline" in chain or "TxPipeline" in chain
    _ = state  # facade hosts apply kernels; pipeline owns validate order
    mem = (ROOT / "blockchain" / "mempool.py").read_text(encoding="utf-8")
    assert "chain_prevalidated" in mem
    rs = (ROOT / "native" / "abs_native" / "src" / "p2p_rate_limit.rs").read_text(
        encoding="utf-8"
    )
    assert '"new_tx"' not in rs.split("DEFAULT_EXEMPT")[1].split("];")[0]
    notes = (ROOT / "RELEASE_NOTES_v1.3.143.md").read_text(encoding="utf-8")
    assert "1.3.143-industrial" in notes
    assert Config().node_version.startswith("1.3.")
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_p2p_native_mempool_cheap_refuse" in metrics
    assert "abs_p2p_mempool_dup_refuse_total" in metrics
    # Installed wheel may lag source; Python exempt set is authoritative for tables.
    assert native.p2p_rate_limit_is_exempt("status") is True


def test_new_tx_not_exempt_on_python_table():
    import time

    table = native.P2PRateLimitTable(2, 5, 300, sorted(RATE_LIMIT_EXEMPT_TYPES), 100)
    now = time.time()
    assert table.rate_ok("p1", MSG_NEW_TX, now) is True
    assert table.rate_ok("p1", MSG_NEW_TX, now) is True
    assert table.rate_ok("p1", MSG_NEW_TX, now) is False


def test_dup_hash_refuses_before_validate():
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_mempool_require_wire_satoshi = False
    cfg.require_signatures = False
    chain = MagicMock()
    chain.validate_transaction = MagicMock(
        return_value={"valid": True}
    )
    mp = MagicMock()
    mp.has_transaction = MagicMock(return_value=True)
    node = P2PNode(cfg, chain, mp)
    data = {
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "value": 1,
        "nonce": 0,
        "gas": 21000,
        "hash": "ab" * 32,
        "signature": "sig",
        "public_key": "pk",
    }
    # Shape may fail without full wire fields — stub native validate if needed.
    if not native.validate_p2p_wire_tx(data):
        # Minimal valid-shaped payload for unit path: monkeypatch shape gate.
        native_mod = sys.modules.get("crypto.native") or native
        orig = native.validate_p2p_wire_tx
        try:
            native.validate_p2p_wire_tx = lambda _d: True  # type: ignore
            built = node._build_mempool_tx_from_wire(data)
        finally:
            native.validate_p2p_wire_tx = orig  # type: ignore
    else:
        built = node._build_mempool_tx_from_wire(data)
    assert built is None
    assert node._last_tx_wire_reject == "duplicate_tx"
    assert node._mempool_dup_refuse_total == 1
    chain.validate_transaction.assert_not_called()


def test_sig_before_db_order():
    """Junk signature must fail before nonce/balance DB when require_signatures."""
    from core.blockchain import Blockchain, Transaction
    from core.components import TxPipeline

    cfg = Config()
    cfg.require_signatures = True
    cfg.deployment_mode = "dev"
    cfg.require_native_crypto = False
    db = MagicMock()
    db.get_nonce = MagicMock(return_value=0)
    db.get_balance_satoshi = MagicMock(return_value=10**18)
    bc = Blockchain.__new__(Blockchain)
    bc.config = cfg
    bc.db = db
    bc.storage = db
    bc.pool_locks = None
    bc.evm = None
    bc.bus = None
    bc.tx_pipeline = TxPipeline(
        config=cfg,
        storage=db,
        get_pool_locks=lambda: None,
        get_evm=lambda: None,
    )
    tx = Transaction(
        from_addr="0x" + "11" * 20,
        to_addr="0x" + "22" * 20,
        value=1.0,
        nonce=0,
        gas=21000,
        signature="deadbeef",
        public_key="00" * 33,
    )
    out = bc.validate_transaction(tx)
    assert out.get("valid") is False
    db.get_nonce.assert_not_called()
    db.get_balance_satoshi.assert_not_called()
