#!/usr/bin/env python3
"""ADR 0019 Slice BZ — UPnP listen addrs respect the shared advertised cap.

UPnP 0.3 queues an IGD port map on every NewListenAddr (Inactive until
the gateway is found). Uncharged listen sockets (over-cap expansion)
must be omitted from UPnP, not silently mapped. Circuit ``/p2p-circuit``
is still forwarded (outside the cap). Capability
``upnp_listen_addrs_capped`` / phase >= 77.

Does not require a real IGD. CI typically sees GatewayNotFound (Slice AD).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_upnp_listen_addrs_capped_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _is_circuit(addr: str) -> bool:
    return "/p2p-circuit" in addr


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    hub = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        enable_upnp=True,
        max_advertised_external=1,
    )
    try:
        cap = hub.capability_status()
        if not cap.get("upnp_listen_addrs_capped"):
            print(f"FAIL: capability upnp_listen_addrs_capped: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 77:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        hub_addrs = hub.listen("/ip4/127.0.0.1/tcp/0")
        if not hub_addrs:
            print("FAIL: hub listen empty")
            return 1
        raised = False
        try:
            hub.listen("/ip4/127.0.0.1/tcp/0")
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "at max" not in msg and "exceeds max" not in msg:
                print(f"FAIL: second listen error text: {exc}")
                return 1
            print(f"OK: second listen refuse: {exc}")
        if not raised:
            print("FAIL: second listen did not raise under cap 1")
            return 1
        time.sleep(0.3)

        charged = list(hub.external_addrs())
        used = int(hub.metrics().get("libp2p_advertised_externals_used", 0))
        omitted = int(hub.metrics().get("libp2p_upnp_listen_addr_omitted", 0))
        upnp_adv = int(hub.metrics().get("libp2p_upnp_advertised_listen", -1))
        print(
            f"OK: hub_listen={list(hub.listen_addrs())} charged={charged} "
            f"upnp_adv={upnp_adv} used={used} omitted={omitted}"
        )
        if upnp_adv < 0:
            print("FAIL: missing libp2p_upnp_advertised_listen")
            return 1
        if upnp_adv > 1:
            print(f"FAIL: UPnP advertised listen {upnp_adv} exceed cap 1")
            return 1
        if used > 1:
            print(f"FAIL: advertised used {used} exceed cap 1")
            return 1
        if used >= 1 and upnp_adv < 1:
            print(
                f"FAIL: charged used={used} but UPnP advertised listen {upnp_adv}"
            )
            return 1
        local_listen = [a for a in list(hub.listen_addrs()) if not _is_circuit(a)]
        if len(local_listen) > used and omitted < 1 and upnp_adv >= len(local_listen):
            print(
                f"FAIL: local listen {local_listen} larger than used {used} "
                f"but omitted={omitted} upnp_adv={upnp_adv}"
            )
            return 1
    finally:
        try:
            hub.close()
        except Exception:
            pass

    print("OK: libp2p_rust_upnp_listen_addrs_capped_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; UPnP listen addrs capped; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
