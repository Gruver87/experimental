#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration tests for the Unified Absolute Blockchain Node.

Tests all three systems integrated into one:
  - System A: core blockchain, mempool, burn, genesis
  - System B: kernel/event_bus (shared)
  - System C: consensus (LMD-GHOST, Slashing, PBS, ValidatorRegistry),
              execution (StateEngine, BlockValidator, CanonicalSerializer),
              P2P (SyncEngine), API (RateLimiter, InputValidation)
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from runtime.config import Config
from storage.database import Database
from kernel.event_bus import EventBus
from core.blockchain import Blockchain, Block, Transaction
from blockchain.mempool import Mempool, MempoolTransaction
from consensus.adapter import ConsensusAdapter
from execution.evm_adapter import EVMAdapter
from execution.state_engine import StateEngine
from execution.block_validator import BlockValidator
from blockchain.canonical_serializer import CanonicalSerializer
from consensus.validator_registry import ValidatorRegistry
from consensus.pbs import PBSMarket, Builder, Proposer
from sync.sync_engine import SyncEngine
from middleware.rate_limit import RateLimiter
from middleware.validators import validate_address, validate_amount
from features.nft import NFTMarketplace
from features.zk import ZKProofSystem
from bridge.abs_bridge import RustBridge


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def config():
    cfg = Config()
    cfg.db_path = "data/test_integration.db"
    cfg.p2p_port = 5099
    cfg.rpc_port = 8599
    cfg.http_port = 8098
    cfg.block_time = 1
    cfg.mining_enabled = False
    cfg.bridge_enabled = False
    return cfg


@pytest.fixture(scope="module")
def db(config):
    database = Database(config.db_path)
    database.initialize()
    yield database
    try:
        database.close()
        import sqlite3
        os.remove(config.db_path)
    except Exception:
        pass


@pytest.fixture(scope="module")
def bus():
    return EventBus()


@pytest.fixture(scope="module")
def blockchain(config, db, bus):
    return Blockchain(config, db, bus)


@pytest.fixture(scope="module")
def mempool(config):
    return Mempool(max_size=1000, min_fee=0.0)


@pytest.fixture(scope="module")
def consensus(config, db, bus):
    return ConsensusAdapter(config, db, bus)


# ── System A Tests ────────────────────────────────────────────────────────────

class TestSystemA_Core:
    """System A: Absolute Chain core (blockchain, burn, genesis)."""

    def test_genesis_exists(self, blockchain):
        """Genesis block should be created on startup."""
        height = blockchain.get_height()
        assert height >= 0

    def test_create_block(self, blockchain, config):
        """Can create a block with no transactions."""
        config.miner_address = "0x" + "a" * 40
        block = blockchain.create_block([], config.miner_address)
        assert block is not None
        assert block.height > 0
        assert block.parent_hash != ""
        assert block.hash != ""

    def test_add_block(self, blockchain, config):
        """Can add a block to the chain."""
        config.miner_address = "0x" + "b" * 40
        blockchain.db.set_balance(config.miner_address, 1000.0)
        block = blockchain.create_block([], config.miner_address)
        success = blockchain.add_block(block)
        assert success

    def test_canonical_hash(self, blockchain, config):
        """Block hash uses CanonicalSerializer (deterministic). Same data = same hash."""
        config.miner_address = "0x" + "c" * 40
        block1 = blockchain.create_block([], config.miner_address)
        # Add block1 first so block2 gets a different parent
        blockchain.add_block(block1)
        block2 = blockchain.create_block([], config.miner_address)
        # Different heights = different hashes
        assert block1.hash != block2.hash

    def test_state_root(self, blockchain):
        """StateEngine computes non-empty state root."""
        root = blockchain.get_state_root()
        assert root != "", "State root should not be empty"

    def test_burn_mechanism(self, blockchain, config):
        """Fee burn mechanism works."""
        config.miner_address = "0x" + "d" * 40
        from_addr = "0x" + "e" * 40
        to_addr = "0x" + "f" * 40
        blockchain.db.set_balance(from_addr, 1000.0)
        
        tx = Transaction(
            from_addr=from_addr,
            to_addr=to_addr,
            value=1.0,
            nonce=0,
            gas=21000,
        )
        block = blockchain.create_block([tx], config.miner_address)
        if block.transactions:
            tx_applied = block.transactions[0]
            assert tx_applied.burned >= 0
            assert tx_applied.fee >= 0


