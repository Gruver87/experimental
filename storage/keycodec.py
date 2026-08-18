#!/usr/bin/env python3
"""Binary key encoding for RocksDB chain storage."""

from __future__ import annotations

import struct
from functools import wraps
from typing import Iterable, List, Tuple


_native = None
_native_checked = False


def _n():
    """Return the cached native module, if it can be imported."""
    global _native, _native_checked
    if not _native_checked:
        try:
            import abs_native
        except Exception:  # pragma: no cover - depends on local wheel install
            _native = None
        else:
            _native = abs_native
        _native_checked = True
    return _native


def native_keycodec_available() -> bool:
    native = _n()
    return native is not None and hasattr(native, "rocks_key_account")

# Column-family style single-DB prefixes
P_BLOCK_HEIGHT = b"\x01"
P_BLOCK_HASH = b"\x02"
P_BLOCK_TX = b"\x03"
P_TX = b"\x04"
P_TX_RECEIPT = b"\x05"
P_ACCOUNT = b"\x10"
P_VALIDATOR = b"\x20"
P_META = b"\x40"
P_BURN = b"\x41"
P_PROPOSER_AUDIT = b"\x42"
P_STATE_ROOT_MM = b"\x43"
P_TX_PROP = b"\x44"
P_TX_FROM = b"\x06"
P_TX_TO = b"\x07"
P_TX_RECENT = b"\x08"
P_BRIDGE_LOCK = b"\x50"
P_BRIDGE_CREDIT = b"\x51"
P_EVM_LOG = b"\x52"
P_EVM_LOG_TX = b"\x53"
P_NFT_TOKEN = b"\x54"
P_NFT_OFFER = b"\x55"
P_NFT_AUCTION = b"\x56"
P_NFT_SALE = b"\x57"


def pack_u32(value: int) -> bytes:
    return struct.pack(">I", int(value) & 0xFFFFFFFF)


def unpack_u32(data: bytes) -> int:
    if len(data) != 4:
        raise ValueError("invalid u32 key segment")
    return struct.unpack(">I", data)[0]


def pack_u64(value: int) -> bytes:
    return struct.pack(">Q", int(value) & 0xFFFFFFFFFFFFFFFF)


def unpack_u64(data: bytes) -> int:
    if len(data) != 8:
        raise ValueError("invalid u64 key segment")
    return struct.unpack(">Q", data)[0]


def normalize_hash_key(block_hash: str) -> bytes:
    h = (block_hash or "").strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if len(h) != 64:
        raise ValueError(f"invalid block hash key: {block_hash!r}")
    return bytes.fromhex(h)


def key_block_height(height: int) -> bytes:
    return P_BLOCK_HEIGHT + pack_u64(height)


def key_block_hash_to_height(block_hash: str) -> bytes:
    return P_BLOCK_HASH + normalize_hash_key(block_hash)


def key_tx(tx_hash: str) -> bytes:
    h = (tx_hash or "").strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    return P_TX + bytes.fromhex(h.zfill(64)[-64:])


def key_block_tx(height: int, tx_hash: str) -> bytes:
    return P_BLOCK_TX + pack_u64(height) + key_tx(tx_hash)[1:]


def _tx_hash_body(tx_hash: str) -> bytes:
    return key_tx(tx_hash)[len(P_TX) :]


def key_tx_from_index(address: str, block_height: int, tx_hash: str) -> bytes:
    return (
        P_TX_FROM
        + normalize_address_key(address).encode("utf-8")
        + pack_u64(int(block_height))
        + _tx_hash_body(tx_hash)
    )


def key_tx_to_index(address: str, block_height: int, tx_hash: str) -> bytes:
    return (
        P_TX_TO
        + normalize_address_key(address).encode("utf-8")
        + pack_u64(int(block_height))
        + _tx_hash_body(tx_hash)
    )


def prefix_tx_from(address: str) -> bytes:
    return P_TX_FROM + normalize_address_key(address).encode("utf-8")


def prefix_tx_to(address: str) -> bytes:
    return P_TX_TO + normalize_address_key(address).encode("utf-8")


def key_tx_recent_index(block_height: int, timestamp: int, tx_hash: str) -> bytes:
    inv_h = (1 << 64) - 1 - int(block_height)
    inv_ts = (1 << 64) - 1 - int(timestamp)
    return P_TX_RECENT + pack_u64(inv_h) + pack_u64(inv_ts) + _tx_hash_body(tx_hash)


def prefix_tx_recent() -> bytes:
    return P_TX_RECENT


def key_tx_prop(tx_hash: str, stage: str) -> bytes:
    return P_TX_PROP + _tx_hash_body(tx_hash) + (stage or "").encode("utf-8")[:16]


def prefix_tx_prop(tx_hash: str) -> bytes:
    return P_TX_PROP + _tx_hash_body(tx_hash)


