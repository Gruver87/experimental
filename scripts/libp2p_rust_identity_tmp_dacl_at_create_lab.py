#!/usr/bin/env python3
"""ADR 0019 Slice CL — identity tmp born restricted (DACL/0600 at create).

CI applied the Windows protected DACL *after* ``File::create`` + write.
The Ed25519 protobuf sat on disk under the inherited parent ACL (Users/
Everyone) until ``SetNamedSecurityInfo``. Slice CL creates the staging tmp
with the protected DACL on ``CreateFileW`` (Unix already uses ``0o600`` at
open). A leftover tmp is locked down and unlinked before CREATE_NEW.
Capability ``identity_key_tmp_restrict_at_create`` / phase >= 89.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_tmp_dacl_at_create_lab.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FORBIDDEN = (
    "everyone:",
    "builtin\\users:",
    "nt authority\\authenticated users:",
    "authenticated users:",
)


def _icacls_forbidden(path: Path) -> str | None:
    proc = subprocess.run(
        ["icacls", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    body = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return f"icacls failed ({proc.returncode})"
    low = body.lower()
    for token in _FORBIDDEN:
        if token in low:
            return token.rstrip(":")
    return None


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = (
        "windows_createfile_owner_dacl"
        if os.name == "nt"
        else "unix_0600_at_create"
    )
    mod_strategy = str(getattr(abs_native, "IDENTITY_KEY_TMP_RESTRICT_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-tmpdacl-") as td:
        key_path = Path(td) / "node.key"
        tmp = Path(str(key_path) + f".{os.getpid()}.tmp")
        tmp.write_bytes(b"stale-key-material")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = node.capability_status()
            if not cap.get("identity_key_tmp_restrict_at_create"):
                print(f"FAIL: capability identity_key_tmp_restrict_at_create: {cap}")
                return 1
            if cap.get("identity_key_tmp_restrict_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_key_tmp_restrict_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 89:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = node.peer_id
            if not key_path.is_file():
                print("FAIL: key dest missing after create")
                return 1
            if tmp.exists():
                print(f"FAIL: key tmp leftover: {tmp}")
                return 1
            if key_path.read_bytes() == b"stale-key-material":
                print("FAIL: dest is leftover tmp bytes")
                return 1
            if os.name == "nt":
                hit = _icacls_forbidden(key_path)
                if hit:
                    print(f"FAIL: dest ACL still grants {hit}")
                    return 1
        finally:
            node.close()

        b = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            if b.peer_id != pid:
                print(f"FAIL: PeerId changed across restart {pid} -> {b.peer_id}")
                return 1
        finally:
            b.close()
        print(f"OK: identity tmp restrict-at-create strategy={want} peer_id={pid}")

    print("OK: libp2p_rust_identity_tmp_dacl_at_create_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; identity tmp born restricted; "
        "leftover tmp locked+unlinked; existing dest ACLs not rewritten; "
        "not POSIX 0600 on Windows; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
