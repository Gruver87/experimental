"""Plasma Chain — L2 sidechain with Merkle proofs and signed transactions."""

import json
import threading
import time
from typing import Dict, List, Optional, Tuple

from crypto import native
from crypto.signing import Signer
from features.l2_crypto import canonical_json, hash_state


class PlasmaBlock:
    def __init__(self, block_id: int, parent_hash: str, transactions: List[Dict],
                 created_at: int = None, block_hash: str = ""):
        self.block_id = block_id
        self.parent_hash = parent_hash
        self.transactions = transactions
        self.created_at = created_at if created_at is not None else int(time.time())
        self.block_hash = block_hash or self._calc_hash()
        self.transaction_count = len(transactions)
        self.total_amount = sum(tx.get("amount", 0) for tx in transactions)
        self.merkle_root = ""
        self.tx_hashes: List[str] = []

    def bind_merkle(self, tx_hashes: List[str]) -> None:
        self.tx_hashes = list(tx_hashes)
        if tx_hashes:
            self.merkle_root = native.merkle_root(tx_hashes)
        else:
            self.merkle_root = native.sha256_hex(b"")

    def _calc_hash(self) -> str:
        tx_data = json.dumps(self.transactions, sort_keys=True)
        raw = f"{self.block_id}{self.parent_hash}{tx_data}{self.created_at}"
        return native.sha256_hex(raw.encode())

    def to_dict(self) -> Dict:
        return {
            "block_id": self.block_id,
            "block_hash": self.block_hash[:16] + "...",
            "parent_hash": self.parent_hash[:16] + "...",
            "merkle_root": (self.merkle_root or "")[:16] + "...",
            "transaction_count": self.transaction_count,
            "total_amount": self.total_amount,
            "created_at": self.created_at,
        }

    def to_db(self) -> Dict:
        return {
            "block_id": self.block_id,
            "block_hash": self.block_hash,
            "parent_hash": self.parent_hash,
            "transactions": self.transactions,
            "total_amount": self.total_amount,
            "transaction_count": self.transaction_count,
            "created_at": self.created_at,
            "merkle_root": self.merkle_root,
            "tx_root": self.merkle_root,
        }


