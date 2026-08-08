"""Dual-stack dial selector: TCP+TLS default, libp2p when FEATURE_LIBP2P (ADR 0018)."""

from __future__ import annotations

from typing import Any, Literal, Mapping, Optional

from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.types import PeerEndpoint

TransportKind = Literal["native_tcp_tls", "libp2p"]


class DualStackDialer:
    """Select transport for outbound dial without changing industrial default.

    When ``feature_libp2p`` is false (prod/default), always reports native.
    When true, lab dials prefer libp2p adapter (phase-1 stub OK).
    """

    def __init__(
        self,
        *,
        feature_libp2p: bool = False,
        libp2p: Optional[Libp2pTransportAdapter] = None,
    ) -> None:
        self._feature = bool(feature_libp2p)
        self._libp2p = libp2p or Libp2pTransportAdapter(enabled=self._feature)

    @property
    def active_kind(self) -> TransportKind:
        return "libp2p" if self._feature and self._libp2p.enabled else "native_tcp_tls"

    def capability_status(self) -> Mapping[str, Any]:
        return {
            "active": self.active_kind,
            "feature_libp2p": self._feature,
            "default_mesh": "native_tcp_tls",
            "libp2p": dict(self._libp2p.capability_status()),
            "honesty": "dual_stack_selector_lab",
        }

    def dial(self, endpoint: PeerEndpoint, **kwargs: Any) -> Mapping[str, Any]:
        if self.active_kind == "libp2p":
            handle = self._libp2p.connect(endpoint, **kwargs)
            return {"kind": "libp2p", "handle": handle}
        # Native path: return intent record (real dial stays in P2PNode/NativeTransportAdapter).
        host = str(endpoint.host or "").strip()
        port = int(endpoint.port or 0)
        if not host or port <= 0:
            raise TransportCapabilityError("native dial requires host:port")
        return {
            "kind": "native_tcp_tls",
            "handle": {
                "transport": "native_tcp_tls",
                "peer": f"{host}:{port}",
                "peer_id": str(endpoint.peer_id or ""),
                "note": "selector_delegates_to_native_p2p_node",
            },
        }

    def dial_discovered(self, registry: Any, peer_id: str, **kwargs: Any) -> Mapping[str, Any]:
        """Resolve ``peer_id`` via discovery registry, then dial (wave-8)."""
        addr = registry.lookup(str(peer_id))
        if not addr:
            raise TransportCapabilityError(f"peer not announced: {peer_id}")
        from network.transport.libp2p_adapter.multiaddr import parse_multiaddr

        ma = parse_multiaddr(addr)
        endpoint = ma.to_endpoint()
        return self.dial(endpoint, multiaddr=addr, **kwargs)

    @staticmethod
    def from_config(cfg: Any) -> "DualStackDialer":
        enabled = bool(getattr(cfg, "feature_libp2p", False))
        return DualStackDialer(
            feature_libp2p=enabled,
            libp2p=Libp2pTransportAdapter(enabled=enabled),
        )
