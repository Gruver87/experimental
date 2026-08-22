#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute Blockchain — единая конфигурация узла.
Все параметры системы берутся отсюда.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from runtime.env_loader import env_str, env_int, env_bool, env_list


@dataclass
class Config:
    # ── Идентификация сети ──────────────────────────────────────────────────
    chain_id: int = 77777                 # Absolute Devnet (see node.example.json)
    genesis_timestamp: int = 0              # 0 = deterministic from chain_id (multi-node P2P)
    network_name: str = "Absolute"
    node_version: str = "1.3.206-industrial"
    node_id: str = "node-1"
    tip_safety_shadow: bool = False  # stage 2: observe tip policy without enforce
    tip_safety_enforce: bool = False  # stage 3: refuse import on tip-safety reject
    tip_ancestry_window_max: int = 256  # ADR 0016 stage-1.5 bounded tip ancestry

    # ── Монета (токеномика D.U.P. / Uladzimir Dabranski) ───────────────────
    coin_symbol: str = "ABS"
    coin_name: str = "Absolute"
    max_supply: int = 221_000_000       # жёсткий лимит: 221 млн ABS
    genesis_supply: int = 110_500_000   # genesis-эмиссия (без mining pool)
    founder_percent: float = 17.4       # доля основателя D.U.P.
    founder_amount: float = 38_454_000  # 17.4% от 221M
    founder_address: str = ""           # заполняется из wallet при запуске
    founder_initials: str = "D.U.P."
    founder_name: str = "Uladzimir Dabranski"
    block_reward: float = 50.0          # вознаграждение майнера за блок (из mining pool)
    burn_rate: float = 0.02             # 2% каждой комиссии сжигается навсегда
    burn_address: str = "0x000000000000000000000000000000000000dead"
    base_gas_price: int = 21_000        # базовая стоимость перевода в gas units
    gas_price_wei: float = 0.000_000_1  # цена одного gas в ABS

    # ── Сервера ─────────────────────────────────────────────────────────────
    rpc_host: str = "0.0.0.0"
    rpc_port: int = 8545        # JSON-RPC (Ethereum-совместимый)
    http_host: str = "0.0.0.0"
    http_port: int = 8080       # REST API
    ws_host: str = "0.0.0.0"
    ws_port: int = 8766         # WebSocket
    p2p_host: str = "0.0.0.0"
    p2p_port: int = 5000        # P2P сеть

    # ── База данных ─────────────────────────────────────────────────────────
    db_path: str = "data/blockchain.db"
    db_engine: str = "sqlite"           # sqlite | rocksdb (prod mainnet)
    rocksdb_sync: str = "FULL"          # normal | full — durable WAL/fsync
    rocksdb_block_cache_mb: int = 256   # 0 = RocksDB default
    rocksdb_write_buffer_mb: int = 64   # 0 = RocksDB default
    rocksdb_column_families: bool = False  # prod JSON true; dual-read legacy default
    db_wal_mode: bool = True            # WAL для производительности SQLite

    # ── Майнинг / Консенсус ─────────────────────────────────────────────────
    block_time: int = 15                # секунд между блоками
    epoch_size: int = 32                # блоков в эпохе (staking release)
    max_tx_per_block: int = 500
    mining_enabled: bool = True
    miner_address: str = ""             # заполняется из wallet при запуске
    signing_address: str = ""           # operational wallet for API signing
    validator_count: int = 21
    min_stake: float = 1000.0           # минимальный стейк валидатора
    consensus_mode: str = "auto"        # auto | parallel | unified (prod → unified)
    require_signatures: bool = False    # prod / node.json: true — reject unsigned txs
    enforce_proposer: bool = True       # reject blocks from unknown/slashed proposers
    verify_peer_state_root: bool = True # compare state_root on P2P import
    state_root_strict_p2p: bool = True  # strict state_root on P2P import above baseline
    state_root_legacy_cutoff_height: int = 0  # blocks <= cutoff: warn on drift; above: strict
    allow_state_root_rewrite: bool = True  # rewrite tip header state_root/hash; prod forces False (genesis h=0 still allowed)
    # Wave C tip encoding: v2 satoshi tip only when ceremony-armed (prod mesh JSON sets both).
    state_root_encoding_version: int = 1
    state_root_v2_ceremony_ok: bool = False
    monitor_port: int = 0               # 0 = http_port + 12 (8092 for :8080)
    rpc_proxy_port: int = 0             # 0 = http_port + 2 (8082 for :8080)
    monitor_enabled: bool = True

    # ── P2P ─────────────────────────────────────────────────────────────────
    bootstrap_peers: List[str] = field(default_factory=list)
    follower_genesis_sync: bool = False  # prod followers: import genesis from peers, no local mint
    genesis_artifact_path: str = ""  # shared JSON with leader genesis #0 (ceremony mesh fallback)
    mesh_min_peers_before_mine: int = 0   # prod mesh hub: wait for N peers before forging
    chain_apply_queue_max: int = 64       # serial apply backlog (mine + P2P import)
    chain_apply_timeout_sec: float = 120.0
    max_peers: int = 50
    testnet_expected_peers: int = 1     # mesh health threshold (3-node devnet: 2 on hub)
    testnet_expected_validators: int = 0  # Wave 55: 5-validator devnet
    testnet_validator_index: int = 0      # this node's slot in manifest (1..5)
    testnet_validators_manifest: str = "" # docker/validators.devnet5.json
    validators_manifest_path: str = ""    # prod: public validator set (addresses only)
    peer_timeout: int = 30              # секунд до отключения неактивного пира
    p2p_max_message_bytes: int = 2 * 1024 * 1024  # max JSON line on P2P wire
    p2p_max_messages_per_sec: int = 500           # per-peer wire rate limit (0=off)
    p2p_exempt_messages_per_sec: int = 2000       # secondary budget for sync/tx exempt types (0=off)
    p2p_attest_messages_per_sec: int = 80         # class cap: attestation flood (0=off)
    p2p_tx_messages_per_sec: int = 120            # class cap: new_tx gossip flood (0=off)
    p2p_block_announce_messages_per_sec: int = 40 # class cap: new_block announce flood (0=off)
    p2p_max_sync_inflight: int = 2                # global concurrent peer sync tasks
    p2p_send_queue_max: int = 256                 # per-peer outbound message queue
    p2p_drain_timeout_sec: float = 5.0            # writer.drain timeout per send
    p2p_ban_seconds: int = 300                    # temp ban after repeated abuse
    p2p_rate_limit_strikes: int = 5               # strikes before ban
    p2p_max_inbound_per_ip: int = 8               # inbound connections per remote IP (0=off)
    p2p_max_peers_per_subnet: int = 4             # public /24|/64 inbound cap (0=off; private IPs exempt)
    p2p_reserved_outbound_slots: int = 2          # inbound cannot fill these dial slots
    p2p_max_bytes_per_sec: int = 4 * 1024 * 1024  # per-peer inbound bandwidth budget (0=off)
    p2p_max_outbound_bytes_per_sec: int = 4 * 1024 * 1024  # per-peer outbound bandwidth (0=off)
    p2p_evict_min_score: int = 0                  # evict peers below score when >1 peer (0=off)
    p2p_eclipse_warn_ratio: float = 0.34          # densest public subnet / public peers (0=off)
    p2p_discovery_allow_private: bool = False     # v1.3.128: allow RFC1918/link-local in MSG_PEERS dials
    p2p_max_peer_height_ahead: int = 100_000      # v1.3.131+: cap status/new_block/handshake peer.height above local tip
    p2p_max_attestation_slot_ahead: int = 100_000 # v1.3.136: refuse attestation slot/target_height above local tip/slot
    p2p_catch_up_require_head: bool = True        # v1.3.139: refuse height-only catch-up without peer.head
    p2p_catch_up_tip_probe: bool = True           # v1.3.146: solicit local-tip state_root before ahead catch-up
    p2p_catch_up_peer_head_probe: bool = True     # v1.3.154: solicit peer.head via get_block_by_hash before catch-up
    p2p_catch_up_peer_head_parent_bind: bool = True  # v1.3.157: +1 peer.head parent_hash must match local tip
    p2p_catch_up_tip_head_bind: bool = True       # v1.3.172: after catch-up, tip hash must match peer.head
    p2p_catch_up_contiguous_parent_bind: bool = True  # v1.3.175: +1 catch-up import parent must match tip
    p2p_catch_up_height_continuity_bind: bool = True  # v1.3.176: catch-up import height must equal expected current
    p2p_peers_solicit_only: bool = True           # v1.3.152: refuse unsolicited MSG_PEERS (no dial from push)
    p2p_mempool_min_fee_refuse: bool = True       # v1.3.177: refuse fee<min_fee before validate_transaction
    p2p_mempool_max_fee_refuse: bool = True       # v1.3.201: refuse fee>max_fee before validate_transaction
    p2p_mempool_max_fee: float = 1_000_000_000.0 # v1.3.201: max wire fee (ABS; soft DoS ceiling)
    p2p_mempool_max_gas_refuse: bool = True       # v1.3.179: refuse gas>evm_gas_limit before validate_transaction
    p2p_mempool_max_calldata_refuse: bool = True  # v1.3.183: refuse oversized calldata before validate_transaction
    p2p_mempool_max_calldata_bytes: int = 131072  # v1.3.183: max wire calldata bytes (128 KiB)
    p2p_mempool_negative_value_refuse: bool = True  # v1.3.184: refuse value<0 before validate_transaction
    p2p_mempool_max_value_refuse: bool = True       # v1.3.202: refuse value>max_value before validate_transaction
    p2p_mempool_max_value: float = 221_000_000.0   # v1.3.202: max wire value (ABS; soft DoS; aligns max_supply)
    p2p_mempool_negative_nonce_refuse: bool = True  # v1.3.185: refuse nonce<0 before validate_transaction
    p2p_mempool_max_nonce_refuse: bool = True       # v1.3.200: refuse oversized nonce before validate_transaction
    p2p_mempool_max_nonce: int = 1_000_000_000_000 # v1.3.200: max wire nonce (align MAX_P2P_HEIGHT style)
    p2p_mempool_negative_fee_refuse: bool = True    # v1.3.186: refuse fee<0 before validate_transaction
    p2p_mempool_negative_gas_refuse: bool = True    # v1.3.187: refuse gas<0 before validate_transaction
    p2p_mempool_unparseable_gas_refuse: bool = True # v1.3.203: refuse unparseable gas before validate_transaction
    p2p_mempool_unparseable_value_refuse: bool = True # v1.3.204: refuse unparseable value before validate_transaction
    p2p_mempool_unparseable_nonce_refuse: bool = True # v1.3.205: refuse unparseable nonce before validate_transaction
    p2p_mempool_empty_from_refuse: bool = True      # v1.3.188: refuse empty from before validate_transaction
    p2p_mempool_max_from_refuse: bool = True        # v1.3.198: refuse oversized from before validate_transaction
    p2p_mempool_max_addr_chars: int = 128           # v1.3.198: max wire from/to chars (align MAX_P2P_ADDR_LEN)
    p2p_mempool_empty_to_refuse: bool = True        # v1.3.195: refuse empty to before validate_transaction
    p2p_mempool_max_to_refuse: bool = True          # v1.3.199: refuse oversized to before validate_transaction
    p2p_mempool_empty_hash_refuse: bool = True      # v1.3.196: refuse empty hash before validate_transaction
    p2p_mempool_max_hash_refuse: bool = True        # v1.3.197: refuse oversized hash before validate_transaction
    p2p_mempool_max_hash_chars: int = 128           # v1.3.197: max wire hash chars (align MAX_P2P_HASH_LEN)
    p2p_mempool_empty_sig_refuse: bool = True       # v1.3.189: refuse empty signature before validate_transaction
    p2p_mempool_empty_pubkey_refuse: bool = True    # v1.3.190: refuse empty public_key before validate_transaction
    p2p_mempool_max_sig_refuse: bool = True         # v1.3.191: refuse oversized signature before validate_transaction
    p2p_mempool_max_sig_bytes: int = 2048           # v1.3.191: max wire signature bytes
    p2p_mempool_max_pubkey_refuse: bool = True      # v1.3.192: refuse oversized public_key before validate_transaction
    p2p_mempool_max_pubkey_bytes: int = 2048        # v1.3.192: max wire public_key bytes
    p2p_mempool_nonfinite_value_refuse: bool = True # v1.3.193: refuse NaN/Inf value before validate_transaction
    p2p_mempool_nonfinite_fee_refuse: bool = True   # v1.3.194: refuse NaN/Inf fee before validate_transaction
    p2p_get_blocks_future_refuse: bool = True     # v1.3.180: refuse GET_BLOCKS when from_height > local tip
    p2p_get_block_future_refuse: bool = True      # v1.3.181: refuse GET_BLOCK when height > local tip
    p2p_get_blocks_past_tip_clamp: bool = True    # v1.3.182: clamp GET_BLOCKS end to local tip (no DB past tip)
    p2p_mempool_serve_tip_align: bool = True      # v1.3.178: refuse GET_MEMPOOL dump when peer tip far from local
    p2p_mempool_serve_max_height_delta: int = 2   # v1.3.178: |peer.height-local| max for mempool serve
    p2p_new_block_head_height_bind: bool = True   # v1.3.153: known announce hash ⇒ height must match local header
    p2p_status_head_height_bind: bool = True      # v1.3.155: known status/handshake head ⇒ height must match local header
    p2p_status_head_requires_height: bool = True  # v1.3.161: refuse head-only STATUS when local tip > 0
    p2p_handshake_head_requires_height: bool = True  # v1.3.166: refuse head-only handshake when local tip > 0
    p2p_attestation_target_head_bind: bool = True  # v1.3.167: tip-height attestation must cite local tip hash
    p2p_fork_peer_head_probe: bool = True         # v1.3.162: solicit peer.head via get_block_by_hash before same-height fork reorg
    p2p_fork_peer_head_parent_bind: bool = True   # v1.3.168: same-height fork peer.head parent must match tip parent
    p2p_reconcile_head_hash_bind: bool = True     # v1.3.163: fetched reconcile block hash must match target_head
    p2p_ghost_head_probe: bool = True             # v1.3.164: solicit ghost canonical head via get_block_by_hash before reorg
    p2p_ghost_head_parent_bind: bool = True       # v1.3.169: GHOST head parent must match tip-height parent
    p2p_reconcile_contiguous_parent_bind: bool = True  # v1.3.165: +1 reconcile parent_hash must match local tip
    p2p_reconcile_same_height_parent_bind: bool = True  # v1.3.171: same-height reconcile parent must match tip parent
    p2p_reconcile_tip_head_bind: bool = True      # v1.3.173: after reconcile import, tip hash must match target_head
    p2p_new_block_announce_body_bind: bool = True # v1.3.156: announce hash/height must match Block.from_dict body
    p2p_new_block_contiguous_parent_bind: bool = True  # v1.3.160: +1 new_block parent_hash must match local tip
    p2p_new_block_same_height_parent_bind: bool = True  # v1.3.170: same-height new_block parent must match tip parent
    p2p_new_block_tip_head_bind: bool = True      # v1.3.174: after new_block import, tip hash must match announce
    p2p_height_cap_clear_head: bool = True        # v1.3.159: height-cap clears fantasy peer.head (status/new_block/handshake)
    p2p_native_transport: bool = False            # v1.3.90+; prod forces True (v1.3.114)
    p2p_native_auto_pong: bool = True             # v1.3.98/99: ping reply + pong consume on read path
    p2p_native_read_batch: int = 8                # v1.3.101: read_messages max_n (1..64)
    p2p_native_write_batch: int = 8               # v1.3.101: send-queue write batch (1..64)
    p2p_native_read_chunk: int = 65536            # v1.3.101: native read chunk bytes
    p2p_native_io_timeout_ms: int = 30000         # v1.3.102: socket SO_RCV/SNDTIMEO after connect
    p2p_tls_enabled: bool = False                 # TLS on P2P wire (mainnet / public mesh)
    p2p_tls_cert_path: str = ""                   # node cert (PEM)
    p2p_tls_key_path: str = ""                    # node private key (PEM)
    p2p_tls_ca_path: str = ""                     # CA bundle for peer verify / mTLS
    p2p_tls_require_client_cert: bool = False     # mTLS: require client cert from peers
    p2p_tls_fail_closed: bool = True              # TLS on ⇒ CERT_REQUIRED (never CERT_NONE)
    p2p_tls_bind_identity: bool = True            # bind handshake node_id to cert CN/SAN
    p2p_tls_peer_fingerprints: str = ""           # optional SHA-256 DER allowlist (csv)
    p2p_bootstrap_pins: str = ""                  # v1.3.133: host:port=sha256[@node_id] csv
    sync_batch_size: int = 100          # блоков за один запрос синхронизации

    # ── EVM ─────────────────────────────────────────────────────────────────
    evm_enabled: bool = True
    evm_gas_limit: int = 8_000_000
    evm_create2_eip1014: bool = False   # prod: Ethereum CREATE2 (0xff++addr++salt++hash)
    evm_require_deploy_salt: bool = False  # prod: reject non-deterministic EVM deploy addresses
    feature_nft: bool = True
    feature_zk: bool = True
    feature_minivm: bool = True
    feature_sharding: bool = True
    num_shards: int = 4
    assigned_shard_id: int = -1          # distributed: 0..N-1; -1 = legacy routing coordinator
    shard_mode: str = "routing"          # routing | distributed
    feature_oracles: bool = True
    feature_wasm: bool = True
    feature_plasma: bool = True
    feature_lightning: bool = True
    feature_pq: bool = True
    feature_mev: bool = True
    feature_ai_agents: bool = True
    feature_ai_validator: bool = True
    feature_smart_accounts: bool = True
    feature_validator_selection: bool = True
    # Experimental R&D (Profile F) — always default OFF; prod forces OFF.
    feature_libp2p: bool = False
    feature_long_range: bool = False

    # ── Мост (Cross-chain bridge) ────────────────────────────────────────────
    bridge_enabled: bool = False        # OFF by default (mainnet-v1 decision until L1 contracts)
    bridge_mode: str = "rust"           # "rust" | "simulator" | test-only "fake"
    bridge_auto_confirm_sec: int = 0    # 0 = manual POST /bridge/confirm-lock only
    bridge_require_l1_proof: bool = False
    bridge_require_l1_event: bool = False  # require receipt log from lock contract (address-level)
    bridge_min_confirmations: int = 0   # 0 = skip confirmation gate unless proof required
    bridge_require_inbound_zk: bool = False  # fail-closed ZK when feature_zk + inbound
    bridge_dev_adapter_enabled: bool = False  # explicit dev/test CrossChainBridge adapter
    rust_bridge_path: str = "bridge/abs_bridge_bin"
    bridge_oracle_secret: str = ""      # HMAC secret for /bridge/oracle/* relayer
    bridge_l1_queue_path: str = "data/bridge_l1_queue.json"
    bridge_l1_chain: str = "ethereum"   # target L1 chain for cutover profile
    bridge_l1_lock_contract: str = ""   # L1 escrow/lock contract (address)
    bridge_l1_mint_contract: str = ""   # L1 mint/release contract (address)

    # ── Логирование ─────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "data/node.log"
    log_json: bool = False                # structured JSON logs (prod)

    # ── Промышленный профиль ────────────────────────────────────────────────
    # Fail-closed defaults: empty CORS / proxy off (opt-in via env or JSON).
    deployment_mode: str = "dev"          # dev | staging | prod
    cors_origins: List[str] = field(default_factory=list)
    jwt_enforce_admin: bool = False       # prod: требовать JWT на POST/admin
    require_wallet_file: bool = False     # prod: не генерировать кошелёк автоматически
    enable_cors_rpc_proxy: bool = False   # opt-in RPC proxy :8082 (never default-on)
    allow_insecure_public_bind: bool = False
    sqlite_synchronous: str = "NORMAL"      # prod: FULL
    metrics_enabled: bool = True
    secret_backend: str = "env"  # ADR 0015: env|vault|file|null
    require_native_crypto: bool = False     # prod: require abs_native PyO3 kernels
    http_max_body_bytes: int = 1_048_576    # v1.3.65: REST/RPC body cap (1 MiB)
    jsonrpc_max_batch: int = 32             # v1.3.65: max JSON-RPC batch elements
    rpc_get_logs_max_range: int = 2000      # ADR 0011 amplification cap
    rpc_get_logs_max_results: int = 1000
    rpc_heavy_query_timeout_ms: int = 5000
    rpc_heavy_workers: int = 2
    rpc_full_tx_block_max_txs: int = 500

    # ── Scale / HA (Phase 5) ────────────────────────────────────────────────
    redis_url: str = ""                     # redis://localhost:6379/0
    redis_rate_limit_enabled: bool = False  # distributed rate limit
    rate_limit_rpm: int = 120               # requests per minute per IP

    # ── RPC Security (Phase 2b) ─────────────────────────────────────────────
    rpc_api_key_required: bool = False      # prod: требовать ключ на :8545
    rpc_api_keys: List[str] = field(default_factory=list)  # из RPC_API_KEYS env

    # ────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_json(cls, path: str) -> "Config":
        """Загрузить конфигурацию из JSON-файла."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cfg = cls()
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    def to_json(self, path: str) -> None:
        """Сохранить конфигурацию в JSON-файл."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        data = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def base_fee(self) -> float:
        """Базовая комиссия за обычный перевод в ABS."""
        return self.base_gas_price * self.gas_price_wei

    def resolved_monitor_port(self) -> int:
        return self.monitor_port or (self.http_port + 12)

    def resolved_rpc_proxy_port(self) -> int:
        return self.rpc_proxy_port or (self.http_port + 2)

    def resolve_genesis_timestamp(self) -> int:
        """Deterministic genesis time for multi-node P2P (override via genesis_timestamp)."""
        ts = int(getattr(self, "genesis_timestamp", 0) or 0)
        if ts > 0:
            return ts
        return 1_704_067_200 + int(getattr(self, "chain_id", 77777))

    def resolved_consensus_mode(self) -> str:
        """Single canonical fork-choice path in prod/staging (LMD-GHOST + FinalityEngine)."""
        mode = str(getattr(self, "consensus_mode", "auto") or "auto").strip().lower()
        if mode == "auto":
            dep = str(getattr(self, "deployment_mode", "dev") or "dev").lower()
            return "unified" if dep in ("prod", "staging") else "parallel"
        if mode in ("parallel", "unified"):
            return mode
        return "parallel"

    @property
    def is_production(self) -> bool:
        return self.deployment_mode == "prod"

    def resolve_rust_bridge_path(self) -> str:
        """Resolve rust bridge binary (incl. .exe on Windows and project-relative paths)."""
        candidates = [self.rust_bridge_path, self.rust_bridge_path + ".exe"]
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for base in candidates:
            if os.path.isfile(base):
                return base
            rel = os.path.join(root, base)
            if os.path.isfile(rel):
                return rel
        return self.rust_bridge_path

    def resolve_storage_paths(self) -> None:
        """Normalize db_path/log_file after env + JSON merge."""
        data_dir = env_str("DATA_DIR")
        if self.db_engine == "rocksdb":
            base = data_dir or (os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else "data")
            self.db_path = os.path.join(base, "chainstore")
        elif data_dir:
            self.db_path = os.path.join(data_dir, "blockchain.db")
        if data_dir:
            self.log_file = os.path.join(data_dir, "node.log")

    def apply_env(self) -> "Config":
        """Переопределяет поля из переменных окружения (.env / Docker / K8s)."""
        data_dir = env_str("DATA_DIR")
        if data_dir:
            self.db_path = os.path.join(data_dir, "blockchain.db")
            self.log_file = os.path.join(data_dir, "node.log")

        self.db_engine = env_str("DB_ENGINE", self.db_engine).strip().lower()
        self.rocksdb_sync = env_str("ROCKSDB_SYNC", self.rocksdb_sync).strip().upper()
        self.rocksdb_block_cache_mb = env_int(
            "ROCKSDB_BLOCK_CACHE_MB", self.rocksdb_block_cache_mb
        )
        self.rocksdb_write_buffer_mb = env_int(
            "ROCKSDB_WRITE_BUFFER_MB", self.rocksdb_write_buffer_mb
        )
        self.rocksdb_column_families = env_bool(
            "ROCKSDB_COLUMN_FAMILIES", self.rocksdb_column_families
        )
        self.resolve_storage_paths()

        self.node_id = env_str("NODE_ID", self.node_id)
        self.deployment_mode = env_str("DEPLOYMENT_MODE", self.deployment_mode).lower()
        # staging/prod: hard-coerce parallel → unified (matches resolved_consensus_mode)
        if self.deployment_mode in ("prod", "staging"):
            if str(self.consensus_mode or "").strip().lower() == "parallel":
                self.consensus_mode = "unified"
        self.tip_safety_shadow = env_bool(
            "TIP_SAFETY_SHADOW",
            self.tip_safety_shadow,
        )
        self.tip_safety_enforce = env_bool(
            "TIP_SAFETY_ENFORCE",
            self.tip_safety_enforce,
        )
        self.state_root_encoding_version = env_int(
            "ABS_STATE_ROOT_ENCODING_VERSION",
            self.state_root_encoding_version,
        )
        self.state_root_v2_ceremony_ok = env_bool(
            "ABS_STATE_ROOT_V2_CEREMONY_OK",
            self.state_root_v2_ceremony_ok,
        )
        if self.tip_safety_enforce:
            # Enforce implies observation; keep metrics aligned with gate decisions.
            self.tip_safety_shadow = True
        self.tip_ancestry_window_max = env_int(
            "TIP_ANCESTRY_WINDOW_MAX",
            self.tip_ancestry_window_max,
        )
        if int(self.tip_ancestry_window_max or 0) < 1:
            self.tip_ancestry_window_max = 256
        self.chain_id = env_int("CHAIN_ID", self.chain_id)
        self.rpc_host = env_str("RPC_HOST", self.rpc_host)
        self.http_host = env_str("HTTP_HOST", self.http_host)
        self.ws_host = env_str("WS_HOST", self.ws_host)
        self.p2p_host = env_str("P2P_HOST", self.p2p_host)
        self.rpc_port = env_int("RPC_PORT", self.rpc_port)
        self.http_port = env_int("HTTP_PORT", env_int("WEB_PORT", self.http_port))
        self.ws_port = env_int("WS_PORT", self.ws_port)
        self.p2p_port = env_int("P2P_PORT", self.p2p_port)
        self.p2p_max_message_bytes = env_int(
            "P2P_MAX_MESSAGE_BYTES", self.p2p_max_message_bytes
        )
        self.p2p_max_messages_per_sec = env_int(
            "P2P_MAX_MESSAGES_PER_SEC", self.p2p_max_messages_per_sec
        )
        self.p2p_exempt_messages_per_sec = env_int(
            "P2P_EXEMPT_MESSAGES_PER_SEC", self.p2p_exempt_messages_per_sec
        )
        self.p2p_attest_messages_per_sec = env_int(
            "P2P_ATTEST_MESSAGES_PER_SEC", self.p2p_attest_messages_per_sec
        )
        self.p2p_tx_messages_per_sec = env_int(
            "P2P_TX_MESSAGES_PER_SEC", self.p2p_tx_messages_per_sec
        )
        self.p2p_block_announce_messages_per_sec = env_int(
            "P2P_BLOCK_ANNOUNCE_MESSAGES_PER_SEC",
            self.p2p_block_announce_messages_per_sec,
        )
        self.p2p_max_sync_inflight = env_int(
            "P2P_MAX_SYNC_INFLIGHT", self.p2p_max_sync_inflight
        )
        self.p2p_send_queue_max = env_int(
            "P2P_SEND_QUEUE_MAX", self.p2p_send_queue_max
        )
        try:
            self.p2p_drain_timeout_sec = float(
                env_str("P2P_DRAIN_TIMEOUT_SEC", str(self.p2p_drain_timeout_sec))
            )
        except (TypeError, ValueError):
            pass
        self.p2p_ban_seconds = env_int("P2P_BAN_SECONDS", self.p2p_ban_seconds)
        self.p2p_rate_limit_strikes = env_int(
            "P2P_RATE_LIMIT_STRIKES", self.p2p_rate_limit_strikes
        )
        self.p2p_max_inbound_per_ip = env_int(
            "P2P_MAX_INBOUND_PER_IP", self.p2p_max_inbound_per_ip
        )
        self.p2p_max_peers_per_subnet = env_int(
            "P2P_MAX_PEERS_PER_SUBNET", self.p2p_max_peers_per_subnet
        )
        self.p2p_reserved_outbound_slots = env_int(
            "P2P_RESERVED_OUTBOUND_SLOTS", self.p2p_reserved_outbound_slots
        )
        self.p2p_max_bytes_per_sec = env_int(
            "P2P_MAX_BYTES_PER_SEC", self.p2p_max_bytes_per_sec
        )
        self.p2p_max_outbound_bytes_per_sec = env_int(
            "P2P_MAX_OUTBOUND_BYTES_PER_SEC", self.p2p_max_outbound_bytes_per_sec
        )
        self.p2p_evict_min_score = env_int(
            "P2P_EVICT_MIN_SCORE", self.p2p_evict_min_score
        )
        try:
            self.p2p_eclipse_warn_ratio = float(
                env_str("P2P_ECLIPSE_WARN_RATIO", str(self.p2p_eclipse_warn_ratio))
            )
        except (TypeError, ValueError):
            pass
        self.p2p_discovery_allow_private = env_bool(
            "P2P_DISCOVERY_ALLOW_PRIVATE", self.p2p_discovery_allow_private
        )
        self.p2p_max_peer_height_ahead = env_int(
            "P2P_MAX_PEER_HEIGHT_AHEAD", self.p2p_max_peer_height_ahead
        )
        self.p2p_max_attestation_slot_ahead = env_int(
            "P2P_MAX_ATTESTATION_SLOT_AHEAD", self.p2p_max_attestation_slot_ahead
        )
        self.p2p_catch_up_require_head = env_bool(
            "P2P_CATCH_UP_REQUIRE_HEAD", self.p2p_catch_up_require_head
        )
        self.p2p_catch_up_tip_probe = env_bool(
            "P2P_CATCH_UP_TIP_PROBE", self.p2p_catch_up_tip_probe
        )
        self.p2p_catch_up_peer_head_probe = env_bool(
            "P2P_CATCH_UP_PEER_HEAD_PROBE", self.p2p_catch_up_peer_head_probe
        )
        self.p2p_catch_up_peer_head_parent_bind = env_bool(
            "P2P_CATCH_UP_PEER_HEAD_PARENT_BIND",
            self.p2p_catch_up_peer_head_parent_bind,
        )
        self.p2p_catch_up_tip_head_bind = env_bool(
            "P2P_CATCH_UP_TIP_HEAD_BIND", self.p2p_catch_up_tip_head_bind
        )
        self.p2p_catch_up_contiguous_parent_bind = env_bool(
            "P2P_CATCH_UP_CONTIGUOUS_PARENT_BIND",
            self.p2p_catch_up_contiguous_parent_bind,
        )
        self.p2p_catch_up_height_continuity_bind = env_bool(
            "P2P_CATCH_UP_HEIGHT_CONTINUITY_BIND",
            self.p2p_catch_up_height_continuity_bind,
        )
        self.p2p_peers_solicit_only = env_bool(
            "P2P_PEERS_SOLICIT_ONLY", self.p2p_peers_solicit_only
        )
        self.p2p_mempool_min_fee_refuse = env_bool(
            "P2P_MEMPOOL_MIN_FEE_REFUSE", self.p2p_mempool_min_fee_refuse
        )
        self.p2p_mempool_max_fee_refuse = env_bool(
            "P2P_MEMPOOL_MAX_FEE_REFUSE",
            self.p2p_mempool_max_fee_refuse,
        )
        _max_fee_raw = env_str("P2P_MEMPOOL_MAX_FEE")
        if _max_fee_raw:
            try:
                self.p2p_mempool_max_fee = float(_max_fee_raw)
            except ValueError:
                pass
        self.p2p_mempool_max_gas_refuse = env_bool(
            "P2P_MEMPOOL_MAX_GAS_REFUSE", self.p2p_mempool_max_gas_refuse
        )
        self.p2p_mempool_max_calldata_refuse = env_bool(
            "P2P_MEMPOOL_MAX_CALLDATA_REFUSE", self.p2p_mempool_max_calldata_refuse
        )
        self.p2p_mempool_max_calldata_bytes = env_int(
            "P2P_MEMPOOL_MAX_CALLDATA_BYTES",
            self.p2p_mempool_max_calldata_bytes,
        )
        self.p2p_mempool_negative_value_refuse = env_bool(
            "P2P_MEMPOOL_NEGATIVE_VALUE_REFUSE",
            self.p2p_mempool_negative_value_refuse,
        )
        self.p2p_mempool_max_value_refuse = env_bool(
            "P2P_MEMPOOL_MAX_VALUE_REFUSE",
            self.p2p_mempool_max_value_refuse,
        )
        _max_value_raw = env_str("P2P_MEMPOOL_MAX_VALUE")
        if _max_value_raw:
            try:
                self.p2p_mempool_max_value = float(_max_value_raw)
            except ValueError:
                pass
        self.p2p_mempool_negative_nonce_refuse = env_bool(
            "P2P_MEMPOOL_NEGATIVE_NONCE_REFUSE",
            self.p2p_mempool_negative_nonce_refuse,
        )
        self.p2p_mempool_max_nonce_refuse = env_bool(
            "P2P_MEMPOOL_MAX_NONCE_REFUSE",
            self.p2p_mempool_max_nonce_refuse,
        )
        self.p2p_mempool_max_nonce = env_int(
            "P2P_MEMPOOL_MAX_NONCE",
            self.p2p_mempool_max_nonce,
        )
        self.p2p_mempool_negative_fee_refuse = env_bool(
            "P2P_MEMPOOL_NEGATIVE_FEE_REFUSE",
            self.p2p_mempool_negative_fee_refuse,
        )
        self.p2p_mempool_negative_gas_refuse = env_bool(
            "P2P_MEMPOOL_NEGATIVE_GAS_REFUSE",
            self.p2p_mempool_negative_gas_refuse,
        )
        self.p2p_mempool_unparseable_gas_refuse = env_bool(
            "P2P_MEMPOOL_UNPARSEABLE_GAS_REFUSE",
            self.p2p_mempool_unparseable_gas_refuse,
        )
        self.p2p_mempool_unparseable_value_refuse = env_bool(
            "P2P_MEMPOOL_UNPARSEABLE_VALUE_REFUSE",
            self.p2p_mempool_unparseable_value_refuse,
        )
        self.p2p_mempool_unparseable_nonce_refuse = env_bool(
            "P2P_MEMPOOL_UNPARSEABLE_NONCE_REFUSE",
            self.p2p_mempool_unparseable_nonce_refuse,
        )
        self.p2p_mempool_empty_from_refuse = env_bool(
            "P2P_MEMPOOL_EMPTY_FROM_REFUSE",
            self.p2p_mempool_empty_from_refuse,
        )
        self.p2p_mempool_max_from_refuse = env_bool(
            "P2P_MEMPOOL_MAX_FROM_REFUSE",
            self.p2p_mempool_max_from_refuse,
        )
        self.p2p_mempool_max_addr_chars = env_int(
            "P2P_MEMPOOL_MAX_ADDR_CHARS",
            self.p2p_mempool_max_addr_chars,
        )
        self.p2p_mempool_empty_to_refuse = env_bool(
            "P2P_MEMPOOL_EMPTY_TO_REFUSE",
            self.p2p_mempool_empty_to_refuse,
        )
        self.p2p_mempool_max_to_refuse = env_bool(
            "P2P_MEMPOOL_MAX_TO_REFUSE",
            self.p2p_mempool_max_to_refuse,
        )
        self.p2p_mempool_empty_hash_refuse = env_bool(
            "P2P_MEMPOOL_EMPTY_HASH_REFUSE",
            self.p2p_mempool_empty_hash_refuse,
        )
        self.p2p_mempool_max_hash_refuse = env_bool(
            "P2P_MEMPOOL_MAX_HASH_REFUSE",
            self.p2p_mempool_max_hash_refuse,
        )
        self.p2p_mempool_max_hash_chars = env_int(
            "P2P_MEMPOOL_MAX_HASH_CHARS",
            self.p2p_mempool_max_hash_chars,
        )
        self.p2p_mempool_empty_sig_refuse = env_bool(
            "P2P_MEMPOOL_EMPTY_SIG_REFUSE",
            self.p2p_mempool_empty_sig_refuse,
        )
        self.p2p_mempool_empty_pubkey_refuse = env_bool(
            "P2P_MEMPOOL_EMPTY_PUBKEY_REFUSE",
            self.p2p_mempool_empty_pubkey_refuse,
        )
        self.p2p_mempool_max_sig_refuse = env_bool(
            "P2P_MEMPOOL_MAX_SIG_REFUSE",
            self.p2p_mempool_max_sig_refuse,
        )
        self.p2p_mempool_max_sig_bytes = env_int(
            "P2P_MEMPOOL_MAX_SIG_BYTES",
            self.p2p_mempool_max_sig_bytes,
        )
        self.p2p_mempool_max_pubkey_refuse = env_bool(
            "P2P_MEMPOOL_MAX_PUBKEY_REFUSE",
            self.p2p_mempool_max_pubkey_refuse,
        )
        self.p2p_mempool_max_pubkey_bytes = env_int(
            "P2P_MEMPOOL_MAX_PUBKEY_BYTES",
            self.p2p_mempool_max_pubkey_bytes,
        )
        self.p2p_mempool_nonfinite_value_refuse = env_bool(
            "P2P_MEMPOOL_NONFINITE_VALUE_REFUSE",
            self.p2p_mempool_nonfinite_value_refuse,
        )
        self.p2p_mempool_nonfinite_fee_refuse = env_bool(
            "P2P_MEMPOOL_NONFINITE_FEE_REFUSE",
            self.p2p_mempool_nonfinite_fee_refuse,
        )
        self.p2p_get_blocks_future_refuse = env_bool(
            "P2P_GET_BLOCKS_FUTURE_REFUSE", self.p2p_get_blocks_future_refuse
        )
        self.p2p_get_block_future_refuse = env_bool(
            "P2P_GET_BLOCK_FUTURE_REFUSE", self.p2p_get_block_future_refuse
        )
        self.p2p_get_blocks_past_tip_clamp = env_bool(
            "P2P_GET_BLOCKS_PAST_TIP_CLAMP", self.p2p_get_blocks_past_tip_clamp
        )
        self.p2p_mempool_serve_tip_align = env_bool(
            "P2P_MEMPOOL_SERVE_TIP_ALIGN", self.p2p_mempool_serve_tip_align
        )
        self.p2p_mempool_serve_max_height_delta = env_int(
            "P2P_MEMPOOL_SERVE_MAX_HEIGHT_DELTA",
            self.p2p_mempool_serve_max_height_delta,
        )
        self.p2p_new_block_head_height_bind = env_bool(
            "P2P_NEW_BLOCK_HEAD_HEIGHT_BIND", self.p2p_new_block_head_height_bind
        )
        self.p2p_status_head_height_bind = env_bool(
            "P2P_STATUS_HEAD_HEIGHT_BIND", self.p2p_status_head_height_bind
        )
        self.p2p_status_head_requires_height = env_bool(
            "P2P_STATUS_HEAD_REQUIRES_HEIGHT", self.p2p_status_head_requires_height
        )
        self.p2p_handshake_head_requires_height = env_bool(
            "P2P_HANDSHAKE_HEAD_REQUIRES_HEIGHT",
            self.p2p_handshake_head_requires_height,
        )
        self.p2p_attestation_target_head_bind = env_bool(
            "P2P_ATTESTATION_TARGET_HEAD_BIND",
            self.p2p_attestation_target_head_bind,
        )
        self.p2p_fork_peer_head_probe = env_bool(
            "P2P_FORK_PEER_HEAD_PROBE", self.p2p_fork_peer_head_probe
        )
        self.p2p_fork_peer_head_parent_bind = env_bool(
            "P2P_FORK_PEER_HEAD_PARENT_BIND",
            self.p2p_fork_peer_head_parent_bind,
        )
        self.p2p_reconcile_head_hash_bind = env_bool(
            "P2P_RECONCILE_HEAD_HASH_BIND", self.p2p_reconcile_head_hash_bind
        )
        self.p2p_ghost_head_probe = env_bool(
            "P2P_GHOST_HEAD_PROBE", self.p2p_ghost_head_probe
        )
        self.p2p_ghost_head_parent_bind = env_bool(
            "P2P_GHOST_HEAD_PARENT_BIND", self.p2p_ghost_head_parent_bind
        )
        self.p2p_reconcile_contiguous_parent_bind = env_bool(
            "P2P_RECONCILE_CONTIGUOUS_PARENT_BIND",
            self.p2p_reconcile_contiguous_parent_bind,
        )
        self.p2p_reconcile_same_height_parent_bind = env_bool(
            "P2P_RECONCILE_SAME_HEIGHT_PARENT_BIND",
            self.p2p_reconcile_same_height_parent_bind,
        )
        self.p2p_reconcile_tip_head_bind = env_bool(
            "P2P_RECONCILE_TIP_HEAD_BIND", self.p2p_reconcile_tip_head_bind
        )
        self.p2p_new_block_announce_body_bind = env_bool(
            "P2P_NEW_BLOCK_ANNOUNCE_BODY_BIND", self.p2p_new_block_announce_body_bind
        )
        self.p2p_new_block_contiguous_parent_bind = env_bool(
            "P2P_NEW_BLOCK_CONTIGUOUS_PARENT_BIND",
            self.p2p_new_block_contiguous_parent_bind,
        )
        self.p2p_new_block_same_height_parent_bind = env_bool(
            "P2P_NEW_BLOCK_SAME_HEIGHT_PARENT_BIND",
            self.p2p_new_block_same_height_parent_bind,
        )
        self.p2p_new_block_tip_head_bind = env_bool(
            "P2P_NEW_BLOCK_TIP_HEAD_BIND", self.p2p_new_block_tip_head_bind
        )
        self.p2p_height_cap_clear_head = env_bool(
            "P2P_HEIGHT_CAP_CLEAR_HEAD", self.p2p_height_cap_clear_head
        )
        self.p2p_native_transport = env_bool(
            "P2P_NATIVE_TRANSPORT",
            self.p2p_native_transport if not self.is_production else True,
        )
        self.p2p_native_auto_pong = env_bool(
            "P2P_NATIVE_AUTO_PONG", self.p2p_native_auto_pong
        )
        self.p2p_native_read_batch = env_int(
            "P2P_NATIVE_READ_BATCH", self.p2p_native_read_batch
        )
        self.p2p_native_write_batch = env_int(
            "P2P_NATIVE_WRITE_BATCH", self.p2p_native_write_batch
        )
        self.p2p_native_read_chunk = env_int(
            "P2P_NATIVE_READ_CHUNK", self.p2p_native_read_chunk
        )
        self.p2p_native_io_timeout_ms = env_int(
            "P2P_NATIVE_IO_TIMEOUT_MS", self.p2p_native_io_timeout_ms
        )
        self.p2p_tls_enabled = env_bool("P2P_TLS_ENABLED", self.p2p_tls_enabled)
        self.p2p_tls_cert_path = env_str("P2P_TLS_CERT_PATH", self.p2p_tls_cert_path)
        self.p2p_tls_key_path = env_str("P2P_TLS_KEY_PATH", self.p2p_tls_key_path)
        self.p2p_tls_ca_path = env_str("P2P_TLS_CA_PATH", self.p2p_tls_ca_path)
        self.p2p_tls_require_client_cert = env_bool(
            "P2P_TLS_REQUIRE_CLIENT_CERT", self.p2p_tls_require_client_cert
        )
        self.p2p_tls_fail_closed = env_bool(
            "P2P_TLS_FAIL_CLOSED", self.p2p_tls_fail_closed
        )
        self.p2p_tls_bind_identity = env_bool(
            "P2P_TLS_BIND_IDENTITY", self.p2p_tls_bind_identity
        )
        self.p2p_tls_peer_fingerprints = env_str(
            "P2P_TLS_PEER_FINGERPRINTS", self.p2p_tls_peer_fingerprints
        )
        self.p2p_bootstrap_pins = env_str(
            "P2P_BOOTSTRAP_PINS", self.p2p_bootstrap_pins
        )
        self.log_level = env_str("LOG_LEVEL", self.log_level)
        self.log_json = env_bool("LOG_JSON", self.log_json)
        self.mining_enabled = env_bool("MINING_ENABLED", self.mining_enabled)
        self.mesh_min_peers_before_mine = env_int(
            "MESH_MIN_PEERS_BEFORE_MINE", self.mesh_min_peers_before_mine
        )
        self.chain_apply_queue_max = env_int(
            "CHAIN_APPLY_QUEUE_MAX", self.chain_apply_queue_max
        )
        try:
            self.chain_apply_timeout_sec = float(
                env_str("CHAIN_APPLY_TIMEOUT_SEC", str(self.chain_apply_timeout_sec))
            )
        except (TypeError, ValueError):
            pass
        if "TESTNET_EXPECTED_PEERS" in os.environ:
            self.testnet_expected_peers = env_int(
                "TESTNET_EXPECTED_PEERS", self.testnet_expected_peers
            )
        self.require_signatures = env_bool(
            "REQUIRE_SIGNATURES",
            self.require_signatures if not self.is_production else True,
        )
        self.enforce_proposer = env_bool("ENFORCE_PROPOSER", self.enforce_proposer)
        self.verify_peer_state_root = env_bool(
            "VERIFY_PEER_STATE_ROOT", self.verify_peer_state_root
        )
        self.state_root_strict_p2p = env_bool(
            "STATE_ROOT_STRICT_P2P", self.state_root_strict_p2p
        )
        self.allow_state_root_rewrite = env_bool(
            "ALLOW_STATE_ROOT_REWRITE", self.allow_state_root_rewrite
        )
        self.state_root_legacy_cutoff_height = env_int(
            "STATE_ROOT_LEGACY_CUTOFF_HEIGHT",
            self.state_root_legacy_cutoff_height,
        )
        self.monitor_enabled = env_bool("MONITOR_ENABLED", self.monitor_enabled)
        self.monitor_port = env_int("MONITOR_PORT", self.monitor_port)
        self.rpc_proxy_port = env_int("RPC_PROXY_PORT", self.rpc_proxy_port)
        self.metrics_enabled = env_bool("METRICS_ENABLED", self.metrics_enabled)
        self.secret_backend = env_str("SECRET_BACKEND", self.secret_backend or "env")
        self.require_native_crypto = env_bool(
            "ABS_REQUIRE_NATIVE_CRYPTO",
            self.require_native_crypto if not self.is_production else True,
        )
        self.jwt_enforce_admin = env_bool("JWT_ENFORCE_ADMIN", self.jwt_enforce_admin)
        self.enable_cors_rpc_proxy = env_bool("ENABLE_CORS_RPC_PROXY", self.enable_cors_rpc_proxy)
        self.allow_insecure_public_bind = env_bool(
            "ALLOW_INSECURE_PUBLIC_BIND", self.allow_insecure_public_bind
        )
        self.redis_url = env_str("REDIS_URL", self.redis_url)
        self.redis_rate_limit_enabled = env_bool("REDIS_RATE_LIMIT", self.redis_rate_limit_enabled)
        self.rate_limit_rpm = env_int("RATE_LIMIT_RPM", self.rate_limit_rpm)
        self.rpc_api_key_required = env_bool("RPC_API_KEY_REQUIRED", self.rpc_api_key_required)
        rpc_keys = env_list("RPC_API_KEYS")
        if rpc_keys:
            self.rpc_api_keys = rpc_keys

        self.feature_nft = env_bool("FEATURE_NFT", self.feature_nft)
        self.feature_zk = env_bool("FEATURE_ZK", self.feature_zk)
        self.feature_minivm = env_bool("FEATURE_MINIVM", self.feature_minivm)
        self.feature_sharding = env_bool("FEATURE_SHARDING", self.feature_sharding)
        self.num_shards = env_int("NUM_SHARDS", self.num_shards)
        self.assigned_shard_id = env_int("ASSIGNED_SHARD_ID", self.assigned_shard_id)
        self.shard_mode = env_str("SHARD_MODE", self.shard_mode).lower()
        self.feature_oracles = env_bool("FEATURE_ORACLES", self.feature_oracles)
        self.feature_wasm = env_bool("FEATURE_WASM", self.feature_wasm)
        self.feature_plasma = env_bool("FEATURE_PLASMA", self.feature_plasma)
        self.feature_lightning = env_bool("FEATURE_LIGHTNING", self.feature_lightning)
        self.feature_pq = env_bool("FEATURE_PQ", self.feature_pq)
        self.feature_mev = env_bool("FEATURE_MEV", self.feature_mev)
        self.feature_ai_agents = env_bool("FEATURE_AI_AGENTS", self.feature_ai_agents)
        self.feature_ai_validator = env_bool(
            "FEATURE_AI_VALIDATOR", self.feature_ai_validator
        )
        self.feature_smart_accounts = env_bool(
            "FEATURE_SMART_ACCOUNTS", self.feature_smart_accounts
        )
        self.feature_validator_selection = env_bool(
            "FEATURE_VALIDATOR_SELECTION", self.feature_validator_selection
        )
        self.feature_libp2p = env_bool("FEATURE_LIBP2P", self.feature_libp2p)
        self.feature_long_range = env_bool(
            "FEATURE_LONG_RANGE", self.feature_long_range
        )

        peers = env_list("BOOTSTRAP_PEERS")
        if peers:
            self.bootstrap_peers = peers
        self.follower_genesis_sync = env_bool(
            "FOLLOWER_GENESIS_SYNC", self.follower_genesis_sync
        )
        genesis_art = env_str("GENESIS_ARTIFACT_PATH", "")
        if genesis_art:
            self.genesis_artifact_path = genesis_art

        manifest_path = env_str("VALIDATORS_MANIFEST_PATH", "")
        if manifest_path:
            self.validators_manifest_path = manifest_path

        self.bridge_enabled = env_bool("BRIDGE_ENABLED", self.bridge_enabled)
        self.bridge_mode = env_str("BRIDGE_MODE", self.bridge_mode)
        self.bridge_auto_confirm_sec = env_int(
            "BRIDGE_AUTO_CONFIRM_SEC", self.bridge_auto_confirm_sec
        )
        self.bridge_require_l1_proof = env_bool(
            "BRIDGE_REQUIRE_L1_PROOF", self.bridge_require_l1_proof
        )
        self.bridge_require_l1_event = env_bool(
            "BRIDGE_REQUIRE_L1_EVENT", self.bridge_require_l1_event
        )
        self.bridge_min_confirmations = env_int(
            "BRIDGE_MIN_CONFIRMATIONS", self.bridge_min_confirmations
        )
        self.bridge_require_inbound_zk = env_bool(
            "BRIDGE_REQUIRE_INBOUND_ZK", self.bridge_require_inbound_zk
        )
        self.bridge_dev_adapter_enabled = env_bool(
            "BRIDGE_DEV_ADAPTER_ENABLED", self.bridge_dev_adapter_enabled
        )
        rust_path = env_str("RUST_BRIDGE_PATH", "")
        if rust_path:
            self.rust_bridge_path = rust_path
        oracle_secret = env_str("BRIDGE_ORACLE_SECRET", "")
        if oracle_secret:
            self.bridge_oracle_secret = oracle_secret
        l1_queue = env_str("BRIDGE_L1_QUEUE_PATH", "")
        if l1_queue:
            self.bridge_l1_queue_path = l1_queue
        l1_chain = env_str("BRIDGE_L1_CHAIN", "")
        if l1_chain:
            self.bridge_l1_chain = l1_chain
        lock_contract = env_str("BRIDGE_L1_LOCK_CONTRACT", "")
        if lock_contract:
            self.bridge_l1_lock_contract = lock_contract
        mint_contract = env_str("BRIDGE_L1_MINT_CONTRACT", "")
        if mint_contract:
            self.bridge_l1_mint_contract = mint_contract

        origins = env_list("CORS_ORIGINS")
        if origins:
            self.cors_origins = origins

        if self.is_production:
            self.sqlite_synchronous = env_str("SQLITE_SYNCHRONOUS", "FULL")
            self.rocksdb_sync = env_str("ROCKSDB_SYNC", "FULL")
            self.enable_cors_rpc_proxy = env_bool("ENABLE_CORS_RPC_PROXY", False)
            self.log_json = env_bool("LOG_JSON", True)
            # Fail-closed: env cannot weaken L1 proof requirement in prod.
            self.bridge_require_l1_proof = True
            self.evm_create2_eip1014 = env_bool("EVM_CREATE2_EIP1014", True)
            self.evm_require_deploy_salt = env_bool("EVM_REQUIRE_DEPLOY_SALT", True)
            self.allow_state_root_rewrite = env_bool("ALLOW_STATE_ROOT_REWRITE", False)
            self.feature_zk = env_bool("FEATURE_ZK", False)
            self.feature_minivm = env_bool("FEATURE_MINIVM", False)
            self.feature_sharding = env_bool("FEATURE_SHARDING", False)
            self.feature_oracles = env_bool("FEATURE_ORACLES", False)
            self.feature_wasm = env_bool("FEATURE_WASM", False)
            self.feature_plasma = env_bool("FEATURE_PLASMA", False)
            self.feature_lightning = env_bool("FEATURE_LIGHTNING", False)
            self.feature_pq = env_bool("FEATURE_PQ", False)
            self.feature_nft = env_bool("FEATURE_NFT", False)
            self.feature_mev = env_bool("FEATURE_MEV", False)
            self.feature_ai_agents = env_bool("FEATURE_AI_AGENTS", False)
            self.feature_ai_validator = env_bool("FEATURE_AI_VALIDATOR", False)
            self.feature_smart_accounts = env_bool("FEATURE_SMART_ACCOUNTS", False)
            self.feature_validator_selection = env_bool(
                "FEATURE_VALIDATOR_SELECTION", False
            )
            # Profile F: Long-Range stays hard-off in prod (env cannot enable).
            # ADR 0020: feature_libp2p may be enabled on Experimental mesh JSON/env.
            self.feature_long_range = False
            # Fail-closed: env cannot weaken these for prod (break-glass forbidden).
            self.require_wallet_file = True
            self.require_signatures = True
            self.enforce_proposer = True
            self.verify_peer_state_root = True
            self.state_root_strict_p2p = True
            self.jwt_enforce_admin = True
            self.rpc_api_key_required = True
            self.allow_insecure_public_bind = False
            self.p2p_tls_fail_closed = True
            self.p2p_tls_bind_identity = True
            if str(self.consensus_mode or "").strip().lower() == "parallel":
                self.consensus_mode = "unified"
            if int(self.rate_limit_rpm or 0) <= 0:
                self.rate_limit_rpm = 120
            if self.cors_origins == ["*"]:
                self.cors_origins = env_list("CORS_ORIGINS", [])

        return self

    def apply_env_secrets(self) -> "Config":
        """Re-apply credential fields from env after JSON load (secrets stay out of node JSON)."""
        manifest_path = env_str("VALIDATORS_MANIFEST_PATH", "")
        if manifest_path:
            self.validators_manifest_path = manifest_path
        rpc_keys = env_list("RPC_API_KEYS")
        if rpc_keys:
            self.rpc_api_keys = rpc_keys
        oracle_secret = env_str("BRIDGE_ORACLE_SECRET", "")
        if oracle_secret:
            self.bridge_oracle_secret = oracle_secret
        origins = env_list("CORS_ORIGINS")
        if origins:
            self.cors_origins = origins
        rust_path = env_str("RUST_BRIDGE_PATH", "")
        if rust_path:
            self.rust_bridge_path = rust_path
        l1_queue = env_str("BRIDGE_L1_QUEUE_PATH", "")
        if l1_queue:
            self.bridge_l1_queue_path = l1_queue
        l1_chain = env_str("BRIDGE_L1_CHAIN", "")
        if l1_chain:
            self.bridge_l1_chain = l1_chain
        lock_contract = env_str("BRIDGE_L1_LOCK_CONTRACT", "")
        if lock_contract:
            self.bridge_l1_lock_contract = lock_contract
        mint_contract = env_str("BRIDGE_L1_MINT_CONTRACT", "")
        if mint_contract:
            self.bridge_l1_mint_contract = mint_contract
        if "BRIDGE_ENABLED" in os.environ:
            self.bridge_enabled = env_bool("BRIDGE_ENABLED", self.bridge_enabled)
        if "BRIDGE_REQUIRE_L1_PROOF" in os.environ:
            if self.is_production:
                # Env cannot weaken prod L1-proof invariant.
                self.bridge_require_l1_proof = True
            else:
                self.bridge_require_l1_proof = env_bool(
                    "BRIDGE_REQUIRE_L1_PROOF", self.bridge_require_l1_proof
                )
        elif self.is_production:
            self.bridge_require_l1_proof = True
        return self

    def validate(self) -> List[str]:
        """Возвращает список ошибок конфигурации (пустой = OK)."""
        errors = []

        def weak_secret(value: str, min_len: int = 24) -> bool:
            from runtime.secret_utils import is_placeholder_secret
            return is_placeholder_secret(value) or len(value.strip()) < min_len

        for name, port in [
            ("rpc_port", self.rpc_port),
            ("http_port", self.http_port),
            ("p2p_port", self.p2p_port),
            ("ws_port", self.ws_port),
        ]:
            if not (1 <= port <= 65535):
                errors.append(f"{name} invalid: {port}")
        if self.deployment_mode not in ("dev", "staging", "prod"):
            errors.append(f"deployment_mode invalid: {self.deployment_mode}")
        if self.is_production and self.require_wallet_file:
            wallet = os.path.join(
                os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else "data",
                "wallet.json",
            )
            if not os.path.isfile(wallet):
                errors.append(f"prod mode requires wallet file: {wallet}")
        if self.rpc_api_key_required:
            if not self.rpc_api_keys:
                errors.append("RPC_API_KEY_REQUIRED=true but RPC_API_KEYS is empty")
            else:
                weak_keys = [k for k in self.rpc_api_keys if weak_secret(str(k))]
                if weak_keys:
                    errors.append("RPC_API_KEYS contains placeholder or weak key")
        if self.bridge_mode not in ("simulator", "rust", "fake"):
            errors.append(f"bridge_mode invalid: {self.bridge_mode}")
        if self.bridge_mode == "rust":
            resolved = self.resolve_rust_bridge_path()
            if not os.path.isfile(resolved):
                msg = f"bridge_mode=rust but binary missing: {resolved}"
                # Industrial mesh keeps bridge_mode=rust (simulator/fake forbidden)
                # while bridge_enabled=false until L1 contracts. Missing abs_bridge_bin
                # is an error only when the bridge is actually on (MAINNET_GAP / v1.3.09).
                if self.is_production and self.bridge_enabled:
                    errors.append(msg)
        if self.is_production and self.bridge_mode == "simulator":
            errors.append("prod deployment should use bridge_mode=rust (or disable bridge)")
        if self.is_production and self.bridge_mode == "fake":
            errors.append("prod deployment forbids bridge_mode=fake")
        if self.is_production and self.bridge_dev_adapter_enabled:
            errors.append("prod deployment forbids BRIDGE_DEV_ADAPTER_ENABLED")
        if self.is_production:
            if not self.cors_origins:
                errors.append("prod mode requires CORS_ORIGINS")
            if "*" in self.cors_origins:
                errors.append("prod mode forbids wildcard CORS_ORIGINS")
            if any(o.startswith("http://localhost") or o.startswith("http://127.") for o in self.cors_origins):
                errors.append("prod mode forbids localhost CORS_ORIGINS")
            blocked = {
                "FEATURE_ZK": self.feature_zk,
                "FEATURE_MINIVM": self.feature_minivm,
                "FEATURE_SHARDING": self.feature_sharding,
                "FEATURE_ORACLES": self.feature_oracles,
                "FEATURE_WASM": self.feature_wasm,
                "FEATURE_PLASMA": self.feature_plasma,
                "FEATURE_LIGHTNING": self.feature_lightning,
                "FEATURE_PQ": self.feature_pq,
                "FEATURE_NFT": self.feature_nft,
                "FEATURE_MEV": self.feature_mev,
                "FEATURE_AI_AGENTS": self.feature_ai_agents,
                "FEATURE_AI_VALIDATOR": self.feature_ai_validator,
                "FEATURE_SMART_ACCOUNTS": self.feature_smart_accounts,
                "FEATURE_VALIDATOR_SELECTION": self.feature_validator_selection,
            }
            enabled_blocked = [name for name, enabled in blocked.items() if enabled]
            if enabled_blocked:
                errors.append(
                    "prod deployment blocks dev/test/routing/offchain features: "
                    + ", ".join(enabled_blocked)
                )
            if not self.require_native_crypto:
                errors.append("prod mode requires ABS_REQUIRE_NATIVE_CRYPTO=true")
            if not self.p2p_native_transport and not self.feature_libp2p:
                errors.append(
                    "prod mode requires p2p_native_transport=true "
                    "(native TCP+TLS data plane; set P2P_NATIVE_TRANSPORT=true) "
                    "or feature_libp2p=true (ADR 0020 rust-libp2p mesh)"
                )
            if not self.evm_create2_eip1014:
                errors.append("prod mode requires evm_create2_eip1014=true")
            if not self.evm_require_deploy_salt:
                errors.append("prod mode requires evm_require_deploy_salt=true")
            if not self.tip_safety_enforce:
                errors.append(
                    "prod mode requires tip_safety_enforce=true "
                    "(TIP_SAFETY_ENFORCE=true; tip/finality import gate)"
                )
            if int(self.chain_id or 0) == 77777:
                errors.append(
                    "prod chain_id 77777 is devnet default; assign unique mainnet chain_id"
                )
        if self.require_native_crypto:
            try:
                from crypto import native
                if not native.native_available():
                    errors.append("ABS_REQUIRE_NATIVE_CRYPTO=true but abs_native is unavailable")
                elif not hasattr(native, "evm_run_until_halt"):
                    errors.append(
                        "ABS_REQUIRE_NATIVE_CRYPTO=true but abs_native lacks evm_run_until_halt "
                        "(rebuild native wheel)"
                    )
                else:
                    st = native.native_crypto_status(required=True)
                    if not st.get("self_test"):
                        errors.append(
                            "ABS_REQUIRE_NATIVE_CRYPTO=true but native self_test failed: "
                            + str(st.get("error") or st)
                        )
                    if self.p2p_native_transport and not getattr(
                        native, "p2p_native_transport_available", lambda: False
                    )():
                        errors.append(
                            "p2p_native_transport=true but abs_native P2P transport unavailable "
                            "(rebuild native wheel with p2p_transport)"
                        )
            except Exception as e:
                errors.append(f"ABS_REQUIRE_NATIVE_CRYPTO=true but native crypto check failed: {e}")
        if self.deployment_mode != "dev" and not self.allow_insecure_public_bind:
            public_http = self.http_host in ("0.0.0.0", "::", "")
            public_rpc = self.rpc_host in ("0.0.0.0", "::", "")
            if public_http and not self.jwt_enforce_admin:
                errors.append("non-dev public HTTP bind requires JWT_ENFORCE_ADMIN=true")
            if public_rpc and not self.rpc_api_key_required:
                errors.append("non-dev public RPC bind requires RPC_API_KEY_REQUIRED=true")
            if (public_http or public_rpc) and "*" in self.cors_origins:
                errors.append("non-dev public bind forbids wildcard CORS_ORIGINS")
        if self.is_production:
            if not self.require_signatures:
                errors.append("prod mode requires REQUIRE_SIGNATURES=true")
            if not self.enforce_proposer:
                errors.append("prod mode requires ENFORCE_PROPOSER=true")
            if not self.verify_peer_state_root:
                errors.append("prod mode requires VERIFY_PEER_STATE_ROOT=true")
            if not self.jwt_enforce_admin:
                errors.append("prod mode requires JWT_ENFORCE_ADMIN=true")
            if not self.rpc_api_key_required:
                errors.append("prod mode requires RPC_API_KEY_REQUIRED=true")
            if int(self.rate_limit_rpm or 0) <= 0:
                errors.append("prod mode forbids RATE_LIMIT_RPM=0 (rate limit required)")
            if self.allow_insecure_public_bind:
                errors.append(
                    "prod mode forbids ALLOW_INSECURE_PUBLIC_BIND "
                    "(break-glass not allowed on mainnet-prep profiles)"
                )
            if not self.state_root_strict_p2p:
                errors.append("prod mode requires state_root_strict_p2p=true")
            if self.allow_state_root_rewrite:
                errors.append(
                    "prod mode forbids allow_state_root_rewrite "
                    "(set ALLOW_STATE_ROOT_REWRITE=false; genesis h=0 align still allowed)"
                )
            jwt_secret = os.environ.get("JWT_SECRET") or getattr(self, "jwt_secret", "")
            if not jwt_secret:
                errors.append("prod mode requires JWT_SECRET")
            elif weak_secret(jwt_secret, min_len=32):
                errors.append(
                    "prod JWT_SECRET is placeholder or too short "
                    "(HS256 requires >= 32 bytes)"
                )
        if self.is_production and self.bridge_enabled:
            if env_bool("BRIDGE_ALLOW_SYNTHETIC", False):
                errors.append("prod bridge forbids BRIDGE_ALLOW_SYNTHETIC (local dev only)")
            if int(getattr(self, "bridge_auto_confirm_sec", 0) or 0) > 0:
                errors.append("prod bridge forbids BRIDGE_AUTO_CONFIRM_SEC > 0 (dev simulator only)")
            if self.bridge_mode == "rust":
                try:
                    from bridge.health import check_rust_bridge_binary
                    bridge_status = check_rust_bridge_binary(self.resolve_rust_bridge_path())
                    if not bridge_status.get("ok"):
                        errors.append(
                            "prod bridge rust binary smoke-test failed: "
                            + str(bridge_status.get("error") or bridge_status)
                        )
                except Exception as e:
                    errors.append(f"prod bridge rust binary smoke-test failed: {e}")
            if not self.bridge_oracle_secret:
                errors.append("prod bridge requires BRIDGE_ORACLE_SECRET for relayer callbacks")
            elif weak_secret(self.bridge_oracle_secret):
                errors.append("prod BRIDGE_ORACLE_SECRET is placeholder or too short")
            l1_rpc = [
                os.environ.get("ETH_RPC_URL", "").strip(),
                os.environ.get("BSC_RPC_URL", "").strip(),
                os.environ.get("POLYGON_RPC_URL", "").strip(),
            ]
            if not any(l1_rpc):
                errors.append("prod bridge requires at least one L1 RPC URL (ETH_RPC_URL/BSC_RPC_URL/POLYGON_RPC_URL)")
            if not self.bridge_require_l1_proof:
                errors.append("prod bridge requires BRIDGE_REQUIRE_L1_PROOF=true")
            if not self.bridge_require_l1_event:
                errors.append(
                    "prod bridge requires BRIDGE_REQUIRE_L1_EVENT=true (semantic L1 bind, v1.3.68)"
                )
            if os.environ.get("BRIDGE_REQUIRE_L1_PROOF", "").strip().lower() in (
                "0",
                "false",
                "no",
                "off",
            ):
                errors.append(
                    "prod forbids BRIDGE_REQUIRE_L1_PROOF=false "
                    "(env cannot weaken L1 proof requirement)"
                )
            if self.bridge_require_l1_event:
                lock = str(getattr(self, "bridge_l1_lock_contract", "") or "").strip().lower()
                if not lock.startswith("0x") or len(lock) < 42 or "placeholder" in lock:
                    errors.append(
                        "BRIDGE_REQUIRE_L1_EVENT=true requires a real BRIDGE_L1_LOCK_CONTRACT"
                    )
            if not str(getattr(self, "bridge_l1_queue_path", "") or "").strip():
                errors.append("prod bridge requires BRIDGE_L1_QUEUE_PATH (L1 proof queue)")
            from bridge.health import should_probe_l1_rpc

            if should_probe_l1_rpc(self):
                from bridge.l1_rpc import (
                    configured_l1_rpc_urls,
                    is_placeholder_l1_rpc_url,
                    probe_configured_l1_rpcs,
                )

                for key, url in configured_l1_rpc_urls().items():
                    if is_placeholder_l1_rpc_url(url):
                        errors.append(
                            f"prod bridge {key} is a placeholder URL; "
                            "set a real L1 RPC endpoint before enabling bridge"
                        )
                if not any("placeholder URL" in e for e in errors):
                    try:
                        probe = probe_configured_l1_rpcs()
                        if not probe.get("ok"):
                            errors.append(
                                "prod L1 RPC reachability probe failed: "
                                + str(probe.get("error") or probe)
                            )
                    except Exception as e:
                        errors.append(f"prod L1 RPC reachability probe failed: {e}")
        if self.is_production:
            if not self.validators_manifest_path:
                errors.append("prod mode requires validators_manifest_path")
            else:
                try:
                    from runtime.genesis_ceremony import verify_live_manifest

                    # Prod default strict; break-glass: GENESIS_STRICT_MAINNET=false
                    strict = env_bool("GENESIS_STRICT_MAINNET", True)
                    manifest_errors, _artifact = verify_live_manifest(
                        self,
                        strict_addresses=strict,
                    )
                    errors.extend([f"validators_manifest:{e}" for e in manifest_errors])
                except Exception as e:
                    errors.append(f"validators_manifest:check_failed:{e}")
            mode = str(getattr(self, "consensus_mode", "auto") or "auto").strip().lower()
            if mode == "parallel":
                errors.append("prod forbids consensus_mode=parallel (use unified or auto)")
        if str(self.deployment_mode or "").lower() == "staging":
            mode = str(getattr(self, "consensus_mode", "auto") or "auto").strip().lower()
            if mode == "parallel":
                errors.append(
                    "staging forbids consensus_mode=parallel (use unified or auto)"
                )
        if self.is_production:
            if not self.p2p_tls_fail_closed:
                errors.append("prod requires p2p_tls_fail_closed=true")
            if not self.p2p_tls_bind_identity:
                errors.append("prod requires p2p_tls_bind_identity=true")
            mesh_min = int(getattr(self, "mesh_min_peers_before_mine", 0) or 0)
            if mesh_min >= 1:
                if not self.redis_rate_limit_enabled:
                    errors.append("prod mesh requires redis_rate_limit_enabled=true (REDIS_RATE_LIMIT)")
                if not str(self.redis_url or "").strip():
                    errors.append("prod mesh requires REDIS_URL")
        if self.p2p_tls_enabled:
            for attr, label in (
                ("p2p_tls_cert_path", "P2P_TLS_CERT_PATH"),
                ("p2p_tls_key_path", "P2P_TLS_KEY_PATH"),
                ("p2p_tls_ca_path", "P2P_TLS_CA_PATH"),
            ):
                if not str(getattr(self, attr, "") or "").strip():
                    errors.append(f"p2p_tls_enabled requires {label}")
            if self.is_production and self.p2p_tls_require_client_cert:
                if not str(self.p2p_tls_ca_path or "").strip():
                    errors.append("prod mTLS requires P2P_TLS_CA_PATH")
        return errors

    def __repr__(self) -> str:
        return (
            f"Config(chain={self.chain_id} '{self.network_name}', "
            f"rpc=:{self.rpc_port}, http=:{self.http_port}, "
            f"p2p=:{self.p2p_port}, db='{self.db_path}')"
        )
