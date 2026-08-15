# crypto/native.py
"""
Native crypto facade for Absolute Blockchain.

This module routes hot deterministic crypto kernels to the PyO3/maturin
extension when it is installed. The Python path is kept byte-for-byte aligned
with the historical implementation so consensus behavior does not drift.
"""

import hashlib
import json
import math
import os
from typing import Any, List, Optional


from runtime.native_capabilities import (
    NativeFamily,
    bootstrap_native_capabilities,
    get_registry,
    resolve_native_mode,
)

_MODE = resolve_native_mode()
_DISABLE_NATIVE = _MODE == "off"
_REQUIRE_NATIVE = _MODE == "require"

_native_error: Optional[BaseException] = None
_native = None

try:
    _registry = bootstrap_native_capabilities()
    _native = _registry.module()
    if _native is None and _registry.status().get("import_error"):
        _native_error = RuntimeError(str(_registry.status()["import_error"]))
except Exception as exc:  # pragma: no cover - require mode / import
    _native_error = exc
    if _REQUIRE_NATIVE:
        raise

_NATIVE_REQUIRED_MSG = (
    "ABS_NATIVE_MODE=require (or ABS_REQUIRE_NATIVE_CRYPTO): abs_native kernel required "
    "(pip install -e native/abs_native)"
)


def _require_native_kernel(kernel: str = "abs_native") -> None:
    if _REQUIRE_NATIVE and _native is None:
        raise RuntimeError(_NATIVE_REQUIRED_MSG)


def _use_rust(family: NativeFamily) -> bool:
    return get_registry().use_rust(family)


def _demote(family: NativeFamily, reason: str) -> None:
    get_registry().demote(family, reason)


def native_available() -> bool:
    """True when abs_native module loaded (any family may still be demoted)."""
    return get_registry().module() is not None


def native_error() -> Optional[BaseException]:
    return _native_error


def native_capabilities_status() -> dict:
    """ADR 0009 per-family backend map for /health."""
    return get_registry().status()


def native_crypto_status(required: bool = False) -> dict:
    caps = get_registry().status()
    status = {
        "available": native_available(),
        "required": bool(required or _REQUIRE_NATIVE),
        "mode": caps.get("mode", resolve_native_mode()),
        "self_test": False,
        "error": str(_native_error) if _native_error else "",
        "capabilities": caps.get("families", {}),
        "kernels": [
            "sha256",
            "sha256_batch",
            "hash_text",
            "hash_text_batch",
            "block_header_hash",
            "block_header_hash_batch",
            "transaction_hash",
            "transaction_hash_batch",
            "block_canonical_hash",
            "block_canonical_hash_batch",
            "canonical_hash_json",
            "keccak256",
            "keccak256_digest_batch",
            "evm_u256",
            "evm_u256_cmp",
            "evm_u256_sgt",
            "evm_memory",
            "evm_read_push",
            "evm_jumpdest",
            "evm_call_gas",
            "evm_stack",
            "evm_memory_slice",
            "evm_bytecode_scan",
            "evm_keccak256_memory",
            "evm_pure_runner",
            "evm_run_until_halt",
            "evm_host_snapshot_storage",
            "evm_host_restore_storage",
            "evm_plan_nested_call_effects",
            "evm_plan_nested_call_writeback",
            "evm_plan_create_writeback",
            "evm_apply_writeback_ops",
            "evm_plan_nested_call_gas",
            "evm_decode_nested_call_frame",
            "evm_run_nested_pure_frame",
            "evm_run_nested_host_frame",
            "account_storage_map_from_raw",
            "account_view_from_blob",
            "account_view_from_json",
            "evm_bytecode_is_nested_native_eligible",
            "evm_deploy_address",
            "evm_create2_eip1014",
            "validate_imported_block_chain",
            "validate_peer_header_chain",
            "consensus_stake_weighted_proposer",
            "consensus_fisher_yates_committee",
            "ghost_select_head",
            "ghost_cumulative_weight",
            "ghost_chain_from_head",
            "lmd_compute_weights",
            "blockchain_apply_simple_block",
            "blockchain_apply_host_effects",
            "blockchain_replay_simple_blocks",
            "ffg_threshold",
            "ffg_evaluate_epoch",
            "ffg_accumulate_vote",
            "ffg_best_checkpoint",
            "fe_epoch",
            "fe_quorum_reached",
            "fe_can_finalize",
            "slash_check_double_vote",
            "slash_check_double_proposal",
            "decode_eth_raw_tx",
            "decode_eth_raw_tx_hex",
            "rocks_key_account",
            "rocks_pack_u64",
            "rocks_key_block_height",
            "P2PRateLimitTable",
            "P2PConnectionGovernor",
            "P2PLineFramer",
            "P2PNativeConn",
            "P2PNativeListener",
            "p2p_native_transport_available",
            "p2p_native_tls_available",
            "p2p_native_clamp_batch",
            "p2p_native_clamp_chunk",
            "p2p_native_clamp_timeout_ms",
            "p2p_native_connect",
            "p2p_frame_feed_once",
            "p2p_subnet_key",
            "p2p_ip_is_public",
            "p2p_peer_addr_is_dialable",
            "p2p_rate_limit_is_exempt",
            "p2p_rate_limit_tick",
            "p2p_strike_should_ban",
            "p2p_ingress_admit",
            "p2p_ingress_cost_units",
            "p2p_egress_admit",
            "p2p_egress_cost_units",
            "p2p_egress_prepare",
            "validator_selection_proposer",
            "validator_selection_proposer_weighted",
            "validator_selection_committee",
            "validator_selection_shuffle",
            "state_engine_root_from_accounts_json",
            "parse_p2p_wire_line",
            "encode_p2p_wire_message",
            "hash_sorted_json",
            "verify_attestation_secp256k1",
            "validate_p2p_status_payload",
            "validate_p2p_attestation_payload",
            "validate_p2p_block_announce",
            "validate_p2p_state_root_request",
            "validate_p2p_state_root_response",
            "validate_p2p_handshake_payload",
            "validate_p2p_get_blocks_payload",
            "validate_p2p_wire_tx",
            "validate_p2p_mempool_batch",
            "validate_p2p_validator_register",
            "validate_p2p_peers_list",
            "validate_p2p_get_block",
            "validate_p2p_get_block_by_hash",
            "validate_p2p_blocks_batch",
            "verify_p2p_blocks_response_semantics",
            "verify_p2p_block_response_semantics",
            "verify_p2p_state_root_response_request_semantics",
            "verify_p2p_status_height_head_binding",
            "verify_p2p_handshake_head_semantics",
            "validate_p2p_cross_shard_tx",
            "validate_p2p_cross_shard_ack",
            "validate_p2p_shard_migration",
            "amount_to_satoshi",
            "amount_apply_delta_satoshi",
            "state_engine_apply_transactions",
            "plan_transfer_fees",
            "plan_transfer_fees_satoshi",
            "can_afford_transfer",
            "merkle",
            "state_root",
            "secp256k1_verify",
            "consensus_hash",
            "hash_chain_validation",
            "rlp_encode",
            "rlp_decode",
            "rlp_decode_single",
        ],
    }
    if _native is None:
        return status
    try:
        ok = (
            sha256_hex(b"absolute")
            == "747355bdc2a224032fd405b1b9e8985bfca47e45b34668f7d0a70ee4789bd855"
        )
        ok = ok and merkle_root(["tx1", "tx2", "tx3"]) == _python_merkle_root_strings([
            "tx1",
            "tx2",
            "tx3",
        ])
        ok = ok and state_root_from_accounts_json("[]") == _python_state_root_from_accounts([])
        ok = ok and keccak256_hex(b"") == (
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
        )
        if _native is not None and hasattr(_native, "rlp_encode"):
            from crypto.rlp import decode_single, encode

            sample = [0, 1, 255, 256]
            ok = ok and decode_single(encode(sample)) == [
                b"",
                b"\x01",
                b"\xff",
                b"\x01\x00",
            ]
        if _native is not None and hasattr(_native, "evm_run_until_halt"):
            bc = bytes([0x60, 0x02, 0x60, 0x03, 0x01, 0x00])
            table = evm_build_jumpdest_table(bc)
            seg = evm_run_until_halt(
                bc,
                0,
                1_000_000,
                0,
                [],
                bytearray(),
                table,
                b"",
                b"",
                {
                    "address": 0,
                    "caller": 0,
                    "origin": 0,
                    "value": 0,
                    "timestamp": 0,
                    "block_number": 0,
                    "chain_id": 0,
                },
            )
            ok = ok and seg.get("stop_reason") == "halt" and seg.get("stack") == [5]
        status["self_test"] = bool(ok)
    except Exception as exc:
        status["error"] = str(exc)
    return status


def _string_items(items: List[Any]) -> List[str]:
    return [str(item) for item in items]


def hash_data(data: Any) -> str:
    """Hash data exactly like the historical Merkle implementation."""
    return sha256_hex(str(data).encode())


def hash_text(text: str) -> str:
    """SHA-256 of UTF-8 text through the native kernel when available."""
    if _native is not None and hasattr(_native, "hash_text"):
        return str(_native.hash_text(text))
    return sha256_hex(text.encode())


def hash_text_batch(items: List[str]) -> List[str]:
    """Batch SHA-256 of UTF-8 strings, preserving legacy per-item hashes."""
    if _native is not None and hasattr(_native, "hash_text_batch"):
        return [str(value) for value in _native.hash_text_batch(items)]
    return sha256_hex_batch([item.encode() for item in items])


def block_header_hash(
    number: int,
    parent_hash: str,
    proposer: str,
    state_root: str,
    tx_root: str,
    timestamp: int,
    extra_data: str = "",
) -> str:
    """Legacy consensus header hash (single header)."""
    if _native is not None and hasattr(_native, "block_header_hash"):
        return str(_native.block_header_hash(
            int(number),
            str(parent_hash),
            str(proposer),
            str(state_root),
            str(tx_root),
            int(timestamp),
            str(extra_data or ""),
        ))
    return hash_text(
        f"{number}{parent_hash}{proposer}{state_root}{tx_root}{timestamp}{extra_data or ''}"
    )


def block_header_hash_batch(
    headers: List[tuple[int, str, str, str, str, int, str]],
) -> List[str]:
    """Legacy consensus header hash for many headers in one native call."""
    if _native is not None and hasattr(_native, "block_header_hash_batch"):
        payload = [
            (
                int(number),
                str(parent_hash),
                str(proposer),
                str(state_root),
                str(tx_root),
                int(timestamp),
                str(extra_data or ""),
            )
            for number, parent_hash, proposer, state_root, tx_root, timestamp, extra_data in headers
        ]
        return [str(value) for value in _native.block_header_hash_batch(payload)]
    return [
        block_header_hash(number, parent_hash, proposer, state_root, tx_root, timestamp, extra_data)
        for number, parent_hash, proposer, state_root, tx_root, timestamp, extra_data in headers
    ]


def transaction_hash(
    from_addr: str,
    to_addr: str,
    value: float,
    nonce: int,
    gas: int,
    data: str,
    timestamp: int,
) -> str:
    """Legacy raw transaction hash used by consensus and signing."""
    if _native is not None and hasattr(_native, "transaction_hash"):
        return str(_native.transaction_hash(
            str(from_addr),
            str(to_addr),
            float(value),
            int(nonce),
            int(gas),
            str(data or ""),
            int(timestamp),
        ))
    raw = f"{from_addr}{to_addr}{value}{nonce}{gas}{data}{timestamp}"
    return hash_text(raw)


def transaction_hash_batch(
    transactions: List[tuple[str, str, float, int, int, str, int]],
) -> List[str]:
    if _native is not None and hasattr(_native, "transaction_hash_batch"):
        payload = [
            (
                str(from_addr),
                str(to_addr),
                float(value),
                int(nonce),
                int(gas),
                str(data or ""),
                int(timestamp),
            )
            for from_addr, to_addr, value, nonce, gas, data, timestamp in transactions
        ]
        return [str(value) for value in _native.transaction_hash_batch(payload)]
    return [
        transaction_hash(from_addr, to_addr, value, nonce, gas, data, timestamp)
        for from_addr, to_addr, value, nonce, gas, data, timestamp in transactions
    ]


def _block_dict_for_canonical_hash(block: dict) -> dict:
    block_copy = dict(block)
    txs = list(block_copy.get("transactions") or [])
    if txs:
        block_copy["transactions"] = sorted(
            txs,
            key=lambda row: str((row or {}).get("hash", "")),
        )
    return block_copy


def block_canonical_hash(block: dict) -> str:
    """Deterministic block hash via CanonicalSerializer rules."""
    block_copy = _block_dict_for_canonical_hash(block)
    encoded = json.dumps(block_copy, separators=(",", ":"), ensure_ascii=False)
    if _native is not None and hasattr(_native, "block_canonical_hash_json"):
        return str(_native.block_canonical_hash_json(encoded))
    _require_native_kernel("block_canonical_hash")
    return hash_text(_python_canonical_serialize(block_copy))


def block_canonical_hash_batch(blocks: List[dict]) -> List[str]:
    """Batch canonical block hash for sync/import hot paths."""
    payloads = [
        json.dumps(_block_dict_for_canonical_hash(block), separators=(",", ":"), ensure_ascii=False)
        for block in blocks
    ]
    if _native is not None and hasattr(_native, "block_canonical_hash_batch"):
        return [str(value) for value in _native.block_canonical_hash_batch(payloads)]
    return [block_canonical_hash(block) for block in blocks]


def canonical_hash_json(obj_json: str) -> str:
    """Hash a JSON object using canonical float-to-satoshi rules."""
    if _native is not None and hasattr(_native, "canonical_hash_json"):
        return str(_native.canonical_hash_json(obj_json))
    _require_native_kernel("canonical_hash_json")
    value = json.loads(obj_json)
    return hash_text(_python_canonical_serialize(value))


