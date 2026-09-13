"""Wave L: block value satoshi, require_signatures honesty, NFT/bridge fail-closed."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_block_validator_value_satoshi_not_float():
    src = (
        Path(__file__).resolve().parents[2] / "execution" / "block_validator.py"
    ).read_text(encoding="utf-8")
    assert "float(tx.get(\"value\"" not in src
    assert "to_satoshi" in src


def test_blockchain_require_signatures_from_config():
    from core.blockchain import Blockchain
    from storage.database import Database
    import os
    import tempfile

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "rs.db"))
    db.initialize()
    cfg = SimpleNamespace(
        require_signatures=True,
        deployment_mode="dev",
        is_production=False,
        require_native_crypto=False,
        follower_genesis_sync=False,
        founder_address="0x" + "1" * 40,
        miner_address="0x" + "1" * 40,
        founder_percent=17.4,
        founder_initials="T",
        network_name="test",
        coin_symbol="ABS",
        resolve_genesis_timestamp=lambda: 1,
        genesis_alloc={},
        min_stake=1000,
        validators_manifest_path="",
        allow_state_root_rewrite=True,
        verify_peer_state_root=True,
        state_root_strict_p2p=True,
        state_root_legacy_cutoff_height=0,
        state_root_encoding_version=1,
        state_root_v2_ceremony_ok=False,
        chain_id=77777,
    )
    # Blockchain init is heavy — sniff source + light construct if possible
    src = (
        Path(__file__).resolve().parents[2] / "core" / "blockchain.py"
    ).read_text(encoding="utf-8")
    assert 'getattr(config, "require_signatures", False)' in src
    assert "self.require_signatures = False" not in src.split("bind_tip_encoding_config")[1][:800]


def test_nft_settle_uses_satoshi():
    src = (Path(__file__).resolve().parents[2] / "features" / "nft.py").read_text(
        encoding="utf-8"
    )
    assert "balance_delta_satoshi" in src
    assert "nft_council_gate_unavailable" in src


def test_bridge_confirm_refuses_without_persist():
    from bridge.store_adapter import BridgeStoreAdapter

    class _NoConfirm:
        def get_bridge_lock(self, h):
            return {"status": "pending", "tx_hash": h}

        def get_bridge_locks(self, limit=500):
            return []

    ad = BridgeStoreAdapter(_NoConfirm())
    out = ad.confirm_bridge_lock_status("abc")
    assert out["ok"] is False
    assert out["error"] == "confirm_bridge_lock_unavailable"


def test_nft_mutation_auth_requires_sig_without_jwt():
    from api.http import _nft_mutation_authorized

    cfg = SimpleNamespace(jwt_enforce_admin=False)
    err = _nft_mutation_authorized(cfg, {"token_id": "t1"}, "0x" + "a" * 40)
    assert err and "signature" in err

    cfg2 = SimpleNamespace(jwt_enforce_admin=True)
    assert _nft_mutation_authorized(cfg2, {}, "0x" + "a" * 40) is None
