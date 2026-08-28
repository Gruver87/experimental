"""P2PDispatcher — application message router (Handler Registry).

Transport / ``_message_loop`` admit frames; this module owns type → handler
routing. Tip-safety evidence is injected via ``TipEvidencePort`` (no cycles).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from network.p2p_dispatch.constants import (
    MSG_ATTESTATION,
    MSG_BLOCK,
    MSG_BLOCKS,
    MSG_CROSS_SHARD_ACK,
    MSG_CROSS_SHARD_TX,
    MSG_GET_BLOCK,
    MSG_GET_BLOCK_BY_HASH,
    MSG_GET_BLOCKS,
    MSG_GET_MEMPOOL,
    MSG_GET_PEERS,
    MSG_MEMPOOL,
    MSG_NEW_BLOCK,
    MSG_NEW_TX,
    MSG_PEERS,
    MSG_PING,
    MSG_PONG,
    MSG_SHARD_MIGRATION,
    MSG_STATE_ROOT_REQUEST,
    MSG_STATE_ROOT_RESPONSE,
    MSG_STATUS,
    MSG_VALIDATOR_REGISTER,
    MSG_WS_CHECKPOINT,
)
from network.p2p_dispatch import handlers as h
from network.p2p_dispatch.ports import DispatchHost, TipEvidencePort
from network.p2p_dispatch.registry import HandlerRegistry, MessageHandler
from network.p2p_dispatch.types import DispatchOutcome

logger = logging.getLogger("P2P.Dispatch")


class P2PDispatcher:
    """Async application dispatcher backed by a ``HandlerRegistry``.

    Args:
        registry: Handler map. When omitted, ``build_default_registry`` is used.
        tip_evidence: Optional tip-safety evidence port (DI).
    """

    __slots__ = ("_registry", "_tip_evidence", "_dispatch_total", "_refuse_total")

    def __init__(
        self,
        registry: Optional[HandlerRegistry] = None,
        *,
        tip_evidence: Optional[TipEvidencePort] = None,
    ) -> None:
        self._registry = registry if registry is not None else build_default_registry()
        self._tip_evidence = tip_evidence
        self._dispatch_total = 0
        self._refuse_total = 0

    @property
    def registry(self) -> HandlerRegistry:
        return self._registry

    @property
    def tip_evidence(self) -> Optional[TipEvidencePort]:
        return self._tip_evidence

    def set_tip_evidence(self, port: Optional[TipEvidencePort]) -> None:
        """Inject or clear the tip-evidence port (runtime DI)."""
        self._tip_evidence = port

    def register(self, msg_type: str, handler: MessageHandler) -> None:
        """Register a handler without modifying transport code."""
        self._registry.register(msg_type, handler)

    def status(self) -> dict[str, Any]:
        """Counters for security / metrics merge."""
        return {
            "dispatch_boundary": True,
            "dispatch_registered_types": sorted(self._registry.registered_types()),
            "dispatch_total": int(self._dispatch_total),
            "dispatch_tip_evidence_refuse_total": int(self._refuse_total),
            "dispatch_tip_evidence_bound": self._tip_evidence is not None,
        }

    def merge_into_status(self, target: dict[str, Any]) -> dict[str, Any]:
        """Merge dispatcher status into a p2p_security-like mapping."""
        target.update(self.status())
        return target

    async def dispatch(
        self,
        host: DispatchHost,
        peer: Any,
        msg_type: str,
        data: Any,
    ) -> DispatchOutcome:
        """Route one admitted application message.

        Returns:
            HANDLED when a registry handler ran,
            REFUSED when tip-evidence enforce stopped NEW_BLOCK,
            UNHANDLED when no handler is registered.
        """
        key = str(msg_type or "")
        handler = self._registry.get(key)
        if handler is None:
            return DispatchOutcome.UNHANDLED

        self._dispatch_total += 1

        # Tip-evidence pre-gate for block announces (enforce refuse before domain).
        if key == MSG_NEW_BLOCK and self._tip_evidence is not None and isinstance(data, dict):
            decision = self._tip_evidence.evaluate_block_candidate(data, host.blockchain)
            if decision.enforce_refuse:
                self._refuse_total += 1
                host.bump_counter("dispatch_tip_evidence_refuse_total")
                if host.strike_peer(peer, decision.reason_code or "tip_evidence_refuse"):
                    host.remove_peer(getattr(peer, "peer_id", "") or "", peer)
                return DispatchOutcome.REFUSED

        await handler(host, peer, data)
        return DispatchOutcome.HANDLED


def build_default_registry(
    tip_evidence: Optional[TipEvidencePort] = None,
) -> HandlerRegistry:
    """Build the production handler map.

    ``NEW_BLOCK`` / ``STATUS`` handlers close over ``tip_evidence`` so callers
    may also rely on ``P2PDispatcher.set_tip_evidence`` + rebind via
    ``rebind_tip_handlers``.
    """
    registry = HandlerRegistry()

    async def _new_block(host: DispatchHost, peer: Any, data: Any) -> None:
        await h.handle_new_block(host, peer, data, tip_evidence=tip_evidence)

    async def _status(host: DispatchHost, peer: Any, data: Any) -> None:
        await h.handle_status(host, peer, data, tip_evidence=tip_evidence)

    registry.extend(
        [
            (MSG_PING, h.handle_ping),
            (MSG_PONG, h.handle_pong),
            (MSG_NEW_BLOCK, _new_block),
            (MSG_GET_BLOCK, h.handle_get_block),
            (MSG_GET_BLOCK_BY_HASH, h.handle_get_block_by_hash),
            (MSG_GET_BLOCKS, h.handle_get_blocks),
            (MSG_NEW_TX, h.handle_new_tx),
            (MSG_GET_MEMPOOL, h.handle_get_mempool),
            (MSG_MEMPOOL, h.handle_unsolicited_mempool),
            (MSG_BLOCKS, h.handle_unsolicited_blocks),
            (MSG_BLOCK, h.handle_unsolicited_block),
            (MSG_GET_PEERS, h.handle_get_peers),
            (MSG_PEERS, h.handle_peers),
            (MSG_STATUS, _status),
            (MSG_ATTESTATION, h.handle_attestation),
            (MSG_VALIDATOR_REGISTER, h.handle_validator_register),
            (MSG_STATE_ROOT_REQUEST, h.handle_state_root_request),
            (MSG_STATE_ROOT_RESPONSE, h.handle_unsolicited_state_root),
            (MSG_CROSS_SHARD_TX, h.handle_cross_shard_tx),
            (MSG_CROSS_SHARD_ACK, h.handle_cross_shard_ack),
            (MSG_SHARD_MIGRATION, h.handle_shard_migration),
            (MSG_WS_CHECKPOINT, h.handle_ws_checkpoint),
        ]
    )
    return registry


def build_default_dispatcher(
    *,
    tip_evidence: Optional[TipEvidencePort] = None,
) -> P2PDispatcher:
    """Construct a production dispatcher with the default registry."""
    return P2PDispatcher(
        build_default_registry(tip_evidence=tip_evidence),
        tip_evidence=tip_evidence,
    )


def rebind_tip_handlers(dispatcher: P2PDispatcher) -> None:
    """Re-register NEW_BLOCK/STATUS closures after ``set_tip_evidence``."""
    tip = dispatcher.tip_evidence

    async def _new_block(host: DispatchHost, peer: Any, data: Any) -> None:
        await h.handle_new_block(host, peer, data, tip_evidence=tip)

    async def _status(host: DispatchHost, peer: Any, data: Any) -> None:
        await h.handle_status(host, peer, data, tip_evidence=tip)

    dispatcher.register(MSG_NEW_BLOCK, _new_block)
    dispatcher.register(MSG_STATUS, _status)
