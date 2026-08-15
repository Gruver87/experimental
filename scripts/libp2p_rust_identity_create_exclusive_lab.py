#!/usr/bin/env python3
"""ADR 0019 Slice CK — identity first-create exclusive dest (no clobber).

CF used tmp+fsync+replace. Windows ``MoveFileExW(REPLACE_EXISTING)`` and POSIX
``rename`` still overwrite dest if it appears after ``exists()`` (two processes
both saw missing). A shared ``dest.tmp`` staging file can also land process A
bytes from process B's overwrite. Slice CK lands identity via exclusive
replace (Windows MoveFileEx without REPLACE_EXISTING; POSIX ``link(tmp, dest)``)
and per-process staging ``dest.{pid}.tmp`` (Slice CU: ``dest.{pid}.{tid}.tmp``).
Dest bytes are never clobbered.
JSON persist still uses replace (CD). Capability ``identity_create_exclusive``
/ phase >= 88.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_create_exclusive_lab.py
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
        "windows_movefileex_noreplace"
        if os.name == "nt"
        else "posix_hardlink_exclusive"
    )
    mod_strategy = str(getattr(abs_native, "IDENTITY_CREATE_EXCLUSIVE_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-excl-") as td:
        key_path = Path(td) / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if not cap.get("identity_create_exclusive"):
                print(f"FAIL: capability identity_create_exclusive: {cap}")
                return 1
            if cap.get("identity_create_exclusive_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_create_exclusive_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 88:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
            if not pid:
                print("FAIL: empty peer_id")
                return 1
            if not key_path.is_file():
                print("FAIL: key dest missing after create")
                return 1
            leftovers_create = sorted(key_path.parent.glob(key_path.name + ".*.tmp"))
            if leftovers_create:
                print(f"FAIL: key tmp leftover: {leftovers_create}")
                return 1
            first_bytes = key_path.read_bytes()
            if len(first_bytes) < 16:
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
        finally:
            b.close()
        if key_path.read_bytes() != first_bytes:
            print("FAIL: dest bytes changed on reload")
            return 1

        keep = Path(td) / "keep.key"
        keep.write_bytes(b"keep-me-identity")
        try:
            abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                key_path=str(keep),
            )
            print("FAIL: existing dest was accepted (must refuse, not clobber)")
            return 1
        except Exception as exc:
            msg = str(exc).lower()
            if "decode" not in msg and "key" not in msg:
                print(f"FAIL: existing dest error too vague: {exc}")
                return 1
        if keep.read_bytes() != b"keep-me-identity":
            print("FAIL: existing dest was overwritten")
            return 1

        race_key = Path(td) / "race.key"
        env = os.environ.copy()
        pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT)] + ([pp] if pp else []))
        code = (
            "import sys\n"
            "import abs_native\n"
            "p = sys.argv[1]\n"
            "try:\n"
            "    n = abs_native.libp2p_node_new("
            "enable_mdns=False, enable_reconnect=False, key_path=p)\n"
            "    print('OK', n.peer_id)\n"
            "    n.close()\n"
            "except Exception as e:\n"
            "    print('ERR', e)\n"
            "    raise SystemExit(2)\n"
        )
        procs = [
            subprocess.Popen(
                [sys.executable, "-c", code, str(race_key)],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            for _ in range(2)
        ]
        results: list[tuple[int, str]] = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            results.append((p.returncode, (out or "") + (err or "")))

        oks: list[str] = []
        errs: list[str] = []
        for rc, text in results:
            line = next(
                (ln.strip() for ln in text.splitlines() if ln.startswith("OK ")),
                "",
            )
            if rc == 0 and line.startswith("OK "):
                oks.append(line[3:].strip())
            else:
                errs.append(text)

        if len(oks) == 2:
            if oks[0] != oks[1]:
                print(f"FAIL: raced first-create minted two PeerIds: {oks}")
                return 1
        elif len(oks) == 1:
            # Exclusive refuse (or a lock on dest) — dest must still be the winner.
            pass
        else:
            print(f"FAIL: both first-creates failed: {results}")
            return 1

        winner = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(race_key),
        )
        try:
            if oks and winner.peer_id not in oks:
                print(
                    f"FAIL: reload PeerId {winner.peer_id} not in race winners {oks}"
                )
                return 1
        finally:
            winner.close()
        leftovers = sorted(Path(td).glob("*.tmp"))
        if leftovers:
            print(f"FAIL: tmp leftover after race: {leftovers}")
            return 1
        print(f"OK: identity exclusive create peer_id={pid} race_ok={len(oks)}")

    print("OK: libp2p_rust_identity_create_exclusive_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; exclusive identity first-create; "
        "existing dest not clobbered; JSON persist still replaces; "
        "not POSIX inode-atomic on NTFS; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
