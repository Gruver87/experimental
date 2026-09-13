#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Валидация входных данных (satoshi-honest amount boundary — Wave H)."""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def validate_address(address: str) -> Tuple[bool, str]:
    """Адрес: 0x + 40 hex."""
    if not address or not isinstance(address, str):
        return False, "Address must be a non-empty string"
    if not address.startswith("0x"):
        return False, "Address must start with 0x"
    hex_part = address[2:]
    if len(hex_part) != 40:
        return False, "Address must be 40 hex characters after 0x"
    if not re.match(r"^[0-9a-fA-F]{40}$", hex_part):
        return False, "Address contains invalid hex characters"
    return True, ""


def validate_amount(
    amount: Any,
    min_amount: Any = 0,
    max_amount: Any = 1_000_000_000,
) -> Tuple[bool, str]:
    """Validate amount via integer satoshi (1 ABS = 1e6). No float money math."""
    if isinstance(amount, bool):
        return False, "Amount must be a number, not bool"
    try:
        from runtime.amount import to_satoshi

        amount_sats = int(to_satoshi(amount))
        min_sats = int(to_satoshi(min_amount)) if min_amount not in (None, "") else 0
        max_sats = (
            int(to_satoshi(max_amount))
            if max_amount not in (None, "")
            else 1_000_000_000 * 1_000_000
        )
    except (TypeError, ValueError) as exc:
        return False, f"Amount must be a number ({exc})"

    if amount_sats < 0:
        return False, "Amount must be non-negative"
    if min_sats > 0 and amount_sats < min_sats:
        return False, f"Amount too small (minimum satoshi: {min_sats})"
    if min_sats == 0 and amount_sats < 0:
        return False, "Amount must be non-negative"
    if amount_sats > max_sats:
        return False, f"Amount too large (maximum satoshi: {max_sats})"
    return True, ""


def validate_signature(signature: str) -> Tuple[bool, str]:
    if not signature or not isinstance(signature, str):
        return False, "Signature must be a non-empty string"
    if len(signature) < 64:
        return False, "Signature too short"
    if not re.match(r"^[0-9a-fA-F]+$", signature):
        return False, "Signature must be hex-encoded"
    return True, ""


def validate_tx_data(data: Dict[str, Any]) -> Tuple[bool, str]:
    required_fields = ["from", "to", "amount"]
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    valid, err = validate_address(data["from"])
    if not valid:
        return False, f"Invalid from address: {err}"
    valid, err = validate_address(data["to"])
    if not valid:
        return False, f"Invalid to address: {err}"
    valid, err = validate_amount(data["amount"], min_amount=0)
    if not valid:
        return False, f"Invalid amount: {err}"
    return True, ""


def sanitize_input(data: Any) -> Any:
    if isinstance(data, str):
        return data[:10000]
    if isinstance(data, dict):
        return {k: sanitize_input(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_input(item) for item in data]
    return data
