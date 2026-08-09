#!/usr/bin/env python3
"""ADR 0019 Slice AG — external address book lab.

Listen auto-confirms listen addr as external; add/remove API updates book + counters.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_external_addr_lab.py
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
        print(f"OK: listen {listen}")

        if not _wait(
            lambda: int(node.metrics().get("libp2p_external_addr_confirmed", 0)) >= 1
            and listen in node.external_addrs(),
            timeout=4.0,
        ):
            print(
                f"FAIL: listen not confirmed external "
                f"ext={node.external_addrs()} m={node.metrics()}"
            )
            return 1
        print(
            f"OK: listen confirmed "
            f"confirmed={node.metrics().get('libp2p_external_addr_confirmed')} "
            f"book={node.external_addrs()}"
        )

        # Explicit add of a distinct advertised address.
        advertised = "/ip4/203.0.113.10/tcp/4001"
        before = int(node.metrics().get("libp2p_external_addr_confirmed", 0))
        node.add_external_address(advertised)
        if not _wait(
            lambda: advertised in node.external_addrs()
            and int(node.metrics().get("libp2p_external_addr_confirmed", 0)) > before,
            timeout=3.0,
        ):
            print(
                f"FAIL: add_external_address "
                f"ext={node.external_addrs()} m={node.metrics()}"
            )
            return 1
        print("OK: add_external_address")

        before_exp = int(node.metrics().get("libp2p_external_addr_expired", 0))
        node.remove_external_address(advertised)
        if not _wait(
            lambda: advertised not in node.external_addrs()
            and int(node.metrics().get("libp2p_external_addr_expired", 0)) > before_exp,
            timeout=3.0,
        ):
            print(
                f"FAIL: remove_external_address "
                f"ext={node.external_addrs()} m={node.metrics()}"
            )
            return 1
        print(
            f"OK: remove_external_address "
            f"expired={node.metrics().get('libp2p_external_addr_expired')}"
        )

        cap = node.capability_status()
        if not cap.get("external_addrs"):
            print(f"FAIL: capability external_addrs: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 32:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        if listen not in (cap.get("external_addrs") or []):
            # listen should remain after removing only advertised
            print(f"FAIL: capability missing listen in external_addrs: {cap.get('external_addrs')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_external_addr_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; external addr book; TCP+TLS remains default mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
