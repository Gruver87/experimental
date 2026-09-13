#!/usr/bin/env python3
"""ADR 0021 phase-0: Mempool satisfies MempoolPort structurally."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.mempool import Mempool
from blockchain.ports import MempoolPort


def test_mempool_is_mempool_port() -> None:
    pool = Mempool(max_size=10, min_fee=0.0)
    assert isinstance(pool, MempoolPort)


def test_add_batch_port_shape() -> None:
    """MempoolPort.add_batch matches live Tuple return used by P2P."""
    import inspect

    from blockchain.mempool import MempoolTransaction

    sig = inspect.signature(Mempool.add_batch)
    assert "chain_prevalidated" in sig.parameters
    assert "signature_preverified" not in sig.parameters
    pool = Mempool(max_size=10, min_fee=0.0)
    tx = MempoolTransaction(
        tx_hash="b1",
        from_addr="0x1111111111111111111111111111111111111111",
        to_addr="0x2222222222222222222222222222222222222222",
        amount=1.0,
        fee=1.0,
    )
    added, rejected, hashes = pool.add_batch([tx], chain_prevalidated=True)
    assert added + rejected == 1
    assert isinstance(hashes, list)


def test_tx_pipeline_port_surface() -> None:
    """ADR 0021: validation stays on TxPipelinePort (not duplicated on MempoolPort)."""
    from blockchain.ports import MempoolPort
    from core.components.ports import TxPipelinePort, TxValidationResult

    assert hasattr(TxPipelinePort, "validate_for_mempool")
    assert hasattr(TxPipelinePort, "validate_for_block")
    assert hasattr(TxPipelinePort, "verify_signatures")
    assert hasattr(TxPipelinePort, "verify_tx_signature")
    assert not hasattr(MempoolPort, "validate_for_mempool")
    ok = TxValidationResult(valid=True)
    assert ok.as_dict() == {"valid": True}
    bad = TxValidationResult(valid=False, error="refuse")
    assert bad.as_dict()["error"] == "refuse"
