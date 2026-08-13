#!/usr/bin/env python3
"""ADR 0019 Slice BT — shared advertised externals cap (operator + listen-derived).

Operator-advertised and listen-derived share one budget: sum ≤ max
(MAX 32; ``max_advertised_external`` may only lower it). Over-limit
``listen()`` / ``add_external_address`` / persist restore refuse.
Circuit ``/p2p-circuit`` is not counted. Capability
``advertised_externals_shared_max`` / phase >= 71.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_advertised_externals_shared_max_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OP1 = "/ip4/203.0.113.90/tcp/4090"
OP2 = "/ip4/203.0.113.91/tcp/4091"


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
    if hard != 32:
        print(f"FAIL: hard max constant {hard}")
        return 1

    node = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=2,
    )
    try:
        if not node.add_external_address(OP1):
            print("FAIL: first operator add False")
            return 1
        a1 = node.listen("/ip4/127.0.0.1/tcp/0")
        if not a1:
            print("FAIL: listen empty after one operator")
            return 1
        print(f"OK: mixed fill operator+listen {a1}")
        raised = False
        try:
            node.listen("/ip4/127.0.0.1/tcp/0")
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "at max" not in msg and "exceeds max" not in msg:
                print(f"FAIL: mixed listen error text: {exc}")
                return 1
            print(f"OK: mixed listen refuse: {exc}")
        if not raised:
            print("FAIL: second listen did not raise under shared cap")
            return 1
        raised = False
        try:
            node.add_external_address(OP2)
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "exceeds max" not in msg:
                print(f"FAIL: mixed add error text: {exc}")
                return 1
            print(f"OK: mixed add refuse: {exc}")
        if not raised:
            print("FAIL: second operator add did not raise under shared cap")
            return 1
        if OP2 in list(node.external_addrs()):
            print(f"FAIL: refused operator in book: {node.external_addrs()}")
            return 1
        m = node.metrics()
        used = int(m.get("libp2p_advertised_externals_used", 0))
        if used != 2:
            print(f"FAIL: used metric {used} metrics={m}")
            return 1
        if int(m.get("libp2p_listen_derived_externals", 0)) != 1:
            print(f"FAIL: listen_derived {m.get('libp2p_listen_derived_externals')}")
            return 1
        if int(m.get("libp2p_external_addr_limit_refused", 0)) < 2:
            print(f"FAIL: limit_refused {m.get('libp2p_external_addr_limit_refused')}")
            return 1
        cap = node.capability_status()
        if not cap.get("advertised_externals_shared_max"):
            print(f"FAIL: capability shared_max: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 71:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    node2 = abs_native.libp2p_node_new(
        enable_mdns=False,
        enable_reconnect=False,
        max_advertised_external=2,
    )
    try:
        a = node2.listen("/ip4/127.0.0.1/tcp/0")
        if not a:
            print("FAIL: node2 listen empty")
            return 1
        if not node2.add_external_address(OP1):
            print("FAIL: node2 operator add after listen False")
            return 1
        raised = False
        try:
            node2.add_external_address(OP2)
        except Exception as exc:
            raised = True
            print(f"OK: listen-then-add refuse: {exc}")
        if not raised:
            print("FAIL: listen-then-add did not refuse third slot")
            return 1
        print("OK: listen-then-operator shared cap")
    finally:
        try:
            node2.close()
        except Exception:
            pass

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-sharedmax-") as td:
        store = Path(td) / "external_addrs.json"
        store.write_text(
            json.dumps({"version": 1, "addrs": [OP1, OP2]}),
            encoding="utf-8",
        )
        node3 = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
            max_advertised_external=2,
        )
        try:
            used = int(node3.metrics().get("libp2p_advertised_externals_used", 0))
            if used != 2:
                print(f"FAIL: restore used {used}")
                return 1
            raised = False
            try:
                node3.listen("/ip4/127.0.0.1/tcp/0")
            except Exception as exc:
                raised = True
                print(f"OK: restore-then-listen refuse: {exc}")
            if not raised:
                print("FAIL: restore of 2 did not block listen")
                return 1
        finally:
            try:
                node3.close()
            except Exception:
                pass

    print("OK: libp2p_rust_advertised_externals_shared_max_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; shared advertised cap refuse; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
