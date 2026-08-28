# core/components/ports.py — Blockchain facade component ports
"""Protocols for TxPipeline / StateService / ZkGateway (facade decomposition)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class TxValidationResult:
    valid: bool
    error: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"valid": self.valid}
        if self.error:
            out["error"] = self.error
        if self.meta:
            out.update(self.meta)
        return out


@dataclass
class ApplyBlockResult:
    success: bool
    burned: int = 0  # satoshi (Wave C); display via from_satoshi_float at edges
    state_root: str = ""
    error: str = ""
    native_applied: bool = False


@runtime_checkable
class TxPipelinePort(Protocol):
    def validate_for_mempool(self, tx: Any) -> TxValidationResult:
        ...

    def validate_for_block(
        self, tx: Any, *, expected_nonce: int
    ) -> TxValidationResult:
        ...

    def verify_signatures(self, block: Any) -> TxValidationResult:
        ...

    def verify_tx_signature(self, tx: Any) -> TxValidationResult:
        ...

    # ADR 0021: semantic validation stays behind this port. Phase-1 Rust kernels
    # consume a {nonce, balance_sat} snapshot built here — not a StoragePort from Rust.


@runtime_checkable
class StateServicePort(Protocol):
    def compute_state_root(self) -> str:
        ...

    def apply_transaction(
        self,
        tx: Any,
        block_height: int,
        proposer: Optional[str] = None,
        *,
        in_atomic: bool = False,
    ) -> Dict[str, Any]:
        ...

    def apply_block_reward(self, proposer: str, *, in_atomic: bool = False) -> float:
        ...

    def apply_block_mutations(
        self, block: Any, *, preserve_peer_hash: bool = False
    ) -> ApplyBlockResult:
        """Apply txs + reward inside an already-open storage atomic (no UoW tip)."""
        ...

    def ensure_at_tip(self) -> bool:
        ...

    def replay_from_ancestor(self, ancestor_height: int, alloc: Dict[str, Any]) -> float:
        ...


@runtime_checkable
class ZkGatewayPort(Protocol):
    def enabled(self) -> bool:
        ...

    def validate_zk_tx(self, tx: Any) -> TxValidationResult:
        ...

    def verify_proof(self, proof: Dict[str, Any], *, proof_type: str) -> bool:
        ...

    def system_info(self) -> Dict[str, Any]:
        ...
