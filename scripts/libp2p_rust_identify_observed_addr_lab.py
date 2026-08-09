#!/usr/bin/env python3
"""ADR 0019 Slice BG — identify observed-addr + confirm lab.

After dial/identify, ``last_observed_addr`` / ``observed_addr_updates`` fill in.
``confirm_observed_addr`` promotes that address into the external book.
Capability ``identify_observed_addr`` / phase >= 58.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identify_observed_addr_lab.py
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


def _is_loopback(addr: str) -> bool:
    return (
        "/ip4/127.0.0.1/" in addr
        or "/ip4/127." in addr
        or "/ip6/::1/" in addr
        or "/ip6/0:0:0:0:0:0:0:1/" in addr
    )


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
            lambda: int(hub.metrics().get("libp2p_observed_addr_updates", 0)) >= 1
            and int(client.metrics().get("libp2p_observed_addr_updates", 0)) >= 1
            and str(hub.metrics().get("libp2p_last_observed_addr", ""))
            and str(client.metrics().get("libp2p_last_observed_addr", "")),
            timeout=6.0,
        ):
            print(
                f"FAIL: observed addr "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1

        hub_obs = str(hub.metrics().get("libp2p_last_observed_addr", ""))
        client_obs = str(client.metrics().get("libp2p_last_observed_addr", ""))
        if not (_is_loopback(hub_obs) or _is_loopback(client_obs)):
            print(f"FAIL: expected loopback observed hub={hub_obs!r} client={client_obs!r}")
            return 1

        before_conf = int(client.metrics().get("libp2p_observed_addr_confirmed", 0))
        before_ext = int(client.metrics().get("libp2p_external_addr_confirmed", 0))
        confirmed = client.confirm_observed_addr()
        if confirmed != client_obs:
            print(f"FAIL: confirm returned {confirmed!r} want {client_obs!r}")
            return 1
        if confirmed not in client.external_addrs():
            print(f"FAIL: not in external book: {client.external_addrs()}")
            return 1
        if not _wait(
            lambda: int(client.metrics().get("libp2p_observed_addr_confirmed", 0))
            > before_conf
            and int(client.metrics().get("libp2p_external_addr_confirmed", 0))
            > before_ext,
            timeout=3.0,
        ):
            print(f"FAIL: confirm counters: {client.metrics()}")
            return 1

        cm = client.metrics()
        hm = hub.metrics()
        print(
            f"OK: hub_obs={hm.get('libp2p_last_observed_addr')} "
            f"client_obs={cm.get('libp2p_last_observed_addr')} "
            f"updates={cm.get('libp2p_observed_addr_updates')} "
            f"confirmed={cm.get('libp2p_observed_addr_confirmed')}"
        )

        cap = client.capability_status()
        if not cap.get("identify_observed_addr"):
            print(f"FAIL: capability identify_observed_addr: {cap}")
            return 1
        if str(cap.get("last_observed_addr", "")) != client_obs:
            print(f"FAIL: capability last_observed_addr: {cap.get('last_observed_addr')!r}")
            return 1
        if int(cap.get("phase", 0)) < 58:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_identify_observed_addr_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; identify observed-addr; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