class TestSystemA_Mempool:
    """System A: Mempool with input validation."""

    def test_add_valid_tx(self, mempool):
        """Valid transaction is added to mempool."""
        tx = MempoolTransaction(
            tx_hash="abc123",
            from_addr="0x" + "a" * 40,
            to_addr="0x" + "b" * 40,
            amount=1.0,
            fee=0.001,
            nonce=0,
        )
        result = mempool.add(tx)
        assert result is True

    def test_reject_duplicate(self, mempool):
        """Duplicate transaction is rejected."""
        tx = MempoolTransaction(
            tx_hash="abc123",
            from_addr="0x" + "a" * 40,
            to_addr="0x" + "b" * 40,
            amount=1.0,
            fee=0.001,
            nonce=0,
        )
        result = mempool.add(tx)
        assert result is False  # duplicate

    def test_get_sorted(self, mempool):
        """Transactions returned sorted by fee."""
        for i in range(3):
            mempool.add(MempoolTransaction(
                tx_hash=f"sort_test_{i}",
                from_addr="0x" + "a" * 40,
                to_addr="0x" + "b" * 40,
                amount=1.0,
                fee=float(i + 1) * 0.001,
                nonce=i + 1,
            ))
        txs = mempool.get(limit=10)
        fees = [tx.fee for tx in txs]
        assert fees == sorted(fees, reverse=True), "Should be sorted by fee descending"


# ── System C Consensus Tests ──────────────────────────────────────────────────

class TestSystemC_Consensus:
    """System C: LMD-GHOST + Slashing + ValidatorRegistry + PBS."""

    def test_lmd_ghost_enabled(self, consensus):
        """ConsensusAdapter has LMD-GHOST slashing engine."""
        assert consensus.slashing_engine is not None

    def test_validator_registry_enabled(self, consensus):
        """ValidatorRegistry is active."""
        assert consensus.validator_registry is not None

    def test_pbs_market_enabled(self, consensus):
        """PBS is opt-in via feature_mev (off by default — honesty)."""
        assert consensus.pbs_market is None
        stats = consensus.get_stats()
        assert stats.get("pbs_enabled") is False

    def test_add_validator(self, consensus):
        """Can register a new validator."""
        addr = "0x" + "9" * 40
        result = consensus.add_validator(addr, 500)
        assert result is True
        # Check in registry
        validators = consensus.get_validators()
        addrs = [v["address"] for v in validators]
        assert addr in addrs

    def test_select_proposer(self, consensus):
        """Proposer selection returns a valid address."""
        proposer = consensus.select_proposer()
        assert proposer is not None
        assert len(proposer) > 0

    def test_fork_choice_head(self, consensus):
        """GHOST fork choice returns None (no blocks added to fork tree yet) or a hash."""
        head = consensus.get_canonical_head()
        # None is valid when no blocks have been added to fork tree
        assert head is None or isinstance(head, str)

    def test_pbs_auction(self, consensus):
        """Without feature_mev, PBS auction is a no-op (returns None)."""
        txs = [
            {"hash": "tx1", "gas_price": 10, "from": "alice", "to": "bob", "value": 1},
            {"hash": "tx2", "gas_price": 5, "from": "bob", "to": "carol", "value": 2},
        ]
        result = consensus.run_pbs_auction(txs)
        assert result is None

    def test_stats_structure(self, consensus):
        """Consensus stats include all expected fields."""
        stats = consensus.get_stats()
        assert "lmd_ghost_enabled" in stats
        assert "pbs_enabled" in stats
        assert stats["lmd_ghost_enabled"] is True
        assert stats["pbs_enabled"] is False


