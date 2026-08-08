#!/usr/bin/env python3
"""3-node in-process libp2p swarm lab (ADR 0018 wave-4).

Full mesh dial + gossip topic fan-out. Not rust-libp2p; not prod TCP+TLS mesh.

Usage:
  python scripts/libp2p_three_node_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.libp2p_adapter import InProcessSwarm


def main() -> int:
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4101/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4102/p2p/n2")
    c = swarm.spawn("n3", "/ip4/127.0.0.1/tcp/4103/p2p/n3")

    # Full mesh
    assert a.dial(b.listen.to_string())["connected"]
    assert a.dial(c.listen.to_string())["connected"]
    assert b.dial(c.listen.to_string())["connected"]
    assert set(a.connected_peers()) == {"n2", "n3"}
    assert set(b.connected_peers()) == {"n1", "n3"}
    assert set(c.connected_peers()) == {"n1", "n2"}

    inbox_b: list[bytes] = []
    inbox_c: list[bytes] = []
    b.subscribe("blocks", lambda _p, data: inbox_b.append(data))
    c.subscribe("blocks", lambda _p, data: inbox_c.append(data))

    n = a.publish("blocks", b"h=42")
    assert n == 2
    assert inbox_b == [b"h=42"] and inbox_c == [b"h=42"]

    print("OK: libp2p_three_node_lab PASS")
    print("  mesh: n1-n2-n3 in-process")
    print("  gossip: topic blocks -> 2 peers")
    print("  honesty: not rust-libp2p; docker_prod_3node unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
