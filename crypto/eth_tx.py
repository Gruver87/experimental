#!/usr/bin/env python3
"""Decode and verify Ethereum-style signed raw transactions (RLP)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from crypto import native
from crypto.rlp import decode, decode_single, encode, item_to_int


def _addr_from_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    return "0x" + raw.hex().rjust(40, "0")[-40:]


def _scalar_bytes(item) -> bytes:
    if isinstance(item, list):
        raise ValueError("expected_scalar")
    if isinstance(item, int):
        if item == 0:
            return b""
        length = (item.bit_length() + 7) // 8
        return item.to_bytes(length, "big")
    return bytes(item or b"")


def _recovery_id_from_v(v: int, chain_id: Optional[int] = None) -> int:
    if v in (0, 1):
        return v
    if v in (27, 28):
        return v - 27
    if v >= 35:
        if chain_id is None:
            chain_id = (v - 35) // 2
        return (v - 35 - 2 * chain_id) % 2
    raise ValueError(f"unsupported_v:{v}")


def _recover_address(signing_hash: bytes, v: int, r: bytes, s: bytes, chain_id: Optional[int]) -> str:
    rec_id = _recovery_id_from_v(v, chain_id)
    return native.recover_eth_address_keccak(signing_hash, r, s, rec_id)


def _legacy_signing_payload(
    nonce: int,
    gas_price: int,
    gas_limit: int,
    to_addr: bytes,
    value: int,
    data: bytes,
    chain_id: Optional[int],
    for_signing: bool,
) -> List:
    base = [nonce, gas_price, gas_limit, to_addr, value, data]
    if for_signing and chain_id is not None:
        return base + [chain_id, b"", b""]
    return base


def _decode_access_list(raw_list) -> list:
    if not raw_list:
        return []
    out = []
    for entry in raw_list:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError("bad_access_list")
        addr = _scalar_bytes(entry[0])
        keys = entry[1] if isinstance(entry[1], list) else []
        out.append((addr, [_scalar_bytes(k) for k in keys]))
    return out


def _decode_legacy(fields: list, typed_prefix: Optional[bytes] = None) -> Dict[str, Any]:
    if len(fields) != 9:
        raise ValueError("legacy_tx_field_count")
    nonce = item_to_int(fields[0])
    gas_price = item_to_int(fields[1])
    gas_limit = item_to_int(fields[2])
    to_raw = _scalar_bytes(fields[3])
    value = item_to_int(fields[4])
    data = _scalar_bytes(fields[5])
    v = item_to_int(fields[6])
    r = _scalar_bytes(fields[7])
    s = _scalar_bytes(fields[8])
    chain_id = None
    if v >= 35:
        chain_id = (v - 35) // 2
    signing_hash = native.keccak256_digest(
        (typed_prefix or b"") + encode(_legacy_signing_payload(
            nonce, gas_price, gas_limit, to_raw, value, data, chain_id, True
        ))
    )
    from_addr = _recover_address(signing_hash, v, r, s, chain_id)
    return {
        "from": from_addr,
        "to": _addr_from_bytes(to_raw),
        "value": value,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "data": "0x" + data.hex() if data else "0x",
        "chain_id": chain_id,
        "eth_signed": True,
        "eth_tx_type": "legacy",
        "signature": r.hex() + s.hex() + format(v, "x"),
        "public_key": "",
        "eth_v": v,
        "eth_r": r.hex(),
        "eth_s": s.hex(),
    }


def _decode_eip1559(raw: bytes) -> Dict[str, Any]:
    payload, _ = decode(raw, 1)
    if not isinstance(payload, list) or len(payload) != 12:
        raise ValueError("eip1559_field_count")
    chain_id = item_to_int(payload[0])
    nonce = item_to_int(payload[1])
    max_priority = item_to_int(payload[2])
    max_fee = item_to_int(payload[3])
    gas_limit = item_to_int(payload[4])
    to_raw = _scalar_bytes(payload[5])
    value = item_to_int(payload[6])
    data = _scalar_bytes(payload[7])
    _decode_access_list(payload[8])
    y_parity = item_to_int(payload[9])
    r = _scalar_bytes(payload[10])
    s = _scalar_bytes(payload[11])
    signing_body = [
        chain_id, nonce, max_priority, max_fee, gas_limit,
        to_raw, value, data, payload[8],
    ]
    signing_hash = native.keccak256_digest(b"\x02" + encode(signing_body))
    v = y_parity + 35 + 2 * chain_id if chain_id else y_parity + 27
    from_addr = _recover_address(signing_hash, y_parity, r, s, None)
    return {
        "from": from_addr,
        "to": _addr_from_bytes(to_raw),
        "value": value,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": max_fee,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_priority,
        "data": "0x" + data.hex() if data else "0x",
        "chain_id": chain_id,
        "eth_signed": True,
        "eth_tx_type": "eip1559",
        "signature": r.hex() + s.hex() + format(y_parity, "x"),
        "public_key": "",
        "eth_v": v,
        "eth_y_parity": y_parity,
        "eth_r": r.hex(),
        "eth_s": s.hex(),
    }


def _decode_blob_hashes(raw_list) -> List[bytes]:
    if not raw_list:
        return []
    if not isinstance(raw_list, list):
        raise ValueError("blob_hashes_not_list")
    out: List[bytes] = []
    for item in raw_list:
        h = _scalar_bytes(item)
        if len(h) != 32:
            raise ValueError("blob_hash_length")
        out.append(h)
    return out


def _decode_eip4844(raw: bytes) -> Dict[str, Any]:
    """EIP-4844 blob transaction (type 0x03)."""
    payload, _ = decode(raw, 1)
    if not isinstance(payload, list) or len(payload) != 14:
        raise ValueError("eip4844_field_count")
    chain_id = item_to_int(payload[0])
    nonce = item_to_int(payload[1])
    max_priority = item_to_int(payload[2])
    max_fee = item_to_int(payload[3])
    gas_limit = item_to_int(payload[4])
    to_raw = _scalar_bytes(payload[5])
    value = item_to_int(payload[6])
    data = _scalar_bytes(payload[7])
    access_list = payload[8]
    _decode_access_list(access_list)
    max_fee_per_blob_gas = item_to_int(payload[9])
    blob_hashes_raw = _decode_blob_hashes(payload[10])
    y_parity = item_to_int(payload[11])
    r = _scalar_bytes(payload[12])
    s = _scalar_bytes(payload[13])
    signing_body = [
        chain_id, nonce, max_priority, max_fee, gas_limit,
        to_raw, value, data, access_list, max_fee_per_blob_gas, payload[10],
    ]
    signing_hash = native.keccak256_digest(b"\x03" + encode(signing_body))
    v = y_parity + 35 + 2 * chain_id if chain_id else y_parity + 27
    from_addr = _recover_address(signing_hash, y_parity, r, s, None)
    blob_hashes_hex = ["0x" + h.hex() for h in blob_hashes_raw]
    blob_hashes_int = [int.from_bytes(h, "big") for h in blob_hashes_raw]
    return {
        "from": from_addr,
        "to": _addr_from_bytes(to_raw),
        "value": value,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": max_fee,
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": max_priority,
        "maxFeePerBlobGas": max_fee_per_blob_gas,
        "blob_versioned_hashes": blob_hashes_hex,
        "blob_hashes": blob_hashes_int,
        "data": "0x" + data.hex() if data else "0x",
        "chain_id": chain_id,
        "eth_signed": True,
        "eth_tx_type": "eip4844",
        "signature": r.hex() + s.hex() + format(y_parity, "x"),
        "public_key": "",
        "eth_v": v,
        "eth_y_parity": y_parity,
        "eth_r": r.hex(),
        "eth_s": s.hex(),
    }


def decode_raw_transaction(raw: bytes | str) -> Dict[str, Any]:
    if isinstance(raw, str):
        raw_bytes = bytes.fromhex(raw.replace("0x", "").replace("0X", ""))
    else:
        raw_bytes = raw
    if not raw_bytes:
        raise ValueError("empty_raw_transaction")

    if native.native_available() and hasattr(native, "decode_eth_raw_tx"):
        try:
            import json as _json

            payload = native.decode_eth_raw_tx(raw_bytes)
            decoded = _json.loads(payload)
            # blob_hashes may be decimal strings from Rust JSON for 256-bit ints
            if isinstance(decoded.get("blob_hashes"), list):
                decoded["blob_hashes"] = [
                    int(x) if not isinstance(x, int) else x for x in decoded["blob_hashes"]
                ]
            return decoded
        except Exception:
            status = native.native_crypto_status(required=False)
            if status.get("required"):
                raise

    if raw_bytes[0] == 0x02:
        return _decode_eip1559(raw_bytes)
    if raw_bytes[0] == 0x03:
        return _decode_eip4844(raw_bytes)
    if raw_bytes[0] in (0x01, 0x04):
        raise ValueError(f"unsupported_typed_tx:{raw_bytes[0]:#x}")
    item = decode_single(raw_bytes)
    if not isinstance(item, list):
        raise ValueError("raw_tx_not_list")
    return _decode_legacy(item)


def verify_eth_transaction_dict(tx: dict) -> bool:
    if not tx.get("eth_signed"):
        return False
    try:
        r = bytes.fromhex(str(tx.get("eth_r", "")))
        s = bytes.fromhex(str(tx.get("eth_s", "")))
        chain_id = int(tx.get("chain_id") or 0)
        to_raw = bytes.fromhex(str(tx.get("to", "")).replace("0x", "")) if tx.get("to") else b""
        data = bytes.fromhex(str(tx.get("data", "0x")).replace("0x", ""))
        tx_type = tx.get("eth_tx_type", "legacy")
        if tx_type == "eip1559":
            signing_body = [
                chain_id,
                int(tx.get("nonce", 0)),
                int(tx.get("maxPriorityFeePerGas", 0)),
                int(tx.get("maxFeePerGas", tx.get("gasPrice", 0))),
                int(tx.get("gas", 0)),
                to_raw,
                int(tx.get("value", 0)),
                data,
                [],
            ]
            signing_hash = native.keccak256_digest(b"\x02" + encode(signing_body))
            y_parity = int(tx.get("eth_y_parity", 0))
            recovered = _recover_address(signing_hash, y_parity, r, s, None)
        elif tx_type == "eip4844":
            blob_raw = [
                bytes.fromhex(str(h).replace("0x", ""))
                for h in (tx.get("blob_versioned_hashes") or [])
            ]
            signing_body = [
                chain_id,
                int(tx.get("nonce", 0)),
                int(tx.get("maxPriorityFeePerGas", 0)),
                int(tx.get("maxFeePerGas", tx.get("gasPrice", 0))),
                int(tx.get("gas", 0)),
                to_raw,
                int(tx.get("value", 0)),
                data,
                [],
                int(tx.get("maxFeePerBlobGas", 0)),
                blob_raw,
            ]
            signing_hash = native.keccak256_digest(b"\x03" + encode(signing_body))
            y_parity = int(tx.get("eth_y_parity", 0))
            recovered = _recover_address(signing_hash, y_parity, r, s, None)
        else:
            v = int(tx.get("eth_v", 0))
            signing_hash = native.keccak256_digest(encode(_legacy_signing_payload(
                int(tx.get("nonce", 0)),
                int(tx.get("gasPrice", 0)),
                int(tx.get("gas", 0)),
                to_raw,
                int(tx.get("value", 0)),
                data,
                chain_id if v >= 35 else None,
                True,
            )))
            recovered = _recover_address(signing_hash, v, r, s, chain_id if v >= 35 else None)
        from_addr = tx.get("from", tx.get("from_addr", ""))
        return recovered.lower() == str(from_addr).lower()
    except (ValueError, TypeError):
        return False
    except Exception as exc:
        # Wave P: backend/probe failures must not paint as invalid signature.
        raise RuntimeError(f"eth signature verify unavailable: {exc}") from exc
