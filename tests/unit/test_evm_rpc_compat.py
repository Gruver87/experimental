"""Experimental EVM RPC compat wave — eth_call encode + receipt fields."""

from __future__ import annotations

from api.eth_format import encode_eth_call_return, format_receipt


def test_encode_eth_call_int_word() -> None:
    out = encode_eth_call_return(1)
    assert out.startswith("0x")
    assert len(out) == 2 + 64
    assert out.endswith("1")


def test_encode_eth_call_bytes() -> None:
    assert encode_eth_call_return(b"\x01\x02") == "0x0102"


def test_encode_eth_call_none() -> None:
    assert encode_eth_call_return(None) == "0x"


def test_format_receipt_eth_fields() -> None:
    tx = {
        "hash": "0xabc",
        "block_height": 7,
        "from_addr": "0x1",
        "to_addr": "0x2",
        "status": 1,
        "gas_used": 42000,
        "gas_price": 100,
        "type": 2,
        "tx_index": 3,
    }
    r = format_receipt(tx)
    assert r is not None
    assert r["transactionHash"] == "0xabc"
    assert r["blockNumber"] == hex(7)
    assert r["gasUsed"] == hex(42000)
    assert r["cumulativeGasUsed"] == hex(42000)
    assert r["transactionIndex"] == hex(3)
    assert r["type"] == hex(2)
    assert r["effectiveGasPrice"] == hex(100)
    assert r["logsBloom"].startswith("0x")
    assert len(r["logsBloom"]) == 2 + 512
