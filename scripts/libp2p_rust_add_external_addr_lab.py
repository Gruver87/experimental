#!/usr/bin/env python3
"""ADR 0019 Slice BO — add_external_address bool lab.

``add_external_address`` returns True when the addr was newly inserted into
the local book, bumps ``external_addr_confirmed`` only then, and returns
False on a duplicate add. Capability ``add_external_address`` / phase >= 66.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_add_external_addr_lab.py
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
        addrs = node.listen("/ip4/127.0.0.1/tcp/0")
        if not addrs:
            print("FAIL: empty listen")
            return 1
        listen = addrs[0]
        if not _wait(lambda: listen in node.external_addrs(), timeout=4.0):
            print(f"FAIL: listen not external: {node.external_addrs()}")
            return 1

        before_listen = int(node.metrics().get("libp2p_external_addr_confirmed", 0))
        dup_listen = node.add_external_address(listen)
        if dup_listen:
            print("FAIL: listen already in book should return False")
            return 1
        if int(node.metrics().get("libp2p_external_addr_confirmed", 0)) != before_listen:
            print(f"FAIL: listen dup bumped confirmed: {node.metrics()}")
            return 1

        advertised = "/ip4/203.0.113.21/tcp/4011"
        before = int(node.metrics().get("libp2p_external_addr_confirmed", 0))
        fresh = node.add_external_address(advertised)
        if not fresh:
            print("FAIL: first add returned False")
            return 1
        if advertised not in node.external_addrs():
            print(f"FAIL: not in book: {node.external_addrs()}")
            return 1
        if int(node.metrics().get("libp2p_external_addr_confirmed", 0)) != before + 1:
            print(f"FAIL: confirmed counter: {node.metrics()}")
            return 1

        before2 = int(node.metrics().get("libp2p_external_addr_confirmed", 0))
        again = node.add_external_address(advertised)
        if again:
            print("FAIL: second add should be False")
            return 1
        if int(node.metrics().get("libp2p_external_addr_confirmed", 0)) != before2:
            print(f"FAIL: second add bumped confirmed: {node.metrics()}")
            return 1

        cap = node.capability_status()
        print(
            f"OK: confirmed={node.metrics().get('libp2p_external_addr_confirmed')} "
            f"book={node.external_addrs()}"
        )
        if not cap.get("add_external_address"):
            print(f"FAIL: capability add_external_address: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 66:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_add_external_addr_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; add external bool; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
