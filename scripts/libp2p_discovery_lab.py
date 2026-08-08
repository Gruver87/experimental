#!/usr/bin/env python3
"""libp2p lab peer discovery stub (ADR 0018 wave-7).

Usage:
  python scripts/libp2p_discovery_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.libp2p_adapter import InProcessSwarm
from network.transport.libp2p_adapter.discovery import DiscoveryRegistry


def main() -> int:
    reg = DiscoveryRegistry()
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4401/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4402/p2p/n2")
    reg.announce("n1", a.listen.to_string())
    reg.announce("n2", b.listen.to_string())
    assert "n2" in reg.list_peers()
    h = reg.find_and_dial(a, "n2")
    assert h["connected"] and h["remote"] == "n2"
    print("OK: libp2p_discovery_lab PASS")
    print("  registry: announce + lookup + dial")
    print("  honesty: not Kademlia/mDNS; in-process stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
