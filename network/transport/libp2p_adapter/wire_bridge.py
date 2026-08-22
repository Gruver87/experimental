"""ADR 0008 Absolute wire frames over `/abs/wire/1.0.0` (ADR 0019).

Honesty: length-prefix is rust-libp2p codec; payload is Absolute NDJSON/AB2 line.
Slice M: v1 NDJSON + v2 Borsh (AB2) round-trip over request-response.
Not a gossipsub rewrite; not prod mesh cutover.
"""

from __future__ import annotations

import json
import time
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from network.transport.native_adapter import NativeTransportAdapter
from network.transport.types import AdmitDecision, OutboundEnvelope


def detect_abs_wire_codec(frame: bytes) -> str:
    """Classify Absolute ADR 0008 codec (v1 / v2 / lab)."""
    try:
        import abs_native

        if hasattr(abs_native, "libp2p_classify_abs_wire"):
            return str(abs_native.libp2p_classify_abs_wire(bytes(frame)))
    except Exception:
        pass
    body = bytes(frame).rstrip(b"\r\n")
    if body.startswith(b"AB2:"):
        return "v2"
    if body.startswith(b"{"):
        return "v1"
    return "lab"


def encode_abs_wire_frame(
    msg_type: str,
    data: Any = None,
    *,
    codec: str = "v1",
) -> bytes:
    """Encode one Absolute P2P wire line (ADR 0008) for libp2p ``send_wire``."""
    from crypto import native as nat

    return bytes(
        nat.encode_p2p_wire_message_codec(str(msg_type), data, codec=str(codec))
    )


def admit_abs_wire_frame(
    frame: bytes,
    *,
    peer_id: str,
    adapter: Optional[NativeTransportAdapter] = None,
    rate_table: Any = None,
    max_bytes: int = 2 * 1024 * 1024,
    allowed_types: Optional[Sequence[str]] = None,
    now: Optional[float] = None,
) -> AdmitDecision:
    """Admit inbound Absolute wire bytes via NativeTransportAdapter ingress."""
    ad = adapter or NativeTransportAdapter(require_native=False)
    return ad.admit_inbound_line(
        bytes(frame),
        peer_id=str(peer_id),
        now=float(now if now is not None else time.time()),
        max_bytes=int(max_bytes),
        allowed_types=allowed_types,
        rate_table=rate_table,
    )


def prepare_abs_wire_frame(
    *,
    peer_id: str,
    msg_type: str,
    payload: Any = None,
    adapter: Optional[NativeTransportAdapter] = None,
    rate_table: Any = None,
    max_bytes: int = 2 * 1024 * 1024,
    now: Optional[float] = None,
    codec: str = "v1",
) -> Tuple[AdmitDecision, bytes]:
    """Prepare egress via ADR 0008 path. Refuse returns empty bytes (no encode fallback)."""
    ad = adapter or NativeTransportAdapter(require_native=False)
    data_json: Optional[str] = None
    if payload is None:
        mapping: dict = {}
        data_json = "null"
    elif isinstance(payload, Mapping):
        mapping = dict(payload)
    else:
        mapping = {}
        data_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    env = OutboundEnvelope(
        peer_id=str(peer_id),
        msg_type=str(msg_type),
        payload=mapping,
    )
    decision = ad.prepare_outbound(
        env,
        data_json=data_json,
        now=float(now if now is not None else time.time()),
        max_bytes=int(max_bytes),
        rate_table=rate_table,
        peer_wire_codec=str(codec),
    )
    if decision.ok and decision.frame is not None:
        raw = decision.frame.data.get("payload") if decision.frame.data else None
        if isinstance(raw, (bytes, bytearray)) and raw:
            return decision, bytes(raw)
        from network.transport.reject import make_reject

        reject = make_reject(
            "transport_internal", "egress prepare ok without payload bytes"
        )
        return AdmitDecision(ok=False, reject=reject), b""
    return decision, b""


def admit_abs_inbox(
    items: Sequence[Tuple[str, bytes]],
    *,
    adapter: Optional[NativeTransportAdapter] = None,
    rate_table: Any = None,
    max_bytes: int = 2 * 1024 * 1024,
    allowed_types: Optional[Sequence[str]] = None,
) -> List[Tuple[str, AdmitDecision, str]]:
    """Admit a batch of ``(peer_id, frame)`` from libp2p ``poll_inbox`` (Slice M)."""
    out: List[Tuple[str, AdmitDecision, str]] = []
    for peer_id, frame in items:
        raw = bytes(frame)
        codec = detect_abs_wire_codec(raw)
        decision = admit_abs_wire_frame(
            raw,
            peer_id=str(peer_id),
            adapter=adapter,
            rate_table=rate_table,
            max_bytes=int(max_bytes),
            allowed_types=allowed_types,
        )
        out.append((str(peer_id), decision, codec))
    return out
