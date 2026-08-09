"""libp2p Identify protocol stub (ADR 0018 wave-8).

In-process only — not the full identify/1.0.0 wire format over rust-libp2p.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Mapping, Optional

from network.transport.libp2p_adapter.lab_swarm import LabPeer
from network.transport.libp2p_adapter.request_response import RequestResponseService


IDENTIFY_PROTOCOL = "/ipfs/id/1.0.0"


@dataclass(frozen=True, slots=True)
class IdentifyInfo:
    peer_id: str
    listen_addrs: List[str]
    protocols: List[str]
    agent_version: str = "absolute-lab/0.1"

    def to_dict(self) -> Mapping[str, object]:
        return {
            "peer_id": self.peer_id,
            "listen_addrs": list(self.listen_addrs),
            "protocols": list(self.protocols),
            "agent_version": self.agent_version,
        }

    def encode(self) -> bytes:
        # Lab-local encoding (not protobuf identify).
        addrs = ",".join(self.listen_addrs)
        protos = ",".join(self.protocols)
        return f"{self.peer_id}|{addrs}|{protos}|{self.agent_version}".encode("utf-8")

    @staticmethod
    def decode(raw: bytes) -> "IdentifyInfo":
        text = raw.decode("utf-8", errors="replace")
        parts = text.split("|", 3)
        if len(parts) != 4:
            raise ValueError("bad identify payload")
        peer_id, addrs, protos, agent = parts
        return IdentifyInfo(
            peer_id=peer_id,
            listen_addrs=[a for a in addrs.split(",") if a],
            protocols=[p for p in protos.split(",") if p],
            agent_version=agent,
        )


@dataclass
class IdentifyService:
    peer: LabPeer
    protocols: List[str] = field(default_factory=lambda: [IDENTIFY_PROTOCOL, "/abs/lab/req/1.0.0"])
    agent_version: str = "absolute-lab/0.1"
    _rr: Optional[RequestResponseService] = None

    def __post_init__(self) -> None:
        self._rr = RequestResponseService(self.peer, protocol=IDENTIFY_PROTOCOL)
        self._rr.set_handler(lambda _from, _data: self.local_info().encode())

    def local_info(self) -> IdentifyInfo:
        return IdentifyInfo(
            peer_id=self.peer.peer_id,
            listen_addrs=[self.peer.listen.to_string()],
            protocols=list(self.protocols),
            agent_version=self.agent_version,
        )

    def identify(self, peer_id: str, *, timeout: float = 2.0) -> IdentifyInfo:
        assert self._rr is not None
        raw = self._rr.request(peer_id, b"id", timeout=timeout)
        return IdentifyInfo.decode(raw)
