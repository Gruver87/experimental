"""Peer ban / strike hooks for rust-libp2p dials (ADR 0019 Slice C).

Delegates to ``PeerManager`` / rate-limit tables used by the TCP+TLS mesh.
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

    def __init__(self, peer_manager: Any = None) -> None:
        self._pm = peer_manager
        self.dial_refused_ban = 0
        self.strikes = 0

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
            return bool(self._pm.strike(peer, str(reason or "libp2p_fail")))
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        return {
            "attached": self._pm is not None,
            "dial_refused_ban": int(self.dial_refused_ban),
            "strikes": int(self.strikes),
            "honesty": "ADR0019_libp2p_peer_policy_hooks_mesh_tables",
        }
