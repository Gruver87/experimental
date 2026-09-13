#!/usr/bin/env python3
"""Wave C: Rocks native pack fallback counter + require-native refuse."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storage.rocks_store import RocksChainStore


def test_pack_fallback_counts_and_returns_json() -> None:
    store = object.__new__(RocksChainStore)
    store._native_pack_fallbacks = 0
    store._require_native_pack = False
    with patch.dict(sys.modules, {"abs_native": None}):
        # Force import failure path inside helper
        import storage.rocks_store as rs

        def _boom():
            raise RuntimeError("no native")

        with patch.object(rs, "json") as j:
            j.dumps.return_value = '{"a":1}'
            # Call helper with a fake that always fails native
            out = RocksChainStore._pack_row_native_or_json(
                store, "pack_account_row", {"a": 1}
            )
    assert isinstance(out, (bytes, bytearray))
    assert store._native_pack_fallbacks >= 1


def test_require_native_pack_refuses_fallback() -> None:
    store = object.__new__(RocksChainStore)
    store._native_pack_fallbacks = 0
    store._require_native_pack = True
    try:
        RocksChainStore._pack_row_native_or_json(store, "pack_tx_row_missing_xyz", {"x": 1})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "ABS_REQUIRE_NATIVE_CRYPTO" in str(exc) or "required" in str(exc).lower()
    assert store._native_pack_fallbacks >= 1


def test_source_needles() -> None:
    rocks = (ROOT / "storage" / "rocks_store.py").read_text(encoding="utf-8")
    assert "_native_pack_fallbacks" in rocks
    assert "_pack_row_native_or_json" in rocks
    assert "ABS_REQUIRE_NATIVE_CRYPTO" in rocks
    metrics = (ROOT / "observability" / "metrics.py").read_text(encoding="utf-8")
    assert "abs_rocksdb_native_pack_fallbacks" in metrics