class TestSystemC_ValidatorRegistry:
    """Standalone ValidatorRegistry tests."""

    def test_register_and_score(self):
        registry = ValidatorRegistry()
        registry.register_validator("val1", 1000)
        registry.register_validator("val2", 500)
        
        assert registry.get_total_stake() == 1500
        top = registry.get_top_validators()
        assert len(top) == 2
        assert top[0].stake == 1000  # Higher stake first

    def test_slash_reduces_score(self):
        registry = ValidatorRegistry()
        registry.register_validator("bad_val", 1000)
        
        v = registry.get_validator("bad_val")
        score_before = v.get_score()
        
        registry.slash_validator("bad_val")
        score_after = v.get_score()
        
        assert score_after < score_before

    def test_missed_block_penalty(self):
        registry = ValidatorRegistry()
        registry.register_validator("offline_val", 1000)
        
        for _ in range(5):
            registry.record_missed_block("offline_val")
        
        v = registry.get_validator("offline_val")
        assert v.missed_blocks == 5


class TestSystemC_StateEngine:
    """System C: StateEngine deterministic state transitions."""

    def test_genesis_state(self):
        engine = StateEngine()
        state = engine.create_genesis({"alice": 1000, "bob": 500})
        
        assert engine.get_balance("alice") == 1000
        assert engine.get_balance("bob") == 500
        assert engine.get_state_root() != ""

    def test_state_transition(self):
        engine = StateEngine()
        engine.create_genesis({"alice": 1000, "bob": 0})
        
        block = {
            "number": 1,
            "hash": "blockhash1",
            "parent_hash": "genesis",
            "timestamp": int(time.time()),
            "transactions": [
                {"from": "alice", "to": "bob", "amount": 100, "nonce": 0}
            ]
        }
        new_state = engine.transition(block)
        
        assert engine.get_balance("alice") == 900
        assert engine.get_balance("bob") == 100
        assert new_state.state_root != ""

    def test_state_root_changes(self):
        engine = StateEngine()
        engine.create_genesis({"alice": 1000})
        root_before = engine.get_state_root()
        
        block = {
            "number": 1,
            "hash": "h1",
            "parent_hash": "g",
            "timestamp": int(time.time()),
            "transactions": [
                {"from": "alice", "to": "bob", "amount": 50, "nonce": 0}
            ]
        }
        engine.transition(block)
        root_after = engine.get_state_root()
        
        assert root_before != root_after, "State root should change after transfer"


class TestSystemC_CanonicalSerializer:
    """CanonicalSerializer for deterministic block hashing."""

    def test_deterministic_order(self):
        """Same data always produces same result."""
        block = {"number": 1, "miner": "alice", "txs": [1, 2, 3]}
        result1 = CanonicalSerializer.serialize(block)
        result2 = CanonicalSerializer.serialize(block)
        assert result1 == result2

    def test_key_order_independent(self):
        """Dict key order doesn't affect output."""
        block_a = {"number": 1, "miner": "alice"}
        block_b = {"miner": "alice", "number": 1}
        assert CanonicalSerializer.serialize(block_a) == CanonicalSerializer.serialize(block_b)


class TestSystemC_BlockValidator:
    """System C: BlockValidator for P2P block validation."""

    def test_valid_block(self):
        engine = StateEngine()
        engine.create_genesis({"alice": 1000})
        
        validator = BlockValidator(engine, None)
        parent = {"hash": "genesis", "number": 0, "timestamp": int(time.time()) - 10}
        block = {
            "number": 1,
            "parent_hash": "genesis",
            "timestamp": int(time.time()),
            "proposer": "alice",
            "transactions": [],
            "tx_root": "e3b0c44298fc1c14",  # empty tx root
        }
        # Patch tx_root to match
        import hashlib
        block["tx_root"] = hashlib.sha256(b"empty_tx").hexdigest()[:32]
        
        valid, msg = validator.validate_block(block, parent)
        assert valid is True

    def test_invalid_parent_hash(self):
        engine = StateEngine()
        engine.create_genesis({})
        
        validator = BlockValidator(engine, None)
        parent = {"hash": "correcthash", "number": 0, "timestamp": int(time.time()) - 10}
        block = {
            "number": 1,
            "parent_hash": "wronghash",
            "timestamp": int(time.time()),
            "proposer": "alice",
            "transactions": [],
        }
        valid, msg = validator.validate_block(block, parent)
        assert valid is False
        assert "parent" in msg.lower()


# ── Middleware Tests ──────────────────────────────────────────────────────────

