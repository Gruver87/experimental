# Porting Roadmap — Hybrid Industrial Blockchain

Goal: move deterministic, CPU-bound, and consensus-critical code to **Rust/PyO3** while keeping **Python** as the orchestration layer. Each step ships with unit tests, CI gates, and a Python fallback only for dev (prod requires `ABS_REQUIRE_NATIVE_CRYPTO=true`).

## Python stays (orchestration layer)

| Module | Why Python |
|--------|------------|
| `main.py`, node lifecycle | Fast iteration, config, signals |
| `api/http.py`, `rpc/server.py` | REST/RPC routing, OpenAPI, admin gates |
| `network/p2p_node.py` | Async gossip, peer management |
| `sync/sync_engine.py` | Sync policy; calls Rust validators |
| `storage/database.py` | SQLite I/O, migrations |
| `consensus/*` adapters | PoS policy, slashing rules |
| `runtime/*`, `scripts/*` | Devnet, CI, Docker, prod gates |
| `web/explorer/` | Browser UI |

## Rust owns (industrial kernels)

| Crate | Kernels | Status |
|-------|---------|--------|
| `native/abs_native` (PyO3) | SHA-256, batch SHA-256, hash_text, block_header_hash, Merkle, state_root, secp256k1 verify, hash_chain validation | **Active** |
| `bridge/rust_bridge` (CLI) | L1 RPC proof, real ETH/BSC/Polygon confirmations | **Prod path** |

## Priority timeline

### Priority 1 — Crypto kernels ✅

- [x] `sha256`, `sha256_batch`, `double_sha256`
- [x] `merkle_root`, `generate_proof`, `verify_proof`
- [x] `state_root_from_accounts_json`
- [x] `verify_secp256k1_sha256` (+ batch)
- [x] `validate_hash_chain`
- Tests: `test_native_consensus_hash.py`, `test_state_root_native.py`

### Priority 2 — Consensus header hashing ✅ (this wave)

- [x] `hash_text`, `hash_text_batch` in Rust
- [x] `block_header_hash`, `block_header_hash_batch` in Rust
- [x] `core/block_header.py` wired to native kernels
- [x] `light/light_client.py` batch index via `BlockHeader.batch_hash`

### Priority 3 — Block import & validation ✅ (this wave)

- [x] `transaction_hash`, `transaction_hash_batch` in Rust
- [x] `block_canonical_hash_json`, `canonical_hash_json` in Rust
- [x] `core/blockchain.py` wired to native tx/block hash kernels
- [x] Batch tx signature verify on block import (`verify_transaction_signatures_batch`)
- Tests: `test_native_consensus_hash.py` golden vectors

### Priority 4 — Sync & P2P hardening ✅ (this wave)

- [x] `validate_imported_block_chain` — parent links + canonical block hash before P2P import
- [x] `validate_peer_header_chain` — SPV/light client header batch gate
- [x] `keccak256_hex` — real Ethereum Keccak-256 in Rust (not NIST SHA3-256)
- [x] `sync/sync_engine.py` wired to native imported-block validator
- [x] `light/light_client.py` rejects broken peer header chains
- [x] `parse_p2p_wire_line` / `encode_p2p_wire_message` — fail-closed wire envelope (size/UTF-8/JSON/allowlist)
- [x] `verify_attestation_secp256k1` + `hash_sorted_json` — attestation/tx hash+verify on gossip path
- [x] `network/p2p_node.py` PeerConnection send/recv wired to native wire kernels
- [x] `validate_p2p_status_payload` / `validate_p2p_attestation_payload` — gossip payload shape gates
- [x] `validate_p2p_block_announce` / `validate_p2p_state_root_request|response` — block & root gossip gates
- [x] `validate_p2p_handshake_payload` / `get_blocks` / `wire_tx` / `mempool_batch` — sync & tx gossip gates
- [x] `validate_p2p_validator_register` / `peers_list` / `get_block` / `get_block_by_hash` / `blocks_batch` — peer discovery & sync fetch gates
- [x] `validate_p2p_cross_shard_tx` / `cross_shard_ack` / `shard_migration` — distributed sharding gossip gates

### Priority 4d — Rust CI hygiene ✅

- [x] `abs_native` clippy `-D warnings` clean (crate allows for PyO3 false positives; mechanical lint fixes)
- [x] `rust_bridge` clippy `-D warnings` clean
- [x] `cargo fmt --check` clean for both crates (CI `test.yml`)
- [x] `MSG_BLOCK` fail-closed shape gate (null = not-found allowed; dict via `validate_p2p_block_announce`)
- [x] `dynamic_sharding.py` cross-shard tx_id via `native.sha256_hex`
- [x] `evm_interpreter.py` addr_int fallback hash via `native.sha256_hex`
- [x] `runtime/mainnet_constants.py` ceremony address seed via `native.sha256_hex`
- [x] `nft_core.py` mint token_id via `native.sha256_hex`
- [x] `api/http.py` bridge/devnet/wallet fallback hashes via `native.sha256_hex`
- [x] `crypto/tx_signer.py` transaction hash via `native.sha256_hex`
- [x] `features/*` + `main.py` + `bridge/dev_bridge_adapter.py` + `scripts/verify_p2p_ci.py` sha256 via native (PQ keep shake/sha3; HMAC keep stdlib)
- [x] `runtime/devnet_validators.py` + `crypto/sphincs_plus.py` sha256 via native

### Priority 4b — Consensus selection kernels ✅

- [x] `consensus_stake_weighted_proposer` / `consensus_fisher_yates_committee`
- [x] `validator_selection_*` (proposer, weighted, committee, shuffle)
- [x] `state_engine_root_from_accounts_json`

### Priority 4c — Amount + StateEngine apply ✅

- [x] `amount_to_satoshi` / `amount_apply_delta_satoshi` / `amount_from_satoshi_float`
- [x] `state_engine_apply_transactions` — in-memory batch apply (fee burned)
- [x] `runtime/amount.py` + `execution/state_engine.py` wired to native kernels
- [x] `plan_transfer_fees` / `can_afford_transfer` — L1 fee split + affordability gate
- [x] `core/blockchain.py` validate/apply simple + EVM fee paths use native planner

### Priority 5 — Bridge (no simulators in prod)

- [x] `BRIDGE_MODE=rust` enforced by `prod_gate.py`
- [x] Real L1 RPC (`ETH_RPC_URL`, `BSC_RPC_URL`, `POLYGON_RPC_URL`)
- [x] PyO3 bridge helper CLI (`scripts/native_bridge_helper.py`; rust CLI remains prod path)
- Dev-only: `bridge/mock_l1_rpc.py`, `bridge/dev_bridge_adapter.py` — **blocked in prod**

### Priority 6 — EVM execution ✅

- [x] EVM SHA3 opcode → native Ethereum Keccak-256
- [x] `evm_u256_*` arithmetic/bitwise kernels in Rust
- [x] `evm_keccak256_memory` for SHA3 memory slices
- [x] Mempool `add_batch` + `verify_signatures_batch` via native secp256k1
- [x] P2P `_handle_mempool_batch` → native batch mempool ingest
- [x] CREATE / CREATE2 legacy deploy addresses in Rust (`evm_deploy_address_*`)
- [x] Optional EIP-1014 CREATE2 via `evm_create2_eip1014` + `config.evm_create2_eip1014`
- [x] EVM compare opcodes (`EQ/LT/GT/ISZERO/BYTE`) + memory/calldata kernels in Rust
- [x] Extended arithmetic opcodes (`SDIV/SMOD/ADDMOD/MULMOD/EXP/SIGNEXTEND`) + native MSTORE
- [x] Native PUSH decode (`evm_read_push`) + EXTCODECOPY memory kernel
- [x] Jumpdest bitmap + EIP-150 call gas cap + address masking in Rust
- [x] Native stack DUP/SWAP + memory slice for CALL/CREATE calldata
- [x] Native bytecode scan + gas remaining; validator sync with all interpreter opcodes
- [x] Pure-opcode segment runner (`evm_run_pure_until_host`) + interpreter host-boundary loop
- [x] Native env opcodes + SLOAD/SSTORE in pure runner (static host context)
- [x] Host bridge for BALANCE / EXTCODE* / BLOCKHASH in native pure runner
- [x] Runtime bridge for CALL / CREATE / LOG / SELFDESTRUCT via apply_host_op
- [x] `evm_run_until_halt` — full bytecode dispatch loop in Rust with runtime bridge
- [x] Inline Rust bridge callbacks via `host_context.bridge_state` / `bridge_hooks`

### Priority 7 — Bridge hardening ✅

- [x] Prod config validates rust bridge binary smoke-test (`config.validate`)
- [x] Prod requires L1 RPC URLs + `BRIDGE_REQUIRE_L1_PROOF`
- [x] Runtime bridge health in `/metrics` and API overview
- [x] Live L1 RPC reachability probe at startup (opt-in: `BRIDGE_PROBE_L1_RPC=true`)
- [x] L1 RPC health in `/health/ready`, `/metrics`, and Prometheus alerts

