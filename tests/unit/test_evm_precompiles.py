"""Experimental EVM precompile subset (identity + sha256)."""

from __future__ import annotations

from api.eth_format import encode_eth_call_return
from execution.evm_precompiles import is_precompile, try_precompile


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
