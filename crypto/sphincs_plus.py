# crypto/sphincs_plus.py - SPHINCS+ interface (fail-closed until real backend)
"""SPHINCS+ surface — refuse all crypto ops until a real backend is wired."""

from __future__ import annotations

import base64


class SPHINCSPLUS:
    """
    SPHINCS+ - Stateless Hash-Based Signature Scheme

    This class intentionally fails closed until a real SPHINCS+ backend is
    wired in. The previous HMAC/length-check implementation was not SPHINCS+.
    """

    def __init__(self, param_set: str = "SHA2_256f"):
        self.param_set = param_set

    def generate_keypair(self) -> tuple[bytes, bytes]:
        raise NotImplementedError("SPHINCS+ key generation backend not available")

    def sign(self, message: bytes, private_key: bytes) -> bytes:
        raise NotImplementedError("SPHINCS+ signing backend not available")

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        # Wave H: never return False as a fake verifier — refuse like sign/keygen.
        raise NotImplementedError("SPHINCS+ verify backend not available")

    @staticmethod
    def quantum_address_from_pubkey(public_key: bytes) -> str:
        raise NotImplementedError("SPHINCS+ address derivation backend not available")


class QuantumWallet:
    """Post-quantum wallet using SPHINCS+ (unavailable until backend lands)."""

    def __init__(self):
        self.sphincs = SPHINCSPLUS()
        self.private_key = None
        self.public_key = None
        self.address = None
        self.balance = 0

    def create(self) -> "QuantumWallet":
        self.private_key, self.public_key = self.sphincs.generate_keypair()
        self.address = SPHINCSPLUS.quantum_address_from_pubkey(self.public_key)
        return self

    def sign_transaction(self, tx_data: bytes) -> bytes:
        if not self.private_key:
            raise RuntimeError("wallet not created")
        return self.sphincs.sign(tx_data, self.private_key)

    def verify_transaction(self, tx_data: bytes, signature: bytes, address: str) -> bool:
        if not self.public_key:
            raise RuntimeError("wallet not created")
        return self.sphincs.verify(tx_data, signature, self.public_key)

    def export_private_key(self) -> str:
        if not self.private_key:
            raise RuntimeError("wallet not created")
        return base64.b64encode(self.private_key).decode()

    def import_private_key(self, key_str: str) -> None:
        raise NotImplementedError(
            "SPHINCS+ import_private_key refused until real backend is wired"
        )

    def get_info(self) -> dict:
        return {
            "address": self.address,
            "balance": self.balance,
            "algorithm": "SPHINCS+ (unavailable)",
            "param_set": self.sphincs.param_set,
        }
