#!/usr/bin/env python3
"""ADR 0019 Slice AP — relay event taxonomy metrics lab.

Success: reservation + circuit → ``relay_reservations`` / ``relay_circuits``.
Close: disconnect dialer → ``relay_circuit_closed``.
Deny reservation: ``relay_max_reservations=1`` + second listener.
Deny circuit: dial circuit to peer without reservation.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_relay_events_lab.py
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


def _reserve(listener, relay, relay_ma: str) -> None:
    listener.dial(relay_ma)
    if not _wait(lambda: relay.peer_id in listener.connected_peers(), timeout=3.0):
        raise RuntimeError("listener not connected to relay")
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
        raise RuntimeError(
            f"no reservation relay={relay.metrics()} listener={listener.metrics()}"
        )


def _part_accept_and_close(abs_native) -> None:
    relay = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    listener = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    dialer = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        r_tcp = _listen_tcp(relay)
        _listen_tcp(listener)
        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"
        _reserve(listener, relay, relay_ma)

        circuit_dial = f"{relay_ma}/p2p-circuit/p2p/{listener.peer_id}"
        dialer.dial(circuit_dial)
        if not _wait(
            lambda: listener.peer_id in dialer.connected_peers(),
            timeout=4.0,
        ):
            raise RuntimeError(
                f"circuit dial failed dialer={dialer.metrics()} "
                f"relay={relay.metrics()}"
            )
        if not _wait(
            lambda: int(relay.metrics().get("libp2p_relay_circuits", 0)) >= 1,
            timeout=3.0,
        ):
            raise RuntimeError(f"circuits metric missing relay={relay.metrics()}")

        closed_before = int(relay.metrics().get("libp2p_relay_circuit_closed", 0))
        dialer.close()
        if not _wait(
            lambda: int(relay.metrics().get("libp2p_relay_circuit_closed", 0))
            > closed_before,
            timeout=5.0,
        ):
            raise RuntimeError(
                f"expected circuit_closed relay={relay.metrics()}"
            )
        rm = relay.metrics()
        print(
            f"OK: accept+close reservations={rm.get('libp2p_relay_reservations')} "
            f"circuits={rm.get('libp2p_relay_circuits')} "
            f"closed={rm.get('libp2p_relay_circuit_closed')}"
        )
    finally:
        for n in (dialer, listener, relay):
            try:
                n.close()
            except Exception:
                pass


def _part_reservation_denied(abs_native) -> None:
    relay = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, relay_max_reservations=1
    )
    a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        r_tcp = _listen_tcp(relay)
        _listen_tcp(a)
        _listen_tcp(b)
        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"
        _reserve(a, relay, relay_ma)

        denied_before = int(relay.metrics().get("libp2p_relay_reservation_denied", 0))
        b.dial(relay_ma)
        try:
            b.listen_relay(relay_ma)
        except Exception as exc:
            print(f"  second listen_relay note: {exc}")
        if not _wait(
            lambda: int(relay.metrics().get("libp2p_relay_reservation_denied", 0))
            > denied_before,
            timeout=5.0,
        ):
            raise RuntimeError(
                f"expected reservation_denied relay={relay.metrics()}"
            )
        print(
            f"OK: reservation_denied="
            f"{relay.metrics().get('libp2p_relay_reservation_denied')} "
            f"max={relay.metrics().get('libp2p_relay_max_reservations')}"
        )
    finally:
        for n in (a, b, relay):
            try:
                n.close()
            except Exception:
                pass


def _part_circuit_denied(abs_native) -> None:
    relay = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    ghost = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    dialer = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        r_tcp = _listen_tcp(relay)
        ghost_pid = ghost.peer_id
        ghost.close()
        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"
        dialer.dial(relay_ma)
        if not _wait(lambda: relay.peer_id in dialer.connected_peers(), timeout=3.0):
            raise RuntimeError("dialer not connected to relay")

        denied_before = int(relay.metrics().get("libp2p_relay_circuit_denied", 0))
        circuit_dial = f"{relay_ma}/p2p-circuit/p2p/{ghost_pid}"
        try:
            dialer.dial(circuit_dial)
        except Exception as exc:
            print(f"  circuit dial note: {exc}")
        if not _wait(
            lambda: int(relay.metrics().get("libp2p_relay_circuit_denied", 0))
            > denied_before,
            timeout=5.0,
        ):
            raise RuntimeError(
                f"expected circuit_denied relay={relay.metrics()}"
            )
        print(
            f"OK: circuit_denied="
            f"{relay.metrics().get('libp2p_relay_circuit_denied')}"
        )
    finally:
        for n in (dialer, relay):
            try:
                n.close()
            except Exception:
                pass


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    try:
        _part_accept_and_close(abs_native)
        _part_reservation_denied(abs_native)
        _part_circuit_denied(abs_native)

        probe = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        try:
            cap = probe.capability_status()
            if not cap.get("relay_events"):
                raise RuntimeError(f"capability relay_events: {cap}")
            if int(cap.get("phase", 0)) < 41:
                raise RuntimeError(f"phase {cap.get('phase')}")
        finally:
            probe.close()
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print("OK: libp2p_rust_relay_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; relay events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
