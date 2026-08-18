# api/rpc_service.py — ADR 0011 default RpcPort
"""Ethereum JSON-RPC method dispatch behind QueryFacadePort."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from runtime.amount import WEI_PER_SATOSHI, abs_to_wei, to_satoshi
from api.eth_format import (
    format_block,
    format_fee_history,
    format_receipt,
    format_tx,
    handle_eth_get_logs,
    resolve_block_by_tag,
    tx_at_block_index,
)
from api.ports import (
    BlockQuery,
    QueryLimitError,
    QueryTimeoutError,
    RpcRequest,
    RpcResponse,
)
from api.rpc_schema import (
    GetBalanceParams,
    GetBlockByHashParams,
    GetBlockByNumberParams,
    GetLogsParams,
    GetStorageAtParams,
    AddressOnlyParams,
    SendRawTxParams,
    TxHashParams,
    parse_method_params,
    rpc_error,
    validate_block_hash_param,
)


def _is_production_cfg(cfg) -> bool:
    mode = str(getattr(cfg, "deployment_mode", "dev") or "dev").lower()
    return mode in ("prod", "production")


class RpcService:
    def __init__(
        self,
        *,
        query: Any,
        blockchain: Any = None,
        mempool: Any = None,
        config: Any = None,
        evm: Any = None,
        p2p: Any = None,
        wallet: Any = None,
        sync_engine: Any = None,
        eth_filters: Any = None,
        send_raw=None,
        send_tx_obj=None,
        build_sync_status=None,
        reject_auto_sign=None,
    ):
        self.query = query
        self.blockchain = blockchain
        self.mempool = mempool
        self.config = config
        self.evm = evm
        self.p2p = p2p
        self.wallet = wallet
        self.sync_engine = sync_engine
        self.eth_filters = eth_filters
        self._send_raw = send_raw
        self._send_tx_obj = send_tx_obj
        self._build_sync_status = build_sync_status
        self._reject_auto_sign = reject_auto_sign

    def get_stats(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "backend": "rpc_service",
            "port": "RpcPort",
            "tip": self.query.tip_height() if self.query else 0,
        }

    def call_batch(self, requests: Sequence[RpcRequest]) -> List[RpcResponse]:
        max_batch = int(getattr(self.config, "jsonrpc_max_batch", 32) or 32)
        if len(requests) > max_batch:
            return [
                rpc_error(-32600, f"batch too large (max {max_batch})")
            ]
        return [self.call(r) for r in requests]

    def call(self, request: RpcRequest) -> RpcResponse:
        method = request.method
        if not method:
            return rpc_error(-32600, "Invalid Request", request.id)
        dto, err = parse_method_params(method, request.params)
        if err:
            return rpc_error(-32602, err, request.id)
        try:
            result = self._dispatch(method, list(request.params), dto)
            return RpcResponse(ok=True, result=result, id=request.id)
        except QueryLimitError as exc:
            return rpc_error(-32000, str(exc.reason), request.id)
        except QueryTimeoutError as exc:
            return rpc_error(-32000, str(exc.reason), request.id)
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("Method not supported"):
                return rpc_error(-32601, msg, request.id)
            return rpc_error(-32602, msg, request.id)
        except Exception as exc:
            return rpc_error(-32603, str(exc), request.id)

    def _dispatch(self, method: str, params: list, dto: Any = None) -> Any:
        bc = self.blockchain
        mp = self.mempool
        cfg = self.config
        q = self.query
        evm_adapter = self.evm
        p2p = self.p2p
        wallet = self.wallet
        sync_engine = self.sync_engine

        if method == "net_version":
            return str(cfg.chain_id)
        if method == "web3_clientVersion":
            return f"Absolute/{cfg.node_version}/python"
        if method == "net_peerCount":
            count = p2p.peer_count() if p2p else 0
            return hex(count)
        if method == "eth_chainId":
            return hex(cfg.chain_id)

        if method == "eth_mining":
            if not bool(getattr(cfg, "mining_enabled", False)):
                return False
            mode = str(getattr(cfg, "deployment_mode", "dev") or "dev").lower()
            if p2p is None:
                if mode in ("prod", "production", "staging"):
                    return False
                return True
            if not bool(getattr(p2p, "_running", False)):
                return False
            peers = getattr(p2p, "peers", None) or {}
            try:
                connected = len(peers)
            except Exception:
                connected = 0
            min_mesh = int(getattr(cfg, "mesh_min_peers_before_mine", 0) or 0)
            consistent = bool(getattr(p2p, "_state_consistent", False))
            if min_mesh > 0:
                if connected < min_mesh or not consistent:
                    return False
            elif connected > 0 and not consistent:
                return False
            return True

        if method == "eth_syncing":
            if self._build_sync_status:
                status = self._build_sync_status(sync_engine, p2p, bc, cfg)
            else:
                status = {}
            behind = int(status.get("behind", 0) or 0)
            syncing = bool(status.get("syncing", False)) or behind > 0
            peer_n = int(status.get("peers", status.get("p2p_peers", 0)) or 0)
            if peer_n > 0 and not bool(status.get("state_consistent", False)):
                syncing = True
            if peer_n > 0 and not bool(status.get("wire_probe_probed", False)):
                syncing = True
            if peer_n > 0 and status.get("wire_probe_probed") and not bool(
                status.get("wire_probe_ok", False)
            ):
                syncing = True
            if syncing:
                return {
                    "startingBlock": hex(max(0, int(status.get("local_height", 0)) - behind)),
                    "currentBlock": hex(int(status.get("local_height", 0))),
                    "highestBlock": hex(
                        int(status.get("best_peer_height", status.get("local_height", 0)))
                    ),
                }
            return False

        if method == "eth_blockNumber":
            return hex(q.tip_height())

        if method == "eth_getBlockByNumber":
            if isinstance(dto, GetBlockByNumberParams):
                tag, full_tx = dto.tag, dto.full_tx
            else:
                tag = params[0] if params else "latest"
                full_tx = params[1] if len(params) > 1 else False
            blk = q.get_block(BlockQuery(tag=str(tag), full_tx=bool(full_tx)))
            return format_block(blk, bool(full_tx), query=q)

        if method == "eth_getBlockByHash":
            if isinstance(dto, GetBlockByHashParams):
                block_hash, full_tx = dto.block_hash, dto.full_tx
            else:
                err = validate_block_hash_param(tuple(params))
                if err:
                    raise ValueError(err)
                block_hash = params[0]
                full_tx = params[1] if len(params) > 1 else False
            blk = q.get_block(BlockQuery(block_hash=str(block_hash), full_tx=bool(full_tx)))
            return format_block(blk, bool(full_tx), query=q)

        if method == "eth_getBalance":
            if isinstance(dto, GetBalanceParams):
                address = dto.address
            else:
                address = params[0] if params else ""
                if not address:
                    raise ValueError("invalid address")
            balance = q.get_balance(address)
            try:
                return hex(int(to_satoshi(balance or 0)) * WEI_PER_SATOSHI)
            except (TypeError, ValueError):
                return "0x0"

        if method == "eth_getTransactionCount":
            if isinstance(dto, AddressOnlyParams):
                address = dto.address
            else:
                address = params[0] if params else ""
                if not address:
                    raise ValueError("address required")
            return hex(q.get_nonce(address))

        if method == "eth_getCode":
            if isinstance(dto, AddressOnlyParams):
                address = dto.address
            else:
                address = params[0] if params else ""
            account = q.get_account(address)
            if account and account.get("code"):
                return "0x" + str(account["code"]).replace("0x", "")
            return "0x"

        if method == "eth_sendRawTransaction":
            raw = dto.raw_tx if isinstance(dto, SendRawTxParams) else (params[0] if params else "")
            if not self._send_raw:
                raise ValueError("send path unavailable")
            return self._send_raw(raw, bc, mp, cfg)

        if method == "eth_sendTransaction":
            tx_obj = dict(params[0] if params else {})
            if self._reject_auto_sign:
                self._reject_auto_sign(tx_obj, cfg)
            if wallet and not _is_production_cfg(cfg):
                from_addr = str(tx_obj.get("from", "")).lower()
                if from_addr and from_addr == wallet.address.lower() and not tx_obj.get("signature"):
                    tx_obj["auto_sign"] = True
            if not self._send_tx_obj:
                raise ValueError("send path unavailable")
            return self._send_tx_obj(tx_obj, bc, mp, cfg, wallet)

        if method == "eth_getTransactionByHash":
            tx_hash = dto.tx_hash if isinstance(dto, TxHashParams) else (params[0] if params else "")
            return format_tx(q.get_transaction(tx_hash))

        if method == "eth_getTransactionReceipt":
            tx_hash = dto.tx_hash if isinstance(dto, TxHashParams) else (params[0] if params else "")
            tx = q.get_transaction(tx_hash)
            return format_receipt(tx, bc, query=q)

        if method == "eth_call":
            from api.eth_format import encode_eth_call_return

            tx_obj = params[0] if params else {}
            to_addr = tx_obj.get("to", "")
            data = tx_obj.get("data", tx_obj.get("input", ""))
            if evm_adapter and to_addr:
                result = evm_adapter.static_call(to_addr, data)
                if result.success and result.return_value is not None:
                    return encode_eth_call_return(result.return_value)
            return "0x"

        if method == "eth_estimateGas":
            tx_obj = params[0] if params else {}
            to_addr = tx_obj.get("to", "") or ""
            data = tx_obj.get("data", tx_obj.get("input", ""))
            # Create txs omit `to`; still estimate via adapter when present.
            if evm_adapter and (to_addr or data):
                gas = evm_adapter.estimate_gas(to_addr, data)
                return hex(max(21_000, int(gas or 0)))
            return hex(21_000)

        if method == "eth_gasPrice":
            try:
                return hex(abs_to_wei(getattr(cfg, "gas_price_wei", 0) or 0))
            except (TypeError, ValueError):
                return "0x0"

        if method == "eth_maxPriorityFeePerGas":
            return hex(int(getattr(cfg, "priority_fee_wei", 0) or 0))

        if method == "eth_feeHistory":
            return format_fee_history(
                query=q,
                cfg=cfg,
                block_count=params[0] if params else 1,
                newest_tag=params[1] if len(params) > 1 else "latest",
            )

        if method == "eth_accounts":
            if wallet and getattr(wallet, "address", ""):
                return [wallet.address]
            miner = getattr(cfg, "miner_address", "") or ""
            return [miner] if miner else []

        if method == "eth_coinbase":
            return getattr(cfg, "miner_address", "") or "0x0"

        if method == "eth_hashrate":
            return "0x0"

        if method == "eth_protocolVersion":
            return hex(65)

        if method == "eth_getStorageAt":
            if isinstance(dto, GetStorageAtParams):
                address, slot_raw = dto.address, dto.slot
            else:
                address = params[0] if params else ""
                slot_raw = params[1] if len(params) > 1 else "0x0"
            slot = int(slot_raw, 16) if str(slot_raw).startswith("0x") else int(slot_raw)
            account = q.get_account(address)
            storage: Dict[str, Any] = {}
            if account and account.get("storage"):
                raw = account["storage"]
                if isinstance(raw, dict):
                    storage = raw
                else:
                    text = raw if isinstance(raw, str) else str(raw)
                    if text.strip():
                        try:
                            storage = json.loads(text)
                        except (TypeError, ValueError, json.JSONDecodeError) as exc:
                            raise ValueError("corrupt account storage") from exc
            val = storage.get(str(slot), storage.get(slot, 0))
            return hex(int(val or 0))

        if method == "eth_getBlockTransactionCountByHash":
            err = validate_block_hash_param(tuple(params))
            if err:
                raise ValueError(err)
            blk = q.get_block(BlockQuery(block_hash=str(params[0])))
            if not blk:
                return hex(0)
            txs = blk.get("transactions", [])
            return hex(len(txs) if isinstance(txs, list) else int(blk.get("tx_count", 0) or 0))

        if method == "eth_getTransactionByBlockNumberAndIndex":
            tag = params[0] if params else "latest"
            idx = (
                int(params[1], 16)
                if len(params) > 1 and str(params[1]).startswith("0x")
                else int(params[1] if len(params) > 1 else 0)
            )
            blk = q.get_block(BlockQuery(tag=str(tag)))
            return format_tx(tx_at_block_index(bc, blk, idx, query=q))

        if method == "eth_getTransactionByBlockHashAndIndex":
            err = validate_block_hash_param(tuple(params))
            if err:
                raise ValueError(err)
            idx = (
                int(params[1], 16)
                if len(params) > 1 and str(params[1]).startswith("0x")
                else int(params[1] if len(params) > 1 else 0)
            )
            blk = q.get_block(BlockQuery(block_hash=str(params[0])))
            return format_tx(tx_at_block_index(bc, blk, idx, query=q))

        if method in ("eth_getUncleCountByBlockNumber", "eth_getUncleCountByBlockHash"):
            return hex(0)

        if method == "eth_getLogs":
            if isinstance(dto, GetLogsParams):
                filt = {
                    "fromBlock": dto.from_block,
                    "toBlock": dto.to_block,
                    "topics": list(dto.topics),
                    "limit": dto.limit,
                }
                if dto.address is not None:
                    filt["address"] = (
                        list(dto.address) if isinstance(dto.address, tuple) else dto.address
                    )
            else:
                filt = params[0] if params else {}
                if not isinstance(filt, dict):
                    raise ValueError("eth_getLogs expects object filter")
            return handle_eth_get_logs(filt, bc, query=q)

        filters = self.eth_filters
        if method == "eth_newFilter":
            filt = params[0] if params else {}
            if not isinstance(filt, dict):
                raise ValueError("eth_newFilter expects object filter")
            if not filters:
                raise ValueError("eth filters unavailable")
            return filters.new_log_filter(filt, bc)

        if method == "eth_newBlockFilter":
            if not filters:
                raise ValueError("eth filters unavailable")
            return filters.new_block_filter(bc)

        if method == "eth_newPendingTransactionFilter":
            if not filters:
                raise ValueError("eth filters unavailable")
            return filters.new_pending_filter(mp)

        if method == "eth_getFilterChanges":
            if not filters:
                raise ValueError("eth filters unavailable")
            filter_id = params[0] if params else ""

            def _logs(f, b):
                return handle_eth_get_logs(f, b, query=q)

            return filters.get_filter_changes(filter_id, bc, mp, _logs)

        if method == "eth_getFilterLogs":
            if not filters:
                raise ValueError("eth filters unavailable")
            filter_id = params[0] if params else ""

            def _logs(f, b):
                return handle_eth_get_logs(f, b, query=q)

            return filters.get_filter_logs(filter_id, bc, _logs)

        if method == "eth_uninstallFilter":
            if not filters:
                raise ValueError("eth filters unavailable")
            return filters.uninstall(params[0] if params else "")

        if method == "eth_getMempoolSize":
            return hex(mp.get_size() if mp else 0)

        if method == "eth_getBlockTransactionCountByNumber":
            tag = params[0] if params else "latest"
            blk = q.get_block(BlockQuery(tag=str(tag)))
            if not blk:
                return hex(0)
            txs = blk.get("transactions", [])
            count = len(txs) if isinstance(txs, list) else int(blk.get("tx_count", 0) or 0)
            return hex(count)

        raise ValueError(f"Method not supported: {method}")


def build_rpc_service(
    blockchain,
    mempool,
    config,
    *,
    query=None,
    evm=None,
    p2p=None,
    wallet=None,
    sync_engine=None,
    eth_filters=None,
) -> RpcService:
    from api.query_facade import QueryFacade
    from api.query_executor import QueryExecutor

    if query is None:
        executor = QueryExecutor(
            workers=int(getattr(config, "rpc_heavy_workers", 2) or 2),
            default_timeout_ms=int(
                getattr(config, "rpc_heavy_query_timeout_ms", 5000) or 5000
            ),
        )
        query = QueryFacade(blockchain, config, executor=executor)

    # Late-bind send helpers from http to avoid circular import at module load
    from api import http as http_mod

    return RpcService(
        query=query,
        blockchain=blockchain,
        mempool=mempool,
        config=config,
        evm=evm,
        p2p=p2p,
        wallet=wallet,
        sync_engine=sync_engine,
        eth_filters=eth_filters,
        send_raw=http_mod._handle_send_tx,
        send_tx_obj=http_mod._handle_send_tx_with_wallet,
        build_sync_status=http_mod._build_sync_status,
        reject_auto_sign=http_mod._reject_auto_sign_in_prod,
    )
