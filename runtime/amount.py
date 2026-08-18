#!/usr/bin/env python3
"""Canonical ABS amount helpers (satoshi / micro-ABS).

Canonical money unit for new storage writes is integer satoshi
(1 ABS = 1_000_000). Float ABS remains on the wire / legacy columns for
compatibility; dual-write keeps ``balance`` (float) derived from satoshi.
"""
from __future__ import annotations

import logging
import math
import os
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from typing import Any, Dict, Mapping, MutableMapping, Optional, Union

# 1 ABS = 1_000_000 satoshi (same as USDC-style micro units)
ABS_DECIMALS = 6
SATOSHI_MULTIPLIER = 10 ** ABS_DECIMALS

NumberLike = Union[int, float, str, Decimal]
logger = logging.getLogger("amount")
_native_fallback_warned = False


def _native_required() -> bool:
    """Fail-closed when prod-canonical ABS_REQUIRE_NATIVE_CRYPTO is set (v1.3.65)."""
    for key in ("ABS_REQUIRE_NATIVE_CRYPTO", "REQUIRE_NATIVE_CRYPTO"):
        if os.environ.get(key, "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    return False


def _native_fallback(op: str, exc: BaseException) -> None:
    global _native_fallback_warned
    if _native_required():
        raise RuntimeError(f"native amount op {op} required but failed: {exc}") from exc
    if not _native_fallback_warned:
        _native_fallback_warned = True
        logger.warning(
            "[amount] native %s failed; using Python fallback (further falls suppressed): %s",
            op,
            exc,
        )


def to_satoshi(amount_abs: NumberLike) -> int:
    """Convert ABS amount to integer satoshi (floor toward zero)."""
    if isinstance(amount_abs, bool):
        raise TypeError("bool is not a valid amount")
    try:
        from crypto import native

        if native.native_available() and hasattr(native, "amount_to_satoshi"):
            if isinstance(amount_abs, int):
                return int(native.amount_to_satoshi(str(amount_abs)))
            if isinstance(amount_abs, Decimal):
                return int(native.amount_to_satoshi(format(amount_abs, "f")))
            return int(native.amount_to_satoshi(str(amount_abs)))
    except (ValueError, TypeError, InvalidOperation):
        # Invalid input is not a native-missing fallback — caller must refuse.
        raise
    except Exception as exc:
        _native_fallback("amount_to_satoshi", exc)
    try:
        d = Decimal(str(amount_abs))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid amount: {amount_abs!r}") from exc
    scaled = (d * Decimal(SATOSHI_MULTIPLIER)).quantize(
        Decimal("1"), rounding=ROUND_DOWN
    )
    return int(scaled)


def parse_abs_int(raw: Any, *, field: str = "amount", allow_negative: bool = False) -> int:
    """Parse a whole ABS amount at an input boundary (HTTP / StoragePort).

    JSON ``1`` is int; ``1.0`` is a whole float (accepted); ``1.5`` is refused.
    Hex wei is not ABS — callers that need wei must convert before this helper.
    """
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be an integer ABS amount")
    if raw is None or raw == "":
        n = 0
    elif isinstance(raw, int):
        n = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError(f"{field} must be a whole ABS amount, got {raw!r}")
        n = int(raw)
    elif isinstance(raw, str):
        s = raw.strip()
        if not s:
            n = 0
        elif s.lower().startswith("0x"):
            raise ValueError(f"{field} must be integer ABS, not hex wei")
        else:
            try:
                d = Decimal(s)
            except (InvalidOperation, ValueError, TypeError) as exc:
                raise ValueError(f"invalid {field}: {raw!r}") from exc
            if d != d.to_integral_value():
                raise ValueError(f"{field} must be a whole ABS amount, got {raw!r}")
            n = int(d)
    elif isinstance(raw, Decimal):
        if raw != raw.to_integral_value():
            raise ValueError(f"{field} must be a whole ABS amount, got {raw!r}")
        n = int(raw)
    else:
        raise ValueError(f"{field} must be an integer ABS amount")
    if n < 0 and not allow_negative:
        raise ValueError(f"{field} must be >= 0")
    return n


# ETH-style RPC: 1 ABS = 10**18 wei = 10**6 satoshi → 10**12 wei per satoshi.
WEI_PER_ABS = 10**18
WEI_PER_SATOSHI = WEI_PER_ABS // SATOSHI_MULTIPLIER
# Preserve historical JSON-RPC heuristic: hex >= 1e15 is wei, smaller hex is integer ABS.
WEI_STYLE_THRESHOLD = 10**15


def abs_to_wei(amount_abs: NumberLike) -> int:
    """ABS → ETH-style wei via Decimal (1 ABS = 10**18 wei).

    Gas price defaults are sub-satoshi (``1e-7`` ABS = ``1e11`` wei). Do not
    route that field through ``to_satoshi`` — it floors to 0.
    """
    if isinstance(amount_abs, bool):
        raise TypeError("bool is not an amount")
    try:
        d = Decimal(str(amount_abs))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid amount: {amount_abs!r}") from exc
    if not d.is_finite():
        raise ValueError("amount must be finite")
    if d < 0:
        raise ValueError("amount must be >= 0")
    return int((d * Decimal(WEI_PER_ABS)).to_integral_value(rounding=ROUND_DOWN))


def parse_rpc_value_abs(raw: Any, *, field: str = "value") -> float:
    """Parse JSON-RPC / REST money to a satoshi-quantized ABS float.

    Hex ``>= 10**15`` is ETH-style wei (``1e18`` wei = 1 ABS). Smaller hex and
    decimal values are ABS. Return type stays float so ``Transaction.value``
    hash encoding is unchanged; IEEE dust is floored via satoshi.
    """
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be an amount, not bool")
    if raw is None or raw == "":
        return 0.0
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return 0.0
        if s.lower().startswith("0x"):
            try:
                wei = int(s, 16)
            except ValueError as exc:
                raise ValueError(f"invalid {field} hex: {raw!r}") from exc
            if wei < 0:
                raise ValueError(f"{field} must be >= 0")
            if wei >= WEI_STYLE_THRESHOLD:
                return from_satoshi_float(wei // WEI_PER_SATOSHI)
            return from_satoshi_float(to_satoshi(wei))
        return from_satoshi_float(to_satoshi(s))
    return from_satoshi_float(to_satoshi(raw))


def parse_p2p_wire_abs(raw: Any, *, field: str = "value") -> float:
    """P2P mempool amount: satoshi-quantized ABS float.

    Hex wei is REST/JSON-RPC only — ``float("0x…")`` historically refused
    the wire as unparseable. Keep that refuse so hex cannot smuggle ABS.
    ``bool`` is not an amount (``float(True) == 1.0`` would mint 1 ABS).
    """
    if isinstance(raw, str) and raw.strip().lower().startswith("0x"):
        raise ValueError(f"{field} must not be hex wei on P2P wire")
    return parse_rpc_value_abs(raw, field=field)


def parse_finite_number(raw: Any, *, field: str = "value") -> float:
    """Non-money numeric (oracle prices). Refuses bool and non-finite."""
    if isinstance(raw, bool):
        raise ValueError(f"{field} must be a number, not bool")
    try:
        v = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {raw!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"{field} must be finite")
    return v


def money_abs(raw: Any, *, field: str = "amount") -> float:
    """Storage / bridge / stake amount: satoshi-quantized ABS float.

    ``bool`` is TypeError (same contract as StoragePort.set_balance).
    """
    if isinstance(raw, bool):
        raise TypeError("bool is not an amount")
    return parse_rpc_value_abs(raw, field=field)


def tx_money_abs(row: Optional[Mapping[str, Any]]) -> Dict[str, float]:
    """Satoshi-quantize tx ``value`` / ``fee`` / ``burned`` for persist and display."""
    src = dict(row) if row else {}
    raw_value = src.get("value", src.get("amount", 0.0))
    return {
        "value": money_abs(raw_value, field="value"),
        "fee": money_abs(src.get("fee", 0.0), field="fee"),
        "burned": money_abs(src.get("burned", 0.0), field="burned"),
    }


def writeback_balance_abs(row: Optional[Mapping[str, Any]]) -> float:
    """EVM writeback balance: satoshi wins, else ``money_abs(balance)``.

    ``bool`` is TypeError (``float(True) == 1.0`` must not mint 1 ABS).
    """
    src = dict(row) if row else {}
    if src.get("balance_satoshi") is not None:
        return from_satoshi_float(max(0, int(src["balance_satoshi"])))
    return money_abs(src.get("balance"), field="balance")


def from_satoshi(satoshi: int) -> Decimal:
    """Convert satoshi int to Decimal ABS (exact)."""
    return Decimal(int(satoshi)) / Decimal(SATOSHI_MULTIPLIER)


def from_satoshi_float(satoshi: int) -> float:
    """Display / legacy float ABS — prefer from_satoshi for money math."""
    try:
        from crypto import native

        if native.native_available() and hasattr(native, "amount_from_satoshi_float"):
            return float(native.amount_from_satoshi_float(int(satoshi)))
    except Exception as exc:
        _native_fallback("amount_from_satoshi_float", exc)
    return float(from_satoshi(satoshi))


def account_satoshi(row: Optional[Mapping[str, Any]]) -> int:
    """Read satoshi from account row; backfill from float balance if needed."""
    if not row:
        return 0
    if row.get("balance_satoshi") is not None:
        try:
            return max(0, int(row["balance_satoshi"]))
        except (TypeError, ValueError):
            pass
    return max(0, to_satoshi(row.get("balance", 0) or 0))


def account_balance_abs(row: Optional[Mapping[str, Any]]) -> float:
    """ABS float derived from satoshi when present."""
    return from_satoshi_float(account_satoshi(row))


def dual_write_balance(row: MutableMapping[str, Any], balance_abs: NumberLike) -> Dict[str, Any]:
    """Set balance_satoshi + derived float balance on an account dict."""
    sat = max(0, to_satoshi(balance_abs))
    row["balance_satoshi"] = sat
    row["balance"] = from_satoshi_float(sat)
    return dict(row)


def apply_delta_satoshi(current_sat: int, delta_abs: NumberLike) -> int:
    """Apply ABS delta to satoshi balance (never negative — clamps)."""
    try:
        from crypto import native

        if native.native_available() and hasattr(native, "amount_apply_delta_satoshi"):
            if isinstance(delta_abs, bool):
                raise TypeError("bool is not a valid amount")
            if isinstance(delta_abs, Decimal):
                delta_s = format(delta_abs, "f")
            else:
                delta_s = str(delta_abs)
            return int(native.amount_apply_delta_satoshi(int(current_sat), delta_s))
    except TypeError:
        raise
    except Exception as exc:
        _native_fallback("amount_apply_delta_satoshi", exc)
    return max(0, int(current_sat) + to_satoshi(delta_abs))


def try_debit_satoshi(current_sat: int, debit_abs: NumberLike) -> int:
    """Debit ABS amount from satoshi; raise on underflow (v1.3.68 — no silent clamp)."""
    if isinstance(debit_abs, bool):
        raise TypeError("bool is not a valid amount")
    debit = to_satoshi(debit_abs)
    if debit < 0:
        raise ValueError("debit must be non-negative")
    cur = int(current_sat)
    if cur < debit:
        raise ValueError(f"insufficient_balance: have={cur} need={debit}")
    return cur - debit


def plan_transfer_fees_sat(
    gas: int,
    gas_price_wei: NumberLike,
    burn_rate: NumberLike,
    value: NumberLike = 0,
    gas_used: Optional[int] = None,
) -> Dict[str, int]:
    """Split L1 transfer fee into satoshi ints (Wave C tip+apply hot path)."""
    try:
        from crypto import native

        if native.native_available() and hasattr(native, "plan_transfer_fees_satoshi"):
            fee_s, burned_s, miner_s, total_s = native.plan_transfer_fees_satoshi(
                int(gas),
                str(gas_price_wei),
                str(burn_rate),
                str(value),
                int(gas_used) if gas_used is not None else None,
            )
            value_s = to_satoshi(value)
            return {
                "fee_sat": int(fee_s),
                "burned_sat": int(burned_s),
                "miner_fee_sat": int(miner_s),
                "value_sat": value_s,
                "total_cost_sat": int(total_s),
            }
    except Exception as exc:
        _native_fallback("plan_transfer_fees_satoshi", exc)
    gp = Decimal(str(gas_price_wei))
    if gp < 0:
        raise ValueError("negative gas_price_wei")
    fee_abs = Decimal(int(gas)) * gp
    if gas_used is not None:
        fee_abs = max(fee_abs, Decimal(int(gas_used)) * gp)
    fee_sat = to_satoshi(fee_abs)
    rate = Decimal(str(burn_rate))
    if rate < 0:
        rate = Decimal("0")
    if rate > 1:
        rate = Decimal("1")
    burned_sat = int((Decimal(fee_sat) * rate).to_integral_value(rounding=ROUND_DOWN))
    miner_fee_sat = fee_sat - burned_sat
    value_sat = to_satoshi(value)
    return {
        "fee_sat": fee_sat,
        "burned_sat": burned_sat,
        "miner_fee_sat": miner_fee_sat,
        "value_sat": value_sat,
        "total_cost_sat": value_sat + fee_sat,
    }


def plan_transfer_fees(
    gas: int,
    gas_price_wei: float,
    burn_rate: float,
    value: float = 0.0,
    gas_used: Optional[int] = None,
) -> Dict[str, float]:
    """Display/legacy ABS floats — prefer plan_transfer_fees_sat for apply math."""
    sat = plan_transfer_fees_sat(gas, gas_price_wei, burn_rate, value, gas_used=gas_used)
    return {
        "fee": from_satoshi_float(sat["fee_sat"]),
        "burned": from_satoshi_float(sat["burned_sat"]),
        "miner_fee": from_satoshi_float(sat["miner_fee_sat"]),
        "total_cost": from_satoshi_float(sat["total_cost_sat"]),
    }


def can_afford_transfer_sat(sender_sat: int, total_cost_sat: int) -> bool:
    """True if sender satoshi covers integer total cost."""
    return int(sender_sat) >= max(0, int(total_cost_sat))


def can_afford_transfer(sender_sat: int, total_cost_abs: NumberLike) -> bool:
    """True if sender satoshi balance covers ABS total cost (edge helper)."""
    try:
        from crypto import native

        if native.native_available() and hasattr(native, "can_afford_transfer"):
            return bool(native.can_afford_transfer(int(sender_sat), float(total_cost_abs)))
    except Exception as exc:
        _native_fallback("can_afford_transfer", exc)
    return can_afford_transfer_sat(int(sender_sat), to_satoshi(total_cost_abs))


def apply_satoshi_delta(current_sat: int, delta_sat: int) -> int:
    """Apply integer satoshi delta; never negative."""
    return max(0, int(current_sat) + int(delta_sat))
