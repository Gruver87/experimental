#!/usr/bin/env python3
"""Smoke all wired EVM precompiles 0x01-0x09 (experimental wave-8).

Usage:
  python scripts/evm_precompile_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.evm_precompiles import try_precompile


def _modexp_calldata(base: bytes, exp: bytes, mod: bytes) -> str:
    def _len(n: int) -> bytes:
        return n.to_bytes(32, "big")

    return (_len(len(base)) + _len(len(exp)) + _len(len(mod)) + base + exp + mod).hex()


def main() -> int:
    checks: list[tuple[str, bool]] = []

    # 0x04 identity
    r = try_precompile("0x04", b"hi".hex())
    checks.append(("0x04 identity", bool(r and r.success and r.return_value == b"hi")))

    # 0x02 sha256
    import hashlib

    r = try_precompile("0x02", b"abc".hex())
    checks.append(
        ("0x02 sha256", bool(r and r.success and r.return_value == hashlib.sha256(b"abc").digest()))
    )

    # 0x03 ripemd160
    r = try_precompile("0x03", b"abc".hex())
    digest = hashlib.new("ripemd160", b"abc").digest().rjust(32, b"\x00")
    checks.append(("0x03 ripemd160", bool(r and r.success and r.return_value == digest)))

    # 0x05 modexp 3^5 mod 7 = 5
    r = try_precompile("0x05", _modexp_calldata(b"\x03", b"\x05", b"\x07"))
    checks.append(("0x05 modexp", bool(r and r.success and r.return_value == b"\x05")))

    # 0x01 ecrecover — soft: empty on bad input still success
    r = try_precompile("0x01", (b"\x00" * 128).hex())
    checks.append(("0x01 ecrecover empty-sig", bool(r and r.success and len(r.return_value) == 32)))

    # 0x09 blake2f vector5 (partial — only if length ok)
    blake_in = bytes.fromhex(
        "0000000c"
        "48c9bdf267e6096a3ba7ca8485ae67bb2bf894fe72f36e3cf1361d5f3af54fa5"
        "d182e6ad7f520e511f6c3e2b8c68059b6bbd41fbabd9831f79217e1319cde05b"
        "6162630000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "0000000000000000000000000000000000000000000000000000000000000000"
        "0300000000000000"
        "0000000000000000"
        "01"
    )
    r = try_precompile("0x09", blake_in.hex())
    checks.append(("0x09 blake2f", bool(r and r.success and r.gas_used == 12)))

    # 0x06-0x08 bn254 if py_ecc present
    try:
        import importlib.util

        if importlib.util.find_spec("py_ecc") is not None:
            from py_ecc.bn128 import G1  # type: ignore

            g = int(G1[0]).to_bytes(32, "big") + int(G1[1]).to_bytes(32, "big")
            r = try_precompile("0x06", (g + g).hex())
            checks.append(("0x06 ecAdd", bool(r and r.success)))
            r = try_precompile("0x07", (g + (2).to_bytes(32, "big")).hex())
            checks.append(("0x07 ecMul", bool(r and r.success)))
            r = try_precompile("0x08", "")
            checks.append(("0x08 pairing empty", bool(r and r.success and r.return_value[-1:] == b"\x01")))
        else:
            checks.append(("0x06-0x08 bn254", False))
            print("SKIP: py_ecc not installed (bn254)")
    except Exception as exc:
        checks.append(("0x06-0x08 bn254", False))
        print(f"SKIP/FAIL bn254: {exc}")

    print("EVM precompile lab wave-8")
    bad = 0
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            bad += 1
    if bad:
        print(f"FAIL: {bad}/{len(checks)} precompile checks")
        return 1
    print(f"OK: evm_precompile_lab PASS ({len(checks)} checks)")
    print("  honesty: eth_call subset; not full Ethereum client")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
