"""Wave P: stake unit, pool satoshi, sig/eth verify honesty, bridge fee money."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from runtime.amount import to_satoshi


ROOT = Path(__file__).resolve().parents[2]


def test_pool_locks_total_satoshi_and_spend_compare():
    import os
    import tempfile

    from runtime.pool_locks import PoolLockManager
    from storage.database import Database

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(path)
        db.initialize()
        miner = "0xminer000000000000000000000000000001"
        pl = PoolLockManager(db, miner)
        status = pl.get_status()
        eco = next(p for p in status["pools"] if p["id"] == "ecosystem")
        assert "total_satoshi" in eco
        assert eco["total_satoshi"] == int(to_satoshi(eco["total"]))
        assert eco["spendable_satoshi"] == 0
        # Locked pool refuses tiny spend without inventing float eps.
        ok, _ = pl.is_outgoing_allowed(eco["address"], 0.000001, eco["total"])
        assert ok is False
    finally:
        try:
            db.close()
        except Exception:
            pass
        os.remove(path)


def test_tx_validator_runtime_error_message():
    from blockchain.tx_validator import TransactionValidator

    with patch.object(
        TransactionValidator,
        "_verify_signature",
        side_effect=RuntimeError("signature verify unavailable: probe"),
    ):
        tx = {
            "from": "0x" + "a" * 40,
            "to": "0x" + "b" * 40,
            "amount": 1,
            "fee": 1,
            "nonce": 0,
            "signature": "ab" * 32,
            "public_key": "cd" * 33,
        }

        class _SM:
            def get_account(self, _a):
                return type("A", (), {"nonce": 0})()

            def get_balance_satoshi(self, _a):
                return 10_000_000_000

        ok, reason = TransactionValidator.validate(tx, _SM(), require_signature=True)
        assert ok is False
        assert reason == "signature verify unavailable: probe"
        assert reason != "Invalid signature"


def test_eth_tx_verify_unavailable_raises():
    from crypto import eth_tx

    with patch.object(eth_tx.native, "keccak256_digest", side_effect=RuntimeError("native down")):
        try:
            eth_tx.verify_eth_transaction_dict(
                {
                    "eth_signed": True,
                    "eth_tx_type": "legacy",
                    "eth_r": "11" * 32,
                    "eth_s": "22" * 32,
                    "eth_v": 37,
                    "chain_id": 1,
                    "to": "0x" + "a" * 40,
                    "data": "0x",
                    "nonce": 0,
                    "gasPrice": 1,
                    "gas": 21000,
                    "value": 0,
                    "from": "0x" + "b" * 40,
                }
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "unavailable" in str(exc)


def test_consensus_stake_http_unit_needle():
    src = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    assert '"unit": "satoshi"' in src
    assert "total_stake_satoshi" in src
    assert "total_stake_abs" in src


def test_bridge2_fee_money_abs_needle():
    src = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    assert 'path == "/bridge2/fee"' in src
    assert "amount_satoshi" in src
    assert 'float(qs.get("amount"' not in src.split('path == "/bridge2/fee"')[1].split("elif path")[0]
