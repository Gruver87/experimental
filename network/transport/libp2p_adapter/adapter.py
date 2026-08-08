"""Phase-1 libp2p TransportPort adapter (capability + gated dial).

Full rust-libp2p swarm wiring can replace the body without changing the port
surface. Default industrial mesh must keep FEATURE_LIBP2P=false and continue
using NativeTransportAdapter (TCP+TLS).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from network.transport.errors import TransportCapabilityError
from network.transport.types import PeerEndpoint


class Libp2pTransportAdapter:
    """Dual-stack lab adapter behind FEATURE_LIBP2P."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = bool(enabled)
        self._dial_count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def capability_status(self) -> Mapping[str, Any]:
        return {
            "available": self._enabled,
            "transport": "libp2p",
            "phase": 1,
            "tls": False,
            "default_mesh": False,
            "honesty": "lab_only_behind_FEATURE_LIBP2P",
            "dial_count": self._dial_count,
            "error": "" if self._enabled else "feature_libp2p_disabled",
        }

    def require_transport(self) -> None:
        if not self._enabled:
            raise TransportCapabilityError(
                "libp2p adapter disabled (set FEATURE_LIBP2P=true for lab)"
            )

    def connect(self, endpoint: PeerEndpoint, **kwargs: Any) -> Any:
        self.require_transport()
        multiaddr = str(kwargs.get("multiaddr") or "").strip()
        if multiaddr:
            from network.transport.libp2p_adapter.multiaddr import parse_multiaddr

            ma = parse_multiaddr(multiaddr)
            host, port = ma.host, ma.port
            peer_id = ma.peer_id or str(endpoint.peer_id or "")
        else:
            host = str(endpoint.host or "").strip()
            port = int(endpoint.port or 0)
            peer_id = str(endpoint.peer_id or "")
        if not host or port <= 0:
            raise TransportCapabilityError("libp2p dial requires host:port or multiaddr")
        self._dial_count += 1
        from network.transport.libp2p_adapter.multiaddr import Multiaddr

        ma_str = Multiaddr(host=host, port=port, peer_id=peer_id).to_string()
        # Phase-1/2: opaque handle; in-process swarm is separate (lab_swarm).
        return {
            "transport": "libp2p",
            "peer": f"{host}:{port}",
            "peer_id": peer_id,
            "multiaddr": ma_str,
            "phase": 1,
            "connected": False,
            "note": "stub_handle_pending_rust_libp2p_swarm",
        }

    @staticmethod
    def from_config(cfg: Any) -> "Libp2pTransportAdapter":
        enabled = bool(getattr(cfg, "feature_libp2p", False))
        return Libp2pTransportAdapter(enabled=enabled)
