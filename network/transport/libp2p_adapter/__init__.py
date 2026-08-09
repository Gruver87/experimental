"""libp2p transport adapter (ADR 0018) — FEATURE_LIBP2P lab path."""

from network.transport.libp2p_adapter.adapter import (
    Libp2pTransportAdapter,
    native_libp2p_available,
)
from network.transport.libp2p_adapter.lab_swarm import InProcessSwarm, LabPeer
from network.transport.libp2p_adapter.multiaddr import (
    Multiaddr,
    endpoint_to_multiaddr,
    parse_multiaddr,
)
from network.transport.libp2p_adapter.discovery import DiscoveryRegistry
from network.transport.libp2p_adapter.identify import IdentifyInfo, IdentifyService
from network.transport.libp2p_adapter.peer_policy import Libp2pPeerPolicy
from network.transport.libp2p_adapter.request_response import RequestResponseService
from network.transport.libp2p_adapter.status_metrics import (
    LIBP2P_STATUS_METRIC_KEYS,
    empty_libp2p_status_metrics,
    merge_libp2p_status_metrics,
)
from network.transport.libp2p_adapter.prometheus_export import (
    append_libp2p_prometheus_lines,
    render_libp2p_prometheus,
)
from network.transport.libp2p_adapter.wire_bridge import (
    admit_abs_inbox,
    admit_abs_wire_frame,
    detect_abs_wire_codec,
    encode_abs_wire_frame,
    prepare_abs_wire_frame,
)

__all__ = [
    "Libp2pTransportAdapter",
    "native_libp2p_available",
    "InProcessSwarm",
    "LabPeer",
    "Multiaddr",
    "parse_multiaddr",
    "endpoint_to_multiaddr",
    "RequestResponseService",
    "DiscoveryRegistry",
    "IdentifyInfo",
    "IdentifyService",
    "Libp2pPeerPolicy",
    "LIBP2P_STATUS_METRIC_KEYS",
    "empty_libp2p_status_metrics",
    "merge_libp2p_status_metrics",
    "append_libp2p_prometheus_lines",
    "render_libp2p_prometheus",
    "encode_abs_wire_frame",
    "admit_abs_wire_frame",
    "prepare_abs_wire_frame",
    "detect_abs_wire_codec",
    "admit_abs_inbox",
]
