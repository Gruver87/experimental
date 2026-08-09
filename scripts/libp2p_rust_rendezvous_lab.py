#!/usr/bin/env python3
"""ADR 0019 Slice X — rendezvous register + discover lab.

Hub acts as rendezvous point; peer_a registers its listen addr; peer_b
discovers peer_a via hub (no direct dial between a and b first).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_rendezvous_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 10.0, step: float = 0.05) -> bool:
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
        hub_addrs = hub.listen("/ip4/127.0.0.1/tcp/0")
        if not hub_addrs:
            print("FAIL: hub listen empty")
            return 1
        hub_addr = hub_addrs[0]
        print(f"OK: hub listen {hub_addr}")

        a_addrs = peer_a.listen("/ip4/127.0.0.1/tcp/0")
        if not a_addrs:
            print("FAIL: peer_a listen empty")
            return 1
        print(f"OK: peer_a listen {a_addrs[0]}")

        # Dial-only peer_b (Windows loopback listen+redial footgun).
        remote = peer_a.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: peer_a dial hub got {remote}")
            return 1
        remote_b = peer_b.dial(hub_addr)
        if remote_b != hub.peer_id:
            print(f"FAIL: peer_b dial hub got {remote_b}")
            return 1
        if not _wait(
            lambda: hub.peer_id in peer_a.connected_peers()
            and hub.peer_id in peer_b.connected_peers(),
            timeout=5.0,
        ):
            print(
                f"FAIL: not connected to hub "
                f"a={peer_a.connected_peers()} b={peer_b.connected_peers()}"
            )
            return 1
        print("OK: a+b dialed hub")

        ttl = peer_a.rendezvous_register(hub.peer_id, namespace=ns)
        if int(ttl) < 1:
            print(f"FAIL: register ttl={ttl}")
            return 1
        print(f"OK: peer_a registered ttl={ttl}")

        if not _wait(
            lambda: int(hub.metrics().get("libp2p_rendezvous_server_registrations", 0))
            >= 1,
            timeout=5.0,
        ):
            print(f"FAIL: hub server_registrations: {hub.metrics()}")
            return 1

        found = peer_b.rendezvous_discover(hub.peer_id, namespace=ns)
        if peer_a.peer_id not in found:
            print(f"FAIL: discover missing peer_a: {found}")
            return 1
        addrs = found[peer_a.peer_id]
        if not addrs or not any("/ip4/" in a for a in addrs):
            print(f"FAIL: peer_a addrs empty/bad: {addrs}")
            return 1
        print(f"OK: peer_b discovered peer_a addrs={addrs}")

        am = peer_a.metrics()
        bm = peer_b.metrics()
        hm = hub.metrics()
        if int(am.get("libp2p_rendezvous_registers", 0)) < 1:
            print(f"FAIL: peer_a registers: {am}")
            return 1
        if int(bm.get("libp2p_rendezvous_discovers", 0)) < 1:
            print(f"FAIL: peer_b discovers: {bm}")
            return 1
        if int(bm.get("libp2p_rendezvous_discovered_peers", 0)) < 1:
            print(f"FAIL: peer_b discovered_peers: {bm}")
            return 1
        if int(hm.get("libp2p_rendezvous_server_registrations", 0)) < 1:
            print(f"FAIL: hub server_registrations: {hm}")
            return 1

        cap = peer_b.capability_status()
        if not cap.get("rendezvous"):
            print(f"FAIL: capability rendezvous: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 23:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(
            f"OK: rendezvous metrics "
            f"reg={am.get('libp2p_rendezvous_registers')} "
            f"disc={bm.get('libp2p_rendezvous_discovers')} "
            f"srv={hm.get('libp2p_rendezvous_server_registrations')}"
        )
    finally:
        for n in (peer_b, peer_a, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_rendezvous_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; rendezvous; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
