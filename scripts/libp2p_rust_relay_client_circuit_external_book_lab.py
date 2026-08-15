#!/usr/bin/env python3
"""ADR 0019 Slice CX — relay-client circuit must not occupy crate ExternalAddresses.

``libp2p-relay`` client emits ``ToSwarm::ExternalAddrConfirmed`` on
reservation accept. Swarm maps that to ``add_external_address``, which
occupies Identify/Kad/Relay ``ExternalAddresses`` (silent eviction past 20).
Slice CX omits circuit confirm from the client. Lab: fill 20 charged, then
``listen_relay``; crate book still has the 20 charged and no ``/p2p-circuit``.
Capability ``relay_client_circuit_not_in_external_book`` / phase >= 101.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_relay_client_circuit_external_book_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOOK = 20
WANT = "omit_circuit_external_confirmed"


def _wait(pred, timeout: float = 8.0, step: float = 0.1) -> bool:
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
        getattr(abs_native, "RELAY_CLIENT_CIRCUIT_EXTERNAL_STRATEGY", "")
    )
    if mod_strategy != WANT:
        print(f"FAIL: module strategy {mod_strategy!r} != {WANT}")
        return 1

    book = int(getattr(abs_native, "LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX", 0) or 0)
    if book != BOOK:
        print(f"FAIL: libp2p ExternalAddresses book max {book}")
        return 1

    relay = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    listener = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        cap = listener.capability_status()
        if not cap.get("relay_client_circuit_not_in_external_book"):
            print(f"FAIL: capability relay_client_circuit_not_in_external_book: {cap}")
            return 1
        if cap.get("relay_client_circuit_external_strategy") != WANT:
            print(
                "FAIL: capability strategy "
                f"{cap.get('relay_client_circuit_external_strategy')!r} != {WANT}"
            )
            return 1
        if not cap.get("swarm_external_addrs"):
            print(f"FAIL: capability swarm_external_addrs: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 101:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        r_tcp = relay.listen("/ip4/127.0.0.1/tcp/0")[0]
        l_tcp = listener.listen("/ip4/127.0.0.1/tcp/0")[0]
        if not _wait(lambda: l_tcp in listener.external_addrs(), timeout=4.0):
            print(f"FAIL: listen not charged: {listener.external_addrs()}")
            return 1

        charged = [l_tcp]
        for i in range(book - 1):
            addr = f"/ip4/203.0.113.{i + 1}/tcp/{4300 + i}"
            fresh = listener.add_external_address(addr)
            if not fresh:
                print(f"FAIL: add {i} not fresh: {addr}")
                return 1
            charged.append(addr)
        used = int(listener.metrics().get("libp2p_advertised_externals_used", 0))
        if used != book:
            print(f"FAIL: used {used} after filling book {book}")
            return 1
        print(f"OK: filled {book} charged (1 listen + {book - 1} operator)")

        crate0 = list(listener.swarm_external_addrs())
        missing0 = [a for a in charged if a not in crate0]
        if missing0:
            print(f"FAIL: charged missing from crate book before relay: {missing0}")
            return 1
        if any("p2p-circuit" in a for a in crate0):
            print(f"FAIL: circuit already in crate book: {crate0}")
            return 1

        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"
        listener.dial(relay_ma)
        if not _wait(
            lambda: relay.peer_id in listener.connected_peers(),
            timeout=4.0,
        ):
            print(f"FAIL: listener did not connect to relay: {listener.metrics()}")
            return 1

        try:
            listener.listen_relay(relay_ma)
        except Exception as exc:
            print(f"  listen_relay note: {exc}")

        reserved = _wait(
            lambda: int(listener.metrics().get("libp2p_relay_reservations", 0)) >= 1
            or int(relay.metrics().get("libp2p_relay_reservations", 0)) >= 1
            or bool(list(listener.circuit_addrs())),
            timeout=8.0,
        )
        if not reserved:
            print(
                "FAIL: no relay reservation; "
                f"listener={listener.metrics()} relay={relay.metrics()}"
            )
            return 1
        time.sleep(0.4)

        circuits = list(listener.circuit_addrs())
        if not circuits:
            print(f"FAIL: reservation without circuit_addrs: {listener.metrics()}")
            return 1
        print(f"OK: circuit listen {circuits}")

        crate = list(listener.swarm_external_addrs())
        circuit_in_crate = [a for a in crate if "p2p-circuit" in a]
        if circuit_in_crate:
            print(f"FAIL: circuit occupied crate ExternalAddresses: {circuit_in_crate}")
            return 1
        missing = [a for a in charged if a not in crate]
        if missing:
            print(f"FAIL: charged evicted from crate book after relay: {missing}")
            return 1
        omitted = int(
            listener.metrics().get("libp2p_relay_client_circuit_external_omitted", 0)
        )
        if omitted < 1:
            print(
                "FAIL: relay-client circuit confirm was not omitted "
                f"omitted={omitted} crate={crate}"
            )
            return 1
        print(
            f"OK: crate book still {len(charged)} charged; "
            f"circuit omitted={omitted} crate_len={len(crate)}"
        )
    finally:
        for n in (listener, relay):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_relay_client_circuit_external_book_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; relay-client circuit omitted from "
        "rust-libp2p ExternalAddresses book; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
