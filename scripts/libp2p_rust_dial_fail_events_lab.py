#!/usr/bin/env python3
"""ADR 0019 Slice AU — outbound dial failure taxonomy lab.

Transport: dial closed TCP port → ``dial_fail_transport``.
Wrong PeerId: dial live hub with ghost PeerId → ``dial_fail_wrong_peer_id``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_dial_fail_events_lab.py
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

    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    ghost = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        ghost_pid = ghost.peer_id
        ghost.close()

        # Transport failure: nothing listening on port 1.
        before_t = int(client.metrics().get("libp2p_dial_fail_transport", 0))
        try:
            client.dial("/ip4/127.0.0.1/tcp/1")
        except Exception as exc:
            print(f"  transport dial note: {exc}")
        if not _wait(
            lambda: int(client.metrics().get("libp2p_dial_fail_transport", 0))
            > before_t,
            timeout=4.0,
        ):
            print(f"FAIL: dial_fail_transport client={client.metrics()}")
            return 1
        print(
            f"OK: transport="
            f"{client.metrics().get('libp2p_dial_fail_transport')}"
        )

        # Wrong PeerId on a live listener.
        before_w = int(client.metrics().get("libp2p_dial_fail_wrong_peer_id", 0))
        wrong = f"{hub_addr}/p2p/{ghost_pid}"
        try:
            client.dial(wrong)
        except Exception as exc:
            print(f"  wrong_peer dial note: {exc}")
        if not _wait(
            lambda: int(client.metrics().get("libp2p_dial_fail_wrong_peer_id", 0))
            > before_w,
            timeout=4.0,
        ):
            print(f"FAIL: dial_fail_wrong_peer_id client={client.metrics()}")
            return 1
        print(
            f"OK: wrong_peer_id="
            f"{client.metrics().get('libp2p_dial_fail_wrong_peer_id')} "
            f"dial_fail={client.metrics().get('libp2p_dial_fail')}"
        )

        cap = client.capability_status()
        if not cap.get("dial_fail_events"):
            print(f"FAIL: capability dial_fail_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 46:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_dial_fail_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; dial fail events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
