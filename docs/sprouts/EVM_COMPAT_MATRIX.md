# EVM compatibility matrix (honest)

Scope: Absolute hybrid EVM subset on the single apply path.  
**Not** a full Ethereum client. Target reference: Shanghai / Cancun opcodes where noted.

| Area | Status | Notes |
|------|--------|-------|
| Transfer + fee burn | **Supported** | Native apply + satoshi domain. Nested CALL writeback `transfer_value` refuses `insufficient_writeback_value` (no clamp-to-zero mint). Host `deploy_contract` / `call_contract` value is one debit+credit via `try_debit_satoshi` |
| CREATE / CREATE2 + deploy salt | **Supported (prod)** | `evm_create2_eip1014` + `evm_require_deploy_salt`. Endowment is on the account before init (constructor can forward value); revert refunds |
| CALL / STATICCALL host | **Partial** | Host-in-apply; nested depth cap 4. Inline CALL `RETURNDATACOPY` uses the live return buffer. Inline STATICCALL refuses SSTORE/LOG/CREATE/TSTORE/SELFDESTRUCT and value-CALL. Nested CALL/DELEGATECALL under STATICCALL is sticky (EIP-214): SSTORE does not commit. Nested OOG burns all forwarded gas (REVERT does not). Python interpreter handoff also refuses static writes. Nested CALL to empty code (EOA) succeeds with empty returndata; value still transfers when the caller covers satoshi (otherwise CALL returns 0, no mint). No-code writeback does not persist empty storage (DELEGATECALL to a precompile must not wipe the caller) |
| Precompiles (ecrecover, sha256, …) | **Partial** | **0x01–0x09** via `execution/evm_precompiles.py` on eth_call, nested CALL/STATICCALL, `call_contract`, and host apply (`_run_evm_host_only`). Tx `to` a precompile is a message-call, not CREATE. `ecrecover` pads/truncates to 128 bytes (geth `getData`). Failed precompile CALL burns forwarded gas. Identity/SHA256/RIPEMD/MODEXP/BN254/BLAKE2F gas tables are Yellow Paper / Istanbul / EIP-2565 / EIP-152. Curve edge cases may still diverge from geth |
| `eth_call` | **Supported** | Hex ABI word encoding + precompile bytes |
| `eth_estimateGas` | **Supported (Absolute honesty)** | Adapter estimate when present. No 21000 floor. Missing adapter / adapter `None` → JSON `null` (`evm_rpc_lab` + unit). **Not** geth gas semantics |
| `eth_getTransactionReceipt` | **Supported (Absolute honesty)** | Core fields + logs + **logsBloom from address/topics**. Missing tx → JSON `null`. Missing `gas_used` is `null` — never the `21000` transfer stub. Lab + unit |
| `eth_getLogs` | **Supported (Absolute honesty)** | Rows from the log index. Missing inclusion fields → `null`. Empty range → `[]`. Lab + unit |
| `eth_newFilter` / `eth_getFilterChanges` / `eth_uninstallFilter` | **Supported (Absolute honesty)** | Polling filters (log/block/pending). Missing store → error. Unknown id → `[]`. `getFilterLogs` on log filter. Lab: `evm_filters_lab.py` — **not WS `eth_subscribe`.** |
| `eth_getBlockByNumber` / `ByHash` | **Supported (Absolute honesty)** | Missing block → JSON `null`. Sparse header null-honesty. `fullTx=false` → hash list; `fullTx=true` → stored tx objects. Lab + unit |
| `eth_getBlockTransactionCount*` / `eth_getUncleCount*` | **Supported (Absolute honesty)** | Count of the observed block. **Missing block is JSON `null`**, not `0x0` |
| `eth_getUncleByBlock*AndIndex` | **Supported (Absolute honesty)** | JSON `null` when missing/OOR/hash-only. Absolute has no uncle blocks |
| `eth_feeHistory` | **Supported (Absolute honesty)** | `gasUsedRatio` from observed heights. `baseFeePerGas` / `reward` JSON `null` (not EIP-1559). Lab: `evm_rpc_lab.py` |
| `eth_maxPriorityFeePerGas` | **Supported (Absolute honesty)** | Not EIP-1559 tip market. Unset / `0` → JSON `null` (not `0x0`). Explicit `priority_fee_wei>0` returns hex. Lab + unit |
| `eth_coinbase` / `eth_mining` / `eth_hashrate` | **Supported (Absolute honesty)** | Empty `miner_address` → coinbase `null`. `mining_enabled=false` → `false`. Hashrate always `0x0` — **not** ethash. Lab + unit |
| `eth_getCode` / `eth_getBalance` / `eth_getStorageAt` | **Supported (Absolute honesty)** | Missing account: code `0x`, balance `0x0` wei, storage slot `0x0`. Lab + unit |
| `eth_protocolVersion` | **Supported (Absolute honesty)** | JSON-RPC client compatibility constant `0x41` (65) — **not** Ethereum eth/65 wire |
| `eth_chainId` / `net_version` / `web3_clientVersion` | **Supported (Absolute honesty)** | Config-backed. Lab + unit |
| `eth_syncing` / `net_peerCount` | **Supported (Absolute honesty)** | No P2P/sync adapter → `false` / `0x0`. With peers, follows mesh consistency + wire probe. Lab + unit |
| `eth_gasPrice` | **Supported (Absolute honesty)** | JSON null by default; config floor only when `advertise_config_gas_price=true` (not a live tip). Lab + unit |
| `eth_getTransactionCount` | **Supported (Absolute honesty)** | Observed account nonce; missing → `0x0`. Lab + unit |
| `eth_getTransactionByHash` | **Supported (Absolute honesty)** | Missing tx → JSON `null`. Lab + unit |
| `eth_blockNumber` / `eth_accounts` / `eth_getMempoolSize` | **Supported (Absolute honesty)** | Tip height hex; accounts from wallet/miner only; mempool size hex. Lab + unit |
| `eth_getTransactionByBlockNumberAndIndex` | **Supported (Absolute honesty)** | Missing block or OOR index → JSON `null`. Lab + unit |
| Blob txs (EIP-4844) | **Not claimed** | Optional / out of scope |
| EOF | **Not claimed** | Out of scope |
| Full geth JSON-RPC surface | **Not claimed** | Wave-gated methods only |

Evidence: `scripts/verify_evm_depth_lab.ps1` · pack [`docs/evidence/runs/evmlab1/`](../evidence/runs/evmlab1/) · `scripts/prod_evm_smoke.py` · `scripts/evm_precompile_lab.py` · `scripts/evm_rpc_lab.py` · `scripts/evm_filters_lab.py` · `scripts/evm_nested_lab.py` · `scripts/evm_reorg_lab.py` · `scripts/evm_logs_lab.py` · unit tests under `tests/unit/test_evm_rpc_compat.py`.

Update this table when a wave closes a row — never mark Supported without a test.
