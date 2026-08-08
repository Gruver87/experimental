#!/usr/bin/env python3
"""libp2p Identify + DualStackDialer discovery lab (ADR 0018 wave-8).

Usage:
  python scripts/libp2p_identify_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.dual_stack import DualStackDialer
from network.transport.libp2p_adapter import DiscoveryRegistry, InProcessSwarm
from network.transport.libp2p_adapter.identify import IdentifyService


def main() -> int:
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4501/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4502/p2p/n2")
    a.dial(b.listen.to_string())

    id_a = IdentifyService(a)
    id_b = IdentifyService(b)
    info = id_a.identify("n2")
    assert info.peer_id == "n2"
    assert any("4502" in x for x in info.listen_addrs)

    reg = DiscoveryRegistry()
    reg.announce("n2", b.listen.to_string())
    dialer = DualStackDialer(feature_libp2p=True)
    h = dialer.dial_discovered(reg, "n2")
    assert h["kind"] == "libp2p"
    assert h["handle"]["peer_id"] == "n2"

    print("OK: libp2p_identify_lab PASS")
    print("  identify: /ipfs/id/1.0.0 lab encoding")
    print("  dual-stack: dial_discovered via registry")
    print("  honesty: in-process; not rust-libp2p identify protobuf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
