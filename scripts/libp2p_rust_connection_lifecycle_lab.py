#!/usr/bin/env python3
"""ADR 0019 Slice AH — connection lifecycle metrics lab.

Hub sees IncomingConnection + inbound_established; client dial_ok;
close → connection_closed on both sides.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_connection_lifecycle_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 5.0, step: float = 0.05) -> bool:
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

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote}")
            return 1

        if not _wait(
            lambda: int(hub.metrics().get("libp2p_inbound_established", 0)) >= 1
            and int(hub.metrics().get("libp2p_incoming_connections", 0)) >= 1
            and int(client.metrics().get("libp2p_dial_ok", 0)) >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: establish hub={hub.metrics()} client={client.metrics()}")
            return 1

        hm = hub.metrics()
        cm = client.metrics()
        if int(cm.get("libp2p_established_in_ms_last", 0)) < 0:
            print(f"FAIL: client established_in_ms_last: {cm}")
            return 1
        print(
            f"OK: established "
            f"hub inbound={hm.get('libp2p_inbound_established')} "
            f"incoming={hm.get('libp2p_incoming_connections')} "
            f"client dial_ok={cm.get('libp2p_dial_ok')} "
            f"est_ms={cm.get('libp2p_established_in_ms_last')}"
        )

        hub_closed_before = int(hm.get("libp2p_connection_closed", 0))
        client_closed_before = int(cm.get("libp2p_connection_closed", 0))
        client.close()
        # client object closed; only hub remains observable
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_connection_closed", 0))
            > hub_closed_before,
            timeout=4.0,
        ):
            print(f"FAIL: hub connection_closed not bumped: {hub.metrics()}")
            return 1
        print(
            f"OK: connection_closed "
            f"hub={hub.metrics().get('libp2p_connection_closed')} "
            f"(client_before={client_closed_before})"
        )

        cap = hub.capability_status()
        if not cap.get("connection_lifecycle"):
            print(f"FAIL: capability connection_lifecycle: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 33:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_connection_lifecycle_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; connection lifecycle; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