### Priority 8 — Operational tooling ✅

- [x] Full test entry: `scripts/test_all.ps1` / `test_all.sh`
- [x] Production stack gate: `scripts/verify_prod_stack.py`
- [x] Live prod smoke: `scripts/prod_smoke.py`
- [x] Release gate: `scripts/release_gate.ps1`
- [x] Multi-node P2P smoke: `scripts/multi_node_smoke.ps1` / `.sh`
- [x] Docker prod: node + relayer sidecar
- [x] Grafana panels for native crypto / bridge / L1 RPC metrics

### Priority 9 — Industrialization (simulators → real network) ✅

- [x] `.env.example` default `BRIDGE_MODE=rust` (simulator explicit opt-in)
- [x] Keccak fallback: no wrong `sha3_256`; require native or pycryptodome
- [x] `node.industrial.json` / `node2.industrial.json` — prod-like devnet profile
- [x] `start_two_nodes.ps1 -Industrial` — native crypto + rust bridge + no L2 demos
- [x] JSON-RPC wallet wave: `eth_accounts`, `eth_getStorageAt`, `eth_feeHistory`, MetaMask block fields
- [x] Solidity 0.8+ opcodes: `SLT`, `SAR`, `PC`, `MSIZE`, `SELFBALANCE`, `BASEFEE` (native + Python fallback)
- [x] Block/env opcodes: `GASPRICE`, `COINBASE`, `DIFFICULTY`, `EXTCODEHASH`
- [x] Cancun opcodes: `SGT`, `TLOAD`, `TSTORE`, `MCOPY` (Python + native pure runner SGT)
- [x] `evm_u256_slt` signed-compare fix (both-negative operands)
- [x] `eth_sendRawTransaction`: RLP decode (legacy + EIP-1559) + native `recover_eth_address_keccak`
- [x] Tests: `test_evm_extended_opcodes.py`, `test_eth_raw_tx.py`
- [x] Full EVM opcode coverage for Shanghai/Cancun (BLOBHASH, BLOBBASEFEE; EOF/blob tx optional)
- [x] Distributed sharding MVP: `shard_mode=distributed`, `assigned_shard_id`, separate DBs, P2P `cross_shard_tx`/`cross_shard_ack`
- [x] `node.shard0.json` / `node.shard1.json`, `scripts/start_shard_devnet.ps1`
- [x] Tests: `test_distributed_sharding.py`
- [x] Cross-shard 2PC quorum coordinator + resharding planner (`consensus/cross_shard_coordinator.py`)
- [x] Live resharding migrations: discover/apply API, P2P `shard_migration`, coordinator debit/credit
- [x] Multi-validator per-shard quorum (2/3 committee ACKs, manifest `shard_id`, `/sharding/cross-shard/quorum/{tx_id}`)
- [x] Cross-shard committee gossip ACK fan-out (`MSG_CROSS_SHARD_ACK`, relay dedup, `POST /sharding/cross-shard/ack`)
- [x] Public validator set registry: `validators.manifest.example.json`, `runtime/validator_loader.py`, `/validators/registry`, prod gate
- [x] Validator key provider interface: local wallet + external HSM/KMS HTTP signer (`VALIDATOR_KEY_PROVIDER`)
- [x] Validator AWS KMS provider (`VALIDATOR_KEY_PROVIDER=aws_kms`, `AWS_KMS_KEY_ID`)
- [x] Validator GCP KMS provider (`VALIDATOR_KEY_PROVIDER=gcp_kms`, `GCP_KMS_KEY_VERSION`)
- [x] Validator GCP Cloud HSM provider (`VALIDATOR_KEY_PROVIDER=gcp_cloudhsm`, HSM protection_level gate)
- [x] P2P catch-up hardening: `catch_up_sync` retry loop, `verify_p2p_ci` devnet preflight, live audit skip/extend
- [x] Validator AWS CloudHSM proxy (`VALIDATOR_KEY_PROVIDER=aws_cloudhsm`, `AWS_CLOUDHSM_SIGNER_URL`)
- [x] JSON-RPC `eth_getLogs` filters + `eth_sendRawTransaction` RLP
- [x] JSON-RPC polling filters: `eth_newFilter`, `eth_getFilterChanges`, `eth_getFilterLogs`, block/pending filters
- [x] JSON-RPC WebSocket subscriptions (`eth_subscribe` / `eth_unsubscribe`: newHeads, logs, newPendingTransactions)
- [x] Pre-mainnet audit runner: `scripts/pre_mainnet_audit.py` (static gate + JSON report + external checklist)
- [ ] External security audit before public mainnet (third-party firm; track via `scripts/external_audit_tracker.py`)
- [x] Mainnet gap analysis doc (`docs/MAINNET_GAP_ANALYSIS.md`)
- [x] Strict external audit gate in `mainnet_readiness.py` (default; `--no-strict-audit` for dev)
- [x] Prod EVM: `evm_require_deploy_salt`, `evm_create2_eip1014` required in prod config
- [x] Prod bridge: Solana blocked; L1 chains ethereum/bsc/polygon only in rust path
- [x] Prod `chain_id` must not be devnet default `77777` (placeholder `778888` in prod examples)
- [x] Prod smoke spawn (`verify_p2p_ci --mode prod-smoke`) + E2E prod boot test
- [x] `scripts/industrial_gate.py` — code gate without external audit blockers
- [x] CI: industrial gate + prod P2P smoke on Linux
- [x] Mainnet v1 config without bridge (`node.prod.mainnet-v1.example.json`)
- [x] State harness `canonical_state_root_source: blockchain.database`
- [x] PyO3 bridge helper CLI: `scripts/native_bridge_helper.py`
- Dev-only (keep blocked in prod): `bridge_mode=simulator`, `mock_l1_rpc`, `feature_wasm/plasma/lightning/pq/zk`

### Priority 10 — Mainnet launch 🔄

- [x] Mainnet readiness gate: `scripts/mainnet_readiness.py` / `.ps1` (prod stack + pre-mainnet audit)
- [x] Release gate `-Mainnet` flag: `scripts/release_gate.ps1 -Mainnet`
- [ ] External security audit before public mainnet (third-party firm; track via `scripts/external_audit_tracker.py`)
- [x] Mainnet gap analysis doc (`docs/MAINNET_GAP_ANALYSIS.md`)
- [x] Strict external audit gate in `mainnet_readiness.py` (default; `--no-strict-audit` for dev)
- [x] Prod EVM: `evm_require_deploy_salt`, `evm_create2_eip1014` required in prod config
- [x] Prod bridge: Solana blocked; L1 chains ethereum/bsc/polygon only in rust path
- [x] Prod `chain_id` must not be devnet default `77777` (placeholder `778888` in prod examples)
- [x] Prod smoke spawn (`verify_p2p_ci --mode prod-smoke`) + E2E prod boot test
- [x] `scripts/industrial_gate.py` — code gate without external audit blockers
- [x] CI: industrial gate + prod P2P smoke on Linux
- [x] Mainnet v1 config without bridge (`node.prod.mainnet-v1.example.json`)
- [x] State harness `canonical_state_root_source: blockchain.database`
- [x] Public mainnet genesis + validator set ceremony (`genesis_ceremony.py`, `GET /chain/genesis/ceremony`)
- [x] EIP-4844 blob transaction type in `eth_sendRawTransaction` (type 0x03 decode + verify)
- [x] EOF container rejected at deploy (`eof_container_not_supported`; full EOF VM optional)

### Priority 11 — Fork-choice + simple state mutation kernels ✅ (v1.3.38)

- [x] `ghost_select_head` / `ghost_cumulative_weight` / `ghost_chain_from_head` in Rust
- [x] `lmd_compute_weights` in Rust; `consensus/ghost.py` + `lmd.py` wired
- [x] `blockchain_apply_simple_block` — fee/burn/proposer + reward (no EVM calldata)
- [x] `blockchain_replay_simple_blocks` — reorg/tip-repair assist for simple chains
- [x] `core/blockchain.py` prefers native apply/replay; falls back to Python per-tx on EVM/error
- Remaining (next waves): mixed simple+EVM native apply

### Priority 12 — Finality FFG + slashing conflict kernels ✅ (v1.3.39)

- [x] `ffg_threshold` / `ffg_best_checkpoint` / `ffg_accumulate_vote` / `ffg_evaluate_epoch`
- [x] `fe_epoch` / `fe_quorum_reached` / `fe_can_finalize` (FinalityEngine count path)
- [x] `slash_check_double_vote` / `slash_check_double_proposal`
- [x] Wired in `finality_casper.py`, `finality_beacon.py`, `finality_engine.py`, `slashing.py`
- Remaining: P2P rate-limit · full EVM host-in-apply

