#!/usr/bin/env python3
"""ADR 0019 Slice BD — identify interval + error taxonomy lab.

With ``ABS_LIBP2P_IDENTIFY_INTERVAL_MS`` short, peers re-identify after the
first exchange. Taxonomy keys for ``identify_error_*`` must be present.
Capability ``identify_interval`` / ``identify_fail_events`` / phase >= 55.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identify_interval_lab.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INTERVAL_MS = 200


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

    prev = os.environ.get("ABS_LIBP2P_IDENTIFY_INTERVAL_MS")
    os.environ["ABS_LIBP2P_IDENTIFY_INTERVAL_MS"] = str(INTERVAL_MS)

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        if int(hub.metrics().get("libp2p_identify_interval_ms", 0)) != INTERVAL_MS:
            print(
                f"FAIL: identify_interval_ms "
                f"{hub.metrics().get('libp2p_identify_interval_ms')} want {INTERVAL_MS}"
            )
            return 1

        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addr)
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_identify_received", 0)) >= 1
            and int(client.metrics().get("libp2p_identify_received", 0)) >= 1,
            timeout=6.0,
        ):
            print(
                f"FAIL: initial identify "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1

        before_hub = int(hub.metrics().get("libp2p_identify_received", 0))
        before_client = int(client.metrics().get("libp2p_identify_received", 0))
        before_sent = int(hub.metrics().get("libp2p_identify_sent", 0)) + int(
            client.metrics().get("libp2p_identify_sent", 0)
        )
        if not _wait(
            lambda: int(hub.metrics().get("libp2p_identify_received", 0)) > before_hub
            or int(client.metrics().get("libp2p_identify_received", 0)) > before_client
            or (
                int(hub.metrics().get("libp2p_identify_sent", 0))
                + int(client.metrics().get("libp2p_identify_sent", 0))
            )
            > before_sent,
            timeout=5.0,
        ):
            print(
                f"FAIL: no periodic re-identify "
                f"hub={hub.metrics()} client={client.metrics()}"
            )
            return 1

        cm = client.metrics()
        for key in (
            "libp2p_identify_error_timeout",
            "libp2p_identify_error_negotiation",
            "libp2p_identify_error_apply",
            "libp2p_identify_error_io",
        ):
            if key not in cm:
                print(f"FAIL: missing metric key {key}")
                return 1

        hm = hub.metrics()
        print(
            f"OK: interval_ms={hm.get('libp2p_identify_interval_ms')} "
            f"hub_recv={hm.get('libp2p_identify_received')} "
            f"client_recv={cm.get('libp2p_identify_received')} "
            f"hub_sent={hm.get('libp2p_identify_sent')} "
            f"client_sent={cm.get('libp2p_identify_sent')}"
        )

        cap = hub.capability_status()
        if not cap.get("identify_interval"):
            print(f"FAIL: capability identify_interval: {cap}")
            return 1
        if not cap.get("identify_fail_events"):
            print(f"FAIL: capability identify_fail_events: {cap}")
            return 1
        if int(cap.get("identify_interval_ms", 0)) != INTERVAL_MS:
            print(f"FAIL: capability interval {cap.get('identify_interval_ms')}")
            return 1
        if int(cap.get("phase", 0)) < 55:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass
        if prev is None:
            os.environ.pop("ABS_LIBP2P_IDENTIFY_INTERVAL_MS", None)
        else:
            os.environ["ABS_LIBP2P_IDENTIFY_INTERVAL_MS"] = prev

    print("OK: libp2p_rust_identify_interval_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; identify interval; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
