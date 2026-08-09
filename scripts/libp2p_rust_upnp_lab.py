#!/usr/bin/env python3
"""ADR 0019 Slice AD — UPnP / IGD port-mapping lab (opt-in).

Without a real IGD gateway (typical CI / Windows loopback), expects
``GatewayNotFound`` or ``NonRoutableGateway`` counters. With a gateway,
``NewExternalAddr`` may fire instead.

Requires abs_native built with Cargo features ``libp2p`` + ``upnp``.

Usage:
  python scripts/libp2p_rust_upnp_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 20.0, step: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def _upnp_activity(m: dict) -> int:
    return (
        int(m.get("libp2p_upnp_external_addrs", 0))
        + int(m.get("libp2p_upnp_gateway_not_found", 0))
        + int(m.get("libp2p_upnp_non_routable_gateway", 0))
        + int(m.get("libp2p_upnp_expired_external_addrs", 0))
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

    # Control: UPnP off → no activity after listen.
    off = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_upnp=False
    )
    try:
        off.listen("/ip4/127.0.0.1/tcp/0")
        time.sleep(0.5)
        om = off.metrics()
        if _upnp_activity(om) != 0:
            print(f"FAIL: upnp off still active: {om}")
            return 1
        if off.capability_status().get("upnp"):
            print("FAIL: capability upnp true when disabled")
            return 1
        print("OK: UPnP off stays silent")
    finally:
        try:
            off.close()
        except Exception:
            pass

    node = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_upnp=True
    )
    try:
        addrs = node.listen("/ip4/127.0.0.1/tcp/0")
        if not addrs:
            print("FAIL: empty listen")
            return 1
        print(f"OK: listen {addrs[0]}")

        ok = _wait(lambda: _upnp_activity(node.metrics()) >= 1, timeout=25.0)
        m = node.metrics()
        if not ok:
            print(f"FAIL: no UPnP event within timeout: {m}")
            return 1

        cap = node.capability_status()
        if not cap.get("upnp"):
            print(f"FAIL: capability upnp: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 29:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        print(
            f"OK: UPnP activity "
            f"external={m.get('libp2p_upnp_external_addrs')} "
            f"not_found={m.get('libp2p_upnp_gateway_not_found')} "
            f"non_routable={m.get('libp2p_upnp_non_routable_gateway')} "
            f"expired={m.get('libp2p_upnp_expired_external_addrs')}"
        )
        print("  note: GatewayNotFound is expected without a real IGD")
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_upnp_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; UPnP opt-in; TCP+TLS remains default mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
