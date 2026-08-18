"""RocksDB evm_logs persistence (hybrid prod path)."""
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from runtime.config import Config
from storage.hybrid_database import HybridDatabase


@pytest.fixture
def hybrid_db(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "chainstore")
    cfg.db_engine = "rocksdb"
    cfg.rocksdb_sync = "FULL"
    try:
        import abs_native  # noqa: F401
    except ImportError:
        pytest.skip("abs_native not built")
    db = HybridDatabase(cfg)
    db.initialize()
    yield db
    db.close()


def test_evm_logs_rocks_roundtrip(hybrid_db):
    logs = [{"topics": ["0xabc"], "data": "0x01"}]
    n = hybrid_db.save_evm_logs(
        "0x" + "11" * 20,
        logs,
        block_height=3,
        tx_hash="0x" + "aa" * 32,
        timestamp=1700000000,
    )
    assert n == 1
    by_tx = hybrid_db.get_evm_logs_by_tx("0x" + "aa" * 32)
    assert len(by_tx) == 1
    assert by_tx[0]["block_height"] == 3
    queried = hybrid_db.query_evm_logs(from_block=0, to_block=10, limit=10)
    assert len(queried) == 1
    assert hybrid_db.get_meta("aux_evm_logs_migrated_v1") is True


def test_query_evm_logs_single_height_skips_neighbors(hybrid_db):
    contract = "0x" + "22" * 20
    hybrid_db.save_evm_logs(
        contract,
        [{"topics": ["0x01"], "data": "old"}],
        block_height=1,
        tx_hash="0x" + "11" * 32,
    )
    hybrid_db.save_evm_logs(
        contract,
        [{"topics": ["0x01"], "data": "mid"}],
        block_height=4,
        tx_hash="0x" + "44" * 32,
    )
    hybrid_db.save_evm_logs(
        contract,
        [{"topics": ["0x01"], "data": "new"}],
        block_height=9,
        tx_hash="0x" + "99" * 32,
    )
    rows = hybrid_db.query_evm_logs(from_block=4, to_block=4, limit=10)
    assert [row["data"] for row in rows] == ["mid"]
