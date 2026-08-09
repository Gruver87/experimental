#!/usr/bin/env python3
"""ADR 0019 Slice AR — AutoNAT probe event taxonomy lab.

Client probes server → ``autonat_outbound_probe`` / ``autonat_inbound_probe``.
Capability ``autonat_events`` / phase 43.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_autonat_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

    server = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_autonat=True
    )
    client = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, enable_autonat=True
    )
    try:
        s_addr = server.listen("/ip4/127.0.0.1/tcp/0")[0]
        # Dial-only client (Windows loopback listen+redial footgun).
        server_ma = f"{s_addr}/p2p/{server.peer_id}"
        if client.dial(server_ma) != server.peer_id:
            print("FAIL: dial server")
            return 1
        if not _wait(
            lambda: server.peer_id in client.connected_peers()
            and client.peer_id in server.connected_peers(),
            timeout=5.0,
        ):
            print("FAIL: not connected")
            return 1

        client.autonat_add_server(server.peer_id, server_ma)

        if not _wait(
            lambda: (
                int(client.metrics().get("libp2p_autonat_outbound_probe", 0)) >= 1
                or int(server.metrics().get("libp2p_autonat_inbound_probe", 0)) >= 1
            ),
            timeout=12.0,
        ):
            print(
                f"FAIL: no probe taxonomy "
                f"client={client.metrics()} server={server.metrics()}"
            )
            return 1

        cm = client.metrics()
        sm = server.metrics()
        print(
            f"OK: outbound={cm.get('libp2p_autonat_outbound_probe')} "
            f"inbound={sm.get('libp2p_autonat_inbound_probe')} "
            f"out_err={cm.get('libp2p_autonat_outbound_probe_error')} "
            f"in_err={sm.get('libp2p_autonat_inbound_probe_error')} "
            f"probes_c={cm.get('libp2p_autonat_probes')} "
            f"probes_s={sm.get('libp2p_autonat_probes')}"
        )

        cap = client.capability_status()
        if not cap.get("autonat_events"):
            print(f"FAIL: capability autonat_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 43:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, server):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_autonat_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; AutoNAT events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
