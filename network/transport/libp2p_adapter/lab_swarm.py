"""In-process 2-node libp2p lab swarm (ADR 0018 wave-3).

Simulates peer dial + gossip pub/sub over an in-memory bus. Does **not**
replace TCP+TLS prod mesh or rust-libp2p. Lab-only when FEATURE_LIBP2P.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from network.transport.libp2p_adapter.multiaddr import Multiaddr, parse_multiaddr


MessageHandler = Callable[[str, bytes], None]


@dataclass
class LabPeer:
    peer_id: str
    listen: Multiaddr
    _bus: "InProcessSwarm"
    _handlers: Dict[str, List[MessageHandler]] = field(default_factory=dict)
    _peers: Dict[str, str] = field(default_factory=dict)  # peer_id -> multiaddr

    def subscribe(self, topic: str, handler: MessageHandler) -> None:
        self._handlers.setdefault(topic, []).append(handler)

    def publish(self, topic: str, data: bytes) -> int:
        return self._bus.publish(self.peer_id, topic, data)

    def publish_relay(self, topic: str, data: bytes, *, ttl: int = 2) -> int:
        """Publish with multi-hop relay (wave-6 gossip-like flood)."""
        return self._bus.publish_relay(
            self.peer_id, topic, data, ttl=int(ttl), exclude=set()
        )

    def dial(self, addr: str) -> dict:
        ma = parse_multiaddr(addr)
        remote = self._bus.resolve(ma.peer_id or "")
        if remote is None and ma.peer_id:
            raise ConnectionError(f"unknown peer_id {ma.peer_id}")
        if remote is None:
            remote = self._bus.resolve_by_listen(ma.to_string())
        if remote is None:
            raise ConnectionError(f"no lab peer at {addr}")
        self._peers[remote.peer_id] = remote.listen.to_string()
        remote._peers[self.peer_id] = self.listen.to_string()
        return {
            "transport": "libp2p",
            "phase": 2,
            "connected": True,
            "local": self.peer_id,
            "remote": remote.peer_id,
            "multiaddr": remote.listen.to_string(),
            "note": "in_process_lab_swarm",
        }

    def connected_peers(self) -> List[str]:
        return sorted(self._peers.keys())

    def _deliver(self, topic: str, data: bytes, from_peer: str) -> None:
        for h in self._handlers.get(topic, []):
            h(from_peer, data)

    def _deliver_relay(
        self,
        topic: str,
        data: bytes,
        from_peer: str,
        *,
        ttl: int,
        seen: set[str],
    ) -> int:
        """Deliver locally then flood to neighbors except ``seen`` (hop count)."""
        self._deliver(topic, data, from_peer)
        if ttl <= 0:
            return 1
        delivered = 1
        next_seen = set(seen)
        next_seen.add(self.peer_id)
        for remote_id in self.connected_peers():
            if remote_id in next_seen:
                continue
            remote = self._bus.resolve(remote_id)
            if remote is None:
                continue
            delivered += remote._deliver_relay(
                topic, data, self.peer_id, ttl=ttl - 1, seen=next_seen
            )
        return delivered


class InProcessSwarm:
    """Shared memory bus for N lab peers in one process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._peers: Dict[str, LabPeer] = {}

    def spawn(self, peer_id: str, listen: str) -> LabPeer:
        ma = parse_multiaddr(listen)
        if not ma.peer_id:
            ma = Multiaddr(host=ma.host, port=ma.port, peer_id=peer_id)
        with self._lock:
            if peer_id in self._peers:
                raise ValueError(f"peer already spawned: {peer_id}")
            peer = LabPeer(peer_id=peer_id, listen=ma, _bus=self)
            self._peers[peer_id] = peer
            return peer

    def resolve(self, peer_id: str) -> Optional[LabPeer]:
        with self._lock:
            return self._peers.get(peer_id)

    def resolve_by_listen(self, listen: str) -> Optional[LabPeer]:
        target = parse_multiaddr(listen).to_string().rsplit("/p2p/", 1)[0]
        with self._lock:
            for p in self._peers.values():
                base = p.listen.to_string().rsplit("/p2p/", 1)[0]
                if base == target:
                    return p
        return None

    def publish(self, from_peer: str, topic: str, data: bytes) -> int:
        delivered = 0
        with self._lock:
            peers = list(self._peers.values())
        sender = None
        for p in peers:
            if p.peer_id == from_peer:
                sender = p
                break
        if sender is None:
            return 0
        remotes = set(sender.connected_peers())
        for p in peers:
            if p.peer_id == from_peer:
                continue
            if p.peer_id not in remotes:
                continue
            p._deliver(topic, data, from_peer)
            delivered += 1
        return delivered

    def publish_relay(
        self,
        from_peer: str,
        topic: str,
        data: bytes,
        *,
        ttl: int = 2,
        exclude: Optional[set[str]] = None,
    ) -> int:
        """1-hop publish that relays up to ``ttl`` hops (line/mesh lab)."""
        sender = self.resolve(from_peer)
        if sender is None:
            return 0
        seen = set(exclude or ())
        seen.add(from_peer)
        delivered = 0
        for remote_id in sender.connected_peers():
            if remote_id in seen:
                continue
            remote = self.resolve(remote_id)
            if remote is None:
                continue
            delivered += remote._deliver_relay(
                topic, data, from_peer, ttl=max(0, int(ttl) - 1), seen=set(seen)
            )
        return delivered
