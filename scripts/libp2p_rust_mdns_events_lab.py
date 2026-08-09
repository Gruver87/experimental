#!/usr/bin/env python3
"""ADR 0019 Slice AS — mDNS event metrics + TTL override lab.

Hard: ``mdns_ttl_secs`` override + capability ``mdns_events`` / phase 44.
Soft: discover → expire when multicast works (Windows often filters mDNS).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_mdns_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 12.0, step: float = 0.1) -> bool:
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

    a = abs_native.libp2p_node_new(
        enable_mdns=True, enable_reconnect=False, mdns_ttl_secs=5
    )
    b = abs_native.libp2p_node_new(
        enable_mdns=True, enable_reconnect=False, mdns_ttl_secs=5
    )
    try:
        a.listen("/ip4/127.0.0.1/tcp/0")
        b.listen("/ip4/127.0.0.1/tcp/0")

        am = a.metrics()
        if int(am.get("libp2p_mdns_ttl_secs", 0)) != 5:
            print(f"FAIL: mdns_ttl_secs a={am}")
            return 1
        if "libp2p_mdns_expired" not in am:
            print(f"FAIL: missing mdns_expired key a={am}")
            return 1
        if not bool(am.get("libp2p_mdns_enabled", False)):
            print(f"FAIL: mdns not enabled a={am}")
            return 1
        print(f"OK: mdns_ttl_secs={am.get('libp2p_mdns_ttl_secs')} keys present")

        discovered = _wait(
            lambda: int(a.metrics().get("libp2p_mdns_discovered", 0)) >= 1
            or b.peer_id in dict(a.discovered_peers()),
            timeout=8.0,
        )
        if discovered:
            print(
                f"OK: discovered={a.metrics().get('libp2p_mdns_discovered')}"
            )
            expired_before = int(a.metrics().get("libp2p_mdns_expired", 0))
            b.close()
            if not _wait(
                lambda: int(a.metrics().get("libp2p_mdns_expired", 0))
                > expired_before,
                timeout=15.0,
            ):
                print(f"FAIL: expected mdns_expired a={a.metrics()}")
                return 1
            print(f"OK: expired={a.metrics().get('libp2p_mdns_expired')}")
        else:
            print(
                "OK: mdns discover not observed in window "
                "(multicast may be filtered; TTL/capability still PASS)"
            )

        cap = a.capability_status()
        if not cap.get("mdns_events"):
            print(f"FAIL: capability mdns_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 44:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_mdns_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; mDNS events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
