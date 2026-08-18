"""Ethereum precompile subset for eth_call (experimental R&D wave).

Addresses (20-byte, hex with/without 0x):
  0x01 — ECRECOVER
  0x02 — SHA256
  0x03 — RIPEMD160
  0x04 — IDENTITY (data copy)
  0x05 — MODEXP (EIP-198 + EIP-2565 gas)
  0x06 — BN254 ECADD
  0x07 — BN254 ECMUL
  0x08 — BN254 ECPAIRING
  0x09 — BLAKE2F (EIP-152)

Honesty: requires optional ``py_ecc`` for 0x06–0x08. Not a full Ethereum client.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

# Canonical 20-byte addresses
_ECRECOVER = "0000000000000000000000000000000000000001"
_SHA256 = "0000000000000000000000000000000000000002"
_RIPEMD160 = "0000000000000000000000000000000000000003"
_IDENTITY = "0000000000000000000000000000000000000004"
_MODEXP = "0000000000000000000000000000000000000005"
_ECADD = "0000000000000000000000000000000000000006"
_ECMUL = "0000000000000000000000000000000000000007"
_ECPAIRING = "0000000000000000000000000000000000000008"
_BLAKE2F = "0000000000000000000000000000000000000009"

# Lab/DoS bound (bytes) for base/exp/mod payloads
_MODEXP_MAX_LEN = 1024


def _norm_addr(addr: str) -> str:
    a = str(addr or "").strip().lower().replace("0x", "")
    if len(a) > 40:
        a = a[-40:]
    return a.zfill(40)


def _modexp_gas(base_len: int, exp_len: int, mod_len: int, exp_head: int) -> int:
    """EIP-2565 gas (Berlin+)."""
    words = math.ceil(max(base_len, mod_len) / 8)
    multiplication_complexity = words * words
    if exp_len <= 32 and exp_head == 0:
        iteration_count = 0
    elif exp_len <= 32:
        iteration_count = max(exp_head.bit_length() - 1, 0)
    else:
        # First 32 bytes of exponent as integer (big-endian head).
        head = exp_head & ((1 << 256) - 1)
        iteration_count = (8 * (exp_len - 32)) + max(head.bit_length() - 1, 0)
    iteration_count = max(iteration_count, 1)
    return max(200, math.floor(multiplication_complexity * iteration_count / 3))


def _parse_modexp(data: bytes) -> Optional[Tuple[bytes, bytes, bytes, int]]:
    """Return (base, exp, mod, gas) or None if lengths invalid / over cap."""
    if len(data) < 96:
        # Geth pads short input with zeros for length fields.
        data = data + b"\x00" * (96 - len(data))
    base_len = int.from_bytes(data[0:32], "big")
    exp_len = int.from_bytes(data[32:64], "big")
    mod_len = int.from_bytes(data[64:96], "big")
    if (
        base_len > _MODEXP_MAX_LEN
        or exp_len > _MODEXP_MAX_LEN
        or mod_len > _MODEXP_MAX_LEN
    ):
        return None
    total = 96 + base_len + exp_len + mod_len
    if len(data) < total:
        data = data + b"\x00" * (total - len(data))
    base = data[96 : 96 + base_len]
    exp = data[96 + base_len : 96 + base_len + exp_len]
    mod = data[96 + base_len + exp_len : 96 + base_len + exp_len + mod_len]
    if exp_len == 0:
        exp_head = 0
    elif exp_len <= 32:
        exp_head = int.from_bytes(exp, "big") if exp else 0
    else:
        exp_head = int.from_bytes(exp[:32], "big")
    gas = _modexp_gas(base_len, exp_len, mod_len, exp_head)
    return base, exp, mod, gas


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
        # geth getData(inOff, 128): truncate/pad — never require exact length.
        if len(data) < 128:
            data = data + b"\x00" * (128 - len(data))
        else:
            data = data[:128]
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

    if key == _RIPEMD160:
        # Yellow paper: 600 + 120 * words; return left-padded 32-byte digest.
        words = (len(data) + 31) // 32
        gas = 600 + 120 * words
        try:
            import hashlib

            digest = hashlib.new("ripemd160", data).digest()
        except Exception:
            return EVMResult(
                success=False, error="ripemd160_unavailable", gas_used=gas
            )
        return EVMResult(success=True, return_value=digest.rjust(32, b"\x00"), gas_used=gas)

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

    if key == _MODEXP:
        parsed = _parse_modexp(data)
        if parsed is None:
            return EVMResult(success=False, error="modexp_input_too_large", gas_used=0)
        base_b, exp_b, mod_b, gas = parsed
        mod_len = len(mod_b)
        if mod_len == 0:
            return EVMResult(success=True, return_value=b"", gas_used=gas)
        mod_i = int.from_bytes(mod_b, "big")
        if mod_i == 0:
            return EVMResult(success=True, return_value=b"\x00" * mod_len, gas_used=gas)
        base_i = int.from_bytes(base_b, "big") if base_b else 0
        exp_i = int.from_bytes(exp_b, "big") if exp_b else 0
        try:
            out_i = pow(base_i, exp_i, mod_i)
        except Exception:
            return EVMResult(success=False, error="modexp_failed", gas_used=gas)
        out = out_i.to_bytes(mod_len, "big")
        return EVMResult(success=True, return_value=out, gas_used=gas)

    if key == _ECADD:
        gas = 150
        try:
            from execution import bn254

            if not bn254.available():
                return EVMResult(success=False, error="bn254_unavailable", gas_used=gas)
            out = bn254.ec_add(data)
        except Exception as exc:
            return EVMResult(success=False, error=str(exc), gas_used=gas)
        return EVMResult(success=True, return_value=out, gas_used=gas)

    if key == _ECMUL:
        gas = 6000
        try:
            from execution import bn254

            if not bn254.available():
                return EVMResult(success=False, error="bn254_unavailable", gas_used=gas)
            out = bn254.ec_mul(data)
        except Exception as exc:
            return EVMResult(success=False, error=str(exc), gas_used=gas)
        return EVMResult(success=True, return_value=out, gas_used=gas)

    if key == _ECPAIRING:
        if len(data) % 192 != 0:
            return EVMResult(success=False, error="pairing_bad_length", gas_used=0)
        k = len(data) // 192
        gas = 45000 + 34000 * k
        try:
            from execution import bn254

            if not bn254.available():
                return EVMResult(success=False, error="bn254_unavailable", gas_used=gas)
            out = bn254.ec_pairing(data)
        except Exception as exc:
            return EVMResult(success=False, error=str(exc), gas_used=gas)
        return EVMResult(success=True, return_value=out, gas_used=gas)

    if key == _BLAKE2F:
        # EIP-152: gas = rounds (GFROUND=1). Invalid encoding → fail.
        if len(data) != 213:
            return EVMResult(
                success=False, error="blake2f_bad_length", gas_used=0
            )
        rounds = int.from_bytes(data[0:4], "big")
        gas = int(rounds)
        try:
            from execution.blake2f import parse_and_run

            out = parse_and_run(data)
        except ValueError as exc:
            return EVMResult(success=False, error=str(exc), gas_used=gas)
        return EVMResult(success=True, return_value=out, gas_used=gas)

    return None


def is_precompile(contract_addr: str) -> bool:
    return _norm_addr(contract_addr) in {
        _ECRECOVER,
        _SHA256,
        _RIPEMD160,
        _IDENTITY,
        _MODEXP,
        _ECADD,
        _ECMUL,
        _ECPAIRING,
        _BLAKE2F,
    }


def is_evm_call_target(to_addr: str, account_code: object = None) -> bool:
    """True when ``to`` is a precompile or an account with code (not CREATE)."""
    if is_precompile(to_addr or ""):
        return True
    return bool(account_code)
