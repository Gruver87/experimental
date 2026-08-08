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

    def __init__(
        self,
        *,
        enabled: bool = False,
        peer_policy: Optional[Any] = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._dial_count = 0
        self._node: Any = None
        self._native_capable = native_libp2p_available()
        self._peer_policy = peer_policy

    def set_peer_policy(self, policy: Any) -> None:
        self._peer_policy = policy

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

            key_path = str(os.environ.get("ABS_LIBP2P_KEY_PATH", "") or "").strip() or None
            if key_path:
                self._node = abs_native.libp2p_node_new(32, key_path)
            else:
                self._node = abs_native.libp2p_node_new()
            if self._peer_policy is not None and hasattr(self._peer_policy, "attach_native"):
                try:
                    self._peer_policy.attach_native(self._node)
                except Exception:
                    pass
        except Exception as exc:
            raise TransportCapabilityError(f"libp2p node start failed: {exc}") from exc
        return self._node

    def capability_status(self) -> Mapping[str, Any]:
        policy = (
            dict(self._peer_policy.status())
            if self._peer_policy is not None and hasattr(self._peer_policy, "status")
            else {"attached": False}
        )
        if self._node is not None:
            try:
                st = dict(self._node.capability_status())
                st["feature_libp2p"] = self._enabled
                st["dial_count"] = self._dial_count
                st["rust_backend"] = True
                st["peer_policy"] = policy
                try:
                    st.update(
                        {
                            k: v
                            for k, v in dict(self._node.metrics()).items()
                            if str(k).startswith("libp2p_")
                        }
                    )
                except Exception:
                    pass
                return st
            except Exception as exc:
                return {
                    "available": False,
                    "transport": "libp2p",
                    "phase": 3,
                    "error": str(exc),
                    "honesty": "ADR0019_rust_libp2p_lab_not_prod_mesh",
                    "peer_policy": policy,
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
            "peer_policy": (
                dict(self._peer_policy.status())
                if self._peer_policy is not None and hasattr(self._peer_policy, "status")
                else {"attached": False}
            ),
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
        if self._peer_policy is not None:
            self._peer_policy.check_dial(peer_id=peer_id, host=host, port=port)
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
                if self._peer_policy is not None:
                    self._peer_policy.note_failure(
                        peer_id=peer_id or str(exc),
                        reason="libp2p_dial_fail",
                        host=host,
                        port=port,
                    )
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

    def subscribe(self, topic: str) -> bool:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return bool(node.subscribe(str(topic)))

    def publish(self, topic: str, data: bytes) -> str:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return str(node.publish(str(topic), data))

    def poll_gossip(self) -> list[tuple[str, str, bytes]]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            return []
        return [(str(p), str(t), bytes(b)) for p, t, b in node.poll_gossip()]

    def identify_info(self, peer_id: str) -> Mapping[str, Any]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            return {"peer_id": str(peer_id), "received": False}
        return dict(node.identify_info(str(peer_id)))

    def block_peer(self, peer_id: str) -> None:
        """Slice I/J: push PeerId into native allow/block-list."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.block_peer(str(peer_id))

    def unblock_peer(self, peer_id: str) -> None:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.unblock_peer(str(peer_id))

    def blocked_peers(self) -> list[str]:
        if self._node is None:
            return []
        try:
            return [str(p) for p in self._node.blocked_peers()]
        except Exception:
            return []

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

    def status_snapshot(self) -> Mapping[str, Any]:
        """Flat lab status block (same keys as P2PNode._libp2p_status_block metrics)."""
        from network.transport.libp2p_adapter.status_metrics import (
            empty_libp2p_status_metrics,
            merge_libp2p_status_metrics,
        )

        policy_attached = False
        if self._peer_policy is not None and hasattr(self._peer_policy, "status"):
            try:
                policy_attached = bool(dict(self._peer_policy.status()).get("attached"))
            except Exception:
                policy_attached = False
        out: dict[str, Any] = {
            "feature_libp2p": self._enabled,
            "active": bool(self._enabled and self._node is not None),
            "default_mesh": False,
            "honesty": "ADR0019_rust_libp2p_lab_not_prod_mesh",
            "rust_backend": bool(self._native_capable),
            "peer_policy": policy_attached,
        }
        out.update(empty_libp2p_status_metrics())
        merge_libp2p_status_metrics(out, dict(self.capability_status() or {}))
        merge_libp2p_status_metrics(out, dict(self.metrics() or {}))
        if self._node is not None:
            out["peer_id"] = str(self._node.peer_id)
        return out

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
