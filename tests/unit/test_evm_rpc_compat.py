"""Experimental EVM RPC compat wave — eth_call encode + receipt/block bloom."""

from __future__ import annotations

from api.eth_format import (
    EMPTY_LOGS_BLOOM,
    block_logs_bloom,
    encode_eth_call_return,
    format_block,
    format_receipt,
    logs_bloom,
)
from api.fake_rpc import FakeQueryFacade, FakeRpcClient
from api.query_facade import QueryFacade


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
    assert r["logsBloom"] == EMPTY_LOGS_BLOOM


def test_logs_bloom_sets_bits_for_address() -> None:
    bloom0 = logs_bloom([])
    bloom1 = logs_bloom(
        [
            {
                "address": "0x" + "11" * 20,
                "topics": ["0x" + "22" * 32],
            }
        ]
    )
    assert bloom0 == EMPTY_LOGS_BLOOM
    assert bloom1 != bloom0
    assert len(bloom1) == 2 + 512
    # At least one non-zero byte when address/topic present
    assert any(c != "0" for c in bloom1[2:])


def test_format_receipt_bloom_from_injected_logs(monkeypatch) -> None:
    class _Facade:
        def get_evm_logs_by_tx(self, _tx_hash):
            return [
                {
                    "block_height": 1,
                    "log_index": 0,
                    "tx_hash": "0xabc",
                    "contract_address": "0x" + "ab" * 20,
                    "data": "0x",
                    "topics": ["0x" + "cd" * 32],
                }
            ]

    tx = {
        "hash": "0xabc",
        "block_height": 1,
        "from_addr": "0x1",
        "to_addr": "0x2",
        "status": 1,
        "gas_used": 21000,
    }
    r = format_receipt(tx, query=_Facade())
    assert r is not None
    assert len(r["logs"]) == 1
    assert r["logsBloom"] != EMPTY_LOGS_BLOOM


def test_format_block_empty_bloom_without_query() -> None:
    from crypto.merkle import merkle_root

    out = format_block({"height": 3, "hash": "0x" + "aa" * 32, "transactions": []})
    assert out is not None
    assert out["logsBloom"] == EMPTY_LOGS_BLOOM
    empty = "0x" + merkle_root(["empty"])
    assert out["transactionsRoot"] == empty
    assert out["receiptsRoot"] == empty
    assert out["transactionsRoot"] != "0x" + "0" * 64
    assert out["sha3Uncles"] == (
        "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
    )
    assert out["sha3Uncles"] != "0x" + "0" * 64


def test_format_block_bloom_from_query_logs() -> None:
    q = FakeQueryFacade(tip=7)
    q.blocks[7] = {"height": 7, "hash": "0x" + "bb" * 32, "transactions": []}
    q.logs = [
        {
            "block_height": 7,
            "tx_hash": "0x1",
            "log_index": 0,
            "contract_address": "0x" + "11" * 20,
            "topics": ["0x" + "22" * 32],
        },
        {
            "block_height": 7,
            "tx_hash": "0x2",
            "log_index": 1,
            "contract_address": "0x" + "33" * 20,
            "topics": ["0x" + "44" * 32],
        },
        {
            "block_height": 6,
            "tx_hash": "0xother",
            "log_index": 0,
            "contract_address": "0x" + "ff" * 20,
            "topics": ["0x" + "ee" * 32],
        },
    ]
    out = format_block(q.blocks[7], query=q)
    assert out is not None
    expected = logs_bloom(q.get_evm_logs_by_block(7))
    assert out["logsBloom"] == expected
    assert out["logsBloom"] != EMPTY_LOGS_BLOOM
    assert out["logsBloom"] != logs_bloom(q.logs)


def test_block_bloom_is_or_of_receipt_logs() -> None:
    log_a = {
        "block_height": 1,
        "contract_address": "0x" + "11" * 20,
        "topics": ["0x" + "aa" * 32],
    }
    log_b = {
        "block_height": 1,
        "contract_address": "0x" + "22" * 20,
        "topics": ["0x" + "bb" * 32],
    }
    q = FakeQueryFacade(tip=1)
    q.logs = [log_a, log_b]
    combined = block_logs_bloom({"height": 1}, query=q)
    assert combined == logs_bloom([log_a, log_b])
    assert combined != logs_bloom([log_a])
    assert combined != logs_bloom([log_b])


def test_block_bloom_prefers_nonzero_stored_header() -> None:
    stored = logs_bloom(
        [{"address": "0x" + "99" * 20, "topics": ["0x" + "88" * 32]}]
    )
    q = FakeQueryFacade(tip=2)
    q.logs = [
        {
            "block_height": 2,
            "contract_address": "0x" + "11" * 20,
            "topics": ["0x" + "22" * 32],
        }
    ]
    out = block_logs_bloom({"height": 2, "logsBloom": stored}, query=q)
    assert out == stored
    assert out != logs_bloom(q.logs)


