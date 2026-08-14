#!/usr/bin/env python3
"""ADR 0019 Slice CA — advertised cap equals rust-libp2p ExternalAddresses book.

rust-libp2p 0.45 Identify / Kad / Relay keep at most 20 confirmed externals
and silently evict the oldest past that. A hard max of 32 would paint 32
charged addrs while the wire book dropped 12. Fail-closed: unique advertised
cap is 20 (``LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX``); the 21st add refuses.
Circuit ``/p2p-circuit`` is still outside the cap. Capability
``advertised_externals_libp2p_book_aligned`` / phase >= 78.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_advertised_externals_libp2p_book_max_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    hard = int(getattr(abs_native, "MAX_ADVERTISED_EXTERNAL_ADDRS", 0) or 0)
    book = int(getattr(abs_native, "LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX", 0) or 0)
    if book != 20:
        print(f"FAIL: libp2p ExternalAddresses book max {book}")
        return 1
    if hard != book:
        print(f"FAIL: advertised hard {hard} != libp2p book {book}")
        return 1

    raised = False
    try:
        abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            max_advertised_external=book + 1,
        )
    except Exception as exc:
        raised = True
        print(f"OK: over-book cap refuse: {exc}")
    if not raised:
        print("FAIL: max>book did not raise")
        return 1

    node = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=book,
    )
    try:
        cap = node.capability_status()
        if not cap.get("advertised_externals_libp2p_book_aligned"):
            print(f"FAIL: capability advertised_externals_libp2p_book_aligned: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 78:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        if int(cap.get("libp2p_swarm_external_addresses_max", 0) or 0) != book:
            print(f"FAIL: capability book max {cap.get('libp2p_swarm_external_addresses_max')}")
            return 1
        if int(cap.get("max_advertised_external_hard", 0) or 0) != book:
            print(f"FAIL: capability hard {cap.get('max_advertised_external_hard')}")
            return 1

        for i in range(book):
            addr = f"/ip4/203.0.113.{i + 1}/tcp/{4100 + i}"
            fresh = node.add_external_address(addr)
            if not fresh:
                print(f"FAIL: add {i} not fresh: {addr}")
                return 1
        used = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used != book:
            print(f"FAIL: used {used} after filling book {book}")
            return 1
        print(f"OK: filled {book} operator externals used={used}")

        overflow = f"/ip4/203.0.113.250/tcp/4999"
        raised = False
        try:
            node.add_external_address(overflow)
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "exceeds max" not in msg:
                print(f"FAIL: 21st add error text: {exc}")
                return 1
            print(f"OK: 21st add refuse: {exc}")
        if not raised:
            print("FAIL: 21st add did not raise")
            return 1
        used2 = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used2 != book:
            print(f"FAIL: used grew past book after refuse: {used2}")
            return 1
        book_addrs = list(node.external_addrs())
        if overflow in book_addrs:
            print(f"FAIL: overflow landed in book: {book_addrs}")
            return 1
        if len(book_addrs) != book:
            print(f"FAIL: book len {len(book_addrs)} != {book}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_advertised_externals_libp2p_book_max_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; advertised cap aligned to libp2p "
        "ExternalAddresses book (20); TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
