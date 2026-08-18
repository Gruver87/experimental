#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Валидация входных данных"""

import re
from typing import Any, Dict, List, Optional, Tuple

def validate_address(address: str) -> Tuple[bool, str]:
    """
    Проверка корректности адреса кошелька
    Формат: 0x + 40 hex символов
    """
    if not address or not isinstance(address, str):
        return False, "Address must be a non-empty string"
    
    if not address.startswith('0x'):
        return False, "Address must start with 0x"
    
    hex_part = address[2:]
    if len(hex_part) != 40:
        return False, "Address must be 40 hex characters after 0x"
    
    if not re.match(r'^[0-9a-fA-F]{40}$', hex_part):
        return False, "Address contains invalid hex characters"
    
    return True, ""

def validate_amount(amount: Any, min_amount: float = 0.0001, max_amount: float = 1_000_000_000) -> Tuple[bool, str]:
    """Проверка суммы"""
    if isinstance(amount, bool):
        return False, "Amount must be a number, not bool"
    try:
        from runtime.amount import parse_rpc_value_abs

        amount_float = parse_rpc_value_abs(amount, field="amount")
    except (TypeError, ValueError):
        return False, "Amount must be a number"
    
    if amount_float <= 0:
        return False, "Amount must be positive"
    
    if amount_float < min_amount:
        return False, f"Amount too small (minimum: {min_amount})"
    
    if amount_float > max_amount:
        return False, f"Amount too large (maximum: {max_amount})"
    
    # Проверка на слишком много знаков после запятой
    if len(str(amount_float).split('.')[-1]) > 8:
        return False, "Amount cannot have more than 8 decimal places"
    
    return True, ""

def validate_signature(signature: str) -> Tuple[bool, str]:
    """Проверка формата подписи"""
    if not signature or not isinstance(signature, str):
        return False, "Signature must be a non-empty string"
    
    if len(signature) < 64:
        return False, "Signature too short"
    
    # Проверка hex формата
    if not re.match(r'^[0-9a-fA-F]+$', signature):
        return False, "Signature must be hex-encoded"
    
    return True, ""

def validate_tx_data(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Комплексная проверка данных транзакции"""
    required_fields = ['from', 'to', 'amount']
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    # Проверка адресов
    valid, err = validate_address(data['from'])
    if not valid:
        return False, f"Invalid from address: {err}"
    
    valid, err = validate_address(data['to'])
    if not valid:
        return False, f"Invalid to address: {err}"
    
    # Проверка суммы
    valid, err = validate_amount(data['amount'])
    if not valid:
        return False, f"Invalid amount: {err}"
    
    return True, ""

def sanitize_input(data: Any) -> Any:
    """Базовая санитизация входных данных"""
    if isinstance(data, str):
        # Ограничиваем длину строк
        return data[:10000]
    elif isinstance(data, dict):
        return {k: sanitize_input(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_input(item) for item in data]
    else:
        return data
