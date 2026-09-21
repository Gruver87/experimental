import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from features.postquantum import (
    HybridCrypto,
    PQAlgorithm,
    PQKeyPair,
    PQSignature,
    PostQuantumManager,
    SecurityLevel,
)


def test_unsupported_signature_keygen_fails_closed_without_backend():
    pqm = PostQuantumManager()

    for algorithm in (PQAlgorithm.SPHINCS_PLUS, PQAlgorithm.FALCON):
        with pytest.raises(NotImplementedError):
            pqm.generate_keypair(algorithm)


def test_unsupported_signature_signing_fails_closed_without_backend():
    pqm = PostQuantumManager()

    for algorithm in (PQAlgorithm.SPHINCS_PLUS, PQAlgorithm.FALCON):
        keypair = PQKeyPair(
            algorithm=algorithm,
            security_level=SecurityLevel.LEVEL5,
            public_key=b"public",
            private_key=b"private",
        )
        with pytest.raises(NotImplementedError):
            pqm.sign(b"absolute-chain", keypair)


def test_sphincs_and_falcon_verify_fail_closed_without_backend():
    pqm = PostQuantumManager()
    message = b"absolute-chain"

    for algorithm in (PQAlgorithm.SPHINCS_PLUS, PQAlgorithm.FALCON):
        signature = PQSignature(
            id="fake",
            algorithm=algorithm,
            signature=b"a" * 64,
            public_key_hash="fake",
            message_hash="fake",
        )
        with pytest.raises(NotImplementedError):
            pqm.verify(signature, message, b"public")


def test_kyber_kem_fails_closed_without_backend():
    pqm = PostQuantumManager()
    keypair = PQKeyPair(
        algorithm=PQAlgorithm.KYBER,
        security_level=SecurityLevel.LEVEL5,
        public_key=b"public",
        private_key=b"private",
    )

    with pytest.raises(NotImplementedError):
        pqm.generate_keypair(PQAlgorithm.KYBER)
    with pytest.raises(NotImplementedError):
        pqm.encapsulate(PQAlgorithm.KYBER, keypair.public_key)
    with pytest.raises(NotImplementedError):
        pqm.decapsulate(b"ciphertext", keypair)


def test_hybrid_crypto_fails_closed_without_backend():
    hybrid = HybridCrypto(PostQuantumManager())
    keypair = PQKeyPair(
        algorithm=PQAlgorithm.DILITHIUM,
        security_level=SecurityLevel.LEVEL5,
        public_key=b"public",
        private_key=b"private",
    )

    with pytest.raises(NotImplementedError):
        hybrid.hybrid_sign(b"message", keypair, "ecdsa")
    with pytest.raises(NotImplementedError):
        hybrid.hybrid_encrypt(b"message", b"public", "ecdsa-public")
    with pytest.raises(NotImplementedError):
        hybrid.hybrid_decrypt({}, keypair)


def test_dilithium_commitment_path_still_verifies_and_rejects_tamper():
    """Educational hash-demo removed — Dilithium must fail-closed without NIST ML-DSA."""
    pqm = PostQuantumManager()
    with pytest.raises(NotImplementedError):
        pqm.generate_keypair(PQAlgorithm.DILITHIUM)
