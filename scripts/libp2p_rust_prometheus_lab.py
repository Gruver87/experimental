#!/usr/bin/env python3
"""ADR 0019 Slice Z — Prometheus export of libp2p_* metrics.

Proves adapter.prometheus_text / MetricsCollector.render_prometheus emit
``abs_libp2p_*`` series from a live rust dial, with default_mesh=0 honesty.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_prometheus_lab.py
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_METRIC_LINE = re.compile(
    r"^(?:# (?:HELP|TYPE) .+|[a-zA-Z_:][a-zA-Z0-9_:]*(?:\{[^}]*\})? "
    r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)$"
)


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    from network.transport.libp2p_adapter import Libp2pTransportAdapter
    from network.transport.types import PeerEndpoint
    from observability.metrics import MetricsCollector

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    ad = Libp2pTransportAdapter(enabled=True, enable_mdns=False)
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        port = int(hub_addr.rsplit("/", 1)[-1])
        handle = ad.connect(PeerEndpoint(host="127.0.0.1", port=port))
        if not handle.get("connected"):
            print(f"FAIL: dial not connected: {handle}")
            return 1
        time.sleep(0.2)

        text = ad.prometheus_text(node_id="lab-z")
        if not text.strip():
            print("FAIL: empty prometheus_text")
            return 1
        for line in text.strip().splitlines():
            if not _METRIC_LINE.match(line):
                print(f"FAIL: invalid prometheus line: {line!r}")
                return 1
        need = (
            "abs_libp2p_feature",
            "abs_libp2p_default_mesh",
            "abs_libp2p_dial_ok",
            "abs_libp2p_peers",
        )
        for needle in need:
            if needle not in text:
                print(f"FAIL: missing series {needle}")
                return 1
        if 'abs_libp2p_default_mesh{node_id="lab-z"} 0' not in text:
            print(f"FAIL: default_mesh must be 0:\n{text}")
            return 1
        snap = ad.status_snapshot()
        if int(snap.get("libp2p_dial_ok", 0)) < 1 and int(snap.get("libp2p_peers", 0)) < 1:
            print(f"FAIL: expected dial/peers: {snap}")
            return 1
        if not snap.get("prometheus_export"):
            print(f"FAIL: prometheus_export flag: {snap}")
            return 1
        # Sample must reflect live dial.
        if 'abs_libp2p_dial_ok{node_id="lab-z"} 0' in text and int(
            snap.get("libp2p_dial_ok", 0)
        ) >= 1:
            print(f"FAIL: prometheus dial_ok not updated:\n{text}")
            return 1
        print("OK: adapter prometheus_text")

        # /metrics path: MetricsCollector reads p2p_security["libp2p"]
        mc = MetricsCollector()
        full = mc.render_prometheus(
            node_id="lab-z",
            p2p_security={
                "active_bans": 0,
                "libp2p": dict(snap),
            },
        )
        if "abs_libp2p_feature" not in full:
            print("FAIL: MetricsCollector missing abs_libp2p_feature")
            return 1
        if "abs_libp2p_dial_ok" not in full:
            print("FAIL: MetricsCollector missing abs_libp2p_dial_ok")
            return 1
        print("OK: MetricsCollector /metrics hook")

        cap = ad.capability_status()
        if not cap.get("prometheus"):
            print(f"FAIL: capability prometheus: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 25:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(f"OK: phase={cap.get('phase')} prometheus capability")
    finally:
        try:
            ad.close()
        except Exception:
            pass
        try:
            hub.close()
        except Exception:
            pass

    print("OK: libp2p_rust_prometheus_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab Prometheus export; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
