"""libp2p TransportPort adapter (ADR 0018 / 0019).

When FEATURE_LIBP2P is on and abs_native was built with Cargo feature ``libp2p``,
dials use the real rust-libp2p swarm. Otherwise Phase-1 stub handles remain
(lab scaffolding). Default industrial mesh must keep FEATURE_LIBP2P=false.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from network.transport.errors import TransportCapabilityError
from network.transport.types import PeerEndpoint


def native_libp2p_available() -> bool:
    try:
        import abs_native

        return bool(getattr(abs_native, "libp2p_available", lambda: False)())
    except Exception:
        return False


class Libp2pTransportAdapter:
    """Dual-stack lab adapter behind FEATURE_LIBP2P."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = bool(enabled)
        self._dial_count = 0
        self._node: Any = None
        self._native_capable = native_libp2p_available()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def rust_backend(self) -> bool:
        return bool(self._native_capable)

    def _ensure_node(self) -> Any:
        if self._node is not None:
            return self._node
        if not self._native_capable:
            return None
        try:
            import abs_native

            self._node = abs_native.libp2p_node_new()
        except Exception as exc:
            raise TransportCapabilityError(f"libp2p node start failed: {exc}") from exc
        return self._node

    def capability_status(self) -> Mapping[str, Any]:
        if self._node is not None:
            try:
                st = dict(self._node.capability_status())
                st["feature_libp2p"] = self._enabled
                st["dial_count"] = self._dial_count
                st["rust_backend"] = True
                return st
            except Exception as exc:
                return {
                    "available": False,
                    "transport": "libp2p",
                    "phase": 3,
                    "error": str(exc),
                    "honesty": "ADR0019_rust_libp2p_lab_not_prod_mesh",
                }
        return {
            "available": self._enabled,
            "transport": "libp2p",
            "phase": 3 if (self._enabled and self._native_capable) else (1 if self._enabled else 0),
            "rust_backend": bool(self._native_capable),
            "tls": False,
            "noise": bool(self._native_capable),
            "default_mesh": False,
            "honesty": (
                "ADR0019_rust_libp2p_lab_not_prod_mesh"
                if self._native_capable
                else "lab_stub_or_disabled_behind_FEATURE_LIBP2P"
            ),
            "dial_count": self._dial_count,
            "error": "" if self._enabled else "feature_libp2p_disabled",
        }

    def require_transport(self) -> None:
        if not self._enabled:
            raise TransportCapabilityError(
                "libp2p adapter disabled (set FEATURE_LIBP2P=true for lab)"
            )
        require = str(os.environ.get("ABS_NATIVE_MODE", "") or "").strip().lower()
        if require == "require" and not self._native_capable:
            raise TransportCapabilityError(
                "FEATURE_LIBP2P + ABS_NATIVE_MODE=require needs abs_native built "
                "with --features libp2p"
            )

    def listen(self, multiaddr: str = "/ip4/127.0.0.1/tcp/0") -> list[str]:
        """Listen via rust swarm when available."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return list(node.listen(str(multiaddr)))

    @property
    def peer_id(self) -> str:
        if self._node is None:
            return ""
        return str(self._node.peer_id)

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
        dial_addr = f"/ip4/{host}/tcp/{port}"

        if self._native_capable:
            node = self._ensure_node()
            assert node is not None
            try:
                remote = node.dial(dial_addr)
            except Exception as exc:
                raise TransportCapabilityError(f"libp2p dial failed: {exc}") from exc
            return {
                "transport": "libp2p",
                "peer": f"{host}:{port}",
                "peer_id": str(remote),
                "multiaddr": ma_str,
                "phase": 3,
                "connected": True,
                "backend": "rust_libp2p",
                "local_peer_id": str(node.peer_id),
                "note": "ADR0019_rust_libp2p",
            }

        return {
            "transport": "libp2p",
            "peer": f"{host}:{port}",
            "peer_id": peer_id,
            "multiaddr": ma_str,
            "phase": 1,
            "connected": False,
            "backend": "stub",
            "note": "stub_handle_pending_rust_libp2p_swarm",
        }

    def send_wire(self, peer_id: str, data: bytes) -> bytes:
        """Send Absolute lab wire bytes over `/abs/wire/1.0.0` (rust backend)."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return bytes(node.send_wire(str(peer_id), data))

    def poll_inbox(self) -> list[tuple[str, bytes]]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            return []
        return [(str(p), bytes(b)) for p, b in node.poll_inbox()]

    def metrics(self) -> Mapping[str, Any]:
        if self._node is None:
            return {"rust_backend": bool(self._native_capable), "libp2p_peers": 0}
        try:
            st = dict(self._node.metrics())
            st["rust_backend"] = True
            st["feature_libp2p"] = self._enabled
            return st
        except Exception as exc:
            return {"available": False, "error": str(exc)}

    def close(self) -> None:
        if self._node is not None:
            try:
                self._node.close()
            except Exception:
                pass
            self._node = None

    @staticmethod
    def from_config(cfg: Any) -> "Libp2pTransportAdapter":
        enabled = bool(getattr(cfg, "feature_libp2p", False))
        return Libp2pTransportAdapter(enabled=enabled)
