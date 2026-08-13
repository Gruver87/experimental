#!/usr/bin/env python3
"""ADR 0019 Slice BV — Identify listen addrs respect the shared advertised cap.

Identify 0.45 has no hide_listen_addrs. Uncharged listen sockets (over-cap
expansion) must be omitted from Identify, not leaked to peers. Circuit
``/p2p-circuit`` is still advertised (outside the cap). Capability
``identify_listen_addrs_capped`` / phase >= 73.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identify_listen_addrs_capped_lab.py
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
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=1,
    )
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        cap = hub.capability_status()
        if not cap.get("identify_listen_addrs_capped"):
            print(f"FAIL: capability identify_listen_addrs_capped: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 73:
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
        # Expansion NewListenAddr (dual-stack siblings) may still arrive
        # after listen() returns; Identify must not publish the uncharged set.
        time.sleep(0.3)
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addrs[0])
        if not _wait(
            lambda: bool(client.identify_info(hub.peer_id).get("received")),
            timeout=6.0,
        ):
            print(
                f"FAIL: no identify "
                f"client={client.identify_info(hub.peer_id)} hub={hub.metrics()}"
            )
            return 1
        info = client.identify_info(hub.peer_id)
        advertised = list(info.get("listen_addrs") or [])
        charged = list(hub.external_addrs())
        used = int(hub.metrics().get("libp2p_advertised_externals_used", 0))
        omitted = int(hub.metrics().get("libp2p_identify_listen_addr_omitted", 0))
        print(
            f"OK: hub_listen={list(hub.listen_addrs())} charged={charged} "
            f"identify={advertised} used={used} omitted={omitted}"
        )
        leaked = []
        non_circuit = 0
        for a in advertised:
            if _is_circuit(a):
                continue
            non_circuit += 1
            if not _charged_match(a, charged):
                leaked.append(a)
        if leaked:
            print(f"FAIL: Identify leaked uncharged listen addrs: {leaked}")
            return 1
        if non_circuit > 1:
            print(f"FAIL: Identify non-circuit addrs {non_circuit} exceed cap 1")
            return 1
        if used > 1:
            print(f"FAIL: advertised used {used} exceed cap 1")
            return 1
        local_listen = [
            a for a in list(hub.listen_addrs()) if not _is_circuit(a)
        ]
        if len(local_listen) > used and omitted < 1:
            print(
                f"FAIL: local listen {local_listen} larger than used {used} "
                f"but omitted={omitted}"
            )
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_identify_listen_addrs_capped_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; Identify listen addrs capped; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
