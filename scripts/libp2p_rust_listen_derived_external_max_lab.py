#!/usr/bin/env python3
"""ADR 0019 Slice BS — listen-derived externals hard max (refuse, no truncate).

The advertised ceiling (MAX 32; ``max_advertised_external`` may only lower it)
applies to listen-derived addrs. Slice BT shares this budget with operator
persist (sum ≤ max). Over-limit ``listen()`` raises. Circuit listen is not
counted.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_listen_derived_external_max_lab.py
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
    if hard != 32:
        print(f"FAIL: hard max constant {hard}")
        return 1

    node = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=2,
    )
    try:
        a1 = node.listen("/ip4/127.0.0.1/tcp/0")
        if not a1:
            print("FAIL: first listen empty")
            return 1
        print(f"OK: first listen {a1}")
        a2 = node.listen("/ip4/127.0.0.1/tcp/0")
        if not a2:
            print("FAIL: second listen empty")
            return 1
        print(f"OK: second listen {a2}")
        raised = False
        try:
            node.listen("/ip4/127.0.0.1/tcp/0")
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "listen-derived" not in msg and "at max" not in msg and "exceeds max" not in msg:
                print(f"FAIL: third listen error text: {exc}")
                return 1
            print(f"OK: third listen refuse: {exc}")
        if not raised:
            print("FAIL: third listen did not raise")
            return 1
        book = list(node.external_addrs())
        listen_in_book = [a for a in book if a.startswith("/ip4/127.0.0.1/tcp/")]
        if len(listen_in_book) != 2:
            print(f"FAIL: advertised listen-derived count {listen_in_book} book={book}")
            return 1
        m = node.metrics()
        if int(m.get("libp2p_listen_derived_externals", 0)) != 2:
            print(f"FAIL: listen_derived metric: {m.get('libp2p_listen_derived_externals')}")
            return 1
        if int(m.get("libp2p_external_addr_limit_refused", 0)) < 1:
            print(f"FAIL: limit_refused counter: {m.get('libp2p_external_addr_limit_refused')}")
            return 1
        if int(m.get("libp2p_max_advertised_external", 0)) != 2:
            print(f"FAIL: max metric: {m.get('libp2p_max_advertised_external')}")
            return 1
        cap = node.capability_status()
        if not cap.get("listen_derived_external_max"):
            print(f"FAIL: capability listen_derived_external_max: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 70:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_listen_derived_external_max_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; listen-derived externals hard max refuse; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
