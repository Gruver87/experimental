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


def test_unknown_address_none() -> None:
    assert try_precompile("0x" + "0" * 39 + "9", "00") is None
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
