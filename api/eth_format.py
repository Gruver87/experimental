# api/eth_format.py — ADR 0011 WS-safe eth formatters (no RESTHandler)
"""Block/tx/receipt/log formatting shared by JSON-RPC and WebSocket."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from api.ports import BlockQuery, LogsQuery, QueryLimitError, QueryTimeoutError
from runtime.amount import WEI_PER_SATOSHI, abs_to_wei, to_satoshi


def _keccak(data: bytes) -> bytes:
    try:
        from crypto import native

        return native.keccak256_digest(data)
    except Exception:
        import hashlib

        # Fallback only for environments without native keccak (not Ethereum-accurate).
        return hashlib.sha3_256(data).digest()


def _addr_bytes(addr: str) -> bytes:
    a = str(addr or "").strip().lower().replace("0x", "")
    if len(a) != 40:
        a = a.zfill(40)[-40:]
    return bytes.fromhex(a)


def _topic_bytes(topic: str) -> bytes:
    t = str(topic or "").strip().lower().replace("0x", "")
    if len(t) > 64:
        t = t[-64:]
    return bytes.fromhex(t.zfill(64))


EMPTY_LOGS_BLOOM = "0x" + ("0" * 512)
ZERO_ROOT = "0x" + ("0" * 64)
ETH_BLOCK_GAS_LIMIT = 30_000_000


def _as_eth_root(value: str) -> str:
    """Normalize a 32-byte hex digest to 0x-prefixed RPC form."""
    s = str(value or "").strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    if len(s) != 64 or any(c not in "0123456789abcdef" for c in s):
        raise ValueError(f"invalid merkle root encoding: {value!r}")
    return "0x" + s


def _abs_tx_merkle_root(items: List[str]) -> str:
    """Absolute SHA256 merkle (same as Block.tx_root). Not Ethereum Hexary MPT."""
    from crypto.merkle import merkle_root

    cleaned = [str(x) for x in items if str(x)]
    raw = merkle_root(cleaned) if cleaned else merkle_root(["empty"])
    return _as_eth_root(raw)


def _tx_hash_from_block_item(tx: Any) -> str:
    if isinstance(tx, dict):
        return str(tx.get("hash") or tx.get("tx_hash") or "")
    return str(tx or "")


def block_transactions_root(blk: Dict[str, Any]) -> str:
    """RPC transactionsRoot: stored Block.tx_root, else merkle of tx hashes.

    Empty blocks use merkle_root(['empty']) — the same leaf as core.Block.
    This is not geth Hexary MPT; wallets must not treat it as Ethereum-identical.
    """
    stored = blk.get("tx_root") or blk.get("transactions_root") or blk.get("transactionsRoot")
    if stored:
        try:
            return _as_eth_root(str(stored))
        except ValueError:
            pass
    txs = blk.get("transactions") or []
    hashes = []
    if isinstance(txs, list):
        for tx in txs:
            h = _tx_hash_from_block_item(tx)
            if h:
                hashes.append(h)
    return _abs_tx_merkle_root(hashes)


def block_receipts_root(blk: Dict[str, Any]) -> str:
    """RPC receiptsRoot: stored receipts_root, else merkle of hash:status leaves.

    Status comes from tx rows already on the block (no extra receipt scan).
    Empty / hash-only lists follow the same empty merkle as transactionsRoot.
    Not Ethereum Hexary MPT.
    """
    stored = blk.get("receipts_root") or blk.get("receiptsRoot")
    if stored:
        try:
            return _as_eth_root(str(stored))
        except ValueError:
            pass
    txs = blk.get("transactions") or []
    leaves: List[str] = []
    if isinstance(txs, list):
        for tx in txs:
            if isinstance(tx, dict):
                h = str(tx.get("hash") or tx.get("tx_hash") or "")
                if not h:
                    continue
                try:
                    status = int(tx.get("status") or 0)
                except (TypeError, ValueError):
                    status = 0
                leaves.append(f"{h}:{status}")
            else:
                s = str(tx or "")
                if s:
                    leaves.append(s)
    return _abs_tx_merkle_root(leaves)


def logs_bloom(logs: Sequence[Dict[str, Any]]) -> str:
    """Compute Ethereum logsBloom (256 bytes / 2048 bits) from formatted logs.

    Wave-8: receipt-level bloom from address + topics (Yellow Paper / geth parity).
    Block-level bloom is the same OR over every log in the block.
    """
    bloom = bytearray(256)
    for log in logs or ():
        if not isinstance(log, dict):
            continue
        addr = log.get("address") or log.get("contract_address") or ""
        if addr:
            _bloom_add(bloom, _addr_bytes(str(addr)))
        topics = log.get("topics") or []
        if isinstance(topics, (list, tuple)):
            for topic in topics:
                if topic is None or topic == "":
                    continue
                _bloom_add(bloom, _topic_bytes(str(topic)))
    return "0x" + bloom.hex()


def _logs_for_block(height: int, query=None, bc=None) -> List[Dict[str, Any]]:
    """Load raw EVM log rows for one height via QueryFacadePort (ADR 0011)."""
    facade = query
    if facade is not None and hasattr(facade, "get_evm_logs_by_block"):
        rows = facade.get_evm_logs_by_block(int(height))
        return list(rows) if rows else []
    if bc is not None:
        qf = getattr(bc, "query_facade", None)
        if qf is not None and hasattr(qf, "get_evm_logs_by_block"):
            rows = qf.get_evm_logs_by_block(int(height))
            return list(rows) if rows else []
    return []


def _block_height(blk: Dict[str, Any]) -> int:
    height = blk.get("height", blk.get("block_height"))
    if height is not None:
        try:
            return int(height)
        except (TypeError, ValueError):
            return 0
    num = blk.get("number")
    if isinstance(num, str) and num.startswith(("0x", "0X")):
        try:
            return int(num, 16)
        except ValueError:
            return 0
    if num is not None:
        try:
            return int(num)
        except (TypeError, ValueError):
            return 0
    return 0


def block_logs_bloom(blk: Dict[str, Any], query=None, bc=None) -> str:
    """Yellow Paper block logsBloom: OR of address+topics for all logs in the block.

    Prefers a non-zero stored header field (future apply-path persist). Otherwise
    reconstructs from the log index through QueryFacadePort — not getLogs caps.
    Missing query yields the empty bloom (honest: no logs observed).
    """
    stored = blk.get("logsBloom") or blk.get("logs_bloom")
    if stored:
        s = str(stored).strip().lower()
        hexpart = s[2:] if s.startswith("0x") else s
        if len(hexpart) == 512 and any(c != "0" for c in hexpart):
            return "0x" + hexpart
    return logs_bloom(_logs_for_block(_block_height(blk), query=query, bc=bc))


def _bloom_add(bloom: bytearray, data: bytes) -> None:
    h = _keccak(data)
    for i in (0, 2, 4):
        bit_index = ((h[i] << 8) | h[i + 1]) & 2047
        byte_index = 255 - (bit_index // 8)
        bloom[byte_index] |= 1 << (bit_index % 8)


def block_sha3_uncles(blk: Dict[str, Any]) -> str:
    """Yellow Paper sha3Uncles: keccak256(rlp([])) when the uncle list is empty.

    Absolute has no uncle headers. A non-empty `uncles` field is hashed with
    Absolute SHA256 merkle (same as tx_root) — not a geth uncle trie.
    Never return the zero digest for an empty list (that is not keccak(0xc0)).
    """
    uncles = blk.get("uncles") or []
    if isinstance(uncles, list) and uncles:
        hashes: List[str] = []
        for uncle in uncles:
            if isinstance(uncle, dict):
                h = str(uncle.get("hash") or uncle.get("block_hash") or "")
            else:
                h = str(uncle or "")
            if h:
                hashes.append(h)
        return _abs_tx_merkle_root(hashes)
    from crypto import native

    digest = native.keccak256_digest(b"\xc0")
    return "0x" + digest.hex()


def format_block(
    blk: Optional[Dict],
    full_tx: bool = False,
    *,
    query=None,
    bc=None,
) -> Optional[Dict]:
    if not blk:
        return None
    if blk.get("_full_tx_truncated"):
        full_tx = False
    state_root = blk.get("state_root", "") or ""
    if state_root and not str(state_root).startswith("0x"):
        state_root = "0x" + str(state_root)
    txs = blk.get("transactions", [])
    tx_hashes = [
        tx.get("hash", "") if isinstance(tx, dict) else str(tx)
        for tx in (txs if isinstance(txs, list) else [])
    ]
    return {
        "number": hex(blk.get("height", 0)),
        "hash": blk.get("hash", blk.get("block_hash", "")),
        "parentHash": blk.get("parent_hash", ""),
        "nonce": "0x0000000000000000",
        "sha3Uncles": block_sha3_uncles(blk),
        "logsBloom": block_logs_bloom(blk, query=query, bc=bc),
        "transactionsRoot": block_transactions_root(blk),
        "stateRoot": state_root or ZERO_ROOT,
        "receiptsRoot": block_receipts_root(blk),
        "miner": blk.get("miner", blk.get("proposer", "")),
        "difficulty": "0x0",
        "totalDifficulty": "0x0",
        "extraData": "0x",
        "size": hex(256 + len(tx_hashes) * 32),
        "gasLimit": hex(ETH_BLOCK_GAS_LIMIT),
        "gasUsed": hex(block_gas_used(blk, query=query, bc=bc)),
        "timestamp": hex(blk.get("timestamp", 0)),
        "uncles": [],
        "transactions": txs if full_tx else tx_hashes,
        "totalBurned": blk.get("total_burned", 0.0),
        "txCount": blk.get("tx_count", len(tx_hashes)),
    }


def format_tx(tx: Optional[Dict]) -> Optional[Dict]:
    if not tx:
        return None
    try:
        wei = int(to_satoshi(tx.get("value", tx.get("amount", 0)) or 0)) * WEI_PER_SATOSHI
    except (TypeError, ValueError):
        wei = 0
    return {
        "hash": tx.get("hash", tx.get("tx_hash", "")),
        "blockNumber": hex(tx.get("block_height", 0)),
        "from": tx.get("from_addr", tx.get("from", "")),
        "to": tx.get("to_addr", tx.get("to", "")),
        "value": hex(wei),
        "gas": hex(tx.get("gas", 21000)),
        "gasUsed": hex(tx.get("gas_used", tx.get("gas", 21000))),
        "nonce": hex(tx.get("nonce", 0)),
        "input": tx.get("data", tx.get("tx_data", "0x")),
        "burned": tx.get("burned", 0.0),
    }


def resolve_block_tag_to_height(bc_or_query, tag) -> int:
    tip_fn = getattr(bc_or_query, "tip_height", None)
    get_height = getattr(bc_or_query, "get_height", None)
    if tag in (None, "", "earliest"):
        return 0
    if tag in ("latest", "pending"):
        if callable(tip_fn):
            return int(tip_fn())
        if callable(get_height):
            return int(get_height())
        return 0
    try:
        return int(tag, 16) if str(tag).startswith("0x") else int(tag)
    except (TypeError, ValueError):
        return 0


def normalize_log_data(data) -> str:
    raw = str(data or "")
    if not raw or raw == "0x":
        return "0x"
    return raw if raw.startswith("0x") else "0x" + raw


def tx_index_in_block(bc, block_height: int, tx_hash: str) -> int:
    if not bc or not tx_hash:
        return 0
    blk = None
    get_block = getattr(bc, "get_block", None)
    if callable(get_block):
        try:
            blk = bc.get_block(BlockQuery(height=int(block_height)))
        except TypeError:
            blk = bc.get_block(int(block_height))
        except Exception:
            blk = None
    if not blk:
        return 0
    txs = blk.get("transactions", [])
    if not isinstance(txs, list):
        return 0
    target = tx_hash.lower()
    for idx, entry in enumerate(txs):
        if isinstance(entry, dict):
            h = str(entry.get("hash", entry.get("tx_hash", ""))).lower()
        else:
            h = str(entry).lower()
        if h == target:
            return idx
    return 0


def _block_at_height(height: int, query=None, bc=None) -> Optional[Dict[str, Any]]:
    src = query if query is not None else bc
    if src is None:
        return None
    get_block = getattr(src, "get_block", None)
    if not callable(get_block):
        return None
    try:
        blk = get_block(BlockQuery(height=int(height)))
    except TypeError:
        try:
            blk = get_block(int(height))
        except Exception:
            return None
    except Exception:
        return None
    return blk if isinstance(blk, dict) else None


def _tx_entry_hash_and_gas(entry: Any, query=None, bc=None) -> Optional[tuple[str, int]]:
    """Hash + gas_used for a block tx slot. None if the slot cannot be observed."""
    if isinstance(entry, dict):
        h = str(entry.get("hash") or entry.get("tx_hash") or "").lower()
        if not h:
            return None
        if entry.get("gas_used") is not None or entry.get("gas") is not None:
            try:
                used = int(entry.get("gas_used", entry.get("gas", 0)) or 0)
            except (TypeError, ValueError):
                used = 0
            return h, used
    else:
        h = str(entry or "").lower()
        if not h:
            return None
    get_tx = None
    if query is not None and hasattr(query, "get_transaction"):
        get_tx = query.get_transaction
    elif bc is not None and hasattr(bc, "get_transaction"):
        get_tx = bc.get_transaction
    if not callable(get_tx):
        return None
    row = get_tx(h)
    if not isinstance(row, dict):
        return None
    try:
        used = int(row.get("gas_used", row.get("gas", 0)) or 0)
    except (TypeError, ValueError):
        used = 0
    return h, used


def _sum_block_tx_gas(blk: Dict[str, Any], query=None, bc=None) -> Optional[int]:
    """Sum gas_used of every tx in block list order. None if any slot is unobserved."""
    txs = blk.get("transactions")
    if not isinstance(txs, list) or not txs:
        return None
    total = 0
    for entry in txs[:10_000]:
        parsed = _tx_entry_hash_and_gas(entry, query=query, bc=bc)
        if parsed is None:
            return None
        total += parsed[1]
    return total


def block_gas_used(blk: Optional[Dict[str, Any]], query=None, bc=None) -> int:
    """Block gasUsed: reconstructed from observed tx gas, else stored header.

    Incomplete or empty tx lists do not invent a total. Prefer the apply-path
    `gas_used` field when reconstruction is not possible. Last-receipt
    `cumulativeGasUsed` matches this value when the full list is observed.
    """
    if not blk:
        return 0
    reconstructed = _sum_block_tx_gas(blk, query=query, bc=bc)
    if reconstructed is not None:
        return reconstructed
    stored = blk.get("gas_used")
    if stored is None:
        return 0
    try:
        return max(0, int(stored))
    except (TypeError, ValueError):
        return 0


def format_fee_history(
    *,
    query,
    cfg,
    block_count: Any = 1,
    newest_tag: Any = "latest",
) -> Dict[str, Any]:
    """EIP-1559 feeHistory from observed heights. No stubbed 0.5 ratios.

    Arrays cover existing heights `oldest..tip` only (not padded to the
    requested count). `gasUsedRatio` is `gasUsed / ETH_BLOCK_GAS_LIMIT`.
    `reward` stays `[["0x0"]]` — Absolute is not an EIP-1559 tip market.
    """
    if isinstance(block_count, bool):
        n_req = 1
    elif isinstance(block_count, int):
        n_req = block_count
    else:
        raw = str(block_count or "1").strip() or "1"
        try:
            n_req = int(raw, 16) if raw.startswith(("0x", "0X")) else int(raw)
        except (TypeError, ValueError):
            n_req = 1
    n_req = max(1, min(int(n_req), 1024))
    get_block = getattr(query, "get_block", None)
    tip = None
    if callable(get_block):
        try:
            tip = get_block(BlockQuery(tag=str(newest_tag or "latest")))
        except Exception:
            tip = None
    tip_fn = getattr(query, "tip_height", None)
    if isinstance(tip, dict):
        try:
            tip_h = int(tip.get("height", tip_fn() if callable(tip_fn) else 0) or 0)
        except (TypeError, ValueError):
            tip_h = int(tip_fn()) if callable(tip_fn) else 0
    else:
        tip_h = int(tip_fn()) if callable(tip_fn) else 0
    oldest = max(0, tip_h - n_req + 1)
    try:
        base = hex(abs_to_wei(getattr(cfg, "gas_price_wei", 0) or 0))
    except (TypeError, ValueError):
        base = "0x0"
    ratios: List[float] = []
    for height in range(oldest, tip_h + 1):
        blk = None
        if callable(get_block):
            try:
                blk = get_block(BlockQuery(height=int(height)))
            except Exception:
                blk = None
        used = block_gas_used(blk, query=query) if isinstance(blk, dict) else 0
        ratios.append(min(1.0, max(0.0, used / float(ETH_BLOCK_GAS_LIMIT))))
    n = len(ratios)
    return {
        "oldestBlock": hex(oldest),
        "baseFeePerGas": [base] * n,
        "gasUsedRatio": ratios,
        "reward": [["0x0"]] * n,
    }


def receipt_cumulative_gas_used(tx: Dict[str, Any], query=None, bc=None) -> int:
    """Sum gas_used of txs in block order up to and including `tx`.

    Without a block listing, returns this receipt's gas only (honest: no siblings
    observed). Incomplete prior slots do not invent a running total.
    """
    try:
        own = int(tx.get("gas_used", tx.get("gas", 21000)) or 21000)
    except (TypeError, ValueError):
        own = 21000
    tx_hash = str(tx.get("hash") or tx.get("tx_hash") or "").lower()
    if not tx_hash:
        return own
    try:
        height = int(tx.get("block_height", tx.get("blockNumber", 0)) or 0)
    except (TypeError, ValueError):
        return own
    blk = _block_at_height(height, query=query, bc=bc)
    if not blk:
        return own
    txs = blk.get("transactions")
    if not isinstance(txs, list) or not txs:
        return own
    total = 0
    for entry in txs[:10_000]:
        parsed = _tx_entry_hash_and_gas(entry, query=query, bc=bc)
        if parsed is None:
            return own
        h, used = parsed
        total += used
        if h == tx_hash:
            return total
    return own


def format_eth_log(row: Dict, bc=None) -> Dict:
    block_height = int(row.get("block_height", 0))
    block_hash = ""
    if bc is not None:
        blk = None
        get_block = getattr(bc, "get_block", None)
        if callable(get_block):
            try:
                blk = bc.get_block(BlockQuery(height=block_height))
            except TypeError:
                try:
                    blk = bc.get_block(block_height)
                except Exception:
                    blk = None
            except Exception:
                blk = None
        if blk:
            block_hash = blk.get("hash", blk.get("block_hash", ""))
    tx_hash = row.get("tx_hash", "")
    topics = row.get("topics", [])
    if not isinstance(topics, list):
        topics = []
    return {
        "removed": False,
        "logIndex": hex(int(row.get("log_index", 0))),
        "transactionIndex": hex(tx_index_in_block(bc, block_height, tx_hash)),
        "transactionHash": tx_hash,
        "blockHash": block_hash,
        "blockNumber": hex(block_height),
        "address": row.get("contract_address", ""),
        "data": normalize_log_data(row.get("data", "")),
        "topics": topics,
    }


def encode_eth_call_return(value: Any) -> str:
    """Encode eth_call return as 0x-hex (ABI word for ints; raw hex for bytes)."""
    if value is None:
        return "0x"
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return "0x"
        if s.startswith("0x") or s.startswith("0X"):
            return "0x" + s[2:]
        return "0x" + s
    if isinstance(value, bool):
        return "0x" + ("1" if value else "0").zfill(64)
    if isinstance(value, int):
        if value < 0:
            raise ValueError("eth_call negative int unsupported")
        return "0x" + format(value, "x").zfill(64)
    return "0x"


def format_receipt(tx: Optional[Dict], bc=None, query=None) -> Optional[Dict]:
    if not tx:
        return None
    from storage.database import Database

    tx_hash = tx.get("hash", tx.get("tx_hash", ""))
    logs: List[Dict] = []
    facade = query
    if facade is not None and hasattr(facade, "get_evm_logs_by_tx"):
        rows = facade.get_evm_logs_by_tx(tx_hash)
        logs = [format_eth_log(row, facade) for row in rows]
    elif bc is not None and getattr(bc, "query_facade", None) is not None:
        rows = bc.query_facade.get_evm_logs_by_tx(tx_hash)
        logs = [format_eth_log(row, bc.query_facade) for row in rows]
    status_i = Database._normalize_tx_status(tx.get("status"))
    gas_used = int(tx.get("gas_used", tx.get("gas", 21000)) or 21000)
    to_addr = tx.get("to_addr", tx.get("to", "")) or None
    contract = tx.get("contract_address") or None
    try:
        stored_index = int(tx.get("tx_index", tx.get("index", 0)) or 0)
    except (TypeError, ValueError):
        stored_index = 0
    tx_index = stored_index
    try:
        height = int(tx.get("block_height", 0) or 0)
    except (TypeError, ValueError):
        height = 0
    blk = _block_at_height(height, query=facade, bc=bc)
    txs = blk.get("transactions") if isinstance(blk, dict) else None
    if isinstance(txs, list) and tx_hash:
        want = str(tx_hash).lower()
        for i, entry in enumerate(txs):
            if isinstance(entry, dict):
                h = str(entry.get("hash") or entry.get("tx_hash") or "").lower()
            else:
                h = str(entry).lower()
            if h == want:
                tx_index = i
                break
    cumulative = receipt_cumulative_gas_used(tx, query=facade, bc=bc)
    return {
        "transactionHash": tx_hash,
        "transactionIndex": hex(int(tx_index)),
        "blockNumber": hex(tx.get("block_height", 0)),
        "blockHash": tx.get("block_hash", tx.get("blockHash", "0x" + "0" * 64)),
        "from": tx.get("from_addr", tx.get("from", "")),
        "to": to_addr,
        "cumulativeGasUsed": hex(int(cumulative)),
        "gasUsed": hex(gas_used),
        "contractAddress": contract,
        "logs": logs,
        "logsBloom": logs_bloom(logs),
        "status": hex(status_i),
        "type": hex(int(tx.get("type", 0) or 0)),
        "effectiveGasPrice": hex(int(tx.get("gas_price", tx.get("gasPrice", 0)) or 0)),
        "burned": tx.get("burned", 0.0),
    }


def handle_eth_get_logs(filt: Dict, bc=None, query=None) -> List[Dict]:
    from api.ports import NullQueryFacade

    facade = query
    if facade is None and bc is not None:
        facade = getattr(bc, "query_facade", None)
    # Unattached Blockchain defaults to NullQueryFacade — fall through to db.
    if isinstance(facade, NullQueryFacade):
        facade = None

    height_src = facade or bc
    from_block = resolve_block_tag_to_height(height_src, filt.get("fromBlock", "0x0"))
    to_block = resolve_block_tag_to_height(height_src, filt.get("toBlock", "latest"))
    if to_block < from_block:
        return []

    address = filt.get("address")
    addresses: tuple = ()
    if address:
        addresses = tuple(address if isinstance(address, list) else [address])
    topics = filt.get("topics")
    topics_t = tuple(topics) if isinstance(topics, list) else ()

    if facade is not None and hasattr(facade, "query_logs"):
        q = LogsQuery(
            from_block=from_block,
            to_block=to_block,
            addresses=addresses,
            topics=topics_t,
            limit=int(filt.get("limit") or 1000),
        )
        try:
            rows = facade.query_logs(q)
        except (QueryLimitError, QueryTimeoutError):
            raise
        return [format_eth_log(row, facade) for row in rows]

    store = getattr(bc, "db", None) if bc is not None else None
    if store is None or not hasattr(store, "query_evm_logs"):
        return []
    rows = store.query_evm_logs(
        from_block=from_block,
        to_block=to_block,
        addresses=list(addresses) if addresses else None,
        topics=list(topics_t) if topics_t else None,
    )
    return [format_eth_log(row, bc) for row in rows]


def resolve_block_by_tag(bc, tag: str, query=None) -> Optional[Dict]:
    facade = query or (getattr(bc, "query_facade", None) if bc else None)
    if facade is not None:
        return facade.get_block(BlockQuery(tag=str(tag or "latest")))
    if not bc:
        return None
    if tag in ("latest", "pending"):
        return bc.get_last_block()
    try:
        height = int(tag, 16) if str(tag).startswith("0x") else int(tag)
        return bc.get_block(height)
    except (TypeError, ValueError):
        return None


def tx_at_block_index(bc, blk: Optional[Dict], index: int, query=None) -> Optional[Dict]:
    facade = query or (getattr(bc, "query_facade", None) if bc else None)
    if not blk or index < 0:
        return None
    txs = blk.get("transactions", [])
    if not isinstance(txs, list) or index >= len(txs):
        return None
    entry = txs[index]
    if isinstance(entry, dict):
        return entry
    tx_hash = str(entry)
    if facade is not None:
        return facade.get_transaction(tx_hash)
    if bc is not None and hasattr(bc, "get_transaction"):
        return bc.get_transaction(tx_hash)
    return None


# Compat aliases
_format_block = format_block
_format_tx = format_tx
_format_receipt = format_receipt
_handle_eth_get_logs = handle_eth_get_logs
_resolve_block_by_tag = resolve_block_by_tag
_format_eth_log = format_eth_log
