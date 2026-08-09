#!/usr/bin/env python3
"""rust-libp2p Kademlia lab (ADR 0019 Slice G).

3-node mesh: dial, seed kad addresses, get_closest_peers.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_kad_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _listen_tcp(node) -> str:
    addrs = node.listen("/ip4/127.0.0.1/tcp/0")
    return addrs[0]


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    proto = str(getattr(abs_native, "ABS_KAD_PROTOCOL", "/absolute/kad/1.0.0"))
    nodes = [abs_native.libp2p_node_new() for _ in range(3)]
    try:
        listens = [_listen_tcp(n) for n in nodes]
        nodes[1].dial(listens[0])
        nodes[2].dial(listens[0])
        nodes[2].dial(listens[1])
        time.sleep(0.4)

        # Explicit kad seeds (also auto-seeded on ConnectionEstablished)
        nodes[0].kad_add_address(nodes[1].peer_id, listens[1])
        nodes[0].kad_add_address(nodes[2].peer_id, listens[2])
        nodes[1].kad_add_address(nodes[0].peer_id, listens[0])
        nodes[1].kad_add_address(nodes[2].peer_id, listens[2])

        closest = nodes[1].kad_get_closest_peers(nodes[0].peer_id)
        if not isinstance(closest, list):
            print(f"FAIL: closest not list {closest!r}")
            return 1
        # Local DHT should surface at least the queried peer or mesh peers
        ids = set(closest)
        if nodes[0].peer_id not in ids and len(ids) < 1:
            print(f"FAIL: empty closest peers {closest}")
            return 1

        m = nodes[1].metrics()
        if int(m.get("libp2p_kad_queries", 0)) < 1:
            print(f"FAIL: kad_queries {m}")
            return 1
        if int(m.get("libp2p_kad_peers", 0)) < 1:
            print(f"FAIL: kad_peers {m}")
            return 1

        print("OK: libp2p_rust_kad_lab PASS")
        print(f"  protocol: {proto}")
        print(f"  closest_count: {len(closest)}")
        print(f"  kad_peers: {m.get('libp2p_kad_peers')} queries={m.get('libp2p_kad_queries')}")
        print("  honesty: FEATURE_LIBP2P lab; not IPFS public DHT; not prod mesh")
        return 0
    finally:
        for n in nodes:
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