### Priority 13 — Eth raw tx decode kernel ✅ (v1.3.40)

- [x] `decode_eth_raw_tx` / `decode_eth_raw_tx_hex` — legacy / EIP-1559 / EIP-4844 + recover
- [x] `crypto/eth_tx.py` prefers native JSON; blob_hashes coerced to int
- Remaining: P2P rate-limit · full EVM host-in-apply

### Priority 14 — EVM host storage snapshot around runner ✅ (v1.3.41)

- [x] `evm_host_snapshot_storage` / `evm_host_restore_storage`
- [x] `evm_run_until_halt` restores storage on REVERT / OOG / error
- [x] `evm_interpreter.execute_bytecode` framesnap + restore; adapter fail-closed writeback on revert
- Remaining: P2P rate-limit · full EVM host-in-apply

### Priority 15 — Rocks typed key codecs ✅ (v1.3.42)

- [x] `rocks_keycodec.rs` — pack/unpack + all Rocks key/prefix builders
- [x] `storage/keycodec.py` prefers abs_native; Python fallback retained
- Remaining: P2P rate-limit · full EVM host-in-apply

### Priority 16 — P2P rate-limit / strike table ✅ (v1.3.43)

- [x] `P2PRateLimitTable` — per-peer window + strikes + bans
- [x] `p2p_rate_limit_tick` / `p2p_rate_limit_is_exempt` / `p2p_strike_should_ban`
- [x] `network/p2p_node.py` prefers native table; Python fallback retained
- Remaining: see Priority 17\r\n\r\n### Priority 17 — EVM host-in-apply fee effects ✅ (v1.3.44)

- [x] `blockchain_apply_host_effects` — fee/nonce/reward after Python EVM host
- [x] All-EVM blocks: host runs storage/code/value, native applies economics
- [x] v1.3.45: writeback preserves code/storage; no empty burn materialization; receipt status=1
- Remaining: see Priority 18

### Priority 18 — Mixed simple+EVM native apply ✅ (v1.3.46)

- [x] `_block_transactions_are_mixed` + `_apply_mixed_block_native`
- [x] Per-tx host_effects (reward=0) then final native reward; EVM host between
- [x] `create_block` nonce cursor honored via `validate_transaction(expected_nonce=…)`
- Remaining: see Priority 19

### Priority 19 — Nested CALL effects planner ✅ (v1.3.47)

- [x] `evm_plan_nested_call_effects` — read-only / persist / value policy kernel
- [x] `EVMAdapter._contract_call_hook` driven by planner; Python fallback retained
- Remaining: see Priority 20

### Priority 20 — Nested CALL gas planner ✅ (v1.3.48)

- [x] `evm_plan_nested_call_gas` — EIP-150 + 2300 stipend
- [x] `evm_interpreter._execute_call` uses planner for forwarded gas
- Remaining: see Priority 21

### Priority 21 — Nested CALL frame decode ✅ (v1.3.49)

- [x] `evm_decode_nested_call_frame` — pure CALL stack-frame decode (kind + fields)
- [x] `evm_host_bridge.apply_host_op` CALL branch uses decoder then `_execute_call`
- Remaining: see Priority 22

### Priority 22 — Nested pure bytecode frame ✅ (v1.3.50 first slice)

- [x] `evm_run_nested_pure_frame` — child frame via pure runner (no host_bridge)
- [x] `evm_bytecode_is_nested_pure_eligible` + adapter fast-path; fallback to Python on host/bridge
- Remaining: see Priority 23

### Priority 23 — Nested CALL native bridge surface ✅ (v1.3.55)

- [x] `evm_bytecode_is_nested_native_eligible` — bridge ops OK; recursive host still Python
- [x] `allow_bridge=True` keeps BALANCE/EXTCODE*/BLOCKHASH in abs_native nested frame
- Remaining: see Priority 24

### Priority 24 — Nested CALL/CREATE/LOG host frame ✅ (v1.3.56 first slice)

- [x] `evm_run_nested_host_frame` — child frame via full runner + `host_bridge`
- [x] Adapter wires recursive CALL/CREATE/LOG through Rust + `EvmRuntimeBridge`
- Remaining: see Priority 25

### Priority 25 — Host opcode bodies in Rust ✅ (v1.3.57)

- [x] LOG0–LOG4 gas/stack/memory + segment `logs[]` entirely in Rust
- [x] CALL/CREATE/SELFDESTRUCT bodies in Rust via thin `bridge_hooks`
- Remaining: see Priority 26

### Priority 26 — Native account view decode ✅ (v1.3.58 first slice)

- [x] `account_view_from_blob` / `account_storage_map_from_raw` — fail-closed decode
- [x] `RocksEngine.get_account_view` + adapter `_account_view` nested CALL preload
- Remaining: see Priority 27

### Priority 27 — Nested CALL writeback ops ✅ (v1.3.59)

- [x] `evm_plan_nested_call_writeback` — concrete `ops[]` (set_storage / transfer_value / append_logs)
- [x] Adapter `_apply_nested_writeback_ops` applies via Python DB only
- Remaining: see Priority 28

### Priority 28 — CREATE writeback ops ✅ (v1.3.60)

- [x] `evm_plan_create_writeback` — `save_account` + optional `transfer_value`
- [x] Adapter CREATE path applies via shared writeback ops (no double-credit balance)
- Remaining: see Priority 29

### Priority 29 — Native writeback apply ✅ (v1.3.61)

- [x] `evm_apply_writeback_ops` — in-memory accounts map transform
- [x] Adapter loads accounts → native apply → `save_account` commit + log persist
- Remaining: see Priority 30

### Priority 30 — Store-lock Rocks writeback commit ✅ (v1.3.62)

- [x] `RocksEngine.commit_account_rows` — batch put under caller-held store lock
- [x] `RocksChainStore.commit_writeback_accounts` / Hybrid delegate
- [x] Adapter prefers store-lock commit after native apply (logs still Python)
- Remaining: see Priority 31

### Priority 31 — Unified writeback bundle ✅ (v1.3.63)

- [x] `RocksEngine.commit_writeback_bundle` — one WriteBatch for accounts + dual log keys
- [x] `RocksChainStore.commit_writeback_bundle` / Hybrid delegate
- [x] Adapter commits accounts+logs under one store path after native apply
- Remaining: see Priority 32

### Priority 32 — Rocks batch writeback preload ✅ (v1.3.64)

- [x] `RocksEngine.get_account_rows` — batch account blob load for touched addresses
- [x] `RocksChainStore.load_writeback_accounts` / Hybrid delegate
- [x] Adapter preloads via Rocks before `evm_apply_writeback_ops`
- Remaining: see Priority 33

### Priority 33 — Tx-scoped writeback journal ✅ (v1.3.67)

- [x] Buffer nested CALL/CREATE writeback ops until top-level success
- [x] Discard journal on revert/exception
- Remaining: see Priority 34

### Priority 34 — Rust frame storage arena ✅ (v1.3.67)

- [x] SLOAD/SSTORE against Rust HashMap arena; flush to Python dict on exit
- Remaining: recursive native frames / block-scoped session (see Priority 35)

### Priority 35 — Block-scoped sat session ✅ (v1.3.69)

- [x] Mixed apply: in-memory sat session + single writeback
- [x] `scripts/verify_industrial_waves.py` for waves 65–68(+69)
- Remaining: see Priority 36

### Priority 36 — Recursive frame arena sync ✅ (v1.3.70)

- [x] Flush arena before nested CALL; re-sync after DELEGATECALL/CALLCODE merge
- [x] Live parent storage for recursive DELEGATECALL (`_abs_live_storage`)
- Remaining: see Priority 37

### Priority 37 — In-Rust inline leaf frame ✅ (v1.3.71)

- [x] Eligible DELEGATECALL/CALLCODE (value=0) push/pop inside parent Rust frame
- [x] Skip Python `contract_call` when leaf succeeds; fall through otherwise
- Remaining: see Priority 38 (EVM) + mesh admission (v1.3.72)

### Priority 37b — P2P sync admission + outbound honesty ✅ (v1.3.72)

- [x] Global sync inflight cap; outbound max_peers; outbound drop metrics
- [x] Config-driven send queue/drain; secondary exempt-type rate budget
- Remaining: see Priority 37c

### Priority 37c — Apply-queue priority lanes ✅ (v1.3.73)

- [x] PriorityQueue: REORG > FORGE > ADD > IMPORT
- Remaining: see Priority 38

### Priority 38 — value=0 CALL + multi-depth + value transfer ✅ (v1.3.74–v1.3.84)

