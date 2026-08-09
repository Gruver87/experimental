#!/usr/bin/env python3
"""libp2p lab request/response smoke (ADR 0018 wave-5).

Usage:
  python scripts/libp2p_reqresp_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.libp2p_adapter import InProcessSwarm, RequestResponseService


def main() -> int:
    swarm = InProcessSwarm()
    a = swarm.spawn("n1", "/ip4/127.0.0.1/tcp/4201/p2p/n1")
    b = swarm.spawn("n2", "/ip4/127.0.0.1/tcp/4202/p2p/n2")
    a.dial(b.listen.to_string())

    rr_a = RequestResponseService(a)
    rr_b = RequestResponseService(b)
    rr_b.set_handler(lambda _peer, data: b"echo:" + data)

    out = rr_a.request("n2", b"ping")
    assert out == b"echo:ping"

    print("OK: libp2p_reqresp_lab PASS")
    print("  protocol: /abs/lab/req/1.0.0")
    print("  honesty: in-process only; not rust-libp2p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
