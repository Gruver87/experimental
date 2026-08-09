#!/usr/bin/env python3
"""ADR 0019 Slice AI — connection close cause taxonomy lab.

Local ``disconnect_peer`` → ``libp2p_connection_closed_local``;
remote close → ``libp2p_connection_closed_io`` (best-effort).
Keep-alive path remains covered by Slice V (``idle_timeout_closes``).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_connection_close_cause_lab.py
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
            and int(client.metrics().get("libp2p_dial_ok", 0)) >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: establish hub={hub.metrics()} client={client.metrics()}")
            return 1
        print("OK: established")

        # Local close on hub → connection_closed_local.
        before = int(hub.metrics().get("libp2p_connection_closed", 0))
        local_before = int(hub.metrics().get("libp2p_connection_closed_local", 0))
        hub.disconnect_peer(client.peer_id)
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_connection_closed", 0)) > before
            and int(hub.metrics().get("libp2p_connection_closed_local", 0))
            > local_before,
            timeout=4.0,
        ):
            print(f"FAIL: local close cause hub={hub.metrics()}")
            return 1
        hm = hub.metrics()
        print(
            f"OK: local close "
            f"closed={hm.get('libp2p_connection_closed')} "
            f"local={hm.get('libp2p_connection_closed_local')} "
            f"io={hm.get('libp2p_connection_closed_io')} "
            f"keep_alive={hm.get('libp2p_connection_closed_keep_alive')}"
        )

        # Re-dial; remote close (client.close) → hub typically sees IO.
        remote2 = client.dial(hub_addr)
        if remote2 != hub.peer_id:
            print(f"FAIL: redial remote {remote2}")
            return 1
        if not _wait(
            lambda: client.peer_id in hub.connected_peers(),
            timeout=4.0,
        ):
            print(f"FAIL: redial not connected hub={hub.connected_peers()}")
            return 1

        closed_before = int(hub.metrics().get("libp2p_connection_closed", 0))
        io_before = int(hub.metrics().get("libp2p_connection_closed_io", 0))
        local_mid = int(hub.metrics().get("libp2p_connection_closed_local", 0))
        client.close()
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_connection_closed", 0))
            > closed_before,
            timeout=4.0,
        ):
            print(f"FAIL: remote close not observed hub={hub.metrics()}")
            return 1
        hm2 = hub.metrics()
        io_after = int(hm2.get("libp2p_connection_closed_io", 0))
        local_after = int(hm2.get("libp2p_connection_closed_local", 0))
        # Remote close is usually IO; accept local if platform reports None.
        if not (io_after > io_before or local_after > local_mid):
            print(f"FAIL: expected io or local bump on remote close: {hm2}")
            return 1
        print(
            f"OK: remote close "
            f"closed={hm2.get('libp2p_connection_closed')} "
            f"io={io_after} local={local_after}"
        )

        cap = hub.capability_status()
        if not cap.get("connection_close_causes"):
            print(f"FAIL: capability connection_close_causes: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 34:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_connection_close_cause_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; close-cause taxonomy; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
