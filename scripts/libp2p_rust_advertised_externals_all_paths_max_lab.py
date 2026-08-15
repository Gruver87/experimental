#!/usr/bin/env python3
"""ADR 0019 Slice BU — observed/UPnP/rendezvous advertise share the BT cap.

``confirm_observed_addr`` (and UPnP / rendezvous ``add_external_address``)
must not grow advertised externals past the shared unique budget
(MAX 20; ``max_advertised_external`` may only lower it). Over-limit
confirm raises. Circuit ``/p2p-circuit`` is not counted.
Capability ``advertised_externals_all_paths_max`` / phase >= 72.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_advertised_externals_all_paths_max_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OP1 = "/ip4/203.0.113.92/tcp/4092"


def _charge_key(addr: str) -> str:
    """Slice CZ: confirm books the canonical key (strip trailing /p2p/<peer>)."""
    parts = addr.strip("/").split("/")
    if len(parts) >= 2 and parts[-2] == "p2p" and parts[-1] != "p2p-circuit":
        return "/" + "/".join(parts[:-2])
    return addr


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

    hard = int(getattr(abs_native, "MAX_ADVERTISED_EXTERNAL_ADDRS", 0) or 0)
    if hard != 20:
        print(f"FAIL: hard max constant {hard}")
        return 1

    hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    client = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=1,
    )
    try:
        hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
        client.listen("/ip4/127.0.0.1/tcp/0")
        client.dial(hub_addr)
        if not _wait(
            lambda: bool(str(client.metrics().get("libp2p_last_observed_addr", "")).strip()),
            timeout=6.0,
        ):
            print(f"FAIL: no observed addr client={client.metrics()}")
            return 1
        obs = str(client.metrics().get("libp2p_last_observed_addr", ""))
        print(f"OK: observed {obs}")
        n = client.clear_external_addrs()
        print(f"OK: cleared {n} externals; last_observed kept")
        used = int(client.metrics().get("libp2p_advertised_externals_used", -1))
        if used != 0:
            print(f"FAIL: used after clear {used}")
            return 1
        if not client.add_external_address(OP1):
            print("FAIL: operator add after clear False")
            return 1
        if int(client.metrics().get("libp2p_advertised_externals_used", 0)) != 1:
            print(f"FAIL: used after operator {client.metrics()}")
            return 1
        if obs == OP1:
            print("FAIL: observed unexpectedly equals operator TEST-NET addr")
            return 1
        raised = False
        try:
            client.confirm_observed_addr()
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "exceeds max" not in msg and "at max" not in msg:
                print(f"FAIL: confirm error text: {exc}")
                return 1
            print(f"OK: confirm refuse: {exc}")
        if not raised:
            print("FAIL: confirm_observed_addr did not raise at shared cap")
            return 1
        book = list(client.external_addrs())
        key = _charge_key(obs)
        if obs in book:
            print(f"FAIL: refused observed in book: {book}")
            return 1
        if key != OP1 and key in book:
            print(f"FAIL: refused observed charge key in book key={key!r} book={book}")
            return 1
        if OP1 not in book:
            print(f"FAIL: operator missing after refuse: {book}")
            return 1
        m = client.metrics()
        if int(m.get("libp2p_external_addr_limit_refused", 0)) < 1:
            print(f"FAIL: limit_refused {m.get('libp2p_external_addr_limit_refused')}")
            return 1
        if int(m.get("libp2p_aux_advertised_externals", 0)) != 0:
            print(f"FAIL: aux charged after refuse {m.get('libp2p_aux_advertised_externals')}")
            return 1
        cap = client.capability_status()
        if not cap.get("advertised_externals_all_paths_max"):
            print(f"FAIL: capability all_paths_max: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 72:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        for n in (client, hub):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_advertised_externals_all_paths_max_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; observed/UPnP/rendezvous share advertised cap; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
