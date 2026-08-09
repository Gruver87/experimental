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
        enable_mdns: Optional[bool] = None,
        wire_timeout_secs: Optional[int] = None,
        bootstrap_path: Optional[str] = None,
        enable_reconnect: Optional[bool] = None,
        peerstore_path: Optional[str] = None,
        idle_connection_timeout_secs: Optional[int] = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._dial_count = 0
        self._node: Any = None
        self._native_capable = native_libp2p_available()
        self._peer_policy = peer_policy
        self._enable_mdns = enable_mdns
        self._wire_timeout_secs = (
            int(wire_timeout_secs) if wire_timeout_secs is not None else None
        )
        self._bootstrap_path = (
            str(bootstrap_path).strip() if bootstrap_path is not None else None
        )
        self._enable_reconnect = enable_reconnect
        self._peerstore_path = (
            str(peerstore_path).strip() if peerstore_path is not None else None
        )
        self._idle_connection_timeout_secs = (
            int(idle_connection_timeout_secs)
            if idle_connection_timeout_secs is not None
            else None
        )

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
            kwargs: dict[str, Any] = {"max_dials": 32}
            if key_path:
                kwargs["key_path"] = key_path
            if self._enable_mdns is not None:
                kwargs["enable_mdns"] = bool(self._enable_mdns)
            if self._wire_timeout_secs is not None:
                kwargs["wire_timeout_secs"] = int(self._wire_timeout_secs)
            boot = self._bootstrap_path
            if boot is None:
                boot = str(os.environ.get("ABS_LIBP2P_BOOTSTRAP_PATH", "") or "").strip() or None
            if boot:
                kwargs["bootstrap_path"] = str(boot)
            if self._enable_reconnect is not None:
                kwargs["enable_reconnect"] = bool(self._enable_reconnect)
            store = self._peerstore_path
            if store is None:
                store = (
                    str(os.environ.get("ABS_LIBP2P_PEERSTORE_PATH", "") or "").strip() or None
                )
            if store:
                kwargs["peerstore_path"] = str(store)
            if self._idle_connection_timeout_secs is not None:
                kwargs["idle_connection_timeout_secs"] = int(
                    self._idle_connection_timeout_secs
                )
            self._node = abs_native.libp2p_node_new(**kwargs)
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

    def listen_relay(self, relay_multiaddr: str) -> list[str]:
        """Slice H/L: circuit-relay-v2 reservation via adapter."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return list(node.listen_relay(str(relay_multiaddr)))

    def kad_add_address(self, peer_id: str, multiaddr: str) -> str:
        """Slice G/L: seed Kademlia address via adapter."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return str(node.kad_add_address(str(peer_id), str(multiaddr)))

    def kad_get_closest_peers(self, peer_id: str) -> list[str]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return [str(p) for p in node.kad_get_closest_peers(str(peer_id))]

    def autonat_add_server(
        self, peer_id: str, multiaddr: Optional[str] = None
    ) -> None:
        """Slice N: register AutoNAT dial-back server via adapter."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        if multiaddr is None:
            node.autonat_add_server(str(peer_id))
        else:
            node.autonat_add_server(str(peer_id), str(multiaddr))

    def bootstrap_add(self, peer_id: str, multiaddr: str) -> None:
        """Slice O: persist bootstrap peer multiaddr."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.bootstrap_add(str(peer_id), str(multiaddr))

    def bootstrap_remove(self, peer_id: str) -> bool:
        """Slice BH: forget bootstrap peer; True if it was present."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return bool(node.bootstrap_remove(str(peer_id)))

    def bootstrap_clear(self) -> int:
        """Slice BJ: wipe bootstrap book; returns peers cleared."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return int(node.bootstrap_clear())

    def bootstrap_list(self) -> Mapping[str, list[str]]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            return {}
        raw = dict(node.bootstrap_list())
        return {str(k): [str(a) for a in (v or [])] for k, v in raw.items()}

    def bootstrap_dial(self) -> list[tuple[str, str]]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return [(str(p), str(s)) for p, s in node.bootstrap_dial()]

    def peerstore_list(self) -> Mapping[str, list[str]]:
        """Slice T: learned peerstore book."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            return {}
        raw = dict(node.peerstore_list())
        return {str(k): [str(a) for a in (v or [])] for k, v in raw.items()}

    def peerstore_clear(self) -> None:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.peerstore_clear()

    def peerstore_dial(self) -> list[tuple[str, str]]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return [(str(p), str(s)) for p, s in node.peerstore_dial()]

    def set_reconnect_enabled(self, enabled: bool) -> None:
        """Slice P: enable/disable bootstrap reconnect policy."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.set_reconnect_enabled(bool(enabled))

    def disconnect_peer(self, peer_id: str) -> None:
        """Slice P: drop connections to peer (lab / policy control)."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.disconnect_peer(str(peer_id))

    def gossip_peer_score(self, peer_id: str) -> Optional[float]:
        """Slice Q: gossipsub peer score, or None if unknown."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        score = node.gossip_peer_score(str(peer_id))
        return float(score) if score is not None else None

    def set_gossip_app_score(self, peer_id: str, score: float) -> bool:
        """Slice Q: application-specific gossip score contribution."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return bool(node.set_gossip_app_score(str(peer_id), float(score)))

    def report_gossip_validation(
        self, message_id: str, peer_id: str, acceptance: str
    ) -> bool:
        """Slice Q: Accept/Reject/Ignore a gossip message id."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        return bool(
            node.report_gossip_validation(str(message_id), str(peer_id), str(acceptance))
        )

    def set_ping_unhealthy_policy(
        self, enabled: bool, max_fails: int = 3, max_rtt_ms: int = 0
    ) -> None:
        """Slice R: tune unhealthy ping disconnect policy."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.set_ping_unhealthy_policy(bool(enabled), int(max_fails), int(max_rtt_ms))

    def last_ping_rtt_ms(self, peer_id: str) -> Optional[int]:
        """Slice R: last successful ping RTT in milliseconds."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        v = node.last_ping_rtt_ms(str(peer_id))
        return int(v) if v is not None else None

    def set_score_autoblock(
        self, enabled: bool, graylist_threshold: float = -80.0
    ) -> None:
        """Slice S: auto-block peers at/below gossip graylist score."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.set_score_autoblock(bool(enabled), float(graylist_threshold))

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
        dial_addr = Multiaddr(host=host, port=port, peer_id="").to_string()

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

    def send_abs_wire(
        self,
        peer_id: str,
        msg_type: str,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        codec: str = "v1",
    ) -> bytes:
        """Encode ADR 0008 Absolute frame and send over `/abs/wire` (Slice M)."""
        from network.transport.libp2p_adapter.wire_bridge import prepare_abs_wire_frame

        _decision, frame = prepare_abs_wire_frame(
            peer_id=str(peer_id),
            msg_type=str(msg_type),
            payload=payload,
            codec=str(codec),
        )
        return self.send_wire(str(peer_id), frame)

    def poll_inbox(self) -> list[tuple[str, bytes]]:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            return []
        return [(str(p), bytes(b)) for p, b in node.poll_inbox()]

    def poll_admit_inbox(self) -> list[tuple[str, Any, str]]:
        """Drain inbox and admit Absolute ADR 0008 frames (Slice M)."""
        from network.transport.libp2p_adapter.wire_bridge import admit_abs_inbox

        return admit_abs_inbox(self.poll_inbox())

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

    def allow_peer(self, peer_id: str) -> None:
        """Slice AE: push PeerId into native allow-list (requires enable_allow_list)."""
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.allow_peer(str(peer_id))

    def disallow_peer(self, peer_id: str) -> None:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.disallow_peer(str(peer_id))

    def allowed_peers(self) -> list[str]:
        if self._node is None:
            return []
        try:
            return [str(p) for p in self._node.allowed_peers()]
        except Exception:
            return []

    def external_addrs(self) -> list[str]:
        """Slice AG: confirmed external multiaddrs."""
        if self._node is None:
            return []
        try:
            return [str(a) for a in self._node.external_addrs()]
        except Exception:
            return []

    def add_external_address(self, multiaddr: str) -> None:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.add_external_address(str(multiaddr))

    def remove_external_address(self, multiaddr: str) -> None:
        self.require_transport()
        node = self._ensure_node()
        if node is None:
            raise TransportCapabilityError("rust libp2p node not available")
        node.remove_external_address(str(multiaddr))

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
        out["prometheus_export"] = True
        if self._node is not None:
            out["peer_id"] = str(self._node.peer_id)
        return out

    def prometheus_text(self, node_id: str = "lab") -> str:
        """ADR 0019 Slice Z: Prometheus text for current libp2p status snapshot."""
        from network.transport.libp2p_adapter.prometheus_export import (
            render_libp2p_prometheus,
        )

        return render_libp2p_prometheus(self.status_snapshot(), node_id=node_id)

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