- [x] Eligible value=0 CALL/STATICCALL leaf (v1.3.74)
- [x] Multi-depth call-frames (CALL*/LOG) with depth cap 4 (v1.3.75)
- [x] Value CALL via fail-closed `bridge_state.balances` (v1.3.76)
- [x] CALLCODE value via fail-closed balances (v1.3.79)
- [x] Simple CREATE (empty/STOP init) inline (v1.3.80)
- [x] CREATE2 empty/STOP init (EIP-1014 / legacy) (v1.3.81)
- [x] Eligible CREATE init with RETURN runtime (v1.3.82)
- [x] Inline value → `pending_writeback_ops` → adapter satoshi journal (v1.3.83)
- [x] Inline CREATE `save_account` journal (v1.3.84)
- EVM Priority 38 closed; P2P transport remains under Priority 39–40

### Isolation wave — apply under load ✅ (v1.3.51–v1.3.53)

- [x] v1.3.51: P2P/sync `import_block` off asyncio loop
- [x] v1.3.52: serial `ChainApplyQueue` (atomic forge_and_apply)
- [x] v1.3.53: dedicated sync executor + Prometheus apply metrics + backpressure honesty
- [x] v1.3.54: EVM/mempool high-load soak harness (`scripts/evm_mempool_load_harness.py`)
- [x] v1.3.55: nested CALL native bridge (BALANCE/EXTCODE*/BLOCKHASH via host_context)
- [x] v1.3.56: nested host frame (CALL/CREATE/LOG orchestration in Rust + bridge)
- [x] v1.3.57: host opcode bodies in Rust (thin hooks for state)
- [x] v1.3.58: native account-blob decode for nested CALL preload
- [x] v1.3.59: nested CALL writeback ops planned in Rust
- [x] v1.3.60: CREATE writeback ops planned in Rust
- [x] v1.3.61: native in-memory writeback apply
- [x] v1.3.62: store-lock Rocks writeback commit
- [x] v1.3.63: unified writeback bundle (accounts + logs)
- [x] v1.3.66: load backpressure + tip O(1)
- [x] v1.3.67: tx writeback journal + Rust storage arena
- [x] v1.3.68: bridge semantic event bind + fail-closed debit
- [x] v1.3.69: block-scoped sat session + verify_industrial_waves
- [x] v1.3.70: recursive frame arena sync + live DELEGATECALL storage
- [x] v1.3.71: in-Rust inline leaf frame (eligible DELEGATECALL/CALLCODE)
- [x] v1.3.72: P2P sync admission + outbound honesty
- [x] v1.3.73: apply-queue priority lanes (reorg>forge>add>import)
- [x] v1.3.74: value=0 CALL/STATICCALL inline leaf (Priority 38)
- [x] v1.3.75: multi-depth value=0 CALL frames (depth cap 4)
- [x] v1.3.76: value-transfer CALL (fail-closed bridge_state.balances)
- [x] v1.3.77: Rust P2P ingress admit (wire+rate) + connection governor
- [x] v1.3.78: per-peer bandwidth / cost-weighted ingress budget
- [x] v1.3.79: CALLCODE value (fail-closed bridge_state.balances)
- [x] v1.3.80: simple CREATE (empty/STOP init) inline
- [x] v1.3.81: CREATE2 empty/STOP (EIP-1014 default)
- [x] v1.3.82: CREATE eligible init → RETURN runtime
- [x] v1.3.83: inline value → pending_writeback_ops / satoshi journal
- [x] v1.3.84: inline CREATE → save_account writeback journal
- [x] v1.3.85: P2P outbound egress bandwidth (Priority 40)
- [x] v1.3.86: P2P NDJSON line framer (Priority 41)
- [x] v1.3.87: P2P unified egress prepare (Priority 42)
- [x] v1.3.88: P2P kernel fuzz_api + cargo-fuzz / smoke (Priority 43)
- [x] v1.3.89: P2P Sybil/Eclipse subnet + reserved slots (Priority 44)
- [x] v1.3.90: Native plain-TCP transport slice (Priority 45)
- [x] v1.3.91: Native rustls TLS on transport (Priority 46)
- [x] v1.3.92: Native read_message pump — frame+parse (Priority 47)
- [x] v1.3.93: Native write_message pump — encode+write (Priority 48)
- [x] v1.3.94: Native read_messages batch pump (Priority 49)
- [x] v1.3.95: Native write_messages / write_payloads batch (Priority 50)
- [x] v1.3.96: Native handshake_roundtrip I/O fuse (Priority 51)
- [x] v1.3.97: Native peer cert CN/SAN identities (Priority 52)
- [x] v1.3.98: Native auto-pong keepalive (Priority 53)
- [x] v1.3.99: Native keepalive consume / touch (Priority 54)
- [x] v1.3.100: Native housekeeping payload gate (Priority 55)
- [x] v1.3.101: Native batch/chunk config knobs (Priority 56)
- [x] v1.3.102: Native I/O timeout config (Priority 57)
- [x] v1.3.103: Native mid-session handshake gate (Priority 58)
- [x] v1.3.104: Native status payload gate (Priority 59)
- [x] v1.3.105: Native attestation shape gate (Priority 60)
- [x] v1.3.106: Native block sync shape gates (Priority 61)
- [x] v1.3.107: Native block fetch shape gates (Priority 62)
- [x] v1.3.108: Native tx gossip shape gates (Priority 63)
- [x] v1.3.109: Native singular block payload gate (Priority 64)
- [x] v1.3.110: Native peer discovery shape gates (Priority 65)
- [x] v1.3.111: Native state-root shape gates (Priority 66)
- [x] v1.3.112: Native cross-shard shape gates (Priority 67)
- [x] v1.3.113: Native handshake payload gate (Priority 68)
- [x] v1.3.114: Prod-mandatory native P2P transport + skip dual shape re-validate (Priority 69)

### Priority 39 — P2P Rust ingress data plane ✅ (v1.3.77–v1.3.78)

- [x] Unified native admit: decode → allowlist → primary/exempt rate
- [x] Connection governor: max_peers + per-IP inbound
- [x] Per-peer bandwidth / cost units (v1.3.78)

### Priority 40 — P2P outbound egress QoS ✅ (v1.3.85)

- [x] Separate egress byte window + cost weights (same as ingress)
- [x] `admit_egress` / `p2p_egress_admit` wired into send path

### Priority 41 — P2P NDJSON line framer ✅ (v1.3.86)

- [x] `P2PLineFramer` fail-closed extract before `\n`
- [x] `PeerConnection._read_wire_line` chunked read + framer
- Remaining: full Rust transport — TCP/TLS/message loop (not claimed)

### Priority 42 — P2P unified egress prepare ✅ (v1.3.87)

- [x] `p2p_egress_prepare`: encode + allowlist + size + egress admit
- [x] `PeerConnection._prepare_outbound` on send path
- Remaining: full Rust transport — TCP/TLS/message loop (not claimed)

### Priority 43 — P2P kernel fuzzing ✅ (v1.3.88)

- [x] `fuzz_api` + smoke (`cargo test`) + cargo-fuzz targets + CI
- Honesty: fuzz ≠ full audit; remaining: full Rust transport (not claimed)

### Priority 44 — P2P Sybil / Eclipse ✅ (v1.3.89)

- [x] Public-only subnet diversity + reserved outbound slots on native governor
- [x] Eclipse ratio telemetry + prune + Prometheus
- Honesty: not ASN/BGP; remaining: full Rust transport (not claimed)

### Priority 45 — Native plain-TCP transport slice ✅ (v1.3.90)

- [x] `P2PNativeListener` + `P2PNativeConn` framed I/O; opt-in wire-up
- Remaining: TLS in Rust (see Priority 46), full message loop ownership, libp2p (not claimed)

### Priority 46 — Native rustls TLS ✅ (v1.3.91)

- [x] rustls mTLS on native accept/connect; peer fingerprint; Python TLS+native co-enable
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 47 — Native read_message pump ✅ (v1.3.92)

- [x] `P2PNativeConn.read_message`: framed read + wire parse in one native call
- [x] `PeerConnection.recv` wired; rate admit stays Python on ingress path
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 48 — Native write_message pump ✅ (v1.3.93)

- [x] `P2PNativeConn.write_message`: wire encode + write in one native call
- [x] `PeerConnection._write_message` wired; egress prepare/admit stays Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 49 — Native read_messages batch ✅ (v1.3.94)

- [x] `P2PNativeConn.read_messages`: drain up to N decoded envelopes per call
- [x] `PeerConnection.recv` queues `_pending_msgs`; rate admit stays Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 50 — Native write_messages batch ✅ (v1.3.95)

- [x] `write_messages` + `write_payloads` on `P2PNativeConn`
- [x] `_send_loop` batch drain via `_write_messages_batch`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 51 — Native handshake_roundtrip ✅ (v1.3.96)

- [x] `handshake_roundtrip` I/O fuse on native conn
- [x] `_do_handshake` wired; validate/policy stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 52 — Native peer cert identities ✅ (v1.3.97)

- [x] CN/SAN extract via `x509-parser`; `peer_cert_identities` getter
- [x] Native TLS identity bind in `_do_handshake`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 53 — Native auto-pong keepalive ✅ (v1.3.98)

