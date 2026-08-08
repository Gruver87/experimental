#!/usr/bin/env python3
"""rust-libp2p dial-budget / backpressure soak lab (ADR 0019 Slice C).

Exercises max_dials=1 (outbound peers + inflight), then a short wire soak.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_soak_lab.py
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

    listener = abs_native.libp2p_node_new()
    dialer = abs_native.libp2p_node_new(1)  # Slice C: max 1 outbound
    extra = abs_native.libp2p_node_new()
    nodes = [listener, dialer, extra]
    try:
        listen_l = listener.listen("/ip4/127.0.0.1/tcp/0")[0]
        listen_e = extra.listen("/ip4/127.0.0.1/tcp/0")[0]

        remote = dialer.dial(listen_l)
        if remote != listener.peer_id:
            print(f"FAIL: first dial {remote=} want={listener.peer_id}")
            return 1

        # Budget full: second outbound must refuse
        refused = False
        try:
            dialer.dial(listen_e)
        except Exception as exc:
            if "dial_budget_exceeded" in str(exc):
                refused = True
            else:
                print(f"FAIL: unexpected second-dial error: {exc}")
                return 1
        if not refused:
            print("FAIL: second dial should hit dial_budget_exceeded")
            return 1

        m = dialer.metrics()
        if int(m.get("libp2p_dial_refused_budget", 0)) < 1:
            print(f"FAIL: refused metric not bumped: {m}")
            return 1
        if int(m.get("libp2p_outbound_peers", 0)) != 1:
            print(f"FAIL: expected 1 outbound peer: {m}")
            return 1

        # Short wire soak on the allowed outbound
        frames = 20
        for i in range(frames):
            frame = abs_native.libp2p_pack_wire("soak", f"#{i}".encode())
            ack = dialer.send_wire(listener.peer_id, frame)
            if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
                print(f"FAIL: soak ack #{i} {ack!r}")
                return 1

        for _ in range(100):
            inbox = listener.poll_inbox()
            if len(inbox) >= frames:
                break
            time.sleep(0.05)

        ml = listener.metrics()
        md = dialer.metrics()
        if int(md.get("libp2p_wire_sent", 0)) < frames:
            print(f"FAIL: wire_sent {md}")
            return 1
        if int(ml.get("libp2p_wire_recv", 0)) < frames:
            print(f"FAIL: wire_recv {ml}")
            return 1

        print("OK: libp2p_rust_soak_lab PASS")
        print(
            "  budget: max_dials=1, second dial refused, "
            f"refused_metric={md.get('libp2p_dial_refused_budget')}"
        )
        print(
            f"  dialer: outbound={md.get('libp2p_outbound_peers')} "
            f"wire_sent={md.get('libp2p_wire_sent')}"
        )
        print(f"  listener wire_recv: {ml.get('libp2p_wire_recv')}")
        print("  honesty: FEATURE_LIBP2P lab; not prod TCP+TLS mesh")
        return 0
    finally:
        for n in nodes:
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
