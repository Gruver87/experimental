#!/usr/bin/env python3
"""ADR 0019 Slice BW — mDNS listen addrs respect the shared advertised cap.

mDNS 0.46 advertises every NewListenAddr via DNS-SD. Uncharged listen
sockets (over-cap expansion) must be omitted from mDNS, not leaked on
the LAN. Circuit ``/p2p-circuit`` is still advertised (outside the cap).
Capability ``mdns_listen_addrs_capped`` / phase >= 74.

Windows multicast is often filtered (Slice AS); this lab does not require
a discover event. It probes the forwarded mDNS listen set via metrics.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_mdns_listen_addrs_capped_lab.py
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


def _is_circuit(addr: str) -> bool:
    return "/p2p-circuit" in addr


def _charged_match(addr: str, charged: list[str]) -> bool:
    if addr in charged:
        return True
    for c in charged:
        if addr == c or addr.startswith(c + "/p2p/"):
            return True
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

    hub = abs_native.libp2p_node_new(
        enable_mdns=True,
        enable_reconnect=False,
        max_advertised_external=1,
        mdns_ttl_secs=5,
    )
    peer = abs_native.libp2p_node_new(
        enable_mdns=True,
        enable_reconnect=False,
        mdns_ttl_secs=5,
    )
    try:
        cap = hub.capability_status()
        if not cap.get("mdns_listen_addrs_capped"):
            print(f"FAIL: capability mdns_listen_addrs_capped: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 74:
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
        peer.listen("/ip4/127.0.0.1/tcp/0")

        charged = list(hub.external_addrs())
        used = int(hub.metrics().get("libp2p_advertised_externals_used", 0))
        omitted = int(hub.metrics().get("libp2p_mdns_listen_addr_omitted", 0))
        mdns_adv = int(hub.metrics().get("libp2p_mdns_advertised_listen", -1))
        print(
            f"OK: hub_listen={list(hub.listen_addrs())} charged={charged} "
            f"mdns_adv={mdns_adv} used={used} omitted={omitted}"
        )
        if mdns_adv < 0:
            print("FAIL: missing libp2p_mdns_advertised_listen")
            return 1
        if mdns_adv > 1:
            print(f"FAIL: mDNS advertised listen {mdns_adv} exceed cap 1")
            return 1
        if used > 1:
            print(f"FAIL: advertised used {used} exceed cap 1")
            return 1
        if used >= 1 and mdns_adv < 1:
            print(
                f"FAIL: charged used={used} but mDNS advertised listen {mdns_adv}"
            )
            return 1
        local_listen = [a for a in list(hub.listen_addrs()) if not _is_circuit(a)]
        if len(local_listen) > used and omitted < 1 and mdns_adv >= len(local_listen):
            print(
                f"FAIL: local listen {local_listen} larger than used {used} "
                f"but omitted={omitted} mdns_adv={mdns_adv}"
            )
            return 1

        discovered = _wait(
            lambda: bool(dict(peer.discovered_peers()).get(hub.peer_id)),
            timeout=4.0,
        )
        if discovered:
            got = str(dict(peer.discovered_peers()).get(hub.peer_id) or "")
            print(f"OK: mdns discovered hub addr={got}")
            if got and not _is_circuit(got) and not _charged_match(got, charged):
                print(f"FAIL: mDNS leaked uncharged listen addr: {got}")
                return 1
        else:
            print("OK: no mdns discover (Windows multicast often filtered)")
    finally:
        for n in (peer, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_mdns_listen_addrs_capped_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; mDNS listen addrs capped; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