- [x] `auto_pong` on `read_message` / `read_messages`; ping answered in-band
- [x] Config `p2p_native_auto_pong`; Python recv wired
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 54 — Native keepalive consume ✅ (v1.3.99)

- [x] Consume inbound `pong`; `keepalive_touches` / `auto_keeps`
- [x] Empty keepalive batch → Python touch (synthetic pong)
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 55 — Native housekeeping payload gate ✅ (v1.3.100)

- [x] `housekeeping_payload_ok` parity with Python on native read
- [x] Malformed ping/pong/get_* rejected before auto-keepalive
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 56 — Native batch/chunk config ✅ (v1.3.101)

- [x] Config/env for read/write batch + read chunk
- [x] `p2p_native_clamp_batch` / `p2p_native_clamp_chunk`; status gauges
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 57 — Native I/O timeout config ✅ (v1.3.102)

- [x] `p2p_native_io_timeout_ms` → `set_timeout_ms` on accept/connect
- [x] Async recv `wait_for` aligned; `p2p_native_clamp_timeout_ms`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 58 — Native mid-session handshake gate ✅ (v1.3.103)

- [x] `session_established` + reject `handshake`/`handshake_ack` on native read
- [x] Wired after `_do_handshake`; WireReject → strike / handshake_rejects
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 59 — Native status payload gate ✅ (v1.3.104)

- [x] `check_status_payload` via `validate_status_inner` on native read
- [x] Null keepalive allowed; bad dict → `bad_status_payload`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 60 — Native attestation shape gate ✅ (v1.3.105)

- [x] `check_attestation_payload` via `validate_attestation_shape_inner`
- [x] Bad shape → `bad_attestation_shape` before Python sig verify
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 61 — Native block sync shape gates ✅ (v1.3.106)

- [x] `check_block_announce_payload` / `check_get_block_payload` on native read
- [x] Bad → `bad_block_announce` / `bad_get_block` before Python dispatch
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 62 — Native block fetch shape gates ✅ (v1.3.107)

- [x] `check_get_blocks_payload` / `check_get_block_by_hash_payload` / `check_blocks_batch_payload`
- [x] Bad → `bad_get_blocks` / `bad_get_block_by_hash` / `bad_blocks_batch`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 63 — Native tx gossip shape gates ✅ (v1.3.108)

- [x] `check_wire_tx_payload` / `check_mempool_batch_payload` on native read
- [x] Bad → `bad_wire_tx` / `bad_mempool_batch`; `check_ingress_shape_gates` helper
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 64 — Native singular block payload gate ✅ (v1.3.109)

- [x] `check_block_payload` on native read (null = not-found OK)
- [x] Bad non-null → `bad_block_payload` before Python dispatch
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 65 — Native peer discovery shape gates ✅ (v1.3.110)

- [x] `check_peers_list_payload` / `check_validator_register_payload` on native read
- [x] Bad → `bad_peers_list` / `bad_validator_register`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 66 — Native state-root shape gates ✅ (v1.3.111)

- [x] `check_state_root_request_payload` / `check_state_root_response_payload` on native read
- [x] Bad → `bad_state_root_request` / `bad_state_root_response`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 67 — Native cross-shard shape gates ✅ (v1.3.112)

- [x] `check_cross_shard_tx_payload` / `check_cross_shard_ack_payload` / `check_shard_migration_payload`
- [x] Bad → `bad_cross_shard_tx` / `bad_cross_shard_ack` / `bad_shard_migration`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 68 — Native handshake payload gate ✅ (v1.3.113)

- [x] `check_handshake_payload` on `handshake_roundtrip` inbound handshake/ack
- [x] Bad → `bad_handshake_payload`; chain-id / TLS policy stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 69 — Prod-mandatory native P2P transport ✅ (v1.3.114)

- [x] Prod default + `prod_gate` / config fail-closed for `p2p_native_transport`
- [x] No silent asyncio fallback when prod / `require_native_crypto` requires transport
- [x] Skip Python dual shape re-validate when `_use_native_transport`
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 70 — Native handshake policy fuse ✅ (v1.3.115)

- [x] `check_handshake_policy` on `handshake_roundtrip` (chain_id + TLS identity)
- [x] Skip Python dual chain/identity when native policy applied; fingerprint allowlist stays Python
- [x] Max-gate: `/health/ready` native listener + k8s/smoke `p2p_native_transport` sync
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 71 — Native message-loop event shell ✅ (v1.3.116)

- [x] `read_message_loop_events` ordered dispatch/strike/keepalive/idle/eof
- [x] Python `_message_loop` shell path; handlers + ban policy stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 72 — Native attestation semantic ingress ✅ (v1.3.117)

- [x] `verify_attestation_semantics_inner` on loop-shell before dispatch
- [x] Identity + secp256k1; tx semantic / mempool stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 73 — Native new_tx signature semantic ingress ✅ (v1.3.118)

- [x] `verify_wire_tx_signature_inner` on loop-shell (`expected_chain_id` + `require_tx_signatures`)
- [x] Mempool batch / nonce-balance / full dispatch stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 74 — Native mempool batch signature semantic ingress ✅ (v1.3.119)

- [x] `verify_mempool_batch_signatures_inner` on loop-shell (per-tx; same chain_id policy)
- [x] Nonce/balance ingest / full dispatch stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 75 — Native new_block canonical-hash semantic ingress ✅ (v1.3.120)

- [x] `verify_block_announce_semantics_inner` on loop-shell (claimed hash vs canonical recompute)
- [x] Parent/height / proposer / state_root / import stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 76 — Native blocks batch hash semantic ingress ✅ (v1.3.121)

- [x] `verify_blocks_batch_semantics_inner` on loop-shell (per-block hash; reuses announce gate)
- [x] Root Makefile Linux/macOS UX (does not replace PowerShell / existing CI)
- [x] Continuity / import / fork-choice stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 77 — Native singular block response hash semantic ingress ✅ (v1.3.122)

- [x] `check_block_payload_semantics` on loop-shell (null OK; non-null canonical hash)
- [x] Request correlation / import / fork-choice stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 78 — Native state_root_response digest semantic ingress ✅ (v1.3.123)

- [x] `verify_state_root_response_semantics_inner` on loop-shell (32-byte hex digests)
- [x] Correlation / root-belongs-to-head / sync ownership stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 79 — Native status.head_hash digest semantic ingress ✅ (v1.3.124)

- [x] `verify_status_head_hash_semantics_inner` on loop-shell (empty OK; non-empty 32-byte hex)
- [x] Height↔hash binding / peer auth stay Python
- Remaining: full message-loop ownership / libp2p (not claimed)

### Priority 80 — Request-bound blocks response + prod shell contract ✅ (v1.3.125)

- [x] `verify_blocks_response_semantics_inner` on sync waiters (range/continuity/parent + hashes)
- [x] Prod native transport fail-closed without `read_message_loop_events`
- [x] `/health/ready` exposes `p2p_native_message_loop_shell`
- Remaining: tip existence proof / fork-choice / full sync ownership / libp2p (not claimed)

### Priority 81 — Request-bound singular block response hash correlation ✅ (v1.3.126)

- [x] `verify_block_response_semantics_inner` on `get_block_by_hash` waiters
- [x] Null = not-found OK; mismatched hash never steers reconcile
- Remaining: tip existence proof / fork-choice / full sync ownership / libp2p (not claimed)

### Priority 82 — Request-bound state_root_response height correlation ✅ (v1.3.127)

- [x] `verify_state_root_response_request_semantics_inner` on state_root waiters
- [x] Height must match probe; digests remain gated
- Remaining: root-belongs-to-head / tip proof / full sync ownership / libp2p (not claimed)

### Priority 83 — Discovery dialability + soft height↔head binding ✅ (v1.3.128)

- [x] `p2p_peer_addr_is_dialable` on MSG_PEERS / GET_PEERS (`p2p_discovery_allow_private`)
- [x] Handshake + status soft height↔head (height>0 ⇒ digest head)
- Remaining: tip proof / DHT / libp2p / anti-Sybil / full sync ownership (not claimed)

### Priority 84 — Outbound state_root height honesty ✅ (v1.3.129)

- [x] `_state_root_response_for_height` — tip live vs historical header; ahead/missing refuse
- [x] Unsolicited `state_root_response` no longer inflates `peer.height`
- Remaining: tip proof / root-belongs-to-head crypto / libp2p (not claimed)

### Priority 85 — Soft expected_head + professional repo surface ✅ (v1.3.130)

- [x] `expected_head` on state_root waiters (`bad_state_root_response_head`)
- [x] Dependabot / EditorConfig / SUPPORT / AUDITS / RELEASING / SBOM workflow
- Remaining: external audit / ceremony pin / tip proof / libp2p (not claimed)

### Priority 86 — Solicit-only mempool + status height ahead cap ✅ (v1.3.131)

