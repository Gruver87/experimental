"""Native amount/writeback fail-closed: refuse float satoshi + Decimal fee path."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native


pytestmark = pytest.mark.skipif(
    not native.native_available(),
    reason="abs_native not built",
)


def test_refuse_float_amount_satoshi_via_state_engine():
    before = {"alice": {"balance": 10_000_000, "nonce": 0}, "bob": {"balance": 0, "nonce": 0}}
    txs = [
        {
            "from": "alice",
            "to": "bob",
            "amount_satoshi": 1.5,
            "fee": 0,
            "nonce": 0,
        }
    ]
    with pytest.raises(Exception) as exc:
        native.state_engine_apply_transactions(
            json.dumps(before),
            json.dumps(txs),
        )
    assert "integer" in str(exc.value).lower() or "satoshi" in str(exc.value).lower()


def test_plan_transfer_fees_satoshi_integer():
    fee, burned, miner, total = native.plan_transfer_fees_satoshi(
        21_000, "0.0000001", "0.02", "1.0"
    )
    assert fee == 2100
    assert burned == 42
    assert miner == 2058
    assert total == 1_000_000 + 2100


def test_evm_writeback_refuses_float_balance_satoshi():
    accounts = {"0xabc": {"balance_satoshi": 1_000_000, "balance": 1.0, "nonce": 0}}
    ops = [
        {
            "op": "save_account",
            "address": "0xabc",
            "code": "",
            "nonce": 1,
            "storage": "{}",
            "balance_satoshi": 2.5,
        }
    ]
    with pytest.raises(Exception) as exc:
        native.evm_apply_writeback_ops(accounts, ops)
    assert "integer" in str(exc.value).lower() or "satoshi" in str(exc.value).lower()


def test_source_needles_no_f64_times_million_writeback():
    src = (ROOT / "native" / "abs_native" / "src" / "evm_writeback.rs").read_text(
        encoding="utf-8"
    )
    assert "f * 1_000_000.0" not in src
    assert "(sat as f64) / 1_000_000.0" not in src
    assert "from_satoshi_float_inner" in src
    amt = (ROOT / "native" / "abs_native" / "src" / "amount.rs").read_text(
        encoding="utf-8"
    )
    assert "to_f64().unwrap_or(0.0)" not in amt
    assert "must be integer satoshi" in amt
