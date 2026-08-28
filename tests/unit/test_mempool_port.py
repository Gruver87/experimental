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
