"""Minimal multiaddr parse/format for lab dials (ADR 0018 / 0019).

Supports a narrow subset used by in-process / dual-stack labs:
  /ip4/<host>/tcp/<port>[/p2p/<peer_id>]
  /ip6/<host>/tcp/<port>[/p2p/<peer_id>]   (Slice W)
  /dns4/<name>/tcp/<port>[/p2p/<peer_id>]  (Slice Y)
  /dns6/<name>/tcp/<port>[/p2p/<peer_id>]  (Slice Y)
  /ip4|ip6/<host>/udp/<port>/quic-v1[/p2p/<peer_id>]  (Slice AB)

Not a full multiaddr codec — honesty: lab convenience only.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Optional

from network.transport.types import PeerEndpoint


def _addr_proto(host: str, *, dns: str = "") -> str:
    """Pick multiaddr host protocol: ip4/ip6 or dns4/dns6."""
    d = str(dns or "").strip().lower()
    if d in ("dns4", "dns6"):
        return d
    h = str(host or "").strip().strip("[]")
    try:
        return "ip6" if ipaddress.ip_address(h).version == 6 else "ip4"
    except ValueError:
        # Hostname → dns4 by default (Slice Y).
        return "dns4"


@dataclass(frozen=True, slots=True)
class Multiaddr:
    host: str
    port: int
    peer_id: str = ""
    dns: str = ""  # "", "dns4", or "dns6" — empty = auto from host
    transport: str = "tcp"  # "tcp" or "quic-v1"

    def to_string(self) -> str:
        host = str(self.host).strip().strip("[]")
        proto = _addr_proto(host, dns=self.dns)
        transport = str(self.transport or "tcp").strip().lower()
        if transport in ("quic-v1", "quic"):
            base = f"/{proto}/{host}/udp/{int(self.port)}/quic-v1"
        else:
            base = f"/{proto}/{host}/tcp/{int(self.port)}"
        if self.peer_id:
            return f"{base}/p2p/{self.peer_id}"
        return base

    def to_endpoint(self) -> PeerEndpoint:
        return PeerEndpoint(
            host=self.host, port=int(self.port), peer_id=self.peer_id or None
        )


def parse_multiaddr(value: str) -> Multiaddr:
    """Parse ip/dns + tcp or udp/quic-v1 multiaddrs into :class:`Multiaddr`."""
    raw = str(value or "").strip()
    if not raw.startswith("/"):
        raise ValueError("multiaddr must start with /")
    parts = [p for p in raw.split("/") if p]
    host: Optional[str] = None
    port: Optional[int] = None
    peer_id = ""
    dns = ""
    transport = "tcp"
    i = 0
    while i < len(parts):
        proto = parts[i]
        if proto in ("ip4", "ip6"):
            if i + 1 >= len(parts):
                raise ValueError(f"{proto} requires host")
            host = parts[i + 1]
            dns = ""
            i += 2
            continue
        if proto in ("dns4", "dns6"):
            if i + 1 >= len(parts):
                raise ValueError(f"{proto} requires name")
            host = parts[i + 1]
            dns = proto
            i += 2
            continue
        if proto == "tcp":
            if i + 1 >= len(parts):
                raise ValueError("tcp requires port")
            port = int(parts[i + 1])
            transport = "tcp"
            i += 2
            continue
        if proto == "udp":
            if i + 1 >= len(parts):
                raise ValueError("udp requires port")
            port = int(parts[i + 1])
            i += 2
            # Expect /quic-v1 next for Slice AB.
            if i < len(parts) and parts[i] in ("quic-v1", "quic"):
                transport = "quic-v1"
                i += 1
            else:
                raise ValueError("udp multiaddr requires /quic-v1 (Slice AB)")
            continue
        if proto in ("quic-v1", "quic"):
            # Allow after udp already consumed; orphan quic is invalid.
            raise ValueError("quic-v1 must follow /udp/<port>")
        if proto == "p2p":
            if i + 1 >= len(parts):
                raise ValueError("p2p requires peer id")
            peer_id = parts[i + 1]
            i += 2
            continue
        raise ValueError(f"unsupported multiaddr protocol: {proto}")
    if not host or port is None or port <= 0:
        raise ValueError(
            "multiaddr requires /ip4|ip6|dns4|dns6/<host>/(tcp|udp)/<port>[/quic-v1]"
        )
    return Multiaddr(
        host=host, port=port, peer_id=peer_id, dns=dns, transport=transport
    )


def endpoint_to_multiaddr(endpoint: PeerEndpoint) -> str:
    return Multiaddr(
        host=str(endpoint.host),
        port=int(endpoint.port),
        peer_id=str(endpoint.peer_id or ""),
    ).to_string()
