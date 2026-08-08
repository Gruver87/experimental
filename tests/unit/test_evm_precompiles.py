"""Experimental EVM precompile subset (ecrecover + identity + sha256)."""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from api.eth_format import encode_eth_call_return
from crypto import native
from crypto.crypto import Crypto
from crypto.secp256k1_backend import sign
from execution.evm_precompiles import is_precompile, try_precompile

pytestmark = pytest.mark.skipif(
    not native.native_available(),
    reason="abs_native required for ecrecover precompile tests",
)


def test_identity_precompile() -> None:
    data = b"hello-absolute"
    r = try_precompile("0x" + "0" * 38 + "04", data.hex())
    assert r is not None
    assert r.success
    assert r.return_value == data
    assert encode_eth_call_return(r.return_value) == "0x" + data.hex()


def test_sha256_precompile() -> None:
    import hashlib

    payload = b"abc"
    r = try_precompile("0x0000000000000000000000000000000000000002", payload.hex())
    assert r is not None and r.success
    assert r.return_value == hashlib.sha256(payload).digest()


def _modexp_calldata(base: bytes, exp: bytes, mod: bytes) -> str:
    def _len(n: int) -> bytes:
        return n.to_bytes(32, "big")

    return (_len(len(base)) + _len(len(exp)) + _len(len(mod)) + base + exp + mod).hex()


def test_blake2f_eip152_vector5() -> None:
    # EIP-152 test vector 5 (12 rounds, f=1) — blake2b("abc") compression.
    inp = bytes.fromhex(
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
    assert len(inp) == 213
    r = try_precompile("0x09", inp.hex())
    assert r is not None and r.success
    assert r.gas_used == 12
    assert r.return_value.hex() == (
        "ba80a53f981c4d0d6a2797b69f12f6e94c212f14685ac4b74b12bb6fdbffa2d1"
        "7d87c5392aab792dc252d5de4533cc9518d38aa8dbf1925ab92386edd4009923"
    )


def test_blake2f_bad_length() -> None:
    r = try_precompile("0x09", "00")
    assert r is not None and not r.success


def test_modexp_precompile() -> None:
    # 3^5 mod 7 = 5; EIP-2565 min gas 200 for tiny inputs.
    data = _modexp_calldata(b"\x03", b"\x05", b"\x07")
    r = try_precompile("0x0000000000000000000000000000000000000005", data)
    assert r is not None and r.success
    assert r.return_value == b"\x05"
    assert r.gas_used >= 200


def test_modexp_zero_modulus() -> None:
    data = _modexp_calldata(b"\x02", b"\x03", b"\x00")
    r = try_precompile("0x05", data)
    assert r is not None and r.success
    assert r.return_value == b"\x00"


def test_ripemd160_precompile() -> None:
    import hashlib

    payload = b"abc"
    r = try_precompile("0x0000000000000000000000000000000000000003", payload.hex())
    assert r is not None and r.success
    digest = hashlib.new("ripemd160", payload).digest()
    assert r.return_value == digest.rjust(32, b"\x00")
    assert r.gas_used == 600 + 120 * 1


def test_unknown_address_none() -> None:
    # 0x0a is not implemented (bn254 range starts at 0x06; blake2f is 0x09).
    assert try_precompile("0x" + "0" * 38 + "0a", "00") is None
    assert not is_precompile("0xdead")


def test_ecrecover_precompile() -> None:
    _priv, _pub, addr = Crypto.generate_keypair()
    private_key = bytes.fromhex(_priv)
    prehash = native.keccak256_digest(b"ecrecover-wave3")

    def _prehashed(_message: bytes):
        class _Digest:
            def digest(self):
                return prehash

        return _Digest()

    der = sign(prehash, private_key, hashfunc=_prehashed)
    r_int, s_int = decode_dss_signature(der)
    r = r_int.to_bytes(32, "big")
    s = s_int.to_bytes(32, "big")
    rec_id = None
    for candidate in (0, 1):
        recovered = native.recover_eth_address_keccak(prehash, r, s, candidate)
        if recovered.lower() == addr.lower():
            rec_id = candidate
            break
    assert rec_id is not None
    v = (27 + rec_id).to_bytes(32, "big")
    data = (prehash + v + r + s).hex()
    out = try_precompile("0x0000000000000000000000000000000000000001", data)
    assert out is not None and out.success
    assert out.gas_used == 3000
    got = "0x" + out.return_value[-20:].hex()
    assert got.lower() == addr.lower()


def test_ecrecover_bad_v_empty() -> None:
    data = (b"\x00" * 32 + (99).to_bytes(32, "big") + b"\x11" * 64).hex()
    out = try_precompile("0x01", data)
    assert out is not None and out.success
    assert out.return_value == b"\x00" * 32
