#!/usr/bin/env python3
"""ADR 0019 Slice CY — AutoNAT/UPnP ExternalAddrConfirmed must not evict charged addrs.

``libp2p-autonat`` / ``libp2p-upnp`` emit ``ToSwarm::ExternalAddrConfirmed``.
Swarm maps that to ``add_external_address``, which occupies Identify/Kad/Relay
``ExternalAddresses`` (silent eviction past 20). Slice CY forwards only after
the unique advertised cap admits the canonical charge key (trailing
``/p2p/<peer>`` stripped) and omits otherwise. Lab: fill 20 charged, enable
AutoNAT+UPnP, wait for probe or gateway-not-found; crate book still has every
charged addr and no ``/p2p-circuit``. Do not require omitted >= 1 (CI has no
IGD; AutoNAT may only refresh an already-charged listen).

Capability ``behaviour_external_confirmed_capped`` / phase >= 102.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_behaviour_external_confirmed_capped_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOOK = 20
WANT = "admit_canonical_or_omit"


def _wait(pred, timeout: float = 12.0, step: float = 0.1) -> bool:
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

    mod_strategy = str(
        getattr(abs_native, "BEHAVIOUR_EXTERNAL_CONFIRMED_STRATEGY", "")
    )
    if mod_strategy != WANT:
        print(f"FAIL: module strategy {mod_strategy!r} != {WANT}")
        return 1

    book = int(getattr(abs_native, "LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX", 0) or 0)
    if book != BOOK:
        print(f"FAIL: libp2p ExternalAddresses book max {book}")
        return 1

    server = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_autonat=True
    )
    listener = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        enable_autonat=True,
        enable_upnp=True,
    )
    try:
        cap = listener.capability_status()
        if not cap.get("behaviour_external_confirmed_capped"):
            print(f"FAIL: capability behaviour_external_confirmed_capped: {cap}")
            return 1
        if cap.get("behaviour_external_confirmed_strategy") != WANT:
            print(
                "FAIL: capability strategy "
                f"{cap.get('behaviour_external_confirmed_strategy')!r} != {WANT}"
            )
            return 1
        if not cap.get("swarm_external_addrs"):
            print(f"FAIL: capability swarm_external_addrs: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 102:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        s_tcp = server.listen("/ip4/127.0.0.1/tcp/0")[0]
        l_tcp = listener.listen("/ip4/127.0.0.1/tcp/0")[0]
        if not _wait(lambda: l_tcp in listener.external_addrs(), timeout=4.0):
            print(f"FAIL: listen not charged: {listener.external_addrs()}")
            return 1

        charged = [l_tcp]
        i = 0
        while int(listener.metrics().get("libp2p_advertised_externals_used", 0)) < book:
            if i >= 40:
                print(
                    "FAIL: could not fill advertised book: "
                    f"used={listener.metrics().get('libp2p_advertised_externals_used')} "
                    f"charged={len(charged)}"
                )
                return 1
            addr = f"/ip4/203.0.113.{(i % 250) + 1}/tcp/{4300 + i}"
            if listener.add_external_address(addr):
                charged.append(addr)
            i += 1
        used = int(listener.metrics().get("libp2p_advertised_externals_used", 0))
        if used != book:
            print(f"FAIL: used {used} after filling book {book}")
            return 1
        print(
            f"OK: filled {book} charged "
            f"(1 listen + {len(charged) - 1} operator/aux)"
        )

        crate0 = list(listener.swarm_external_addrs())
        missing0 = [a for a in charged if a not in crate0]
        if missing0:
            print(f"FAIL: charged missing from crate book before probes: {missing0}")
            return 1
        if any("p2p-circuit" in a for a in crate0):
            print(f"FAIL: circuit already in crate book: {crate0}")
            return 1

        server_ma = f"{s_tcp}/p2p/{server.peer_id}"
        if listener.dial(server_ma) != server.peer_id:
            print("FAIL: dial AutoNAT server")
            return 1
        if not _wait(
            lambda: server.peer_id in listener.connected_peers(),
            timeout=5.0,
        ):
            print(f"FAIL: listener did not connect to server: {listener.metrics()}")
            return 1

        listener.autonat_add_server(server.peer_id, server_ma)

        activity = _wait(
            lambda: (
                int(listener.metrics().get("libp2p_autonat_outbound_probe", 0)) >= 1
                or int(listener.metrics().get("libp2p_autonat_outbound_probe_error", 0))
                >= 1
                or int(server.metrics().get("libp2p_autonat_inbound_probe", 0)) >= 1
                or int(listener.metrics().get("libp2p_upnp_gateway_not_found", 0)) >= 1
                or int(listener.metrics().get("libp2p_upnp_external_addrs", 0)) >= 1
                or int(listener.metrics().get("libp2p_upnp_non_routable_gateway", 0))
                >= 1
                or int(
                    listener.metrics().get(
                        "libp2p_autonat_external_confirmed_omitted", 0
                    )
                )
                >= 1
                or int(
                    listener.metrics().get("libp2p_upnp_external_confirmed_omitted", 0)
                )
                >= 1
            ),
            timeout=12.0,
        )
        if not activity:
            print(
                "FAIL: no AutoNAT/UPnP activity; "
                f"listener={listener.metrics()} server={server.metrics()}"
            )
            return 1
        time.sleep(0.4)

        crate = list(listener.swarm_external_addrs())
        circuit_in_crate = [a for a in crate if "p2p-circuit" in a]
        if circuit_in_crate:
            print(f"FAIL: circuit occupied crate ExternalAddresses: {circuit_in_crate}")
            return 1
        missing = [a for a in charged if a not in crate]
        if missing:
            print(
                f"FAIL: charged evicted from crate book after AutoNAT/UPnP: {missing}"
            )
            return 1
        omitted_a = int(
            listener.metrics().get("libp2p_autonat_external_confirmed_omitted", 0)
        )
        omitted_u = int(
            listener.metrics().get("libp2p_upnp_external_confirmed_omitted", 0)
        )
        print(
            f"OK: crate book still {len(charged)} charged; "
            f"autonat_omitted={omitted_a} upnp_omitted={omitted_u} "
            f"crate_len={len(crate)} "
            f"upnp_gnf={listener.metrics().get('libp2p_upnp_gateway_not_found')} "
            f"autonat_out={listener.metrics().get('libp2p_autonat_outbound_probe')}"
        )
    finally:
        for n in (listener, server):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_behaviour_external_confirmed_capped_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; AutoNAT/UPnP confirm gated through "
        "advertised cap; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
