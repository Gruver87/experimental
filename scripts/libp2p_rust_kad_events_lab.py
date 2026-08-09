#!/usr/bin/env python3
"""ADR 0019 Slice AN — Kademlia event metrics lab.

Dial + seed + ``kad_get_closest_peers`` → ``libp2p_kad_query_ok`` /
routing updates; capability ``kad_events``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_kad_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 6.0, step: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        addr_a = a.listen("/ip4/127.0.0.1/tcp/0")[0]
        addr_b = b.listen("/ip4/127.0.0.1/tcp/0")[0]
        remote = b.dial(addr_a)
        if remote != a.peer_id:
            print(f"FAIL: dial remote {remote}")
            return 1

        a.kad_add_address(b.peer_id, addr_b)
        b.kad_add_address(a.peer_id, addr_a)

        closest = b.kad_get_closest_peers(a.peer_id)
        if not isinstance(closest, list) or not closest:
            print(f"FAIL: closest peers {closest!r}")
            return 1

        if not _wait(
            lambda: int(b.metrics().get("libp2p_kad_query_ok", 0)) >= 1
            and int(b.metrics().get("libp2p_kad_queries", 0)) >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: query metrics {b.metrics()}")
            return 1

        bm = b.metrics()
        print(
            f"OK: closest={len(closest)} "
            f"queries={bm.get('libp2p_kad_queries')} "
            f"ok={bm.get('libp2p_kad_query_ok')} "
            f"fail={bm.get('libp2p_kad_query_fail')} "
            f"routing={bm.get('libp2p_kad_routing_updates')} "
            f"inbound={bm.get('libp2p_kad_inbound_requests')} "
            f"routable={bm.get('libp2p_kad_routable_peer')} "
            f"unroutable={bm.get('libp2p_kad_unroutable_peer')} "
            f"mode={bm.get('libp2p_kad_mode_changed')}"
        )

        cap = b.capability_status()
        if not cap.get("kad_events"):
            print(f"FAIL: capability kad_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 39:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (b, a):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_kad_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; kad events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
