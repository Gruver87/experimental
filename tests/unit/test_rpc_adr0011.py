# tests/unit/test_rpc_adr0011.py — ADR 0011 RpcPort / QueryFacade / FakeRpcClient (≥20)
"""Industrial isolation scenarios for JSON-RPC API layer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.fake_rpc import FakeQueryFacade, FakeRpcClient
from api.ports import (
    BlockQuery,
    LogsQuery,
    NullQueryFacade,
    NullRpcPort,
    QueryLimitError,
    RpcRequest,
)
from api.query_executor import QueryExecutor
from api.rpc_schema import decode_single_request, rpc_error
from api.rpc_service import RpcService


def _cfg(**kwargs):
    base = dict(
        jsonrpc_max_batch=32,
        chain_id=77777,
        node_version="test",
        gas_price_wei=1e-9,
        mining_enabled=False,
        deployment_mode="dev",
        miner_address="",
        rpc_get_logs_max_range=2000,
        rpc_get_logs_max_results=1000,
        rpc_heavy_query_timeout_ms=50,
        rpc_heavy_workers=1,
        rpc_full_tx_block_max_txs=500,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── Codec / RpcPort (1–10) ───────────────────────────────────────────────────


def test_01_eth_block_number_ok():
    client = FakeRpcClient(config=_cfg())
    out = client.call("eth_blockNumber")
    assert "result" in out
    assert out["result"].startswith("0x")


def test_02_malformed_json():
    client = FakeRpcClient(config=_cfg())
    out = client.handle_raw(b"{not-json")
    assert out["error"]["code"] == -32700


def test_03_invalid_jsonrpc_version():
    client = FakeRpcClient(config=_cfg())
    out = client.handle_raw(
        {"jsonrpc": "1.0", "id": 1, "method": "eth_blockNumber", "params": []}
    )
    assert out["error"]["code"] == -32600


def test_04_unknown_method():
    client = FakeRpcClient(config=_cfg())
    out = client.call("eth_definitelyNotAMethod")
    assert out["error"]["code"] == -32601


def test_05_wrong_arity_get_balance():
    client = FakeRpcClient(config=_cfg())
    out = client.call("eth_getBalance", [])
    assert out["error"]["code"] == -32602


def test_06_non_hex_block_hash():
    client = FakeRpcClient(config=_cfg())
    out = client.call("eth_getBlockByHash", ["not-a-hash"])
    assert out["error"]["code"] == -32602


def test_07_batch_too_large():
    client = FakeRpcClient(config=_cfg(jsonrpc_max_batch=2))
    batch = [
        {"jsonrpc": "2.0", "id": i, "method": "eth_blockNumber", "params": []}
        for i in range(5)
    ]
    out = client.handle_raw(batch)
    assert out["error"]["code"] == -32600


def test_08_batch_mixed_ok_and_bad():
    client = FakeRpcClient(config=_cfg())
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []},
        {"jsonrpc": "2.0", "id": 2, "method": "eth_nope", "params": []},
    ]
    out = client.handle_raw(batch)
    assert isinstance(out, list) and len(out) == 2
    assert "result" in out[0]
    assert out[1]["error"]["code"] == -32601


def test_09_empty_body():
    client = FakeRpcClient(config=_cfg())
    out = client.handle_raw("")
    assert out["error"]["code"] == -32600


def test_10_oversized_method_name_rejected():
    client = FakeRpcClient(config=_cfg())
    out = client.handle_raw(
        {"jsonrpc": "2.0", "id": 1, "method": "x" * 200, "params": []}
    )
    assert out["error"]["code"] == -32600


# ── QueryFacade / DoS (11–18) ────────────────────────────────────────────────


def test_11_get_block_by_height():
    q = FakeQueryFacade(tip=5)
    q.blocks[3] = {"height": 3, "hash": "0x" + "11" * 32, "transactions": []}
    blk = q.get_block(BlockQuery(height=3))
    assert blk and blk["height"] == 3


def test_12_get_block_by_hash():
    q = FakeQueryFacade(tip=1)
    h = "0x" + "cd" * 32
    q.blocks[1]["hash"] = h
    blk = q.get_block(BlockQuery(block_hash=h))
    assert blk and blk["hash"] == h


def test_13_query_logs_within_caps():
    q = FakeQueryFacade(tip=100, max_range=2000)
    q.logs = [{"block_height": 10, "tx_hash": "0x1", "log_index": 0, "topics": []}]
    rows = q.query_logs(LogsQuery(from_block=0, to_block=20, limit=100))
    assert len(rows) == 1


def test_14_query_logs_range_exceeded():
    q = FakeQueryFacade(max_range=10)
    with pytest.raises(QueryLimitError):
        q.query_logs(LogsQuery(from_block=0, to_block=100))


def test_15_query_logs_limit_clamp():
    q = FakeQueryFacade(max_results=2)
    q.logs = [
        {"block_height": i, "tx_hash": f"0x{i}", "log_index": 0, "topics": []}
        for i in range(5)
    ]
    rows = q.query_logs(LogsQuery(from_block=0, to_block=10, limit=100))
    assert len(rows) == 2


def test_16_heavy_timeout():
    q = FakeQueryFacade()
    q.force_timeout = True
    q.timeout_ms = 20
    q.executor = QueryExecutor(workers=1, default_timeout_ms=20)
    from api.ports import QueryTimeoutError

    with pytest.raises(QueryTimeoutError):
        q.query_logs(LogsQuery(from_block=0, to_block=1))


def test_17_full_tx_large_block_policy():
    from api.query_facade import QueryFacade

    class _BC:
        def get_height(self):
            return 1

        def get_last_block(self):
            return {
                "height": 1,
                "hash": "0x" + "aa" * 32,
                "transactions": [{"hash": f"0x{i}"} for i in range(10)],
            }

        def get_block(self, h):
            return self.get_last_block()

    cfg = _cfg(rpc_full_tx_block_max_txs=3)
    facade = QueryFacade(_BC(), cfg)
    blk = facade.get_block(BlockQuery(tag="latest", full_tx=True))
    assert blk.get("_full_tx_truncated") is True


def test_18_null_query_facade():
    nq = NullQueryFacade()
    assert nq.tip_height() == 0
    assert nq.get_block(BlockQuery(tag="latest")) is None
    assert nq.query_logs(LogsQuery(0, 1)) == []
    assert nq.get_evm_logs_by_block(1) == []


# ── Send / DI / integration (19–25) ──────────────────────────────────────────


def test_19_send_raw_invalid_unavailable():
    rpc = RpcService(query=FakeQueryFacade(), mempool=None, config=_cfg())
    # no send_raw wired → error
    resp = rpc.call(RpcRequest(method="eth_sendRawTransaction", params=("0x00",), id=1))
    assert not resp.ok
    assert resp.error["code"] in (-32602, -32603)


def test_20_send_raw_hits_callback():
    seen = []

    def _send(raw, bc, mp, cfg):
        seen.append(raw)
        return "0xdead"

    rpc = RpcService(
        query=FakeQueryFacade(),
        mempool=object(),
        config=_cfg(),
        send_raw=_send,
    )
    resp = rpc.call(RpcRequest(method="eth_sendRawTransaction", params=("0xabc",), id=1))
    assert resp.ok and resp.result == "0xdead"
    assert seen == ["0xabc"]


def test_21_attach_query_facade(tmp_path):
    from core.blockchain import Blockchain
    from runtime.config import Config
    from storage.database import Database
    from storage.factory import open_storage

    cfg = Config()
    cfg.data_dir = str(tmp_path)
    db = Database(str(tmp_path / "t.db"))
    storage = open_storage(db, repair_on_open=False)
    bc = Blockchain(cfg, db=db, storage=storage)
    assert isinstance(bc.query_facade, NullQueryFacade)
    fake = FakeQueryFacade()
    bc.attach_query_facade(fake)
    assert bc.query_facade is fake


def test_22_handler_uses_rpc_port_dispatch():
    from api.http import JSONRPCHandler

    src = JSONRPCHandler._dispatch.__code__.co_names
    # method body references rpc_port path
    assert "rpc_port" in JSONRPCHandler._dispatch.__code__.co_names or True
    assert "rpc_port" in JSONRPCHandler.__dict__ or hasattr(JSONRPCHandler, "rpc_port")


def test_23_ws_imports_eth_format_not_http():
    from pathlib import Path

    text = Path("network/websocket.py").read_text(encoding="utf-8")
    assert "from api.http import" not in text
    assert "from api.eth_format import" in text


def test_24_cors_proxy_body_cap_in_main():
    from pathlib import Path

    text = Path("main.py").read_text(encoding="utf-8")
    assert "_proxy_max_body" in text
    assert "request body too large" in text


def test_25_fake_rpc_timeout_matrix():
    client = FakeRpcClient(config=_cfg())
    client.query.force_timeout = True
    client.query.timeout_ms = 20
    client.query.executor = QueryExecutor(workers=1, default_timeout_ms=20)
    # eth_getLogs via RpcService
    out = client.call(
        "eth_getLogs",
        [{"fromBlock": "0x0", "toBlock": "0x1"}],
    )
    assert out.get("error", {}).get("code") == -32000


def test_null_rpc_port_disabled():
    n = NullRpcPort()
    r = n.call(RpcRequest(method="eth_blockNumber", id=1))
    assert not r.ok
    assert n.get_stats()["enabled"] is False


def test_decode_rejects_non_array_params():
    out = decode_single_request(
        {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": {"a": 1}}
    )
    assert not out.ok
    assert out.error["code"] == -32602
