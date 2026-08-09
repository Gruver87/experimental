"""BLAKE2b compression function F (EIP-152 / RFC 7693).

Used by the ``0x09`` precompile. Pure Python — lab/R&D path.
"""

from __future__ import annotations

from typing import List

_MASK64 = (1 << 64) - 1

_IV = [
    0x6A09E667F3BCC908,
    0xBB67AE8584CAA73B,
    0x3C6EF372FE94F82B,
    0xA54FF53A5F1D36F1,
    0x510E527FADE682D1,
    0x9B05688C2B3E6C1F,
    0x1F83D9ABFB41BD6B,
    0x5BE0CD19137E2179,
]

_SIGMA = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
]


def _rotr64(x: int, n: int) -> int:
    return ((x >> n) | (x << (64 - n))) & _MASK64


def _g(v: List[int], a: int, b: int, c: int, d: int, x: int, y: int) -> None:
    v[a] = (v[a] + v[b] + x) & _MASK64
    v[d] = _rotr64(v[d] ^ v[a], 32)
    v[c] = (v[c] + v[d]) & _MASK64
    v[b] = _rotr64(v[b] ^ v[c], 24)
    v[a] = (v[a] + v[b] + y) & _MASK64
    v[d] = _rotr64(v[d] ^ v[a], 16)
    v[c] = (v[c] + v[d]) & _MASK64
    v[b] = _rotr64(v[b] ^ v[c], 63)


def blake2b_f(
    rounds: int,
    h: List[int],
    m: List[int],
    t0: int,
    t1: int,
    f: bool,
) -> List[int]:
    """Run ``rounds`` of BLAKE2b F; return updated 8-word state ``h``."""
    v = list(h) + list(_IV)
    v[12] ^= t0 & _MASK64
    v[13] ^= t1 & _MASK64
    if f:
        v[14] ^= _MASK64
    for i in range(int(rounds)):
        s = _SIGMA[i % 10]
        _g(v, 0, 4, 8, 12, m[s[0]], m[s[1]])
        _g(v, 1, 5, 9, 13, m[s[2]], m[s[3]])
        _g(v, 2, 6, 10, 14, m[s[4]], m[s[5]])
        _g(v, 3, 7, 11, 15, m[s[6]], m[s[7]])
        _g(v, 0, 5, 10, 15, m[s[8]], m[s[9]])
        _g(v, 1, 6, 11, 12, m[s[10]], m[s[11]])
        _g(v, 2, 7, 8, 13, m[s[12]], m[s[13]])
        _g(v, 3, 4, 9, 14, m[s[14]], m[s[15]])
    return [(h[i] ^ v[i] ^ v[i + 8]) & _MASK64 for i in range(8)]


def parse_and_run(data: bytes) -> bytes:
    """Parse 213-byte EIP-152 input and return 64-byte little-endian ``h``."""
    if len(data) != 213:
        raise ValueError("blake2f input must be exactly 213 bytes")
    rounds = int.from_bytes(data[0:4], "big")
    h = [int.from_bytes(data[4 + i * 8 : 12 + i * 8], "little") for i in range(8)]
    m = [int.from_bytes(data[68 + i * 8 : 76 + i * 8], "little") for i in range(16)]
    t0 = int.from_bytes(data[196:204], "little")
    t1 = int.from_bytes(data[204:212], "little")
    f_byte = data[212]
    if f_byte not in (0, 1):
        raise ValueError("incorrect final block indicator flag")
    # eth_call DoS bound — full geth may accept larger; we refuse above cap.
    if rounds > 100_000:
        raise ValueError("blake2f rounds exceed lab cap 100000")
    out_h = blake2b_f(rounds, h, m, t0, t1, bool(f_byte))
    return b"".join(w.to_bytes(8, "little") for w in out_h)