class PlasmaChain:
    """
    Plasma sidechain with L1 balance debit on deposit and credit on exit.
    State persisted in SQLite when db is provided.
    """

    CHALLENGE_PERIOD = 7 * 86400

    def __init__(self, chain_id: str = "plasma_main", root_chain=None, db=None):
        self.chain_id = chain_id
        self.root_chain = root_chain
        self.db = db
        self.blocks: List[PlasmaBlock] = []
        self.pending_txs: List[Dict] = []
        self.deposits: Dict[str, Dict] = {}
        self.exit_requests: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._load_from_db()
        if not self.blocks:
            genesis = PlasmaBlock(0, "0" * 64, [])
            self.blocks.append(genesis)
            self._persist_block(genesis)
        threading.Thread(target=self._exit_monitor_loop, daemon=True).start()
        print(f"[Plasma] Chain '{chain_id}' initialized "
              f"({len(self.blocks)} blocks, persisted={bool(db)})")

    def _l1_balance_sat(self, addr: str) -> int:
        from runtime.amount import to_satoshi

        if self.db and hasattr(self.db, "get_balance_satoshi"):
            return int(self.db.get_balance_satoshi(addr))
        if self.db and hasattr(self.db, "get_balance"):
            return int(to_satoshi(self.db.get_balance(addr)))
        if self.root_chain and hasattr(self.root_chain, "get_balance"):
            return int(to_satoshi(self.root_chain.get_balance(addr)))
        return 0

    def _l1_balance(self, addr: str) -> float:
        from runtime.amount import from_satoshi_float

        return float(from_satoshi_float(self._l1_balance_sat(addr)))

    def _debit_l1(self, addr: str, amount: float) -> bool:
        from runtime.amount import from_satoshi_float, to_satoshi, try_debit_satoshi

        try:
            need = int(to_satoshi(amount))
            try_debit_satoshi(self._l1_balance_sat(addr), amount)
        except (TypeError, ValueError):
            return False
        if need <= 0:
            return False
        if self.db and hasattr(self.db, "balance_delta_satoshi"):
            self.db.balance_delta_satoshi(addr, -need)
            return True
        if self.db and hasattr(self.db, "update_balance"):
            self.db.update_balance(addr, -from_satoshi_float(need))
            return True
        return False

    def _credit_l1(self, addr: str, amount: float) -> bool:
        from runtime.amount import from_satoshi_float, to_satoshi

        try:
            add = int(to_satoshi(amount))
        except (TypeError, ValueError):
            return False
        if add <= 0:
            return False
        if self.db and hasattr(self.db, "balance_delta_satoshi"):
            self.db.balance_delta_satoshi(addr, add)
            return True
        if self.db and hasattr(self.db, "update_balance"):
            self.db.update_balance(addr, from_satoshi_float(add))
            return True
        if self.root_chain and hasattr(self.root_chain, "update_balance"):
            self.root_chain.update_balance(addr, from_satoshi_float(add))
            return True
        return False

    def _load_from_db(self) -> None:
        if not self.db:
            return
        if hasattr(self.db, "get_plasma_deposits"):
            for dep in self.db.get_plasma_deposits(limit=500):
                self.deposits[dep["id"]] = dep
        if hasattr(self.db, "get_plasma_exits"):
            for ex in self.db.get_plasma_exits(limit=500):
                self.exit_requests[ex["id"]] = ex
        if hasattr(self.db, "get_plasma_blocks"):
            for row in self.db.get_plasma_blocks(limit=500):
                blk = PlasmaBlock(
                    block_id=row["block_id"],
                    parent_hash=row["parent_hash"],
                    transactions=row.get("transactions", []),
                    created_at=row.get("created_at"),
                    block_hash=row["block_hash"],
                )
                blk.merkle_root = row.get("merkle_root") or row.get("tx_root") or ""
                blk.tx_hashes = [
                    native.sha256_hex(canonical_json(tx).encode("utf-8"))
                    for tx in blk.transactions
                    if isinstance(tx, dict)
                ]
                if blk.tx_hashes and not blk.merkle_root:
                    blk.bind_merkle(blk.tx_hashes)
                self.blocks.append(blk)
            self.blocks.sort(key=lambda b: b.block_id)
        if hasattr(self.db, "get_meta"):
            pending = self.db.get_meta("plasma_pending_txs", [])
            if isinstance(pending, list):
                self.pending_txs = list(pending)

    def _persist_deposit(self, dep: Dict) -> None:
        if self.db and hasattr(self.db, "save_plasma_deposit"):
            self.db.save_plasma_deposit(dep)

    def _persist_exit(self, ex: Dict) -> None:
        if self.db and hasattr(self.db, "save_plasma_exit"):
            self.db.save_plasma_exit(ex)

    def _persist_block(self, block: PlasmaBlock) -> None:
        if self.db and hasattr(self.db, "save_plasma_block"):
            self.db.save_plasma_block(block.to_db())

    def _persist_pending(self) -> None:
        if self.db and hasattr(self.db, "set_meta"):
            self.db.set_meta("plasma_pending_txs", self.pending_txs[-200:])

    def _l2_balance(self, addr: str) -> float:
        balance = 0.0
        for dep in self.deposits.values():
            if dep.get("from") == addr and dep.get("status") == "confirmed":
                balance += float(dep.get("amount", 0) or 0)
        for block in self.blocks:
            for tx in block.transactions:
                if tx.get("type") == "deposit":
                    continue
                amount = float(tx.get("amount", 0) or 0)
                if tx.get("from") == addr:
                    balance -= amount
                if tx.get("to") == addr:
                    balance += amount
        for tx in self.pending_txs:
            if tx.get("type") == "deposit":
                continue
            amount = float(tx.get("amount", 0) or 0)
            if tx.get("from") == addr:
                balance -= amount
            if tx.get("to") == addr:
                balance += amount
        return balance

    def deposit(self, from_addr: str, amount: float,
                main_tx_hash: str = "") -> Optional[str]:
        if amount <= 0:
            return None
        if not self._debit_l1(from_addr, amount):
            return None
        deposit_id = native.sha256_hex(
            f"{from_addr}{amount}{main_tx_hash}{time.time()}".encode()
        )[:16]
        with self._lock:
            dep = {
                "id": deposit_id,
                "from": from_addr,
                "amount": amount,
                "main_tx_hash": main_tx_hash or deposit_id,
                "created_at": int(time.time()),
                "status": "confirmed",
            }
            self.deposits[deposit_id] = dep
            self.pending_txs.append({
                "type": "deposit",
                "from": from_addr,
                "to": from_addr,
                "amount": amount,
                "deposit_id": deposit_id,
                "timestamp": int(time.time()),
            })
            self._persist_deposit(dep)
            self._persist_pending()
        print(f"[Plasma] Deposit {deposit_id}: {amount} ABS from {from_addr[:12]}...")
        return deposit_id

    def _tx_hash(self, tx: Dict) -> str:
        return native.sha256_hex(canonical_json(tx).encode("utf-8"))

    def _verify_signed_tx(self, tx: Dict) -> bool:
        # Wave K: unsigned plasma txs must not admit (fail-closed).
        sig = tx.get("signature", "")
        pubkey = tx.get("public_key", "")
        if not sig or not pubkey:
            return False
        body = {k: v for k, v in tx.items() if k not in ("signature", "public_key")}
        try:
            return Signer._verify_hash(
                hash_state(body),
                bytes.fromhex(sig),
                bytes.fromhex(pubkey),
            )
        except (ValueError, TypeError):
            return False

    def submit_transaction(
        self,
        from_addr: str,
        to_addr: str,
        amount: float,
        signature: str = "",
        public_key: str = "",
        private_key: bytes = b"",
    ) -> Optional[str]:
        if amount <= 0 or not from_addr or not to_addr:
            return None
        with self._lock:
            if self._l2_balance(from_addr) < amount:
                return None
            tx = {
                "hash": "",
                "from": from_addr,
                "to": to_addr,
                "amount": amount,
                "timestamp": int(time.time()),
            }
            if private_key and public_key:
                body = {
                    k: v for k, v in tx.items() if k not in ("signature", "public_key")
                }
                try:
                    tx["signature"] = Signer._sign_hash(hash_state(body), private_key)
                    tx["public_key"] = public_key
                except (ValueError, TypeError):
                    return None
            elif signature and public_key:
                tx["signature"] = signature
                tx["public_key"] = public_key
            if not self._verify_signed_tx(tx):
                return None
            tx["hash"] = self._tx_hash(tx)[:16]
            self.pending_txs.append(tx)
            self._persist_pending()
            return tx["hash"]

    def submit_block(self, proposer: str = "operator") -> Optional[Dict]:
        with self._lock:
            if not self.pending_txs:
                return None
            parent_hash = self.blocks[-1].block_hash if self.blocks else "0" * 64
            txs = list(self.pending_txs)
            tx_hashes = [self._tx_hash(tx) for tx in txs]
            new_block = PlasmaBlock(len(self.blocks), parent_hash, txs)
            new_block.bind_merkle(tx_hashes)
            self.blocks.append(new_block)
            self.pending_txs.clear()
            self._persist_block(new_block)
            self._persist_pending()
            if self.db and hasattr(self.db, "set_meta"):
                self.db.set_meta(
                    f"plasma_l1_root_{new_block.block_id}",
                    {"merkle_root": new_block.merkle_root, "block_hash": new_block.block_hash},
                )
        print(
            f"[Plasma] Block #{new_block.block_id} by {proposer[:12]}... "
            f"txs={new_block.transaction_count} root={new_block.merkle_root[:16]}..."
        )
        return new_block.to_dict()

    def merkle_proof(self, block_id: int, tx_hash: str) -> Optional[Dict]:
        with self._lock:
            block = next((b for b in self.blocks if b.block_id == block_id), None)
            if not block or not block.tx_hashes:
                return None
            try:
                idx = block.tx_hashes.index(tx_hash)
            except ValueError:
                return None
            proof = native.generate_proof(block.tx_hashes, idx)
            return {
                "block_id": block_id,
                "tx_hash": tx_hash,
                "index": idx,
                "merkle_root": block.merkle_root,
                "proof": proof,
            }

    def verify_inclusion(self, block_id: int, tx_hash: str, proof: List[str]) -> bool:
        with self._lock:
            block = next((b for b in self.blocks if b.block_id == block_id), None)
            if not block or not block.merkle_root:
                return False
            try:
                idx = block.tx_hashes.index(tx_hash)
            except ValueError:
                return False
            return native.verify_proof(tx_hash, proof, block.merkle_root, idx)

    def request_exit(self, deposit_id: str, user: str) -> Optional[str]:
        with self._lock:
            dep = self.deposits.get(deposit_id)
            if not dep or dep["status"] != "confirmed" or dep["from"] != user:
                return None
            if self._l2_balance(user) < float(dep.get("amount", 0) or 0):
                return None
            exit_id = native.sha256_hex(
                f"{deposit_id}{user}{time.time()}".encode()
            )[:16]
            ex = {
                "id": exit_id,
                "deposit_id": deposit_id,
                "user": user,
                "amount": dep["amount"],
                "created_at": int(time.time()),
                "status": "pending",
            }
            self.exit_requests[exit_id] = ex
            dep["status"] = "exiting"
            self._persist_exit(ex)
            self._persist_deposit(dep)
        return exit_id

    def finalize_exit(self, exit_id: str, force: bool = False) -> bool:
        with self._lock:
            req = self.exit_requests.get(exit_id)
            if not req or req["status"] != "pending":
                return False
            if not force and time.time() - req["created_at"] < self.CHALLENGE_PERIOD:
                return False
            if not self._credit_l1(req["user"], req["amount"]):
                return False
            req["status"] = "finalized"
            dep = self.deposits.get(req["deposit_id"])
            if dep:
                dep["status"] = "exited"
                self._persist_deposit(dep)
            self._persist_exit(req)
        print(f"[Plasma] Exit finalized: {exit_id} {req['amount']} ABS → {req['user'][:12]}...")
        return True

    def get_blocks(self, limit: int = 20) -> List[Dict]:
        with self._lock:
            return [b.to_dict() for b in self.blocks[-limit:]]

    def get_deposits(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            deps = sorted(self.deposits.values(), key=lambda d: d["created_at"], reverse=True)
            return deps[:limit]

    def get_stats(self) -> Dict:
        with self._lock:
            total_deposited = sum(d["amount"] for d in self.deposits.values())
            total_withdrawn = sum(
                e["amount"] for e in self.exit_requests.values()
                if e["status"] == "finalized"
            )
            return {
                "chain_id": self.chain_id,
                "blocks": len(self.blocks),
                "pending_transactions": len(self.pending_txs),
                "total_deposits": len(self.deposits),
                "total_exits": len(self.exit_requests),
                "total_deposited": total_deposited,
                "total_withdrawn": total_withdrawn,
                "tvl": total_deposited - total_withdrawn,
                "persisted": bool(self.db),
                "challenge_period_sec": self.CHALLENGE_PERIOD,
                "merkle_proofs": True,
                "signed_txs": True,
            }

    def _exit_monitor_loop(self):
        while True:
            time.sleep(3600)
            with self._lock:
                pending = [eid for eid, e in self.exit_requests.items()
                           if e["status"] == "pending"]
            for eid in pending:
                self.finalize_exit(eid)
