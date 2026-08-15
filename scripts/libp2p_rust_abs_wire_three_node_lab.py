#!/usr/bin/env python3
"""3-node Absolute `/abs/wire` mesh (ADR 0008 codecs + admit).

Criterion C: real Absolute bytes between three rust-libp2p nodes.
v1/v2 ping around the triangle must admit; junk must HARD REFUSE.
Not a new ExternalAddresses/DACL/hard-gate slice. Not prod mesh cutover.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_abs_wire_three_node_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.errors import TransportValidationError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.libp2p_adapter.wire_bridge import (
    admit_abs_wire_frame,
    encode_abs_wire_frame,
)


def _wait_peers(node, n: int, timeout_s: float = 3.0) -> list[str]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        peers = list(node.connected_peers())
        if len(peers) >= n:
            return peers
        time.sleep(0.05)
    return list(node.connected_peers())


def _poll_one(node, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        inbox = node.poll_inbox()
        if inbox:
            return inbox[0]
        time.sleep(0.05)
    return None


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    nodes = [abs_native.libp2p_node_new(enable_mdns=False) for _ in range(3)]
    try:
        listens = [n.listen("/ip4/127.0.0.1/tcp/0")[0] for n in nodes]
        r10 = nodes[1].dial(listens[0])
        r20 = nodes[2].dial(listens[0])
        r21 = nodes[2].dial(listens[1])
        if r10 != nodes[0].peer_id or r20 != nodes[0].peer_id:
            print(f"FAIL: dial to n0 mismatch {r10=} {r20=}")
            return 1
        if r21 != nodes[1].peer_id:
            print(f"FAIL: dial to n1 mismatch {r21=}")
            return 1

        p0 = _wait_peers(nodes[0], 2)
        p1 = _wait_peers(nodes[1], 2)
        p2 = _wait_peers(nodes[2], 2)
        if len(p0) < 2 or len(p1) < 2 or len(p2) < 2:
            print(f"FAIL: incomplete mesh peers {p0=} {p1=} {p2=}")
            return 1

        hops = ((0, 1, "v1"), (1, 2, "v2"), (2, 0, "v1"))
        for src, dst, codec in hops:
            frame = encode_abs_wire_frame(
                "ping",
                {"lab": "abs-wire-3node", "src": src, "dst": dst, "codec": codec},
                codec=codec,
            )
            ack = nodes[src].send_wire(nodes[dst].peer_id, frame)
            if not (isinstance(ack, (bytes, bytearray)) and ack.startswith(b"OK:")):
                print(f"FAIL: wire ack {src}->{dst} codec={codec} {ack!r}")
                return 1
            got = _poll_one(nodes[dst])
            if got is None:
                print(f"FAIL: inbox empty {src}->{dst} codec={codec}")
                return 1
            peer_from, payload = got
            if peer_from != nodes[src].peer_id:
                print(f"FAIL: inbox peer {src}->{dst} got {peer_from}")
                return 1
            decision = admit_abs_wire_frame(
                bytes(payload), peer_id=nodes[src].peer_id
            )
            if not decision.ok or decision.frame is None:
                print(
                    f"FAIL: admit {src}->{dst} codec={codec} "
                    f"ok={decision.ok} reject={decision.reject}"
                )
                return 1
            if str(decision.frame.msg_type).lower() != "ping":
                print(f"FAIL: msg_type {decision.frame.msg_type!r}")
                return 1
            print(f"OK: abs_wire {src}->{dst} codec={codec} admit=ping")

        junk = b"%%%not-abs-wire%%%\n"
        ack_j = nodes[0].send_wire(nodes[1].peer_id, junk)
        if not (isinstance(ack_j, (bytes, bytearray)) and ack_j.startswith(b"OK:")):
            print(f"FAIL: junk transport ack {ack_j!r}")
            return 1
        got_j = _poll_one(nodes[1])
        if got_j is None:
            print("FAIL: junk did not arrive on the stream (cannot prove admit refuse)")
            return 1
        junk_dec = admit_abs_wire_frame(bytes(got_j[1]), peer_id=nodes[0].peer_id)
        if junk_dec.ok:
            print("FAIL: junk Absolute frame was admitted")
            return 1
        print(f"OK: junk admit HARD REFUSE reason={junk_dec.reject}")

        ad = Libp2pTransportAdapter(enabled=False)
        try:
            ad.send_abs_wire("peer-a", "", {"lab": True})
            print("FAIL: send_abs_wire empty type did not refuse")
            return 1
        except TransportValidationError as exc:
            print(f"OK: send_abs_wire prepare refuse code={exc.code}")

        print("OK: libp2p_rust_abs_wire_three_node_lab PASS")
        print("  honesty: FEATURE_LIBP2P lab; ADR 0008 over 3-node /abs/wire; not prod mesh")
        return 0
    finally:
        for n in nodes:
            try:
                n.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
