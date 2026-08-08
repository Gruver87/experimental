#!/usr/bin/env python3
"""In-process 2-node libp2p swarm lab (ADR 0018 wave-3).

Usage:
  python scripts/libp2p_swarm_lab.py
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
    a = swarm.spawn("lab-a", "/ip4/127.0.0.1/tcp/4001/p2p/lab-a")
    b = swarm.spawn("lab-b", "/ip4/127.0.0.1/tcp/4002/p2p/lab-b")

    seen: list[tuple[str, bytes]] = []
    b.subscribe("blocks", lambda peer, data: seen.append((peer, data)))

    h = a.dial(b.listen.to_string())
    assert h["connected"] is True
    assert h["remote"] == "lab-b"
    assert "lab-b" in a.connected_peers()
    assert "lab-a" in b.connected_peers()

    n = a.publish("blocks", b"height=1")
    assert n == 1
    assert seen == [("lab-a", b"height=1")]

    print("OK: libp2p_swarm_lab PASS")
    print("  dial: multiaddr + in-process bus")
    print("  gossip: topic blocks delivered to connected peer")
    print("  honesty: not rust-libp2p; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
