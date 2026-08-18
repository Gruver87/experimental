"""Experimental EVM RPC compat wave — eth_call encode + receipt/block bloom."""

from __future__ import annotations

from api.eth_format import (
    EMPTY_LOGS_BLOOM,
    ZERO_HASH,
    ZERO_ROOT,
    block_logs_bloom,
    encode_eth_call_return,
    format_block,
    format_receipt,
    format_tx,
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
    assert r["blockHash"] is None
    assert r["blockHash"] != ZERO_HASH
    assert r["burned"] == 0
    assert isinstance(r["burned"], int)


def test_receipt_cumulative_gas_sums_prior_txs_in_block() -> None:
    q = FakeQueryFacade(tip=3)
    txs = [
        {"hash": "0xa", "gas_used": 21000, "block_height": 3},
        {"hash": "0xb", "gas_used": 42000, "block_height": 3},
        {"hash": "0xc", "gas_used": 1000, "block_height": 3},
    ]
    q.blocks[3] = {"height": 3, "hash": "0x" + "bb" * 32, "transactions": txs}
    mid = format_receipt(txs[1], query=q)
    assert mid is not None
    assert mid["gasUsed"] == hex(42000)
    assert mid["cumulativeGasUsed"] == hex(63000)
    assert mid["transactionIndex"] == hex(1)
    last = format_receipt(txs[2], query=q)
    assert last is not None
    assert last["cumulativeGasUsed"] == hex(64000)
    assert last["transactionIndex"] == hex(2)
    blk = format_block(q.blocks[3], query=q)
    assert blk is not None
    assert blk["gasUsed"] == last["cumulativeGasUsed"]
    assert blk["gasUsed"] == hex(64000)
    assert mid["blockHash"] == q.blocks[3]["hash"]
    assert last["blockHash"] == q.blocks[3]["hash"]


def test_receipt_cumulative_gas_from_hash_only_block_list() -> None:
    q = FakeQueryFacade(tip=4)
    q.blocks[4] = {
        "height": 4,
        "hash": "0x" + "cc" * 32,
        "transactions": ["0xaa", "0xbb"],
    }
    q.txs["0xaa"] = {"hash": "0xaa", "gas_used": 21000, "block_height": 4}
    q.txs["0xbb"] = {"hash": "0xbb", "gas_used": 5000, "block_height": 4}
    r = format_receipt(q.txs["0xbb"], query=q)
    assert r is not None
    assert r["gasUsed"] == hex(5000)
    assert r["cumulativeGasUsed"] == hex(26000)
    assert r["transactionIndex"] == hex(1)
    blk = format_block(q.blocks[4], query=q)
    assert blk is not None
    assert blk["gasUsed"] == hex(26000)
    assert blk["gasUsed"] == r["cumulativeGasUsed"]


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
    assert out["stateRoot"] is None
    assert out["parentHash"] is None
    assert out["totalBurned"] == 0
    assert isinstance(out["totalBurned"], int)
    assert out["nonce"] is None
    assert out["size"] is None


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


def test_format_block_uses_stored_gas_used_when_tx_list_empty() -> None:
    out = format_block(
        {
            "height": 2,
            "hash": "0x" + "aa" * 32,
            "gas_used": 15_000_000,
            "transactions": [],
        }
    )
    assert out is not None
    assert out["gasUsed"] == hex(15_000_000)
    assert out["gasLimit"] == hex(30_000_000)


def test_fee_history_ratios_from_observed_gas() -> None:
    from api.eth_format import ETH_BLOCK_GAS_LIMIT, format_fee_history

    q = FakeQueryFacade(tip=5)
    q.blocks[4] = {
        "height": 4,
        "hash": "0x" + "44" * 32,
        "gas_used": 15_000_000,
        "transactions": [],
    }
    q.blocks[5] = {
        "height": 5,
        "hash": "0x" + "55" * 32,
        "gas_used": ETH_BLOCK_GAS_LIMIT,
        "transactions": [],
    }
    cfg = type("C", (), {"gas_price_wei": 0})()
    out = format_fee_history(query=q, cfg=cfg, block_count=2, newest_tag="latest")
    assert out["oldestBlock"] == hex(4)
    assert out["gasUsedRatio"] == [0.5, 1.0]
    assert len(out["baseFeePerGas"]) == 2
    assert len(out["reward"]) == 2
    assert out["reward"] == [["0x0"], ["0x0"]]


def test_fee_history_does_not_pad_missing_heights() -> None:
    from api.eth_format import format_fee_history

    q = FakeQueryFacade(tip=0)
    q.blocks[0] = {"height": 0, "hash": "0x" + "00" * 32, "transactions": []}
    cfg = type("C", (), {"gas_price_wei": 0})()
    out = format_fee_history(query=q, cfg=cfg, block_count=10, newest_tag="latest")
    assert out["oldestBlock"] == hex(0)
    assert len(out["gasUsedRatio"]) == 1
    assert out["gasUsedRatio"] == [0.0]
    assert 0.5 not in out["gasUsedRatio"]


def test_eth_fee_history_rpc_uses_real_ratio() -> None:
    from api.eth_format import ETH_BLOCK_GAS_LIMIT

    client = FakeRpcClient()
    client.query._tip = 3
    client.query.blocks[2] = {
        "height": 2,
        "hash": "0x" + "22" * 32,
        "gas_used": 7_500_000,
        "transactions": [],
    }
    client.query.blocks[3] = {
        "height": 3,
        "hash": "0x" + "33" * 32,
        "gas_used": ETH_BLOCK_GAS_LIMIT // 4,
        "transactions": [],
    }
    out = client.call("eth_feeHistory", [hex(2), "latest", []])
    assert out.get("error") is None
    result = out["result"]
    assert result["oldestBlock"] == hex(2)
    assert result["gasUsedRatio"] == [7_500_000 / ETH_BLOCK_GAS_LIMIT, 0.25]
    assert 0.5 not in result["gasUsedRatio"]


def test_receipt_block_hash_from_block_listing() -> None:
    q = FakeQueryFacade(tip=8)
    h = "0x" + "ab" * 32
    tx = {"hash": "0xaaa", "gas_used": 21000, "block_height": 8}
    q.blocks[8] = {"height": 8, "hash": h, "transactions": [tx]}
    r = format_receipt(tx, query=q)
    assert r is not None
    assert r["blockHash"] == h
    assert r["blockHash"] != ZERO_HASH


def test_receipt_rejects_zero_stored_block_hash() -> None:
    r = format_receipt(
        {
            "hash": "0xabc",
            "block_height": 1,
            "gas_used": 21000,
            "block_hash": ZERO_HASH,
        }
    )
    assert r is not None
    assert r["blockHash"] is None


def test_format_tx_block_hash_and_index_from_query() -> None:
    q = FakeQueryFacade(tip=2)
    h = "0x" + "cd" * 32
    tx = {"hash": "0xbb", "block_height": 2, "value": 0}
    q.blocks[2] = {"height": 2, "hash": h, "transactions": ["0xaa", "0xbb"]}
    out = format_tx(tx, query=q)
    assert out is not None
    assert out["blockHash"] == h
    assert out["transactionIndex"] == hex(1)
    assert out["blockHash"] != ZERO_HASH


def test_eth_get_transaction_receipt_block_hash() -> None:
    client = FakeRpcClient()
    h = "0x" + "ef" * 32
    client.query._tip = 6
    tx = {"hash": "0xdead", "block_height": 6, "gas_used": 21000, "status": 1}
    client.query.txs["0xdead"] = tx
    client.query.blocks[6] = {"height": 6, "hash": h, "transactions": [tx]}
    out = client.call("eth_getTransactionReceipt", ["0xdead"])
    assert out.get("error") is None
    assert out["result"]["blockHash"] == h
    tx_out = client.call("eth_getTransactionByHash", ["0xdead"])
    assert tx_out.get("error") is None
    assert tx_out["result"]["blockHash"] == h
    assert tx_out["result"]["transactionIndex"] == hex(0)
    assert tx_out["result"]["blockNumber"] == hex(6)


def test_pending_tx_inclusion_fields_are_null() -> None:
    out = format_tx({"hash": "0xabc", "value": 0})
    assert out is not None
    assert out["blockNumber"] is None
    assert out["blockHash"] is None
    assert out["transactionIndex"] is None
    r = format_receipt({"hash": "0xabc", "gas_used": 21000})
    assert r is not None
    assert r["blockNumber"] is None
    assert r["blockHash"] is None


def test_format_tx_gas_price_from_stored() -> None:
    out = format_tx({"hash": "0xabc", "block_height": 1, "gas_price": 42})
    assert out is not None
    assert out["gasPrice"] == hex(42)
    assert out["blockNumber"] == hex(1)


def test_format_block_extra_data_from_header() -> None:
    out = format_block(
        {
            "height": 1,
            "hash": "0x" + "aa" * 32,
            "extra_data": "abs",
            "transactions": [],
        }
    )
    assert out is not None
    assert out["extraData"] == "0x" + b"abs".hex()
    empty = format_block({"height": 1, "hash": "0x" + "bb" * 32, "transactions": []})
    assert empty is not None
    assert empty["extraData"] == "0x"
    assert empty["uncles"] == []


def test_format_block_uncles_match_observed_list() -> None:
    h = "0x" + "ab" * 32
    out = format_block(
        {
            "height": 1,
            "hash": "0x" + "aa" * 32,
            "uncles": [h],
            "transactions": [],
        }
    )
    assert out is not None
    assert out["uncles"] == [h]


def test_missing_block_tx_count_is_null() -> None:
    client = FakeRpcClient()
    out = client.call("eth_getBlockTransactionCountByHash", ["0x" + "11" * 32])
    assert out.get("error") is None
    assert out["result"] is None


def test_observed_block_tx_count() -> None:
    client = FakeRpcClient()
    h = "0x" + "aa" * 32
    client.query._tip = 1
    client.query.blocks[1] = {"height": 1, "hash": h, "transactions": ["0x1", "0x2"]}
    out = client.call("eth_getBlockTransactionCountByHash", [h])
    assert out.get("error") is None
    assert out["result"] == hex(2)


def test_missing_uncle_count_is_null() -> None:
    client = FakeRpcClient()
    out = client.call("eth_getUncleCountByBlockHash", ["0x" + "22" * 32])
    assert out.get("error") is None
    assert out["result"] is None


def test_latest_uncle_count_is_zero_for_observed_block() -> None:
    client = FakeRpcClient()
    out = client.call("eth_getUncleCountByBlockNumber", ["latest"])
    assert out.get("error") is None
    assert out["result"] == hex(0)


def test_get_uncle_by_index_null_when_none() -> None:
    client = FakeRpcClient()
    out = client.call("eth_getUncleByBlockNumberAndIndex", ["latest", "0x0"])
    assert out.get("error") is None
    assert out["result"] is None
    missing = client.call(
        "eth_getUncleByBlockHashAndIndex", ["0x" + "33" * 32, "0x0"]
    )
    assert missing.get("error") is None
    assert missing["result"] is None


def test_get_uncle_by_index_returns_stored_header() -> None:
    client = FakeRpcClient()
    parent = "0x" + "aa" * 32
    uncle_hash = "0x" + "bb" * 32
    uncle = {
        "height": 1,
        "hash": uncle_hash,
        "parent_hash": "0x" + "00" * 32,
        "transactions": [],
        "timestamp": 9,
    }
    client.query._tip = 2
    client.query.blocks[2] = {
        "height": 2,
        "hash": parent,
        "transactions": [],
        "uncles": [uncle],
    }
    out = client.call("eth_getUncleByBlockNumberAndIndex", ["latest", "0x0"])
    assert out.get("error") is None
    result = out["result"]
    assert result is not None
    assert result["hash"] == uncle_hash
    assert result["number"] == hex(1)
    empty = client.call("eth_getUncleByBlockNumberAndIndex", ["latest", "0x1"])
    assert empty["result"] is None


def test_get_uncle_hash_only_without_header_is_null() -> None:
    q = FakeQueryFacade(tip=4)
    h = "0x" + "cc" * 32
    q.blocks[4] = {
        "height": 4,
        "hash": "0x" + "dd" * 32,
        "transactions": [],
        "uncles": [h],
    }
    from api.eth_format import format_uncle_by_index

    assert format_uncle_by_index(q.blocks[4], 0, query=q) is None


def test_get_uncle_hash_resolves_stored_block() -> None:
    q = FakeQueryFacade(tip=5)
    uncle_hash = "0x" + "ee" * 32
    q.blocks[3] = {
        "height": 3,
        "hash": uncle_hash,
        "transactions": [],
        "timestamp": 4,
    }
    q.blocks[5] = {
        "height": 5,
        "hash": "0x" + "ff" * 32,
        "transactions": [],
        "uncles": [uncle_hash],
    }
    from api.eth_format import format_uncle_by_index

    out = format_uncle_by_index(q.blocks[5], 0, query=q)
    assert out is not None
    assert out["hash"] == uncle_hash
    assert out["number"] == hex(3)


def test_genesis_parent_hash_may_be_zero() -> None:
    out = format_block({"height": 0, "hash": "0x" + "aa" * 32, "transactions": []})
    assert out is not None
    assert out["parentHash"] == ZERO_HASH


def test_non_genesis_missing_parent_hash_is_null() -> None:
    out = format_block({"height": 4, "hash": "0x" + "aa" * 32, "transactions": []})
    assert out is not None
    assert out["parentHash"] is None
    stored = "bb" * 32
    with_parent = format_block(
        {
            "height": 4,
            "hash": "0x" + "aa" * 32,
            "parent_hash": stored,
            "transactions": [],
        }
    )
    assert with_parent is not None
    assert with_parent["parentHash"] == "0x" + stored


def test_missing_or_zero_state_root_is_null() -> None:
    missing = format_block({"height": 2, "hash": "0x" + "aa" * 32, "transactions": []})
    assert missing is not None
    assert missing["stateRoot"] is None
    stub = format_block(
        {
            "height": 2,
            "hash": "0x" + "aa" * 32,
            "state_root": "0" * 64,
            "transactions": [],
        }
    )
    assert stub is not None
    assert stub["stateRoot"] is None
    assert stub["stateRoot"] != ZERO_ROOT
    real = "cc" * 32
    stored = format_block(
        {
            "height": 2,
            "hash": "0x" + "aa" * 32,
            "state_root": real,
            "transactions": [],
        }
    )
    assert stored is not None
    assert stored["stateRoot"] == "0x" + real


def test_burned_fields_are_satoshi_integers() -> None:
    blk = format_block(
        {
            "height": 8,
            "hash": "0x" + "aa" * 32,
            "total_burned": 0.5,
            "transactions": [],
        }
    )
    assert blk is not None
    assert blk["totalBurned"] == 500_000
    assert isinstance(blk["totalBurned"], int)
    tx_out = format_tx({"hash": "0xabc", "burned": 0.02})
    assert tx_out is not None
    assert tx_out["burned"] == 20_000
    assert isinstance(tx_out["burned"], int)
    receipt = format_receipt({"hash": "0xabc", "burned": 0.02, "block_height": 1})
    assert receipt is not None
    assert receipt["burned"] == 20_000
    assert isinstance(receipt["burned"], int)


def test_block_nonce_and_size_are_not_invented() -> None:
    txs = ["0x" + "11" * 32, "0x" + "22" * 32]
    missing = format_block(
        {"height": 6, "hash": "0x" + "aa" * 32, "transactions": txs}
    )
    assert missing is not None
    assert missing["nonce"] is None
    assert missing["size"] is None
    assert missing["size"] != hex(256 + 2 * 32)
    # Integer nonce on a block row is a tx/account field — not ethash.
    contaminated = format_block(
        {
            "height": 6,
            "hash": "0x" + "aa" * 32,
            "nonce": 7,
            "transactions": txs,
        }
    )
    assert contaminated is not None
    assert contaminated["nonce"] is None
    stored = format_block(
        {
            "height": 6,
            "hash": "0x" + "aa" * 32,
            "nonce": "0x00000000000000ab",
            "block_size": 320,
            "transactions": txs,
        }
    )
    assert stored is not None
    assert stored["nonce"] == "0x00000000000000ab"
    assert stored["size"] == hex(320)
    via_key = format_block(
        {
            "height": 6,
            "hash": "0x" + "aa" * 32,
            "block_nonce": 171,
            "size": 99,
            "transactions": [],
        }
    )
    assert via_key is not None
    assert via_key["nonce"] == "0x00000000000000ab"
    assert via_key["size"] == hex(99)
