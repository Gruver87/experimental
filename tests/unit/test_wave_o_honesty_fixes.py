"""Wave O: P2P wire satoshi, DAO int quorum, no gas_price invent."""

from __future__ import annotations

from pathlib import Path

from runtime.amount import to_satoshi


ROOT = Path(__file__).resolve().parents[2]


def test_p2p_validator_register_stake_satoshi():
    from crypto import native

    reg = native.validate_p2p_validator_register(
        {"address": "0x" + "a" * 40, "stake": 1000.0, "node_id": "abs-1"}
    )
    assert reg is not None
    assert reg["stake_satoshi"] == int(to_satoshi(1000.0))
    assert reg["stake"] == 1000.0
    assert native.validate_p2p_validator_register({"address": "", "stake": 1}) is None


def test_p2p_cross_shard_and_migration_satoshi():
    from crypto import native

    tx = {
        "tx_id": "abcd1234efgh5678",
        "from_shard": 0,
        "to_shard": 1,
        "from_addr": "0x" + "a" * 40,
        "to_addr": "0x" + "b" * 40,
        "amount": 25.5,
        "status": "debited",
        "source_node": "shard-src",
    }
    ok = native.validate_p2p_cross_shard_tx(tx)
    assert ok is not None
    assert ok["amount_satoshi"] == int(to_satoshi(25.5))
    assert ok["amount"] == 25.5

    mig = native.validate_p2p_shard_migration(
        {
            "type": "shard_migration",
            "address": "0x" + "c" * 40,
            "from_shard": 0,
            "to_shard": 2,
            "balance": 10.0,
        }
    )
    assert mig is not None
    assert mig["balance_satoshi"] == int(to_satoshi(10.0))


def test_dao_empty_set_no_invented_quorum():
    import os
    import tempfile

    from runtime.pool_locks import PoolLockManager
    from storage.database import Database

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(path)
        db.initialize()
        pl = PoolLockManager(db, "0xminer")
        out = pl.dao_vote("ecosystem", "0xminer", validator_registry=None)
        assert out["success"] is True
        assert out["validators"] == 0
        assert out["quorum_reached"] is False
        assert out["unlocked"] is False
    finally:
        try:
            db.close()
        except Exception:
            pass
        os.remove(path)


def test_dao_int_quorum_with_registry():
    import os
    import tempfile

    from consensus.validator_registry import ValidatorRegistry
    from runtime.pool_locks import PoolLockManager
    from storage.database import Database

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = Database(path)
        db.initialize()
        miner = "0xminer000000000000000000000000000001"
        pl = PoolLockManager(db, miner)
        vr = ValidatorRegistry()
        vr.register_validator(miner, 1000)
        out = pl.dao_vote("ecosystem", miner, validator_registry=vr)
        assert out["quorum_reached"] is True
        assert out["validators"] == 1
    finally:
        try:
            db.close()
        except Exception:
            pass
        os.remove(path)


def test_p2p_no_gas_price_or_invent():
    src = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "fee_gas_price_unset" in src
    assert 'gas_price_wei", 0.001) or 0.001' not in src
