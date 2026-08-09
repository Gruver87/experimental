"""Peer ban / strike hooks for rust-libp2p dials (ADR 0019 Slice C/I).

Delegates to ``PeerManager`` / rate-limit tables used by the TCP+TLS mesh.
Slice I: can also push bans into native ``Libp2pNode.block_peer`` allow/block-list.
Does not replace industrial PeerManager; only gates FEATURE_LIBP2P lab dials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from network.transport.errors import TransportCapabilityError


@dataclass
class _PeerKey:
    peer_id: str
    host: str = ""
    port: int = 0


class Libp2pPeerPolicy:
    """Fail-closed ban check + strike on wire/dial abuse for libp2p path."""

    def __init__(self, peer_manager: Any = None, native_node: Any = None) -> None:
        self._pm = peer_manager
        self._native = native_node
        self.dial_refused_ban = 0
        self.strikes = 0
        self.native_blocks = 0

    def attach_native(self, node: Any) -> None:
        """Attach a rust ``Libp2pNode`` for Slice I block-list sync."""
        self._native = node

    def check_dial(
        self,
        *,
        peer_id: str = "",
        host: str = "",
        port: int = 0,
    ) -> None:
        if self._pm is None:
            return
        pid = str(peer_id or "").strip()
        h = str(host or "").strip()
        p = int(port or 0)
        if pid and self._pm.is_banned(pid):
            self.dial_refused_ban += 1
            raise TransportCapabilityError(
                f"libp2p dial refused: peer banned ({pid})",
                code="peer_banned",
            )
        if h and p > 0 and self._pm.is_addr_banned(h, p):
            self.dial_refused_ban += 1
            raise TransportCapabilityError(
                f"libp2p dial refused: addr banned ({h}:{p})",
                code="peer_banned",
            )

    def sync_block(self, peer_id: str) -> bool:
        """Push PeerId into native block-list when a node is attached."""
        pid = str(peer_id or "").strip()
        node = self._native
        if not pid or node is None or not hasattr(node, "block_peer"):
            return False
        try:
            node.block_peer(pid)
            self.native_blocks += 1
            return True
        except Exception:
            return False

    def note_failure(
        self,
        *,
        peer_id: str,
        reason: str,
        host: str = "",
        port: int = 0,
    ) -> bool:
        """Record strike. Returns True if peer is now banned."""
        if self._pm is None:
            return False
        self.strikes += 1
        peer = _PeerKey(peer_id=str(peer_id or ""), host=str(host or ""), port=int(port or 0))
        try:
            banned = bool(self._pm.strike(peer, str(reason or "libp2p_fail")))
        except Exception:
            return False
        if banned:
            self.sync_block(str(peer_id or ""))
        return banned

    def status(self) -> dict[str, Any]:
        return {
            "attached": self._pm is not None,
            "native_attached": self._native is not None,
            "dial_refused_ban": int(self.dial_refused_ban),
            "strikes": int(self.strikes),
            "native_blocks": int(self.native_blocks),
            "honesty": "ADR0019_libp2p_peer_policy_hooks_mesh_tables",
        }
