#!/usr/bin/env python3
"""ADR 0019 Slice P — industrial bootstrap reconnect policy lab.

Connect via bootstrap book, local disconnect from bootstrap peer, wait for
auto-redial with backoff metrics (scheduled + ok). Disable policy and confirm
no further schedule.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_reconnect_lab.py
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-reconn-") as td:
        boot_path = str(Path(td) / "bootstrap.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            bootstrap_path=boot_path,
            enable_reconnect=True,
        )
        try:
            # Disable ping unhealthy disconnect so it does not race the lab.
            client.set_ping_unhealthy_policy(False, 8, 0)
            hub.set_ping_unhealthy_policy(False, 8, 0)

            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
            # Dial-only client: listening on loopback races Windows WSAEADDRINUSE (10048) on redial.
            client.bootstrap_add(hub.peer_id, hub_ma)
            results = list(client.bootstrap_dial())
            if not any(p == hub.peer_id and s in ("ok", "already_connected") for p, s in results):
                print(f"FAIL: initial dial: {results}")
                return 1
            if not _wait(lambda: hub.peer_id in client.connected_peers(), timeout=3.0):
                print("FAIL: not connected after bootstrap_dial")
                return 1
            print("OK: initial bootstrap connect")

            # Local drop of bootstrap peer → ConnectionClosed → reconnect schedule.
            client.disconnect_peer(hub.peer_id)
            _wait(lambda: hub.peer_id not in client.connected_peers(), timeout=2.0)
            # Let Windows TCP fully tear down before the first auto-redial.
            time.sleep(0.15)
            if not _wait(
                lambda: int(client.metrics().get("libp2p_reconnect_scheduled", 0)) >= 1,
                timeout=5.0,
            ):
                print(f"FAIL: reconnect not scheduled: {client.metrics()}")
                return 1
            print("OK: reconnect scheduled after disconnect")

            # Allow backoff + settle (per-attempt safety timeout is 8s).
            if not _wait(
                lambda: (
                    hub.peer_id in client.connected_peers()
                    and int(client.metrics().get("libp2p_reconnect_ok", 0)) >= 1
                ),
                timeout=30.0,
            ):
                print(
                    f"FAIL: reconnect did not complete "
                    f"client={client.metrics()} hub_peers={hub.connected_peers()}"
                )
                return 1

            m = client.metrics()
            cap = client.capability_status()
            if not cap.get("reconnect"):
                print(f"FAIL: capability reconnect flag: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 15:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            print("OK: reconnect restored connection")
            print(
                f"  scheduled={m.get('libp2p_reconnect_scheduled')} "
                f"ok={m.get('libp2p_reconnect_ok')} fail={m.get('libp2p_reconnect_fail')}"
            )

            # Disable policy → disconnect should not schedule more.
            before = int(client.metrics().get("libp2p_reconnect_scheduled", 0))
            client.set_reconnect_enabled(False)
            client.disconnect_peer(hub.peer_id)
            time.sleep(0.6)
            after = int(client.metrics().get("libp2p_reconnect_scheduled", 0))
            if after > before:
                print(f"FAIL: reconnect scheduled while disabled before={before} after={after}")
                return 1
            print("OK: reconnect disabled suppresses schedule")
        finally:
            for n in (client, hub):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_reconnect_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; reconnect policy opt-in; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
