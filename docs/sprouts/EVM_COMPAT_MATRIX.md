# EVM compatibility matrix (honest)

Scope: Absolute hybrid EVM subset on the single apply path.  
**Not** a full Ethereum client. Target reference: Shanghai / Cancun opcodes where noted.

| Area | Status | Notes |
|------|--------|-------|
| Transfer + fee burn | **Supported** | Native apply + satoshi domain |
| CREATE / CREATE2 + deploy salt | **Supported (prod)** | `evm_create2_eip1014` + `evm_require_deploy_salt` |
| CALL / STATICCALL host | **Partial** | Host-in-apply; nested depth cap 4. Inline CALL `RETURNDATACOPY` uses the live return buffer. Inline STATICCALL refuses SSTORE/LOG/CREATE/TSTORE/SELFDESTRUCT and value-CALL. Nested CALL/DELEGATECALL under STATICCALL is sticky (EIP-214): SSTORE does not commit. Nested OOG burns all forwarded gas (REVERT does not). Python interpreter handoff also refuses static writes |
| Precompiles (ecrecover, sha256, …) | **Partial** | **0x01–0x09** via `execution/evm_precompiles.py` on eth_call, nested CALL/STATICCALL, `call_contract`, and host apply (`_run_evm_host_only`). Tx `to` a precompile is a message-call, not CREATE. Gas/curve edge cases may still diverge from geth |
| `eth_call` | **Supported** | Hex ABI word encoding + precompile bytes |
| `eth_estimateGas` | **Supported** | Includes create (`to` empty) path |
| `eth_getTransactionReceipt` | **Partial** | Core fields + logs + **logsBloom from address/topics** |
| `eth_getBlockByNumber` / `ByHash` | **Partial** | Header fields + **block `logsBloom` reconstructed from log index** (OR of address/topics; cap 10k logs/block). `transactionsRoot` / `receiptsRoot` still stub |
| Blob txs (EIP-4844) | **Not claimed** | Optional / out of scope |
| EOF | **Not claimed** | Out of scope |
| Full geth JSON-RPC surface | **Not claimed** | Wave-gated methods only |

Evidence: `scripts/prod_evm_smoke.py` · unit tests under `tests/unit/test_evm_rpc_compat.py`.

Update this table when a wave closes a row — never mark Supported without a test.
