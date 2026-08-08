# EVM compatibility matrix (honest)

Scope: Absolute hybrid EVM subset on the single apply path.  
**Not** a full Ethereum client. Target reference: Shanghai / Cancun opcodes where noted.

| Area | Status | Notes |
|------|--------|-------|
| Transfer + fee burn | **Supported** | Native apply + satoshi domain |
| CREATE / CREATE2 + deploy salt | **Supported (prod)** | `evm_create2_eip1014` + `evm_require_deploy_salt` |
| CALL / STATICCALL host | **Partial** | Host-in-apply; nested depth limited |
| Precompiles (ecrecover, sha256, …) | **Partial** | **0x01–0x05 + 0x09 blake2f** via `execution/evm_precompiles.py` (+ `blake2f.py`); bn254 (0x06–0x08) still open |
| `eth_call` | **Supported** | Hex ABI word encoding + precompile bytes |
| `eth_estimateGas` | **Supported** | Includes create (`to` empty) path |
| `eth_getTransactionReceipt` | **Partial** | Core fields + logs; bloom/type stubs |
| Blob txs (EIP-4844) | **Not claimed** | Optional / out of scope |
| EOF | **Not claimed** | Out of scope |
| Full geth JSON-RPC surface | **Not claimed** | Wave-gated methods only |

Evidence: `scripts/prod_evm_smoke.py` · unit tests under `tests/unit/test_evm_rpc_compat.py`.

Update this table when a wave closes a row — never mark Supported without a test.
