#!/usr/bin/env python3
"""ADR 0019 Slice BN — remove_external_address bool lab.

``remove_external_address`` returns True when the addr was in the local book,
bumps ``external_addr_expired`` only then, and returns False on a second remove.
Capability ``remove_external_address`` / phase >= 65.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_remove_external_addr_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 5.0, step: float = 0.05) -> bool:
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

    node = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        node.listen("/ip4/127.0.0.1/tcp/0")
        advertised = "/ip4/203.0.113.20/tcp/4010"
        node.add_external_address(advertised)
        if not _wait(lambda: advertised in node.external_addrs(), timeout=3.0):
            print(f"FAIL: add: {node.external_addrs()}")
            return 1

        before = int(node.metrics().get("libp2p_external_addr_expired", 0))
        removed = node.remove_external_address(advertised)
        if not removed:
            print("FAIL: first remove returned False")
            return 1
        if advertised in node.external_addrs():
            print(f"FAIL: still in book: {node.external_addrs()}")
            return 1
        if int(node.metrics().get("libp2p_external_addr_expired", 0)) != before + 1:
            print(f"FAIL: expired counter: {node.metrics()}")
            return 1

        before2 = int(node.metrics().get("libp2p_external_addr_expired", 0))
        again = node.remove_external_address(advertised)
        if again:
            print("FAIL: second remove should be False")
            return 1
        if int(node.metrics().get("libp2p_external_addr_expired", 0)) != before2:
            print(f"FAIL: second remove bumped expired: {node.metrics()}")
            return 1

        ghost = "/ip4/198.51.100.9/tcp/9"
        if node.remove_external_address(ghost):
            print("FAIL: ghost remove should be False")
            return 1

        cap = node.capability_status()
        print(
            f"OK: expired={node.metrics().get('libp2p_external_addr_expired')} "
            f"book={node.external_addrs()}"
        )
        if not cap.get("remove_external_address"):
            print(f"FAIL: capability remove_external_address: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 65:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_remove_external_addr_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; remove external bool; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
