#!/usr/bin/env python3
"""ADR 0019 Slice AT — relay client circuit direction metrics lab.

Reservation + circuit dial → dialer ``relay_outbound_circuit``,
listener ``relay_inbound_circuit``. Capability ``relay_client_events``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_relay_client_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 6.0, step: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def _listen_tcp(node) -> str:
    return node.listen("/ip4/127.0.0.1/tcp/0")[0]


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    relay = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    listener = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    dialer = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        r_tcp = _listen_tcp(relay)
        _listen_tcp(listener)
        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"

        listener.dial(relay_ma)
        if not _wait(lambda: relay.peer_id in listener.connected_peers(), timeout=3.0):
            print("FAIL: listener not connected to relay")
            return 1
        if not _wait(
            lambda: any(
                "circuit/relay" in str(p)
                for p in (listener.identify_info(relay.peer_id).get("protocols") or [])
            ),
            timeout=5.0,
        ):
            print(
                f"FAIL: hop protocol missing: "
                f"{listener.identify_info(relay.peer_id)}"
            )
            return 1

        try:
            listener.listen_relay(relay_ma)
        except Exception as exc:
            print(f"  listen_relay note: {exc}")
        if not _wait(
            lambda: int(relay.metrics().get("libp2p_relay_reservations", 0)) >= 1
            or int(listener.metrics().get("libp2p_relay_reservations", 0)) >= 1
            or bool(listener.circuit_addrs()),
            timeout=5.0,
        ):
            print(
                f"FAIL: no reservation relay={relay.metrics()} "
                f"listener={listener.metrics()}"
            )
            return 1

        circuit_dial = f"{relay_ma}/p2p-circuit/p2p/{listener.peer_id}"
        dialer.dial(circuit_dial)
        if not _wait(
            lambda: listener.peer_id in dialer.connected_peers(),
            timeout=4.0,
        ):
            print(
                f"FAIL: circuit dial dialer={dialer.metrics()} "
                f"relay={relay.metrics()}"
            )
            return 1

        if not _wait(
            lambda: int(dialer.metrics().get("libp2p_relay_outbound_circuit", 0))
            >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: outbound_circuit dialer={dialer.metrics()}")
            return 1
        if not _wait(
            lambda: int(listener.metrics().get("libp2p_relay_inbound_circuit", 0))
            >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: inbound_circuit listener={listener.metrics()}")
            return 1

        dm = dialer.metrics()
        lm = listener.metrics()
        print(
            f"OK: outbound={dm.get('libp2p_relay_outbound_circuit')} "
            f"inbound={lm.get('libp2p_relay_inbound_circuit')} "
            f"circuits_d={dm.get('libp2p_relay_circuits')} "
            f"circuits_l={lm.get('libp2p_relay_circuits')}"
        )

        cap = listener.capability_status()
        if not cap.get("relay_client_events"):
            print(f"FAIL: capability relay_client_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 45:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (dialer, listener, relay):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_relay_client_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; relay client events; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
