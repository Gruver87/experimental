"""ADR 0008 Absolute wire frames over `/abs/wire/1.0.0` (ADR 0019).

Honesty: length-prefix is rust-libp2p codec; payload is Absolute NDJSON/AB2 line.
Not a gossipsub rewrite; not prod mesh cutover.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional, Sequence, Tuple

from network.transport.native_adapter import NativeTransportAdapter
from network.transport.types import AdmitDecision, OutboundEnvelope


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
    payload: Optional[Mapping[str, Any]] = None,
    adapter: Optional[NativeTransportAdapter] = None,
    rate_table: Any = None,
    max_bytes: int = 2 * 1024 * 1024,
    now: Optional[float] = None,
    codec: str = "v1",
) -> Tuple[AdmitDecision, bytes]:
    """Prepare egress via ADR 0008 path; fallback encode if prepare unavailable."""
    ad = adapter or NativeTransportAdapter(require_native=False)
    env = OutboundEnvelope(
        peer_id=str(peer_id),
        msg_type=str(msg_type),
        payload=dict(payload or {}),
    )
    decision = ad.prepare_outbound(
        env,
        now=float(now if now is not None else time.time()),
        max_bytes=int(max_bytes),
        rate_table=rate_table,
        peer_wire_codec=str(codec),
    )
    if decision.ok and decision.frame is not None:
        raw = decision.frame.data.get("payload") if decision.frame.data else None
        if isinstance(raw, (bytes, bytearray)):
            return decision, bytes(raw)
    # Lab-safe fallback: encode without rate table when native prepare soft-fails
    return decision, encode_abs_wire_frame(msg_type, payload, codec=codec)
