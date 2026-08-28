"""Protocol ports for the P2P application dispatcher (no p2p_node imports)."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from network.p2p_dispatch.types import TipEvidenceDecision


@runtime_checkable
class TipEvidencePort(Protocol):
    """Tip-safety / evidence gate used by the dispatcher (DI; no cycles)."""

    def evaluate_block_candidate(
        self,
        data: Mapping[str, Any],
        chain: Any,
    ) -> TipEvidenceDecision:
        """Evaluate a NEW_BLOCK / import-shaped payload against tip policy."""
        ...

    def evaluate_status_claim(
        self,
        *,
        height: int,
        head_hash: str,
        local_height: int,
        local_head: str,
    ) -> TipEvidenceDecision:
        """Evaluate STATUS height/head claim (soft evidence; not tip proof)."""
        ...


@runtime_checkable
class DispatchHost(Protocol):
    """Minimal host surface handlers need. Implemented structurally by P2PNode."""

    config: Any
    blockchain: Any
    peers: Any

    def head(self) -> Optional[str]:
        ...

    def strike_peer(self, peer: Any, reason: str) -> bool:
        """Record a strike; return True if peer should be removed."""
        ...

    def remove_peer(self, peer_id: str, peer: Any = None) -> None:
        ...

    def bump_counter(self, name: str, delta: int = 1) -> None:
        ...

    async def handle_new_block(self, peer: Any, data: Any) -> None:
        ...

    async def handle_get_blocks(self, peer: Any, data: Any) -> None:
        ...

    async def handle_new_tx(self, peer: Any, data: Any) -> None:
        ...

    async def handle_get_mempool(self, peer: Any) -> None:
        ...

    async def handle_attestation(self, peer: Any, data: Any) -> None:
        ...

    async def handle_validator_register(self, peer: Any, data: Any) -> None:
        ...

    async def handle_cross_shard_tx(self, peer: Any, data: Any) -> None:
        ...

    async def handle_cross_shard_ack(self, peer: Any, data: Any) -> None:
        ...

    async def handle_shard_migration(self, peer: Any, data: Any) -> None:
        ...

    async def handle_ws_checkpoint(self, peer: Any, data: Any) -> None:
        ...

    def get_block_future_refuse_reason(self, height: int) -> str:
        ...

    def cap_claimed_peer_height(self, height: int) -> tuple[int, bool]:
        ...

    def status_head_height_refuse_reason(self, head_hash: str, height: int) -> str:
        ...

    def ingest_discovered_peers(self, peer: Any, data: Any) -> None:
        ...

    def state_root_response_for_height(self, height: int) -> Any:
        ...
