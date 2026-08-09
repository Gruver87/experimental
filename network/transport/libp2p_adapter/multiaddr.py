"""Minimal multiaddr parse/format for lab dials (ADR 0018 / 0019).

Supports a narrow subset used by in-process / dual-stack labs:
  /ip4/<host>/tcp/<port>[/p2p/<peer_id>]
  /ip6/<host>/tcp/<port>[/p2p/<peer_id>]   (Slice W)

Not a full multiaddr codec — honesty: lab convenience only.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Optional

from network.transport.types import PeerEndpoint


def _ip_proto(host: str) -> str:
    h = str(host or "").strip().strip("[]")
    try:
        return "ip6" if ipaddress.ip_address(h).version == 6 else "ip4"
    except ValueError:
        return "ip4"


@dataclass(frozen=True, slots=True)
class Multiaddr:
    host: str
    port: int
    peer_id: str = ""

    def to_string(self) -> str:
        host = str(self.host).strip().strip("[]")
        proto = _ip_proto(host)
        base = f"/{proto}/{host}/tcp/{int(self.port)}"
        if self.peer_id:
            return f"{base}/p2p/{self.peer_id}"
        return base

    def to_endpoint(self) -> PeerEndpoint:
        return PeerEndpoint(
            host=self.host, port=int(self.port), peer_id=self.peer_id or None
        )


def parse_multiaddr(value: str) -> Multiaddr:
    """Parse ``/ip4|ip6/.../tcp/...[/p2p/...]`` into :class:`Multiaddr`."""
    raw = str(value or "").strip()
    if not raw.startswith("/"):
        raise ValueError("multiaddr must start with /")
    parts = [p for p in raw.split("/") if p]
    host: Optional[str] = None
    port: Optional[int] = None
    peer_id = ""
    i = 0
    while i < len(parts):
        proto = parts[i]
        if proto in ("ip4", "ip6"):
            if i + 1 >= len(parts):
                raise ValueError(f"{proto} requires host")
            host = parts[i + 1]
            i += 2
            continue
        if proto == "tcp":
            if i + 1 >= len(parts):
                raise ValueError("tcp requires port")
            port = int(parts[i + 1])
            i += 2
            continue
        if proto == "p2p":
            if i + 1 >= len(parts):
                raise ValueError("p2p requires peer id")
            peer_id = parts[i + 1]
            i += 2
            continue
        raise ValueError(f"unsupported multiaddr protocol: {proto}")
    if not host or port is None or port <= 0:
        raise ValueError("multiaddr requires /ip4|ip6/<host>/tcp/<port>")
    return Multiaddr(host=host, port=port, peer_id=peer_id)


def endpoint_to_multiaddr(endpoint: PeerEndpoint) -> str:
    return Multiaddr(
        host=str(endpoint.host),
        port=int(endpoint.port),
        peer_id=str(endpoint.peer_id or ""),
    ).to_string()
