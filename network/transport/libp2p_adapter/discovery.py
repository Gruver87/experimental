"""In-process peer discovery stub (ADR 0018 wave-7).

Not Kademlia/mDNS/rendezvous — a lab registry peers announce into.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from network.transport.libp2p_adapter.multiaddr import Multiaddr, parse_multiaddr


@dataclass
class DiscoveryRegistry:
    """Shared announce/lookup table for lab swarms."""

    _peers: Dict[str, Multiaddr] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def announce(self, peer_id: str, listen: str) -> Multiaddr:
        ma = parse_multiaddr(listen)
        if not ma.peer_id:
            ma = Multiaddr(host=ma.host, port=ma.port, peer_id=peer_id)
        with self._lock:
            self._peers[peer_id] = ma
        return ma

    def lookup(self, peer_id: str) -> Optional[str]:
        with self._lock:
            ma = self._peers.get(peer_id)
        return ma.to_string() if ma else None

    def list_peers(self) -> List[str]:
        with self._lock:
            return sorted(self._peers.keys())

    def find_and_dial(self, local_peer, peer_id: str) -> dict:
        """Resolve ``peer_id`` from registry and dial via local lab peer."""
        addr = self.lookup(peer_id)
        if not addr:
            raise LookupError(f"peer not announced: {peer_id}")
        return local_peer.dial(addr)