- [x] `request_ctx.kind=mempool` waiter; unsolicited `MSG_MEMPOOL` struck
- [x] `p2p_max_peer_height_ahead` caps mid-session status height inflation
- Remaining: tip proof / libp2p (not claimed)

### Priority 87 — Resilient bootstrap (sticky-first-peer fix) ✅ (v1.3.132)

- [x] Redial missing bootstrap seeds even when non-bootstrap peers exist
- [x] `dial_target` coverage for hostname→IP mismatch
- Remaining: tip proof / libp2p (not claimed)

### Priority 88 — Authenticated bootstrap seed pins ✅ (v1.3.133)

- [x] `P2P_BOOTSTRAP_PINS` / `bootstrap_pin_map` — host:port → TLS SHA-256 (+ optional node_id)
- [x] Handshake reject + coverage requires pin match when configured
- Remaining: tip proof / DHT trust roots / libp2p / ceremony (not claimed)

### Priority 89 — Soft NEW_BLOCK height-ahead ownership gate ✅ (v1.3.134)

- [x] `MSG_NEW_BLOCK` uses `p2p_max_peer_height_ahead` for peer.height/head ownership
- [x] Fantasy announces refused before sync/import steering
- Remaining: tip proof / fork-choice / libp2p (not claimed)

### Priority 90 — Local state_root consistency + tip ownership completion ✅ (v1.3.135)

- [x] Known-header `expected_state_root` / historical `expected_head` on state_root waiters
- [x] Handshake height-ahead + status capped ⇒ refuse fantasy `peer.head`
- [x] Shared `_cap_claimed_peer_height`
- Remaining: merkle tip proof / fork-choice / libp2p / ceremony (not claimed)

### Priority 91 — Soft attestation slot-ahead ownership gate ✅ (v1.3.136)

- [x] Refuse `MSG_ATTESTATION` when slot/target_height > local tip/slot + max_ahead
- [x] No LMD apply / relay on far-ahead votes (`p2p_max_attestation_slot_ahead`)
- Remaining: tip proof / libp2p (not claimed)

### Priority 92 — Attestation local-head + solicit-only block responses ✅ (v1.3.137)

- [x] Known `target_hash` ⇒ `target_height` must match local header
- [x] Unsolicited `MSG_BLOCKS` / `MSG_BLOCK` struck (waiter-only like mempool)
- Remaining: tip proof / libp2p / ceremony (not claimed)

### Priority 93 — Solicit-only state_root + ceremony status in check_all ✅ (v1.3.138)

- [x] Unsolicited `MSG_STATE_ROOT_RESPONSE` struck; no consistency mutation
- [x] `scripts/ceremony_status.py` + `check_all.ps1` informational step (never invents pin)
- Remaining: operator `GENESIS_CEREMONY_HASH` / external audit / tip proof / libp2p (not claimed)

### Priority 94 — Catch-up requires peer.head ✅ (v1.3.139)

- [x] Refuse height-only catch-up / `_schedule_sync` when ahead without `peer.head`
- [x] `p2p_catch_up_require_head` (default true)
- Remaining: tip existence proof / fork-choice / libp2p / ceremony (not claimed)

### Priority 95 — SyncEngine never invents peer.head ✅ (v1.3.140)

- [x] `request_heads` skips empty heads (no local `get_block(peer.height)` invent)
- [x] Telemetry `heads_skipped_no_head` + check_all evidence tag refresh
- Remaining: tip proof / fork-choice / libp2p / ceremony (not claimed)

### Priority 96 — sync_state same-height match wire-only ✅ (v1.3.141)

- [x] Remove local `get_block(peer_height)` invent loop in `sync_state`
- [x] `native_sync_state_wire_only` status + metrics
- Remaining: tip proof / fork-choice / libp2p / ceremony (not claimed)

### Priority 96b — Standard pytest solicit-only needle ✅ (v1.3.142)

- [x] Honesty needle aligned with unsolicited state_root strike (not legacy match log)
- Remaining: tip proof / fork-choice / libp2p / ceremony (not claimed)

### Priority 97 — Mempool cheap-refuse + new_tx primary rate ✅ (v1.3.143)

- [x] Remove `new_tx` from RATE_LIMIT_EXEMPT (Python + Rust DEFAULT_EXEMPT)
- [x] Dup-hash refuse before validate; sig-before-DB; `chain_prevalidated` on P2P add
- Remaining: anti-Sybil QoS / fee-market / Long-Range checkpoint / full Rocks rewrite / tip proof / libp2p (not claimed)

### Priority 98 — Native solicit-armed mempool shell ✅ (v1.3.144)

- [x] `mempool_solicit_armed` on `read_message_loop_events` — unarmed skips batch ECDSA
- [x] `_mempool_solicit_armed_for` wires pull waiters only
- Remaining: anti-Sybil / tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 99 — Peer score quality (strikes + import fails) ✅ (v1.3.145)

- [x] `_peer_health_score` penalties for strikes / import_fails
- [x] Failed imports attributed to sourcing peer; eclipse/evict use `_score_peer`
- Remaining: tip proof / hard isolation / Long-Range / libp2p / ceremony (not claimed)

### Priority 100 — Catch-up tip probe + head↔height bind ✅ (v1.3.146)

- [x] Known local `peer.head` ⇒ claimed height must match
- [x] Solicit local-tip `state_root` before ahead `get_blocks` (`p2p_catch_up_tip_probe`)
- Remaining: tip proof / Long-Range checkpoint / libp2p / ceremony (not claimed)

### Priority 101 — Typed Rocks account-row codec ✅ (v1.3.147)

- [x] Native `ABAR` pack/unpack + dual-read (binary or legacy JSON)
- [x] Writeback / state-root / account_view / RocksStore hot path
- Remaining: block/tx blob migration / full Rocks rewrite / tip proof / libp2p / ceremony (not claimed)

### Priority 102 — Typed Rocks tx-row codec ✅ (v1.3.148)

- [x] Native `ATXV` pack/unpack + dual-read (binary or legacy JSON)
- [x] `_insert_transaction` / get / scan / reorg dual-decode
- Remaining: block blob (`ABLK`) / receipts / full Rocks rewrite / tip proof / libp2p / ceremony (not claimed)

### Priority 103 — Typed Rocks block-row codec ✅ (v1.3.149)

- [x] Native `ABLK` pack/unpack + dual-read (typed header + JSON txs/extras)
- [x] `_insert_block` / get / latest / reorg dual-decode
- Remaining: receipts (`ATXR`) / full nested-tx binary / full Rocks rewrite / tip proof / libp2p / ceremony (not claimed)

### Priority 104 — Standard pytest honesty needles ✅ (v1.3.150)

- [x] Align `new_tx` rate-limit test with v1.3.143 (not exempt)
- [x] Align Rocks point-get needles with ATXV/ABLK dual-read helpers
- Remaining: receipts / tip proof / libp2p / ceremony (not claimed)

### Priority 105 — Typed Rocks receipt-row codec ✅ (v1.3.151)

- [x] Native `ATXR` pack/unpack + dual-read (binary or legacy JSON)
- [x] `_insert_tx_receipt` / get / reorg dual-decode
- Remaining: tip proof / Long-Range / libp2p / ceremony / full Rocks rewrite (not claimed)

### Priority 106 — Solicit-only discovery peers ✅ (v1.3.152)

- [x] Refuse unsolicited `MSG_PEERS` (`unsolicited_peers`) — no dial/remember
- [x] `_discovery_loop` pull-armed via `_wait_peer_response` + `_ingest_discovered_peers`
- Remaining: tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 107 — NEW_BLOCK head↔height bind ✅ (v1.3.153)

- [x] Known local announce hash ⇒ claimed height must match (`new_block_head_height_mismatch`)
- [x] Config `p2p_new_block_head_height_bind` (default on)
- Remaining: catch-up peer-head wire probe / tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 108 — Catch-up peer-head wire probe ✅ (v1.3.154)

- [x] Before ahead `get_blocks`, solicit `peer.head` via `get_block_by_hash`
- [x] Refuse `catch_up_peer_head_probe_failed` / `_hash_mismatch` / `_height_mismatch`
- [x] Config `p2p_catch_up_peer_head_probe` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 109 — STATUS/handshake head↔height bind ✅ (v1.3.155)

- [x] Known local `head_hash` ⇒ claimed height must match (`status_head_height_mismatch` / `handshake_head_height_mismatch`)
- [x] Config `p2p_status_head_height_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 110 — NEW_BLOCK defer tip + announce↔body bind ✅ (v1.3.156)

- [x] Parse `Block.from_dict` before mutating peer tip
- [x] Refuse `new_block_announce_hash_mismatch` / `new_block_announce_height_mismatch`
- [x] Config `p2p_new_block_announce_body_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 111 — Catch-up contiguous peer-head parent bind ✅ (v1.3.157)

