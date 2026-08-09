#!/usr/bin/env python3
"""ADR 0019 Slice AL — identify event metrics lab.

Two-node dial → ``libp2p_identify_received`` / ``libp2p_identify_sent``
and ``identify_info(...).received``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identify_events_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 8.0, step: float = 0.05) -> bool:
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
            lambda: int(hub.metrics().get("libp2p_identify_received", 0)) >= 1
            and int(client.metrics().get("libp2p_identify_received", 0)) >= 1
            and int(hub.metrics().get("libp2p_identify_sent", 0)) >= 1
            and int(client.metrics().get("libp2p_identify_sent", 0)) >= 1,
            timeout=6.0,
        ):
            print(
                f"FAIL: identify events "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1

        info = client.identify_info(hub.peer_id)
        if not info.get("received"):
            print(f"FAIL: identify_info not received: {info}")
            return 1
        if not info.get("protocols"):
            print(f"FAIL: empty protocols: {info}")
            return 1

        hm = hub.metrics()
        cm = client.metrics()
        print(
            f"OK: identify "
            f"hub recv={hm.get('libp2p_identify_received')} "
            f"sent={hm.get('libp2p_identify_sent')} "
            f"pushed={hm.get('libp2p_identify_pushed')} "
            f"err={hm.get('libp2p_identify_error')} "
            f"| client recv={cm.get('libp2p_identify_received')} "
            f"sent={cm.get('libp2p_identify_sent')} "
            f"peers={cm.get('libp2p_identify_peers')}"
        )
        print(
            f"OK: identify_info agent={info.get('agent_version')} "
            f"observed={info.get('observed_addr')}"
        )

        cap = hub.capability_status()
        if not cap.get("identify_events"):
            print(f"FAIL: capability identify_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 37:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_identify_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; identify events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
