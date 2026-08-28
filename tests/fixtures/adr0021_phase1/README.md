# ADR 0021 phase 1 — golden fixtures (Python-only, pre-Rust)

**Status:** schema + examples only — **no Rust kernel until libp2p 48h PASS.**

These JSON files document the read-only snapshot contract and expected kernel
outcomes for future `mempool_kernel` PyO3 work. They do **not** change runtime
behavior.

| File | Role |
|------|------|
| `snapshot_minimal.json` | Canonical snapshot shape `{nonce, balance_sat}` |
| `kernel_input_accept.json` | Valid transfer after sig verify |
| `kernel_input_refuse_nonce.json` | Nonce mismatch → refuse |
| `kernel_input_refuse_balance.json` | Insufficient satoshi → refuse |
| `pipeline_refuse_deploy_eof.json` | Phase 3 golden: EOF bytecode → pipeline refuse |
| `pipeline_refuse_deploy_bad_opcode.json` | Phase 3 golden: unsupported opcode |
| `invariant_sig_before_snapshot.json` | Phase 1 ordering invariant (docs only) |

Invariant: snapshot is supplied **after** signature verification; Rust must not
open StoragePort / RocksDB.

Phase 3 deploy fixtures are **golden references** for future Rust admit — Python
`TxPipeline._validate_evm_deploy_bytecode` remains canonical until phase 3 ships.

See [docs/adr/0021-mempool-validation-rust-phases.md](../../../docs/adr/0021-mempool-validation-rust-phases.md).
