#!/usr/bin/env python3
"""ADR 0019 Slice CW — circuit must not occupy ExternalAddresses book.

rust-libp2p 0.45 Identify / Kad / Relay keep at most 20 confirmed externals
and silently evict the oldest past that. Circuit ``/p2p-circuit`` is outside
our unique charged cap, so ``swarm.add_external_address(circuit)`` after 20
charged unique addrs would evict a charged operator/listen addr. Fail-closed:
circuit never enters the crate book (operator add refuses; persist JSON with
circuit refuses spawn). Capability
``circuit_excluded_from_external_book`` / phase >= 100.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_circuit_excluded_from_external_book_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CIRCUIT = "/ip4/192.0.2.9/tcp/4009/p2p-circuit"
WANT = "never_add_external_address"
BOOK = 20


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    mod_strategy = str(
        getattr(abs_native, "CIRCUIT_EXCLUDED_FROM_EXTERNAL_BOOK_STRATEGY", "")
    )
    if mod_strategy != WANT:
        print(f"FAIL: module strategy {mod_strategy!r} != {WANT}")
        return 1

    book = int(getattr(abs_native, "LIBP2P_SWARM_EXTERNAL_ADDRESSES_MAX", 0) or 0)
    if book != BOOK:
        print(f"FAIL: libp2p ExternalAddresses book max {book}")
        return 1

    node = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        cap = node.capability_status()
        if not cap.get("circuit_excluded_from_external_book"):
            print(f"FAIL: capability circuit_excluded_from_external_book: {cap}")
            return 1
        if cap.get("circuit_excluded_from_external_book_strategy") != WANT:
            print(
                "FAIL: capability strategy "
                f"{cap.get('circuit_excluded_from_external_book_strategy')!r} != {WANT}"
            )
            return 1
        if int(cap.get("phase", 0)) < 100:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        raised = False
        try:
            node.add_external_address(CIRCUIT)
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "p2p-circuit" not in msg:
                print(f"FAIL: circuit add error text: {exc}")
                return 1
            print(f"OK: empty-book circuit refuse: {exc}")
        if not raised:
            print("FAIL: circuit add did not raise")
            return 1
        if CIRCUIT in list(node.external_addrs()):
            print(f"FAIL: circuit landed in book: {node.external_addrs()}")
            return 1

        charged = []
        for i in range(book):
            addr = f"/ip4/203.0.113.{i + 1}/tcp/{4200 + i}"
            fresh = node.add_external_address(addr)
            if not fresh:
                print(f"FAIL: add {i} not fresh: {addr}")
                return 1
            charged.append(addr)
        used = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used != book:
            print(f"FAIL: used {used} after filling book {book}")
            return 1
        print(f"OK: filled {book} charged externals used={used}")

        raised = False
        try:
            node.add_external_address(CIRCUIT)
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "p2p-circuit" not in msg:
                print(f"FAIL: full-book circuit add error text: {exc}")
                return 1
            if "exceeds max" in msg:
                print(f"FAIL: circuit charged the unique cap: {exc}")
                return 1
            print(f"OK: full-book circuit refuse: {exc}")
        if not raised:
            print("FAIL: full-book circuit add did not raise")
            return 1

        book_addrs = list(node.external_addrs())
        if CIRCUIT in book_addrs:
            print(f"FAIL: circuit in book after refuse: {book_addrs}")
            return 1
        missing = [a for a in charged if a not in book_addrs]
        if missing:
            print(f"FAIL: charged evicted after circuit refuse: {missing}")
            return 1
        if len(book_addrs) != book:
            print(f"FAIL: book len {len(book_addrs)} != {book}")
            return 1
        used2 = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used2 != book:
            print(f"FAIL: used changed after circuit refuse: {used2}")
            return 1

        overflow = "/ip4/203.0.113.250/tcp/4999"
        raised = False
        try:
            node.add_external_address(overflow)
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "exceeds max" not in msg:
                print(f"FAIL: 21st charged error text: {exc}")
                return 1
            print(f"OK: 21st charged refuse: {exc}")
        if not raised:
            print("FAIL: 21st charged add did not raise")
            return 1
        if overflow in list(node.external_addrs()):
            print(f"FAIL: overflow landed: {node.external_addrs()}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-circuit-book-") as td:
        store = Path(td) / "external_addrs.json"
        store.write_text(
            json.dumps({"version": 1, "addrs": [CIRCUIT]}),
            encoding="utf-8",
        )
        raised = False
        try:
            abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                external_addrs_path=str(store),
            )
        except Exception as exc:
            raised = True
            msg = str(exc)
            if "p2p-circuit" not in msg:
                print(f"FAIL: persist circuit load error text: {exc}")
                return 1
            print(f"OK: persist circuit spawn refuse: {exc}")
        if not raised:
            print("FAIL: persist JSON with circuit did not refuse spawn")
            return 1

    print("OK: libp2p_rust_circuit_excluded_from_external_book_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; circuit excluded from rust-libp2p "
        "ExternalAddresses book; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