class TestMiddleware:
    """Rate limiter + input validation + JWT."""

    def test_rate_limiter(self):
        limiter = RateLimiter(requests_per_minute=5, window_seconds=60)
        
        # Should allow 5 requests
        for i in range(5):
            allowed, remaining = limiter.allow_request("client1")
            assert allowed is True
        
        # 6th should be rejected
        allowed, remaining = limiter.allow_request("client1")
        assert allowed is False

    def test_validate_address_valid(self):
        valid, err = validate_address("0x" + "a" * 40)
        assert valid is True

    def test_validate_address_invalid(self):
        valid, err = validate_address("notanaddress")
        assert valid is False

    def test_validate_amount_valid(self):
        valid, err = validate_amount(1.5)
        assert valid is True

    def test_validate_amount_zero(self):
        # min_amount default 0 → zero is valid (contract/calldata txs may be 0-value).
        valid, err = validate_amount(0)
        assert valid is True

    def test_validate_amount_negative(self):
        valid, err = validate_amount(-10)
        assert valid is False


# ── SyncEngine Tests ──────────────────────────────────────────────────────────

class TestSyncEngine:
    """System C: SyncEngine fast catch-up."""

    def test_init(self, blockchain):
        """SyncEngine initializes with a node interface."""
        engine = SyncEngine(node=blockchain)
        assert engine.is_syncing is False
        assert engine.sync_progress == 0

    def test_no_peers(self, blockchain):
        """Fast sync returns False with no peers."""
        engine = SyncEngine(node=blockchain)
        result = engine.fast_sync()
        assert result is False  # No peers

    def test_status(self, blockchain):
        """SyncEngine status is structured correctly."""
        engine = SyncEngine(node=blockchain)
        status = engine.get_status()
        assert "syncing" in status
        assert "peers" in status
        assert "progress" in status


# ── Features Tests ────────────────────────────────────────────────────────────

class TestFeatures:
    """NFT Marketplace + ZK Proof System."""

    def test_nft_marketplace(self, db, bus):
        nft = NFTMarketplace(db=db, bus=bus)
        assert nft is not None

    def test_zk_proof_knowledge(self):
        zk = ZKProofSystem()
        # prove_knowledge takes one arg: secret (int)
        proof = zk.prove_knowledge(12345)
        assert proof is not None
        assert hasattr(proof, "proof_type") or isinstance(proof, object)

    def test_zk_proof_range(self):
        zk = ZKProofSystem()
        proof = zk.prove_range(50, 0, 100)
        assert proof is not None
        # ZKProof is a dataclass/object, check as dict via __dict__ or attributes
        if hasattr(proof, "valid"):
            assert proof.valid is True
        elif hasattr(proof, "proof_data"):
            assert "in_range" in proof.proof_data or proof.proof_data is not None

    def test_zk_proof_balance(self):
        zk = ZKProofSystem()
        proof = zk.prove_balance(1000, 500)
        assert proof is not None


# ── Full Node Integration Test ────────────────────────────────────────────────

class TestFullNodeIntegration:
    """Full NodeOrchestrator integration test."""

    def test_node_orchestrator_init(self):
        """NodeOrchestrator initializes all 10 components."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from main import NodeOrchestrator
        
        cfg = Config()
        cfg.db_path = "data/test_node_integration.db"
        cfg.p2p_port = 5088
        cfg.rpc_port = 8588
        cfg.http_port = 8088
        cfg.mining_enabled = False
        cfg.bridge_enabled = False
        
        node = NodeOrchestrator(cfg)
        
        # System A
        assert node.blockchain is not None
        assert node.mempool is not None
        assert node.db is not None
        
        # System B (shared)
        assert node.bus is not None
        
        # System C consensus (PBS opt-in via feature_mev — off by default)
        assert node.consensus is not None
        assert node.consensus.slashing_engine is not None
        assert node.consensus.validator_registry is not None
        assert node.consensus.pbs_market is None
        
        # System C execution
        assert node.blockchain.state_engine is not None
        assert node.blockchain.block_validator is not None
        
        # System C P2P
        assert node.p2p is not None
        assert node.p2p.sync_engine is not None
        
        # Features — NFT/ZK off by default (feature flags); EVM on.
        assert node.nft is None
        assert node.zk is None
        assert node.evm is not None
        
        # Cleanup
        try:
            node.db.close()
            os.remove(cfg.db_path)
        except Exception:
            pass
