"""Wave R: tx_signer fee honesty, mempool satoshi store, AI avg, /tx/verify."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def test_tx_signer_hash_refuses_invented_fee():
    from crypto.tx_signer import TransactionSigner

    try:
        TransactionSigner.hash_transaction({"from": "a", "to": "b", "amount": 1, "nonce": 0})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "fee" in str(exc)


def test_tx_signer_hash_with_explicit_fee():
    from crypto.tx_signer import TransactionSigner

    h1 = TransactionSigner.hash_transaction(
        {"from": "a", "to": "b", "amount": 1, "nonce": 0, "fee": 0.002}
    )
    h2 = TransactionSigner.hash_transaction(
        {"from": "a", "to": "b", "amount": 1, "nonce": 0, "fee": 0.002}
    )
    assert h1 == h2
    src = (ROOT / "crypto" / "tx_signer.py").read_text(encoding="utf-8")
    assert "get('fee', 0.001)" not in src
    assert 'get("fee", 0.001)' not in src


def test_tx_signer_verify_ecdsa_missing_raises():
    from crypto import tx_signer

    with patch.object(tx_signer, "CRYPTO_AVAILABLE", False):
        try:
            tx_signer.TransactionSigner.verify_signature(
                {"public_key": "ab" * 33, "fee": 0.001}, "cd" * 32, "0x" + "a" * 40
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "unavailable" in str(exc)


def test_mempool_store_roundtrip_satoshi():
    from blockchain.mempool import MempoolTransaction, _tx_from_store_dict, _tx_to_store_dict
    from runtime.amount import to_satoshi

    tx = MempoolTransaction(
        tx_hash="h1",
        from_addr="0x" + "a" * 40,
        to_addr="0x" + "b" * 40,
        amount=1.5,
        fee=0.002,
    )
    raw = _tx_to_store_dict(tx)
    assert raw["amount_satoshi"] == int(to_satoshi(1.5))
    assert raw["fee_satoshi"] == int(to_satoshi(0.002))
    back = _tx_from_store_dict(raw)
    assert back.amount_satoshi == raw["amount_satoshi"] if hasattr(back, "amount_satoshi") else True
    assert back.fee_satoshi == raw["fee_satoshi"]


def test_ai_validator_empty_avg_zero():
    from features.ai_validator import AIValidatorEngine

    stats = AIValidatorEngine().get_stats()
    assert stats["avg_performance"] == 0.0
    assert stats["validators"] == 0


def test_tx_verify_unavailable_needle():
    src = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    chunk = src.split('path == "/tx/verify"')[1].split("elif path")[0]
    assert '"valid": None' in chunk or "'valid': None" in chunk
    assert "unavailable" in chunk
