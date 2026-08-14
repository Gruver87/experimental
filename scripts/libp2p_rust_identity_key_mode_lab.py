#!/usr/bin/env python3
"""ADR 0019 Slice CH — identity keystore Unix mode 0o600.

``File::create`` first-create was typically 0o644 (umask 022): group/other
could read the Ed25519 private key. Slice CH writes the key tmp with Unix
mode 0o600 before replace. An *existing* key with group/other bits refuses
spawn (no silent chmod). Windows DACL is Slice CI (not POSIX 0600).
Capability ``identity_key_mode_restrict`` / phase >= 85.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_key_mode_lab.py
"""

from __future__ import annotations

import os
import stat
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

    want = "unix_0600" if os.name == "posix" else "windows_owner_only_dacl"
    mod_strategy = str(getattr(abs_native, "IDENTITY_KEY_MODE_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1
    if int(getattr(abs_native, "IDENTITY_KEY_UNIX_MODE", 0)) != 0o600:
        print("FAIL: IDENTITY_KEY_UNIX_MODE != 0o600")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-keymode-") as td:
        key_path = Path(td) / "node.key"
        tmp = Path(str(key_path) + f".{os.getpid()}.tmp")
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if not cap.get("identity_key_mode_restrict"):
                print(f"FAIL: capability identity_key_mode_restrict: {cap}")
                return 1
            if cap.get("identity_key_mode_strategy") != want:
                print(
                    f"FAIL: capability strategy "
                    f"{cap.get('identity_key_mode_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 85:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
            if not key_path.is_file():
                print("FAIL: key dest missing after create")
                return 1
            if tmp.exists():
                print(f"FAIL: key tmp leftover: {tmp}")
                return 1
            if os.name == "posix":
                mode = stat.S_IMODE(key_path.stat().st_mode)
                if mode != 0o600:
                    print(f"FAIL: first-create mode {oct(mode)} != 0o600")
                    return 1
        finally:
            a.close()

        if os.name == "posix":
            key_path.chmod(0o644)
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: world-readable key was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if "mode" not in msg and "group/other" not in msg:
                    print(f"FAIL: world-readable error too vague: {exc}")
                    return 1
            key_path.chmod(0o600)
            b = abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                key_path=str(key_path),
            )
            try:
                if b.peer_id != pid:
                    print(f"FAIL: PeerId changed after chmod restore {pid} -> {b.peer_id}")
                    return 1
            finally:
                b.close()
            print(f"OK: identity key mode 0600 peer_id={pid}")
        else:
            print(f"OK: identity key mode windows_owner_only_dacl peer_id={pid}")

    print("OK: libp2p_rust_identity_key_mode_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; Unix 0600 + refuse world-readable; "
        "Windows DACL is Slice CI (this lab checks strategy); TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
