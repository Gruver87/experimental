#!/usr/bin/env python3
"""Chain backup/restore helpers (RocksDB chainstore + legacy SQLite)."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Tuple


def _rocksdb_initialized(path: Path) -> bool:
    return (path / "CURRENT").is_file()


def resolve_storage(data_dir: str) -> Tuple[str, str, str]:
    """
    Resolve chain storage layout.

    Returns (engine, chainstore_path, storage_root).
    ``storage_root`` is the prod-style data directory (``/app/data``).
    ``chainstore_path`` is the path passed to ``HybridDatabase`` / ``RocksChainStore``.
    """
    base = Path(data_dir).resolve()

    nested = base / "chainstore"
    if nested.is_dir() and (_rocksdb_initialized(nested) or (nested / "aux.db").is_file()):
        return "rocksdb", str(nested), str(base)

    if _rocksdb_initialized(base):
        root = str(base.parent) if base.name == "chainstore" else str(base)
        return "rocksdb", str(base), root

    if (base / "blockchain.db").is_file() or (base / "chain.db").is_file():
        return "sqlite", "", str(base)

    if nested.is_dir():
        return "rocksdb", str(nested), str(base)

    raise FileNotFoundError(
        f"no chainstore/ or blockchain.db under {base}"
    )


def detect_engine(data_dir: str) -> str:
    return resolve_storage(data_dir)[0]


def _storage_layout(chainstore_path: str, storage_root: str) -> str:
    nested = os.path.join(storage_root, "chainstore")
    if os.path.normcase(chainstore_path) == os.path.normcase(nested):
        return "nested"
    return "direct"


def backup_chainstore(data_dir: str, dest_dir: str) -> Dict[str, Any]:
    data_dir = os.path.abspath(data_dir)
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)

    engine, chainstore, storage_root = resolve_storage(data_dir)
    manifest: Dict[str, Any] = {
        "engine": engine,
        "layout": _storage_layout(chainstore, storage_root) if engine == "rocksdb" else "nested",
        "source": data_dir,
        "created_at": int(time.time()),
        "files": [],
    }

    if engine == "rocksdb":
        from storage.rocks_store import RocksChainStore

        out_chain = os.path.join(dest_dir, "chainstore")
        if os.path.isdir(out_chain):
            shutil.rmtree(out_chain)
        store = RocksChainStore(chainstore, synchronous="FULL")
        store.initialize()
        try:
            manifest["chain_tip"] = int(store.get_chain_tip() or 0)
            store.backup_to(out_chain)
        finally:
            store.close()

        aux_src = os.path.join(chainstore, "aux.db")
        if os.path.isfile(aux_src):
            shutil.copy2(aux_src, os.path.join(out_chain, "aux.db"))
            manifest["files"].append("chainstore/aux.db")
        manifest["files"].append("chainstore/")
    else:
        db_name = (
            "blockchain.db"
            if os.path.isfile(os.path.join(data_dir, "blockchain.db"))
            else "chain.db"
        )
        src = os.path.join(data_dir, db_name)
        dst = os.path.join(dest_dir, db_name)
        from storage.database import Database

        db = Database(src)
        db.initialize()
        try:
            manifest["chain_tip"] = int(db.get_chain_tip() or 0)
            # Fail-closed: online backup API only — never silent copy2 of a live DB.
            db.backup_to(dst)
        finally:
            db.close()
        for suffix in ("-wal", "-shm"):
            side = src + suffix
            if os.path.isfile(side):
                shutil.copy2(side, dst + suffix)
        manifest["files"].append(db_name)

    manifest_path = os.path.join(dest_dir, "backup_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def _clear_rocksdb_dir(path: str) -> None:
    target = Path(path)
    if not target.is_dir():
        return
    if _rocksdb_initialized(target):
        shutil.rmtree(target)
        return
    for child in target.iterdir():
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)


def restore_chainstore(backup_dir: str, data_dir: str, *, force: bool = False) -> Dict[str, Any]:
    backup_dir = os.path.abspath(backup_dir)
    data_dir = os.path.abspath(data_dir)
    manifest_path = os.path.join(backup_dir, "backup_manifest.json")
    if not os.path.isfile(manifest_path):
        raise FileNotFoundError(f"missing {manifest_path}")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    engine = manifest.get("engine", "")
    if engine not in ("rocksdb", "sqlite"):
        raise ValueError(f"unknown engine in manifest: {engine}")

    layout = manifest.get("layout", "nested")

    if force:
        if engine == "rocksdb":
            if layout == "direct":
                _clear_rocksdb_dir(data_dir)
            else:
                nested = os.path.join(data_dir, "chainstore")
                if os.path.isdir(nested):
                    shutil.rmtree(nested)
        for name in ("blockchain.db", "chain.db"):
            base = os.path.join(data_dir, name)
            for path in (base, base + "-wal", base + "-shm"):
                if os.path.isfile(path):
                    os.remove(path)

    os.makedirs(data_dir, exist_ok=True)

    if engine == "rocksdb":
        src = os.path.join(backup_dir, "chainstore")
        if not os.path.isdir(src):
            raise FileNotFoundError(f"missing backup chainstore: {src}")
        if layout == "direct":
            dst = data_dir
            _clear_rocksdb_dir(dst)
            os.makedirs(dst, exist_ok=True)
            for item in os.listdir(src):
                s = os.path.join(src, item)
                d = os.path.join(dst, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
        else:
            dst = os.path.join(data_dir, "chainstore")
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    else:
        restored = False
        for name in ("blockchain.db", "chain.db"):
            src = os.path.join(backup_dir, name)
            if os.path.isfile(src):
                dst = os.path.join(data_dir, name)
                shutil.copy2(src, dst)
                for suffix in ("-wal", "-shm"):
                    side = src + suffix
                    if os.path.isfile(side):
                        shutil.copy2(side, dst + suffix)
                restored = True
                break
        if not restored:
            raise FileNotFoundError("no blockchain.db or chain.db in backup")

    return manifest


def read_chain_tip(chainstore_or_data_dir: str) -> int:
    """Read chain tip from a Rocks chainstore path or nested data directory.

    Fail-closed: missing/corrupt storage raises — never invent tip 0 as success.
    """
    engine, chainstore, storage_root = resolve_storage(chainstore_or_data_dir)

    if engine == "rocksdb":
        path = chainstore
        from storage.rocks_store import RocksChainStore

        store = RocksChainStore(
            path, synchronous="FULL", block_cache_mb=0, write_buffer_mb=0
        )
        store.initialize()
        try:
            return int(store.get_chain_tip() or 0)
        finally:
            store.close()

    db_name = (
        "blockchain.db"
        if os.path.isfile(os.path.join(storage_root, "blockchain.db"))
        else "chain.db"
    )
    from storage.database import Database

    db_path = os.path.join(storage_root, db_name)
    db = Database(db_path)
    db.initialize()
    try:
        return int(db.get_chain_tip() or 0)
    finally:
        db.close()


def verify_chain_tip(data_dir: str, expected_tip: int | None = None) -> int:
    from runtime.config import Config
    from storage.factory import open_database

    engine, chainstore, storage_root = resolve_storage(data_dir)
    cfg = Config()
    cfg.db_engine = engine
    if engine == "rocksdb":
        cfg.db_path = chainstore
        cfg.rocksdb_sync = "FULL"
    else:
        db_name = (
            "blockchain.db"
            if os.path.isfile(os.path.join(storage_root, "blockchain.db"))
            else "chain.db"
        )
        cfg.db_path = os.path.join(storage_root, db_name)

    db = open_database(cfg)
    db.initialize()
    try:
        tip = int(db.get_chain_tip() or 0)
        genesis = db.get_block(0)
    finally:
        db.close()

    if not genesis:
        return 2
    if (
        expected_tip is not None
        and int(expected_tip) > 0
        and tip != int(expected_tip)
    ):
        return 3
    return 0
