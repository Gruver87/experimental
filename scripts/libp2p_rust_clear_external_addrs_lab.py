#!/usr/bin/env python3
"""ADR 0019 Slice BM — clear_external_addrs lab.

``clear_external_addrs`` wipes the external address book (and swarm
removes each), returns the count cleared, and bumps
``external_addr_cleared``. Capability ``clear_external_addrs`` / phase >= 64.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_clear_external_addrs_lab.py
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
        if not _wait(
            lambda: listen in node.external_addrs()
            and int(node.metrics().get("libp2p_external_addr_confirmed", 0)) >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: listen not external: {node.external_addrs()} {node.metrics()}")
            return 1

        a1 = "/ip4/203.0.113.10/tcp/4001"
        a2 = "/ip4/203.0.113.11/tcp/4002"
        node.add_external_address(a1)
        node.add_external_address(a2)
        if not _wait(
            lambda: a1 in node.external_addrs() and a2 in node.external_addrs(),
            timeout=3.0,
        ):
            print(f"FAIL: advertised not in book: {node.external_addrs()}")
            return 1

        before_book = list(node.external_addrs())
        n_before = len(before_book)
        if n_before < 3:
            print(f"FAIL: expected >=3 external addrs: {before_book}")
            return 1
        before_clr = int(node.metrics().get("libp2p_external_addr_cleared", 0))
        cleared = node.clear_external_addrs()
        if cleared != n_before:
            print(f"FAIL: clear returned {cleared}, want {n_before}")
            return 1
        if int(node.metrics().get("libp2p_external_addr_cleared", 0)) != before_clr + n_before:
            print(f"FAIL: cleared counter: {node.metrics()}")
            return 1
        # Book empty immediately after clear (listen may re-confirm later).
        if node.external_addrs():
            # Tiny race: NewListenAddr re-confirmed — allow only listen back.
            leftover = list(node.external_addrs())
            if leftover != [listen] and listen not in leftover:
                print(f"FAIL: unexpected leftover after clear: {leftover}")
                return 1
            print(f"WARN: listen re-confirmed after clear: {leftover}")

        # Drain any listen re-confirm, then empty clear is a no-op (or clears 1).
        time.sleep(0.2)
        before2 = int(node.metrics().get("libp2p_external_addr_cleared", 0))
        again = node.clear_external_addrs()
        after2 = int(node.metrics().get("libp2p_external_addr_cleared", 0))
        if again == 0 and after2 != before2:
            print(f"FAIL: empty clear bumped counter: {node.metrics()}")
            return 1
        if again > 0 and after2 != before2 + again:
            print(f"FAIL: second clear counter: cleared={again} m={node.metrics()}")
            return 1
        empty = node.clear_external_addrs()
        if empty != 0:
            # Another late re-confirm — clear once more.
            empty2 = node.clear_external_addrs()
            if empty2 != 0:
                print(f"FAIL: expected empty clear, got {empty}/{empty2}")
                return 1

        cap = node.capability_status()
        print(
            f"OK: cleared={cleared} "
            f"counter={node.metrics().get('libp2p_external_addr_cleared')}"
        )
        if not cap.get("clear_external_addrs"):
            print(f"FAIL: capability clear_external_addrs: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 64:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_clear_external_addrs_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; clear external addrs; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
