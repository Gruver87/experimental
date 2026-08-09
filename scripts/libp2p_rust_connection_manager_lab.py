#!/usr/bin/env python3
"""ADR 0019 Slice AA — connection manager / full ConnectionLimits lab.

1) max_established_outgoing=1 on dialer denies second outbound.
2) Runtime set_connection_limits(max_established=1) blocks a new inbound
   without shedding the already-connected peer.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_connection_manager_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _listen(node) -> str:
    return node.listen("/ip4/127.0.0.1/tcp/0")[0]


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    # Part 1: outbound established cap on dial-only client.
    hub_a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    hub_b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    dialer = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_established_outgoing=1,
    )
    try:
        a_addr = _listen(hub_a)
        b_addr = _listen(hub_b)
        remote = dialer.dial(a_addr)
        if remote != hub_a.peer_id:
            print(f"FAIL: first dial remote={remote}")
            return 1
        time.sleep(0.25)
        if hub_a.peer_id not in dialer.connected_peers():
            print(f"FAIL: not connected to hub_a: {dialer.connected_peers()}")
            return 1
        denied = False
        try:
            dialer.dial(b_addr)
        except Exception:
            denied = True
        time.sleep(0.4)
        dm = dialer.metrics()
        if int(dm.get("libp2p_conn_limit_denied", 0)) < 1 and not denied:
            print(f"FAIL: expected outbound limit deny: {dm}")
            return 1
        if hub_b.peer_id in dialer.connected_peers():
            print(f"FAIL: second outbound accepted: {dialer.connected_peers()}")
            return 1
        if int(dm.get("libp2p_max_established_outgoing", 0)) != 1:
            print(f"FAIL: max_established_outgoing metric: {dm}")
            return 1
        print(
            f"OK: outbound cap denied second dial "
            f"conn_limit_denied={dm.get('libp2p_conn_limit_denied')}"
        )
    finally:
        for n in (dialer, hub_a, hub_b):
            try:
                n.close()
            except Exception:
                pass

    # Part 2: runtime set_connection_limits (does not shed existing).
    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    c1 = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    c2 = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = _listen(hub)
        c1.dial(hub_addr)
        time.sleep(0.3)
        if c1.peer_id not in hub.connected_peers():
            print(f"FAIL: c1 not connected: {hub.connected_peers()}")
            return 1
        hub.set_connection_limits(max_established=1)
        hm = hub.metrics()
        if int(hm.get("libp2p_connection_limits_updates", 0)) < 1:
            print(f"FAIL: connection_limits_updates: {hm}")
            return 1
        if int(hm.get("libp2p_max_established", 0)) != 1:
            print(f"FAIL: max_established after set: {hm}")
            return 1
        # Existing peer must remain.
        if c1.peer_id not in hub.connected_peers():
            print("FAIL: set_connection_limits shed existing peer")
            return 1
        denied2 = False
        try:
            c2.dial(hub_addr)
        except Exception:
            denied2 = True
        time.sleep(0.5)
        hm2 = hub.metrics()
        if int(hm2.get("libp2p_conn_limit_denied", 0)) < 1 and not denied2:
            print(f"FAIL: expected runtime total cap deny: {hm2}")
            return 1
        if int(hm2.get("libp2p_peers", 0)) > 1:
            print(f"FAIL: hub accepted second peer after runtime cap: {hm2}")
            return 1
        print(
            f"OK: runtime set_connection_limits "
            f"updates={hm2.get('libp2p_connection_limits_updates')} "
            f"denied={hm2.get('libp2p_conn_limit_denied')}"
        )

        cap = hub.capability_status()
        if not cap.get("connection_manager"):
            print(f"FAIL: capability connection_manager: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 26:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (c2, c1, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_connection_manager_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; connection manager; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
