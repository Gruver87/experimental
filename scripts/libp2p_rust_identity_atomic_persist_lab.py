#!/usr/bin/env python3
"""ADR 0019 Slice CF — identity keystore first-create via atomic replace.

Slice F wrote a new Ed25519 protobuf key with ``std::fs::write`` (truncate
in place). A crash mid-write could leave a half key. Slice CF creates the
file via tmp+fsync+replace (same CD MoveFileEx / POSIX rename). An
*existing* path is never overwritten: corrupt key refuses spawn (does not
mint a new PeerId). Capability ``identity_atomic_persist`` / phase >= 83.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_atomic_persist_lab.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-atomic-") as td:
        key_path = Path(td) / "node.key"
        tmp = Path(str(key_path) + ".tmp")
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if not cap.get("identity_atomic_persist"):
                print(f"FAIL: capability identity_atomic_persist: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 83:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
            if not pid:
                print("FAIL: empty peer_id")
                return 1
            if not key_path.is_file():
                print("FAIL: key dest missing after create")
                return 1
            if tmp.exists():
                print(f"FAIL: key tmp leftover: {tmp}")
                return 1
            if key_path.stat().st_size < 16:
                print("FAIL: key dest too small")
                return 1
        finally:
            a.close()

        b = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            if b.peer_id != pid:
                print(f"FAIL: PeerId changed across restart {pid} -> {b.peer_id}")
                return 1
            if tmp.exists():
                print("FAIL: tmp leftover after reload")
                return 1
        finally:
            b.close()

        garbage = Path(td) / "corrupt.key"
        garbage.write_bytes(b"not-a-protobuf-key")
        try:
            abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                key_path=str(garbage),
            )
            print("FAIL: corrupt key was accepted (must refuse, not mint)")
            return 1
        except Exception as exc:
            msg = str(exc).lower()
            if "decode" not in msg and "key" not in msg:
                print(f"FAIL: corrupt key error too vague: {exc}")
                return 1
        if garbage.read_bytes() != b"not-a-protobuf-key":
            print("FAIL: corrupt key file was overwritten")
            return 1
        print(f"OK: identity atomic persist peer_id={pid}")

    print("OK: libp2p_rust_identity_atomic_persist_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; identity keystore atomic create; "
        "corrupt existing key refuses; not POSIX inode-atomic on NTFS; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
