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
| `eth_estimateGas` | **Supported** | Includes create (`to` empty) path |
| `eth_getTransactionReceipt` | **Partial** | Core fields + logs + **logsBloom from address/topics**. `cumulativeGasUsed` is the running sum of `gas_used` in block tx order (QueryFacade `get_block`); without a block listing it equals this receipt's `gasUsed`. `blockHash` / `blockNumber` come from the tx row or block listing — **never** the 32-byte zero digest or height `0` for a missing inclusion (`null` if unobserved) |
| `eth_getBlockByNumber` / `ByHash` | **Partial** | Header fields + **block `logsBloom` reconstructed from log index** (OR of address/topics; cap 10k logs/block). `gasUsed` is stored header or the sum of observed tx `gas_used` (matches last-receipt `cumulativeGasUsed` when the full list is observed). `extraData` is the stored header (UTF-8 hex if not already 0x). `uncles` is the observed list (Absolute has none). `transactionsRoot` / `receiptsRoot` are **Absolute SHA256 merkle** (same leaf rule as `Block.tx_root` / hash:status receipts) — **not** Ethereum Hexary MPT. `sha3Uncles` is Yellow Paper `keccak256(rlp([]))` when the uncle list is empty; Absolute has no uncle headers |
| `eth_getBlockTransactionCount*` / `eth_getUncleCount*` | **Partial** | Count of the observed block. **Missing block is JSON `null`**, not `0x0` (that would look like an empty block exists) |
| `eth_getUncleByBlock*AndIndex` | **Partial** | JSON `null` when the parent block is missing, the index is out of range, or the uncle is hash-only without a stored header. Does not invent a header. Absolute has no uncle blocks |
| `eth_feeHistory` | **Partial** | `gasUsedRatio` is `gasUsed / gasLimit` per observed height (`oldest..tip`, not padded). `baseFeePerGas` is the configured gas price (Absolute is not EIP-1559). `reward` stays `[["0x0"]]` — no tip percentiles |
| Blob txs (EIP-4844) | **Not claimed** | Optional / out of scope |
| EOF | **Not claimed** | Out of scope |
| Full geth JSON-RPC surface | **Not claimed** | Wave-gated methods only |

Evidence: `scripts/prod_evm_smoke.py` · unit tests under `tests/unit/test_evm_rpc_compat.py`.

Update this table when a wave closes a row — never mark Supported without a test.
