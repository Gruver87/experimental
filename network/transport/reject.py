"""Canonical transport reject taxonomy and counters.

Maps native / adapter reason strings onto ``TransportRejectClass`` for metrics
and logs. Unknown reasons default to ``INTERNAL`` (fail-closed classification,
not silent drop).
"""

from __future__ import annotations

from collections import Counter
from typing import Mapping

from network.transport.types import TransportReject, TransportRejectClass

# Exact reason codes → class (native ingress / egress / adapter).
_EXACT: dict[str, TransportRejectClass] = {
    # Frame / size
    "p2p_line_too_large": TransportRejectClass.FRAME,
    "bad_wire_line": TransportRejectClass.FRAME,
    # Rate / bandwidth (live P2PNode + native reason codes)
    "rate_limited": TransportRejectClass.RATE,
    "rate_limit": TransportRejectClass.RATE,
    "rate_limit_exceeded": TransportRejectClass.RATE,
    "rate_limit_class_exceeded": TransportRejectClass.RATE,
    "exempt_rate_exceeded": TransportRejectClass.RATE,
    "bandwidth_exceeded": TransportRejectClass.RATE,
    "egress_bandwidth_exceeded": TransportRejectClass.EGRESS,
    "egress_rate_limited": TransportRejectClass.EGRESS,
    "prepare_failed": TransportRejectClass.EGRESS,
    # I/O / admit internals
    "ingress_error": TransportRejectClass.INTERNAL,
    "recv_error": TransportRejectClass.INTERNAL,
    # Wire shape / allowlist
    "p2p_type_not_allowed": TransportRejectClass.WIRE_SHAPE,
    "p2p_missing_type": TransportRejectClass.WIRE_SHAPE,
    "p2p_bad_json": TransportRejectClass.WIRE_SHAPE,
    "p2p_not_object": TransportRejectClass.WIRE_SHAPE,
    # Capability
    "transport_capability": TransportRejectClass.CAPABILITY,
    "native_unavailable": TransportRejectClass.CAPABILITY,
    # Adapter validation
    "transport_validation": TransportRejectClass.ADMIT,
    "empty_line": TransportRejectClass.ADMIT,
    "empty_peer_id": TransportRejectClass.ADMIT,
}

# Prefix → class (longest match wins via sorted iteration).
_PREFIX: tuple[tuple[str, TransportRejectClass], ...] = (
    ("p2p_type_not_allowed", TransportRejectClass.WIRE_SHAPE),
    ("p2p_line_too_large", TransportRejectClass.FRAME),
    ("p2p_", TransportRejectClass.WIRE_SHAPE),
    ("egress_", TransportRejectClass.EGRESS),
    ("rate_", TransportRejectClass.RATE),
    ("bandwidth_", TransportRejectClass.RATE),
    ("transport_", TransportRejectClass.ADMIT),
)


def classify_reason(reason_code: str) -> TransportRejectClass:
    """Map a machine reason string to ``TransportRejectClass``.

    Args:
        reason_code: Stable reject code from native or adapter.

    Returns:
        Reject class. Empty / blank → ``INTERNAL``.
    """
    code = str(reason_code or "").strip()
    if not code:
        return TransportRejectClass.INTERNAL
    if code in _EXACT:
        return _EXACT[code]
    for prefix, klass in _PREFIX:
        if code.startswith(prefix):
            return klass
    return TransportRejectClass.INTERNAL


def make_reject(reason_code: str, detail: str = "") -> TransportReject:
    """Build a ``TransportReject`` with classified reason."""
    code = str(reason_code or "transport_internal").strip() or "transport_internal"
    return TransportReject(
        reason_code=code,
        reject_class=classify_reason(code),
        detail=str(detail or ""),
    )


class RejectCounters:
    """In-memory reject counters for status / Prometheus export.

    Thread-safety: single-threaded event-loop use (same as ``P2PNode``); not
    lock-protected. Callers that share across threads must serialize access.
    """

    __slots__ = ("_by_reason", "_by_class", "_admit_ok", "_egress_ok")

    def __init__(self) -> None:
        self._by_reason: Counter[str] = Counter()
        self._by_class: Counter[str] = Counter()
        self._admit_ok: int = 0
        self._egress_ok: int = 0

    def record_reject(self, reject: TransportReject) -> None:
        """Increment counters for a structured reject."""
        self._by_reason[reject.reason_code] += 1
        self._by_class[reject.reject_class.value] += 1

    def record_admit_ok(self) -> None:
        """Increment successful ingress admits."""
        self._admit_ok += 1

    def record_egress_ok(self) -> None:
        """Increment successful egress prepares."""
        self._egress_ok += 1

    @property
    def admit_ok_total(self) -> int:
        return int(self._admit_ok)

    @property
    def egress_ok_total(self) -> int:
        return int(self._egress_ok)

    @property
    def reject_total(self) -> int:
        return int(sum(self._by_reason.values()))

    def by_reason(self) -> Mapping[str, int]:
        return dict(self._by_reason)

    def by_class(self) -> Mapping[str, int]:
        return dict(self._by_class)

    def as_status(self) -> dict[str, object]:
        """Flat status dict mergeable into ``p2p_security``."""
        return {
            "transport_boundary": True,
            "transport_admit_ok_total": self._admit_ok,
            "transport_egress_ok_total": self._egress_ok,
            "transport_reject_total": self.reject_total,
            "transport_reject_by_reason": dict(self._by_reason),
            "transport_reject_by_class": dict(self._by_class),
        }
