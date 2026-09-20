"""Wire-format helpers for P2P mempool gossip (full signed tx payloads).

ADR 0021 money cutover: ``fee_satoshi`` / ``amount_satoshi`` are canonical on
wire. ABS ``fee`` / ``amount`` / ``value`` are display dual-write derived from
satoshi integers — never the authority for sort / min-fee / mismatch checks.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from blockchain.mempool import MempoolTransaction


class WireMoneyMismatch(ValueError):
    """Float ABS and explicit satoshi disagree on the same wire payload."""


def _sat_from_keys(data: Dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in data and data.get(key) is not None:
            return int(data[key])
    return None


def resolve_wire_amount_sat(data: Dict[str, Any]) -> Tuple[int, float]:
    """Prefer ``amount_satoshi`` / ``value_satoshi``; else ABS → satoshi.

    When both satoshi and ABS float are present, refuse on mismatch.
    Returns ``(amount_satoshi, amount_abs_display)``.
    """
    from runtime.amount import from_satoshi_float, parse_p2p_wire_abs, to_satoshi

    sat = _sat_from_keys(data, "amount_satoshi", "value_satoshi")
    raw_abs = None
    if "value" in data and data.get("value") is not None:
        raw_abs = data.get("value")
    elif "amount" in data and data.get("amount") is not None:
        raw_abs = data.get("amount")

    if sat is not None:
        # Negative satoshi is refused later (value_negative); keep reason codes.
        if raw_abs is not None:
            abs_sat = int(to_satoshi(parse_p2p_wire_abs(raw_abs, field="value")))
            if abs_sat != int(sat):
                raise WireMoneyMismatch(
                    f"value_satoshi_mismatch sat={sat} abs_sat={abs_sat}"
                )
        return int(sat), from_satoshi_float(int(sat))

    if raw_abs is None:
        raw_abs = 0
    value = parse_p2p_wire_abs(raw_abs, field="value")
    amount_sat = int(to_satoshi(value))
    return amount_sat, from_satoshi_float(amount_sat)


def resolve_wire_fee_sat(
    data: Dict[str, Any],
    *,
    planned_fee_sat: int | None = None,
) -> Tuple[int, float]:
    """Prefer ``fee_satoshi``; else ABS ``fee``; else optional planned satoshi.

    When both ``fee_satoshi`` and ``fee`` are present, refuse on mismatch.
    Returns ``(fee_satoshi, fee_abs_display)``.
    """
    from runtime.amount import from_satoshi_float, parse_p2p_wire_abs, to_satoshi

    sat = _sat_from_keys(data, "fee_satoshi")
    raw_fee = data.get("fee", None) if "fee" in data else None

    if sat is not None:
        # Negative satoshi is refused later (fee_negative); keep reason codes.
        if raw_fee is not None:
            abs_sat = int(to_satoshi(parse_p2p_wire_abs(raw_fee, field="fee")))
            if abs_sat != int(sat):
                raise WireMoneyMismatch(
                    f"fee_satoshi_mismatch sat={sat} abs_sat={abs_sat}"
                )
        return int(sat), from_satoshi_float(int(sat))

    if raw_fee is not None:
        fee = parse_p2p_wire_abs(raw_fee, field="fee")
        fee_sat = int(to_satoshi(fee))
        return fee_sat, from_satoshi_float(fee_sat)

    if planned_fee_sat is not None:
        fee_sat = int(planned_fee_sat)
        return fee_sat, from_satoshi_float(fee_sat)

    raise ValueError("fee or fee_satoshi required")


def mempool_tx_to_wire(tx: "MempoolTransaction") -> Dict:
    """Serialize mempool tx for P2P — must round-trip through _ingest_peer_tx.

    Canonical money: ``fee_satoshi`` / ``amount_satoshi``. ABS floats are
    derived from those integers (display dual-write only).
    """
    from runtime.amount import from_satoshi_float, to_satoshi

    fee_sat = int(getattr(tx, "fee_satoshi", -1))
    if fee_sat < 0:
        fee_sat = int(to_satoshi(tx.fee))
    amount_sat = int(getattr(tx, "amount_satoshi", -1))
    if amount_sat < 0:
        amount_sat = int(to_satoshi(tx.amount))
    amount_abs = from_satoshi_float(amount_sat)
    fee_abs = from_satoshi_float(fee_sat)
    return {
        "hash": tx.tx_hash,
        "tx_hash": tx.tx_hash,
        "from_addr": tx.from_addr,
        "from": tx.from_addr,
        "to_addr": tx.to_addr,
        "to": tx.to_addr,
        "value": amount_abs,
        "amount": amount_abs,
        "amount_satoshi": amount_sat,
        "fee": fee_abs,
        "fee_satoshi": fee_sat,
        "nonce": int(tx.nonce),
        "signature": tx.signature or "",
        "public_key": tx.public_key or "",
        "data": tx.data or "",
        "gas": int(getattr(tx, "gas", 0) or 21_000),
        "timestamp": float(tx.timestamp),
    }
