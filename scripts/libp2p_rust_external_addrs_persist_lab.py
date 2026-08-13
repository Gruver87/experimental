#!/usr/bin/env python3
"""ADR 0019 Slice BP — persistent advertised external addrs lab.

Operator ``add_external_address`` writes JSON at ``external_addrs_path``.
A new node with the same path restores those addrs (loaded, not confirmed).
Listen-derived addrs are not persisted. Corrupt JSON / missing ``addrs``
fail-closed. Capability ``external_addrs_persist`` / phase >= 67.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_external_addrs_persist_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADVERTISED = "/ip4/203.0.113.50/tcp/4011"


def _wait(pred, timeout: float = 5.0, step: float = 0.05) -> bool:
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-extaddrs-") as td:
        store = Path(td) / "external_addrs.json"
        missing = Path(td) / "missing.json"
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            addrs = node.listen("/ip4/127.0.0.1/tcp/0")
            if not addrs:
                print("FAIL: empty listen")
                return 1
            listen = addrs[0]
            if not _wait(lambda: listen in node.external_addrs(), timeout=4.0):
                print(f"FAIL: listen not external: {node.external_addrs()}")
                return 1

            fresh = node.add_external_address(ADVERTISED)
            if not fresh:
                print("FAIL: first advertised add returned False")
                return 1
            if ADVERTISED not in node.external_addrs():
                print(f"FAIL: advertised not in book: {node.external_addrs()}")
                return 1

            if not store.is_file():
                print("FAIL: persist file missing")
                return 1
            disk = json.loads(store.read_text(encoding="utf-8"))
            persisted = list(disk.get("addrs") or [])
            if ADVERTISED not in persisted:
                print(f"FAIL: disk missing advertised: {disk}")
                return 1
            if listen in persisted:
                print(f"FAIL: listen-derived persisted: {disk}")
                return 1
            m = node.metrics()
            if int(m.get("libp2p_external_addr_persisted", 0)) < 1:
                print(f"FAIL: persisted counter: {m}")
                return 1
            cap = node.capability_status()
            if not cap.get("external_addrs_persist"):
                print(f"FAIL: capability persist: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 67:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            print(f"OK: persisted advertised={persisted}")
        finally:
            try:
                node.close()
            except Exception:
                pass

        node2 = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            if not _wait(lambda: ADVERTISED in node2.external_addrs(), timeout=5.0):
                print(f"FAIL: restore book: {node2.external_addrs()}")
                return 1
            m2 = node2.metrics()
            if int(m2.get("libp2p_external_addr_loaded", 0)) < 1:
                print(f"FAIL: loaded counter: {m2}")
                return 1
            if int(m2.get("libp2p_external_addr_confirmed", 0)) != 0:
                print(f"FAIL: restore bumped confirmed: {m2}")
                return 1
            print(
                f"OK: restored loaded={m2.get('libp2p_external_addr_loaded')} "
                f"confirmed={m2.get('libp2p_external_addr_confirmed')}"
            )
        finally:
            try:
                node2.close()
            except Exception:
                pass

        empty = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(missing),
        )
        try:
            if missing.is_file():
                print("FAIL: missing path should not create empty file on start")
                return 1
            print("OK: missing file -> empty advertised set")
        finally:
            try:
                empty.close()
            except Exception:
                pass

        bad = Path(td) / "corrupt.json"
        bad.write_text("{nope", encoding="utf-8")
        raised = False
        try:
            abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                external_addrs_path=str(bad),
            )
        except Exception as exc:
            raised = True
            print(f"OK: corrupt JSON fail-closed: {exc}")
        if not raised:
            print("FAIL: corrupt JSON did not raise")
            return 1

        missing_arr = Path(td) / "no_addrs.json"
        missing_arr.write_text('{"version":1}', encoding="utf-8")
        raised2 = False
        try:
            abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                external_addrs_path=str(missing_arr),
            )
        except Exception as exc:
            raised2 = True
            print(f"OK: missing addrs array fail-closed: {exc}")
        if not raised2:
            print("FAIL: missing addrs array did not raise")
            return 1

    print("OK: libp2p_rust_external_addrs_persist_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; persist advertised externals; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
