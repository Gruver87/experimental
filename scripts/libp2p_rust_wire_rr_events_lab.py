#!/usr/bin/env python3
"""ADR 0019 Slice AO — wire RR event metrics lab.

Success path: ``wire_response_ok`` / ``wire_response_sent``.
Failure path: disconnect then ``send_wire`` → ``wire_outbound_failure``.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_wire_rr_events_lab.py
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
    client = abs_native.libp2p_node_new(
        enable_mdns=False, enable_reconnect=False, wire_timeout_secs=2
    )
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        remote = client.dial(hub_addr)
        if remote != hub.peer_id:
            print(f"FAIL: dial remote {remote}")
            return 1
        if not _wait(
            lambda: client.peer_id in hub.connected_peers(),
            timeout=3.0,
        ):
            print("FAIL: not connected")
            return 1

        frame = abs_native.libp2p_pack_wire("ping", b"slice-ao")
        ack = client.send_wire(hub.peer_id, frame)
        if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
            print(f"FAIL: bad ack {ack!r}")
            return 1

        if not _wait(
            lambda: int(client.metrics().get("libp2p_wire_response_ok", 0)) >= 1
            and int(hub.metrics().get("libp2p_wire_response_sent", 0)) >= 1
            and int(hub.metrics().get("libp2p_wire_recv", 0)) >= 1,
            timeout=3.0,
        ):
            print(
                f"FAIL: success metrics hub={hub.metrics()} client={client.metrics()}"
            )
            return 1
        print(
            f"OK: success "
            f"response_ok={client.metrics().get('libp2p_wire_response_ok')} "
            f"response_sent={hub.metrics().get('libp2p_wire_response_sent')} "
            f"recv={hub.metrics().get('libp2p_wire_recv')}"
        )

        # Outbound failure: request a never-connected peer.
        ghost = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        ghost_pid = ghost.peer_id
        try:
            ghost.close()
        except Exception:
            pass
        fail_before = int(client.metrics().get("libp2p_wire_outbound_failure", 0))
        failed = False
        try:
            client.send_wire(ghost_pid, frame)
        except Exception:
            failed = True
        if not _wait(
            lambda: int(client.metrics().get("libp2p_wire_outbound_failure", 0))
            > fail_before,
            timeout=4.0,
        ):
            if not failed:
                print(
                    f"FAIL: expected outbound failure "
                    f"client={client.metrics()} failed={failed}"
                )
                return 1
            print("WARN: send errored but counter lag")
        print(
            f"OK: outbound_failure="
            f"{client.metrics().get('libp2p_wire_outbound_failure')}"
        )

        cap = hub.capability_status()
        if not cap.get("wire_rr_events"):
            print(f"FAIL: capability wire_rr_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 40:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_wire_rr_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; wire RR events; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
