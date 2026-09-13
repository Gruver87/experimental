"""Wave Q: sharding/tx/MEV money honesty; wallet/attestation unavailable."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def test_sharding_balance_satoshi_needle():
    src = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    assert "/sharding/balance/" in src
    chunk = src.split('path.startswith("/sharding/balance/")')[1].split("elif path")[0]
    assert "balance_satoshi" in chunk
    assert "float(bc.get_balance" not in chunk
    assert "float(sh.get_shard_balance" not in chunk


def test_tx_sign_requires_fee_no_invent():
    src = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    chunk = src.split('path == "/tx/sign"')[1].split("elif path")[0]
    assert "fee or fee_satoshi required" in chunk
    assert 'fee", 0.001)' not in chunk


def test_mev_no_float_value_or_fee_times_1e9():
    src = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    assert "value=float(tx.amount)" not in src
    assert "value=float(t.get(\"value\"" not in src
    assert "tx.fee * 1e9" not in src


def test_wallet_ecdsa_missing_raises_unavailable():
    from crypto import wallet

    with patch.object(wallet, "ECDSA_AVAILABLE", False):
        try:
            wallet.verify_transaction_signature(
                {
                    "from": "0x" + "a" * 40,
                    "to": "0x" + "b" * 40,
                    "value": 1,
                    "nonce": 0,
                    "signature": "ab" * 32,
                    "public_key": "04" + "cd" * 64,
                    "chain_id": 1,
                }
            )
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "unavailable" in str(exc)


def test_validator_keys_derive_failure_unavailable():
    from crypto.validator_keys import ValidatorKeys

    mgr = ValidatorKeys.__new__(ValidatorKeys)
    att = {
        "validator": "0x" + "a" * 40,
        "signature": "ab" * 32,
        "public_key": "cd" * 33,
    }
    with patch("crypto.keys.KeyGenerator.derive_address", side_effect=RuntimeError("boom")):
        try:
            mgr.verify_attestation(att)
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "unavailable" in str(exc)
