#!/usr/bin/env python3
"""ADR 0021 phase-2: fee-sorted Rust store parity behind MempoolPort."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.mempool import Mempool, MempoolTransaction
from blockchain.ports import MempoolPort


def _mk_tx(h: str, fee: float, nonce: int = 0) -> MempoolTransaction:
    return MempoolTransaction(
        tx_hash=h,
        from_addr="0x1111111111111111111111111111111111111111",
        to_addr="0x2222222222222222222222222222222222222222",
        amount=1.0,
        fee=fee,
        nonce=nonce,
        signature="",
        public_key="",
        data="",
        gas=21_000,
    )


def test_mempool_port_and_fee_sort() -> None:
    pool = Mempool(max_size=100, min_fee=0.0)
    assert isinstance(pool, MempoolPort)
    assert pool.add(_mk_tx("low", 1.0), signature_preverified=True)
    assert pool.add(_mk_tx("high", 9.0), signature_preverified=True)
    assert pool.add(_mk_tx("mid", 5.0), signature_preverified=True)
    assert pool.get_size() == 3
    ordered = [t.tx_hash for t in pool.get(limit=10)]
    assert ordered == ["high", "mid", "low"]
    assert pool.transactions.get("high") is not None
    assert pool.remove("mid")
    assert not pool.has_transaction("mid")
    assert pool.get_size() == 2
    stats = pool.get_stats()
    assert stats["size"] == 2
    assert stats.get("store_backend") in {"rust", "python"}


def test_rust_store_preferred_when_native_on() -> None:
    if os.getenv("ABS_NATIVE_MODE", "").strip().lower() == "off":
        return
    # Force registry re-probe is process-global; just assert create path.
    from crypto.native import create_mempool_store, native_capabilities_status

    caps = native_capabilities_status()
    fam = (caps.get("families") or {}).get("mempool_store") or {}
    store = create_mempool_store(16, 0.0)
    if fam.get("backend") == "rust":
        assert store is not None
        pool = Mempool(max_size=16, min_fee=0.0)
        assert pool.get_stats().get("store_backend") == "rust"
    else:
        # Python fallback still satisfies MempoolPort.
        pool = Mempool(max_size=16, min_fee=0.0)
        assert isinstance(pool, MempoolPort)


def test_duplicate_and_min_fee_refuse() -> None:
    pool = Mempool(max_size=10, min_fee=1.0)
    assert pool.add(_mk_tx("a", 2.0), signature_preverified=True)
    assert not pool.add(_mk_tx("a", 3.0), signature_preverified=True)
    assert not pool.add(_mk_tx("b", 0.5), signature_preverified=True)
    assert pool.get_size() == 1
