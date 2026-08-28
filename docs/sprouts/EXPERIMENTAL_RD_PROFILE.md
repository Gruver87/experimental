# Profile F — Experimental R&D (Gruver87/experimental)

Lab-only profile for Long-Range. libp2p on Experimental `778888` mesh is
**ADR 0020** (not Hybrid audit-pin).

| Flag | Env | Default | Purpose |
|------|-----|---------|---------|
| `feature_libp2p` | `FEATURE_LIBP2P` | **true on Experimental mesh JSON** | rust-libp2p industrial mesh (ADR 0020); Hybrid pin stays false |
| `feature_long_range` | `FEATURE_LONG_RANGE` | **false** | Weak-subjectivity / Long-Range research (ADR 0017) |

## Transport honesty

- **Experimental industrial mesh:** rust-libp2p Noise/Yamux + ADR 0008 `/abs/wire` (ADR 0020).
- **Hybrid audit-pin:** native TCP + TLS/mTLS (unchanged).
- **Long-Range:** stays off on prod mesh JSON. Lab arm: `feature_long_range=true` (dev) or `FEATURE_LONG_RANGE` env + `ABS_WS_CHECKPOINT_PATH`.
- **Execution order:** [EXECUTION_ORDER.md](../EXECUTION_ORDER.md) — libp2p 48h → LR lab soak → EVM regression → mempool Rust (ADR 0021).

## EVM depth

EVM stays on Profile A apply path ([EVM_DEPTH.md](EVM_DEPTH.md)).
Compatibility gaps: [EVM_COMPAT_MATRIX.md](EVM_COMPAT_MATRIX.md).

## Gates

- `scripts/industrial_gate.py` requires Experimental mesh JSON `feature_libp2p=true` and `feature_long_range=false`.
- Lab scripts: `scripts/long_range_lab.py`, `scripts/long_range_p2p_lab.py`, `scripts/long_range_gossip_lab.py`, `scripts/long_range_lab_2h_harness.py` (preflight; 2h not auto-started), `scripts/evm_precompile_lab.py`, `scripts/evm_rpc_lab.py`, `scripts/evm_nested_lab.py`, `scripts/evm_reorg_lab.py`, `scripts/evm_logs_lab.py`, `scripts/oracle_lab.py`, `scripts/cross_shard_lab.py`, `scripts/libp2p_lab_smoke.py`,
  `scripts/libp2p_two_node_lab.py`, `scripts/libp2p_swarm_lab.py`,
  `scripts/libp2p_three_node_lab.py`,   `scripts/libp2p_reqresp_lab.py`,
  `scripts/libp2p_relay_lab.py`, `scripts/libp2p_discovery_lab.py`,
  `scripts/libp2p_identify_lab.py`,
  `scripts/verify_experimental_rd.py`, `scripts/verify_parallel_rd_batch.py`,
  `scripts/libp2p_rust_two_node_lab.py`,
  `scripts/libp2p_rust_wire_lab.py`, `scripts/libp2p_rust_gossip_lab.py`,
  `scripts/package_libp2p_evidence.py`
  (rust labs require `maturin build --features pyo3/extension-module,libp2p`).
- Rust industrial path: [ADR 0019](../adr/0019-rust-libp2p-industrial.md) Slices **A–DB** (phase 105).
- Hard gate: `scripts/verify_adr0019_libp2p_hard.ps1` (± `-Rebuild`).
- `cargo test` for `abs_native` must link CPython (`scripts/cargo_test_abs_native.py`);
  crate default `extension-module` is wheel-only and does **not** link libpython.
- Unified Hybrid+Experimental operator view: `scripts/verify_absolute_unified.ps1`.
- Long-Range tip gate (when `FEATURE_LONG_RANGE=true`): persist
  `ABS_WS_CHECKPOINT_PATH` (height+hash JSON) across restart. Optional
  `ABS_WS_ANCHOR_HEIGHT` + `ABS_WS_ANCHOR_HASH` seed an empty store once and
  are written to that path. Armed without an anchor is **HARD REFUSE**
  (`ws_no_anchor`). Candidate history below the anchor is **HARD REFUSE**.
  Not a live finality quorum. Industrial JSON keeps the flag **false**.

See [EXPERIMENTAL_SANDBOX.md](../../EXPERIMENTAL_SANDBOX.md).
