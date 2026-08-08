#!/usr/bin/env python3
"""ADR 0019 Slice U — peerstore reconnect policy lab.

Learn hub via dial into peerstore (no bootstrap book), disconnect, wait for
auto-redial from learned peerstore with reconnect_from_peerstore metric.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_peerstore_reconnect_lab.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 12.0, step: float = 0.05) -> bool:
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-psr-") as td:
        store_path = str(Path(td) / "peerstore.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            peerstore_path=store_path,
            enable_reconnect=True,
        )
        try:
            # Disable ping unhealthy disconnect so it does not race the lab.
            client.set_ping_unhealthy_policy(False, 8, 0)
            hub.set_ping_unhealthy_policy(False, 8, 0)

            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            client.listen("/ip4/127.0.0.1/tcp/0")
            client.dial(hub_addr)
            if not _wait(
                lambda: hub.peer_id in client.connected_peers()
                and hub.peer_id in dict(client.peerstore_list()),
                timeout=8.0,
            ):
                print(
                    f"FAIL: learn/connect "
                    f"peers={client.connected_peers()} store={dict(client.peerstore_list())}"
                )
                return 1
            print("OK: connected + peerstore learned (no bootstrap)")

            before_sched = int(client.metrics().get("libp2p_reconnect_scheduled", 0))
            before_ps = int(client.metrics().get("libp2p_reconnect_from_peerstore", 0))
            client.disconnect_peer(hub.peer_id)
            if not _wait(
                lambda: (
                    int(client.metrics().get("libp2p_reconnect_scheduled", 0)) > before_sched
                    and int(client.metrics().get("libp2p_reconnect_from_peerstore", 0))
                    > before_ps
                ),
                timeout=5.0,
            ):
                print(f"FAIL: peerstore reconnect not scheduled: {client.metrics()}")
                return 1
            print("OK: reconnect scheduled from peerstore")

            # Allow backoff + settle; dial-timeout default is 8s per attempt.
            if not _wait(
                lambda: (
                    hub.peer_id in client.connected_peers()
                    and int(client.metrics().get("libp2p_reconnect_ok", 0)) >= 1
                ),
                timeout=20.0,
            ):
                print(
                    f"FAIL: peerstore reconnect incomplete "
                    f"store={dict(client.peerstore_list())} "
                    f"client={client.metrics()} hub={hub.connected_peers()}"
                )
                return 1

            cap = client.capability_status()
            if not cap.get("peerstore_reconnect"):
                print(f"FAIL: capability peerstore_reconnect: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 20:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            m = client.metrics()
            print(
                f"OK: peerstore reconnect restored "
                f"from_ps={m.get('libp2p_reconnect_from_peerstore')} "
                f"ok={m.get('libp2p_reconnect_ok')}"
            )
        finally:
            for n in (client, hub):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_peerstore_reconnect_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; peerstore reconnect opt-in; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
