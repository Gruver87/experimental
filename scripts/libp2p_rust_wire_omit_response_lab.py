#!/usr/bin/env python3
"""ADR 0019 Slice BB — wire omit-response (ResponseOmission) lab.

With ``ABS_LIBP2P_WIRE_OMIT_RESPONSE=1`` on the hub, inbound RR drops the
response channel → ``wire_inbound_fail_response_omission``. Client sees
outbound timeout. Capability ``wire_omit_response`` / phase >= 53.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_wire_omit_response_lab.py
"""

from __future__ import annotations

import os
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

    prev = os.environ.get("ABS_LIBP2P_WIRE_OMIT_RESPONSE")
    os.environ["ABS_LIBP2P_WIRE_OMIT_RESPONSE"] = "1"
    hub = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, wire_timeout_secs=1
    )
    if prev is None:
        os.environ.pop("ABS_LIBP2P_WIRE_OMIT_RESPONSE", None)
    else:
        os.environ["ABS_LIBP2P_WIRE_OMIT_RESPONSE"] = prev

    client = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, wire_timeout_secs=1
    )
    try:
        if not hub.metrics().get("libp2p_wire_omit_response"):
            print(f"FAIL: omit not enabled on hub: {hub.metrics()}")
            return 1
        if client.metrics().get("libp2p_wire_omit_response"):
            print(f"FAIL: omit unexpectedly enabled on client: {client.metrics()}")
            return 1

        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addr)
        if not _wait(
            lambda: hub.peer_id in client.connected_peers()
            and client.peer_id in hub.connected_peers(),
            timeout=5.0,
        ):
            print("FAIL: peers not connected")
            return 1

        before_omit = int(
            hub.metrics().get("libp2p_wire_inbound_fail_response_omission", 0)
        )
        before_inbound = int(hub.metrics().get("libp2p_wire_inbound_failure", 0))
        before_timeout = int(
            client.metrics().get("libp2p_wire_outbound_fail_timeout", 0)
        )
        frame = abs_native.libp2p_pack_wire("ping", b"slice-bb")
        try:
            client.send_wire(hub.peer_id, frame)
        except Exception as exc:
            print(f"  send_wire note: {exc}")

        if not _wait(
            lambda: int(
                hub.metrics().get("libp2p_wire_inbound_fail_response_omission", 0)
            )
            > before_omit
            and int(hub.metrics().get("libp2p_wire_inbound_failure", 0))
            > before_inbound,
            timeout=4.0,
        ):
            print(f"FAIL: hub response_omission hub={hub.metrics()}")
            return 1

        if not _wait(
            lambda: int(
                client.metrics().get("libp2p_wire_outbound_fail_timeout", 0)
            )
            > before_timeout
            or int(client.metrics().get("libp2p_wire_outbound_failure", 0)) >= 1,
            timeout=4.0,
        ):
            print(f"FAIL: client outbound fail client={client.metrics()}")
            return 1

        hm = hub.metrics()
        cm = client.metrics()
        print(
            f"OK: hub omission={hm.get('libp2p_wire_inbound_fail_response_omission')} "
            f"inbound_failure={hm.get('libp2p_wire_inbound_failure')} "
            f"client_timeout={cm.get('libp2p_wire_outbound_fail_timeout')} "
            f"client_outbound_failure={cm.get('libp2p_wire_outbound_failure')}"
        )

        cap = hub.capability_status()
        if not cap.get("wire_omit_response"):
            print(f"FAIL: capability wire_omit_response: {cap}")
            return 1
        if not cap.get("wire_fail_events"):
            print(f"FAIL: capability wire_fail_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 53:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_wire_omit_response_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; wire omit-response; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
