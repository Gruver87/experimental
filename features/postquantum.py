#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔐 ЧАСТЬ 28: POST-QUANTUM CRYPTO - ЯДРО
🔐 WATERMARK: DABRANSKI ULADZIMIR PETROVICH | 14.07.1987 | GRODNO

Квантово-устойчивые криптографические алгоритмы (EDUCATIONAL / R&D ONLY).

SPHINCS+/Kyber/Falcon/Dilithium raise NotImplementedError in this repo.
Do not use for production wallets or consensus; feature_pq is blocked in prod.
"""

import hashlib
from crypto import native
import time
import json
import secrets
import math
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

# ============================================================================
# ТИПЫ АЛГОРИТМОВ
# ============================================================================

class PQAlgorithm(Enum):
    """Типы пост-квантовых алгоритмов"""
    SPHINCS_PLUS = "sphincs_plus"      # Хеш-подписи (статические)
    KYBER = "kyber"                     # KEM на основе решёток
    DILITHIUM = "dilithium"             # Цифровые подписи на решётках
    FALCON = "falcon"                   # Компактные подписи на решётках
    CLASSIC_MCELIECE = "classic_mceliece" # Коды Гоппы


class SecurityLevel(Enum):
    """Уровни безопасности (NIST)"""
    LEVEL1 = 1   # 128 бит (AES-128)
    LEVEL3 = 3   # 192 бита (AES-192)
    LEVEL5 = 5   # 256 бит (AES-256)


# ============================================================================
# ДАТАКЛАССЫ
# ============================================================================

@dataclass
class PQKeyPair:
    """Пост-квантовая ключевая пара"""
    
    algorithm: PQAlgorithm
    security_level: SecurityLevel
    public_key: bytes
    private_key: bytes
    created_at: float = field(default_factory=time.time)
    key_id: str = ""
    
    def __post_init__(self):
        if not self.key_id:
            self.key_id = native.sha256_hex(
                f"{self.algorithm.value}{time.time()}{secrets.token_hex(8)}".encode()
            )[:16]
    
    def to_dict(self) -> Dict:
        return {
            'id': self.key_id[:8],
            'algorithm': self.algorithm.value,
            'security': f"NIST{self.security_level.value}",
            'public_key_size': len(self.public_key),
            'private_key_size': len(self.private_key),
            'created': self.created_at
        }


@dataclass
class PQSignature:
    """Пост-квантовая подпись"""
    
    id: str
    algorithm: PQAlgorithm
    signature: bytes
    public_key_hash: str
    message_hash: str
    timestamp: float = field(default_factory=time.time)
    verified: bool = False
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id[:8],
            'algorithm': self.algorithm.value,
            'size': len(self.signature),
            'verified': self.verified
        }


@dataclass
class SharedSecret:
    """Общий секрет (для KEM)"""
    
    id: str
    algorithm: PQAlgorithm
    ciphertext: bytes
    shared_secret: bytes
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id[:8],
            'algorithm': self.algorithm.value,
            'ciphertext_size': len(self.ciphertext),
            'secret_size': len(self.shared_secret)
        }


# ============================================================================
# SPHINCS+ (ХЕШ-ПОДПИСИ)
# ============================================================================

class SPHINCSPlus:
    """
    SPHINCS+ - статическая хеш-подпись
    Безопасна против квантовых компьютеров
    """
    
    def __init__(self, security_level: SecurityLevel = SecurityLevel.LEVEL5):
        self.security_level = security_level
        
        # Параметры в зависимости от уровня безопасности
        self.params = {
            SecurityLevel.LEVEL1: {
                'n': 16,  # байт
                'h': 64,  # высота дерева
                'd': 8,   # слои
                'k': 14,  # виног
                'w': 16,  # Winternitz
                'key_size': 32,
                'sig_size': 8080
            },
            SecurityLevel.LEVEL3: {
                'n': 24,
                'h': 64,
                'd': 8,
                'k': 22,
                'w': 16,
                'key_size': 48,
                'sig_size': 17000
            },
            SecurityLevel.LEVEL5: {
                'n': 32,
                'h': 64,
                'd': 8,
                'k': 30,
                'w': 16,
                'key_size': 64,
                'sig_size': 30000
            }
        }
        
    def generate_keypair(self) -> PQKeyPair:
        """Генерация ключевой пары"""
        raise NotImplementedError("SPHINCS+ key generation backend not available")
    
    def sign(self, message: bytes, keypair: PQKeyPair) -> PQSignature:
        """Подписание сообщения"""
        raise NotImplementedError("SPHINCS+ signing backend not available")
    
    def verify(self, signature: PQSignature, message: bytes, public_key: bytes) -> bool:
        """Проверка подписи — fail-closed until a real SPHINCS+ backend is wired."""
        raise NotImplementedError("SPHINCS+ verify backend not available")


# ============================================================================
# KYBER (KEM - KEY ENCAPSULATION MECHANISM)
# ============================================================================

class Kyber:
    """
    Kyber - KEM на основе решёток (ML-KEM)
    Для обмена ключами
    """
    
    def __init__(self, security_level: SecurityLevel = SecurityLevel.LEVEL5):
        self.security_level = security_level
        
        self.params = {
            SecurityLevel.LEVEL1: {
                'k': 2,   # ранг матрицы
                'eta1': 3,
                'eta2': 2,
                'du': 10,
                'dv': 4,
                'key_size': 800,
                'ct_size': 768
            },
            SecurityLevel.LEVEL3: {
                'k': 3,
                'eta1': 2,
                'eta2': 2,
                'du': 10,
                'dv': 4,
                'key_size': 1184,
                'ct_size': 1088
            },
            SecurityLevel.LEVEL5: {
                'k': 4,
                'eta1': 2,
                'eta2': 2,
                'du': 11,
                'dv': 5,
                'key_size': 1568,
                'ct_size': 1568
            }
        }
        
    def generate_keypair(self) -> PQKeyPair:
        """Генерация ключевой пары для KEM"""
        raise NotImplementedError("Kyber key generation backend not available")
    
    def encapsulate(self, public_key: bytes) -> SharedSecret:
        """Создание общего секрета (для отправителя)"""
        raise NotImplementedError("Kyber KEM encapsulation backend not available")
    
    def decapsulate(self, ciphertext: bytes, keypair: PQKeyPair) -> Optional[SharedSecret]:
        """Извлечение общего секрета (для получателя)"""
        raise NotImplementedError("Kyber KEM decapsulation backend not available")


# ============================================================================
# DILITHIUM (ПОДПИСИ НА РЕШЁТКАХ)
# ============================================================================

class Dilithium:
    """
    Dilithium - цифровые подписи на решётках (ML-DSA)
    NIST стандарт для пост-квантовых подписей
    """
    
    def __init__(self, security_level: SecurityLevel = SecurityLevel.LEVEL5):
        self.security_level = security_level
        
        self.params = {
            SecurityLevel.LEVEL1: {
                'k': 4,
                'l': 4,
                'eta': 2,
                'tau': 39,
                'gamma1': 131072,
                'gamma2': 95232,
                'key_size': 1312,
                'sig_size': 2420
            },
            SecurityLevel.LEVEL3: {
                'k': 6,
                'l': 5,
                'eta': 4,
                'tau': 49,
                'gamma1': 131072,
                'gamma2': 261888,
                'key_size': 1952,
                'sig_size': 3293
            },
            SecurityLevel.LEVEL5: {
                'k': 8,
                'l': 7,
                'eta': 2,
                'tau': 60,
                'gamma1': 131072,
                'gamma2': 261888,
                'key_size': 2592,
                'sig_size': 4595
            }
        }
        
    def generate_keypair(self) -> PQKeyPair:
        """Генерация ключевой пары — refuse educational hash-demo (Wave I)."""
        raise NotImplementedError(
            "Dilithium key generation backend not available "
            "(educational hash-demo removed; no NIST ML-DSA)"
        )
    
    def sign(self, message: bytes, keypair: PQKeyPair) -> PQSignature:
        """Подписание — refuse educational hash-demo (Wave I)."""
        raise NotImplementedError(
            "Dilithium signing backend not available "
            "(educational hash-demo removed; no NIST ML-DSA)"
        )
    
    def verify(self, signature: PQSignature, message: bytes, public_key: bytes) -> bool:
        """Проверка — refuse educational hash-demo that painted valid:true (Wave I)."""
        raise NotImplementedError(
            "Dilithium verify backend not available "
            "(educational hash-demo removed; no NIST ML-DSA)"
        )


# ============================================================================
# FALCON (КОМПАКТНЫЕ ПОДПИСИ)
# ============================================================================

class Falcon:
    """
    FALCON - компактные пост-квантовые подписи
    Основаны на решётках NTRU
    """
    
    def __init__(self, security_level: SecurityLevel = SecurityLevel.LEVEL5):
        self.security_level = security_level
        
        self.params = {
            SecurityLevel.LEVEL1: {
                'n': 512,
                'key_size': 897,
                'sig_size': 666,
                'logn': 9
            },
            SecurityLevel.LEVEL3: {
                'n': 768,
                'key_size': 1233,
                'sig_size': 986,
                'logn': 10
            },
            SecurityLevel.LEVEL5: {
                'n': 1024,
                'key_size': 1569,
                'sig_size': 1280,
                'logn': 10
            }
        }
        
    def generate_keypair(self) -> PQKeyPair:
        """Генерация ключевой пары"""
        raise NotImplementedError("Falcon key generation backend not available")
    
    def sign(self, message: bytes, keypair: PQKeyPair) -> PQSignature:
        """Подписание сообщения (Fast Fourier sampling)"""
        raise NotImplementedError("Falcon signing backend not available")
    
    def verify(self, signature: PQSignature, message: bytes, public_key: bytes) -> bool:
        """Проверка подписи — fail-closed until a real Falcon backend is wired."""
        raise NotImplementedError("Falcon verify backend not available")


# ============================================================================
# МЕНЕДЖЕР ПОСТ-КВАНТОВОЙ КРИПТОГРАФИИ
# ============================================================================

class PostQuantumManager:
    """
    Менеджер пост-квантовой криптографии
    Объединяет все алгоритмы
    """
    
    def __init__(self):
        self.algorithms = {
            PQAlgorithm.SPHINCS_PLUS: SPHINCSPlus(),
            PQAlgorithm.KYBER: Kyber(),
            PQAlgorithm.DILITHIUM: Dilithium(),
            PQAlgorithm.FALCON: Falcon()
        }
        self.keypairs: Dict[str, PQKeyPair] = {}
        self.signatures: Dict[str, PQSignature] = {}
        self.secrets: Dict[str, SharedSecret] = {}
        
    def generate_keypair(
        self,
        algorithm: PQAlgorithm,
        security_level: SecurityLevel = SecurityLevel.LEVEL5
    ) -> PQKeyPair:
        """Генерация ключевой пары"""
        
        algo = self.algorithms.get(algorithm)
        if not algo:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        
        keypair = algo.generate_keypair()
        self.keypairs[keypair.key_id] = keypair
        
        return keypair
    
    def sign(
        self,
        message: bytes,
        keypair: PQKeyPair,
        algorithm: Optional[PQAlgorithm] = None
    ) -> PQSignature:
        """Подписание сообщения"""
        
        if algorithm is None:
            algorithm = keypair.algorithm
        
        algo = self.algorithms.get(algorithm)
        if not algo:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        
        signature = algo.sign(message, keypair)
        self.signatures[signature.id] = signature
        
        return signature
    
    def verify(
        self,
        signature: PQSignature,
        message: bytes,
        public_key: bytes
    ) -> bool:
        """Проверка подписи"""
        
        algo = self.algorithms.get(signature.algorithm)
        if not algo:
            return False
        
        return algo.verify(signature, message, public_key)
    
    def encapsulate(self, algorithm: PQAlgorithm, public_key: bytes) -> SharedSecret:
        """Создание общего секрета"""
        
        algo = self.algorithms.get(algorithm)
        if not algo:
            raise ValueError(f"Unsupported algorithm for KEM: {algorithm}")
        
        if not hasattr(algo, 'encapsulate'):
            raise ValueError(f"{algorithm} does not support KEM")
        
        secret = algo.encapsulate(public_key)
        self.secrets[secret.id] = secret
        
        return secret
    
    def decapsulate(
        self,
        ciphertext: bytes,
        keypair: PQKeyPair
    ) -> Optional[SharedSecret]:
        """Извлечение общего секрета"""
        
        algo = self.algorithms.get(keypair.algorithm)
        if not algo or not hasattr(algo, 'decapsulate'):
            return None
        
        secret = algo.decapsulate(ciphertext, keypair)
        if secret:
            self.secrets[secret.id] = secret
        
        return secret
    
    def get_keypair(self, key_id: str) -> Optional[PQKeyPair]:
        """Получение ключевой пары по ID"""
        return self.keypairs.get(key_id)
    
    def get_signature(self, sig_id: str) -> Optional[PQSignature]:
        """Получение подписи по ID"""
        return self.signatures.get(sig_id)
    
    def get_stats(self) -> Dict:
        """Статистика пост-квантовой криптографии + honesty capability matrix."""
        return {
            'keypairs': len(self.keypairs),
            'signatures': len(self.signatures),
            'secrets': len(self.secrets),
            'by_algorithm': {
                algo.value: len([k for k in self.keypairs.values() if k.algorithm == algo])
                for algo in PQAlgorithm
            },
            'production_ready': False,
            'educational_only': True,
            'capabilities': {
                'dilithium': {
                    'callable': False,
                    'backend': None,
                    'nist_ml_dsa': False,
                    'reason': 'NotImplementedError',
                },
                'kyber': {
                    'callable': False,
                    'backend': None,
                    'reason': 'NotImplementedError',
                },
                'falcon': {
                    'callable': False,
                    'backend': None,
                    'reason': 'NotImplementedError',
                },
                'sphincs_plus': {
                    'callable': False,
                    'backend': None,
                    'reason': 'NotImplementedError',
                },
            },
        }

    def _parse_algorithm(self, name: str) -> PQAlgorithm:
        raw = (name or "dilithium").strip().lower().replace("-", "_")
        for algo in PQAlgorithm:
            if algo.value == raw or algo.name.lower() == raw:
                return algo
        raise ValueError(f"Unsupported algorithm: {name}")

    def sign_text(
        self,
        message: str,
        algorithm: str = "dilithium",
        key_id: Optional[str] = None,
    ) -> Dict:
        """API-friendly sign: returns signature payload + public key hex."""
        algo = self._parse_algorithm(algorithm)
        keypair = self.keypairs.get(key_id) if key_id else None
        if not keypair:
            keypair = self.generate_keypair(algo)
        msg_bytes = message.encode("utf-8")
        sig = self.sign(msg_bytes, keypair, algo)
        return {
            "algorithm": algo.value,
            "key_id": keypair.key_id,
            "public_key": keypair.public_key.hex(),
            "signature": sig.signature.hex(),
            "signature_id": sig.id,
            "message_hash": sig.message_hash,
        }

    def verify_text(
        self,
        message: str,
        signature_payload,
        algorithm: str = "dilithium",
        public_key_hex: str = "",
    ) -> bool:
        """API-friendly verify from REST /pq/verify."""
        algo = self._parse_algorithm(algorithm)
        msg_bytes = message.encode("utf-8")
        if isinstance(signature_payload, dict):
            sig_hex = signature_payload.get("signature", "")
            pub_hex = public_key_hex or signature_payload.get("public_key", "")
            sig_id = signature_payload.get("signature_id", signature_payload.get("id", "api"))
        else:
            sig_hex = str(signature_payload)
            pub_hex = public_key_hex
            sig_id = "api"
        if not sig_hex or not pub_hex:
            return False
        pq_sig = PQSignature(
            id=sig_id,
            algorithm=algo,
            signature=bytes.fromhex(sig_hex.replace("0x", "")),
            public_key_hash=native.sha256_hex(pub_hex.encode()),
            message_hash=native.sha256_hex(msg_bytes),
        )
        pub_bytes = bytes.fromhex(pub_hex.replace("0x", ""))
        return self.verify(pq_sig, msg_bytes, pub_bytes)


# ============================================================================
# ГИБРИДНАЯ КРИПТОГРАФИЯ (КЛАССИЧЕСКАЯ + ПОСТ-КВАНТОВАЯ)
# ============================================================================

class HybridCrypto:
    """
    Гибридная криптография
    Комбинирует классические и пост-квантовые алгоритмы
    """
    
    def __init__(self, pq_manager: PostQuantumManager):
        self.pq = pq_manager
        
    def hybrid_sign(self, message: bytes, pq_keypair: PQKeyPair, ecdsa_key: str) -> Dict:
        """
        Гибридная подпись (ECDSA + пост-квант)
        """
        raise NotImplementedError("Hybrid signature backend not available")
    
    def hybrid_encrypt(self, message: bytes, pq_public_key: bytes, ecdsa_public_key: str) -> Dict:
        """
        Гибридное шифрование
        """
        raise NotImplementedError("Hybrid encryption backend not available")
    
    def hybrid_decrypt(self, encrypted: Dict, pq_keypair: PQKeyPair) -> Optional[bytes]:
        """
        Гибридное расшифрование
        """
        raise NotImplementedError("Hybrid decryption backend not available")