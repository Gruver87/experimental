"""Shared ADR 0019 libp2p metric keys for /status / security snapshots (Slice J).

Honesty: these are lab/R&D counters — not a prod mesh cutover signal.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, MutableMapping

# Keys merged from adapter/node metrics into P2PNode._libp2p_status_block.
LIBP2P_STATUS_METRIC_KEYS: tuple[str, ...] = (
    "libp2p_peers",
    "libp2p_dial_ok",
    "libp2p_dial_fail",
    "libp2p_wire_sent",
    "libp2p_wire_recv",
    "libp2p_dial_refused_budget",
    "libp2p_gossip_pub",
    "libp2p_gossip_recv",
    "libp2p_mdns_discovered",
    "libp2p_kad_peers",
    "libp2p_kad_queries",
    "libp2p_relay_reservations",
    "libp2p_relay_circuits",
    "libp2p_conn_limit_denied",
    "libp2p_block_denied",
    "libp2p_blocked_peers",
    "libp2p_identify_peers",
)


def empty_libp2p_status_metrics() -> Dict[str, int]:
    return {k: 0 for k in LIBP2P_STATUS_METRIC_KEYS}


def merge_libp2p_status_metrics(
    block: MutableMapping[str, Any],
    source: Mapping[str, Any] | None,
    *,
    keys: Iterable[str] = LIBP2P_STATUS_METRIC_KEYS,
) -> None:
    """Copy int metric keys from ``source`` into ``block`` when present."""
    if not source:
        return
    for key in keys:
        if key in source:
            try:
                block[key] = int(source.get(key) or 0)
            except (TypeError, ValueError):
                block[key] = 0
