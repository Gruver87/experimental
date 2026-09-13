"""Wave N: native satoshi, PoS stake, multisig, secp None, eth root honesty."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from runtime.amount import to_satoshi


ROOT = Path(__file__).resolve().parents[2]


def test_consensus_engine_stake_satoshi():
    from consensus_engine import ConsensusEngine

    engine = ConsensusEngine()
    assert engine.add_validator("0x01", 100.0) is True
    assert engine.validators["0x01"].stake == int(to_satoshi(100.0))
    assert isinstance(engine.validators["0x01"].stake, int)
    assert engine.get_total_stake() == int(to_satoshi(100.0))


def test_finality_empty_set_does_not_invent_denom():
    from finality_engine import FinalityEngine

    fe = FinalityEngine()
    fe.set_active_validator_count(0)
    assert fe.active_validator_count == 0
    fe.create_checkpoint(0, "0xabc")
    # One vote against empty set must not justify (would if denom invented as 1).
    assert fe.add_attestation("0xv", 0, "0xabc") is True
    assert fe.checkpoints[0].is_justified is False


def test_multisig_amount_satoshi_and_execution_failed_not_success():
    from features.multisig import MultiSigWallet

    wallet = MultiSigWallet(["0x1", "0x2"], 2)
    created = wallet.create_transaction("0x3", 10)
    assert created["success"] is True
    assert created["amount_satoshi"] == int(to_satoshi(10))
    assert created["amount"] == int(to_satoshi(10))

    def boom(_tx):
        return {"success": False, "error": "debit refused"}

    wallet2 = MultiSigWallet(["0x1", "0x2"], 2, transaction_executor=boom)
    tx_id = wallet2.create_transaction("0x3", 1)["tx_id"]
    wallet2.confirm(tx_id, "0x1")
    second = wallet2.confirm(tx_id, "0x2")
    assert second["success"] is False
    assert second["error"] == "execution_failed"
    assert second["status"] == "execution_failed"
    assert wallet2.get_transaction(tx_id)["status"] == "execution_failed"


def test_verify_secp256k1_exception_returns_none_not_false():
    from crypto import native

    fake = MagicMock()
    fake.verify_secp256k1_sha256.side_effect = RuntimeError("probe down")
    fake.verify_secp256k1_sha256_batch.side_effect = RuntimeError("batch down")
    with patch.object(native, "_native", fake):
        assert native.verify_secp256k1_sha256(b"m", b"s", b"p") is None
        assert native.verify_secp256k1_sha256_batch([(b"m", b"s", b"p")]) is None


def test_eth_format_corrupt_stored_root_returns_none():
    from api.eth_format import block_receipts_root, block_transactions_root

    blk = {
        "tx_root": "not-a-valid-root",
        "receipts_root": "zz",
        "transactions": ["0x" + "11" * 32],
    }
    assert block_transactions_root(blk) is None
    assert block_receipts_root(blk) is None


def test_native_canonicalize_uses_to_satoshi_not_float_mul():
    src = (ROOT / "crypto" / "native.py").read_text(encoding="utf-8")
    assert "int(obj * 1_000_000)" not in src
    assert "int(float(row.get(\"balance\") or 0) * 1_000_000)" not in src
    assert "int(float(op.get(\"balance\") or 0) * 1_000_000)" not in src