def prefix_tx_prop_all() -> bytes:
    return P_TX_PROP


def key_bridge_lock(tx_hash: str) -> bytes:
    return P_BRIDGE_LOCK + _tx_hash_body(tx_hash)


def key_bridge_credit(credit_key: str) -> bytes:
    ck = (credit_key or "").strip().lower().replace("0x", "")
    return P_BRIDGE_CREDIT + bytes.fromhex(ck.zfill(64)[-64:])


def prefix_bridge_locks() -> bytes:
    return P_BRIDGE_LOCK


def prefix_bridge_credits() -> bytes:
    return P_BRIDGE_CREDIT


def key_evm_log(block_height: int, tx_hash: str, log_index: int) -> bytes:
    return (
        P_EVM_LOG
        + pack_u64(int(block_height))
        + _tx_hash_body(tx_hash)
        + pack_u32(int(log_index))
    )


def key_evm_log_tx(tx_hash: str, log_index: int) -> bytes:
    return P_EVM_LOG_TX + _tx_hash_body(tx_hash) + pack_u32(int(log_index))


def prefix_evm_logs() -> bytes:
    return P_EVM_LOG


def prefix_evm_logs_block(height: int) -> bytes:
    """Inclusive start of logs at `height` (P_EVM_LOG || u64 height)."""
    return P_EVM_LOG + pack_u64(int(height))


def prefix_family_end(prefix: bytes) -> bytes:
    """Exclusive end of a one-byte key family (next prefix byte)."""
    if not prefix:
        raise ValueError("empty prefix family")
    return bytes([(prefix[0] + 1) & 0xFF])


def prefix_evm_logs_tx(tx_hash: str) -> bytes:
    return P_EVM_LOG_TX + _tx_hash_body(tx_hash)


def key_nft_token(token_id: str) -> bytes:
    tid = (token_id or "").strip().encode("utf-8")
    return P_NFT_TOKEN + pack_u32(len(tid)) + tid


def prefix_nft_tokens() -> bytes:
    return P_NFT_TOKEN


def key_nft_offer(offer_id: str) -> bytes:
    oid = (offer_id or "").strip().encode("utf-8")
    return P_NFT_OFFER + pack_u32(len(oid)) + oid


def prefix_nft_offers() -> bytes:
    return P_NFT_OFFER


def key_nft_auction(auction_id: str) -> bytes:
    aid = (auction_id or "").strip().encode("utf-8")
    return P_NFT_AUCTION + pack_u32(len(aid)) + aid


def prefix_nft_auctions() -> bytes:
    return P_NFT_AUCTION


def key_nft_sale(created_at: int, seq: int) -> bytes:
    inv_ts = (1 << 64) - 1 - int(created_at)
    return P_NFT_SALE + pack_u64(inv_ts) + pack_u64(int(seq))


def prefix_nft_sales() -> bytes:
    return P_NFT_SALE


def normalize_address_key(address: str) -> str:
    """Match SQLite Database._normalize_address (arbitrary labels allowed)."""
    return (address or "").strip().lower()


def key_account(address: str) -> bytes:
    # Genesis pools use symbolic keys (0xecosystem..., treasury, mining_pool).
    return P_ACCOUNT + normalize_address_key(address).encode("utf-8")


def key_validator(address: str) -> bytes:
    return P_VALIDATOR + normalize_address_key(address).encode("utf-8")


def key_meta(name: str) -> bytes:
    return P_META + name.encode("utf-8")


def key_burn(height: int) -> bytes:
    return P_BURN + pack_u64(height)


def key_proposer_audit(height: int) -> bytes:
    return P_PROPOSER_AUDIT + pack_u64(height)


def prefix_block_heights() -> bytes:
    return P_BLOCK_HEIGHT


def prefix_accounts() -> bytes:
    return P_ACCOUNT


def prefix_validators() -> bytes:
    return P_VALIDATOR


def iter_prefix_keys(rows: Iterable[Tuple[bytes, bytes]], prefix: bytes) -> List[Tuple[bytes, bytes]]:
    out: List[Tuple[bytes, bytes]] = []
    for key, value in rows:
        if not key.startswith(prefix):
            break
        out.append((key, value))
    return out


