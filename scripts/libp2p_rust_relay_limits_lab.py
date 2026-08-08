#!/usr/bin/env python3
"""rust-libp2p circuit-relay-v2 + connection_limits lab (ADR 0019 Slice H).

Part 1 — connection limits: hub with max_established_incoming=1 denies 2nd peer.
Part 2 — relay: hop identify, reservation on relay server, circuit dial + wire.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_relay_limits_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _listen_tcp(node) -> str:
    addrs = node.listen("/ip4/127.0.0.1/tcp/0")
    return addrs[0]


def _part_limits(abs_native) -> None:
    hub = abs_native.libp2p_node_new(
        max_dials=32,
        max_established_incoming=1,
    )
    c1 = abs_native.libp2p_node_new()
    c2 = abs_native.libp2p_node_new()
    try:
        hub_addr = _listen_tcp(hub)
        c1.dial(hub_addr)
        time.sleep(0.35)
        if c1.peer_id not in hub.connected_peers():
            raise RuntimeError(f"first dial failed hub={hub.metrics()}")

        try:
            c2.dial(hub_addr)
        except Exception:
            pass
        time.sleep(0.5)
        m = hub.metrics()
        if int(m.get("libp2p_conn_limit_denied", 0)) < 1:
            raise RuntimeError(f"expected conn limit deny, metrics={m}")
        if int(m.get("libp2p_peers", 0)) > 1:
            raise RuntimeError(f"hub accepted too many peers: {m}")
        print("OK: connection_limits denied second inbound")
        print(f"  conn_limit_denied={m.get('libp2p_conn_limit_denied')}")
    finally:
        for n in (hub, c1, c2):
            try:
                n.close()
            except Exception:
                pass


def _part_relay(abs_native) -> None:
    relay = abs_native.libp2p_node_new()
    listener = abs_native.libp2p_node_new()
    dialer = abs_native.libp2p_node_new()
    try:
        r_tcp = _listen_tcp(relay)
        _listen_tcp(listener)
        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"

        # Direct dial so identify sees hop protocol before reservation.
        listener.dial(relay_ma)
        time.sleep(0.4)
        info = listener.identify_info(relay.peer_id)
        protos = info.get("protocols") or []
        if not any("circuit/relay" in str(p) for p in protos):
            raise RuntimeError(f"relay hop protocol missing in identify: {info}")

        circuits = []
        try:
            circuits = list(listener.listen_relay(relay_ma) or [])
        except Exception as exc:
            # Reservation may still land on the relay server; poll metrics.
            print(f"  listen_relay note: {exc}")

        reserved = False
        for _ in range(50):
            rm = relay.metrics()
            lm = listener.metrics()
            if int(rm.get("libp2p_relay_reservations", 0)) >= 1:
                reserved = True
                break
            if int(lm.get("libp2p_relay_reservations", 0)) >= 1:
                reserved = True
                break
            circuits = list(listener.circuit_addrs()) or circuits
            if circuits:
                reserved = True
                break
            time.sleep(0.1)
        if not reserved:
            raise RuntimeError(
                f"no relay reservation; relay={relay.metrics()} "
                f"listener={listener.metrics()} err={listener.capability_status().get('error')}"
            )

        circuit_dial = f"{relay_ma}/p2p-circuit/p2p/{listener.peer_id}"
        dialer.dial(circuit_dial)
        time.sleep(0.8)
        if listener.peer_id not in dialer.connected_peers():
            raise RuntimeError(
                f"circuit dial failed dialer={dialer.metrics()} "
                f"listener={listener.metrics()} relay={relay.metrics()}"
            )

        payload = abs_native.libp2p_pack_wire("ping", b"relay-h")
        ack = dialer.send_wire(listener.peer_id, payload)
        if not (isinstance(ack, (bytes, bytearray)) and bytes(ack).startswith(b"OK:")):
            raise RuntimeError(f"bad wire ack over circuit: {ack!r}")

        rm = relay.metrics()
        print("OK: circuit-relay-v2 reservation + wire over circuit")
        print(f"  hop_protocols: {[p for p in protos if 'relay' in str(p)]}")
        print(f"  circuit_addrs: {circuits or listener.circuit_addrs()}")
        print(
            f"  relay_reservations={rm.get('libp2p_relay_reservations')} "
            f"circuits={rm.get('libp2p_relay_circuits')}"
        )
    finally:
        for n in (relay, listener, dialer):
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
        _part_limits(abs_native)
        _part_relay(abs_native)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print("OK: libp2p_rust_relay_limits_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; not prod mesh; not tip proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
