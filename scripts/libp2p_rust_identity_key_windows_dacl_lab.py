#!/usr/bin/env python3
"""ADR 0019 Slice CI — identity keystore Windows protected DACL.

Slice CH locked Unix mode 0o600; Windows still inherited the parent ACL
(Users/Everyone could read the Ed25519 key on a shared directory). Slice CI
sets a protected DACL on first-create: owner + SYSTEM + Administrators,
no Users/Everyone. Existing Windows ACLs are not silently rewritten.
Capability ``identity_key_windows_owner_dacl`` / strategy
``windows_owner_only_dacl`` / phase >= 86.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_key_windows_dacl_lab.py
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

# Match whole ACE principal names, not substrings of Administrators.
_FORBIDDEN = (
    "everyone:",
    "builtin\\users:",
    "nt authority\\authenticated users:",
    "authenticated users:",
)


def _icacls(path: Path) -> str:
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
        raise RuntimeError(f"icacls failed ({proc.returncode}): {body}")
    return body


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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-keydacl-") as td:
        key_path = Path(td) / "node.key"
        tmp = Path(str(key_path) + f".{os.getpid()}.tmp")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = node.capability_status()
            if cap.get("identity_key_mode_strategy") != want:
                print(
                    f"FAIL: capability strategy "
                    f"{cap.get('identity_key_mode_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 86:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            if os.name == "nt":
                if not cap.get("identity_key_windows_owner_dacl"):
                    print(f"FAIL: capability identity_key_windows_owner_dacl: {cap}")
                    return 1
            elif cap.get("identity_key_windows_owner_dacl"):
                print("FAIL: identity_key_windows_owner_dacl true on non-Windows")
                return 1
            if not key_path.is_file():
                print("FAIL: key dest missing after create")
                return 1
            if tmp.exists():
                print(f"FAIL: key tmp leftover: {tmp}")
                return 1
            if os.name == "nt":
                try:
                    acl = _icacls(key_path)
                except RuntimeError as exc:
                    print(f"FAIL: {exc}")
                    return 1
                low = acl.lower().replace("/", "\\")
                for needle in _FORBIDDEN:
                    if needle in low:
                        print(f"FAIL: forbidden ACE {needle!r} in icacls:\n{acl}")
                        return 1
                print("OK: windows owner DACL (no Users/Everyone)")
            else:
                print("OK: windows DACL N/A (unix_0600 Slice CH)")
        finally:
            try:
                node.close()
            except Exception:
                pass

    print("OK: libp2p_rust_identity_key_windows_dacl_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; Windows protected DACL owner+SYSTEM+Admin; "
        "existing ACLs not rewritten; not POSIX 0600; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