_NATIVE_INTEGER_ARGS = {
    "rocks_pack_u32": ((0, "value", 0xFFFFFFFF),),
    "rocks_pack_u64": ((0, "value", 0xFFFFFFFFFFFFFFFF),),
    "rocks_key_block_height": ((0, "height", 0xFFFFFFFFFFFFFFFF),),
    "rocks_key_block_tx": ((0, "height", 0xFFFFFFFFFFFFFFFF),),
    "rocks_key_tx_from_index": ((1, "block_height", 0xFFFFFFFFFFFFFFFF),),
    "rocks_key_tx_to_index": ((1, "block_height", 0xFFFFFFFFFFFFFFFF),),
    "rocks_key_tx_recent_index": (
        (0, "block_height", 0xFFFFFFFFFFFFFFFF),
        (1, "timestamp", 0xFFFFFFFFFFFFFFFF),
    ),
    "rocks_key_evm_log": (
        (0, "block_height", 0xFFFFFFFFFFFFFFFF),
        (2, "log_index", 0xFFFFFFFF),
    ),
    "rocks_key_evm_log_tx": ((1, "log_index", 0xFFFFFFFF),),
    "rocks_key_nft_sale": (
        (0, "created_at", 0xFFFFFFFFFFFFFFFF),
        (1, "seq", 0xFFFFFFFFFFFFFFFF),
    ),
    "rocks_key_burn": ((0, "height", 0xFFFFFFFFFFFFFFFF),),
    "rocks_key_proposer_audit": ((0, "height", 0xFFFFFFFFFFFFFFFF),),
}


def _prefer_native(function, native_name: str, *, returns_bytes: bool = True):
    @wraps(function)
    def encoded(*args, **kwargs):
        native = _n()
        if native is None or not hasattr(native, "rocks_key_account"):
            return function(*args, **kwargs)

        native_args = list(args)
        native_kwargs = dict(kwargs)
        for index, name, mask in _NATIVE_INTEGER_ARGS.get(native_name, ()):
            if index < len(native_args):
                native_args[index] = int(native_args[index]) & mask
            elif name in native_kwargs:
                native_kwargs[name] = int(native_kwargs[name]) & mask

        result = getattr(native, native_name)(*native_args, **native_kwargs)
        return bytes(result) if returns_bytes else result

    return encoded


_NATIVE_CODECS = {
    "pack_u32": "rocks_pack_u32",
    "unpack_u32": "rocks_unpack_u32",
    "pack_u64": "rocks_pack_u64",
    "unpack_u64": "rocks_unpack_u64",
    "normalize_hash_key": "rocks_normalize_hash_key",
    "key_block_height": "rocks_key_block_height",
    "key_block_hash_to_height": "rocks_key_block_hash_to_height",
    "key_tx": "rocks_key_tx",
    "key_block_tx": "rocks_key_block_tx",
    "key_tx_from_index": "rocks_key_tx_from_index",
    "key_tx_to_index": "rocks_key_tx_to_index",
    "prefix_tx_from": "rocks_prefix_tx_from",
    "prefix_tx_to": "rocks_prefix_tx_to",
    "key_tx_recent_index": "rocks_key_tx_recent_index",
    "prefix_tx_recent": "rocks_prefix_tx_recent",
    "key_tx_prop": "rocks_key_tx_prop",
    "prefix_tx_prop": "rocks_prefix_tx_prop",
    "prefix_tx_prop_all": "rocks_prefix_tx_prop_all",
    "key_bridge_lock": "rocks_key_bridge_lock",
    "key_bridge_credit": "rocks_key_bridge_credit",
    "prefix_bridge_locks": "rocks_prefix_bridge_locks",
    "prefix_bridge_credits": "rocks_prefix_bridge_credits",
    "key_evm_log": "rocks_key_evm_log",
    "key_evm_log_tx": "rocks_key_evm_log_tx",
    "prefix_evm_logs": "rocks_prefix_evm_logs",
    "prefix_evm_logs_tx": "rocks_prefix_evm_logs_tx",
    "key_nft_token": "rocks_key_nft_token",
    "prefix_nft_tokens": "rocks_prefix_nft_tokens",
    "key_nft_offer": "rocks_key_nft_offer",
    "prefix_nft_offers": "rocks_prefix_nft_offers",
    "key_nft_auction": "rocks_key_nft_auction",
    "prefix_nft_auctions": "rocks_prefix_nft_auctions",
    "key_nft_sale": "rocks_key_nft_sale",
    "prefix_nft_sales": "rocks_prefix_nft_sales",
    "key_account": "rocks_key_account",
    "key_validator": "rocks_key_validator",
    "key_meta": "rocks_key_meta",
    "key_burn": "rocks_key_burn",
    "key_proposer_audit": "rocks_key_proposer_audit",
    "prefix_block_heights": "rocks_prefix_block_heights",
    "prefix_accounts": "rocks_prefix_accounts",
    "prefix_validators": "rocks_prefix_validators",
}

for _python_name, _native_name in _NATIVE_CODECS.items():
    globals()[_python_name] = _prefer_native(
        globals()[_python_name],
        _native_name,
        returns_bytes=_python_name not in {"unpack_u32", "unpack_u64"},
    )

normalize_address_key = _prefer_native(
    normalize_address_key,
    "rocks_normalize_address_key",
    returns_bytes=False,
)
