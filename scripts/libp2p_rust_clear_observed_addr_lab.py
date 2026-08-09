#!/usr/bin/env python3
"""ADR 0019 Slice BL — clear_observed_addr lab.

After identify fills ``last_observed_addr``, ``clear_observed_addr`` returns
the previous value, wipes the surface, and bumps ``observed_addr_cleared``.
Does not touch the external address book. Capability ``clear_observed_addr``
/ phase >= 63.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_clear_observed_addr_lab.py
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

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addr)
        if not _wait(
            lambda: str(client.metrics().get("libp2p_last_observed_addr", "")).strip()
            and int(client.metrics().get("libp2p_observed_addr_updates", 0)) >= 1,
            timeout=6.0,
        ):
            print(f"FAIL: no observed addr: {client.metrics()}")
            return 1

        obs = str(client.metrics().get("libp2p_last_observed_addr", ""))
        before = int(client.metrics().get("libp2p_observed_addr_cleared", 0))
        ext_before = list(client.external_addrs())

        cleared = client.clear_observed_addr()
        if cleared != obs:
            print(f"FAIL: clear returned {cleared!r} want {obs!r}")
            return 1
        if int(client.metrics().get("libp2p_observed_addr_cleared", 0)) != before + 1:
            print(f"FAIL: cleared counter: {client.metrics()}")
            return 1
        if list(client.external_addrs()) != ext_before:
            print(
                f"FAIL: external book changed "
                f"before={ext_before} after={client.external_addrs()}"
            )
            return 1

        # Stop identify refill, then prove empty clear is a no-op.
        try:
            hub.close()
        except Exception:
            pass
        hub = None
        time.sleep(0.15)
        if str(client.metrics().get("libp2p_last_observed_addr", "")).strip():
            client.clear_observed_addr()
        before2 = int(client.metrics().get("libp2p_observed_addr_cleared", 0))
        empty = client.clear_observed_addr()
        if empty != "":
            print(f"FAIL: empty clear returned {empty!r}")
            return 1
        if int(client.metrics().get("libp2p_observed_addr_cleared", 0)) != before2:
            print(f"FAIL: empty clear bumped counter: {client.metrics()}")
            return 1

        cap = client.capability_status()
        print(
            f"OK: cleared={cleared} "
            f"counter={client.metrics().get('libp2p_observed_addr_cleared')}"
        )
        if not cap.get("clear_observed_addr"):
            print(f"FAIL: capability clear_observed_addr: {cap}")
            return 1
        if not cap.get("identify_observed_addr"):
            print(f"FAIL: capability identify_observed_addr: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 63:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            if n is None:
                continue
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_clear_observed_addr_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; clear observed-addr; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
