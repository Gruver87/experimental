#!/usr/bin/env python3
"""ADR 0019 Slice AZ — wire RR failure taxonomy lab.

Ghost PeerId ``send_wire`` → ``wire_outbound_fail_dial``.
Capability ``wire_fail_events`` / phase >= 51.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_wire_fail_events_lab.py
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

    client = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, wire_timeout_secs=2
    )
    ghost = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        ghost_pid = ghost.peer_id
        ghost.close()

        frame = abs_native.libp2p_pack_wire("ping", b"slice-az")
        before_dial = int(client.metrics().get("libp2p_wire_outbound_fail_dial", 0))
        before_total = int(client.metrics().get("libp2p_wire_outbound_failure", 0))
        try:
            client.send_wire(ghost_pid, frame)
        except Exception as exc:
            print(f"  dial fail note: {exc}")

        if not _wait(
            lambda: int(client.metrics().get("libp2p_wire_outbound_fail_dial", 0))
            > before_dial
            and int(client.metrics().get("libp2p_wire_outbound_failure", 0))
            > before_total,
            timeout=4.0,
        ):
            print(f"FAIL: wire_outbound_fail_dial client={client.metrics()}")
            return 1

        cm = client.metrics()
        print(
            f"OK: outbound_fail_dial={cm.get('libp2p_wire_outbound_fail_dial')} "
            f"outbound_failure={cm.get('libp2p_wire_outbound_failure')}"
        )

        # Taxonomy keys must be present (inbound may stay zero in this lab).
        for key in (
            "libp2p_wire_outbound_fail_timeout",
            "libp2p_wire_outbound_fail_connection_closed",
            "libp2p_wire_outbound_fail_unsupported",
            "libp2p_wire_outbound_fail_io",
            "libp2p_wire_inbound_fail_timeout",
            "libp2p_wire_inbound_fail_connection_closed",
            "libp2p_wire_inbound_fail_unsupported",
            "libp2p_wire_inbound_fail_response_omission",
            "libp2p_wire_inbound_fail_io",
        ):
            if key not in cm:
                print(f"FAIL: missing metric key {key}")
                return 1

        cap = client.capability_status()
        if not cap.get("wire_fail_events"):
            print(f"FAIL: capability wire_fail_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 51:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            client.close()
        except Exception:
            pass

    print("OK: libp2p_rust_wire_fail_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; wire fail events; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
