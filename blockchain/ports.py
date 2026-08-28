"""Mempool port (ADR 0021 phase-0).

Protocol only — ``blockchain.mempool.Mempool`` remains the canonical implementation.
Do not wire a Rust adapter until libp2p 48h PASS and ADR 0021 phase 1 is approved.

Validation boundary: ``core.components.ports.TxPipelinePort`` (not duplicated here).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class MempoolPort(Protocol):
    """Minimal mempool surface for P2P, HTTP, and mining."""

    def set_blockchain(self, blockchain: Any) -> None:
        """Attach chain for optional re-validation on add."""
        ...

    def add(
        self,
        tx: Any,
        *,
        signature_preverified: bool = False,
        chain_prevalidated: bool = False,
    ) -> bool:
        """Insert tx when valid and pool has capacity."""
        ...

    def add_batch(
        self,
        txs: List[Any],
        *,
        signature_preverified: bool = False,
        chain_prevalidated: bool = False,
    ) -> int:
        """Batch insert; returns count accepted."""
        ...

    def get(self, limit: int = 100, min_fee: float = 0) -> List[Any]:
        """Pending txs for block assembly (fee filter optional)."""
        ...

    def get_sorted_transactions(self) -> List[Dict[str, Any]]:
        """Wire/export shape sorted by fee policy."""
        ...

    def remove(self, tx_hash: str) -> bool:
        """Drop tx after mined import or explicit eviction."""
        ...

    def has_transaction(self, tx_hash: str) -> bool:
        ...

    def get_transaction(self, tx_hash: str) -> Optional[Any]:
        ...

    def get_size(self) -> int:
        ...

    def get_stats(self) -> Dict[str, Any]:
        ...
