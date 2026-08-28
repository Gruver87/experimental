"""Default async handlers for the application dispatcher.

Handlers depend on ``DispatchHost`` only — never import ``network.p2p_node``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from crypto import native
from network.p2p_dispatch.constants import (
    MSG_BLOCK,
    MSG_PEERS,
    MSG_PONG,
    MSG_STATE_ROOT_RESPONSE,
    MSG_STATUS,
)
from network.p2p_dispatch.ports import DispatchHost, TipEvidencePort

logger = logging.getLogger("P2P.Dispatch")


def _maybe_remove(host: DispatchHost, peer: Any, reason: str) -> None:
    if host.strike_peer(peer, reason):
        host.remove_peer(getattr(peer, "peer_id", "") or "", peer)


async def handle_ping(host: DispatchHost, peer: Any, data: Any) -> None:
    await peer.send(MSG_PONG, {"ts": time.time()})


async def handle_pong(host: DispatchHost, peer: Any, data: Any) -> None:
    return None


async def handle_new_block(
    host: DispatchHost,
    peer: Any,
    data: Any,
    *,
    tip_evidence: TipEvidencePort | None = None,
) -> None:
    if tip_evidence is not None and isinstance(data, dict):
        decision = tip_evidence.evaluate_block_candidate(data, host.blockchain)
        if decision.enforce_refuse:
            host.bump_counter("dispatch_tip_evidence_refuse_total")
            _maybe_remove(host, peer, decision.reason_code or "tip_evidence_refuse")
            return
    await host.handle_new_block(peer, data)


async def handle_get_block(host: DispatchHost, peer: Any, data: Any) -> None:
    height = native.validate_p2p_get_block(data)
    if height is None:
        host.strike_peer(peer, "bad_get_block")
        return
    refuse = host.get_block_future_refuse_reason(int(height))
    if refuse:
        host.bump_counter("get_block_future_refuse_total")
        logger.info(
            "[P2P] get_block future refuse %s peer=%s height=%s local=%s",
            refuse,
            (getattr(peer, "peer_id", None) or "")[:12],
            height,
            host.blockchain.get_height() if host.blockchain else 0,
        )
        await peer.send(MSG_BLOCK, None)
        return
    block = host.blockchain.get_block(int(height))
    await peer.send(MSG_BLOCK, block)


async def handle_get_block_by_hash(host: DispatchHost, peer: Any, data: Any) -> None:
    block_hash = native.validate_p2p_get_block_by_hash(data)
    if block_hash is None:
        host.strike_peer(peer, "bad_get_block_by_hash")
        return
    block = None
    if hasattr(host.blockchain, "get_block_by_hash"):
        block = host.blockchain.get_block_by_hash(block_hash)
    await peer.send(MSG_BLOCK, block)


async def handle_get_blocks(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_get_blocks(peer, data)


async def handle_new_tx(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_new_tx(peer, data)


async def handle_get_mempool(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_get_mempool(peer)


async def handle_unsolicited_mempool(host: DispatchHost, peer: Any, data: Any) -> None:
    host.bump_counter("unsolicited_mempool_rejects_total")
    host.strike_peer(peer, "unsolicited_mempool")


async def handle_unsolicited_blocks(host: DispatchHost, peer: Any, data: Any) -> None:
    host.bump_counter("unsolicited_block_rejects_total")
    host.strike_peer(peer, "unsolicited_blocks")


async def handle_unsolicited_block(host: DispatchHost, peer: Any, data: Any) -> None:
    host.bump_counter("unsolicited_block_rejects_total")
    host.strike_peer(peer, "unsolicited_block")


async def handle_get_peers(host: DispatchHost, peer: Any, data: Any) -> None:
    allow_private = bool(getattr(host.config, "p2p_discovery_allow_private", False))
    peer_list = []
    for p in host.peers.values():
        if p.peer_id == peer.peer_id:
            continue
        port = p.listen_port or p.port
        if not port:
            continue
        addr = f"{p.host}:{port}"
        if native.p2p_peer_addr_is_dialable(addr, allow_private=allow_private):
            peer_list.append(addr)
    await peer.send(MSG_PEERS, peer_list)


async def handle_peers(host: DispatchHost, peer: Any, data: Any) -> None:
    if bool(getattr(host.config, "p2p_peers_solicit_only", True)):
        host.bump_counter("unsolicited_peers_rejects_total")
        host.strike_peer(peer, "unsolicited_peers")
        return
    host.ingest_discovered_peers(peer, data)


async def handle_status(
    host: DispatchHost,
    peer: Any,
    data: Any,
    *,
    tip_evidence: TipEvidencePort | None = None,
) -> None:
    status = native.validate_p2p_status_payload(data)
    if not status:
        return
    bind_reason = native.verify_p2p_status_height_head_binding(
        data if isinstance(data, dict) else status
    )
    if bind_reason:
        host.bump_counter("status_height_head_rejects_total")
        host.strike_peer(peer, str(bind_reason))
        return
    incoming_h: int | None
    if isinstance(status, dict) and "height" in status and status.get("height") is not None:
        try:
            incoming_h = int(status.get("height"))
        except (TypeError, ValueError):
            incoming_h = None
    else:
        incoming_h = None
    our_h = int(host.blockchain.get_height() or 0)
    if incoming_h is not None:
        capped_h, was_capped = host.cap_claimed_peer_height(incoming_h)
        if was_capped:
            host.bump_counter("status_height_cap_total")
        incoming_head = status.get("head_hash") or ""
        if tip_evidence is not None and incoming_head and not was_capped:
            tip_d = tip_evidence.evaluate_status_claim(
                height=capped_h,
                head_hash=str(incoming_head),
                local_height=our_h,
                local_head=str(host.head() or ""),
            )
            if tip_d.enforce_refuse:
                host.bump_counter("dispatch_tip_evidence_refuse_total")
                _maybe_remove(host, peer, tip_d.reason_code)
                return
        if incoming_head and not was_capped:
            bind_local = host.status_head_height_refuse_reason(
                str(incoming_head), capped_h
            )
            if bind_local:
                host.bump_counter("status_head_height_mismatch_total")
                host.strike_peer(peer, bind_local)
                return
        peer.height = max(int(peer.height or 0), capped_h)
        if was_capped and bool(
            getattr(host.config, "p2p_height_cap_clear_head", True)
        ):
            peer.head = ""
        elif incoming_head and not was_capped:
            peer.head = str(incoming_head)
    else:
        incoming_head = status.get("head_hash") or ""
        if incoming_head:
            if bool(
                getattr(host.config, "p2p_status_head_requires_height", True)
            ) and our_h > 0:
                host.bump_counter("status_head_without_height_total")
                host.strike_peer(peer, "status_head_without_height")
                return
            bind_local = host.status_head_height_refuse_reason(str(incoming_head), 0)
            if bind_local:
                host.bump_counter("status_head_height_mismatch_total")
                host.strike_peer(peer, bind_local)
                return
            peer.head = str(incoming_head)
    if incoming_h is not None and incoming_h != our_h:
        await peer.send(
            MSG_STATUS,
            {
                "height": our_h,
                "head_hash": host.head() or "",
            },
        )


async def handle_attestation(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_attestation(peer, data)


async def handle_validator_register(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_validator_register(peer, data)


async def handle_state_root_request(host: DispatchHost, peer: Any, data: Any) -> None:
    req_h = native.validate_p2p_state_root_request(data)
    if req_h is None:
        host.strike_peer(peer, "bad_state_root_request")
        return
    payload = host.state_root_response_for_height(int(req_h))
    if payload is None:
        host.bump_counter("state_root_outbound_refuse_total")
        # Ahead of our tip only: answer with local tip (honest lag). Missing
        # historical headers stay silent — never send a higher tip as that
        # height (hub treats got>expect as inflation).
        tip_payload = host.state_root_response_for_height(0)
        if not isinstance(tip_payload, dict):
            return
        try:
            tip_h = int(tip_payload.get("height") or 0)
        except (TypeError, ValueError):
            return
        if not (0 < tip_h < int(req_h)):
            return
        host.bump_counter("state_root_outbound_lag_total")
        payload = tip_payload
    await peer.send(MSG_STATE_ROOT_RESPONSE, payload)


async def handle_unsolicited_state_root(host: DispatchHost, peer: Any, data: Any) -> None:
    resp = native.validate_p2p_state_root_response(data)
    if not resp:
        host.strike_peer(peer, "bad_state_root_response")
        return
    host.bump_counter("unsolicited_state_root_rejects_total")
    host.strike_peer(peer, "unsolicited_state_root_response")


async def handle_cross_shard_tx(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_cross_shard_tx(peer, data)


async def handle_cross_shard_ack(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_cross_shard_ack(peer, data)


async def handle_shard_migration(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_shard_migration(peer, data)


async def handle_ws_checkpoint(host: DispatchHost, peer: Any, data: Any) -> None:
    await host.handle_ws_checkpoint(peer, data)
