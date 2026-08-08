"""BN254 / alt_bn128 helpers for EVM precompiles 0x06–0x08 (experimental).

Uses ``py_ecc`` when installed. Honesty: not a constant-time audited stack.
"""

from __future__ import annotations

from typing import Any

_FIELD_MODULUS = 21888242871839275222246405745257275088696311157297823662689037894645226208583
_CURVE_ORDER = 21888242871839275222246405745257275088548364400416034343698204186575808495617


def _py_ecc():
    try:
        from py_ecc.bn128 import FQ, FQ2, FQ12, add, multiply, pairing  # type: ignore
        from py_ecc.bn128.bn128_curve import b, b2, is_inf, is_on_curve  # type: ignore

        return {
            "FQ": FQ,
            "FQ2": FQ2,
            "FQ12": FQ12,
            "add": add,
            "multiply": multiply,
            "pairing": pairing,
            "b": b,
            "b2": b2,
            "is_on_curve": is_on_curve,
            "is_inf": is_inf,
        }
    except ImportError as exc:
        raise RuntimeError("bn254 requires py_ecc") from exc


def available() -> bool:
    try:
        _py_ecc()
        return True
    except Exception:
        return False


def _decode_g1(data: bytes, offset: int = 0) -> Any:
    ecc = _py_ecc()
    x = int.from_bytes(data[offset : offset + 32], "big")
    y = int.from_bytes(data[offset + 32 : offset + 64], "big")
    if x == 0 and y == 0:
        return None
    if x >= _FIELD_MODULUS or y >= _FIELD_MODULUS:
        raise ValueError("g1 coordinate out of field")
    pt = (ecc["FQ"](x), ecc["FQ"](y))
    if not ecc["is_on_curve"](pt, ecc["b"]):
        raise ValueError("g1 point not on curve")
    return pt


def _encode_g1(pt: Any) -> bytes:
    ecc = _py_ecc()
    if pt is None or ecc["is_inf"](pt):
        return b"\x00" * 64
    x = int(pt[0]) % _FIELD_MODULUS
    y = int(pt[1]) % _FIELD_MODULUS
    return x.to_bytes(32, "big") + y.to_bytes(32, "big")


def ec_add(data: bytes) -> bytes:
    """Precompile 0x06 — 128-byte input → 64-byte point."""
    if len(data) < 128:
        data = data + b"\x00" * (128 - len(data))
    elif len(data) > 128:
        data = data[:128]
    p = _decode_g1(data, 0)
    q = _decode_g1(data, 64)
    ecc = _py_ecc()
    if p is None:
        return _encode_g1(q)
    if q is None:
        return _encode_g1(p)
    return _encode_g1(ecc["add"](p, q))


def ec_mul(data: bytes) -> bytes:
    """Precompile 0x07 — 96-byte input → 64-byte point."""
    if len(data) < 96:
        data = data + b"\x00" * (96 - len(data))
    elif len(data) > 96:
        data = data[:96]
    p = _decode_g1(data, 0)
    scalar = int.from_bytes(data[64:96], "big") % _CURVE_ORDER
    if p is None or scalar == 0:
        return b"\x00" * 64
    ecc = _py_ecc()
    return _encode_g1(ecc["multiply"](p, scalar))


def _decode_g2(data: bytes, offset: int = 0) -> Any:
    """Ethereum G2 encoding: x=(x_im||x_re), y=(y_im||y_re)."""
    ecc = _py_ecc()
    FQ2 = ecc["FQ2"]
    x_i = int.from_bytes(data[offset : offset + 32], "big")
    x_r = int.from_bytes(data[offset + 32 : offset + 64], "big")
    y_i = int.from_bytes(data[offset + 64 : offset + 96], "big")
    y_r = int.from_bytes(data[offset + 96 : offset + 128], "big")
    if x_i == 0 and x_r == 0 and y_i == 0 and y_r == 0:
        return None
    for v in (x_i, x_r, y_i, y_r):
        if v >= _FIELD_MODULUS:
            raise ValueError("g2 coordinate out of field")
    pt = (FQ2([x_r, x_i]), FQ2([y_r, y_i]))
    if not ecc["is_on_curve"](pt, ecc["b2"]):
        raise ValueError("g2 point not on curve")
    return pt


def ec_pairing(data: bytes) -> bytes:
    """Precompile 0x08 — k*192 bytes → 32-byte boolean."""
    if len(data) % 192 != 0:
        raise ValueError("pairing input length must be multiple of 192")
    ecc = _py_ecc()
    k = len(data) // 192
    if k == 0:
        return (1).to_bytes(32, "big")
    acc = ecc["FQ12"].one()
    for i in range(k):
        chunk = data[i * 192 : (i + 1) * 192]
        g1 = _decode_g1(chunk, 0)
        g2 = _decode_g2(chunk, 64)
        if g1 is None or g2 is None:
            continue
        acc = acc * ecc["pairing"](g2, g1)
    return (1 if acc == ecc["FQ12"].one() else 0).to_bytes(32, "big")
