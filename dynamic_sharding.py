# dynamic_sharding.py - COMPLETE SHARDING IMPLEMENTATION
import logging
import threading
import time
import json
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field

from crypto import native

logger = logging.getLogger(__name__)

@dataclass
class Shard:
    """Individual shard in the blockchain"""
    id: int
    name: str
    nodes: List[str] = field(default_factory=list)
    transactions: List[dict] = field(default_factory=list)
    block_height: int = 0
    last_hash: str = "0" * 64
    state_root: str = "0" * 64


@dataclass
class CrossShardTransaction:
    """Transaction between different shards"""
    tx_id: str
    from_shard: int
    to_shard: int
    from_addr: str
    to_addr: str
    amount: float
    status: str  # pending, debited, confirmed, failed
    created_at: float
    confirmed_at: Optional[float] = None


class ShardingManager:
    """Sharding: routing (single-DB labels) or distributed (per-node shard ownership)."""

    def __init__(
        self,
        num_shards: int = 4,
        db=None,
        assigned_shard_id: int = -1,
        node_id: str = "",
        validator_id: str = "",
        mode: str = "routing",
    ):
        self.num_shards = max(1, int(num_shards))
        self.shards: Dict[int, Shard] = {}
        self.cross_shard_txs: Dict[str, CrossShardTransaction] = {}
        self.pending_cross_txs: List[str] = []
        self.node_to_shard: Dict[str, int] = {}
        self.shard_lock = threading.Lock()
        self._db = db
        self.assigned_shard_id = int(assigned_shard_id)
        self.node_id = node_id or ""
        self.validator_id = (validator_id or node_id or "").strip()
        self.mode = (mode or "routing").lower()
        self._gossip_fn: Optional[Callable[[dict], None]] = None
        self._seen_validator_acks: set = set()
        self._relayed_validator_acks: set = set()
        self.coordinator = None
        try:
            from consensus.cross_shard_coordinator import CrossShardCoordinator
            self.coordinator = CrossShardCoordinator(self.num_shards)
        except ImportError:
            self.coordinator = None
        self._initialize_shards()

    def set_database(self, db) -> None:
        """Attach chain database for real balance lookups."""
        self._db = db

    def set_gossip_callback(self, fn: Optional[Callable[[dict], None]]) -> None:
        """Optional hook (P2P) to broadcast cross-shard payloads."""
        self._gossip_fn = fn

    def load_shard_committees(self, committees: Dict[int, List[str]]) -> int:
        if not self.coordinator:
            return 0
        return self.coordinator.load_shard_committees(committees)

    def load_validators_from_manifest(self, manifest: dict) -> int:
        if not self.coordinator:
            return 0
        return self.coordinator.load_validators_from_manifest(manifest, self.num_shards)

    def _ack_key(self, tx_id: str, shard_id: int, validator_id: str) -> str:
        return f"{tx_id}:{int(shard_id)}:{validator_id}"

    def _gossip_validator_ack(self, tx_id: str, shard_id: int, validator_id: str) -> None:
        """Fan-out validator ACK to P2P mesh (deduplicated per node)."""
        vid = (validator_id or "").strip()
        if not vid or not self._gossip_fn:
            return
        key = self._ack_key(tx_id, shard_id, vid)
        if key in self._seen_validator_acks:
            return
        self._seen_validator_acks.add(key)
        self._emit_validator_ack_gossip(tx_id, shard_id, vid)

    def _relay_validator_ack(self, tx_id: str, shard_id: int, validator_id: str) -> None:
        """Relay a peer ACK once (committee mesh fan-out)."""
        vid = (validator_id or "").strip()
        if not vid or not self._gossip_fn:
            return
        key = self._ack_key(tx_id, shard_id, vid)
        if key in self._relayed_validator_acks:
            return
        self._relayed_validator_acks.add(key)
        self._emit_validator_ack_gossip(tx_id, shard_id, vid)

    def _emit_validator_ack_gossip(self, tx_id: str, shard_id: int, validator_id: str) -> None:
        try:
            self._gossip_fn({
                "type": "cross_shard_ack",
                "tx_id": tx_id,
                "shard_id": int(shard_id),
                "validator_id": validator_id,
                "status": "validator_ack",
                "source_node": self.node_id,
            })
        except Exception as exc:
            logger.warning("cross-shard validator_ack gossip failed: %s", exc)

    def submit_cross_shard_validator_ack(
        self, tx_id: str, shard_id: int, validator_id: str = ""
    ) -> bool:
        """Committee peer signs ACK without re-applying debit/credit."""
        vid = (validator_id or self.validator_id or self.node_id or "").strip()
        if not vid or not self.coordinator:
            return False
        recorded = self.coordinator.record_validator_ack(tx_id, int(shard_id), vid)
        self._gossip_validator_ack(tx_id, int(shard_id), vid)
        return recorded

    def _record_shard_ack(self, tx_id: str, shard_id: int) -> bool:
        if not self.coordinator:
            return True
        if self.coordinator.has_shard_committee(shard_id):
            vid = self.validator_id or self.node_id
            if not vid:
                return False
            ok = self.coordinator.record_validator_ack(tx_id, shard_id, vid)
            self._gossip_validator_ack(tx_id, shard_id, vid)
            return ok
        ok = self.coordinator.record_ack(tx_id, shard_id)
        return ok

    def cross_shard_quorum_status(self, tx_id: str) -> Optional[dict]:
        if not self.coordinator:
            return None
        return self.coordinator.quorum_status(tx_id)

    def is_distributed(self) -> bool:
        return self.mode == "distributed" and self.assigned_shard_id >= 0

    def owns_shard(self, shard_id: int) -> bool:
        if not self.is_distributed():
            return True
        return int(shard_id) == self.assigned_shard_id

    def owns_address(self, address: str) -> bool:
        return self.owns_shard(self.get_shard_for_address(address))

    def _initialize_shards(self):
        """Initialize shards"""
        shard_names = ["Genesis", "Finance", "Governance", "Identity", "Data"]
        for i in range(self.num_shards):
            self.shards[i] = Shard(
                id=i,
                name=shard_names[i % len(shard_names)],
                nodes=[],
            )

    def get_shard_for_address(self, address: str) -> int:
        """Determine which shard an address belongs to"""
        hash_val = int(native.sha256_hex(address.encode()), 16)
        shard = hash_val % self.num_shards
        if self.coordinator:
            return self.coordinator.resolve_shard(address, shard)
        return shard

    def get_shard_for_transaction(self, tx: dict) -> int:
        """Determine shard for transaction"""
        from_addr = tx.get("from", tx.get("from_addr", ""))
        return self.get_shard_for_address(from_addr)

    @staticmethod
    def _tx_amount(tx: dict) -> float:
        raw = tx.get("value", tx.get("amount", 0))
        if isinstance(raw, str) and raw.startswith("0x"):
            return float(int(raw, 16))
        return float(raw)

    def add_transaction(self, tx: dict) -> tuple:
        """Add transaction to appropriate shard."""
        from_addr = tx.get("from", tx.get("from_addr", ""))
        to_addr = tx.get("to", tx.get("to_addr", ""))
        from_shard = self.get_shard_for_address(from_addr)
        to_shard = self.get_shard_for_address(to_addr)

        if self.is_distributed() and not self.owns_shard(from_shard):
            raise ValueError(
                f"foreign_shard_sender: shard {from_shard} not owned by node "
                f"(assigned={self.assigned_shard_id})"
            )

        if from_shard == to_shard:
            with self.shard_lock:
                self.shards[from_shard].transactions.append(tx)
            return from_shard, None

        amount = self._tx_amount(tx)
        tx_id = native.sha256_hex(
            json.dumps(
                {
                    "from": from_addr,
                    "to": to_addr,
                    "value": amount,
                    "nonce": tx.get("nonce", 0),
                },
                sort_keys=True,
            ).encode()
        )[:16]
        cross_tx = CrossShardTransaction(
            tx_id=tx_id,
            from_shard=from_shard,
            to_shard=to_shard,
            from_addr=from_addr,
            to_addr=to_addr,
            amount=amount,
            status="pending",
            created_at=time.time(),
        )
        with self.shard_lock:
            self.cross_shard_txs[tx_id] = cross_tx
            self.pending_cross_txs.append(tx_id)
        if self.coordinator:
            self.coordinator.begin(tx_id, from_shard, to_shard)

        if self.is_distributed() and self.owns_shard(from_shard):
            if self._debit_cross_shard_source(cross_tx):
                cross_tx.status = "debited"
                if self.coordinator:
                    self._record_shard_ack(tx_id, from_shard)
                self._gossip_cross_shard(tx_id)
            else:
                cross_tx.status = "failed"
                self.pending_cross_txs.remove(tx_id)
        elif not self.is_distributed():
            self.process_cross_shard_transactions()

        return from_shard, tx_id

    def _debit_cross_shard_source(self, tx: CrossShardTransaction) -> bool:
        from runtime.amount import from_satoshi_float, to_satoshi

        if not self._validate_cross_shard_tx(tx):
            return False
        try:
            need = int(to_satoshi(tx.amount))
        except (TypeError, ValueError):
            return False
        if need <= 0:
            return False
        if hasattr(self._db, "balance_delta_satoshi"):
            self._db.balance_delta_satoshi(tx.from_addr, -need)
        else:
            self._db.update_balance(tx.from_addr, -from_satoshi_float(need))
        return True

    def _gossip_cross_shard(self, tx_id: str) -> None:
        if not self._gossip_fn:
            return
        payload = self.export_cross_shard_payload(tx_id)
        if payload:
            try:
                self._gossip_fn(payload)
            except Exception as exc:
                logger.warning("cross-shard tx gossip failed: %s", exc)
    def export_cross_shard_payload(self, tx_id: str) -> Optional[dict]:
        tx = self.cross_shard_txs.get(tx_id)
        if not tx:
            return None
        return {
            "tx_id": tx.tx_id,
            "from_shard": tx.from_shard,
            "to_shard": tx.to_shard,
            "from_addr": tx.from_addr,
            "to_addr": tx.to_addr,
            "amount": tx.amount,
            "status": tx.status,
            "source_node": self.node_id,
        }

    def receive_cross_shard_credit(self, payload: dict) -> bool:
        """Dest-shard node: credit recipient after P2P gossip."""
        if not isinstance(payload, dict):
            return False
        to_shard = int(payload.get("to_shard", -1))
        if not self.owns_shard(to_shard):
            return False
        tx_id = str(payload.get("tx_id", ""))
        if not tx_id:
            return False
        with self.shard_lock:
            existing = self.cross_shard_txs.get(tx_id)
            if existing and existing.status == "confirmed":
                return True
            amount_raw = payload.get("amount", 0)
            to_addr = payload.get("to_addr", "")
            try:
                from runtime.amount import from_satoshi_float, to_satoshi

                amount_sat = int(to_satoshi(amount_raw))
            except (TypeError, ValueError):
                return False
            if amount_sat <= 0 or not to_addr:
                return False
            if not self._db or not (
                hasattr(self._db, "balance_delta_satoshi")
                or hasattr(self._db, "update_balance")
            ):
                return False
            if hasattr(self._db, "balance_delta_satoshi"):
                self._db.balance_delta_satoshi(to_addr, amount_sat)
            else:
                self._db.update_balance(to_addr, from_satoshi_float(amount_sat))
            amount = from_satoshi_float(amount_sat)
            cross_tx = existing or CrossShardTransaction(
                tx_id=tx_id,
                from_shard=int(payload.get("from_shard", 0)),
                to_shard=to_shard,
                from_addr=payload.get("from_addr", ""),
                to_addr=to_addr,
                amount=amount,
                status="confirmed",
                created_at=time.time(),
            )
            cross_tx.status = "confirmed"
            cross_tx.confirmed_at = time.time()
            self.cross_shard_txs[tx_id] = cross_tx
            if tx_id in self.pending_cross_txs:
                self.pending_cross_txs.remove(tx_id)
            if self.coordinator:
                self._record_shard_ack(tx_id, to_shard)
                if self.coordinator.quorum_reached(tx_id):
                    self.coordinator.clear(tx_id)
        return True

    def receive_cross_shard_ack(self, payload: dict) -> bool:
        """Record validator or shard ACK from P2P gossip (source or dest shard)."""
        if not isinstance(payload, dict):
            return False
        tx_id = str(payload.get("tx_id", ""))
        if not tx_id:
            return False
        with self.shard_lock:
            tx = self.cross_shard_txs.get(tx_id)
            if not tx:
                return False
            shard_id = int(payload.get("shard_id", payload.get("to_shard", tx.to_shard)))
            validator_id = str(payload.get("validator_id", "") or "").strip()
            owns_from = self.owns_shard(tx.from_shard)
            owns_to = self.owns_shard(tx.to_shard)
            if not owns_from and not owns_to:
                return False

            if self.coordinator:
                if validator_id:
                    key = self._ack_key(tx_id, shard_id, validator_id)
                    if key not in self._seen_validator_acks:
                        self._seen_validator_acks.add(key)
                        self.coordinator.record_validator_ack(tx_id, shard_id, validator_id)
                    self._relay_validator_ack(tx_id, shard_id, validator_id)
                elif owns_from:
                    self._record_shard_ack(tx_id, shard_id)

                if owns_from and self.coordinator.quorum_reached(tx_id):
                    self.coordinator.clear(tx_id)
                    tx.status = "confirmed"
                    tx.confirmed_at = time.time()
                    if tx_id in self.pending_cross_txs:
                        self.pending_cross_txs.remove(tx_id)
            elif owns_from:
                tx.status = "confirmed"
                tx.confirmed_at = time.time()
                if tx_id in self.pending_cross_txs:
                    self.pending_cross_txs.remove(tx_id)
        return True

    def process_cross_shard_transactions(self):
        """Legacy routing mode: debit+credit on one DB. Distributed: gossip debited."""
        if self.is_distributed():
            for tx_id in self.pending_cross_txs[:]:
                tx = self.cross_shard_txs.get(tx_id)
                if tx and tx.status == "debited":
                    self._gossip_cross_shard(tx_id)
            return

        for tx_id in self.pending_cross_txs[:]:
            tx = self.cross_shard_txs[tx_id]
            if self._validate_cross_shard_tx(tx):
                from runtime.amount import from_satoshi_float, to_satoshi

                try:
                    amount_sat = int(to_satoshi(tx.amount))
                except (TypeError, ValueError):
                    tx.status = "failed"
                    self.pending_cross_txs.remove(tx_id)
                    continue
                if hasattr(self._db, "balance_delta_satoshi"):
                    self._db.balance_delta_satoshi(tx.from_addr, -amount_sat)
                    self._db.balance_delta_satoshi(tx.to_addr, amount_sat)
                else:
                    amt = from_satoshi_float(amount_sat)
                    self._db.update_balance(tx.from_addr, -amt)
                    self._db.update_balance(tx.to_addr, amt)
                tx.status = "confirmed"
                tx.confirmed_at = time.time()
                self.pending_cross_txs.remove(tx_id)
            else:
                tx.status = "failed"
                self.pending_cross_txs.remove(tx_id)

    def _validate_cross_shard_tx(self, tx: CrossShardTransaction) -> bool:
        """Validate cross-shard transaction against chain balances (satoshi)."""
        from runtime.amount import to_satoshi, try_debit_satoshi

        try:
            need = int(to_satoshi(tx.amount))
        except (TypeError, ValueError):
            return False
        if need <= 0:
            return False
        if not tx.from_addr or not tx.to_addr:
            return False
        if not self._db or not (
            hasattr(self._db, "get_balance_satoshi")
            or hasattr(self._db, "get_balance")
        ):
            return False
        if hasattr(self._db, "get_balance_satoshi"):
            bal_sat = int(self._db.get_balance_satoshi(tx.from_addr))
        else:
            bal_sat = int(to_satoshi(self._db.get_balance(tx.from_addr)))
        try:
            try_debit_satoshi(bal_sat, tx.amount)
        except ValueError:
            return False
        return True

    def get_shard_balance(self, address: str, shard_id: int = None) -> float:
        """Balance for address (logical shard routing; funds live on L1 state)."""
        if shard_id is None:
            shard_id = self.get_shard_for_address(address)
        if self.is_distributed() and not self.owns_shard(shard_id):
            return 0.0
        if self._db and hasattr(self._db, "get_balance"):
            return float(self._db.get_balance(address))
        return 0.0

    def get_shard_state(self, shard_id: int) -> dict:
        """Get state of a specific shard"""
        if shard_id not in self.shards:
            return {}
        shard = self.shards[shard_id]
        return {
            "id": shard.id,
            "name": shard.name,
            "nodes": len(shard.nodes),
            "transactions": len(shard.transactions),
            "block_height": shard.block_height,
            "last_hash": shard.last_hash,
            "owned_by_node": self.owns_shard(shard_id),
        }

    def get_all_shards_state(self) -> dict:
        """Get state of all shards"""
        return {
            "num_shards": self.num_shards,
            "mode": self.mode,
            "assigned_shard_id": self.assigned_shard_id,
            "node_id": self.node_id,
            "shards": [self.get_shard_state(i) for i in range(self.num_shards)],
            "pending_cross_txs": len(self.pending_cross_txs),
            "total_cross_txs": len(self.cross_shard_txs),
        }

    def register_node(self, node_id: str, shard_id: int = None) -> bool:
        """Register a node to a shard"""
        if shard_id is None:
            shard_id = hash(node_id) % self.num_shards
        shard_id = int(shard_id) % self.num_shards
        self.node_to_shard[node_id] = shard_id
        if node_id not in self.shards[shard_id].nodes:
            self.shards[shard_id].nodes.append(node_id)
        return True

    def list_nodes(self) -> List[dict]:
        return [
            {"node_id": node_id, "shard_id": shard_id}
            for node_id, shard_id in self.node_to_shard.items()
        ]

    def mine_shard_block(self, shard_id: int, miner: str = "") -> Optional[dict]:
        """Mine a block for a specific shard"""
        shard = self.shards.get(shard_id)
        if not shard or not shard.transactions:
            return None

        transactions = shard.transactions[:100]
        shard.transactions = shard.transactions[100:]

        block = {
            "height": shard.block_height,
            "shard_id": shard_id,
            "miner": miner,
            "transactions": transactions,
            "prev_hash": shard.last_hash,
            "timestamp": time.time(),
            "state_root": native.sha256_hex(json.dumps(transactions).encode())[:16],
        }

        block_string = (
            f"{block['height']}{block['shard_id']}{block['transactions']}"
            f"{block['prev_hash']}{block['timestamp']}"
        )
        block["hash"] = native.sha256_hex(block_string.encode())[:16]

        shard.block_height += 1
        shard.last_hash = block["hash"]

        return block

    def get_stats(self) -> dict:
        """Get sharding statistics"""
        tier = "distributed" if self.is_distributed() else "routing"
        return {
            "enabled": True,
            "tier": tier,
            "mode": self.mode,
            "assigned_shard_id": self.assigned_shard_id,
            "node_id": self.node_id,
            "balance_source": "chain_state" if self._db else "unavailable",
            "total_shards": self.num_shards,
            "total_transactions": sum(len(s.transactions) for s in self.shards.values()),
            "total_cross_shard_txs": len(self.cross_shard_txs),
            "pending_cross_shard_txs": len(self.pending_cross_txs),
            "registered_nodes": len(self.node_to_shard),
            "coordinator": self.coordinator.status() if self.coordinator else None,
            "shard_details": [
                {
                    "id": s.id,
                    "name": s.name,
                    "nodes": len(s.nodes),
                    "txs": len(s.transactions),
                    "height": s.block_height,
                    "owned": self.owns_shard(s.id),
                }
                for s in self.shards.values()
            ],
        }

    def plan_reshard(self, new_num_shards: int, effective_epoch: int = 0) -> dict:
        if not self.coordinator:
            raise RuntimeError("reshard_coordinator_unavailable")
        return self.coordinator.plan_reshard(new_num_shards, effective_epoch)

    def discover_reshard_migrations(self) -> int:
        if not self.coordinator or not self._db:
            return 0
        plan = self.coordinator.status().get("reshard_plan") or {}
        if plan.get("status") != "planned":
            return 0
        accounts = self._db.get_all_accounts() if hasattr(self._db, "get_all_accounts") else []
        return self.coordinator.discover_migrations(
            accounts,
            int(plan.get("from_shards", self.num_shards)),
            int(plan.get("to_shards", self.num_shards)),
        )

    def apply_reshard(self) -> bool:
        if not self.coordinator:
            return False
        if self.coordinator.apply_reshard():
            self.num_shards = self.coordinator.num_shards
            return True
        return False

    def process_reshard_migrations(self, limit: int = 20) -> dict:
        if not self.coordinator:
            return {"processed": 0, "error": "coordinator_unavailable"}
        result = self.coordinator.process_local_migrations(
            self._db,
            self.owns_shard,
            limit=limit,
        )
        for payload in result.get("payloads", []):
            self._gossip_migration(payload)
        return result

    def receive_shard_migration(self, payload: dict) -> bool:
        if not self.coordinator:
            return False
        credited = self.coordinator.apply_migration_credit(payload, self._db, self.owns_shard)
        if credited and self._gossip_fn:
            try:
                self._gossip_fn({
                    "type": "shard_migration_ack",
                    "address": payload.get("address", ""),
                    "to_shard": payload.get("to_shard", 0),
                })
            except Exception as exc:
                logger.warning("shard_migration_ack gossip failed: %s", exc)
        return credited

    def _gossip_migration(self, payload: dict) -> None:
        if not self._gossip_fn:
            return
        try:
            self._gossip_fn(payload)
        except Exception as exc:
            logger.warning("shard_migration gossip failed: %s", exc)

# Global instance for import
sharding_manager = ShardingManager()

if __name__ == "__main__":
    sharding = ShardingManager(num_shards=4)
    print("\nSharding Stats:")
    print(json.dumps(sharding.get_stats(), indent=2))
