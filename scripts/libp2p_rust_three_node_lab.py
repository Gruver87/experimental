#!/usr/bin/env python3
"""rust-libp2p 3-node mesh + metrics lab (ADR 0019 Slice B).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_three_node_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait_peers(node, n: int, timeout_s: float = 3.0) -> list[str]:
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

    nodes = [abs_native.libp2p_node_new() for _ in range(3)]
    try:
        listens = [n.listen("/ip4/127.0.0.1/tcp/0")[0] for n in nodes]
        # Sequential star: n1 dials n0, n2 dials n0 and n1
        r10 = nodes[1].dial(listens[0])
        r20 = nodes[2].dial(listens[0])
        r21 = nodes[2].dial(listens[1])
        if r10 != nodes[0].peer_id or r20 != nodes[0].peer_id:
            print(f"FAIL: dial to n0 mismatch {r10=} {r20=}")
            return 1
        if r21 != nodes[1].peer_id:
            print(f"FAIL: dial to n1 mismatch {r21=}")
            return 1

        p0 = _wait_peers(nodes[0], 2)
        p1 = _wait_peers(nodes[1], 2)
        p2 = _wait_peers(nodes[2], 2)
        if len(p0) < 2 or len(p1) < 2 or len(p2) < 2:
            print(f"FAIL: incomplete mesh peers {p0=} {p1=} {p2=}")
            return 1

        frame = abs_native.libp2p_pack_wire("hello", b"n2->n0")
        ack = nodes[2].send_wire(nodes[0].peer_id, frame)
        if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
            print(f"FAIL: wire ack {ack!r}")
            return 1

        for _ in range(50):
            inbox = nodes[0].poll_inbox()
            if inbox:
                break
            time.sleep(0.05)
        else:
            print("FAIL: n0 inbox empty")
            return 1

        metrics = [n.metrics() for n in nodes]
        dial_oks = [int(m.get("libp2p_dial_ok", 0)) for m in metrics]
        peers = [int(m.get("libp2p_peers", 0)) for m in metrics]
        if sum(dial_oks) < 3:
            print(f"FAIL: expected >=3 dial_ok across mesh, got {dial_oks}")
            return 1
        if any(p < 2 for p in peers):
            print(f"FAIL: expected each node libp2p_peers>=2, got {peers}")
            return 1

        print("OK: libp2p_rust_three_node_lab PASS")
        print(f"  peers: {[n.peer_id[:12] + '…' for n in nodes]}")
        print(f"  libp2p_peers: {peers}")
        print(f"  libp2p_dial_ok: {dial_oks}")
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
