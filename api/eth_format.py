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
ZERO_HASH = "0x" + ("0" * 64)
ETH_BLOCK_GAS_LIMIT = 30_000_000


def _normalize_block_hash(value: Any) -> Optional[str]:
    """Return a non-zero 0x-hash, or None if missing / all-zero stub."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not s.startswith(("0x", "0X")):
        s = "0x" + s
    hexpart = s[2:]
    if not hexpart or any(c not in "0123456789abcdefABCDEF" for c in hexpart):
        return None
    if all(c == "0" for c in hexpart):
        return None
    return s


def observed_block_hash(
    tx: Optional[Dict[str, Any]] = None,
    blk: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Block hash from the tx row or block listing. Never the 32-byte zero stub."""
    if isinstance(tx, dict):
        h = _normalize_block_hash(tx.get("block_hash") or tx.get("blockHash"))
        if h:
            return h
    if isinstance(blk, dict):
        h = _normalize_block_hash(blk.get("hash") or blk.get("block_hash") or blk.get("blockHash"))
        if h:
            return h
    return None


def observed_parent_hash(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Parent hash from the header. Genesis may be the 32-byte zero digest.

    Missing parent on a non-genesis block is None — not an empty string and not
    an invented zero hash (that would look like genesis).
    """
    if not isinstance(blk, dict):
        return None
    raw = blk.get("parent_hash")
    if raw is None or str(raw).strip() == "":
        raw = blk.get("parentHash")
    if raw is not None and str(raw).strip() != "":
        try:
            return _as_eth_root(str(raw))
        except ValueError:
            return None
    height = _as_int_height(blk.get("height", blk.get("block_height", blk.get("number"))))
    if height == 0:
        return ZERO_HASH
    return None


def observed_state_root(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Stored state root. Never the 32-byte zero stub (not Absolute empty merkle)."""
    if not isinstance(blk, dict):
        return None
    raw = blk.get("state_root") or blk.get("stateRoot")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        out = _as_eth_root(str(raw))
    except ValueError:
        return None
    if out == ZERO_ROOT:
        return None
    return out


def burned_satoshi(row: Optional[Dict[str, Any]], key: str = "burned") -> int:
    """ABS burn as integer satoshi. Missing/unparseable is 0, never a float."""
    if not isinstance(row, dict):
        return 0
    raw = row.get(key)
    if raw is None and key == "total_burned":
        raw = row.get("totalBurned")
    try:
        return int(to_satoshi(raw or 0))
    except (TypeError, ValueError):
        return 0


def observed_block_nonce(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Ethereum header nonce is 8 bytes. Absolute is not ethash.

    Missing is JSON null — never the 8-byte zero stub. A bare integer ``nonce``
    on the block dict is not used (that field is a tx/account nonce elsewhere).
    """
    if not isinstance(blk, dict):
        return None
    raw = blk.get("block_nonce")
    if raw is None or str(raw).strip() == "":
        raw = blk.get("nonce")
        # Integer nonce on a block row is ambiguous with tx.nonce — refuse.
        if isinstance(raw, int) and "block_nonce" not in blk:
            return None
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith(("0x", "0X")):
            hexpart = s[2:]
            if len(hexpart) == 16 and all(c in "0123456789abcdefABCDEF" for c in hexpart):
                return "0x" + hexpart.lower()
            return None
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 0 or n >= 1 << 64:
        return None
    return "0x" + format(n, "016x")


def observed_block_size(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Stored encoded size only. Never invent 256 + 32 * tx_count (not RLP)."""
    if not isinstance(blk, dict):
        return None
    raw = blk.get("size", blk.get("block_size"))
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, str) and str(raw).startswith(("0x", "0X")):
            n = int(raw, 16)
        else:
            n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return hex(n)


def observed_miner(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Proposer from the header. Missing is null — never '' or the 20-byte zero address."""
    if not isinstance(blk, dict):
        return None
    raw = blk.get("miner")
    if raw is None or str(raw).strip() == "":
        raw = blk.get("proposer")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    hexpart = s[2:] if s.startswith(("0x", "0X")) else s
    if hexpart and all(c in "0123456789abcdefABCDEF" for c in hexpart):
        if all(c == "0" for c in hexpart):
            return None
        return "0x" + hexpart.lower()
    return s


def observed_block_timestamp(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    """Unix timestamp from the header. Missing is null, never epoch 0."""
    if not isinstance(blk, dict):
        return None
    if "timestamp" in blk:
        raw = blk.get("timestamp")
    elif "time" in blk:
        raw = blk.get("time")
    else:
        return None
    if raw is None or raw == "":
        return None
    n = _as_int_height(raw)
    if n is None or n < 0:
        return None
    return hex(n)


def observed_uint(row: Optional[Dict[str, Any]], *keys: str) -> Optional[int]:
    """First present non-empty integer field. Missing is None — 0 is valid if stored."""
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key not in row:
            continue
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        n = _as_int_height(raw)
        if n is None or n < 0:
            return None
        return n
    return None


def observed_uint_hex(row: Optional[Dict[str, Any]], *keys: str) -> Optional[str]:
    n = observed_uint(row, *keys)
    if n is None:
        return None
    return hex(n)


def observed_tx_address(
    row: Optional[Dict[str, Any]],
    *keys: str,
    allow_zero: bool = False,
) -> Optional[str]:
    """Address from a tx/receipt row. Missing/empty is null, not ''."""
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key not in row:
            continue
        raw = row.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        s = str(raw).strip()
        hexpart = s[2:] if s.startswith(("0x", "0X")) else s
        if hexpart and all(c in "0123456789abcdefABCDEF" for c in hexpart):
            if not allow_zero and all(c == "0" for c in hexpart):
                return None
            return "0x" + hexpart.lower()
        return s
    return None


def observed_tx_hash(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """Tx hash from the row. Missing/empty/all-zero is null, not ''."""
    if not isinstance(row, dict):
        return None
    raw = row.get("hash") or row.get("tx_hash") or row.get("transactionHash")
    if raw is None or str(raw).strip() == "":
        return None
    s = str(raw).strip()
    if not s.startswith(("0x", "0X")):
        s = "0x" + s
    hexpart = s[2:]
    if not hexpart or any(c not in "0123456789abcdefABCDEF" for c in hexpart):
        return None
    if all(c == "0" for c in hexpart):
        return None
    return s


def observed_value_hex(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """ABS value as wei hex. Missing is null; stored 0 is 0x0."""
    if not isinstance(row, dict):
        return None
    if "value" not in row and "amount" not in row:
        return None
    raw = row.get("value")
    if raw is None or raw == "":
        raw = row.get("amount")
    if raw is None or raw == "":
        return None
    try:
        wei = int(to_satoshi(raw or 0)) * WEI_PER_SATOSHI
    except (TypeError, ValueError):
        return None
    return hex(wei)


def observed_receipt_status(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """Receipt status 0x0/0x1 from a stored field. Missing is null, not reverted."""
    if not isinstance(row, dict) or "status" not in row:
        return None
    from storage.database import Database

    return hex(int(Database._normalize_tx_status(row.get("status"))))


def _as_int_height(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, str) and str(value).startswith(("0x", "0X")):
            return int(value, 16)
        return int(value)
    except (TypeError, ValueError):
        return None


def observed_block_number(
    tx: Optional[Dict[str, Any]] = None,
    blk: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Inclusion height from the block listing or tx row. Missing is None, not 0."""
    if isinstance(blk, dict):
        n = _as_int_height(blk.get("height", blk.get("block_height", blk.get("number"))))
        if n is not None:
            return n
    if not isinstance(tx, dict):
        return None
    if tx.get("block_height") is None and tx.get("blockNumber") is None:
        return None
    return _as_int_height(tx.get("block_height", tx.get("blockNumber")))


def block_extra_data(blk: Dict[str, Any]) -> str:
    """RPC extraData from the stored header. Empty / missing is `0x`, not invented text."""
    raw = blk.get("extra_data")
    if raw is None:
        raw = blk.get("extraData")
    if raw is None or raw == "":
        return "0x"
    s = str(raw)
    if s.startswith(("0x", "0X")):
        hexpart = s[2:]
        if not hexpart:
            return "0x"
        if any(c not in "0123456789abcdefABCDEF" for c in hexpart):
            return "0x" + s.encode("utf-8").hex()
        return "0x" + hexpart.lower()
    return "0x" + s.encode("utf-8").hex()


def block_uncle_hashes(blk: Optional[Dict[str, Any]]) -> List[str]:
    """Observed uncle hashes. Absolute has none; never invent a list."""
    if not isinstance(blk, dict):
        return []
    uncles = blk.get("uncles") or []
    if not isinstance(uncles, list):
        return []
    hashes: List[str] = []
    for uncle in uncles:
        if isinstance(uncle, dict):
            h = str(uncle.get("hash") or uncle.get("block_hash") or "")
        else:
            h = str(uncle or "")
        if h:
            hashes.append(h)
    return hashes


def block_transaction_count(blk: Optional[Dict[str, Any]]) -> Optional[int]:
    """Tx count for an observed block. None if the block was not found."""
    if not isinstance(blk, dict) or not blk:
        return None
    txs = blk.get("transactions")
    if isinstance(txs, list):
        return len(txs)
    if blk.get("tx_count") is not None:
        try:
            return int(blk.get("tx_count") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def format_block_tx_count(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    n = block_transaction_count(blk)
    return hex(n) if n is not None else None


def format_uncle_count(blk: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(blk, dict) or not blk:
        return None
    return hex(len(block_uncle_hashes(blk)))


def _rpc_index(raw: Any) -> Optional[int]:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return int(raw)
    s = str(raw if raw is not None else "0").strip() or "0"
    try:
        return int(s, 16) if s.startswith(("0x", "0X")) else int(s)
    except (TypeError, ValueError):
        return None


def format_uncle_by_index(
    blk: Optional[Dict[str, Any]],
    index: Any,
    *,
    query=None,
    bc=None,
) -> Optional[Dict[str, Any]]:
    """Uncle header at index, or None.

    Missing parent block, out-of-range index, or a hash-only uncle without a
    stored header → JSON null. Never invent a block object from a hash.
    """
    if not isinstance(blk, dict) or not blk:
        return None
    idx = _rpc_index(index)
    if idx is None or idx < 0:
        return None
    uncles = blk.get("uncles") or []
    if not isinstance(uncles, list) or idx >= len(uncles):
        return None
    entry = uncles[idx]
    if isinstance(entry, dict) and (
        entry.get("height") is not None
        or entry.get("parent_hash")
        or entry.get("transactions") is not None
        or entry.get("state_root")
        or entry.get("miner")
        or entry.get("proposer")
    ):
        return format_block(entry, False, query=query, bc=bc)
    if isinstance(entry, dict):
        uncle_hash = str(entry.get("hash") or entry.get("block_hash") or "")
    else:
        uncle_hash = str(entry or "")
    if not uncle_hash:
        return None
    src = query if query is not None else bc
    if src is None:
        return None
    get_block = getattr(src, "get_block", None)
    if not callable(get_block):
        return None
    try:
        found = get_block(BlockQuery(block_hash=str(uncle_hash)))
    except TypeError:
        try:
            found = get_block(uncle_hash)
        except Exception:
            return None
    except Exception:
        return None
    if not isinstance(found, dict) or not found:
        return None
    return format_block(found, False, query=query, bc=bc)


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
    hashes = block_uncle_hashes(blk)
    if hashes:
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
    txs = blk.get("transactions", [])
    tx_hashes = [
        tx.get("hash", "") if isinstance(tx, dict) else str(tx)
        for tx in (txs if isinstance(txs, list) else [])
    ]
    number = _as_int_height(blk.get("height", blk.get("block_height", blk.get("number"))))
    used = block_gas_used(blk, query=query, bc=bc)
    return {
        "number": hex(number) if number is not None else None,
        "hash": observed_block_hash(blk=blk),
        "parentHash": observed_parent_hash(blk),
        "nonce": observed_block_nonce(blk),
        "sha3Uncles": block_sha3_uncles(blk),
        "logsBloom": block_logs_bloom(blk, query=query, bc=bc),
        "transactionsRoot": block_transactions_root(blk),
        "stateRoot": observed_state_root(blk),
        "receiptsRoot": block_receipts_root(blk),
        "miner": observed_miner(blk),
        "difficulty": "0x0",
        "totalDifficulty": "0x0",
        "extraData": block_extra_data(blk),
        "size": observed_block_size(blk),
        "gasLimit": hex(ETH_BLOCK_GAS_LIMIT),
        "gasUsed": hex(used) if used is not None else None,
        "timestamp": observed_block_timestamp(blk),
        "uncles": block_uncle_hashes(blk),
        "transactions": txs if full_tx else tx_hashes,
        "totalBurned": burned_satoshi(blk, "total_burned"),
        "txCount": blk.get("tx_count", len(tx_hashes)),
    }


def format_tx(tx: Optional[Dict], *, query=None, bc=None) -> Optional[Dict]:
    if not tx:
        return None
    lookup_hash = str(tx.get("hash") or tx.get("tx_hash") or "")
    height = observed_uint(tx, "block_height", "blockNumber")
    blk = _block_at_height(height, query=query, bc=bc) if height is not None else None
    try:
        stored_index = int(tx.get("tx_index", tx.get("index", 0)) or 0)
        have_stored_index = (
            tx.get("tx_index") is not None or tx.get("index") is not None
        )
    except (TypeError, ValueError):
        stored_index = 0
        have_stored_index = False
    listing_index = _tx_index_in_listing(lookup_hash, blk)
    if listing_index is not None:
        tx_index: Optional[int] = listing_index
    elif have_stored_index:
        tx_index = stored_index
    else:
        tx_index = None
    number = observed_block_number(tx, blk)
    return {
        "hash": observed_tx_hash(tx),
        "blockNumber": hex(number) if number is not None else None,
        "blockHash": observed_block_hash(tx, blk),
        "transactionIndex": hex(int(tx_index)) if tx_index is not None else None,
        "from": observed_tx_address(tx, "from_addr", "from"),
        "to": observed_tx_address(tx, "to_addr", "to", allow_zero=True),
        "value": observed_value_hex(tx),
        "gas": observed_uint_hex(tx, "gas", "gas_limit"),
        "gasPrice": observed_uint_hex(tx, "gas_price", "gasPrice"),
        "gasUsed": observed_uint_hex(tx, "gas_used", "gasUsed"),
        "nonce": observed_uint_hex(tx, "nonce"),
        "input": tx.get("data", tx.get("tx_data", "0x")),
        "type": observed_uint_hex(tx, "type"),
        "burned": burned_satoshi(tx, "burned"),
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


def tx_index_in_block(bc, block_height: int, tx_hash: str) -> Optional[int]:
    if not bc or not tx_hash:
        return None
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
        return None
    txs = blk.get("transactions", [])
    if not isinstance(txs, list):
        return None
    target = tx_hash.lower()
    for idx, entry in enumerate(txs):
        if isinstance(entry, dict):
            h = str(entry.get("hash", entry.get("tx_hash", ""))).lower()
        else:
            h = str(entry).lower()
        if h == target:
            return idx
    return None


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


def _tx_index_in_listing(tx_hash: Any, blk: Optional[Dict[str, Any]]) -> Optional[int]:
    """Index of `tx_hash` in block tx order, or None if the slot is not observed."""
    if not blk or not tx_hash:
        return None
    txs = blk.get("transactions")
    if not isinstance(txs, list) or not txs:
        return None
    want = str(tx_hash).lower()
    for i, entry in enumerate(txs):
        if isinstance(entry, dict):
            h = str(entry.get("hash") or entry.get("tx_hash") or "").lower()
        else:
            h = str(entry).lower()
        if h == want:
            return i
    return None


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


def block_gas_used(blk: Optional[Dict[str, Any]], query=None, bc=None) -> Optional[int]:
    """Block gasUsed: reconstructed from observed tx gas, else stored header.

    Incomplete lists do not invent a total. An observed empty tx list with no
    stored header is 0. Missing both is None — never a fake empty-block 0x0.
    """
    if not blk:
        return None
    reconstructed = _sum_block_tx_gas(blk, query=query, bc=bc)
    if reconstructed is not None:
        return reconstructed
    stored = blk.get("gas_used")
    if stored is not None:
        try:
            return max(0, int(stored))
        except (TypeError, ValueError):
            return None
    txs = blk.get("transactions")
    if isinstance(txs, list) and not txs:
        return 0
    return None


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
        used = block_gas_used(blk, query=query) if isinstance(blk, dict) else None
        if used is None:
            used = 0
        ratios.append(min(1.0, max(0.0, used / float(ETH_BLOCK_GAS_LIMIT))))
    n = len(ratios)
    return {
        "oldestBlock": hex(oldest),
        "baseFeePerGas": [base] * n,
        "gasUsedRatio": ratios,
        "reward": [["0x0"]] * n,
    }


def receipt_cumulative_gas_used(tx: Dict[str, Any], query=None, bc=None) -> Optional[int]:
    """Sum gas_used of txs in block order up to and including `tx`.

    Without a block listing, returns this receipt's observed gas_used. Missing
    gas_used is None — never the 21000 transfer stub. Incomplete prior slots
    do not invent a running total.
    """
    own = observed_uint(tx, "gas_used", "gasUsed")
    if own is None:
        return None
    tx_hash = str(tx.get("hash") or tx.get("tx_hash") or "").lower()
    if not tx_hash:
        return own
    height = observed_uint(tx, "block_height", "blockNumber")
    if height is None:
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


def format_eth_log(row: Dict, bc=None, query=None) -> Dict:
    facade = query if query is not None else bc
    number = observed_block_number(row)
    blk = _block_at_height(number, query=facade, bc=bc) if number is not None else None
    raw_hash = row.get("tx_hash") or row.get("transactionHash") or row.get("transaction_hash")
    tx_hash = str(raw_hash).strip() if raw_hash is not None and str(raw_hash).strip() else None
    topics = row.get("topics", [])
    if not isinstance(topics, list):
        topics = []
    listing_index = _tx_index_in_listing(tx_hash, blk) if tx_hash else None
    tx_index = listing_index
    if tx_index is None:
        tx_index = observed_uint(row, "tx_index", "transactionIndex")
    if tx_index is None and number is not None and tx_hash:
        tx_index = tx_index_in_block(facade, number, tx_hash)
    return {
        "removed": False,
        "logIndex": observed_uint_hex(row, "log_index", "logIndex"),
        "transactionIndex": hex(int(tx_index)) if tx_index is not None else None,
        "transactionHash": tx_hash,
        "blockHash": observed_block_hash(row, blk),
        "blockNumber": hex(number) if number is not None else None,
        "address": observed_tx_address(row, "contract_address", "address", allow_zero=True),
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
    tx_hash = str(tx.get("hash") or tx.get("tx_hash") or "")
    logs: List[Dict] = []
    facade = query
    if facade is not None and hasattr(facade, "get_evm_logs_by_tx"):
        rows = facade.get_evm_logs_by_tx(tx_hash)
        logs = [format_eth_log(row, facade) for row in rows]
    elif bc is not None and getattr(bc, "query_facade", None) is not None:
        rows = bc.query_facade.get_evm_logs_by_tx(tx_hash)
        logs = [format_eth_log(row, bc.query_facade) for row in rows]
    gas_used = observed_uint(tx, "gas_used", "gasUsed")
    to_addr = observed_tx_address(tx, "to_addr", "to", allow_zero=True)
    contract = tx.get("contract_address") or None
    try:
        stored_index = int(tx.get("tx_index", tx.get("index", 0)) or 0)
        have_stored_index = (
            tx.get("tx_index") is not None or tx.get("index") is not None
        )
    except (TypeError, ValueError):
        stored_index = 0
        have_stored_index = False
    tx_index: Optional[int] = stored_index if have_stored_index else None
    height = observed_uint(tx, "block_height", "blockNumber")
    blk = _block_at_height(height, query=facade, bc=bc) if height is not None else None
    listing_index = _tx_index_in_listing(tx_hash, blk)
    if listing_index is not None:
        tx_index = listing_index
    elif have_stored_index:
        tx_index = stored_index
    else:
        tx_index = None
    cumulative = receipt_cumulative_gas_used(tx, query=facade, bc=bc)
    number = observed_block_number(tx, blk)
    return {
        "transactionHash": observed_tx_hash(tx),
        "transactionIndex": hex(int(tx_index)) if tx_index is not None else None,
        "blockNumber": hex(number) if number is not None else None,
        "blockHash": observed_block_hash(tx, blk),
        "from": observed_tx_address(tx, "from_addr", "from"),
        "to": to_addr,
        "cumulativeGasUsed": hex(int(cumulative)) if cumulative is not None else None,
        "gasUsed": hex(int(gas_used)) if gas_used is not None else None,
        "contractAddress": contract,
        "logs": logs,
        "logsBloom": logs_bloom(logs),
        "status": observed_receipt_status(tx),
        "type": observed_uint_hex(tx, "type"),
        "effectiveGasPrice": observed_uint_hex(tx, "gas_price", "gasPrice"),
        "burned": burned_satoshi(tx, "burned"),
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
