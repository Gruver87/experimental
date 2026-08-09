#!/usr/bin/env python3
"""ADR 0019 Slice AF — bandwidth accounting lab (bytes in/out).

Dial + wire exchange must move stream bytes through BandwidthSinks.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_bandwidth_lab.py
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

        payload = abs_native.libp2p_pack_wire("ping", b"bandwidth-af-" + (b"x" * 64))
        for _ in range(3):
            ack = client.send_wire(hub.peer_id, payload)
            if not (
                isinstance(ack, (bytes, bytearray)) and bytes(ack).startswith(b"OK:")
            ):
                print(f"FAIL: wire: {ack!r}")
                return 1

        def _moved() -> bool:
            cm = client.metrics()
            hm = hub.metrics()
            c_out = int(cm.get("libp2p_bytes_out", 0))
            c_in = int(cm.get("libp2p_bytes_in", 0))
            h_out = int(hm.get("libp2p_bytes_out", 0))
            h_in = int(hm.get("libp2p_bytes_in", 0))
            return (c_out + c_in) > 0 and (h_out + h_in) > 0

        if not _wait(_moved, timeout=5.0):
            print(
                f"FAIL: no bandwidth movement "
                f"client={client.metrics()} hub={hub.metrics()}"
            )
            return 1

        cm = client.metrics()
        hm = hub.metrics()
        if int(cm.get("libp2p_bytes_out", 0)) < 1:
            print(f"FAIL: client bytes_out expected >0: {cm}")
            return 1
        if int(hm.get("libp2p_bytes_in", 0)) < 1:
            print(f"FAIL: hub bytes_in expected >0: {hm}")
            return 1

        cap = client.capability_status()
        if not cap.get("bandwidth"):
            print(f"FAIL: capability bandwidth: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 31:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        print(
            f"OK: bandwidth "
            f"client out={cm.get('libp2p_bytes_out')} in={cm.get('libp2p_bytes_in')} "
            f"hub out={hm.get('libp2p_bytes_out')} in={hm.get('libp2p_bytes_in')}"
        )
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_bandwidth_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; bandwidth counters; TCP+TLS remains default mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
