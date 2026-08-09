#!/usr/bin/env python3
"""rust-libp2p gossipsub announce lab (ADR 0019 Slice E).

3-node mesh: subscribe abs/blocks, publish from n0, receive on n1/n2.
Also waits for identify Received snapshots.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_gossip_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait_peers(node, n: int, timeout_s: float = 4.0) -> list[str]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        peers = list(node.connected_peers())
        if len(peers) >= n:
            return peers
        time.sleep(0.05)
    return list(node.connected_peers())


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    topic = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", "abs/blocks/1.0.0"))
    nodes = [abs_native.libp2p_node_new() for _ in range(3)]
    try:
        listens = [n.listen("/ip4/127.0.0.1/tcp/0")[0] for n in nodes]
        nodes[1].dial(listens[0])
        nodes[2].dial(listens[0])
        nodes[2].dial(listens[1])
        for n in nodes:
            if len(_wait_peers(n, 2)) < 2:
                print("FAIL: incomplete mesh")
                return 1

        for n in nodes:
            n.subscribe(topic)

        # Allow gossipsub heartbeat / mesh join
        time.sleep(1.2)

        payload = b"h=42;slice-e"
        mid = nodes[0].publish(topic, payload)
        if not mid:
            print("FAIL: empty publish id")
            return 1

        got_b: list[bytes] = []
        got_c: list[bytes] = []
        deadline = time.time() + 5.0
        while time.time() < deadline and (not got_b or not got_c):
            for peer, t, data in nodes[1].poll_gossip():
                if t == topic or topic in str(t):
                    got_b.append(bytes(data))
            for peer, t, data in nodes[2].poll_gossip():
                if t == topic or topic in str(t):
                    got_c.append(bytes(data))
            time.sleep(0.1)

        if payload not in got_b or payload not in got_c:
            print(f"FAIL: gossip fan-out got_b={got_b!r} got_c={got_c!r}")
            return 1

        # Identify: wait for at least one Received snapshot on n0
        id_ok = False
        for _ in range(40):
            for pid in nodes[0].connected_peers():
                info = nodes[0].identify_info(pid)
                if info.get("received"):
                    id_ok = True
                    break
            if id_ok:
                break
            time.sleep(0.1)
        if not id_ok:
            print("FAIL: no identify Received snapshot")
            return 1

        m0 = nodes[0].metrics()
        m1 = nodes[1].metrics()
        if int(m0.get("libp2p_gossip_pub", 0)) < 1:
            print(f"FAIL: gossip_pub {m0}")
            return 1
        if int(m1.get("libp2p_gossip_recv", 0)) < 1:
            print(f"FAIL: gossip_recv {m1}")
            return 1

        print("OK: libp2p_rust_gossip_lab PASS")
        print(f"  topic: {topic}")
        print(f"  publish_id: {mid}")
        print(f"  fan-out: n1={len(got_b)} n2={len(got_c)}")
        print(f"  identify_peers: {m0.get('libp2p_identify_peers')}")
        print("  honesty: FEATURE_LIBP2P lab; not prod TCP+TLS mesh")
        return 0
    finally:
        for n in nodes:
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
