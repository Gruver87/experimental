#!/usr/bin/env python3
"""ADR 0019 Slice BR — advertised externals hard max (refuse, no truncate).

``max_advertised_external`` (arg / ``ABS_LIBP2P_MAX_ADVERTISED_EXTERNAL_ADDRS``)
must be 1..=MAX_ADVERTISED_EXTERNAL_ADDRS (20). Over-limit add raises.
Oversized JSON on restore refuses spawn. Capability ``external_addrs_max``
/ phase >= 69.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_external_addrs_max_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

A1 = "/ip4/203.0.113.70/tcp/4070"
A2 = "/ip4/203.0.113.71/tcp/4071"
A3 = "/ip4/203.0.113.72/tcp/4072"


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

    raised = False
    try:
        abs_native.libp2p_node_new(
            enable_mdns=False, enable_reconnect=False, max_advertised_external=0
        )
    except Exception as exc:
        raised = True
        print(f"OK: zero cap refuse: {exc}")
    if not raised:
        print("FAIL: max=0 did not raise")
        return 1

    raised = False
    try:
        abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            max_advertised_external=hard + 1,
        )
    except Exception as exc:
        raised = True
        print(f"OK: over-hard cap refuse: {exc}")
    if not raised:
        print("FAIL: max>hard did not raise")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-extmax-") as td:
        store = Path(td) / "external_addrs.json"
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
            max_advertised_external=2,
        )
        try:
            if not node.add_external_address(A1):
                print("FAIL: first add False")
                return 1
            if not node.add_external_address(A2):
                print("FAIL: second add False")
                return 1
            raised = False
            try:
                node.add_external_address(A3)
            except Exception as exc:
                raised = True
                msg = str(exc)
                if "exceeds max" not in msg:
                    print(f"FAIL: third add error text: {exc}")
                    return 1
                print(f"OK: third add refuse: {exc}")
            if not raised:
                print("FAIL: third add did not raise")
                return 1
            book = list(node.external_addrs())
            if A3 in book:
                print(f"FAIL: over-limit addr in book: {book}")
                return 1
            if A1 not in book or A2 not in book:
                print(f"FAIL: cap-2 book missing advertised: {book}")
                return 1
            m = node.metrics()
            if int(m.get("libp2p_external_addr_limit_refused", 0)) < 1:
                print(f"FAIL: limit_refused counter: {m}")
                return 1
            if int(m.get("libp2p_max_advertised_external", 0)) != 2:
                print(f"FAIL: max metric: {m}")
                return 1
            disk = json.loads(store.read_text(encoding="utf-8"))
            persisted = list(disk.get("addrs") or [])
            if A3 in persisted or len(persisted) != 2:
                print(f"FAIL: disk not refuse-closed: {disk}")
                return 1
            cap = node.capability_status()
            if not cap.get("external_addrs_max"):
                print(f"FAIL: capability max: {cap}")
                return 1
            if int(cap.get("max_advertised_external", 0)) != 2:
                print(f"FAIL: cap max {cap.get('max_advertised_external')}")
                return 1
            if int(cap.get("phase", 0)) < 69:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            try:
                node.close()
            except Exception:
                pass

        oversized = Path(td) / "too_many.json"
        oversized.write_text(
            json.dumps({"version": 1, "addrs": [A1, A2, A3]}),
            encoding="utf-8",
        )
        raised = False
        try:
            abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                external_addrs_path=str(oversized),
                max_advertised_external=2,
            )
        except Exception as exc:
            raised = True
            print(f"OK: restore over max refuse: {exc}")
        if not raised:
            print("FAIL: oversized JSON did not refuse spawn")
            return 1

    print("OK: libp2p_rust_external_addrs_max_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; advertised externals hard max refuse; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
