#!/usr/bin/env python3
"""Transaction.from_dict money boundary: bool refuse, hash preserved."""

import pytest

from core.blockchain import Transaction


def test_from_dict_refuses_bool_value():
    with pytest.raises(ValueError, match="bool"):
        Transaction.from_dict(
            {
                "from_addr": "0x" + "a" * 40,
                "to_addr": "0x" + "b" * 40,
                "value": True,
                "nonce": 0,
            }
        )


def test_from_dict_preserves_provided_hash_and_quantizes():
    tx = Transaction(
        from_addr="0x" + "a" * 40,
        to_addr="0x" + "b" * 40,
        value=1.0,
        nonce=1,
        timestamp=1_700_000_000,
    )
    payload = tx.to_dict()
    again = Transaction.from_dict(payload)
    assert again.hash == tx.hash
    assert again.value == 1.0
    frac = Transaction.from_dict({**payload, "hash": "deadbeef", "value": 7.5})
    assert frac.hash == "deadbeef"
    assert frac.value == 7.5


def test_validate_amount_refuses_bool():
    from middleware.validators import validate_amount

    ok, err = validate_amount(True)
    assert ok is False
    assert "bool" in err
    ok, _err = validate_amount(1.5)
    assert ok is True
