#!/usr/bin/env python3
"""ADR 0019 Slice AY — ping Failure taxonomy lab.

Forces ``ping_fail_timeout`` via ``ABS_LIBP2P_PING_TIMEOUT_MS=0``
(``Duration::ZERO`` → immediate timeout) and a short interval.
Capability ``ping_fail_events`` / phase >= 50.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_ping_fail_events_lab.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 12.0, step: float = 0.05) -> bool:
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

    prev_timeout = os.environ.get("ABS_LIBP2P_PING_TIMEOUT_MS")
    prev_interval = os.environ.get("ABS_LIBP2P_PING_INTERVAL_MS")
    os.environ["ABS_LIBP2P_PING_TIMEOUT_MS"] = "0"
    os.environ["ABS_LIBP2P_PING_INTERVAL_MS"] = "50"

    a = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    b = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        # Keep the session up while timeouts accumulate.
        a.set_ping_unhealthy_policy(False, 8, 0)
        b.set_ping_unhealthy_policy(False, 8, 0)

        am = a.metrics()
        if int(am.get("libp2p_ping_timeout_ms", -1)) != 0:
            print(f"FAIL: ping_timeout_ms not 0: {am.get('libp2p_ping_timeout_ms')}")
            return 1
        if int(am.get("libp2p_ping_interval_ms", 0)) != 50:
            print(
                f"FAIL: ping_interval_ms not 50: {am.get('libp2p_ping_interval_ms')}"
            )
            return 1

        a_addr = a.listen("/ip4/127.0.0.1/tcp/0")[0]
        b.dial(a_addr)
        if not _wait(
            lambda: a.peer_id in b.connected_peers()
            and b.peer_id in a.connected_peers(),
            timeout=5.0,
        ):
            print("FAIL: peers not connected")
            return 1

        before = int(b.metrics().get("libp2p_ping_fail_timeout", 0))
        if not _wait(
            lambda: int(b.metrics().get("libp2p_ping_fail_timeout", 0)) > before
            or int(a.metrics().get("libp2p_ping_fail_timeout", 0)) > 0,
            timeout=10.0,
        ):
            print(
                f"FAIL: no ping_fail_timeout "
                f"a={a.metrics()} b={b.metrics()}"
            )
            return 1

        bm = b.metrics()
        am = a.metrics()
        total_timeout = int(bm.get("libp2p_ping_fail_timeout", 0)) + int(
            am.get("libp2p_ping_fail_timeout", 0)
        )
        print(
            f"OK: ping_fail_timeout total={total_timeout} "
            f"a={am.get('libp2p_ping_fail_timeout')} "
            f"b={bm.get('libp2p_ping_fail_timeout')} "
            f"ping_fail_a={am.get('libp2p_ping_fail')} "
            f"ping_fail_b={bm.get('libp2p_ping_fail')}"
        )

        cap = b.capability_status()
        if not cap.get("ping_fail_events"):
            print(f"FAIL: capability ping_fail_events: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 50:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass
        if prev_timeout is None:
            os.environ.pop("ABS_LIBP2P_PING_TIMEOUT_MS", None)
        else:
            os.environ["ABS_LIBP2P_PING_TIMEOUT_MS"] = prev_timeout
        if prev_interval is None:
            os.environ.pop("ABS_LIBP2P_PING_INTERVAL_MS", None)
        else:
            os.environ["ABS_LIBP2P_PING_INTERVAL_MS"] = prev_interval

    print("OK: libp2p_rust_ping_fail_events_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; ping fail events; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