def test_block_bloom_ignores_getlogs_result_cap() -> None:
    q = FakeQueryFacade(tip=4, max_results=1)
    q.logs = [
        {
            "block_height": 4,
            "tx_hash": "0xa",
            "contract_address": "0x" + "11" * 20,
            "topics": ["0x" + "aa" * 32],
        },
        {
            "block_height": 4,
            "tx_hash": "0xb",
            "contract_address": "0x" + "22" * 20,
            "topics": ["0x" + "bb" * 32],
        },
    ]
    bloom = block_logs_bloom({"height": 4}, query=q)
    assert bloom == logs_bloom(q.logs)
    from api.ports import LogsQuery

    capped = q.query_logs(LogsQuery(from_block=4, to_block=4, limit=100))
    assert len(capped) == 1
    assert bloom != logs_bloom(capped)


def _block_with_log(*, height: int, block_hash: str) -> FakeRpcClient:
    client = FakeRpcClient()
    client.query._tip = height
    client.query.blocks[height] = {
        "height": height,
        "hash": block_hash,
        "transactions": [],
        "timestamp": 1,
    }
    client.query.logs = [
        {
            "block_height": height,
            "contract_address": "0x" + "11" * 20,
            "topics": ["0x" + "22" * 32],
        }
    ]
    return client


def test_eth_get_block_by_number_includes_block_bloom() -> None:
    client = _block_with_log(height=10, block_hash="0x" + "ab" * 32)
    out = client.call("eth_getBlockByNumber", ["latest", False])
    assert out.get("error") is None
    bloom = out["result"]["logsBloom"]
    assert bloom == logs_bloom(client.query.logs)
    assert bloom != EMPTY_LOGS_BLOOM


def test_eth_get_block_by_hash_includes_block_bloom() -> None:
    block_hash = "0x" + "cd" * 32
    client = _block_with_log(height=11, block_hash=block_hash)
    out = client.call("eth_getBlockByHash", [block_hash, False])
    assert out.get("error") is None
    result = out["result"]
    assert result["hash"] == block_hash
    bloom = result["logsBloom"]
    assert bloom == logs_bloom(client.query.logs)
    assert bloom != EMPTY_LOGS_BLOOM


def test_query_facade_logs_by_block_uses_store() -> None:
    class _Store:
        def query_evm_logs(self, from_block=0, to_block=None, addresses=None, topics=None, limit=10_000):
            _ = addresses, topics, limit
            if int(from_block) == 9 and int(to_block) == 9:
                return [
                    {
                        "block_height": 9,
                        "contract_address": "0x" + "ab" * 20,
                        "topics": ["0x" + "cd" * 32],
                    }
                ]
            return []

    class _BC:
        storage = _Store()

        def get_height(self):
            return 9

    rows = QueryFacade(_BC()).get_evm_logs_by_block(9)
    assert len(rows) == 1
    assert rows[0]["block_height"] == 9


def test_format_block_uses_stored_tx_root() -> None:
    stored = "ab" * 32
    out = format_block(
        {
            "height": 1,
            "hash": "0x" + "aa" * 32,
            "tx_root": stored,
            "transactions": ["0x" + "11" * 32],
        }
    )
    assert out is not None
    assert out["transactionsRoot"] == "0x" + stored


def test_format_block_tx_root_matches_core_merkle() -> None:
    from crypto.merkle import merkle_root

    h1 = "0x" + "11" * 32
    h2 = "0x" + "22" * 32
    out = format_block(
        {
            "height": 4,
            "hash": "0x" + "aa" * 32,
            "transactions": [h1, h2],
        }
    )
    assert out is not None
    assert out["transactionsRoot"] == "0x" + merkle_root([h1, h2])
    assert out["transactionsRoot"] != "0x" + "0" * 64
    # Hash-only list: receiptsRoot uses the same leaves.
    assert out["receiptsRoot"] == out["transactionsRoot"]


def test_format_block_receipts_root_includes_status() -> None:
    from crypto.merkle import merkle_root

    h1 = "0x" + "11" * 32
    txs = [
        {"hash": h1, "status": 1},
        {"hash": "0x" + "22" * 32, "status": 0},
    ]
    out = format_block({"height": 5, "hash": "0x" + "aa" * 32, "transactions": txs})
    assert out is not None
    assert out["transactionsRoot"] == "0x" + merkle_root([h1, txs[1]["hash"]])
    assert out["receiptsRoot"] == "0x" + merkle_root([f"{h1}:1", f"{txs[1]['hash']}:0"])
    assert out["receiptsRoot"] != out["transactionsRoot"]


def test_eth_get_block_by_number_roots_are_not_zero_stub() -> None:
    client = _block_with_log(height=10, block_hash="0x" + "ab" * 32)
    out = client.call("eth_getBlockByNumber", ["latest", False])
    assert out.get("error") is None
    result = out["result"]
    assert result["transactionsRoot"] != "0x" + "0" * 64
    assert result["receiptsRoot"] != "0x" + "0" * 64
    assert result["transactionsRoot"].startswith("0x")
    assert len(result["transactionsRoot"]) == 66
    assert result["sha3Uncles"] == (
        "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
    )


def test_block_sha3_uncles_nonempty_is_abs_merkle_not_zero() -> None:
    from api.eth_format import block_sha3_uncles
    from crypto.merkle import merkle_root

    h = "0x" + "ab" * 32
    out = block_sha3_uncles({"uncles": [h]})
    assert out == "0x" + merkle_root([h])
    assert out != "0x" + "0" * 64
    assert out != "0x1dcc4de8dec75d7aab85b567b6ccd41ad312451b948a7413f0a142fd40d49347"
