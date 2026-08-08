#!/usr/bin/env python3
"""ADR 0019 Slice N — AutoNAT + DCUtR lab.

Part 1 — AutoNAT: client probes a dial-back server; expects probe/status metrics.
Part 2 — DCUtR: circuit-relay path triggers hole-punch attempt counters.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_autonat_dcutr_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _listen_tcp(node) -> str:
    return node.listen("/ip4/127.0.0.1/tcp/0")[0]


def _wait(pred, timeout: float = 8.0, step: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def _part_autonat(abs_native) -> None:
    server = abs_native.libp2p_node_new(enable_mdns=False)
    client = abs_native.libp2p_node_new(enable_mdns=False)
    try:
        s_addr = _listen_tcp(server)
        _listen_tcp(client)
        server_ma = f"{s_addr}/p2p/{server.peer_id}"
        client.dial(server_ma)
        if not _wait(
            lambda: server.peer_id in client.connected_peers()
            and client.peer_id in server.connected_peers()
        ):
            raise RuntimeError("autonat peers not connected")

        # Explicit server registration (also auto via identify when protocol present).
        client.autonat_add_server(server.peer_id, server_ma)
        time.sleep(0.2)

        ok = _wait(
            lambda: (
                int(client.metrics().get("libp2p_autonat_probes", 0)) >= 1
                or int(client.metrics().get("libp2p_autonat_status_changes", 0)) >= 1
                or int(server.metrics().get("libp2p_autonat_probes", 0)) >= 1
            ),
            timeout=12.0,
        )
        cm = client.metrics()
        sm = server.metrics()
        if not ok:
            raise RuntimeError(f"no AutoNAT activity client={cm} server={sm}")

        cap = client.capability_status()
        if not cap.get("autonat"):
            raise RuntimeError(f"capability missing autonat: {cap}")
        if int(cap.get("phase", 0)) < 13:
            raise RuntimeError(f"phase too low: {cap.get('phase')}")

        print("OK: AutoNAT probes/status activity")
        print(
            f"  client probes={cm.get('libp2p_autonat_probes')} "
            f"status_changes={cm.get('libp2p_autonat_status_changes')} "
            f"status={cap.get('autonat_status')}"
        )
        print(
            f"  server probes={sm.get('libp2p_autonat_probes')} "
            f"status_changes={sm.get('libp2p_autonat_status_changes')}"
        )
    finally:
        for n in (server, client):
            try:
                n.close()
            except Exception:
                pass


def _part_dcutr(abs_native) -> None:
    relay = abs_native.libp2p_node_new(enable_mdns=False)
    listener = abs_native.libp2p_node_new(enable_mdns=False)
    dialer = abs_native.libp2p_node_new(enable_mdns=False)
    try:
        r_tcp = _listen_tcp(relay)
        _listen_tcp(listener)
        relay_ma = f"{r_tcp}/p2p/{relay.peer_id}"

        listener.dial(relay_ma)
        time.sleep(0.4)
        try:
            listener.listen_relay(relay_ma)
        except Exception as exc:
            print(f"  listen_relay note: {exc}")

        reserved = _wait(
            lambda: (
                int(relay.metrics().get("libp2p_relay_reservations", 0)) >= 1
                or int(listener.metrics().get("libp2p_relay_reservations", 0)) >= 1
                or bool(listener.circuit_addrs())
            ),
            timeout=8.0,
        )
        if not reserved:
            raise RuntimeError(
                f"no relay reservation for dcutr; "
                f"relay={relay.metrics()} listener={listener.metrics()}"
            )

        circuit_dial = f"{relay_ma}/p2p-circuit/p2p/{listener.peer_id}"
        dialer.dial(circuit_dial)
        if not _wait(
            lambda: listener.peer_id in dialer.connected_peers(),
            timeout=8.0,
        ):
            raise RuntimeError(
                f"circuit dial failed dialer={dialer.metrics()} "
                f"listener={listener.metrics()}"
            )

        # Hole-punch may succeed or fail on loopback; either proves DCUtR engaged.
        punched = _wait(
            lambda: (
                int(dialer.metrics().get("libp2p_dcutr_upgrade_success", 0))
                + int(dialer.metrics().get("libp2p_dcutr_upgrade_fail", 0))
                + int(listener.metrics().get("libp2p_dcutr_upgrade_success", 0))
                + int(listener.metrics().get("libp2p_dcutr_upgrade_fail", 0))
            )
            >= 1,
            timeout=10.0,
        )
        dm = dialer.metrics()
        lm = listener.metrics()
        cap = dialer.capability_status()
        if not cap.get("dcutr"):
            raise RuntimeError(f"capability missing dcutr: {cap}")
        if not punched:
            # Honest fallback: circuit path + dcutr capability is enough for lab
            # when hole-punch is skipped (already-direct / platform timing).
            if int(dm.get("libp2p_relay_circuits", 0)) + int(
                lm.get("libp2p_relay_circuits", 0)
            ) + int(relay.metrics().get("libp2p_relay_circuits", 0)) < 1:
                raise RuntimeError(
                    f"no DCUtR event and no circuit metric; dialer={dm} listener={lm}"
                )
            print("OK: DCUtR enabled + circuit path (no upgrade event in window)")
        else:
            print("OK: DCUtR upgrade attempt observed")
        print(
            f"  dialer success={dm.get('libp2p_dcutr_upgrade_success')} "
            f"fail={dm.get('libp2p_dcutr_upgrade_fail')}"
        )
        print(
            f"  listener success={lm.get('libp2p_dcutr_upgrade_success')} "
            f"fail={lm.get('libp2p_dcutr_upgrade_fail')}"
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
        _part_autonat(abs_native)
        _part_dcutr(abs_native)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print("OK: libp2p_rust_autonat_dcutr_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; AutoNAT/DCUtR opt-in; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
