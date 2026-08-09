#!/usr/bin/env python3
"""libp2p multi-hop relay lab (ADR 0018 wave-6).

Line topology n1--n2--n3: publish_relay from n1 reaches n3 via n2.

Usage:
  python scripts/libp2p_relay_lab.py
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
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4301/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4302/p2p/n2")
    c = swarm.spawn("n3", "/ip4/127.0.0.1/tcp/4303/p2p/n3")
    # Line only (not full mesh)
    a.dial(b.listen.to_string())
    b.dial(c.listen.to_string())

    got: list[bytes] = []
    c.subscribe("blocks", lambda _p, data: got.append(data))

    # Direct publish from n1 cannot reach n3 (not connected)
    assert a.publish("blocks", b"direct") == 1  # only n2
    assert got == []

    n = a.publish_relay("blocks", b"relayed", ttl=2)
    assert n >= 2
    assert got == [b"relayed"]

    print("OK: libp2p_relay_lab PASS")
    print("  topology: n1-n2-n3 line")
    print("  relay: ttl=2 reaches n3")
    print("  honesty: in-process flood; not gossipsub/rust-libp2p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
