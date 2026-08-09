"""In-process request/response protocol for lab swarm (ADR 0018 wave-5).

Mirrors the shape of libp2p request-response without rust-libp2p.
Frames are topic-broadcast to connected peers; only the addressed peer replies.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from network.transport.libp2p_adapter.lab_swarm import LabPeer

RequestHandler = Callable[[str, bytes], bytes]


def _pack_str(s: str) -> bytes:
    b = s.encode("utf-8")
    if len(b) > 255:
        raise ValueError("string too long for lab RR frame")
    return bytes([len(b)]) + b


def _unpack_str(data: bytes, offset: int = 0) -> Tuple[str, int]:
    if offset >= len(data):
        raise ValueError("truncated frame")
    n = data[offset]
    start = offset + 1
    end = start + n
    if end > len(data):
        raise ValueError("truncated frame")
    return data[start:end].decode("utf-8", errors="replace"), end


@dataclass
class RequestResponseService:
    """Attach a protocol handler to a :class:`LabPeer`."""

    peer: LabPeer
    protocol: str = "/abs/lab/req/1.0.0"
    _handler: Optional[RequestHandler] = None
    _pending: Dict[str, threading.Event] = field(default_factory=dict)
    _replies: Dict[str, bytes] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self.peer.subscribe(self._topic(), self._on_message)

    def _topic(self) -> str:
        return f"rr:{self.protocol}"

    def set_handler(self, handler: RequestHandler) -> None:
        self._handler = handler

    def _on_message(self, from_peer: str, data: bytes) -> None:
        if not data:
            return
        kind = data[0:1]
        body = data[1:]
        try:
            if kind == b"Q":
                target, o = _unpack_str(body, 0)
                if target != self.peer.peer_id:
                    return
                req_id, o = _unpack_str(body, o)
                payload = body[o:]
                handler = self._handler
                reply = handler(from_peer, payload) if handler else b""
                frame = b"R" + _pack_str(from_peer) + _pack_str(req_id) + reply
                self.peer.publish(self._topic(), frame)
                return
            if kind == b"R":
                dest, o = _unpack_str(body, 0)
                if dest != self.peer.peer_id:
                    return
                req_id, o = _unpack_str(body, o)
                payload = body[o:]
                with self._lock:
                    self._replies[req_id] = payload
                    ev = self._pending.get(req_id)
                if ev is not None:
                    ev.set()
        except ValueError:
            return

    def request(
        self,
        peer_id: str,
        payload: bytes,
        *,
        timeout: float = 2.0,
    ) -> bytes:
        if peer_id not in self.peer.connected_peers():
            raise ConnectionError(f"not connected to {peer_id}")
        req_id = uuid.uuid4().hex[:16]
        frame = b"Q" + _pack_str(peer_id) + _pack_str(req_id) + payload
        ev = threading.Event()
        with self._lock:
            self._pending[req_id] = ev
        try:
            if self.peer.publish(self._topic(), frame) < 1:
                raise ConnectionError("request not delivered")
            if not ev.wait(timeout):
                raise TimeoutError(f"request to {peer_id} timed out")
            with self._lock:
                return self._replies.pop(req_id, b"")
        finally:
            with self._lock:
                self._pending.pop(req_id, None)