def _python_canonical_serialize(obj: Any) -> str:
    return json.dumps(
        _python_canonicalize(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _python_canonicalize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: _python_canonicalize(value)
            for key, value in sorted(obj.items())
        }
    if isinstance(obj, list):
        return [_python_canonicalize(item) for item in obj]
    if isinstance(obj, float):
        return int(obj * 1_000_000)
    return obj


def keccak256_hex(data: bytes) -> str:
    """Ethereum-compatible Keccak-256."""
    if _native is not None and hasattr(_native, "keccak256_hex"):
        return str(_native.keccak256_hex(data))
    if _REQUIRE_NATIVE:
        raise RuntimeError(_NATIVE_REQUIRED_MSG)
    try:
        from Crypto.Hash import keccak as _keccak

        digest = _keccak.new(digest_bits=256)
        digest.update(data)
        return digest.hexdigest()
    except ImportError:
        raise RuntimeError(
            "keccak256_hex requires abs_native (pip install -e native/abs_native) "
            "or pycryptodome; hashlib.sha3_256 is NOT Ethereum Keccak"
        )


def keccak256_digest(data: bytes) -> bytes:
    if _native is not None and hasattr(_native, "keccak256_digest"):
        return bytes(_native.keccak256_digest(data))
    return bytes.fromhex(keccak256_hex(data))


def keccak256_digest_batch(items: List[bytes]) -> List[bytes]:
    if _native is not None and hasattr(_native, "keccak256_digest_batch"):
        return [bytes(digest) for digest in _native.keccak256_digest_batch([bytes(item) for item in items])]
    return [keccak256_digest(item) for item in items]


def recover_eth_address_keccak(prehash: bytes, r: bytes, s: bytes, rec_id: int) -> str:
    if _native is not None and hasattr(_native, "recover_eth_address_keccak"):
        return str(_native.recover_eth_address_keccak(prehash, r, s, int(rec_id)))
    raise RuntimeError("recover_eth_address_keccak requires abs_native")


def pubkey_to_eth_address(public_key: bytes) -> str:
    """Keccak-256 Ethereum address from secp256k1 public key bytes."""
    if _native is not None and hasattr(_native, "pubkey_to_eth_address"):
        return str(_native.pubkey_to_eth_address(public_key))
    if _REQUIRE_NATIVE:
        raise RuntimeError(_NATIVE_REQUIRED_MSG)
    pk = public_key[1:] if len(public_key) == 65 and public_key[0] == 0x04 else public_key
    if len(pk) != 64:
        raise ValueError("public_key must be 64 bytes uncompressed or 65 with 0x04 prefix")
    digest = keccak256_digest(pk)
    return "0x" + digest[-20:].hex()


EVM_U256_MASK = (1 << 256) - 1


def _evm_u256_bytes(value: int) -> bytes:
    return int(value & EVM_U256_MASK).to_bytes(32, "big")


def _evm_u256_int(value: bytes) -> int:
    return int.from_bytes(value, "big")


def _evm_u256_binop(name: str, left: int, right: int) -> int:
    if _native is not None and hasattr(_native, name):
        result = getattr(_native, name)(_evm_u256_bytes(left), _evm_u256_bytes(right))
        return _evm_u256_int(bytes(result))
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    if name == "evm_u256_add":
        return (left + right) & EVM_U256_MASK
    if name == "evm_u256_mul":
        return (left * right) & EVM_U256_MASK
    if name == "evm_u256_sub":
        return (left - right) & EVM_U256_MASK
    if name == "evm_u256_div":
        return 0 if right == 0 else left // right
    if name == "evm_u256_mod":
        return 0 if right == 0 else left % right
    if name == "evm_u256_and":
        return left & right
    if name == "evm_u256_or":
        return left | right
    if name == "evm_u256_xor":
        return left ^ right
    raise ValueError(f"unsupported EVM binop: {name}")


def evm_u256_add(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_add", left, right)


def evm_u256_mul(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_mul", left, right)


def evm_u256_sub(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_sub", left, right)


def evm_u256_div(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_div", left, right)


def evm_u256_mod(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_mod", left, right)


def evm_u256_and(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_and", left, right)


def evm_u256_or(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_or", left, right)


def evm_u256_xor(left: int, right: int) -> int:
    return _evm_u256_binop("evm_u256_xor", left, right)


def evm_u256_not(value: int) -> int:
    value &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_not"):
        return _evm_u256_int(bytes(_native.evm_u256_not(_evm_u256_bytes(value))))
    return (~value) & EVM_U256_MASK


def evm_u256_shl(value: int, shift: int) -> int:
    value &= EVM_U256_MASK
    shift = int(shift) & EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_shl"):
        return _evm_u256_int(bytes(_native.evm_u256_shl(_evm_u256_bytes(value), int(shift))))
    return (value << shift) & EVM_U256_MASK


def evm_u256_shr(value: int, shift: int) -> int:
    value &= EVM_U256_MASK
    shift = int(shift) & EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_shr"):
        return _evm_u256_int(bytes(_native.evm_u256_shr(_evm_u256_bytes(value), int(shift))))
    return value >> shift


def evm_u256_slt(left: int, right: int) -> int:
    if _native is not None and hasattr(_native, "evm_u256_slt"):
        return _evm_u256_int(
            bytes(_native.evm_u256_slt(_evm_u256_bytes(left), _evm_u256_bytes(right)))
        )
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    sign = 1 << 255
    left_neg = left >= sign
    right_neg = right >= sign
    if left_neg == right_neg:
        truthy = left < right
    else:
        truthy = left_neg
    return 1 if truthy else 0


def evm_u256_sgt(left: int, right: int) -> int:
    if _native is not None and hasattr(_native, "evm_u256_sgt"):
        return _evm_u256_int(
            bytes(_native.evm_u256_sgt(_evm_u256_bytes(left), _evm_u256_bytes(right)))
        )
    return evm_u256_slt(right, left)


def evm_u256_sar(value: int, shift: int) -> int:
    shift = int(shift) & EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_sar"):
        return _evm_u256_int(bytes(_native.evm_u256_sar(_evm_u256_bytes(value), int(shift))))
    value &= EVM_U256_MASK
    if shift >= 256:
        return EVM_U256_MASK if value >= (1 << 255) else 0
    if value >= (1 << 255):
        mask = EVM_U256_MASK << (256 - shift) & EVM_U256_MASK
        return (value >> shift) | mask
    return value >> shift


def _evm_u256_cmp(name: str, left: int, right: int = 0) -> int:
    if name == "evm_u256_iszero":
        if _native is not None and hasattr(_native, name):
            result = getattr(_native, name)(_evm_u256_bytes(left))
            return _evm_u256_int(bytes(result))
        return 1 if (left & EVM_U256_MASK) == 0 else 0
    if _native is not None and hasattr(_native, name):
        result = getattr(_native, name)(_evm_u256_bytes(left), _evm_u256_bytes(right))
        return _evm_u256_int(bytes(result))
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    if name == "evm_u256_eq":
        return 1 if left == right else 0
    if name == "evm_u256_lt":
        return 1 if left < right else 0
    if name == "evm_u256_gt":
        return 1 if left > right else 0
    raise ValueError(f"unsupported EVM cmp: {name}")


def evm_u256_eq(left: int, right: int) -> int:
    return _evm_u256_cmp("evm_u256_eq", left, right)


def evm_u256_lt(left: int, right: int) -> int:
    return _evm_u256_cmp("evm_u256_lt", left, right)


def evm_u256_gt(left: int, right: int) -> int:
    return _evm_u256_cmp("evm_u256_gt", left, right)


def evm_u256_iszero(value: int) -> int:
    return _evm_u256_cmp("evm_u256_iszero", value)


def evm_u256_byte(index: int, word: int) -> int:
    index = int(index) & EVM_U256_MASK
    word &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_byte"):
        return _evm_u256_int(bytes(_native.evm_u256_byte(int(index), _evm_u256_bytes(word))))
    if index >= 32:
        return 0
    return (word >> (8 * (31 - index))) & 0xFF


def evm_memory_read_word(memory: bytes, offset: int) -> int:
    offset = int(offset)
    if _native is not None and hasattr(_native, "evm_memory_read_word"):
        return _evm_u256_int(bytes(_native.evm_memory_read_word(memory, offset)))
    end = offset + 32
    chunk = memory[offset:end] if offset < len(memory) else b""
    if len(chunk) < 32:
        chunk = chunk + (b"\x00" * (32 - len(chunk)))
    return int.from_bytes(chunk, "big")


def evm_calldataload(calldata: bytes, offset: int) -> int:
    offset = int(offset)
    if _native is not None and hasattr(_native, "evm_calldataload"):
        return _evm_u256_int(bytes(_native.evm_calldataload(calldata, offset)))
    end = offset + 32
    chunk = calldata[offset:end] if offset < len(calldata) else b""
    if len(chunk) < 32:
        chunk = chunk + (b"\x00" * (32 - len(chunk)))
    return int.from_bytes(chunk, "big")


def _evm_i256_to_signed(value: int) -> int:
    value &= EVM_U256_MASK
    if value >= (1 << 255):
        return value - (1 << 256)
    return value


def _evm_i256_from_signed(value: int) -> int:
    return int(value) & EVM_U256_MASK


def _evm_u256_native_call(name: str, *args: int) -> int:
    if _native is not None and hasattr(_native, name):
        packed = [_evm_u256_bytes(arg) for arg in args]
        if len(packed) == 1:
            result = getattr(_native, name)(packed[0])
        elif len(packed) == 2:
            result = getattr(_native, name)(packed[0], packed[1])
        else:
            result = getattr(_native, name)(packed[0], packed[1], packed[2])
        return _evm_u256_int(bytes(result))
    raise ValueError(f"unsupported native call: {name}")


def evm_u256_sdiv(left: int, right: int) -> int:
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_sdiv"):
        return _evm_u256_native_call("evm_u256_sdiv", left, right)
    if right == 0:
        return 0
    if left == (1 << 255) and right == EVM_U256_MASK:
        return left
    return _evm_i256_from_signed(int(_evm_i256_to_signed(left) / _evm_i256_to_signed(right)))


def evm_u256_smod(left: int, right: int) -> int:
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_smod"):
        return _evm_u256_native_call("evm_u256_smod", left, right)
    if right == 0:
        return 0
    left_s = _evm_i256_to_signed(left)
    right_s = abs(_evm_i256_to_signed(right))
    return _evm_i256_from_signed(int(math.copysign(abs(left_s) % right_s, left_s)))


def evm_u256_addmod(left: int, right: int, modulo: int) -> int:
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    modulo &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_addmod"):
        return _evm_u256_native_call("evm_u256_addmod", left, right, modulo)
    if modulo == 0:
        return 0
    return (left + right) % modulo


def evm_u256_mulmod(left: int, right: int, modulo: int) -> int:
    left &= EVM_U256_MASK
    right &= EVM_U256_MASK
    modulo &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_mulmod"):
        return _evm_u256_native_call("evm_u256_mulmod", left, right, modulo)
    if modulo == 0:
        return 0
    return (left * right) % modulo


def evm_u256_exp(base: int, exponent: int) -> int:
    base &= EVM_U256_MASK
    exponent &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_exp"):
        return _evm_u256_native_call("evm_u256_exp", base, exponent)
    if exponent == 0:
        return 0 if base == 0 else 1
    result = 1
    b = base
    e = exponent
    while e:
        if e & 1:
            result = (result * b) & EVM_U256_MASK
        b = (b * b) & EVM_U256_MASK
        e >>= 1
    return result


def evm_u256_signextend(index: int, word: int) -> int:
    index = int(index) & EVM_U256_MASK
    word &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_u256_signextend"):
        result = _native.evm_u256_signextend(int(index), _evm_u256_bytes(word))
        return _evm_u256_int(bytes(result))
    if index >= 32:
        return word
    bit = 8 * index + 7
    lower_mask = (1 << (bit + 1)) - 1
    if word & (1 << bit):
        return word | (~lower_mask & EVM_U256_MASK)
    return word & lower_mask


def evm_memory_write_word(memory: bytearray, offset: int, value: int) -> None:
    offset = int(offset)
    word = _evm_u256_bytes(value)
    if _native is not None and hasattr(_native, "evm_memory_write_word"):
        _native.evm_memory_write_word(memory, offset, word)
        return
    for i in range(32):
        idx = offset + i
        if idx < len(memory):
            memory[idx] = word[i]


def evm_memory_write_byte(memory: bytearray, offset: int, value: int) -> None:
    offset = int(offset)
    if _native is not None and hasattr(_native, "evm_memory_write_byte"):
        _native.evm_memory_write_byte(memory, offset, int(value) & 0xFF)
        return
    if offset < len(memory):
        memory[offset] = int(value) & 0xFF


def evm_read_push(bytecode: bytes, pc: int, size: int) -> int:
    pc = int(pc)
    size = int(size)
    if _native is not None and hasattr(_native, "evm_read_push"):
        return _evm_u256_int(bytes(_native.evm_read_push(bytecode, pc, size)))
    start = pc + 1
    end = min(start + size, len(bytecode))
    chunk = bytecode[start:end]
    if len(chunk) < size:
        chunk = chunk + (b"\x00" * (size - len(chunk)))
    return int.from_bytes(chunk, "big")


def evm_build_jumpdest_table(bytecode: bytes) -> bytes:
    if _native is not None and hasattr(_native, "evm_build_jumpdest_table"):
        return bytes(_native.evm_build_jumpdest_table(bytecode))
    table = bytearray((len(bytecode) + 7) // 8)
    pc = 0
    while pc < len(bytecode):
        op = bytecode[pc]
        if op == 0x5B:
            table[pc // 8] |= 1 << (pc % 8)
        if 0x60 <= op <= 0x7F:
            pc += 1 + (op - 0x5F)
        else:
            pc += 1
    return bytes(table)


def evm_is_jumpdest(table: bytes, dest: int, bytecode_len: int) -> bool:
    dest = int(dest)
    bytecode_len = int(bytecode_len)
    if dest < 0 or dest >= bytecode_len:
        return False
    if _native is not None and hasattr(_native, "evm_is_jumpdest"):
        return bool(_native.evm_is_jumpdest(table, dest, bytecode_len))
    return bool((table[dest // 8] >> (dest % 8)) & 1)


def evm_word_to_address(word: int) -> str:
    word &= EVM_U256_MASK
    if _native is not None and hasattr(_native, "evm_word_to_address"):
        return str(_native.evm_word_to_address(_evm_u256_bytes(word)))
    return "0x" + format(word & ((1 << 160) - 1), "040x")


def evm_call_gas_cap(remaining: int, requested: int) -> int:
    remaining = max(0, int(remaining))
    requested = max(0, int(requested))
    if _native is not None and hasattr(_native, "evm_call_gas_cap"):
        return int(_native.evm_call_gas_cap(remaining, requested))
    cap = remaining * 63 // 64
    if requested <= 0:
        return cap
    return min(requested, cap)


def evm_memory_slice(memory: bytes, offset: int, size: int) -> bytes:
    offset = int(offset)
    size = int(size)
    if _native is not None and hasattr(_native, "evm_memory_slice"):
        return bytes(_native.evm_memory_slice(memory, offset, size))
    end = offset + size
    chunk = memory[offset:end] if offset < len(memory) else b""
    if len(chunk) < size:
        chunk = chunk + (b"\x00" * (size - len(chunk)))
    return bytes(chunk)


def evm_stack_dup(stack: list, depth: int) -> None:
    depth = int(depth)
    if _native is not None and hasattr(_native, "evm_stack_dup"):
        try:
            _native.evm_stack_dup(stack, depth)
        except Exception as exc:
            raise RuntimeError("stack underflow") from exc
        return
    if depth <= 0 or depth > len(stack):
        raise RuntimeError("stack underflow")
    stack.append(stack[-depth])


def evm_stack_swap(stack: list, depth: int) -> None:
    depth = int(depth)
    if _native is not None and hasattr(_native, "evm_stack_swap"):
        try:
            _native.evm_stack_swap(stack, depth)
        except Exception as exc:
            raise RuntimeError("stack underflow") from exc
        return
    if depth <= 0 or depth >= len(stack):
        raise RuntimeError("stack underflow")
    stack[-1], stack[-1 - depth] = stack[-1 - depth], stack[-1]


def evm_scan_bytecode(bytecode: bytes):
    if _native is not None and hasattr(_native, "evm_scan_bytecode"):
        return [(int(pc), int(op)) for pc, op in _native.evm_scan_bytecode(bytecode)]
    issues = []
    pc = 0
    while pc < len(bytecode):
        op = bytecode[pc]
        if not _evm_opcode_supported_python(op):
            issues.append((pc, op))
        if 0x60 <= op <= 0x7F:
            pc += 1 + (op - 0x5F)
        else:
            pc += 1
    return issues


def _evm_opcode_supported_python(op: int) -> bool:
    if 0x60 <= op <= 0x7F or 0x80 <= op <= 0x8F or 0x90 <= op <= 0x9F or 0xA0 <= op <= 0xA4:
        return True
    return op in _EVM_SUPPORTED_SINGLE_OPCODES


_EVM_SUPPORTED_SINGLE_OPCODES = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B,
    0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D,
    0x20,
    0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A,
    0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
    0x49, 0x4A,
    0x50, 0x51, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x5B,
    0x5C, 0x5D, 0x5E, 0x5F,
    0xA0, 0xA1, 0xA2, 0xA3, 0xA4,
    0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xFA, 0xFD, 0xFE, 0xFF,
}


def evm_gas_remaining(gas_limit: int, gas_used: int) -> int:
    gas_limit = max(0, int(gas_limit))
    gas_used = max(0, int(gas_used))
    if _native is not None and hasattr(_native, "evm_gas_remaining"):
        return int(_native.evm_gas_remaining(gas_limit, gas_used))
    return max(0, gas_limit - gas_used)


_EVM_HOST_OPCODES = frozenset({
    0xF0, 0xF1, 0xF2, 0xF4, 0xF5, 0xFA, 0xFF,
    *range(0xA0, 0xA5),
})

_EVM_BRIDGE_OPCODES = frozenset({0x31, 0x3B, 0x3C, 0x3F, 0x40})


def evm_host_context_from_evm(ctx) -> dict:
    """Build static host context dict for native pure runner."""
    host = {
        "address": ctx.addr_int(ctx.address),
        "caller": ctx.addr_int(ctx.caller),
        "origin": ctx.addr_int(ctx.origin),
        "value": int(ctx.value),
        "timestamp": int(ctx.timestamp),
        "block_number": int(ctx.block_number),
        "chain_id": int(ctx.chain_id),
        "base_fee": int(getattr(ctx, "base_fee", 0) or 0),
        "gas_price": int(getattr(ctx, "gas_price", 0) or 0),
        "difficulty": int(getattr(ctx, "difficulty", 0) or 0),
        "coinbase": ctx.addr_int(getattr(ctx, "coinbase", "") or ""),
        "blob_base_fee": int(getattr(ctx, "blob_base_fee", 0) or 0),
        "blob_hashes": [
            int(h) & ((1 << 256) - 1)
            for h in (getattr(ctx, "blob_hashes", None) or [])
        ],
    }
    hooks = {}
    if ctx.balance_of:
        hooks["balance"] = ctx.balance_of
    if ctx.code_size_of:
        hooks["code_size"] = ctx.code_size_of
    if ctx.code_copy_of:
        hooks["code_copy"] = ctx.code_copy_of
    if ctx.code_size_of or ctx.code_copy_of:
        def _code_hash(addr):
            size = int(ctx.code_size_of(addr)) if ctx.code_size_of else 0
            if size <= 0:
                return 0
            code = ctx.code_copy_of(addr, 0, size) if ctx.code_copy_of else b""
            if not code:
                return 0
            return int.from_bytes(keccak256_digest(code), "big")
        hooks["code_hash"] = _code_hash
    if ctx.block_hash_of:
        hooks["block_hash"] = ctx.block_hash_of
    if ctx.emit_log:
        hooks["emit_log"] = ctx.emit_log
    if ctx.contract_call:
        hooks["contract_call"] = ctx.contract_call
    if ctx.contract_create:
        def _contract_create(init_code, value, salt=None):
            return ctx.contract_create(init_code, value, ctx, salt)

        hooks["contract_create"] = _contract_create
    if ctx.selfdestruct:
        hooks["selfdestruct"] = ctx.selfdestruct
    if hooks:
        host["bridge_hooks"] = hooks
    host["_abs_read_only"] = bool(getattr(ctx, "_abs_read_only", False))
    return host


def evm_opcode_is_host(op: int) -> bool:
    op = int(op) & 0xFF
    if _native is not None and hasattr(_native, "evm_opcode_is_host"):
        return bool(_native.evm_opcode_is_host(op))
    return op in _EVM_HOST_OPCODES


def evm_opcode_is_bridge(op: int) -> bool:
    op = int(op) & 0xFF
    if _native is not None and hasattr(_native, "evm_opcode_is_bridge"):
        return bool(_native.evm_opcode_is_bridge(op))
    return op in _EVM_BRIDGE_OPCODES


def _parse_native_segment(seg) -> dict:
    logs = []
    raw_logs = seg.get("logs") if hasattr(seg, "get") else None
    if raw_logs is None and isinstance(seg, dict):
        raw_logs = seg.get("logs")
    try:
        for entry in list(raw_logs or []):
            if isinstance(entry, dict):
                logs.append({
                    "topics": list(entry.get("topics") or []),
                    "data": str(entry.get("data") or ""),
                })
            else:
                topics = list(entry.get("topics") or []) if hasattr(entry, "get") else []
                data = str(entry.get("data") or "") if hasattr(entry, "get") else ""
                logs.append({"topics": topics, "data": data})
    except Exception:
        logs = []
    return {
        "pc": int(seg["pc"]),
        "gas_used": int(seg["gas_used"]),
        "running": bool(seg["running"]),
        "reverted": bool(seg["reverted"]),
        "return_data": bytes(seg["return_data"]),
        "stop_reason": str(seg["stop_reason"]),
        "host_opcode": seg.get("host_opcode"),
        "error": seg.get("error"),
        "steps": int(seg["steps"]),
        "stack": [int(x) for x in seg["stack"]],
        "memory": bytearray(seg["memory"]),
        "logs": logs,
    }


def evm_run_pure_until_host(
    bytecode: bytes,
    pc: int,
    gas_limit: int,
    gas_used: int,
    stack: list,
    memory: bytearray,
    jumpdest_table: bytes,
    calldata: bytes,
    return_data: bytes,
    host_context: Optional[dict] = None,
    storage: Optional[dict] = None,
    host_bridge: Any = None,
) -> dict:
    if _native is not None and hasattr(_native, "evm_run_pure_until_host"):
        seg = _native.evm_run_pure_until_host(
            bytes(bytecode),
            int(pc),
            int(gas_limit),
            int(gas_used),
            stack,
            memory,
            bytes(jumpdest_table),
            bytes(calldata),
            bytes(return_data),
            host_context,
            storage,
            host_bridge,
        )
        return _parse_native_segment(seg)
    raise RuntimeError("evm_run_pure_until_host requires abs_native")


def evm_run_until_halt(
    bytecode: bytes,
    pc: int,
    gas_limit: int,
    gas_used: int,
    stack: list,
    memory: bytearray,
    jumpdest_table: bytes,
    calldata: bytes,
    return_data: bytes,
    host_context: Optional[dict] = None,
    storage: Optional[dict] = None,
    host_bridge: Any = None,
) -> dict:
    if _native is not None and hasattr(_native, "evm_run_until_halt"):
        seg = _native.evm_run_until_halt(
            bytes(bytecode),
            int(pc),
            int(gas_limit),
            int(gas_used),
            stack,
            memory,
            bytes(jumpdest_table),
            bytes(calldata),
            bytes(return_data),
            host_context,
            storage,
            host_bridge,
        )
        return _parse_native_segment(seg)
    raise RuntimeError("evm_run_until_halt requires abs_native")


def evm_bytecode_is_nested_pure_eligible(bytecode: bytes) -> bool:
    """True when child bytecode has no host/bridge opcodes (strict nested pure)."""
    pc = 0
    bc = bytes(bytecode or b"")
    while pc < len(bc):
        op = bc[pc]
        if evm_opcode_is_host(op) or evm_opcode_is_bridge(op):
            return False
        if 0x60 <= op <= 0x7F:
            pc += 1 + (op - 0x5F)
        else:
            pc += 1
    return True


def evm_bytecode_is_nested_native_eligible(bytecode: bytes) -> bool:
    """True when child has no recursive host ops (CALL/CREATE/LOG/SELFDESTRUCT).

    Bridge ops (BALANCE/EXTCODE*/BLOCKHASH) are allowed when host_context carries
    bridge_hooks or bridge_state — industrial nested CALL surface in abs_native.
    """
    if _native is not None and hasattr(_native, "evm_bytecode_is_nested_native_eligible"):
        return bool(_native.evm_bytecode_is_nested_native_eligible(bytes(bytecode or b"")))
    pc = 0
    bc = bytes(bytecode or b"")
    while pc < len(bc):
        op = bc[pc]
        if evm_opcode_is_host(op):
            return False
        if 0x60 <= op <= 0x7F:
            pc += 1 + (op - 0x5F)
        else:
            pc += 1
    return True


def evm_bytecode_is_inline_call_frame_eligible(bytecode: bytes) -> bool:
    """True when bytecode may run as an in-Rust call-frame (v1.3.75).

    Allows CALL*/LOG; rejects CREATE/CREATE2/SELFDESTRUCT.
    """
    if _native is not None and hasattr(_native, "evm_bytecode_is_inline_call_frame_eligible"):
        return bool(
            _native.evm_bytecode_is_inline_call_frame_eligible(bytes(bytecode or b""))
        )
    pc = 0
    bc = bytes(bytecode or b"")
    while pc < len(bc):
        op = bc[pc]
        if op in (0xF0, 0xF5, 0xFF):
            return False
        if 0x60 <= op <= 0x7F:
            pc += 1 + (op - 0x5F)
        else:
            pc += 1
    return True


def evm_run_nested_pure_frame(
    bytecode: bytes,
    gas_limit: int,
    calldata: bytes = b"",
    host_context: Optional[dict] = None,
    storage: Optional[dict] = None,
    *,
    allow_bridge: bool = False,
) -> dict:
    """Run a nested CALL child in abs_native (no recursive CALL host).

    Prefers abs_native. On host/handoff stop reasons the caller must fall back
    to Python execute_bytecode. Mutates ``storage`` in place when provided.

    allow_bridge=True keeps bridge_hooks/bridge_state so BALANCE/EXTCODE*/BLOCKHASH
    run in Rust via host_context (v1.3.55).
    """
    storage_work = storage if storage is not None else {}
    ctx = dict(host_context or {})
    if not allow_bridge:
        # Strict pure: no Python bridge callbacks.
        ctx.pop("bridge_hooks", None)
        ctx.pop("bridge_state", None)
    if _native is not None and hasattr(_native, "evm_run_nested_pure_frame"):
        seg = _native.evm_run_nested_pure_frame(
            bytes(bytecode),
            int(gas_limit),
            bytes(calldata or b""),
            ctx,
            storage_work,
        )
        out = _parse_native_segment(seg)
        out["storage"] = {int(k): int(v) for k, v in dict(storage_work).items()}
        out["native_nested_pure"] = True
        out["allow_bridge"] = bool(allow_bridge)
        reason = str(out.get("stop_reason") or "")
        out["success"] = (not out.get("reverted")) and reason in ("halt", "return")
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_run_nested_pure_frame")
    raise RuntimeError("evm_run_nested_pure_frame requires abs_native")


def evm_run_nested_host_frame(
    bytecode: bytes,
    gas_limit: int,
    calldata: bytes = b"",
    host_context: Optional[dict] = None,
    storage: Optional[dict] = None,
    host_bridge: Any = None,
) -> dict:
    """Nested CALL child via Rust runner with runtime host_bridge.

    CALL/CREATE/LOG/SELFDESTRUCT go through ``host_bridge.apply_host_op``
    (Python callbacks) without dropping into the Python opcode loop (v1.3.56).
    Mutates ``storage`` in place when provided.
    """
    storage_work = storage if storage is not None else {}
    ctx = dict(host_context or {})
    if _native is not None and hasattr(_native, "evm_run_nested_host_frame"):
        seg = _native.evm_run_nested_host_frame(
            bytes(bytecode),
            int(gas_limit),
            bytes(calldata or b""),
            ctx,
            storage_work,
            host_bridge,
        )
        out = _parse_native_segment(seg)
        out["storage"] = {int(k): int(v) for k, v in dict(storage_work).items()}
        out["native_nested_host"] = True
        reason = str(out.get("stop_reason") or "")
        out["success"] = (not out.get("reverted")) and reason in ("halt", "return")
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_run_nested_host_frame")
    raise RuntimeError("evm_run_nested_host_frame requires abs_native")


def account_storage_map_from_raw(raw=None) -> Optional[dict]:
    """Decode contract storage JSON/dict → `{int: int}` or None if corrupt (v1.3.58)."""
    if _native is not None and hasattr(_native, "account_storage_map_from_raw"):
        out = _native.account_storage_map_from_raw(raw)
        if out is None:
            return None
        return {int(k): int(v) for k, v in dict(out).items()}
    # Python fail-closed reference
    try:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return {int(k): int(v) for k, v in raw.items()}
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw or "{}")
        text = text.strip() or "{}"
        parsed = json.loads(text)
        return {int(k): int(v) for k, v in parsed.items()}
    except Exception:
        return None


def account_view_from_blob(blob: bytes) -> dict:
    """Decode Rocks/SQLite account JSON blob into a structured view."""
    if _native is not None and hasattr(_native, "account_view_from_blob"):
        return dict(_native.account_view_from_blob(bytes(blob or b"")))
    if _REQUIRE_NATIVE:
        _require_native_kernel("account_view_from_blob")
    raise RuntimeError("account_view_from_blob requires abs_native")


def account_view_from_json(account_json: str) -> dict:
    if _native is not None and hasattr(_native, "account_view_from_json"):
        return dict(_native.account_view_from_json(str(account_json or "")))
    if _REQUIRE_NATIVE:
        _require_native_kernel("account_view_from_json")
    raise RuntimeError("account_view_from_json requires abs_native")


def account_view_from_row(row: Optional[dict]) -> dict:
    """Build account view from a DB row dict (uses native storage/code decode)."""
    if not row:
        return {
            "ok": True,
            "corrupt": False,
            "missing": True,
            "address": "",
            "balance_satoshi": 0,
            "nonce": 0,
            "code": "",
            "code_bytes": b"",
            "storage": {},
            "native_account_view": True,
        }
    storage = account_storage_map_from_raw(row.get("storage"))
    if storage is None:
        return {
            "ok": False,
            "corrupt": True,
            "missing": False,
            "address": str(row.get("address") or ""),
            "error": "corrupt_storage",
            "native_account_view": True,
        }
    code = str(row.get("code") or "")
    try:
        code_bytes = bytes.fromhex(code.replace("0x", "")) if code else b""
    except ValueError:
        code_bytes = b""
    return {
        "ok": True,
        "corrupt": False,
        "missing": False,
        "address": str(row.get("address") or ""),
        "balance_satoshi": int(row.get("balance_satoshi") or 0),
        "nonce": int(row.get("nonce") or 0),
        "code": code,
        "code_bytes": code_bytes,
        "storage": storage,
        "native_account_view": True,
    }


def evm_host_snapshot_storage(storage: dict) -> dict:
    _require_native_kernel("evm_host_snapshot_storage")
    if _native is not None and hasattr(_native, "evm_host_snapshot_storage"):
        out = _native.evm_host_snapshot_storage(storage)
        return dict(out) if out is not None else {}
    raise RuntimeError("evm_host_snapshot_storage requires abs_native")


def evm_host_restore_storage(storage: dict, snapshot: dict) -> None:
    _require_native_kernel("evm_host_restore_storage")
    if _native is not None and hasattr(_native, "evm_host_restore_storage"):
        _native.evm_host_restore_storage(storage, snapshot)
        return
    raise RuntimeError("evm_host_restore_storage requires abs_native")


def _evm_plan_nested_call_effects_py(
    kind: str,
    parent_read_only: bool,
    caller: str,
    target: str,
    value_wei: int,
    success: bool,
) -> dict:
    """Python reference for nested CALL persist/value/read-only policy."""
    kind_n = str(kind or "").strip().lower()
    if kind_n not in ("call", "callcode", "delegatecall", "staticcall"):
        raise ValueError("kind must be call|callcode|delegatecall|staticcall")
    value_wei = max(0, int(value_wei or 0))
    nested_read_only = bool(parent_read_only) or kind_n == "staticcall"
    persist_storage = False
    persist_value = False
    persist_logs = False
    storage_owner = "caller" if kind_n in ("delegatecall", "callcode") else "target"
    exec_address = "caller" if kind_n in ("delegatecall", "callcode") else "target"
    value_from = ""
    value_to = ""
    effective_value_wei = 0
    if success and not nested_read_only:
        persist_storage = True
        if kind_n in ("delegatecall", "callcode"):
            persist_logs = True
        if kind_n in ("call", "callcode") and value_wei > 0:
            persist_value = True
            value_from = "caller"
            value_to = "target"
            effective_value_wei = value_wei
    return {
        "kind": kind_n,
        "caller": str(caller or ""),
        "target": str(target or ""),
        "nested_read_only": nested_read_only,
        "persist_storage": persist_storage,
        "persist_value": persist_value,
        "persist_logs": persist_logs,
        "storage_owner": storage_owner,
        "exec_address": exec_address,
        "value_from": value_from,
        "value_to": value_to,
        "effective_value_wei": effective_value_wei,
        "reject_create": nested_read_only,
        "success": bool(success),
        "native_plan": False,
    }


def evm_plan_nested_call_effects(
    kind: str,
    parent_read_only: bool,
    caller: str,
    target: str,
    value_wei: int,
    success: bool,
) -> dict:
    """Plan nested CALL effects (read-only / persist / value). Prefers abs_native."""
    if _native is not None and hasattr(_native, "evm_plan_nested_call_effects"):
        raw = _native.evm_plan_nested_call_effects(
            str(kind),
            bool(parent_read_only),
            str(caller or ""),
            str(target or ""),
            int(value_wei or 0),
            bool(success),
        )
        out = json.loads(raw) if isinstance(raw, str) else dict(raw)
        out["native_plan"] = True
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_plan_nested_call_effects")
    return _evm_plan_nested_call_effects_py(
        kind, parent_read_only, caller, target, value_wei, success
    )


def _evm_plan_nested_call_writeback_py(
    kind: str,
    parent_read_only: bool,
    caller: str,
    target: str,
    value_wei: int,
    success: bool,
    storage=None,
    logs=None,
) -> dict:
    """Python reference: effects policy + concrete writeback ops."""
    base = _evm_plan_nested_call_effects_py(
        kind, parent_read_only, caller, target, value_wei, success
    )
    ops: list = []
    if base.get("persist_storage"):
        storage_map = {}
        if isinstance(storage, dict):
            storage_map = {str(int(k)): int(v) for k, v in storage.items()}
        elif storage is not None:
            try:
                parsed = json.loads(storage) if isinstance(storage, (str, bytes, bytearray)) else {}
                storage_map = {str(int(k)): int(v) for k, v in dict(parsed).items()}
            except Exception:
                storage_map = {}
        owner = caller if base.get("storage_owner") == "caller" else target
        ops.append({"op": "set_storage", "address": str(owner or ""), "storage": storage_map})
    if base.get("persist_value") and int(base.get("effective_value_wei") or 0) > 0:
        from_addr = caller if base.get("value_from") == "caller" else target
        to_addr = target if base.get("value_to") == "target" else caller
        ops.append({
            "op": "transfer_value",
            "from": str(from_addr or ""),
            "to": str(to_addr or ""),
            "value_wei": int(base["effective_value_wei"]),
        })
    if base.get("persist_logs"):
        log_list = list(logs or [])
        if log_list:
            ops.append({
                "op": "append_logs",
                "address": str(caller or ""),
                "logs": log_list,
            })
    base["ops"] = ops
    base["native_writeback"] = False
    return base


def evm_plan_nested_call_writeback(
    kind: str,
    parent_read_only: bool,
    caller: str,
    target: str,
    value_wei: int,
    success: bool,
    storage=None,
    logs=None,
) -> dict:
    """Plan nested CALL writeback ops with resolved addresses (v1.3.59)."""
    storage_json = None
    if storage is not None:
        if isinstance(storage, dict):
            storage_json = json.dumps({str(int(k)): int(v) for k, v in storage.items()})
        elif isinstance(storage, (bytes, bytearray)):
            storage_json = storage.decode("utf-8", errors="replace")
        else:
            storage_json = str(storage)
    logs_json = None
    if logs is not None:
        logs_json = json.dumps(list(logs))
    if _native is not None and hasattr(_native, "evm_plan_nested_call_writeback"):
        raw = _native.evm_plan_nested_call_writeback(
            str(kind),
            bool(parent_read_only),
            str(caller or ""),
            str(target or ""),
            int(value_wei or 0),
            bool(success),
            storage_json,
            logs_json,
        )
        out = json.loads(raw) if isinstance(raw, str) else dict(raw)
        out["native_writeback"] = True
        out["native_plan"] = True
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_plan_nested_call_writeback")
    return _evm_plan_nested_call_writeback_py(
        kind, parent_read_only, caller, target, value_wei, success, storage, logs
    )


def _evm_plan_create_writeback_py(
    deployer: str,
    contract_address: str,
    value_wei: int,
    success: bool,
    code_hex: str = "",
    storage=None,
) -> dict:
    """Python reference for CREATE/CREATE2 writeback ops."""
    ops: list = []
    deployer = str(deployer or "")
    contract_address = str(contract_address or "")
    value_wei = max(0, int(value_wei or 0))
    if success and contract_address:
        if isinstance(storage, dict):
            storage_str = json.dumps({str(int(k)): int(v) for k, v in storage.items()})
        elif storage is None:
            storage_str = "{}"
        else:
            storage_str = str(storage)
        ops.append({
            "op": "save_account",
            "address": contract_address,
            "balance": 0.0,
            "nonce": 0,
            "code": str(code_hex or ""),
            "storage": storage_str,
        })
        if value_wei > 0 and deployer:
            ops.append({
                "op": "transfer_value",
                "from": deployer,
                "to": contract_address,
                "value_wei": value_wei,
            })
    return {
        "deployer": deployer,
        "address": contract_address,
        "value_wei": value_wei,
        "success": bool(success),
        "reverted": not bool(success),
        "ops": ops,
        "native_create_writeback": False,
        "native_plan": False,
    }


def evm_plan_create_writeback(
    deployer: str,
    contract_address: str,
    value_wei: int,
    success: bool,
    code_hex: str = "",
    storage=None,
) -> dict:
    """Plan CREATE/CREATE2 writeback ops with resolved addresses (v1.3.60)."""
    storage_json = None
    if storage is not None:
        if isinstance(storage, dict):
            storage_json = json.dumps({str(int(k)): int(v) for k, v in storage.items()})
        elif isinstance(storage, (bytes, bytearray)):
            storage_json = storage.decode("utf-8", errors="replace")
        else:
            storage_json = str(storage)
    if _native is not None and hasattr(_native, "evm_plan_create_writeback"):
        raw = _native.evm_plan_create_writeback(
            str(deployer or ""),
            str(contract_address or ""),
            int(value_wei or 0),
            bool(success),
            str(code_hex or ""),
            storage_json,
        )
        out = json.loads(raw) if isinstance(raw, str) else dict(raw)
        out["native_create_writeback"] = True
        out["native_plan"] = True
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_plan_create_writeback")
    return _evm_plan_create_writeback_py(
        deployer, contract_address, value_wei, success, code_hex, storage
    )


def _evm_apply_writeback_ops_py(accounts: dict, ops: list) -> dict:
    """Python reference: apply writeback ops to an in-memory accounts map."""
    accounts = {str(k): dict(v) for k, v in dict(accounts or {}).items()}
    log_batches = []
    touched = []
    applied = 0

    def _ensure(addr: str) -> dict:
        if addr not in accounts:
            accounts[addr] = {
                "address": addr,
                "balance_satoshi": 0,
                "balance": 0.0,
                "nonce": 0,
                "code": "",
                "storage": "{}",
            }
        return accounts[addr]

    def _sat(row: dict) -> int:
        if row.get("balance_satoshi") is not None:
            return max(0, int(row["balance_satoshi"]))
        return max(0, int(float(row.get("balance") or 0) * 1_000_000))

    def _set_sat(row: dict, sat: int) -> None:
        sat = max(0, int(sat))
        row["balance_satoshi"] = sat
        row["balance"] = sat / 1_000_000.0

    for op in list(ops or []):
        kind = str(op.get("op") or "")
        if kind == "set_storage":
            addr = str(op.get("address") or "")
            if not addr:
                continue
            row = _ensure(addr)
            storage = op.get("storage") or {}
            if isinstance(storage, dict):
                row["storage"] = json.dumps({str(k): int(v) for k, v in storage.items()})
            else:
                row["storage"] = str(storage or "{}")
            if addr not in touched:
                touched.append(addr)
            applied += 1
        elif kind == "save_account":
            addr = str(op.get("address") or "")
            if not addr:
                continue
            row = _ensure(addr)
            row["code"] = str(op.get("code") or "")
            row["nonce"] = int(op.get("nonce") or 0)
            storage = op.get("storage")
            if isinstance(storage, dict):
                row["storage"] = json.dumps({str(k): int(v) for k, v in storage.items()})
            else:
                row["storage"] = str(storage or "{}")
            if op.get("balance_satoshi") is not None:
                _set_sat(row, int(op["balance_satoshi"]))
            else:
                _set_sat(row, int(float(op.get("balance") or 0) * 1_000_000))
            if addr not in touched:
                touched.append(addr)
            applied += 1
        elif kind == "transfer_value":
            from_addr = str(op.get("from") or "")
            to_addr = str(op.get("to") or "")
            value_wei = max(0, int(op.get("value_wei") or 0))
            if not from_addr or not to_addr or value_wei <= 0:
                continue
            sat = value_wei // 1_000_000_000_000
            if sat == 0:
                applied += 1
                continue
            fr = _ensure(from_addr)
            to = _ensure(to_addr)
            _set_sat(fr, _sat(fr) - sat)
            _set_sat(to, _sat(to) + sat)
            if from_addr not in touched:
                touched.append(from_addr)
            if to_addr not in touched:
                touched.append(to_addr)
            applied += 1
        elif kind == "append_logs":
            logs = list(op.get("logs") or [])
            if logs:
                log_batches.append({
                    "address": str(op.get("address") or ""),
                    "logs": logs,
                })
                applied += 1
        else:
            raise ValueError(f"unsupported_writeback_op:{kind}")
    return {
        "accounts": {a: accounts[a] for a in touched},
        "log_batches": log_batches,
        "applied": applied,
        "touched": touched,
        "native_apply": False,
    }


def evm_apply_writeback_ops(accounts: dict, ops: list) -> dict:
    """Apply writeback ops to an in-memory accounts map (v1.3.61)."""
    if _native is not None and hasattr(_native, "evm_apply_writeback_ops"):
        raw = _native.evm_apply_writeback_ops(
            json.dumps(accounts or {}),
            json.dumps(list(ops or [])),
        )
        out = json.loads(raw) if isinstance(raw, str) else dict(raw)
        out["native_apply"] = True
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_apply_writeback_ops")
    return _evm_apply_writeback_ops_py(accounts, ops)


def _evm_plan_nested_call_gas_py(
    remaining: int,
    requested: int,
    value_wei: int,
    kind: str,
) -> dict:
    kind_n = str(kind or "").strip().lower()
    if kind_n not in ("call", "callcode", "delegatecall", "staticcall"):
        raise ValueError("kind must be call|callcode|delegatecall|staticcall")
    remaining = max(0, int(remaining or 0))
    requested = max(0, int(requested or 0))
    value_wei = int(value_wei or 0)
    base_cap = (remaining * 63) // 64
    if requested > 0:
        base_cap = min(base_cap, requested)
    stipend_applied = value_wei > 0 and kind_n in ("call", "callcode")
    call_gas = min(remaining, base_cap + 2300) if stipend_applied else base_cap
    return {
        "kind": kind_n,
        "remaining": remaining,
        "requested": requested,
        "base_cap": base_cap,
        "stipend_applied": stipend_applied,
        "call_gas": call_gas,
        "stipend": 2300,
        "native_plan": False,
    }


def evm_plan_nested_call_gas(
    remaining: int,
    requested: int,
    value_wei: int,
    kind: str,
) -> dict:
    """Plan nested CALL gas (EIP-150 + 2300 stipend). Prefers abs_native."""
    if _native is not None and hasattr(_native, "evm_plan_nested_call_gas"):
        raw = _native.evm_plan_nested_call_gas(
            int(remaining or 0),
            int(requested or 0),
            int(value_wei or 0),
            str(kind),
        )
        out = json.loads(raw) if isinstance(raw, str) else dict(raw)
        out["native_plan"] = True
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_plan_nested_call_gas")
    return _evm_plan_nested_call_gas_py(remaining, requested, value_wei, kind)


def _evm_decode_nested_call_frame_py(
    op: int,
    stack_words: list,
    memory: Optional[bytes] = None,
) -> dict:
    op = int(op)
    kind_map = {
        0xF1: ("call", 7, True),
        0xF2: ("callcode", 7, True),
        0xF4: ("delegatecall", 6, False),
        0xFA: ("staticcall", 6, False),
    }
    if op not in kind_map:
        raise ValueError("op must be CALL/CALLCODE/DELEGATECALL/STATICCALL")
    kind, consume, has_value = kind_map[op]
    words = [int(x) for x in list(stack_words)]
    if len(words) < consume:
        raise ValueError("stack underflow")
    frame = words[-consume:]
    gas = frame[-1]
    to_word = frame[-2]
    if has_value:
        value = frame[-3]
        args_offset = frame[-4]
        args_size = frame[-5]
        ret_offset = frame[-6]
        ret_size = frame[-7]
    else:
        value = 0
        args_offset = frame[-3]
        args_size = frame[-4]
        ret_offset = frame[-5]
        ret_size = frame[-6]
    to_address = "0x" + format(to_word & ((1 << 160) - 1), "040x")
    out = {
        "op": op,
        "kind": kind,
        "stack_consumed": consume,
        "gas": str(gas),
        "to_word": str(to_word),
        "to_address": to_address,
        "value": str(value),
        "args_offset": str(args_offset),
        "args_size": str(args_size),
        "ret_offset": str(ret_offset),
        "ret_size": str(ret_size),
        "delegate": kind == "delegatecall",
        "static": kind == "staticcall",
        "callcode": kind == "callcode",
        "native_plan": False,
    }
    if memory is not None:
        data = evm_memory_slice(bytes(memory), int(args_offset), int(args_size))
        out["call_data_hex"] = bytes(data).hex()
    return out


def evm_decode_nested_call_frame(
    op: int,
    stack_words: list,
    memory: Optional[bytes] = None,
) -> dict:
    """Decode nested CALL stack frame. Prefers abs_native."""
    words = [str(int(x)) for x in list(stack_words)]
    if _native is not None and hasattr(_native, "evm_decode_nested_call_frame"):
        raw = _native.evm_decode_nested_call_frame(
            int(op),
            words,
            None if memory is None else bytes(memory),
        )
        out = json.loads(raw) if isinstance(raw, str) else dict(raw)
        out["native_plan"] = True
        return out
    if _REQUIRE_NATIVE:
        _require_native_kernel("evm_decode_nested_call_frame")
    return _evm_decode_nested_call_frame_py(op, stack_words, memory)


def evm_memory_copy(memory: bytearray, dest: int, src: bytes, src_offset: int, size: int) -> None:
    dest = int(dest)
    src_offset = int(src_offset)
    size = int(size)
    if _native is not None and hasattr(_native, "evm_memory_copy"):
        _native.evm_memory_copy(memory, dest, src, src_offset, size)
        return
    for i in range(size):
        byte = src[src_offset + i] if (src_offset + i) < len(src) else 0
        idx = dest + i
        if idx < len(memory):
            memory[idx] = byte


def evm_keccak256_memory(memory: bytes, offset: int, size: int) -> bytes:
    if _native is not None and hasattr(_native, "evm_keccak256_memory"):
        return bytes(_native.evm_keccak256_memory(memory, int(offset), int(size)))
    end = int(offset) + int(size)
    data = memory[int(offset):end] if int(offset) < len(memory) else b""
    if len(data) < int(size):
        data = data + (b"\x00" * (int(size) - len(data)))
    return keccak256_digest(data)


def evm_deploy_address_create(deployer: str, block_number: int, init_code_len: int) -> str:
    if _native is not None and hasattr(_native, "evm_deploy_address_create"):
        return str(_native.evm_deploy_address_create(
            str(deployer),
            int(block_number),
            int(init_code_len),
        ))
    _require_native_kernel("evm_deploy_address_create")
    seed = f"{deployer}{int(block_number)}{int(init_code_len)}"
    return "0x" + hashlib.sha256(seed.encode()).hexdigest()[:40]


def evm_deploy_address_create2_legacy(deployer: str, salt, init_code: bytes) -> str:
    salt_text = str(int(salt)) if isinstance(salt, int) else str(salt)
    if _native is not None and hasattr(_native, "evm_deploy_address_create2_legacy"):
        return str(_native.evm_deploy_address_create2_legacy(
            str(deployer),
            salt_text,
            bytes(init_code),
        ))
    _require_native_kernel("evm_deploy_address_create2_legacy")
    seed = f"create2:{deployer}:{salt_text}:{init_code.hex()}"
    return "0x" + hashlib.sha256(seed.encode()).hexdigest()[:40]


def evm_create2_address_eip1014(deployer: str, salt_word: int, init_code: bytes) -> str:
    salt_bytes = int(salt_word).to_bytes(32, "big")
    if _native is not None and hasattr(_native, "evm_create2_address_eip1014"):
        addr = bytes(_native.evm_create2_address_eip1014(
            str(deployer),
            salt_bytes,
            bytes(init_code),
        ))
        return "0x" + addr.hex()
    init_hash = keccak256_digest(init_code)
    prefix = b"\xff" + _address_to_bytes(deployer) + salt_bytes + init_hash
    return "0x" + keccak256_digest(prefix)[12:].hex()


def _address_to_bytes(address: str) -> bytes:
    raw = str(address or "").strip().lower().removeprefix("0x")
    if len(raw) != 40:
        raise ValueError("address must be 20-byte hex")
    return bytes.fromhex(raw)


def validate_imported_block_chain(
    blocks: List[dict],
    expected_parent_hash: str = "",
    start_height: int = 0,
) -> bool:
    """Fail-closed P2P sync gate: parent links + canonical block hash."""
    if not blocks:
        return True
    payloads = [
        json.dumps(block, separators=(",", ":"), ensure_ascii=False)
        for block in blocks
    ]
    if _native is not None and hasattr(_native, "validate_imported_block_chain"):
        return bool(_native.validate_imported_block_chain(
            payloads,
            str(expected_parent_hash or ""),
            int(start_height),
        ))
    _require_native_kernel("validate_imported_block_chain")

    previous_hash = str(expected_parent_hash or "")
    previous_height = int(start_height)
    computed_hashes = block_canonical_hash_batch(blocks)
    for block, canonical_hash in zip(blocks, computed_hashes):
        height = int(block.get("height", block.get("number", 0)) or 0)
        block_hash = str(block.get("hash", block.get("block_hash", "")) or "")
        parent_hash = str(block.get("parent_hash", block.get("parent", "")) or "")
        if not block_hash or height != previous_height + 1:
            return False
        if previous_hash and parent_hash != previous_hash:
            return False
        if canonical_hash != block_hash:
            return False
        previous_hash = block_hash
        previous_height = height
    return True


def validate_peer_header_chain(
    headers: List[tuple[int, str, str, str, str, str, int, str]],
    expected_parent_hash: str = "",
    start_height: int = 0,
) -> bool:
    """Validate contiguous peer headers and recomputed header hashes."""
    if not headers:
        return True
    if _native is not None and hasattr(_native, "validate_peer_header_chain"):
        payload = [
            (
                int(number),
                str(block_hash),
                str(parent_hash),
                str(proposer),
                str(state_root),
                str(tx_root),
                int(timestamp),
                str(extra_data or ""),
            )
            for number, block_hash, parent_hash, proposer, state_root, tx_root, timestamp, extra_data in headers
        ]
        return bool(_native.validate_peer_header_chain(
            payload,
            str(expected_parent_hash or ""),
            int(start_height),
        ))

    previous_hash = str(expected_parent_hash or "")
    previous_height = int(start_height)
    for number, block_hash, parent_hash, proposer, state_root, tx_root, timestamp, extra_data in headers:
        if not block_hash or int(number) != previous_height + 1:
            return False
        if previous_hash and parent_hash != previous_hash:
            return False
        if block_header_hash(
            number, parent_hash, proposer, state_root, tx_root, timestamp, extra_data
        ) != block_hash:
            return False
        previous_hash = block_hash
        previous_height = int(number)
    return True


def sha256_hex(data: bytes) -> str:
    if _native is not None:
        return _native.sha256_hex(data)
    _require_native_kernel("sha256_hex")
    return hashlib.sha256(data).hexdigest()


def sha256_hex_batch(items: List[bytes]) -> List[str]:
    if _native is not None and hasattr(_native, "sha256_hex_batch"):
        return [str(value) for value in _native.sha256_hex_batch(items)]
    _require_native_kernel("sha256_hex_batch")
    return [hashlib.sha256(item).hexdigest() for item in items]


def double_sha256_hex(data: bytes) -> str:
    if _native is not None:
        return _native.double_sha256_hex(data)
    _require_native_kernel("double_sha256_hex")
    return hashlib.sha256(hashlib.sha256(data).digest()).hexdigest()


def merkle_root(items: List[Any]) -> str:
    string_items = _string_items(items)
    if _native is not None:
        return _native.merkle_root(string_items)
    _require_native_kernel("merkle_root")
    return _python_merkle_root_strings(string_items)


def generate_proof(items: List[Any], target_index: int) -> List[str]:
    string_items = _string_items(items)
    if target_index < 0:
        return []
    if _native is not None:
        return _native.generate_proof(string_items, target_index)
    _require_native_kernel("generate_proof")
    return _python_generate_proof_strings(string_items, target_index)


def verify_proof(item: Any, proof: List[str], expected_root: str, target_index: int) -> bool:
    if target_index < 0:
        return False
    item_str = str(item)
    if _native is not None:
        return bool(_native.verify_proof(item_str, proof, expected_root, target_index))
    _require_native_kernel("verify_proof")
    return merkle_root_from_proof(item_str, proof, target_index) == expected_root


def merkle_root_from_proof(item: Any, proof: List[str], target_index: int) -> str:
    if target_index < 0:
        return hash_data(item)
    item_str = str(item)
    if _native is not None:
        return _native.merkle_root_from_proof(item_str, proof, target_index)
    return _python_merkle_root_from_proof_string(item_str, proof, target_index)


def state_root_from_accounts_json(accounts_json: str) -> str:
    from runtime.state_root_encoding import tip_encoding_version

    ver = tip_encoding_version()
    accounts = json.loads(accounts_json)
    if ver >= 2:
        # Wave C: native tip hasher emits integer b_satoshi leaves.
        if _native is not None:
            return _native.state_root_from_accounts_json(accounts_json)
        return _python_state_root_from_accounts(accounts, encoding_version=2)
    # Legacy v1 float tip — Python only (native tip path is satoshi-only).
    return _python_state_root_from_accounts(accounts, encoding_version=1)


def _account_blob_to_row(blob: bytes) -> dict:
    """Decode ABAR binary or legacy JSON account blob to a row dict."""
    raw = bytes(blob or b"")
    if _native is not None and hasattr(_native, "account_blob_to_json"):
        try:
            row = json.loads(_native.account_blob_to_json(raw))
            if isinstance(row, dict):
                return row
        except Exception:
            pass
    return json.loads(raw.decode("utf-8"))


def state_root_from_account_blobs(blobs: List[bytes]) -> str:
    from runtime.state_root_encoding import tip_encoding_version

    ver = tip_encoding_version()
    if ver >= 2:
        if _native is not None and hasattr(_native, "state_root_from_account_blobs"):
            return _native.state_root_from_account_blobs(list(blobs))
        accounts = [_account_blob_to_row(blob) for blob in blobs]
        accounts = sorted(accounts, key=lambda row: str(row.get("address", "")))
        return _python_state_root_from_accounts(accounts, encoding_version=2)
    # Legacy v1 float tip — decode ABAR via native, hash in Python.
    accounts = [_account_blob_to_row(blob) for blob in blobs]
    accounts = sorted(accounts, key=lambda row: str(row.get("address", "")))
    return _python_state_root_from_accounts(accounts, encoding_version=1)


def state_root_accumulator_available() -> bool:
    return _native is not None and hasattr(_native, "StateRootAccumulator")


def new_state_root_accumulator():
    if not state_root_accumulator_available():
        _require_native_kernel("StateRootAccumulator")
    return _native.StateRootAccumulator()


def state_root_accumulator_root_from_blobs(blobs: List[bytes]) -> str:
    from runtime.state_root_encoding import tip_encoding_version

    # Accumulator uses the same account_payload_row (satoshi tip after Wave C).
    if tip_encoding_version() >= 2 and state_root_accumulator_available():
        acc = new_state_root_accumulator()
        if blobs:
            acc.load_from_blobs(list(blobs))
        return acc.root()
    return state_root_from_account_blobs(list(blobs))


def verify_secp256k1_sha256(
    message: bytes, signature_der: bytes, public_key_xy: bytes
) -> Optional[bool]:
    if _native is None:
        return None
    try:
        return bool(_native.verify_secp256k1_sha256(
            message, signature_der, public_key_xy
        ))
    except Exception:
        return False


def verify_secp256k1_sha256_batch(
    items: List[tuple[bytes, bytes, bytes]]
) -> Optional[List[bool]]:
    if _native is None:
        return None
    try:
        return [
            bool(result)
            for result in _native.verify_secp256k1_sha256_batch(items)
        ]
    except Exception:
        return [False for _ in items]


def consensus_stake_weighted_proposer(
    validators: List[tuple[str, float, bool]],
    epoch: int,
    slot: int,
) -> Optional[str]:
    """Deterministic stake-weighted proposer (consensus_engine contract)."""
    payload = [
        (str(addr), float(stake), bool(active))
        for addr, stake, active in validators
    ]
    if _native is not None and hasattr(_native, "consensus_stake_weighted_proposer"):
        result = _native.consensus_stake_weighted_proposer(payload, int(epoch), int(slot))
        return str(result) if result else None
    total_stake = sum(stake for _, stake, active in payload if active and stake > 0)
    if total_stake <= 0:
        return None
    digest = sha256_hex(f"abs-proposer:{int(epoch)}:{int(slot)}".encode())
    ratio = int(digest[:16], 16) / float(16 ** 16)
    pick = ratio * total_stake
    current = 0.0
    for addr, stake, _active in sorted(
        ((a, s, act) for a, s, act in payload if _active and s > 0),
        key=lambda row: row[0],
    ):
        current += stake
        if current >= pick:
            return addr
    return None


def consensus_fisher_yates_committee(
    validators: List[tuple[str, float, bool]],
    slot: int,
    committee_size: int,
) -> List[str]:
    """Deterministic Fisher-Yates committee shuffle (consensus_engine contract)."""
    payload = [
        (str(addr), float(stake), bool(active))
        for addr, stake, active in validators
    ]
    if _native is not None and hasattr(_native, "consensus_fisher_yates_committee"):
        return [
            str(addr)
            for addr in _native.consensus_fisher_yates_committee(
                payload, int(slot), int(committee_size)
            )
        ]
    active_rows = sorted(
        [(addr, stake) for addr, stake, active in payload if active and stake > 0],
        key=lambda row: row[0],
    )
    if not active_rows:
        return []
    size = max(1, min(int(committee_size), len(active_rows)))
    order = [addr for addr, _ in active_rows]
    digest = sha256_hex(f"abs-committee:{int(slot)}".encode())
    for i in range(len(order) - 1, 0, -1):
        mix = int(sha256_hex(f"{digest}:{i}".encode())[:8], 16)
        j = mix % (i + 1)
        order[i], order[j] = order[j], order[i]
    return order[:size]


def validator_selection_proposer(
    seed: str,
    epoch: int,
    slot: int,
    validators: List[tuple[str, int]],
) -> Optional[str]:
    payload = [(str(addr), int(stake)) for addr, stake in validators]
    if _native is not None and hasattr(_native, "validator_selection_proposer"):
        result = _native.validator_selection_proposer(
            str(seed), int(epoch), int(slot), payload
        )
        return str(result) if result else None
    ranked = sorted(
        payload,
        key=lambda item: int(
            hash_text("|".join((str(seed), str(epoch), "proposer", str(slot), item[0]))),
            16,
        ),
    )
    return ranked[0][0] if ranked else None


def validator_selection_proposer_weighted(
    seed: str,
    epoch: int,
    slot: int,
    validators: List[tuple[str, int]],
) -> Optional[str]:
    payload = [(str(addr), int(stake)) for addr, stake in validators]
    if _native is not None and hasattr(_native, "validator_selection_proposer_weighted"):
        result = _native.validator_selection_proposer_weighted(
            str(seed), int(epoch), int(slot), payload
        )
        return str(result) if result else None
    canonical = sorted(payload, key=lambda item: item[0])
    total_stake = sum(stake for _, stake in canonical)
    if total_stake <= 0:
        return validator_selection_proposer(seed, epoch, slot, validators)
    target = int(
        hash_text("|".join((str(seed), str(epoch), "weighted-proposer", str(slot)))),
        16,
    ) % total_stake
    cumulative = 0
    for address, stake in canonical:
        cumulative += stake
        if cumulative > target:
            return address
    return canonical[0][0] if canonical else None


def validator_selection_committee(
    seed: str,
    epoch: int,
    validators: List[tuple[str, int]],
    committee_size: int,
) -> List[str]:
    payload = [(str(addr), int(stake)) for addr, stake in validators]
    if _native is not None and hasattr(_native, "validator_selection_committee"):
        return [
            str(addr)
            for addr in _native.validator_selection_committee(
                str(seed), int(epoch), payload, int(committee_size)
            )
        ]
    ranked = sorted(
        payload,
        key=lambda item: int(
            hash_text("|".join((str(seed), str(epoch), "committee", item[0]))),
            16,
        ),
    )
    take = min(int(committee_size), len(ranked))
    return [addr for addr, _ in ranked[:take]]


def validator_selection_shuffle(
    seed: str,
    epoch: int,
    validators: List[tuple[str, int]],
) -> List[tuple[str, int]]:
    payload = [(str(addr), int(stake)) for addr, stake in validators]
    if _native is not None and hasattr(_native, "validator_selection_shuffle"):
        return [
            (str(addr), int(stake))
            for addr, stake in _native.validator_selection_shuffle(
                str(seed), int(epoch), payload
            )
        ]
    ranked = sorted(
        payload,
        key=lambda item: int(
            hash_text("|".join((str(seed), str(epoch), "shuffle", item[0]))),
            16,
        ),
    )
    return ranked


def state_engine_root_from_accounts_json(accounts_json: str) -> str:
    if _native is not None and hasattr(_native, "state_engine_root_from_accounts_json"):
        return str(_native.state_engine_root_from_accounts_json(accounts_json))
    return sha256_hex(accounts_json.encode())[:32]


def amount_to_satoshi(amount_abs: str) -> int:
    if _native is not None and hasattr(_native, "amount_to_satoshi"):
        return int(_native.amount_to_satoshi(str(amount_abs)))
    from decimal import Decimal, ROUND_DOWN

    d = Decimal(str(amount_abs))
    return int((d * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_DOWN))


def amount_apply_delta_satoshi(current_sat: int, delta_abs: str) -> int:
    if _native is not None and hasattr(_native, "amount_apply_delta_satoshi"):
        return int(_native.amount_apply_delta_satoshi(int(current_sat), str(delta_abs)))
    return max(0, int(current_sat) + amount_to_satoshi(delta_abs))


def amount_from_satoshi_float(satoshi: int) -> float:
    if _native is not None and hasattr(_native, "amount_from_satoshi_float"):
        return float(_native.amount_from_satoshi_float(int(satoshi)))
    return float(int(satoshi)) / 1_000_000.0


def state_engine_apply_transactions(accounts_json: str, txs_json: str) -> str:
    if _native is not None and hasattr(_native, "state_engine_apply_transactions"):
        return str(_native.state_engine_apply_transactions(accounts_json, txs_json))
    raise RuntimeError("state_engine_apply_transactions requires abs_native")


def ghost_cumulative_weight(block_hash: str, tree_json: str, weights_json: str) -> int:
    _require_native_kernel("ghost_cumulative_weight")
    if _native is not None and hasattr(_native, "ghost_cumulative_weight"):
        return int(_native.ghost_cumulative_weight(block_hash, tree_json, weights_json))
    raise RuntimeError("ghost_cumulative_weight requires abs_native")


def ghost_select_head(tree_json: str, weights_json: str):
    _require_native_kernel("ghost_select_head")
    if _native is not None and hasattr(_native, "ghost_select_head"):
        return _native.ghost_select_head(tree_json, weights_json)
    raise RuntimeError("ghost_select_head requires abs_native")


def ghost_chain_from_head(tree_json: str, weights_json: str):
    _require_native_kernel("ghost_chain_from_head")
    if _native is not None and hasattr(_native, "ghost_chain_from_head"):
        return list(_native.ghost_chain_from_head(tree_json, weights_json))
    raise RuntimeError("ghost_chain_from_head requires abs_native")


def lmd_compute_weights(votes_json: str, stakes_json: str) -> str:
    _require_native_kernel("lmd_compute_weights")
    if _native is not None and hasattr(_native, "lmd_compute_weights"):
        return str(_native.lmd_compute_weights(votes_json, stakes_json))
    raise RuntimeError("lmd_compute_weights requires abs_native")


def blockchain_apply_simple_block(
    accounts_json: str,
    txs_json: str,
    gas_price_wei: float,
    burn_rate: float,
    proposer: str,
    burn_address: str,
    block_reward_abs: float,
    current_supply_sat: int,
    max_supply_sat: int,
) -> str:
    _require_native_kernel("blockchain_apply_simple_block")
    if _native is not None and hasattr(_native, "blockchain_apply_simple_block"):
        return str(
            _native.blockchain_apply_simple_block(
                accounts_json,
                txs_json,
                float(gas_price_wei),
                float(burn_rate),
                str(proposer or ""),
                str(burn_address or ""),
                float(block_reward_abs),
                int(current_supply_sat),
                int(max_supply_sat),
            )
        )
    raise RuntimeError("blockchain_apply_simple_block requires abs_native")


def blockchain_apply_host_effects(
    accounts_json: str,
    effects_json: str,
    gas_price_wei: float,
    burn_rate: float,
    proposer: str,
    burn_address: str,
    block_reward_abs: float,
    current_supply_sat: int,
    max_supply_sat: int,
) -> str:
    _require_native_kernel("blockchain_apply_host_effects")
    if _native is not None and hasattr(_native, "blockchain_apply_host_effects"):
        return str(
            _native.blockchain_apply_host_effects(
                accounts_json,
                effects_json,
                float(gas_price_wei),
                float(burn_rate),
                str(proposer or ""),
                str(burn_address or ""),
                float(block_reward_abs),
                int(current_supply_sat),
                int(max_supply_sat),
            )
        )
    raise RuntimeError("blockchain_apply_host_effects requires abs_native")


def blockchain_replay_simple_blocks(
    accounts_json: str,
    blocks_json: str,
    gas_price_wei: float,
    burn_rate: float,
    burn_address: str,
    block_reward_abs: float,
    current_supply_sat: int,
    max_supply_sat: int,
) -> str:
    _require_native_kernel("blockchain_replay_simple_blocks")
    if _native is not None and hasattr(_native, "blockchain_replay_simple_blocks"):
        return str(
            _native.blockchain_replay_simple_blocks(
                accounts_json,
                blocks_json,
                float(gas_price_wei),
                float(burn_rate),
                str(burn_address or ""),
                float(block_reward_abs),
                int(current_supply_sat),
                int(max_supply_sat),
            )
        )
    raise RuntimeError("blockchain_replay_simple_blocks requires abs_native")


def ffg_threshold(total_stake: int, threshold_numer: int = 2, threshold_denom: int = 3) -> int:
    _require_native_kernel("ffg_threshold")
    if _native is not None and hasattr(_native, "ffg_threshold"):
        return int(_native.ffg_threshold(int(total_stake), int(threshold_numer), int(threshold_denom)))
    raise RuntimeError("ffg_threshold requires abs_native")


def ffg_best_checkpoint(votes_json: str):
    _require_native_kernel("ffg_best_checkpoint")
    if _native is not None and hasattr(_native, "ffg_best_checkpoint"):
        return _native.ffg_best_checkpoint(votes_json)
    raise RuntimeError("ffg_best_checkpoint requires abs_native")


def ffg_accumulate_vote(votes_json: str, block_hash: str, weight: int) -> str:
    _require_native_kernel("ffg_accumulate_vote")
    if _native is not None and hasattr(_native, "ffg_accumulate_vote"):
        return str(_native.ffg_accumulate_vote(votes_json, str(block_hash), int(weight)))
    raise RuntimeError("ffg_accumulate_vote requires abs_native")


def ffg_evaluate_epoch(
    epoch: int,
    votes_for_epoch_json: str,
    total_stake: int,
    justified_epochs_json: str,
    finalized_epochs_json: str,
    threshold_numer: int = 2,
    threshold_denom: int = 3,
) -> str:
    _require_native_kernel("ffg_evaluate_epoch")
    if _native is not None and hasattr(_native, "ffg_evaluate_epoch"):
        return str(
            _native.ffg_evaluate_epoch(
                int(epoch),
                votes_for_epoch_json,
                int(total_stake),
                justified_epochs_json,
                finalized_epochs_json,
                int(threshold_numer),
                int(threshold_denom),
            )
        )
    raise RuntimeError("ffg_evaluate_epoch requires abs_native")


def fe_epoch(block_number: int, epoch_length: int = 32) -> int:
    _require_native_kernel("fe_epoch")
    if _native is not None and hasattr(_native, "fe_epoch"):
        return int(_native.fe_epoch(int(block_number), int(epoch_length)))
    raise RuntimeError("fe_epoch requires abs_native")


def fe_quorum_reached(vote_count: int, active_validator_count: int) -> bool:
    _require_native_kernel("fe_quorum_reached")
    if _native is not None and hasattr(_native, "fe_quorum_reached"):
        return bool(_native.fe_quorum_reached(int(vote_count), int(active_validator_count)))
    raise RuntimeError("fe_quorum_reached requires abs_native")


def fe_can_finalize(epoch: int, justified_epochs_json: str) -> bool:
    _require_native_kernel("fe_can_finalize")
    if _native is not None and hasattr(_native, "fe_can_finalize"):
        return bool(_native.fe_can_finalize(int(epoch), justified_epochs_json))
    raise RuntimeError("fe_can_finalize requires abs_native")


def slash_check_double_vote(new_hash: str, prior_hash: Optional[str] = None) -> str:
    _require_native_kernel("slash_check_double_vote")
    if _native is not None and hasattr(_native, "slash_check_double_vote"):
        return str(_native.slash_check_double_vote(str(new_hash), prior_hash))
    raise RuntimeError("slash_check_double_vote requires abs_native")


def slash_check_double_proposal(already_proposed: bool) -> str:
    _require_native_kernel("slash_check_double_proposal")
    if _native is not None and hasattr(_native, "slash_check_double_proposal"):
        return str(_native.slash_check_double_proposal(bool(already_proposed)))
    raise RuntimeError("slash_check_double_proposal requires abs_native")


def decode_eth_raw_tx(raw: bytes) -> str:
    _require_native_kernel("decode_eth_raw_tx")
    if _native is not None and hasattr(_native, "decode_eth_raw_tx"):
        return str(_native.decode_eth_raw_tx(bytes(raw)))
    raise RuntimeError("decode_eth_raw_tx requires abs_native")


def decode_eth_raw_tx_hex(raw_hex: str) -> str:
    _require_native_kernel("decode_eth_raw_tx_hex")
    if _native is not None and hasattr(_native, "decode_eth_raw_tx_hex"):
        return str(_native.decode_eth_raw_tx_hex(str(raw_hex)))
    raise RuntimeError("decode_eth_raw_tx_hex requires abs_native")


def rocks_key_account(address: str) -> bytes:
    _require_native_kernel("rocks_key_account")
    if _native is not None and hasattr(_native, "rocks_key_account"):
        return bytes(_native.rocks_key_account(str(address)))
    raise RuntimeError("rocks_key_account requires abs_native")


def rocks_pack_u64(value: int) -> bytes:
    _require_native_kernel("rocks_pack_u64")
    if _native is not None and hasattr(_native, "rocks_pack_u64"):
        return bytes(_native.rocks_pack_u64(int(value) & 0xFFFFFFFFFFFFFFFF))
    raise RuntimeError("rocks_pack_u64 requires abs_native")


def rocks_key_block_height(height: int) -> bytes:
    _require_native_kernel("rocks_key_block_height")
    if _native is not None and hasattr(_native, "rocks_key_block_height"):
        return bytes(_native.rocks_key_block_height(int(height) & 0xFFFFFFFFFFFFFFFF))
    raise RuntimeError("rocks_key_block_height requires abs_native")


def rocks_unpack_u64(data: bytes) -> int:
    _require_native_kernel("rocks_unpack_u64")
    if _native is not None and hasattr(_native, "rocks_unpack_u64"):
        return int(_native.rocks_unpack_u64(bytes(data)))
    raise RuntimeError("rocks_unpack_u64 requires abs_native")


def P2PRateLimitTable(*args, **kwargs):
    _require_native_kernel("P2PRateLimitTable")
    if _native is not None and hasattr(_native, "P2PRateLimitTable"):
        return _native.P2PRateLimitTable(*args, **kwargs)
    raise RuntimeError("P2PRateLimitTable requires abs_native")


def P2PConnectionGovernor(*args, **kwargs):
    _require_native_kernel("P2PConnectionGovernor")
    if _native is not None and hasattr(_native, "P2PConnectionGovernor"):
        return _native.P2PConnectionGovernor(*args, **kwargs)
    raise RuntimeError("P2PConnectionGovernor requires abs_native")


def p2p_subnet_key(ip: str) -> str:
    """IPv4 /24 or IPv6 /64 subnet key (v1.3.89)."""
    _require_native_kernel("p2p_subnet_key")
    if _native is not None and hasattr(_native, "p2p_subnet_key"):
        return str(_native.p2p_subnet_key(str(ip or "")))
    raise RuntimeError("p2p_subnet_key requires abs_native")


def p2p_ip_is_public(ip: str) -> bool:
    """True for globally routable IPs (v1.3.89 Sybil/Eclipse)."""
    _require_native_kernel("p2p_ip_is_public")
    if _native is not None and hasattr(_native, "p2p_ip_is_public"):
        return bool(_native.p2p_ip_is_public(str(ip or "")))
    raise RuntimeError("p2p_ip_is_public requires abs_native")


def p2p_peer_addr_is_dialable(addr: str, *, allow_private: bool = False) -> bool:
    """v1.3.128: discovery dial target policy (host:port).

    Fail-closed without native when private dials are disallowed.
    """
    if _native is not None and hasattr(_native, "p2p_peer_addr_is_dialable"):
        return bool(
            _native.p2p_peer_addr_is_dialable(str(addr or ""), bool(allow_private))
        )
    if allow_private:
        s = str(addr or "").strip()
        return bool(s) and ":" in s
    return False


def P2PNativeListener(*args, **kwargs):
    """Native plain-TCP listener (v1.3.90)."""
    _require_native_kernel("P2PNativeListener")
    if _native is not None and hasattr(_native, "P2PNativeListener"):
        return _native.P2PNativeListener(*args, **kwargs)
    raise RuntimeError("P2PNativeListener requires abs_native")


def P2PNativeConn(*args, **kwargs):
    """Native framed TCP connection (v1.3.90). Prefer p2p_native_connect()."""
    _require_native_kernel("P2PNativeConn")
    if _native is not None and hasattr(_native, "P2PNativeConn"):
        return _native.P2PNativeConn(*args, **kwargs)
    raise RuntimeError("P2PNativeConn requires abs_native")


def p2p_native_connect(
    host: str,
    port: int,
    max_bytes: int = 2 * 1024 * 1024,
    timeout_ms: int = 10_000,
    cert_path: str | None = None,
    key_path: str | None = None,
    ca_path: str | None = None,
):
    """Outbound TCP(+TLS) framed connect (v1.3.90/91)."""
    _require_native_kernel("P2PNativeConn")
    if _native is not None and hasattr(_native, "P2PNativeConn"):
        return _native.P2PNativeConn.connect(
            str(host),
            int(port),
            int(max_bytes),
            int(timeout_ms),
            None if not cert_path else str(cert_path),
            None if not key_path else str(key_path),
            None if not ca_path else str(ca_path),
        )
    raise RuntimeError("P2PNativeConn requires abs_native")


def p2p_native_transport_available() -> bool:
    if _native is not None and hasattr(_native, "p2p_native_transport_available"):
        return bool(_native.p2p_native_transport_available())
    return False


def p2p_native_tls_available() -> bool:
    if _native is not None and hasattr(_native, "p2p_native_tls_available"):
        return bool(_native.p2p_native_tls_available())
    return False


def p2p_native_clamp_batch(n: int) -> int:
    """Clamp native read/write batch size to 1..64 (v1.3.101)."""
    if _native is not None and hasattr(_native, "p2p_native_clamp_batch"):
        return int(_native.p2p_native_clamp_batch(int(n)))
    return max(1, min(64, int(n)))


def p2p_native_clamp_chunk(n: int) -> int:
    """Clamp native read chunk bytes to 1024..1MiB (v1.3.101)."""
    if _native is not None and hasattr(_native, "p2p_native_clamp_chunk"):
        return int(_native.p2p_native_clamp_chunk(int(n)))
    return max(1024, min(1024 * 1024, int(n)))


def p2p_native_clamp_timeout_ms(n: int) -> int:
    """Clamp native socket I/O timeout to 1000..600000 ms (v1.3.102)."""
    if _native is not None and hasattr(_native, "p2p_native_clamp_timeout_ms"):
        return int(_native.p2p_native_clamp_timeout_ms(int(n)))
    return max(1000, min(600_000, int(n)))


def P2PLineFramer(*args, **kwargs):
    """Native NDJSON line framer (v1.3.86)."""
    _require_native_kernel("P2PLineFramer")
    if _native is not None and hasattr(_native, "P2PLineFramer"):
        return _native.P2PLineFramer(*args, **kwargs)
    raise RuntimeError("P2PLineFramer requires abs_native")


def p2p_frame_feed_once(chunk: bytes, max_bytes: int = 2 * 1024 * 1024):
    """One-shot framer feed for tests (v1.3.86)."""
    _require_native_kernel("p2p_frame_feed_once")
    if _native is not None and hasattr(_native, "p2p_frame_feed_once"):
        return _native.p2p_frame_feed_once(bytes(chunk), int(max_bytes))
    raise RuntimeError("p2p_frame_feed_once requires abs_native")


def p2p_ingress_admit(
    line: bytes,
    peer_id: str,
    now: float,
    max_bytes: int = 2 * 1024 * 1024,
    allowed_types: Optional[List[str]] = None,
    rl=None,
):
    """Native wire+rate+bandwidth ingress admit. Returns {ok, type/data} or {ok:False, reason}."""
    _require_native_kernel("p2p_ingress_admit")
    if _native is not None and hasattr(_native, "p2p_ingress_admit"):
        return _native.p2p_ingress_admit(
            bytes(line),
            str(peer_id or ""),
            float(now),
            int(max_bytes),
            list(allowed_types) if allowed_types is not None else None,
            rl,
        )
    raise RuntimeError("p2p_ingress_admit requires abs_native")


def p2p_ingress_cost_units(msg_type: str, nbytes: int) -> int:
    """Cost-weighted units for per-peer bandwidth budget (v1.3.78)."""
    _require_native_kernel("p2p_ingress_cost_units")
    if _native is not None and hasattr(_native, "p2p_ingress_cost_units"):
        return int(_native.p2p_ingress_cost_units(str(msg_type), int(nbytes)))
    raise RuntimeError("p2p_ingress_cost_units requires abs_native")


def p2p_egress_cost_units(msg_type: str, nbytes: int) -> int:
    """Cost-weighted units for outbound bandwidth budget (v1.3.85)."""
    _require_native_kernel("p2p_egress_cost_units")
    if _native is not None and hasattr(_native, "p2p_egress_cost_units"):
        return int(_native.p2p_egress_cost_units(str(msg_type), int(nbytes)))
    raise RuntimeError("p2p_egress_cost_units requires abs_native")


def p2p_egress_admit(
    peer_id: str,
    nbytes: int,
    now: float,
    msg_type: str = "",
    rl=None,
):
    """Outbound bandwidth admit (v1.3.85). Returns {ok} / {ok:false, reason}."""
    _require_native_kernel("p2p_egress_admit")
    if _native is not None and hasattr(_native, "p2p_egress_admit"):
        return _native.p2p_egress_admit(
            str(peer_id),
            int(nbytes),
            float(now),
            str(msg_type or ""),
            rl,
        )
    raise RuntimeError("p2p_egress_admit requires abs_native")


def p2p_egress_prepare(
    msg_type: str,
    data_json: str,
    peer_id: str,
    now: float,
    max_bytes: int = 2 * 1024 * 1024,
    allowed_types: Optional[List[str]] = None,
    rl=None,
    codec: Optional[str] = None,
):
    """Encode + allowlist + size + egress admit (v1.3.87). Returns {ok, payload} / reject.

    ``codec``: ``v1`` (NDJSON) or ``v2`` (AB2 Borsh). Defaults to ``ABS_P2P_WIRE_CODEC``.
    """
    _require_native_kernel("p2p_egress_prepare")
    mode = codec if codec is not None else p2p_wire_codec_mode()
    if _native is not None and hasattr(_native, "p2p_egress_prepare"):
        return _native.p2p_egress_prepare(
            str(msg_type or ""),
            str(data_json if data_json is not None else "null"),
            str(peer_id or ""),
            float(now),
            int(max_bytes),
            list(allowed_types) if allowed_types is not None else None,
            rl,
            str(mode or "v1"),
        )
    raise RuntimeError("p2p_egress_prepare requires abs_native")


def p2p_rate_limit_is_exempt(msg_type: str) -> bool:
    _require_native_kernel("p2p_rate_limit_is_exempt")
    if _native is not None and hasattr(_native, "p2p_rate_limit_is_exempt"):
        return bool(_native.p2p_rate_limit_is_exempt(str(msg_type)))
    raise RuntimeError("p2p_rate_limit_is_exempt requires abs_native")


def p2p_rate_limit_tick(count: int, start: float, now: float, limit: int):
    _require_native_kernel("p2p_rate_limit_tick")
    if _native is not None and hasattr(_native, "p2p_rate_limit_tick"):
        return _native.p2p_rate_limit_tick(int(count), float(start), float(now), int(limit))
    raise RuntimeError("p2p_rate_limit_tick requires abs_native")


def p2p_strike_should_ban(strikes: int, max_strikes: int) -> bool:
    _require_native_kernel("p2p_strike_should_ban")
    if _native is not None and hasattr(_native, "p2p_strike_should_ban"):
        return bool(_native.p2p_strike_should_ban(int(strikes), int(max_strikes)))
    raise RuntimeError("p2p_strike_should_ban requires abs_native")


def plan_transfer_fees(
    gas: int,
    gas_price_wei: float,
    burn_rate: float,
    value: float = 0.0,
    gas_used: Optional[int] = None,
):
    if _native is not None and hasattr(_native, "plan_transfer_fees"):
        return _native.plan_transfer_fees(
            int(gas),
            float(gas_price_wei),
            float(burn_rate),
            float(value),
            int(gas_used) if gas_used is not None else None,
        )
    fee_s, burned_s, miner_s, total_s = plan_transfer_fees_satoshi(
        gas, str(gas_price_wei), str(burn_rate), str(value), gas_used
    )
    return (
        amount_from_satoshi_float(fee_s),
        amount_from_satoshi_float(burned_s),
        amount_from_satoshi_float(miner_s),
        amount_from_satoshi_float(total_s),
    )


def plan_transfer_fees_satoshi(
    gas: int,
    gas_price_wei: str,
    burn_rate: str,
    value: str = "0",
    gas_used: Optional[int] = None,
):
    if _native is not None and hasattr(_native, "plan_transfer_fees_satoshi"):
        return _native.plan_transfer_fees_satoshi(
            int(gas),
            str(gas_price_wei),
            str(burn_rate),
            str(value),
            int(gas_used) if gas_used is not None else None,
        )
    from runtime.amount import plan_transfer_fees_sat

    sat = plan_transfer_fees_sat(
        int(gas), gas_price_wei, burn_rate, value, gas_used=gas_used
    )
    return (
        sat["fee_sat"],
        sat["burned_sat"],
        sat["miner_fee_sat"],
        sat["total_cost_sat"],
    )


def can_afford_transfer(sender_sat: int, total_cost_abs: float) -> bool:
    if _native is not None and hasattr(_native, "can_afford_transfer"):
        return bool(_native.can_afford_transfer(int(sender_sat), float(total_cost_abs)))
    return int(sender_sat) >= amount_to_satoshi(str(total_cost_abs))


def validate_p2p_status_payload(data: Any) -> Optional[dict]:
    """Normalize/validate gossip status payload; None if malformed."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_status_payload"):
        result = _native.validate_p2p_status_payload(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        try:
            data = json.loads(payload)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    try:
        height = int(data.get("height", 0) or 0)
    except (TypeError, ValueError):
        return None
    if height < 0 or height > 1_000_000_000_000:
        return None
    head_hash = str(data.get("head_hash") or "").strip()
    if len(head_hash) > 128:
        return None
    return {"height": height, "head_hash": head_hash}


def validate_p2p_attestation_payload(data: Any) -> bool:
    """Fail-closed shape check for attestation gossip (before sig verify)."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_attestation_payload"):
        return bool(_native.validate_p2p_attestation_payload(payload))
    if not isinstance(data, dict):
        try:
            data = json.loads(payload)
        except Exception:
            return False
    if not isinstance(data, dict):
        return False
    validator = data.get("validator")
    target_hash = data.get("target_hash")
    signature = data.get("signature")
    public_key = data.get("public_key")
    if not isinstance(validator, str) or not validator or len(validator) > 128:
        return False
    if not isinstance(target_hash, str) or not target_hash or len(target_hash) > 128:
        return False
    if not isinstance(signature, str) or not signature or len(signature) % 2 or len(signature) > 512:
        return False
    if not isinstance(public_key, str) or not public_key or len(public_key) % 2 or len(public_key) > 130:
        return False
    try:
        int(signature, 16)
        int(public_key, 16)
    except ValueError:
        return False
    return True


def validate_p2p_block_announce(data: Any) -> Optional[dict]:
    """Fail-closed block gossip shape: height + hash (+ tx count bound)."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_block_announce"):
        result = _native.validate_p2p_block_announce(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        try:
            data = json.loads(payload)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    try:
        height = int(data.get("height", data.get("number", 0)) or 0)
    except (TypeError, ValueError):
        return None
    if height < 0 or height > 1_000_000_000_000:
        return None
    block_hash = str(data.get("hash") or "").strip()
    if not block_hash or len(block_hash) > 128:
        return None
    txs = data.get("transactions")
    if txs is not None and (not isinstance(txs, list) or len(txs) > 10_000):
        return None
    return {"height": height, "hash": block_hash}


def validate_p2p_state_root_request(data: Any) -> Optional[int]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_state_root_request"):
        result = _native.validate_p2p_state_root_request(payload)
        return int(result) if result is not None else None
    if not isinstance(data, dict):
        try:
            data = json.loads(payload)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    try:
        height = int(data.get("height", 0) or 0)
    except (TypeError, ValueError):
        return None
    if height < 0 or height > 1_000_000_000_000:
        return None
    return height


def validate_p2p_state_root_response(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_state_root_response"):
        result = _native.validate_p2p_state_root_response(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        try:
            data = json.loads(payload)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    try:
        height = int(data.get("height", 0) or 0)
    except (TypeError, ValueError):
        return None
    if height < 0 or height > 1_000_000_000_000:
        return None
    state_root = str(data.get("state_root") or "").strip()
    head_hash = str(data.get("head_hash") or "").strip()
    if len(state_root) > 128 or len(head_hash) > 128:
        return None
    return {"height": height, "state_root": state_root, "head_hash": head_hash}


def validate_p2p_handshake_payload(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_handshake_payload"):
        result = _native.validate_p2p_handshake_payload(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    if data.get("accepted") is False:
        return {
            "chain_id": -1,
            "height": 0,
            "head_hash": "",
            "node_id": "",
            "p2p_port": 0,
            "accepted": False,
        }
    try:
        chain_id = int(data.get("chain_id"))
        height = int(data.get("height", 0) or 0)
        p2p_port = int(data.get("p2p_port", 0) or 0)
    except (TypeError, ValueError):
        return None
    if chain_id < 0 or height < 0 or p2p_port < 0 or p2p_port > 65535:
        return None
    head_hash = str(data.get("head_hash") or "").strip()
    node_id = str(data.get("node_id") or "").strip()
    if len(head_hash) > 128 or len(node_id) > 128:
        return None
    return {
        "chain_id": chain_id,
        "height": height,
        "head_hash": head_hash,
        "node_id": node_id,
        "p2p_port": p2p_port,
        "accepted": True,
    }


def validate_p2p_get_blocks_payload(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_get_blocks_payload"):
        result = _native.validate_p2p_get_blocks_payload(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    try:
        from_height = int(data.get("from_height", 0) or 0)
        to_height = int(data.get("to_height", from_height) or from_height)
    except (TypeError, ValueError):
        return None
    if from_height < 0 or to_height < from_height or (to_height - from_height) > 10_000:
        return None
    return {"from_height": from_height, "to_height": to_height}


def validate_p2p_wire_tx(data: Any) -> bool:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_wire_tx"):
        return bool(_native.validate_p2p_wire_tx(payload))
    if not isinstance(data, dict):
        return False
    from_addr = data.get("from_addr", data.get("from", ""))
    to_addr = data.get("to_addr", data.get("to", ""))
    return bool(isinstance(from_addr, str) and isinstance(to_addr, str) and from_addr and to_addr)


def validate_p2p_mempool_batch(data: Any) -> Optional[int]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_mempool_batch"):
        result = _native.validate_p2p_mempool_batch(payload)
        return int(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    txs = data.get("transactions")
    if not isinstance(txs, list) or len(txs) > 500:
        return None
    for tx in txs:
        if not validate_p2p_wire_tx(tx):
            return None
    return len(txs)


def validate_p2p_validator_register(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_validator_register"):
        result = _native.validate_p2p_validator_register(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    address = str(data.get("address") or "").strip()
    if not address or len(address) > 128:
        return None
    try:
        stake = float(data.get("stake", 0) or 0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(stake) or stake < 0.0 or stake > 1e18:
        return None
    node_id = str(data.get("node_id") or "").strip()
    if len(node_id) > 128:
        return None
    return {"address": address, "stake": stake, "node_id": node_id}


def validate_p2p_peers_list(data: Any) -> Optional[List[str]]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_peers_list"):
        result = _native.validate_p2p_peers_list(payload)
        return [str(x) for x in result] if result is not None else None
    if not isinstance(data, list) or len(data) > 50:
        return None
    out: List[str] = []
    for item in data:
        if not isinstance(item, str):
            return None
        s = item.strip()
        if not s or len(s) > 253 or ":" not in s:
            return None
        host, port_s = s.rsplit(":", 1)
        if not host:
            return None
        try:
            port = int(port_s)
        except (TypeError, ValueError):
            return None
        if port <= 0 or port > 65_535:
            return None
        out.append(s)
    return out


def validate_p2p_get_block(data: Any) -> Optional[int]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_get_block"):
        result = _native.validate_p2p_get_block(payload)
        return int(result) if result is not None else None
    if isinstance(data, (int, float)):
        height = int(data)
    elif isinstance(data, str):
        try:
            height = int(data)
        except ValueError:
            return None
    elif isinstance(data, dict):
        raw = data.get("height", data.get("number"))
        try:
            height = int(raw)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if height < 0 or height > 1_000_000_000_000:
        return None
    return height


def validate_p2p_get_block_by_hash(data: Any) -> Optional[str]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_get_block_by_hash"):
        result = _native.validate_p2p_get_block_by_hash(payload)
        return str(result) if result is not None else None
    if isinstance(data, str):
        block_hash = data.strip()
    elif isinstance(data, dict):
        block_hash = str(data.get("hash") or "").strip()
    else:
        return None
    if not block_hash or len(block_hash) > 128:
        return None
    return block_hash


def validate_p2p_blocks_batch(data: Any) -> Optional[int]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_blocks_batch"):
        result = _native.validate_p2p_blocks_batch(payload)
        return int(result) if result is not None else None
    if not isinstance(data, list) or len(data) > 500:
        return None
    for block in data:
        if validate_p2p_block_announce(block) is None:
            return None
    return len(data)


def verify_p2p_blocks_response_semantics(
    data: Any,
    expected_from: int,
    expected_to: int,
    expected_parent_hash: str = "",
    *,
    allow_empty: bool = False,
) -> Optional[str]:
    """v1.3.125: request-bound blocks response (range/continuity/parent + hashes).

    Returns None on OK, else a strike reason string. Fail-closed without native.
    """
    payload = (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if not isinstance(data, str)
        else data
    )
    if _native is not None and hasattr(_native, "verify_p2p_blocks_response_semantics"):
        result = _native.verify_p2p_blocks_response_semantics(
            payload,
            int(expected_from),
            int(expected_to),
            str(expected_parent_hash or ""),
            bool(allow_empty),
        )
        return str(result) if result else None
    return "blocks_response_native_required"


def verify_p2p_block_response_semantics(
    data: Any,
    expected_hash: str,
    *,
    allow_null: bool = True,
) -> Optional[str]:
    """v1.3.126: request-bound singular block response (hash must match request).

    Null/None = not-found OK when allow_null. Fail-closed without native.
    """
    if data is None:
        payload = "null"
    elif isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if _native is not None and hasattr(_native, "verify_p2p_block_response_semantics"):
        result = _native.verify_p2p_block_response_semantics(
            payload,
            str(expected_hash or ""),
            bool(allow_null),
        )
        return str(result) if result else None
    return "block_response_native_required"


def verify_p2p_state_root_response_request_semantics(
    data: Any,
    expected_height: int,
    expected_head: str = "",
) -> Optional[str]:
    """v1.3.127/130: request-bound state_root_response (height + digests + soft head).

    Fail-closed without native. Empty expected_head skips head match.
    Does not prove root belongs to head cryptographically.
    """
    payload = (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if not isinstance(data, str)
        else data
    )
    if _native is not None and hasattr(
        _native, "verify_p2p_state_root_response_request_semantics"
    ):
        result = _native.verify_p2p_state_root_response_request_semantics(
            payload,
            int(expected_height),
            str(expected_head or ""),
        )
        return str(result) if result else None
    return "state_root_response_request_native_required"


def verify_p2p_status_height_head_binding(data: Any) -> Optional[str]:
    """v1.3.128: soft status height↔head binding (height>0 requires digest head)."""
    payload = (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if not isinstance(data, str)
        else data
    )
    if _native is not None and hasattr(_native, "verify_p2p_status_height_head_binding"):
        result = _native.verify_p2p_status_height_head_binding(payload)
        return str(result) if result else None
    return "status_height_head_native_required"


def verify_p2p_handshake_head_semantics(data: Any) -> Optional[str]:
    """v1.3.128: handshake head digest + soft height binding."""
    payload = (
        json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if not isinstance(data, str)
        else data
    )
    if _native is not None and hasattr(_native, "verify_p2p_handshake_head_semantics"):
        result = _native.verify_p2p_handshake_head_semantics(payload)
        return str(result) if result else None
    return "handshake_head_native_required"


def validate_p2p_cross_shard_tx(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_cross_shard_tx"):
        result = _native.validate_p2p_cross_shard_tx(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    tx_id = str(data.get("tx_id") or "").strip()
    if not tx_id or len(tx_id) > 128:
        return None
    try:
        from_shard = int(data.get("from_shard"))
        to_shard = int(data.get("to_shard"))
    except (TypeError, ValueError):
        return None
    if from_shard < 0 or to_shard < 0 or from_shard > 1_000_000 or to_shard > 1_000_000:
        return None
    if from_shard == to_shard:
        return None
    from_addr = str(data.get("from_addr") or "").strip()
    to_addr = str(data.get("to_addr") or "").strip()
    if not from_addr or not to_addr or len(from_addr) > 128 or len(to_addr) > 128:
        return None
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount <= 0.0 or amount > 1e18:
        return None
    status = str(data.get("status") or "").strip()
    if len(status) > 64:
        return None
    source_node = str(data.get("source_node") or "").strip()
    if len(source_node) > 128:
        return None
    return {
        "tx_id": tx_id,
        "from_shard": from_shard,
        "to_shard": to_shard,
        "from_addr": from_addr,
        "to_addr": to_addr,
        "amount": amount,
        "status": status,
        "source_node": source_node,
    }


def validate_p2p_cross_shard_ack(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_cross_shard_ack"):
        result = _native.validate_p2p_cross_shard_ack(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    tx_id = str(data.get("tx_id") or "").strip()
    if not tx_id or len(tx_id) > 128:
        return None
    out: dict = {"tx_id": tx_id, "status": "", "validator_id": ""}
    if "shard_id" in data and data.get("shard_id") is not None:
        try:
            shard_id = int(data.get("shard_id"))
        except (TypeError, ValueError):
            return None
        if shard_id < 0 or shard_id > 1_000_000:
            return None
        out["shard_id"] = shard_id
    if "to_shard" in data and data.get("to_shard") is not None:
        try:
            to_shard = int(data.get("to_shard"))
        except (TypeError, ValueError):
            return None
        if to_shard < 0 or to_shard > 1_000_000:
            return None
        out["to_shard"] = to_shard
    status = str(data.get("status") or "").strip()
    if len(status) > 64:
        return None
    validator_id = str(data.get("validator_id") or "").strip()
    if len(validator_id) > 128:
        return None
    out["status"] = status
    out["validator_id"] = validator_id
    return out


def validate_p2p_shard_migration(data: Any) -> Optional[dict]:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False) if not isinstance(data, str) else data
    if _native is not None and hasattr(_native, "validate_p2p_shard_migration"):
        result = _native.validate_p2p_shard_migration(payload)
        return dict(result) if result is not None else None
    if not isinstance(data, dict):
        return None
    if str(data.get("type") or "").strip() != "shard_migration":
        return None
    address = str(data.get("address") or "").strip()
    if not address or len(address) > 128:
        return None
    try:
        from_shard = int(data.get("from_shard"))
        to_shard = int(data.get("to_shard"))
    except (TypeError, ValueError):
        return None
    if from_shard < 0 or to_shard < 0 or from_shard > 1_000_000 or to_shard > 1_000_000:
        return None
    if from_shard == to_shard:
        return None
    try:
        balance = float(data.get("balance"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(balance) or balance <= 0.0 or balance > 1e18:
        return None
    return {
        "type": "shard_migration",
        "address": address,
        "from_shard": from_shard,
        "to_shard": to_shard,
        "balance": balance,
    }


def parse_p2p_wire_line(
    line: bytes,
    max_bytes: int = 2 * 1024 * 1024,
    allowed_types: Optional[List[str]] = None,
) -> Optional[dict]:
    """Fail-closed P2P envelope parse: size + UTF-8 + JSON object with type."""
    from crypto.kernels.python.wire_borsh import python_wire_parse

    if _use_rust(NativeFamily.WIRE_CODEC) and hasattr(_native, "parse_p2p_wire_line"):
        try:
            result = _native.parse_p2p_wire_line(
                bytes(line),
                int(max_bytes),
                list(allowed_types) if allowed_types is not None else None,
            )
            return dict(result) if result is not None else None
        except ValueError:
            raise
        except Exception as exc:
            _demote(NativeFamily.WIRE_CODEC, f"parse_p2p_wire_line:{exc}")
    return python_wire_parse(
        bytes(line),
        max_bytes=int(max_bytes),
        allowed_types=list(allowed_types) if allowed_types is not None else None,
    )


def encode_p2p_wire_message(msg_type: str, data: Any = None) -> bytes:
    """Encode a newline-terminated P2P envelope (v1 NDJSON by default)."""
    from crypto.kernels.python.wire_borsh import python_wire_encode

    data_json = "null" if data is None else json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if _use_rust(NativeFamily.WIRE_CODEC) and hasattr(_native, "encode_p2p_wire_message"):
        try:
            return bytes(_native.encode_p2p_wire_message(str(msg_type), data_json))
        except Exception as exc:
            _demote(NativeFamily.WIRE_CODEC, f"encode_p2p_wire_message:{exc}")
    return python_wire_encode(str(msg_type), data, codec="v1")


def p2p_wire_codec_mode(default: str = "auto") -> str:
    """Outbound codec policy: ``ABS_P2P_WIRE_CODEC`` = ``auto`` | ``v1`` | ``v2``.

    ``auto`` (default): reply in the peer's last inbound codec; bootstrap with v1.
    """
    raw = os.getenv("ABS_P2P_WIRE_CODEC", default or "auto").strip().lower()
    if raw in {"v2", "borsh", "wire_v2"}:
        return "v2"
    if raw in {"v1", "json", "ndjson"}:
        return "v1"
    return "auto"


def encode_p2p_wire_message_v2(msg_type: str, data: Any = None) -> bytes:
    """Encode Borsh dual-stack line: ``AB2:`` + hex(envelope) + ``\\n``."""
    from crypto.kernels.python.wire_borsh import python_wire_encode

    data_json = "null" if data is None else json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if _use_rust(NativeFamily.WIRE_CODEC) and hasattr(_native, "encode_p2p_wire_message_v2"):
        try:
            return bytes(_native.encode_p2p_wire_message_v2(str(msg_type), data_json))
        except Exception as exc:
            _demote(NativeFamily.WIRE_CODEC, f"encode_p2p_wire_message_v2:{exc}")
    return python_wire_encode(str(msg_type), data, codec="v2")


def encode_p2p_wire_message_codec(
    msg_type: str, data: Any = None, *, codec: Optional[str] = None
) -> bytes:
    """Encode with explicit or env-selected codec (``v1`` / ``v2``)."""
    mode = (codec or p2p_wire_codec_mode()).strip().lower()
    if mode in {"v2", "borsh", "wire_v2"}:
        return encode_p2p_wire_message_v2(msg_type, data)
    return encode_p2p_wire_message(msg_type, data)


def p2p_wire_detect_codec(line: bytes) -> str:
    from crypto.kernels.python.wire_borsh import python_wire_detect

    if _use_rust(NativeFamily.WIRE_CODEC) and hasattr(_native, "p2p_wire_detect_codec"):
        try:
            return str(_native.p2p_wire_detect_codec(bytes(line)))
        except Exception as exc:
            _demote(NativeFamily.WIRE_CODEC, f"p2p_wire_detect_codec:{exc}")
    return python_wire_detect(bytes(line))


def hash_sorted_json(obj_json: str) -> str:
    """SHA-256 of compact sorted-key JSON (Hasher.hash_object contract)."""
    if _native is not None and hasattr(_native, "hash_sorted_json"):
        return str(_native.hash_sorted_json(obj_json))
    value = json.loads(obj_json)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(encoded.encode())


def verify_attestation_secp256k1(
    attestation: dict,
    signature_der: bytes,
    public_key_xy: bytes,
) -> bool:
    """Verify attestation signature over canonical {validator,target_hash,target_height,slot}."""
    payload = {
        "validator": attestation.get("validator"),
        "target_hash": attestation.get("target_hash"),
        "target_height": attestation.get("target_height"),
        "slot": attestation.get("slot"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if _native is not None and hasattr(_native, "verify_attestation_secp256k1"):
        return bool(
            _native.verify_attestation_secp256k1(
                encoded,
                bytes(signature_der),
                bytes(public_key_xy),
            )
        )
    digest = sha256_hex(encoded.encode())
    result = verify_secp256k1_sha256(digest.encode(), signature_der, public_key_xy)
    return bool(result)


def validate_hash_chain(
    headers: List[tuple[int, str, str]],
    expected_parent_hash: str = "",
    start_height: int = 0,
) -> bool:
    """Validate contiguous (height, hash, parent_hash) links."""
    normalized = [
        (int(height), str(block_hash), str(parent_hash))
        for height, block_hash, parent_hash in headers
    ]
    if _native is not None and hasattr(_native, "validate_hash_chain"):
        return bool(_native.validate_hash_chain(
            normalized,
            str(expected_parent_hash or ""),
            int(start_height),
        ))
    previous_hash = str(expected_parent_hash or "")
    previous_height = int(start_height)
    for height, block_hash, parent_hash in normalized:
        if not block_hash or height != previous_height + 1:
            return False
        if previous_hash and parent_hash != previous_hash:
            return False
        previous_hash = block_hash
        previous_height = height
    return True


def _python_merkle_root_strings(items: List[str]) -> str:
    if not items:
        return hash_data("empty")

    layer = [hash_data(item) for item in items]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])

        new_layer = []
        for i in range(0, len(layer), 2):
            new_layer.append(hash_data(layer[i] + layer[i + 1]))
        layer = new_layer

    return layer[0]


def _python_generate_proof_strings(items: List[str], target_index: int) -> List[str]:
    if not items or target_index >= len(items):
        return []

    layer = [hash_data(item) for item in items]
    proof = []
    index = target_index

    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])

        sibling_index = index + 1 if index % 2 == 0 else index - 1
        if sibling_index < len(layer):
            proof.append(layer[sibling_index])

        new_layer = []
        for i in range(0, len(layer), 2):
            new_layer.append(hash_data(layer[i] + layer[i + 1]))
        layer = new_layer
        index //= 2

    return proof


def _python_merkle_root_from_proof_string(
    item: str, proof: List[str], target_index: int
) -> str:
    current_hash = hash_data(item)
    index = target_index

    for sibling_hash in proof:
        if index % 2 == 0:
            combined = current_hash + sibling_hash
        else:
            combined = sibling_hash + current_hash
        current_hash = hash_data(combined)
        index //= 2

    return current_hash


def _python_state_root_from_accounts(accounts: List[dict], *, encoding_version: int = 1) -> str:
    """Tip state_root from account rows via versioned ``build_tip_payload``.

    v1: legacy float ``\"b\"``. v2 (ceremony-armed): integer ``b_satoshi``.
    """
    from runtime.state_root_encoding import build_tip_payload

    version = int(encoding_version or 1)
    payload = build_tip_payload(accounts, version=version)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256_hex(encoded.encode())
