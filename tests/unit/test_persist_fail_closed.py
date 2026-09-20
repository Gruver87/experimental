"""Hot persist fail-closed: PersistError instead of soft False."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.chain_storage import ChainStorage
from storage.database import Database
from storage.types import PersistError


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "persist.db")
    database = Database(path)
    database.initialize()
    yield database
    database.close()


def test_sqlite_save_block_raises_persist_error(db):
    with patch.object(db, "_insert_block", side_effect=RuntimeError("disk boom")):
        with pytest.raises(PersistError, match="save_block failed"):
            db.save_block(
                {
                    "height": 1,
                    "hash": "ab" * 32,
                    "parent_hash": "0" * 64,
                    "timestamp": 1,
                    "miner": "0xm",
                    "transactions": [],
                }
            )


def test_sqlite_persist_block_atomic_raises_persist_error(db):
    with patch.object(
        db, "_persist_block_locked", side_effect=RuntimeError("batch boom")
    ):
        with pytest.raises(PersistError, match="persist_block_atomic failed"):
            db.persist_block_atomic(
                {
                    "height": 1,
                    "hash": "cd" * 32,
                    "parent_hash": "0" * 64,
                    "timestamp": 1,
                    "miner": "0xm",
                    "transactions": [],
                },
                [],
            )


def test_sqlite_save_transaction_raises_persist_error(db):
    with patch.object(
        db, "_insert_transaction", side_effect=RuntimeError("tx boom")
    ):
        with pytest.raises(PersistError, match="save_transaction failed"):
            db.save_transaction(
                {
                    "hash": "ef" * 32,
                    "from_addr": "0xa",
                    "to_addr": "0xb",
                    "value": 1.0,
                    "fee": 0.001,
                    "nonce": 0,
                }
            )


def test_chain_storage_save_block_raises(tmp_path):
    cs = ChainStorage(str(tmp_path / "chain"))
    bad_dir = tmp_path / "chain" / "blocks"
    # Make blocks path a file so open-for-write fails.
    import shutil

    shutil.rmtree(bad_dir)
    bad_dir.write_text("not-a-dir", encoding="utf-8")
    with pytest.raises(PersistError, match="Error saving block"):
        cs.save_block(1, {"height": 1, "hash": "11" * 32})


def test_persist_error_is_storage_unavailable():
    from storage.types import StorageUnavailableError

    assert issubclass(PersistError, StorageUnavailableError)
    exc = PersistError("x", reason_code="persist_failed")
    assert exc.reason_code == "persist_failed"


def test_source_needles_no_soft_false_on_hot_persist():
    rocks = (ROOT / "storage" / "rocks_store.py").read_text(encoding="utf-8")
    db = (ROOT / "storage" / "database.py").read_text(encoding="utf-8")
    chain = (ROOT / "storage" / "chain_storage.py").read_text(encoding="utf-8")
    assert "raise PersistError" in rocks
    assert "raise PersistError" in db
    assert "raise PersistError" in chain
    # Soft return False must not remain on these hot methods' except arms.
    for label, src, marker in (
        ("rocks save_block", rocks, "def save_block"),
        ("rocks persist_block_atomic", rocks, "def persist_block_atomic"),
        ("db save_block", db, "def save_block"),
        ("db persist_block_atomic", db, "def persist_block_atomic"),
    ):
        chunk = src.split(marker, 1)[1].split("\n    def ", 1)[0]
        assert "return False" not in chunk, f"{label} still soft-returns False"
