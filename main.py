#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║         ABSOLUTE BLOCKCHAIN NODE — main.py               ║
║  Единственная точка запуска всего узла.                  ║
╚══════════════════════════════════════════════════════════╝

Использование:
    python main.py                         # полный узел (miner + validator)
    python main.py --mode miner            # только майнинг
    python main.py --mode validator        # только валидация
    python main.py --mode rpc-only         # только RPC/HTTP без майнинга
    python main.py --config node.json      # кастомный конфиг из файла
    python main.py --port 5001             # другой P2P-порт
    python main.py --peers 127.0.0.1:5000  # bootstrap-пиры
    python main.py --data-dir ./mydata     # кастомная директория данных
"""

import asyncio
import argparse
import json
import signal
import sys
import os
import time
import threading
import logging
from concurrent.futures import ThreadPoolExecutor

_node_log = logging.getLogger("Node")


def _configure_stdio_utf8() -> None:
    """Windows cp1251 consoles crash on emoji in print when stdout is redirected."""
    if sys.platform != "win32":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_stdio_utf8()

# ── Настройка путей ──────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── Импорты всех модулей узла ────────────────────────────────────────────────
from runtime.config import Config
from storage.factory import open_database, open_storage
from core.blockchain import Blockchain, Transaction
from core.chain_apply_queue import ChainApplyQueue
from blockchain.mempool import Mempool, MempoolTransaction
from kernel.event_bus import EventBus
from consensus.adapter import ConsensusAdapter
from execution.evm_adapter import EVMAdapter
from network.p2p_node import P2PNode
from api.http import (
    start_rpc_server_thread,
    start_http_server_thread,
    shutdown_http_server,
    set_accepting_requests,
)
from network.websocket import WebSocketServer
from bridge.adapter import build_bridge_port
from features.nft import NFTMarketplace
from features.zk import ZKProofSystem

# --- Wallet (ECDSA miner key generation) ---
try:
    from crypto.wallet import Wallet
    _WALLET_AVAILABLE = True
except ImportError:
    _WALLET_AVAILABLE = False

# --- Dynamic Sharding ---
try:
    from dynamic_sharding import ShardingManager
    _SHARDING_AVAILABLE = True
except Exception:
    _SHARDING_AVAILABLE = False

# --- Real World Oracles ---
try:
    from features.oracle_registry import OracleFeedRegistry
    _ORACLE_REGISTRY_AVAILABLE = True
except Exception:
    OracleFeedRegistry = None  # type: ignore
    _ORACLE_REGISTRY_AVAILABLE = False

try:
    from real_world_oracles import OracleManager
    _ORACLE_MANAGER_AVAILABLE = True
except Exception:
    _ORACLE_MANAGER_AVAILABLE = False

_ORACLES_AVAILABLE = _ORACLE_REGISTRY_AVAILABLE or _ORACLE_MANAGER_AVAILABLE

# --- Multisig Wallets ---
try:
    from features.multisig import MultiSigWallet
    _MULTISIG_AVAILABLE = True
except Exception:
    _MULTISIG_AVAILABLE = False

# --- Smart Accounts ---
try:
    from features.smart_accounts import SmartAccountManager
    _SMART_ACCOUNTS_AVAILABLE = True
except Exception:
    _SMART_ACCOUNTS_AVAILABLE = False

# --- Post-Quantum Crypto ---
try:
    from crypto.sphincs_plus import SPHINCSPLUS as SphincsPlus
    _POSTQUANTUM_AVAILABLE = True
except Exception:
    _POSTQUANTUM_AVAILABLE = False

# --- MiniVM Contract Manager + Assembler ---
try:
    from execution.contract_manager import ContractManager
    from compiler.assembler import Assembler, assemble
    _MINIVM_CONTRACTS_AVAILABLE = True
except Exception:
    _MINIVM_CONTRACTS_AVAILABLE = False

# --- BlockBuilder ---
try:
    from execution.block_builder import BlockBuilder
    _BLOCK_BUILDER_AVAILABLE = True
except Exception:
    _BLOCK_BUILDER_AVAILABLE = False

# --- ValidatorKeys ---
try:
    from crypto.validator_keys import ValidatorKeys
    _VALIDATOR_KEYS_AVAILABLE = True
except Exception:
    _VALIDATOR_KEYS_AVAILABLE = False

# --- Transaction Validator ---
try:
    from blockchain.tx_validator import TransactionValidator
    _TX_VALIDATOR_AVAILABLE = True
except Exception:
    _TX_VALIDATOR_AVAILABLE = False

# --- RANDAO Validator Selection ---
try:
    from consensus.validator_selection import ValidatorSelection
    _VALIDATOR_SELECTION_AVAILABLE = True
except Exception:
    _VALIDATOR_SELECTION_AVAILABLE = False

# --- Chain Storage (JSON file backup) ---
try:
    from storage.chain_storage import ChainStorage
    _CHAIN_STORAGE_AVAILABLE = True
except Exception:
    _CHAIN_STORAGE_AVAILABLE = False

# --- PostQuantum Manager (full suite) ---
try:
    from features.postquantum import PostQuantumManager
    _PQ_MANAGER_AVAILABLE = True
except Exception:
    _PQ_MANAGER_AVAILABLE = False

# --- AI Validator Engine ---
try:
    from features.ai_validator import AIValidatorEngine
    _AI_VALIDATOR_AVAILABLE = True
except Exception:
    _AI_VALIDATOR_AVAILABLE = False

# --- Reorg Predictor ---
try:
    from features.reorg_predictor import ReorgPredictor
    _REORG_PREDICTOR_AVAILABLE = True
except Exception:
    _REORG_PREDICTOR_AVAILABLE = False

# --- MEV Analyzer ---
try:
    from features.mev_analyzer import MEVAnalyzer
    _MEV_ANALYZER_AVAILABLE = True
except Exception:
    _MEV_ANALYZER_AVAILABLE = False

# --- Immutable State Manager (satoshi-precision balances) ---
try:
    from blockchain.immutable_state import ImmutableStateManager
    _IMMUTABLE_STATE_AVAILABLE = True
except Exception:
    _IMMUTABLE_STATE_AVAILABLE = False

# --- Lightning Network (payment channels) ---
try:
    from features.lightning import LightningNetwork
    _LIGHTNING_AVAILABLE = True
except Exception:
    _LIGHTNING_AVAILABLE = False

# --- Crypto Will (blockchain inheritance) ---
try:
    from features.crypto_will import CryptoWillManager
    _CRYPTO_WILL_AVAILABLE = True
except Exception:
    _CRYPTO_WILL_AVAILABLE = False

# --- Plasma Chain (L2 sidechain) ---
try:
    from features.plasma import PlasmaChain
    _PLASMA_AVAILABLE = True
except Exception:
    _PLASMA_AVAILABLE = False

# --- WASM VM (WebAssembly-style smart contracts) ---
try:
    from features.wasm_vm import WASMVirtualMachine
    _WASM_VM_AVAILABLE = True
except Exception:
    _WASM_VM_AVAILABLE = False

# --- AI Agent Manager (trading agents) ---
try:
    from features.ai_manager import AIAgentManager
    _AI_MANAGER_AVAILABLE = True
except Exception:
    _AI_MANAGER_AVAILABLE = False

# --- Cross-Chain Bridge dev/test adapter ---
try:
    from bridge.dev_bridge_adapter import DevBridgeAdapter
    _CROSS_BRIDGE_AVAILABLE = True
except Exception:
    _CROSS_BRIDGE_AVAILABLE = False

# --- Standalone Consensus Engine (PoS slots/epochs) ---
try:
    from consensus_engine import ConsensusEngine as StandaloneConsensusEngine
    _CONSENSUS_ENGINE_AVAILABLE = True
except Exception:
    _CONSENSUS_ENGINE_AVAILABLE = False

# --- Finality Engine (Casper FFG) ---
try:
    from finality_engine import FinalityEngine
    _FINALITY_ENGINE_AVAILABLE = True
except Exception:
    _FINALITY_ENGINE_AVAILABLE = False

# --- Sync Engine ---
try:
    from sync.sync_engine import SyncEngine
    _SYNC_ENGINE_AVAILABLE = True
except Exception:
    _SYNC_ENGINE_AVAILABLE = False


# ── Логирование ──────────────────────────────────────────────────────────────

def _setup_logging(config: Config):
    from observability.logging_setup import setup_logging as _obs_setup
    _obs_setup(
        log_level=config.log_level,
        log_file=config.log_file,
        log_json=getattr(config, "log_json", False),
        node_id=getattr(config, "node_id", "node-1"),
        deployment_mode=getattr(config, "deployment_mode", "dev"),
    )


_ACTIVE_NODE: "NodeOrchestrator | None" = None


def _handle_shutdown_signal(signum, frame):
    """OS signal path — drain via NodeOrchestrator.stop then exit PID (ADR 0014).

    After RocksDB clean close we must ``os._exit``: ``asyncio.gather`` can remain
    stuck on native P2P ``asyncio.to_thread(accept)`` even though tasks were
    cancelled and storage already closed (observed on Windows SIGBREAK).
    """
    global _ACTIVE_NODE
    print(f"\n[Node] Signal {signum} received — graceful shutdown")
    node = _ACTIVE_NODE
    if node is None:
        return
    try:
        # Inline drain is intentional: Windows signal handlers already reached
        # clean close here; only the post-Goodbye PID hang needed fixing.
        node.stop(force_process_exit=True)
    except Exception as exc:
        print(f"[Node] shutdown drain error: {exc}")
        os._exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  NodeOrchestrator — центральный оркестратор
# ═══════════════════════════════════════════════════════════════════════════════

class NodeOrchestrator:
    """
    Собирает все компоненты в единый работающий узел.

    Порядок инициализации:
      1. EventBus      — шина событий (нет зависимостей)
      2. Database      — БД (нет зависимостей, кроме config.db_path)
      3. Mempool       — пул транзакций (нет зависимостей)
      4. Blockchain    — ядро (зависит от Database, EventBus)
      5. Consensus     — консенсус (зависит от Blockchain, Database, EventBus)
      6. EVM           — исполнитель (зависит от Database)
      7. P2PNode       — сеть (зависит от Blockchain, Mempool, EventBus)
      8. Bridge        — кросс-чейн мост (зависит от Database, EventBus)
      9. RPC Server    — JSON-RPC :8545 (зависит от Blockchain, Mempool)
     10. HTTP Server   — REST API :8080 (зависит от всего выше)
    """

    def __init__(self, config: Config):
        global _ACTIVE_NODE
        self.config = config
        self.feature_init_errors: dict = {}
        self._running = False
        self._shutting_down = False
        self._mesh_forge_hold_height = 0
        self._tasks = []
        self._rpc_server = None
        self._http_server = None
        _ACTIVE_NODE = self

        logging.getLogger("Node").info("Initializing components...")

        # 1. Шина событий
        self.bus = EventBus()

        # 2. База данных
        self.db = open_database(config)
        self.db.initialize()
        engine = getattr(self.db, "engine", getattr(config, "db_engine", "sqlite"))
        print(f"[Node] Database: {config.db_path} (engine={engine})")

        _data_dir = os.path.dirname(config.db_path) if os.path.dirname(config.db_path) else "data"
        _wallet_path = os.path.join(_data_dir, "wallet.json")
        _founder_tpl = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "docker", "founder.wallet.json"
        )
        if not os.path.exists(_wallet_path) and os.path.isfile(_founder_tpl):
            os.makedirs(_data_dir, exist_ok=True)
            import shutil as _shutil
            _shutil.copy(_founder_tpl, _wallet_path)
            print(f"[Node] Founder wallet template installed: {_wallet_path}")
        if os.path.exists(_wallet_path):
            try:
                import json as _json
                with open(_wallet_path, encoding="utf-8") as _wf:
                    _waddr = _json.load(_wf).get("address", "")
                if _waddr:
                    if not getattr(config, "founder_address", ""):
                        config.founder_address = _waddr
                    if not config.miner_address:
                        config.miner_address = _waddr
            except Exception as exc:
                _node_log.warning("founder wallet template read failed: %s", exc)

        # 3. Мемпул
        self.mempool = Mempool(max_size=10_000, min_fee=config.base_fee() * 0.5)

        # 4. Ядро блокчейна (StoragePort DI — ADR 0006 D–E canonical UoW)
        self.storage = open_storage(self.db)
        self.blockchain = Blockchain(config, self.db, self.bus, storage=self.storage)
        self.apply_queue = ChainApplyQueue(
            self.blockchain,
            maxsize=int(getattr(config, "chain_apply_queue_max", 64) or 64),
            timeout_sec=float(getattr(config, "chain_apply_timeout_sec", 120.0) or 120.0),
        )
        self.sync_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="AbsSyncState"
        )
        print(
            f"[Node] ChainApplyQueue: max={self.apply_queue.maxsize} "
            f"timeout={self.apply_queue.timeout_sec}s (serial mine+import)"
        )
        print("[Node] SyncState executor: dedicated pool (max_workers=2)")
        self.mempool.set_blockchain(self.blockchain)
        print(f"[Node] Blockchain height: {self.blockchain.get_height()}")
        if (
            config.verify_peer_state_root
            and not config.state_root_legacy_cutoff_height
            and self.blockchain.get_height() > 0
        ):
            config.state_root_legacy_cutoff_height = self.blockchain.get_height()
        if config.verify_peer_state_root:
            self.blockchain.set_state_root_baseline(
                config.state_root_legacy_cutoff_height or self.blockchain.get_height()
            )
            print(
                f"[Node] state_root policy: strict_p2p={config.state_root_strict_p2p} "
                f"baseline=#{self.blockchain._state_root_baseline}"
            )
        # Сохраняем метаданные токеномики (genesis-аллокация — после загрузки wallet)
        try:
            from runtime.tokenomics import get_tokenomics_summary, resolve_founder_address
            founder = resolve_founder_address(
                getattr(config, "founder_address", ""),
                config.miner_address,
            )
            if not self.db.get_meta("tokenomics"):
                self.db.set_meta("tokenomics", get_tokenomics_summary(founder or None))
                print(f"[Node] Tokenomics saved: 221M ABS, founder D.U.P. 17.4%")
        except Exception as _tok_err:
            print(f"[Node] Tokenomics migration note: {_tok_err}")

        # 5. Консенсус
        self.consensus = ConsensusAdapter(config, self.db, self.bus)
        self.blockchain.consensus_adapter = self.consensus

        # ADR 0015 — SecretManagerPort (env/K8s / Vault / file)
        _data_dir = os.path.dirname(config.db_path) if os.path.dirname(config.db_path) else "data"
        _wallet_path = os.path.join(_data_dir, "wallet.json")
        try:
            from secret_mgmt import (
                SECRET_NODE_BFT_SIGNING_KEY,
                SECRET_NODE_WALLET_PRIVATE_KEY,
                build_secret_manager,
            )
            self.secret_manager = build_secret_manager(
                config, wallet_path=_wallet_path
            )
        except Exception as _sm_err:
            self.secret_manager = None
            print(f"[Node] SecretManager unavailable ({_sm_err})")

        def _resolve_wallet_private_key() -> str:
            """Resolve signing key via SecretManagerPort; never log the value."""
            sm = getattr(self, "secret_manager", None)
            if sm is None:
                return (os.environ.get("WALLET_PRIVATE_KEY", "") or "").strip()
            for logical in (
                SECRET_NODE_WALLET_PRIVATE_KEY,
                SECRET_NODE_BFT_SIGNING_KEY,
            ):
                try:
                    if sm.has_secret(logical):
                        return (sm.get_secret(logical) or "").strip()
                except Exception as exc:
                    _node_log.warning("secret lookup failed for %s: %s", logical, exc)
                    continue
            return ""

        # Если miner_address не задан — загружаем wallet.json или генерируем ECDSA
        self.wallet = None
        _chain_h_boot = self.blockchain.get_height() if self.blockchain else 0
        if os.path.exists(_wallet_path):
            try:
                import json as _json
                with open(_wallet_path, encoding="utf-8") as _wf:
                    _wdata = _json.load(_wf)
                _waddr = _wdata.get("address", "")
                if _waddr:
                    if not getattr(config, "founder_address", ""):
                        config.founder_address = _waddr
                    if not config.miner_address:
                        config.miner_address = _waddr
                    print(f"[Node] Founder wallet (D.U.P.): {_waddr}")
                if _WALLET_AVAILABLE:
                    _follower_node = not config.mining_enabled and _chain_h_boot > 1
                    if _wdata.get("private_key") and not _follower_node:
                        self.wallet = Wallet.import_wallet(_wallet_path)
                        config.signing_address = self.wallet.address
                        if not config.miner_address:
                            config.miner_address = self.wallet.address
                        print(f"[Node] Wallet loaded from wallet.json (signing enabled): {self.wallet.address}")
                    elif _wdata.get("private_key") and _follower_node:
                        print(
                            f"[Node] Follower node: wallet.json private_key ignored "
                            f"(height={_chain_h_boot})"
                        )
                    else:
                        _pk_env = _resolve_wallet_private_key()
                        if _pk_env:
                            try:
                                _w = Wallet.from_private_key(_pk_env)
                                self.wallet = _w
                                config.signing_address = _w.address
                                _founder_mining = (
                                    _waddr
                                    and config.miner_address
                                    and config.miner_address.lower() == _waddr.lower()
                                )
                                if _founder_mining and _w.address.lower() != _waddr.lower():
                                    self._dev_signer_only = True
                                    print(
                                        f"[Node] Signing wallet from SecretManager: "
                                        f"{_w.address} (founder mines: {_waddr})"
                                    )
                                else:
                                    config.miner_address = _w.address
                                    print(
                                        f"[Node] Operational wallet from SecretManager: "
                                        f"{_w.address} (mining + signing)"
                                    )
                                if _waddr and _w.address.lower() != _waddr.lower() and not _founder_mining:
                                    print(
                                        f"[Node] Founder in wallet.json is watch-only "
                                        f"(tokenomics): {_waddr}"
                                    )
                            except Exception as _pke:
                                print(f"[Node] SecretManager wallet key invalid ({_pke})")
            except Exception as _we:
                print(f"[Node] Wallet load warning ({_we})")
        elif _WALLET_AVAILABLE:
            _pk_env = _resolve_wallet_private_key()
            if _pk_env:
                try:
                    _w = Wallet.from_private_key(_pk_env)
                    self.wallet = _w
                    config.signing_address = _w.address
                    config.miner_address = _w.address
                    print(f"[Node] Operational wallet from SecretManager: {_w.address}")
                except Exception as _pke:
                    print(f"[Node] SecretManager wallet key invalid ({_pke})")
        if config.require_wallet_file and self.wallet is None:
            _synced_prod_follower = (
                not config.mining_enabled
                and getattr(config, "follower_genesis_sync", False)
                and _chain_h_boot > 1
                and os.path.exists(_wallet_path)
            )
            if not _synced_prod_follower:
                raise RuntimeError(
                    f"Production mode requires wallet with private_key at: {_wallet_path}"
                )
            print(
                f"[Node] Prod synced follower: wallet.json present (watch-only, "
                f"height={_chain_h_boot})"
            )
        if _WALLET_AVAILABLE and self.wallet is None and not config.require_wallet_file:
            if config.miner_address and os.path.exists(_wallet_path):
                _dev_loaded = False
                if config.deployment_mode == "dev":
                    _dev_signer_path = os.path.join(_data_dir, "dev_signer.json")
                    _chain_h = self.blockchain.get_height() if self.blockchain else 0
                    try:
                        # Only skip inventing a signer once the chain has real blocks
                        # past genesis. genesis_alloc_applied alone is true on every
                        # fresh DB after _ensure_genesis — that must not block signing.
                        _seeded_chain = _chain_h >= 1
                        if _seeded_chain and not os.path.exists(_dev_signer_path):
                            print(
                                f"[Node] Seeded chain (height={_chain_h}) — "
                                "dev_signer skipped (state integrity)"
                            )
                        elif os.path.exists(_dev_signer_path) and config.mining_enabled:
                            self.wallet = Wallet.import_wallet(_dev_signer_path)
                        elif _chain_h <= 1 and config.mining_enabled:
                            self.wallet = Wallet.create_new()
                            os.makedirs(_data_dir, exist_ok=True)
                            self.wallet.export(_dev_signer_path)
                            # Avoid mutating genesis state_root when alloc already applied
                            # (P2P peers would diverge). Fund via /devnet/faucet instead.
                            if not self.db.get_meta("genesis_alloc_applied"):
                                self.db.update_balance(self.wallet.address, 10_000.0)
                                print(
                                    f"[Node] Dev signer created + funded (10k ABS): "
                                    f"{self.wallet.address}"
                                )
                            else:
                                print(
                                    f"[Node] Dev signer created (unfunded): "
                                    f"{self.wallet.address}"
                                )
                        if self.wallet:
                            config.signing_address = self.wallet.address
                            self._dev_signer_only = True
                            _dev_loaded = True
                            if (
                                _chain_h <= 1
                                and not self.db.get_meta("genesis_alloc_applied")
                                and self.db.get_balance(self.wallet.address) < 1.0
                            ):
                                self.db.update_balance(self.wallet.address, 10_000.0)
                            print(
                                f"[Node] Dev signing wallet ready: {self.wallet.address} "
                                f"(miner unchanged: {config.miner_address})"
                            )
                    except Exception as _dse:
                        print(f"[Node] Dev signer warning: {_dse}")
                if not _dev_loaded:
                    print(
                        f"[Node] Wallet address loaded (no private_key in file — "
                        f"signing disabled): {config.miner_address}"
                    )
            else:
                try:
                    self.wallet = Wallet.create_new()
                    if not config.miner_address:
                        config.miner_address = self.wallet.address
                    if not getattr(config, "founder_address", ""):
                        config.founder_address = self.wallet.address
                    print(f"[Node] ECDSA wallet generated. Address: {config.miner_address}")
                    try:
                        os.makedirs(_data_dir, exist_ok=True)
                        self.wallet.export(_wallet_path)
                        print(f"[Node] Wallet saved: {_wallet_path}")
                    except Exception as _save_err:
                        print(f"[Node] Wallet save warning: {_save_err}")
                except Exception as _we:
                    print(f"[Node] Wallet unavailable ({_we})")
        if not config.miner_address:
            from crypto import native as _native
            config.miner_address = "0x" + _native.sha256_hex(
                f"miner-{config.p2p_port}".encode()
            )[:40]

        try:
            from runtime.validator_key_provider import build_validator_key_provider
            self.validator_key_provider = build_validator_key_provider(self.wallet)
        except Exception as exc:
            self.validator_key_provider = None
            print(
                f"[Node] Validator key provider unavailable ({exc}); "
                f"auto-generated miner address: {config.miner_address}"
            )

        self._pin_chain_founder_address()
        self._apply_genesis_allocation()

        _val_idx = int(getattr(config, "testnet_validator_index", 0) or 0)
        if _val_idx >= 2 and config.mining_enabled and config.deployment_mode == "dev":
            try:
                from runtime.devnet_validators import install_validator_wallet
                install_validator_wallet(self, _val_idx)
            except Exception as _d5w:
                print(f"[Node] Devnet5 validator wallet note: {_d5w}")

        _manifest = getattr(config, "testnet_validators_manifest", "") or ""
        if not _manifest and int(getattr(config, "testnet_expected_validators", 0) or 0) >= 3:
            try:
                from runtime.devnet_validators import resolve_manifest_path
                _manifest = resolve_manifest_path(config)
            except Exception as exc:
                _node_log.warning("devnet manifest resolve failed: %s", exc)
                _manifest = ""
        if _manifest and os.path.isfile(_manifest) and config.deployment_mode == "dev":
            try:
                from runtime.devnet_validators import apply_manifest
                apply_manifest(self, _manifest)
            except Exception as _d5m:
                print(f"[Node] Devnet5 manifest note: {_d5m}")

        # Если нет валидаторов в БД — регистрируем текущий узел как валидатор
        if not self.db.get_validators():
            self.consensus.add_validator(config.miner_address, config.min_stake)
            print(f"[Node] Registered self as validator: {config.miner_address}")

        # Operational wallet (WALLET_PRIVATE_KEY) must mine + sign on solo devnet
        _op = getattr(config, "signing_address", "") or ""
        _multi_validator_devnet = int(
            getattr(config, "testnet_expected_validators", 0) or 0
        ) >= 3
        if (
            _op
            and self.wallet
            and not getattr(self, "_dev_signer_only", False)
            and not _multi_validator_devnet
        ):
            _vals = self.db.get_validators(active_only=True) or []
            if not any(v["address"].lower() == _op.lower() for v in _vals):
                self.consensus.add_validator(_op, config.min_stake)
            config.miner_address = _op
            print(f"[Node] Mining proposer locked to operational wallet: {_op}")

        # 4b. Pool locks (ecosystem/treasury/staking enforcement)
        try:
            from runtime.pool_locks import PoolLockManager
            founder = getattr(config, "founder_address", "") or config.miner_address
            self.pool_locks = PoolLockManager(
                self.db, founder, epoch_size=getattr(config, "epoch_size", 32)
            )
            self.blockchain.pool_locks = self.pool_locks
            print("[Node] PoolLockManager: ecosystem/treasury/staking locks active")
        except Exception as _pl_err:
            self.pool_locks = None
            print(f"[Node] PoolLockManager: unavailable ({_pl_err})")

        # 4c. Light client (SPV headers)
        try:
            from light.light_client import LightClient
            self.light_client = LightClient()
            synced = self.light_client.sync_from_blockchain(self.blockchain)
            print(f"[Node] LightClient: enabled ({synced} headers synced)")
        except Exception as _lc_err:
            self.light_client = None
            print(f"[Node] LightClient: unavailable ({_lc_err})")

        # 6. EVM
        self.evm = EVMAdapter(self.db, config) if config.evm_enabled else None
        if self.evm:
            print("[Node] EVM: enabled")
        self.blockchain.evm = self.evm

        # 7. P2P
        self.p2p = P2PNode(config, self.blockchain, self.mempool, self.bus)
        self.p2p.apply_queue = self.apply_queue
        self.p2p.sync_executor = self.sync_executor

        # 7b. Tip-safety gate (stage 2 shadow / stage 3 enforce)
        from consensus.tip_safety import TipSafetyShadowObserver

        _enforce = bool(getattr(config, "tip_safety_enforce", False))
        _shadow = bool(getattr(config, "tip_safety_shadow", False)) or _enforce
        self.tip_safety_shadow = TipSafetyShadowObserver(
            enabled=_shadow,
            enforce=_enforce,
        )
        self.p2p.tip_safety_shadow = self.tip_safety_shadow
        if self.tip_safety_shadow.enabled:
            synced = self.tip_safety_shadow.sync_from_chain(self.blockchain)
            mode = "ENFORCE" if self.tip_safety_shadow.enforce else "shadow-observe"
            print(
                f"[Node] Tip-safety: {mode} (synced={synced})"
            )
        else:
            print(
                "[Node] Tip-safety: OFF "
                "(TIP_SAFETY_SHADOW=1 observe, TIP_SAFETY_ENFORCE=1 refuse)"
            )

        # 8. NFT marketplace (app-profile sprout; off on prod mesh — ADR 0016)
        from features.nft_ports import NftMarketplaceAdapter, NullNftMarketplacePort

        if getattr(config, "feature_nft", True):
            self.nft = NFTMarketplace(db=self.db, bus=self.bus)
            self.nft_port = NftMarketplaceAdapter(self.nft)
            stats = self.nft.get_stats()
            print(
                f"[Node] NFT Marketplace: {len(self.nft.tokens)} tokens "
                f"(persisted={stats.get('persisted', False)}, "
                f"execution_bound={stats.get('execution_bound', False)})"
            )
        else:
            self.nft = None
            self.nft_port = NullNftMarketplacePort()
            print("[Node] NFT Marketplace: disabled")

        # 9. ZK Proof System (R&D; disabled by prod profile)
        self.zk = ZKProofSystem() if getattr(config, "feature_zk", True) else None
        print("[Node] ZK Proof System: ready" if self.zk else "[Node] ZK Proof System: disabled")
        if hasattr(self.blockchain, "attach_zk_system"):
            self.blockchain.attach_zk_system(
                self.zk, enabled=bool(getattr(config, "feature_zk", True))
            )

        # 10. Мост (ADR 0010 — BridgePort after ZK so inbound validator can use gateway)
        self.bridge = build_bridge_port(
            config,
            self.db,
            self.bus,
            zk_gateway=getattr(self.blockchain, "zk_gateway", None),
        )
        if hasattr(self.blockchain, "attach_bridge"):
            self.blockchain.attach_bridge(self.bridge)
        if config.bridge_enabled and getattr(config, "bridge_mode", "rust") == "simulator":
            print(
                "[Node] WARN: bridge_mode=simulator is dev/test only - "
                "set BRIDGE_MODE=rust for real L1 cross-chain path"
            )
        elif config.bridge_enabled and getattr(config, "bridge_mode", "rust") == "fake":
            print("[Node] WARN: bridge_mode=fake is test-only FakeEvmBridge")

        # 11. Dynamic Sharding
        if _SHARDING_AVAILABLE and getattr(config, "feature_sharding", True):
            self.sharding = ShardingManager(
                num_shards=getattr(config, "num_shards", 4),
                db=self.db,
                assigned_shard_id=getattr(config, "assigned_shard_id", -1),
                node_id=config.node_id,
                mode=getattr(config, "shard_mode", "routing"),
            )
            shard_id = getattr(config, "assigned_shard_id", -1)
            reg_shard = shard_id if shard_id >= 0 else None
            self.sharding.register_node(config.node_id, reg_shard)
            if self.p2p and hasattr(self.p2p, "set_sharding"):
                self.p2p.set_sharding(self.sharding)
            mode = "distributed" if self.sharding.is_distributed() else "routing"
            print(
                f"[Node] Sharding: {self.sharding.num_shards} shards ({mode}"
                f"{f', assigned={shard_id}' if shard_id >= 0 else ''})"
            )
        else:
            self.sharding = None

        # 12. Real World Oracles (crypto prices, weather) + on-chain feed registry
        self.oracle_registry = None
        self.oracles = None
        if _ORACLE_REGISTRY_AVAILABLE and getattr(config, "feature_oracles", True):
            try:
                self.oracle_registry = OracleFeedRegistry(self.db)
                print("[Node] Oracle registry: SQLite feeds enabled")
            except Exception as e:
                self.oracle_registry = None
                self.feature_init_errors["oracles"] = str(e)
                print(f"[Node] Oracle registry: unavailable ({e})")
        if _ORACLE_MANAGER_AVAILABLE and getattr(config, "feature_oracles", True):
            try:
                self.oracles = OracleManager()
                print("[Node] Oracles: price feeds active (BTC/ETH/ABS)")
            except Exception as e:
                self.oracles = None
                self.feature_init_errors["oracles"] = str(e)
                print(f"[Node] Oracles: live feeds unavailable ({e})")

        # 13. Multisig support (in-memory registry; no chain executor by default)
        if _MULTISIG_AVAILABLE:
            self.multisig = MultiSigWallet  # pass class for API to instantiate
            print(
                "[Node] Multisig: available "
                "(persistent=false, execution_bound=false — in-memory only)"
            )
        else:
            self.multisig = None

        # 14. Smart Accounts (Account Abstraction — in-memory unless executor wired)
        if _SMART_ACCOUNTS_AVAILABLE and getattr(config, "feature_smart_accounts", True):
            try:
                self.smart_accounts = SmartAccountManager()
                print(
                    "[Node] Smart Accounts: available "
                    "(persistent=false, execution_bound=false — no chain executor)"
                )
            except Exception as e:
                self.smart_accounts = None
                print(f"[Node] Smart Accounts: unavailable ({e})")
        else:
            self.smart_accounts = None
            if not getattr(config, "feature_smart_accounts", True):
                print("[Node] Smart Accounts: disabled")

        # 15. Post-Quantum Crypto
        if _POSTQUANTUM_AVAILABLE and getattr(config, "feature_pq", True):
            print("[Node] Post-Quantum Crypto: SPHINCS+ interface available (backend required)")

        # 16. WebSocket server (real-time browser events on :8546)
        self.ws_server = WebSocketServer(
            event_bus=self.bus,
            host=getattr(config, "ws_host", "0.0.0.0"),
            port=getattr(config, "ws_port", 8546),
            blockchain=self.blockchain,
            config=config,
        )

        # 17. MiniVM Contract Manager + Assembler (R&D — not chain-canonical)
        if _MINIVM_CONTRACTS_AVAILABLE and getattr(config, "feature_minivm", True):
            self.contract_manager = ContractManager(db=self.db)
            self.assembler = Assembler()
            print(
                "[Node] MiniVM ContractManager: available "
                "(execution_bound=false, canonical=false — R&D registry only)"
            )
        else:
            self.contract_manager = None
            self.assembler = None
            if not getattr(config, "feature_minivm", True):
                print("[Node] MiniVM: disabled")

        # 18. Deterministic hash-ranked proposer selection (not commit/reveal RANDAO)
        if _VALIDATOR_SELECTION_AVAILABLE and getattr(
            config, "feature_validator_selection", True
        ):
            self.validator_selection = ValidatorSelection()
            last_blk = self.blockchain.get_last_block()
            if last_blk and last_blk.get("hash"):
                self.validator_selection.update_seed(last_blk["hash"])
            print(
                "[Node] ValidatorSelection: deterministic_hash_selection "
                "(randao_commit_reveal=false)"
            )
        else:
            self.validator_selection = None
            if not getattr(config, "feature_validator_selection", True):
                print("[Node] ValidatorSelection: disabled")

        # 19. Chain Storage (JSON file backup layer)
        if _CHAIN_STORAGE_AVAILABLE:
            self.chain_storage = ChainStorage(data_dir="data")
            print("[Node] ChainStorage: JSON backup layer ready")
        else:
            self.chain_storage = None

        # 20. Post-Quantum Manager (educational / R&D — not NIST production backends)
        if _PQ_MANAGER_AVAILABLE and getattr(config, "feature_pq", True):
            try:
                self.pq_manager = PostQuantumManager()
                print(
                    "[Node] PostQuantumManager: educational suite loaded "
                    "(Dilithium=hash-demo; Kyber/Falcon=NotImplemented — not prod-ready)"
                )
            except Exception as e:
                self.pq_manager = None
                print(f"[Node] PostQuantumManager: unavailable ({e})")
        else:
            self.pq_manager = None

        # 21. Transaction Validator
        if _TX_VALIDATOR_AVAILABLE:
            self.tx_validator = TransactionValidator()
            print("[Node] TransactionValidator: enabled (nonce/fee/balance checks)")
        else:
            self.tx_validator = None

        # 22. AI Validator Engine (simulation_only; off in prod via FEATURE_AI_VALIDATOR)
        if _AI_VALIDATOR_AVAILABLE and getattr(config, "feature_ai_validator", True):
            self.ai_validator = AIValidatorEngine()
            print(
                "[Node] AIValidatorEngine: enabled "
                "(simulation_only; consensus_wired=false; model_bound=false)"
            )
        else:
            self.ai_validator = None
            if _AI_VALIDATOR_AVAILABLE:
                print("[Node] AIValidatorEngine: disabled (feature_ai_validator=false)")

        # 23. Reorg Predictor
        if _REORG_PREDICTOR_AVAILABLE:
            self.reorg_predictor = ReorgPredictor(db=self.db)
            print("[Node] ReorgPredictor: enabled (SQLite assessments + fork risk)")
            if self.p2p:
                self.p2p.reorg_predictor = self.reorg_predictor
        else:
            self.reorg_predictor = None

        # 24. MEV analysis module (disabled by prod profile)
        if _MEV_ANALYZER_AVAILABLE and getattr(config, "feature_mev", True):
            self.mev_simulator = MEVAnalyzer(db=self.db)
            print("[Node] MEVAnalyzer: enabled (sandwich/arbitrage/frontrun analysis)")
        else:
            self.mev_simulator = None

        # 24b. StateEngine (deterministic state transitions)
        try:
            from execution.state_engine import StateEngine
            _se_candidate = getattr(self.blockchain, "state_engine", None)
            self.state_engine = _se_candidate if _se_candidate else StateEngine(db=self.db)
            print("[Node] StateEngine: enabled (deterministic state transitions)")
        except Exception as _se_err:
            self.state_engine = None
            print(f"[Node] StateEngine: unavailable ({_se_err})")
            if self.config.is_production:
                raise RuntimeError(
                    f"Production mode requires StateEngine: {_se_err}"
                ) from _se_err

        # 25. BlockBuilder (optional helper — forge path still uses create_block)
        if _BLOCK_BUILDER_AVAILABLE:
            try:
                self.block_builder = BlockBuilder(self.mempool, self.state_engine) if self.state_engine else None
                if self.block_builder:
                    # Honesty: constructed but not wired into mining forge.
                    print(
                        "[Node] BlockBuilder: constructed "
                        "(forge still uses blockchain.create_block — not wired)"
                    )
            except Exception as e:
                self.block_builder = None
                print(f"[Node] BlockBuilder: unavailable ({e})")
        else:
            self.block_builder = None

        # 26. Immutable State Manager (satoshi-precision, replay-only state)
        if _IMMUTABLE_STATE_AVAILABLE:
            self.immutable_state = ImmutableStateManager()
            try:
                from runtime.tokenomics import genesis_balances
                founder = getattr(config, "founder_address", "") or config.miner_address
                alloc = genesis_balances(founder or None)
                self.immutable_state.seed_from_balances(alloc)
                # Align shadow IMS to DB tip (rewards/burns already on chain if any)
                try:
                    self.immutable_state.reconcile_from_store(
                        self.db,
                        fail_loud=bool(getattr(config, "is_production", False)),
                    )
                except Exception as _ims_seed_rec:
                    print(f"[ImmutableState] reconcile_from_store at boot: {_ims_seed_rec}")
                    if getattr(config, "is_production", False):
                        raise
            except Exception as _ims_seed_err:
                print(f"[ImmutableState] seed_from_balances failed: {_ims_seed_err}")
                if getattr(config, "is_production", False):
                    raise
            print("[Node] ImmutableStateManager: enabled (satoshi-precision balances)")
        else:
            self.immutable_state = None
            if self.config.is_production:
                raise RuntimeError(
                    "Production mode requires ImmutableStateManager module"
                )
        # 27. ValidatorKeys (block/attestation signing)
        if _VALIDATOR_KEYS_AVAILABLE:
            try:
                self.validator_keys = ValidatorKeys().initialize(self.wallet)
                print(f"[Node] ValidatorKeys: initialized ({self.validator_keys.get_address()[:16]}...)")
            except Exception as e:
                self.validator_keys = None
                print(f"[Node] ValidatorKeys: unavailable ({e})")
        else:
            self.validator_keys = None

        if self.p2p:
            self.p2p.set_consensus(self.consensus, self.validator_keys)

        # Register attestation validator (node2 gets its own key separate from miner)
        self._attestation_validator = None
        if self.validator_keys and self.wallet:
            _vaddr = self.validator_keys.get_address()
            _vals = self.db.get_validators(active_only=False) or []
            if not _multi_validator_devnet and not any(
                v["address"].lower() == _vaddr.lower() for v in _vals
            ):
                self.consensus.add_validator(_vaddr, config.min_stake)
                print(f"[Node] Registered attestation validator: {_vaddr[:16]}…")
            self._attestation_validator = _vaddr

        # 28. Lightning Network (payment channels)
        if _LIGHTNING_AVAILABLE and getattr(config, "feature_lightning", True):
            try:
                self.lightning = LightningNetwork(
                    node_address=config.miner_address or "genesis",
                    db=self.db,
                )
                print("[Node] Lightning Network: payment channels ready")
            except Exception as e:
                self.lightning = None
                self.feature_init_errors["lightning"] = str(e)
                print(f"[Node] Lightning: unavailable ({e})")
        else:
            self.lightning = None

        # 29. Crypto Will (blockchain inheritance system)
        if _CRYPTO_WILL_AVAILABLE:
            try:
                self.crypto_will = CryptoWillManager(blockchain=self.blockchain, db=self.db)
                print("[Node] CryptoWill: inheritance system ready")
            except Exception as e:
                self.crypto_will = None
                print(f"[Node] CryptoWill: unavailable ({e})")
        else:
            self.crypto_will = None

        # 30. Plasma Chain (L2 sidechain)
        if _PLASMA_AVAILABLE and getattr(config, "feature_plasma", True):
            try:
                self.plasma = PlasmaChain(
                    chain_id="plasma_abs",
                    root_chain=self.blockchain,
                    db=self.db,
                )
                print("[Node] Plasma Chain: L2 sidechain ready")
            except Exception as e:
                self.plasma = None
                self.feature_init_errors["plasma"] = str(e)
                print(f"[Node] Plasma: unavailable ({e})")
        else:
            self.plasma = None

        # 31. WASM VM (WebAssembly-style contracts)
        if _WASM_VM_AVAILABLE and getattr(config, "feature_wasm", True):
            try:
                self.wasm_vm = WASMVirtualMachine(db=self.db)
                from features.wasm_engine import WASMEngine

                wt = WASMEngine.available()
                print(
                    f"[Node] WASM VM: registry ready "
                    f"(wasmtime={'on' if wt else 'off'}, "
                    f"execution_bound={wt}, pseudo_token_host=true)"
                )
            except Exception as e:
                self.wasm_vm = None
                self.feature_init_errors["wasm"] = str(e)
                print(f"[Node] WASM VM: unavailable ({e})")
        else:
            self.wasm_vm = None

        # 32. AI Agent Manager (trading agents; disabled by prod profile)
        if _AI_MANAGER_AVAILABLE and getattr(config, "feature_ai_agents", True):
            try:
                self.ai_manager = AIAgentManager(db=self.db)
                print("[Node] AI Agent Manager: registry ready (no model/executor bound)")
            except Exception as e:
                self.ai_manager = None
                print(f"[Node] AI Manager: unavailable ({e})")
        else:
            self.ai_manager = None

        # 33. Cross-Chain Bridge dev/test adapter (production path is RustBridge)
        if (
            _CROSS_BRIDGE_AVAILABLE
            and not config.bridge_enabled
            and getattr(config, "bridge_dev_adapter_enabled", False)
        ):
            try:
                self.cross_bridge = DevBridgeAdapter()
                print("[Node] Cross-Chain Bridge dev/test adapter: explicitly enabled")
            except Exception as e:
                self.cross_bridge = None
                print(f"[Node] Cross-Bridge dev/test adapter: unavailable ({e})")
        else:
            self.cross_bridge = None
            if config.bridge_enabled:
                print("[Node] Cross-Chain Bridge: using RustBridge (production path)")

        # 34. Standalone Consensus Engine (PoS slots/epochs/attestations)
        # Prod unified path: ConsensusAdapter only — skip parallel engines for API.
        _unified = config.resolved_consensus_mode() == "unified"
        if _unified:
            self.consensus_engine_standalone = None
            print("[Node] Consensus mode=unified: skipping parallel consensus engines")
        elif _CONSENSUS_ENGINE_AVAILABLE:
            try:
                self.consensus_engine_standalone = StandaloneConsensusEngine()
                if config.miner_address:
                    self.consensus_engine_standalone.add_validator(config.miner_address, config.min_stake)
                print("[Node] Standalone ConsensusEngine: PoS slots/attestations ready")
            except Exception as e:
                self.consensus_engine_standalone = None
                print(f"[Node] Standalone ConsensusEngine: unavailable ({e})")
        else:
            self.consensus_engine_standalone = None

        # 34b. Consensus Sub-Engines (LMD-GHOST, Casper, Slashing, Registry, Epoch, Beacon)
        # Slashing + registry + epoch stay available (ops/API); fork-choice engines only in parallel mode.
        try:
            from consensus.slashing import SlashingEngine as _SlashingEng
            self.slashing_engine = _SlashingEng()
            if config.miner_address:
                self.slashing_engine.register_validator(config.miner_address, config.min_stake)
            if self.db and hasattr(self.db, "save_slash_event"):
                self.slashing_engine.register_slash_callback(
                    lambda v, r, e, p: self.db.save_slash_event(v, r, e, p)
                )
            print("[Node] SlashingEngine: double-vote detection ready")
        except Exception as _e:
            self.slashing_engine = None
            print(f"[Node] SlashingEngine: unavailable ({_e})")

        try:
            from consensus.validator_registry import ValidatorRegistry as _ValReg
            self.validator_registry = _ValReg()
            if config.miner_address:
                self.validator_registry.register_validator(
                    config.miner_address, int(config.min_stake)
                )
            print("[Node] ValidatorRegistry: ready")
        except Exception as _e:
            self.validator_registry = None
            print(f"[Node] ValidatorRegistry: unavailable ({_e})")

        _public_manifest = getattr(config, "validators_manifest_path", "") or ""
        if _public_manifest and os.path.isfile(_public_manifest):
            try:
                from runtime.validator_loader import apply_public_manifest
                apply_public_manifest(self, _public_manifest)
            except Exception as _pm:
                if config.is_production:
                    raise
                print(f"[Node] Public validator manifest note: {_pm}")

        try:
            from api.http import RESTHandler
            RESTHandler.public_validator_set = getattr(self, "_public_validator_set", None)
            RESTHandler.validators_manifest_path = (
                getattr(self, "_public_validator_manifest", "") or ""
            )
        except Exception as _rh:
            print(f"[Node] RESTHandler public validator manifest wiring failed: {_rh}")

        try:
            from consensus.epoch import EpochManager as _EpMgr
            self.epoch_manager = _EpMgr(epoch_size=getattr(config, "epoch_size", 32))
            print(f"[Node] EpochManager: {self.epoch_manager.epoch_size} blocks/epoch")
        except Exception as _e:
            self.epoch_manager = None
            print(f"[Node] EpochManager: unavailable ({_e})")

        if _unified:
            self.beacon_finality = None
            self.lmd_table = None
            self.consensus_casper = None
            self.consensus_beacon = None
            self.consensus_engine_slashing = None
            self.casper_finality = None
        else:
            try:
                from consensus.finality_beacon import BeaconFinality as _BF
                self.beacon_finality = _BF()
                print("[Node] BeaconFinality: beacon chain finality ready")
            except Exception as _e:
                self.beacon_finality = None
                print(f"[Node] BeaconFinality: unavailable ({_e})")

            try:
                from consensus.lmd import LMDTable as _LMD
                self.lmd_table = _LMD()
                if config.miner_address:
                    self.lmd_table.add_validator(config.miner_address)
                print("[Node] LMDTable: LMD-GHOST fork choice ready")
            except Exception as _e:
                self.lmd_table = None
                print(f"[Node] LMDTable: unavailable ({_e})")

            try:
                from consensus.engine_casper import ConsensusEngineCasper as _CECasper
                self.consensus_casper = _CECasper()
                print("[Node] ConsensusEngineCasper: Casper FFG engine ready")
            except Exception as _e:
                self.consensus_casper = None
                print(f"[Node] ConsensusEngineCasper: unavailable ({_e})")

            try:
                from consensus.engine_beacon import ConsensusEngineBeacon as _CEBeacon
                self.consensus_beacon = _CEBeacon()
                print("[Node] ConsensusEngineBeacon: Beacon consensus ready")
            except Exception as _e:
                self.consensus_beacon = None
                print(f"[Node] ConsensusEngineBeacon: unavailable ({_e})")

            try:
                from consensus.engine_slashing import ConsensusEngineSlashing as _CESl
                self.consensus_engine_slashing = _CESl()
                print("[Node] ConsensusEngineSlashing: slashing-aware consensus ready")
            except Exception as _e:
                self.consensus_engine_slashing = None
                print(f"[Node] ConsensusEngineSlashing: unavailable ({_e})")

            try:
                from consensus.finality_casper import CasperFinality as _CasperFin
                self.casper_finality = _CasperFin()
                print("[Node] CasperFinality: Casper finality engine ready")
            except Exception as _e:
                self.casper_finality = None
                print(f"[Node] CasperFinality: unavailable ({_e})")

        try:
            from execution.block_validator import BlockValidator as _BV
            _se = getattr(self.blockchain, "state_engine", None) or self.state_engine
            self.block_validator = _BV(_se, self.mempool)
            print("[Node] BlockValidator: block pre-validation ready")
        except Exception as _e:
            self.block_validator = None
            print(f"[Node] BlockValidator: unavailable ({_e})")

        try:
            from crypto.sphincs_plus import SPHINCSPLUS as _SPHINCS
            self.sphincs = _SPHINCS()
            print("[Node] SPHINCS+: interface ready (signing backend required)")
        except Exception as _e:
            self.sphincs = None
            print(f"[Node] SPHINCS+: unavailable ({_e})")

        try:
            from blockchain.canonical_serializer import CanonicalSerializer as _CS
            self.canonical_serializer = _CS()
            print("[Node] CanonicalSerializer: deterministic block hashing ready")
        except Exception as _e:
            self.canonical_serializer = None
            print(f"[Node] CanonicalSerializer: unavailable ({_e})")

        # 34c. Crypto Utilities (Hasher, KeyPair, Signer, TransactionSigner)
        try:
            from crypto.hashing import Hasher as _Hasher
            self.hasher = _Hasher()
            print("[Node] Hasher: crypto hashing utility ready")
        except Exception as _e:
            self.hasher = None
            print(f"[Node] Hasher: unavailable ({_e})")

        try:
            from crypto.keys import KeyGenerator as _KeyGen
            self.key_generator = _KeyGen()
            print("[Node] KeyGenerator: key pair generation ready")
        except Exception as _e:
            self.key_generator = None
            print(f"[Node] KeyGenerator: unavailable ({_e})")

        try:
            from crypto.signing import Signer as _Signer
            self.signer = _Signer()
            print("[Node] Signer: transaction signing utility ready")
        except Exception as _e:
            self.signer = None
            print(f"[Node] Signer: unavailable ({_e})")

        try:
            from crypto.tx_signer import TransactionSigner as _TxSigner
            self.tx_signer = _TxSigner()
            print("[Node] TransactionSigner: advanced TX signing ready")
        except Exception as _e:
            self.tx_signer = None
            print(f"[Node] TransactionSigner: unavailable ({_e})")

        # 35. Finality Engine (standalone observer — consensus uses ConsensusAdapter.finality)
        if _FINALITY_ENGINE_AVAILABLE:
            try:
                self.finality_engine = FinalityEngine()
                print(
                    "[Node] FinalityEngine: standalone observer ready "
                    "(consensus_bound=false — block path uses ConsensusAdapter)"
                )
            except Exception as e:
                self.finality_engine = None
                print(f"[Node] FinalityEngine: unavailable ({e})")
                if self.config.is_production:
                    raise RuntimeError(
                        f"Production mode requires FinalityEngine: {e}"
                    ) from e
        else:
            self.finality_engine = None
            if self.config.is_production:
                raise RuntimeError(
                    "Production mode requires FinalityEngine module"
                )
        # 36. Sync Engine (fast-sync for P2P) — single shared instance for node + P2P
        if _SYNC_ENGINE_AVAILABLE:
            try:
                self.sync_engine = SyncEngine(node=self)
                # Replace any boot-time SyncEngine created inside P2PNode.__init__
                if self.p2p is not None:
                    self.p2p.sync_engine = self.sync_engine
                print("[Node] SyncEngine: fast-sync ready (shared with P2P)")
            except Exception as e:
                self.sync_engine = None
                print(f"[Node] SyncEngine: unavailable ({e})")
                if self.config.is_production:
                    raise RuntimeError(
                        f"Production mode requires SyncEngine: {e}"
                    ) from e
        else:
            self.sync_engine = None
            if self.config.is_production:
                raise RuntimeError(
                    "Production mode requires SyncEngine module"
                )

        self._finalize_boot_state()
        print("[Node] All components initialized.")

    # ── SyncEngine node interface ─────────────────────────────────────────────

    def get_block(self, block_hash: str):
        """Resolve block locally or via P2P peers (for SyncEngine.download_chain)."""
        blk = self.blockchain.get_block_by_hash(block_hash)
        if blk:
            return blk
        if self.p2p and hasattr(self.p2p, "fetch_block_from_peers_sync"):
            return self.p2p.fetch_block_from_peers_sync(block_hash)
        return None

    def import_block(self, block_data: dict) -> bool:
        """Tip-safety-aware import for SyncEngine (ADR 0003 SyncChainPort)."""
        if self.p2p is not None and hasattr(self.p2p, "import_block"):
            return bool(self.p2p.import_block(block_data))
        return bool(self.blockchain.import_block(block_data))

    def get_height(self) -> int:
        return self.blockchain.get_height()

    def request_peer_state_roots_sync(self, timeout: float = 15):
        if self.p2p and hasattr(self.p2p, "request_peer_state_roots_sync"):
            return self.p2p.request_peer_state_roots_sync(timeout)
        return []

    # ── Запуск ───────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True

        # Запускаем API-серверы в отдельных потоках (не блокируют event loop)
        _, self._rpc_server = start_rpc_server_thread(
            self.blockchain, self.mempool, self.config, self.evm,
            p2p=self.p2p, wallet=self.wallet, sync_engine=self.sync_engine,
        )
        # Aliases for audit compatibility
        self.websocket_server = self.ws_server
        self.bot = getattr(self, '_bot_instance', None)

        _, self._http_server = start_http_server_thread(
            self.blockchain, self.mempool, self.db, self.config,
            self.p2p, self.evm, self.nft, self.zk,
            sharding=self.sharding, oracles=self.oracles,
            oracle_registry=self.oracle_registry,
            contract_manager=self.contract_manager,
            assembler=self.assembler,
            pq_manager=self.pq_manager,
            smart_accounts=self.smart_accounts,
            multisig=self.multisig,
            ai_validator=self.ai_validator,
            reorg_predictor=self.reorg_predictor,
            mev_simulator=self.mev_simulator,
            immutable_state=self.immutable_state,
            lightning=self.lightning,
            crypto_will=self.crypto_will,
            plasma=self.plasma,
            wasm_vm=self.wasm_vm,
            ai_manager=self.ai_manager,
            cross_bridge=self.cross_bridge,
            consensus_adapter=self.consensus,
            consensus_engine_standalone=self.consensus_engine_standalone,
            finality_engine=self.finality_engine,
            sync_engine=self.sync_engine,
            state_engine=self.state_engine,
            slashing_engine=self.slashing_engine,
            validator_registry=self.validator_registry,
            epoch_manager=self.epoch_manager,
            beacon_finality=self.beacon_finality,
            lmd_table=self.lmd_table,
            consensus_casper=self.consensus_casper,
            block_validator=self.block_validator,
            sphincs=self.sphincs,
            canonical_serializer=self.canonical_serializer,
            consensus_beacon=self.consensus_beacon,
            consensus_engine_slashing=self.consensus_engine_slashing,
            casper_finality=self.casper_finality,
            pool_locks=self.pool_locks,
            light_client=self.light_client,
            bridge=self.bridge,
            wallet=self.wallet,
            bus=self.bus,
        )
        from api.http import RESTHandler
        RESTHandler.ws_server = self.ws_server
        RESTHandler.apply_queue = self.apply_queue
        RESTHandler.feature_init_errors = dict(self.feature_init_errors)

        self._print_banner()

        # Asyncio задачи
        tasks = []

        # P2P сервер
        tasks.append(asyncio.create_task(self.p2p.start(), name="P2PServer"))
        if getattr(self.config, "follower_genesis_sync", False):
            tasks.append(
                asyncio.create_task(
                    self._follower_genesis_sync_loop(), name="FollowerGenesisSync"
                )
            )
        if self._attestation_validator and self.p2p:
            tasks.append(asyncio.create_task(
                self._announce_validator_loop(), name="ValidatorAnnounce"
            ))

        # Цикл майнинга (если включён)
        if self.config.mining_enabled:
            tasks.append(asyncio.create_task(self._mining_loop(), name="MiningLoop"))

        # Мост (если включён) — NullBridgePort is truthy; gate on config
        if getattr(self.config, "bridge_enabled", False) and self.bridge:
            tasks.append(asyncio.create_task(self.bridge.start(), name="BridgeLoop"))

        # WebSocket сервер (порт 8546)
        tasks.append(asyncio.create_task(self.ws_server.start(), name="WebSocketServer"))

        # Blockchain Monitor — per-node port (8092 node1, 8093 node2)
        self.monitor = None
        if self.config.monitor_enabled:
            try:
                from monitor import MonitorServer
                _mon_port = self.config.resolved_monitor_port()
                _api_url = f"http://127.0.0.1:{self.config.http_port}"
                self.monitor = MonitorServer(
                    api_url=_api_url,
                    port=_mon_port,
                    node_id=self.config.node_id,
                )
                self.monitor.start()
                print(f"[Monitor] Health monitor started: http://localhost:{_mon_port}")
            except Exception as exc:
                self.monitor = None
                print(f"[Monitor] Health monitor failed: {exc}")

        # RPC CORS Proxy — per-node port (8082 node1, 8083 node2)
        if self.config.enable_cors_rpc_proxy:
            try:
                import threading as _threading
                from http.server import HTTPServer as _HTTPServer, BaseHTTPRequestHandler as _BH
                import json as _json_mod
                _rpc_port = self.config.rpc_port
                _proxy_port = self.config.resolved_rpc_proxy_port()
                _cors_origins = list(getattr(self.config, "cors_origins", []) or [])
                if self.config.is_production and (
                    not _cors_origins or "*" in _cors_origins
                ):
                    raise RuntimeError(
                        "prod CORS RPC proxy requires explicit CORS_ORIGINS (no *)"
                    )

                def _proxy_cors_origin(request_origin: str) -> str:
                    # Match REST CORS honesty: never echo first allowlist entry on miss.
                    from api.http import _resolve_cors_allow_origin
                    return _resolve_cors_allow_origin(self.config, request_origin)

                _proxy_max_body = int(
                    getattr(self.config, "http_max_body_bytes", 1_048_576) or 1_048_576
                )

                class _CORSProxy(_BH):
                    def do_OPTIONS(self):
                        allow = _proxy_cors_origin(self.headers.get("Origin", ""))
                        self.send_response(200)
                        if allow:
                            self.send_header("Access-Control-Allow-Origin", allow)
                        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                        self.send_header("Access-Control-Allow-Headers", "Content-Type")
                        self.end_headers()
                    def do_POST(self):
                        import requests as _req
                        cl = int(self.headers.get("Content-Length", 0) or 0)
                        allow = _proxy_cors_origin(self.headers.get("Origin", ""))
                        if cl < 0 or cl > _proxy_max_body:
                            data = _json_mod.dumps(
                                {"error": "request body too large"}
                            ).encode()
                            self.send_response(413)
                            self.send_header("Content-Type", "application/json")
                            if allow:
                                self.send_header("Access-Control-Allow-Origin", allow)
                            self.send_header("Content-Length", len(data))
                            self.end_headers()
                            try:
                                self.wfile.write(data)
                            except Exception:
                                pass
                            return
                        body = self.rfile.read(cl)
                        status = 200
                        try:
                            resp = _req.post(
                                f"http://localhost:{_rpc_port}", data=body,
                                headers={"Content-Type": "application/json"}, timeout=5,
                            )
                            data = resp.content
                            status = int(resp.status_code or 200)
                        except Exception as e:
                            status = 502
                            data = _json_mod.dumps({"error": str(e)}).encode()
                        self.send_response(status)
                        self.send_header("Content-Type", "application/json")
                        if allow:
                            self.send_header("Access-Control-Allow-Origin", allow)
                        self.send_header("Content-Length", len(data))
                        self.end_headers()
                        try:
                            self.wfile.write(data)
                        except Exception:
                            pass
                    def log_message(self, *a):
                        pass
                _proxy = _HTTPServer(("127.0.0.1", _proxy_port), _CORSProxy)
                _threading.Thread(target=_proxy.serve_forever, daemon=True, name="RPCProxy").start()
                print(f"[RPC Proxy] CORS proxy started: http://localhost:{_proxy_port}/rpc -> :{_rpc_port}")
            except Exception as exc:
                print(f"[RPC Proxy] CORS proxy unavailable: {exc}")
        else:
            print("[RPC Proxy] Disabled (ENABLE_CORS_RPC_PROXY=false or prod mode)")

        # Telegram Bot — автозапуск если TELEGRAM_BOT_TOKEN установлен
        import os as _os
        _tg_token = _os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        try:
            from runtime.secret_utils import is_placeholder_secret
            _tg_placeholder = is_placeholder_secret(_tg_token)
        except ImportError:
            _tg_placeholder = _tg_token.lower().startswith("your_")
        if _tg_token and not _tg_placeholder:
            try:
                import threading as _threading
                # BOT_TOKEN is read at module import time from env — already set above
                from telegram_super_bot import AbsoluteBot as _TGBot
                _bot = _TGBot()
                _tg_t = _threading.Thread(target=_bot.run, daemon=True, name="TelegramBot")
                _tg_t.start()
                print(f"[Telegram] Bot started (token: {_tg_token[:8]}...)")
            except Exception as _te:
                print(f"[Telegram] Bot unavailable: {_te}")
        elif _tg_token and _tg_placeholder:
            print("[Telegram] Skipped — TELEGRAM_BOT_TOKEN is placeholder in .env")
        else:
            print("[Telegram] Bot ready — set TELEGRAM_BOT_TOKEN in .env to activate")

        # Обработка tx из мемпула (периодическое включение в блок)
        tasks.append(asyncio.create_task(self._mempool_monitor(), name="MempoolMonitor"))

        self._tasks = tasks

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            # If a signal already drained storage, do not leave gather orphans
            # blocking interpreter shutdown (native accept to_thread).
            pending = [t for t in tasks if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                try:
                    await asyncio.wait(pending, timeout=2.0)
                except Exception:
                    pass

    async def _announce_validator_loop(self):
        """Gossip attestation validator to peers once P2P is up (dev only)."""
        mode = str(getattr(self.config, "deployment_mode", "dev") or "dev").lower()
        if mode in ("prod", "production", "staging") or bool(
            getattr(self.config, "require_native_crypto", False)
        ):
            # Ceremony/manifest owns validator set — P2P register is fail-closed.
            return
        await asyncio.sleep(8)
        while self._running:
            if self.p2p and self._attestation_validator:
                self.p2p.announce_validator(
                    self._attestation_validator, self.config.min_stake
                )
            await asyncio.sleep(60)

    def _apply_genesis_allocation(self) -> None:
        """Credit genesis pools after wallet/config founder address is known."""
        try:
            from runtime.tokenomics import (
                FOUNDER_AMOUNT_ABS,
                genesis_balances,
                get_tokenomics_summary,
                resolve_founder_address,
            )
            # Followers must not mint a local alloc before importing leader genesis —
            # per-wallet founder credits diverge state_root/hash and break import.
            if (
                getattr(self.config, "follower_genesis_sync", False)
                and self.blockchain.get_last_block() is None
            ):
                print(
                    "[Node] follower_genesis_sync: defer genesis allocation "
                    "until leader block #0 is imported"
                )
                return
            founder = resolve_founder_address(
                getattr(self.config, "founder_address", ""),
                self.config.miner_address,
            )
            blk0 = self.db.get_block(0) if hasattr(self.db, "get_block") else None
            if blk0:
                if not self.db.get_meta("genesis_alloc_applied"):
                    self.db.set_meta("genesis_alloc_applied", True)
                if not self.db.get_meta("tokenomics"):
                    self.db.set_meta("tokenomics", get_tokenomics_summary(founder or None))
                return
            if not self.db.get_meta("genesis_alloc_applied"):
                alloc = genesis_balances(founder or None)
                for addr, amount in alloc.items():
                    if isinstance(amount, bool):
                        raise TypeError("bool is not an amount")
                    cur = self.db.get_balance(addr)
                    if cur < amount * 0.99:
                        self.db.set_balance(addr, int(amount))
                self.db.set_meta("genesis_alloc_applied", True)
                self.db.set_meta("tokenomics", get_tokenomics_summary(founder or None))
                print(
                    f"[Node] Genesis allocation applied "
                    f"(founder {FOUNDER_AMOUNT_ABS:,.0f} ABS -> {founder})"
                )
                return
            expected = int(genesis_balances(founder or None).get(founder, FOUNDER_AMOUNT_ABS))
            cur = self.db.get_balance(founder)
            if cur < expected * 0.99:
                self.db.set_balance(founder, int(expected))
                print(f"[Node] Founder wallet synced: {expected:,.0f} ABS -> {founder}")
        except Exception as exc:
            _node_log.warning("Genesis allocation failed: %s", exc)
            if str(getattr(self.config, "deployment_mode", "")).lower() == "prod":
                raise
            print(f"[Node] Genesis allocation note: {exc}")

    def _pin_chain_founder_address(self) -> None:
        """Mesh followers must replay genesis with the miner's founder, not local wallet."""
        pinned = ""
        try:
            pinned = str(self.db.get_meta("genesis_founder") or "").strip()
        except Exception as exc:
            _node_log.warning("genesis_founder meta read failed: %s", exc)
            pinned = ""
        if not pinned:
            try:
                tok = self.db.get_meta("tokenomics")
                if isinstance(tok, dict):
                    pinned = str((tok.get("founder") or {}).get("address", "") or "").strip()
            except Exception as exc:
                _node_log.warning("tokenomics founder meta read failed: %s", exc)
                pinned = ""
        manifest = getattr(self.config, "validators_manifest_path", "") or ""
        if not pinned and manifest and os.path.isfile(manifest):
            try:
                from runtime.validator_loader import manifest_founder_address

                pinned = manifest_founder_address(manifest)
            except Exception as exc:
                _node_log.warning("manifest founder resolve failed (%s): %s", manifest, exc)
                pinned = ""
        if pinned:
            if (
                getattr(self.config, "founder_address", "")
                and self.config.founder_address.lower() != pinned.lower()
            ):
                print(
                    f"[Node] Founder pinned to genesis/manifest: {pinned[:12]}… "
                    f"(local wallet is signing-only)"
                )
            self.config.founder_address = pinned

    def _finalize_boot_state(self) -> None:
        """Align live state with tip metadata after all boot-time DB mutations."""
        if self.blockchain.get_height() >= 0:
            self.blockchain.ensure_state_at_tip()
        if not self.pool_locks:
            return
        h = self.blockchain.get_height()
        if h <= 0 or not self.config.mining_enabled:
            if h > 0 and not self.config.mining_enabled:
                print("[Node] Staking catch-up skipped (follower node)")
            return
        try:
            from consensus.epoch import EpochManager as _EpCatch
            _ep = _EpCatch(epoch_size=getattr(self.config, "epoch_size", 32))
            catch = self.pool_locks.catch_up_epochs(_ep.get_epoch(h))
            if catch.get("staking_released_total", 0) > 0:
                print(
                    f"[Node] Staking catch-up: +{catch['staking_released_total']:,.0f} "
                    f"ABS released (pool meta only)"
                )
        except Exception as _catch_err:
            print(f"[Node] Staking catch-up note: {_catch_err}")

    # ── Остановка (ADR 0014 graceful shutdown) ───────────────────────────────

    def stop(self, *, force_process_exit: bool = False):
        """Ordered drain: refuse RPC → stop listeners → cancel workers → RocksDB clean close.

        Safe to call from the event loop and ``finally``. Idempotent.

        ``force_process_exit``: after clean close, ``os._exit(0)`` so a stuck
        ``asyncio.to_thread`` native accept cannot keep the PID alive (K8s SIGTERM).
        """
        if getattr(self, "_shutting_down", False):
            if force_process_exit:
                os._exit(0)
            return
        if not self._running and getattr(self, "_http_server", None) is None:
            # Never started — nothing to drain.
            if force_process_exit:
                os._exit(0)
            return
        self._shutting_down = True
        self._running = False
        print("\n[Node] Shutting down (graceful)...")

        # 1) Stop accepting new RPC/REST (K8s readiness flips to 503).
        try:
            set_accepting_requests(False)
        except Exception as exc:
            _node_log.warning("set_accepting_requests failed: %s", exc)

        # 2) Stop HTTP/RPC servers (no new sockets).
        shutdown_http_server(getattr(self, "_http_server", None), "HTTP")
        shutdown_http_server(getattr(self, "_rpc_server", None), "RPC")
        self._http_server = None
        self._rpc_server = None

        # 3) WebSocket + monitor (best-effort).
        ws = getattr(self, "ws_server", None)
        if ws is not None and hasattr(ws, "stop"):
            try:
                ws.stop()
            except Exception as exc:
                _node_log.warning("websocket stop failed: %s", exc)
        mon = getattr(self, "monitor", None)
        if mon is not None and hasattr(mon, "stop"):
            try:
                mon.stop()
            except Exception as exc:
                _node_log.warning("monitor stop failed: %s", exc)

        # 4) Cancel asyncio tasks (mining / P2P loops / bridge).
        for task in list(getattr(self, "_tasks", []) or []):
            if not task.done():
                task.cancel()

        # 5) Tear down P2P (close peers + listeners) before storage.
        p2p = getattr(self, "p2p", None)
        if p2p is not None and hasattr(p2p, "stop"):
            try:
                p2p.stop()
            except Exception as exc:
                _node_log.warning("p2p stop failed: %s", exc)

        aq = getattr(self, "apply_queue", None)
        if aq is not None:
            try:
                aq.stop()
            except Exception as exc:
                _node_log.warning("apply_queue stop failed: %s", exc)
        se = getattr(self, "sync_executor", None)
        if se is not None:
            # Don't block drain on a wedged sync worker — cancel and move on.
            try:
                se.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                try:
                    se.shutdown(wait=False)
                except Exception as exc:
                    _node_log.warning("sync_executor shutdown failed: %s", exc)
            except Exception as exc:
                _node_log.warning("sync_executor shutdown failed: %s", exc)
        if getattr(self, "bridge", None):
            try:
                self.bridge.stop()
            except Exception as exc:
                _node_log.warning("bridge stop failed: %s", exc)

        # 6) Storage last — waits WriteBatch lock, then RocksDB clean close.
        for label, obj in (
            ("storage", getattr(self, "storage", None)),
            ("database", getattr(self, "db", None)),
        ):
            if obj is None or not hasattr(obj, "close"):
                continue
            try:
                obj.close()
                print(f"[Node] {label} closed")
            except Exception as exc:
                _node_log.warning("%s close failed: %s", label, exc)

        print("[Node] Goodbye.")
        if force_process_exit:
            # Bypass stuck asyncio.to_thread(native accept) keeping the PID alive.
            os._exit(0)

    # ── Цикл майнинга ────────────────────────────────────────────────────────

    async def _follower_genesis_sync_loop(self):
        """Prod followers: import block #0 from artifact / bootstrap / P2P before RPC ready."""
        if not getattr(self.config, "follower_genesis_sync", False):
            return
        if self.blockchain.get_last_block() is not None:
            return
        if not self.config.bootstrap_peers:
            print("[Node] follower_genesis_sync requires bootstrap_peers")
            if self.config.is_production:
                self._running = False
            return

        print("[Node] follower_genesis_sync: waiting for leader genesis...")
        deadline = time.time() + 180
        while self._running and time.time() < deadline:
            if self.blockchain.get_last_block() is not None:
                print("[Node] follower genesis ready")
                return
            # Shared ceremony artifact (leader export / host bind) beats flaky P2P.
            try:
                if self.blockchain.try_import_genesis_artifact():
                    print("[Node] follower genesis ready (ceremony artifact)")
                    return
            except Exception as exc:
                print(f"[Node] follower genesis artifact: {exc}")
            if self.sync_engine and self.p2p:
                try:
                    if len(getattr(self.p2p, "peers", {}) or {}) > 0:
                        await asyncio.to_thread(self.sync_engine.fast_sync)
                except Exception as exc:
                    print(f"[Node] follower genesis sync: {exc}")
            await asyncio.sleep(3)

        if self.blockchain.get_last_block() is None:
            print("[Node] FATAL: follower_genesis_sync timeout without leader genesis")
            if self.config.is_production:
                self._running = False

    async def _mining_loop(self):
        """
        Каждые block_time секунд форжит новый блок если:
          1. Наступил нужный момент (consensus.should_produce_block)
          2. Есть транзакции в мемпуле ИЛИ прошло > block_time с последнего блока
        """
        print(f"[Mining] Loop started. Block time: {self.config.block_time}s")

        while self._running:
            await asyncio.sleep(1)  # проверяем каждую секунду

            if not self.consensus.should_produce_block():
                continue

            _min_mesh_peers = int(getattr(self.config, "mesh_min_peers_before_mine", 0) or 0)
            peers = getattr(self.p2p, "peers", {}) or {} if self.p2p else {}
            connected = len(peers)
            # Peers present require consistency even when mesh_min_peers_before_mine=0.
            if self.p2p and (connected > 0 or _min_mesh_peers > 0):
                if _min_mesh_peers > 0 and connected < _min_mesh_peers:
                    continue
                if connected == 0:
                    continue
                local_h = self.blockchain.get_height()
                local_root = str(self.blockchain.get_state_root() or "")
                if not getattr(self.p2p, "_state_consistent", False) and self.sync_engine:
                    try:
                        loop = asyncio.get_running_loop()
                        ex = getattr(self, "sync_executor", None) or getattr(
                            self.p2p, "sync_executor", None
                        )
                        await loop.run_in_executor(ex, self.sync_engine.sync_state)
                    except Exception as _sync_probe_err:
                        print(f"[Mining] sync_state probe failed: {_sync_probe_err}")
                        if hasattr(self.p2p, "force_inconsistent"):
                            self.p2p.force_inconsistent("mining_probe_failed")
                        else:
                            self.p2p._state_consistent = False
                if connected > 0 and not getattr(self.p2p, "_state_consistent", False):
                    continue
                if _min_mesh_peers > 0:
                    peer_heights = [
                        int(getattr(p, "height", 0) or 0) for p in peers.values()
                    ]
                    from runtime.mesh_mining import mesh_ready_for_mining

                    wire_roots = []
                    try:
                        wire_roots = await self.p2p.request_peer_state_roots()
                    except Exception as exc:
                        print(f"[Mining] request_peer_state_roots failed: {exc}")
                        wire_roots = []
                        if bool(getattr(self.config, "is_production", False)):
                            if hasattr(self.p2p, "force_inconsistent"):
                                self.p2p.force_inconsistent("mining_wire_roots_failed")
                            else:
                                self.p2p._state_consistent = False

                    hold_h = int(getattr(self, "_mesh_forge_hold_height", 0) or 0)
                    if hold_h and local_h >= hold_h:
                        local_root_hold = local_root
                        matching_hold = sum(
                            1
                            for entry in wire_roots
                            if int(entry.get("height", 0) or 0) == local_h
                            and str(entry.get("state_root") or "").strip().lower()
                            == local_root_hold.strip().lower()
                        )
                        if matching_hold < _min_mesh_peers:
                            continue
                        self._mesh_forge_hold_height = 0

                    if not mesh_ready_for_mining(
                        min_mesh_peers=_min_mesh_peers,
                        connected_peers=connected,
                        wire_roots=wire_roots,
                        local_height=local_h,
                        local_root=local_root,
                        state_consistent=bool(getattr(self.p2p, "_state_consistent", False)),
                        peer_heights=peer_heights,
                    ):
                        continue

            if self.sharding and hasattr(self.sharding, "process_cross_shard_transactions"):
                try:
                    self.sharding.process_cross_shard_transactions()
                except Exception as exc:
                    _node_log.warning("[Mining] cross-shard processing failed: %s", exc)

            # ── Proposer: solo operational wallet OR RANDAO when multiple validators ──
            proposer = None
            _signing = getattr(self.config, "signing_address", "")
            _active_vals = self.db.get_validators(active_only=True) if self.db else []
            _multi_validator_devnet = int(
                getattr(self.config, "testnet_expected_validators", 0) or 0
            ) >= 3
            from runtime.devnet_validators import (
                mining_validator_addresses,
                resolve_manifest_path,
            )
            _mf = getattr(self.config, "validators_manifest_path", "") or ""
            if not (_mf and os.path.isfile(_mf)):
                _mf = resolve_manifest_path(self.config) if _multi_validator_devnet else ""
            _founder = getattr(self.config, "founder_address", "") or ""
            _mine_only = mining_validator_addresses(_mf, _founder) if _mf else set()
            if _signing and self.wallet and len(_active_vals) <= 1:
                proposer = _signing

            # 1) RANDAO-style selection if validators registered
            if not proposer and self.validator_selection and self.db:
                try:
                    validators_dict = {v["address"]: v.get("stake", 100)
                                       for v in (self.db.get_validators() or [])}
                    if validators_dict and _mine_only:
                        validators_dict = {
                            k: v
                            for k, v in validators_dict.items()
                            if k.lower() in _mine_only
                        }
                    # Docker prod mesh: only node1 mines; followers use follower_genesis_sync.
                    if (
                        validators_dict
                        and self.config.mining_enabled
                        and not getattr(self.config, "follower_genesis_sync", False)
                        and _signing
                    ):
                        validators_dict = {
                            k: v
                            for k, v in validators_dict.items()
                            if k.lower() == _signing.lower()
                        }
                    if validators_dict:
                        slot = getattr(self.consensus, "engine", None)
                        slot_n = getattr(slot, "current_slot", 0) if slot else 0
                        proposer = self.validator_selection.select_proposer_weighted(
                            validators_dict, slot_n
                        )
                except Exception as exc:
                    print(f"[Mining] select_proposer_weighted failed: {exc}")
                    if bool(getattr(self.config, "is_production", False)):
                        # Fail closed: skip this tick rather than forging with a weak fallback.
                        await asyncio.sleep(0.5)
                        continue

            # 2) Consensus adapter fallback (deterministic stake-weighted)
            if not proposer:
                proposer = self.consensus.select_proposer()
            if not proposer:
                proposer = self.config.miner_address or "genesis"

            if _mine_only and proposer.lower() not in _mine_only:
                    _eligible = [
                        v["address"]
                        for v in (_active_vals or [])
                        if v["address"].lower() in _mine_only
                    ]
                    if _eligible:
                        slot = getattr(self.consensus, "engine", None)
                        slot_n = getattr(slot, "current_slot", 0) if slot else 0
                        proposer = _eligible[slot_n % len(_eligible)]

            if (
                self.config.mining_enabled
                and _signing
                and not getattr(self.config, "follower_genesis_sync", False)
            ):
                proposer = _signing
            elif len(_active_vals) > 1:
                _local = set()
                for _a in (
                    getattr(self.config, "signing_address", ""),
                    self.config.miner_address,
                    getattr(self, "_attestation_validator", "") or "",
                ):
                    if _a:
                        _local.add(_a.lower())
                if self.wallet and self.wallet.address:
                    _local.add(self.wallet.address.lower())
                if proposer.lower() not in _local:
                    continue

            # ── PBS fee-bid simulation (not MEV protection; no reorder) ───────
            try:
                pending_dicts = [{"hash": t.tx_hash, "from": t.from_addr, "to": t.to_addr,
                                  "value": t.amount, "gasPrice": int(t.fee * 1e9),
                                  "gas": int(getattr(t, "gas", 0) or 21000),
                                  "nonce": t.nonce,
                                  "data": getattr(t, "data", "") or "",
                                  "timestamp": t.timestamp,
                                  "gas_price": int(t.fee * 1e9)}
                                 for t in self.mempool.get(limit=self.config.max_tx_per_block)]
                # Fee-bid auction result is observational only (ordering_applied=false).
                self.consensus.run_pbs_auction(pending_dicts)
            except Exception as exc:
                _node_log.warning("[Mining] PBS auction failed: %s", exc)

            # ── Get mempool transactions (mempool order; PBS does not reorder) ─
            pending = self.mempool.get(limit=self.config.max_tx_per_block)

            # ── MEV scan (monitoring only; PBS is fee-bid simulation) ─────────
            if self.mev_simulator and len(pending) >= 2:
                try:
                    from features.mev_analyzer import Transaction as MevTx
                    mev_txs = [MevTx(mp_tx.tx_hash, mp_tx.from_addr, mp_tx.to_addr,
                                     mp_tx.amount, int(mp_tx.fee * 1e9), int(mp_tx.timestamp))
                               for mp_tx in pending[:10]]
                    self.mev_simulator.detect_sandwich_opportunity(mev_txs)
                except Exception as exc:
                    _node_log.debug("[Mining] MEV scan failed: %s", exc)

            # ── Конвертируем MempoolTransaction → Transaction ─────────────────
            txs = []
            for mp_tx in pending:
                tx_gas = int(getattr(mp_tx, "gas", 0) or 0)
                if not tx_gas:
                    tx_gas = (
                        self.config.evm_gas_limit
                        if getattr(mp_tx, "data", "")
                        else self.config.base_gas_price
                    )
                txs.append(Transaction(
                    from_addr=mp_tx.from_addr,
                    to_addr=mp_tx.to_addr,
                    value=mp_tx.amount,
                    nonce=mp_tx.nonce,
                    gas=tx_gas,
                    data=getattr(mp_tx, "data", "") or "",
                    timestamp=int(mp_tx.timestamp),
                    tx_hash=mp_tx.tx_hash,
                    signature=mp_tx.signature,
                    public_key=mp_tx.public_key,
                ))

            # Обновляем miner_address в конфиге если задан
            if proposer != "genesis":
                self.config.miner_address = proposer

            def _sign_block(blk):
                if not self.validator_keys:
                    return
                try:
                    block_dict = {
                        "hash": blk.hash,
                        "number": blk.height,
                        "proposer": proposer,
                        "timestamp": blk.timestamp,
                    }
                    blk.signature = self.validator_keys.sign_block(block_dict)
                except Exception as exc:
                    _node_log.warning(
                        "Block signing failed (height=%s): %s",
                        getattr(blk, "height", "?"),
                        exc,
                    )
                    if bool(getattr(self.config, "is_production", False)):
                        raise RuntimeError(
                            f"Production mode requires block signature: {exc}"
                        ) from exc

            # Atomic create+sign+add relative to P2P import (ChainApplyQueue).
            aq = getattr(self, "apply_queue", None)
            reject_before = int(getattr(aq, "reject_total", 0) or 0) if aq else 0
            if aq is not None:
                success, block = await aq.submit_forge_and_apply_async(
                    txs, proposer, _sign_block
                )
            else:
                block = self.blockchain.create_block(txs, proposer)
                _sign_block(block)
                success = await asyncio.to_thread(self.blockchain.add_block, block)

            if not success and txs:
                if aq is not None and int(aq.reject_total) > reject_before:
                    print("[Mining] apply queue backpressure — skip forge tick")
                    continue
                print(
                    f"[Mining] Block with {len(txs)} tx(s) rejected; evicting and forging empty block"
                )
                for tx in txs:
                    self.mempool.remove(tx.hash)
                reject_before = int(getattr(aq, "reject_total", 0) or 0) if aq else 0
                if aq is not None:
                    success, block = await aq.submit_forge_and_apply_async(
                        [], proposer, _sign_block
                    )
                else:
                    block = self.blockchain.create_block([], proposer)
                    _sign_block(block)
                    success = await asyncio.to_thread(self.blockchain.add_block, block)

            if not success or block is None:
                if aq is not None and int(aq.reject_total) > reject_before:
                    print("[Mining] apply queue backpressure — skip forge tick")
                continue

            if int(getattr(self.config, "mesh_min_peers_before_mine", 0) or 0) > 0:
                self._mesh_forge_hold_height = int(block.height)
            # Удаляем включённые транзакции из мемпула
            for tx in block.transactions:
                self.mempool.remove(tx.hash)

            # LMD-GHOST: attest at current slot, then advance for next block
            try:
                self.consensus.attest(proposer, block.hash)
            except Exception as exc:
                logger = getattr(self, "logger", None) or __import__("logging").getLogger("Node")
                logger.error(
                    "Consensus attest failed (height=%s hash=%s): %s",
                    getattr(block, "height", "?"),
                    getattr(block, "hash", "?"),
                    exc,
                )
                if bool(getattr(self.config, "is_production", False)):
                    raise

            self.consensus.mark_block_produced(proposer=proposer)

            self._log_block(block)

            if self.p2p and self.p2p._loop and self.p2p._running:
                try:
                    # Record forge height before gossip so inbound echo cannot
                    # hit dispatcher tip-evidence with a stale AncestryWindow.
                    note = getattr(self.p2p, "note_local_forge", None)
                    if callable(note):
                        note(1.0, height=int(getattr(block, "height", 0) or 0))
                    await self.p2p._broadcast_block(block.to_dict())
                except Exception as exc:
                    print(f"[Mining] broadcast_block failed: {exc}")

            if self.sync_engine and self.p2p:
                try:
                    loop = asyncio.get_running_loop()
                    ex = getattr(self, "sync_executor", None) or getattr(
                        self.p2p, "sync_executor", None
                    )
                    loop.run_in_executor(ex, self.sync_engine.sync_state)
                except Exception as exc:
                    print(f"[Mining] sync_state schedule failed: {exc}")
                    if bool(getattr(self.config, "is_production", False)):
                        if hasattr(self.p2p, "force_inconsistent"):
                            self.p2p.force_inconsistent("mining_sync_schedule_failed")
                        else:
                            self.p2p._state_consistent = False

            # Deterministic proposer entropy mix (not commit/reveal RANDAO)
            if self.validator_selection:
                self.validator_selection.update_seed(block.hash)

            # AI Validator: обновляем performance proposer'а
            if self.ai_validator:
                self.ai_validator.update_performance(proposer, success=True)

            # ImmutableState: mirror DB satoshi after L1 apply (fees/rewards/burns)
            if self.immutable_state:
                try:
                    addrs = set()
                    for tx in block.transactions:
                        if getattr(tx, "from_addr", None):
                            addrs.add(tx.from_addr)
                        if getattr(tx, "to_addr", None):
                            addrs.add(tx.to_addr)
                    addrs.add(proposer)
                    burn = getattr(self.config, "burn_address", None)
                    if burn:
                        addrs.add(burn)
                    n = self.immutable_state.reconcile_from_store(
                        self.db,
                        addrs,
                        fail_loud=bool(getattr(self.config, "is_production", False)),
                    )
                    if n < 0:
                        raise RuntimeError("IMS reconcile_from_store returned failure")
                except Exception as _ims_err:
                    print(f"[ImmutableState] reconcile_from_store failed: {_ims_err}")
                    if getattr(self.config, "is_production", False):
                        raise

            # Light client: новый заголовок
            if self.light_client:
                try:
                    from core.block_header import BlockHeader
                    self.light_client.add_header(BlockHeader.from_block_dict(block.to_dict()))
                except Exception as exc:
                    _node_log.warning("[Mining] light client header add failed: %s", exc)

            # Epoch boundary: разблокировка staking-пула
            if self.epoch_manager and self.pool_locks:
                try:
                    if self.epoch_manager.is_epoch_boundary(block.height):
                        ep = self.epoch_manager.get_epoch(block.height)
                        rel = self.pool_locks.on_epoch_boundary(ep)
                        delta = rel.get("staking_released_delta", 0)
                        if delta > 0:
                            print(f"[Epoch] #{ep}: staking +{delta:,.0f} ABS released")
                except Exception as exc:
                    _node_log.warning("[Mining] epoch pool unlock failed: %s", exc)

            # ChainStorage: JSON backup (non-authoritative; failures must be visible)
            if self.chain_storage:
                try:
                    block_dict = {
                        "number": block.height,
                        "hash": block.hash,
                        "parent_hash": block.parent_hash,
                        "timestamp": block.timestamp,
                        "proposer": proposer,
                        "tx_count": len(block.transactions),
                    }
                    ok_backup = self.chain_storage.save_block(block.height, block_dict)
                    if not ok_backup:
                        print(
                            f"[ChainStorage] WARN: backup save failed for height={block.height}"
                        )
                except Exception as exc:
                    print(f"[ChainStorage] backup save error height={block.height}: {exc}")

    async def _mempool_monitor(self):
        """Периодически логирует статус мемпула."""
        while self._running:
            await asyncio.sleep(60)
            stats = self.mempool.get_stats()
            if stats["size"] > 0:
                print(f"[Mempool] size={stats['size']} "
                      f"avg_fee={stats['avg_fee']:.6f} ABS")

    # ── Вывод ─────────────────────────────────────────────────────────────────

    def _print_banner(self):
        tip = self.db.get_chain_tip()
        burned = self.db.get_total_burned()
        validators = len(self.db.get_validators())
        state_root = self.blockchain.get_state_root() if hasattr(self.blockchain, "get_state_root") else ""
        consensus_stats = self.consensus.get_stats()
        sep = "-" * 62
        shards_str = f"{self.sharding.num_shards} shards" if self.sharding else "off"
        oracles_str = "on" if self.oracles else "off"
        pq_str = "SPHINCS+" if _POSTQUANTUM_AVAILABLE else "off"
        multisig_str = "on" if _MULTISIG_AVAILABLE else "off"
        sa_str = "on" if self.smart_accounts else "off"
        ln_str = "on" if self.lightning else "off"
        plasma_str = "on" if self.plasma else "off"
        wasm_str = "on" if self.wasm_vm else "off"
        will_str = "on" if self.crypto_will else "off"
        lines = [
            "",
            "+" + sep + "+",
            f"|  ABSOLUTE BLOCKCHAIN NODE  v{self.config.node_version:<10}                      |",
            "+" + sep + "+",
            f"|  Chain      : {self.config.network_name:<16}  Chain ID : {self.config.chain_id:<10}      |",
            f"|  Supply     : max={self.config.max_supply:,} ABS  founder={getattr(self.config,'founder_initials','D.U.P.')} {getattr(self.config,'founder_percent',17.4)}% |",
            f"|  Founder    : {getattr(self.config,'founder_name','Uladzimir Dabranski'):<45} |",
            f"|  Height     : {str(tip):<45} |",
            f"|  Burned     : {f'{burned:.4f} {self.config.coin_symbol}':<45} |",
            f"|  Validators : {str(validators):<45} |",
            f"|  State Root : {(state_root[:32] + '...' if len(state_root) > 32 else state_root or 'n/a'):<45} |",
            "+" + sep + "+",
            f"|  Consensus  : LMD-GHOST={consensus_stats.get('lmd_ghost_enabled', False)}  PBS={consensus_stats.get('pbs_enabled', False)}  Slashing=yes  |",
            f"|  Features   : Sharding={shards_str}  Oracles={oracles_str}  PQ={pq_str}       |",
            f"|  Wallets    : Multisig={multisig_str}  SmartAccounts={sa_str}                  |",
            f"|  L2/Bridge  : Lightning={ln_str}  Plasma={plasma_str}  WASM={wasm_str}  Will={will_str}  |",
            "+" + sep + "+",
            f"|  JSON-RPC  ->  http://localhost:{self.config.rpc_port:<30}|",
            f"|  Explorer  ->  http://localhost:{self.config.http_port:<30}|",
            f"|  WebSocket ->  ws://localhost:{getattr(self.config,'ws_port',8546):<31}|",
            f"|  P2P       ->  0.0.0.0:{self.config.p2p_port:<38}|",
            "+" + sep + "+",
            "",
        ]
        print("\n".join(lines))

    def _log_block(self, block):
        burned_str = f"{block.total_burned:.4f}" if block.total_burned > 0 else "0"
        print(
            f"[BLOCK #{block.height:>6}] "
            f"hash={block.hash[:12]}... "
            f"txs={len(block.transactions):>3}  "
            f"burned={burned_str} ABS"
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI аргументы
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Absolute Blockchain Node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "miner", "validator", "rpc-only"],
        default="full",
        help="Режим работы узла (default: full)",
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="FILE",
        help="Путь к JSON-файлу конфигурации",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="P2P-порт (переопределяет конфиг)",
    )
    parser.add_argument(
        "--rpc-port",
        type=int,
        default=None,
        metavar="PORT",
        help="JSON-RPC порт (default: 8545)",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=None,
        metavar="PORT",
        help="REST API порт (default: 8080)",
    )
    parser.add_argument(
        "--peers",
        nargs="+",
        default=[],
        metavar="HOST:PORT",
        help="Список bootstrap-пиров",
    )
    parser.add_argument(
        "--miner",
        default=None,
        metavar="ADDRESS",
        help="Адрес кошелька для получения наград",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="DIR",
        help="Директория для данных (БД, логи)",
    )
    parser.add_argument(
        "--no-bridge",
        action="store_true",
        help="Отключить кросс-чейн мост",
    )
    parser.add_argument(
        "--no-evm",
        action="store_true",
        help="Отключить EVM",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Уровень логирования",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> Config:
    """Строит Config: .env → JSON-файл → CLI (последний побеждает)."""
    config = Config()

    # 1) Глобальные значения из .env / окружения
    try:
        from runtime.env_loader import load_dotenv_file
        load_dotenv_file(os.path.join(BASE_DIR, ".env"))
    except Exception as exc:
        _node_log.debug(".env load skipped: %s", exc)
    config.apply_env()

    # 2) JSON-файл узла (перекрывает .env — важно для node2 на других портах).
    # Only overlay keys present in the file — Config.from_json() fills missing
    # fields with dataclass defaults (e.g. feature_minivm=True), which would
    # undo prod fail-closed values from apply_env().
    if args.config and os.path.exists(args.config):
        with open(args.config, "r", encoding="utf-8") as f:
            file_data = json.load(f)
        for key, value in file_data.items():
            if hasattr(config, key) and not str(key).startswith("_"):
                setattr(config, key, value)
        print(f"[Config] Loaded from: {args.config}")

    # Credentials from env must survive JSON merge (node JSON does not store secrets).
    config.apply_env_secrets()
    config.resolve_storage_paths()

    # 3) CLI — высший приоритет
    if args.port:
        config.p2p_port = args.port
    if args.rpc_port:
        config.rpc_port = args.rpc_port
    if args.http_port:
        config.http_port = args.http_port
    if args.peers:
        config.bootstrap_peers = args.peers
    if args.miner:
        config.miner_address = args.miner
    if args.data_dir:
        config.db_path = os.path.join(args.data_dir, "blockchain.db")
        config.log_file = os.path.join(args.data_dir, "node.log")
    if args.no_bridge:
        config.bridge_enabled = False
    if args.no_evm:
        config.evm_enabled = False
    if args.log_level:
        config.log_level = args.log_level

    errors = config.validate()
    if errors and config.is_production:
        for e in errors:
            print(f"[Config] ERROR: {e}")
        raise SystemExit(1)
    elif errors:
        for e in errors:
            print(f"[Config] WARN: {e}")

    # Режимы работы
    if args.mode == "rpc-only":
        config.mining_enabled = False
    elif args.mode == "validator":
        config.mining_enabled = False  # валидатор не майнит, только аттестует

    return config


# ═══════════════════════════════════════════════════════════════════════════════
#  Точка входа
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_node(config: Config):
    """Корутина верхнего уровня: создаёт узел и запускает его."""
    # Ensure fresh accept flag after prior test / reload.
    try:
        set_accepting_requests(True)
    except Exception as exc:
        _node_log.warning("set_accepting_requests failed at boot: %s", exc)
    node = NodeOrchestrator(config)

    # Graceful shutdown: Unix (asyncio) + Windows (signal) — ADR 0014
    loop = asyncio.get_running_loop()

    def _signal_stop():
        _handle_shutdown_signal(signal.SIGTERM, None)

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_stop)
    else:
        signal.signal(signal.SIGINT, _handle_shutdown_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_shutdown_signal)
        # CREATE_NEW_PROCESS_GROUP children receive CTRL_BREAK → SIGBREAK.
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _handle_shutdown_signal)

    try:
        await node.start()
    except asyncio.CancelledError:
        pass
    finally:
        # In-process / normal unwind — never os._exit from here.
        node.stop(force_process_exit=False)


def main():
    args = parse_args()
    config = build_config(args)
    _setup_logging(config)

    try:
        asyncio.run(_run_node(config))
    except KeyboardInterrupt:
        print("\n[Node] Interrupted.")


if __name__ == "__main__":
    main()
