#!/usr/bin/env python3
"""libp2p dual-stack lab smoke (ADR 0018).

Verifies TCP+TLS remains the default and libp2p adapter only activates behind
FEATURE_LIBP2P. Phase-1 adapter is a capability stub (no real swarm).

Usage:
  python scripts/libp2p_lab_smoke.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.types import PeerEndpoint
from runtime.config import Config


def main() -> int:
    cfg = Config()
    # Industrial-style defaults must keep libp2p off.
    assert getattr(cfg, "feature_libp2p", False) is False

    off = Libp2pTransportAdapter.from_config(cfg)
    st = off.capability_status()
    assert st["available"] is False
    assert st["default_mesh"] is False
    try:
        off.connect(PeerEndpoint(host="127.0.0.1", port=4001))
        print("FAIL: dial should refuse when FEATURE_LIBP2P=false")
        return 1
    except TransportCapabilityError:
        pass

    on = Libp2pTransportAdapter(enabled=True)
    handle = on.connect(PeerEndpoint(host="127.0.0.1", port=4001, peer_id="lab-peer"))
    assert handle["transport"] == "libp2p"
    assert handle["phase"] == 1
    assert on.capability_status()["dial_count"] == 1

    print("OK: libp2p_lab_smoke PASS")
    print("  default transport: TCP+TLS (native) — libp2p opt-in only")
    print("  honesty: stub handle != prod mesh is libp2p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
