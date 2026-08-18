#!/usr/bin/env python3
"""Tests for runtime.amount satoshi helpers."""

from decimal import Decimal

from runtime.amount import ABS_DECIMALS, SATOSHI_MULTIPLIER, from_satoshi, to_satoshi


def test_to_satoshi_junk_is_value_error_not_native_fallback():
    from runtime.amount import to_satoshi
    import pytest

    with pytest.raises(ValueError):
        to_satoshi("not-a-number")


def test_satoshi_round_trip_whole_abs():
    assert to_satoshi(1) == SATOSHI_MULTIPLIER
    assert from_satoshi(SATOSHI_MULTIPLIER) == Decimal("1")
    assert ABS_DECIMALS == 6


def test_to_satoshi_floors_dust():
    # 0.0000001 ABS -> 0 satoshi
    assert to_satoshi("0.0000001") == 0
    assert to_satoshi("1.9999999") == 1_999_999


def test_parse_abs_int_accepts_whole_values():
    from runtime.amount import parse_abs_int

    assert parse_abs_int(10) == 10
    assert parse_abs_int(10.0) == 10
    assert parse_abs_int("10") == 10
    assert parse_abs_int(None) == 0
    assert parse_abs_int(-3, allow_negative=True) == -3


def test_parse_abs_int_refuses_fractional_and_bool():
    from runtime.amount import parse_abs_int
    import pytest

    with pytest.raises(ValueError):
        parse_abs_int(1.5)
    with pytest.raises(ValueError):
        parse_abs_int("1.5")
    with pytest.raises(ValueError):
        parse_abs_int(True)
    with pytest.raises(ValueError):
        parse_abs_int(-1)


def test_parse_rpc_value_abs_wei_and_abs():
    from runtime.amount import WEI_PER_ABS, parse_rpc_value_abs
    import pytest

    assert parse_rpc_value_abs(hex(WEI_PER_ABS)) == 1.0
    assert parse_rpc_value_abs("0x64") == 100.0
    assert parse_rpc_value_abs("0.001") == 0.001
    assert parse_rpc_value_abs(7.5) == 7.5
    assert parse_rpc_value_abs(None) == 0.0
    # Sub-satoshi wei floors (1 wei cannot become a phantom float ABS).
    assert parse_rpc_value_abs(hex(WEI_PER_ABS + 1)) == 1.0
    with pytest.raises(ValueError):
        parse_rpc_value_abs(True)


def test_parse_tx_value_thin_wraps_rpc_parser():
    from api.http import _parse_tx_value

    assert _parse_tx_value("0xde0b6b3a7640000") == 1.0
    assert _parse_tx_value("1.5") == 1.5


def test_abs_to_wei_preserves_sub_satoshi_gas_price():
    from runtime.amount import WEI_PER_ABS, abs_to_wei, to_satoshi
    import pytest

    assert abs_to_wei(1) == WEI_PER_ABS
    assert abs_to_wei("0.0000001") == 10**11
    # Satoshi path would floor this default gas price to 0 — that is why gas uses wei.
    assert to_satoshi("0.0000001") == 0
    with pytest.raises(TypeError):
        abs_to_wei(True)
    with pytest.raises(ValueError):
        abs_to_wei(-1)


def test_http_abs_accepts_fractional_bridge_amount():
    from api.http import _http_abs
    import pytest

    assert _http_abs(42.5) == 42.5
    assert _http_abs("7.5") == 7.5
    with pytest.raises(ValueError):
        _http_abs(True)


def test_money_abs_refuses_bool_and_quantizes():
    from runtime.amount import money_abs
    import pytest

    assert money_abs(7.5) == 7.5
    assert money_abs("32") == 32.0
    with pytest.raises(TypeError, match="bool is not an amount"):
        money_abs(True)


def test_parse_p2p_wire_abs_refuses_bool_and_hex():
    from runtime.amount import parse_p2p_wire_abs
    import pytest

    assert parse_p2p_wire_abs(1.25) == 1.25
    assert parse_p2p_wire_abs("7.5") == 7.5
    with pytest.raises(ValueError, match="bool"):
        parse_p2p_wire_abs(True)
    with pytest.raises(ValueError, match="hex"):
        parse_p2p_wire_abs("0x1")


def test_parse_finite_number_refuses_bool_and_nan():
    from runtime.amount import parse_finite_number
    import pytest

    assert parse_finite_number(97000.5) == 97000.5
    with pytest.raises(ValueError, match="bool"):
        parse_finite_number(True)
    with pytest.raises(ValueError, match="finite"):
        parse_finite_number(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        parse_finite_number(float("inf"))


def test_apply_delta_and_account_helpers():
    from runtime.amount import account_balance_abs, apply_delta_satoshi, dual_write_balance

    assert apply_delta_satoshi(1_000_000, -0.25) == 750_000
    row: dict = {}
    dual_write_balance(row, 2)
    assert account_balance_abs(row) == 2.0


def test_immutable_state_uses_shared_multiplier():
    from blockchain.immutable_state import SATOSHI_MULTIPLIER as ims_mult
    from runtime.amount import SATOSHI_MULTIPLIER as amt_mult

    assert ims_mult == amt_mult


def test_plan_transfer_fees_sat_is_integer_only():
    from runtime.amount import can_afford_transfer_sat, plan_transfer_fees_sat

    # 21000 * 1e-7 ABS = 0.0021 ABS = 2100 satoshi
    plan = plan_transfer_fees_sat(21000, 0.0000001, 0.5, 1.0)
    assert plan["fee_sat"] == 2100
    assert plan["burned_sat"] == 1050
    assert plan["miner_fee_sat"] == 1050
    assert plan["value_sat"] == 1_000_000
    assert plan["total_cost_sat"] == 1_002_100
    assert all(isinstance(v, int) for v in plan.values())
    assert can_afford_transfer_sat(1_002_100, plan["total_cost_sat"])
    assert not can_afford_transfer_sat(1_002_099, plan["total_cost_sat"])


def test_tx_money_abs_quantizes_and_refuses_bool():
    from runtime.amount import tx_money_abs
    import pytest

    money = tx_money_abs({"value": 7.5000003, "fee": 0.1, "burned": 0.02})
    assert money["value"] == 7.5
    assert money["fee"] == 0.1
    assert money["burned"] == 0.02
    money_amt = tx_money_abs({"amount": 42.5})
    assert money_amt["value"] == 42.5
    with pytest.raises(TypeError):
        tx_money_abs({"value": True})


def test_writeback_balance_abs_prefers_satoshi_and_refuses_bool():
    from runtime.amount import writeback_balance_abs
    import pytest

    assert writeback_balance_abs({"balance": 99.9, "balance_satoshi": 1_000_000}) == 1.0
    assert writeback_balance_abs({"balance": 7.5}) == 7.5
    assert writeback_balance_abs({"balance": 7.5000003}) == 7.5
    with pytest.raises(TypeError):
        writeback_balance_abs({"balance": True})
