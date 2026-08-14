# Profile F — Experimental R&D (Gruver87/experimental)

Lab-only profile for this sandbox repo. **Never** enable on audit-pin
`778888` industrial mesh JSON.

| Flag | Env | Default | Purpose |
|------|-----|---------|---------|
| `feature_libp2p` | `FEATURE_LIBP2P` | **false** | Dual-stack libp2p transport (ADR 0018); TCP+TLS remains default |
| `feature_long_range` | `FEATURE_LONG_RANGE` | **false** | Weak-subjectivity / Long-Range research (ADR 0017) |

## Transport honesty

- **Default:** native TCP + TLS/mTLS mesh (ADR 0002).
- **libp2p:** opt-in only when `FEATURE_LIBP2P=true` (dev/lab). Industrial compose keeps the flag **off**.

## EVM depth

EVM stays on Profile A apply path ([EVM_DEPTH.md](EVM_DEPTH.md)).
Compatibility gaps: [EVM_COMPAT_MATRIX.md](EVM_COMPAT_MATRIX.md).

## Gates

- `scripts/industrial_gate.py` requires `feature_libp2p=false` and `feature_long_range=false` on prod mesh JSON.
- Lab scripts: `scripts/long_range_lab.py`, `scripts/libp2p_lab_smoke.py`,
  `scripts/libp2p_two_node_lab.py`, `scripts/libp2p_swarm_lab.py`,
  `scripts/libp2p_three_node_lab.py`,   `scripts/libp2p_reqresp_lab.py`,
  `scripts/libp2p_relay_lab.py`, `scripts/libp2p_discovery_lab.py`,
  `scripts/libp2p_identify_lab.py`, `scripts/evm_precompile_lab.py`,
  `scripts/verify_experimental_rd.py`, `scripts/libp2p_rust_two_node_lab.py`,
  `scripts/libp2p_rust_wire_lab.py`, `scripts/libp2p_rust_gossip_lab.py`,
  `scripts/package_libp2p_evidence.py`
  (rust labs require `maturin build --features pyo3/extension-module,libp2p`).
- Rust industrial path: [ADR 0019](../adr/0019-rust-libp2p-industrial.md) Slices **A–CP** (phase 93).
- Hard gate: `scripts/verify_adr0019_libp2p_hard.ps1` (± `-Rebuild`).
- `cargo test` for `abs_native` must link CPython (`scripts/cargo_test_abs_native.py`);
  crate default `extension-module` is wheel-only and does **not** link libpython.
- Unified Hybrid+Experimental operator view: `scripts/verify_absolute_unified.ps1`.
- Long-Range tip gate (when `FEATURE_LONG_RANGE=true`): optional
  `ABS_WS_ANCHOR_HEIGHT` + `ABS_WS_ANCHOR_HASH` on tip-safety shadow sync.
  Without an anchor, tip import is **not** blocked (`no_anchor` is informational).

See [EXPERIMENTAL_SANDBOX.md](../../EXPERIMENTAL_SANDBOX.md).
