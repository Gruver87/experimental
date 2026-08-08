#!/usr/bin/env python3
"""2-node dual-stack lab smoke (ADR 0018).

Simulates two lab peers selecting transport via DualStackDialer.
Does not replace docker_prod_3node TCP+TLS mesh.

Usage:
  python scripts/libp2p_two_node_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.dual_stack import DualStackDialer
from network.transport.types import PeerEndpoint


def main() -> int:
    # Default industrial path
    n1 = DualStackDialer(feature_libp2p=False)
    n2 = DualStackDialer(feature_libp2p=False)
    assert n1.active_kind == "native_tcp_tls"
    assert n2.active_kind == "native_tcp_tls"
    h1 = n1.dial(PeerEndpoint(host="127.0.0.1", port=5002, peer_id="node2"))
    h2 = n2.dial(PeerEndpoint(host="127.0.0.1", port=5001, peer_id="node1"))
    assert h1["kind"] == "native_tcp_tls"
    assert h2["kind"] == "native_tcp_tls"

    # Lab libp2p path (both peers opt-in)
    l1 = DualStackDialer(feature_libp2p=True)
    l2 = DualStackDialer(feature_libp2p=True)
    assert l1.active_kind == "libp2p"
    d1 = l1.dial(PeerEndpoint(host="127.0.0.1", port=4002, peer_id="lab-2"))
    d2 = l2.dial(PeerEndpoint(host="127.0.0.1", port=4001, peer_id="lab-1"))
    assert d1["kind"] == "libp2p" and d2["kind"] == "libp2p"
    assert d1["handle"]["phase"] == 1

    print("OK: libp2p_two_node_lab PASS")
    print("  default pair: native_tcp_tls")
    print("  feature pair: libp2p phase-1 stub handles")
    print("  honesty: not prod mesh libp2p; docker_prod_3node unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