- [x] When peer is exactly `local+1`, probed head `parent_hash` must match local tip
- [x] Refuse `catch_up_peer_head_parent_mismatch`
- [x] Config `p2p_catch_up_peer_head_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony (not claimed)

### Priority 112 — JWT HS256 min 32-byte secret ✅ (v1.3.158)

- [x] Refuse mint/verify when `JWT_SECRET` < 32 bytes (`MIN_HS256_SECRET_BYTES`)
- [x] Prod `Config.validate` JWT weak check uses `min_len=32`
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 113 — Height-cap clears fantasy peer.head ✅ (v1.3.159)

- [x] STATUS / NEW_BLOCK / handshake: capped height ⇒ clear `peer.head`
- [x] Config `p2p_height_cap_clear_head` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 114 — NEW_BLOCK contiguous parent bind ✅ (v1.3.160)

- [x] When announce is exactly `local+1`, `parent_hash` must match local tip
- [x] Refuse `new_block_contiguous_parent_mismatch` before tip mutate
- [x] Config `p2p_new_block_contiguous_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 115 — STATUS head requires positive height ✅ (v1.3.161)

- [x] Head-only STATUS (`height<=0`) refused when local tip `> 0` (`status_head_without_height`)
- [x] Config `p2p_status_head_requires_height` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 116 — Fork peer-head wire probe ✅ (v1.3.162)

- [x] Before same-height fork reorg, solicit `peer.head` via `get_block_by_hash`
- [x] Refuse `fork_no_head` / `fork_peer_head_probe_failed` / hash / height mismatch
- [x] Config `p2p_fork_peer_head_probe` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 117 — Reconcile fetched head hash bind ✅ (v1.3.163)

- [x] After fetch for `target_head`, refuse reorg if body hash ≠ target (`reconcile_head_hash_mismatch`)
- [x] Covers GHOST + fork paths via `_reconcile_to_head_hash`
- [x] Config `p2p_reconcile_head_hash_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 118 — GHOST head wire probe ✅ (v1.3.164)

- [x] Before GHOST reorg, solicit canonical head via `get_block_by_hash`
- [x] Refuse `ghost_no_head` / `ghost_head_probe_failed` / hash / height mismatch
- [x] Config `p2p_ghost_head_probe` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 119 — Reconcile contiguous parent bind ✅ (v1.3.165)

- [x] When fetched head is exactly `local+1`, `parent_hash` must match local tip
- [x] Refuse `reconcile_contiguous_parent_mismatch`
- [x] Config `p2p_reconcile_contiguous_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 120 — Handshake head requires positive height ✅ (v1.3.166)

- [x] Head-only handshake (`height<=0`) refused when local tip `> 0` (`handshake_head_without_height`)
- [x] Config `p2p_handshake_head_requires_height` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 121 — Attestation tip target-head bind ✅ (v1.3.167)

- [x] Tip-height attestation must cite local tip hash (`attestation_target_head_mismatch`)
- [x] Config `p2p_attestation_target_head_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 122 — Fork peer-head parent bind ✅ (v1.3.168)

- [x] After same-height fork peer.head probe, parent must match tip-height parent
- [x] Refuse `fork_peer_head_parent_mismatch`
- [x] Config `p2p_fork_peer_head_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 123 — GHOST head parent bind ✅ (v1.3.169)

- [x] After GHOST head probe, parent must match tip-height parent
- [x] Refuse `ghost_head_parent_mismatch`
- [x] Config `p2p_ghost_head_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 124 — NEW_BLOCK same-height parent bind ✅ (v1.3.170)

- [x] Same-height announce parent must match tip-height parent before tip mutate
- [x] Refuse `new_block_same_height_parent_mismatch`
- [x] Config `p2p_new_block_same_height_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 125 — Reconcile same-height parent bind ✅ (v1.3.171)

- [x] Same-height fetched head parent must match tip-height parent before reorg
- [x] Refuse `reconcile_same_height_parent_mismatch`
- [x] Config `p2p_reconcile_same_height_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 126 — Catch-up tip-head bind ✅ (v1.3.172)

- [x] After catch-up to `peer.height`, local tip hash must match `peer.head`
- [x] Refuse `catch_up_tip_head_mismatch` (import-loop + post-loop)
- [x] Config `p2p_catch_up_tip_head_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 127 — Reconcile tip-head bind ✅ (v1.3.173)

- [x] After reconcile reorg/import, local tip hash must match `target_head`
- [x] Refuse `reconcile_tip_head_mismatch`
- [x] Config `p2p_reconcile_tip_head_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 128 — NEW_BLOCK tip-head bind ✅ (v1.3.174)

- [x] After gossip import at announce height, local tip hash must match announce hash
- [x] Refuse `new_block_tip_head_mismatch` (no attest / no rebroadcast)
- [x] Config `p2p_new_block_tip_head_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 129 — Catch-up contiguous parent bind ✅ (v1.3.175)

- [x] Catch-up `get_blocks` import at tip+1 must cite local tip as parent
- [x] Refuse `catch_up_contiguous_parent_mismatch`
- [x] Config `p2p_catch_up_contiguous_parent_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 130 — Catch-up height continuity bind ✅ (v1.3.176)

- [x] Catch-up import body height must equal expected sync cursor
- [x] Refuse `catch_up_height_continuity_mismatch` (refuse-before-mutate under DoS)
- [x] Config `p2p_catch_up_height_continuity_bind` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 131 — Mempool min-fee refuse before validate ✅ (v1.3.177)

- [x] P2P wire txs with `fee < mempool.min_fee` refused before `validate_transaction`
- [x] Refuse `fee_too_low` (cheap DoS path; not Rust gas priority queue)
- [x] Config `p2p_mempool_min_fee_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 132 — GET_MEMPOOL tip-align serve gate ✅ (v1.3.178)

- [x] Inbound `GET_MEMPOOL` dump refused when peer tip far from local (`±max_delta`, default 2)
- [x] Refuse `get_mempool_tip_misaligned` (empty response; no 200-tx serialization)
- [x] Config `p2p_mempool_serve_tip_align` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 133 — Mempool max-gas refuse before validate ✅ (v1.3.179)

- [x] P2P wire txs with `gas > evm_gas_limit` refused before `validate_transaction`
- [x] Refuse `gas_too_high` (cheap DoS path; not Rust gas priority queue)
- [x] Config `p2p_mempool_max_gas_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 134 — GET_BLOCKS future-height refuse ✅ (v1.3.180)

- [x] Inbound `GET_BLOCKS` with `from_height > local tip` gets empty reply
- [x] Refuse `get_blocks_future_height` (no fantasy-future empty loop)
- [x] Config `p2p_get_blocks_future_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 135 — GET_BLOCK future-height refuse ✅ (v1.3.181)

- [x] Inbound `GET_BLOCK` with `height > local tip` gets null reply
- [x] Refuse `get_block_future_height` (no DB fetch for fantasy height)
- [x] Config `p2p_get_block_future_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 136 — GET_BLOCKS past-tip end clamp ✅ (v1.3.182)

- [x] Inbound `GET_BLOCKS` with `to_height > local tip` clamps inclusive end to tip
- [x] Clamp reason `get_blocks_past_tip_clamp` (no DB fetch above tip)
- [x] Config `p2p_get_blocks_past_tip_clamp` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 137 — Mempool max-calldata refuse before validate ✅ (v1.3.183)

- [x] P2P wire txs with oversized calldata refused before `validate_transaction`
- [x] Refuse `calldata_too_large` (cheap DoS path; default 128 KiB)
- [x] Config `p2p_mempool_max_calldata_refuse` / `p2p_mempool_max_calldata_bytes` (default on / 131072)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 138 — Mempool negative-value refuse before validate ✅ (v1.3.184)

- [x] P2P wire txs with `value < 0` refused before `validate_transaction`
- [x] Refuse `value_negative` (cheap DoS path; not amount-cap economics)
- [x] Config `p2p_mempool_negative_value_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 139 — Mempool negative-nonce refuse before validate ✅ (v1.3.185)

- [x] P2P wire txs with `nonce < 0` refused before `validate_transaction`
- [x] Refuse `nonce_negative` (cheap DoS path; not account-nonce window)
- [x] Config `p2p_mempool_negative_nonce_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 140 — Mempool negative-fee refuse before validate ✅ (v1.3.186)

- [x] P2P wire txs with `fee < 0` refused before `validate_transaction`
- [x] Refuse `fee_negative` (cheap DoS path; complements fee_too_low when min_fee==0)
- [x] Config `p2p_mempool_negative_fee_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 141 — Mempool negative-gas refuse before validate ✅ (v1.3.187)

