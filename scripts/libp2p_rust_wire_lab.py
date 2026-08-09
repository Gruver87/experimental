#!/usr/bin/env python3
"""rust-libp2p /abs/wire/1.0.0 request-response lab (ADR 0019 Slice B).

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_wire_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    proto = str(getattr(abs_native, "ABS_WIRE_PROTOCOL", "/abs/wire/1.0.0"))
    a = abs_native.libp2p_node_new()
    b = abs_native.libp2p_node_new()
    try:
        addrs_a = a.listen("/ip4/127.0.0.1/tcp/0")
        listen_a = addrs_a[0]
        remote = b.dial(listen_a)
        if remote != a.peer_id:
            print(f"FAIL: dial peer mismatch remote={remote} a={a.peer_id}")
            return 1

        for _ in range(50):
            if a.connected_peers() and b.connected_peers():
                break
            time.sleep(0.05)

        frame = abs_native.libp2p_pack_wire("ping", b"slice-b")
        ack = b.send_wire(a.peer_id, frame)
        if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
            print(f"FAIL: bad ack {ack!r}")
            return 1

        for _ in range(50):
            inbox = a.poll_inbox()
            if inbox:
                break
            time.sleep(0.05)
        else:
            print("FAIL: inbox empty on peer a")
            return 1

        peer_from, payload = inbox[0]
        if peer_from != b.peer_id:
            print(f"FAIL: inbox peer {peer_from} != {b.peer_id}")
            return 1
        msg_type, body = abs_native.libp2p_unpack_wire(payload)
        if msg_type != "ping" or bytes(body) != b"slice-b":
            print(f"FAIL: unpack msg_type={msg_type!r} body={bytes(body)!r}")
            return 1

        ma = a.metrics()
        mb = b.metrics()
        if int(mb.get("libp2p_wire_sent", 0)) < 1:
            print(f"FAIL: wire_sent metrics {mb}")
            return 1
        if int(ma.get("libp2p_wire_recv", 0)) < 1:
            print(f"FAIL: wire_recv metrics {ma}")
            return 1
        if int(mb.get("libp2p_dial_ok", 0)) < 1 or int(mb.get("libp2p_peers", 0)) < 1:
            print(f"FAIL: dial/peers metrics {mb}")
            return 1

        print("OK: libp2p_rust_wire_lab PASS")
        print(f"  protocol: {proto}")
        print(f"  peer_a: {a.peer_id}")
        print(f"  peer_b: {b.peer_id}")
        print(f"  metrics_a: peers={ma.get('libp2p_peers')} recv={ma.get('libp2p_wire_recv')}")
        print(f"  metrics_b: dial_ok={mb.get('libp2p_dial_ok')} sent={mb.get('libp2p_wire_sent')}")
        print("  honesty: FEATURE_LIBP2P lab; not prod TCP+TLS mesh")
        return 0
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
