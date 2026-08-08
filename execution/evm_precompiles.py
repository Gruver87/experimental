"""Ethereum precompile subset for eth_call (experimental R&D wave).

Addresses (20-byte, hex with/without 0x):
  0x01 — ECRECOVER
  0x02 — SHA256
  0x04 — IDENTITY (data copy)

Honesty: modexp/bn254/blake2f remain open.
"""

from __future__ import annotations

from typing import Any, Optional

# Canonical 20-byte addresses
_ECRECOVER = "0000000000000000000000000000000000000001"
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

    if key == _ECRECOVER:
        # Input: hash(32) || v(32) || r(32) || s(32). Gas fixed 3000.
        # Failure / bad sig → success with empty return (geth parity).
        gas = 3000
        empty = b"\x00" * 32
        if len(data) != 128:
            return EVMResult(success=True, return_value=empty, gas_used=gas)
        prehash = data[0:32]
        v_word = data[32:64]
        r = data[64:96]
        s = data[96:128]
        v = int.from_bytes(v_word, "big")
        # Yellow paper: v in {27,28}; also accept 0/1 as y-parity.
        if v in (0, 1):
            rec_id = v
        elif v in (27, 28):
            rec_id = v - 27
        else:
            return EVMResult(success=True, return_value=empty, gas_used=gas)
        try:
            from crypto import native

            addr = native.recover_eth_address_keccak(prehash, r, s, rec_id)
            addr_hex = str(addr).lower().replace("0x", "")
            if len(addr_hex) != 40:
                return EVMResult(success=True, return_value=empty, gas_used=gas)
            out = bytes.fromhex(addr_hex.rjust(64, "0"))
            return EVMResult(success=True, return_value=out, gas_used=gas)
        except Exception:
            return EVMResult(success=True, return_value=empty, gas_used=gas)

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
    return _norm_addr(contract_addr) in {_ECRECOVER, _SHA256, _IDENTITY}
