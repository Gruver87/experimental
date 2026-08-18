#!/usr/bin/env python3
"""Keycodec tests for symbolic genesis addresses."""

import pytest

from storage.keycodec import (
    key_account,
    normalize_address_key,
    prefix_evm_logs_block,
    prefix_family_end,
    P_EVM_LOG,
)


@pytest.mark.parametrize(
    "address",
    [
        "0xbeb0962327d6f0ad8de263bd883bb184e88744a2",
        "0xecosystem000000000000000000000000000001",
        "0xtreasury00000000000000000000000000001",
        "0xstaking0000000000000000000000000000001",
        "genesis",
        "mining_pool",
    ],
)
def test_key_account_symbolic_addresses(address: str):
    key = key_account(address)
    assert key.startswith(b"\x10")
    assert normalize_address_key(address).encode("utf-8") in key


def test_key_account_roundtrip_bytes():
    addr = "0xtreasury00000000000000000000000000001"
    suffix = key_account(addr)[1:]
    assert suffix.decode("utf-8") == addr


def test_prefix_evm_logs_block_orders_by_height():
    a = prefix_evm_logs_block(5)
    b = prefix_evm_logs_block(6)
    assert a.startswith(P_EVM_LOG)
    assert a < b
    assert prefix_family_end(P_EVM_LOG) == bytes([P_EVM_LOG[0] + 1])
