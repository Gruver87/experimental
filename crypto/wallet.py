# crypto/wallet.py (COMPLETE REWRITE - NO INDENTATION ERRORS)
"""
Full crypto wallet with ECDSA signing for transactions
"""

import json
import hashlib
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from crypto.secp256k1_backend import (
    CRYPTO_AVAILABLE as ECDSA_AVAILABLE,
    generate_keypair as _generate_secp_keypair,
    sign,
    verify,
    verify_batch_sha256,
)
from crypto.keys import KeyGenerator
from crypto import native


@dataclass
class KeyPair:
    private_key: bytes
    public_key: bytes
    address: str


class Wallet:
    """Cryptocurrency wallet with ECDSA signing"""
    
    def __init__(self, keypair: KeyPair = None):
        self.keypair = keypair or self._generate_keypair()
    
    def _generate_keypair(self) -> KeyPair:
        """Generate new secp256k1 keypair"""
        if not ECDSA_AVAILABLE:
            raise RuntimeError("SECP256K1 backend not available")
        private_key, public_key = _generate_secp_keypair()
        
        address = self._derive_address(public_key)
        
        return KeyPair(
            private_key=private_key,
            public_key=public_key,
            address=address
        )
    
    def _derive_address(self, public_key: bytes) -> str:
        """Derive chain address from public key (delegates to KeyGenerator)."""
        from crypto.keys import KeyGenerator

        return KeyGenerator.derive_address(public_key)
    
    @property
    def address(self) -> str:
        return self.keypair.address
    
    @property
    def public_key(self) -> str:
        return self.keypair.public_key.hex()
    
    @property
    def private_key(self) -> str:
        return self.keypair.private_key.hex()
    
    def sign_transaction(
        self,
        to: str,
        value: int,
        nonce: int,
        chain_id: int = 1,
        data: str = "",
        gas_limit: int = 21000,
    ) -> dict:
        """Create and sign a transaction (optional calldata + gas for EVM deploy/call)."""
        tx = {
            "from": self.address,
            "to": to,
            "value": value,
            "nonce": nonce,
            "chain_id": chain_id,
            "gas_limit": int(gas_limit),
            "data": data or "",
        }

        tx_hash = self._hash_transaction(tx)
        signature = self._sign_hash(tx_hash)

        tx["signature"] = signature
        tx["public_key"] = self.public_key
        tx["hash"] = tx_hash

        return tx

    @staticmethod
    def _canonical_tx_for_hash(tx: dict) -> dict:
        """Canonical signing payload; includes data/gas only when non-default."""
        payload = {
            "from": tx["from"],
            "to": tx["to"],
            "value": tx["value"],
            "nonce": tx["nonce"],
            "chain_id": tx.get("chain_id", 1),
        }
        data = tx.get("data", "") or ""
        if data:
            payload["data"] = data
        gas_limit = tx.get("gas_limit") or tx.get("gas")
        if gas_limit is not None and int(gas_limit) != 21000:
            payload["gas_limit"] = int(gas_limit)
        return payload

    def _hash_transaction(self, tx: dict) -> str:
        """Create canonical hash of transaction for signing."""
        encoded = json.dumps(
            self._canonical_tx_for_hash(tx),
            sort_keys=True,
            separators=(",", ":"),
        )
        return native.hash_sorted_json(encoded)

    def _sign_hash(self, data_hash: str) -> str:
        """Sign a hash with private key"""
        if not ECDSA_AVAILABLE:
            raise RuntimeError("SECP256K1 backend not available")
        
        signature = sign(data_hash.encode(), self.keypair.private_key, hashfunc=hashlib.sha256)
        return signature.hex()
    
    def sign_block(self, block: dict) -> str:
        """Sign a block as proposer"""
        block_hash = self._hash_block(block)
        return self._sign_hash(block_hash)
    
    def _hash_block(self, block: dict) -> str:
        block_for_hash = {
            "number": block.get("number"),
            "parent_hash": block.get("parent_hash"),
            "timestamp": block.get("timestamp"),
            "proposer": block.get("proposer")
        }
        # Legacy contract: default json.dumps separators (spaces), sort_keys=True.
        encoded = json.dumps(block_for_hash, sort_keys=True)
        return native.sha256_hex(encoded.encode())
    
    def sign_attestation(self, attestation: dict) -> str:
        """Sign an attestation as validator"""
        att_hash = self._hash_attestation(attestation)
        return self._sign_hash(att_hash)
    
    def _hash_attestation(self, attestation: dict) -> str:
        """Hash attestation for signing"""
        att_for_hash = {
            "validator": attestation.get("validator"),
            "target_hash": attestation.get("target_hash"),
            "target_height": attestation.get("target_height"),
            "slot": attestation.get("slot")
        }
        encoded = json.dumps(att_for_hash, sort_keys=True, separators=(',', ':'))
        return native.hash_sorted_json(encoded)
    
    def export(self, filepath: str, password: str = None):
        """Export wallet to file"""
        data = {
            "address": self.address,
            "public_key": self.public_key,
            "private_key": self.private_key
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def import_wallet(cls, filepath: str, password: str = None) -> "Wallet":
        """Import wallet from file"""
        with open(filepath, "r") as f:
            data = json.load(f)
        
        private_key = bytes.fromhex(data["private_key"])
        public_key = bytes.fromhex(data["public_key"])
        keypair = KeyPair(
            private_key=private_key,
            public_key=public_key,
            address=data["address"]
        )
        return cls(keypair)
    
    @classmethod
    def create_new(cls) -> "Wallet":
        return cls()
    
    @classmethod
    def from_private_key(cls, private_key_hex: str) -> "Wallet":
        private_key = bytes.fromhex(private_key_hex)
        public_key = KeyGenerator.private_to_public(private_key)
        address = KeyGenerator.derive_address(public_key)
        keypair = KeyPair(
            private_key=private_key,
            public_key=public_key,
            address=address
        )
        return cls(keypair)
    
    @classmethod
    def _derive_address(cls, public_key: bytes) -> str:
        return "0x" + native.sha256_hex(public_key)[-40:]


# ========== SIGNATURE VERIFICATION ==========

def verify_transaction_signature(tx: dict) -> bool:
    """Verify transaction signature.

    Wave Q: missing ECDSA backend is unavailable (RuntimeError), not invalid False.
    """
    material = _transaction_signature_material(tx)
    if material is None:
        return False
    if not ECDSA_AVAILABLE:
        raise RuntimeError("signature verify unavailable: ECDSA backend missing")
    message, signature, public_key = material
    return verify(message, signature, public_key, hashfunc=hashlib.sha256)


def verify_transaction_signatures_batch(txs: List[dict]) -> List[bool]:
    """Batch verify canonical transaction signatures."""
    if not ECDSA_AVAILABLE:
        raise RuntimeError("signature verify unavailable: ECDSA backend missing")

    batch: List[Tuple[bytes, bytes, bytes]] = []
    positions: List[int] = []
    results = [False for _ in txs]

    for idx, tx in enumerate(txs):
        material = _transaction_signature_material(tx)
        if material is None:
            continue
        batch.append(material)
        positions.append(idx)

    if not batch:
        return results

    verified = verify_batch_sha256(batch)
    for idx, ok in zip(positions, verified):
        results[idx] = bool(ok)

    return results


def _transaction_signature_material(tx: dict) -> Optional[Tuple[bytes, bytes, bytes]]:
    if "signature" not in tx or "public_key" not in tx:
        return None

    tx_to_verify = Wallet._canonical_tx_for_hash({
        "from": tx["from"],
        "to": tx["to"],
        "value": tx["value"],
        "nonce": tx["nonce"],
        "chain_id": tx.get("chain_id", 1),
        "data": tx.get("data", ""),
        "gas_limit": tx.get("gas_limit") or tx.get("gas"),
    })

    tx_hash_hashed = native.hash_sorted_json(
        json.dumps(tx_to_verify, sort_keys=True, separators=(",", ":"))
    )

    try:
        signature = bytes.fromhex(tx["signature"])
        public_key = bytes.fromhex(tx["public_key"])
    except (TypeError, ValueError):
        return None

    return tx_hash_hashed.encode(), signature, public_key


def create_test_wallet() -> Wallet:
    return Wallet.create_new()
