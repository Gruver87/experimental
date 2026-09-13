# crypto/validator_keys.py
"""
Validator key management for staking
"""

from typing import Optional
from crypto.wallet import Wallet


class ValidatorKeys:
    """Manages validator cryptographic identities"""
    
    def __init__(self):
        self.wallet: Optional[Wallet] = None
        self.validator_id: Optional[str] = None
        self.stake: int = 0
    
    def initialize(self, wallet: Wallet = None) -> "ValidatorKeys":
        """Initialize validator with wallet"""
        self.wallet = wallet or Wallet.create_new()
        self.validator_id = self.wallet.address
        return self
    
    def get_validator_id(self) -> str:
        return self.validator_id
    
    def sign_block(self, block: dict) -> str:
        """Sign a block as block proposer"""
        if not self.wallet:
            raise Exception("Validator not initialized")
        return self.wallet.sign_block(block)
    
    def sign_attestation(self, target_block: dict, slot: int) -> dict:
        """Create and sign an attestation (vote)"""
        if not self.wallet:
            raise Exception("Validator not initialized")
        
        attestation = {
            "validator": self.validator_id,
            "target_hash": target_block.get("hash"),
            "target_height": target_block.get("number"),
            "slot": slot
        }
        
        signature = self.wallet.sign_attestation(attestation)
        attestation["signature"] = signature
        attestation["public_key"] = self.wallet.public_key
        
        return attestation
    
    def verify_attestation(self, attestation: dict) -> bool:
        """Verify attestation signature and bind pubkey → claimed validator (v1.3.65)."""
        if "signature" not in attestation or "public_key" not in attestation:
            return False

        claimed = str(attestation.get("validator") or "").strip().lower()
        if not claimed:
            return False

        try:
            signature = bytes.fromhex(attestation["signature"])
            public_key = bytes.fromhex(attestation["public_key"])
        except (TypeError, ValueError):
            return False

        from crypto.keys import KeyGenerator
        from crypto import native

        try:
            derived = KeyGenerator.derive_address(public_key).strip().lower()
        except Exception as exc:
            # Wave Q: key derive failure is unavailable, not attestation invalid.
            raise RuntimeError(f"attestation verify unavailable: {exc}") from exc
        if derived != claimed:
            return False

        try:
            return bool(native.verify_attestation_secp256k1(attestation, signature, public_key))
        except Exception as exc:
            raise RuntimeError(f"attestation verify unavailable: {exc}") from exc
    
    def get_public_key(self) -> str:
        return self.wallet.public_key if self.wallet else ""
    
    def get_address(self) -> str:
        return self.wallet.address if self.wallet else ""
    
    def to_dict(self) -> dict:
        return {
            "validator_id": self.validator_id,
            "address": self.get_address(),
            "public_key": self.get_public_key(),
            "stake": self.stake
        }