- [x] P2P wire txs with `gas < 0` refused before `validate_transaction`
- [x] Refuse `gas_negative` (cheap DoS path; complements gas_too_high)
- [x] Config `p2p_mempool_negative_gas_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 142 — Mempool empty-from refuse before validate ✅ (v1.3.188)

- [x] P2P wire txs with empty/whitespace `from` refused before `validate_transaction`
- [x] Refuse `from_empty` (cheap DoS path; not address checksum)
- [x] Config `p2p_mempool_empty_from_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 143 — Mempool empty-signature refuse before validate ✅ (v1.3.189)

- [x] P2P wire txs with empty/whitespace `signature` refused before `validate_transaction`
- [x] Refuse `signature_empty` (cheap DoS path; not full ECDSA verify)
- [x] Config `p2p_mempool_empty_sig_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 144 — Mempool empty-pubkey refuse before validate ✅ (v1.3.190)

- [x] P2P wire txs with empty/whitespace `public_key` refused before `validate_transaction`
- [x] Refuse `pubkey_empty` (cheap DoS path; not key-format validation)
- [x] Config `p2p_mempool_empty_pubkey_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 145 — Mempool max-signature refuse before validate ✅ (v1.3.191)

- [x] P2P wire txs with oversized `signature` refused before `validate_transaction`
- [x] Refuse `signature_too_large` (cheap DoS path; default 2048 bytes)
- [x] Config `p2p_mempool_max_sig_refuse` / `p2p_mempool_max_sig_bytes` (default on / 2048)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 146 — Mempool max-pubkey refuse before validate ✅ (v1.3.192)

- [x] P2P wire txs with oversized `public_key` refused before `validate_transaction`
- [x] Refuse `pubkey_too_large` (cheap DoS path; default 2048 bytes)
- [x] Config `p2p_mempool_max_pubkey_refuse` / `p2p_mempool_max_pubkey_bytes` (default on / 2048)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 147 — Mempool non-finite value refuse before validate ✅ (v1.3.193)

- [x] P2P wire txs with NaN/Inf `value` refused before `validate_transaction`
- [x] Refuse `value_non_finite` (cheap DoS path; complements value_negative)
- [x] Config `p2p_mempool_nonfinite_value_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 148 — Mempool non-finite fee refuse before validate ✅ (v1.3.194)

- [x] P2P wire txs with NaN/Inf `fee` refused before `validate_transaction`
- [x] Refuse `fee_non_finite` (cheap DoS path; complements fee_negative)
- [x] Config `p2p_mempool_nonfinite_fee_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 149 — Mempool empty-to refuse before validate ✅ (v1.3.195)

- [x] P2P wire txs with empty/whitespace `to` / `to_addr` refused before `validate_transaction`
- [x] Refuse `to_empty` (cheap DoS path; mirrors from_empty / missing_address)
- [x] Config `p2p_mempool_empty_to_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 150 — Mempool empty-hash refuse before validate ✅ (v1.3.196)

- [x] P2P wire txs with empty/whitespace `hash` / `tx_hash` refused before `validate_transaction`
- [x] Refuse `hash_empty` (cheap DoS path; empty hash skips duplicate_tx)
- [x] Config `p2p_mempool_empty_hash_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 151 — Mempool max-hash refuse before validate ✅ (v1.3.197)

- [x] P2P wire txs with oversized `hash` / `tx_hash` refused before `validate_transaction`
- [x] Refuse `hash_too_large` (cheap DoS path; default 128 chars, aligns MAX_P2P_HASH_LEN)
- [x] Config `p2p_mempool_max_hash_refuse` / `p2p_mempool_max_hash_chars` (default on / 128)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 152 — Mempool max-from refuse before validate ✅ (v1.3.198)

- [x] P2P wire txs with oversized `from` / `from_addr` refused before `validate_transaction`
- [x] Refuse `from_too_large` (cheap DoS path; default 128 chars, aligns MAX_P2P_ADDR_LEN)
- [x] Config `p2p_mempool_max_from_refuse` / `p2p_mempool_max_addr_chars` (default on / 128)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 153 — Mempool max-to refuse before validate ✅ (v1.3.199)

- [x] P2P wire txs with oversized `to` / `to_addr` refused before `validate_transaction`
- [x] Refuse `to_too_large` (cheap DoS path; shares max_addr_chars / MAX_P2P_ADDR_LEN)
- [x] Config `p2p_mempool_max_to_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 154 — Mempool max-nonce refuse before validate ✅ (v1.3.200)

- [x] P2P wire txs with oversized `nonce` refused before `validate_transaction`
- [x] Refuse `nonce_too_high` (cheap DoS path; default 1e12, MAX_P2P_HEIGHT-style)
- [x] Config `p2p_mempool_max_nonce_refuse` / `p2p_mempool_max_nonce` (default on / 1e12)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 155 — Mempool max-fee refuse before validate ✅ (v1.3.201)

- [x] P2P wire txs with oversized `fee` refused before `validate_transaction`
- [x] Refuse `fee_too_high` (cheap DoS path; default 1e9 ABS; complements fee_too_low)
- [x] Config `p2p_mempool_max_fee_refuse` / `p2p_mempool_max_fee` (default on / 1e9)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 156 — Mempool max-value refuse before validate ✅ (v1.3.202)

- [x] P2P wire txs with oversized `value` refused before `validate_transaction`
- [x] Refuse `value_too_high` (cheap DoS path; default 221M ABS, aligns max_supply)
- [x] Config `p2p_mempool_max_value_refuse` / `p2p_mempool_max_value` (default on / 221M)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 157 — Mempool unparseable-gas refuse before validate ✅ (v1.3.203)

- [x] P2P wire txs with Inf/junk `gas` refused before `validate_transaction`
- [x] Refuse `gas_unparseable` (cheap DoS path; no OverflowError into ingest)
- [x] Config `p2p_mempool_unparseable_gas_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 158 — Mempool unparseable-value refuse before validate ✅ (v1.3.204)

- [x] P2P wire txs with junk `value` / `amount` refused before `validate_transaction`
- [x] Refuse `value_unparseable` (cheap DoS path; no TypeError into ingest)
- [x] Config `p2p_mempool_unparseable_value_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

### Priority 159 — Mempool unparseable-nonce refuse before validate ✅ (v1.3.205)

- [x] P2P wire txs with junk / Inf `nonce` refused before `validate_transaction`
- [x] Refuse `nonce_unparseable` (cheap DoS path; no OverflowError into ingest)
- [x] Config `p2p_mempool_unparseable_nonce_refuse` (default on)
- Remaining: tip proof / Long-Range / libp2p / ceremony pin / external audit (not claimed)

## Process per module

1. Python tests + golden vectors first.
2. Rust implementation with identical behavior + PyO3 export.
3. CI: build wheel + targeted pytest in `check_hybrid_full`.
4. Enable in prod via `require_native_crypto: true`.
5. Monitor `/metrics` native crypto gauges.

## Safety flags

| Env / config | Effect |
|--------------|--------|
| `ABS_REQUIRE_NATIVE_CRYPTO=true` | Node fails closed without `abs_native` wheel |
| `ABS_DISABLE_NATIVE_CRYPTO=true` | Force Python fallback (dev only) |
| `BRIDGE_MODE=rust` + `BRIDGE_REQUIRE_L1_PROOF=true` | No simulator, real L1 RPC required |
| `deployment_mode=prod` | `scripts/prod_gate.py` static checks |

## What is NOT a simulator (prod-safe)

- Rust `abs_native` — real crypto, same outputs as Python reference
- Rust `rust_bridge` — real JSON-RPC to external chains
- P2P sync — real TCP mesh, Docker devnet 2/3/5 nodes
- SQLite persistence — `synchronous=FULL` in prod

## What stays dev-only (blocked in prod)

- `bridge_mode=simulator`
- `feature_zk`, `feature_lightning`, `feature_pq`, etc.
- `mock_l1_rpc`, `auto_sign` on `/tx/send`
- Post-quantum private-key helper endpoints

---

## Priority 10 — Mempool / validation Rust (planned, ADR 0021)

**Status:** **Phase 0 landed** (`MempoolPort` + `tests/unit/test_mempool_port.py`). Phases 1–3 **unblocked** after [EXECUTION_ORDER.md](EXECUTION_ORDER.md) Phase 1 libp2p 48h PASS ([`3c801b87`](evidence/runs/3c801b87/)) — implementation not started.

| Sub-phase | Deliverable | Behavior change |
|-----------|-------------|-----------------|
| 0 | `blockchain/ports.py` `MempoolPort` | None (protocol + structural test) |
| 1 | Rust validation kernels + snapshot from Python | Optional fast path |
| 2 | Rust priority store behind port | Perf after parity proof |
| 3 | EVM deploy admit (Rust or callback) | Golden vs Python validator |

Detail: [adr/0021-mempool-validation-rust-phases.md](adr/0021-mempool-validation-rust-phases.md).

**Already in Rust (do not re-implement):** P2P wire shape, batch ECDSA, solicit-only mempool shell, rate limits — see `p2p_transport.rs` / `p2p_wire.rs`.

