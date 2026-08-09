#!/usr/bin/env python3
"""ADR 0019 Slice AQ — rendezvous event taxonomy metrics lab.

Register + discover → ``rendezvous_server_discover_served``.
Unregister → ``rendezvous_server_unregistrations``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_rendezvous_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 8.0, step: float = 0.05) -> bool:
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

    ns = getattr(abs_native, "ABS_RENDEZVOUS_NAMESPACE", "absolute")
    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    peer_a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    peer_b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        peer_a.listen("/ip4/127.0.0.1/tcp/0")

        # Dial-only peer_b (Windows loopback listen+redial footgun).
        if peer_a.dial(hub_addr) != hub.peer_id:
            print("FAIL: peer_a dial hub")
            return 1
        if peer_b.dial(hub_addr) != hub.peer_id:
            print("FAIL: peer_b dial hub")
            return 1
        if not _wait(
            lambda: hub.peer_id in peer_a.connected_peers()
            and hub.peer_id in peer_b.connected_peers(),
            timeout=5.0,
        ):
            print("FAIL: not connected to hub")
            return 1

        ttl = peer_a.rendezvous_register(hub.peer_id, namespace=ns)
        if int(ttl) < 1:
            print(f"FAIL: register ttl={ttl}")
            return 1
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_rendezvous_server_registrations", 0))
            >= 1,
            timeout=5.0,
        ):
            print(f"FAIL: server_registrations hub={hub.metrics()}")
            return 1

        found = peer_b.rendezvous_discover(hub.peer_id, namespace=ns)
        if peer_a.peer_id not in found:
            print(f"FAIL: discover missing peer_a: {found}")
            return 1
        if not _wait(
            lambda: int(
                hub.metrics().get("libp2p_rendezvous_server_discover_served", 0)
            )
            >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: discover_served hub={hub.metrics()}")
            return 1
        print(
            f"OK: discover_served="
            f"{hub.metrics().get('libp2p_rendezvous_server_discover_served')}"
        )

        unreg_before = int(
            hub.metrics().get("libp2p_rendezvous_server_unregistrations", 0)
        )
        peer_a.rendezvous_unregister(hub.peer_id, namespace=ns)
        if not _wait(
            lambda: int(
                hub.metrics().get("libp2p_rendezvous_server_unregistrations", 0)
            )
            > unreg_before,
            timeout=5.0,
        ):
            print(f"FAIL: unregistrations hub={hub.metrics()}")
            return 1
        print(
            f"OK: unregistrations="
            f"{hub.metrics().get('libp2p_rendezvous_server_unregistrations')}"
        )

        cap = hub.capability_status()
        if not cap.get("rendezvous_events"):
            print(f"FAIL: capability rendezvous_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 42:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (peer_b, peer_a, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_rendezvous_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; rendezvous events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
