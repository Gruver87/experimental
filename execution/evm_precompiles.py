"""Ethereum precompile subset for eth_call (experimental R&D wave).

Addresses (20-byte, hex with/without 0x):
  0x02 — SHA256
  0x04 — IDENTITY (data copy)

Honesty: not full precompile set; ecrecover/modexp/bn254 remain Partial.
"""

from __future__ import annotations

from typing import Any, Optional

# Canonical 20-byte addresses
_SHA256 = "0000000000000000000000000000000000000002"
_IDENTITY = "0000000000000000000000000000000000000004"


def _norm_addr(addr: str) -> str:
    a = str(addr or "").strip().lower().replace("0x", "")
    if len(a) > 40:
        a = a[-40:]
    return a.zfill(40)


def try_precompile(contract_addr: str, calldata_hex: str = "") -> Optional[Any]:
    """Return EVMResult if ``contract_addr`` is a supported precompile, else None."""
    from execution.evm_adapter import EVMResult

    key = _norm_addr(contract_addr)
    try:
        data = bytes.fromhex(str(calldata_hex or "").replace("0x", ""))
    except ValueError:
        return EVMResult(success=False, error="invalid_calldata", gas_used=0)

    if key == _IDENTITY:
        # EIP: gas = 15 + 3 * ceil(len/32)
        words = (len(data) + 31) // 32
        gas = 15 + 3 * words
        return EVMResult(success=True, return_value=data, gas_used=gas)

    if key == _SHA256:
        try:
            from crypto import native

            digest_hex = native.sha256_hex(data)
            out = bytes.fromhex(digest_hex)
        except Exception:
            import hashlib

            out = hashlib.sha256(data).digest()
        # Yellow paper-ish: 60 + 12 * words
        words = (len(data) + 31) // 32
        gas = 60 + 12 * words
        return EVMResult(success=True, return_value=out, gas_used=gas)

    return None


def is_precompile(contract_addr: str) -> bool:
    return _norm_addr(contract_addr) in {_SHA256, _IDENTITY}
